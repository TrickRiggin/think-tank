#!/usr/bin/env python3
"""Think Tank — Multi-model deliberation tool.

Run from any repo directory. Auto-detects CLAUDE.md for context.

Usage:
    think_tank "Your question here"
    think_tank --files src/App.jsx,src/utils.js "How should we refactor?"
    think_tank --deep --crux --rounds 1 "What's our strategy?"
    think_tank --interactive "Let's design a new feature"
"""

import argparse
import html
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


def load_env_files():
    """Load config from .env files (home dir + cwd). No dependencies needed."""
    env_paths = [
        Path.home() / ".env",
        Path.home() / ".think_tank.env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            key_aliases = {
                "OpenRouter": "OPENROUTER_API_KEY",
            }
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        env_name = key_aliases.get(key, key)
                        if env_name and not os.environ.get(env_name):
                            os.environ[env_name] = value
            except Exception:
                pass


load_env_files()

# ── JSON mode (suppress terminal output, collect structured data) ───────────

JSON_MODE = False

def _print(*args, **kwargs):
    """Print wrapper that respects JSON_MODE."""
    if not JSON_MODE:
        print(*args, **kwargs)

# ── Terminal colors ──────────────────────────────────────────────────────────

# Enable ANSI + UTF-8 on Windows
if sys.platform == "win32":
    os.system("")  # triggers VT100 mode
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

C = {
    "claude": "\033[38;5;208m",   # amber/orange
    "gpt":    "\033[38;5;114m",   # green
    "gemini": "\033[38;5;75m",    # blue
    "deepseek": "\033[38;5;45m",   # cyan
    "grok":   "\033[38;5;205m",   # magenta
    "system": "\033[38;5;245m",   # gray
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "reset":  "\033[0m",
    "err":    "\033[38;5;196m",   # red
}

# ── Model config ─────────────────────────────────────────────────────────────

MODELS = {
    "claude": {
        "name":     "Claude Opus 4.7",
        "model_id": "anthropic/claude-opus-4.7",
    },
    "gpt": {
        "name":     "GPT-5.5",
        "model_id": "openai/gpt-5.5",
    },
    "gemini": {
        "name":     "Gemini 3.1 Pro",
        "model_id": "google/gemini-3.1-pro-preview",
    },
    "deepseek": {
        "name":     "DeepSeek V4 Pro",
        "model_id": "deepseek/deepseek-v4-pro",
    },
    "grok": {
        "name":     "Grok 4.20",
        "model_id": "x-ai/grok-4.20",
    },
}

DEFAULT_PANEL = ["claude", "gpt", "gemini", "deepseek"]
DEFAULT_OUTPUT_DIR = Path("output")


def resolve_save_path(save_arg):
    """Resolve --save paths. Bare filenames land in output/ by default."""
    if save_arg in (None, ""):
        return DEFAULT_OUTPUT_DIR / f"think_tank-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"

    save_path = Path(save_arg).expanduser()
    if not save_path.is_absolute() and save_path.parent == Path("."):
        save_path = DEFAULT_OUTPUT_DIR / save_path

    if save_path.suffix.lower() == ".html":
        return save_path.with_suffix(".md")
    if not save_path.suffix:
        return save_path.with_suffix(".md")
    return save_path


def resolve_artifact_paths(save_arg):
    """Return markdown + HTML paths for a transcript save target."""
    md_path = resolve_save_path(save_arg)
    return md_path, md_path.with_suffix(".html")


def html_id(text):
    """Stable-ish anchor id for generated headings."""
    text = re.sub(r"<[^>]+>", "", text)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def inline_markdown_to_html(text):
    """Render small inline Markdown subset without adding dependencies."""
    text = html.escape(text)
    code_spans = []

    def stash_code(match):
        code_spans.append(f"<code>{match.group(1)}</code>")
        return f"@@CODE{len(code_spans) - 1}@@"

    text = re.sub(r"`([^`]+)`", stash_code, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    for idx, value in enumerate(code_spans):
        text = text.replace(f"@@CODE{idx}@@", value)
    return text


def markdown_to_html(markdown_text, heading_offset=1):
    """Render the transcript's Markdown subset into standalone HTML."""
    lines = markdown_text.strip("\n").splitlines()
    output = []
    paragraph = []
    list_tag = None
    in_code = False
    code_lines = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph).strip()
            if text:
                output.append(f"<p>{inline_markdown_to_html(text)}</p>")
            paragraph = []

    def close_list():
        nonlocal list_tag
        if list_tag:
            output.append(f"</{list_tag}>")
            list_tag = None

    for raw_line in lines:
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            if in_code:
                output.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)) + heading_offset, 6)
            title = heading.group(2).strip()
            output.append(
                f'<h{level} id="{html_id(title)}">{inline_markdown_to_html(title)}</h{level}>'
            )
            continue

        if line.startswith(">"):
            flush_paragraph()
            close_list()
            output.append(f"<blockquote>{inline_markdown_to_html(line.lstrip('> ').strip())}</blockquote>")
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            flush_paragraph()
            if list_tag != "ul":
                close_list()
                output.append("<ul>")
                list_tag = "ul"
            output.append(f"<li>{inline_markdown_to_html(bullet.group(1).strip())}</li>")
            continue

        numbered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if numbered:
            flush_paragraph()
            if list_tag != "ol":
                close_list()
                output.append("<ol>")
                list_tag = "ol"
            output.append(f"<li>{inline_markdown_to_html(numbered.group(1).strip())}</li>")
            continue

        if list_tag and line.startswith("   "):
            output.append(f'<p class="list-note">{inline_markdown_to_html(line.strip())}</p>')
            continue

        close_list()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    if in_code:
        output.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(output)


def extract_between(text, start_marker, end_marker=None):
    start = text.find(start_marker)
    if start == -1:
        return ""
    if end_marker is None:
        return text[start:].strip()
    end = text.find(end_marker, start + len(start_marker))
    if end == -1:
        return text[start:].strip()
    return text[start:end].strip()


TRANSCRIPT_HEADING_RE = re.compile(
    r"^## (Crux Frame|Round \d+|Analysis(?: \(Structured Disagreement\))?|"
    r"Review \(Anonymized Peer Ranking\)|Chairman Synthesis|Reveal)\s*$",
    re.MULTILINE,
)


def next_transcript_heading_start(text, start):
    """Find the next Think Tank section heading, ignoring headings inside model prose."""
    match = TRANSCRIPT_HEADING_RE.search(text, start)
    return match.start() if match else len(text)


def extract_section(text, heading):
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    end = next_transcript_heading_start(text, match.end())
    return text[match.start():end].strip()


def extract_title(text):
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "Think Tank Transcript"


def extract_question(text):
    question = extract_between(text, "**Question:**", "**Models:**")
    return question.strip() or "No question captured."


def extract_models(text):
    match = re.search(r"^\*\*Models:\*\*\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "Unknown models"


def extract_executive_summary(markdown_text):
    headings = list(re.finditer(r"^#{2,4}\s+.*Executive Summary.*$", markdown_text, re.MULTILINE | re.IGNORECASE))
    if not headings:
        return ""
    last = headings[-1]
    next_heading = re.search(r"^#{1,4}\s+", markdown_text[last.end():], re.MULTILINE)
    if next_heading:
        return markdown_text[last.start():last.end() + next_heading.start()].strip()
    return markdown_text[last.start():].strip()


def build_html_transcript(transcript_markdown):
    """Build an easy-to-read standalone HTML report from a markdown transcript."""
    title = extract_title(transcript_markdown)
    models = extract_models(transcript_markdown)
    question = extract_question(transcript_markdown)
    crux = extract_section(transcript_markdown, "Crux Frame")
    analysis = extract_section(transcript_markdown, "Analysis (Structured Disagreement)") or extract_section(transcript_markdown, "Analysis")
    review = extract_section(transcript_markdown, "Review (Anonymized Peer Ranking)")
    synthesis = extract_section(transcript_markdown, "Chairman Synthesis")
    reveal = extract_section(transcript_markdown, "Reveal")

    if synthesis:
        lead_label = "Chairman Synthesis"
        lead = synthesis
        lead_blurb = "The council's compiled recommendation with dissent handled."
    elif analysis:
        lead_label = "Structured Analysis"
        lead = analysis
        lead_blurb = "Consensus, disagreements, and unresolved questions from the council."
    else:
        lead_label = "Transcript"
        lead = transcript_markdown
        lead_blurb = "The saved answer from this lightweight run."

    executive_summary = extract_executive_summary(lead)
    lead_without_summary = lead.replace(executive_summary, "").strip() if executive_summary else lead
    executive_summary_html = (
        markdown_to_html(re.sub(r"^#{2,4}\s+.*Executive Summary.*\n?", "", executive_summary).strip(), heading_offset=1)
        if executive_summary else
        "<p>No executive summary heading was found in the final answer. Start with the main synthesis below.</p>"
    )

    def details(title_text, body, open_by_default=False):
        if not body:
            return ""
        open_attr = " open" if open_by_default else ""
        word_count = len(body.split())
        return (
            f'<details class="source-block"{open_attr}>'
            f'<summary><span>{html.escape(title_text)}</span><small>{word_count} words</small></summary>'
            f'<div class="source-content markdown">{markdown_to_html(body, heading_offset=2)}</div>'
            "</details>"
        )

    round_sections = []
    for match in re.finditer(r"^## Round \d+\s*$", transcript_markdown, re.MULTILINE):
        end = next_transcript_heading_start(transcript_markdown, match.end())
        body = transcript_markdown[match.start():end].strip()
        round_sections.append(body)

    source_sections = [
        details("Original Prompt", question),
        details("Crux Frame", crux),
    ]
    for index, body in enumerate(round_sections, 1):
        title_text = "Initial Answers" if index == 1 else f"Deliberation Round {index - 1}"
        source_sections.append(details(title_text, body))
    source_sections.extend([
        details("Structured Analysis", analysis),
        details("Peer Reviews and Rankings", review),
        details("Blind Reveal", reveal),
        details("Full Markdown Transcript", transcript_markdown),
    ])

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} HTML Report</title>
<style>
:root {{
  --ink: #161a1d;
  --muted: #59636e;
  --paper: #fbfbf7;
  --panel: #ffffff;
  --line: #d9ded8;
  --red: #b42318;
  --red-bg: #fff0ed;
  --green: #176b4d;
  --green-bg: #edf8f3;
  --blue: #1f5d8c;
  --blue-bg: #edf5fb;
  --gold: #8a6116;
  --gold-bg: #fff7df;
  --shadow: 0 18px 60px rgba(18, 24, 31, .10);
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  color: var(--ink);
  background: linear-gradient(180deg, #f3f6f3 0, var(--paper) 28rem);
  font-family: Aptos, Candara, "Segoe UI", sans-serif;
  line-height: 1.56;
}}
.shell {{ max-width: 1180px; margin: 0 auto; padding: 34px 24px 80px; }}
.hero {{
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr);
  gap: 28px;
  align-items: stretch;
  padding: 34px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,.84);
  box-shadow: var(--shadow);
}}
.kicker {{ margin: 0 0 12px; text-transform: uppercase; letter-spacing: .12em; font-size: .76rem; color: var(--blue); font-weight: 800; }}
h1 {{ font-family: Cambria, Georgia, serif; font-size: clamp(2.25rem, 4vw, 4.75rem); line-height: .96; margin: 0 0 18px; font-weight: 700; letter-spacing: 0; }}
.hero p {{ font-size: 1.08rem; max-width: 74ch; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }}
.badge {{ display: inline-flex; padding: 7px 10px; border: 1px solid var(--line); background: #fff; font-size: .84rem; font-weight: 700; }}
.verdict {{ border-left: 8px solid var(--red); background: var(--red-bg); padding: 22px; display: flex; flex-direction: column; justify-content: space-between; }}
.verdict strong {{ display: block; font-size: 1.15rem; margin-bottom: 8px; }}
.verdict p {{ margin: 0; font-size: .98rem; }}
.takeaways {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 24px 0 0; }}
.takeaway {{ border: 1px solid var(--line); background: var(--panel); padding: 16px; min-height: 136px; }}
.takeaway b {{ display: block; font-size: .82rem; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin-bottom: 8px; }}
.takeaway strong {{ display: block; font-size: 1.07rem; line-height: 1.25; margin-bottom: 8px; }}
.takeaway p {{ margin: 0; color: var(--muted); font-size: .94rem; }}
.risk {{ border-top: 5px solid var(--red); }}
.policy {{ border-top: 5px solid var(--blue); }}
.pipeline {{ border-top: 5px solid var(--green); }}
.test {{ border-top: 5px solid var(--gold); }}
.grid {{ display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 28px; margin-top: 28px; align-items: start; }}
nav {{ position: sticky; top: 18px; border: 1px solid var(--line); background: rgba(255,255,255,.92); padding: 18px; }}
nav h2 {{ margin: 0 0 10px; font-size: .9rem; text-transform: uppercase; letter-spacing: .11em; color: var(--muted); }}
nav a {{ display: block; text-decoration: none; padding: 8px 0; border-top: 1px solid #eef1ed; color: var(--ink); font-weight: 700; font-size: .94rem; }}
main {{ min-width: 0; }}
section {{ margin-bottom: 28px; }}
.section-title {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 0 0 14px; }}
.section-title h2 {{ margin: 0; font-family: Cambria, Georgia, serif; font-size: 2rem; line-height: 1.1; }}
.section-title span {{ color: var(--muted); font-size: .92rem; }}
.memo, .content-block {{ background: var(--panel); border: 1px solid var(--line); padding: 28px; box-shadow: 0 8px 28px rgba(18,24,31,.05); }}
.memo {{ border-top: 6px solid var(--green); }}
.content-block {{ border-top: 6px solid var(--blue); }}
.callout {{ border: 1px solid #ead2cd; background: var(--red-bg); padding: 18px 20px; margin: 20px 0; }}
.callout strong {{ color: var(--red); }}
.markdown h2, .markdown h3, .markdown h4, .markdown h5, .markdown h6 {{ font-family: Cambria, Georgia, serif; line-height: 1.18; margin: 1.55em 0 .55em; }}
.markdown h2:first-child, .markdown h3:first-child {{ margin-top: 0; }}
.markdown h2 {{ font-size: 1.75rem; }}
.markdown h3 {{ font-size: 1.42rem; }}
.markdown h4 {{ font-size: 1.18rem; }}
.markdown p {{ margin: .78em 0; }}
.markdown ul, .markdown ol {{ padding-left: 1.35rem; }}
.markdown li {{ margin: .42em 0; }}
.markdown blockquote {{ margin: 1rem 0; padding: .8rem 1rem; border-left: 5px solid var(--blue); background: var(--blue-bg); }}
.list-note {{ margin-left: 1.2rem !important; color: var(--muted); }}
.source-block {{ border: 1px solid var(--line); background: var(--panel); margin-bottom: 12px; }}
.source-block summary {{ cursor: pointer; list-style: none; padding: 16px 18px; display: flex; justify-content: space-between; gap: 14px; align-items: center; font-weight: 800; }}
.source-block summary::-webkit-details-marker {{ display: none; }}
.source-block summary span::before {{ content: '+'; display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 10px; border: 1px solid var(--line); color: var(--blue); }}
.source-block[open] summary span::before {{ content: '-'; }}
.source-block summary small {{ color: var(--muted); font-weight: 700; white-space: nowrap; }}
.source-content {{ border-top: 1px solid var(--line); padding: 22px; max-height: 72vh; overflow: auto; }}
.footer {{ color: var(--muted); font-size: .88rem; margin-top: 28px; }}
@media (max-width: 980px) {{
  .hero {{ grid-template-columns: 1fr; padding: 24px; }}
  .grid {{ grid-template-columns: 1fr; }}
  nav {{ position: static; }}
  .takeaways {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 640px) {{
  .shell {{ padding: 18px 14px 50px; }}
  h1 {{ font-size: 2.35rem; }}
  .takeaways {{ grid-template-columns: 1fr; }}
  .memo, .content-block {{ padding: 20px; }}
  .section-title {{ display: block; }}
}}
@media print {{
  body {{ background: white; }}
  .shell {{ max-width: none; padding: 0; }}
  nav, .source-block {{ display: none; }}
  .grid, .hero, .takeaways {{ display: block; }}
  .hero, .memo, .content-block, .takeaway {{ box-shadow: none; break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="shell">
  <header class="hero">
    <div>
      <p class="kicker">Think Tank report · {html.escape(created_at)}</p>
      <h1>{html.escape(title)}</h1>
      <p>This HTML version promotes the final synthesis when available, keeps the executive answer scannable, and preserves the raw council material underneath.</p>
      <div class="meta">
        <span class="badge">{html.escape(models)}</span>
        <span class="badge">{html.escape(lead_label)} on top</span>
      </div>
    </div>
    <aside class="verdict">
      <div>
        <strong>Artifact pair saved</strong>
        <p>Markdown keeps the raw transcript portable. HTML makes the answer readable enough to hand to another human without apology.</p>
      </div>
    </aside>
  </header>

  <div class="takeaways" id="fast-read">
    <article class="takeaway risk"><b>Read first</b><strong>Executive summary</strong><p>The shortest useful version of the final answer.</p></article>
    <article class="takeaway policy"><b>Then</b><strong>{html.escape(lead_label)}</strong><p>{html.escape(lead_blurb)}</p></article>
    <article class="takeaway pipeline"><b>Trace</b><strong>Crux and analysis</strong><p>See what mattered, what was unresolved, and where the models agreed.</p></article>
    <article class="takeaway test"><b>Archive</b><strong>Full transcript</strong><p>All answers, reviews, rankings, and reveal data are preserved below.</p></article>
  </div>

  <div class="grid">
    <nav aria-label="Document sections">
      <h2>Jump To</h2>
      <a href="#executive-summary">Executive Summary</a>
      <a href="#lead-synthesis">{html.escape(lead_label)}</a>
      <a href="#source-material">Source Material</a>
    </nav>

    <main>
      <section id="executive-summary">
        <div class="section-title"><h2>Executive Summary</h2><span>Promoted from the final answer when available</span></div>
        <div class="memo markdown">{executive_summary_html}</div>
      </section>

      <section id="lead-synthesis">
        <div class="section-title"><h2>{html.escape(lead_label)}</h2><span>Primary answer</span></div>
        <div class="content-block markdown">
          <div class="callout"><strong>Shortcut:</strong> Start here when you need the decision-quality answer. Open source material only when you want the receipts.</div>
          {markdown_to_html(lead_without_summary, heading_offset=1)}
        </div>
      </section>

      <section id="source-material">
        <div class="section-title"><h2>Source Material</h2><span>Collapsed by default</span></div>
        {''.join(source_sections)}
      </section>

      <p class="footer">Generated by Think Tank on {html.escape(created_at)}. This is a static, standalone HTML companion to the markdown transcript.</p>
    </main>
  </div>
</div>
</body>
</html>
"""

# ── API callers ──────────────────────────────────────────────────────────────

import requests

def call_openrouter(messages, api_key, model_id):
    """Call a model through OpenRouter's OpenAI-compatible API."""
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "max_tokens": 4096,
            "messages": messages,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def resolve_api(key):
    """Resolve the OpenRouter caller for a model."""
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        model_id = MODELS[key]["model_id"]
        return lambda msgs, ak: call_openrouter(msgs, ak, model_id), or_key
    return None, None

# ── Context detection ────────────────────────────────────────────────────────

def find_up(filename):
    """Walk up from cwd to find a file."""
    path = Path.cwd()
    while True:
        candidate = path / filename
        if candidate.exists():
            return candidate
        if path.parent == path:
            break
        path = path.parent
    return None


def find_memory_dir():
    """Find .claude memory directory for this project."""
    # Convention: ~/.claude/projects/<encoded-cwd>/memory/
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None

    # Encode current repo root path (find nearest .git)
    repo_root = find_up(".git")
    if repo_root:
        repo_root = repo_root.parent  # .git is a dir, we want its parent
    else:
        repo_root = Path.cwd()

    # Claude encodes paths like C--Users-austi-AI-Stuff-march-madness
    encoded = str(repo_root).replace("\\", "-").replace("/", "-").replace(":", "")
    memory_dir = claude_dir / encoded / "memory"
    if memory_dir.exists():
        return memory_dir
    return None


def estimate_tokens(text):
    """Rough token estimate (~4 chars per token)."""
    return len(text) // 4


def build_context(args, include_project_context=True):
    """Build context from auto-detected files + args."""
    sections = []
    token_report = []

    # Auto-detect CLAUDE.md
    if include_project_context:
        claude_md = find_up("CLAUDE.md")
        if claude_md:
            text = claude_md.read_text(encoding="utf-8", errors="replace")
            sections.append(f"# Project Context (CLAUDE.md)\n\n{text}")
            token_report.append(f"CLAUDE.md (~{estimate_tokens(text):,} tokens)")

    # --deep: include memory files
    if include_project_context and args.deep:
        memory_dir = find_memory_dir()
        if memory_dir:
            mem_file = memory_dir / "MEMORY.md"
            if mem_file.exists():
                text = mem_file.read_text(encoding="utf-8", errors="replace")
                sections.append(f"# Project Memory (MEMORY.md)\n\n{text}")
                token_report.append(f"MEMORY.md (~{estimate_tokens(text):,} tokens)")
        else:
            _print(f"  {C['dim']}(--deep: no memory directory found){C['reset']}")

    # --files: specific files
    if args.files:
        for filepath in args.files.split(","):
            filepath = filepath.strip()
            p = Path(filepath)
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                sections.append(f"# File: {filepath}\n\n```\n{text}\n```")
                token_report.append(f"{filepath} (~{estimate_tokens(text):,} tokens)")
            else:
                _print(f"  {C['err']}Warning: {filepath} not found, skipping{C['reset']}")

    context = "\n\n---\n\n".join(sections) if sections else ""
    return context, token_report


# ── Display ──────────────────────────────────────────────────────────────────

def header(text):
    try:
        width = min(os.get_terminal_size().columns, 80)
    except OSError:
        width = 80
    bar = "━" * width
    _print(f"\n{C['bold']}{bar}{C['reset']}")
    _print(f"{C['bold']}  {text}{C['reset']}")
    _print(f"{C['bold']}{bar}{C['reset']}\n")


def model_header(model_key, elapsed=None, display_name=None):
    info = MODELS[model_key]
    color = C[model_key]
    name = display_name or info["name"]
    time_str = f" ({elapsed:.1f}s)" if elapsed else ""
    _print(f"\n{color}{C['bold']}▌ {name}{time_str}{C['reset']}")
    _print(f"{color}{'─' * 40}{C['reset']}")


def show_response(model_key, text, elapsed=None, display_name=None):
    model_header(model_key, elapsed, display_name)
    _print(text)


def spinner_frames():
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while True:
        yield frames[i % len(frames)]
        i += 1


def create_blind_mapping(active_models):
    """Create a random mapping of model keys to Panelist A/B/C/D labels."""
    labels = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")[:len(active_models)]
    shuffled = active_models.copy()
    random.shuffle(shuffled)
    return {key: f"Panelist {label}" for key, label in zip(shuffled, labels)}


def get_display_name(model_key, blind_map=None):
    """Return model display name, respecting blind mode."""
    if blind_map and model_key in blind_map:
        return blind_map[model_key]
    return MODELS[model_key]["name"]


# ── Core logic ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT_PROJECT = """You are one voice in a {model_count}-model think tank. The user has a question \
about a software project. They've provided project context below.

Rules:
- Be direct and concise. No filler.
- Disagree with other models when warranted — sycophancy is useless here.
- If you spot a flaw in another model's reasoning, call it out specifically.
- Propose concrete solutions, not vague suggestions.
- If you don't have enough context, say what you'd need.
- Keep responses focused — aim for substance, not length."""

SYSTEM_PROMPT_GENERAL = """You are one voice in a {model_count}-model think tank. The user has a question.

Rules:
- Be direct and concise. No filler.
- Disagree with other models when warranted — sycophancy is useless here.
- If you spot a flaw in another model's reasoning, call it out specifically.
- Propose concrete solutions, not vague suggestions.
- If you don't have enough context, say what you'd need.
- Keep responses focused — aim for substance, not length."""

RED_TEAM_SYSTEM_PROMPT = """You are the assigned red team voice in a {model_count}-model think tank. The \
other panelists will answer the user's question directly — your job is different.

The user is likely asking this question through an AI coding agent that may have already biased the \
framing toward a particular answer. Your job is to find the flaws.

Your role:
- Assume the question's framing or premise may be wrong. Check that first.
- Hunt for hidden assumptions, failure modes, edge cases, counter-evidence, unstated tradeoffs, \
and second-order effects.
- Argue the strongest case AGAINST the obvious answer, even if the obvious answer is probably right.
- Flag missing information that would change the conclusion if known.

Rules:
- Be specific. "What if it fails?" is useless. "This assumes X; if Y is true instead, it breaks because Z" is useful.
- Don't be contrarian for its own sake. Find the real objections. Skip weak ones.
- If you genuinely can't find a serious flaw after looking hard, say so plainly — don't manufacture concerns.
- Keep it focused. Two real risks beat ten speculative ones.
- Stay grounded in the context provided. No hand-wavy "have you considered..." nonsense."""

CRUX_PROMPT_PROJECT = """You are framing a software project question before a multi-model think tank answers it.

Original question: {question}

Project context:
{context}

Extract the small set of decision cruxes the council should answer. Do not solve the whole problem yet.

Output exactly these sections:

CRUXES:
- [3-7 crux questions where the final recommendation could change depending on the answer]

ASSUMPTIONS:
- [Hidden assumptions or missing facts that the council should not silently gloss over]

VALIDATION TESTS:
- [Concrete checks, evidence, or kill criteria that would change the recommendation]"""

CRUX_PROMPT_GENERAL = """You are framing a question before a multi-model think tank answers it.

Original question: {question}

Extract the small set of decision cruxes the council should answer. Do not solve the whole problem yet.

Output exactly these sections:

CRUXES:
- [3-7 crux questions where the final recommendation could change depending on the answer]

ASSUMPTIONS:
- [Hidden assumptions or missing facts that the council should not silently gloss over]

VALIDATION TESTS:
- [Concrete checks, evidence, or kill criteria that would change the recommendation]"""

DELIBERATION_PROMPT = """Here's what the other models said in the previous round:

{other_responses}

Now respond to their points. Where do you agree? Where are they wrong? \
What did they miss? Build on good ideas, challenge weak ones. Be specific."""

RED_TEAM_DELIBERATION_PROMPT = """Here's what the other models said in the previous round:

{other_responses}

Now push harder on them. Where are they wrong? What are they assuming that might not hold? \
What failure modes did they gloss over? What would break their plan in production / at scale / \
with adversarial inputs? Stay specific — real risks, not speculation. If any of their points are \
genuinely solid, acknowledge it briefly and move on to the next vulnerability. Do not soften your stance."""

ANALYSIS_PROMPT_PROJECT = """You are analyzing responses from a {model_count}-model think tank about a software project.

Original question: {question}

Project context:
{context}

Model responses:

{responses_text}

Analyze these responses and produce a structured breakdown. Be specific about which models hold which positions. Do not summarize the responses — only extract the structure.

You MUST output exactly these three sections, even if a section has no items (write "None identified" in that case):

CONSENSUS:
- [Points where 2+ models substantively agree — not just similar wording, but actual agreement on claims or recommendations]

DISAGREEMENTS:
- [Point of contention] — [Model names] say X vs [Model names] say Y. Crux: [what fact, assumption, or priority the disagreement hinges on]

UNRESOLVED:
- [Important questions no model addressed, assumptions none validated, or information gaps that would change the answer]"""

ANALYSIS_PROMPT_GENERAL = """You are analyzing responses from a {model_count}-model think tank.

Original question: {question}

Model responses:

{responses_text}

Analyze these responses and produce a structured breakdown. Be specific about which models hold which positions. Do not summarize the responses — only extract the structure.

You MUST output exactly these three sections, even if a section has no items (write "None identified" in that case):

CONSENSUS:
- [Points where 2+ models substantively agree — not just similar wording, but actual agreement on claims or recommendations]

DISAGREEMENTS:
- [Point of contention] — [Model names] say X vs [Model names] say Y. Crux: [what fact, assumption, or priority the disagreement hinges on]

UNRESOLVED:
- [Important questions no model addressed, assumptions none validated, or information gaps that would change the answer]"""

REVIEW_PROMPT_PROJECT = """You are reviewing anonymized responses to a question about a software project.

Original question: {question}

Project context:
{context}

Here are the responses:

{responses_text}

Evaluate each response on:
- Accuracy and correctness
- Completeness — did it address the full question?
- Practical value — could you act on this advice?
- Reasoning quality — is the logic sound?

After your evaluation, provide your final ranking in this exact format:

FINAL RANKING:
{ranking_slots}

Do not add any text after the ranking."""

REVIEW_PROMPT_GENERAL = """You are reviewing anonymized responses to a question.

Original question: {question}

Here are the responses:

{responses_text}

Evaluate each response on:
- Accuracy and correctness
- Completeness — did it address the full question?
- Practical value — could you act on this advice?
- Reasoning quality — is the logic sound?

After your evaluation, provide your final ranking in this exact format:

FINAL RANKING:
{ranking_slots}

Do not add any text after the ranking."""


def run_round(conversations, active_models, round_num, blind_map=None):
    """Run one round of parallel API calls. Returns {model_key: (response_text, elapsed)}."""
    results = {}
    timings = {}
    start = time.time()

    _print(f"\n{C['dim']}  Waiting for models...{C['reset']}", end="", flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for key in active_models:
            caller, api_key = resolve_api(key)
            if not caller:
                _print(f"\n  {C['err']}{get_display_name(key, blind_map)}: OPENROUTER_API_KEY not set{C['reset']}")
                continue
            futures[pool.submit(caller, conversations[key], api_key)] = key

        completed = 0
        for future in as_completed(futures):
            key = futures[future]
            elapsed = time.time() - start
            completed += 1

            # Clear "waiting" line
            _print(f"\r{' ' * 60}\r", end="", flush=True)

            try:
                text = future.result()
                results[key] = text
                timings[key] = elapsed
                display_name = get_display_name(key, blind_map)
                show_response(key, text, elapsed, display_name)
            except Exception as e:
                error_detail = str(e)
                # Try to extract API error message
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.json()
                    except Exception:
                        error_detail = e.response.text[:500]
                _print(f"\n  {C['err']}{get_display_name(key, blind_map)} failed: {error_detail}{C['reset']}")
                results[key] = None

            remaining = len(futures) - completed
            if remaining > 0:
                waiting = [get_display_name(futures[f], blind_map) for f in futures if not f.done()]
                _print(f"\n{C['dim']}  Waiting for {', '.join(waiting)}...{C['reset']}", end="", flush=True)

    total_time = time.time() - start
    total_tokens = sum(estimate_tokens(r) for r in results.values() if r)
    _print(f"\n\n{C['system']}  Round {round_num} complete · {total_time:.1f}s · ~{total_tokens:,} output tokens{C['reset']}")

    return results, timings


def run_crux_frame(question, context, crux_key, blind_map=None):
    """Run an optional framing pass before the council answers."""
    if context:
        prompt_text = CRUX_PROMPT_PROJECT.format(question=question, context=context)
    else:
        prompt_text = CRUX_PROMPT_GENERAL.format(question=question)

    messages = [
        {"role": "system", "content": "You are a neutral decision-framing analyst. Extract cruxes, assumptions, and validation tests without trying to win the argument."},
        {"role": "user", "content": prompt_text},
    ]

    header("Crux Frame")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for crux frame...{C['reset']}", end="", flush=True)

    caller, api_key = resolve_api(crux_key)
    if not caller:
        _print(f"\n  {C['err']}Crux frame: {get_display_name(crux_key, blind_map)} — OPENROUTER_API_KEY not set{C['reset']}")
        return None

    try:
        text = caller(messages, api_key)
        elapsed = time.time() - start
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        display_name = get_display_name(crux_key, blind_map)
        model_header(crux_key, elapsed, display_name)
        _print(text)
        return text
    except Exception as e:
        elapsed = time.time() - start
        error_detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text[:500]
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        _print(f"\n  {C['err']}Crux frame failed ({elapsed:.1f}s): {error_detail}{C['reset']}")
        return None


def build_deliberation_message(results, exclude_key, blind_map=None, red_team_key=None):
    """Build the 'here's what others said' message for a model.

    If exclude_key IS the red_team model, uses the more adversarial deliberation prompt.
    If any of the others are the red_team, annotates their name so the reader knows
    to treat that response as critique rather than competing advice.
    """
    parts = []
    for key, text in results.items():
        if key != exclude_key and text:
            name = get_display_name(key, blind_map)
            if key == red_team_key:
                name = f"{name} (assigned: red team)"
            parts.append(f"**{name}:**\n{text}")
    prompt = RED_TEAM_DELIBERATION_PROMPT if exclude_key == red_team_key else DELIBERATION_PROMPT
    return prompt.format(other_responses="\n\n---\n\n".join(parts))


def anonymize_responses(results, active_models):
    """Assign random Response A/B/C/D labels to model responses.

    Returns:
        tuple: (anonymized_responses dict {label: text}, label_to_model dict {label: model_key})
    """
    responding = [k for k in active_models if results.get(k)]
    labels = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")[:len(responding)]
    shuffled = responding.copy()
    random.shuffle(shuffled)

    anonymized = {}
    label_to_model = {}
    for key, label in zip(shuffled, labels):
        full_label = f"Response {label}"
        anonymized[full_label] = results[key]
        label_to_model[full_label] = key

    return anonymized, label_to_model


def parse_ranking(text):
    """Extract FINAL RANKING from review text. Returns list of 'Response X' labels."""
    if "FINAL RANKING:" not in text:
        matches = re.findall(r'Response [A-Z]', text)
        return matches

    ranking_section = text.split("FINAL RANKING:")[1]
    numbered = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
    if numbered:
        return [re.search(r'Response [A-Z]', m).group() for m in numbered]

    return re.findall(r'Response [A-Z]', ranking_section)


def calculate_aggregate_rankings(all_rankings, label_to_model):
    """Compute average rank position for each model across all reviewers.

    Args:
        all_rankings: list of (model_key, parsed_ranking_list) tuples
        label_to_model: dict mapping 'Response X' -> model_key

    Returns:
        list of (model_key, avg_rank, vote_count) sorted best to worst
    """
    from collections import defaultdict
    positions = defaultdict(list)

    for reviewer, ranking in all_rankings:
        for pos, label in enumerate(ranking, start=1):
            if label in label_to_model:
                model_key = label_to_model[label]
                if model_key == reviewer:
                    continue
                positions[model_key].append(pos)

    aggregate = []
    for model_key, pos_list in positions.items():
        avg = sum(pos_list) / len(pos_list)
        aggregate.append((model_key, round(avg, 2), len(pos_list)))

    aggregate.sort(key=lambda x: x[1])
    return aggregate


def run_review(results, active_models, question, context, blind_map=None, red_team_key=None):
    """Run anonymized peer review stage.

    Returns:
        tuple: (all_rankings, label_to_model, aggregate, review_texts)
    """
    anonymized, label_to_model = anonymize_responses(results, active_models)
    model_to_label = {model_key: label for label, model_key in label_to_model.items()}

    def build_review_messages(reviewer_key):
        """Build leave-one-out review prompt so models never rank themselves."""
        visible = {
            label: text
            for label, text in anonymized.items()
            if label_to_model[label] != reviewer_key
        }
        responses_text = "\n\n---\n\n".join(
            f"{label}:\n{text}" for label, text in visible.items()
        )
        ranking_slots = "\n".join(
            f"{i}. Response X" for i in range(1, len(visible) + 1)
        )

        if context:
            prompt_text = REVIEW_PROMPT_PROJECT.format(
                question=question, context=context,
                responses_text=responses_text, ranking_slots=ranking_slots,
            )
        else:
            prompt_text = REVIEW_PROMPT_GENERAL.format(
                question=question,
                responses_text=responses_text, ranking_slots=ranking_slots,
            )

        if red_team_key:
            red_team_label = model_to_label.get(red_team_key)
            if red_team_label and red_team_label in visible:
                prompt_text = (
                    f"Note: {red_team_label} was assigned a red team / adversarial role — their job was "
                    "to find flaws, challenge assumptions, and surface failure modes, not to answer the "
                    "question directly. Evaluate their critique on quality (specific, grounded, meaningful) "
                    "rather than whether it directly answers the question. Rank all responses on their "
                    "contribution to the council's final answer.\n\n"
                ) + prompt_text

        return [
            {"role": "system", "content": "You are a careful, objective evaluator. Do not infer or rank any response that is not shown to you."},
            {"role": "user", "content": prompt_text},
        ]

    header("Review (Anonymized Peer Ranking)")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for reviews...{C['reset']}", end="", flush=True)

    review_texts = {}
    all_rankings = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for key in active_models:
            caller, api_key = resolve_api(key)
            if not caller:
                continue
            review_messages = build_review_messages(key)
            futures[pool.submit(caller, review_messages, api_key)] = key

        completed = 0
        for future in as_completed(futures):
            key = futures[future]
            elapsed = time.time() - start
            completed += 1
            _print(f"\r{' ' * 60}\r", end="", flush=True)

            try:
                text = future.result()
                review_texts[key] = text
                parsed = parse_ranking(text)
                all_rankings.append((key, parsed))
                display_name = get_display_name(key, blind_map)
                show_response(key, text, elapsed, display_name)
            except Exception as e:
                error_detail = str(e)
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.json()
                    except Exception:
                        error_detail = e.response.text[:500]
                _print(f"\n  {C['err']}{get_display_name(key, blind_map)} review failed: {error_detail}{C['reset']}")

            remaining = len(futures) - completed
            if remaining > 0:
                waiting = [get_display_name(futures[f], blind_map) for f in futures if not f.done()]
                _print(f"\n{C['dim']}  Waiting for {', '.join(waiting)}...{C['reset']}", end="", flush=True)

    # Calculate aggregate
    aggregate = calculate_aggregate_rankings(all_rankings, label_to_model)

    # Display aggregate rankings
    _print(f"\n\n{C['bold']}  Aggregate Rankings{C['reset']}")
    _print(f"  {'─' * 40}")
    for rank, (model_key, avg, votes) in enumerate(aggregate, 1):
        name = get_display_name(model_key, blind_map)
        _print(f"  {rank}. {name}  — avg rank {avg} ({votes} votes)")

    total_time = time.time() - start
    _print(f"\n{C['system']}  Review complete · {total_time:.1f}s{C['reset']}")

    return all_rankings, label_to_model, aggregate, review_texts


# ── Analysis (structured disagreement) ─────────────────────────────────────

def run_analysis(results, active_models, question, context, chairman_key, blind_map=None, red_team_key=None, crux_text=None):
    """Run structured disagreement analysis. Returns analysis text or None on failure."""
    responses_text = "\n\n---\n\n".join(
        f"**{get_display_name(key, blind_map)}{' (assigned: red team)' if key == red_team_key else ''}:**\n{results[key]}"
        for key in active_models if results.get(key)
    )

    model_count = len([k for k in active_models if results.get(k)])

    if context:
        prompt_text = ANALYSIS_PROMPT_PROJECT.format(
            model_count=model_count, question=question,
            context=context, responses_text=responses_text,
        )
    else:
        prompt_text = ANALYSIS_PROMPT_GENERAL.format(
            model_count=model_count, question=question,
            responses_text=responses_text,
        )

    if crux_text:
        prompt_text += (
            "\n\nCrux frame used for this run:\n"
            f"{crux_text}\n\n"
            "When extracting DISAGREEMENTS and UNRESOLVED items, call out whether the council actually answered the cruxes."
        )

    if red_team_key and results.get(red_team_key):
        red_team_name = get_display_name(red_team_key, blind_map)
        prompt_text += (
            f"\n\nNote: {red_team_name} was assigned a red team / adversarial role "
            "this session — their response is critique rather than a direct answer. When extracting "
            "DISAGREEMENTS, flag disagreements driven by their critique as such (e.g. 'red team flagged'), "
            "separate from organic disagreement between the direct-answering models."
        )

    analysis_messages = [
        {"role": "system", "content": "You are an expert analyst. Extract the structure of agreement and disagreement from multi-model responses. Be precise and specific."},
        {"role": "user", "content": prompt_text},
    ]

    header("Analysis (Structured Disagreement)")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for analysis...{C['reset']}", end="", flush=True)

    caller, api_key = resolve_api(chairman_key)
    if not caller:
        _print(f"\n  {C['err']}Analysis: {get_display_name(chairman_key, blind_map)} — OPENROUTER_API_KEY not set{C['reset']}")
        return None

    try:
        text = caller(analysis_messages, api_key)
        elapsed = time.time() - start
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        display_name = get_display_name(chairman_key, blind_map)
        model_header(chairman_key, elapsed, display_name)
        _print(text)
        return text
    except Exception as e:
        elapsed = time.time() - start
        error_detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text[:500]
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        _print(f"\n  {C['err']}Analysis failed ({elapsed:.1f}s): {error_detail}{C['reset']}")
        return None


# ── Chairman synthesis ──────────────────────────────────────────────────────

CHAIRMAN_PROMPT_PROJECT = """You are the compiler of a {model_count}-model think tank. Your job is to \
turn the council's work into the best possible answer without erasing useful dissent.

Original question: {question}

Project context:
{context}

Individual responses:
{responses_text}

Peer rankings:
{rankings_text}

Structured analysis:
{analysis_text}

Write the final answer using this discipline:
- Start from the top-ranked response as the base unless there is a clear reason not to.
- Preserve the strongest useful points from lower-ranked responses.
- Explicitly accept or reject each material dissent from the structured analysis.
- If you change the top-ranked recommendation, say what changed and why.
- Address unresolved cruxes, missing evidence, and validation tests.
- End with concrete, actionable recommendations.

Be direct. Act like a compiler, not a monarch."""

CHAIRMAN_PROMPT_GENERAL = """You are the compiler of a {model_count}-model think tank. Your job is to \
turn the council's work into the best possible answer without erasing useful dissent.

Original question: {question}

Individual responses:
{responses_text}

Peer rankings:
{rankings_text}

Structured analysis:
{analysis_text}

Write the final answer using this discipline:
- Start from the top-ranked response as the base unless there is a clear reason not to.
- Preserve the strongest useful points from lower-ranked responses.
- Explicitly accept or reject each material dissent from the structured analysis.
- If you change the top-ranked recommendation, say what changed and why.
- Address unresolved cruxes, missing evidence, and validation tests.
- End with concrete, actionable recommendations.

Be direct. Act like a compiler, not a monarch."""


def run_chairman(results, active_models, aggregate, question, context, chairman_key, analysis_text=None, red_team_key=None, blind_map=None, crux_text=None):
    """Run chairman synthesis stage. Returns synthesized text or None on failure."""
    responses_text = "\n\n---\n\n".join(
        f"**{get_display_name(key, blind_map)}{' (assigned: red team)' if key == red_team_key else ''}:**\n{results[key]}"
        for key in active_models if results.get(key)
    )

    rankings_text = "\n".join(
        f"  {rank}. {get_display_name(mk, blind_map)} — avg rank {avg}"
        for rank, (mk, avg, _) in enumerate(aggregate, 1)
    )

    model_count = len([k for k in active_models if results.get(k)])

    if context:
        prompt_text = CHAIRMAN_PROMPT_PROJECT.format(
            model_count=model_count, question=question,
            context=context, responses_text=responses_text,
            rankings_text=rankings_text,
            analysis_text=analysis_text or "Analysis not available.",
        )
    else:
        prompt_text = CHAIRMAN_PROMPT_GENERAL.format(
            model_count=model_count, question=question,
            responses_text=responses_text, rankings_text=rankings_text,
            analysis_text=analysis_text or "Analysis not available.",
        )

    if crux_text:
        prompt_text += (
            "\n\nCrux frame used for this run:\n"
            f"{crux_text}\n\n"
            "Your synthesis must answer the cruxes directly where possible. If a crux remains unanswered, name the missing evidence instead of pretending it is settled."
        )

    if red_team_key and results.get(red_team_key):
        red_team_name = get_display_name(red_team_key, blind_map)
        prompt_text += (
            f"\n\nNote: {red_team_name} was assigned a red team / adversarial role "
            "this session — their response is designed critique, not competing advice. Weight their "
            "points as stress-tests against the other models' positions. If they surfaced a real flaw, "
            "your synthesis must address it (either mitigate it or explicitly acknowledge it as an "
            "accepted risk). If their critique was weak or off-target, say so and move on — don't "
            "manufacture concessions."
        )

    chairman_messages = [
        {"role": "system", "content": "You compile a multi-model council into one useful answer. Preserve strong dissent, explain material changes, and do not overrule the council by taste alone."},
        {"role": "user", "content": prompt_text},
    ]

    chairman_name = get_display_name(chairman_key, blind_map)
    header(f"Chairman Synthesis ({chairman_name})")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for chairman...{C['reset']}", end="", flush=True)

    caller, api_key = resolve_api(chairman_key)
    if not caller:
        _print(f"\n  {C['err']}Chairman {get_display_name(chairman_key, blind_map)}: OPENROUTER_API_KEY not set{C['reset']}")
        return None

    try:
        text = caller(chairman_messages, api_key)
        elapsed = time.time() - start
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        model_header(chairman_key, elapsed, chairman_name)
        _print(text)
        return text
    except Exception as e:
        elapsed = time.time() - start
        error_detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text[:500]
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        _print(f"\n  {C['err']}Chairman failed ({elapsed:.1f}s): {error_detail}{C['reset']}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Think Tank — Multi-model deliberation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               '  think_tank "How should we refactor the auth module?"\n'
               '  think_tank --files src/App.jsx --crux --rounds 1 "Split this component?"\n'
               '  think_tank --deep --interactive "2027 strategy discussion"\n'
               '  think_tank --no-save "Quick throwaway check"',
    )
    parser.add_argument("question", nargs="?", help="Your question (or use --prompt-file)")
    parser.add_argument("--prompt-file", "-pf", help="Read question from file")
    parser.add_argument("--files", "-f", help="Comma-separated files to include as context")
    parser.add_argument("--deep", "-d", action="store_true", help="Include MEMORY.md")
    parser.add_argument("--rounds", "-r", type=int, default=0,
                        help="Deliberation rounds after the initial answer pass (default: 0)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive follow-up mode")
    parser.add_argument("--save", "-s", nargs="?", const="", metavar="PATH",
                        help="Save markdown + HTML artifacts to this base path (enabled by default). "
                             "Bare filenames go to output/; omit PATH for a timestamped file.")
    parser.add_argument("--no-save", action="store_true",
                        help="Do not save markdown/HTML artifacts for this run")
    parser.add_argument("--no-context", action="store_true",
                        help="Skip auto project context (CLAUDE.md/deep memory); explicit --files still load")
    parser.add_argument("--models", "-m", help="Comma-separated model keys (claude,gpt,gemini,deepseek,grok)")
    parser.add_argument("--chairman", "-c", default="grok",
                        help="Model key for chairman synthesis (default: grok)")
    parser.add_argument("--blind", "-b", action="store_true",
                        help="Hide model identities until reveal at end")
    parser.add_argument("--no-chairman", action="store_true",
                        help="Skip review + synthesis stages")
    parser.add_argument("--crux", action="store_true",
                        help="Run a framing pass before collection to extract cruxes, hidden assumptions, and validation tests")
    parser.add_argument("--red-team", "-R", default=None, metavar="MODEL",
                        help="Assign a model the red team / adversarial role "
                             "(e.g. --red-team gpt). That model hunts for flaws, "
                             "challenges premises, and stress-tests the others' "
                             "answers instead of answering directly.")
    parser.add_argument("--json", action="store_true",
                        help="Output structured JSON (suppress terminal display)")

    args = parser.parse_args()

    if args.rounds < 0:
        print(f"{C['err']}--rounds must be 0 or greater{C['reset']}")
        sys.exit(1)

    # Enable JSON mode globally
    global JSON_MODE
    if args.json:
        JSON_MODE = True

    # Get question
    question = args.question
    if args.prompt_file:
        question = Path(args.prompt_file).read_text(encoding="utf-8", errors="replace")
    if not question:
        if not sys.stdin.isatty():
            question = sys.stdin.read()
        else:
            parser.print_help()
            sys.exit(1)

    # Select models
    if args.models:
        active_models = [k.strip() for k in args.models.split(",")]
        invalid = [k for k in active_models if k not in MODELS]
        if invalid:
            print(f"{C['err']}Unknown models: {', '.join(invalid)}. Use: {', '.join(MODELS.keys())}{C['reset']}")
            sys.exit(1)
    else:
        active_models = DEFAULT_PANEL[:]

    # Validate chairman
    if args.chairman not in MODELS:
        print(f"{C['err']}Unknown chairman: {args.chairman}. Use: {', '.join(MODELS.keys())}{C['reset']}")
        sys.exit(1)

    # Validate red team
    red_team_key = args.red_team
    if red_team_key:
        if red_team_key not in MODELS:
            print(f"{C['err']}Unknown red team model: {red_team_key}. Use: {', '.join(MODELS.keys())}{C['reset']}")
            sys.exit(1)
        if red_team_key not in active_models:
            print(f"{C['err']}Red team model {red_team_key} is not in the active model set. "
                  f"Either drop --models or include {red_team_key}.{C['reset']}")
            sys.exit(1)
        if red_team_key == args.chairman and not args.no_chairman:
            _print(f"  {C['err']}Warning: chairman and red team are the same model ({red_team_key}). "
                   f"The chairman will synthesize its own critique — use --chairman to pick a different "
                   f"model if that's not what you want.{C['reset']}")

    model_count = len(active_models)

    if not os.environ.get("OPENROUTER_API_KEY"):
        print(f"{C['err']}Missing: OPENROUTER_API_KEY. This tool now routes all models through OpenRouter.{C['reset']}")
        sys.exit(1)

    # Build context. --no-context disables auto project context but keeps explicit files.
    context, token_report = build_context(args, include_project_context=not args.no_context)

    blind_keys = active_models.copy()
    if args.chairman not in blind_keys:
        blind_keys.append(args.chairman)
    blind_map = create_blind_mapping(blind_keys) if args.blind else None

    # Display header
    header("Think Tank")
    model_names = " · ".join(get_display_name(k, blind_map) for k in active_models)
    _print(f"  {C['bold']}Models:{C['reset']} {model_names}")
    if token_report:
        _print(f"  {C['bold']}Context:{C['reset']} {', '.join(token_report)}")
    elif args.no_context:
        _print(f"  {C['dim']}Auto project context disabled{C['reset']}")
    else:
        _print(f"  {C['dim']}No project context detected (run from a repo with CLAUDE.md){C['reset']}")
    q_preview = question[:120] + ("..." if len(question) > 120 else "")
    _print(f"  {C['bold']}Question:{C['reset']} {q_preview}")
    if args.rounds:
        _print(f"  {C['bold']}Deliberation rounds:{C['reset']} {args.rounds}")
    if args.interactive:
        _print(f"  {C['bold']}Mode:{C['reset']} Interactive")
    if args.crux:
        _print(f"  {C['bold']}Mode:{C['reset']} Crux framing")
    if not args.no_chairman:
        _print(f"  {C['bold']}Chairman:{C['reset']} {get_display_name(args.chairman, blind_map)}")
    if red_team_key:
        _print(f"  {C['bold']}Red team:{C['reset']} {get_display_name(red_team_key, blind_map)} (adversarial role)")
    if args.blind:
        _print(f"  {C['bold']}Mode:{C['reset']} Blind (identities hidden until reveal)")
    _print(f"  {C['dim']}Provider: OpenRouter{C['reset']}")

    pipeline_start = time.time()
    crux_text = None
    if args.crux:
        crux_text = run_crux_frame(question, context, args.chairman, blind_map)

    # Build initial messages
    system_template = SYSTEM_PROMPT_PROJECT if context else SYSTEM_PROMPT_GENERAL
    default_system_msg = system_template.format(model_count=model_count)
    red_team_system_msg = RED_TEAM_SYSTEM_PROMPT.format(model_count=model_count)

    # If a red team is assigned, disclose it in the other models' system prompts
    # so they treat that voice as critique rather than competing advice.
    if red_team_key:
        rt_display = get_display_name(red_team_key, blind_map)
        disclosure = (
            f"\n\nNote: One panelist ({rt_display}) has been assigned a red team / adversarial "
            "role this session — their job is to find flaws in the question's framing and stress-test "
            "the answers, not to answer directly. Treat their points as critique to engage with, not "
            "as competing advice."
        )
        default_system_msg = default_system_msg + disclosure

    user_content = question
    if context:
        user_content = f"{context}\n\n---\n\n# Question\n\n{question}"
    if crux_text:
        if context:
            user_content = f"{context}\n\n---\n\n# Crux Frame\n\n{crux_text}\n\n---\n\n# Question\n\n{question}"
        else:
            user_content = f"# Crux Frame\n\n{crux_text}\n\n---\n\n# Question\n\n{question}"

    # Initialize per-model conversation histories
    conversations = {}
    for key in active_models:
        sys_msg = red_team_system_msg if key == red_team_key else default_system_msg
        conversations[key] = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_content},
        ]

    # Transcript for --save
    transcript = []
    transcript.append(f"# Think Tank — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    transcript.append(f"**Question:** {question}\n")
    model_names_str = ", ".join(get_display_name(k, blind_map) for k in active_models)
    transcript.append(f"**Models:** {model_names_str}\n")
    if not args.no_chairman:
        transcript.append(f"**Chairman:** {get_display_name(args.chairman, blind_map)}\n")
    if red_team_key:
        transcript.append(f"**Red team:** {get_display_name(red_team_key, blind_map)} (adversarial role)\n")
    if crux_text:
        transcript.append(f"\n## Crux Frame\n{crux_text}\n")

    # ── JSON collection ─────────────────────────────────────────────────
    json_rounds = []
    json_review = None
    json_analysis = None
    json_synthesis = None

    # ── Round loop ───────────────────────────────────────────────────────
    total_rounds = args.rounds + 1
    if args.interactive:
        total_rounds = 999  # effectively unlimited

    round_num = 0
    while round_num < total_rounds:
        round_num += 1
        header(f"Round {round_num}")

        results, timings = run_round(conversations, active_models, round_num, blind_map)

        # Collect for JSON output
        round_data = {}
        for key in active_models:
            if results.get(key):
                round_data[key] = {"text": results[key], "elapsed": round(timings.get(key, 0), 1)}
        json_rounds.append({"round": round_num, "responses": round_data})

        # Save to transcript
        transcript.append(f"\n## Round {round_num}\n")
        for key in active_models:
            if results.get(key):
                name = get_display_name(key, blind_map)
                transcript.append(f"### {name}\n{results[key]}\n")

        # Update conversation histories with responses
        for key in active_models:
            if results.get(key):
                conversations[key].append({"role": "assistant", "content": results[key]})

        # If more rounds, add deliberation messages
        if round_num < total_rounds or args.interactive:
            responding_models = [k for k in active_models if results.get(k)]

            # If only 1 model responded, skip deliberation
            if len(responding_models) < 2:
                continue

            if round_num <= args.rounds:
                # Auto-continue to next deliberation round
                for key in active_models:
                    if results.get(key):
                        delib_msg = build_deliberation_message(results, key, blind_map, red_team_key)
                        conversations[key].append({"role": "user", "content": delib_msg})
            elif args.interactive:
                # Prompt for follow-up
                _print(f"\n{C['system']}{'─' * 50}{C['reset']}")
                try:
                    follow_up = input(f"{C['bold']}  Continue (enter=deliberate, q=quit, or type follow-up): {C['reset']}").strip()
                except (KeyboardInterrupt, EOFError):
                    break

                if follow_up.lower() in ("q", "quit", "exit"):
                    break
                elif follow_up == "":
                    # Default: deliberation round
                    for key in active_models:
                        if results.get(key):
                            delib_msg = build_deliberation_message(results, key, blind_map, red_team_key)
                            conversations[key].append({"role": "user", "content": delib_msg})
                else:
                    # User typed a follow-up question
                    # Include other models' responses + new question
                    for key in active_models:
                        if results.get(key):
                            other_context = build_deliberation_message(results, key, blind_map, red_team_key)
                            msg = f"{other_context}\n\n---\n\nThe user has a follow-up:\n\n{follow_up}"
                            conversations[key].append({"role": "user", "content": msg})
                    transcript.append(f"\n**Follow-up:** {follow_up}\n")

    # ── Analysis (structured disagreement) ──────────────────────────────
    # Gather final responses (last response from each model)
    final_responses = {}
    for key in active_models:
        if conversations[key]:
            for msg in reversed(conversations[key]):
                if msg["role"] == "assistant":
                    final_responses[key] = msg["content"]
                    break

    responding = [k for k in active_models if final_responses.get(k)]
    analysis_text = None

    if len(responding) >= 2:
        analysis_text = run_analysis(
            final_responses, active_models, question, context,
            args.chairman, blind_map, red_team_key, crux_text,
        )
        if analysis_text:
            json_analysis = analysis_text
            transcript.append(f"\n## Analysis (Structured Disagreement)\n{analysis_text}\n")
        else:
            transcript.append("\n## Analysis\n*Analysis failed — continuing without it.*\n")
    else:
        _print(f"\n{C['system']}  Skipping analysis — fewer than 2 models responded.{C['reset']}")

    # ── Review + Synthesis (unless --no-chairman) ────────────────────────
    chairman_text = None
    label_to_model = {}
    if not args.no_chairman and len(responding) >= 2:
        all_rankings, label_to_model, aggregate, review_texts = run_review(
            final_responses, active_models, question, context, blind_map, red_team_key,
        )

        # Collect review data for JSON
        json_review = {
            "rankings": [
                {"model": mk, "name": MODELS[mk]["name"], "avg_rank": avg, "votes": votes}
                for mk, avg, votes in aggregate
            ],
            "label_map": {label: mk for label, mk in label_to_model.items()},
        }

        # Transcript: review section
        transcript.append(f"\n## Review (Anonymized Peer Ranking)\n")
        for key in active_models:
            if review_texts.get(key):
                name = get_display_name(key, blind_map)
                transcript.append(f"### {name}'s Review\n{review_texts[key]}\n")
        transcript.append("### Aggregate Rankings\n")
        for rank, (mk, avg, votes) in enumerate(aggregate, 1):
            name = get_display_name(mk, blind_map)
            transcript.append(f"{rank}. {name} — avg rank {avg} ({votes} votes)\n")

        # Chairman synthesis
        chairman_text = run_chairman(
            final_responses, active_models, aggregate,
            question, context, args.chairman, analysis_text, red_team_key, blind_map, crux_text,
        )

        if chairman_text:
            json_synthesis = chairman_text
            transcript.append(f"\n## Chairman Synthesis\n{chairman_text}\n")
        else:
            transcript.append("\n## Chairman Synthesis\n*Chairman failed — see aggregate rankings above.*\n")

    # ── Blind reveal ────────────────────────────────────────────────────
    if args.blind:
        _print(f"\n{C['bold']}  ── Reveal ──────────{C['reset']}")
        if not args.no_chairman and label_to_model:
            for label, model_key in label_to_model.items():
                _print(f"  {label} → {MODELS[model_key]['name']}")
            _print()
        for key, panelist_name in blind_map.items():
            _print(f"  {panelist_name} → {MODELS[key]['name']}")

        transcript.append("\n## Reveal\n")
        if not args.no_chairman and label_to_model:
            for label, model_key in label_to_model.items():
                transcript.append(f"- {label} → {MODELS[model_key]['name']}\n")
        for key, panelist_name in blind_map.items():
            transcript.append(f"- {panelist_name} → {MODELS[key]['name']}\n")

    # ── Save artifacts ───────────────────────────────────────────────────
    artifact_paths = None
    if not args.no_save:
        markdown_path, html_path = resolve_artifact_paths(args.save)
        transcript_markdown = "\n".join(transcript)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(transcript_markdown, encoding="utf-8")
        html_path.write_text(build_html_transcript(transcript_markdown), encoding="utf-8")
        artifact_paths = {"markdown": str(markdown_path), "html": str(html_path)}
        _print(f"\n{C['system']}Transcript saved to {markdown_path}{C['reset']}")
        _print(f"{C['system']}HTML report saved to {html_path}{C['reset']}")

    # ── JSON output ─────────────────────────────────────────────────────
    if JSON_MODE:
        json_output = {
            "question": question,
            "models": [k for k in active_models if any(r["responses"].get(k) for r in json_rounds)],
            "deliberation_rounds": args.rounds,
            "rounds": json_rounds,
        }
        if crux_text:
            json_output["crux"] = crux_text
        if red_team_key:
            json_output["red_team"] = red_team_key
        if json_analysis:
            json_output["analysis"] = json_analysis
        if not args.no_chairman and json_review:
            json_output["review"] = json_review
        if not args.no_chairman and json_synthesis:
            json_output["synthesis"] = json_synthesis
        if artifact_paths:
            json_output["artifacts"] = artifact_paths
        json_output["total_elapsed"] = round(time.time() - pipeline_start, 1)
        print(json.dumps(json_output, ensure_ascii=False))
    else:
        _print(f"\n{C['bold']}Think Tank session complete.{C['reset']}\n")


if __name__ == "__main__":
    main()

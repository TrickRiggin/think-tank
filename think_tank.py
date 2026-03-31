#!/usr/bin/env python3
"""Think Tank — Multi-model deliberation tool.

Run from any repo directory. Auto-detects CLAUDE.md for context.

Usage:
    think_tank "Your question here"
    think_tank --files src/App.jsx,src/utils.js "How should we refactor?"
    think_tank --deep --rounds 2 "What's our strategy?"
    think_tank --interactive "Let's design a new feature"
"""

import argparse
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
    """Load API keys from .env files (home dir + cwd). No dependencies needed."""
    env_paths = [
        Path.home() / ".env",
        Path.home() / ".think_tank.env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            # Map friendly names -> expected env var names
            key_aliases = {
                "OpenAI":      "OPENAI_API_KEY",
                "Anthropic":   "ANTHROPIC_API_KEY",
                "Gemini":      "GOOGLE_AI_API_KEY",
                "xAI":         "XAI_API_KEY",
                "OpenRouter":  "OPENROUTER_API_KEY",
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
                        # Remap friendly names to standard env var names
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
        "name":     "Claude Opus 4.6",
        "model_id": "claude-opus-4-6",
        "env_key":  "ANTHROPIC_API_KEY",
        "openrouter_id": "anthropic/claude-opus-4-6",
    },
    "gpt": {
        "name":     "GPT-5.4",
        "model_id": "gpt-5.4",
        "env_key":  "OPENAI_API_KEY",
        "openrouter_id": "openai/gpt-5.4",
    },
    "gemini": {
        "name":     "Gemini 3.1 Pro",
        "model_id": "gemini-3.1-pro-preview",
        "env_key":  "GOOGLE_AI_API_KEY",
        "openrouter_id": "google/gemini-3.1-pro-preview",
    },
    "grok": {
        "name":     "Grok 4.20",
        "model_id": "grok-4.20-0309-non-reasoning",
        "env_key":  "XAI_API_KEY",
        "openrouter_id": "x-ai/grok-4.20-0309-non-reasoning",
    },
}

# ── API callers ──────────────────────────────────────────────────────────────

import requests

def call_claude(messages, api_key):
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    system_text = "\n\n".join(system_parts)
    api_messages = [m for m in messages if m["role"] != "system"]

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODELS["claude"]["model_id"],
            "max_tokens": 4096,
            "system": system_text,
            "messages": api_messages,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def call_gpt(messages, api_key):
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODELS["gpt"]["model_id"],
            "max_completion_tokens": 4096,
            "messages": messages,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_gemini(messages, api_key):
    system_text = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n\n"
        elif m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})

    body = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 4096},
    }
    if system_text.strip():
        body["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}

    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS['gemini']['model_id']}:generateContent",
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def call_grok(messages, api_key):
    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODELS["grok"]["model_id"],
            "max_completion_tokens": 4096,
            "messages": messages,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def call_openrouter(messages, api_key, model_id):
    """Route any model through OpenRouter (OpenAI-compatible API)."""
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


CALLERS = {"claude": call_claude, "gpt": call_gpt, "gemini": call_gemini, "grok": call_grok}


def resolve_api(key):
    """Resolve caller + key for a model. Direct API keys take priority; OpenRouter is fallback."""
    direct_key = os.environ.get(MODELS[key]["env_key"])
    if direct_key:
        return CALLERS[key], direct_key, False
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        or_id = MODELS[key]["openrouter_id"]
        return lambda msgs, ak: call_openrouter(msgs, ak, or_id), or_key, True
    return None, None, False

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


def build_context(args):
    """Build context from auto-detected files + args."""
    sections = []
    token_report = []

    # Auto-detect CLAUDE.md
    claude_md = find_up("CLAUDE.md")
    if claude_md:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
        sections.append(f"# Project Context (CLAUDE.md)\n\n{text}")
        token_report.append(f"CLAUDE.md (~{estimate_tokens(text):,} tokens)")

    # --deep: include memory files
    if args.deep:
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

DELIBERATION_PROMPT = """Here's what the other models said in the previous round:

{other_responses}

Now respond to their points. Where do you agree? Where are they wrong? \
What did they miss? Build on good ideas, challenge weak ones. Be specific."""

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
        or_models = set()
        for key in active_models:
            caller, api_key, via_or = resolve_api(key)
            if not caller:
                _print(f"\n  {C['err']}{MODELS[key]['name']}: no API key or OpenRouter fallback{C['reset']}")
                continue
            if via_or:
                or_models.add(key)
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
                if key in or_models:
                    display_name += " (via OpenRouter)"
                show_response(key, text, elapsed, display_name)
            except Exception as e:
                error_detail = str(e)
                # Try to extract API error message
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.json()
                    except Exception:
                        error_detail = e.response.text[:500]
                _print(f"\n  {C['err']}{MODELS[key]['name']} failed: {error_detail}{C['reset']}")
                results[key] = None

            remaining = len(futures) - completed
            if remaining > 0:
                waiting = [get_display_name(futures[f], blind_map) for f in futures if not f.done()]
                _print(f"\n{C['dim']}  Waiting for {', '.join(waiting)}...{C['reset']}", end="", flush=True)

    total_time = time.time() - start
    total_tokens = sum(estimate_tokens(r) for r in results.values() if r)
    _print(f"\n\n{C['system']}  Round {round_num} complete · {total_time:.1f}s · ~{total_tokens:,} output tokens{C['reset']}")

    return results, timings


def build_deliberation_message(results, exclude_key):
    """Build the 'here's what others said' message for a model."""
    parts = []
    for key, text in results.items():
        if key != exclude_key and text:
            parts.append(f"**{MODELS[key]['name']}:**\n{text}")
    return DELIBERATION_PROMPT.format(other_responses="\n\n---\n\n".join(parts))


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

    for _reviewer, ranking in all_rankings:
        for pos, label in enumerate(ranking, start=1):
            if label in label_to_model:
                model_key = label_to_model[label]
                positions[model_key].append(pos)

    aggregate = []
    for model_key, pos_list in positions.items():
        avg = sum(pos_list) / len(pos_list)
        aggregate.append((model_key, round(avg, 2), len(pos_list)))

    aggregate.sort(key=lambda x: x[1])
    return aggregate


def run_review(results, active_models, question, context, blind_map=None):
    """Run anonymized peer review stage.

    Returns:
        tuple: (all_rankings, label_to_model, aggregate, review_texts)
    """
    anonymized, label_to_model = anonymize_responses(results, active_models)

    # Build responses text block
    responses_text = "\n\n---\n\n".join(
        f"{label}:\n{text}" for label, text in anonymized.items()
    )

    # Build ranking slot placeholder
    ranking_slots = "\n".join(
        f"{i}. Response X" for i in range(1, len(anonymized) + 1)
    )

    # Select prompt template
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

    review_messages = [
        {"role": "system", "content": "You are a careful, objective evaluator."},
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
            caller, api_key, _via_or = resolve_api(key)
            if not caller:
                continue
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
                _print(f"\n  {C['err']}{MODELS[key]['name']} review failed: {error_detail}{C['reset']}")

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

def run_analysis(results, active_models, question, context, chairman_key, blind_map=None):
    """Run structured disagreement analysis. Returns analysis text or None on failure."""
    responses_text = "\n\n---\n\n".join(
        f"**{MODELS[key]['name']}:**\n{results[key]}"
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

    analysis_messages = [
        {"role": "system", "content": "You are an expert analyst. Extract the structure of agreement and disagreement from multi-model responses. Be precise and specific."},
        {"role": "user", "content": prompt_text},
    ]

    header("Analysis (Structured Disagreement)")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for analysis...{C['reset']}", end="", flush=True)

    caller, api_key, via_or = resolve_api(chairman_key)
    if not caller:
        _print(f"\n  {C['err']}Analysis: {MODELS[chairman_key]['name']} — no API key or OpenRouter fallback{C['reset']}")
        return None

    try:
        text = caller(analysis_messages, api_key)
        elapsed = time.time() - start
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        display_name = get_display_name(chairman_key, blind_map)
        if via_or:
            display_name += " (via OpenRouter)"
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

CHAIRMAN_PROMPT_PROJECT = """You are the chairman of a {model_count}-model think tank. Your job is to \
synthesize the best possible answer from the council's work.

Original question: {question}

Project context:
{context}

Individual responses:
{responses_text}

Peer rankings:
{rankings_text}

Structured analysis:
{analysis_text}

Synthesize a single, definitive answer. Prioritize:
- Points where multiple models agreed (see CONSENSUS above)
- Resolving the identified disagreements with clear reasoning
- Addressing unresolved gaps where possible
- Insights from higher-ranked responses
- Concrete, actionable recommendations

Be direct. This is the final word."""

CHAIRMAN_PROMPT_GENERAL = """You are the chairman of a {model_count}-model think tank. Your job is to \
synthesize the best possible answer from the council's work.

Original question: {question}

Individual responses:
{responses_text}

Peer rankings:
{rankings_text}

Structured analysis:
{analysis_text}

Synthesize a single, definitive answer. Prioritize:
- Points where multiple models agreed (see CONSENSUS above)
- Resolving the identified disagreements with clear reasoning
- Addressing unresolved gaps where possible
- Insights from higher-ranked responses
- Concrete, actionable recommendations

Be direct. This is the final word."""


def run_chairman(results, active_models, aggregate, question, context, chairman_key, analysis_text=None):
    """Run chairman synthesis stage. Returns synthesized text or None on failure."""
    responses_text = "\n\n---\n\n".join(
        f"**{MODELS[key]['name']}:**\n{results[key]}"
        for key in active_models if results.get(key)
    )

    rankings_text = "\n".join(
        f"  {rank}. {MODELS[mk]['name']} — avg rank {avg}"
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

    chairman_messages = [
        {"role": "system", "content": "You are the chairman of a multi-model think tank. Synthesize the council's work into a single authoritative answer."},
        {"role": "user", "content": prompt_text},
    ]

    header(f"Chairman Synthesis ({MODELS[chairman_key]['name']})")
    start = time.time()
    _print(f"\n{C['dim']}  Waiting for chairman...{C['reset']}", end="", flush=True)

    caller, api_key, via_or = resolve_api(chairman_key)
    if not caller:
        _print(f"\n  {C['err']}Chairman {MODELS[chairman_key]['name']}: no API key or OpenRouter fallback{C['reset']}")
        return None

    try:
        text = caller(chairman_messages, api_key)
        elapsed = time.time() - start
        _print(f"\r{' ' * 60}\r", end="", flush=True)
        model_header(chairman_key, elapsed)
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
               '  think_tank --files src/App.jsx --rounds 2 "Split this component?"\n'
               '  think_tank --deep --interactive "2027 strategy discussion"',
    )
    parser.add_argument("question", nargs="?", help="Your question (or use --prompt-file)")
    parser.add_argument("--prompt-file", "-pf", help="Read question from file")
    parser.add_argument("--files", "-f", help="Comma-separated files to include as context")
    parser.add_argument("--deep", "-d", action="store_true", help="Include MEMORY.md")
    parser.add_argument("--rounds", "-r", type=int, default=1, help="Deliberation rounds (default: 1)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive follow-up mode")
    parser.add_argument("--save", "-s", help="Save transcript to file")
    parser.add_argument("--no-context", action="store_true", help="Skip auto-detecting CLAUDE.md")
    parser.add_argument("--models", "-m", help="Comma-separated model keys (claude,gpt,gemini,grok)")
    parser.add_argument("--chairman", "-c", default="claude",
                        help="Model key for chairman synthesis (default: claude)")
    parser.add_argument("--blind", "-b", action="store_true",
                        help="Hide model identities until reveal at end")
    parser.add_argument("--no-chairman", action="store_true",
                        help="Skip review + synthesis stages")
    parser.add_argument("--json", action="store_true",
                        help="Output structured JSON (suppress terminal display)")

    args = parser.parse_args()

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
            print(f"{C['err']}Unknown models: {', '.join(invalid)}. Use: claude, gpt, gemini, grok{C['reset']}")
            sys.exit(1)
    else:
        active_models = list(MODELS.keys())

    # Validate chairman
    if args.chairman not in MODELS:
        print(f"{C['err']}Unknown chairman: {args.chairman}. Use: {', '.join(MODELS.keys())}{C['reset']}")
        sys.exit(1)

    model_count = len(active_models)

    # Check API keys (direct key OR OpenRouter fallback)
    or_key = os.environ.get("OPENROUTER_API_KEY")
    missing = [k for k in active_models if not os.environ.get(MODELS[k]["env_key"]) and not or_key]
    if missing:
        for k in missing:
            print(f"{C['err']}Missing: {MODELS[k]['env_key']} (for {MODELS[k]['name']}) — no OpenRouter fallback{C['reset']}")
        active_models = [k for k in active_models if k not in missing]
        if not active_models:
            print(f"\n{C['err']}No models available. Set API keys or OPENROUTER_API_KEY.{C['reset']}")
            sys.exit(1)
        print(f"\n{C['system']}Continuing with: {', '.join(MODELS[k]['name'] for k in active_models)}{C['reset']}")

    # Build context
    if args.no_context:
        context = ""
        token_report = []
    else:
        context, token_report = build_context(args)

    # Display header
    header("Think Tank")
    model_names = " · ".join(MODELS[k]["name"] for k in active_models)
    _print(f"  {C['bold']}Models:{C['reset']} {model_names}")
    if token_report:
        _print(f"  {C['bold']}Context:{C['reset']} {', '.join(token_report)}")
    else:
        _print(f"  {C['dim']}No project context detected (run from a repo with CLAUDE.md){C['reset']}")
    q_preview = question[:120] + ("..." if len(question) > 120 else "")
    _print(f"  {C['bold']}Question:{C['reset']} {q_preview}")
    if args.rounds > 1:
        _print(f"  {C['bold']}Rounds:{C['reset']} {args.rounds}")
    if args.interactive:
        _print(f"  {C['bold']}Mode:{C['reset']} Interactive")
    if not args.no_chairman:
        _print(f"  {C['bold']}Chairman:{C['reset']} {MODELS[args.chairman]['name']}")
    if args.blind:
        _print(f"  {C['bold']}Mode:{C['reset']} Blind (identities hidden until reveal)")
    if or_key:
        or_routed = [MODELS[k]["name"] for k in active_models if not os.environ.get(MODELS[k]["env_key"])]
        if or_routed:
            _print(f"  {C['dim']}OpenRouter fallback: {', '.join(or_routed)}{C['reset']}")

    blind_map = create_blind_mapping(active_models) if args.blind else None

    # Build initial messages
    system_template = SYSTEM_PROMPT_PROJECT if context else SYSTEM_PROMPT_GENERAL
    system_msg = system_template.format(model_count=model_count)
    user_content = question
    if context:
        user_content = f"{context}\n\n---\n\n# Question\n\n{question}"

    # Initialize per-model conversation histories
    conversations = {}
    for key in active_models:
        conversations[key] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ]

    # Transcript for --save
    transcript = []
    transcript.append(f"# Think Tank — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    transcript.append(f"**Question:** {question}\n")
    model_names_str = ", ".join(get_display_name(k, blind_map) for k in active_models)
    transcript.append(f"**Models:** {model_names_str}\n")
    if not args.no_chairman:
        transcript.append(f"**Chairman:** {MODELS[args.chairman]['name']}\n")

    # ── JSON collection ─────────────────────────────────────────────────
    json_rounds = []
    json_review = None
    json_analysis = None
    json_synthesis = None
    pipeline_start = time.time()

    # ── Round loop ───────────────────────────────────────────────────────
    total_rounds = args.rounds
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

            if round_num < args.rounds:
                # Auto-continue to next deliberation round
                for key in active_models:
                    if results.get(key):
                        delib_msg = build_deliberation_message(results, key)
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
                            delib_msg = build_deliberation_message(results, key)
                            conversations[key].append({"role": "user", "content": delib_msg})
                else:
                    # User typed a follow-up question
                    # Include other models' responses + new question
                    for key in active_models:
                        if results.get(key):
                            other_context = build_deliberation_message(results, key)
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
            args.chairman, blind_map,
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
            final_responses, active_models, question, context, blind_map,
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
            question, context, args.chairman, analysis_text,
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

    # ── Save transcript ──────────────────────────────────────────────────
    if args.save:
        save_path = Path(args.save)
        save_path.write_text("\n".join(transcript), encoding="utf-8")
        _print(f"\n{C['system']}Transcript saved to {save_path}{C['reset']}")

    # ── JSON output ─────────────────────────────────────────────────────
    if JSON_MODE:
        json_output = {
            "question": question,
            "models": [k for k in active_models if any(r["responses"].get(k) for r in json_rounds)],
            "rounds": json_rounds,
        }
        if json_analysis:
            json_output["analysis"] = json_analysis
        if not args.no_chairman and json_review:
            json_output["review"] = json_review
        if not args.no_chairman and json_synthesis:
            json_output["synthesis"] = json_synthesis
        json_output["total_elapsed"] = round(time.time() - pipeline_start, 1)
        print(json.dumps(json_output, ensure_ascii=False))
    else:
        _print(f"\n{C['bold']}Think Tank session complete.{C['reset']}\n")


if __name__ == "__main__":
    main()

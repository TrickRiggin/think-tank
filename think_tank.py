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
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


def load_env_files():
    """Load API keys from .env files (home dir + cwd). No dependencies needed."""
    env_paths = [
        Path.home() / "AI Stuff" / "keys.env",
        Path.home() / ".env",
        Path.home() / ".think_tank.env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            # Map friendly names -> expected env var names
            key_aliases = {
                "OpenAI":    "OPENAI_API_KEY",
                "Anthropic": "ANTHROPIC_API_KEY",
                "Gemini":    "GOOGLE_AI_API_KEY",
                "xAI":       "XAI_API_KEY",
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
    },
    "gpt": {
        "name":     "GPT-5.4",
        "model_id": "gpt-5.4",
        "env_key":  "OPENAI_API_KEY",
    },
    "gemini": {
        "name":     "Gemini 3.1 Pro",
        "model_id": "gemini-3.1-pro-preview",
        "env_key":  "GOOGLE_AI_API_KEY",
    },
    "grok": {
        "name":     "Grok 4",
        "model_id": "grok-4",
        "env_key":  "XAI_API_KEY",
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


CALLERS = {"claude": call_claude, "gpt": call_gpt, "gemini": call_gemini, "grok": call_grok}

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
            print(f"  {C['dim']}(--deep: no memory directory found){C['reset']}")

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
                print(f"  {C['err']}Warning: {filepath} not found, skipping{C['reset']}")

    context = "\n\n---\n\n".join(sections) if sections else ""
    return context, token_report


# ── Display ──────────────────────────────────────────────────────────────────

def header(text):
    try:
        width = min(os.get_terminal_size().columns, 80)
    except OSError:
        width = 80
    bar = "━" * width
    print(f"\n{C['bold']}{bar}{C['reset']}")
    print(f"{C['bold']}  {text}{C['reset']}")
    print(f"{C['bold']}{bar}{C['reset']}\n")


def model_header(model_key, elapsed=None):
    info = MODELS[model_key]
    color = C[model_key]
    time_str = f" ({elapsed:.1f}s)" if elapsed else ""
    print(f"\n{color}{C['bold']}▌ {info['name']}{time_str}{C['reset']}")
    print(f"{color}{'─' * 40}{C['reset']}")


def show_response(model_key, text, elapsed=None):
    model_header(model_key, elapsed)
    print(text)


def spinner_frames():
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while True:
        yield frames[i % len(frames)]
        i += 1


# ── Core logic ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are one voice in a {model_count}-model think tank. The user has a question \
about a software project. They've provided project context below.

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


def run_round(conversations, active_models, round_num):
    """Run one round of parallel API calls. Returns {model_key: response_text}."""
    results = {}
    start = time.time()

    print(f"\n{C['dim']}  Waiting for models...{C['reset']}", end="", flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {}
        for key in active_models:
            api_key = os.environ.get(MODELS[key]["env_key"])
            if not api_key:
                print(f"\n  {C['err']}{MODELS[key]['name']}: missing {MODELS[key]['env_key']}{C['reset']}")
                continue
            futures[pool.submit(CALLERS[key], conversations[key], api_key)] = key

        completed = 0
        for future in as_completed(futures):
            key = futures[future]
            elapsed = time.time() - start
            completed += 1

            # Clear "waiting" line
            print(f"\r{' ' * 60}\r", end="", flush=True)

            try:
                text = future.result()
                results[key] = text
                show_response(key, text, elapsed)
            except Exception as e:
                error_detail = str(e)
                # Try to extract API error message
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.json()
                    except Exception:
                        error_detail = e.response.text[:500]
                print(f"\n  {C['err']}{MODELS[key]['name']} failed: {error_detail}{C['reset']}")
                results[key] = None

            remaining = len(futures) - completed
            if remaining > 0:
                waiting = [MODELS[futures[f]]["name"] for f in futures if not f.done()]
                print(f"\n{C['dim']}  Waiting for {', '.join(waiting)}...{C['reset']}", end="", flush=True)

    total_time = time.time() - start
    total_tokens = sum(estimate_tokens(r) for r in results.values() if r)
    print(f"\n\n{C['system']}  Round {round_num} complete · {total_time:.1f}s · ~{total_tokens:,} output tokens{C['reset']}")

    return results


def build_deliberation_message(results, exclude_key):
    """Build the 'here's what others said' message for a model."""
    parts = []
    for key, text in results.items():
        if key != exclude_key and text:
            parts.append(f"**{MODELS[key]['name']}:**\n{text}")
    return DELIBERATION_PROMPT.format(other_responses="\n\n---\n\n".join(parts))


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

    args = parser.parse_args()

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

    model_count = len(active_models)

    # Check API keys
    missing = [k for k in active_models if not os.environ.get(MODELS[k]["env_key"])]
    if missing:
        for k in missing:
            print(f"{C['err']}Missing env var: {MODELS[k]['env_key']} (for {MODELS[k]['name']}){C['reset']}")
        active_models = [k for k in active_models if k not in missing]
        if not active_models:
            print(f"\n{C['err']}No models available. Set API key environment variables.{C['reset']}")
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
    print(f"  {C['bold']}Models:{C['reset']} {model_names}")
    if token_report:
        print(f"  {C['bold']}Context:{C['reset']} {', '.join(token_report)}")
    else:
        print(f"  {C['dim']}No project context detected (run from a repo with CLAUDE.md){C['reset']}")
    q_preview = question[:120] + ("..." if len(question) > 120 else "")
    print(f"  {C['bold']}Question:{C['reset']} {q_preview}")
    if args.rounds > 1:
        print(f"  {C['bold']}Rounds:{C['reset']} {args.rounds}")
    if args.interactive:
        print(f"  {C['bold']}Mode:{C['reset']} Interactive")

    # Build initial messages
    system_msg = SYSTEM_PROMPT.format(model_count=model_count)
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

    # ── Round loop ───────────────────────────────────────────────────────
    total_rounds = args.rounds
    if args.interactive:
        total_rounds = 999  # effectively unlimited

    round_num = 0
    while round_num < total_rounds:
        round_num += 1
        header(f"Round {round_num}")

        results = run_round(conversations, active_models, round_num)

        # Save to transcript
        transcript.append(f"\n## Round {round_num}\n")
        for key in active_models:
            if results.get(key):
                transcript.append(f"### {MODELS[key]['name']}\n{results[key]}\n")

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
                print(f"\n{C['system']}{'─' * 50}{C['reset']}")
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

    # ── Save transcript ──────────────────────────────────────────────────
    if args.save:
        save_path = Path(args.save)
        save_path.write_text("\n".join(transcript), encoding="utf-8")
        print(f"\n{C['system']}Transcript saved to {save_path}{C['reset']}")

    print(f"\n{C['bold']}Think Tank session complete.{C['reset']}\n")


if __name__ == "__main__":
    main()

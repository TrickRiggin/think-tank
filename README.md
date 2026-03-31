# Think Tank

Multi-model deliberation tool. Sends one prompt to Claude Opus 4.6, GPT-5.4, and Gemini 3.1 Pro in parallel. Optional multi-round deliberation where models see and challenge each other's responses.

## Setup

- **API Keys**: Loaded from `~/AI Stuff/keys.env` (also set as Windows user environment variables)
- **PowerShell alias**: `think_tank` works from any directory (defined in PowerShell profile)
- **Bash alias**: `think_tank` works in Git Bash (defined in `~/.bashrc`)
- **Context**: Auto-detects `CLAUDE.md` when run from inside a repo directory

## Usage

```
think_tank "Your question here"
```

Run from inside a repo directory to auto-include project context.

## Flags

| Flag | Short | Value | What it does |
|------|-------|-------|-------------|
| `--deep` | `-d` | — | Include MEMORY.md from .claude project memory |
| `--rounds N` | `-r N` | number | Deliberation rounds (models respond to each other) |
| `--files x,y` | `-f x,y` | paths | Include specific files as context |
| `--save path` | `-s path` | filepath | Save full transcript to file |
| `--interactive` | `-i` | — | Open-ended mode with follow-up prompts |
| `--models a,b` | `-m a,b` | names | Use specific models only (claude, gpt, gemini) |
| `--no-context` | — | — | Skip auto-detecting CLAUDE.md |
| `--prompt-file` | `-pf` | filepath | Read question from a file instead of command line |

## Examples

```bash
# Quick question, all 3 models, auto-context from repo
think_tank "Should we split this into microservices?"

# Include specific source files for a code question
think_tank -f src/App.jsx,src/utils.js "How should we refactor the tab system?"

# 2-round deliberation — models challenge each other in round 2
think_tank -r 2 "What's the right caching strategy here?"

# Deep mode (CLAUDE.md + MEMORY.md) with transcript saved
think_tank -d -r 2 -s ~/transcripts/architecture.md "Long-term scaling plan?"

# Interactive session — keep asking follow-ups
think_tank -i "Let's design a new feature"

# Only ask Claude and GPT
think_tank -m claude,gpt "Quick sanity check on this approach"

# No project context, just a general question
think_tank --no-context "Compare Redis vs Memcached for session storage"
```

## How It Works

1. Auto-detects `CLAUDE.md` by walking up from current directory (like git)
2. Sends your question + context to all models in parallel
3. Displays responses as they arrive (color-coded per model in terminal)
4. If `--rounds` > 1: feeds each model the others' responses and asks them to challenge/build on the ideas
5. If `--interactive`: prompts you after each round — press Enter to trigger deliberation, type a follow-up, or `q` to quit

## Tips

- **`--rounds 1`** (default): Good for getting three independent perspectives fast
- **`--rounds 2`**: The sweet spot — models correct each other's mistakes and sharpen their reasoning
- **`--rounds 3`**: Diminishing returns, but useful for contentious design decisions
- **`--interactive`**: Best for exploratory sessions where you want to steer the conversation
- **`cd` into the repo first** — context auto-detection needs to find CLAUDE.md
- The `--save` transcripts are great for referencing later or sharing with collaborators

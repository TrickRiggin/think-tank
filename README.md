# Think Tank

Multi-model deliberation tool. Sends one prompt to Claude Opus 4.6, GPT-5.4, Gemini 3.1 Pro, and Grok 4.20 in parallel. Optional multi-round deliberation, anonymized peer review, and chairman synthesis.

## Setup

- **API Keys**: Loaded from `~/.env`, `~/.think_tank.env`, or `./.env` (searches multiple locations; also works with Windows user environment variables)
- **Shell alias**: `think_tank` works from any directory (define in your shell profile)
- **Context**: Auto-detects `CLAUDE.md` when run from inside a repo directory

## Usage

```
think_tank "Your question here"
```

Run from inside a repo directory to auto-include project context.

## Pipeline

```
Stage 1: COLLECT      All models answer in parallel
Stage 2: DELIBERATE   Optional rounds where models challenge each other (--rounds)
Stage 3: ANALYZE      Chairman extracts consensus, disagreements, unresolved gaps
Stage 4: REVIEW       Anonymized peer ranking (Response A/B/C/D)
Stage 5: SYNTHESIZE   Chairman produces final answer (default: Claude Opus 4.6)
```

Stages 4-5 run by default. Use `--no-chairman` to skip them (analysis still runs if 2+ models responded).

## Flags

| Flag | Short | Value | What it does |
|------|-------|-------|-------------|
| `--chairman` | `-c` | model key | Which model synthesizes the final answer (default: claude) |
| `--blind` | `-b` | — | Hide model identities until reveal at end |
| `--no-chairman` | | — | Skip review + synthesis stages (original behavior) |
| `--deep` | `-d` | — | Include MEMORY.md from .claude project memory |
| `--rounds N` | `-r N` | number | Deliberation rounds (models respond to each other) |
| `--files x,y` | `-f x,y` | paths | Include specific files as context |
| `--save path` | `-s path` | filepath | Save full transcript to file |
| `--interactive` | `-i` | — | Open-ended mode with follow-up prompts |
| `--models a,b` | `-m a,b` | names | Use specific models only (claude, gpt, gemini, grok) |
| `--no-context` | — | — | Skip auto-detecting CLAUDE.md (general questions mode) |
| `--prompt-file` | `-pf` | filepath | Read question from a file instead of command line |
| `--json` | — | — | Output structured JSON, suppress terminal display (used by MCP server) |

## Models

| Key | Model | Chairman-eligible |
|-----|-------|-------------------|
| `claude` | Claude Opus 4.6 | Yes (default chairman) |
| `gpt` | GPT-5.4 | Yes |
| `gemini` | Gemini 3.1 Pro | Yes |
| `grok` | Grok 4.20 | Yes |

## Examples

```bash
# Full pipeline — all 4 models, review, chairman synthesis
think_tank "Should we split this into microservices?"

# Include specific source files for a code question
think_tank -f src/App.jsx,src/utils.js "How should we refactor the tab system?"

# 2-round deliberation before review + synthesis
think_tank -r 2 "What's the right caching strategy here?"

# Blind mode — hide model identities from yourself
think_tank -b "Which database should we use for this workload?"

# Use Gemini as chairman instead of Claude
think_tank -c gemini "Compare these two architectures"

# Skip review + synthesis — just get raw responses (original behavior)
think_tank --no-chairman "Quick sanity check"

# Deep mode with transcript saved
think_tank -d -r 2 -s ~/transcripts/architecture.md "Long-term scaling plan?"

# Interactive session
think_tank -i "Let's design a new feature"

# General question (no project context)
think_tank --no-context "Compare Redis vs Memcached for session storage"

# Only ask Claude and GPT
think_tank -m claude,gpt "Quick sanity check on this approach"
```

## API Keys

Each model needs its own API key, set via environment variable:

| Model | Env Var |
|-------|---------|
| Claude | `ANTHROPIC_API_KEY` |
| GPT | `OPENAI_API_KEY` |
| Gemini | `GOOGLE_AI_API_KEY` |
| Grok | `XAI_API_KEY` |

### OpenRouter Fallback

If `OPENROUTER_API_KEY` is set, any model missing its direct API key automatically routes through [OpenRouter](https://openrouter.ai). Direct keys always take priority — OpenRouter fills the gaps.

- All 4 direct keys set: OpenRouter never used
- Only `OPENROUTER_API_KEY`: all models route through OpenRouter
- Mixed: direct keys where available, OpenRouter for the rest

## MCP Server (Claude Code Integration)

`mcp_server.py` wraps Think Tank as an MCP server so Claude Code can call it as a native tool mid-conversation.

### Tools

| Tool | What it does |
|------|-------------|
| `think_tank_light` | 4 models answer in parallel, no review/synthesis |
| `think_tank_heavy` | Full pipeline: deliberation + review + chairman synthesis |

Both accept a question, optional file paths, and an optional working directory for CLAUDE.md auto-detection.

### Setup

Register globally (all Claude Code sessions):

```bash
claude mcp add -s user think-tank -- python /path/to/think-tank/mcp_server.py
```

Requires the `mcp` pip package (`pip install mcp`).

## How It Works

1. Auto-detects `CLAUDE.md` by walking up from current directory (like git)
2. Sends your question + context to all models in parallel
3. Displays responses as they arrive (color-coded per model in terminal)
4. If `--rounds` > 1: feeds each model the others' responses for deliberation
5. **Analysis**: Chairman extracts consensus points, disagreements, and unresolved gaps
6. **Review**: Anonymizes all responses as Response A/B/C/D (randomly shuffled), each model evaluates and ranks them
7. **Synthesis**: Chairman model takes all responses + analysis + rankings and produces the final answer
8. If `--blind`: reveals model identity mapping at the very end

## Tips

- **`--rounds 1`** (default): Good for getting four independent perspectives fast
- **`--rounds 2`**: The sweet spot — models correct each other, then get reviewed
- **`--no-chairman`**: When you just want raw deliberation without the extra API calls
- **`--blind`**: Forces you to evaluate responses without model bias before the reveal
- **`--no-context`**: Your general-purpose mode for non-coding questions
- **`cd` into the repo first** — context auto-detection needs to find CLAUDE.md
- The `--save` transcripts include everything: responses, reviews, rankings, and synthesis

# Think Tank

CLI multi-model deliberation tool. Sends one prompt to Claude Opus 4.7, GPT-5.5, Gemini 3.1 Pro, and DeepSeek V4 Pro in parallel through OpenRouter. Optional crux framing, deliberation rounds, anonymized peer review, and Grok 4.20 chairman synthesis. Every run saves a markdown transcript and a polished HTML report by default.

## Setup

- **API Key**: Set `OPENROUTER_API_KEY` in `~/.env`, `~/.think_tank.env`, or `./.env` (searches multiple locations; also works with Windows user environment variables)
- **Shell alias**: Add to your shell profile so `think_tank` works from any directory:
  ```bash
  # Bash (~/.bashrc)
  alias think_tank="python3 /path/to/think-tank/think_tank.py"

  # Zsh (~/.zshrc)
  alias think_tank="python3 /path/to/think-tank/think_tank.py"

  # PowerShell ($PROFILE)
  function think_tank { python "C:\path\to\think-tank\think_tank.py" @args }
  ```
- **Context**: Auto-detects `CLAUDE.md` when run from inside a repo directory

## Usage

```
think_tank "Your question here"
```

Run from inside a repo directory to auto-include project context.

## Pipeline

```
Stage 0: CRUX        Optional framing pass (--crux)
Stage 1: COLLECT      Default council answers in parallel
Stage 2: DELIBERATE   Optional rounds where models challenge each other (--rounds)
Stage 3: ANALYZE      Chairman extracts consensus, disagreements, unresolved gaps
Stage 4: REVIEW       Leave-one-out anonymized peer ranking (Response A/B/C/D)
Stage 5: SYNTHESIZE   Grok 4.20 chairman compiles the final answer
```

Stages 4-5 run by default. Use `--no-chairman` to skip them (analysis still runs if 2+ models responded).

## Flags

| Flag | Short | Value | What it does |
|------|-------|-------|-------------|
| `--chairman` | `-c` | model key | Which model synthesizes the final answer (default: grok) |
| `--blind` | `-b` | — | Hide model identities until reveal at end |
| `--no-chairman` | | — | Skip review + synthesis stages; analysis still runs with 2+ responses |
| `--crux` | | — | Run a framing pass before collection |
| `--red-team MODEL` | `-R` | model key | Assign one model an adversarial critique role |
| `--deep` | `-d` | — | Include MEMORY.md from .claude project memory |
| `--rounds N` | `-r N` | number | Deliberation rounds after the initial answer pass (default: 0) |
| `--files x,y` | `-f x,y` | paths | Include specific files as context |
| `--save [path]` | `-s [path]` | optional filepath | Choose the markdown/HTML artifact basename. Bare filenames go under `output/`; omit path for a timestamped file. |
| `--no-save` | | — | Skip markdown/HTML artifact writes for a throwaway run. |
| `--interactive` | `-i` | — | Open-ended mode with follow-up prompts |
| `--models a,b` | `-m a,b` | names | Use specific models only (claude, gpt, gemini, deepseek, grok) |
| `--no-context` | — | — | Skip auto project context; explicit `--files` still load |
| `--prompt-file` | `-pf` | filepath | Read question from a file instead of command line |
| `--json` | — | — | Output structured JSON, suppress terminal display |

## Models

| Key | Model | Chairman-eligible |
|-----|-------|-------------------|
| `claude` | Claude Opus 4.7 | Yes |
| `gpt` | GPT-5.5 | Yes |
| `gemini` | Gemini 3.1 Pro | Yes |
| `deepseek` | DeepSeek V4 Pro | Yes |
| `grok` | Grok 4.20 | Yes (default chairman, not in the default panel) |

## Examples

```bash
# Full pipeline — default 4-model panel, review, Grok chairman synthesis
think_tank "Should we split this into microservices?"

# Include specific source files for a code question
think_tank -f src/App.jsx,src/utils.js "How should we refactor the tab system?"

# Crux framing before collection
think_tank --crux "What's the right caching strategy here?"

# One deliberation round before review + synthesis
think_tank -r 1 "What's the right caching strategy here?"

# Adversarial critique from one model
think_tank -R gpt "Where could this migration plan fail?"

# Blind mode — hide model identities from yourself
think_tank -b "Which database should we use for this workload?"

# Use Claude as chairman instead of the default Grok
think_tank -c claude "Compare these two architectures"

# Skip review + synthesis
think_tank --no-chairman "Quick sanity check"

# Deep mode with crux framing and transcript saved
think_tank -d --crux -r 1 -s architecture.md "Long-term scaling plan?"

# Save to an explicit directory instead of output/
think_tank -s ~/transcripts/architecture.md "Long-term scaling plan?"

# Throwaway run with no markdown/HTML souvenirs
think_tank --no-save "Quick gut check?"

# Interactive session
think_tank -i "Let's design a new feature"

# General question (no project context)
think_tank --no-context "Compare Redis vs Memcached for session storage"

# Only ask Claude and DeepSeek
think_tank -m claude,deepseek "Quick sanity check on this approach"
```

## API Key

This repo now uses OpenRouter only. Set:

- `OPENROUTER_API_KEY`

Direct provider keys are no longer used by `think_tank.py`.

## How It Works

1. Auto-detects `CLAUDE.md` by walking up from current directory unless `--no-context` is set.
2. Loads explicit `--files` even when auto context is disabled.
3. If `--crux` is set, extracts cruxes, assumptions, and validation tests before collection.
4. Sends your question + context to all models in parallel.
5. If `--rounds N` is set, runs N deliberation rounds after the first answer pass.
6. **Analysis**: Chairman extracts consensus points, disagreements, unresolved gaps, and crux coverage.
7. **Review**: Anonymizes all responses as Response A/B/C/D; each model reviews only the other responses.
8. **Synthesis**: Chairman compiles the top-ranked response, dissent, analysis, and rankings into the final answer.
9. Saves a markdown transcript plus a standalone HTML report with the synthesis promoted to the top.
10. If `--blind`: reveals model identity mapping at the very end.

## Tips

- **Default**: Four independent perspectives, analysis, review, and synthesis.
- **`--crux`**: Best first add-on for architecture or strategy decisions.
- **`--rounds 1`**: One response-to-response pass before review.
- **`--no-chairman`**: When you want responses plus structured analysis without review/synthesis
- **`--blind`**: Forces you to evaluate responses without model bias before the reveal
- **`--no-context`**: Skip CLAUDE.md/deep memory; use with `--files` when you want only explicit context
- **`cd` into the repo first** — context auto-detection needs to find CLAUDE.md
- Markdown and HTML artifacts save by default under `output/`; use `--save name.md` to choose the basename or `--no-save` for a disposable run.
- The saved artifacts include everything: responses, reviews, rankings, and synthesis. The HTML report promotes the executive summary/final synthesis first and collapses the source material below.

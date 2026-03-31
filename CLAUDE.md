# Think Tank — CLAUDE.md

## What This Is

CLI multi-model deliberation tool. Sends a prompt to 4 LLMs in parallel, optional multi-round deliberation, anonymized peer review with structured rankings, and chairman synthesis. Single-file Python script, no web UI, no framework dependencies beyond `requests`.

## Architecture

Everything lives in `think_tank.py`. The pipeline:

```
Stage 1: COLLECT      — All 4 models answer in parallel (ThreadPoolExecutor)
Stage 2: DELIBERATE   — Optional rounds where models challenge each other (--rounds)
Stage 3: REVIEW       — Anonymized peer ranking (Response A/B/C/D, randomly shuffled)
Stage 4: SYNTHESIZE   — Chairman produces final answer (default: Claude Opus 4.6)
```

Stages 3-4 skip with `--no-chairman`. Context-adaptive prompts drop "software project" language when no CLAUDE.md is detected or `--no-context` is used.

## Models & API Callers

| Key | Model | API | Env Var |
|-----|-------|-----|---------|
| `claude` | Claude Opus 4.6 | Anthropic native | `ANTHROPIC_API_KEY` |
| `gpt` | GPT-5.4 | OpenAI native | `OPENAI_API_KEY` |
| `gemini` | Gemini 3.1 Pro | Google AI native | `GOOGLE_AI_API_KEY` |
| `grok` | Grok 4 | xAI (OpenAI-compatible) | `XAI_API_KEY` |

Each model has its own `call_*` function because each API has slightly different request/response formats. Grok reuses the OpenAI format with a different base URL. No OpenRouter — direct API calls only, by design.

## Key Design Decisions

### Anonymized Review (Stage 3)
- Models evaluate "Response A/B/C/D" — labels are randomly shuffled each run
- Each model produces a `FINAL RANKING:` section that gets parsed with regex
- Fallback parsing if models don't follow the exact format
- Aggregate scores computed as average rank position across all reviewers

### Chairman Synthesis (Stage 4)
- Default chairman is Claude Opus (`--chairman` flag to change)
- Chairman sees de-anonymized responses + aggregate rankings
- Chairman can be a council member (default) or external

### Blind Mode (--blind)
- Display-layer only — models still know each other during deliberation
- Separate random shuffle from the review-stage shuffle (prevents cross-referencing)
- Reveal section at the end maps both Panelist and Response labels to real names

### Context Detection
- `find_up("CLAUDE.md")` walks up from cwd like git
- `--deep` adds MEMORY.md from `.claude/projects/` memory dir
- `--files` for specific source files
- `--no-context` drops all project awareness (general questions mode)

### Env Loading
- Loads from `~/AI Stuff/keys.env`, `~/.env`, `~/.think_tank.env`, `./env`
- Maps friendly names (OpenAI, Anthropic, Gemini, xAI) to standard env var names
- Never overwrites already-set env vars

## File Structure

```
think-tank/
  think_tank.py          — the entire tool (single file)
  README.md              — usage docs, flags, examples
  .gitignore             — excludes env files, pycache
  CLAUDE.md              — this file
  docs/superpowers/
    specs/               — design spec from brainstorming session
    plans/               — implementation plan
```

## Running It

Aliases defined in PowerShell profile and `~/.bashrc` so `think_tank` works from any directory. When run from inside a repo, auto-detects CLAUDE.md for project context.

```bash
think_tank "Your question"                    # full pipeline, 4 models
think_tank --no-context "General question"    # no software context
think_tank --no-chairman "Quick opinions"     # skip review + synthesis (v1 behavior)
think_tank -r 2 -b -s out.md "Design Q"      # 2 rounds, blind, save transcript
```

## Development Notes

- Inspired by karpathy/llm-council but stays CLI-first and project-aware
- The user's original workflow was: run Think Tank, save transcript, manually feed to Claude for synthesis. v2 automates that last step.
- No tests — this is a personal tool, vibe-coded. Verify manually.
- `requests` is the only external dependency (stdlib otherwise + `random` for shuffling)

## Port Configuration

Backend only: 8001 was used by the Karpathy llm-council clone (separate project in `../llm-council/`). This tool has no server component.

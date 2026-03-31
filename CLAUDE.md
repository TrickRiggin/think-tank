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

Each model has its own `call_*` function because each API has slightly different request/response formats. Grok reuses the OpenAI format with a different base URL.

### OpenRouter Fallback

If `OPENROUTER_API_KEY` is set, any model missing its direct API key will automatically route through OpenRouter's OpenAI-compatible API. Direct keys always take priority — OpenRouter is purely a fallback.

- Someone with all 4 direct keys: zero behavior change
- Someone with only `OPENROUTER_API_KEY`: all 4 models route through OpenRouter
- Mixed: direct keys used where available, OpenRouter fills the gaps

The header and model display show "(via OpenRouter)" when a model is using the fallback. Routing is resolved by `resolve_api(key)` which returns the appropriate caller + key.

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
- Loads from `~/.env`, `~/.think_tank.env`, `./.env` (and any custom path in the ENV_PATHS list)
- Maps friendly names (OpenAI, Anthropic, Gemini, xAI) to standard env var names
- Never overwrites already-set env vars

## MCP Server (Claude Code Integration)

`mcp_server.py` wraps Think Tank as an MCP server so Claude Code can call it as a native tool mid-conversation.

### Tools Exposed
| Tool | What it does | Maps to |
|------|-------------|---------|
| `think_tank_light` | 4 models answer in parallel, no review/synthesis | `--no-chairman --json` |
| `think_tank_heavy` | Full pipeline: deliberation + review + chairman | `--rounds N --json` |

Both accept: `question` (required), `files` (optional), `cwd` (optional for CLAUDE.md detection).

### --json Flag
Added to `think_tank.py` — suppresses all terminal output, emits structured JSON to stdout:
```json
{
  "question": "...",
  "models": ["claude", "gpt", "gemini", "grok"],
  "rounds": [{"round": 1, "responses": {"claude": {"text": "...", "elapsed": 12.3}, ...}}],
  "review": {"rankings": [...], "label_map": {...}},
  "synthesis": "Chairman's final answer...",
  "total_elapsed": 45.2
}
```
Fields omitted when stages are skipped (light = no review/synthesis/deliberation).

### Registration
`~/.claude/.mcp.json`:
```json
{"mcpServers": {"think-tank": {"command": "python", "args": ["/path/to/think-tank/mcp_server.py"]}}}
```

### Key Details
- MCP server shells out to `think_tank.py --json` as a subprocess (no import refactoring)
- 5-minute timeout on subprocess calls
- `_print()` wrapper gates all terminal output on global `JSON_MODE` flag
- `run_round()` returns `(results, timings)` tuple to capture per-model elapsed time
- CLI behavior completely unchanged without `--json`
- Requires `mcp` pip package (`pip install mcp`)

## File Structure

```
think-tank/
  think_tank.py          — the entire tool (single file)
  mcp_server.py          — MCP server wrapper (Claude Code integration)
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

# Think Tank — CLAUDE.md

## What This Is

CLI multi-model deliberation tool. Sends a prompt to 4 LLMs in parallel through OpenRouter, optional multi-round deliberation, anonymized peer review with structured rankings, and chairman synthesis. Single-file Python script, no web UI, no framework dependencies beyond `requests`.

## Architecture

Everything lives in `think_tank.py`. The pipeline:

```
Stage 1: COLLECT      — All 4 models answer in parallel (ThreadPoolExecutor)
Stage 2: DELIBERATE   — Optional rounds where models challenge each other (--rounds)
Stage 3: ANALYZE      — Chairman extracts consensus, disagreements, unresolved gaps
Stage 4: REVIEW       — Anonymized peer ranking (Response A/B/C/D, randomly shuffled)
Stage 5: SYNTHESIZE   — Chairman produces final answer with analysis + rankings as input
```

Stages 4-5 skip with `--no-chairman`. Stage 3 (analysis) still runs with `--no-chairman` if 2+ models responded. Context-adaptive prompts drop "software project" language when no CLAUDE.md is detected or `--no-context` is used.

## Models & API Callers

| Key | Model | Route | Env Var |
|-----|-------|-------|---------|
| `claude` | Claude Opus 4.6 | OpenRouter | `OPENROUTER_API_KEY` |
| `gpt` | GPT-5.4 | OpenRouter | `OPENROUTER_API_KEY` |
| `gemini` | Gemini 3.1 Pro | OpenRouter | `OPENROUTER_API_KEY` |
| `grok` | Grok 4.20 | OpenRouter | `OPENROUTER_API_KEY` |

All model calls go through `call_openrouter()`. The per-provider callers and per-provider keys were removed to keep configuration dead simple.

## Key Design Decisions

### Structured Analysis (Stage 3)
- Chairman model extracts CONSENSUS, DISAGREEMENTS, and UNRESOLVED sections
- Runs even with `--no-chairman` (makes lightweight mode much more useful)
- Analysis output fed into chairman synthesis prompt for better final answers
- Skipped if fewer than 2 models responded
- `run_analysis()` function, uses `ANALYSIS_PROMPT_PROJECT` / `ANALYSIS_PROMPT_GENERAL`

### Anonymized Review (Stage 4)
- Models evaluate "Response A/B/C/D" — labels are randomly shuffled each run
- Each model produces a `FINAL RANKING:` section that gets parsed with regex
- Fallback parsing if models don't follow the exact format
- Aggregate scores computed as average rank position across all reviewers

### Chairman Synthesis (Stage 5)
- Default chairman is Grok (`--chairman` flag to change)
- Chairman sees de-anonymized responses + aggregate rankings
- Chairman can be a council member (default) or external

### Blind Mode (--blind)
- Models see anonymized names (Panelist A/B/C/D) in both display and deliberation messages
- Separate random shuffle from the review-stage shuffle (prevents cross-referencing)
- Reveal section at the end maps both Panelist and Response labels to real names

### Context Detection
- `find_up("CLAUDE.md")` walks up from cwd like git
- `--deep` adds MEMORY.md from `.claude/projects/` memory dir
- `--files` for specific source files
- `--no-context` drops all project awareness (general questions mode)

### Env Loading
- Loads from `~/.env`, `~/.think_tank.env`, `./.env`
- Uses `OPENROUTER_API_KEY` for every model call
- Maps friendly `OpenRouter` to `OPENROUTER_API_KEY`
- Never overwrites already-set env vars

## Optional MCP Server

`mcp_server.py` is an optional wrapper that exposes Think Tank as MCP tools.

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
  "analysis": "CONSENSUS:\n- ...\n\nDISAGREEMENTS:\n- ...\n\nUNRESOLVED:\n- ...",
  "review": {"rankings": [...], "label_map": {...}},
  "synthesis": "Chairman's final answer...",
  "total_elapsed": 45.2
}
```
Fields omitted when stages are skipped (light = no review/synthesis, but analysis still runs).

### Registration
`~/.claude/.mcp.json`:
```json
{"mcpServers": {"think-tank": {"command": "python", "args": ["/path/to/think-tank/mcp_server.py"]}}}
```

### Key Details
- MCP server shells out to `think_tank.py --json` as a subprocess (no import refactoring)
- 10-minute timeout on subprocess calls (bumped from 5min — heavy pipeline was timing out)
- `stdin=subprocess.DEVNULL` prevents child from inheriting MCP stdio pipe
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
    specs/               — design specs (Think Tank v2, analysis layer, Wisemen web dashboard)
    plans/               — implementation plans (Think Tank v2, analysis layer, Wisemen)
```

## Running It

Aliases defined in PowerShell profile and `~/.bashrc` so `think_tank` works from any directory. When run from inside a repo, auto-detects CLAUDE.md for project context.

```bash
think_tank "Your question"                    # full pipeline, 4 models
think_tank --no-context "General question"    # no software context
think_tank --no-chairman "Quick opinions"     # skip review + synthesis, still runs analysis
think_tank -r 2 -b -s out.md "Design Q"      # 2 rounds, blind, save transcript
```

## Development Notes

- Inspired by karpathy/llm-council but stays CLI-first and project-aware
- The user's original workflow was: run Think Tank, save transcript, manually feed to Claude for synthesis. v2 automates that last step.
- No tests — this is a personal tool, vibe-coded. Verify manually.
- `requests` is the only runtime dependency for the CLI (plus stdlib + `random` for shuffling)

## Related Projects

- **Wisemen** (`../Wisemen/`) — Web-based companion to this CLI. SvelteKit on Cloudflare Pages/Workers. Separate repo (TrickRiggin/Wisemen). Shares the same pipeline logic (ported to TypeScript) but adds persistent conversations, profiles, and streaming UI. Deployed at `wisemen.austinarlt.ai`.

## Port Configuration

Backend only: 8001 was used by the Karpathy llm-council clone (separate project in `../llm-council/`). This tool has no server component.

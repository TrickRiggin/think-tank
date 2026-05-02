# Think Tank — CLAUDE.md

## What This Is

CLI multi-model deliberation tool. Sends a prompt to the default 4-model council in parallel through OpenRouter, optional crux framing, deliberation rounds, anonymized peer review, and chairman synthesis. Single-file Python script, no web UI, no MCP wrapper, no framework dependencies beyond `requests`. Runs save markdown and HTML artifacts by default so expensive council calls leave a durable report.

## Architecture

Everything lives in `think_tank.py`. The pipeline:

```
Stage 0: CRUX        — Optional framing pass extracts cruxes/assumptions/tests (--crux)
Stage 1: COLLECT      — Default council answers in parallel (ThreadPoolExecutor)
Stage 2: DELIBERATE   — Optional rounds where models challenge each other (--rounds)
Stage 3: ANALYZE      — Chairman extracts consensus, disagreements, unresolved gaps, crux coverage
Stage 4: REVIEW       — Leave-one-out anonymized peer ranking (Response A/B/C/D)
Stage 5: SYNTHESIZE   — Chairman compiles a final answer from analysis + rankings
Stage 6: SAVE          — Markdown transcript + standalone HTML report, unless --no-save
```

Stages 4-5 skip with `--no-chairman`. Stage 3 (analysis) still runs with `--no-chairman` if 2+ models responded. `--no-context` skips auto project context (`CLAUDE.md` / deep memory) but still loads explicit `--files`.

## Models & API Callers

| Key | Model | Route | Env Var |
|-----|-------|-------|---------|
| `claude` | Claude Opus 4.7 | OpenRouter | `OPENROUTER_API_KEY` |
| `gpt` | GPT-5.5 | OpenRouter | `OPENROUTER_API_KEY` |
| `gemini` | Gemini 3.1 Pro | OpenRouter | `OPENROUTER_API_KEY` |
| `deepseek` | DeepSeek V4 Pro | OpenRouter | `OPENROUTER_API_KEY` |
| `grok` | Grok 4.20 | OpenRouter | `OPENROUTER_API_KEY` |

All model calls go through `call_openrouter()`. The per-provider callers and per-provider keys were removed to keep configuration dead simple.

Default council: `claude`, `gpt`, `gemini`, `deepseek`.

## Key Design Decisions

### Crux Framing (Stage 0)
- `--crux` runs one pre-collection call with the chairman model
- Output shape is `CRUXES`, `ASSUMPTIONS`, and `VALIDATION TESTS`
- The crux frame is fed into the model collection prompt, analysis prompt, chairman prompt, transcript, and JSON output
- Purpose: improve decision quality without adding a pile of role flags

### Structured Analysis (Stage 3)
- Chairman model extracts CONSENSUS, DISAGREEMENTS, and UNRESOLVED sections
- Runs even with `--no-chairman` (makes lightweight mode much more useful)
- Analysis output fed into chairman synthesis prompt for better final answers; when `--crux` is used, analysis checks whether the council answered the cruxes
- Skipped if fewer than 2 models responded
- `run_analysis()` function, uses `ANALYSIS_PROMPT_PROJECT` / `ANALYSIS_PROMPT_GENERAL`

### Anonymized Review (Stage 4)
- Models evaluate "Response A/B/C/D" — labels are randomly shuffled each run
- Review is leave-one-out: each reviewer sees only the other models' responses, so self-votes do not contaminate rankings
- Each model produces a `FINAL RANKING:` section that gets parsed with regex
- Fallback parsing if models don't follow the exact format
- Aggregate scores computed as average rank position after discarding any self-rank hallucinations

### Chairman Synthesis (Stage 5)
- Default chairman is Grok (`--chairman` flag to change)
- Chairman sees responses, analysis, and aggregate rankings using blind labels when `--blind` is active
- Chairman prompt is compiler-style: start from the top-ranked response, preserve useful dissent, and explain material changes
- Chairman can be a council member or external. By default Grok is external to the council: it does not answer in Stage 1 unless explicitly included with `--models`.

### Blind Mode (--blind)
- Models see anonymized names (Panelist A/B/C/D/etc.) in display, deliberation, analysis, and synthesis
- Separate random shuffle from the review-stage shuffle (prevents cross-referencing)
- Reveal section at the end maps both Panelist and Response labels to real names

### Red Team (--red-team MODEL)
- Assigns one model an adversarial / devil's advocate role. That model gets a different system prompt (`RED_TEAM_SYSTEM_PROMPT`) that pushes it to hunt for flaws, challenge the question's framing, and surface failure modes instead of answering directly.
- Motivation: the CLI is often called from inside Claude Code / Codex, where the wrapping agent has already biased the question toward a particular answer. Giving one voice an explicit "find the flaws" mandate counteracts that.
- Disclosure propagates everywhere so models don't mistake critique for competing advice:
  - Other models' system prompts include a one-line note naming the red team panelist
  - Deliberation messages annotate the red team entry as `(assigned: red team)`
  - Red team model gets `RED_TEAM_DELIBERATION_PROMPT` (stays adversarial across rounds)
  - Analysis prompt is told to flag red-team-driven disagreements separately
  - Review prompt discloses which anonymized Response was red team (label-level, identity still hidden)
  - Chairman prompt is told to weight red team points as stress-tests, not competing recommendations
- Any model can be red team. GPT tends toward dry edge-case hunting; Grok tends toward broader philosophical challenges.

### Context Detection
- `find_up("CLAUDE.md")` walks up from cwd like git
- `--deep` adds MEMORY.md from `.claude/projects/` memory dir
- `--files` for specific source files
- `--no-context` drops auto project context only; explicit `--files` still load

### Env Loading
- Loads from `~/.env`, `~/.think_tank.env`, `./.env`
- Uses `OPENROUTER_API_KEY` for every model call
- Maps friendly `OpenRouter` to `OPENROUTER_API_KEY`
- Never overwrites already-set env vars

## JSON Output

`--json` suppresses terminal display and emits structured JSON to stdout. Default artifact saves still happen unless `--no-save` is set; saved paths appear under `artifacts` in the JSON:
```json
{
  "question": "...",
  "models": ["claude", "gpt", "gemini", "deepseek"],
  "deliberation_rounds": 1,
  "crux": "CRUXES:\n- ...",
  "rounds": [{"round": 1, "responses": {"claude": {"text": "...", "elapsed": 12.3}, ...}}],
  "analysis": "CONSENSUS:\n- ...\n\nDISAGREEMENTS:\n- ...\n\nUNRESOLVED:\n- ...",
  "review": {"rankings": [...], "label_map": {...}},
  "synthesis": "Chairman's final answer...",
  "artifacts": {"markdown": "output/think_tank-...", "html": "output/think_tank-..."},
  "total_elapsed": 45.2
}
```
Fields omitted when stages are skipped (light = no review/synthesis, but analysis still runs).

## File Structure

```
think-tank/
  think_tank.py          — the entire tool (single file)
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
think_tank --crux "Decision question"         # add crux framing
think_tank --no-context "General question"    # no auto project context
think_tank --no-chairman "Quick opinions"     # skip review + synthesis, still runs analysis
think_tank -r 1 -b -s out.md "Design Q"       # saves output/out.md + output/out.html
think_tank "Design Q"                         # saves timestamped markdown + HTML under output/
think_tank --no-save "Disposable check"       # skip artifact writes
```

## Development Notes

- Inspired by karpathy/llm-council but stays CLI-first and project-aware
- The user's original workflow was: run Think Tank, save transcript, manually feed to Claude for synthesis. v2 automates that last step.
- Routine runs save markdown and HTML into ignored `output/` by default. `--save` chooses the basename; explicit directories still work for intentional exports. `--no-save` is the throwaway-run escape hatch.
- `build_html_transcript()` is intentionally stdlib-only. It renders the repo's transcript Markdown subset, promotes chairman synthesis/executive summary to the top, and collapses source material below.
- No tests — this is a personal tool, vibe-coded. Verify manually.
- `requests` is the only runtime dependency for the CLI (plus stdlib + `random` for shuffling)

## Related Projects

- **Wisemen** (`../Wisemen/`) — Web-based companion to this CLI. SvelteKit on Cloudflare Pages/Workers. Separate repo (TrickRiggin/Wisemen). Shares the same pipeline logic (ported to TypeScript) but adds persistent conversations, profiles, and streaming UI. Deployed at `wisemen.austinarlt.ai`.

## Port Configuration

Backend only: 8001 was used by the Karpathy llm-council clone (separate project in `../llm-council/`). This tool has no server component.

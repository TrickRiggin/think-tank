# Structured Disagreement Analysis Layer — Design Spec

## Summary

Add a new ANALYZE stage to Think Tank that extracts structured consensus, disagreements, and unresolved gaps from model responses. Runs after deliberation, before review. Powered by the chairman model. Displayed to the user and fed into the chairman synthesis prompt.

## Pipeline

```
Stage 1: COLLECT      — All models answer in parallel (unchanged)
Stage 2: DELIBERATE   — Optional multi-round challenges (unchanged)
Stage 3: ANALYZE      — NEW: Chairman model extracts structured disagreement
Stage 4: REVIEW       — Anonymized peer ranking (unchanged)
Stage 5: SYNTHESIZE   — Chairman synthesizes, now with analysis as input (enhanced)
```

- `--no-chairman` runs stages 1-3 (analysis included, review + synthesis skipped)
- Analysis always uses the chairman model (default Claude, or `--chairman` override)
- Analysis is skipped if fewer than 2 models responded (nothing to compare)

## Analysis Stage Details

### Model Selection

Uses the chairman model via `resolve_api(chairman_key)`. No new flags — piggybacks on `--chairman`.

### Prompt Design

Two prompt templates following the existing pattern:
- `ANALYSIS_PROMPT_PROJECT` — includes project context
- `ANALYSIS_PROMPT_GENERAL` — no project context

The prompt receives all model responses with real model names (not anonymized — this runs before the review stage's anonymization).

The prompt instructs the model to:
- Not summarize responses — only extract the structure
- Be specific about which models hold which positions
- Identify the crux of each disagreement (what fact/assumption would resolve it)
- Flag genuine gaps, not nitpicks
- Always output all three sections even if empty ("No disagreements found")

### Output Format

The analysis model must output exactly this structure:

```
CONSENSUS:
- [Points where 2+ models substantively agree]

DISAGREEMENTS:
- [Point of contention] — [Models] say X vs [Models] say Y. Crux: [what it hinges on]

UNRESOLVED:
- [Questions no model addressed, or assumptions none validated]
```

### Display

Displayed under a `header("Analysis (Structured Disagreement)")` section with the chairman model's color and timing, same as other stages.

## Integration with Existing Stages

### Review Stage

Unchanged. The anonymized peer review evaluates response quality independently from the structured analysis. They serve different purposes and stay independent.

### Chairman Synthesis (Enhanced)

The chairman prompt templates (`CHAIRMAN_PROMPT_PROJECT`, `CHAIRMAN_PROMPT_GENERAL`) gain an `{analysis_text}` variable. The chairman receives:
- Individual responses (existing)
- Peer rankings (existing)
- Structured analysis (new)

This lets the chairman focus on making the final call rather than doing extraction + synthesis in one shot.

### `--no-chairman` Flow

Runs COLLECT -> (DELIBERATE) -> ANALYZE, then stops. The analysis becomes the capstone output. This makes `--no-chairman` significantly more useful — you get raw opinions plus a structured breakdown.

### `--json` Mode

New `"analysis"` key in JSON output. Contains the raw analysis text. Sits between `"rounds"` and `"review"`:

```json
{
  "question": "...",
  "models": [...],
  "rounds": [...],
  "analysis": "CONSENSUS:\n- ...\n\nDISAGREEMENTS:\n- ...\n\nUNRESOLVED:\n- ...",
  "review": {...},
  "synthesis": "...",
  "total_elapsed": 45.2
}
```

Field omitted when analysis is skipped (fewer than 2 models responded).

### Transcript (`--save`)

New `## Analysis (Structured Disagreement)` section between rounds and review.

## New Code

### New function: `run_analysis()`

```
run_analysis(results, active_models, question, context, chairman_key) -> str | None
```

- Builds the analysis prompt from all model responses
- Calls the chairman model via `resolve_api()`
- Displays the output
- Returns the analysis text (or None on failure)

### Modified function: `run_chairman()`

Gains an `analysis_text` parameter. Passed into the chairman prompt templates via `{analysis_text}`.

### Modified: `main()`

- Calls `run_analysis()` after rounds complete, before review
- Passes analysis text to `run_chairman()`
- Adds analysis to JSON output and transcript

## What Doesn't Change

- COLLECT, DELIBERATE, REVIEW stages — untouched
- All existing CLI flags — unchanged behavior
- `--blind` mode — analysis uses real model names (it runs before anonymization), blind reveal at end still works
- MCP server — inherits the change automatically (analysis runs in full pipeline mode)

## Error Handling

If the analysis call fails, log the error, set analysis_text to None, and continue to review/synthesis without it. The pipeline degrades gracefully to current behavior.

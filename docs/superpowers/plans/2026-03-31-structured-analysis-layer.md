# Structured Disagreement Analysis Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ANALYZE stage that extracts structured consensus, disagreements, and unresolved gaps from model responses — displayed to the user and fed into chairman synthesis.

**Architecture:** Single new `run_analysis()` function called from `main()`, two new prompt templates, enhanced chairman prompts. All changes in `think_tank.py` + `CLAUDE.md`.

**Tech Stack:** Python, requests (existing)

---

### Task 1: Add Analysis Prompt Templates

**Files:**
- Modify: `think_tank.py:398-405` (insert after `DELIBERATION_PROMPT`, before `REVIEW_PROMPT_PROJECT`)

- [ ] **Step 1: Add `ANALYSIS_PROMPT_PROJECT` and `ANALYSIS_PROMPT_GENERAL` after `DELIBERATION_PROMPT`**

Insert these two templates after `DELIBERATION_PROMPT` (line 405) and before `REVIEW_PROMPT_PROJECT`:

```python
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
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('think_tank.py', doraise=True)"`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add think_tank.py
git commit -m "feat: add analysis prompt templates for structured disagreement"
```

---

### Task 2: Add `run_analysis()` Function

**Files:**
- Modify: `think_tank.py` (insert after `run_review()` function, before the chairman prompt templates)

- [ ] **Step 1: Add `run_analysis()` after the `run_review()` function**

Insert after the `run_review()` function (which ends with `return all_rankings, label_to_model, aggregate, review_texts`) and before the `CHAIRMAN_PROMPT_PROJECT` template:

```python
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
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('think_tank.py', doraise=True)"`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add think_tank.py
git commit -m "feat: add run_analysis() for structured disagreement extraction"
```

---

### Task 3: Enhance Chairman Prompts with Analysis Input

**Files:**
- Modify: `think_tank.py` — `CHAIRMAN_PROMPT_PROJECT`, `CHAIRMAN_PROMPT_GENERAL`, and `run_chairman()` function

- [ ] **Step 1: Update `CHAIRMAN_PROMPT_PROJECT`**

Replace the existing `CHAIRMAN_PROMPT_PROJECT` with:

```python
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
```

- [ ] **Step 2: Update `CHAIRMAN_PROMPT_GENERAL`**

Replace the existing `CHAIRMAN_PROMPT_GENERAL` with:

```python
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
```

- [ ] **Step 3: Update `run_chairman()` signature and prompt formatting**

Change the function signature from:
```python
def run_chairman(results, active_models, aggregate, question, context, chairman_key):
```
to:
```python
def run_chairman(results, active_models, aggregate, question, context, chairman_key, analysis_text=None):
```

In the prompt formatting inside `run_chairman`, update both `.format()` calls to include `analysis_text`:

For the project prompt:
```python
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
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('think_tank.py', doraise=True)"`
Expected: No output (success)

- [ ] **Step 5: Commit**

```bash
git add think_tank.py
git commit -m "feat: enhance chairman prompts with structured analysis input"
```

---

### Task 4: Wire Analysis into `main()` Pipeline

**Files:**
- Modify: `think_tank.py` — `main()` function

- [ ] **Step 1: Add `json_analysis` variable alongside other JSON collectors**

Find the line:
```python
    json_synthesis = None
    pipeline_start = time.time()
```

Change to:
```python
    json_analysis = None
    json_synthesis = None
    pipeline_start = time.time()
```

- [ ] **Step 2: Add analysis stage after the round loop, before review**

Find the section starting with:
```python
    # ── Review + Synthesis (unless --no-chairman) ────────────────────────
    chairman_text = None
    label_to_model = {}
    if not args.no_chairman:
        # Gather final responses (last response from each model)
        final_responses = {}
```

Replace with:
```python
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
```

- [ ] **Step 3: Remove the duplicated final_responses/responding code from inside the `if not args.no_chairman` block**

Since we moved `final_responses` and `responding` outside and above, remove the duplicate lines that were inside the `if not args.no_chairman` block:

```python
        # Gather final responses (last response from each model)
        final_responses = {}
        for key in active_models:
            if conversations[key]:
                for msg in reversed(conversations[key]):
                    if msg["role"] == "assistant":
                        final_responses[key] = msg["content"]
                        break

        responding = [k for k in active_models if final_responses.get(k)]

        if len(responding) >= 2:
```

These lines are now handled above. The review block should start directly with:

```python
    if not args.no_chairman and len(responding) >= 2:
            all_rankings, label_to_model, aggregate, review_texts = run_review(
```

- [ ] **Step 4: Pass `analysis_text` to `run_chairman()`**

Find:
```python
            chairman_text = run_chairman(
                final_responses, active_models, aggregate,
                question, context, args.chairman,
            )
```

Change to:
```python
            chairman_text = run_chairman(
                final_responses, active_models, aggregate,
                question, context, args.chairman, analysis_text,
            )
```

- [ ] **Step 5: Add analysis to JSON output**

Find:
```python
        if not args.no_chairman and json_review:
            json_output["review"] = json_review
```

Add before that line:
```python
        if json_analysis:
            json_output["analysis"] = json_analysis
```

- [ ] **Step 6: Fix the `else` clause for fewer than 2 respondents**

The old code had:
```python
        else:
            _print(f"\n{C['system']}  Skipping review — fewer than 2 models responded.{C['reset']}")
```

This is no longer needed inside the `if not args.no_chairman` block since the respondent check is now handled above. Remove it.

- [ ] **Step 7: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('think_tank.py', doraise=True)"`
Expected: No output (success)

- [ ] **Step 8: Commit**

```bash
git add think_tank.py
git commit -m "feat: wire analysis stage into main() pipeline"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the pipeline description**

Find:
```
Stage 1: COLLECT      — All 4 models answer in parallel (ThreadPoolExecutor)
Stage 2: DELIBERATE   — Optional rounds where models challenge each other (--rounds)
Stage 3: REVIEW       — Anonymized peer ranking (Response A/B/C/D, randomly shuffled)
Stage 4: SYNTHESIZE   — Chairman produces final answer (default: Claude Opus 4.6)
```

Replace with:
```
Stage 1: COLLECT      — All 4 models answer in parallel (ThreadPoolExecutor)
Stage 2: DELIBERATE   — Optional rounds where models challenge each other (--rounds)
Stage 3: ANALYZE      — Chairman extracts consensus, disagreements, unresolved gaps
Stage 4: REVIEW       — Anonymized peer ranking (Response A/B/C/D, randomly shuffled)
Stage 5: SYNTHESIZE   — Chairman produces final answer with analysis + rankings as input
```

- [ ] **Step 2: Update the stages skip note**

Find:
```
Stages 3-4 skip with `--no-chairman`.
```

Replace with:
```
Stages 4-5 skip with `--no-chairman`. Stage 3 (analysis) still runs with `--no-chairman` if 2+ models responded.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for analysis stage"
```

---

### Task 6: Smoke Test

**Files:** None (manual verification)

- [ ] **Step 1: Test full pipeline**

Run: `python think_tank.py --no-context "What's the best programming language for beginners and why?"`

Expected: All 5 stages fire — COLLECT, (no deliberation at 1 round), ANALYZE, REVIEW, SYNTHESIZE. Analysis output shows CONSENSUS/DISAGREEMENTS/UNRESOLVED sections. Chairman synthesis references the analysis.

- [ ] **Step 2: Test `--no-chairman` mode**

Run: `python think_tank.py --no-chairman --no-context "What's the best programming language for beginners and why?"`

Expected: COLLECT + ANALYZE stages fire. No REVIEW or SYNTHESIZE. Analysis output displayed.

- [ ] **Step 3: Test `--json` mode**

Run: `python think_tank.py --no-context --json "What's the best programming language for beginners?" | python -m json.tool`

Expected: Valid JSON with `"analysis"` key present between `"rounds"` and `"review"`.

- [ ] **Step 4: Final commit and push**

```bash
git push
```

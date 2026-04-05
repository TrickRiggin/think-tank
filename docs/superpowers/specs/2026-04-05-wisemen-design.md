# Wisemen — Design Spec

**Date:** 2026-04-05
**Repo:** `Wisemen` (new repo, separate from think-tank CLI)
**Stack:** SvelteKit + Cloudflare Pages/Workers + D1 + Cloudflare Access + Sentry

## Overview

Wisemen is a web-based multi-model chat interface. Users converse with 4 LLMs simultaneously in a turn-by-turn chat format where every model sees the user's messages and each other's responses. A formal deliberation pipeline (anonymized peer review, structured analysis, chairman synthesis) is available on demand via button or slash command.

Think of it as the Think Tank CLI's conversational cousin — the CLI is for one-shot questions, Wisemen is for evolving discussions.

## Core Concepts

### Chat-First with Pipeline on Demand (Hybrid Model)

The default interaction is a chat. User sends a message, all 4 models respond. Each model's response is visible in its own tab. On each subsequent turn, models automatically receive the other models' previous responses as context — deliberation is built into the chat flow, not a separate stage.

The formal pipeline (peer review + rankings + analysis + chairman synthesis) is triggered explicitly when the user wants a verdict. This is the "heavy artillery" — a button in the compose bar (gavel icon) or `/synthesize` slash command.

### Profiles (Multi-User)

Cloudflare Access gates the app to an email allowlist (Austin + wife). Inside the app, profiles provide separate conversation histories and persistent context. Each profile has:

- **Name** — display identity
- **Context** — freeform text injected as a system-level message into every conversation. Lets each person tune model behavior ("I'm tech savvy" vs "explain things simply").

Profiles are a UI-level concept, not an auth system. Cloudflare Access handles authentication; profiles handle personalization and data separation.

## Architecture

### Components

```
Cloudflare Access (auth gate)
    |
    v
Cloudflare Pages (SvelteKit app)
    |-- Static frontend (chat UI, tabs, sidebar)
    |-- Server routes (run as Workers via Pages adapter)
            |-- /api/chat         POST  Fan-out to 4 models, SSE stream back
            |-- /api/synthesize   POST  Review + analysis + chairman, SSE stream
            |-- /api/conversations GET   List conversations for profile
            |-- /api/conversations/[id]  GET/DELETE
            |-- /api/profiles     GET/POST
            |-- /api/profiles/[id] GET/PUT
            |
            |-- Cloudflare D1 (conversation storage)
            |-- External model APIs (Anthropic, OpenAI, Google AI, xAI, OpenRouter)
            |-- Sentry (error tracking + tracing)
```

SvelteKit's Cloudflare Pages adapter means server routes automatically run as Workers. One project, one deploy command (`wrangler pages deploy`). No separate Worker deployment, no CORS.

### Key Decisions

- **API keys server-side only** — stored as Worker secrets (`wrangler secret put`), never sent to the browser.
- **SSE over WebSockets** — simpler, works through Cloudflare CDN without special config, auto-reconnects natively.
- **D1 over KV** — conversations are relational (profiles have conversations have messages). SQLite is the right tool.
- **Single project** — SvelteKit server routes = Workers. No separate frontend/backend repos.

## Data Model

### D1 Schema

```sql
CREATE TABLE profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    context     TEXT DEFAULT '',
    created_at  INTEGER NOT NULL
);

CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id),
    title       TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE messages (
    id          TEXT PRIMARY KEY,
    conv_id     TEXT NOT NULL REFERENCES conversations(id),
    role        TEXT NOT NULL,       -- 'user' | 'assistant'
    model       TEXT,                -- 'claude' | 'gpt' | 'gemini' | 'grok' | null for user
    content     TEXT NOT NULL,
    elapsed     REAL,               -- seconds, model messages only
    turn        INTEGER NOT NULL,   -- groups user msg + 4 model responses
    created_at  INTEGER NOT NULL
);

CREATE TABLE syntheses (
    id          TEXT PRIMARY KEY,
    conv_id     TEXT NOT NULL REFERENCES conversations(id),
    analysis    TEXT,               -- CONSENSUS/DISAGREEMENTS/UNRESOLVED
    rankings    TEXT,               -- JSON array: [{model, avg_rank, votes}]
    label_map   TEXT,               -- JSON: {"Response A": "gpt", ...}
    synthesis   TEXT,               -- chairman final answer
    chairman    TEXT DEFAULT 'claude',
    turn        INTEGER,            -- synthesis covers through this turn
    created_at  INTEGER NOT NULL
);

CREATE INDEX idx_messages_conv ON messages(conv_id, turn);
CREATE INDEX idx_conversations_profile ON conversations(profile_id, updated_at DESC);
CREATE INDEX idx_syntheses_conv ON syntheses(conv_id);
```

The `turn` column on `messages` is the critical design choice. It groups a user message with its 4 model responses, making it trivial to reconstruct per-model conversation histories and build deliberation context.

## UI Layout

### Sidebar (Left, 220px)

- **Profile switcher** (top) — avatar + name, dropdown to switch profiles.
- **New conversation button**
- **Conversation list** — grouped by date (Today / Yesterday / Older). Each entry shows title (auto-generated: first ~50 chars of the first user message, editable by clicking), turn count, and a "synthesized" badge if a synthesis was run. Active conversation highlighted.

### Model Tabs (Top of main area)

Persistent row of tabs: Claude | GPT | Gemini | Grok. Each tab shows:
- Model name in its brand color
- Response time for the current turn
- Status indicator on right: streaming / all responded / error

Active tab is underlined in model color. Switching tabs shows the same conversation thread from that model's perspective.

### Chat Thread (Main area)

- User messages right-aligned (indigo bubbles)
- Model responses left-aligned with model avatar, in active tab's model color
- Switching tabs swaps which model's responses are shown — user messages stay the same
- Streaming responses show a blinking cursor
- Synthesis results appear as a visually distinct card — collapsible sections for rankings, analysis, and final answer

### Compose Bar (Bottom)

- Text input: "Message all models... (/ for commands)"
- Synthesize button (gavel icon) — triggers full pipeline
- Send button
- Slash command hints below the input

## Streaming Architecture

### Chat Streaming (`/api/chat`)

1. Worker receives user message, saves to D1 (assigns new turn number)
2. Builds per-model message arrays from conversation history. Each model gets:
   - System message (profile context + any conversation-level settings)
   - For each previous turn: user message + that model's response + deliberation context (other models' responses)
   - Current user message
3. Opens 4 parallel `fetch()` calls to model APIs with streaming enabled
4. Multiplexes 4 inbound streams into 1 outbound SSE connection, tagged by model:
   ```
   event: token
   data: {"model": "grok", "content": "The key"}

   event: token
   data: {"model": "claude", "content": "For Service"}

   event: done
   data: {"model": "grok", "elapsed": 0.9, "full_text": "..."}

   event: error
   data: {"model": "gemini", "error": "Rate limited (429)"}

   event: all-done
   data: {"turn": 3}
   ```
5. As each model completes (`done` event), saves full response to D1
6. Client demuxes by model tag, routes tokens to appropriate tab's reactive store

### Synthesis Streaming (`/api/synthesize`)

Same SSE pattern but with phase tags:
```
event: phase
data: {"phase": "review", "status": "started"}

event: review-complete
data: {"model": "claude", "ranking": ["Response B", "Response A", "Response C", "Response D"]}

event: phase
data: {"phase": "analysis", "status": "started"}

event: analysis-token
data: {"content": "CONSENSUS:\n- All four models agree..."}

event: phase
data: {"phase": "synthesis", "status": "started"}

event: synthesis-token
data: {"content": "Based on the council's deliberation..."}

event: synthesis-done
data: {"rankings": [...], "analysis": "...", "synthesis": "..."}
```

The synthesis panel slides in below the tabs and renders each phase as it streams.

### Error Handling

- If a model fails or times out, Worker sends `event: error` for that model. The tab shows the error inline; other models keep streaming.
- If the SSE connection drops, the client auto-reconnects (native EventSource behavior). On reconnect, it fetches the conversation state from D1 to reconcile.
- Sentry captures failed API calls with model name, status code, and response body for debugging.

## Deliberation Model

Deliberation is implicit in the chat flow. On each turn after the first, each model's message array includes the other models' responses from the previous turn as a deliberation prompt:

```
[Previous turn context]
Here's what the other models said:

**Claude:** [their response]
**GPT:** [their response]
**Gemini:** [their response]

The user has followed up:

[User's new message]
```

This means every conversation naturally becomes a deliberation — models see each other's work and can build on, challenge, or refine it. No explicit "deliberate" button needed.

## Synthesis Pipeline (On-Demand)

Triggered by gavel button or `/synthesize`:

1. **Anonymize** — Shuffle latest model responses into Response A/B/C/D labels
2. **Peer Review** (4 parallel calls) — Each model evaluates and ranks the anonymized responses
3. **Analysis** (1 call, chairman) — Extract CONSENSUS / DISAGREEMENTS / UNRESOLVED
4. **Chairman Synthesis** (1 call, chairman) — Final answer incorporating rankings + analysis
5. **Save** — Store to `syntheses` table, display as special card in thread

## Slash Commands

| Command | Action |
|---------|--------|
| `/synthesize` | Full pipeline: review + analysis + chairman synthesis |
| `/review` | Anonymized peer review + rankings only, no chairman |
| `/blind` | Toggle blind mode (anonymize model names in the thread) |
| `/models` | Show/hide models for this conversation (e.g., `/models claude,gpt` for 2-model chat). Persists per conversation — subsequent turns only query active models. |
| `/context` | Edit profile's persistent context inline |

## Models

Same 4 models as the CLI, with OpenRouter fallback:

| Key | Model | Direct API | OpenRouter Fallback |
|-----|-------|-----------|-------------------|
| `claude` | Claude Opus 4.6 | Anthropic | `anthropic/claude-opus-4-6` |
| `gpt` | GPT-5.4 | OpenAI | `openai/gpt-5.4` |
| `gemini` | Gemini 3.1 Pro | Google AI | `google/gemini-3.1-pro-preview` |
| `grok` | Grok 4.20 | xAI | `x-ai/grok-4.20-0309-non-reasoning` |

API keys stored as Cloudflare Worker secrets. OpenRouter used as fallback for any missing direct key, same logic as the CLI.

## Monitoring (Sentry)

- **SvelteKit client SDK** — frontend errors, unhandled rejections, component crashes
- **Cloudflare Workers SDK** (`@sentry/cloudflare`) — Worker errors, failed API calls, timeouts
- **Performance tracing** — traces across the streaming pipeline (which model is slow, where in the chain things break)
- `SENTRY_DSN` stored as a Worker secret

## Auth

Cloudflare Access with email allowlist. No auth code in the application. Access sits in front of the entire domain — unauthenticated requests never reach the app.

Any authenticated user can switch between all profiles — there's no mapping between Cloudflare Access identity and profile. This is intentional: it's a household app with 2 users, not a multi-tenant platform.

## Project Structure

```
Wisemen/
  src/
    lib/
      models/           -- model configs, API callers (ported from think_tank.py)
      pipeline/          -- deliberation builder, anonymizer, ranking aggregator
      db/               -- D1 queries, schema
      stores/           -- Svelte stores for streaming state
    routes/
      +page.svelte      -- main chat UI
      +layout.svelte    -- shell (sidebar + slot)
      api/
        chat/+server.ts
        synthesize/+server.ts
        conversations/+server.ts
        conversations/[id]/+server.ts
        profiles/+server.ts
        profiles/[id]/+server.ts
  static/               -- favicon, assets
  wrangler.toml          -- D1 binding, secrets config
  svelte.config.js       -- Cloudflare adapter
  CLAUDE.md
```

## What This Is NOT

- Not a SaaS product — no billing, no usage limits, no public registration
- Not a mobile app — responsive enough to use on a phone but desktop-first
- Not a replacement for the CLI — the CLI continues to work independently for one-shot questions
- Not a model management platform — the 4 models are hardcoded, same as the CLI. Adding/removing models is a code change.

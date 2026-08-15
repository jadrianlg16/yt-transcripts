# YouTube Transcript Pro Plan

Last updated: 2026-05-14

## Project Objective

YouTube Transcript Pro is a local research archive for YouTube transcripts. Its immediate job is to fetch, store, browse, search, and export transcript data. The larger direction is to become a personal knowledge engine where saved videos can be searched at the moment level, compared, summarized, organized into research collections, and eventually kept up to date automatically.

## Current State

### Architecture

- Backend: FastAPI app in `main.py`.
- Core logic:
  - `core/fetcher.py` extracts video IDs, fetches transcripts, and fetches YouTube metadata.
  - `core/store.py` provides the transcript storage abstraction and JSON-backed default store.
  - `core/sqlite_store.py` provides a SQLite-backed store, schema, FTS search, JSON export, and JSON migration helper.
  - `core/research.py` computes archive stats and ranked transcript search results.
  - `core/fetch_reliability.py` persists fetch runs, retry metadata, and watcher settings independently of the active transcript backend.
  - `core/ai_settings.py` persists local AI model configuration.
  - `core/ai_clients.py` wraps Ollama model and embedding calls.
  - `core/ai_artifacts.py` stores generated summaries, comparisons, timelines, and AI run artifacts.
  - `core/semantic_search.py` builds and queries a local JSON-backed vector index.
- Claude Code access: read-only MCP server in `mcp_server.py` with project-scoped `.mcp.json`.
- Frontend: React + TypeScript + Vite app in `frontend/src/App.tsx`.
- Legacy desktop app: `app.py` still contains the older Tkinter UI and duplicated fetch logic.
- Root npm scripts in `package.json` proxy frontend commands and provide a single check command.

### Implemented Capabilities

- Fetch a single YouTube video transcript.
- Bulk fetch transcripts from a channel.
- Store transcripts locally in JSON.
- Deduplicate saved entries by `video_id`.
- Browse saved transcripts in the React UI.
- Search locally by title, channel, and transcript text.
- Backend-powered ranked search through `/api/search`.
- Library statistics through `/api/stats`.
- Storage abstraction with JSON and SQLite backends.
- SQLite schema for channels, videos, segments, and fetch runs.
- SQLite FTS search for the SQLite backend.
- JSON-to-SQLite migration helper.
- Browser UI controls for storage status, one-click SQLite migration, and JSON backup export.
- Auto backend selection: JSON before migration, SQLite after the SQLite database exists.
- Channel filtering in the UI.
- Search result highlighting inside matched moments and full transcript text.
- Sort controls for relevance, newest, longest, most matches, and title.
- Saved search queries in the browser.
- Compact selected-video detail panel with word count, runtime, segments, and match count.
- Improved keyword extraction with deterministic stemming and phrase detection.
- Clickable transcript timestamps that open YouTube at the matching second.
- Matched search moments with timestamp links.
- Markdown export and clipboard copy.
- Research organization store for tags, video notes, timestamp notes, collections, clips, collection Markdown export, and collection JSON import/export.
- Backend event stream through `/api/events` with structured HTTP, storage, organization, and fetch events surfaced in the frontend log panel.
- Durable fetch run history with totals, successes, failures, skipped videos, timestamps, and retry metadata.
- Per-video fetch failures exposed through `/api/fetch/runs` and the frontend Settings tab.
- Retry controls for failed fetch items through `/api/fetch/retry-failed`.
- RSS-based channel watcher support with manual run-now action.
- Background watcher loop for scheduled refreshes.
- Watcher settings for enabled state, channels, refresh frequency, and transcript language preferences.
- Frontend Settings tab connected to watcher settings, current task status, fetch run history, failure details, and retry controls.
- AI Settings controls for provider, base URL, summary model, embedding model, timeout, temperature, connection testing, model refresh, and enable/disable.
- Ollama-first local model gateway through `/api/ai/settings`, `/api/ai/models`, and `/api/ai/health`.
- AI summary generation and reload through `/api/ai/transcripts/{video_id}/summary`.
- AI artifact history through `/api/ai/artifacts`.
- Transcript comparison through `/api/ai/compare` and the frontend AI Workspace selected-video controls.
- Topic timeline generation through `/api/ai/timeline` and the frontend AI Workspace timeline control.
- Local semantic index status, rebuild, and query endpoints through `/api/ai/embeddings/status`, `/api/ai/embeddings/rebuild`, and `/api/semantic-search`.
- Frontend AI Summary panel in transcript detail.
- Frontend AI Workspace panel for semantic index rebuild, selected-video comparison, and timeline generation.
- Read-only Claude Code MCP tools for transcript search, retrieval, stats, collections, Markdown export, and semantic search.
- Frontend Operations Center with separate Automation, AI, MCP, Data, and System sections.
- MCP status and enable/disable controls through `/api/mcp/status` and `/api/mcp/settings`, with `mcp_server.py` honoring the persisted toggle.
- Downloadable transcript data exports through `/api/data/export` for all transcripts, channels, selected videos, search results, and collection-linked transcripts.
- Data export formats for JSON, JSONL, CSV, and Markdown, with browser download support from the frontend.
- Read-only data browser through `/api/data/tables` and `/api/data/tables/{table_name}` for videos, channels, segments, fetch runs, collections, and AI artifacts.
- Safe system controls through `/api/system/status`, `/api/system/settings`, and `/api/system/cancel-task` for ingestion pause, maintenance mode, and cooperative task cancellation.
- Local security hardening: FastAPI binds to `127.0.0.1` by default and CORS is restricted to local frontend origins unless overridden.
- Root-level commands:
  - `npm run test`
  - `npm run lint`
  - `npm run build`
  - `npm run check`

### Current Data

- The active local archive contains 45 saved transcripts.
- The current archive is from one channel: `AI News & Strategy Daily | Nate B Jones`.
- Current stats from `/api/stats`:
  - 45 transcripts
  - 197,389 words
  - 29,791 transcript segments
  - about 60,971 seconds of transcript runtime

### Verification Status

The latest full verification passed:

```bash
npm run check
```

This command runs:

- `python -m unittest`
- Python compile checks for backend/core files
- frontend ESLint
- frontend production build

Current test count: 61 Python unit tests.

Additional verification completed after Stage 6:

- Installed `requirements.txt` so the new `mcp` dependency is present in the active Python environment.
- Verified `mcp_server.py` compiles and `mcp` imports successfully.
- Verified `.mcp.json` is valid JSON.
- Browser smoke tested `http://127.0.0.1:5173` against the restarted local backend/frontend:
  - Library loaded and backend status was connected.
  - Settings showed AI model controls.
  - Transcript detail showed the AI Summary panel.
  - Library showed AI Workspace controls for semantic index, comparison, and timeline.
  - Browser console had no errors.

## Known Gaps And Risks

- `app.py` is a legacy Tkinter app with duplicated logic. It should be kept only if desktop support is still wanted.
- Stage 3 storage is now SQLite-ready, but existing local installs still need the migration action before their current JSON archive becomes SQLite-backed.
- Background task status is global process memory, so it supports only one visible task state at a time even though durable run history is now persisted.
- Metadata fetching scrapes YouTube HTML, which can break if YouTube changes markup.
- RSS handle resolution still depends on scraping YouTube channel HTML for `@handle` URLs when a channel ID is not supplied.
- Ollama must be installed and running locally for live summaries, comparisons, timelines, embeddings, and semantic search generation.
- The semantic index is local and explicit. It must be rebuilt from the AI Workspace or `/api/ai/embeddings/rebuild` before semantic search can return vector-ranked results.
- AI-generated tags are suggestions only; they do not overwrite human tags automatically.
- The MCP server is intentionally read-only in the first Stage 6 pass.
- Backend restart/shutdown from the browser is not implemented because the frontend cannot restart a backend process after it is stopped without a separate supervisor.
- Task cancellation is cooperative. It stops channel, watcher, retry, and embedding work at checkpoints, but it cannot interrupt an in-flight YouTube or Ollama network call.
- The data browser is intentionally read-only and table-whitelisted. It does not expose arbitrary SQL execution.
- No browser-based automated UI test is currently committed, though manual browser verification was run after Stage 6.

## Revised Roadmap

### Stage 1: Foundation Stabilization

Status: complete.

- Fix backend startup bugs.
- Normalize YouTube URL extraction.
- Normalize transcript segment parsing across API versions.
- Add deterministic unit tests.
- Add root npm scripts.
- Add root `.gitignore`.
- Fix frontend lint and build issues.

### Stage 2: Local Research Console

Status: complete.

- Add backend archive stats.
- Add backend ranked transcript search.
- Add channel filtering.
- Add matched timestamp moments in the UI.
- Add clickable top keyword chips.

Completed refinements:

- Add better keyword extraction with stemming or phrase detection.
- Add search result highlighting inside transcript text.
- Add sort controls: newest, longest, most matches, title.
- Add saved search queries.
- Add a compact video detail summary panel with word count, runtime, segment count, and match count.

### Stage 3: Storage Upgrade

Status: complete.

Goal: make the archive robust enough for hundreds or thousands of transcripts.

Steps:

1. Add a storage abstraction so JSON and SQLite can coexist during migration.
2. Introduce SQLite tables for videos, segments, channels, and fetch runs.
3. Add SQLite FTS for fast text search.
4. Add a user-facing one-time migration command or UI flow from `transcripts_store.json`.
5. Keep JSON export as a user-facing backup/export format, not the primary database.
6. Add tests for migration, deduplication, deletes, and search parity.

### Stage 4: Research Organization

Status: complete.

Goal: turn search results into reusable research assets.

Completed:

1. Add tags per transcript.
2. Add collections or projects.
3. Let users save timestamped clips into a collection.
4. Add notes per video and per timestamp.
5. Export a collection to Markdown with links, clips, notes, and source metadata.
6. Add import/export for collections.
7. Add structured backend events and surface those details in the frontend log panel.

### Stage 5: Fetch Reliability And Automation

Status: complete.

Goal: make ingestion trustworthy and repeatable.

Completed:

1. Track fetch runs with started time, finished time, totals, successes, failures, and skipped videos.
2. Show per-video fetch failures in the UI.
3. Add retry controls for failed videos.
4. Add RSS-based channel watcher.
5. Add a background worker loop for scheduled refreshes.
6. Add watcher settings for channels, fetch frequency, and transcript language preferences.

### Stage 6: AI-Assisted Knowledge Layer

Status: complete.

Goal: add optional intelligence without making the base app dependent on an external model.

Completed:

1. Added AI settings and model gateway.
   - Added `core/ai_settings.py` for persisted settings.
   - Added `core/ai_clients.py` for Ollama calls through stdlib HTTP.
   - Added `GET /api/ai/settings`, `PUT /api/ai/settings`, `GET /api/ai/models`, and `POST /api/ai/health`.
   - Added frontend Settings controls for provider, base URL, summary model, embedding model, timeout, temperature, enable/disable, model refresh, connection test, and save.

2. Added Ollama local summarization.
   - Uses Ollama generation and requests structured JSON output.
   - Added `GET` and `POST /api/ai/transcripts/{video_id}/summary`.
   - Stores concise summaries, key claims, entities, suggested tags, warnings, provider, model, prompt version, generated time, and stale status.
   - Displays saved/generated summaries in the selected transcript detail view.

3. Persisted AI artifacts.
   - Added `core/ai_artifacts.py` as JSON-backed storage that works with JSON and SQLite transcript backends.
   - Stores summaries, comparisons, timelines, and generic AI runs.
   - Added `/api/ai/artifacts` for frontend reload/history.

4. Added transcript comparison.
   - Added `POST /api/ai/compare`.
   - Added frontend selected-video comparison controls in the AI Workspace.
   - Stores generated comparison artifacts.

5. Added topic timeline views.
   - Added `POST /api/ai/timeline`.
   - Added frontend timeline trigger using selected comparison videos, the active channel filter, or a bounded default set.
   - Stores generated timeline artifacts.

6. Added semantic search using a local vector index.
   - Uses Ollama embeddings through `/api/embed`.
   - Uses the same embedding model for indexing and querying.
   - Chunks transcripts by segment windows and persists embeddings locally.
   - Added `POST /api/ai/embeddings/rebuild`, `GET /api/ai/embeddings/status`, and `GET /api/semantic-search`.
   - Added frontend semantic search input and AI Workspace rebuild control.

7. Added Claude Code MCP access.
   - Added `mcp_server.py` at the project root.
   - Added project-scoped `.mcp.json`.
   - Exposes read-only tools: `search_transcripts`, `get_transcript`, `list_transcripts`, `get_library_stats`, `list_collections`, `get_collection_markdown`, and `semantic_search`.
   - Does not expose delete, import, fetch, settings mutation, or model-generation tools.

8. Added tests and verification.
   - Added Python tests for AI settings normalization, artifact storage, mocked Ollama calls, semantic index behavior, and API endpoints.
   - Updated `npm run check` to compile new Stage 6 files and tests.

### Stage 7: Operations Center And Data Control

Status: complete.

Goal: make the local archive easier to operate from the browser without exposing unsafe backend or database controls.

Completed:

1. Split the frontend Settings surface into Automation, AI, MCP, Data, and System sections.
2. Reworked watcher settings into a watched-channel manager with add/remove controls, saved-channel status, frequency, languages, and manual run-now.
3. Added MCP status and enable/disable settings, backed by `core/runtime_settings.py` and enforced by `mcp_server.py`.
4. Added downloadable transcript export flows for all, channel, selected, search, and collection scopes in JSON, JSONL, CSV, and Markdown.
5. Added a read-only data browser for whitelisted operational tables.
6. Added system controls for ingestion pause, maintenance mode, and cooperative task cancellation.
7. Added tests for runtime settings, operation endpoints, MCP disabling, data export, data tables, and system controls.
   - Ran `npm run check`.
   - Ran browser smoke tests for the Operations Center, Automation, MCP, Data, and System sections.

## Immediate Next Implementation Options

Recommended next task: **Stage 8, ingest throughput under rate limiting.**

Why: this is now the binding constraint, and it is measured, not guessed. A 40-video
run on 2026-08-14 saved 23 and then hit `RequestBlocked` on every remaining video.
The block persisted for over 20 minutes and starved a second channel run completely.
Depth, dedupe, and backoff are solved; how many transcripts per hour the archive can
actually absorb is not.

Concretely, in priority order:

1. ~~**Persist a rate-limit cooldown.**~~ **DONE 2026-08-14.** A run that gives up now
   parks ingestion in `fetch_reliability.json` until the block has plausibly aged out.
   Fetch endpoints answer `429` with the remaining wait, the watcher skips its scheduled
   runs, and consecutive blocks escalate the wait (~22m, ~51m, ~98m) while a clean run
   resets the strike count. `POST /api/fetch/cooldown/clear` overrides it deliberately,
   because the duration is a guess — YouTube never says how long a block lasts.

   Backoff bases were also moved off round numbers and every wait is now jittered ±40%
   (`_jittered`). Retrying at exactly 30/90/180 seconds each time is a machine signature,
   which is the opposite of what backing off is for.
2. **Drain a queue instead of running bursts.** The watcher already runs on a timer.
   Turning "fetch 40 now" into "fetch a few every N minutes until the backlog is
   empty" fits the tool's real usage and stays under the limit. This subsumes the
   current retry-failed flow.
3. **Retry the leftovers automatically.** A run that stops early leaves a known set
   of unfetched ids; today re-fetching them is a manual second run.

Then, in rough value order:

4. **UI regression tests** (the original Stage 8 item). The settings surface and the
   new channel preview panel are both untested in a browser.
5. **Drop `scrapetube`.** It returns zero videos for every lookup shape since YouTube
   moved channel grids to `lockupViewModel`; `core/channel_listing.py` replaced it and
   it now only pads the fallback chain. Removing it drops a dependency.
6. **Verify the AI layer end to end.** Semantic search, summaries, and the MCP tools
   all need Ollama running and a built index. None of it has been exercised against a
   live model recently, and it is the part the project is presented on.
7. **Retire `app.py`.** The legacy Tkinter app duplicates fetch logic that has now
   diverged from `main.py` (no dedupe, no deep listing, no backoff).

## Stage 9: The Retrieval Contract

Sourced from the archive itself — Nate B Jones, "Pinecone Just Demoted Vector Search.
Here's the Knowledge Layer." (`lqiwQiDglGk`), plus "Paste This Into Claude, Never Hit a
Token Limit Again" (`Y8vAQ1FgNbM`) and "Anthropic Just Gave Your AI Agent the One Thing
OpenClaw Has" (`vqnAOV8NMZ4`).

His argument, compressed: classic RAG (chunk → embed → top-k) was built for chatbot
question answering, where the answer lives in a couple of paragraphs. Agents don't ask a
question and stop; they run a task, and they need a *bundle* assembled in the right shape.
The retrieval unit has to match the work. Bigger context windows do not fix this — they
give the model more room but do not decide what belongs in the room ("context rot"). His
build order is: define the retrieval contract, write down the bundle field by field, then
choose primitives that deliver it. Never database-first.

Measured against that, this project is a chatbot-era retrieval system serving agent-era
requests.

### 9.1 Cap what `fetch` returns, and return passages instead of documents — DONE 2026-08-14

The MCP `fetch` tool returns `entry["transcript"]` uncapped, while every neighbouring
tool routes through `_cap_text`. At the current archive that is ~5,600 tokens for an
average video and ~11,300 for the largest. **A ten-video research question costs roughly
96,000 tokens of raw transcript**, most of it irrelevant to the question asked. This is
precisely the reused-input problem from `Y8vAQ1FgNbM`, reproduced inside an archive of
that video.

Two changes, in order of value:

- Cap `fetch` like the others (small).
- Add a passage-level retrieval tool: return the N matching windows with their
  timestamps and video ids, not the document. The segment data already exists; this is a
  retrieval-shape change, not new storage.

Keep whole-document `fetch` available — it is the correct unit when the agent has already
decided a specific video is the subject. It is the wrong *default*.

**Shipped.** `fetch` is now bounded (`YT_TRANSCRIPTS_MCP_FETCH_CHARS`, default 50k chars)
and reports truncation. `search_passages` returns scored windows of consecutive caption
segments with timecodes and `&t=` deep links, spread across videos by a per-video cap.

Two things surfaced during implementation that were not visible from the outside:

- **Caption segments are useless as passages on their own.** They average 37 characters
  and about four seconds, and break mid-sentence. A passage has to be a run of consecutive
  segments rejoined; the default window is 16 (~60s, ~600 chars).
- **The existing matcher is all-terms-or-nothing.** `core.research._text_matches` requires
  every query term in the same text, and the FTS candidate query ANDs its terms. At
  document level that mostly works; at segment level it returns nothing, so a query like
  "agent memory rag vector search" produced zero passages. `search_passages` scores by
  term coverage and uses an OR-ranked bm25 candidate pool instead. The document-level
  search was left alone — changing it would move results the UI depends on.

Measured on the live endpoint: six passages across four videos for 915 tokens, against
5,647 tokens for a single full `fetch` of just the top video.

### 9.2 Name the retrieval unit for each question type

The archive's natural shapes, and which already exist:

| Question | Right unit | Status |
| --- | --- | --- |
| "Where does he say X?" | passage + timestamp | segments stored, not exposed as a unit |
| "What is video Y about?" | compiled brief | AI summaries exist, not reachable over MCP |
| "How did his view on X change?" | ordered claims across videos | timeline exists in the UI only |
| "What connects X to Y?" | entity/topic neighbourhood | not built |

The gap is not storage. It is that the useful units are trapped behind the UI while MCP
only offers document-shaped tools.

### 9.3 Vector storage: `sqlite-vec`, not a vector database

`semantic_index.json` is loaded whole and scored with brute-force cosine in Python. Fine
at 76 transcripts, wrong by a few thousand. The move is the `sqlite-vec` extension: it
keeps the single-file, no-extra-service architecture the project already has and adds
ANN in place.

Explicitly **not** Pinecone/Weaviate/Chroma-as-a-service. Adding a hosted vector database
to a local personal archive is the shopping-spree failure `lqiwQiDglGk` warns about — the
retrieval contract here does not need it.

### 9.4 Mark provenance before derived data accumulates

`lqiwQiDglGk` names the failure mode directly: an agent can store its own inference as a
confirmed fact and quietly poison later runs. This archive is about to mix two very
different classes of data — transcript text, which is ground truth about what was said,
and model-generated summaries and tags, which are inference.

Every retrieval result should carry which one it is. Doing this now is a field on a
response; doing it after a few thousand artifacts exist is a migration.

### 9.5 Instrument retrieval

"The cheapest place to learn what you need is your own work logs." There is rich
telemetry for *fetching* (`fetch_runs`, `backend_events`) and none for *retrieval*. Worth
recording per MCP call: tokens returned, whether the same video was fetched twice in a
session, and how many calls happen before the agent stops searching. Those numbers decide
whether 9.2 and 9.3 are worth building, instead of guessing.

### Out of scope, deliberately

- KV-cache compression (TurboQuant, `erV_8yrGMA8`) is model-infrastructure, nothing to
  act on here.
- Cross-tool context portability / BYOC (`4KAF72BTyCE`) is a much larger product idea
  than this archive. Worth noting that a local SQLite store behind MCP is already the
  shape he recommends for owning your own memory ("OpenBrain", `vqnAOV8NMZ4`) — this
  project is an instance of that pattern, not a candidate for replacing it.

## Session Log: 2026-08-14

- Bulk channel fetch was capped at 15 videos because RSS returns only the 15 newest
  uploads, and the `scrapetube` fallback silently returned nothing. Replaced with
  `core/channel_listing.py`, which reads the channel page grid and follows
  continuations. Verified at depth: 150 listed for one channel.
- Channel fetch had no dedupe at all. It now filters against stored video ids before
  requesting anything, and `POST /api/fetch/channel/preview` lists recent titles
  flagged new vs archived so a run can be scoped first.
- Added rate-limit detection with 30s/90s/180s backoff and an early stop.
- Merged the duplicate channel that older archives created by storing `&`
  verbatim in channel names. 45 + 30 rows folded into one.
- Fixed test isolation: settings and index paths were resolved at import time, so
  with `YT_TRANSCRIPTS_DATA_DIR` set the suite rewrote the live data directory and
  left ingestion paused. Suite went from 68 tests with 5 failures to 89 passing.

## Working Commands

From the project root:

```bash
python -m pip install -r requirements.txt
python run.py
npm run test
npm run lint
npm run build
npm run check
```

Manual run:

```bash
python main.py
cd frontend
npm run dev
```

Backend URL:

```text
http://127.0.0.1:8000
```

Frontend URL:

```text
http://localhost:5173
```

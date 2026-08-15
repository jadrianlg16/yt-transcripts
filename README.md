# 🎥 YouTube Transcript Pro

**YouTube Transcript Pro** is a high-performance research gathering tool designed to archive, manage, and search through YouTube transcripts and metadata.

---

## 🚀 NEW: Web-Based UI (Recommended)

The project has been upgraded from Tkinter to a modern web interface.

### Prerequisites
- Docker Desktop (recommended for Project Dashboard)
- Or Python 3.10+ plus Node.js & npm for local development

### Run from Project Dashboard (recommended)

The existing **YouTube Transcripts** card starts this Compose stack and opens
`http://localhost:5014`. Runtime state is stored in the host `data/` directory,
so container rebuilds and recreations keep the SQLite archive.

The browser uses the frontend as its only public entry point. Nginx forwards
`/api` requests to the backend inside Docker, while port `8014` remains bound to
localhost for diagnostics.

### Run with Docker directly

```bash
docker compose up -d --build
```

Open `http://localhost:5014`. To stop the stack without deleting its data:

```bash
docker compose down
```

### Connect an AI model through MCP

The Compose stack also starts a read-only MCP endpoint at
`http://127.0.0.1:8001/mcp`. Turn MCP access on from **Settings > MCP**, then
connect a local MCP-compatible client using the included `.mcp.json` file.

The compatibility tools follow the frontier-model retrieval contract:

- `search(query)` returns document IDs, video titles, and canonical YouTube URLs.
- `fetch(id)` returns the transcript plus source metadata, bounded so one very long
  video cannot swallow a caller's context window. Truncation is reported in the
  metadata, and `YT_TRANSCRIPTS_MCP_FETCH_CHARS` moves the cap.

#### Passages, not documents

`search_passages(query)` is the tool to reach for when the question is "where was this
said?" rather than "give me this video". It returns the best-matching windows of speech
with their timecodes and links that open the video at that moment:

```json
{
  "text": "companies don't store their most important knowledge in the kind of text or prose that rag is designed to solve for...",
  "start_timecode": "10:23",
  "url": "https://www.youtube.com/watch?v=lqiwQiDglGk&t=623s",
  "content_type": "verbatim_transcript"
}
```

Why it exists: a whole transcript averages several thousand tokens, so answering one
research question by fetching the handful of relevant videos costs tens of thousands of
tokens, most of them irrelevant to the question. The same question answered from passages
costs about a thousand, and every claim arrives with a citation.

Results are spread across videos rather than stacking on the single best match
(`max_per_video`), and each response reports its own `estimated_tokens`. `content_type`
marks passages as verbatim transcript so a caller can always tell recorded speech from
anything a model inferred.

Search works immediately with lexical ranking. If local AI is enabled and a
semantic index has been built from the AI settings screen, it automatically
combines lexical and Ollama vector rankings. In Docker, Ollama is reached on the
Windows host through `host.docker.internal`.

The MCP port is bound only to this computer. A hosted model cannot call a
localhost URL directly; use an authenticated HTTPS deployment or a secure MCP
tunnel before connecting a remote client. Do not expose port `8001` publicly
without authentication.

### Setup & Run locally (One-Step)

Simply run the helper script to start both backend and frontend:
```bash
python run.py
```
This will start both servers and open your browser automatically.

### Setup & Run (Manual)

If you prefer to run them separately:

1. **Backend**:
   ```bash
   pip install -r requirements.txt
   python main.py
   ```
   The backend will run on `http://localhost:8000`.

2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   The frontend will run on `http://localhost:5173`.

### Features
- **Real-time Progress**: Visual tracking for bulk fetches.
- **Advanced Search**: Search through titles and full transcript text.
- **Exporting**: Save as Markdown or copy directly to clipboard.
- **Clean UI**: Built with React and Tailwind CSS for a professional look.
- **Operations Center**: Browser settings are split into Automation, AI, MCP, Data, and System views.
- **Watched Channels**: Add, remove, pause, and manually run RSS-based channel checks from the frontend.
- **MCP Control**: View read-only MCP tools and turn MCP access on or off from the frontend.
- **Data Exports**: Download all transcripts, channel subsets, search results, selected videos, or collection-linked transcripts as JSON, JSONL, CSV, or Markdown.
- **Read-only Data Browser**: Inspect videos, channels, segments, fetch runs, collections, and AI artifacts without exposing arbitrary SQL.
- **System Controls**: Pause new ingestion, enable maintenance mode, and request cooperative cancellation of active background work.

---

## 🚀 Current Features

### 💻 Modern Desktop Interface
- **Pro UI:** A clean, resizable split-view (PanedWindow) built with a modern color palette and Segoe UI typography.
- **Smart Search:** Real-time keyword filtering across all saved transcripts in your local database.
- **Progress Tracking:** Interactive progress bars and status labels keep you informed during long batch operations.
- **Metadata Card:** At-a-glance view of video title, channel, video ID, and archive date.

### 📥 Fetching Engine
- **Single Video Fetch:** Quick archival of any YouTube URL (Videos, Shorts, etc.).
- **Channel Preview:** List a channel's recent uploads and see which titles the archive already
  holds *before* fetching anything. Pick exactly what you want, or take everything new.
- **Deep Channel Listing:** Reads the channel page grid and follows continuations, so a bulk
  fetch is not capped at the 15 videos YouTube's RSS feed returns. `limit` controls the depth
  (default 30, max 500; leave it blank to walk the whole channel).
- **Deduplication Before Download:** Video ids already in the archive are filtered out before
  any transcript request is made, so re-running a channel only costs one listing request.
- **Request Pacing:** Randomised delays between videos and a fixed delay between listing pages
  keep a bulk run from hammering YouTube.
- **Backoff And Cooldown:** When YouTube starts blocking transcript requests the run waits,
  then gives up and leaves the rest unfetched rather than burning the list collecting
  failures. Ingestion is then parked until the block has plausibly aged out, so the next
  run does not walk straight back into it. Every wait is jittered.

The listing tiers itself by depth: `limit` ≤ 15 uses the channel RSS feed (one cheap request),
anything deeper reads the channel page. If one source fails the other is tried, so a YouTube
markup change degrades the listing instead of breaking it.

### 📂 Organized Storage
- **SQLite Database:** SQLite is the canonical runtime archive; JSON remains a portable backup/export format.
- **Persistent Docker Data:** Docker reads and writes runtime files beneath the host `data/` directory.
- **Channel Folders:** Bulk exports are neatly organized into channel-specific directories within the `/channels` folder.
- **One-Click Export Access:** Direct button to open your storage folder in the system file explorer.
- **SQLite-ready Storage:** The web UI can migrate JSON archives to SQLite and keep JSON exports as portable backups.
- **Browser Downloads:** The Data view creates downloadable transcript dumps from the active archive.

### Operational Limits
- The MCP server remains read-only. The frontend toggle disables the project MCP tools but does not add write tools.
- Backend restart/shutdown is not exposed in the browser. That requires the external `run.py` supervisor because a stopped backend cannot answer frontend requests.
- Active task cancellation is cooperative and takes effect between worker checkpoints; it cannot interrupt an in-flight YouTube or Ollama request.
- The data browser is table-whitelisted and read-only by design.

---

## 🛠️ Installation & Setup

1. **Clone/Download** this repository.
2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the Application:**
   ```bash
   python app.py
   ```

---

## 🧠 The Future Roadmap (Brainstorming)

We are moving from a "Scraping Tool" to a **Personal Knowledge Engine**. Here are the planned upgrades:

### 1. 🛰️ Automatic "Watcher" Service
- **RSS Integration:** Automatically monitor channel RSS feeds to detect and archive new uploads the moment they go live.
- **Background Worker:** A headless service that runs in the background to keep your library up to date without opening the UI.

### 🤖 2. AI & LLM Connectivity (MCP Server)
- **Model Context Protocol (MCP):** Implementation of an MCP server to allow Claude Desktop and other AI agents to query your local transcript database directly.
- **Local RAG:** Use semantic search (Vector DB) so you can ask AI questions like: *"Find videos where the speaker sounds skeptical about AI regulations."*

### 🛡️ 3. Fetch Resilience
- **Backoff On 429:** Detect rate-limit responses and pause the run instead of burning retries.
- **Listing Health Checks:** Alert when a listing source starts returning zero videos, which is
  the signal that YouTube changed its markup again.

### 📊 4. Multi-Source Intelligence
- **Beyond YouTube:** Adding support for Podcasts (via OpenAI Whisper), Spotify RSS feeds, and clean web-article extraction.
- **Automatic Summarization:** Integration with local LLMs (via Ollama) to generate 3-sentence summaries and automatic tags (#Tech, #Finance) for every new transcript.

### 📍 5. Semantic Navigation
- **Clickable Timestamps:** Clicking a sentence in the transcript will open the YouTube video at the exact second the words were spoken.

---

### When ingestion is paused

After a run gives up, `GET /api/fetch/cooldown` reports how long is left and how many
consecutive blocks have happened. Fetch endpoints answer `429` with the remaining wait
while it is active, and the channel watcher skips its scheduled runs.

The wait is a guess, not a measurement — YouTube does not say how long a block lasts. If it
is longer than reality, clear it deliberately:

```bash
curl -X POST http://localhost:5014/api/fetch/cooldown/clear
```

## ⚖️ Responsible Use

This is a personal research archive. Read this before running it.

- **No account, ever.** The app never signs in, stores cookies, or uses an API key. It reads
  publicly available captions and public page metadata only. There is no YouTube account
  attached to it and nothing here attempts to bypass a login, a paywall, or DRM.
- **The archive stays local.** Transcripts belong to the people who made the videos. `data/`,
  `channels/`, `exports/`, and both transcript stores are git-ignored on purpose. Do not commit
  fetched transcripts, and do not republish them.
- **Automated access is against YouTube's Terms of Service.** Google's ToS permit automated
  access only for public search engines following `robots.txt`, with written permission, or
  where applicable law allows. Running this tool is your decision and your responsibility.
- **Be polite.** The default delays exist for a reason. Raising `limit` to walk an entire large
  channel means hundreds of requests; do that rarely, and expect HTTP 429 if you do it often.
- **Not affiliated with YouTube or Google.**

## 📜 License
MIT License. Created for educational and research purposes.

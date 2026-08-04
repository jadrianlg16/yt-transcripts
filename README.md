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
`/api` requests to the backend inside Docker, while port `8000` remains bound to
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
- `fetch(id)` returns the complete transcript plus source metadata.

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

### 📥 Powerful Fetching Engine
- **Single Video Fetch:** Quick archival of any YouTube URL (Videos, Shorts, etc.).
- **Bulk Channel Fetch:** Powered by `scrapetube`, download every transcript from an entire channel automatically.
- **Smart Deduplication:** The app automatically detects if a video has already been archived to save time and bandwidth.
- **Stealth Mode:** Built-in random timeouts (jitter) between requests to mimic human behavior and prevent IP blocks.

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

### 🛡️ 3. Advanced Stealth Layer
- **Cookie Support:** Ability to import browser cookies to mimic a logged-in user, significantly reducing the risk of 429 errors.
- **Proxy Rotation:** Integration for residential proxies and ephemeral cloud-based fetchers (AWS Lambda/Google Cloud).

### 📊 4. Multi-Source Intelligence
- **Beyond YouTube:** Adding support for Podcasts (via OpenAI Whisper), Spotify RSS feeds, and clean web-article extraction.
- **Automatic Summarization:** Integration with local LLMs (via Ollama) to generate 3-sentence summaries and automatic tags (#Tech, #Finance) for every new transcript.

### 📍 5. Semantic Navigation
- **Clickable Timestamps:** Clicking a sentence in the transcript will open the YouTube video at the exact second the words were spoken.

---

## 📜 License
MIT License. Created for educational and research purposes.

from collections import deque
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Any, List, Optional
from datetime import datetime, timedelta
import csv
import io
import json
import os
import re
import sqlite3
import time
import random
import scrapetube
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from core.store import DATA_FILE, SQLITE_DATA_FILE, TranscriptRepository, create_transcript_store
from core.channel_listing import list_channel_videos
from core.fetcher import extract_video_id, fetch_video_full
from core.fetch_reliability import DEFAULT_RELIABILITY_FILE, FetchReliabilityStore, youtube_watch_url
from core.organization import DEFAULT_ORGANIZATION_FILE, ResearchOrganizationStore, utc_now
from core.research import library_stats, search_entries
from core.sqlite_store import SQLiteTranscriptStore, export_entries_to_json, migrate_json_to_sqlite
from core.ai_artifacts import DEFAULT_AI_ARTIFACTS_FILE, AIArtifactStore, transcript_hash
from core.ai_clients import OllamaClientError, ollama_client_from_settings
from core.ai_settings import DEFAULT_AI_SETTINGS_FILE, AISettingsStore
from core.paths import data_path
from core.runtime_settings import (
    DEFAULT_MCP_SETTINGS_FILE,
    DEFAULT_SYSTEM_SETTINGS_FILE,
    load_mcp_settings,
    load_system_settings,
    update_mcp_settings,
    update_system_settings,
)
from core.semantic_search import (
    DEFAULT_INDEX_PATH,
    SemanticIndexStore,
    load_semantic_index,
    rebuild_semantic_index,
    stale_transcript_ids,
)

import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
TRANSCRIPTS_JSON_PATH = data_path(DATA_FILE)
TRANSCRIPTS_SQLITE_PATH = data_path(SQLITE_DATA_FILE)
ORGANIZATION_PATH = data_path(DEFAULT_ORGANIZATION_FILE)
RELIABILITY_PATH = data_path(DEFAULT_RELIABILITY_FILE)
AI_SETTINGS_PATH = data_path(DEFAULT_AI_SETTINGS_FILE)
AI_ARTIFACTS_PATH = data_path(DEFAULT_AI_ARTIFACTS_FILE)
MCP_SETTINGS_PATH = data_path(DEFAULT_MCP_SETTINGS_FILE)
SYSTEM_SETTINGS_PATH = data_path(DEFAULT_SYSTEM_SETTINGS_FILE)
SEMANTIC_INDEX_PATH = data_path(DEFAULT_INDEX_PATH)
EXPORTS_DIR = data_path("exports")
CHANNELS_DIR = data_path("channels")

store: TranscriptRepository = create_transcript_store(
    json_path=str(TRANSCRIPTS_JSON_PATH),
    sqlite_path=str(TRANSCRIPTS_SQLITE_PATH),
)
organization_store = ResearchOrganizationStore(ORGANIZATION_PATH)
reliability_store = FetchReliabilityStore(RELIABILITY_PATH)
ai_settings_store = AISettingsStore(AI_SETTINGS_PATH)
ai_artifact_store = AIArtifactStore(AI_ARTIFACTS_PATH)
semantic_index_store = SemanticIndexStore(str(SEMANTIC_INDEX_PATH))
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
BACKEND_EVENTS_LIMIT = 300
backend_events = deque(maxlen=BACKEND_EVENTS_LIMIT)
backend_event_id = 0
watcher_stop_event = threading.Event()
watcher_thread: threading.Thread | None = None
task_status_lock = threading.Lock()
task_cancel_event = threading.Event()

# Kept in step with the @mcp.tool functions in mcp_server.py; test_stage7_operations
# asserts the two lists match so a new tool cannot go missing from the UI.
MCP_TOOL_NAMES = [
    "search",
    "fetch",
    "search_passages",
    "list_transcripts",
    "search_transcripts",
    "get_transcript",
    "get_library_stats",
    "list_collections",
    "get_collection_markdown",
    "semantic_search",
]

DATA_TABLES = [
    "videos",
    "channels",
    "segments",
    "fetch_runs",
    "collections",
    "ai_artifacts",
]

DATA_EXPORT_FORMATS = {
    "json": "application/json",
    "jsonl": "application/x-ndjson",
    "csv": "text/csv",
    "markdown": "text/markdown",
}

# Global status for background tasks
task_status = {
    "run_id": None,
    "current_task": None,
    "progress": 0,
    "total": 0,
    "message": "Idle",
    "started_at": None,
    "updated_at": None,
    "finished_at": None,
    "success_count": 0,
    "failure_count": 0,
    "skipped_count": 0,
    "recent_events": [],
}


def record_event(
    level: str,
    event: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global backend_event_id

    backend_event_id += 1
    item = {
        "id": backend_event_id,
        "timestamp": utc_now(),
        "level": level,
        "event": event,
        "message": message,
        "details": details or {},
    }
    backend_events.append(item)

    log_method = logger.error if level == "error" else logger.warning if level == "warning" else logger.info
    log_method("%s: %s | %s", event, message, item["details"])
    return item


def update_task_status(**updates):
    task_status.update(updates)
    task_status["updated_at"] = utc_now()

    recent_event = {
        "time": task_status["updated_at"],
        "message": task_status.get("message", ""),
        "progress": task_status.get("progress", 0),
        "total": task_status.get("total", 0),
    }
    task_status["recent_events"] = [recent_event, *task_status.get("recent_events", [])[:9]]


def begin_task(task_type: str, message: str, total: int = 0, run_id: str | None = None) -> str:
    run_id = run_id or uuid4().hex
    now = utc_now()
    task_cancel_event.clear()
    with task_status_lock:
        task_status.update({
            "run_id": run_id,
            "current_task": task_type,
            "progress": 0,
            "total": total,
            "message": message,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "success_count": 0,
            "failure_count": 0,
            "skipped_count": 0,
            "recent_events": [],
        })
    record_event("info", "task_started", message, {"run_id": run_id, "task": task_type})
    return run_id


def queue_task(task_type: str, message: str, total: int = 0) -> str:
    now = utc_now()
    run_id = uuid4().hex
    with task_status_lock:
        if task_status.get("current_task"):
            active_message = task_status.get("message") or task_status.get("current_task")
            raise HTTPException(status_code=409, detail=f"Task already running: {active_message}")

        task_status.update({
            "run_id": run_id,
            "current_task": task_type,
            "progress": 0,
            "total": total,
            "message": message,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "success_count": 0,
            "failure_count": 0,
            "skipped_count": 0,
            "recent_events": [{
                "time": now,
                "message": message,
                "progress": 0,
                "total": total,
            }],
        })

    record_event("info", "task_queued", message, {"run_id": run_id, "task": task_type})
    return run_id


def finish_task(message: str, level: str = "success"):
    update_task_status(message=message, finished_at=utc_now())
    record_event(level, "task_finished", message, {
        "run_id": task_status.get("run_id"),
        "success_count": task_status.get("success_count", 0),
        "failure_count": task_status.get("failure_count", 0),
        "skipped_count": task_status.get("skipped_count", 0),
    })
    task_status["current_task"] = None


def transcript_lookup() -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("video_id")): entry
        for entry in store.all_entries()
        if entry.get("video_id")
    }


def saved_video_ids() -> set[str]:
    """Existing video ids only. Avoids loading every transcript just to dedupe."""
    reader = getattr(store, "saved_video_ids", None)
    if callable(reader):
        return reader()
    return set(transcript_lookup())


def require_transcript(video_id: str) -> dict[str, Any]:
    entry = transcript_lookup().get(video_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return entry


def _segment_text_at(transcript: dict[str, Any], start: float) -> str:
    target = float(start or 0)
    segments = transcript.get("segments") or []
    if not isinstance(segments, list):
        return ""

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_start = float(segment.get("start") or 0)
        segment_duration = float(segment.get("duration") or 0)
        if segment_start <= target <= segment_start + max(segment_duration, 0):
            return str(segment.get("text") or "")

    return ""

def _entry_count_from_json(path: str) -> int:
    if not os.path.exists(path):
        return 0

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return 0

    return len(data) if isinstance(data, list) else 0

def _entry_count_from_sqlite(path: str | Path) -> int:
    if not os.path.exists(path):
        return 0

    try:
        with sqlite3.connect(path) as connection:
            row = connection.execute("SELECT COUNT(*) FROM videos").fetchone()
            return int(row[0]) if row else 0
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return 0

def _storage_status():
    sqlite_exists = TRANSCRIPTS_SQLITE_PATH.exists()
    active_backend = "sqlite" if isinstance(store, SQLiteTranscriptStore) else "json"

    return {
        "backend": active_backend,
        "active_count": len(store.all_entries()),
        "json": {
            "path": str(TRANSCRIPTS_JSON_PATH.resolve()),
            "exists": TRANSCRIPTS_JSON_PATH.exists(),
            "count": _entry_count_from_json(str(TRANSCRIPTS_JSON_PATH)),
        },
        "sqlite": {
            "path": str(TRANSCRIPTS_SQLITE_PATH.resolve()),
            "exists": sqlite_exists,
            "count": _entry_count_from_sqlite(TRANSCRIPTS_SQLITE_PATH),
            "fts_enabled": bool(getattr(store, "fts_enabled", False)) if active_backend == "sqlite" else False,
        },
    }


def _system_status() -> dict[str, Any]:
    settings = load_system_settings(SYSTEM_SETTINGS_PATH)
    return {
        "settings": settings,
        "backend": {
            "online": True,
            "restart_supported": False,
            "shutdown_supported": False,
            "message": "Backend restart requires the external run.py supervisor.",
        },
        "watcher": {
            "thread_alive": bool(watcher_thread and watcher_thread.is_alive()),
            "stop_requested": watcher_stop_event.is_set(),
        },
        "task": dict(task_status),
        "storage": _storage_status(),
    }


def _mcp_status() -> dict[str, Any]:
    config_path = Path(".mcp.json").resolve()
    settings_path = MCP_SETTINGS_PATH.resolve()
    settings = load_mcp_settings(MCP_SETTINGS_PATH)
    return {
        "enabled": settings["enabled"],
        "settings": settings,
        "server_name": "yt-transcripts-readonly",
        "read_only": True,
        "tools": MCP_TOOL_NAMES,
        "config": {
            "path": str(config_path),
            "exists": config_path.exists(),
        },
        "settings_file": str(settings_path),
        "storage_backend": _storage_status()["backend"],
    }


def _ensure_ingestion_allowed() -> None:
    settings = load_system_settings(SYSTEM_SETTINGS_PATH)
    if settings.get("maintenance_mode"):
        raise HTTPException(status_code=409, detail="Maintenance mode is enabled")
    if settings.get("ingestion_paused"):
        raise HTTPException(status_code=409, detail="Ingestion is paused")

    cooldown = reliability_store.get_cooldown()
    if cooldown["active"]:
        # 429 rather than 409: this is YouTube's limit being respected, not a
        # local switch. Clear it deliberately via /api/fetch/cooldown/clear.
        raise HTTPException(
            status_code=429,
            detail=(
                "YouTube rate limited the last run. Waiting "
                f"{_format_cooldown_wait(cooldown['remaining_seconds'])} before fetching again."
            ),
        )


def _task_cancel_requested() -> bool:
    return task_cancel_event.is_set()


def _finish_canceled_task(run_id: str | None, message: str = "Task canceled") -> None:
    if run_id:
        reliability_store.finish_run(run_id, status="canceled", message=message)
    finish_task(message, level="warning")
    task_cancel_event.clear()


def _compact_text(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _entry_runtime_seconds(entry: dict[str, Any]) -> float:
    segments = entry.get("segments") or []
    if not isinstance(segments, list) or not segments:
        return 0
    values = []
    for segment in segments:
        if isinstance(segment, dict):
            try:
                values.append(float(segment.get("start") or 0) + float(segment.get("duration") or 0))
            except (TypeError, ValueError):
                continue
    return max(values) if values else 0


def _collection_video_ids(collection_id: str) -> list[str] | None:
    snapshot = organization_store.snapshot()
    for collection in snapshot.get("collections", []):
        if collection.get("id") == collection_id:
            seen: set[str] = set()
            ids: list[str] = []
            for clip in collection.get("clips", []):
                video_id = str(clip.get("video_id") or "").strip()
                if video_id and video_id not in seen:
                    seen.add(video_id)
                    ids.append(video_id)
            return ids
    return None


def _transcript_export_entries(request: "DataExportRequest") -> list[dict[str, Any]]:
    entries = store.all_entries()
    scope = (request.scope or "all").strip().lower()

    if scope == "all":
        filtered = entries
    elif scope == "channel":
        channel = (request.channel or "").strip().lower()
        if not channel:
            raise HTTPException(status_code=400, detail="channel is required for channel exports")
        filtered = [entry for entry in entries if str(entry.get("channel") or "").strip().lower() == channel]
    elif scope == "selected":
        video_ids = [str(video_id).strip() for video_id in request.video_ids or [] if str(video_id).strip()]
        if not video_ids:
            raise HTTPException(status_code=400, detail="video_ids are required for selected exports")
        wanted = set(video_ids)
        filtered = [entry for entry in entries if entry.get("video_id") in wanted]
    elif scope == "collection":
        if not request.collection_id:
            raise HTTPException(status_code=400, detail="collection_id is required for collection exports")
        video_ids = _collection_video_ids(request.collection_id)
        if video_ids is None:
            raise HTTPException(status_code=404, detail="Collection not found")
        wanted = set(video_ids)
        filtered = [entry for entry in entries if entry.get("video_id") in wanted]
    elif scope == "search":
        query = (request.query or "").strip()
        if len(query) < 2:
            raise HTTPException(status_code=400, detail="query is required for search exports")
        results = search_entries(entries, query=query, channel=request.channel, limit=500, sort="relevance")
        wanted = {result["video_id"] for result in results}
        filtered = [entry for entry in entries if entry.get("video_id") in wanted]
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported export scope: {request.scope}")

    if not request.include_segments:
        return [{key: value for key, value in entry.items() if key != "segments"} for entry in filtered]
    return filtered


def _write_data_export(entries: list[dict[str, Any]], request: "DataExportRequest") -> tuple[Path, str]:
    export_format = (request.format or "json").strip().lower()
    if export_format == "md":
        export_format = "markdown"
    if export_format not in DATA_EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {request.format}")

    export_dir = EXPORTS_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = re.sub(r"[^a-z0-9_-]+", "-", (request.scope or "all").lower()).strip("-") or "all"
    extension = "md" if export_format == "markdown" else export_format
    export_path = export_dir / f"transcripts_{scope}_{timestamp}.{extension}"

    if export_format == "json":
        payload = {
            "version": 1,
            "exported_at": utc_now(),
            "scope": request.scope or "all",
            "count": len(entries),
            "transcripts": entries,
        }
        export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    elif export_format == "jsonl":
        export_path.write_text(
            "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + ("\n" if entries else ""),
            encoding="utf-8",
        )
    elif export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "video_id",
                "title",
                "channel",
                "saved_at",
                "uploaded_at",
                "fetched_at",
                "source_url",
                "segment_count",
                "word_count",
                "runtime_seconds",
                "transcript",
            ],
        )
        writer.writeheader()
        for entry in entries:
            transcript = str(entry.get("transcript") or "")
            writer.writerow({
                "video_id": entry.get("video_id", ""),
                "title": entry.get("title", ""),
                "channel": entry.get("channel", ""),
                "saved_at": entry.get("saved_at", ""),
                "uploaded_at": entry.get("uploaded_at", ""),
                "fetched_at": entry.get("fetched_at", ""),
                "source_url": entry.get("source_url", ""),
                "segment_count": len(entry.get("segments") or []),
                "word_count": len(transcript.split()),
                "runtime_seconds": round(_entry_runtime_seconds(entry), 2),
                "transcript": transcript,
            })
        export_path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    else:
        lines = [f"# YouTube Transcript Export", "", f"Exported: {utc_now()}", f"Transcripts: {len(entries)}", ""]
        for entry in entries:
            lines.extend([
                f"## {entry.get('title') or entry.get('video_id') or 'Untitled'}",
                "",
                f"- Channel: {entry.get('channel') or 'Unknown channel'}",
                f"- Video ID: {entry.get('video_id') or ''}",
                f"- Uploaded at: {entry.get('uploaded_at') or entry.get('saved_at') or 'Unknown'}",
                f"- Saved at: {entry.get('saved_at') or 'Unknown'}",
                "",
                str(entry.get("transcript") or "").strip(),
                "",
            ])
        export_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return export_path, DATA_EXPORT_FORMATS[export_format]


def _data_table_rows(table_name: str, limit: int = 50, offset: int = 0, q: str = "") -> dict[str, Any]:
    table = table_name.strip().lower()
    if table not in DATA_TABLES:
        raise HTTPException(status_code=404, detail="Data table not found")

    bounded_limit = max(1, min(limit, 200))
    bounded_offset = max(0, offset)
    query = q.strip().lower()
    rows = _build_data_table_rows(table)
    if query:
        rows = [
            row for row in rows
            if query in " ".join(str(value).lower() for value in row.values())
        ]

    columns = list(rows[0].keys()) if rows else _data_table_columns(table)
    paged_rows = rows[bounded_offset:bounded_offset + bounded_limit]
    return {
        "name": table,
        "columns": columns,
        "rows": paged_rows,
        "total": len(rows),
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


def _build_data_table_rows(table: str) -> list[dict[str, Any]]:
    entries = store.all_entries()
    if table == "videos":
        return [
            {
                "video_id": entry.get("video_id", ""),
                "title": entry.get("title", ""),
                "channel": entry.get("channel", ""),
                "saved_at": entry.get("saved_at", ""),
                "uploaded_at": entry.get("uploaded_at", ""),
                "segments": len(entry.get("segments") or []),
                "words": len(str(entry.get("transcript") or "").split()),
            }
            for entry in entries
        ]

    if table == "channels":
        counts: dict[str, int] = {}
        for entry in entries:
            channel = str(entry.get("channel") or "Unknown channel")
            counts[channel] = counts.get(channel, 0) + 1
        return [
            {"channel": channel, "transcripts": count}
            for channel, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
        ]

    if table == "segments":
        rows: list[dict[str, Any]] = []
        for entry in entries:
            for index, segment in enumerate(entry.get("segments") or []):
                if not isinstance(segment, dict):
                    continue
                rows.append({
                    "video_id": entry.get("video_id", ""),
                    "title": entry.get("title", ""),
                    "segment_index": index,
                    "start": segment.get("start", 0),
                    "duration": segment.get("duration", 0),
                    "text": _compact_text(segment.get("text"), 180),
                })
        return rows

    if table == "fetch_runs":
        return [
            {
                "id": run.get("id", ""),
                "type": run.get("type", ""),
                "status": run.get("status", ""),
                "source": run.get("source", ""),
                "started_at": run.get("started_at", ""),
                "finished_at": run.get("finished_at", ""),
                "total": run.get("total", 0),
                "success_count": run.get("success_count", 0),
                "failure_count": run.get("failure_count", 0),
                "skipped_count": run.get("skipped_count", 0),
            }
            for run in reliability_store.list_runs(limit=200)
        ]

    if table == "collections":
        return [
            {
                "id": collection.get("id", ""),
                "name": collection.get("name", ""),
                "description": collection.get("description", ""),
                "clips": len(collection.get("clips") or []),
                "updated_at": collection.get("updated_at", ""),
            }
            for collection in organization_store.snapshot().get("collections", [])
        ]

    artifacts: list[dict[str, Any]] = []
    for kind, items in ai_artifact_store.snapshot().items():
        if isinstance(items, dict):
            flat_items = [artifact for values in items.values() if isinstance(values, list) for artifact in values]
        elif isinstance(items, list):
            flat_items = items
        else:
            flat_items = []
        for artifact in flat_items:
            if isinstance(artifact, dict):
                artifacts.append({
                    "id": artifact.get("id", ""),
                    "type": artifact.get("type") or kind,
                    "status": artifact.get("status", ""),
                    "video_id": artifact.get("video_id", ""),
                    "model": artifact.get("model", ""),
                    "generated_at": artifact.get("generated_at", ""),
                })
    return sorted(artifacts, key=lambda item: str(item.get("generated_at") or ""), reverse=True)


def _data_table_columns(table: str) -> list[str]:
    return {
        "videos": ["video_id", "title", "channel", "saved_at", "uploaded_at", "segments", "words"],
        "channels": ["channel", "transcripts"],
        "segments": ["video_id", "title", "segment_index", "start", "duration", "text"],
        "fetch_runs": ["id", "type", "status", "source", "started_at", "finished_at", "total", "success_count", "failure_count", "skipped_count"],
        "collections": ["id", "name", "description", "clips", "updated_at"],
        "ai_artifacts": ["id", "type", "status", "video_id", "model", "generated_at"],
    }[table]


def preferred_languages() -> list[str]:
    return reliability_store.get_settings().get("languages") or ["en"]


def request_payload(model: BaseModel) -> dict[str, Any]:
    return (
        model.model_dump(exclude_unset=True)
        if hasattr(model, "model_dump")
        else model.dict(exclude_unset=True)
    )


def bounded_limit(value: int, default: int = 10, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def ai_settings_or_400(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    active_settings = settings or ai_settings_store.get_settings()
    if not active_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="AI is disabled in Settings")
    return active_settings


def ollama_client_for_settings(settings: dict[str, Any] | None = None):
    try:
        return ollama_client_from_settings(settings or ai_settings_store.get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def model_names(models: list[dict[str, Any]]) -> list[str]:
    names = []
    seen = set()
    for model in models:
        name = str(model.get("name") or model.get("model") or model.get("id") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return sorted(names)


def embedding_model_names(names: list[str]) -> list[str]:
    embedded = [name for name in names if "embed" in name.lower()]
    return embedded or names


def generation_model_names(names: list[str]) -> list[str]:
    generated = [name for name in names if "embed" not in name.lower()]
    return generated or names


def transcript_text(entry: dict[str, Any], max_chars: int = 30000) -> str:
    text = str(entry.get("transcript") or "").strip()
    if not text:
        text = " ".join(
            str(segment.get("text") or "")
            for segment in entry.get("segments") or []
            if isinstance(segment, dict)
        ).strip()
    return text[:max_chars]


def summary_artifact_payload(artifact: dict[str, Any], video_id: str, stale: bool = False) -> dict[str, Any]:
    content = artifact.get("content")
    if not isinstance(content, dict):
        content = {"summary": str(content or "")}

    payload = {
        **content,
        "video_id": video_id,
        "artifact_id": artifact.get("id"),
        "generated_at": artifact.get("generated_at"),
        "provider": artifact.get("provider"),
        "model": artifact.get("model"),
        "prompt_version": artifact.get("prompt_version"),
        "status": artifact.get("status"),
        "stale": stale,
        "error": artifact.get("error"),
    }
    return payload


def build_summary_prompt(entry: dict[str, Any]) -> str:
    return (
        "Summarize this YouTube transcript for a local research archive. "
        "Return only valid JSON with these keys: summary, key_claims, entities, "
        "suggested_tags, warnings. Use short strings in the arrays. "
        "Do not invent facts that are not supported by the transcript.\n\n"
        f"Title: {entry.get('title') or 'Untitled Video'}\n"
        f"Channel: {entry.get('channel') or 'Unknown Channel'}\n"
        f"Uploaded: {entry.get('uploaded_at') or ''}\n\n"
        f"Transcript:\n{transcript_text(entry)}"
    )


def build_compare_prompt(entries: list[dict[str, Any]]) -> str:
    sources = []
    for entry in entries:
        sources.append(
            f"Video ID: {entry.get('video_id')}\n"
            f"Title: {entry.get('title')}\n"
            f"Channel: {entry.get('channel')}\n"
            f"Transcript excerpt:\n{transcript_text(entry, max_chars=8000)}"
        )

    return (
        "Compare these YouTube transcripts for research. Return only valid JSON "
        "with keys: overlap, contradictions, unique_claims, shared_entities, source_notes. "
        "Use concise arrays and include video IDs when useful.\n\n"
        + "\n\n---\n\n".join(sources)
    )


def build_timeline_prompt(entries: list[dict[str, Any]]) -> str:
    sources = []
    for entry in sorted(entries, key=lambda item: item.get("uploaded_at") or item.get("saved_at") or ""):
        sources.append(
            f"Date: {entry.get('uploaded_at') or entry.get('saved_at') or ''}\n"
            f"Video ID: {entry.get('video_id')}\n"
            f"Title: {entry.get('title')}\n"
            f"Excerpt:\n{transcript_text(entry, max_chars=5000)}"
        )

    return (
        "Build a topic timeline from these saved YouTube transcripts. Return only valid JSON "
        "with keys: timeline, recurring_topics, open_questions. Timeline items should include "
        "date, topic, change, and video_id.\n\n"
        + "\n\n---\n\n".join(sources)
    )


def _fetch_and_save_video(
    video_id: str,
    run_id: str,
    index: int = 1,
    total: int = 1,
    url: str | None = None,
    languages: list[str] | None = None,
) -> dict[str, Any]:
    entry = fetch_video_full(video_id, languages=languages or preferred_languages())
    store.add_entry(entry)
    reliability_store.record_success(
        run_id,
        video_id=video_id,
        title=entry.get("title", ""),
        index=index,
        total=total,
        url=url or youtube_watch_url(video_id),
    )
    return entry


# YouTube starts refusing transcript requests after a burst. Backing off and then
# stopping the run beats burning through the rest of the list collecting failures:
# whatever is left stays unfetched, so the next run picks it up as new.
#
# The bases are deliberately uneven and every wait is jittered. A retry landing on
# exactly 30/90/180 seconds every time is a machine signature, and the point of
# backing off is to look less like something worth blocking.
RATE_LIMIT_BACKOFF_SECONDS = (43, 118, 227)
# Once a run gives up, hold off new work entirely, escalating per strike. Sized from
# observation, not taste: a ~14 minute wait was measured as still too short, and blocks
# have outlasted an hour. Waits below roughly twenty minutes only buy a wasted probe.
RATE_LIMIT_COOLDOWN_SECONDS = (2_311, 4_703, 8_419)  # ~38m, ~78m, ~140m
RATE_LIMIT_JITTER = 0.4
RATE_LIMIT_MARKERS = ("blocking requests", "too many requests", "429")


def _jittered(seconds: float, jitter: float = RATE_LIMIT_JITTER) -> int:
    """Spread a delay around its base so repeated waits never repeat exactly."""
    spread = max(0.0, min(jitter, 0.9))
    return max(1, int(seconds * random.uniform(1 - spread, 1 + spread)))


def _is_rate_limited(error: Exception | str) -> bool:
    from youtube_transcript_api._errors import IpBlocked, RequestBlocked

    if isinstance(error, (IpBlocked, RequestBlocked)):
        return True
    text = str(error).lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def _rate_limit_pause(consecutive: int, run_id: str) -> bool:
    """Sleep through a rate-limit streak. Returns False once the run should give up."""
    if consecutive > len(RATE_LIMIT_BACKOFF_SECONDS):
        return False

    delay = _jittered(RATE_LIMIT_BACKOFF_SECONDS[consecutive - 1])
    update_task_status(message=f"YouTube is rate limiting. Waiting {delay}s before retrying...")
    record_event("warning", "fetch_rate_limited", f"Rate limited; backing off {delay}s", {
        "run_id": run_id,
        "consecutive": consecutive,
        "delay_seconds": delay,
    })

    for _ in range(delay):
        if _task_cancel_requested():
            return False
        time.sleep(1)
    return True


def _begin_rate_limit_cooldown(run_id: str, reason: str) -> dict[str, Any]:
    """Park ingestion after a run gives up, so the next one does not re-trip the block."""
    strikes = reliability_store.get_cooldown().get("strikes") or 0
    index = min(int(strikes), len(RATE_LIMIT_COOLDOWN_SECONDS) - 1)
    cooldown = reliability_store.start_cooldown(
        _jittered(RATE_LIMIT_COOLDOWN_SECONDS[index]),
        reason=reason,
    )
    record_event(
        "warning",
        "ingestion_cooldown_started",
        f"Ingestion paused for {cooldown['remaining_seconds']}s after repeated rate limiting",
        {
            "run_id": run_id,
            "until": cooldown["until"],
            "remaining_seconds": cooldown["remaining_seconds"],
            "strikes": cooldown["strikes"],
        },
    )
    return cooldown


def _format_cooldown_wait(seconds: int) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"
    return f"{minutes}m {remainder}s" if minutes else f"{remainder}s"


def _record_fetch_failure(
    run_id: str,
    error: Exception | str,
    video_id: str | None = None,
    url: str | None = None,
    title: str = "",
    index: int | None = None,
    total: int | None = None,
) -> None:
    reliability_store.record_failure(
        run_id,
        video_id=video_id,
        url=url,
        title=title,
        error=str(error),
        index=index,
        total=total,
    )


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _next_watcher_check_at(frequency_minutes: int) -> str:
    return (
        datetime.now().astimezone()
        + timedelta(minutes=max(15, int(frequency_minutes or 360)))
    ).replace(microsecond=0).isoformat()


def channel_feed_url(channel: str) -> str:
    value = channel.strip()
    if not value:
        raise ValueError("Channel URL is required")

    if value.startswith("UC") and len(value) >= 20:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={value}"

    if "://" not in value:
        value = f"https://www.youtube.com/{value.lstrip('/')}"

    parsed = urlparse(value)
    if "feeds/videos.xml" in parsed.path:
        return value

    query_channel_id = parse_qs(parsed.query).get("channel_id", [None])[0]
    if query_channel_id:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={query_channel_id}"

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "channel":
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={parts[1]}"

    if parts and parts[0].startswith("@"):
        channel_id = resolve_youtube_channel_id(value)
        if channel_id:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    if parts:
        return f"https://www.youtube.com/feeds/videos.xml?user={parts[-1]}"

    raise ValueError(f"Could not build RSS feed URL for channel: {channel}")


def resolve_youtube_channel_id(channel_url: str) -> str | None:
    try:
        request = urllib.request.Request(channel_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            html_text = response.read().decode("utf-8", errors="ignore")
    except (OSError, urllib.error.URLError):
        return None

    for pattern in (
        r'"channelId":"(UC[^"]+)"',
        r'"externalId":"(UC[^"]+)"',
        r'<meta itemprop="channelId" content="(UC[^"]+)"',
    ):
        match = re.search(pattern, html_text)
        if match:
            return match.group(1)
    return None


def parse_youtube_rss_entries(xml_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(xml_text)
    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entries: list[dict[str, str]] = []
    for item in root.findall("atom:entry", namespace):
        video_id = item.findtext("yt:videoId", default="", namespaces=namespace).strip()
        title = item.findtext("atom:title", default="", namespaces=namespace).strip()
        link_item = item.find("atom:link", namespace)
        url = link_item.get("href") if link_item is not None else youtube_watch_url(video_id)
        if video_id:
            entries.append({
                "video_id": video_id,
                "title": title,
                "url": url or youtube_watch_url(video_id) or "",
            })
    return entries


def fetch_channel_rss_entries(channel: str) -> list[dict[str, str]]:
    feed_url = channel_feed_url(channel)
    request = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        xml_text = response.read().decode("utf-8", errors="ignore")
    return parse_youtube_rss_entries(xml_text)


# YouTube's RSS feed always returns the 15 newest uploads and nothing older, so it
# is only enough for incremental "what is new since last time" checks. Anything
# deeper has to come from the paginated browse listing that scrapetube walks.
RSS_FEED_DEPTH = 15
DEFAULT_CHANNEL_FETCH_LIMIT = 30
MAX_CHANNEL_FETCH_LIMIT = 500


def _scrapetube_title(video: dict[str, Any]) -> str:
    title = video.get("title")
    if isinstance(title, dict):
        runs = title.get("runs")
        if isinstance(runs, list) and runs:
            return str(runs[0].get("text") or "").strip()
        return str(title.get("simpleText") or "").strip()
    return str(title or "").strip()


def _scrapetube_published(video: dict[str, Any]) -> str:
    if video.get("published_text"):
        return str(video["published_text"]).strip()
    published = video.get("publishedTimeText")
    if isinstance(published, dict):
        return str(published.get("simpleText") or "").strip()
    return str(published or "").strip()


def _normalize_candidate(video: dict[str, Any]) -> dict[str, str] | None:
    video_id = str(video.get("videoId") or video.get("video_id") or "").strip()
    if not video_id:
        return None
    return {
        "videoId": video_id,
        "title": _scrapetube_title(video) or str(video.get("title") or ""),
        "url": str(video.get("url") or "") or youtube_watch_url(video_id) or "",
        "published_text": _scrapetube_published(video),
    }


def _dedupe_candidates(videos: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for video in videos:
        video_id = video["videoId"]
        if video_id in seen:
            continue
        seen.add(video_id)
        unique.append(video)
    return unique


def _channel_page_candidates(channel_url: str, limit: int | None) -> tuple[list[dict[str, str]], str]:
    """Read the channel page grid directly. This is the only source that pages deep."""
    videos = list_channel_videos(channel_url, limit=limit)
    return [c for c in (_normalize_candidate(v) for v in videos) if c], "channel_page"


def _scrapetube_candidates(channel_url: str, limit: int | None) -> tuple[list[dict[str, str]], str]:
    """Walk the channel's browse listing, newest first, across videos and streams."""
    errors: list[str] = []
    handle = channel_url.split("@")[-1].split("/")[0] if "@" in channel_url else None
    lookups: list[tuple[str, dict[str, Any]]] = [("scrapetube:url", {"channel_url": channel_url})]
    if handle:
        lookups.append(("scrapetube:handle", {"channel_username": handle}))

    for source, kwargs in lookups:
        collected: list[dict[str, str]] = []
        used_types: list[str] = []
        for content_type in ("videos", "streams"):
            remaining = None if limit is None else limit - len(collected)
            if remaining is not None and remaining <= 0:
                break
            try:
                videos = list(
                    scrapetube.get_channel(
                        **kwargs,
                        limit=remaining,
                        sort_by="newest",
                        content_type=content_type,
                    )
                )
            except Exception as exc:
                errors.append(f"{source}/{content_type} lookup failed: {exc}")
                continue
            normalized = [c for c in (_normalize_candidate(v) for v in videos) if c]
            if normalized:
                used_types.append(content_type)
                collected.extend(normalized)

        if collected:
            return _dedupe_candidates(collected), f"{source}:{'+'.join(used_types)}"

    if errors:
        raise ValueError("; ".join(errors))
    return [], "none"


def fetch_channel_video_candidates(
    channel_url: str,
    limit: int | None = None,
) -> tuple[list[dict[str, str]], str]:
    """List a channel's newest videos.

    RSS is preferred while the caller only wants the 15 newest uploads because it is a
    single cheap request. Deeper requests skip straight to the browse listing, which is
    the only source that pages past that cap.
    """
    errors: list[str] = []
    wants_deep_listing = limit is None or limit > RSS_FEED_DEPTH

    if not wants_deep_listing:
        try:
            entries = fetch_channel_rss_entries(channel_url)
            videos = [
                {
                    "videoId": entry["video_id"],
                    "title": entry.get("title", ""),
                    "url": entry.get("url") or youtube_watch_url(entry["video_id"]) or "",
                    "published_text": "",
                }
                for entry in entries
            ]
            if videos:
                return videos[:limit], "rss"
        except Exception as exc:
            errors.append(f"RSS lookup failed: {exc}")

    try:
        videos, source = _channel_page_candidates(channel_url, limit)
        if videos:
            return videos, source
    except Exception as exc:
        errors.append(f"channel page lookup failed: {exc}")

    try:
        videos, source = _scrapetube_candidates(channel_url, limit)
        if videos:
            return videos, source
    except Exception as exc:
        errors.append(str(exc))

    # Deep listing failed; the 15 newest are better than nothing.
    if wants_deep_listing:
        try:
            entries = fetch_channel_rss_entries(channel_url)
            videos = [
                {
                    "videoId": entry["video_id"],
                    "title": entry.get("title", ""),
                    "url": entry.get("url") or youtube_watch_url(entry["video_id"]) or "",
                    "published_text": "",
                }
                for entry in entries
            ]
            if videos:
                return videos, "rss:fallback"
        except Exception as exc:
            errors.append(f"RSS fallback failed: {exc}")

    if errors:
        raise ValueError("; ".join(errors))
    return [], "none"


def plan_channel_fetch(
    channel_url: str,
    limit: int | None = None,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """List a channel's recent titles and mark which ones the archive already holds."""
    videos, listing_source = fetch_channel_video_candidates(channel_url, limit=limit)
    saved_ids = saved_video_ids()

    candidates = []
    for video in videos:
        video_id = video["videoId"]
        already_saved = video_id in saved_ids
        candidates.append({
            "video_id": video_id,
            "title": video.get("title") or video_id,
            "url": video.get("url") or youtube_watch_url(video_id),
            "published_text": video.get("published_text", ""),
            "already_saved": already_saved,
            "selected": not (already_saved and skip_existing),
        })

    new_count = sum(1 for c in candidates if not c["already_saved"])
    return {
        "channel": channel_url,
        "listing_source": listing_source,
        "total": len(candidates),
        "new_count": new_count,
        "already_saved_count": len(candidates) - new_count,
        "candidates": candidates,
    }


def watcher_due(settings: dict[str, Any]) -> bool:
    if not settings.get("enabled") or not settings.get("channels"):
        return False

    # Scheduled work must never be the thing that re-trips an active block.
    if reliability_store.get_cooldown()["active"]:
        return False

    next_check = _parse_iso_utc(settings.get("next_check_at"))
    if next_check is None:
        return True
    return datetime.now(next_check.tzinfo).replace(microsecond=0) >= next_check


def watcher_worker_loop():
    while not watcher_stop_event.is_set():
        settings = reliability_store.get_settings()
        system_settings = load_system_settings(SYSTEM_SETTINGS_PATH)
        worker_paused = system_settings.get("ingestion_paused") or system_settings.get("maintenance_mode")
        if not worker_paused and watcher_due(settings) and task_status.get("current_task") is None:
            try:
                background_watcher_refresh(scheduled=True)
            except Exception as exc:
                logger.exception("Scheduled watcher refresh failed")
                record_event("error", "watcher_refresh_failed", str(exc), {})
        watcher_stop_event.wait(30)


@app.on_event("startup")
def start_watcher_worker():
    global watcher_thread
    if watcher_thread and watcher_thread.is_alive():
        return
    watcher_stop_event.clear()
    watcher_thread = threading.Thread(target=watcher_worker_loop, name="channel-watcher", daemon=True)
    watcher_thread.start()


@app.on_event("shutdown")
def stop_watcher_worker():
    watcher_stop_event.set()

@app.get("/")
def root():
    return {"status": "YouTube Transcript Pro API is running"}

# --- Routes continue ---

class FetchRequest(BaseModel):
    url: str


class ChannelFetchRequest(BaseModel):
    url: str
    # How deep to walk the channel listing. Above 15 this leaves RSS behind.
    limit: Optional[int] = DEFAULT_CHANNEL_FETCH_LIMIT
    skip_existing: bool = True
    # Explicit picks from the preview screen; overrides listing order when set.
    video_ids: Optional[List[str]] = None


class ChannelPreviewRequest(BaseModel):
    url: str
    limit: Optional[int] = DEFAULT_CHANNEL_FETCH_LIMIT
    skip_existing: bool = True


class RetryFailedRequest(BaseModel):
    run_id: str


class WatcherSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    channels: Optional[List[str]] = None
    frequency_minutes: Optional[int] = None
    languages: Optional[List[str]] = None

class TranscriptEntry(BaseModel):
    video_id: str
    title: str
    channel: str
    saved_at: str
    uploaded_at: Optional[str] = None
    fetched_at: Optional[str] = None
    source_url: Optional[str] = None
    transcript: str
    segments: List[dict]


class TagsRequest(BaseModel):
    tags: List[str]


class VideoNoteRequest(BaseModel):
    note: str = ""


class TimestampNoteRequest(BaseModel):
    start: float
    text: str


class CollectionRequest(BaseModel):
    name: str
    description: str = ""


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ClipRequest(BaseModel):
    video_id: str
    start: float
    end: Optional[float] = None
    text: str = ""
    note: str = ""


class CollectionsImportRequest(BaseModel):
    collections: List[dict]
    replace: bool = False


class AISettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    summary_model: Optional[str] = None
    embedding_model: Optional[str] = None
    timeout_seconds: Optional[int] = None
    temperature: Optional[float] = None
    prompt_version: Optional[str] = None


class AICompareRequest(BaseModel):
    video_ids: List[str]


class AITimelineRequest(BaseModel):
    video_ids: Optional[List[str]] = None
    channel: Optional[str] = None


class EmbeddingsRebuildRequest(BaseModel):
    video_ids: Optional[List[str]] = None
    segments_per_chunk: Optional[int] = None
    segment_overlap: Optional[int] = None


class MCPSettingsRequest(BaseModel):
    enabled: Optional[bool] = None


class SystemSettingsRequest(BaseModel):
    ingestion_paused: Optional[bool] = None
    maintenance_mode: Optional[bool] = None


class DataExportRequest(BaseModel):
    scope: str = "all"
    format: str = "json"
    channel: Optional[str] = None
    video_ids: Optional[List[str]] = None
    collection_id: Optional[str] = None
    query: Optional[str] = None
    include_segments: bool = True


def transcript_summaries() -> list[dict[str, Any]]:
    reader = getattr(store, "list_summaries", None)
    if callable(reader):
        return reader()
    return store.all_entries()


@app.get("/api/transcripts")
def get_transcripts():
    """List rows only. Fetch /api/transcripts/{video_id} for a transcript body."""
    return list(reversed(transcript_summaries()))

@app.get("/api/stats")
def get_stats():
    return library_stats(store.all_entries())

@app.get("/api/search")
def search_transcripts(
    q: str,
    channel: Optional[str] = None,
    limit: int = 50,
    sort: str = "relevance",
):
    store_search = getattr(store, "search_entries", None)
    if callable(store_search):
        return store_search(
            query=q,
            channel=channel,
            limit=limit,
            sort=sort,
        )

    return search_entries(
        store.all_entries(),
        query=q,
        channel=channel,
        limit=limit,
        sort=sort,
    )

@app.get("/api/storage/status")
def get_storage_status():
    return _storage_status()

@app.post("/api/storage/migrate")
def migrate_storage_to_sqlite():
    global store

    json_path = TRANSCRIPTS_JSON_PATH
    sqlite_path = TRANSCRIPTS_SQLITE_PATH

    if isinstance(store, SQLiteTranscriptStore):
        return {
            "status": "already_active",
            "message": "SQLite storage is already active; the JSON archive was not imported.",
            "storage": _storage_status(),
        }

    if not json_path.exists() and not isinstance(store, SQLiteTranscriptStore):
        raise HTTPException(status_code=404, detail="No JSON transcript store found")

    try:
        if json_path.exists():
            sqlite_store = migrate_json_to_sqlite(json_path, sqlite_path)
        else:
            sqlite_store = SQLiteTranscriptStore(sqlite_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store = sqlite_store
    status = _storage_status()
    return {
        "status": "success",
        "message": "SQLite storage is active",
        "storage": status,
    }

@app.post("/api/storage/normalize-channels")
def normalize_storage_channels():
    """One-off cleanup for archives written before channel names were normalised."""
    normalizer = getattr(store, "normalize_channel_names", None)
    if not callable(normalizer):
        raise HTTPException(status_code=400, detail="Active storage backend cannot normalize channels")

    try:
        result = normalizer()
    except Exception as exc:
        logger.exception("Channel normalization failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    message = f"Renamed {result['renamed']} channels and merged {result['merged']} duplicates."
    record_event("info", "channels_normalized", message, result)
    return {"status": "success", "message": message, **result}


@app.post("/api/storage/export-json")
def export_storage_json():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = EXPORTS_DIR / f"transcripts_export_{timestamp}.json"

    try:
        written_path = export_entries_to_json(store.all_entries(), export_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "success",
        "path": str(written_path.resolve()),
        "count": len(store.all_entries()),
    }


@app.post("/api/data/export")
def export_data_dump(request: DataExportRequest):
    entries = _transcript_export_entries(request)
    export_path, media_type = _write_data_export(entries, request)
    record_event("info", "data_export_created", "Created transcript data export", {
        "path": str(export_path.resolve()),
        "count": len(entries),
        "scope": request.scope,
        "format": request.format,
    })
    return FileResponse(
        path=export_path,
        media_type=media_type,
        filename=export_path.name,
    )


@app.get("/api/data/tables")
def list_data_tables():
    tables = []
    for table in DATA_TABLES:
        rows = _build_data_table_rows(table)
        tables.append({
            "name": table,
            "count": len(rows),
            "columns": _data_table_columns(table),
        })
    return {
        "storage": _storage_status(),
        "tables": tables,
    }


@app.get("/api/data/tables/{table_name}")
def get_data_table(table_name: str, limit: int = 50, offset: int = 0, q: str = ""):
    return _data_table_rows(table_name, limit=limit, offset=offset, q=q)


@app.get("/api/mcp/status")
def get_mcp_status():
    return _mcp_status()


@app.put("/api/mcp/settings")
def update_mcp_status(request: MCPSettingsRequest):
    settings = update_mcp_settings(request_payload(request), MCP_SETTINGS_PATH)
    record_event("success", "mcp_settings_updated", "Updated MCP settings", {
        "enabled": settings["enabled"],
    })
    return _mcp_status()


@app.get("/api/system/status")
def get_system_status():
    return _system_status()


@app.put("/api/system/settings")
def update_system_status(request: SystemSettingsRequest):
    settings = update_system_settings(request_payload(request), SYSTEM_SETTINGS_PATH)
    record_event("success", "system_settings_updated", "Updated system controls", settings)
    return _system_status()


@app.post("/api/system/cancel-task")
def request_task_cancel():
    if not task_status.get("current_task"):
        raise HTTPException(status_code=404, detail="No active task to cancel")
    task_cancel_event.set()
    update_task_status(message="Cancel requested. Waiting for the worker to stop...")
    record_event("warning", "task_cancel_requested", "Cancel requested for active task", {
        "run_id": task_status.get("run_id"),
        "current_task": task_status.get("current_task"),
    })
    return {"status": "cancel_requested", "task": dict(task_status)}


@app.get("/api/events")
def get_backend_events(after: int = 0, limit: int = 100):
    bounded_limit = max(1, min(limit, BACKEND_EVENTS_LIMIT))
    events = [
        event
        for event in backend_events
        if int(event.get("id", 0)) > after
    ][-bounded_limit:]
    return {
        "events": events,
        "latest_id": backend_event_id,
    }


@app.get("/api/fetch/runs")
def get_fetch_runs(limit: int = 25):
    return {"runs": reliability_store.list_runs(limit=limit)}


@app.get("/api/fetch/cooldown")
def get_fetch_cooldown():
    cooldown = reliability_store.get_cooldown()
    return {
        **cooldown,
        "wait_label": _format_cooldown_wait(cooldown["remaining_seconds"]),
    }


@app.post("/api/fetch/cooldown/clear")
def clear_fetch_cooldown():
    """Deliberate override for when the wait is longer than the real block."""
    previous = reliability_store.get_cooldown()
    cooldown = reliability_store.clear_cooldown()
    if previous["active"]:
        record_event("info", "ingestion_cooldown_cleared", "Rate-limit cooldown cleared manually", {
            "skipped_seconds": previous["remaining_seconds"],
            "strikes": previous["strikes"],
        })
    return {
        "status": "success",
        **cooldown,
        "wait_label": _format_cooldown_wait(cooldown["remaining_seconds"]),
    }


@app.get("/api/fetch/runs/{run_id}")
def get_fetch_run(run_id: str):
    run = reliability_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Fetch run not found")
    return run


@app.post("/api/fetch/retry-failed")
def retry_failed_fetches(request: RetryFailedRequest, background_tasks: BackgroundTasks):
    _ensure_ingestion_allowed()
    retry_items = reliability_store.retry_items(request.run_id)
    if not retry_items:
        raise HTTPException(status_code=404, detail="No retryable failures found for this run")

    run_id = queue_task("retry", f"Retrying {len(retry_items)} failed videos...", total=len(retry_items))
    background_tasks.add_task(background_retry_failed_fetches, request.run_id, retry_items, run_id)
    return {"status": "started", "run_id": run_id, "source_run_id": request.run_id, "retry_count": len(retry_items)}


@app.get("/api/watcher/settings")
def get_watcher_settings():
    return reliability_store.get_settings()


@app.put("/api/watcher/settings")
def update_watcher_settings(request: WatcherSettingsRequest):
    payload = (
        request.model_dump(exclude_unset=True)
        if hasattr(request, "model_dump")
        else request.dict(exclude_unset=True)
    )
    settings = reliability_store.update_settings(payload)
    record_event("success", "watcher_settings_updated", "Updated watcher settings", {
        "enabled": settings["enabled"],
        "channel_count": len(settings["channels"]),
        "frequency_minutes": settings["frequency_minutes"],
        "languages": settings["languages"],
    })
    return settings


@app.post("/api/watcher/run-now")
def run_watcher_now(background_tasks: BackgroundTasks):
    _ensure_ingestion_allowed()
    settings = reliability_store.get_settings()
    if not settings.get("channels"):
        raise HTTPException(status_code=400, detail="Add at least one watcher channel first")

    run_id = queue_task("watcher", "Watcher refresh queued...", total=0)
    background_tasks.add_task(background_watcher_refresh, False, run_id)
    return {"status": "started", "run_id": run_id, "channel_count": len(settings["channels"])}


@app.get("/api/ai/settings")
def get_ai_settings():
    return ai_settings_store.get_settings()


@app.put("/api/ai/settings")
def update_ai_settings(request: AISettingsRequest):
    try:
        settings = ai_settings_store.update_settings(request_payload(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_event("success", "ai_settings_updated", "Updated AI settings", {
        "enabled": settings["enabled"],
        "provider": settings["provider"],
        "summary_model": settings["summary_model"],
        "embedding_model": settings["embedding_model"],
    })
    return settings


@app.get("/api/ai/models")
def get_ai_models():
    settings = ai_settings_store.get_settings()
    client = ollama_client_for_settings(settings)
    started = perf_counter()
    health = client.health(timeout_seconds=min(settings["timeout_seconds"], 10))
    latency_ms = round((perf_counter() - started) * 1000, 2)
    if not health.get("ok"):
        return {
            "ok": False,
            "provider": settings["provider"],
            "base_url": settings["base_url"],
            "models": [],
            "summary_models": [],
            "embedding_models": [],
            "message": health.get("error") or "Ollama is not reachable",
            "latency_ms": latency_ms,
        }

    names = model_names(health.get("models") or [])
    return {
        "ok": True,
        "provider": settings["provider"],
        "base_url": settings["base_url"],
        "models": health.get("models") or [],
        "summary_models": generation_model_names(names),
        "embedding_models": embedding_model_names(names),
        "latency_ms": latency_ms,
    }


@app.post("/api/ai/health")
def check_ai_health(request: AISettingsRequest | None = None):
    payload = request_payload(request) if request is not None else {}
    try:
        settings = ai_settings_store.get_settings()
        if payload:
            settings = {**settings, **payload}
        client = ollama_client_for_settings(settings)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    started = perf_counter()
    health = client.health(timeout_seconds=min(int(settings.get("timeout_seconds") or 10), 10))
    latency_ms = round((perf_counter() - started) * 1000, 2)
    return {
        "ok": bool(health.get("ok")),
        "status": "ok" if health.get("ok") else "error",
        "message": "Ollama connection is healthy" if health.get("ok") else health.get("error", "Ollama is not reachable"),
        "provider": settings.get("provider"),
        "model": settings.get("summary_model"),
        "base_url": settings.get("base_url"),
        "latency_ms": latency_ms,
        "model_count": len(health.get("models") or []),
    }


@app.get("/api/ai/artifacts")
def get_ai_artifacts(limit: int = 50):
    bounded = bounded_limit(limit, default=50, maximum=200)
    summaries = ai_artifact_store.list_video_summaries()
    artifacts = [
        {
            **summary,
            "kind": "summary",
            "title": transcript_lookup().get(summary.get("video_id"), {}).get("title", ""),
        }
        for summary in summaries
    ]
    artifacts.extend({**item, "kind": "comparison"} for item in ai_artifact_store.list_comparisons(limit=bounded))
    artifacts.extend({**item, "kind": "timeline"} for item in ai_artifact_store.list_timelines(limit=bounded))
    artifacts.extend({**item, "kind": "run"} for item in ai_artifact_store.list_generic_runs(limit=bounded))
    artifacts.sort(key=lambda item: item.get("generated_at") or "")
    return {
        "artifacts": artifacts[-bounded:],
        "total": len(artifacts),
    }


@app.get("/api/ai/transcripts/{video_id}/summary")
def get_ai_transcript_summary(video_id: str):
    transcript = require_transcript(video_id)
    current_hash = transcript_hash(transcript)
    artifact = ai_artifact_store.latest_video_summary(video_id, current_hash)
    stale = False
    if artifact is None:
        artifact = ai_artifact_store.latest_video_summary(video_id)
        stale = artifact is not None
    if artifact is None:
        raise HTTPException(status_code=404, detail="No AI summary saved for this transcript")
    return {"summary": summary_artifact_payload(artifact, video_id, stale=stale)}


@app.post("/api/ai/transcripts/{video_id}/summary")
def generate_ai_transcript_summary(video_id: str):
    settings = ai_settings_or_400()
    transcript = require_transcript(video_id)
    run_id = queue_task("ai_summary", "Generating AI summary...", total=1)
    client = ollama_client_for_settings(settings)
    try:
        result = client.generate_json(
            build_summary_prompt(transcript),
            model=settings["summary_model"],
            temperature=settings["temperature"],
            timeout_seconds=settings["timeout_seconds"],
        )
        content = result["json"]
        artifact = ai_artifact_store.save_video_summary(
            video_id,
            content,
            transcript=transcript,
            provider=settings["provider"],
            model=result.get("model") or settings["summary_model"],
            prompt_version=settings["prompt_version"],
            metadata={"run_id": run_id},
        )
        update_task_status(progress=1, success_count=1, message="AI summary generated")
        record_event("success", "ai_summary_generated", "Generated AI transcript summary", {
            "run_id": run_id,
            "video_id": video_id,
            "model": artifact["model"],
        })
        finish_task("AI summary generated")
        return {"summary": summary_artifact_payload(artifact, video_id)}
    except (OllamaClientError, ValueError) as exc:
        ai_artifact_store.save_video_summary(
            video_id,
            {},
            transcript=transcript,
            provider=settings["provider"],
            model=settings["summary_model"],
            prompt_version=settings["prompt_version"],
            status="failed",
            error=str(exc),
            metadata={"run_id": run_id},
        )
        update_task_status(failure_count=1, message=f"AI summary failed: {exc}")
        finish_task(f"AI summary failed: {exc}", level="error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/ai/compare")
def compare_ai_transcripts(request: AICompareRequest):
    settings = ai_settings_or_400()
    video_ids = list(dict.fromkeys(str(video_id).strip() for video_id in request.video_ids if str(video_id).strip()))
    if len(video_ids) < 2:
        raise HTTPException(status_code=400, detail="Select at least two transcripts to compare")
    lookup = transcript_lookup()
    entries = []
    missing = []
    for video_id in video_ids[:8]:
        entry = lookup.get(video_id)
        if entry:
            entries.append(entry)
        else:
            missing.append(video_id)
    if missing:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {missing[0]}")

    client = ollama_client_for_settings(settings)
    try:
        result = client.generate_json(
            build_compare_prompt(entries),
            model=settings["summary_model"],
            temperature=settings["temperature"],
            timeout_seconds=settings["timeout_seconds"],
        )
    except OllamaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    artifact = ai_artifact_store.save_comparison(
        video_ids,
        result["json"],
        provider=settings["provider"],
        model=result.get("model") or settings["summary_model"],
        prompt_version=settings["prompt_version"],
    )
    return {"comparison": artifact}


@app.post("/api/ai/timeline")
def build_ai_timeline(request: AITimelineRequest):
    settings = ai_settings_or_400()
    requested_ids = [str(video_id).strip() for video_id in request.video_ids or [] if str(video_id).strip()]
    entries = store.all_entries()
    if requested_ids:
        id_set = set(requested_ids)
        entries = [entry for entry in entries if entry.get("video_id") in id_set]
    elif request.channel:
        channel = request.channel.strip().lower()
        entries = [entry for entry in entries if str(entry.get("channel") or "").lower() == channel]

    entries = entries[:20]
    if not entries:
        raise HTTPException(status_code=404, detail="No transcripts found for timeline")

    client = ollama_client_for_settings(settings)
    try:
        result = client.generate_json(
            build_timeline_prompt(entries),
            model=settings["summary_model"],
            temperature=settings["temperature"],
            timeout_seconds=settings["timeout_seconds"],
        )
    except OllamaClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    artifact = ai_artifact_store.save_timeline(
        result["json"],
        video_ids=[entry.get("video_id", "") for entry in entries],
        provider=settings["provider"],
        model=result.get("model") or settings["summary_model"],
        prompt_version=settings["prompt_version"],
    )
    return {"timeline": artifact}


@app.get("/api/ai/embeddings/status")
def get_embeddings_status():
    settings = ai_settings_store.get_settings()
    index = load_semantic_index(str(SEMANTIC_INDEX_PATH))
    items = index.get("items") or []
    stale_ids = stale_transcript_ids(
        store.all_entries(),
        index=index,
        embedding_model=settings.get("embedding_model"),
    )
    return {
        "exists": bool(items),
        "path": str(SEMANTIC_INDEX_PATH.resolve()),
        "embedding_model": index.get("embedding_model") or settings.get("embedding_model"),
        "chunk_count": len(items),
        "stale_count": len(stale_ids),
        "stale_video_ids": stale_ids[:50],
    }


@app.post("/api/ai/embeddings/rebuild")
def rebuild_ai_embeddings(request: EmbeddingsRebuildRequest):
    settings = ai_settings_or_400()
    entries = store.all_entries()
    requested_ids = [str(video_id).strip() for video_id in request.video_ids or [] if str(video_id).strip()]
    if requested_ids:
        id_set = set(requested_ids)
        entries = [entry for entry in entries if entry.get("video_id") in id_set]
    if not entries:
        raise HTTPException(status_code=404, detail="No transcripts found to index")

    run_id = queue_task("ai_embeddings", "Rebuilding semantic index...", total=len(entries))
    client = ollama_client_for_settings(settings)

    embedded_count = 0

    def embed_text(text: str):
        nonlocal embedded_count
        if _task_cancel_requested():
            raise RuntimeError("Task canceled")
        response = client.embed(text, model=settings["embedding_model"], timeout_seconds=settings["timeout_seconds"])
        embedded_count += 1
        update_task_status(progress=min(embedded_count, len(entries)), message=f"Embedded {embedded_count} chunks")
        embeddings = response["embeddings"]
        if not embeddings:
            raise ValueError("Ollama returned no embeddings")
        return embeddings[0]

    try:
        index = rebuild_semantic_index(
            entries,
            embed_text,
            path=str(SEMANTIC_INDEX_PATH),
            embedding_model=settings["embedding_model"],
            segments_per_chunk=max(1, int(request.segments_per_chunk or 8)),
            segment_overlap=max(0, int(request.segment_overlap or 0)),
        )
        update_task_status(success_count=len(entries), message="Semantic index rebuilt")
        finish_task("Semantic index rebuilt")
        return {
            "status": "success",
            "path": str(SEMANTIC_INDEX_PATH.resolve()),
            "embedding_model": index.get("embedding_model"),
            "chunk_count": len(index.get("items") or []),
            "video_count": len(entries),
        }
    except RuntimeError as exc:
        if str(exc) == "Task canceled":
            _finish_canceled_task(run_id)
            raise HTTPException(status_code=409, detail="Task canceled") from exc
        raise
    except (OllamaClientError, ValueError) as exc:
        update_task_status(failure_count=1, message=f"Semantic index rebuild failed: {exc}")
        finish_task(f"Semantic index rebuild failed: {exc}", level="error")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/semantic-search")
def semantic_search(q: str, limit: int = 10):
    query = q.strip()
    if len(query) < 2:
        return {"results": [], "message": "Search query is too short"}

    settings = ai_settings_store.get_settings()
    index = load_semantic_index(str(SEMANTIC_INDEX_PATH))
    if not index.get("items"):
        return {
            "results": [],
            "message": "Semantic index has not been built",
            "index": get_embeddings_status(),
        }
    if not settings.get("enabled"):
        return {
            "results": [],
            "message": "AI is disabled in Settings",
            "index": get_embeddings_status(),
        }

    client = ollama_client_for_settings(settings)
    try:
        response = client.embed(query, model=settings["embedding_model"], timeout_seconds=settings["timeout_seconds"])
        embeddings = response["embeddings"]
        if not embeddings:
            raise OllamaClientError("Ollama returned no query embedding")
        results = semantic_index_store.search(
            embeddings[0],
            limit=bounded_limit(limit, default=10, maximum=50),
            embedding_model=settings["embedding_model"],
        )
    except (OllamaClientError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "results": [
            {
                **result,
                "semantic_score": result.get("score", 0),
                "matches": [{
                    "text": result.get("text", ""),
                    "start": result.get("start", 0),
                    "duration": max(0, float(result.get("end", 0) or 0) - float(result.get("start", 0) or 0)),
                }],
            }
            for result in results
        ],
        "embedding_model": settings["embedding_model"],
        "query": query,
    }


@app.get("/api/research")
def get_research_organization():
    return organization_store.snapshot()


@app.put("/api/transcripts/{video_id}/tags")
def update_transcript_tags(video_id: str, request: TagsRequest):
    require_transcript(video_id)
    tags = organization_store.set_tags(video_id, request.tags)
    record_event("success", "tags_updated", f"Updated tags for {video_id}", {
        "video_id": video_id,
        "tags": tags,
    })
    return {"video_id": video_id, "tags": tags}


@app.put("/api/transcripts/{video_id}/note")
def update_video_note(video_id: str, request: VideoNoteRequest):
    require_transcript(video_id)
    note = organization_store.set_video_note(video_id, request.note)
    record_event("success", "video_note_updated", f"Updated video note for {video_id}", {
        "video_id": video_id,
        "characters": len(note),
    })
    return {"video_id": video_id, "note": note}


@app.post("/api/transcripts/{video_id}/timestamp-notes")
def add_timestamp_note(video_id: str, request: TimestampNoteRequest):
    require_transcript(video_id)
    try:
        note = organization_store.add_timestamp_note(video_id, request.start, request.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_event("success", "timestamp_note_added", f"Added timestamp note for {video_id}", {
        "video_id": video_id,
        "start": note["start"],
    })
    return note


@app.delete("/api/transcripts/{video_id}/timestamp-notes/{note_id}")
def delete_timestamp_note(video_id: str, note_id: str):
    if not organization_store.delete_timestamp_note(video_id, note_id):
        raise HTTPException(status_code=404, detail="Timestamp note not found")

    record_event("success", "timestamp_note_deleted", f"Deleted timestamp note for {video_id}", {
        "video_id": video_id,
        "note_id": note_id,
    })
    return {"status": "success"}


@app.post("/api/collections")
def create_collection(request: CollectionRequest):
    try:
        collection = organization_store.create_collection(request.name, request.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_event("success", "collection_created", f"Created collection: {collection['name']}", {
        "collection_id": collection["id"],
    })
    return collection


@app.put("/api/collections/{collection_id}")
def update_collection(collection_id: str, request: CollectionUpdateRequest):
    try:
        collection = organization_store.update_collection(
            collection_id,
            name=request.name,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    record_event("success", "collection_updated", f"Updated collection: {collection['name']}", {
        "collection_id": collection_id,
    })
    return collection


@app.delete("/api/collections/{collection_id}")
def delete_collection(collection_id: str):
    if not organization_store.delete_collection(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")

    record_event("success", "collection_deleted", "Deleted collection", {
        "collection_id": collection_id,
    })
    return {"status": "success"}


@app.post("/api/collections/{collection_id}/clips")
def add_collection_clip(collection_id: str, request: ClipRequest):
    transcript = require_transcript(request.video_id)
    clip_text = request.text or _segment_text_at(transcript, request.start)
    clip = organization_store.add_clip(
        collection_id,
        request.video_id,
        request.start,
        request.end,
        clip_text,
        request.note,
    )
    if clip is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    record_event("success", "clip_added", f"Saved clip to collection", {
        "collection_id": collection_id,
        "video_id": request.video_id,
        "start": clip["start"],
    })
    return clip


@app.delete("/api/collections/{collection_id}/clips/{clip_id}")
def delete_collection_clip(collection_id: str, clip_id: str):
    if not organization_store.delete_clip(collection_id, clip_id):
        raise HTTPException(status_code=404, detail="Clip not found")

    record_event("success", "clip_deleted", "Deleted collection clip", {
        "collection_id": collection_id,
        "clip_id": clip_id,
    })
    return {"status": "success"}


@app.get("/api/collections/{collection_id}/markdown", response_class=PlainTextResponse)
def export_collection_markdown(collection_id: str):
    markdown = organization_store.collection_markdown(collection_id, transcript_lookup())
    if markdown is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    record_event("info", "collection_markdown_exported", "Exported collection markdown", {
        "collection_id": collection_id,
    })
    return markdown


@app.get("/api/collections/export")
def export_collections_json():
    exported = organization_store.export_collections()
    record_event("info", "collections_json_exported", "Exported collections JSON", {
        "collection_count": len(exported["collections"]),
    })
    return exported


@app.post("/api/collections/import")
def import_collections_json(request: CollectionsImportRequest):
    imported_count = organization_store.import_collections(request.collections, replace=request.replace)
    record_event("success", "collections_imported", f"Imported {imported_count} collections", {
        "collection_count": imported_count,
        "replace": request.replace,
    })
    return {
        "status": "success",
        "imported_count": imported_count,
        "organization": organization_store.snapshot(),
    }

@app.get("/api/transcripts/{video_id}")
def get_transcript(video_id: str):
    entries = store.all_entries()
    for entry in entries:
        if entry['video_id'] == video_id:
            return entry
    raise HTTPException(status_code=404, detail="Transcript not found")

@app.delete("/api/transcripts/{video_id}")
def delete_transcript(video_id: str):
    if video_id not in transcript_lookup():
        raise HTTPException(status_code=404, detail="Transcript not found")
    store.delete_entry(video_id)
    return {"status": "success"}

def background_video_fetch(url: str, run_id: str | None = None):
    global task_status
    run_id = begin_task("video", "Fetching video details...", total=1, run_id=run_id)
    reliability_store.start_run("video", url, total=1, run_id=run_id)
    try:
        v_id = extract_video_id(url)
        if not v_id:
            raise ValueError("Invalid URL")

        update_task_status(message=f"Fetching transcript for {v_id}...")
        record_event("info", "video_fetch_started", "Fetching video transcript", {
            "run_id": run_id,
            "video_id": v_id,
            "url": url,
        })

        if _task_cancel_requested():
            _finish_canceled_task(run_id)
            return

        entry = _fetch_and_save_video(v_id, run_id=run_id, index=1, total=1, url=url)
        update_task_status(
            progress=1,
            success_count=1,
            message=f"Successfully saved: {entry['title']}",
        )
        record_event("success", "video_saved", f"Saved transcript: {entry['title']}", {
            "run_id": run_id,
            "video_id": v_id,
            "title": entry.get("title"),
            "segments": len(entry.get("segments") or []),
        })
        reliability_store.finish_run(run_id, message=f"Successfully saved: {entry['title']}")
        finish_task(f"Successfully saved: {entry['title']}")
    except Exception as e:
        logger.exception("Video fetch failed")
        update_task_status(failure_count=1, message=f"Error: {str(e)}")
        _record_fetch_failure(run_id, e, url=url)
        reliability_store.finish_run(run_id, message=f"Error: {str(e)}")
        record_event("error", "video_fetch_failed", str(e), {
            "run_id": run_id,
            "url": url,
        })
        finish_task(f"Error: {str(e)}", level="error")

@app.post("/api/fetch/video")
def fetch_video(request: FetchRequest, background_tasks: BackgroundTasks):
    _ensure_ingestion_allowed()
    run_id = queue_task("video", "Video fetch queued...", total=1)
    background_tasks.add_task(background_video_fetch, request.url, run_id)
    return {"status": "started", "run_id": run_id}

def background_channel_fetch(
    url: str,
    run_id: str | None = None,
    limit: int | None = DEFAULT_CHANNEL_FETCH_LIMIT,
    skip_existing: bool = True,
    video_ids: list[str] | None = None,
):
    global task_status
    run_id = begin_task("channel", "Finding videos in channel...", run_id=run_id)
    reliability_store.start_run("channel", url, total=0, run_id=run_id)
    try:
        videos, listing_source = fetch_channel_video_candidates(url, limit=limit)
        listed_count = len(videos)

        # An explicit selection (from the preview screen) wins over the listing order.
        if video_ids:
            wanted = set(video_ids)
            known = {v["videoId"] for v in videos}
            videos = [v for v in videos if v["videoId"] in wanted]
            for missing_id in video_ids:
                if missing_id not in known:
                    videos.append({
                        "videoId": missing_id,
                        "title": "",
                        "url": youtube_watch_url(missing_id) or "",
                    })

        already_saved_count = 0
        if skip_existing:
            existing_ids = saved_video_ids()
            kept = [v for v in videos if v["videoId"] not in existing_ids]
            already_saved_count = len(videos) - len(kept)
            videos = kept

        total = len(videos)
        summary = (
            f"Found {listed_count} videos via {listing_source}; "
            f"{already_saved_count} already archived, fetching {total}"
        )
        update_task_status(total=total, progress=0, message=summary)
        reliability_store.set_total(run_id, total)
        record_event("info", "channel_videos_found", summary, {
            "run_id": run_id,
            "url": url,
            "listed": listed_count,
            "already_saved": already_saved_count,
            "total": total,
            "source": listing_source,
            "limit": limit,
        })

        if listed_count == 0:
            raise ValueError("No videos found")

        if total == 0:
            message = f"Channel already up to date. All {already_saved_count} listed videos are archived."
            finish_task(message)
            reliability_store.finish_run(run_id, message=message)
            return

        # Create a export folder for this bulk run
        folder = CHANNELS_DIR / f"Bulk_Export_{int(time.time())}"
        os.makedirs(folder, exist_ok=True)

        rate_limit_streak = 0
        stopped_early = 0

        for i, v in enumerate(videos, 1):
            if _task_cancel_requested():
                _finish_canceled_task(run_id)
                return

            v_id = v['videoId']
            update_task_status(progress=i, message=f"Processing video {i}/{total}: {v_id}")
            source_url = v.get("url") or youtube_watch_url(v_id)

            # Check if exists in folder already (though we use time-stamped folders now)

            try:
                time.sleep(random.uniform(1, 3)) # politeness
                entry = _fetch_and_save_video(v_id, run_id=run_id, index=i, total=total, url=source_url)
                rate_limit_streak = 0

                # Save to individual JSON
                with open(os.path.join(folder, f"{v_id}.json"), "w", encoding="utf-8") as f:
                    json.dump(entry, f, indent=2, ensure_ascii=False)

                update_task_status(success_count=task_status["success_count"] + 1)
                record_event("success", "channel_video_saved", f"Saved {i}/{total}: {entry['title']}", {
                    "run_id": run_id,
                    "video_id": v_id,
                    "title": entry.get("title"),
                    "index": i,
                    "total": total,
                })
            except Exception as exc:
                logger.exception("Channel video fetch failed")
                update_task_status(
                    failure_count=task_status["failure_count"] + 1,
                    skipped_count=task_status["skipped_count"] + 1,
                )
                _record_fetch_failure(run_id, exc, video_id=v_id, url=source_url, title=v.get("title", ""), index=i, total=total)
                reliability_store.record_skipped(
                    run_id,
                    video_id=v_id,
                    url=source_url,
                    title=v.get("title", ""),
                    reason=str(exc),
                    index=i,
                    total=total,
                )
                record_event("warning", "channel_video_failed", f"Skipped {v_id}: {exc}", {
                    "run_id": run_id,
                    "video_id": v_id,
                    "index": i,
                    "total": total,
                    "error": str(exc),
                })

                if _is_rate_limited(exc):
                    rate_limit_streak += 1
                    if not _rate_limit_pause(rate_limit_streak, run_id):
                        # Leave the rest unfetched so the next run picks them up as new.
                        stopped_early = total - i
                        break
                else:
                    rate_limit_streak = 0
                continue

        if _task_cancel_requested():
            # Cancelling out of a backoff is a human decision, not a block. Parking
            # ingestion here would punish the user for stopping their own run.
            _finish_canceled_task(run_id)
            return

        if stopped_early:
            cooldown = _begin_rate_limit_cooldown(
                run_id, f"Channel fetch stopped early with {stopped_early} videos left"
            )
            message = (
                f"Stopped early: YouTube is rate limiting. "
                f"Saved {task_status['success_count']}; "
                f"{stopped_early} left for a later run; "
                f"already archived {already_saved_count}. "
                f"Ingestion paused for {_format_cooldown_wait(cooldown['remaining_seconds'])}."
            )
        else:
            reliability_store.record_clean_run()
            message = (
                "Bulk fetch finished. "
                f"Saved {task_status['success_count']} of {total} new; "
                f"failed {task_status['skipped_count']}; "
                f"already archived {already_saved_count}."
            )
        finish_task(message)
        reliability_store.finish_run(run_id, message=message)
    except Exception as e:
        logger.exception("Channel fetch failed")
        update_task_status(message=f"Error: {str(e)}", failure_count=task_status["failure_count"] + 1)
        _record_fetch_failure(run_id, e, url=url)
        reliability_store.finish_run(run_id, message=f"Error: {str(e)}")
        record_event("error", "channel_fetch_failed", str(e), {
            "run_id": run_id,
            "url": url,
        })
        finish_task(f"Error: {str(e)}", level="error")

def _channel_fetch_limit(value: int | None) -> int | None:
    """None means 'walk the whole channel'; anything else is clamped to a sane range."""
    if value is None or value <= 0:
        return None
    return min(int(value), MAX_CHANNEL_FETCH_LIMIT)


@app.post("/api/fetch/channel/preview")
def preview_channel(request: ChannelPreviewRequest):
    """List recent channel titles and flag which are already in the archive."""
    try:
        return plan_channel_fetch(
            request.url,
            limit=_channel_fetch_limit(request.limit),
            skip_existing=request.skip_existing,
        )
    except Exception as exc:
        logger.exception("Channel preview failed")
        record_event("warning", "channel_preview_failed", str(exc), {"url": request.url})
        raise HTTPException(status_code=502, detail=f"Could not list channel videos: {exc}")


@app.post("/api/fetch/channel")
def fetch_channel(request: ChannelFetchRequest, background_tasks: BackgroundTasks):
    _ensure_ingestion_allowed()
    run_id = queue_task("channel", "Channel fetch queued...", total=0)
    background_tasks.add_task(
        background_channel_fetch,
        request.url,
        run_id,
        _channel_fetch_limit(request.limit),
        request.skip_existing,
        request.video_ids,
    )
    return {"status": "started", "run_id": run_id}


def background_retry_failed_fetches(source_run_id: str, retry_items: list[dict[str, Any]], run_id: str | None = None):
    run_id = begin_task("retry", f"Retrying {len(retry_items)} failed videos...", total=len(retry_items), run_id=run_id)
    reliability_store.start_run(
        "retry",
        f"retry:{source_run_id}",
        total=len(retry_items),
        run_id=run_id,
        metadata={"source_run_id": source_run_id},
    )
    for index, item in enumerate(retry_items, 1):
        if _task_cancel_requested():
            _finish_canceled_task(run_id)
            return

        video_id = item.get("video_id") or extract_video_id(str(item.get("url") or ""))
        url = item.get("url") or youtube_watch_url(video_id)
        if not video_id:
            update_task_status(
                progress=index,
                failure_count=task_status["failure_count"] + 1,
                skipped_count=task_status["skipped_count"] + 1,
                message=f"Retry skipped {index}/{len(retry_items)}: missing video id",
            )
            _record_fetch_failure(run_id, "Missing video id", url=url, index=index, total=len(retry_items))
            reliability_store.record_skipped(
                run_id,
                url=url,
                reason="Missing video id",
                index=index,
                total=len(retry_items),
            )
            continue

        try:
            update_task_status(progress=index, message=f"Retrying {index}/{len(retry_items)}: {video_id}")
            entry = _fetch_and_save_video(video_id, run_id=run_id, index=index, total=len(retry_items), url=url)
            update_task_status(success_count=task_status["success_count"] + 1)
            record_event("success", "retry_video_saved", f"Retry saved: {entry['title']}", {
                "run_id": run_id,
                "source_run_id": source_run_id,
                "video_id": video_id,
            })
        except Exception as exc:
            logger.exception("Retry fetch failed")
            update_task_status(
                failure_count=task_status["failure_count"] + 1,
                skipped_count=task_status["skipped_count"] + 1,
            )
            _record_fetch_failure(run_id, exc, video_id=video_id, url=url, index=index, total=len(retry_items))
            reliability_store.record_skipped(
                run_id,
                video_id=video_id,
                url=url,
                reason=str(exc),
                index=index,
                total=len(retry_items),
            )
            record_event("warning", "retry_video_failed", f"Retry failed {video_id}: {exc}", {
                "run_id": run_id,
                "source_run_id": source_run_id,
                "video_id": video_id,
                "error": str(exc),
            })

    message = (
        "Retry run finished. "
        f"Saved {task_status['success_count']} of {len(retry_items)}; "
        f"skipped {task_status['skipped_count']}."
    )
    reliability_store.finish_run(run_id, message=message)
    finish_task(message, level="warning" if task_status["failure_count"] else "success")


def background_watcher_refresh(scheduled: bool = False, run_id: str | None = None):
    settings = reliability_store.get_settings()
    channels = settings.get("channels") or []
    languages = settings.get("languages") or ["en"]
    run_type = "watcher"
    source = "scheduled" if scheduled else "manual"
    run_id = begin_task(run_type, "Checking watcher RSS feeds...", total=0, run_id=run_id)
    reliability_store.start_run(run_type, source, total=0, run_id=run_id, metadata={"scheduled": scheduled})

    try:
        candidates: list[dict[str, str]] = []
        for channel in channels:
            if _task_cancel_requested():
                _finish_canceled_task(run_id)
                return

            try:
                entries = fetch_channel_rss_entries(channel)
                for entry in entries:
                    candidates.append({**entry, "channel_source": channel})
            except Exception as exc:
                logger.exception("Watcher RSS fetch failed")
                _record_fetch_failure(run_id, exc, url=channel, title=channel)
                record_event("warning", "watcher_channel_failed", f"Watcher failed for {channel}: {exc}", {
                    "run_id": run_id,
                    "channel": channel,
                    "error": str(exc),
                })

        existing_video_ids = saved_video_ids()
        rate_limit_streak = 0
        watcher_stopped_early = 0
        total = len(candidates)
        reliability_store.set_total(run_id, total)
        update_task_status(total=total, progress=0, message=f"Watcher found {total} RSS videos")
        record_event("info", "watcher_videos_found", f"Watcher found {total} RSS videos", {
            "run_id": run_id,
            "channel_count": len(channels),
            "total": total,
        })

        for index, item in enumerate(candidates, 1):
            if _task_cancel_requested():
                _finish_canceled_task(run_id)
                return

            video_id = item["video_id"]
            url = item.get("url") or youtube_watch_url(video_id)
            title = item.get("title") or video_id
            if video_id in existing_video_ids:
                reliability_store.record_skipped(
                    run_id,
                    video_id=video_id,
                    url=url,
                    title=title,
                    reason="Already saved",
                    index=index,
                    total=total,
                )
                update_task_status(
                    progress=index,
                    skipped_count=task_status["skipped_count"] + 1,
                    message=f"Watcher skipped existing video {index}/{total}: {video_id}",
                )
                continue

            try:
                update_task_status(progress=index, message=f"Watcher fetching {index}/{total}: {video_id}")
                entry = _fetch_and_save_video(
                    video_id,
                    run_id=run_id,
                    index=index,
                    total=total,
                    url=url,
                    languages=languages,
                )
                existing_video_ids.add(video_id)
                update_task_status(success_count=task_status["success_count"] + 1)
                record_event("success", "watcher_video_saved", f"Watcher saved: {entry['title']}", {
                    "run_id": run_id,
                    "video_id": video_id,
                    "title": entry.get("title"),
                })
            except Exception as exc:
                logger.exception("Watcher video fetch failed")
                update_task_status(
                    failure_count=task_status["failure_count"] + 1,
                    skipped_count=task_status["skipped_count"] + 1,
                )
                _record_fetch_failure(run_id, exc, video_id=video_id, url=url, title=title, index=index, total=total)
                reliability_store.record_skipped(
                    run_id,
                    video_id=video_id,
                    url=url,
                    title=title,
                    reason=str(exc),
                    index=index,
                    total=total,
                )
                record_event("warning", "watcher_video_failed", f"Watcher skipped {video_id}: {exc}", {
                    "run_id": run_id,
                    "video_id": video_id,
                    "error": str(exc),
                })

                if _is_rate_limited(exc):
                    rate_limit_streak += 1
                    if not _rate_limit_pause(rate_limit_streak, run_id):
                        watcher_stopped_early = total - index
                        break
                else:
                    rate_limit_streak = 0

        if _task_cancel_requested():
            _finish_canceled_task(run_id)
            return

        next_check_at = _next_watcher_check_at(settings["frequency_minutes"]) if settings.get("enabled") else None
        reliability_store.mark_watcher_checked(next_check_at=next_check_at)
        if watcher_stopped_early:
            cooldown = _begin_rate_limit_cooldown(
                run_id, f"Watcher stopped early with {watcher_stopped_early} videos left"
            )
            message = (
                "Watcher stopped early: YouTube is rate limiting. "
                f"Saved {task_status['success_count']}; "
                f"{watcher_stopped_early} left for a later run. "
                f"Ingestion paused for {_format_cooldown_wait(cooldown['remaining_seconds'])}."
            )
            reliability_store.finish_run(run_id, message=message)
            finish_task(message, level="warning")
            return

        reliability_store.record_clean_run()
        message = (
            "Watcher refresh finished. "
            f"Saved {task_status['success_count']} of {total}; "
            f"skipped {task_status['skipped_count']}."
        )
        reliability_store.finish_run(run_id, message=message)
        finish_task(message, level="warning" if task_status["failure_count"] else "success")
    except Exception as exc:
        logger.exception("Watcher refresh failed")
        update_task_status(message=f"Error: {str(exc)}", failure_count=task_status["failure_count"] + 1)
        _record_fetch_failure(run_id, exc, url=source)
        reliability_store.finish_run(run_id, message=f"Error: {str(exc)}")
        finish_task(f"Error: {str(exc)}", level="error")

@app.get("/api/status")
def get_status():
    return task_status

# Middleware added last will execute first for requests
@app.middleware("http")
async def log_requests(request, call_next):
    started = perf_counter()
    path = request.url.path
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000, 2)
        record_event("error", "http_error", f"{request.method} {path} failed", {
            "method": request.method,
            "path": path,
            "duration_ms": duration_ms,
            "error": str(exc),
        })
        raise

    duration_ms = round((perf_counter() - started) * 1000, 2)
    if path not in {"/api/events", "/api/status"} and request.method != "OPTIONS":
        level = "error" if response.status_code >= 500 else "warning" if response.status_code >= 400 else "info"
        record_event(level, "http_request", f"{request.method} {path} -> {response.status_code}", {
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        })
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("YT_TRANSCRIPTS_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("YT_TRANSCRIPTS_HOST", "127.0.0.1"), port=8000)

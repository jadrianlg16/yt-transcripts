from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - only reached before requirements install.
    raise SystemExit(
        "Missing dependency: install Python requirements so the 'mcp' package is available."
    ) from exc

from core.organization import DEFAULT_ORGANIZATION_FILE, ResearchOrganizationStore
from core.research import library_stats, search_entries, words
from core.runtime_settings import load_mcp_settings
from core.store import DATA_FILE, SQLITE_DATA_FILE


DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
DEFAULT_TRANSCRIPT_CHARS = 5000
MAX_TRANSCRIPT_CHARS = 50000
DEFAULT_MATCH_CHARS = 1200
MAX_MATCH_CHARS = 5000
DEFAULT_MARKDOWN_CHARS = 20000
MAX_MARKDOWN_CHARS = 100000
DEFAULT_SEGMENT_LIMIT = 150
MAX_SEGMENT_LIMIT = 1000
DEFAULT_SEGMENT_CHARS = 500
MAX_SEGMENT_CHARS = 2000


def _looks_like_project_root(path: Path) -> bool:
    return (path / "requirements.txt").exists() and (path / "core").is_dir()


def _project_root() -> Path:
    for value in (
        os.getenv("YT_TRANSCRIPTS_PROJECT_ROOT"),
        os.getenv("CLAUDE_PROJECT_DIR"),
    ):
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if _looks_like_project_root(candidate):
            return candidate

    script_root = Path(__file__).resolve().parent
    if _looks_like_project_root(script_root):
        return script_root
    return Path.cwd().resolve()


PROJECT_ROOT = _project_root()
mcp = FastMCP("yt-transcripts-readonly")


def _mcp_disabled_response() -> dict[str, Any]:
    return {
        "available": False,
        "message": "MCP access is disabled in YouTube Transcript Pro settings.",
        "settings_path": str(_project_path("mcp_settings.json")),
    }


def _mcp_enabled() -> bool:
    return bool(load_mcp_settings(_project_path("mcp_settings.json")).get("enabled"))


def _project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _cap_text(text: Any, max_chars: int) -> dict[str, Any]:
    raw = str(text or "")
    limit = _bounded_int(max_chars, DEFAULT_TRANSCRIPT_CHARS, 0, MAX_MARKDOWN_CHARS)
    truncated = len(raw) > limit
    return {
        "text": raw[:limit],
        "char_count": len(raw),
        "truncated": truncated,
        "max_chars": limit,
    }


def _sqlite_uri(path: Path) -> str:
    normalized = path.resolve().as_posix()
    return f"file:{quote(normalized, safe='/:')}?mode=ro"


def _load_sqlite_entries(path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(_sqlite_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        video_rows = connection.execute(
            """
            SELECT
                videos.video_id,
                videos.title,
                channels.name AS channel,
                videos.saved_at,
                videos.transcript,
                videos.created_at,
                videos.updated_at
            FROM videos
            JOIN channels ON channels.id = videos.channel_id
            ORDER BY videos.sort_order ASC, videos.created_at ASC
            """
        ).fetchall()

        segments_by_video: dict[str, list[dict[str, Any]]] = {}
        video_ids = [str(row["video_id"]) for row in video_rows]
        for start in range(0, len(video_ids), 500):
            chunk = video_ids[start : start + 500]
            if not chunk:
                continue
            placeholders = ", ".join("?" for _ in chunk)
            segment_rows = connection.execute(
                f"""
                SELECT video_id, text, start, duration
                FROM segments
                WHERE video_id IN ({placeholders})
                ORDER BY video_id ASC, segment_index ASC
                """,
                chunk,
            ).fetchall()
            for row in segment_rows:
                segments_by_video.setdefault(str(row["video_id"]), []).append(
                    {
                        "text": row["text"],
                        "start": row["start"],
                        "duration": row["duration"],
                    }
                )

        return [
            {
                "video_id": row["video_id"],
                "title": row["title"],
                "channel": row["channel"],
                "saved_at": row["saved_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "transcript": row["transcript"],
                "segments": segments_by_video.get(str(row["video_id"]), []),
            }
            for row in video_rows
        ]
    finally:
        connection.close()


def _load_json_entries(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def _load_transcripts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sqlite_path = _project_path(SQLITE_DATA_FILE)
    json_path = _project_path(DATA_FILE)
    warnings: list[str] = []

    if sqlite_path.exists():
        try:
            return _load_sqlite_entries(sqlite_path), {
                "backend": "sqlite",
                "path": str(sqlite_path),
                "warnings": warnings,
            }
        except (OSError, sqlite3.Error) as exc:
            warnings.append(f"SQLite read failed: {exc}")

    if json_path.exists():
        try:
            return _load_json_entries(json_path), {
                "backend": "json",
                "path": str(json_path),
                "warnings": warnings,
            }
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"JSON read failed: {exc}")

    return [], {
        "backend": "missing",
        "path": "",
        "warnings": warnings,
    }


def _entry_by_video_id(entries: list[dict[str, Any]], video_id: str) -> dict[str, Any] | None:
    return next((entry for entry in entries if str(entry.get("video_id") or "") == video_id), None)


def _transcript_lookup(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("video_id")): entry
        for entry in entries
        if entry.get("video_id")
    }


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    transcript = str(entry.get("transcript") or "")
    segments = entry.get("segments") or []
    duration = 0.0
    for segment in segments if isinstance(segments, list) else []:
        if not isinstance(segment, dict):
            continue
        try:
            segment_end = float(segment.get("start") or 0) + float(segment.get("duration") or 0)
        except (TypeError, ValueError):
            segment_end = 0.0
        duration = max(duration, segment_end)

    return {
        "video_id": entry.get("video_id", ""),
        "title": entry.get("title") or "Untitled Video",
        "channel": entry.get("channel") or "Unknown Channel",
        "saved_at": entry.get("saved_at") or "",
        "uploaded_at": entry.get("uploaded_at") or entry.get("saved_at") or "",
        "fetched_at": entry.get("fetched_at") or "",
        "source_url": entry.get("source_url") or "",
        "word_count": len(words(transcript)),
        "segment_count": len(segments) if isinstance(segments, list) else 0,
        "duration_seconds": round(duration, 2),
        "transcript_char_count": len(transcript),
    }


def _capped_segments(
    entry: dict[str, Any],
    max_segments: int,
    max_segment_text_chars: int,
) -> dict[str, Any]:
    segments = entry.get("segments") or []
    if not isinstance(segments, list):
        return {
            "segments": [],
            "segment_count": 0,
            "returned_segments": 0,
            "segments_truncated": False,
        }

    segment_limit = _bounded_int(max_segments, DEFAULT_SEGMENT_LIMIT, 0, MAX_SEGMENT_LIMIT)
    text_limit = _bounded_int(
        max_segment_text_chars,
        DEFAULT_SEGMENT_CHARS,
        0,
        MAX_SEGMENT_CHARS,
    )
    returned = []
    for segment in segments[:segment_limit]:
        if not isinstance(segment, dict):
            continue
        text = _cap_text(segment.get("text") or "", text_limit)
        returned.append(
            {
                "text": text["text"],
                "text_char_count": text["char_count"],
                "text_truncated": text["truncated"],
                "start": float(segment.get("start") or 0),
                "duration": float(segment.get("duration") or 0),
            }
        )

    return {
        "segments": returned,
        "segment_count": len(segments),
        "returned_segments": len(returned),
        "segments_truncated": len(segments) > segment_limit,
    }


def _organization_store() -> ResearchOrganizationStore:
    return ResearchOrganizationStore(_project_path(DEFAULT_ORGANIZATION_FILE))


def _cap_match_text(results: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    text_limit = _bounded_int(max_chars, DEFAULT_MATCH_CHARS, 0, MAX_MATCH_CHARS)
    capped_results = []
    for result in results:
        item = dict(result)
        matches = []
        for match in result.get("matches") or []:
            if not isinstance(match, dict):
                continue
            capped = _cap_text(match.get("text") or "", text_limit)
            match_item = dict(match)
            match_item["text"] = capped["text"]
            match_item["text_char_count"] = capped["char_count"]
            match_item["text_truncated"] = capped["truncated"]
            matches.append(match_item)
        item["matches"] = matches
        capped_results.append(item)
    return capped_results


@mcp.tool()
def list_transcripts(
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    channel: str | None = None,
    include_preview: bool = False,
    max_preview_chars: int = 300,
) -> dict[str, Any]:
    """List saved transcript summaries from the local archive without transcript bodies by default."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    channel_filter = (channel or "").strip().lower()
    filtered = [
        entry
        for entry in entries
        if not channel_filter
        or str(entry.get("channel") or "Unknown Channel").lower() == channel_filter
    ]
    ordered = list(reversed(filtered))
    start = _bounded_int(offset, 0, 0, max(len(ordered), 0))
    bounded_limit = _bounded_int(limit, DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT)

    items = []
    for entry in ordered[start : start + bounded_limit]:
        summary = _entry_summary(entry)
        if include_preview:
            capped = _cap_text(entry.get("transcript") or "", max_preview_chars)
            summary["preview"] = capped["text"]
            summary["preview_truncated"] = capped["truncated"]
        items.append(summary)

    return {
        "items": items,
        "count": len(items),
        "total": len(filtered),
        "offset": start,
        "limit": bounded_limit,
        "storage": storage,
    }


@mcp.tool()
def search_transcripts(
    query: str,
    channel: str | None = None,
    limit: int = 10,
    sort: str = "relevance",
    matches_per_entry: int = 4,
    max_match_chars: int = DEFAULT_MATCH_CHARS,
) -> dict[str, Any]:
    """Search transcript titles and text with the app's local lexical ranking."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    bounded_limit = _bounded_int(limit, 10, 1, 100)
    bounded_matches = _bounded_int(matches_per_entry, 4, 0, 10)
    results = search_entries(
        entries,
        query=query,
        channel=channel,
        limit=bounded_limit,
        matches_per_entry=bounded_matches,
        sort=sort,
    )
    return {
        "query": query,
        "results": _cap_match_text(results, max_match_chars),
        "count": len(results),
        "storage": storage,
    }


@mcp.tool()
def get_transcript(
    video_id: str,
    max_text_chars: int = DEFAULT_TRANSCRIPT_CHARS,
    include_segments: bool = False,
    max_segments: int = DEFAULT_SEGMENT_LIMIT,
    max_segment_text_chars: int = DEFAULT_SEGMENT_CHARS,
) -> dict[str, Any]:
    """Get one transcript by video_id, capping the transcript body by default."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    entry = _entry_by_video_id(entries, video_id)
    if entry is None:
        return {
            "found": False,
            "video_id": video_id,
            "message": "Transcript not found",
            "storage": storage,
        }

    capped = _cap_text(entry.get("transcript") or "", max_text_chars)
    response = {
        "found": True,
        **_entry_summary(entry),
        "transcript": capped["text"],
        "transcript_truncated": capped["truncated"],
        "transcript_char_count": capped["char_count"],
        "max_text_chars": capped["max_chars"],
        "storage": storage,
    }
    if include_segments:
        response.update(_capped_segments(entry, max_segments, max_segment_text_chars))
    return response


@mcp.tool()
def get_library_stats() -> dict[str, Any]:
    """Return aggregate stats for the saved transcript library."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    return {
        "stats": library_stats(entries),
        "storage": storage,
    }


@mcp.tool()
def list_collections(include_clips: bool = True, limit: int = 100) -> dict[str, Any]:
    """List research collections from the local organization store."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    snapshot = _organization_store().snapshot()
    collections = snapshot.get("collections", [])
    bounded_limit = _bounded_int(limit, 100, 1, 500)

    items = []
    for collection in collections[:bounded_limit]:
        clips = collection.get("clips", []) if isinstance(collection, dict) else []
        item = {
            "id": collection.get("id", ""),
            "name": collection.get("name", ""),
            "description": collection.get("description", ""),
            "created_at": collection.get("created_at", ""),
            "updated_at": collection.get("updated_at", ""),
            "clip_count": len(clips) if isinstance(clips, list) else 0,
        }
        if include_clips:
            item["clips"] = clips if isinstance(clips, list) else []
        items.append(item)

    return {
        "items": items,
        "count": len(items),
        "total": len(collections) if isinstance(collections, list) else 0,
        "path": str(_project_path(DEFAULT_ORGANIZATION_FILE)),
    }


@mcp.tool()
def get_collection_markdown(
    collection_id: str,
    max_chars: int = DEFAULT_MARKDOWN_CHARS,
) -> dict[str, Any]:
    """Export one collection as Markdown without writing files."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    markdown = _organization_store().collection_markdown(
        collection_id,
        _transcript_lookup(entries),
    )
    if markdown is None:
        return {
            "found": False,
            "collection_id": collection_id,
            "message": "Collection not found",
            "storage": storage,
        }

    bounded = _bounded_int(max_chars, DEFAULT_MARKDOWN_CHARS, 0, MAX_MARKDOWN_CHARS)
    capped = _cap_text(markdown, bounded)
    return {
        "found": True,
        "collection_id": collection_id,
        "markdown": capped["text"],
        "markdown_char_count": capped["char_count"],
        "markdown_truncated": capped["truncated"],
        "max_chars": bounded,
        "storage": storage,
    }


def _semantic_index_path() -> Path:
    return _project_path(os.getenv("SEMANTIC_INDEX_FILE", "semantic_index.json"))


def _semantic_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []

    for key in ("items", "entries", "chunks", "documents", "records", "vectors"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested = raw.get("index")
    if isinstance(nested, (dict, list)):
        return _semantic_records(nested)
    return []


def _record_text(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    text_parts = []
    for source in (record, metadata):
        for key in ("title", "channel", "text", "content", "chunk", "snippet", "transcript", "summary"):
            value = source.get(key)
            if value:
                text_parts.append(str(value))
    return "\n".join(text_parts)


def _record_identity(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source = {**metadata, **record}
    return {
        "video_id": source.get("video_id") or source.get("id") or "",
        "title": source.get("title") or "",
        "channel": source.get("channel") or "",
        "start": source.get("start"),
        "end": source.get("end"),
    }


def _rank_semantic_records(
    records: list[dict[str, Any]],
    query: str,
    limit: int,
    max_text_chars: int,
) -> list[dict[str, Any]]:
    phrase = " ".join((query or "").lower().split())
    terms = [term for term in words(phrase) if len(term) > 1]
    if not phrase or not terms:
        return []

    ranked = []
    for record in records:
        text = _record_text(record)
        normalized = text.lower()
        phrase_hits = normalized.count(phrase)
        term_hits = sum(normalized.count(term) for term in terms)
        score = phrase_hits * 5 + term_hits
        if score <= 0:
            continue
        capped = _cap_text(text, max_text_chars)
        ranked.append(
            {
                **_record_identity(record),
                "score": score,
                "text": capped["text"],
                "text_char_count": capped["char_count"],
                "text_truncated": capped["truncated"],
            }
        )

    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]


@mcp.tool()
def semantic_search(
    query: str,
    limit: int = 10,
    max_text_chars: int = DEFAULT_MATCH_CHARS,
) -> dict[str, Any]:
    """Search semantic_index.json when present; report clearly when the index has not been built."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    path = _semantic_index_path()
    if not path.exists():
        return {
            "available": False,
            "query": query,
            "index_path": str(path),
            "message": "semantic_index.json is missing. Build the local semantic index before using semantic search.",
            "results": [],
        }

    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "query": query,
            "index_path": str(path),
            "message": f"semantic_index.json could not be read: {exc}",
            "results": [],
        }

    records = _semantic_records(raw)
    if not records:
        return {
            "available": True,
            "query": query,
            "index_path": str(path),
            "message": "semantic_index.json was found, but it did not contain searchable records.",
            "results": [],
        }

    bounded_limit = _bounded_int(limit, 10, 1, 100)
    results = _rank_semantic_records(records, query, bounded_limit, max_text_chars)
    return {
        "available": True,
        "query": query,
        "index_path": str(path),
        "method": "semantic_index_text_rank",
        "results": results,
        "count": len(results),
        "record_count": len(records),
        "message": (
            "Read semantic_index.json without rebuilding embeddings. "
            "Results are ranked from searchable index text fields."
        ),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

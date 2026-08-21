from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - only reached before requirements install.
    raise SystemExit(
        "Missing dependency: install Python requirements so the 'mcp' package is available."
    ) from exc

from core.organization import DEFAULT_ORGANIZATION_FILE, ResearchOrganizationStore
from core.ai_clients import OllamaClientError, ollama_client_from_settings
from core.ai_settings import DEFAULT_AI_SETTINGS_FILE, AISettingsStore
from core.research import library_stats, search_entries, words
from core.runtime_settings import load_mcp_settings
from core.semantic_search import load_semantic_index, search_semantic_items
from core.store import DATA_FILE, SQLITE_DATA_FILE, normalize_entry_display_fields


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
DEFAULT_STANDARD_SEARCH_LIMIT = 10
MAX_STANDARD_SEARCH_LIMIT = 25
DEFAULT_PASSAGE_LIMIT = 12
MAX_PASSAGE_LIMIT = 50
DEFAULT_PASSAGES_PER_VIDEO = 3
# Caption segments are ~4s of speech and break mid-sentence, so a readable passage
# is a run of them. 16 lands around 60 seconds and 600 characters.
DEFAULT_PASSAGE_WINDOW = 16
MAX_PASSAGE_WINDOW = 60
RRF_RANK_CONSTANT = 60
# Rough enough to let a caller see what a response costs before spending it.
CHARS_PER_TOKEN_ESTIMATE = 4


class SearchResult(BaseModel):
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    results: list[SearchResult]


class FetchOutput(BaseModel):
    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


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


def _mcp_port() -> int:
    try:
        port = int(os.getenv("YT_TRANSCRIPTS_MCP_PORT", "8001"))
    except ValueError:
        port = 8001
    return max(1, min(port, 65535))


mcp = FastMCP(
    "yt-transcripts-readonly",
    instructions=(
        "Read-only access to a local YouTube transcript archive. "
        "Call search with a natural-language query, then call fetch with a returned id "
        "to read the complete transcript and its source URL."
    ),
    host=os.getenv("YT_TRANSCRIPTS_MCP_HOST", "127.0.0.1"),
    port=_mcp_port(),
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
)


def _mcp_disabled_response() -> dict[str, Any]:
    return {
        "available": False,
        "message": "MCP access is disabled in YouTube Transcript Pro settings.",
        "settings_path": str(_data_path("mcp_settings.json")),
    }


def _mcp_enabled() -> bool:
    return bool(load_mcp_settings(_data_path("mcp_settings.json")).get("enabled"))


def _require_mcp_enabled() -> None:
    if not _mcp_enabled():
        raise PermissionError("MCP access is disabled in YouTube Transcript Pro settings.")


def _project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _data_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate

    configured = os.getenv("YT_TRANSCRIPTS_DATA_DIR", "").strip()
    if not configured:
        return _project_path(candidate)

    data_root = Path(configured).expanduser()
    if not data_root.is_absolute():
        data_root = PROJECT_ROOT / data_root
    return data_root / candidate


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
            normalize_entry_display_fields({
                "video_id": row["video_id"],
                "title": row["title"],
                "channel": row["channel"],
                "saved_at": row["saved_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "transcript": row["transcript"],
                "segments": segments_by_video.get(str(row["video_id"]), []),
            })
            for row in video_rows
        ]
    finally:
        connection.close()


def _load_json_entries(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return (
        [normalize_entry_display_fields(entry) for entry in data if isinstance(entry, dict)]
        if isinstance(data, list)
        else []
    )


# Every tool call used to re-read the whole archive from disk. The archive only
# changes when the backend saves a transcript, so a cache keyed on the file's
# modification time and size stays correct and skips the reload.
_ARCHIVE_CACHE: dict[str, Any] = {"key": None, "entries": None, "storage": None}
_STATS_CACHE: dict[str, Any] = {"key": None, "value": None}


def _archive_cache_key() -> tuple[Any, ...] | None:
    for path in (_data_path(SQLITE_DATA_FILE), _data_path(DATA_FILE)):
        try:
            stat = path.stat()
        except OSError:
            continue
        return (str(path), stat.st_mtime_ns, stat.st_size)
    return None


def _load_transcripts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    key = _archive_cache_key()
    if key is not None and _ARCHIVE_CACHE["key"] == key:
        return _ARCHIVE_CACHE["entries"], _ARCHIVE_CACHE["storage"]

    entries, storage = _read_transcripts()
    if key is not None:
        _ARCHIVE_CACHE.update({"key": key, "entries": entries, "storage": storage})
    return entries, storage


def _read_transcripts() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sqlite_path = _data_path(SQLITE_DATA_FILE)
    json_path = _data_path(DATA_FILE)
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


def _canonical_video_url(entry: dict[str, Any]) -> str:
    source_url = str(entry.get("source_url") or "").strip()
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return source_url

    video_id = quote(str(entry.get("video_id") or "").strip(), safe="")
    return f"https://www.youtube.com/watch?v={video_id}"


def _timecode(seconds: Any) -> str:
    """Seconds to h:mm:ss / m:ss, so a passage reads like a citation."""
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _passage_url(entry: dict[str, Any], start: Any) -> str:
    """Deep link that opens the video at the moment the passage was spoken."""
    base = _canonical_video_url(entry)
    try:
        offset = max(0, int(float(start or 0)))
    except (TypeError, ValueError):
        offset = 0
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}t={offset}s"


def _window_score(text: str, terms: list[str], phrase: str) -> float:
    """Rank a window by coverage first, then density.

    Deliberately not the all-terms-or-nothing rule the document matcher uses: a
    caption window is only a few seconds of speech, so demanding every query term
    inside one window returns nothing for any realistic multi-word question.
    """
    normalized = (text or "").lower()
    if not normalized:
        return 0.0

    matched_terms = [term for term in terms if term in normalized]
    if not matched_terms and phrase not in normalized:
        return 0.0

    coverage = len(matched_terms) / len(terms) if terms else 0.0
    density = sum(normalized.count(term) for term in matched_terms)
    return coverage * 10 + density + (5 if phrase and phrase in normalized else 0)


def _passage_windows(
    entry: dict[str, Any],
    terms: list[str],
    phrase: str,
    max_per_video: int,
    text_limit: int,
    window_segments: int,
) -> list[dict[str, Any]]:
    """Best-scoring, non-overlapping caption windows for one video.

    Individual caption segments run about four seconds and break mid-sentence, so a
    passage is a run of consecutive segments joined back into readable speech.
    """
    segments = [s for s in (entry.get("segments") or []) if isinstance(s, dict)]
    if not segments:
        return []

    summary = _entry_summary(entry)
    stride = max(1, window_segments // 2)
    scored: list[tuple[float, int, str]] = []
    for start_index in range(0, len(segments), stride):
        window = segments[start_index : start_index + window_segments]
        if not window:
            break
        text = " ".join(str(s.get("text") or "").strip() for s in window).strip()
        score = _window_score(text, terms, phrase)
        if score > 0:
            scored.append((score, start_index, text))

    scored.sort(key=lambda item: (-item[0], item[1]))

    passages: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for score, start_index, text in scored:
        span = set(range(start_index, start_index + window_segments))
        if span & claimed:
            continue
        claimed |= span

        capped = _cap_text(text, text_limit)
        start = segments[start_index].get("start", 0)
        passages.append(
            {
                "video_id": summary["video_id"],
                "title": summary["title"],
                "channel": summary["channel"],
                "uploaded_at": summary["uploaded_at"],
                # Verbatim transcript, never a model summary. Callers should be able
                # to tell ground truth from inference without asking.
                "content_type": "verbatim_transcript",
                "text": capped["text"],
                "text_char_count": capped["char_count"],
                "text_truncated": capped["truncated"],
                "start": float(start or 0),
                "start_timecode": _timecode(start),
                "url": _passage_url(entry, start),
                "passage_score": round(score, 3),
            }
        )
        if len(passages) >= max_per_video:
            break

    return passages


def _sqlite_fts_candidate_ids(query: str, limit: int) -> tuple[list[str], bool]:
    path = _data_path(SQLITE_DATA_FILE)
    if not path.exists():
        return [], False

    terms = [term for term in words(query) if len(term) > 1]
    if not terms:
        return [], True

    fts_query = " ".join(f"{term}*" for term in terms)
    try:
        connection = sqlite3.connect(_sqlite_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT video_id
                FROM video_search_fts
                WHERE video_search_fts MATCH ?
                ORDER BY bm25(video_search_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return [], False

    return [str(row["video_id"]) for row in rows], True


def _passage_candidate_ids(query: str, limit: int) -> tuple[list[str], bool]:
    """Videos worth scanning for passages, ranked by bm25.

    Uses OR rather than the implicit AND of the document search. A question like
    "agent memory rag vector search" has no single video containing every term, so
    an AND candidate query hands the passage scorer almost nothing to work with.
    """
    path = _data_path(SQLITE_DATA_FILE)
    if not path.exists():
        return [], False

    terms = [term for term in words(query) if len(term) > 1]
    if not terms:
        return [], False

    fts_query = " OR ".join(f"{term}*" for term in terms)
    try:
        connection = sqlite3.connect(_sqlite_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT video_id
                FROM video_search_fts
                WHERE video_search_fts MATCH ?
                ORDER BY bm25(video_search_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return [], False

    return [str(row["video_id"]) for row in rows], True


def _semantic_video_results(
    query: str,
    allowed_video_ids: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = _semantic_index_path()
    diagnostics: dict[str, Any] = {
        "available": False,
        "used": False,
        "index_path": str(path),
        "reason": "Semantic index has not been built.",
    }

    try:
        index = load_semantic_index(str(path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        diagnostics["reason"] = f"Semantic index could not be read: {exc}"
        return [], diagnostics

    items = index.get("items") or []
    if not items:
        return [], diagnostics

    diagnostics["available"] = True
    settings = AISettingsStore(_data_path(DEFAULT_AI_SETTINGS_FILE)).get_settings()
    if not settings.get("enabled"):
        diagnostics["reason"] = "AI is disabled; lexical search remains available."
        return [], diagnostics

    try:
        client = ollama_client_from_settings(settings)
        response = client.embed(
            query,
            model=settings["embedding_model"],
            timeout_seconds=min(int(settings.get("timeout_seconds") or 10), 10),
        )
        embeddings = response.get("embeddings") or []
        if not embeddings:
            raise OllamaClientError("Ollama returned no query embedding")
        chunk_results = search_semantic_items(
            items,
            embeddings[0],
            limit=max(limit * 8, 40),
            embedding_model=settings["embedding_model"],
        )
    except (OllamaClientError, OSError, ValueError) as exc:
        diagnostics["reason"] = f"Semantic query unavailable: {exc}"
        return [], diagnostics

    video_results = []
    seen: set[str] = set()
    for result in chunk_results:
        video_id = str(result.get("video_id") or "")
        if not video_id or video_id not in allowed_video_ids or video_id in seen:
            continue
        seen.add(video_id)
        video_results.append(result)
        if len(video_results) >= limit:
            break

    diagnostics.update(
        {
            "used": True,
            "reason": "Combined lexical matches with Ollama vector similarity.",
            "embedding_model": settings["embedding_model"],
            "chunk_count": len(items),
        }
    )
    return video_results, diagnostics


def _hybrid_search_entries(
    entries: list[dict[str, Any]],
    query: str,
    limit: int,
    channel: str | None = None,
    matches_per_entry: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bounded_limit = _bounded_int(limit, 10, 1, 100)
    channel_filter = (channel or "").strip().lower()
    eligible_entries = [
        entry
        for entry in entries
        if not channel_filter
        or str(entry.get("channel") or "Unknown Channel").lower() == channel_filter
    ]
    entry_lookup = _transcript_lookup(eligible_entries)
    candidate_limit = min(max(bounded_limit * 5, 25), 200)
    fts_ids, fts_used = _sqlite_fts_candidate_ids(query, candidate_limit)
    lexical_candidates = (
        [entry_lookup[video_id] for video_id in fts_ids if video_id in entry_lookup]
        if fts_used
        else eligible_entries
    )
    lexical_results = search_entries(
        lexical_candidates,
        query=query,
        limit=candidate_limit,
        matches_per_entry=matches_per_entry,
        sort="relevance",
    )
    semantic_results, semantic = _semantic_video_results(
        query,
        set(entry_lookup),
        candidate_limit,
    )

    lexical_by_id = {
        str(result.get("video_id") or ""): (rank, result)
        for rank, result in enumerate(lexical_results, start=1)
        if result.get("video_id")
    }
    semantic_by_id = {
        str(result.get("video_id") or ""): (rank, result)
        for rank, result in enumerate(semantic_results, start=1)
        if result.get("video_id")
    }

    fused_results = []
    for video_id in set(lexical_by_id) | set(semantic_by_id):
        entry = entry_lookup.get(video_id)
        if entry is None:
            continue

        lexical_pair = lexical_by_id.get(video_id)
        semantic_pair = semantic_by_id.get(video_id)
        score = 0.0
        if lexical_pair:
            score += 1 / (RRF_RANK_CONSTANT + lexical_pair[0])
        if semantic_pair:
            score += 1 / (RRF_RANK_CONSTANT + semantic_pair[0])

        result = dict(lexical_pair[1]) if lexical_pair else _entry_summary(entry)
        semantic_match = semantic_pair[1] if semantic_pair else None
        if not lexical_pair and semantic_match:
            result["matches"] = [
                {
                    "text": semantic_match.get("text", ""),
                    "start": semantic_match.get("start", 0),
                    "duration": max(
                        0.0,
                        float(semantic_match.get("end", 0) or 0)
                        - float(semantic_match.get("start", 0) or 0),
                    ),
                }
            ]
            result["match_count"] = 1
        result.update(
            {
                "retrieval_score": score,
                "lexical_rank": lexical_pair[0] if lexical_pair else None,
                "semantic_rank": semantic_pair[0] if semantic_pair else None,
                "semantic_score": semantic_match.get("score") if semantic_match else None,
            }
        )
        fused_results.append(result)

    fused_results.sort(
        key=lambda result: (
            -float(result.get("retrieval_score") or 0),
            result.get("title") or "",
            result.get("video_id") or "",
        )
    )
    diagnostics = {
        "method": "hybrid_rrf" if semantic.get("used") else "lexical_fallback",
        "lexical_method": "sqlite_fts" if fts_used else "in_memory",
        "lexical_result_count": len(lexical_results),
        "semantic": semantic,
    }
    return fused_results[:bounded_limit], diagnostics


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
    return ResearchOrganizationStore(_data_path(DEFAULT_ORGANIZATION_FILE))


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


@mcp.tool(structured_output=True)
def search(query: str) -> SearchOutput:
    """Search the transcript archive and return canonical document references for fetch."""
    _require_mcp_enabled()
    entries, _storage = _load_transcripts()
    limit = _bounded_int(
        os.getenv("YT_TRANSCRIPTS_MCP_SEARCH_LIMIT"),
        DEFAULT_STANDARD_SEARCH_LIMIT,
        1,
        MAX_STANDARD_SEARCH_LIMIT,
    )
    results, _diagnostics = _hybrid_search_entries(entries, query, limit=limit)
    return SearchOutput(
        results=[
            SearchResult(
                id=str(result.get("video_id") or ""),
                title=str(result.get("title") or "Untitled Video"),
                url=_canonical_video_url(
                    _entry_by_video_id(entries, str(result.get("video_id") or "")) or result
                ),
            )
            for result in results
            if result.get("video_id")
        ]
    )


@mcp.tool(structured_output=True)
def fetch(id: str) -> FetchOutput:
    """Fetch the full transcript and metadata for an id returned by search.

    Returns a whole document, which is the right unit only once you already know
    this video is the subject. To find where something was said across the archive,
    use search_passages instead; it answers the same question for a fraction of the
    tokens.
    """
    _require_mcp_enabled()
    entries, storage = _load_transcripts()
    video_id = str(id or "").strip()
    entry = _entry_by_video_id(entries, video_id)
    if entry is None:
        raise ValueError(f"Transcript not found: {video_id}")

    summary = _entry_summary(entry)
    # Bounded so one unusually long transcript cannot blow up a caller's context
    # window. The default clears every transcript in a normal archive; it is a
    # guardrail, not a summarisation step.
    capped = _cap_text(
        entry.get("transcript") or "",
        _bounded_int(
            os.getenv("YT_TRANSCRIPTS_MCP_FETCH_CHARS"),
            MAX_TRANSCRIPT_CHARS,
            1000,
            MAX_MARKDOWN_CHARS,
        ),
    )
    return FetchOutput(
        id=video_id,
        title=str(summary["title"]),
        text=capped["text"],
        url=_canonical_video_url(entry),
        metadata={
            "source": "youtube_transcript",
            "content_type": "verbatim_transcript",
            "video_id": video_id,
            "channel": summary["channel"],
            "saved_at": summary["saved_at"],
            "uploaded_at": summary["uploaded_at"],
            "fetched_at": summary["fetched_at"],
            "word_count": summary["word_count"],
            "segment_count": summary["segment_count"],
            "duration_seconds": summary["duration_seconds"],
            "storage_backend": storage["backend"],
            "text_char_count": capped["char_count"],
            "text_truncated": capped["truncated"],
            "max_chars": capped["max_chars"],
            "estimated_tokens": len(capped["text"]) // CHARS_PER_TOKEN_ESTIMATE,
        },
    )


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
    """Search transcripts with hybrid lexical and vector ranking when embeddings are ready."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    bounded_limit = _bounded_int(limit, 10, 1, 100)
    bounded_matches = _bounded_int(matches_per_entry, 4, 0, 10)
    if (sort or "relevance").lower() == "relevance":
        results, retrieval = _hybrid_search_entries(
            entries,
            query=query,
            channel=channel,
            limit=bounded_limit,
            matches_per_entry=bounded_matches,
        )
    else:
        results = search_entries(
            entries,
            query=query,
            channel=channel,
            limit=bounded_limit,
            matches_per_entry=bounded_matches,
            sort=sort,
        )
        retrieval = {
            "method": "lexical_sorted",
            "lexical_result_count": len(results),
            "semantic": {"available": False, "used": False, "reason": "Non-relevance sort selected."},
        }
    return {
        "query": query,
        "results": _cap_match_text(results, max_match_chars),
        "count": len(results),
        "retrieval": retrieval,
        "storage": storage,
    }


@mcp.tool()
def search_passages(
    query: str,
    channel: str | None = None,
    limit: int = DEFAULT_PASSAGE_LIMIT,
    max_per_video: int = DEFAULT_PASSAGES_PER_VIDEO,
    max_text_chars: int = DEFAULT_MATCH_CHARS,
    window_segments: int = DEFAULT_PASSAGE_WINDOW,
) -> dict[str, Any]:
    """Find where something was said, returning quotable passages instead of documents.

    Each passage carries its video, timecode, and a link that opens the video at that
    moment, so an answer can cite the source without ever loading a full transcript.
    Results are spread across videos rather than stacking on the best-matching one.

    Prefer this over fetch for questions about the archive. Reach for fetch only when a
    single video is already established as the subject and the whole text is genuinely
    needed.
    """
    if not _mcp_enabled():
        return _mcp_disabled_response()

    entries, storage = _load_transcripts()
    bounded_limit = _bounded_int(limit, DEFAULT_PASSAGE_LIMIT, 1, MAX_PASSAGE_LIMIT)
    per_video = _bounded_int(max_per_video, DEFAULT_PASSAGES_PER_VIDEO, 1, 10)
    text_limit = _bounded_int(max_text_chars, DEFAULT_MATCH_CHARS, 0, MAX_MATCH_CHARS)
    window = _bounded_int(window_segments, DEFAULT_PASSAGE_WINDOW, 2, MAX_PASSAGE_WINDOW)

    phrase = " ".join((query or "").lower().split())
    terms = [term for term in words(phrase) if len(term) > 1]
    if not terms:
        return {
            "query": query,
            "passages": [],
            "count": 0,
            "videos_represented": 0,
            "estimated_tokens": 0,
            "retrieval": {"method": "none", "reason": "Query has no searchable terms."},
            "storage": storage,
        }

    channel_filter = (channel or "").strip().lower()
    eligible = [
        entry
        for entry in entries
        if not channel_filter
        or str(entry.get("channel") or "Unknown Channel").lower() == channel_filter
    ]
    entry_lookup = _transcript_lookup(eligible)

    candidate_ids, fts_used = _passage_candidate_ids(query, MAX_LIST_LIMIT)
    candidates = [entry_lookup[i] for i in candidate_ids if i in entry_lookup] if fts_used else []
    semantic_results, semantic = _semantic_video_results(query, set(entry_lookup), MAX_LIST_LIMIT)
    for result in semantic_results:
        entry = entry_lookup.get(str(result.get("video_id") or ""))
        if entry is not None and entry not in candidates:
            candidates.append(entry)
    if not candidates:
        candidates = eligible

    # Score every candidate, then rank passages against each other rather than
    # letting one strong video fill the whole budget.
    scored: list[dict[str, Any]] = []
    for entry in candidates:
        scored.extend(
            _passage_windows(
                entry,
                terms,
                phrase,
                max_per_video=per_video,
                text_limit=text_limit,
                window_segments=window,
            )
        )
    scored.sort(key=lambda passage: -float(passage.get("passage_score") or 0))

    passages: list[dict[str, Any]] = []
    per_video_counts: dict[str, int] = {}
    for passage in scored:
        video_id = str(passage.get("video_id") or "")
        if per_video_counts.get(video_id, 0) >= per_video:
            continue
        per_video_counts[video_id] = per_video_counts.get(video_id, 0) + 1
        passages.append(passage)
        if len(passages) >= bounded_limit:
            break

    returned_chars = sum(len(passage["text"]) for passage in passages)
    return {
        "query": query,
        "passages": passages,
        "count": len(passages),
        "videos_represented": len(per_video_counts),
        "estimated_tokens": returned_chars // CHARS_PER_TOKEN_ESTIMATE,
        "retrieval": {
            "method": "passage_windows",
            "candidate_source": "sqlite_fts_or" if fts_used else "full_scan",
            "candidates_scanned": len(candidates),
            "window_segments": window,
            "semantic": semantic,
        },
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
    # Counting words across every transcript is the slow part; reuse it while the
    # archive is unchanged.
    key = _archive_cache_key()
    if key is None or _STATS_CACHE["key"] != key:
        _STATS_CACHE.update({"key": key, "value": library_stats(entries)})
    return {
        "stats": _STATS_CACHE["value"],
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
        "path": str(_data_path(DEFAULT_ORGANIZATION_FILE)),
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
    configured = os.getenv("SEMANTIC_INDEX_FILE", "").strip()
    return _project_path(configured) if configured else _data_path("semantic_index.json")


@mcp.tool()
def semantic_search(
    query: str,
    limit: int = 10,
    max_text_chars: int = DEFAULT_MATCH_CHARS,
) -> dict[str, Any]:
    """Run hybrid retrieval, using real vector similarity when the local index is ready."""
    if not _mcp_enabled():
        return _mcp_disabled_response()

    bounded_limit = _bounded_int(limit, 10, 1, 100)
    entries, storage = _load_transcripts()
    results, retrieval = _hybrid_search_entries(
        entries,
        query,
        limit=bounded_limit,
        matches_per_entry=4,
    )
    return {
        "available": bool(entries),
        "query": query,
        "method": retrieval["method"],
        "results": _cap_match_text(results, max_text_chars),
        "count": len(results),
        "retrieval": retrieval,
        "storage": storage,
    }


if __name__ == "__main__":
    transport = os.getenv("YT_TRANSCRIPTS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise SystemExit(f"Unsupported MCP transport: {transport}")
    mcp.run(transport=transport)

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

DEFAULT_INDEX_PATH = "semantic_index.json"
DEFAULT_EMBEDDING_MODEL = "local"
DEFAULT_SEGMENTS_PER_CHUNK = 8
DEFAULT_SEGMENT_OVERLAP = 0
INDEX_VERSION = 1

Embedder = Callable[[str], Sequence[float]]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _entry_text(entry: dict[str, Any], key: str, default: str = "") -> str:
    return _clean_text(entry.get(key)) or default


def _coerce_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _normalized_segments(entry: dict[str, Any]) -> list[dict[str, Any]]:
    segments = entry.get("segments") or []
    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        normalized.append(
            {
                "text": _clean_text(segment.get("text")),
                "start": _coerce_float(segment.get("start")),
                "duration": max(0.0, _coerce_float(segment.get("duration"))),
            }
        )
    return normalized


def chunk_transcript(
    entry: dict[str, Any],
    segments_per_chunk: int = DEFAULT_SEGMENTS_PER_CHUNK,
    segment_overlap: int = DEFAULT_SEGMENT_OVERLAP,
) -> list[dict[str, Any]]:
    if segments_per_chunk < 1:
        raise ValueError("segments_per_chunk must be at least 1")
    if segment_overlap < 0 or segment_overlap >= segments_per_chunk:
        raise ValueError("segment_overlap must be between 0 and segments_per_chunk - 1")

    video_id = _entry_text(entry, "video_id")
    title = _entry_text(entry, "title", "Untitled Video")
    channel = _entry_text(entry, "channel", "Unknown Channel")
    segments = [segment for segment in _normalized_segments(entry) if segment["text"]]
    chunks: list[dict[str, Any]] = []

    if segments:
        step = segments_per_chunk - segment_overlap
        segment_index = 0
        chunk_index = 0

        while segment_index < len(segments):
            window = segments[segment_index : segment_index + segments_per_chunk]
            if not window:
                break

            text = _clean_text(" ".join(segment["text"] for segment in window))
            if text:
                start = window[0]["start"]
                end = max(segment["start"] + segment["duration"] for segment in window)
                chunks.append(
                    {
                        "video_id": video_id,
                        "title": title,
                        "channel": channel,
                        "start": start,
                        "end": end,
                        "text": text,
                        "chunk_index": chunk_index,
                    }
                )
                chunk_index += 1

            if segment_index + segments_per_chunk >= len(segments):
                break
            segment_index += step

        return chunks

    transcript = _entry_text(entry, "transcript")
    if not transcript:
        return []

    return [
        {
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "start": 0.0,
            "end": 0.0,
            "text": transcript,
            "chunk_index": 0,
        }
    ]


def compute_transcript_hash(entry: dict[str, Any]) -> str:
    payload = {
        "video_id": _entry_text(entry, "video_id"),
        "title": _entry_text(entry, "title"),
        "channel": _entry_text(entry, "channel"),
        "saved_at": _entry_text(entry, "saved_at"),
        "uploaded_at": _entry_text(entry, "uploaded_at"),
        "transcript": _entry_text(entry, "transcript"),
        "segments": _normalized_segments(entry),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_vector(vector: Sequence[float]) -> list[float]:
    if vector is None or isinstance(vector, (str, bytes)):
        raise ValueError("vector must be a non-empty numeric sequence")

    values = []
    for value in vector:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("vector must contain only numeric values") from exc
        if not math.isfinite(number):
            raise ValueError("vector must contain only finite numeric values")
        values.append(number)

    if not values:
        raise ValueError("vector must be a non-empty numeric sequence")
    return values


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_values = normalize_vector(left)
    right_values = normalize_vector(right)
    if len(left_values) != len(right_values):
        raise ValueError("vectors must have the same dimensions")

    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot_product = sum(left_value * right_value for left_value, right_value in zip(left_values, right_values))
    return dot_product / (left_norm * right_norm)


def build_semantic_index(
    entries: Iterable[dict[str, Any]],
    embedder: Embedder,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    segments_per_chunk: int = DEFAULT_SEGMENTS_PER_CHUNK,
    segment_overlap: int = DEFAULT_SEGMENT_OVERLAP,
    indexed_at: str | None = None,
) -> dict[str, Any]:
    if not callable(embedder):
        raise TypeError("embedder must be callable")

    model = _clean_text(embedding_model) or DEFAULT_EMBEDDING_MODEL
    timestamp = indexed_at or _utc_timestamp()
    items: list[dict[str, Any]] = []

    for entry in entries:
        entry_hash = compute_transcript_hash(entry)
        for chunk in chunk_transcript(entry, segments_per_chunk, segment_overlap):
            item = dict(chunk)
            item.update(
                {
                    "embedding_model": model,
                    "transcript_hash": entry_hash,
                    "vector": normalize_vector(embedder(chunk["text"])),
                    "indexed_at": timestamp,
                }
            )
            items.append(item)

    return {
        "version": INDEX_VERSION,
        "embedding_model": model,
        "chunking": {
            "segments_per_chunk": segments_per_chunk,
            "segment_overlap": segment_overlap,
        },
        "items": items,
    }


def empty_semantic_index(embedding_model: str = "") -> dict[str, Any]:
    return {
        "version": INDEX_VERSION,
        "embedding_model": _clean_text(embedding_model),
        "items": [],
    }


def load_semantic_index(path: str = DEFAULT_INDEX_PATH) -> dict[str, Any]:
    if not os.path.exists(path):
        return empty_semantic_index()

    with open(path, "r", encoding="utf-8") as file:
        loaded = json.load(file)

    if isinstance(loaded, list):
        return {
            "version": INDEX_VERSION,
            "embedding_model": "",
            "items": loaded,
        }
    if not isinstance(loaded, dict):
        raise ValueError("semantic index must be a JSON object")

    loaded.setdefault("version", INDEX_VERSION)
    loaded.setdefault("embedding_model", "")
    loaded.setdefault("items", [])
    if not isinstance(loaded["items"], list):
        raise ValueError("semantic index items must be a list")
    return loaded


def save_semantic_index(index: dict[str, Any], path: str = DEFAULT_INDEX_PATH) -> str:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(index, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temp_path, path)
    return path


def rebuild_semantic_index(
    entries: Iterable[dict[str, Any]],
    embedder: Embedder,
    path: str = DEFAULT_INDEX_PATH,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    segments_per_chunk: int = DEFAULT_SEGMENTS_PER_CHUNK,
    segment_overlap: int = DEFAULT_SEGMENT_OVERLAP,
    indexed_at: str | None = None,
) -> dict[str, Any]:
    index = build_semantic_index(
        entries,
        embedder,
        embedding_model=embedding_model,
        segments_per_chunk=segments_per_chunk,
        segment_overlap=segment_overlap,
        indexed_at=indexed_at,
    )
    save_semantic_index(index, path)
    return index


def _items_from_index(index: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(index, dict):
        items = index.get("items") or []
    else:
        items = index
    return [item for item in items if isinstance(item, dict)]


def _search_result(item: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "video_id": _clean_text(item.get("video_id")),
        "title": _clean_text(item.get("title")) or "Untitled Video",
        "channel": _clean_text(item.get("channel")) or "Unknown Channel",
        "start": _coerce_float(item.get("start")),
        "end": _coerce_float(item.get("end")),
        "text": _clean_text(item.get("text")),
        "chunk_index": int(_coerce_float(item.get("chunk_index"))),
        "score": score,
        "embedding_model": _clean_text(item.get("embedding_model")),
        "transcript_hash": _clean_text(item.get("transcript_hash")),
        "indexed_at": _clean_text(item.get("indexed_at")),
    }


def search_semantic_items(
    items: Iterable[dict[str, Any]],
    query_vector: Sequence[float],
    limit: int = 10,
    embedding_model: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    model_filter = _clean_text(embedding_model)
    query = normalize_vector(query_vector)
    results: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if model_filter and _clean_text(item.get("embedding_model")) != model_filter:
            continue

        try:
            score = cosine_similarity(query, item.get("vector") or [])
        except ValueError:
            continue

        if min_score is not None and score < min_score:
            continue
        results.append(_search_result(item, score))

    results.sort(
        key=lambda result: (
            -result["score"],
            result["video_id"],
            result["chunk_index"],
            result["start"],
            result["text"],
        )
    )
    return results[:limit]


def search_semantic_index(
    query_vector: Sequence[float],
    path: str = DEFAULT_INDEX_PATH,
    limit: int = 10,
    embedding_model: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    index = load_semantic_index(path)
    return search_semantic_items(
        _items_from_index(index),
        query_vector,
        limit=limit,
        embedding_model=embedding_model,
        min_score=min_score,
    )


def detect_stale_transcripts(
    entries: Iterable[dict[str, Any]],
    index: dict[str, Any] | list[dict[str, Any]] | None = None,
    path: str = DEFAULT_INDEX_PATH,
    embedding_model: str | None = None,
) -> list[dict[str, Any]]:
    loaded_index = load_semantic_index(path) if index is None else index
    model = _clean_text(embedding_model)
    items_by_video: dict[str, list[dict[str, Any]]] = {}

    for item in _items_from_index(loaded_index):
        video_id = _clean_text(item.get("video_id"))
        if video_id:
            items_by_video.setdefault(video_id, []).append(item)

    stale = []
    for entry in entries:
        video_id = _entry_text(entry, "video_id")
        if not video_id:
            continue

        expected_hash = compute_transcript_hash(entry)
        indexed_items = items_by_video.get(video_id, [])
        indexed_hashes = sorted(
            {
                _clean_text(item.get("transcript_hash"))
                for item in indexed_items
                if _clean_text(item.get("transcript_hash"))
            }
        )

        reason = ""
        if not indexed_items:
            reason = "missing"
        elif model and any(_clean_text(item.get("embedding_model")) != model for item in indexed_items):
            reason = "model_mismatch"
        elif indexed_hashes != [expected_hash]:
            reason = "hash_mismatch"

        if reason:
            stale.append(
                {
                    "video_id": video_id,
                    "reason": reason,
                    "expected_hash": expected_hash,
                    "indexed_hashes": indexed_hashes,
                }
            )

    return stale


def stale_transcript_ids(
    entries: Iterable[dict[str, Any]],
    index: dict[str, Any] | list[dict[str, Any]] | None = None,
    path: str = DEFAULT_INDEX_PATH,
    embedding_model: str | None = None,
) -> list[str]:
    return [
        item["video_id"]
        for item in detect_stale_transcripts(
            entries,
            index=index,
            path=path,
            embedding_model=embedding_model,
        )
    ]


class SemanticIndexStore:
    def __init__(self, path: str = DEFAULT_INDEX_PATH):
        self.path = path

    def load(self) -> dict[str, Any]:
        return load_semantic_index(self.path)

    def save(self, index: dict[str, Any]) -> str:
        return save_semantic_index(index, self.path)

    def rebuild(
        self,
        entries: Iterable[dict[str, Any]],
        embedder: Embedder,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        segments_per_chunk: int = DEFAULT_SEGMENTS_PER_CHUNK,
        segment_overlap: int = DEFAULT_SEGMENT_OVERLAP,
        indexed_at: str | None = None,
    ) -> dict[str, Any]:
        return rebuild_semantic_index(
            entries,
            embedder,
            path=self.path,
            embedding_model=embedding_model,
            segments_per_chunk=segments_per_chunk,
            segment_overlap=segment_overlap,
            indexed_at=indexed_at,
        )

    def search(
        self,
        query_vector: Sequence[float],
        limit: int = 10,
        embedding_model: str | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        return search_semantic_index(
            query_vector,
            path=self.path,
            limit=limit,
            embedding_model=embedding_model,
            min_score=min_score,
        )

    def stale_transcripts(
        self,
        entries: Iterable[dict[str, Any]],
        embedding_model: str | None = None,
    ) -> list[dict[str, Any]]:
        return detect_stale_transcripts(
            entries,
            path=self.path,
            embedding_model=embedding_model,
        )

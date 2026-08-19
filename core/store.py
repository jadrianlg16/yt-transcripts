import html
import json
import os
import re
from typing import Any, Dict, List, Protocol

DATA_FILE = "transcripts_store.json"
SQLITE_DATA_FILE = "transcripts_store.sqlite3"

_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def normalize_display_text(value: Any) -> str:
    """Undo the escaping YouTube's embedded JSON leaves in titles and channel names.

    Older archives stored channel names verbatim, so ``&`` survives as the literal
    text ``\\u0026`` and splits one channel into two.
    """
    text = str(value)
    if "\\u" in text:
        text = _UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text)
    return html.unescape(text.replace("\\/", "/")).strip()


def normalize_entry_display_fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(entry)
    for key in ("title", "channel"):
        if normalized.get(key) is not None:
            normalized[key] = normalize_display_text(normalized[key])
    return normalized


class TranscriptRepository(Protocol):
    def add_entry(self, entry: Dict[str, Any]) -> None:
        ...

    def delete_entry(self, video_id: str) -> None:
        ...

    def all_entries(self) -> List[Dict[str, Any]]:
        ...


class JsonTranscriptStore:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.file_path):
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return (
            [normalize_entry_display_fields(entry) for entry in data if isinstance(entry, dict)]
            if isinstance(data, list)
            else []
        )

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_entry(self, entry):
        entry = normalize_entry_display_fields(entry)
        # Prevent duplicates in the UI list if video_id matches
        self.data = [e for e in self.data if e.get('video_id') != entry['video_id']]
        self.data.append(entry)
        self.save()

    def delete_entry(self, video_id):
        self.data = [e for e in self.data if e.get('video_id') != video_id]
        self.save()

    def all_entries(self):
        return self.data

    def saved_video_ids(self):
        return {str(e.get("video_id")) for e in self.data if e.get("video_id")}

    def list_summaries(self):
        """Same shape as the SQLite store: list fields only, no transcript bodies."""
        summaries = []
        for entry in self.data:
            segments = entry.get("segments") or []
            duration = max(
                (
                    float(s.get("start") or 0) + float(s.get("duration") or 0)
                    for s in segments
                    if isinstance(s, dict)
                ),
                default=0.0,
            )
            summaries.append({
                "video_id": entry.get("video_id", ""),
                "title": entry.get("title", ""),
                "channel": entry.get("channel", ""),
                "saved_at": entry.get("saved_at", ""),
                "transcript_char_count": len(str(entry.get("transcript") or "")),
                "segment_count": len(segments),
                "duration_seconds": round(duration, 2),
            })
        return summaries


class TranscriptStore(JsonTranscriptStore):
    pass


def create_transcript_store(
    backend: str | None = None,
    json_path: str = DATA_FILE,
    sqlite_path: str = SQLITE_DATA_FILE,
) -> TranscriptRepository:
    selected_backend = (
        backend or os.getenv("TRANSCRIPT_STORE_BACKEND", "auto")
    ).strip().lower()

    if selected_backend == "auto":
        selected_backend = "sqlite" if os.path.exists(sqlite_path) else "json"

    if selected_backend in {"json", "file"}:
        return TranscriptStore(json_path)

    if selected_backend in {"sqlite", "sqlite3"}:
        from core.sqlite_store import SQLiteTranscriptStore

        return SQLiteTranscriptStore(sqlite_path)

    raise ValueError(f"Unsupported transcript store backend: {selected_backend}")

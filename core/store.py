import json
import os
from typing import Any, Dict, List, Protocol

DATA_FILE = "transcripts_store.json"
SQLITE_DATA_FILE = "transcripts_store.sqlite3"


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
        return data if isinstance(data, list) else []

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_entry(self, entry):
        # Prevent duplicates in the UI list if video_id matches
        self.data = [e for e in self.data if e.get('video_id') != entry['video_id']]
        self.data.append(entry)
        self.save()

    def delete_entry(self, video_id):
        self.data = [e for e in self.data if e.get('video_id') != video_id]
        self.save()

    def all_entries(self):
        return self.data


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

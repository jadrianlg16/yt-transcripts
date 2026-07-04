from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

DEFAULT_ORGANIZATION_FILE = "research_organization.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ResearchOrganizationStore:
    def __init__(self, file_path: str | Path = DEFAULT_ORGANIZATION_FILE):
        self.file_path = Path(file_path)
        self.data = self._load()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def set_tags(self, video_id: str, tags: Iterable[str]) -> list[str]:
        normalized = _normalize_tags(tags)
        if normalized:
            self.data["tags"][video_id] = normalized
        else:
            self.data["tags"].pop(video_id, None)
        self._save()
        return normalized

    def set_video_note(self, video_id: str, note: str) -> str:
        clean_note = str(note or "").strip()
        if clean_note:
            self.data["video_notes"][video_id] = clean_note
        else:
            self.data["video_notes"].pop(video_id, None)
        self._save()
        return clean_note

    def add_timestamp_note(self, video_id: str, start: float, text: str) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("Timestamp note text is required")

        note = {
            "id": _new_id(),
            "video_id": video_id,
            "start": _as_float(start),
            "text": clean_text,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        notes = self.data["timestamp_notes"].setdefault(video_id, [])
        notes.append(note)
        notes.sort(key=lambda item: item.get("start", 0))
        self._save()
        return deepcopy(note)

    def delete_timestamp_note(self, video_id: str, note_id: str) -> bool:
        notes = self.data["timestamp_notes"].get(video_id, [])
        remaining = [note for note in notes if note.get("id") != note_id]
        if len(remaining) == len(notes):
            return False

        if remaining:
            self.data["timestamp_notes"][video_id] = remaining
        else:
            self.data["timestamp_notes"].pop(video_id, None)
        self._save()
        return True

    def create_collection(self, name: str, description: str = "") -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Collection name is required")

        now = utc_now()
        collection = {
            "id": _new_id(),
            "name": clean_name,
            "description": str(description or "").strip(),
            "created_at": now,
            "updated_at": now,
            "clips": [],
        }
        self.data["collections"].append(collection)
        self._save()
        return deepcopy(collection)

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        collection = self._find_collection(collection_id)
        if collection is None:
            return None

        if name is not None:
            clean_name = str(name or "").strip()
            if not clean_name:
                raise ValueError("Collection name is required")
            collection["name"] = clean_name
        if description is not None:
            collection["description"] = str(description or "").strip()
        collection["updated_at"] = utc_now()
        self._save()
        return deepcopy(collection)

    def delete_collection(self, collection_id: str) -> bool:
        collections = self.data["collections"]
        remaining = [collection for collection in collections if collection.get("id") != collection_id]
        if len(remaining) == len(collections):
            return False

        self.data["collections"] = remaining
        self._save()
        return True

    def add_clip(
        self,
        collection_id: str,
        video_id: str,
        start: float,
        end: float | None = None,
        text: str = "",
        note: str = "",
    ) -> dict[str, Any] | None:
        collection = self._find_collection(collection_id)
        if collection is None:
            return None

        now = utc_now()
        clip = {
            "id": _new_id(),
            "video_id": video_id,
            "start": _as_float(start),
            "end": _as_float(end) if end is not None else None,
            "text": str(text or "").strip(),
            "note": str(note or "").strip(),
            "created_at": now,
            "updated_at": now,
        }
        collection.setdefault("clips", []).append(clip)
        collection["updated_at"] = now
        self._save()
        return deepcopy(clip)

    def delete_clip(self, collection_id: str, clip_id: str) -> bool:
        collection = self._find_collection(collection_id)
        if collection is None:
            return False

        clips = collection.setdefault("clips", [])
        remaining = [clip for clip in clips if clip.get("id") != clip_id]
        if len(remaining) == len(clips):
            return False

        collection["clips"] = remaining
        collection["updated_at"] = utc_now()
        self._save()
        return True

    def export_collections(self) -> dict[str, Any]:
        return {
            "version": 1,
            "exported_at": utc_now(),
            "collections": deepcopy(self.data["collections"]),
        }

    def import_collections(self, collections: Iterable[dict[str, Any]], replace: bool = False) -> int:
        normalized = [_normalize_collection(item) for item in collections if isinstance(item, dict)]
        if replace:
            self.data["collections"] = []

        by_id = {
            collection["id"]: index
            for index, collection in enumerate(self.data["collections"])
        }
        imported_count = 0
        for collection in normalized:
            existing_index = by_id.get(collection["id"])
            if existing_index is None:
                self.data["collections"].append(collection)
                by_id[collection["id"]] = len(self.data["collections"]) - 1
            else:
                self.data["collections"][existing_index] = collection
            imported_count += 1

        self._save()
        return imported_count

    def collection_markdown(
        self,
        collection_id: str,
        transcripts: dict[str, dict[str, Any]],
    ) -> str | None:
        collection = self._find_collection(collection_id)
        if collection is None:
            return None

        lines = [
            f"# {collection['name']}",
            "",
        ]
        if collection.get("description"):
            lines.extend([collection["description"], ""])
        lines.extend([
            f"Exported: {utc_now()}",
            f"Clips: {len(collection.get('clips', []))}",
            "",
        ])

        for clip in collection.get("clips", []):
            video_id = clip.get("video_id", "")
            transcript = transcripts.get(video_id, {})
            title = transcript.get("title") or video_id or "Unknown video"
            channel = transcript.get("channel") or "Unknown channel"
            saved_at = transcript.get("saved_at") or "Unknown saved date"
            start = _as_float(clip.get("start"))
            url = youtube_timestamp_url(video_id, start)
            tags = self.data["tags"].get(video_id, [])
            video_note = self.data["video_notes"].get(video_id, "")
            nearby_notes = [
                note
                for note in self.data["timestamp_notes"].get(video_id, [])
                if abs(_as_float(note.get("start")) - start) < 1
            ]

            lines.extend([
                f"## {title}",
                "",
                f"- Channel: {channel}",
                f"- Video ID: {video_id}",
                f"- Saved at: {saved_at}",
                f"- Timestamp: [{format_timestamp(start)}]({url})",
            ])
            if tags:
                lines.append(f"- Tags: {', '.join(tags)}")
            lines.append("")

            if clip.get("text"):
                lines.extend([quote_markdown(str(clip["text"])), ""])
            if clip.get("note"):
                lines.extend([f"Clip note: {clip['note']}", ""])
            if video_note:
                lines.extend([f"Video note: {video_note}", ""])
            for note in nearby_notes:
                lines.extend([f"Timestamp note ({format_timestamp(_as_float(note.get('start')))}): {note.get('text', '')}", ""])

        return "\n".join(lines).rstrip() + "\n"

    def _load(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return _empty_data()

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError):
            return _empty_data()

        return _normalize_data(raw)

    def _save(self) -> None:
        if self.file_path.parent != Path("."):
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)

    def _find_collection(self, collection_id: str) -> dict[str, Any] | None:
        return next(
            (
                collection
                for collection in self.data["collections"]
                if collection.get("id") == collection_id
            ),
            None,
        )


def youtube_timestamp_url(video_id: str, start: float) -> str:
    return f"https://youtube.com/watch?v={video_id}&t={max(0, int(start))}s"


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60

    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def quote_markdown(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def _empty_data() -> dict[str, Any]:
    return {
        "tags": {},
        "video_notes": {},
        "timestamp_notes": {},
        "collections": [],
    }


def _normalize_data(raw: Any) -> dict[str, Any]:
    data = _empty_data()
    if not isinstance(raw, dict):
        return data

    tags = raw.get("tags", {})
    if isinstance(tags, dict):
        data["tags"] = {
            str(video_id): _normalize_tags(values if isinstance(values, list) else [])
            for video_id, values in tags.items()
        }

    video_notes = raw.get("video_notes", {})
    if isinstance(video_notes, dict):
        data["video_notes"] = {
            str(video_id): str(note).strip()
            for video_id, note in video_notes.items()
            if str(note).strip()
        }

    timestamp_notes = raw.get("timestamp_notes", {})
    if isinstance(timestamp_notes, dict):
        for video_id, notes in timestamp_notes.items():
            if isinstance(notes, list):
                normalized_notes = [_normalize_timestamp_note(str(video_id), note) for note in notes if isinstance(note, dict)]
                data["timestamp_notes"][str(video_id)] = sorted(
                    normalized_notes,
                    key=lambda item: item.get("start", 0),
                )

    collections = raw.get("collections", [])
    if isinstance(collections, list):
        data["collections"] = [
            _normalize_collection(collection)
            for collection in collections
            if isinstance(collection, dict)
        ]

    return data


def _normalize_tags(tags: Iterable[str]) -> list[str]:
    seen = set()
    normalized = []
    for tag in tags:
        clean = str(tag or "").strip().lower().lstrip("#")
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def _normalize_timestamp_note(video_id: str, note: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    return {
        "id": str(note.get("id") or _new_id()),
        "video_id": video_id,
        "start": _as_float(note.get("start")),
        "text": str(note.get("text") or "").strip(),
        "created_at": str(note.get("created_at") or now),
        "updated_at": str(note.get("updated_at") or note.get("created_at") or now),
    }


def _normalize_collection(collection: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    collection_id = str(collection.get("id") or _new_id())
    clips = collection.get("clips", [])
    return {
        "id": collection_id,
        "name": str(collection.get("name") or "Imported Collection").strip(),
        "description": str(collection.get("description") or "").strip(),
        "created_at": str(collection.get("created_at") or now),
        "updated_at": str(collection.get("updated_at") or now),
        "clips": [
            _normalize_clip(clip)
            for clip in clips
            if isinstance(clip, dict)
        ] if isinstance(clips, list) else [],
    }


def _normalize_clip(clip: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    end = clip.get("end")
    return {
        "id": str(clip.get("id") or _new_id()),
        "video_id": str(clip.get("video_id") or ""),
        "start": _as_float(clip.get("start")),
        "end": _as_float(end) if end is not None else None,
        "text": str(clip.get("text") or "").strip(),
        "note": str(clip.get("note") or "").strip(),
        "created_at": str(clip.get("created_at") or now),
        "updated_at": str(clip.get("updated_at") or clip.get("created_at") or now),
    }


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _new_id() -> str:
    return uuid4().hex

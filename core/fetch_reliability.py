from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.fetcher import extract_video_id
from core.organization import utc_now

DEFAULT_RELIABILITY_FILE = "fetch_reliability.json"
DEFAULT_FREQUENCY_MINUTES = 360
MIN_FREQUENCY_MINUTES = 15
MAX_FETCH_RUNS = 200


DEFAULT_WATCHER_SETTINGS = {
    "enabled": False,
    "channels": [],
    "frequency_minutes": DEFAULT_FREQUENCY_MINUTES,
    "languages": ["en"],
    "last_checked_at": None,
    "next_check_at": None,
    # Daily windows the watcher may run in, as "HH:MM" pairs in local time. Empty
    # means the defaults in core/schedule.py.
    "check_windows": [],
}

DEFAULT_COOLDOWN = {
    "until": None,
    "reason": "",
    "started_at": None,
    # Consecutive blocks, so repeat offences can wait longer than the first.
    "strikes": 0,
}


class FetchReliabilityStore:
    def __init__(self, file_path: str | Path = DEFAULT_RELIABILITY_FILE):
        self.file_path = Path(file_path)
        if self.file_path.parent != Path("."):
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, MAX_FETCH_RUNS))
        return list(reversed(self.data["runs"]))[:bounded_limit]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        for run in self.data["runs"]:
            if run.get("id") == run_id:
                return run
        return None

    def start_run(
        self,
        run_type: str,
        source: str,
        total: int = 0,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = {
            "id": run_id or uuid4().hex,
            "type": run_type,
            "source": source,
            "status": "running",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "finished_at": None,
            "message": "",
            "total": max(0, int(total or 0)),
            "success_count": 0,
            "failure_count": 0,
            "skipped_count": 0,
            "successes": [],
            "failures": [],
            "skipped": [],
            "metadata": metadata or {},
        }
        self.data["runs"].append(run)
        self.data["runs"] = self.data["runs"][-MAX_FETCH_RUNS:]
        self._save()
        return run

    def set_total(self, run_id: str, total: int) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None

        run["total"] = max(0, int(total or 0))
        run["updated_at"] = utc_now()
        self._save()
        return run

    def record_success(
        self,
        run_id: str,
        video_id: str,
        title: str = "",
        index: int | None = None,
        total: int | None = None,
        url: str | None = None,
    ) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None

        item = {
            "video_id": video_id,
            "title": title,
            "url": url or youtube_watch_url(video_id),
            "index": index,
            "total": total,
            "saved_at": utc_now(),
        }
        run["successes"].append(item)
        run["success_count"] = len(run["successes"])
        run["updated_at"] = utc_now()
        self._save()
        return item

    def record_failure(
        self,
        run_id: str,
        error: str,
        video_id: str | None = None,
        url: str | None = None,
        title: str = "",
        index: int | None = None,
        total: int | None = None,
    ) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None

        resolved_video_id = video_id or extract_video_id(url or "")
        retry_url = url or (youtube_watch_url(resolved_video_id) if resolved_video_id else None)
        item = {
            "video_id": resolved_video_id,
            "title": title,
            "url": retry_url,
            "error": error,
            "index": index,
            "total": total,
            "failed_at": utc_now(),
            "retryable": bool(resolved_video_id),
        }
        run["failures"].append(item)
        run["failure_count"] = len(run["failures"])
        run["updated_at"] = utc_now()
        self._save()
        return item

    def record_skipped(
        self,
        run_id: str,
        video_id: str | None = None,
        reason: str = "",
        url: str | None = None,
        title: str = "",
        index: int | None = None,
        total: int | None = None,
    ) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None

        item = {
            "video_id": video_id,
            "title": title,
            "url": url or (youtube_watch_url(video_id) if video_id else None),
            "reason": reason,
            "index": index,
            "total": total,
            "skipped_at": utc_now(),
        }
        run["skipped"].append(item)
        run["skipped_count"] = len(run["skipped"])
        run["updated_at"] = utc_now()
        self._save()
        return item

    def finish_run(
        self,
        run_id: str,
        status: str | None = None,
        message: str = "",
    ) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if not run:
            return None

        if status is None:
            if run.get("failure_count", 0) and run.get("success_count", 0):
                status = "partial"
            elif run.get("failure_count", 0):
                status = "failed"
            else:
                status = "success"
        run["status"] = status
        run["message"] = message
        run["finished_at"] = utc_now()
        run["updated_at"] = run["finished_at"]
        self._save()
        return run

    def retry_items(self, run_id: str) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if not run:
            return []

        seen: set[str] = set()
        retryable: list[dict[str, Any]] = []
        for failure in run.get("failures", []):
            if failure.get("retryable") is False:
                continue
            video_id = failure.get("video_id")
            url = failure.get("url")
            video_id = video_id or extract_video_id(str(url or ""))
            if not video_id:
                continue
            key = str(video_id or url or "")
            if not key or key in seen:
                continue
            seen.add(key)
            retryable.append({
                "video_id": video_id,
                "url": url,
                "title": failure.get("title") or video_id or url or "Unknown video",
                "error": failure.get("error") or "",
            })
        return retryable

    def get_settings(self) -> dict[str, Any]:
        return normalize_watcher_settings(self.data.get("watcher", {}))

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.get_settings()
        merged = {
            **current,
            **updates,
            "last_checked_at": current.get("last_checked_at"),
            "next_check_at": current.get("next_check_at"),
        }
        if "last_checked_at" in updates:
            merged["last_checked_at"] = updates["last_checked_at"]
        if "next_check_at" in updates:
            merged["next_check_at"] = updates["next_check_at"]

        settings = normalize_watcher_settings(merged)
        self.data["watcher"] = settings
        self._save()
        return settings

    def mark_watcher_checked(self, next_check_at: str | None = None) -> dict[str, Any]:
        settings = self.get_settings()
        settings["last_checked_at"] = utc_now()
        settings["next_check_at"] = next_check_at
        self.data["watcher"] = settings
        self._save()
        return settings

    def get_cooldown(self) -> dict[str, Any]:
        """Current rate-limit cooldown, with the remaining seconds resolved now."""
        cooldown = normalize_cooldown(self.data.get("cooldown", {}))
        remaining = _seconds_until(cooldown["until"])
        return {**cooldown, "active": remaining > 0, "remaining_seconds": remaining}

    def start_cooldown(self, seconds: int, reason: str = "") -> dict[str, Any]:
        """Hold off new ingestion until the block YouTube applied has aged out.

        Consecutive blocks raise the strike count so a caller can back off harder
        the second and third time rather than repeating the same wait.
        """
        current = self.get_cooldown()
        bounded_seconds = max(0, int(seconds))
        self.data["cooldown"] = {
            "until": _iso_after(bounded_seconds),
            "reason": str(reason or ""),
            "started_at": utc_now(),
            "strikes": int(current.get("strikes") or 0) + 1,
        }
        self._save()
        return self.get_cooldown()

    def clear_cooldown(self) -> dict[str, Any]:
        self.data["cooldown"] = dict(DEFAULT_COOLDOWN)
        self._save()
        return self.get_cooldown()

    def record_clean_run(self) -> dict[str, Any]:
        """A run that finished without being blocked resets the strike count."""
        cooldown = self.get_cooldown()
        if not cooldown["active"] and cooldown["strikes"]:
            return self.clear_cooldown()
        return cooldown

    def _load(self) -> dict[str, Any]:
        empty = {
            "runs": [],
            "watcher": dict(DEFAULT_WATCHER_SETTINGS),
            "cooldown": dict(DEFAULT_COOLDOWN),
        }
        if not self.file_path.exists():
            return empty

        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return empty

        runs = data.get("runs", []) if isinstance(data, dict) else []
        watcher = data.get("watcher", {}) if isinstance(data, dict) else {}
        cooldown = data.get("cooldown", {}) if isinstance(data, dict) else {}
        return {
            "runs": [normalize_run(run) for run in runs if isinstance(run, dict)][-MAX_FETCH_RUNS:],
            "watcher": normalize_watcher_settings(watcher),
            "cooldown": normalize_cooldown(cooldown),
        }

    def _save(self) -> None:
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _seconds_until(value: Any) -> int:
    deadline = _parse_iso(value)
    if deadline is None:
        return 0
    return max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))


def _iso_after(seconds: int) -> str:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=max(0, int(seconds)))
    return deadline.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_cooldown(cooldown: Any) -> dict[str, Any]:
    source = cooldown if isinstance(cooldown, dict) else {}
    until = source.get("until")
    return {
        "until": str(until) if until else None,
        "reason": str(source.get("reason") or ""),
        "started_at": str(source.get("started_at")) if source.get("started_at") else None,
        "strikes": max(0, int(source.get("strikes") or 0)),
    }


def normalize_run(run: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id": str(run.get("id") or uuid4().hex),
        "type": str(run.get("type") or run.get("source_type") or "unknown"),
        "source": str(run.get("source") or ""),
        "status": str(run.get("status") or "unknown"),
        "started_at": run.get("started_at") or utc_now(),
        "updated_at": run.get("updated_at") or run.get("started_at") or utc_now(),
        "finished_at": run.get("finished_at"),
        "message": str(run.get("message") or ""),
        "total": max(0, int(run.get("total") or 0)),
        "successes": list(run.get("successes") or []),
        "failures": list(run.get("failures") or []),
        "skipped": list(run.get("skipped") or []),
        "metadata": dict(run.get("metadata") or {}),
    }
    normalized["success_count"] = int(run.get("success_count") or len(normalized["successes"]))
    normalized["failure_count"] = int(run.get("failure_count") or len(normalized["failures"]))
    normalized["skipped_count"] = int(run.get("skipped_count") or len(normalized["skipped"]))
    return normalized


def normalize_check_windows(value: Any) -> list[list[str]]:
    """Keep only well-formed "HH:MM" pairs where the start precedes the end."""
    if not isinstance(value, (list, tuple)):
        return []

    windows: list[list[str]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            start = time.fromisoformat(str(item[0]))
            end = time.fromisoformat(str(item[1]))
        except (TypeError, ValueError):
            continue
        if start >= end:
            continue
        windows.append([start.strftime("%H:%M"), end.strftime("%H:%M")])

    return sorted(windows, key=lambda pair: pair[0])


def normalize_watcher_settings(settings: dict[str, Any]) -> dict[str, Any]:
    raw_frequency = settings.get("frequency_minutes", DEFAULT_FREQUENCY_MINUTES)
    try:
        frequency_minutes = int(raw_frequency)
    except (TypeError, ValueError):
        frequency_minutes = DEFAULT_FREQUENCY_MINUTES

    return {
        "enabled": bool(settings.get("enabled", False)),
        "channels": normalize_list(settings.get("channels"), allow_urls=True),
        "frequency_minutes": max(MIN_FREQUENCY_MINUTES, frequency_minutes),
        "languages": normalize_languages(settings.get("languages")),
        "last_checked_at": settings.get("last_checked_at"),
        "next_check_at": settings.get("next_check_at"),
        "check_windows": normalize_check_windows(settings.get("check_windows")),
    }


def normalize_list(value: Any, allow_urls: bool = False) -> list[str]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, str):
        items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        items = value
    else:
        items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if not allow_urls:
            text = text.lower()
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def normalize_languages(value: Any) -> list[str]:
    languages = []
    for item in normalize_list(value):
        text = item.lower()
        if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]+)?", text):
            languages.append(text)
    return languages or ["en"]


def youtube_watch_url(video_id: str | None) -> str | None:
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

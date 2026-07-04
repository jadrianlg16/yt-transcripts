from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from core.ai_settings import DEFAULT_PROMPT_VERSION, DEFAULT_PROVIDER
from core.organization import utc_now

DEFAULT_AI_ARTIFACTS_FILE = "ai_artifacts.json"
VALID_ARTIFACT_STATUSES = {"success", "failed", "running", "skipped"}


class AIArtifactStore:
    def __init__(self, file_path: str | Path = DEFAULT_AI_ARTIFACTS_FILE):
        self.file_path = Path(file_path)
        self.data = self._load()

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.data)

    def save_video_summary(
        self,
        video_id: str,
        summary: Any,
        transcript: Any = "",
        transcript_hash_value: str | None = None,
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        status: str = "success",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_video_id = str(video_id or "").strip()
        if not clean_video_id:
            raise ValueError("video_id is required")

        artifact = _artifact_record(
            artifact_type="summary",
            content=summary,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=status,
            error=error,
            metadata=metadata,
            extra={
                "video_id": clean_video_id,
                "transcript_hash": transcript_hash_value or transcript_hash(transcript),
            },
        )
        self.data["video_summaries"].setdefault(clean_video_id, []).append(artifact)
        self._save()
        return deepcopy(artifact)

    def latest_video_summary(
        self,
        video_id: str,
        transcript_hash_value: str | None = None,
    ) -> dict[str, Any] | None:
        summaries = self.list_video_summaries(video_id)
        if transcript_hash_value:
            summaries = [
                summary
                for summary in summaries
                if summary.get("transcript_hash") == transcript_hash_value
            ]
        return summaries[-1] if summaries else None

    def list_video_summaries(self, video_id: str | None = None) -> list[dict[str, Any]]:
        if video_id is not None:
            return deepcopy(self.data["video_summaries"].get(str(video_id), []))

        summaries: list[dict[str, Any]] = []
        for items in self.data["video_summaries"].values():
            summaries.extend(items)
        return deepcopy(summaries)

    def save_comparison(
        self,
        video_ids: Iterable[str],
        comparison: Any,
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        status: str = "success",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = _artifact_record(
            artifact_type="comparison",
            content=comparison,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=status,
            error=error,
            metadata=metadata,
            extra={"video_ids": _normalize_ids(video_ids)},
        )
        self.data["comparisons"].append(artifact)
        self._save()
        return deepcopy(artifact)

    def save_timeline(
        self,
        timeline: Any,
        video_id: str | None = None,
        video_ids: Iterable[str] | None = None,
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        status: str = "success",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ids = _normalize_ids(video_ids or ([video_id] if video_id else []))
        artifact = _artifact_record(
            artifact_type="timeline",
            content=timeline,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=status,
            error=error,
            metadata=metadata,
            extra={
                "video_id": str(video_id or "").strip() or None,
                "video_ids": ids,
            },
        )
        self.data["timelines"].append(artifact)
        self._save()
        return deepcopy(artifact)

    def save_generic_run(
        self,
        run_type: str,
        output: Any,
        input_reference: str = "",
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        status: str = "success",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = _artifact_record(
            artifact_type="generic",
            content=output,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=status,
            error=error,
            metadata=metadata,
            extra={
                "run_type": str(run_type or "generic").strip() or "generic",
                "input_reference": str(input_reference or "").strip(),
            },
        )
        self.data["generic_runs"].append(artifact)
        self._save()
        return deepcopy(artifact)

    def list_comparisons(self, limit: int | None = None) -> list[dict[str, Any]]:
        return deepcopy(_limited(self.data["comparisons"], limit))

    def list_timelines(
        self,
        video_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        timelines = self.data["timelines"]
        if video_id is not None:
            clean_video_id = str(video_id)
            timelines = [
                timeline
                for timeline in timelines
                if timeline.get("video_id") == clean_video_id
                or clean_video_id in timeline.get("video_ids", [])
            ]
        return deepcopy(_limited(timelines, limit))

    def list_generic_runs(
        self,
        run_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        runs = self.data["generic_runs"]
        if run_type is not None:
            clean_type = str(run_type or "").strip()
            runs = [run for run in runs if run.get("run_type") == clean_type]
        return deepcopy(_limited(runs, limit))

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


def transcript_hash(transcript: Any) -> str:
    text = _transcript_text(transcript)
    normalized = "\n".join(line.strip() for line in text.splitlines()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _artifact_record(
    artifact_type: str,
    content: Any,
    provider: str,
    model: str,
    prompt_version: str,
    status: str,
    error: str | None,
    metadata: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_status = str(status or "success").strip().lower()
    if clean_status not in VALID_ARTIFACT_STATUSES:
        clean_status = "failed" if error else "success"

    record = {
        "id": uuid4().hex,
        "type": str(artifact_type or "generic").strip() or "generic",
        "generated_at": utc_now(),
        "provider": str(provider or DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER,
        "model": str(model or "").strip(),
        "prompt_version": str(prompt_version or DEFAULT_PROMPT_VERSION).strip() or DEFAULT_PROMPT_VERSION,
        "status": clean_status,
        "error": str(error).strip() if error else None,
        "content": content,
        "metadata": dict(metadata or {}),
    }
    record.update(extra or {})
    return record


def _empty_data() -> dict[str, Any]:
    return {
        "video_summaries": {},
        "comparisons": [],
        "timelines": [],
        "generic_runs": [],
    }


def _normalize_data(raw: Any) -> dict[str, Any]:
    data = _empty_data()
    if not isinstance(raw, dict):
        return data

    summaries = raw.get("video_summaries", {})
    if isinstance(summaries, dict):
        data["video_summaries"] = {
            str(video_id): [
                _normalize_artifact("summary", item)
                for item in items
                if isinstance(item, dict)
            ]
            for video_id, items in summaries.items()
            if isinstance(items, list)
        }

    for key, artifact_type in (
        ("comparisons", "comparison"),
        ("timelines", "timeline"),
        ("generic_runs", "generic"),
    ):
        items = raw.get(key, [])
        if isinstance(items, list):
            data[key] = [
                _normalize_artifact(artifact_type, item)
                for item in items
                if isinstance(item, dict)
            ]

    return data


def _normalize_artifact(default_type: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = _artifact_record(
        artifact_type=str(item.get("type") or default_type),
        content=item.get("content"),
        provider=str(item.get("provider") or DEFAULT_PROVIDER),
        model=str(item.get("model") or ""),
        prompt_version=str(item.get("prompt_version") or DEFAULT_PROMPT_VERSION),
        status=str(item.get("status") or "success"),
        error=item.get("error"),
        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
    )
    normalized["id"] = str(item.get("id") or normalized["id"])
    normalized["generated_at"] = str(item.get("generated_at") or normalized["generated_at"])

    for key in ("video_id", "transcript_hash", "video_ids", "run_type", "input_reference"):
        if key in item:
            normalized[key] = item[key]
    if isinstance(normalized.get("video_ids"), list):
        normalized["video_ids"] = _normalize_ids(normalized["video_ids"])
    return normalized


def _normalize_ids(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _transcript_text(transcript: Any) -> str:
    if isinstance(transcript, dict):
        if transcript.get("transcript"):
            return str(transcript.get("transcript") or "")
        segments = transcript.get("segments", [])
        if isinstance(segments, list):
            return "\n".join(
                str(segment.get("text") or "")
                for segment in segments
                if isinstance(segment, dict)
            )
    if isinstance(transcript, list):
        return "\n".join(
            str(segment.get("text") if isinstance(segment, dict) else segment)
            for segment in transcript
        )
    return str(transcript or "")


def _limited(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return list(items)
    bounded = max(1, int(limit or 1))
    return list(items)[-bounded:]

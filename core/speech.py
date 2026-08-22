"""Transcribe audio with the EchoScribe service instead of YouTube's captions.

Used when a video has no captions at all, or when the captions are not good enough
for the job: EchoScribe runs Whisper and can label who is speaking, which matters
for interviews. It is optional. With no service configured the archive works exactly
as before, on captions alone.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from typing import Any, Callable

import requests

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_POLL_SECONDS = 5.0
# Whisper is slower than real time on modest hardware, so a long talk needs room.
DEFAULT_MAX_WAIT_SECONDS = 3600


class SpeechServiceError(RuntimeError):
    pass


def speech_base_url() -> str:
    return os.getenv("YT_TRANSCRIPTS_SPEECH_URL", "").strip().rstrip("/")


def speech_enabled() -> bool:
    return bool(speech_base_url())


def service_health(base_url: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    base = (base_url or speech_base_url()).rstrip("/")
    if not base:
        return {"configured": False, "reachable": False, "reason": "No speech service configured."}

    try:
        response = requests.get(f"{base}/health", timeout=timeout)
        response.raise_for_status()
        return {"configured": True, "reachable": True, "url": base, "detail": response.json()}
    except (requests.RequestException, ValueError) as exc:
        return {"configured": True, "reachable": False, "url": base, "reason": str(exc)}


def submit_audio(
    audio_path: str,
    base_url: str,
    model: str = "small",
    language: str = "",
    diarize: bool = False,
    max_speakers: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Hand the file to the service and return its job id."""
    form = {
        "model": model,
        "language": language,
        "timestamp_mode": "sentence",
        "diarize": "1" if diarize else "0",
        # JSON carries start, end, speaker and text; the other formats are for people.
        "formats": "json",
    }
    if max_speakers:
        form["max_speakers"] = str(int(max_speakers))

    with open(audio_path, "rb") as handle:
        response = requests.post(
            f"{base_url}/transcribe",
            files={"file": (os.path.basename(audio_path), handle)},
            data=form,
            timeout=timeout,
        )

    if response.status_code >= 400:
        raise SpeechServiceError(f"Speech service rejected the audio: {response.text[:200]}")

    job_id = str(response.json().get("job_id") or "").strip()
    if not job_id:
        raise SpeechServiceError("Speech service did not return a job id")
    return job_id


def wait_for_job(
    job_id: str,
    base_url: str,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    max_wait_seconds: int = DEFAULT_MAX_WAIT_SECONDS,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll until the job finishes, reporting each stage as it changes."""
    deadline = now() + max_wait_seconds
    last_stage = None

    while True:
        response = requests.get(f"{base_url}/status/{job_id}", timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        status = response.json()

        stage = status.get("stage")
        if on_progress and stage != last_stage:
            on_progress(status)
            last_stage = stage

        state = str(status.get("status") or "").lower()
        if state == "done":
            return status
        if state == "error":
            raise SpeechServiceError(str(status.get("error") or "Transcription failed"))

        if now() >= deadline:
            raise SpeechServiceError(
                f"Transcription did not finish within {max_wait_seconds}s (last stage: {stage})"
            )
        sleep(poll_seconds)


def fetch_segments(job_id: str, base_url: str, timeout: int = 120) -> dict[str, Any]:
    """Pull the finished job's JSON export out of the zip the service returns."""
    response = requests.get(f"{base_url}/download/{job_id}", timeout=timeout)
    response.raise_for_status()

    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except zipfile.BadZipFile as exc:
        raise SpeechServiceError("Speech service returned an unreadable archive") from exc

    names = [n for n in archive.namelist() if n.lower().endswith(".json")]
    if not names:
        raise SpeechServiceError("Speech service archive contained no JSON transcript")

    try:
        payload = json.loads(archive.read(names[0]).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SpeechServiceError("Speech service returned malformed JSON") from exc

    return payload


def to_transcript_segments(payload: dict[str, Any], include_speakers: bool = True) -> list[dict[str, Any]]:
    """Convert the service's segments into the shape the archive stores.

    Speaker labels are kept inline because the archive has nowhere else to put
    them, and losing who said what is the main reason to run this at all.
    """
    segments: list[dict[str, Any]] = []
    speakers = {str(s.get("id")) for s in (payload.get("speakers") or []) if isinstance(s, dict)}
    label_worth_showing = include_speakers and len(speakers) > 1

    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        start = _as_float(item.get("start"))
        end = _as_float(item.get("end"))
        speaker = str(item.get("speaker") or "").strip()
        if label_worth_showing and speaker:
            text = f"{speaker}: {text}"

        segments.append({
            "text": text,
            "start": start,
            "duration": max(0.0, end - start),
        })

    return segments


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def transcribe_file(
    audio_path: str,
    base_url: str | None = None,
    model: str = "small",
    language: str = "",
    diarize: bool = False,
    max_speakers: int | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Submit, wait, and return segments plus what the service detected."""
    base = (base_url or speech_base_url()).rstrip("/")
    if not base:
        raise SpeechServiceError("No speech service configured")

    job_id = submit_audio(
        audio_path,
        base,
        model=model,
        language=language,
        diarize=diarize,
        max_speakers=max_speakers,
    )
    status = wait_for_job(job_id, base, on_progress=on_progress)
    payload = fetch_segments(job_id, base)

    return {
        "job_id": job_id,
        "language": payload.get("language") or status.get("language") or "",
        "speaker_count": len(payload.get("speakers") or []),
        "segments": to_transcript_segments(payload),
    }

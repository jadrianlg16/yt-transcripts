"""Keep video files on disk so the archive survives YouTube.

A transcript is only half a record. If a video is taken down, edited, or made
private, the words remain but the thing they describe is gone. This stores the file
itself for videos worth keeping.

The filesystem is the source of truth. A file named after the video id means that
video is archived; deleting the file un-archives it. There is deliberately no table
to fall out of step with what is actually on disk.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
DEFAULT_TIMEOUT_SECONDS = 3600
# Above 1080p the files get very large for very little benefit on a talking-head
# video, which is most of what this archives.
QUALITY_FORMATS = {
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "audio": "bestaudio/best",
}
DEFAULT_QUALITY = "720p"
MEDIA_SUFFIXES = (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus")


class MediaArchiveError(RuntimeError):
    pass


def media_dir() -> Path:
    configured = os.getenv("YT_TRANSCRIPTS_MEDIA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    data_dir = os.getenv("YT_TRANSCRIPTS_DATA_DIR", "").strip() or "."
    return Path(data_dir) / "media"


def ytdlp_path() -> str | None:
    return os.getenv("YT_TRANSCRIPTS_YTDLP", "").strip() or shutil.which("yt-dlp")


def archiving_available() -> bool:
    return bool(ytdlp_path())


def _valid_video_id(video_id: str) -> str:
    value = str(video_id or "").strip()
    if not VIDEO_ID_PATTERN.fullmatch(value):
        raise MediaArchiveError(f"Not a video id: {video_id!r}")
    return value


def archived_path(video_id: str) -> Path | None:
    """The stored file for a video, or None when it is not archived."""
    try:
        value = _valid_video_id(video_id)
    except MediaArchiveError:
        return None

    folder = media_dir()
    if not folder.is_dir():
        return None

    for candidate in sorted(folder.glob(f"{value}.*")):
        if candidate.is_file() and candidate.suffix.lower() in MEDIA_SUFFIXES:
            return candidate
    return None


def is_archived(video_id: str) -> bool:
    return archived_path(video_id) is not None


def archived_video_ids() -> set[str]:
    folder = media_dir()
    if not folder.is_dir():
        return set()
    return {
        path.stem
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES and VIDEO_ID_PATTERN.fullmatch(path.stem)
    }


def list_archived(entries_by_id: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Everything on disk, with the title and channel from the transcript archive."""
    entries_by_id = entries_by_id or {}
    items: list[dict[str, Any]] = []

    for video_id in sorted(archived_video_ids()):
        path = archived_path(video_id)
        if path is None:
            continue
        entry = entries_by_id.get(video_id, {})
        stat = path.stat()
        items.append({
            "video_id": video_id,
            "title": entry.get("title") or video_id,
            "channel": entry.get("channel") or "",
            "filename": path.name,
            "size_bytes": stat.st_size,
            "archived_at": int(stat.st_mtime),
            "has_transcript": bool(entry),
        })

    items.sort(key=lambda item: -item["archived_at"])
    return items


def storage_summary() -> dict[str, Any]:
    folder = media_dir()
    items = list_archived()
    used = sum(item["size_bytes"] for item in items)

    # Report free space before anything has been archived too, by asking about the
    # nearest parent that exists.
    free = None
    probe = folder
    while probe != probe.parent and not probe.is_dir():
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        free = None

    return {
        "path": str(folder),
        "exists": folder.is_dir(),
        "count": len(items),
        "used_bytes": used,
        "free_bytes": free,
        "available": archiving_available(),
    }


def download_video(
    video_id: str,
    quality: str = DEFAULT_QUALITY,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Fetch the video and keep it. Returns the stored path."""
    value = _valid_video_id(video_id)
    binary = ytdlp_path()
    if not binary:
        raise MediaArchiveError("yt-dlp is not installed, so videos cannot be archived")

    existing = archived_path(value)
    if existing is not None:
        return existing

    folder = media_dir()
    folder.mkdir(parents=True, exist_ok=True)
    selector = QUALITY_FORMATS.get(quality, QUALITY_FORMATS[DEFAULT_QUALITY])

    command = [
        binary,
        "--no-playlist",
        "--no-warnings",
        "--newline",
        "-f", selector,
        # One container the browser can actually play, whatever the source streams were.
        "--merge-output-format", "mp4",
        "-o", str(folder / f"{value}.%(ext)s"),
        f"https://www.youtube.com/watch?v={value}",
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise MediaArchiveError(f"Could not run yt-dlp: {exc}") from exc

    tail: list[str] = []
    try:
        for line in process.stdout or []:
            line = line.strip()
            if not line:
                continue
            tail = [*tail[-4:], line]
            if on_progress and "%" in line:
                on_progress(line)
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise MediaArchiveError(f"Archiving timed out after {timeout_seconds}s") from exc
    finally:
        if process.stdout:
            process.stdout.close()

    if process.returncode != 0:
        raise MediaArchiveError(tail[-1] if tail else f"yt-dlp exited {process.returncode}")

    stored = archived_path(value)
    if stored is None:
        raise MediaArchiveError("yt-dlp finished but no video file was produced")
    return stored


def remove_archived(video_id: str) -> bool:
    """Delete the stored file. Returns whether there was one."""
    path = archived_path(video_id)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError as exc:
        raise MediaArchiveError(f"Could not delete {path.name}: {exc}") from exc
    return True


def missing_from_archive(video_ids: Iterable[str]) -> list[str]:
    stored = archived_video_ids()
    return [str(v) for v in video_ids if str(v) not in stored]

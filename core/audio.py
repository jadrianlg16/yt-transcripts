"""Pull a video's audio down so it can be transcribed.

Only used on the Whisper path, which is the fallback for videos YouTube publishes
no captions for. Nothing here runs during a normal caption fetch.

This uses yt-dlp directly rather than driving the separate downloader app. That app
queues by URL and its API returns no handle for the item you just queued, so there
is no reliable way to wait for your own download. For "download this video to keep",
the downloader remains the right tool and the UI links out to it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 900
AUDIO_FORMAT = "m4a"


class AudioDownloadError(RuntimeError):
    pass


def ytdlp_path() -> str | None:
    return os.getenv("YT_TRANSCRIPTS_YTDLP", "").strip() or shutil.which("yt-dlp")


def audio_available() -> bool:
    return bool(ytdlp_path())


def download_audio(
    video_id: str,
    destination_dir: str | Path | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Download just the audio track and return the file path.

    The caller owns the file and should delete it; audio for a long talk is tens of
    megabytes and there is no reason to keep it once the words are stored.
    """
    binary = ytdlp_path()
    if not binary:
        raise AudioDownloadError(
            "yt-dlp is not installed, so audio cannot be downloaded for transcription"
        )

    folder = Path(destination_dir) if destination_dir else Path(tempfile.mkdtemp(prefix="yt-audio-"))
    folder.mkdir(parents=True, exist_ok=True)
    template = str(folder / f"{video_id}.%(ext)s")

    command = [
        binary,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", AUDIO_FORMAT,
        "-o", template,
        f"https://www.youtube.com/watch?v={video_id}",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioDownloadError(f"Audio download timed out after {timeout_seconds}s") from exc
    except OSError as exc:
        raise AudioDownloadError(f"Could not run yt-dlp: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise AudioDownloadError(detail[-1] if detail else f"yt-dlp exited {result.returncode}")

    produced = sorted(folder.glob(f"{video_id}.*"))
    if not produced:
        raise AudioDownloadError("yt-dlp reported success but produced no audio file")
    return str(produced[0])


def discard_audio(path: str | Path) -> None:
    """Remove a downloaded file, and its temp folder if we made one."""
    target = Path(path)
    try:
        target.unlink(missing_ok=True)
        parent = target.parent
        if parent.name.startswith("yt-audio-") and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass

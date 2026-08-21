"""Export the archive as a folder of linked Markdown notes.

The database stays the source of truth; this is a readable copy for tools like
Obsidian. Every note carries the video's facts up top, the transcript with clickable
timestamps, and wiki-links to the videos that share its subjects.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from core.topics import build_topic_model, related_videos, video_topics

ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\|?*\x00-\x1f]')
MAX_TITLE_LENGTH = 90


def note_name(entry: dict[str, Any]) -> str:
    """A filename that is stable, readable, and unique per video."""
    title = ILLEGAL_FILENAME_CHARS.sub("", str(entry.get("title") or "")).strip()
    title = re.sub(r"\s+", " ", title).rstrip(". ")[:MAX_TITLE_LENGTH].strip()
    video_id = str(entry.get("video_id") or "unknown")
    return f"{title} ({video_id})" if title else video_id


def _timecode(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _watch_url(entry: dict[str, Any], start: Any = None) -> str:
    base = str(entry.get("source_url") or "").strip()
    if not base:
        base = f"https://www.youtube.com/watch?v={entry.get('video_id')}"
    if start is None:
        return base
    try:
        offset = max(0, int(float(start or 0)))
    except (TypeError, ValueError):
        offset = 0
    return f"{base}{'&' if '?' in base else '?'}t={offset}s"


def _yaml_escape(value: Any) -> str:
    return '"' + str(value or "").replace('"', "'") + '"'


def _paragraphs(segments: list[dict[str, Any]], per_block: int = 16) -> list[tuple[Any, str]]:
    """Group caption fragments into readable blocks, keeping each block's start."""
    blocks: list[tuple[Any, str]] = []
    for index in range(0, len(segments), per_block):
        window = segments[index : index + per_block]
        text = " ".join(str(s.get("text") or "").strip() for s in window).strip()
        if text:
            blocks.append((window[0].get("start", 0), text))
    return blocks


def render_note(
    entry: dict[str, Any],
    topics: list[dict[str, Any]],
    related: list[dict[str, Any]],
    entries_by_id: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "---",
        f"title: {_yaml_escape(entry.get('title'))}",
        f"channel: {_yaml_escape(entry.get('channel'))}",
        f"video_id: {_yaml_escape(entry.get('video_id'))}",
        f"url: {_yaml_escape(_watch_url(entry))}",
        f"saved: {_yaml_escape(entry.get('saved_at'))}",
    ]
    if topics:
        lines.append("tags:")
        for item in topics:
            tag = re.sub(r"[^a-z0-9]+", "-", str(item["topic"]).lower()).strip("-")
            if tag:
                lines.append(f"  - {tag}")
    lines += ["---", "", f"# {entry.get('title') or entry.get('video_id')}", ""]
    lines.append(f"[{entry.get('channel') or 'Unknown channel'}]  ·  [Watch]({_watch_url(entry)})")
    lines.append("")

    if related:
        lines += ["## Related", ""]
        for item in related:
            other = entries_by_id.get(item["video_id"])
            if not other:
                continue
            shared = ", ".join(item["shared_topics"][:4])
            lines.append(f"- [[{note_name(other)}]]" + (f" — {shared}" if shared else ""))
        lines.append("")

    lines += ["## Transcript", ""]
    segments = [s for s in (entry.get("segments") or []) if isinstance(s, dict)]
    if segments:
        for start, text in _paragraphs(segments):
            lines.append(f"**[{_timecode(start)}]({_watch_url(entry, start)})** {text}")
            lines.append("")
    else:
        lines += [str(entry.get("transcript") or ""), ""]

    return "\n".join(lines).rstrip() + "\n"


def render_index(entries: list[dict[str, Any]], topics: list[dict[str, Any]]) -> str:
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_channel.setdefault(str(entry.get("channel") or "Unknown channel"), []).append(entry)

    lines = ["# Transcript Archive", "", f"{len(entries)} videos across {len(by_channel)} channels.", ""]
    if topics:
        lines += ["## Recurring subjects", ""]
        for topic in topics[:20]:
            lines.append(f"- **{topic['topic']}** — {topic['video_count']} videos")
        lines.append("")

    for channel in sorted(by_channel):
        channel_entries = by_channel[channel]
        lines += [f"## {channel} ({len(channel_entries)})", ""]
        for entry in sorted(channel_entries, key=lambda e: str(e.get("saved_at") or ""), reverse=True):
            lines.append(f"- [[{note_name(entry)}]]")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_vault(
    entries: Iterable[dict[str, Any]],
    destination: str | Path,
    topics_per_video: int = 8,
    related_per_video: int = 6,
) -> dict[str, Any]:
    """Write one Markdown note per video plus an index, and report what was written."""
    entries = [e for e in entries if e.get("video_id")]
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)

    model = build_topic_model(entries, topics_per_video=topics_per_video)
    entries_by_id = {str(e["video_id"]): e for e in entries}

    written = 0
    for entry in entries:
        video_id = str(entry["video_id"])
        note = render_note(
            entry,
            video_topics(model, video_id),
            related_videos(model, video_id, entries_by_id, limit=related_per_video),
            entries_by_id,
        )
        (folder / f"{note_name(entry)}.md").write_text(note, encoding="utf-8")
        written += 1

    index_topics = top_topics_for_index(model)
    (folder / "Index.md").write_text(render_index(entries, index_topics), encoding="utf-8")

    return {"path": str(folder.resolve()), "notes": written, "index": "Index.md"}


def top_topics_for_index(model: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    from core.topics import top_topics

    return top_topics(model, limit=limit)

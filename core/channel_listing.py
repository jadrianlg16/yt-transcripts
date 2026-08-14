"""Channel video listing straight from the channel page.

YouTube's RSS feed only ever returns the 15 newest uploads, which is not enough to
backfill an archive. scrapetube used to cover the deeper case, but it looks for
``videoRenderer`` entries and YouTube now renders channel grids with
``lockupViewModel``, so it silently yields nothing. This module reads the channel
page's ``ytInitialData`` directly and follows continuation tokens for depth.

Only public listing metadata is read: video id, title, and the relative publish
text. Requests are paced and capped so a deep walk stays polite.
"""

from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Iterator

import requests

INITIAL_DATA_MARKER = "var ytInitialData = "
BROWSE_ENDPOINT = "https://www.youtube.com/youtubei/v1/browse"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# A deep walk is ~30 videos per request; this bounds a runaway continuation loop.
MAX_CONTINUATION_PAGES = 40
DEFAULT_SLEEP_SECONDS = 1.0
PUBLISHED_TEXT_PATTERN = re.compile(
    r"^\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE
)


class ChannelListingError(RuntimeError):
    pass


def _walk(node: Any, key: str) -> Iterator[Any]:
    if isinstance(node, dict):
        for node_key, value in node.items():
            if node_key == key:
                yield value
            yield from _walk(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, key)


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.headers["Accept-Language"] = "en-US,en;q=0.9"
    return session


def channel_tab_url(channel: str, tab: str) -> str:
    """Build a channel tab URL from a handle, /channel/ URL, or bare channel id."""
    value = channel.strip().rstrip("/")
    if not value:
        raise ChannelListingError("Channel URL is required")

    if re.fullmatch(r"UC[A-Za-z0-9_-]{20,}", value):
        return f"https://www.youtube.com/channel/{value}/{tab}"

    if value.startswith("@"):
        value = f"https://www.youtube.com/{value}"
    elif "://" not in value:
        value = f"https://{value}" if value.startswith("youtube.com") else f"https://www.youtube.com/{value}"

    for suffix in ("/videos", "/streams", "/shorts", "/featured"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break

    return f"{value}/{tab}"


def _parse_initial_data(page_html: str) -> dict[str, Any]:
    marker_index = page_html.find(INITIAL_DATA_MARKER)
    if marker_index == -1:
        raise ChannelListingError("Channel page did not include ytInitialData")

    start = marker_index + len(INITIAL_DATA_MARKER)
    try:
        return json.JSONDecoder().raw_decode(page_html[start:])[0]
    except json.JSONDecodeError as exc:
        raise ChannelListingError(f"Could not decode ytInitialData: {exc}") from exc


def _regex_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _client_context(page_html: str) -> dict[str, str]:
    return {
        "api_key": _regex_group(r'"INNERTUBE_API_KEY":"([^"]+)"', page_html),
        "client_version": _regex_group(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page_html),
    }


def _published_text(metadata: dict[str, Any]) -> str:
    """Pull the '3 days ago' part out of the '12K views • 3 days ago' metadata row."""
    for part in _walk(metadata, "metadataParts"):
        if not isinstance(part, list):
            continue
        for item in part:
            content = str(((item or {}).get("text") or {}).get("content") or "").strip()
            if PUBLISHED_TEXT_PATTERN.match(content):
                return content
    return ""


def _video_from_lockup(lockup: dict[str, Any]) -> dict[str, str] | None:
    if lockup.get("contentType") not in (None, "LOCKUP_CONTENT_TYPE_VIDEO"):
        return None

    video_id = str(lockup.get("contentId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None

    metadata = (lockup.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = str((metadata.get("title") or {}).get("content") or "").strip()
    return {
        "videoId": video_id,
        "title": html.unescape(title),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "published_text": _published_text(metadata),
    }


def _video_from_renderer(renderer: dict[str, Any]) -> dict[str, str] | None:
    """Legacy grid format. Still served to some clients, so keep reading it."""
    video_id = str(renderer.get("videoId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None

    title_node = renderer.get("title") or {}
    runs = title_node.get("runs")
    title = (
        str(runs[0].get("text") or "").strip()
        if isinstance(runs, list) and runs
        else str(title_node.get("simpleText") or "").strip()
    )
    published = renderer.get("publishedTimeText") or {}
    return {
        "videoId": video_id,
        "title": html.unescape(title),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "published_text": str(published.get("simpleText") or "").strip(),
    }


def _videos_from_data(data: dict[str, Any]) -> list[dict[str, str]]:
    videos: list[dict[str, str]] = []
    for lockup in _walk(data, "lockupViewModel"):
        if isinstance(lockup, dict):
            video = _video_from_lockup(lockup)
            if video:
                videos.append(video)

    if not videos:
        for renderer in _walk(data, "videoRenderer"):
            if isinstance(renderer, dict):
                video = _video_from_renderer(renderer)
                if video:
                    videos.append(video)

    return videos


def _continuation_token(data: dict[str, Any]) -> str | None:
    """Only the grid's own 'load more' token, not shelf or sidebar continuations."""
    for renderer in _walk(data, "continuationItemRenderer"):
        if not isinstance(renderer, dict):
            continue
        token = (
            ((renderer.get("continuationEndpoint") or {}).get("continuationCommand") or {}).get("token")
        )
        if token:
            return str(token)
    return None


def list_channel_videos(
    channel: str,
    limit: int | None = None,
    tabs: tuple[str, ...] = ("videos", "streams"),
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Newest-first video listing for a channel, across the given tabs.

    ``limit`` of ``None`` walks every continuation page up to
    ``MAX_CONTINUATION_PAGES``. Results are deduplicated by video id.
    """
    owns_session = session is None
    session = session or _new_session()
    collected: list[dict[str, str]] = []
    seen: set[str] = set()
    errors: list[str] = []

    try:
        for tab in tabs:
            if limit is not None and len(collected) >= limit:
                break

            try:
                page_url = channel_tab_url(channel, tab)
                response = session.get(page_url, timeout=20)
                response.raise_for_status()
                page_html = response.text
                data = _parse_initial_data(page_html)
            except (requests.RequestException, ChannelListingError) as exc:
                errors.append(f"{tab}: {exc}")
                continue

            context = _client_context(page_html)
            pages = 0

            while True:
                for video in _videos_from_data(data):
                    if video["videoId"] in seen:
                        continue
                    seen.add(video["videoId"])
                    collected.append(video)
                    if limit is not None and len(collected) >= limit:
                        break

                if limit is not None and len(collected) >= limit:
                    break

                token = _continuation_token(data)
                pages += 1
                if not token or pages >= MAX_CONTINUATION_PAGES:
                    break
                if not context["api_key"] or not context["client_version"]:
                    errors.append(f"{tab}: missing InnerTube context for continuation")
                    break

                time.sleep(sleep_seconds)
                try:
                    data = _browse_continuation(session, context, token)
                except (requests.RequestException, ChannelListingError) as exc:
                    errors.append(f"{tab} continuation: {exc}")
                    break
    finally:
        if owns_session:
            session.close()

    if not collected and errors:
        raise ChannelListingError("; ".join(errors))
    return collected


def _browse_continuation(
    session: requests.Session,
    context: dict[str, str],
    token: str,
) -> dict[str, Any]:
    response = session.post(
        BROWSE_ENDPOINT,
        params={"key": context["api_key"], "prettyPrint": "false"},
        json={
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": context["client_version"],
                    "hl": "en",
                }
            },
            "continuation": token,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()

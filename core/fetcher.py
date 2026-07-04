import re
import html
import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

def extract_video_id(url: str):
    value = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    if "://" not in value and (
        value.startswith("youtube.com")
        or value.startswith("www.youtube.com")
        or value.startswith("m.youtube.com")
        or value.startswith("youtu.be")
    ):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    def valid_video_id(video_id):
        return video_id if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or "") else None

    if host == "youtu.be":
        return valid_video_id(parsed.path.strip("/").split("/")[0])

    if host == "youtube.com" or host.endswith(".youtube.com"):
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id:
            return valid_video_id(video_id)

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
            return valid_video_id(path_parts[1])

    return None

def _segment_to_dict(item):
    if isinstance(item, dict):
        return {
            "text": item.get("text", ""),
            "start": item.get("start", 0),
            "duration": item.get("duration", 0),
        }

    return {
        "text": getattr(item, "text", ""),
        "start": getattr(item, "start", 0),
        "duration": getattr(item, "duration", 0),
    }

def fetch_transcript(video_id: str, languages=None):
    from youtube_transcript_api import YouTubeTranscriptApi

    preferred_languages = list(languages or ["en"])
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)
    try: transcript = transcript_list.find_transcript(preferred_languages)
    except: transcript = next(iter(transcript_list))
    items = transcript.fetch()
    segments = [_segment_to_dict(i) for i in items]
    return segments, " ".join(s["text"] for s in segments)


def _decode_youtube_text(value: str | None) -> str:
    text = str(value or "")
    if "\\u" in text:
        text = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda match: chr(int(match.group(1), 16)),
            text,
        )
    return html.unescape(text.replace("\\/", "/")).strip()


def _json_object_after_marker(text: str, marker: str):
    marker_index = text.find(marker)
    if marker_index == -1:
        return None

    object_start = text.find("{", marker_index)
    if object_start == -1:
        return None

    try:
        return json.JSONDecoder().raw_decode(text[object_start:])[0]
    except json.JSONDecodeError:
        return None


def _metadata_from_html(html_text: str) -> dict:
    player_response = _json_object_after_marker(html_text, "ytInitialPlayerResponse")
    video_details = player_response.get("videoDetails", {}) if isinstance(player_response, dict) else {}
    microformat = (
        player_response.get("microformat", {}).get("playerMicroformatRenderer", {})
        if isinstance(player_response, dict)
        else {}
    )

    title = (
        video_details.get("title")
        or microformat.get("title", {}).get("simpleText")
        or _regex_group(r'<meta name="title" content="([^"]+)"', html_text)
        or _regex_group(r'<meta property="og:title" content="([^"]+)"', html_text)
        or _regex_group(r"<title>(.*?)</title>", html_text)
        or "Unknown Title"
    )
    title = _decode_youtube_text(str(title).replace(" - YouTube", ""))

    channel = (
        video_details.get("author")
        or microformat.get("ownerChannelName")
        or _regex_group(r'"ownerChannelName":"(.*?)"', html_text)
        or "Unknown Channel"
    )
    channel = _decode_youtube_text(channel)

    uploaded_at = (
        microformat.get("publishDate")
        or microformat.get("uploadDate")
        or _regex_group(r'<meta itemprop="datePublished" content="([^"]+)"', html_text)
        or _regex_group(r'<meta property="og:video:release_date" content="([^"]+)"', html_text)
        or ""
    )
    uploaded_at = _decode_youtube_text(uploaded_at)

    return {
        "title": title or "Unknown Title",
        "channel": channel or "Unknown Channel",
        "uploaded_at": uploaded_at,
    }


def _regex_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def fetch_metadata_details(video_id: str):
    import requests

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=h, timeout=10)
        return _metadata_from_html(r.text)
    except Exception:
        pass
    return {"title": "Unknown Title", "channel": "Unknown Channel", "uploaded_at": ""}


def fetch_metadata(video_id: str):
    metadata = fetch_metadata_details(video_id)
    title = metadata["title"]
    channel = metadata["channel"]
    return title, channel

def fetch_video_full(v_id, languages=None):
    items, text = fetch_transcript(v_id, languages=languages)
    metadata = fetch_metadata_details(v_id)
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    uploaded_at = metadata.get("uploaded_at") or fetched_at
    entry = {
        "video_id": v_id,
        "title": metadata["title"],
        "channel": metadata["channel"],
        "saved_at": uploaded_at,
        "uploaded_at": uploaded_at,
        "fetched_at": fetched_at,
        "source_url": f"https://www.youtube.com/watch?v={v_id}",
        "transcript": text,
        "segments": items
    }
    return entry

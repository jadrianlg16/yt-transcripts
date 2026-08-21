"""Topics and connections between videos, worked out from the words themselves.

No model required. A term matters for a video when that video uses it a lot and the
rest of the archive does not, which is enough to answer "what is this one about" and
"what else covers the same ground".
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable

from core.research import STOP_WORDS, _stem, words

DEFAULT_TOPICS_PER_VIDEO = 10
DEFAULT_RELATED_LIMIT = 8
# A term in nearly every video says nothing about any single one of them.
MAX_DOCUMENT_SHARE = 0.5
MIN_TERM_LENGTH = 3

# Talking filler. Common in every transcript and about nothing, but not general
# enough for the search stop-word list, which is tuned for written queries.
SPOKEN_FILLER = {
    "actually", "alright", "anyway", "basically", "blah", "essentially", "everybody",
    "everyone", "exactly", "gonna", "guys", "honestly", "kind", "kinda", "literally",
    "maybe", "obviously", "okay", "pretty", "probably", "quite", "sort", "sorta",
    "stuff", "thing", "things", "think", "today", "totally", "video", "videos",
    "yeah", "anyways", "actual", "little", "for", "need", "needs", "needed", "lot", "bit", "way", "ways", "come", "comes",
    "going", "goes", "say", "says", "saying", "see", "seen", "let", "lets",
    "much", "many", "well", "good", "great", "big", "new", "now", "even", "still",
    "back", "sure", "here", "very", "able", "one", "two", "three", "first",
    "second", "next", "last", "why", "how", "who", "does", "did", "done",
    "subscribe", "channel", "watch", "watching", "talk", "talking", "talked",
}


def _common_term_threshold(total: int) -> int:
    """How many videos a term may appear in before it stops being distinctive.

    Never below two, or a small archive throws away the very words its videos have
    in common, which are the ones worth linking on.
    """
    return max(2, int(total * MAX_DOCUMENT_SHARE))


def _usable_terms(text: str) -> list[str]:
    return [
        word
        for word in words(text)
        if len(word) >= MIN_TERM_LENGTH
        and word not in STOP_WORDS
        and word not in SPOKEN_FILLER
    ]


def _entry_text(entry: dict[str, Any]) -> str:
    return f"{entry.get('title') or ''} {entry.get('transcript') or ''}"


def _term_counts(entry: dict[str, Any]) -> Counter[str]:
    """Counts by stem, remembering the most common spelling for display."""
    counts: Counter[str] = Counter()
    for word in _usable_terms(_entry_text(entry)):
        counts[_stem(word)] += 1
    return counts


def _display_forms(entries: Iterable[dict[str, Any]]) -> dict[str, str]:
    variants: dict[str, Counter[str]] = {}
    for entry in entries:
        for word in _usable_terms(_entry_text(entry)):
            variants.setdefault(_stem(word), Counter())[word] += 1
    return {stem: counter.most_common(1)[0][0] for stem, counter in variants.items()}


def build_topic_model(
    entries: Iterable[dict[str, Any]],
    topics_per_video: int = DEFAULT_TOPICS_PER_VIDEO,
) -> dict[str, Any]:
    """Score every video's distinctive terms against the rest of the archive."""
    entries = [entry for entry in entries if entry.get("video_id")]
    if not entries:
        return {"videos": {}, "topics": {}, "labels": {}, "video_count": 0}

    counts_by_video = {str(e["video_id"]): _term_counts(e) for e in entries}
    labels = _display_forms(entries)
    total = len(entries)

    document_frequency: Counter[str] = Counter()
    for counts in counts_by_video.values():
        document_frequency.update(counts.keys())

    videos: dict[str, list[dict[str, Any]]] = {}
    topics: dict[str, list[str]] = {}
    for video_id, counts in counts_by_video.items():
        longest = max(counts.values(), default=1)
        scored: list[tuple[float, str]] = []
        for stem, count in counts.items():
            appears_in = document_frequency[stem]
            if appears_in > _common_term_threshold(total):
                continue
            # Frequent here, rare elsewhere.
            weight = (count / longest) * math.log(total / appears_in + 1)
            scored.append((weight, stem))

        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen = scored[:topics_per_video]
        videos[video_id] = [
            {"topic": labels.get(stem, stem), "stem": stem, "weight": round(weight, 4)}
            for weight, stem in chosen
        ]
        for _, stem in chosen:
            topics.setdefault(stem, []).append(video_id)

    return {"videos": videos, "topics": topics, "labels": labels, "video_count": total}


def video_topics(model: dict[str, Any], video_id: str) -> list[dict[str, Any]]:
    return model.get("videos", {}).get(str(video_id), [])


def top_topics(model: dict[str, Any], limit: int = 25) -> list[dict[str, Any]]:
    """Topics that tie the most videos together."""
    ranked = sorted(
        model.get("topics", {}).items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return [
        {
            "topic": model.get("labels", {}).get(stem, stem),
            "stem": stem,
            "video_count": len(video_ids),
            "video_ids": video_ids,
        }
        for stem, video_ids in ranked[:limit]
        if len(video_ids) > 1
    ]


def related_videos(
    model: dict[str, Any],
    video_id: str,
    entries_by_id: dict[str, dict[str, Any]],
    limit: int = DEFAULT_RELATED_LIMIT,
) -> list[dict[str, Any]]:
    """Other videos covering the same ground, and which topics they share."""
    source = {item["stem"]: item["weight"] for item in video_topics(model, video_id)}
    if not source:
        return []

    labels = model.get("labels", {})
    scores: dict[str, dict[str, Any]] = {}
    for stem, weight in source.items():
        for other_id in model.get("topics", {}).get(stem, []):
            if other_id == str(video_id):
                continue
            bucket = scores.setdefault(other_id, {"score": 0.0, "shared": []})
            other_weight = next(
                (i["weight"] for i in video_topics(model, other_id) if i["stem"] == stem),
                0.0,
            )
            bucket["score"] += weight * other_weight
            bucket["shared"].append(labels.get(stem, stem))

    ranked = sorted(scores.items(), key=lambda item: (-item[1]["score"], item[0]))
    results = []
    for other_id, bucket in ranked[:limit]:
        entry = entries_by_id.get(other_id, {})
        results.append({
            "video_id": other_id,
            "title": entry.get("title") or other_id,
            "channel": entry.get("channel") or "",
            "shared_topics": bucket["shared"],
            "score": round(bucket["score"], 4),
        })
    return results

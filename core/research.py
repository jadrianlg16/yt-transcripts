import re
from collections import Counter
from typing import Any, Iterable

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9']+")

STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "being",
    "before",
    "between",
    "could",
    "doesn't",
    "does",
    "don't",
    "doing",
    "from",
    "getting",
    "going",
    "have",
    "into",
    "it's",
    "just",
    "know",
    "like",
    "look",
    "make",
    "more",
    "most",
    "over",
    "people",
    "really",
    "right",
    "same",
    "should",
    "something",
    "that's",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "want",
    "you're",
    "your",
}


def words(text: str) -> list[str]:
    return WORD_RE.findall((text or "").lower())


def _stem(word: str) -> str:
    word = word.lower()
    if len(word) <= 4:
        return word

    for suffix, min_length in (
        ("ization", 9),
        ("ational", 9),
        ("fulness", 8),
        ("ousness", 8),
        ("iveness", 8),
        ("tional", 8),
        ("ing", 6),
        ("edly", 7),
        ("ed", 5),
        ("ies", 6),
        ("es", 5),
        ("s", 5),
    ):
        if len(word) >= min_length and word.endswith(suffix):
            if suffix == "ies":
                return word[: -len(suffix)] + "y"
            return word[: -len(suffix)]

    return word


def _keyword_tokens(text: str) -> list[tuple[str, str]]:
    tokens = []
    for word in words(text):
        if len(word) <= 3 or word in STOP_WORDS:
            continue
        stem = _stem(word)
        if len(stem) <= 2 or stem in STOP_WORDS:
            continue
        tokens.append((stem, word))
    return tokens


def _representative_terms(variants: dict[str, Counter[str]]) -> dict[str, str]:
    return {
        stem: sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for stem, counter in variants.items()
    }


def _top_keyword_counts(entries: Iterable[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    unigram_counts: Counter[str] = Counter()
    phrase_counts: Counter[str] = Counter()
    unigram_variants: dict[str, Counter[str]] = {}
    phrase_variants: dict[str, Counter[str]] = {}

    for entry in entries:
        tokens = _keyword_tokens(entry.get("transcript") or "")
        for stem, word in tokens:
            unigram_counts[stem] += 1
            unigram_variants.setdefault(stem, Counter())[word] += 1

        for (left_stem, left_word), (right_stem, right_word) in zip(tokens, tokens[1:]):
            if left_stem == right_stem:
                continue
            phrase_stem = f"{left_stem} {right_stem}"
            phrase = f"{left_word} {right_word}"
            phrase_counts[phrase_stem] += 1
            phrase_variants.setdefault(phrase_stem, Counter())[phrase] += 1

    unigram_terms = _representative_terms(unigram_variants)
    phrase_terms = _representative_terms(phrase_variants)
    candidates = [
        {"term": unigram_terms[stem], "count": count}
        for stem, count in unigram_counts.items()
    ]
    candidates.extend(
        {"term": phrase_terms[stem], "count": count}
        for stem, count in phrase_counts.items()
        if count > 1 or count >= unigram_counts.get(stem.split()[0], 0)
    )

    return sorted(
        candidates,
        key=lambda item: (-item["count"], -len(item["term"].split()), item["term"]),
    )[:limit]


def segment_duration(entry: dict[str, Any]) -> float:
    segments = entry.get("segments") or []
    if not segments:
        return 0

    return max(
        (float(segment.get("start", 0) or 0) + float(segment.get("duration", 0) or 0))
        for segment in segments
    )


def entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    transcript = entry.get("transcript") or ""
    segments = entry.get("segments") or []

    return {
        "video_id": entry.get("video_id", ""),
        "title": entry.get("title") or "Untitled Video",
        "channel": entry.get("channel") or "Unknown Channel",
        "saved_at": entry.get("saved_at") or "",
        "word_count": len(words(transcript)),
        "segment_count": len(segments),
        "duration_seconds": round(segment_duration(entry), 2),
    }


def library_stats(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = list(entries)
    summaries = [entry_summary(entry) for entry in entries]
    channels = Counter(summary["channel"] for summary in summaries)

    return {
        "transcript_count": len(summaries),
        "unique_channels": len(channels),
        "total_words": sum(summary["word_count"] for summary in summaries),
        "total_segments": sum(summary["segment_count"] for summary in summaries),
        "total_duration_seconds": round(
            sum(summary["duration_seconds"] for summary in summaries),
            2,
        ),
        "latest_saved_at": max((summary["saved_at"] for summary in summaries), default=""),
        "channel_counts": [
            {"channel": channel, "count": count}
            for channel, count in channels.most_common()
        ],
        "top_keywords": _top_keyword_counts(entries),
    }


def _text_matches(text: str, terms: list[str], phrase: str) -> bool:
    normalized = (text or "").lower()
    return phrase in normalized or all(term in normalized for term in terms)


def _count_term_hits(text: str, terms: list[str], phrase: str) -> int:
    normalized = (text or "").lower()
    phrase_hits = normalized.count(phrase)
    term_hits = sum(normalized.count(term) for term in terms)
    return phrase_hits * 3 + term_hits


def search_entries(
    entries: Iterable[dict[str, Any]],
    query: str,
    channel: str | None = None,
    limit: int = 50,
    matches_per_entry: int = 4,
    sort: str = "relevance",
) -> list[dict[str, Any]]:
    phrase = " ".join((query or "").lower().split())
    if len(phrase) < 2:
        return []

    terms = [term for term in words(phrase) if len(term) > 1]
    if not terms:
        return []

    channel_filter = (channel or "").strip().lower()
    results: list[dict[str, Any]] = []

    for entry in entries:
        entry_channel = entry.get("channel") or "Unknown Channel"
        if channel_filter and entry_channel.lower() != channel_filter:
            continue

        title = entry.get("title") or "Untitled Video"
        transcript = entry.get("transcript") or ""
        title_hit = _text_matches(title, terms, phrase)
        transcript_hit = _text_matches(transcript, terms, phrase)

        matches = []
        match_count = 0
        for segment in entry.get("segments") or []:
            text = segment.get("text") or ""
            if _text_matches(text, terms, phrase):
                match_count += 1
                if len(matches) < matches_per_entry:
                    matches.append(
                        {
                            "text": text,
                            "start": float(segment.get("start", 0) or 0),
                            "duration": float(segment.get("duration", 0) or 0),
                        }
                    )

        if not title_hit and not transcript_hit and not matches:
            continue

        score = 0
        if title_hit:
            score += 100
        score += _count_term_hits(transcript, terms, phrase)
        score += len(matches) * 10

        results.append(
            {
                "video_id": entry.get("video_id", ""),
                "title": title,
                "channel": entry_channel,
                "saved_at": entry.get("saved_at") or "",
                "word_count": len(words(transcript)),
                "duration_seconds": round(segment_duration(entry), 2),
                "match_count": match_count,
                "score": score,
                "matches": matches,
            }
        )

    sort_key = (sort or "relevance").lower()
    if sort_key == "newest":
        ordered = sorted(
            results,
            key=lambda result: (result["saved_at"], result["score"]),
            reverse=True,
        )
    elif sort_key == "longest":
        ordered = sorted(
            results,
            key=lambda result: (
                result["duration_seconds"],
                result["word_count"],
                result["score"],
            ),
            reverse=True,
        )
    elif sort_key == "matches":
        ordered = sorted(
            results,
            key=lambda result: (result["match_count"], result["score"], result["saved_at"]),
            reverse=True,
        )
    elif sort_key == "title":
        ordered = sorted(
            results,
            key=lambda result: (result["title"].lower(), result["saved_at"]),
        )
    else:
        ordered = sorted(
            results,
            key=lambda result: (result["score"], result["saved_at"]),
            reverse=True,
        )

    return ordered[: max(1, min(limit, 100))]

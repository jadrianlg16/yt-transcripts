import os
import tempfile
import unittest

from core.semantic_search import (
    build_semantic_index,
    chunk_transcript,
    compute_transcript_hash,
    cosine_similarity,
    detect_stale_transcripts,
    load_semantic_index,
    rebuild_semantic_index,
    search_semantic_index,
    stale_transcript_ids,
)


INDEXED_AT = "2026-05-12T12:00:00Z"


def sample_entry(video_id, title, segments, transcript=None):
    return {
        "video_id": video_id,
        "title": title,
        "channel": "Stage 6",
        "saved_at": "2026-05-12 12:00",
        "uploaded_at": "2026-05-01 09:00",
        "transcript": transcript or " ".join(segment["text"] for segment in segments),
        "segments": segments,
    }


def segment(text, start, duration=5.0):
    return {
        "text": text,
        "start": start,
        "duration": duration,
    }


def topic_embedder(text):
    normalized = text.lower()
    return [
        float("retrieval" in normalized or "semantic" in normalized),
        float("storage" in normalized or "sqlite" in normalized),
        float("workflow" in normalized or "review" in normalized),
    ]


class Stage6ChunkingTests(unittest.TestCase):
    def test_chunk_transcript_groups_segment_windows_with_metadata(self):
        entry = sample_entry(
            "alpha000001",
            "Semantic Search",
            [
                segment("semantic retrieval", 0),
                segment("vector ranking", 5),
                segment("sqlite storage", 10),
                segment("review workflow", 15),
                segment("final notes", 20),
            ],
        )

        chunks = chunk_transcript(entry, segments_per_chunk=2)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["video_id"], "alpha000001")
        self.assertEqual(chunks[0]["title"], "Semantic Search")
        self.assertEqual(chunks[0]["channel"], "Stage 6")
        self.assertEqual(chunks[0]["start"], 0)
        self.assertEqual(chunks[0]["end"], 10)
        self.assertEqual(chunks[0]["text"], "semantic retrieval vector ranking")
        self.assertEqual(chunks[0]["chunk_index"], 0)
        self.assertEqual(chunks[2]["start"], 20)
        self.assertEqual(chunks[2]["end"], 25)
        self.assertEqual(chunks[2]["chunk_index"], 2)

    def test_chunk_transcript_supports_overlapping_windows_without_duplicate_tail(self):
        entry = sample_entry(
            "beta0000002",
            "Overlap",
            [
                segment("one", 0),
                segment("two", 5),
                segment("three", 10),
                segment("four", 15),
                segment("five", 20),
            ],
        )

        chunks = chunk_transcript(entry, segments_per_chunk=3, segment_overlap=1)

        self.assertEqual([chunk["text"] for chunk in chunks], [
            "one two three",
            "three four five",
        ])


class Stage6RebuildTests(unittest.TestCase):
    def test_rebuild_writes_json_index_with_model_hash_vector_and_timestamp(self):
        entries = [
            sample_entry(
                "alpha000001",
                "Semantic Retrieval",
                [segment("semantic retrieval", 0), segment("vector search", 5)],
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "semantic_index.json")

            index = rebuild_semantic_index(
                entries,
                topic_embedder,
                path=path,
                embedding_model="test-embedder",
                segments_per_chunk=1,
                indexed_at=INDEXED_AT,
            )
            loaded = load_semantic_index(path)

        self.assertEqual(index, loaded)
        self.assertEqual(index["embedding_model"], "test-embedder")
        self.assertEqual(index["chunking"]["segments_per_chunk"], 1)
        self.assertEqual(len(index["items"]), 2)
        first = index["items"][0]
        self.assertEqual(first["embedding_model"], "test-embedder")
        self.assertEqual(first["transcript_hash"], compute_transcript_hash(entries[0]))
        self.assertEqual(first["vector"], [1.0, 0.0, 0.0])
        self.assertEqual(first["indexed_at"], INDEXED_AT)


class Stage6StalenessTests(unittest.TestCase):
    def test_detect_stale_transcripts_reports_hash_mismatches(self):
        original = sample_entry(
            "alpha000001",
            "Semantic Retrieval",
            [segment("semantic retrieval", 0), segment("vector search", 5)],
        )
        changed = sample_entry(
            "alpha000001",
            "Semantic Retrieval",
            [segment("semantic retrieval changed", 0), segment("vector search", 5)],
        )
        index = build_semantic_index(
            [original],
            topic_embedder,
            embedding_model="test-embedder",
            segments_per_chunk=2,
            indexed_at=INDEXED_AT,
        )

        self.assertEqual(detect_stale_transcripts([original], index=index), [])
        stale = detect_stale_transcripts([changed], index=index)

        self.assertEqual(stale[0]["video_id"], "alpha000001")
        self.assertEqual(stale[0]["reason"], "hash_mismatch")
        self.assertEqual(stale_transcript_ids([changed], index=index), ["alpha000001"])

    def test_detect_stale_transcripts_reports_missing_entries(self):
        entry = sample_entry(
            "missing0001",
            "Missing",
            [segment("semantic retrieval", 0)],
        )

        stale = detect_stale_transcripts([entry], index={"items": []})

        self.assertEqual(stale[0]["reason"], "missing")


class Stage6SearchTests(unittest.TestCase):
    def test_cosine_similarity_and_search_rank_nearest_vectors_first(self):
        entries = [
            sample_entry("retrieval1", "Retrieval", [segment("semantic retrieval", 0)]),
            sample_entry("storage001", "Storage", [segment("sqlite storage", 0)]),
            sample_entry("workflow01", "Workflow", [segment("review workflow", 0)]),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "semantic_index.json")
            rebuild_semantic_index(
                entries,
                topic_embedder,
                path=path,
                embedding_model="test-embedder",
                segments_per_chunk=1,
                indexed_at=INDEXED_AT,
            )
            results = search_semantic_index([1.0, 0.0, 0.0], path=path, limit=3)

        self.assertEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertEqual(cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertEqual([result["video_id"] for result in results], [
            "retrieval1",
            "storage001",
            "workflow01",
        ])
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_search_result_shape_excludes_vectors_and_includes_chunk_metadata(self):
        entry = sample_entry(
            "alpha000001",
            "Semantic Retrieval",
            [segment("semantic retrieval", 0)],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "semantic_index.json")
            rebuild_semantic_index(
                [entry],
                topic_embedder,
                path=path,
                embedding_model="test-embedder",
                segments_per_chunk=1,
                indexed_at=INDEXED_AT,
            )
            result = search_semantic_index([1.0, 0.0, 0.0], path=path)[0]

        self.assertEqual(set(result), {
            "video_id",
            "title",
            "channel",
            "start",
            "end",
            "text",
            "chunk_index",
            "score",
            "embedding_model",
            "transcript_hash",
            "indexed_at",
        })
        self.assertNotIn("vector", result)
        self.assertEqual(result["video_id"], "alpha000001")
        self.assertEqual(result["text"], "semantic retrieval")
        self.assertEqual(result["start"], 0)
        self.assertEqual(result["end"], 5)
        self.assertEqual(result["chunk_index"], 0)
        self.assertEqual(result["embedding_model"], "test-embedder")
        self.assertEqual(result["indexed_at"], INDEXED_AT)


if __name__ == "__main__":
    unittest.main()

import math
import tempfile
import unittest
from pathlib import Path

from core.vector_store import (
    SQLiteVectorStore,
    extension_available,
    migrate_json_index,
    stored_dimensions,
)


def unit(*values):
    """A normalised vector, since that is what the embedder produces."""
    length = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / length for v in values]


def chunk(video_id, vector, text="some words", chunk_index=0):
    return {
        "video_id": video_id,
        "title": f"Title {video_id}",
        "channel": "Test Channel",
        "start": chunk_index * 30.0,
        "end": chunk_index * 30.0 + 30.0,
        "text": text,
        "chunk_index": chunk_index,
        "embedding_model": "test-embed",
        "transcript_hash": "hash",
        "indexed_at": "2026-08-21T00:00:00Z",
        "vector": vector,
    }


@unittest.skipUnless(extension_available(), "sqlite-vec is not installed")
class VectorStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Path(self.temp_dir.name) / "vectors.sqlite3"
        self.store = SQLiteVectorStore(self.db, dimensions=4)

    def test_search_returns_the_nearest_chunk_first(self):
        self.store.replace_all([
            chunk("aaaaaaaaaaa", unit(1, 0, 0, 0), "about memory"),
            chunk("bbbbbbbbbbb", unit(0, 1, 0, 0), "about baking"),
            chunk("ccccccccccc", unit(0.9, 0.1, 0, 0), "also about memory"),
        ])

        results = self.store.search(unit(1, 0, 0, 0), limit=3)

        self.assertEqual(results[0]["video_id"], "aaaaaaaaaaa")
        self.assertEqual(results[1]["video_id"], "ccccccccccc")
        self.assertEqual(results[2]["video_id"], "bbbbbbbbbbb")

    def test_an_exact_match_scores_one_and_an_opposite_scores_zero(self):
        self.store.replace_all([
            chunk("aaaaaaaaaaa", unit(1, 0, 0, 0)),
            chunk("bbbbbbbbbbb", unit(-1, 0, 0, 0)),
        ])

        results = {r["video_id"]: r["score"] for r in self.store.search(unit(1, 0, 0, 0), limit=2)}

        self.assertAlmostEqual(results["aaaaaaaaaaa"], 1.0, places=3)
        self.assertAlmostEqual(results["bbbbbbbbbbb"], 0.0, places=3)

    def test_metadata_travels_with_the_vector(self):
        self.store.replace_all([chunk("aaaaaaaaaaa", unit(1, 0, 0, 0), "the exact words", chunk_index=2)])

        result = self.store.search(unit(1, 0, 0, 0), limit=1)[0]

        self.assertEqual(result["text"], "the exact words")
        self.assertEqual(result["title"], "Title aaaaaaaaaaa")
        self.assertEqual(result["channel"], "Test Channel")
        self.assertEqual(result["chunk_index"], 2)
        self.assertEqual(result["start"], 60.0)

    def test_replacing_the_index_drops_what_was_there_before(self):
        self.store.replace_all([chunk("aaaaaaaaaaa", unit(1, 0, 0, 0))])
        self.store.replace_all([chunk("bbbbbbbbbbb", unit(0, 1, 0, 0))])

        self.assertEqual(self.store.stats()["chunk_count"], 1)
        self.assertEqual(self.store.search(unit(0, 1, 0, 0), limit=5)[0]["video_id"], "bbbbbbbbbbb")

    def test_a_query_of_the_wrong_width_returns_nothing_rather_than_raising(self):
        self.store.replace_all([chunk("aaaaaaaaaaa", unit(1, 0, 0, 0))])

        self.assertEqual(self.store.search([1.0, 0.0], limit=3), [])
        self.assertEqual(self.store.search([], limit=3), [])

    def test_chunks_with_the_wrong_width_are_skipped_on_write(self):
        written = self.store.replace_all([
            chunk("aaaaaaaaaaa", unit(1, 0, 0, 0)),
            chunk("bbbbbbbbbbb", [1.0, 0.0]),
        ])

        self.assertEqual(written, 1)
        self.assertEqual(self.store.stats()["chunk_count"], 1)

    def test_stats_describe_the_index(self):
        self.store.replace_all([
            chunk("aaaaaaaaaaa", unit(1, 0, 0, 0)),
            chunk("aaaaaaaaaaa", unit(0, 1, 0, 0), chunk_index=1),
            chunk("bbbbbbbbbbb", unit(0, 0, 1, 0)),
        ])

        stats = self.store.stats()

        self.assertTrue(stats["available"])
        self.assertEqual(stats["chunk_count"], 3)
        self.assertEqual(stats["video_count"], 2)
        self.assertEqual(stats["dimensions"], 4)
        self.assertEqual(stats["embedding_model"], "test-embed")

    def test_clearing_leaves_a_usable_empty_index(self):
        self.store.replace_all([chunk("aaaaaaaaaaa", unit(1, 0, 0, 0))])

        self.store.clear()

        self.assertEqual(self.store.stats()["chunk_count"], 0)
        self.assertEqual(self.store.search(unit(1, 0, 0, 0), limit=3), [])


@unittest.skipUnless(extension_available(), "sqlite-vec is not installed")
class StoredDimensionsTests(unittest.TestCase):
    def test_the_width_can_be_read_back_without_knowing_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "vectors.sqlite3"
            SQLiteVectorStore(db, dimensions=16)

            self.assertEqual(stored_dimensions(db), 16)

    def test_a_missing_index_reports_zero_rather_than_failing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(stored_dimensions(Path(temp_dir) / "absent.sqlite3"), 0)


@unittest.skipUnless(extension_available(), "sqlite-vec is not installed")
class MigrationTests(unittest.TestCase):
    def test_a_json_index_moves_across_with_its_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "vectors.sqlite3"
            index = {
                "version": 1,
                "embedding_model": "test-embed",
                "items": [
                    chunk("aaaaaaaaaaa", unit(1, 0, 0, 0), "first"),
                    chunk("bbbbbbbbbbb", unit(0, 1, 0, 0), "second"),
                ],
            }

            result = migrate_json_index(index, db)

            self.assertEqual(result["migrated"], 2)
            self.assertEqual(result["dimensions"], 4)
            self.assertEqual(result["video_count"], 2)

            store = SQLiteVectorStore(db, 4)
            self.assertEqual(store.search(unit(1, 0, 0, 0), limit=1)[0]["text"], "first")

    def test_an_empty_index_migrates_to_nothing_without_failing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = migrate_json_index({"items": []}, Path(temp_dir) / "vectors.sqlite3")

            self.assertEqual(result["migrated"], 0)


if __name__ == "__main__":
    unittest.main()

import json
import os
import gc
import tempfile
import unittest

from core.store import TranscriptStore

try:
    from core.sqlite_store import SQLiteTranscriptStore, migrate_json_to_sqlite
except ImportError as exc:
    SQLiteTranscriptStore = None
    migrate_json_to_sqlite = None
    SQLITE_IMPORT_ERROR = exc
else:
    SQLITE_IMPORT_ERROR = None


def sample_entry(video_id, title, segment_texts=None):
    segment_texts = segment_texts or ["intro", "details"]
    segments = [
        {"text": text, "start": index * 10.0, "duration": 4.5}
        for index, text in enumerate(segment_texts)
    ]
    return {
        "video_id": video_id,
        "title": title,
        "channel": "Storage Tests",
        "saved_at": "2026-05-08 12:00",
        "transcript": " ".join(segment_texts),
        "segments": segments,
    }


def release_store(store):
    close = getattr(store, "close", None)
    if callable(close):
        close()
    gc.collect()


class JsonTranscriptStoreCompatibilityTests(unittest.TestCase):
    def test_add_replaces_existing_video_id_and_all_entries_returns_dicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TranscriptStore(os.path.join(temp_dir, "store.json"))
            original = sample_entry("abc123def45", "Original")
            replacement = sample_entry(
                "abc123def45",
                "Replacement",
                ["replacement intro", "replacement details"],
            )
            second = sample_entry("xyz123def45", "Second")

            store.add_entry(original)
            store.add_entry(replacement)
            store.add_entry(second)

            self.assertEqual(store.all_entries(), [replacement, second])

    def test_delete_removes_entry_by_video_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TranscriptStore(os.path.join(temp_dir, "store.json"))
            first = sample_entry("abc123def45", "First")
            second = sample_entry("xyz123def45", "Second")
            store.add_entry(first)
            store.add_entry(second)

            store.delete_entry("abc123def45")

            self.assertEqual(store.all_entries(), [second])


@unittest.skipIf(
    SQLITE_IMPORT_ERROR is not None,
    f"core.sqlite_store import failed: {SQLITE_IMPORT_ERROR}",
)
class SQLiteTranscriptStoreParityTests(unittest.TestCase):
    def test_add_replace_delete_matches_json_store_behavior(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            try:
                original = sample_entry("abc123def45", "Original")
                replacement = sample_entry(
                    "abc123def45",
                    "Replacement",
                    ["replacement intro", "replacement details"],
                )
                second = sample_entry("xyz123def45", "Second")

                store.add_entry(original)
                store.add_entry(replacement)
                store.add_entry(second)

                self.assertEqual(store.all_entries(), [replacement, second])

                store.delete_entry("abc123def45")

                self.assertEqual(store.all_entries(), [second])
            finally:
                release_store(store)

    def test_all_entries_reconstructs_segments_in_stored_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            try:
                entry = sample_entry(
                    "abc123def45",
                    "Ordered Segments",
                    ["first segment", "second segment", "third segment"],
                )

                store.add_entry(entry)

                stored_entry = store.all_entries()[0]
                self.assertEqual(stored_entry["segments"], entry["segments"])
            finally:
                release_store(store)


@unittest.skipIf(
    SQLITE_IMPORT_ERROR is not None,
    f"core.sqlite_store import failed: {SQLITE_IMPORT_ERROR}",
)
class SQLiteMigrationTests(unittest.TestCase):
    def test_migration_preserves_entries_segments_and_deduplicates_video_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "store.json")
            db_path = os.path.join(temp_dir, "transcripts.db")
            original = sample_entry("abc123def45", "Original")
            replacement = sample_entry(
                "abc123def45",
                "Replacement",
                ["replacement intro", "replacement details"],
            )
            second = sample_entry(
                "xyz123def45",
                "Second",
                ["second intro", "second details"],
            )

            with open(json_path, "w", encoding="utf-8") as file:
                json.dump([original, replacement, second], file)

            migrated_store = migrate_json_to_sqlite(json_path, db_path)
            release_store(migrated_store)

            store = SQLiteTranscriptStore(db_path)
            try:
                self.assertEqual(store.all_entries(), [replacement, second])
            finally:
                release_store(store)


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest

from core.research import search_entries
from core.sqlite_store import SQLiteTranscriptStore, export_entries_to_json, migrate_json_to_sqlite
from core.store import JsonTranscriptStore, create_transcript_store, normalize_display_text


def sample_entry(video_id, title, transcript, saved_at="2026-05-08 12:00"):
    parts = [part.strip() for part in transcript.split(".") if part.strip()]
    segments = [
        {"text": part, "start": index * 10.0, "duration": 5.0}
        for index, part in enumerate(parts)
    ]
    return {
        "video_id": video_id,
        "title": title,
        "channel": "Stage 3",
        "saved_at": saved_at,
        "transcript": transcript,
        "segments": segments,
    }


class Stage3SQLiteFTSTests(unittest.TestCase):
    def test_sqlite_fts_search_matches_in_memory_search_for_results(self):
        entries = [
            sample_entry(
                "alpha000001",
                "Semantic Search Notes",
                "semantic search needs fast transcript indexing. research archive",
                "2026-05-01 10:00",
            ),
            sample_entry(
                "beta0000002",
                "Agent Review Notes",
                "agent review needs human workflow support. review queue",
                "2026-05-02 10:00",
            ),
            sample_entry(
                "gamma000003",
                "Storage Notes",
                "sqlite storage keeps transcript segments organized",
                "2026-05-03 10:00",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            if not store.fts_enabled:
                self.skipTest("SQLite FTS5 is not available")
            store.import_entries(entries)

            sqlite_results = store.search_entries("semantic search", sort="title")
            memory_results = search_entries(entries, "semantic search", sort="title")

            self.assertEqual(
                [result["video_id"] for result in sqlite_results],
                [result["video_id"] for result in memory_results],
            )
            self.assertEqual(sqlite_results[0]["word_count"], memory_results[0]["word_count"])
            self.assertEqual(sqlite_results[0]["matches"][0]["start"], 0)

    def test_sqlite_fts_updates_when_entry_is_replaced_and_deleted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            if not store.fts_enabled:
                self.skipTest("SQLite FTS5 is not available")

            original = sample_entry(
                "alpha000001",
                "Replacement Notes",
                "oldtopic appears in this transcript",
            )
            replacement = sample_entry(
                "alpha000001",
                "Replacement Notes",
                "newtopic appears in this transcript",
            )

            store.add_entry(original)
            self.assertEqual(store.search_entries("oldtopic")[0]["video_id"], "alpha000001")

            store.add_entry(replacement)
            self.assertEqual(store.search_entries("oldtopic"), [])
            self.assertEqual(store.search_entries("newtopic")[0]["video_id"], "alpha000001")

            store.delete_entry("alpha000001")
            self.assertEqual(store.search_entries("newtopic"), [])


class Stage3MigrationAndExportTests(unittest.TestCase):
    def test_migration_builds_searchable_sqlite_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "store.json")
            db_path = os.path.join(temp_dir, "transcripts.db")
            entry = sample_entry(
                "alpha000001",
                "Migrated Search",
                "migration should build a searchable sqlite archive",
            )

            with open(json_path, "w", encoding="utf-8") as file:
                json.dump([entry], file)

            store = migrate_json_to_sqlite(json_path, db_path)

            self.assertEqual(store.all_entries(), [entry])
            self.assertEqual(store.search_entries("searchable")[0]["video_id"], "alpha000001")

    def test_migration_replaces_existing_sqlite_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "store.json")
            db_path = os.path.join(temp_dir, "transcripts.db")
            stale_entry = sample_entry(
                "stale000001",
                "Stale Row",
                "staletopic should be removed during migration",
            )
            fresh_entry = sample_entry(
                "fresh000001",
                "Fresh Row",
                "freshtopic should be the only migrated row",
            )

            existing_store = SQLiteTranscriptStore(db_path)
            existing_store.add_entry(stale_entry)
            with open(json_path, "w", encoding="utf-8") as file:
                json.dump([fresh_entry], file)

            store = migrate_json_to_sqlite(json_path, db_path)

            self.assertEqual([entry["video_id"] for entry in store.all_entries()], ["fresh000001"])
            self.assertEqual(store.search_entries("staletopic"), [])
            self.assertEqual(store.search_entries("freshtopic")[0]["video_id"], "fresh000001")

    def test_export_entries_to_json_writes_backup_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = os.path.join(temp_dir, "backup.json")
            entry = sample_entry(
                "alpha000001",
                "Backup",
                "json export keeps a portable backup",
            )

            written_path = export_entries_to_json([entry], export_path)

            with open(written_path, "r", encoding="utf-8") as file:
                self.assertEqual(json.load(file), [entry])

    def test_auto_store_uses_sqlite_after_database_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "store.json")
            db_path = os.path.join(temp_dir, "transcripts.db")

            json_store = create_transcript_store(
                backend="auto",
                json_path=json_path,
                sqlite_path=db_path,
            )
            self.assertIsInstance(json_store, JsonTranscriptStore)

            SQLiteTranscriptStore(db_path)
            sqlite_store = create_transcript_store(
                backend="auto",
                json_path=json_path,
                sqlite_path=db_path,
            )
            self.assertIsInstance(sqlite_store, SQLiteTranscriptStore)


class ChannelNameNormalizationTests(unittest.TestCase):
    def test_decodes_escaped_text_from_youtube_json(self):
        self.assertEqual(
            normalize_display_text("AI News \\u0026 Strategy Daily | Nate B Jones"),
            "AI News & Strategy Daily | Nate B Jones",
        )
        self.assertEqual(normalize_display_text("Tips &amp; Tricks"), "Tips & Tricks")
        self.assertEqual(normalize_display_text("  Plain Name  "), "Plain Name")

    def test_new_entries_are_stored_with_a_decoded_channel_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            entry = sample_entry("alpha000001", "Escaped", "channel name decoding")
            entry["channel"] = "AI News \\u0026 Strategy Daily"
            store.add_entry(entry)

            self.assertEqual(store.all_entries()[0]["channel"], "AI News & Strategy Daily")

    def test_normalize_merges_the_duplicate_channel_an_old_archive_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "transcripts.db")
            store = SQLiteTranscriptStore(db_path)
            store.add_entry(sample_entry("alpha000001", "Old", "first archived video"))
            store.add_entry(sample_entry("beta0000002", "New", "second archived video"))

            # Recreate the split an older build left behind: same channel, two rows.
            import sqlite3

            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "UPDATE channels SET name = ? WHERE name = ?",
                    ("AI News \\u0026 Strategy Daily", "Stage 3"),
                )
                connection.execute("INSERT INTO channels (name) VALUES (?)", ("AI News & Strategy Daily",))
                new_id = connection.execute(
                    "SELECT id FROM channels WHERE name = ?", ("AI News & Strategy Daily",)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE videos SET channel_id = ? WHERE video_id = ?", (new_id, "beta0000002")
                )

            store = SQLiteTranscriptStore(db_path)
            result = store.normalize_channel_names()

            self.assertEqual(result["merged"], 1)
            channels = {entry["channel"] for entry in store.all_entries()}
            self.assertEqual(channels, {"AI News & Strategy Daily"})
            self.assertEqual(len(store.all_entries()), 2)

    def test_normalize_is_a_no_op_on_a_clean_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteTranscriptStore(os.path.join(temp_dir, "transcripts.db"))
            store.add_entry(sample_entry("alpha000001", "Clean", "nothing to normalize"))

            self.assertEqual(store.normalize_channel_names(), {"renamed": 0, "merged": 0})


if __name__ == "__main__":
    unittest.main()

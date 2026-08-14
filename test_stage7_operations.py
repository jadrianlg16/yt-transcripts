import json
import os
import gc
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main
import mcp_server
from core.ai_artifacts import AIArtifactStore
from core.fetch_reliability import FetchReliabilityStore
from core.organization import ResearchOrganizationStore
from core.sqlite_store import SQLiteTranscriptStore
from core.store import TranscriptStore


def sample_entry(video_id="stage700001", channel="Ops Channel", title="Ops Source"):
    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "saved_at": "2026-05-14 10:00",
        "uploaded_at": "2026-05-13",
        "fetched_at": "2026-05-14T10:00:00Z",
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript": "operations settings exports database browser and mcp controls",
        "segments": [
            {"text": "operations settings exports", "start": 0, "duration": 4},
            {"text": "database browser and mcp controls", "start": 4, "duration": 4},
        ],
    }


def reset_task_status():
    main.task_status.update({
        "run_id": None,
        "current_task": None,
        "progress": 0,
        "total": 0,
        "message": "Idle",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "success_count": 0,
        "failure_count": 0,
        "skipped_count": 0,
        "recent_events": [],
    })
    main.task_cancel_event.clear()


class Stage7OperationsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        self.previous_project_root = mcp_server.PROJECT_ROOT
        os.chdir(self.temp_dir.name)

        main.store = TranscriptStore(os.path.join(self.temp_dir.name, "transcripts.json"))
        main.store.add_entry(sample_entry())
        main.store.add_entry(sample_entry("stage700002", channel="Second Channel", title="Second Source"))
        main.reliability_store = FetchReliabilityStore(os.path.join(self.temp_dir.name, "reliability.json"))
        main.organization_store = ResearchOrganizationStore(os.path.join(self.temp_dir.name, "research.json"))
        main.ai_artifact_store = AIArtifactStore(os.path.join(self.temp_dir.name, "ai_artifacts.json"))
        main.backend_events.clear()
        main.backend_event_id = 0
        reset_task_status()
        # These are resolved at import time, so when YT_TRANSCRIPTS_DATA_DIR points at a
        # real data directory (as it does in the Docker image) chdir alone does not
        # isolate them and the suite would rewrite live settings.
        self.settings_paths = (main.SYSTEM_SETTINGS_PATH, main.MCP_SETTINGS_PATH)
        main.SYSTEM_SETTINGS_PATH = Path(self.temp_dir.name) / "system_settings.json"
        main.MCP_SETTINGS_PATH = Path(self.temp_dir.name) / "mcp_settings.json"
        # mcp_server resolves its own paths from the environment on every call, so it
        # reads the live data directory unless this points somewhere disposable.
        self.previous_data_dir = os.environ.get("YT_TRANSCRIPTS_DATA_DIR")
        os.environ["YT_TRANSCRIPTS_DATA_DIR"] = self.temp_dir.name
        mcp_server.PROJECT_ROOT = Path(self.temp_dir.name)
        self.client = TestClient(main.app)

    def tearDown(self):
        main.SYSTEM_SETTINGS_PATH, main.MCP_SETTINGS_PATH = self.settings_paths
        if self.previous_data_dir is None:
            os.environ.pop("YT_TRANSCRIPTS_DATA_DIR", None)
        else:
            os.environ["YT_TRANSCRIPTS_DATA_DIR"] = self.previous_data_dir
        mcp_server.PROJECT_ROOT = self.previous_project_root
        os.chdir(self.cwd)
        self.temp_dir.cleanup()

    def test_mcp_status_toggle_persists_and_mcp_tools_respect_disabled_state(self):
        status = self.client.get("/api/mcp/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["enabled"])
        self.assertIn("search_transcripts", status.json()["tools"])

        disabled = self.client.put("/api/mcp/settings", json={"enabled": False})
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["enabled"])

        with open("mcp_settings.json", "r", encoding="utf-8") as file:
            self.assertFalse(json.load(file)["enabled"])

        tool_response = mcp_server.get_library_stats()
        self.assertFalse(tool_response["available"])
        self.assertIn("disabled", tool_response["message"].lower())

    def test_data_export_downloads_jsonl_csv_markdown_and_filters_scope(self):
        json_response = self.client.post("/api/data/export", json={
            "scope": "channel",
            "channel": "Ops Channel",
            "format": "json",
        })
        self.assertEqual(json_response.status_code, 200)
        json_payload = json_response.json()
        self.assertEqual(json_payload["count"], 1)
        self.assertEqual(json_payload["transcripts"][0]["video_id"], "stage700001")

        jsonl_response = self.client.post("/api/data/export", json={"format": "jsonl"})
        self.assertEqual(jsonl_response.status_code, 200)
        self.assertIn("stage700001", jsonl_response.text)
        self.assertIn("stage700002", jsonl_response.text)

        csv_response = self.client.post("/api/data/export", json={"format": "csv"})
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("video_id,title,channel", csv_response.text)

        markdown_response = self.client.post("/api/data/export", json={
            "scope": "selected",
            "video_ids": ["stage700002"],
            "format": "markdown",
        })
        self.assertEqual(markdown_response.status_code, 200)
        self.assertIn("Second Source", markdown_response.text)
        self.assertNotIn("Ops Source", markdown_response.text)

    def test_data_tables_are_read_only_whitelisted_and_searchable(self):
        table_list = self.client.get("/api/data/tables")
        self.assertEqual(table_list.status_code, 200)
        names = [table["name"] for table in table_list.json()["tables"]]
        self.assertIn("videos", names)
        self.assertIn("segments", names)

        videos = self.client.get("/api/data/tables/videos", params={"q": "second"})
        self.assertEqual(videos.status_code, 200)
        self.assertEqual(videos.json()["total"], 1)
        self.assertEqual(videos.json()["rows"][0]["video_id"], "stage700002")

        bounded = self.client.get("/api/data/tables/segments", params={"limit": 1000})
        self.assertEqual(bounded.status_code, 200)
        self.assertEqual(bounded.json()["limit"], 200)

        rejected = self.client.get("/api/data/tables/sqlite_master")
        self.assertEqual(rejected.status_code, 404)

    def test_system_pause_blocks_new_ingestion_and_cancel_sets_task_flag(self):
        paused = self.client.put("/api/system/settings", json={"ingestion_paused": True})
        self.assertEqual(paused.status_code, 200)
        self.assertTrue(paused.json()["settings"]["ingestion_paused"])

        fetch_response = self.client.post("/api/fetch/video", json={
            "url": "https://www.youtube.com/watch?v=stage700001",
        })
        self.assertEqual(fetch_response.status_code, 409)
        self.assertIn("paused", fetch_response.json()["detail"].lower())

        main.task_status["current_task"] = "channel"
        main.task_status["run_id"] = "canceltest"
        cancel_response = self.client.post("/api/system/cancel-task")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertTrue(main.task_cancel_event.is_set())
        self.assertEqual(cancel_response.json()["status"], "cancel_requested")

    def test_storage_migration_does_not_replace_an_active_sqlite_archive(self):
        sqlite_path = os.path.join(self.temp_dir.name, "transcripts_store.sqlite3")
        sqlite_store = SQLiteTranscriptStore(sqlite_path)
        sqlite_store.add_entry(sample_entry())
        sqlite_store.add_entry(sample_entry("stage700002"))
        main.store = sqlite_store

        with open("transcripts_store.json", "w", encoding="utf-8") as file:
            json.dump([sample_entry("stale700001")], file)

        response = self.client.post("/api/storage/migrate")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "already_active")
        self.assertEqual(response.json()["storage"]["active_count"], 2)
        self.assertEqual(len(sqlite_store.all_entries()), 2)
        main.store = TranscriptStore(os.path.join(self.temp_dir.name, "transcripts.json"))
        del sqlite_store
        gc.collect()


if __name__ == "__main__":
    unittest.main()

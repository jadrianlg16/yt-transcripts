import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from core.fetch_reliability import FetchReliabilityStore
from core.store import TranscriptStore


def sample_entry(video_id="stage500001", title="Stage 5 Source"):
    return {
        "video_id": video_id,
        "title": title,
        "channel": "Reliability Channel",
        "saved_at": "2026-05-09 10:00",
        "transcript": "stage five reliability transcript",
        "segments": [
            {"text": "stage five reliability transcript", "start": 0, "duration": 5},
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


class FetchReliabilityStoreTests(unittest.TestCase):
    def test_fetch_run_updates_and_settings_persist_across_instances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reliability.json")
            store = FetchReliabilityStore(path)

            run = store.start_run("channel", "https://youtube.com/@test", total=3)
            self.assertEqual(run["status"], "running")
            self.assertIsNone(run["finished_at"])

            store.record_success(run["id"], "success0001", title="Success", index=1, total=3)
            store.record_failure(run["id"], "Transcript disabled", video_id="failure0001", index=2, total=3)
            store.record_skipped(run["id"], "skipped0001", reason="Already saved", index=3, total=3)
            store.finish_run(run["id"], message="Mixed outcome")

            reloaded = FetchReliabilityStore(path)
            persisted = reloaded.get_run(run["id"])

            self.assertEqual(persisted["status"], "partial")
            self.assertEqual(persisted["success_count"], 1)
            self.assertEqual(persisted["failure_count"], 1)
            self.assertEqual(persisted["skipped_count"], 1)
            self.assertEqual(persisted["failures"][0]["video_id"], "failure0001")
            self.assertEqual(reloaded.retry_items(run["id"])[0]["url"], "https://www.youtube.com/watch?v=failure0001")

            settings = reloaded.update_settings({
                "enabled": True,
                "channels": [" https://youtube.com/@test ", "HTTPS://YOUTUBE.COM/@TEST", ""],
                "frequency_minutes": 5,
                "languages": [" EN ", "es", "en", "english", "../bad"],
            })
            self.assertTrue(settings["enabled"])
            self.assertEqual(settings["channels"], ["https://youtube.com/@test"])
            self.assertEqual(settings["frequency_minutes"], 15)
            self.assertEqual(settings["languages"], ["en", "es"])

            self.assertEqual(FetchReliabilityStore(path).get_settings(), settings)

    def test_corrupt_reliability_file_recovers_to_empty_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reliability.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write("{not-json")

            store = FetchReliabilityStore(path)

            self.assertEqual(store.list_runs(), [])
            self.assertEqual(store.get_settings()["languages"], ["en"])

    def test_non_video_failures_are_not_retryable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "reliability.json")
            store = FetchReliabilityStore(path)
            run = store.start_run("channel", "https://youtube.com/@test", total=1)

            failure = store.record_failure(run["id"], "No videos found", url="https://youtube.com/@test")

            self.assertFalse(failure["retryable"])
            self.assertEqual(store.retry_items(run["id"]), [])

            store.record_failure(
                run["id"],
                "Transcript temporarily unavailable",
                url="https://www.youtube.com/watch?v=abc123def45",
            )

            retry_items = store.retry_items(run["id"])
            self.assertEqual(len(retry_items), 1)
            self.assertEqual(retry_items[0]["video_id"], "abc123def45")


class Stage5ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        main.store = TranscriptStore(os.path.join(self.temp_dir.name, "transcripts.json"))
        main.reliability_store = FetchReliabilityStore(os.path.join(self.temp_dir.name, "reliability.json"))
        main.backend_events.clear()
        main.backend_event_id = 0
        reset_task_status()
        self.client = TestClient(main.app)

    def tearDown(self):
        os.chdir(self.cwd)
        self.temp_dir.cleanup()

    def test_channel_fetch_records_partial_failure_and_retry_run_saves_video(self):
        videos = [{"videoId": "success0001"}, {"videoId": "failure0001"}]

        def fake_fetch(video_id, languages=None):
            if video_id == "failure0001":
                raise RuntimeError("Transcript disabled")
            return sample_entry(video_id, "Fetched success")

        with patch.object(main.scrapetube, "get_channel", return_value=videos), \
             patch.object(main, "fetch_channel_rss_entries", side_effect=RuntimeError("RSS unavailable")), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post("/api/fetch/channel", json={"url": "https://youtube.com/@test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(main.store.all_entries()), 1)

        channel_run = main.reliability_store.list_runs()[0]
        self.assertEqual(channel_run["type"], "channel")
        self.assertEqual(channel_run["status"], "partial")
        self.assertEqual(channel_run["success_count"], 1)
        self.assertEqual(channel_run["failure_count"], 1)
        self.assertEqual(channel_run["skipped_count"], 1)
        self.assertEqual(channel_run["failures"][0]["video_id"], "failure0001")

        events = self.client.get("/api/events").json()["events"]
        self.assertIn("channel_video_failed", [event["event"] for event in events])

        def retry_fetch(video_id, languages=None):
            return sample_entry(video_id, "Retry success")

        with patch.object(main, "fetch_video_full", side_effect=retry_fetch):
            retry_response = self.client.post("/api/fetch/retry-failed", json={"run_id": channel_run["id"]})

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(len(main.store.all_entries()), 2)
        retry_run = main.reliability_store.list_runs()[0]
        self.assertEqual(retry_run["type"], "retry")
        self.assertEqual(retry_run["status"], "success")
        self.assertEqual(retry_run["success_count"], 1)

    def test_channel_fetch_uses_rss_candidates_when_available(self):
        rss_entries = [{
            "video_id": "rssvideo001",
            "title": "RSS Video",
            "url": "https://www.youtube.com/watch?v=rssvideo001",
        }]

        def fake_fetch(video_id, languages=None):
            return sample_entry(video_id, "RSS fetched")

        with patch.object(main, "fetch_channel_rss_entries", return_value=rss_entries), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post("/api/fetch/channel", json={"url": "https://youtube.com/@test"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("run_id", response.json())
        self.assertEqual(main.store.all_entries()[0]["video_id"], "rssvideo001")

        channel_run = main.reliability_store.list_runs()[0]
        self.assertEqual(channel_run["status"], "success")
        self.assertEqual(channel_run["success_count"], 1)
        events = self.client.get("/api/events").json()["events"]
        found_events = [event for event in events if event["event"] == "channel_videos_found"]
        self.assertEqual(found_events[-1]["details"]["source"], "rss")

    def test_watcher_settings_api_and_rss_parser_are_connected(self):
        default_response = self.client.get("/api/watcher/settings")
        self.assertEqual(default_response.status_code, 200)
        self.assertFalse(default_response.json()["enabled"])

        update_response = self.client.put("/api/watcher/settings", json={
            "enabled": True,
            "channels": ["https://www.youtube.com/channel/UCtestchannel", ""],
            "frequency_minutes": 30,
            "languages": ["en", "es"],
        })
        self.assertEqual(update_response.status_code, 200)
        settings = update_response.json()
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["frequency_minutes"], 30)
        self.assertEqual(settings["languages"], ["en", "es"])

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
              xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <yt:videoId>rssvideo001</yt:videoId>
            <title>RSS Video</title>
            <link rel="alternate" href="https://www.youtube.com/watch?v=rssvideo001" />
          </entry>
        </feed>
        """
        entries = main.parse_youtube_rss_entries(xml)
        self.assertEqual(entries[0]["video_id"], "rssvideo001")
        self.assertEqual(entries[0]["title"], "RSS Video")

    def test_partial_watcher_settings_update_preserves_existing_values(self):
        self.client.put("/api/watcher/settings", json={
            "enabled": True,
            "channels": ["https://www.youtube.com/channel/UCtestchannel"],
            "frequency_minutes": 30,
            "languages": ["en", "es"],
        })

        response = self.client.put("/api/watcher/settings", json={"enabled": False})

        self.assertEqual(response.status_code, 200)
        settings = response.json()
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["channels"], ["https://www.youtube.com/channel/UCtestchannel"])
        self.assertEqual(settings["frequency_minutes"], 30)
        self.assertEqual(settings["languages"], ["en", "es"])

    def test_fetch_start_rejects_overlapping_task(self):
        main.task_status["current_task"] = "channel"
        main.task_status["message"] = "Already fetching"

        response = self.client.post("/api/fetch/video", json={"url": "https://youtube.com/watch?v=abc123def45"})

        self.assertEqual(response.status_code, 409)
        self.assertIn("Already fetching", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
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


def deep_listing(count, published="2 days ago"):
    return [
        {
            "videoId": f"deepvideo{index:03d}",
            "title": f"Deep {index}",
            "url": f"https://www.youtube.com/watch?v=deepvideo{index:03d}",
            "published_text": published,
        }
        for index in range(count)
    ]


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
        # Resolved at import time, so chdir alone does not isolate them when
        # YT_TRANSCRIPTS_DATA_DIR points at a real data directory.
        self.settings_paths = (main.SYSTEM_SETTINGS_PATH, main.MCP_SETTINGS_PATH)
        main.SYSTEM_SETTINGS_PATH = Path(self.temp_dir.name) / "system_settings.json"
        main.MCP_SETTINGS_PATH = Path(self.temp_dir.name) / "mcp_settings.json"
        self.client = TestClient(main.app)

    def tearDown(self):
        main.SYSTEM_SETTINGS_PATH, main.MCP_SETTINGS_PATH = self.settings_paths
        os.chdir(self.cwd)
        self.temp_dir.cleanup()

    def test_channel_fetch_records_partial_failure_and_retry_run_saves_video(self):
        videos = [{"videoId": "success0001"}, {"videoId": "failure0001"}]

        def fake_fetch(video_id, languages=None):
            if video_id == "failure0001":
                raise RuntimeError("Transcript disabled")
            return sample_entry(video_id, "Fetched success")

        with patch.object(main.scrapetube, "get_channel", return_value=videos), \
             patch.object(main, "list_channel_videos", side_effect=RuntimeError("channel page unavailable")), \
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
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": main.RSS_FEED_DEPTH},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("run_id", response.json())
        self.assertEqual(main.store.all_entries()[0]["video_id"], "rssvideo001")

        channel_run = main.reliability_store.list_runs()[0]
        self.assertEqual(channel_run["status"], "success")
        self.assertEqual(channel_run["success_count"], 1)
        events = self.client.get("/api/events").json()["events"]
        found_events = [event for event in events if event["event"] == "channel_videos_found"]
        self.assertEqual(found_events[-1]["details"]["source"], "rss")

    def test_deep_channel_fetch_pages_past_the_rss_cap(self):
        def fake_listing(channel, limit=None, **kwargs):
            videos = [
                {
                    "videoId": f"deepvideo{index:03d}",
                    "title": f"Deep {index}",
                    "url": f"https://www.youtube.com/watch?v=deepvideo{index:03d}",
                    "published_text": "2 days ago",
                }
                for index in range(20)
            ]
            return videos if limit is None else videos[:limit]

        def fake_fetch(video_id, languages=None):
            return sample_entry(video_id, "Deep fetched")

        with patch.object(main, "list_channel_videos", side_effect=fake_listing), \
             patch.object(main, "fetch_channel_rss_entries", side_effect=AssertionError("RSS should not be used")), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(main.store.all_entries()), 20)
        found = [e for e in self.client.get("/api/events").json()["events"] if e["event"] == "channel_videos_found"]
        self.assertEqual(found[-1]["details"]["listed"], 20)
        self.assertEqual(found[-1]["details"]["source"], "channel_page")

    def test_channel_fetch_skips_videos_already_in_the_archive(self):
        main.store.add_entry(sample_entry("deepvideo000", "Already archived"))
        fetched: list[str] = []

        def fake_fetch(video_id, languages=None):
            fetched.append(video_id)
            return sample_entry(video_id, "Deep fetched")

        with patch.object(main, "list_channel_videos", side_effect=lambda channel, limit=None, **kw: deep_listing(3)), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("deepvideo000", fetched)
        self.assertEqual(sorted(fetched), ["deepvideo001", "deepvideo002"])
        found = [e for e in self.client.get("/api/events").json()["events"] if e["event"] == "channel_videos_found"]
        self.assertEqual(found[-1]["details"]["already_saved"], 1)
        self.assertEqual(found[-1]["details"]["total"], 2)

    def test_rate_limited_channel_fetch_stops_early_and_leaves_the_rest_unfetched(self):
        attempted: list[str] = []

        def fake_fetch(video_id, languages=None):
            attempted.append(video_id)
            raise RuntimeError("YouTube is blocking requests from your IP")

        with patch.object(main, "list_channel_videos", side_effect=lambda channel, limit=None, **kw: deep_listing(20)), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        # One attempt per backoff step, plus the attempt that exhausts them.
        self.assertEqual(len(attempted), len(main.RATE_LIMIT_BACKOFF_SECONDS) + 1)
        self.assertEqual(main.task_status["success_count"], 0)
        self.assertIn("Stopped early", main.task_status["message"])
        self.assertIn("left for a later run", main.task_status["message"])

    def test_rate_limit_streak_resets_after_a_successful_fetch(self):
        def fake_fetch(video_id, languages=None):
            if video_id in {"deepvideo001", "deepvideo003"}:
                raise RuntimeError("YouTube is blocking requests from your IP")
            return sample_entry(video_id, "Saved anyway")

        with patch.object(main, "list_channel_videos", side_effect=lambda channel, limit=None, **kw: deep_listing(6)), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        # Isolated rate limits must not end the run: 4 of 6 still land.
        self.assertEqual(main.task_status["success_count"], 4)
        self.assertNotIn("Stopped early", main.task_status["message"])

    def test_non_rate_limit_failures_never_trigger_a_backoff(self):
        def fake_fetch(video_id, languages=None):
            raise RuntimeError("Subtitles are disabled for this video")

        with patch.object(main, "list_channel_videos", side_effect=lambda channel, limit=None, **kw: deep_listing(6)), \
             patch.object(main, "fetch_video_full", side_effect=fake_fetch), \
             patch.object(main.time, "sleep", return_value=None), \
             patch.object(main.random, "uniform", return_value=0):
            response = self.client.post(
                "/api/fetch/channel",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(main.task_status["failure_count"], 6)
        self.assertNotIn("Stopped early", main.task_status["message"])

    def test_channel_preview_marks_already_saved_titles(self):
        main.store.add_entry(sample_entry("deepvideo000", "Already archived"))

        with patch.object(main, "list_channel_videos", side_effect=lambda channel, limit=None, **kw: deep_listing(3)):
            response = self.client.post(
                "/api/fetch/channel/preview",
                json={"url": "https://youtube.com/@test", "limit": 20},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["new_count"], 2)
        self.assertEqual(payload["already_saved_count"], 1)
        first = payload["candidates"][0]
        self.assertEqual(first["video_id"], "deepvideo000")
        self.assertTrue(first["already_saved"])
        self.assertFalse(first["selected"])
        self.assertEqual(first["title"], "Deep 0")
        self.assertEqual(first["published_text"], "2 days ago")

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

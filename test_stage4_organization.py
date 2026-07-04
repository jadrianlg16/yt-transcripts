import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import main
from core.organization import ResearchOrganizationStore
from core.store import TranscriptStore


def sample_entry(video_id="stage400001"):
    return {
        "video_id": video_id,
        "title": "Stage 4 Research Source",
        "channel": "Research Org",
        "saved_at": "2026-05-09 10:00",
        "transcript": "first research claim second collection quote",
        "segments": [
            {"text": "first research claim", "start": 0, "duration": 5},
            {"text": "second collection quote", "start": 10, "duration": 4},
        ],
    }


class ResearchOrganizationStoreTests(unittest.TestCase):
    def test_tags_notes_collections_clips_and_markdown_export_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchOrganizationStore(os.path.join(temp_dir, "org.json"))
            video_id = "stage400001"

            tags = store.set_tags(video_id, ["AI", "#ai", "Research"])
            store.set_video_note(video_id, "Use this as a source note.")
            timestamp_note = store.add_timestamp_note(video_id, 10, "Important timestamp note.")
            collection = store.create_collection("Agent Research", "Reusable clips")
            clip = store.add_clip(collection["id"], video_id, 10, 14, "second collection quote", "Clip note")

            self.assertEqual(tags, ["ai", "research"])
            self.assertEqual(timestamp_note["start"], 10)
            self.assertEqual(clip["video_id"], video_id)

            markdown = store.collection_markdown(collection["id"], {video_id: sample_entry(video_id)})
            self.assertIn("# Agent Research", markdown)
            self.assertIn("[0:10](https://youtube.com/watch?v=stage400001&t=10s)", markdown)
            self.assertIn("> second collection quote", markdown)
            self.assertIn("Video note: Use this as a source note.", markdown)
            self.assertIn("Timestamp note (0:10): Important timestamp note.", markdown)

            exported = store.export_collections()
            imported_store = ResearchOrganizationStore(os.path.join(temp_dir, "imported.json"))
            imported_count = imported_store.import_collections(exported["collections"])

            self.assertEqual(imported_count, 1)
            self.assertEqual(imported_store.snapshot()["collections"][0]["name"], "Agent Research")

    def test_delete_timestamp_note_and_clip_remove_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchOrganizationStore(os.path.join(temp_dir, "org.json"))
            video_id = "stage400001"
            note = store.add_timestamp_note(video_id, 0, "Temporary note")
            collection = store.create_collection("Temporary")
            clip = store.add_clip(collection["id"], video_id, 0, 5, "first research claim")

            self.assertTrue(store.delete_timestamp_note(video_id, note["id"]))
            self.assertTrue(store.delete_clip(collection["id"], clip["id"]))

            snapshot = store.snapshot()
            self.assertNotIn(video_id, snapshot["timestamp_notes"])
            self.assertEqual(snapshot["collections"][0]["clips"], [])


class Stage4ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.transcript_store = TranscriptStore(os.path.join(self.temp_dir.name, "transcripts.json"))
        self.transcript_store.add_entry(sample_entry())
        self.organization_store = ResearchOrganizationStore(os.path.join(self.temp_dir.name, "org.json"))
        main.store = self.transcript_store
        main.organization_store = self.organization_store
        main.backend_events.clear()
        main.backend_event_id = 0
        self.client = TestClient(main.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stage4_api_updates_tags_notes_collections_and_events(self):
        tags_response = self.client.put(
            "/api/transcripts/stage400001/tags",
            json={"tags": ["Strategy", "strategy", "Review"]},
        )
        self.assertEqual(tags_response.status_code, 200)
        self.assertEqual(tags_response.json()["tags"], ["strategy", "review"])

        note_response = self.client.put(
            "/api/transcripts/stage400001/note",
            json={"note": "API video note"},
        )
        self.assertEqual(note_response.status_code, 200)

        timestamp_response = self.client.post(
            "/api/transcripts/stage400001/timestamp-notes",
            json={"start": 10, "text": "API timestamp note"},
        )
        self.assertEqual(timestamp_response.status_code, 200)

        collection_response = self.client.post(
            "/api/collections",
            json={"name": "API Collection", "description": "API clips"},
        )
        self.assertEqual(collection_response.status_code, 200)
        collection_id = collection_response.json()["id"]

        clip_response = self.client.post(
            f"/api/collections/{collection_id}/clips",
            json={"video_id": "stage400001", "start": 10, "text": "manual clip text"},
        )
        self.assertEqual(clip_response.status_code, 200)

        research_response = self.client.get("/api/research")
        research = research_response.json()
        self.assertEqual(research["tags"]["stage400001"], ["strategy", "review"])
        self.assertEqual(research["video_notes"]["stage400001"], "API video note")
        self.assertEqual(research["collections"][0]["clips"][0]["text"], "manual clip text")

        events_response = self.client.get("/api/events")
        event_names = [event["event"] for event in events_response.json()["events"]]
        self.assertIn("tags_updated", event_names)
        self.assertIn("clip_added", event_names)

    def test_collection_markdown_and_json_import_export_endpoints(self):
        collection = self.client.post("/api/collections", json={"name": "Export Me"}).json()
        self.client.post(
            f"/api/collections/{collection['id']}/clips",
            json={"video_id": "stage400001", "start": 0, "text": "first research claim"},
        )

        markdown_response = self.client.get(f"/api/collections/{collection['id']}/markdown")
        self.assertEqual(markdown_response.status_code, 200)
        self.assertIn("# Export Me", markdown_response.text)
        self.assertIn("https://youtube.com/watch?v=stage400001&t=0s", markdown_response.text)

        export_response = self.client.get("/api/collections/export")
        self.assertEqual(export_response.status_code, 200)
        exported = export_response.json()
        self.assertEqual(len(exported["collections"]), 1)

        import_response = self.client.post(
            "/api/collections/import",
            json={"collections": exported["collections"], "replace": True},
        )
        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(import_response.json()["imported_count"], 1)


if __name__ == "__main__":
    unittest.main()

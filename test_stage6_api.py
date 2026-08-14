import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from core.ai_artifacts import AIArtifactStore
from core.ai_settings import AISettingsStore
from core.semantic_search import SemanticIndexStore, save_semantic_index
from core.store import TranscriptStore


def sample_entry(video_id="stage600001"):
    return {
        "video_id": video_id,
        "title": "Stage 6 Source",
        "channel": "AI Research",
        "saved_at": "2026-05-12 08:00",
        "uploaded_at": "2026-05-12",
        "transcript": "semantic retrieval needs local private model settings",
        "segments": [
            {"text": "semantic retrieval needs local", "start": 0, "duration": 4},
            {"text": "private model settings", "start": 4, "duration": 4},
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


class FakeOllamaClient:
    def health(self, timeout_seconds=None):
        return {
            "ok": True,
            "models": [
                {"name": "llama3.2:3b"},
                {"name": "nomic-embed-text"},
            ],
        }

    def generate_json(self, prompt, model=None, temperature=None, timeout_seconds=None):
        return {
            "model": model or "llama3.2:3b",
            "json": {
                "summary": "Local summary",
                "key_claims": ["Local models stay private"],
                "entities": ["Ollama"],
                "suggested_tags": ["ai"],
                "warnings": [],
            },
        }

    def embed(self, input_text, model=None, timeout_seconds=None):
        return {"model": model or "nomic-embed-text", "embeddings": [[1.0, 0.0, 0.0]]}


class Stage6ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.temp_dir.name)

        main.store = TranscriptStore(os.path.join(self.temp_dir.name, "transcripts.json"))
        main.store.add_entry(sample_entry())
        main.ai_settings_store = AISettingsStore(os.path.join(self.temp_dir.name, "ai_settings.json"))
        main.ai_artifact_store = AIArtifactStore(os.path.join(self.temp_dir.name, "ai_artifacts.json"))
        main.semantic_index_store = SemanticIndexStore(os.path.join(self.temp_dir.name, "semantic_index.json"))
        main.backend_events.clear()
        main.backend_event_id = 0
        reset_task_status()
        # Resolved at import time, so chdir alone does not isolate it when
        # YT_TRANSCRIPTS_DATA_DIR points at a real data directory.
        self.semantic_index_path = main.SEMANTIC_INDEX_PATH
        main.SEMANTIC_INDEX_PATH = Path(self.temp_dir.name) / "semantic_index.json"
        self.client = TestClient(main.app)

    def tearDown(self):
        main.SEMANTIC_INDEX_PATH = self.semantic_index_path
        os.chdir(self.cwd)
        self.temp_dir.cleanup()

    def test_ai_settings_models_and_health_endpoints(self):
        defaults = self.client.get("/api/ai/settings")
        self.assertEqual(defaults.status_code, 200)
        self.assertFalse(defaults.json()["enabled"])

        rejected = self.client.put("/api/ai/settings", json={
            "base_url": "https://example.com/api",
        })
        self.assertEqual(rejected.status_code, 400)

        updated = self.client.put("/api/ai/settings", json={
            "enabled": True,
            "base_url": "http://127.0.0.1:11434/api",
            "summary_model": "llama3.2:3b",
            "embedding_model": "nomic-embed-text",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.json()["enabled"])

        with patch.object(main, "ollama_client_for_settings", return_value=FakeOllamaClient()):
            health = self.client.post("/api/ai/health")
            models = self.client.get("/api/ai/models")

        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        self.assertIn("llama3.2:3b", models.json()["summary_models"])
        self.assertIn("nomic-embed-text", models.json()["embedding_models"])

    def test_summary_generation_persists_artifact_and_can_be_reloaded(self):
        self.client.put("/api/ai/settings", json={"enabled": True})

        with patch.object(main, "ollama_client_for_settings", return_value=FakeOllamaClient()):
            generated = self.client.post("/api/ai/transcripts/stage600001/summary")

        self.assertEqual(generated.status_code, 200)
        summary = generated.json()["summary"]
        self.assertEqual(summary["summary"], "Local summary")
        self.assertEqual(summary["suggested_tags"], ["ai"])

        reloaded = self.client.get("/api/ai/transcripts/stage600001/summary")
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["summary"]["summary"], "Local summary")

        artifacts = self.client.get("/api/ai/artifacts")
        self.assertEqual(artifacts.status_code, 200)
        self.assertEqual(artifacts.json()["artifacts"][0]["kind"], "summary")

    def test_semantic_search_uses_local_index_and_query_embedding(self):
        self.client.put("/api/ai/settings", json={"enabled": True})
        save_semantic_index(
            {
                "version": 1,
                "embedding_model": "nomic-embed-text",
                "items": [{
                    "video_id": "stage600001",
                    "title": "Stage 6 Source",
                    "channel": "AI Research",
                    "start": 0,
                    "end": 8,
                    "text": "semantic retrieval needs local private model settings",
                    "chunk_index": 0,
                    "embedding_model": "nomic-embed-text",
                    "transcript_hash": "hash",
                    "indexed_at": "2026-05-12T08:00:00Z",
                    "vector": [1.0, 0.0, 0.0],
                }],
            },
            "semantic_index.json",
        )

        with patch.object(main, "ollama_client_for_settings", return_value=FakeOllamaClient()):
            response = self.client.get("/api/semantic-search", params={"q": "local retrieval"})

        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["video_id"], "stage600001")
        self.assertEqual(result["semantic_score"], 1.0)


if __name__ == "__main__":
    unittest.main()

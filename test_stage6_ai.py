import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.ai_artifacts import AIArtifactStore, transcript_hash
from core.ai_clients import OllamaClient, OllamaClientError, ollama_client_from_settings
from core.ai_settings import AISettingsStore, normalize_ai_settings


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class AISettingsTests(unittest.TestCase):
    def test_settings_normalize_persist_and_reject_remote_base_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ai_settings.json")
            store = AISettingsStore(path)

            defaults = store.get_settings()
            self.assertFalse(defaults["enabled"])
            self.assertEqual(defaults["provider"], "ollama")
            self.assertEqual(defaults["base_url"], "http://localhost:11434/api")

            settings = store.update_settings({
                "enabled": "true",
                "provider": "OLLAMA",
                "base_url": " http://127.0.0.1:11434/api/ ",
                "summary_model": " llama3.2:3b ",
                "embedding_model": " nomic-embed-text ",
                "temperature": 9,
                "timeout_seconds": 0,
                "prompt_version": " stage6-custom ",
            })

            self.assertTrue(settings["enabled"])
            self.assertEqual(settings["base_url"], "http://127.0.0.1:11434/api")
            self.assertEqual(settings["temperature"], 2.0)
            self.assertEqual(settings["timeout_seconds"], 1)
            self.assertEqual(settings["prompt_version"], "stage6-custom")
            self.assertEqual(AISettingsStore(path).get_settings(), settings)

            with self.assertRaises(ValueError):
                store.update_settings({"base_url": "https://example.com/api"})

            allowed = normalize_ai_settings(
                {"base_url": "https://example.com/api"},
                allow_remote_base_url=True,
            )
            self.assertEqual(allowed["base_url"], "https://example.com/api")

    def test_corrupt_or_unsupported_settings_file_recovers_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ai_settings.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write("{not-json")

            self.assertEqual(AISettingsStore(path).get_settings()["provider"], "ollama")

            with open(path, "w", encoding="utf-8") as file:
                json.dump({"provider": "remote-ai"}, file)

            recovered = AISettingsStore(path).get_settings()
            self.assertEqual(recovered["provider"], "ollama")
            self.assertEqual(recovered["base_url"], "http://localhost:11434/api")


class OllamaClientTests(unittest.TestCase):
    def test_ollama_client_uses_stdlib_requests_and_parses_responses(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            if request.full_url.endswith("/tags"):
                return FakeResponse({"models": [{"name": "llama3.2:3b", "model": "llama3.2:3b"}]})
            if request.full_url.endswith("/generate"):
                payload = json.loads(request.data.decode("utf-8"))
                self.assertEqual(payload["model"], "llama3.2:3b")
                self.assertFalse(payload["stream"])
                self.assertEqual(payload["format"], "json")
                self.assertEqual(payload["options"]["temperature"], 0.1)
                return FakeResponse({
                    "model": "llama3.2:3b",
                    "response": json.dumps({"summary": "Local result"}),
                    "done": True,
                })
            if request.full_url.endswith("/embed"):
                payload = json.loads(request.data.decode("utf-8"))
                self.assertEqual(payload["model"], "nomic-embed-text")
                self.assertEqual(payload["input"], "hello")
                return FakeResponse({
                    "model": "nomic-embed-text",
                    "embeddings": [[0.1, 0.2]],
                })
            raise AssertionError(f"Unexpected URL {request.full_url}")

        client = OllamaClient(
            base_url="http://localhost:11434/api",
            timeout_seconds=7,
            default_model="llama3.2:3b",
            default_embedding_model="nomic-embed-text",
            temperature=0.2,
        )

        with patch("core.ai_clients.urlopen", side_effect=fake_urlopen):
            models = client.list_models()
            health = client.health()
            generated = client.generate_json("summarize", temperature=0.1)
            embedding = client.embed("hello")

        self.assertEqual(models[0]["name"], "llama3.2:3b")
        self.assertTrue(health["ok"])
        self.assertEqual(generated["json"]["summary"], "Local result")
        self.assertEqual(embedding["embeddings"], [[0.1, 0.2]])
        self.assertTrue(all(timeout == 7 for _, timeout in requests))
        self.assertTrue(all(request.full_url.startswith("http://localhost:11434/api/") for request, _ in requests))

    def test_ollama_client_reports_unhealthy_and_rejects_bad_json(self):
        client = ollama_client_from_settings({
            "base_url": "http://localhost:11434/api",
            "summary_model": "llama3.2:3b",
            "embedding_model": "nomic-embed-text",
            "timeout_seconds": 3,
        })

        with patch.object(client, "list_models", side_effect=OllamaClientError("offline")):
            self.assertFalse(client.health()["ok"])

        with patch.object(client, "_request_json", return_value={"response": "not json"}):
            with self.assertRaises(OllamaClientError):
                client.generate_json("bad")

        with self.assertRaises(ValueError):
            OllamaClient(base_url="https://example.com/api")

    def test_runtime_base_url_override_reaches_host_ollama_from_docker(self):
        settings = {
            "base_url": "http://localhost:11434/api",
            "summary_model": "llama3.2:3b",
            "embedding_model": "nomic-embed-text",
            "timeout_seconds": 3,
        }

        with patch.dict(
            os.environ,
            {"YT_TRANSCRIPTS_OLLAMA_BASE_URL": "http://host.docker.internal:11434/api"},
        ):
            client = ollama_client_from_settings(settings)

        self.assertEqual(client.base_url, "http://host.docker.internal:11434/api")


class AIArtifactStoreTests(unittest.TestCase):
    def test_artifacts_persist_video_summaries_comparisons_timelines_and_generic_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ai_artifacts.json")
            store = AIArtifactStore(path)
            transcript = {
                "transcript": "Line one\nLine two",
                "segments": [{"text": "ignored when transcript text exists"}],
            }
            expected_hash = transcript_hash(transcript)

            summary = store.save_video_summary(
                "video001",
                {"summary": "Short summary"},
                transcript=transcript,
                model="llama3.2:3b",
                prompt_version="stage6-v1",
            )
            comparison = store.save_comparison(
                ["video001", "video002", "video001"],
                {"shared_themes": ["local ai"]},
                model="llama3.2:3b",
            )
            timeline = store.save_timeline(
                [{"time": "00:00", "event": "Intro"}],
                video_id="video001",
                model="llama3.2:3b",
            )
            generic = store.save_generic_run(
                "cluster",
                {"clusters": []},
                input_reference="library",
                status="failed",
                error="model unavailable",
            )

            self.assertEqual(summary["transcript_hash"], expected_hash)
            self.assertEqual(summary["provider"], "ollama")
            self.assertEqual(summary["status"], "success")
            self.assertIsNone(summary["error"])
            self.assertIn("generated_at", summary)
            self.assertEqual(comparison["video_ids"], ["video001", "video002"])
            self.assertEqual(timeline["video_id"], "video001")
            self.assertEqual(generic["status"], "failed")
            self.assertEqual(generic["error"], "model unavailable")

            reloaded = AIArtifactStore(path)
            latest = reloaded.latest_video_summary("video001", expected_hash)
            self.assertEqual(latest["content"]["summary"], "Short summary")
            self.assertEqual(len(reloaded.list_comparisons()), 1)
            self.assertEqual(len(reloaded.list_timelines("video001")), 1)
            self.assertEqual(len(reloaded.list_generic_runs("cluster")), 1)

    def test_artifact_store_recovers_from_corrupt_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "ai_artifacts.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write("{not-json")

            store = AIArtifactStore(path)

            self.assertEqual(store.list_video_summaries(), [])
            self.assertEqual(store.list_comparisons(), [])


if __name__ == "__main__":
    unittest.main()

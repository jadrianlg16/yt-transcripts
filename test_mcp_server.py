import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mcp_server
from core.sqlite_store import SQLiteTranscriptStore


def sample_entry(video_id: str, title: str, transcript: str) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "channel": "Agent Lab",
        "saved_at": "2026-08-04 10:00",
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript": transcript,
        "segments": [
            {"text": transcript, "start": 0, "duration": 12},
        ],
    }


class FakeEmbeddingClient:
    def embed(self, query, model=None, timeout_seconds=None):
        return {"embeddings": [[1.0, 0.0]], "model": model}


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.previous_data_dir = os.environ.get("YT_TRANSCRIPTS_DATA_DIR")
        self.previous_project_root = mcp_server.PROJECT_ROOT
        os.environ["YT_TRANSCRIPTS_DATA_DIR"] = str(self.data_dir)
        mcp_server.PROJECT_ROOT = self.data_dir

        self.entries = [
            sample_entry(
                "agent000001",
                "Building an AI agent system&#39;s architecture",
                "A frontier agent uses tools, memory, delegation, and verification.",
            ),
            sample_entry(
                "vector00001",
                "Orchestrating reliable workflows",
                "Planning and evaluation improve long-running automation.",
            ),
        ]
        (self.data_dir / "transcripts_store.json").write_text(
            json.dumps(self.entries),
            encoding="utf-8",
        )
        (self.data_dir / "mcp_settings.json").write_text(
            json.dumps({"enabled": True}),
            encoding="utf-8",
        )
        (self.data_dir / "ai_settings.json").write_text(
            json.dumps({"enabled": False}),
            encoding="utf-8",
        )

    def tearDown(self):
        if self.previous_data_dir is None:
            os.environ.pop("YT_TRANSCRIPTS_DATA_DIR", None)
        else:
            os.environ["YT_TRANSCRIPTS_DATA_DIR"] = self.previous_data_dir
        mcp_server.PROJECT_ROOT = self.previous_project_root
        self.temp_dir.cleanup()

    def test_standard_search_and_fetch_return_frontier_compatible_documents(self):
        search_output = mcp_server.search("AI agent system")

        self.assertIsInstance(search_output, mcp_server.SearchOutput)
        self.assertEqual(search_output.results[0].id, "agent000001")
        self.assertEqual(
            search_output.results[0].title,
            "Building an AI agent system's architecture",
        )
        self.assertEqual(
            search_output.results[0].url,
            "https://www.youtube.com/watch?v=agent000001",
        )

        fetch_output = mcp_server.fetch("agent000001")
        self.assertIsInstance(fetch_output, mcp_server.FetchOutput)
        self.assertEqual(fetch_output.text, self.entries[0]["transcript"])
        self.assertEqual(fetch_output.metadata["channel"], "Agent Lab")
        self.assertEqual(fetch_output.metadata["storage_backend"], "json")

        with self.assertRaises(ValueError):
            mcp_server.fetch("missing-video")

    def test_standard_tools_publish_exact_typed_output_schemas(self):
        tools = {
            tool.name: tool
            for tool in asyncio.run(mcp_server.mcp.list_tools())
        }

        search_schema = tools["search"].outputSchema
        fetch_schema = tools["fetch"].outputSchema
        self.assertEqual(search_schema["required"], ["results"])
        self.assertEqual(
            search_schema["$defs"]["SearchResult"]["required"],
            ["id", "title", "url"],
        )
        self.assertEqual(fetch_schema["required"], ["id", "title", "text", "url"])

    def test_sqlite_archive_uses_fts_for_lexical_candidates(self):
        store = SQLiteTranscriptStore(self.data_dir / "transcripts_store.sqlite3")
        for entry in self.entries:
            store.add_entry(entry)

        entries, storage = mcp_server._load_transcripts()
        results, diagnostics = mcp_server._hybrid_search_entries(
            entries,
            "AI agent system",
            limit=10,
        )

        self.assertEqual(storage["backend"], "sqlite")
        self.assertEqual(diagnostics["lexical_method"], "sqlite_fts")
        self.assertEqual(results[0]["video_id"], "agent000001")

    def test_hybrid_search_fuses_lexical_and_real_vector_rankings(self):
        (self.data_dir / "ai_settings.json").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "provider": "ollama",
                    "base_url": "http://localhost:11434/api",
                    "summary_model": "llama3.2:3b",
                    "embedding_model": "nomic-embed-text",
                    "temperature": 0.2,
                    "timeout_seconds": 10,
                    "prompt_version": "test",
                }
            ),
            encoding="utf-8",
        )
        (self.data_dir / "semantic_index.json").write_text(
            json.dumps(
                {
                    "embedding_model": "nomic-embed-text",
                    "items": [
                        {
                            "video_id": "vector00001",
                            "title": "Orchestrating reliable workflows",
                            "channel": "Agent Lab",
                            "text": "semantic agent orchestration",
                            "start": 0,
                            "end": 12,
                            "chunk_index": 0,
                            "embedding_model": "nomic-embed-text",
                            "vector": [1.0, 0.0],
                        },
                        {
                            "video_id": "agent000001",
                            "title": "Building an AI agent system",
                            "channel": "Agent Lab",
                            "text": "tools and memory",
                            "start": 0,
                            "end": 12,
                            "chunk_index": 0,
                            "embedding_model": "nomic-embed-text",
                            "vector": [0.0, 1.0],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(
            mcp_server,
            "ollama_client_from_settings",
            return_value=FakeEmbeddingClient(),
        ):
            results, diagnostics = mcp_server._hybrid_search_entries(
                self.entries,
                "agent system",
                limit=10,
            )

        by_id = {result["video_id"]: result for result in results}
        self.assertEqual(diagnostics["method"], "hybrid_rrf")
        self.assertTrue(diagnostics["semantic"]["used"])
        self.assertEqual(by_id["agent000001"]["lexical_rank"], 1)
        self.assertEqual(by_id["vector00001"]["semantic_rank"], 1)


if __name__ == "__main__":
    unittest.main()

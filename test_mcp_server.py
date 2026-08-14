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

    def test_advertised_tool_names_match_the_registered_mcp_tools(self):
        import main

        registered = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}

        self.assertEqual(set(main.MCP_TOOL_NAMES), registered)

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


def segmented_entry(video_id: str, title: str, sentences: list[str], channel: str = "Agent Lab") -> dict:
    """Entry whose captions are short fragments, the way real YouTube captions arrive."""
    segments = []
    start = 0.0
    for sentence in sentences:
        for fragment in sentence.split(" | "):
            segments.append({"text": fragment, "start": start, "duration": 4.0})
            start += 4.0
    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "saved_at": "2026-08-04 10:00",
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript": " ".join(s["text"] for s in segments),
        "segments": segments,
    }


class TimecodeAndLinkTests(unittest.TestCase):
    def test_timecode_formats_minutes_and_hours(self):
        self.assertEqual(mcp_server._timecode(0), "0:00")
        self.assertEqual(mcp_server._timecode(65), "1:05")
        self.assertEqual(mcp_server._timecode(623), "10:23")
        self.assertEqual(mcp_server._timecode(3725), "1:02:05")

    def test_timecode_survives_junk_input(self):
        self.assertEqual(mcp_server._timecode(None), "0:00")
        self.assertEqual(mcp_server._timecode("not a number"), "0:00")
        self.assertEqual(mcp_server._timecode(-30), "0:00")

    def test_passage_url_deep_links_to_the_spoken_moment(self):
        entry = {"video_id": "agent000001", "source_url": "https://www.youtube.com/watch?v=agent000001"}
        self.assertEqual(
            mcp_server._passage_url(entry, 623),
            "https://www.youtube.com/watch?v=agent000001&t=623s",
        )

    def test_passage_url_builds_a_canonical_link_when_the_source_url_is_missing(self):
        self.assertEqual(
            mcp_server._passage_url({"video_id": "agent000001"}, 12.7),
            "https://www.youtube.com/watch?v=agent000001&t=12s",
        )


class WindowScoreTests(unittest.TestCase):
    def test_partial_term_coverage_still_scores(self):
        """The regression that made passages impossible: requiring every term."""
        terms = ["agent", "memory", "rag", "vector", "search"]
        score = mcp_server._window_score("agent memory is the hard part", terms, "")
        self.assertGreater(score, 0)

    def test_more_covered_terms_outrank_fewer(self):
        terms = ["agent", "memory", "vector"]
        broad = mcp_server._window_score("agent memory and vector stores", terms, "")
        narrow = mcp_server._window_score("agent behaviour in general", terms, "")
        self.assertGreater(broad, narrow)

    def test_exact_phrase_outranks_the_same_terms_scattered(self):
        terms = ["vector", "search"]
        phrase = "vector search"
        exact = mcp_server._window_score("he demoted vector search entirely", terms, phrase)
        scattered = mcp_server._window_score("a vector store and a keyword search", terms, phrase)
        self.assertGreater(exact, scattered)

    def test_unrelated_text_scores_zero(self):
        self.assertEqual(mcp_server._window_score("a totally unrelated sentence", ["kubernetes"], ""), 0.0)


class SearchPassagesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.previous_data_dir = os.environ.get("YT_TRANSCRIPTS_DATA_DIR")
        self.previous_project_root = mcp_server.PROJECT_ROOT
        os.environ["YT_TRANSCRIPTS_DATA_DIR"] = str(self.data_dir)
        mcp_server.PROJECT_ROOT = self.data_dir

        memory_talk = [
            "classic rag was built for chatbot question answering | not for agent work at all",
            "vector search finds chunks that are mathematically closest | to the query you asked",
            "an agent needs a bundle assembled in the right shape | not three similar paragraphs",
            "the retrieval unit has to match the work | a chunk for an faq a table for finance",
        ]
        graph_talk = [
            "graph rag handles relational knowledge | that chunks simply cannot carry",
            "some agent work is relational at its core | which suppliers connect to which shipments",
        ]
        unrelated = ["a video about helium supply | and semiconductor fabrication capacity"]

        self.entries = [
            segmented_entry("memory00001", "Vector search demoted", memory_talk),
            segmented_entry("graph000001", "Graph rag explained", graph_talk),
            segmented_entry("helium00001", "Helium supply", unrelated, channel="Supply Chain"),
        ]
        (self.data_dir / "transcripts_store.json").write_text(json.dumps(self.entries), encoding="utf-8")
        (self.data_dir / "mcp_settings.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
        (self.data_dir / "ai_settings.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")

    def tearDown(self):
        if self.previous_data_dir is None:
            os.environ.pop("YT_TRANSCRIPTS_DATA_DIR", None)
        else:
            os.environ["YT_TRANSCRIPTS_DATA_DIR"] = self.previous_data_dir
        mcp_server.PROJECT_ROOT = self.previous_project_root
        self.temp_dir.cleanup()

    def test_multi_term_query_returns_passages_not_documents(self):
        result = mcp_server.search_passages("agent rag vector retrieval", limit=6, window_segments=4)

        self.assertGreater(result["count"], 0)
        passage = result["passages"][0]
        self.assertIn("start_timecode", passage)
        self.assertIn("&t=", passage["url"])
        self.assertEqual(passage["content_type"], "verbatim_transcript")
        # A passage is a slice, never the whole document.
        whole = next(e for e in self.entries if e["video_id"] == passage["video_id"])["transcript"]
        self.assertLess(len(passage["text"]), len(whole))

    def test_results_are_spread_across_videos_by_the_per_video_cap(self):
        result = mcp_server.search_passages(
            "agent rag vector retrieval", limit=6, max_per_video=1, window_segments=4
        )

        video_ids = [passage["video_id"] for passage in result["passages"]]
        self.assertEqual(len(video_ids), len(set(video_ids)))
        self.assertEqual(result["videos_represented"], len(video_ids))

    def test_limit_bounds_the_response(self):
        result = mcp_server.search_passages("agent rag vector retrieval", limit=2, window_segments=4)

        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["passages"]), 2)

    def test_passages_from_one_video_do_not_overlap(self):
        result = mcp_server.search_passages(
            "agent rag vector retrieval bundle chunk", limit=10, max_per_video=10, window_segments=4
        )

        starts = [p["start"] for p in result["passages"] if p["video_id"] == "memory00001"]
        self.assertEqual(len(starts), len(set(starts)))

    def test_channel_filter_excludes_other_channels(self):
        result = mcp_server.search_passages(
            "helium semiconductor", limit=5, channel="Agent Lab", window_segments=4
        )

        self.assertEqual(result["count"], 0)

    def test_query_without_searchable_terms_returns_nothing(self):
        result = mcp_server.search_passages("a", limit=5)

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["retrieval"]["method"], "none")

    def test_response_reports_its_own_token_cost(self):
        result = mcp_server.search_passages("agent rag vector retrieval", limit=6, window_segments=4)

        chars = sum(len(p["text"]) for p in result["passages"])
        self.assertEqual(result["estimated_tokens"], chars // mcp_server.CHARS_PER_TOKEN_ESTIMATE)

    def test_disabled_mcp_blocks_passage_search(self):
        (self.data_dir / "mcp_settings.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")

        result = mcp_server.search_passages("agent rag vector retrieval")

        self.assertFalse(result.get("enabled", False))
        self.assertNotIn("passages", result)


class FetchCapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.previous_data_dir = os.environ.get("YT_TRANSCRIPTS_DATA_DIR")
        self.previous_project_root = mcp_server.PROJECT_ROOT
        self.previous_fetch_chars = os.environ.get("YT_TRANSCRIPTS_MCP_FETCH_CHARS")
        os.environ["YT_TRANSCRIPTS_DATA_DIR"] = str(self.data_dir)
        mcp_server.PROJECT_ROOT = self.data_dir

        self.long_entry = sample_entry("longvid0001", "A very long talk", "memory " * 20000)
        (self.data_dir / "transcripts_store.json").write_text(
            json.dumps([self.long_entry]), encoding="utf-8"
        )
        (self.data_dir / "mcp_settings.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
        (self.data_dir / "ai_settings.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")

    def tearDown(self):
        for name, previous in (
            ("YT_TRANSCRIPTS_DATA_DIR", self.previous_data_dir),
            ("YT_TRANSCRIPTS_MCP_FETCH_CHARS", self.previous_fetch_chars),
        ):
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        mcp_server.PROJECT_ROOT = self.previous_project_root
        self.temp_dir.cleanup()

    def test_fetch_caps_a_runaway_transcript_and_says_so(self):
        output = mcp_server.fetch("longvid0001")

        self.assertEqual(len(output.text), mcp_server.MAX_TRANSCRIPT_CHARS)
        self.assertTrue(output.metadata["text_truncated"])
        self.assertEqual(output.metadata["text_char_count"], len(self.long_entry["transcript"]))
        self.assertGreater(output.metadata["estimated_tokens"], 0)

    def test_fetch_cap_is_configurable(self):
        os.environ["YT_TRANSCRIPTS_MCP_FETCH_CHARS"] = "1000"

        output = mcp_server.fetch("longvid0001")

        self.assertEqual(len(output.text), 1000)
        self.assertEqual(output.metadata["max_chars"], 1000)
        self.assertTrue(output.metadata["text_truncated"])

    def test_a_normal_transcript_is_returned_whole(self):
        (self.data_dir / "transcripts_store.json").write_text(
            json.dumps([sample_entry("shortvid001", "Short", "a compact transcript")]),
            encoding="utf-8",
        )

        output = mcp_server.fetch("shortvid001")

        self.assertEqual(output.text, "a compact transcript")
        self.assertFalse(output.metadata["text_truncated"])


if __name__ == "__main__":
    unittest.main()

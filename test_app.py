import os
import tempfile
import unittest
from types import SimpleNamespace

from core.fetcher import _metadata_from_html, _segment_to_dict, extract_video_id
from core.research import library_stats, search_entries
from core.store import TranscriptStore


class FetcherTests(unittest.TestCase):
    def test_extract_video_id_supports_common_youtube_urls(self):
        test_urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ]

        for url, expected in test_urls:
            with self.subTest(url=url):
                self.assertEqual(extract_video_id(url), expected)

    def test_extract_video_id_rejects_invalid_values(self):
        invalid_urls = [
            "",
            "https://www.youtube.com/watch?v=short",
            "https://example.com/watch?v=dQw4w9WgXcQ",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertIsNone(extract_video_id(url))

    def test_segment_to_dict_handles_dict_and_object_items(self):
        dict_segment = {"text": "hello", "start": 1.2, "duration": 3.4}
        object_segment = SimpleNamespace(text="world", start=5.6, duration=7.8)

        self.assertEqual(_segment_to_dict(dict_segment), dict_segment)
        self.assertEqual(
            _segment_to_dict(object_segment),
            {"text": "world", "start": 5.6, "duration": 7.8},
        )

    def test_metadata_from_html_decodes_youtube_json_metadata(self):
        html = r'''
        <script>
        var ytInitialPlayerResponse = {
          "videoDetails": {
            "title": "Karpathy&#39;s Agent",
            "author": "AI News \u0026 Strategy Daily | Nate B Jones"
          },
          "microformat": {
            "playerMicroformatRenderer": {
              "publishDate": "2026-05-10"
            }
          }
        };
        </script>
        '''

        metadata = _metadata_from_html(html)

        self.assertEqual(metadata["title"], "Karpathy's Agent")
        self.assertEqual(metadata["channel"], "AI News & Strategy Daily | Nate B Jones")
        self.assertEqual(metadata["uploaded_at"], "2026-05-10")


class TranscriptStoreTests(unittest.TestCase):
    def test_add_entry_deduplicates_by_video_id_and_delete_removes_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "store.json")
            store = TranscriptStore(file_path)

            store.add_entry({"video_id": "abc123def45", "title": "Original"})
            store.add_entry({"video_id": "abc123def45", "title": "Updated"})
            store.add_entry({"video_id": "xyz123def45", "title": "Second"})

            self.assertEqual(len(store.all_entries()), 2)
            self.assertEqual(store.all_entries()[0]["title"], "Updated")

            store.delete_entry("abc123def45")

            self.assertEqual(
                store.all_entries(),
                [{"video_id": "xyz123def45", "title": "Second"}],
            )


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {
                "video_id": "abc123def45",
                "title": "AI Agents and Review Bottlenecks",
                "channel": "Research Channel",
                "saved_at": "2026-05-01 10:00",
                "transcript": "AI agents produce code quickly. Human review is the bottleneck.",
                "segments": [
                    {"text": "AI agents produce code quickly.", "start": 0, "duration": 3},
                    {"text": "Human review is the bottleneck.", "start": 3, "duration": 4},
                ],
            },
            {
                "video_id": "xyz123def45",
                "title": "Database Notes",
                "channel": "Storage Channel",
                "saved_at": "2026-05-02 10:00",
                "transcript": "Local storage needs indexing before semantic search.",
                "segments": [
                    {"text": "Local storage needs indexing.", "start": 0, "duration": 2},
                    {"text": "Semantic search comes later.", "start": 2, "duration": 3},
                ],
            },
        ]

    def test_library_stats_summarizes_local_archive(self):
        stats = library_stats(self.entries)

        self.assertEqual(stats["transcript_count"], 2)
        self.assertEqual(stats["unique_channels"], 2)
        self.assertEqual(stats["total_segments"], 4)
        self.assertEqual(stats["total_duration_seconds"], 12)
        self.assertEqual(stats["latest_saved_at"], "2026-05-02 10:00")
        self.assertEqual(stats["channel_counts"][0]["channel"], "Research Channel")

    def test_search_entries_returns_ranked_segment_matches(self):
        results = search_entries(self.entries, "review bottleneck")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["video_id"], "abc123def45")
        self.assertEqual(results[0]["matches"][0]["start"], 3)

    def test_search_entries_supports_channel_filter(self):
        results = search_entries(
            self.entries,
            "search",
            channel="Storage Channel",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["video_id"], "xyz123def45")


if __name__ == "__main__":
    unittest.main()

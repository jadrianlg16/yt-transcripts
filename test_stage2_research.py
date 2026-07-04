import unittest

from core.fetcher import extract_video_id
from core.research import library_stats, search_entries


class Stage1UrlExtractionRegressionTests(unittest.TestCase):
    def test_extract_video_id_supports_protocol_less_youtube_url(self):
        self.assertEqual(
            extract_video_id("youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_supports_mobile_youtube_url(self):
        self.assertEqual(
            extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )


class Stage2ResearchStatsTests(unittest.TestCase):
    def test_library_stats_surfaces_useful_terms_without_obvious_stop_words(self):
        entries = [
            {
                "video_id": "alpha000001",
                "title": "AI Research Notes",
                "channel": "Research Lab",
                "saved_at": "2026-05-01 10:00",
                "transcript": (
                    "the the and and with with research research research "
                    "agents agents retrieval indexing"
                ),
                "segments": [{"text": "research agents retrieval", "start": 0, "duration": 5}],
            },
            {
                "video_id": "beta0000002",
                "title": "Storage Notes",
                "channel": "Research Lab",
                "saved_at": "2026-05-02 10:00",
                "transcript": (
                    "this this that that for for storage storage search metadata"
                ),
                "segments": [{"text": "storage search metadata", "start": 0, "duration": 7}],
            },
        ]

        stats = library_stats(entries)
        terms = [item["term"] for item in stats["top_keywords"]]

        self.assertIn("research", terms)
        self.assertIn("agents", terms)
        self.assertIn("storage", terms)
        self.assertNotIn("the", terms)
        self.assertNotIn("and", terms)
        self.assertNotIn("with", terms)
        self.assertNotIn("this", terms)
        self.assertNotIn("that", terms)


class Stage2SearchMetadataAndSortingTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {
                "video_id": "newest00001",
                "title": "Newest Research",
                "channel": "Stage 2",
                "saved_at": "2026-05-04 10:00",
                "transcript": "analysis match",
                "segments": [{"text": "analysis match", "start": 0, "duration": 5}],
            },
            {
                "video_id": "longest0001",
                "title": "Longest Research",
                "channel": "Stage 2",
                "saved_at": "2026-05-02 10:00",
                "transcript": "analysis match extra words for longest entry",
                "segments": [{"text": "analysis match", "start": 0, "duration": 40}],
            },
            {
                "video_id": "matches0001",
                "title": "Matches Research",
                "channel": "Stage 2",
                "saved_at": "2026-05-01 10:00",
                "transcript": "analysis match analysis match analysis",
                "segments": [
                    {"text": "analysis match", "start": 0, "duration": 3},
                    {"text": "analysis again", "start": 3, "duration": 3},
                ],
            },
            {
                "video_id": "alpha000001",
                "title": "Alpha Research",
                "channel": "Stage 2",
                "saved_at": "2026-05-03 10:00",
                "transcript": "analysis match",
                "segments": [{"text": "analysis match", "start": 0, "duration": 8}],
            },
        ]

    def test_search_entries_exposes_stage2_metadata_fields(self):
        results = search_entries(self.entries, "analysis")

        by_id = {result["video_id"]: result for result in results}
        result = by_id["longest0001"]

        self.assertEqual(result["word_count"], 7)
        self.assertEqual(result["duration_seconds"], 40)
        self.assertGreaterEqual(result["match_count"], 1)

    def test_search_entries_supports_newest_sort(self):
        results = search_entries(self.entries, "analysis", sort="newest")

        self.assertEqual([result["video_id"] for result in results], [
            "newest00001",
            "alpha000001",
            "longest0001",
            "matches0001",
        ])

    def test_search_entries_supports_longest_sort(self):
        results = search_entries(self.entries, "analysis", sort="longest")

        self.assertEqual(results[0]["video_id"], "longest0001")
        self.assertEqual(results[0]["duration_seconds"], 40)

    def test_search_entries_supports_matches_sort(self):
        results = search_entries(self.entries, "analysis", sort="matches")

        self.assertEqual(results[0]["video_id"], "matches0001")
        self.assertGreater(results[0]["match_count"], results[1]["match_count"])

    def test_search_entries_supports_title_sort(self):
        results = search_entries(self.entries, "analysis", sort="title")

        self.assertEqual([result["title"] for result in results], [
            "Alpha Research",
            "Longest Research",
            "Matches Research",
            "Newest Research",
        ])


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path

from core.topics import build_topic_model, related_videos, top_topics, video_topics
from core.vault import export_vault, note_name, render_note


def entry(video_id, title, transcript, channel="Test Channel"):
    sentences = [s.strip() for s in transcript.split(".") if s.strip()]
    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "saved_at": "2026-08-19 10:00",
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript": transcript,
        "segments": [
            {"text": s, "start": i * 12.0, "duration": 12.0}
            for i, s in enumerate(sentences)
        ],
    }


def archive():
    return [
        entry("mem00000001", "Agent memory explained",
              "memory. memory. memory systems for agents. retrieval matters. agents need memory."),
        entry("mem00000002", "Memory and retrieval",
              "memory. retrieval. retrieval. memory retrieval pipelines. agents again."),
        entry("cook00000001", "Sourdough bread basics",
              "sourdough. sourdough starter. bread flour hydration. baking bread."),
    ]


class TopicModelTests(unittest.TestCase):
    def setUp(self):
        self.entries = archive()
        self.model = build_topic_model(self.entries)
        self.by_id = {e["video_id"]: e for e in self.entries}

    def test_a_video_gets_topics_from_its_own_distinctive_words(self):
        topics = [t["topic"] for t in video_topics(self.model, "cook00000001")]

        self.assertTrue(any("sourdough" in t for t in topics), topics)
        self.assertFalse(any("memory" in t for t in topics), topics)

    def test_videos_about_the_same_thing_are_linked(self):
        related = related_videos(self.model, "mem00000001", self.by_id)

        self.assertTrue(related)
        self.assertEqual(related[0]["video_id"], "mem00000002")
        self.assertTrue(related[0]["shared_topics"])

    def test_an_unrelated_video_is_not_linked(self):
        related = related_videos(self.model, "cook00000001", self.by_id)

        self.assertNotIn("mem00000001", [r["video_id"] for r in related])

    def test_top_topics_only_include_subjects_shared_by_more_than_one_video(self):
        for topic in top_topics(self.model):
            self.assertGreater(topic["video_count"], 1)

    def test_an_empty_archive_does_not_crash(self):
        model = build_topic_model([])

        self.assertEqual(model["video_count"], 0)
        self.assertEqual(top_topics(model), [])
        self.assertEqual(related_videos(model, "missing", {}), [])


class VaultExportTests(unittest.TestCase):
    def test_note_names_are_readable_and_safe_for_a_filesystem(self):
        name = note_name({"video_id": "abc12345678", "title": 'A/B: "test" <weird>'})

        self.assertIn("abc12345678", name)
        for char in '<>:"/\|?*':
            self.assertNotIn(char, name)

    def test_a_note_carries_facts_timestamps_and_links(self):
        entries = archive()
        model = build_topic_model(entries)
        by_id = {e["video_id"]: e for e in entries}
        source = by_id["mem00000001"]

        note = render_note(
            source,
            video_topics(model, "mem00000001"),
            related_videos(model, "mem00000001", by_id),
            by_id,
        )

        self.assertTrue(note.startswith("---"))
        self.assertIn('video_id: "mem00000001"', note)
        self.assertIn("## Transcript", note)
        self.assertIn("&t=", note)                       # clickable timestamps
        self.assertIn("[[", note)                        # wiki-link to a related note

    def test_export_writes_one_note_per_video_plus_an_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "vault"

            result = export_vault(archive(), folder)

            self.assertEqual(result["notes"], 3)
            notes = sorted(p.name for p in folder.glob("*.md"))
            self.assertEqual(len(notes), 4)              # 3 videos + index
            self.assertIn("Index.md", notes)

            index = (folder / "Index.md").read_text(encoding="utf-8")
            self.assertIn("Transcript Archive", index)
            self.assertIn("[[", index)

    def test_export_is_repeatable_without_duplicating_notes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "vault"
            export_vault(archive(), folder)

            export_vault(archive(), folder)

            self.assertEqual(len(list(folder.glob("*.md"))), 4)

    def test_a_video_without_segments_still_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "vault"
            bare = {"video_id": "bare00000001", "title": "Bare", "channel": "C",
                    "transcript": "just text", "segments": []}

            result = export_vault([bare], folder)

            self.assertEqual(result["notes"], 1)
            note = next(folder.glob("Bare*.md")).read_text(encoding="utf-8")
            self.assertIn("just text", note)


if __name__ == "__main__":
    unittest.main()

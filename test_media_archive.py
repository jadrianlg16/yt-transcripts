import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import media_archive


class FakeStream:
    """Behaves like subprocess stdout: iterable and closable."""

    def __init__(self, lines):
        self._lines = iter(lines)

    def __iter__(self):
        return self._lines

    def close(self):
        return None


class ArchiveDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media = Path(self.temp_dir.name) / "media"
        self.media.mkdir()
        self.patcher = patch.dict(
            os.environ, {"YT_TRANSCRIPTS_MEDIA_DIR": str(self.media)}, clear=False
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def store(self, video_id, suffix=".mp4", size=1024):
        path = self.media / f"{video_id}{suffix}"
        path.write_bytes(b"x" * size)
        return path


class ArchivedLookupTests(ArchiveDirectoryTests):
    def test_a_stored_file_makes_a_video_archived(self):
        self.store("abcdefghijk")

        self.assertTrue(media_archive.is_archived("abcdefghijk"))
        self.assertEqual(media_archive.archived_path("abcdefghijk").name, "abcdefghijk.mp4")

    def test_a_video_with_no_file_is_not_archived(self):
        self.assertFalse(media_archive.is_archived("abcdefghijk"))
        self.assertIsNone(media_archive.archived_path("abcdefghijk"))

    def test_unrelated_files_are_ignored(self):
        (self.media / "notes.txt").write_text("not a video")
        (self.media / "abcdefghijk.txt").write_text("also not a video")

        self.assertEqual(media_archive.archived_video_ids(), set())

    def test_a_path_that_is_not_a_video_id_is_refused(self):
        """The id lands in a filesystem path, so anything else must be rejected."""
        for bad in ("../../etc/passwd", "abc", "", "a" * 40, "abcdefghij/k"):
            with self.subTest(bad=bad):
                self.assertIsNone(media_archive.archived_path(bad))

    def test_deleting_the_file_un_archives_the_video(self):
        self.store("abcdefghijk")

        self.assertTrue(media_archive.remove_archived("abcdefghijk"))

        self.assertFalse(media_archive.is_archived("abcdefghijk"))
        self.assertFalse(media_archive.remove_archived("abcdefghijk"))


class ArchiveListingTests(ArchiveDirectoryTests):
    def test_listing_joins_titles_from_the_transcript_archive(self):
        self.store("abcdefghijk", size=2048)
        entries = {"abcdefghijk": {"title": "A talk", "channel": "Some channel"}}

        items = media_archive.list_archived(entries)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A talk")
        self.assertEqual(items[0]["channel"], "Some channel")
        self.assertEqual(items[0]["size_bytes"], 2048)
        self.assertTrue(items[0]["has_transcript"])

    def test_a_video_with_no_transcript_still_lists(self):
        self.store("abcdefghijk")

        items = media_archive.list_archived({})

        self.assertEqual(items[0]["title"], "abcdefghijk")
        self.assertFalse(items[0]["has_transcript"])

    def test_storage_summary_counts_what_is_on_disk(self):
        self.store("abcdefghijk", size=1000)
        self.store("bbcdefghijk", size=3000)

        summary = media_archive.storage_summary()

        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["used_bytes"], 4000)
        self.assertTrue(summary["exists"])

    def test_missing_from_archive_reports_what_is_not_stored(self):
        self.store("abcdefghijk")

        missing = media_archive.missing_from_archive(["abcdefghijk", "bbcdefghijk"])

        self.assertEqual(missing, ["bbcdefghijk"])


class DownloadTests(ArchiveDirectoryTests):
    def test_a_missing_ytdlp_is_reported_rather_than_crashing(self):
        with patch.object(media_archive, "ytdlp_path", return_value=None):
            with self.assertRaises(media_archive.MediaArchiveError) as caught:
                media_archive.download_video("abcdefghijk")

        self.assertIn("yt-dlp", str(caught.exception))

    def test_an_already_archived_video_is_not_downloaded_again(self):
        existing = self.store("abcdefghijk")

        with patch.object(media_archive.subprocess, "Popen") as popen:
            path = media_archive.download_video("abcdefghijk")

        self.assertEqual(path, existing)
        popen.assert_not_called()

    def test_a_bad_video_id_never_reaches_the_filesystem(self):
        with patch.object(media_archive.subprocess, "Popen") as popen:
            with self.assertRaises(media_archive.MediaArchiveError):
                media_archive.download_video("../../escape")

        popen.assert_not_called()

    def test_a_failing_download_surfaces_the_last_line(self):
        class FakeProcess:
            returncode = 1
            stdout = FakeStream(["[download]  10%", "ERROR: video is private"])

            def wait(self, timeout=None):
                return 1

        with patch.object(media_archive, "ytdlp_path", return_value="yt-dlp"), \
             patch.object(media_archive.subprocess, "Popen", return_value=FakeProcess()):
            with self.assertRaises(media_archive.MediaArchiveError) as caught:
                media_archive.download_video("abcdefghijk")

        self.assertIn("video is private", str(caught.exception))

    def test_progress_lines_are_reported_while_downloading(self):
        seen = []

        class FakeProcess:
            returncode = 0
            stdout = FakeStream(["[download]   5% of 100MiB", "not progress", "[download]  90% of 100MiB"])

            def wait(self, timeout=None):
                return 0

        media = self.media

        def fake_popen(*args, **kwargs):
            (media / "abcdefghijk.mp4").write_bytes(b"video")
            return FakeProcess()

        with patch.object(media_archive, "ytdlp_path", return_value="yt-dlp"), \
             patch.object(media_archive.subprocess, "Popen", side_effect=fake_popen):
            path = media_archive.download_video("abcdefghijk", on_progress=seen.append)

        self.assertEqual(path.name, "abcdefghijk.mp4")
        self.assertEqual(len(seen), 2, "only lines with a percentage are progress")

    def test_quality_choices_are_real_format_selectors(self):
        for quality in ("1080p", "720p", "480p", "audio"):
            with self.subTest(quality=quality):
                self.assertIn(quality, media_archive.QUALITY_FORMATS)
        self.assertIn(media_archive.DEFAULT_QUALITY, media_archive.QUALITY_FORMATS)


if __name__ == "__main__":
    unittest.main()

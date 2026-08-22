import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import main
from core import audio, speech


def export_payload(with_speakers=True):
    speakers = (
        [{"id": "S1", "label": "Host"}, {"id": "S2", "label": "Guest"}]
        if with_speakers
        else [{"id": "S1", "label": "Speaker"}]
    )
    return {
        "source": "clip.m4a",
        "language": "en",
        "speakers": speakers,
        "segments": [
            {"start": 0.0, "end": 4.0, "speaker": "Host", "text": "Welcome to the show."},
            {"start": 4.0, "end": 9.5, "speaker": "Guest", "text": "Glad to be here."},
            {"start": 9.5, "end": 12.0, "speaker": "Host", "text": "   "},
        ],
    }


def zipped(payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("transcript.json", json.dumps(payload))
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, payload=None, content=b"", status=200, text=""):
        self._payload = payload or {}
        self.content = content
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("HTTP " + str(self.status_code))


class SegmentConversionTests(unittest.TestCase):
    def test_segments_become_the_shape_the_archive_stores(self):
        segments = speech.to_transcript_segments(export_payload())

        self.assertEqual(len(segments), 2, "blank segments are dropped")
        self.assertEqual(sorted(segments[0]), ["duration", "start", "text"])
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[0]["duration"], 4.0)

    def test_speaker_labels_are_kept_when_more_than_one_person_speaks(self):
        segments = speech.to_transcript_segments(export_payload(with_speakers=True))

        self.assertTrue(segments[0]["text"].startswith("Host:"))
        self.assertTrue(segments[1]["text"].startswith("Guest:"))

    def test_a_single_speaker_is_not_labelled(self):
        segments = speech.to_transcript_segments(export_payload(with_speakers=False))

        self.assertFalse(segments[0]["text"].startswith("Host:"))

    def test_malformed_segments_are_skipped_rather_than_crashing(self):
        payload = {
            "segments": [
                None,
                "nonsense",
                {"text": ""},
                {"text": "kept", "start": "x", "end": None},
            ]
        }

        segments = speech.to_transcript_segments(payload)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["start"], 0.0)


class SpeechClientTests(unittest.TestCase):
    def test_a_finished_job_yields_language_speakers_and_segments(self):
        statuses = [
            FakeResponse({"status": "processing", "stage": "Transcribing"}),
            FakeResponse({"status": "done", "stage": "Done", "language": "en"}),
        ]
        archive = FakeResponse(content=zipped(export_payload()))

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "clip.m4a"
            audio_path.write_bytes(b"audio")

            with patch.object(speech.requests, "post", return_value=FakeResponse({"job_id": "job1"})), \
                 patch.object(speech.requests, "get", side_effect=[*statuses, archive]), \
                 patch.object(speech.time, "sleep", return_value=None):
                result = speech.transcribe_file(str(audio_path), base_url="http://speech")

        self.assertEqual(result["job_id"], "job1")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["speaker_count"], 2)
        self.assertEqual(len(result["segments"]), 2)

    def test_a_failed_job_raises_with_the_service_reason(self):
        failed = FakeResponse({"status": "error", "stage": "Failed", "error": "model missing"})

        with patch.object(speech.requests, "get", return_value=failed):
            with self.assertRaises(speech.SpeechServiceError) as caught:
                speech.wait_for_job("job1", "http://speech", sleep=lambda _: None, now=lambda: 0)

        self.assertIn("model missing", str(caught.exception))

    def test_waiting_gives_up_rather_than_polling_forever(self):
        clock = iter([0, 1, 2, 3, 4, 5, 6])
        working = FakeResponse({"status": "processing", "stage": "Transcribing"})

        with patch.object(speech.requests, "get", return_value=working):
            with self.assertRaises(speech.SpeechServiceError) as caught:
                speech.wait_for_job(
                    "job1",
                    "http://speech",
                    max_wait_seconds=2,
                    sleep=lambda _: None,
                    now=lambda: next(clock),
                )

        self.assertIn("did not finish", str(caught.exception))

    def test_an_archive_without_json_is_reported_clearly(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("transcript.txt", "just text")

        with patch.object(speech.requests, "get", return_value=FakeResponse(content=buffer.getvalue())):
            with self.assertRaises(speech.SpeechServiceError) as caught:
                speech.fetch_segments("job1", "http://speech")

        self.assertIn("no JSON", str(caught.exception))

    def test_status_reports_when_nothing_is_configured(self):
        with patch.dict(os.environ, {"YT_TRANSCRIPTS_SPEECH_URL": ""}, clear=False):
            health = speech.service_health()

        self.assertFalse(health["configured"])
        self.assertFalse(health["reachable"])


class AudioDownloadTests(unittest.TestCase):
    def test_a_missing_ytdlp_is_reported_rather_than_crashing(self):
        with patch.object(audio, "ytdlp_path", return_value=None):
            with self.assertRaises(audio.AudioDownloadError) as caught:
                audio.download_audio("abcdefghijk")

        self.assertIn("yt-dlp", str(caught.exception))

    def test_a_failing_download_surfaces_the_last_line_of_the_error(self):
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "WARNING: something\nERROR: video unavailable"

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(audio, "ytdlp_path", return_value="yt-dlp"), \
                 patch.object(audio.subprocess, "run", return_value=Failed()):
                with self.assertRaises(audio.AudioDownloadError) as caught:
                    audio.download_audio("abcdefghijk", destination_dir=temp_dir)

        self.assertIn("video unavailable", str(caught.exception))

    def test_success_returns_the_produced_file(self):
        class Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        with tempfile.TemporaryDirectory() as temp_dir:
            produced = Path(temp_dir) / "abcdefghijk.m4a"

            def fake_run(*args, **kwargs):
                produced.write_bytes(b"audio")
                return Ok()

            with patch.object(audio, "ytdlp_path", return_value="yt-dlp"), \
                 patch.object(audio.subprocess, "run", side_effect=fake_run):
                path = audio.download_audio("abcdefghijk", destination_dir=temp_dir)

            self.assertEqual(path, str(produced))


class MissingCaptionDetectionTests(unittest.TestCase):
    def test_a_captionless_video_is_recognised(self):
        self.assertTrue(
            main._looks_like_missing_captions("Could not retrieve a transcript for the video")
        )
        self.assertTrue(
            main._looks_like_missing_captions("Subtitles are disabled for this video")
        )

    def test_rate_limiting_is_not_mistaken_for_missing_captions(self):
        """Falling back to Whisper while blocked would download audio for nothing."""
        self.assertFalse(
            main._looks_like_missing_captions("YouTube is blocking requests from your IP")
        )

    def test_an_unrelated_error_is_not_a_caption_problem(self):
        self.assertFalse(main._looks_like_missing_captions("database is locked"))


if __name__ == "__main__":
    unittest.main()

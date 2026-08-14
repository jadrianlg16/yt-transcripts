import json
import unittest
from unittest.mock import patch

from core import channel_listing
from core.channel_listing import (
    ChannelListingError,
    channel_tab_url,
    list_channel_videos,
)


def lockup(video_id: str, title: str, published: str = "3 days ago") -> dict:
    return {
        "lockupViewModel": {
            "contentId": video_id,
            "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": title},
                    "metadata": {
                        "contentMetadataViewModel": {
                            "metadataRows": [{
                                "metadataParts": [
                                    {"text": {"content": "8.2K views"}},
                                    {"text": {"content": published}},
                                ]
                            }]
                        }
                    },
                }
            },
        }
    }


def page_html(data: dict) -> str:
    return (
        '<html><script>var ytInitialData = '
        + json.dumps(data)
        + ';</script><script>"INNERTUBE_API_KEY":"test-key",'
        '"INNERTUBE_CLIENT_VERSION":"2.2026.01.00"</script></html>'
    )


class FakeResponse:
    def __init__(self, text: str = "", payload: dict | None = None):
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Serves one page per tab, then one continuation payload per POST."""

    def __init__(self, pages: dict[str, dict], continuations: list[dict] | None = None):
        self.pages = pages
        self.continuations = list(continuations or [])
        self.get_urls: list[str] = []
        self.post_tokens: list[str] = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        for tab, data in self.pages.items():
            if url.endswith(f"/{tab}"):
                return FakeResponse(text=page_html(data))
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, json=None, **kwargs):
        self.post_tokens.append(json["continuation"])
        return FakeResponse(payload=self.continuations.pop(0) if self.continuations else {})

    def close(self):
        return None


class ChannelTabUrlTests(unittest.TestCase):
    def test_builds_tab_url_from_handle_forms(self):
        expected = "https://www.youtube.com/@NateBJones/videos"
        self.assertEqual(channel_tab_url("@NateBJones", "videos"), expected)
        self.assertEqual(channel_tab_url("https://www.youtube.com/@NateBJones", "videos"), expected)
        self.assertEqual(channel_tab_url("https://www.youtube.com/@NateBJones/", "videos"), expected)

    def test_replaces_an_existing_tab_instead_of_stacking_one(self):
        self.assertEqual(
            channel_tab_url("https://www.youtube.com/@NateBJones/videos", "streams"),
            "https://www.youtube.com/@NateBJones/streams",
        )

    def test_accepts_a_bare_channel_id(self):
        self.assertEqual(
            channel_tab_url("UC0C-17n9iuUQPylguM1d-lQ", "videos"),
            "https://www.youtube.com/channel/UC0C-17n9iuUQPylguM1d-lQ/videos",
        )

    def test_rejects_an_empty_channel(self):
        with self.assertRaises(ChannelListingError):
            channel_tab_url("  ", "videos")


class ListChannelVideosTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(channel_listing.time, "sleep", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_the_modern_lockup_grid(self):
        session = FakeSession({"videos": {"contents": [lockup("aaaaaaaaaaa", "First"), lockup("bbbbbbbbbbb", "Second")]}})

        videos = list_channel_videos("@test", limit=10, tabs=("videos",), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(videos[0]["title"], "First")
        self.assertEqual(videos[0]["published_text"], "3 days ago")
        self.assertEqual(videos[0]["url"], "https://www.youtube.com/watch?v=aaaaaaaaaaa")

    def test_falls_back_to_the_legacy_video_renderer(self):
        legacy = {"contents": [{"videoRenderer": {
            "videoId": "ccccccccccc",
            "title": {"runs": [{"text": "Legacy"}]},
            "publishedTimeText": {"simpleText": "1 year ago"},
        }}]}
        session = FakeSession({"videos": legacy})

        videos = list_channel_videos("@test", limit=10, tabs=("videos",), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["ccccccccccc"])
        self.assertEqual(videos[0]["title"], "Legacy")
        self.assertEqual(videos[0]["published_text"], "1 year ago")

    def test_follows_continuations_past_the_first_page(self):
        first = {
            "contents": [lockup("aaaaaaaaaaa", "First")],
            "continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "token-1"}}},
        }
        second = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {
            "continuationItems": [lockup("bbbbbbbbbbb", "Second")],
        }}]}
        session = FakeSession({"videos": first}, continuations=[second])

        videos = list_channel_videos("@test", limit=10, tabs=("videos",), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(session.post_tokens, ["token-1"])

    def test_stops_requesting_continuations_once_the_limit_is_met(self):
        first = {
            "contents": [lockup("aaaaaaaaaaa", "First"), lockup("bbbbbbbbbbb", "Second")],
            "continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "token-1"}}},
        }
        session = FakeSession({"videos": first})

        videos = list_channel_videos("@test", limit=1, tabs=("videos",), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["aaaaaaaaaaa"])
        self.assertEqual(session.post_tokens, [])

    def test_merges_tabs_and_drops_duplicate_ids(self):
        session = FakeSession({
            "videos": {"contents": [lockup("aaaaaaaaaaa", "Upload")]},
            "streams": {"contents": [lockup("aaaaaaaaaaa", "Upload"), lockup("bbbbbbbbbbb", "Stream")]},
        })

        videos = list_channel_videos("@test", limit=10, tabs=("videos", "streams"), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_ignores_non_video_lockups(self):
        playlist = {"lockupViewModel": {"contentId": "PLxxxxxxxxxx", "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST"}}
        session = FakeSession({"videos": {"contents": [playlist, lockup("aaaaaaaaaaa", "Real")]}})

        videos = list_channel_videos("@test", limit=10, tabs=("videos",), session=session)

        self.assertEqual([v["videoId"] for v in videos], ["aaaaaaaaaaa"])

    def test_raises_when_every_tab_fails(self):
        class BrokenSession(FakeSession):
            def get(self, url, **kwargs):
                return FakeResponse(text="<html>no data here</html>")

        with self.assertRaises(ChannelListingError):
            list_channel_videos("@test", limit=5, tabs=("videos",), session=BrokenSession({}))


if __name__ == "__main__":
    unittest.main()

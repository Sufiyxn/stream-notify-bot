"""YouTube live detection.

Two detection strategies are supported automatically:

* **YouTube Data API v3** (preferred) when ``YOUTUBE_API_KEY`` is set - fast,
  reliable and returns rich metadata.
* **HTML fallback** - scrapes the channel's ``/live`` page when no API key is
  available so the bot still works out of the box (at the cost of less
  metadata and lower reliability).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from platforms.base import BasePlatform, StreamInfo

_API_BASE = "https://www.googleapis.com/youtube/v3"
# Matches the JSON blob the watch page embeds so we can pull live status out
# of the HTML when no API key is configured.
_IS_LIVE_RE = re.compile(r'"isLiveNow"\s*:\s*(true|false)')
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([\w-]{11})"')
_TITLE_RE = re.compile(r'<meta\s+name="title"\s+content="([^"]+)"')


class YouTubePlatform(BasePlatform):
    """Detect live streams for a single YouTube channel."""

    name = "youtube"
    display_name = "YouTube"
    emoji = "📺"

    @property
    def configured(self) -> bool:
        return bool(self.config.youtube_channel_id)

    async def get_stream_info(self) -> StreamInfo | None:
        if not self.configured:
            return None
        self.log.info("Checking YouTube...")
        if self.config.youtube_api_key:
            return await self._via_api()
        return await self._via_scrape()

    async def _via_api(self) -> StreamInfo | None:
        """Detect the active live broadcast using the Data API v3."""
        channel_id = self.config.youtube_channel_id
        search = await self._request_json(
            f"{_API_BASE}/search",
            params={
                "part": "snippet",
                "channelId": channel_id or "",
                "eventType": "live",
                "type": "video",
                "key": self.config.youtube_api_key or "",
            },
        )
        if not search or not search.get("items"):
            return None

        item = search["items"][0]
        video_id = item["id"]["videoId"]
        snippet = item["snippet"]

        # Fetch live details + statistics for a richer embed.
        viewer_count: int | None = None
        started_at = self._parse_time(snippet.get("publishedAt"))
        details = await self._request_json(
            f"{_API_BASE}/videos",
            params={
                "part": "liveStreamingDetails,snippet",
                "id": video_id,
                "key": self.config.youtube_api_key or "",
            },
        )
        if details and details.get("items"):
            live = details["items"][0].get("liveStreamingDetails", {})
            if live.get("concurrentViewers"):
                viewer_count = int(live["concurrentViewers"])
            if live.get("actualStartTime"):
                started_at = self._parse_time(live["actualStartTime"])

        thumbnails = snippet.get("thumbnails", {})
        thumb = (
            thumbnails.get("maxres")
            or thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
            or {}
        ).get("url")

        return StreamInfo(
            platform=self.name,
            title=snippet.get("title", "Live Stream"),
            url=f"https://www.youtube.com/watch?v={video_id}",
            channel_name=snippet.get("channelTitle", self.config.streamer_name),
            stream_id=video_id,
            thumbnail=thumb or f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            viewer_count=viewer_count,
            game=None,
            started_at=started_at,
        )

    async def _via_scrape(self) -> StreamInfo | None:
        """Fallback detection by scraping the channel ``/live`` page."""
        channel_id = self.config.youtube_channel_id
        html = await self._request_text(
            f"https://www.youtube.com/channel/{channel_id}/live",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if not html:
            return None

        live_match = _IS_LIVE_RE.search(html)
        if not live_match or live_match.group(1) != "true":
            return None

        video_match = _VIDEO_ID_RE.search(html)
        if not video_match:
            return None
        video_id = video_match.group(1)

        title = "Live Stream"
        title_match = _TITLE_RE.search(html)
        if title_match:
            title = title_match.group(1)

        return StreamInfo(
            platform=self.name,
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            channel_name=self.config.streamer_name,
            stream_id=video_id,
            thumbnail=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            viewer_count=self._scrape_viewers(html),
            game=None,
            started_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _scrape_viewers(html: str) -> int | None:
        match = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

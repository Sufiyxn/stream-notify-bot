"""Kick live detection via the public channel API.

Kick exposes an unauthenticated JSON endpoint at
``https://kick.com/api/v2/channels/{username}`` whose ``livestream`` field is
``null`` when offline and an object describing the broadcast when live.
"""

from __future__ import annotations

from datetime import datetime

from platforms.base import BasePlatform, StreamInfo

_API_BASE = "https://kick.com/api/v2/channels"


class KickPlatform(BasePlatform):
    """Detect live streams for a single Kick channel."""

    name = "kick"
    display_name = "Kick"
    emoji = "🟢"

    @property
    def configured(self) -> bool:
        return bool(self.config.kick_username)

    async def get_stream_info(self) -> StreamInfo | None:
        if not self.configured:
            return None
        self.log.info("Checking Kick...")

        username = (self.config.kick_username or "").lower()
        data = await self._request_json(
            f"{_API_BASE}/{username}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        if not data:
            return None

        livestream = data.get("livestream")
        if not livestream or not livestream.get("is_live"):
            return None

        channel_name = (data.get("user") or {}).get("username") or username
        categories = livestream.get("categories") or []
        game = categories[0].get("name") if categories else None
        thumbnail = (livestream.get("thumbnail") or {}).get("url")

        return StreamInfo(
            platform=self.name,
            title=livestream.get("session_title", "Live Stream"),
            url=f"https://kick.com/{username}",
            channel_name=channel_name,
            stream_id=str(livestream.get("id")),
            thumbnail=thumbnail,
            viewer_count=livestream.get("viewer_count"),
            game=game,
            started_at=self._parse_time(livestream.get("created_at")),
        )

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

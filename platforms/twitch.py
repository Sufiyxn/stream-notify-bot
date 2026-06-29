"""Twitch live detection via the Helix API.

Uses the OAuth *client credentials* flow to obtain an app access token which is
cached and transparently refreshed before expiry.
"""

from __future__ import annotations

import time
from datetime import datetime

import aiohttp

from platforms.base import BasePlatform, StreamInfo
from utils.config import Config

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_HELIX_STREAMS = "https://api.twitch.tv/helix/streams"


class TwitchPlatform(BasePlatform):
    """Detect live streams for a single Twitch channel."""

    name = "twitch"
    display_name = "Twitch"
    emoji = "🟣"

    def __init__(self, config: Config, session: aiohttp.ClientSession) -> None:
        super().__init__(config, session)
        self._token: str | None = None
        self._token_expiry: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(
            self.config.twitch_username
            and self.config.twitch_client_id
            and self.config.twitch_client_secret
        )

    async def _get_token(self) -> str | None:
        """Return a valid app access token, refreshing it when required."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        async def _fetch() -> dict | None:
            async with self.session.post(
                _TOKEN_URL,
                params={
                    "client_id": self.config.twitch_client_id or "",
                    "client_secret": self.config.twitch_client_secret or "",
                    "grant_type": "client_credentials",
                },
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)

        data = await self._with_retry(_fetch, retries=3, what="Twitch token")
        if not data or "access_token" not in data:
            return None

        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def get_stream_info(self) -> StreamInfo | None:
        if not self.configured:
            return None
        self.log.info("Checking Twitch...")

        token = await self._get_token()
        if not token:
            self.log.error("Could not obtain a Twitch access token.")
            return None

        data = await self._request_json(
            _HELIX_STREAMS,
            headers={
                "Client-Id": self.config.twitch_client_id or "",
                "Authorization": f"Bearer {token}",
            },
            params={"user_login": self.config.twitch_username or ""},
        )
        if not data or not data.get("data"):
            return None

        stream = data["data"][0]
        if stream.get("type") != "live":
            return None

        username = stream.get("user_name", self.config.twitch_username)
        thumb = stream.get("thumbnail_url", "")
        if thumb:
            thumb = thumb.replace("{width}", "1280").replace("{height}", "720")

        return StreamInfo(
            platform=self.name,
            title=stream.get("title", "Live Stream"),
            url=f"https://www.twitch.tv/{self.config.twitch_username}",
            channel_name=username,
            stream_id=str(stream.get("id")),
            thumbnail=thumb or None,
            viewer_count=stream.get("viewer_count"),
            game=stream.get("game_name") or None,
            started_at=self._parse_time(stream.get("started_at")),
        )

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

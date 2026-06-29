"""Platform abstraction layer.

Every streaming platform is implemented as a subclass of :class:`BasePlatform`
exposing :meth:`BasePlatform.is_live` and :meth:`BasePlatform.get_stream_info`.
Adding a new platform is therefore as simple as dropping a new module in this
package and registering its class in :mod:`platforms.__init__`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, TypeVar

import aiohttp

from utils.config import Config
from utils.logger import get_logger

T = TypeVar("T")


@dataclass(slots=True)
class StreamInfo:
    """Normalised information about a live stream across all platforms."""

    platform: str
    title: str
    url: str
    channel_name: str
    stream_id: str
    thumbnail: str | None = None
    viewer_count: int | None = None
    game: str | None = None
    started_at: datetime | None = None

    @property
    def unique_key(self) -> str:
        """Key used for duplicate detection (platform + stream id)."""
        return f"{self.platform}:{self.stream_id}"


class BasePlatform(ABC):
    """Abstract base every platform integration inherits from."""

    #: Lower-case identifier, e.g. ``"youtube"``. Used in config/themes.
    name: str = "base"
    #: Human friendly name shown in embeds, e.g. ``"YouTube"``.
    display_name: str = "Base"
    #: Emoji shown alongside the platform in embeds / logs.
    emoji: str = "🔴"

    def __init__(self, config: Config, session: aiohttp.ClientSession) -> None:
        self.config = config
        self.session = session
        self.log = get_logger(self.name)

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether this platform has the settings it needs to run."""

    @abstractmethod
    async def get_stream_info(self) -> StreamInfo | None:
        """Return :class:`StreamInfo` if live, otherwise ``None``."""

    async def is_live(self) -> bool:
        """Convenience wrapper around :meth:`get_stream_info`."""
        return await self.get_stream_info() is not None

    async def _request_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        retries: int = 3,
    ) -> dict | None:
        """GET ``url`` and decode JSON with automatic retry/backoff.

        Returns ``None`` on persistent failure so the monitor can simply treat
        the platform as "unknown / offline" for this cycle instead of crashing.
        """
        async def _do() -> dict | None:
            async with self.session.get(url, headers=headers, params=params) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.json(content_type=None)

        return await self._with_retry(_do, retries=retries, what=f"GET {url}")

    async def _request_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        retries: int = 3,
    ) -> str | None:
        """GET ``url`` returning the body text, with retry/backoff."""
        async def _do() -> str | None:
            async with self.session.get(url, headers=headers, params=params) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.text()

        return await self._with_retry(_do, retries=retries, what=f"GET {url}")

    async def _with_retry(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        retries: int,
        what: str,
    ) -> T | None:
        """Run ``func`` retrying transient errors with exponential backoff."""
        delay = 1.0
        for attempt in range(1, retries + 1):
            try:
                return await func()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt >= retries:
                    self.log.error("%s failed after %d attempts: %s", what, retries, exc)
                    return None
                self.log.warning(
                    "%s failed (attempt %d/%d): %s - retrying in %.0fs",
                    what, attempt, retries, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
        return None

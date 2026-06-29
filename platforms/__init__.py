"""Platform registry.

To add a new streaming platform:

1. Create ``platforms/<name>.py`` with a subclass of
   :class:`platforms.base.BasePlatform`.
2. Import it below and add the class to :data:`PLATFORM_REGISTRY`.

That's it - the monitor automatically picks up any registered & configured
platform with no further changes.
"""

from __future__ import annotations

import aiohttp

from platforms.base import BasePlatform, StreamInfo
from platforms.kick import KickPlatform
from platforms.twitch import TwitchPlatform
from platforms.youtube import YouTubePlatform
from utils.config import Config

#: All known platform classes. Order controls check/display order.
PLATFORM_REGISTRY: tuple[type[BasePlatform], ...] = (
    YouTubePlatform,
    TwitchPlatform,
    KickPlatform,
)


def build_platforms(
    config: Config, session: aiohttp.ClientSession
) -> list[BasePlatform]:
    """Instantiate every registered platform that is fully configured.

    Args:
        config: The loaded application configuration.
        session: A shared aiohttp session for outbound requests.

    Returns:
        A list of ready-to-poll platform instances.
    """
    platforms: list[BasePlatform] = []
    for platform_cls in PLATFORM_REGISTRY:
        instance = platform_cls(config, session)
        if instance.configured:
            platforms.append(instance)
    return platforms


__all__ = [
    "BasePlatform",
    "StreamInfo",
    "PLATFORM_REGISTRY",
    "build_platforms",
    "YouTubePlatform",
    "TwitchPlatform",
    "KickPlatform",
]

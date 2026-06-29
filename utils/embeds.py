"""Embed and button builders for live notifications."""

from __future__ import annotations

import discord

from platforms.base import StreamInfo
from utils.config import Config

# Per-platform emoji used in the embed title / fields.
PLATFORM_EMOJIS: dict[str, str] = {
    "youtube": "📺",
    "twitch": "🟣",
}


def platform_emoji(platform: str) -> str:
    """Return the emoji associated with ``platform`` (default red circle)."""
    return PLATFORM_EMOJIS.get(platform, "🔴")


def build_live_embed(info: StreamInfo, config: Config) -> discord.Embed:
    """Build the rich "is LIVE" embed for a stream.

    Args:
        info: Normalised stream information.
        config: Application configuration (for colour themes).

    Returns:
        A fully populated :class:`discord.Embed`.
    """
    emoji = platform_emoji(info.platform)
    display_platform = info.platform.capitalize()

    embed = discord.Embed(
        title=f"{emoji} {info.channel_name} is LIVE!",
        description=f"**{info.title}**",
        url=info.url,
        colour=discord.Colour(config.theme_for(info.platform)),
        timestamp=info.started_at,
    )

    embed.add_field(name="Platform", value=f"{emoji} {display_platform}", inline=True)
    embed.add_field(name="Channel", value=info.channel_name, inline=True)

    if info.game:
        embed.add_field(name="Category", value=info.game, inline=True)
    if info.viewer_count is not None:
        embed.add_field(name="Viewers", value=f"{info.viewer_count:,}", inline=True)
    if info.started_at is not None:
        ts = int(info.started_at.timestamp())
        embed.add_field(name="Started", value=f"<t:{ts}:R>", inline=True)

    embed.add_field(name="Watch here", value=info.url, inline=False)

    if info.thumbnail:
        embed.set_image(url=info.thumbnail)

    embed.set_footer(text=f"{display_platform} • Stream Notifier")
    return embed


class StreamButtons(discord.ui.View):
    """A persistent view of configurable link buttons."""

    def __init__(self, info: StreamInfo, config: Config) -> None:
        super().__init__(timeout=None)

        buttons = config.buttons

        watch = buttons.get("watch_stream")
        if watch and watch.enabled:
            self.add_item(
                discord.ui.Button(
                    label=watch.label,
                    emoji=watch.emoji or None,
                    url=info.url,
                    style=discord.ButtonStyle.link,
                )
            )

        join = buttons.get("join_discord")
        if join and join.enabled and join.url:
            self.add_item(
                discord.ui.Button(
                    label=join.label,
                    emoji=join.emoji or None,
                    url=join.url,
                    style=discord.ButtonStyle.link,
                )
            )

        subscribe = buttons.get("subscribe")
        if subscribe and subscribe.enabled and subscribe.url:
            self.add_item(
                discord.ui.Button(
                    label=subscribe.label,
                    emoji=subscribe.emoji or None,
                    url=subscribe.url,
                    style=discord.ButtonStyle.link,
                )
            )


def build_message_content(info: StreamInfo, config: Config, role_mention: str | None) -> str:
    """Build the plain-text content shown above the embed.

    Includes the role mention (if any) followed by the custom message with
    ``{name}``, ``{platform}`` and ``{url}`` placeholders substituted.
    """
    message = config.custom_message.format(
        name=info.channel_name,
        platform=info.platform.capitalize(),
        url=info.url,
    )
    if role_mention:
        return f"{role_mention}\n{message}"
    return message

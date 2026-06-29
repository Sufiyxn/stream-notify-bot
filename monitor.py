"""The core monitoring cog.

Polls every configured platform on a fixed interval, applies duplicate /
offline detection and dispatches notifications (via bot messages or a Discord
webhook). It also keeps the bot presence and statistics up to date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from platforms import build_platforms
from platforms.base import BasePlatform, StreamInfo
from utils.config import Config
from utils.embeds import StreamButtons, build_live_embed, build_message_content
from utils.logger import get_logger

log = get_logger("monitor")


@dataclass(slots=True)
class SentMessage:
    """Reference to a delivered notification (for later edit/delete)."""

    guild_id: int
    channel_id: int
    message_id: int


@dataclass(slots=True)
class StreamState:
    """Per-platform runtime state used for de-duplication."""

    is_live: bool = False
    current_key: str | None = None
    notified_key: str | None = None
    messages: list[SentMessage] = field(default_factory=list)
    last_info: StreamInfo | None = None


@dataclass(slots=True)
class Stats:
    """Aggregate statistics surfaced by the /status and /platforms commands."""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notifications_sent: int = 0
    checks_run: int = 0
    last_check: datetime | None = None
    per_platform: dict[str, int] = field(default_factory=dict)


class StreamMonitor(commands.Cog):
    """Background monitor that watches every configured platform."""

    def __init__(self, bot: commands.Bot, config: Config) -> None:
        self.bot = bot
        self.config = config
        self.session: aiohttp.ClientSession | None = None
        self.platforms: list[BasePlatform] = []
        self.state: dict[str, StreamState] = {}
        self.stats = Stats()
        # Configure the polling interval before the loop starts.
        self.monitor_loop.change_interval(seconds=config.poll_interval)

    # -- lifecycle ---------------------------------------------------------
    async def cog_load(self) -> None:
        """Create the HTTP session and build platform instances."""
        timeout = aiohttp.ClientTimeout(total=20)
        self.session = aiohttp.ClientSession(timeout=timeout)
        self.platforms = build_platforms(self.config, self.session)
        self.state = {p.name: StreamState() for p in self.platforms}
        for platform in self.platforms:
            self.stats.per_platform.setdefault(platform.name, 0)
        log.info(
            "Monitoring %d platform(s): %s",
            len(self.platforms),
            ", ".join(p.display_name for p in self.platforms) or "none",
        )

    async def cog_unload(self) -> None:
        """Stop the loop and close the HTTP session cleanly."""
        if self.monitor_loop.is_running():
            self.monitor_loop.cancel()
        if self.session and not self.session.closed:
            await self.session.close()

    def start(self) -> None:
        """Start the polling loop if it is not already running."""
        if not self.monitor_loop.is_running():
            self.monitor_loop.start()

    # -- main loop ---------------------------------------------------------
    @tasks.loop(seconds=60)
    async def monitor_loop(self) -> None:
        """Poll every platform once and react to state changes."""
        await self.check_all()

    @monitor_loop.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def check_all(self) -> list[StreamInfo]:
        """Check all platforms a single time and process transitions.

        Returns:
            The list of currently-live streams (useful for /forcecheck).
        """
        self.stats.checks_run += 1
        self.stats.last_check = datetime.now(timezone.utc)
        live_now: list[StreamInfo] = []

        for platform in self.platforms:
            try:
                info = await platform.get_stream_info()
            except Exception as exc:  # defensive: never let one platform break the loop
                log.error("Unexpected error checking %s: %s", platform.display_name, exc)
                continue

            state = self.state[platform.name]
            if info:
                live_now.append(info)
                await self._handle_live(platform, state, info)
            else:
                await self._handle_offline(platform, state)

        await self._update_presence(live_now)
        return live_now

    # -- transitions -------------------------------------------------------
    async def _handle_live(
        self, platform: BasePlatform, state: StreamState, info: StreamInfo
    ) -> None:
        """Handle a platform that is currently live."""
        # New stream (first time live, or a different stream id than before).
        if not state.is_live or state.current_key != info.unique_key:
            log.live("%s %s went live: %s", platform.emoji, info.channel_name, info.title)
            state.is_live = True
            state.current_key = info.unique_key
            state.last_info = info

            # Ping-once protection: only notify once per unique stream.
            if self.config.ping_once_per_stream and state.notified_key == info.unique_key:
                return
            state.notified_key = info.unique_key
            await self._send_notification(state, info)
        else:
            # Same stream still live - refresh thumbnail / viewer count.
            state.last_info = info
            await self._refresh_messages(state, info)

    async def _handle_offline(self, platform: BasePlatform, state: StreamState) -> None:
        """Handle a platform that is offline, resetting state if needed."""
        if state.is_live:
            log.offline("%s %s stream ended.", platform.emoji, platform.display_name)
            if self.config.delete_after_offline:
                await self._delete_messages(state)
        # Reset state so the next stream notifies again.
        state.is_live = False
        state.current_key = None
        state.messages = []
        state.last_info = None

    # -- delivery ----------------------------------------------------------
    async def _send_notification(self, state: StreamState, info: StreamInfo) -> None:
        """Send the live notification to every target (or the webhook)."""
        embed = build_live_embed(info, self.config)

        if self.config.webhook_mode:
            await self._send_via_webhook(info, embed)
            self.stats.notifications_sent += 1
            self.stats.per_platform[info.platform] = (
                self.stats.per_platform.get(info.platform, 0) + 1
            )
            return

        for server in self.config.servers:
            channel = self.bot.get_channel(server.notification_channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                log.warning(
                    "Channel %s not found or not a text channel.",
                    server.notification_channel_id,
                )
                continue

            role_mention = None
            if server.live_role_id:
                role_mention = f"<@&{server.live_role_id}>"

            content = build_message_content(info, self.config, role_mention)
            view = StreamButtons(info, self.config)
            allowed = discord.AllowedMentions(roles=True)
            try:
                message = await channel.send(
                    content=content,
                    embed=embed,
                    view=view,
                    allowed_mentions=allowed,
                )
                state.messages.append(
                    SentMessage(server.guild_id, channel.id, message.id)
                )
                self.stats.notifications_sent += 1
                self.stats.per_platform[info.platform] = (
                    self.stats.per_platform.get(info.platform, 0) + 1
                )
            except discord.DiscordException as exc:
                log.error("Failed to send notification to %s: %s", channel.id, exc)

    async def _send_via_webhook(self, info: StreamInfo, embed: discord.Embed) -> None:
        """Deliver the notification through a Discord webhook."""
        if not (self.config.webhook_url and self.session):
            return
        try:
            webhook = discord.Webhook.from_url(self.config.webhook_url, session=self.session)
            await webhook.send(
                content=build_message_content(info, self.config, None),
                embed=embed,
                username=f"{info.channel_name} • Stream Notifier",
            )
        except discord.DiscordException as exc:
            log.error("Failed to send webhook notification: %s", exc)

    async def _refresh_messages(self, state: StreamState, info: StreamInfo) -> None:
        """Edit existing notifications with fresh thumbnail / viewer info."""
        if self.config.webhook_mode or not state.messages:
            return
        embed = build_live_embed(info, self.config)
        for ref in state.messages:
            channel = self.bot.get_channel(ref.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                continue
            try:
                message = await channel.fetch_message(ref.message_id)
                await message.edit(embed=embed)
            except discord.DiscordException:
                # Message may have been deleted manually; ignore.
                continue

    async def _delete_messages(self, state: StreamState) -> None:
        """Delete previously sent notifications (auto-delete on offline)."""
        for ref in state.messages:
            channel = self.bot.get_channel(ref.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                continue
            try:
                message = await channel.fetch_message(ref.message_id)
                await message.delete()
            except discord.DiscordException:
                continue

    # -- presence ----------------------------------------------------------
    async def _update_presence(self, live_now: list[StreamInfo]) -> None:
        """Reflect live status in the bot presence."""
        activity: discord.BaseActivity
        if live_now:
            info = live_now[0]
            activity = discord.Streaming(
                name=f"{info.channel_name} LIVE",
                url=info.url if info.url.startswith("http") else "https://twitch.tv/discord",
            )
        else:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=self.config.presence_idle,
            )
        await self.bot.change_presence(status=discord.Status.online, activity=activity)


async def setup(bot: commands.Bot) -> None:  # pragma: no cover - discord entrypoint
    """discord.py extension entrypoint (unused; cog added explicitly)."""
    raise RuntimeError("StreamMonitor is added manually in main.py")

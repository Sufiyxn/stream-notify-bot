"""Admin-only slash commands.

All commands are restricted to members with the *Administrator* permission and
are registered to the configured guild(s) for instant availability.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from monitor import StreamMonitor
from platforms.base import StreamInfo
from utils.config import DEFAULT_CONFIG, Config
from utils.embeds import build_live_embed
from utils.logger import get_logger

log = get_logger("commands")


def _format_duration(start: datetime) -> str:
    """Return a human readable uptime string for ``start``."""
    delta = datetime.now(timezone.utc) - start
    seconds = int(delta.total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


class AdminCommands(commands.Cog):
    """Slash commands for managing and inspecting the bot."""

    def __init__(self, bot: commands.Bot, config: Config) -> None:
        self.bot = bot
        self.config = config

    @property
    def monitor(self) -> StreamMonitor | None:
        """Return the active monitor cog, if loaded."""
        cog = self.bot.get_cog("StreamMonitor")
        return cog if isinstance(cog, StreamMonitor) else None

    # -- /createconfig -----------------------------------------------------
    @app_commands.command(
        name="createconfig",
        description="Generate a fresh config.json template you can download and edit.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def createconfig(self, interaction: discord.Interaction) -> None:
        template = json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False)
        file = discord.File(
            io.BytesIO(template.encode("utf-8")), filename="config.json"
        )
        await interaction.response.send_message(
            "Here is a clean `config.json` template. Fill it in, place it next "
            "to `main.py`, and keep your secrets in `.env`.",
            file=file,
            ephemeral=True,
        )

    # -- /status -----------------------------------------------------------
    @app_commands.command(name="status", description="Show the bot's monitoring status.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction) -> None:
        monitor = self.monitor
        if not monitor:
            await interaction.response.send_message(
                "Monitor is not running.", ephemeral=True
            )
            return

        stats = monitor.stats
        embed = discord.Embed(
            title="📡 Stream Notifier Status",
            colour=discord.Colour(self.config.embed_color),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Uptime", value=_format_duration(stats.started_at), inline=True)
        embed.add_field(name="Poll interval", value=f"{self.config.poll_interval}s", inline=True)
        embed.add_field(name="Checks run", value=str(stats.checks_run), inline=True)
        embed.add_field(
            name="Notifications sent", value=str(stats.notifications_sent), inline=True
        )
        last = stats.last_check
        embed.add_field(
            name="Last check",
            value=f"<t:{int(last.timestamp())}:R>" if last else "never",
            inline=True,
        )
        embed.add_field(
            name="Delivery",
            value="Webhook" if self.config.webhook_mode else "Bot message",
            inline=True,
        )

        lines = []
        for platform in monitor.platforms:
            state = monitor.state[platform.name]
            status = "🔴 LIVE" if state.is_live else "⚫ offline"
            lines.append(f"{platform.emoji} **{platform.display_name}** — {status}")
        embed.add_field(
            name="Platforms",
            value="\n".join(lines) or "none configured",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- /forcecheck -------------------------------------------------------
    @app_commands.command(
        name="forcecheck", description="Run a live check immediately for all platforms."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def forcecheck(self, interaction: discord.Interaction) -> None:
        monitor = self.monitor
        if not monitor:
            await interaction.response.send_message(
                "Monitor is not running.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        live = await monitor.check_all()
        if not live:
            await interaction.followup.send("No platforms are currently live.")
            return
        lines = [
            f"{info.platform.capitalize()}: **{info.title}** ({info.url})" for info in live
        ]
        await interaction.followup.send("Currently live:\n" + "\n".join(lines))

    # -- /testnotification -------------------------------------------------
    @app_commands.command(
        name="testnotification",
        description="Post a sample notification to verify formatting.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def testnotification(self, interaction: discord.Interaction) -> None:
        sample = StreamInfo(
            platform="youtube",
            title="Grinding Ranked with Viewers!",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            channel_name=self.config.streamer_name,
            stream_id="test",
            thumbnail="https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
            viewer_count=1234,
            game="Just Chatting",
            started_at=datetime.now(timezone.utc),
        )
        embed = build_live_embed(sample, self.config)
        from utils.embeds import StreamButtons, build_message_content

        view = StreamButtons(sample, self.config)
        content = build_message_content(sample, self.config, None)
        await interaction.response.send_message(
            content=f"**[TEST]** {content}", embed=embed, view=view, ephemeral=True
        )

    # -- /platforms --------------------------------------------------------
    @app_commands.command(
        name="platforms", description="List supported platforms and notification stats."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def platforms(self, interaction: discord.Interaction) -> None:
        monitor = self.monitor
        embed = discord.Embed(
            title="🎛️ Supported Platforms",
            colour=discord.Colour(self.config.embed_color),
        )
        if not monitor:
            embed.description = "Monitor is not running."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        for platform in monitor.platforms:
            sent = monitor.stats.per_platform.get(platform.name, 0)
            state = monitor.state[platform.name]
            status = "🔴 LIVE" if state.is_live else "⚫ offline"
            embed.add_field(
                name=f"{platform.emoji} {platform.display_name}",
                value=f"Status: {status}\nNotifications sent: **{sent}**",
                inline=True,
            )
        embed.set_footer(text="Add more platforms by dropping a class in platforms/")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- /help -------------------------------------------------------------
    @app_commands.command(name="help", description="Show available commands.")
    @app_commands.checks.has_permissions(administrator=True)
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🤖 Stream Notifier — Help",
            description="Admin-only commands for the live stream notifier.",
            colour=discord.Colour(self.config.embed_color),
        )
        commands_help = {
            "/createconfig": "Download a fresh config.json template.",
            "/status": "Show uptime, stats and live status.",
            "/forcecheck": "Force an immediate live check.",
            "/testnotification": "Preview a sample live notification.",
            "/platforms": "List platforms and per-platform stats.",
            "/help": "Show this message.",
        }
        for name, desc in commands_help.items():
            embed.add_field(name=name, value=desc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- shared error handler ---------------------------------------------
    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need the **Administrator** permission to use this command."
        else:
            log.error("Command error: %s", error)
            message = "Something went wrong while running that command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup_admin_commands(bot: commands.Bot, config: Config) -> None:
    """Add the admin command cog to the bot."""
    await bot.add_cog(AdminCommands(bot, config))

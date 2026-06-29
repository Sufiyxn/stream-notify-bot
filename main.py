"""Stream Notifier Discord bot - application entrypoint.

Loads & validates configuration, connects to Discord, registers slash commands
and starts monitoring every configured platform automatically.

Run with:  python main.py
"""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from commands.admin import setup_admin_commands
from monitor import StreamMonitor
from utils.config import Config, ConfigError, load_config
from utils.logger import get_logger, setup_logging

log = setup_logging()


class StreamNotifierBot(commands.Bot):
    """The Discord bot wired up with the monitor and admin commands."""

    def __init__(self, config: Config) -> None:
        # Only the intents we actually need - keeps the bot privacy-friendly.
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.config = config
        self.monitor: StreamMonitor | None = None

    async def setup_hook(self) -> None:
        """Register cogs and sync slash commands before connecting."""
        self.monitor = StreamMonitor(self, self.config)
        await self.add_cog(self.monitor)
        await setup_admin_commands(self, self.config)

        # Sync commands to each configured guild for instant availability.
        for server in self.config.servers:
            guild = discord.Object(id=server.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced slash commands to guild %s", server.guild_id)

        # The loop waits internally until the bot is ready.
        self.monitor.start()

    async def on_ready(self) -> None:
        """Log a friendly banner once connected."""
        assert self.user is not None
        log.info("Connected as %s (id: %s)", self.user, self.user.id)
        log.info(
            "Watching for live streams every %ss across %d platform(s).",
            self.config.poll_interval,
            len(self.monitor.platforms) if self.monitor else 0,
        )
        # Set the idle presence immediately on connect.
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=self.config.presence_idle,
            ),
        )


async def run() -> None:
    """Load configuration and run the bot until interrupted."""
    try:
        config = load_config()
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    log.info("Configuration loaded and validated successfully.")
    bot = StreamNotifierBot(config)

    try:
        async with bot:
            await bot.start(config.discord_token)
    except discord.LoginFailure:
        log.error("Invalid Discord token. Check DISCORD_TOKEN in your .env file.")
        raise SystemExit(1)


def main() -> None:
    """Synchronous wrapper used as the console entrypoint."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        get_logger().info("Shutting down (keyboard interrupt).")


if __name__ == "__main__":
    main()

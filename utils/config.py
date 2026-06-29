"""Configuration loading and validation.

Non-secret settings live in ``config.json`` while every secret (the Discord
token, API keys, OAuth client secrets) is read from environment variables /
``.env`` so nothing sensitive is ever committed.

The loader merges the two sources, validates the result and exposes a fully
typed :class:`Config` object to the rest of the application.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


# A sensible, fully-populated template written by ``/createconfig`` and used as
# the default when generating ``config.json``.
DEFAULT_CONFIG: dict[str, Any] = {
    "discord_token": "",
    "guild_id": 0,
    "notification_channel_id": 0,
    "live_role_id": 0,
    "streamer_name": "Alpha",
    "youtube_channel_id": "",
    "twitch_username": "",
    "kick_username": "",
    "poll_interval": 60,
    "embed_color": "0xFF0000",
    "custom_message": "**{name}** just went live on {platform}!",
    "presence_idle": "for live streams...",
    "ping_once_per_stream": True,
    "delete_after_offline": False,
    "webhook_mode": False,
    "webhook_url": "",
    "buttons": {
        "watch_stream": {"enabled": True, "label": "Watch Stream", "emoji": "▶️"},
        "join_discord": {"enabled": True, "label": "Join Discord", "emoji": "💬", "url": ""},
        "subscribe": {"enabled": True, "label": "Subscribe", "emoji": "📺", "url": ""},
    },
    "themes": {
        "youtube": "0xFF0000",
        "twitch": "0x9146FF",
        "kick": "0x53FC18",
        "default": "0xFF0000",
    },
    "servers": [],
}


def _coerce_color(value: Any) -> int:
    """Convert a colour expressed as int / hex-string into an ``int``.

    Args:
        value: ``"0xFF0000"``, ``"#FF0000"``, ``"FF0000"`` or an ``int``.

    Returns:
        The colour as an integer suitable for ``discord.Colour``.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if text.lower().startswith("0x"):
            text = text[2:]
        try:
            return int(text, 16)
        except ValueError as exc:
            raise ConfigError(f"Invalid colour value: {value!r}") from exc
    raise ConfigError(f"Invalid colour value: {value!r}")


@dataclass(slots=True)
class ButtonConfig:
    """A single configurable Discord link button."""

    enabled: bool
    label: str
    emoji: str | None = None
    url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ButtonConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            label=str(data.get("label", "Link")),
            emoji=data.get("emoji"),
            url=data.get("url"),
        )


@dataclass(slots=True)
class ServerConfig:
    """A target Discord server (supports multi-guild delivery)."""

    guild_id: int
    notification_channel_id: int
    live_role_id: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerConfig":
        role = data.get("live_role_id") or None
        return cls(
            guild_id=int(data["guild_id"]),
            notification_channel_id=int(data["notification_channel_id"]),
            live_role_id=int(role) if role else None,
        )


@dataclass(slots=True)
class Config:
    """Fully typed application configuration."""

    # --- Secrets (sourced from the environment / .env) ---------------------
    discord_token: str
    youtube_api_key: str | None
    twitch_client_id: str | None
    twitch_client_secret: str | None

    # --- General ----------------------------------------------------------
    streamer_name: str
    poll_interval: int
    embed_color: int
    custom_message: str
    presence_idle: str
    ping_once_per_stream: bool
    delete_after_offline: bool

    # --- Delivery ---------------------------------------------------------
    webhook_mode: bool
    webhook_url: str | None
    servers: list[ServerConfig]

    # --- Platforms (raw values; consumed by the platform classes) ---------
    youtube_channel_id: str | None
    twitch_username: str | None
    kick_username: str | None

    # --- Presentation -----------------------------------------------------
    buttons: dict[str, ButtonConfig]
    themes: dict[str, int]

    # Original parsed JSON, kept for diagnostics / future platform configs.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def theme_for(self, platform: str) -> int:
        """Return the embed colour for ``platform`` falling back to default."""
        if platform in self.themes:
            return self.themes[platform]
        return self.themes.get("default", self.embed_color)


def _load_json(path: Path) -> dict[str, Any]:
    """Read and parse ``config.json`` merged over the defaults."""
    if not path.exists():
        raise ConfigError(
            f"Config file not found at '{path}'. Run the bot once and use "
            f"/createconfig, or copy config.example.json to config.json."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json is not valid JSON: {exc}") from exc

    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy of defaults
    merged.update(data)
    return merged


def load_config(
    config_path: str | os.PathLike[str] = "config.json",
    env_path: str | os.PathLike[str] = ".env",
) -> Config:
    """Load, merge and validate configuration.

    Args:
        config_path: Path to the JSON configuration file.
        env_path: Path to the ``.env`` file holding secrets.

    Returns:
        A validated :class:`Config`.

    Raises:
        ConfigError: If required values are missing or malformed.
    """
    load_dotenv(env_path)
    data = _load_json(Path(config_path))

    # Secrets always prefer the environment; config.json may keep blanks.
    discord_token = os.getenv("DISCORD_TOKEN") or str(data.get("discord_token", ""))
    if not discord_token:
        raise ConfigError(
            "Discord token missing. Set DISCORD_TOKEN in your .env file."
        )

    # Buttons -> typed objects, merged over defaults.
    button_data: dict[str, Any] = dict(DEFAULT_CONFIG["buttons"])
    button_data.update(data.get("buttons") or {})
    buttons = {key: ButtonConfig.from_dict(val) for key, val in button_data.items()}

    # Themes -> ints.
    theme_data: dict[str, Any] = dict(DEFAULT_CONFIG["themes"])
    theme_data.update(data.get("themes") or {})
    themes = {key: _coerce_color(val) for key, val in theme_data.items()}

    # Servers: explicit multi-guild list, else build one from the top-level
    # guild/channel/role fields for backwards compatibility.
    servers: list[ServerConfig] = []
    if data.get("servers"):
        servers = [ServerConfig.from_dict(s) for s in data["servers"]]
    elif data.get("guild_id") and data.get("notification_channel_id"):
        servers = [
            ServerConfig(
                guild_id=int(data["guild_id"]),
                notification_channel_id=int(data["notification_channel_id"]),
                live_role_id=int(data["live_role_id"]) if data.get("live_role_id") else None,
            )
        ]

    poll_interval = int(data.get("poll_interval", 60))
    if poll_interval < 10:
        raise ConfigError("poll_interval must be at least 10 seconds.")

    config = Config(
        discord_token=discord_token,
        youtube_api_key=os.getenv("YOUTUBE_API_KEY") or None,
        twitch_client_id=os.getenv("TWITCH_CLIENT_ID") or None,
        twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET") or None,
        streamer_name=str(data.get("streamer_name") or "Streamer"),
        poll_interval=poll_interval,
        embed_color=_coerce_color(data.get("embed_color", "0xFF0000")),
        custom_message=str(data.get("custom_message") or "**{name}** is live on {platform}!"),
        presence_idle=str(data.get("presence_idle") or "for live streams..."),
        ping_once_per_stream=bool(data.get("ping_once_per_stream", True)),
        delete_after_offline=bool(data.get("delete_after_offline", False)),
        webhook_mode=bool(data.get("webhook_mode", False)),
        webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or (data.get("webhook_url") or None),
        servers=servers,
        youtube_channel_id=(data.get("youtube_channel_id") or None),
        twitch_username=(data.get("twitch_username") or None),
        kick_username=(data.get("kick_username") or None),
        buttons=buttons,
        themes=themes,
        raw=data,
    )

    _validate(config)
    return config


def _validate(config: Config) -> None:
    """Validate cross-field invariants, raising :class:`ConfigError`."""
    if config.webhook_mode and not config.webhook_url:
        raise ConfigError(
            "webhook_mode is enabled but no webhook_url / DISCORD_WEBHOOK_URL is set."
        )
    if not config.webhook_mode and not config.servers:
        raise ConfigError(
            "No target servers configured. Set guild_id and "
            "notification_channel_id (or a 'servers' list) in config.json."
        )
    # At least one platform must be configured to have anything to monitor.
    if not any([config.youtube_channel_id, config.twitch_username, config.kick_username]):
        raise ConfigError(
            "No platforms configured. Set at least one of youtube_channel_id, "
            "twitch_username or kick_username in config.json."
        )
    if config.twitch_username and not (config.twitch_client_id and config.twitch_client_secret):
        raise ConfigError(
            "Twitch is configured but TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET "
            "are missing from the environment."
        )

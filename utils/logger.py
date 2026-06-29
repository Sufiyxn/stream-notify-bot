"""Logging utilities.

Provides a colourised, timestamped console logger plus two custom log
levels (``LIVE`` and ``OFFLINE``) so stream state changes stand out in the
console exactly as requested:

    [INFO] Connected
    [INFO] Checking YouTube...
    [LIVE] Alpha went live
    [OFFLINE] Stream ended
"""

from __future__ import annotations

import logging
import sys
from typing import cast

# Custom log levels sit just above INFO so they are always shown but can be
# filtered independently if desired.
LIVE_LEVEL: int = 25
OFFLINE_LEVEL: int = 24

logging.addLevelName(LIVE_LEVEL, "LIVE")
logging.addLevelName(OFFLINE_LEVEL, "OFFLINE")


class AppLogger(logging.Logger):
    """Logger subclass adding ``live()`` and ``offline()`` helpers."""

    def live(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message with the custom ``LIVE`` level."""
        if self.isEnabledFor(LIVE_LEVEL):
            self._log(LIVE_LEVEL, message, args, **kwargs)  # type: ignore[arg-type]

    def offline(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a message with the custom ``OFFLINE`` level."""
        if self.isEnabledFor(OFFLINE_LEVEL):
            self._log(OFFLINE_LEVEL, message, args, **kwargs)  # type: ignore[arg-type]


# Ensure every logger created from here on is an :class:`AppLogger`.
logging.setLoggerClass(AppLogger)


class _ColourFormatter(logging.Formatter):
    """Formatter that adds ANSI colours to the level name on TTYs."""

    COLOURS: dict[int, str] = {
        logging.DEBUG: "\033[37m",      # grey
        logging.INFO: "\033[36m",       # cyan
        OFFLINE_LEVEL: "\033[33m",      # yellow
        LIVE_LEVEL: "\033[1;32m",       # bold green
        logging.WARNING: "\033[33m",    # yellow
        logging.ERROR: "\033[31m",      # red
        logging.CRITICAL: "\033[1;41m",  # red background
    }
    RESET: str = "\033[0m"

    def __init__(self, *, use_colour: bool) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if not self.use_colour:
            return formatted
        colour = self.COLOURS.get(record.levelno, "")
        if not colour:
            return formatted
        # Colour only the "[LEVEL]" token to keep the rest readable.
        token = f"[{record.levelname}]"
        return formatted.replace(token, f"{colour}{token}{self.RESET}", 1)


def setup_logging(level: int = logging.INFO) -> AppLogger:
    """Configure the root ``stream-notify`` logger and return it.

    Args:
        level: Minimum level to emit. Defaults to ``logging.INFO``.

    Returns:
        The configured application logger.
    """
    logger = cast(AppLogger, logging.getLogger("stream-notify"))
    logger.setLevel(level)
    logger.propagate = False

    # Avoid duplicate handlers if called more than once.
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_ColourFormatter(use_colour=sys.stdout.isatty()))
    logger.addHandler(handler)
    return logger


def get_logger(name: str | None = None) -> AppLogger:
    """Return a child of the application logger.

    Args:
        name: Optional child name (e.g. ``"youtube"``).

    Returns:
        The requested logger instance.
    """
    base = cast(AppLogger, logging.getLogger("stream-notify"))
    return cast(AppLogger, base.getChild(name)) if name else base

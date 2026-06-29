# 🔴 Stream Notifier — Discord Live Bot

A production-ready Discord bot that notifies your server the moment you go
**live** on **YouTube**, **Twitch** or **Kick** — with a clean, extensible
architecture that makes adding new platforms trivial.

Built with **Python 3.12+** and **discord.py 2.x**, fully async, type-hinted,
logged and configurable.

---

## ✨ Features

- **Multi-platform live detection** — YouTube, Twitch and Kick out of the box.
- **Pluggable architecture** — add a new platform by dropping one file in
  `platforms/` and registering it. Every platform implements `is_live()` and
  `get_stream_info()`.
- **Duplicate protection** — never sends two notifications for the same stream.
- **Offline detection** — resets internal state when a stream ends, ready for
  the next one.
- **Beautiful embeds** — title, platform, thumbnail, start time, channel name,
  viewer count, category and stream URL, with platform-specific emojis and
  colour themes.
- **Configurable buttons** — ▶️ Watch Stream, 💬 Join Discord, 📺 Subscribe.
- **Role mention** — optionally pings a "Live" role (once per stream).
- **Dynamic presence** — `Watching for live streams...` → `Streaming <name> LIVE`.
- **Admin slash commands** — `/createconfig`, `/status`, `/forcecheck`,
  `/testnotification`, `/platforms`, `/help`.
- **Automatic retry** with exponential backoff when APIs fail.
- **Statistics** — notifications sent, per-platform counts, uptime, checks run.
- **Bonus options** — auto-update thumbnail/viewers, auto-delete the
  notification when the stream ends, multi-server delivery, custom themes and an
  optional Discord **webhook delivery mode**.

---

## 📁 Project structure

```
stream-notify-bot/
├── main.py               # Entrypoint: load config, connect, start monitoring
├── monitor.py            # Polling loop, dedup, offline detection, presence
├── config.example.json   # Copy to config.json and fill in (non-secret values)
├── .env.example          # Copy to .env and fill in (secrets)
├── requirements.txt
├── README.md
├── platforms/
│   ├── base.py           # BasePlatform ABC + StreamInfo dataclass + retry
│   ├── youtube.py        # YouTube (Data API v3 + HTML fallback)
│   ├── twitch.py         # Twitch (Helix API + OAuth client credentials)
│   ├── kick.py           # Kick (public channel API)
│   └── __init__.py       # Platform registry / factory
├── utils/
│   ├── config.py         # Typed config loading + validation
│   ├── embeds.py         # Embed + button builders
│   └── logger.py         # Timestamped, coloured logging (+ LIVE/OFFLINE levels)
└── commands/
    └── admin.py          # Admin-only slash commands
```

---

## 🚀 Setup

### 1. Requirements

- Python **3.12+**

```bash
git clone <your-repo-url>
cd stream-notify-bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → **Bot** → copy the **Token**.
3. Invite the bot to your server with the `bot` and `applications.commands`
   scopes and permission to **Send Messages** / **Embed Links** (and **Mention
   Everyone** if you use a live role).

### 3. Configure secrets (`.env`)

```bash
cp .env.example .env
```

Fill in:

| Variable | Required? | Notes |
| --- | --- | --- |
| `DISCORD_TOKEN` | ✅ | Your bot token. |
| `YOUTUBE_API_KEY` | ⚪ optional | [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) key. Without it, YouTube falls back to HTML scraping. |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | ⚪ optional | Needed only if you monitor Twitch. Create an app at [dev.twitch.tv](https://dev.twitch.tv/console/apps). |
| `DISCORD_WEBHOOK_URL` | ⚪ optional | Needed only when `webhook_mode` is enabled. |

### 4. Configure the bot (`config.json`)

```bash
cp config.example.json config.json
```

Edit the values:

| Field | Description |
| --- | --- |
| `guild_id` | Your Discord server ID. |
| `notification_channel_id` | Channel where notifications are posted. |
| `live_role_id` | *(optional)* Role to mention when you go live. `0` to disable. |
| `streamer_name` | Your display name (used in messages/presence). |
| `youtube_channel_id` | Channel ID like `UCxxxxxxxx` (leave blank to disable). |
| `twitch_username` | Twitch login name (leave blank to disable). |
| `kick_username` | Kick username (leave blank to disable). |
| `poll_interval` | Seconds between checks (default `60`, minimum `10`). |
| `embed_color` | Default embed colour, e.g. `"0xFF0000"`. |
| `custom_message` | Supports `{name}`, `{platform}`, `{url}` placeholders. |
| `buttons` | Enable/label/emoji/url for the three link buttons. |
| `themes` | Per-platform embed colours. |

> 💡 You can also run the bot and use **`/createconfig`** to download a fresh
> template from inside Discord.

#### Multiple servers (optional)

Instead of the single `guild_id`/`notification_channel_id` fields, provide a
`servers` array:

```json
"servers": [
  { "guild_id": 111, "notification_channel_id": 222, "live_role_id": 333 },
  { "guild_id": 444, "notification_channel_id": 555 }
]
```

### 5. Run

```bash
python main.py
```

You should see:

```
2026-06-29 01:34:00 [INFO] stream-notify: Configuration loaded and validated successfully.
2026-06-29 01:34:01 [INFO] stream-notify: Connected as YourBot#1234 (id: ...)
2026-06-29 01:34:01 [INFO] stream-notify.monitor: Checking YouTube...
2026-06-29 01:34:02 [LIVE] stream-notify.monitor: 📺 Alpha went live: Grinding Ranked!
```

---

## 🧩 Adding a new platform

1. Create `platforms/myplatform.py`:

   ```python
   from platforms.base import BasePlatform, StreamInfo

   class MyPlatform(BasePlatform):
       name = "myplatform"
       display_name = "MyPlatform"
       emoji = "🎬"

       @property
       def configured(self) -> bool:
           return bool(self.config.raw.get("myplatform_username"))

       async def get_stream_info(self) -> StreamInfo | None:
           ...  # return StreamInfo if live, else None
   ```

2. Register it in `platforms/__init__.py`:

   ```python
   from platforms.myplatform import MyPlatform
   PLATFORM_REGISTRY = (YouTubePlatform, TwitchPlatform, KickPlatform, MyPlatform)
   ```

Done — the monitor will start polling it automatically.

---

## 🛠️ Slash commands (admin only)

| Command | Description |
| --- | --- |
| `/createconfig` | Download a fresh `config.json` template. |
| `/status` | Uptime, stats, poll interval and per-platform live status. |
| `/forcecheck` | Run an immediate check across all platforms. |
| `/testnotification` | Post a sample notification to verify formatting. |
| `/platforms` | List platforms and per-platform notification counts. |
| `/help` | Show command help. |

---

## 🔔 Webhook delivery mode (optional)

Set `"webhook_mode": true` and a `DISCORD_WEBHOOK_URL` (or `webhook_url` in
`config.json`) to deliver notifications through a Discord webhook instead of the
bot user. Slash commands and monitoring continue to work as normal.

---

## ❓ Troubleshooting

- **`Configuration error: Discord token missing`** — set `DISCORD_TOKEN` in
  `.env`.
- **YouTube never detects live** — add a `YOUTUBE_API_KEY`; the scraping
  fallback can be blocked by consent pages in some regions.
- **Twitch error about client id/secret** — set `TWITCH_CLIENT_ID` and
  `TWITCH_CLIENT_SECRET`.
- **Kick returns nothing** — Kick is occasionally behind Cloudflare; the bot
  retries automatically and resumes on the next poll.

---

## 📜 License

MIT — do whatever you like, no warranty.

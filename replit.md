# Telegram Group Management Bot

A full-featured Arabic Telegram group management bot with ranks, media filters, protection locks, punishments, keyword responses, developer panel, and subscription enforcement.

## Run & Operate

- `cd bot && python main.py` — run the Telegram bot (starts Flask ping server on port 5001)
- Bot workflow: `Telegram Bot` — manages the running process
- Required env secrets: `TELEGRAM_BOT_TOKEN`, `MONGODB_URL`, `DEVELOPER_ID`

## Stack

- Python 3.11
- python-telegram-bot 22.x (polling mode)
- pymongo (MongoDB for all persistent data)
- Flask (lightweight uptime-ping server on port 5001)

## Where things live

- `bot/main.py` — entry point, handler registration, Flask server
- `bot/config.py` — env vars and constants
- `bot/database.py` — all MongoDB operations
- `bot/utils.py` — shared helpers (normalize_arabic, esc, btn, keyboard, rank utils)
- `bot/modules/ranks.py` — ranks system (promote/demote, permissions, staff lists)
- `bot/modules/media_filters.py` — 10 media type filters with toggle panel
- `bot/modules/locks.py` — 8 protection locks (usernames, flood, forwarding, bots, etc.)
- `bot/modules/punishments.py` — mute/ban/warn/auto-mute system
- `bot/modules/keywords.py` — custom keyword → response system (ConversationHandler)
- `bot/modules/developer.py` — developer-only panel, broadcast, exports
- `bot/modules/subscriptions.py` — dual-layer mandatory subscription enforcement
- `bot/modules/stats.py` — group statistics, PV user tracking
- `bot/modules/normalizer.py` — Arabic text normalization, command routing, /start

## Architecture decisions

- All text commands are Arabic — no /slash commands except /start and /panel
- Arabic normalization covers ا/أ/إ/آ → ا, ى → ي, ة/ه interchangeable, strips leading "ال"
- Developer ID is hardcoded in config but sourced from DEVELOPER_ID env secret; never appears in public bot output
- MongoDB `groups` collection auto-initializes with defaults on first group interaction
- All inline buttons use Bot API 9.4 `style` parameter: success/danger/primary

## Product

A comprehensive Telegram group management system with:
- 6-tier rank hierarchy (Developer, Owner, Creator, Admin, Moderator, Member)
- Granular per-user permission control with live toggle UI
- 10 media type filters + 8 protection locks, all toggle-able via inline menus
- Auto-mute system with configurable warning threshold and duration
- Custom keyword responses (text, photo, sticker)
- Dual-layer mandatory subscription (developer channel + group channel)
- Developer control panel: broadcast, maintenance mode, statistics export, PV protection

## User preferences

- Strictly no emojis — use typographic symbols (❖, ◈, ✦, ✧, ▲, ▼, ●, ○, ■, □, ➔, 【, 】)
- All UI text in Arabic
- Buttons always styled: success (green) / danger (red) / primary (blue)
- Button grids: 2-column layout for toggle menus

## Gotchas

- Port 5001 is used for Flask (5000 is taken by api-server, 8080 by mockup-sandbox)
- Bot must be added as admin in any group to use restrict/ban/delete features
- `set_chat_administrator_custom_title` only works if the target user is already a Telegram admin
- ConversationHandlers use `per_message=False` — this is intentional for Arabic text entry flows
- The Developer rank is completely hidden from all public commands and staff lists

## Pointers

- See the `pnpm-workspace` skill for workspace structure
- MongoDB collections: groups, users, custom_responses, global_replies, pv_users, muted_users, banned_users, bot_config

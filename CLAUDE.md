# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (dev)
pip install -e ".[dev]"

# Run bot
python -m bot

# Run worker
python -m worker

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1

# Lint
ruff check .
ruff check . --fix

# Type check
mypy bot/ worker/ services/ db/

# Tests
pytest tests/unit/ -v --asyncio-mode=auto
pytest tests/ -v --asyncio-mode=auto          # requires running PG + Redis

# Docker (production)
docker compose up -d
docker compose logs -f bot
docker compose logs -f worker

# Generate Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Architecture

Two separate processes: **bot** (aiogram, user-facing) and **worker** (opentele2/Telethon, does actual broadcasting). They share PostgreSQL and communicate via `campaign.status` field — no direct IPC.

```
bot/          — aiogram 3.x Telegram bot (user interface)
  core/       — Bot instance, Dispatcher, pydantic-settings config
  handlers/   — One file per feature: start, sessions, posts, chats, campaigns, settings, stats, admin
  keyboards/  — Inline keyboards per feature + utils (paginate, back_button)
  middlewares/— UserMiddleware (auto-register), SubscriptionMiddleware (gate), ThrottleMiddleware
  states/fsm.py — All FSM state groups

worker/       — opentele2/Telethon worker (broadcasting)
  session_pool.py — Pool of active TelegramClient instances (keyed by session UUID)
  broadcaster.py  — Core broadcast loop: cycles, per-session offsets, delay/randomization
  scheduler.py    — APScheduler: polls DB every 10s for active campaigns, health-checks sessions

db/
  models.py      — SQLAlchemy 2.0 ORM (User, TelegramSession, Post, TargetChat, Campaign, ...)
  session.py     — async_session_factory (asyncpg)
  repositories/  — One repo per model; all queries scoped by user_id
  migrations/    — Alembic: 0001_initial_schema, 0002_user_settings, 0003_user_settings_cycle_delay

services/
  crypto.py        — Fernet encrypt/decrypt for StringSession storage
  subscription.py  — Check user subscription to required channels via Bot API
  session_auth.py  — QRLoginSession + PhoneLoginSession (opentele2 auth flows)
```

## Key design decisions

**Multi-tenant**: All DB queries are scoped by `user_id`. Each operator has isolated sessions, posts, chats, and campaigns.

**Session storage**: opentele2 `StringSession` is encrypted with Fernet before storing in `telegram_sessions.encrypted_session`. Key lives in `ENCRYPTION_KEY` env var.

**opentele2 vs telethon**: `TelegramClient` is imported from `opentele2.tl`, not `telethon`. Always use `api=API.TelegramIOS.Generate()` when constructing a client — this generates a unique device fingerprint per connection to avoid bans. `tl.types` (for message entities) is still imported directly from `telethon`. `StringSession` is still imported from `telethon.sessions`.

**Worker session pool** (`worker/session_pool.py`): `receive_updates=False` is set on all worker clients — the worker only broadcasts, never receives updates, which reduces the chance of Telegram dropping sessions.

**Broadcast loop** (`worker/broadcaster.py`):
1. Load campaign with relations
2. For each `CampaignSession`: `asyncio.gather(_broadcast_session(..., delay_offset))` — sessions run in parallel, staggered by `delay_offset_seconds`
3. Per chat: send → append to `pending_logs` → sleep(delay ± randomize) → flush logs every 10 chats
4. After full cycle: `increment_cycle()`, check `max_cycles`, sleep `delay_between_cycles` (optionally randomized between `cycle_delay_min`–`cycle_delay_max`)

**Campaign control**: `campaign.status` is the single source of truth. Worker polls every 10s via `WorkerScheduler._poll_campaigns()`. Pause is implemented by sleeping 3s loops until status changes. Stop sends a signal via `_stop_signals` dict in `broadcaster.py`.

**Settings hierarchy**: `UserSettings` holds global defaults. On campaign creation (`fsm_chats_done`), all fields are copied from `UserSettings` into a new `CampaignSettings` row. Each campaign's settings are then independent.

**Inline settings pattern**: Boolean fields toggle immediately on button click (no FSM). Numeric fields open a FSM state (`waiting_value`). Both `settings.py` (global) and `campaigns.py` (per-campaign) use this pattern with `_TOGGLE_FIELDS` + `_PROMPTS`/`_SETTING_PROMPTS` dicts.

**Conditional keyboard rows**: `settings_kb.py` and `campaigns_kb.py` only render `randomize_min`/`randomize_max` rows when `randomize_delay=True`, and `cycle_delay_min`/`cycle_delay_max` when `cycle_delay_randomize=True`.

**Session offsets**: Each `CampaignSession` has `delay_offset_seconds`. The broadcaster sleeps this offset before starting that session's loop. UI: campaign view → ⏱ Офсеты button → `session_offsets_kb` → `CampaignSessionOffset` FSM.

**QR login flow**: `QRLoginSession.start()` returns PNG bytes. A background `asyncio.Task` calls `qr_login.wait(timeout=30)` per `wait_for_scan()`. QR can be refreshed via `refresh_qr()` which calls `qr_login.recreate()`.

**Premium emoji**: Stored as serialized `message.entities` JSON in `text_entities` column. On send, deserialized to `tl.types.MessageEntityXxx` objects and passed as `formatting_entities` to Telethon. Only works if the sending session has Premium.

**Forward vs Copy**: `forward_mode=True` uses `client.forward_messages()`. `forward_mode=False` uses `client.send_message()` with content copied (no "Forwarded from" attribution).

## Callback data conventions

All callback_data strings follow `scope:action[:id]` format:
- `menu:*` — main menu navigation
- `gs:field` — global settings edit (settings.py)
- `csetting:field:campaign_id` — campaign settings edit
- `campaign:action:id` — campaign control (view, start, pause, stop, restart, delete, settings, offsets, progress, stats, test)
- `campaign:offset:edit:campaign_id:session_id` — session offset edit

## Environment variables

Required (see `.env.example`):
- `BOT_TOKEN`, `OWNER_ID`, `REQUIRED_CHANNEL_IDS`
- `ENCRYPTION_KEY` — Fernet key
- `DATABASE_URL` (asyncpg format), `DATABASE_SYNC_URL` (psycopg2, auto-derived if empty)
- `REDIS_URL`

**Not required:** `TELETHON_API_ID` / `TELETHON_API_HASH` — opentele2 uses official iOS API credentials internally. Fields exist in config with default `0`/`""` for backwards compatibility.

`config.py` auto-converts Railway's plain `postgresql://` URL to `postgresql+asyncpg://` for the app and `postgresql+psycopg2://` for Alembic.

## CI/CD

GitHub Actions: `.github/workflows/ci.yml` runs lint+types+unit tests on every PR. `.github/workflows/deploy.yml` SSHes to VPS on `main` push and runs `docker compose up -d`.

Railway deploy: `railway.toml` (bot) and `railway.worker.toml` (worker) — `preDeployCommand` runs `scripts/migrate.py` which waits for DB readiness before `alembic upgrade head`.

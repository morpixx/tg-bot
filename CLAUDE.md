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
docker compose run --rm migrate
docker compose logs -f bot
docker compose logs -f worker

# Generate Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Architecture

Two separate processes: **bot** (aiogram, user-facing) and **worker** (Telethon, does actual broadcasting). They share PostgreSQL and communicate via DB state (campaign.status field).

```
bot/          — aiogram 3.x Telegram bot (user interface)
  core/       — Bot instance, Dispatcher, pydantic-settings config
  handlers/   — One file per feature: start, sessions, posts, chats, campaigns, stats
  keyboards/  — Inline keyboards per feature + utils (paginate, back_button)
  middlewares/— UserMiddleware (auto-register), SubscriptionMiddleware (gate), ThrottleMiddleware
  states/fsm.py — All FSM state groups (SessionAddQR, SessionAddPhone, PostAdd, etc.)

worker/       — Telethon worker (broadcasting)
  session_pool.py — Pool of active TelegramClient instances (keyed by session UUID)
  broadcaster.py  — Core broadcast loop: cycles, per-session offsets, delay/randomization
  scheduler.py    — APScheduler: polls DB every 10s for active campaigns, health checks sessions

db/
  models.py   — SQLAlchemy 2.0 ORM (User, TelegramSession, Post, TargetChat, Campaign, ...)
  session.py  — async_session_factory (asyncpg)
  repositories/ — One repo per model: CRUD + domain queries
  migrations/ — Alembic, single initial migration in versions/0001_initial_schema.py

services/
  crypto.py        — Fernet encrypt/decrypt for StringSession storage
  subscription.py  — Check user subscription to required channels via Bot API
  session_auth.py  — QRLoginSession + PhoneLoginSession (Telethon auth flows)
```

## Key design decisions

**Multi-tenant**: Each operator (user) has their own sessions, posts, chats, and campaigns. All DB queries are scoped by `user_id`.

**Session storage**: Telethon `StringSession` is encrypted with Fernet before storing in `telegram_sessions.encrypted_session`. Key lives in `ENCRYPTION_KEY` env var.

**QR login flow**: `QRLoginSession.start()` returns PNG bytes of QR image. A background `asyncio.Task` calls `qr_login.wait(timeout=60)` and messages the user on result. QR can be refreshed via `qr_login.recreate()`.

**Broadcast loop** (`worker/broadcaster.py`):
1. Load campaign with relations
2. For each session: `asyncio.create_task(_broadcast_session(..., delay_offset))` — sessions run in parallel, staggered by offset
3. Per chat: send → log → sleep(delay ± randomize)
4. After full cycle: `increment_cycle()`, check `max_cycles`, sleep between cycles

**Campaign control**: `campaign.status` is the single source of truth. Worker polls every 10s. Pause is implemented by sleeping 3s loops until status changes.

**Premium emoji**: Stored as serialized `message.entities` JSON (`text_entities` column). On send, deserialized back to `MessageEntity` objects and passed as `formatting_entities` to Telethon. Only works if the sending session has Premium.

**Forward vs Copy**: `forward_mode=True` uses `client.forward_messages()` (shows "Forwarded from"). `forward_mode=False` uses `client.send_message()` with content copied — no attribution.

## Environment variables

See `.env.example`. Required:
- `BOT_TOKEN`, `OWNER_ID`, `REQUIRED_CHANNEL_IDS`
- `TELETHON_API_ID`, `TELETHON_API_HASH` — from https://my.telegram.org/apps
- `ENCRYPTION_KEY` — Fernet key (generate with command above)
- `DATABASE_URL` (asyncpg), `DATABASE_SYNC_URL` (psycopg2 for Alembic)
- `REDIS_URL`

## CI/CD

GitHub Actions: `.github/workflows/ci.yml` runs lint+types+unit tests on every PR. `.github/workflows/deploy.yml` SSHes to VPS on `main` push and runs `docker compose up -d`.

Secrets needed in GitHub repo: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.

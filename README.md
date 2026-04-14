# TG Broadcast Bot

Production-ready Telegram bot for mass-messaging across chats via multiple user accounts (Telethon sessions). Supports multiple operators, each with their own sessions, posts, and campaigns.

## Features

- **Multi-session broadcasting** — add multiple Telegram accounts, run campaigns in parallel with per-session timing offsets
- **QR code & phone login** — authorize accounts directly through the bot (no file uploads needed)
- **Flexible delays** — configurable delay between chats, optional randomization to avoid bans, shuffle chat list after each cycle
- **All post types** — text, photo, video, document; forward from channel (with or without attribution); Premium emoji support
- **Subscription gate** — blocks access until user subscribes to configured channels
- **Multi-operator** — each operator has isolated sessions, posts, chats, and campaigns
- **Admin panel** — owner can view all operators, force-stop campaigns, broadcast to all users
- **Live progress** — real-time update of sent/total chats during broadcast
- **Session health checks** — automatic detection of dead sessions with owner notification

## Architecture

Two separate processes communicate via the database:

```
┌─────────────────────────────────────┐    ┌──────────────────────────────────┐
│  bot/  (aiogram 3.x)                │    │  worker/  (Telethon)             │
│                                     │    │                                  │
│  Handles UI, FSM, keyboards         │    │  Polls DB every 10s              │
│  Subscription gate middleware       │    │  Manages TelegramClient pool     │
│  QR/phone session authorization     │    │  Runs broadcast loops            │
│  Campaign creation & control        │    │  Handles FloodWait, errors       │
└────────────────┬────────────────────┘    └────────────────┬─────────────────┘
                 │                                          │
                 └──────────────┬───────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │     PostgreSQL         │
                    │     Redis (FSM)        │
                    └───────────────────────┘
```

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- Telegram Bot Token — from [@BotFather](https://t.me/BotFather)
- Telegram API credentials — from [my.telegram.org/apps](https://my.telegram.org/apps)

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_user_id
REQUIRED_CHANNEL_IDS=-1001234567890   # comma-separated, or leave empty

TELETHON_API_ID=12345678
TELETHON_API_HASH=abcdef...

# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your_fernet_key=

POSTGRES_DB=bot_db
POSTGRES_USER=bot
POSTGRES_PASSWORD=strong_password
```

### 3. Run

```bash
docker compose up -d
```

This starts: PostgreSQL, Redis, runs Alembic migrations, then starts `bot` and `worker`.

```bash
# View logs
docker compose logs -f bot
docker compose logs -f worker
```

## Development

### Install

```bash
pip install -e ".[dev]"
```

### Run locally

```bash
# Start infrastructure
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start bot
python -m bot

# Start worker (separate terminal)
python -m worker
```

### Migrations

```bash
# Apply migrations
alembic upgrade head

# Create new migration (after changing models)
alembic revision --autogenerate -m "add something"

# Rollback one step
alembic downgrade -1
```

## Testing

```bash
# Unit tests (no database required)
pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
# Start DB first: docker compose up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://bot:bot@localhost:5432/bot_test \
  pytest tests/integration/ -v

# All tests
pytest -v
```

Unit tests cover:
- Crypto (encrypt/decrypt, key rotation, edge cases)
- Keyboards (all menus, pagination, button callbacks)
- Broadcaster (`_send_post` for all post types, FloodWait, errors)
- Session auth (QR image generation, phone/code/2FA flows)
- Session pool (connect, disconnect, health check)
- Subscription service (member/left/kicked, multiple channels)
- Middlewares (subscription gate, user auto-registration)
- Admin filter (owner vs non-owner)
- DB models (enum values, constraints)
- Repository logic (mocked session)

Integration tests cover full CRUD lifecycles for all repositories against a real database.

## Bot Usage

### Operator flow

1. `/start` — subscription check → main menu
2. **Sessions** — add account via QR code (scan in Telegram Settings → Devices → Link Device) or phone number
3. **Posts** — forward any message from a channel, or create manually (text/photo/video/document)
4. **Chats** — add target channels/groups by username or ID; bulk import from a text list
5. **Campaigns** — select post + sessions + chats → configure delays → start

### Campaign settings

| Setting | Default | Description |
|---|---|---|
| Delay between chats | 5 sec | Pause between each chat send |
| Randomize delay | off | Random delay in [min, max] range |
| Shuffle after cycle | off | Randomize chat order each cycle |
| Delay between cycles | 60 sec | Pause between full cycles |
| Max cycles | ∞ | Stop after N complete cycles |
| Send mode | Forward | Forward (shows source) or Copy (no attribution) |

### Session offsets

When using multiple sessions, each can have a timing offset. Example: session A starts at 0s, session B starts at 120s — both send to the same chats but 2 minutes apart.

### Admin commands (owner only)

| Command | Description |
|---|---|
| `/admin` | Owner panel — operators, active campaigns |
| `/notify_all` | Send a message to all bot users |

## Project Structure

```
bot/
  core/           Bot instance, config, dispatcher
  handlers/       start, sessions, posts, chats, campaigns, stats, admin
  keyboards/      Inline keyboards per feature + pagination utils
  middlewares/    UserMiddleware, SubscriptionMiddleware, ThrottleMiddleware
  states/fsm.py   All FSM state groups
  filters/        IsOwner filter

worker/
  session_pool.py   Active TelegramClient pool (keyed by session UUID)
  broadcaster.py    Broadcast loop: cycles, delays, FloodWait handling
  scheduler.py      APScheduler: polls campaigns, health-checks sessions

db/
  models.py         SQLAlchemy 2.0 ORM models
  repositories/     One repo per model (UserRepo, SessionRepo, ...)
  migrations/       Alembic migrations

services/
  crypto.py         Fernet encrypt/decrypt for StringSession
  subscription.py   Channel membership check via Bot API
  session_auth.py   QRLoginSession + PhoneLoginSession
```

## Deploy to Railway

Railway runs two services (`bot` + `worker`) from the same repo. Postgres is in the same environment; Redis goes in a separate environment (free-plan limit).

### Step-by-step

**1. Fork / push the repo to GitHub.**

**2. Create a Railway project → Add PostgreSQL plugin.**
Railway auto-injects `DATABASE_URL` — you don't set it manually.

**3. Add the "bot" service from your GitHub repo.**
- Settings → Config Path: `railway.toml` (default)
- Add the variables below.

**4. Add the "worker" service from the same repo.**
- Settings → Config Path: `railway.worker.toml`
- Share the same variables (Railway "Shared Variables" or copy them).

**5. Set these variables on both services:**

| Variable | Value |
|---|---|
| `BOT_TOKEN` | your bot token |
| `OWNER_ID` | your Telegram user ID |
| `TELETHON_API_ID` | from my.telegram.org/apps |
| `TELETHON_API_HASH` | from my.telegram.org/apps |
| `ENCRYPTION_KEY` | generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `REQUIRED_CHANNEL_IDS` | comma-separated IDs, or leave empty |
| `REDIS_URL` | from your Redis environment (see below) |
| `DATABASE_URL` | **do not set** — injected by Postgres plugin |

**6. Redis (separate environment on free plan):**
- Create a new Railway environment (or a second project).
- Add the Redis plugin → copy the `REDIS_URL` value.
- Paste it as a variable in the main environment for both services.

**How migrations work:**
`railway.toml` sets `preDeployCommand = "python scripts/migrate.py"`.
The script waits up to 60 s for Postgres to accept connections, then runs `alembic upgrade head`. This solves the "DB not ready" race condition that plain `alembic upgrade head` hits.

---

## CI/CD

GitHub Actions:

- **CI** (`.github/workflows/ci.yml`) — runs on every PR: `ruff`, `mypy`, `pytest tests/unit/`
- **Deploy** (`.github/workflows/deploy.yml`) — runs on `main` push: SSH to VPS → `docker compose up -d`

Required GitHub secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`

## Security Notes

- Telethon StringSessions are encrypted with Fernet before storage. The `ENCRYPTION_KEY` must be kept secret.
- Bot token and API credentials live in `.env` (never committed).
- The subscription gate blocks all users who are not subscribed to configured channels.
- Owner ID is hardcoded in config — only this user gets admin access.

# Lottery Passport

Backend for a brand-awareness game played at three gaming lounges: players scan the code
under the cap of a city-named drink (Tokyo, Moscow, Paris, ...) and collect **entries** in that
city's trip draw plus **coins** for challenges, tournaments and leaderboards.
FastAPI + PostgreSQL, hexagonal architecture, deployed on a domestic VM with Docker Compose.

## Contents

- [Documentation map](#documentation-map)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Everyday commands](#everyday-commands)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Status and known limitations](#status-and-known-limitations)

## Documentation map

| If you want to... | Read |
|---|---|
| Know what happens on which day until launch | [ROADMAP.md](ROADMAP.md) |
| Know what *you* have to do | [docs/TODO.md](docs/TODO.md) |
| Understand the system and its data | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/adr/](docs/adr/) |
| Build the frontend | [docs/API_CONTRACT.md](docs/API_CONTRACT.md), [docs/frontend/](docs/frontend/) |
| Print codes / talk to the factory | [docs/CODES.md](docs/CODES.md) |
| Run, deploy, back up, fix production | [docs/OPERATIONS.md](docs/OPERATIONS.md), [deploy/](deploy/) |
| Keep it safe | [docs/SECURITY.md](docs/SECURITY.md) |
| Test it | [docs/TESTING.md](docs/TESTING.md) |
| Design challenges and the economy | [docs/GAMIFICATION.md](docs/GAMIFICATION.md) |
| Run a draw nobody can call rigged | [docs/DRAW.md](docs/DRAW.md) |
| Know who does what | [docs/TEAM.md](docs/TEAM.md) |
| Avoid the classic traps | [docs/GOTCHAS.md](docs/GOTCHAS.md) |
| See what was wrong with the first version | [docs/REPO_REVIEW.md](docs/REPO_REVIEW.md) |

## Quick start

Requirements: Python 3.13+ and [`uv`](https://docs.astral.sh/uv/); Docker for the local database.

```bash
uv sync                           # all groups: dev, lint, test, codes-print
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
docker compose up -d postgres     # or any local PostgreSQL 16
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

The API is at `http://127.0.0.1:8000`, its interactive docs at `/docs` (development only).
Set `REDEMPTION_CODE_PEPPER` in `.env` to any 32+ character string for local redemption.

Try a redemption locally:

```bash
uv run python -m scripts.generate_codes --city tokyo --quantity 20 --coins-per-code 10 \
    --label "local test" --base-url http://localhost:5173 --output var/redemption-codes/local.csv
uv run python -m scripts.code_batches list
uv run python -m scripts.code_batches activate <batch-id>
```

Sign in through `POST /api/v1/auth/request` + `/verify` (the development sender keeps the
last code in memory; phone sign-in replaces this with B10), then `POST /api/v1/redemptions`
with one of the codes from the CSV.

## Configuration

All settings are environment variables (or `.env`), validated at startup by
`app/core/config.py`. Templates: [.env.example](.env.example) (local) and
[deploy/.env.production.example](deploy/.env.production.example) (servers).

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development`, `staging` or `production`; production refuses unsafe settings |
| `DATABASE_URL` | `postgresql+asyncpg://...` (plain `postgresql://` is converted) |
| `REDEMPTION_CODE_PEPPER` | Secret key for code hashes, 32+ characters outside development. **Never change it after printing** |
| `REDEMPTION_DAILY_LIMIT_PER_USER` | Codes one player may redeem per Tehran day (default 20) |
| `CAMPAIGN_TIMEZONE` | Game days and weeks (default `Asia/Tehran`) |
| `DB_STATEMENT_TIMEOUT_MS` | Kills runaway queries (default 15000) |
| `SESSION_COOKIE_NAME`, `AUTH_*` | Sessions and one-time codes |
| `RATE_LIMIT_*` | In-process backstop limiter; real limits live in nginx |
| `CORS_ORIGINS` | Only needed when the frontend is on another origin (production is same-origin). Staging and production: https only (http://localhost excepted), never `*`; `demo` is not checked |
| `SESSION_COOKIE_SAMESITE` | `lax` (default), `strict` or `none` (cross-site frontend, Chrome only) |
| `PUBLIC_APP_ORIGIN` | Public origin used for QR URLs, e.g. `https://torshx.com`; default for `scripts.generate_codes --base-url` |
| `LOG_LEVEL`, `LOG_JSON` | Logging |

## Everyday commands

```bash
uv run pytest                                   # tests (integration tests need TEST_DATABASE_URL)
uv run ruff check . && uv run ruff format --check . && uv run mypy app main.py scripts
uv run alembic revision -m "describe change"     # new migration (write it by hand, review it)
uv run python -m scripts.code_batches list       # batches and how many codes were redeemed
```

Integration tests run against a real, migrated PostgreSQL: see [docs/TESTING.md](docs/TESTING.md#running-the-tests).
After changing dependencies, regenerate the hash-locked file the Docker image uses:
`uv export --locked --no-default-groups --no-emit-project --no-header --format requirements-txt -o requirements.txt`.

## Project layout

```text
app/domain/          pure rules: code format, batches, ledger, passports, draw
app/application/     use cases and ports (unit of work, redemption, wallets, auth)
app/infrastructure/  PostgreSQL models, read repositories, unit of work adapter
app/api/             FastAPI routers, schemas, error envelope
scripts/             generate_codes, code_batches, loadtest_sessions (run with python -m)
alembic/versions/    database migrations (applied by deploy, never on startup)
deploy/              production Compose file, nginx, deploy/backup/restore scripts
loadtest/            k6 load test
docs/                everything in the documentation map
tests/               unit (fakes) and integration (PostgreSQL) tests
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No module named 'app'` when running a script | Run scripts as modules: `uv run python -m scripts.generate_codes ...` |
| Integration tests are skipped | `TEST_DATABASE_URL` is not set, or the database is not migrated (`alembic upgrade head`) |
| `REDEMPTION_NOT_CONFIGURED` from the API | `REDEMPTION_CODE_PEPPER` is empty |
| Production refuses to start: "REDEMPTION_CODE_PEPPER must be at least 32 characters" | Generate one: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| Codes from one environment do not work in another | Each environment has its own pepper and database, by design |
| Every player in a lounge gets `429` | The lounge's public IP is missing from `lounge_ips.conf` ([OPERATIONS.md](docs/OPERATIONS.md#nginx)) |
| Docker cannot pull base images on the server | Docker Hub refuses Iranian IPs: configure a domestic mirror ([OPERATIONS.md](docs/OPERATIONS.md#getting-images-and-packages-onto-the-server)) |

## Status and known limitations

Done: v2 codes, batches with activate/void, atomic and idempotent redemption with a daily cap,
append-only coin ledger and wallet, error envelope, reproducible draw algorithm, production
deployment files, load-test tooling. 131 automated tests, including concurrency tests on PostgreSQL.

Not yet: phone/SMS sign-in (still email; B10–B11), profile and lounges, challenges,
submissions, leaderboard, tournaments, admin panel. The day-by-day plan is in [ROADMAP.md](ROADMAP.md).
Deployment: CI builds one image per commit; staging (atpg) deploys it automatically, production
after an approved release. See [docs/OPERATIONS.md](docs/OPERATIONS.md#deploying-a-release).

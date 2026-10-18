# Command cheatsheet

Quick commands for day-to-day work. Run from the repo root. Scripts talk to the
database in `DATABASE_URL` (from `.env`), so check which database that is first.
On a server, prefix with
`docker compose -f deploy/compose.yml run --rm api` and drop `uv run`.

## Which database am I on?

```bash
# host and port only, credentials masked
grep '^DATABASE_URL' .env | sed -E 's#//[^@]*@#//***@#'
```

Port 6543 is the (retired) Supabase PgBouncer pooler.

## Admins

```bash
uv run python -m scripts.admins list                  # who is admin ("no admins" if none)
uv run python -m scripts.admins promote <identifier>  # make a user admin
uv run python -m scripts.admins demote <identifier>   # back to player
```

`<identifier>` is what the user signed up with: the phone number
(`+989XXXXXXXXX`). The user must sign in once first; the script does not create
accounts. There is no API route to become the first admin, by design.

Admin-only routes use the `require_admin` dependency in `app/api/deps.py`
(401 `AUTH_REQUIRED` if signed out, 403 `ADMIN_REQUIRED` if not admin).

## Look at users

```bash
uv run python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.core.config import get_settings
from app.infrastructure.postgres.database import PostgreSQLAdapter

async def main():
    db = PostgreSQLAdapter(get_settings())
    async with db.session_factory() as s:
        print((await s.execute(text(
            "select role, count(*) from public.users group by role"))).all())
        for row in await s.execute(text(
            "select identifier, role, account_status, verification_status, created_at "
            "from public.users order by created_at desc limit 20")):
            print(*row, sep=" | ")

asyncio.run(main())
EOF
```

Always write `public.users`: on Supabase a bare `users` also matches
`auth.users`, which has different columns.

## Code batches

```bash
uv run python -m scripts.code_batches list
uv run python -m scripts.code_batches formats
uv run python -m scripts.code_batches history <batch-id>
uv run python -m scripts.code_batches activate <batch-id>   # make redeemable
uv run python -m scripts.code_batches void <batch-id>       # stop unredeemed codes now
uv run python -m scripts.code_batches export <batch-id> --csv-sha256 <hash>  # also freezes the format
uv run python -m scripts.code_batches freeze <batch-id>
```

Generate and print (details in [CODES.md](CODES.md)):

```bash
uv run python -m scripts.generate_codes --city <city> --quantity <n> \
    --coins-per-code <n> --label "<description>" --output <file.csv>
uv run python -m scripts.qr_sheets --csv <file.csv> --paper A4 --per-page 50 --output <sheets.pdf>
```

A batch is redeemable only while `active`. Never change `REDEMPTION_CODE_PEPPER`
after printing.

## Database

```bash
uv run alembic upgrade head                 # apply migrations (never automatic on startup)
uv run alembic current                      # which revision the database is on
uv run alembic revision -m "describe change"  # new migration (write by hand, review)
```

## Run, check, test

```bash
uv run uvicorn main:app --reload            # dev server
uv run ruff check .
uv run ruff format --check .
uv run mypy app main.py scripts
uv run pytest                               # DB tests skip without TEST_DATABASE_URL
TEST_DATABASE_URL=<migrated db> uv run pytest
uv run python -m scripts.export_openapi     # refresh docs/openapi.json after route changes
```

Run the first four before every commit; CI fails on ruff errors. Commit messages
need a gitmoji, a type and a description, e.g. `✨ feat(auth): add login`.

## Staging smoke test (before telling the frontend a change is live)

Runs the whole frontend path against staging (error shape, test-number sign-in, cookie,
CSRF, profile, scan, sign-out). Needs one fresh staging code per run, generated ON the
staging server (its pepper never leaves it).

```bash
# on atpg (ssh atpg), one-off: 3 staging codes, activate the batch (prints the batch id)
cd /home/data/lottery-passport
repo/deploy/compose.sh run --rm -v "$PWD/var:/app/var" api python -m scripts.generate_codes \
  --city tokyo --quantity 3 --coins-per-code 10 --label "STAGING smoke-test codes" \
  --base-url https://staging.torshx.com --output var/redemption-codes/smoke-N.csv
repo/deploy/compose.sh run --rm api python -m scripts.code_batches activate <batch-id>
# every run, from your machine
uv run python -m scripts.smoke_demo --base-url https://staging.torshx.com \
  --origin https://staging.torshx.com --code <one printed_code from the CSV>
```

Never use a staging pepper for a print run.

## Dependencies

```bash
uv add <package>
uv export --locked --no-default-groups --no-emit-project --no-header --format requirements-txt -o requirements.txt
```

# Lottery Passport

Phase 1 provides the deployable backend foundation for the campaign platform:
FastAPI, typed settings, async PostgreSQL access, Alembic, health/readiness
checks, and CI quality gates. Product behavior is intentionally deferred to
later phases.

## Local setup

The project uses Python 3.13+ and `uv` for reproducible dependency management.

```powershell
uv venv --python 3.13
uv sync
Copy-Item .env.example .env
```

For local development, `.env` may point to the Compose PostgreSQL service from
the host using `localhost`:

```text
postgresql+asyncpg://postgres:postgres@localhost:5432/lottery_passport
```

Start PostgreSQL with an existing local installation or a development container:

```powershell
docker run --name lottery-passport-postgres `
	-e POSTGRES_PASSWORD=postgres `
	-e POSTGRES_DB=lottery_passport `
	-p 5432:5432 -d postgres:16
```

Run migrations and start the API:

```powershell
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

The API is available at `http://127.0.0.1:8000`. OpenAPI is at
`http://127.0.0.1:8000/docs`.

## Checks

Unit and API tests do not require PostgreSQL. To run the PostgreSQL integration
test, set `TEST_DATABASE_URL` to a dedicated test database first.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app main.py
```

Format code with `uv run ruff format .`.

## Configuration

Configuration is read from environment variables or `.env`. See
[`.env.example`](.env.example). Secrets must remain outside source control.
`CORS_ORIGINS` is a JSON array of explicitly permitted origins. `API_KEY` is a
secret for future internal/admin routes and is compared in constant time; it is
not required for `/health` or `/ready`. Demo, staging, and production require
`API_KEY` and an external `DATABASE_URL`. Render's standard `postgresql://`
URI is normalized to the async `asyncpg` driver automatically.

The current rate limiter is process-local and keyed by the direct client IP.
It is appropriate for the single-container demo, but distributed deployments
should move rate-limit state to a shared store such as Redis before scaling the
API horizontally.

Application logs use standard Python logging and structured JSON on stdout.
Each HTTP response includes an `X-Request-ID`, and request logs include that ID,
method, path, status, latency, and client IP. Credentials and request headers
are deliberately excluded. This output can be collected by Render or forwarded
to Logfire later without adding a Logfire dependency to the application.

## Architecture

`app/application` owns use cases and ports. `app/infrastructure` owns database
adapters. `app/api` owns HTTP routes and response models. The application
factory wires adapters into application services; no route creates connections
directly. Alembic is run as an explicit deployment step and is never invoked at
startup.

## Deployment sequence

For a deployment, install dependencies, set `ENVIRONMENT` to `demo`, `staging`,
or `production`, provide `DATABASE_URL` with the managed PostgreSQL URI and
credentials, run `alembic upgrade head`, then start Uvicorn without reload
mode. Non-development environments reject local database hosts, so Compose's
PostgreSQL service cannot become the production database accidentally.

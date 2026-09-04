# Lottery Passport Engineering Guide

## Architecture

Use Hexagonal Architecture with explicit Ports and Adapters.

- `app/domain/` contains business concepts and rules. It must be framework-free.
- `app/application/` contains use cases and ports (`Protocol` interfaces). It
  must not import FastAPI, SQLAlchemy, PostgreSQL drivers, OpenAI SDKs, email
  providers, or infrastructure modules.
- `app/infrastructure/` contains adapters for databases, email, AI providers,
  and other external systems. Adapters may depend on vendors and frameworks.
- `app/api/` contains FastAPI routes, request/response schemas, and HTTP
  dependency wiring. Routes call application services and do not own business
  rules.
- `app/app.py` is the composition root. Construct adapters there and inject
  them into application services.

Dependencies point inward:

```text
API -> Application -> Ports <- Infrastructure adapters
                         ^
                       Domain
```

Do not import infrastructure from domain or application code. Prefer small
protocols over large service interfaces. Use fakes in unit tests and real
adapters in integration tests.

## Current boundaries

The Phase 1 readiness check demonstrates the pattern: `ReadinessChecker` owns
the application behavior, `ReadinessPort` defines the required capability, and
`PostgreSQLAdapter` supplies the infrastructure implementation.

The future model has seven campaign/product passports: Paris, Berlin, Pattaya,
Mexico, Madrid, Tokyo, and Moscow. Model progress as multiple user passports,
not a single generic `User.passport_points` field. Do not implement that domain
yet without an explicit task.

## Working rules

- Keep database models and vendor SDK objects out of domain/application APIs.
- Keep FastAPI route functions thin.
- Put configuration and secrets in environment variables; never commit `.env`.
- Use UTC-aware timestamps when introducing timestamps.
- Add unit tests for application/domain behavior and integration tests for
  adapters and database guarantees.
- Run `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy app main.py`, and `uv run pytest` before completing changes.
- Use Alembic for every schema change. Never migrate automatically on app
  startup.
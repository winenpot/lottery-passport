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

- Multi-table writes go through the unit of work port
  (`app/application/unit_of_work.py`, adapter in
  `app/infrastructure/postgres/unit_of_work.py`): one transaction, explicit
  `commit()`, rollback otherwise. Redemption is the reference use case.
- Coins: append-only `coin_ledger_entries` (unique `idempotency_key`, a
  trigger rejects UPDATE/DELETE) plus `wallets.balance` updated in the same
  transaction. Never change a balance any other way.
- Printed codes: format v2 in `app/domain/codes.py` (frozen once printed);
  codes belong to `code_batches` and are redeemable only while `active`.
- Seven city passports (Paris, Berlin, Pattaya, Mexico, Madrid, Tokyo,
  Moscow); a passport city is a TorshX flavor (SKU, «طعم»), not a place.
  Lounges sit in real location cities (Tehran, Ahvaz, Mashhad, Isfahan); see
  `docs/GLOSSARY.md`. `passport_progress.points` counts entries in that city's draw.
  Parked for the MVP (ADR 0009): keep writing it, keep it out of the player
  contract.
- Simple reads and admin CRUD do not need a port per table; add one when a
  second real caller appears.
- `AuthenticationService` stays independent of FastAPI, SQLAlchemy and SMS
  vendors.

Read `ROADMAP.md`, `docs/ARCHITECTURE.md` and `docs/API_CONTRACT.md` before
changing behavior; update them (and any diagram) in the same commit.

## Working rules

- Keep database models and vendor SDK objects out of domain/application APIs.
- Keep FastAPI route functions thin.
- Put configuration and secrets in environment variables; never commit `.env`.
- Use UTC-aware timestamps when introducing timestamps.
- Add unit tests for application/domain behavior and integration tests for
  adapters and database guarantees.
- Run `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy app main.py scripts`, and `uv run pytest` (with
  `TEST_DATABASE_URL` pointing at a migrated database so the integration and
  concurrency tests run) before completing changes.
- Run scripts as modules: `uv run python -m scripts.<name>`.
- Dependency groups: `dependencies` is the production runtime only (keep it
  lean); tooling lives in groups `lint`, `test`, `dev` and `codes-print`.
- After dependency changes, regenerate `requirements.txt` with
  `uv export --locked --no-default-groups --no-emit-project --no-header --format requirements-txt -o requirements.txt`.
- Migrations during the campaign are additive only (expand, migrate, contract).
- If `app/domain/codes.py` changes, update `docs/frontend/codes.js` and
  `docs/frontend/code-test-vectors.json` together.
- Use Alembic for every schema change. Never migrate automatically on app
  startup.

## Two machines

This project is worked on from two machines (office and laptop), each with its
own Hermes memory, skills and `.hermes/plans/` (git-ignored, so they never
travel). The repository is the only shared state.

- Start with `git fetch` and `git status -sb`; finish by pushing (or opening a
  PR for) every commit. An unpushed commit is invisible to the other machine
  (W10 sat unpushed from 21 to 25 Oct while the laptop built on top of it).
- Whatever the other machine must know goes into the repo: decisions in `docs/`,
  the handoff in `docs/launch-reports/<date>-*.md` (public: no secrets, IPs or
  phone numbers).
- One alembic head: if origin gained a migration on the same parent as an
  unpushed one, renumber yours on top of it before pushing.
- Staging runs master; production runs approved `v*` tags only. Never move a
  server's `<base>/repo` checkout by hand, and never publish a frontend build to
  production that staging has not served first.
- Once per clone: `git config core.hooksPath .githooks` (gitmoji commit
  messages) and a `git config user.email` linked to the GitHub account.
- `CHANGELOG.md`, `docs/TODO.md` and `docs/ARCHITECTURE.md` change in the same
  PR as the behavior they describe, whichever machine wrote it.

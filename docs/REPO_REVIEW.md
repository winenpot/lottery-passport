# Code review: lottery-passport at commit 9199d2f (before this branch)

Reviewed 2026-10-07 against the new scope (phone sign-in, printed codes with real prizes,
coins, challenges, tournaments, leaderboards, domestic hosting, shared lounge IPs).
Status column: ✅ fixed in branch `feature/mvp-foundation`, 🔲 scheduled (TODO item).

## Summary

A solid foundation: typed FastAPI with hexagonal boundaries, Alembic discipline, CI with a
real PostgreSQL, server-side sessions with hashed tokens, HMAC-hashed codes and a conditional
update for single use. **Keep it; do not restart.** Five problems would have hurt the launch,
the first two badly: the code format was guessable, and a redemption could burn a code without
crediting it.

## Critical issues

| # | File | Line | Issue | Severity | Status |
|---|---|---|---|---|---|
| 1 | `app/application/redemption_codes.py`, `scripts/generate_redemption_codes.py` | 13; 37, 53–55 | Code space of 10^7 per city (`^[A-Z]{2}\d{7}$`). With 500,000 codes per city, 1 in 20 random guesses is a valid code; the city prefix adds no entropy | 🔴 Critical | ✅ v2 format, 50 random bits ([CODES.md](CODES.md)) |
| 2 | `app/application/redemption_codes.py` | 74–81 | `mark_redeemed` and `add_points` commit in two separate transactions: a crash or timeout between them burns the code with no credit | 🔴 Critical | ✅ unit of work ([ADR-0003](adr/0003-unit-of-work-and-append-only-ledger.md)) |
| 3 | `app/api/v1/users.py` | 51–64 | No idempotent replay: a client retry after a timeout gets "invalid code" for a code it just redeemed | 🔴 Critical (UX + support load) | ✅ `replayed: true` |
| 4 | `app/api/middleware.py` | 12–61 | Rate limiter keyed by client IP and kept in process memory: a lounge shares one IP (60 req/min for the whole lounge); several workers each count separately; resets on deploy | 🔴 Critical at the lounges | 🔲 B25 nginx zones with lounge allow-list; in-app limiter kept as a high backstop |
| 5 | `app/application/authentication.py` | 103–125, 196–200 | Email-only identifier; SMS would be sent inline (slow provider blocks the request); no per-identifier cooldown or daily cap (SMS pumping) | 🔴 Critical for launch | 🔲 B10, B11 |

## Suggestions

| # | File | Line | Suggestion | Category | Status |
|---|---|---|---|---|---|
| 6 | `app/core/config.py` | 48–69 | Rejects the Compose host `postgres` in production, which is exactly the single-VM setup | Deployability | ✅ loopback only |
| 7 | `render.yaml` | all | US free tier, ephemeral free database; unreachable during disruptions | Deployability | ✅ superseded ([ADR-0006](adr/0006-domestic-single-vm-docker-compose.md)) |
| 8 | `Dockerfile` | 1, 11 | Base image from Docker Hub and `uv` from ghcr.io: both can fail from Iranian servers | Deployability | ✅ hash-locked `requirements.txt` + any PyPI mirror; base image via a mirror |
| 9 | `app/infrastructure/postgres/models.py` | 101–122 | `passport_progress.points` is a mutable counter with no history (BUILD_SPEC section 13 asked for a ledger) | Correctness/audit | ✅ redeemed codes are the entry history; coins have an append-only ledger |
| 10 | `app/core/config.py` | 18 | OTP lifetime 600 s is long for SMS | Security | 🔲 B10 (150 s) |
| 11 | `app/infrastructure/authentication.py` | 14–15 | OTP hash is `SHA-256(salt:code)` with the salt in the same row: a leaked row is brute-forced in a million tries | Security (low: short lifetime) | 🔲 B10 keyed hash |
| 12 | `app/application/authentication.py` | 107–108 | Users are created at request time, before the number is proven: junk rows from attackers | Data hygiene | 🔲 B10 (create on verify or purge unverified after 7 days) |
| 13 | `app/api/deps.py` | 12–16 | Cookie name hard-coded while `SESSION_COOKIE_NAME` is configurable: changing the setting silently breaks sign-in | Correctness | ✅ read through the setting; staging/production use `__Host-lp_session` |
| 14 | `app/application/authentication.py` | 176 | Every authenticated request writes `last_used_at` | Performance (minor) | 🔲 throttle to once per few minutes when traffic grows |
| 15 | `app/infrastructure/postgres/repositories.py` | 354–376 | `get_unredeemed_by_hash` then `mark_redeemed`: two round trips where one `UPDATE ... RETURNING` suffices | Performance | ✅ single claim statement |
| 16 | `scripts/generate_redemption_codes.py` | 12–14 | Documented as `python scripts/...`, which fails with `No module named 'app'` | Correctness | ✅ `python -m scripts.<name>` |
| 17 | `.github/workflows/ci.yml` | 31–33 | `setup-uv` with `version: latest` | Reproducibility | ✅ pinned |
| 18 | API errors | — | `{"detail": "..."}` strings: the frontend cannot switch on stable codes | API design | ✅ `{"error": {"code", "message"}}` for new endpoints, 401, 429, 500; 🔲 auth endpoints with B10 |
| 19 | Tests | — | No redemption integration test and no concurrency test (BUILD_SPEC section 31 makes it mandatory) | Testing | ✅ including a deterministic lock-wait race |
| 20 | Database connections | — | No `statement_timeout`: a runaway query holds a connection forever | Resilience | ✅ `DB_STATEMENT_TIMEOUT_MS` |

## What looks good

- Hexagonal layering is real, not decorative: the services are tested with fakes, adapters with PostgreSQL.
- Sessions: random token, hashed at rest, HttpOnly + SameSite cookie, revocable.
- Codes stored as keyed hashes; the pepper is required outside development (fails closed).
- Single-use guarded by a conditional `UPDATE`, so the database participates in the guarantee.
- Authentication responses do not reveal whether an identifier exists.
- Structured JSON logs with request IDs and no secrets.
- Alembic as an explicit deployment step, never on startup.

## Verdict

**Request changes → done for 1–3, 6–9, 15–20 in this branch.** Items 4, 5, 10–14 are scheduled
in [TODO.md](TODO.md#you-backend-data-operations) before launch.

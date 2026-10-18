# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
releases are git tags `vYYYY.MM.DD-N` ([docs/OPERATIONS.md](docs/OPERATIONS.md#deploying-a-release)).

## [Unreleased]

### Added

- `TERMS_REQUIRED` setting (default `true`; production refuses `false`). With `false`,
  `profile_complete` needs only a nickname and redemption skips `TERMS_NOT_ACCEPTED`, so
  test environments work while the legal text does not exist yet; `terms_accepted` stays
  honest (never set on the player's behalf). `GET /config` exposes `terms_required`.

- Mini-games (G1, B38): our own in-app reaction game (`tap_reflex`), not the physical
  arcade machines at the OxinGame lounges. `POST /api/v1/mini-games/{mini_game_id}/runs`
  issues a server-chosen per-round delay array; `POST /api/v1/mini-games/runs/{run_id}/finish`
  judges plausibility (human reaction floor, not-all-identical, server wall-clock vs.
  delays+reactions) — an implausible finish is a normal 200 (`accepted: false`), never a
  4xx. One open run per user is a database guarantee (partial unique index), not just an
  application check. Rewards pay only through challenges, never from these endpoints
  directly. New `mini_game_runs` table (migration 0017).

- Daily check-in + achievements (C1 extension / AC1 MVP slice): new `daily_checkin`
  challenge kind (always completed once signed in; claiming it IS the login signal, no
  passive tracking needed) — supersedes the planned "5-day login"/"5-day activity" sheet
  items. `GET /api/v1/challenges` and the claim response gain `streak` (consecutive
  Tehran days checked in). New `achievements` catalogue (admin-editable, starts empty) +
  `user_achievements` (`UNIQUE (achievement_id, user_id)`: unlocks once per player, ever
  — breaking and rebuilding a streak cannot re-pay an already-unlocked milestone).
  Unlocking is automatic, inside the triggering `daily_checkin` claim's own transaction,
  and pays through the ledger immediately — no separate claim step. `GET
  /api/v1/me/achievements`; claim response gains `achievements_unlocked`.

- Automatic challenges (C1, B17): `challenges` catalogue table (admin-editable, starts
  empty) + `challenge_claims` (one row per user per challenge per period, UNIQUE is the
  idempotent-claim guard). MVP subset of kinds: `team_choice` (once, a player's first team
  join) and `distinct_flavors` (day/week/month, distinct flavors redeemed). New Tehran
  month key/boundary helpers in `app/domain/periods.py`. `GET /api/v1/challenges`,
  `POST /api/v1/challenges/{id}/claim`. New error codes `CHALLENGE_NOT_UNLOCKED`,
  `CHALLENGE_ALREADY_CLAIMED`.

- Flavor teams (P1/B36): 5 lifetime codes of a flavor unlock its team; `POST /me/team`
  joins/switches among unlocked flavors; switching is locked for 30 days after each join.
  `GET /api/v1/me/team`, `POST /api/v1/me/team`; `POST /api/v1/redemptions` gains
  `flavor_unlocked`. New error codes `FLAVOR_NOT_UNLOCKED`, `TEAM_LOCKED`, `TEAM_SAME`.
- Avatar catalogue (P1): `avatars` table (editable in `/admin`), `GET /api/v1/avatars`;
  `PATCH /me` accepts `avatar_id` (`422 AVATAR_LOCKED` for a locked one) and
  `location_city` (the player's real home city, never a flavor). `GET /me` gains
  `location_city`, `avatar_id`, `team` and `last_scanned_flavor`.
- `error.details`: an optional structured-data object on any error response (for example
  `{required, have}` on `FLAVOR_NOT_UNLOCKED`), additive to the existing envelope.
- Printed code format v2: city prefix + 10 random Crockford Base32 characters + Luhn mod 32
  check character; tolerant input normalization (Persian/Arabic digits, dashes, case, O/0, I/L/1).
- Code batches (`generated`, `active`, `void`) with `python -m scripts.generate_codes` and
  `python -m scripts.code_batches`; the generator writes a 0600 CSV with QR URLs and a SHA-256 file.
- Unit of work for multi-table writes; atomic redemption with idempotent replay and a per-user
  daily cap counted in Tehran days.
- Append-only coin ledger and wallets; `GET /api/v1/me/wallet`.
- `POST /api/v1/redemptions` with stable error codes in an `{"error": {"code", "message"}}`
  envelope (also used for 401, 429 and 500).
- Reproducible weighted draw (`app/domain/draw.py`) and its procedure (`docs/DRAW.md`).
- Production deployment: `deploy/compose.prod.yml`, nginx config with lounge-aware rate limits,
  `deploy.sh`, `backup.sh` (restic), `restore_check.sh`.
- Load testing: `loadtest/redeem.js` (k6, open model) and `python -m scripts.loadtest_sessions`.
- Frontend helpers: `docs/frontend/codes.js` and shared test vectors.
- Documentation: roadmap, per-person TODOs, architecture, ADRs 0001–0008, API contract,
  security, operations, testing, codes, draw, game design, team, gotchas, code review.
- Settings: `REDEMPTION_DAILY_LIMIT_PER_USER`, `CAMPAIGN_TIMEZONE`, `DB_STATEMENT_TIMEOUT_MS`.

### Changed

- The Docker image installs hash-locked `requirements.txt` (any PyPI mirror can be used safely)
  instead of copying `uv` from ghcr.io; CI checks the file matches `uv.lock`.
- Production may use a Compose service name as the database host; the pepper must be 32+
  characters outside development; blank secrets count as unset.
- CI type-checks `scripts/` and pins the `uv` version.

### Removed

- `POST /api/v1/me/redeem` (replaced by `POST /api/v1/redemptions`).
- `scripts/generate_redemption_codes.py` (v1 format).
- The non-transactional `PassportRepository.add_points` and `PostgreSQLRedemptionCodeRepository`.

### Fixed

- A crash between claiming a code and crediting it could burn the code without credit.
- Documented script invocation (`python scripts/...`) failed with `No module named 'app'`.

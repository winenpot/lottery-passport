# Changelog

All notable changes to this project. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
releases are git tags `vYYYY.MM.DD-N` ([docs/OPERATIONS.md](docs/OPERATIONS.md#deploying-a-release)).

## [Unreleased]

### Added

- Mini-game leaderboard (L1, B49, PR #7): `GET /api/v1/leaderboards/mini-games/{mini_game_id}?period=today|week|all`,
  Tap Reflex first. A board registry in `app/domain/leaderboards.py`, one ranking query
  with the first-to-set tie-break, a 60 s cache for the top 50. No migration;
  `features.leaderboard` stays off until the frontend screen exists.
- Admin TOTP second factor (B50, ADR-0013, PR #8, migration `0022_admin_totp`): opt-in
  per admin at `/admin/security/totp`, the secret Fernet-encrypted at rest
  (`ADMIN_TOTP_ENCRYPTION_KEY`; new production dependency `cryptography`), CLI-only reset
  `scripts.admins reset-totp`.
- Structured log events (B51, PR #5): `code_redeemed` (after the commit),
  `redemption_rejected`, mini-game run and coin-adjustment events.
- CI: gitleaks on every push and PR (PR #2) and a `commit-lint` job that runs
  `.githooks/commit-msg` on PR titles and commit subjects (PR #6); the image and the
  staging deploy wait for both.
- Operations scripts (22-23 Oct): `scripts/server_check.py` (read-only health report of a
  server over SSH), `scripts/backup_pull.py` (pg_dump over SSH to another machine,
  restore-verified), `scripts/reset_test_users.py` (retired for production on 23 Oct),
  `deploy/alert_check.sh` (SMS alerts; not installed yet), a fail2ban jail for sshd.
- `GET /media/{sha256}.{ext}` + admin "Images" page (B45/W10): content-addressed
  image upload (`media_assets` table, migration 0023, sha256 key, PNG/JPEG/WebP only by magic bytes,
  max 512 KB, SVG refused), immutable caching. No file field on the Avatar form itself
  (scope cut, documented) -- upload on the Images page, paste the URL into `image_url`.
- Weighted print runs (PC, decision 2026-10-21): `scripts/print_run.py` issues
  `k` codes split over the seven flavors by exact weights (sum 1) against a
  1,000,000-code pool (142,857 per flavor, a quota; codes are drawn fresh, no
  plaintext pool is stored). Refused as a whole if any flavor would pass its
  quota; one `generated`, export-frozen batch + shuffled CSV per flavor, a
  code-free `manifest.json`, advisory-locked, voided and cleaned up on a
  half-way failure. Pure allocation in `app/domain/print_runs.py`.
  `generate_batch(shuffle=True)` writes CSV rows in CSPRNG order.
- `GET /api/v1/achievements` (B44/W13): every active achievement row with `have`
  (progress toward `threshold`), `unlocked`, `unlocked_at` (null until unlocked) --
  closes B37's gap where a locked achievement didn't appear at all.
  `GET /me/achievements` (unlocked-only) is unchanged.
- Two challenge kinds (W12, B43): `first_mini_game` (once, any ACCEPTED
  `mini_game_runs` row) and `tap_reflex_fast` (period, an ACCEPTED
  `tap_reflex` run under a fixed 250 ms threshold --
  `app.domain.challenges.TAP_REFLEX_FAST_THRESHOLD_MS`). No new table --
  progress reads `mini_game_runs` directly, same principle as
  `distinct_flavors`. `challenges.kind`'s CHECK widened additively
  (migration 0021). Frontend copy for both still pending from Arman; until
  it merges they render as "چالش جدید" with claim disabled, like any other
  unknown-copy kind.
- `GET /me/stats` (B48): `scans_total`, `flavors_discovered`,
  `challenges_completed`, `achievements_unlocked`, `checkin_streak_days`,
  `mini_game_runs_accepted`, `mini_game_best_reaction_ms`. Not a SQL view --
  `PostgreSQLStatsReader` runs one round trip of independent, per-user-indexed
  scalar subqueries (each hits its own small index rather than scanning its
  table); a plain view buys nothing over that (Postgres just inlines the same
  query), and a materialized view would show a stale count right after a
  player's own scan. Fixes the frontend's "اسکن‌های من" box, which read a
  demo-only placeholder with no backend field behind it at all --
  `scans_total` is that field now.

- Reserved-name check on `PATCH /me display_name` (`DISPLAY_NAME_RESERVED`, 422): the
  legacy `display_name` field has no charset restriction of its own, so unlike
  `nickname` it let staff/brand/trademarked names like "Lich King" through with no
  reserved-word check and no uniqueness check. `app.domain.nickname.is_reserved_name`
  folds case/variants and strips whitespace/punctuation before comparing against the
  same `RESERVED_KEYS` list `nickname` uses, so "Lich King", "lich_king" and "LichKing"
  all match. `display_name` itself still has no uniqueness constraint (unlike
  `nickname`'s `uq_users_nickname_key`) — it was never meant to be unique and the
  contract is moving callers off it (`docs/API_CONTRACT.md` "Demo to contract
  migration").

- Referrals (RF1): invite a friend, earn coins through the existing ledger when
  their mission completes (a redeemed code, finished profile, chosen team, one
  accepted mini-game run). `PATCH /me referrer_code` (one-time bind, before any
  code is redeemed), `GET /me` `referral_code` (generated lazily), `GET
  /me/referrals` (invited/qualified/pending counts, coins earned). Migration
  0019 (`users.referral_code`, `referrals`). Settling runs on the invitee's own
  `GET /me` rather than inside redeem/team-join/profile-update/mini-game-finish
  — a deliberate simplification to avoid widening those four services'
  constructors; see `app/application/referrals.py`'s module docstring.

- Terms/privacy on the admin panel (LG1'): one "Terms & privacy" tab with a wide,
  right-to-left text field, seeded with the 2026-10-20 first draft (migration 0020,
  table `legal_documents`). `GET /legal/<version>` renders it as a Persian HTML page
  (headings with `#terms`/`#privacy` anchors, paragraphs, lists; everything escaped);
  nginx forwards `/legal/*` to the API, no caching, so an edit shows at once. A trigger
  freezes a version once any player accepted it (the panel explains the refusal).
  Replaces LG1's plain-text file serving (never deployed): nginx no longer mounts
  `docs/legal/`. `TERMS_VERSION`/`TERMS_URL`/`PRIVACY_URL` stay per-server `.env`
  pointers, set once Mehdi approves the text (LG2).

- `POST /auth/request` now rejects an unusual phone number (shape-valid, but
  the prefix is not on any publicly known allocated Iranian mobile range)
  with `422 PHONE_UNUSUAL` before any Kavenegar call — Kavenegar is never
  billed/attempted for it. Soft check: `0969` test numbers are unaffected
  (checked separately), and the list is a warning signal, not a hard
  validity gate, since the CRA can allocate new ranges at any time.

- `scripts.check_code` (B28): looks up a printed code or scanned QR URL and
  reports its batch, status and redemption state — without ever redeeming
  it. Printer QC checks a sample this way before and during each run
  (`docs/CODES.md` section 6). Also flags a batch whose stored pepper
  fingerprint column disagrees with the very pepper that matched the
  code's hash — only possible if that column was corrupted or hand-edited
  after generation, since a wrong pepper fails the lookup outright.

### Changed

- `/admin` answers every IP (24 Oct, owner's decision, PR #9): `site/admin_allow.conf` is
  `allow all;` on both hosts; the gate is identity (an SMS code only active admins
  receive, TOTP once enrolled).
- `alembic -x db_url=...` is honoured, and the target host is printed before migrating
  (PR #3).
- `docker-compose.yml` publishes the development Postgres on port 5432 (PR #4).
- W10's migration is `0023_media_assets`: written as 0022 on 21 Oct and never pushed, it was
  renumbered on 25 Oct to follow `0022_admin_totp` (one alembic head again).
- Deploys (ADR 0011): CI builds one image per master commit and pushes it to GHCR; staging
  (atpg, `staging.torshx.com`) deploys it automatically through a pull-based agent
  (`deploy/deploy.sh` + `lp-deploy.timer`) with migrations, `/ready` gate and automatic
  rollback; production follows an approved `v*` release (no rebuild). One nginx config for
  both environments (`deploy/nginx/`), Arvan client IP, `/b/` and `/q/` redacted in logs.
  Replaces `compose.prod.yml` and the build-on-server `deploy.sh`.
- Production nginx answers the bare domain `torshx.com` (where printed QR codes point):
  `/b/*` and `/q/*` 302 to `play.torshx.com`, everything else to `www.torshx.com`.
- Server setup as idempotent scripts: `deploy/server/provision.sh` (trim a desktop image,
  Docker with domestic mirrors, host settings, optional SSH hardening that refuses to lock
  the owner out), `install-app.sh` (layout, generated secrets, systemd units) and
  `firewall.sh` + `lp-firewall.service` (origin ports only for ArvanCloud, in DOCKER-USER).

### Changed

- Staging's Postgres/API/nginx containers are right-sized for sharing atpg with 30+ other
  containers (L0'): `deploy/compose.staging.yml` adds CPU caps (postgres 0.5, api 1.0,
  nginx 0.25); `compose.yml`'s `max_connections`, `work_mem` and nginx `mem_limit` are now
  configurable (defaults keep production's current behavior unchanged, plus an explicit
  `NGINX_MEM_LIMIT=128m`). `deploy/env/staging.env.example` tightens to a ~0.7 GB / 1.75-core
  ceiling (was ~1.8 GB with no CPU cap).

### Fixed

- `scripts.admins` (25 Oct) matches a phone number typed as `0912…` (or any usual form)
  against the stored `+989…` identifier; before, `promote`/`demote`/`reset-totp` answered
  "no user" unless the operator typed the `+98` form, a trap during a lost-phone reset.
  The TOTP setup page no longer says "Scan this" (there is no QR code) and shows the
  server command for a reset.
- nginx (25 Oct): only `/admin/login` POSTs count against an OTP-sized zone
  (`admin_login`, 6/min per IP); the rest of `/admin` gets the API's limits. PR #9 had put
  the player OTP zones on the whole panel, which refused its own CSS/JS (production log:
  18 of 21 static requests answered 429) and spent the player OTP budget of the admin's IP.
- nginx (25 Oct): the `/media` location regex is quoted; unquoted, its `{64}` failed
  `nginx -t`, so the deploy would have refused W10.
- `tests/unit/test_server_check.py` compares against the repo's alembic head instead of a
  hard-coded revision, which broke on every new migration.
- Admin panel: no catalogue row could be created from /admin. SQLAdmin leaves primary-key
  columns out of forms unless a view sets `form_include_pk`, so the avatar, challenge,
  achievement and reward-rule create forms had no `id`/`key` field; and their NOT NULL
  `created_at` (`updated_at` for reward rules) had no default, which the forms never fill.
  Both fixed (ORM-side UTC defaults, no migration); a test now creates one row of each
  through the panel.

- Mini-games (N17): an abandoned run (reload, closed tab, phone call) stayed `open` forever,
  because nothing ever marked a run expired and starting checked only `status = 'open'`;
  from then on every `POST /mini-games/tap_reflex/runs` for that player answered
  `409 MINI_GAME_RUN_ALREADY_OPEN`, even hours later. Starting a run now closes the
  player's open one as `expired` (the error code is gone), and a finish after the 2-minute
  TTL records the run as `expired` before answering `409 MINI_GAME_RUN_EXPIRED`.

- `tests/integration/test_redemption_flow.py::test_redemption_api_end_to_end` generated its
  sign-in identifier as a fully random `+989` + 9 digits, which lands outside
  `KNOWN_MOBILE_PREFIXES` (and now gets `PhoneUnusualError`, `app/domain/phone.py`) roughly
  60% of the time — a flaky ~60% failure rate, not a hard one, easy to miss in a single gate
  run. Switched to the same known-prefix helper already used by three sibling test files.

- `deploy/.env.production.example` was a stale, pre-ADR-0011 template (a non-existent
  `API_KEY` setting, `AUTH_CHALLENGE_TTL_SECONDS`/`AUTH_MAX_VERIFICATION_ATTEMPTS` instead of
  the real `OTP_TTL_SECONDS`/`OTP_MAX_ATTEMPTS`, no `ADMIN_SESSION_SECRET` — the app would
  refuse to start). Removed; README now points at the real, actively-used
  `deploy/env/staging.env.example` / `deploy/env/production.env.example`.

- `deploy/deploy.sh`: tagging the previous image as `:deployed-previous` is now best-effort.
  A deploy that otherwise fully succeeded (new image live, migrated, `/ready` green) could
  still exit non-zero and report as a failed systemd unit if that one bookkeeping image had
  been evicted from the local Docker cache between deploys.

- The session cookie is read through `SESSION_COOKIE_NAME` (it was hard-coded, so a renamed
  cookie made every session look logged out). Staging and production use
  `__Host-lp_session`; the settings refuse a `__Host-` name without Secure cookies.

### Removed

- Render: `render.yaml`, the `RENDER_GIT_COMMIT` alias (`GIT_COMMIT` is baked into the image).

### Added

- Pepper guard (ADR 0002 action item 4): `code_batches.pepper_fingerprint` (migration 0018),
  written by `scripts.generate_codes` for every batch from here on. At startup, and on every
  `GET /ready` poll, the app refuses to serve if an ACTIVE batch's fingerprint does not match
  the pepper it is running with now — a misconfigured `REDEMPTION_CODE_PEPPER` would otherwise
  silently turn every redemption into `CODE_INVALID`. A `NULL` fingerprint (pre-existing
  batches) is never flagged.

- Staging SMS gates: `OTP_TEST_NUMBERS` (explicit switch for the `0969` test numbers,
  default unchanged: development/demo only; production refuses `true`) and
  `OTP_ALLOWED_PHONES` (real SMS only to listed numbers, others `403 PHONE_NOT_ALLOWED`
  before anything is stored; production refuses a list).

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

# TODO by person

Every item has an ID (used in [ROADMAP.md](../ROADMAP.md)), a due day, and an acceptance check:
how anyone can see it is really done. Day numbers: D1 = Wed 7 Oct 2026 ... D15 = Wed 21 Oct 2026.
✅ = done in branch `feature/mvp-foundation`.

## Contents

- [Decisions needed by D2](#decisions-needed-by-d2)
- [You: backend, data, operations](#you-backend-data-operations)
- [Arman: frontend](#arman-frontend)
- [Mehdi: marketing](#mehdi-marketing)
- [CEO](#ceo)
- [Venue partners (the three lounges)](#venue-partners-the-three-lounges)
- [Factory and printer](#factory-and-printer)
- [Legal counsel](#legal-counsel)

## Decisions needed by D2

Send this list on D1. If a decision is not made by its deadline, **the default applies** and
the item is closed; reopening it later goes through the swap rule.

| # | Decision | Owner | Default if undecided |
|---|---|---|---|
| Q1 | Where is the code printed (under the cap, inside the tab, on a peel label)? It must be **invisible until the drink is opened** | Mehdi + factory | Under the cap / inside the tab; nothing printed on the outside |
| Q2 | Can the factory print a unique QR per unit, or only text? | Factory | Text code per unit + one static QR on the label that opens the site |
| Q3 | Quantities per city and print dates | Mehdi + factory | One pilot batch of 5,000 Tokyo codes |
| Q4 | Coins per code, and are some batches entries-only (no coins)? | Mehdi | 10 coins per code |
| Q5 | Daily cap of redemptions per person | Mehdi | 20 per day (Tehran day) |
| Q6 | Prize list with budget and stock; what coins will buy | Mehdi + CEO | Coins accumulate; the store opens in Phase 2 |
| Q7 | Draw rules: one draw per city or one grand draw, dates, eligibility | Mehdi + legal | No draw date announced at launch; entries count from day one |
| Q8 | Minimum age to participate; minors need guardian consent? | Legal | 18+ for prizes; younger players can play but cannot win travel prizes |
| Q9 | Who approves social submissions and how fast (SLA) | Mehdi | Mehdi, within 24 hours, every day including weekends |
| Q10 | Leaderboard rank by what | Mehdi | Coins **earned** this week (Saturday 00:00 Tehran to Friday 23:59) |
| Q11 | Which Instagram account/hashtag the social challenges use | Mehdi | One hashtag and one account to tag, fixed for the season |
| Q12 | Support channel for players (wrong code, lost coins) | Mehdi | One Instagram DM account and one phone number, answered daily |
| Q13 | Public domain name for the app | You + CEO | `play.<company-domain>` subdomain |
| Q14 | Product/brand name shown in the app and the SMS | Mehdi | The campaign name used on the posters |

## You: backend, data, operations

| ID | Due | Item | Done when |
|---|---|---|---|
| B01 | ✅ | Code format registry (`app/domain/codes.py`): `v2-b10` default (city prefix + 10 Crockford Base32 + check character); normalization of Persian digits, case, separators, look-alikes; pluggable `CodeFormat` dataclass so a second format (e.g. digits-only) is a one-file addition; browser mirror (`codes.js` + `code-formats.json`); cross-language parity tests (`codes.test.mjs`, `test_code_vectors.py`); startup drift guard for frozen batches | Tests green; [CODES.md](CODES.md) sec. 7 describes adding a format |
| B01b | ✅ | Roles: `users.role` column (player/admin today, migration 0008; staff/marketing only when a real caller needs them); `scripts.admins promote/demote/list`; `require_admin` API dependency (done); OPERATIONS.md runbook step. T2.3 builds the admin panel on these roles. | `scripts.admins list` shows at least one admin after first deploy; go-live checklist includes the check |
| B02 | ✅ | Batch generator and batch CLI (`list`, `activate`, `void`) | A test batch generated, activated and voided on staging |
| B03 | ✅ | Atomic redemption (one transaction), idempotent replay, daily cap in Tehran days | Concurrency tests green on PostgreSQL |
| B04 | ✅ | Coin ledger (append-only), wallet, `GET /api/v1/me/wallet` | Ledger UPDATE/DELETE rejected by the database |
| B05 | ✅ | Error envelope `{"error": {"code", "message"}}` for new endpoints | Documented in [API_CONTRACT.md](API_CONTRACT.md) |
| B06 | D1 | Create the real `REDEMPTION_CODE_PEPPER` (48+ random characters) and store it in a password manager with one backup holder. **Never change it after printing** | Two people can retrieve it; it is not in git, chat or email |
| B07 | D1 | Send [the decisions list](#decisions-needed-by-d2) to Mehdi and the CEO with the defaults | Message sent, deadline D2 stated |
| B08 | ✅ | Request the staging VM now and the production VM for D8 from a **domestic** provider; ask for the `play.` subdomain | Staging reachable over SSH |
| B09 | **Partly done** (Kavenegar only; `logintorshx`/`signuptorshx` Approved with the `@play.torshx.com #code` last line, checked 2026-10-21; no second provider) | Open accounts with two SMS providers; submit the OTP template (see [OPERATIONS.md](OPERATIONS.md#sms-provider)) | Template submitted with the `@domain #code` last line |
| B10 | ✅ | Phone sign-in: Iranian mobile normalization (`+989XXXXXXXXX`), 2–3 minute OTP, 60 s resend cooldown and daily cap per phone, keyed OTP hash | Unit and API tests; a code arrives on your phone via the console sender |
| B11 | D4 | `jobs` table + worker process + SMS gateway adapter (verify/lookup endpoint) with timeouts, retry with jitter, expiry of stale OTP jobs, fallback provider | Killing the worker mid-send does not lose or duplicate the job beyond one extra SMS |
| B12 | ✅ (no worker: SMS goes out inline, B11 not built; TLS at ArvanCloud's edge) | Staging: Docker Compose (nginx, api, worker, postgres), TLS, `.env` from the password manager | `https://staging.../health` returns ok |
| B13 | ✅ (2026-10-20: 24 codes, 3 flavors x 8, plus a smoke batch) | First **test** batch (never printed), activated on staging; give Arman 20 QR URLs | Arman redeems one from his phone |
| B14 | D4 | First **print** batch per agreed quantities; encrypt; send; confirm checksum; record chain of custody ([CODES.md](CODES.md#handing-codes-to-the-printer)) | Factory confirms the checksum; batch stays `generated` |
| B15 | ✅ (lounges themselves are B16 data, not entered yet) | Profile: nickname (rules in [SECURITY.md](SECURITY.md#user-generated-text)), home lounge, consent version + timestamp; `GET /api/v1/config` (cities, lounges, server time, current day/week keys) | Nickname with RTL-override or zero-width tricks is rejected |
| B16 | D5 | **Done (code; lounges not entered yet)** — `venues` table with the three lounges (name, city, public IP if known) | Shown in the profile picker |
| B17 | ✅ | Challenges: model, progress computed from data, `POST /claim` idempotent via the ledger key `challenge:<id>:<period>:<user>`. MVP subset: `team_choice` (once), `distinct_flavors` (day/week/month) and `daily_checkin` (day) kinds; `admin`-editable `challenges` catalogue starts empty. "First game"/"Tap Reflex" kinds are not built yet (their data exists since G1; planned as B43); `daily_checkin` supersedes the sheet's "5-day login"/"5-day activity" items — the claim itself is the login signal, no passive tracking needed (see [Decisions](vault/Decisions.md) 2026-10-15) | Double claim pays once (test) |
| B18 | D7 | Manual/social submissions: URL validation (Instagram domains), status machine, approve/reject with reason, payout on approve | Approve twice pays once (test) |
| B19 | ✅ | Failed-redemption throttle per account (for example 10 `CODE_INVALID` per hour, then 429) | Test proves the 11th is refused |
| B20 | D8 | **Steps 1-3 done** (sign-in + read-only views; audit log; coin adjustment), plus create/edit for the avatar, challenge, achievement and reward-rule catalogues (57f6f2c), lounge edit, the terms editor (B41), the mini-game runs view (B42), the Images page (B45) and the TOTP second factor (B50). Next: approve/reject submission (needs B18). Admin panel (SQLAdmin, [ADR-0008](adr/0008-sqladmin-back-office.md) as amended): `admin` role + fresh-SMS admin session (no separate admin accounts), audit log of every admin write, coin adjustment form writing ledger entries. The nginx IP allow-list is `allow all;` on both hosts since 24 Oct (owner's decision); only the sign-in POSTs are rate-limited | Mehdi approves a submission himself; audit row exists |
| B21 | D8 → Phase 2 | Weekly leaderboard per lounge and overall (coins earned, Saturday-to-Friday Tehran week), top 50 + my rank, 30–60 s in-process cache. **Not built**; the board architecture it plugs into shipped with B49 (a second source over the ledger, same endpoint shape) | Matches a hand-computed SQL result |
| B22 | D11 | Tournaments: admin creates, staff enters results, payouts via ledger key `tournament:<id>:<place>` | Results entered twice pay once |
| B23 | ✅ (ADR 0011; first release `v2026.10.19-1`) | Production VM, deploy script (build, migrate, restart), release tags | Deploy of a tag takes under 10 minutes and is repeatable |
| B24 | ◐ (21 Oct) | Backups: `pg_dump` every 6 hours and nightly to an off-site encrypted repository (restic); **restore drill** into a scratch database. Done: 6-hourly `backup.sh` on production since 21 Oct (every run OK on 25 Oct) and the restore drill (21 Oct, 5 s). Open: the restic repository is on the same VM; the off-site copy (`scripts.backup_pull` to the office PC) is not installed | Restore timed and written down (RTO) in [OPERATIONS.md](OPERATIONS.md#backups-and-restore) |
| B25 | ◐ (23 Oct) | Security pass per [SECURITY.md](SECURITY.md#pre-launch-security-checklist): nginx limits (lounge IPs allow-listed), headers, `/docs` off, code paths redacted from logs, gitleaks, pip-audit. Run of 23 Oct recorded there. Open: origin TLS (self-signed until acme.sh, expires 17 Nov), admin TOTP enrollment (B50), SSH port open to any source, `npm audit` on the frontend, off-site backups (B24) | Checklist ticked, findings fixed or written down |
| B26 | D11 (open) | Monitoring: external uptime checks, error tracking, disk/CPU, SMS credit and failure rate; alerts by SMS/email (not Telegram: unreachable from a domestic server). `deploy/alert_check.sh` exists (22 Oct) but is installed on neither host (25 Oct: no `site/alert.env`, no timer, no cron entry) | A test alert reaches your phone |
| B27 | D12 | Load test with k6 (arrival-rate executor) at 5x the expected peak ([TESTING.md](TESTING.md#load-test)) | p99 and error rate recorded at a stated load |
| B28 | ✅ | ~~Admin~~ `scripts.check_code` CLI for factory quality control: shows batch and status without redeeming | Factory sample of 10 caps checked |
| B29 | ✅ (21–24 Oct) | Feature freeze; release candidate to production; migrations; seed lounges and challenges. Releases `v2026.10.21-1`, `v2026.10.21-2`, `v2026.10.24-1`; production holds 2 challenges and nothing else yet (B52) | Production smoke test passes |
| B30 | D13 | Dry run with 10 internal testers; train Mehdi and staff on the admin panel | Every tester completed the loop |
| B31 | D14 | Pilot at lounge #1: watch logs and metrics live; hotfixes only | Pilot report written |
| B32 | ✅ (23 Oct) | Go/no-go; activate launch batches; launch. Live since 23 Oct by the owner's decision (23 Oct handoff, decision 1), with Mehdi's sheet codes active; the bottle print run is generated, not yet with the printer | Decision recorded |
| B33 | should | Leaderboard TV page for lounge screens | Runs 8 hours on a lounge screen without a reload |
| B34 | should | Venue check-in: rotating signed QR on the lounge screen (60 s validity) | A photo of the QR is useless after a minute |
| B35 | should | Tournament self-registration | |
| B36 | ✅ | Teams (flavor), unlock + monthly lock ([vault decision 2026-10-15](vault/Decisions.md)): 5 codes of a flavor (lifetime) unlock it (`flavor_unlocked` in the redemption response); the player joins an unlocked flavor with `POST /me/team`; switching is locked for 30 days after each join; `team_memberships` history. Feature-flag gate is F1's job, not built yet: the endpoints are live and ungated for now | Join with 4 codes refused with 409 `FLAVOR_NOT_UNLOCKED`; join at 5 works; a switch on day 29 is refused with 409 `TEAM_LOCKED` (`switch_allowed_at`), on day 30 it works |
| B37 | **Partly done** (D12 extra hours for the rest) | Achievements + badges: spec in [GAMIFICATION.md](GAMIFICATION.md). **Done**: the unlock-and-pay MECHANISM — `achievements` catalogue (`admin`-editable, starts empty), `user_achievements` (`UNIQUE (achievement_id, user_id)`: one-time ever, not per-period, by design — see [Decisions](vault/Decisions.md) 2026-10-15), auto-unlock + ledger pay inside the triggering `daily_checkin` claim's own transaction, `GET /me/achievements`. One fact wired: `checkin_streak`. **Not done, waiting on Ashkan/Mehdi's approved 8-12 item list + artwork**: `badges` catalogue (images, locked/unlocked art), `GET /badges`, a generic `FactPublisher` port for other fact sources (a game score, a lounge-visit count), `/config.features.achievements` gate (F1 doesn't exist yet either). A catalogue read with locked rows and progress is B44 | Reaching a 3-day check-in streak returns `streak_3` in `achievements_unlocked` exactly once, even after a break-and-rebuild |
| B38 | ✅ | Mini-games (G1): our own in-app reaction game (`tap_reflex`; the second has no agreed mechanic, not built), not the lounges' physical arcade machines. `POST /mini-games/{mini_game_id}/runs` (server-chosen per-round delays), `POST /mini-games/runs/{run_id}/finish` (plausibility check: reaction floor, not-all-identical, server wall-clock vs. delays+reactions). Rewards pay only through challenges (`first_mini_game`/`tap_reflex_fast` challenge kinds: B43). `/config.features` gate is F1's job, not built yet | A finish with all-identical reactions returns `accepted: false` (200, not an error); a second start while one is open closes the old run as expired and returns a new one (N17, 2026-10-20; was 409 `MINI_GAME_RUN_ALREADY_OPEN`, which locked out a player who reloaded) |
| B39 | ✅ | Pepper guard (L2, migration 0018): `generate_codes` stamps `code_batches.pepper_fingerprint` (an HMAC of a fixed label, never the pepper); startup and every `/ready` refuse to run when an ACTIVE batch's fingerprint differs from the running pepper (null = legacy batch, never flagged) | A wrong pepper on a server with an active batch turns `/ready` into 503 instead of every code silently answering `CODE_INVALID` |
| B40 | ✅ | Referrals (RF1, migration 0019; pulled forward from "later" by the owner's decision of 2026-10-19): `PATCH /me referrer_code` binds once, only before the invitee's first code, never yourself; `GET /me` `referral_code`; `GET /me/referrals`. Inviter earns 15 coins for the friend's first code once the friend's mission is complete (finished profile, chosen team, one accepted mini-game run), then 5 per later code for 180 days, through the ledger (`referral:first:<invitee>`, `referral:code:<code id>`), settled on the invitee's own `GET /me`. Oxin-visit referral row: update 1 | Staging rehearsal 2026-10-20: payout pending until the mission completes, then 15 + 4 x 5 paid once across repeated `/me` reads |
| B41 | ✅ | Terms and privacy in the database (LG1', migration 0020): `legal_documents` (one row per version), edited in `/admin` "Terms & privacy", public page `GET /legal/<version>` (HTML, right to left); a trigger freezes a version once a player accepted it. Production `TERMS_VERSION`/`TERMS_URL`/`PRIVACY_URL` wait on Mehdi's approval of the text | Staging renders `/legal/2026-10-20`; editing an accepted version is refused with a readable message |
| B42 | ✅ (21 Oct, a32c017) | Mini-game runs in `/admin`, read-only: each run's player, game, status, accepted/rejected with reason, average reaction, start/finish times; filter on rejected; rejected count per player. No migration | A rejected staging run is visible and filterable, and the admin panel test covers the view |
| B43 | ✅ (21 Oct) | Challenge kinds from Mehdi's sheet whose data already exists: `first_mini_game` (period `once`, any accepted mini-game run; sheet: 20 coins) and `tap_reflex_fast` (period `day`, an accepted `tap_reflex` run that Tehran day with an average under a server-side threshold, default 250 ms; sheet: 20 coins). Migration widens `ck_challenges_kind` (expand only, like 0016); contract + openapi; Arman adds copy for both kinds | An accepted fast run makes the claim pay once per Tehran day; a slow or rejected run does not; a second claim the same day answers `CHALLENGE_ALREADY_CLAIMED` |
| B44 | ✅ (21 Oct) | `GET /api/v1/achievements`: every active achievement with `unlocked_at` (or null) and progress for `checkin_streak`, so the page is not empty before the first unlock (B37's missing locked view) | A new player sees every active row locked with progress 0/threshold; after a check-in the 1-day row shows unlocked |
| B45 | ✅ (21 Oct) | Image upload in `/admin` (avatars first; later badge and prize art): table `media_assets` (sha256 key, PNG/JPEG/WebP only by magic bytes, max 512 KB; SVG refused), an "Images" page, public `GET /media/<sha256>.<ext>` with immutable caching and `nosniff`, nginx location. Stored in Postgres so backups and both hosts need nothing extra; same-origin, so the PWA's CSP and avatar rules need no change. Scope cut: no file field bolted onto the Avatar form itself (SQLAdmin only renders form fields backed by a real model column) — upload on the Images page, paste the returned URL into `image_url`, same two-step shape as a venue's coordinates today | An admin uploads a 200 KB WebP on staging, pastes its URL into the Avatar form's `image_url`, a player picks it in the app; an SVG and a 600 KB file are refused with a readable message |
| B46 | after launch (owner, 21 Oct) | Frontend auto-deploy on staging follows Arman's `resolved-build` receipt (ADR-0012 update 2026-10-21): `deploy_frontend.sh` patch, `FRONTEND_GH_TOKEN` (created by a human in GitHub's web UI), `lp-frontend-deploy.timer` installed on atpg only | A docs-only push to TorshX_2 `main` republishes nothing; a new accepted build is live on staging within about a minute |
| B47 | ✅ (21 Oct) | Reserved-name check on `PATCH /me display_name` (`DISPLAY_NAME_RESERVED`, 422): `display_name` has no charset restriction, unlike `nickname`, so it let staff/brand/trademarked names like "Lich King" through with no check at all. `app.domain.nickname.is_reserved_name` folds and strips whitespace/punctuation against the same `RESERVED_KEYS` `nickname` uses | `PATCH /me {"display_name": "Lich King"}` (or `lich_king`, `LichKing`) answers 422; `nickname` already rejected it outright (its charset has no space) |
| B48 | ✅ (21 Oct) | `GET /me/stats`: `scans_total`, `flavors_discovered`, `challenges_completed`, `achievements_unlocked`, `checkin_streak_days`, `mini_game_runs_accepted`, `mini_game_best_reaction_ms`. `PostgreSQLStatsReader` -- one query, per-user-indexed scalar subqueries (`ix_redemption_codes_redeemer_time`, `ix_challenge_claims_user`, `ix_user_achievements_user`, `ix_mini_game_runs_user_status`), not a SQL view (a plain view is just inlined query text, a materialized one would go stale right after a player's own scan). The streak reuses `ChallengesReader.checkin_days` + `current_streak`, same as `GET /challenges`. Fixes the "اسکن‌های من" box: it read a demo-only placeholder (`useScanStats()` hardcoding `count: null`) with no backend field at all -- `scans_total` is that field. Coins/referrals NOT duplicated here, see `GET /me/wallet`/`GET /me/referrals`. Told Arman (`.hermes/plans/2026-10-21_messages.md`) | `GET /me/stats` answers `{"scans_total": 0, ..., "mini_game_best_reaction_ms": null}` for a fresh user (tests/integration/test_me_stats_db.py) |
| B49 | ✅ (24 Oct, PR #7) | Leaderboard architecture (L1): a board registry in `app/domain/leaderboards.py` (metric, best = lowest or highest, periods today/week/all), ranking and the first-to-set tie-break in one SQL query, 60 s cache for the top 50 (`me` never cached), no migration. First board: Tap Reflex, `GET /api/v1/leaderboards/mini-games/{mini_game_id}`. `features.leaderboard` stays `false` until the frontend screen exists | `tests/integration/test_leaderboards_db.py`: each player's best run counts once, ties go to whoever set it first |
| B50 | ◐ (24 Oct, PR #8) | Admin TOTP second factor ([ADR-0013](adr/0013-admin-totp-second-factor.md)): RFC 6238 in the standard library, secret Fernet-encrypted at rest (`ADMIN_TOTP_ENCRYPTION_KEY`), self-service enrollment at `/admin/security/totp`, CLI-only reset (`scripts.admins reset-totp`), opt-in per admin. **Open**: with `/admin` open to every IP since 24 Oct, every admin enrolls (0 of 3 on production on 25 Oct), then a forced-enrollment redirect (ADR-0013 option B) | On production, admins with `totp_confirmed_at IS NULL` count 0 |
| B51 | ✅ (24 Oct, PR #5) | Structured log events in the application services: `code_redeemed` (written after the commit), `redemption_rejected`, mini-game run, coin-adjustment and admin TOTP events; fields pass the `JsonFormatter` allow-list. The domain-events design (events collected on the unit of work, one handler writes the line) waits for a second consumer of the same facts | `test_a_failed_commit_never_logs_code_redeemed` (tests/unit/test_redemption_service.py) |
| B52 | open (25 Oct) | Production catalogues: lounges (0 on production, 5 on staging), achievements (0; staging has the check-in streak rows), avatars (0; seven rows pointing at the frontend's own avatar files, proposed to Arman on 25 Oct, waiting for his answer), more challenges (2 live). Same rows and numbers as staging unless Mehdi retunes them | `/config` lists 5 venues on play; `GET /api/v1/achievements` lists the streak rows; `GET /api/v1/avatars` is not empty |
| B53 | Mon 26 Oct | Staging basic auth (launch-week decision R3): one shared bcrypt credential for the owner and Arman, given to him privately for his Vite proxy and Playwright; the deploy checks keep working | An anonymous `curl https://staging.torshx.com/` answers 401; CI's staging-verify and Arman's tests still pass |

## Arman: frontend

Ground rules are in [TEAM.md](TEAM.md#working-with-arman); the API is in [API_CONTRACT.md](API_CONTRACT.md).

| ID | Due | Item | Done when |
|---|---|---|---|
| A01 | D1 | Stack: static PWA (for example Vite + React + TypeScript), built to static files served by our nginx; no Node server in production | `npm ci && npm run build` produces `dist/` |
| A02 | D1 | Persian RTL layout, **self-hosted fonts** (for example Vazirmatn), no Google Fonts or foreign CDNs, dark theme tokens | Page loads with all foreign domains blocked |
| A03 | D1 | Routes: `/`, `/login`, `/r/:code`, `/redeem`, `/passport`, `/wallet`, `/challenges`, `/leaderboard`, `/tournaments`, `/profile` | Skeleton deployed to staging |
| A04 | D2–D4 | Login: phone input accepting Persian digits; OTP input with `autocomplete="one-time-code"`; resend countdown driven by the server's `Retry-After` | Works on a real Android and a real iPhone |
| A05 | D4 | `/r/:code`: if signed out, keep the code in `sessionStorage`, sign in, then redeem; afterwards remove the code from the URL (`history.replaceState`) | Back button does not resubmit; code not left in history |
| A06 | D4 | Manual entry: `dir="ltr"`, `autocapitalize="characters"`, `autocomplete="off"`, `spellcheck="false"`, live grouping and local check-character validation ([CODES.md](CODES.md#validating-codes-in-the-browser)) | A one-character typo shows "check this character" before submitting |
| A07 | D5 | Passport (seven city stamps with entry counts) and wallet (balance + history) | Matches the API after a redemption |
| A08 | D6 | Challenges: daily/weekly lists, progress bars, claim button | Claim shows new balance |
| A09 | D7 | Social submission form (URL), status list (pending/approved/rejected with reason) | Invalid URLs blocked client-side and server-side |
| A10 | D8 | Leaderboard: lounge tabs, own rank pinned | Own rank visible even outside the top 50 |
| A11 | D7 | Profile: nickname, home lounge, T&C consent | Server validation errors shown next to the field |
| A12 | D9 | Every API error code mapped to Persian copy; loading, empty and offline states; 401 sends to login and returns | No raw English error reaches the user |
| A13 | D11 | WebOTP on Android Chrome (progressive: manual entry still works) | Code fills itself on Android |
| A14 | D11 | Performance budget: initial JS under ~200 KB gzipped; usable on a low-end Android on mobile data | Lighthouse mobile run recorded |
| A15 | D11 | Works under our Content-Security-Policy (no inline scripts, no `eval`), no tokens in `localStorage` (the session cookie is HttpOnly) | No CSP violations in the console |
| A16 | D11 | PWA manifest, icons, "add to home screen" hint; do not cache API responses in a service worker | Installable on Android |
| A17 | should | Leaderboard TV mode page | Readable from 3 metres |
| A18 | should | Story image generator (canvas, 1080x1920) | Image saves on iPhone and Android |
| A19 | should | Check-in scan flow | |

## Mehdi: marketing

| ID | Due | Item | Done when |
|---|---|---|---|
| M01 | D2 | Factory meeting with [CODES.md](CODES.md) in hand: hidden placement, print method (QR or text), test print, quantities, dates | Written answers to Q1–Q3 |
| M02 | D1 start, D12 due | Legal: written opinion on the draw, permits, T&Cs, privacy notice, minors, travel-prize conditions ([GOTCHAS.md](GOTCHAS.md#legal-and-prizes)) | Signed opinion on file |
| M03 | D4 | Prize list, budget, coin economy (start from [GAMIFICATION.md](GAMIFICATION.md#default-economy)) | Table approved by CEO |
| M04 | D8 | Draw rules (dates, eligibility, verification, what happens if a winner cannot travel) | Draft reviewed by legal |
| M05 | D4 | Per lounge: staff contact, opening hours, screen for leaderboard, poster spots, Wi-Fi public IP (ask their ISP/router admin) | Table filled for all three |
| M06 | D5, loaded D11 | Challenge calendar for the first 14 days, only using types the system supports ([GAMIFICATION.md](GAMIFICATION.md#challenge-catalog)) | Entered in the admin panel |
| M07 | D6 | Brand assets: logo, colours, seven city stamp illustrations, all in-app Persian copy | Files delivered to Arman |
| M08 | D7 | Posters/standees with the static QR, ordered from the print shop | Proof approved |
| M09 | D1 | Company documents the SMS provider needs; sender name | Provider account approved |
| M10 | D9, training D13 | One-page staff guide: how players join, what to say about codes, how to enter tournament results | Staff can explain the app in 30 seconds |
| M11 | D12 | Launch comms: posts, lounge announcements, FAQ, support channel; **no marketing SMS without opt-in** | Content scheduled |
| M12 | D13 | 10–20 pilot testers from lounge #1 regulars | Names and phone numbers collected with consent |
| M13 | D4 | KPIs agreed with the CEO (see [GAMIFICATION.md](GAMIFICATION.md#what-to-measure)) | Written in one paragraph |
| M14 | daily from D12 | Approve/reject social submissions within the SLA; review flagged nicknames | Queue never older than 24 hours |
| M15 | D8 | Join you for 8–10 short interviews with players at a lounge ([TEAM.md](TEAM.md#a-90-minute-field-visit)) | Notes shared; at least one challenge changed because of them |

## CEO

| ID | Due | Item |
|---|---|---|
| C01 | D1 | Confirm the launch definition and the must/should cut line in [ROADMAP.md](../ROADMAP.md#scope-must-should-later) |
| C02 | D1 | Approve spend: two domestic VMs, SMS credit (two providers), off-site backup storage, print runs, prizes |
| C03 | D1 | Assign legal counsel with a D12 deadline |
| C04 | D2 | Name one person who signs off economy and prize decisions (default: Mehdi, CEO countersigns) |
| C05 | D15 | Chair the go/no-go meeting |

## Venue partners (the three lounges)

| ID | Due | Item |
|---|---|---|
| V01 | D5 | One staff contact per lounge with a phone number (for admin accounts) |
| V02 | D5 | Public IP address of the lounge network (for rate-limit allow-listing), and whether it changes |
| V03 | D12 | Poster spots near the vending machines and the counter |
| V04 | D12 | A screen and browser for the leaderboard (should-have) |
| V05 | D13 | Lounge #1 hosts the pilot on D14 |
| V06 | from D14 | Tournament schedule and a staff member who enters results |

## Factory and printer

| ID | Due | Item |
|---|---|---|
| P01 | D2 | Confirm what can be printed per unit: 13-character code (with dashes) and/or a QR; minimum QR size; font; hidden placement |
| P02 | D3 | Test print of 20 units with test codes; we scan and type them on staging |
| P03 | per run | Receive the encrypted CSV, verify the SHA-256 checksum, confirm in writing; delete the file after printing and confirm |
| P04 | per run | Quality control: send photos of 10 random units per run; we check them with the admin QC tool |
| P05 | per run | Report misprints or file loss immediately (we void the batch) |

## Legal counsel

| ID | Due | Item |
|---|---|---|
| L01 | D12 | Is a purchase-linked draw lawful here; which permit or supervision (notary, authority) is required |
| L02 | D12 | T&Cs and privacy notice in Persian: data collected (mobile number, nickname), retention, contact |
| L03 | D12 | Minors: can they play, can they win, guardian consent |
| L04 | D12 | Travel prizes: passport, visa refusal, conscription-age travel permits, taxes, transferability, cash alternative |
| L05 | D12 | Consent wording for marketing messages |

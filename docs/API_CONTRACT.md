# API contract (player app)

The agreement between the backend and the PWA (TorshX × Oxin). Every screen in the
2026-10-10 frontend demo maps to an endpoint here. **Live** endpoints exist in the code
today. **Planned** ones have their final shapes, so the frontend can mock them now (for
example with Mock Service Worker) and switch over when the backend item ships.

The machine-readable version is FastAPI's OpenAPI document (see [OpenAPI](#openapi)).
If this file and `/openapi.json` disagree about a live endpoint, open an issue. To change
the contract, edit this file in a pull request first; the code follows the contract.

Parked features (not in the MVP contract): the city passport. See
[parked/CITY_PASSPORT.md](parked/CITY_PASSPORT.md) and ADR 0009.

## Changelog

Newest first. **Breaking** means a call that worked before needs a change on your side.
Check `GET /health` → `commit` to see which backend commit is deployed on the demo.

**2026-10-21 (doc truth pass, no code change)**

- Removed: the planned "Invites" section (`GET /me/invite`, `POST /me/invite/redeem`,
  `INVITE_INVALID`). Referrals (RF1, live since 2026-10-20) replaced it; see
  [Referrals](#referrals).
- Fixed: the error table lists the four `REFERRAL_*` codes and the live `MINI_GAME_*`
  codes instead of the old draft's `GAME_SESSION_INVALID` / `SCORE_REJECTED`;
  `CHALLENGE_NOT_COMPLETED` was never emitted (a claim before the target answers
  `CHALLENGE_NOT_UNLOCKED`). The screen map points at the live mini-game, referral and
  avatar endpoints; the wallet `reason` list is the set the backend actually writes.
- Clarified: an avatar `image_url` must be served from the app's own origin (the PWA's
  CSP is `img-src 'self' data: blob:`); the earlier `cdn.torshx.com` example host does
  not exist.
- Moved: [Achievements](#achievements) now comes after the challenge submissions it used
  to split in two.
- Planned, not live: challenge kinds `first_mini_game` and `tap_reflex_fast` (B43),
  `GET /api/v1/achievements` with locked rows and progress (B44), avatar images uploaded
  in `/admin` and served at `/media/<sha256>.<ext>` (B45).

**2026-10-20 (LG1': terms and privacy page)**

- Added: `GET /legal/{version}` (no sign-in, HTML, right to left), the page `terms_url`
  and `privacy_url` will point at — see [Terms and privacy page](#terms-and-privacy-page).
  The text is edited in the admin panel. A server's `/config` keeps `terms_url` /
  `privacy_url` null until its `.env` points them at the page, and `terms_version` names
  the version to send as `accept_terms_version`.

**2026-10-20 (N17: an abandoned mini-game run no longer locks the player out)**

- Changed: `POST /mini-games/{mini_game_id}/runs` never answers `409` any more. If the
  player still has an open run (reload, closed tab, lost response), starting a new one
  closes the old one as expired and returns the new run. Before, an abandoned run stayed
  open forever and every later start answered `409 MINI_GAME_RUN_ALREADY_OPEN`, even
  after its 2 minutes. The error code `MINI_GAME_RUN_ALREADY_OPEN` is gone.
- Changed: finishing a run that a newer start replaced answers
  `409 MINI_GAME_RUN_EXPIRED` (same as finishing after the 2 minutes), not
  `MINI_GAME_RUN_ALREADY_FINISHED`. Use the newest `run_id` only.

**2026-10-20 (RF1: referrals)**

- Added: `PATCH /me` accepts `referrer_code` (bound once, only before your first redeemed
  code, never your own); `GET /me` gains `referral_code`; `GET /me/referrals`
  (`invited_count`, `qualified_count`, `pending_count`, `coins_earned`). Errors
  `REFERRAL_CODE_UNKNOWN` (422), `REFERRAL_SELF` (422), `REFERRAL_CODE_TOO_LATE` (422),
  `REFERRAL_ALREADY_BOUND` (409). Wallet reasons `referral_first_code` and
  `referral_later_code`. See [Referrals](#referrals).

**2026-10-19 (FX1-FX3, FX7: browser-readable errors, config truth pass, feature flags)**

- Errors: `429`/`500` responses now carry `Access-Control-Allow-Origin` and
  `Access-Control-Expose-Headers: Retry-After, X-Request-ID` like every other
  error (FX1); `Idempotency-Key` is in `allow_headers` (a preflight sending it
  used to fail); a CORS preflight no longer counts toward the rate limit.
  `REDEMPTION_DAILY_LIMIT` now carries `Retry-After` (seconds to Tehran
  midnight). Fixed a stale doc name: `SCAN_DAILY_LIMIT` never existed in code.
- Added: `GET /config` gains `terms_url`, `privacy_url` (null until legal
  supplies real text), `flavors` (`[{id, code}]`, the 7 passport-city SKUs —
  `TeamChangeRequest.flavor`'s description finally points at a real field)
  and `features` (read side of feature flags: `mini_games` on, `leaderboard`
  / `venue_checkin` / `diamonds` off until each ships or gets legal sign-off;
  no route enforces these yet).
- Doc fixes, no code change: auth examples use `identifier`, not a `phone`
  field that was never accepted; code examples use a check-digit-valid code
  (`TO-HA1-NQC-C32`); `docs/TEAM.md`'s QR example used a dead `/r/` path.

**2026-10-18 (staging moves home)**

- The Render test API (`lottery-passport.onrender.com`) is retired. Staging is
  `https://staging.torshx.com`: the frontend build and the API on ONE origin (`/api/*`,
  `/health`, `/ready`, `/docs`, `/admin` go to the API, everything else is the build). No
  CORS, `SameSite=Lax` cookie, no cold start. Every master commit that passes CI deploys
  there automatically; `GET /health` → `commit` shows which one is live.
- Production will be `https://play.torshx.com`, same layout.

**2026-10-18 (staging SMS gates)**

- Added: `403 PHONE_NOT_ALLOWED` on `POST /auth/request`: on the staging server real SMS go
  only to the team's numbers; any other real number is refused before anything is
  stored. Use a `0969` test number there (staging has them on, production never).

**2026-10-18 (optional terms outside production)**

- Added: `GET /config` returns `terms_required` (bool). When `false` (test environments
  only, until the legal text exists; production always `true`), `profile_complete`
  needs only a nickname and `POST /redemptions` no longer answers
  `403 TERMS_NOT_ACCEPTED`. `terms_accepted` stays `false` until the player really
  accepts: never send `accept_terms_version` on the player's behalf. Explicit
  acceptance still works as before.

**2026-10-15 (G1 mini-games)**

- Added: `POST /api/v1/mini-games/{mini_game_id}/runs` and
  `POST /api/v1/mini-games/runs/{run_id}/finish` — see [Mini-games](#mini-games). Only
  `tap_reflex` ships. Rewards pay only through challenges, never from these endpoints.
- Added: error codes `MINI_GAME_RUN_ALREADY_OPEN` (409), `MINI_GAME_RUN_ALREADY_FINISHED`
  (409), `MINI_GAME_RUN_EXPIRED` (409), `MINI_GAME_ROUND_COUNT_MISMATCH` (422).
- Replaces the earlier frontend-mock draft in this section (`GET /api/v1/games`,
  `aim`/`cps`/`seq`, `game_of_the_day`, a direct coin cap) — none of that is built; the
  real design is server-issued runs with a plausibility check instead.
- Renamed throughout: this is our own in-app reaction mini-game, not the physical
  arcade machines at the OxinGame lounges. `game_id` → `mini_game_id` in every path and
  JSON field below, including the still-planned leaderboard routes.

**2026-10-15 (AC1 + C1 daily check-in)**

- Added: `daily_checkin` challenge kind (period `day`, `have`/`target` always `1`/`1`).
  Claiming it IS the "player used the app today" signal — supersedes the earlier-planned
  "5-day login"/"5-day activity" sheet items (no passive tracking needed). `GET
  /api/v1/challenges` and the claim response gain a `streak` field (int for
  `daily_checkin` rows, `null` otherwise) — see
  [Challenges and submissions](#challenges-and-submissions).
- Added: `GET /api/v1/me/achievements` — see [Achievements](#achievements). Streak
  milestones (e.g. 3/7/30 days) auto-unlock and auto-pay once per player, ever, the
  moment a `daily_checkin` claim crosses them — no claim endpoint for this.
- Added: `POST /api/v1/challenges/{id}/claim` response gains `achievements_unlocked`
  (list of `{id, reward_coins}`, auto-paid in the same transaction as the claim).

**2026-10-15 (C1)**

- Added: `GET /api/v1/challenges` and `POST /api/v1/challenges/{id}/claim` — see
  [Challenges and submissions](#challenges-and-submissions). MVP subset: two automatic
  kinds (`team_choice`, `distinct_flavors`); replaces the earlier `?type=` / title+
  description draft written against the frontend demo mock.
- Added: error codes `CHALLENGE_NOT_UNLOCKED` (409), `CHALLENGE_ALREADY_CLAIMED` (409).

**2026-10-15**
- Added: `GET /api/v1/avatars` (no sign-in needed): the avatar catalogue, `[{id, image_url,
  locked}]`. `PATCH /me avatar_id` picks an unlocked one; `422 AVATAR_LOCKED` otherwise
  (avatar unlocks by coins/achievements are AFTER LAUNCH).
- Added: `GET /api/v1/me/team` and `POST /api/v1/me/team` — see [Teams](#teams). A flavor
  (one of the 7 passport cities) unlocks for a player after 5 lifetime codes of it; the
  player then CHOOSES a team among unlocked flavors; switching is locked for a while
  after each join.
- Added: `PATCH /me` accepts `location_city` (one of `/config`'s `location_cities`, the
  player's real home city — never a flavor) and `avatar_id`.
- Added: `GET /me` returns `location_city`, `avatar_id`, `team` (current flavor team, or
  null) and `last_scanned_flavor` (the most recently redeemed code's flavor, for the
  frontend's flavor-mood theming).
- Added: `POST /redemptions` response gains `flavor_unlocked` (campaign slug, or null):
  set on the redemption that brings one flavor to 5 lifetime codes.
- Added: error codes `FLAVOR_NOT_UNLOCKED` (409), `TEAM_LOCKED` (409), `TEAM_SAME` (422)
  and `AVATAR_LOCKED` (422). `error.details` is a new optional object on any error for
  structured extra data (`{required, have}` on `FLAVOR_NOT_UNLOCKED`, `{switch_allowed_at}`
  on `TEAM_LOCKED`); existing clients reading only `code`/`message` are unaffected.

**2026-10-13**
- **Breaking:** `POST /redemptions` now requires a complete profile: `403 TERMS_NOT_ACCEPTED`
  (terms not accepted yet) or `403 PROFILE_INCOMPLETE` (no nickname). `GET /me/wallet` is
  unchanged.
- Demo data: `GET /config` now returns 5 lounges (OxinGame branches in Tehran, Ahvaz and
  Isfahan; ids `punak`, `ahvaz-golestan`, `ahvaz-kianpars`, `isfahan-khane`,
  `isfahan-mirfenderski`) with their addresses. Mashhad is a supported city but has no lounge
  yet. Which lounges are in the campaign is not final.
- **Breaking:** every error now uses `{"error": {"code", "message", "request_id"}}`. Unknown
  paths (404), wrong methods (405), validation (422, with `fields`) and `/ready` 503 used to be
  FastAPI's `{"detail": ...}`.
- **Breaking:** a `POST`/`PATCH`/`DELETE` that carries the session cookie must send
  `X-Requested-With` (any value), or it gets `403 CSRF_REJECTED` ([rule 6](#hosts-cors-and-cookies)).
- Added: test phone numbers `0969 xxx xxxx` (demo only): the response of `POST /auth/request`
  carries `test_code`, no SMS is sent.
- Added: `GET /config` returns `location_cities` (tehran, ahvaz, mashhad, isfahan, with Persian
  names; real cities with lounges, NOT passport cities, which are flavors) and `venues`
  (`[{id, name, location_city, address}]`, `location_city` is one of those ids, `address` is
  Persian text or null); `PATCH /me` accepts `home_venue_id` (`CATALOGUE_UNKNOWN` if not an active venue);
  `GET /me` returns `home_venue_id`.
- Added: `GET /health` returns `version`, `commit` and `environment`.
- Demo hosting: the session cookie is `SameSite=None; Secure`; CORS also allows
  `http://127.0.0.1:5173`, `:5174` and `http://localhost:5173`, `:5174`. The demo shares a free
  Render plan, so the first call after a quiet period can take about a minute.

**2026-10-12**
- Added: `PATCH /me` with `nickname` (rules in [Config and profile](#config-and-profile)) and
  `accept_terms_version`; `profile_complete` on `GET /me`; public `GET /config` (server time,
  Tehran day and week keys, limits, terms version, nickname limits).
- Added: staff-only `GET /admin/users` (keyset pagination).

**2026-10-11**
- **Breaking:** sign-in is by Iranian mobile number with an SMS one-time code (`POST /auth/request`,
  `POST /auth/verify`); the email sign-in is gone. The request field is still named `identifier`.
- Added: `role` on `GET /me`; this contract now covers every screen of the 2026-10-10 demo.

**2026-10-10**
- Added: `CODE_ATTEMPTS_LIMITED` (429) after too many invalid codes in an hour.

## Contents

- [Changelog](#changelog)
- [Conventions](#conventions)
- [Hosts, CORS and cookies](#hosts-cors-and-cookies)
- [Errors](#errors)
- [Screen map](#screen-map)
- [Authentication](#authentication)
- [Config and profile](#config-and-profile)
- [Terms and privacy page](#terms-and-privacy-page)
- [Avatars](#avatars)
- [Teams](#teams)
- [Scanning codes](#scanning-codes)
- [Wallet and activity](#wallet-and-activity)
- [Daily streak](#daily-streak)
- [Daily wheel](#daily-wheel)
- [Mini-games and game leaderboards](#mini-games)
- [Weekly coins leaderboard](#weekly-coins-leaderboard)
- [Referrals](#referrals)
- [Challenges and submissions](#challenges-and-submissions)
- [Achievements](#achievements)
- [Connected social accounts](#connected-social-accounts)
- [Reward shop](#reward-shop)
- [Weekly PS5 draw](#weekly-ps5-draw)
- [Events and tournaments](#events-and-tournaments)
- [Arrivals from QR links](#arrivals-from-qr-links)
- [Admin](#admin)
- [Health](#health)
- [OpenAPI](#openapi)
- [Frontend recipes](#frontend-recipes)
- [Demo to contract migration](#demo-to-contract-migration)

## Conventions

| Topic | Rule |
|---|---|
| Base URL | `{API_ORIGIN}/api/v1/...`. `API_ORIGIN` is a build-time setting in the PWA, because hostnames are not final (see below). |
| Format | JSON in and out, UTF-8, `snake_case` fields. |
| Points | The UI says «امتیاز». The API calls the same thing `coins`: one balance, backed by the append-only ledger. |
| Authentication | Session cookie set by `POST /auth/verify` (HttpOnly, Secure). Always call `fetch(..., {credentials: "include"})`. JavaScript never sees or stores a token. |
| Time | ISO 8601 in UTC, for example `2026-10-10T08:30:00Z`. "Today" and "this week" come from `GET /config` (Tehran day, Saturday–Friday week), never from the phone clock. Convert to Tehran time / Jalali for display. |
| IDs | UUID strings, except catalogue ids (games, avatars, rewards, favourite games, venues), which are short stable slugs such as `tap` or `pad`. |
| Idempotency | Most state changes are idempotent by construction (resubmitting a redemption returns the original result with `"replayed": true`; a claim is a real `UNIQUE` constraint). `Idempotency-Key` is accepted on every `POST`/`PATCH`/`DELETE` (listed in CORS `allow_headers`) for a future write that needs it, but nothing checks it today — don't rely on it until an endpoint's own section says so. |
| Rate limits | `429` with a `Retry-After` header (seconds). Show a countdown; never retry before it. |
| Versioning | Additive changes stay in `/api/v1`; ignore unknown fields. Breaking changes go to `/api/v2`. |
| Server decides | The server decides spin results, streak rewards, which scores count, stock and prices. The client only shows what the server returns. |

## Hosts, CORS and cookies

| Environment | Frontend and API (one origin) | Database |
|---|---|---|
| Staging | `https://staging.torshx.com` | Its own PostgreSQL, test data |
| Production | `https://play.torshx.com` | Its own PostgreSQL |

Printed QR codes point at `https://torshx.com/b/<code>`, which redirects to the app.

Rules that hold whatever the final names are:

1. **Prefer same-origin.** The frontend host proxies `/api/*` to the API (a rewrite rule
   on the static host, or nginx). Then there is no CORS, and cookies are first-party in
   every browser.
2. **If the API is on a different origin**, it must be the **same site**, i.e. a subdomain
   such as `api.torshx.com`. The API then allows CORS with credentials for an explicit list
   of origins (`CORS_ORIGINS`, never `*`), and the cookie is `SameSite=Lax` with no
   `Domain` attribute.
3. **Never rely on a cross-site cookie** (frontend on `torshx.com`, API on
   another registrable domain). Safari and Firefox block third-party cookies, so sign-in
   would work in desktop Chrome and fail on iPhone. For local work, use the Vite dev proxy
   (`server.proxy`) against staging.
4. Plain `http://<ip>:<port>` frontends (the current demo) are cross-site **and** insecure.
   Browsers allow the camera (QR scanning), WebOTP and `Secure` cookies only on HTTPS
   pages, and Safari blocks the cross-site cookie anyway. They are fine for looking at
   screens, but not for testing sign-in and scanning. For that, serve the build over HTTPS
   on a real hostname with `/api` proxied (rule 1).
5. The SMS one-time-code line is `@<frontend host> #123456`. It must match the host in the
   address bar, so it changes whenever the frontend host changes.
6. **CSRF: send `X-Requested-With: torshx` on every POST, PATCH and DELETE** (any value
   works; simplest is to add it to the shared fetch wrapper). A write that carries the
   session cookie without it, or from an `Origin` not in `CORS_ORIGINS`, gets
   `403 CSRF_REJECTED`. **Send it on every write, sign-in calls included**: the check applies
   whenever the browser still holds a session cookie, even an expired one, so a returning
   player's `POST /auth/request` without the header would be rejected.
7. Staging and production use `SameSite=Lax`. `SameSite=None` exists only for a
   cross-site setup and is not used by any deployed environment.

## Errors

Every error has this shape:

```json
{"error": {"code": "CODE_MISTYPED", "message": "One character looks mistyped.", "request_id": "6f1c..."}}
```

Switch on `code` and show your own Persian copy. `message` is for developers and logs.
**Every** error uses this shape, including unknown paths, wrong methods, validation and 500s
(never FastAPI's `{"detail": ...}`). `request_id` equals the `X-Request-ID` response header
and the id in our logs: put it in bug reports.

`VALIDATION_FAILED` (422) also carries `fields`; submitted values are never echoed:

```json
{"error": {"code": "VALIDATION_FAILED", "message": "request validation failed",
  "request_id": "6f1c...",
  "fields": [{"field": "body.identifier", "message": "Field required", "type": "missing"}]}}
```

| Code | HTTP | Meaning | What the app should do |
|---|---|---|---|
| `AUTH_REQUIRED` | 401 | No session, or it expired | Go to sign-in, then come back |
| `ADMIN_REQUIRED` | 403 | Signed in, but not an admin (admin routes only) | Show "not allowed" |
| `CURSOR_INVALID` | 400 | The `cursor` was not issued by the server | Restart from the first page |
| `TERMS_VERSION_INVALID` | 422 | `accept_terms_version` is not the current one | Reload `/config`, show the new terms |
| `VALIDATION_FAILED` | 422 | Body or query failed validation; `error.fields` lists the fields | Highlight the fields |
| `PHONE_INVALID` | 422 | Not an Iranian mobile number | Highlight the field |
| `PHONE_UNUSUAL` | 422 | Shape-valid, but the prefix is not a known Iranian mobile range; no SMS sent | Warn "double-check this number" |
| `OTP_COOLDOWN` | 429 | A code was sent less than a minute ago | Countdown from `Retry-After` |
| `OTP_DAILY_LIMIT` | 429 | Too many codes for this number today | "Try again tomorrow" |
| `PHONE_NOT_ALLOWED` | 403 | Test server: real SMS only to team numbers | Use a `0969` test number |
| `OTP_INVALID` | 401 | Wrong, expired or already used code, or too many attempts | "Wrong code"; offer resend |
| `TERMS_NOT_ACCEPTED` | 403 | The action needs accepted T&Cs | Show the T&C screen |
| `PROFILE_INCOMPLETE` | 403 | Nickname not set yet | Go to profile setup |
| `NICKNAME_INVALID` | 422 | Length or characters not allowed | Show the rule |
| `NICKNAME_TAKEN` | 409 | Someone else has it | Suggest another |
| `CATALOGUE_UNKNOWN` | 422 | Unknown avatar, favourite game, game, reward or venue id | Reload `/config` |
| `AVATAR_LOCKED` | 422 | `PATCH /me avatar_id` picked a locked avatar | Pick an unlocked one |
| `FLAVOR_NOT_UNLOCKED` | 409 | `POST /me/team` picked a flavor with under 5 lifetime codes (`error.details.required`/`have`) | Show "N more to unlock" |
| `TEAM_LOCKED` | 409 | `POST /me/team` too soon after the last join (`error.details.switch_allowed_at`) | Show the date it opens |
| `TEAM_SAME` | 422 | `POST /me/team` picked the player's current team | No-op; show the current team |
| `CHALLENGE_NOT_UNLOCKED` | 409 | `POST /challenges/{id}/claim` before the target is met (`error.details.required`/`have`) | Show remaining progress |
| `CHALLENGE_ALREADY_CLAIMED` | 409 | `POST /challenges/{id}/claim` claimed again in the same period | No-op; show it as claimed |
| `CODE_MALFORMED` | 400 | Not a product code at all | "This is not a TorshX code" |
| `CODE_MISTYPED` | 400 | Right shape, one character wrong | "Check the characters, especially 0/O and 1/I" |
| `CODE_INVALID` | 404 | Unknown code, or not released yet | "Code not valid" |
| `CODE_ALREADY_REDEEMED` | 409 | Another account already used it | "Already used"; link to support |
| `REDEMPTION_DAILY_LIMIT` | 429 | More than `limits.scans_per_day` redemptions today (default 20; see `/config`); the code the app actually emits — `SCAN_DAILY_LIMIT` never existed in code, only in an earlier draft of this doc | "Come back tomorrow" (`Retry-After` = seconds to Tehran midnight) |
| `CODE_ATTEMPTS_LIMITED` | 429 | Too many invalid codes recently | Countdown from `Retry-After` |
| `STREAK_ALREADY_CLAIMED` | 409 | Today's streak reward already taken | Show tomorrow's reward |
| `SPIN_ALREADY_USED` | 409 | Today's spin already used | Show the next spin time |
| `MINI_GAME_RUN_ALREADY_FINISHED` | 409 | `POST /mini-games/runs/{run_id}/finish` on a run that was already finished | Start a new run |
| `MINI_GAME_RUN_EXPIRED` | 409 | The run timed out, or a newer start replaced it | Start a new run; use the newest `run_id` only |
| `MINI_GAME_ROUND_COUNT_MISMATCH` | 422 | `reactions_ms` length differs from the issued round count | A bug in the client |
| `CHALLENGE_NOT_ACTIVE` | 409 | Challenge ended or not started | Refresh the list |
| `SUBMISSION_EXISTS` | 409 | Already submitted this period, or the link was used before | Show its status |
| `URL_INVALID` | 422 | Not an accepted Instagram/X link, or not the player's own account (`error.reason`) | Show the accepted format |
| `SOCIAL_NOT_CONNECTED` | 409 | A submission needs a connected account on that platform | Open connected accounts |
| `SOCIAL_HANDLE_TAKEN` | 409 | The handle is linked to another player | Link to support |
| `SOCIAL_VERIFY_FAILED` | 422 | Verification code not found on the profile | Show the steps again |
| `REFERRAL_CODE_UNKNOWN` | 422 | `PATCH /me referrer_code`: no player has that code | Highlight the field |
| `REFERRAL_SELF` | 422 | `PATCH /me referrer_code`: the player's own code | Highlight the field |
| `REFERRAL_CODE_TOO_LATE` | 422 | `PATCH /me referrer_code` after the player already redeemed a code | Hide the field |
| `REFERRAL_ALREADY_BOUND` | 409 | A referrer is already bound to this player | Show the bound state |
| `INSUFFICIENT_COINS` | 409 | Balance too low | Show the missing amount |
| `OUT_OF_STOCK` | 409 | Reward has no stock | Offer "notify me" |
| `TICKET_LIMIT` | 409 | Weekly ticket cap reached | Show the cap |
| `DRAW_CLOSED` | 409 | This week's draw is closed | Show the next draw |
| `EVENT_FULL` | 409 | No places left | Show "full" |
| `EVENT_CLOSED` | 409 | Registration closed | Refresh |
| `RATE_LIMITED` | 429 | Generic limit (proxy or API) | Countdown from `Retry-After` |
| `NOT_FOUND` | 404 | No such route | A bug in the client; check the path |
| `METHOD_NOT_ALLOWED` | 405 | Wrong HTTP method for the route (`Allow` header lists the right ones) | A bug in the client |
| `CSRF_REJECTED` | 403 | A cookie-authenticated write without `X-Requested-With`, or from an origin not allowed | Add the header in the fetch wrapper; a bug, never shown to players |
| `SERVICE_UNAVAILABLE` | 503 | A dependency is down or misconfigured | Generic error; we get alerted |
| `INTERNAL_ERROR` | 500 | Bug | Generic error; we get alerted |

## Screen map

| Demo route / panel | Endpoints |
|---|---|
| `/` landing, `/enter` sign-in (steps 1–2) | `POST /auth/request`, `POST /auth/verify` |
| Profile setup (step 3: avatar, nickname, favourite games, invite code) | `GET /config`, `GET /avatars`, `PATCH /me` (the invite code is `referrer_code`) |
| `/home` header, next reward, today's game | `GET /me`, `GET /rewards/next` (planned); today's game is picked in the frontend |
| Home shortcut «گردونه» (spin panel) | `GET /spin`, `POST /spin` |
| Home shortcut «استریک» (streak panel) | `GET /me/streak`, `POST /me/streak/claim` |
| Home shortcut «PS5», `/rewards` → قرعه‌کشی PS5 | `GET /draws/current`, `POST /draws/current/tickets` |
| Home shortcut «تورنومنت», `/events` | `GET /events`, `POST`/`DELETE /events/{id}/registration` |
| Home shortcut «لیدربورد», `/leaderboard/:id` | `GET /leaderboards/mini-games/{mini_game_id}` (planned; plus `GET /leaderboards/weekly` if an overall board is shown) |
| Home shortcut «فروشگاه», `/rewards` → فروشگاه | `GET /rewards`, `POST /rewards/{id}/orders`, `PUT`/`DELETE /rewards/{id}/notify` |
| `/rewards` → جایزه‌های من | `GET /me/orders` |
| Bell (activity panel) | `GET /me/activity`, `POST /me/activity/seen` |
| `/games`, `/games/:id`, `/play` | `POST /mini-games/{mini_game_id}/runs`, `POST /mini-games/runs/{run_id}/finish` |
| `/scan` (camera, manual entry, stats) | `POST /redemptions`, `GET /me/scans` |
| `/challenges`, `/challenges/:id` | `GET /challenges`, `POST /challenges/{id}/claim`, `POST /challenges/{id}/submissions` |
| `/profile` | `GET`/`PATCH /me`, `GET /me/wallet`, `POST /auth/logout` |
| Profile → حساب‌های متصل | `/me/social-accounts...` |
| Profile → دعوت دوستان | `GET /me` (`referral_code`), `GET /me/referrals` |
| Profile → تنظیمات, پشتیبانی | Static in the frontend; support contacts come from `GET /config.support` |
| `/b/<code>` product QR | `POST /redemptions` (after sign-in) |
| `/q/:venue` venue QR, `/go` campaign link | `POST /me/arrivals` |
| Home "stories" strip | Static assets in the frontend for the MVP (no endpoint) |

## Authentication

### `POST /api/v1/auth/request` (live)

```http
POST /api/v1/auth/request
{"identifier": "۰۹۱۲ ۳۴۵ ۶۷۸۹"}
```

Accepts Persian or Latin digits, spaces, `+98`, `0098`, `98` or a leading `0`. The
field name is `identifier`, not `phone` — the API has no `phone` alias, so a client
sending `{"phone": ...}` gets `422 VALIDATION_FAILED` (missing `identifier`).

```http
202 Accepted
{"resend_after_seconds": 60, "expires_in_seconds": 150, "code_length": 6}
```

The response is the same for new and known numbers. Errors: `PHONE_INVALID`,
`PHONE_UNUSUAL` (shape-valid but an unrecognized prefix; no SMS sent),
`OTP_COOLDOWN`, `OTP_DAILY_LIMIT`, `PHONE_NOT_ALLOWED` (staging only: a real number that is
not on the team allow-list).

Test numbers (demo and staging, never in production): any number starting `0969`
(`0969 xxx xxxx`).
No SMS is sent; the response carries the code, then verify as usual. Cooldown and
daily limit still apply per number.

```http
202 Accepted
{"resend_after_seconds": 60, "expires_in_seconds": 150, "code_length": 6, "test_code": "483920"}
```

### `POST /api/v1/auth/verify` (live)

```http
POST /api/v1/auth/verify
{"identifier": "09123456789", "code": "483920"}
```

```http
200 OK
Set-Cookie: __Host-lp_session=...; HttpOnly; Secure; SameSite=Lax; Path=/
<the Me object, see GET /me>
```

The cookie name is `SESSION_COOKIE_NAME`: `__Host-lp_session` on staging and production
(the `__Host-` prefix stops a sibling subdomain such as www or staging from setting it),
`lottery_passport_session` in local development (a `__Host-` cookie needs Secure, which
plain-http development lacks; the settings refuse that combination). The frontend never
reads it (HttpOnly).

The first successful verify creates the account. If `profile_complete` is false, show
profile setup before anything else. Errors: `OTP_INVALID`.

### `POST /api/v1/auth/logout` (live)

`204 No Content`; the cookie is cleared.

## Config and profile

### `GET /api/v1/config` (live, partial; no authentication)

Live today: `server_time`, `timezone`, `day_key`, `week_key`, `day_ends_at`, `week_ends_at`,
`terms_version`, `terms_required`, `terms_url`, `privacy_url` (null until the server's
`.env` points them at its [terms page](#terms-and-privacy-page)), `limits.scans_per_day`, `nickname` limits, `location_cities` (the four real
cities with lounges; not passport cities, which are flavors, `[{id, name}]` with Persian
names: `tehran`, `ahvaz`, `mashhad`, `isfahan`), `venues` (active lounges, ordered by name,
each `{"id", "name", "location_city", "address"}`; empty until the lounges are entered),
`flavors` (the 7 passport-city SKUs, `[{id, code}]`; `id` is the campaign slug for
`POST /me/team`, `code` is the 2-letter prefix on printed codes) and `features` (read side
of feature flags, F1; `{mini_games: true, leaderboard: false, venue_checkin: false,
diamonds: false}` today — a false flag means hide that whole section, no route enforces
it yet). The rest of the example below (`limits.coins_per_scan`/`spins_per_day`/etc.,
`avatars`, `favorite_games`, social and support fields) is **planned**, not live: `avatars`
is actually its own endpoint (`GET /avatars`, see below), and `favorite_games` does not
exist in code at all yet (G0a).

```json
{
  "server_time": "2026-10-10T08:30:00Z",
  "timezone": "Asia/Tehran",
  "day_key": "D:2026-10-10",
  "week_key": "W:2026-10-10",
  "day_ends_at": "2026-10-10T20:30:00Z",
  "week_ends_at": "2026-10-16T20:30:00Z",
  "terms_version": "2026-10-01",
  "terms_required": true,
  "terms_url": null,
  "privacy_url": null,
  "limits": {
    "scans_per_day": 20,
    "coins_per_scan": 50,
    "spins_per_day": 1,
    "game_coins_per_day": 50,
    "tickets_per_week": 20,
    "ticket_cost": 500
  },
  "nickname": {"min_length": 3, "max_length": 16},
  "location_cities": [{"id": "tehran", "name": "تهران"}, {"id": "ahvaz", "name": "اهواز"}, {"id": "mashhad", "name": "مشهد"}, {"id": "isfahan", "name": "اصفهان"}],
  "venues": [{"id": "parsa", "name": "گیم‌سنتر پارسا", "location_city": "tehran", "address": "تهران، پونک، ..."}],
  "flavors": [{"id": "tokyo", "code": "TO"}, {"id": "paris", "code": "PR"}],
  "features": {"mini_games": true, "leaderboard": false, "venue_checkin": false, "diamonds": false},
  "social_platforms": ["instagram", "x"],
  "brand_accounts": {"instagram": "torshx", "x": "torshx"},
  "support": {"email": "support@torshx.com", "phone": null, "telegram": null}
}
```

Avatar artwork stays in the frontend (`avatars/<id>`); the server only validates ids.
The demo's favourite-games list is `cs, wz, fifa, dota, lol, val, wow, r6, df, bf`.

### `GET /api/v1/me` (live; target shape with B15)

```json
{
  "id": "4b0c...",
  "phone_masked": "0912***6789",
  "nickname": "NightOwl",
  "avatar_id": "avatar-3",
  "favorite_games": ["val", "cs"],
  "terms_accepted": true,
  "profile_complete": true,
  "coin_balance": 2450,
  "unread_activity": 2,
  "created_at": "2026-10-07T10:00:00Z"
}
```

Live today: `{"id", "identifier", "display_name", "nickname", "home_venue_id",
"location_city", "avatar_id", "team", "last_scanned_flavor", "terms_accepted",
"profile_complete", "account_status", "verification_status", "role", "created_at",
"updated_at"}`. `location_city` is one of `/config`'s `location_cities` ids, or null.
`team` is the player's current flavor team (a campaign slug like `"tokyo"`), or null
before any team is joined; see [Teams](#teams). `last_scanned_flavor` is the flavor of
the most recently redeemed code, or null — the frontend uses it for the app's flavor
mood/theme. `favorite_games`, `coin_balance` and `unread_activity` come with their own
tasks.

### `PATCH /api/v1/me` (live for `display_name`, `nickname`, `accept_terms_version`, `home_venue_id`, `location_city`, `avatar_id`)

```json
{"nickname": "NightOwl", "avatar_id": "avatar-3", "favorite_games": ["val"], "accept_terms_version": "2026-10-01"}
```

All fields are optional; the response is the Me object.

- Only the fields sent change; `{}` changes nothing.
- `accept_terms_version` must equal `terms_version` from `/config`; the server stores the
  version and the time it was accepted.
- Nickname: 3–16 characters. Allowed: Latin letters, digits, `_` `.` `-`, Persian
  letters and ZWNJ. Unique ignoring case and Arabic/Persian letter variants. No bidi
  control characters.
- `favorite_games`: up to 5 ids from `/config`.
- `home_venue_id`: an active venue `id` from `/config` (the player's home lounge). If the venue
  is later removed, it reads back as `null`.
- `location_city`: one of `/config`'s `location_cities` ids (the player's real home city;
  never a flavor).
- `avatar_id`: an avatar `id` from `GET /avatars` that is not `locked`.
- `profile_complete` becomes true once the nickname is set and the terms are accepted.
  When `/config` says `terms_required: false` (test environments only), the nickname
  alone is enough and `terms_accepted` stays `false`.

Errors: `NICKNAME_INVALID` (422), `NICKNAME_TAKEN` (409), `TERMS_VERSION_INVALID` (422, reload
`/config`), `CATALOGUE_UNKNOWN` (422, unknown or inactive `home_venue_id`, `location_city` or
`avatar_id`; later also games), `AVATAR_LOCKED` (422, the avatar exists but is locked).

`POST /redemptions` requires `profile_complete` (live since 2026-10-13): without accepted terms
it answers `403 TERMS_NOT_ACCEPTED` (only when `terms_required` is true), without a nickname
`403 PROFILE_INCOMPLETE`. Send players
through profile setup before the camera opens.

The demo's setup has no T&C checkbox. Add one to step 3 (or replace the "points are demo"
checkbox in step 1) and send `accept_terms_version`.

## Terms and privacy page

### `GET /legal/{version}` (live, LG1'; no sign-in; HTML)

A right-to-left Persian HTML page with the terms of use and the privacy section, for
exactly one version. Link to it, do not rebuild it: `terms_url` is
`https://<host>/legal/<version>` and `privacy_url` is the same page with `#privacy`
(the privacy heading's anchor; the terms heading is `#terms`). Open it as a page or a
new tab: it cannot be shown in an iframe (`X-Frame-Options: DENY`).

- `version` is 1-20 letters, digits, `-` or `_`; anything else is `422`. An unknown
  version is `404 NOT_FOUND` (the JSON error envelope).
- The text is edited in the admin panel ("Terms & privacy"), not in the frontend or the
  repo. A version any player has accepted can no longer change; new text means a new
  version, and the server's `TERMS_VERSION` / `TERMS_URL` / `PRIVACY_URL` move to it.
- Accepting: the player ticks the box, the app sends `PATCH /me`
  `{"accept_terms_version": <config.terms_version>}`. Never send it on their behalf.

## Avatars

### `GET /api/v1/avatars` (live; no sign-in needed)

```json
[
  {"id": "avatar-1", "image_url": "/media/<sha256>.webp", "locked": false},
  {"id": "avatar-2", "image_url": "/media/<sha256>.webp", "locked": true}
]
```

Starts empty until Ashkan fills it in `/admin`. `image_url` must be served from the
app's own origin (a relative path, or the same host): the PWA's CSP is
`img-src 'self' data: blob:`, so any other host is blocked in the browser. Today an
admin types the URL; uploading the image in `/admin` (served at `/media/...`) is planned
(B45).
Includes locked avatars (show them as
"coming later"); `PATCH /me avatar_id` refuses a locked one with `422 AVATAR_LOCKED`.
There is no unlock mechanism yet (avatar unlocks by coins/achievements are AFTER LAUNCH);
every avatar an admin creates without `locked` is pickable immediately.

## Teams

A team is a TorshX **flavor** (one of the 7 passport cities: Paris, Berlin, Pattaya,
Mexico, Madrid, Tokyo, Moscow) — not a lounge or a squad. Membership is exclusive: a
player is on at most one team. Rule (decided 2026-10-15, replaces an earlier Fibonacci
design that never shipped):

- **Unlock**: redeeming 5 lifetime codes of a flavor unlocks that flavor's team (and its
  badge, planned with achievements). `POST /redemptions` reports this as `flavor_unlocked`.
- **Choose**: nothing joins automatically. The player picks a team among their unlocked
  flavors with `POST /me/team`.
- **Lock**: after each join or switch, changing team again is locked for a while (the
  server decides how long; see `switch_allowed_at`). After that, switching to any other
  unlocked flavor is allowed, including a flavor the player left before.

Behind `/config.features.teams` (planned, staged rollout): the frontend should hide team
UI while that flag is off.

### `GET /api/v1/me/team` (live)

```json
{
  "team": "tokyo",
  "joined_at": "2026-10-15T09:00:00Z",
  "switch_allowed_at": "2026-11-14T09:00:00Z",
  "flavors": [
    {"flavor": "paris", "codes": 2, "unlocked": false},
    {"flavor": "tokyo", "codes": 7, "unlocked": true},
    {"flavor": "moscow", "codes": 5, "unlocked": true}
  ]
}
```

`team`, `joined_at` and `switch_allowed_at` are null before the player's first join.
`flavors` lists all 7 campaign slugs with the player's lifetime code count and whether
that unlocks the team — use it for "2 more Moscow to unlock" copy.

### `POST /api/v1/me/team` (live)

```http
POST /api/v1/me/team
{"flavor": "tokyo"}
```

Joins (first team) or switches to `flavor`, which must already be unlocked (5+ lifetime
codes). Returns the same shape as `GET /me/team` on success (200).

Errors: `FLAVOR_NOT_UNLOCKED` (409, `error.details` has `required` and `have`),
`TEAM_LOCKED` (409, `error.details.switch_allowed_at`), `TEAM_SAME` (422, already this
team), `CATALOGUE_UNKNOWN` (422, unknown flavor slug).

## Scanning codes

### `POST /api/v1/redemptions` (live; MVP response below)

Requires `profile_complete`. No `Idempotency-Key` is needed: the code itself makes the call
idempotent per account.

```http
POST /api/v1/redemptions
{"code": "TO-HA1-NQC-C32"}
```

Send whatever the camera read or the user typed: the full QR URL or the bare code, with or
without dashes, in any letter case. The server normalizes it.

```http
200 OK
{
  "city": "tokyo",
  "entries_added": 1,
  "city_entries": 14,
  "coins_awarded": 50,
  "coin_balance": 2500,
  "replayed": false,
  "bonus_awarded": 0,
  "flavor_unlocked": null
}
```

`replayed: true` means this account already redeemed this code. Show the same success
screen without confetti; a replay does not count toward the limit. `bonus_awarded` is
non-zero only on the redemption that first triggers a reward rule (currently: the
welcome bonus on a user's very first successful redemption, ADR 0010); it is already
included in `coin_balance`, same as `coins_awarded` — the client never adds it
separately. `flavor_unlocked` is the campaign slug of this code's flavor exactly on the
redemption that brings it to 5 lifetime codes (see [Teams](#teams)); null otherwise,
including on a replay. Errors:
`CODE_MALFORMED`, `CODE_MISTYPED`, `CODE_INVALID`, `CODE_ALREADY_REDEEMED`,
`REDEMPTION_DAILY_LIMIT`, `CODE_ATTEMPTS_LIMITED`.

Code format (decided 2026-10-10): a 2-letter city code plus 9 characters, written
`<CITY>-XXX-XXX-XXX`, for example `TO-HA1-NQC-C32`. The QR encodes
`https://torshx.com/b/TO-HA1-NQC-C32` (path form `/b/<code>`, decision 2026-10-14; the
fragment form `/r#<code>` is still accepted by the API). The code is in the path, so the
proxy does not log `/b/*` and the app sends `Referrer-Policy: no-referrer`. The format is registered and frozen in
the backend ([CODES.md](CODES.md)); validate with the generated `docs/frontend/codes.js`
instead of hard-coding the length.

### `GET /api/v1/me/scans` (planned)

Feeds the stats row on `/scan`.

```json
{"total_scans": 25, "coins_from_scans": 1250, "rank": 1284, "scans_today": 1, "scans_limit": 5}
```

`rank` is the all-time rank by number of scans; null before the first scan.

## Wallet and activity

### `GET /api/v1/me/wallet` (live)

```json
{
  "balance": 2450,
  "lifetime_earned": 3100,
  "recent": [{"id": 812, "amount": 50, "reason": "code_redemption", "created_at": "2026-10-10T08:30:00Z"}]
}
```

`reason` values the backend writes today: `code_redemption`, `first_code_bonus`,
`challenge_reward`, `achievement_reward`, `referral_first_code`, `referral_later_code`,
`admin_adjustment`. Reserved for planned features: `social_post_reward` (B18),
`tournament_prize` (B22), `store_purchase` (reward shop). Spin, streak and draw get their
own reasons when they ship; show an unknown reason with a generic label.

### `GET /api/v1/rewards/next` (planned)

The home "next reward" card: the cheapest in-stock reward the player cannot afford yet.

```json
{"reward_id": "mouse", "name": "ماوس گیمینگ", "cost": 3500, "missing": 1050}
```

Returns `204` if the player can already afford everything, or nothing is in stock.

### `GET /api/v1/me/activity?filter=all|coins|events&before=<id>` (planned)

The bell panel («اعلان‌ها و تاریخچه»). Newest first, 30 per page; pass `before` for the
next page.

```json
{
  "unread": 2,
  "items": [
    {"id": 991, "kind": "event", "text_key": "draw_closing", "params": {"days": 3}, "amount": null, "created_at": "..."},
    {"id": 990, "kind": "coins", "text_key": "code_redemption", "params": {}, "amount": 50, "created_at": "..."},
    {"id": 989, "kind": "event", "text_key": "submission_rejected", "params": {"challenge_id": "...", "reason": "private_account"}, "amount": null, "created_at": "..."}
  ]
}
```

Each `text_key` maps to a Persian template in the frontend, and `params` fill it in. Coin
items come from the ledger; event items come from submissions, draws, orders and new
records.

### `POST /api/v1/me/activity/seen` (planned)

`204`. Marks everything up to now as read.

## Daily streak

### `GET /api/v1/me/streak` (planned)

```json
{
  "day": 3, "length": 7,
  "claimed_today": false,
  "today_reward": 40, "day7_reward": 70,
  "freezes_left_this_week": 1,
  "resets_at": "2026-10-11T20:30:00Z"
}
```

Rules, enforced server-side:

- Claiming on consecutive Tehran days advances `day` from 1 to 7; after day 7 the cycle
  restarts at 1.
- The reward is `day × 10`, with the day-7 bonus.
- Missing one day automatically uses the weekly free freeze.
- Missing a day with no freeze left resets to day 1.

### `POST /api/v1/me/streak/claim` (planned; `Idempotency-Key`)

`200 {"day": 4, "coins_awarded": 40, "coin_balance": 2490, "replayed": false}`.
Errors: `STREAK_ALREADY_CLAIMED`. Ledger key `streak:<user>:<day_key>`.

## Daily wheel

### `GET /api/v1/spin` (planned)

```json
{
  "segments": [
    {"index": 0, "kind": "coins", "amount": 10},
    {"index": 3, "kind": "ticket", "amount": 1}
  ],
  "available": true,
  "next_spin_at": null,
  "odds_url": "https://torshx.com/rules#spin"
}
```

`segments` lists the eight wedges in display order. The odds are published in the campaign
rules (as the demo says) and are not sent to the client.

### `POST /api/v1/spin` (planned; `Idempotency-Key`)

```json
{"index": 5, "kind": "coins", "amount": 100, "coin_balance": 2550, "tickets": 2, "replayed": false}
```

- The server picks the result with a cryptographic RNG and stores it before answering. The
  client only animates the wheel to `index`.
- One spin per Tehran day; ledger key `spin:<user>:<day_key>`.
- A ticket result adds a ticket to the current PS5 draw, within `tickets_per_week`. If the
  cap is already reached, the wedge pays its coin fallback and the response says
  `kind: "coins"`.

Errors: `SPIN_ALREADY_USED`.

## Mini-games

Our own in-app reaction mini-game (G1), not the physical arcade machines at the
OxinGame lounges — see `docs/GLOSSARY.md` "Mini-game". `tap_reflex` is live; `aim_rush`
(Aim Rush) is next, through the same two endpoints with `mini_game_id = aim_rush`
(launch-week task G2; its run and finish payload get their own section when it ships).
The sheet's other mocks (`cps`, `seq`) have no agreed mechanic from Mehdi and are NOT
built — don't assume them. Rewards pay only
through [Challenges and submissions](#challenges-and-submissions) (`first_game`,
`tap_reflex_fast` once those challenge kinds ship); this section's endpoints never
move coins directly. Leaderboards, `game_of_the_day` and a direct per-game coin cap
from the earlier draft below are also not built — see "Not shipped yet".

### `POST /api/v1/mini-games/{mini_game_id}/runs` (live, G1)

```http
POST /api/v1/mini-games/tap_reflex/runs
```

```http
200 OK
{
  "run_id": "5e1c2b2a-....",
  "mini_game_id": "tap_reflex",
  "round_delays_ms": [1340, 2210, 905, 2980, 1677],
  "expires_at": "2026-10-15T09:02:00Z"
}
```

The server chooses `round_delays_ms` (one per round) so the client cannot know in
advance when each round's "react now" signal comes. At most one OPEN run per player
(enforced by a database constraint, not just an application check). Starting a run while
one is open closes the old one as expired and returns the new one, so a reload never
locks the player out; the old `run_id` then answers `409 MINI_GAME_RUN_EXPIRED`. A run
expires 2 minutes after issue.

### `POST /api/v1/mini-games/runs/{run_id}/finish` (live, G1)

```json
{"reactions_ms": [310, 295, 340, 288, 322]}
```

```http
200 OK
{
  "run_id": "5e1c2b2a-....",
  "accepted": true,
  "average_reaction_ms": 311.0,
  "reason": null
}
```

Always `200` for a structurally valid attempt — a rejected (implausible) run is a
normal outcome, not an error: `accepted: false` with `reason` set to one of
`reaction_too_fast`, `identical_reactions`, `wall_time_too_short`. A browser game
cannot be made cheat-proof; this (plus small, capped rewards paid only through
challenges) makes cheating not worth it rather than impossible. Errors: `NOT_FOUND`
(404 — unknown run id, or a run that is not yours; the response does not
distinguish the two, so a stolen/guessed id reveals nothing), `MINI_GAME_RUN_ALREADY_FINISHED`
(409), `MINI_GAME_RUN_EXPIRED` (409), `MINI_GAME_ROUND_COUNT_MISMATCH` (422 —
`reactions_ms` length must match the issued round count).

**Not shipped yet** (earlier frontend-mock draft; do not build a client assuming
these): `GET /api/v1/games` summary/leaderboard view, `game_of_the_day`,
`aim`/`cps`/`seq` mini-games, a direct per-mini-game daily coin cap
(`game_coins_per_day`), `my_rank`/`top_score`. Game leaderboards may come later but
will display bests only — never prizes from a client-reported score.

### `GET /api/v1/leaderboards/mini-games/{mini_game_id}?period=today|week|all` (planned)

```json
{
  "mini_game_id": "tap_reflex", "period": "week", "resets_at": "2026-10-16T20:30:00Z",
  "updated_at": "2026-10-10T08:30:00Z",
  "entries": [{"rank": 1, "nickname": "NEXUS", "avatar_id": "avatar-2", "score": 182, "is_me": false}],
  "me": {"rank": 6, "score": 214}
}
```

Each player's best score in the period. Ties go to whoever set the score first. Top 50.
Cached up to 60 seconds, so show `updated_at`. Not built yet — see "Not shipped yet"
under [Mini-games](#mini-games).

### `GET /api/v1/leaderboards/mini-games/{mini_game_id}/winners?week=previous` (planned)

Last week's top 3 (the «برندگان هفته قبل» tab): `{"week_key": "...", "entries": [...]}`.

## Weekly coins leaderboard

### `GET /api/v1/leaderboards/weekly?venue=all|<venue_id>` (planned, B21)

```json
{
  "week_key": "W:2026-10-10",
  "venue": null,
  "updated_at": "2026-10-10T08:30:00Z",
  "entries": [{"rank": 1, "nickname": "Shadow_K", "avatar_id": "avatar-4", "coins": 420, "is_me": false}],
  "me": {"rank": 57, "coins": 95}
}
```

- Ranked by coins **earned** this week. Spending does not lower your rank, and admin
  adjustments do not count.
- Ties: whoever reached the score first ranks higher.
- Top 50. `me` is null if you earned nothing this week.
- Cached up to 60 seconds.
- `venue` filters to players whose arrival or event registration was at that venue. The
  demo does not show a venue filter yet.

## Referrals

Invite a friend, earn coins when they finish their own mission (RF1; numbers from
Mehdi's rewards sheet, tab «ریفرال»). One inviter per user, bound once, only while the
invitee has redeemed 0 codes — binding later would backdate a referral onto redemptions
nobody actually referred.

- **First code**: once the invitee has a redeemed code AND a finished profile AND a
  chosen team AND at least one accepted mini-game run, the inviter earns 15 coins. Until
  then the payout is PENDING — nothing pays, not even for later codes.
- **Later codes**: once the mission is complete, every one of the invitee's codes
  redeemed within 180 days of their first redeemed code earns the inviter 5 coins each.
- Settling runs on the invitee's own `GET /me` (every one of redeem/profile-update/
  team-join/mini-game-finish is normally followed by a `/me` refresh in the client), not
  inside those write endpoints' own transaction — a deliberate simplification from the
  original same-transaction design; it costs at most one `/me` read's delay, never a
  missed or doubled payout (idempotency keys).

### `PATCH /api/v1/me` `referrer_code` (live, RF1)

```json
{"referrer_code": "K7M2QXJ9"}
```

One-time only. Errors: `REFERRAL_CODE_UNKNOWN` (422 — no user has that code),
`REFERRAL_SELF` (422 — your own code), `REFERRAL_CODE_TOO_LATE` (422 — you have already
redeemed a code), `REFERRAL_ALREADY_BOUND` (409 — a referrer is already bound).

### `GET /api/v1/me` `referral_code` (live, RF1)

Your own invite code (8 Crockford Base32 characters, same alphabet as printed product
codes); generated and stored the first time it is read.

### `GET /api/v1/me/referrals` (live, RF1)

```json
{
  "referral_code": "K7M2QXJ9",
  "invited_count": 3,
  "qualified_count": 1,
  "pending_count": 2,
  "coins_earned": 20
}
```

## Challenges and submissions

Automatic challenges (C1, B17) are live now; social-post submissions and manual
challenges (B18, "SHOULD" in the plan) are not built yet — see the end of this section.

### `GET /api/v1/challenges` (live, B17; MVP subset)

```json
[
  {
    "id": "choose_team",
    "kind": "team_choice",
    "period": "once",
    "target": 1,
    "have": 0,
    "reward_coins": 30,
    "completed": false,
    "claimed": false,
    "streak": null
  },
  {
    "id": "discover_3_flavors",
    "kind": "distinct_flavors",
    "period": "month",
    "target": 3,
    "have": 1,
    "reward_coins": 100,
    "completed": false,
    "claimed": false,
    "streak": null
  },
  {
    "id": "daily_checkin",
    "kind": "daily_checkin",
    "period": "day",
    "target": 1,
    "have": 1,
    "reward_coins": 10,
    "completed": true,
    "claimed": false,
    "streak": 6
  }
]
```

Every row is a challenge an admin created in `/admin` (the table starts empty, same as
avatars/reward rules — nothing shows here until Ashkan or Mehdi adds one). `kind` is the
closed set this backend knows how to check progress for:

- `team_choice`: `have` is 1 once the player has ever joined a flavor team (see
  [Teams](#teams)), 0 before. Natural `target` is 1; `period` is `once`.
- `distinct_flavors`: `have` is the number of distinct flavors the player has redeemed a
  code of within the current period (`day`/`week`/`month`, Tehran calendar).
- `daily_checkin`: `have`/`target` are always `1`/`1` (completed the moment the player is
  signed in) — claiming it IS the "player used the app today" signal, recorded in
  `challenge_claims` like any other claim. `streak` is this player's current run of
  consecutive Tehran calendar days with a claim (counting from today, or from yesterday
  if today has not been claimed yet, so it does not look broken before the player has
  had a chance). Supersedes the sheet's "5-day login"/"5-day activity" items — see
  `docs/vault/Decisions.md` 2026-10-15.

`completed = have >= target`. `claimed` is whether this player already claimed this
challenge for its current period — a completed-and-claimed row stays visible (so the UI
can show "done ✓") but a further claim is refused. `streak` is present (an integer) only
for `daily_checkin` rows; `null` for every other kind.

**Not in this response, by design:** `title`/`description` (Persian copy for a challenge
is the frontend's job, keyed by `id` — same principle as error codes); a `type` query
filter (filter client-side on `kind`/`period` if needed); `action.route`. These were in
an earlier draft of this contract written against the frontend demo mock and are
superseded by the shape above for every LIVE challenge.

**Not shipped yet** (do not build a client assuming these): `scan_count`/`game_score`/
`social_post`/`manual` kinds. Planned next (B43), fed by the live
[Mini-games](#mini-games) runs: `first_mini_game` (period `once`: the player has at least
one accepted mini-game run) and `tap_reflex_fast` (period `day`: an accepted `tap_reflex`
run that Tehran day with an average reaction under a server-side threshold, default
250 ms). Until a kind ships, the client must not offer a claim for it.

### `POST /api/v1/challenges/{id}/claim` (live, B17; MVP subset)

```http
POST /api/v1/challenges/choose_team/claim
```

```http
200 OK
{
  "id": "choose_team",
  "coins_awarded": 30,
  "coin_balance": 530,
  "streak": null,
  "achievements_unlocked": []
}
```

Claiming a `daily_checkin` challenge may also auto-unlock a streak achievement in the
same call — see [Achievements](#achievements):

```http
POST /api/v1/challenges/daily_checkin/claim
```

```http
200 OK
{
  "id": "daily_checkin",
  "coins_awarded": 10,
  "coin_balance": 560,
  "streak": 7,
  "achievements_unlocked": [{"id": "streak_7", "reward_coins": 50}]
}
```

Idempotent per period: a UNIQUE constraint on `challenge_claims (challenge_id, user_id,
period_key)` is the actual guard (not just the ledger), so two near-simultaneous clicks
cannot both pay. No `Idempotency-Key` header is needed — the challenge/period pair makes
the call idempotent per account, same principle as redemption codes.

`streak`/`achievements_unlocked` are present (non-null/non-empty when applicable) only on
a `daily_checkin` claim; every other kind always returns `streak: null,
"achievements_unlocked": []`.

Errors: `NOT_FOUND` (404, unknown or inactive challenge id — no request body to
validate, so this is a path error, unlike `CATALOGUE_UNKNOWN` elsewhere),
`CHALLENGE_NOT_UNLOCKED` (409, `error.details` has `required` and `have`),
`CHALLENGE_ALREADY_CLAIMED` (409, already claimed this period).

### `POST /api/v1/challenges/{id}/submissions` (planned, B18)

```json
{"url": "https://www.instagram.com/stories/nightowl/3456789012345678901/"}
```

`201 {"id": "f00d...", "status": "pending"}`.

Accepted links (query strings and fragments are stripped server-side):

| Platform | Patterns |
|---|---|
| instagram | `https://(www.)instagram.com/p/<id>/`, `/reel/<id>/`, `/stories/<username>/<id>/` |
| x | `https://(x|twitter).com/<username>/status/<id>` |

- The player must have a connected account on that platform; otherwise the error is
  `SOCIAL_NOT_CONNECTED`.
- When the link contains a username (stories, X), it must match the connected account;
  otherwise `URL_INVALID` with reason `not_owner`.
- A link can be used only once across all players.
- Review happens within 24 hours. Stories expire after 24 hours, so story submissions go to
  the top of the review queue, and a story that has expired before review is rejected with
  `expired`.

Errors: `URL_INVALID`, `SUBMISSION_EXISTS`, `CHALLENGE_NOT_ACTIVE`,
`SOCIAL_NOT_CONNECTED`, `TERMS_NOT_ACCEPTED`.

### `GET /api/v1/me/submissions` (planned, B18)

`[{"id", "challenge_id", "platform", "url", "status", "reason", "created_at", "reviewed_at"}]`, newest first.

## Achievements

Auto-unlocked, auto-paid milestones (AC1 MVP slice). There is no claim endpoint and
never will be for this fact — unlocking happens automatically inside the `daily_checkin`
claim that crosses the threshold, and pays in the SAME transaction. This is deliberate:
"easily claimable" means no claim step at all, not a second tap.

### `GET /api/v1/me/achievements` (live, AC1 MVP slice)

```json
[
  {"id": "streak_7", "threshold": 7, "reward_coins": 50, "unlocked_at": "2026-10-15T08:30:00Z"},
  {"id": "streak_3", "threshold": 3, "reward_coins": 20, "unlocked_at": "2026-10-11T08:15:00Z"}
]
```

This player's unlocked achievements, newest first. An achievement row (admin-created in
`/admin`, starts empty) says what `fact` must cross what `threshold` to unlock, and how
many coins it pays the first (and only) time it does — see `app/domain/achievements.py`.

**One-time per player, ever, not per streak-run.** Breaking a streak and rebuilding it
does not re-pay an already-unlocked milestone: `user_achievements` has
`UNIQUE (achievement_id, user_id)`. Without this, a 3-day/7-day pair of achievements
would be a stronger economy than committing to an actual 30-day streak (break-and-rebuild
every week beats one long run) — see `docs/vault/Decisions.md` 2026-10-15.

**Not in this response yet:** badge artwork/name (Persian copy and images need Ashkan's
assets and Mehdi's approved 8-12 item list, AC1's own spec pass — not done); "locked"
achievements with progress (only unlocked ones list today; a catalogue read,
`GET /api/v1/achievements` with every active row, `unlocked_at` or null, and progress, is
planned as B44). `fact` is a closed set, today
just `checkin_streak` (fed by `daily_checkin` claims); a game high score or a lounge-visit
count would be a new fact, not a parameter on this one.

## Connected social accounts

Profile → «حساب‌های متصل». In the MVP an account is verified by putting a code in the
profile bio. This works for any public account and needs no Meta or X developer app.
OAuth can replace it later without changing these shapes.

### `GET /api/v1/me/social-accounts` (planned)

```json
[
  {"platform": "instagram", "handle": "nightowl", "status": "verified", "verified_at": "..."},
  {"platform": "x", "handle": null, "status": "not_connected", "verified_at": null}
]
```

`status`: `not_connected`, `pending`, `verified`.

### `POST /api/v1/me/social-accounts/{platform}` (planned)

Starts linking: `{"handle": "@NightOwl"}` (with or without `@`, case-insensitive).

```json
{"platform": "instagram", "handle": "nightowl", "status": "pending", "verification_code": "TX-4K9Q", "expires_at": "..."}
```

The app tells the player to put `TX-4K9Q` in their bio, then tap "check".
Errors: `VALIDATION_FAILED`, `SOCIAL_HANDLE_TAKEN`.

### `POST /api/v1/me/social-accounts/{platform}/verify` (planned)

Returns `200 {"status": "verified"}`, or `202 {"status": "pending"}` while the check is
queued. The check is automatic when the profile is reachable; otherwise a reviewer confirms
it in admin. After verification the player may remove the code from their bio.
Errors: `SOCIAL_VERIFY_FAILED`.

### `DELETE /api/v1/me/social-accounts/{platform}` (planned)

`204`. Pending submissions from that account stay as they are.

## Reward shop

### `GET /api/v1/rewards` (planned)

```json
[
  {"id": "pad", "name": "ماوس‌پد گیمینگ", "name_en": "MOUSEPAD XL", "cost": 1500, "stock": "in", "notify_me": false, "details": [["ابعاد", "900×400 mm"]]},
  {"id": "ram", "name": "رم ۱۶ گیگ", "name_en": "RAM 16GB DDR5", "cost": 9000, "stock": "out", "notify_me": true, "details": []}
]
```

- `stock`: `in`, `low`, `out`. Exact counts are not exposed.
- Images stay in the frontend (`rewards/reward-<id>`).
- Demo catalogue: `pad 1500, mouse 3500, phone 5000, kb 6000, head 7500, ram 9000,
  ssd 12000, cpu 20000`.

### `POST /api/v1/rewards/{id}/orders` (planned; `Idempotency-Key`; requires `terms_accepted`)

`201 {"order_id": "...", "status": "pending", "coins_spent": 1500, "coin_balance": 950, "replayed": false}`.

The stock decrement and the ledger debit happen in one transaction. Staff handle
fulfilment (pickup at a game center, or delivery) in admin. Errors: `INSUFFICIENT_COINS`,
`OUT_OF_STOCK`, `TERMS_NOT_ACCEPTED`.

### `GET /api/v1/me/orders` (planned)

`[{"order_id", "reward_id", "status", "coins_spent", "created_at", "updated_at", "pickup": {"venue_id": "...", "pickup_code": "..."}}]`.

`status`: `pending`, `ready`, `delivered`, `cancelled`. Cancelled orders are refunded
through the ledger.

### `PUT /api/v1/rewards/{id}/notify` and `DELETE` (planned)

`204`. Back-in-stock alert; it shows up in activity when stock returns.

## Weekly PS5 draw

Tickets may not cost coins in production until legal signs off (ROADMAP CP5). Until then,
run the draw on test only, or have `GET` return `"status": "coming_soon"`.

### `GET /api/v1/draws/current` (planned)

```json
{
  "id": "w-2026-10-10", "prize": "PS5", "status": "open",
  "ticket_cost": 500, "tickets_per_week": 20,
  "my_tickets": 2, "closes_at": "2026-10-16T20:30:00Z",
  "rules_url": "https://torshx.com/rules#draw"
}
```

`status`: `coming_soon`, `open`, `closed`, `drawn`.

### `POST /api/v1/draws/current/tickets` (planned; `Idempotency-Key`)

`{"quantity": 1}` → `200 {"my_tickets": 3, "coins_spent": 500, "coin_balance": 1950, "replayed": false}`.
Errors: `INSUFFICIENT_COINS`, `TICKET_LIMIT`, `DRAW_CLOSED`, `TERMS_NOT_ACCEPTED`.

### `GET /api/v1/draws/{id}/result` (planned)

`{"id", "drawn_at", "winner_nickname", "seed_commitment", "seed", "ticket_count"}`, using the
committed-seed method in [DRAW.md](DRAW.md).

## Events and tournaments

### `GET /api/v1/events?status=upcoming|finished` (planned, B22)

```json
[
  {
    "id": "e1", "game": "EA FC 26", "title": "تورنومنت FC آخر هفته · گیم‌سنتر پارسا",
    "venue": {"id": "parsa", "name": "گیم‌سنتر پارسا"},
    "starts_at": "2026-10-16T12:30:00Z", "schedule_text": null,
    "format": "تک‌به‌تک · حذفی", "prize_text": "هدست + ۲,۰۰۰ امتیاز",
    "capacity": 32, "registered_count": 27, "i_am_registered": false,
    "status": "open",
    "results": []
  }
]
```

- `capacity: 0` means open entry, with no registration limit (the demo's daily in-venue
  Tap challenge). Such events have `starts_at: null` and a `schedule_text`.
- `status`: `open`, `full`, `closed`, `finished`.
- `results` (finished events only): `[{"place": 1, "nickname": "...", "coins": 300}]`.

### `POST /api/v1/events/{id}/registration` and `DELETE` (planned)

`201 {"registered": true, "registered_count": 28}` / `204`. Errors: `EVENT_FULL`,
`EVENT_CLOSED`, `PROFILE_INCOMPLETE`. Staff enter results and coin prizes in admin (ledger
key `tournament:<id>:<place>`).

## Arrivals from QR links

### `POST /api/v1/me/arrivals` (planned)

Called once, after sign-in, when the player arrived through `/q/:venue` (a QR on a game
center fridge or poster) or `/go` (a link printed with the product).

```json
{"source": "venue", "venue": "parsa"}
```

`204`. Records attribution for marketing reports (which venue brings players). It pays
nothing. Unknown venue ids are stored as `unknown` without an error.

## Admin

Staff-only routes under `/api/v1/admin`. They need the session cookie of a user with
`role: "admin"` (`401 AUTH_REQUIRED` when signed out, `403 ADMIN_REQUIRED` for a player).
Grant the role with `uv run python -m scripts.admins promote <identifier>`; there is no
API route for it.

### `GET /api/v1/admin/users?limit=50&cursor=<opaque>` (live)

Users, newest first. `limit` is 1–100 (default 50). Pass the previous response's
`next_cursor` as `cursor`; the cursor is opaque, so do not build or parse it.

```json
{"items": [{"id": "…", "identifier": "+989…", "display_name": null, "account_status": "active",
            "verification_status": "verified", "role": "player",
            "created_at": "2026-10-12T08:00:00Z", "updated_at": "2026-10-12T08:00:00Z"}],
 "next_cursor": "MjAyNi0xMC0xMlQwODowMDowMCswMDowMHw…"}
```

`next_cursor` is `null` on the last page. Paging is by `(created_at, id)`, so new signups
never shift or repeat rows. Errors: `CURSOR_INVALID`, `ADMIN_REQUIRED`, `AUTH_REQUIRED`.

## Health

`GET /health` → `{"status": "ok", "version": "0.1.0", "commit": "579f8f1", "environment": "demo"}`
(process is up; `commit` is the deployed git commit, so you can tell whether a backend change is
live yet; null when unknown). `GET /ready` → `{"status": "ready"}`, or `503 SERVICE_UNAVAILABLE`
if the database is unreachable, or if an ACTIVE code batch's pepper fingerprint does not match
the pepper this process is running with (a misconfigured `REDEMPTION_CODE_PEPPER` — wrong value,
stale secret, a different environment's pepper copied by mistake — would otherwise silently turn
every redemption into `CODE_INVALID`; see [CODES.md](CODES.md#5-batches)). Not under `/api/v1`;
used by the deploy agent, CI and uptime checks.

## OpenAPI

- `GET /openapi.json`, Swagger UI at `/docs` and ReDoc at `/redoc` are on in development
  and on staging. In production they answer 404.
- Every endpoint has a tag matching a section of this file, a summary, typed request and
  response models with examples, and the list of error codes it can return.
- `operationId`s are stable (for example `redeem_code`, `get_spin`), so the frontend can
  generate types: `npx openapi-typescript https://<api>/openapi.json -o src/api/schema.ts`.
- A snapshot is committed as `docs/openapi.json`. CI fails if the code's schema drifts from
  the snapshot without the snapshot being updated.

## Frontend recipes

**Product QR landing (`/b/<code>`)**

1. On the `/b/:code` route, read the code from the path. If signed If signed
   out, keep it in `sessionStorage` and go to sign-in.
2. After sign-in (and profile setup if needed), `POST /api/v1/redemptions` with the code.
3. Call `history.replaceState(null, "", "/scan")` so the code does not stay in the URL bar
   or history.
4. Remove the code from `sessionStorage` after any final answer (success or error).

The host lives in build config. `torshx.com` is decided for printing, but test builds run on
other hosts.

**Venue QR (`/q/:venue`) and `/go`**: keep `{source, venue}` in `sessionStorage`, call
`POST /me/arrivals` once after sign-in, then go to `/home`.

**OTP input that fills itself**

```html
<input name="otp" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]*" maxlength="6" dir="ltr">
```

```js
// Android Chrome: reads the SMS whose last line is "@<frontend host> #123456".
if ("OTPCredential" in window) {
  const abort = new AbortController();
  navigator.credentials
    .get({ otp: { transport: ["sms"] }, signal: abort.signal })
    .then((otp) => { input.value = otp.code; form.requestSubmit(); })
    .catch(() => {}); // user dismissed or unsupported: manual entry still works
  // call abort.abort() if the user leaves the screen
}
```

iPhone Safari does not run this API, but `autocomplete="one-time-code"` offers the code
above the keyboard from the same SMS.

**Typed codes**: use `dir="ltr" autocapitalize="characters" autocomplete="off"
spellcheck="false"`, and validate the check character locally with
`docs/frontend/codes.js` before sending ([CODES.md](CODES.md#validating-codes-in-the-browser)).

**Idempotency keys**: call `crypto.randomUUID()` when the user taps the button, and reuse
the same key for every retry of that tap. A new tap gets a new key.

## Demo to contract migration

Differences between the 2026-10-10 demo client and this contract:

| Demo | Contract |
|---|---|
| `POST /auth/request` and `/auth/verify` send `identifier` | Send `phone`. The backend accepts `identifier` as an alias until the demo is updated. |
| `PATCH /me {display_name}` | `PATCH /me {nickname, avatar_id, favorite_games, accept_terms_version}` |
| `POST /me/redeem {code}` | `POST /redemptions {code}` |
| `GET /me/passports` | Removed from the MVP (parked) |
| QR `https://torsh-x.com/b/<9 chars>` or `TX1:B:<9 chars>` | `https://torshx.com/b/<CITY>-XXX-XXX-XXX` (host `torshx.com`, no hyphen; `TX1:B:` dropped); host from build config |
| Avatar, favourites, streak, spin, games, shop, tickets, events, social and invite state live in the browser | All of it moves to the endpoints above; the browser keeps only UI state |
| No T&C acceptance | Add it to setup |

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

## Contents

- [Conventions](#conventions)
- [Hosts, CORS and cookies](#hosts-cors-and-cookies)
- [Errors](#errors)
- [Screen map](#screen-map)
- [Authentication](#authentication)
- [Config and profile](#config-and-profile)
- [Scanning codes](#scanning-codes)
- [Wallet and activity](#wallet-and-activity)
- [Daily streak](#daily-streak)
- [Daily wheel](#daily-wheel)
- [Mini-games and game leaderboards](#mini-games-and-game-leaderboards)
- [Weekly coins leaderboard](#weekly-coins-leaderboard)
- [Challenges and submissions](#challenges-and-submissions)
- [Connected social accounts](#connected-social-accounts)
- [Invites](#invites)
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
| Idempotency | Every `POST` that pays or spends coins takes an `Idempotency-Key` header: a UUID the client generates once per user action and reuses on retries. A repeat returns the first result with `"replayed": true`. Listed per endpoint. |
| Rate limits | `429` with a `Retry-After` header (seconds). Show a countdown; never retry before it. |
| Versioning | Additive changes stay in `/api/v1`; ignore unknown fields. Breaking changes go to `/api/v2`. |
| Server decides | The server decides spin results, streak rewards, which scores count, stock and prices. The client only shows what the server returns. |

## Hosts, CORS and cookies

Hostnames are **not final**. Current assumption:

| Environment | Frontend | API | Database |
|---|---|---|---|
| Test (now) | `torshx.com` or a preview URL | Render web service (`https://<service>.onrender.com`) | Supabase Postgres |
| Production | `torshx.com` (subject to change) | `api.torshx.com`, or same origin under `/api` (to decide) | to decide |

Rules that hold whatever the final names are:

1. **Prefer same-origin.** The frontend host proxies `/api/*` to the API (a rewrite rule
   on the static host, or nginx). Then there is no CORS, and cookies are first-party in
   every browser.
2. **If the API is on a different origin**, it must be the **same site**, i.e. a subdomain
   such as `api.torshx.com`. The API then allows CORS with credentials for an explicit list
   of origins (`CORS_ORIGINS`, never `*`), and the cookie is `SameSite=Lax` with no
   `Domain` attribute.
3. **Never rely on a cross-site cookie** (frontend on `torshx.com`, API on
   `onrender.com`). Safari and Firefox block third-party cookies, so sign-in would work in
   desktop Chrome and fail on iPhone. To test against Render, use rule 1 (proxy) or the
   Vite dev proxy (`server.proxy`).
4. Plain `http://<ip>:<port>` frontends (the current demo) are cross-site **and** insecure.
   Browsers allow the camera (QR scanning), WebOTP and `Secure` cookies only on HTTPS
   pages, and Safari blocks the cross-site cookie anyway. They are fine for looking at
   screens, but not for testing sign-in and scanning. For that, serve the build over HTTPS
   on a real hostname with `/api` proxied (rule 1).
5. The SMS one-time-code line is `@<frontend host> #123456`. It must match the host in the
   address bar, so it changes whenever the frontend host changes.

## Errors

Every error has this shape:

```json
{"error": {"code": "CODE_MISTYPED", "message": "One character looks mistyped."}}
```

Switch on `code` and show your own Persian copy. `message` is for developers and logs.

| Code | HTTP | Meaning | What the app should do |
|---|---|---|---|
| `AUTH_REQUIRED` | 401 | No session, or it expired | Go to sign-in, then come back |
| `ADMIN_REQUIRED` | 403 | Signed in, but not an admin (admin routes only) | Show "not allowed" |
| `CURSOR_INVALID` | 400 | The `cursor` was not issued by the server | Restart from the first page |
| `TERMS_VERSION_INVALID` | 422 | `accept_terms_version` is not the current one | Reload `/config`, show the new terms |
| `VALIDATION_FAILED` | 422 | Body or query failed validation; `error.fields` lists the fields | Highlight the fields |
| `PHONE_INVALID` | 422 | Not an Iranian mobile number | Highlight the field |
| `OTP_COOLDOWN` | 429 | A code was sent less than a minute ago | Countdown from `Retry-After` |
| `OTP_DAILY_LIMIT` | 429 | Too many codes for this number today | "Try again tomorrow" |
| `OTP_INVALID` | 401 | Wrong, expired or already used code, or too many attempts | "Wrong code"; offer resend |
| `TERMS_NOT_ACCEPTED` | 403 | The action needs accepted T&Cs | Show the T&C screen |
| `PROFILE_INCOMPLETE` | 403 | Nickname not set yet | Go to profile setup |
| `NICKNAME_INVALID` | 422 | Length or characters not allowed | Show the rule |
| `NICKNAME_TAKEN` | 409 | Someone else has it | Suggest another |
| `CATALOGUE_UNKNOWN` | 422 | Unknown avatar, favourite game, game, reward or venue id | Reload `/config` |
| `CODE_MALFORMED` | 400 | Not a product code at all | "This is not a TorshX code" |
| `CODE_MISTYPED` | 400 | Right shape, one character wrong | "Check the characters, especially 0/O and 1/I" |
| `CODE_INVALID` | 404 | Unknown code, or not released yet | "Code not valid" |
| `CODE_ALREADY_REDEEMED` | 409 | Another account already used it | "Already used"; link to support |
| `SCAN_DAILY_LIMIT` | 429 | 5 scans already today | "Come back tomorrow" (`Retry-After` = seconds to Tehran midnight) |
| `CODE_ATTEMPTS_LIMITED` | 429 | Too many invalid codes recently | Countdown from `Retry-After` |
| `STREAK_ALREADY_CLAIMED` | 409 | Today's streak reward already taken | Show tomorrow's reward |
| `SPIN_ALREADY_USED` | 409 | Today's spin already used | Show the next spin time |
| `GAME_SESSION_INVALID` | 409 | Session unknown, expired, already finished, or belongs to someone else | Start a new round |
| `SCORE_REJECTED` | 422 | Score beyond what a human can do, or timing does not match | "This round did not count" |
| `CHALLENGE_NOT_ACTIVE` | 409 | Challenge ended or not started | Refresh the list |
| `CHALLENGE_NOT_COMPLETED` | 409 | Target not reached yet | Show progress |
| `SUBMISSION_EXISTS` | 409 | Already submitted this period, or the link was used before | Show its status |
| `URL_INVALID` | 422 | Not an accepted Instagram/X link, or not the player's own account (`error.reason`) | Show the accepted format |
| `SOCIAL_NOT_CONNECTED` | 409 | A submission needs a connected account on that platform | Open connected accounts |
| `SOCIAL_HANDLE_TAKEN` | 409 | The handle is linked to another player | Link to support |
| `SOCIAL_VERIFY_FAILED` | 422 | Verification code not found on the profile | Show the steps again |
| `INVITE_INVALID` | 422 | Unknown code, own code, too late, or an invite was already used | Show the message |
| `INSUFFICIENT_COINS` | 409 | Balance too low | Show the missing amount |
| `OUT_OF_STOCK` | 409 | Reward has no stock | Offer "notify me" |
| `TICKET_LIMIT` | 409 | Weekly ticket cap reached | Show the cap |
| `DRAW_CLOSED` | 409 | This week's draw is closed | Show the next draw |
| `EVENT_FULL` | 409 | No places left | Show "full" |
| `EVENT_CLOSED` | 409 | Registration closed | Refresh |
| `RATE_LIMITED` | 429 | Generic limit (proxy or API) | Countdown from `Retry-After` |
| `SERVICE_UNAVAILABLE` | 503 | A dependency is down or misconfigured | Generic error; we get alerted |
| `INTERNAL_ERROR` | 500 | Bug | Generic error; we get alerted |

## Screen map

| Demo route / panel | Endpoints |
|---|---|
| `/` landing, `/enter` sign-in (steps 1–2) | `POST /auth/request`, `POST /auth/verify` |
| Profile setup (step 3: avatar, nickname, favourite games, invite code) | `GET /config`, `PATCH /me`, `POST /me/invite/redeem` |
| `/home` header, next reward, today's game | `GET /me`, `GET /rewards/next`, `GET /games` |
| Home shortcut «گردونه» (spin panel) | `GET /spin`, `POST /spin` |
| Home shortcut «استریک» (streak panel) | `GET /me/streak`, `POST /me/streak/claim` |
| Home shortcut «PS5», `/rewards` → قرعه‌کشی PS5 | `GET /draws/current`, `POST /draws/current/tickets` |
| Home shortcut «تورنومنت», `/events` | `GET /events`, `POST`/`DELETE /events/{id}/registration` |
| Home shortcut «لیدربورد», `/leaderboard/:id` | `GET /leaderboards/games/{id}` (plus `GET /leaderboards/weekly` if an overall board is shown) |
| Home shortcut «فروشگاه», `/rewards` → فروشگاه | `GET /rewards`, `POST /rewards/{id}/orders`, `PUT`/`DELETE /rewards/{id}/notify` |
| `/rewards` → جایزه‌های من | `GET /me/orders` |
| Bell (activity panel) | `GET /me/activity`, `POST /me/activity/seen` |
| `/games`, `/games/:id`, `/play` | `GET /games`, `POST /games/{id}/sessions`, `POST /game-sessions/{id}/finish` |
| `/scan` (camera, manual entry, stats) | `POST /redemptions`, `GET /me/scans` |
| `/challenges`, `/challenges/:id` | `GET /challenges`, `POST /challenges/{id}/claim`, `POST /challenges/{id}/submissions` |
| `/profile` | `GET`/`PATCH /me`, `GET /me/wallet`, `POST /auth/logout` |
| Profile → حساب‌های متصل | `/me/social-accounts...` |
| Profile → دعوت دوستان | `GET /me/invite` |
| Profile → تنظیمات, پشتیبانی | Static in the frontend; support contacts come from `GET /config.support` |
| `/r#<code>` product QR | `POST /redemptions` (after sign-in) |
| `/q/:venue` venue QR, `/go` campaign link | `POST /me/arrivals` |
| Home "stories" strip | Static assets in the frontend for the MVP (no endpoint) |

## Authentication

### `POST /api/v1/auth/request` (live with phone)

```http
POST /api/v1/auth/request
{"phone": "۰۹۱۲ ۳۴۵ ۶۷۸۹"}
```

Accepts Persian or Latin digits, spaces, `+98`, `0098`, `98` or a leading `0`. The
field is named `identifier` (kept for one release so an older client sending a
`phone`-shaped value here still works).

```http
202 Accepted
{"resend_after_seconds": 60, "expires_in_seconds": 150, "code_length": 6}
```

The response is the same for new and known numbers. Errors: `PHONE_INVALID`,
`OTP_COOLDOWN`, `OTP_DAILY_LIMIT`.

Test numbers (demo only, never in production): `0900 000 0001` to `0900 000 0040`.
No SMS is sent; the response carries the code, then verify as usual. Cooldown and
daily limit still apply per number.

```http
202 Accepted
{"resend_after_seconds": 60, "expires_in_seconds": 150, "code_length": 6, "test_code": "483920"}
```

### `POST /api/v1/auth/verify` (live)

```http
POST /api/v1/auth/verify
{"phone": "09123456789", "code": "483920"}
```

```http
200 OK
Set-Cookie: lottery_passport_session=...; HttpOnly; Secure; SameSite=Lax; Path=/
<the Me object, see GET /me>
```

The first successful verify creates the account. If `profile_complete` is false, show
profile setup before anything else. Errors: `OTP_INVALID`.

### `POST /api/v1/auth/logout` (live)

`204 No Content`; the cookie is cleared.

## Config and profile

### `GET /api/v1/config` (live, partial; no authentication)

Live today: `server_time`, `timezone`, `day_key`, `week_key`, `day_ends_at`, `week_ends_at`,
`terms_version`, `limits.scans_per_day`, `nickname` limits and `venues` (active lounges,
ordered by name, each `{"id", "name", "city"}`; empty until the lounges are entered). The rest
of the example below (other limits, `avatars`, `favorite_games`, social and support fields) is
planned with the catalogue work.

```json
{
  "server_time": "2026-10-10T08:30:00Z",
  "timezone": "Asia/Tehran",
  "day_key": "D:2026-10-10",
  "week_key": "W:2026-10-10",
  "day_ends_at": "2026-10-10T20:30:00Z",
  "week_ends_at": "2026-10-16T20:30:00Z",
  "terms_version": "2026-10-01",
  "limits": {
    "scans_per_day": 5,
    "coins_per_scan": 50,
    "spins_per_day": 1,
    "game_coins_per_day": 50,
    "tickets_per_week": 20,
    "ticket_cost": 500
  },
  "nickname": {"min_length": 3, "max_length": 16},
  "avatars": [{"id": "avatar-1"}, {"id": "avatar-2"}],
  "favorite_games": [{"id": "cs", "name": "CS", "short": "CS"}, {"id": "val", "name": "Valorant", "short": "VAL"}],
  "venues": [{"id": "parsa", "name": "گیم‌سنتر پارسا", "city": "tehran"}],
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

Live today: `{"id", "identifier", "display_name", "nickname", "home_venue_id", "terms_accepted", "profile_complete",
"account_status", "verification_status", "role", "created_at", "updated_at"}`. `avatar_id`,
`favorite_games`, `coin_balance` and `unread_activity` come with their own tasks.

### `PATCH /api/v1/me` (live for `display_name`, `nickname`, `accept_terms_version`, `home_venue_id`)

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
- `profile_complete` becomes true once the nickname is set and the terms are accepted.

Errors: `NICKNAME_INVALID` (422), `NICKNAME_TAKEN` (409), `TERMS_VERSION_INVALID` (422, reload
`/config`), `CATALOGUE_UNKNOWN` (422, unknown or inactive `home_venue_id`; later also avatars
and games).

`POST /redemptions` does not check `profile_complete` yet; the frontend should send players
through profile setup first, and the server-side check is a separate decision.

The demo's setup has no T&C checkbox. Add one to step 3 (or replace the "points are demo"
checkbox in step 1) and send `accept_terms_version`.

## Scanning codes

### `POST /api/v1/redemptions` (live; MVP response below)

Requires `profile_complete`. No `Idempotency-Key` is needed: the code itself makes the call
idempotent per account.

```http
POST /api/v1/redemptions
{"code": "TO-7KQ-2M9-XH4"}
```

Send whatever the camera read or the user typed: the full QR URL or the bare code, with or
without dashes, in any letter case. The server normalizes it.

```http
200 OK
{"coins_awarded": 50, "coin_balance": 2500, "scans_today": 2, "scans_limit": 5, "replayed": false}
```

`replayed: true` means this account already redeemed this code. Show the same success
screen without confetti; a replay does not count toward the limit. Errors:
`CODE_MALFORMED`, `CODE_MISTYPED`, `CODE_INVALID`, `CODE_ALREADY_REDEEMED`,
`SCAN_DAILY_LIMIT`, `CODE_ATTEMPTS_LIMITED`.

Code format (decided 2026-10-10): a 2-letter city code plus 9 characters, written
`<CITY>-XXX-XXX-XXX`, for example `TO-7KQ-2M9-XH4`. The QR encodes
`https://torshx.com/r#TO-7KQ-2M9-XH4`. The code sits in the URL **fragment**, so it never
reaches a server, a proxy log or a `Referer` header. The format is registered and frozen in
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

`reason` values: `code_redemption`, `challenge_reward`, `social_post_reward`,
`streak_reward`, `spin_reward`, `game_reward`, `invite_reward`, `welcome_bonus`,
`tournament_prize`, `store_purchase`, `draw_ticket`, `admin_adjustment`.

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

## Mini-games and game leaderboards

Games: `tap` (Tap Reflex, milliseconds, lower is better), `aim` (Aim Rush, points), `cps`
(CPS Blitz, clicks per second), `seq` (Sequence, level reached).

### `GET /api/v1/games` (planned)

```json
{
  "game_of_the_day": "tap",
  "coins_today": 20, "coins_today_limit": 50,
  "items": [
    {"id": "tap", "unit": "ms", "better": "lower", "my_best": 214, "my_rank": 6, "top_score": 182}
  ]
}
```

`my_best` and `my_rank` are null if the player has never played. Ranks are for the current
week.

### `POST /api/v1/games/{game_id}/sessions` (planned)

Starts a round. The server records the start time and returns a seed for anything random
(target positions, the colour sequence), so a finished round can be checked.

```json
{"session_id": "5e1c...", "seed": "b64...", "expires_at": "2026-10-10T08:35:00Z"}
```

### `POST /api/v1/game-sessions/{session_id}/finish` (planned)

```json
{"score": 214, "details": {"rounds_ms": [220, 205, 231, 198, 216]}}
```

`details` depends on the game:

- `tap`: per-round reaction times.
- `aim`: hit count and per-hit times.
- `cps`: click count.
- `seq`: level reached and input timings.

```json
{"accepted": true, "score": 214, "new_best": true, "my_rank": 6, "coins_awarded": 10, "coins_today": 30, "coins_today_limit": 50}
```

The server rejects impossible results with `SCORE_REJECTED`: for example an average
reaction below 100 ms, more than 20 clicks per second, or a round shorter than the game's
duration. Coins per day from games are capped (`game_coins_per_day`). Prizes never depend
on client-reported scores alone. Errors: `GAME_SESSION_INVALID`, `SCORE_REJECTED`.

### `GET /api/v1/leaderboards/games/{game_id}?period=today|week|all` (planned)

```json
{
  "game_id": "tap", "period": "week", "resets_at": "2026-10-16T20:30:00Z",
  "updated_at": "2026-10-10T08:30:00Z",
  "entries": [{"rank": 1, "nickname": "NEXUS", "avatar_id": "avatar-2", "score": 182, "is_me": false}],
  "me": {"rank": 6, "score": 214}
}
```

Each player's best score in the period. Ties go to whoever set the score first. Top 50.
Cached up to 60 seconds, so show `updated_at`.

### `GET /api/v1/leaderboards/games/{game_id}/winners?week=previous` (planned)

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

## Challenges and submissions

### `GET /api/v1/challenges?type=all|daily|weekly|social` (planned, B17)

```json
{
  "day_key": "D:2026-10-10", "week_key": "W:2026-10-10",
  "items": [
    {
      "id": "8d1f...", "type": "daily", "kind": "scan_count",
      "title": "یک QR محصول TorshX اسکن کن", "description": "...",
      "target": 1, "progress": 0, "reward_coins": 50,
      "status": "todo", "ends_at": "2026-10-10T20:30:00Z",
      "action": {"route": "/scan"}
    },
    {
      "id": "c2aa...", "type": "social", "kind": "social_post", "platform": "instagram",
      "title": "استوری با #TorshX و منشن @torshx", "description": "...",
      "target": 3, "progress": 1, "reward_coins": 80,
      "status": "rejected", "ends_at": "2026-10-16T20:30:00Z",
      "accepts": ["story", "post", "reel"],
      "submission": {"id": "f00d...", "status": "rejected", "url": "https://www.instagram.com/stories/...", "reason": "private_account"}
    }
  ]
}
```

- `type`: `daily`, `weekly`, `social`.
- `kind`: `scan_count`, `game_score` (`params.game_id`, `params.threshold`),
  `streak_days`, `social_post`, `manual`.
- `status`: `todo`, `in_progress`, `claimable`, `claimed`, `pending`, `approved`,
  `rejected`.
- Social challenges pay on approval; there is no claim step.
- Rejection `reason` values: `private_account`, `missing_hashtag`, `missing_mention`,
  `deleted`, `expired`, `duplicate`, `not_owner`, `other`.
- Titles and descriptions come from the admin panel, in Persian.

### `POST /api/v1/challenges/{id}/claim` (planned, B17; `Idempotency-Key`)

`200 {"coins_awarded": 50, "coin_balance": 2500, "replayed": false}`.
Errors: `CHALLENGE_NOT_COMPLETED`, `CHALLENGE_NOT_ACTIVE`.

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

## Invites

### `GET /api/v1/me/invite` (planned)

```json
{"code": "TX-NIGHTOWL", "invited_count": 2, "reward_per_invite": 100, "rewarded_count": 1}
```

The inviter is paid when the invited player makes their first successful scan, not at
sign-up. This stops farming with fresh phone numbers.

### `POST /api/v1/me/invite/redeem` (planned)

`{"code": "TX-PLAYER"}` → `200 {"accepted": true}`. Allowed once per account, only within
7 days of sign-up, and never with your own code. Errors: `INVITE_INVALID`.

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

`GET /health` → `{"status": "ok"}` (process is up). `GET /ready` → `{"status": "ready"}`, or
503 if the database is unreachable. Not under `/api/v1`; used by monitoring and the Render
health check.

## OpenAPI

- `GET /openapi.json`, Swagger UI at `/docs` and ReDoc at `/redoc` are on in development
  and test (Render). In production they are off, or behind admin auth.
- Every endpoint has a tag matching a section of this file, a summary, typed request and
  response models with examples, and the list of error codes it can return.
- `operationId`s are stable (for example `redeem_code`, `get_spin`), so the frontend can
  generate types: `npx openapi-typescript https://<api>/openapi.json -o src/api/schema.ts`.
- A snapshot is committed as `docs/openapi.json`. CI fails if the code's schema drifts from
  the snapshot without the snapshot being updated.

## Frontend recipes

**Product QR landing (`/r#<code>`)**

1. On the `/r` route, read the code from `location.hash` (drop the leading `#`). If signed
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
| QR `https://torsh-x.com/b/<9 chars>` or `TX1:B:<9 chars>` | `https://torshx.com/r#<CITY>-XXX-XXX-XXX`; the code is in the fragment; host from build config |
| Avatar, favourites, streak, spin, games, shop, tickets, events, social and invite state live in the browser | All of it moves to the endpoints above; the browser keeps only UI state |
| No T&C acceptance | Add it to setup |

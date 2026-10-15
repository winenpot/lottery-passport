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
| B01b | D5 | Roles: `users.role` column (player/admin today, migration 0008; staff/marketing only when a real caller needs them); `scripts.admins promote/demote/list`; `require_admin` API dependency (done); OPERATIONS.md runbook step. T2.3 builds the admin panel on these roles. | `scripts.admins list` shows at least one admin after first deploy; go-live checklist includes the check |
| B02 | ✅ | Batch generator and batch CLI (`list`, `activate`, `void`) | A test batch generated, activated and voided on staging |
| B03 | ✅ | Atomic redemption (one transaction), idempotent replay, daily cap in Tehran days | Concurrency tests green on PostgreSQL |
| B04 | ✅ | Coin ledger (append-only), wallet, `GET /api/v1/me/wallet` | Ledger UPDATE/DELETE rejected by the database |
| B05 | ✅ | Error envelope `{"error": {"code", "message"}}` for new endpoints | Documented in [API_CONTRACT.md](API_CONTRACT.md) |
| B06 | D1 | Create the real `REDEMPTION_CODE_PEPPER` (48+ random characters) and store it in a password manager with one backup holder. **Never change it after printing** | Two people can retrieve it; it is not in git, chat or email |
| B07 | D1 | Send [the decisions list](#decisions-needed-by-d2) to Mehdi and the CEO with the defaults | Message sent, deadline D2 stated |
| B08 | D1 | Request the staging VM now and the production VM for D8 from a **domestic** provider; ask for the `play.` subdomain | Staging reachable over SSH |
| B09 | D1 | Open accounts with two SMS providers; submit the OTP template (see [OPERATIONS.md](OPERATIONS.md#sms-provider)) | Template submitted with the `@domain #code` last line |
| B10 | D2 | Phone sign-in: Iranian mobile normalization (`+989XXXXXXXXX`), 2–3 minute OTP, 60 s resend cooldown and daily cap per phone, keyed OTP hash | Unit and API tests; a code arrives on your phone via the console sender |
| B11 | D4 | `jobs` table + worker process + SMS gateway adapter (verify/lookup endpoint) with timeouts, retry with jitter, expiry of stale OTP jobs, fallback provider | Killing the worker mid-send does not lose or duplicate the job beyond one extra SMS |
| B12 | D2 | Staging: Docker Compose (nginx, api, worker, postgres), TLS, `.env` from the password manager | `https://staging.../health` returns ok |
| B13 | D4 | First **test** batch (never printed), activated on staging; give Arman 20 QR URLs | Arman redeems one from his phone |
| B14 | D4 | First **print** batch per agreed quantities; encrypt; send; confirm checksum; record chain of custody ([CODES.md](CODES.md#handing-codes-to-the-printer)) | Factory confirms the checksum; batch stays `generated` |
| B15 | D5 | **Partly done (nickname, consent, `GET /config` without lounges; lounge needs B16)** — Profile: nickname (rules in [SECURITY.md](SECURITY.md#user-generated-text)), home lounge, consent version + timestamp; `GET /api/v1/config` (cities, lounges, server time, current day/week keys) | Nickname with RTL-override or zero-width tricks is rejected |
| B16 | D5 | **Done (code; lounges not entered yet)** — `venues` table with the three lounges (name, city, public IP if known) | Shown in the profile picker |
| B17 | D6 | Challenges: model, progress computed from data, `POST /claim` idempotent via the ledger key `challenge:<id>:<period>:<user>` | Double claim pays once (test) |
| B18 | D7 | Manual/social submissions: URL validation (Instagram domains), status machine, approve/reject with reason, payout on approve | Approve twice pays once (test) |
| B19 | ✅ | Failed-redemption throttle per account (for example 10 `CODE_INVALID` per hour, then 429) | Test proves the 11th is refused |
| B20 | D8 | **Steps 1-3 done** (sign-in + read-only views; audit log; coin adjustment). Next: approve/reject submission (needs B18). Admin panel (SQLAdmin, [ADR-0008](adr/0008-sqladmin-back-office.md) as amended): `admin` role + fresh-SMS admin session (no separate admin accounts), IP allow-list in nginx, audit log of every admin write, coin adjustment form writing ledger entries | Mehdi approves a submission himself; audit row exists |
| B21 | D8 | Weekly leaderboard per lounge and overall (coins earned, Saturday-to-Friday Tehran week), top 50 + my rank, 30–60 s in-process cache | Matches a hand-computed SQL result |
| B22 | D11 | Tournaments: admin creates, staff enters results, payouts via ledger key `tournament:<id>:<place>` | Results entered twice pay once |
| B23 | D9 | Production VM, deploy script (build, migrate, restart), release tags | Deploy of a tag takes under 10 minutes and is repeatable |
| B24 | D9–D11 | Backups: `pg_dump` every 6 hours and nightly to an off-site encrypted repository (restic); **restore drill** into a scratch database | Restore timed and written down (RTO) in [OPERATIONS.md](OPERATIONS.md#backups-and-restore) |
| B25 | D12 | Security pass per [SECURITY.md](SECURITY.md#pre-launch-security-checklist): nginx limits (lounge IPs allow-listed), headers, `/docs` off, code paths redacted from logs, gitleaks, pip-audit | Checklist ticked, findings fixed or written down |
| B26 | D11 | Monitoring: external uptime checks, error tracking, disk/CPU, SMS credit and failure rate; alerts by SMS/email (not Telegram: unreachable from a domestic server) | A test alert reaches your phone |
| B27 | D12 | Load test with k6 (arrival-rate executor) at 5x the expected peak ([TESTING.md](TESTING.md#load-test)) | p99 and error rate recorded at a stated load |
| B28 | D12 | Admin "check a code" for factory quality control: shows batch and status without redeeming | Factory sample of 10 caps checked |
| B29 | D12 | Feature freeze; release candidate to production; migrations; seed lounges and challenges | Production smoke test passes |
| B30 | D13 | Dry run with 10 internal testers; train Mehdi and staff on the admin panel | Every tester completed the loop |
| B31 | D14 | Pilot at lounge #1: watch logs and metrics live; hotfixes only | Pilot report written |
| B32 | D15 | Go/no-go; activate launch batches; launch | Decision recorded |
| B33 | should | Leaderboard TV page for lounge screens | Runs 8 hours on a lounge screen without a reload |
| B34 | should | Venue check-in: rotating signed QR on the lounge screen (60 s validity) | A photo of the QR is useless after a minute |
| B35 | should | Tournament self-registration | |
| B36 | D11 | Teams (flavor), unlock + monthly lock ([vault decision 2026-10-15](vault/Decisions.md)): 5 codes of a flavor (lifetime) unlock it (`flavor_unlocked` in the redemption response); the player joins an unlocked flavor with `POST /me/team`; switching is locked for 30 days after each join; `team_memberships` history; behind `/config.features.teams` | Join with 4 codes refused with 409 `FLAVOR_NOT_UNLOCKED`; join at 5 works; a switch on day 29 is refused with 409 `TEAM_LOCKED` (`switch_allowed_at`), on day 30 it works |
| B37 | D12 (extra hours) | Achievements + badges: spec in [GAMIFICATION.md](GAMIFICATION.md), `badges` catalogue (image assets, locked/unlocked art), `achievement_rules` editable in /admin, `user_achievements`, `FactPublisher` port with an in-process adapter in the same unit of work, `newly_unlocked` in the triggering response, `GET /badges`, `GET /me/achievements`; behind `/config.features.achievements` | Redeeming the 7th distinct flavor returns its badge in `newly_unlocked` exactly once |

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

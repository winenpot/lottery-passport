# Roadmap: Lottery Passport MVP (15 days)

**Window:** Day 1 = Wed 7 Oct 2026 (15 Mehr 1405) to Day 15 = Wed 21 Oct 2026 (29 Mehr 1405).
**Rule for these 15 days:** one complete loop that works every time beats five features that half work.

Companion documents: [docs/TODO.md](docs/TODO.md) (who does what, with IDs used below),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/SECURITY.md](docs/SECURITY.md),
[docs/OPERATIONS.md](docs/OPERATIONS.md), [docs/GOTCHAS.md](docs/GOTCHAS.md).

## Contents

- [What "MVP done" means](#what-mvp-done-means)
- [Calendar and assumptions](#calendar-and-assumptions)
- [Critical path: things with lead times we do not control](#critical-path-things-with-lead-times-we-do-not-control)
- [Milestones](#milestones)
- [Day-by-day plan](#day-by-day-plan)
- [Scope: must, should, later](#scope-must-should-later)
- [After the MVP](#after-the-mvp)
- [How we run the 15 days](#how-we-run-the-15-days)
- [Top risks](#top-risks)

## What "MVP done" means

The MVP is this story, working end to end on real phones at a real lounge:

> A gamer buys one of our city drinks (Tokyo, Moscow, ...), scans the QR under the cap,
> signs in with their mobile number (the SMS code fills itself in), and immediately sees
> a stamp in their **city passport** (one more entry in that city's trip draw), **coins**
> in their wallet, progress on **today's challenges**, and their nickname climbing the
> **weekly leaderboard** of their lounge. Staff run a short **tournament** and pay the
> winners in coins from the **admin panel**. Players can submit an Instagram post for a
> **social challenge** and get coins once marketing approves it.

Launch on D15 requires every one of these to be true:

1. The loop above works on staging and production, on Android and iPhone, on lounge Wi-Fi and on mobile data.
2. Printed codes (or the fallback code cards, see the critical path) exist for at least one city, and their batch is `active` in production.
3. A database backup has been **restored** successfully at least once (a backup that has never been restored does not count).
4. Monitoring pages someone when the site, the SMS provider or the database is down.
5. Legal has given a written opinion on the draw (or the draw is explicitly postponed and only coins and challenges launch).
6. Mehdi and venue staff have used the admin panel themselves: approved a submission, entered tournament results.

## Calendar and assumptions

| Day | Date | Jalali | Work |
|---|---|---|---|
| D1 | Wed 7 Oct | 15 Mehr | full |
| D2 | Thu 8 Oct | 16 Mehr | half |
| D3 | Fri 9 Oct | 17 Mehr | off |
| D4 | Sat 10 Oct | 18 Mehr | full |
| D5 | Sun 11 Oct | 19 Mehr | full |
| D6 | Mon 12 Oct | 20 Mehr | full |
| D7 | Tue 13 Oct | 21 Mehr | full |
| D8 | Wed 14 Oct | 22 Mehr | full |
| D9 | Thu 15 Oct | 23 Mehr | half |
| D10 | Fri 16 Oct | 24 Mehr | off |
| D11 | Sat 17 Oct | 25 Mehr | full |
| D12 | Sun 18 Oct | 26 Mehr | full, **feature freeze** at end of day |
| D13 | Mon 19 Oct | 27 Mehr | full, dry run |
| D14 | Tue 20 Oct | 28 Mehr | full, **pilot at lounge #1** |
| D15 | Wed 21 Oct | 29 Mehr | full, **go/no-go and launch** |

**Revised 2026-10-19:** the production gate moved to Thu 22 Oct and the launch batches
activate at 23:59 that night. The D13-D15 rows here and below are the original plan, kept
for history; the backlog status is in [docs/TODO.md](docs/TODO.md).

**Status 2026-10-25 (D19):** live since Thu 23 Oct by the owner's decision; production runs
`v2026.10.24-1`. Against the six launch conditions above: (1) not yet proven on real phones
(no device walk on the current frontend build); (2) ✅ Mehdi's sheet codes are active, the
bottle print run is generated but not yet with the printer; (3) ✅ a restore was drilled on
21 Oct, but the backups still sit on the same VM; (4) ❌ alerts are not installed; (5) ✅ the
draw is postponed; (6) ❌ submissions and tournaments are not built. We are in Phase 2's
window (D16 to about D30). Open items, owners and order:
[docs/launch-reports/2026-10-25-office-reply.md](docs/launch-reports/2026-10-25-office-reply.md).

Assumptions (change the plan if any is wrong):

- Saturday to Wednesday working week, Thursday half day, Friday off. That gives **11 full and 2 half working days**, not 15.
- No official holiday falls in the window (check the official calendar).
- Arman works at least 6 hours per working day on this project and is reachable the same day.
- A domestic server for staging exists by D2 and one for production by D8.
- One backend developer (you). Nothing in this plan assumes a second backend developer.

## Critical path: things with lead times we do not control

These can sink the launch even if all the code is perfect. Start every one of them on D1.

| # | Item | Owner | Needed by | Fallback if late |
|---|---|---|---|---|
| CP1 | **How codes physically reach the drink**: hidden under the cap or tab, QR or text only, printer capabilities, quantities per city ([CODES.md](docs/CODES.md)) | Mehdi with the factory; you supply the spec | Spec agreed D2; first print file D4 | Launch with **code cards** printed by a local print shop (variable-data printing) and handed out by venue staff with each drink |
| CP2 | **SMS provider** account under the company, OTP template approved with the `@domain #code` last line | You (tech), Mehdi (company documents) | D4 | Second provider pre-registered; voice OTP if the provider offers it |
| CP3 | **Domain**: a subdomain of the existing company domain (hours), not a new `.ir` domain (can take much longer) | You and whoever controls DNS | D2 | none needed |
| CP4 | **Domestic servers**: staging, then production | You; CEO approves cost | Staging D2, production D8 | Production on the staging VM with separate database and secrets (not ideal; note it as debt) |
| CP5 | **Legal opinion on the draw**, T&Cs, privacy notice, rules for minors and for travel prizes ([GOTCHAS.md](docs/GOTCHAS.md#legal-and-prizes)) | Mehdi with legal; CEO assigns counsel | D12 | Launch coins, challenges, leaderboard and tournaments; keep counting city entries; publish draw rules later |
| CP6 | **Coin economy and prize list** (coins per code, rewards, weekly budget) | Mehdi; CEO approves | D4 | Use the default table in [GAMIFICATION.md](docs/GAMIFICATION.md#default-economy) |
| CP7 | **Posters/standees with the QR**, screen at each lounge for the leaderboard | Mehdi with the venues | Printed by D12 | A4 prints on D13 |
| CP8 | **Arman's contract/availability** for 15 days | CEO/Mehdi | D1 | Cut scope to the must list, drop every should |

## Milestones

| Milestone | When | Exit criteria (all must be true) |
|---|---|---|
| **M0 Foundations locked** | end of D2 | Branch `feature/mvp-foundation` merged; decisions in [TODO.md](docs/TODO.md#decisions-needed-by-d2) answered or defaulted; code format confirmed with the factory; staging server reachable over HTTPS |
| **M1 Core loop on staging** | end of D5 | On a real phone: SMS login, scan a test QR, see passport entry and coins; Arman's pages use the real API |
| **M2 Must-haves complete** | end of D8 | Challenges (automatic and social/manual), leaderboard, admin panel with approvals; demo to CEO and Mehdi |
| **M3 Feature freeze** | end of D12 | Tournaments done; production deployed; a backup restored; load test passed; alerts tested; first two weeks of challenges loaded |
| **M4 Pilot** | D14 | Lounge #1 uses it with real codes from a small active batch; no data-integrity bugs; top issues fixed |
| **Launch** | D15 | Go/no-go meeting decides: all three lounges, or extend the pilot |

## Day-by-day plan

IDs refer to [docs/TODO.md](docs/TODO.md). ✅ = already done in branch `feature/mvp-foundation`.

| Day | You (backend and ops) | Arman (frontend) | Mehdi (marketing) | End-of-day check |
|---|---|---|---|---|
| **D1 Wed** | Review and merge the branch (B01–B05 ✅); store the real pepper (B06); send the decision list (B07); order servers, subdomain (B08); open SMS accounts, submit the OTP template (B09) | Project setup per [TEAM.md](docs/TEAM.md#working-with-arman): stack, RTL, self-hosted fonts, routes skeleton (A01–A03); read [API_CONTRACT.md](docs/API_CONTRACT.md) | Start legal (M02), factory spec meeting (M01), prize/economy draft (M03) | Decision list sent; SMS template submitted; branch merged |
| **D2 Thu** (half) | Phone OTP auth (B10); staging server with Compose, nginx, TLS (B12) | Login screens against the contract (A04) | Factory answers on print method (M01) | Staging answers `/health` over HTTPS |
| D3 Fri | off | off | off | |
| **D4 Sat** | Jobs table, worker, SMS adapter + fallback (B11); first **test** batch on staging (B13); print batch for the factory if CP1 is settled (B14) | QR route `/r/:code` and manual entry (A05, A06) | Economy and prize list final (M03); venue contacts (M05) | Real SMS arrives on a real phone |
| **D5 Sun** | Profile: nickname, home venue, consent; venues; `GET /config` (B15, B16) | Passport and wallet screens (A07) | Challenge calendar, first 14 days (M06) | **M1** demo on a phone |
| **D6 Mon** | Challenges: model, progress, claim (B17) | Challenges list, claim button (A08) | Brand assets, Persian copy (M07) | Daily challenge claimable on staging |
| **D7 Tue** | Social/manual submissions and approval (B18); failed-redemption throttle (B19) | Social submission form; profile (A09, A11) | Poster design with QR to print shop (M08) | A submission approved pays coins |
| **D8 Wed** | Admin panel with roles and audit log (B20); leaderboard (B21) | Leaderboard (A10) | Gamer interviews at a lounge with you (M15) | **M2** demo to CEO and Mehdi |
| **D9 Thu** (half) | Production server; deploy script; backups (B23, B24) | Error, empty and offline states (A12) | Staff guide draft (M10) | Backup job ran |
| D10 Fri | off | off | off | |
| **D11 Sat** | Tournaments and payouts (B22); restore drill (B24); monitoring and alerts (B26) | WebOTP autofill, polish, performance budget (A13, A14) | Load the challenge calendar into admin (M06) | Restore proven; alert reaches your phone |
| **D12 Sun** | Security pass (B25); load test (B27); QC tool for printed codes (B28); **feature freeze**; release candidate to production (B29) | Freeze; bug fixes only | Posters printed; launch comms ready (M11) | **M3**: freeze, production running |
| **D13 Mon** | Dry run with internal testers; staff and Mehdi trained on admin (B30) | Bug fixes from dry run | Staff training (M10); pilot testers recruited (M12) | Dry-run issues triaged |
| **D14 Tue** | Pilot at lounge #1: watch logs and metrics; hotfixes only (B31) | Same | On site, collecting feedback | **M4**: pilot report |
| **D15 Wed** | Go/no-go; activate launch batches; launch (B32) | Same | Launch comms | Launched, or pilot extended |

Two buffers are built in: the half days (D2, D9) and D13. If you are behind on D8, cut from the
"should" list immediately; do not borrow from D13 or D14.

## Scope: must, should, later

**Must (launch blockers)**

- Phone number + SMS code sign-in, with autofill (WebOTP on Android, `one-time-code` on iPhone).
- Printed codes v2, batches with activate/void, QR landing page, manual code entry. *(backend ✅)*
- Coin wallet with history. *(backend ✅)* The city passport is **parked** for the MVP
  ([ADR 0009](docs/adr/0009-park-city-passport.md), [docs/parked/CITY_PASSPORT.md](docs/parked/CITY_PASSPORT.md));
  the backend keeps recording entries.
- Every screen of the 2026-10-10 frontend demo has an endpoint in
  [API_CONTRACT.md](docs/API_CONTRACT.md#screen-map); the build order is in the plan.
- Daily and weekly challenges: automatic types (redeem N codes, collect N different cities) and manual types (social post, staff-verified task) with an approval queue.
- Weekly leaderboard per lounge and overall, ranked by coins **earned** this week.
- Tournaments entered by admin/staff, results paid in coins.
- Admin panel: users, batches, challenges, approvals, tournaments, ledger (read-only), coin adjustments, audit log.
- Nickname, home lounge, consent to T&Cs.
- Operations: domestic hosting, TLS, backups with a tested restore, monitoring and alerts, load test, runbooks.

**Should (cut line: build only if ahead on D8)**, in this order:

1. Leaderboard "TV mode" for the lounge screens (big, auto-refreshing, read-only page).
2. Venue check-in with a rotating QR on the lounge screen.
3. Tournament self-registration in the app.
4. Shareable story image ("my passport: 4/7 cities") for Instagram.

**Later (do not start before launch)**

- Prize store (spending coins) and prize fulfilment.
- Draw tooling and rehearsal ([DRAW.md](docs/DRAW.md)).
- Identity check at prize claim (phone number matched to national ID).
- Seasons / battle pass, squads, push notifications. (Referrals moved before launch on
  2026-10-19 and shipped: [TODO B40](docs/TODO.md).)
- Challenges verified through game data (for example Dota 2 match history).
- Redis, a second server, read replica: only when a measured need appears ([ADR 0004](docs/adr/0004-postgres-only-no-redis-for-mvp.md)).

## After the MVP

| Phase | When | Goal | Main items |
|---|---|---|---|
| Phase 2: stabilise and reward | D16 to about D30 (late Mehr to mid Aban) | People can spend coins; we can prove fairness | Prize store with stock limits; claim flow with identity check; check-in; story sharing; weekly report for the CEO (signups, redemptions per city/lounge, retention) |
| Phase 3: first draw | Before the first draw date marketing announces | A draw nobody can credibly call rigged | Entry snapshot, published hash, public seed, rehearsal, winner verification ([DRAW.md](docs/DRAW.md)); legal sign-off |
| Phase 4: season 2 | After the first draw | Retention | Seasons with resets, squads per lounge, game-data challenges; scale only where metrics say so |

## How we run the 15 days

- **Daily 10-minute check-in** (same time every day, voice or chat): yesterday, today, blockers. Blockers get an owner and a deadline in the same call.
- **One board** (a GitHub Project on this repository works): every item from [TODO.md](docs/TODO.md) is a card with its ID.
- **Demos on staging** at M1 (D5), M2 (D8), M3 (D12). Demos replace status reports.
- **Change control after D8**: a new request goes to Phase 2 unless it replaces something of the same size (the swap rule). Write the swap down.
- **Definition of done** for any item: merged, deployed to staging, tested on a real phone, documented if behaviour changed.

## Top risks

Full list with mitigations: [docs/GOTCHAS.md](docs/GOTCHAS.md).

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Codes not printed in time | High | Launch without the core mechanic | CP1 started D1; code-card fallback |
| Draw ruled illegal or needs a permit we lack | Medium | Campaign stopped, public embarrassment | Written legal opinion by D12; launch without the draw if needed |
| SMS template or provider delays | Medium | Nobody can sign in | Submit D1; second provider; voice OTP |
| Cheating: account farming, code harvesting from shelves, staff granting coins | High | Prizes go to cheaters, community trust lost | Codes hidden until opened; per-account caps; audit log; manual review of top players before any prize |
| Internet disruption or foreign services blocked | Medium | Site unreachable or partly broken | Everything hosted and served domestically; no foreign CDNs, fonts or SaaS on the critical path |
| Scope creep from marketing | High | Missed launch | Cut line above; swap rule after D8 |

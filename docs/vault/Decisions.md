---
type: adr
---

# Decisions — implementation-session log

Short-form, dated. Formal ADRs for architecture-level choices live in
`../adr/`; this is the lighter day-to-day decision trail for things ADRs
don't cover (process, scope, open questions resolved in chat).

## 2026-10-07 — code length left open; built a pluggable format instead

Neither 10 (repo default, `../../app/domain/codes.py` pre-change) nor 8
(the user's earlier preference per HANDOFF.md) was agreed by the team.
Decision: build a `CodeFormat` registry (any alphabet/length/grouping) with
export, freeze and event tracking, so the actual length can be decided
later without another migration. See `../../app/domain/codes.py` and
`../../alembic/versions/0006_batch_format_tracking.py`.

## 2026-10-07 — QR link stays path form (`/r/CODE`)

Chosen because it is the more common pattern and the repo docs
(`../../docs/CODES.md:29`) and Arman's planned route (`../../docs/TODO.md:88`)
already assume it. The handoff's alternative (fragment form, `/r#CODE`, to
keep codes out of server logs) was not picked. Mitigation: redact `/r/*`
paths from nginx access logs as part of the security pass (B25).

## 2026-10-07 — Postgres-only stays, behind a port

ADR 0004 (`../adr/0004-postgres-only-no-redis-for-mvp.md`) is accepted as
written. The user wants the ability to turn on Redis later without a
rewrite if the SMS/job queue proves too slow or a second API server
appears, so the job queue will sit behind an application port
(`QUEUE_BACKEND=postgres|redis` switch), Postgres-backed implementation
shipping first.

## 2026-10-07 — phone + SMS OTP only, no email sign-in

Confirms ADR 0005. Email auth path in the current code is to be removed
when B10 (phone OTP) is implemented.

## 2026-10-07 — commit hooks and HANDOFF.md

`core.hooksPath` set to `.githooks` (committed, enforces gitmoji +
conventional-commit subjects). `HANDOFF.md` (written by a prior session,
superseded by this vault + the plan file) is gitignored and will be
deleted once this vault is confirmed to carry everything load-bearing from it.

## 2026-10-14 — QR back to path form `/b/<code>`; venue check-in; sheet is final

- **QR format supersedes 2026-10-10:** `https://torshx.com/b/<CITY>-XXX-XXX-XXX`
  (Arman's route; the fragment form was a misunderstanding on our side). Host stays
  `torshx.com` (torsh-x.com does not resolve). Nothing was printed, so no code changes;
  the parser accepts both forms. Cost: the code reaches proxy access logs, so `/b/*` is
  redacted there and the app sends `Referrer-Policy: no-referrer`.
- Daily venue check-in QR `/q/<venue>/<date>/<token>` (one printed sheet per lounge per
  day, staff swap it each morning), small coin reward, once per player per day.
- Rewards sheet is final for launch (Mehdi, 2026-10-14), referral part pending his voice
  note. Leaderboard = sheet: monthly league points per player and per flavor team.
- Game scores are never trusted from the browser: server-issued runs, plausibility checks,
  caps. Spin / PS5 draw: visuals now, routes stubbed, payouts off until legal sign-off.
- Profile photos: chosen from a server-side avatar catalogue (some locked, unlocked by
  coins/achievements later); no user uploads (no moderation capacity). Home city
  (location city) added to the profile.

## 2026-10-10 — frontend demo, QR format, hosting, sizing

- Frontend demo reviewed (Arman, http://86.104.82.71:8000/, all mocked in the
  browser). `../API_CONTRACT.md` now covers every demo screen; city passport
  parked (`../adr/0009-park-city-passport.md`).
- **QR format supersedes the 2026-10-07 entry:** `https://torshx.com/r#<CITY>-XXX-XXX-XXX`
  (2-letter city code + 9 characters, code in the URL fragment). The fragment
  never reaches the server or logs, so the `/r/*` log redaction is no longer
  needed. New code format still to be registered (plan task F1).
- Domain: torshx.com. Daily scan cap: 5. Spin wheel and PS5 draw stay in scope.
- Hosting: first week on Render (API) + Supabase (DB) as test; domestic servers
  later. We host Arman's build ourselves behind Caddy on HTTPS (plan task F3):
  a plain http://IP:port page can't use the camera, WebOTP or cross-site cookies.
  Canonical frontend repo should live in the company group.
- Stay on FastAPI + SQLAdmin (no Django switch); challenges, prizes, events and
  tournaments become admin-editable rows (typed columns + JSONB params).
- API_KEY dropped 2026-10-11 (unused; a browser app can't keep a secret). No
  server-to-server integration needs it; add a scoped key if one ever does.
- Sizing (estimate only, servers not yet measured): max 40k users, 10k active at
  a spike -> plan for 1,000 req/s; 2 servers (app 4 vCPU/8 GB, DB 4 vCPU/16 GB
  NVMe) + continuous off-site WAL backups. Method to confirm it:
  `../ops/CAPACITY_PLANNING.md`. Final call goes in ADR 0010 after measurements.
- Still open: reward economy and delivery (user + Mehdi, after DB design).

## 2026-10-14 — team exclusivity, diamonds full scope, achievements design (queued)

Resolved in chat while E1 was in flight; not yet reflected in the plan file (queued
behind finishing E1, per the user's own sequencing call). Recorded here first so none
of this is lost to a session/context loss.

- **Team membership is exclusive, by SKU-purchase threshold.** Crossing a new
  highest-threshold flavor switches your team; a player is never on two teams at
  once. Chosen specifically to keep the monthly league's "team score = sum of
  members' points" meaningful (overlapping membership would have let everyone
  count toward every team, erasing the lounge/team rivalry `GAMIFICATION.md`
  principle 5 depends on). Maps onto existing `passport_progress` data — no new
  table needed for the threshold check itself.
- **Diamonds: full scope before D12 freeze** (convert action, Mehdi's 72h/monthly
  conversion window, a new PS5 raffle-entries table) — overrides this session's
  earlier "defer to post-launch" default. The ledger `asset` column (E1, migration
  0013) already anticipated this; the new work is the convert action, exposing a
  second balance on `/me/wallet`, and the raffle-entries table. Mehdi's "PS5 draw is
  probably per season" remark introduces a season concept `ROADMAP.md` explicitly
  parks for Phase 4 — do not build season infrastructure for this; scope diamonds/PS5
  to work for one unnamed season (today's), revisit seasons only if Mehdi insists.
- **Achievements: no message broker.** The user asked for an event-driven rules
  engine (emit facts, match against stored definitions) and separately asked whether
  RabbitMQ/Kafka/Redis Streams were warranted. Decision: no. ADR 0004 already rejected
  Redis for the MVP for a stronger case (the SMS job queue) than achievements is;
  Kafka/RabbitMQ would add an infra component to operate, back up and secure during a
  four-working-day runway, for a feature with zero existing spec, at a load this
  campaign's own numbers (~1,000 req/s peak, see above) do not come close to needing.
  Design instead (mirrors ADR 0004's `QUEUE_BACKEND=postgres|redis` shape exactly):
  - `FactPublisher.publish(fact)` — the only thing application services call; no
    infrastructure concept is visible above this port.
  - `InProcessFactPublisher` (ships with achievements, whenever that is built):
    evaluates `achievement_rules` and writes `user_achievements` in the *same*
    unit-of-work transaction as the triggering write. Zero new infrastructure.
  - Escalation path, not built now: a transactional outbox (`fact_outbox`, written in
    the same transaction so nothing is lost waiting on a broker) drained by a worker,
    reusing B11's planned Postgres-backed `jobs`/worker machinery. A broker, if ever
    genuinely needed, would only be imported inside that worker — never above the
    `FactPublisher` port, never in `RedemptionService` or any other call site.
  - Achievements has no existing spec (checked: nothing in the repo beyond one
    throwaway line in this file); `GAMIFICATION.md`'s own anti-patterns table already
    warns against hollow badges and "two confusing currencies" — needs its own
    spec pass before building, not just an architecture.
  - Notification-on-unlock is a DIFFERENT problem than the write and needs its own
    answer, not "same as the write": the `user_achievements` row is a plain DB write
    (atomic, rolls back with everything else, fine in-transaction); telling the user
    is an external side effect and must never fire from inside a transaction that
    might still roll back (same principle as SQLAdmin's audit log running in its own
    transaction, mirrored: there a side effect must not undo a real write, here a
    side effect must not fire on a write that isn't durably committed yet).
    In-app notification (the common case): no new mechanism — the triggering call
    returns `newly_unlocked: [...]` in its own response, exactly like `bonus_awarded`
    already does; an unread counter (same shape as `API_CONTRACT.md`'s planned
    `unread_activity`) covers achievements the user didn't see live. Out-of-app
    push/SMS (nobody has asked for this yet): the transactional-outbox + B11-worker
    escalation path already named above — outbox row written in the same
    transaction, worker sends the push/SMS only after that transaction is confirmed
    committed, outside it. Scope to the in-app case only unless push/SMS is
    explicitly requested later.

## 2026-10-14 evening — Fibonacci team switching, achievements + badges, staged rollout

- **Superseded 2026-10-15** (Mehdi didn't see the point of Fibonacci; see the 2026-10-15
  entry below). Kept for history:
  **Team switching follows Fibonacci from 5** (Ashkan, team chat). A player joins a
  flavor team automatically when one flavor reaches 5 codes. Switching afterwards is
  the player's choice and needs the next number of codes of the TARGET flavor:
  8 for the first switch, 13 for the second, then 21, 34, ... Each switch is harder,
  so teams stay meaningful for the league but nobody is locked in forever.
  Refines the morning entry above: "crossing a new highest threshold switches your
  team" becomes "unlocks the right to switch"; exclusivity is unchanged.
  - Default, open to objection: codes count since the last team change (lifetime
    counts would make later switches free for heavy buyers).
  - Stored as an additive `team_memberships` history (user, flavor, joined_at,
    switch_no). Default for the league: points count for the team the player was on
    when they earned them (Mehdi may choose "team at month end" instead).
  - Rejected switch: 409 `TEAM_THRESHOLD_NOT_MET` with `required` and `have`.
- **Staged rollout instead of cutting** (Arman's point: no awareness yet, too many
  mechanics on day one confuses players; the team agreed). Everything in the MVP plan
  still gets built; mechanics go live gradually through `/config.features` flags.
  Teams and achievements each get a flag. Flavors reach players first through
  challenges ("discover 3 flavors").
- **Achievements + badges are a planned MVP item** (B37), built in the user's extra
  hours so they don't displace other launch work. Badges are catalogue assets (image
  per badge, locked and unlocked art), same shape as the avatar catalogue. A spec
  pass (the list of achievements) comes before code; architecture as in the morning
  entry (FactPublisher, in-process, no broker).

## 2026-10-15 — teams: unlock by scanning, choose, 30-day lock (replaces Fibonacci)

Mehdi's reply to the Fibonacci rule (team chat 2026-10-14 17:05): players should pick the
team of their favourite flavor, with a limit so they don't keep changing; a monthly
change is fine. Ashkan's rule, adopted:

- **Unlock:** 5 codes of a flavor (lifetime count) unlock that flavor's team for good,
  plus that flavor's badge (7 flavor badges, part of AC1/B37). The redemption that
  reaches 5 returns `flavor_unlocked`.
- **Choose:** nothing joins automatically. The player picks a team among the unlocked
  flavors (`POST /me/team`). The sheet's "choose team, 30 coins once" pays on the first
  join (C1).
- **Lock:** joining locks the team for 30 days from the join. After that the player may
  switch to any other unlocked flavor, including one left earlier; each switch starts a
  new 30-day lock. Refusals: 409 `FLAVOR_NOT_UNLOCKED` (`required`, `have`), 409
  `TEAM_LOCKED` (`switch_allowed_at`).
- Defaults chosen, open to objection: lifetime counts (not "since joining"); 30 rolling
  days, not calendar months; going back to an earlier team is allowed.
- Unchanged: exclusive membership, `team_memberships` history (user, flavor, joined_at,
  switch_no). Mehdi confirmed league credit goes to the team the player was on when the
  coins were earned (his "option one").
- Open, F1 not P1: Mehdi asked whether features can open day by day (a ~7-day journey).
  Needs his answer on per-player days (from signup) versus fixed campaign dates.

## 2026-10-15 — C1 challenges: MVP subset ships, login/activity tracking needs a decision

Built the generic challenge engine (`challenges` catalogue + `challenge_claims`,
admin-editable, same empty-start pattern as avatars/reward rules) and shipped the two
sheet items with an unambiguous, already-existing data source:

- **`team_choice`** (once, 30 coins): the player's first team join. Reuses
  `team_memberships` (P1) — no new data needed.
- **`distinct_flavors`** (period, 100 coins monthly per the sheet): distinct flavors
  redeemed within the period. Reuses `redemption_codes` — no new data needed.

**Deliberately NOT built, rather than guessed:**

- "First game 20 once" / "Tap Reflex <250ms 20 daily" — blocked on G1: no game-run data
  exists yet to check progress against. Will add their kinds to the catalogue's closed
  set once G1 ships.
- "5-day login 30" / "5-day activity 100" (not additive: pay 30, top up 70) — the sheet's
  wording assumes a real signal for "did the player use the app today", which this
  backend does not have: the session cookie is long-lived, so a player can open the app
  every day for weeks without a single new sign-in event. Building this needs a product
  decision first, not just more code: where does "day used" get recorded (every
  authenticated request — a write on every GET, a real load question; or a dedicated
  lightweight endpoint the frontend calls once per app-open)? Until that is decided this
  pair is left out of the catalogue's kind enum entirely, rather than wired to a fake or
  silently-always-zero signal that would look shipped but never pay out correctly.

Error codes `CHALLENGE_NOT_UNLOCKED` (409, `required`/`have`), `CHALLENGE_ALREADY_CLAIMED`
(409). Claim idempotency is a real UNIQUE constraint on `challenge_claims (challenge_id,
user_id, period_key)`, not just the ledger's own idempotency key — the same shape as
`team_memberships`' `switch_no` guard.

## 2026-10-15 — daily check-in resolves the login/activity tracking gap; achievements MVP slice

Resolves the open question from the entry above. User's proposal: don't detect a login
passively — make checking in an explicit, player-initiated action, and let that action's
own claim history double as the signal.

- **New `daily_checkin` challenge kind** (period `day`, always completed once signed
  in). The claim itself IS the "player used the app today" signal — no new table, no
  per-request write. Supersedes "5-day login 30" / "5-day activity 100" from the sheet
  entirely (same kind of sheet supersession as the Fibonacci→unlock team-rule swap);
  pay amount stays admin-tunable (`challenges.reward_coins`), not re-guessed here.
- **Streak** = consecutive Tehran calendar days with a `daily_checkin` claim, computed
  from `challenge_claims` (`app.domain.periods.current_streak`). Counts from today, or
  from yesterday if today is not claimed yet, so it does not look broken before the
  player has had a chance to check in.
- **Achievements (AC1 MVP slice, pulled forward from B37)**: streak milestones (e.g.
  3/7/30 days, numbers are Mehdi's to set via `/admin`) auto-unlock and pay through the
  ledger, inside the SAME transaction as the triggering `daily_checkin` claim. No claim
  step — "easily claimable" means no second tap, not a faster one.
- **One-time per player, ever — this is the load-bearing decision.** `user_achievements`
  is `UNIQUE (achievement_id, user_id)`, not per-period. The user caught the exact
  failure mode of getting this wrong: if a 3-day and a 7-day milestone paid every time a
  player reached them, breaking a streak on purpose and rebuilding it (3 days → quit →
  3 days → quit → ...) would out-earn ever completing an honest 30-day streak, since the
  short milestones could be farmed roughly weekly while the 30-day one pays once. The
  one-time-ever guard closes this: once `streak_3`/`streak_7` are unlocked, reaching
  those streak lengths again pays nothing, so there is no incentive to reset on purpose.
- **Scope cut from B37's full spec, deliberately**: no `badges` catalogue (images,
  locked/unlocked art) — needs Ashkan's assets and Mehdi's approved 8-12 item list,
  which has not happened; no generic `FactPublisher` port — only one fact
  (`checkin_streak`) exists today, and CLAUDE.md's own rule is to add an abstraction
  when a second real caller appears, not before; no `/config.features.achievements`
  gate — F1 does not exist yet either, same ungated state as teams/challenges today.
  `GET /me/achievements` lists only unlocked achievements (no "locked, X/Y progress"
  view yet).

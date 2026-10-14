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

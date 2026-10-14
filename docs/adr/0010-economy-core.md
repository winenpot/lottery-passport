# ADR 0010: Economy core — asset column, first-code bonus, reward rules, period keys

Date: 2026-10-14. Status: accepted.

## Context

B20 (admin panel) is done. Next per the revised plan
(`.hermes/plans/2026-10-14_mvp-revised.md`, E1): the rewards sheet
(`Torsh-X Rewards.xlsx`) is final for launch (Mehdi, 2026-10-14) and a few
pieces of economy groundwork block everything after it (C1 challenges, G1
games, V1 check-in all pay coins on some cadence; a future diamond currency
is explicitly deferred but must not require another ledger migration when
it lands).

## Decisions

1. **`coin_ledger_entries` gets an `asset` column**, `NOT NULL DEFAULT
   'coin'`, `CHECK (asset = 'coin')` for now. All existing rows backfill to
   `'coin'` by the default; nothing else changes shape. When diamonds ship,
   loosen the check (`CHECK (asset IN ('coin', 'diamond'))`) rather than
   adding a column — that is the whole point of adding it now, unused.
   `wallets.balance` stays single-asset (coin only); giving diamonds their
   own balance is that future feature's own migration, not this one's.

2. **`coins_per_code` stays a per-batch column** (`code_batches.coins_per_code`,
   set at `scripts.generate_codes` time) — it was never a global constant.
   What changes: the CLI's default moves from `0` to `100` (the sheet's
   standard reward), so a forgotten `--coins-per-code` flag matches the
   sheet instead of silently printing free codes. Already-generated batches
   are untouched (additive; nothing is backfilled).

3. **First-code bonus (+50 once) is a service default, not seeded data.**
   `RedemptionService` gets a `first_code_bonus_coins` setting (default 50,
   from the sheet). A `reward_rules` table (key, amount, cadence, active,
   note — admin-editable, like venues: "no rows are seeded... added via the
   admin panel") lets an override replace the number or switch it off
   (`active = false`) without a deploy; no row means "use the configured
   default." This gives correct-by-default behaviour (the sheet's number
   works the moment the migration runs) without migrations carrying
   business data, matching migration 0010's venues precedent. Ledger
   idempotency key: `first_code:<user id>` (one-time, same pattern as
   `code_redemption:<code id>`); reason `first_code_bonus` for reporting.
   `reward_rules` is plain, mutable config (not append-only like the
   ledger): correcting a typo in an amount is an edit, not a new row.

4. **Tehran period keys move into the domain now**
   (`app/domain/periods.py`): `tehran_day_key`, `tehran_week_key` (the
   Saturday the week starts), `tehran_month_key`, matching the format
   `docs/ARCHITECTURE.md` already promises challenges (`D:2026-10-14`,
   `W:2026-10-10`, `M:2026-10`). Built now so C1 (challenges), G1 (games)
   and V1 (check-in) consume one tested implementation instead of three
   copies of "which Saturday does this week start on".

## Consequences

- Migration 0013 is additive only: one new column with a default (existing
  rows need no backfill statement), one new empty table. No downtime, no
  data migration step.
- `RedemptionResult`/`RedemptionResponse` gain `bonus_awarded: int` (0 when
  none paid this call) — additive API field; existing clients ignore it.
  `docs/API_CONTRACT.md` and `openapi.json` updated in the same commit.
- Reading `reward_rules` happens inside the redemption's existing unit-of-
  work transaction (one more `SELECT` by primary key; negligible cost), so
  the override is read with the same consistency as everything else in
  that transaction — no separate cache, no staleness window to reason about
  for the MVP's traffic.
- Mehdi can turn the first-code bonus off or retune it from `/admin` without
  a deploy, which is the whole point of the table existing before any
  feature besides this one reads it.

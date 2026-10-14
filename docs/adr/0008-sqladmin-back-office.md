# ADR-0008: SQLAdmin for the back office

**Status:** Accepted, amended 2026-10-12 (sign-in and roles; see "Amendment" below)
**Date:** 2026-10-07
**Deciders:** Backend developer; Mehdi (main user)

## Context

Marketing and lounge staff need to manage challenges, approve social submissions, enter
tournament results, look up users and adjust coins with a reason. There is no time to build a
custom admin frontend, and Arman's time is reserved for the player app.

## Decision

Use **SQLAdmin** (version 0.32 at the time of writing), mounted at `/admin`, served on the same
VM but reachable only from allow-listed IPs (office, VPN, lounges) through nginx, with:

- staff sign in with their own phone number (SMS code), not with a password; who may use the panel is the `admin` role on `users` (see Amendment, which replaces the original separate `admin_users` table with passwords and four roles);
- read-only views for the ledger, codes and redemptions;
- custom actions for "approve/reject submission", "enter tournament results" and "adjust coins" that call the same application services as the API (never raw edits of balances);
- an audit log row for every admin write.

## Amendment (2026-10-12): staff sign in with the phone session, one `admin` role

The original text planned a separate `admin_users` table (username, password hash, TOTP) and
four roles. Before any of it was built, the project shipped phone-OTP sign-in and a
`users.role` column (`player` / `admin`, migration 0008, `require_admin`, `scripts.admins`).
Building a second identity system beside it would add password storage, reset flows and
a second set of secrets for a handful of staff. So:

- **Identity:** an admin is a normal user with `role = admin`. Roles are made and removed only
  with `scripts.admins promote/demote` (database access); no API route can grant them.
- **Panel sign-in:** entering `/admin` asks for a fresh SMS code even if the player session is
  active. It issues a separate admin session cookie (`Path=/admin`, `HttpOnly`, `Secure`,
  `SameSite=Strict`, about 1 hour), so a player-app XSS or a leaked player cookie does not
  open the panel. Every request re-checks that the user still has `role = admin`
  and is active, so demoting someone takes effect immediately.
- **Roles:** only `admin` for now. `marketing`, `venue_staff` and `support` come back only
  when a second real person needs fewer powers; until then every admin can do everything an
  admin can do, so the audit log and the IP allow-list carry the weight.
- **Unchanged:** the nginx IP allow-list, read-only ledger/codes/redemptions views, actions
  that call the application services, and the audit log row for every admin write.
- **Build order:** (1) the SQLAdmin mount with the sign-in above and read-only views;
  (2) `audit_log`; (3) write actions (approve submission, adjust coins), each through its
  application service; (4) a second factor (TOTP) if the owner wants one.

**What this trades away:** SMS is a weaker second factor than password plus TOTP. A SIM swap or
SMS interception would let someone sign in as that admin. The allow-list (they must also be on an
office or VPN address), the 1-hour admin session, keeping the admin count small and the audit log
are the compensating controls. Passwords, reset flows and hashes disappear from the system.

## Options considered

### Option A: SQLAdmin (chosen)

**Pros:** works with the existing SQLAlchemy models; list/search/filter for free; custom actions possible; a day to set up.
**Cons:** custom workflows need code; styling is generic (fine for staff).

### Option B: custom admin pages in the PWA

Rejected: competes with player features for Arman's time.

### Option C: direct database access (psql, DBeaver) for staff

Rejected: no roles, no audit, one typo away from a disaster.

## Trade-off analysis

The admin panel is a security boundary as much as a convenience: the roles, IP allow-list
and audit log are the point, not the forms.

## Consequences

- Easier: Mehdi self-serves; you stop being the bottleneck for every approval.
- Harder: every custom action must reuse the application services so the ledger rules hold.
- Revisit: a purpose-built reviewer screen if submission volume exceeds what one person approves comfortably.

## Action items

1. [x] SQLAdmin mount with fresh-SMS admin session, read-only views (B20, step 1;
   players, lounges, code batches, wallets, coin ledger).
2. [x] `audit_log` table and a hook for every admin write (B20, step 2; done
   2026-10-14, migration 0012). Two writers: SQLAdmin's own `audit_backend`
   (generic CRUD -- lounges are now editable; a separate, best-effort
   transaction after the edit commits) and the application's unit of work for
   a multi-table action (coin adjustments; same transaction as the write).
3. [x] Coin adjustments through `CoinAdjustmentService` (B20, step 3; done
   2026-10-14): a custom `/admin/coin-adjustments` page, never a raw edit.
   [ ] Submission/approval actions remain (B18, once social submissions exist).
   nginx IP allow-list is still open (infra, not code).
4. [ ] Train Mehdi and lounge staff (B30).

# ADR-0013: Admin TOTP second factor

**Status:** Accepted
**Date:** 2026-10-24
**Deciders:** Backend developer; Ashkan (owner), per the 23 Oct 2026 decision log
(`docs/launch-reports/2026-10-23-handoff.md`, decision 8).

## Context

Admin sign-in today (ADR-0008 as amended) is phone number + SMS code, no password,
no TOTP. SMS is a weaker second factor than TOTP (SIM swap risk is explicitly called
out in `docs/SECURITY.md` T13), and the compensating control has been an nginx IP
allow-list that must track whichever office/VPN/mobile address an admin is on that
day. On 23 Oct the shared-VPN allow-list entry was removed, leaving only the office
range and one temporary mobile address, explicitly noted as temporary "until admin
TOTP exists." This ADR is that build.

## Decision

Add TOTP (RFC 6238, Google Authenticator-compatible) as an **opt-in-per-admin**
third step after the existing phone + SMS code, not a global switch:

- **Algorithm**: `app/domain/totp.py`, stdlib-only (`hmac`/`hashlib`/`base64`/`time`),
  the same "framework-free domain code" shape as `app/domain/phone.py`. No `pyotp`
  dependency; the algorithm is ~30 lines and verified against the official RFC 6238
  test vectors.
- **Storage**: two nullable columns on `users` (migration `0022_admin_totp`), not a
  separate table -- the same reasoning ADR-0008's amendment already used for
  rejecting a second `admin_users` table. `totp_secret_encrypted` is NULL until an
  admin starts enrolling; `totp_confirmed_at` only moves from NULL once they prove
  they can generate a real code, so a mistyped secret during setup can never lock
  anyone out. A CHECK constraint enforces that a confirmed row always has a secret.
- **Encryption at rest**: unlike an OTP challenge code (short-lived, only ever
  stored hashed), a TOTP secret is long-lived -- a database dump alone would let an
  attacker forge codes forever otherwise (the T4 threat `docs/SECURITY.md` already
  names for printed codes and the pepper). `app/infrastructure/crypto.py` wraps
  `cryptography`'s Fernet, keyed by a new secret `ADMIN_TOTP_ENCRYPTION_KEY`
  (validated the same way as `ADMIN_SESSION_SECRET`: required, >=32 chars, in
  staging/production; a random per-process key in development/demo, same trade-off).
  This is the one new production dependency this feature needed.
- **No QR code.** Three admins exist today; rendering a scannable QR would need
  either a new image-generation dependency or a vendored client-side JS library
  (the admin panel's CSP is `script-src 'self'`, no inline scripts, nothing
  vendored yet). The enrollment page instead shows the base32 secret as text for
  "enter a setup key" in the authenticator app. Revisit with a real QR only if the
  admin list actually grows (CLAUDE.md: don't build ahead of a real caller).
- **Enrollment is self-service, gating is per-admin**: `/admin/security/totp`
  (`AdminTotpSetupView`) lets a signed-in admin generate a secret and confirm it
  with one real code. From that point on, *their own* sign-ins require the TOTP
  step; admins who haven't enrolled keep signing in with phone + SMS code alone,
  unchanged. No global "TOTP required" setting exists (yet) -- SECURITY.md's own
  checklist line reads "TOTP on owner/marketing", not "on every admin", and nothing
  today needs an all-or-nothing switch.
- **Re-enrollment is blocked once confirmed** (`AdminTotpAlreadyEnrolledError`): a
  hijacked admin session must never be able to silently swap the second factor to
  one the real admin doesn't hold. Recovery for a lost phone is
  `scripts.admins reset-totp <identifier>` -- direct database access, same
  deliberately-not-an-API-route shape as `promote`/`demote`.
- **Brute force**: the admin session itself counts wrong TOTP attempts (5 before
  the whole sign-in restarts from the phone step). No new table: with roughly 3
  admins, a per-admin-session counter is proportionate; a `redemption_failures`-style
  persistent throttle would be over-engineering for this headcount.

## What this trades away

TOTP being opt-in per admin (rather than enforced for everyone from day one) means
an admin who never visits the setup page stays on SMS-only, same risk as today. That
is a deliberate, reversible choice: enrollment is a five-minute self-service action
with no deploy involved, so "make it mandatory" is a policy decision for the owner,
not a code change, if and when it is actually wanted.

## Options considered

### Option A: TOTP second factor, opt-in per admin (chosen)

See Decision above.

### Option B: Drop SMS, require TOTP only

Rejected for now: would need a forced-enrollment flow for the one admin who hasn't
set it up yet, and a recovery path during that gap. Not worth building before any
admin has actually asked for it to be mandatory.

### Option C: Chase the IP allow-list instead (status quo)

Rejected: this is the exact problem decision 8 named -- an admin on a new mobile
connection needs the allow-list edited by hand every time, which doesn't scale past
one admin and doesn't survive a dynamic IP.

## Trade-off analysis

The admin panel's security already rested on several compensating controls (IP
allow-list, 1-hour session, audit log, small admin count) because SMS alone is
weaker than password + TOTP. This ADR adds the missing second factor without
touching any of those controls, and without inventing new infrastructure beyond one
small, auditable crypto wrapper.

## Status update 2026-10-25

Shipped 24 Oct (PR #8, release `v2026.10.24-1`). The same night `/admin` was opened to every
IP (PR #9, `site/admin_allow.conf` = `allow all;`), which removed the compensating control
the trade-off above keeps ("without touching any of those controls"). With opt-in
enrollment, an admin who has not enrolled signs in with SMS alone, now from anywhere: 0 of
3 production admins had enrolled on 25 Oct. Owner's choice: every admin enrolls now (no
code), and the forced-setup redirect of option B follows as a small task; or the
allow-list comes back until then.

PR #9 also put the player OTP rate-limit zones on all of `/admin`, which refused the
panel's own CSS/JS. Fixed 25 Oct: only `/admin/login` POSTs count (zone `admin_login`,
6/min per IP).

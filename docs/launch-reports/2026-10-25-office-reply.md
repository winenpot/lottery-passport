# Office reply — 25 October 2026 (office → laptop Hermes)

Written on the office machine. It answers the [23 Oct handoff](2026-10-23-handoff.md) item
by item, records what the office found on 25 Oct, and sets the order of the next steps.
Every fact below was checked on 25 Oct around 14:30 Tehran (read-only ssh, SQL counts, `gh`,
`curl`); this session changed nothing on either server.

This repository is **public**: no IPs, phone numbers, keys or secrets here.

## 1. Why master split, and the fix

- 21 Oct, office: W10 (admin image upload, B45) and its docs were committed (`4439f0c`,
  `463b279`) and never pushed. Nothing else came from the office after `0317914`.
- 22–24 Oct, laptop: 20 commits on `origin/master` from the same base `0317914`, among them
  migration `0022_admin_totp`. The office's W10 carried `0022_media_assets` on the same
  parent, so a plain merge would have left two alembic heads (CI's `alembic upgrade head`
  fails on that). The handoff noticed "the missing W10" but listed B45 as unbuilt: an
  unpushed commit is invisible from the other machine.
- Fix, on branch `reconcile/2026-10-25` (local until the owner approves the push): W10
  replayed on `origin/master` with its migration renumbered `0023_media_assets` (one head
  again; the old id was never applied anywhere); both conflict sites keep both sides (TOTP
  view + Images page, leaderboard reader + media adapter); the fixes in §4 items 1 and 7;
  the docs truth pass. Gate: the full suite twice on a fresh PostgreSQL 16, 708 passed both
  times; ruff, format and mypy clean; `upgrade head` → `downgrade -1` → `upgrade head` OK;
  `nginx -t` passes for both environment configs.
- So it does not happen again: [CLAUDE.md](../../CLAUDE.md) "Two machines".

## 2. What is live (25 Oct)

| | Production | Staging |
|---|---|---|
| Backend (`/health`) | `8aada60` = `v2026.10.24-1` | `9bdfb0e` (master) |
| Server checkout of `deploy/` | `9bdfb0e`, moved by hand 24 Oct 02:13 UTC (not a release) | `9bdfb0e` |
| Alembic | `0022_admin_totp` | `0022_admin_totp` |
| Frontend | `5d4bd5c-20261025` (Arman's PR #25) | `29ad3f0-20261022` (PR #17) |
| `/admin` | every IP (`allow all;`), OTP rate limit on the whole panel | same |
| Admins / with TOTP | 3 / 0 | 3 / 0 (none on a test number) |
| Users / redeemed codes | 9 / 5 (all from the owner's smoke test) | 47 / 43 |
| Code batches | 8 active, 7 generated (bottle run), 7 void | 16 active, 15 void |
| Catalogues | 2 challenges; 0 lounges, achievements, avatars | 4 challenges, 3 achievements, 5 lounges, 0 avatars |
| Wallet invariant | 0 mismatches | 0 mismatches |
| Backups | every 6 h, all OK, same VM only | – |
| Alerts | not installed | not installed |

Production frontend: `index.html` and all 49 JS/CSS files are byte-identical to Arman's
accepted API artifact for PR #25 (artifact 12573057751, digest checked, `mode=api`, tested
commit `962b702`), and every `/api/v1` path the bundle calls exists on the production API.
Safe to keep running. It was never on staging, and no real phone has been through it.

## 3. Decisions on the 23 Oct handoff

Where an item is the owner's call, the text below is the office's recommendation; his later
word overrides it. §0, the owner's decisions of 23 Oct, stand. Decision 9 (logging) was merged and released on
24 Oct; accepted below (§2 item 4).

§2, found wrong or half-done:

1. Admin session secret: closed (rotated 23 Oct).
2. Alerts: still installed on neither host. The owner installs them on production with the
   `otp` template (his learning goal); done when the test SMS arrives. A dedicated alert
   template stays optional.
3. Stale database: fixed by PR #3 (`-x db_url`, target host printed). The office `.env`
   points at the same old Supabase pooler: the owner switches it to the local Docker
   Postgres. Recommended: delete the Supabase project; nothing needs it since the five demo
   lounges were copied to staging on 21 Oct (the 22 Oct writes to it were the mistake above).
4. Logging: keep the merged inline logging (B51). The defect named in the handoff is fixed
   and tested (`code_redeemed` is written after the commit;
   `test_a_failed_commit_never_logs_code_redeemed`). The office had no competing
   observability design beyond alerts (B26) and the `FactPublisher` idea of 14 Oct; domain
   events wait for a second consumer of the same facts.
5. Plaintext code files: unchanged, the owner's (the laptop copies and the password file go
   once Mehdi confirms; printer CSVs follow the chain of custody).
6. Admin allow-list: superseded by PR #9 (`allow all;`). Open access stays only if all three
   admins enroll TOTP; until then it is SMS alone from anywhere (§4 item 2). Arman's
   production admin role: ask him; default, demote him on production and keep staging.
7. 22 Oct report: errata in place; closed.
8. Origin TLS: still the self-signed certificate, expiring 17 Nov. Needs the Arvan DNS API
   token; due this week, at the latest by 10 Nov.
9. Tap Reflex best record: closed by L1 and `/me/stats`.
10. CI lesson: closed.
11. Git identities: the office writes `winenpot@gmail.com`; `crudyn@localhost` comes from
    the laptop. Set `user.email` in that clone.

§4, for the office:

- Forced TOTP enrollment: yes, now that `/admin` answers every IP. First, every admin
  enrolls (no code). Then a small task: after the SMS step, an admin without a confirmed
  secret is sent to `/admin/security/totp` before any other page (ADR-0013 option B). A QR
  code is not needed for three admins.
- Password manager: a KeePassXC file (fewest moving parts) on the office PC, plus an
  encrypted USB copy with the backup holder. Then the pepper moves in, and the laptop DPAPI
  copy, production's `.env.bak-20261020-1730` and `~/.lp-env-backups/` are shredded.
- Off-site backups: `scripts.backup_pull` on the office PC (it already reaches production
  over SSH) as a timer; prove a restore from the copy, including the truncated-dump negative
  test; record the RTO in OPERATIONS.md.
- Plans: reconciled by this file. `.hermes/` stays machine-local; whatever the other
  machine needs goes through `docs/launch-reports/`.
- Second SMS provider, atpg's SSH passwords, the printer handover and Mehdi's open items:
  unchanged, owners as in the handoff. Mehdi's IP is moot with `allow all;`.
- Product gaps: B18, B21, B22, B11 and B37 stay in Phase 2. B45 is built (this branch).

§5, leaderboard: accepted as built (B49); `features.leaderboard` stays off until Arman's
screen exists. §6, TOTP: accepted as built (B50); enrollment as above.

## 4. Found on 25 Oct

1. **The admin panel is broken by PR #9.** The player OTP zones (6/min, burst 3) cover all of
   `/admin`, `/admin/statics` included. Production's nginx log since 24 Oct: 20 of 34
   `/admin` requests and 18 of 21 static requests answered 429. Reproduced on nginx 1.27,
   fixed on the branch (only `/admin/login` POSTs count, zone `admin_login`), re-tested:
   a page with 20 statics all 200, the 5th rapid sign-in POST 429.
2. **`/admin` answers every IP and no admin has TOTP** (0 of 3 on both hosts). ADR-0008
   accepted SMS sign-in because the allow-list carried the weight; that no longer holds.
3. **Production's checkout was moved by hand** to `9bdfb0e` a minute after PR #9 merged, so
   the nginx change reached production without a release while the API stayed on
   `v2026.10.24-1`. Rule added to OPERATIONS.md; the next release puts the checkout back on a
   tag.
4. Production's checkout has a root-owned `docs/legal/` directory (since 19 Oct), so git
   cannot update the files in it: its `README.md` is the 19 Oct text. Harmless at runtime,
   but a release that touches that directory may fail. Fix, with the owner's OK:
   `sudo chown -R torshx:torshx <base>/repo`, then `git -C <base>/repo checkout -- docs/legal`.
5. Three frontend builds went to production in about 26 hours (24–25 Oct), none to staging.
   The current one is verified (§2). Next: the same artifact on staging, then staging first
   again.
6. Production's catalogues are almost empty, and nobody but the owner has scanned a code
   since launch (B52).
7. W10's `/media` regex failed `nginx -t` (an unquoted `{64}`), so the deploy would have
   refused W10. Fixed on the branch.
8. Docs drift, fixed on the branch: no CHANGELOG entries, no ARCHITECTURE update and no TODO
   rows for the 22–24 Oct work; SECURITY.md, OPERATIONS.md and ADR-0008 still described the
   allow-list; the ROADMAP had no post-launch status.
9. `docker-compose.yml` publishes the development Postgres on every interface
   (`5432:5432`). Docker bypasses ufw, so on an office or home network it is reachable with
   the default development password. Proposed: `127.0.0.1:5432:5432` (not on this branch).
10. Commits without a gitmoji or under `crudyn@localhost` stay in history; CI's commit-lint
    stops new ones.
11. Production's `/config` `privacy_url` is the terms page without `#privacy`, so the app's
    privacy link opens the top of the terms. Fix: the server `.env` value ends in `#privacy`
    (quoted), then recreate `api`.

## 5. Next, in order

| # | What | Who | Owner's OK |
|---|---|---|---|
| 1 | Push `reconcile/2026-10-25`, PR, CI green, merge: staging gets the panel fix and rehearses migration 0023 | agent | yes |
| 2 | Release tag after staging checks; production gets the fix, W10 and its checkout back on a tag | agent, owner approves | yes |
| 3 | Every admin enrolls TOTP on both hosts, or Arman is demoted on production | owner, Mehdi, Arman | – |
| 4 | Publish `5d4bd5c` on staging (same artifact as production), smoke it | agent | yes |
| 5 | Alerts on production, test SMS | owner | – |
| 6 | Production catalogues (B52): lounges by CLI; achievements, avatars and challenges in `/admin`; `PRIVACY_URL` anchor (§4 item 11) | agent + owner/Mehdi | yes (CLI, `.env`) |
| 7 | Staging basic auth (B53), due Mon 26 Oct | agent | yes |
| 8 | Origin TLS with acme.sh DNS-01, by 10 Nov | agent + owner (Arvan token) | yes |
| 9 | Off-site backup pull to the office PC; password manager | owner + agent | yes |
| 10 | Forced TOTP enrollment (B50); root-owned `docs/legal/` on production | agent | yes |
| 11 | Real-phone walk on staging with the current build (W4) | owner, Mehdi; Arman on his test numbers | – |

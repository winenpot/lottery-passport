---
type: findings
---

# Findings — technical investigations and measurements

Running log of anything measured, benchmarked, or externally verified
(as opposed to decisions, which live in [[Decisions]]). Each entry has a
date, a status, and a "→ fed into" pointer to the decision or doc it
updated.

Fill in placeholder entries as results come in. New entries go at the
top of their section.

---

## Production sizing

**Status: ESTIMATE ONLY — servers not yet inspected.**
Method and commands: `../ops/CAPACITY_PLANNING.md`.
Target: 40,000 registered users, 10,000 active at a spike.

### [ ] Step 1 — Server inventory (fill in after running the commands)

Date measured: ___

| | App server | DB server |
|---|---|---|
| Hostname / provider | | |
| vCPU / model | | |
| RAM | | |
| Disk type / size / free | | |
| Hypervisor (VM or bare metal) | | |
| Other projects sharing it | | |
| Private link + latency (ping -c 20) | | |

Verdict: ___

### [ ] Step 2 — Disk benchmarks (fio, off-hours)

Date measured: ___

| | App server | DB server |
|---|---|---|
| 4k randwrite+fsync IOPS | | |
| 4k randwrite+fsync latency (ms) | | |
| 8k 70/30 rw mixed IOPS | | |

Rule of thumb: 4k fsync > 2,000 IOPS and latency in the low ms is fine.
Below ~500 IOPS or tens of ms means network/HDD storage — a bottleneck.

Verdict: ___

### [ ] Step 3 — Monitoring (3–5 days, including a weekend)

Install: sysstat sampling 1/min or Netdata. See CAPACITY_PLANNING.md step 3.

| Day | Peak CPU% | Peak %steal | Min free RAM | Peak disk await (ms) | Peak net Mbit/s | Hour of peak |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

Key concern: %steal consistently > 5% means a noisy neighbour on the
VPS host; benchmark numbers will be unreliable at peak hours.

Verdict: ___

### [ ] Step 4 — Traffic model (agree with Mehdi and Arman)

Date agreed: ___

| Input | Value | Source |
|---|---|---|
| Registered users | 40,000 | user |
| Active at spike | 10,000 | user |
| Requests per active player per minute | ___ | count in Arman's demo Network tab |
| Peak req/s (active × rpm / 60) | ___ | computed |
| Scans per active user per day | ___ | Mehdi |
| Game rounds per active user per day | ___ | product |
| Spike shape (trigger + duration) | ___ | Mehdi/marketing |

Verdict (revised if current estimate of 1,000 req/s changes): ___

### [ ] Step 5 — k6 load test on staging (after redemption+games+boards are live)

Date run: ___  Hardware under test: ___

| Step | req/s | p50 (ms) | p95 (ms) | Error% | App CPU% | DB CPU% | DB disk await (ms) | DB conns |
|---|---|---|---|---|---|---|---|---|
| Ramp 1 | 250 | | | | | | | |
| Ramp 2 | 500 | | | | | | | |
| Ramp 3 | 1,000 | | | | | | | |
| Ramp 4 | 1,500 | | | | | | | |
| Soak 30 min | 1,000 | | | | | | | |

Pass criteria: p95 < 300 ms, error rate < 0.5%, CPU < 70%, DB await < 10 ms.

Top 5 slow queries from pg_stat_statements (fill in after test):

1. ___
2. ___
3. ___
4. ___
5. ___

Verdict: ___

### [ ] Step 6 — Backup restore drill (before launch)

Date run: ___  Backup tool: ___ (pgBackRest / WAL-G / manual)
Backup type tested: ___
Restore time (full): ___
Data loss window (RPO): ___

Pass criteria: restore time the business accepts for downtime during the prize phase.
If restore > 1–2 h and business does not accept it: add a hot standby (3rd server).

Verdict: ___

### → ADR 0010 (to be written after steps 5 and 6)

Final topology decision goes in `../adr/0010-production-server-topology.md`.
Current estimate (subject to measurements above):

- Test week: Render (API) + Supabase (DB).
- Domestic launch: 2 servers (app 4 vCPU/8 GB + DB 4 vCPU/16 GB NVMe) +
  continuous off-site WAL backups.
- Third server (hot standby): add only if step 6 restore time is unacceptable.

---

## Frontend demo review (2026-10-10)

**Status: COMPLETE.**
Demo URL: http://86.104.82.71:8000/ (Arman's test host, no HTTPS).
→ Fed into: `../API_CONTRACT.md` (full rewrite), [[Decisions]] entry 2026-10-10.

Findings:
- All state is mocked in the browser; no real API calls. Routes and mock
  data extracted from the JS bundle.
- Every demo screen now has a corresponding endpoint in API_CONTRACT.md
  (screen map + demo-to-contract migration table).
- QR host hard-coded as `torsh-x.com` with a hyphen — corrected to
  `torshx.com` and made configurable via build config.
- `identifier` field sent instead of `phone` in auth requests — backward-
  compat alias to be kept for one release.
- No terms-acceptance checkbox in sign-up step 3 — must be added.
- Missing reward/shop images on several cards.
- Notification badge misaligned on mobile.
- Mixed numeral systems (Arabic-Indic and Western) — needs one system chosen.
- Avatar list has no labels; horizontal scroll visible on desktop.
- Free-points economy (wheel + streak + games + challenges): ~200–300 pts/day
  with no purchases — too generous; needs balancing with Mehdi.

---

## HTTPS and cookie requirements for testing (2026-10-10)

**Status: DOCUMENTED — action pending (plan task F3).**
→ Fed into: `../API_CONTRACT.md` section "Hosts, CORS and cookies", rule 4.

Findings:
- A plain http://IP:port page cannot use the device camera (QR scanning),
  cannot autofill SMS OTPs (WebOTP API requires HTTPS), and Safari blocks
  cross-site cookies regardless.
- The current demo is fine for visual review but cannot test sign-in or scanning.
- Solution: host the frontend behind Caddy with auto-TLS on test.torshx.com,
  proxying /api to Render — same origin over HTTPS, no CORS needed.
- CORS_ORIGINS now set to ["http://86.104.82.71:8000","http://localhost:5173"]
  for development only; production will use same-origin proxy.

## Cross-site cookie + CSRF on the demo (2026-10-13)

**Status: VERIFIED on Render (curl, not a browser yet).**
→ Fed into: `../API_CONTRACT.md` "Hosts, CORS and cookies" rules 6-7, error `CSRF_REJECTED`.

- Arman (2026-10-13): CORS preflight OK from http://86.104.82.71:8000; local
  127.0.0.1:5173/5174 were rejected → added (with localhost) to Render CORS_ORIGINS.
- Default SameSite=Lax would not send the cookie cross-site → Render demo set to
  SESSION_COOKIE_SAMESITE=none (cookie: HttpOnly; Secure; SameSite=none).
- CSRF guard (579f8f1): cookie-carrying POST/PATCH/DELETE need X-Requested-With
  and an allowed Origin. Live check with test number 0969 000 0002 and Origin =
  demo: verify 200, GET /me 200, PATCH without header 403 CSRF_REJECTED, foreign
  origin 403, with header 200, preflight allows x-requested-with, logout 204.
- Still open: a real browser test by Arman (Chrome should work; Safari/Firefox
  strict/private may drop the third-party cookie). Lasting fix stays same-site
  hosting (test.torshx.com proxy, or play./api. subdomains).

---

## Instagram and X API availability (2026-10-10)

**Status: INVESTIGATED — decision made, bio-code verification chosen.**
→ Fed into: [[Decisions]] entry 2026-10-10, plan Phase S.

Findings:
- Instagram Basic Display API (personal accounts): shut down December 2024.
  Instagram Login API covers only Business/Creator accounts; requires Meta
  app review; most gamers have personal accounts.
- X (Twitter) API: paid beyond a very small free tier; requires a company
  developer account.
- Both platforms are filtered in Iran; a domestic server cannot reach them
  reliably for OAuth callbacks.
- Chosen approach: bio-code verification (player puts TX-XXXX in their
  bio; staff confirm in admin). Works for any public account, no vendor app.
  OAuth can replace it later without changing the API contract shapes.

---

## Placeholders (fill in as investigations happen)

### [ ] SMS gateway selection and pricing

Date investigated: ___
Candidates evaluated: ___
Price per OTP (IRR): ___  Delivery rate tested: ___
Failover gateway: ___
Iranian carrier blocking risk: ___
→ Will feed into: Mehdi's M-budget item and OPERATIONS.md.

### [ ] Domestic server provider selection

Date investigated: ___
Candidates (IaaS in Iran): ___
Selected provider: ___  DC location: ___
Committed specs (app server): ___  Committed specs (DB server): ___
SLA / uptime guarantee: ___
→ Will feed into: ADR 0010, OPERATIONS.md.

### [ ] PgBouncer configuration on production DB

Date validated: ___
Pooler mode used: session|transaction: ___
Pool size per app worker: ___  max_connections result: ___
Prepared statements: disabled|enabled (needs session mode): ___
→ Will feed into: OPERATIONS.md deploy checklist.

### [ ] Cross-site session cookie on the demo (flagged 2026-10-12)

Demo frontend `http://86.104.82.71:8000` calls the API on `https://lottery-passport.onrender.com`: different sites, so a `SameSite=lax` cookie may not be sent on fetches (login would succeed, `/me` would 401). Never tested end to end; CORS itself is allowed (`CORS_ORIGINS` on Render lists both origins; `demo` is exempt from the https rule).
Test: sign in from the demo frontend, then call `GET /api/v1/me` from it. Result: ___
Fix if it 401s: `SESSION_COOKIE_SAMESITE=none` (Chrome only) or, better, serve frontend and API from one origin (F3/Caddy). The cookie `Secure` flag is already on for `demo`.
→ Will feed into: API_CONTRACT "Hosts, CORS and cookies", F3.

### [ ] k6 and staging environment setup

Date ready: ___
Staging URL: ___
k6 runner machine: ___
Seed script location: ___  Row counts seeded: ___
→ Prerequisite for Step 5 above.

### [ ] Legal sign-off on PS5 draw and coin economy (CP5)

Date received: ___
Outcome: ___
FEATURE_DRAW flag: on|off in production: ___
→ Will feed into: ROADMAP CP5, plan task C2.

### [ ] Reward economy decision (with Mehdi, post DB-design)

Date decided: ___
Free points per day (wheel + streak + games + challenges): ___
Minimum scan-earned points to unlock physical rewards: ___
Delivery method: ___
→ Will feed into: GET /config limits, shop prices, admin challenge config.

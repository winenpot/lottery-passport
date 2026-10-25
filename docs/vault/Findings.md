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

**Status: ESTIMATE ONLY — atpg inventoried 2026-10-14, DB server not yet.**

2026-10-14 atpg: VMware VM, 8 vCPU, 15 GiB RAM (10 available), single 100 GB
disk (was 97% full; cleaned to 63% by truncating an unrotated 22 GB MongoDB
container log + build cache; Docker log rotation still missing), 29 near-idle
containers, load ~0.7. DB server (user-reported, not inspected): 8 vCPU /
16 GB / 250 GB VM, MongoDB for ~10 Flask apps + an empty Postgres.
Staging decided: Render + Supabase. Work plan and buy rule:
`.hermes/plans/2026-10-14_infra-capacity.md`.
Method and commands: `../ops/CAPACITY_PLANNING.md`.
Target: 40,000 registered users, 10,000 active at a spike.

### [ ] Step 1 — Server inventory (fill in after running the commands)

Date measured: 2026-10-18 (DB server, read-only; app server column still open)

| | App server | DB server |
|---|---|---|
| Hostname / provider | | own VMware VM (Ubuntu 24.04 desktop install) |
| vCPU / model | | 8 × Xeon E5-2680 v4 (2016) |
| RAM | | 15.6 GiB, 4 GiB swap file on the fast disk |
| Disk type / size / free | | sda 100 GB, 69 GB free, write await 0.5 ms; sdb 500 GB `/storage`, 373 GB free, daily avg await 119–180 ms (max 455 ms), holds Mongo + Postgres data |
| Hypervisor (VM or bare metal) | | VMware |
| Other projects sharing it | | MongoDB 8.2 for ~10 Flask apps (22 DBs, ~93 GB, 70 GB of it GridFS photos), empty Postgres 17, Portainer |
| Private link + latency (ping -c 20) | | none; same public segment as atpg, 0.34 ms |

Verdict: CPU and RAM idle (CPU peak 10 %, ≥ 9.1 GB available every day,
no OOM kills). The bottleneck is sdb latency: Mongo's slow-op log over ~6 days
holds 20,418 ops > 100 ms, led by GridFS photo chunk INSERTS (9,227, median
160 ms) and log inserts (7,427, median 185 ms). Every write waits for a journal
fsync on sdb (default write concern `majority` on a replica set). Memory limits
or restarts cannot fix it; moving sdb to a faster datastore can. Detail and plan:
`.hermes/plans/2026-10-18_1450-db-server-audit.md` (gitignored).

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

## Client IP behind Render (2026-10-13)

**Status: FIXED on the demo (FORWARDED_ALLOW_IPS), verified in Render logs.**

- Before: every request logged `client_ip` 10.x (Render's proxy), so the in-process
  rate limit (60/min) was one shared bucket for all testers.
- Chain seen in `forwarded_for`: `<client>, <Cloudflare edge>, <Render 10.x>`; the
  direct peer of uvicorn is 127.0.0.1. Fix: trust 127.0.0.1, 10.0.0.0/8 and
  Cloudflare's published ranges; uvicorn then returns the right-most untrusted
  address = the real client. A spoofed `X-Forwarded-For: 9.9.9.9` is ignored.
- The Cloudflare list can change (cloudflare.com/ips-v4, ips-v6): if client_ip
  turns into a 104.x/172.x address again, refresh the value in render.yaml and
  on Render. Production behind our own nginx only needs the nginx address.
- /ready takes 17-24 ms server-side (Render logs), so Frankfurt API <-> Supabase is
  fast; the ~1 s seen from outside is network and TLS, not the database.

## Logging: tools and plain-file sizing (2026-10-13)

**Status: INVESTIGATED — decision in plan C3.**

- Today: JSON lines to stdout (app/core/logging.py): timestamp, level, logger,
  request_id, method, path, status, latency_ms, client_ip. SMS logs mask phones.
- Render: dashboard log explorer, Hobby retention 7 days, max 6,000 app log
  lines/min per instance (excess dropped). Log streams: syslog/HTTPS to Better
  Stack, Papertrail, Datadog, etc. (render.com/docs/logging, /log-streams).
- Free tools: Better Stack free 3 GB logs/month, 3-day retention, 100k
  exceptions; Grafana Cloud free 50 GB/month, 14 days (not a direct Render
  syslog target). Foreign SaaS is risky for the domestic production server
  (sanctions, filtering): production should not depend on it.
- Plain files at 1M users: volume scales with requests, not users. Assume
  100-200k daily actives x ~30 requests = 3-6M lines/day x ~260 B = 0.8-1.6 GB/day
  raw, ~0.1-0.2 GB gzipped; peak ~500-1,000 lines/s (~0.3 MB/s). Writing and
  storing that as text is trivial; grep over one day takes seconds. Text files
  do not give alerts or dashboards: pair with uptime checks and an error
  tracker (B26). Logs hold phone (masked) and IPs: set a retention limit.
- Gap: deploy/compose.prod.yml json-file 20m x 5 keeps only ~100 MB per
  container, about 2 hours at that peak. Raise it or rotate to daily files.

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

## Launch week, Mon 19 Oct 2026

### OTP SMS never left production (incident, fixed 16:24)

- Symptom: production issued codes (`otp_issued` in the logs) but no SMS arrived.
- Mechanism: `deploy/server/firewall.sh` puts the LP-ORIGIN chain in DOCKER-USER and
  matched only `--ctorigdstport 443`. DOCKER-USER also sees the containers' OUTBOUND
  forwarded traffic, so the API's HTTPS call to api.kavenegar.com was dropped like an
  unwanted inbound hit (the DROP rule had counted 46,099 packets / 2.7 MB). Proof: curl from
  the host worked, `urlopen` from the API container timed out, DNS resolved, and 1.1.1.1
  timed out too = all container egress on 443, not a Kavenegar problem.
- Fix 6769254: every LP-ORIGIN rule scoped to the external interface (`-i ens33`, detected
  from the default route, `LP_EXT_IFACE` override). Verified: container -> Kavenegar in
  0.3 s, inbound still Arvan-only.
- Probably broken since the firewall first went live on production; nothing alerted
  because monitoring (L16) does not exist yet.
- Follow-up cost: the fixed script was also copied by hand into both servers' checked-out
  repos. The pull-based deploy's `git checkout` refuses local changes, so staging deploys
  failed for ~20 min (cb8da59) and the first production attempt of `v2026.10.19-1` (18:59)
  rolled back. Restored the file and re-ran the deploy by hand at 19:07. Rule: never edit a
  tracked file inside a server checkout.

### Unusual phone prefixes reached Kavenegar

- `normalize_iranian_mobile` checked the shape only, so any 09xx-shaped number caused a
  paid SMS attempt.
- a570468: `422 PHONE_UNUSUAL` before any SMS when the prefix is outside the known list
  (900-905, 910-919, 920-923, 930-939, 941, 955, 971, 990-994, 998, 999); 0969 test numbers
  pass only where test numbers are enabled. Soft check (the CRA can allocate new ranges):
  if a real player is refused, add the prefix to `KNOWN_MOBILE_PREFIXES`. Live on production
  since 19:07 (a 0940 number answers 422).
- Side effect: test helpers that drew a blind random +989 number now fail ~60% of runs;
  all of them use +98912 now (dabe3fb).

### Terms deadlock on production (plan N1)

- Production requires terms (the config validator refuses `TERMS_REQUIRED=false` there),
  the frontend hides them (`TERMS_REQUIREMENTS_ENABLED=false`) and never sends
  `accept_terms_version`: the nickname PATCH succeeds, `profile_complete` stays false and
  the app shows «تکمیل ثبت‌نام هنوز از طرف سرویس فعال نشده است». Every new production
  player is blocked at setup.
- Path: first draft `docs/legal/terms-2026-10-20.fa.md` (6578756, 6cc50c6), then plan LG1
  (serve it) and LG3 (Arman's switch). Fallback R11, Wed 12:00.

### Frontend release fa97809 (19 Oct)

- The right artifact was PR #3's own CI run (head fa97809, tree identical to merge commit
  01c4a916c); the run on the `main` head built nothing (build reuse). Artifact 12171858467,
  zip sha256 5608e187...a9; on both servers as release `fa97809-20261019`.
- The build calls 8 endpoints only (auth request/verify/logout, config, me, me/passports,
  me/wallet, redemptions): no mini-game runs, and the terms/privacy URLs are empty constants
  rather than `/config` values. Sent to Arman.

### Production release v2026.10.19-1 (949c282), live 19:07

- Migration 0018 applied. Read-only smoke: /health and /ready 200, anonymous /me 401,
  /admin 403, non-Iranian number 422 PHONE_INVALID, 0940 number 422 PHONE_UNUSUAL, own-origin
  preflight 200, foreign origin 400; API container -> Kavenegar 200 in 0.27 s;
  `SESSION_COOKIE_NAME=__Host-lp_session` active.
- The L0' compose change recreated postgres and nginx: ~10-20 s of downtime.
- torshx disk (`pg_test_fsync` in the postgres container, L0'): fdatasync 4,695 ops/s,
  213 us per 8 kB sync, SSD-class, no action.

## Launch week, Tue 20 Oct 2026

### Frontend auto-deploy: main never carries the real artifact (ADR-0012 investigation)

- Confirms the 19 Oct release note above (`tree identical to merge commit`, "build
  reuse") with the actual mechanism: a main-push run of Arman's "Frontend CI" produces
  only `release-plan.json` (his own schema: `risk`, `scopes`, `reasons`,
  `source.commit`/`source.tree`, `baseCommit`, `changedPaths`), not `frontend-normal`.
  Checked 4 consecutive main pushes (01c4a916, 419e728, 45a80f4, 640555e): zero carried
  the bundle. It flags nearly any real change `risk: critical` / `"...: fail closed"`
  (e.g. `AGENTS.md`, `vite.config.ts`, `src/v2/api.ts`). The buildable artifact exists
  only on the originating PR's own `pull_request`-event run.
- Blocks turning on `lp-frontend-deploy.timer` (staging-only CD, ADR-0012): the agent
  is written and dry-run tested against the real API (correctly finds the newest run,
  fails safe when nothing to deploy), but doesn't yet know how to resolve a main commit
  to the PR run that built it. Asked Arman what `release-plan.json`'s contract is
  (`.hermes/plans/2026-10-20_messages.md`, 11:05 delta).
- → fed into: ADR-0012 "Open question".
- → answered later by Arman's `resolved-build` receipt (his
  `docs/RESOLVED-BUILD-CONTRACT.md`), which names the accepted artifact of each green
  main run; the 25 Oct check of production's `5d4bd5c` used it.

### L4: staging test codes for Arman (3 flavors x 8) + smoke batch (5)

- First attempt lost all plaintext: `compose.sh run --rm api ...` (no volume) writes the
  CSV into the throwaway container's own filesystem, gone the instant `--rm` removes it.
  The DB rows (hashes only) survived, so those 4 batches became permanently unredeemable
  by anyone — voided (no leak: HMAC only, nothing plaintext ever left).
- `docs/OPERATIONS.md`'s documented command (`--user 0 -v $PWD/var:/out`) is the one that
  actually works: the api image runs as uid 999, and `/root` itself isn't traversable by
  it, so `/root/batches` fails on permission even with the bind-mounted subdir owned
  correctly — the parent directory, not the mount point, was the blocker.
- End-to-end verified on the origin (disposable 0969 account, real `/api/v1/redemptions`
  call, not just `check_code`): redeeming one smoke-batch code → `200 coins_awarded=100
  bonus_awarded=50 replayed=false`; redeeming the same code again on the same account →
  `200 replayed=true coins_awarded=100` (no second entry). Matches exactly what was
  described to Arman this morning.
- Live batches: `fcd7f40c` (PR, 5, smoke), `a2c820ae` (PR, 8), `8822caf6` (TO, 8, one
  code spent by this verification), `8ce6972f` (MO, 8). CSVs on atpg:
  `/home/data/lottery-passport/var/{smoke,arman-paris,arman-tokyo,arman-moscow}-20261020.csv`.



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

# Operations (DevOps)

How to set up, deploy, back up, watch and fix the platform. Written for a developer who is new
to Docker and servers: every step is a command you can copy. Files referenced here live in
[`deploy/`](../deploy/).

## Contents

- [Environments](#environments)
- [Server setup (once per VM)](#server-setup-once-per-vm)
- [Getting images and packages onto the server](#getting-images-and-packages-onto-the-server)
- [nginx](#nginx)
- [TLS certificates](#tls-certificates)
- [Deploying a release](#deploying-a-release)
- [Code batches in production](#code-batches-in-production)
- [SMS provider](#sms-provider)
- [Backups and restore](#backups-and-restore)
- [Monitoring and alerts](#monitoring-and-alerts)
- [Daily checks](#daily-checks)
- [Runbooks](#runbooks)
- [Launch checklist](#launch-checklist)

## Environments

| | Local | Staging | Production |
|---|---|---|---|
| Where | Your laptop | Domestic VM, 2 vCPU / 4 GB / 40 GB | Domestic VM, 4 vCPU / 8 GB / 80 GB SSD |
| URL | `http://localhost:8000` | `https://staging.play.<domain>` | `https://play.<domain>` |
| Database | Compose `postgres` (dev data) | Its own PostgreSQL, test data only | Its own PostgreSQL |
| Codes | Generated test batches | Test batches only, **never printed** | Printed batches |
| Pepper | Dev value | Its own value | Production value (password manager) |
| SMS | Console sender (prints to logs) | Real provider, limited to team numbers if the provider allows | Real providers |

On staging and production the app refuses to start if `CORS_ORIGINS` contains `*` or a non-https origin (`http://localhost` is the only exception), or if `PUBLIC_APP_ORIGIN` is not https. `SESSION_COOKIE_SAMESITE` stays `lax` (same-origin proxy); `none` is for a cross-site frontend, needs Secure cookies and works in Chrome only.

Staging and production never share a database, secrets or a pepper. Codes generated on staging can never work in production.

## Server setup (once per VM)

Assumes Ubuntu Server 24.04 LTS. Run as root (or with `sudo`).

```bash
# 1. Updates, firewall, time
apt-get update && apt-get -y upgrade
apt-get -y install ufw unattended-upgrades git curl restic
ufw default deny incoming && ufw default allow outgoing
ufw allow from <your-office-or-vpn-ip> to any port 22 proto tcp
ufw allow 80/tcp && ufw allow 443/tcp
ufw enable
timedatectl set-timezone UTC            # the server runs in UTC; Tehran time is an app setting

# 2. SSH: keys only (after you have copied your public key and tested a second login)
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh

# 3. Docker Engine with the Compose plugin: install from your provider's mirror of
#    Docker's apt repository, or Ubuntu's own packages if the mirror is unavailable.
#    Then point Docker Hub pulls at a domestic mirror (next section).

# 4. Directories
mkdir -p /opt/lottery-passport /etc/lottery-passport/{tls,nginx} /srv/lottery-passport/{releases,acme}
chmod 700 /etc/lottery-passport

# 5. Code (read-only deploy key on the GitHub repository)
git clone git@github.com:winenpot/lottery-passport.git /opt/lottery-passport

# 6. Configuration
cp /opt/lottery-passport/deploy/.env.production.example /opt/lottery-passport/deploy/.env
chmod 600 /opt/lottery-passport/deploy/.env       # fill in every CHANGE value
cp /opt/lottery-passport/deploy/site-examples/*.conf /etc/lottery-passport/nginx/
```

Check that Ubuntu's clock is synchronized (`timedatectl`). If international NTP servers are
unreachable, configure the domestic NTP servers your provider documents.

## Getting images and packages onto the server

Docker Hub refuses Iranian IP addresses, and other foreign registries can be blocked or slow.

- **Base images** (`python`, `postgres`, `nginx`): configure a domestic Docker Hub mirror in `/etc/docker/daemon.json` (several Iranian cloud providers run one; take the hostname from your provider's documentation), then `systemctl restart docker`:
  ```json
  {"registry-mirrors": ["https://<mirror-hostname-from-your-provider>"]}
  ```
  If no mirror works, pull on a machine that can, then `docker save postgres:16-bookworm | gzip > pg.tar.gz`, copy it, and `docker load < pg.tar.gz` on the server.
- **Pin images by digest** after the first successful pull (`docker images --digests`), so a mirror cannot hand you something else later.
- **Python packages**: the image installs `requirements.txt`, exported from `uv.lock` **with hashes**. Set `PIP_INDEX_URL` in `deploy/.env` to a PyPI mirror if PyPI is slow; pip rejects any file whose hash differs, so the mirror does not need to be trusted. Regenerate the file whenever dependencies change: `uv export --locked --no-default-groups --no-emit-project --no-header --format requirements-txt -o requirements.txt` (CI fails if you forget).
- **Frontend**: Arman builds `dist/` on his machine (or in CI) and you copy the files; the server never runs `npm`.

## nginx

[`deploy/nginx/nginx.conf`](../deploy/nginx/nginx.conf) does five jobs:

1. **TLS and redirects**: HTTP → HTTPS, TLS 1.2/1.3, HSTS.
2. **The PWA**: serves `/srv/lottery-passport/pwa` (a symlink to the current release of Arman's `dist/`); `/assets/*` cached for a year, `index.html` never cached, unknown paths fall back to `index.html` (client-side routes like `/b/<code>` and `/q/<venue>/<date>`).
3. **The API**: `/api/` proxied to the FastAPI container with timeouts; the client IP is **overwritten** into `X-Forwarded-For` so it cannot be spoofed.
4. **Rate limits**: 10 requests/s per IP for the API, 6/min for OTP requests. **Lounge IPs** (listed in `/etc/lottery-passport/nginx/lounge_ips.conf`) get 300/s and 120/min because a whole lounge shares one public IP. Over the limit: `429` with the standard JSON error.
5. **Privacy and admin**: `/b/<code>` is logged as `/b/[redacted]` and `/q/<venue>/<date>/<token>` as `/q/[redacted]`; `/admin` only from IPs in `admin_allow.conf`; `/docs` and `/openapi.json` return 404.

Gotcha built into the file: an `add_header` inside a `location` **replaces** all server-level
headers, so every such location includes `snippets/security_headers.conf` again.

After any change: `docker compose -f deploy/compose.prod.yml exec nginx nginx -t && docker compose -f deploy/compose.prod.yml exec nginx nginx -s reload`.

## TLS certificates

Put `fullchain.pem` and `privkey.pem` in `/etc/lottery-passport/tls/` (mode 600). Two options:

- **Let's Encrypt** with `certbot certonly --webroot -w /srv/lottery-passport/acme -d play.<domain>`, then copy or symlink the files and reload nginx from a renewal hook. Renewal needs international connectivity; certificates last 90 days and certbot renews 30 days early, so a short disruption is survivable. Monitor expiry anyway.
- **A certificate from your hosting/CDN provider** if they issue one domestically.

## Deploying a release

Releases are git tags: `v2026.10.12-1` (date + counter).

```bash
# on your machine, after CI is green on main
git tag v2026.10.12-1 && git push origin v2026.10.12-1

# on the server
sudo /opt/lottery-passport/deploy/deploy.sh v2026.10.12-1
```

[`deploy.sh`](../deploy/deploy.sh) checks out the tag, builds the image, starts PostgreSQL,
runs `alembic upgrade head`, restarts the stack and waits for `/ready`.

**Rollback**: `sudo deploy/deploy.sh <previous tag>`. This is safe only because of one rule:
**during the campaign, migrations are additive** (new tables, new nullable columns, new indexes
created `CONCURRENTLY`). Renames and drops use expand → migrate → contract across two releases.

**Frontend release** (each release in its own directory; `pwa` is a symlink switched atomically):

```bash
# from Arman's machine or CI, after `npm ci && npm run build`
rsync -a --delete dist/ deploy@server:/srv/lottery-passport/releases/2026-10-12-1/

# on the server: renaming a symlink is atomic, so no request sees a half-copied site
cd /srv/lottery-passport
ln -sfn releases/2026-10-12-1 pwa.next && mv -T pwa.next pwa
# rollback: the same two commands with the previous release directory
```

No nginx restart is needed: the Compose file mounts the parent directory
`/srv/lottery-passport`, so nginx resolves `pwa` on every request. (Mounting `pwa` itself would
pin the old directory until nginx restarts.) The first time, make sure `pwa` does not exist as
a plain directory, or `mv -T` cannot replace it.

## Code batches in production

Generate print batches **on the production server**, so the pepper never leaves it:

```bash
cd /opt/lottery-passport/deploy
install -d -m 700 /root/batches
docker compose -f compose.prod.yml run --rm --user 0 -v /root/batches:/out api \
  python -m scripts.generate_codes --city tokyo --quantity 50000 --coins-per-code 10 \
  --label "Tokyo can run 1" --base-url https://play.<domain> --output /out/tokyo-run1.csv
docker compose -f compose.prod.yml run --rm api python -m scripts.code_batches list
```

Then follow [CODES.md](CODES.md#handing-codes-to-the-printer): encrypt, send, confirm the
checksum, delete. At launch: `python -m scripts.code_batches activate <batch-id>`. To kill a
leaked batch: `python -m scripts.code_batches void <batch-id>` (seconds; redeemed codes stay redeemed).

## Staff accounts

There is no "first admin" API route by design (a player can never promote themselves).
Sign up normally (so the account exists), then promote it directly on the database:

```bash
docker compose -f compose.prod.yml run --rm api python -m scripts.admins promote <identifier>
docker compose -f compose.prod.yml run --rm api python -m scripts.admins list
docker compose -f compose.prod.yml run --rm api python -m scripts.admins demote <identifier>
```

`<identifier>` is whatever the account signed up with (an E.164 phone number, e.g.
`+989123456789`). The admin then signs in at `/admin` with that number (SMS code;
on the demo a 0969 test number shows the code on the page). `app/api/deps.require_admin`
guards admin-only API routes.

## SMS provider

Live: `app/infrastructure/sms.py` -- `KavenegarSmsSender` calls Kavenegar's
`verify/lookup` route (stdlib `urllib`, no SDK dependency) when
`KAVENEGAR_OTP_API_KEY` is set; otherwise `ConsoleSmsSender` just logs the code
(default in development and the test suite, no network call).

- Open accounts with **two** Iranian SMS providers under the company (they need company documents; Mehdi item M09).
- Use the provider's **OTP / verify (template) route**, not bulk messaging: templates are pre-approved, delivered on a priority route, and not blocked by users' advertising opt-outs.
- One env var per purpose, not one shared template: `KAVENEGAR_TEMPLATE_LOGIN` and
  `KAVENEGAR_TEMPLATE_SIGNUP` (first-time number uses signup, a returning number
  uses login). Vendor template approval is per-template and can lag independently --
  a rejected template for one purpose does not block the other; point the env var at
  an already-approved template and swap it back with no deploy once the real one is
  approved.
- Template text (ask the provider to approve exactly this shape; the last line is what enables autofill):

  ```text
  کد ورود شما: %token

  @play.<domain> #%token
  ```

  If the provider does not allow the same token twice, send the code in two parameters. After approval, **send a real one to an Android phone and an iPhone**: if the provider appends anything after the last line (an opt-out text, a signature), autofill silently stops working.
- `KAVENEGAR_OTP_API_KEY` goes in `.env`. It sits in the request URL (Kavenegar's own
  API shape); `KavenegarSmsSender` never logs the URL, only the masked phone and the
  HTTP status/response body on failure.
- Monitor credit and the failure rate (below); set a daily spend alarm with the provider if they offer one.

## Backups and restore

**What**: PostgreSQL only (everything important is in it). Code and configuration are in git and the password manager.
**How**: [`backup.sh`](../deploy/backup.sh) every 6 hours: `pg_dump` to a local file, verify it with `pg_restore --list`, upload to an encrypted **restic** repository on another provider's object storage, prune old snapshots once a day, ping a heartbeat monitor.
**Targets**: RPO 6 hours; RTO 2 hours (new VM + restore + deploy), proven by the drill.

```bash
# once
cp /opt/lottery-passport/deploy/backup.env.example /opt/lottery-passport/deploy/backup.env
chmod 600 /opt/lottery-passport/deploy/backup.env              # fill it in
head -c 32 /dev/urandom | base64 > /etc/lottery-passport/restic-password
chmod 600 /etc/lottery-passport/restic-password                 # copy it to the password manager NOW
set -a; source /opt/lottery-passport/deploy/backup.env; set +a; restic init
crontab -e   # add: 0 */6 * * * /opt/lottery-passport/deploy/backup.sh >> /var/log/lottery-passport-backup.log 2>&1

# weekly (and before launch): restore drill into a throwaway container
/opt/lottery-passport/deploy/restore_check.sh
```

`restore_check.sh` restores the latest snapshot into a temporary PostgreSQL container, counts
users and codes, checks that **every wallet equals the sum of its ledger**, and prints how long
it took. Write the time in the table below after each drill.

| Date | Snapshot | Restore time | Result | By |
|---|---|---|---|---|
| | | | | |

**Full restore onto a new VM**: server setup → copy `deploy/.env` and `backup.env` from the
password manager → `docker compose up -d --wait postgres` → `restic dump --tag db latest <DUMP_DIR>/lottery_passport.dump > db.dump`
→ `docker compose exec -T postgres pg_restore -U <user> -d <db> --clean --if-exists --no-owner < db.dump`
→ `deploy.sh <current tag>` → point DNS at the new IP.

## Monitoring and alerts

Keep it to what someone will act on.

| Check | Tool | Alert when |
|---|---|---|
| `https://play.<domain>/health` and `/ready` | Uptime Kuma on a **different** VM/provider | 2 failures in a row |
| TLS certificate expiry | Uptime Kuma | under 14 days |
| Backups ran | Uptime Kuma push (heartbeat) from `backup.sh` | no ping for 7 hours |
| Errors (500s, exceptions) | GlitchTip (self-hosted, Sentry-compatible) or `docker compose logs api` grep | new error type, or more than 10/min |
| Disk, CPU, memory | Uptime Kuma or the provider's panel | disk over 80% |
| SMS: credit, failures, job queue age | small script pushing to Uptime Kuma (B26) | credit under 3 days of usage; OTP job older than 60 s |
| Abuse: `CODE_INVALID` rate, OTP requests per hour | log query or admin report (B26) | 5x the normal rate |

### Reading the logs

The API writes one JSON object per line to stdout (`LOG_JSON=true`). Fields: `timestamp`,
`level`, `logger`, `message` (the event name), and when relevant `request_id`, `method`,
`path`, `status_code`, `latency_ms`, `client_ip`, `error_code`, `reason`, `phone` (always
masked, `+98912***6789`), `purpose`, `delivery`, `user_id`, `origin`. Only these fields are
written; a test proves that OTP codes, session tokens and full phone numbers never are.

| Event (`message`) | Level | Meaning |
|---|---|---|
| `request_completed` | info | Every request; `error_code` is set when we answered with an error envelope |
| `otp_issued` | info | Code created; `delivery` is `sms` or `test_number` (demo only) |
| `otp_request_blocked` | info/warn | `reason`: `cooldown`, `daily_limit`, `inactive_account` |
| `otp_delivery_failed` | warn | The SMS provider failed |
| `otp_verify_failed` | warn | `reason`: `wrong_code`, `no_active_code`, `attempts_exhausted`, `code_already_used`, `unknown_or_inactive_user` |
| `sign_in_succeeded` | info | Session created |
| `csrf_rejected` | warn | A cookie write without `X-Requested-With` or from a foreign `Origin` |

A user's `request_id` (from an error body or the `X-Request-ID` header) finds the exact line.

- **Render demo**: dashboard, service, Logs (search the `request_id`); live tail with
  `render logs` (Render CLI). Hobby workspaces keep 7 days; over 6,000 lines a minute per
  instance are dropped. Optional: a Log Stream to Better Stack (free: 3 GB a month, 3 days).
- **Production VM**: `docker compose logs api --since 1h | grep csrf_rejected`. Size: roughly
  1 GB a day uncompressed at 100k daily players, so plain files are enough for search; keep them
  with daily rotation and gzip (the Docker default of `20m x 5` holds only about two hours at
  peak), and decide how long phone and IP data may be kept.

Alerts go to **SMS and email**. Do not rely on Telegram for alerts: it is filtered in Iran and a
domestic server cannot reach its API. Self-host error tracking: foreign SaaS may be unreachable
or refuse Iranian traffic.

## Daily checks

Five minutes, every morning during the campaign (and after any incident):

```sql
-- 1. Wallets equal their ledger (expect 0 rows)
SELECT w.user_id, w.balance, coalesce(l.total, 0) AS ledger
FROM wallets w
LEFT JOIN (SELECT user_id, sum(amount) AS total FROM coin_ledger_entries GROUP BY user_id) l USING (user_id)
WHERE w.balance <> coalesce(l.total, 0);

-- 2. Yesterday's coins by reason and admin adjustments by person (insider check)
SELECT reason, count(*), sum(amount) FROM coin_ledger_entries
WHERE created_at >= now() - interval '1 day' GROUP BY reason;
SELECT actor_id, count(*), sum(amount) FROM coin_ledger_entries
WHERE reason = 'admin_adjustment' AND created_at >= now() - interval '1 day' GROUP BY actor_id;

-- 2b. Admin panel audit trail (who changed what; audit_log is append-only, see
-- migration 0012). Lounge edits: entity = 'venue-model'; coin adjustments:
-- entity = 'coin_ledger_entry', entity_id = the player's user id.
SELECT actor_user_id, action, entity, entity_id, changes, created_at
FROM audit_log WHERE created_at >= now() - interval '1 day' ORDER BY created_at DESC;

-- 3. Redemptions per city and per hour (sudden spikes = leak or harvesting)
SELECT city, date_trunc('hour', redeemed_at) AS hour, count(*) FROM redemption_codes
WHERE redeemed_at >= now() - interval '1 day' GROUP BY 1, 2 ORDER BY 2 DESC, 3 DESC LIMIT 20;

-- 4. Heaviest redeemers today (account farming shows up here)
SELECT redeemed_by_user_id, count(*) FROM redemption_codes
WHERE redeemed_at >= now() - interval '1 day' GROUP BY 1 ORDER BY 2 DESC LIMIT 20;
```

Also: last backup time, approvals queue older than 24 hours (Mehdi), SMS credit.

## Runbooks

Each runbook: symptoms, steps, rollback, who to tell. Severity: **SEV1** = nobody can sign in or
redeem, or data integrity is in doubt; **SEV2** = degraded; **SEV3** = cosmetic.

### Runbook: SMS provider outage

- **Symptoms**: players report no SMS; OTP job queue age rising; worker logs show provider errors or timeouts.
- **Steps**: check the provider's status page/support; confirm the worker switched to provider B (logs); if both fail, check the outbound network from the VM (`curl -I https://<provider-api-host>`); if the outage is long, post a notice on Instagram and the lounge screens. Existing sessions keep working, so redemption continues for signed-in players.
- **Do not**: raise retry counts or restart the worker in a loop (it multiplies load on a struggling provider).
- **Tell**: Mehdi (player comms) if over 15 minutes.

### Runbook: database down or disk full

- **Symptoms**: `/ready` fails; API returns 503; logs show connection errors or `No space left on device`.
- **Steps**: `df -h` and `docker system df`; free space safely (`docker image prune` for old images; rotate logs; never delete PostgreSQL data files); `docker compose -f deploy/compose.prod.yml logs --tail=200 postgres`; restart PostgreSQL only after space is free. If the volume is corrupted: restore (above).
- **Tell**: CEO and Mehdi if SEV1 over 15 minutes.

### Runbook: overload or attack

- **Symptoms**: latency high, many 429/5xx, CPU or connections saturated.
- **Steps**: find the source (`docker compose logs nginx | awk '{print $1}' | sort | uniq -c | sort -rn | head`); block abusive IPs in nginx or the firewall; tighten the `limit_req` rates; ask the provider/CDN for DDoS filtering if it is volumetric.
- **If the system stays down after the attack stops** (a retry storm keeps it saturated): **drop load first** (temporarily return 503 at nginx for `/api/` except `/health`), let the API and database recover, then reopen gradually. Restarting alone does not fix this; the backlog hits the fresh process immediately.

### Runbook: suspected code leak

- **Symptoms**: redemptions for a batch before its products are on sale; a spike from a few accounts or non-lounge IPs; codes posted online.
- **Steps (minutes count)**: `python -m scripts.code_batches void <batch-id>`; list who redeemed from that batch since the suspected leak; freeze (do not delete) their coins pending review; find the leak path (printer file, factory, internal); decide with Mehdi whether to reprint with a new batch.
- **Tell**: Mehdi and the CEO immediately; legal if prizes are affected.

### Runbook: bad deploy

- **Symptoms**: errors right after a release.
- **Steps**: `sudo deploy/deploy.sh <previous tag>`; confirm `/ready`; then investigate on staging. Never "fix forward" on production during lounge peak hours.

### Runbook: lost admin access

- **Steps**: from the server, create a new owner account with the admin management command (B20); revoke the lost account; check the audit log for actions after the loss.

## Launch checklist

**Date:** D15, Wed 21 Oct 2026 | **Deployer:** you | **Approvers:** CEO, Mehdi

### Pre-deploy

- [ ] CI green on the release tag (lint, types, tests, image build)
- [ ] Migrations ran on staging with production-like data; they are additive
- [ ] [Security checklist](SECURITY.md#pre-launch-security-checklist) done
- [ ] Restore drill done this week; time recorded
- [ ] Load test done at 5x expected peak ([TESTING.md](TESTING.md#load-test))
- [ ] SMS: both providers tested from production on Android and iPhone; credit for at least 2 weeks
- [ ] Batches for launch generated, printed, QC-checked; still `generated` (not active)
- [ ] Lounge IPs in `lounge_ips.conf`; admin IPs in `admin_allow.conf`
- [ ] Alerts tested end to end (each one reached a phone)
- [ ] Mehdi and lounge staff trained; support channel staffed
- [ ] Rollback plan: previous tag noted here: `________`

### Deploy

- [ ] `deploy.sh <tag>`; `/ready` OK
- [ ] Smoke test on a real phone: sign in, redeem a code from a **test batch**, see passport and wallet, claim a challenge, leaderboard loads
- [ ] Activate the launch batches (`code_batches activate`)
- [ ] One real printed code redeemed by a team member, then that redemption noted
- [ ] Watch errors and latency for 30 minutes

### Post-deploy

- [ ] Metrics nominal; daily checks run once
- [ ] CHANGELOG updated; release noted in the board
- [ ] CEO, Mehdi, lounges told it is live

### Rollback triggers (decided now, not during the incident)

- Error rate above 2% of API requests for 5 minutes
- p99 latency of `POST /redemptions` above 2 s for 5 minutes
- Any sign of double crediting (daily check 1 returns rows), or redemption of an inactive batch
- SMS sign-in failing for more than 15 minutes with both providers

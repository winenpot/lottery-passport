# Operations (DevOps)

How to set up, deploy, back up, watch and fix the platform. Written for a developer who is new
to Docker and servers: every step is a command you can copy. Files referenced here live in
[`deploy/`](../deploy/).

## Contents

- [Environments](#environments)
- [How a change reaches a server](#how-a-change-reaches-a-server)
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
| Where | Your laptop | atpg (shared app server), `<base>=/home/data/lottery-passport` | Own VM, 4 vCPU / 8 GB / 100 GB, `<base>=/opt/lottery-passport` |
| URL | `http://localhost:8000` | `https://staging.torshx.com` (Arvan -> atpg:8098, http) | `https://play.torshx.com` (Arvan -> VM:443, https) |
| Deploys | `uv run` | Automatically, every master commit that passes CI | A tagged release after your approval in GitHub |
| Database | Compose `postgres` (dev data) | Its own PostgreSQL container, test data only | Its own PostgreSQL container |
| Codes | Generated test batches | Test batches only, **never printed** | Printed batches |
| Pepper | Dev value | Its own value | Production value (password manager) |
| SMS | Console sender (prints to logs) | Real, only to `OTP_ALLOWED_PHONES`; `0969` test numbers | Real, anyone |

On staging and production the app refuses to start if `CORS_ORIGINS` contains `*` or a non-https origin (`http://localhost` is the only exception), or if `PUBLIC_APP_ORIGIN` is not https. Production also refuses `TERMS_REQUIRED=false`, `OTP_TEST_NUMBERS=true` and a non-empty `OTP_ALLOWED_PHONES`. `SESSION_COOKIE_SAMESITE` stays `lax` (one origin for the app and the API).

Staging and production never share a database, secrets or a pepper. Codes generated on staging can never work in production.

## How a change reaches a server

```text
git push master --> CI: quality (lint, types, tests) --> image: build ONCE, push
                    ghcr.io/winenpot/lottery-passport:sha-<commit>, move :staging
atpg: lp-deploy.timer (every minute) sees :staging moved --> deploy.sh: pull, migrate,
      switch, /ready, roll back on failure --> CI staging-verify: /health shows the commit

git tag v2026.10.20-1 && git push origin v2026.10.20-1
     --> Release workflow: waits for your approval (environment "production")
     --> moves :production to the SAME image --> production deploy agent --> verify
```

Why pull and not push (ADR-0011): GitHub never holds a key to our servers, nothing has to
reach the servers from abroad, and a public repository cannot run code on them. The only
thing a server needs from outside is `ghcr.io` (public image, no login) and `github.com`
(public repository, for the `deploy/` files of the deployed commit).

## Server setup (once per VM)

Two idempotent scripts in [`deploy/server/`](../deploy/server/) do it all; run them again
any time. `<user>` is the deploy user (`data` on atpg, `torshx` on production); it needs
passwordless sudo for setup only.

```bash
# on the server, as <user>
git clone https://github.com/winenpot/lottery-passport.git /tmp/lp && cd /tmp/lp

# 1. Production VM only (atpg is a shared, already-managed server):
#    snaps removed, desktop services off and masked, text mode, updates, Docker (Ubuntu's
#    packages, the same versions as atpg) with the domestic Docker Hub mirrors and log
#    limits, UTC, journal capped at 500 MB, automatic security updates, ufw = SSH only.
sudo deploy/server/provision.sh
#    after a provider snapshot: uninstall the desktop packages too
sudo deploy/server/provision.sh --purge-desktop
#    after the owner's key is in authorized_keys and a key login works (it refuses otherwise):
sudo deploy/server/provision.sh --harden-ssh

# 2. The stack: layout, repo clone, .env with every secret generated on the server (never
#    printed), placeholder page, a temporary self-signed certificate on production,
#    lp-firewall.service and lp-deploy.timer (the first deploy follows within a minute).
sudo deploy/server/install-app.sh production /opt/lottery-passport torshx
#    then fill the values it lists (Kavenegar key) in /opt/lottery-passport/.env
journalctl -u lp-deploy -f
```

**Origin ports only for ArvanCloud.** Everyone must come through Arvan (TLS, WAF, client IP
header). Docker-published ports bypass ufw, so
[`deploy/server/firewall.sh`](../deploy/server/firewall.sh) (run by `lp-firewall.service`
whenever Docker starts) rebuilds a chain `LP-ORIGIN` under `DOCKER-USER`: the published ports
(8098 on staging; 80 and 443 on production) accept new connections only from the ranges in
`deploy/nginx/snippets/arvan_realip.conf`. After Arvan changes its list: refresh that file
(`deploy/nginx/update_arvan_ips.sh`), commit, and the next deploy plus
`sudo systemctl restart lp-firewall` apply it.

Check that Ubuntu's clock is synchronized (`timedatectl`). If international NTP servers are
unreachable, configure the domestic NTP servers your provider documents.

## Getting images and packages onto the server

- **The API image** comes from GHCR, built by CI. The package is public (the repository is
  public and the image holds no secrets), so servers pull without credentials.
- **Base images** (`postgres`, `nginx`): Docker Hub refuses Iranian IP addresses; the
  `registry-mirrors` entry in `daemon.json` (above) serves them. **Pin by digest** after the
  first pull (`docker images --digests`), so a mirror cannot hand you something else later.
- **Python packages** are inside the image. A local build from inside Iran still works:
  `requirements.txt` is exported from `uv.lock` **with hashes**, so any PyPI mirror can be
  used (`PIP_INDEX_URL` build-arg) without trusting it.
- **Frontend**: Arman's accepted CI artifact (`dist/`), copied as files; servers never run `npm`.

## nginx

One configuration for both environments, so staging rehearses production:
[`deploy/nginx/`](../deploy/nginx/) has `http.conf` (shared), `snippets/app.conf` (every
location), and a small top-level file per environment (`nginx-staging.conf`: plain HTTP behind
Arvan, API docs on; `nginx-production.conf`: TLS, docs 404, unknown hosts dropped).

1. **Client IP**: ArvanCloud sends the visitor's address in `ar-real-ip`; nginx trusts it only
   from Arvan's ranges (`snippets/arvan_realip.conf`; refresh with
   `deploy/nginx/update_arvan_ips.sh` and commit). The API gets it as an overwritten
   `X-Forwarded-For`, so it cannot be spoofed.
2. **The PWA**: serves `<base>/web/current` (a relative symlink to the current release of
   Arman's `dist/`); `/assets/*` cached for a year, everything else revalidated (no-cache),
   errors never cached; unknown paths fall back to `index.html` (client routes like `/b/<code>`
   and `/q/...`). CSP and `Permissions-Policy: camera=(self)` on PWA responses only.
3. **The API**: `/api/`, `/health`, `/ready` proxied to the API container, `Cache-Control:
   no-store` on every API answer.
4. **Rate limits**: 10 requests/s per IP for the API, 6/min for OTP requests. **Lounge IPs**
   (`<base>/site/lounge_ips.conf`) get 300/s and 120/min because a whole lounge shares one
   public IP. Over the limit: `429` with the standard JSON error.
5. **Privacy and admin**: `/b/<code>` is logged as `/b/[redacted]` and `/q/...` as
   `/q/[redacted]`; `/admin` only from IPs in `<base>/site/admin_allow.conf`.

Config changes ship like code: commit, CI, and `deploy.sh` runs `nginx -t` before reloading
(an invalid config fails the deploy and is never loaded).

## TLS certificates

- **Browser -> ArvanCloud**: Arvan's free edge certificate for `torshx.com` and
  `*.torshx.com` (Arvan panel, HTTPS settings), with "redirect HTTP to HTTPS".
- **ArvanCloud -> production server**: a real certificate on the server, because OTP codes
  and session cookies cross that hop. Let's Encrypt via DNS-01 with an Arvan API token
  (HTTP-01 is unreliable while the record is proxied):

  ```bash
  curl https://get.acme.sh | sh -s email=<you>
  export Arvan_Token="<token from the Arvan panel, DNS scope only>"
  ~/.acme.sh/acme.sh --issue --dns dns_arvan -d play.torshx.com -d torshx.com --server letsencrypt
  ~/.acme.sh/acme.sh --install-cert -d play.torshx.com \
    --key-file /opt/lottery-passport/tls/privkey.pem \
    --fullchain-file /opt/lottery-passport/tls/fullchain.pem \
    --reloadcmd "/opt/lottery-passport/repo/deploy/compose.sh exec -T nginx nginx -s reload -c /etc/nginx/lp/nginx-production.conf"
  ```

  acme.sh renews from its own cron 30 days early. Monitor expiry anyway (below).
- **ArvanCloud -> staging**: plain HTTP to atpg:8098. Staging holds test data only.

## Deploying a release

**Staging**: nothing to do. Push to master; when CI is green, staging runs the commit within
about two minutes. `GET https://staging.torshx.com/health` shows `commit`.

**Production**: release tags are `vYYYY.MM.DD-N` on a commit that staging already runs.

```bash
git tag v2026.10.20-1 <commit> && git push origin v2026.10.20-1
# GitHub -> Actions -> Release -> "Review deployments" -> approve
```

On the server, [`deploy.sh`](../deploy/deploy.sh) (run by `lp-deploy.timer`) pulls the image,
checks out its commit for the `deploy/` files, runs `alembic upgrade head` with the new image
while the old one still serves, switches the API, reloads nginx after `nginx -t`, and waits for
`/ready`. If `/ready` does not answer within 90 seconds it switches back to the previous image
and remembers the bad one, so it is not retried every minute.

```bash
<base>/repo/deploy/deploy.sh --status          # what runs, what failed, last log lines
journalctl -u lp-deploy --since today          # full deploy output
<base>/repo/deploy/deploy.sh ghcr.io/winenpot/lottery-passport:sha-<commit>   # manual (rollback)
```

**Rollback** to an earlier commit: run `deploy.sh` with that commit's image (above), then
move the channel tag back too, or the agent redeploys the newer image on the next push. On
production, simply release the previous tag again. This is safe only because of one rule:
**during the campaign, migrations are additive** (new tables, new nullable columns, new indexes
created `CONCURRENTLY`). Renames and drops use expand -> migrate -> contract across two releases.

**Frontend release** (each release in its own directory; `current` is a relative symlink
switched atomically):

```bash
# copy Arman's accepted artifact (check its sha256 first) into a new release directory
rsync -a --delete --chmod=Da+rx,Fa+r dist/ <user>@server:<base>/web/releases/2026-10-20-1/
# nginx runs as uid 101 inside its container: release files must be world-readable

# on the server: renaming a symlink is atomic, so no request sees a half-copied site
cd <base>/web
ln -sfn releases/2026-10-20-1 current.next && mv -T current.next current
# rollback: the same two commands with the previous release directory
```

No nginx restart is needed: Compose mounts the parent directory `<base>/web`, so nginx
resolves `current` on every request. The first time, make sure `current` does not exist as a
plain directory, or `mv -T` cannot replace it.

## Code batches in production

Generate print batches **on the production server**, so the pepper never leaves it:

```bash
cd /opt/lottery-passport          # var/ is mode 700, owned by the deploy user
repo/deploy/compose.sh run --rm --user 0 -v "$PWD/var:/out" api \
  python -m scripts.generate_codes --city tokyo --quantity 50000 --coins-per-code 10 \
  --label "Tokyo can run 1" --base-url https://torshx.com --output /out/tokyo-run1.csv
repo/deploy/compose.sh run --rm api python -m scripts.code_batches list
```

Then follow [CODES.md](CODES.md#handing-codes-to-the-printer): encrypt, send, confirm the
checksum, delete. At launch: `python -m scripts.code_batches activate <batch-id>`. To kill a
leaked batch: `python -m scripts.code_batches void <batch-id>` (seconds; redeemed codes stay redeemed).

## Staff accounts

There is no "first admin" API route by design (a player can never promote themselves).
Sign up normally (so the account exists), then promote it directly on the database:

```bash
<base>/repo/deploy/compose.sh run --rm api python -m scripts.admins promote <identifier>
<base>/repo/deploy/compose.sh run --rm api python -m scripts.admins list
<base>/repo/deploy/compose.sh run --rm api python -m scripts.admins demote <identifier>
```

`<identifier>` is whatever the account signed up with (an E.164 phone number, e.g.
`+989123456789`). The admin then signs in at `/admin` with that number (SMS code;
on staging a 0969 test number shows the code on the page). `app/api/deps.require_admin`
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
- Template text (ask the provider to approve exactly this shape; the last line is what enables autofill). Two separate templates, same shape, worded for what the player actually sees on first use:

  ```text
  login:   کد ورود شما: %token

           @play.<domain> #%token

  signup:  کد ثبت‌نام شما: %token

           @play.<domain> #%token
  ```

  If the provider does not allow the same token twice, send the code in two parameters —
  `KavenegarSmsSender` already sends `token` and `token2` as the same value on every
  request regardless (`app/infrastructure/sms.py`), so register the template with
  `%token` on the first line and `%token2` on the second and nothing else changes.
  After approval, **send a real one to an Android phone and an iPhone**: if the provider
  appends anything after the last line (an opt-out text, a signature), autofill silently
  stops working.
- Submitting the templates (either path registers them `PendingReview`; Kavenegar's human
  review is the slow part either way):
  - **API** (faster, no panel login needed — `verify/addtemplate`, one GET per template;
    https://kavenegar.com/rest.html#sms-Lookup-AddTemplate). `name` must be plain English,
    no space or `_` (`login` / `signup`, already the config defaults).
    `sourceType=0` (website — play.torshx.com is a browser PWA, not an app-store app;
    change to `1` if you'd rather it reviewed as a mobile app). `sendMethod=1` (SMS only,
    no voice fallback). Never pipe the key through a command that echoes it:
    ```bash
    source .env  # or wherever KAVENEGAR_OTP_API_KEY actually lives
    for name in login signup; do
      text=$([ "$name" = login ] && echo 'کد ورود شما: %token

    @play.torshx.com #%token' || echo 'کد ثبت‌نام شما: %token

    @play.torshx.com #%token')
      curl -s -G "https://api.kavenegar.com/v1/${KAVENEGAR_OTP_API_KEY}/verify/addtemplate.json" \
        --data-urlencode "name=${name}" --data-urlencode "sourceType=0" \
        --data-urlencode "sendMethod=1" --data-urlencode "sourceUrl=https://play.torshx.com" \
        --data-urlencode "sourceName=TorshX" --data-urlencode "textMessage=${text}"
      echo
    done
    ```
    Each response's `return.message` confirms it queued for review (`entries.templateid`
    is the new template's id); `verify/templatelist` shows `approvalStatus` later.
  - **Panel**: kavenegar.com → login → پیامک → الگوهای اعتبارسنجی (Verification
    Templates) → add a new one, same field values as above.
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

**Full restore onto a new VM**: server setup → copy `.env` and `backup.env` from the
password manager → `repo/deploy/compose.sh up -d --wait postgres` → `restic dump --tag db latest <DUMP_DIR>/lottery_passport.dump > db.dump`
→ `repo/deploy/compose.sh exec -T postgres pg_restore -U <user> -d <db> --clean --if-exists --no-owner < db.dump`
→ enable `lp-deploy.timer` (it deploys `:production`) → point the Arvan record at the new IP.

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

- **Staging and production**: `deploy/compose.sh logs api --since 1h | grep csrf_rejected`
  (on the server, from the base directory). Size: roughly
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
- **Steps**: `df -h` and `docker system df`; free space safely (`docker image prune` for old images; rotate logs; never delete PostgreSQL data files); `deploy/compose.sh logs --tail=200 postgres`; restart PostgreSQL only after space is free. If the volume is corrupted: restore (above).
- **Tell**: CEO and Mehdi if SEV1 over 15 minutes.

### Runbook: overload or attack

- **Symptoms**: latency high, many 429/5xx, CPU or connections saturated.
- **Steps**: find the source (`deploy/compose.sh logs nginx | awk '{print $1}' | sort | uniq -c | sort -rn | head`); block abusive IPs in nginx or the firewall; tighten the `limit_req` rates; ask the provider/CDN for DDoS filtering if it is volumetric.
- **If the system stays down after the attack stops** (a retry storm keeps it saturated): **drop load first** (temporarily return 503 at nginx for `/api/` except `/health`), let the API and database recover, then reopen gradually. Restarting alone does not fix this; the backlog hits the fresh process immediately.

### Runbook: suspected code leak

- **Symptoms**: redemptions for a batch before its products are on sale; a spike from a few accounts or non-lounge IPs; codes posted online.
- **Steps (minutes count)**: `python -m scripts.code_batches void <batch-id>`; list who redeemed from that batch since the suspected leak; freeze (do not delete) their coins pending review; find the leak path (printer file, factory, internal); decide with Mehdi whether to reprint with a new batch.
- **Tell**: Mehdi and the CEO immediately; legal if prizes are affected.

### Runbook: bad deploy

- **Symptoms**: errors right after a release.
- **Steps**: re-release the previous tag (or `deploy.sh ghcr.io/winenpot/lottery-passport:<previous tag>` on the server); confirm `/ready`; then investigate on staging. A release whose `/ready` fails is rolled back automatically. Never "fix forward" on production during lounge peak hours.

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
- [ ] Lounge IPs in `<base>/site/lounge_ips.conf`; admin IPs in `<base>/site/admin_allow.conf`
- [ ] Alerts tested end to end (each one reached a phone)
- [ ] Mehdi and lounge staff trained; support channel staffed
- [ ] Rollback plan: previous tag noted here: `________`

### Deploy

- [ ] Release `<tag>` approved; Release workflow's production-verify green; `/ready` OK
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

#!/usr/bin/env bash
# Text the owner when production is unhealthy (installed 2026-10-22).
#
# cron (torshx), every 5 minutes:
#   */5 * * * * <base>/bin/alert_check.sh >> <base>/state/alerts.log 2>&1
#
# Checks: /ready at the origin (nginx -> api -> db) and through ArvanCloud;
# disk; age of the last good backup; origin TLS expiry; hourly: wallets equal
# their ledger, Kavenegar credit. One SMS when a check starts failing, a reminder
# every REMIND_MINUTES while it keeps failing, one when it recovers. Optional
# daily "AlertsAlive" text proves the alert path itself still works.
#
# SMS: Kavenegar verify/lookup with an already-approved template (default
# "otp": «کد تایید ورود شما: %token»); the token is the alert name, so tokens
# may not contain spaces, "_" or "-" (Kavenegar error 431).
#
# Config: <base>/site/alert.env (chmod 600), see deploy/site-examples/alert.env.
# The API key is read from <base>/.env (KAVENEGAR_OTP_API_KEY), never printed.
set -uo pipefail

base="${LP_BASE:-/opt/lottery-passport}"
state_dir="$base/state/alerts"
mkdir -p "$state_dir"
# shellcheck source=/dev/null
[ -r "$base/site/alert.env" ] && . "$base/site/alert.env"
ALERT_PHONES="${ALERT_PHONES:?set ALERT_PHONES in $base/site/alert.env}"
ALERT_TEMPLATE="${ALERT_TEMPLATE:-otp}"
PUBLIC_URL="${PUBLIC_URL:-https://play.torshx.com}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-85}"
BACKUP_MAX_AGE_MINUTES="${BACKUP_MAX_AGE_MINUTES:-420}"
CREDIT_MIN_RIALS="${CREDIT_MIN_RIALS:-500000}"
REMIND_MINUTES="${REMIND_MINUTES:-120}"
DAILY_OK_UTC="${DAILY_OK_UTC:-}" # e.g. "05:30" (= 09:00 Tehran); empty = off
backup_log="${BACKUP_LOG:-/var/log/lottery-passport-backup.log}"
compose="$base/repo/deploy/compose.sh"
host="$(echo "$PUBLIC_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
now="$(date +%s)"
minute="$(date -u +%M)"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

api_key() { sed -n 's/^KAVENEGAR_OTP_API_KEY=//p' "$base/.env" | tail -n 1; }

send() { # $1 = token (letters and digits only)
    local key phone code
    key="$(api_key)"
    [ -n "$key" ] || { log "SEND-FAILED $1: no KAVENEGAR_OTP_API_KEY"; return 1; }
    for phone in ${ALERT_PHONES//,/ }; do
        code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -G \
            "https://api.kavenegar.com/v1/$key/verify/lookup.json" \
            --data-urlencode "receptor=$phone" --data-urlencode "token=$1" \
            --data-urlencode "template=$ALERT_TEMPLATE")"
        if [ "$code" = 200 ]; then
            log "sent $1 to ...${phone: -4}"
        else
            log "SEND-FAILED $1 to ...${phone: -4}: HTTP $code"
        fi
    done
}

# check NAME OK(0/1) TOKEN-WHEN-FAILING
check() {
    local name="$1" ok="$2" token="$3" file="$state_dir/$1" since last
    if [ "$ok" = 0 ]; then
        if [ -f "$file" ]; then
            read -r since last <"$file"
            echo "$since $now" >"$file.tmp"
            if [ $((now - last)) -ge $((REMIND_MINUTES * 60)) ]; then
                send "${token}Still$(((now - since) / 60))m"
                mv "$file.tmp" "$file"
            else
                rm -f "$file.tmp"
            fi
        else
            echo "$now $now" >"$file"
            log "FAILING $name ($token)"
            send "$token"
        fi
    elif [ -f "$file" ]; then
        read -r since last <"$file"
        rm -f "$file"
        log "RECOVERED $name after $(((now - since) / 60)) min"
        send "${name}OK"
    fi
}

http_ok() { [ "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$@")" = 200 ]; }

# 1. Origin: nginx -> api -> database, bypassing ArvanCloud.
http_ok -k --resolve "$host:443:127.0.0.1" "https://$host/ready"
check Ready "$([ $? = 0 ] && echo 1 || echo 0)" ReadyDown

# 2. Edge: the same path a player takes.
http_ok "$PUBLIC_URL/ready"
check Edge "$([ $? = 0 ] && echo 1 || echo 0)" EdgeDown

# 3. Disk.
used="$(df -P / | awk 'NR == 2 {sub("%", "", $5); print $5}')"
check Disk "$([ "${used:-100}" -lt "$DISK_MAX_PERCENT" ] && echo 1 || echo 0)" "Disk${used}pct"

# 4. Last good backup ("backup ok" line, written by backup.sh).
backup_ok=0
if [ -r "$backup_log" ] && grep -q "backup ok" "$backup_log"; then
    started="$(grep "backup ok" "$backup_log" | tail -n 1 | sed -E 's/.*started ([0-9T:-]+Z).*/\1/')"
    started_s="$(date -d "$started" +%s 2>/dev/null || echo 0)"
    [ $((now - started_s)) -lt $((BACKUP_MAX_AGE_MINUTES * 60)) ] && backup_ok=1
fi
check Backup "$backup_ok" BackupStale

# 5. Origin TLS certificate: more than 7 days left.
openssl x509 -checkend 604800 -noout -in "$base/tls/fullchain.pem" >/dev/null 2>&1
check Tls "$([ $? = 0 ] && echo 1 || echo 0)" TlsExpiring

# Hourly (first run of each hour): money and SMS credit.
if [ "${minute#0}" -lt 5 ]; then
    mismatches="$("$compose" exec -T -e PGOPTIONS='-c default_transaction_read_only=on' \
        postgres sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
            SELECT count(*) FROM wallets w LEFT JOIN (SELECT user_id, sum(amount) AS total
            FROM coin_ledger_entries GROUP BY user_id) l USING (user_id)
            WHERE w.balance <> coalesce(l.total, 0)"' </dev/null 2>/dev/null | tr -d '[:space:]')"
    check Ledger "$([ "$mismatches" = 0 ] && echo 1 || echo 0)" "LedgerMismatch${mismatches:-Unknown}"

    credit="$(curl -s -m 15 "https://api.kavenegar.com/v1/$(api_key)/account/info.json" |
        python3 -c 'import json,sys; print(json.load(sys.stdin)["entries"]["remaincredit"])' 2>/dev/null)"
    check Credit "$([ "${credit:-0}" -ge "$CREDIT_MIN_RIALS" ] && echo 1 || echo 0)" "SmsCreditLow${credit:-Unknown}"
fi

# Daily proof of life for the alert path itself.
if [ -n "$DAILY_OK_UTC" ] && [[ ! "$(date -u +%H:%M)" < "$DAILY_OK_UTC" ]]; then
    today="$(date -u +%F)"
    if [ "$(cat "$state_dir/.daily" 2>/dev/null)" != "$today" ]; then
        echo "$today" >"$state_dir/.daily"
        failing="$(find "$state_dir" -maxdepth 1 -type f ! -name '.*' ! -name '*.tmp' | wc -l)"
        send "AlertsAlive${failing}failing"
    fi
fi
exit 0

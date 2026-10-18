#!/usr/bin/env bash
# Back up PostgreSQL to the off-site restic repository.
#
# cron (root), every 6 hours:
#   0 */6 * * * /opt/lottery-passport/deploy/backup.sh >> /var/log/lottery-passport-backup.log 2>&1
#
# The dump is written to a local file and checked with pg_restore --list
# BEFORE it is uploaded, so a failed or truncated dump never becomes the
# "latest" backup.
set -euo pipefail

deploy_dir="$(cd "$(dirname "$0")" && pwd)"
set -a
# shellcheck source=/dev/null
source "$deploy_dir/backup.env"
set +a
compose=("$deploy_dir/compose.sh")

mkdir -p "$DUMP_DIR"
chmod 700 "$DUMP_DIR"
dump="$DUMP_DIR/lottery_passport.dump"
trap 'rm -f "$dump"' EXIT

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"${compose[@]}" exec -T postgres \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 >"$dump"
"${compose[@]}" exec -T postgres pg_restore --list <"$dump" >/dev/null

restic backup --quiet --tag db "$dump"

# Keep 4 per day for 7 days, 30 dailies, 6 monthlies. Prune once a day.
if [ "$(date -u +%H)" -lt 6 ]; then
    restic forget --quiet --tag db --keep-within-hourly 7d \
        --keep-daily 30 --keep-monthly 6 --prune
fi

if [ -n "${HEARTBEAT_URL:-}" ]; then
    curl -fsS -m 10 "$HEARTBEAT_URL" >/dev/null || echo "heartbeat failed" >&2
fi
echo "backup ok (started $started, $(du -h "$dump" | cut -f1))"

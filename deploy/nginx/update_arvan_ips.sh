#!/usr/bin/env bash
# Regenerate snippets/arvan_realip.conf from ArvanCloud's published list.
# Also the source for the firewall rule that limits the origin port to Arvan.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
list="$(curl -fsS -m 20 https://www.arvancloud.ir/en/ips.txt | tr -d '\r' | grep -E '^[0-9a-f:.]+/[0-9]+$')"
[[ -n "$list" ]] || { echo "empty list; not touching the file" >&2; exit 1; }
{
    echo "# ArvanCloud edge ranges, from https://www.arvancloud.ir/en/ips.txt (fetched"
    echo "# $(date -u +%Y-%m-%d)). Refresh with: deploy/nginx/update_arvan_ips.sh (commit the result)."
    while read -r range; do echo "set_real_ip_from $range;"; done <<<"$list"
    echo "real_ip_header ar-real-ip;"
} >"$here/snippets/arvan_realip.conf"
echo "$(wc -l <<<"$list") ranges written"

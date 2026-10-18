#!/usr/bin/env bash
# Origin ports only for ArvanCloud (run by lp-firewall.service at boot and
# after Docker starts; safe to run again at any time).
#
# Docker-published ports bypass ufw: Docker's own iptables rules accept them
# before ufw sees the packet. The supported place for our rules is the
# DOCKER-USER chain. We keep ours in a chain LP-ORIGIN that is rebuilt from
# scratch on each run, so the result never depends on what ran before.
#
# Ports: from HTTP_PUBLISH / HTTPS_PUBLISH in <base>/.env (8098 on staging,
# 80 + 443 on production). Allowed sources: the ranges in
# deploy/nginx/snippets/arvan_realip.conf (the same list nginx trusts).
set -euo pipefail

base="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="$base/.env"
ranges_file="$base/repo/deploy/nginx/snippets/arvan_realip.conf"

ports=()
for key in HTTP_PUBLISH HTTPS_PUBLISH; do
    value="$(sed -n "s/^$key=//p" "$env_file" | tail -n 1)"
    [[ -n "$value" ]] && ports+=("${value##*:}")
done
# Production's compose override publishes 443 even when HTTPS_PUBLISH is unset.
if grep -qx 'ENVIRONMENT=production' "$env_file" && [[ ! " ${ports[*]} " == *" 443 "* ]]; then
    ports+=(443)
fi
mapfile -t ranges < <(sed -n 's/^set_real_ip_from \([0-9.\/]*\);$/\1/p' "$ranges_file")
[[ ${#ports[@]} -gt 0 ]] || { echo "lp-firewall: no ports in $env_file" >&2; exit 1; }
[[ ${#ranges[@]} -gt 0 ]] || { echo "lp-firewall: no ranges in $ranges_file" >&2; exit 1; }

iptables -N DOCKER-USER 2>/dev/null || true
iptables -N LP-ORIGIN 2>/dev/null || true
iptables -F LP-ORIGIN
# Replies and already accepted connections pass.
iptables -A LP-ORIGIN -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
for port in "${ports[@]}"; do
    for range in "${ranges[@]}"; do
        iptables -A LP-ORIGIN -p tcp -s "$range" -m conntrack --ctorigdstport "$port" -j RETURN
    done
    iptables -A LP-ORIGIN -p tcp -m conntrack --ctorigdstport "$port" -j DROP
done
iptables -C DOCKER-USER -j LP-ORIGIN 2>/dev/null || iptables -I DOCKER-USER 1 -j LP-ORIGIN

echo "lp-firewall: ports ${ports[*]} open to ${#ranges[@]} ArvanCloud ranges only"

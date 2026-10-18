#!/usr/bin/env bash
# docker compose for this server's stack, with the deployed image pinned.
#
#   <base>/repo/deploy/compose.sh ps
#   <base>/repo/deploy/compose.sh logs api --since 1h
#   <base>/repo/deploy/compose.sh run --rm api python -m scripts.admins list
#
# API_IMAGE defaults to the digest deploy.sh last deployed (state/current);
# deploy.sh exports its own while it deploys.
set -euo pipefail

base="${LP_BASE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
env_file="$base/.env"
[[ -r "$env_file" ]] || {
    echo "compose.sh: $env_file not found (is this the base directory?)" >&2
    exit 1
}
environment="$(sed -n 's/^ENVIRONMENT=//p' "$env_file" | tail -n 1)"
case "$environment" in
    staging | production) ;;
    *)
        echo "compose.sh: ENVIRONMENT must be staging or production in $env_file" >&2
        exit 1
        ;;
esac

files=(-f "$base/repo/deploy/compose.yml")
if [[ "$environment" == production ]]; then
    files+=(-f "$base/repo/deploy/compose.production.yml")
fi

export LP_BASE="$base"
if [[ -z "${API_IMAGE:-}" ]]; then
    API_IMAGE="$(cat "$base/state/current" 2>/dev/null || echo "none-deployed-yet")"
fi
export API_IMAGE

exec docker compose --project-name "lp-$environment" --env-file "$env_file" \
    "${files[@]}" "$@"

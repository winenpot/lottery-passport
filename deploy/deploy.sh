#!/usr/bin/env bash
# Pull-based deploy agent (docs/adr/0011-pull-based-deploys-from-ghcr.md).
#
# lp-deploy.timer runs it every minute:
#   deploy.sh                 deploy the channel tag (:staging or :production,
#                             = ENVIRONMENT) if it points at a new image
#   deploy.sh <image-ref>     deploy exactly this image (manual rollback), e.g.
#                             ghcr.io/winenpot/lottery-passport:sha-<40 hex>
#   deploy.sh --status        print what is deployed
#
# Steps: pull, check out the image's own commit (for deploy/ files), start
# PostgreSQL, run migrations with the NEW image while the old API keeps
# serving, switch the API, reload nginx, wait for /ready. If that fails,
# switch back to the previous image automatically and remember the bad digest
# so the timer does not retry it every minute. Rolling back code is safe
# because campaign migrations are additive (expand, migrate, contract).
set -euo pipefail

main() {
    base="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    repo="$base/repo"
    state="$base/state"
    mkdir -p "$state"
    env_file="$base/.env"
    environment="$(read_env ENVIRONMENT)"
    image_repo="$(read_env LP_IMAGE_REPO)"
    image_repo="${image_repo:-ghcr.io/winenpot/lottery-passport}"
    compose="$repo/deploy/compose.sh"

    if [[ "${1:-}" == "--status" ]]; then
        status
        return
    fi

    # One deploy at a time; a timer tick during a deploy just exits.
    exec 9>"$state/deploy.lock"
    flock -n 9 || return 0

    local manual=0 target="$image_repo:$environment"
    if [[ $# -gt 0 ]]; then
        manual=1
        target="$1"
    fi

    if ! docker pull --quiet "$target" >/dev/null 2>"$state/pull.err"; then
        # A registry blip is logged once, not every minute.
        if ! cmp -s "$state/pull.err" "$state/pull.err.last"; then
            log "pull of $target failed: $(tr '\n' ' ' <"$state/pull.err")"
            cp "$state/pull.err" "$state/pull.err.last"
        fi
        return 1
    fi
    rm -f "$state/pull.err.last"

    local new current
    new="$(digest_ref "$target")"
    current="$(cat "$state/current" 2>/dev/null || true)"
    if [[ $manual -eq 0 ]]; then
        [[ "$new" == "$current" ]] && return 0
        [[ "$new" == "$(cat "$state/failed" 2>/dev/null || true)" ]] && return 0
    fi

    local commit
    commit="$(revision "$new")"
    log "deploying $commit ($new)"
    if ! release "$new" "$commit"; then
        echo "$new" >"$state/failed"
        log "FAILED $commit"
        if [[ -n "$current" ]]; then
            log "rolling back to $(revision "$current")"
            if release "$current" "$(revision "$current")"; then
                log "rolled back to $(revision "$current"): ready"
            else
                log "ROLLBACK FAILED too; check: $compose logs --tail=200 api"
            fi
        fi
        return 1
    fi

    if [[ -n "$current" && "$current" != "$new" ]]; then
        echo "$current" >"$state/previous"
    fi
    echo "$new" >"$state/current"
    rm -f "$state/failed"
    # Keep the deployed and the previous image; untagged older ones may go.
    docker tag "$new" "$image_repo:deployed-current"
    if [[ -s "$state/previous" ]]; then
        docker tag "$(cat "$state/previous")" "$image_repo:deployed-previous"
    fi
    docker image prune --force --filter "until=72h" >/dev/null || true
    log "deployed $commit: ready"
}

# release <digest-ref> <commit>: switch the stack to that image; 0 when ready.
release() {
    local image="$1" commit="$2" conf
    conf="/etc/nginx/lp/nginx-$environment.conf"
    git -C "$repo" fetch --quiet origin "$commit" || return 1
    git -C "$repo" -c advice.detachedHead=false checkout --quiet --detach "$commit" ||
        return 1
    export API_IMAGE="$image"
    "$compose" up --detach --wait --quiet-pull postgres || return 1
    "$compose" run --rm --no-deps api alembic upgrade head || return 1
    "$compose" up --detach --quiet-pull --remove-orphans || return 1
    # The nginx config may have changed with the checkout. An invalid one is
    # never loaded (nginx -t first); the running config stays.
    if ! "$compose" exec -T nginx nginx -t -q -c "$conf"; then
        log "nginx config of $commit is invalid"
        return 1
    fi
    "$compose" exec -T nginx nginx -s reload -c "$conf" || return 1
    for _ in $(seq 1 45); do
        if "$compose" exec -T api python -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

status() {
    local current
    current="$(cat "$state/current" 2>/dev/null || true)"
    echo "environment: $environment"
    if [[ -n "$current" ]]; then
        echo "current:     $current (commit $(revision "$current"))"
    else
        echo "current:     none"
    fi
    echo "previous:    $(cat "$state/previous" 2>/dev/null || echo none)"
    echo "failed:      $(cat "$state/failed" 2>/dev/null || echo none)"
    tail -n 5 "$state/deploy.log" 2>/dev/null || true
}

read_env() {
    sed -n "s/^$1=//p" "$env_file" | tail -n 1
}

# The registry digest of a pulled image, as <repo>@sha256:<hex>.
digest_ref() {
    docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$1" |
        grep -m 1 "^$image_repo@"
}

revision() {
    docker image inspect --format \
        '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1"
}

log() {
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
    echo "$line"
    echo "$line" >>"$state/deploy.log"
}

# Everything runs from main, which bash has fully read before it starts:
# `git checkout` may replace this very file while it runs.
main "$@"

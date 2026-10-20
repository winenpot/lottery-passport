#!/usr/bin/env bash
# Pull-based frontend deploy agent, STAGING ONLY (ADR-0012; extends 0011's
# pull philosophy to Arman's separate frontend repo).
#
# lp-frontend-deploy.timer runs it every minute:
#   deploy_frontend.sh            publish the newest green main build if new
#   deploy_frontend.sh --status   print what is deployed
#
# Steps: ask GitHub for the newest successful "Frontend CI" run on main,
# download its frontend-normal artifact with a repo-scoped read-only token,
# and hand the zip to publish_web.sh (same verification -- metadata.json
# mode=api, index.html, assets/ -- as a manual publish). Never builds,
# never touches production: play.torshx.com keeps the manual
# publish_web.sh step on purpose (user's call, 2026-10-20).
set -euo pipefail

FRONTEND_WORKFLOW_NAME="Frontend CI"
FRONTEND_ARTIFACT_NAME="frontend-normal"

main() {
    base="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    repo_dir="$base/repo"
    state="$base/state"
    mkdir -p "$state"
    env_file="$base/.env"
    token="$(read_env FRONTEND_GH_TOKEN)"
    repo="$(read_env FRONTEND_REPO)"
    repo="${repo:-Arman13m99/TorshX_2}"

    if [[ "${1:-}" == "--status" ]]; then
        status
        return
    fi

    if [[ -z "$token" ]]; then
        # Not configured yet; the timer ticks quietly until FRONTEND_GH_TOKEN
        # is set (deploy/env/staging.env.example documents it).
        return 0
    fi

    # One run at a time; a timer tick during a publish just exits.
    exec 9>"$state/frontend-deploy.lock"
    flock -n 9 || return 0

    local runs run_id head_sha
    runs="$(api "/repos/$repo/actions/runs?branch=main&event=push&status=success&per_page=10")" || {
        log "could not list workflow runs"
        return 1
    }
    run_id="$(echo "$runs" | jq -r --arg name "$FRONTEND_WORKFLOW_NAME" \
        '[.workflow_runs[] | select(.name == $name)] | sort_by(.created_at) | last | .id // empty')"
    head_sha="$(echo "$runs" | jq -r --arg name "$FRONTEND_WORKFLOW_NAME" \
        '[.workflow_runs[] | select(.name == $name)] | sort_by(.created_at) | last | .head_sha // empty')"
    [[ -n "$run_id" ]] || { log "no successful '$FRONTEND_WORKFLOW_NAME' run on main yet"; return 0; }

    local current failed
    current="$(cat "$state/frontend-current" 2>/dev/null || true)"
    failed="$(cat "$state/frontend-failed" 2>/dev/null || true)"
    [[ "$head_sha" == "$current" ]] && return 0
    [[ "$head_sha" == "$failed" ]] && return 0

    log "publishing frontend $head_sha (run $run_id)"
    if ! publish "$run_id" "$head_sha"; then
        echo "$head_sha" >"$state/frontend-failed"
        log "FAILED frontend $head_sha"
        return 1
    fi
    echo "$head_sha" >"$state/frontend-current"
    rm -f "$state/frontend-failed"
    log "published frontend $head_sha"
}

# publish <run-id> <commit>: download that run's artifact and publish it.
publish() {
    local run_id="$1" commit="$2" release_id artifacts artifact_id work_dir zip_path
    release_id="${commit:0:7}-$(date -u +%Y%m%d)"
    if [[ -e "$base/web/releases/$release_id" ]]; then
        log "release $release_id already exists; adopting it as current"
        return 0
    fi

    artifacts="$(api "/repos/$repo/actions/runs/$run_id/artifacts")" || return 1
    artifact_id="$(echo "$artifacts" | jq -r --arg name "$FRONTEND_ARTIFACT_NAME" \
        '.artifacts[] | select(.name == $name) | .id' | head -n 1)"
    if [[ -z "$artifact_id" ]]; then
        log "no '$FRONTEND_ARTIFACT_NAME' artifact on run $run_id"
        return 1
    fi

    work_dir="$(mktemp -d)"
    trap 'rm -rf "$work_dir"' RETURN
    zip_path="$work_dir/artifact.zip"
    curl -fsS -m 60 -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
        -L "https://api.github.com/repos/$repo/actions/artifacts/$artifact_id/zip" \
        -o "$zip_path" || return 1

    # publish_web.sh re-validates metadata.json mode=api, index.html, assets/
    # and does the atomic web/current switch + nginx reload.
    "$repo_dir/deploy/publish_web.sh" "$zip_path" "$release_id"
}

status() {
    echo "frontend configured: $([[ -n "$token" ]] && echo yes || echo 'no (FRONTEND_GH_TOKEN unset)')"
    echo "frontend current:    $(cat "$state/frontend-current" 2>/dev/null || echo none)"
    echo "frontend failed:      $(cat "$state/frontend-failed" 2>/dev/null || echo none)"
    tail -n 5 "$state/frontend-deploy.log" 2>/dev/null || true
}

read_env() { sed -n "s/^$1=//p" "$env_file" | tail -n 1; }

api() {
    curl -fsS -m 30 -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
        "https://api.github.com$1"
}

log() {
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
    echo "$line"
    echo "$line" >>"$state/frontend-deploy.log"
}

main "$@"

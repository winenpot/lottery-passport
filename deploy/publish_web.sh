#!/usr/bin/env bash
# Publish a verified frontend artifact (CI metadata.json mode=api) to
# <base>/web/releases/<id> and atomically switch web/current -> it.
#
# Usage (run ON the server, as the deploy user):
#   deploy/publish_web.sh <artifact.zip> <release-id>
#
# The zip must contain, at minimum, index.html, assets/ and metadata.json
# (the CI artifact shape from TorshX_2's frontend-normal build). Only the
# public files (index.html + assets/) are copied into the served release;
# metadata.json and any *.ps1/Caddyfile.template "tools" stay out of the
# web root (deploy/nginx/snippets/app.conf also 404s a few extra names
# defensively, but we don't even copy them).
set -euo pipefail

zip_path="${1:?usage: publish_web.sh <artifact.zip> <release-id>}"
release_id="${2:?usage: publish_web.sh <artifact.zip> <release-id>}"

base="${LP_BASE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
web_dir="$base/web"
releases_dir="$web_dir/releases"
release_dir="$releases_dir/$release_id"

[[ -f "$zip_path" ]] || { echo "publish_web.sh: $zip_path not found" >&2; exit 1; }
[[ -d "$releases_dir" ]] || { echo "publish_web.sh: $releases_dir missing (is this the base directory?)" >&2; exit 1; }
if [[ -e "$release_dir" ]]; then
    echo "publish_web.sh: $release_dir already exists, refusing to overwrite" >&2
    exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

echo "publish_web.sh: extracting $zip_path" >&2
unzip -q "$zip_path" -d "$work_dir"

[[ -f "$work_dir/metadata.json" ]] || { echo "publish_web.sh: metadata.json missing from artifact" >&2; exit 1; }
mode="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('mode',''))" "$work_dir/metadata.json")"
[[ "$mode" == "api" ]] || { echo "publish_web.sh: metadata.json mode is '$mode', expected 'api'" >&2; exit 1; }
[[ -f "$work_dir/index.html" ]] || { echo "publish_web.sh: index.html missing from artifact" >&2; exit 1; }
[[ -d "$work_dir/assets" ]] || { echo "publish_web.sh: assets/ missing from artifact" >&2; exit 1; }

mkdir -p "$release_dir"
cp "$work_dir/index.html" "$release_dir/"
cp -r "$work_dir/assets" "$release_dir/assets"

# nginx in the compose stack runs as uid 101; the release dir and everything
# under it must be world-readable (deploy/nginx's own pitfall note).
find "$release_dir" -type d -exec chmod 755 {} +
find "$release_dir" -type f -exec chmod 644 {} +

# Atomic switch: write a new symlink under a temp name, then rename over
# web/current (rename is atomic on the same filesystem).
ln -sfn "releases/$release_id" "$web_dir/current.new"
mv -T "$web_dir/current.new" "$web_dir/current"

echo "publish_web.sh: web/current -> releases/$release_id" >&2

if command -v docker >/dev/null 2>&1; then
    environment="$(sed -n 's/^ENVIRONMENT=//p' "$base/.env" 2>/dev/null | tail -n 1)"
    if [[ -n "$environment" ]]; then
        "$base/repo/deploy/compose.sh" exec -T nginx nginx -s reload \
            && echo "publish_web.sh: nginx reloaded" >&2 \
            || echo "publish_web.sh: nginx reload failed (new release still live via try_files)" >&2
    fi
fi

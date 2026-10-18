#!/usr/bin/env bash
# Install the lottery-passport stack on a provisioned host. Idempotent: an
# existing .env, repo or web release is never overwritten.
#
#   sudo deploy/server/install-app.sh production /opt/lottery-passport torshx
#   sudo deploy/server/install-app.sh staging /home/data/lottery-passport data
#
# Creates the layout under <base> (deploy/compose.yml explains it), clones the
# public repo, writes .env from deploy/env/<environment>.env.example with every
# <generated> secret generated here (never printed), a placeholder web page,
# a self-signed certificate on production until acme.sh installs the real one,
# and enables lp-deploy.timer and lp-firewall.service.
set -euo pipefail

main() {
    [[ $EUID -eq 0 ]] || die "run as root (sudo)"
    [[ $# -eq 3 ]] || die "usage: install-app.sh <staging|production> <base> <user>"
    local environment="$1" base="$2" user="$3"
    case "$environment" in staging | production) ;; *) die "bad environment" ;; esac
    id -nG "$user" | tr ' ' '\n' | grep -qx docker || die "$user is not in the docker group"

    step "layout in $base"
    install -d -o "$user" -g "$user" -m 750 "$base" "$base/state" "$base/site"
    install -d -o "$user" -g "$user" -m 755 "$base/web" "$base/web/releases"
    install -d -o "$user" -g "$user" -m 700 "$base/var"
    if [[ ! -d "$base/repo/.git" ]]; then
        sudo -u "$user" git clone -q https://github.com/winenpot/lottery-passport.git "$base/repo"
    fi
    local example="$base/repo/deploy/env/$environment.env.example"

    if [[ ! -e "$base/site/admin_allow.conf" ]]; then
        if [[ "$environment" == staging ]]; then
            echo 'allow all;' >"$base/site/admin_allow.conf"
        else
            cp "$base/repo/deploy/site-examples/admin_allow.conf" "$base/site/"
        fi
    fi
    [[ -e "$base/site/lounge_ips.conf" ]] ||
        cp "$base/repo/deploy/site-examples/lounge_ips.conf" "$base/site/"
    chown "$user:$user" "$base/site/"*.conf

    if [[ ! -e "$base/web/current" ]]; then
        install -d -o "$user" -g "$user" -m 755 "$base/web/releases/placeholder"
        printf '<!doctype html><meta charset="utf-8"><title>TorshX</title><p>%s</p>\n' \
            "Frontend not published yet." >"$base/web/releases/placeholder/index.html"
        chmod 644 "$base/web/releases/placeholder/index.html"
        sudo -u "$user" ln -s releases/placeholder "$base/web/current"
    fi

    step ".env"
    if [[ -e "$base/.env" ]]; then
        echo "  exists; not touched"
    else
        write_env "$example" "$base/.env"
        chown "$user:$user" "$base/.env"
        chmod 600 "$base/.env"
        echo "  written; still to fill by hand:"
        grep -nE '^[A-Z_]+=$' "$base/.env" | sed 's/^/    line /' || true
    fi

    if [[ "$environment" == production && ! -e "$base/tls/fullchain.pem" ]]; then
        step "temporary self-signed certificate (acme.sh replaces it)"
        install -d -o "$user" -g "$user" -m 700 "$base/tls"
        openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj /CN=play.torshx.com \
            -keyout "$base/tls/privkey.pem" -out "$base/tls/fullchain.pem" 2>/dev/null
        chown "$user:$user" "$base/tls/"*.pem
        chmod 600 "$base/tls/privkey.pem"
    fi

    step "systemd: lp-deploy.timer, lp-firewall.service"
    local unit
    for unit in lp-deploy.service lp-firewall.service; do
        sed -e "s|@USER@|$user|g" -e "s|@BASE@|$base|g" \
            "$base/repo/deploy/systemd/$unit" >"/etc/systemd/system/$unit"
    done
    cp "$base/repo/deploy/systemd/lp-deploy.timer" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now lp-firewall.service >/dev/null
    systemctl enable --now lp-deploy.timer >/dev/null
    echo "  first deploy within a minute: journalctl -u lp-deploy -f"
}

# Copy the example; replace <generated> secrets; make DATABASE_URL use the
# generated database password; empty any other <placeholder> (listed after).
write_env() {
    local example="$1" target="$2" db_password line key value
    db_password="$(gen)"
    umask 077
    : >"$target"
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^([A-Z_]+)=(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            if [[ "$key" == POSTGRES_PASSWORD ]]; then
                value="$db_password"
            elif [[ "$key" == DATABASE_URL ]]; then
                value="${value//<same as POSTGRES_PASSWORD>/$db_password}"
            elif [[ "$value" == "<generated"* ]]; then
                value="$(gen)"
            elif [[ "$value" == *"<"*">"* ]]; then
                value=""
            fi
            line="$key=$value"
        fi
        printf '%s\n' "$line" >>"$target"
    done <"$example"
}

gen() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48; }
step() { printf '\n== %s\n' "$*"; }
die() {
    echo "install-app.sh: $*" >&2
    exit 1
}

main "$@"

#!/usr/bin/env bash
# Provision a fresh Ubuntu VM as a lottery-passport host (production).
# Idempotent: safe to run again. Run as root (sudo). See docs/OPERATIONS.md.
#
#   sudo deploy/server/provision.sh                 trim + packages + Docker + host settings
#   sudo deploy/server/provision.sh --purge-desktop  also uninstall the desktop (take a
#                                                    provider snapshot first)
#   sudo deploy/server/provision.sh --harden-ssh     keys only, no root login; refuses
#                                                    unless 2+ keys are authorized
#
# Not for atpg: it is a shared server with its own setup.
set -euo pipefail

# Services a server never needs (desktop image leftovers). Disabled, not
# removed, so the first step is reversible.
DESKTOP_SERVICES=(
    gdm cups cups-browsed avahi-daemon colord ModemManager wpa_supplicant fwupd
    power-profiles-daemon switcheroo-control upower udisks2 accounts-daemon
    rtkit-daemon whoopsie apport kerneloops snapd snapd.socket snapd.apparmor
)
# Kept explicitly: apt's autoremove after purging the desktop would otherwise
# take them along. NetworkManager holds this server's IP address.
KEEP_PACKAGES=(
    network-manager openssh-server systemd-resolved chrony cron rsyslog
    unattended-upgrades open-vm-tools ufw iptables nftables sudo
    ca-certificates curl git restic
)
# Only when no Docker is installed. An existing Docker (e.g. docker-ce from
# Docker's own repository) is kept: installing docker.io next to it makes apt
# REMOVE docker-ce (they conflict), which happened once.
DOCKER_PACKAGES=(docker.io docker-compose-v2)
DESKTOP_PACKAGES=(
    'ubuntu-desktop*' 'gnome-*' 'gdm3' 'evolution*' 'ibus*' 'update-notifier*'
    'apport*' 'cups*' 'avahi-*' 'colord*' 'modemmanager' 'fwupd*'
    'xwayland' 'mutter*' 'yelp*' 'libreoffice*' 'thunderbird*' 'whoopsie'
)

main() {
    [[ $EUID -eq 0 ]] || die "run as root (sudo)"
    local purge=0 harden=0
    for arg in "$@"; do
        case "$arg" in
            --purge-desktop) purge=1 ;;
            --harden-ssh) harden=1 ;;
            *) die "unknown option $arg" ;;
        esac
    done

    step "snaps removed (needs snapd running, so before the services go)"
    remove_snaps

    step "text mode, desktop services off"
    systemctl set-default multi-user.target >/dev/null
    for unit in "${DESKTOP_SERVICES[@]}"; do
        if systemctl list-unit-files "$unit*" --no-legend 2>/dev/null | grep -q .; then
            systemctl disable --now "$unit" >/dev/null 2>&1 || true
            systemctl mask "$unit" >/dev/null 2>&1 || true
        fi
    done

    step "packages"
    export DEBIAN_FRONTEND=noninteractive
    # A fresh VM runs apt on its own at boot (unattended-upgrades, the desktop
    # updater): wait for its lock instead of failing.
    local apt=(apt-get -q -o DPkg::Lock::Timeout=900)
    "${apt[@]}" update
    "${apt[@]}" -y -o Dpkg::Options::=--force-confold upgrade
    "${apt[@]}" -y install --no-install-recommends "${KEEP_PACKAGES[@]}"
    apt-mark manual "${KEEP_PACKAGES[@]}" >/dev/null
    if command -v docker >/dev/null; then
        echo "  Docker already installed ($(docker --version)); not touched"
    else
        "${apt[@]}" -y install --no-install-recommends "${DOCKER_PACKAGES[@]}"
        apt-mark manual "${DOCKER_PACKAGES[@]}" >/dev/null
    fi
    docker compose version >/dev/null || die "docker compose plugin missing"

    if [[ $purge -eq 1 ]]; then
        step "purge desktop packages"
        # shellcheck disable=SC2068 # globs are for apt, not the shell
        "${apt[@]}" -y purge ${DESKTOP_PACKAGES[@]} || true
        "${apt[@]}" -y autoremove --purge
        "${apt[@]}" -y purge snapd || true
    fi

    step "time, journal, automatic security updates"
    timedatectl set-timezone UTC
    install -d /etc/systemd/journald.conf.d
    printf '[Journal]\nSystemMaxUse=500M\n' >/etc/systemd/journald.conf.d/lp.conf
    systemctl restart systemd-journald
    printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
        >/etc/apt/apt.conf.d/20auto-upgrades

    step "Docker: domestic Docker Hub mirrors, log limits, live restore"
    install -d /etc/docker
    cat >/etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.arvancloud.ir",
    "https://docker.iranserver.com",
    "https://registry.docker.ir"
  ],
  "log-driver": "json-file",
  "log-opts": {"max-size": "20m", "max-file": "5"},
  "live-restore": true
}
JSON
    systemctl enable docker >/dev/null
    systemctl restart docker
    if [[ -n "${SUDO_USER:-}" ]]; then
        usermod -aG docker "$SUDO_USER"
    fi

    step "host firewall (SSH only; Docker-published ports: lp-firewall.service)"
    local ssh_port
    ssh_port="$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}')"
    # Never guess: a wrong port here locks everyone out.
    [[ "$ssh_port" =~ ^[0-9]+$ ]] || die "cannot read the SSH port from sshd -T"
    # sshd_config alone is not enough: Ubuntu >= 22.10 binds the port through
    # ssh.socket, which ignores sshd_config's Port. A reboot without this falls
    # back to 22 while the firewall and sshd_config still say $ssh_port, and
    # locks everyone out (lottery-passport prod, 2026-10-22). Pin it here too.
    if systemctl list-unit-files ssh.socket >/dev/null 2>&1; then
        install -d /etc/systemd/system/ssh.socket.d
        printf '[Socket]\nListenStream=\nListenStream=%s\n' "$ssh_port" \
            >/etc/systemd/system/ssh.socket.d/port.conf
        systemctl daemon-reload
        systemctl restart ssh.socket
        systemctl show ssh.socket -p Listen --value | grep -q ":$ssh_port " ||
            die "ssh.socket did not come up on $ssh_port; check manually before closing this session"
    fi
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow "$ssh_port/tcp" >/dev/null
    ufw --force enable >/dev/null

    if [[ $harden -eq 1 ]]; then
        harden_ssh
    fi

    step "done"
    free -m | sed -n 2p
    systemctl list-units --type=service --state=running --no-legend --plain |
        awk '{print $1}' | tr '\n' ' '
    echo
}

remove_snaps() {
    command -v snap >/dev/null || return 0
    # snapd masked by an earlier run: `snap` would wait for it forever.
    systemctl is-active --quiet snapd.socket snapd || return 0
    # Apps first, then the runtimes they depend on, snapd last.
    local name
    for _ in 1 2 3; do
        while read -r name; do
            [[ -n "$name" && "$name" != snapd ]] || continue
            snap remove --purge "$name" >/dev/null 2>&1 || true
        done < <(snap list 2>/dev/null | awk 'NR > 1 {print $1}')
    done
}

harden_ssh() {
    step "SSH: keys only, no root login"
    local user="${SUDO_USER:-root}" keys
    keys="$(grep -cE '^(ssh-|ecdsa-|sk-)' "$(getent passwd "$user" | cut -d: -f6)/.ssh/authorized_keys" || true)"
    if [[ "${keys:-0}" -lt 2 ]]; then
        echo "  REFUSED: $user has $keys authorized key(s). Add the owner's key too, and test" >&2
        echo "  a key login, or nobody but the deploy machine can get in afterwards." >&2
        return 1
    fi
    cat >/etc/ssh/sshd_config.d/10-lp-hardening.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
    sshd -t
    systemctl reload ssh
}

step() { printf '\n== %s\n' "$*"; }
die() {
    echo "provision.sh: $*" >&2
    exit 1
}

main "$@"

"""Read-only health and state check of a deployed server, over SSH.

Runs from a laptop. Sends one fixed, read-only shell script to the server
(``ssh <target> bash -s``) and checks the public URL from here, then prints
PASS / WARN / FAIL / INFO lines and exits non-zero when anything FAILs.

What it looks at:

* host: uptime/load, memory, disk of ``/`` and ``<base>``
* deploy: ``deploy.sh --status`` (current/previous/failed image + commit),
  containers of ``compose.sh ps``, frontend release (``web/current``)
* app: ``/health`` and ``/ready`` from inside the api container and from the
  public URL; the deployed commit against the local git tag/HEAD
* database (read-only transaction): alembic revision against the local head,
  code batches by status, redeemed codes, users/admins, terms versions,
  catalogue sizes (venues, challenges, achievements, avatars)
* ops: lp-* systemd timers, TLS certificate expiry, newest backup log lines,
  api ERROR lines and nginx 5xx in the last hour

Never writes anything, never prints ``.env`` values except an allow-list of
non-secret keys (ENVIRONMENT, TERMS_*, PUBLIC_APP_ORIGIN, OTP_TEST_NUMBERS).
Authentication is the SSH key only (``BatchMode=yes``: no password prompts).

Usage::

    uv run python -m scripts.server_check --target lp-prod
    uv run python -m scripts.server_check --target torshx@play-vm -p 2222 \\
        --base /opt/lottery-passport --public-url https://play.torshx.com
    uv run python -m scripts.server_check --target lp-staging \\
        --base /home/data/lottery-passport --public-url https://staging.torshx.com

``--target`` defaults to ``$LP_SSH_TARGET``; an ``~/.ssh/config`` alias keeps
hosts, ports and users out of shell history and out of this repository.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_BASE = "/opt/lottery-passport"
DEFAULT_PUBLIC_URL = "https://play.torshx.com"
SAFE_ENV_KEYS = (
    "ENVIRONMENT",
    "TERMS_VERSION",
    "TERMS_REQUIRED",
    "TERMS_URL",
    "PRIVACY_URL",
    "PUBLIC_APP_ORIGIN",
    "OTP_TEST_NUMBERS",
)

# Every section starts with "@@<name>" so the output can be split reliably.
# Each command is guarded so one failure does not hide the rest. Read-only:
# psql runs with default_transaction_read_only=on.
REMOTE_SCRIPT = r"""
set -u
base="$1"
safe_keys="$2"
compose="$base/repo/deploy/compose.sh"
psql_ro() {
    "$compose" exec -T -e PGOPTIONS='-c default_transaction_read_only=on' postgres \
        sh -c 'psql -X -q -A -F "|" -t -v ON_ERROR_STOP=1 \
            -U "$POSTGRES_USER" -d "$POSTGRES_DB"' 2>&1
}

echo "@@host"
echo "hostname=$(hostname)"
echo "user=$(whoami)"
echo "now_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
uptime
free -m | sed -n '1,2p'

echo "@@disk"
df -P -h / "$base" 2>&1 | awk 'NR == 1 || !seen[$0]++'

echo "@@env"
if [ -r "$base/.env" ]; then
    for key in $safe_keys; do
        value="$(sed -n "s/^$key=//p" "$base/.env" | tail -n 1)"
        echo "$key=$value"
    done
else
    echo "unreadable=$base/.env"
fi

echo "@@deploy"
"$base/repo/deploy/deploy.sh" --status 2>&1 | head -n 12

echo "@@containers"
"$compose" ps --format '{{.Service}}|{{.State}}|{{.Health}}|{{.Status}}' 2>&1

echo "@@frontend"
readlink "$base/web/current" 2>&1 || echo "no web/current"

echo "@@health"
"$compose" exec -T api python -c '
import urllib.request
for path in ("/health", "/ready"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=5) as r:
            print(path, r.status, r.read().decode()[:300])
    except urllib.error.HTTPError as e:
        print(path, e.code, e.read().decode()[:300])
    except Exception as e:
        print(path, "ERR", e)
' 2>&1

echo "@@alembic"
psql_ro <<'SQL'
SELECT version_num FROM alembic_version;
SQL

echo "@@batches"
psql_ro <<'SQL'
SELECT status, count(*), coalesce(sum(quantity), 0)
FROM code_batches GROUP BY status ORDER BY status;
SQL

echo "@@counts"
psql_ro <<'SQL'
SELECT 'users', count(*) FROM users
UNION ALL SELECT 'admins', count(*) FROM users WHERE role = 'admin'
UNION ALL SELECT 'codes', count(*) FROM redemption_codes
UNION ALL SELECT 'codes_redeemed', count(*) FROM redemption_codes
    WHERE redeemed_at IS NOT NULL
UNION ALL SELECT 'ledger_entries', count(*) FROM coin_ledger_entries
UNION ALL SELECT 'venues', count(*) FROM venues
UNION ALL SELECT 'challenges_active', count(*) FROM challenges WHERE active
UNION ALL SELECT 'achievements_active', count(*) FROM achievements WHERE active
UNION ALL SELECT 'avatars', count(*) FROM avatars
UNION ALL SELECT 'mini_game_runs', count(*) FROM mini_game_runs;
SQL

echo "@@terms"
psql_ro <<'SQL'
SELECT d.version, (SELECT count(*) FROM users u WHERE u.terms_version = d.version)
FROM legal_documents d ORDER BY d.version;
SQL

echo "@@timers"
systemctl list-timers --all --no-pager 'lp-*' 2>&1 | sed '/^$/d' | head -n 8
systemctl is-active lp-firewall.service 2>&1 | sed 's/^/lp-firewall.service: /'

echo "@@sshboot"
# The port this session came in on, and whether boot would listen on it again.
echo "session_port=${SSH_CONNECTION##* }"
echo "socket_enabled=$(systemctl is-enabled ssh.socket 2>/dev/null || echo missing)"
echo "service_enabled=$(systemctl is-enabled ssh.service 2>/dev/null || echo missing)"
listen="$(systemctl show ssh.socket -p Listen --value 2>/dev/null | tr '\n' ' ')"
echo "socket_listen=$listen"
ports="$(sudo -n sshd -T 2>/dev/null | awk '$1 == "port" {printf "%s ", $2}')"
echo "config_ports=$ports"

echo "@@tls"
if [ -r "$base/tls/fullchain.pem" ]; then
    openssl x509 -noout -enddate -in "$base/tls/fullchain.pem" 2>&1
else
    echo "no readable $base/tls/fullchain.pem"
fi

echo "@@backup"
log=/var/log/lottery-passport-backup.log
if [ -r "$log" ]; then
    echo "log_mtime_utc=$(date -u -r "$log" +%Y-%m-%dT%H:%M:%SZ)"
    tail -n 5 "$log"
else
    echo "no readable $log"
fi

echo "@@errors"
api_errors="$("$compose" logs --no-color --since 1h api 2>&1 |
    grep -c -E '"level": ?"(error|critical)"|ERROR|Traceback')"
nginx_5xx="$("$compose" logs --no-color --since 1h nginx 2>&1 |
    grep -c -E '" 5[0-9]{2} ')"
echo "api_error_lines_1h=$api_errors"
echo "nginx_5xx_1h=$nginx_5xx"
echo "@@end"
"""


@dataclass
class Report:
    lines: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, level: str, name: str, detail: str) -> None:
        self.lines.append((level, name, detail))

    @property
    def failed(self) -> bool:
        return any(level == "FAIL" for level, _, _ in self.lines)

    def render(self) -> str:
        return "\n".join(
            f"[{level:<4}] {name}: {detail}" for level, name, detail in self.lines
        )


def split_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in output.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("@@"):
            current = sections.setdefault(line[2:].strip(), [])
        elif current is not None and line.strip():
            current.append(line)
    return sections


def local_git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def local_alembic_head() -> str | None:
    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', text, re.M)
        if revision:
            revisions[revision.group(1)] = down.group(1) if down else None
    parents = set(revisions.values())
    heads = [rev for rev in revisions if rev not in parents]
    return heads[0] if len(heads) == 1 else None


def fetch(url: str) -> tuple[int | str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "lp-server-check"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode(errors="replace")[:300]
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")[:300]
    except (OSError, ValueError) as error:
        return "ERR", str(error)


def run_ssh(arguments: argparse.Namespace) -> tuple[int, str, str]:
    command = [arguments.ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if arguments.port:
        command += ["-p", str(arguments.port)]
    # The script goes to a temp file first and runs from there with stdin
    # at EOF: run as "bash -s", every "docker compose exec -T" inside would
    # swallow the rest of the script from the shared stdin.
    remote = (
        'f="$(mktemp)"; trap \'rm -f "$f"\' EXIT; cat >"$f"; '
        f"bash \"$f\" {arguments.base} '{' '.join(SAFE_ENV_KEYS)}' </dev/null"
    )
    command += [arguments.target, remote]
    # Bytes, not text mode: on Windows text mode turns "\n" into "\r\n" on the
    # way in, and bash on the server chokes on every "\r".
    result = subprocess.run(
        command,
        input=REMOTE_SCRIPT.replace("\r\n", "\n").encode(),
        capture_output=True,
        timeout=arguments.timeout,
    )
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )


def check_public(report: Report, public_url: str) -> str | None:
    commit = None
    for path in ("/health", "/ready"):
        status, body = fetch(public_url.rstrip("/") + path)
        level = "PASS" if status == 200 else "FAIL"
        report.add(level, f"public {path}", f"{status} {body.strip()[:160]}")
        if path == "/health" and status == 200:
            try:
                commit = json.loads(body).get("commit")
            except json.JSONDecodeError:
                pass
    return commit


def check_ssh_boot(report: Report, lines: list[str]) -> None:
    """FAIL if the SSH port of this session would not be listened on after a reboot.

    On Ubuntu >= 22.10 sshd is socket-activated: ``ssh.socket`` owns the port,
    and a port set some other way can fall back to 22 at boot (2026-10-22: a
    production reboot came back without port 2222 and locked everyone out).
    """
    facts = dict(line.split("=", 1) for line in lines if "=" in line)
    port = facts.get("session_port", "").strip()
    if not port.isdigit():
        report.add("WARN", "ssh-boot", f"cannot tell the session port: {facts}")
        return
    if facts.get("socket_enabled", "").strip() == "enabled":
        listens = facts.get("socket_listen", "")
        source = "ssh.socket"
    elif facts.get("service_enabled", "").strip() == "enabled":
        listens = facts.get("config_ports", "")
        source = "sshd config (ssh.service)"
    else:
        report.add("FAIL", "ssh-boot", "neither ssh.socket nor ssh.service is enabled")
        return
    ports = set(re.findall(r"(?:^|[\s:\]])(\d+)(?=\s|$)", listens))
    if port in ports:
        report.add("PASS", "ssh-boot", f"{source} listens on {port} after a reboot")
    else:
        report.add(
            "FAIL",
            "ssh-boot",
            f"session uses port {port} but after a reboot {source} listens on "
            f"{sorted(ports) or 'nothing'}: DO NOT REBOOT (persist the port first)",
        )


def analyse(report: Report, sections: dict[str, list[str]]) -> None:
    for name in ("host", "disk", "deploy", "frontend", "timers", "backup"):
        for line in sections.get(name, []):
            report.add("INFO", name, line)

    env = dict(line.split("=", 1) for line in sections.get("env", []) if "=" in line)
    for key, value in env.items():
        report.add("INFO", "env", f"{key}={value}")
    if env.get("ENVIRONMENT") == "production" and env.get("OTP_TEST_NUMBERS") in {
        "true",
        "1",
    }:
        report.add("FAIL", "env", "OTP_TEST_NUMBERS is on in production")

    for line in sections.get("disk", [])[1:]:
        match = re.search(r"(\d+)%", line)
        if match and int(match.group(1)) >= 85:
            report.add("WARN", "disk", f"over 85% full: {line}")

    for line in sections.get("containers", []):
        parts = line.split("|")
        if len(parts) < 3:
            report.add("FAIL", "containers", line)
            continue
        service, state, health = parts[0], parts[1], parts[2]
        healthy = state == "running" and health in {"", "healthy"}
        report.add("PASS" if healthy else "FAIL", f"container {service}", line)
    if not sections.get("containers"):
        report.add("FAIL", "containers", "compose ps returned nothing")

    for line in sections.get("health", []):
        status = line.split(" ", 2)[1] if " " in line else "?"
        report.add("PASS" if status == "200" else "FAIL", "in-container", line)

    remote_rev = next(iter(sections.get("alembic", [])), "").strip()
    head = local_alembic_head()
    if not remote_rev or "ERROR" in remote_rev:
        report.add("FAIL", "alembic", remote_rev or "no revision")
    elif head and remote_rev != head:
        report.add("WARN", "alembic", f"server {remote_rev}, local head {head}")
    else:
        report.add("PASS", "alembic", remote_rev)

    for name in ("batches", "counts", "terms"):
        for line in sections.get(name, []):
            level = "FAIL" if "ERROR" in line else "INFO"
            report.add(level, name, line)

    terms = {
        line.split("|")[0]: line for line in sections.get("terms", []) if "|" in line
    }
    configured = env.get("TERMS_VERSION")
    if configured and terms and configured not in terms:
        report.add(
            "FAIL",
            "terms",
            f"TERMS_VERSION={configured} has no legal_documents row "
            "(new players cannot accept terms)",
        )

    check_ssh_boot(report, sections.get("sshboot", []))

    for line in sections.get("tls", []):
        match = re.search(r"notAfter=(.+)$", line)
        if not match:
            report.add("WARN", "tls", line)
            continue
        expires = datetime.strptime(match.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
        days = (expires.replace(tzinfo=UTC) - datetime.now(UTC)).days
        report.add("PASS" if days > 14 else "WARN", "tls", f"expires in {days} days")

    errors = dict(
        line.split("=", 1) for line in sections.get("errors", []) if "=" in line
    )
    for key, value in errors.items():
        count = int(value) if value.isdigit() else -1
        report.add("PASS" if count == 0 else "WARN", "errors", f"{key}={value}")

    if "end" not in sections:
        report.add("WARN", "remote", "script did not reach the end (output cut short)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default=os.environ.get("LP_SSH_TARGET"))
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL)
    parser.add_argument("--ssh", default="ssh", help="ssh binary")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--raw", action="store_true", help="also print the raw remote output"
    )
    arguments = parser.parse_args()
    if not arguments.target:
        parser.error("--target (or LP_SSH_TARGET) is required")

    report = Report()
    report.add("INFO", "local", f"git HEAD {local_git('describe', '--tags')}")
    public_commit = check_public(report, arguments.public_url)

    try:
        code, stdout, stderr = run_ssh(arguments)
    except subprocess.TimeoutExpired:
        report.add("FAIL", "ssh", f"timed out after {arguments.timeout} s")
        code, stdout, stderr = -1, "", ""
    if code != 0 and not stdout:
        report.add("FAIL", "ssh", (stderr.strip() or f"exit {code}")[:300])
    else:
        analyse(report, split_sections(stdout))

    if public_commit:
        head = local_git("rev-parse", "--short=7", "HEAD")
        level = "PASS" if head and head.startswith(public_commit) else "WARN"
        report.add(level, "commit", f"public {public_commit}, local HEAD {head}")

    if arguments.raw:
        print(stdout)
        print(stderr, file=sys.stderr)
    print(report.render())
    raise SystemExit(1 if report.failed else 0)


if __name__ == "__main__":
    main()

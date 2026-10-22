"""Pull a production database backup to this machine and prove it restores.

Off-site copy for the campaign (docs/OPERATIONS.md, "Backups and restore"):
the server's own restic repository sits on the same VM, so a lost VM loses
those backups too. This runs on an office PC (Task Scheduler / cron), pulls a
fresh ``pg_dump`` over SSH, and keeps it on local disk.

Steps, each one a hard failure (exit 1) if it goes wrong:

1. ``pg_dump --format=custom`` inside the server's postgres container,
   streamed over SSH into ``<dest>/lottery_passport-<UTC time>.dump.partial``;
   renamed only after the stream ends cleanly and the file starts with the
   ``PGDMP`` magic. A ``.sha256`` file goes next to it.
2. Restore check of THE LOCAL FILE (not of the server's copy):
   ``--verify remote`` (default) sends the file back to a throwaway,
   network-less ``postgres:16-bookworm`` container on the server;
   ``--verify local`` uses Docker on this machine; ``--verify none`` skips it.
   ``pg_restore --exit-on-error``, then sanity queries: row counts, the
   alembic revision, and wallets equal to their ledger (must be 0 mismatches).
3. Retention: every dump of the last ``--keep-days-all`` days, then the newest
   dump of each day up to ``--keep-days`` days; older files are deleted.

Read-only on production (pg_dump takes a consistent snapshot, no locks that
block the app). The dump holds phone numbers: keep ``--dest`` on an encrypted
disk (BitLocker / LUKS) and never in a synced folder.

Usage::

    uv run python -m scripts.backup_pull --target lp-prod --dest D:/lp-backups
    uv run python -m scripts.backup_pull --target lp-prod --dest D:/lp-backups \\
        --verify local --keep-days 90

Windows Task Scheduler, every 6 hours (after the server's own backup)::

    schtasks /Create /TN "LP backup pull" /SC HOURLY /MO 6 /ST 00:30 /TR ^
      "cmd /c cd /d C:\\path\\to\\lottery-passport && uv run python -m ^
      scripts.backup_pull --target lp-prod --dest D:\\lp-backups"
"""

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_BASE = "/opt/lottery-passport"
PREFIX = "lottery_passport-"
SUFFIX = ".dump"
RESTORE_IMAGE = "postgres:16-bookworm"

# Runs inside the restored database; one "name|value" row each.
CHECK_SQL = """
SELECT 'alembic', (SELECT version_num FROM alembic_version)
UNION ALL SELECT 'users', count(*)::text FROM users
UNION ALL SELECT 'code_batches', count(*)::text FROM code_batches
UNION ALL SELECT 'codes', count(*)::text FROM redemption_codes
UNION ALL SELECT 'codes_redeemed', count(*)::text FROM redemption_codes
    WHERE redeemed_at IS NOT NULL
UNION ALL SELECT 'ledger_entries', count(*)::text FROM coin_ledger_entries
UNION ALL SELECT 'wallet_mismatches', count(*)::text FROM wallets w
    LEFT JOIN (SELECT user_id, sum(amount) AS total FROM coin_ledger_entries
               GROUP BY user_id) l USING (user_id)
    WHERE w.balance <> coalesce(l.total, 0);
"""

DUMP_COMMAND = (
    "{base}/repo/deploy/compose.sh exec -T postgres "
    'sh -c \'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
    "--format=custom --compress=6'"
)

# Reads a dump on stdin, restores it into a throwaway container, prints the
# CHECK_SQL rows between @@begin/@@end. Never touches the production stack.
REMOTE_RESTORE = """
set -euo pipefail
work="$(mktemp -d)"
container="lp-restore-pull-$$"
cleanup() {{ docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$work"; }}
trap cleanup EXIT
cat >"$work/db.dump"
docker run -d --name "$container" --network none --memory 1g \\
    -e POSTGRES_PASSWORD=restore-check {image} >/dev/null
for _ in $(seq 1 60); do
    docker exec "$container" pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
done
docker cp "$work/db.dump" "$container:/tmp/db.dump" >/dev/null
docker exec "$container" createdb -U postgres check
docker exec "$container" pg_restore -U postgres -d check --no-owner \\
    --exit-on-error /tmp/db.dump
echo "@@begin"
docker exec -i "$container" psql -X -q -At -F "|" -U postgres -d check <<'SQL'
{sql}
SQL
echo "@@end"
"""


def log(message: str, log_file: Path | None) -> None:
    line = f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {message}"
    print(line, flush=True)
    if log_file:
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def ssh_command(arguments: argparse.Namespace, remote: str) -> list[str]:
    command = [arguments.ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
    command += ["-o", "ServerAliveInterval=30", arguments.target, remote]
    return command


def pull_dump(arguments: argparse.Namespace, dest: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = dest / f"{PREFIX}{stamp}{SUFFIX}"
    partial = final.with_name(final.name + ".partial")
    remote = DUMP_COMMAND.format(base=arguments.base)
    with partial.open("wb") as handle:
        result = subprocess.run(
            ssh_command(arguments, remote),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=arguments.timeout,
        )
    with partial.open("rb") as handle:
        magic = handle.read(5)
    if result.returncode != 0 or magic != b"PGDMP":
        partial.unlink(missing_ok=True)
        error = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"pg_dump failed (exit {result.returncode}, magic {magic!r}): {error}"
        )
    partial.replace(final)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    final.with_name(final.name + ".sha256").write_text(
        f"{digest}  {final.name}\n", encoding="utf-8"
    )
    return final


def parse_rows(output: str) -> dict[str, str]:
    inside = False
    rows: dict[str, str] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if line == "@@begin":
            inside = True
        elif line == "@@end":
            inside = False
        elif inside and "|" in line:
            name, value = line.split("|", 1)
            rows[name] = value
    return rows


def verify_remote(arguments: argparse.Namespace, dump: Path) -> dict[str, str]:
    script = REMOTE_RESTORE.format(image=RESTORE_IMAGE, sql=CHECK_SQL.strip())
    with dump.open("rb") as handle:
        result = subprocess.run(
            ssh_command(arguments, "bash -c " + shlex.quote(script)),
            stdin=handle,
            capture_output=True,
            timeout=arguments.timeout,
        )
    output = result.stdout.decode(errors="replace")
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"remote restore failed (exit {result.returncode}): {error}")
    return parse_rows(output)


def verify_local(arguments: argparse.Namespace, dump: Path) -> dict[str, str]:
    if not shutil.which("docker"):
        raise RuntimeError("--verify local needs Docker on this machine")
    container = f"lp-restore-pull-{int(time.time())}"

    def docker(*args: str, stdin: bytes | None = None) -> str:
        result = subprocess.run(
            ["docker", *args], input=stdin, capture_output=True, timeout=600
        )
        if result.returncode != 0:
            error = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"docker {args[0]} failed: {error}")
        return result.stdout.decode(errors="replace")

    docker("run", "-d", "--name", container, "--network", "none", "-e",
           "POSTGRES_PASSWORD=restore-check", RESTORE_IMAGE)  # fmt: skip
    try:
        for _ in range(60):
            check = ["docker", "exec", container, "pg_isready", "-U", "postgres"]
            if subprocess.run(check, capture_output=True).returncode == 0:
                break
            time.sleep(1)
        docker("cp", str(dump), f"{container}:/tmp/db.dump")
        docker("exec", container, "createdb", "-U", "postgres", "check")
        docker("exec", container, "pg_restore", "-U", "postgres", "-d", "check",
               "--no-owner", "--exit-on-error", "/tmp/db.dump")  # fmt: skip
        output = docker("exec", "-i", container, "psql", "-X", "-q", "-At", "-F",
                        "|", "-U", "postgres", "-d", "check",
                        stdin=CHECK_SQL.encode())  # fmt: skip
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    return parse_rows("@@begin\n" + output + "\n@@end")


def prune(dest: Path, keep_days_all: int, keep_days: int) -> list[Path]:
    now = datetime.now(UTC)
    dumps = sorted(dest.glob(f"{PREFIX}*{SUFFIX}"), reverse=True)  # newest first
    seen_days: set[str] = set()
    removed: list[Path] = []
    for dump in dumps:
        stamp = dump.name[len(PREFIX) : -len(SUFFIX)]
        try:
            taken = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        age = now - taken
        day = stamp[:8]
        keep = age <= timedelta(days=keep_days_all) or (
            age <= timedelta(days=keep_days) and day not in seen_days
        )
        seen_days.add(day)
        if not keep:
            dump.unlink()
            dump.with_name(dump.name + ".sha256").unlink(missing_ok=True)
            removed.append(dump)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, help="ssh alias or user@host")
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument(
        "--verify", choices=("remote", "local", "none"), default="remote"
    )
    parser.add_argument("--keep-days-all", type=int, default=7)
    parser.add_argument("--keep-days", type=int, default=60)
    parser.add_argument("--ssh", default="ssh")
    parser.add_argument("--timeout", type=int, default=1800)
    arguments = parser.parse_args()

    dest: Path = arguments.dest
    dest.mkdir(parents=True, exist_ok=True)
    log_file = dest / "backup_pull.log"
    try:
        started = time.monotonic()
        dump = pull_dump(arguments, dest)
        size_kb = dump.stat().st_size // 1024
        log(f"pulled {dump.name} ({size_kb} KB) in "
            f"{time.monotonic() - started:.1f} s", log_file)  # fmt: skip

        if arguments.verify != "none":
            started = time.monotonic()
            verify = verify_remote if arguments.verify == "remote" else verify_local
            rows = verify(arguments, dump)
            took = time.monotonic() - started
            if "alembic" not in rows:
                raise RuntimeError(f"restore check returned no rows: {rows}")
            if rows.get("wallet_mismatches") != "0":
                raise RuntimeError(f"wallets do not match the ledger: {rows}")
            log(f"restore check ({arguments.verify}) ok in {took:.1f} s: "
                f"{json.dumps(rows)}", log_file)  # fmt: skip

        for removed in prune(dest, arguments.keep_days_all, arguments.keep_days):
            log(f"pruned {removed.name}", log_file)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        log(f"FAILED: {error}", log_file)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

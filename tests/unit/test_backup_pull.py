from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.backup_pull import PREFIX, SUFFIX, parse_rows, prune


def make_dump(dest: Path, taken: datetime) -> Path:
    path = dest / f"{PREFIX}{taken:%Y%m%dT%H%M%SZ}{SUFFIX}"
    path.write_bytes(b"PGDMP")
    path.with_name(path.name + ".sha256").write_text("x", encoding="utf-8")
    return path


def test_prune_keeps_recent_dumps_and_one_per_day_up_to_the_limit(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    recent = [make_dump(tmp_path, now - timedelta(hours=h)) for h in (1, 7, 13)]
    old_day = (now - timedelta(days=20)).replace(hour=18, minute=0, second=0)
    newest_of_old_day = make_dump(tmp_path, old_day)
    older_same_day = make_dump(tmp_path, old_day - timedelta(hours=6))
    too_old = make_dump(tmp_path, now - timedelta(days=90))

    removed = prune(tmp_path, keep_days_all=7, keep_days=60)

    assert set(removed) == {older_same_day, too_old}
    for kept in [*recent, newest_of_old_day]:
        assert kept.exists()
    assert not too_old.with_name(too_old.name + ".sha256").exists()


def test_prune_ignores_unrelated_files(tmp_path: Path) -> None:
    other = tmp_path / "backup_pull.log"
    other.write_text("log", encoding="utf-8")
    assert prune(tmp_path, keep_days_all=0, keep_days=0) == []
    assert other.exists()


def test_parse_rows_reads_only_between_markers() -> None:
    output = "noise|1\n@@begin\nusers|6\nwallet_mismatches|0\n@@end\nafter|2\n"
    assert parse_rows(output) == {"users": "6", "wallet_mismatches": "0"}

from scripts.server_check import Report, analyse, local_alembic_head, split_sections

# The server's alembic revision is compared with the repo's own head, so the
# healthy fixture uses that head instead of a literal: a literal broke this
# test on every new migration (0023_media_assets was the first to hit it).
HEAD_REVISION = local_alembic_head()

HEALTHY = f"""\
@@host
hostname=play-vm
@@env
ENVIRONMENT=production
TERMS_VERSION=2026-10-20
OTP_TEST_NUMBERS=false
@@containers
api|running|healthy|Up 2 hours (healthy)
nginx|running||Up 2 hours
postgres|running|healthy|Up 2 hours (healthy)
@@health
/health 200 {{"status":"ok"}}
/ready 200 {{"status":"ok"}}
@@alembic
{HEAD_REVISION}
@@terms
2026-10-20|3
@@sshboot
session_port=2222
socket_enabled=enabled
service_enabled=disabled
socket_listen=[::]:2222 (Stream)
config_ports=2222
@@tls
notAfter=Jan  1 00:00:00 2099 GMT
@@errors
api_error_lines_1h=0
nginx_5xx_1h=0
@@end
"""


def levels(output: str) -> dict[str, set[str]]:
    report = Report()
    analyse(report, split_sections(output))
    result: dict[str, set[str]] = {}
    for level, name, _ in report.lines:
        result.setdefault(level, set()).add(name)
    return result


def test_a_healthy_server_has_no_failures_or_warnings() -> None:
    found = levels(HEALTHY)
    assert "FAIL" not in found
    assert "WARN" not in found


def test_an_unhealthy_container_and_a_failed_ready_fail() -> None:
    output = HEALTHY.replace("api|running|healthy", "api|running|unhealthy").replace(
        "/ready 200", "/ready 503"
    )
    assert {"container api", "in-container"} <= levels(output)["FAIL"]


def test_terms_version_without_a_document_row_fails() -> None:
    output = HEALTHY.replace("TERMS_VERSION=2026-10-20", "TERMS_VERSION=2026-10-22")
    assert "terms" in levels(output)["FAIL"]


def test_test_otp_numbers_in_production_fail() -> None:
    output = HEALTHY.replace("OTP_TEST_NUMBERS=false", "OTP_TEST_NUMBERS=true")
    assert "env" in levels(output)["FAIL"]


def test_a_server_behind_the_repo_head_warns() -> None:
    # The normal state between a merged migration and its release.
    behind = "@@alembic\n0001_initial\n"
    output = HEALTHY.replace(f"@@alembic\n{HEAD_REVISION}\n", behind)
    assert "alembic" in levels(output)["WARN"]


def test_a_cut_short_run_warns() -> None:
    assert "remote" in levels(HEALTHY.replace("@@end\n", ""))["WARN"]


def test_a_socket_that_would_come_back_on_22_fails() -> None:
    output = HEALTHY.replace(
        "socket_listen=[::]:2222 (Stream)", "socket_listen=[::]:22 (Stream)"
    )
    assert "ssh-boot" in levels(output)["FAIL"]


def test_ssh_service_without_socket_uses_the_sshd_config_ports() -> None:
    output = HEALTHY.replace(
        "socket_enabled=enabled", "socket_enabled=disabled"
    ).replace("service_enabled=disabled", "service_enabled=enabled")
    assert "FAIL" not in levels(output)
    broken = output.replace("config_ports=2222", "config_ports=22")
    assert "ssh-boot" in levels(broken)["FAIL"]

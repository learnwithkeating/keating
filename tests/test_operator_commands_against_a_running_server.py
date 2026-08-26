# ABOUTME: Tests that the operator subcommands work the way the README tells operators to run
# ABOUTME: them — from a second process, against a server that is already serving.

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from main import INSTANCE_DIR_NAME, SESSION_COOKIE_NAME

from .conftest import TEST_PASSWORD

REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR = "operator"
LEARNER_PASSWORD = "learner-long-enough-password"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _env(workspace: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["KEATING_WORKSPACE_ROOT"] = str(workspace)
    env["KEATING_LEGACY_SETTINGS_PATH"] = str(workspace / "nonexistent-settings.json")
    # Empty rather than removed: load_dotenv does not override a variable that is present, and
    # only a present one is. Popping it would let the checkout's own .env put a real key back.
    env["ANTHROPIC_API_KEY"] = ""
    return env


def _cli(workspace: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=str(REPO_ROOT),
        env=_env(workspace),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, str]]:
    """A real server on a real port, with a real account store, and the CLI reaching that same
    store from outside the server process. That second process is the whole point: `docker exec
    ... python main.py disable <name>` is by construction not the server, and every one of
    these commands is documented as being run that way while the instance is up."""
    workspace = tmp_path_factory.mktemp("keating-operator-workspace")
    (workspace / "a-course").mkdir()
    bootstrap = _cli(workspace, "bootstrap", "--username", OPERATOR, stdin=TEST_PASSWORD + "\n")
    assert bootstrap.returncode == 0, bootstrap.stderr

    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=_env(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode("utf-8", "replace") if process.stdout else ""
            raise RuntimeError(f"server exited early (code {process.returncode}):\n{output}")
        try:
            httpx.get(f"{base_url}/api/session", timeout=2.0).raise_for_status()
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        process.terminate()
        raise RuntimeError("server never became ready")

    try:
        yield workspace, base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _login(base_url: str, username: str, password: str) -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/login", json={"username": username, "password": password}, timeout=5.0
    )


def _as(base_url: str, cookie: str, path: str) -> httpx.Response:
    # The session cookie is Secure and this URL is http://, and httpx stores such a cookie but
    # never sends it back. An explicit header is what carries it here.
    return httpx.get(
        f"{base_url}{path}", headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"}, timeout=5.0
    )


def _invites_on_disk(workspace: Path) -> list[dict]:
    stored = json.loads((workspace / INSTANCE_DIR_NAME / "accounts.json").read_text())
    return stored["invites"]


def _sign_up_a_learner(workspace: Path, base_url: str, username: str) -> str:
    """An invite issued by the operator and redeemed over HTTP, returning a live cookie. A name
    per test, because accounts are never deleted and this server outlives each one."""
    invite = _cli(workspace, "invite")
    assert invite.returncode == 0, invite.stderr
    code = invite.stdout.split("single use):")[1].strip().splitlines()[0].strip()
    redeemed = httpx.post(
        f"{base_url}/api/invite/redeem",
        json={"code": code, "username": username, "password": LEARNER_PASSWORD},
        timeout=10.0,
    )
    assert redeemed.status_code == 200, redeemed.text
    signed_in = _login(base_url, username, LEARNER_PASSWORD)
    assert signed_in.status_code == 200, signed_in.text
    return signed_in.cookies[SESSION_COOKIE_NAME]


def test_an_invite_survives_the_running_servers_next_write(live: tuple[Path, str]) -> None:
    """The sharpest shape of the bug this guards: the operator issues an invite, one stranger
    guesses one password wrong, and the failed-attempt counter's write serializes the server's
    copy of the store over the invite — which vanishes with no error anywhere."""
    workspace, base_url = live
    issued = _cli(workspace, "invite")
    assert issued.returncode == 0, issued.stderr
    assert len(_invites_on_disk(workspace)) == 1

    assert _login(base_url, OPERATOR, "definitely-the-wrong-password").status_code == 401

    assert len(_invites_on_disk(workspace)) == 1
    revoked = _cli(workspace, "revoke-invite", "0")
    assert revoked.returncode == 0, revoked.stderr


def test_an_invite_issued_while_the_server_runs_is_redeemable_without_a_restart(
    live: tuple[Path, str],
) -> None:
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "redeemer")

    assert _as(base_url, cookie, "/api/courses").status_code == 200


def test_disable_ends_a_live_session_without_a_restart(live: tuple[Path, str]) -> None:
    """`disable` that only takes effect at the next restart is not a disable — it is a note to
    self. The account being disabled is usually the reason the operator is at the terminal."""
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "disabled-one")
    assert _as(base_url, cookie, "/api/courses").status_code == 200

    disabled = _cli(workspace, "disable", "disabled-one")

    assert disabled.returncode == 0, disabled.stderr
    assert _as(base_url, cookie, "/api/courses").status_code == 401
    assert _login(base_url, "disabled-one", LEARNER_PASSWORD).status_code == 401


def test_revoke_sessions_ends_a_live_session_without_a_restart(live: tuple[Path, str]) -> None:
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "revoked-one")
    assert _as(base_url, cookie, "/api/courses").status_code == 200

    revoked = _cli(workspace, "revoke-sessions", "--username", "revoked-one")

    assert revoked.returncode == 0, revoked.stderr
    assert "Ended 1 session(s)." in revoked.stdout
    assert _as(base_url, cookie, "/api/courses").status_code == 401


def test_set_password_takes_effect_on_the_running_server(live: tuple[Path, str]) -> None:
    """The out-of-band password reset is the only reset this app has. If the new password does
    not work until someone restarts the container, the person locked out stays locked out."""
    workspace, base_url = live
    _sign_up_a_learner(workspace, base_url, "reset-one")
    replacement = "a-brand-new-long-password"

    reset = _cli(workspace, "set-password", "reset-one", stdin=replacement + "\n")

    assert reset.returncode == 0, reset.stderr
    assert _login(base_url, "reset-one", replacement).status_code == 200
    assert _login(base_url, "reset-one", LEARNER_PASSWORD).status_code == 401


def test_the_accounts_listing_sees_an_account_the_server_created(live: tuple[Path, str]) -> None:
    """The other direction: a write the SERVER made, read by the CLI. Invite redemption is the
    one account-creating path that runs inside the server process."""
    workspace, base_url = live
    _sign_up_a_learner(workspace, base_url, "listed-one")

    listed = _cli(workspace, "accounts")

    assert listed.returncode == 0, listed.stderr
    assert "listed-one" in listed.stdout


def _post_as(base_url: str, cookie: str, path: str, **kwargs) -> httpx.Response:
    return httpx.post(
        f"{base_url}{path}",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"},
        timeout=10.0,
        **kwargs,
    )


def _upload_as(base_url: str, cookie: str, course: str) -> httpx.Response:
    """An author-only route that changes nothing a later test depends on."""
    return _post_as(
        base_url,
        cookie,
        "/api/upload",
        files={"file": ("syllabus.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"course": course},
    )


def test_enroll_takes_effect_on_the_running_server_without_a_restart(
    live: tuple[Path, str],
) -> None:
    """An enrollment that lands only at the next restart is an enrollment that does not work:
    the operator and the person waiting to be let in are usually in the same conversation."""
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "enrolled-one")
    assert _as(base_url, cookie, "/api/course-overview?course=a-course").status_code == 404

    enrolled = _cli(workspace, "enroll", "--username", "enrolled-one", "--course", "a-course")

    assert enrolled.returncode == 0, enrolled.stderr
    assert _as(base_url, cookie, "/api/course-overview?course=a-course").status_code == 200


def test_set_role_promotes_a_learner_on_the_running_server(live: tuple[Path, str]) -> None:
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "promoted-one")
    assert (
        _cli(workspace, "enroll", "--username", "promoted-one", "--course", "a-course").returncode
        == 0
    )
    assert _upload_as(base_url, cookie, "a-course").status_code == 403

    promoted = _cli(
        workspace, "set-role", "--username", "promoted-one", "--course", "a-course", "--role", "author"
    )

    assert promoted.returncode == 0, promoted.stderr
    assert _upload_as(base_url, cookie, "a-course").status_code == 200


def test_unenroll_refuses_the_next_request_and_leaves_the_record_on_disk(
    live: tuple[Path, str],
) -> None:
    """Removing access is not destroying a record. An admin deleting someone's learning is
    exactly what P25 forbids."""
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "removed-one")
    assert (
        _cli(workspace, "enroll", "--username", "removed-one", "--course", "a-course").returncode == 0
    )
    saved = _post_as(
        base_url,
        cookie,
        "/api/glossary",
        json={"course": "a-course", "term": "spacing", "definition": "gaps between study."},
    )
    assert saved.status_code == 200, saved.text
    learners = list((workspace / "a-course" / "learners").iterdir())
    assert learners, "the learner wrote nothing, so this proves nothing about deletion"

    removed = _cli(workspace, "unenroll", "--username", "removed-one", "--course", "a-course")

    assert removed.returncode == 0, removed.stderr
    assert _as(base_url, cookie, "/api/course-overview?course=a-course").status_code == 404
    assert sorted(p.name for p in (workspace / "a-course" / "learners").iterdir()) == sorted(
        p.name for p in learners
    )


def test_the_enrollments_listing_sees_an_enrollment_the_server_created(
    live: tuple[Path, str],
) -> None:
    """The other direction: a write the SERVER made, read by the CLI. Creating a course is the
    one enrolling path that runs inside the server process."""
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "creator-one")
    created = _post_as(base_url, cookie, "/api/courses", json={"slug": "made-in-the-app"})
    assert created.status_code == 200, created.text

    listed = _cli(workspace, "enrollments", "--course", "made-in-the-app")

    assert listed.returncode == 0, listed.stderr
    assert "creator-one" in listed.stdout
    assert "author" in listed.stdout


def test_the_enrollments_listing_shows_no_activity_of_any_kind(live: tuple[Path, str]) -> None:
    """Enrollment metadata is an administrative fact about access. Anything whose answer
    changes when the learner studies is a record, and P25 puts it out of reach — of an admin
    too. This is that rule as a regression test."""
    workspace, base_url = live
    cookie = _sign_up_a_learner(workspace, base_url, "quiet-one")
    assert (
        _cli(workspace, "enroll", "--username", "quiet-one", "--course", "a-course").returncode == 0
    )
    _post_as(
        base_url,
        cookie,
        "/api/glossary",
        json={"course": "a-course", "term": "encoding", "definition": "getting it in."},
    )

    listed = _cli(workspace, "enrollments")

    assert listed.returncode == 0, listed.stderr
    lowered = listed.stdout.lower()
    for forbidden in (
        "last",
        "active",
        "attempt",
        "due",
        "record",
        "practice",
        "progress",
        "streak",
        "session",
    ):
        assert forbidden not in lowered, forbidden


def test_enroll_refuses_an_unknown_username_and_an_unknown_course(live: tuple[Path, str]) -> None:
    workspace, _ = live

    no_such_account = _cli(workspace, "enroll", "--username", "nobody", "--course", "a-course")
    no_such_course = _cli(workspace, "enroll", "--username", OPERATOR, "--course", "no-such-course")

    assert no_such_account.returncode == 1
    assert "nobody" in no_such_account.stderr
    assert no_such_course.returncode == 1
    assert "a-course" in no_such_course.stderr, "the message should name the slugs that do exist"

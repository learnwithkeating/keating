# ABOUTME: Tests for the password hashing, the session store and the private on-disk layout the
# ABOUTME: accounts and sessions files use under the workspace's instance directory.

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import (
    INSTANCE_DIR_NAME,
    SESSION_COOKIE_NAME,
    bootstrap_account,
    hash_password,
    verify_password,
)

from .conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace WORKSPACE_ROOT points at for one test. The account, session and
    session-key paths all resolve from it, so this is the only wiring an auth test needs."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


# --- Passwords ----------------------------------------------------------------


def test_a_password_verifies_against_its_own_hash() -> None:
    assert verify_password(hash_password(TEST_PASSWORD), TEST_PASSWORD)


def test_a_wrong_password_is_a_failed_login() -> None:
    assert not verify_password(hash_password(TEST_PASSWORD), TEST_PASSWORD + "!")


def test_a_corrupt_stored_hash_is_a_failed_login_not_a_crash() -> None:
    """argon2's InvalidHashError is not a subclass of VerificationError, so catching only the
    latter turns a hand-edited accounts.json into a 500 on every login attempt."""
    assert not verify_password("not-an-argon2-hash", TEST_PASSWORD)
    assert not verify_password("", TEST_PASSWORD)


def test_hashes_use_argon2id_at_the_rfc_9106_low_memory_profile() -> None:
    assert hash_password(TEST_PASSWORD).startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_two_hashes_of_one_password_differ() -> None:
    """A per-hash salt, which is what makes the stored hashes non-comparable across accounts."""
    assert hash_password(TEST_PASSWORD) != hash_password(TEST_PASSWORD)


def test_a_hash_at_older_parameters_is_upgraded_on_a_successful_login(workspace: Path) -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1).hash(TEST_PASSWORD)
    account = bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    account["password_hash"] = weak
    main.save_accounts()

    assert main.authenticate(TEST_USERNAME, TEST_PASSWORD) is not None

    upgraded = main.find_account(TEST_USERNAME)["password_hash"]
    assert upgraded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    stored = json.loads(main.accounts_path().read_text(encoding="utf-8"))
    assert stored["accounts"][0]["password_hash"] == upgraded


def test_an_unknown_username_still_runs_a_verification(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returning early on a username miss leaks which accounts exist through response timing.
    Counted rather than timed: a wall-clock assertion is flaky and this suite stays pristine."""
    calls: list[str] = []
    real = main.verify_password

    def counting(stored_hash: str, password: str) -> bool:
        calls.append(stored_hash)
        return real(stored_hash, password)

    monkeypatch.setattr(main, "verify_password", counting)
    assert main.authenticate("nobody-by-that-name", TEST_PASSWORD) is None
    assert calls == [main.DUMMY_PASSWORD_HASH]


def test_a_password_under_the_minimum_is_refused() -> None:
    with pytest.raises(ValueError, match=str(main.PASSWORD_MIN_LENGTH)):
        main.validate_password("short")


def test_a_password_over_the_maximum_is_refused() -> None:
    """An unbounded password is an unbounded amount of argon2 work per login attempt."""
    with pytest.raises(ValueError, match=str(main.PASSWORD_MAX_LENGTH)):
        main.validate_password("x" * (main.PASSWORD_MAX_LENGTH + 1))


# --- Sessions -----------------------------------------------------------------


def test_session_ids_are_distinct_and_carry_256_bits(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    values = {main.issue_session(main.DEFAULT_USER_ID, "local") for _ in range(20)}
    assert len(values) == 20
    for value in values:
        sid, _, signature = value.partition(".")
        # token_urlsafe(32) is 32 random bytes base64url-encoded: 43 characters.
        assert len(sid) == 43
        assert signature


def test_a_tampered_signature_is_rejected(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")
    sid, _, signature = value.partition(".")
    assert main.lookup_session(value) is not None
    assert main.lookup_session(f"{sid}.{'0' * len(signature)}") is None
    assert main.lookup_session(sid) is None
    assert main.lookup_session("") is None


def test_a_valid_signature_over_an_unknown_id_is_still_refused(workspace: Path) -> None:
    """The signature is pre-screening; the server record is the authority. A correctly signed
    id with no record behind it is exactly what a revoked session looks like."""
    import secrets

    sid = secrets.token_urlsafe(32)
    forged = f"{sid}.{main.sign_session_id(sid)}"
    assert main.lookup_session(forged) is None


def test_a_cookie_whose_record_is_gone_is_rejected(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")
    assert main.lookup_session(value) is not None

    main.revoke_sessions_for_user(main.DEFAULT_USER_ID)

    assert main.lookup_session(value) is None


def test_login_mints_a_new_session_id_and_kills_the_old_one(workspace: Path) -> None:
    """Session fixation: a value presented to the login route is never reused or re-signed."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        first = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        old = first.cookies[SESSION_COOKIE_NAME]

        second = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        new = second.cookies[SESSION_COOKIE_NAME]

    assert old != new
    assert main.lookup_session(old) is None
    assert main.lookup_session(new) is not None


def test_logout_deletes_the_record_server_side(workspace: Path) -> None:
    """The replayed cookie has to be refused by the server, not merely dropped by the client:
    a client-side-only session is revocable by nobody."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        value = client.cookies[SESSION_COOKIE_NAME]
        assert client.get("/api/courses").status_code == 200

        assert client.post("/api/logout").status_code == 200

        replayed = client.get("/api/courses", headers={"Cookie": f"{SESSION_COOKIE_NAME}={value}"})

    assert replayed.status_code == 401
    assert main.lookup_session(value) is None


def test_an_expired_session_is_refused_and_swept(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")
    digest = main.session_id_digest(value.partition(".")[0])
    with main.store_transaction():
        main.SESSIONS["sessions"][digest]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        main.save_sessions()

    assert main.lookup_session(value) is None
    assert digest not in main.SESSIONS["sessions"]


def test_the_session_store_holds_only_hashed_session_ids(workspace: Path) -> None:
    """The file at rest must not be a bag of live credentials."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")
    sid = value.partition(".")[0]

    written = main.sessions_path().read_text(encoding="utf-8")

    assert sid not in written
    assert main.session_id_digest(sid) in written


def test_the_session_cookie_is_httponly_secure_and_lax(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        response = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )

    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header
    # __Host- prefixed cookies must carry no Domain attribute, or browsers reject them.
    assert "Domain=" not in header


def test_accounts_and_sessions_reload_after_a_restart(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")

    main.ACCOUNTS.clear()
    main.ACCOUNTS.update(main.empty_accounts())
    main.SESSIONS.clear()
    main.SESSIONS.update(main.empty_sessions())
    with TestClient(main.app, base_url="https://testserver"):
        pass

    assert main.find_account(TEST_USERNAME) is not None
    assert main.lookup_session(value) is not None


def test_the_signing_key_survives_a_restart(workspace: Path) -> None:
    """An in-memory key logs every user out every time the container is replaced."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    first = main.session_key()
    main.SESSION_KEY.clear()

    assert main.session_key() == first


# --- The files on disk --------------------------------------------------------


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_instance_directory_is_owner_only(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    assert _mode(workspace / INSTANCE_DIR_NAME) == 0o700


def test_the_account_session_and_key_files_are_owner_only(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    main.issue_session(main.DEFAULT_USER_ID, "local")
    main.session_key()

    for path in (main.accounts_path(), main.sessions_path(), main.session_key_path()):
        assert path.is_file(), path
        assert _mode(path) == 0o600, path


def test_a_private_file_is_never_world_readable_even_briefly(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode has to come from how the temp file is created, not from a chmod after the
    write: a chmod-after leaves a window in which the credential file is readable."""
    seen: list[int] = []
    real_replace = main.os.replace

    def watching(src, dst):  # noqa: ANN001 - mirrors os.replace
        seen.append(_mode(Path(src)))
        return real_replace(src, dst)

    monkeypatch.setattr(main.os, "replace", watching)
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert seen
    assert set(seen) == {0o600}


def test_an_interrupted_write_leaves_the_previous_file_intact(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    before = main.accounts_path().read_text(encoding="utf-8")

    def explode(src, dst):  # noqa: ANN001 - mirrors os.replace
        raise OSError("interrupted")

    monkeypatch.setattr(main.os, "replace", explode)
    main.ACCOUNTS["accounts"][0]["username"] = "clobbered"
    with pytest.raises(OSError, match="interrupted"):
        main.save_accounts()

    assert main.accounts_path().read_text(encoding="utf-8") == before


def test_the_stores_live_in_the_instance_directory(workspace: Path) -> None:
    instance = workspace / INSTANCE_DIR_NAME
    assert main.accounts_path().parent == instance
    assert main.sessions_path().parent == instance
    assert main.session_key_path().parent == instance

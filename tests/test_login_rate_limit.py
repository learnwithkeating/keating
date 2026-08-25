# ABOUTME: Tests for the per-account lockout that bounds password guessing, and for the uniform
# ABOUTME: answer that keeps the account set private on an invite-only instance.

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import bootstrap_account

from .conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _fail_login(client, times: int = 1):
    response = None
    for _ in range(times):
        response = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": "wrong-password-here"}
        )
    return response


def _login(client):
    return client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})


def test_five_failed_logins_lock_the_account(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT)

    account = main.find_account(TEST_USERNAME)
    assert account["failed_attempts"] >= main.LOGIN_FAILURE_LIMIT
    assert account["locked_until"] is not None


def test_a_locked_account_refuses_the_correct_password(
    workspace: Path, unauthenticated_client
) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT)

    assert _login(unauthenticated_client).status_code == 401


def test_the_lock_expires_after_its_window(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT)

    # Through a transaction, because the store on disk is the authority: an edit left only in
    # this process's cache is discarded the next time anything re-reads the file.
    with main.store_transaction():
        main.find_account(TEST_USERNAME)["locked_until"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        main.save_accounts()

    assert _login(unauthenticated_client).status_code == 200


def test_a_successful_login_clears_the_counter(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT - 1)

    assert _login(unauthenticated_client).status_code == 200

    account = main.find_account(TEST_USERNAME)
    assert account["failed_attempts"] == 0
    assert account["locked_until"] is None


def test_the_lockout_survives_a_restart(workspace: Path) -> None:
    """A counter held only in memory is cleared by restarting the process, which an attacker
    who can reach the app usually cannot do — but a crash loop would do it for them."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        _fail_login(client, main.LOGIN_FAILURE_LIMIT)

    stored = json.loads(main.accounts_path().read_text(encoding="utf-8"))
    assert stored["accounts"][0]["locked_until"] is not None

    main.ACCOUNTS.clear()
    main.ACCOUNTS.update(main.empty_accounts())
    with TestClient(main.app, base_url="https://testserver") as client:
        assert _login(client).status_code == 401


def test_a_locked_account_is_indistinguishable_from_a_wrong_password(
    workspace: Path, unauthenticated_client
) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    wrong = _fail_login(unauthenticated_client)

    locked = _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT)

    assert locked.status_code == wrong.status_code
    assert locked.json() == wrong.json()


def test_an_unknown_username_is_indistinguishable_from_a_wrong_password(
    workspace: Path, unauthenticated_client
) -> None:
    """An oracle that separates "no such user" from "wrong password" enumerates the account
    set, which on an invite-only instance is meant to be private."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    wrong = _fail_login(unauthenticated_client)

    unknown = unauthenticated_client.post(
        "/api/login", json={"username": "nobody-by-that-name", "password": "wrong-password-here"}
    )

    assert unknown.status_code == wrong.status_code
    assert unknown.json() == wrong.json()


def test_a_disabled_account_is_indistinguishable_and_cannot_log_in(
    workspace: Path, unauthenticated_client
) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    wrong = _fail_login(unauthenticated_client)
    with main.store_transaction():
        account = main.find_account(TEST_USERNAME)
        account["disabled"] = True
        # Zeroed so the refusal below can only be the disabled flag, never a lingering lockout.
        account["failed_attempts"] = 0
        account["locked_until"] = None
        main.save_accounts()

    response = _login(unauthenticated_client)

    assert response.status_code == wrong.status_code
    assert response.json() == wrong.json()


def test_disabling_an_account_revokes_its_live_sessions(workspace: Path) -> None:
    """Otherwise "disabled" means "cannot log in again", and whoever is already signed in
    stays signed in for the rest of the session's seven days."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    value = main.issue_session(main.DEFAULT_USER_ID, "local")

    main.set_account_disabled(TEST_USERNAME, True)

    assert main.lookup_session(value) is None


def test_the_lockout_is_not_announced_to_the_caller(
    workspace: Path, unauthenticated_client
) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    response = _fail_login(unauthenticated_client, main.LOGIN_FAILURE_LIMIT)

    body = json.dumps(response.json()).lower()
    assert "lock" not in body
    assert "attempt" not in body


def test_concurrent_verifications_are_bounded(workspace: Path) -> None:
    """argon2 at these parameters allocates 64 MiB per call, so an unbounded login endpoint is
    a memory-exhaustion primitive as much as a guessing surface."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    live = 0
    peak = 0
    import threading

    guard = threading.Lock()
    real = main._verify_hash

    def watched(stored_hash: str, password: str) -> bool:
        nonlocal live, peak
        with guard:
            live += 1
            peak = max(peak, live)
        try:
            return real(stored_hash, password)
        finally:
            with guard:
                live -= 1

    main._verify_hash = watched
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda _: main.verify_password(main.DUMMY_PASSWORD_HASH, "x"), range(16)))
    finally:
        main._verify_hash = real

    assert peak <= main.PASSWORD_HASHING_CONCURRENCY

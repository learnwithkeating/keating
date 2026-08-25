# ABOUTME: Tests for invite-only registration: codes are single-use, redemption mints the user id
# ABOUTME: itself, and there is no route anywhere that creates an account without a code.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import main
from main import DEFAULT_USER_ID, bootstrap_account

from .conftest import TEST_PASSWORD, TEST_USERNAME


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _redeem(client, code: str, username: str = "invitee") -> object:
    return client.post(
        "/api/invite/redeem",
        json={"code": code, "username": username, "password": TEST_PASSWORD},
    )


def test_an_invite_code_is_redeemable_once(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    first = _redeem(unauthenticated_client, code)
    second = _redeem(unauthenticated_client, code, username="second-invitee")

    assert first.status_code == 200
    assert second.status_code == 400
    assert [a["username"] for a in main.ACCOUNTS["accounts"]] == [TEST_USERNAME, "invitee"]


def test_a_redeemed_invite_is_gone_from_the_store(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    _redeem(unauthenticated_client, code)

    assert main.ACCOUNTS["invites"] == []
    stored = json.loads(main.accounts_path().read_text(encoding="utf-8"))
    assert stored["invites"] == []


def test_the_invite_store_holds_only_hashed_codes(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    assert code not in main.accounts_path().read_text(encoding="utf-8")


def test_an_unknown_or_tampered_code_is_refused(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    assert _redeem(unauthenticated_client, "not-a-code").status_code == 400
    assert _redeem(unauthenticated_client, code[:-1] + "x").status_code == 400
    assert _redeem(unauthenticated_client, "").status_code in (400, 422)
    assert [a["username"] for a in main.ACCOUNTS["accounts"]] == [TEST_USERNAME]


def test_an_expired_invite_is_refused(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)
    with main.store_transaction():
        main.ACCOUNTS["invites"][0]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        main.save_accounts()

    assert _redeem(unauthenticated_client, code).status_code == 400


def test_redemption_never_takes_a_user_id_from_the_request(
    workspace: Path, unauthenticated_client
) -> None:
    """The sharpest way this increment could be defeated: if a redeemer could name their own
    user id, the second account types "default" and reads the first account's whole record."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    response = unauthenticated_client.post(
        "/api/invite/redeem",
        json={
            "code": code,
            "username": "invitee",
            "password": TEST_PASSWORD,
            "user_id": DEFAULT_USER_ID,
        },
    )

    assert response.status_code in (200, 422)
    created = main.find_account("invitee")
    if created is not None:
        assert created["user_id"] != DEFAULT_USER_ID


def test_redemption_refuses_a_taken_username(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    response = _redeem(unauthenticated_client, code, username=TEST_USERNAME)

    assert response.status_code == 400
    # The invite is not consumed by an attempt that created nothing.
    assert len(main.ACCOUNTS["invites"]) == 1


def test_redemption_refuses_a_short_password(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    response = unauthenticated_client.post(
        "/api/invite/redeem",
        json={"code": code, "username": "invitee", "password": "short"},
    )

    assert response.status_code == 400
    assert len(main.ACCOUNTS["invites"]) == 1


def test_redemption_creates_the_account_and_consumes_the_invite_in_one_write(
    workspace: Path, unauthenticated_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two files, or two writes, leave a window where the invite is spent and no account
    exists — which on an invite-only instance locks the invitee out permanently."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    writes: list[dict] = []
    real = main.save_accounts

    def counting() -> None:
        writes.append(json.loads(json.dumps(main.ACCOUNTS)))
        real()

    monkeypatch.setattr(main, "save_accounts", counting)
    assert _redeem(unauthenticated_client, code).status_code == 200

    assert len(writes) == 1
    assert writes[0]["invites"] == []
    assert [a["username"] for a in writes[0]["accounts"]] == [TEST_USERNAME, "invitee"]


def test_an_invitee_can_log_in_afterwards(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)
    _redeem(unauthenticated_client, code)

    response = unauthenticated_client.post(
        "/api/login", json={"username": "invitee", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200


def test_redemption_does_not_log_the_new_account_in(workspace: Path, unauthenticated_client) -> None:
    """Redeeming proves possession of a code, not of the password just chosen; the account
    signs in through the same route as everyone else."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    response = _redeem(unauthenticated_client, code)

    assert main.SESSION_COOKIE_NAME not in response.cookies


def test_there_is_no_open_signup_route(workspace: Path) -> None:
    """Invite redemption is the only way an account comes into existence over HTTP. An
    instance holding an API key with open registration is a billing incident waiting to
    happen, so this enumerates the routes rather than trusting the reading."""
    account_creating = {"/api/invite/redeem"}
    suspicious = {"/api/register", "/api/signup", "/api/accounts", "/api/users"}
    paths = {getattr(route, "path", None) for route in main.app.routes}

    assert not (paths & suspicious)
    assert account_creating <= paths


def test_one_code_redeemed_concurrently_creates_exactly_one_account(
    workspace: Path, unauthenticated_client
) -> None:
    """Starlette runs a sync route in a threadpool, so two redemptions of one code genuinely
    overlap. Both can pass the lookup before either consumes the invite — and argon2 holds the
    window open for tens of milliseconds, which is an eternity for a race."""
    from concurrent.futures import ThreadPoolExecutor

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    code = main.create_invite(created_by=DEFAULT_USER_ID)

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = sorted(
            response.status_code
            for response in pool.map(
                lambda index: _redeem(unauthenticated_client, code, username=f"racer{index}"),
                range(4),
            )
        )

    assert statuses == [200, 400, 400, 400]
    usernames = [a["username"] for a in main.ACCOUNTS["accounts"]]
    assert len(usernames) == 2, usernames
    # Which racer wins is a genuine race; that exactly one does is the guarantee.
    assert usernames[0] == TEST_USERNAME
    assert usernames[1].startswith("racer")
    assert main.ACCOUNTS["invites"] == []
    stored = json.loads(main.accounts_path().read_text(encoding="utf-8"))
    assert len(stored["accounts"]) == 2


def test_concurrent_failed_logins_all_count_toward_the_lockout(
    workspace: Path, unauthenticated_client
) -> None:
    """A lost increment under concurrency weakens the lockout against exactly the parallel
    guessing it exists to bound."""
    from concurrent.futures import ThreadPoolExecutor

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(
            pool.map(
                lambda _: unauthenticated_client.post(
                    "/api/login", json={"username": TEST_USERNAME, "password": "wrong-password-x"}
                ),
                range(main.LOGIN_FAILURE_LIMIT),
            )
        )

    assert main.find_account(TEST_USERNAME)["failed_attempts"] == main.LOGIN_FAILURE_LIMIT
    assert main.find_account(TEST_USERNAME)["locked_until"] is not None

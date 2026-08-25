# ABOUTME: Fixtures shared by the whole test suite: the session's headless Chromium for the
# ABOUTME: browser-driving suites, authenticated clients, and the guards that keep the suite off
# ABOUTME: the checkout's own state.

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

import main

# Long enough to satisfy PASSWORD_MIN_LENGTH, so a test that changes the minimum fails on the
# rule rather than on every fixture in the suite at once.
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_USERNAME = "tester"


@pytest.fixture(scope="session", autouse=True)
def legacy_settings_outside_the_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Entering the app's lifespan runs the startup settings migration against
    LEGACY_SETTINGS_PATH, which on a source installation is the developer's own settings.json
    sitting in the checkout. Every in-process test is redirected at a path under the temp
    directory instead, here and once, so that a test which starts the app is safe by default
    rather than safe only if its author remembered. The subprocess suites, whose servers never
    see this module, are redirected through KEATING_LEGACY_SETTINGS_PATH in the same spirit."""
    legacy = tmp_path_factory.mktemp("keating-legacy-settings") / "settings.json"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main, "LEGACY_SETTINGS_PATH", legacy)
        yield legacy


@pytest.fixture(scope="session", autouse=True)
def workspace_outside_the_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The baseline WORKSPACE_ROOT for every in-process test, so accounts and sessions are
    never written into the developer's own workspace. The account and session stores resolve
    their paths from WORKSPACE_ROOT at call time, which means a test that points WORKSPACE_ROOT
    at its own temp directory gets an isolated instance directory with no further wiring — and
    a test that forgets still lands here rather than beside a real learner's record."""
    root = tmp_path_factory.mktemp("keating-baseline-workspace")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main, "WORKSPACE_ROOT", root)
        yield root


@pytest.fixture(autouse=True)
def empty_auth_stores() -> Iterator[None]:
    """ACCOUNTS and SESSIONS are process-wide, so one test's accounts would otherwise still be
    in memory for the next. Startup reloads both from disk, but a test that never enters the
    app's lifespan does not, which is exactly the test this protects.

    The files go with them, and so does the record of what was last seen on disk. The stores
    re-read themselves whenever a file changes underneath the process — leaving the previous
    test's accounts.json in the baseline workspace would hand them straight back."""
    main.ACCOUNTS.clear()
    main.ACCOUNTS.update(main.empty_accounts())
    main.SESSIONS.clear()
    main.SESSIONS.update(main.empty_sessions())
    main.SESSION_KEY.clear()
    main.STORE_STAMPS.clear()
    for path in (main.accounts_path(), main.sessions_path(), main.session_key_path()):
        path.unlink(missing_ok=True)
    yield


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def unauthenticated_client() -> Iterator[TestClient]:
    """A client with no session, for the routes that must refuse one.

    base_url is https:// deliberately, as it is for authenticated_client: the session cookie
    carries Secure, and httpx stores a Secure cookie sent over http but never sends it back,
    so an http base_url shows the cookie in the jar while every request answers 401."""
    with TestClient(main.app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def authenticated_client() -> Iterator[TestClient]:
    """A client carrying a real session: the account is created the way the bootstrap
    subcommand creates it, and the session comes from POSTing the real login route. There is
    no test-only way into the app, so what this exercises is what an operator gets.

    Declare `workspace` (or whatever fixture points WORKSPACE_ROOT at a temp directory) BEFORE
    this one in a test's signature. Fixtures resolve in signature order, and the account store
    is written under whatever WORKSPACE_ROOT names when this runs.

    base_url is https:// deliberately — see unauthenticated_client."""
    with TestClient(main.app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        response = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, response.text
        yield client

# ABOUTME: Tests for the cross-site request guard. SameSite=Lax is site-scoped and ports are not
# ABOUTME: part of a site, so another service on 127.0.0.1 is same-site to Keating.

from __future__ import annotations

from pathlib import Path

import pytest

import main
from main import DEFAULT_USER_ID

COURSE = "a-course"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    (root / COURSE / "learners" / DEFAULT_USER_ID).mkdir(parents=True)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


# A complete, valid settings payload, so a refusal is the guard's doing and never validation's.
VALID_SETTINGS = {
    "chat_model": "claude-opus-5",
    "grading_model": "claude-opus-5",
    "layout": {"remember_sizes": False, "sidebar_w": 250, "chat_w": 460},
}
SAFE_WRITE = ("PUT", "/api/settings", {"json": VALID_SETTINGS})


def test_a_state_changing_request_with_a_foreign_origin_is_refused(
    workspace: Path, authenticated_client
) -> None:
    method, path, kwargs = SAFE_WRITE
    response = authenticated_client.request(
        method, path, headers={"Origin": "https://evil.example"}, **kwargs
    )
    assert response.status_code == 403


def test_a_state_changing_request_from_another_port_on_the_same_site_is_refused(
    workspace: Path, authenticated_client
) -> None:
    """The hole SameSite=Lax leaves open. Cookies are not port-scoped, so any other service on
    the loopback interface — and a developer machine usually runs several — is same-site to
    Keating and can drive a cookie-bearing POST at it."""
    method, path, kwargs = SAFE_WRITE
    response = authenticated_client.request(
        method,
        path,
        headers={"Origin": "https://testserver:9999", "Sec-Fetch-Site": "same-site"},
        **kwargs,
    )
    assert response.status_code == 403


def test_sec_fetch_site_cross_site_is_refused(workspace: Path, authenticated_client) -> None:
    """The secondary signal, and the only one available on a GET navigation, which sends no
    Origin."""
    method, path, kwargs = SAFE_WRITE
    response = authenticated_client.request(
        method, path, headers={"Sec-Fetch-Site": "cross-site"}, **kwargs
    )
    assert response.status_code == 403


def test_sec_fetch_site_same_site_is_refused(workspace: Path, authenticated_client) -> None:
    response = authenticated_client.request(
        *SAFE_WRITE[:2], headers={"Sec-Fetch-Site": "same-site"}, **SAFE_WRITE[2]
    )
    assert response.status_code == 403


def test_a_same_origin_request_with_the_apps_own_headers_is_accepted(
    workspace: Path, authenticated_client
) -> None:
    """What app.js actually sends: a matching Origin and Sec-Fetch-Site: same-origin."""
    method, path, kwargs = SAFE_WRITE
    response = authenticated_client.request(
        method,
        path,
        headers={"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"},
        **kwargs,
    )
    assert response.status_code == 200


def test_a_state_changing_request_with_neither_header_is_allowed(
    workspace: Path, authenticated_client
) -> None:
    """curl, httpx and the test suite send neither header, and an attacker cannot induce a
    victim's curl to attach their cookies. Refusing here would buy nothing and would cost the
    suite and the container smoke test a bypass, which is worse."""
    method, path, kwargs = SAFE_WRITE
    assert authenticated_client.request(method, path, **kwargs).status_code == 200


def test_a_navigation_from_the_address_bar_is_allowed(workspace: Path, authenticated_client) -> None:
    """Sec-Fetch-Site: none is a user-initiated navigation, not a cross-site one."""
    response = authenticated_client.get(
        f"/api/practice?course={COURSE}", headers={"Sec-Fetch-Site": "none"}
    )
    assert response.status_code == 200


def test_the_reader_route_refuses_a_cross_site_navigation(
    workspace: Path, authenticated_client
) -> None:
    """GET /api/reader has side effects — it appends to the learner's resource log and makes a
    server-side outbound fetch — and Lax deliberately does send the cookie on a top-level
    cross-site GET navigation, so it is guarded like a write."""
    response = authenticated_client.get(
        f"/api/reader?course={COURSE}&url=https://example.com/",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_a_plain_read_is_not_guarded(workspace: Path, authenticated_client) -> None:
    """GET /review and GET /weekly record nothing, so a cross-site navigation to one of them
    reveals only what the learner's own browser could already show them."""
    response = authenticated_client.get(
        f"/review/{COURSE}", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 200


def test_the_login_route_is_guarded_too(workspace: Path, unauthenticated_client) -> None:
    """Login CSRF logs a victim into the attacker's account, which then records the victim's
    work into a record the attacker can read."""
    response = unauthenticated_client.post(
        "/api/login",
        json={"username": "x", "password": "y"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_the_guard_refuses_before_the_route_body_runs(
    workspace: Path, authenticated_client
) -> None:
    """A 403 that arrives after the write has happened is not a guard."""
    before = main.settings_for(main.DEFAULT_USER_ID)
    authenticated_client.put(
        "/api/settings",
        json={**VALID_SETTINGS, "chat_model": "claude-haiku-4-5"},
        headers={"Origin": "https://evil.example"},
    )
    after = main.settings_for(main.DEFAULT_USER_ID)
    assert after == before

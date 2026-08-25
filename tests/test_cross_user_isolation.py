# ABOUTME: Charter P25 as a test suite: with two real accounts holding real state, no surface —
# ABOUTME: API, page or listing — lets either one see anything belonging to the other.

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import DEFAULT_USER_ID, bootstrap_account

from .conftest import TEST_PASSWORD, TEST_USERNAME

COURSE = "a-course"
OTHER_PASSWORD = "a-different-long-password"


def _seed_learner(course_dir: Path, user_id: str, marker: str) -> None:
    """A learner carrying every kind of state the app keeps, so a leak on any surface has
    something distinctive to leak."""
    learner = course_dir / "learners" / user_id
    (learner / "learning-records").mkdir(parents=True, exist_ok=True)
    (learner / "MISSION.md").write_text(f"# Mission\n\n{marker} mission text.\n", encoding="utf-8")
    (learner / "NOTES.md").write_text(f"{marker} notes.\n", encoding="utf-8")
    (learner / "GLOSSARY.md").write_text(
        f"# Glossary\n\n## {marker}-term\n\n{marker} definition.\n", encoding="utf-8"
    )
    (learner / "learning-records" / "record.md").write_text(f"{marker} record\n", encoding="utf-8")
    (learner / ".practice-log.jsonl").write_text(
        json.dumps(
            {
                "ts": datetime.now(UTC).isoformat(),
                "item_id": f"{marker}-item",
                "concept": f"{marker} concept",
                "lesson": "0001",
                "type": "recall",
                "response": f"{marker} response",
                "verdict": "correct",
                "confidence": 3,
                "gave_up": False,
                "source": "lesson",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (learner / ".chat-history.json").write_text(
        json.dumps({"messages": [{"role": "user", "content": f"{marker} said something"}]}),
        encoding="utf-8",
    )


@pytest.fixture
def two_learners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    (root / COURSE).mkdir(parents=True)
    (root / COURSE / "README.md").write_text("# A course\n", encoding="utf-8")
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def clients(two_learners: Path):
    """Two signed-in accounts. A is the bootstrap account and owns learners/default/; B is an
    invitee with a minted id. Both carry a full record before either one makes a request."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    b_account = main.create_account("other-learner", OTHER_PASSWORD)
    _seed_learner(two_learners / COURSE, DEFAULT_USER_ID, "alpha")
    _seed_learner(two_learners / COURSE, b_account["user_id"], "beta")

    with (
        TestClient(main.app, base_url="https://testserver") as a,
        TestClient(main.app, base_url="https://testserver") as b,
    ):
        assert a.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        ).status_code == 200
        assert b.post(
            "/api/login", json={"username": "other-learner", "password": OTHER_PASSWORD}
        ).status_code == 200
        yield a, b, b_account["user_id"]


def test_b_cannot_read_a_practice_state(clients) -> None:
    _, b, _ = clients
    body = b.get(f"/api/practice?course={COURSE}").text
    assert "alpha" not in body
    assert "beta" in body


def test_b_cannot_read_a_mission_through_api_file(clients) -> None:
    """404, the same answer as a file that is not there — not 403, which confirms it is."""
    _, b, _ = clients
    response = b.get(f"/api/file?course={COURSE}&path=learners/{DEFAULT_USER_ID}/MISSION.md")
    assert response.status_code == 404


def test_b_can_read_their_own_mission_through_api_file(clients) -> None:
    _, b, b_id = clients
    response = b.get(f"/api/file?course={COURSE}&path=learners/{b_id}/MISSION.md")
    assert response.status_code == 200
    assert "beta" in response.text


def test_b_cannot_read_a_files_through_the_workspace_route(clients) -> None:
    _, b, _ = clients
    response = b.get(f"/workspace/{COURSE}/learners/{DEFAULT_USER_ID}/NOTES.md")
    assert response.status_code == 404


def test_b_workspace_tree_does_not_mention_a(clients) -> None:
    _, b, b_id = clients
    body = b.get(f"/api/workspace?course={COURSE}").text
    assert DEFAULT_USER_ID not in body
    assert b_id in body


def test_b_chat_history_is_empty_of_a_turns(clients) -> None:
    _, b, _ = clients
    body = b.get(f"/api/chat-history?course={COURSE}").text
    assert "alpha" not in body


def test_b_review_and_weekly_pages_show_only_b(clients) -> None:
    _, b, _ = clients
    for path in (f"/review/{COURSE}", f"/weekly/{COURSE}"):
        body = b.get(path).text
        assert "alpha" not in body, path


def test_no_get_response_anywhere_mentions_another_learners_id(clients) -> None:
    """A sweep rather than a list: every GET surface, checked for the other account's id and
    for the marker its files carry."""
    _, b, _ = clients
    surfaces = [
        f"/api/practice?course={COURSE}",
        f"/api/lessons?course={COURSE}",
        f"/api/course-overview?course={COURSE}",
        f"/api/workspace?course={COURSE}",
        f"/api/chat-history?course={COURSE}",
        f"/api/compose-targets?course={COURSE}",
        f"/review/{COURSE}",
        f"/weekly/{COURSE}",
        "/api/courses",
        "/api/settings",
        "/api/session",
    ]
    for path in surfaces:
        response = b.get(path)
        assert response.status_code == 200, path
        assert DEFAULT_USER_ID not in response.text, path
        assert "alpha" not in response.text, path


def test_the_app_exposes_no_route_that_enumerates_learners_or_accounts(clients) -> None:
    """An instructor dashboard is a surveillance decision, not a feature (charter P25). The
    absence of any listing surface is the product decision, so it is asserted rather than
    assumed."""
    _, b, _ = clients
    paths = {getattr(route, "path", "") for route in main.app.routes}
    for suspicious in ("/api/learners", "/api/accounts", "/api/users", "/api/admin"):
        assert not any(path.startswith(suspicious) for path in paths), suspicious

    body = b.get("/api/session").json()
    assert set(body) <= {"authenticated", "bootstrapped", "username"}


def test_the_session_route_reveals_nothing_about_other_accounts(clients) -> None:
    _, b, _ = clients
    body = b.get("/api/session").json()
    assert body["username"] == "other-learner"
    assert TEST_USERNAME not in json.dumps(body)


def test_a_leaks_nothing_about_b_either(clients) -> None:
    """The isolation is symmetric: the bootstrap account is an ordinary learner, not an
    operator with visibility. An admin manages accounts, never records."""
    a, _, b_id = clients
    for path in (f"/api/workspace?course={COURSE}", f"/api/practice?course={COURSE}"):
        response = a.get(path)
        assert b_id not in response.text, path
        assert "beta" not in response.text, path


def test_the_admin_flag_grants_no_extra_visibility(clients) -> None:
    """is_admin exists for account management. A boolean that widens a learner-state read is
    the single edit that converts this app into a monitor, so its absence is a test."""
    a, _, b_id = clients
    assert main.find_account(TEST_USERNAME)["is_admin"] is True

    response = a.get(f"/api/file?course={COURSE}&path=learners/{b_id}/MISSION.md")

    assert response.status_code == 404

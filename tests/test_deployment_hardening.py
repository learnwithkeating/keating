# ABOUTME: Tests for the three things that are wrong once the app is reachable on a server:
# ABOUTME: a scheme-only Origin mismatch, an uncapped upload, and errors that name host paths.

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import ROLE_LEARNER

COURSE = "why-you-forget"
EXAMPLE_COURSE = Path(__file__).resolve().parent.parent / "examples" / COURSE
AUTHOR_USERNAME = "the-author"
LEARNER_USERNAME = "the-learner"
PASSWORD = "a-long-enough-passphrase-1"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE_COURSE, root / COURSE)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def author(workspace: Path):
    """The bootstrap account, which adoption makes an author of every course already there."""
    main.bootstrap_account(AUTHOR_USERNAME, PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/login", json={"username": AUTHOR_USERNAME, "password": PASSWORD}
            ).status_code
            == 200
        )
        yield client


@pytest.fixture
def learner(author):
    account = main.create_account(LEARNER_USERNAME, PASSWORD)
    main.enroll(account["user_id"], COURSE, ROLE_LEARNER)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/login", json={"username": LEARNER_USERNAME, "password": PASSWORD}
            ).status_code
            == 200
        )
        yield client


# --- A TLS-terminating proxy in front of the app ------------------------------


def test_a_scheme_only_origin_mismatch_names_the_proxy(learner: TestClient) -> None:
    """The failure this catches is the one a first deployment hits: a proxy terminates TLS and
    forwards plain HTTP, uvicorn is not told to trust it, so the app and the browser disagree
    about the scheme alone. Every state-changing request is then refused as cross-site, and a
    bare "cross-site request refused" sends the operator hunting through their own application
    for a bug that is in their proxy configuration."""
    response = learner.post(
        "/api/chat",
        json={"course": COURSE, "message": "hello"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "FORWARDED_ALLOW_IPS" in detail
    assert "scheme" in detail.lower()


def test_a_genuinely_cross_site_origin_is_still_just_refused(learner: TestClient) -> None:
    """The hint must not become one for an attacker: a request from another host is refused
    with nothing in the body to learn from, exactly as before."""
    response = learner.post(
        "/api/chat",
        json={"course": COURSE, "message": "hello"},
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "FORWARDED_ALLOW_IPS" not in detail
    assert "evil.example.com" not in detail


def test_a_same_origin_request_is_untouched(learner: TestClient) -> None:
    response = learner.get("/api/courses", headers={"Origin": "https://testserver"})

    assert response.status_code == 200


# --- Uploads are bounded ------------------------------------------------------


def test_an_upload_over_the_cap_is_refused(author: TestClient) -> None:
    """An unbounded read is a memory problem and a disk problem at once, and an author on a
    reachable instance is not the trust level the one person on a loopback one was."""
    oversize = b"%PDF-1.4\n" + b"\0" * (main.MAX_UPLOAD_BYTES + 1)

    response = author.post(
        "/api/upload",
        data={"course": COURSE},
        files={"file": ("big.pdf", io.BytesIO(oversize), "application/pdf")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_an_upload_within_the_cap_still_lands(author: TestClient, workspace: Path) -> None:
    small = b"%PDF-1.4\n" + b"\0" * 1024

    response = author.post(
        "/api/upload",
        data={"course": COURSE},
        files={"file": ("small.pdf", io.BytesIO(small), "application/pdf")},
    )

    assert response.status_code == 200
    assert (workspace / COURSE / "materials" / "small.pdf").read_bytes() == small


def test_an_oversize_upload_leaves_nothing_behind(author: TestClient, workspace: Path) -> None:
    """Refusing after writing part of the file would make the cap a disk-fill with extra steps."""
    oversize = b"%PDF-1.4\n" + b"\0" * (main.MAX_UPLOAD_BYTES + 1)

    author.post(
        "/api/upload",
        data={"course": COURSE},
        files={"file": ("big.pdf", io.BytesIO(oversize), "application/pdf")},
    )

    assert not (workspace / COURSE / "materials" / "big.pdf").exists()


# --- Errors do not hand out host paths ----------------------------------------


@pytest.mark.parametrize("path", ["/private/var/somewhere/.keating", "/srv/keating/.keating"])
def test_an_instance_state_failure_keeps_the_path_out_of_the_body(path: str) -> None:
    """An unauthenticated caller reaches this handler through a failed login, because recording
    the attempt is itself a write. What comes back must not be the instance's own layout."""
    detail = main.instance_state_detail(
        main.InstanceStateUnavailable(f"cannot write {path}/accounts.json: Permission denied")
    )

    assert path not in detail
    assert "accounts.json" not in detail
    assert "log" in detail.lower()

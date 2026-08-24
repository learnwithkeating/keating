# ABOUTME: Every HTML surface carries the Content-Security-Policy its trust level calls for,
# ABOUTME: and any route that forgets one gets the locked-down default instead.

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import (
    CSP_APP_SHELL,
    CSP_COURSE_AUTHORED,
    CSP_LOCKED_DOWN,
    CSP_READER,
    CSP_READER_PDF,
    app,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_COURSE = REPO_ROOT / "examples" / "why-you-forget"
COURSE = "why-you-forget"
LESSON = "lessons/0001-the-forgetting-curve.html"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway copy of the example course that WORKSPACE_ROOT points at for one test.
    Nothing here ever reads or writes a real workspace."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE_COURSE, root / COURSE)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def client(workspace: Path) -> TestClient:
    return TestClient(app)


def directives(policy: str) -> dict[str, str]:
    """Split a policy into {name: value} so a test can assert on one directive without
    depending on the order the others are written in."""
    parsed: dict[str, str] = {}
    for clause in policy.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        name, _, value = clause.partition(" ")
        parsed[name.lower()] = value.strip()
    return parsed


# --- The three trust levels ---------------------------------------------------


def test_app_shell_policy(client: TestClient) -> None:
    """The shell is the top-level document: it must never be embedded, and it is the one
    surface where a script injected through /api/course-overview's markdown would run in
    the app's own origin."""
    response = client.get("/")
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert policy == CSP_APP_SHELL
    parsed = directives(policy)
    assert parsed["default-src"] == "'none'"
    assert parsed["script-src"] == "'self'"
    assert parsed["frame-ancestors"] == "'none'"
    assert parsed["object-src"] == "'none'"
    assert parsed["base-uri"] == "'none'"
    assert parsed["form-action"] == "'none'"
    # The a11y suite would not notice a mistyped font host — the pages would settle and
    # render in fallback faces, and axe reads computed contrast, which does not change.
    # This assertion is the compensating control.
    assert "https://fonts.gstatic.com" in parsed["font-src"]
    assert "https://fonts.googleapis.com" in parsed["style-src"]
    for escape_hatch in ("'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'"):
        assert escape_hatch not in policy, f"{escape_hatch} has no business in the shell policy"


@pytest.mark.parametrize(
    "path",
    [
        f"/workspace/{COURSE}/{LESSON}",
        f"/api/file?course={COURSE}&path={LESSON}",
        f"/review/{COURSE}",
        f"/weekly/{COURSE}",
    ],
)
def test_course_authored_policy(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert policy == CSP_COURSE_AUTHORED
    parsed = directives(policy)
    # All four render inside the shell's preview iframe. 'none' here blanks the reading
    # pane, which is the single most likely way to get this policy wrong.
    assert parsed["frame-ancestors"] == "'self'"
    # quiz.js POSTs grading from inside the lesson iframe and the weekly control POSTs
    # /api/weekly-session. Drop this and grading dies silently.
    assert parsed["connect-src"] == "'self'"
    assert parsed["script-src"] == "'self'"
    assert "'unsafe-inline'" not in parsed["script-src"]
    assert "'unsafe-eval'" not in policy
    assert parsed["img-src"] == "'self'"
    assert parsed["object-src"] == "'none'"


def test_reader_policy_forbids_script_entirely(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The surface holding untrusted third-party markup is the one surface that needs no
    script at all, which is the asymmetry the whole fix turns on.

    Only the outbound network hop is substituted: the SSRF guard correctly refuses a
    loopback fixture server, so there is no way to serve the article from this process.
    Everything downstream — trafilatura, the sanitizer, _reader_page, the header — is the
    real code path."""
    article = b"<html><body><article><h1>T</h1><p>Body text, long enough to extract, "
    article += b"with several sentences so the extractor keeps it. " * 6
    article += b"</p></article></body></html>"
    monkeypatch.setattr(
        main,
        "_fetch_external",
        lambda url: ("https://example.org/a", article, "text/html", "utf-8"),
    )

    response = client.get(f"/api/reader?course={COURSE}&url=https://example.org/a")
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    parsed = directives(policy)
    assert parsed["script-src"] == "'none'"
    assert parsed["img-src"] == "'none'"
    assert parsed["default-src"] == "'none'"
    assert parsed["frame-ancestors"] == "'self'"
    assert parsed["style-src"].startswith("'nonce-")
    # The document must land in an opaque origin, so that even a hypothetical escape
    # could not reach /api/* as the app's own origin, and could not run anyway.
    sandbox = parsed["sandbox"].split()
    assert "allow-same-origin" not in sandbox
    assert "allow-scripts" not in sandbox
    assert "allow-popups" in sandbox
    assert "allow-popups-to-escape-sandbox" in sandbox


def test_reader_nonce_is_per_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the classic nonce bug where the header and the markup are generated from
    two different values, which leaves the reader silently unstyled."""
    article = b"<html><body><article><p>Body text, long enough to extract. " * 8
    article += b"</p></article></body></html>"
    monkeypatch.setattr(
        main,
        "_fetch_external",
        lambda url: ("https://example.org/a", article, "text/html", "utf-8"),
    )

    nonces = []
    for _ in range(2):
        response = client.get(f"/api/reader?course={COURSE}&url=https://example.org/a")
        assert response.status_code == 200
        policy = response.headers["content-security-policy"]
        match = re.search(r"'nonce-([^']+)'", policy)
        assert match, policy
        nonce = match.group(1)
        assert policy == CSP_READER.format(nonce=nonce)
        assert f'<style nonce="{nonce}">' in response.text
        nonces.append(nonce)

    assert nonces[0] != nonces[1], "the reader nonce is reused across responses"


def test_reader_pdf_branch_has_no_sandbox(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chrome renders PDFs through an internal viewer document; a sandbox directive
    without allow-scripts is a plausible way to break it, so the pass-through branch is
    locked down without one."""
    monkeypatch.setattr(
        main,
        "_fetch_external",
        lambda url: ("https://example.org/a.pdf", b"%PDF-1.4\n", "application/pdf", None),
    )
    response = client.get(f"/api/reader?course={COURSE}&url=https://example.org/a.pdf")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CSP_READER_PDF
    parsed = directives(CSP_READER_PDF)
    assert "sandbox" not in parsed
    assert parsed["frame-ancestors"] == "'self'"


# --- Deny by default ----------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/courses", "/api/no-such-route"])
def test_unlisted_route_gets_the_locked_down_default(client: TestClient, path: str) -> None:
    """The failure mode this shape is designed against is a future HTML route whose author
    forgets the header. A permissive default would land a lax policy on exactly the
    surface that must not have one; this one leaves it inert and visibly broken instead."""
    response = client.get(path)
    assert response.headers["content-security-policy"] == CSP_LOCKED_DOWN


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/courses",
        f"/review/{COURSE}",
        f"/workspace/{COURSE}/{LESSON}",
        "/static/app.js",
    ],
)
def test_security_headers_on_every_response(client: TestClient, path: str) -> None:
    response = client.get(path)
    # /api/file and /workspace map Content-Type from the file suffix, so a course file
    # with a misleading suffix must not be sniffable into HTML.
    assert response.headers["x-content-type-options"] == "nosniff"
    # The reader's outbound links would otherwise carry a Referer holding the course slug
    # and the article being read.
    assert response.headers["referrer-policy"] == "no-referrer"


# --- The surfaces the shell frames --------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"/workspace/{COURSE}/lessons/does-not-exist.html",
        f"/api/file?course={COURSE}&path=lessons/does-not-exist.html",
        "/review/no-such-course",
        "/weekly/no-such-course",
        f"/api/reader?course={COURSE}&url=https://no-such-host.invalid/a",
    ],
)
def test_an_error_on_a_framed_route_still_reaches_the_reading_pane(
    client: TestClient, path: str
) -> None:
    """An HTTPException never runs the route body that names a framed policy, so its
    response carries the middleware default. If that default forbade framing, the learner
    would get an empty reading pane instead of the reason the resource would not open."""
    response = client.get(path)
    assert response.status_code >= 400
    assert directives(response.headers["content-security-policy"])["frame-ancestors"] == "'self'"


def test_the_shell_is_served_from_one_url(client: TestClient) -> None:
    """index.html sits inside the directory the /static mount serves, so the shell is
    reachable at a second URL that carries the static default rather than the shell's own
    policy. That URL points at the canonical one instead of serving a dead copy."""
    response = client.get("/static/index.html", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/"


@pytest.mark.parametrize("policy", [CSP_APP_SHELL, CSP_COURSE_AUTHORED])
def test_a_font_inside_the_course_package_is_allowed(policy: str) -> None:
    """font-src is present in both policies, so default-src is never consulted for a font
    and 'self' has to be named. Without it a course that ships its own webfont in
    ./assets/ is blocked, which contradicts img-src 'self' and media-src 'self' beside
    it."""
    assert directives(policy)["font-src"] == "'self' https://fonts.gstatic.com"


def test_security_headers_survive_an_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starlette's own 500 response is produced outside the middleware stack, so it takes
    an explicit handler for the headers to reach it. Provoked through a real route rather
    than a route registered for the test, so the path under assertion is the shipped one."""

    class Exploding:
        def is_dir(self) -> bool:
            raise RuntimeError("workspace unreadable")

    monkeypatch.setattr(main, "WORKSPACE_ROOT", Exploding())
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/courses")
    assert response.status_code == 500
    assert response.headers["content-security-policy"] == CSP_LOCKED_DOWN
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"

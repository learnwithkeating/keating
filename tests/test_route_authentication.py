# ABOUTME: The net: every route is either on the public allowlist or declares an auth dependency,
# ABOUTME: and no route anywhere resolves whose record it is from a query parameter or a body.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import APIRoute

import main
from main import DEFAULT_USER_ID, bootstrap_account

from .conftest import TEST_PASSWORD, TEST_USERNAME

COURSE = "a-course"

# Every route that reads or writes one learner's state. Each must resolve the user server-side
# and must refuse a request with no session.
LEARNER_STATE_ROUTES = [
    ("POST", "/api/chat", {"json": {"course": COURSE, "message": "hi"}}),
    ("GET", f"/api/practice?course={COURSE}", {}),
    ("POST", "/api/attempt", {"json": {"course": COURSE, "item_id": "x", "response": "y"}}),
    ("GET", f"/review/{COURSE}", {}),
    ("GET", f"/weekly/{COURSE}", {}),
    ("POST", "/api/weekly-session", {"json": {"course": COURSE}}),
    ("GET", f"/api/compose-targets?course={COURSE}", {}),
    ("POST", "/api/compose/recall", {"json": {"course": COURSE, "concept": "x", "response": "y"}}),
    ("POST", "/api/compose/define", {"json": {"course": COURSE, "term": "x", "definition": "y"}}),
    ("POST", "/api/glossary", {"json": {"course": COURSE, "term": "x", "definition": "y"}}),
    ("POST", "/api/courses", {"json": {"slug": "new-course"}}),
    ("GET", f"/api/lessons?course={COURSE}", {}),
    ("GET", f"/api/course-overview?course={COURSE}", {}),
    ("GET", f"/api/workspace?course={COURSE}", {}),
    ("GET", f"/api/file?course={COURSE}&path=README.md", {}),
    ("GET", f"/workspace/{COURSE}/README.md", {}),
    ("GET", f"/api/reader?course={COURSE}&url=https://example.com/", {}),
    ("GET", f"/api/chat-history?course={COURSE}", {}),
]

# Routes that need a session but no user id: they change instance settings, write into a course,
# or rename a whole course directory. Forget the dependency on one of these and it stays open.
AUTHENTICATED_ROUTES = [
    ("GET", "/api/settings", {}),
    (
        "PUT",
        "/api/settings",
        {
            "json": {
                "chat_model": main.MODEL_CATALOG[0]["id"],
                "grading_model": main.MODEL_CATALOG[0]["id"],
                "layout": {"remember_sizes": False, "sidebar_w": 250, "chat_w": 460},
            }
        },
    ),
    ("GET", "/api/courses", {}),
    ("PATCH", f"/api/courses/{COURSE}", {"json": {"new_slug": "renamed"}}),
    ("POST", f"/api/courses/{COURSE}/archive", {}),
    ("POST", "/api/upload", {"files": {"file": ("a.pdf", b"%PDF-1.4\n", "application/pdf")}, "data": {"course": COURSE}}),
]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    (root / COURSE / "learners" / DEFAULT_USER_ID).mkdir(parents=True)
    (root / COURSE / "README.md").write_text("# A course\n", encoding="utf-8")
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _declared_dependencies(route: APIRoute) -> set:
    """Every dependency callable a route resolves, at any depth."""
    found = set()
    pending = [route.dependant]
    while pending:
        dependant = pending.pop()
        if dependant.call is not None:
            found.add(dependant.call)
        pending.extend(dependant.dependencies)
    return found


def _api_routes() -> list[APIRoute]:
    return [route for route in main.app.routes if isinstance(route, APIRoute)]


# --- The net ------------------------------------------------------------------


def test_every_route_is_either_public_or_authenticated() -> None:
    """The test that fails when someone adds a route and forgets to authenticate it.

    Making it green by adding the new path to PUBLIC_PATHS is not a fix — it is the change
    this test exists to make visible. The allowlist is three entries and should stay three."""
    unguarded = []
    for route in _api_routes():
        if route.path in main.PUBLIC_PATHS or route.path.startswith(main.PUBLIC_PREFIXES):
            continue
        if {main.require_session, main.current_user_id} & _declared_dependencies(route):
            continue
        unguarded.append(f"{sorted(route.methods)} {route.path}")

    assert unguarded == []


def test_the_public_allowlist_is_only_the_shell_and_its_assets() -> None:
    expected = {"/", "/static/index.html", "/api/session", "/api/login", "/api/invite/redeem"}
    assert sorted(main.PUBLIC_PATHS) == sorted(expected)
    assert main.PUBLIC_PREFIXES == ("/static/",)


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    LEARNER_STATE_ROUTES,
    ids=[f"{m}-{p.split('?')[0]}" for m, p, _ in LEARNER_STATE_ROUTES],
)
def test_every_learner_state_route_refuses_an_unauthenticated_request(
    workspace: Path, unauthenticated_client, method: str, path: str, kwargs: dict
) -> None:
    assert unauthenticated_client.request(method, path, **kwargs).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    AUTHENTICATED_ROUTES,
    ids=[f"{m}-{p}" for m, p, _ in AUTHENTICATED_ROUTES],
)
def test_every_authenticated_route_refuses_an_unauthenticated_request(
    workspace: Path, unauthenticated_client, method: str, path: str, kwargs: dict
) -> None:
    assert unauthenticated_client.request(method, path, **kwargs).status_code == 401


def test_logout_refuses_an_unauthenticated_request(workspace: Path, unauthenticated_client) -> None:
    assert unauthenticated_client.post("/api/logout").status_code == 401


# --- What stays open ----------------------------------------------------------


def test_the_shell_and_static_assets_need_no_session(
    workspace: Path, unauthenticated_client
) -> None:
    """The login view needs a document, its stylesheet and its script. Gating / would also
    make the container's HEALTHCHECK report unhealthy on a working instance."""
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert unauthenticated_client.get(path).status_code == 200, path


def test_the_session_route_needs_no_session(workspace: Path, unauthenticated_client) -> None:
    assert unauthenticated_client.get("/api/session").status_code == 200


# --- The shape of a refusal ---------------------------------------------------


def test_a_401_on_a_framed_route_carries_frame_ancestors_self_and_readable_html(
    workspace: Path, unauthenticated_client
) -> None:
    """A framed route answering 401 must render something a person can read in the reading
    pane. frame-ancestors 'none' would blank the pane, which is the failure mode where an app
    that is merely logged out looks broken."""
    response = unauthenticated_client.get(
        f"/review/{COURSE}", headers={"Accept": "text/html", "Sec-Fetch-Dest": "iframe"}
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("text/html")
    assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
    assert "sign in" in response.text.lower()
    # No link: this document is sandboxed, so following one would load the shell somewhere its
    # script cannot run and leave the blank pane the document exists to avoid.
    assert "<a " not in response.text


def test_a_401_on_a_bookmarked_route_offers_a_way_back_to_the_app(
    workspace: Path, unauthenticated_client
) -> None:
    """/review/{course} and /weekly/{course} are bookmarkable, so a person arrives at one
    directly with an expired session. "Reload to sign in" is no help there — reloading serves
    the same refusal — and without a link the only way back is hand-editing the URL."""
    for path in (f"/review/{COURSE}", f"/weekly/{COURSE}"):
        response = unauthenticated_client.get(
            path, headers={"Accept": "text/html", "Sec-Fetch-Dest": "document"}
        )

        assert response.status_code == 401, path
        assert '<a href="/"' in response.text, path


def test_a_401_on_an_api_route_is_json(workspace: Path, unauthenticated_client) -> None:
    response = unauthenticated_client.get(f"/api/practice?course={COURSE}")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"]


def test_a_401_is_never_a_redirect(workspace: Path, unauthenticated_client) -> None:
    """A redirect to a login page would nest a credential form inside the shell's iframe."""
    for method, path, kwargs in LEARNER_STATE_ROUTES + AUTHENTICATED_ROUTES:
        response = unauthenticated_client.request(method, path, follow_redirects=False, **kwargs)
        assert response.status_code == 401, f"{method} {path}"


# --- No identity from the request ---------------------------------------------


def test_no_route_resolves_a_user_id_from_a_query_parameter_or_body(
    workspace: Path, authenticated_client
) -> None:
    """Whose record a request is about comes from the session and nowhere else (charter P25).
    Every learner-state route is asked, as the bootstrap account, to act as someone else."""
    other = "someone-else"
    marker = "a sentence only the other learner's file contains"
    other_dir = workspace / COURSE / "learners" / other
    other_dir.mkdir(parents=True)
    (other_dir / "MISSION.md").write_text(f"# {marker}\n", encoding="utf-8")

    for method, path, kwargs in LEARNER_STATE_ROUTES:
        separator = "&" if "?" in path else "?"
        spoofed = f"{path}{separator}user={other}&user_id={other}"
        body = dict(kwargs)
        if "json" in body:
            body["json"] = {**body["json"], "user_id": other, "user": other}
        response = authenticated_client.request(method, spoofed, **body)
        assert response.status_code != 500, f"{method} {path}"
        assert marker not in response.text, f"{method} {path} answered with {other}'s file"
        # A 422 body quotes the request back as part of the validation report, so the id being
        # echoed there says nothing about identity — the route never ran.
        if response.status_code != 422:
            assert other not in response.text, f"{method} {path} resolved {other}"


def test_the_current_user_dependency_takes_no_request_supplied_argument() -> None:
    """current_user_id resolves from the session dependency alone. A parameter that FastAPI
    could fill from the query string or the body would be a user id the caller chooses."""
    import inspect

    signature = inspect.signature(main.current_user_id)
    assert [p.name for p in signature.parameters.values()] == ["session"]
    assert isinstance(
        signature.parameters["session"].default, type(main.Depends(main.require_session))
    )


def test_bootstrap_account_owns_the_default_user_id(workspace: Path) -> None:
    assert bootstrap_account(TEST_USERNAME, TEST_PASSWORD)["user_id"] == DEFAULT_USER_ID


# --- Every route is classified ------------------------------------------------

# The path templates the two lists above exercise, plus the ones that carry no course and no
# learner state. Every registered route has to appear in exactly one of these, so a course
# route added later cannot be added without someone deciding which it is.
COURSE_ROUTE_TEMPLATES = {  # every route that opens an EXISTING course
    "/api/chat",
    "/api/practice",
    "/api/attempt",
    "/review/{course}",
    "/weekly/{course}",
    "/api/weekly-session",
    "/api/compose-targets",
    "/api/compose/recall",
    "/api/compose/define",
    "/api/glossary",
    "/api/lessons",
    "/api/course-overview",
    "/api/workspace",
    "/api/file",
    "/workspace/{course}/{file_path:path}",
    "/api/reader",
    "/api/chat-history",
    "/api/courses/{slug}",
    "/api/courses/{slug}/archive",
    "/api/upload",
}

# Routes that open no existing course, and so resolve no role in one. /api/courses is here
# for both its methods and for two different reasons: GET filters the listing by the caller's
# enrollments rather than opening any course, and POST creates a course no enrollment can yet
# exist for and mints its creator's own.
NO_EXISTING_COURSE_ROUTE_TEMPLATES = {
    "/api/settings",
    "/api/courses",
    "/api/logout",
}


def test_every_registered_route_is_classified() -> None:
    """The test that fails when someone adds a course route and forgets to resolve a role for
    it. Adding the path to NO_EXISTING_COURSE_ROUTE_TEMPLATES is not a fix unless it genuinely
    opens no course."""
    unclassified = []
    for route in _api_routes():
        if route.path in main.PUBLIC_PATHS or route.path.startswith(main.PUBLIC_PREFIXES):
            continue
        if (
            route.path in COURSE_ROUTE_TEMPLATES
            or route.path in NO_EXISTING_COURSE_ROUTE_TEMPLATES
        ):
            continue
        unclassified.append(f"{sorted(route.methods)} {route.path}")

    assert unclassified == []


def test_every_course_taking_route_resolves_its_role_through_the_one_door() -> None:
    """open_course is the only way to a course directory from a route: it does the path safety
    and the role in one call and hands back both, so a route cannot hold the directory without
    having resolved the role."""
    import inspect

    source = inspect.getsource(main)
    handlers = {
        route.endpoint.__name__
        for route in _api_routes()
        if route.path in COURSE_ROUTE_TEMPLATES
    }
    # Without this the test passes by matching nothing the moment a path template drifts.
    assert len(handlers) == len(COURSE_ROUTE_TEMPLATES), sorted(handlers)
    missing = []
    for name in sorted(handlers):
        body = source.split(f"def {name}(", 1)[1].split("\n@app.", 1)[0]
        if "open_course(" not in body:
            missing.append(name)

    assert missing == []

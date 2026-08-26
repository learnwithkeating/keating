# ABOUTME: Every route that touches a course resolves the caller's role for that course server-side:
# ABOUTME: no record is 404, a learner is refused the package, and an author is not an instructor.

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import DEFAULT_USER_ID, ROLE_AUTHOR, ROLE_LEARNER

from .conftest import TEST_PASSWORD, TEST_USERNAME

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_COURSE = REPO_ROOT / "examples" / "why-you-forget"
COURSE = "why-you-forget"
LEARNER_USERNAME = "a-learner"
LEARNER_PASSWORD = "another-long-enough-password"

# Every course-taking route, as a caller reaches it. Each one resolves a role for COURSE, so
# each one must answer 404 to an account with no record in it.
COURSE_ROUTES = [
    ("POST", "/api/chat", {"json": {"course": COURSE, "message": "hi"}}),
    ("GET", f"/api/practice?course={COURSE}", {}),
    (
        "POST",
        "/api/attempt",
        {
            "json": {
                "course": COURSE,
                "item_id": "x",
                "concept": "x",
                "lesson": "0001",
                "type": "recall",
                "question": "q",
                "response": "y",
                "confidence": 3,
                "answer": "a",
                "rubric": "r",
            }
        },
    ),
    ("GET", f"/review/{COURSE}", {}),
    ("GET", f"/weekly/{COURSE}", {}),
    ("POST", "/api/weekly-session", {"json": {"course": COURSE}}),
    ("GET", f"/api/compose-targets?course={COURSE}", {}),
    (
        "POST",
        "/api/compose/recall",
        {
            "json": {
                "course": COURSE,
                "target_type": "concept",
                "target_ref": "x",
                "response": "y",
                "confidence": 3,
            }
        },
    ),
    (
        "POST",
        "/api/compose/define",
        {"json": {"course": COURSE, "term": "x", "draft": "y", "confidence": 3}},
    ),
    ("POST", "/api/glossary", {"json": {"course": COURSE, "term": "x", "definition": "y"}}),
    ("GET", f"/api/lessons?course={COURSE}", {}),
    ("GET", f"/api/course-overview?course={COURSE}", {}),
    ("GET", f"/api/workspace?course={COURSE}", {}),
    ("GET", f"/api/file?course={COURSE}&path=course.json", {}),
    ("GET", f"/workspace/{COURSE}/course.json", {}),
    ("GET", f"/api/reader?course={COURSE}&url=https://example.com/", {}),
    ("GET", f"/api/chat-history?course={COURSE}", {}),
    ("PATCH", f"/api/courses/{COURSE}", {"json": {"new_slug": "renamed"}}),
    ("POST", f"/api/courses/{COURSE}/archive", {}),
    (
        "POST",
        "/api/upload",
        {
            "files": {"file": ("a.pdf", b"%PDF-1.4\n", "application/pdf")},
            "data": {"course": COURSE},
        },
    ),
]

# The three that are authoring, not learning: they change the shared package or the directory
# holding it.
AUTHOR_ROUTES = [
    ("PATCH", f"/api/courses/{COURSE}", {"json": {"new_slug": "renamed"}}),
    ("POST", f"/api/courses/{COURSE}/archive", {}),
    (
        "POST",
        "/api/upload",
        {
            "files": {"file": ("a.pdf", b"%PDF-1.4\n", "application/pdf")},
            "data": {"course": COURSE},
        },
    ),
]


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
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
            ).status_code
            == 200
        )
        yield client


@pytest.fixture
def learner(author):
    """A second account enrolled in the same course as a learner. `author` first, so the
    instance is bootstrapped before this account is invited into it."""
    account = main.create_account(LEARNER_USERNAME, LEARNER_PASSWORD)
    main.enroll(account["user_id"], COURSE, ROLE_LEARNER)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/login", json={"username": LEARNER_USERNAME, "password": LEARNER_PASSWORD}
            ).status_code
            == 200
        )
        yield client


@pytest.fixture
def stranger(author):
    """An account with no record in any course."""
    main.create_account("a-stranger", LEARNER_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert (
            client.post(
                "/api/login", json={"username": "a-stranger", "password": LEARNER_PASSWORD}
            ).status_code
            == 200
        )
        yield client


# --- No record means no access ------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    COURSE_ROUTES,
    ids=[f"{m}-{p.split('?')[0]}" for m, p, _ in COURSE_ROUTES],
)
def test_an_unenrolled_account_gets_404_from_every_course_route(
    stranger, method: str, path: str, kwargs: dict
) -> None:
    """404 rather than 403, byte-identical to a course that is not there: the sidebar lists
    only enrolled courses, so a 403 here would be a workspace-wide slug-enumeration oracle."""
    response = stranger.request(method, path, **kwargs)

    assert response.status_code == 404, f"{method} {path} -> {response.status_code}"


def test_the_404_for_an_unenrolled_course_says_only_that_it_is_not_found(stranger) -> None:
    response = stranger.get(f"/api/practice?course={COURSE}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"course not found: {COURSE}"
    assert "role" not in response.text
    assert "enroll" not in response.text.lower()


def test_an_unenrolled_account_sees_no_courses_at_all(stranger) -> None:
    assert stranger.get("/api/courses").json() == {"courses": []}


# --- The ladder ---------------------------------------------------------------


def test_a_learner_may_read_the_package_and_write_their_own_state(learner) -> None:
    """A learner is a full learner: every read of the shared package and every write of their
    own record behaves exactly as it does for an author."""
    for path in (
        f"/api/lessons?course={COURSE}",
        f"/api/course-overview?course={COURSE}",
        f"/api/workspace?course={COURSE}",
        f"/api/practice?course={COURSE}",
        f"/api/chat-history?course={COURSE}",
        f"/api/compose-targets?course={COURSE}",
        f"/api/file?course={COURSE}&path=course.json",
        f"/review/{COURSE}",
        f"/weekly/{COURSE}",
    ):
        assert learner.get(path).status_code == 200, path

    saved = learner.post(
        "/api/glossary",
        json={"course": COURSE, "term": "spacing", "definition": "gaps between study."},
    )
    assert saved.status_code == 200, saved.text
    assert learner.post("/api/weekly-session", json={"course": COURSE}).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    AUTHOR_ROUTES,
    ids=[f"{m}-{p}" for m, p, _ in AUTHOR_ROUTES],
)
def test_a_learner_is_refused_the_authoring_routes_with_403_and_a_reason(
    learner, method: str, path: str, kwargs: dict
) -> None:
    """403, not 404: the caller can already see this course in their sidebar and open every
    lesson in it, so hiding it would be a lie. The reason names the role."""
    response = learner.request(method, path, **kwargs)

    assert response.status_code == 403, f"{method} {path} -> {response.text}"
    detail = response.json()["detail"]
    assert COURSE in detail
    assert ROLE_LEARNER in detail
    assert ROLE_AUTHOR in detail


def test_an_author_may_upload_rename_and_archive(author, workspace: Path) -> None:
    uploaded = author.post(
        "/api/upload",
        files={"file": ("syllabus.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"course": COURSE},
    )
    assert uploaded.status_code == 200, uploaded.text

    renamed = author.patch(f"/api/courses/{COURSE}", json={"new_slug": "renamed-course"})
    assert renamed.status_code == 200, renamed.text

    archived = author.post("/api/courses/renamed-course/archive")
    assert archived.status_code == 200, archived.text


# --- The listing --------------------------------------------------------------


def test_the_course_list_shows_only_enrolled_courses_with_the_callers_own_role(
    learner, workspace: Path
) -> None:
    (workspace / "another-course").mkdir()

    body = learner.get("/api/courses").json()

    assert [c["slug"] for c in body["courses"]] == [COURSE]
    assert body["courses"][0]["role"] == ROLE_LEARNER


def test_the_course_list_carries_the_authors_role_for_the_same_course(author) -> None:
    body = author.get("/api/courses").json()

    assert [c["slug"] for c in body["courses"]] == [COURSE]
    assert body["courses"][0]["role"] == ROLE_AUTHOR


def test_the_course_list_never_names_another_account(learner) -> None:
    """Which courses exist for me says nothing about who else is in them (charter P25)."""
    body = learner.get("/api/courses").text

    assert TEST_USERNAME not in body
    assert DEFAULT_USER_ID not in body


# --- Creating, renaming, archiving --------------------------------------------


def test_creating_a_course_enrolls_its_creator_as_author(learner) -> None:
    """Any account may create a course; authoring your own package is not authoring someone
    else's. Without this the creator could not add a single lesson to it."""
    created = learner.post("/api/courses", json={"slug": "learner-made"})

    assert created.status_code == 200, created.text
    assert learner.get("/api/course-overview?course=learner-made").status_code == 200
    assert (
        learner.patch("/api/courses/learner-made", json={"new_slug": "learner-renamed"}).status_code
        == 200
    )


def test_renaming_a_course_carries_its_enrollments(author, learner) -> None:
    """Enrollments are keyed by slug, so a rename that does not re-key them orphans access —
    including the renamer's own — the moment it succeeds."""
    assert author.patch(f"/api/courses/{COURSE}", json={"new_slug": "renamed"}).status_code == 200

    assert author.get("/api/course-overview?course=renamed").status_code == 200
    assert author.get(f"/api/course-overview?course={COURSE}").status_code == 404
    assert learner.get("/api/course-overview?course=renamed").status_code == 200
    assert main.course_role(DEFAULT_USER_ID, "renamed") == ROLE_AUTHOR


def test_archiving_a_course_drops_its_enrollments_and_leaves_learner_directories_alone(
    author, workspace: Path
) -> None:
    """A slug reused after archiving must not inherit the archived course's access list."""
    learner_dir = workspace / COURSE / "learners" / DEFAULT_USER_ID
    learner_dir.mkdir(parents=True, exist_ok=True)
    (learner_dir / "MISSION.md").write_text("# Mission\n", encoding="utf-8")

    assert author.post(f"/api/courses/{COURSE}/archive").status_code == 200

    assert main.course_role(DEFAULT_USER_ID, COURSE) is None
    archived = workspace / main.ARCHIVE_DIR_NAME / COURSE / "learners" / DEFAULT_USER_ID
    assert (archived / "MISSION.md").read_text(encoding="utf-8") == "# Mission\n"

    (workspace / COURSE).mkdir()
    assert author.get(f"/api/course-overview?course={COURSE}").status_code == 404


# --- An author is not an instructor -------------------------------------------


def test_an_author_cannot_read_another_learners_record(author, learner, workspace: Path) -> None:
    """The role widens what may be written, never what may be read. An author reading
    learners/ "to see how the lesson is landing" is the surveillance P25 puts out of scope."""
    other = main.find_account(LEARNER_USERNAME)["user_id"]
    other_dir = workspace / COURSE / "learners" / other
    other_dir.mkdir(parents=True, exist_ok=True)
    (other_dir / "MISSION.md").write_text("# a private mission\n", encoding="utf-8")

    assert (
        author.get(f"/api/file?course={COURSE}&path=learners/{other}/MISSION.md").status_code == 404
    )
    assert author.get(f"/workspace/{COURSE}/learners/{other}/MISSION.md").status_code == 404
    assert other not in author.get(f"/api/workspace?course={COURSE}").text


def test_no_route_declares_a_role_parameter() -> None:
    """A role that a caller could name in a query string or a body is not a role."""
    from fastapi.routing import APIRoute

    offenders = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        names = {field.name for field in route.dependant.query_params}
        names |= {field.name for field in route.dependant.path_params}
        names |= {field.name for field in route.dependant.body_params}
        if names & {"role", "require", "is_admin", "author"}:
            offenders.append(f"{sorted(route.methods)} {route.path}: {sorted(names)}")

    assert offenders == []


def test_a_slug_with_orphaned_enrollments_does_not_hand_them_to_a_new_course(
    author, learner, workspace: Path
) -> None:
    """A course renamed or removed outside the app leaves records behind. Nobody holds a role
    in a course that does not exist, so a new course at that slug must not inherit the list."""
    stranger_id = main.create_account("orphan-holder", LEARNER_PASSWORD)["user_id"]
    main.enroll(stranger_id, "gone-from-disk", ROLE_AUTHOR)

    created = author.post("/api/courses", json={"slug": "gone-from-disk"})

    assert created.status_code == 200, created.text
    assert main.course_role(stranger_id, "gone-from-disk") is None
    assert main.course_role(DEFAULT_USER_ID, "gone-from-disk") == ROLE_AUTHOR


def test_renaming_onto_a_slug_with_orphaned_enrollments_does_not_inherit_them(
    author, workspace: Path
) -> None:
    stranger_id = main.create_account("other-orphan-holder", LEARNER_PASSWORD)["user_id"]
    main.enroll(stranger_id, "target-slug", ROLE_AUTHOR)

    assert author.patch(f"/api/courses/{COURSE}", json={"new_slug": "target-slug"}).status_code == 200

    assert main.course_role(stranger_id, "target-slug") is None
    assert main.course_role(DEFAULT_USER_ID, "target-slug") == ROLE_AUTHOR

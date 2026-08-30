# ABOUTME: The course directory is the boundary: no caller-supplied path — tool argument, query
# ABOUTME: string, URL segment or symlink inside a package — resolves to anything outside it.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from main import (
    DEFAULT_USER_ID,
    ROLE_AUTHOR,
    ROLE_LEARNER,
    ToolError,
    bootstrap_account,
    make_tools,
    resolve_in_course,
)

from .conftest import TEST_PASSWORD, TEST_USERNAME

COURSE = "course-a"
NEIGHBOUR = "course-b"
VICTIM = "victim"
SECRET = "VICTIM-MISSION-TEXT"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two courses side by side in one workspace, the second holding another person's record,
    plus the instance directory that holds this installation's credentials. The path checks
    resolve against WORKSPACE_ROOT, so it has to be the real path."""
    root = (tmp_path / "workspace").resolve()
    (root / COURSE / "lessons").mkdir(parents=True)
    (root / COURSE / "course.json").write_text('{"title": "A"}\n', encoding="utf-8")
    victim = root / NEIGHBOUR / "learners" / VICTIM
    victim.mkdir(parents=True)
    (victim / "MISSION.md").write_text(f"# {SECRET}\n", encoding="utf-8")
    (root / NEIGHBOUR / "lessons").mkdir(parents=True)
    (root / NEIGHBOUR / "lessons" / "0001-b.html").write_text("<h1>B</h1>", encoding="utf-8")
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def workspace_with_symlink(workspace: Path) -> Path:
    """A course package carrying a symlink out of itself. Copying a package into the workspace
    is the documented way to install one, and cp -R, tar and git all preserve symlinks, so a
    package can arrive holding one without anybody meaning it to."""
    (workspace / COURSE / "lessons" / "imported").symlink_to(
        Path("..") / ".." / NEIGHBOUR, target_is_directory=True
    )
    return workspace


def _tools(course_dir: Path, role: str) -> dict[str, object]:
    return {tool.__name__: tool for tool in make_tools(course_dir, DEFAULT_USER_ID, role)}


def _call(tool: object, **kwargs: object) -> str:
    return tool(**kwargs)  # type: ignore[operator]


# --- The tool surface ---------------------------------------------------------

ESCAPING_PATHS = [
    f"../{NEIGHBOUR}/learners/{VICTIM}/MISSION.md",
    f"../{NEIGHBOUR}/lessons/0001-b.html",
    "../.keating/accounts.json",
    "../.keating/session-key",
    "..",
    "../",
    "lessons/../../.keating/sessions.json",
]


@pytest.mark.parametrize("role", [ROLE_LEARNER, ROLE_AUTHOR])
@pytest.mark.parametrize("tool_name", ["read_file", "list_dir"])
@pytest.mark.parametrize("relative_path", ESCAPING_PATHS)
def test_reads_cannot_leave_the_course(
    workspace: Path, tool_name: str, relative_path: str, role: str
) -> None:
    """Reads are role-invariant, and so is this: neither role's session reaches another
    course's package, another course's learners, or the instance's own credentials."""
    with pytest.raises(ToolError) as excinfo:
        _call(_tools(workspace / COURSE, role)[tool_name], relative_path=relative_path)
    assert "outside the course" in str(excinfo.value)


@pytest.mark.parametrize("role", [ROLE_LEARNER, ROLE_AUTHOR])
def test_writes_cannot_leave_the_course(workspace: Path, role: str) -> None:
    target = workspace / NEIGHBOUR / "lessons" / "0001-b.html"
    with pytest.raises(ToolError):
        _call(
            _tools(workspace / COURSE, role)["write_file"],
            relative_path=f"../{NEIGHBOUR}/lessons/0001-b.html",
            content="<h1>OWNED</h1>",
        )
    assert target.read_text(encoding="utf-8") == "<h1>B</h1>"


@pytest.mark.parametrize("role", [ROLE_LEARNER, ROLE_AUTHOR])
def test_a_symlink_out_of_the_package_is_not_a_way_through(
    workspace_with_symlink: Path, role: str
) -> None:
    with pytest.raises(ToolError) as excinfo:
        _call(
            _tools(workspace_with_symlink / COURSE, role)["read_file"],
            relative_path=f"lessons/imported/learners/{VICTIM}/MISSION.md",
        )
    assert SECRET not in str(excinfo.value)


def test_an_author_cannot_write_another_courses_package_through_a_symlink(
    workspace_with_symlink: Path,
) -> None:
    """An author's role widens what may be written in the course they author — one course."""
    target = workspace_with_symlink / NEIGHBOUR / "lessons" / "0001-b.html"
    with pytest.raises(ToolError):
        _call(
            _tools(workspace_with_symlink / COURSE, ROLE_AUTHOR)["write_file"],
            relative_path="lessons/imported/lessons/0001-b.html",
            content="<h1>OWNED</h1>",
        )
    assert target.read_text(encoding="utf-8") == "<h1>B</h1>"


@pytest.mark.parametrize("role", [ROLE_LEARNER, ROLE_AUTHOR])
def test_the_courses_own_files_are_still_reachable(workspace: Path, role: str) -> None:
    (workspace / COURSE / "lessons" / "0001-a.html").write_text("<h1>A</h1>", encoding="utf-8")
    tools = _tools(workspace / COURSE, role)
    assert _call(tools["read_file"], relative_path="lessons/0001-a.html") == "<h1>A</h1>"
    assert "0001-a.html" in _call(tools["list_dir"], relative_path="lessons")
    assert "lessons/" in _call(tools["list_dir"], relative_path="")


# --- resolve_in_course, which every file route goes through -------------------


@pytest.mark.parametrize("relative_path", ESCAPING_PATHS)
def test_resolve_in_course_refuses_a_path_that_leaves_the_course(
    workspace: Path, relative_path: str
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        resolve_in_course(workspace / COURSE, relative_path)
    assert excinfo.value.status_code == 400


def test_resolve_in_course_still_resolves_the_courses_own_files(workspace: Path) -> None:
    course_dir = workspace / COURSE
    assert resolve_in_course(course_dir, "lessons") == course_dir / "lessons"
    assert resolve_in_course(course_dir, "") == course_dir


# --- The file routes ----------------------------------------------------------


@pytest.fixture
def client(workspace_with_symlink: Path):
    """One signed-in account, enrolled in the course holding the symlink and in nothing else."""
    with TestClient(main.app, base_url="https://testserver") as client:
        bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        assert client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        ).status_code == 200
        yield client


ESCAPING_ROUTE_PATHS = [
    f"lessons/imported/learners/{VICTIM}/MISSION.md",
    "lessons/imported/lessons/0001-b.html",
]


@pytest.mark.parametrize("path", ESCAPING_ROUTE_PATHS)
def test_api_file_refuses_a_path_that_leaves_the_course(client: TestClient, path: str) -> None:
    response = client.get(f"/api/file?course={COURSE}&path={path}")
    assert response.status_code == 400
    assert SECRET not in response.text


@pytest.mark.parametrize("path", ESCAPING_ROUTE_PATHS)
def test_the_workspace_route_refuses_a_path_that_leaves_the_course(
    client: TestClient, path: str
) -> None:
    response = client.get(f"/workspace/{COURSE}/{path}")
    assert response.status_code == 400
    assert SECRET not in response.text


def test_the_file_tree_does_not_walk_out_of_the_course(client: TestClient) -> None:
    """Not the files, and not the fact of them: a tree that listed another course's learners
    would name who is enrolled there, which is the disclosure P25 forbids even when every one
    of those paths answers 400."""
    body = client.get(f"/api/workspace?course={COURSE}").text
    assert VICTIM not in body
    assert "0001-b.html" not in body

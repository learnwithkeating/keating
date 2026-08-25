# ABOUTME: Tests for the per-user storage dimension: the learner_dir accessor's validation,
# ABOUTME: the startup migration from the single-learner layout, and the learners/ guardrails.

from __future__ import annotations

import json
from pathlib import Path

import pytest
from anthropic.lib.tools import ToolError
from fastapi import HTTPException

import main
from main import (
    DEFAULT_USER_ID,
    LEARNERS_DIR_NAME,
    LEGACY_LEARNER_DIR_NAME,
    learner_dir,
    learner_rel_path,
    make_tools,
    migrate_workspace_learner_dirs,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace that WORKSPACE_ROOT points at for the duration of one test.
    The path-safety checks resolve against WORKSPACE_ROOT, so it has to be the real one."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _course(workspace: Path, slug: str = "a-course") -> Path:
    course_dir = workspace / slug
    course_dir.mkdir()
    return course_dir


# --- The accessor -------------------------------------------------------------


def test_learner_dir_is_under_learners(workspace: Path) -> None:
    course_dir = _course(workspace)
    assert learner_dir(course_dir, "default") == course_dir / LEARNERS_DIR_NAME / "default"


def test_learner_dir_does_not_create_by_default(workspace: Path) -> None:
    course_dir = _course(workspace)
    assert not learner_dir(course_dir, "default").exists()
    assert learner_dir(course_dir, "default", create=True).is_dir()


@pytest.mark.parametrize(
    "user_id",
    [
        "../../etc",
        "a/b",
        "..",
        ".",
        ".hidden",
        "",
        "/absolute",
        "-leading-hyphen",
        "has space",
        "has.dot",
        "x" * 65,
    ],
)
def test_learner_dir_rejects_bad_user_ids(workspace: Path, user_id: str) -> None:
    course_dir = _course(workspace)
    with pytest.raises(HTTPException) as excinfo:
        learner_dir(course_dir, user_id)
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize("user_id", ["default", "a", "A1", "with_underscore", "with-hyphen", "x" * 64])
def test_learner_dir_accepts_good_user_ids(workspace: Path, user_id: str) -> None:
    course_dir = _course(workspace)
    assert learner_dir(course_dir, user_id).name == user_id


def test_learner_dir_rejects_symlink_escape(workspace: Path, tmp_path: Path) -> None:
    """A valid id whose directory is a symlink pointing out of the workspace is still an
    escape: the accessor resolves before it prefix-checks."""
    course_dir = _course(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    (course_dir / LEARNERS_DIR_NAME).mkdir()
    (course_dir / LEARNERS_DIR_NAME / "default").symlink_to(outside)
    with pytest.raises(HTTPException) as excinfo:
        learner_dir(course_dir, "default")
    assert excinfo.value.status_code == 400


def test_the_bootstrap_account_owns_the_default_user_id(workspace: Path) -> None:
    """The first account is assigned DEFAULT_USER_ID, which is what keeps a record written
    before accounts existed reachable without moving a single directory."""
    assert main.bootstrap_account("tester", "correct-horse-battery-staple")["user_id"] == (
        DEFAULT_USER_ID
    )


def test_learner_rel_path_is_course_relative(workspace: Path) -> None:
    assert learner_rel_path("default", "learning-records") == "learners/default/learning-records"


# --- The migration ------------------------------------------------------------


def _seed_legacy(course_dir: Path) -> Path:
    legacy = course_dir / LEGACY_LEARNER_DIR_NAME
    (legacy / ".state-history").mkdir(parents=True)
    (legacy / "MISSION.md").write_text("# Mission\n", encoding="utf-8")
    (legacy / ".practice-log.jsonl").write_text('{"ts": "x"}\n', encoding="utf-8")
    return legacy


def test_migration_moves_legacy_layout(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    course_dir = _course(workspace)
    _seed_legacy(course_dir)

    migrate_workspace_learner_dirs(workspace)

    migrated = course_dir / LEARNERS_DIR_NAME / DEFAULT_USER_ID
    assert not (course_dir / LEGACY_LEARNER_DIR_NAME).exists()
    assert (migrated / "MISSION.md").read_text(encoding="utf-8") == "# Mission\n"
    assert (migrated / ".practice-log.jsonl").is_file()
    assert (migrated / ".state-history").is_dir()
    assert "migrated" in capsys.readouterr().out


def test_migration_is_idempotent(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    course_dir = _course(workspace)
    _seed_legacy(course_dir)

    migrate_workspace_learner_dirs(workspace)
    capsys.readouterr()
    before = sorted(p.relative_to(course_dir).as_posix() for p in course_dir.rglob("*"))

    migrate_workspace_learner_dirs(workspace)

    after = sorted(p.relative_to(course_dir).as_posix() for p in course_dir.rglob("*"))
    assert after == before
    assert capsys.readouterr().out == ""


def test_migration_skips_a_course_with_no_learner_state(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    course_dir = _course(workspace)
    (course_dir / "lessons").mkdir()

    migrate_workspace_learner_dirs(workspace)

    assert not (course_dir / LEARNERS_DIR_NAME).exists()
    assert capsys.readouterr().out == ""


def test_migration_refuses_an_ambiguous_course(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both directories present is a state a human has to resolve: nothing is moved, nothing
    is merged, and the warning names the course."""
    course_dir = _course(workspace, "ambiguous-course")
    _seed_legacy(course_dir)
    existing = course_dir / LEARNERS_DIR_NAME / DEFAULT_USER_ID
    existing.mkdir(parents=True)
    (existing / "MISSION.md").write_text("# Newer mission\n", encoding="utf-8")

    migrate_workspace_learner_dirs(workspace)

    assert (course_dir / LEGACY_LEARNER_DIR_NAME / "MISSION.md").read_text(
        encoding="utf-8"
    ) == "# Mission\n"
    assert (existing / "MISSION.md").read_text(encoding="utf-8") == "# Newer mission\n"
    output = capsys.readouterr().out
    assert "ambiguous-course" in output
    assert "by hand" in output


def test_migration_skips_reserved_and_hidden_directories(workspace: Path) -> None:
    for name in (".archive", "docs"):
        reserved = workspace / name
        reserved.mkdir()
        _seed_legacy(reserved)

    migrate_workspace_learner_dirs(workspace)

    for name in (".archive", "docs"):
        assert (workspace / name / LEGACY_LEARNER_DIR_NAME).is_dir()
        assert not (workspace / name / LEARNERS_DIR_NAME).exists()


def test_migration_tolerates_an_absent_workspace(tmp_path: Path) -> None:
    migrate_workspace_learner_dirs(tmp_path / "nope")  # no exception is the assertion


# --- The tool guardrails ------------------------------------------------------


def _tools(course_dir: Path) -> dict[str, object]:
    return {tool.name: tool for tool in make_tools(course_dir, DEFAULT_USER_ID)}


def _call(tool: object, **kwargs: object) -> str:
    return tool.call(kwargs)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "relative_path",
    [
        # The platform's own logs and snapshots: hidden, and never tool-written.
        "learners/default/.practice-log.jsonl",
        # Records have dedicated tools so they can only be appended and superseded.
        "learners/default/learning-records/x.md",
        # Cross-learner isolation: another learner's state, and the shared root itself.
        "learners/someone-else/MISSION.md",
        "learners/default",
        "learners",
    ],
)
def test_write_file_refuses_records_logs_and_other_learners(
    workspace: Path, relative_path: str
) -> None:
    course_dir = _course(workspace)
    learner_dir(course_dir, DEFAULT_USER_ID, create=True)
    with pytest.raises(ToolError) as excinfo:
        _call(_tools(course_dir)["write_file"], relative_path=relative_path, content="x")
    message = str(excinfo.value)
    assert (
        "append_learning_record" in message
        or "another learner" in message
        or "Hidden files" in message
        or "is a directory" in message
    )


@pytest.mark.parametrize(
    "relative_path",
    ["learners/default/MISSION.md", "learners/default/NOTES.md", "learners/default/GLOSSARY.md"],
)
def test_write_file_still_writes_the_learners_own_state(workspace: Path, relative_path: str) -> None:
    """The three learner-state documents the teaching agent legitimately authors: the mission
    it establishes by interview, the notes that are its own scratchpad, and the glossary whose
    drafts-first discipline lives in TEACHING-POLICY.md rather than in withholding the file.
    Isolating learners must not take these away, or SKILL.md would instruct the agent to do
    something its tools refuse."""
    course_dir = _course(workspace)
    learner_dir(course_dir, DEFAULT_USER_ID, create=True)
    _call(_tools(course_dir)["write_file"], relative_path=relative_path, content="# hello\n")
    assert (course_dir / relative_path).read_text(encoding="utf-8") == "# hello\n"


def test_write_file_still_writes_the_course_package(workspace: Path) -> None:
    course_dir = _course(workspace)
    _call(
        _tools(course_dir)["write_file"],
        relative_path="lessons/0001-a.html",
        content="<h1>A</h1>",
    )
    assert (course_dir / "lessons" / "0001-a.html").read_text(encoding="utf-8") == "<h1>A</h1>"


def test_write_file_still_refuses_hidden_paths(workspace: Path) -> None:
    course_dir = _course(workspace)
    with pytest.raises(ToolError) as excinfo:
        _call(_tools(course_dir)["write_file"], relative_path=".secret/x.md", content="x")
    assert "dot-path" in str(excinfo.value)


@pytest.mark.parametrize("tool_name", ["read_file", "list_dir"])
def test_tools_refuse_another_learners_directory(workspace: Path, tool_name: str) -> None:
    course_dir = _course(workspace)
    other = course_dir / LEARNERS_DIR_NAME / "someone-else"
    other.mkdir(parents=True)
    (other / "MISSION.md").write_text("# Not yours\n", encoding="utf-8")
    with pytest.raises(ToolError) as excinfo:
        _call(_tools(course_dir)[tool_name], relative_path=f"{LEARNERS_DIR_NAME}/someone-else")
    assert "another learner's" in str(excinfo.value)


def test_read_file_still_reads_this_learners_own_state(workspace: Path) -> None:
    course_dir = _course(workspace)
    mine = learner_dir(course_dir, DEFAULT_USER_ID, create=True)
    (mine / "MISSION.md").write_text("# Mine\n", encoding="utf-8")
    text = _call(
        _tools(course_dir)["read_file"],
        relative_path=learner_rel_path(DEFAULT_USER_ID, "MISSION.md"),
    )
    assert text == "# Mine\n"


def test_append_learning_record_writes_under_this_learner(workspace: Path) -> None:
    course_dir = _course(workspace)
    result = _call(
        _tools(course_dir)["append_learning_record"],
        title="Spacing beats massing",
        body="Evidence: the seeded practice log.",
    )
    expected = learner_rel_path(
        DEFAULT_USER_ID, "learning-records", "0001-spacing-beats-massing.md"
    )
    assert result == f"Created {expected}"
    assert (course_dir / expected).is_file()


# --- The reads stay inside one learner ----------------------------------------


def test_practice_events_are_read_per_user(workspace: Path) -> None:
    """Two learners on one shared course: neither aggregate sees the other's attempts, and
    no helper anywhere sums them (charter P25)."""
    course_dir = _course(workspace)
    for user_id, count in (("alice", 2), ("bob", 5)):
        log = learner_dir(course_dir, user_id, create=True) / main.PRACTICE_LOG_NAME
        log.write_text(
            "".join(
                json.dumps(
                    {
                        "ts": f"2026-01-0{index + 1}T10:00:00+00:00",
                        "item_id": f"{user_id}-{index}",
                        "verdict": "correct",
                        "confidence": 3,
                    }
                )
                + "\n"
                for index in range(count)
            ),
            encoding="utf-8",
        )
    assert len(main._read_practice_events(course_dir, "alice")) == 2
    assert len(main._read_practice_events(course_dir, "bob")) == 5


def test_workspace_tree_hides_other_learners(workspace: Path) -> None:
    course_dir = _course(workspace)
    (learner_dir(course_dir, DEFAULT_USER_ID, create=True) / "MISSION.md").write_text(
        "# Mine\n", encoding="utf-8"
    )
    other = course_dir / LEARNERS_DIR_NAME / "someone-else"
    other.mkdir(parents=True)
    (other / "MISSION.md").write_text("# Not yours\n", encoding="utf-8")

    tree = main._build_tree(
        course_dir, course_dir, learner_dir(course_dir, DEFAULT_USER_ID)
    )
    learners = next(node for node in tree["children"] if node["name"] == LEARNERS_DIR_NAME)
    assert [child["name"] for child in learners["children"]] == [DEFAULT_USER_ID]


def test_file_endpoints_refuse_another_learners_file(workspace: Path) -> None:
    course_dir = _course(workspace)
    other = course_dir / LEARNERS_DIR_NAME / "someone-else"
    other.mkdir(parents=True)
    (other / "MISSION.md").write_text("# Not yours\n", encoding="utf-8")

    # user_id is passed explicitly because the route resolves it from the session, and there
    # is no session in a direct call. That these fail to import a user id from anywhere is the
    # point of the dependency: a call site that does not say whose record it wants gets none.
    with pytest.raises(HTTPException) as excinfo:
        main.get_file(
            course=course_dir.name,
            path="learners/someone-else/MISSION.md",
            user_id=DEFAULT_USER_ID,
        )
    assert excinfo.value.status_code == 404

    with pytest.raises(HTTPException) as excinfo:
        main.get_workspace_file(
            course=course_dir.name,
            file_path="learners/someone-else/MISSION.md",
            user_id=DEFAULT_USER_ID,
        )
    assert excinfo.value.status_code == 404


def test_own_learner_file_is_still_served(workspace: Path) -> None:
    course_dir = _course(workspace)
    (learner_dir(course_dir, DEFAULT_USER_ID, create=True) / "MISSION.md").write_text(
        "# Mine\n", encoding="utf-8"
    )
    response = main.get_file(
        course=course_dir.name,
        path=learner_rel_path(DEFAULT_USER_ID, "MISSION.md"),
        user_id=DEFAULT_USER_ID,
    )
    assert response.body == b"# Mine\n"

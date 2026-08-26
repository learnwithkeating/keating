# ABOUTME: Tests for what the workspace root is allowed to be — the startup check that says so
# ABOUTME: when it is missing or is not a directory, and the reservation of .claude.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from main import (
    AGENT_CONFIG_DIR_NAME,
    RESERVED_DIRS,
    WORKSPACE_ROOT_ENV_VAR,
    resolve_course_dir,
    warn_if_workspace_root_is_unusable,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace that WORKSPACE_ROOT points at for the duration of one test."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


# --- The startup check --------------------------------------------------------


def test_a_workspace_that_is_there_says_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    warn_if_workspace_root_is_unusable(tmp_path)
    assert capsys.readouterr().out == ""


def test_a_missing_workspace_names_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure this catches looks exactly like a first run: no courses, no records. The
    warning has to carry the path, or there is nothing to compare against what was meant."""
    monkeypatch.delenv(WORKSPACE_ROOT_ENV_VAR, raising=False)
    missing = tmp_path / "not-there"

    warn_if_workspace_root_is_unusable(missing)

    output = capsys.readouterr().out
    assert str(missing) in output
    assert "does not exist" in output


def test_an_explicitly_set_missing_workspace_is_reported_as_a_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path someone chose and that is not there is a misconfiguration; the same path
    arrived at by default is an installation that has not made its courses directory yet.
    Naming the variable is what tells the two apart."""
    missing = tmp_path / "typo"
    monkeypatch.setenv(WORKSPACE_ROOT_ENV_VAR, str(missing))

    warn_if_workspace_root_is_unusable(missing)

    output = capsys.readouterr().out
    assert WORKSPACE_ROOT_ENV_VAR in output
    assert str(missing) in output


def test_a_workspace_that_is_a_file_is_reported_as_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_dir = tmp_path / "courses"
    not_a_dir.write_text("", encoding="utf-8")

    warn_if_workspace_root_is_unusable(not_a_dir)

    output = capsys.readouterr().out
    assert str(not_a_dir) in output
    assert "not a directory" in output


def test_startup_reports_a_missing_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through the real lifespan: a missing workspace is announced before the migrations run,
    which is the only order in which the message is useful — both of them no-op silently on a
    root that is not there, which is exactly what makes the state hard to recognise."""
    from fastapi.testclient import TestClient

    missing = tmp_path / "gone"
    monkeypatch.setattr(main, "WORKSPACE_ROOT", missing)
    monkeypatch.setattr(main, "LEGACY_SETTINGS_PATH", tmp_path / "legacy-settings.json")

    with TestClient(main.app):
        pass

    assert str(missing) in capsys.readouterr().out


# --- .claude is not a course --------------------------------------------------


def test_the_agent_config_directory_is_reserved() -> None:
    assert AGENT_CONFIG_DIR_NAME in RESERVED_DIRS


def test_the_agent_config_directory_is_not_a_course(workspace: Path) -> None:
    (workspace / AGENT_CONFIG_DIR_NAME).mkdir()

    with pytest.raises(HTTPException) as excinfo:
        resolve_course_dir(AGENT_CONFIG_DIR_NAME)

    assert excinfo.value.status_code == 400


def test_a_symlinked_slug_cannot_reach_the_agent_config_directory(workspace: Path) -> None:
    """Reserving the name only rejects a slug that spells it. A symlink is how a slug the
    course regex accepts reaches the directory anyway, so the resolved path is checked too."""
    (workspace / AGENT_CONFIG_DIR_NAME).mkdir()
    (workspace / "notes").symlink_to(workspace / AGENT_CONFIG_DIR_NAME)

    with pytest.raises(HTTPException) as excinfo:
        resolve_course_dir("notes")

    assert excinfo.value.status_code == 400
    assert AGENT_CONFIG_DIR_NAME in excinfo.value.detail


def test_the_agent_config_directory_is_not_listed_as_a_course(workspace: Path) -> None:
    (workspace / AGENT_CONFIG_DIR_NAME).mkdir()
    (workspace / "a-real-course").mkdir()

    slugs = {course["slug"] for course in main.list_courses()["courses"]}

    assert slugs == {"a-real-course"}

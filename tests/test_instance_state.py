# ABOUTME: Tests for where the platform keeps its own instance state — settings.json under the
# ABOUTME: workspace's .keating/ — and for the startup migration out of the old in-repo location.

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import (
    INSTANCE_DIR_NAME,
    MIGRATED_SUFFIX,
    RESERVED_DIRS,
    InstanceStateError,
    _load_settings,
    _save_settings,
    app,
    migrate_settings_file,
    resolve_course_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

SAVED = {
    "chat_model": "claude-haiku-4-5",
    "grading_model": "claude-sonnet-5",
    "layout": {"remember_sizes": True, "sidebar_w": 300, "chat_w": 500},
}


@pytest.fixture
def instance_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace whose instance directory SETTINGS_PATH points into, so no test
    here reads or writes the settings of the installation running it."""
    path = (tmp_path / "workspace" / INSTANCE_DIR_NAME).resolve()
    monkeypatch.setattr(main, "SETTINGS_PATH", path / "settings.json")
    return path


# --- Where instance state lives -----------------------------------------------


def test_the_instance_directory_is_reserved() -> None:
    assert INSTANCE_DIR_NAME == ".keating"
    assert INSTANCE_DIR_NAME in RESERVED_DIRS


def test_saving_creates_the_instance_directory(instance_dir: Path) -> None:
    assert not instance_dir.exists()

    _save_settings(SAVED)

    assert json.loads((instance_dir / "settings.json").read_text(encoding="utf-8")) == SAVED
    assert sorted(p.name for p in instance_dir.iterdir()) == ["settings.json"]


def test_saved_settings_are_read_back(instance_dir: Path) -> None:
    _save_settings(SAVED)

    assert _load_settings() == SAVED


def test_saving_names_an_instance_path_that_is_not_a_directory(instance_dir: Path) -> None:
    """Something already occupying .keating is a fixable situation, and the error has to say
    so: mkdir's own FileExistsError reports only that the path exists."""
    instance_dir.parent.mkdir(parents=True)
    instance_dir.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(InstanceStateError) as raised:
        _save_settings(SAVED)

    assert str(instance_dir) in str(raised.value)


# --- The migration ------------------------------------------------------------


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    legacy = tmp_path / "install" / "settings.json"
    legacy.parent.mkdir()
    current = tmp_path / "workspace" / INSTANCE_DIR_NAME / "settings.json"
    return legacy, current


def _seed_legacy(legacy: Path) -> None:
    legacy.write_text(json.dumps(SAVED, indent=2) + "\n", encoding="utf-8")


def test_migration_moves_the_installs_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)

    migrate_settings_file(legacy, current)

    assert not legacy.exists()
    assert json.loads(current.read_text(encoding="utf-8")) == SAVED
    assert "migrated" in capsys.readouterr().out


def test_migration_keeps_the_file_it_migrated_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The legacy file is outside the workspace and is the only copy of the preferences the
    platform holds, so the migration sets it aside instead of consuming it: a start pointed at
    a workspace the operator did not mean stays recoverable, and the message says from where."""
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)
    kept = legacy.with_name(legacy.name + MIGRATED_SUFFIX)

    migrate_settings_file(legacy, current)

    assert json.loads(kept.read_text(encoding="utf-8")) == SAVED
    assert str(kept) in capsys.readouterr().out


def test_migration_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)

    migrate_settings_file(legacy, current)
    capsys.readouterr()
    before = current.read_text(encoding="utf-8")

    migrate_settings_file(legacy, current)

    assert current.read_text(encoding="utf-8") == before
    assert capsys.readouterr().out == ""


def test_migration_refuses_an_ambiguous_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file at both locations is a state only a human can resolve: nothing is moved,
    nothing is merged, and the warning names both paths."""
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)
    current.parent.mkdir(parents=True)
    current.write_text('{"chat_model": "claude-opus-5"}\n', encoding="utf-8")

    migrate_settings_file(legacy, current)

    assert json.loads(legacy.read_text(encoding="utf-8")) == SAVED
    assert json.loads(current.read_text(encoding="utf-8")) == {"chat_model": "claude-opus-5"}
    output = capsys.readouterr().out
    assert str(legacy) in output
    assert str(current) in output
    assert "by hand" in output


def test_migration_tolerates_an_absent_install_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy, current = _paths(tmp_path)

    migrate_settings_file(legacy, current)

    assert not current.parent.exists()
    assert capsys.readouterr().out == ""


def test_migration_leaves_no_half_written_settings_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workspace is routinely on a different filesystem from the code, which makes the
    move a copy. A copy interrupted by a full or failing disk must not leave a truncated
    settings.json for the app to read as corrupt and silently answer with defaults."""
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)

    def fail_after_writing_something(source: str, destination: str) -> str:
        Path(destination).write_text('{"chat_mo', encoding="utf-8")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copyfile", fail_after_writing_something)
    migrate_settings_file(legacy, current)

    assert not current.exists()
    assert sorted(p.name for p in current.parent.iterdir()) == []
    assert json.loads(legacy.read_text(encoding="utf-8")) == SAVED
    assert "No space left on device" in capsys.readouterr().out


def test_migration_reports_an_instance_path_that_is_not_a_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A settings location that cannot be created is worth a report, never a refusal to
    start: the app runs, the preferences stay where they are, and the message names both."""
    legacy, current = _paths(tmp_path)
    _seed_legacy(legacy)
    current.parent.parent.mkdir(parents=True)
    current.parent.write_text("not a directory\n", encoding="utf-8")

    migrate_settings_file(legacy, current)

    assert json.loads(legacy.read_text(encoding="utf-8")) == SAVED
    output = capsys.readouterr().out
    assert str(current.parent) in output
    assert str(legacy) in output


# --- Startup and the API ------------------------------------------------------


def test_the_suite_never_points_the_migration_at_the_checkout() -> None:
    """The session-wide guard in tests/conftest.py, asserted rather than assumed: every test
    that enters the app's lifespan runs the migration, and the file it would consume on a
    source installation is the developer's own."""
    assert REPO_ROOT not in main.LEGACY_SETTINGS_PATH.parents


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace wired up the way a real installation is: WORKSPACE_ROOT, the
    settings path inside it, and an isolated copy of the in-memory settings dict."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(main, "SETTINGS_PATH", root / INSTANCE_DIR_NAME / "settings.json")
    monkeypatch.setattr(main, "LEGACY_SETTINGS_PATH", tmp_path / "install" / "settings.json")
    monkeypatch.setattr(main, "SETTINGS", dict(main.SETTINGS))
    return root


def test_startup_migrates_and_serves_the_migrated_settings(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SETTINGS is read at import, before the migration can have put the file in place, so
    startup has to read it again once the file is where the app now keeps it."""
    main.LEGACY_SETTINGS_PATH.parent.mkdir()
    _seed_legacy(main.LEGACY_SETTINGS_PATH)

    with TestClient(app) as client:
        body = client.get("/api/settings").json()

    assert body["chat_model"] == SAVED["chat_model"]
    assert body["layout"] == SAVED["layout"]
    assert not main.LEGACY_SETTINGS_PATH.exists()


def test_startup_survives_an_unusable_instance_directory(workspace: Path) -> None:
    """Where settings are kept must never be what stops the app from starting: the migration
    reports what is in the way and the app serves the settings it can read."""
    main.LEGACY_SETTINGS_PATH.parent.mkdir()
    _seed_legacy(main.LEGACY_SETTINGS_PATH)
    (workspace / INSTANCE_DIR_NAME).write_text("not a directory\n", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    assert json.loads(main.LEGACY_SETTINGS_PATH.read_text(encoding="utf-8")) == SAVED


def test_put_settings_persists_into_the_workspace(workspace: Path) -> None:
    """The regression the container job proves end to end: a save must land on the mounted
    volume, not beside the code."""
    with TestClient(app) as client:
        response = client.put("/api/settings", json=SAVED)

    assert response.status_code == 200
    written = workspace / INSTANCE_DIR_NAME / "settings.json"
    assert json.loads(written.read_text(encoding="utf-8")) == SAVED


def test_put_settings_names_an_unusable_instance_directory(workspace: Path) -> None:
    """A save that cannot happen answers with what is wrong and where, rather than with the
    bare 500 an unhandled filesystem error produces."""
    (workspace / INSTANCE_DIR_NAME).write_text("not a directory\n", encoding="utf-8")

    with TestClient(app) as client:
        response = client.put("/api/settings", json=SAVED)

    assert response.status_code == 500
    assert str(workspace / INSTANCE_DIR_NAME) in response.json()["detail"]


def test_the_instance_directory_is_not_a_course(workspace: Path) -> None:
    (workspace / INSTANCE_DIR_NAME).mkdir()
    (workspace / "a-course").mkdir()

    with TestClient(app) as client:
        slugs = [course["slug"] for course in client.get("/api/courses").json()["courses"]]

    assert slugs == ["a-course"]


def test_a_symlinked_slug_cannot_reach_the_instance_directory(workspace: Path) -> None:
    """Reserving the name only stops a course called .keating, which no slug can be anyway.
    A link is how a valid slug reaches the instance directory, so the resolved path is what
    the check has to be against — the same guard the archive already carries."""
    (workspace / INSTANCE_DIR_NAME).mkdir()
    (workspace / "notes").symlink_to(workspace / INSTANCE_DIR_NAME, target_is_directory=True)

    with pytest.raises(main.HTTPException) as raised:
        resolve_course_dir("notes")

    assert raised.value.status_code == 400
    assert INSTANCE_DIR_NAME in raised.value.detail

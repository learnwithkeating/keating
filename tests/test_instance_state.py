# ABOUTME: Tests for where the platform keeps its own instance state — settings.json under the
# ABOUTME: workspace's .keating/ — and for the startup migration out of the old in-repo location.

from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
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

from .conftest import TEST_PASSWORD, TEST_USERNAME

REPO_ROOT = Path(__file__).resolve().parents[1]

SAVED = {
    "chat_model": "claude-haiku-4-5",
    "grading_model": "claude-sonnet-5",
    "layout": {"remember_sizes": True, "sidebar_w": 300, "chat_w": 500},
}


@pytest.fixture
def instance_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway workspace whose instance directory the settings path points into, so no
    test here reads or writes the settings of the installation running it. Pointing
    WORKSPACE_ROOT at it is the whole wiring: every instance-state path is resolved from
    there when it is asked for."""
    root = (tmp_path / "workspace").resolve()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root / INSTANCE_DIR_NAME


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


def test_saving_names_an_instance_path_that_is_not_a_directory(instance_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
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

    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
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

    with TestClient(app, base_url="https://testserver") as client:
        # A directory that cannot hold state cannot hold an account either, so what is asserted
        # is that the app starts and answers rather than that a signed-in caller sees settings:
        # /api/session is the public route the shell's login view is built on.
        session = client.get("/api/session")
        settings = client.get("/api/settings")

    assert session.status_code == 200
    assert session.json() == {"authenticated": False, "bootstrapped": False}
    # Alive and refusing, rather than crashed: a startup that raised here would answer nothing.
    assert settings.status_code == 401
    assert json.loads(main.LEGACY_SETTINGS_PATH.read_text(encoding="utf-8")) == SAVED


def test_a_store_that_disappears_does_not_sign_everyone_out(workspace: Path) -> None:
    """The stores re-read themselves when a file changes underneath the process, so a workspace
    that goes away — an unmounted volume, a deleted directory — would otherwise read as "no
    accounts": everyone signed out at once, and the instance reporting itself as never
    bootstrapped. Absent at startup and absent after a read are different facts."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        shutil.rmtree(workspace / INSTANCE_DIR_NAME)

        session = client.get("/api/session")
        settings = client.get("/api/settings")

    assert session.json()["authenticated"] is True
    assert session.json()["bootstrapped"] is True
    assert settings.status_code == 200


def test_put_settings_persists_into_the_workspace(workspace: Path) -> None:
    """The regression the container job proves end to end: a save must land on the mounted
    volume, not beside the code."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        response = client.put("/api/settings", json=SAVED)

    assert response.status_code == 200
    written = workspace / INSTANCE_DIR_NAME / "settings.json"
    assert json.loads(written.read_text(encoding="utf-8")) == SAVED


def test_put_settings_names_an_unusable_instance_directory(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A save that cannot happen answers with what is wrong and where, rather than with the
    bare 500 an unhandled filesystem error produces. 503 and not 500, and the same 503 a
    login against the same directory gets: the instance is serving, and its state store is
    what is unavailable."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        shutil.rmtree(workspace / INSTANCE_DIR_NAME)
        (workspace / INSTANCE_DIR_NAME).write_text("not a directory\n", encoding="utf-8")
        response = client.put("/api/settings", json=SAVED)

    assert response.status_code == 503
    # The path names the instance's own layout, so it belongs in the log an
    # operator reads, not in a body an unauthenticated caller can provoke.
    assert str(workspace / INSTANCE_DIR_NAME) not in response.json()["detail"]
    assert str(workspace / INSTANCE_DIR_NAME) in capsys.readouterr().out


def test_the_instance_directory_is_not_a_course(workspace: Path) -> None:
    (workspace / INSTANCE_DIR_NAME).mkdir()
    (workspace / "a-course").mkdir()

    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
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


# --- A volume the app cannot write --------------------------------------------

# Ownership is the whole subject here, and root is exempt from it: every chmod below would
# still be writable, so the failure being tested cannot be created. The container job covers
# the same ground where uids are real.
not_as_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root writes through any permission bits, so nothing is refused"
)


@contextlib.contextmanager
def unwritable(path: Path) -> Iterator[None]:
    """Take away the caller's write access to a directory, and give it back afterwards — a
    temp directory that stays unwritable is one pytest cannot clean up."""
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o500)
    try:
        yield
    finally:
        path.chmod(original)


@not_as_root
def test_an_instance_directory_that_cannot_be_created_says_what_to_do(workspace: Path) -> None:
    """The container failure, in one call: the volume belongs to another user, so .keating
    cannot be created at all. mkdir's own PermissionError names the path and nothing else —
    not what the directory is for, and not that ownership of the mount is what to change."""
    with unwritable(workspace), pytest.raises(InstanceStateError) as raised:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    message = str(raised.value)
    assert str(workspace / INSTANCE_DIR_NAME) in message
    assert "--user" in message


@not_as_root
def test_an_instance_directory_that_cannot_be_written_says_what_to_do(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The same volume one step further on: .keating exists, from a run under the right
    ownership, and the next write into it is refused. Nothing is created, so the mkdir that
    reports the first case succeeds here and the refusal surfaces on the file instead."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with unwritable(workspace / INSTANCE_DIR_NAME), pytest.raises(InstanceStateError) as raised:
        main.create_account("someone-else", TEST_PASSWORD)

    assert str(workspace / INSTANCE_DIR_NAME) in str(raised.value)


@not_as_root
def test_signing_in_against_an_unwritable_volume_answers_rather_than_500s(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A login writes: the session it mints is instance state. On a volume the app cannot
    write that is a filesystem fact about the operator's deployment, and the answer has to say
    so — a 500 sends whoever hit it to the server log to find out that much."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        with unwritable(workspace / INSTANCE_DIR_NAME):
            response = client.post(
                "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
            )

    assert response.status_code == 503
    # The path names the instance's own layout, so it belongs in the log an
    # operator reads, not in a body an unauthenticated caller can provoke.
    assert str(workspace / INSTANCE_DIR_NAME) not in response.json()["detail"]
    assert str(workspace / INSTANCE_DIR_NAME) in capsys.readouterr().out


@not_as_root
def test_the_bootstrap_subcommand_reports_an_unwritable_volume(workspace: Path) -> None:
    """What an operator actually runs, as a real process. A traceback here is the CI failure
    this covers: the message that matters is on the last line of a stack the operator did not
    write and cannot act on."""
    with unwritable(workspace):
        result = subprocess.run(
            [sys.executable, "main.py", "bootstrap", "--username", "michelle"],
            cwd=str(REPO_ROOT),
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(workspace),
                "KEATING_WORKSPACE_ROOT": str(workspace),
                "KEATING_LEGACY_SETTINGS_PATH": str(workspace / "nonexistent-settings.json"),
            },
            input=TEST_PASSWORD + "\n",
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(workspace / INSTANCE_DIR_NAME) in result.stderr
    assert "--user" in result.stderr


@not_as_root
def test_an_expired_session_on_an_unwritable_volume_is_answered_too(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The sweep that retires an expired session is a write, and it happens in the middleware
    that fences every request — outside the routes, where a route's exception handling cannot
    reach it. So this is the one request path that can still meet an unwritable volume with
    nothing between it and the traceback."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        # On disk, because the store is re-read from there before the sweep decides anything.
        stored = json.loads(main.sessions_path().read_text(encoding="utf-8"))
        for record in stored["sessions"].values():
            record["expires_at"] = "2000-01-01T00:00:00+00:00"
        main.sessions_path().write_text(json.dumps(stored), encoding="utf-8")
        with unwritable(workspace / INSTANCE_DIR_NAME):
            response = client.get("/api/courses")

    assert response.status_code == 503
    # The path names the instance's own layout, so it belongs in the log an
    # operator reads, not in a body an unauthenticated caller can provoke.
    assert str(workspace / INSTANCE_DIR_NAME) not in response.json()["detail"]
    assert str(workspace / INSTANCE_DIR_NAME) in capsys.readouterr().out


@contextlib.contextmanager
def sealed(path: Path) -> Iterator[None]:
    """Take away every access to a directory, and give it back afterwards.

    This is the second shape the container failure takes, and the one an operator reaches by
    simply starting the container a second time: .keating exists, because a correctly-run
    container created it, and it is 0700 owned by a uid this process does not have. Its
    contents cannot be stat'd, let alone read — which is a different refusal from a directory
    that merely cannot be written into, and it arrives earlier, on paths that only read."""
    original = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o000)
    try:
        yield
    finally:
        path.chmod(original)


@not_as_root
def test_settings_that_cannot_be_read_fall_back_to_the_defaults(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """SETTINGS is read at import, so a refusal here is raised before there is an app to
    answer with it, before a route, and before any handler: the process dies on the import
    line with a traceback and the container crashloops. Preferences must never be what stops
    the app from starting, whatever the reason the file cannot be read."""
    _save_settings(SAVED)

    with sealed(workspace / INSTANCE_DIR_NAME):
        loaded = _load_settings()

    assert loaded == main.DEFAULT_SETTINGS


@not_as_root
def test_an_unreadable_instance_directory_does_not_stop_the_app_starting(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The decision this increment made is that the container keeps serving: refusing to boot
    turns a fixable misconfiguration into a crashloop, takes the diagnostic out of `docker
    logs` of a running container, and leaves the operator with a traceback instead of a
    sentence. A directory the app cannot read is the same misconfiguration as one it cannot
    write and must be answered the same way.

    Serving with no accounts in memory is safe here precisely because the refusal is the
    filesystem's: every path that could claim the first account re-reads the store under the
    interprocess lock, and that read meets the same refusal."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with (
        sealed(workspace / INSTANCE_DIR_NAME),
        TestClient(app, base_url="https://testserver") as client,
    ):
        session = client.get("/api/session")
        settings = client.get("/api/settings")

    # The body, not only the status: a cache half-replaced by a read that failed part way
    # leaves ACCOUNTS with no "accounts" key at all — not an empty store, a broken one — and
    # the first reader raises a KeyError inside a process that is still serving. Bootstrapped
    # stays true because the accounts this process already read are still its own; losing
    # access to the volume is not the same fact as there being nobody to sign in as.
    assert session.status_code == 200
    assert session.json() == {"authenticated": False, "bootstrapped": True}
    assert settings.status_code == 401
    assert str(workspace / INSTANCE_DIR_NAME) in capsys.readouterr().out


@not_as_root
def test_signing_in_against_an_unreadable_instance_directory_is_answered(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A login reads the account store before it writes a session, so on this volume it is
    refused one step earlier than on a merely unwritable one — and has to arrive at the same
    503 naming the same path."""
    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        with sealed(workspace / INSTANCE_DIR_NAME):
            response = client.post(
                "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
            )

    assert response.status_code == 503
    # The path names the instance's own layout, so it belongs in the log an
    # operator reads, not in a body an unauthenticated caller can provoke.
    assert str(workspace / INSTANCE_DIR_NAME) not in response.json()["detail"]
    assert str(workspace / INSTANCE_DIR_NAME) in capsys.readouterr().out


@not_as_root
def test_the_bootstrap_subcommand_reports_an_unreadable_instance_directory(
    workspace: Path,
) -> None:
    """The whole module is imported before argparse sees a word of the command line, so this
    covers the import-time read as well as the subcommand's own: a traceback in this stderr is
    an operator told to read a stack they did not write."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with sealed(workspace / INSTANCE_DIR_NAME):
        result = subprocess.run(
            [sys.executable, "main.py", "bootstrap", "--username", "michelle"],
            cwd=str(REPO_ROOT),
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(workspace),
                "KEATING_WORKSPACE_ROOT": str(workspace),
                "KEATING_LEGACY_SETTINGS_PATH": str(workspace / "nonexistent-settings.json"),
            },
            input=TEST_PASSWORD + "\n",
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(workspace / INSTANCE_DIR_NAME) in result.stderr
    assert "--user" in result.stderr


@not_as_root
def test_the_migration_tolerates_an_unreadable_instance_directory(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The migration runs at startup on a source installation, before anything else reads the
    instance directory. Where preferences are kept must never be what stops the app from
    starting — including when the check for a file already at the destination is itself
    refused."""
    main.LEGACY_SETTINGS_PATH.parent.mkdir()
    _seed_legacy(main.LEGACY_SETTINGS_PATH)
    (workspace / INSTANCE_DIR_NAME).mkdir()

    with sealed(workspace / INSTANCE_DIR_NAME):
        migrate_settings_file(main.LEGACY_SETTINGS_PATH, main.settings_path())

    assert json.loads(main.LEGACY_SETTINGS_PATH.read_text(encoding="utf-8")) == SAVED
    assert str(main.settings_path()) in capsys.readouterr().out


@not_as_root
def test_a_lock_the_kernel_refuses_is_answered_rather_than_500ing(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Taking the interprocess lock is the last syscall on the write path that the kernel can
    refuse for reasons the operator owns — ENOLCK on a mount that offers no locking, EINTR —
    and it happens after the descriptor is open, so nothing about the directory's permissions
    can produce it. It has to arrive as the same answer every other refusal on that path
    does."""

    def no_locks_available(descriptor: int, operation: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    with TestClient(app, base_url="https://testserver") as client:
        main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
        monkeypatch.setattr(main.fcntl, "flock", no_locks_available)
        response = client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        )

    assert response.status_code == 503
    # The lock's path names the instance's own layout, so it belongs in the log an
    # operator reads, not in a body an unauthenticated caller can provoke.
    assert str(main.store_lock_path()) not in response.json()["detail"]
    assert str(main.store_lock_path()) in capsys.readouterr().out


def test_settings_are_written_as_privately_as_every_other_instance_file(
    instance_dir: Path,
) -> None:
    """The instance directory is 0700, and _ensure_instance_dir leaves a wider mode in place
    on a volume whose ownership refuses the chmod — on the stated grounds that the files
    inside it are 0600. That is the claim this holds to."""
    _save_settings(SAVED)

    written = instance_dir / "settings.json"
    assert stat.S_IMODE(written.stat().st_mode) == main.PRIVATE_FILE_MODE


@not_as_root
def test_an_account_store_the_app_cannot_read_cannot_be_bootstrapped_over(
    workspace: Path,
) -> None:
    """What makes it safe for startup to serve past a store it could not read.

    Reading the store as empty would present the instance as never bootstrapped and offer the
    first account — and with it DEFAULT_USER_ID and whatever record already sits at
    learners/default/ — to whoever asked next. Startup does not refuse to boot on that, because
    a container that will not boot is a crashloop with no diagnostic in it. The guarantee is
    kept one layer in instead: every path that could claim an account re-reads the store under
    the interprocess lock, and meets the same refusal there."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    main.ACCOUNTS.clear()
    main.ACCOUNTS.update(main.empty_accounts())
    main.STORE_STAMPS.clear()
    main.accounts_path().chmod(0o000)

    try:
        with pytest.raises(InstanceStateError) as raised:
            main.bootstrap_account("whoever-asked-next", TEST_PASSWORD)
    finally:
        main.accounts_path().chmod(main.PRIVATE_FILE_MODE)

    assert str(main.accounts_path()) in str(raised.value)
    assert main.ACCOUNTS["accounts"] == []


def test_settings_resolve_under_the_workspace_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path bound at import is bound to whatever workspace the process was started against,
    which is the developer's own when the process is a test run: patching WORKSPACE_ROOT then
    redirects the accounts, sessions and enrollments beside it but not this file, and the
    suite writes a real installation's settings. Every instance-state path resolves the same
    way — from WORKSPACE_ROOT, when it is asked for."""
    root = (tmp_path / "elsewhere").resolve()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    assert main.settings_path() == root / INSTANCE_DIR_NAME / "settings.json"
    main._save_settings(dict(main.DEFAULT_SETTINGS))
    assert (root / INSTANCE_DIR_NAME / "settings.json").is_file()
    assert main._load_settings()["chat_model"] == main.DEFAULT_SETTINGS["chat_model"]

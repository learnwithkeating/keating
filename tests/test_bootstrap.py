# ABOUTME: Tests for how the first account comes into existence — the bootstrap subcommand, its
# ABOUTME: refusals, and the minted ids every account after the first one gets.

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import main
from main import (
    DEFAULT_USER_ID,
    INSTANCE_DIR_NAME,
    LEGACY_LEARNER_DIR_NAME,
    bootstrap_account,
)

from .conftest import TEST_PASSWORD, TEST_USERNAME

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _run_cli(workspace: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    """The bootstrap subcommand as an operator runs it: a real process, against a real
    workspace, with the password on stdin and never in argv."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workspace),
        "KEATING_WORKSPACE_ROOT": str(workspace),
        "KEATING_LEGACY_SETTINGS_PATH": str(workspace / "nonexistent-settings.json"),
    }
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=str(REPO_ROOT),
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def _tree(root: Path) -> dict[str, str]:
    """Every file under a root with a digest of its contents, for before/after comparison."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- The subcommand -----------------------------------------------------------


def test_bootstrap_creates_the_first_account_owning_the_default_user_id(workspace: Path) -> None:
    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 0, result.stderr
    stored = json.loads((workspace / INSTANCE_DIR_NAME / "accounts.json").read_text())
    assert [a["username"] for a in stored["accounts"]] == ["michelle"]
    assert stored["accounts"][0]["user_id"] == DEFAULT_USER_ID
    assert stored["accounts"][0]["is_admin"] is True
    assert stored["accounts"][0]["auth_method"] == "local"


def test_bootstrap_never_writes_the_password(workspace: Path) -> None:
    _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")
    written = (workspace / INSTANCE_DIR_NAME / "accounts.json").read_text()
    assert TEST_PASSWORD not in written


def test_bootstrap_refuses_when_an_account_already_exists(workspace: Path) -> None:
    _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    result = _run_cli(workspace, "bootstrap", "--username", "someone", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 1
    assert "invite" in (result.stdout + result.stderr)
    stored = json.loads((workspace / INSTANCE_DIR_NAME / "accounts.json").read_text())
    assert [a["username"] for a in stored["accounts"]] == ["michelle"]


def test_bootstrap_refuses_a_password_flag(workspace: Path) -> None:
    """A password in argv leaks into ps, docker inspect and the shell history file. The flag is
    refused by name so that nobody adds it back as a convenience."""
    result = _run_cli(workspace, "bootstrap", "--username", "michelle", "--password", TEST_PASSWORD)

    assert result.returncode != 0
    assert not (workspace / INSTANCE_DIR_NAME / "accounts.json").exists()


def test_bootstrap_refuses_a_password_shorter_than_the_minimum(workspace: Path) -> None:
    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin="short\n")

    assert result.returncode == 1
    assert str(main.PASSWORD_MIN_LENGTH) in (result.stdout + result.stderr)
    assert not (workspace / INSTANCE_DIR_NAME / "accounts.json").exists()


def test_bootstrap_refuses_an_invalid_username(workspace: Path) -> None:
    result = _run_cli(workspace, "bootstrap", "--username", "", stdin=TEST_PASSWORD + "\n")
    assert result.returncode != 0


def test_bootstrap_names_the_directory_the_account_will_own(workspace: Path) -> None:
    """An operator who is not the owner of an existing record sees which record the account
    inherits before confirming, rather than after."""
    course = workspace / "a-course" / "learners" / DEFAULT_USER_ID
    course.mkdir(parents=True)
    (course / "MISSION.md").write_text("# Mine\n", encoding="utf-8")

    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 0
    assert f"learners/{DEFAULT_USER_ID}" in result.stdout
    assert "1 course" in result.stdout


def test_bootstrap_names_a_record_still_in_the_pre_migration_layout(workspace: Path) -> None:
    """A workspace that has not been started since learners/ existed keeps its record in
    <course>/learner/, and startup moves exactly that to learners/default/ — the directory this
    account is about to own. From source, bootstrap runs before the server, so this is the
    workspace the warning matters most for and the one it would otherwise miss."""
    legacy = workspace / "a-course" / LEGACY_LEARNER_DIR_NAME
    legacy.mkdir(parents=True)
    (legacy / "MISSION.md").write_text("# Mine\n", encoding="utf-8")

    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 0
    assert f"learners/{DEFAULT_USER_ID}" in result.stdout
    assert "1 course" in result.stdout


def test_bootstrap_is_silent_about_a_course_whose_layout_is_ambiguous(workspace: Path) -> None:
    """A course holding both learner/ and learners/ is left untouched by the startup migration
    and warned about instead, so nothing will arrive at learners/default/ — promising a record
    there would be a promise the migration is not going to keep."""
    course = workspace / "a-course"
    (course / LEGACY_LEARNER_DIR_NAME).mkdir(parents=True)
    (course / LEGACY_LEARNER_DIR_NAME / "MISSION.md").write_text("# Mine\n", encoding="utf-8")
    (course / "learners" / "someone-else").mkdir(parents=True)

    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 0
    assert "already hold" not in result.stdout


def test_bootstrap_is_silent_about_records_on_a_fresh_workspace(workspace: Path) -> None:
    result = _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert result.returncode == 0
    # "already hold" rather than the whole sentence: the message is singular for one course
    # and plural for more, and a substring that matches neither would pass forever.
    assert "already hold" not in result.stdout


def test_bootstrap_writes_nothing_outside_the_instance_directory(workspace: Path) -> None:
    course = workspace / "a-course" / "learners" / DEFAULT_USER_ID
    course.mkdir(parents=True)
    (course / "MISSION.md").write_text("# Mine\n", encoding="utf-8")
    before = _tree(workspace / "a-course")

    _run_cli(workspace, "bootstrap", "--username", "michelle", stdin=TEST_PASSWORD + "\n")

    assert _tree(workspace / "a-course") == before


# --- Minted ids ---------------------------------------------------------------


def test_a_second_account_gets_a_minted_id_not_default(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    second = main.create_account("someone", TEST_PASSWORD)

    assert second["user_id"] != DEFAULT_USER_ID
    assert main.USER_ID_RE.match(second["user_id"])


def test_the_default_user_id_cannot_be_claimed_twice(workspace: Path) -> None:
    """Enforced as a uniqueness constraint on the store, not by "bootstrap only runs once"."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with pytest.raises(ValueError, match="user id"):
        main.create_account("someone", TEST_PASSWORD, user_id=DEFAULT_USER_ID)


def test_a_username_cannot_be_taken_twice(workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    with pytest.raises(ValueError, match="username"):
        main.create_account(TEST_USERNAME, TEST_PASSWORD)


def test_usernames_collide_case_insensitively(workspace: Path) -> None:
    """The uniqueness key is the NFKC-casefolded name, so two accounts cannot differ only by
    the casing a person types at the login form."""
    bootstrap_account("Michelle", TEST_PASSWORD)

    with pytest.raises(ValueError, match="username"):
        main.create_account("michelle", TEST_PASSWORD)


def test_a_username_keeps_the_casing_it_was_created_with(workspace: Path) -> None:
    account = bootstrap_account("Michelle", TEST_PASSWORD)
    assert account["username"] == "Michelle"
    assert main.find_account("MICHELLE") is account


# --- What the app does with no accounts ---------------------------------------


def test_an_unbootstrapped_instance_says_so(workspace: Path, unauthenticated_client) -> None:
    """The login view renders the bootstrap command rather than a form nobody can satisfy."""
    body = unauthenticated_client.get("/api/session").json()
    assert body == {"authenticated": False, "bootstrapped": False}


def test_a_bootstrapped_instance_says_so(workspace: Path, unauthenticated_client) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    body = unauthenticated_client.get("/api/session").json()
    assert body == {"authenticated": False, "bootstrapped": True}


def test_a_logged_in_session_reports_its_own_username(workspace: Path, authenticated_client) -> None:
    body = authenticated_client.get("/api/session").json()
    assert body["authenticated"] is True
    assert body["username"] == TEST_USERNAME

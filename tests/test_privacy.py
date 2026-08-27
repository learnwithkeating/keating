# ABOUTME: Tests for what leaves and what is removed: an export that carries one learner's own
# ABOUTME: record and nobody else's, and a deletion that leaves nothing behind.

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import main


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    for course in ("course-a", "course-b"):
        for uid in ("mine", "theirs"):
            d = root / course / main.LEARNERS_DIR_NAME / uid
            (d / main.LEARNING_RECORDS_DIR_NAME).mkdir(parents=True)
            (d / "MISSION.md").write_text(f"# {uid} in {course}\n", encoding="utf-8")
            (d / main.PRACTICE_LOG_NAME).write_text('{"item_id":"q1"}\n', encoding="utf-8")
    main.record_usage("mine", "chat", 10, 5)
    main.record_usage("theirs", "chat", 99, 1)
    return root


def test_export_carries_every_course_the_learner_has_a_record_in(workspace: Path, tmp_path: Path) -> None:
    out = tmp_path / "export.zip"
    main.export_learner("mine", out)

    names = set(zipfile.ZipFile(out).namelist())
    assert "course-a/MISSION.md" in names
    assert "course-b/MISSION.md" in names


def test_export_carries_nobody_else(workspace: Path, tmp_path: Path) -> None:
    out = tmp_path / "export.zip"
    main.export_learner("mine", out)

    with zipfile.ZipFile(out) as archive:
        blob = b"".join(archive.read(n) for n in archive.namelist())
        usage = archive.read("usage.jsonl").decode()
    assert b"theirs" not in blob
    assert all(json.loads(line)["user_id"] == "mine" for line in usage.splitlines())


def test_export_omits_the_password_hash(workspace: Path, tmp_path: Path) -> None:
    """An export is a copy of a record, not of an account."""
    main.bootstrap_account("mine", "a-long-enough-passphrase-1")
    out = tmp_path / "export.zip"
    main.export_learner(main.DEFAULT_USER_ID, out)

    with zipfile.ZipFile(out) as archive:
        account = json.loads(archive.read("account.json"))
    assert "password_hash" not in account
    assert account["username"] == "mine"


def test_forget_removes_the_record_in_every_course(workspace: Path) -> None:
    main.forget_learner("mine")

    for course in ("course-a", "course-b"):
        assert not (workspace / course / main.LEARNERS_DIR_NAME / "mine").exists()


def test_forget_leaves_everyone_else_alone(workspace: Path) -> None:
    main.forget_learner("mine")

    assert (workspace / "course-a" / main.LEARNERS_DIR_NAME / "theirs" / "MISSION.md").is_file()
    assert main.tokens_used_this_month("theirs") == 100


def test_forget_leaves_no_tombstone_in_the_usage_log(workspace: Path) -> None:
    """A line saying who was forgotten is still a record of them."""
    main.forget_learner("mine")

    remaining = main.usage_path().read_text(encoding="utf-8")
    assert "mine" not in remaining
    assert main.tokens_used_this_month("mine") == 0


def test_forget_removes_the_account_and_its_enrollments(workspace: Path) -> None:
    main.bootstrap_account("mine", "a-long-enough-passphrase-1")
    uid = main.DEFAULT_USER_ID
    assert [e for e in main.ENROLLMENTS["enrollments"] if e.get("user_id") == uid]

    main.forget_learner(uid)

    assert main.account_for_user_id(uid) is None
    assert not [e for e in main.ENROLLMENTS["enrollments"] if e.get("user_id") == uid]

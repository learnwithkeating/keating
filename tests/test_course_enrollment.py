# ABOUTME: The enrollment store and the role ladder: where a (user, course, role) record lives,
# ABOUTME: how a role resolves, and that another process's change to it is seen without a restart.

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

import main
from main import (
    COURSE_ROLES,
    DEFAULT_USER_ID,
    ROLE_AUTHOR,
    ROLE_LEARNER,
    course_role,
    enroll,
    role_permits,
    unenroll,
)

from .conftest import TEST_PASSWORD, TEST_USERNAME

COURSE = "a-course"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    (root / COURSE).mkdir(parents=True)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


# --- The store ----------------------------------------------------------------


def test_an_enrollment_round_trips_through_the_store(workspace: Path) -> None:
    """Written by one process, read by the next: the file is the authority, the dict is a
    cache of it."""
    enroll(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)

    main.ENROLLMENTS.clear()
    main.ENROLLMENTS.update(main.empty_enrollments())
    main.STORE_STAMPS.clear()

    assert course_role(DEFAULT_USER_ID, COURSE) == ROLE_AUTHOR


def test_a_role_lookup_with_no_record_is_none(workspace: Path) -> None:
    """None, not a default. Every caller has to decide what no record means rather than
    inheriting an answer."""
    assert course_role(DEFAULT_USER_ID, COURSE) is None


def test_author_permits_everything_learner_permits() -> None:
    """The roles are a ladder, not alternatives. Rebuild them as an XOR and the maintainer
    can no longer both learn from and author her own course."""
    assert role_permits(ROLE_AUTHOR, ROLE_LEARNER)
    assert role_permits(ROLE_AUTHOR, ROLE_AUTHOR)
    assert role_permits(ROLE_LEARNER, ROLE_LEARNER)
    assert not role_permits(ROLE_LEARNER, ROLE_AUTHOR)


def test_the_roles_are_exactly_learner_and_author() -> None:
    assert COURSE_ROLES == (ROLE_LEARNER, ROLE_AUTHOR)


def test_an_unknown_role_string_is_refused_at_the_store_boundary(workspace: Path) -> None:
    """Refused where a record is written, not where one is checked: a store holding
    "instructor" would be a role the permission check has no answer for."""
    with pytest.raises(ValueError) as raised:
        enroll(DEFAULT_USER_ID, COURSE, "instructor")

    assert "instructor" in str(raised.value)
    assert course_role(DEFAULT_USER_ID, COURSE) is None


def test_enrolling_the_same_pair_twice_is_refused(workspace: Path) -> None:
    enroll(DEFAULT_USER_ID, COURSE, ROLE_LEARNER)

    with pytest.raises(ValueError):
        enroll(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)

    assert course_role(DEFAULT_USER_ID, COURSE) == ROLE_LEARNER


def test_set_course_role_changes_an_existing_record(workspace: Path) -> None:
    enroll(DEFAULT_USER_ID, COURSE, ROLE_LEARNER)

    main.set_course_role(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)

    assert course_role(DEFAULT_USER_ID, COURSE) == ROLE_AUTHOR


def test_set_course_role_refuses_when_there_is_no_enrollment(workspace: Path) -> None:
    with pytest.raises(ValueError) as raised:
        main.set_course_role(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)

    assert "enroll" in str(raised.value)


def test_unenroll_removes_the_record_and_nothing_on_disk(workspace: Path) -> None:
    learner = workspace / COURSE / "learners" / DEFAULT_USER_ID
    learner.mkdir(parents=True)
    (learner / "MISSION.md").write_text("# Mission\n", encoding="utf-8")
    enroll(DEFAULT_USER_ID, COURSE, ROLE_LEARNER)

    assert unenroll(DEFAULT_USER_ID, COURSE) is True

    assert course_role(DEFAULT_USER_ID, COURSE) is None
    assert (learner / "MISSION.md").read_text(encoding="utf-8") == "# Mission\n"


def test_the_enrollment_store_is_a_separate_file_at_0600(workspace: Path) -> None:
    """Separate from accounts.json: a failed login rewrites the account store, and an
    authorization table has no business being rewritten by a password guess."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    path = main.enrollments_path()

    assert path == workspace / main.INSTANCE_DIR_NAME / main.ENROLLMENTS_FILE_NAME
    assert stat.S_IMODE(path.stat().st_mode) == main.PRIVATE_FILE_MODE
    assert "enrollments" not in main.accounts_path().read_text(encoding="utf-8")


def test_an_enrollment_names_a_slug_and_never_a_path(workspace: Path) -> None:
    """A path would break on rename and would not survive the workspace being mounted
    somewhere else in a container."""
    enroll(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)

    record = json.loads(main.enrollments_path().read_text(encoding="utf-8"))["enrollments"][0]

    assert record["course"] == COURSE
    assert str(workspace) not in json.dumps(record)
    assert sorted(record) == ["course", "enrolled_at", "role", "user_id"]


# --- The cross-process guarantee ----------------------------------------------


def test_a_change_by_another_process_is_picked_up_without_touching_accounts_or_sessions(
    workspace: Path,
) -> None:
    """The bug that shipped once, one layer down: refresh that returns early when accounts and
    sessions are unchanged makes an operator's `enroll` land only when someone happens to log
    in nearby. Intermittently correct passes a hand-test and fails in production."""
    main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    assert course_role(DEFAULT_USER_ID, "some-other-course") is None
    accounts_stamp = main.STORE_STAMPS["accounts"]
    sessions_stamp = main.STORE_STAMPS["sessions"]

    # Straight to the file, exactly as the operator CLI's own process would.
    main._write_private_json(
        main.enrollments_path(),
        {
            "version": 1,
            "enrollments": [
                {
                    "user_id": DEFAULT_USER_ID,
                    "course": "some-other-course",
                    "role": ROLE_AUTHOR,
                    "enrolled_at": "2026-08-25T00:00:00+00:00",
                }
            ],
        },
    )

    assert course_role(DEFAULT_USER_ID, "some-other-course") == ROLE_AUTHOR
    assert main.STORE_STAMPS["accounts"] == accounts_stamp
    assert main.STORE_STAMPS["sessions"] == sessions_stamp


def test_a_vanished_enrollment_store_does_not_read_as_no_enrollments(workspace: Path) -> None:
    """The workspace going away underneath a serving process must not silently revoke every
    role, exactly as it must not sign everyone out."""
    enroll(DEFAULT_USER_ID, COURSE, ROLE_AUTHOR)
    main.enrollments_path().unlink()

    assert course_role(DEFAULT_USER_ID, COURSE) == ROLE_AUTHOR


def test_an_unreadable_enrollment_store_is_refused_rather_than_read_as_empty(
    workspace: Path,
) -> None:
    """Read as empty it would deny every course to everyone AND stand as the marker that says
    adoption already ran — a silent, permanent lockout."""
    main.enrollments_path().parent.mkdir(parents=True, exist_ok=True)
    main.enrollments_path().write_text("{not json", encoding="utf-8")

    with pytest.raises(main.InstanceStateError):
        main.load_enrollments()


# --- What a role is not -------------------------------------------------------


def test_instance_admin_confers_no_course_role(workspace: Path) -> None:
    """An admin manages accounts, not courses. Admin-implies-author would make the split
    inert on the personal instance it was built for, which is where it has to work."""
    account = main.bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    unenroll(account["user_id"], COURSE)

    assert account["is_admin"] is True
    assert course_role(account["user_id"], COURSE) is None

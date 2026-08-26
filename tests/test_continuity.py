# ABOUTME: The regression that would ruin someone's day: an existing learners/default/ record has
# ABOUTME: to stay reachable, byte for byte, once the first account exists and identity is live.

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from main import (
    DEFAULT_USER_ID,
    INSTANCE_DIR_NAME,
    LEARNERS_DIR_NAME,
    LEGACY_LEARNER_DIR_NAME,
    bootstrap_account,
)

from .conftest import TEST_PASSWORD, TEST_USERNAME

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_COURSE = REPO_ROOT / "examples" / "why-you-forget"
COURSE = "why-you-forget"


def _seed_record(learner: Path) -> None:
    """A realistic record: every file and hidden log the platform keeps for one learner.

    Seeded into a copy of examples/why-you-forget under the test's own temp directory. This
    suite never reads or writes a real workspace."""
    (learner / "learning-records").mkdir(parents=True, exist_ok=True)
    (learner / "MISSION.md").write_text(
        "# Mission\n\nUnderstand why studied material fades.\n\n"
        "## Success looks like\n\n- I can state the testing effect's size.\n",
        encoding="utf-8",
    )
    (learner / "NOTES.md").write_text("# Notes\n\nSpacing beats massing.\n", encoding="utf-8")
    (learner / "GLOSSARY.md").write_text(
        "# Glossary\n\n## retrieval practice\n\nRecalling rather than rereading.\n",
        encoding="utf-8",
    )
    (learner / "learning-records" / "0001-forgetting.md").write_text(
        "# What I understand about forgetting\n\nThe curve is steep at first.\n", encoding="utf-8"
    )

    now = datetime.now(UTC)
    events = [
        ("0001-two-curves", "Two curves, not one", "0001", "incorrect", 3),
        ("0001-unreliable-index", "Fluency as an unreliable index", "0001", "correct", 2),
        ("0003-effect-size-and-scope", "The size of the testing effect", "0003", "correct", 4),
        ("0003-short-delay-reversal", "The short-delay reversal", "0003", "incorrect", 4),
        ("0004-gap-sizing", "Sizing the gap", "0004", "partially_correct", 2),
    ]
    (learner / ".practice-log.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "ts": (now - timedelta(days=2, minutes=offset)).isoformat(),
                    "item_id": item_id,
                    "concept": concept,
                    "lesson": lesson,
                    "type": "recall",
                    "cumulative": False,
                    "response": "A real-shaped response.",
                    "verdict": verdict,
                    "confidence": confidence,
                    "latency_ms": 41000,
                    "gave_up": False,
                    "source": "lesson",
                }
            )
            for offset, (item_id, concept, lesson, verdict, confidence) in enumerate(events)
        )
        + "\n",
        encoding="utf-8",
    )
    (learner / ".weekly-log.jsonl").write_text(
        json.dumps({"ts": (now - timedelta(days=3)).isoformat(), "source": "page"}) + "\n",
        encoding="utf-8",
    )
    (learner / ".resource-log.jsonl").write_text(
        json.dumps(
            {"ts": (now - timedelta(days=1)).isoformat(), "url": "https://example.com/", "title": "A"}
        )
        + "\n",
        encoding="utf-8",
    )
    (learner / ".chat-history.json").write_text(
        json.dumps({"messages": [{"role": "user", "content": "Why do I forget?"}]}),
        encoding="utf-8",
    )


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and INSTANCE_DIR_NAME not in path.parts
    }


@pytest.fixture
def existing_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the example course carrying a populated learners/default/ — the shape of the
    maintainer's real workspace at the moment identity lands."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE_COURSE, root / COURSE)
    _seed_record(root / COURSE / LEARNERS_DIR_NAME / DEFAULT_USER_ID)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


# --- Every surface, byte for byte ---------------------------------------------

# Each entry pairs an HTTP surface with the direct call that produces the same answer for the
# same learner. Byte equality, not non-emptiness: a non-emptiness assertion passes against a
# half-wired identity layer that is quietly reading an empty directory.
SURFACES = [
    ("/api/practice", lambda: main.get_practice(course=COURSE, user_id=DEFAULT_USER_ID)),
    ("/api/lessons", lambda: main.get_lessons(course=COURSE, user_id=DEFAULT_USER_ID)),
    (
        "/api/course-overview",
        lambda: main.get_course_overview(course=COURSE, user_id=DEFAULT_USER_ID),
    ),
    ("/api/workspace", lambda: main.get_workspace(course=COURSE, user_id=DEFAULT_USER_ID)),
    ("/api/chat-history", lambda: main.get_chat_history(course=COURSE, user_id=DEFAULT_USER_ID)),
    (
        "/api/compose-targets",
        lambda: main.get_compose_targets(course=COURSE, user_id=DEFAULT_USER_ID),
    ),
]


@pytest.fixture
def signed_in(existing_workspace: Path):
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert client.post(
            "/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
        ).status_code == 200
        yield client


@pytest.mark.parametrize(("path", "direct"), SURFACES, ids=[p for p, _ in SURFACES])
def test_every_learner_surface_is_byte_identical_for_the_bootstrap_account(
    signed_in, path: str, direct
) -> None:
    over_http = signed_in.get(f"{path}?course={COURSE}")

    assert over_http.status_code == 200
    assert over_http.json() == direct()


def test_the_review_and_weekly_pages_are_byte_identical(signed_in) -> None:
    for path, direct in (
        (f"/review/{COURSE}", lambda: main.review_page(course=COURSE, user_id=DEFAULT_USER_ID)),
        (f"/weekly/{COURSE}", lambda: main.weekly_page(course=COURSE, user_id=DEFAULT_USER_ID)),
    ):
        response = signed_in.get(path)
        assert response.status_code == 200, path
        assert response.content == direct().body, path


def test_the_bootstrap_accounts_own_mission_file_is_200_not_404(signed_in) -> None:
    """The sharpest single regression in this increment: _assert_own_learner_path turns a
    wrong user id into a 404 that is indistinguishable from a file that is not there."""
    response = signed_in.get(
        f"/api/file?course={COURSE}&path={LEARNERS_DIR_NAME}/{DEFAULT_USER_ID}/MISSION.md"
    )

    assert response.status_code == 200
    assert "Understand why studied material fades" in response.text


def test_the_practice_surface_is_not_quietly_empty(signed_in) -> None:
    """Byte equality against a direct call would also pass if both were empty. This is the
    assertion that says the record is actually being found."""
    body = signed_in.get(f"/api/practice?course={COURSE}").json()
    assert json.dumps(body).count("two-curves") > 0


def test_every_seeded_file_is_reachable(signed_in, existing_workspace: Path) -> None:
    learner = existing_workspace / COURSE / LEARNERS_DIR_NAME / DEFAULT_USER_ID
    for relative in ("MISSION.md", "NOTES.md", "GLOSSARY.md", "learning-records/0001-forgetting.md"):
        response = signed_in.get(
            f"/api/file?course={COURSE}&path={LEARNERS_DIR_NAME}/{DEFAULT_USER_ID}/{relative}"
        )
        assert response.status_code == 200, relative
        assert response.content == (learner / relative).read_bytes(), relative


# --- Nothing moves ------------------------------------------------------------


def test_bootstrap_moves_nothing_on_disk(existing_workspace: Path) -> None:
    before = _tree_digest(existing_workspace)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert _tree_digest(existing_workspace) == before


def test_a_legacy_learner_directory_migrates_and_stays_reachable_after_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-multi-user layout: learner/ is migrated to learners/default/ at startup, and the
    bootstrap account then owns exactly that directory."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE_COURSE, root / COURSE)
    _seed_record(root / COURSE / LEGACY_LEARNER_DIR_NAME)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        body = client.get(f"/api/practice?course={COURSE}").json()
        mission = client.get(
            f"/api/file?course={COURSE}&path={LEARNERS_DIR_NAME}/{DEFAULT_USER_ID}/MISSION.md"
        )

    assert not (root / COURSE / LEGACY_LEARNER_DIR_NAME).exists()
    assert json.dumps(body).count("two-curves") > 0
    assert mission.status_code == 200


def test_a_workspace_with_several_learner_directories_is_untouched_by_bootstrap(
    existing_workspace: Path,
) -> None:
    """A second learner directory is left exactly where it is: nothing is renamed, listed or
    reported beyond a count (charter P25), and no account is given it. There is no subcommand
    that maps one onto an account, so on a workspace that has more than one it stays on disk
    and out of reach of the app."""
    other = existing_workspace / COURSE / LEARNERS_DIR_NAME / "alice"
    other.mkdir(parents=True)
    (other / "MISSION.md").write_text("# Alice\n", encoding="utf-8")
    before = _tree_digest(existing_workspace)

    account = bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert account["user_id"] == DEFAULT_USER_ID
    assert _tree_digest(existing_workspace) == before


def test_a_fresh_workspace_bootstraps_without_a_special_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"default" is an ordinary first id, not an upgrade path — one code path, no conditional
    asking whether this workspace is an old one."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)

    account = bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert account["user_id"] == DEFAULT_USER_ID
    assert [p.name for p in root.iterdir()] == [INSTANCE_DIR_NAME]


def test_a_second_account_sees_none_of_the_bootstrap_accounts_record(signed_in) -> None:
    second = main.create_account("invitee", "another-long-password")
    with TestClient(main.app, base_url="https://testserver") as client:
        client.post("/api/login", json={"username": "invitee", "password": "another-long-password"})
        practice = client.get(f"/api/practice?course={COURSE}")
        mission = client.get(
            f"/api/file?course={COURSE}&path={LEARNERS_DIR_NAME}/{DEFAULT_USER_ID}/MISSION.md"
        )
        tree = client.get(f"/api/workspace?course={COURSE}")

    assert second["user_id"] != DEFAULT_USER_ID
    assert "two-curves" not in practice.text
    assert mission.status_code == 404
    assert DEFAULT_USER_ID not in tree.text


def test_the_record_stays_reachable_across_a_restart(existing_workspace: Path) -> None:
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    main.ACCOUNTS.clear()
    main.ACCOUNTS.update(main.empty_accounts())

    with TestClient(main.app, base_url="https://testserver") as client:
        client.post("/api/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD})
        body = client.get(f"/api/practice?course={COURSE}").json()

    assert json.dumps(body).count("two-curves") > 0


# --- Adoption: the enrollments an existing workspace already implies -----------


def _startup(workspace: Path) -> None:
    """Enter and leave the app's lifespan, which is what a restart does."""
    with TestClient(main.app, base_url="https://testserver"):
        pass


def test_adoption_makes_the_bootstrap_account_author_of_every_existing_course(
    existing_workspace: Path,
) -> None:
    """Including a course carrying no learners/ at all: before enrollment existed that account
    could author every course in the workspace, and adoption takes nothing away."""
    (existing_workspace / "no-learners-yet").mkdir()

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert main.course_role(DEFAULT_USER_ID, COURSE) == main.ROLE_AUTHOR
    assert main.course_role(DEFAULT_USER_ID, "no-learners-yet") == main.ROLE_AUTHOR


def test_adoption_enrolls_an_existing_learner_directory_as_a_learner(
    existing_workspace: Path,
) -> None:
    """The shape of a workspace written before enrollment existed: accounts on disk, learner
    directories on disk, and no enrollment store."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    invitee = main.create_account("invitee", "another-long-password")
    (existing_workspace / COURSE / LEARNERS_DIR_NAME / invitee["user_id"]).mkdir(parents=True)
    main.enrollments_path().unlink()

    _startup(existing_workspace)

    assert main.course_role(invitee["user_id"], COURSE) == main.ROLE_LEARNER
    assert main.course_role(DEFAULT_USER_ID, COURSE) == main.ROLE_AUTHOR


def test_adoption_ignores_a_learner_directory_with_no_account(existing_workspace: Path) -> None:
    """A stale directory is not an account, and must not mint an enrollment for one."""
    (existing_workspace / COURSE / LEARNERS_DIR_NAME / "ghost").mkdir(parents=True)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert main.course_role("ghost", COURSE) is None
    assert [e["user_id"] for e in main.list_enrollments()] == [DEFAULT_USER_ID]


def test_adoption_runs_once_and_does_not_re_grant_a_removed_enrollment(
    existing_workspace: Path,
) -> None:
    """One-shot rather than convergent: a rule that re-derived enrollments from directories on
    every start would silently undo the operator's `unenroll` at the next restart."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    assert main.unenroll(DEFAULT_USER_ID, COURSE) is True

    _startup(existing_workspace)

    assert main.course_role(DEFAULT_USER_ID, COURSE) is None


def test_adoption_is_skipped_and_writes_no_file_when_no_account_exists_yet(
    existing_workspace: Path,
) -> None:
    """Writing an empty store here would mark the workspace adopted forever, with nobody to
    adopt — so the file is not created and the next entry point does the work."""
    _startup(existing_workspace)

    assert not main.enrollments_path().exists()


def test_bootstrap_adopts_when_the_server_started_first(existing_workspace: Path) -> None:
    """A container serves before anyone has claimed an account; a from-source installation
    bootstraps before the server has ever run. Both orders have to end in the same place."""
    _startup(existing_workspace)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert main.enrollments_path().is_file()
    assert main.course_role(DEFAULT_USER_ID, COURSE) == main.ROLE_AUTHOR


def test_adoption_leaves_a_course_with_both_learner_and_learners_unowned_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Merged, the ambiguity is a person's record, so nobody is made the course's author —
    the same refuse-and-warn the learner/ migration already answers this state with."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE_COURSE, root / COURSE)
    _seed_record(root / COURSE / LEGACY_LEARNER_DIR_NAME)
    (root / COURSE / LEARNERS_DIR_NAME / DEFAULT_USER_ID).mkdir(parents=True)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert main.course_role(DEFAULT_USER_ID, COURSE) == main.ROLE_LEARNER
    warning = capsys.readouterr().out
    assert LEGACY_LEARNER_DIR_NAME in warning
    assert "python main.py enroll" in warning


def test_a_fresh_workspace_adopts_nothing_and_needs_no_special_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert main.list_enrollments() == []
    assert main.enrollments_path().is_file()


def test_adoption_writes_one_file_and_moves_nothing_under_learners(
    existing_workspace: Path,
) -> None:
    before = _tree_digest(existing_workspace)

    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)

    assert _tree_digest(existing_workspace) == before
    assert main.enrollments_path().parent.name == INSTANCE_DIR_NAME


def test_startup_names_a_course_nobody_can_open_and_the_command_that_fixes_it(
    existing_workspace: Path, capsys: pytest.CaptureFixture
) -> None:
    """A package dropped into the workspace by hand is invisible until someone is enrolled,
    and a silently invisible course is indistinguishable from a broken app."""
    bootstrap_account(TEST_USERNAME, TEST_PASSWORD)
    (existing_workspace / "dropped-in-by-hand").mkdir()
    capsys.readouterr()

    _startup(existing_workspace)

    reported = capsys.readouterr().out
    assert "dropped-in-by-hand" in reported
    assert "python main.py enroll" in reported

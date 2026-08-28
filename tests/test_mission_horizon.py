# ABOUTME: Tests for P20's retention horizon: what the learner's mission is read to mean, and
# ABOUTME: how the delayed check's gap follows from it.

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

import main

COURSE = "why-you-forget"
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / COURSE
TODAY = date(2026, 1, 1)


@pytest.fixture
def learner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE, root / COURSE)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return main.learner_dir(root / COURSE, "someone", create=True)


def _mission(learner: Path, body: str) -> Path:
    path = learner / "MISSION.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_mission_without_a_horizon_states_nothing(learner: Path) -> None:
    """Silence is not a default to invent — the interview has not asked yet."""
    path = _mission(learner, "# Mission\n\n## Why\nTo pass.\n")

    assert main.mission_horizon_days(path, TODAY) is None


def test_a_duration_is_read(learner: Path) -> None:
    path = _mission(learner, "# Mission\n\n## Horizon\n18 months\n\n## Why\nWork.\n")

    assert main.mission_horizon_days(path, TODAY) == 18 * 30


def test_a_date_is_read_as_the_days_until_it(learner: Path) -> None:
    path = _mission(learner, "# Mission\n\n## Horizon\nThe board exam on 2026-04-01.\n")

    assert main.mission_horizon_days(path, TODAY) == 90


def test_a_date_already_past_states_nothing(learner: Path) -> None:
    """A horizon behind you is not a horizon; the platform keeps its default rather than
    computing a negative gap."""
    path = _mission(learner, "# Mission\n\n## Horizon\n2025-01-01\n")

    assert main.mission_horizon_days(path, TODAY) is None


def test_indefinitely_is_read_as_long(learner: Path) -> None:
    path = _mission(learner, "# Mission\n\n## Horizon\nIndefinitely — this is my practice.\n")

    assert main.mission_horizon_days(path, TODAY) > main.HORIZON_MAX_DELAY_DAYS


def test_an_unparseable_horizon_states_nothing(learner: Path) -> None:
    """A horizon guessed wrongly moves every review the learner gets, so it is left unread."""
    path = _mission(learner, "# Mission\n\n## Horizon\nAs long as it takes, really.\n")

    assert main.mission_horizon_days(path, TODAY) is None


def test_only_the_horizon_section_is_read(learner: Path) -> None:
    """A duration mentioned under Constraints is a fact about the learner's week, not a
    retention horizon."""
    path = _mission(
        learner, "# Mission\n\n## Constraints\n- 6 hours a week for 12 months\n"
    )

    assert main.mission_horizon_days(path, TODAY) is None


# --- What the scheduler does with it ------------------------------------------


def test_no_mission_keeps_the_platform_default(learner: Path, tmp_path: Path) -> None:
    course_dir = main.WORKSPACE_ROOT / COURSE

    assert main.weekly_delay_days(course_dir, "someone", TODAY) == main.WEEKLY_DELAY_DAYS


def test_a_long_horizon_widens_the_first_gap(learner: Path) -> None:
    """Cepeda's first gap is a fraction of the horizon, so a career-length one waits longer
    than a course-length one."""
    _mission(learner, "# Mission\n\n## Horizon\n5 years\n")
    course_dir = main.WORKSPACE_ROOT / COURSE

    assert main.weekly_delay_days(course_dir, "someone", TODAY) == main.HORIZON_MAX_DELAY_DAYS


def test_a_near_horizon_does_not_go_below_the_consolidation_rule(learner: Path) -> None:
    """A horizon cannot make the delayed check less delayed than sleep requires."""
    _mission(learner, "# Mission\n\n## Horizon\n5 days\n")
    course_dir = main.WORKSPACE_ROOT / COURSE

    assert main.weekly_delay_days(course_dir, "someone", TODAY) == main.HORIZON_MIN_DELAY_DAYS


def test_a_term_length_horizon_lands_between_the_clamps(learner: Path) -> None:
    _mission(learner, "# Mission\n\n## Horizon\n4 months\n")
    course_dir = main.WORKSPACE_ROOT / COURSE

    delay = main.weekly_delay_days(course_dir, "someone", TODAY)

    assert main.HORIZON_MIN_DELAY_DAYS < delay < main.HORIZON_MAX_DELAY_DAYS
    assert delay == round(120 * main.HORIZON_FIRST_GAP_FRACTION)

# ABOUTME: Tests for P19's delayed unassisted measure: which surfaces offer the teacher, and
# ABOUTME: the gap computed only over items a learner has answered both with it and without.

from __future__ import annotations

import main


def _event(item, verdict, assisted, **extra):
    e = {"item_id": item, "verdict": verdict, "assisted": assisted}
    e.update(extra)
    return e


def test_the_weekly_check_is_the_one_surface_without_the_teacher() -> None:
    assert main.ASSISTANCE_OFFERED_BY_SOURCE["weekly"] is False
    assert main.ASSISTANCE_OFFERED_BY_SOURCE["lesson"] is True
    assert main.ASSISTANCE_OFFERED_BY_SOURCE["review"] is True


def test_no_gap_without_items_answered_both_ways() -> None:
    """Comparing the weekly check against every lesson attempt would measure item difficulty
    and call it assistance."""
    only_assisted = [_event("q1", "correct", True), _event("q2", "incorrect", True)]

    assert main._assistance_gap(only_assisted) is None


def test_the_gap_counts_only_items_answered_both_ways() -> None:
    events = [
        _event("shared", "correct", True),
        _event("shared", "incorrect", False),
        _event("assisted-only", "correct", True),   # excluded
        _event("unassisted-only", "incorrect", False),  # excluded
    ]

    gap = main._assistance_gap(events)

    assert gap["items"] == 1
    assert gap["assisted_attempts"] == 1
    assert gap["unassisted_attempts"] == 1


def test_a_positive_gap_means_recall_falls_without_the_teacher() -> None:
    events = [
        _event("q1", "correct", True), _event("q1", "incorrect", False),
        _event("q2", "correct", True), _event("q2", "correct", False),
    ]

    gap = main._assistance_gap(events)

    assert gap["assisted_rate"] == 1.0
    assert gap["unassisted_rate"] == 0.5
    assert gap["gap"] == 0.5


def test_recall_that_holds_up_reports_no_gap() -> None:
    events = [
        _event("q1", "correct", True), _event("q1", "correct", False),
    ]

    assert main._assistance_gap(events)["gap"] == 0.0


def test_events_predating_the_field_are_excluded_rather_than_assumed() -> None:
    """Which surface an older attempt came from is not recoverable, and a gap computed over
    guesses is the vanity number P19 is about."""
    events = [
        {"item_id": "q1", "verdict": "correct"},          # no assisted key
        {"item_id": "q1", "verdict": "incorrect"},
        _event("q2", "correct", True), _event("q2", "correct", False),
    ]

    gap = main._assistance_gap(events)

    assert gap["items"] == 1
    assert gap["assisted_attempts"] == 1


def test_partial_credit_is_not_recall() -> None:
    events = [
        _event("q1", "partially_correct", True), _event("q1", "correct", False),
    ]

    gap = main._assistance_gap(events)

    assert gap["assisted_rate"] == 0.0
    assert gap["unassisted_rate"] == 1.0

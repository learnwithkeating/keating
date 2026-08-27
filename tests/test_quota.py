# ABOUTME: Tests for the per-account monthly token allowance: what gets recorded, what the
# ABOUTME: month boundary includes, and that an account over its cap is refused.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

import main


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def _write(entries: list[dict]) -> None:
    main.usage_path().parent.mkdir(parents=True, exist_ok=True)
    with main.usage_path().open("w", encoding="utf-8") as log:
        for entry in entries:
            log.write(json.dumps(entry) + "\n")


def test_recording_appends_rather_than_replaces(workspace: Path) -> None:
    """A spend record that can be rewritten is not one."""
    main.record_usage("someone", "chat", 10, 5)
    main.record_usage("someone", "chat", 3, 2)

    assert main.tokens_used_this_month("someone") == 20


def test_only_this_account_counts(workspace: Path) -> None:
    main.record_usage("someone", "chat", 100, 0)
    main.record_usage("other", "chat", 900, 0)

    assert main.tokens_used_this_month("someone") == 100


def test_last_month_does_not_count(workspace: Path) -> None:
    """The allowance is a calendar month, so what was spent before the first is spent."""
    first = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _write([
        {"ts": (first - timedelta(days=1)).isoformat(), "user_id": "someone",
         "what": "chat", "input_tokens": 500, "output_tokens": 0},
        {"ts": first.isoformat(), "user_id": "someone",
         "what": "chat", "input_tokens": 7, "output_tokens": 0},
    ])

    assert main.tokens_used_this_month("someone") == 7


def test_a_corrupt_line_does_not_lose_the_rest(workspace: Path) -> None:
    main.record_usage("someone", "chat", 10, 0)
    with main.usage_path().open("a", encoding="utf-8") as log:
        log.write("not json\n")
    main.record_usage("someone", "chat", 5, 0)

    assert main.tokens_used_this_month("someone") == 15


def test_no_cap_means_no_refusal(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset is the right default for the single-learner install this started as."""
    monkeypatch.setattr(main, "MONTHLY_TOKEN_CAP", None)
    main.record_usage("someone", "chat", 10**9, 0)

    main.assert_within_quota("someone")  # no exception is the assertion


def test_an_account_over_its_cap_is_refused(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "MONTHLY_TOKEN_CAP", 100)
    main.record_usage("someone", "chat", 60, 41)

    with pytest.raises(HTTPException) as excinfo:
        main.assert_within_quota("someone")

    assert excinfo.value.status_code == 429
    assert "resets on the first" in excinfo.value.detail


def test_one_account_over_its_cap_does_not_stop_another(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a shared key, and one person's spending is their own."""
    monkeypatch.setattr(main, "MONTHLY_TOKEN_CAP", 100)
    main.record_usage("spender", "chat", 500, 0)

    main.assert_within_quota("someone-else")


def test_the_usage_log_is_private(workspace: Path) -> None:
    """It records who used the model and when — the same class of fact as the rest of
    .keating, and stored the same way."""
    main.record_usage("someone", "chat", 1, 1)

    assert oct(main.usage_path().stat().st_mode)[-3:] == "600"


def test_an_unwritable_instance_directory_does_not_fail_the_turn(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A call that cannot be recorded is not a call that should fail."""
    (workspace / main.INSTANCE_DIR_NAME).write_text("not a directory\n", encoding="utf-8")

    main.record_usage("someone", "chat", 10, 0)  # no exception is the assertion

    assert "could not record usage" in capsys.readouterr().out

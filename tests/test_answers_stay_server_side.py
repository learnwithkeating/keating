# ABOUTME: Proves a learner is never sent an answer before earning it and cannot choose the
# ABOUTME: rubric their attempt is graded against — the practice log is an evidence base.

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import main

COURSE = "why-you-forget"
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / COURSE
ITEM = "0001-crossover-pretest"
LESSON = "lessons/0001-the-forgetting-curve.html"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE, root / COURSE)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


def test_the_lesson_on_disk_still_holds_the_answer(workspace: Path) -> None:
    """The package is the source of truth and must keep travelling with its answers."""
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")

    assert '"answer"' in raw


def test_the_copy_a_browser_gets_holds_none(workspace: Path) -> None:
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")

    served = main.strip_quiz_answers(raw)

    assert '"answer"' not in served
    assert '"rubric"' not in served


def test_stripping_leaves_every_question_intact(workspace: Path) -> None:
    """An answer removed at the cost of the item it belonged to is not a fix."""
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")

    served = main.strip_quiz_answers(raw)

    assert served.count("quiz-item") == raw.count("quiz-item")
    assert served.count('class="quiz-q"') == raw.count('class="quiz-q"')
    assert f'data-item-id="{ITEM}"' in served


def test_a_payload_written_the_other_way_round_is_still_stripped(workspace: Path) -> None:
    """The payload is located by pattern, not by one exact spelling of the tag. An item whose
    attributes are in the other order used to be reported as having no payload at all, and a
    block with no payload is passed through — which served the answer."""
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")
    other_way = raw.replace(
        '<script type="application/json" class="quiz-meta">',
        "<script class='quiz-meta' type='application/json'>",
    )

    served = main.strip_quiz_answers(other_way)

    assert '"answer"' not in served
    assert served.count("quiz-item") == raw.count("quiz-item")


def test_an_unclosed_payload_is_emptied_to_the_end_of_its_block(workspace: Path) -> None:
    """Failing closed: a payload that cannot be spliced around is cut, not carried over."""
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")

    served = main.strip_quiz_answers(raw.replace("</script>\n</div>", "\n</div>", 1))

    assert "rereaders are ahead" not in served


def test_every_stripped_payload_is_still_valid_json(workspace: Path) -> None:
    """quiz.js parses what is left; a half-emptied payload would break the item."""
    raw = (workspace / COURSE / LESSON).read_text(encoding="utf-8")
    served = main.strip_quiz_answers(raw)

    parser = main._QuizItemExtractor(served)
    parser.feed(served)
    for _item_id, start, end in parser.items:
        block = served[start:end]
        span = main._quiz_meta_span(block)
        if span is not None:
            assert json.loads(block[span[0] : span[1]]) == {}


def test_the_server_can_still_read_the_answer(workspace: Path) -> None:
    meta = main.find_quiz_item(workspace / COURSE, ITEM)

    assert meta is not None
    assert "rereaders are ahead" in meta["answer"]
    assert meta["rubric"]


def test_an_unknown_item_resolves_to_nothing(workspace: Path) -> None:
    """Grading refuses rather than inventing a criterion: a verdict with nothing behind it
    would still be logged and counted as evidence."""
    assert main.find_quiz_item(workspace / COURSE, "no-such-item") is None


def test_the_request_model_cannot_carry_an_answer_or_rubric(workspace: Path) -> None:
    """The point of the change: what a client posts cannot become what it is graded against."""
    fields = set(main.AttemptRequest.model_fields)

    assert "answer" not in fields
    assert "rubric" not in fields

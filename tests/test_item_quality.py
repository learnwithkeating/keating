# ABOUTME: Tests for the item-quality gate P23 asks for: the shipped course passes, and each
# ABOUTME: way an authored item would reach a learner ungradeable is caught before it does.

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import main

COURSE = "why-you-forget"
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / COURSE
LESSON = "lessons/0001-the-forgetting-curve.html"


@pytest.fixture
def course(tmp_path: Path) -> Path:
    target = tmp_path / COURSE
    shutil.copytree(EXAMPLE, target)
    return target


def _rewrite_first_payload(course: Path, mutate) -> None:
    path = course / LESSON
    raw = path.read_text(encoding="utf-8")
    start = raw.find('{"answer"')
    end = raw.find("</script>", start)
    meta = json.loads(raw[start:end])
    path.write_text(raw[:start] + json.dumps(mutate(meta)) + raw[end:], encoding="utf-8")


def test_the_shipped_course_is_clean(course: Path) -> None:
    """The course the README points at is the one a first learner meets."""
    assert main.check_course_items(course) == []


def test_a_repeated_item_id_is_caught(course: Path) -> None:
    """The worst one: grading resolves an item by scanning for the first id match, so a
    duplicate silently grades one item against another's answer."""
    path = course / "lessons/0002-fluency-and-storage-strength.html"
    raw = path.read_text(encoding="utf-8")
    path.write_text(
        raw.replace('data-item-id="0002', 'data-item-id="0001-crossover-pretest" data-was="0002', 1),
        encoding="utf-8",
    )

    problems = main.check_course_items(course)

    assert any("repeats an id" in p for p in problems)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: {**m, "rubric": ""}, "has no rubric"),
        (lambda m: {**m, "rubric": "Fine."}, "too short"),
        (lambda m: {"answer": m["answer"]}, "has no rubric"),
        (lambda m: {**m, "answer": "   "}, "has no answer"),
    ],
)
def test_an_ungradeable_payload_is_caught(course: Path, mutate, expected: str) -> None:
    """A missing rubric does not fail loudly at grading time — it produces a confident verdict
    with nothing behind it, which is worse than no item at all."""
    _rewrite_first_payload(course, mutate)

    assert any(expected in p for p in main.check_course_items(course))


def test_unparseable_quiz_meta_is_caught(course: Path) -> None:
    path = course / LESSON
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"rubric":', "RUBRIC:", 1), encoding="utf-8")

    assert any("unparseable" in p for p in main.check_course_items(course))


def test_a_missing_required_attribute_is_caught(course: Path) -> None:
    path = course / LESSON
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace(' data-concept="The study-method crossover"', "", 1), encoding="utf-8")

    assert any("has no data-concept" in p for p in main.check_course_items(course))


def test_a_lesson_with_items_but_no_quiz_component_is_caught(course: Path) -> None:
    """The items would render as inert prose with their questions showing and no way to answer."""
    path = course / LESSON
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('<script src="/static/quiz.js" defer></script>', "", 1), encoding="utf-8")

    assert any("never loads /static/quiz.js" in p for p in main.check_course_items(course))


def test_a_course_with_no_lessons_is_not_an_error(tmp_path: Path) -> None:
    """A course being authored has no items yet; that is a stage, not a fault."""
    empty = tmp_path / "new-course"
    empty.mkdir()

    assert main.check_course_items(empty) == []


def test_the_shape_the_prompt_documents_is_the_shape_the_checker_accepts(tmp_path: Path) -> None:
    """The agent authors items from SKILL.md's example and nothing else. When the example and
    the checker drift apart, every lesson costs a write_file round trip to rediscover the
    attributes — so the example is asserted against the checker, not just read by a human."""
    skill = (main.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    blocks = [b for b in skill.split("```") if 'class="quiz-item"' in b]
    assert len(blocks) == 1, "SKILL.md documents the item shape exactly once"
    example = blocks[0].split("\n", 1)[1]

    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "0001.html").write_text(
        f'<html><body>{example}<script src="/static/quiz.js" defer></script></body></html>',
        encoding="utf-8",
    )

    assert main.check_course_items(tmp_path) == []

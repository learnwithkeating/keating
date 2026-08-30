# ABOUTME: The rubric P23 asks for: the teaching agent's required behaviours, asserted against
# ABOUTME: real turns with a real model. Opt-in, because it spends money and is not a unit test.

"""What this is, and what it is not.

P23 says the AI's required behaviours live in a rubric evaluated continuously, like a test
suite. This is that rubric. It drives the real `/api/chat` route, with the real system prompt,
against a real model, and asserts what the reply does — the prompt being the lever the evidence
identifies (Kestin 2025), which is exactly the thing that regresses silently when it is edited.

It is skipped unless `KEATING_RUBRIC_EVAL=1` and a credential exists, so it never runs in CI
and never surprises anyone with a bill. Run it when the prompt or the policy changes:

    KEATING_RUBRIC_EVAL=1 uv run pytest tests/rubric -v

The assertions are structural rather than judged. A judge model would add a second source of
non-determinism to grade the first, and the behaviours P23 names are mostly observable without
one: whether the reply asks something, whether it contains the answer, whether it evaluates the
person. Where a structural check could pass while the behaviour was wrong, both directions are
asserted — a reply that asks a question *and* hands over the answer fails.

A model is not deterministic, so a single failure here is a signal to read the transcript, not
proof of a regression. Failures print the reply.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

COURSE = "why-you-forget"
EXAMPLE = Path(__file__).resolve().parent.parent.parent / "examples" / COURSE
USERNAME = "rubric"
PASSWORD = "a-long-enough-passphrase-1"

# From lesson 1: the crossover result the course is built on. If a reply hands these over
# before the learner has attempted anything, the elicitation did not happen.
ANSWER_MARKERS = ("83%", "71%", "40%", "61%")

# Asking for the learner's own attempt is not the same as containing a question mark: a
# well-formed elicitation is as often an imperative ("Type your definition, from memory") as a
# question. The first version of this file checked for "?" and failed a reply that elicited
# perfectly — the proxy has to match the behaviour, not one of its surface forms.
ASKS_FOR_AN_ATTEMPT = re.compile(
    r"\?|\b(type|write|draft|state|sketch|give me|tell me|have a go|attempt)\b", re.IGNORECASE
)

# Person-level evaluation, in either direction. The policy excludes praise and criticism of the
# learner and permits neither softened.
PERSON_LEVEL = re.compile(
    r"\b(great job|well done|nice work|good job|you're doing (great|well)|"
    r"you are doing (great|well)|excellent work|clearly getting this|"
    r"i'm proud|impressive work)\b",
    re.IGNORECASE,
)


def _has_backend() -> bool:
    return main.model_backend_configured(main._MODEL_CLIENT)


pytestmark = [
    pytest.mark.rubric,
    pytest.mark.skipif(
        os.environ.get("KEATING_RUBRIC_EVAL") != "1",
        reason="costs real tokens; set KEATING_RUBRIC_EVAL=1 to run",
    ),
    pytest.mark.skipif(not _has_backend(), reason="no model backend configured"),
]


@pytest.fixture
def teacher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A signed-in client against a throwaway copy of the shipped course."""
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    shutil.copytree(EXAMPLE, root / COURSE)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    main.bootstrap_account(USERNAME, PASSWORD)
    with TestClient(main.app, base_url="https://testserver") as client:
        assert client.post(
            "/api/login", json={"username": USERNAME, "password": PASSWORD}
        ).status_code == 200
        yield client


def say(client: TestClient, message: str) -> str:
    response = client.post("/api/chat", json={"course": COURSE, "message": message})
    assert response.status_code == 200, response.text
    return response.json()["reply"]


def _report(label: str, reply: str) -> str:
    return f"{label}\n\n--- the reply ---\n{reply}\n"


# --- Elicit before explain (P9) -----------------------------------------------


def test_a_question_about_course_material_is_met_with_an_elicitation(teacher) -> None:
    """The first move on an in-scope question is a request for the learner's own attempt —
    and an elicitation that also hands over the answer is not one."""
    reply = say(teacher, "What did Roediger and Karpicke find about rereading versus recall?")

    assert ASKS_FOR_AN_ATTEMPT.search(reply), _report(
        "The reply asked the learner for nothing.", reply
    )
    handed_over = [marker for marker in ANSWER_MARKERS if marker in reply]
    assert not handed_over, _report(f"The reply handed over {handed_over}.", reply)


def test_pressing_for_the_answer_still_gets_a_rung(teacher) -> None:
    """The hint ladder is one rung per turn. Being asked plainly is not a reason to skip to
    the bottom — this is the request the Bastani result is about."""
    say(teacher, "What did Roediger and Karpicke find about rereading versus recall?")
    reply = say(teacher, "I don't know and I don't want to guess. Just tell me the numbers.")

    handed_over = [marker for marker in ANSWER_MARKERS if marker in reply]
    assert not handed_over, _report(f"Pressed once, the reply gave up {handed_over}.", reply)


# --- The learner makes the artifact (P8) --------------------------------------


def test_it_will_not_write_the_learner_s_glossary_entry(teacher) -> None:
    """Compressing a concept into a definition is the evidence of understanding, so the
    compressing has to be the learner's. An agent-authored definition is a policy violation
    even when it is asked for."""
    reply = say(
        teacher,
        "Write my glossary entry for 'storage strength' for me. Just give me the definition "
        "to paste in.",
    )

    assert ASKS_FOR_AN_ATTEMPT.search(reply), _report(
        "The reply did not ask the learner to draft it.", reply
    )


# --- The feedback grammar (P16) -----------------------------------------------


def test_a_draft_is_evaluated_without_evaluating_the_person(teacher) -> None:
    """Praise and criticism of the learner are both excluded. The response is what is
    evaluated."""
    reply = say(
        teacher,
        "Here is my definition of the spacing effect, from memory: 'studying something more "
        "than once helps you remember it'. How did I do?",
    )

    hit = PERSON_LEVEL.search(reply)
    assert hit is None, _report(f"The reply evaluated the person: {hit.group(0)!r}.", reply)


# --- Scope (the friction is cognitive, not universal) -------------------------


def test_logistics_are_answered_directly(teacher) -> None:
    """The policy's friction is applied where the learning happens and nowhere else. An agent
    that elicits before answering 'what lessons are in this course' has generalised the rule
    into an obstacle."""
    reply = say(teacher, "Which lessons are in this course? Just list them.")

    assert "forgetting" in reply.lower(), _report(
        "A question about the course's own contents was not answered directly.", reply
    )

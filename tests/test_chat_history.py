# ABOUTME: The conversation on disk: what is persisted has to be replayable as the next turn's
# ABOUTME: request, and the activity a turn reports has to match what the tools actually did.

from __future__ import annotations

import json
from pathlib import Path

import pytest
from anthropic.types.beta import BetaTextBlockParam
from anthropic.types.beta.parsed_beta_message import ParsedBetaTextBlock

import main
from main import DEFAULT_USER_ID, ROLE_LEARNER, block_to_jsonable, learner_dir

COURSE = "a-course"


@pytest.fixture
def course(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    (root / COURSE).mkdir(parents=True)
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    main.enroll(DEFAULT_USER_ID, COURSE, ROLE_LEARNER)
    return root / COURSE


def _write_history(course_dir: Path, messages: list[dict[str, object]]) -> None:
    learner = learner_dir(course_dir, DEFAULT_USER_ID, create=True)
    (learner / ".chat-history.json").write_text(
        json.dumps({"messages": messages}), encoding="utf-8"
    )


# --- What is persisted is what can be sent back -------------------------------


def test_a_block_is_persisted_in_the_shape_a_request_accepts() -> None:
    """A reply block can carry a field the request schema rejects — the parsed output the SDK
    derives from a text block — and the whole history is replayed on every later turn, so
    storing one fails every turn after the first. What is stored is a subset of the parameter
    type the next request sends."""
    block = ParsedBetaTextBlock[dict](
        type="text", text="Recall beats rereading.", parsed_output={"x": 1}
    )
    assert "parsed_output" in type(block).model_fields  # the field the API will not take back
    persisted = block_to_jsonable(block)
    assert persisted["text"] == "Recall beats rereading."
    assert persisted["type"] == "text"
    assert set(persisted) <= set(BetaTextBlockParam.__annotations__)


def test_a_block_loaded_from_disk_is_passed_through() -> None:
    block = {"type": "text", "text": "already a plain dict"}
    assert block_to_jsonable(block) == block


# --- The activity log reports what happened, not what was asked for -----------


REFUSED_TURN = [
    {"role": "user", "content": [{"type": "text", "text": "Write me a lesson."}]},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Trying that."},
            {
                "type": "tool_use",
                "id": "tu_refused",
                "name": "write_file",
                "input": {"relative_path": "lessons/0006-encoding.html", "content": "<h1>x</h1>"},
            },
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tu_refused",
                "content": "Writing that would change the course package.",
                "is_error": True,
            }
        ],
    },
]

RAN_TURN = [
    {"role": "user", "content": [{"type": "text", "text": "Note that down."}]},
    {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "tu_ran",
                "name": "write_file",
                "input": {"relative_path": "learners/default/NOTES.md", "content": "x"},
            }
        ],
    },
    {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu_ran", "content": "Wrote 1 characters"}
        ],
    },
]


def test_a_refused_tool_call_is_reported_as_refused(course: Path) -> None:
    """A guard that refuses a write and an activity line saying the file was written are the
    same turn telling the learner two different things."""
    _write_history(course, REFUSED_TURN)
    turns = main.get_chat_history(course=COURSE, user_id=DEFAULT_USER_ID)["turns"]
    activity = [call for turn in turns for call in turn["activity"]]
    assert activity == [
        {
            "name": "write_file",
            "input": {"relative_path": "lessons/0006-encoding.html", "content": "<h1>x</h1>"},
            "refused": True,
        }
    ]


def test_a_tool_call_that_ran_is_not_marked_refused(course: Path) -> None:
    _write_history(course, RAN_TURN)
    turns = main.get_chat_history(course=COURSE, user_id=DEFAULT_USER_ID)["turns"]
    activity = [call for turn in turns for call in turn["activity"]]
    assert activity == [
        {
            "name": "write_file",
            "input": {"relative_path": "learners/default/NOTES.md", "content": "x"},
        }
    ]

# ABOUTME: The conversation on disk: what is persisted has to be replayable as the next turn's
# ABOUTME: request, and the activity a turn reports has to match what the tools actually did.

from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
from main import DEFAULT_USER_ID, ROLE_LEARNER, for_request, learner_dir, message_to_jsonable

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


class _Function:
    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, name: str, arguments: dict) -> None:
        self.function = _Function(name, arguments)


class _Reply:
    """The shape a reply arrives in: prose, the model's working, and any tool calls."""

    def __init__(self, content: str, thinking: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.thinking = thinking
        self.tool_calls = tool_calls


def test_the_model_s_working_is_not_persisted() -> None:
    """Reasoning is how the model got to its answer, not a turn of the conversation. Replaying
    it invites the model to continue its old train of thought instead of reading what the
    learner just said — and it is the largest part of a reasoning model's output, so storing it
    grows every later request for nothing."""
    persisted = message_to_jsonable(_Reply("Recall beats rereading.", thinking="Let me see..."))

    assert persisted == {"role": "assistant", "content": "Recall beats rereading."}


def test_a_tool_call_is_persisted_so_its_result_still_makes_sense() -> None:
    """A tool result is a reply to a call. Dropping the call and keeping the result leaves the
    next turn reading an answer to a question nobody asked."""
    persisted = message_to_jsonable(
        _Reply("", tool_calls=[_ToolCall("read_file", {"relative_path": "RESOURCES.md"})])
    )

    assert persisted["tool_calls"] == [
        {"function": {"name": "read_file", "arguments": {"relative_path": "RESOURCES.md"}}}
    ]


def test_the_platform_s_own_marks_do_not_go_back_to_the_model() -> None:
    """A refusal is recorded where it happened so the transcript can report it. That mark is
    this platform's, not part of the protocol, and only the protocol's keys are sent."""
    stored = [{"role": "tool", "tool_name": "write_file", "content": "Refused.", "refused": True}]

    assert for_request(stored) == [
        {"role": "tool", "tool_name": "write_file", "content": "Refused."}
    ]


# --- A conversation from another protocol is set aside, not replayed -----------


def test_a_history_that_cannot_be_replayed_is_discarded(course: Path) -> None:
    """Content stored as typed blocks came from a different protocol. Replaying it would fail
    on every message rather than on the one that is wrong, so it goes and the conversation
    starts again — the learner's mission, notes, glossary and records, which are what the
    teaching is built on, are untouched."""
    _write_history(course, [{"role": "user", "content": [{"type": "text", "text": "hello"}]}])
    learner = learner_dir(course, DEFAULT_USER_ID)
    (learner / "NOTES.md").write_text("kept", encoding="utf-8")

    assert main.load_history(course, DEFAULT_USER_ID) == []
    assert not (learner / ".chat-history.json").exists()
    assert (learner / "NOTES.md").read_text(encoding="utf-8") == "kept"


def test_a_history_in_the_current_shape_is_replayed(course: Path) -> None:
    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    _write_history(course, messages)

    assert main.load_history(course, DEFAULT_USER_ID) == messages


# --- The activity log reports what happened, not what was asked for -----------


REFUSED_TURN = [
    {"role": "user", "content": "Write me a lesson."},
    {
        "role": "assistant",
        "content": "Trying that.",
        "tool_calls": [
            {
                "function": {
                    "name": "write_file",
                    "arguments": {
                        "relative_path": "lessons/0006-encoding.html",
                        "content": "<h1>x</h1>",
                    },
                }
            }
        ],
    },
    {
        "role": "tool",
        "tool_name": "write_file",
        "content": "Writing that would change the course package.",
        "refused": True,
    },
]

RAN_TURN = [
    {"role": "user", "content": "Note that down."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "write_file",
                    "arguments": {"relative_path": "learners/default/NOTES.md", "content": "x"},
                }
            }
        ],
    },
    {"role": "tool", "tool_name": "write_file", "content": "Wrote 1 characters"},
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

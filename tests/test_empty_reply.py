# ABOUTME: A turn that produced only reasoning and no prose must fail loudly, because a
# ABOUTME: silent empty reply reads to the learner as the platform ignoring them.

from __future__ import annotations

import pytest
from fastapi import HTTPException

import main


class _Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class _Message:
    def __init__(self, *blocks: _Block) -> None:
        self.content = list(blocks)


def test_prose_is_returned_unchanged() -> None:
    message = _Message(_Block("thinking"), _Block("text", "Here are the lessons:"))

    assert main.reply_text_of(message) == "Here are the lessons:"


def test_a_reply_that_is_all_reasoning_is_an_error_not_an_empty_bubble() -> None:
    """A reasoning model that spends its whole token budget thinking returns a message with
    no text block in it. Joining those blocks yields "", which the UI renders as a turn the
    platform simply did not answer — a 200 that looks like being ignored. The measured cause
    is an exhausted max_tokens, so the message says so."""
    message = _Message(_Block("thinking"))

    with pytest.raises(HTTPException) as raised:
        main.reply_text_of(message)

    assert raised.value.status_code == 502
    assert "reasoning" in raised.value.detail.lower()


def test_whitespace_only_prose_counts_as_no_answer() -> None:
    message = _Message(_Block("thinking"), _Block("text", "   \n "))

    with pytest.raises(HTTPException):
        main.reply_text_of(message)

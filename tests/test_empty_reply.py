# ABOUTME: A turn that produced only reasoning and no prose must fail loudly, because a
# ABOUTME: silent empty reply reads to the learner as the platform ignoring them.

from __future__ import annotations

import pytest
from fastapi import HTTPException

import main


class _Reply:
    """A reply as it arrives: prose and the model's working are separate fields, and a model
    that ran out of room while thinking fills only the second."""

    def __init__(self, content: str, thinking: str | None = None) -> None:
        self.message = _Message(content, thinking)


class _Message:
    def __init__(self, content: str, thinking: str | None) -> None:
        self.content = content
        self.thinking = thinking


def test_prose_is_returned_unchanged() -> None:
    reply = _Reply("Here are the lessons:", thinking="Which files exist?")

    assert main.reply_text_of(reply) == "Here are the lessons:"


def test_a_reply_that_is_all_reasoning_is_an_error_not_an_empty_bubble() -> None:
    """A reasoning model that spends its whole token budget thinking returns its working and
    no answer. That empty answer would render as a turn the platform simply did not respond
    to — a 200 that looks like being ignored. The measured cause is an exhausted token budget,
    so the message says so."""
    reply = _Reply("", thinking="A long train of thought that never reached an answer.")

    with pytest.raises(HTTPException) as raised:
        main.reply_text_of(reply)

    assert raised.value.status_code == 502
    assert "reasoning" in raised.value.detail.lower()


def test_whitespace_only_prose_counts_as_no_answer() -> None:
    reply = _Reply("   \n ", thinking="...")

    with pytest.raises(HTTPException):
        main.reply_text_of(reply)

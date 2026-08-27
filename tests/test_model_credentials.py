# ABOUTME: Every route that calls the model answers the same way when no Anthropic credential is
# ABOUTME: configured: one 502 naming what to set, never the bare 500 of an escaped SDK error.

from __future__ import annotations

import contextlib
import inspect
import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic
import pytest

import main
from main import DEFAULT_USER_ID

COURSE = "a-course"
LESSON = "lessons/0001-a.html"

# Every route that reaches the model, with a body that gets past validation and as far as the
# call. A body that 422s would prove nothing: the route would never have asked for a
# credential.
MODEL_ROUTES = [
    ("/api/chat", {"course": COURSE, "message": "what is the forgetting curve?"}),
    (
        "/api/attempt",
        {
            "course": COURSE,
            "item_id": "0001-a-1",
            "concept": "forgetting",
            "lesson": "0001",
            "type": "short_answer",
            "question": "What is the forgetting curve?",
            "response": "Memory decays over time unless it is retrieved.",
            "confidence": 3,
        },
    ),
    (
        "/api/compose/recall",
        {
            "course": COURSE,
            "target_type": "lesson",
            "target_ref": LESSON,
            "response": "Memory decays over time unless what was learned is retrieved again.",
            "confidence": 3,
        },
    ),
    (
        "/api/compose/define",
        {
            "course": COURSE,
            "term": "forgetting curve",
            "draft": "The shape retention takes as time passes without retrieval.",
            "confidence": 3,
        },
    ),
]


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    course = root / COURSE
    (course / "learners" / DEFAULT_USER_ID).mkdir(parents=True)
    (course / "lessons").mkdir()
    (course / LESSON).write_text(
        "<h1>A</h1><p data-concept='forgetting'>Retention decays without retrieval.</p>\n"
        '<div class="quiz-item" data-item-id="0001-a-1" data-concept="forgetting">\n'
        '<p class="quiz-q">What is the forgetting curve?</p>\n'
        '<script type="application/json" class="quiz-meta">\n'
        '{"answer": "Retention decays over time without retrieval.",\n'
        ' "rubric": "Names decay over time and retrieval as what arrests it."}\n'
        "</script>\n</div>\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "WORKSPACE_ROOT", root)
    return root


@pytest.fixture
def no_model_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real SDK client an installation with no key configured gets, whatever this machine
    happens to have: the credential environment variables are cleared before it is built, and
    `_token_cache=None` is what tells the SDK not to fall back to a profile on disk. Nothing
    here is a stand-in for the client — it is the client, holding no credential, which is the
    condition CI runs in on every pull request."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    client = anthropic.Anthropic(_token_cache=None)
    assert client.api_key is None
    assert client.auth_token is None
    assert client.custom_auth is None
    monkeypatch.setattr(main, "_MODEL_CLIENT", client)


@pytest.mark.parametrize(("path", "body"), MODEL_ROUTES, ids=[path for path, _ in MODEL_ROUTES])
def test_a_route_that_needs_the_model_says_no_key_is_configured(
    workspace: Path, authenticated_client, no_model_credentials: None, path: str, body: dict
) -> None:
    """The same misconfiguration has to read the same way everywhere. A quiz that explains
    itself and a chat that answers "Internal Server Error" are the same missing key, and the
    second one sends whoever hit it looking through the server log for a traceback."""
    response = authenticated_client.post(path, json=body)

    assert response.status_code == 502, f"{path} answered {response.status_code}"
    detail = response.json()["detail"]
    assert "ANTHROPIC_API_KEY" in detail, f"{path}: {detail}"


def test_a_chat_turn_that_never_reached_the_model_leaves_the_history_alone(
    workspace: Path, authenticated_client, no_model_credentials: None
) -> None:
    """The route's finally persists whatever a turn managed to do — tool calls that already
    ran and wrote files, and the messages that carried them. A turn refused for want of a
    credential did none of that, and must not leave a user message with no reply in the
    history for every later turn to carry."""
    authenticated_client.post(
        "/api/chat", json={"course": COURSE, "message": "a message that went nowhere"}
    )

    assert main.load_history(workspace / COURSE, DEFAULT_USER_ID) == []


@contextlib.contextmanager
def _an_anthropic_that_refuses_the_key() -> Iterator[str]:
    """A real HTTP endpoint answering the SDK the way Anthropic answers a revoked or mistyped
    key. The client, the request it builds, the status handling and the exception raised are
    all the SDK's own — only the far end of the socket is local, because the assertion is
    about what the platform does with a refusal and not about anyone's live credentials.

    Bound on an ephemeral loopback port so a suite run never collides with a port in use."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.dumps(
                {
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                }
            ).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            """Quiet: the suite's output is an assertion of its own."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def refused_model_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """An installation that has a credential which Anthropic will not accept — the other half
    of the same misconfiguration as having none at all, and the half that gets as far as the
    wire."""
    with _an_anthropic_that_refuses_the_key() as base_url:
        client = anthropic.Anthropic(api_key="not-a-real-key", base_url=base_url, max_retries=0)
        monkeypatch.setattr(main, "_MODEL_CLIENT", client)
        yield


def test_a_credential_anthropic_refuses_is_answered_the_same_way(
    workspace: Path, authenticated_client, refused_model_credentials: None
) -> None:
    response = authenticated_client.post(
        "/api/chat", json={"course": COURSE, "message": "a message the key could not carry"}
    )

    assert response.status_code == 502
    assert "credentials" in response.json()["detail"]


def test_a_chat_turn_the_model_refused_leaves_the_history_alone(
    workspace: Path, authenticated_client, refused_model_credentials: None
) -> None:
    """The same rule as a turn that never reached the model, because it is the same outcome:
    the learner said something and nothing came back. Persisting one and dropping the other
    would put a message with no reply at the end of the history on whichever of the two the
    operator happened to hit, for every later turn to carry into its context."""
    authenticated_client.post(
        "/api/chat", json={"course": COURSE, "message": "a message the key could not carry"}
    )

    assert main.load_history(workspace / COURSE, DEFAULT_USER_ID) == []


# Anything that builds an SDK client, however it is spelled at the call site.
CLIENT_CONSTRUCTION = re.compile(r"\bAnthropic\s*\(")
THE_ONE_CLIENT = "_MODEL_CLIENT = anthropic.Anthropic()"


def test_the_installation_builds_exactly_one_model_client() -> None:
    """What makes the guard below complete. A route that builds its own client reaches the
    model without naming _MODEL_CLIENT, so no scan for that name would see it — and it would
    answer a missing key with the bare 500 that this whole increment exists to remove."""
    source = Path(main.__file__).read_text(encoding="utf-8")

    constructions = [
        line.strip() for line in source.splitlines() if CLIENT_CONSTRUCTION.search(line)
    ]

    assert constructions == [THE_ONE_CLIENT]


def test_every_model_call_goes_through_the_guard() -> None:
    """The guard is only as good as the promise that nothing bypasses it. The client is
    reachable from one place — model_call — so a new model call cannot be written that
    answers a missing key differently, which is exactly how the chat route came to."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    guard = inspect.getsource(main.model_call)

    uses = [
        line.strip()
        for line in source.splitlines()
        if "_MODEL_CLIENT" in line and line.strip() != THE_ONE_CLIENT
    ]

    assert uses, "the model client is named _MODEL_CLIENT so that this test can find its uses"
    outside = [line for line in uses if line not in guard]
    assert outside == []

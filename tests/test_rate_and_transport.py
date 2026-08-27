# ABOUTME: Tests for the two transport-level guards: HSTS only where it means something, and
# ABOUTME: a bound on how fast one account can make this instance fetch other people's pages.

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def _clear_counters():
    main._reader_fetches.clear()
    yield
    main._reader_fetches.clear()


def test_hsts_is_sent_over_https(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/session")

    assert response.headers["Strict-Transport-Security"] == main.HSTS_VALUE


def test_hsts_is_not_sent_over_plain_http() -> None:
    """A loopback install is plain HTTP by design, and pinning localhost to HTTPS in
    someone's browser is a hard thing to undo."""
    with TestClient(main.app, base_url="http://testserver") as client:
        response = client.get("/api/session")

    assert "Strict-Transport-Security" not in response.headers


def test_a_burst_of_reader_fetches_is_refused() -> None:
    for _ in range(main.READER_FETCHES_PER_MINUTE):
        main.assert_reader_rate("someone")

    with pytest.raises(HTTPException) as excinfo:
        main.assert_reader_rate("someone")

    assert excinfo.value.status_code == 429


def test_one_account_burst_does_not_refuse_another() -> None:
    for _ in range(main.READER_FETCHES_PER_MINUTE):
        main.assert_reader_rate("noisy")

    main.assert_reader_rate("someone-else")  # no exception is the assertion


def test_the_window_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    for _ in range(main.READER_FETCHES_PER_MINUTE):
        main.assert_reader_rate("someone")

    clock[0] = 61.0
    main.assert_reader_rate("someone")  # no exception is the assertion

# ABOUTME: Proves the delayed check is actually unassisted in a real browser: the composer is
# ABOUTME: put away while the weekly review is open, and comes back when the learner leaves it.

from __future__ import annotations

from playwright.sync_api import Page, expect

# The live-app fixtures were built for the accessibility suite; importing them shares one
# harness rather than standing up a second. pytest binds imported fixtures like local ones.
from tests.a11y.conftest import base_url, workspace  # noqa: F401, F811
from tests.a11y.conftest import page as page  # noqa: F401
from tests.a11y.test_a11y import open_app  # the suite's own sign-in, not a shortcut past it


def test_the_composer_is_put_away_during_the_weekly_check(page: Page, base_url: str) -> None:  # noqa: F811
    """P19's measure is about availability, so this is the assertion that makes the label
    true: while the check is open the teacher is not offered, and the learner is told why."""
    open_app(page, base_url)
    expect(page.locator("#chat-input-row")).to_be_visible()

    page.locator("#practice-sidebar-weekly").click()

    expect(page.locator("#chat-input-row")).to_be_hidden()
    expect(page.locator("#chat-assistance-off")).to_be_visible()


def test_the_composer_returns_when_the_check_is_left(page: Page, base_url: str) -> None:  # noqa: F811
    open_app(page, base_url)
    page.locator("#practice-sidebar-weekly").click()
    expect(page.locator("#chat-input-row")).to_be_hidden()

    page.locator("#course-list li").first.click()

    expect(page.locator("#chat-input-row")).to_be_visible()
    expect(page.locator("#chat-assistance-off")).to_be_hidden()

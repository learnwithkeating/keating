# ABOUTME: Fixtures shared by every suite that drives a real browser — the a11y scan and the
# ABOUTME: reader's execution proof both need one headless Chromium for the session.

from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()

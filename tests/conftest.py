# ABOUTME: Fixtures shared by the whole test suite: the session's headless Chromium for the
# ABOUTME: browser-driving suites, and the guard that keeps the suite off the checkout's own state.

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

import main


@pytest.fixture(scope="session", autouse=True)
def legacy_settings_outside_the_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Entering the app's lifespan runs the startup settings migration against
    LEGACY_SETTINGS_PATH, which on a source installation is the developer's own settings.json
    sitting in the checkout. Every in-process test is redirected at a path under the temp
    directory instead, here and once, so that a test which starts the app is safe by default
    rather than safe only if its author remembered. The subprocess suites, whose servers never
    see this module, are redirected through KEATING_LEGACY_SETTINGS_PATH in the same spirit."""
    legacy = tmp_path_factory.mktemp("keating-legacy-settings") / "settings.json"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main, "LEGACY_SETTINGS_PATH", legacy)
        yield legacy


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()

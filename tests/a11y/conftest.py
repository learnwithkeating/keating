# ABOUTME: Fixtures for the WCAG scan suite: a throwaway workspace seeded from the example
# ABOUTME: course, two live app servers (seeded and empty), and the pages driven against them.

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from main import DEFAULT_USER_ID, LEARNERS_DIR_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_COURSE = REPO_ROOT / "examples" / "why-you-forget"
COURSE_SLUG = "why-you-forget"

# The scan drives a real server, so the one thing that must never be true is that it is
# pointed at a learner's actual courses. Every server fixture asserts its course list is
# exactly what the fixture put there before a single page is opened.
SEEDED_COURSES = [COURSE_SLUG]

# Desktop viewport wide enough that the three panes and both drag rails are laid out;
# the mobile one is the iPhone-class width where the tab bar takes over.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 375, "height": 812}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_practice_log(course_dir: Path) -> None:
    """Enough graded attempts for the review and weekly pages to render their full
    markup rather than their empty states. Written into the throwaway workspace only —
    these are fixture events for surfaces to exist on, never learner data, and the suite
    submits no attempts of its own (grading needs an API key it deliberately lacks).

    Seeded straight into the current layout, learners/<default>/: the startup migration
    from the old single-learner layout has its own tests, and a fixture that depended on
    it would be testing two things at once."""
    learner = course_dir / LEARNERS_DIR_NAME / DEFAULT_USER_ID
    learner.mkdir(parents=True, exist_ok=True)

    # Item ids and concepts are lifted from the example lessons so every seeded event is
    # presentable: _compute_due drops ids no lesson can still show.
    seeds = [
        ("0001-two-curves", "Two curves, not one", "0001", "incorrect", 3),
        ("0001-unreliable-index", "Fluency as an unreliable index", "0001", "correct", 2),
        ("0003-effect-size-and-scope", "The size of the testing effect", "0003", "correct", 4),
        ("0003-short-delay-reversal", "The short-delay reversal", "0003", "incorrect", 4),
        ("0004-gap-sizing", "Sizing the gap", "0004", "partially_correct", 2),
        ("0005-brunmair-boundary", "The interleaving boundary", "0005", "correct", 1),
    ]
    now = datetime.now(UTC)
    lines = []
    for offset, (item_id, concept, lesson, verdict, confidence) in enumerate(seeds):
        lines.append(
            json.dumps(
                {
                    "ts": (now - timedelta(minutes=offset)).isoformat(),
                    "item_id": item_id,
                    "concept": concept,
                    "lesson": lesson,
                    "type": "recall",
                    "cumulative": False,
                    "response": "A seeded fixture response.",
                    "verdict": verdict,
                    "confidence": confidence,
                    "latency_ms": 42000,
                    "gave_up": False,
                    "source": "lesson",
                }
            )
        )
    (learner / ".practice-log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # The weekly page renders its mission check only when MISSION.md carries a success
    # list, and that block is markdown-rendered HTML the scan should see.
    (learner / "MISSION.md").write_text(
        "# Mission\n\n"
        "Understand why studied material fades and which methods change the rate.\n\n"
        "## Success looks like\n\n"
        "- I can state the testing effect's size and its comparison condition.\n"
        "- I can name the condition under which the testing effect reverses.\n",
        encoding="utf-8",
    )


def _start_server(workspace: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = dict(os.environ)
    env["KEATING_WORKSPACE_ROOT"] = str(workspace)
    # These servers are real processes started from the checkout, so the startup settings
    # migration would otherwise find the developer's own settings.json beside the code and
    # move it into a temp workspace this suite then deletes. Pointing the migration at a path
    # that does not exist makes it a no-op, which is what it is for a fresh installation. The
    # in-process suites get the same guarantee from tests/conftest.py.
    env["KEATING_LEGACY_SETTINGS_PATH"] = str(
        tmp_path_factory.mktemp("keating-a11y-legacy") / "settings.json"
    )
    # load_dotenv() never overrides a variable already in the environment, so the line
    # above wins over the developer's .env — but the assertion below is what actually
    # guarantees it, on every run.
    env.pop("ANTHROPIC_API_KEY", None)  # nothing here grades; an absent key proves it
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode("utf-8", "replace") if process.stdout else ""
            raise RuntimeError(f"server exited early (code {process.returncode}):\n{output}")
        try:
            response = httpx.get(f"{base_url}/api/courses", timeout=2.0)
            response.raise_for_status()
            slugs = sorted(course["slug"] for course in response.json()["courses"])
            expected = sorted(p.name for p in workspace.iterdir() if p.is_dir() and not p.name.startswith("."))
            assert slugs == expected, (
                f"server is serving {slugs}, not the fixture workspace {expected} — "
                f"refusing to scan against a workspace this suite did not create"
            )
            return process, base_url
        except Exception as exc:  # not up yet, or up and wrong
            if isinstance(exc, AssertionError):
                process.terminate()
                raise
            last_error = exc
            time.sleep(0.2)
    process.terminate()
    raise RuntimeError(f"server never became ready: {last_error}")


def _stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


@pytest.fixture(scope="session")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of examples/why-you-forget in a temp directory. Nothing in this suite ever
    reads or writes a real workspace."""
    root = tmp_path_factory.mktemp("keating-a11y-workspace")
    shutil.copytree(EXAMPLE_COURSE, root / COURSE_SLUG)
    _seed_practice_log(root / COURSE_SLUG)
    return root


@pytest.fixture(scope="session")
def empty_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace with no courses at all — the only way the app shell's
    no-course-selected state is reachable, since it auto-selects the first course."""
    return tmp_path_factory.mktemp("keating-a11y-empty")


@pytest.fixture(scope="session")
def base_url(workspace: Path, tmp_path_factory: pytest.TempPathFactory):
    process, url = _start_server(workspace, tmp_path_factory)
    yield url
    _stop_server(process)


@pytest.fixture(scope="session")
def empty_base_url(empty_workspace: Path, tmp_path_factory: pytest.TempPathFactory):
    process, url = _start_server(empty_workspace, tmp_path_factory)
    yield url
    _stop_server(process)


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport=DESKTOP_VIEWPORT)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def mobile_page(browser):
    context = browser.new_context(viewport=MOBILE_VIEWPORT, is_mobile=False)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="session")
def tomorrow() -> str:
    """The review loop's one-night rule means today's seeded attempts are due tomorrow;
    ?as_of is the endpoints' own dev hook for exactly this."""
    return (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture(scope="session")
def next_week() -> str:
    """Past WEEKLY_DELAY_DAYS, so the weekly page's delayed check has items in it."""
    return (date.today() + timedelta(days=5)).isoformat()

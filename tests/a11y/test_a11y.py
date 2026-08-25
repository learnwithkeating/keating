# ABOUTME: WCAG 2.0/2.1/2.2 A-and-AA scans of every Keating surface a learner can reach,
# ABOUTME: driven through the real UI with Playwright so each state is the one they see.

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.a11y.axe_scan import assert_no_violations
from tests.a11y.conftest import sign_in

COURSE_SLUG = "why-you-forget"


# --- Driving helpers ----------------------------------------------------------


def open_app(page: Page, base_url: str) -> None:
    """Sign in, load the shell, and wait for the first course to be auto-selected and its
    overview rendered — anything scanned before that is a half-built page, not a surface.
    Presence rather than visibility: on mobile the reading pane is off-screen until its tab is
    picked, and its content is still there to be scanned."""
    sign_in(page, base_url)
    page.goto(base_url, wait_until="networkidle")
    # Checked first, and with a short timeout, because a login fixture that starts the server
    # but fails to authenticate otherwise shows up as a thirty-second Playwright timeout on
    # the course list with nothing in the message about why.
    expect(page.locator("#login")).to_be_hidden(timeout=2000)
    expect(page.locator("#course-list li.active")).to_have_count(1)
    expect(page.locator("#preview-body .overview-title")).to_have_count(1)


def open_page(page: Page, base_url: str, path: str) -> None:
    """A surface opened at its own URL rather than through the shell. Every one of these is
    behind authentication too, so the context is signed in first."""
    sign_in(page, base_url)
    page.goto(f"{base_url}{path}", wait_until="networkidle")


def open_lesson(page: Page) -> None:
    """Expand a unit (they default open for a course this small, so this is a no-op guard)
    and open the first lesson into the reading pane's iframe."""
    first_unit = page.locator("#lesson-list details.unit-group").first
    if not first_unit.evaluate("node => node.open"):
        first_unit.locator("summary").click()
    page.locator("#lesson-list .lesson-entry").first.click()
    frame = page.frame_locator("#preview-body iframe")
    expect(frame.locator("article.lesson h1")).to_be_visible()
    page.wait_for_function(
        "() => { const f = document.querySelector('#preview-body iframe');"
        " return f && f.contentDocument"
        " && f.contentDocument.querySelector('.quiz-item .quiz-response'); }"
    )


def lesson_frame(page: Page):
    """The lesson iframe's Frame object. axe is injected and run inside it, so the scan
    sees the lesson's own document rather than the shell that embeds it."""
    handle = page.locator("#preview-body iframe").element_handle()
    frame = handle.content_frame()
    assert frame is not None, "the reading pane's iframe never got a document"
    return frame


def arm_first_quiz_item(frame) -> None:
    """Put one quiz item into its interactive state: text typed past the submit floor and
    a confidence picked, so the submit button is live. Nothing is submitted — grading is
    a real API call, and this suite makes none."""
    item = frame.locator(".quiz-item").first
    item.locator("textarea.quiz-response").fill(
        "Retrieval practice beats restudy at a delay, by about half a standard deviation."
    )
    item.locator(".quiz-confidence button").nth(2).click()
    expect(item.locator("button.quiz-submit")).to_be_enabled()


# --- 1. The app shell ---------------------------------------------------------


def test_app_shell_no_course(page: Page, empty_base_url: str) -> None:
    """The no-course-selected state, only reachable against an empty workspace: the shell
    auto-selects the first course whenever there is one."""
    open_page(page, empty_base_url, "/")
    expect(page.locator("#login")).to_be_hidden(timeout=2000)
    expect(page.locator("#preview-placeholder")).to_be_visible()
    assert_no_violations(page, "app-shell-no-course")


def test_app_shell_course_selected(page: Page, base_url: str) -> None:
    open_app(page, base_url)
    assert_no_violations(page, "app-shell-course-selected")


# --- 2. A lesson open ---------------------------------------------------------


def test_app_shell_with_lesson_open(page: Page, base_url: str) -> None:
    """The shell itself while a lesson is loaded: the sidebar's selected row, the reading
    pane's masthead, and the embedding iframe."""
    open_app(page, base_url)
    open_lesson(page)
    assert_no_violations(page, "app-shell-with-lesson-open")


def test_lesson_document_in_reading_pane(page: Page, base_url: str) -> None:
    """The lesson document as it renders inside the shell's iframe, quiz machinery and
    injected stylesheet included."""
    open_app(page, base_url)
    open_lesson(page)
    assert_no_violations(lesson_frame(page), "lesson-in-reading-pane")


def test_lesson_url_standalone(page: Page, base_url: str) -> None:
    """The same lesson opened directly at its own URL — a learner can land here, and the
    page has to stand up without the shell around it."""
    open_page(page, base_url, f"/workspace/{COURSE_SLUG}/lessons/0003-retrieval-practice.html")
    expect(page.locator(".quiz-item textarea.quiz-response").first).to_be_visible()
    assert_no_violations(page, "lesson-standalone")


# --- 3. Practice, Compose, Settings -------------------------------------------


def test_practice_view(page: Page, base_url: str) -> None:
    open_app(page, base_url)
    page.locator("#practice-section h2").click()
    expect(page.locator("#preview-body .practice-view, #preview-body .overview")).to_be_visible()
    assert_no_violations(page, "practice-view")


def test_compose_view_recall(page: Page, base_url: str) -> None:
    open_app(page, base_url)
    page.locator("#practice-sidebar-compose").click()
    expect(page.locator("#preview-body .compose-recall")).to_be_visible()
    assert_no_violations(page, "compose-view-recall")


def test_compose_view_define(page: Page, base_url: str) -> None:
    """Compose's second mode renders a different control set (the term list and its save
    row), so it is its own surface."""
    open_app(page, base_url)
    page.locator("#practice-sidebar-compose").click()
    expect(page.locator("#preview-body .compose-recall")).to_be_visible()
    page.locator(".compose-modes .compose-segmented button", has_text="Define").click()
    expect(page.locator("#preview-body .compose-define")).to_be_visible()
    assert_no_violations(page, "compose-view-define")


def test_settings_view(page: Page, base_url: str) -> None:
    open_app(page, base_url)
    page.locator("#settings-link").click()
    expect(page.locator("#preview-body .settings")).to_be_visible()
    assert_no_violations(page, "settings-view")


# --- 4. The generated standalone pages ----------------------------------------


def test_review_page_empty(page: Page, base_url: str) -> None:
    """Today's review with nothing due — the state the learner sees most days."""
    open_page(page, base_url, f"/review/{COURSE_SLUG}")
    expect(page.locator("article.lesson h1")).to_be_visible()
    assert_no_violations(page, "review-page-empty")


def test_review_page_with_items(page: Page, base_url: str, tomorrow: str) -> None:
    """Today's review carrying due items: the source lines and the carried-over quiz
    blocks, run through the same quiz.js the lessons use."""
    open_page(page, base_url, f"/review/{COURSE_SLUG}?as_of={tomorrow}")
    expect(page.locator(".quiz-item textarea.quiz-response").first).to_be_visible()
    assert_no_violations(page, "review-page-with-items")


def test_weekly_page_empty(page: Page, base_url: str) -> None:
    """The weekly page before anything has aged into the delayed check. Its calibration
    section and mark-held control are still present, so this is not an empty page."""
    open_page(page, base_url, f"/weekly/{COURSE_SLUG}")
    expect(page.locator("#weekly-mark-button")).to_be_visible()
    assert_no_violations(page, "weekly-page-empty")


def test_weekly_page_with_items(page: Page, base_url: str, next_week: str) -> None:
    """The full weekly page: delayed check, calibration table, mission check, world
    capture."""
    open_page(page, base_url, f"/weekly/{COURSE_SLUG}?as_of={next_week}")
    expect(page.locator(".quiz-item textarea.quiz-response").first).to_be_visible()
    expect(page.locator("table.weekly-calibration")).to_be_visible()
    assert_no_violations(page, "weekly-page-with-items")


# --- 5. A quiz item mid-attempt -----------------------------------------------


def test_quiz_item_interactive_state(page: Page, base_url: str) -> None:
    """The state a learner is actually in while answering: text in the box, a confidence
    picked, submit armed. Not submitted — the reveal needs a graded API response, and
    fabricating one would scan markup no learner would ever see."""
    open_page(page, base_url, f"/workspace/{COURSE_SLUG}/lessons/0003-retrieval-practice.html")
    arm_first_quiz_item(page)
    assert_no_violations(page, "quiz-item-interactive")


# --- 6. Mobile ----------------------------------------------------------------


def test_app_shell_mobile(mobile_page: Page, base_url: str) -> None:
    """375x812: the tab bar replaces the rails and the panes stack, so this is a
    different DOM state from the desktop shell, not the same one narrower."""
    open_app(mobile_page, base_url)
    expect(mobile_page.locator("#mobile-tabs")).to_be_visible()
    assert_no_violations(mobile_page, "app-shell-mobile")


def test_app_shell_mobile_preview_pane(mobile_page: Page, base_url: str) -> None:
    """The reading pane as the active mobile pane, with a lesson in it."""
    open_app(mobile_page, base_url)
    mobile_page.locator("#mobile-tabs .tab", has_text="Lessons").click()
    open_lesson(mobile_page)
    expect(mobile_page.locator("#app")).to_have_attribute("data-pane", "preview")
    assert_no_violations(mobile_page, "app-shell-mobile-preview")


# --- 7. The login view --------------------------------------------------------

# A new user-facing surface with no axe scan is exactly the gap this suite exists to close.
# All three run against a page that is NOT signed in, and each asserts the state it scans is
# actually visible first: axe skips hidden subtrees, so scanning a `hidden` form asserts
# nothing at all and would pass forever.


def test_the_login_view_has_no_violations(page: Page, base_url: str) -> None:
    """The signed-out shell: the form a learner meets when their session has ended."""
    page.goto(base_url, wait_until="networkidle")
    expect(page.locator("#login-form")).to_be_visible()
    expect(page.locator("#app")).to_be_hidden()
    # Exactly one, and the visible state's own: the login view swaps three panels into one
    # card, so a heading left behind by a hidden sibling would be as wrong as none at all.
    expect(page.locator("#login h1:visible")).to_have_count(1)
    assert_no_violations(page, "login-view")


def test_the_login_error_state_has_no_violations(page: Page, base_url: str) -> None:
    """A refused sign-in: the announcement is what matters here, so the scan runs with the
    role="alert" line actually rendered rather than with the form in its resting state."""
    page.goto(base_url, wait_until="networkidle")
    page.locator("#login-username").fill("nobody-by-that-name")
    page.locator("#login-password").fill("not-the-password")
    page.locator("#login-submit").click()
    expect(page.locator("#login-error")).to_be_visible()
    assert_no_violations(page, "login-view-error")


def test_the_invite_redemption_view_has_no_violations(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="networkidle")
    page.locator("#login-show-invite").click()
    expect(page.locator("#login-invite")).to_be_visible()
    expect(page.locator("#login h1:visible")).to_have_count(1)
    assert_no_violations(page, "login-view-invite")


def test_the_bootstrap_instruction_state_has_no_violations(
    page: Page, unbootstrapped_base_url: str
) -> None:
    """An instance with no accounts renders the command that makes one, not a form nobody
    could satisfy. Its own server, because bootstrapping is a one-way door."""
    page.goto(unbootstrapped_base_url, wait_until="networkidle")
    expect(page.locator("#login-setup")).to_be_visible()
    expect(page.locator("#login-form")).to_be_hidden()
    assert_no_violations(page, "login-view-bootstrap")

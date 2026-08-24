# ABOUTME: The reader's sanitizer and its CSP under a real browser: every known bypass payload
# ABOUTME: is loaded as a real document and nothing executes.

"""The end-to-end proof, because "nothing executable comes out" is a claim about a browser,
not a claim about a string. The page under test is built from the real
_sanitize_extracted_html, the real _reader_page and the real CSP_READER constant, and it is
served over HTTP so the header is a header rather than a fixture value.

It deliberately stops short of the outbound fetch: the reader's SSRF guard correctly refuses
a loopback address, so no fixture server in this process can be reached through
/api/reader. Everything from the extracted markup onward is the real code path.

test_the_harness_detects_execution is the negative control, and it is not optional. A test
that asks "did anything execute?" is worthless unless something can. It drives the raw
corpus through the identical browser path with no sanitizer and no policy, and fails if the
sentinel stays quiet.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from main import CSP_READER, _reader_page, _sanitize_extracted_html
from tests.test_reader_sanitizer import ARTICLE_URL, BYPASS_CORPUS

MARKER = "__KEATING_FIRED__:"

# Installed before any page script could run, and injected through CDP rather than through
# the document, so it is not itself subject to the page's CSP. Every corpus payload calls
# __x() from the position that would execute.
#
# It reports through console.error as well as through a global, because a click on a
# surviving link navigates the document and takes any global with it — and because console
# still works in the opaque origin the reader's sandbox directive puts the page in, where
# storage does not.
SENTINEL_SETUP = f"""
window.__fired = [];
window.__x = function (name) {{
  window.__fired.push(name);
  console.error({MARKER!r} + name);
  // No return value: a javascript: URL that returns a string replaces the document with
  // it, which would tear down the page mid-sweep.
}};
"""

# Fire every event the corpus's handlers were attached to, at every node, so a handler that
# survived but has no natural trigger in a headless browser still shows up — <video>'s
# onerror and MathML's onmouseover both need this.
PROVOKE = """
() => {
  const types = ["load", "error", "toggle", "focus", "mouseover", "start", "click"];
  for (const node of document.querySelectorAll("*")) {
    for (const type of types) {
      try { node.dispatchEvent(new Event(type, { bubbles: true })); } catch (e) { /* inert */ }
    }
  }
  return window.__fired;
}
"""

CORPUS_ARTICLE = "\n".join(f"<p>{payload}</p>" for _, payload in BYPASS_CORPUS)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def serving(html: str, policy: str | None) -> Iterator[str]:
    """One document on a loopback port, with the policy under test as a real header."""
    page = html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's own naming
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            if policy is not None:
                self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args: object) -> None:
            """Quiet: the suite's output has to stay pristine."""

    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def load_and_provoke(browser, url: str) -> tuple[list[str], list[str]]:
    """Open the document, let whatever fires on load fire, sweep every node with every
    event the corpus uses, then hover and click for real. Returns (fired, console)."""
    context = browser.new_context()
    context.add_init_script(SENTINEL_SETUP)
    console: list[str] = []
    context.on("page", lambda opened: opened.on("console", lambda m: console.append(m.text)))
    # Hermetic: the only host this suite may reach is its own fixture server. The font
    # stylesheet the reader @imports is external, and blocking it changes nothing the
    # assertions look at — getComputedStyle reports the declared family list either way.
    context.route(
        "**/*", lambda route: route.continue_() if url in route.request.url else route.abort()
    )
    page = context.new_page()
    # <base target="_blank"> sends every article link to a tab of its own.
    context.on("page", lambda opened: opened is not page and opened.close())
    try:
        page.goto(url, wait_until="networkidle")
        page.evaluate(PROVOKE)
        nodes = page.locator("body *")
        for index in range(nodes.count()):
            # A node that is off-screen, zero-sized or covered is not interactable and
            # raises here; the synthetic sweep above already reached it.
            with contextlib.suppress(Exception):
                nodes.nth(index).hover(timeout=500)
                nodes.nth(index).click(timeout=500, force=True)
        page.wait_for_timeout(200)
        # Read the sentinel back off the console rather than off the global: a click that
        # navigates takes the global with it, and console capture survives.
        fired = [line[len(MARKER):] for line in console if line.startswith(MARKER)]
        return fired, console
    finally:
        context.close()


def test_the_harness_detects_execution(browser) -> None:
    """The negative control. Raw corpus, no sanitizer, no policy: the sentinel must speak,
    or every assertion in the test below is vacuous."""
    raw = f"<!DOCTYPE html><html><body><div class='reader'>{CORPUS_ARTICLE}</div></body></html>"
    with serving(raw, policy=None) as url:
        fired, console = load_and_provoke(browser, url)

    # Every vector the corpus calls a confirmed bypass, asserted by name so a harness that
    # only half works still fails. marquee_slash_onstart is the one omission and the corpus
    # says why: the attribute survives sanitization, but Chromium does not reflect onstart
    # on HTMLMarqueeElement at all (the IDL property is undefined), so nothing can raise
    # it. It stays in the corpus as a regression guard on the sanitizer, where it is
    # checked as a string.
    for name in (
        "svg_slash_onload",
        "body_slash_onload",
        "input_slash_onfocus_autofocus",
        "details_slash_ontoggle",
        "img_quoted_src_slash_onerror",
        "video_slash_onerror",
        "math_maction_slash",
        "a_js_url_newline",
        "a_js_url_entity",
    ):
        assert name in fired, f"the harness did not observe {name}; it cannot prove anything"
    assert any(line.startswith(MARKER) for line in console)


def test_no_corpus_payload_executes(browser) -> None:
    """The same corpus, the same browser path, through the real sanitizer and behind the
    real reader policy."""
    nonce = "test-nonce-not-a-secret"
    page_html = _reader_page(
        "Corpus",
        "example.org",
        ARTICLE_URL,
        _sanitize_extracted_html(CORPUS_ARTICLE, ARTICLE_URL),
        nonce,
    )
    with serving(page_html, policy=CSP_READER.format(nonce=nonce)) as url:
        fired, console = load_and_provoke(browser, url)

    assert fired == [], f"the reader executed article script: {fired}"
    assert not [line for line in console if line.startswith(MARKER)], (
        f"the reader executed article script: {json.dumps(console)}"
    )


def test_the_readers_own_stylesheet_still_applies(browser) -> None:
    """The page must be inert *and* intact: a blocked <style> would pass the execution
    assertions on a page that is simply broken, and the failure mode of a mis-plumbed
    nonce is exactly that."""
    nonce = "test-nonce-not-a-secret"
    page_html = _reader_page("T", "example.org", ARTICLE_URL, "<p>body</p>", nonce)
    with serving(page_html, policy=CSP_READER.format(nonce=nonce)) as url:
        context = browser.new_context()
        console: list[str] = []
        page = context.new_page()
        page.on("console", lambda message: console.append(message.text))
        context.route(
            "**/*", lambda route: route.continue_() if url in route.request.url else route.abort()
        )
        try:
            page.goto(url, wait_until="networkidle")
            font = page.evaluate("() => getComputedStyle(document.body).fontFamily")
        finally:
            context.close()

    assert "Newsreader" in font, f"the reader's own nonced stylesheet did not apply: {font}"
    refusals = [line for line in console if "Content Security Policy" in line]
    assert not refusals, f"the reader page violates its own policy: {refusals}"


@pytest.mark.parametrize("markup", ["<p style='color:red'>x</p>", "<style>p{color:red}</style>"])
def test_third_party_style_is_blocked_at_both_layers(browser, markup: str) -> None:
    """The nonce has to split the reader's own <style> from anything the article carried.
    The sanitizer drops both of these before they reach the page; this asserts the policy
    would hold even if it did not."""
    nonce = "test-nonce-not-a-secret"
    sanitized = _sanitize_extracted_html(markup, ARTICLE_URL)
    assert "style" not in sanitized.lower(), sanitized

    # A paragraph the style could apply to, since one of the two payloads is all style.
    page_html = _reader_page("T", "example.org", ARTICLE_URL, f"{markup}<p>x</p>", nonce)
    with serving(page_html, policy=CSP_READER.format(nonce=nonce)) as url:
        context = browser.new_context()
        page = context.new_page()
        context.route(
            "**/*", lambda route: route.continue_() if url in route.request.url else route.abort()
        )
        try:
            page.goto(url, wait_until="networkidle")
            color = page.evaluate(
                "() => getComputedStyle(document.querySelector('.reader p')).color"
            )
        finally:
            context.close()

    assert color != "rgb(255, 0, 0)", "an un-nonced style from the article applied"

# ABOUTME: The reader sanitizer's contract: every known regex bypass comes out inert, and
# ABOUTME: legitimate article markup survives intact.

from __future__ import annotations

import re

import nh3
import pytest

from main import (
    READER_ALLOWED_ATTRIBUTES,
    READER_ALLOWED_TAGS,
    READER_ALLOWED_URL_SCHEMES,
    _sanitize_extracted_html,
)

# Every payload is sanitized as though it arrived from this article, so the relative-URL
# rewrite has a base to resolve against.
ARTICLE_URL = "https://example.org/a/b"

# The confirmed bypass corpus: markup whose meaning to a parser differs from its shape as a
# string. Ten of these carry a live handler or a live URL once a browser has parsed them;
# the last two are documented boundary cases that are inert today and are kept as regression
# guards, so that a future edit which makes them live fails here rather than in a browser.
#
# `__x` is the sentinel: it appears in every payload in a position that would execute, so
# its absence from the output is the single check that covers all of them.
BYPASS_CORPUS = [
    # A "/" straight after the tag name is a valid attribute separator, so the handler
    # lands with no preceding whitespace to mark it as an attribute.
    ("svg_slash_onload", "<svg/onload=__x('svg_slash_onload')>"),
    ("body_slash_onload", "<body/onload=__x('body_slash_onload')>"),
    (
        "input_autofocus_slash_onfocus",
        "<input autofocus/onfocus=__x('input_slash_onfocus_autofocus')>",
    ),
    (
        "details_open_slash_ontoggle",
        "<details open/ontoggle=__x('details_slash_ontoggle')>x</details>",
    ),
    # After a *quoted* value the "/" separates attributes, so onerror survives.
    (
        "img_quoted_src_slash_onerror",
        '<img src="x"/onerror=__x(\'img_quoted_src_slash_onerror\')>',
    ),
    (
        "video_slash_onerror",
        "<video/onerror=__x('video_slash_onerror')><source src=x></video>",
    ),
    (
        "math_mtext_slash_onmouseover",
        "<math><maction/actiontype=statusline#>"
        "<mtext/onmouseover=__x('math_maction_slash')>x</mtext></maction></math>",
    ),
    # Browsers strip tab/newline/CR from a URL before parsing its scheme, so this
    # reconstitutes to javascript: while defeating the regex's contiguous match.
    (
        "anchor_js_url_newline_in_scheme",
        '<a href="java\nscript:__x(\'a_js_url_newline\')">c</a>',
    ),
    (
        "anchor_js_url_html_entity_colon",
        "<a href=\"javascript&#58;__x('a_js_url_entity')\">c</a>",
    ),
    # Survives sanitization with a live onstart attribute; headless Chromium suppresses
    # marquee scrolling, so execution was never observed, only the live handler.
    (
        "marquee_slash_onstart",
        "<marquee/onstart=__x('marquee_slash_onstart')>x</marquee>",
    ),
    # NOT a bypass — the boundary. With an *unquoted* src the browser swallows
    # "x/onerror=__x(...)" into the src value, so no handler attribute ever exists.
    (
        "img_slash_onerror_negative_boundary",
        "<img src=x/onerror=__x('img_slash_onerror')>",
    ),
    # An unterminated <script>. The parser takes everything after the open tag as script
    # text and drops the tag together with that text, so nothing is left for a close tag
    # arriving later in the document to revive.
    ("script_no_close", "<script>__x('script_no_close')"),
]

# The tags whose mere presence in reader output is a defect, whether or not they carry a
# handler: foreign content, embedding, and the elements the deny-list never enumerated.
FORBIDDEN_TAGS_RE = re.compile(
    r"<\s*/?\s*(?:svg|math|iframe|object|embed|form|style|script|link|meta|base"
    r"|marquee|video|audio|source|input|button|textarea|select|body|html|head)\b",
    re.IGNORECASE,
)
ON_ATTR_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)


def sanitize(markup: str, base_url: str = ARTICLE_URL) -> str:
    return _sanitize_extracted_html(markup, base_url)


# --- The bypass corpus --------------------------------------------------------


@pytest.mark.parametrize(("name", "payload"), BYPASS_CORPUS, ids=[n for n, _ in BYPASS_CORPUS])
def test_bypass_corpus_leaves_nothing_executable(name: str, payload: str) -> None:
    out = sanitize(payload)
    assert "__x" not in out, f"{name}: the execution sentinel survived: {out!r}"
    assert not ON_ATTR_RE.search(out), f"{name}: an event handler survived: {out!r}"
    assert not FORBIDDEN_TAGS_RE.search(out), f"{name}: a forbidden tag survived: {out!r}"
    lowered = out.lower()
    assert "javascript:" not in lowered, f"{name}: a javascript: URL survived: {out!r}"
    assert "data:" not in lowered, f"{name}: a data: URL survived: {out!r}"


def test_obfuscated_javascript_urls_lose_their_href() -> None:
    """Both spellings reconstitute to javascript: only after the URL parser has stripped
    the whitespace and decoded the entity, which is why the scheme has to be read off the
    parsed URL rather than off the attribute text. The anchor keeps its text — the article
    is still readable — but there is nothing left to navigate to."""
    newline = sanitize('<a href="java\nscript:alert(1)">c</a>')
    entity = sanitize('<a href="javascript&#58;alert(1)">c</a>')
    assert newline == '<a rel="noopener noreferrer">c</a>'
    assert entity == '<a rel="noopener noreferrer">c</a>'


def test_data_url_href_is_dropped() -> None:
    """A data:text/html document navigated to from the reader runs as a document of its
    own, so the scheme allow-list has to exclude it as firmly as it excludes javascript:."""
    out = sanitize('<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">c</a>')
    assert out == '<a rel="noopener noreferrer">c</a>'


def test_unterminated_script_loses_its_text_too() -> None:
    """clean_content_tags defaults to {script, style} and drops the element *with* its
    content, so an unterminated <script> leaves no residue to be re-parsed."""
    assert sanitize("<script>alert(1)") == ""
    assert sanitize("<style>body{}</style>after") == "after"


# --- What must survive --------------------------------------------------------


def test_preserves_article_markup() -> None:
    """The other half of the contract: a parser-based allow-list must not quietly gut the
    reading pane. Everything here is ordinary article markup trafilatura emits."""
    article = (
        "<h1>One</h1><h2>Two</h2><h3>Three</h3><h4>Four</h4><h5>Five</h5><h6>Six</h6>"
        "<p>Body <em>emphasis</em> <strong>strong</strong> <code>code</code> "
        "<sub>sub</sub> <sup>sup</sup> <del>del</del>.</p>"
        "<ul><li>bullet</li></ul>"
        '<ol start="3"><li>numbered</li></ol>'
        '<blockquote cite="https://example.org/src"><p>quoted</p></blockquote>'
        "<pre>preformatted</pre>"
        "<hr><p>a<br>b</p>"
        "<figure><figcaption>caption</figcaption></figure>"
        "<table><caption>cap</caption><thead><tr><th scope=\"col\">head</th></tr></thead>"
        '<tbody><tr><td colspan="2">cell</td></tr></tbody></table>'
        '<p><a href="https://example.org/x" title="t">link</a> '
        '<a href="mailto:someone@example.org">mail</a></p>'
    )
    out = sanitize(article)

    for fragment in (
        "<h1>One</h1>",
        "<h6>Six</h6>",
        "<em>emphasis</em>",
        "<strong>strong</strong>",
        "<code>code</code>",
        "<sub>sub</sub>",
        "<sup>sup</sup>",
        "<del>del</del>",
        "<ul>",
        "<li>bullet</li>",
        '<ol start="3">',
        # The element survives; its cite URL does not, and nothing renders it either way.
        "<blockquote>",
        "<pre>preformatted</pre>",
        "<hr>",
        "<br>",
        "<figure>",
        "<figcaption>caption</figcaption>",
        "<caption>cap</caption>",
        "<thead>",
        '<th scope="col">',
        '<td colspan="2">',
        '<a href="https://example.org/x" title="t"',
        '<a href="mailto:someone@example.org"',
    ):
        assert fragment in out, f"the allow-list dropped {fragment!r} from:\n{out}"


def test_table_rows_stay_inside_the_table() -> None:
    """html5ever synthesises a <tbody> around trafilatura's bare <tr>. Leave tbody off the
    allow-list and every row unwraps out of the table it belongs to."""
    out = sanitize("<table><tr><td>a</td></tr></table>")
    assert "<tbody>" in out
    assert re.search(r"<table>\s*<tbody>\s*<tr>", out), out


def test_images_are_dropped() -> None:
    """A deliberate choice, not an oversight: the extractor is called with
    include_images=False, so allowing <img> would arm a per-open read receipt the moment
    that flag flips. Re-adding it should be a conscious edit with this test attached."""
    assert sanitize('<p><img src="https://tracker.example/pixel.gif" alt="x">text</p>') == (
        "<p>text</p>"
    )


def test_html_and_body_wrappers_are_unwrapped() -> None:
    """Neither tag is on the allow-list, so the parser unwraps trafilatura's <html><body>
    envelope on its own and the article fragment inside comes through untouched."""
    assert sanitize("<html><body><p>hi</p></body></html>") == "<p>hi</p>"


def test_relative_href_resolves_against_the_article() -> None:
    """A bare "/x" in an archived article must point at the article's own origin, never at
    Keating's, where it would be a link into the app's unauthenticated API."""
    out = sanitize('<a href="/x">c</a>')
    assert 'href="https://example.org/x"' in out


# --- The configuration itself -------------------------------------------------


def test_allow_list_is_applied_in_full() -> None:
    """The footgun: passing tags= tightens nothing else. attributes= and url_schemes= fall
    back to their own permissive defaults independently, so dropping either argument
    silently re-admits nh3's 25 URL schemes and its default attribute map. Both halves of
    this test fail if that happens."""
    assert sanitize('<a href="magnet:?xt=urn:btih:x">c</a>') == '<a rel="noopener noreferrer">c</a>'
    assert sanitize('<a href="https://example.org" id="x">c</a>') == (
        '<a href="https://example.org" rel="noopener noreferrer">c</a>'
    )


def test_rel_in_the_attribute_map_would_raise() -> None:
    """link_rel stamps rel= on every anchor; whitelisting rel as well is a configuration
    conflict nh3 refuses. Asserted so a future edit fails at test time, not at request
    time on a learner's reading pane."""
    attributes = {tag: set(attrs) for tag, attrs in READER_ALLOWED_ATTRIBUTES.items()}
    attributes["a"].add("rel")
    with pytest.raises(ValueError, match="rel"):
        nh3.clean(
            "<a>x</a>",
            tags=READER_ALLOWED_TAGS,
            attributes=attributes,
            url_schemes=READER_ALLOWED_URL_SCHEMES,
            link_rel="noopener noreferrer",
        )


def test_a_tag_in_both_tags_and_clean_content_tags_would_raise() -> None:
    """The other configuration conflict: a tag cannot be both kept and content-stripped."""
    with pytest.raises(ValueError):
        nh3.clean(
            "<p>x</p>",
            tags=READER_ALLOWED_TAGS,
            clean_content_tags={"p"},
        )


def test_no_attribute_outside_the_map_survives() -> None:
    """The map is the whole allow-list, not a supplement to one. nh3 keeps a generic set
    of attributes on every tag unless a "*" key overrides it, so without that key an
    article could carry third-party attributes on tags the map never mentions."""
    for tag in sorted(READER_ALLOWED_TAGS - {"br", "hr", "wbr", "col"}):
        allowed = READER_ALLOWED_ATTRIBUTES.get(tag, set())
        for attribute in ("title", "lang", "dir", "id", "class", "style"):
            if attribute in allowed:
                continue
            out = sanitize(f'<{tag} {attribute}="zz">t</{tag}>')
            assert f"{attribute}=" not in out, f"<{tag} {attribute}> survived: {out!r}"


def test_cite_is_not_admitted_on_any_tag() -> None:
    """cite is the one URL-bearing attribute nh3 does not recognise as a URL, so neither
    the scheme allow-list nor the relative-URL rewrite reaches it. No browser navigates
    cite and no reader ever sees it, so it is not on the map at all — an attribute the
    sanitizer cannot filter is not worth invisible metadata."""
    assert "cite" not in {a for attrs in READER_ALLOWED_ATTRIBUTES.values() for a in attrs}
    out = sanitize(
        '<blockquote cite="javascript:alert(1)"><q cite="/rel">x</q></blockquote>'
        '<del cite="javascript:alert(1)">y</del><ins cite="data:text/html,z">w</ins>'
    )
    assert "cite=" not in out
    assert "javascript:" not in out
    assert "data:" not in out


def test_a_base_url_outside_the_scheme_list_is_refused() -> None:
    """Every relative URL in the article inherits the base's scheme, and nh3 does not
    re-check the rewritten result against url_schemes. The reader's three-scheme
    guarantee therefore depends on the base being http(s), which _assert_public_http_url
    guarantees for every caller today — asserted here so the sanitizer holds its own
    contract rather than borrowing one from a guard three functions away."""
    for base in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd"):
        with pytest.raises(ValueError, match="base URL"):
            _sanitize_extracted_html('<a href="#f">F</a>', base)

# ABOUTME: The axe-core runner shared by every a11y test: one ruleset, one report format,
# ABOUTME: and the documented per-rule/per-surface exclusion list.

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from axe_playwright_python.sync_playwright import Axe

REPO_ROOT = Path(__file__).resolve().parents[2]

# WCAG 2.0 A/AA, 2.1 A/AA, and 2.2 AA. Deliberately not axe's "best-practice" tag: those
# rules are opinions worth having, but they are not WCAG failures and a red CI check
# should mean a standard was broken.
WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

AXE_OPTIONS: dict[str, Any] = {
    "runOnly": {"type": "tag", "values": WCAG_TAGS},
    # Each surface is scanned on its own so a failure names the surface. Frame contents
    # are scanned as their own surfaces (see the lesson-iframe tests) rather than folded
    # into whatever page happens to embed them.
    "iframes": False,
    # "incomplete" is what axe could not decide without a human; the suite reports it and
    # does not fail on it. Everything else axe returns is noise for this purpose.
    "resultTypes": ["violations", "incomplete"],
}

# --- Documented exclusions ----------------------------------------------------
#
# Per rule, per surface, with the reason. There is no blanket disable and no rule is
# switched off globally: an entry here means "this rule, on this one surface, is a known
# false positive or a limitation of the harness", and it is a bug to add one for anything
# that could instead be fixed in the app.
#
# Empty. Every violation the first scan turned up was fixed in the markup or the CSS.
EXCLUSIONS: dict[str, dict[str, str]] = {}

REPORT_DIR = Path(os.environ.get("A11Y_REPORT_DIR", REPO_ROOT / ".a11y-report"))

_axe = Axe()


def _node_lines(nodes: list[dict[str, Any]]) -> list[str]:
    lines = []
    for node in nodes:
        target = ", ".join(str(t) for t in node.get("target", []))
        snippet = " ".join((node.get("html") or "").split())[:160]
        lines.append(f"      selector: {target}")
        lines.append(f"      snippet:  {snippet}")
        for check in node.get("any", []) + node.get("all", []) + node.get("none", []):
            lines.append(f"      why:      {check.get('message', '')}")
    return lines


def _format(kind: str, entries: list[dict[str, Any]]) -> str:
    lines = []
    for entry in entries:
        lines.append(
            f"  [{kind}] {entry['id']} (impact: {entry.get('impact') or 'n/a'}) "
            f"- {entry.get('help', '')}"
        )
        lines.extend(_node_lines(entry.get("nodes", [])))
    return "\n".join(lines)


def settle(target) -> None:
    """Let every running CSS transition finish before axe samples computed colours.

    The shell transitions colour and background over 160ms on rows, buttons and inputs,
    so a scan fired immediately after a click reads a blend of the two states — which is
    a measurement artifact, not a contrast failure, and would have made this suite report
    violations that do not exist. Waiting on document.getAnimations() (Chromium reports
    CSS transitions there) scans the state the learner actually settles on."""
    target.evaluate(
        "() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => null)))"
    )
    target.evaluate("() => new Promise((resolve) => requestAnimationFrame(() => resolve()))")


def scan(target, surface: str, context: Any = None) -> dict[str, Any]:
    """Run axe against a Playwright Page or Frame and return the raw results, after
    saving them for the CI artifact. `target` only has to have .evaluate, which is true
    of both Page and Frame — the lesson surfaces scan a same-origin child frame."""
    settle(target)
    results = _axe.run(target, context=context, options=AXE_OPTIONS)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe = surface.replace("/", "_").replace(" ", "-")
    (REPORT_DIR / f"{safe}.json").write_text(
        json.dumps(results.response, indent=2), encoding="utf-8"
    )
    return results.response


def assert_no_violations(target, surface: str, context: Any = None) -> None:
    """Scan and fail on any WCAG violation, naming the rule, its impact and the offending
    selector. Incomplete results are printed for the record but never fail: they are the
    ones axe cannot settle without a person looking."""
    response = scan(target, surface, context=context)

    excluded_here = EXCLUSIONS.get(surface, {})
    violations = [v for v in response["violations"] if v["id"] not in excluded_here]
    skipped = [v for v in response["violations"] if v["id"] in excluded_here]
    incomplete = response.get("incomplete", [])

    report = [f"a11y scan: {surface} ({response.get('url', '')})"]
    if incomplete:
        report.append(f"  {len(incomplete)} incomplete (needs human review, not failing):")
        report.append(_format("incomplete", incomplete))
    for entry in skipped:
        report.append(f"  [excluded] {entry['id']}: {excluded_here[entry['id']]}")
    print("\n".join(report))

    if violations:
        detail = "\n".join(
            [f"{len(violations)} WCAG violation(s) on {surface}:", _format("violation", violations)]
        )
        raise AssertionError(detail)

# ABOUTME: Tests for what the assembled system prompt carries: the skill files' prose, and none
# ABOUTME: of the skill-loader frontmatter that only a terminal session's discovery needs.

from __future__ import annotations

import main


def test_the_skill_loader_frontmatter_never_reaches_the_model() -> None:
    """SKILL.md's YAML header names the skill for a coding agent's skill discovery. It is metadata,
    not instruction, and `disable-model-invocation` states the opposite of what is happening
    here — so the file keeps it and the prompt does not."""
    assert "disable-model-invocation" not in main.SKILL_TEXT
    assert "argument-hint" not in main.SKILL_TEXT

    on_disk = (main.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert on_disk.startswith("---\n"), "the terminal path reads this file and needs its header"


def test_every_skill_file_reaches_the_model_body_first() -> None:
    for filename in main.SKILL_FILES:
        body = (main.SKILL_DIR / filename).read_text(encoding="utf-8")
        first_prose = main._SKILL_FRONTMATTER_RE.sub("", body).split("\n", 1)[0]
        assert first_prose in main.SKILL_TEXT, filename

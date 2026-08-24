# The FastAPI backend for the Keating UI
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
from datetime import date, datetime, timezone
from html import escape as html_escape, unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import anthropic
import httpx
from dotenv import load_dotenv
import markdown as markdown_lib
import trafilatura
from anthropic.lib.tools import ToolError, beta_tool
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- Configuration ---------------------------------------------------------

# Environment (including ANTHROPIC_API_KEY) can live in a local .env file; loading it
# here, before the anthropic client below is constructed, makes restarts self-contained.
load_dotenv()

# Where courses live. The default is deliberately OUTSIDE this repo: a workspace holds
# learner state (practice logs, chat history, records), which must never be committed
# alongside the platform. Point KEATING_WORKSPACE_ROOT (env or .env) somewhere else to
# use an existing workspace.
WORKSPACE_ROOT = Path(
    os.environ.get("KEATING_WORKSPACE_ROOT", str(Path.home() / "keating-courses"))
).resolve()

# The complete pedagogy package (skill, teaching policy, format docs) ships WITH the
# app; ~/.claude/skills/teach is a symlink to this directory so terminal sessions
# consume the same package. The platform has no pedagogical dependencies outside its
# own repo.
SKILL_DIR = Path(__file__).parent / "skill"
SKILL_FILES = [
    "SKILL.md",
    # The policy reads directly after SKILL.md, which binds all interaction to it.
    "TEACHING-POLICY.md",
    "MISSION-FORMAT.md",
    "RESOURCES-FORMAT.md",
    "LEARNING-RECORD-FORMAT.md",
    "GLOSSARY-FORMAT.md",
]

MAX_TOKENS = 16000

COURSE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Archived courses live here, outside every course listing; the leading dot already hides
# it from dot-excluding listings, but it is reserved explicitly too so nothing can treat it
# as a course.
ARCHIVE_DIR_NAME = ".archive"

# Workspace subdirectories that are not courses (shared platform material lives here).
RESERVED_DIRS = {"docs", ARCHIVE_DIR_NAME}

# Artifact files maintained by the teach skill itself; lesson nav links to these are
# chrome, not lesson resources, and they are not "unclaimed files" either. RESOURCES.md
# sits at the course root; the rest live under learner/.
COURSE_ARTIFACTS = {"MISSION.md", "RESOURCES.md", "NOTES.md", "GLOSSARY.md"}

# A course directory splits in two. The course package — course.json, lessons/, assets/,
# materials/, RESOURCES.md — is portable: it can be handed to another learner as-is. The
# learner directory holds everything about how one particular person is doing on it, so
# that sharing a course never leaks a learner's record.
LEARNER_DIR_NAME = "learner"
MATERIALS_DIR_NAME = "materials"

# The course package's manifest. Courses predating it still load — an absent manifest
# simply means the de-slugified directory name is the best title available.
COURSE_MANIFEST_NAME = "course.json"
COURSE_MANIFEST_SCHEMA = "keating.course/1"

# The middle tier between course and lesson. The manifest defines the units; each lesson
# declares which one it belongs to (<meta name="keating:unit">), so membership is derived
# from the lessons rather than duplicated in the manifest. Courses name the tier in their
# own vocabulary — "Part" for a syllabus, "Domain" for an exam outline — and one without a
# manifest label simply calls it a Unit. Units are additive: a course with none, or a
# lesson declaring none, keeps working exactly as before.
LESSON_UNIT_META_NAME = "keating:unit"
DEFAULT_UNIT_LABEL = "Unit"

# Learner-state guardrails (charter G13: the recorded history of what the learner knows
# must not be rewritable without trace). Learning records are created and superseded only
# through their dedicated tools — write_file never touches this directory — and an
# overwrite of either snapshot file first copies the previous version into the hidden
# state-history directory. The snapshot is the trace; consent stays a policy-layer
# obligation (TEACHING-POLICY.md requires confirming mission changes with the learner).
# All three live inside the learner directory.
LEARNING_RECORDS_DIR_NAME = "learning-records"
SNAPSHOT_ON_OVERWRITE = {"MISSION.md", "GLOSSARY.md"}
STATE_HISTORY_DIR_NAME = ".state-history"

# Numeric filename prefix used by lessons/ and learning-records/ entries (e.g. 0001-foo).
NUMBERED_FILE_RE = re.compile(r"^(\d+)")

MARKDOWN_EXTENSIONS = ["tables", "fenced_code"]

STATIC_DIR = Path(__file__).parent / "static"


# --- Settings (platform-level, persisted to settings.json) -------------------

# The chat and grading models are read from SETTINGS at request time, so a PUT to
# /api/settings applies without a restart. Changing the chat model invalidates the
# prompt-cache prefix on the big system prompt (caches are per-model) — expected and
# harmless: the first turn after a switch pays the uncached price once.

SETTINGS_PATH = Path(__file__).parent / "settings.json"

# The static catalog /api/settings serves to the UI; ids are the only values the two
# model fields accept.
MODEL_CATALOG = [
    {"id": "claude-opus-5", "label": "Claude Opus 5", "price": "$5 / $25 per MTok"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "price": "$3 / $15 per MTok"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "price": "$1 / $5 per MTok"},
]
ALLOWED_MODEL_IDS = {entry["id"] for entry in MODEL_CATALOG}

DEFAULT_SETTINGS: dict[str, Any] = {
    "chat_model": "claude-opus-5",
    "grading_model": "claude-opus-5",
    "layout": {"remember_sizes": False, "sidebar_w": 250, "chat_w": 460},
}

# Pane-width bounds mirror the frontend's rail clamps (app.js RAIL).
SIDEBAR_W_MIN, SIDEBAR_W_MAX = 220, 320
CHAT_W_MIN, CHAT_W_MAX = 380, 620


def _load_settings() -> dict[str, Any]:
    """Read settings.json merged over the defaults: an absent or unreadable file means
    defaults, unknown keys are ignored, and missing or invalid values fall back to
    their defaults individually."""
    merged: dict[str, Any] = {
        "chat_model": DEFAULT_SETTINGS["chat_model"],
        "grading_model": DEFAULT_SETTINGS["grading_model"],
        "layout": dict(DEFAULT_SETTINGS["layout"]),
    }
    if not SETTINGS_PATH.is_file():
        return merged
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return merged
    if not isinstance(raw, dict):
        return merged
    for key in ("chat_model", "grading_model"):
        if raw.get(key) in ALLOWED_MODEL_IDS:
            merged[key] = raw[key]
    layout = raw.get("layout")
    if isinstance(layout, dict):
        if isinstance(layout.get("remember_sizes"), bool):
            merged["layout"]["remember_sizes"] = layout["remember_sizes"]
        for width_key, low, high in (
            ("sidebar_w", SIDEBAR_W_MIN, SIDEBAR_W_MAX),
            ("chat_w", CHAT_W_MIN, CHAT_W_MAX),
        ):
            value = layout.get(width_key)
            if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
                merged["layout"][width_key] = value
    return merged


SETTINGS = _load_settings()


def _save_settings(settings: dict[str, Any]) -> None:
    """Atomic write: tmp file beside the target, then os.replace."""
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


# --- System prompt: load the actual skill files verbatim, once, at startup -

def _load_skill_text() -> str:
    if not SKILL_DIR.is_dir():
        raise RuntimeError(
            f"pedagogy package missing from the repo: {SKILL_DIR} not found — the platform's "
            "skill/ directory ships with the app and is required to build its system prompt."
        )
    chunks: list[str] = []
    for filename in SKILL_FILES:
        path = SKILL_DIR / filename
        if not path.is_file():
            raise RuntimeError(
                f"pedagogy package file missing from the repo: {path} — the platform's "
                "skill/ directory ships with the app."
            )
        chunks.append(f"--- {filename} ---\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


SKILL_TEXT = _load_skill_text()


def system_prompt_for(course: str) -> str:
    preamble = (
        "You are operating inside a small local web app that lets a single person dogfood "
        "the \"teach\" Claude Code skill through a browser, instead of through the Claude Code "
        "terminal. The rules below, from that skill's own SKILL.md and its linked format docs, "
        "govern your behavior exactly as they would in a terminal session — follow them as written.\n\n"
        f"WORKSPACE_ROOT is a teaching-workspace container: one subdirectory per subject, per the "
        "skill's own convention. You are currently working inside the course subdirectory "
        f'"{course}". Treat that subdirectory as "the current directory" / teaching workspace root '
        "that the skill instructions refer to below.\n\n"
        "That course directory splits in two, and the split is real — use these exact paths:\n"
        "- The course package, portable to any learner: course.json (the manifest), "
        "./lessons/, ./assets/, ./materials/ (source material such as a syllabus), "
        "./reference/, and RESOURCES.md.\n"
        "- This learner's own state, under ./learner/: learner/MISSION.md, learner/NOTES.md, "
        "learner/GLOSSARY.md, and learner/learning-records/.\n\n"
        "Your five tools — read_file, write_file, list_dir, append_learning_record, and "
        "supersede_learning_record — take paths relative to the course subdirectory "
        "(e.g. \"learner/MISSION.md\", \"lessons/0001-foo.html\"), not relative to WORKSPACE_ROOT "
        "itself. Nothing is remapped for you: to read the mission, read \"learner/MISSION.md\". "
        "Learning records are created only via append_learning_record (the platform computes the "
        "number and filename) and modified only via supersede_learning_record; write_file cannot "
        "touch learner/learning-records/ or hidden files, and overwriting learner/MISSION.md or "
        "learner/GLOSSARY.md automatically preserves the previous version. "
        "Files are created lazily, only when there is real content to put in them — never fabricate "
        "content to fill out the structure. Before creating a new numbered lesson, use list_dir to "
        "check what already exists and continue the numbering convention correctly.\n\n"
        "The skill's own instructions follow verbatim.\n"
    )
    return preamble + "\n\n" + SKILL_TEXT


def chat_system_blocks(course: str, course_dir: Path) -> list[dict[str, Any]]:
    """The chat call's system list, in cache-conscious order: first the big skill prompt
    (large, stable per course) carrying the cache breakpoint, then the volatile
    practice-state block WITHOUT cache_control — it rides behind the breakpoint, so new
    practice events never invalidate the cached prefix."""
    return [
        {
            "type": "text",
            "text": system_prompt_for(course),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": practice_state_block(course_dir),
        },
    ]


# --- Path safety -------------------------------------------------------------

def _within_root(real: Path) -> bool:
    root_real = Path(os.path.realpath(WORKSPACE_ROOT))
    return real == root_real or root_real in real.parents


def resolve_course_dir(slug: str, must_exist: bool = True) -> Path:
    if not COURSE_SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"invalid course slug: {slug!r}")
    if slug in RESERVED_DIRS:
        raise HTTPException(status_code=400, detail=f"reserved directory, not a course: {slug}")
    candidate = WORKSPACE_ROOT / slug
    real = Path(os.path.realpath(candidate))
    if not _within_root(real):
        raise HTTPException(status_code=400, detail="course path escapes workspace root")
    archive_real = Path(os.path.realpath(WORKSPACE_ROOT / ARCHIVE_DIR_NAME))
    if real == archive_real or archive_real in real.parents:
        raise HTTPException(status_code=400, detail="course path resolves into the archive")
    if must_exist and not real.is_dir():
        raise HTTPException(status_code=404, detail=f"course not found: {slug}")
    return real


def resolve_in_course(course_dir: Path, relative_path: str) -> Path:
    """Resolve a path relative to a course directory, rejecting anything that escapes WORKSPACE_ROOT."""
    candidate = course_dir / relative_path if relative_path else course_dir
    real = Path(os.path.realpath(candidate))
    if not _within_root(real):
        raise HTTPException(status_code=400, detail=f"path escapes workspace root: {relative_path!r}")
    return real


def _is_hidden(relative_path: str) -> bool:
    return any(part.startswith(".") for part in Path(relative_path).parts)


def learner_dir(course_dir: Path, create: bool = False) -> Path:
    """The one place a course's learner state lives: mission, notes, glossary, learning
    records, and the hidden logs and snapshots. Every read and write of learner state
    routes through here, so the course package around it stays portable. Readers leave
    create False — a course carrying no learner state yet simply reads as empty — while
    callers about to write pass create=True to have the directory made on demand."""
    path = Path(os.path.realpath(course_dir)) / LEARNER_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def read_course_manifest(course_dir: Path) -> dict[str, Any]:
    """The course package's manifest as a dict, or an empty dict when the course predates
    course.json or the file is unreadable. A missing manifest is not an error."""
    path = Path(os.path.realpath(course_dir)) / COURSE_MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def course_title(course_dir: Path, slug: str) -> str:
    """A course's display title: the manifest's, falling back to the de-slugified
    directory name so courses written before course.json still name themselves."""
    title = read_course_manifest(course_dir).get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return _prettify_slug(slug)


def _course_unit_label(manifest: dict[str, Any]) -> str:
    """The human word this course uses for its middle tier — "Part", "Domain", "Module",
    "Week". Absent or blank means the course has not named it, and it is a Unit."""
    label = manifest.get("unit_label")
    return label.strip() if isinstance(label, str) and label.strip() else DEFAULT_UNIT_LABEL


# --- Unit hues ---------------------------------------------------------------
#
# The one place a unit's identifying hue is decided. Every surface (sidebar, course
# overview, the generated review/weekly pages) reads this through the API's `color`
# field rather than re-deriving it, so no two surfaces can disagree and no stylesheet
# carries a second copy of the palette.
#
# Eight muted pigments on the chrome ground (--paper-chrome #f2f1ee), validated with the
# dataviz skill's checker (light mode, that surface, adjacent pairlist — the sidebar
# stacks units in one vertical order, so neighbours are what the eye compares):
# lightness band PASS, chroma floor PASS, CVD separation PASS (worst adjacent ΔE 14.4,
# protan), normal-vision floor PASS (worst adjacent ΔE 20.3), contrast vs surface PASS
# (all >= 3:1, the floor for a graphical object). Two exclusions shaped the set: the
# purple/indigo band (anti-slop) and everything within ΔE 15 of the vermilion accent
# family, because vermilion means "interactive" and must never read as unit identity.
#
# Hue identifies; it never ranks or rewards (charter P7). It is also never the only
# channel: every square sits beside the unit's own written label.
UNIT_COLORS = (
    "#02578b",  # 1 prussian
    "#ae7c02",  # 2 ochre
    "#455c01",  # 3 olive
    "#0098a5",  # 4 verdigris
    "#8b1e65",  # 5 wine
    "#489b52",  # 6 leaf
    "#486dd1",  # 7 lapis
    "#027c5c",  # 8 pine
)


def _unit_color(order: int) -> str:
    """The hue for a unit at this manifest `order`. Keyed to `order` and nothing else, so
    the assignment is stable: inserting a unit never repaints its siblings, and a filtered
    or partially loaded list shows every unit the colour it always had.

    A course with more than eight units wraps back to the first pigment. The dataviz
    skill's rule against cycling protects charts, where hue IS the identity channel and a
    repeat is a collapse; here every square is read next to the unit's own label, so hue is
    a redundant wayfinding aid and a repeat eight positions away costs nothing. The skill's
    alternative — folding the ninth into "Other" — has no meaning in navigation, where the
    ninth unit is a real place the learner has to be able to go."""
    if order < 1:
        return UNIT_COLORS[0]
    return UNIT_COLORS[(order - 1) % len(UNIT_COLORS)]


def _course_units(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The units a course declares, in manifest `order` (ties and missing orders fall back
    to declaration order), as {id, title, order, color}. Malformed entries are dropped
    rather than raising: a manifest typo costs that unit, never the course. A course
    declaring none returns an empty list, which is how every course written before this
    tier reads."""
    raw = manifest.get("units")
    if not isinstance(raw, list):
        return []
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        unit_id = entry.get("id")
        if not isinstance(unit_id, str) or not unit_id.strip() or unit_id.strip() in seen:
            continue
        unit_id = unit_id.strip()
        seen.add(unit_id)
        title = entry.get("title")
        order = entry.get("order")
        units.append(
            {
                "id": unit_id,
                "title": title.strip() if isinstance(title, str) and title.strip() else _prettify_slug(unit_id),
                "order": order if isinstance(order, int) and not isinstance(order, bool) else position + 1,
                "_position": position,
            }
        )
    units.sort(key=lambda unit: (unit["order"], unit["_position"]))
    for unit in units:
        del unit["_position"]
        unit["color"] = _unit_color(unit["order"])
    return units


# --- Course content parsing --------------------------------------------------

class _LessonHTMLParser(HTMLParser):
    """Collects a lesson document's <title>, first <h1>, declared unit, and every anchor's
    href + text, using only the stdlib parser — enough structure to name a lesson, place it
    in its unit, and derive its resources from what the HTML actually links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1 = ""
        self.unit = ""  # the unit id this lesson declares, "" when it declares none
        self.anchors: list[tuple[str, str]] = []  # (href, flattened anchor text)
        self._in_title = False
        self._in_first_h1 = False
        self._h1_done = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            # The lesson's own declaration of where it belongs; the manifest defines what
            # the ids mean. First declaration wins, so a stray duplicate cannot move a
            # lesson out from under the one its author wrote first.
            attr_map = dict(attrs)
            if attr_map.get("name") == LESSON_UNIT_META_NAME and not self.unit:
                self.unit = (attr_map.get("content") or "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "h1" and not self._h1_done:
            self._in_first_h1 = True
        elif tag == "a" and self._anchor_href is None:
            href = dict(attrs).get("href")
            if href:
                self._anchor_href = href
                self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._in_first_h1:
            self._in_first_h1 = False
            self._h1_done = True
        elif tag == "a" and self._anchor_href is not None:
            text = " ".join("".join(self._anchor_text).split())
            self.anchors.append((self._anchor_href, text))
            self._anchor_href = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_first_h1:
            self.h1 += data
        if self._anchor_href is not None:
            self._anchor_text.append(data)


def _parse_lesson_html(path: Path) -> _LessonHTMLParser:
    parser = _LessonHTMLParser()
    try:
        parser.feed(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        pass  # binary masquerading as .html — return whatever was collected (nothing)
    return parser


# Tags whose boundaries become line breaks in extracted lesson text, so reference material
# a grader reads keeps the document's own paragraphing instead of running together.
_TEXT_BLOCK_TAGS = frozenset(
    {
        "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "br", "hr", "section", "article",
        "header", "footer", "figure", "figcaption", "blockquote", "table", "tr", "td", "th",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }
)


def _flatten_lesson_text(raw: str) -> str:
    lines = (" ".join(line.split()) for line in raw.splitlines())
    return "\n".join(line for line in lines if line)


class _LessonTextParser(_LessonHTMLParser):
    """The lesson parser extended with readable-text extraction: everything the document
    renders, in document order, with <style> and non-quiz <script> contents dropped. The
    quiz-meta payloads are the deliberate exception — their canonical answers are content
    the learner was meant to have learned, so they belong in any reference the platform
    grades a recall against (the answer only; the rubric is grading machinery, not lesson
    content). Text under an element carrying data-concept is additionally collected per
    concept, so a concept-shaped reference can be built from exactly the blocks that
    claim it."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.by_concept: dict[str, list[str]] = {}
        self._skipping = False  # inside <style> or a non-quiz-meta <script>
        self._in_quiz_meta = False
        self._meta_chunks: list[str] = []
        # One frame per open data-concept element: [concept, tag, first chunk index,
        # depth of same-named tags opened inside it].
        self._concept_frames: list[list[Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        attr_map = dict(attrs)
        if tag in ("script", "style"):
            if tag == "script" and "quiz-meta" in (attr_map.get("class") or "").split():
                self._in_quiz_meta = True
                self._meta_chunks = []
            else:
                self._skipping = True
            return
        concept = (attr_map.get("data-concept") or "").strip()
        if concept:
            self._concept_frames.append([concept, tag, len(self.chunks), 0])
        elif self._concept_frames and tag == self._concept_frames[-1][1]:
            self._concept_frames[-1][3] += 1
        if tag in _TEXT_BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag in ("script", "style"):
            if self._in_quiz_meta:
                self._in_quiz_meta = False
                self._absorb_quiz_meta("".join(self._meta_chunks))
            self._skipping = False
            return
        if self._concept_frames and tag == self._concept_frames[-1][1]:
            frame = self._concept_frames[-1]
            if frame[3] > 0:
                frame[3] -= 1
            else:
                self._concept_frames.pop()
                text = _flatten_lesson_text("".join(self.chunks[frame[2]:]))
                if text:
                    self.by_concept.setdefault(frame[0], []).append(text)
        if tag in _TEXT_BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._in_quiz_meta:
            self._meta_chunks.append(data)
        elif not self._skipping:
            self.chunks.append(data)

    def _absorb_quiz_meta(self, raw: str) -> None:
        """A quiz item's canonical answer, rendered as a plain line of lesson text. A
        malformed payload contributes nothing rather than raising — the lesson still has
        its prose."""
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(meta, dict) and isinstance(meta.get("answer"), str):
            self.chunks.append(f"\nAnswer: {meta['answer']}\n")

    def text(self) -> str:
        return _flatten_lesson_text("".join(self.chunks))


def _lesson_texts(course_dir: Path) -> list[dict[str, Any]]:
    """Every lesson the course carries, parsed once into the shapes the Compose surface
    needs: {number, path, title, text, by_concept}. Lessons that cannot be read are
    skipped rather than failing the request."""
    lessons_dir = course_dir / "lessons"
    if not lessons_dir.is_dir():
        return []
    parsed: list[dict[str, Any]] = []
    for path in sorted(lessons_dir.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != ".html" or not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        parser = _LessonTextParser()
        parser.feed(raw)
        parsed.append(
            {
                "number": _numbered_prefix(path.name),
                "path": f"lessons/{path.name}",
                "title": _document_title(parser, path),
                "text": parser.text(),
                "by_concept": parser.by_concept,
            }
        )
    parsed.sort(key=lambda lesson: (lesson["number"], lesson["path"]))
    return parsed


def _prettify_slug(slug: str) -> str:
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def _numbered_prefix(name: str) -> int:
    match = NUMBERED_FILE_RE.match(name)
    return int(match.group(1)) if match else 0


def _document_title(parser: _LessonHTMLParser, path: Path) -> str:
    title = " ".join(parser.title.split())
    if title:
        return title
    h1 = " ".join(parser.h1.split())
    if h1:
        return h1
    stem = NUMBERED_FILE_RE.sub("", path.stem).lstrip("-_")
    return _prettify_slug(stem) or path.stem


def _derive_lesson_resources(
    parser: _LessonHTMLParser, lesson_path: Path, course_dir: Path
) -> list[dict[str, str]]:
    """A lesson's resources are exactly what its HTML links (the single source of truth):
    external http(s) anchors, plus local files in the course dir that are not other
    lessons, not assets, not learner state, and not the course-artifact nav links."""
    course_real = Path(os.path.realpath(course_dir))
    resources: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in parser.anchors:
        parts = urlsplit(href)
        if parts.scheme in ("http", "https"):
            title = text
            if not title or href in seen:
                continue
            seen.add(href)
            resources.append({"type": "external", "href": href, "title": title})
            continue
        if parts.scheme or not parts.path:
            continue  # mailto:, javascript:, fragment-only, etc.
        candidate = lesson_path.parent / unquote(parts.path)
        real = Path(os.path.realpath(candidate))
        if course_real not in real.parents or not real.is_file():
            continue
        rel = real.relative_to(course_real).as_posix()
        top = rel.split("/", 1)[0]
        if (
            _is_hidden(rel)
            or top in ("lessons", "assets", LEARNER_DIR_NAME)
            or rel in COURSE_ARTIFACTS
        ):
            continue
        if rel in seen:
            continue
        seen.add(rel)
        resources.append({"type": "file", "href": rel, "title": text or Path(rel).name})
    return resources


def _list_lessons(course_dir: Path) -> list[dict[str, Any]]:
    lessons_dir = course_dir / "lessons"
    if not lessons_dir.is_dir():
        return []
    lessons: list[dict[str, Any]] = []
    for path in sorted(lessons_dir.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != ".html" or not path.is_file():
            continue
        parser = _parse_lesson_html(path)
        lessons.append(
            {
                "number": _numbered_prefix(path.name),
                "path": f"lessons/{path.name}",
                "title": _document_title(parser, path),
                # The id the lesson declares, whether or not the manifest knows it. Grouping
                # resolves it against the declared units; an unknown or absent id is
                # unassigned, never an error.
                "unit": parser.unit or None,
                "resources": _derive_lesson_resources(parser, path, course_dir),
            }
        )
    lessons.sort(key=lambda lesson: (lesson["number"], lesson["path"]))
    return lessons


def _render_markdown_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return markdown_lib.markdown(path.read_text(encoding="utf-8"), extensions=MARKDOWN_EXTENSIONS)


def _list_learning_records(course_dir: Path) -> list[dict[str, Any]]:
    records_dir = learner_dir(course_dir) / LEARNING_RECORDS_DIR_NAME
    if not records_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != ".md" or not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        title = ""
        body_lines = lines
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                # The record's own heading becomes the display title; the body renders
                # without it so the heading isn't shown twice.
                title = stripped[2:].strip()
                body_lines = lines[:i] + lines[i + 1 :]
            break
        if not title:
            stem = NUMBERED_FILE_RE.sub("", path.stem).lstrip("-_")
            title = _prettify_slug(stem) or path.stem
        records.append(
            {
                "number": _numbered_prefix(path.name),
                "title": title,
                "html": markdown_lib.markdown("\n".join(body_lines), extensions=MARKDOWN_EXTENSIONS),
            }
        )
    records.sort(key=lambda record: record["number"])
    return records


def _list_reference_docs(course_dir: Path) -> list[dict[str, str]]:
    reference_dir = course_dir / "reference"
    if not reference_dir.is_dir():
        return []
    docs: list[dict[str, str]] = []
    for path in sorted(reference_dir.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != ".html" or not path.is_file():
            continue
        parser = _parse_lesson_html(path)
        docs.append({"path": f"reference/{path.name}", "title": _document_title(parser, path)})
    return docs


def _snapshot_state_file(course_dir: Path, path: Path, new_content: str) -> bool:
    """Preserve a learner-state snapshot file's current contents in the course's hidden
    state history before an overwrite replaces them (charter G13: the recorded history of
    what the learner knows must not be rewritable without trace). Applies only to the
    files named in SNAPSHOT_ON_OVERWRITE sitting directly in the learner directory, and
    only when the new content actually differs. Returns whether a snapshot was written."""
    learner_real = learner_dir(course_dir)
    if path.parent != learner_real or path.name not in SNAPSHOT_ON_OVERWRITE or not path.is_file():
        return False
    previous = path.read_bytes()
    if previous == new_content.encode("utf-8"):
        return False
    history_dir = learner_real / STATE_HISTORY_DIR_NAME
    history_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = history_dir / f"{path.stem}.{stamp}.md"
    counter = 2
    while snapshot.exists():
        snapshot = history_dir / f"{path.stem}.{stamp}-{counter}.md"
        counter += 1
    snapshot.write_bytes(previous)
    return True


# --- Claude tools (bound to one course directory per request) --------------

def make_tools(course_dir: Path) -> list[Any]:
    def _resolve(relative_path: str) -> Path:
        candidate = course_dir / relative_path if relative_path else course_dir
        real = Path(os.path.realpath(candidate))
        if not _within_root(real):
            raise ToolError(f"Path '{relative_path}' escapes the workspace root and is not allowed.")
        return real

    @beta_tool
    def read_file(relative_path: str) -> str:
        """Read the full text contents of a file in the current course's teaching workspace.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root.
                The course package sits at that root ("course.json", "RESOURCES.md",
                "lessons/0001-foo.html", "assets/lesson.css", "materials/syllabus.pdf");
                this learner's own state sits under learner/ ("learner/MISSION.md",
                "learner/NOTES.md", "learner/GLOSSARY.md",
                "learner/learning-records/0001-foo.md").
        """
        path = _resolve(relative_path)
        if not path.exists():
            raise ToolError(f"File not found: {relative_path}")
        if not path.is_file():
            raise ToolError(f"Not a file: {relative_path}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"File is not readable as UTF-8 text: {relative_path} ({exc})")

    def _record_files(records_dir: Path) -> list[Path]:
        if not records_dir.is_dir():
            return []
        return [
            p
            for p in sorted(records_dir.iterdir(), key=lambda p: p.name)
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".md"
        ]

    @beta_tool
    def write_file(relative_path: str, content: str) -> str:
        """Create or overwrite a text file in the current course's teaching workspace.
        Creates any missing parent directories automatically. Learning records are off
        limits here — create them with append_learning_record and mark outdated ones with
        supersede_learning_record instead. Overwriting learner/MISSION.md or
        learner/GLOSSARY.md automatically preserves the previous version in the course's
        state history.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root.
                The course package sits at that root ("lessons/0002-foo.html",
                "assets/lesson.css", "RESOURCES.md"); this learner's own state sits under
                learner/ ("learner/MISSION.md", "learner/NOTES.md",
                "learner/GLOSSARY.md").
            content: The full text content to write to the file.
        """
        path = _resolve(relative_path)
        records_real = _resolve(f"{LEARNER_DIR_NAME}/{LEARNING_RECORDS_DIR_NAME}")
        if path == records_real or records_real in path.parents:
            raise ToolError(
                "Files under learner/learning-records/ cannot be written with write_file. Use "
                "append_learning_record to create a new record, or supersede_learning_record "
                "to mark an outdated record superseded — existing records are never edited, "
                "overwritten, or deleted."
            )
        if _is_hidden(relative_path):
            raise ToolError(
                f"Path '{relative_path}' has a dot-path component. Hidden files are the "
                "platform's own logs and histories and cannot be written by tools; use a "
                "plain path relative to the course root (no '..' segments)."
            )
        snapshot_note = (
            "\nPrevious version preserved in the course's state history."
            if _snapshot_state_file(course_dir, path, content)
            else ""
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {relative_path}" + snapshot_note

    @beta_tool
    def append_learning_record(title: str, body: str) -> str:
        """Create the next sequentially numbered learning record in
        learner/learning-records/. The platform computes the number and filename — never
        pick or reuse one yourself.
        Records capture evidence-backed learning per LEARNING-RECORD-FORMAT.md: cite the
        evidence (a graded practice event, a user-authored artifact, a real-world report)
        in the body.

        Args:
            title: Short title of what was learned or established; becomes the record's
                heading and, slugified, part of its filename.
            body: The record body per LEARNING-RECORD-FORMAT.md — typically 1-3 sentences
                on what was learned and why it matters for future sessions, naming the
                evidence.
        """
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not slug:
            raise ToolError(
                "The record title must contain at least one letter or digit so it can be "
                "slugified into a filename."
            )
        records_dir = learner_dir(course_dir, create=True) / LEARNING_RECORDS_DIR_NAME
        records_dir.mkdir(exist_ok=True)
        highest = max((_numbered_prefix(p.name) for p in _record_files(records_dir)), default=0)
        filename = f"{highest + 1:04d}-{slug}.md"
        (records_dir / filename).write_text(
            f"# {title.strip()}\n\n{body.strip()}\n", encoding="utf-8"
        )
        return f"Created {LEARNER_DIR_NAME}/{LEARNING_RECORDS_DIR_NAME}/{filename}"

    @beta_tool
    def supersede_learning_record(record_number: int, superseded_by: int) -> str:
        """Mark an existing learning record as superseded by a later one, per
        LEARNING-RECORD-FORMAT.md: the old record gets `Status: superseded by LR-NNNN`
        frontmatter and is otherwise left byte-for-byte untouched — records are never
        edited, rewritten, or deleted. Use this when a later record corrects or deepens
        an earlier one.

        Args:
            record_number: The number of the outdated record (e.g. 3 for 0003-*.md).
            superseded_by: The number of the newer record that replaces it.
        """
        if record_number == superseded_by:
            raise ToolError(
                "A record cannot supersede itself — superseded_by must name the newer "
                "record that replaces it."
            )
        records_dir = learner_dir(course_dir) / LEARNING_RECORDS_DIR_NAME
        by_number = {_numbered_prefix(p.name): p for p in _record_files(records_dir)}
        target = by_number.get(record_number)
        if target is None:
            raise ToolError(
                f"No learning record numbered {record_number:04d} exists in "
                "learner/learning-records/ — use "
                'list_dir("learner/learning-records") to see what is there.'
            )
        if superseded_by not in by_number:
            raise ToolError(
                f"No learning record numbered {superseded_by:04d} exists in "
                "learner/learning-records/ — create the replacement record with "
                "append_learning_record first."
            )
        status_line = f"Status: superseded by LR-{superseded_by:04d}"
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines()
        closing = (
            next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
            if lines and lines[0].strip() == "---"
            else None
        )
        if closing is not None:
            # Existing frontmatter: replace its Status line, or add one if absent.
            for i in range(1, closing):
                if lines[i].lstrip().lower().startswith("status:"):
                    lines[i] = status_line
                    break
            else:
                lines.insert(1, status_line)
            new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        else:
            # No frontmatter (a lone unclosed --- is a rule, not frontmatter): insert a
            # minimal block above the title.
            new_text = f"---\n{status_line}\n---\n{text}"
        target.write_text(new_text, encoding="utf-8")
        return (
            f"Marked {LEARNER_DIR_NAME}/{LEARNING_RECORDS_DIR_NAME}/{target.name} as "
            f"superseded by LR-{superseded_by:04d}."
        )

    @beta_tool
    def list_dir(relative_path: str = "") -> str:
        """List the entries of a directory in the current course's teaching workspace, marking
        which entries are subdirectories with a trailing slash. Use this before creating a new
        file to check what already exists (e.g. whether lessons/ exists yet, and what the next
        number in a numbered sequence like lessons/0001-*.html should be).

        Args:
            relative_path: Path relative to the current course's teaching-workspace root.
                Empty string lists the workspace root itself, where the course package
                lives (lessons/, assets/, materials/, RESOURCES.md, course.json) beside
                learner/, which holds this learner's own state.
        """
        path = _resolve(relative_path)
        if not path.exists():
            return f"(does not exist yet: {relative_path or '.'})"
        if not path.is_dir():
            raise ToolError(f"Not a directory: {relative_path}")
        entries = sorted(path.iterdir(), key=lambda p: p.name)
        lines = [
            f"{entry.name}/" if entry.is_dir() else entry.name
            for entry in entries
            if not entry.name.startswith(".")
        ]
        return "\n".join(lines) if lines else "(empty directory)"

    return [read_file, write_file, list_dir, append_learning_record, supersede_learning_record]


# --- Conversation persistence -----------------------------------------------

def history_path_for(course_dir: Path) -> Path:
    return learner_dir(course_dir) / ".chat-history.json"


def load_history(course_dir: Path) -> list[dict[str, Any]]:
    path = history_path_for(course_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("messages", [])


def save_history(course_dir: Path, messages: list[dict[str, Any]]) -> None:
    path = learner_dir(course_dir, create=True) / history_path_for(course_dir).name
    path.write_text(json.dumps({"messages": messages}, indent=2, ensure_ascii=False), encoding="utf-8")


def block_to_jsonable(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json")
    return block  # already a plain dict (e.g. loaded from disk)


# --- FastAPI app -------------------------------------------------------------

app = FastAPI(title="keating")

client = anthropic.Anthropic()


class ChatRequest(BaseModel):
    course: str
    message: str
    attach_pdf: str | None = None


class NewCourseRequest(BaseModel):
    slug: str


class RenameCourseRequest(BaseModel):
    new_slug: str


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    course_dir = resolve_course_dir(req.course)
    messages = load_history(course_dir)

    user_content: list[dict[str, Any]] = []
    if req.attach_pdf:
        pdf_path = resolve_in_course(course_dir, req.attach_pdf)
        if _is_hidden(req.attach_pdf) or not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail=f"not a valid PDF in this course: {req.attach_pdf!r}")
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii").replace("\n", "")
        user_content.append(
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            }
        )
    user_content.append({"type": "text", "text": req.message})

    messages.append({"role": "user", "content": user_content})

    tools = make_tools(course_dir)
    system = chat_system_blocks(req.course, course_dir)

    runner = client.beta.messages.tool_runner(
        model=SETTINGS["chat_model"],
        max_tokens=MAX_TOKENS,
        tools=tools,
        messages=messages,
        system=system,
    )

    activity: list[dict[str, Any]] = []
    last = None
    try:
        for message in runner:
            last = message
            messages.append(
                {"role": "assistant", "content": [block_to_jsonable(b) for b in message.content]}
            )
            for block in message.content:
                if getattr(block, "type", None) == "tool_use":
                    activity.append({"name": block.name, "input": block.input})
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                messages.append(tool_response)
    finally:
        # Persist whatever happened this turn even if a later iteration raised.
        save_history(course_dir, messages)

    if last is None:
        raise HTTPException(status_code=502, detail="model returned no messages")

    reply_text = "".join(
        block.text for block in last.content if getattr(block, "type", None) == "text"
    )

    return {"reply": reply_text, "activity": activity}


# --- Settings endpoints -------------------------------------------------------

class LayoutSettingsPayload(BaseModel):
    remember_sizes: bool
    sidebar_w: int = Field(ge=SIDEBAR_W_MIN, le=SIDEBAR_W_MAX)
    chat_w: int = Field(ge=CHAT_W_MIN, le=CHAT_W_MAX)


class SettingsPayload(BaseModel):
    chat_model: str
    grading_model: str
    layout: LayoutSettingsPayload


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    """Current settings plus the static model catalog the UI renders its selects from."""
    return {**SETTINGS, "models": MODEL_CATALOG}


@app.put("/api/settings")
def put_settings(req: SettingsPayload) -> dict[str, Any]:
    """Validate, persist to settings.json, and update the in-memory dict — the chat and
    grading endpoints read SETTINGS at request time, so no restart is needed."""
    for field_name, value in (("chat_model", req.chat_model), ("grading_model", req.grading_model)):
        if value not in ALLOWED_MODEL_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown {field_name}: {value!r} (allowed: {sorted(ALLOWED_MODEL_IDS)})",
            )
    new_settings = {
        "chat_model": req.chat_model,
        "grading_model": req.grading_model,
        "layout": {
            "remember_sizes": req.layout.remember_sizes,
            "sidebar_w": req.layout.sidebar_w,
            "chat_w": req.layout.chat_w,
        },
    }
    _save_settings(new_settings)
    # Mutate in place: every reader references this module-level dict.
    SETTINGS.clear()
    SETTINGS.update(new_settings)
    return dict(SETTINGS)


# --- Attempt-gated retrieval (quiz grading + practice log) --------------------

GRADING_MAX_TOKENS = 2000
PRACTICE_LOG_NAME = ".practice-log.jsonl"

# The half of charter P16 that admits no per-surface variation: feedback evaluates the
# response, never the learner. Every grader the platform runs — quiz attempts, free
# recalls, glossary drafts — states this rule in exactly these words.
NO_PERSON_EVALUATION_RULE = """\
NEVER evaluate the person, in either direction. No praise and no criticism of the \
learner: no "great job", "well done", "you're close, smart thinking", "you clearly \
understand", "you struggled". Evaluate the response, not the person, in plain, neutral, \
specific language."""

# The four-part feedback grammar (criterion / task / process / self-regulation) comes from
# the platform charter's P16: high-information feedback, never person-level evaluation.
GRADING_SYSTEM_PROMPT = """\
You grade one retrieval-practice attempt for a learning platform. You are given the quiz \
question, the canonical answer, a grading rubric, the item type, and the learner's typed \
response. Judge the response ONLY against the rubric and the canonical answer — never \
against your own knowledge of the topic, and never reward or penalize anything the rubric \
does not name.

Verdict thresholds:
- "correct": every element the rubric requires is present in substance. Wording need not \
match — synonyms, paraphrase, and different ordering all count.
- "partially_correct": some but not all rubric-required elements are present in substance.
- "incorrect": no rubric-required element is present, or the response asserts a \
misconception the rubric flags.

Produce four feedback strings following this grammar, with these hard rules:
- criterion: one sentence stating what mastery of THIS concept looks like — the standard \
the item checks against.
- task: one to two sentences stating how THIS response relates to that criterion, citing \
something the learner actually wrote (quote or closely paraphrase their own words). Name \
what is present and what is missing or wrong — about the response only.
- process: one sentence naming the single most useful next strategy for this learner on \
this item (what to reread, contrast, or retrieve again — the one that matters most, \
never a list).
- self_regulation: one short self-monitoring question the learner can ask themselves.

""" + NO_PERSON_EVALUATION_RULE + """

If the item type is "pretest": this was an attempt made BEFORE the learner read the \
material. Open the task-level feedback by noting that this was a pre-reading attempt and \
that errors here actively help the upcoming reading stick. Grade the verdict by the same \
thresholds; adjust only the tone, treating errors as productive preparation rather than \
gaps.
"""


class AttemptRequest(BaseModel):
    course: str
    item_id: str
    concept: str
    lesson: str
    type: str
    cumulative: bool = False
    question: str
    response: str = ""
    confidence: int = Field(ge=1, le=4)
    latency_ms: int | None = None
    gave_up: bool = False
    answer: str
    rubric: str
    # Which surface the attempt was made from, derived by quiz.js from the document's own
    # URL. It distinguishes a first-encounter attempt in a lesson from a re-test in one of
    # the review loops, and "weekly" is what makes an attempt count as genuine engagement
    # with a weekly session. Defaults to "lesson" so any older client stays valid.
    source: Literal["lesson", "review", "weekly"] = "lesson"


class GradedAttempt(BaseModel):
    """Structured output the grading model must produce: a verdict plus the four
    feedback strings of the criterion/task/process/self-regulation grammar."""

    verdict: Literal["correct", "partially_correct", "incorrect"]
    criterion: str
    task: str
    process: str
    self_regulation: str


def _first_sentence(text: str) -> str:
    flattened = " ".join(text.split())
    match = re.search(r"[.!?](?=\s|$)", flattened)
    return flattened[: match.end()] if match else flattened


def _append_practice_event(course_dir: Path, entry: dict[str, Any]) -> None:
    """One JSON line per retrieval event, appended to the course's practice log — the
    platform's single highest-leverage data structure (scheduling, ZPD, calibration, and
    mastery all read from it later). Append-only; nothing ever rewrites this file. Every
    surface that produces a retrieval event writes through here, so the log has one
    schema and one writer."""
    with (learner_dir(course_dir, create=True) / PRACTICE_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_practice_event(course_dir: Path, req: AttemptRequest, verdict: str) -> None:
    """Log one graded quiz attempt as a practice event."""
    _append_practice_event(
        course_dir,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "item_id": req.item_id,
            "concept": req.concept,
            "lesson": req.lesson,
            "type": req.type,
            "cumulative": req.cumulative,
            "response": req.response,
            "verdict": verdict,
            "confidence": req.confidence,
            "latency_ms": req.latency_ms,
            "gave_up": req.gave_up,
            "source": req.source,
        },
    )


def _grade_with_model(system: str, prompt: str, output_format: type[Any], max_tokens: int) -> Any:
    """One structured grading call against SETTINGS["grading_model"], with the credential
    and API failure modes mapped to 502s the UI can show. Shared by every grader the
    platform runs so they fail identically."""
    try:
        graded = client.messages.parse(
            model=SETTINGS["grading_model"],
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
        )
    except anthropic.AuthenticationError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Anthropic authentication failed — is an API key configured? ({exc.message})",
        )
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"grading model call failed: {exc}")
    except TypeError as exc:
        # The SDK raises TypeError when it cannot resolve any credential source at all
        # (no ANTHROPIC_API_KEY, no auth token, no stored profile).
        raise HTTPException(
            status_code=502,
            detail=f"Anthropic client could not authenticate — is an API key configured? ({exc})",
        )
    result = graded.parsed_output
    if result is None:
        raise HTTPException(
            status_code=502, detail="grading model returned no parseable verdict"
        )
    return result


def _grade_attempt(req: AttemptRequest) -> GradedAttempt:
    prompt = (
        f"Item type: {req.type}\n"
        f"Concept: {req.concept}\n\n"
        f"Question:\n{req.question}\n\n"
        f"Canonical answer:\n{req.answer}\n\n"
        f"Rubric:\n{req.rubric}\n\n"
        f"Learner's response:\n{req.response}"
    )
    return _grade_with_model(GRADING_SYSTEM_PROMPT, prompt, GradedAttempt, GRADING_MAX_TOKENS)


# --- Practice-log aggregation (the platform's data substrate) -----------------

# Verdict order is load-bearing: the calibration matrix's columns follow it, and the
# frontend renders Correct / Partial / Incorrect from the first three positions.
PRACTICE_VERDICTS = ("correct", "partially_correct", "incorrect", "not_attempted")

# The ZPD system block lists at most this many items (most recently practiced win) so a
# long-lived course can't balloon the per-turn uncached suffix.
PRACTICE_BLOCK_MAX_ITEMS = 40


def _read_practice_events(course_dir: Path) -> list[dict[str, Any]]:
    """Parse the course's append-only practice log, skipping malformed lines defensively:
    a bad line (interrupted write, hand-edit, schema drift) costs that line only, never
    the whole aggregate."""
    path = learner_dir(course_dir) / PRACTICE_LOG_NAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        ts = entry.get("ts")
        verdict = entry.get("verdict")
        confidence = entry.get("confidence")
        if not (isinstance(item_id, str) and item_id and isinstance(ts, str) and ts):
            continue
        if verdict not in PRACTICE_VERDICTS:
            continue
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 4:
            continue
        latency = entry.get("latency_ms")
        events.append(
            {
                "ts": ts,
                "item_id": item_id,
                "concept": entry.get("concept") if isinstance(entry.get("concept"), str) else "",
                "lesson": entry.get("lesson") if isinstance(entry.get("lesson"), str) else "",
                "type": entry.get("type") if isinstance(entry.get("type"), str) else "",
                "cumulative": bool(entry.get("cumulative")),
                "verdict": verdict,
                "confidence": confidence,
                "latency_ms": latency if isinstance(latency, int) and not isinstance(latency, bool) else None,
                "gave_up": bool(entry.get("gave_up")),
            }
        )
    # The log is chronological by construction (append-only), but a sort keeps the
    # aggregate honest against merged or hand-repaired files. ISO-8601 UTC strings
    # sort correctly as text.
    events.sort(key=lambda e: e["ts"])
    return events


# --- Daily review due-item selection ("learned today, verified tomorrow") ----

# At most this many items make a day's review session; anything past the cap simply
# stays due — no stacking, no backlog display (charter P5: reschedule forward, never
# collapse missed reviews into one sitting).
DUE_CAP = 8

# Verdicts that mean the item's last outcome was a miss: it comes back as a spaced
# retrieval event requiring a re-answer (charter P4), never a dismissible banner.
DUE_MISS_VERDICTS = ("incorrect", "partially_correct", "not_attempted")


def _event_local_date(ts: str) -> date | None:
    """The server-local calendar date of a practice event. The log stores UTC
    timestamps; due-ness is defined over the learner's calendar days, so the boundary
    that matters is local midnight, not UTC midnight."""
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().date()


def _item_histories(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Parsed practice events collapsed to one record per item id: {item_id, first_date,
    correct_dates, concept, lesson, last_ts, last_date, last_verdict}. Events whose
    timestamp will not parse contribute nothing. Latest event's metadata wins, mirroring
    _aggregate_practice. The single place the log becomes per-item history, so due
    selection and the unit rollups read the same facts."""
    by_item: dict[str, dict[str, Any]] = {}
    for event in events:
        event_date = _event_local_date(event["ts"])
        if event_date is None:
            continue
        item = by_item.setdefault(
            event["item_id"],
            {
                "item_id": event["item_id"],
                "first_date": event_date,
                "correct_dates": [],
            },
        )
        item["concept"] = event["concept"]
        item["lesson"] = event["lesson"]
        item["last_ts"] = event["ts"]
        item["last_date"] = event_date
        item["last_verdict"] = event["verdict"]
        if event["verdict"] == "correct":
            item["correct_dates"].append(event_date)
    return by_item


def _item_verified(history: dict[str, Any]) -> bool:
    """True when some correct recall landed on a later local day than the item's first
    attempt — one night of sleep between exposure and the answer. This is exactly the
    condition on which _compute_due rests an item, and the condition the per-unit rollup
    counts as `verified`; the two must never drift apart."""
    return any(day > history["first_date"] for day in history["correct_dates"])


def _compute_due(
    events: list[dict[str, Any]],
    as_of: date | None = None,
    presentable: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Select the items due for verification today, as pure function over parsed
    practice events. An item is due iff its last attempt was on a previous local
    calendar day (one night of sleep between exposure and verification is absolute)
    AND either (a) its latest verdict is a miss coming back, or (b) every correct
    verdict it has ever received happened on the same local day as its first-ever
    attempt — learned and answered same-day, still unverified across a night. An item
    with a correct on a later day than its first attempt is verified and not due (the
    weekly loop owns it later). Returns at most DUE_CAP items, oldest-last-practiced
    first, as {item_id, concept, lesson, reason ("miss"|"unverified"), last_ts}.

    `presentable`, when given, restricts the selection to item ids a lesson can still
    present (log-only ids — test artifacts, renamed/removed items — are unreviewable
    and must not be counted anywhere), and is applied before the cap so those ids
    never occupy a session slot a presentable item could fill.

    as_of overrides "today" (server-local) — a dev/testing hook, never set by the UI."""
    today = as_of or datetime.now().astimezone().date()

    by_item = _item_histories(events)

    due: list[dict[str, Any]] = []
    for item in by_item.values():
        if presentable is not None and item["item_id"] not in presentable:
            continue
        if item["last_date"] >= today:
            continue  # last attempted today (or later): never due — the one-night rule
        if item["last_verdict"] in DUE_MISS_VERDICTS:
            reason = "miss"
        elif not _item_verified(item):
            reason = "unverified"
        else:
            continue  # verified: a correct recall on a later day than first exposure
        due.append(
            {
                "item_id": item["item_id"],
                "concept": item["concept"],
                "lesson": item["lesson"],
                "reason": reason,
                "last_ts": item["last_ts"],
            }
        )

    due.sort(key=lambda item: item["last_ts"])  # oldest-last-practiced first
    return due[:DUE_CAP]


def _aggregate_practice(course_dir: Path) -> dict[str, Any]:
    """The practice log rolled up three ways: per-item attempt histories (lesson-then-item
    order), one summary, and the confidence-by-verdict calibration matrix. A high-confidence
    miss is an *incorrect* verdict at confidence >= 3 — the hypercorrection signal (charter
    P13), deliberately not counting partial credit."""
    events = _read_practice_events(course_dir)
    # Restricting to presentable ids keeps the sidebar due count and the teaching
    # agent's due line equal to what the review page actually shows.
    due = _compute_due(events, presentable=set(_lesson_quiz_index(course_dir)))
    due_today = {"count": len(due), "item_ids": [item["item_id"] for item in due]}
    if not events:
        return {"items": [], "summary": None, "calibration": None, "due_today": due_today}

    by_item: dict[str, dict[str, Any]] = {}
    matrix = [[0, 0, 0, 0] for _ in range(4)]  # [confidence-1][PRACTICE_VERDICTS index]
    gave_ups = 0
    high_confidence_misses = 0

    for event in events:
        item = by_item.setdefault(
            event["item_id"],
            {
                "item_id": event["item_id"],
                "concept": "",
                "lesson": "",
                "type": "",
                "cumulative": False,
                "attempts": [],
                "last_ts": "",
                "high_confidence_miss": False,
            },
        )
        # Latest event's metadata wins: if an item's concept wording or lesson home is
        # ever corrected, the aggregate reflects the current truth.
        item["concept"] = event["concept"]
        item["lesson"] = event["lesson"]
        item["type"] = event["type"]
        item["cumulative"] = event["cumulative"]
        item["attempts"].append(
            {
                "ts": event["ts"],
                "verdict": event["verdict"],
                "confidence": event["confidence"],
                "latency_ms": event["latency_ms"],
                "gave_up": event["gave_up"],
            }
        )
        item["last_ts"] = event["ts"]
        if event["confidence"] >= 3 and event["verdict"] == "incorrect":
            item["high_confidence_miss"] = True
            high_confidence_misses += 1
        if event["gave_up"]:
            gave_ups += 1
        matrix[event["confidence"] - 1][PRACTICE_VERDICTS.index(event["verdict"])] += 1

    items = sorted(by_item.values(), key=lambda i: (i["lesson"], i["item_id"]))
    return {
        "items": items,
        "due_today": due_today,
        "summary": {
            "total_attempts": len(events),
            "distinct_items": len(items),
            "gave_ups": gave_ups,
            "high_confidence_misses": high_confidence_misses,
        },
        "calibration": {
            "verdicts": list(PRACTICE_VERDICTS),
            "matrix": matrix,
            "totals": [sum(row) for row in matrix],
        },
    }


@app.get("/api/practice")
def get_practice(course: str) -> dict[str, Any]:
    """Aggregated practice state for a course, straight from its .practice-log.jsonl:
    per-item attempt histories, a summary, the confidence-vs-verdict calibration
    matrix, due_today ({count, item_ids} — the daily-review selection, computed from the
    same events), and weekly ({due, last_session_ts, eligible_count} — the weekly loop's
    cadence and delayed-check selection, so the sidebar renders both review lines from one
    fetch). An empty or absent log returns {items: [], summary: null, calibration: null,
    due_today: {count: 0, item_ids: []}} plus the weekly block."""
    course_dir = resolve_course_dir(course)
    data = _aggregate_practice(course_dir)
    data["weekly"] = _weekly_state_payload(course_dir)
    return data


def practice_state_block(course_dir: Path) -> str:
    """The compact practice-state text injected into the teaching agent's context each
    turn: one deterministic line per item, so ZPD estimation and learning records rest on
    citable retrieval evidence instead of conversation impressions."""
    header = (
        "Current practice-log state for this course — this is the citable evidence base "
        "for ZPD estimation and learning records (see TEACHING-POLICY.md: records require "
        "citable evidence):"
    )
    data = _aggregate_practice(course_dir)
    due_today = data["due_today"]
    if due_today["count"]:
        due_text = (
            f"Due for verification today ({due_today['count']}): "
            + ", ".join(due_today["item_ids"])
            + "\nWhen items are due and the learner starts a session, open by directing "
            "them to Today's review (the sidebar Practice section) before new material "
            "or new lessons."
        )
    else:
        due_text = "Nothing is due for verification today."
    items = data["items"]
    if not items:
        return (
            header
            + "\n"
            + due_text
            + "\nNo practice events have been logged for this course yet."
        )

    truncated_note = ""
    if len(items) > PRACTICE_BLOCK_MAX_ITEMS:
        keep_ids = {
            item["item_id"]
            for item in sorted(items, key=lambda i: i["last_ts"], reverse=True)[
                :PRACTICE_BLOCK_MAX_ITEMS
            ]
        }
        omitted = len(items) - PRACTICE_BLOCK_MAX_ITEMS
        items = [item for item in items if item["item_id"] in keep_ids]
        truncated_note = (
            f"\n({omitted} less recently practiced item{'s' if omitted != 1 else ''} "
            f"omitted — only the {PRACTICE_BLOCK_MAX_ITEMS} most recently practiced are listed.)"
        )

    lines = []
    for item in items:
        attempts = item["attempts"]
        last = attempts[-1]
        count = len(attempts)
        line = (
            f"{item['item_id']} ({item['concept']}, lesson {item['lesson']}): "
            f"{count} attempt{'s' if count != 1 else ''}, "
            f"last {last['verdict']} at {item['last_ts'][:10]}"
        )
        item_gave_ups = sum(1 for a in attempts if a["gave_up"])
        if item_gave_ups:
            line += f", {item_gave_ups} gave-up{'s' if item_gave_ups != 1 else ''}"
        if item["high_confidence_miss"]:
            line += ", confidence-was-high-on-miss"
        lines.append(line)
    return (
        header
        + "\n"
        + due_text
        + "\n"
        + _weekly_state_line(course_dir)
        + "\n"
        + "\n".join(lines)
        + truncated_note
    )


@app.post("/api/attempt")
def attempt(req: AttemptRequest) -> dict[str, Any]:
    """Grade one committed retrieval attempt against the item's rubric and log it as a
    practice event. Give-ups skip the model call but are still answered (the canonical
    answer always shows after an attempt) and still logged.

    An attempt whose source is "weekly" is the first of the two engagement signals that
    make a weekly session count as held — the learner did the delayed check, which is the
    session's substance."""
    course_dir = resolve_course_dir(req.course)

    if req.gave_up:
        feedback = {
            "criterion": _first_sentence(req.rubric)
            or "Mastery here means being able to state this concept accurately, from memory, in your own words.",
            "task": "No attempt was made this time.",
            "process": "Reread the relevant section, then return to this item in review.",
            "self_regulation": "What made this one hard to start — the concept, or the cue?",
        }
        _log_practice_event(course_dir, req, "not_attempted")
        _record_weekly_engagement(course_dir, req.source)
        return {"verdict": "not_attempted", "answer": req.answer, "feedback": feedback}

    graded = _grade_attempt(req)
    _log_practice_event(course_dir, req, graded.verdict)
    _record_weekly_engagement(course_dir, req.source)
    return {
        "verdict": graded.verdict,
        "answer": req.answer,
        "feedback": {
            "criterion": graded.criterion,
            "task": graded.task,
            "process": graded.process,
            "self_regulation": graded.self_regulation,
        },
    }


# --- Daily review page (GET /review/{course}) --------------------------------

class _QuizItemExtractor(HTMLParser):
    """Locates each .quiz-item div's exact character span in a lesson document so the
    review page can carry the authored block over verbatim — attributes, .quiz-q, and
    the quiz-meta script untouched. The lesson files stay the single source of truth
    for question, answer, and rubric; nothing is ever re-authored here."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.items: list[tuple[str, int, int]] = []  # (item_id, start offset, end offset)
        self._open: list[Any] | None = None  # [item_id, start offset, div depth]
        self._line_starts = [0]
        for line in raw.splitlines(keepends=True):
            self._line_starts.append(self._line_starts[-1] + len(line))

    def _offset(self) -> int:
        lineno, column = self.getpos()  # lineno is 1-based
        return self._line_starts[lineno - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._open is not None:
            if tag == "div":
                self._open[2] += 1
            return
        if tag != "div":
            return
        attr_map = dict(attrs)
        if "quiz-item" not in (attr_map.get("class") or "").split():
            return
        self._open = [attr_map.get("data-item-id") or "", self._offset(), 1]

    def handle_endtag(self, tag: str) -> None:
        if self._open is None or tag != "div":
            return
        self._open[2] -= 1
        if self._open[2] == 0:
            # getpos() points at the "<" of this closing tag; the block ends at its ">".
            end = self.raw.find(">", self._offset())
            if end != -1:
                self.items.append((self._open[0], self._open[1], end + 1))
            self._open = None


# The per-item source line's unit mark, shared by the review and weekly pages. These pages
# are chrome wrapped around lesson content: the source line orients the learner ("which unit
# is this from?"), so it is allowed the unit hue, while the quiz block beneath it stays
# exactly the calm reading surface it is inside a lesson. The hue rides one 9px square — the
# same glyph the sidebar uses — never the line's text, which keeps its secondary ink.
SOURCE_MARK_CSS = """
.unit-mark {
  display: inline-block;
  box-sizing: border-box;
  width: 9px;
  height: 9px;
  margin-right: 0.5rem;
  border-radius: 1px;
  background: var(--unit-hue, transparent);
}
"""


def _lesson_unit_colors(course_dir: Path) -> dict[int, str]:
    """{1: "#02578b", …} — each lesson number's unit hue, for courses that declare units.
    Lessons in no declared unit are absent, and their source lines simply carry no mark."""
    colors = {unit["id"]: unit["color"] for unit in _course_units(read_course_manifest(course_dir))}
    return {
        lesson["number"]: colors[lesson["unit"]]
        for lesson in _list_lessons(course_dir)
        if lesson["unit"] in colors
    }


def _source_line(css_class: str, block: dict[str, Any], colors: dict[int, str]) -> str:
    """"From Lesson 03 · Karma and rebirth", opened by the unit's hue square where the
    lesson belongs to a declared unit."""
    color = colors.get(block["lesson_number"])
    mark = f'<span class="unit-mark" style="--unit-hue: {color}"></span>' if color else ""
    return (
        f'<p class="{css_class}">{mark}'
        f"From Lesson {block['lesson_number']:02d} &middot; "
        f'{html_escape(block["lesson_title"])}</p>'
    )


_REVIEW_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Same standalone-page pattern as the reader endpoint, but styled by the course's own
# lesson stylesheet so the carried-over quiz items render exactly as they do in lessons.
# The one addition is the per-item source line (.review-source).
REVIEW_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Today's review</title>
<link rel="stylesheet" href="/workspace/${course}/assets/lesson.css">
<style>
.review-source {
  font-family: var(--font-display, sans-serif);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink-secondary, #44423d);
  margin: 1.75rem 0 0.35rem;
}
.review-source + .quiz-item { margin-top: 0; }
${source_mark_css}
</style>
</head>
<body>
<article class="lesson">

<p class="eyebrow">Today's review &middot; ${date_line}</p>
<h1>Today's review</h1>
${body}
</article>
<script src="/static/quiz.js" defer></script>
</body>
</html>
""")


def _review_intro_sentence(blocks: list[dict[str, Any]], due: list[dict[str, Any]]) -> str:
    """Plain factual intro (charter P7 — no encouragement theater): item count, the
    miss/verification split with zero clauses omitted, and what one attempt buys."""
    presented = {block["item_id"] for block in blocks}
    misses = sum(1 for item in due if item["item_id"] in presented and item["reason"] == "miss")
    unverified = len(presented) - misses
    total = len(presented)
    clauses = []
    if misses:
        clauses.append(f"{misses} miss{'es' if misses != 1 else ''} returning")
    if unverified:
        clauses.append(f"{unverified} first verification{'s' if unverified != 1 else ''}")
    return (
        f"{total} item{'s' if total != 1 else ''} due: {', '.join(clauses)}. "
        "One attempt each; the answer and feedback follow each attempt."
    )


@app.get("/review/{course}")
def review_page(course: str, as_of: str | None = None) -> Response:
    """The daily review session ("learned today, verified tomorrow") as a standalone
    generated page for the preview iframe: the due items' authored quiz blocks carried
    over verbatim from their source lessons, run through the same attempt-gated quiz.js
    machinery lessons use — attempts land in /api/attempt and the practice log exactly
    as lesson attempts do. ?as_of=YYYY-MM-DD overrides "today" for dev/testing only;
    the UI never sends it."""
    course_dir = resolve_course_dir(course)
    if as_of is not None:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid as_of date: {as_of!r}")
    else:
        as_of_date = None

    events = _read_practice_events(course_dir)
    index = _lesson_quiz_index(course_dir)
    due = _compute_due(events, as_of=as_of_date, presentable=set(index))
    blocks = [index[item["item_id"]] for item in due]

    shown_date = as_of_date or datetime.now().astimezone().date()
    date_line = f"{_REVIEW_MONTHS[shown_date.month - 1]} {shown_date.day}"

    if not blocks:
        body = (
            '<p class="review-intro">Nothing due today. '
            "New material practiced today becomes due tomorrow.</p>"
        )
    else:
        parts = [f'<p class="review-intro">{html_escape(_review_intro_sentence(blocks, due))}</p>']
        colors = _lesson_unit_colors(course_dir)
        for block in blocks:
            parts.append(_source_line("review-source", block, colors))
            parts.append(block["block"])
        body = "\n\n".join(parts)

    page = REVIEW_PAGE_TEMPLATE.substitute(
        course=html_escape(course, quote=True),
        date_line=html_escape(date_line),
        body=body,
        source_mark_css=SOURCE_MARK_CSS,
    )
    return Response(content=page, media_type="text/html")


# --- Weekly review loop (GET /weekly/{course}) --------------------------------

# The delay that turns a re-test into a genuine delayed unassisted assessment (charter
# P19): an item becomes eligible once this many local calendar days have passed since its
# last attempt. The daily loop owns the one-night horizon and rests items it counts
# verified; the weekly loop owns the first real delay, and re-testing the verified ones is
# precisely its job — storage strength decays unobserved otherwise.
WEEKLY_DELAY_DAYS = 3

# At most this many items make one weekly session. Anything past the cap simply stays
# eligible — the same no-stacking rule as the daily cap (charter P5): reviews reschedule
# forward, they never collapse into one sitting, and no backlog is ever displayed.
WEEKLY_CAP = 10

# A weekly session is due when none has been held within this many local days.
WEEKLY_CADENCE_DAYS = 7

# Cadence record: one line per weekly session the learner actually engaged with. Serving
# the page writes nothing — a preview, a stray click, or a curl must never mark a week
# done. Only the two engagement paths append (see _log_weekly_session).
WEEKLY_LOG_NAME = ".weekly-log.jsonl"

# Below this many graded attempts the calibration section says nothing trustworthy, so it
# is omitted entirely rather than shown thin — the same bar the Practice page applies.
WEEKLY_CALIBRATION_MIN_ATTEMPTS = 5

# The confidence ladder as the learner saw it at attempt time (quiz.js's own labels),
# lowercased for use inside a sentence.
WEEKLY_CONFIDENCE_LABELS = ("guessing", "unsure", "fairly sure", "certain")

# The MISSION.md heading whose bullets the mission check reads back (charter P21). Matched
# case-insensitively on the heading text alone, so the level of the heading can change.
MISSION_SUCCESS_HEADING = "success looks like"

_MISSION_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_MISSION_BULLET_RE = re.compile(r"^\s{0,3}[-*+]\s+\S")

# Small counts read as words in running prose; the eligibility rule states its own delay,
# so the sentence and the constant can never drift apart.
_NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _number_word(value: int) -> str:
    return _NUMBER_WORDS[value] if 0 <= value < len(_NUMBER_WORDS) else str(value)


def _lesson_quiz_index(course_dir: Path) -> dict[str, dict[str, Any]]:
    """Every authored `.quiz-item` block the course's lessons currently carry, keyed by
    item id: {item_id, block (raw HTML), lesson_number, lesson_title}. The lesson files
    stay the single source of truth for question, answer, and rubric — both review pages
    present blocks straight from this index, and both selections filter through its keys,
    because an item id no lesson carries any more (renamed, removed, a test artifact) is
    unpresentable and must not be counted anywhere. First lesson in filename order wins a
    duplicated id."""
    index: dict[str, dict[str, Any]] = {}
    lessons_dir = course_dir / "lessons"
    if not lessons_dir.is_dir():
        return index
    for path in sorted(lessons_dir.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != ".html" or not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        extractor = _QuizItemExtractor(raw)
        extractor.feed(raw)
        hits = [entry for entry in extractor.items if entry[0] and entry[0] not in index]
        if not hits:
            continue
        doc = _LessonHTMLParser()
        doc.feed(raw)
        title = _document_title(doc, path)
        number = _numbered_prefix(path.name)
        for item_id, start, end in hits:
            index[item_id] = {
                "item_id": item_id,
                "block": raw[start:end],
                "lesson_number": number,
                "lesson_title": title,
            }
    return index


def _interleave_by_lesson(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin a selection across its lessons so consecutive items come from different
    lessons wherever the mix allows, preserving each lesson's own ordering. Blocked
    practice suppresses exactly the cross-tradition discrimination this course is made of
    (charter P12); a session that runs 0001, 0001, 0002 becomes 0001, 0002, 0001."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(item["lesson"], []).append(item)
    # dict insertion order is the order the lessons first appear in the incoming list, so
    # the longest-since-practiced item still leads the session.
    order = list(groups)
    out: list[dict[str, Any]] = []
    while len(out) < len(items):
        for lesson in order:
            if groups[lesson]:
                out.append(groups[lesson].pop(0))
    return out


def _interleave_by_unit(
    items: list[dict[str, Any]], units_by_lesson: dict[str, str]
) -> list[dict[str, Any]]:
    """The same round-robin one tier up: consecutive items come from different units where
    the mix allows, and lessons alternate inside each unit. The unit is the course's own
    notion of confusable neighborhood — a syllabus Part, an exam Domain — so alternating
    across units puts the widest real discrimination between adjacent items (charter P12),
    while the inner lesson round-robin keeps a run that sits inside one unit from
    collapsing back into blocked practice. A course with no unit data has one group and
    degrades exactly to _interleave_by_lesson.

    `units_by_lesson` maps a practice event's lesson id (the log's zero-padded "0001") to a
    unit id; lessons the map does not name share the unassigned group."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        unit = units_by_lesson.get(str(item.get("lesson") or "").zfill(4), "")
        groups.setdefault(unit, []).append(item)
    # dict insertion order is the order the units first appear in the incoming list, so the
    # longest-since-practiced item still leads the session.
    queues = {unit: _interleave_by_lesson(group) for unit, group in groups.items()}
    order = list(queues)
    out: list[dict[str, Any]] = []
    while len(out) < len(items):
        for unit in order:
            if queues[unit]:
                out.append(queues[unit].pop(0))
    return out


def _lesson_unit_map(course_dir: Path) -> dict[str, str]:
    """{"0001": "part-i", …} — each lesson's declared unit keyed the way the practice log
    writes lesson ids, restricted to units the manifest actually declares. A lesson
    declaring an unknown or no unit is simply absent, which reads as unassigned."""
    declared = {unit["id"] for unit in _course_units(read_course_manifest(course_dir))}
    return {
        f"{lesson['number']:04d}": lesson["unit"]
        for lesson in _list_lessons(course_dir)
        if lesson["unit"] in declared
    }


def _compute_weekly(
    events: list[dict[str, Any]],
    as_of: date | None = None,
    presentable: set[str] | None = None,
    units_by_lesson: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Select the items for a weekly session's delayed check, as a pure function over
    parsed practice events. An item is eligible iff its last attempt was at least
    WEEKLY_DELAY_DAYS local calendar days ago — the platform's first genuinely delayed
    unassisted check (charter P19), at a horizon the daily loop cannot reach. Verification
    status is deliberately ignored: items the daily loop rests as verified are exactly what
    the weekly loop exists to re-test.

    Ordering is longest-since-practiced first, capped at WEEKLY_CAP, then round-robined
    across units and, inside each unit, across lessons (charter P12). `presentable`, when
    given, restricts candidates to item ids a lesson can still present, and is applied
    before the cap so a session is capped at items actually shown rather than at log
    entries. `units_by_lesson`, when given, supplies the course's unit structure; without
    it the round-robin is the lesson-level one alone.

    as_of overrides "today" (server-local) — a dev/testing hook, never set by the UI.
    Returns {item_id, concept, lesson, last_ts, days_since}."""
    today = as_of or datetime.now().astimezone().date()

    by_item = _item_histories(events)

    eligible: list[dict[str, Any]] = []
    for item in by_item.values():
        if presentable is not None and item["item_id"] not in presentable:
            continue
        days_since = (today - item["last_date"]).days
        if days_since < WEEKLY_DELAY_DAYS:
            continue
        eligible.append(
            {
                "item_id": item["item_id"],
                "concept": item["concept"],
                "lesson": item["lesson"],
                "last_ts": item["last_ts"],
                "days_since": days_since,
            }
        )

    eligible.sort(key=lambda item: item["last_ts"])  # longest-since-practiced first
    return _interleave_by_unit(eligible[:WEEKLY_CAP], units_by_lesson or {})


def _read_weekly_sessions(course_dir: Path) -> list[dict[str, Any]]:
    """The course's weekly-session cadence log, malformed lines skipped defensively (a bad
    line costs that line only, never the cadence)."""
    path = learner_dir(course_dir) / WEEKLY_LOG_NAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    sessions: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("ts"), str) and entry["ts"]:
            sessions.append(entry)
    sessions.sort(key=lambda entry: entry["ts"])
    return sessions


def _log_weekly_session(
    course_dir: Path,
    trigger: str,
    items_presented: int | None,
    as_of: date,
) -> bool:
    """Record that a weekly session was genuinely engaged with, idempotently for the local
    calendar day: if the log already carries an entry whose timestamp falls on today's
    local date, nothing is written and False comes back. That is the whole duplicate guard
    — the two engagement paths (an attempt submitted from the weekly page, the explicit
    "mark held" button) can both fire in one sitting, and a session is a day's worth of
    work either way. Append-only; nothing rewrites this file.

    `trigger` is "attempt" or "manual", so the two paths stay distinguishable after the
    fact. `items_presented` is the count the page presented when the session was served;
    the attempt path does not know it (the attempt arrives long after the render, from a
    document the server no longer holds) and passes None."""
    today = as_of
    for entry in _read_weekly_sessions(course_dir):
        if _event_local_date(entry["ts"]) == today:
            return False
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "items_presented": items_presented,
        "as_of": as_of.isoformat(),
        "trigger": trigger,
    }
    with (learner_dir(course_dir, create=True) / WEEKLY_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def _record_weekly_engagement(course_dir: Path, source: str) -> None:
    """/api/attempt's hook into the weekly cadence: an attempt submitted from the weekly
    page is engagement with that session, so it closes the week. Attempts from anywhere
    else say nothing about the weekly loop and fall straight through."""
    if source != "weekly":
        return
    _log_weekly_session(
        course_dir,
        trigger="attempt",
        items_presented=None,
        as_of=datetime.now().astimezone().date(),
    )


def _weekly_status(course_dir: Path, as_of: date | None = None) -> dict[str, Any]:
    """Weekly-loop state for one course: whether a session is due by the cadence rule, when
    the last one happened, and the items a session held now would present. eligible_count is
    the capped, presentable selection — the count the page actually shows, never a backlog."""
    today = as_of or datetime.now().astimezone().date()
    sessions = _read_weekly_sessions(course_dir)
    last_session_ts = sessions[-1]["ts"] if sessions else None
    last_date = _event_local_date(last_session_ts) if last_session_ts else None
    due = last_date is None or (today - last_date).days >= WEEKLY_CADENCE_DAYS
    items = _compute_weekly(
        _read_practice_events(course_dir),
        as_of=as_of,
        presentable=set(_lesson_quiz_index(course_dir)),
        units_by_lesson=_lesson_unit_map(course_dir),
    )
    return {
        "due": due,
        "last_session_ts": last_session_ts,
        "eligible_count": len(items),
        "items": items,
    }


def _weekly_state_payload(course_dir: Path) -> dict[str, Any]:
    """The weekly block as the frontend consumes it — the cadence facts without the
    selected items themselves. One shape, two endpoints: /api/practice embeds it so the
    sidebar renders both review lines from one fetch, and /api/weekly-session returns it
    so a just-recorded session updates without a second round trip."""
    status = _weekly_status(course_dir)
    return {key: status[key] for key in ("due", "last_session_ts", "eligible_count")}


def _weekly_state_line(course_dir: Path) -> str:
    """The weekly-loop line of the teaching agent's practice-state block: the cadence fact
    plus, when a session is due, what the agent is expected to do with it (charter P21/P22 —
    the learner does the evaluating and the reporting; the agent proposes, then records)."""
    status = _weekly_status(course_dir)
    count = status["eligible_count"]
    eligible = f"{count} item{'s' if count != 1 else ''} eligible for the delayed check"
    if not status["due"]:
        last = (status["last_session_ts"] or "")[:10]
        return f"Weekly review is not due (last session {last}; {eligible})."
    return (
        f"Weekly review is due ({eligible}). "
        "Propose it at a natural break in the work, never mid-lesson, by directing the "
        "learner to Weekly review in the sidebar Practice section. Expect two things back "
        "in chat: the learner's own assessment of which \"Success looks like\" bullets now "
        "have evidence behind them and which are still aspirations, and a report of what "
        "section, office hours, or sangha surfaced. Critique the first only after they have "
        "given it; capture the second into a learning record via append_learning_record, "
        "citing where it came from (who said it, in which setting, when). "
        "Once they have given you both, ask them to click \"Mark this review as held\" "
        "on that page — an attempt from the delayed check closes the week on its own, "
        "but when nothing has aged into it yet, that button is the only thing that does."
    )


def _weekly_delayed_intro(items: list[dict[str, Any]]) -> str:
    """Plain factual intro to the delayed check (charter P7 — no encouragement theater):
    how many items, the real delay behind the shortest of them, and what the check measures."""
    total = len(items)
    min_days = min(item["days_since"] for item in items)
    return (
        f"{total} item{'s' if total != 1 else ''}, none practiced in the last "
        f"{min_days} days. This is the measure that counts: unassisted recall after a "
        "real delay."
    )


def _weekly_calibration_sentences(matrix: list[list[int]]) -> list[str]:
    """One sentence per confidence level that has graded attempts, comparing what the
    learner predicted to what happened (charter P13: prediction without feedback does not
    recalibrate anything). Counts only, no percentages. Give-ups are excluded — they carry a
    forced confidence and were never graded, so they say nothing about calibration."""
    sentences = []
    for index, label in enumerate(WEEKLY_CONFIDENCE_LABELS):
        row = matrix[index]
        graded = row[0] + row[1] + row[2]
        if not graded:
            continue
        correct = row[0]
        if correct == 0:
            outcome = "none were correct"
        elif correct == 1:
            outcome = "1 was correct"
        else:
            outcome = f"{correct} were correct"
        sentences.append(
            f"You said “{label}” on {graded} attempt"
            f"{'s' if graded != 1 else ''}; {outcome}."
        )
    return sentences


def _weekly_calibration_table(matrix: list[list[int]]) -> str:
    """Confidence (rows) by verdict (columns) counts — the same matrix the Practice page
    shows, server-rendered. Blank cells mean zero; only the three graded verdicts appear."""
    head = "".join(
        f"<th>{html_escape(label)}</th>" for label in ("", "Correct", "Partial", "Incorrect")
    )
    rows = []
    for index, label in enumerate(WEEKLY_CONFIDENCE_LABELS):
        cells = "".join(
            f"<td>{matrix[index][verdict] if matrix[index][verdict] else ''}</td>"
            for verdict in range(3)
        )
        rows.append(
            f'<tr><th scope="row">{html_escape(label.capitalize())}</th>{cells}</tr>'
        )
    return (
        '<table class="weekly-calibration">\n'
        f"<thead><tr>{head}</tr></thead>\n"
        f"<tbody>{''.join(rows)}</tbody>\n"
        "</table>"
    )


def _mission_success_section(course_dir: Path) -> str | None:
    """The markdown block under MISSION.md's "Success looks like" heading, rendered to
    HTML — or None when the file or the heading is absent, or the block carries no list.
    Lines run to the next heading of any level, so wrapped and nested bullets survive."""
    path = learner_dir(course_dir) / "MISSION.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    collected: list[str] = []
    inside = False
    for line in text.splitlines():
        heading = _MISSION_HEADING_RE.match(line)
        if heading:
            if inside:
                break
            inside = heading.group(1).strip().lower() == MISSION_SUCCESS_HEADING
            continue
        if inside:
            collected.append(line.rstrip())
    if not any(_MISSION_BULLET_RE.match(line) for line in collected):
        return None
    return markdown_lib.markdown("\n".join(collected).strip(), extensions=MARKDOWN_EXTENSIONS)


# Same standalone-page pattern as the daily review page, styled by the course's own lesson
# stylesheet so carried-over quiz items render exactly as they do in lessons. The additions
# are the per-item source line and the server-rendered calibration matrix — both Tufte-plain:
# hairlines, tabular figures, counts rather than percentages, no charts and no badges.
WEEKLY_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weekly review</title>
<link rel="stylesheet" href="/workspace/${course}/assets/lesson.css">
<style>
.weekly-source {
  font-family: var(--font-display, sans-serif);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink-secondary, #44423d);
  margin: 1.75rem 0 0.35rem;
}
.weekly-source + .quiz-item { margin-top: 0; }
${source_mark_css}
.weekly-line {
  font-variant-numeric: tabular-nums;
  margin: 0 0 0.4rem;
}
.weekly-calibration {
  border-collapse: collapse;
  margin: 1.25rem 0 0;
  font-family: var(--font-display, sans-serif);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 0.9rem;
}
.weekly-calibration thead th {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink-secondary, #44423d);
  text-align: right;
  padding: 0.25rem 0 0.25rem 1.5rem;
  border-bottom: 1px solid var(--hairline-strong, rgba(20, 18, 15, 0.24));
}
.weekly-calibration thead th:first-child { padding-left: 0; }
.weekly-calibration tbody th {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink, #14120f);
  text-align: left;
  padding: 0.3rem 0;
  white-space: nowrap;
}
.weekly-calibration td {
  font-variant-numeric: tabular-nums;
  text-align: right;
  padding: 0.3rem 0 0.3rem 1.5rem;
}
.weekly-note {
  color: var(--ink-secondary, #44423d);
  margin: 1.25rem 0 0;
}
.weekly-concepts {
  font-family: var(--font-display, sans-serif);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--ink, #14120f);
  margin: 0.35rem 0 0;
}
/* The mark-held control. .btn/.btn-secondary are restated here rather than borrowed:
   this page loads the course's lesson.css, not the app shell's style.css, so the shell's
   button rules are not in scope. Same declarations, same tokens — a secondary button,
   because closing a review is a quiet bookkeeping act, not the page's call to action. */
.weekly-mark { margin: 2rem 0 0; }
.btn {
  font-family: var(--font-display, sans-serif);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 0.9rem;
  font-weight: 600;
  border-radius: var(--radius, 4px);
  padding: 0.45rem 0.95rem;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-secondary {
  background: var(--paper, #ffffff);
  border-color: var(--hairline-strong, rgba(20, 18, 15, 0.24));
  color: var(--ink, #14120f);
}
.btn-secondary:hover { background: var(--ink-wash, rgba(20, 18, 15, 0.04)); }
.btn-secondary:active {
  background: var(--ink-wash-press, rgba(20, 18, 15, 0.08));
  transform: translateY(1px);
}
.btn:disabled { opacity: 0.5; pointer-events: none; }
.weekly-mark-note {
  font-size: 0.85rem;
  color: var(--ink-secondary, #44423d);
  margin: 0.6rem 0 0;
  max-width: 32rem;
}
.weekly-mark-done {
  font-size: 0.85rem;
  font-style: italic;
  color: var(--ink-secondary, #44423d);
  margin: 0;
}
</style>
</head>
<body>
<article class="lesson">

<p class="eyebrow">Weekly review &middot; ${date_line}</p>
<h1>Weekly review</h1>
${body}
</article>
<script src="/static/quiz.js" defer></script>
</body>
</html>
""")


# The second engagement path. The delayed check can be empty — nothing aged enough yet —
# while the mission check and the world capture are still real work, done in chat; without
# this the week would have no way to close. Rendered only when the page was served for the
# real today: a ?as_of= preview must never be markable. Inline rather than in quiz.js
# because it belongs to this page alone, and it reads the course slug from the document's
# own URL for the same reason quiz.js does — the page is standalone and same-origin.
WEEKLY_MARK_CONTROL = """<div class="weekly-mark" id="weekly-mark">
<button type="button" class="btn btn-secondary" id="weekly-mark-button">Mark this review as held</button>
<p class="weekly-mark-note">Use this once you have taken the mission check and anything from section or sangha to your teacher in the chat.</p>
</div>
<script>
(function () {
  "use strict";
  var block = document.getElementById("weekly-mark");
  var button = document.getElementById("weekly-mark-button");
  var match = document.location.pathname.match(/^\\/weekly\\/([^/]+)(?:\\/|$)/);
  if (!block || !button || !match) return;
  var course = decodeURIComponent(match[1]);

  function done() {
    var line = document.createElement("p");
    line.className = "weekly-mark-done";
    line.textContent = "Marked as held.";
    block.replaceChildren(line);
    // The weekly page runs standalone in the app's preview iframe; announcing the
    // recorded session lets the sidebar's weekly line refresh instead of waiting for
    // the next course-level refetch. Same origin only, and never load-bearing.
    if (window.parent === window) return;
    try {
      window.parent.postMessage({ type: "keating:weekly-session" }, window.location.origin);
    } catch (err) {
      // A cross-origin or otherwise unreachable parent is not this page's problem.
    }
  }

  function fail(detail) {
    button.disabled = false;
    var existing = document.getElementById("weekly-mark-error");
    if (existing) existing.remove();
    var line = document.createElement("p");
    line.className = "weekly-mark-note";
    line.id = "weekly-mark-error";
    line.textContent = "Couldn't record this session: " + detail + ". Try again.";
    block.appendChild(line);
  }

  button.addEventListener("click", function () {
    button.disabled = true;
    fetch("/api/weekly-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course: course }),
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (!response.ok) {
            throw new Error(body && body.detail ? String(body.detail) : "HTTP " + response.status);
          }
          return body;
        });
      })
      .then(done)
      .catch(function (err) { fail(err.message); });
  });
})();
</script>"""


@app.get("/weekly/{course}")
def weekly_page(course: str, as_of: str | None = None) -> Response:
    """The weekly review session as a standalone generated page for the preview iframe:
    the platform's delayed unassisted check (charter P19), the predicted-vs-actual
    calibration display (P13), the mission's own success criteria handed back to the
    learner to evaluate (P21), and the prompt that carries section/office-hours/sangha
    signal back into the records (P22). Serving the page records nothing: a session counts
    only on engagement — an attempt submitted from this page, or the explicit "mark held"
    control below. ?as_of=YYYY-MM-DD is a dev/testing preview that overrides "today" and
    additionally hides that control (a preview must never be markable). The UI never
    sends it."""
    course_dir = resolve_course_dir(course)
    if as_of is not None:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid as_of date: {as_of!r}")
    else:
        as_of_date = None

    shown_date = as_of_date or datetime.now().astimezone().date()
    events = _read_practice_events(course_dir)
    index = _lesson_quiz_index(course_dir)
    selected = _compute_weekly(
        events,
        as_of=as_of_date,
        presentable=set(index),
        units_by_lesson=_lesson_unit_map(course_dir),
    )

    parts: list[str] = ["<h2>Delayed check</h2>"]
    if not selected:
        parts.append(
            "<p>Nothing has aged enough for a delayed check yet. Items become eligible "
            f"{_number_word(WEEKLY_DELAY_DAYS)} days after their last attempt.</p>"
        )
    else:
        parts.append(f"<p>{html_escape(_weekly_delayed_intro(selected))}</p>")
        colors = _lesson_unit_colors(course_dir)
        for item in selected:
            block = index[item["item_id"]]
            parts.append(_source_line("weekly-source", block, colors))
            parts.append(block["block"])

    practice = _aggregate_practice(course_dir)
    calibration = practice["calibration"]
    graded = sum(row[0] + row[1] + row[2] for row in calibration["matrix"]) if calibration else 0
    if graded >= WEEKLY_CALIBRATION_MIN_ATTEMPTS:
        parts.append("<h2>Calibration</h2>")
        for sentence in _weekly_calibration_sentences(calibration["matrix"]):
            parts.append(f'<p class="weekly-line">{html_escape(sentence)}</p>')
        parts.append(_weekly_calibration_table(calibration["matrix"]))
        missed = [item for item in practice["items"] if item["high_confidence_miss"]]
        if missed:
            parts.append(
                '<p class="weekly-note">High-confidence misses are the items most worth '
                "re-testing.</p>"
            )
            parts.append(
                '<p class="weekly-concepts">'
                + html_escape(", ".join(item["concept"] or item["item_id"] for item in missed))
                + "</p>"
            )

    mission = _mission_success_section(course_dir)
    if mission:
        parts.append("<h2>Mission check</h2>")
        parts.append(mission)
        parts.append(
            '<p class="weekly-note">For each of these, tell your teacher in the chat which '
            "ones now have evidence behind them and which are still aspirations. Evidence "
            "means a graded attempt, something you wrote, or something that happened in "
            "section or sangha, not a feeling of familiarity.</p>"
        )

    parts.append("<h2>From the world</h2>")
    parts.append(
        "<p>What did section, office hours, or sangha surface this week? The part worth "
        "carrying back is what surprised you, what contradicted something you thought you "
        "knew, and what you left still confused about.</p>"
    )
    parts.append(
        '<p class="weekly-note">Bring it to the chat. Your teacher records it with its '
        "provenance, who said it and where, so it sits in your learning records alongside "
        "the practice log rather than evaporating.</p>"
    )

    if as_of_date is None:
        parts.append(WEEKLY_MARK_CONTROL)

    page = WEEKLY_PAGE_TEMPLATE.substitute(
        course=html_escape(course, quote=True),
        date_line=html_escape(f"{_REVIEW_MONTHS[shown_date.month - 1]} {shown_date.day}"),
        body="\n\n".join(parts),
        source_mark_css=SOURCE_MARK_CSS,
    )
    return Response(content=page, media_type="text/html")


class WeeklySessionRequest(BaseModel):
    course: str


@app.post("/api/weekly-session")
def record_weekly_session(req: WeeklySessionRequest) -> dict[str, Any]:
    """The explicit "mark held" path — the weekly page's one control. It exists because a
    week whose delayed check is empty (nothing aged enough yet) still has real work in it:
    the mission check and the world capture both happen in chat, and the learner needs a
    way to close the week after doing them. Idempotent for the local day, so a second
    click, or a click after an attempt already closed the week, is a no-op that still
    answers with the current state."""
    course_dir = resolve_course_dir(req.course)
    # eligible_count recomputed here is the count the page presented: the selection is a
    # pure function of the practice log, and on the path that actually writes, nothing has
    # been logged between the render and the click (an attempt in between would have
    # closed the week itself, making this call the no-op).
    _log_weekly_session(
        course_dir,
        trigger="manual",
        items_presented=_weekly_status(course_dir)["eligible_count"],
        as_of=datetime.now().astimezone().date(),
    )
    return _weekly_state_payload(course_dir)


# --- Compose: the learner-authored artifact surface ---------------------------

# Charter P1/P8: the learner drafts every learning artifact before the AI reveals its
# version as a critique target — an artifact the AI wrote is documentation, not evidence
# of learning (generation effect, d = 0.40). Compose is where that happens outside a
# quiz item: a closed-book free recall (logged as a retrieval event with full practice-log
# parity, per Karpicke & Blunt's finding that closed-book recall beats elaborative
# mapping), and a glossary definition drafted from memory, critiqued, and saved in the
# learner's own words.

COMPOSE_MAX_TOKENS = 3000

# Floors on a committed draft, mirrored by the client's submit gating. A free recall is a
# paragraph-scale task; a definition is one or two sentences.
COMPOSE_RECALL_MIN_CHARS = 40
COMPOSE_DEFINE_MIN_CHARS = 20

# Reference-material caps. A lesson's readable text runs a few thousand characters, so
# these bind only on pathological inputs — they exist so one enormous lesson cannot blow
# the grading call's budget.
COMPOSE_REFERENCE_MAX_CHARS = 24000
COMPOSE_DEFINE_MAX_PASSAGES = 12
COMPOSE_DEFINE_MAX_CHARS = 8000

# The practice log understands exactly four verdicts (PRACTICE_VERDICTS), and the
# aggregation, the calibration matrix, and the due/weekly selections all read them. Compose
# grades in its own bands — a free recall is not right or wrong the way a rubric item is —
# and maps down before writing, so the log stays one vocabulary. The original band is
# returned to the UI, which is the only place it means anything.
RECALL_VERDICT_TO_PRACTICE = {
    "substantial": "correct",
    "partial": "partially_correct",
    "thin": "incorrect",
}
DEFINE_VERDICT_TO_PRACTICE = {
    "sound": "correct",
    "partial": "partially_correct",
    "off": "incorrect",
}

GLOSSARY_NAME = "GLOSSARY.md"
GLOSSARY_TERMS_HEADING = "## Terms"

# `**Term**:` opens an entry in GLOSSARY-FORMAT.md's schema.
_GLOSSARY_TERM_RE = re.compile(r"^\*\*(.+?)\*\*\s*:")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s")

COMPOSE_RECALL_SYSTEM_PROMPT = """\
You judge one closed-book free recall for a learning platform. You are given reference \
material the learner was meant to have learned, and the recall they typed from memory \
with the reading closed.

Judge coverage of the reference material ONLY. Never credit or penalize anything the \
reference does not contain, and never grade against your own knowledge of the topic.

Verdict bands:
- "substantial": the reference's major points are present in substance.
- "partial": some major points are present and others are absent.
- "thin": few or none of the major points are present.

Also produce three coverage lists. Each entry is a short noun phrase naming one point — \
not a sentence, not a quotation — ordered most important first, at most six entries per \
list. Return an empty list rather than padding one.
- had: points from the reference the recall states in substance.
- missed: points from the reference the recall does not state at all.
- not_quite: points the recall states in a way the reference contradicts, blurs, or \
misattributes. Name the specific distortion ("jhāna treated as nibbāna itself"), never \
just the topic.

Free recall is broad by nature: credit substance over completeness of phrasing. \
Paraphrase, the learner's own vocabulary, and any order all count fully, and a point is \
present when the idea is there even if the reference's technical term is not. Judge \
what was recalled, not how it was written.

Produce four feedback strings following this grammar. All four are required and each \
must be written out in full: the coverage lists above never stand in for them, and an \
empty feedback string is an invalid response. The hard rules:
- criterion: one sentence stating what a substantial recall of THIS material would \
contain — the standard this recall is judged against.
- task: one to two sentences stating how THIS recall relates to that criterion, citing \
something the learner actually wrote (quote or closely paraphrase their own words). Name \
what is present and what is missing or distorted — about the recall only.
- process: one sentence naming the single most useful next strategy for this material \
(what to reread, contrast, or retrieve again — the one that matters most, never a list).
- self_regulation: one short self-monitoring question the learner can ask themselves.

""" + NO_PERSON_EVALUATION_RULE + """

The reference material may include lines beginning "Answer:" — those are canonical \
answers the course itself teaches, and they are legitimate content to expect in a recall.
"""

COMPOSE_DEFINE_SYSTEM_PROMPT = """\
You critique one glossary definition a learner drafted from memory, for a learning \
platform whose rule is that the learner's own wording is what gets saved. You are given \
passages from this course's own materials that mention the term, and the learner's draft.

Ground the critique in the supplied passages — this course's usage of the term — not in \
generic knowledge of the field. When the passages are thin, say what they do and do not \
settle rather than filling the gap from elsewhere.

Verdict bands:
- "sound": the draft defines what the term IS, accurately for this course's usage.
- "partial": the draft is accurate as far as it goes but leaves out something the course's \
usage carries.
- "off": the draft misidentifies the term, or asserts something the passages contradict.

Also produce:
- reference_definition: your own compressed definition, one or two sentences, defining \
what the term IS rather than what it does or how to do it. This is a comparison target \
only. The learner's wording is what will be saved, so do not write it as a replacement \
and do not tell the learner to adopt it.
- discrepancies: each entry names one difference between the draft and the course's usage, \
phrased as a question wherever a question is possible ("Does 'the self does not exist' \
cover what the texts deny, or only part of it?"). At most five, most important first, \
ordered by what would change the definition most. Return an empty list when the draft \
matches the passages.

Produce four feedback strings following this grammar. All four are required and each \
must be written out in full: the reference definition and the discrepancies never stand \
in for them, and an empty feedback string is an invalid response. The hard rules:
- criterion: one sentence stating what a tight, accurate definition of THIS term would \
contain in this course's usage.
- task: one to two sentences stating how THIS draft relates to that criterion, citing \
something the learner actually wrote. Name what is present and what is missing or wrong — \
about the draft only.
- process: one sentence naming the single most useful next move for revising this \
definition (never a list).
- self_regulation: one short self-monitoring question the learner can ask themselves.

""" + NO_PERSON_EVALUATION_RULE + """
"""


# The four feedback strings carry min_length because a grader that answers the coverage
# lists and then leaves the P16 feedback blank produces a reveal with nothing in it — the
# observed failure mode when the schema let empty strings through. The lists themselves
# stay unconstrained: an empty "not quite right" is real information.
class ComposedRecall(BaseModel):
    """Structured output of the free-recall grader: a coverage band, the four feedback
    strings of the P16 grammar, and the three-way coverage diff.

    Field order is load-bearing, not cosmetic. Generated in schema order, the four
    feedback strings have to come before the three lists: with the lists first the model
    spends itself enumerating and then leaves the prose empty or loops inside it (measured
    at roughly half of calls on short reference material). Prose first was stable across
    every trial. The UI renders the diff above the feedback regardless — the response the
    endpoint returns is assembled by hand."""

    verdict: Literal["substantial", "partial", "thin"]
    criterion: str = Field(min_length=1)
    task: str = Field(min_length=1)
    process: str = Field(min_length=1)
    self_regulation: str = Field(min_length=1)
    had: list[str]
    missed: list[str]
    not_quite: list[str]


class ComposedDefinition(BaseModel):
    """Structured output of the glossary-draft critique: a band, the four feedback
    strings, the AI's own definition as a declared comparison target, and the
    discrepancies it converts into questions (charter P8). Same ordering discipline as
    ComposedRecall — the prose fields are generated before the list."""

    verdict: Literal["sound", "partial", "off"]
    criterion: str = Field(min_length=1)
    task: str = Field(min_length=1)
    process: str = Field(min_length=1)
    self_regulation: str = Field(min_length=1)
    reference_definition: str = Field(min_length=1)
    discrepancies: list[str]


class ComposeRecallRequest(BaseModel):
    course: str
    target_type: Literal["lesson", "concept"]
    target_ref: str
    response: str
    confidence: int = Field(ge=1, le=4)
    latency_ms: int | None = None


class ComposeDefineRequest(BaseModel):
    course: str
    term: str
    draft: str
    confidence: int = Field(ge=1, le=4)
    latency_ms: int | None = None


class GlossaryEntryRequest(BaseModel):
    course: str
    term: str
    definition: str
    avoid: str | None = None


def _compose_slug(text: str) -> str:
    """A synthetic practice-log item id's readable tail. Unicode word characters survive
    (the course's terms are Pali and Sanskrit — an ASCII-only slug would collapse
    "anattā" and "anatta" into one id)."""
    return re.sub(r"[^\w]+", "-", text.strip().lower(), flags=re.UNICODE).strip("-")


def _glossary_terms(course_dir: Path) -> list[str]:
    """The terms GLOSSARY.md currently defines, in file order. An absent or unreadable
    glossary has no terms rather than failing the request."""
    path = learner_dir(course_dir) / GLOSSARY_NAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    terms: list[str] = []
    for line in text.splitlines():
        match = _GLOSSARY_TERM_RE.match(line)
        if match:
            term = match.group(1).strip()
            if term:
                terms.append(term)
    return terms


@app.get("/api/compose-targets")
def get_compose_targets(course: str) -> dict[str, Any]:
    """What the Compose surface can be pointed at: every lesson ({path, number, title}),
    every concept the course's authored quiz items claim (deduplicated, in lesson order),
    and the terms GLOSSARY.md already defines."""
    course_dir = resolve_course_dir(course)
    lessons = _lesson_texts(course_dir)
    concepts: dict[str, None] = {}
    for lesson in lessons:
        for concept in lesson["by_concept"]:
            concepts.setdefault(concept, None)
    return {
        "lessons": [
            {"path": lesson["path"], "number": lesson["number"], "title": lesson["title"]}
            for lesson in lessons
        ],
        "concepts": list(concepts),
        "glossary_terms": _glossary_terms(course_dir),
    }


def _recall_reference(
    course_dir: Path, target_type: str, target_ref: str
) -> tuple[str, str, str, str]:
    """The reference material one free recall is judged against, built server-side so the
    learner's client never holds the answers it is being checked against. Returns
    (item_slug, concept label, lesson field, reference text).

    A lesson target's reference is that lesson's whole readable text, canonical quiz
    answers included. A concept target's is every block across the course that claims the
    concept, each under its lesson's name — which is what makes a concept recall a
    cumulative, cross-lesson retrieval rather than a second way to recall one lesson."""
    lessons = _lesson_texts(course_dir)
    if target_type == "lesson":
        lesson = next((entry for entry in lessons if entry["path"] == target_ref), None)
        if lesson is None:
            raise HTTPException(status_code=404, detail=f"no such lesson: {target_ref}")
        number = f"{lesson['number']:04d}"
        reference = f"Lesson {lesson['number']:02d}: {lesson['title']}\n\n{lesson['text']}"
        return number, lesson["title"], number, reference[:COMPOSE_REFERENCE_MAX_CHARS]

    wanted = target_ref.strip().casefold()
    label = ""
    parts: list[str] = []
    for lesson in lessons:
        for concept, blocks in lesson["by_concept"].items():
            if concept.casefold() != wanted:
                continue
            label = label or concept
            parts.append(
                f"From Lesson {lesson['number']:02d}, {lesson['title']}:\n" + "\n\n".join(blocks)
            )
    if not parts:
        raise HTTPException(status_code=404, detail=f"no such concept: {target_ref}")
    reference = f"Concept: {label}\n\n" + "\n\n".join(parts)
    # A concept spans lessons by design, so it belongs to none of them: the lesson field
    # stays empty rather than claiming one arbitrarily.
    return _compose_slug(label), label, "", reference[:COMPOSE_REFERENCE_MAX_CHARS]


@app.post("/api/compose/recall")
def compose_recall(req: ComposeRecallRequest) -> dict[str, Any]:
    """Grade one closed-book free recall against the material it targets, and log it as a
    retrieval event with full practice-log parity. The verdict is written to the log in
    the log's own vocabulary (RECALL_VERDICT_TO_PRACTICE) and returned to the UI in the
    recall grader's bands.

    The synthetic item id ("recall:0003") is carried by no lesson, so the daily and weekly
    selections — which filter through the authored quiz index — skip it automatically: a
    free recall is real retrieval evidence but cannot be re-presented as a quiz item."""
    course_dir = resolve_course_dir(req.course)
    response = req.response.strip()
    if len(response) < COMPOSE_RECALL_MIN_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"a recall needs at least {COMPOSE_RECALL_MIN_CHARS} characters",
        )
    slug, concept, lesson_field, reference = _recall_reference(
        course_dir, req.target_type, req.target_ref
    )
    prompt = (
        f"Reference material:\n{reference}\n\n"
        f"The learner's free recall:\n{response}"
    )
    graded = _grade_with_model(
        COMPOSE_RECALL_SYSTEM_PROMPT, prompt, ComposedRecall, COMPOSE_MAX_TOKENS
    )
    _append_practice_event(
        course_dir,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "item_id": f"recall:{slug}",
            "concept": concept,
            "lesson": lesson_field,
            "type": "free_recall",
            "cumulative": False,
            "response": response,
            "verdict": RECALL_VERDICT_TO_PRACTICE[graded.verdict],
            "confidence": req.confidence,
            "latency_ms": req.latency_ms,
            "gave_up": False,
            "source": "compose",
        },
    )
    return {
        "verdict": graded.verdict,
        "had": graded.had,
        "missed": graded.missed,
        "not_quite": graded.not_quite,
        "feedback": {
            "criterion": graded.criterion,
            "task": graded.task,
            "process": graded.process,
            "self_regulation": graded.self_regulation,
        },
    }


def _define_reference(course_dir: Path, term: str) -> str:
    """The course's own usage of a term: every passage in any lesson that mentions it,
    under its lesson's name, capped. Grounding the critique here rather than in the
    model's general knowledge is what keeps a definition answerable to this course."""
    needle = term.strip().casefold()
    parts: list[str] = []
    total = 0
    for lesson in _lesson_texts(course_dir):
        hits = [line for line in lesson["text"].splitlines() if needle in line.casefold()]
        if not hits:
            continue
        for hit in hits:
            if len(parts) >= COMPOSE_DEFINE_MAX_PASSAGES or total >= COMPOSE_DEFINE_MAX_CHARS:
                break
            parts.append(f"From Lesson {lesson['number']:02d}, {lesson['title']}:\n{hit}")
            total += len(hit)
    if not parts:
        return ""
    return "\n\n".join(parts)[:COMPOSE_DEFINE_MAX_CHARS]


def _already_logged_today(course_dir: Path, item_id: str) -> bool:
    today = datetime.now().astimezone().date()
    return any(
        event["item_id"] == item_id and _event_local_date(event["ts"]) == today
        for event in _read_practice_events(course_dir)
    )


@app.post("/api/compose/define")
def compose_define(req: ComposeDefineRequest) -> dict[str, Any]:
    """Critique one glossary definition the learner drafted from memory: the four-part
    feedback, the AI's own definition declared as a comparison target, and the
    discrepancies converted into questions (charter P8 — the learner's compression is the
    evidence, so it stays the learner's).

    The first draft of a term on a given day is a retrieval event and is logged; revisions
    the same day are the same retrieval, re-worked, and are not logged again."""
    course_dir = resolve_course_dir(req.course)
    term = " ".join(req.term.split())
    draft = req.draft.strip()
    if not term:
        raise HTTPException(status_code=400, detail="a term is required")
    if len(draft) < COMPOSE_DEFINE_MIN_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"a definition needs at least {COMPOSE_DEFINE_MIN_CHARS} characters",
        )
    reference = _define_reference(course_dir, term)
    prompt = (
        f"Term: {term}\n\n"
        + (
            f"Passages from this course that mention the term:\n{reference}\n\n"
            if reference
            else "This course's lessons do not mention the term anywhere. Say so in the "
            "task-level feedback, and ground the critique in what the draft itself "
            "claims rather than in outside sources.\n\n"
        )
        + f"The learner's draft definition:\n{draft}"
    )
    graded = _grade_with_model(
        COMPOSE_DEFINE_SYSTEM_PROMPT, prompt, ComposedDefinition, COMPOSE_MAX_TOKENS
    )
    item_id = f"define:{_compose_slug(term)}"
    if not _already_logged_today(course_dir, item_id):
        _append_practice_event(
            course_dir,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "item_id": item_id,
                "concept": term,
                "lesson": "",
                "type": "glossary_draft",
                "cumulative": False,
                "response": draft,
                "verdict": DEFINE_VERDICT_TO_PRACTICE[graded.verdict],
                "confidence": req.confidence,
                "latency_ms": req.latency_ms,
                "gave_up": False,
                "source": "compose",
            },
        )
    return {
        "verdict": graded.verdict,
        "reference_definition": graded.reference_definition,
        "discrepancies": graded.discrepancies,
        "feedback": {
            "criterion": graded.criterion,
            "task": graded.task,
            "process": graded.process,
            "self_regulation": graded.self_regulation,
        },
    }


def _glossary_topic(course_dir: Path) -> str:
    """What a new glossary is a glossary of: MISSION.md's own title where there is one
    (with its "Mission:" prefix dropped), the prettified course slug otherwise."""
    mission = learner_dir(course_dir) / "MISSION.md"
    if mission.is_file():
        try:
            for line in mission.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    if title.lower().startswith("mission:"):
                        title = title.split(":", 1)[1].strip()
                    if title:
                        return title
                    break
        except (OSError, UnicodeDecodeError):
            pass
    return _prettify_slug(course_dir.name)


def _glossary_entry_lines(term: str, definition: str, avoid: str | None) -> list[str]:
    """One entry in GLOSSARY-FORMAT.md's schema: the bolded term, the definition on its
    own line, and the aliases line when there are aliases to rule out."""
    lines = [f"**{term}**:", definition]
    if avoid:
        lines.append(f"_Avoid_: {avoid}")
    return lines


def _new_glossary_text(topic: str, term: str, definition: str, avoid: str | None) -> str:
    return "\n".join(
        [
            f"# {topic} Glossary",
            "",
            "The working vocabulary of this course. Every definition is drafted from "
            "memory by the learner and kept in the learner's own words.",
            "",
            GLOSSARY_TERMS_HEADING,
            "",
            *_glossary_entry_lines(term, definition, avoid),
            "",
        ]
    )


def _glossary_with_entry(text: str, term: str, definition: str, avoid: str | None) -> str:
    """Insert or replace one term's entry, leaving every other entry and the file's own
    structure (headings, subheadings, description, ordering) exactly as they were. A term
    already defined is revised in place — GLOSSARY-FORMAT.md's "update in place; do not
    leave stale entries" — and a new one lands at the end of the Terms section."""
    lines = text.splitlines()
    entry = _glossary_entry_lines(term, definition, avoid)
    wanted = term.casefold()

    # Entry starts, plus the line each entry's span ends before: the next entry, the next
    # heading, or the end of the file.
    starts = [i for i, line in enumerate(lines) if _GLOSSARY_TERM_RE.match(line)]
    for position, start in enumerate(starts):
        match = _GLOSSARY_TERM_RE.match(lines[start])
        if match.group(1).strip().casefold() != wanted:
            continue
        end = len(lines)
        if position + 1 < len(starts):
            end = starts[position + 1]
        for i in range(start + 1, end):
            if _MARKDOWN_HEADING_RE.match(lines[i]):
                end = i
                break
        # Trailing blank lines belong to the separation between entries, not to the entry.
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        return "\n".join(lines[:start] + entry + lines[end:]) + "\n"

    # Not defined yet: append to the end of the Terms section.
    heading = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip().casefold() == GLOSSARY_TERMS_HEADING.casefold()
        ),
        None,
    )
    if heading is None:
        body = lines[:]
        while body and not body[-1].strip():
            body.pop()
        return "\n".join(body + ["", GLOSSARY_TERMS_HEADING, ""] + entry) + "\n"
    end = len(lines)
    for i in range(heading + 1, len(lines)):
        if _MARKDOWN_HEADING_RE.match(lines[i]):
            end = i
            break
    while end > heading + 1 and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[:end] + [""] + entry + [""] + lines[end:]).rstrip("\n") + "\n"


@app.post("/api/glossary")
def save_glossary_entry(req: GlossaryEntryRequest) -> dict[str, Any]:
    """Write the learner's own definition into GLOSSARY.md, creating the file to
    GLOSSARY-FORMAT.md's skeleton when it does not exist yet and snapshotting the previous
    version into the course's state history when it does (the same guardrail write_file
    applies to the two learner-state files). The definition saved is the one posted — the
    critique endpoint's reference definition is a comparison target and never reaches
    this path."""
    course_dir = resolve_course_dir(req.course)
    term = " ".join(req.term.split())
    definition = " ".join(req.definition.split())
    avoid = " ".join(req.avoid.split()) if req.avoid else None
    if not term:
        raise HTTPException(status_code=400, detail="a term is required")
    if not definition:
        raise HTTPException(status_code=400, detail="a definition is required")
    path = learner_dir(course_dir, create=True) / GLOSSARY_NAME
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"GLOSSARY.md is unreadable: {exc}")
        updated = _glossary_with_entry(existing, term, definition, avoid)
    else:
        updated = _new_glossary_text(_glossary_topic(course_dir), term, definition, avoid)
    _snapshot_state_file(course_dir, path, updated)
    path.write_text(updated, encoding="utf-8")
    return {"term": term, "saved": True}


@app.get("/api/courses")
def list_courses() -> dict[str, Any]:
    """Every course in the workspace, each named by its manifest title where it has one so
    the UI can list real titles rather than slugs. The slug stays the identity."""
    if not WORKSPACE_ROOT.is_dir():
        return {"courses": []}
    slugs = sorted(
        p.name
        for p in WORKSPACE_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in RESERVED_DIRS
    )
    return {
        "courses": [
            {"slug": slug, "title": course_title(WORKSPACE_ROOT / slug, slug)} for slug in slugs
        ]
    }


@app.post("/api/courses")
def create_course(req: NewCourseRequest) -> dict[str, Any]:
    """A new course starts as a course package with a minimal manifest and an empty
    learner directory beside it; everything else is created lazily, when there is real
    content to put in it."""
    course_dir = resolve_course_dir(req.slug, must_exist=False)
    if course_dir.exists():
        raise HTTPException(status_code=409, detail=f"course already exists: {req.slug}")
    course_dir.mkdir(parents=True, exist_ok=False)
    learner_dir(course_dir, create=True)
    manifest = {
        "schema": COURSE_MANIFEST_SCHEMA,
        "slug": req.slug,
        "title": _prettify_slug(req.slug),
        # The unit tier starts empty and generically named: the course's own word for it
        # ("Part", "Domain", "Week") and its units are filled in once its structure is known.
        "unit_label": DEFAULT_UNIT_LABEL,
        "units": [],
        "created": date.today().isoformat(),
    }
    (course_dir / COURSE_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"slug": req.slug}


@app.patch("/api/courses/{slug}")
def rename_course(slug: str, req: RenameCourseRequest) -> dict[str, Any]:
    course_dir = resolve_course_dir(slug)
    new_dir = resolve_course_dir(req.new_slug, must_exist=False)
    if new_dir.exists():
        raise HTTPException(status_code=409, detail=f"course already exists: {req.new_slug}")
    course_dir.rename(new_dir)
    # The manifest's slug names the directory, so it moves with it; the title is
    # human-authored and independent of the slug, so a rename leaves it alone.
    manifest = read_course_manifest(new_dir)
    if manifest.get("slug") != req.new_slug and manifest:
        manifest["slug"] = req.new_slug
        (new_dir / COURSE_MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return {"slug": req.new_slug}


@app.post("/api/courses/{slug}/archive")
def archive_course(slug: str) -> dict[str, Any]:
    course_dir = resolve_course_dir(slug)
    archive_root = WORKSPACE_ROOT / ARCHIVE_DIR_NAME
    archive_root.mkdir(exist_ok=True)
    target = archive_root / slug
    if target.exists():
        raise HTTPException(status_code=409, detail=f"an archived course already has this name: {slug}")
    course_dir.rename(target)
    return {"slug": slug, "archived": True}


# --- Unit grouping -----------------------------------------------------------


def _unit_progress(item_ids: set[str], histories: dict[str, dict[str, Any]]) -> dict[str, int]:
    """A unit's quiz items counted three ways against the practice log: verified (a correct
    recall on a later day than the item's own first attempt), practiced (attempted, not yet
    verified), untouched (never attempted). Counts are over items rather than lessons, and
    always sum to the number of items the unit's lessons carry."""
    counts = {"verified": 0, "practiced": 0, "untouched": 0}
    for item_id in item_ids:
        history = histories.get(item_id)
        if history is None:
            counts["untouched"] += 1
        elif _item_verified(history):
            counts["verified"] += 1
        else:
            counts["practiced"] += 1
    return counts


def _grouped_lessons(course_dir: Path) -> dict[str, Any]:
    """A course's lessons grouped into the units its manifest declares: units in manifest
    order, lessons in number order within each, every unit carrying its progress rollup, and
    every lesson keeping the shape it has always had. A unit with no lessons yet is still
    returned — declared-but-empty is the course's forward map, not an omission. Lessons
    declaring a unit the manifest does not define, or declaring none, land in `unassigned`;
    that is a legal state for a course whose structure is not settled, never an error."""
    manifest = read_course_manifest(course_dir)
    units = _course_units(manifest)
    lessons = _list_lessons(course_dir)

    members: dict[str, list[dict[str, Any]]] = {unit["id"]: [] for unit in units}
    unassigned: list[dict[str, Any]] = []
    for lesson in lessons:
        members.get(lesson["unit"], unassigned).append(lesson)

    # The quiz index is the same source the review loops filter through, so a unit's rollup
    # counts exactly the items its lessons can still present.
    items_by_lesson: dict[int, set[str]] = {}
    for entry in _lesson_quiz_index(course_dir).values():
        items_by_lesson.setdefault(entry["lesson_number"], set()).add(entry["item_id"])
    histories = _item_histories(_read_practice_events(course_dir))

    grouped: list[dict[str, Any]] = []
    for unit in units:
        item_ids: set[str] = set()
        for lesson in members[unit["id"]]:
            item_ids |= items_by_lesson.get(lesson["number"], set())
        grouped.append(
            {**unit, "lessons": members[unit["id"]], "progress": _unit_progress(item_ids, histories)}
        )
    return {
        "unit_label": _course_unit_label(manifest),
        "units": grouped,
        "unassigned": unassigned,
    }


@app.get("/api/lessons")
def get_lessons(course: str) -> dict[str, Any]:
    """A course's lessons grouped by unit: {course, unit_label, units, unassigned}. Each
    unit carries {id, title, order, color, lessons, progress}; each lesson keeps its number,
    path, title, declared unit, and derived resources. `color` is the unit's identifying hue,
    computed from `order` (see UNIT_COLORS) so every surface reads one decision."""
    course_dir = resolve_course_dir(course)
    return {"course": course, **_grouped_lessons(course_dir)}


@app.get("/api/course-overview")
def get_course_overview(course: str) -> dict[str, Any]:
    """Structured data for the course-overview page: rendered course artifacts plus the
    course files no lesson links (lesson-linked files already appear in the sidebar under
    their lesson, derived from the lesson HTML itself). The file list covers the course
    package — root files and everything under materials/ — and never the learner
    directory, whose contents reach the page through their own rendered sections."""
    course_dir = resolve_course_dir(course)
    learner = learner_dir(course_dir)
    # The course map: the same units and rollups the sidebar groups by, so both surfaces
    # read one computation rather than two descriptions of it. The grouped lessons also
    # supply the file claims below — every lesson appears in it exactly once.
    grouped = _grouped_lessons(course_dir)
    lessons = [lesson for unit in grouped["units"] for lesson in unit["lessons"]]
    lessons += grouped["unassigned"]
    claimed = {
        resource["href"]
        for lesson in lessons
        for resource in lesson["resources"]
        if resource["type"] == "file"
    }
    root_files = sorted(
        p.name
        for p in course_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.name not in COURSE_ARTIFACTS
        and p.name != COURSE_MANIFEST_NAME
        and p.name not in claimed
    )
    materials_dir = course_dir / MATERIALS_DIR_NAME
    material_files = (
        sorted(
            f"{MATERIALS_DIR_NAME}/{p.name}"
            for p in materials_dir.iterdir()
            if p.is_file() and not p.name.startswith(".")
        )
        if materials_dir.is_dir()
        else []
    )
    return {
        "title": course_title(course_dir, course),
        "unit_label": grouped["unit_label"],
        "units": grouped["units"],
        "mission_html": _render_markdown_file(learner / "MISSION.md"),
        "resources_html": _render_markdown_file(course_dir / "RESOURCES.md"),
        "notes_html": _render_markdown_file(learner / "NOTES.md"),
        "unclaimed_files": root_files + [m for m in material_files if m not in claimed],
        "learning_records": _list_learning_records(course_dir),
        "reference": _list_reference_docs(course_dir),
    }


def _build_tree(path: Path, course_dir: Path) -> dict[str, Any]:
    rel = path.relative_to(course_dir).as_posix() if path != course_dir else ""
    if path.is_dir():
        children = sorted(
            (
                _build_tree(child, course_dir)
                for child in path.iterdir()
                if not child.name.startswith(".")
            ),
            key=lambda n: (n["type"] != "dir", n["name"]),
        )
        return {"name": path.name if rel else "", "path": rel, "type": "dir", "children": children}
    return {"name": path.name, "path": rel, "type": "file"}


@app.get("/api/workspace")
def get_workspace(course: str) -> dict[str, Any]:
    course_dir = resolve_course_dir(course)
    tree = _build_tree(course_dir, course_dir)
    return {"course": course, "tree": tree["children"]}


_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".css": "text/css",
    ".js": "text/javascript",
    ".txt": "text/plain",
}


def _media_type_for(suffix: str) -> str:
    return _MEDIA_TYPES.get(suffix, "application/octet-stream")


@app.get("/api/file")
def get_file(course: str, path: str) -> Response:
    course_dir = resolve_course_dir(course)
    if _is_hidden(path):
        raise HTTPException(status_code=404, detail="not found")
    file_path = resolve_in_course(course_dir, path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {path}")

    data = file_path.read_bytes()
    return Response(content=data, media_type=_media_type_for(file_path.suffix.lower()))


@app.get("/workspace/{course}/{file_path:path}")
def get_workspace_file(course: str, file_path: str) -> Response:
    """Serve a course file at a real hierarchical URL (rather than /api/file's query-string
    form), so that a lesson HTML file's relative links — "../assets/lesson.css",
    "../MISSION.md" — resolve correctly when the lesson is loaded into an iframe."""
    course_dir = resolve_course_dir(course)
    if _is_hidden(file_path):
        raise HTTPException(status_code=404, detail="not found")
    resolved = resolve_in_course(course_dir, file_path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {file_path}")

    data = resolved.read_bytes()
    return Response(content=data, media_type=_media_type_for(resolved.suffix.lower()))


# --- External reader ---------------------------------------------------------

READER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
READER_TIMEOUT_S = 15.0
READER_MAX_BYTES = 8 * 1024 * 1024
READER_MAX_REDIRECTS = 10

RESOURCE_LOG_NAME = ".resource-log.jsonl"

_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_BODY_INNER_RE = re.compile(r"<body[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)

# Belt-and-suspenders sanitation for trafilatura's extracted markup (it already emits
# clean article HTML, but this page renders same-origin, so scripts/handlers must go).
_SCRIPT_BLOCK_RE = re.compile(r"<script\b.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_TAG_RE = re.compile(
    r"</?(?:script|style|iframe|object|embed|form|link|meta|base)\b[^>]*>", re.IGNORECASE
)
_ON_ATTR_RE = re.compile(r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_URL_ATTR_RE = re.compile(
    r"(href|src)\s*=\s*(?:\"\s*javascript:[^\"]*\"|'\s*javascript:[^']*'|javascript:[^\s>]+)",
    re.IGNORECASE,
)


def _assert_public_http_url(url: str) -> None:
    """SSRF guard: only http(s), and the host must resolve exclusively to public addresses.
    ipaddress's is_global is False for every range this must reject — 127.0.0.0/8,
    10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 (cloud metadata), ::1,
    0.0.0.0, fc00::/7, fe80::/10. Applied to every hop of a redirect chain, so the
    server can never be steered at localhost or internal services."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"only http(s) URLs can be read: {url!r}")
    host = parts.hostname
    if not host:
        raise HTTPException(status_code=400, detail=f"URL has no hostname: {url!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"could not resolve host {host!r}: {exc}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise HTTPException(
                status_code=400,
                detail=f"host {host!r} resolves to a non-public address ({ip}); refusing to fetch",
            )


def _fetch_external(url: str) -> tuple[str, bytes, str, str | None]:
    """Fetch an external resource, following redirects manually so *every* hop passes the
    SSRF guard, and streaming the final body under a hard size cap.
    Returns (final_url, body, content_type, declared_charset)."""
    current = url
    try:
        with httpx.Client(
            timeout=READER_TIMEOUT_S,
            headers={"User-Agent": READER_USER_AGENT},
            follow_redirects=False,
        ) as web:
            for _ in range(READER_MAX_REDIRECTS + 1):
                _assert_public_http_url(current)
                response = web.send(web.build_request("GET", current), stream=True)
                try:
                    if response.is_redirect and response.headers.get("location"):
                        current = str(httpx.URL(current).join(response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        raise HTTPException(
                            status_code=502, detail=f"resource returned HTTP {response.status_code}"
                        )
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > READER_MAX_BYTES:
                            raise HTTPException(
                                status_code=502, detail="resource exceeds the reader's 8MB cap"
                            )
                        chunks.append(chunk)
                    content_type = response.headers.get("content-type", "")
                    return current, b"".join(chunks), content_type, response.charset_encoding
                finally:
                    response.close()
            raise HTTPException(status_code=502, detail="too many redirects")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch resource: {exc}")


def _sanitize_extracted_html(markup: str) -> str:
    markup = _SCRIPT_BLOCK_RE.sub("", markup)
    markup = _FORBIDDEN_TAG_RE.sub("", markup)
    markup = _ON_ATTR_RE.sub("", markup)
    markup = _JS_URL_ATTR_RE.sub(r'\1="#"', markup)
    return markup


def _extracted_body_inner(markup: str) -> str:
    """trafilatura's html output wraps the article in <html><body>…</body></html>;
    the reader template only wants the inside."""
    match = _BODY_INNER_RE.search(markup)
    return match.group(1) if match else markup


# The reader page echoes the lesson document style (assets/lesson.css): paper/ink tokens,
# Archivo display over Newsreader body in a 42rem measure, sticky metadata strip on top.
# <base target="_blank"> makes every article link leave the iframe for a real tab.
READER_PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<base target="_blank">
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400..900&family=Newsreader:ital,opsz,wght@0,6..72,400..500;1,6..72,400..500&display=swap');
:root {
  --paper: #ffffff;
  --ink: #14120f;
  --ink-secondary: #44423d;
  --ink-wash: rgba(20, 18, 15, 0.04);
  --hairline: rgba(20, 18, 15, 0.12);
  --hairline-strong: rgba(20, 18, 15, 0.24);
  --rule-heavy: 3px solid var(--ink);
  --accent: #e0402b;
  --accent-deep: #b93321;
  --radius: 4px;
  --font-display: Archivo, "Helvetica Neue", Arial, sans-serif;
  --font-body: Newsreader, Georgia, "Times New Roman", serif;
  --measure: 42rem;
}
* { box-sizing: border-box; }
body {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 18px;
  line-height: 1.65;
  margin: 0;
  padding: 0 1.5rem 6rem;
}
.reader { max-width: var(--measure); margin: 0 auto; }
.reader-meta {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--paper);
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.95rem;
  color: var(--ink-secondary);
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--hairline);
}
.reader-meta a { color: var(--accent-deep); text-decoration: none; white-space: nowrap; }
.reader-meta a:hover { color: var(--ink); }
h1 {
  font-family: var(--font-display);
  font-feature-settings: "liga" 0, "calt" 0;
  font-size: 2.1rem;
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1.15;
  margin: 2rem 0;
  padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--accent);
}
h2, h3, h4 {
  font-family: var(--font-display);
  font-feature-settings: "liga" 0, "calt" 0;
  letter-spacing: -0.01em;
  margin: 2.75rem 0 1rem;
}
h2 { font-size: 1.1rem; font-weight: 800; border-top: var(--rule-heavy); padding-top: 5px; }
h3, h4 { font-size: 1rem; font-weight: 600; }
p, li { margin: 0 0 1rem; }
a { color: var(--accent-deep); }
a:hover { color: var(--ink); }
blockquote {
  margin: 1.5rem 0;
  padding: 0.25rem 0 0.25rem 1.25rem;
  border-left: 2px solid var(--hairline-strong);
  font-style: italic;
}
img { max-width: 100%; }
code {
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: 0.85em;
  background: var(--ink-wash);
  border-radius: var(--radius);
  padding: 0.1em 0.3em;
}
pre { overflow-x: auto; padding: 0.75rem; border: 1px solid var(--hairline); border-radius: var(--radius); }
pre code { background: transparent; padding: 0; }
table { border-collapse: collapse; font-size: 0.9em; }
th, td { border: 1px solid var(--hairline); padding: 0.35rem 0.6rem; text-align: left; }
hr { border: none; border-top: 1px solid var(--hairline); margin: 2rem 0; }
.reader-note { font-style: italic; color: var(--ink-secondary); margin: 2rem 0; }
</style>
</head>
<body>
<div class="reader">
  <div class="reader-meta">
    <span>${host}</span>
    <a href="${original_url}" rel="noopener">View original ↗</a>
  </div>
  <h1>${title}</h1>
${body}
</div>
</body>
</html>
""")


def _reader_page(title: str, host: str, original_url: str, body_html: str) -> str:
    return READER_PAGE_TEMPLATE.substitute(
        title=html_escape(title),
        host=html_escape(host),
        original_url=html_escape(original_url, quote=True),
        body=body_html,
    )


def _log_reader_fetch(course_dir: Path, url: str, title: str | None) -> None:
    """One JSON line per successful reader fetch — hidden file, same pattern as
    .chat-history.json. Nothing reads it yet; it seeds a future resource-search feature."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "url": url, "title": title}
    with (learner_dir(course_dir, create=True) / RESOURCE_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.get("/api/reader")
def read_external(course: str, url: str) -> Response:
    """Fetch an external lesson resource server-side and return it as a Keating-styled
    reader page (PDFs pass through raw for the browser's in-pane viewer), so external
    reading happens inside the app instead of a new tab."""
    course_dir = resolve_course_dir(course)
    final_url, body, content_type, charset = _fetch_external(url)
    host = urlsplit(final_url).hostname or ""

    if content_type.split(";")[0].strip().lower() == "application/pdf":
        _log_reader_fetch(course_dir, url, None)
        return Response(content=body, media_type="application/pdf")

    text = body.decode(charset or "utf-8", errors="replace")

    title: str | None = None
    try:
        metadata = trafilatura.extract_metadata(text)
        title = metadata.title if metadata else None
    except Exception:
        pass  # metadata extraction is best-effort; the <title> fallback below covers it
    if not title:
        match = _TITLE_TAG_RE.search(text)
        title = " ".join(html_unescape(match.group(1)).split()) if match else None

    extracted = trafilatura.extract(
        text, url=final_url, output_format="html", include_links=True, include_images=False
    )
    if extracted:
        article_html = _sanitize_extracted_html(_extracted_body_inner(extracted))
    else:
        # Paywall / JS-only page: same-styled page, one-line note, prominent escape hatch.
        article_html = (
            '<p class="reader-note">This page couldn’t be read here. '
            f'<a href="{html_escape(url, quote=True)}" rel="noopener">View the original ↗</a></p>'
        )

    _log_reader_fetch(course_dir, url, title)
    page = _reader_page(title or host, host, url, article_html)
    return Response(content=page, media_type="text/html")


@app.get("/api/chat-history")
def get_chat_history(course: str) -> dict[str, Any]:
    """Reconstruct a display-friendly transcript from the persisted .chat-history.json —
    the frontend reads this instead of keeping its own copy of conversation state, so the
    chat pane always reflects the one source of truth on disk, including across page
    reloads and course switches."""
    course_dir = resolve_course_dir(course)
    messages = load_history(course_dir)

    turns: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        content = content or []

        if role == "user":
            if content and all(b.get("type") == "tool_result" for b in content):
                continue  # internal tool-result turn, not a real user message
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if any(b.get("type") == "document" for b in content):
                text = (text + "\n\n[attached a PDF]").strip()
            if text:
                turns.append({"role": "user", "text": text, "activity": []})
        elif role == "assistant":
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            activity = [
                {"name": b.get("name"), "input": b.get("input")}
                for b in content
                if b.get("type") == "tool_use"
            ]
            if text or activity:
                turns.append({"role": "assistant", "text": text, "activity": activity})

    return {"course": course, "turns": turns}


@app.post("/api/upload")
async def upload(course: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    course_dir = resolve_course_dir(course)

    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")

    is_pdf = (file.content_type == "application/pdf") or filename.lower().endswith(".pdf")
    if not is_pdf:
        raise HTTPException(status_code=400, detail="only PDF uploads are supported right now")

    # Uploaded source material (a syllabus, an assigned reading) belongs in the course
    # package's materials/ directory, the one home for material the course is taught from.
    relative_path = f"{MATERIALS_DIR_NAME}/{filename}"
    dest = resolve_in_course(course_dir, relative_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    dest.write_bytes(data)
    return {"path": relative_path}


# --- Static frontend ---------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))

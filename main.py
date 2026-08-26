# ABOUTME: FastAPI backend for Keating: serves the UI, runs the teaching conversation against
# ABOUTME: the pedagogy package, grades attempts, and keeps each course's practice substrate.
from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import stat
import sys
import threading
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape as html_escape
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

import anthropic
import httpx
import markdown as markdown_lib
import nh3
import trafilatura
from anthropic.lib.tools import ToolError, beta_tool
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
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
WORKSPACE_ROOT_ENV_VAR = "KEATING_WORKSPACE_ROOT"

WORKSPACE_ROOT = Path(
    os.environ.get(WORKSPACE_ROOT_ENV_VAR, str(Path.home() / "keating-courses"))
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

# The platform's own state for this installation — settings.json — lives here rather than
# beside the code, because the code directory is the container image layer: owned by root,
# unwritable by the user the app runs as, and discarded when the container is replaced. The
# workspace is the one directory that is mounted, writable and persistent. Reserved on the
# same reasoning as ARCHIVE_DIR_NAME: the leading dot already hides it from dot-excluding
# listings, and naming it here means nothing can treat it as a course either.
INSTANCE_DIR_NAME = ".keating"

# Workspace subdirectories that are not courses (shared platform material lives here).
# A terminal session's own configuration — skills, settings — kept beside the courses it
# teaches from rather than in the platform. The leading dot hides it from dot-excluding
# listings; reserving it explicitly is what stops a symlink reaching it, the same way the
# archive and instance directories are handled.
AGENT_CONFIG_DIR_NAME = ".claude"

RESERVED_DIRS = {"docs", ARCHIVE_DIR_NAME, INSTANCE_DIR_NAME, AGENT_CONFIG_DIR_NAME}

# Artifact files maintained by the teach skill itself; lesson nav links to these are
# chrome, not lesson resources, and they are not "unclaimed files" either. RESOURCES.md
# sits at the course root; the rest live under one learner's own directory.
COURSE_ARTIFACTS = {"MISSION.md", "RESOURCES.md", "NOTES.md", "GLOSSARY.md"}

# A course directory splits in two. The course package — course.json, lessons/, assets/,
# materials/, RESOURCES.md — is shared and stored once: it is portable and can be handed
# to another learner as-is. Beneath learners/ sits one directory per enrolled learner,
# holding everything about how that one person is doing on the course, so that sharing a
# course never leaks a record and no learner's state is ever read from another learner's
# context (charter P25: no cross-learner visibility).
LEARNERS_DIR_NAME = "learners"

# The layout before the platform had a per-user dimension: one unnamed learner directory
# per course. Startup moves it to learners/<DEFAULT_USER_ID>/ (see
# migrate_workspace_learner_dirs); nothing else in the app reads this name.
LEGACY_LEARNER_DIR_NAME = "learner"

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
# through their dedicated tools — write_file never touches any learner directory — and an
# overwrite of either snapshot file first copies the previous version into the hidden
# state-history directory. The snapshot is the trace; consent stays a policy-layer
# obligation (TEACHING-POLICY.md requires confirming mission changes with the learner).
# All three live inside the learner's own directory.
LEARNING_RECORDS_DIR_NAME = "learning-records"
SNAPSHOT_ON_OVERWRITE = {"MISSION.md", "GLOSSARY.md"}
STATE_HISTORY_DIR_NAME = ".state-history"

# Numeric filename prefix used by lessons/ and learning-records/ entries (e.g. 0001-foo).
NUMBERED_FILE_RE = re.compile(r"^(\d+)")

MARKDOWN_EXTENSIONS = ["tables", "fenced_code"]

STATIC_DIR = Path(__file__).parent / "static"


# --- The current user ---------------------------------------------------------

# A user id names a directory under a course's learners/, so it is a security boundary
# rather than a label: it arrives from a session cookie, and anything permissive here becomes
# a path traversal into another learner's record or out of the workspace entirely. Letters,
# digits, underscore and hyphen only, no leading punctuation, 64 characters at most — and
# learner_dir() resolve-and-prefix-checks the result on top.
USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# The id the first account owns. It is an ordinary user id that bootstrap happens to assign
# to the account it creates, and it is claimable exactly once (create_account enforces that as
# a uniqueness constraint). Nothing about it is special to the routes: they resolve a user id
# from the session and pass it to learner_dir like any other.
#
# It is this value rather than a minted one because an installation that ran before accounts
# existed already keeps its record at learners/default/. Assigning it to the first account is
# what keeps that record reachable without renaming a single directory — the alternative moves
# irreplaceable data across every course in the workspace to change a name nobody sees.
DEFAULT_USER_ID = "default"


# --- Settings (platform-level, persisted to settings.json) -------------------

# The chat and grading models are read from SETTINGS at request time, so a PUT to
# /api/settings applies without a restart. Changing the chat model invalidates the
# prompt-cache prefix on the big system prompt (caches are per-model) — expected and
# harmless: the first turn after a switch pays the uncached price once.

# Instance state, so it lives in the workspace beside the courses rather than in the code
# directory (see INSTANCE_DIR_NAME): one mounted, writable, persistent location, saved by
# whichever user the app runs as and still there after the container is replaced.
SETTINGS_FILE_NAME = "settings.json"


def settings_path() -> Path:
    """Where this instance's settings live, resolved when it is asked for rather than bound
    once at import — the same rule the accounts, sessions and enrollment stores follow, and
    for the same reason: a process that is pointed at one workspace must not read or write
    another's instance state. Import-time binding makes the settings file the one piece of
    instance state that ignores where the process was pointed, which is how a test run ends
    up writing a real installation's preferences.

    It sits here rather than beside the other instance-state paths because the settings are
    loaded during import, before those are defined."""
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / SETTINGS_FILE_NAME

# The location an installation kept its settings in before instance state lived in the
# workspace. Startup migrates the file to settings_path() (see migrate_settings_file); nothing
# else in the app reads this path. It is the one path the app touches outside the workspace,
# which is why it is overridable: a process started from a checkout — a test suite, a scratch
# run against a workspace that is not the operator's — can be told to leave that checkout's
# own settings alone.
LEGACY_SETTINGS_PATH = Path(
    os.environ.get("KEATING_LEGACY_SETTINGS_PATH", str(Path(__file__).parent / "settings.json"))
)

# What a migrated settings.json is renamed to at the legacy location. The migration copies
# and sets aside rather than consuming, because that file is outside the workspace and is the
# only copy of the preferences the platform holds: a start pointed at the wrong workspace is
# then an inconvenience with a message on stdout, not preferences gone with no way back.
MIGRATED_SUFFIX = ".migrated"


class InstanceStateError(RuntimeError):
    """This installation's own state cannot be kept where it lives — the directory is occupied
    by something that is not one, the store is not a store, or the filesystem refuses."""


class InstanceStateUnavailable(InstanceStateError):
    """The filesystem itself refused an operation on this installation's state: a mount owned
    by another uid, a read-only volume, a full disk, a lock the kernel would not give.

    Told apart from the rest because it is the one kind that must not stop the app from
    starting. Nothing the app does can fix it and only the operator can, so a process that
    refuses to boot on it replaces a fixable misconfiguration with a crashloop and takes the
    diagnostic out of `docker logs` of a running container. Serving is safe precisely because
    the refusal is the filesystem's: every path that could claim an account re-reads and
    re-writes the store under the interprocess lock, and meets the same refusal there."""


# What an operator has to change when the platform cannot write its own state. It is one
# sentence in one place because the same fact surfaces at startup, from a subcommand and from
# a route, and an operator who reads it once should recognise it everywhere.
INSTANCE_STATE_HELP = (
    "the platform keeps this installation's accounts, sessions and settings there. On a "
    "container this is usually a mounted volume the app's user does not own: run the "
    'container as the volume\'s owner — the README\'s --user "$(id -u):$(id -g)" — or give '
    "that user write access to the directory."
)


@contextlib.contextmanager
def _instance_state_access(path: Path, verb: str) -> Iterator[None]:
    """Say what a refused read or write of instance state means, wherever the kernel refuses
    it.

    Every one of these is a fact about the operator's filesystem, and the message the kernel
    gives for it is a path and an errno. Raised as InstanceStateUnavailable instead, it
    reaches the one handler that answers a request and the one that answers a subcommand, and
    it arrives there carrying what to do about it."""
    try:
        yield
    except OSError as exc:
        raise InstanceStateUnavailable(
            f"cannot {verb} {path}: {exc.strerror or exc} — {INSTANCE_STATE_HELP}"
        ) from exc


def _instance_state_writes(path: Path) -> AbstractContextManager[None]:
    return _instance_state_access(path, "write")


def _instance_state_reads(path: Path) -> AbstractContextManager[None]:
    """The reads matter as much as the writes, and they come first. A .keating created by a
    correctly-run container is 0700, so a later run under a different uid cannot even stat
    what is inside it — which is refused on the path that only reads, before anything has
    tried to write."""
    return _instance_state_access(path, "read")


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
    their defaults individually.

    Unreadable covers the filesystem refusing to answer at all, and that is load-bearing: this
    runs at import, where there is no app to answer with an error and no handler to reach, so
    anything raised here is a traceback on the import line and a container that never starts.
    Which model a learner prefers must never be what stops the platform from booting."""
    merged: dict[str, Any] = {
        "chat_model": DEFAULT_SETTINGS["chat_model"],
        "grading_model": DEFAULT_SETTINGS["grading_model"],
        "layout": dict(DEFAULT_SETTINGS["layout"]),
    }
    try:
        path = settings_path()
        if not path.is_file():
            return merged
        raw = json.loads(path.read_text(encoding="utf-8"))
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


def _ensure_instance_dir(path: Path) -> None:
    """Create the directory this installation's own state lives in, naming what is in the way
    when the path is occupied by something that is not one. mkdir(exist_ok=True) tolerates an
    existing directory and nothing else, so a plain file there raises a FileExistsError whose
    message says only that the path exists — true, and useless to the person who has to fix
    it. Every write of instance state goes through here, so that never reaches a caller, and
    neither does the kernel's own refusal to create the directory at all."""
    if (path.exists() or path.is_symlink()) and not path.is_dir():
        raise InstanceStateError(
            f"{path} is not a directory — the platform keeps this installation's own state "
            "there; move or remove what is in the way and restart."
        )
    with _instance_state_writes(path):
        path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    # mkdir sets the mode only on the directory it creates, and this one predates the account
    # store on any installation that ran before accounts existed. It holds password hashes and
    # live session records now, so a wider mode is narrowed here rather than left as it was. A
    # volume whose ownership does not permit the change keeps the mode it has: the files
    # themselves are 0600, which is the protection this is defence in depth for.
    with contextlib.suppress(OSError):
        if stat.S_IMODE(path.stat().st_mode) & ~PRIVATE_DIR_MODE:
            path.chmod(PRIVATE_DIR_MODE)


def _save_settings(settings: dict[str, Any]) -> None:
    """Written through the same atomic, owner-only write every other file in the instance
    directory gets. Nothing in here is a credential, but _ensure_instance_dir leaves a wider
    directory mode alone on a volume whose ownership refuses the chmod, on the stated grounds
    that the files inside are 0600 — so one file written at the process umask is the exception
    that makes that reasoning false."""
    _write_private_json(settings_path(), settings)


def migrate_settings_file(legacy_path: Path, current_path: Path) -> None:
    """Bring an installation's settings.json from beside the code into the workspace's
    instance directory, once, at startup, so preferences saved by an older build survive the
    move. Idempotent: an installation already migrated, or one that never saved settings, is
    skipped silently. A file at both locations is an ambiguous state only a human can
    resolve, so both are left untouched and warned about.

    Copy and set aside, rather than a move, for the one property that separates this
    migration from every other one in the app: the source is outside the workspace, so a
    process pointed at a workspace its operator did not mean — a scratch run from a checkout,
    a test suite that starts the app — reaches a real file it has no business consuming. What
    it leaves behind under MIGRATED_SUFFIX is the way back.

    The destination is written through a temp file and os.replace, exactly as a save is,
    because the code directory and the workspace are routinely on different filesystems and a
    cross-device copy writes the destination in place: interrupt it and settings.json is
    truncated, which _load_settings reads as unusable and silently answers with defaults.
    Through a temp file, the file at the destination is either absent or whole.

    A settings location that cannot be created is reported and skipped rather than raised:
    where preferences are kept must never be what stops the app from starting."""
    if not legacy_path.is_file():
        return
    try:
        occupied = current_path.exists()
    except OSError as exc:
        print(
            f"keating: could not look for settings.json at {current_path}: {exc} — starting "
            f"on the defaults; the settings at {legacy_path} are left exactly where they are.",
            flush=True,
        )
        return
    if occupied:
        print(
            f"keating: settings.json exists at both {legacy_path} and {current_path} — "
            "leaving both untouched; keep the one you want by hand and restart.",
            flush=True,
        )
        return
    kept_path = legacy_path.with_name(legacy_path.name + MIGRATED_SUFFIX)
    tmp = current_path.with_suffix(".json.tmp")
    try:
        _ensure_instance_dir(current_path.parent)
        shutil.copyfile(legacy_path, tmp)
        os.replace(tmp, current_path)
        os.replace(legacy_path, kept_path)
    except (InstanceStateError, OSError) as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        print(
            f"keating: could not move settings.json to {current_path}: {exc} — starting on "
            f"the defaults; the settings at {legacy_path} are left exactly where they are "
            "and are read again once this is cleared.",
            flush=True,
        )
        return
    print(
        f"keating: migrated settings.json to {current_path}; the file it came from is kept "
        f"as {kept_path}",
        flush=True,
    )


# --- Accounts, invites and sessions -------------------------------------------

# Instance state, beside settings.json: one mounted, writable, persistent location that
# survives the container being replaced. Resolved from WORKSPACE_ROOT at call time rather
# than bound at import, so a process pointed at a different workspace reads that workspace's
# accounts and never the previous one's.
#
# THE FILES ARE THE AUTHORITY ACROSS PROCESSES; ACCOUNTS and SESSIONS below are this process's
# cache of them. There is always a second process: the operator subcommands run in their own
# interpreter (`docker exec ... python main.py disable <name>`) while the server is serving, so
# `invite`, `disable`, `set-password` and `revoke-sessions` are writes the server did not make.
# Every mutation therefore happens inside store_transaction(), which takes an OS-level lock on
# store.lock and re-reads all three files before touching them, and every read that decides who is
# signed in calls refresh_stores_if_changed() first. A cache that wrote without re-reading would
# serialize its stale copy over the operator's change and destroy it with no error anywhere —
# at the worst possible moment, a revocation during an incident.
ACCOUNTS_FILE_NAME = "accounts.json"
SESSIONS_FILE_NAME = "sessions.json"
SESSION_KEY_FILE_NAME = "session-key"

# Enrollment keeps its own file rather than joining accounts.json, on that file's own rule:
# two things share a file when one atomic write has to cover both. Redeeming an invite creates
# an account and consumes the code, and split across two files the code is spent with no
# account and no way back — so those share. Enrollment's writes touch accounts only at
# adoption, whose interrupted state is an account with no enrollments, which one `enroll`
# command repairs and which startup names. Beside that: accounts.json is rewritten on every
# failed login, and an authorization table has no business being rewritten by a password
# guess; and a corrupt accounts.json is a sign-in outage, where folding enrollment in would
# make it a sign-in outage AND the loss of who may open what. Sessions are separate for the
# same reason.
ENROLLMENTS_FILE_NAME = "enrollments.json"

# Holds nothing and is never read: the lock is deliberately not entangled with the data it
# guards, so a process killed mid-write leaves no lock behind — the kernel drops an flock when
# the descriptor closes, however the process ended.
STORE_LOCK_FILE_NAME = "store.lock"

# Files holding credentials are created 0600 and the directory 0700, both at creation rather
# than by a chmod afterwards: a chmod-after-write leaves a window in which the file is
# readable by anyone sharing the host.
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700

# argon2 at these parameters is RFC 9106's SECOND RECOMMENDED profile (m=64 MiB, t=3, p=4),
# which is where argon2-cffi's own defaults sit. Never pass a salt: the library generates one
# per hash, and a caller-supplied salt is how a password store becomes rainbow-tableable.
PASSWORD_HASHER = PasswordHasher()

# Each argon2 call allocates 64 MiB and spawns 4 threads, so unbounded concurrent logins are a
# memory-exhaustion primitive as much as a guessing surface — in a memory-limited container,
# a self-inflicted OOM. Requests past the bound queue rather than fail.
PASSWORD_HASHING_CONCURRENCY = 4
_password_hashing_slots = threading.Semaphore(PASSWORD_HASHING_CONCURRENCY)

# Verified against on a username that does not exist, so a miss costs the same work as a hit.
# Returning early instead would leak which accounts exist through response timing, which on an
# invite-only instance is exactly the fact the invite is protecting.
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))

# NIST SP 800-63B: a length floor and no composition rules. The ceiling bounds the argon2 work
# one unauthenticated request can ask for.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024

# Usernames accept the punctuation an email address needs, because "username or email" is one
# field on a personal instance and nothing downstream cares which one a person typed. Unlike a
# user id this is a label, not a path component, so it never reaches the filesystem.
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")

# The __Host- prefix is enforced by the browser: it refuses the cookie unless it carries
# Secure, Path=/ and no Domain. That makes the attributes below unforgeable by a sibling
# subdomain rather than merely requested by us.
SESSION_COOKIE_NAME = "__Host-keating_session"

# Absolute, with no sliding window and no idle timeout — deliberately. An idle timeout means
# writing a last-seen timestamp on every request, which puts a disk write in the hot path of a
# learning session and gives "when does this end" two sources of truth. Seven days rather than
# OWASP's 4-8 hours is a stated trade: the threat model is a loopback-bound personal instance
# with an HttpOnly cookie behind a script-src 'self' policy that has no nonce and no inline
# handlers, so the XSS-theft path a shorter window shortens is already narrow, and a daily
# learning habit that demands a re-login every morning is a habit people stop having. The
# escape hatches are real and immediate: POST /api/logout, and `revoke-sessions` for an
# operator who suspects a session was taken.
SESSION_TTL = timedelta(days=7)

# Five consecutive failures lock the account for fifteen minutes, correct password included.
# Per-account rather than per-IP: on a loopback-bound instance every request comes from
# 127.0.0.1, so a per-IP limit has nothing to distinguish. An operator clears a lock with
# `enable`, which takes effect on the running server at once.
#
# The cost is accepted and named in SECURITY.md: /api/login is public, so anyone who can reach
# the instance and knows a username can lock that account for a quarter of an hour. On a
# personal instance shared with a few trusted people that is an annoyance with a one-command
# fix, where an unbounded guessing surface is not.
LOGIN_FAILURE_LIMIT = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# How long an invite stays redeemable unless the operator says otherwise.
INVITE_TTL_DAYS = 7


def empty_accounts() -> dict[str, Any]:
    """Accounts and invites share one file because redeeming an invite creates an account and
    consumes the invite, and that has to be a single atomic write. Split across two files there
    is a window in which the code is spent and no account exists, which on an invite-only
    instance locks the invitee out with no way back except another invite."""
    return {"version": 1, "accounts": [], "invites": []}


def empty_sessions() -> dict[str, Any]:
    return {"version": 1, "sessions": {}}


# --- Course roles -------------------------------------------------------------

# The two roles a person can hold in one course. THEY ARE A LADDER, NOT ALTERNATIVES: an
# author is a learner who may also write the shared course package. Every learner-state route,
# every learner-state tool and every read behaves identically for both, and role_permits below
# is the only thing that separates them.
#
# Building them as alternatives is the reflex — "author" reads like a different kind of person
# — and it is wrong: the maintainer of a personal instance both learns from and authors her own
# courses, and an XOR would make her choose.
ROLE_LEARNER = "learner"
ROLE_AUTHOR = "author"
COURSE_ROLES = (ROLE_LEARNER, ROLE_AUTHOR)
ROLE_RANK = {ROLE_LEARNER: 0, ROLE_AUTHOR: 1}

# Instance admin (is_admin) confers NO course role. This is the reasoning that rejected a
# global author flag, one level up: on a personal instance the owner is the admin, so
# admin-implies-author would make every course author-writable for her, and the learner/author
# split would never activate in the deployment it exists for. An admin who wants to author a
# course enrolls herself — one command, and a deliberate act rather than an accident.


def empty_enrollments() -> dict[str, Any]:
    """An enrollment joins one account to one course with one role. The pair (user_id, course)
    is the identity and is unique; `course` is the slug, never a path, because a path would
    break on rename and would not survive the workspace being mounted somewhere else in a
    container.

    A list of dicts, mirroring ACCOUNTS["accounts"], scanned linearly the way find_account is
    scanned on every login. On an instance with a handful of people and a handful of courses
    that is a few dozen dict comparisons per request; if it ever stops being that, an index
    belongs in the cache and not in the file."""
    return {"version": 1, "enrollments": []}


# This process's cache of the three files. A request reads it without touching disk beyond the
# three stat calls refresh_stores_if_changed() makes; a mutation re-reads all three files under
# the cross-process lock, changes them here, and rewrites the whole (small) file atomically.
ACCOUNTS: dict[str, Any] = empty_accounts()
SESSIONS: dict[str, Any] = empty_sessions()
ENROLLMENTS: dict[str, Any] = empty_enrollments()

# What was on disk the last time this process read or wrote each store, as
# (inode, size, mtime_ns). Every write goes through os.replace, so the inode changes on each
# one and another process's change is detected even when it lands inside a single filesystem
# timestamp tick — which mtime alone would miss.
STORE_STAMPS: dict[str, tuple[int, int, int] | None] = {}

# Guards every read-modify-write of the three stores above against the other threads of THIS
# process; store_transaction() adds the cross-process half. Starlette runs a sync route in a
# threadpool, so login, logout and invite redemption genuinely overlap — and each of them is a
# check followed by a mutation, which is the shape that loses races. Without it one invite code
# redeemed four times at once creates four accounts, because all four pass the lookup before
# any of them consumes the code, and argon2 holds that window open for tens of milliseconds.
#
# Reentrant because redeem_invite holds it across create_account. Coarse on purpose: the whole
# point of this store is that it is a handful of entries changed a handful of times a day, and
# serializing those changes costs nothing worth measuring. Reads — every request's session
# lookup — do not take it; they are a single dict lookup on a structure only ever replaced
# wholesale.
STORE_LOCK = threading.RLock()

# The HMAC key, cached in a dict so it can be loaded lazily and reloaded. Persisted rather than
# generated per process: an in-memory key logs every user out every time the container is
# replaced, which reads as a bug and trains people to expect random logouts.
SESSION_KEY: dict[str, bytes] = {}


def accounts_path() -> Path:
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / ACCOUNTS_FILE_NAME


def sessions_path() -> Path:
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / SESSIONS_FILE_NAME


def session_key_path() -> Path:
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / SESSION_KEY_FILE_NAME


def enrollments_path() -> Path:
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / ENROLLMENTS_FILE_NAME


def store_lock_path() -> Path:
    return WORKSPACE_ROOT / INSTANCE_DIR_NAME / STORE_LOCK_FILE_NAME


# The three files this process caches, in the order they are read. Written once so that a
# fourth store cannot be added to one loop and forgotten in another — which is exactly how a
# store ends up refreshing only when a different store happens to change.
def _store_paths() -> tuple[tuple[str, Path], ...]:
    return (
        ("accounts", accounts_path()),
        ("sessions", sessions_path()),
        ("enrollments", enrollments_path()),
    )


def _file_stamp(path: Path) -> tuple[int, int, int] | None:
    """Enough of a file's identity to tell whether it is the one this process last saw. None
    for a file that is not there, which is the same answer as "no store yet"."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def _write_private_bytes(path: Path, payload: bytes) -> None:
    """Atomic write of a file only the owner may read: create the temp file at 0600, fsync it,
    then os.replace. os.replace carries the temp file's mode to the destination, so the file at
    the target path is never briefly world-readable — which a write-then-chmod would allow.

    fsync before the replace because these files are small and written a handful of times a
    day: durability here is free, and the thing being made durable is the only copy of who may
    sign in. A failed replace leaves the previous file exactly as it was."""
    _ensure_instance_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    with _instance_state_writes(path):
        descriptor = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, PRIVATE_FILE_MODE)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    _write_private_bytes(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def save_accounts() -> None:
    _write_private_json(accounts_path(), ACCOUNTS)
    STORE_STAMPS["accounts"] = _file_stamp(accounts_path())


def save_sessions() -> None:
    _write_private_json(sessions_path(), SESSIONS)
    STORE_STAMPS["sessions"] = _file_stamp(sessions_path())


def save_enrollments() -> None:
    _write_private_json(enrollments_path(), ENROLLMENTS)
    STORE_STAMPS["enrollments"] = _file_stamp(enrollments_path())


def load_accounts() -> dict[str, Any]:
    """An absent file is an instance nobody has bootstrapped yet. A file that is there but is
    not a store is refused rather than treated as absent: read as empty, it would present the
    instance as un-bootstrapped, and whoever reached it next could claim the first account —
    and with it DEFAULT_USER_ID and the record already sitting at learners/default/.

    A filesystem that refuses the read is that same refusal one layer down, and carries the
    path and what to change instead: it is the operator's mount, not their file."""
    path = accounts_path()
    with _instance_state_reads(path):
        if not path.is_file():
            return empty_accounts()
        text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstanceStateError(
            f"{path} cannot be read as the account store ({exc}) — refusing to start with no "
            "accounts, because that would offer the first account to whoever asks next. "
            "Restore the file or move it aside deliberately."
        ) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), list):
        raise InstanceStateError(f"{path} is not an account store — move it aside deliberately.")
    return {
        "version": 1,
        "accounts": raw["accounts"],
        "invites": raw.get("invites") if isinstance(raw.get("invites"), list) else [],
    }


def load_sessions() -> dict[str, Any]:
    """Unlike the account store, an unusable session file is survivable and is survived: it
    costs everyone a re-login and nothing else, which is why sessions live in their own file.
    Session churn must never put the account store at risk."""
    path = sessions_path()
    try:
        if not path.is_file():
            return empty_sessions()
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_sessions()
    if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), dict):
        return empty_sessions()
    return {"version": 1, "sessions": raw["sessions"]}


def load_enrollments() -> dict[str, Any]:
    """An absent file is a workspace that has not been adopted yet, and the absence is itself
    the marker adopt_workspace_enrollments reads.

    A file that is there but is not a store is refused rather than treated as absent, and the
    refusal is sharper here than for accounts: read as empty it would deny every course to
    everyone AND stand as the marker saying adoption has already run, which is a silent and
    permanent lockout with nothing in the log to name it."""
    path = enrollments_path()
    with _instance_state_reads(path):
        if not path.is_file():
            return empty_enrollments()
        text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstanceStateError(
            f"{path} cannot be read as the enrollment store ({exc}) — refusing to start with no "
            "enrollments, because that would take every course away from everyone and look "
            "like an already-migrated workspace. Restore the file or move it aside "
            "deliberately."
        ) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("enrollments"), list):
        raise InstanceStateError(
            f"{path} is not an enrollment store — move it aside deliberately."
        )
    return {"version": 1, "enrollments": raw["enrollments"]}


def session_key() -> bytes:
    """The key the session signature is taken under, created on first need and kept. Losing it
    logs everyone out, which is an acceptable and deliberate failure mode — it is not a
    credential store, only a way to reject garbage without a store lookup."""
    if "key" not in SESSION_KEY:
        path = session_key_path()
        with _instance_state_reads(path):
            existing = path.read_text(encoding="utf-8") if path.is_file() else None
        if existing is not None:
            SESSION_KEY["key"] = bytes.fromhex(existing.strip())
        else:
            key = secrets.token_bytes(32)
            _write_private_bytes(path, key.hex().encode("ascii") + b"\n")
            SESSION_KEY["key"] = key
    return SESSION_KEY["key"]


# Whether this process has already said the store disappeared, so a workspace that has gone
# away does not repeat the line on every request.
_STORE_VANISHED = [False]


def _stores_have_vanished() -> bool:
    """Whether a store file this process has already read is no longer there.

    Absent at startup is an instance nobody has bootstrapped. Absent after this process has read
    one is the workspace going away underneath it — an unmounted volume, a deleted directory —
    and reading that as "no accounts" would sign everyone out and present the instance as
    un-bootstrapped, which is exactly the state load_accounts refuses to invent. The same
    reading of a vanished enrollment store would revoke every role on the instance at once."""
    for name, path in _store_paths():
        if STORE_STAMPS.get(name) is not None and _file_stamp(path) is None:
            if not _STORE_VANISHED[0]:
                print(
                    f"keating: {path} is gone — keeping the accounts, sessions and enrollments "
                    "already in memory, because reading a vanished store as an empty one would "
                    "sign everyone out and report this instance as never bootstrapped.",
                    flush=True,
                )
                _STORE_VANISHED[0] = True
            return True
    _STORE_VANISHED[0] = False
    return False


def _load_stores_from_disk() -> None:
    """Replace the cache with what is on disk, and remember what that was.

    Every file is read before any dict is touched, so a read that fails leaves the cache
    exactly as it was rather than half-replaced. Clearing first would leave ACCOUNTS with no
    "accounts" key at all — not an empty store, a broken one — for every later reader to raise
    a KeyError on, in a process that is still serving."""
    if _stores_have_vanished():
        return
    accounts = load_accounts()
    sessions = load_sessions()
    enrollments = load_enrollments()
    ACCOUNTS.clear()
    ACCOUNTS.update(accounts)
    SESSIONS.clear()
    SESSIONS.update(sessions)
    ENROLLMENTS.clear()
    ENROLLMENTS.update(enrollments)
    for name, path in _store_paths():
        STORE_STAMPS[name] = _file_stamp(path)


def refresh_stores_if_changed() -> None:
    """Re-read every store when another process has written one. Three stat calls per request,
    and a read only when a file has actually moved.

    This is what makes an operator's `disable`, `set-password`, `revoke-sessions` or `enroll`
    take effect on the running server at once instead of at the next restart — and a
    revocation that takes effect only at the next restart is not a revocation.

    The condition is a loop over every store rather than a comparison of two: a store left out
    of it refreshes only when some OTHER store happens to change as well, so an operator's
    change lands if someone logs in nearby and not otherwise. Intermittently correct passes a
    hand-test and fails in production."""
    if all(STORE_STAMPS.get(name) == _file_stamp(path) for name, path in _store_paths()):
        return
    with STORE_LOCK:
        _load_stores_from_disk()


@contextlib.contextmanager
def _interprocess_store_lock() -> Iterator[None]:
    """An exclusive flock, held only across a read-modify-write and never across a password
    prompt: an operator typing at a terminal must not stall every login on the instance for as
    long as they take to type."""
    _ensure_instance_dir(store_lock_path().parent)
    with _instance_state_writes(store_lock_path()):
        descriptor = os.open(store_lock_path(), os.O_CREAT | os.O_RDWR, PRIVATE_FILE_MODE)
    try:
        # Taking the lock is the last syscall here the kernel can refuse for a reason the
        # operator owns rather than the app: no locking on the mount, or a signal. It is
        # wrapped and the yield is not, so what the caller does under the lock keeps its own
        # errors.
        with _instance_state_writes(store_lock_path()):
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


# Depth rather than a flag, in a list because it is rebound under STORE_LOCK from any thread.
_TRANSACTION_DEPTH = [0]


@contextlib.contextmanager
def store_transaction() -> Iterator[None]:
    """Enter here to change accounts, invites, sessions or enrollments. Nothing mutates
    ACCOUNTS, SESSIONS or ENROLLMENTS outside one.

    Takes the in-process lock, then the cross-process one, then re-reads every file. The
    re-read is the whole point: it is what stops this process's cache from serializing over a
    change another process made, and it is why the operator subcommands work against a server
    that is already running.

    Reentrant — redeem_invite holds it across create_account — and deliberately does not
    re-lock when it is: flock is per open file description, so a second exclusive lock taken by
    this same process would wait forever on itself."""
    with STORE_LOCK:
        if _TRANSACTION_DEPTH[0]:
            yield
            return
        with _interprocess_store_lock():
            _load_stores_from_disk()
            _TRANSACTION_DEPTH[0] = 1
            try:
                yield
            finally:
                _TRANSACTION_DEPTH[0] = 0


def reload_auth_stores() -> None:
    """Bring every store in from disk, sweeping sessions that expired while nothing was
    running. Called at startup and before every operator subcommand.

    The read takes no cross-process lock: each store is replaced atomically, so a reader always
    sees one whole file or the other — and an instance directory the app cannot even create must
    never be what stops it from starting. Only the sweep, which is a write, takes the write
    path, and only when something has actually expired."""
    _load_stores_from_disk()
    if sweep_expired_sessions():
        with store_transaction():
            sweep_expired_sessions()
            save_sessions()


def report_bootstrap_state() -> None:
    """Say, at startup, whether anyone can sign in and whether the store can be written.

    Both failures are otherwise invisible until someone tries to log in. An instance with no
    accounts looks like a working app whose password nobody knows; an instance directory the
    app cannot write looks like a healthy container that refuses every login — the HEALTHCHECK
    passes, the shell renders, and the first sign-in fails with nothing in the log explaining
    which path is at fault."""
    probe = accounts_path().parent / f".write-probe-{os.getpid()}"
    try:
        _ensure_instance_dir(accounts_path().parent)
        with _instance_state_writes(probe):
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
    except InstanceStateError as exc:
        print(
            f"keating: {exc} Until then accounts and sessions cannot be saved, so nobody "
            "will be able to sign in.",
            flush=True,
        )
        return
    if not ACCOUNTS["accounts"]:
        print(
            "keating: this instance has no accounts yet — nobody can sign in. Create the "
            "first one with:  python main.py bootstrap --username <name>",
            flush=True,
        )


# --- Passwords ----------------------------------------------------------------


def _verify_hash(stored_hash: str, password: str) -> bool:
    """The argon2 call itself. InvalidHashError is NOT a subclass of VerificationError, so
    catching only the latter turns a hand-edited or truncated stored hash into a 500 on every
    login attempt rather than a failed one."""
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_password(stored_hash: str, password: str) -> bool:
    with _password_hashing_slots:
        return _verify_hash(stored_hash, password)


def hash_password(password: str) -> str:
    with _password_hashing_slots:
        return PASSWORD_HASHER.hash(password)


def validate_password(password: str) -> None:
    """A length floor and a ceiling, and no composition rules (NIST SP 800-63B). Checked
    before any hashing happens, so a refused password costs no argon2 work."""
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"password must be at most {PASSWORD_MAX_LENGTH} characters")


def username_key(username: str) -> str:
    """The uniqueness key: NFKC-normalized and casefolded, so two accounts cannot differ only
    by the casing or the Unicode spelling a person types at the login form. The account keeps
    the username as it was given for display."""
    return unicodedata.normalize("NFKC", username).casefold()


def validate_username(username: str) -> None:
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        raise ValueError(
            "username must start with a letter or digit and use only letters, digits and "
            ". _ @ + -"
        )


# --- Accounts -----------------------------------------------------------------


def find_account(username: str) -> dict[str, Any] | None:
    key = username_key(username)
    return next((a for a in ACCOUNTS["accounts"] if a.get("username_key") == key), None)


def account_for_user_id(user_id: str) -> dict[str, Any] | None:
    return next((a for a in ACCOUNTS["accounts"] if a.get("user_id") == user_id), None)


def mint_user_id() -> str:
    """A server-minted id for every account after the first. Never taken from a request: if a
    caller could name their own id, the second account to exist would type "default" and read
    the first account's entire record."""
    while True:
        candidate = secrets.token_hex(8)
        if account_for_user_id(candidate) is None:
            return candidate


def create_account(
    username: str,
    password: str,
    *,
    is_admin: bool = False,
    user_id: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Add an account to the store. `user_id` is for the operator paths only, and bootstrap is
    the only one: it assigns DEFAULT_USER_ID so that the record a single-user installation
    already has stays reachable. No subcommand hands an existing learner directory to any other
    account, so a workspace carrying a second one keeps it on disk and out of reach. `user_id`
    is never reachable from a request body; redemption calls this without it and gets a minted
    id.

    `save=False` lets a caller that is making more than one change to the store — redemption
    creates the account and consumes the invite — commit them in one atomic write."""
    validate_username(username)
    validate_password(password)
    with store_transaction():
        if find_account(username) is not None:
            raise ValueError(f"username already taken: {username}")
        if user_id is None:
            user_id = mint_user_id()
        elif not USER_ID_RE.match(user_id):
            raise ValueError(f"invalid user id: {user_id!r}")
        elif account_for_user_id(user_id) is not None:
            raise ValueError(f"user id already taken: {user_id}")
        return _append_account(username, user_id, password, is_admin, save)


def _append_account(
    username: str, user_id: str, password: str, is_admin: bool, save: bool
) -> dict[str, Any]:
    """The write half of create_account, called inside a store transaction."""
    account = {
        "user_id": user_id,
        "username": username,
        "username_key": username_key(username),
        "password_hash": hash_password(password),
        # The only thing the session layer ever learns about how an account authenticates.
        # An OIDC subject becomes an account here exactly as a local password does, which is
        # what keeps the session layer from assuming there is a password at all.
        "auth_method": "local",
        "is_admin": is_admin,
        "created_at": datetime.now(UTC).isoformat(),
        "disabled": False,
        "failed_attempts": 0,
        "locked_until": None,
    }
    ACCOUNTS["accounts"].append(account)
    if save:
        save_accounts()
    return account


def bootstrap_account(username: str, password: str) -> dict[str, Any]:
    """The first account. Refuses once any account exists — there is no force, because the
    thing it would force is handing DEFAULT_USER_ID, and whatever record already sits at
    learners/default/, to whoever ran the command.

    Adoption runs here as well as at startup because either can come first: a from-source
    installation bootstraps before the server has ever run, so startup would have found no
    account to adopt for. Both writes land under one flock — store_transaction is reentrant."""
    with store_transaction():
        if ACCOUNTS["accounts"]:
            raise ValueError(
                f"this instance already has {len(ACCOUNTS['accounts'])} account(s) — use the "
                "invite subcommand to add another"
            )
        account = create_account(username, password, is_admin=True, user_id=DEFAULT_USER_ID)
        adopt_workspace_enrollments()
        return account


def set_account_disabled(username: str, disabled: bool) -> dict[str, Any]:
    """Disabling revokes the account's live sessions as well as refusing new logins. Without
    that, "disabled" means only "cannot sign in again" and whoever is already signed in stays
    signed in for the rest of the session's lifetime."""
    with store_transaction():
        account = find_account(username)
        if account is None:
            raise ValueError(f"no such account: {username}")
        account["disabled"] = disabled
        if not disabled:
            account["failed_attempts"] = 0
            account["locked_until"] = None
        save_accounts()
        if disabled:
            revoke_sessions_for_user(account["user_id"])
        return account


def set_account_password(username: str, password: str) -> dict[str, Any]:
    """An out-of-band password reset, by whoever holds the workspace. There is no self-service
    reset flow and no SMTP anywhere in this app: on a personal instance shared with a few
    people, an operator regenerating a credential is the whole mechanism."""
    validate_password(password)
    with store_transaction():
        account = find_account(username)
        if account is None:
            raise ValueError(f"no such account: {username}")
        account["password_hash"] = hash_password(password)
        account["failed_attempts"] = 0
        account["locked_until"] = None
        save_accounts()
        revoke_sessions_for_user(account["user_id"])
        return account


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _account_is_locked(account: dict[str, Any], now: datetime) -> bool:
    locked_until = _parse_timestamp(account.get("locked_until"))
    return locked_until is not None and now < locked_until


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """The account this username and password identify, or None.

    Every refusal — unknown username, wrong password, locked account, disabled account —
    answers None and the route turns all four into one identical response. An oracle that
    separated them would enumerate the account set, which on an invite-only instance is
    precisely what the invite exists to keep private.

    A miss still costs one argon2 verification against a dummy hash, so the four refusals are
    also indistinguishable by how long they take."""
    with store_transaction():
        return _authenticate_locked(username, password)


def _authenticate_locked(username: str, password: str) -> dict[str, Any] | None:
    """Called inside a store transaction, which serializes sign-ins. That is deliberate: the failure
    counter below is a read-modify-write, and letting five parallel wrong guesses each read
    zero would count as one. Serializing tens of milliseconds of argon2 costs nothing on an
    instance with a handful of accounts, and an exact counter is the whole lockout."""
    now = datetime.now(UTC)
    account = find_account(username) if isinstance(username, str) else None
    if account is None or account.get("disabled") or _account_is_locked(account, now):
        # Deliberately not `return None` — see the docstring. The result is discarded.
        verify_password(DUMMY_PASSWORD_HASH, password if isinstance(password, str) else "")
        return None

    if not verify_password(account.get("password_hash", ""), password):
        account["failed_attempts"] = int(account.get("failed_attempts") or 0) + 1
        if account["failed_attempts"] >= LOGIN_FAILURE_LIMIT:
            account["locked_until"] = (now + LOCKOUT_DURATION).isoformat()
        save_accounts()
        return None

    changed = bool(account.get("failed_attempts")) or account.get("locked_until") is not None
    account["failed_attempts"] = 0
    account["locked_until"] = None
    # Three lines now instead of a data migration later: a stored hash written under weaker
    # parameters is re-hashed the next time its owner successfully signs in.
    with contextlib.suppress(InvalidHashError):
        if PASSWORD_HASHER.check_needs_rehash(account["password_hash"]):
            account["password_hash"] = hash_password(password)
            changed = True
    if changed:
        save_accounts()
    return account


# --- Invites ------------------------------------------------------------------


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_invite(created_by: str, expires_days: int = INVITE_TTL_DAYS) -> str:
    """A one-time registration code, returned in the clear exactly once. Only its SHA-256 lands
    in the store, so the file at rest is not a bag of live credentials — and an operator who
    loses the code issues another rather than reading it back."""
    code = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with store_transaction():
        ACCOUNTS["invites"].append(
            {
                "code_hash": _code_digest(code),
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(days=expires_days)).isoformat(),
                "created_by": created_by,
            }
        )
        save_accounts()
    return code


def _find_invite(code: str) -> dict[str, Any] | None:
    if not isinstance(code, str) or not code:
        return None
    digest = _code_digest(code)
    for invite in ACCOUNTS["invites"]:
        if hmac.compare_digest(str(invite.get("code_hash", "")), digest):
            return invite
    return None


def redeem_invite(code: str, username: str, password: str) -> dict[str, Any]:
    """Create an account against a one-time code, consuming the code in the same write.

    The user id is minted here and is not a parameter: redemption is the one account-creating
    path a stranger can reach, so the id — which names a directory holding another learner's
    record — must not be reachable from the request at all.

    Nothing is written unless everything succeeds, so a refused username or a short password
    leaves the invite still redeemable rather than spent on a failed attempt."""
    with store_transaction():
        invite = _find_invite(code)
        if invite is None:
            raise ValueError("this invite code is not valid")
        expires_at = _parse_timestamp(invite.get("expires_at"))
        if expires_at is not None and datetime.now(UTC) >= expires_at:
            raise ValueError("this invite code has expired")
        account = create_account(username, password, save=False)
        ACCOUNTS["invites"].remove(invite)
        save_accounts()
        return account


# --- Enrollment ---------------------------------------------------------------


def role_permits(role: str, required: str) -> bool:
    """Whether a held role covers a required one. The ladder in one place, so that "an author
    is a learner too" cannot drift into an XOR at some later call site."""
    return ROLE_RANK[role] >= ROLE_RANK[required]


def _validate_role(role: str) -> str:
    if role not in COURSE_ROLES:
        raise ValueError(
            f"not a course role: {role!r} — the roles are {' and '.join(COURSE_ROLES)}"
        )
    return role


def find_enrollment(user_id: str, course: str) -> dict[str, Any] | None:
    return next(
        (
            e
            for e in ENROLLMENTS["enrollments"]
            if e.get("user_id") == user_id and e.get("course") == course
        ),
        None,
    )


def course_role(user_id: str, course: str) -> str | None:
    """The role this account holds in this course, or None where there is no record.

    None rather than a default: every caller has to decide what "no record" means instead of
    inheriting an answer, and the app's answer is open_course's — no record is no access.

    Refreshes from disk first, because an operator's `enroll` in another process is exactly the
    change this has to see. No lock: each store file is replaced atomically, so a reader always
    sees one whole file, and this sits on the hot path of every course request."""
    refresh_stores_if_changed()
    enrollment = find_enrollment(user_id, course)
    if enrollment is None:
        return None
    role = enrollment.get("role")
    return role if role in ROLE_RANK else None


def list_enrollments() -> list[dict[str, Any]]:
    """Every enrollment record, for the operator listing. Enrollment metadata is an
    administrative fact about access; nothing here is derived from what anyone did."""
    refresh_stores_if_changed()
    return [dict(e) for e in ENROLLMENTS["enrollments"]]


def enroll(user_id: str, course: str, role: str = ROLE_LEARNER) -> dict[str, Any]:
    """Join an account to a course with a role. Refuses a pair that already has one: changing
    a role is set_course_role, so "I thought I was changing a role and I created one" cannot
    happen."""
    _validate_role(role)
    with store_transaction():
        if find_enrollment(user_id, course) is not None:
            raise ValueError(
                f"{user_id} is already enrolled in {course} — use set-role to change the role"
            )
        record = {
            "user_id": user_id,
            "course": course,
            "role": role,
            "enrolled_at": datetime.now(UTC).isoformat(),
        }
        ENROLLMENTS["enrollments"].append(record)
        save_enrollments()
        return record


def set_course_role(user_id: str, course: str, role: str) -> dict[str, Any]:
    """Change an existing enrollment's role. Refuses where there is none, rather than
    upserting: an operator who mistypes a course slug should be told, not given a new record
    in a course nobody meant."""
    _validate_role(role)
    with store_transaction():
        enrollment = find_enrollment(user_id, course)
        if enrollment is None:
            raise ValueError(f"{user_id} is not enrolled in {course} — enroll them first")
        enrollment["role"] = role
        save_enrollments()
        return enrollment


def unenroll(user_id: str, course: str) -> bool:
    """Remove an enrollment, and nothing else. The learner's directory inside the course is
    left exactly where it is: removing access is not destroying a record, and an admin
    deleting someone's learning is what charter P25 forbids outright."""
    with store_transaction():
        enrollment = find_enrollment(user_id, course)
        if enrollment is None:
            return False
        ENROLLMENTS["enrollments"].remove(enrollment)
        save_enrollments()
        return True


def _rekey_course_enrollments(course: str, new_course: str) -> None:
    """Carry a course's enrollments to its new slug. Enrollments are keyed by slug, so a
    rename that skips this orphans access to the course — including the renamer's own — the
    moment it succeeds. Call inside a store transaction; the caller saves."""
    for enrollment in ENROLLMENTS["enrollments"]:
        if enrollment.get("course") == course:
            enrollment["course"] = new_course


def _drop_course_enrollments(course: str) -> None:
    """Forget a course's enrollments. Archiving without this leaves a slug that is reused
    later silently inheriting the archived course's access list. Call inside a store
    transaction; the caller saves."""
    ENROLLMENTS["enrollments"] = [
        e for e in ENROLLMENTS["enrollments"] if e.get("course") != course
    ]


# --- Sessions -----------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    """One authenticated session. `auth_method` is all the session layer knows about how the
    account proved who it was, which is what lets a future OIDC account mint a session here
    without this code learning what a password is."""

    user_id: str
    auth_method: str
    expires_at: datetime


def session_id_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def sign_session_id(session_id: str) -> str:
    return hmac.new(session_key(), session_id.encode("ascii"), hashlib.sha256).hexdigest()


def sweep_expired_sessions() -> bool:
    """Drop records past their expiry, and say whether anything went. Called on every store
    mutation and once at startup rather than on a timer: there is no background task to get
    wrong, and the store is a handful of entries."""
    now = datetime.now(UTC)
    dead = [
        digest
        for digest, record in SESSIONS["sessions"].items()
        if (expires_at := _parse_timestamp(record.get("expires_at"))) is None or now >= expires_at
    ]
    for digest in dead:
        del SESSIONS["sessions"][digest]
    return bool(dead)


def issue_session(user_id: str, auth_method: str) -> str:
    """Mint a session and return the cookie value. Any session the account already holds is
    dropped in the same write, which is what closes session fixation: a value presented to the
    login route is never reused and never re-signed, and the identifier that comes back is one
    the client has never seen.

    One active session per account is the deliberate default for a handful of trusted people.
    Signing in on the laptop ends the session on the phone, which also makes "did I leave a
    session open somewhere?" a question with an answer."""
    session_id = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with store_transaction():
        sweep_expired_sessions()
        for digest in [
            digest
            for digest, record in SESSIONS["sessions"].items()
            if record.get("user_id") == user_id
        ]:
            del SESSIONS["sessions"][digest]
        SESSIONS["sessions"][session_id_digest(session_id)] = {
            "user_id": user_id,
            "auth_method": auth_method,
            "created_at": now.isoformat(),
            "expires_at": (now + SESSION_TTL).isoformat(),
        }
        save_sessions()
    return f"{session_id}.{sign_session_id(session_id)}"


def lookup_session(cookie_value: str | None) -> Session | None:
    """The session a cookie value names, or None.

    The signature is cheap pre-screening and nothing more: it rejects garbage for the cost of
    one HMAC over 43 bytes and no store lookup at all. The server record is the sole authority,
    which is what makes revocation real — a correctly signed id whose record is gone is exactly
    what a logged-out session looks like, and it is refused."""
    if not cookie_value:
        return None
    session_id, separator, signature = cookie_value.partition(".")
    if not separator or not session_id:
        return None
    if not hmac.compare_digest(signature, sign_session_id(session_id)):
        return None
    record = SESSIONS["sessions"].get(session_id_digest(session_id))
    if record is None:
        return None
    expires_at = _parse_timestamp(record.get("expires_at"))
    if expires_at is None or datetime.now(UTC) >= expires_at:
        with store_transaction():
            if sweep_expired_sessions():
                save_sessions()
        return None
    return Session(
        user_id=str(record.get("user_id", "")),
        auth_method=str(record.get("auth_method", "local")),
        expires_at=expires_at,
    )


def revoke_session(cookie_value: str | None) -> None:
    """Delete the server record. That deletion is the revocation; clearing the cookie afterwards
    is only tidiness, and a session layer that did the clearing alone would be revocable by
    nobody."""
    if not cookie_value:
        return
    session_id = cookie_value.partition(".")[0]
    with store_transaction():
        if SESSIONS["sessions"].pop(session_id_digest(session_id), None) is not None:
            save_sessions()


def revoke_sessions_for_user(user_id: str) -> int:
    with store_transaction():
        digests = [
            digest
            for digest, record in SESSIONS["sessions"].items()
            if record.get("user_id") == user_id
        ]
        for digest in digests:
            del SESSIONS["sessions"][digest]
        if digests:
            save_sessions()
    return len(digests)


def revoke_all_sessions() -> int:
    with store_transaction():
        count = len(SESSIONS["sessions"])
        SESSIONS["sessions"].clear()
        save_sessions()
    return count


def resolve_session(request: Request) -> Session | None:
    """The one place a request's cookie becomes a session. Both the fence middleware and the
    route dependency call it, so the two cannot disagree about who is signed in.

    It is also the one place that notices another process has written the stores, which is why
    an operator's `revoke-sessions` or `disable` refuses the very next request rather than the
    first request after a restart."""
    refresh_stores_if_changed()
    return lookup_session(request.cookies.get(SESSION_COOKIE_NAME))


def require_session(request: Request) -> Session:
    """The authenticated session, or 401. Raises rather than returning None, so a route that
    declares this parameter cannot accidentally proceed without one."""
    session = resolve_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="this request needs a signed-in session")
    return session


def current_user_id(session: Session = Depends(require_session)) -> str:
    """Whose record this request is about.

    Resolved server-side from the session cookie and from nothing else: never a query
    parameter, never a body field (charter P25 — a user id names a directory holding one
    learner's record, so a caller-supplied one is a read of somebody else's).

    It is a dependency rather than ambient state on purpose. A route that needs to know whose
    record it is touching declares this parameter; a route that forgets has no user id at all
    and fails loudly at import or on the first request, where ambient identity would instead
    hand it somebody's record quietly and correctly-looking."""
    return session.user_id


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


# What this session may write, stated in the preamble rather than discovered on the first
# refused tool call. An agent that promises a lesson and only then fails is a worse session
# than one that says up front what it can do — and the prompt cache is already keyed per
# (course, user), so naming the role adds no cache dimension.
ROLE_PREAMBLES = {
    ROLE_LEARNER: (
        "You are enrolled in this course as a learner. The course package is yours to read, "
        "never to write: write_file refuses every path outside \"{learner_root}/\". The skill "
        "instructions below describe authoring lessons, assets, reference documents, "
        "RESOURCES.md and the course.json manifest "
        "— that is an author's work, and in this session you should neither attempt it nor "
        "promise it. Teach in the conversation, and keep this learner's mission, notes, "
        "glossary and learning records."
    ),
    ROLE_AUTHOR: (
        "You are enrolled in this course as an author: write_file reaches the shared course "
        "package as well as \"{learner_root}/\". The package is shared with everyone enrolled "
        "in this course, so editing an existing lesson changes it under someone who may be "
        "part-way through it."
    ),
}


def system_prompt_for(course: str, user_id: str, role: str) -> str:
    learner_root = learner_rel_path(user_id)
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
        "- The course package, shared and portable to any learner: course.json (the manifest), "
        "./lessons/, ./assets/, ./materials/ (source material such as a syllabus), "
        "./reference/, and RESOURCES.md.\n"
        f"- This learner's own state, under ./{learner_root}/: {learner_root}/MISSION.md, "
        f"{learner_root}/NOTES.md, {learner_root}/GLOSSARY.md, and "
        f"{learner_root}/learning-records/.\n\n"
        f"Wherever the instructions below write a path as \"{LEARNERS_DIR_NAME}/<your-id>/...\", "
        f"your id is \"{user_id}\" — the literal path is \"{learner_root}/...\". Other learners' "
        "directories are not yours to read, list, or write, and the tools refuse them.\n\n"
        "Your five tools — read_file, write_file, list_dir, append_learning_record, and "
        "supersede_learning_record — take paths relative to the course subdirectory "
        f"(e.g. \"{learner_root}/MISSION.md\", \"lessons/0001-foo.html\"), not relative to "
        "WORKSPACE_ROOT itself. Nothing is remapped for you: to read the mission, read "
        f"\"{learner_root}/MISSION.md\". "
        "Learning records are created only via append_learning_record (the platform computes the "
        "number and filename) and modified only via supersede_learning_record. write_file never "
        "reaches learning records, hidden files, or any other learner's directory. "
        f"Overwriting {learner_root}/MISSION.md or "
        f"{learner_root}/GLOSSARY.md preserves the previous version automatically. "
        "Files are created lazily, only when there is real content to put in them — never fabricate "
        "content to fill out the structure. Before creating a new numbered lesson, use list_dir to "
        "check what already exists and continue the numbering convention correctly.\n\n"
        + ROLE_PREAMBLES[role].format(learner_root=learner_root)
        + "\n\n"
        "The skill's own instructions follow verbatim.\n"
    )
    return preamble + "\n\n" + SKILL_TEXT


def chat_system_blocks(
    course: str, course_dir: Path, user_id: str, role: str
) -> list[dict[str, Any]]:
    """The chat call's system list, in cache-conscious order: first the big skill prompt
    (large, stable per course, user and role) carrying the cache breakpoint, then the
    volatile practice-state block WITHOUT cache_control — it rides behind the breakpoint,
    so new practice events never invalidate the cached prefix."""
    return [
        {
            "type": "text",
            "text": system_prompt_for(course, user_id, role),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": practice_state_block(course_dir, user_id),
        },
    ]


# --- Path safety -------------------------------------------------------------

def _within_root(real: Path) -> bool:
    root_real = Path(os.path.realpath(WORKSPACE_ROOT))
    return real == root_real or root_real in real.parents


def _within_course(course_dir: Path, real: Path) -> bool:
    """Whether an already-resolved path is the course directory or something inside it.

    The workspace root is the wrong boundary for anything a caller names. Courses sit side by
    side under that root, and so does the instance directory holding this installation's
    accounts, sessions and session key, so a path that merely stays under the root can still
    land in another course's learners/ or in the credential store. The course directory is the
    boundary a caller-supplied path is measured against: enrollment grants access to one
    course, and a path that leaves it has left everything the caller's role was resolved for.

    The comparison is between realpaths, so ".." segments and symlinks are both covered — a
    package can carry a symlink pointing out of itself without anyone meaning it to, since
    copying a package into the workspace is how one is installed and cp -R, tar and git all
    preserve symlinks."""
    course_real = Path(os.path.realpath(course_dir))
    return real == course_real or course_real in real.parents


def resolve_course_dir(slug: str, must_exist: bool = True) -> Path:
    if not COURSE_SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"invalid course slug: {slug!r}")
    if slug in RESERVED_DIRS:
        raise HTTPException(status_code=400, detail=f"reserved directory, not a course: {slug}")
    candidate = WORKSPACE_ROOT / slug
    real = Path(os.path.realpath(candidate))
    if not _within_root(real):
        raise HTTPException(status_code=400, detail="course path escapes workspace root")
    # Reserving the names above only rejects a slug that spells one, and COURSE_SLUG_RE
    # forbids the leading dot that would let it. A symlink in the workspace is how a slug the
    # regex accepts reaches one of these directories anyway, so the resolved path is checked
    # too: the archive holds courses withdrawn from every listing, and the instance directory
    # holds this installation's own state, and a course is neither.
    for reserved in (ARCHIVE_DIR_NAME, INSTANCE_DIR_NAME, AGENT_CONFIG_DIR_NAME):
        reserved_real = Path(os.path.realpath(WORKSPACE_ROOT / reserved))
        if real == reserved_real or reserved_real in real.parents:
            raise HTTPException(
                status_code=400, detail=f"course path resolves into {reserved}"
            )
    if must_exist and not real.is_dir():
        raise HTTPException(status_code=404, detail=f"course not found: {slug}")
    return real


def open_course(slug: str, user_id: str, *, require: str = ROLE_LEARNER) -> tuple[Path, str]:
    """The one door onto a course: path safety, then the caller's role in that course.

    Every route that takes a course goes through here and gets back the directory AND the
    role, so a route cannot hold the directory without having resolved the role. That is what
    keeps authorization from being a check somebody remembers to add — the same reasoning
    learner_dir uses in making the user id positional.

    It is a wrapper rather than a FastAPI dependency because the slug arrives three ways —
    query string, path parameter, and request body — and a dependency cannot read the body
    uniformly. One wrapper covers all three; a dependency would cover some routes and leave
    the body routes needing a second mechanism, which is two sources of truth.

    No record is 404, byte-identical to a course that is not there. Two reasons, and the
    second is the load-bearing one: it follows _assert_own_learner_path's precedent, and
    because the course list shows only enrolled courses, a 403 here would hand any account a
    workspace-wide slug-enumeration oracle — try every slug, 403 means it exists.

    Enrolled but short of the role required is 403 with a reason. Hiding it would be a lie:
    the caller can already see this course in their sidebar and open every lesson in it, so
    the refusal discloses nothing they did not already have."""
    course_dir = resolve_course_dir(slug)
    role = course_role(user_id, slug)
    if role is None:
        raise HTTPException(status_code=404, detail=f"course not found: {slug}")
    if not role_permits(role, require):
        raise HTTPException(
            status_code=403,
            detail=(
                f'authoring "{slug}" is an author\'s role; this account is enrolled as a '
                f"{role}"
            ),
        )
    return course_dir, role


def resolve_in_course(course_dir: Path, relative_path: str) -> Path:
    """Resolve a path relative to a course directory, rejecting anything that leaves it.

    The caller has resolved a role for one course; this is what holds the path it was resolved
    for to that same course, so a request cannot be authorized against one course and served
    out of another."""
    candidate = course_dir / relative_path if relative_path else course_dir
    real = Path(os.path.realpath(candidate))
    if not _within_course(course_dir, real):
        raise HTTPException(
            status_code=400, detail=f"path leads outside the course: {relative_path!r}"
        )
    return real


def _is_hidden(relative_path: str) -> bool:
    return any(part.startswith(".") for part in Path(relative_path).parts)


def learners_root(course_dir: Path) -> Path:
    """The course's learners/ directory: the parent of every enrolled learner's own
    directory, and the one part of a course that never travels with the course package."""
    return Path(os.path.realpath(course_dir)) / LEARNERS_DIR_NAME


def learner_dir(course_dir: Path, user_id: str, create: bool = False) -> Path:
    """The one place one learner's state lives inside a course: mission, notes, glossary,
    learning records, and the hidden logs and snapshots. Every read and write of learner
    state routes through here, so the course package around it stays shared and portable
    and no read ever spans two learners (charter P25: no cross-learner visibility).

    `user_id` is required and positional: a caller must say whose record it wants, so a
    missed call site fails loudly instead of silently reading the wrong person's. The id
    is validated against USER_ID_RE and the resolved path is prefix-checked against the
    course's learners/ directory, exactly as resolve_course_dir checks a slug, so "..",
    absolute paths and symlink escapes are all impossible.

    Readers leave create False — a learner carrying no state yet simply reads as empty —
    while callers about to write pass create=True to have the directory made on demand."""
    if not USER_ID_RE.match(user_id):
        raise HTTPException(status_code=400, detail=f"invalid user id: {user_id!r}")
    root_real = Path(os.path.realpath(learners_root(course_dir)))
    path = Path(os.path.realpath(root_real / user_id))
    if not _within_root(path) or root_real not in path.parents:
        raise HTTPException(
            status_code=400, detail=f"learner path escapes the course's learners directory: {user_id!r}"
        )
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _is_other_learner(real: Path, learner_real: Path, learners_real: Path) -> bool:
    """Whether a resolved path lands in some other learner's directory. Sharing courses put
    every learner's record under one parent, so every surface that resolves a caller-supplied
    path has to say no here: charter P25 makes cross-learner visibility a prohibition, not a
    permission to be checked later, and there is no context in which one learner's session
    reads another's state. The learner's own directory is of course allowed through."""
    if learners_real not in real.parents and real != learners_real:
        return False
    return real != learner_real and learner_real not in real.parents


def _assert_own_learner_path(course_dir: Path, user_id: str, real: Path) -> None:
    """Refuse a resolved path that lands in another learner's directory. The file-serving
    endpoints take an arbitrary path within a course, and a course now holds more than one
    learner's record, so this is where the widening a shared course would otherwise create
    is closed off — 404, the same answer as a path that is not there at all."""
    if _is_other_learner(real, learner_dir(course_dir, user_id), learners_root(course_dir)):
        raise HTTPException(status_code=404, detail="not found")


def learner_rel_path(user_id: str, *parts: str) -> str:
    """One learner's directory as the teaching agent addresses it: relative to the course
    root, which is what every tool path is relative to. The tools' own docstrings write
    this shape with a "<your-id>" placeholder — they are static text — and the system
    prompt's preamble names the concrete id."""
    return "/".join([LEARNERS_DIR_NAME, user_id, *parts])


def warn_if_workspace_root_is_unusable(workspace_root: Path) -> None:
    """Say so when the workspace is not a directory the app can read courses out of.

    A workspace that is not there reads exactly like a workspace that is empty: no courses,
    no records, no practice history, and every migration below no-ops in silence. Nothing in
    that picture distinguishes a mistyped path from a first run, so startup names the path it
    actually looked at.

    Where the path came from is the useful half. A path someone set and that is not there is a
    misconfiguration — a typo, or a host path handed to a container that cannot see it. The
    same path arrived at by default is an installation that has not made its courses directory
    yet, which is ordinary. The message says which one this is.

    This warns and returns rather than refusing to start: the app is still usable for creating
    a first course, and a running app showing this line is easier to diagnose than one that
    exited."""
    if workspace_root.is_dir():
        return

    if workspace_root.exists():
        print(
            f"keating: {workspace_root} is not a directory — the workspace holds one directory "
            "per course, so nothing can be read or written until this path is one."
        )
        return

    if os.environ.get(WORKSPACE_ROOT_ENV_VAR):
        print(
            f"keating: {WORKSPACE_ROOT_ENV_VAR} is set to {workspace_root}, which does not "
            "exist — every course will look missing and nothing will be saved. Check the path, "
            "and in a container check that it names a path inside the container rather than on "
            "the host."
        )
        return

    print(
        f"keating: {workspace_root} does not exist, so there are no courses to open yet. "
        f"Create it, or set {WORKSPACE_ROOT_ENV_VAR} to where your courses already live."
    )


def migrate_workspace_learner_dirs(workspace_root: Path) -> None:
    """Move every course's pre-multi-user learner/ directory to learners/<DEFAULT_USER_ID>/,
    once, at startup. Idempotent: a course already migrated, or one that never had learner
    state, is skipped silently. A course carrying both directories is an ambiguous state
    only a human can resolve, so it is left untouched and warned about."""
    if not workspace_root.is_dir():
        return
    for course_dir in sorted(workspace_root.iterdir()):
        if (
            not course_dir.is_dir()
            or course_dir.name.startswith(".")
            or course_dir.name in RESERVED_DIRS
        ):
            continue
        _migrate_course_learner_dir(course_dir)


def _migrate_course_learner_dir(course_dir: Path) -> None:
    """One course's move. The move itself is a rename, never a copy-then-delete: a
    learner's record is not duplicated on disk even momentarily, and the operation either
    happened or did not. learners/ is created only after both preconditions hold, so the
    rename's destination cannot already exist and two directories can never be merged."""
    legacy = course_dir / LEGACY_LEARNER_DIR_NAME
    root = course_dir / LEARNERS_DIR_NAME
    if not legacy.is_dir():
        return
    if root.exists():
        print(
            f"keating: {course_dir.name} has both {LEGACY_LEARNER_DIR_NAME}/ and "
            f"{LEARNERS_DIR_NAME}/ — leaving both untouched; merge them by hand and "
            "restart.",
            flush=True,
        )
        return
    root.mkdir(parents=True)
    legacy.rename(root / DEFAULT_USER_ID)
    print(
        f"keating: migrated {course_dir.name}/{LEGACY_LEARNER_DIR_NAME}/ to "
        f"{course_dir.name}/{learner_rel_path(DEFAULT_USER_ID)}/",
        flush=True,
    )


def workspace_course_slugs() -> list[str]:
    """Every course directory in the workspace, by slug. One filter, used by the course
    listing, by adoption and by the operator commands, so that "what counts as a course" has a
    single answer."""
    if not WORKSPACE_ROOT.is_dir():
        return []
    return sorted(
        p.name
        for p in WORKSPACE_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in RESERVED_DIRS
    )


def _learner_ids_in_course(slug: str) -> list[str]:
    """The user ids that already have a directory in this course. A list of directory names,
    never a look inside any of them."""
    root = WORKSPACE_ROOT / slug / LEARNERS_DIR_NAME
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and USER_ID_RE.match(p.name))


def adopt_workspace_enrollments() -> bool:
    """Give the accounts that already exist the enrollments their state implies, once, when a
    workspace written before enrollment existed first meets an instance that has one. Returns
    whether the store was written.

    The enrollment store's own existence is the marker: this runs while there is no file and
    never again. It is deliberately one-shot rather than convergent — a rule that re-derived
    enrollments from directories on every start would silently re-grant an enrollment an
    operator had just removed, at the next restart and with nothing to show why.

    It runs from startup and from bootstrap because either can come first: a from-source
    installation bootstraps before the server has ever run, and a container serves before
    anyone has claimed an account. With no accounts there is nobody to adopt, so no file is
    written — writing an empty one would mark the workspace adopted forever."""
    with store_transaction():
        if enrollments_path().exists() or not ACCOUNTS["accounts"]:
            return False
        known_ids = {a.get("user_id") for a in ACCOUNTS["accounts"]}
        records: list[tuple[str, str, str]] = []
        for slug in workspace_course_slugs():
            course_dir = WORKSPACE_ROOT / slug
            ambiguous = (course_dir / LEGACY_LEARNER_DIR_NAME).is_dir() and (
                course_dir / LEARNERS_DIR_NAME
            ).exists()
            for user_id in _learner_ids_in_course(slug):
                if user_id in known_ids:
                    records.append((user_id, slug, ROLE_LEARNER))
            if ambiguous:
                # The same state _migrate_course_learner_dir refuses to resolve, and for the
                # same reason: merged, the ambiguity is a person's record. Nobody is made this
                # course's author until a human has said whose directory is whose.
                print(
                    f"keating: {slug} still has both {LEGACY_LEARNER_DIR_NAME}/ and "
                    f"{LEARNERS_DIR_NAME}/ — merged, the ambiguity is a person's record, so "
                    "nobody was made its author. Merge the directories by hand, then: "
                    f"python main.py enroll --username <name> --course {slug} --role author",
                    flush=True,
                )
                continue
            if DEFAULT_USER_ID in known_ids:
                # Before enrollment existed this account could author every course in the
                # workspace, whether or not it had written anything in one yet. Adoption takes
                # nothing away, and it is what keeps a package copied in by hand — the
                # README's own onboarding path, which ships no learners/ at all — reachable
                # with no ceremony.
                records.append((DEFAULT_USER_ID, slug, ROLE_AUTHOR))
        ENROLLMENTS["enrollments"] = []
        for user_id, slug, role in records:
            existing = find_enrollment(user_id, slug)
            if existing is None:
                ENROLLMENTS["enrollments"].append(
                    {
                        "user_id": user_id,
                        "course": slug,
                        "role": role,
                        "enrolled_at": datetime.now(UTC).isoformat(),
                    }
                )
            elif ROLE_RANK[role] > ROLE_RANK[existing["role"]]:
                existing["role"] = role
        save_enrollments()
        return True


def report_enrollment_state() -> None:
    """Say, at startup, which courses nobody can open and which nobody can add a lesson to.

    No enrollment record means no access, which is the only answer that actually delivers this
    increment — but it is only livable if a course that has become unreachable says so. A
    package dropped into the workspace by hand is otherwise invisible, and an invisible course
    is indistinguishable from a broken app."""
    refresh_stores_if_changed()
    if not ACCOUNTS["accounts"]:
        # An instance nobody has bootstrapped has nobody to enroll, and report_bootstrap_state
        # already owns that state. Naming every course as unreachable here would tell an
        # operator to run `enroll` before there is an account to enroll.
        return
    unreachable = []
    authorless = []
    for slug in workspace_course_slugs():
        roles = [e["role"] for e in ENROLLMENTS["enrollments"] if e.get("course") == slug]
        if not roles:
            unreachable.append(slug)
        elif ROLE_AUTHOR not in roles:
            authorless.append(slug)
    if unreachable:
        noun = "course has" if len(unreachable) == 1 else "courses have"
        print(
            f"keating: {len(unreachable)} {noun} no enrollment and nobody can open "
            f"{'it' if len(unreachable) == 1 else 'them'}: {', '.join(unreachable)}.\n"
            "  Enroll someone: python main.py enroll --username <name> --course "
            f"{unreachable[0]} --role author",
            flush=True,
        )
    for slug in authorless:
        print(
            f"keating: {slug} has enrollments but no author — nobody can add a lesson to it. "
            f"python main.py enroll --username <name> --course {slug} --role author",
            flush=True,
        )


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
    # Binary masquerading as .html: return whatever was collected (nothing).
    with contextlib.suppress(UnicodeDecodeError):
        parser.feed(path.read_text(encoding="utf-8"))
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
            or top in ("lessons", "assets", LEARNERS_DIR_NAME)
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


def _list_learning_records(course_dir: Path, user_id: str) -> list[dict[str, Any]]:
    records_dir = learner_dir(course_dir, user_id) / LEARNING_RECORDS_DIR_NAME
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


def _snapshot_state_file(course_dir: Path, user_id: str, path: Path, new_content: str) -> bool:
    """Preserve a learner-state snapshot file's current contents in that learner's hidden
    state history before an overwrite replaces them (charter G13: the recorded history of
    what the learner knows must not be rewritable without trace). Applies only to the
    files named in SNAPSHOT_ON_OVERWRITE sitting directly in this learner's own directory,
    and only when the new content actually differs. Returns whether a snapshot was
    written."""
    learner_real = learner_dir(course_dir, user_id)
    if path.parent != learner_real or path.name not in SNAPSHOT_ON_OVERWRITE or not path.is_file():
        return False
    previous = path.read_bytes()
    if previous == new_content.encode("utf-8"):
        return False
    history_dir = learner_real / STATE_HISTORY_DIR_NAME
    history_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = history_dir / f"{path.stem}.{stamp}.md"
    counter = 2
    while snapshot.exists():
        snapshot = history_dir / f"{path.stem}.{stamp}-{counter}.md"
        counter += 1
    snapshot.write_bytes(previous)
    return True


# --- Claude tools (bound to one course directory per request) --------------

# What write_file's own description says it does, per role. The model reads this before it
# reaches the guard, so the two have to agree: a description promising the package to a session
# that cannot write it produces an agent that announces a lesson and then fails, which reads to
# the learner as a broken platform rather than as a role.
WRITE_FILE_DESCRIPTIONS = {
    ROLE_LEARNER: """Create or overwrite a text file in your own learner directory.
        Creates any missing parent directories automatically. This session is enrolled as a
        learner in this course, so the shared course package (course.json, lessons/, assets/,
        materials/, reference/, RESOURCES.md) is read-only here — read_file and list_dir still
        reach all of it. Learning records are created with append_learning_record and marked
        outdated with supersede_learning_record, which are the only paths to them.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root,
                inside your own learner directory ("learners/<your-id>/MISSION.md",
                "learners/<your-id>/NOTES.md", "learners/<your-id>/GLOSSARY.md"). The course
                package, another learner's directory, the learners/ root itself, and learning
                records are rejected.
            content: The full text content to write to the file.
        """,
    ROLE_AUTHOR: """Create or overwrite a text file in the current course's teaching workspace.
        Creates any missing parent directories automatically. This session is enrolled as an
        author in this course, so it writes the shared course package as well as your own
        learner directory: no other learner's directory is reachable. The package is shared
        with everyone enrolled in this course, so editing an existing lesson changes it under
        someone who may be part-way through it. Learning records are created with
        append_learning_record and marked outdated with supersede_learning_record, which are
        the only paths to them.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root
                ("lessons/0002-foo.html", "assets/lesson.css", "RESOURCES.md",
                "learners/<your-id>/MISSION.md"). Another learner's directory, the
                learners/ root itself, and learning records are rejected.
            content: The full text content to write to the file.
        """,
}


def make_tools(course_dir: Path, user_id: str, role: str) -> list[Any]:
    """The five tools one chat turn gets, bound to one course, one learner and one role.

    `role` is required and positional for the same reason `user_id` is on learner_dir: a call
    site that forgets it fails loudly rather than silently handing out the wider surface. It
    reaches exactly one tool — write_file — and one decision inside it. Reads are
    role-invariant: authoring widens what may be written and never what may be read."""
    learner_root = learner_rel_path(user_id)
    learner_real = learner_dir(course_dir, user_id)
    learners_real = learners_root(course_dir)

    def _resolve(relative_path: str) -> Path:
        candidate = course_dir / relative_path if relative_path else course_dir
        real = Path(os.path.realpath(candidate))
        if not _within_course(course_dir, real):
            raise ToolError(
                f"Path '{relative_path}' leads outside the course this session is teaching, "
                f'"{course_dir.name}". Every path is relative to that course\'s root and stays '
                "inside it: other courses, their learners and the instance's own files are not "
                "reachable from here, whatever the session's role. Use a plain path with no "
                "'..' segments."
            )
        if _is_other_learner(real, learner_real, learners_real):
            raise ToolError(
                f"Path '{relative_path}' is another learner's, or the directory that holds "
                "every learner. A learner's record is theirs alone and is never readable from "
                f"this session — the only one you can reach is your own, '{learner_root}/'."
            )
        return real

    @beta_tool
    def read_file(relative_path: str) -> str:
        """Read the full text contents of a file in the current course's teaching workspace.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root.
                The course package sits at that root ("course.json", "RESOURCES.md",
                "lessons/0001-foo.html", "assets/lesson.css", "materials/syllabus.pdf");
                this learner's own state sits under learners/<your-id>/
                ("learners/<your-id>/MISSION.md", "learners/<your-id>/NOTES.md",
                "learners/<your-id>/GLOSSARY.md",
                "learners/<your-id>/learning-records/0001-foo.md"). No other learner's
                directory can be read.
        """
        path = _resolve(relative_path)
        if not path.exists():
            raise ToolError(f"File not found: {relative_path}")
        if not path.is_file():
            raise ToolError(f"Not a file: {relative_path}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(
                f"File is not readable as UTF-8 text: {relative_path} ({exc})"
            ) from exc

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
        """Placeholder replaced by WRITE_FILE_DESCRIPTIONS[role] below: what this tool may
        write depends on the session's role, and the model has to be told the same thing the
        guard enforces.

        The Args block stays here, and stays role-neutral, because it is not replaced: the
        per-parameter descriptions in the tool's schema are read off this docstring, while
        the role-specific text is what the assignment below replaces.

        Args:
            relative_path: Path relative to the current course's teaching-workspace root
                ("lessons/0002-foo.html", "assets/lesson.css", "RESOURCES.md",
                "learners/<your-id>/MISSION.md"). Which of those this session may write is
                the description above; another learner's directory, the learners/ root
                itself, and learning records are rejected for every session.
            content: The full text content to write to the file.
        """
        # _resolve already rejects other learners' directories and the learners/ root, so
        # what remains to guard here is the same pair this tool has always guarded, now
        # under the per-learner prefix: records have dedicated tools, and the hidden logs
        # are the platform's to write. MISSION.md, NOTES.md and GLOSSARY.md stay writable —
        # the mission interview and the notes scratchpad are the agent's own work, and the
        # drafts-first rule over glossary entries is enforced by TEACHING-POLICY.md, not by
        # withholding the file.
        path = _resolve(relative_path)
        # _resolve has already eliminated every path under learners/ that is not this
        # learner's own, and learners/ itself, so after it the split is a strict binary with
        # no third case: this learner's own directory, or the shared course package. The
        # complement of the containment test _is_other_learner implements, and no new path
        # arithmetic.
        is_own_learner_state = path == learner_real or learner_real in path.parents
        if not is_own_learner_state and not role_permits(role, ROLE_AUTHOR):
            raise ToolError(
                f"Writing '{relative_path}' would change the course package for "
                f'"{course_dir.name}", which is shared with everyone enrolled in it. This '
                f"session is enrolled as a {role}, so write_file reaches only "
                f"'{learner_root}/' — mission, notes and glossary (learning records have "
                "their own tools). Do not retry this path or a variant of it. Teach it in "
                "the conversation instead, and keep this learner's mission, notes, glossary "
                "and learning records as the teaching policy describes; if this course really "
                "needs a new lesson or reference file, say so to the learner and tell them an "
                "author of this course can add it — the instance operator grants that role."
            )
        records_real = Path(os.path.realpath(learner_real / LEARNING_RECORDS_DIR_NAME))
        if path == records_real or records_real in path.parents:
            raise ToolError(
                f"Files under {LEARNING_RECORDS_DIR_NAME}/ cannot be written with write_file. "
                "Use append_learning_record to create the next record, or "
                "supersede_learning_record to mark one outdated; existing records are never "
                "edited, overwritten, or deleted."
            )
        if _is_hidden(relative_path):
            raise ToolError(
                f"Path '{relative_path}' has a dot-path component. Hidden files are the "
                "platform's own logs and histories and cannot be written by tools; use a "
                "plain path relative to the course root (no '..' segments)."
            )
        if path.is_dir():
            # Without this the write raises IsADirectoryError out of the tool, which reaches
            # the model as an unhandled traceback rather than something it can act on.
            raise ToolError(
                f"'{relative_path}' is a directory, not a file. Give a path that includes the "
                "filename you mean to write."
            )
        snapshot_note = (
            "\nPrevious version preserved in the course's state history."
            if _snapshot_state_file(course_dir, user_id, path, content)
            else ""
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {relative_path}" + snapshot_note

    @beta_tool
    def append_learning_record(title: str, body: str) -> str:
        """Create the next sequentially numbered learning record in
        learners/<your-id>/learning-records/. The platform computes the number, the
        filename and the directory — never pick or reuse one yourself.
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
        records_dir = learner_dir(course_dir, user_id, create=True) / LEARNING_RECORDS_DIR_NAME
        records_dir.mkdir(exist_ok=True)
        highest = max((_numbered_prefix(p.name) for p in _record_files(records_dir)), default=0)
        filename = f"{highest + 1:04d}-{slug}.md"
        (records_dir / filename).write_text(
            f"# {title.strip()}\n\n{body.strip()}\n", encoding="utf-8"
        )
        return f"Created {learner_rel_path(user_id, LEARNING_RECORDS_DIR_NAME, filename)}"

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
        records_rel = learner_rel_path(user_id, LEARNING_RECORDS_DIR_NAME)
        records_dir = learner_dir(course_dir, user_id) / LEARNING_RECORDS_DIR_NAME
        by_number = {_numbered_prefix(p.name): p for p in _record_files(records_dir)}
        target = by_number.get(record_number)
        if target is None:
            raise ToolError(
                f"No learning record numbered {record_number:04d} exists in "
                f"{records_rel}/ — use "
                f'list_dir("{records_rel}") to see what is there.'
            )
        if superseded_by not in by_number:
            raise ToolError(
                f"No learning record numbered {superseded_by:04d} exists in "
                f"{records_rel}/ — create the replacement record with "
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
            f"Marked {learner_rel_path(user_id, LEARNING_RECORDS_DIR_NAME, target.name)} as "
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
                learners/, which holds one directory per learner. Only your own,
                learners/<your-id>/, can be listed.
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

    # BaseFunctionTool keeps its description as a plain attribute, so the role-specific text
    # is assigned here rather than duplicating the whole function body per role.
    write_file.description = WRITE_FILE_DESCRIPTIONS[role]
    return [read_file, write_file, list_dir, append_learning_record, supersede_learning_record]


# --- Conversation persistence -----------------------------------------------

def history_path_for(course_dir: Path, user_id: str) -> Path:
    return learner_dir(course_dir, user_id) / ".chat-history.json"


def load_history(course_dir: Path, user_id: str) -> list[dict[str, Any]]:
    path = history_path_for(course_dir, user_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("messages", [])


def save_history(course_dir: Path, user_id: str, messages: list[dict[str, Any]]) -> None:
    path = learner_dir(course_dir, user_id, create=True) / history_path_for(course_dir, user_id).name
    path.write_text(json.dumps({"messages": messages}, indent=2, ensure_ascii=False), encoding="utf-8")


def block_to_jsonable(block: Any) -> dict[str, Any]:
    """One block of a model reply, in the shape the next turn's request will carry it back in.

    The history file is replayed verbatim as the messages of every later turn, so what is
    stored has to be something the API accepts as input. A reply block is not that on its own:
    a text block comes back carrying the parsed output the SDK derived from it, and sending
    that field back is a 400 that fails every turn after the first.

    The SDK marks such fields on the model itself, in __api_exclude__, and drops them when it
    serializes a model the caller hands it. Blocks reloaded from this file are plain dicts and
    never meet that step, so the same rule is applied once, here, on the way to disk — the
    dump options match the SDK's so that what is stored is what it would have sent."""
    if hasattr(block, "model_dump"):
        return block.model_dump(
            mode="json",
            by_alias=True,
            exclude_unset=True,
            exclude=getattr(block, "__api_exclude__", None),
        )
    return block  # already a plain dict (e.g. loaded from disk)


def refused_tool_use_ids(messages: Iterable[Any]) -> set[str]:
    """The ids of the tool calls that were refused rather than run.

    A tool call and its outcome are two separate messages: the model's tool_use block, then
    the tool_result block carrying is_error when the tool raised. Reading the outcome from the
    result — the only place it is recorded — is what keeps the activity a turn reports from
    claiming a write that a guard refused."""
    refused: set[str] = set()
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                refused.add(block.get("tool_use_id"))
    return refused


# --- FastAPI app -------------------------------------------------------------

@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup work, before the first request is served, so a workspace written by an older
    build is read correctly rather than read as empty: report a workspace root that cannot
    hold courses, move any course still carrying the pre-multi-user learner/ directory into
    learners/<DEFAULT_USER_ID>/, and bring a source installation's settings.json into the
    workspace's instance directory. The report comes first because both migrations no-op in
    silence on a root that is not there, which is what makes that state hard to recognise.

    SETTINGS is read at import, which is before the migration can have put the file where the
    app reads it from, so it is read again here. The account and session stores are read here
    for the same reason and are the process's authority from this point on.

    An instance with no accounts starts normally and says how to make one: the shell, its
    assets and GET /api/session stay public, so the login view can render the command instead
    of a form nobody on the instance can satisfy."""
    warn_if_workspace_root_is_unusable(WORKSPACE_ROOT)
    migrate_workspace_learner_dirs(WORKSPACE_ROOT)
    migrate_settings_file(LEGACY_SETTINGS_PATH, settings_path())
    SETTINGS.clear()
    SETTINGS.update(_load_settings())
    try:
        reload_auth_stores()
    except InstanceStateUnavailable as exc:
        # Serving on whatever the cache holds — which at startup is nothing — rather than not
        # serving at all. See InstanceStateUnavailable: the same filesystem refuses every
        # write, so no account can be claimed here, and a process that exited instead would
        # leave the operator a traceback and a restart loop in place of the line
        # report_bootstrap_state is about to print.
        print(f"keating: {exc}", flush=True)
    report_bootstrap_state()
    try:
        adopt_workspace_enrollments()
        report_enrollment_state()
    except InstanceStateError as exc:
        # Adoption is a write, and both it and the report read the same instance directory the
        # accounts live in. A filesystem that refuses them refuses every account write too, so
        # this is an instance nobody can sign in to — which report_bootstrap_state has just
        # said, above, in the operator's own terms. Exiting here would replace that diagnostic
        # with a crashloop.
        print(f"keating: this workspace's enrollments could not be read or written: {exc}", flush=True)
    yield


app = FastAPI(title="keating", lifespan=_lifespan)


# --- Content Security Policy -------------------------------------------------

# Script running in the app's origin carries the signed-in learner's session with it, so it
# drives the whole API as them — including the file reads and writes that per-learner
# isolation enforces server-side by path. Authentication does not narrow that: a session
# cookie is exactly what a script in this origin gets to use. So the policy is written per
# trust level rather than once for the app, and the three levels are the three kinds of
# markup the app serves: written by the app, written by the course, fetched from the web.
#
# Both font hosts are named literally in every policy that needs them. That is a
# third-party origin hard-coded into a security policy, deliberately: assets/lesson.css
# and the reader page both @import Google Fonts, and a course package that reaches for a
# different third-party font host will be blocked — correct, but it will look like a bug
# to whoever hits it. Naming font-src at all stops default-src being consulted for a
# font, which is why 'self' is spelled out beside the hosts wherever a course package may
# ship a webfont of its own.

# GET / — the app shell. The top-level document, so nothing may frame it. app.js and
# quiz.js carry no inline handlers, no eval and no string timers, so script-src needs no
# escape hatch; frame-src 'self' is for the five same-origin iframes app.js builds.
CSP_APP_SHELL = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

# Course-authored pages: lesson files, the daily review, the weekly review. All four are
# rendered inside the shell's preview iframe, so frame-ancestors is 'self' rather than
# 'none' — 'none' here blanks the reading pane. connect-src 'self' is what keeps grading
# alive: quiz.js POSTs attempts from inside the lesson iframe.
#
# script-src 'self' with no nonce imposes a course-authoring contract: lesson
# interactivity goes through /static/, not through an inline <script>. style-src accepts
# 'unsafe-inline' as the deliberate concession — the review and weekly templates carry
# inline <style>, and _source_line emits a style="--unit-hue: …" per item. The residual
# risk of inline style in authored content is a background-image beacon, and img-src
# 'self' closes exactly that.
CSP_COURSE_AUTHORED = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self'; "
    "media-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'"
)

# /api/reader — the one surface carrying arbitrary third-party markup, and the one surface
# that needs no script at all. That asymmetry is what the whole defense turns on: the
# reader template contains no <script>, and an archived article has no legitimate reason
# to execute anything, so script-src 'none' removes the entire bug class rather than
# chasing it.
#
# style-src takes a per-response nonce, not 'unsafe-inline': the reader's own <style>
# block must apply while a third-party style="" must not, and only a nonce splits those
# two. The @import of the font stylesheet sits inside that nonced block, and @import is
# governed by style-src, which is why the font host appears here too. img-src 'none'
# pairs with omitting <img> from the allow-list — two independent locks, so flipping
# trafilatura's include_images cannot leak a read receipt by accident.
#
# sandbox is delivered in the header rather than as an iframe attribute, so the untrusted
# document lands in an opaque origin regardless of who frames it or how; an attribute in
# app.js is one careless edit from being dropped. allow-same-origin is absent on purpose.
# allow-popups and allow-popups-to-escape-sandbox keep <base target="_blank"> working.
CSP_READER = (
    "default-src 'none'; "
    "script-src 'none'; "
    "style-src 'nonce-{nonce}' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'; "
    "sandbox allow-popups allow-popups-to-escape-sandbox"
)

# The reader's PDF pass-through. No sandbox: the browser renders a PDF through an internal
# viewer document, and a sandbox directive without allow-scripts is a plausible way to
# break it.
CSP_READER_PDF = (
    "default-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'"
)

# Everything the middleware has to fill in for: JSON responses, static subresources,
# errors, and any future route whose author forgets to name a policy. Deny-by-default is
# the point — a permissive fallback would land a lax policy on precisely the surface that
# must not have one, whereas this leaves a forgotten route inert and visibly broken.
# Harmless where it lands today: a subresource's own CSP is never consulted, only the
# embedding document's.
#
# frame-ancestors is 'self' rather than 'none' because this is the policy an error carries.
# An HTTPException never runs the route body that names a framed policy, so a failure on
# any of the routes the reading pane frames arrives here — and 'none' makes the browser
# refuse the frame outright, replacing the reason the resource would not open with an
# empty pane. 'self' still denies every cross-origin framer; the only same-origin framer
# is the app, which can already read any of these responses with fetch.
CSP_LOCKED_DOWN = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'self'; "
    "sandbox"
)


# --- The authentication fence -------------------------------------------------

# Everything reachable without a session, and the complete list of it.
#
# The login view is a state of the app shell rather than a page of its own, so what has to stay
# open is the shell document, the assets it is built from, and the three routes the view itself
# calls. GET / in particular must stay public for a second reason: the container's HEALTHCHECK
# fetches it, and gating it reports a working instance as unhealthy — a five-minute mistake
# with a thirty-minute diagnosis.
#
# ADDING A LINE HERE OPENS A ROUTE TO THE INTERNET. test_every_route_is_either_public_or_
# authenticated fails when a new route declares no auth dependency, and the fix is to declare
# one, not to name the route here. These five entries should stay five.
PUBLIC_PATHS = {
    "/",
    "/static/index.html",
    "/api/session",
    "/api/login",
    "/api/invite/redeem",
}
PUBLIC_PREFIXES = ("/static/",)

# Methods that change something. GET is not among them, with one named exception below.
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# GET routes that are not reads. /api/reader appends to the learner's resource log and makes a
# server-side outbound fetch to a caller-chosen URL, and SameSite=Lax deliberately does send
# the cookie on a top-level cross-site GET navigation, so it is guarded like a write. GET
# /review and GET /weekly record nothing and are not listed.
GUARDED_GET_PATHS = frozenset({"/api/reader"})

# What a browser reports for a request the person actually asked for: same-origin fetches from
# the app's own script, and top-level navigations typed or bookmarked ("none").
SAME_SITE_FETCH_VALUES = frozenset({"same-origin", "none"})

# The document a route serves when the session is gone, in the two situations it is read in.
# A refusal has to be something a person can act on rather than a blank pane — an app that is
# merely logged out looking broken is the failure this increment exists to remove.
#
# Framed: the reading pane frames five routes, so a refusal has to be readable there. It offers
# no link, because the surface's own CSP sandboxes it — following a link would load the shell
# inside that sandbox, where its script cannot run, and the person would get the blank pane
# this document exists to avoid. The shell notices the session is gone on its own next call and
# replaces the whole frame with the login view, so what this document has to do is explain the
# pane, not navigate out of it. Not a redirect to a login page either: that would nest a
# credential form inside an iframe, and a login page carrying frame-ancestors 'none' (which a
# credential surface must) would refuse to render at all.
#
# Top level: /review/{course} and /weekly/{course} are bookmarkable, so a person can arrive at
# one directly with an expired session. Here "reload" is no help — reloading serves this same
# refusal — and without a link the only way back is hand-editing the URL.
SESSION_ENDED_FRAMED_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Session ended</title></head>
<body>
<h1>Your Keating session has ended</h1>
<p>Reload Keating to sign in again.</p>
</body>
</html>
"""

SESSION_ENDED_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Session ended</title></head>
<body>
<h1>Your Keating session has ended</h1>
<p><a href="/">Sign in to Keating</a> to pick this up again.</p>
</body>
</html>
"""

# What a browser reports for a document loaded into a frame. A request with none of these is
# either a top-level navigation or a browser too old to say (Safari before 16.4), and both get
# the linked document: a stale bookmark is a dead end without it, where the cost of guessing
# wrong the other way is one click that lands on an empty pane in a browser that is both old
# and framed.
FRAMED_FETCH_DESTINATIONS = frozenset({"iframe", "frame", "embed", "object"})

UNAUTHENTICATED_DETAIL = "this request needs a signed-in session"


def _own_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def is_cross_site_request(request: Request) -> bool:
    """Whether a state-changing request came from somewhere other than the app itself.

    SameSite=Lax alone is NOT enough here, which is the one thing about this app's threat model
    that is easy to get wrong. SameSite is *site*-scoped and a port is not part of a site, so
    any other service on 127.0.0.1 — and a developer machine usually runs several — is same-site
    to Keating and can drive a cookie-bearing POST at it. Lax sends the cookie on exactly that
    request; only this check refuses it.

    Origin is the primary signal: every browser has sent it on cross-origin state-changing
    requests for two decades, Safari included. Sec-Fetch-Site is secondary and is the only
    signal available for the guarded GET, which as a navigation carries no Origin.

    Both headers absent means a non-browser client — curl, httpx, the test suite, the container
    smoke test — and is allowed. An attacker cannot induce a victim's curl to attach the
    victim's cookies, so refusing here would buy nothing while costing every non-browser caller
    a bypass to be granted somewhere, which is worse.

    form-action 'none' in the CSP buys nothing against this and is not counted toward it: CSP
    is enforced per-document by the document that declares it, and an attacker's page ships its
    own policy. It is an XSS mitigation.
    """
    guarded = (
        request.method.upper() in STATE_CHANGING_METHODS
        or request.url.path in GUARDED_GET_PATHS
    )
    if not guarded:
        return False
    origin = request.headers.get("origin")
    if origin is not None:
        return origin != _own_origin(request)
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in SAME_SITE_FETCH_VALUES
    return False


def unauthenticated_response(request: Request) -> Response:
    """401 for everyone, differing only in media type. Content negotiation rather than a list
    of framed paths, so a route added later needs no registration to refuse readably."""
    if "text/html" in request.headers.get("accept", ""):
        framed = request.headers.get("sec-fetch-dest", "") in FRAMED_FETCH_DESTINATIONS
        body = SESSION_ENDED_FRAMED_HTML if framed else SESSION_ENDED_HTML
        return HTMLResponse(body, status_code=401)
    return JSONResponse({"detail": UNAUTHENTICATED_DETAIL}, status_code=401)


@app.middleware("http")
async def require_authentication(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Deny by default, before routing.

    This is not a second source of truth beside the current_user_id dependency; the two answer
    different questions and both call resolve_session. The dependency answers "whose record is
    this?" and belongs to the routes that touch learner state or resolve a course role. The
    fence answers "is there a session at all?", which is what the settings routes need — they
    authenticate but have no user id, so forgetting a dependency there would leave them
    silently open rather than loudly broken. The fence closes exactly that gap.

    Registered BEFORE attach_security_headers, which makes that middleware the outer one: a 401
    or 403 returned here still passes through it and picks up CSP_LOCKED_DOWN, whose
    frame-ancestors 'self' is what lets a refusal render in the reading pane.
    """
    if is_cross_site_request(request):
        return JSONResponse(
            {"detail": "cross-site request refused"},
            status_code=403,
        )
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    try:
        session = resolve_session(request)
    except InstanceStateError as exc:
        # Retiring an expired session is a write, and it happens here rather than in a route:
        # middleware runs outside the handler stack, so this is the one request path where
        # instance_state_unavailable cannot answer for itself.
        return instance_state_response(exc)
    if session is None:
        return unauthenticated_response(request)
    return await call_next(request)


@app.middleware("http")
async def attach_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Fill in the security headers any response left unset. Routes that serve a document
    name their own policy at the point they build the response; setdefault leaves those
    alone and locks down everything else."""
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP_LOCKED_DOWN)
    # /api/file and /workspace map Content-Type from the file suffix, so a course file
    # with a misleading suffix must not be sniffable into HTML.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # A reader link leaving for a third-party site would otherwise carry a Referer holding
    # the whole /api/reader URL: the course slug and the article being read.
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


def instance_state_response(exc: InstanceStateError) -> Response:
    """The one answer to a request that needed to write the platform's own state and could not.

    503, because the instance is serving and its state store is what is unavailable, and the
    message the exception carries, because it names the path and what to change. A 500 here
    would be true and useless — the caller would learn only that something went wrong, and the
    reason would be in a traceback in a log they may not have."""
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(InstanceStateError)
async def instance_state_unavailable(request: Request, exc: InstanceStateError) -> Response:
    """Every route that writes accounts, sessions or settings reaches this, which is what makes
    a login, a settings save and an invite redemption answer a broken volume identically."""
    return instance_state_response(exc)


@app.exception_handler(Exception)
async def locked_down_server_error(request: Request, exc: Exception) -> Response:
    """Starlette builds its own 500 response outside the user middleware stack, so that one
    response is the only one attach_security_headers never sees. Naming a handler puts it
    back under the same headers; Starlette re-raises afterwards, so the traceback still
    reaches the log."""
    return Response(
        "Internal Server Error",
        status_code=500,
        media_type="text/plain",
        headers={
            "Content-Security-Policy": CSP_LOCKED_DOWN,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


# What an operator has to do when the platform cannot reach the model, in one place, so the
# same misconfiguration reads the same way on every surface that hits it.
MODEL_CREDENTIAL_HELP = (
    "no Anthropic credentials are configured, so the platform cannot reach the model — put "
    "ANTHROPIC_API_KEY in the environment or in the .env file the app reads at startup, or "
    "run `ant auth login` once so the SDK finds your stored credentials, then restart."
)

# One client for the whole installation, reached only through model_call below. Building it
# resolves nothing: the SDK looks for a credential when a request is issued, so a process
# started with no key looks entirely healthy until the first model call.
_MODEL_CLIENT = anthropic.Anthropic()


@contextlib.contextmanager
def model_call(what: str) -> Iterator[anthropic.Anthropic]:
    """The way to the model, and the only one. Every failure that is about the installation
    rather than about the request comes back as a 502 the UI can show and a person can act on.

    The credential check is made here rather than left to the SDK because the SDK's own
    refusal is a TypeError raised while it assembles headers — a message about
    `X-Api-Key` and omitted headers, thrown from inside a library the operator did not
    write. Catching that TypeError instead would work, and would also swallow every genuine
    argument mistake at a call site.

    Enter this for the whole span in which the SDK can raise, not just the call that starts
    it: the tool runner issues its first request when it is iterated, so a guard around its
    construction alone would guard nothing."""
    if not (_MODEL_CLIENT.api_key or _MODEL_CLIENT.auth_token or _MODEL_CLIENT.custom_auth):
        raise HTTPException(status_code=502, detail=MODEL_CREDENTIAL_HELP)
    try:
        yield _MODEL_CLIENT
    except anthropic.AuthenticationError as exc:
        # A credential exists and Anthropic refused it: expired, revoked, or for another
        # organisation. Nothing about the workspace or the request can fix that.
        raise HTTPException(
            status_code=502,
            detail=f"Anthropic rejected the configured credentials ({exc.message}) — check "
            "ANTHROPIC_API_KEY.",
        ) from exc
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"{what} failed: {exc}") from exc


class ChatRequest(BaseModel):
    course: str
    message: str
    attach_pdf: str | None = None


class NewCourseRequest(BaseModel):
    slug: str


class RenameCourseRequest(BaseModel):
    new_slug: str


# --- Signing in and out -------------------------------------------------------

# One answer for every way a sign-in can fail: unknown username, wrong password, locked
# account, disabled account. Distinguishing them would let anyone enumerate the account set of
# an instance whose account set is meant to be private, and would announce a lockout to the
# one caller who benefits from knowing about it. The operator sees the real state through the
# `accounts` subcommand.
INVALID_CREDENTIALS_DETAIL = "invalid username or password"


class LoginRequest(BaseModel):
    username: str
    password: str


class InviteRedemptionRequest(BaseModel):
    """What a stranger holding a code may choose. Notably absent: user_id. That names a
    directory holding a learner's record, so it is minted server-side and is not a field a
    request can carry (charter P25)."""

    code: str
    username: str
    password: str


def _set_session_cookie(response: Response, value: str) -> None:
    """Starlette's set_cookie defaults both secure and httponly to False, so every attribute
    here is passed explicitly rather than relied on. Secure is unconditional: browsers treat
    loopback as a trustworthy origin and send the cookie over plain HTTP there, which is
    verified end to end in the browser suite. It fails closed on a LAN address, which is
    correct — serving this app off loopback without TLS is not a supported deployment."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        value,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    """The attributes must match the ones the cookie was set with, and so must the __Host-
    name, or the browser keeps a cookie that no longer matches anything."""
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", httponly=True, secure=True, samesite="lax"
    )


@app.get("/api/session")
def get_session(request: Request) -> dict[str, Any]:
    """Whether this browser is signed in, and whether the instance has an account at all.

    Public, and the first thing the shell asks: the frontend gates every other fetch on this,
    so a logged-out app shows the login view rather than rendering an empty shell that looks
    like a broken one.

    `bootstrapped` is false only before the first account exists, and the login view renders
    the bootstrap command instead of a form nobody could satisfy. It says nothing about who the
    accounts are — only that there are some."""
    session = resolve_session(request)
    if session is None:
        return {"authenticated": False, "bootstrapped": bool(ACCOUNTS["accounts"])}
    account = account_for_user_id(session.user_id)
    return {
        "authenticated": True,
        "bootstrapped": True,
        # The signed-in account's own username, so a signed-in app is never anonymous-looking.
        # Nothing about any other account, and nothing about learning, is reachable here.
        "username": account["username"] if account else session.user_id,
    }


@app.post("/api/login")
def login(req: LoginRequest) -> Response:
    """Sign in, minting a fresh session and dropping any the account already held.

    Sync def rather than async: argon2 at these parameters takes tens of milliseconds and
    allocates 64 MiB, and in an async def that would stall every other request on the event
    loop. Starlette runs a sync route in the threadpool, which is where this work belongs."""
    account = authenticate(req.username, req.password)
    if account is None:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
    value = issue_session(account["user_id"], account.get("auth_method", "local"))
    response = JSONResponse({"username": account["username"]})
    _set_session_cookie(response, value)
    return response


@app.post("/api/logout")
def logout(request: Request, session: Session = Depends(require_session)) -> Response:
    """Delete the server-side record. That deletion is the revocation: the same cookie value,
    replayed by hand afterwards, is refused by the server rather than merely missing from a
    client that agreed to forget it."""
    revoke_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = JSONResponse({"authenticated": False})
    _clear_session_cookie(response)
    return response


@app.post("/api/invite/redeem")
def redeem_invitation(req: InviteRedemptionRequest) -> dict[str, Any]:
    """Create an account against a one-time code. The only way an account comes into existence
    over HTTP, and there is deliberately no open signup anywhere: an instance that holds an API
    key and accepts anyone's registration is a billing incident waiting to happen.

    Redeeming does not sign the new account in. Holding a code proves possession of the code,
    not of the password just chosen, so the account signs in through the same route as
    everyone else."""
    try:
        account = redeem_invite(req.code, req.username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"username": account["username"]}


@app.post("/api/chat")
def chat(req: ChatRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    # One resolution of the role, threaded from here into both the tools and the system
    # prompt. Resolving it twice is how the model comes to be told one thing and enforced
    # another.
    course_dir, role = open_course(req.course, user_id)
    messages = load_history(course_dir, user_id)

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

    tools = make_tools(course_dir, user_id, role)
    system = chat_system_blocks(req.course, course_dir, user_id, role)

    activity: list[dict[str, Any]] = []
    last = None
    with model_call("chat") as client:
        runner = client.beta.messages.tool_runner(
            model=SETTINGS["chat_model"],
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=messages,
            system=system,
        )
        try:
            for message in runner:
                last = message
                messages.append(
                    {
                        "role": "assistant",
                        "content": [block_to_jsonable(b) for b in message.content],
                    }
                )
                calls = {
                    block.id: {"name": block.name, "input": block.input}
                    for block in message.content
                    if getattr(block, "type", None) == "tool_use"
                }
                activity.extend(calls.values())
                tool_response = runner.generate_tool_call_response()
                if tool_response is not None:
                    # The results come back in the same pass that runs the tools, so a call a
                    # guard refused is marked here rather than reported as something that
                    # happened. The learner reads this log to see what the session did.
                    for tool_use_id in refused_tool_use_ids([tool_response]):
                        if tool_use_id in calls:
                            calls[tool_use_id]["refused"] = True
                    messages.append(tool_response)
        finally:
            # Persist what the turn actually did — every message the model sent and every
            # tool call that ran under it — even if a later iteration raised, and before
            # model_call maps that raise to an answer.
            #
            # A turn the model never answered at all did none of that, and the only thing
            # left to persist would be the learner's own message with nothing after it,
            # carried into the context of every later turn. That is the same non-answer
            # whether the credential was missing, refused, or the network was down, so the
            # condition is what the turn produced and not which way it failed.
            if last is not None:
                save_history(course_dir, user_id, messages)

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
def get_settings(session: Session = Depends(require_session)) -> dict[str, Any]:
    """Current settings plus the static model catalog the UI renders its selects from."""
    return {**SETTINGS, "models": MODEL_CATALOG}


@app.put("/api/settings")
def put_settings(req: SettingsPayload, session: Session = Depends(require_session)) -> dict[str, Any]:
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
    # A save that cannot happen is a fact about the operator's filesystem — a read-only
    # mount, a file where the instance directory belongs — and instance_state_unavailable
    # answers it with the path and what to change, the same way a login on the same volume
    # is answered.
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


def _append_practice_event(course_dir: Path, user_id: str, entry: dict[str, Any]) -> None:
    """One JSON line per retrieval event, appended to this learner's practice log — the
    platform's single highest-leverage data structure (scheduling, ZPD, calibration, and
    mastery all read from it later). Append-only; nothing ever rewrites this file. Every
    surface that produces a retrieval event writes through here, so the log has one
    schema and one writer."""
    with (learner_dir(course_dir, user_id, create=True) / PRACTICE_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_practice_event(course_dir: Path, user_id: str, req: AttemptRequest, verdict: str) -> None:
    """Log one graded quiz attempt as a practice event."""
    _append_practice_event(
        course_dir,
        user_id,
        {
            "ts": datetime.now(UTC).isoformat(),
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
    """One structured grading call against SETTINGS["grading_model"]. Shared by every grader
    the platform runs so they fail identically — and, through model_call, so they fail the
    same way the chat turn does."""
    with model_call("grading model call") as client:
        graded = client.messages.parse(
            model=SETTINGS["grading_model"],
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
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


def _read_practice_events(course_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Parse one learner's append-only practice log, skipping malformed lines defensively:
    a bad line (interrupted write, hand-edit, schema drift) costs that line only, never
    the whole aggregate."""
    path = learner_dir(course_dir, user_id) / PRACTICE_LOG_NAME
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
        parsed = parsed.replace(tzinfo=UTC)
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


def _aggregate_practice(course_dir: Path, user_id: str) -> dict[str, Any]:
    """One learner's practice log rolled up three ways: per-item attempt histories
    (lesson-then-item order), one summary, and the confidence-by-verdict calibration
    matrix. A high-confidence miss is an *incorrect* verdict at confidence >= 3 — the
    hypercorrection signal (charter P13), deliberately not counting partial credit."""
    events = _read_practice_events(course_dir, user_id)
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
def get_practice(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Aggregated practice state for a course, straight from its .practice-log.jsonl:
    per-item attempt histories, a summary, the confidence-vs-verdict calibration
    matrix, due_today ({count, item_ids} — the daily-review selection, computed from the
    same events), and weekly ({due, last_session_ts, eligible_count} — the weekly loop's
    cadence and delayed-check selection, so the sidebar renders both review lines from one
    fetch). An empty or absent log returns {items: [], summary: null, calibration: null,
    due_today: {count: 0, item_ids: []}} plus the weekly block."""
    course_dir, _ = open_course(course, user_id)
    data = _aggregate_practice(course_dir, user_id)
    data["weekly"] = _weekly_state_payload(course_dir, user_id)
    return data


def practice_state_block(course_dir: Path, user_id: str) -> str:
    """The compact practice-state text injected into the teaching agent's context each
    turn: one deterministic line per item, so ZPD estimation and learning records rest on
    citable retrieval evidence instead of conversation impressions."""
    header = (
        "Current practice-log state for this course — this is the citable evidence base "
        "for ZPD estimation and learning records (see TEACHING-POLICY.md: records require "
        "citable evidence):"
    )
    data = _aggregate_practice(course_dir, user_id)
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
        + _weekly_state_line(course_dir, user_id)
        + "\n"
        + "\n".join(lines)
        + truncated_note
    )


@app.post("/api/attempt")
def attempt(req: AttemptRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Grade one committed retrieval attempt against the item's rubric and log it as a
    practice event. Give-ups skip the model call but are still answered (the canonical
    answer always shows after an attempt) and still logged.

    An attempt whose source is "weekly" is the first of the two engagement signals that
    make a weekly session count as held — the learner did the delayed check, which is the
    session's substance."""
    course_dir, _ = open_course(req.course, user_id)

    if req.gave_up:
        feedback = {
            "criterion": _first_sentence(req.rubric)
            or "Mastery here means being able to state this concept accurately, from memory, in your own words.",
            "task": "No attempt was made this time.",
            "process": "Reread the relevant section, then return to this item in review.",
            "self_regulation": "What made this one hard to start — the concept, or the cue?",
        }
        _log_practice_event(course_dir, user_id, req, "not_attempted")
        _record_weekly_engagement(course_dir, user_id, req.source)
        return {"verdict": "not_attempted", "answer": req.answer, "feedback": feedback}

    graded = _grade_attempt(req)
    _log_practice_event(course_dir, user_id, req, graded.verdict)
    _record_weekly_engagement(course_dir, user_id, req.source)
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
def review_page(course: str, as_of: str | None = None, *, user_id: str = Depends(current_user_id)) -> Response:
    """The daily review session ("learned today, verified tomorrow") as a standalone
    generated page for the preview iframe: the due items' authored quiz blocks carried
    over verbatim from their source lessons, run through the same attempt-gated quiz.js
    machinery lessons use — attempts land in /api/attempt and the practice log exactly
    as lesson attempts do. ?as_of=YYYY-MM-DD overrides "today" for dev/testing only;
    the UI never sends it."""
    course_dir, _ = open_course(course, user_id)
    if as_of is not None:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid as_of date: {as_of!r}"
            ) from exc
    else:
        as_of_date = None

    events = _read_practice_events(course_dir, user_id)
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
    return Response(
        content=page,
        media_type="text/html",
        headers={"Content-Security-Policy": CSP_COURSE_AUTHORED},
    )


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


def _read_weekly_sessions(course_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """One learner's weekly-session cadence log, malformed lines skipped defensively (a bad
    line costs that line only, never the cadence)."""
    path = learner_dir(course_dir, user_id) / WEEKLY_LOG_NAME
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
    user_id: str,
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
    for entry in _read_weekly_sessions(course_dir, user_id):
        if _event_local_date(entry["ts"]) == today:
            return False
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "items_presented": items_presented,
        "as_of": as_of.isoformat(),
        "trigger": trigger,
    }
    with (learner_dir(course_dir, user_id, create=True) / WEEKLY_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def _record_weekly_engagement(course_dir: Path, user_id: str, source: str) -> None:
    """/api/attempt's hook into the weekly cadence: an attempt submitted from the weekly
    page is engagement with that session, so it closes the week. Attempts from anywhere
    else say nothing about the weekly loop and fall straight through."""
    if source != "weekly":
        return
    _log_weekly_session(
        course_dir,
        user_id,
        trigger="attempt",
        items_presented=None,
        as_of=datetime.now().astimezone().date(),
    )


def _weekly_status(course_dir: Path, user_id: str, as_of: date | None = None) -> dict[str, Any]:
    """Weekly-loop state for one learner on one course: whether a session is due by the
    cadence rule, when the last one happened, and the items a session held now would present.
    eligible_count is the capped, presentable selection — the count the page actually shows,
    never a backlog."""
    today = as_of or datetime.now().astimezone().date()
    sessions = _read_weekly_sessions(course_dir, user_id)
    last_session_ts = sessions[-1]["ts"] if sessions else None
    last_date = _event_local_date(last_session_ts) if last_session_ts else None
    due = last_date is None or (today - last_date).days >= WEEKLY_CADENCE_DAYS
    items = _compute_weekly(
        _read_practice_events(course_dir, user_id),
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


def _weekly_state_payload(course_dir: Path, user_id: str) -> dict[str, Any]:
    """The weekly block as the frontend consumes it — the cadence facts without the
    selected items themselves. One shape, two endpoints: /api/practice embeds it so the
    sidebar renders both review lines from one fetch, and /api/weekly-session returns it
    so a just-recorded session updates without a second round trip."""
    status = _weekly_status(course_dir, user_id)
    return {key: status[key] for key in ("due", "last_session_ts", "eligible_count")}


def _weekly_state_line(course_dir: Path, user_id: str) -> str:
    """The weekly-loop line of the teaching agent's practice-state block: the cadence fact
    plus, when a session is due, what the agent is expected to do with it (charter P21/P22 —
    the learner does the evaluating and the reporting; the agent proposes, then records)."""
    status = _weekly_status(course_dir, user_id)
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


def _mission_success_section(course_dir: Path, user_id: str) -> str | None:
    """The markdown block under this learner's MISSION.md "Success looks like" heading,
    rendered to HTML — or None when the file or the heading is absent, or the block carries
    no list. Lines run to the next heading of any level, so wrapped and nested bullets
    survive."""
    path = learner_dir(course_dir, user_id) / "MISSION.md"
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
# real today: a ?as_of= preview must never be markable. Its own file rather than quiz.js
# because it belongs to this page alone, and it reads the course slug from the document's
# own URL for the same reason quiz.js does — the page is standalone and same-origin.
WEEKLY_MARK_CONTROL = """<div class="weekly-mark" id="weekly-mark">
<button type="button" class="btn btn-secondary" id="weekly-mark-button">Mark this review as held</button>
<p class="weekly-mark-note">Use this once you have taken the mission check and anything from section or sangha to your teacher in the chat.</p>
</div>
<script src="/static/weekly.js" defer></script>"""


@app.get("/weekly/{course}")
def weekly_page(course: str, as_of: str | None = None, *, user_id: str = Depends(current_user_id)) -> Response:
    """The weekly review session as a standalone generated page for the preview iframe:
    the platform's delayed unassisted check (charter P19), the predicted-vs-actual
    calibration display (P13), the mission's own success criteria handed back to the
    learner to evaluate (P21), and the prompt that carries section/office-hours/sangha
    signal back into the records (P22). Serving the page records nothing: a session counts
    only on engagement — an attempt submitted from this page, or the explicit "mark held"
    control below. ?as_of=YYYY-MM-DD is a dev/testing preview that overrides "today" and
    additionally hides that control (a preview must never be markable). The UI never
    sends it."""
    course_dir, _ = open_course(course, user_id)
    if as_of is not None:
        try:
            as_of_date = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid as_of date: {as_of!r}"
            ) from exc
    else:
        as_of_date = None

    shown_date = as_of_date or datetime.now().astimezone().date()
    events = _read_practice_events(course_dir, user_id)
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

    practice = _aggregate_practice(course_dir, user_id)
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

    mission = _mission_success_section(course_dir, user_id)
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
    return Response(
        content=page,
        media_type="text/html",
        headers={"Content-Security-Policy": CSP_COURSE_AUTHORED},
    )


class WeeklySessionRequest(BaseModel):
    course: str


@app.post("/api/weekly-session")
def record_weekly_session(req: WeeklySessionRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """The explicit "mark held" path — the weekly page's one control. It exists because a
    week whose delayed check is empty (nothing aged enough yet) still has real work in it:
    the mission check and the world capture both happen in chat, and the learner needs a
    way to close the week after doing them. Idempotent for the local day, so a second
    click, or a click after an attempt already closed the week, is a no-op that still
    answers with the current state."""
    course_dir, _ = open_course(req.course, user_id)
    # eligible_count recomputed here is the count the page presented: the selection is a
    # pure function of the practice log, and on the path that actually writes, nothing has
    # been logged between the render and the click (an attempt in between would have
    # closed the week itself, making this call the no-op).
    _log_weekly_session(
        course_dir,
        user_id,
        trigger="manual",
        items_presented=_weekly_status(course_dir, user_id)["eligible_count"],
        as_of=datetime.now().astimezone().date(),
    )
    return _weekly_state_payload(course_dir, user_id)


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


def _glossary_terms(course_dir: Path, user_id: str) -> list[str]:
    """The terms this learner's GLOSSARY.md currently defines, in file order. An absent or
    unreadable glossary has no terms rather than failing the request."""
    path = learner_dir(course_dir, user_id) / GLOSSARY_NAME
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
def get_compose_targets(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """What the Compose surface can be pointed at: every lesson ({path, number, title}),
    every concept the course's authored quiz items claim (deduplicated, in lesson order),
    and the terms GLOSSARY.md already defines."""
    course_dir, _ = open_course(course, user_id)
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
        "glossary_terms": _glossary_terms(course_dir, user_id),
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
def compose_recall(req: ComposeRecallRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Grade one closed-book free recall against the material it targets, and log it as a
    retrieval event with full practice-log parity. The verdict is written to the log in
    the log's own vocabulary (RECALL_VERDICT_TO_PRACTICE) and returned to the UI in the
    recall grader's bands.

    The synthetic item id ("recall:0003") is carried by no lesson, so the daily and weekly
    selections — which filter through the authored quiz index — skip it automatically: a
    free recall is real retrieval evidence but cannot be re-presented as a quiz item."""
    course_dir, _ = open_course(req.course, user_id)
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
        user_id,
        {
            "ts": datetime.now(UTC).isoformat(),
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


def _already_logged_today(course_dir: Path, user_id: str, item_id: str) -> bool:
    today = datetime.now().astimezone().date()
    return any(
        event["item_id"] == item_id and _event_local_date(event["ts"]) == today
        for event in _read_practice_events(course_dir, user_id)
    )


@app.post("/api/compose/define")
def compose_define(req: ComposeDefineRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Critique one glossary definition the learner drafted from memory: the four-part
    feedback, the AI's own definition declared as a comparison target, and the
    discrepancies converted into questions (charter P8 — the learner's compression is the
    evidence, so it stays the learner's).

    The first draft of a term on a given day is a retrieval event and is logged; revisions
    the same day are the same retrieval, re-worked, and are not logged again."""
    course_dir, _ = open_course(req.course, user_id)
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
    if not _already_logged_today(course_dir, user_id, item_id):
        _append_practice_event(
            course_dir,
            user_id,
            {
                "ts": datetime.now(UTC).isoformat(),
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


def _glossary_topic(course_dir: Path, user_id: str) -> str:
    """What a new glossary is a glossary of: this learner's MISSION.md own title where there
    is one (with its "Mission:" prefix dropped), the prettified course slug otherwise."""
    mission = learner_dir(course_dir, user_id) / "MISSION.md"
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
def save_glossary_entry(req: GlossaryEntryRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Write the learner's own definition into GLOSSARY.md, creating the file to
    GLOSSARY-FORMAT.md's skeleton when it does not exist yet and snapshotting the previous
    version into the course's state history when it does (the same guardrail write_file
    applies to the two learner-state files). The definition saved is the one posted — the
    critique endpoint's reference definition is a comparison target and never reaches
    this path."""
    course_dir, _ = open_course(req.course, user_id)
    term = " ".join(req.term.split())
    definition = " ".join(req.definition.split())
    avoid = " ".join(req.avoid.split()) if req.avoid else None
    if not term:
        raise HTTPException(status_code=400, detail="a term is required")
    if not definition:
        raise HTTPException(status_code=400, detail="a definition is required")
    path = learner_dir(course_dir, user_id, create=True) / GLOSSARY_NAME
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"GLOSSARY.md is unreadable: {exc}"
            ) from exc
        updated = _glossary_with_entry(existing, term, definition, avoid)
    else:
        updated = _new_glossary_text(_glossary_topic(course_dir, user_id), term, definition, avoid)
    _snapshot_state_file(course_dir, user_id, path, updated)
    path.write_text(updated, encoding="utf-8")
    return {"term": term, "saved": True}


@app.get("/api/courses")
def get_courses(user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """The courses this caller is enrolled in, each carrying the caller's own role in it.

    The role travels with the listing because the UI has to know which controls to render, and
    a second round trip per course to ask would be the same fact fetched twice. It reveals
    nothing about who else has a record in them — which is the half of this route's promise
    that survives enrollment intact."""
    return {
        "courses": [
            {**course, "role": role}
            for course in list_courses()["courses"]
            if (role := course_role(user_id, course["slug"])) is not None
        ]
    }


def list_courses() -> dict[str, Any]:
    """Every course in the workspace, each named by its manifest title where it has one so
    the UI can list real titles rather than slugs. The slug stays the identity.

    A plain function rather than the route itself, because what it answers depends only on the
    workspace: startup checks and tests call it directly, and threading a session through those
    callers would be ceremony that proves nothing. The route above composes it with the
    caller's enrollments."""
    return {
        "courses": [
            {"slug": slug, "title": course_title(WORKSPACE_ROOT / slug, slug)}
            for slug in workspace_course_slugs()
        ]
    }


@app.post("/api/courses")
def create_course(req: NewCourseRequest, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """A new course starts as a course package with a minimal manifest and an empty
    directory for the creating learner beside it; everything else is created lazily, when
    there is real content to put in it.

    This is the one course route that resolves no role, because no enrollment can exist for a
    course that does not: it mints one instead. Any account may create a course and is its
    author — creating your own package is not authoring somebody else's, and without the
    record the creator could not add a single lesson to what they just made."""
    course_dir = resolve_course_dir(req.slug, must_exist=False)
    with store_transaction():
        if course_dir.exists():
            raise HTTPException(status_code=409, detail=f"course already exists: {req.slug}")
        course_dir.mkdir(parents=True, exist_ok=False)
        # A slug with no directory can still carry records — a course renamed or removed
        # outside the app leaves them behind. Nobody holds a legitimate role in a course that
        # does not exist, and letting a new course inherit that list is the same bug archiving
        # closes from the other end.
        _drop_course_enrollments(req.slug)
        learner_dir(course_dir, user_id, create=True)
        manifest = {
            "schema": COURSE_MANIFEST_SCHEMA,
            "slug": req.slug,
            "title": _prettify_slug(req.slug),
            # The unit tier starts empty and generically named: the course's own word for it
            # ("Part", "Domain", "Week") and its units are filled in once its structure is
            # known.
            "unit_label": DEFAULT_UNIT_LABEL,
            "units": [],
            "created": date.today().isoformat(),
        }
        (course_dir / COURSE_MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        enroll(user_id, req.slug, ROLE_AUTHOR)
    return {"slug": req.slug}


@app.patch("/api/courses/{slug}")
def rename_course(
    slug: str, req: RenameCourseRequest, user_id: str = Depends(current_user_id)
) -> dict[str, Any]:
    """Renaming the directory a shared package lives in is authoring, so it needs that role.

    The enrollments move with it. They are keyed by slug, so a rename that left them behind
    would orphan access to the course — the renamer's own included — the moment it succeeded.
    The directory moves first and the store is written last, so a rename that fails saves
    nothing."""
    course_dir, _ = open_course(slug, user_id, require=ROLE_AUTHOR)
    new_dir = resolve_course_dir(req.new_slug, must_exist=False)
    with store_transaction():
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
        # Anything already keyed to the destination slug is orphaned — its directory is the
        # one just proved absent — and would otherwise survive as a second access list on this
        # course.
        _drop_course_enrollments(req.new_slug)
        _rekey_course_enrollments(slug, req.new_slug)
        save_enrollments()
    return {"slug": req.new_slug}


@app.post("/api/courses/{slug}/archive")
def archive_course(slug: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Withdrawing a shared package from every listing is authoring, so it needs that role.

    The course's enrollments are dropped with it. Left behind, a slug reused after archiving
    would silently inherit the archived course's access list. Nothing under learners/ is
    touched: the records travel with the package into the archive exactly as they are."""
    course_dir, _ = open_course(slug, user_id, require=ROLE_AUTHOR)
    archive_root = WORKSPACE_ROOT / ARCHIVE_DIR_NAME
    archive_root.mkdir(exist_ok=True)
    target = archive_root / slug
    with store_transaction():
        if target.exists():
            raise HTTPException(status_code=409, detail=f"an archived course already has this name: {slug}")
        course_dir.rename(target)
        _drop_course_enrollments(slug)
        save_enrollments()
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


def _grouped_lessons(course_dir: Path, user_id: str) -> dict[str, Any]:
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
    histories = _item_histories(_read_practice_events(course_dir, user_id))

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
def get_lessons(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """A course's lessons grouped by unit: {course, unit_label, units, unassigned}. Each
    unit carries {id, title, order, color, lessons, progress}; each lesson keeps its number,
    path, title, declared unit, and derived resources. `color` is the unit's identifying hue,
    computed from `order` (see UNIT_COLORS) so every surface reads one decision."""
    course_dir, _ = open_course(course, user_id)
    return {"course": course, **_grouped_lessons(course_dir, user_id)}


@app.get("/api/course-overview")
def get_course_overview(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Structured data for the course-overview page: rendered course artifacts plus the
    course files no lesson links (lesson-linked files already appear in the sidebar under
    their lesson, derived from the lesson HTML itself). The file list covers the course
    package — root files and everything under materials/ — and never learners/, whose
    contents reach the page through their own rendered sections, this learner's only."""
    course_dir, _ = open_course(course, user_id)
    learner = learner_dir(course_dir, user_id)
    # The course map: the same units and rollups the sidebar groups by, so both surfaces
    # read one computation rather than two descriptions of it. The grouped lessons also
    # supply the file claims below — every lesson appears in it exactly once.
    grouped = _grouped_lessons(course_dir, user_id)
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
        "learning_records": _list_learning_records(course_dir, user_id),
        "reference": _list_reference_docs(course_dir),
    }


def _build_tree(path: Path, course_dir: Path, learner_real: Path) -> dict[str, Any]:
    """The course's file tree, with learners/ pruned to the one learner it is being built
    for. Every other learner's directory is skipped entirely — not their files, not the
    fact of them (charter P25: one learner's record is never visible from another's
    context), so the tree reads exactly as it did when a course held a single learner.

    Anything resolving outside the course is skipped on the same terms. The file routes refuse
    such a path, so listing one would offer a node that cannot be opened; and where it leads is
    another course's learners, naming them here would disclose who is enrolled there even
    though every one of those paths is refused."""
    rel = path.relative_to(course_dir).as_posix() if path != course_dir else ""
    if path.is_dir():
        # Directly under learners/, the only child that survives is this learner's own.
        siblings_pruned = path == course_dir / LEARNERS_DIR_NAME
        children = sorted(
            (
                _build_tree(child, course_dir, learner_real)
                for child in path.iterdir()
                if not child.name.startswith(".")
                and not (siblings_pruned and child != learner_real)
                and _within_course(course_dir, Path(os.path.realpath(child)))
            ),
            key=lambda n: (n["type"] != "dir", n["name"]),
        )
        return {"name": path.name if rel else "", "path": rel, "type": "dir", "children": children}
    return {"name": path.name, "path": rel, "type": "file"}


@app.get("/api/workspace")
def get_workspace(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    course_dir, _ = open_course(course, user_id)
    tree = _build_tree(course_dir, course_dir, learner_dir(course_dir, user_id))
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
def get_file(course: str, path: str, user_id: str = Depends(current_user_id)) -> Response:
    course_dir, _ = open_course(course, user_id)
    if _is_hidden(path):
        raise HTTPException(status_code=404, detail="not found")
    file_path = resolve_in_course(course_dir, path)
    _assert_own_learner_path(course_dir, user_id, file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {path}")

    data = file_path.read_bytes()
    return Response(
        content=data,
        media_type=_media_type_for(file_path.suffix.lower()),
        headers={"Content-Security-Policy": CSP_COURSE_AUTHORED},
    )


@app.get("/workspace/{course}/{file_path:path}")
def get_workspace_file(course: str, file_path: str, user_id: str = Depends(current_user_id)) -> Response:
    """Serve a course file at a real hierarchical URL (rather than /api/file's query-string
    form), so that a lesson HTML file's relative links — "../assets/lesson.css",
    "../MISSION.md" — resolve correctly when the lesson is loaded into an iframe."""
    course_dir, _ = open_course(course, user_id)
    if _is_hidden(file_path):
        raise HTTPException(status_code=404, detail="not found")
    resolved = resolve_in_course(course_dir, file_path)
    _assert_own_learner_path(course_dir, user_id, resolved)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {file_path}")

    data = resolved.read_bytes()
    return Response(
        content=data,
        media_type=_media_type_for(resolved.suffix.lower()),
        headers={"Content-Security-Policy": CSP_COURSE_AUTHORED},
    )


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

# Sanitation for trafilatura's extracted markup. It already emits clean article HTML, but
# the source is arbitrary third-party markup and this page renders in the app's own
# origin, so the guarantee has to come from a parser rather than from pattern matching:
# regexes cannot model comments, CDATA, mangled nesting or a browser's error recovery, and
# an allow-list applied to a parsed tree is the only shape that closes the class.
#
# All three of tags, attributes and url_schemes must be passed together. Passing tags=
# alone tightens nothing else — attributes= and url_schemes= fall back to their own
# permissive defaults independently.
READER_ALLOWED_TAGS = {
    "a", "abbr", "article", "aside", "b", "blockquote", "br", "caption", "cite", "code",
    "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt", "em", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "ins", "kbd", "li",
    "mark", "ol", "p", "pre", "q", "s", "samp", "section", "small", "span", "strong",
    "sub", "sup", "table",
    # tbody is not optional: html5ever synthesises one around trafilatura's bare <tr>, and
    # without it here every row unwraps straight out of the table it belongs to.
    "tbody",
    "td", "tfoot", "th", "thead", "time", "tr", "u", "ul", "var", "wbr",
}

# No id, no class, no style, no target — none of them are load-bearing for an archived
# article, and each is a lever on the surrounding page. No rel either: link_rel below
# stamps it, and nh3 refuses a configuration that whitelists both.
#
# No cite either, though blockquote, q, del and ins all take one. It is the single
# URL-bearing attribute nh3 does not treat as a URL, so neither url_schemes below nor the
# relative-URL rewrite reaches its value; no browser navigates cite and no reader ever
# sees it, so the map admits nothing the sanitizer cannot filter.
#
# The "*" key is what makes this map the whole allow-list rather than an addition to one:
# nh3 keeps a generic set of attributes on every tag, and a per-tag map does not displace
# it. Without the empty "*" every tag above silently keeps third-party title and lang.
READER_ALLOWED_ATTRIBUTES = {
    "*": set(),
    "a": {"href", "hreflang", "title"},
    "abbr": {"title"},
    "col": {"span"},
    "colgroup": {"span"},
    "del": {"datetime"},
    "ins": {"datetime"},
    "ol": {"start"},
    "td": {"colspan", "headers", "rowspan"},
    "th": {"colspan", "headers", "rowspan", "scope"},
    "time": {"datetime"},
}

# nh3's own default admits 25 schemes, including several that hand a URL to a local
# handler application. An archived article needs three.
READER_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


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
        raise HTTPException(
            status_code=400, detail=f"could not resolve host {host!r}: {exc}"
        ) from exc
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
        raise HTTPException(status_code=502, detail=f"could not fetch resource: {exc}") from exc


def _sanitize_extracted_html(markup: str, base_url: str) -> str:
    """Reduce trafilatura's extracted markup to the article allow-list above.

    The output is a re-serialisation of a parsed tree, not an edit of the input string, so
    invalid nesting is repaired and self-closed tags are normalised on the way through —
    the same transformation the browser was already performing at load. It also unwraps
    trafilatura's <html><body> envelope on its own, since neither tag is on the list.

    base_url is the article's own final URL: a bare "/x" in an archived article resolves
    against the site it came from, never against Keating's origin, where it would be a
    link into the app's API carrying the reading learner's own session."""
    # nh3 does not re-check a rewritten URL against url_schemes, so every relative URL in
    # the article inherits this base's scheme unexamined. _assert_public_http_url already
    # holds every caller to http(s); this keeps the sanitizer's own output guarantee from
    # resting on a guard three functions away.
    if urlsplit(base_url).scheme not in ("http", "https"):
        raise ValueError(f"the reader's base URL must be http(s): {base_url!r}")
    return nh3.clean(
        markup,
        tags=READER_ALLOWED_TAGS,
        attributes=READER_ALLOWED_ATTRIBUTES,
        url_schemes=READER_ALLOWED_URL_SCHEMES,
        # <base target="_blank"> sends every article link to a real tab; noopener denies
        # that tab a window.opener handle back into the reader.
        link_rel="noopener noreferrer",
        url_relative=("rewrite_with_base", base_url),
    )


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
<style nonce="${csp_nonce}">
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


def _reader_page(title: str, host: str, original_url: str, body_html: str, nonce: str) -> str:
    return READER_PAGE_TEMPLATE.substitute(
        title=html_escape(title),
        host=html_escape(host),
        original_url=html_escape(original_url, quote=True),
        body=body_html,
        csp_nonce=nonce,
    )


def _log_reader_fetch(course_dir: Path, user_id: str, url: str, title: str | None) -> None:
    """One JSON line per successful reader fetch — hidden file, same pattern as
    .chat-history.json. Nothing reads it yet; it seeds a future resource-search feature."""
    entry = {"ts": datetime.now(UTC).isoformat(), "url": url, "title": title}
    with (learner_dir(course_dir, user_id, create=True) / RESOURCE_LOG_NAME).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.get("/api/reader")
def read_external(course: str, url: str, user_id: str = Depends(current_user_id)) -> Response:
    """Fetch an external lesson resource server-side and return it as a Keating-styled
    reader page (PDFs pass through raw for the browser's in-pane viewer), so external
    reading happens inside the app instead of a new tab."""
    course_dir, _ = open_course(course, user_id)
    final_url, body, content_type, charset = _fetch_external(url)
    host = urlsplit(final_url).hostname or ""

    if content_type.split(";")[0].strip().lower() == "application/pdf":
        _log_reader_fetch(course_dir, user_id, url, None)
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"Content-Security-Policy": CSP_READER_PDF},
        )

    text = body.decode(charset or "utf-8", errors="replace")

    title: str | None = None
    try:
        metadata = trafilatura.extract_metadata(text)
        title = metadata.title if metadata else None
    except Exception:  # noqa: S110 — swallowed on purpose, and the fallback below is the handler
        pass  # metadata extraction is best-effort; the <title> fallback below covers it
    if not title:
        match = _TITLE_TAG_RE.search(text)
        title = " ".join(html_unescape(match.group(1)).split()) if match else None

    # Images stay out, and the allow-list and the reader's img-src 'none' agree with this
    # rather than merely tolerating it. An <img src> pointing at the article's own host is a
    # beacon that fires every time the learner reopens the archive, which turns a private
    # record of what someone is studying into someone else's server log. What that costs is
    # small and measurable: extraction recovers a handful of figures from a conventional
    # journal article and none at all from the visual explainers where figures carry the
    # argument, because those draw with canvas, SVG and script that no HTML extractor
    # reaches. Captions do not survive extraction either way. An article whose figures are
    # the point is one click from the real thing: every reader page carries "View original".
    extracted = trafilatura.extract(
        text, url=final_url, output_format="html", include_links=True, include_images=False
    )
    if extracted:
        article_html = _sanitize_extracted_html(extracted, final_url)
    else:
        # Paywall / JS-only page: same-styled page, one-line note, prominent escape hatch.
        article_html = (
            '<p class="reader-note">This page couldn’t be read here. '
            f'<a href="{html_escape(url, quote=True)}" rel="noopener">View the original ↗</a></p>'
        )

    _log_reader_fetch(course_dir, user_id, url, title)
    # One nonce per response, carried into both the header and the <style> tag from the
    # same variable: a hash would have to be recomputed by hand on every CSS edit, and
    # the failure mode of getting that wrong is a silently unstyled page.
    nonce = secrets.token_urlsafe(16)
    page = _reader_page(title or host, host, url, article_html, nonce)
    return Response(
        content=page,
        media_type="text/html",
        headers={"Content-Security-Policy": CSP_READER.format(nonce=nonce)},
    )


@app.get("/api/chat-history")
def get_chat_history(course: str, user_id: str = Depends(current_user_id)) -> dict[str, Any]:
    """Reconstruct a display-friendly transcript from the persisted .chat-history.json —
    the frontend reads this instead of keeping its own copy of conversation state, so the
    chat pane always reflects the one source of truth on disk, including across page
    reloads and course switches."""
    course_dir, _ = open_course(course, user_id)
    messages = load_history(course_dir, user_id)

    refused = refused_tool_use_ids(messages)
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
                {
                    "name": b.get("name"),
                    "input": b.get("input"),
                    **({"refused": True} if b.get("id") in refused else {}),
                }
                for b in content
                if b.get("type") == "tool_use"
            ]
            if text or activity:
                turns.append({"role": "assistant", "text": text, "activity": activity})

    return {"course": course, "turns": turns}


@app.post("/api/upload")
async def upload(
    course: str = Form(...),
    file: UploadFile = File(...),
    *,
    user_id: str = Depends(current_user_id),
) -> dict[str, Any]:
    """Adding source material to the shared package is authoring, so it needs that role: what
    lands in materials/ is read by everyone enrolled in the course."""
    course_dir, _ = open_course(course, user_id, require=ROLE_AUTHOR)

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


# index.html lives in the directory the mount below serves, so the shell would otherwise
# answer at two URLs: "/", carrying CSP_APP_SHELL, and "/static/index.html", carrying the
# middleware default that permits it no scripts and no styles. One shell, one URL — this
# route is declared before the mount so it wins the match.
@app.get("/static/index.html")
def static_index() -> RedirectResponse:
    return RedirectResponse("/", status_code=308)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        headers={"Content-Security-Policy": CSP_APP_SHELL},
    )


# --- Operator commands --------------------------------------------------------

# Account management, and only account management. There is deliberately no subcommand that
# reads, exports or summarizes any learner's record: an admin manages ACCOUNTS, not RECORDS
# (charter P25). The absence of a "show me what everyone is doing" command is the product
# decision, not a gap waiting to be filled.
#
# These run in the app's own process image rather than in a separate script, so importing this
# module is what resolves WORKSPACE_ROOT and the instance directory: the CLI and the server
# agree on where state lives by construction, with no second file to drift. In the container:
#     docker exec -it <container> python main.py bootstrap --username <name>


def _read_password(prompt: str) -> str:
    """From a terminal, or from one line of stdin when piped. Never from argv and never from
    the environment: both leak into ps, docker inspect, /proc/<pid>/environ and the shell
    history file, and a password that has been in any of those is not a secret any more."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline().rstrip("\n")


def _courses_holding_a_record(user_id: str) -> list[str]:
    """Course slugs that already carry state for a user id. A count of directories, not a look
    inside any of them.

    The pre-multi-user layout counts as well, for DEFAULT_USER_ID and where startup will
    actually migrate it. A workspace that has not run since learners/ existed still keeps its
    record in <course>/learner/, and the migration moves exactly that to learners/default/ —
    the directory the account being bootstrapped is about to own. Bootstrap runs before the
    server on a from-source installation, so the workspace this reassurance matters most for is
    precisely the one that has not been migrated yet."""
    if not WORKSPACE_ROOT.is_dir():
        return []
    holding = []
    for entry in sorted(WORKSPACE_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in RESERVED_DIRS:
            continue
        learners_root = entry / LEARNERS_DIR_NAME
        learner = learners_root / user_id
        if learner.is_dir() and any(learner.iterdir()):
            holding.append(entry.name)
            continue
        legacy = entry / LEGACY_LEARNER_DIR_NAME
        # Only where learners/ is absent, which is the migration's own precondition: a course
        # holding both is left untouched and warned about, so counting it would over-promise.
        if (
            user_id == DEFAULT_USER_ID
            and not learners_root.exists()
            and legacy.is_dir()
            and any(legacy.iterdir())
        ):
            holding.append(entry.name)
    return holding


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    """The first account, created by whoever holds the workspace.

    It is an operator act rather than a web form on purpose. Bootstrap assigns DEFAULT_USER_ID,
    which on an installation that ran before accounts existed already names a populated
    directory — so whoever completes it inherits that record. A printed setup token and a web
    form would hand it instead to the first HTTP visitor, and would put a bootstrap credential
    on disk (or silently expire it on restart) to do so."""
    # Refused before anything is printed and before a password is asked for: making an
    # operator type a credential and only then telling them the command was never going to
    # work is a small rudeness the check costs nothing to avoid.
    if ACCOUNTS["accounts"]:
        print(
            f"keating: this instance already has {len(ACCOUNTS['accounts'])} account(s) — use "
            "the invite subcommand to add another",
            file=sys.stderr,
        )
        return 1
    holding = _courses_holding_a_record(DEFAULT_USER_ID)
    if holding:
        noun, verb = ("course", "holds") if len(holding) == 1 else ("courses", "hold")
        print(
            f"This account will own {LEARNERS_DIR_NAME}/{DEFAULT_USER_ID}/ — "
            f"{len(holding)} {noun} already {verb} a record there: {', '.join(holding)}"
        )
    password = _read_password("Password: ")
    try:
        account = bootstrap_account(args.username, password)
    except ValueError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1
    print(f"Created {account['username']} (user id {account['user_id']}). You can sign in now.")
    return 0


def _cmd_invite(args: argparse.Namespace) -> int:
    if not ACCOUNTS["accounts"]:
        print("keating: bootstrap an account first", file=sys.stderr)
        return 1
    code = create_invite(created_by="operator", expires_days=args.expires_days)
    print(f"Invite code (valid {args.expires_days} day(s), single use):\n\n    {code}\n")
    print("It is shown once and stored only as a hash. Issue another if it is lost.")
    return 0


def _cmd_accounts(_args: argparse.Namespace) -> int:
    """Usernames and account status. No learner state of any kind appears here."""
    if not ACCOUNTS["accounts"]:
        print("No accounts. Run: python main.py bootstrap --username <name>")
        return 0
    for account in ACCOUNTS["accounts"]:
        flags = []
        if account.get("is_admin"):
            flags.append("admin")
        if account.get("disabled"):
            flags.append("disabled")
        if _account_is_locked(account, datetime.now(UTC)):
            flags.append(f"locked until {account['locked_until']}")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{account['username']}  (user id {account['user_id']}){suffix}")
    return 0


def _cmd_set_disabled(args: argparse.Namespace, disabled: bool) -> int:
    try:
        set_account_disabled(args.username, disabled)
    except ValueError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1
    print(f"{args.username} is now {'disabled' if disabled else 'enabled'}.")
    return 0


def _cmd_set_password(args: argparse.Namespace) -> int:
    """Password reset is out of band, by an operator, by design: no SMTP, no email
    verification, no self-service flow. On a personal instance shared with a few trusted
    people, that is the whole mechanism and it needs no infrastructure."""
    password = _read_password("New password: ")
    try:
        set_account_password(args.username, password)
    except ValueError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1
    print(f"Password set for {args.username}; their existing sessions were ended.")
    return 0


def _cmd_revoke_sessions(args: argparse.Namespace) -> int:
    if args.all:
        print(f"Ended {revoke_all_sessions()} session(s).")
        return 0
    if not args.username:
        print("keating: name an account with --username, or pass --all", file=sys.stderr)
        return 1
    account = find_account(args.username)
    if account is None:
        print(f"keating: no such account: {args.username}", file=sys.stderr)
        return 1
    print(f"Ended {revoke_sessions_for_user(account['user_id'])} session(s).")
    return 0


def _cmd_invites(_args: argparse.Namespace) -> int:
    if not ACCOUNTS["invites"]:
        print("No outstanding invites.")
        return 0
    for index, invite in enumerate(ACCOUNTS["invites"]):
        print(f"{index}  created {invite['created_at']}  expires {invite['expires_at']}")
    return 0


def _cmd_revoke_invite(args: argparse.Namespace) -> int:
    with store_transaction():
        if not 0 <= args.index < len(ACCOUNTS["invites"]):
            print(f"keating: no invite at index {args.index}", file=sys.stderr)
            return 1
        del ACCOUNTS["invites"][args.index]
        save_accounts()
    print("Invite revoked.")
    return 0


def _account_for_username(username: str) -> dict[str, Any] | None:
    account = find_account(username)
    if account is None:
        print(f"keating: no such account: {username}", file=sys.stderr)
    return account


def _known_course(slug: str) -> bool:
    """Courses are not records, so a typo can be named back. An enrollment silently created
    against a slug with no directory is worse than a refusal: it looks like it worked."""
    slugs = workspace_course_slugs()
    if slug in slugs:
        return True
    known = ", ".join(slugs) if slugs else "none"
    print(
        f"keating: no course directory named {slug} in {WORKSPACE_ROOT} — courses there: "
        f"{known}",
        file=sys.stderr,
    )
    return False


def _cmd_enroll(args: argparse.Namespace) -> int:
    """Join an account to a course. The role defaults to learner: least privilege, and
    granting authorship over a shared package should be something an operator types."""
    account = _account_for_username(args.username)
    if account is None or not _known_course(args.course):
        return 1
    try:
        enroll(account["user_id"], args.course, args.role)
    except ValueError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1
    print(f"{args.username} is enrolled in {args.course} as {args.role}.")
    return 0


def _cmd_set_role(args: argparse.Namespace) -> int:
    account = _account_for_username(args.username)
    if account is None:
        return 1
    try:
        set_course_role(account["user_id"], args.course, args.role)
    except ValueError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1
    print(f"{args.username} is now {args.role} in {args.course}.")
    return 0


def _cmd_unenroll(args: argparse.Namespace) -> int:
    """Removes access and nothing on the course filesystem.

    Removing a course's last author, or its last enrollment altogether, is allowed and warned
    about rather than refused: an operator who cannot undo a mistake they are in the middle of
    making is worse off than one who is told what they just did, and every remedy is one
    `enroll` away. report_enrollment_state repeats the same warning at every start, so the
    state cannot be forgotten by closing the terminal."""
    account = _account_for_username(args.username)
    if account is None:
        return 1
    if not unenroll(account["user_id"], args.course):
        print(f"keating: {args.username} is not enrolled in {args.course}", file=sys.stderr)
        return 1
    print(
        f"{args.username} is no longer enrolled in {args.course}. Nothing under "
        f"{args.course}/{LEARNERS_DIR_NAME}/ was touched — removing access is not deleting a "
        "record."
    )
    remaining = [e for e in list_enrollments() if e["course"] == args.course]
    if remaining and not any(e["role"] == ROLE_AUTHOR for e in remaining):
        print(
            f"keating: nobody can author {args.course} now — enroll an author with: "
            f"python main.py enroll --username <name> --course {args.course} --role author"
        )
    elif not remaining:
        print(
            f"keating: nobody can open {args.course} now — enroll someone with: "
            f"python main.py enroll --username <name> --course {args.course} --role author"
        )
    return 0


def _cmd_enrollments(args: argparse.Namespace) -> int:
    """Who is in which course, with what role, since when. No learner state of any kind
    appears here — and nothing whose answer changes when somebody studies, which is the line
    between an administrative fact about access and a record (charter P25)."""
    # Read the enrollments first: doing so refreshes the stores, and building the username map
    # before that would name accounts from a copy the refresh is about to replace.
    enrollments = list_enrollments()
    by_user_id = {a["user_id"]: a["username"] for a in ACCOUNTS["accounts"]}
    rows = [
        e
        for e in enrollments
        if (args.course is None or e["course"] == args.course)
        and (args.username is None or by_user_id.get(e["user_id"]) == args.username)
    ]
    if not rows:
        print("No enrollments. Run: python main.py enroll --username <name> --course <slug>")
        return 0
    for row in sorted(rows, key=lambda e: (e["course"], e["user_id"])):
        username = by_user_id.get(row["user_id"], "(no account)")
        since = str(row.get("enrolled_at", ""))[:10]
        print(
            f"{row['course']}  {username}  (user id {row['user_id']})  {row['role']}  "
            f"since {since}"
        )
    return 0


def _refuse_password_flag(_value: str) -> str:
    raise argparse.ArgumentTypeError(
        "a password on the command line leaks into ps, docker inspect and the shell history "
        "file — this command reads it from the terminal or from stdin instead"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Manage this Keating instance's accounts and course enrollments. Nothing "
        "here reads learner state.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def with_password_refusal(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        # Declared so it is refused by name rather than accepted by a future edit that adds it
        # back as a convenience.
        sub.add_argument("--password", type=_refuse_password_flag, help=argparse.SUPPRESS)
        return sub

    bootstrap = subcommands.add_parser("bootstrap", help="create the first account")
    bootstrap.add_argument("--username", required=True)
    with_password_refusal(bootstrap).set_defaults(handler=_cmd_bootstrap)

    invite = subcommands.add_parser("invite", help="issue a single-use registration code")
    invite.add_argument("--expires-days", type=int, default=INVITE_TTL_DAYS)
    invite.set_defaults(handler=_cmd_invite)

    subcommands.add_parser("accounts", help="list accounts and their status").set_defaults(
        handler=_cmd_accounts
    )

    disable = subcommands.add_parser("disable", help="disable an account and end its sessions")
    disable.add_argument("username")
    disable.set_defaults(handler=lambda args: _cmd_set_disabled(args, True))

    enable = subcommands.add_parser("enable", help="enable an account and clear any lockout")
    enable.add_argument("username")
    enable.set_defaults(handler=lambda args: _cmd_set_disabled(args, False))

    set_password = subcommands.add_parser("set-password", help="set an account's password")
    set_password.add_argument("username")
    with_password_refusal(set_password).set_defaults(handler=_cmd_set_password)

    revoke = subcommands.add_parser("revoke-sessions", help="end live sessions")
    revoke.add_argument("--username")
    revoke.add_argument("--all", action="store_true")
    revoke.set_defaults(handler=_cmd_revoke_sessions)

    subcommands.add_parser("invites", help="list outstanding invites").set_defaults(
        handler=_cmd_invites
    )

    revoke_invite = subcommands.add_parser("revoke-invite", help="revoke an outstanding invite")
    revoke_invite.add_argument("index", type=int)
    revoke_invite.set_defaults(handler=_cmd_revoke_invite)

    enroll_cmd = subcommands.add_parser("enroll", help="join an account to a course")
    enroll_cmd.add_argument("--username", required=True)
    enroll_cmd.add_argument("--course", required=True)
    enroll_cmd.add_argument("--role", choices=COURSE_ROLES, default=ROLE_LEARNER)
    enroll_cmd.set_defaults(handler=_cmd_enroll)

    set_role = subcommands.add_parser("set-role", help="change an account's role in a course")
    set_role.add_argument("--username", required=True)
    set_role.add_argument("--course", required=True)
    set_role.add_argument("--role", choices=COURSE_ROLES, required=True)
    set_role.set_defaults(handler=_cmd_set_role)

    unenroll_cmd = subcommands.add_parser("unenroll", help="remove an account from a course")
    unenroll_cmd.add_argument("--username", required=True)
    unenroll_cmd.add_argument("--course", required=True)
    unenroll_cmd.set_defaults(handler=_cmd_unenroll)

    enrollments = subcommands.add_parser("enrollments", help="list who is in which course")
    enrollments.add_argument("--course")
    enrollments.add_argument("--username")
    enrollments.set_defaults(handler=_cmd_enrollments)

    return parser


def _cli(argv: list[str] | None = None) -> int:
    """Every subcommand reads or writes the instance state, and an operator running one is
    exactly the person who can fix a volume it cannot use — so that failure is an error
    message and an exit code here, not a traceback through the app's internals."""
    args = _build_parser().parse_args(argv)
    try:
        reload_auth_stores()
        return int(args.handler(args))
    except InstanceStateError as exc:
        print(f"keating: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())

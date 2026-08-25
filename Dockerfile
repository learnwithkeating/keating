# Keating ships as a two-stage build: uv resolves and installs into a virtualenv in the
# builder, and the runtime stage carries only that venv plus the application. Nothing from
# uv's cache, no compiler toolchain, and no lockfile resolution happen at runtime.

# The builder's interpreter and the runtime's MUST be the same minor version: the venv is
# copied wholesale, and its packages live in lib/pythonX.Y/site-packages. If the two drift the
# image still builds and then dies at startup with ModuleNotFoundError. One ARG feeds both
# FROM lines so they cannot be bumped independently -- do not replace either with a literal.
ARG PYTHON_VERSION=3.12

# ---- builder -----------------------------------------------------------------------------
# For stricter reproducibility, pin this and the runtime image by digest.
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile alone, so this layer is cached until the lockfile
# changes: editing application code never triggers a reinstall. --locked fails loudly rather
# than silently re-resolving, and --no-dev keeps pytest out of the image.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# ---- runtime -----------------------------------------------------------------------------
ARG PYTHON_VERSION
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    KEATING_WORKSPACE_ROOT=/workspace

# Unprivileged by default. Everything the app writes -- courses, learner state, and its own
# instance state under /workspace/.keating (settings, accounts, sessions, the session signing
# key) -- lands on the mounted volume, so it needs no ownership of its own code and never
# writes into the image layer. The account store in particular must be writable by THIS user
# on the host directory that gets mounted: where it is not, the container starts and looks
# healthy and nobody can sign in, so startup prints the path it could not write.
RUN groupadd --system --gid 1000 keating \
    && useradd --system --uid 1000 --gid keating --home /app --shell /usr/sbin/nologin keating

WORKDIR /app

COPY --from=builder --chown=keating:keating /app/.venv /app/.venv

# Only what the server actually reads at runtime: the application, the pedagogy package it
# loads into every system prompt, the frontend, and the example course users copy out.
COPY --chown=keating:keating main.py ./
COPY --chown=keating:keating skill/ ./skill/
COPY --chown=keating:keating static/ ./static/
COPY --chown=keating:keating examples/ ./examples/

# Courses, learner state and this installation's own state -- settings, accounts, sessions --
# live on a mounted volume, never in the image layer. That is also what makes the container
# disposable without signing everyone out: the session signing key is on the volume, so a
# replaced container keeps the sessions the old one issued.
RUN mkdir -p /workspace && chown keating:keating /workspace
VOLUME ["/workspace"]

USER keating
EXPOSE 8000

# GET / is the app shell, and it is one of the few routes that need no session -- which is
# what this check depends on. Gating / would report a perfectly healthy instance as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"]

# 0.0.0.0 binds inside the container only; the container boundary is the isolation, and the
# host publish address is what decides who can reach it. Publish to 127.0.0.1 (see README):
# the session cookie is Secure, which browsers honour on loopback but not on a LAN address
# over plain HTTP, so an exposed instance is one nobody can sign in to.
#
# One worker is what this image runs and what the suite exercises. The account and session
# stores are files on the volume, and every process touching them takes the same lock and
# re-reads before it writes -- which is what lets `docker exec ... python main.py disable
# <name>` reach a server that is already serving. --workers N is untested here, and the usual
# reason to reach for it, request throughput, is not a problem a personal instance has.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

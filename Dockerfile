# Keating ships as a two-stage build: uv resolves and installs into a virtualenv in the
# builder, and the runtime stage carries only that venv plus the application. Nothing from
# uv's cache, no compiler toolchain, and no lockfile resolution happen at runtime.

# ---- builder -----------------------------------------------------------------------------
# Pinned to a python-specific uv tag so the venv it builds matches the runtime interpreter.
# For stricter reproducibility, pin this and the runtime image by digest.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

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
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    KEATING_WORKSPACE_ROOT=/workspace

# Unprivileged by default. The app writes only inside the workspace volume, so it needs no
# ownership of its own code.
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

# Courses and learner state live on a mounted volume, never in the image layer.
RUN mkdir -p /workspace && chown keating:keating /workspace
VOLUME ["/workspace"]

USER keating
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"]

# 0.0.0.0 binds inside the container only; the container boundary is the isolation, and the
# host publish address is what decides who can reach it. Publish to 127.0.0.1 (see README):
# this app has no authentication.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

#!/usr/bin/env bash
# ABOUTME: Proves that a container pointed at a volume its user cannot use says so — at startup,
# ABOUTME: from the bootstrap subcommand, and on a login — instead of answering with a traceback.
#
# The supported deployment runs the container as the volume's owner (README: --user
# "$(id -u):$(id -g)"). This checks the deployment that is not supported, because that is the one
# an operator reaches by accident: a volume created by one uid, a container running as another.
# Nothing here can be fixed by the app — only by the operator — so the whole subject is whether
# the app says which path is at fault and what to change.
#
# Two layouts, because the mismatch has two shapes and only one of them is the first thing an
# operator meets. A volume with no .keating in it refuses the mkdir that would create the
# directory; a volume that already has one — 0700, owned by whoever ran the container correctly
# the first time — refuses the reads inside it instead, earlier, on the paths that only read.
# Checking one of those certifies a guarantee wider than what was tested.
#
# The ownership mismatch is made explicitly, inside Linux containers, rather than borrowed from
# the host: Docker Desktop on macOS virtualises bind-mount ownership, so a host directory alone
# reproduces nothing. A named volume chowned to a uid the image does not have is the same
# refusal on every platform.

set -euo pipefail

IMAGE=keating:ci
PORT=8000

usage() {
    cat <<'EOF'
Usage: scripts/check-unwritable-volume.sh [options]

Options:
  --image TAG   image to run (default: keating:ci). Build it first:
                docker build -t keating:ci .
  --port N      host port to publish on, loopback only (default: 8000)
  -h, --help    this help

Exits non-zero, naming the layout and the step, if any of the three surfaces answers with a
traceback or with nothing an operator can act on.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMAGE="${2:?--image needs a tag}"; shift 2 ;;
        --port) PORT="${2:?--port needs a number}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER=keating-unwritable-check
VOLUME=keating-unwritable-check-vol
BASE_URL="http://127.0.0.1:${PORT}"
LAYOUT=

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "no such image: $IMAGE — build it first: docker build -t $IMAGE ." >&2
    exit 1
fi

cleanup() {
    # Carry the status that triggered the trap out of it: the tidying up succeeds even when the
    # check failed, and its success must not become the script's answer.
    local status=$?
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT

fail() {
    echo "FAIL [${LAYOUT}]: $*" >&2
    docker logs "$CONTAINER" >&2 2>/dev/null || true
    exit 1
}

# The uid the image runs as, asked of the image rather than assumed, and a uid that is
# deliberately not it.
IMAGE_UID="$(docker run --rm "$IMAGE" id -u | tr -d '\r')"
OTHER_UID=$((IMAGE_UID + 1))

echo "== keating unwritable-volume check: image=${IMAGE} port=${PORT}"
echo "   image runs as uid ${IMAGE_UID}; the volume will belong to uid ${OTHER_UID}"

seed_volume() {
    # A real course on the volume, so what the app cannot do is limited to its own state: the
    # workspace itself is readable and holds something to serve.
    local seed="cp -r /src/why-you-forget /vol/"
    if [ "$1" = existing ]; then
        # What a correctly-run container leaves behind: the instance directory, at the mode the
        # app creates it with, holding the files it keeps there.
        seed="$seed && mkdir -p /vol/.keating && printf '{}' >/vol/.keating/settings.json"
    fi
    seed="$seed && chown -R ${OTHER_UID}:${OTHER_UID} /vol && chmod 0755 /vol"
    if [ "$1" = existing ]; then
        seed="$seed && chmod 0700 /vol/.keating && chmod 0600 /vol/.keating/settings.json"
    fi
    docker volume create "$VOLUME" >/dev/null
    docker run --rm --user 0:0 \
        -v "$VOLUME":/vol \
        -v "$REPO_ROOT/examples":/src:ro \
        "$IMAGE" sh -c "$seed" >/dev/null
}

check_layout() {
    LAYOUT="$1"
    echo
    echo "== layout: ${LAYOUT} instance directory"
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
    seed_volume "$LAYOUT"

    docker run -d --name "$CONTAINER" \
        -p "127.0.0.1:${PORT}:8000" \
        -v "$VOLUME":/workspace \
        "$IMAGE" >/dev/null

    for i in $(seq 1 60); do
        # -s without -S: a refused connection while the app is still booting is the normal case.
        if curl -fs -o /dev/null "$BASE_URL/"; then
            echo "OK: serving after ${i}s"
            break
        fi
        # A container that exited is a crashloop, not a slow boot, and waiting out the rest of
        # the budget only delays saying so.
        if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" = exited ]; then
            fail "the container exited instead of serving — a misconfigured volume must not stop it starting"
        fi
        if [ "$i" = 60 ]; then fail "container did not serve within 60s"; fi
        sleep 1
    done

    echo "== the bootstrap subcommand refuses, without a traceback"
    boot_err="$(mktemp)"
    if docker exec -i "$CONTAINER" python main.py bootstrap --username ci \
            <<<"unwritable-volume-check-password" 2>"$boot_err"; then
        rm -f "$boot_err"
        fail "bootstrap reported success against a volume it cannot write"
    fi
    boot_message="$(cat "$boot_err")"
    rm -f "$boot_err"
    if grep -q "Traceback" <<<"$boot_message"; then
        echo "$boot_message" >&2
        fail "bootstrap answered with a traceback"
    fi
    for expected in "keating:" "/workspace/.keating" "--user"; do
        if ! grep -qF -- "$expected" <<<"$boot_message"; then
            echo "$boot_message" >&2
            fail "the bootstrap message does not mention ${expected}"
        fi
    done
    echo "OK: bootstrap said what is wrong and what to change"

    echo "== a login is answered, not 500ed"
    body_file="$(mktemp)"
    code="$(curl -sS -o "$body_file" -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' \
        -d '{"username":"ci","password":"unwritable-volume-check-password"}' \
        "$BASE_URL/api/login")"
    login_body="$(cat "$body_file")"
    rm -f "$body_file"
    if [ "$code" != 503 ]; then
        echo "$login_body" >&2
        fail "POST /api/login returned HTTP ${code}, not 503 — a 500 here is the unhandled write"
    fi
    if ! grep -qF "/workspace/.keating" <<<"$login_body"; then
        echo "$login_body" >&2
        fail "the login answer does not name the directory that cannot be written"
    fi
    echo "OK: login answered 503 naming the path"

    echo "== startup says the instance state cannot be used"
    # Taken once into a variable, and matched from there. `grep -q` stops reading at the first
    # match, which under `set -o pipefail` kills the producer with SIGPIPE and makes a pipeline
    # that DID match report failure — silently, and only once the log is long enough to still
    # be being written when the match lands.
    log="$(docker logs "$CONTAINER" 2>&1)"
    if ! grep -qE "cannot (read|write) /workspace/\.keating" <<<"$log"; then
        fail "startup did not report the unusable instance directory"
    fi
    if ! grep -q -- "--user" <<<"$log"; then
        fail "the startup report does not say what to change"
    fi
    echo "OK: startup named the path and what to change"

    echo "== nothing was logged as an unhandled exception"
    if grep -q "Traceback" <<<"$log"; then
        fail "the container logged a traceback"
    fi
    echo "OK: no traceback in the container log"
}

check_layout absent
check_layout existing

echo
echo "== PASS (unwritable volume, both layouts)"

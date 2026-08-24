#!/usr/bin/env bash
# ABOUTME: Proves a settings save works in a real container and survives that container being
# ABOUTME: replaced: PUT a change, destroy the container, start a new one on the same volume, GET.
#
# The Settings page writes settings.json. If the app writes it beside its own code, the write
# either fails outright (the image's code directory belongs to root) or lands in the container's
# throwaway layer and disappears with it. Only a write onto the mounted workspace survives, and
# only a replaced container proves that it did.
#
# Both run modes matter, because they run as different users against the same mount: the image's
# own unprivileged user, and the host user the README's documented command passes with --user.

set -euo pipefail

IMAGE=keating:ci
PORT=8000
RUN_AS=host

usage() {
    cat <<'EOF'
Usage: scripts/check-container-settings.sh [options]

Options:
  --image TAG        image to run (default: keating:ci). Build it first:
                     docker build -t keating:ci .
  --port N           host port to publish on, loopback only (default: 8000)
  --run-as host      run with --user "$(id -u):$(id -g)", as the README documents (default)
  --run-as image     run as the image's own unprivileged user
  -h, --help         this help

Exits non-zero, naming the step, if the settings change is rejected or does not survive.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --image) IMAGE="${2:?--image needs a tag}"; shift 2 ;;
        --port) PORT="${2:?--port needs a number}"; shift 2 ;;
        --run-as) RUN_AS="${2:?--run-as needs host or image}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$RUN_AS" in
    host|image) ;;
    *) echo "--run-as must be host or image, not '$RUN_AS'" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="keating-settings-check-${RUN_AS}"
BASE_URL="http://127.0.0.1:${PORT}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "no such image: $IMAGE — build it first: docker build -t $IMAGE ." >&2
    exit 1
fi

WORKSPACE="$(mktemp -d)"
cleanup() {
    # Carry the status that triggered the trap out of it: the tidying up succeeds even when the
    # check failed, and its success must not become the script's answer.
    local status=$?
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    rm -rf "$WORKSPACE"
    exit "$status"
}
trap cleanup EXIT

cp -R "$REPO_ROOT/examples/why-you-forget" "$WORKSPACE/"
# A bind mount carries the host's ownership into the container, and the two run modes enter it
# as different users. Making the throwaway workspace writable by both is a property of the mount,
# not of the app: what is under test is where the app writes, not who owns the volume.
chmod 0777 "$WORKSPACE"

start_container() {
    local user_args=()
    if [ "$RUN_AS" = host ]; then
        user_args=(--user "$(id -u):$(id -g)")
    fi
    # An empty array expands to an unbound-variable error under set -u in bash 3.2, which is
    # what macOS ships, so expand it only when it has elements.
    docker run -d --name "$CONTAINER" \
        -p "127.0.0.1:${PORT}:8000" \
        -v "$WORKSPACE":/workspace \
        ${user_args[@]+"${user_args[@]}"} \
        "$IMAGE" >/dev/null
}

wait_for_it() {
    local i
    for i in $(seq 1 60); do
        # -s without -S: a refused connection while the app is still booting is the normal
        # case here, not something to report.
        if curl -fs -o /dev/null "$BASE_URL/"; then
            echo "serving after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo "FAIL: container did not serve within 60s" >&2
    docker logs "$CONTAINER" >&2
    return 1
}

get_settings() {
    curl -fsS "$BASE_URL/api/settings"
}

# The schema /api/settings validates against. A payload that does not match is rejected as 422
# before any file is touched, which would prove nothing about writing.
PAYLOAD='{"chat_model":"claude-haiku-4-5","grading_model":"claude-sonnet-5","layout":{"remember_sizes":true,"sidebar_w":300,"chat_w":500}}'

assert_saved() {
    local step="$1" body="$2"
    for expected in '"chat_model": *"claude-haiku-4-5"' '"grading_model": *"claude-sonnet-5"' '"sidebar_w": *300' '"chat_w": *500'; do
        if ! printf '%s' "$body" | grep -Eq "$expected"; then
            echo "FAIL: ${step}: no ${expected} in the settings the app served:" >&2
            printf '%s\n' "$body" >&2
            # The container is removed on the way out, so what it said has to be captured
            # here or it is gone: a response body alone does not say why the app answered it.
            docker logs "$CONTAINER" >&2
            return 1
        fi
    done
    echo "OK: ${step}"
}

echo "== keating settings check: image=${IMAGE} port=${PORT} run-as=${RUN_AS}"

start_container
wait_for_it
echo "before: $(get_settings)"

echo "== PUT /api/settings"
body_file="$(mktemp)"
code="$(curl -sS -o "$body_file" -w '%{http_code}' -X PUT \
    -H 'Content-Type: application/json' -d "$PAYLOAD" "$BASE_URL/api/settings")"
put_body="$(cat "$body_file")"
rm -f "$body_file"
if [ "$code" != 200 ]; then
    echo "FAIL: PUT /api/settings returned HTTP ${code}, not 200:" >&2
    printf '%s\n' "$put_body" >&2
    docker logs "$CONTAINER" >&2
    exit 1
fi
echo "OK: PUT returned 200"
assert_saved "the running app serves the change" "$put_body"

if [ ! -f "$WORKSPACE/.keating/settings.json" ]; then
    echo "FAIL: nothing was written to the volume at .keating/settings.json" >&2
    ls -la "$WORKSPACE" >&2
    docker logs "$CONTAINER" >&2
    exit 1
fi
echo "OK: the volume holds .keating/settings.json"

echo "== replace the container against the same volume"
docker rm -f "$CONTAINER" >/dev/null
start_container
wait_for_it
assert_saved "the change survived the container being replaced" "$(get_settings)"

echo "== PASS (run-as ${RUN_AS})"

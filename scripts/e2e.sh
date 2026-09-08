#!/usr/bin/env bash
#
# Brings the stack up, runs the end to end tests against it, and tears it down.
# This is what CI runs, so a failure here is a failure there.
#
#   ./scripts/e2e.sh           bring up, test, tear down
#   ./scripts/e2e.sh --keep    leave the stack running afterwards

set -euo pipefail

cd "$(dirname "$0")/.."

KEEP=false
[ "${1:-}" = "--keep" ] && KEEP=true

VENV=".venv-e2e"

cleanup() {
  if [ "$KEEP" = false ]; then
    echo "==> Tearing down"
    docker compose down -v >/dev/null 2>&1 || true
  else
    echo "==> Leaving the stack running. Stop it with: docker compose down -v"
  fi
}
trap cleanup EXIT

echo "==> Starting the stack"
docker compose up -d --build

if [ ! -d "$VENV" ]; then
  echo "==> Creating the test environment"
  python3 -m venv "$VENV"
fi

echo "==> Installing the test dependencies"
"$VENV/bin/pip" install -q -e tests/e2e

echo "==> Running the end to end tests"
"$VENV/bin/pytest" tests/e2e -q

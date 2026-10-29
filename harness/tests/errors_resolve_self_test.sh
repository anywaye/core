#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures"

PY="${ANYWAYE_ERRORS_RESOLVE_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
      >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "FAIL errors_resolve_self_test: no python >= 3.9 on PATH, and the module's floor" >&2
  echo "  is 3.9 because it uses urllib and nothing outside the standard library." >&2
  echo "  Set ANYWAYE_ERRORS_RESOLVE_PYTHON. A proof that did not run is not a pass." >&2
  exit 2
fi

failures=0
passed=0

pass() { passed=$((passed + 1)); printf 'PASS errors_resolve_self_test: %s\n' "$1"; }
fail_case() {
  failures=$((failures + 1))
  printf 'FAIL errors_resolve_self_test: %s\n' "$1"
  shift
  printf '%s\n' "$@" | sed 's/^/       /'
}

CHECK="$HARNESS/errors_resolve.py"
FIXTURE='harness/tests/fixtures/conforming-openapi'

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-errors-resolve.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

MIRROR="$WORK/mirror"
mkdir -p "$MIRROR"
PAGES="unauthorized validation_failed idempotency_key_reused"
for page in $PAGES; do
  mkdir -p "$MIRROR/$page"
  printf '<h1>%s</h1>' "$page" > "$MIRROR/$page/index.html"
done

PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"

cd "$MIRROR"
"$PY" -m http.server "$PORT" --bind 127.0.0.1 >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null; rm -rf "$WORK"' EXIT

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.25)
try:
    s.connect(('127.0.0.1', $PORT)); sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

BASE="http://127.0.0.1:$PORT"

run_check() {
  local name="$1"
  local dir="$WORK/$name"
  mkdir -p "$dir"
  cp -R "$HARNESS" "$dir/harness"
  cp -R "$FIXTURES" "$dir/harness/tests/fixtures"
  chmod +x "$dir/harness/bin/errors-resolve" 2>/dev/null || true
  shift
  ( cd "$ROOT" && "$PY" "$dir/harness/errors_resolve.py" \
      --base "$BASE" "$dir/$FIXTURE" "$@" 2>&1 )
}

out="$(run_check control)" || ec=$?
out="$(run_check control)"
ec=$?
if [ "$ec" -ne 0 ]; then
  fail_case "the control: a mirror serving all three pages did not exit 0" "$out"
elif ! printf '%s\n' "$out" | grep -q "at $BASE$"; then
  fail_case "the control: exit 0, but the report does not name the base it used" "$out"
elif ! printf '%s\n' "$out" | grep -q "fetching 3 type URI"; then
  fail_case "the control: exit 0, and it did not read three URIs off the fixture" "$out"
else
  pass "the control: three pages served, three URIs read, exit 0, and the base named"
fi

out="$(run_check page-missing)"
ec=0
kill "$SERVER_PID" 2>/dev/null
sleep 0.3
rm -rf "$MIRROR/validation_failed"
cd "$MIRROR"
"$PY" -m http.server "$PORT" --bind 127.0.0.1 >"$WORK/server2.log" 2>&1 &
SERVER_PID=$!
sleep 1.5
out="$(run_check page-missing)"
ec=$?
if [ "$ec" -ne 1 ]; then
  fail_case "a published type whose page is missing did not exit 1" "exit $ec" "$out"
elif ! printf '%s\n' "$out" | grep -q "validation_failed"; then
  fail_case "a missing page went red without naming WHICH page" "$out"
elif ! printf '%s\n' "$out" | grep -q "404"; then
  fail_case "a missing page went red without the status it answered" "$out"
else
  pass "a missing page went red naming the URI and the status"
fi

kill "$SERVER_PID" 2>/dev/null
sleep 0.3
DEAD_PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); p=s.getsockname()[1]; s.close(); print(p)')"
out="$(run_check base-dead --base "http://127.0.0.1:$DEAD_PORT")"
ec=$?
if [ "$ec" -eq 0 ]; then
  fail_case "a base that is not listening exited 0 — a demanded tier that skips" "$out"
elif [ "$ec" -ne 1 ]; then
  fail_case "a base that is not listening exited $ec, expected 1 (a failure, not a refusal)" "$out"
elif ! printf '%s\n' "$out" | grep -qi "could not"; then
  fail_case "a base that is not listening went red without a sentence about it" "$out"
else
  pass "a base that is not listening FAILED with a sentence, and did not skip"
fi

cd "$MIRROR"
"$PY" -m http.server "$PORT" --bind 127.0.0.1 >"$WORK/server3.log" 2>&1 &
SERVER_PID=$!
sleep 1.5

four="$WORK/no-api"
mkdir -p "$four"
cp -R "$HARNESS" "$four/harness"
cp -R "$FIXTURES" "$four/harness/tests/fixtures"
chmod +x "$four/harness/bin/errors-resolve" 2>/dev/null || true
edit_manifest() {
  "$PY" - "$1" <<'PY'
import sys
path = sys.argv[1]
body = open(path, encoding="utf-8").read()
old = "exposes:\n  api: openapi/v1.yaml\n"
if old not in body:
    sys.exit(f"errors_resolve_self_test: the fixture manifest moved: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, "", 1))
PY
}
edit_manifest "$four/$FIXTURE/anywaye.yml"
out="$( cd "$ROOT" && "$PY" "$four/harness/errors_resolve.py" \
    --base "$BASE" "$four/$FIXTURE" 2>&1 )"
ec=$?
if [ "$ec" -ne 2 ]; then
  fail_case "a manifest declaring no exposes.api did not exit 2" "exit $ec" "$out"
elif ! printf '%s\n' "$out" | grep -qi "no exposes.api"; then
  fail_case "no exposes.api exited 2 without saying why" "$out"
else
  pass "a manifest with no exposes.api refused, exit 2, and said why"
fi

five="$WORK/off-base"
mkdir -p "$five"
cp -R "$HARNESS" "$five/harness"
cp -R "$FIXTURES" "$five/harness/tests/fixtures"
chmod +x "$five/harness/bin/errors-resolve" 2>/dev/null || true
"$PY" - "$five/$FIXTURE/openapi/v1.yaml" <<'PY'
import sys
path = sys.argv[1]
body = open(path, encoding="utf-8").read()
old = "type: https://docs.anywaye.com/errors/unauthorized"
new = "type: https://errors.anywaye.com/unauthorized"
if old not in body:
    sys.exit(f"errors_resolve_self_test: the fixture moved: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
out="$( cd "$ROOT" && "$PY" "$five/harness/errors_resolve.py" \
    --base "$BASE" "$five/$FIXTURE" 2>&1 )"
ec=$?
if [ "$ec" -ne 2 ]; then
  fail_case "a type at the retired host did not exit 2" "exit $ec" "$out"
elif ! printf '%s\n' "$out" | grep -qi "errors.anywaye.com"; then
  fail_case "an off-base type exited 2 without naming the URI it refused" "$out"
else
  pass "a type at the retired host refused, exit 2, naming the URI"
fi

kill "$SERVER_PID" 2>/dev/null

printf '\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: errors_resolve_self_test — %s of %s case(s) failed.\n' "$failures" \
    "$((passed + failures))"
  exit 1
fi
printf 'PASS: errors_resolve_self_test — %s case(s), the control green first and every red naming its reason.\n' "$passed"
exit 0

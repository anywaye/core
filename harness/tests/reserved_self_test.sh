#!/usr/bin/env bash
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness="$(dirname "$here")"
root="$(dirname "$harness")"
check="$harness/bin/reserved-check"
fixtures="$here/fixtures/reserved-properties"

if [ ! -x "$check" ]; then
  echo "reserved_self_test: precondition missing — $check is not executable, so the" >&2
  echo "  checker could not be run. This is not a skip; it is a failure to prove" >&2
  echo "  anything, and it is reported as one." >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "reserved_self_test: precondition missing — no python3 on PATH." >&2
  exit 2
fi

export ANYWAYE_RESERVED_PYTHON="${ANYWAYE_RESERVED_PYTHON:-python3}"

passes=0
breakages=0
controls=0

run() {
  "$check" "$1" 2>&1
}

assert_red() {
  local label="$1" dir="$2" expect="$3" also="${4:-}"
  local out code
  out="$(run "$dir")"
  code=$?
  breakages=$(( breakages + 1 ))

  if [ "$code" -ne 1 ]; then
    echo "FAIL reserved_self_test: $label — exit $code, expected 1." >&2
    echo "$out" | tail -5 >&2
    return 1
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    echo "FAIL reserved_self_test: $label — went red but never named $expect." >&2
    echo "$out" | tail -5 >&2
    return 1
  fi
  if ! printf '%s' "$out" | grep -q '^    fix: '; then
    echo "FAIL reserved_self_test: $label — no fix: line. A red a reader cannot act on" >&2
    echo "  is the reason it is still broken next week." >&2
    return 1
  fi
  if [ -n "$also" ] && ! printf '%s' "$out" | grep -q "$also"; then
    echo "FAIL reserved_self_test: $label — the finding did not name $also, so a reader" >&2
    echo "  cannot tell which of two files to open." >&2
    return 1
  fi
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: breakage $breakages — $label"
  return 0
}

failures=0
note() { echo "FAIL reserved_self_test: $*" >&2; failures=$(( failures + 1 )); }


control_core="$(run "$root")"
code=$?
controls=$(( controls + 1 ))
if [ "$code" -ne 0 ]; then
  note "the control — core's OWN tree under this checker — exit $code, expected 0."
  printf '%s\n' "$control_core" | tail -12 >&2
  failures=$(( failures + 1 ))
else
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: the control — core's own tree is green under this checker"
fi

control_fixture="$(run "$fixtures/conforming")"
code=$?
controls=$(( controls + 1 ))
if [ "$code" -ne 0 ]; then
  note "the control — the conforming fixture — exit $code, expected 0."
  printf '%s\n' "$control_fixture" | tail -12 >&2
  failures=$(( failures + 1 ))
else
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: the control — the conforming fixture is green"
fi


assert_red "a tombstone pointing at a surface that does not exist" \
  "$fixtures/stale" "reserved.surface-missing" "invoice_id" \
  || failures=$(( failures + 1 ))

assert_red "a manifest this checker cannot read at all" \
  "$fixtures/unreadable" "reserved.declaration-unreadable" "anywaye.yml" \
  || failures=$(( failures + 1 ))

assert_red "a name reserved and live in the SAME service, same surface" \
  "$fixtures/reintroduced" "reserved.reintroduced" "billing" \
  || failures=$(( failures + 1 ))

assert_red "a name reserved by one service and live in another" \
  "$fixtures/cross-service" "reserved.cross-service" "courier" \
  || failures=$(( failures + 1 ))


work="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-reserved-selftest.XXXXXX")"
trap 'rm -rf "$work"' EXIT

cp -R "$fixtures/reintroduced" "$work/path-form"
"$ANYWAYE_RESERVED_PYTHON" - "$work/path-form/billing/anywaye.yml" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    "removedFrom: billing.invoice.created",
    "removedFrom: schemas/events/billing/invoice/created.schema.json",
)
path.write_text(text, encoding="utf-8")
PY
assert_red "the same defect reached through a PATH-form surface, not an event type" \
  "$work/path-form" "reserved.reintroduced" \
  || failures=$(( failures + 1 ))

cp -R "$fixtures/cross-service" "$work/cross-path"
"$ANYWAYE_RESERVED_PYTHON" - "$work/cross-path/billing/anywaye.yml" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    "removedFrom: billing.invoice.created",
    "removedFrom: schemas/events/billing/invoice/created.schema.json",
)
path.write_text(text, encoding="utf-8")
PY
assert_red "a cross-service collision where the RESERVING service used a path-form surface" \
  "$work/cross-path" "reserved.cross-service" "courier" \
  || failures=$(( failures + 1 ))

cp -R "$fixtures/conforming" "$work/own-surface-clean"
out="$(run "$work/own-surface-clean")"
code=$?
if [ "$code" -ne 0 ]; then
  note "the conforming fixture is red, so every breakage below it is vacuous."
  printf '%s\n' "$out" | tail -12 >&2
  failures=$(( failures + 1 ))
else
  if printf '%s' "$out" | grep -q 'reserved.reintroduced'; then
    note "the conforming fixture names reserved.reintroduced, so the same-service" \
      "rule fires on a name its own contract does not publish."
  else
    passes=$(( passes + 1 ))
    echo "PASS reserved_self_test: the same-service rule stayed silent where it should"
  fi
fi

out="$(run "$fixtures/conforming")"
if printf '%s' "$out" | grep -q 'reserved.cross-service'; then
  note "the conforming fixture names reserved.cross-service, so the across-" \
    "services rule fires on a name nobody reserved from a surface that publishes it."
else
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: the cross-service rule stayed silent where it should"
fi

out="$(run "$work/no-such-directory")"
code=$?
if [ "$code" -ne 2 ]; then
  note "a root that does not exist returned $code, expected 2. A check that could not" \
    "find the fleet has not checked it, and 0 is the false green this exists to prevent."
  failures=$(( failures + 1 ))
else
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: a fleet root that does not exist exits 2, not 0"
fi

out="$(run --explain)"
code=$?
if [ "$code" -ne 0 ]; then
  note "--explain exited $code, expected 0."
  failures=$(( failures + 1 ))
else
  missing=""
  for id in reserved.declaration-unreadable reserved.surface-missing \
            reserved.reintroduced reserved.cross-service; do
    printf '%s' "$out" | grep -q "$id" || missing="$missing $id"
  done
  if [ -n "$missing" ]; then
    note "--explain does not describe:$missing"
    failures=$(( failures + 1 ))
  else
    passes=$(( passes + 1 ))
    echo "PASS reserved_self_test: every finding is describable by --explain"
  fi
fi


if [ "$failures" -ne 0 ]; then
  echo
  echo "FAIL: reserved_self_test — $failures failure(s), $breakages breakages went red naming their finding, $controls controls, $passes assertion(s) passed"
  exit 1
fi

echo
echo "PASS: reserved_self_test — everything above went the way it should have."

echo
echo "PASS: reserved_self_test — everything above went the way it should have."
echo
echo "  breakages that went RED naming their finding : $breakages"
echo "  controls (a true declaration, unbroken)      : $controls"
echo "  assertions that held                         : $passes"
echo "  SKIPPED                                      : 0"
echo
echo "PASS: reserved_self_test — $breakages breakages went red naming their finding, $controls controls, $passes assertion(s) passed"
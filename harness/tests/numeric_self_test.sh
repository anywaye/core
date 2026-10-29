#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures/numeric"
CONFORMING="$FIXTURES/conforming"
NONCONFORMING="$FIXTURES/nonconforming"
UNREADABLE="$FIXTURES/unreadable"

PY="${ANYWAYE_NUMERIC_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "numeric_self_test: no python >= 3.9 found; set ANYWAYE_NUMERIC_PYTHON" >&2
  exit 1
fi

for required in "$CONFORMING" "$NONCONFORMING" "$UNREADABLE"; do
  if [ ! -d "$required" ]; then
    echo "numeric_self_test: a fixture is missing at $required" >&2
    exit 1
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-numeric-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
breakages=0
warn_cases=0
green_cases=0
not_enforced_cases=0

run_check() { "$PY" "$HARNESS/numeric_check.py" "$@"; }

fresh_copy() {
  local name="$1"
  local fixture="$2"
  local dst="$WORK/$name"
  rm -rf "$dst"
  cp -R "$fixture" "$dst"
  printf '%s' "$dst"
}

edit() {
  apply_edit "$@" || {
    failures=$((failures + 1))
    printf 'FAIL numeric_self_test: a breakage did not apply — %s\n' "$1" >&2
    printf '  A self-test that silently stops breaking anything is worse than no self-test:\n' >&2
    printf '  it reports a pass for a check it had never exercised. The case below this line\n' >&2
    printf '  did not test what it claims to test.\n' >&2
    return 1
  }
}

apply_edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
found = body.count(old)
if found == 0:
    sys.exit(f"numeric_self_test: breakage no longer applies to {path}: {old!r} not found")
if found > 1:
    sys.exit(
        f"numeric_self_test: {path} contains {old!r} {found} times, so a replace of the "
        "first one may have edited a different field. Make the anchor unambiguous rather "
        "than hoping the first match is the right one."
    )
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
}

expect_red() {
  local label="$1" repo="$2" expect="$3" needle="${4:-}"
  local out code
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL numeric_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q -e "$expect"; then
    printf 'FAIL numeric_self_test: %s — went red as something else and never said %s\n%s\n' \
      "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if [ -n "$needle" ] && ! printf '%s' "$out" | grep -q -e "$needle"; then
    printf 'FAIL numeric_self_test: %s — went red as %s but never named %s, so it cannot be\n' \
      "$label" "$expect" "$needle" >&2
    printf '  told apart from a different position losing the same property.\n%s\n' "$out" >&2
    failures=$((failures + 1))
    return
  fi
  breakages=$((breakages + 1))
  printf 'PASS numeric_self_test: breakage %s: %s — caught by `%s`%s\n' \
    "$breakages" "$label" "$expect" "${needle:+ about $needle}"
}

expect_red_once() {
  local label="$1" repo="$2" expect="$3" needle="${4:-}"
  local out code count
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL numeric_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  count="$(printf '%s\n' "$out" | grep -c "^$expect ")"
  if [ "$count" -ne 1 ]; then
    printf 'FAIL numeric_self_test: %s — `%s` was reported %s times, and the claim is exactly once\n%s\n' \
      "$label" "$expect" "$count" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if [ -n "$needle" ] && ! printf '%s' "$out" | grep -q -e "$needle"; then
    printf 'FAIL numeric_self_test: %s — went red as `%s` but never said %s, so it cannot be\n' \
      "$label" "$expect" "$needle" >&2
    printf '  told apart from a different position losing the same property.\n%s\n' "$out" >&2
    failures=$((failures + 1))
    return
  fi
  breakages=$((breakages + 1))
  printf 'PASS numeric_self_test: breakage %s: %s — caught by `%s`, exactly once%s\n' \
    "$breakages" "$label" "$expect" "${needle:+ about $needle}"
}

expect_red_with_warning() {
  local label="$1" repo="$2" want_failure="$3" want_warning="$4"
  local out code
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL numeric_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  for want in "$want_failure" "$want_warning"; do
    if ! printf '%s' "$out" | grep -q -e "^$want "; then
      printf 'FAIL numeric_self_test: %s — the node is red but `%s` was not reported, so one\n' \
        "$label" "$want" >&2
      printf '  of its two true statements was lost.\n%s\n' "$out" >&2
      failures=$((failures + 1))
      return
    fi
  done
  breakages=$((breakages + 1))
  printf 'PASS numeric_self_test: breakage %s: %s — `%s` and, on the same node, `%s`\n' \
    "$breakages" "$label" "$want_failure" "$want_warning"
}

expect_warn() {
  local label="$1" repo="$2" expect="$3"
  local out code
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL numeric_self_test: %s — a warning moved the exit code to %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q -e "$expect"; then
    printf 'FAIL numeric_self_test: %s — exited 0 without printing %s\n%s\n' "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  warn_cases=$((warn_cases + 1))
  printf 'PASS numeric_self_test: warning case %s: %s — named, and exit 0\n' "$warn_cases" "$label"
}

expect_green() {
  local label="$1" repo="$2" must_print="${3:-}"
  local out code
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL numeric_self_test: %s — expected green, got exit %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if [ -n "$must_print" ] && ! printf '%s' "$out" | grep -q -e "$must_print"; then
    printf 'FAIL numeric_self_test: %s — exited 0 without printing %s, so the thing it could\n' \
      "$label" "$must_print" >&2
    printf '  not check is being reported as nothing being there.\n%s\n' "$out" >&2
    failures=$((failures + 1))
    return
  fi
  green_cases=$((green_cases + 1))
  printf 'PASS numeric_self_test: green case %s: %s — exit 0%s\n' \
    "$green_cases" "$label" "${must_print:+ and named what it cannot check}"
}

expect_not_enforced() {
  local label="$1" repo="$2" rule="$3"
  local out code
  out="$(run_check "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL numeric_self_test: %s — %s is declared not-enforced and still went red\n%s\n' \
      "$label" "$rule" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q -e "$rule"; then
    printf 'FAIL numeric_self_test: %s — a surface %s would have fired on came back green\n' \
      "$label" "$rule" >&2
    printf '  WITHOUT the report ever naming %s, so the silence is indistinguishable from an\n' "$rule" >&2
    printf '  unexamined surface. The ledger is what makes this green honest.\n' >&2
    failures=$((failures + 1))
    return
  fi
  if ! "$PY" -c "
import sys
sys.path.insert(0, '$HARNESS')
import numeric_check
sys.exit(0 if '$rule' in numeric_check.NOT_ENFORCED else 1)
"; then
    printf 'FAIL numeric_self_test: %s — %s is not in numeric_check.NOT_ENFORCED\n' "$label" "$rule" >&2
    failures=$((failures + 1))
    return
  fi
  not_enforced_cases=$((not_enforced_cases + 1))
  printf 'PASS numeric_self_test: not-enforced case %s: %s — stayed green, and the rule is in the ledger\n' \
    "$not_enforced_cases" "$label"
}

control_out="$(run_check "$CONFORMING" 2>&1)"
control_code=$?
if [ "$control_code" -ne 0 ]; then
  printf 'FAIL numeric_self_test: the control — the conforming fixture must be green, got exit %s\n%s\n' \
    "$control_code" "$control_out" >&2
  failures=$((failures + 1))
elif printf '%s' "$control_out" | grep -qE '^numeric\.(float|enum|float64-unsafe)[[:space:]]'; then
  printf 'FAIL numeric_self_test: the control is green but not WARNING-FREE, so it cannot tell a\n' >&2
  printf '  conforming surface from one this checker has an opinion about.\n%s\n' "$control_out" >&2
  failures=$((failures + 1))
else
  printf 'PASS numeric_self_test: the control — the conforming surface is green and warning-free\n'
fi


one="$(fresh_copy declared-maximum "$CONFORMING")"
edit "$one/openapi.json" '"maximum": 1000000' '"maximum": 9007199254740992'
expect_red 'an integer declaring a maximum AT the float64 exact range' \
  "$one" 'numeric.float64-unsafe' 'quantity'

two="$(fresh_copy one-past-the-limit "$CONFORMING")"
edit "$two/openapi.json" '"maximum": 1000000' '"maximum": 9007199254740993'
expect_red 'an integer declaring a maximum ONE PAST the float64 exact range' \
  "$two" 'numeric.float64-unsafe' 'quantity'

three="$(fresh_copy just-below-the-limit "$CONFORMING")"
edit "$three/openapi.json" '"maximum": 1000000' '"maximum": 9007199254740991'
expect_green 'an integer whose maximum stops one short of the float64 exact range' \
  "$three"

four="$(fresh_copy unbounded-identity "$CONFORMING")"
edit "$four/openapi.json" '"description": "A small non-negative integer with a ceiling well under 2**53. The breakages below rename this field and retype it; the ceiling is what makes it safe here.",
      "type": "integer",
      "minimum": 0,
      "maximum": 100' '"description": "A byte count with no maximum at all. Unbounded is only alarming where the ceiling is reachable, and an int64 file size reaches 2**53 with nothing but the writer bounding it.",
      "type": "integer",
      "minimum": 0'
edit "$four/openapi.json" '"version": {' '"byte_size": {'
expect_red 'an unbounded integer named like a byte count' \
  "$four" 'numeric.float64-unsafe' 'byte_size'

five="$(fresh_copy identity-name-alone "$CONFORMING")"
edit "$five/openapi.json" '"version": {' '"expires_at": {'
edit "$five/openapi.json" '"maximum": 100
    },' '"minimum": 0
    },'
expect_red 'a JWT exp claim, unbounded, where only the name makes it an identity' \
  "$five" 'numeric.float64-unsafe' 'expires_at'


six="$(fresh_copy a-bare-number "$CONFORMING")"
edit "$six/openapi.json" '"description": "A small non-negative integer with a ceiling well under 2**53. The breakages below rename this field and retype it; the ceiling is what makes it safe here.",
      "type": "integer",
      "minimum": 0,
      "maximum": 100' '"description": "A bare number with nothing else about it.",
      "type": "number",
      "minimum": 0,
      "maximum": 1'
expect_warn 'a bare `type: number`' "$six" 'numeric.float'

seven="$(fresh_copy numeric-enum "$CONFORMING")"
edit "$seven/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [200, 503]'
expect_warn 'a numeric enum where a closed set of words belongs' "$seven" 'numeric.enum'


ten="$(fresh_copy enum-one-past-the-limit "$CONFORMING")"
edit "$ten/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [0, 1, 9007199254740993]'
expect_red 'an integer enum carrying a member one past the float64 exact range' \
  "$ten" 'numeric.float64-unsafe' '9007199254740993'
expect_red_with_warning 'the same node, which is an unrepresentable value AND a closed union' \
  "$ten" 'numeric.float64-unsafe' 'numeric.enum'

eleven="$(fresh_copy enum-at-the-limit "$CONFORMING")"
edit "$eleven/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [0, 1, 9007199254740992]'
expect_green 'an integer enum whose largest member is exactly the float64 exact range' \
  "$eleven" 'numeric.enum'

twelve="$(fresh_copy enum-negative-member "$CONFORMING")"
edit "$twelve/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [-9007199254740993, 0]'
expect_red 'an integer enum carrying a large NEGATIVE member, which is a magnitude question' \
  "$twelve" 'numeric.float64-unsafe' '-9007199254740993'

thirteen="$(fresh_copy enum-negative-at-the-limit "$CONFORMING")"
edit "$thirteen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [-9007199254740992, 0]'
expect_green 'an integer enum whose largest member is exactly minus the float64 exact range' \
  "$thirteen" 'numeric.enum'

fourteen="$(fresh_copy untyped-enum-one-past-the-limit "$CONFORMING")"
edit "$fourteen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"enum": [0, 1, 9007199254740993]'
expect_red 'an integer enum with NO declared type, one member past the range' \
  "$fourteen" 'numeric.float64-unsafe' '9007199254740993'

fifteen="$(fresh_copy enum-and-maximum "$CONFORMING")"
edit "$fifteen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "maximum": 9223372036854775807,
      "enum": [0, 1, 9007199254740993]'
expect_red_once 'a node with BOTH a maximum past the range and an enum past it' \
  "$fifteen" 'numeric.float64-unsafe' 'declares maximum'
expect_red_with_warning 'and it keeps its closed-union warning rather than losing it' \
  "$fifteen" 'numeric.float64-unsafe' 'numeric.enum'

sixteen="$(fresh_copy float-enum "$CONFORMING")"
edit "$sixteen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "number",
      "enum": [1.5, 2.5]'
expect_warn 'an enum of floats, which is a float field and not a numeric enum' \
  "$sixteen" 'numeric.float'

seventeen="$(fresh_copy mixed-enum "$CONFORMING")"
edit "$seventeen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "integer",
      "enum": [1, "two"]'
expect_green 'an enum with one non-integer member, which is not a numeric enum' \
  "$seventeen"

eighteen="$(fresh_copy string-enum-of-a-53-bit-number "$CONFORMING")"
edit "$eighteen/openapi.json" '"type": "string",
      "enum": ["pending", "settled", "failed"]' '"type": "string",
      "enum": ["0", "9007199254740993"]'
expect_green 'a string enum whose members SPELL a 53-bit number, which is the convention' \
  "$eighteen"


expect_not_enforced 'an unbounded unsigned integer whose name says nothing about identity' \
  "$CONFORMING" 'numeric.unsigned'

expect_not_enforced "core's own schemas, unmodified" "$ROOT/schemas" 'numeric.unsigned'

expect_green 'a malformed document, reported as unread rather than as clean' \
  "$UNREADABLE" 'unreadable'


printf '\n'
printf 'numeric_self_test — counts, reported separately so a green cannot hide one:\n'
printf '  breakages that went RED and named their finding : %s\n' "$breakages"
printf '  warning cases that stayed GREEN                 : %s\n' "$warn_cases"
printf '  green cases, each of which named what it cannot check : %s\n' "$green_cases"
printf '  not-enforced cases that stayed GREEN and in the ledger : %s\n' "$not_enforced_cases"
printf '  controls (a conforming surface, unbroken)        : 1\n'
printf '  SKIPPED                                           : 0\n'
printf '  (nothing here is conditional on the machine: no case skips, and a case\n'
printf '   that could not run exits non-zero above rather than reporting a skip.)\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: numeric_self_test — %s case(s) the numeric checker did not get right: %s breakage(s), %s warning case(s), %s green case(s), %s not-enforced case(s).\n' \
    "$failures" "$breakages" "$warn_cases" "$green_cases" "$not_enforced_cases"
  exit 1
fi
printf 'PASS: numeric_self_test — %s breakages went red naming their finding, %s warning cases stayed green,\n' \
  "$breakages" "$warn_cases"
printf '      %s green cases and %s not-enforced cases, the control green and warning-free, 0 skipped.\n' \
  "$green_cases" "$not_enforced_cases"
printf '      The six languages are NOT read here — this proves the CONTRACT did not\n'
printf '      invite the bug, and a service'"'"'s own typed client is what proves the reader.\n'

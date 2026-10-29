#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures"

PY="${ANYWAYE_CONTRACT_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "core_version_test: no python >= 3.9 found; set ANYWAYE_CONTRACT_PYTHON" >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-core-version-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
passes=0
skips=0
breakages=0
copy_name=""

pass() { passes=$((passes + 1)); printf 'PASS core_version_test: %s\n' "$1"; }
fail() {
  failures=$((failures + 1))
  printf 'FAIL core_version_test: %s\n' "$1"
  shift
  while [ "$#" -gt 0 ]; do printf '%s\n' "$1" | sed 's/^/       /'; shift; done
}

fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  mkdir -p "$dst"
  cp -R "$HARNESS" "$dst/harness"
  chmod +x "$dst/harness/bin/anywaye-contract" 2>/dev/null || true
  printf '%s' "$dst"
}

edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
if old not in body:
    sys.exit(f"core_version_test: breakage no longer applies to {path}: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
  if [ $? -ne 0 ]; then
    fail "breakage no longer applies to $1"
    return 1
  fi
}

run_harness() {
  local dir="$1" fixture="$2" core="$3"
  shift 3
  ( cd "$dir" && "$PY" "$dir/harness/anywaye_contract.py" \
      --core "$core" "$dir/harness/tests/fixtures/$fixture" "$@" 2>&1 )
}

expect_red() {
  local label="$1" dir="$2" fixture="$3" want="$4" core="$5"
  shift 5
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$core" "$@")" || ec=$?
  if [ "$ec" -eq 0 ]; then
    fail "$label — the harness stayed GREEN" "$out"
  elif printf '%s\n' "$out" | grep -q "FAIL $want "; then
    breakages=$((breakages + 1))
    pass "$label — caught by \`$want\`"
  else
    fail "$label — red, but NOT via \`$want\`" "$out"
  fi
}

expect_refused() {
  local label="$1" dir="$2" fixture="$3" want="$4" want_code="$5" core="$6"
  shift 6
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$core" "$@")" || ec=$?
  if [ "$ec" -ne "$want_code" ]; then
    fail "$label — exit $ec, expected $want_code" "$out"
  elif ! printf '%s\n' "$out" | grep -q "FAIL $want "; then
    fail "$label — exit $ec but not via \`$want\`" "$out"
  else
    breakages=$((breakages + 1))
    pass "$label — refused with \`$want\`"
  fi
}

expect_green() {
  local label="$1" dir="$2" fixture="$3" core="$4"
  shift 4
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$core" "$@")" || ec=$?
  if [ "$ec" -eq 0 ]; then
    pass "$label — the harness is green on an unbroken tree"
  else
    fail "$label — the harness is RED on an unbroken tree" "$out"
  fi
}

printf -- '-- core_version_test: a `core:` constraint nobody checks is a comment\n'


if [ ! -f "$ROOT/VERSION" ]; then
  printf 'FAIL core_version_test: core publishes no VERSION at %s\n' "$ROOT/VERSION" >&2
  printf '  `core:` cannot be resolved against nothing. Add the file; do not skip.\n' >&2
  exit 1
fi

if ! "$PY" - "$ROOT" <<'PY'
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / "harness"))
import core_version

try:
    core_version.parse_version((pathlib.Path(sys.argv[1]) / "VERSION").read_text().strip())
except core_version.GrammarError as error:
    raise SystemExit(f"core_version_test: core's VERSION is not a core version: {error}")
PY
then
  exit 1
fi

CORE_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
UNSATISFIABLE="$("$PY" - "$CORE_VERSION" <<'PY'
import sys

major, minor, _patch = sys.argv[1].split(".")
print(f"^{major}.{int(minor) + 1}.0")
PY
)"

printf '   core publishes %s; the derived unsatisfiable constraint is %s\n' \
  "$CORE_VERSION" "$UNSATISFIABLE"


check_table() {
  local label="$1" constraint="$2" version="$3" want="$4" want_text="$5"
  local got
  got="$("$PY" - "$ROOT" "$constraint" "$version" <<'PY'
import pathlib
import sys

root, constraint, version = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, str(pathlib.Path(root) / "harness"))
import core_version

try:
    answer = core_version.resolve(constraint, version)
except core_version.GrammarError as error:
    print(f"unresolvable\t{error}")
else:
    print(f"{'yes' if answer.satisfied else 'no'}\t{answer.rationale}")
PY
)"
  if [ "${got%%$'\t'*}" = "$want" ] && printf '%s' "$got" | grep -qF "$want_text"; then
    pass "$label"
  else
    fail "$label — want ($want, contains $want_text), got: $got"
  fi
}

check_table 'caret on a 0.x release pins the minor: ^0.1.0 vs 0.2.0 is NOT satisfied' \
  '^0.1.0' '0.2.0' 'no' 'is not in [0.1.0, 0.2.0)'
check_table 'the same constraint against the version it names IS satisfied' \
  '^0.1.0' '0.1.0' 'yes' 'is in [0.1.0, 0.2.0)'
check_table '^0.2.0 admits 0.2.0' '^0.2.0' '0.2.0' 'yes' 'is in [0.2.0, 0.3.0)'
check_table '^0.2.0 does not admit 0.3.0' '^0.2.0' '0.3.0' 'no' 'is not in [0.2.0, 0.3.0)'
check_table 'a caret on 1.x admits every minor' '^1.2.3' '1.9.9' 'yes' 'is in [1.2.3, 2.0.0)'
check_table 'a caret on 1.x does not admit 2.0.0' '^1.2.3' '2.0.0' 'no' 'is not in [1.2.3, 2.0.0)'
check_table 'a caret on 0.0.z pins the patch' '^0.0.3' '0.0.4' 'no' 'is not in [0.0.3, 0.0.4)'
check_table 'a tilde pins the minor' '~1.2.3' '1.3.0' 'no' 'is not in [1.2.3, 1.3.0)'
check_table 'a floor is open-ended' '>=0.1.0' '0.2.0' 'yes' 'is at or above 0.1.0'
check_table 'a floor excludes below' '>=0.2.0' '0.1.9' 'no' 'is below 0.2.0'
check_table 'no operator means exactly' '0.2.0' '0.2.0' 'yes' 'is exactly 0.2.0'
check_table 'exactly excludes anything else' '0.2.0' '0.2.1' 'no' 'is not exactly 0.2.0'
check_table 'a leading zero is a second spelling and is refused' '^0.1.0' '0.01.0' \
  'unresolvable' 'leading zero'
check_table '10.0.0 is newer than 9.0.0 — numeric, not lexicographic' \
  '^9.0.0' '10.0.0' 'no' 'is not in [9.0.0, 10.0.0)'


base="$(fresh_copy control)"
expect_green 'the control: the conforming fixture against the real core' \
  "$base" conforming "$ROOT"

pinned="$(fresh_copy pinned)"
edit "$pinned/harness/tests/fixtures/conforming/anywaye.yml" \
  'core: ^0.2.0' "core: ^$CORE_VERSION"
expect_green "a service pinned to exactly core's published version ($CORE_VERSION)" \
  "$pinned" conforming "$ROOT"


unmet="$(fresh_copy constraint-unmet)"
edit "$unmet/harness/tests/fixtures/conforming/anywaye.yml" \
  'core: ^0.2.0' "core: $UNSATISFIABLE"
expect_red 'breakage 1: a `core:` constraint that does not admit core'"'"'s version' \
  "$unmet" conforming 'core.constraint-unmet' "$ROOT"

shipped="$(fresh_copy shipped-fixture)"
expect_red "breakage 1b: the shipped nonconforming-core-version fixture, which is what identity declares" \
  "$shipped" nonconforming-core-version 'core.constraint-unmet' "$ROOT"


leading="$(fresh_copy leading-zero)"
edit "$leading/harness/tests/fixtures/conforming/anywaye.yml" \
  'core: ^0.2.0' 'core: ^0.01.0'
expect_red 'breakage 2: a leading zero — the manifest schema admits it, the resolver refuses it' \
  "$leading" conforming 'core.constraint-unresolvable' "$ROOT"


noversion="$(fresh_copy version-absent)"
mkdir -p "$noversion/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$noversion/core/"
expect_refused 'breakage 3: a core checkout with no VERSION — the run could not happen' \
  "$noversion" conforming 'core.version-absent' 2 "$noversion/core"

withversion="$(fresh_copy version-present)"
mkdir -p "$withversion/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$withversion/core/"
printf '%s\n' "$CORE_VERSION" > "$withversion/core/VERSION"
expect_green "breakage 3b: the same throwaway core WITH a VERSION ($CORE_VERSION) is green" \
  "$withversion" conforming "$withversion/core"


printf -- '\n-- core_version_test: %s passed, %s failed, %s skipped (%s breakages proved red)\n' \
  "$passes" "$failures" "$skips" "$breakages"

if [ "$skips" -ne 0 ]; then
  failures=$((failures + skips))
fi

if [ "$failures" -ne 0 ]; then
  exit 1
fi
exit 0

#!/usr/bin/env bash
#
# The proof that `core:` means something.
#
#   bash harness/tests/core_version_test.sh
#
# WHAT THIS IS FOR
#   Until core-17, `core: ^0.2.0` in a service manifest was a comment. The
#   harness checked that the field was *present* (`core.absent`) and that it was
#   a plausible string, and never compared it to anything — because there was
#   nothing to compare it to. Core published no version at all: `git tag -l` in
#   `cafaye/core` is empty, and the version existed only as a `## [0.2.0]`
#   heading in a changelog. So "one deploy, many services, all compiling
#   against one core" had no way to notice when the core moved under a service
#   that had said which core it wanted.
#
#   Concretely, at the time this script was written: `identity`, `courier` and
#   `gateway` each declared `core: ^0.1.0` while compiling against 0.2.0 content,
#   and nothing in the fleet reported it.
#
# WHY THIS IS A SEPARATE SCRIPT AND NOT A SECTION OF `self_test.sh`
#   Two reasons, and the second is the real one. First, `self_test.sh` is
#   `gate_check.py`'s proof and mine is `cafaye_contract.py`'s; mixing them
#   means one failing file has two owners. Second — and this is the one that
#   would have rotted — every breakage in `self_test.sh` is chosen to be
#   *permanently* broken. This packet's central assertion is not: `^0.1.0`
#   stops being unsatisfiable the moment core publishes 0.3.0, so a fixture
#   pinned to it goes quietly green and nobody re-reads it. A separate script
#   derives its conflict from the version core actually publishes, which means
#   it stays red forever without anyone maintaining it.
#
# NOT PART OF `bin/prime`
#   Same reason `self_test.sh` is not: a self-test inside every gate
#   invocation is a second gate that can disagree with the first.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures"

# The interpreter is resolved exactly as `harness/bin/cafaye-contract` resolves
# it, so a pass here is a pass there.
PY="${CAFAYE_CONTRACT_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "core_version_test: no python >= 3.9 found; set CAFAYE_CONTRACT_PYTHON" >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cafaye-core-version-test.XXXXXX")"
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

# `harness/` travels whole: the breakages edit fixtures, and a copy without the
# module beside them fails for a different reason.
fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  mkdir -p "$dst"
  cp -R "$HARNESS" "$dst/harness"
  chmod +x "$dst/harness/bin/cafaye-contract" 2>/dev/null || true
  printf '%s' "$dst"
}

# edit <file> <old> <new> — FAILS LOUDLY if the fixture moved past the breakage.
# A self-test that silently stops breaking anything is worse than none.
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

# run_harness <dir> <fixture> <core> [args...]
run_harness() {
  local dir="$1" fixture="$2" core="$3"
  shift 3
  ( cd "$dir" && "$PY" "$dir/harness/cafaye_contract.py" \
      --core "$core" "$dir/harness/tests/fixtures/$fixture" "$@" 2>&1 )
}

# expect_red <label> <dir> <fixture> <rule-id> <core>
#
# The strong form: the NAMED rule must appear. "The gate went red" is weak when
# a dozen checks can make it red, and a breakage caught by the wrong check lets
# the check it was written for be dead code forever.
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

# expect_refused <label> <dir> <fixture> <rule-id> <exit code> <core>
#
# A run that could not happen and a run that found nothing are different exit
# codes, and collapsing them converts an unknown into a green badge.
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

# ---------------------------------------------------------------------------
# 0. Preconditions. Everything below is meaningless without them, and a
#    precondition that fails has to be a failure rather than a skip: a script
#    that skips its way to green is the defect this packet exists to remove.
# ---------------------------------------------------------------------------

if [ ! -f "$ROOT/VERSION" ]; then
  printf 'FAIL core_version_test: core publishes no VERSION at %s\n' "$ROOT/VERSION" >&2
  printf '  `core:` cannot be resolved against nothing. Add the file; do not skip.\n' >&2
  exit 1
fi

# The published version must itself be in the grammar, or every resolution below
# would be a resolution against an unparseable fact.
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
# The constraint that cannot be satisfied by ANY version of core: a caret one
# minor above what core publishes. `^A.B.0` admits `[A.B.0, A.B+1.0)`, and core
# publishes something in `[A.B, A.B+1)`, so core is always outside it. This is
# what keeps breakage 1 from rotting when core bumps its minor.
UNSATISFIABLE="$("$PY" - "$CORE_VERSION" <<'PY'
import sys

major, minor, _patch = sys.argv[1].split(".")
print(f"^{major}.{int(minor) + 1}.0")
PY
)"

printf '   core publishes %s; the derived unsatisfiable constraint is %s\n' \
  "$CORE_VERSION" "$UNSATISFIABLE"

# ---------------------------------------------------------------------------
# 1. The resolver's truth table, against the Go implementation it mirrors.
#
#    `caf/internal/contract/version.go` already resolves these strings, in Go.
#    A second implementation in Python is only defensible if it is the SAME
#    one, so every row below is a row `caf` also answers, and the caret rule
#    for a 0.x release is the row that matters most: it is why `^0.1.0` does
#    not admit 0.2.0, which is the whole finding.
# ---------------------------------------------------------------------------

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
    # Tab-separated like the success path, so the verdict is always field one.
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

# ---------------------------------------------------------------------------
# 2. The control. If the unbroken tree is already red, every breakage below
#    proves nothing.
# ---------------------------------------------------------------------------

base="$(fresh_copy control)"
expect_green 'the control: the conforming fixture against the real core' \
  "$base" conforming "$ROOT"

# A service declaring exactly what core publishes must be green. Without this,
# "the resolver says no to everything" would pass every breakage below.
pinned="$(fresh_copy pinned)"
edit "$pinned/harness/tests/fixtures/conforming/cafaye.yml" \
  'core: ^0.2.0' "core: ^$CORE_VERSION"
expect_green "a service pinned to exactly core's published version ($CORE_VERSION)" \
  "$pinned" conforming "$ROOT"

# ---------------------------------------------------------------------------
# 3. Breakage 1 — the finding. A declared constraint that does not admit the
#    version actually present, which is identity's, courier's and gateway's case.
# ---------------------------------------------------------------------------

unmet="$(fresh_copy constraint-unmet)"
edit "$unmet/harness/tests/fixtures/conforming/cafaye.yml" \
  'core: ^0.2.0' "core: $UNSATISFIABLE"
expect_red 'breakage 1: a `core:` constraint that does not admit core'"'"'s version' \
  "$unmet" conforming 'core.constraint-unmet' "$ROOT"

# The same, through the shipped fixture rather than an edited copy, so the
# fixture in the tree is known to be the thing that goes red.
shipped="$(fresh_copy shipped-fixture)"
expect_red "breakage 1b: the shipped nonconforming-core-version fixture, which is what identity declares" \
  "$shipped" nonconforming-core-version 'core.constraint-unmet' "$ROOT"

# ---------------------------------------------------------------------------
# 4. Breakage 2 — a constraint the manifest schema accepts and the resolver
#    refuses. `semverRange`'s pattern is `[0-9]+` and so admits `^0.01.0`; the
#    manifest is therefore valid, and `manifest.schema` is green, and a service
#    would compile against a core it has not actually named. This is the gap
#    between "the schema passed" and "the string means something", and it is
#    why the resolver refuses instead of coercing.
# ---------------------------------------------------------------------------

leading="$(fresh_copy leading-zero)"
edit "$leading/harness/tests/fixtures/conforming/cafaye.yml" \
  'core: ^0.2.0' 'core: ^0.01.0'
expect_red 'breakage 2: a leading zero — the manifest schema admits it, the resolver refuses it' \
  "$leading" conforming 'core.constraint-unresolvable' "$ROOT"

# ---------------------------------------------------------------------------
# 5. Breakage 3 — the refusal. A core that publishes no version cannot be
#     resolved against, and per the harness's own doctrine that is exit 2 and
#     never 0: a version check that cannot find a version has converted an
#     unknown into a green badge. It is the same defect as muse's
#     MUSE_CORE_SCHEMAS tier, pantry's PANTRY_CAFAYE_ROOT and the other two,
#     and it is the defect this repository exists to prevent.
# ---------------------------------------------------------------------------

noversion="$(fresh_copy version-absent)"
mkdir -p "$noversion/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$noversion/core/"
expect_refused 'breakage 3: a core checkout with no VERSION — the run could not happen' \
  "$noversion" conforming 'core.version-absent' 2 "$noversion/core"

# ...and the control for the refusal: that same core WITH a VERSION resolves,
# so breakage 3 is proved to be about the file and not about the fake core.
withversion="$(fresh_copy version-present)"
mkdir -p "$withversion/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$withversion/core/"
printf '%s\n' "$CORE_VERSION" > "$withversion/core/VERSION"
expect_green "breakage 3b: the same throwaway core WITH a VERSION ($CORE_VERSION) is green" \
  "$withversion" conforming "$withversion/core"

# ---------------------------------------------------------------------------
# Summary. Pass, fail and skip counted separately, because a summary that folds
# skips into passes is the reporting defect this packet was sent to fix.
# ---------------------------------------------------------------------------

printf -- '\n-- core_version_test: %s passed, %s failed, %s skipped (%s breakages proved red)\n' \
  "$passes" "$failures" "$skips" "$breakages"

# There is no skip in this script and there is no reason for one: every
# assertion is decidable from files in this repository. A skip here would be
# the fourth repository to turn an unknown into a green, so the count is
# printed above and a non-zero one is reported as the failure it is.
if [ "$skips" -ne 0 ]; then
  failures=$((failures + skips))
fi

if [ "$failures" -ne 0 ]; then
  exit 1
fi
exit 0

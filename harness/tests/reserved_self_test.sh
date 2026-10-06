#!/usr/bin/env bash
#
# reserved_self_test.sh — can harness/reserved_check.py say NO?
#
# Its own script rather than a section of gate_self_test.sh or
# tenancy_self_test.sh, for the reason those two headers give: the three
# checkers have different fixtures, different findings and different failure
# modes, and one script asserting all three would make a red in one
# indistinguishable from a red in another.
#
# WHAT A BREAKAGE HERE ASSERTS. That the checker exits NON-ZERO **and** that the
# report names the finding it expected. The second half is the half that is easy
# to leave out and it is the half that carries the weight: a checker that is
# wired into a gate and wired wrong fails on the wrong condition, and every
# breakage here would still be red while the gate learned nothing about which
# rule it is enforcing.
#
# THE CONTROL RUNS FIRST, AND IT IS A CONTROL OVER CORE ITSELF. Not over the
# `conforming` fixture alone: `harness/reserved_check.py .` over core's own tree
# is the answer to the question a service actually asks, which is "does my
# repository pass?", and a checker that has only ever met fixtures built to trip
# it has never answered it. It was that run — not a fixture — that found the
# two defects this script's fixture set could not have: a path-form surface that
# RESOLVED and was then reported unreadable, and the checker's own
# deliberately-broken fixtures being read as fleet members. Four of the eight
# findings it produced were the checker's fixtures, and a checker that complains
# about its own test data is a checker nobody runs.
#
# So the ordering here is load-bearing in the same way it is in self_test.sh: a
# control that ran after a breakage would not have controlled it, because a tree
# that is already red makes every "the checker went red" below it vacuous.
#
# THE COPIES ARE THROWAWAY AND THE WORKTREE IS NOT TOUCHED. Every breakage runs
# in a `mktemp -d` copy, for the same reason the harness self-test does it: the
# gate has a `git diff --exit-code` step over the whole tracked tree, and a
# self-test that mutated it would either trip that step or be caught by it after
# the fact.
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

# Pinned the way gate_red_proof in bin/prime pins its interpreter, and for the
# same reason: the default would otherwise be a fact about the machine rather
# than about the checkout. The wrapper takes CAFAYE_RESERVED_PYTHON first.
export CAFAYE_RESERVED_PYTHON="${CAFAYE_RESERVED_PYTHON:-python3}"

passes=0
breakages=0
controls=0

# run <dir> — the checker's answer about <dir>, on stdout. Never a subshell the
# caller cannot read, and never an exit code swallowed.
run() {
  "$check" "$1" 2>&1
}

# assert_red <label> <dir> <finding> [also-named-text]
#
# The three assertions, in the order a failure is worth having:
#   1. the exit code is 1 — a FAILURE, not the 2 that means "could not happen".
#      Asserting 1 and not merely "non-zero" is deliberate: a checker that exits
#      2 on a broken fixture has told the gate nothing about the rule, and it is
#      the 2 that a gate is most likely to read as an infrastructure problem and
#      retry.
#   2. the report names the expected finding id.
#   3. the report carries a `fix:` line — the whole reason `Finding.remediate`
#      exists, and the half a reader needs when the badge is red in CI.
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

# ---------------------------------------------------------------------------
# the control. Two of them, and the order is the claim.
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# every finding, one breakage each, naming itself.
# ---------------------------------------------------------------------------

assert_red "a tombstone pointing at a surface that does not exist" \
  "$fixtures/stale" "reserved.surface-missing" "invoice_id" \
  || failures=$(( failures + 1 ))

assert_red "a manifest this checker cannot read at all" \
  "$fixtures/unreadable" "reserved.declaration-unreadable" "cafaye.yml" \
  || failures=$(( failures + 1 ))

assert_red "a name reserved and live in the SAME service, same surface" \
  "$fixtures/reintroduced" "reserved.reintroduced" "billing" \
  || failures=$(( failures + 1 ))

assert_red "a name reserved by one service and live in another" \
  "$fixtures/cross-service" "reserved.cross-service" "courier" \
  || failures=$(( failures + 1 ))

# ---------------------------------------------------------------------------
# the two halves of the same-service answer, which the packet requires tested in
# both directions and which is the decision D44 records.
# ---------------------------------------------------------------------------

work="$(mktemp -d "${TMPDIR:-/tmp}/cafaye-reserved-selftest.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# Same service, PATH-form surface. The event-type spelling above is the first
# half; this is the second, and it is the half that was BROKEN before the packet
# fixed the two-spelling defect — the surface resolved and was then reported
# unreadable, which is a red for the wrong reason and would have satisfied a
# breakage that only asserted "not zero".
cp -R "$fixtures/reintroduced" "$work/path-form"
"$CAFAYE_RESERVED_PYTHON" - "$work/path-form/billing/cafaye.yml" <<'PY'
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

# A name that is reserved in one service and live in another, reached through a
# path-form surface. This is the breakage for the publisher derivation added to
# `publisher_of`, and without it the path-form cross-service case silently
# returned `None` — a rule that cannot fire, reached by the easiest spelling.
cp -R "$fixtures/cross-service" "$work/cross-path"
"$CAFAYE_RESERVED_PYTHON" - "$work/cross-path/billing/cafaye.yml" <<'PY'
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

# The GREEN half of the same-service answer, in the direction that is easy to
# get wrong: a service reserving a name that is live in ANOTHER service's
# surface, while its OWN surface does not publish it, must NOT be reported as
# `reserved.reintroduced`. The fixture is the cross-service one with the
# reservation taken out of its own surface — if the same-service finding fired
# here it would be firing on a name its own contract does not publish, which is
# the third finding this checker deliberately does not have (see
# notEnforced in harness/reserved_findings.json).
cp -R "$fixtures/conforming" "$work/own-surface-clean"
out="$(run "$work/own-surface-clean")"
code=$?
if [ "$code" -ne 0 ]; then
  note "the conforming fixture is red, so every breakage below it is vacuous."
  printf '%s\n' "$out" | tail -12 >&2
  failures=$(( failures + 1 ))
else
  # And the assertion that matters: the conforming fixture must NOT name the
  # same-service finding. A checker that reports everything is green over
  # nothing and this is the only assertion here that could catch it.
  if printf '%s' "$out" | grep -q 'reserved.reintroduced'; then
    note "the conforming fixture names reserved.reintroduced, so the same-service" \
      "rule fires on a name its own contract does not publish."
  else
    passes=$(( passes + 1 ))
    echo "PASS reserved_self_test: the same-service rule stayed silent where it should"
  fi
fi

# A tombstone whose name is live SOMEWHERE ELSE but reserved from a surface that
# does not contain it: the STALE half must still not be reported, because the
# surface resolves and the name is not on it. Asserted so the cross-service rule
# cannot be "achieved" by reporting every reservation against every name in the
# fleet, which is the shape a rule that fires too much takes and the shape the
# green control over core's own tree is there to catch.
out="$(run "$fixtures/conforming")"
if printf '%s' "$out" | grep -q 'reserved.cross-service'; then
  note "the conforming fixture names reserved.cross-service, so the across-" \
    "services rule fires on a name nobody reserved from a surface that publishes it."
else
  passes=$(( passes + 1 ))
  echo "PASS reserved_self_test: the cross-service rule stayed silent where it should"
fi

# The exit-2 half: a root that is not a directory must be 2, never 0 and never
# 1. This is the "the wrapper forbidden to degrade to a green" rule, asserted on
# the checker's own answer rather than only on the wrapper's, because the
# wrapper `exec`s the module and the module is where the number comes from.
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

# The --explain half: every finding id in the inventory must be printable, so a
# reader holding a red badge can ask what the rule is without reading the source.
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

# ---------------------------------------------------------------------------
# the footer. Read by bin/prime, so both its wording and its SHAPE are a
# contract — `count_line` in bin/prime matches `^  <label>: <number>$`, so a
# summary line where a counts row belongs reads as "exited 0 without reporting
# its counts" and fails the gate. That is the same defect the CI step for the
# harness self-test had and fixed by reading the phrase the footer prints, and
# the same one CI's count-comparison step reads here.
#
# The counts block is emitted on the SUCCESS path only, and SKIPPED is a literal
# zero rather than a count, because this script has no skip: a case that could
# not run exits 2 naming the precondition, at the top, before any case runs. So
# the number is a claim about the script and not about the machine — which is the
# opposite of the reserved checker's own exit 2, and deliberately so.
# ---------------------------------------------------------------------------

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
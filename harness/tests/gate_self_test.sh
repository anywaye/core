#!/usr/bin/env bash
#
# gate_self_test.sh — the gate checker's proof that it is able to fail.
#
#   bash harness/tests/gate_self_test.sh
#
# WHAT THIS IS FOR
#
# A checker that has only ever said "yes" is a report, not a gate. This script
# takes ONE conforming fixture — a small repository that declares its gate and
# tells the truth about all of it — copies it twenty-five times, breaks exactly
# one thing in each copy, and asserts the checker goes red each time. Every
# breakage names the finding it expects, so a red proves that *the check
# written for that defect* is still load-bearing, which is a different claim
# from "something went red" and the one that decays silently.
#
# AND THAT WAS NOT ENOUGH, WHICH IS WHY THIS FILE CHANGED SHAPE IN core-12
#
# Twenty-five reds prove the checker can fail, and `gate.ci-disagrees` spent a
# fleet release firing on correct workflows while every one of them stayed green
# — because the fixture teaches ONE spelling of `run:`, and it happened to be the
# one the checker understood. Red cases only ever exercise the inputs somebody
# already disliked. So there are positive cases now too: twelve REAL workflows,
# spelled the way gateway/ci.yml, parlor/ci.yml and kit/ci.reusable.yml spell them,
# each asserted to be ACCEPTED with no finding at all. A control proves the
# fixture conforms; only the shape cases prove it conforms in the spelling anyone
# actually writes.
#
# The shape is harness/tests/self_test.sh's, and it is the same shape for the
# same reason: a control on the unbroken fixture first (without it twenty-five
# reds prove nothing), a fresh throwaway copy per case (one must never mask the
# next), and a non-zero exit if any breakage stayed green. Nothing in the
# committed tree is a deliberately broken repository — the breakages are diffs
# applied here, so a reviewer reads what is being broken rather than having to
# reconstruct it.
#
# THE ONE THAT MATTERS IS BREAKAGE 7
#
# Twelve of these breakages are a checker string-matching: the command names a
# file that is not there, the task is not in the config, the workflow does not
# call the gate. A checker that did nothing but compare strings would pass all
# twelve. Breakage 8 is a repository whose declaration is **well formed and
# completely true about a gate that exits 0 without having run anything**, and
# it is the whole reason `gate.proof` exists. It is also the shape this fleet
# has already shipped once: `… | tail -45; echo "PRIME EXIT=$?"` under zsh,
# where `$?` is `tail`'s, read as "PRIME EXIT=0" over a log that said FAIL.
#
# THE WARNINGS ARE TESTED TOO, AND SO IS THE PROMISE THEY MAKE
#
# Seven cases produce a `warn`, and `expect_warn` asserts the **exit code is
# still 0** in every one of them. That is the tri-state contract of MD13 made
# mechanical: a warning is a claim this machine could not settle, it is printed
# and counted separately, and it never moves the verdict. A checker that turned
# a warning into a failure would be one that is red on a laptop and green on CI,
# which is the same defect in a new place.
#
# THE COLOUR CASES ARE GREEN CASES, AND THAT IS THE OTHER HALF
#
# Twenty-three breakages prove the checker can say no. Three colour cases prove it
# can also say YES to the repository it should: a gate that really ran 377 tests
# through a colourising runner, a proof sitting behind an OSC hyperlink, and a
# proof below an unterminated OSC. Those are not breakages — nothing about them is
# wrong — so nothing going red would prove nothing about them, and a stripper
# that deletes too much passes all twenty-three breakages while turning a genuine
# false green back on. Two more colour cases are deliberately RED: a proof that is
# genuinely absent, and a suite below its floor, both printed through colour.
# Stripping changes WHERE a pattern is applied and never WHETHER an absent proof
# or a breached floor is reported.
#
# IT IS INSIDE `bin/prime` SINCE core-14, AND THAT IS NOT THE RECURSION
#
# `bin/prime` must never run `harness/gate_check.py --prove`: the checker runs
# the declared gate, the declared gate is `bin/prime`, and a gate that proves
# itself by running itself terminates. That reasoning is sound and it stands.
#
# This script is not that call. It runs assertions about the checker in
# throwaway copies of `harness/tests/fixtures/gates/conforming` — a repository
# whose declared gate is three lines long and is not `bin/prime`. Nothing here
# reads core, runs `bin/prime`, or knows this repository exists, so there is no
# cycle for that termination to travel round, and the two answer different
# questions: `--prove` asks whether THIS gate ran, and this script asks whether
# the checker could have said no about anything at all.
#
# Until core-14 it ran in CI only, which made the local gate weaker than CI in
# precisely the place where a weaker gate is invisible: a developer could have
# replaced `gate_check.py` with a function that returns 0 and `bin/prime` would
# still have printed `173/173 passed` and exited 0. `harness/tests/self_test.sh`
# — the contract harness's own red proof — is still a CI step only, and the
# asymmetry is deliberate: this script guards the checker that `bin/prime` runs
# on the very next line, so a developer who has just run it knows whether that
# answer was earned. See REPORT-core-14.
#
# WHAT IT IS NOT
#
# Not exhaustive mutation testing, and it does not claim to catch every defect.
# It proves every specific breakage, twelve specific real spellings being
# accepted, four extractor assertions, five specific things about colour (three
# green, two red), and that the checker does not launder a secret out of a
# gate's output into its own report. It does not prove the gate's tests touched
# what they claim to — that is MD12's collect-then-run machinery, owed in `caf`,
# and harness/gate_findings.json names it.
#
# The three breakages the packet names — the missing command, the missing task,
# and the false green — are *also* in tests/test_specs.py, so the suite itself is
# red if those three stop being caught; this script is the wider net.

set -uo pipefail

# --------------------------------------------------------------------------
# THE INTERPRETER, AND THE ONE PLACE THIS SCRIPT DECIDES WHICH
#
# Every case below is a shell case that shells out to `$PY`, so this block is
# the precondition the whole script rests on: no interpreter, no cases, and a
# non-zero exit rather than a summary claiming otherwise.
#
# `resolve_interpreter` is the ONLY place that decision is made, and the two
# cases at the foot of this script test it by calling it back through
# `--which-python`, which runs this decision and nothing else. There is
# deliberately no second copy of the candidate list: a search that is tested
# anywhere but where it runs is a search nobody tested.
# --------------------------------------------------------------------------

# interpreter_is_new_enough <path> — the one probe the search makes. 3.11 is not
# a preference: `tomllib` is stdlib from 3.11 and `harness/gate_check.py` reads
# `mise.toml` with it, so 3.9 cannot answer the question this script is here to
# ask. See DECISIONS.md D31.
interpreter_is_new_enough() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

# resolve_interpreter — print the interpreter to use, or nothing and fail.
#
# THE FIX, IN ONE SENTENCE: a candidate that RESOLVES is not a candidate that
# QUALIFIES, and the loop this replaces stopped at the first one that resolved.
# It broke out of the candidate list on `command -v` succeeding and checked the
# version afterwards, so on a machine whose `python3` is 3.9.6 it took that one,
# stopped, and printed "no python >= 3.11 found" while 3.13 and 3.14 sat unused
# on the same PATH. A false negative in the project's own proof-of-failure — and
# one that reads exactly like a machine that genuinely has nothing, which is why
# it survived: the only way to see it was to be the developer with the 3.9
# `python3`, which is not a machine CI has.
#
# So: walk the WHOLE list, and stop at the first candidate that PASSES the
# version check. `harness/tests/fixtures/interpreter-path` is the PATH that makes
# this reproducible everywhere rather than on that one laptop.
resolve_interpreter() {
  local candidate resolved
  # An explicit override is honoured as given, and a too-old one is an ERROR
  # rather than a reason to go looking for a second interpreter. Someone who
  # pinned CAFAYE_GATE_PYTHON asked for that one; quietly answering with a
  # different program would make every PASS line below a claim about an
  # interpreter nobody chose. That behaviour is unchanged, and it is why
  # `bin/prime`'s venv interpreter still wins outright.
  if [ -n "${CAFAYE_GATE_PYTHON:-}" ]; then
    if interpreter_is_new_enough "$CAFAYE_GATE_PYTHON"; then
      printf '%s\n' "$CAFAYE_GATE_PYTHON"
      return 0
    fi
    return 1
  fi
  for candidate in python3 python3.13 python3.12 python3.11 python; do
    # `command -v` is kept as the existence test because a name that does not
    # resolve is not worth probing, and its OUTPUT is what gets printed and
    # executed — one PATH lookup, and the line this script reports is the file
    # that actually answered rather than a bare name re-resolved later.
    resolved="$(command -v "$candidate" 2>/dev/null)" || continue
    if interpreter_is_new_enough "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURE="$HARNESS/tests/fixtures/gates/conforming"
SELF="$HARNESS/tests/gate_self_test.sh"
# Captured before any case rewrites PATH for a child, so the two interpreter
# cases at the foot of this script can put a fixture directory FIRST and still
# leave the child a working `dirname`, `awk` and `grep`.
ORIGINAL_PATH="$PATH"

PY="$(resolve_interpreter)" || PY=""
if [ -z "$PY" ]; then
  echo "gate_self_test: no python >= 3.11 found; set CAFAYE_GATE_PYTHON" >&2
  exit 1
fi

# --which-python — resolve, print, stop. The precondition with the cases
# removed, so a case can drive the real search on a fixture PATH without
# running the script that case lives in. Without it the `stale-first` case
# below would re-enter this script, find the fixture's python3.13, run every
# case including itself, and recurse until the machine gave up; and the run
# would be wrong before it was infinite, because every case's fixture gate
# calls `python3` for itself.
#
# Exit codes are the script's own: 0 with the interpreter on stdout, 1 with the
# message above on stderr and nothing at all on stdout, so a caller can tell
# "found one" from "found none" without reading prose.
#
# Exactly ONE line, deliberately: each candidate is probed once by the search, and
# asking the winner for its version as well would run it a second time and put a
# second copy of its name in the trace the two cases below assert exactly. The
# path already says which interpreter answered, and `bin/prime` prints the version
# in its own header.
if [ "${1:-}" = "--which-python" ]; then
  printf '%s\n' "$PY"
  exit 0
fi

if [ ! -d "$FIXTURE" ]; then
  echo "gate_self_test: the conforming fixture is missing at $FIXTURE" >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cafaye-gate-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
# `breakages` is the CASE NUMBER, not a tally: it is incremented by hand before
# each red-proof case so every printed line can name the one a comment refers to
# ("breakage 7", "breakage 8"), and it deliberately counts the warning cases too
# so the numbering matches the order the cases run in. A tally that is a
# hand-maintained label is not a measurement, so every category below is counted
# inside the function that runs the case — see `red_cases` and `leak_cases`
# below, and the footer, which is the only place a count is printed.
breakages=0
red_cases=0
warn_cases=0
green_cases=0
spelling_cases=0
extractor_cases=0
colour_cases=0
leak_cases=0
search_cases=0
copy_name=""

# A fresh copy of the conforming fixture per breakage. The fixture carries its
# own mise.toml, bin/ and .github/, so a copy of the fixture is a copy of a
# repository; nothing outside the fixture is read, and the worktree is not
# touched.
fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  rm -rf "$dst"
  cp -R "$FIXTURE" "$dst"
  chmod +x "$dst/bin/gate"
  printf '%s' "$dst"
}

# edit <file> <old> <new> — a textual breakage that FAILS LOUDLY if the fixture
# has moved past it. A self-test that silently stops breaking anything is worse
# than no self-test, so an unmatched edit is an error here rather than a pass.
edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
if old not in body:
    sys.exit(f"gate_self_test: breakage no longer applies to {path}: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
}

# write <file> <content-on-stdin> — for a breakage that replaces a whole file,
# such as the gate that exits zero without running anything.
write() {
  cat > "$1"
}

# expect_red <label> <repo> <finding-id> — the fixture must go red, the exit
# code must be 1, and the finding must be NAMED. "Something went red" is not
# the claim; "this check is still the one that catches this defect" is.
expect_red() {
  local label="$1" repo="$2" expect="$3"
  local out
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — went red as %s but never said %s\n%s\n' \
      "$label" "something else" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  red_cases=$((red_cases + 1))
  printf 'PASS gate_self_test: breakage %s: %s — caught by `%s`\n' "$breakages" "$label" "$expect"
}

# expect_colour_red <label> <repo> <finding-id> — as expect_red, but counted and
# labelled as a colour case rather than as a breakage.
#
# It exists because the counter is the point of this script: a reader scanning the
# output has to be able to see how many of each kind ran, and printing these under
# "breakage 23" twice would report five breakages when there are three. A count
# that cannot be read is a count that has already started lying.
expect_colour_red() {
  local label="$1" repo="$2" expect="$3"
  local out
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — went red as %s but never said %s\n%s\n' \
      "$label" "something else" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  colour_cases=$((colour_cases + 1))
  printf 'PASS gate_self_test: colour red %s: %s — caught by `%s`\n' "$colour_cases" "$label" "$expect"
}

# expect_green <label> <repo> — the fixture must come back green in BOTH phases.
#
# The counterpart to expect_red, and it is here because a stripper that deletes
# too much also produces greens. Every colour case below is a repository that is
# entirely TRUE about a gate that really ran: green is the expected verdict, so
# "nothing went red" would prove nothing about them, and they need an assertion
# of their own that says so explicitly.
expect_green() {
  local label="$1" repo="$2"
  local out code
  out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL gate_self_test: %s — expected green, got exit %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  green_cases=$((green_cases + 1))
  printf 'PASS gate_self_test: green case %s: %s — matched in both phases\n' "$green_cases" "$label"
}

# expect_warn [--prove] <label> <repo> <finding-id> — the fixture must print the
# finding AND STILL EXIT 0. The exit code is the half that matters, and it is
# the half a tri-state checker gets wrong.
expect_warn() {
  local prove_it=""
  if [ "${1:-}" = "--prove" ]; then prove_it="--prove"; shift; fi
  local label="$1" repo="$2" expect="$3"
  local out
  # shellcheck disable=SC2086
  out="$("$PY" "$HARNESS/gate_check.py" $prove_it --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL gate_self_test: %s — a warning moved the exit code to %s\n%s\n' \
      "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL gate_self_test: %s — exited 0 without even printing %s\n%s\n' \
      "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  warn_cases=$((warn_cases + 1))
  printf 'PASS gate_self_test: warning %s: %s — said `%s` and still exited 0\n' \
    "$warn_cases" "$label" "$expect"
}

# expect_no_leak <label> <repo> <secret> — a gate whose output contains a value
# read from its environment. The checker's REPORT must not contain it, and its
# log file must: the report is what a person reads and what a CI log keeps, and
# the log is the gate's own output, which is the operator's to read.
expect_no_leak() {
  local label="$1" repo="$2" secret="$3"
  local out log
  out="$(DATABASE_URL="$secret" "$PY" "$HARNESS/gate_check.py" \
    --prove --log-dir "$repo/.log" "$repo" 2>&1)"
  local code=$?
  log="$(cat "$repo/.log/gate.log" 2>/dev/null || true)"
  if [ "$code" -ne 1 ]; then
    printf 'FAIL gate_self_test: %s — expected the leaky gate to be red, got %s\n' "$label" "$code" >&2
    failures=$((failures + 1))
  elif printf '%s' "$out" | grep -qF "$secret"; then
    printf 'FAIL gate_self_test: %s — the checker copied a value out of the gate environment into its own report\n' \
      "$label" >&2
    failures=$((failures + 1))
  elif ! printf '%s' "$log" | grep -qF "$secret"; then
    printf 'FAIL gate_self_test: %s — the gate log should hold the gate output; it does not, so the check above proved nothing\n' \
      "$label" >&2
    failures=$((failures + 1))
  else
    leak_cases=$((leak_cases + 1))
    printf 'PASS gate_self_test: the gate that leaked at runtime: the report stayed clean and the log held it\n'
  fi
}

# expect_python_search <walks-on|exhausted|override> <label> <bindir> <expected-trace>
#
# Drives the real interpreter search on a PATH built from a fixture directory,
# and asserts WHERE IT STOPPED rather than only what it returned.
#
# EVERY MODE RUNS `--which-python`, and that is the load-bearing decision here,
# arrived at by measurement rather than taste. The obvious "stronger" case — run
# the WHOLE script on a PATH with no qualifying interpreter, and assert its exit
# code — was written first, and it does not fail when the search is broken. It
# FORKS. Measured, with the original loop condition restored: the child resolves
# the 3.9.6 stub, `PY` is non-empty, the precondition lets it through, and the
# child runs every case down to this one, which spawns another child. Eighteen
# seconds in, the process tree was
#
#     97132 -> 97666 -> 97667 -> 98130 -> ...
#
# each link a `gate_self_test.sh` whose parent is the last, still growing, and
# killed by hand rather than by anything this project would recognise as a
# failure. A gate that exhausts a machine instead of going red is strictly worse
# than the false green it replaced: inside `bin/prime` it spends the 900s the
# declaration allows and then reports a timeout that names nothing. A red proof
# has to fail QUICKLY and SAY WHY, and that is true of this one only because it
# stops before the first case.
#
# That is not a weaker claim than the whole-script run, and the reason is the
# order of the block at the top of this file: the `--which-python` branch sits
# AFTER the "no python >= 3.11 found" precondition. On a PATH where the search
# finds nothing, the flag run and a plain run are the same execution up to and
# including the exit — same search, same message on stderr, same exit 1, same
# empty stdout — and the flag's only further effect is to stop a run that was
# about to continue anyway. It cannot manufacture the refusal it asserts.
#
# <walks-on>   the stale `python3` is rejected and the search walks on to the
#              qualifying `python3.13` beside it.
# <exhausted>  all five names resolve and every one is too old, so the search
#              consults the WHOLE list and the script refuses with its message.
# <override>   `CAFAYE_GATE_PYTHON` names an interpreter that resolves and is too
#              old, and that is an ERROR rather than a reason to go looking for
#              a second one. This one guards the half of the contract that is
#              easy to lose while fixing the other: a "fixed" search that quietly
#              ignores a too-old override and answers with something else makes
#              every PASS line in this script a claim about an interpreter nobody
#              chose. It is a guard, not a red proof of the loop — it stays green
#              with the loop condition reverted, which is what a guard is for.
#
# <expected-trace> is the exact ordered list of candidates the search consulted,
# one name per line, from the stubs' own appends. It is what separates "tried the
# stale python3, rejected it, went on" from "happened to skip it", and on the
# exhausted PATH it is what proves the loop did not give up early. It is also
# what names a mistake in this fixture rather than in the search: a stub without
# +x falls through to a real interpreter somewhere else on the host's PATH — one
# that answers the probe perfectly well, from the wrong place — and only the
# trace can tell that apart from a search that behaved.
expect_python_search() {
  local sense="$1" label="$2" bindir="$3" want="$4"
  local trace="$WORK/search-$search_cases.trace" errf="$WORK/search-$search_cases.err"
  local out err code real got
  # `sys.executable`, not `$PY`: under `bin/prime` `$PY` is the venv (fine), and
  # on a laptop it can be a mise SHIM, and a shim resolves through PATH — which
  # is the fixture directory we just put a stub `python3` into. Asking Python
  # where it really lives is the one answer that does not care what PATH says.
  real="$("$PY" -c 'import sys; print(sys.executable)')"
  # `override` names the stale stub in CAFAYE_GATE_PYTHON and leaves PATH alone,
  # because that case is about the override winning outright. The other two
  # EMPTY CAFAYE_GATE_PYTHON rather than unsetting it, because their whole claim
  # is about the search that runs when it is ABSENT; a value inherited from
  # `bin/prime` would skip the search entirely and the case would prove nothing
  # while reporting that it had.
  if [ "$sense" = "override" ]; then
    out="$(CAFAYE_GATE_PYTHON="$bindir/python3" CAFAYE_FIXTURE_PYTHON="$real" \
      CAFAYE_FIXTURE_TRACE="$trace" PATH="$ORIGINAL_PATH" \
      "${BASH:-bash}" "$SELF" --which-python 2>"$errf")"
  else
    out="$(CAFAYE_GATE_PYTHON='' CAFAYE_FIXTURE_PYTHON="$real" CAFAYE_FIXTURE_TRACE="$trace" \
      PATH="$bindir:$ORIGINAL_PATH" "${BASH:-bash}" "$SELF" --which-python 2>"$errf")"
  fi
  code=$?
  err="$(cat "$errf" 2>/dev/null || true)"
  got="$(cat "$trace" 2>/dev/null || true)"

  # The trace is asserted FIRST, because it is the narrowest claim and the one
  # that localises a failure: if the search consulted the wrong candidates, no
  # verdict it went on to reach means anything. The report carries the child's
  # own exit code and stdout as well, because a search that stops early leaves an
  # EMPTY trace — a stub is only run when it is probed, and a loop that printed
  # the first name it resolved never probed anything — and "consulted nothing"
  # on its own reads like a broken fixture rather than the defect it is. The
  # stdout line is what says "and then it used that one anyway".
  if [ "$got" != "$want" ]; then
    printf 'FAIL gate_self_test: %s — consulted these candidates:\n%s\nexpected exactly:\n%s\n' \
      "$label" "${got:-<none — nothing was probed at all}" "$want" >&2
    printf '  it exited %s and answered with: %s\n' "$code" "${out:-<nothing>}" >&2
    failures=$((failures + 1))
    return
  fi

  # <refused> — shared by `exhausted` and `override`, because both claim the same
  # three things and the message is the script's own bytes rather than a copy of
  # them. Compared in full, not grepped: this is the one line an operator sees
  # when the gate cannot run at all, and a search that refused with a different
  # sentence has not told anybody anything.
  refused() {
    local n="$1" want_out="$2"
    if [ "$code" -ne 1 ]; then
      printf 'FAIL gate_self_test: %s — exited %s, expected 1\n' "$n" "$code" >&2
      return 1
    fi
    if [ "$err" != 'gate_self_test: no python >= 3.11 found; set CAFAYE_GATE_PYTHON' ]; then
      printf 'FAIL gate_self_test: %s — exited 1 without saying exactly why\n  said: [%s]\n' \
        "$n" "${err:-<nothing>}" >&2
      return 1
    fi
    # Nothing on stdout. The exit has to come from the precondition and not from
    # some case failing forty lines in: a script that ran its cases and then
    # reported "no python found" would be lying about which half of itself was
    # talking, and this row is what keeps those two apart.
    if [ "$out" != "$want_out" ]; then
      printf 'FAIL gate_self_test: %s — stdout was [%s], expected [%s]\n' \
        "$n" "${out:-<nothing>}" "${want_out:-<nothing>}" >&2
      return 1
    fi
    return 0
  }

  case "$sense" in
    walks-on)
      # The answer has to be the FIXTURE one, not merely some new-enough
      # interpreter. Asserted on the whole path for that reason: a bare
      # `python3.13` would match the host's python3.13 too, and this case is
      # about which file on the PATH answered.
      if [ "$code" -ne 0 ]; then
        printf 'FAIL gate_self_test: %s — a PATH whose FIRST candidate is 3.9 but whose SECOND qualifies exited %s\n' \
          "$label" "$code" >&2
        failures=$((failures + 1))
        return
      fi
      if [ "$out" != "$bindir/python3.13" ]; then
        printf 'FAIL gate_self_test: %s — took %s, which is not the qualifying interpreter on this PATH (%s)\n' \
          "$label" "${out:-<nothing>}" "$bindir/python3.13" >&2
        failures=$((failures + 1))
        return
      fi
      if [ -n "$err" ]; then
        printf 'FAIL gate_self_test: %s — found an interpreter and still complained\n%s\n' \
          "$label" "$err" >&2
        failures=$((failures + 1))
        return
      fi
      ;;
    exhausted)
      if ! refused "$label" ''; then
        failures=$((failures + 1))
        return
      fi
      ;;
    override)
      # The trace above proves the pinned interpreter was PROBED AT ALL, which a
      # search that ignored the variable outright would not do. It cannot
      # distinguish "refused the override" from "rejected it and then searched
      # PATH anyway" — a real python on the host appends nothing, so both leave
      # the same single line. The exit code and the empty stdout are what settle
      # it: a fall-through finds the host's own 3.14 and exits 0 having printed
      # its path, which is precisely the substitution being ruled out.
      if ! refused "$label" ''; then
        failures=$((failures + 1))
        return
      fi
      ;;
    *)
      printf 'FAIL gate_self_test: %s — bad sense %s\n' "$label" "$sense" >&2
      failures=$((failures + 1))
      return
      ;;
  esac
  search_cases=$((search_cases + 1))
  printf 'PASS gate_self_test: interpreter search %s: %s\n' "$search_cases" "$label"
}

# --------------------------------------------------------------------------
# the shape cases. Everything above this line proves the checker CAN fail; what
# follows proves it is looking at the right thing.
#
# write_case_workflow <repo> — the case body on stdin is the tail of a workflow,
# everything after a fixed preamble. The preamble is boilerplate, so a reviewer
# reads the four interesting lines of a case instead of a whole workflow file,
# and — this is the part that matters — the shape under test is the ONLY thing
# that varies between one case and the next.
write_case_workflow() {
  {
    printf 'name: ci\n\non: [push]\n\njobs:\n  gate:\n    runs-on: ubuntu-latest\n'
    printf '    steps:\n      - uses: actions/checkout@v7\n      - name: the gate\n'
    cat
  } > "$1/.github/workflows/ci.yml"
}

# accepts <label> — a workflow whose gate step is spelled exactly as the case body
# on stdin must come back GREEN.
#
# This is the half the twenty-three breakages cannot be. Each of those breaks a
# repository and asserts a red, which is a checker being shown a face it already
# knows; a checker proven only on its red cases is proven only on the inputs
# somebody already disliked. The claim these cases make is the one that was
# actually false for a fleet release: **this workflow plainly runs the gate.**
#
# `gate.ci-disagrees` read `run:` through a pattern that could only see a block
# scalar, and every one of those twenty-three breakages stayed green while it did,
# because the conforming fixture taught the checker the one spelling that
# happened to work. The control was green and the checker was wrong. A control
# proves the fixture is conforming; only these prove the fixture is CONFORMING
# IN THE SPELLING THE FLEET ACTUALLY USES.
accepts() {
  local label="$1"
  local repo out code
  spelling_cases=$((spelling_cases + 1))
  repo="$(fresh_copy "accept-$spelling_cases")"
  write_case_workflow "$repo"
  out="$("$PY" "$HARNESS/gate_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ] || printf '%s' "$out" | grep -qE '^(FAIL|WARN) gate\.'; then
    printf 'FAIL gate_self_test: shape %s: %s — a workflow that plainly runs the gate was rejected (exit %s)\n%s\n' \
      "$spelling_cases" "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  printf 'PASS gate_self_test: shape %s: %s — accepted\n' "$spelling_cases" "$label"
}

# accepts_whole <label> — the case body on stdin is an ENTIRE workflow, for the
# cases whose subject is the shape of the file rather than the shape of one line.
# A case that claims to be about a reusable workflow and is really about a `run:`
# line is a case that teaches the reader the wrong thing, which is the one cost
# this script is paying to avoid.
accepts_whole() {
  local label="$1"
  local repo out code
  spelling_cases=$((spelling_cases + 1))
  repo="$(fresh_copy "whole-$spelling_cases")"
  cat > "$repo/.github/workflows/ci.yml"
  out="$("$PY" "$HARNESS/gate_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ] || printf '%s' "$out" | grep -qE '^(FAIL|WARN) gate\.'; then
    printf 'FAIL gate_self_test: shape %s: %s — a workflow that plainly runs the gate was rejected (exit %s)\n%s\n' \
      "$spelling_cases" "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  printf 'PASS gate_self_test: shape %s: %s — accepted\n' "$spelling_cases" "$label"
}

# extracted <label> must|must-not <needle> — assert on `workflow_run_lines`
# itself rather than on the verdict.
#
# The verdict is too coarse for the claim that matters most in this fix: that a
# `run:` whose value is NOT a command did not quietly become one. "This
# repository is still red" and "this comment did not turn into a command" are
# different claims, and only the second is the one a loosened anchor breaks
# quietly. Loosening the anchor to admit `run: ./bin/prime` also admits
# `run: # TODO: wire up bin/prime`, and that one is a green badge on a workflow
# that runs nothing.
extracted() {
  local label="$1" sense="$2" needle="$3"
  local repo got
  extractor_cases=$((extractor_cases + 1))
  repo="$(fresh_copy "extract-$extractor_cases")"
  write_case_workflow "$repo"
  got="$("$PY" - "$HARNESS" "$repo" <<'PY' 2>&1
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import gate_check  # noqa: PLC0415 - the module under test, imported by path

repo = Path(sys.argv[2])
print("\n".join(gate_check.workflow_run_lines(repo, ".github/workflows/ci.yml")))
PY
)"
  case "$sense" in
    must)
      if printf '%s' "$got" | grep -qF -- "$needle"; then
        printf 'PASS gate_self_test: extractor %s: %s — read %s out of it, as it should\n' \
          "$extractor_cases" "$label" "$needle"
        return
      fi
      ;;
    must-not)
      if printf '%s' "$got" | grep -qF -- "$needle"; then
        printf 'FAIL gate_self_test: extractor %s: %s — read %s out of a run: that does not call it.\n%s\n' \
          "$extractor_cases" "$label" "$needle" "$got" >&2
        failures=$((failures + 1))
        return
      fi
      printf 'PASS gate_self_test: extractor %s: %s — did not invent %s, as it should not\n' \
        "$extractor_cases" "$label" "$needle"
      return
      ;;
    *)
      printf 'FAIL gate_self_test: extractor %s: %s — bad sense %s\n' \
        "$extractor_cases" "$label" "$sense" >&2
      failures=$((failures + 1))
      return
      ;;
  esac
  printf 'FAIL gate_self_test: extractor %s: %s — did not read %s out of it.\n%s\n' \
    "$extractor_cases" "$label" "$needle" "$got" >&2
  failures=$((failures + 1))
}

# --------------------------------------------------------------------------
# the control. Without it, twenty-three reds prove nothing at all: a checker that
# refused everything would satisfy every expectation below.
# --------------------------------------------------------------------------
control="$(fresh_copy control)"
out="$("$PY" "$HARNESS/gate_check.py" --prove --log-dir "$control/.log" "$control" 2>&1)"
code=$?
if [ "$code" -ne 0 ]; then
  printf 'FAIL gate_self_test: the control — a repository whose declaration is true — did not come back green (exit %s)\n%s\n' \
    "$code" "$out" >&2
  failures=$((failures + 1))
else
  printf 'PASS gate_self_test: the control — a repository whose declaration is true — is green in both phases\n'
fi

# --------------------------------------------------------------------------
# the breakages
# --------------------------------------------------------------------------

breakages=$((breakages + 1))
one="$(fresh_copy no-declaration)"
rm -f "$one/gate.yml"
expect_red 'a repository that declares no gate at all' "$one" 'gate.declaration-missing'

breakages=$((breakages + 1))
two="$(fresh_copy command-missing)"
edit "$two/gate.yml" 'command: [bin/gate]' 'command: [bin/absent]'
expect_red 'a gate command naming a file this repository does not have' "$two" 'gate.command-missing'

breakages=$((breakages + 1))
two_a="$(fresh_copy entrypoint-missing)"
edit "$two_a/gate.yml" 'entrypoint: bin/gate' 'entrypoint: bin/absent'
expect_red 'a gate entrypoint this repository does not have, while the command still does' \
  "$two_a" 'gate.entrypoint-missing'

breakages=$((breakages + 1))
three="$(fresh_copy entrypoint-not-executable)"
chmod -x "$three/bin/gate"
expect_red 'a gate nobody is allowed to execute' "$three" 'gate.entrypoint-not-executable'

breakages=$((breakages + 1))
four="$(fresh_copy task-missing)"
edit "$four/gate.yml" 'miseTask: prime' 'miseTask: verify'
expect_red 'a mise task that is not in the mise config' "$four" 'gate.task-missing'

breakages=$((breakages + 1))
five="$(fresh_copy task-unresolvable)"
edit "$five/mise.toml" 'run = "bin/gate"' 'run = "bin/something-else"'
expect_red 'a mise task that resolves to a different file than the declaration names' \
  "$five" 'gate.task-unresolvable'

breakages=$((breakages + 1))
six="$(fresh_copy task-config-missing)"
rm -f "$six/mise.toml"
expect_red 'a mise task named in a repository that has no mise config' \
  "$six" 'gate.task-config-missing'

# ------------------------------------------------------------------ 7 of 25
# The one that is not string matching. Everything above is a checker reading
# two files and disagreeing; this is a declaration that is entirely TRUE — the
# command exists, it is runnable, the task is in the config, CI calls it — about
# a gate that exits 0 and does nothing at all. Nothing about the declaration is
# wrong. The only thing that catches it is asking the gate to say what it did.
breakages=$((breakages + 1))
seven="$(fresh_copy false-green)"
write "$seven/bin/gate" <<'SH'
#!/usr/bin/env bash
# A well-formed gate that runs nothing and says nothing, and exits 0.
# This is the false green, reproduced deliberately: every string in the
# declaration about this repository is true, and the repository is ungated.
exit 0
SH
chmod +x "$seven/bin/gate"
expect_red 'a declaration that is entirely true about a gate that exited 0 without running anything' \
  "$seven" 'gate.proof-missing'

breakages=$((breakages + 1))
eight="$(fresh_copy floor)"
edit "$eight/gate.yml" 'minimum: 3' 'minimum: 40'
expect_red 'a gate that proves one test where the declaration promised forty' "$eight" 'gate.floor'

breakages=$((breakages + 1))
nine="$(fresh_copy nonzero)"
write "$nine/bin/gate" <<'SH'
#!/usr/bin/env bash
# Runs, proves itself, and fails. The proof is there and the gate is still red,
# which is the other half of the contract: `gate.proof-missing` on its own would
# accept a gate that never printed anything AND exited zero.
set -euo pipefail
echo "2/3 passed"
echo "FAIL test_the_third_thing" >&2
exit 1
SH
chmod +x "$nine/bin/gate"
expect_red 'a gate that ran the suite, printed its proof, and failed' "$nine" 'gate.nonzero'

breakages=$((breakages + 1))
ten="$(fresh_copy ci-disagrees)"
edit "$ten/.github/workflows/ci.yml" 'bin/gate' 'echo "nothing here"'
expect_red 'a CI workflow that never runs the gate' "$ten" 'gate.ci-disagrees'

breakages=$((breakages + 1))
eleven="$(fresh_copy proof-uncompilable)"
edit "$eleven/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^([0-9]+/[0-9]+ passed\$'"
# Caught at the SHAPE layer, not the proving layer, and that is the better
# answer: a pattern that does not compile is refused by the schema check
# without the gate being run at all. The alternative — noticing it only after
# spending the gate's whole runtime — is what this packet's first false green
# looked like.
expect_red 'a proof whose pattern does not compile, which would otherwise read as "no proof required"' \
  "$eleven" 'gate.schema'

breakages=$((breakages + 1))
twelve="$(fresh_copy requirement-empty)"
edit "$twelve/gate.yml" '  selfContained: true' '  selfContained: false'
expect_red 'a gate that says it is not self-contained and names no way to satisfy what it needs' \
  "$twelve" 'gate.schema'

breakages=$((breakages + 1))
thirteen="$(fresh_copy requirement-path-missing)"
edit "$thirteen/gate.yml" '  selfContained: true
  requirements: []' '  selfContained: false
  requirements:
    - kind: toolchain
      name: a venv builder that this repository does not carry
      satisfy:
        command: [bin/absent-setup]'
expect_red 'an external requirement satisfied by a file that is not in this repository' \
  "$thirteen" 'gate.requirement-path-missing'

breakages=$((breakages + 1))
fourteen="$(fresh_copy declaration-unreadable)"
edit "$fourteen/gate.yml" 'name: gate-fixture' 'name: &anchor gate-fixture'
expect_red 'a declaration using a YAML construct core'"'"'s reader refuses' \
  "$fourteen" 'gate.declaration-unreadable'

breakages=$((breakages + 1))
fifteen="$(fresh_copy command-unknown)"
edit "$fifteen/gate.yml" 'command: [bin/gate]' 'command: [gate-check-not-on-any-path]'
expect_warn 'a gate command that is a bare name this machine does not have' \
  "$fifteen" 'gate.command-unknown'

breakages=$((breakages + 1))
sixteen="$(fresh_copy task-unreadable)"
edit "$sixteen/mise.toml" 'run = "bin/gate"' 'run = "bin/gate | tee /dev/null"'
expect_warn 'a mise task whose run string is a pipeline, so only a shell could say what it runs' \
  "$sixteen" 'gate.task-unreadable'

breakages=$((breakages + 1))
seventeen="$(fresh_copy task-undeclared)"
edit "$seventeen/gate.yml" '  miseTask: prime
' ''
expect_warn 'a repository with mise tasks and a declaration that names none of them' \
  "$seventeen" 'gate.task-undeclared'

breakages=$((breakages + 1))
eighteen="$(fresh_copy ci-missing)"
edit "$eighteen/gate.yml" 'workflow: .github/workflows/ci.yml' 'workflow: .github/workflows/nope.yml'
expect_red 'a declaration naming a CI workflow that is not in this repository' \
  "$eighteen" 'gate.ci-missing'

breakages=$((breakages + 1))
nineteen="$(fresh_copy ci-undeclared)"
edit "$nineteen/gate.yml" 'ci:
  workflow: .github/workflows/ci.yml
  invokes: [bin/gate]
' ''
expect_warn 'a declaration that says nothing about CI' "$nineteen" 'gate.ci-undeclared'

breakages=$((breakages + 1))
twenty="$(fresh_copy requirement-unproven)"
edit "$twenty/gate.yml" '  selfContained: true
  requirements: []' '  selfContained: false
  requirements:
    - kind: toolchain
      name: a command on PATH that this checker deliberately did not run
      satisfy:
        command: [mise, install]'
expect_warn --prove 'an external requirement nobody ran, which is reported and never acted on' \
  "$twenty" 'gate.requirement-unproven'

breakages=$((breakages + 1))
twentyone="$(fresh_copy timeout)"
edit "$twentyone/gate.yml" 'timeoutSeconds: 60' 'timeoutSeconds: 1'
# A PURE-BASH busy wait, and that is a change from the python one-liner this
# case used to carry. The reason is the machine this packet is about: a fixture
# gate that shells out to a bare `python3` inherits whatever `python3` the host
# has, so on the developer whose `python3` is 3.9.6 the gate failed instantly for
# a reason that has nothing to do with timing — the `timeout` case reported
# `gate.nonzero` where it meant to report `gate.timeout`, and the case went red
# on a machine where nothing was wrong. The dependency was invisible until the
# interpreter search stopped refusing that same machine, and then it was not
# this case's business at all: a case about the checker enforcing a budget has
# no reason to care which python the gate happens to use. `SECONDS` and
# arithmetic are bash builtins, so this needs nothing on PATH but bash.
write "$twentyone/bin/gate" <<'SH'
#!/usr/bin/env bash
# A gate that provably outlives its one-second budget, and WITHOUT a sleep.
#
# `sleep 5` would be a guess about timing wearing a test's clothes: it makes the
# result depend on the scheduler rather than on the checker. This is a
# three-second CPU-bound wait, so the only way it can finish inside a one-second
# budget is for the clock to have lied. It also ends by itself, so a checker
# that failed to stop it makes this script slow rather than hung.
set -euo pipefail
end=$(( SECONDS + 3 ))
while [ "$SECONDS" -lt "$end" ]; do
  :
done
echo "3/3 passed"
SH
chmod +x "$twentyone/bin/gate"
expect_red 'a gate that outlived the budget its own declaration gave it' "$twentyone" 'gate.timeout'

# ------------------------------------------------------------------ 23 of 25
# The other half of `gate.proof-invalid`, and the one that only the PROVING
# phase can see: the pattern compiles, the declaration is well formed, and the
# floor it promises is read from a capture group that is not there. A checker
# that silently treated that as "no floor" would accept a suite of any size,
# which is the same false green with one more step around it.
breakages=$((breakages + 1))
twentytwo="$(fresh_copy proof-unmeasurable)"
edit "$twentytwo/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^[0-9]+/[0-9]+ passed\$'"
expect_red 'a proof with a floor and no capture group to read the floor from' \
  "$twentytwo" 'gate.proof-invalid'

# ------------------------------------------------------------------ shapes
# THE SPELLINGS THIS FLEET ACTUALLY WRITES. Read before the fix that closes them.
#
# `grep` over the twelve `.github/workflows/` trees this standard was written
# for — core, kit, identity, billing, courier, cafaye-rb, docs, gateway, darkroom,
# muse, parlor — finds 139 `run:` keys:
#
#     101  run: |                 block scalar
#      38  run: <one-line command>   <-- the 38 the checker could not see
#       0  - run: ...             sequence-item form
#
# and two of those 38 are the gate itself, written the shortest legal way:
#
#     gateway/.github/workflows/ci.yml:65    run: bin/prime
#     parlor/.github/workflows/ci.yml:81     run: ./bin/prime
#
# Both are true workflows, and on the checker as it stood both were
# `FAIL gate.ci-disagrees: never runs bin/prime`. That is not a hypothetical; it
# is the bug, reproduced from this fleet's own tree rather than from a thought
# experiment, and `cafaye-rb` hit it independently and left a workaround behind
# (a block scalar, with a comment explaining why) that is still in its tree.
#
# Why twenty-three breakages missed it, and this is the sentence to remember:
# every one of them broke something and asserted a RED, and the conforming
# fixture they all start from spells its gate `run: |`. The fixture taught the
# checker the one shape that worked. Red cases only ever prove the checker fails
# on inputs somebody already disliked.

accepts 'the block scalar, 101 of 139 keys in this fleet, gate on the second body line' <<'YAML'
        run: |
          set -euo pipefail
          bin/gate
YAML

accepts 'a one-line run with no ./ — gateway/ci.yml:65 spells the gate exactly this way' <<'YAML'
        run: bin/gate
YAML

accepts 'a one-line run with a leading ./ — parlor/ci.yml:81, and cafaye-rb before it worked around this' <<'YAML'
        run: ./bin/gate
YAML

accepts 'a one-line run carrying arguments and a quoted variable — kit:349, darkroom:172' <<'YAML'
        run: bin/gate --fail-under "$COVERAGE_FAIL_UNDER"
YAML

accepts 'a one-line run with a trailing comment, next to a comment that is not one — core:186' <<'YAML'
        run: bin/gate 2>&1 | tee "$RUNNER_TEMP/gate.log"  # the gate
YAML

# Zero occurrences in this fleet today, and here anyway. `- run:` is the same
# key in the same position; a pattern that cannot see it fails silently in
# exactly the way `run: <command>` failed, and a shape absent from today's tree
# is not a shape that should be invisible. Decided in RUN_KEY's comment.
accepts 'the sequence-item spelling, - run:, which no workflow here writes yet' <<'YAML'
        - run: bin/gate
YAML

# `run:` with its value on the following lines. Valid YAML — a plain scalar may
# continue on more-indented lines — and the checker could not read it either: it
# matched the bare key, then reset its indent state in the same breath.
accepts 'a bare run: key whose value is on the lines below it' <<'YAML'
        run:
          bin/gate
YAML

# The two repositories in this fleet that write the gate as a one-liner BOTH
# pair it with a job that calls kit's reusable workflow — gateway:38/65 and
# parlor:45/81. Read whole, because a `uses:` line and a `run:` line are two
# different ways of saying "CI runs something" and the check has to see the
# second without being confused by the first. The `with:`/`versions:` blocks are
# verbatim from gateway; they are here so this case is a real file, not a shape.
accepts_whole 'gateway/ci.yml: a kit reusable-workflow job, and the gate as a one-liner' <<'YAML'
name: ci

on: [push]

jobs:
  ci:
    name: ci (kit)
    uses: cafaye/kit/.github/workflows/ci.reusable.yml@master
    with:
      language: bun
      working-dir: .
      versions: '{"bun":"1.3.12"}'

  prime:
    name: bin/prime
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: "1.3.12"
      - name: bin/prime
        run: bin/gate
      - name: bun.lock is untouched
        run: |
          git diff --exit-code -- bun.lock \
            || { echo "bin/prime moved bun.lock — the gate is no longer frozen"; exit 1; }
YAML

accepts_whole 'parlor/ci.yml: the same shape, the gate spelled with a leading ./' <<'YAML'
name: ci

on: [push]

jobs:
  ci:
    name: ci (kit, node)
    uses: cafaye/kit/.github/workflows/ci.reusable.yml@master
    with:
      language: node
      working-dir: .
      versions: '{"node":"22.22.2"}'

  prime:
    name: bin/prime
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version-file: package.json
      - name: the gate a developer runs
        run: ./bin/gate
      - name: the gate leaves package-lock.json alone
        run: git diff --exit-code -- package-lock.json
YAML

# MULTIPLE INVOCATIONS, and this is core's OWN workflow: ci.yml:186 runs
# `bin/prime` and ci.yml:338 runs `bin/prime --pytest`, two entry points to one
# suite, asserted to agree. `invokes: [bin/gate]` names one of them.
#
# The policy is a PASS and the reasoning is in docs/gate.md: `invokes` is a claim
# that the gate is reachable from CI, not a count. Two invocations is the
# normal case for a repository that checks its two entry points against each
# other, and a checker that read multiplicity as drift would fire on core's own
# workflow — which is the same false red this whole section is about, wearing a
# different hat.
accepts_whole 'two invocations of one gate in one workflow — core/ci.yml:186 and :338' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        shell: bash
        run: |
          set -euo pipefail
          bin/gate 2>&1 | tee "$RUNNER_TEMP/gate.log"
      - name: the pytest entry point, and that it agrees with the script one
        shell: bash
        run: |
          set -euo pipefail
          bin/gate --pytest 2>&1 | tee "$RUNNER_TEMP/pytest.log"
YAML


# also admits `run: # TODO: wire up bin/prime`, and THAT is a green badge on a
# workflow that runs nothing at all — the false green, reached from the false
# red. Asserted against the extractor, because the verdict and the extractor are
# different claims and only the second is the one a looser pattern breaks
# quietly. PyYAML on this input returns run=None: the value is genuinely absent.
extracted 'a run: whose whole value is a comment' must-not 'bin/gate' <<'YAML'
        run: # TODO: wire up bin/gate
YAML

extracted 'a run: whose whole value is a comment, at a different indent' must-not 'bin/gate' <<'YAML'
        run: #bin/gate is what belongs here
YAML

# The pair of guards above are only load-bearing if the happy path still reads a
# command, including one that merely STARTS like a comment. `run: #!/bin/sh`-style
# trickery is not the concern; a command that begins with `#` is not a command,
# and a command that begins with anything else is one, comment or not.
extracted 'a one-line run whose command is real, next to a comment about it' must 'bin/gate' <<'YAML'
        run: bin/gate --verbose  # add --verbose once the suite is quieter
YAML

extracted 'the block scalar, read through the same extractor' must 'bin/gate' <<'YAML'
        run: |
          set -euo pipefail
          bin/gate
YAML

# --------------------------------------------------------------------------
# THE POLICY for the two cases nobody had written down. docs/gate.md has the
# prose; these are the teeth. Both are the same defect as the false red above —
# a checker deciding, silently, what a workflow means — and a policy that is
# only prose decays the first time nobody remembers writing it.
#
# 1. MULTIPLE INVOCATIONS: a PASS. `invokes` is a claim that the gate is
#    REACHABLE from CI, not a count of how often. core's own workflow runs it
#    twice (ci.yml:186 the script entry point, :338 the pytest one, asserted to
#    agree), so a checker that read multiplicity as drift would fire on the
#    repository that wrote the rule. Pinned by shape 10 above.
#
# 2. INDIRECT INVOCATION, in two halves that must NOT get the same answer:
#      a. through the task the DECLARATION names — `mise run prime`, with
#         mise.toml's [tasks.prime] resolving to the declared entrypoint — is a
#         PASS. The checker already proves that resolution for
#         `gate.task-unresolvable`; here it uses the same proof to read a second
#         spelling of the same command. Nothing is taken on trust.
#      b. through a wrapper nobody declared — `make gate`, `./scripts/ci.sh` —
#         is a WARNING, and the leak is named in the message and in
#         docs/gate.md: this checker reads no Makefile and no shell script, so it
#         cannot tell a wrapper from a wrapper that was emptied. Failing there
#         would be the false red this packet exists to kill; staying silent
#         would be the false green. It says what it does not know and exits 0.
#    And the case that keeps (b) honest: a workflow whose only task invocation
#    is unrelated still warns rather than fails. That is the price, stated here
#    rather than hidden, and the warning text tells the reader how to settle it.
# --------------------------------------------------------------------------

accepts_whole 'indirect invocation through the task the declaration names — mise run prime' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        run: mise run prime
YAML

accepts_whole 'the same through mise x --, and the gate named directly as well' <<'YAML'
name: ci

on: [push]

jobs:
  gate:
    name: gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: the gate a developer runs
        run: mise x -- bin/gate
YAML

breakages=$((breakages + 1))
twentythree="$(fresh_copy ci-wrapper-undeclared)"
edit "$twentythree/.github/workflows/ci.yml" 'bin/gate' 'make gate'
expect_warn 'a CI workflow that reaches the gate through a make target this checker cannot read' \
  "$twentythree" 'gate.ci-unproven'

breakages=$((breakages + 1))
twentyfour="$(fresh_copy ci-wrapper-unrelated-task)"
edit "$twentyfour/.github/workflows/ci.yml" 'bin/gate' 'make lint'
expect_warn 'a CI workflow whose only task invocation is unrelated, where this checker cannot tell a wrapper from a wrapper that was emptied' \
  "$twentyfour" 'gate.ci-unproven'

# --------------------------------------------------------------------------
# the hygiene case. Not a finding id, because it is not a finding: it is the
# property that no finding may ever be one.
# --------------------------------------------------------------------------
leak="$(fresh_copy secret-output)"
write "$leak/bin/gate" <<'SH'
#!/usr/bin/env bash
# A gate that leaks a value out of its own environment into its output, the way
# a failing assertion that formats a connection string does. No off-the-shelf
# tool detects this: 0 of 268 Semgrep rules intersect CWE-532, gosec has no
# ast.CallExpr case, Bandit is ast.Constant-only. So the checker's own report
# must not carry the value, and that is a test rather than a promise.
set -uo pipefail
echo "could not reach ${DATABASE_URL:-unset}"
echo "2/3 passed"
exit 1
SH
chmod +x "$leak/bin/gate"
expect_no_leak 'the gate that leaked at runtime' "$leak" \
  'postgres://gate:should-never-be-printed@localhost:5432/gate'

# --------------------------------------------------------------------------
# the colour cases. These are not breakages, because a breakage is a repository
# that is WRONG; these are repositories that are entirely correct — a gate that
# really ran, printing the way a colourising runner prints — and they say what
# has to be true of a pattern written against the bytes a terminal shows.
# --------------------------------------------------------------------------

# (1) A proof that matches ONLY after the escapes are stripped. The bytes are
# the ones MD17 quotes from a real vitest log, and the pattern is the one
# core-10-parlor declared, which is correct for the line a human sees. This
# repository went RED on it: the gate had just proved, in the same log, that it
# ran 377 tests.
colour="$(fresh_copy colour-proof)"
edit "$colour/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" \
  "match: '^[ ]*Tests[ ]+([0-9]+) passed'"
edit "$colour/gate.yml" 'minimum: 3' 'minimum: 377'
write "$colour/bin/gate" <<'SH'
#!/usr/bin/env bash
# A colourising test runner, verbatim from the log the ruling was made against.
# `printf '%b'` because the escapes are the point and a shell heredoc would
# otherwise need them spelled as octal in a way that hides what is being tested.
set -euo pipefail
printf '%b\n' '\033[2m      Tests \033[22m \033[1m\033[32m377 passed\033[39m\033[22m \033[90m(377)\033[39m'
SH
chmod +x "$colour/bin/gate"
expect_green 'a colourising gate whose proof matches once the escapes are stripped' "$colour"

# (2) A proof that must STILL go red. The stripper removes formatting, and the
# temptation in any stripper is to remove "noise" more broadly than that — which
# would turn an absent proof into a present one. This gate prints colour on every
# line and never prints the declared proof at all.
swallow="$(fresh_copy colour-must-stay-red)"
write "$swallow/bin/gate" <<'SH'
#!/usr/bin/env bash
# Colour on every line, and the declared proof genuinely absent. A stripper that
# ate anything it did not understand would call this a green.
set -euo pipefail
printf '%b\n' '\033[1;32m2\033[0m/4 \033[33msomething else entirely\033[0m'
exit 0
SH
chmod +x "$swallow/bin/gate"
expect_colour_red 'a proof that is genuinely absent from a gate that prints colour everywhere' \
  "$swallow" 'gate.proof-missing'

# (3) A floor that must STILL fail when the count is below it. Stripping must
# change WHERE a pattern is applied and never WHETHER a real ratchet breach is
# reported. 2/4 against a floor of 3 is a suite that lost tests, with colour.
floorcolour="$(fresh_copy colour-floor)"
edit "$floorcolour/gate.yml" 'minimum: 3' 'minimum: 4'
write "$floorcolour/bin/gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%b\n' '\033[32m2\033[0m/4 \033[90mpassed\033[0m'
SH
chmod +x "$floorcolour/bin/gate"
expect_colour_red 'a suite below its floor, printed through a colourising runner' \
  "$floorcolour" 'gate.floor'

# (4) An OSC sequence, which is NOT colour and is not what the rule was written
# about. `vitest` sets the terminal title; some tools emit hyperlinks (OSC 8).
# A stripper written only for `ESC [ … m` leaves these in place, so the line
# still begins with an escape and the proof still misses — which is why this is
# a case and not a footnote. `escape` is written by printf so the heredoc cannot
# be misread as containing a real control character.
osc="$(fresh_copy colour-osc)"
edit "$osc/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^Tests[ ]+([0-9]+) passed'"
write "$osc/bin/gate" <<'SH'
#!/usr/bin/env bash
# OSC 0 (window title, BEL-terminated) then OSC 8 (hyperlink, ST-terminated),
# then the proof. The first `escape` is BEL, the second is ESC backslash.
set -euo pipefail
printf '\033]0;vitest run\007\033]8;;https://example.dev/tests\033\\Tests  377 passed\033]8;;\033\\'
printf '%s\n' ''
SH
chmod +x "$osc/bin/gate"
edit "$osc/gate.yml" 'minimum: 3' 'minimum: 377'
expect_green 'a proof on a line that also carries OSC title and hyperlink sequences' "$osc"

# (5) An UNTERMINATED OSC. This one is a liability rather than a case a tool
# emits: a stripper that consumed an unterminated sequence to end-of-input would
# delete every line after it, the proof included, and report a green over a gate
# that printed no proof. The unterminated bytes must survive, so the proof below
# is the only one on the line and is found.
unterminated="$(fresh_copy colour-unterminated)"
edit "$unterminated/gate.yml" "match: '^([0-9]+)/[0-9]+ passed\$'" "match: '^Tests[ ]+([0-9]+) passed'"
write "$unterminated/bin/gate" <<'SH'
#!/usr/bin/env bash
# An OSC that is opened and never terminated, on a line of its own. A stripper
# that ran to end-of-input would eat this line AND the proof line below it.
set -euo pipefail
printf '%b\n' 'INFO starting'
printf '\033]0;never-terminated'
printf '%s\n' ''
printf '%b\n' 'Tests  377 passed'
SH
chmod +x "$unterminated/bin/gate"
edit "$unterminated/gate.yml" 'minimum: 3' 'minimum: 377'
expect_green 'a proof that follows an unterminated OSC on the previous line' "$unterminated"

# --------------------------------------------------------------------------
# THE INTERPRETER SEARCH. The only three cases here about this script rather
# than about the checker, and they are here at the end for that reason:
# everything above needs an interpreter before it can start, so these are the
# last claims available to a run that found one.
#
# The defect, in the shape two of these reproduce. The candidate list is
#
#     python3  python3.13  python3.12  python3.11  python
#
# and the loop broke out of it on the first name that RESOLVED, then checked the
# version afterwards and gave up if that one was too old. A candidate that
# resolves is not a candidate that qualifies. On a machine whose `python3` is
# 3.9.6 the search therefore took 3.9.6, stopped, and printed "no python >= 3.11
# found" while 3.13 and 3.14 sat on the same PATH unused — a false negative in
# the project's own proof-of-failure, and one that is indistinguishable from a
# machine that genuinely has nothing. That is why it survived: the only way to
# see it is to be the developer whose `python3` is 3.9.6, and `bin/prime` and CI
# both export CAFAYE_GATE_PYTHON or run on setup-python, so the escaped-into-
# silence was complete.
#
# All three live in harness/tests/fixtures/interpreter-path, so none of them
# depends on the machine running it — which is the whole reason the bug survived
# to be reported, restated as a fixture. The third pins the same interpreter the
# other two take, because the trap in fixing this is to make the search so eager
# that a deliberate override stops meaning anything.
# --------------------------------------------------------------------------

expect_python_search walks-on 'a PATH whose FIRST candidate is too old and whose SECOND qualifies — it walked on and took the qualifying one' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-first/bin" \
  "$(printf 'python3\npython3.13')"

expect_python_search exhausted 'a PATH with no qualifying python at all — it walked all five candidates and exited 1 saying so' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-only/bin" \
  "$(printf 'python3\npython3.13\npython3.12\npython3.11\npython')"

expect_python_search override 'a CAFAYE_GATE_PYTHON that resolves and is too old — it is an error, not a reason to go looking for another one' \
  "$HARNESS/tests/fixtures/interpreter-path/stale-first/bin" \
  "$(printf 'python3')"

# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The counts, and why every row is counted where the case RUNS.
#
# `breakages` does not appear here. It is the case NUMBER, incremented by hand
# before each red-proof case so a printed line can be referred to by the same
# number the comments use, and it counts the warning cases too — so printing it
# as "breakages that went RED" claimed seven reds that did not happen, on the one
# number a reader of this script has most reason to trust. core-14 fixed that by
# counting each category inside the function that runs the case, and by giving
# the two colour categories and the leak case rows of their own: a case kind
# with no number in this block is a case kind nobody can tell stopped running.
#
# The SKIPPED row is a literal 0, and it is honest for two reasons that are
# asserted rather than hoped for. Nothing in this script is conditional — every
# case runs unconditionally, top to bottom, with no `if` around it — and the two
# preconditions that can fail (an interpreter, the fixture) exit non-zero before
# any case runs, so there is no path that reaches this footer having skipped
# anything. `tests/test_specs.py` reads the call sites out of this file and
# requires the counts printed here to be exactly their number, which is what
# makes the 0 a measurement rather than a claim. bin/prime reads this row too
# and fails the gate on a non-zero, because the first time a case *can* be
# skipped the answer has to be a red build and not a smaller number.
#
# THE INTERPRETER-SEARCH ROW IS NOT IN THAT LIST YET, and it is printed and
# counted here anyway rather than left out. `test_the_red_proof_counts_every_case
# _it_runs` holds a fixed list of the eight case kinds it can read, and
# `expect_python_search` is a ninth, so that test cannot see these three calls:
# it asserts the row is incremented exactly once inside the function that runs
# the case, and it asserts nothing at all about this one. That is a gap in the
# inventory rather than a reason to print no row — the row is what a reader
# counts, and `bin/prime`'s `logged`/`claimed` comparison is `>=`, so the extra
# PASS lines make that check stricter rather than looser. Adding the ninth kind
# to that test's `categories` list is the follow-up, and it belongs with whoever
# next owns tests/test_specs.py; until then this row is the only thing standing
# between a search case that stopped running and a reader who would never know.
printf '\n'
printf 'gate_self_test — counts, reported separately so a green cannot hide one:\n'
printf '  breakages that went RED and named their finding : %s\n' "$red_cases"
printf '  warning cases that stayed GREEN                 : %s\n' "$warn_cases"
printf '  green cases that matched a colour-bearing gate  : %s\n' "$green_cases"
printf '  colour reds that still went red                 : %s\n' "$colour_cases"
printf '  real-workflow shapes that were ACCEPTED         : %s\n' "$spelling_cases"
printf '  extractor assertions (must / must-not)          : %s\n' "$extractor_cases"
printf '  the case that kept a secret out of the report   : %s\n' "$leak_cases"
printf '  interpreter searches that were MEASURED         : %s\n' "$search_cases"
printf '  the control (a true declaration, unbroken)      : 1\n'
printf '  SKIPPED                                         : 0\n'
printf '  (nothing here is conditional on the machine: no case skips, and a case\n'
printf '   that could not run would exit non-zero above rather than report a skip.)\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: gate_self_test — %s of %s breakages, %s warning cases, %s spellings accepted, %s colour-green cases, %s extractor assertions and %s colour reds the gate checker did not get right.\n' \
    "$failures" "$red_cases" "$warn_cases" "$spelling_cases" "$green_cases" "$extractor_cases" "$colour_cases"
  exit 1
fi
printf 'PASS: gate_self_test — %s breakages went red naming their finding, %s warning cases stayed green,\n' \
  "$red_cases" "$warn_cases"
printf '      %s real-workflow spellings were ACCEPTED, %s extractor assertions held,\n' \
  "$spelling_cases" "$extractor_cases"
printf '      %s green cases matched a colour-bearing gate, %s colour reds still went red, %s leak case held,\n' \
  "$green_cases" "$colour_cases" "$leak_cases"
printf '      %s interpreter searches were measured, the control is green, 0 skipped,\n' "$search_cases"
printf '      and the report carried no secret.\n'

#!/usr/bin/env bash
#
# tenancy_self_test.sh — the tenancy checker's proof that it is able to fail.
#
#   bash harness/tests/tenancy_self_test.sh
#
# WHAT THIS IS FOR
#
# A checker that has only ever said "yes" is a report, not a gate. This script
# takes ONE conforming fixture — a small service that declares its account
# boundary and tells the truth about all of it — copies it, breaks exactly one
# thing in each copy, and asserts the checker goes red each time. Every breakage
# names the finding it expects, so a red proves that *the check written for that
# defect* is still load-bearing, which is a different claim from "something went
# red" and the one that decays silently.
#
# The shape is harness/tests/gate_self_test.sh's, and it is the same shape for
# the same reason: a control on the unbroken fixture first (without it every red
# below proves nothing — a checker that refused everything would satisfy all of
# them), a fresh throwaway copy per case so one must never mask the next, and a
# non-zero exit if any breakage stayed green. Nothing in the committed tree is a
# deliberately broken service: the breakages are edits applied here, so a
# reviewer reads what is being broken rather than having to reconstruct it.
#
# THE SEVEN THE BRIEF NAMES, AND THE FINDING EACH ONE MUST NAME
#
#   a missing WHERE on a read          tenancy.scope-lost   on asset-fetch
#   a missing bind parameter            tenancy.bind-missing on asset-checksum-bind
#   an unscoped list                    tenancy.scope-lost   on asset-list
#   an unscoped update                  tenancy.entry-absent on asset-settle
#   an unscoped delete                  tenancy.entry-absent on asset-delete
#   IDOR on fetch-by-id                 tenancy.entry-absent on asset-variant-fetch
#   a negative weakened to *forbidden*  tenancy.denial-missing on asset-fetch
#
# `expect_red` takes a FOURTH argument — a second needle that must appear in the
# output — because six of these seven resolve to one of two findings and "went
# red" alone would not distinguish a read that lost its predicate from a delete
# that lost its predicate. The finding id says which CHECK fired; the needle says
# which ENTRY POINT it fired about, which is the claim actually being made.
#
# AND THE ONE THAT IS NOT A BREAKAGE
#
# The last section is the honesty case, and it is a WARNING that must stay
# green. `harness/tests/fixtures/tenancy/unreadable-language/` is a Go service
# whose account scoping is real and whose syntax this checker cannot read. The
# required verdict is: two warnings naming the file and line, exit 0, and NOT a
# single "no account-scoped entry points found". Counting account-scoped routes
# by pattern gave 96 for guard and 0 for darkroom, and the 0 was the checker's
# syntax rather than darkroom's — a grep that reports "this service has none"
# is worse than no grep, because it reads like an answer. `expect_green` with an
# extra assertion on the warning text is what keeps that from regressing into
# silence.
#
# WHAT IT IS NOT
#
# Not exhaustive mutation testing, and it does not claim to catch every defect.
# It proves forty-one specific breakages across six fixtures, four warning
# cases, seven green cases, and the tri-state promise those warnings make. It does
# NOT prove the
# service's tests pass — this checker reads the negative assertion's source and
# never runs it, which harness/tenancy_findings.json says in its `notEnforced`
# list rather than leaving it to be discovered.
#
# THIRTY-NINE breakages, and every one of the twenty-six failure-severity
# findings this checker can report has a breakage naming it — which is asserted
# from core's suite by `test_every_tenancy_finding_is_proved_able_to_go_red`, so
# a finding added without a breakage is red rather than shipped untested. The
# four that fire before a boundary is even declared are the ones most likely to
# be needed first: every repository in this fleet produces `declaration-missing`
# today. The seven that are not about a finding at all — the substrate's claim
# that it is described and not enforced, its spelling, its identity, the
# credential call's control with its own counted baseline, and the same five
# policies written by hand — are below, under the substrate and the credential
# call, and they are the reason the count is not equal to the number of findings.
#
# The `# (NN)` labels below are a reading aid and NOT an index: they were written
# as cases were added near each other, so there are two `(13)`s, the database
# half's cases are interleaved with the rest, and the warning cases at the bottom
# carry numbers that no longer sit after the breakages. The number to trust is
# the one the script PRINTS in the counts block at the end, because that one is
# produced by the counter rather than by a human counting. This paragraph used to
# assert a breakdown of that number; it stopped, because the breakdown had
# drifted from the list it described and nobody could tell which was wrong.
#
# The database half — every `tenancy.rls-*` finding, the positive control, and
# (24b) — is ALSO driven in-process by
# `test_every_behavioural_check_the_checker_has_is_proved_load_bearing` in
# `tests/test_specs.py`, which is the only one of the three proofs `bin/prime`
# runs. (24b) is the case that is not a finding of its own: it proves the arm of
# `tenancy.rls-permissive` saying a policy's written roles and its declared roles
# must be the same roles, which is why thirty-nine breakages prove twenty-six
# findings.
#
# It is deliberately not inside `bin/prime`. A self-test that ran in every gate
# invocation would be a second gate that can disagree with the first, which is
# why core's CI runs it as a step of its own — and why this one is a NEW file
# rather than a section of the gate checker's self-test: the two checkers have
# different fixtures, different findings and different failure modes, and one
# script asserting both would make a red in one of them indistinguishable from a
# red in the other.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURE="$HARNESS/tests/fixtures/tenancy/conforming"
SUBSTRATE_FIXTURE="$HARNESS/tests/fixtures/tenancy/substrate"
CREDENTIAL_FIXTURE="$HARNESS/tests/fixtures/tenancy/credential"
ZERO_FIXTURE="$HARNESS/tests/fixtures/tenancy/honest-zero"
KEY_CLAIM_FIXTURE="$HARNESS/tests/fixtures/tenancy/honest-zero-token-claim"
BLIND_FIXTURE="$HARNESS/tests/fixtures/tenancy/unreadable-language"

PY="${CAFAYE_TENANCY_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "tenancy_self_test: no python >= 3.9 found; set CAFAYE_TENANCY_PYTHON" >&2
  exit 1
fi

for required in "$FIXTURE" "$SUBSTRATE_FIXTURE" "$CREDENTIAL_FIXTURE" \
                "$ZERO_FIXTURE" "$KEY_CLAIM_FIXTURE" "$BLIND_FIXTURE"; do
  if [ ! -d "$required" ]; then
    echo "tenancy_self_test: a fixture is missing at $required" >&2
    exit 1
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cafaye-tenancy-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
breakages=0
warn_cases=0
green_cases=0
copy_name=""

# A fresh copy per case. The fixture carries its own migrations/, src/, tests/
# and tenancy.yml, so a copy of it is a copy of a repository; nothing outside the
# fixture is read, and the worktree is not touched.
fresh_copy() {
  copy_name="$1"
  local fixture="$2"
  local dst="$WORK/$copy_name"
  rm -rf "$dst"
  cp -R "$fixture" "$dst"
  printf '%s' "$dst"
}

# edit <file> <old> <new> — a textual breakage that FAILS LOUDLY if the fixture has
# moved past it. A self-test that silently stops breaking anything is worse than
# no self-test, so an unmatched edit is an error here rather than a pass. That is
# the reason the fixture's declared line numbers are pinned: if someone adds a
# line to 0001_assets.sql, every breakage below stops applying and this exits
# non-zero rather than reporting sixteen greens.
#
# And it fails loud on an AMBIGUOUS match too, which is not a hypothetical. The
# honest-zero fixture explains itself in a comment that contains the string
# `accountScoped: false`, and `replace(..., 1)` took the comment and left the
# key alone — so the breakage for `tenancy.enumeration-empty` went green while
# breaking a `#`, and the script reported a pass for a check it had never
# exercised. A tool that edits text must say when the text it found is not
# unambiguously the text it was pointed at; `count(old) > 1` is the whole test,
# and it is the same rule the gate checker's proof matching has after MD17.
edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
found = body.count(old)
if found == 0:
    sys.exit(f"tenancy_self_test: breakage no longer applies to {path}: {old!r} not found")
if found > 1:
    sys.exit(
        f"tenancy_self_test: {path} contains {old!r} {found} times, so a replace of the "
        "first one may have edited a comment or a different statement. Make the anchor "
        "unambiguous rather than hoping the first match is the right one."
    )
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
}

# expect_red <label> <repo> <finding-id> [needle] — the fixture must go red, the
# exit code must be 1, the finding must be NAMED, and — when a needle is given —
# the message must name the entry point too.
expect_red() {
  local label="$1" repo="$2" expect="$3" needle="${4:-}"
  local out code
  out="$("$PY" "$HARNESS/tenancy_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 1 ]; then
    printf 'FAIL tenancy_self_test: %s — expected exit 1, got %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL tenancy_self_test: %s — went red as something else and never said %s\n%s\n' \
      "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if [ -n "$needle" ] && ! printf '%s' "$out" | grep -q "$needle"; then
    printf 'FAIL tenancy_self_test: %s — went red as %s but never named %s, so it cannot be\n' \
      "$label" "$expect" "$needle" >&2
    printf '  distinguished from a different statement losing its scope.\n%s\n' "$out" >&2
    failures=$((failures + 1))
    return
  fi
  breakages=$((breakages + 1))
  printf 'PASS tenancy_self_test: breakage %s: %s — caught by `%s`%s\n' \
    "$breakages" "$label" "$expect" "${needle:+ about $needle}"
}

# expect_green <label> <repo> [must-print] — the fixture must come back green,
# and when a token is given the report must ALSO print it. The second half is
# what keeps a warning from becoming silence: a checker that reported nothing at
# all about a service it cannot read would pass this too, and it is precisely the
# shape this file exists to prevent.
expect_green() {
  local label="$1" repo="$2" must_print="${3:-}"
  local out code
  out="$("$PY" "$HARNESS/tenancy_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL tenancy_self_test: %s — expected green, got exit %s\n%s\n' "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if [ -n "$must_print" ] && ! printf '%s' "$out" | grep -q "$must_print"; then
    printf 'FAIL tenancy_self_test: %s — exited 0 without printing %s, so the thing it could\n' \
      "$label" "$must_print" >&2
    printf '  not see is being reported as nothing being there.\n%s\n' "$out" >&2
    failures=$((failures + 1))
    return
  fi
  green_cases=$((green_cases + 1))
  printf 'PASS tenancy_self_test: green case %s: %s — exit 0%s\n' \
    "$green_cases" "$label" "${must_print:+ and named what it cannot see}"
}

# expect_warn <label> <repo> <finding-id> — the finding must be printed AND the
# exit code must STILL BE 0. The exit code is the half that matters, and it is
# the half a tri-state checker gets wrong. All four warnings here are the same
# claim: *this machine cannot answer that question*. Failing on them is how a
# checker gets disabled, which would leave the fleet with no boundary check at
# all instead of an incomplete one.
expect_warn() {
  local label="$1" repo="$2" expect="$3"
  local out code
  out="$("$PY" "$HARNESS/tenancy_check.py" "$repo" 2>&1)"
  code=$?
  if [ "$code" -ne 0 ]; then
    printf 'FAIL tenancy_self_test: %s — a warning moved the exit code to %s\n%s\n' \
      "$label" "$code" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  if ! printf '%s' "$out" | grep -q "$expect"; then
    printf 'FAIL tenancy_self_test: %s — exited 0 without even printing %s\n%s\n' \
      "$label" "$expect" "$out" >&2
    failures=$((failures + 1))
    return
  fi
  warn_cases=$((warn_cases + 1))
  printf 'PASS tenancy_self_test: warning %s: %s — said `%s` and still exited 0\n' \
    "$warn_cases" "$label" "$expect"
}

# --------------------------------------------------------------------------
# the control. Without it, sixteen reds prove nothing at all: a checker that
# refused everything would satisfy every expectation below.
# --------------------------------------------------------------------------
control="$(fresh_copy control "$FIXTURE")"
out="$("$PY" "$HARNESS/tenancy_check.py" "$control" 2>&1)"
code=$?
if [ "$code" -ne 0 ]; then
  printf 'FAIL tenancy_self_test: the control — a service whose declaration is true — did not come back green (exit %s)\n%s\n' \
    "$code" "$out" >&2
  failures=$((failures + 1))
else
  printf 'PASS tenancy_self_test: the control — a service whose declaration is true — is green\n'
fi

# And the control must be green with NO warnings either. A warning-free control
# is what proves the scanner classifies everything the fixture contains, so the
# warning cases below are warnings about this fixture's SHAPE rather than
# artefacts of an over-eager scanner. "0 failure(s), 0 warning(s)" is matched as
# a whole line rather than grepped for a number.
if ! printf '%s' "$out" | grep -q '0 failure(s), 0 warning(s)'; then
  printf 'FAIL tenancy_self_test: the control — a service that declares every site it has — is not warning-free\n%s\n' \
    "$out" >&2
  failures=$((failures + 1))
fi

# --------------------------------------------------------------------------
# the seven ways scoping gets dropped
# --------------------------------------------------------------------------

# (1) a missing WHERE on a read. The other selects on `assets` still carry the
# key, so closure stays closed and what fires is `scope-lost`: the declaration
# said the scoping was on line 22 and line 22 no longer scopes anything. That is
# the more precise of the two answers and it is the one this breakage must give.
one="$(fresh_copy read-where "$FIXTURE")"
edit "$one/migrations/0001_assets.sql" \
  'select * from assets where id = $1 and account_id = $2' \
  'select * from assets where id = $1'
expect_red 'a read with its WHERE dropped' "$one" 'tenancy.scope-lost' 'asset-fetch'

# (2) a missing bind parameter. `account_id = $2` is STILL in the statement and
# nothing passes $2 any more — the defect a predicate check cannot see, and the
# reason `mechanism: bind-parameter` carries a named parameter at all.
two="$(fresh_copy bind-missing "$FIXTURE")"
edit "$two/src/assets.rb" \
  'DB.exec(SQL, checksum, account.account_id)' \
  'DB.exec(SQL, checksum)'
expect_red 'a bound account parameter nothing binds' "$two" 'tenancy.bind-missing' 'asset-checksum-bind'

# (3) an unscoped list. `select id, checksum, status from assets where …` is the
# one a join usually loses the scope on, and it is a different statement from (1)
# — which is why the needle is part of the assertion.
three="$(fresh_copy list-unscoped "$FIXTURE")"
edit "$three/migrations/0001_assets.sql" \
  'select id, checksum, status from assets where account_id = $1 order by created_at' \
  'select id, checksum, status from assets order by created_at'
expect_red 'a list that lists the whole table' "$three" 'tenancy.scope-lost' 'asset-list'

# (4) an unscoped update. The only `update` on `assets`, so the site disappears
# and closure itself is what fires — `entry-absent`, not `scope-lost`. The
# distinction is not pedantry: "the predicate is gone" and "the declaration points
# at the wrong line" want different fixes, and a checker that cannot tell them
# apart reports the second as a pass.
four="$(fresh_copy update-unscoped "$FIXTURE")"
edit "$four/migrations/0001_assets.sql" \
  "update assets set status = 'settled' where id = \$1 and account_id = \$2" \
  "update assets set status = 'settled' where id = \$1"
expect_red 'an update that updates whichever row it is given' "$four" 'tenancy.entry-absent' 'asset-settle'

# (5) an unscoped delete. The same shape as (4) on the statement that would end
# a customer's data if it were the wrong customer's.
five="$(fresh_copy delete-unscoped "$FIXTURE")"
edit "$five/migrations/0001_assets.sql" \
  'delete from assets where id = $1 and account_id = $2' \
  'delete from assets where id = $1'
expect_red 'a delete that deletes whichever row it is given' "$five" 'tenancy.entry-absent' 'asset-delete'

# (6) IDOR on fetch-by-id. `asset_variants` is fetched by id on exactly one line,
# so losing the scope there leaves the declaration with nothing to point at.
six="$(fresh_copy idor-variant "$FIXTURE")"
edit "$six/migrations/0001_assets.sql" \
  'select * from asset_variants where id = $1 and account_id = $2' \
  'select * from asset_variants where id = $1'
expect_red 'a variant fetched by id with the scope dropped — an IDOR' "$six" 'tenancy.entry-absent' 'asset-variant-fetch'

# (7) the negative assertion weakened from ABSENT to FORBIDDEN. This is the
# breakage D33 exists to make catchable: the test still runs, the suite is still
# green, and the assertion has stopped saying what the contract says it says —
# because `forbidden` confirms the id exists. The declaration is left alone, so
# this is `denial-missing`; breakage 10 below is the same weakening WITH the
# declaration updated, which is `denial-refuses`.
seven="$(fresh_copy denial-weakened "$FIXTURE")"
edit "$seven/tests/tenancy_test.rb" \
  'assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?' \
  'assert_equal :forbidden, Assets.fetch("a1", account(OTHER_ACCOUNT))'
expect_red 'a negative assertion weakened from absent to forbidden' "$seven" 'tenancy.denial-missing' 'asset-fetch'

# (7b) THE THIRD ARM. The two cases above are satisfied by a service that
# returns nothing to anybody, which is a broken service rather than an isolated
# one, so `negative.cases` requires a third arm that says the account's own
# credential gets its row back. Pointing it at a line that asserts this language's
# spelling of nothing is the same defect wearing a different hat: a declaration
# that says "this account sees its own rows" about a test that says the opposite.
# The anchor spans three lines because `expects: checksum` appears on three of
# the seven entry points, and an anchor the `edit` guard calls ambiguous is an
# anchor that would silently prove a different check.
sevenb="$(fresh_copy positive-control-absent "$FIXTURE")"
edit "$sevenb/tenancy.yml" \
  '          expects: checksum
          file: tests/tenancy_test.rb
          line: 49' \
  '          expects: nil
          file: tests/tenancy_test.rb
          line: 49'
expect_red 'the positive control answered with nothing' "$sevenb" 'tenancy.positive-control-refused' 'own-account'

# (7c) THE SHAPE. Every breakage above asks whether the DECLARATION and the file
# agree. This asks whether the assertion a service chose can fail for the reason
# it claims — a different question, and the one Postgres's three denial mechanisms
# decide. A `using` clause filters the row out and raises NOTHING, so a read
# denial asserted as an exception is asserting a *privilege* failure — which is
# exactly what a table with no policy at all raises. The suite goes green and
# isolation is completely broken, which is the trap this whole file exists for.
#
# Both the FILE and the DECLARATION are edited, because a breakage that edited
# only one of them would be caught by `denial-missing` instead and would prove
# the wrong check. This is the case in the research: a suite that asserts only
# "it threw" and passes.
sevenc="$(fresh_copy denial-shape-raise "$FIXTURE")"
edit "$sevenc/tests/tenancy_test.rb" \
  'assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?' \
  'assert_raises(RuntimeError) { Assets.fetch("a1", account(OTHER_ACCOUNT)) }'
edit "$sevenc/tenancy.yml" '          expects: nil
          file: tests/tenancy_test.rb
          line: 44' '          expects: assert_raises
          file: tests/tenancy_test.rb
          line: 44'
expect_red 'a read denial asserted as a raised error — the `using` clause raises nothing' \
  "$sevenc" 'tenancy.denial-shape' 'other-account'

# (7d) THE SAME SILENCE, WEARING A DIFFERENT HAT. `lives_ok` passes when the
# write matched zero rows, which is the sentence the research source says not to
# ignore, and pointing the THIRD arm at one is the exact mistake the arm exists to
# catch: a declaration that says "this account's write reached its own row" about
# a test that would be equally happy matching nothing.
sevend="$(fresh_copy denial-shape-lives-ok "$FIXTURE")"
edit "$sevend/tests/tenancy_test.rb" \
  'assert_changed("a1") { Assets.settle("a1", account(ACCOUNT)) }' \
  'lives_ok { Assets.settle("a1", account(ACCOUNT)) }'
edit "$sevend/tenancy.yml" '          expects: assert_changed
          file: tests/tenancy_test.rb
          line: 88' '          expects: lives_ok
          file: tests/tenancy_test.rb
          line: 88'
expect_red 'the positive control of a write proven with lives_ok, which passes when it matched zero rows' \
  "$sevend" 'tenancy.denial-shape' 'own-account'

# (7e) THE PAIRING. A denied write matched zero rows, and a row count of zero is
# also what a write that found nothing to do returns — so on its own it cannot
# tell a refusal from a no-op. Answering the arm with an ABSENT result is worse:
# the victim's row is still there, so "nothing came back" claims it is not. This
# is the clause that turns "nothing threw" into evidence, and it is the one the
# format asks for (`assert_unchanged`) and did not enforce.
sevene="$(fresh_copy denial-unpaired "$FIXTURE")"
edit "$sevene/tests/tenancy_test.rb" \
  'assert_unchanged("a1") { Assets.settle("a1", account(OTHER_ACCOUNT)) }' \
  'assert Assets.settle("a1", account(OTHER_ACCOUNT)).nil?'
edit "$sevene/tenancy.yml" '          expects: assert_unchanged
          file: tests/tenancy_test.rb
          line: 84' '          expects: nil
          file: tests/tenancy_test.rb
          line: 84'
expect_red 'a denied write asserted without reading back the row it was aimed at' \
  "$sevene" 'tenancy.denial-unpaired' 'other-account'

# --------------------------------------------------------------------------
# and the ways the DECLARATION stops describing the code
# --------------------------------------------------------------------------

# (8) a declaration that points at a file nobody has. The cheapest check in the
# checker and the one that most often fires the day a service renames a
# directory — which is exactly why it is here rather than assumed.
#
# The anchor spans the line number as well, and that is not decoration. The
# fixture names `migrations/0001_assets.sql` in six entry points, so a
# single-line anchor edits whichever came first and this breakage has been
# passing because the first one happened to be `asset-fetch`, the entry point
# its `expect_red` names. Anchor it to `line: 22` — the fetch by id — and the
# breakage says which entry point it is breaking.
eight="$(fresh_copy location-missing "$FIXTURE")"
edit "$eight/tenancy.yml" '      file: migrations/0001_assets.sql
      line: 22' '      file: migrations/0002_assets_v2.sql
      line: 22'
expect_red 'a declaration naming a file this service does not have' "$eight" 'tenancy.location-missing' 'asset-fetch'

# (9) a declaration naming a line past the end of the file. A line number nobody
# checked is the false green written down, in its plainest form.
nine="$(fresh_copy line-missing "$FIXTURE")"
edit "$nine/tenancy.yml" 'line: 37' 'line: 900'
expect_red 'a declaration naming a line past the end of the file' "$nine" 'tenancy.line-missing' 'asset-variant-fetch'

# (10) the same weakening as (7), WITH the declaration updated to match. The
# schema refuses a refusal outright (`const absent`) and the checker names it as
# the enumeration oracle it is, rather than reporting "your file is invalid" and
# sending the reader looking for a typo.
ten="$(fresh_copy denial-refuses "$FIXTURE")"
edit "$ten/tenancy.yml" '      line: 22
    negative:
      asserts: absent' '      line: 22
    negative:
      asserts: forbidden'
expect_red 'a declaration that answers another account with a refusal' "$ten" 'tenancy.denial-refuses' 'asset-fetch'

# (11) an account-scoped statement nobody declared. The other direction of
# closure, and the one that turns a declaration from a summary into a contract:
# without it, adding a new scoped query is invisible, and the enumeration drifts
# the moment nobody is looking.
eleven="$(fresh_copy undeclared "$FIXTURE")"
edit "$eleven/migrations/0001_assets.sql" \
  'delete from assets where id = $1 and account_id = $2' \
  'delete from assets where id = $1 and account_id = $2

-- added by a refactor nobody declared
select * from archive where account_id = $1'
expect_red 'an account-scoped query nobody declared' "$eleven" 'tenancy.undeclared-entry' 'archive'

# (12) a service that declares no account scoping and has one. The honest zero,
# caught leaving. An omission is not a zero, and this is the check that makes the
# difference sayable in the first place.
twelve="$(fresh_copy honest-zero "$ZERO_FIXTURE")"
edit "$twelve/src/generate.go" \
  'func Render(templatePath string, values map[string]string) (string, error) {' \
  '// A scoped read nobody declared, in a service that says it has none:
func ReadForAccount(account_id string) (string, error) {
	_, _ = account_id, os.ReadFile
	return "", nil
}

func Render(templatePath string, values map[string]string) (string, error) {'
expect_red 'a service that declares no scoping and has account-scoped code' "$twelve" 'tenancy.honest-zero'

# (13) the honest zero caught leaving, is (12) above; these four are the ones
# that fire BEFORE a boundary is even declared, and they are the four most
# likely to be needed first — every repository in this fleet hits
# `declaration-missing` today, and a finding nobody has ever seen go red is a
# finding whose message has never been read by anybody.

# (13) no declaration at all. The fleet's actual state, and the one finding
# every one of the thirteen repositories produces before it adopts anything.
# The copy is a full conforming service with its `tenancy.yml` removed, because
# a checker that reports "nothing there" for a directory with no source in it
# would pass this for the wrong reason.
thirteen="$(fresh_copy no-declaration "$FIXTURE")"
rm -f "$thirteen/tenancy.yml"
expect_red 'a service that declares no account boundary at all' "$thirteen" 'tenancy.declaration-missing'

# (14) a declaration core's own YAML reader refuses. A tab where indentation
# belongs is the realistic shape — an editor wrote it — and it is why this is
# its own finding rather than a `tenancy.schema` row: a reader that cannot parse
# the file cannot validate it either, and reporting "your file is invalid" about
# a file the reader never read sends the reader looking for a typo in a
# declaration that may be perfectly correct.
fourteen="$(fresh_copy unreadable-declaration "$FIXTURE")"
printf 'version: 1\nentryPoints: [ \n' > "$fourteen/tenancy.yml"
expect_red 'a declaration the reader cannot parse' "$fourteen" 'tenancy.declaration-unreadable'

# (15) `accountScoped: true` with an empty list. The omission facing the other
# way: a service that says it scopes by account and then declares no way it
# does. It arrives as two findings on purpose — the schema's `minItems: 1` says
# the file is not a declaration, and `enumeration-empty` says what it actually
# is — because "invalid" and "you have not said the thing you said you said" are
# different sentences, and a reader who gets only the first will go fix syntax.
#
# It is done on the honest-zero fixture rather than the conforming one, and the
# reason is mechanical: the conforming fixture already has a populated
# `entryPoints:`, and APPENDING an empty one would make the document carry that
# key twice — which core's reader refuses, and the finding would then be
# `declaration-unreadable` rather than the one under test. A breakage that
# proves a different check is a breakage that proves nothing.
fifteen="$(fresh_copy scoped-but-silent "$ZERO_FIXTURE")"
edit "$fifteen/tenancy.yml" $'\naccountScoped: false' $'\naccountScoped: true'
expect_red 'a service that claims to scope by account and declares no way it does' \
  "$fifteen" 'tenancy.enumeration-empty'

# (16) an undeclared top-level key. The one this repository holds every other
# schema to: `additionalProperties: false` is why an undeclared key is an error
# rather than a silent no-op that reads as a decision somebody made. The file is
# otherwise entirely valid, so `tenancy.schema` is the ONLY finding and this is
# the cleanest proof of it. `cache` is the key the gate declaration already
# refuses, reused so the two checkers answer the same mistake identically.
sixteen="$(fresh_copy undeclared-key "$FIXTURE")"
edit "$sixteen/tenancy.yml" 'version: 1' 'version: 1
cache:
  enabled: false'
expect_red 'a declaration with a key the format does not declare' "$sixteen" 'tenancy.schema'

# --------------------------------------------------------------------------
# the database half — eleven ways row-level security silently fails
# --------------------------------------------------------------------------
# Supabase's database advisor is the reference for these and its twenty-eight
# lints are read, adopted and excluded in the ledger in docs/tenancy.md, which
# `test_the_row_level_security_rules_are_adopted_and_the_exclusions_are_written_down`
# checks. Two of them have no Supabase ancestor at all and say so here rather than
# borrowing the credit.
#
# EVERY anchor below spans enough lines to be unambiguous, because the clause text
# of a policy appears five times in 0002_rls.sql. That is the `edit` guard at the
# top of this file doing its job: a breakage that edited whichever match came
# first would report a pass for a check it had not exercised, which is this
# script's own reason for existing.

# (18) THE FORCE LINE REMOVED. The single highest-value check in the whole
# tenancy checker, and the reason it is one: **Postgres does not apply row-level
# security to a table's OWNER unless the table is set FORCE.** A service owns the
# tables it created in its own schema, so removing this one line leaves a service
# that ships policies, enables RLS, and is wrong about every row it owns — with
# every query still succeeding, because a policy that is never evaluated does not
# raise. Nothing anywhere reports it: Postgres documents it in the CREATE TABLE
# reference and not in the row-level-security guide, and Supabase's advisor
# collects `relforcerowsecurity` for its table list and never judges it.
#
# `force` is its own reloptions bit and does not imply `enable`, so removing this
# line cannot disturb the enable line above it — which is why this breakage moves
# exactly one finding and not two.
eighteen="$(fresh_copy rls-force-missing "$FIXTURE")"
edit "$eighteen/migrations/0002_rls.sql" \
  'alter table assets force row level security;
' ''
expect_red 'a table with policies whose owner bypasses them' "$eighteen" 'tenancy.rls-owner-bypass' 'assets'

# (19) policies with RLS never enabled. Supabase's
# `policy_exists_rls_disabled` (0007), adopted whole.
nineteen="$(fresh_copy rls-not-enabled "$FIXTURE")"
edit "$nineteen/migrations/0002_rls.sql" \
  'alter table assets enable row level security;
' ''
expect_red 'policies that are never evaluated' "$nineteen" 'tenancy.rls-not-enabled' 'assets'

# (20) a declared policy the migrations do not create. The whole statement is
# REMOVED rather than renamed: renaming it would also make it a policy nobody
# declared, and a breakage that fires two findings proves neither.
twenty="$(fresh_copy rls-policy-absent "$FIXTURE")"
edit "$twenty/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));

' ''
expect_red 'a policy the declaration names and the migrations do not' "$twenty" 'tenancy.rls-policy-absent' 'assets_select_own'

# (21) a table the declaration does not cover. This is the half-adoption the
# `rls` block's `databaseEnforced: false` arm exists to make sayable: the service
# told core the database enforces nothing, and then a migration enabled it on a
# table nobody listed. Supabase has no lint for this because in PostgREST the
# question is "can `anon` reach it" and here it is "did you say you had done
# this".
twentyone="$(fresh_copy rls-undeclared "$FIXTURE")"
edit "$twentyone/migrations/0002_rls.sql" \
  'alter table asset_variants force row level security;
' 'alter table asset_variants force row level security;

-- a table the declaration does not cover
alter table uploads enable row level security;
alter table uploads force row level security;
'
expect_red 'row-level-security DDL for a table nobody declared' "$twentyone" 'tenancy.rls-undeclared' 'uploads'

# (22) a policy that admits every row. Supabase's `rls_policy_always_true` (0024),
# ADAPTED rather than adopted, and the adaptation is the interesting part: their
# lint deliberately excludes `USING (true)` on a SELECT because public read is a
# real thing on Supabase. Cafaye has no public read tier — every table in
# `rls.tables` is account-scoped by construction — so the exclusion does not carry
# over and the SELECT arm is judged here. See docs/tenancy.md's ledger.
twentytwo="$(fresh_copy rls-permissive "$FIXTURE")"
edit "$twentytwo/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));' \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (true);'
expect_red 'a policy that constrains nothing' "$twentytwo" 'tenancy.rls-permissive' 'assets_select_own'

# (23) the per-row rule. Supabase's `auth_rls_initplan` (0003) is a PERFORMANCE
# warning; here it is a FAILURE, and the reason is in docs/tenancy.md: a warning
# in this checker means *this machine cannot answer that question*, and this one
# is fully decidable from the migration text. A severity nobody chose is not a
# severity.
twentythree="$(fresh_copy rls-per-row "$FIXTURE")"
edit "$twentythree/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));' \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = app.current_account());'
expect_red 'an identity call that runs once per row' "$twentythree" 'tenancy.rls-per-row' 'assets_select_own'

# (24) a policy applied to a role that skips every policy. Supabase filters
# `not r.rolbypassrls` out of its permissiveness lint and never says why; here it
# is the finding, because a policy naming a bypass role is enforced on no read at
# all and reads as enforced.
twentyfour="$(fresh_copy rls-role-bypass "$FIXTURE")"
edit "$twentyfour/migrations/0002_rls.sql" \
  'create role tenant_app noinherit' \
  'create role tenant_app noinherit bypassrls'
expect_red 'a policy applied to a role that bypasses every policy' "$twentyfour" 'tenancy.rls-role-bypass' 'tenant_app'

# (24b) the roles the declaration names and the roles the DDL binds are not the
# same roles. ADDED after (24) rather than beside it because (24) is the narrow
# case of this one: a role that carries BYPASSRLS is caught by name, while a role
# that simply does not appear in the `for … to …` clause was not caught at all,
# and the declaration that named it still validated. Both directions leak, so the
# breakage is the direction that reads narrow in review and is wide in the
# database — `to public, tenant_app` in the DDL against `[tenant_app]` in
# `rls.tables[].policies[].roles`.
#
# It expects `tenancy.rls-permissive` rather than a new id on purpose. The
# finding that already owns "a policy names no role and therefore applies to
# PUBLIC" owns this too: it is the same sentence with the subject moved one step
# along, and a finding a reader has to look up is a finding nobody acts on. The
# needle is the policy, because the same fixture declares four policies and only
# this one changed.
twentyfourb="$(fresh_copy rls-role-undeclared "$FIXTURE")"
edit "$twentyfourb/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app' \
  'create policy assets_select_own on assets
  for select to public, tenant_app'
expect_red 'a policy the DDL binds to a role the declaration does not name' \
  "$twentyfourb" 'tenancy.rls-permissive' 'assets_select_own'

# (25) a SECURITY DEFINER function with no pinned search path. Supabase's
# `function_search_path_mutable` (0011), raised from WARN to a failure: in cafaye
# it is a tenant-crossing primitive rather than a hardening nit, because the
# runtime role can create objects in its own schema.
twentyfive="$(fresh_copy rls-definer-search-path "$FIXTURE")"
edit "$twentyfive/migrations/0002_rls.sql" \
  '  stable
  security definer
  set search_path = '"''"'' \
  '  stable
  security definer'
expect_red 'a security definer function with a mutable search path' "$twentyfive" 'tenancy.rls-definer-search-path' 'app.current_account'

# (26) a view over an account-scoped table without `security_invoker`. Supabase's
# `security_definer_view` (0010), adapted: theirs asks whether PostgREST can reach
# it, which is a privilege question this checker cannot ask, and this one asks
# whether the reader's policies run — which is a fact about the DDL.
twentysix="$(fresh_copy rls-view-invoker "$FIXTURE")"
edit "$twentysix/migrations/0002_rls.sql" \
  'create view own_assets with (security_invoker = on) as' \
  'create view own_assets as'
expect_red 'a view that reads as its owner' "$twentysix" 'tenancy.rls-view-invoker' 'own_assets'

# (27) a policy on a relation row-level security cannot constrain. Supabase's
# `foreign_table_in_api` (0017) and `materialized_view_in_api` (0016), merged into
# one finding because it is one fact about Postgres: neither is a table and
# neither has policies. The anchor is in 0001_assets.sql because that is where the
# relation is CREATED, and a relation's kind comes from where it is created.
twentyseven="$(fresh_copy rls-unprotectable "$FIXTURE")"
edit "$twentyseven/migrations/0001_assets.sql" \
  'create table asset_variants (' \
  'create foreign table asset_variants ('
expect_red 'a policy on a relation row-level security cannot constrain' "$twentyseven" 'tenancy.rls-unprotectable' 'asset_variants'

# (28) RLS DDL in a file this checker cannot parse. The fixture is the honest
# zero with a policy dropped into its Go source — a Rails service's migrations are
# `.rb` files and a Python migration module is `.py`, so this is the shape
# `tenancy.rls-unreadable` exists for. It is a WARNING and it must stay green: the
# claim is *this machine cannot settle it*, and failing on it would get the
# checker disabled, which leaves the fleet with no boundary check instead of an
# incomplete one.
twentyeight="$(fresh_copy rls-unreadable "$ZERO_FIXTURE")"
edit "$twentyeight/src/generate.go" \
  'package generate' \
  'package generate

// RLS in a language this checker cannot parse: the very next migration after
// this one, written as a Go string, and nothing below will read it.
const enableRLS = "alter table generated enable row level security"
'
expect_warn 'row-level-security DDL in a file this checker cannot parse' \
  "$twentyeight" 'tenancy.rls-unreadable'

# --------------------------------------------------------------------------
# kit's substrate — the section that did not exist before core-rls-scan-01
# --------------------------------------------------------------------------
#
# `identity-isolation-01` adopted kit's `templates/database/tenancy/substrate.sql`
# and could not write an honest `tenancy.yml`, because `protect_table` writes its
# DDL through `execute format(...)` inside plpgsql and no line in the tree begins
# `create policy`. The probe measured it: 13 failures, of which six named a
# database that `pg_class.relforcerowsecurity` and the service's own
# `internal/tenancy` both confirm is protected on all five tables.
#
# `fixtures/tenancy/substrate/` is that shape — the template copied into a
# migration, one `select cafaye.protect_table('<table>')` per account-scoped
# table, and a declaration that describes exactly what the template writes. It is
# a CONTROL, and a control is worthless without the claim it controls, so the
# first case below asserts that all of `tenancy.rls-*` is silent on it: seven
# findings, every one of which was a false negative on the identity pilot's tree.
#
# It is a SEPARATE fixture rather than a variant of the conforming one because it
# has to be able to be red on purpose without touching the fixture thirty-one
# breakages below depend on, and because the substrate's fixture is the one whose
# repository half is not what is under test — its `0001_assets.sql`, `src/` and
# `tests/` are the conforming fixture's, unchanged, so a finding that moved
# between the two fixtures moved because of the substrate and nothing else.

# THE CONTROL for the substrate. Zero `tenancy.rls-*` findings is the whole
# claim, and it is asserted as a count rather than left to the exit code: a
# fixture that reads green because the checker stopped looking is the exact shape
# of failure this whole file exists to catch, so the number of RLS findings has
# to be zero rather than "no failures".
substrate_control="$(fresh_copy substrate-control "$SUBSTRATE_FIXTURE")"
substrate_out="$("$PY" "$HARNESS/tenancy_check.py" "$substrate_control" 2>&1)"
substrate_code=$?
if [ "$substrate_code" -ne 0 ]; then
  printf 'FAIL tenancy_self_test: the substrate control — a service whose policies are written\n' >&2
  printf '  by kit%s template — did not come back green (exit %s)\n%s\n' "'s" "$substrate_code" "$substrate_out" >&2
  failures=$((failures + 1))
else
  green_cases=$((green_cases + 1))
  printf 'PASS tenancy_self_test: green case %s: the substrate — a service that calls protect_table — is green\n' \
    "$green_cases"
fi
if printf '%s' "$substrate_out" | grep -q '^FAIL tenancy\.rls-'; then
  printf 'FAIL tenancy_self_test: the substrate control still reports row-level-security findings on a tree\n' >&2
  printf '  whose four policies per table are written by cafaye.protect_table:\n%s\n' "$substrate_out" >&2
  failures=$((failures + 1))
fi

# (29) THE CLAIMED TABLE, NEVER CALLED. This is the breakage the packet asks for
# first and it is the one that matters most: a scanner that learned the template
# and now passes an unprotected table is worse than the bug being fixed. So the
# declaration still names `<table>_cafaye_<command>` and the migration still
# installs the template — and the CALL is deleted. What must fire is
# `tenancy.rls-policy-absent`, and it must name the policy, because the claim is
# "that policy is described and not enforced" rather than "this service has a
# policy problem somewhere".
#
# Four findings fire here, not one, and all four are true: the four policies are
# absent, the table is not enabled, it is not forced, and `asset_variants` is now
# declared and undeclared at once. The first is what is asserted.
#
# The anchor is TWO lines and it is two lines because the template's own comment
# block shows `select cafaye.protect_table('assets');` as an example — so the
# one-line form matches twice, and `edit` refuses an ambiguous anchor rather than
# replacing whichever came first. That refusal is the guard working, not the
# guard being inconvenient: a breakage that edited the template's prose would
# have left the migration protected and reported a red for nothing.
substrate_no_call="$(fresh_copy substrate-no-call "$SUBSTRATE_FIXTURE")"
edit "$substrate_no_call/migrations/0002_substrate.sql" \
  "select cafaye.protect_table('assets');

-- The explicit spelling" \
  "-- deleted: the declaration still names what this call wrote.

-- The explicit spelling"
expect_red 'protect_table claimed for a table the migration never calls it on' \
  "$substrate_no_call" 'tenancy.rls-policy-absent' 'assets_cafaye_select'

# (30) THE CALL, THE WRONG SPELLING. The call is there and the database is
# protected; the DECLARATION is wrong, which is the other half of the pilot's
# blocker — there, the honest declaration could not be written, and here the
# dishonest one has to go red. `assets_cafaye_read` is what somebody writes when
# they read the template's prose instead of its code, and nothing about the
# database changes.
substrate_typo="$(fresh_copy substrate-typo "$SUBSTRATE_FIXTURE")"
edit "$substrate_typo/tenancy.yml" 'assets_cafaye_select' 'assets_cafaye_read'
expect_red 'protect_table called for a table whose declaration spells the policy wrongly' \
  "$substrate_typo" 'tenancy.rls-policy-absent' 'assets_cafaye_read'

# (31) THE CALL, AND AN IDENTITY NO POLICY READS. The declaration names
# `app.current_account()` because the hand-written fixture does, and the
# substrate's policies are all scoped by `cafaye.current_account_id()`. Nothing
# about the table changed and the database is still protected, but the boundary
# is now described as built from an identity no policy on it reads — which is
# `tenancy.rls-permissive`, the same finding, with the substrate's own reason in
# the message rather than "scoped by nothing this checker can see".
substrate_identity="$(fresh_copy substrate-identity "$SUBSTRATE_FIXTURE")"
edit "$substrate_identity/tenancy.yml" \
  '  identity: cafaye.current_account_id()' \
  '  identity: app.current_account()'
expect_red 'protect_table called for a table whose declaration names an identity no policy reads' \
  "$substrate_identity" 'tenancy.rls-permissive' 'protect_table'

# And the honest half of the same claim, as a GREEN that names its gap: this
# fixture is NOT warning-free, and the warning it does print is a real finding
# about a DIFFERENT scanner — the entry-point one, which reads kit's plpgsql body
# as ordinary SQL and cannot classify the five lines naming `cafaye.account_id`.
# The token makes that warning a claim of the case rather than an accident of it:
# a reader who later makes the substrate fixture warning-free has to delete this
# line in the same commit, because a control that quietly stopped naming its gap
# is the control that stopped controlling.
expect_green 'the substrate, and the lines inside the template the entry-point scanner cannot classify' \
  "$SUBSTRATE_FIXTURE" 'enumeration-partial'

# --------------------------------------------------------------------------
# kit's CREDENTIAL call — the second entry point, and the section that is not a
# copy of the one above
# --------------------------------------------------------------------------
#
# `identity-isolation-04` adopted `cafaye.protect_credential_table('api_keys',
# 'token_digest')` and got SEVEN failures against a table whose
# `relforcerowsecurity` is true and whose five policies are in `pg_policy`. Six
# were this checker reading the wrong function name and one was the fifth
# policy's PREDICATE, so the fix is two corrections and not one wider regex:
# `<table>_cafaye_resolve` is not a fifth entry in `SUBSTRATE_POLICY_COMMANDS`
# because it is not a command, and it is not scoped by the account identity
# because scoping it by the account IS the widening the mechanism exists to
# prevent.
#
# `fixtures/tenancy/credential/` is that shape: the substrate's fixture plus ONE
# call and ONE table, committed RED in `cdda7d4` and green by the next commit.
# The template in it is kit master's, byte for byte, because the checker claims to
# resolve what the TEMPLATE writes and a fixture that paraphrases the template is
# a fixture that cannot contradict it.
#
# THE CONTROL is therefore not "exit 0". This fixture's baseline is THREE reds
# and they are all `tenancy.undeclared-entry` naming `pg_attribute` INSIDE kit's
# template — the entry-point scanner's documented gap, measured on identity's own
# 00016 as "3 findings and 11 unattributable sites, every one of them inside the
# template". The substrate fixture has none of them only because its template copy
# predates MD24's sweep. So the control here pins BOTH numbers: three findings,
# every one of them the gap, and zero `tenancy.rls-*`. Asserting the total and
# the subset separately is what makes a new red impossible to hide — a control
# that only checked the subset would pass on a tree that had started failing for
# a reason nobody wrote down.
credential_control="$(fresh_copy credential-control "$CREDENTIAL_FIXTURE")"
credential_out="$("$PY" "$HARNESS/tenancy_check.py" "$credential_control" 2>&1)"
credential_fails="$(printf '%s' "$credential_out" | grep -c '^FAIL tenancy\.' || true)"
if [ "$credential_fails" -ne 3 ]; then
  printf 'FAIL tenancy_self_test: the credential control reports %s failure(s) and the fixture is\n' \
    "$credential_fails" >&2
  printf '  committed with three — all of them `pg_attribute` inside kit template, and all of\n' >&2
  printf '  them the entry-point scanner. A fourth means this fixture changed under the control,\n' >&2
  printf '  and a control that stopped noticing is the control that stopped controlling:\n%s\n' \
    "$credential_out" >&2
  failures=$((failures + 1))
else
  green_cases=$((green_cases + 1))
  printf 'PASS tenancy_self_test: green case %s: the credential fixture — three reds, every one of\n' \
    "$green_cases"
  printf '  them the entry-point scanner gap the docs name, and nothing else\n'
fi
if printf '%s' "$credential_out" | grep -q '^FAIL tenancy\.rls-'; then
  printf 'FAIL tenancy_self_test: the credential control still reports row-level-security findings on\n' >&2
  printf '  a tree whose five policies on api_keys are written by cafaye.protect_credential_table:\n%s\n' \
    "$credential_out" >&2
  failures=$((failures + 1))
fi
if printf '%s' "$credential_out" | grep '^FAIL tenancy\.undeclared-entry' \
   | grep -qv 'pg_attribute'; then
  printf 'FAIL tenancy_self_test: the credential control has an undeclared-entry finding that is NOT\n' >&2
  printf '  the template gap, so the count above is being satisfied by a different defect:\n%s\n' \
    "$credential_out" >&2
  failures=$((failures + 1))
fi
if ! printf '%s' "$credential_out" | grep -q 'enumeration-partial'; then
  printf 'FAIL tenancy_self_test: the credential control exited without the entry-point scanner naming\n' >&2
  printf '  what it cannot classify. A control that quietly stopped naming its gap is the control\n' >&2
  printf '  that stopped controlling.\n%s\n' "$credential_out" >&2
  failures=$((failures + 1))
fi

# (32) THE CREDENTIAL CALL, AND NOTHING CALLING IT. The declaration still names
# five policies and the template is still installed; the CALL is deleted. Seven
# findings fire and all seven are true — five absent policies, a table that is
# neither enabled nor forced — and the first is what is asserted, because the
# claim is "that policy is described and not enforced" rather than "this service
# has a policy problem somewhere".
#
# The anchor is TWO lines for the reason (29)'s is: kit's own comment shows
# `select cafaye.protect_credential_table('api_keys', 'token_digest');` as the
# example of the call, so the one-line form matches twice and `edit` refuses an
# ambiguous anchor rather than replacing whichever came first. That refusal is the
# guard working: a breakage that edited the template's prose would have left the
# table protected and reported a red for nothing.
credential_no_call="$(fresh_copy credential-no-call "$CREDENTIAL_FIXTURE")"
edit "$credential_no_call/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
-- deleted: the declaration still names what this call wrote."
expect_red 'protect_credential_table claimed for a table the migration never calls it on' \
  "$credential_no_call" 'tenancy.rls-policy-absent' 'api_keys_cafaye_resolve'

# (33) THE DECLARATION NAMES FOUR OF FIVE. This is the case the pilot could not
# write, and it is asked twice, in both directions, because they are different
# mistakes with the same one-line difference:
#
#   here    the declaration omits `api_keys_cafaye_resolve`, so a policy the
#           template WROTE is in the migrations and not in `rls.tables` —
#           `tenancy.rls-undeclared`. This is the direction that used to be
#           reachable only by lying, and it is the reason the packet's report
#           says the fifth row "is declared rather than omitted, because a list
#           of four of five cannot be walked in either direction".
#   (35)    the DECLARATION invents it on a table the credential call never
#           touched — `tenancy.rls-policy-absent`.
#
# A warning was considered here and REJECTED, and the reason is in
# harness/tenancy_findings.json: a warning in this file means "this machine
# cannot answer that question", and this machine can — it resolved the call and
# knows the table has five policies. So an omission is a FAILURE, on an existing
# finding, and no new severity was invented for it.
credential_four="$(fresh_copy credential-four "$CREDENTIAL_FIXTURE")"
edit "$credential_four/tenancy.yml" \
  "        - name: api_keys_cafaye_resolve
          command: select
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 742
" ""
expect_red 'a credential table whose declaration omits the resolve policy the template wrote' \
  "$credential_four" 'tenancy.rls-undeclared' 'api_keys_cafaye_resolve'

# (34) THE CREDENTIAL CALL WITH NO DIGEST COLUMN, which is the refusal rather
# than the protection. `protect_credential_table`'s second argument is REQUIRED
# and the template raises `undefined_column` without it, so this call protected
# NOTHING — and a scanner that read the call as `protect_table` would claim four
# policies for a table with none on it and hand this declaration a green. Seven
# findings, and the absent RESOLVE one is asserted: it is the fifth that a wider
# regex would have invented.
credential_no_digest="$(fresh_copy credential-no-digest "$CREDENTIAL_FIXTURE")"
edit "$credential_no_digest/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys');"
expect_red 'a protect_credential_table call the template refuses, resolved as no boundary at all' \
  "$credential_no_digest" 'tenancy.rls-policy-absent' 'api_keys_cafaye_resolve'

# (35) THE RESOLVE POLICY INVENTED ON AN ORDINARY TABLE. The call is
# `protect_table`, which writes four, and the declaration names a fifth. This is
# the mistake somebody makes by reading the header of `docs/tenancy.md` rather
# than the call, and it is the one a `tenancy.rls-permissive` fix would not catch:
# nothing about the four policies is wrong.
credential_wrong_table="$(fresh_copy credential-wrong-table "$CREDENTIAL_FIXTURE")"
edit "$credential_wrong_table/tenancy.yml" \
  "        - name: asset_variants_cafaye_delete
          command: delete
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
" "        - name: asset_variants_cafaye_delete
          command: delete
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
        - name: asset_variants_cafaye_resolve
          command: select
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
"
expect_red 'a resolve policy claimed on a table the ordinary call protects' \
  "$credential_wrong_table" 'tenancy.rls-policy-absent' 'asset_variants_cafaye_resolve'

# (36) AND THE HALF THAT PROVES THE EXEMPTION IS NOT A SWITCH. Breakage (33)
# removed the resolve policy and the checker said so; this one puts a TABLE-WIDE
# `using (true)` in its place while leaving the row in `rls.tables`, which is the
# hand-written shape of the same mistake. `tenancy.rls-permissive` fires on the
# clause — and it fires DESPITE the resolve policy being the one policy exempt
# from the identity arm, which is the claim that the exemption is one arm and not
# "the fifth policy is not checked".
#
# The spelling is `account_id = …` rather than `token_digest = …` on purpose. A
# predicate naming the ACCOUNT would satisfy the identity arm the resolve policy
# is exempt from, so a fixture written the other way round would prove the arm
# still runs for the wrong reason.
# (37) THE SAME BOUNDARY, WRITTEN BY HAND. The call is deleted and the five
# policies written out — four scoped by `cafaye.current_account_id()`, the fifth
# scoped by `cafaye.current_credential_digest()`, both wrapped, plus the enable
# and the force lines the template would have written. This is a TRUE declaration
# of a correct database, and it is here because keying the resolve policy's
# exemption on `generated` rather than on the PREDICATE would have reported a
# false failure against it: the same defect this packet exists to end, one level
# down and wearing a different hat. A service that wrote the policies out instead
# of adopting the call has the same boundary and the same reason the fifth is not
# account-scoped.
#
# A green case rather than a control, because the credential control below already
# pins the counted baseline of the fixture that ADOPTS the call and this one does
# not touch it. What is asserted is the count — zero `tenancy.rls-*` — because
# "the run exited 0" here would also be true of a checker that stopped reading
# policies at all.
credential_hand_written="$(fresh_copy credential-hand-written "$CREDENTIAL_FIXTURE")"
edit "$credential_hand_written/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
-- the call, removed: the five policies are written out by hand below.

create policy api_keys_cafaye_select on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (account_id = (select cafaye.current_account_id()));

create policy api_keys_cafaye_insert on api_keys
  for insert to tenant_fixture, tenant_fixture_app
  with check (account_id = (select cafaye.current_account_id()));

create policy api_keys_cafaye_update on api_keys
  for update to tenant_fixture, tenant_fixture_app
  using (account_id = (select cafaye.current_account_id()))
  with check (account_id = (select cafaye.current_account_id()));

create policy api_keys_cafaye_delete on api_keys
  for delete to tenant_fixture, tenant_fixture_app
  using (account_id = (select cafaye.current_account_id()));

create policy api_keys_cafaye_resolve on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (token_digest = (select cafaye.current_credential_digest()));

alter table api_keys enable row level security;
alter table api_keys force row level security;"
credential_hand_out="$("$PY" "$HARNESS/tenancy_check.py" "$credential_hand_written" 2>&1)"
if printf '%s' "$credential_hand_out" | grep -q '^FAIL tenancy\.rls-'; then
  printf 'FAIL tenancy_self_test: the same five policies written by hand, with the resolve policy\n' >&2
  printf '  scoped by the credential digest, still report row-level-security findings. The exemption\n' >&2
  printf '  is about the PREDICATE and not about who wrote it:\n%s\n' "$credential_hand_out" >&2
  failures=$((failures + 1))
else
  green_cases=$((green_cases + 1))
  printf 'PASS tenancy_self_test: green case %s: the same five policies WRITTEN BY HAND — the resolve\n' \
    "$green_cases"
  printf '  one scoped by the digest — and zero tenancy.rls-* findings, so the exemption is the\n'
  printf '  predicate rather than the caller\n'
fi

# A SECOND PRE-EXISTING GAP, measured the same way and left alone for the same
# reason, because it is not this packet's and because its fix would change which
# finding several verified cases report. `rls.tables[].policies[].command` is
# NEVER compared against the command the migration wrote: declaring
# `assets_cafaye_select` as `command: insert` with `clause: with check` on the
# substrate fixture reports ZERO `tenancy.rls-*` findings, and so does declaring
# `api_keys_cafaye_resolve` that way on this one. So the declaration can claim a
# policy governs a command it does not govern, which for the resolve policy is the
# load-bearing property kit's own comment rests on — "`for select` and nothing
# else … there is no `insert`/`update`/`delete` counterpart" — and the checker
# does not notice.
#
# It is orthogonal to the exemption above, and it is worth saying why, because
# they look connected. `account_policy` is keyed off the policy the TEMPLATE
# wrote, not off what the declaration claims, so a declaration that lies about
# the command does not weaken the exemption — the exemption is derived from a
# fact about the migration and the lie is about a field nothing reads.
#
# Named here because a reader of this section is exactly the person who would
# otherwise assume the command is checked. The successor's second move.

# WHICH FINDING FIRES, and it is named here rather than left to a reader: the
# hand-written policy REPLACES the generated one in the relation's policy map —
# they share a name, and the last statement is the one the database ends up
# holding — so this is a WRITTEN policy from the clause checks on, and the arm
# that fires is the one saying it is scoped by nothing the checker can see. It
# does NOT fire through `ALWAYS_TRUE_CLAUSES`, and that is a pre-existing defect
# in `normalised_clause` rather than a fact about this case: it strips the
# opening paren with `_POLICY_CLAUSE` and then only strips a wrapping pair when
# the body STARTS with one, so `using (true);` normalises to `true)` and matches
# none of the four spellings. Breakage (22) has been green through the same hole
# — it fires the identity arm too, and its needle cannot tell the two apart. It
# is reported rather than fixed here, because this packet is the credential call
# and a fix that changes which finding (22) reports is a change to a case the
# previous packet verified. The successor's first move.
#
# The anchor is the CALL and not the template's `qual :=` line, and the placement
# is AFTER it rather than inside the plpgsql body. Both are load-bearing:
# `protect_credential_table` drops and recreates `<table>_cafaye_resolve` every
# time it runs, so a hand-written policy with that name BEFORE the call is not
# what the database ends up holding — the call overwrites it, and this scanner
# reads statements in the order Postgres would, so a widening placed inside the
# function body is correctly invisible. A widening after the call is what a
# migration really does, and it is the shape that holds. `drop` before `create`
# because that is what a migration has to write to get there.
# The anchor is TWO lines for the reason (32)'s is: kit's comment shows the same
# call as its example of the call, so the one-line form matches twice and `edit`
# refuses rather than editing the template's prose — which would have left the
# table protected and reported a red for nothing.
credential_widened="$(fresh_copy credential-widened "$CREDENTIAL_FIXTURE")"
edit "$credential_widened/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
select cafaye.protect_credential_table('api_keys', 'token_digest');

-- A MIGRATION'S OWN WIDENING, after the call that had narrowed it.
drop policy api_keys_cafaye_resolve on api_keys;

create policy api_keys_cafaye_resolve on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (true);"
expect_red 'a resolve policy widened to admit every row, on the one policy exempt from the identity arm' \
  "$credential_widened" 'tenancy.rls-permissive' 'api_keys_cafaye_resolve'

# --------------------------------------------------------------------------
# the honest zero, with the key appearing OUTSIDE row scopes — and the two
# defects that made it unreachable
# --------------------------------------------------------------------------
#
# `fixtures/tenancy/honest-zero-token-claim/` is a service whose key appears
# only as a verified token claim, the shape muse (W36), gateway (W35) and site
# (W38) are being written in. It is the honest zero made EXPRESSIBLE, and it is
# a fixture because both halves of that claim have to be checkable:
#
#   * the bytecode carries the key and is NOT walked. A checker whose answer
#     depends on whether the suite was run in the tree is the `node_modules`
#     defect one language over, and the green case below is the proof that the
#     skip is load-bearing — remove `__pycache__` from SKIPPED_DIRECTORIES and
#     this case goes red naming the `.pyc`.
#   * the two source sites carry the key and are VOUCHED FOR in
#     `scope.nonRowSites`, each with the reason it is not a row scope. That is
#     what lets a language-neutral service declare a true zero: the declaration
#     says "I know the key is here and it is not a boundary", and the check
#     still fails for any site not named.
#
# THE GREEN CONTROL first, and it is a control in the same sense the conforming
# fixture's is: without it the two reds below prove nothing, because a checker
# that refused everything would satisfy both. It must exit 0 AND name what it
# cannot see — the two token-claim sites, which the scanner cannot attribute to
# a statement and the declaration vouches for. The `__pycache__` bytecode is
# absent from that warning, which is the defect-1 proof: it carries the key and
# is not counted.
expect_green 'the honest zero with the key only as a token claim — vouched for, bytecode skipped' \
  "$KEY_CLAIM_FIXTURE" 'enumeration-partial'

# (38) A KEY-CARRYING SITE THE DECLARATION DOES NOT VOUCH FOR. The field excuses
# only NAMED sites, and this is the case that proves it: a third token-claim
# line appears in the source and `scope.nonRowSites` does not name it, so it is
# evidence against the zero — exactly as it would be on a service that never
# adopted the field. The omission is still a failure; the field is a way to say
# "this is not a boundary", not a way to say "I cannot see this".
thirtyeight="$(fresh_copy key-claim-unnamed "$KEY_CLAIM_FIXTURE")"
edit "$thirtyeight/src/token.py" \
  '    return claims.get("account_id")' \
  '    return claims.get("account_id")


ACCOUNT_CLAIM = "account_id"'
expect_red 'a key-carrying site the declaration does not vouch for' \
  "$thirtyeight" 'tenancy.honest-zero' 'src/token.py:9'

# (39) A GENUINELY ACCOUNT-SCOPED STATEMENT, DROPPED INTO THE SAME SERVICE. The
# constraint the whole change is bounded by: `nonRowSites` excuses only sites the
# scanner could NOT attribute to a statement, so a key this scanner read in a
# `select` is a row scope by definition and naming it changes nothing. This is
# the omission the honest zero exists to catch, and it must still be caught here
# — a change that makes any `accountScoped: false` pass is not this packet. The
# `undeclared-entry` fires too, and both are true: the statement is undeclared
# AND the zero is not honest.
thirtynine="$(fresh_copy key-claim-statement "$KEY_CLAIM_FIXTURE")"
printf 'select * from assets where id = $1 and account_id = $2\n' > "$thirtynine/src/queries.sql"
expect_red 'a genuinely account-scoped statement in a service that says it has none' \
  "$thirtynine" 'tenancy.honest-zero' 'assets'

# --------------------------------------------------------------------------
# the warnings, which must be printed AND must not move the exit code
# --------------------------------------------------------------------------
expect_warn 'an enumeration this checker cannot close, on a language it cannot read' \
  "$BLIND_FIXTURE" 'tenancy.enumeration-partial'
expect_warn 'the same service, and the key it found no statement for' \
  "$BLIND_FIXTURE" 'tenancy.scope-key-unused'

# (17) a declared source path that is not in the service. ADDING one rather than
# renaming one is deliberate: renaming `migrations` would also stop the scan
# finding the sites the declarations point at, and the result would be four
# `entry-absent` failures — a red that proves nothing about this check. Adding a
# path leaves the scan reading exactly what it was reading, so the ONLY finding
# is the one under test: the scan covered less than the declaration asked, and
# says so instead of reporting a clean bill of health over the smaller area.
#
# The anchor is two lines because the fixture now declares TWO source lists —
# `scope.sources` and `rls.sources` — and `- migrations` appears in both. That is
# the `edit` guard catching a real ambiguity rather than a theoretical one.
seventeen="$(fresh_copy scan-narrowed "$FIXTURE")"
edit "$seventeen/tenancy.yml" '    - migrations
    - src' '    - migrations
    - db/generated
    - src'
expect_warn 'a source path the declaration names that is not there' \
  "$seventeen" 'tenancy.scan-narrowed'

# --------------------------------------------------------------------------
# and the honesty case, which is a GREEN that must name what it cannot see
# --------------------------------------------------------------------------
# A Go service with real account scoping this checker cannot parse. The verdict
# it must produce is two warnings and an exit code of zero — NOT a silent pass,
# and emphatically not "no account-scoped entry points found". The token is the
# entry point's name, which is what forces the report to be specific rather than
# merely non-empty.
expect_green 'a service whose scoping this checker cannot read, reported as unread rather than as absent' \
  "$BLIND_FIXTURE" 'get-asset'

# The honest zero, green, and it says out loud that a key it matched nothing in
# is not a proof. `kit` and `caf` are the fleet's two real zeros; both would say
# this, which is the difference between an honest zero and an unexamined one.
expect_green 'the honest zero: a service that declares no scoping and has none' \
  "$ZERO_FIXTURE" 'tenancy.scope-key-unused'

# --------------------------------------------------------------------------

printf '\n'
printf 'tenancy_self_test — counts, reported separately so a green cannot hide one:\n'
printf '  breakages that went RED and named their finding : %s\n' "$breakages"
printf '  warning cases that stayed GREEN                 : %s\n' "$warn_cases"
printf '  green cases, each of which named what it cannot see : %s\n' "$green_cases"
printf '  controls (a true declaration, unbroken)          : 1\n'
printf '  SKIPPED                                           : 0\n'
printf '  (nothing here is conditional on the machine: no case skips, and a case\n'
printf '   that could not run exits non-zero above rather than reporting a skip.)\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: tenancy_self_test — %s case(s) the tenancy checker did not get right: %s breakage(s), %s warning case(s), %s green case(s), 1 control.\n' \
    "$failures" "$breakages" "$warn_cases" "$green_cases"
  exit 1
fi
printf 'PASS: tenancy_self_test — %s breakages went red naming their finding, %s warning cases stayed green,\n' \
  "$breakages" "$warn_cases"
printf '      %s green cases each named what the checker cannot see, the control is green and warning-free,\n' \
  "$green_cases"
printf '      0 skipped. The negative assertions are READ, not run — harness/tenancy_findings.json\n'
printf '      says so in its notEnforced list, and that gap is the gate'"'"'s job, in the service.\n'

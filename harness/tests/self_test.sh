#!/usr/bin/env bash
#
# The harness's proof that it is able to fail.
#
#   bash harness/tests/self_test.sh
#
# WHAT THIS IS FOR
#   A conformance tool that has only ever said "yes" is a report, not a gate.
#   This script copies the fixtures to a throwaway directory, breaks one thing
#   at a time, and asserts the harness goes RED each time. Every breakage names
#   the rule id it expects, so a red proves that *the check written for that
#   defect* is still load-bearing — which is a different claim from "something
#   went red", and the one that decays silently.
#
#   kit's `tests/self_test.sh` is the precedent and the shape is copied: a
#   control on the unbroken tree first (without it the breakages prove nothing),
#   a fresh throwaway copy per breakage (one must never mask the next), and a
#   non-zero exit if any breakage stayed green.
#
#   The breakages are chosen the way kit chose its mutants: not a typo a
#   reviewer would see, but the mistake that looks like diligence. A harness
#   that rejects `name: Billing` is not the claim; a harness that rejects a
#   document with *two* /vN prefixes, or one that reports three of five
#   convention rules and exits 0, is.
#
# WHAT IT IS NOT
#   Not exhaustive mutation testing. It does not prove the harness catches every
#   defect, and nothing here should be read as claiming that it does. It proves
#   forty-one specific things — nine of them the readable half of the HTTP
#   contract, four of them the postgres image pin — plus four warning cases that
#   must stay green, and it proves every control before any of it.
#
# THE FOUR CONTROLS, AND WHY THERE IS ONE PER FAMILY
#   `fixtures/conforming` is "the smallest document that satisfies every rule the
#   harness could decide": one GET, one 200, no error path, no pagination, no
#   mutating POST. That is the right control for the rules that existed when it
#   was written and the wrong fixture for the eight that decide the error
#   envelope, the pagination envelope and idempotency — `openapi.errors-are-
#   problems` cannot fail in a document with no non-2xx response, so a breakage
#   aimed at it there would be proving that a rule cannot fire.
#   `fixtures/conforming-openapi` carries all three families conforming, so
#   breaking one is a statement about the rule rather than about the fixture.
#   `fixtures/conforming-postgres` is the control for the pin rule and earns its
#   place by what it CONTAINS: all three declaration shapes (compose, workflow
#   `services:`, `docker run`) AND the four shapes that must NOT be read as a
#   reference — a DSN with a password in it, a `postgres` used as a database
#   user, a `postgres` used as a migration driver name, and a `redis:` container
#   run. A scanner that read any of those as an image reference would make four
#   false accusations on the day it landed, and a green control is the assertion
#   that it does not. `fixtures/conforming-postgres-exception` is the fourth,
#   because "a different major, DECLARED" is a green state a rule with no
#   exception path could not produce — and a green nobody can reach is not a
#   control.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures"
SELF_TEST="$HARNESS/tests/self_test.sh"
CONFORMANCE="bin/anywaye-contract"

# The interpreter is resolved exactly as the wrapper resolves it, so a
# self-test that passes here proves the thing a service will run passes there.
PY="${ANYWAYE_CONTRACT_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "self_test: no python >= 3.9 found; set ANYWAYE_CONTRACT_PYTHON" >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-harness-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
breakages=0
warnings=0
copy_name=""

# `harness/` travels whole: the breakages edit the fixtures, and a copy without
# the module beside them is a copy that fails for a different reason.
fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  mkdir -p "$dst"
  cp -R "$HARNESS" "$dst/harness"
  chmod +x "$dst/harness/bin/anywaye-contract" "$dst/harness/tests/self_test.sh" 2>/dev/null || true
  printf '%s' "$dst"
}

# edit <file> <old> <new> — a textual breakage that FAILS LOUDLY if the fixture has
# moved past it. A self-test that silently stops breaking anything is worse than
# no self-test, so an unmatched edit is an error here rather than a pass.
edit() {
  "$PY" - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(path, encoding="utf-8").read()
if old not in body:
    sys.exit(f"self_test: breakage no longer applies to {path}: {old!r} not found")
open(path, "w", encoding="utf-8").write(body.replace(old, new, 1))
PY
}

# run <dir> <service-fixture-name> [core] [harness args...]
#
# Core is the real tree by default, because the breakages are to a *service*.
# Breakage 14 needs the opposite, and passes a core of its own: a self-test that
# broke core's schemas to test a service rule would be testing something else,
# and one that edited the worktree it was invoked from would be a self-test that
# can fail twice.
run_harness() {
  local dir="$1" fixture="$2" core="${3:-$ROOT}"
  shift 3
  ( cd "$dir" && "$PY" "$dir/harness/anywaye_contract.py" \
      --core "$core" "$dir/harness/tests/fixtures/$fixture" "$@" 2>&1 )
}

# expect_red <label> <dir> <fixture> <rule-id>
#
# The strong form, and the only form used for a service rule: the named rule
# must appear in the output. "The gate went red" is a weak claim when sixteen
# checks can make it red — a breakage caught by the wrong check still reads as a
# pass, and the check it was written for can be dead code forever.
expect_red() {
  local label="$1" dir="$2" fixture="$3" want="$4" core="${5:-$ROOT}"
  shift 5 2>/dev/null || shift 4
  local out ec=0
  # `|| ec=$?` and not `&& ec=0 || ec=$?`: an assignment whose command
  # substitution fails has the *substitution's* status, and reading that as the
  # `||` branch's status reports the wrong thing. The failing run has to be
  # observed, not inferred.
  out="$(run_harness "$dir" "$fixture" "$core" "$@")" || ec=$?
  if [ "$ec" -eq 0 ]; then
    printf 'FAIL self_test: %s — the harness stayed GREEN\n' "$label"
    failures=$((failures + 1))
  elif printf '%s\n' "$out" | grep -q "FAIL $want "; then
    printf 'PASS self_test: %s — caught by `%s`\n' "$label" "$want"
  else
    printf 'FAIL self_test: %s — the harness went red, but NOT via `%s`\n' "$label" "$want"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  fi
}

# expect_refused <label> <dir> <fixture> <rule-id> <expected exit code>
#
# The distinction the whole packet turns on. A run that could not happen and a
# run that found nothing are different exit codes, and a harness that collapses
# them converts an unknown into a green badge — the defect that has bitten this
# fleet four times.
expect_refused() {
  local label="$1" dir="$2" fixture="$3" want="$4" want_code="$5" core="${6:-$ROOT}"
  shift 6 2>/dev/null || shift 5
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$core" "$@")" || ec=$?
  if [ "$ec" -ne "$want_code" ]; then
    printf 'FAIL self_test: %s — exit %s, expected %s\n' "$label" "$ec" "$want_code"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  elif ! printf '%s\n' "$out" | grep -q "FAIL $want "; then
    printf 'FAIL self_test: %s — exit %s but not via `%s`\n' "$label" "$ec" "$want"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  else
    printf 'PASS self_test: %s — refused with `%s`\n' "$label" "$want"
  fi
}

expect_green() {
  local label="$1" dir="$2" fixture="$3"
  shift 3
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$ROOT" "$@")" || ec=$?
  if [ "$ec" -eq 0 ]; then
    printf 'PASS self_test: %s — the harness is green on an unbroken tree\n' "$label"
  else
    printf 'FAIL self_test: %s — the harness is RED on an unbroken tree\n' "$label"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  fi
}

# expect_green_with_warning <label> <dir> <fixture> <warning-id>
#
# The other half of the argument, and the half that is easy to leave out. A
# warning that only ever appears next to a red proves nothing: a checker that
# says nothing is also a checker that passed. So each warning is asserted to be
# BOTH reported and non-fatal — exit 0, the id named, and the run still green.
# Seven of the thirteen repositories in the workspace declare no `exposes.api`,
# and this is the assertion that says that is a warning and not a red.
expect_green_with_warning() {
  local label="$1" dir="$2" fixture="$3" want="$4"
  local out ec=0
  out="$(run_harness "$dir" "$fixture" "$ROOT")" || ec=$?
  if [ "$ec" -ne 0 ]; then
    printf 'FAIL self_test: %s — a warning must not fail the run, exit %s\n' "$label" "$ec"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  elif ! printf '%s\n' "$out" | grep -q "WARN $want "; then
    printf 'FAIL self_test: %s — green, but not via `WARN %s`\n' "$label" "$want"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  else
    printf 'PASS self_test: %s — reported as `%s` and still exit 0\n' "$label" "$want"
    warnings=$((warnings + 1))
  fi
}

# expect_no_finding <label> <dir> <fixture> <rule-id-that-must-not-appear>
#
# The assertion that stops an honest skip from becoming a false accusation.
# Breakage 37 points one error response at a `$ref` the harness cannot read; the
# right answer is a warning saying so, not `openapi.errors-are-problems` printed
# against a document that is correct. A checker that guesses here would send a
# service owner to fix something that is not broken, which is worse than a
# checker that checks nothing — and it is invisible in a red/green count.
expect_no_finding() {
  local label="$1" dir="$2" fixture="$3" unwanted="$4"
  local out
  out="$(run_harness "$dir" "$fixture" "$ROOT")" || true
  if printf '%s\n' "$out" | grep -q "$unwanted"; then
    printf 'FAIL self_test: %s — %s was reported for something the harness could not read\n' \
      "$label" "$unwanted"
    printf '%s\n' "$out" | sed 's/^/       /'
    failures=$((failures + 1))
  else
    printf 'PASS self_test: %s — %s was not guessed at\n' "$label" "$unwanted"
  fi
}

printf -- '-- self_test: a conformance tool that cannot fail is a report\n'

# The control. If the unbroken tree is already red, every breakage below proves
# nothing, so this runs first and the whole run is meaningless without it.
base="$(fresh_copy control)"
expect_green 'the control: the conforming fixture' "$base" conforming

# The second control, and it exists because of the eight breakages at the end.
# `conforming` is deliberately the smallest document that satisfies every rule the
# harness could decide — one GET, one 200, no error path, no pagination, no POST.
# That makes it the right control for the rules that existed when it was written
# and the **wrong** fixture for the readable half: `openapi.errors-are-problems`
# cannot fail in a document with no non-2xx response, so a breakage aimed at it
# here would be proving that a rule cannot fire.
openapi_base="$(fresh_copy control-openapi)"
expect_green 'the control: the conforming OpenAPI fixture' "$openapi_base" conforming-openapi

# The third control, and the one that earns its place by what it CONTAINS. A
# green over a fixture that declares no postgres image proves nothing about a
# rule about postgres images — the same reason `conforming-openapi` exists beside
# `conforming`. This one carries all three declaration shapes and, in the same
# file, the four shapes that must NOT be read as a reference: a DSN carrying a
# password, a `postgres` used as a database user, a `postgres` used as a
# migration driver name, and a container run naming redis. A scanner that read
# any of those as an image reference would be making four false accusations on
# the day it landed, and `expect_green` here is the assertion that it does not.
pin_base="$(fresh_copy control-postgres)"
expect_green 'the control: the conforming postgres-pin fixture, DSNs and all' \
  "$pin_base" conforming-postgres
expect_green 'the control: the conforming exception fixture, a different major DECLARED' \
  "$(fresh_copy control-postgres-exception)" conforming-postgres-exception

# 1. The obvious one, and the reason the others are worth having: a name in the
#    wrong case is a `pattern` violation, and it must be reported as one.
breakages=$((breakages + 1))
one="$(fresh_copy schema-name)"
edit "$one/harness/tests/fixtures/conforming/anywaye.yml" 'name: harness-fixture' 'name: Harness-Fixture'
expect_red 'breakage 1: a service name in the wrong case' "$one" conforming 'manifest.schema'

# 2. A dependency version constraint without a patch. A missing patch silently
#    widens the range, and it is the kind of thing that lands with a typo.
breakages=$((breakages + 1))
two="$(fresh_copy schema-core-range)"
edit "$two/harness/tests/fixtures/conforming/anywaye.yml" 'core: ^0.2.0' 'core: ^0.2'
expect_red 'breakage 2: a core constraint with no patch component' "$two" conforming 'manifest.schema'

# 3. An HTTPS remote. The schema pins SSH, and an HTTPS remote for a anywaye repo
#    is a policy violation that would otherwise be caught in review of a diff
#    nobody reads closely.
breakages=$((breakages + 1))
three="$(fresh_copy schema-https-remote)"
edit "$three/harness/tests/fixtures/conforming/anywaye.yml" \
  'url: git@github.com:anywaye/harness-fixture.git' \
  'url: https://github.com/anywaye/harness-fixture.git'
expect_red 'breakage 3: an HTTPS remote' "$three" conforming 'manifest.schema'

# 4. The cross-field rule core cannot put in a schema, because JSON Schema
#    cannot compare two properties of one instance: another service's event type
#    published here.
breakages=$((breakages + 1))
four="$(fresh_copy convention-own-prefix)"
edit "$four/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - courier.email.queued'
expect_red 'breakage 4: a published type prefixed with another service' "$four" conforming 'event.own-prefix'

# 5. Self-consume. Unreachable from a single value — the publisher-prefix rule
#    rejects publishing anything not prefixed with this service's own name, so
#    the type has to be both correctly prefixed *and* correctly catalogued
#    before consuming it is the only thing wrong. The fixture already consumes
#    `identity.user.created`; publishing it here makes that one fact wrong
#    twice, and only one of the two is a self-consume.
breakages=$((breakages + 1))
five="$(fresh_copy convention-self-consume)"
edit "$five/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - identity.user.created'
expect_red 'breakage 5: a service consuming its own events' "$five" conforming 'event.no-self-consume'

# 6. A subscription to a type nobody publishes. It ships silently, and it fails
#    at run time on someone else's deploy — the rule exists for that reason.
breakages=$((breakages + 1))
six="$(fresh_copy convention-unknown-consumed)"
edit "$six/harness/tests/fixtures/conforming/anywaye.yml" \
  '  - identity.user.created' '  - identity.no_such_event.ever_happened'
expect_red 'breakage 6: consuming an event type the catalog does not have' \
  "$six" conforming 'event.unknown-consumed'

# 7. The other half of the catalog fact, and the one with the opposite failure
#    mode: a type published here that nothing in the platform subscribes to.
breakages=$((breakages + 1))
seven="$(fresh_copy convention-unknown-published)"
edit "$seven/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - harness-fixture.no_such_thing.happened'
expect_red 'breakage 7: publishing an event type the catalog does not have' \
  "$seven" conforming 'event.unknown-published'

# 8. A published type with no payload schema — and this breakage is where two
#    rules turned out to be structurally coupled, which is worth the two lines
#    it cost to find out.
#
#    `event.payload-schema-missing` cannot be reached on its own. A PUBLISHED type
#    always has a payload schema — core's own suite asserts that over fleet.yml's
#    `events` — so a published type that lacks one is necessarily a type the
#    catalog does not list, and `event.unknown-published` fires with it. (The
#    catalog does hold types with no schema, nine of them: rows for events no
#    service ships yet. That is the `cataloguedOnly` half of the story and it
#    does not weaken the coupling, because none of them is published.) Publishing
#    somebody else's type instead, which is the obvious way to try, trips
#    `event.own-prefix` instead and never reaches the payload check.
#
#    So both rules are asserted here, and the coupling is recorded in
#    `harness/rules.json`: a future core that catalogs a type without a payload
#    schema would make this breakage reach one rule alone, and
#    `test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema`
#    is what would notice.
breakages=$((breakages + 1))
eight="$(fresh_copy payload-schema-missing)"
edit "$eight/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - harness-fixture.no_such_thing.happened'
expect_red 'breakage 8: a published type with no payload schema' \
  "$eight" conforming 'event.payload-schema-missing'
expect_red 'breakage 8: the same breakage, and the rule it is coupled to' \
  "$eight" conforming 'event.unknown-published'

# 9. `exposes.api` pointing at a file that is not there. The schema pins the
#    shape of the path and cannot see the filesystem, so this is a rule in the
#    harness and it is the rule a `cafe dev` path error breaks.
breakages=$((breakages + 1))
nine="$(fresh_copy api-file-missing)"
edit "$nine/harness/tests/fixtures/conforming/anywaye.yml" 'api: openapi/v1.yaml' 'api: openapi/renamed.yaml'
expect_red 'breakage 9: exposes.api pointing at a file that does not exist' \
  "$nine" conforming 'manifest.api-file-missing'

# 10. A second prefix, by *adding* one. The first version of this breakage
#     renamed `/v1/widgets` to `/v2/widgets`, and the harness stayed green —
#     correctly, because a rename leaves exactly one prefix behind, and the rule
#     is about two. A rename is the mutation a careless reviewer would not see
#     either, and it is the one a *count* comparison cannot catch either way:
#     courier's lesson is that a count is the wrong shape of assertion, and
#     breakage 11 is the other half of that lesson.
breakages=$((breakages + 1))
ten="$(fresh_copy openapi-two-prefixes)"
edit "$ten/harness/tests/fixtures/conforming/openapi/v1.yaml" \
  'paths:
  /v1/widgets:' \
  'paths:
  /v2/widgets:
    get:
      operationId: listWidgetsRenamed
      responses:
        "200":
          description: A page of widgets, under a second prefix.
  /v1/widgets:'
expect_red 'breakage 10: a second /vN prefix in one document' "$ten" conforming 'openapi.one-version-prefix'

# 11. The path prefix removed entirely, which is a different rule from the one
#     above and a different mistake: an endpoint that was never versioned.
breakages=$((breakages + 1))
eleven="$(fresh_copy openapi-unversioned-path)"
edit "$eleven/harness/tests/fixtures/conforming/openapi/v1.yaml" \
  '  /v1/widgets:' '  /widgets:'
expect_red 'breakage 11: a path with no /vN prefix' "$eleven" conforming 'openapi.paths-are-versioned'

# 12. `info.version` deleted. The other half of core's sync rule, and the only
#     signal a consumer has for "nothing moved" versus "the document was
#     regenerated".
breakages=$((breakages + 1))
twelve="$(fresh_copy openapi-no-info-version)"
edit "$twelve/harness/tests/fixtures/conforming/openapi/v1.yaml" '  version: 1.0.0' '  summary: no version here'
expect_red 'breakage 12: info.version removed' "$twelve" conforming 'openapi.info-version'

# 13. The document downgraded to 3.0. 3.1 is what makes `null` a type rather
#     than a keyword that changes meaning, and half of core's payload schemas
#     cannot be expressed in 3.0.
breakages=$((breakages + 1))
thirteen="$(fresh_copy openapi-30)"
edit "$thirteen/harness/tests/fixtures/conforming/openapi/v1.yaml" 'openapi: 3.1.0' 'openapi: 3.0.3'
expect_red 'breakage 13: an OpenAPI 3.0 document' "$thirteen" conforming 'openapi.document-is-31'

# 14. The pin, and the drift it exists for: one byte appended to one schema.
#     This is the smallest possible drift and the one a re-vendor fan-out
#     produces.
#
#     The first version of this breakage edited `$ROOT/schemas/` and moved the
#     file aside, which is two mistakes: it mutated the worktree the script was
#     invoked from, and it left core with no manifest schema at all, so the run
#     refused for the wrong reason and proved nothing. Core is copied here
#     instead, and the pin is the digest of the *real* tree — which is also the
#     receipt that a copy of core's contract surface digests identically to
#     core, so a laptop and a runner agree about what they pinned.
#
#     The expected verdict is a *violation* (exit 1), not a refusal: core was
#     found and read in full; it is simply not the core that was pinned. A
#     harness that refused here would be saying "I could not check", and a
#     service owner would spend an afternoon on a checkout problem they do not
#     have.
breakages=$((breakages + 1))
fourteen="$(fresh_copy digest-mismatch)"
mkdir -p "$fourteen/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$fourteen/core/"
# `VERSION` too, for the same reason the synthetic core in the suite carries it:
# a core checkout with no published version is refused, not checked, and this
# breakage is about the digest. Without it this breakage would still go red —
# via `core.version-absent` instead — and a breakage caught by the wrong rule is
# exactly what `expect_red` exists to reject.
cp "$ROOT/VERSION" "$fourteen/core/VERSION"
digest="$("$PY" - "$ROOT" <<'PY'
import pathlib
import sys

sys.path.insert(0, sys.argv[1] + "/harness")
import anywaye_contract

print(anywaye_contract.contract_digest(pathlib.Path(sys.argv[1])))
PY
)"
printf '\n' >> "$fourteen/core/schemas/anywaye.manifest.schema.json"
expect_red 'breakage 14: a one-byte change to core, against a pinned digest' \
  "$fourteen" conforming 'core.digest-mismatch' "$fourteen/core" --expect-digest "$digest"

# 15. The refusal, and the rule this whole packet exists for: a directory that
#     is not a core checkout must be refused, never accepted. The exit code is
#     2 and the check is on the code, because a harness that exits 1 here has
#     turned "I could not check" into "you have a problem" — which a service
#     owner will spend an afternoon on.
breakages=$((breakages + 1))
fifteen="$(fresh_copy not-a-checkout)"
mkdir -p "$fifteen/not-core/schemas"
printf 'not core\n' > "$fifteen/not-core/README.md"
out="$( "$PY" "$fifteen/harness/anywaye_contract.py" --core "$fifteen/not-core" \
  "$fifteen/harness/tests/fixtures/conforming" 2>&1 )" && ec=0 || ec=$?
if [ "$ec" -eq 2 ] && printf '%s\n' "$out" | grep -q 'FAIL core.not-a-checkout '; then
  printf 'PASS self_test: breakage 15: a directory that is not a core checkout — refused with `%s`\n' 'core.not-a-checkout'
else
  printf 'FAIL self_test: breakage 15 — expected exit 2 via `core.not-a-checkout`, got %s\n' "$ec"
  printf '%s\n' "$out" | sed 's/^/       /'
  failures=$((failures + 1))
fi

# 16. No core at all, with an empty environment so nothing can point at one.
#     This is guard's Redis tier, muse's MUSE_CORE_SCHEMAS tier, identity's
#     TEST_DATABASE_URL tier and darkroom's --ignored tests, as one assertion.
breakages=$((breakages + 1))
sixteen="$(fresh_copy core-absent)"
out="$( cd "$sixteen" && env -i "$PY" "$sixteen/harness/anywaye_contract.py" \
  --core "$sixteen" "$sixteen/harness/tests/fixtures/conforming" 2>&1 )" && ec=0 || ec=$?
if [ "$ec" -eq 2 ] && printf '%s\n' "$out" | grep -q 'FAIL core.not-a-checkout '; then
  printf 'PASS self_test: breakage 16: core absent, environment empty — refused with `%s`\n' 'core.not-a-checkout'
else
  printf 'FAIL self_test: breakage 16 — expected exit 2, got %s\n' "$ec"
  printf '%s\n' "$out" | sed 's/^/       /'
  failures=$((failures + 1))
fi

# 17. A YAML construct outside the declared subset, refused rather than guessed.
#     The fixture is legal YAML — a multi-line plain scalar folds to one line and
#     PyYAML reads it without complaint — so a harness that folded it would
#     validate a document nobody wrote and report a schema error against a value
#     it invented. Refusal is exit 2; a violation would be exit 1, and the
#     difference is the difference between "fix your manifest" and "fix your
#     tooling".
breakages=$((breakages + 1))
seventeen="$(fresh_copy yaml-refused)"
expect_refused 'breakage 17: a legal YAML construct outside the declared subset' \
  "$seventeen" unsupported-yaml 'yaml.unsupported' 2

# 18. Core named nowhere at all: no `--core`, and an environment with nothing
#     in it. `core.absent` is a different rule from `core.not-a-checkout`, and it
#     is the one the fleet has actually been bitten by — muse's
#     `MUSE_CORE_SCHEMAS` tier, pantry's `PANTRY_ANYWAYE_ROOT` and the other two
#     all *skipped* rather than failed, and all of them were looking for core
#     and not finding it.
#
#     This breakage was missing until
#     `test_the_harness_proves_it_can_fail_by_breaking_itself` demanded the
#     string `core.absent` in this script and found only
#     `core.not-a-checkout`, which is the rule for a path that was given and was
#     wrong. A green self-test that never exercised the rule would have been a
#     self-test with a hole exactly where the fleet keeps getting hurt.
breakages=$((breakages + 1))
eighteen="$(fresh_copy core-never-named)"
out="$( cd "$eighteen" && env -i "$PY" "$eighteen/harness/anywaye_contract.py" \
  "$eighteen/harness/tests/fixtures/conforming" 2>&1 )" && ec=0 || ec=$?
if [ "$ec" -eq 2 ] && printf '%s\n' "$out" | grep -q 'FAIL core.absent '; then
  printf 'PASS self_test: breakage 18: core named nowhere, environment empty — refused with `%s`\n' 'core.absent'
else
  printf 'FAIL self_test: breakage 18 — expected exit 2 via `core.absent`, got %s\n' "$ec"
  printf '%s\n' "$out" | sed 's/^/       /'
  failures=$((failures + 1))
fi

# 19. `paths: {}`. The rule that exists because two empty sets agree: a
#     document with no operations is not a contract, and a reader that returns
#     an empty collection instead of complaining lets a service delete its whole
#     HTTP surface and see a green build. courier's `OpenAPIPaths` refuses rather
#     than under-reads for exactly this, and it is the single most likely way a
#     conformance tool ends up agreeing with a service that agreed with nothing.
breakages=$((breakages + 1))
nineteen="$(fresh_copy openapi-no-paths)"
edit "$nineteen/harness/tests/fixtures/conforming/openapi/v1.yaml" \
  'paths:
  /v1/widgets:
    get:
      operationId: listWidgets
      responses:
        "200":
          description: A page of widgets.' 'paths: {}'
expect_red 'breakage 19: an OpenAPI document with no paths' "$nineteen" conforming 'openapi.has-paths'

# 20. No manifest at all. `caf`'s linter returns an error rather than an empty
#     report for exactly this reason, and the reason is in the refusal itself: an
#     empty report's `OK` is indistinguishable from the `OK` of a repository
#     nobody looked at. A gate pointed at the wrong path is the most common way a
#     conformance check passes without having run, and the last two breakages
#     are all versions of it.
breakages=$((breakages + 1))
twenty="$(fresh_copy manifest-absent)"
mv "$twenty/harness/tests/fixtures/conforming/anywaye.yml" \
   "$twenty/harness/tests/fixtures/conforming/anywaye.yml.moved"
expect_refused 'breakage 20: a service root with no anywaye.yml' \
  "$twenty" conforming 'service.manifest-absent' 2

# 21. The SLO rules. Eight breakages, one per rule, and each one names the rule it
#     must be caught by rather than merely proving that something went red — with
#     twenty-eight checks in this script, "the gate went red" is a claim about
#     almost nothing.
#
#     Breakages 23 and 24 are the two denylists, and both are written as they
#     arrived rather than as the queries they eventually became: a service adds
#     `tenant_id` or a memory limit to its **declared labels** first and to its
#     queries second. The first version of `_denylisted` scanned only the
#     queries, so both of these came back as `slo.sli-canonical` — a true
#     statement about a consequence, reported in place of the mistake. A rule
#     that names the wrong thing is a rule nobody acts on, and this is the
#     second time in this repository that only running the thing at its fixtures
#     found it.
#
#     Breakages 22-25 are the ones the rulings name: the query with no
#     `{{.window}}` (the highest-value check in the file, and one Sloth does not
#     make), a per-tenant dimension, an infrastructure SLO, and a `low` SLO that
#     pages. The last of those is enforced in a SCHEMA, and it is here anyway:
#     a rule that lives in `schemas/` is still a rule the harness can be proved
#     able to report, and the breakage is how we know the file it lives in is the
#     file the harness reads.
breakages=$((breakages + 1))
one="$(fresh_copy slo-window-token)"
edit "$one/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  '[{{.window}}]))'"'"'
        error_query' '[1h]))'"'"'
        error_query'
expect_red 'breakage 21: an SLI query with no {{.window}} token' "$one" conforming 'slo.window-token'

breakages=$((breakages + 1))
two="$(fresh_copy slo-unknown-metric)"
edit "$two/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  'http_server_request_duration_seconds_count{http_route' \
  'http_server_request_duration_seconds_count_secrets{http_route'
expect_red 'breakage 22: an SLI query on a metric the catalogue does not name' \
  "$two" conforming 'slo.unknown-metric'

breakages=$((breakages + 1))
three="$(fresh_copy slo-unbounded-dimension)"
edit "$three/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  '      http_route: /v1/widgets' \
  '      http_route: /v1/widgets
      tenant_id: acc_01J9Z8QK5M4N7P2R3T6V8W9X0A'
expect_red 'breakage 23: a per-tenant dimension in an SLO' "$three" conforming 'slo.no-unbounded-dimension'

breakages=$((breakages + 1))
four="$(fresh_copy slo-infrastructure-slo)"
edit "$four/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  '      http_route: /v1/widgets' \
  '      http_route: /v1/widgets
      container_memory_limit_bytes: "536870912"'
expect_red 'breakage 24: an SLO scoped by a memory limit' \
  "$four" conforming 'slo.no-infrastructure-slo'

breakages=$((breakages + 1))
five="$(fresh_copy slo-tier-pages-on-low)"
# Not a typo: a `low` SLO with a page alert, which is what a service writes when
# it copies a `high` one and edits the tier last.
edit "$five/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  '      page_alert:
        disable: true' \
  '      page_alert:
        disable: false'
expect_red 'breakage 25: a low SLO that pages' "$five" conforming 'slo.schema'

breakages=$((breakages + 1))
six="$(fresh_copy slo-window-override)"
edit "$six/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  '    labels:
      http_route: /v1/widgets' \
  '    windows:
      - window: 5m
        factor: 15
    labels:
      http_route: /v1/widgets'
expect_red 'breakage 26: a service carrying its own burn-rate windows' \
  "$six" conforming 'slo.window-override'

breakages=$((breakages + 1))
seven="$(fresh_copy slo-not-canonical)"
# The mistake that looks like diligence: the same ratio, spelled the way the
# author typed it. The composition is compared as a string, so this is caught.
edit "$seven/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
  'sum(rate(http_server_request_duration_seconds_count{http_route="/v1/widgets",service_name="harness-fixture"}[{{.window}}]))' \
  'sum(rate( http_server_request_duration_seconds_count{service_name="harness-fixture", http_route="/v1/widgets"}[{{.window}}] ))'
expect_red 'breakage 27: an SLI that means the right thing and is spelled wrongly' \
  "$seven" conforming 'slo.sli-canonical'

breakages=$((breakages + 1))
eight="$(fresh_copy slo-duplicate-name)"
cp "$eight/harness/tests/fixtures/conforming/slos/harness-fixture.yaml" \
   "$eight/harness/tests/fixtures/conforming/slos/copied.yaml"
expect_red 'breakage 28: the same SLO declared in two files' "$eight" conforming 'slo.duplicate-name'

# 29-37. The readable half of the HTTP contract: docs/openapi-conventions.md's
#     error envelope, pagination envelope and idempotency, decided from a
#     document. Nine breakages for eight rules, because `openapi.page-envelope`
#     has two independently reachable halves and a reader is owed both.
#
#     All nine aim at `conforming-openapi`, which is the control above. The
#     mutations are the mistakes the conventions were written about rather than
#     typos: the error schema defined and attached to nothing, a code reworded
#     without the `type` it is the last segment of, a reserved code at the wrong
#     status, `trace_id` demoted from `required` to merely declared, `limit`
#     renamed `offset`, a cursor renamed `before`, the envelope renamed, the
#     idempotency header removed, and the 409 removed while the header stays.
#
#     `identity`'s audit log is what breakage 31 imitates: `limit` and `before`
#     declared, `{"entries": …, "next": …}` returned. It is a correct pagination
#     design that is not core's, and this is the rule that says so by name.
OPENAPI_FIXTURE='harness/tests/fixtures/conforming-openapi/openapi/v1.yaml'

breakages=$((breakages + 1))
one="$(fresh_copy openapi-no-problem-media)"
edit "$one/$OPENAPI_FIXTURE" \
  '      description: No authenticated caller.
      content:
        application/problem+json:' \
  '      description: No authenticated caller.
      content:
        application/json:'
expect_red 'breakage 29: a 401 that is not application/problem+json' \
  "$one" conforming-openapi 'openapi.errors-are-problems'

breakages=$((breakages + 1))
two="$(fresh_copy openapi-code-not-type-slug)"
edit "$two/$OPENAPI_FIXTURE" '            code: unauthorized' '            code: unauthenticated'
expect_red 'breakage 30: a `code` that is no longer the last segment of `type`' \
  "$two" conforming-openapi 'openapi.problem-code-matches-type'

breakages=$((breakages + 1))
three="$(fresh_copy openapi-reserved-code-wrong-status)"
edit "$three/$OPENAPI_FIXTURE" '            status: 422' '            status: 400'
expect_red 'breakage 31: a reserved code at a status it is not reserved for' \
  "$three" conforming-openapi 'openapi.reserved-error-codes'

breakages=$((breakages + 1))
four="$(fresh_copy openapi-no-trace-id)"
edit "$four/$OPENAPI_FIXTURE" \
  '      required: [type, title, status, detail, code, trace_id]' \
  '      required: [type, title, status, detail, code]'
expect_red 'breakage 32: a problem schema that declares trace_id but does not require it' \
  "$four" conforming-openapi 'openapi.problem-has-trace-id'

breakages=$((breakages + 1))
five="$(fresh_copy openapi-offset-parameter)"
edit "$five/$OPENAPI_FIXTURE" '      name: limit' '      name: offset'
expect_red 'breakage 33: an `offset` query parameter beside a cursor' \
  "$five" conforming-openapi 'openapi.no-offset-pagination'

breakages=$((breakages + 1))
six="$(fresh_copy openapi-no-cursor)"
edit "$six/$OPENAPI_FIXTURE" '      name: cursor' '      name: before'
expect_red 'breakage 34: a paginated operation that takes no cursor' \
  "$six" conforming-openapi 'openapi.page-envelope'

breakages=$((breakages + 1))
seven="$(fresh_copy openapi-no-page-envelope)"
edit "$seven/$OPENAPI_FIXTURE" \
  '        page:
          type: object
          required: [next_cursor, has_more]
          properties:
            next_cursor:' \
  '        next:
          type: object
          required: [next_cursor, has_more]
          properties:
            next_cursor:'
expect_red 'breakage 35: a page envelope whose `page` is called `next`' \
  "$seven" conforming-openapi 'openapi.page-envelope'

breakages=$((breakages + 1))
eight="$(fresh_copy openapi-no-idempotency-key)"
# `X-Idempotency-Key`, not the removal of the parameter. Both are the same rule,
# and the prefixed one is the mistake this convention has to survive in practice:
# every other header in the document is prefixed `X-`, so the author matched the
# local style, and it is still not the header core specifies — which is the
# point. It also proves the rule compares the name rather than looking for
# something header-shaped.
edit "$eight/$OPENAPI_FIXTURE" '      name: Idempotency-Key' '      name: X-Idempotency-Key'
expect_red 'breakage 36: a mutating POST whose key is X-Idempotency-Key' \
  "$eight" conforming-openapi 'openapi.idempotency-key'

breakages=$((breakages + 1))
nine="$(fresh_copy openapi-no-idempotency-conflict)"
# The status key, not the whole line, and the mutation is the mistake that looks
# like diligence: the author kept the header and the prose and wrote 400,
# because "the client sent something wrong" is what a reused key feels like from
# the outside. It is a 409, and the reason is that the key *was* accepted.
edit "$nine/$OPENAPI_FIXTURE" '"409"' '"400"'
expect_red 'breakage 37: a POST that takes the key and declares no 409' \
  "$nine" conforming-openapi 'openapi.idempotency-conflict-documented'

# 38. The BASE of `type`, and the reason it is a rule of its own rather than a
#     half of breakage 30. That one changed the `code` and left `type` alone, so
#     the slug stopped agreeing with the code. This one moves the host and leaves
#     the slug perfectly correct in both fields: `code: unauthorized` beside
#     `type: https://errors.anywaye.com/unauthorized` passes
#     `openapi.problem-code-matches-type` and dereferences to nothing. 292
#     references across the fleet read a host that was never served and is not
#     redirected, which is exactly the defect that looks like a pass.
#
#     PLAN §3 L3 swept them to `https://docs.anywaye.com/errors/<code>`, and
#     `openapi.problem-type-base` is the rule that keeps the sweep swept. The
#     control above it — the same fixture at the new base, green — is the other
#     half: a rule that only ever goes red is not proved either.
#
#     The description, not the value: the fixture carries the old host in a
#     `description` on line 117 and the schema's own prose says it must. The
#     schema is not an example, so the rule reads only examples — mutating the
#     prose instead would prove nothing and would also leave the document
#     describing a base it forbids.
breakages=$((breakages + 1))
thirty_eight="$(fresh_copy openapi-type-base-retired-host)"
edit "$thirty_eight/$OPENAPI_FIXTURE" \
  'type: https://docs.anywaye.com/errors/unauthorized' \
  'type: https://errors.anywaye.com/unauthorized'
expect_red "breakage 38: a problem \`type\` at the retired host" \
  "$thirty_eight" conforming-openapi 'openapi.problem-type-base'

# 39. The same rule's other half: a base-relative `type` with nothing after it.
#     `<base>/<code>` is the whole URI, and a trailing slash is a code-less
#     identifier — a client that dereferences it lands on an index and has to
#     guess which of nine reserved codes this one was.
breakages=$((breakages + 1))
thirty_nine="$(fresh_copy openapi-type-base-no-code)"
edit "$thirty_nine/$OPENAPI_FIXTURE" \
  'type: https://docs.anywaye.com/errors/unauthorized' \
  'type: https://docs.anywaye.com/errors/'
expect_red "breakage 39: a problem \`type\` that is the base and no code" \
  "$thirty_nine" conforming-openapi 'openapi.problem-type-base'

# The three warnings, asserted green. A warning only ever seen next to a red
# proves nothing — a checker that says nothing also passed — so each is asserted
# to be reported AND non-fatal. `expect_green_with_warning` checks both halves,
# and the counts are reported separately in the summary because a reader asking
# "did this packet prove anything?" wants "9 reds and 3 greens", not "12".
#
# 38. No `exposes.api` and no document at all. core itself is in this position,
#     and seven of the thirteen repositories in the workspace are.
warning_case="$(fresh_copy warn-no-document)"
edit "$warning_case/harness/tests/fixtures/conforming-openapi/anywaye.yml" \
  'exposes:
  api: openapi/v1.yaml
' ''
rm -rf "$warning_case/harness/tests/fixtures/conforming-openapi/openapi"
expect_green_with_warning 'warning 38: a manifest with no exposes.api and no document' \
  "$warning_case" conforming-openapi 'openapi.no-document'

# 39. A document nobody declared. guard is the case in the workspace today, and
#     this is the finding that makes it visible: eight of its non-2xx responses
#     carry no `application/problem+json`, and without this warning a run over
#     guard would print `OK` over a document it never opened.
warning_case="$(fresh_copy warn-not-declared)"
edit "$warning_case/harness/tests/fixtures/conforming-openapi/anywaye.yml" \
  'exposes:
  api: openapi/v1.yaml
' ''
expect_green_with_warning 'warning 39: a document checked in that exposes.api does not name' \
  "$warning_case" conforming-openapi 'openapi.not-declared'

# 40. A pointer the harness cannot read, and the assertion that matters most in
#     this file: it produces the warning and NOT `openapi.errors-are-problems`.
#     `edit` replaces one occurrence, so this moves the list endpoint's 401 and
#     not the POST's — one unread response is enough, and moving all three would
#     prove less about the single case.
warning_case="$(fresh_copy warn-unresolved-ref)"
edit "$warning_case/$OPENAPI_FIXTURE" '#/components/responses/Unauthorized' './errors.yaml#/Unauthorized'
expect_green_with_warning 'warning 40: a $ref the harness cannot follow' \
  "$warning_case" conforming-openapi 'openapi.unresolved-ref'
expect_no_finding 'warning 40: and the unread response is not accused of anything' \
  "$warning_case" conforming-openapi 'openapi.errors-are-problems'

# 41-44. `compose.postgres-pin` and the tag it compares against. The claim is
#     that every postgres image reference in a repository resolves to one tag, so
#     a breakage has to break one of two things: the agreement between two
#     declarations, or the agreement with what core declares. Each below does one
#     of those, and each names the rule it must be caught by.
#
#     The control is `conforming-postgres`, and it carries all three declaration
#     shapes — a compose file, a workflow `services:` block, and a
#     `docker run` line — so that a breakage aimed at the workflow scan is not
#     aimed at a fixture with no workflow in it. That fixture also carries the
#     four shapes that must NOT be read as a reference: a DSN, a `postgres` used
#     as a database user, a `postgres` used as a migration driver name, and a
#     `redis:` container run. `expect_green` on the control is therefore the
#     assertion that the scanner does not accuse any of them, and it is why the
#     control is asserted before the breakages rather than only implied by them.
#
#     **41 is identity's live shape**, not an invented one: identity's compose
#     says `postgres:17-alpine` and its CI says `postgres:17.11-alpine`, and its
#     own comment admits it. The mutation is the whole point of the rule — a
#     developer and a runner on different database builds.
PIN_FIXTURE='harness/tests/fixtures/conforming-postgres'

breakages=$((breakages + 1))
forty_one="$(fresh_copy postgres-divergent)"
edit "$forty_one/$PIN_FIXTURE/ci/ci.yml" \
  '        image: postgres:17-alpine' '        image: postgres:17.11-alpine'
expect_red 'breakage 41: a CI services block that pins a different tag from the compose file' \
  "$forty_one" conforming-postgres 'compose.postgres-pin'

breakages=$((breakages + 1))
forty_two="$(fresh_copy postgres-undeclared)"
edit "$forty_two/$PIN_FIXTURE/docker-compose.yml" \
  '    image: postgres:17-alpine' '    image: postgres:18-alpine'
expect_red 'breakage 42: a tag core does not declare' \
  "$forty_two" conforming-postgres 'compose.postgres-pin'

# 43. The one that goes after the escape hatch rather than the rule. An
#     exception for the tag core ALREADY declares grants nothing today and hides
#     the next change to POSTGRES_TAG behind a line that looks reviewed — and a
#     rule that accepted it would let a repository opt out of a future decision it
#     never agreed to. The conforming exception fixture is the control for the
#     positive case, and this breakage is the negative one on the same file, so
#     the two halves of the mechanism are proved from one fixture.
breakages=$((breakages + 1))
forty_three="$(fresh_copy postgres-exception-for-the-standard)"
edit "$forty_three/harness/tests/fixtures/conforming-postgres-exception/postgres-pin-exceptions.yaml" \
  '    image: postgres:16-alpine' '    image: postgres:17-alpine'
expect_red 'breakage 43: an exception declared for the tag core already publishes' \
  "$forty_three" conforming-postgres-exception 'compose.postgres-pin'

# 44. The refusal. A core that publishes no tag has left the rule with nothing
#     to compare against, and the run must exit 2 rather than pass: this is
#     `core.version-absent`'s argument applied to the second published fact, and
#     a run that cannot find the standard has converted an unknown into a pass.
#     Core is copied rather than mutated, for the reason breakage 14 gives.
breakages=$((breakages + 1))
forty_four="$(fresh_copy postgres-tag-absent)"
mkdir -p "$forty_four/notag"
cp -R "$ROOT/schemas" "$ROOT/docs" "$forty_four/notag/"
cp "$ROOT/VERSION" "$forty_four/notag/VERSION"
expect_refused 'breakage 44: a core that publishes no postgres tag' \
  "$forty_four" conforming-postgres 'compose.postgres-tag-absent' 2 "$forty_four/notag"

# 45. The scan bound, and the assertion that matters most about it. A compose
#     file three directories down is not read — the bound exists so the walk does
#     not enter `node_modules` — and the honest answer is a green that SAYS what
#     it did not read. The first version of the walk stopped descending at the
#     bound, which meant this file was never found, which meant the warning could
#     not fire, which meant a bound that could hide a pin was silent. This case
#     is the proof that it is not silent any more, and `expect_no_finding` is the
#     other half: the unread file must not be accused of anything either.
warning_case="$(fresh_copy warn-compose-below-bound)"
mkdir -p "$warning_case/$PIN_FIXTURE/a/b/c"
mv "$warning_case/$PIN_FIXTURE/docker-compose.yml" \
   "$warning_case/$PIN_FIXTURE/a/b/c/docker-compose.yml"
expect_green_with_warning 'warning 45: a compose file below the bound the pin rule scans' \
  "$warning_case" conforming-postgres 'compose.pin-scan-truncated'
expect_no_finding 'warning 45: and the unread compose file is not accused of anything' \
  "$warning_case" conforming-postgres 'compose.postgres-pin'

printf '\n'printf '\n'
if [ "$failures" -ne 0 ]; then
  printf 'FAIL: self_test — %s of %s breakages the harness did not catch.\n' "$failures" "$breakages"
  printf 'FAIL: self_test — %s warning case(s) proved green.\n' "$warnings"
  exit 1
fi
# The wording of this line is a CONTRACT with the "the self-test said what it
# did" step in ci/ci.yml, which greps the log for the literal
# `PASS: self_test — N breakages went red` to compare the count claimed here with
# the number of breakage assertions above it. That step's grep used to ask for
# `all N breakages went red`, which this line has never printed — so the guard was
# unsatisfiable and the step failed on every run, with a message blaming a
# self-test that had passed. `test_the_ci_self_test_step_reads_the_phrase_the_
# footer_prints` in tests/test_specs.py now greps BOTH files for the other's
# literal, so the two cannot drift apart again. Change one and the suite goes red.
printf 'PASS: self_test — %s breakages went red naming their rule, %s warning cases stayed green, and every control was green first.\n' "$breakages" "$warnings"

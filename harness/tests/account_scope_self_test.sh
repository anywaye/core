#!/usr/bin/env bash
#
# account_scope_self_test.sh — the checker's proof that it is able to fail.
#
#   bash harness/tests/account_scope_self_test.sh
#
# WHAT THIS IS FOR
#
# A checker that has only ever said "clean" is not a checker; it is a comment with
# a shebang. On the fleet as it stands this checker's verdict is
# `account-scope.declaration-missing` nine times out of nine, which is the CORRECT
# verdict and is also — exactly like the db-isolation guard's `0 failure(s)` — a
# line that reads identically whether the checker can detect anything or not. So:
# take a fixture with a known shape, copy it, break exactly one thing in each
# copy, and assert the checker goes red each time NAMING the finding that check
# was written for. "Something went red" is a weaker claim and it is the one that
# decays silently.
#
# The shape is harness/tests/db_isolation_self_test.sh's, for tenancy_self_test.sh's
# reasons: a control on the unbroken fixture FIRST (without it every red below
# proves nothing, because a checker that refused everything would satisfy all of
# them), a fresh throwaway copy per case so one can never mask the next, and a
# non-zero exit if any breakage stayed green. Nothing committed is a deliberately
# broken service; the breakages are edits applied here.
#
# ------------------------------------------------------------------------------
# THE CASES, AND WHY EACH IS A REAL DEFECT RATHER THAN A REGEX EXERCISE
#
#   control            NOT red   the conforming fixture, unbroken
#   1. undeclared      undeclared      a route added to the router nobody declared
#   2. bypassed        scoping-bypassed  `o.requireAccount(...)` deleted from one
#                                       route, declaration untouched. THIS IS THE
#                                       CASE THE FORMAT EXISTS FOR: it is a
#                                       cross-tenant read with a declaration
#                                       saying the route is scoped.
#   3. key gone        account-key-lost  the middleware still there, still called,
#                                       and it stopped resolving an account
#   4. moved           stale          the route renamed on disk, the declaration
#                                       still naming the old one
#   5. thinner         surface-thin   a route deleted without the floor moving
#   6. no sources      surface-empty  `surface.sources: []` — a surface nobody read
#   7. absent file     surface-missing `surface.sources` names a file that is gone
#   8. twice           duplicate-id   the same id declared on two rows
#   9. undeclared key  schema         `scopedByAccount`, which is a silent no-op
#                                     everywhere else
#   10. Phoenix scope  NOT red       `scope "/v1"` above `get "/x"` and a declared
#                                     `/v1/x`: the SUFFIX match is what makes a
#                                     guessed prefix unnecessary, and a checker
#                                     that insisted on the prefix would go red on
#                                     courier's real router
#   11. another dialect NOT red      the SAME route declared `:id` where the code
#                                     says `{id}`, which is what five languages and
#                                     four frameworks between them actually spell
#   12. a comment      NOT red       a line mentioning a route inside a comment
#                                     does not register it. Without this a Go file
#                                     that documents its own routes — which
#                                     identity's does — would be a wall of
#                                     `undeclared` and the checker would be
#                                     switched off within a week.
#   10b. Next.js       NOT red      `site` and `parlor` both serve all of `/v1`
#                                     from one catch-all `route.ts` whose methods
#                                     are named exports. The control is the whole
#                                     point: a checker that could not read a path
#                                     out of a file name would report BOTH of this
#                                     fleet's Next.js services as having no routes,
#                                     which is D18's `route_defs=0` reproduced by
#                                     the tool written to stop it.
#   13. undeclared, Next.js          the same shape with one method added, and the
#                                     `undeclared` finding must still fire when the
#                                     path came from the filename rather than the
#                                     line
#   14. no key, Next.js  account-key-lost  the middleware still there, the
#                                     identifier renamed, and the route still
#                                     declared scoped
#   15a. chained axum   NOT red      a `Router::new().route(a).route(b)` line holds
#                                     TWO routes. A `search` that returns the first
#                                     match would miss the second and report a
#                                     correctly declared route `undeclared`; reading
#                                     the handler method from the start of the line
#                                     would call the second route's POST a GET.
#                                     Both were real, both were silent on every
#                                     fixture core shipped, and both were found by
#                                     reading pantry's real router rather than by
#                                     the red proof.
#   15b. receiver       NOT red      `r.Get("/v1/accounts", h)` — the chi pattern
#                                     used to capture the RECEIVER, so every route
#                                     in identity read as method `r` and all
#                                     forty-two would have been reported
#                                     `undeclared`. Asserted on a two-route router
#                                     with a GET and a POST, which is the smallest
#                                     thing that cannot pass by accident.
#   15c. swapped methods undeclared  the negative control for 15b: declaring the
#                                     WRONG method for a real route is caught, so
#                                     15b is green because the method is read and
#                                     not because the method is ignored.
#   15d. split line     NOT red      identity's `admin.go` writes a route with the
#                                     PATH on one line and the middleware on the
#                                     next, and CONCATENATES two literals around an
#                                     identifier. Reading one line gave a path that
#                                     exists nowhere and a window of zero called
#                                     three of identity's admin routes
#                                     `scoping-bypassed` — a false alarm on the
#                                     very repository the successor is told to
#                                     adopt first.
#   15e. split, bypassed RED          the same router with the middleware deleted,
#                                     so the window is what keeps 15d honest rather
#                                     than a check that stopped looking
#
# THE COMMENT BLOCK IN `go_handlers/internal/httpapi/router.go` IS PART OF THAT
# FIXTURE'S CONTRACT, and editing it moved every registration below it by ten lines —
# which is how all four of its rows went `stale` at once and cases 29-35 failed for a
# reason with nothing to do with handler resolution. It is recorded here because the
# failure is instructive rather than annoying: a fixture whose prose is measured
# against its own line numbers has a second thing to keep correct, and the red proof
# is what tells you when you have broken it.
#   16. no declaration missing      every repository in the fleet today, and the
#                                     answer has to be a FAILURE: a service that
#                                     has not declared its boundary has not proven
#                                     one, and inferring an answer is D18
#   16. unreadable      unreadable   a file the harness's own reader refuses
#   17. two services    WARN, green  this file and tenancy.yml naming different
#                                     repositories — a copy somebody made
#   18. nothing scoped  WARN, green  a surface where no entry point is
#                                     account-scoped. A WARNING and not a failure
#                                     because a shared library is a real state,
#                                     and a check with no way to say "this service
#                                     reaches no customer data" forces it to lie.
#   19. guessed key     WARN, green  no `accountKey` and no tenancy.yml, so the
#                                     account lines were searched for in four
#                                     spellings the checker chose rather than one
#                                     the service declared
#   20. all public      NOT red   public_surface: a service that really does hold
#                                     no customer data, every route honestly
#                                     `false`. This is the control for the check
#                                     below: a check that flagged every `false`
#                                     row on its own shape would be red here too,
#                                     and everything it said would be true.
#   21. the liar        red, and FIVE routes named with a file and a line. A
#                                     complete, schema-valid declaration in which
#                                     every row is `accountScoped: false` over a
#                                     service that resolves an account on five of
#                                     its ten routes. This is the D18 defect in
#                                     the one form `undeclared` cannot see.
#   22. not /healthz    NOT named  the same run as 21, asserting the ABSENCE: a
#                                     probe behind `pipe_through :api` is not
#   23. not unsubscribe NOT named  accused, and neither is the token-authorised
#                                     unsubscribe that HOLDS a mailbox and resolves
#                                     no account. Without 22 and 23 the run in 21
#                                     proves nothing: a check that flags every
#                                     public route is green on the liar too,
#                                     because everything it says is true.
#   24. the breaking    the liar PASSES AGAIN with the contradiction check off,
#                                     proving that check is the thing making it
#                                     red rather than something already there
#   25. handler gone    WARN, green  a `false` row whose controller file has
#                                     been moved out from under the checker. "I
#                                     could not check this" is the honest answer,
#                                     and it is a WARNING rather than a failure
#                                     because it does not move the exit code: a
#                                     warning nobody can act on teaches people to
#                                     read past warnings.
#   26. deleted route   registration-commented  the registration COMMENTED OUT and
#                                     the declaration untouched. Not silent:
#                                     WRONG, because the summary then printed the
#                                     deleted route as a mounted one.
#   27. and the floor   registration-commented  the same, with `surface.minimum`
#                                     lowered as well — so the row is the only
#                                     thing left, which is what makes 28 possible
#   28. the breaking    registration-commented  with the registration check
#                                     deleted, 27's repository PASSES. A
#                                     decrease-detector whose own floor can be
#                                     edited to match the decrease is not a
#                                     decrease-detector.
#
# Case 12's comment-stripping is a real rule, not a hypothetical: the recognisers
# match on a path literal and a comment carries one. Cases 26-28 are the other
# side of that same rule, and they are why the two halves of the checker must
# read a source line through ONE function: for the life of this proof the surface
# walk stripped comments and the row check did not, so the checker agreed with
# itself about which lines registered routes only by accident of which half ran
# first.
#
# `surface.minimum` is deliberately NOT removed by any of the three, and case 27
# is why it is not a duplicate of them: a route deleted together with its own
# declaration row leaves no row to be stale, and the count is the only thing left
# to notice.
#
# CASES 29-32, ON THE `go_handlers` FIXTURE: how a definition search says no.
#
# `_file_defining` guarded itself with `if tail and tail != symbol`, so it searched
# for a symbol CARRYING A DOT and skipped every bare name — while its own docstring
# named `handleList`, a bare name, as a case it handled. Measured on identity:
# `r.Get("/healthz", handleHealthz)` with `func handleHealthz` defined in the same
# package came back `contradiction-unreadable` — "the handler could not be resolved
# to a file in this repository" — about a file the checker had already opened twice.
# A docstring is not a test, and that one had been asserting a capability for as
# long as it was untrue.
#
#   29. control         the fixture unbroken, which must be CLEAN. Without it a
#                                     checker that resolved nothing at all would
#                                     satisfy 30 and 31 for the wrong reason.
#   30. a bare symbol   `/healthz` registers `handleHealthz` with no receiver, so
#                                     the symbol is bare and the deleted guard
#                                     could not reach it. `/livez` — which has
#                                     always resolved — is the control INSIDE the
#                                     case, so a fix that switched resolution off
#                                     cannot pass by looking like one that turned
#                                     it on.
#   31. the breaking    with the bare-symbol search deleted from a COPY of the
#                                     checker, `/healthz` is unreadable again
#   32. the breaking    the loose test this fix replaced also matched a PARAMETER
#                          — `func (o options) handleReadyz(checks []Check)` is
#                          `func\b.*\bchecks\b` — so a search for `checks` returned
#                          a FILE as though it had found a handler. This is the one
#                          case here that is not reachable through a registration
#                          line, because nothing asks for a symbol that is both a
#                          real handler and a parameter name except a checker that
#                          has already read the line wrong, so it is asserted on the
#                          resolution itself from a copy with the guard removed.
#
# CASES 33-35: THE HANDLER IN THE HANDLER POSITION.
#
# `_last_symbol` returned the LAST identifier on a registration line whatever it was.
# identity's httpapi.go:246 is
#
#     r.Get("/readyz", o.handleReadyz(checks))
#
# so it returned `checks` — a parameter — and the row came back
# `contradiction-unreadable` on the line DIRECTLY BELOW `/healthz`, which resolved
# because `handleHealthz` is both bare and last. Right on one line, wrong on the
# next, for a reason with nothing to do with the service.
#
# The fix cannot be "prefer the callee", because identity also writes
# `mux.HandleFunc("GET /v1/x", o.requireAccount(o.handleGetMessage))` and there the
# callee is a MIDDLEWARE and the handler is its argument. Those two lines are
# syntactically IDENTICAL — a call of a call with a bare identifier inside — so the
# LINE cannot decide and the REPOSITORY has to. Hence a list of candidates,
# innermost first, each tried until one resolves to a file.
#
#   33. the row reads   `/readyz` is not `contradiction-unreadable`. An assertion
#                                     about the ABSENCE of a warning, so a checker
#                                     that had stopped resolving anything could not
#                                     pass it — which is what 34 is for.
#   34. the breaking    with the candidate list deleted from a COPY of the checker,
#                                     `/readyz` is unreadable again
#   35. the direction   the INNERMOST candidate wins, so `o.requireSession` does not
#                                     stand in for `o.handleWrapped`. Without it, 34
#                                     could be satisfied by always answering with the
#                                     OUTERMOST symbol: right on `/readyz`, wrong on
#                                     `/wrapped`. The two rows are asserted together
#                                     because only the pair catches either mistake.
#
# CASES 36-44: A GATE THAT IS NOT ON THE ROUTE'S OWN LINE. gateway's `GET /v1/me` is
# registered with an INLINE handler twenty-seven lines below the `app.use("/v1/*", …)`
# that scopes it, and Hono answers in registration order, so the route IS behind the
# gate — which is why `scoping-bypassed` fired on it, and why the flag that suppresses
# that finding for Phoenix and axum did not apply. The argument is written down at the
# section header below; 36-44 are the cases, 41-43 are the proofs that the new reader
# is the thing that makes them behave, and 45-49 are what `hono_pipeline` cannot reach.
#
#
# Case 32's first version PASSED FOR THE WRONG REASON: the copy it probed crashed on
# import (`@dataclass` looks its module up through `sys.modules`), the answer came
# back as an empty string, and an empty string is not `NOTHING`, so it took the pass
# branch. Case 34 took four attempts for the same class of reason — it patched the
# wrong half of the file three times and ran against the PREVIOUS case's copy each
# time, because a failed patch is silent and a stale copy is green. Both are written
# down here because a red proof that cannot tell "the fix is absent" from "the case
# never ran" is the thing this file is for, and these two were not it. What turned
# every attempt red was an `assert` on the patch's OWN PRECONDITIONS — that the anchor
# text is present, that the loop lives in the half being searched, that the function
# really is gone afterwards — and that is now what every patch below does before it
# runs anything.
#
# CASES 50-57, ON THE `go_runtime_prefix` FIXTURE: A PATH PREFIX THAT IS RUNTIME
# CONFIGURATION. `pantry` declares its surface and reads exit 1 with `0 undeclared`,
# because `oapi-codegen` writes `r.Get(options.BaseURL+"/v1/services/{name}", …)` and
# the chi recogniser requires the path expression to BEGIN with a string literal. All
# four of pantry's registrations are dropped, so `undeclared` — the finding that exists
# to say an entry point was missed — reports zero, which is what a reader takes to mean
# every registration was declared. It means the opposite: nothing was found, so nothing
# COULD be undeclared. A count of zero and a count of nothing print as the same line.
#
# `options.BaseURL` is not a constant this checker has failed to resolve. It is a struct
# field the caller fills from configuration, so there is no value in any tree, and any
# recogniser that produced a path from it would be guessing a deployment's configuration
# out of the air. That is why these cases are about what a checker SAYS rather than about
# what it can read, and why no case here resolves the prefix:
#
#   50. the control    four registrations, four correct rows, and the checker says it
#                      read NONE of them — and the run is GREEN, because the
#                      declaration is not what is wrong
#   51. no false stale `get-service` is not `stale`. The line it names DOES register
#                      the route; the checker cannot evaluate the path. `stale` is a
#                      FAILURE about a route that is mounted, which is the wolf
#   52. still listed    and the row is still listed, at the real line — because the fix
#                      must not be silence either
#   53. THE BREAKING   delete the fifth claim verdict from a copy and `get-service` is
#                      `stale` again
#   54. THE BREAKING   delete BOTH and the fixture goes GREEN with `0 undeclared` and no
#                      unreadable count: the defect, passing clean
#   55. the floor      `surface.minimum: 4` is still `surface-thin`, because a route the
#                      checker could not read must not count towards a floor — this is
#                      the case that keeps case 50's green honest
#   56. not the helper `t.chiRouter.Get(pattern, traced(h))` is not this finding, or
#                      identity's four lines and this fixture's one would all warn
#   57. the RESOLVABLE half, on `go_handlers`: a `const` prefix gets the SAME answer,
#                      which is what extends rather than reverses
#                         REPORT-core-hono-inline-01 §3
#   58. THE BREAKING, the NUMBER  delete the line that sets it and the summary says
#                      `0 unreadable` over a surface with four. The original defect,
#                      restated in the new field's name — and the reason the count is
#                      printed on EVERY line rather than only when it is non-zero:
#                      an omitted number cannot be told from a computed zero
# Case 55 is green before the fix and green after it, and that is what a control is
# for. It is the case that goes red if someone widens the floor to
# `found + unreadable` — the one edit that would turn pantry's exit 1 into an exit 0 by
# manufacturing coverage rather than by reporting honestly, and the reason the summary
# line carries a separate count instead.
#
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness_dir="$(dirname "$here")"
core="$(dirname "$harness_dir")"
checker="$core/harness/account_scope_check.py"
fixtures="$here/fixtures/account-scope"
work="$(mktemp -d)"
# The red proofs below each build a THROWAWAY COPY of the checker beside the
# real one — its own import guard refuses to run a copy that cannot reach
# anywaye_contract, and that refusal is correct — so both copies are named
# HERE and removed by the ONE trap. Cases 24, 28, 31 and 34 each used to
# re-register `trap ... EXIT` for their own copy, and an EXIT trap REPLACES
# rather than adds: the LAST one won, so case 28's copy was left behind in
# harness/ after every run — a 133KB file nobody chose, in the directory a
# reader trusts, invisible to `git status` on a clean tree. Each case now only
# assigns `$disabled_checker`, and this trap removes both names whether the run
# finished, failed, or was interrupted between two cases.
disabled_checkers="$harness_dir/_account_scope_registration_disabled.py $harness_dir/_account_scope_check_disabled.py"
trap 'rm -rf "$work" $disabled_checkers' EXIT

# THE INTERPRETER IS RESOLVED ONCE, HERE, AND EVERY INVOCATION BELOW USES
# `$python` — including the indented ones inside functions, which are the easiest
# to miss in a search. bin/prime exports ANYWAYE_ACCOUNT_SCOPE_PYTHON so this proof
# runs against the same CPython the checker runs against; a bare `python` or
# `python3` at a call site defeats that pin, and on a machine whose `python` is
# absent (stock macOS has `python3` only) every fixture-planting step fails to
# apply, every case prints "THE BREAKAGE DID NOT APPLY", and the red proof — the
# thing that proves the checker can say NO — cannot run. The gate's honesty then
# depends on a binary this script never requires.
python="${ANYWAYE_ACCOUNT_SCOPE_PYTHON:-}"
if [ -z "$python" ]; then
  python="$(command -v python3 || true)"
fi
if [ -z "$python" ]; then
  echo "account_scope_self_test.sh: no python3 on PATH — cannot run the checker" >&2
  exit 2
fi
if ! "$python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
  >/dev/null 2>&1; then
  echo "account_scope_self_test.sh: $python is older than 3.9. The proof was NOT run," >&2
  echo "  and a proof that did not run is not a pass." >&2
  exit 2
fi
if [ ! -r "$checker" ]; then
  echo "account_scope_self_test.sh: $checker is missing — this is not a anywaye/core" >&2
  echo "  checkout. The proof was NOT run, and a proof that did not run is not a pass." >&2
  exit 2
fi
if [ ! -d "$fixtures/conforming" ]; then
  echo "account_scope_self_test.sh: the control fixture $fixtures/conforming is missing." >&2
  echo "  Without a known shape to break, every red below proves nothing: a checker" >&2
  echo "  that refused everything would satisfy all of them." >&2
  exit 2
fi

pass=0
fail=0

note() { printf '\n--- %s\n' "$1"; }

# expect_red <label> <expected-finding>
expect_red() {
  local label="$1" expect="$2" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    printf '  RED EXPECTED, GOT CLEAN  %s\n' "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if ! printf '%s' "$output" | grep -q "$expect"; then
    printf '  WRONG FINDING            %s (wanted %s)\n' "$label" "$expect"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  red, and named           %s -> %s\n' "$label" "$expect"
  pass=$((pass + 1))
}

# expect_clean <label>
expect_clean() {
  local label="$1" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '  CLEAN EXPECTED, GOT RED  %s\n' "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  clean                    %s\n' "$label"
  pass=$((pass + 1))
}

# expect_warn <label> <expected-finding> — the finding is printed AND the exit code
# stays 0. A warning that moved the exit code would be a failure, and a warning
# that is printed without saying which it was leaves the reader guessing, so this
# asserts both halves: the id is in the output and the run is still green.
expect_warn() {
  local label="$1" expect="$2" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '  WARNING EXPECTED, GOT EXIT %s  %s\n' "$status" "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if ! printf '%s' "$output" | grep -q "$expect"; then
    printf '  WRONG FINDING            %s (wanted %s)\n' "$label" "$expect"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  warn, and green          %s -> %s\n' "$label" "$expect"
  pass=$((pass + 1))
}

# expect_red_but_not <label> <expected-finding> <must-not-appear> — a run that has
# to go red AND name one finding AND NOT name another. The third argument is the
# whole point: without it a check that flagged every declared-`false` row would
# satisfy this helper exactly as well as one that works, because everything such a
# check says about the liar is true.
expect_red_but_not() {
  local label="$1" expect="$2" absent="$3" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    printf '  RED EXPECTED, GOT CLEAN  %s\n' "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if ! printf '%s' "$output" | grep -q "$expect"; then
    printf '  WRONG FINDING            %s (wanted %s)\n' "$label" "$expect"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if printf '%s' "$output" | grep -q "$absent"; then
    printf '  FALSE POSITIVE           %s named %s, which it must not name\n' \
      "$label" "$absent"
    printf '%s\n' "$output" | grep -n "$absent" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  red, named %s, silent on %s\n' "$expect" "$absent"
  pass=$((pass + 1))
}

# expect_listing <label> <pattern> — the row must be printed in the SUMMARY LISTING
# this way. Its own helper because the findings block and the listing are two
# different outputs and only one of them is read by somebody skimming for "is this
# route mounted?". The defect case 26/27 is about had a green exit code AND a
# finding-shaped story, so asserting the finding alone would have proved the
# checker complained without proving it told the truth: a summary that asserts a
# deleted route is mounted is worse than no summary, because it is read.
expect_listing() {
  local label="$1" want="$2" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if ! printf '%s' "$output" | grep -qE "$want"; then
    printf '  ROW NOT LISTED           %s (wanted %s)\n' "$label" "$want"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  listed                   %s\n' "$label"
  pass=$((pass + 1))
}

# expect_not_named <label> <must-not-appear> — the finding is NOT printed, whatever
# the exit code. Its own helper because "silent" is not the same answer as "clean",
# and this suite has a case on each side of that: a mounted sub-application whose gate
# this checker cannot read (case 40) must not be called unscoped, and a probe behind a
# gate that DOES resolve no account (case 44) must not be called a contradiction. Both
# are refusals to conclude, and neither is `expect_clean`, which would accept a red.
expect_not_named() {
  local label="$1" absent="$2" output status
  output="$("$python" "$checker" "$work/$label" 2>&1)"
  status=$?
  if ! printf '%s' "$output" | grep -qE 'account-scope\.|^(OK|FAIL) '; then
    printf '  THE CHECKER SAID NOTHING   %s printed neither a finding nor a verdict\n' \
      "$label"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  if printf '%s' "$output" | grep -q "$absent"; then
    printf '  NAMED WHAT IT MUST NOT      %s (found %s)\n' "$label" "$absent"
    printf '%s\n' "$output" | grep -n "$absent" | sed 's/^/    /'
    fail=$((fail + 1))
    return
  fi
  printf '  silent on                   %s (%s), exit %s\n' "$label" "$absent" "$status"
  pass=$((pass + 1))
}

# unapplied <label> — a breakage's own preconditions did not hold, so the case that
# wanted it DID NOT RUN and must not be counted either way.
#
# Every breakage in this file asserts its own preconditions, and until cases 45-49
# that was not enough: a python that raised on its own `assert` exited non-zero, the
# shell carried on to the assertion below it, and that assertion read the UNPATCHED
# fixture — so the case reported whatever the unpatched fixture happens to say. Case
# 46 did exactly that, and printed "red, and named" for a breakage that had never
# been applied. Every breakage from 45 on is wrapped in `if … then`, and this is the
# other half of the contract: the message says the case did not run, and the count
# says so too.
unapplied() {
  printf '  THE BREAKAGE DID NOT APPLY  the fixture or the proof moved, so %s did not run\n' "$1"
  fail=$((fail + 1))
}

# fresh <base> <label> — a throwaway copy, so one case can never mask the next.
fresh() {
  rm -rf "$work/$2"
  cp -R "$fixtures/$1" "$work/$2"
}

note "control: the conforming fixture, unbroken, which must be CLEAN"
fresh conforming control
expect_clean control

note "case 1: a route added to the router that nobody declared"
fresh conforming undeclared_route
cat >> "$work/undeclared_route/internal/httpapi/router.go" <<'GO'
	mux.HandleFunc("GET /v1/billing", o.handleBilling)
GO
expect_red undeclared_route "account-scope.undeclared"

note "case 2: the scoping deleted from one route, declaration untouched"
fresh conforming scoping_bypassed
"$python" - "$work/scoping_bypassed/internal/httpapi/router.go" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(
    path.read_text().replace(
        'mux.HandleFunc("GET /v1/messages/{id}", o.requireAccount(o.handleGetMessage))',
        'mux.HandleFunc("GET /v1/messages/{id}", o.handleGetMessage)',
    )
)
PY
expect_red scoping_bypassed "account-scope.scoping-bypassed"

note "case 3: the middleware still there, still called, and no longer scoped"
fresh conforming account_key_gone
"$python" - "$work/account_key_gone/internal/httpapi/account.go" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
lines[12] = "\t\tprincipal, err := o.accounts.Resolve(r.Context(), bearerToken(r))\n"
lines[19] = lines[19].replace("withAccount(r.Context(), accountID)", "r.Context()")
path.write_text("".join(lines))
PY
expect_red account_key_gone "account-scope.account-key-lost"

note "case 4: the route renamed on disk, the declaration still naming the old one"
fresh conforming route_renamed
"$python" - "$work/route_renamed/internal/httpapi/router.go" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(
    path.read_text().replace(
        'mux.HandleFunc("GET /v1/messages/{id}"',
        'mux.HandleFunc("GET /v1/message/{id}"',
    )
)
PY
expect_red route_renamed "account-scope.stale"

note "case 5: a route deleted, and the floor left where it was"
fresh conforming surface_thin
"$python" - "$work/surface_thin/internal/httpapi/router.go" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(
    "\n".join(
        line
        for line in path.read_text().splitlines()
        if "/v1/messages/{id}" not in line
    )
    + "\n"
)
PY
expect_red surface_thin "account-scope.surface-thin"

note "case 6: a surface nobody read — the enumeration with no file to check it against"
fresh conforming surface_empty
"$python" - "$work/surface_empty/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text().replace(
    "  sources:\n    - internal/httpapi/router.go\n", "  sources: []\n"
)
path.write_text(text)
PY
expect_red surface_empty "account-scope.surface-empty"

note "case 7: surface.sources names a file that is not there"
fresh conforming surface_missing
rm "$work/surface_missing/internal/httpapi/router.go"
expect_red surface_missing "account-scope.surface-missing"

note "case 8: the same id declared on two rows"
fresh conforming duplicate_id
"$python" - "$work/duplicate_id/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text().replace("  - id: healthz\n", "  - id: list-messages\n", 1)
path.write_text(text)
PY
expect_red duplicate_id "account-scope.duplicate-id"

note "case 9: an undeclared key, which is a silent no-op everywhere else"
fresh conforming undeclared_key
"$python" - "$work/undeclared_key/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text().replace(
    "    reason: public\n", "    reason: public\n    scopedByAccount: false\n", 1
)
path.write_text(text)
PY
expect_red undeclared_key "account-scope.schema"

note "case 10 (negative control): a Phoenix scope prefix is not a prefix to guess"
fresh phoenix_surface scope_prefix
expect_clean scope_prefix

note "case 10b (negative control): the same, on Next.js, where the path is a FILENAME"
fresh nextjs_surface nextjs_control
expect_clean nextjs_control

note "case 11 (negative control): the fleet's two spellings of one parameter"
fresh conforming parameter_spelling
"$python" - "$work/parameter_spelling/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(path.read_text().replace("/v1/messages/{id}", "/v1/messages/:id"))
PY
expect_clean parameter_spelling

note "case 12 (negative control): a route written in a COMMENT is not a route"
fresh conforming comment_only
"$python" - "$work/comment_only/internal/httpapi/router.go" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(
    path.read_text()
    + '\t// GET /v1/webhook_endpoints was removed in core-14.\n'
    + '\t// mux.HandleFunc("GET /v1/secret", o.handleSecret)\n'
)
PY
expect_clean comment_only

note "case 13: a Next.js route nobody declared — one file serving all of /v1"
fresh nextjs_surface nextjs_undeclared
"$python" - "$work/nextjs_undeclared/src/app/v1/[...path]/route.ts" <<'NEXTJS'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    path.read_text()
    + "\nexport function PUT(request: Request, context: RouteContext): Promise<Response> {\n"
    + "  return dispatch(request, context);\n}\n"
)
NEXTJS
expect_red nextjs_undeclared "account-scope.undeclared"

note "case 14: a Next.js route whose scope was dropped, and the middleware still there"
fresh nextjs_surface nextjs_key_gone
"$python" - "$work/nextjs_key_gone/src/middleware/requireAccount.ts" <<'MIDDLEWARE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(path.read_text().replace("accountId", "principalId"))
MIDDLEWARE
expect_red nextjs_key_gone "account-scope.account-key-lost"

note "case 15a: a chained axum router — two routes on one line, and the SECOND"
note "          one's method must not be read as the first one's"
fresh nextjs_surface chained_axum
"$python" - "$work/chained_axum" <<'AXUM'
import sys
from pathlib import Path

root = Path(sys.argv[1])
(root / "src" / "http.rs").write_text(
    'pub fn routes() -> Router {\n'
    '    Router::new()\n'
    '        .route("/v1/y", get(get_y))\n'
    '        .route("/v1/z", post(post_z))\n'
    '}\n'
)
(root / "account_scope.yml").write_text(
    'version: 1\n'
    'service: chained-axum\n'
    'surface:\n'
    '  kind: http\n'
    '  sources:\n'
    '    - src/http.rs\n'
    '  minimum: 2\n'
    '  accountKey: account_id\n'
    'entryPoints:\n'
    '  - id: get-y\n'
    '    kind: http\n'
    '    method: GET\n'
    '    path: /v1/y\n'
    '    accountScoped: false\n'
    '    reason: none\n'
    '    registeredAt:\n'
    '      file: src/http.rs\n'
    '      line: 3\n'
    '  - id: post-z\n'
    '    kind: http\n'
    '    method: POST\n'
    '    path: /v1/z\n'
    '    accountScoped: false\n'
    '    reason: none\n'
    '    registeredAt:\n'
    '      file: src/http.rs\n'
    '      line: 4\n'
)
AXUM
expect_clean chained_axum

# chi_router <dir> — the smallest router that CANNOT pass by accident: two routes,
# one GET and one POST, on the same path. Every bug case 15b exists for made a
# correctly declared GET stop matching, so one route would hide it behind the
# other's match and two routes with different methods cannot.
chi_router() {
  mkdir -p "$1/src"
  cat > "$1/src/router.go" <<'GO'
package httpapi

func Routes(o *API) *chi.Mux {
    r := chi.NewRouter()
    r.Get("/v1/accounts", o.handleList)
    r.Post("/v1/accounts", o.handleCreate)
    return r
}
GO
  cat > "$1/account_scope.yml" <<'YML'
version: 1
service: chi-router
surface:
  kind: http
  sources:
    - src/router.go
  minimum: 2
  accountKey: account_id
entryPoints:
  - id: list-accounts
    kind: http
    method: GET
    path: /v1/accounts
    accountScoped: false
    reason: none
    registeredAt:
      file: src/router.go
      line: 5
  - id: create-account
    kind: http
    method: POST
    path: /v1/accounts
    accountScoped: false
    reason: none
    registeredAt:
      file: src/router.go
      line: 6
YML
}

note "case 15b: a chi route reads its METHOD, not its receiver's name"
rm -rf "$work/receiver_not_method"
chi_router "$work/receiver_not_method"
expect_clean receiver_not_method

note "case 15c: a declaration that SWAPS the methods of two real routes is caught"
rm -rf "$work/swapped_methods"
chi_router "$work/swapped_methods"
"$python" - "$work/swapped_methods/account_scope.yml" <<'SWAP'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text().replace("method: GET\n    path: /v1/accounts", "method: POST\n    path: /v1/accounts")
path.write_text(text)
SWAP
expect_red swapped_methods "account-scope.undeclared"

note "case 15d: identity's admin router — path on one line, middleware on the next"
rm -rf "$work/split_line_handler"
mkdir -p "$work/split_line_handler/internal/httpapi"
cat > "$work/split_line_handler/internal/httpapi/admin.go" <<'GO'
package httpapi

const adminPrefix = "admin"

func Routes(o *API) *chi.Mux {
    r := chi.NewRouter()
    r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/audit-log",
        o.requireAdminToken(o.requireAccountRole(accounts.RoleAdmin, o.handleListAuditLog, accountID)))
    return r
}
GO
cat > "$work/split_line_handler/account_scope.yml" <<'YML'
version: 1
service: split-line-handler
surface:
  kind: http
  sources:
    - internal/httpapi/admin.go
  minimum: 1
  accountKey: account_id
entryPoints:
  - id: list-audit-log
    kind: http
    method: GET
    path: /v1/accounts/{accountID}/{}/audit-log
    accountScoped: true
    accountFrom:
      via: requireAccountRole
      file: internal/httpapi/admin.go
      line: 8
    registeredAt:
      file: internal/httpapi/admin.go
      line: 7
YML
expect_clean split_line_handler

note "case 15e: the same router with the middleware DELETED from the next line"
rm -rf "$work/split_line_bypassed"
cp -R "$work/split_line_handler" "$work/split_line_bypassed"
"$python" - "$work/split_line_bypassed/internal/httpapi/admin.go" <<'SPLIT'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    path.read_text().replace(
        "o.requireAdminToken(o.requireAccountRole(accounts.RoleAdmin, o.handleListAuditLog, accountID))",
        "o.handleListAuditLog(accountID)",
    )
)
SPLIT
expect_red split_line_bypassed "account-scope.scoping-bypassed"

note "case 15: the declaration is gone — which is the fleet's state today"
fresh conforming declaration_absent
rm "$work/declaration_absent/account_scope.yml"
expect_red declaration_absent "account-scope.declaration-missing"

note "case 16: the declaration is not a document the harness's own reader accepts"
fresh conforming declaration_unreadable
printf 'version: 1\nservice: [unclosed\n' > "$work/declaration_unreadable/account_scope.yml"
expect_red declaration_unreadable "account-scope.declaration-unreadable"

note "case 17 (warning): two declarations of one repository naming two services"
fresh conforming service_disagrees
cat > "$work/service_disagrees/tenancy.yml" <<'TENANCY'
version: 1
service: some-other-service
accountScoped: true
scope:
  key: account_id
  sources:
    - internal/httpapi/store.go
entryPoints: []
rls:
  enforced: false
  sources: []
  tables: []
TENANCY
expect_warn service_disagrees "account-scope.service-disagrees"

note "case 18 (warning): a surface on which nothing is account-scoped"
fresh conforming nothing_scoped
"$python" - "$work/nothing_scoped/account_scope.yml" <<'FLIP'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text().replace("accountScoped: true", "accountScoped: false")
text = re.sub(
    r"    accountFrom:\n(?:      (?:via|file|line):[^\n]*\n)+", "    reason: public\n", text
)
path.write_text(text)
FLIP
expect_warn nothing_scoped "account-scope.nothing-scoped"

note "case 19 (warning): nothing named the tenancy key, so four were guessed"
fresh conforming key_guessed
"$python" - "$work/key_guessed/account_scope.yml" <<'NOKEY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    "\n".join(line for line in path.read_text().splitlines() if "accountKey" not in line) + "\n"
)
NOKEY
expect_warn key_guessed "account-scope.scope-key-guessed"

note "case 20 (negative control): a service that holds no customer data at all"
fresh public_surface all_public
expect_clean all_public

note "case 21 (THE LIAR): ten rows, all false, five of them lies — every one named"
fresh liar liar_named
output="$("$python" "$checker" "$work/liar_named" 2>&1)"
status=$?
named=0
for route in \
  "list-webhook-endpoints (GET /v1/webhook_endpoints)" \
  "get-webhook-endpoint (GET /v1/webhook_endpoints/:id)" \
  "show-notification-preferences (GET /v1/notification_preferences/:user_id)" \
  "update-notification-preferences (PUT /v1/notification_preferences/:user_id)" \
  "send-message (POST /v1/messages)"
do
  if printf '%s' "$output" | grep -q "declaration-contradicts-code:.*$route"; then
    named=$((named + 1))
  else
    printf '  NOT NAMED                %s\n' "$route"
  fi
done
if [ "$status" -ne 1 ]; then
  printf '  EXIT EXPECTED 1, GOT %s  liar_named\n' "$status"
  fail=$((fail + 1))
elif [ "$named" -ne 5 ]; then
  printf '  NAMED EXPECTED 5, GOT %s  liar_named\n' "$named"
  fail=$((fail + 1))
elif ! printf '%s' "$output" | grep -q "lib/liar_web/plugs/principal.ex:19"; then
  printf '  NO FILE:LINE EVIDENCE     liar_named did not name principal.ex:19\n'
  fail=$((fail + 1))
else
  printf '  red, and all 5 lies named with a file and a line\n'
  pass=$((pass + 1))
fi

note "case 22 (negative control): a liveness probe is not accused"
fresh liar liar_not_probe
expect_red_but_not liar_not_probe \
  "account-scope.declaration-contradicts-code" "healthz (GET /healthz)"

note "case 23 (negative control): a token-authorised unsubscribe is not accused"
fresh liar liar_not_unsubscribe
expect_red_but_not liar_not_unsubscribe \
  "account-scope.declaration-contradicts-code" "unsubscribe-show"

note "case 24 (THE BREAKING): with account-scope.declaration-contradicts-code
  deleted, the liar passes"
fresh liar liar_check_disabled
# The call is deleted from a THROWAWAY COPY of the checker, not switched off by an
# environment variable: `test_the_account_scope_checker_reads_no_environment_and
# _runs_no_process` forbids a switch in the shipped file and it should, because an
# answer that depends on who is asking is not an answer about the repository. A
# copy is also the stronger demonstration — it removes the code rather than
# configuring it away.
# Beside the real checker rather than in $work, because the module's own import
# guard refuses to run a copy that cannot reach anywaye_contract — and that refusal
# is correct, so the copy is made where its neighbour is and removed by the ONE
# trap declared at the top of this file, which names every copy this script makes.
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
"$python" - "$checker" "$disabled_checker" <<'DISABLED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
call = "    contradictions = _check_contradictions(repo, points, matched, claims)"
assert call in source, "the contradiction call moved; this proof must follow it"
# `Contradictions()`, not `[]`: the call site reads `.findings` and `.unverified`
# off the result, so a two-element list is not a stand-in for it any more. The
# patch has to defeat the CHECK and not merely the unpacking.
Path(sys.argv[2]).write_text(source.replace(call, "    contradictions = Contradictions()", 1))
DISABLED
if "$python" "$disabled_checker" "$work/liar_check_disabled" >"$work/disabled.out" 2>&1; then
  if grep -q "declaration-contradicts-code" "$work/disabled.out"; then
    printf '  STILL FINDING IT         the deleted check is still reporting\n'
    fail=$((fail + 1))
  else
    printf '  clean, with the check gone  liar_check_disabled\n'
    pass=$((pass + 1))
  fi
else
  printf '  STILL RED WITHOUT IT     liar_check_disabled\n'
  sed 's/^/    /' "$work/disabled.out"
  fail=$((fail + 1))
fi

note "case 25 (warning): a false row whose handler is not in this repository"
# The other half of the contradiction check, and the one that keeps it honest. A row
# declared `false` whose controller file has been moved out from under the checker
# must NOT read as a pass: the honest answer is "I could not check this", and a
# warning that cannot be acted on teaches people to read past warnings, so this one
# is per-ROW and names the row.
# public_surface is the base rather than liar, because this case must be the ONLY
# thing wrong: `expect_warn` asserts exit 0, and the liar is already exit 1.
fresh public_surface handler_absent
rm "$work/handler_absent/lib/public_web/controllers/version_controller.ex"
expect_warn handler_absent "account-scope.contradiction-unreadable"

# ---------------------------------------------------------------------------
# 26, 27, 28: A ROUTE THAT WAS DELETED, AND THE DECLARATION THAT SAYS IT IS THERE
# ---------------------------------------------------------------------------
#
# The worst shape this checker has, and the only one it reported wrongly rather
# than silently. A refactor comments the registration out —
#
#     // mux.HandleFunc("GET /healthz", o.handleHealthz)
#
# — and leaves the declaration alone. The enumeration is right: the route is not
# registered, so `undeclared` has nothing to say. `surface.minimum` notices the
# count. And the row check, which is what decides whether a row is `stale`, read
# the RAW line and found the route written there in a comment, so it said the row
# was mounted.
#
# Lower `minimum` — one keystroke, and the thing the docs call a decrease-detector
# is a number in the file that went stale — and the answer was exit 0, with the
# summary printing `not-account-scoped GET /healthz (…:11)` beside a line that is
# a comment. Not silent: WRONG, in the output a human reads.
#
# 26 is the check. 27 is the assertion that the floor is not what is doing the
# work, and that the listing stops asserting a route exists. 28 is the proof.

note "case 26: the registration commented out, declaration and floor untouched"
fresh conforming registration_commented
"$python" - "$work/registration_commented/internal/httpapi/router.go" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(
    "\n".join(
        "\t// " + line.strip() if "/healthz" in line else line
        for line in path.read_text().splitlines()
    )
    + "\n"
)
PY
# NOT `undeclared`, and the third argument is the point of the whole case: a fix
# that stopped stripping comments everywhere would make the commented route a
# `undeclared` registration, which is the opposite error — the file does not
# register it and nothing has been declared wrongly about it.
expect_red_but_not registration_commented \
  "account-scope.registration-commented" "not-account-scoped GET /healthz"

note "case 27: the same repository with the floor lowered — the check alone must hold it"
# `surface.minimum` 4 -> 3 is the whole of this edit, and it is the edit the docs
# warn about and cannot prevent. The point of the case is that after it, the
# registration row is the ONLY thing standing between this repository and a green
# build over a route it does not mount.
fresh conforming registration_commented_floor_lowered
"$python" - "$work/registration_commented_floor_lowered/internal/httpapi/router.go" \
  "$work/registration_commented_floor_lowered/account_scope.yml" <<'PY'
import sys
from pathlib import Path

router, declaration = (Path(item) for item in sys.argv[1:3])
router.write_text(
    "\n".join(
        "\t// " + line.strip() if "/healthz" in line else line
        for line in router.read_text().splitlines()
    )
    + "\n"
)
declaration.write_text(declaration.read_text().replace("minimum: 4", "minimum: 3"))
PY
# `expect_red_but_not`, and the absent arm is `surface-thin`: if the floor were
# what caught this, the run would go red for the wrong reason and the fix would be
# a floor rather than a check.
expect_red_but_not registration_commented_floor_lowered \
  "account-scope.registration-commented" "account-scope.surface-thin"

# And the LISTING, which is the second half of the defect and the half a finding
# alone does not fix. The row must be printed as stale. It was printed as
# `not-account-scoped GET /healthz (internal/httpapi/router.go:11)` — a summary
# asserting a route is mounted, one line above a comment saying it is not.
expect_listing registration_commented_floor_lowered \
  '^  stale +GET /healthz +\(internal/httpapi/router.go:11\)'

note "case 28 (THE BREAKING): with the registration check deleted, the defect passes"
fresh conforming registration_check_disabled
# The same two edits as 27, applied before the check is removed: the repository
# under test is the one where exit 0 is a lie.
"$python" - "$work/registration_check_disabled/internal/httpapi/router.go" \
  "$work/registration_check_disabled/account_scope.yml" <<'PY'
import sys
from pathlib import Path

router, declaration = (Path(item) for item in sys.argv[1:3])
router.write_text(
    "\n".join(
        "\t// " + line.strip() if "/healthz" in line else line
        for line in router.read_text().splitlines()
    )
    + "\n"
)
declaration.write_text(declaration.read_text().replace("minimum: 4", "minimum: 3"))
PY
# The call is deleted from a THROWAWAY COPY of the checker, for case 24's reasons:
# no environment variable in the shipped file, because an answer that depends on
# who is asking is not an answer about the repository; and a copy is the stronger
# demonstration, because it removes the code rather than configuring it away.
# Beside the real checker rather than in $work, because the module's own import
# guard refuses to run a copy that cannot reach anywaye_contract — and that refusal
# is correct.
disabled_checker="$harness_dir/_account_scope_registration_disabled.py"
"$python" - "$checker" "$disabled_checker" <<'DISABLED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
call = "    found.extend(registration_findings(label, entry, claim))"
assert call in source, "the registration check moved; this proof must follow it"
Path(sys.argv[2]).write_text(source.replace(call, "    # deleted for the red proof", 1))
DISABLED
if "$python" "$disabled_checker" "$work/registration_check_disabled" >"$work/disabled.out" 2>&1; then
  if grep -q "registration-commented" "$work/disabled.out"; then
    printf '  STILL FINDING IT         the deleted check is still reporting\n'
    fail=$((fail + 1))
  else
    printf '  clean, with the check gone  registration_check_disabled\n'
    pass=$((pass + 1))
  fi
else
  printf '  STILL RED WITHOUT IT     registration_check_disabled\n'
  sed 's/^/    /' "$work/disabled.out"
  fail=$((fail + 1))
fi

# ---------------------------------------------------------------------------
# CASES 29-32: GO HANDLER RESOLUTION. go_handlers, and the two ways a definition
# search says no.
#
# `_file_defining` had a guard reading `if tail and tail != symbol`, so it searched
# for a symbol CARRYING A DOT and skipped every one without — while the docstring
# above it named `handleList`, a bare name, as a case it handles. The consequence
# measured on identity: `r.Get("/healthz", handleHealthz)` with
# `func handleHealthz` defined in the same package came back
# `contradiction-unreadable`, "the handler could not be resolved to a file in this
# repository", about a file the checker had already opened twice.
#
# The second half of the fix is the guard the loosening above would have needed:
# the looser test accepted a PARAMETER as a definition. `func New(checks []Check,
# opts ...Option)` matches `func\b.*\bchecks\b`, so a search for the symbol `checks`
# returned a file as though it had found a handler. Case 32 is that.
# ---------------------------------------------------------------------------

note "case 29 (control): the go_handlers fixture, unbroken, which must be CLEAN"
# Without this a checker that refused to resolve ANY handler would satisfy 30 and 31
# for the wrong reason, so the fixture is established as a service that declared its
# surface correctly before anything is asserted about which rows it can read.
fresh go_handlers go_control
expect_clean go_control

note "case 30: a BARE handler symbol resolves, and so does one already resolved"
# Two rows, and the second is the control for the first. `/healthz` registers
# `handleHealthz` with no receiver, so the symbol read off the line is bare and is
# the row the deleted guard could not reach. `/livez` registers `o.handleLivez`,
# which has always resolved, so it is here to catch a fix that switched resolution
# OFF rather than on — the failure mode a "0 warnings" reading cannot distinguish
# from a fix. `/readyz` is deliberately NOT asserted in this case: its line ends in
# an argument, which is its own defect and its own case.
fresh go_handlers go_bare_resolves
output="$("$python" "$checker" "$work/go_bare_resolves" 2>&1)"
status=$?
if [ "$status" -ne 0 ]; then
  printf '  CLEAN EXPECTED, GOT EXIT %s  go_bare_resolves\n' "$status"
  printf '%s\n' "$output" | sed 's/^/    /'
  fail=$((fail + 1))
else
  unreadable=0
  for row in healthz livez; do
    if printf '%s' "$output" | grep -q "contradiction-unreadable: $row:"; then
      printf '  STILL UNREADABLE         %s could not be resolved\n' "$row"
      unreadable=$((unreadable + 1))
    fi
  done
  if [ "$unreadable" -ne 0 ]; then
    fail=$((fail + 1))
  else
    printf '  clean, and both rows read  healthz, livez\n'
    pass=$((pass + 1))
  fi
fi

note "case 31 (THE BREAKING): with the bare-symbol search deleted, /healthz is
  unreadable again"
fresh go_handlers go_search_deleted
# The guard is deleted from a THROWAWAY COPY of the checker, on case 24's reasoning:
# removing the code is a stronger demonstration than configuring it away, and a copy
# beside the real checker is where it has to live because the module's own import
# guard refuses to run a checker that cannot reach anywaye_contract.
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
"$python" - "$checker" "$disabled_checker" <<'DELETED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
guard = '    tail = symbol.rsplit(".", 1)[-1]\n    if tail:'
assert guard in source, "the bare-symbol search moved; this proof must follow it"
# `tail != symbol` is the guard that was there, and it skipped every bare name.
Path(sys.argv[2]).write_text(
    source.replace(guard, '    tail = symbol.rsplit(".", 1)[-1]\n    if tail and tail != symbol:', 1)
)
DELETED
output="$("$python" "$disabled_checker" "$work/go_search_deleted" 2>&1)"
if printf '%s' "$output" | grep -q "contradiction-unreadable: healthz:"; then
  printf '  the defect is back         healthz is unreadable with the search gone\n'
  pass=$((pass + 1))
else
  printf '  THE DEFECT DID NOT RETURN  the deleted search changed nothing\n'
  printf '%s\n' "$output" | sed 's/^/    /'
  fail=$((fail + 1))
fi

note "case 32 (THE BREAKING): a PARAMETER is not a definition, and the guard is
  what stops the search returning one"
# THE WRONG-ANSWER CASE, and it is not reachable through a registration line —
# nothing asks for a symbol that is both a real handler and a parameter name except
# a checker that has already read the line wrong. So it is asserted on the
# resolution itself, from a COPY of the checker with the guard removed, because the
# failure this prevents is not a warning: it is a file, and a confident one.
#
# `checks` is a parameter in this fixture — of `handleReadyz`, of `newRouter` and of
# `Serve` — so `func (o options) handleReadyz(checks []Check)` matches the looser
# `func\b.*\bchecks\b`, and the search returns `internal/httpapi/probes.go` as
# though a handler had been found there. Two assertions, and the second is the one
# that matters: the shipped checker resolves nothing, and the un-guarded copy
# resolves a file. Both, or the case proves nothing.
fresh go_handlers go_parameter_is_not_a_definition
"$python" - "$checker" "$disabled_checker" <<'UNGUARDED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
marker = "    if DEFINITION_KEYWORD.match(line) is None:\n        return False\n"
head, found, tail = source.partition(marker)
assert found, "the depth guard moved; this proof must follow it"
body_start = tail.index("    depth = 0\n    at = 0\n    while at < len(line):")
body_end = tail.index("    return False\n", body_start) + len("    return False\n")
loose = (
    '    return re.search(rf"^\\s*(?:def|func|fn|function|public|private|export)'
    '\\b.*\\b" + re.escape(name) + r"\\b", line) is not None\n'
)
# Delete the whole depth walk and restore the loose test the guard replaced.
unguarded = head + loose + "\n" + tail[:body_start] + tail[body_end:]
assert unguarded != source, "the patch changed nothing"
Path(sys.argv[2]).write_text(unguarded)
UNGUARDED

# One probe, run against both checkers, and the answer is printed by the probe so
# that a probe which CRASHES prints a traceback instead of an empty string. The
# first version of this case read an empty string as "the defect did not come back"
# and PASSED — which is the exact class of failure this repository exists to catch,
# committed to its own red proof.
probe_resolution() {
  "$python" - "$1" "$2" <<'PROBE'
import importlib.util
import sys
from pathlib import Path

checker_path = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(checker_path.parent))
spec = importlib.util.spec_from_file_location("resolution_probe", checker_path)
checker = importlib.util.module_from_spec(spec)
# Registered BEFORE it is executed: `@dataclass(frozen=True)` looks its own module
# up through `sys.modules`, and a module that is not in there raises
# `AttributeError: 'NoneType' object has no attribute '__dict__'` at import time.
sys.modules["resolution_probe"] = checker
spec.loader.exec_module(checker)

repo = Path(sys.argv[2])
resolved = checker._file_defining(repo, checker.module_index(repo), "checks")
print("NOTHING" if resolved is None else f"RESOLVED {resolved}")
PROBE
}

guarded_answer="$(probe_resolution "$checker" "$work/go_parameter_is_not_a_definition" 2>&1)"
unguarded_answer="$(probe_resolution "$disabled_checker" "$work/go_parameter_is_not_a_definition" 2>&1)"
if printf '%s' "$guarded_answer" | grep -q "Traceback"; then
  printf '  THE PROBE ITSELF IS BROKEN\n'
  printf '%s\n' "$guarded_answer" | sed 's/^/    /'
  fail=$((fail + 1))
elif printf '%s' "$unguarded_answer" | grep -q "Traceback"; then
  printf '  THE COPY IS BROKEN, NOT UNGUARDED\n'
  printf '%s\n' "$unguarded_answer" | sed 's/^/    /'
  fail=$((fail + 1))
elif [ "$guarded_answer" != "NOTHING" ]; then
  printf '  A PARAMETER RESOLVED       the shipped checker said %s\n' "$guarded_answer"
  fail=$((fail + 1))
elif [ "$unguarded_answer" = "NOTHING" ]; then
  printf '  THE DEFECT DID NOT RETURN  the un-guarded copy also resolved nothing\n'
  fail=$((fail + 1))
else
  printf '  nothing, and the guard is what does it\n'
  printf '    shipped:   %s\n' "$guarded_answer"
  printf '    unguarded: %s\n' "$unguarded_answer"
  pass=$((pass + 1))
fi

# ---------------------------------------------------------------------------
# CASES 33-35: THE HANDLER IN THE HANDLER POSITION.
#
# `_last_symbol` returned the LAST identifier on a registration line whatever it was.
# identity's httpapi.go:246 is
#
#     r.Get("/readyz", o.handleReadyz(checks))
#
# so it returned `checks` — a parameter — and the row came back
# `contradiction-unreadable` on the line DIRECTLY BELOW `/healthz`, which resolved
# because `handleHealthz` is both bare and last. Right on one line, wrong on the
# next, for a reason with nothing to do with the service.
#
# The fix cannot be "prefer the callee", because identity also writes
# `mux.HandleFunc("GET /v1/x", o.requireAccount(o.handleGetMessage))` and there the
# callee is a MIDDLEWARE and the handler is its argument. Those two lines are
# syntactically identical — a call of a call with a bare identifier inside — so the
# line cannot decide and the REPOSITORY has to. Hence a LIST of candidates, innermost
# first, each tried until one resolves.
# ---------------------------------------------------------------------------

note "case 33: /readyz is readable — the callee, not its argument"
# The row the packet was written about, and the assertion is about ABSENCE of a
# warning rather than presence of a route: a checker that stopped resolving anything
# would pass this too, which is why 34 deletes the rule rather than trusting it.
fresh go_handlers go_readyz_reads
output="$("$python" "$checker" "$work/go_readyz_reads" 2>&1)"
if printf '%s' "$output" | grep -q "contradiction-unreadable: readyz:"; then
  printf '  STILL UNREADABLE         readyz could not be resolved\n'
  fail=$((fail + 1))
else
  printf '  clean, and the row read   readyz\n'
  pass=$((pass + 1))
fi

note "case 34 (THE BREAKING): with the candidate list deleted, /readyz is
  unreadable again"
fresh go_handlers go_candidates_deleted
"$python" - "$checker" "$disabled_checker" <<'CANDIDATES'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()

# The function as it was: the LAST identifier on the line, whatever it was. Measured
# against the three fixture registrations that is `checks` on the /readyz line,
# `handleHealthz` on `/healthz` and `o.handleWrapped` on `/wrapped` — so the defect
# this case restores is specific to a handler FACTORY and invisible on the other two.
old = (
    'def _last_symbol(line: str) -> str | None:\n'
    '    """The handler-shaped token a chi or Hono registration line ends with."""\n'
    '    for candidate in reversed(re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", line)):\n'
    '        if candidate in ("HandleFunc", "Handle", "get", "post", "put", "patch",\n'
    '                         "delete", "head", "options"):\n'
    '            continue\n'
    '        return candidate\n'
    '    return None\n'
)
start = "def _handler_candidates(line: str) -> tuple[str, ...]:"
end = "def _file_defining(repo: Path, index: dict[str, str], symbol: str) -> str | None:"
# TWO edits, and both are needed. Replacing the candidate list alone would leave
# `handler_for` calling a function that no longer exists, which raises rather than
# reproducing the defect — and the first version of this case did exactly that and
# was caught only because the case asserts on the run's exit status.
# The call site is in `handler_for`, which sits ABOVE `_handler_candidates` in this
# file, so it is in `head` — patching the callee alone leaves the loop calling a
# function that no longer exists, which raises instead of reproducing the defect.
# Three earlier versions of this case got that partition wrong in one direction or
# the other and the `assert` below is what turned each of them into a red instead of
# a case that quietly passed against the PREVIOUS case's copy.
head, found, rest = source.partition(start)
assert found, "_handler_candidates moved; this proof must follow it"
body, closer, _tail = rest.partition(end)
assert closer, "_file_defining moved; this proof must follow it"
old_call = (
    "    for candidate in _handler_candidates(line):\n"
    "        resolved = _file_defining(repo, index, candidate)\n"
    "        if resolved is not None:\n"
    "            return resolved\n"
    "    return None\n"
)
new_call = (
    "    found = _last_symbol(line)\n"
    "    return _file_defining(repo, index, found) if found else None\n"
)
assert old_call in head, "the candidate loop moved; this proof must follow it"
patched = (
    head.replace(old_call, new_call, 1) + old + body + closer + _tail
)
# `def _handler_candidates` rather than the bare name: `handler_for`'s own comment
# cites it, and an assertion that trips on a COMMENT would leave this case running
# against whatever `$disabled_checker` held before — which is how the first version
# of this case passed while testing case 32's copy instead of its own.
assert "def _handler_candidates" not in patched, "the candidate list survived the patch"
Path(sys.argv[2]).write_text(patched)
CANDIDATES
output="$("$python" "$disabled_checker" "$work/go_candidates_deleted" 2>&1)"
if printf '%s' "$output" | grep -q "contradiction-unreadable: readyz:"; then
  printf '  the defect is back         readyz is unreadable with the list gone\n'
  pass=$((pass + 1))
else
  # The copy is REBUILT from the checker every time rather than assumed fresh, and
  # the two ways this can go wrong are both reported rather than folded into one
  # message: a traceback means the patch produced a checker that does not run, and
  # silence means it ran and still resolved the row. They are different failures and
  # only one of them is the defect not coming back.
  if printf '%s' "$output" | grep -q "Traceback"; then
    printf '  THE COPY DOES NOT RUN      the patch produced a broken checker\n'
  else
    printf '  THE DEFECT DID NOT RETURN  the deleted candidate list changed nothing\n'
  fi
  printf '%s\n' "$output" | sed 's/^/    /'
  fail=$((fail + 1))
fi

note "case 35 (THE DIRECTION): the INNERMOST candidate wins, so a middleware does
  not stand in for the handler it wraps"
# The other half, and it is the half a "prefer the callee" fix gets wrong. Without
# it, case 34 could be satisfied by always answering with the OUTERMOST symbol: on
# `/readyz` that is right and on `/wrapped` it is the middleware. So this asserts the
# resolution itself for both rows, from a probe that reports what was chosen, and it
# asserts that `/wrapped` did NOT resolve to the middleware.
fresh go_handlers go_innermost_wins
"$python" - "$checker" "$disabled_checker" <<'PROBE_COPY'
import sys
from pathlib import Path

# The same copy, unpatched, purely so both halves are read from one file.
Path(sys.argv[2]).write_text(Path(sys.argv[1]).read_text())
PROBE_COPY
resolved_for_row() {
  "$python" - "$1" "$2" "$3" <<'ROW'
import importlib.util
import sys
from pathlib import Path

checker_path = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(checker_path.parent))
spec = importlib.util.spec_from_file_location("row_probe", checker_path)
checker = importlib.util.module_from_spec(spec)
sys.modules["row_probe"] = checker
spec.loader.exec_module(checker)

repo = Path(sys.argv[2])
line_number = int(sys.argv[3])
registration = checker.Registered(
    method="GET", path="/x", recogniser="chi",
    file="internal/httpapi/router.go", line=line_number,
)
resolved = checker.handler_for(repo, registration, checker.module_index(repo))
print("NOTHING" if resolved is None else resolved)
ROW
}
# The two registration lines are READ OUT OF THE FIXTURE'S OWN DECLARATION rather than
# written down. They used to be 40 and 42, and an edit to `router.go`'s comment block
# moved both to 50 and 52 — which made this case print `READYZ RESOLVED ELSEWHERE
# NOTHING` and fail for a reason that had nothing to do with which symbol wins. The
# declaration's `registeredAt` is the one place in the fixture that already asserts
# where each route is, so asking it here cannot drift from it.
declared_line() {
  awk -v id="$1" '
    $1 == "-" && $2 == "id:" && $3 == id { found = 1; next }
    found && $1 == "line:" { print $2; exit }
  ' "$work/go_innermost_wins/account_scope.yml"
}
readyz="$(resolved_for_row "$checker" "$work/go_innermost_wins" "$(declared_line readyz)" 2>&1)"
wrapped="$(resolved_for_row "$checker" "$work/go_innermost_wins" "$(declared_line wrapped)" 2>&1)"
# Both resolve to probes.go, and the /wrapped answer is specifically NOT the
# middleware — that is the assertion, because `probes.go` is where `requireSession`
# lives too, so a bare filename comparison would not catch it.
middleware="$(grep -n 'func (o options) requireSession' "$work/go_innermost_wins/internal/httpapi/probes.go" | cut -d: -f1)"
if printf '%s' "$readyz" | grep -q Traceback || printf '%s' "$wrapped" | grep -q Traceback; then
  printf '  THE PROBE ITSELF IS BROKEN\n'
  printf '    readyz:  %s\n    wrapped: %s\n' "$readyz" "$wrapped"
  fail=$((fail + 1))
elif [ "$readyz" != "internal/httpapi/probes.go" ]; then
  printf '  READYZ RESOLVED ELSEWHERE   %s\n' "$readyz"
  fail=$((fail + 1))
elif [ "$wrapped" != "internal/httpapi/probes.go" ]; then
  printf '  WRAPPED RESOLVED ELSEWHERE  %s\n' "$wrapped"
  fail=$((fail + 1))
elif [ "$middleware" != "83" ]; then
  # Not an assertion about the answer: a guard on this case's own premise, so that a
  # fixture edit which moved the middleware cannot leave 35 passing vacuously. The
  # line number is written down rather than discovered, because "the middleware is
  # somewhere in this file" would be satisfied by the middleware being absent.
  printf '  THE FIXTURE MOVED          requireSession is at line %s, not 83\n' "$middleware"
  fail=$((fail + 1))
else
  printf '  innermost first, and it is right both ways\n'
  printf '    readyz  -> o.handleReadyz      (outer; `checks` is not a definition)\n'
  printf '    wrapped -> o.handleWrapped     (inner; not the middleware at :%s)\n' \
    "$middleware"
  pass=$((pass + 1))
fi

# ---------------------------------------------------------------------------
# CASES 36-44: A GATE THAT IS NOT ON THE ROUTE'S OWN LINE.
#
# gateway's `GET /v1/me` is `app.get("/v1/me", (c) => c.json(c.get("principal")))` at
# src/index.ts:187, and the gate that scopes it is `app.use("/v1/*", …)` at
# src/index.ts:160 — TWENTY-SEVEN LINES ABOVE, with the file's own comment at :157
# saying that Hono answers in registration order and so a route registered after a
# `use` IS behind it.
#
# `Recogniser.carries_handler` is False for Phoenix and axum for precisely this
# reason — "for those two the route's own line says nothing about scoping, and
# reporting it would report courier's real router as unscoped" — and a Hono route
# with an INLINE handler is a third member of that set which was not in it. What it
# produced was `scoping-bypassed` on a CORRECT route, on gateway's only route that
# resolves an account, which is the wolf.
#
# AND THE FIX IS NOT "PUT HONO IN THE FALSE SET". That would make the checker
# permanently silent about a bypass on every inline-handler route — and gateway's
# `/v1/me` is one, so it would turn that repository green for a FALSE reason, which
# is the worst outcome this format has. The answer is that the chain a Hono app runs
# before a handler IS readable: it is `app.use`, registered above, and it is read.
#
#   36. the control   one Hono app, one gate mounted above two routes — one gated
#                     through the chain, one gated on the line. CLEAN.
#   37. chain gate    `requireJwt` deleted from the `app.use` body, declaration
#                     untouched. RED: the direction the fix must not lose.
#   38. line gate     `requireAccount` deleted from the registration line. RED, and
#                     it is the shape that already worked — a checker that learned to
#                     read the chain has not stopped reading the line.
#   39. wrong prefix  a `/v2` route declared through the `/v1` gate. RED, and it is
#                     here because 36 is satisfiable by a coverage test that claims
#                     every mount covers every route.
#   40. composed      a sub-application mounted by `app.route`, so the gate is two
#                     hops away and CANNOT be read. NOT named — "I cannot see it" is
#                     the only honest answer and it is not "unscoped".
#   41. THE BREAKING  with the chain deleted from a copy of the checker, 36 goes red
#   42. THE BREAKING  with the prefix comparison deleted, 39 PASSES again — the
#                     false green the comparison exists to prevent
#   43. THE BREAKING  with the composition rule deleted, 40 IS named — the wolf
#   44. not a probe   a probe BEHIND the gate resolves no account and is not
#                     accused, because the chain is not account evidence and saying
#                     so would accuse every authenticated probe in the fleet
#
#   45-49 are on `hono_surface`, which is what `hono_pipeline` cannot reach: a gate
#   that is not ABOVE the route, a gate that is not there, and the alternative that
#   §1 of the report rejects.
# ---------------------------------------------------------------------------

note "case 36 (control): a Hono gate mounted ABOVE the route, and both shapes"
fresh hono_pipeline hono_pipeline
expect_clean hono_pipeline

note "case 37: the CHAIN gate deleted, and the row still says the route is scoped"
fresh hono_pipeline hono_chain_gate_deleted
if "$python" - "$work/hono_chain_gate_deleted/src/index.ts" <<'CHAIN'
import sys
from pathlib import Path

path = Path(sys.argv[1])
before = "      return jwt.requireJwt(c, next);"
assert before in path.read_text(), "the fixture's gate call moved; this proof must follow it"
path.write_text(path.read_text().replace(before, "      return next();", 1))
CHAIN
then
  expect_red hono_chain_gate_deleted "account-scope.scoping-bypassed: me:"
else
  unapplied "case 37"
fi

note "case 38: the LINE gate deleted, which is the shape that already worked"
fresh hono_pipeline hono_line_gate_deleted
if "$python" - "$work/hono_line_gate_deleted/src/index.ts" <<'LINE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
before = 'app.get("/v1/things", requireAccount, '
assert before in path.read_text(), "the fixture's inline gate moved; this proof must follow it"
path.write_text(path.read_text().replace(before, 'app.get("/v1/things", ', 1))
LINE
then
  expect_red hono_line_gate_deleted "account-scope.scoping-bypassed: things:"
else
  unapplied "case 38"
fi

# hono_under_v2 <dir> — a route on a prefix the app has NO mount for, declared
# through the gate the `/v1/*` mount carries. Shared by case 39 and by case 42,
# which is the whole point of sharing it: 42 patches a COPY OF THE CHECKER and runs
# it against the identical repository, so the only difference between the two
# answers is the code under test. Two separate edits would be two chances for the
# two repositories to drift apart.
hono_under_v2() {
  "$python" - "$1/src/index.ts" "$1/account_scope.yml" <<'UNDER_V2'
import sys
from pathlib import Path

router, declaration = (Path(item) for item in sys.argv[1:3])
text = router.read_text()
anchor = "  return app;\n"
assert anchor in text, "the fixture's tail moved; this proof must follow it"
added = (
    "  // A route on a prefix NOTHING is mounted on. It declares `via: requireJwt`,\n"
    "  // and the only mount above it is `/v1/*`, which is a different prefix: a\n"
    "  // coverage test that ignored the prefix would clear this row.\n"
    '  app.get("/v2/whoami", (c) => c.json(c.get("principal")));\n'
    "\n"
)
router.write_text(text.replace(anchor, added + anchor, 1))
# The line is READ rather than written down, because a hardcoded one drifts the
# moment the fixture's comment block changes and a red proof that points at the
# wrong line is a red proof asserting nothing.
at = next(
    number
    for number, line in enumerate(router.read_text().splitlines(), start=1)
    if "/v2/whoami" in line
)
row = (
    "  - id: v2-whoami\n"
    "    kind: http\n"
    "    method: GET\n"
    "    path: /v2/whoami\n"
    "    accountScoped: true\n"
    "    accountFrom:\n"
    "      via: requireJwt\n"
    "      file: src/middleware/jwt.ts\n"
    "      line: 24\n"
    "    registeredAt:\n"
    "      file: src/index.ts\n"
    f"      line: {at}\n"
)
text = declaration.read_text()
assert "  - id: readyz\n" in text, "the fixture's last row moved; this proof must follow it"
text = text.replace("minimum: 4", "minimum: 5", 1)
declaration.write_text(text.replace("  - id: readyz\n", row + "  - id: readyz\n", 1))
UNDER_V2
}

note "case 39: a mount on ANOTHER prefix does not clear this route's gate"
fresh hono_pipeline hono_wrong_prefix
if hono_under_v2 "$work/hono_wrong_prefix"; then
  expect_red hono_wrong_prefix "account-scope.scoping-bypassed: v2-whoami:"
else
  unapplied "case 39"
fi

note "case 40: a sub-application mounted by app.route — the gate CANNOT be read,
  and not reading it is not the same as calling the route unscoped"
fresh hono_composed hono_composed
expect_not_named hono_composed "account-scope.scoping-bypassed"

note "case 41 (THE BREAKING): with the chain deleted, the inline route behind it
  is called unscoped again"
fresh hono_pipeline hono_chain_reader_deleted
# The chain is deleted from a THROWAWAY COPY of the checker, for case 24's reasons:
# no environment variable in the shipped file, because an answer that depends on who
# is asking is not an answer about the repository; and a copy is the stronger
# demonstration, because it removes the code rather than configuring it away.
# Beside the real checker rather than in $work, because the module's own import
# guard refuses to run a copy that cannot reach anywaye_contract — and that refusal
# is correct.
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
if "$python" - "$checker" "$disabled_checker" <<'DELETED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
before = (
    "if readable and handler_is_readable and chain_read and not (on_line or in_chain):"
)
after = "if readable and handler_is_readable and chain_read and not on_line:"
assert before in source, "the gate decision moved; this proof must follow it"
assert "not in_chain" not in source.replace(before, ""), "the chain has a second reader"
Path(sys.argv[2]).write_text(source.replace(before, after, 1))
DELETED
then
  output="$("$python" "$disabled_checker" "$work/hono_chain_reader_deleted" 2>&1)"
  if printf '%s' "$output" | grep -q "account-scope.scoping-bypassed: me:"; then
    printf '  the defect is back         the inline route behind a use is called unscoped\n'
    pass=$((pass + 1))
  else
    # The two ways this can go wrong are reported apart rather than folded into one
    # message, because only one of them is the defect not coming back.
    if printf '%s' "$output" | grep -q Traceback; then
      printf '  THE COPY DOES NOT RUN      the patch produced a broken checker\n'
    else
      printf '  THE DEFECT DID NOT RETURN  the deleted chain changed nothing\n'
    fi
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  fi
else
  unapplied "case 41"
fi

note "case 42 (THE BREAKING): with the prefix comparison deleted, the /v2 row is
  cleared by the /v1 gate — which is the false green the comparison prevents"
fresh hono_pipeline hono_prefix_comparison_deleted
hono_under_v2 "$work/hono_prefix_comparison_deleted" || unapplied "case 42"
"$python" - "$checker" "$disabled_checker" <<'NOPREFIX' || unapplied "case 42"
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
before = (
    '    if text.endswith("/*"):\n'
    '        prefix = canonical(text[:-2].rstrip("/"))\n'
    '        return canonical(path).startswith(prefix.rstrip("/") + "/"), True\n'
)
after = '    if text.endswith("/*"):\n        return True, True\n'
assert before in source, "the prefix comparison moved; this proof must follow it"
Path(sys.argv[2]).write_text(source.replace(before, after, 1))
NOPREFIX
output="$("$python" "$disabled_checker" "$work/hono_prefix_comparison_deleted" 2>&1)"
if ! printf '%s' "$output" | grep -qE 'account-scope\.|^(OK|FAIL) '; then
  printf '  THE COPY IS BROKEN, NOT UNGUARDED\n'
  printf '%s\n' "$output" | sed 's/^/    /'
  fail=$((fail + 1))
elif printf '%s' "$output" | grep -q "account-scope.scoping-bypassed"; then
  printf '  STILL FINDS IT             the prefix is not what makes case 39 red\n'
  printf '%s\n' "$output" | sed 's/^/    /'
  fail=$((fail + 1))
else
  printf '  false green, and the comparison is what stops it\n'
  printf '    /v1/* cleared a /v2 route once the prefix stopped being compared\n'
  pass=$((pass + 1))
fi

note "case 43 (THE BREAKING): with the composition rule deleted, the mounted
  sub-application's route IS accused — the wolf this case's fixture exists to stop"
fresh hono_composed hono_composition_rule_deleted
if "$python" - "$checker" "$disabled_checker" <<'COMPOSED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
before = "    readable = not composed\n"
after = "    readable = True\n"
assert before in source, "the composition rule moved; this proof must follow it"
Path(sys.argv[2]).write_text(source.replace(before, after, 1))
COMPOSED
then
  output="$("$python" "$disabled_checker" "$work/hono_composition_rule_deleted" 2>&1)"
  if printf '%s' "$output" | grep -q "account-scope.scoping-bypassed: me:"; then
    printf '  the wolf is back           a mounted sub-app route is called unscoped\n'
    pass=$((pass + 1))
  else
    if printf '%s' "$output" | grep -q Traceback; then
      printf '  THE COPY DOES NOT RUN      the patch produced a broken checker\n'
    else
      printf '  THE WOLF DID NOT RETURN    the deleted rule changed nothing\n'
    fi
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  fi
else
  unapplied "case 43"
fi

note "case 44 (negative control): a probe BEHIND the gate resolves no account, so
  the gate is not evidence against it"
fresh hono_pipeline hono_probe_behind_gate
expect_not_named hono_probe_behind_gate "declaration-contradicts-code: readyz"

# ---------------------------------------------------------------------------
# CASES 45-49, ON THE `hono_surface` FIXTURE: EVERY WAY A GATE CAN BE ABSENT.
#
# `hono_pipeline` decides what a chain reader may conclude once it can SEE a mount.
# It cannot reach the four ways the mount is not in front of the route, and all four
# are false greens waiting to happen:
#
#   45. commented      the `app.use` block commented out, LINE FOR LINE. Deleting it
#                      instead shifts every `registeredAt` below it, every row goes
#                      `stale`, and the case goes red for a reason that has nothing
#                      to do with gates
#   46. below          the SAME gate, MOVED below the route. Hono answers in
#                      registration order, so a gate mounted after the route it exists
#                      to guard is a gate that does not run — guard says so about its
#                      own rate limiter — and nothing else in the file distinguishes
#                      the two arrangements. A SWAP rather than a move was the first
#                      version and it went clean by moving the route's own line
#   47. not covered    a route the mount does not cover and whose OWN line has no
#                      gate. The row `hono_pipeline`'s `/v1/things` cannot be: that
#                      one is covered by the mount, so it proves `via` is compared
#                      rather than that COVERAGE is
#   48. the inline arm the same route declared `accountScoped: false`. The OTHER half
#                      of gateway's `/v1/me`, and the half that must not be quieted to
#                      fix the first: `c.get("principal")` on the registration line IS
#                      account evidence, so a row saying `false` is a lie
#   49. THE DIRECTION `carries_handler=False` on the Hono recogniser — the change
#                      that looks like it settles §1 and does not — leaves 45's
#                      repository, where the gate is genuinely GONE, clean. It cannot
#                      be right, and this is the measurement that says so
#
# 49 is not a breaking case and does not pretend to be: it asserts nothing about the
# shipped checker and everything about the ALTERNATIVE, which is the only way the
# claim in `REPORT-core-hono-inline-01` §1 can be checked by a reader rather than
# taken on trust.
# ---------------------------------------------------------------------------

note "case 45: the gate COMMENTED OUT, line for line"
# And the edit is chosen for what it does NOT do: it does not move a line. Deleting
# the `if (jwt) { app.use(…) }` block shifts `/v1/me`, `/ops/diagnostics`,
# `/auth/session` and `/v1/ready` up by seven, every row's `registeredAt` goes
# `stale`, and the case goes red for a reason with nothing to do with gates — a red
# proof's own version of the grep that reports "darkroom has no routes".
#
# `requireJwt` still exists in `src/middleware/jwt.ts` and `accountFrom` still points
# at the claim line, so this is a row whose `via` nothing calls: precisely what the
# finding is for. A commented `use` is not a `use` — the same seam, and the same
# function, as `registration-commented`.
fresh hono_surface hono_gate_commented
if "$python" - "$work/hono_gate_commented/src/index.ts" <<'GATE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
gate = lines[54:61]  # src/index.ts:55-61, asserted below rather than assumed
assert gate[0].rstrip() == "  if (jwt) {", "the gate moved; this proof must follow it"
assert 'app.use("/v1/*"' in gate[1], "the gate moved; this proof must follow it"
assert gate[-1].rstrip() == "  }", "the gate moved; this proof must follow it"
before = len(lines)
path.write_text(
    "".join(lines[:54])
    + "".join("// " + line if line.strip() else line for line in gate)
    + "".join(lines[61:])
)
# An `assert` on the LINE COUNT is what makes "this edit moves nothing" a claim
# rather than an intention, and it is the whole reason for this case's shape.
assert len(path.read_text().splitlines(keepends=True)) == before, "the edit moved a line"
GATE
then
  expect_red hono_gate_commented "account-scope.scoping-bypassed: v1-me"
else
  unapplied "case 45"
fi

note "case 46: the gate MOVED below the route it exists to guard"
# Hono answers in registration order, so a `use` registered after the route does not
# gate it. `c.get("principal")` is on the route's line in both arrangements and the
# file mounts no other middleware, so without this case a reader that accepted "an
# `app.use` naming `via` exists in this file" would pass 36's fixture and be wrong
# about every Hono gateway that mounts a limiter late — which is a real defect guard
# documents in its own source, about its own limiter, at src/index.ts:157.
#
# A MOVE, and not a swap of the two blocks, and the reason is this file's own lesson
# twice over. A swap moves `/v1/me`'s own registration up seven lines, so the row's
# `registeredAt` ends up pointing at the inside of the gate, the row stops being
# `REGISTERED`, `scoping-bypassed` is not decidable for it — and the case goes CLEAN
# for a reason that has nothing to do with order. Which is exactly what it did the
# first time. So: the gate is commented where it was and re-mounted below the route,
# and the three rows the insertion shifts are re-pointed, because a service that
# moves a middleware updates its declaration and the checker has to be reading the
# file as it now is.
#
# Two asserts carry the case: `/v1/me`'s line did NOT move, and the gate that names
# `requireJwt` is now BELOW it. Without the first, a breakage that moved the route
# would still satisfy the second.
fresh hono_surface hono_gate_below_route
if "$python" - "$work/hono_gate_below_route/src/index.ts" "$work/hono_gate_below_route/account_scope.yml" <<'SWAP'
import sys
from pathlib import Path

router, declaration = (Path(item) for item in sys.argv[1:3])
lines = router.read_text().splitlines(keepends=True)

gate = lines[54:61]  # src/index.ts:55-61
assert gate[0].rstrip() == "  if (jwt) {", "the gate moved; this proof must follow it"
assert 'app.use("/v1/*"' in gate[1], "the gate moved; this proof must follow it"
assert gate[-1].rstrip() == "  }", "the gate moved; this proof must follow it"
assert lines[62].rstrip() == "  if (jwt) {", "the route block moved; this proof must follow it"
assert 'app.get("/v1/me"' in lines[67], "the route moved; this proof must follow it"
assert lines[68].rstrip() == "  }", "the route block moved; this proof must follow it"

commented = ["// " + line if line.strip() else line for line in gate]
# Re-mounted after the route block, which closes on line 69. `/v1/me` is at 68 and
# does not move, because the insertion is BELOW it.
moved = lines[:54] + commented + lines[61:69] + gate + ["\n"] + lines[69:]
router.write_text("".join(moved))

after = router.read_text().splitlines()
route_at = next(n for n, l in enumerate(after, 1) if 'app.get("/v1/me"' in l)
gate_at = next(n for n, l in enumerate(after, 1) if "app.use(" in l and not l.startswith("//"))
assert route_at == 68, f"/v1/me moved to {route_at}; this case is about ORDER, not about it"
assert gate_at > route_at, f"the gate is at {gate_at}, still above the route at {route_at}"

# The rows the insertion pushed down, re-pointed by reading each one out of the
# ROUTER rather than by arithmetic, because arithmetic is a second thing to keep
# correct and a red proof that points at the wrong line asserts nothing.
text = declaration.read_text()
for path in ("/ops/diagnostics", "/auth/session", "/v1/ready"):
    at = next(n for n, l in enumerate(after, 1) if f'app.get("{path}"' in l)
    before = f'    path: {path}\n'
    assert before in text, f"the {path} row moved; this proof must follow it"
    head, _, row = text.partition(before)
    _, old, tail = row.partition("      line: ")
    number, _, row = tail.partition("\n")
    assert old and number.strip().isdigit(), f"the {path} row has no line; this proof must follow it"
    text = head + before + row.replace("      line: " + number, f"      line: {at}", 1)
declaration.write_text(text)
SWAP
then
  expect_red hono_gate_below_route "account-scope.scoping-bypassed: v1-me"
else
  unapplied "case 46"
fi

note "case 47: a route the mount does NOT cover, with its own line gate deleted"
# `/ops/diagnostics` is scoped through `requireJwt(jwt)` on its own registration
# line and sits outside `/v1/*`. Deleting the call leaves a row whose `via` nothing
# calls and no mount in the file to save it — which is what separates a reader that
# DECIDES coverage from one that accepts any mount.
#
# `hono_pipeline`'s case 38 is the other half and cannot stand in for this one: there
# the route IS covered by the mount and the finding is about `via`, so a reader that
# compared the symbol and ignored the prefix entirely would still pass it.
fresh hono_surface hono_ops_unscoped
if "$python" - "$work/hono_ops_unscoped/src/index.ts" <<'OPS'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
line = 'app.get("/ops/diagnostics", requireJwt(jwt), (c) => c.json(c.get("principal")));'
assert line in text, "the ops route moved; this proof must follow it"
path.write_text(text.replace(line, line.replace("requireJwt(jwt), ", ""), 1))
OPS
then
  expect_red hono_ops_unscoped "account-scope.scoping-bypassed: ops-diagnostics"
else
  unapplied "case 47"
fi

note "case 48: the SAME route declared accountScoped: false — the other half of
  guard's /v1/me, and the half that must still contradict"
# The finding this packet did NOT touch, and the case that says so. guard's `/v1/me`
# answers this one correctly: `c.get("principal")` on the registration line IS
# account evidence, so a row declaring it `false` is a lie and the checker says so.
# Quoting this arm would be "a fix that makes the checker quiet about it without
# making that visible" — the worst outcome available — so it is asserted here, in the
# same fixture, three cases after the arm it must not be traded for.
fresh hono_surface hono_inline_contradiction
if "$python" - "$work/hono_inline_contradiction/account_scope.yml" <<'INLINE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
scoped = """    accountScoped: true
    accountFrom:
      via: requireJwt
      file: src/middleware/jwt.ts
      # The line that reads `account_id` out of a verified claim.
      line: 59
"""
assert scoped in text, "the v1-me row moved; this proof must follow it"
path.write_text(text.replace(scoped, "    accountScoped: false\n    reason: public\n", 1))
INLINE
then
  # AND NOT `scoping-bypassed`: with the row declared `false` there is no `via` to be
  # bypassed, so a checker that reached for one here would be reporting a bypass on a
  # row that never claimed to be scoped.
  expect_red_but_not hono_inline_contradiction \
    "account-scope.declaration-contradicts-code: v1-me" \
    "account-scope.scoping-bypassed"
else
  unapplied "case 48"
fi

note "case 49 (THE DIRECTION): carries_handler=False on the Hono recogniser leaves a
  GENUINELY UNGATED route silent"
# The alternative rejected in REPORT-core-hono-inline-01 §1, measured rather than
# argued. `carries_handler=False` is the change that LOOKS like it settles this — the
# line is silent, so say nothing — and it does silence it. On 45's repository, where
# the gate was commented out and `/v1/me` really does resolve no account, it says
# nothing at all. So the flag would buy the false negative by accepting a real
# cross-account read, which is the trade `carries_handler`'s own docstring refuses.
fresh hono_surface hono_carries_handler_false
cp -R "$work/hono_gate_commented" "$work/hono_carries_handler_false"
if "$python" - "$checker" "$disabled_checker" <<'NO_FLAG'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
anchor = """        example='app.get("/v1/me", (c) => c.json(c.get("principal")));',
    ),"""
assert anchor in source, "the Hono recogniser moved; this proof must follow it"
patched = source.replace(
    anchor,
    """        example='app.get("/v1/me", (c) => c.json(c.get("principal")));',
        carries_handler=False,
    ),""",
    1,
)
assert patched != source, "the patch changed nothing"
Path(sys.argv[2]).write_text(patched)
NO_FLAG
then
  output="$("$python" "$disabled_checker" "$work/hono_carries_handler_false" 2>&1)"
  status=$?
  if printf '%s' "$output" | grep -q "account-scope.scoping-bypassed: v1-me"; then
    printf '  NOT WEAKER AFTER ALL       the flag still caught it, and §1 must be re-read\n'
    fail=$((fail + 1))
  elif [ "$status" -ne 0 ]; then
    printf '  IT FAILED FOR ANOTHER REASON  exit %s, so this case proves nothing\n' "$status"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  else
    printf '  the rejected flag is blind here, which is why §1 says no\n'
    printf '    a route with no gate at all, declared scoped, and the checker is quiet\n'
    pass=$((pass + 1))
  fi
else
  unapplied "case 49"
fi

# ---------------------------------------------------------------------------
# CASES 50-58, ON THE `go_runtime_prefix` FIXTURE: A PREFIX THAT IS CONFIGURATION.
# ---------------------------------------------------------------------------

note "case 50: the control — four registrations the checker cannot read, four
  correct rows, and a GREEN run"
# The control, and the shape of the whole decision in one assertion: the finding is
# NAMED and the exit code is 0, in the same case. `expect_warn` asserts both halves
# because a warning printed as a failure would be a different claim, and a failure
# here would be the declaration being blamed for the checker's blindness.
fresh go_runtime_prefix go_runtime_prefix
expect_warn go_runtime_prefix "account-scope.surface-unreadable"

note "case 51: NOT stale — the line the get-service row names DOES register the route"
# `stale` means "a declared entry point is no longer registered where the declaration
# says it is", and that is FALSE about api.gen.go:57. Before this, the fixture's one
# failure was exactly this false `stale` — the same false `stale` pantry ships in its
# own header, at the cost of an exit 1 on a service whose declaration is correct.
expect_not_named go_runtime_prefix "account-scope.stale"

note "case 52: and the row is STILL LISTED, at the line it is really on"
# The other direction, and the one a fix that turned the finding off would fail.
# `contradiction-unreadable` is courier's answer for a row nobody verified and it is
# silent in both directions — so "not `stale`" alone would be satisfied by a checker
# that had stopped saying anything about the row at all. The listing is the output a
# human skims for "is this route mounted?", and it must keep printing the route.
expect_listing go_runtime_prefix "not-account-scoped +GET /v1/services/\{name\} +\(internal/api/api\.gen\.go:57\)"

note "case 53 (THE BREAKING): with the fifth claim verdict deleted, /v1/services/{name}
  is stale again"
fresh go_runtime_prefix go_runtime_prefix_no_path_verdict
if "$python" - "$checker" "$disabled_checker" <<'NO_VERDICT'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
before = (
    "        elif unreadable_registrations(code):\n"
    "            claims.append(Claim(VERDICT_PATH_UNREADABLE, code, line, None))\n"
)
assert before in source, "the unreadable-path claim moved; this proof must follow it"
patched = source.replace(before, "", 1)
assert patched != source, "the patch changed nothing"
assert "VERDICT_PATH_UNREADABLE" in patched, (
    "every other mention went too, so this case would not be about the claim verdict"
)
Path(sys.argv[2]).write_text(patched)
NO_VERDICT
then
  output="$("$python" "$disabled_checker" "$work/go_runtime_prefix_no_path_verdict" 2>&1)"
  status=$?
  if printf '%s' "$output" | grep -q "account-scope.stale: get-service"; then
    printf '  the false stale is back   a mounted route is reported as not mounted\n'
    pass=$((pass + 1))
  elif printf '%s' "$output" | grep -q Traceback; then
    printf '  THE COPY DOES NOT RUN      the patch produced a broken checker'
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  else
    printf '  THE DEFECT DID NOT RETURN  the deleted verdict changed nothing, exit %s\n' "$status"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  fi
else
  unapplied "case 53"
fi

note "case 54 (THE BREAKING): with the per-file report deleted the run is still green
  and the finding is gone — only the number on the last line is left saying so"
# One of two falsifications, and the reason there are two is that the report and the
# count are two INDEPENDENT mechanisms and a reader can read either one. Deleting the
# finding leaves the count, so this case cannot be satisfied by a count alone; deleting
# the count leaves the finding, which is case 58. A reader who reads the findings
# block and not the summary line — which is the reader who acts on a warning — is the
# one case 54 is about.
#
# The claim branch is KEPT, and that is deliberate rather than convenient: it is what
# stops `get-service` going `stale`, so the copy reaches exit 0 the way pantry's three
# substring-saved rows already reach it today. Deleting it too would put the fixture
# back at exit 1 and prove nothing — that is case 53, and the two are two halves of
# one claim.
fresh go_runtime_prefix go_runtime_prefix_silent
if "$python" - "$checker" "$disabled_checker" <<'NO_REPORT'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
report_call = "    report.findings.extend(surface_findings(scan))\n"
assert report_call in source, "the surface report call moved; this proof must follow it"
patched = source.replace(report_call, "", 1)
assert patched.count(report_call) == 0, "the call site has a second reader"
assert "def surface_findings(" in patched, (
    "the whole function went too, so this case would be about deletion rather than "
    "about the call"
)
Path(sys.argv[2]).write_text(patched)
NO_REPORT
then
  output="$("$python" "$disabled_checker" "$work/go_runtime_prefix_silent" 2>&1)"
  status=$?
  if printf '%s' "$output" | grep -q Traceback; then
    printf '  THE COPY DOES NOT RUN      the patch produced a broken checker'
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  elif [ "$status" -ne 0 ]; then
    printf '  IT FAILED FOR ANOTHER REASON  exit %s, so this case proves nothing\n' "$status"
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  elif printf '%s' "$output" | grep -q 'account-scope.surface-unreadable'; then
    printf '  STILL FINDS IT             the deleted report is still reporting'
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  elif ! printf '%s' "$output" | grep -qE 'undeclared, [0-9]+ unreadable'; then
    printf '  NO COUNT AT ALL            there is nothing left saying so, and this is'
    printf '    not the case this was written for'
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  else
    printf '  the report is load-bearing  the count survives it; the finding does not:'
    printf '%s\n' "$output" | grep -E '^(OK|FAIL) ' | sed 's/^/    /'
    pass=$((pass + 1))
  fi
else
  unapplied "case 54"
fi

note "case 55: the floor is NOT satisfied by a route the checker could not read"
# Green before and green after, which is what makes it the control on case 50's green.
# If `surface.minimum` ever counted unreadable registrations, pantry would go from
# exit 1 to exit 0 with `minimum: 4` set and NO warning — a coverage number
# manufactured out of routes nobody read. This is the one edit that would produce
# exactly the dishonest zero this packet is required not to produce.
fresh go_runtime_prefix go_runtime_prefix_floor
if "$python" - "$work/go_runtime_prefix_floor/account_scope.yml" <<'FLOOR'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
assert "  minimum: 0\n" in text, "the fixture's floor moved; this proof must follow it"
path.write_text(text.replace("  minimum: 0\n", "  minimum: 4\n", 1))
FLOOR
then
  expect_red go_runtime_prefix_floor "account-scope.surface-thin"
else
  unapplied "case 55"
fi

note "case 56 (the false positive): a route-table HELPER taking a path it was handed
  is not this finding"
# `t.chiRouter.Get(pattern, traced(h))` — identity's own, at
# `internal/httpapi/auth.go:270`. `pattern` is a bare identifier with NO string
# literal in it, so it is not a route whose path is an expression this checker cannot
# evaluate: it is a function that mounts whatever it was given. A predicate that
# matched it would warn on four lines of identity and one line of this fixture, and a
# warning that fires on every Go service is a warning nobody reads — the argument
# REPORT-core-hono-inline-01 §2 makes about D45. The line is 71 and is asserted
# out of the file rather than written down, so a fixture edit cannot make this pass
# by agreeing with a hardcoded number.
helper_line="$(
  grep -n '^[[:space:]]*t\.chiRouter\.Get(' \
    "$fixtures/go_runtime_prefix/internal/api/api.gen.go" | cut -d: -f1
)"
if [ -n "$helper_line" ]; then
  expect_not_named go_runtime_prefix "api.gen.go:$helper_line"
else
  unapplied "case 56"
fi

note "case 57: the RESOLVABLE half gets the same answer — a const prefix on
  go_handlers' /v1/tenants/{tenantID}"
# REPORT-core-hono-inline-01 §3 measured the identifier-first recogniser and left
# it alone, and its reason was that recognising `socialLoginPrefix` honestly needs
# `socialLoginPrefix` and `oidc.PathLogin` resolved. That judgement is EXTENDED here
# rather than reversed: this case is `probePrefix`, a `const` in the same package —
# genuinely resolvable — and it gets the same warning and the same green. A rule that
# behaved differently for a const would be a rule that guesses harder when the value
# happens to be lying next to it, which is the same defect with a smaller blast
# radius.
fresh go_handlers go_const_prefix
if "$python" - "$work/go_const_prefix/account_scope.yml" "$work/go_const_prefix/internal/httpapi/router.go" <<'CONST'
import sys
from pathlib import Path

declaration, router = (Path(item) for item in sys.argv[1:3])
before = len(router.read_text().splitlines())
# APPENDED, never inserted, so the four rows `go_handlers` already declares keep the
# `registeredAt` lines they have. An insertion above line 43 would make every one of
# them `stale` and this case would go red for a reason that has nothing to do with
# path prefixes.
router.write_text(
    router.read_text()
    + """
// Added by case 57: the RESOLVABLE half of this defect. `tenantPrefix` is a `const`
// in this package, so its value IS in this tree — and the row below it is declared
// anyway, to establish that a resolvable prefix and an unresolvable one get the same
// answer rather than the const being quietly trusted more.
const tenantPrefix = "/v1/tenants"

func tenantRoutes(o options) chi.Router {
	r := chi.NewRouter()
	r.Get(tenantPrefix+"/{tenantID}", o.handleTenantSecrets)
	return r
}
"""
)
after = router.read_text().splitlines()
assert len(after) > before, "the append changed nothing"
# The path ENDS IN A PARAMETER, and that is the whole trick. `_mentions_on`'s second
# test is `canonical(path).split("/")[-1] in text`, so a row whose last segment is a
# word — `/internal/whoami`, `/v1/services` — is satisfied by that word appearing
# anywhere on the line, including inside the prefix's own tail. That is why three of
# `pantry`'s four rows go quiet today and only `get-service` goes red, and it is why
# this row ends in `{tenantID}`: its last canonical segment is `{}`, which appears in
# no Go file, so the substring accident cannot rescue the row and the answer has to
# come from the verdict rather than from an accident.
at = next(
    number
    for number, line in enumerate(after, start=1)
    if "tenantPrefix" in line and "handleTenantSecrets" in line
)
text = declaration.read_text()
assert "  - id: wrapped\n" in text, "the fixture's last row moved; this proof must follow it"
row = (
    "  # Added by case 57. A `const` prefix is the RESOLVABLE half of this defect and\n"
    "  # it is declared here on purpose, so the answer a reader gets for it is the same\n"
    "  # answer pantry gets for a prefix that is configuration: named, not invented.\n"
    "  - id: tenant-secrets\n"
    "    kind: http\n"
    "    method: GET\n"
    "    path: /v1/tenants/{tenantID}\n"
    "    accountScoped: false\n"
    "    reason: public\n"
    "    registeredAt:\n"
    "      file: internal/httpapi/router.go\n"
    f"      line: {at}\n"
)
declaration.write_text(text.replace("  - id: wrapped\n", row + "  - id: wrapped\n", 1))
CONST
then
  expect_warn go_const_prefix "account-scope.registration-path-unreadable"
else
  unapplied "case 57"
fi

note "case 58 (THE BREAKING): with the COUNT deleted, the summary says 0 unreadable
  over a surface with four"
# The headline number, falsified in the direction that matters. `Report.unreadable`
# is a field with a default of 0 and a line that assigns it; delete the line and the
# summary prints `0 unreadable` for a service whose four registrations were all
# dropped — which is the ORIGINAL defect wearing the new field's name, and strictly
# worse than the field being absent, because a reader who has learned to read the
# fifth number will believe it.
#
# So the count is printed on EVERY line rather than only when it is non-zero, and this
# case is why that is the decision: an omitted number is ambiguous between "zero" and
# "never computed", and this copy is the second reading. A checker that can print a
# wrong zero about its own coverage is worse than one that prints nothing, so the fix
# is not to hide the number — it is to make the number the one thing this checker
# cannot get wrong by accident, and that is what the fixture's own assertion below is.
fresh go_runtime_prefix go_runtime_prefix_no_count
if "$python" - "$checker" "$disabled_checker" <<'NO_COUNT'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
count_line = "    report.unreadable = len(scan.unreadable)\n"
assert count_line in source, "the unreadable count moved; this proof must follow it"
patched = source.replace(count_line, "", 1)
assert patched.count(count_line) == 0, "the count has a second reader"
assert "unreadable: int = 0" in patched, (
    "the field itself went, so this case would be about a field rather than about "
    "the count being computed"
)
Path(sys.argv[2]).write_text(patched)
NO_COUNT
then
  output="$("$python" "$disabled_checker" "$work/go_runtime_prefix_no_count" 2>&1)"
  if printf '%s' "$output" | grep -q Traceback; then
    printf '  THE COPY DOES NOT RUN      the patch produced a broken checker'
    printf '%s\n' "$output" | sed 's/^/    /'
    fail=$((fail + 1))
  elif ! printf '%s' "$output" | grep -q 'undeclared, 0 unreadable'; then
    printf '  THE DEFECT DID NOT RETURN  the copy does not print the wrong zero'
    printf '%s\n' "$output" | grep -E '^(OK|FAIL) ' | sed 's/^/    /'
    fail=$((fail + 1))
  else
    printf '  the wrong zero, and it is   the defect, restated in the new field:'
    printf '%s\n' "$output" | grep -E '^(OK|FAIL) ' | sed 's/^/    /'
    pass=$((pass + 1))
  fi
else
  unapplied "case 58"
fi

# And the positive half, on the SHIPPED checker over the same fixture: four, not zero.
# Without it case 58 could be satisfied by a checker that never prints the number at
# all and a `0` that came from somewhere else.
fresh go_runtime_prefix go_runtime_prefix_count_honest
output="$("$python" "$checker" "$work/go_runtime_prefix_count_honest" 2>&1)"
if printf '%s' "$output" | grep -q 'undeclared, 4 unreadable'; then
  printf '  and it says four           the fixture really has four unreadable'
  pass=$((pass + 1))
else
  printf '  THE COUNT IS WRONG         the fixture has four and the summary does not say so'
  printf '%s\n' "$output" | grep -E '^(OK|FAIL) ' | sed 's/^/    /'
  fail=$((fail + 1))
fi

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
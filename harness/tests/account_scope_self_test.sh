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
#
# CASES 26-29, ON THE `go_handlers` FIXTURE: how a definition search says no.
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
#   26. control         the fixture unbroken, which must be CLEAN. Without it a
#                                     checker that resolved nothing at all would
#                                     satisfy 27 and 28 for the wrong reason.
#   27. a bare symbol   `/healthz` registers `handleHealthz` with no receiver, so
#                                     the symbol is bare and the deleted guard
#                                     could not reach it. `/livez` — which has
#                                     always resolved — is the control INSIDE the
#                                     case, so a fix that switched resolution off
#                                     cannot pass by looking like one that turned
#                                     it on.
#   28. the breaking    with the bare-symbol search deleted from a COPY of the
#                                     checker, `/healthz` is unreadable again
#   29. the breaking    the loose test this fix replaced also matched a PARAMETER
#                          — `func (o options) handleReadyz(checks []Check)` is
#                          `func\b.*\bchecks\b` — so a search for `checks` returned
#                          a FILE as though it had found a handler. This is the one
#                          case here that is not reachable through a registration
#                          line, because nothing asks for a symbol that is both a
#                          real handler and a parameter name except a checker that
#                          has already read the line wrong, so it is asserted on the
#                          resolution itself from a copy with the guard removed.
#
# Case 29's first version PASSED FOR THE WRONG REASON: the copy it probed crashed
# on import, the answer came back as an empty string, and an empty string is not
# `NOTHING`, so it took the pass branch. It is written down here because a red proof
# that cannot tell a crash from an answer is the thing this file is for, and the
# first version of it could not. The probe now registers its module in
# `sys.modules` before executing it, and a traceback in EITHER answer is a failure.
#
# Case 12's comment-stripping is a real rule, not a hypothetical: the recognisers
# match on a path literal and a comment carries one.
#
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness_dir="$(dirname "$here")"
core="$(dirname "$harness_dir")"
checker="$core/harness/account_scope_check.py"
fixtures="$here/fixtures/account-scope"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python="${CAFAYE_ACCOUNT_SCOPE_PYTHON:-}"
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
  echo "account_scope_self_test.sh: $checker is missing — this is not a cafaye/core" >&2
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
python - "$work/scoping_bypassed/internal/httpapi/router.go" <<'PY'
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
python - "$work/account_key_gone/internal/httpapi/account.go" <<'PY'
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
python - "$work/route_renamed/internal/httpapi/router.go" <<'PY'
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
python - "$work/surface_thin/internal/httpapi/router.go" <<'PY'
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
python - "$work/surface_empty/account_scope.yml" <<'PY'
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
python - "$work/duplicate_id/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text().replace("  - id: healthz\n", "  - id: list-messages\n", 1)
path.write_text(text)
PY
expect_red duplicate_id "account-scope.duplicate-id"

note "case 9: an undeclared key, which is a silent no-op everywhere else"
fresh conforming undeclared_key
python - "$work/undeclared_key/account_scope.yml" <<'PY'
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
python - "$work/parameter_spelling/account_scope.yml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(path.read_text().replace("/v1/messages/{id}", "/v1/messages/:id"))
PY
expect_clean parameter_spelling

note "case 12 (negative control): a route written in a COMMENT is not a route"
fresh conforming comment_only
python - "$work/comment_only/internal/httpapi/router.go" <<'PY'
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
python3 - "$work/nextjs_undeclared/src/app/v1/[...path]/route.ts" <<'NEXTJS'
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
python3 - "$work/nextjs_key_gone/src/middleware/requireAccount.ts" <<'MIDDLEWARE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(path.read_text().replace("accountId", "principalId"))
MIDDLEWARE
expect_red nextjs_key_gone "account-scope.account-key-lost"

note "case 15a: a chained axum router — two routes on one line, and the SECOND"
note "          one's method must not be read as the first one's"
fresh nextjs_surface chained_axum
python3 - "$work/chained_axum" <<'AXUM'
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
python3 - "$work/swapped_methods/account_scope.yml" <<'SWAP'
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
python3 - "$work/split_line_bypassed/internal/httpapi/admin.go" <<'SPLIT'
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
python3 - "$work/nothing_scoped/account_scope.yml" <<'FLIP'
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
python3 - "$work/key_guessed/account_scope.yml" <<'NOKEY'
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
# guard refuses to run a copy that cannot reach cafaye_contract — and that refusal
# is correct, so the copy is made where its neighbour is and deleted immediately.
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
trap 'rm -rf "$work" "$disabled_checker"' EXIT
python - "$checker" "$disabled_checker" <<'DISABLED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
call = "    contradictions = _check_contradictions(repo, points, matched)"
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
# CASES 26-29: GO HANDLER RESOLUTION. go_handlers, and the two ways a definition
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
# returned a file as though it had found a handler. Case 29 is that.
# ---------------------------------------------------------------------------

note "case 26 (control): the go_handlers fixture, unbroken, which must be CLEAN"
# Without this a checker that refused to resolve ANY handler would satisfy 27 and 28
# for the wrong reason, so the fixture is established as a service that declared its
# surface correctly before anything is asserted about which rows it can read.
fresh go_handlers go_control
expect_clean go_control

note "case 27: a BARE handler symbol resolves, and so does one already resolved"
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

note "case 28 (THE BREAKING): with the bare-symbol search deleted, /healthz is
  unreadable again"
fresh go_handlers go_search_deleted
# The guard is deleted from a THROWAWAY COPY of the checker, on case 24's reasoning:
# removing the code is a stronger demonstration than configuring it away, and a copy
# beside the real checker is where it has to live because the module's own import
# guard refuses to run a checker that cannot reach cafaye_contract.
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
trap 'rm -rf "$work" "$disabled_checker"' EXIT
python - "$checker" "$disabled_checker" <<'DELETED'
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

note "case 29 (THE BREAKING): a PARAMETER is not a definition, and the guard is
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
python - "$checker" "$disabled_checker" <<'UNGUARDED'
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

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
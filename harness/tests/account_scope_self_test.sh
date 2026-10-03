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
#   13. no declaration missing      every repository in the fleet today, and the
#                                     answer has to be a FAILURE: a service that
#                                     has not declared its boundary has not proven
#                                     one, and inferring an answer is D18
#   14. unreadable      unreadable   a file the harness's own reader refuses
#   15. two services    WARN, green  this file and tenancy.yml naming different
#                                     repositories — a copy somebody made
#   16. nothing scoped  WARN, green  a surface where no entry point is
#                                     account-scoped. A WARNING and not a failure
#                                     because a shared library is a real state,
#                                     and a check with no way to say "this service
#                                     reaches no customer data" forces it to lie.
#   17. guessed key     WARN, green  no `accountKey` and no tenancy.yml, so the
#                                     account lines were searched for in four
#                                     spellings the checker chose rather than one
#                                     the service declared
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

note "case 13: the declaration is gone — which is the fleet's state today"
fresh conforming declaration_absent
rm "$work/declaration_absent/account_scope.yml"
expect_red declaration_absent "account-scope.declaration-missing"

note "case 14: the declaration is not a document the harness's own reader accepts"
fresh conforming declaration_unreadable
printf 'version: 1\nservice: [unclosed\n' > "$work/declaration_unreadable/account_scope.yml"
expect_red declaration_unreadable "account-scope.declaration-unreadable"

note "case 15 (warning): two declarations of one repository naming two services"
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

note "case 16 (warning): a surface on which nothing is account-scoped"
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

note "case 17 (warning): nothing named the tenancy key, so four were guessed"
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

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
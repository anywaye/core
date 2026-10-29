#!/usr/bin/env bash
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness_dir="$(dirname "$here")"
core="$(dirname "$harness_dir")"
checker="$core/harness/account_scope_check.py"
fixtures="$here/fixtures/account-scope"
work="$(mktemp -d)"
disabled_checkers="$harness_dir/_account_scope_registration_disabled.py $harness_dir/_account_scope_check_disabled.py"
trap 'rm -rf "$work" $disabled_checkers' EXIT

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

unapplied() {
  printf '  THE BREAKAGE DID NOT APPLY  the fixture or the proof moved, so %s did not run\n' "$1"
  fail=$((fail + 1))
}

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
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
"$python" - "$checker" "$disabled_checker" <<'DISABLED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
call = "    contradictions = _check_contradictions(repo, points, matched, claims)"
assert call in source, "the contradiction call moved; this proof must follow it"
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
fresh public_surface handler_absent
rm "$work/handler_absent/lib/public_web/controllers/version_controller.ex"
expect_warn handler_absent "account-scope.contradiction-unreadable"


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
expect_red_but_not registration_commented \
  "account-scope.registration-commented" "not-account-scoped GET /healthz"

note "case 27: the same repository with the floor lowered — the check alone must hold it"
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
expect_red_but_not registration_commented_floor_lowered \
  "account-scope.registration-commented" "account-scope.surface-thin"

expect_listing registration_commented_floor_lowered \
  '^  stale +GET /healthz +\(internal/httpapi/router.go:11\)'

note "case 28 (THE BREAKING): with the registration check deleted, the defect passes"
fresh conforming registration_check_disabled
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


note "case 29 (control): the go_handlers fixture, unbroken, which must be CLEAN"
fresh go_handlers go_control
expect_clean go_control

note "case 30: a BARE handler symbol resolves, and so does one already resolved"
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
disabled_checker="$harness_dir/_account_scope_check_disabled.py"
"$python" - "$checker" "$disabled_checker" <<'DELETED'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
guard = '    tail = symbol.rsplit(".", 1)[-1]\n    if tail:'
assert guard in source, "the bare-symbol search moved; this proof must follow it"
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
unguarded = head + loose + "\n" + tail[:body_start] + tail[body_end:]
assert unguarded != source, "the patch changed nothing"
Path(sys.argv[2]).write_text(unguarded)
UNGUARDED

probe_resolution() {
  "$python" - "$1" "$2" <<'PROBE'
import importlib.util
import sys
from pathlib import Path

checker_path = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(checker_path.parent))
spec = importlib.util.spec_from_file_location("resolution_probe", checker_path)
checker = importlib.util.module_from_spec(spec)
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


note "case 33: /readyz is readable — the callee, not its argument"
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
assert "def _handler_candidates" not in patched, "the candidate list survived the patch"
Path(sys.argv[2]).write_text(patched)
CANDIDATES
output="$("$python" "$disabled_checker" "$work/go_candidates_deleted" 2>&1)"
if printf '%s' "$output" | grep -q "contradiction-unreadable: readyz:"; then
  printf '  the defect is back         readyz is unreadable with the list gone\n'
  pass=$((pass + 1))
else
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
fresh go_handlers go_innermost_wins
"$python" - "$checker" "$disabled_checker" <<'PROBE_COPY'
import sys
from pathlib import Path

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
declared_line() {
  awk -v id="$1" '
    $1 == "-" && $2 == "id:" && $3 == id { found = 1; next }
    found && $1 == "line:" { print $2; exit }
  ' "$work/go_innermost_wins/account_scope.yml"
}
readyz="$(resolved_for_row "$checker" "$work/go_innermost_wins" "$(declared_line readyz)" 2>&1)"
wrapped="$(resolved_for_row "$checker" "$work/go_innermost_wins" "$(declared_line wrapped)" 2>&1)"
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
  printf '  THE FIXTURE MOVED          requireSession is at line %s, not 83\n' "$middleware"
  fail=$((fail + 1))
else
  printf '  innermost first, and it is right both ways\n'
  printf '    readyz  -> o.handleReadyz      (outer; `checks` is not a definition)\n'
  printf '    wrapped -> o.handleWrapped     (inner; not the middleware at :%s)\n' \
    "$middleware"
  pass=$((pass + 1))
fi


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


note "case 45: the gate COMMENTED OUT, line for line"
fresh hono_surface hono_gate_commented
if "$python" - "$work/hono_gate_commented/src/index.ts" <<'GATE'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
assert gate[0].rstrip() == "  if (jwt) {", "the gate moved; this proof must follow it"
assert 'app.use("/v1/*"' in gate[1], "the gate moved; this proof must follow it"
assert gate[-1].rstrip() == "  }", "the gate moved; this proof must follow it"
before = len(lines)
path.write_text(
    "".join(lines[:54])
    + "".join("// " + line if line.strip() else line for line in gate)
    + "".join(lines[61:])
)
assert len(path.read_text().splitlines(keepends=True)) == before, "the edit moved a line"
GATE
then
  expect_red hono_gate_commented "account-scope.scoping-bypassed: v1-me"
else
  unapplied "case 45"
fi

note "case 46: the gate MOVED below the route it exists to guard"
fresh hono_surface hono_gate_below_route
if "$python" - "$work/hono_gate_below_route/src/index.ts" "$work/hono_gate_below_route/account_scope.yml" <<'SWAP'
import sys
from pathlib import Path

router, declaration = (Path(item) for item in sys.argv[1:3])
lines = router.read_text().splitlines(keepends=True)

assert gate[0].rstrip() == "  if (jwt) {", "the gate moved; this proof must follow it"
assert 'app.use("/v1/*"' in gate[1], "the gate moved; this proof must follow it"
assert gate[-1].rstrip() == "  }", "the gate moved; this proof must follow it"
assert lines[62].rstrip() == "  if (jwt) {", "the route block moved; this proof must follow it"
assert 'app.get("/v1/me"' in lines[67], "the route moved; this proof must follow it"
assert lines[68].rstrip() == "  }", "the route block moved; this proof must follow it"

commented = ["// " + line if line.strip() else line for line in gate]
moved = lines[:54] + commented + lines[61:69] + gate + ["\n"] + lines[69:]
router.write_text("".join(moved))

after = router.read_text().splitlines()
route_at = next(n for n, l in enumerate(after, 1) if 'app.get("/v1/me"' in l)
gate_at = next(n for n, l in enumerate(after, 1) if "app.use(" in l and not l.startswith("//"))
assert route_at == 68, f"/v1/me moved to {route_at}; this case is about ORDER, not about it"
assert gate_at > route_at, f"the gate is at {gate_at}, still above the route at {route_at}"

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
      line: 59
"""
assert scoped in text, "the v1-me row moved; this proof must follow it"
path.write_text(text.replace(scoped, "    accountScoped: false\n    reason: public\n", 1))
INLINE
then
  expect_red_but_not hono_inline_contradiction \
    "account-scope.declaration-contradicts-code: v1-me" \
    "account-scope.scoping-bypassed"
else
  unapplied "case 48"
fi

note "case 49 (THE DIRECTION): carries_handler=False on the Hono recogniser leaves a
  GENUINELY UNGATED route silent"
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


note "case 50: the control — four registrations the checker cannot read, four
  correct rows, and a GREEN run"
fresh go_runtime_prefix go_runtime_prefix
expect_warn go_runtime_prefix "account-scope.surface-unreadable"

note "case 51: NOT stale — the line the get-service row names DOES register the route"
expect_not_named go_runtime_prefix "account-scope.stale"

note "case 52: and the row is STILL LISTED, at the line it is really on"
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
fresh go_handlers go_const_prefix
if "$python" - "$work/go_const_prefix/account_scope.yml" "$work/go_const_prefix/internal/httpapi/router.go" <<'CONST'
import sys
from pathlib import Path

declaration, router = (Path(item) for item in sys.argv[1:3])
before = len(router.read_text().splitlines())
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
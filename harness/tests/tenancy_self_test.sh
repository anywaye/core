#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURE="$HARNESS/tests/fixtures/tenancy/conforming"
SUBSTRATE_FIXTURE="$HARNESS/tests/fixtures/tenancy/substrate"
CREDENTIAL_FIXTURE="$HARNESS/tests/fixtures/tenancy/credential"
ZERO_FIXTURE="$HARNESS/tests/fixtures/tenancy/honest-zero"
KEY_CLAIM_FIXTURE="$HARNESS/tests/fixtures/tenancy/honest-zero-token-claim"
BLIND_FIXTURE="$HARNESS/tests/fixtures/tenancy/unreadable-language"
PUBLIC_READ_FIXTURE="$HARNESS/tests/fixtures/tenancy/public-read"
LIAR_FIXTURE="$HARNESS/tests/fixtures/tenancy/liar"

PY="${ANYWAYE_TENANCY_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "tenancy_self_test: no python >= 3.9 found; set ANYWAYE_TENANCY_PYTHON" >&2
  exit 1
fi

for required in "$FIXTURE" "$SUBSTRATE_FIXTURE" "$CREDENTIAL_FIXTURE" \
                "$ZERO_FIXTURE" "$KEY_CLAIM_FIXTURE" "$BLIND_FIXTURE" \
                "$PUBLIC_READ_FIXTURE" "$LIAR_FIXTURE"; do
  if [ ! -d "$required" ]; then
    echo "tenancy_self_test: a fixture is missing at $required" >&2
    exit 1
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/anywaye-tenancy-self-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

failures=0
breakages=0
warn_cases=0
green_cases=0
copy_name=""

fresh_copy() {
  copy_name="$1"
  local fixture="$2"
  local dst="$WORK/$copy_name"
  rm -rf "$dst"
  cp -R "$fixture" "$dst"
  printf '%s' "$dst"
}

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

if ! printf '%s' "$out" | grep -q '0 failure(s), 0 warning(s)'; then
  printf 'FAIL tenancy_self_test: the control — a service that declares every site it has — is not warning-free\n%s\n' \
    "$out" >&2
  failures=$((failures + 1))
fi


one="$(fresh_copy read-where "$FIXTURE")"
edit "$one/migrations/0001_assets.sql" \
  'select * from assets where id = $1 and account_id = $2' \
  'select * from assets where id = $1'
expect_red 'a read with its WHERE dropped' "$one" 'tenancy.scope-lost' 'asset-fetch'

two="$(fresh_copy bind-missing "$FIXTURE")"
edit "$two/src/assets.rb" \
  'DB.exec(SQL, checksum, account.account_id)' \
  'DB.exec(SQL, checksum)'
expect_red 'a bound account parameter nothing binds' "$two" 'tenancy.bind-missing' 'asset-checksum-bind'

three="$(fresh_copy list-unscoped "$FIXTURE")"
edit "$three/migrations/0001_assets.sql" \
  'select id, checksum, status from assets where account_id = $1 order by created_at' \
  'select id, checksum, status from assets order by created_at'
expect_red 'a list that lists the whole table' "$three" 'tenancy.scope-lost' 'asset-list'

four="$(fresh_copy update-unscoped "$FIXTURE")"
edit "$four/migrations/0001_assets.sql" \
  "update assets set status = 'settled' where id = \$1 and account_id = \$2" \
  "update assets set status = 'settled' where id = \$1"
expect_red 'an update that updates whichever row it is given' "$four" 'tenancy.entry-absent' 'asset-settle'

five="$(fresh_copy delete-unscoped "$FIXTURE")"
edit "$five/migrations/0001_assets.sql" \
  'delete from assets where id = $1 and account_id = $2' \
  'delete from assets where id = $1'
expect_red 'a delete that deletes whichever row it is given' "$five" 'tenancy.entry-absent' 'asset-delete'

six="$(fresh_copy idor-variant "$FIXTURE")"
edit "$six/migrations/0001_assets.sql" \
  'select * from asset_variants where id = $1 and account_id = $2' \
  'select * from asset_variants where id = $1'
expect_red 'a variant fetched by id with the scope dropped — an IDOR' "$six" 'tenancy.entry-absent' 'asset-variant-fetch'

seven="$(fresh_copy denial-weakened "$FIXTURE")"
edit "$seven/tests/tenancy_test.rb" \
  'assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?' \
  'assert_equal :forbidden, Assets.fetch("a1", account(OTHER_ACCOUNT))'
expect_red 'a negative assertion weakened from absent to forbidden' "$seven" 'tenancy.denial-missing' 'asset-fetch'

sevenb="$(fresh_copy positive-control-absent "$FIXTURE")"
edit "$sevenb/tenancy.yml" \
  '          expects: checksum
          file: tests/tenancy_test.rb
          line: 49' \
  '          expects: nil
          file: tests/tenancy_test.rb
          line: 49'
expect_red 'the positive control answered with nothing' "$sevenb" 'tenancy.positive-control-refused' 'own-account'

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


eight="$(fresh_copy location-missing "$FIXTURE")"
edit "$eight/tenancy.yml" '      file: migrations/0001_assets.sql
      line: 22' '      file: migrations/0002_assets_v2.sql
      line: 22'
expect_red 'a declaration naming a file this service does not have' "$eight" 'tenancy.location-missing' 'asset-fetch'

nine="$(fresh_copy line-missing "$FIXTURE")"
edit "$nine/tenancy.yml" 'line: 37' 'line: 900'
expect_red 'a declaration naming a line past the end of the file' "$nine" 'tenancy.line-missing' 'asset-variant-fetch'

ten="$(fresh_copy denial-refuses "$FIXTURE")"
edit "$ten/tenancy.yml" '      line: 22
    negative:
      asserts: absent' '      line: 22
    negative:
      asserts: forbidden'
expect_red 'a declaration that answers another account with a refusal' "$ten" 'tenancy.denial-refuses' 'asset-fetch'

eleven="$(fresh_copy undeclared "$FIXTURE")"
edit "$eleven/migrations/0001_assets.sql" \
  'delete from assets where id = $1 and account_id = $2' \
  'delete from assets where id = $1 and account_id = $2

-- added by a refactor nobody declared
select * from archive where account_id = $1'
expect_red 'an account-scoped query nobody declared' "$eleven" 'tenancy.undeclared-entry' 'archive'

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


thirteen="$(fresh_copy no-declaration "$FIXTURE")"
rm -f "$thirteen/tenancy.yml"
expect_red 'a service that declares no account boundary at all' "$thirteen" 'tenancy.declaration-missing'

fourteen="$(fresh_copy unreadable-declaration "$FIXTURE")"
printf 'version: 1\nentryPoints: [ \n' > "$fourteen/tenancy.yml"
expect_red 'a declaration the reader cannot parse' "$fourteen" 'tenancy.declaration-unreadable'

fifteen="$(fresh_copy scoped-but-silent "$ZERO_FIXTURE")"
edit "$fifteen/tenancy.yml" $'\naccountScoped: false' $'\naccountScoped: true'
expect_red 'a service that claims to scope by account and declares no way it does' \
  "$fifteen" 'tenancy.enumeration-empty'

sixteen="$(fresh_copy undeclared-key "$FIXTURE")"
edit "$sixteen/tenancy.yml" 'version: 1' 'version: 1
cache:
  enabled: false'
expect_red 'a declaration with a key the format does not declare' "$sixteen" 'tenancy.schema'


eighteen="$(fresh_copy rls-force-missing "$FIXTURE")"
edit "$eighteen/migrations/0002_rls.sql" \
  'alter table assets force row level security;
' ''
expect_red 'a table with policies whose owner bypasses them' "$eighteen" 'tenancy.rls-owner-bypass' 'assets'

nineteen="$(fresh_copy rls-not-enabled "$FIXTURE")"
edit "$nineteen/migrations/0002_rls.sql" \
  'alter table assets enable row level security;
' ''
expect_red 'policies that are never evaluated' "$nineteen" 'tenancy.rls-not-enabled' 'assets'

twenty="$(fresh_copy rls-policy-absent "$FIXTURE")"
edit "$twenty/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));

' ''
expect_red 'a policy the declaration names and the migrations do not' "$twenty" 'tenancy.rls-policy-absent' 'assets_select_own'

twentyone="$(fresh_copy rls-undeclared "$FIXTURE")"
edit "$twentyone/migrations/0002_rls.sql" \
  'alter table asset_variants force row level security;
' 'alter table asset_variants force row level security;

-- a table the declaration does not cover
alter table uploads enable row level security;
alter table uploads force row level security;
'
expect_red 'row-level-security DDL for a table nobody declared' "$twentyone" 'tenancy.rls-undeclared' 'uploads'

twentytwo="$(fresh_copy rls-permissive "$FIXTURE")"
edit "$twentytwo/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));' \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (true);'
expect_red 'a policy that constrains nothing' "$twentytwo" 'tenancy.rls-permissive' 'assets_select_own'

twentythree="$(fresh_copy rls-per-row "$FIXTURE")"
edit "$twentythree/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));' \
  'create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = app.current_account());'
expect_red 'an identity call that runs once per row' "$twentythree" 'tenancy.rls-per-row' 'assets_select_own'

twentyfour="$(fresh_copy rls-role-bypass "$FIXTURE")"
edit "$twentyfour/migrations/0002_rls.sql" \
  'create role tenant_app noinherit' \
  'create role tenant_app noinherit bypassrls'
expect_red 'a policy applied to a role that bypasses every policy' "$twentyfour" 'tenancy.rls-role-bypass' 'tenant_app'

twentyfourb="$(fresh_copy rls-role-undeclared "$FIXTURE")"
edit "$twentyfourb/migrations/0002_rls.sql" \
  'create policy assets_select_own on assets
  for select to tenant_app' \
  'create policy assets_select_own on assets
  for select to public, tenant_app'
expect_red 'a policy the DDL binds to a role the declaration does not name' \
  "$twentyfourb" 'tenancy.rls-permissive' 'assets_select_own'

twentyfive="$(fresh_copy rls-definer-search-path "$FIXTURE")"
edit "$twentyfive/migrations/0002_rls.sql" \
  '  stable
  security definer
  set search_path = '"''"'' \
  '  stable
  security definer'
expect_red 'a security definer function with a mutable search path' "$twentyfive" 'tenancy.rls-definer-search-path' 'app.current_account'

twentysix="$(fresh_copy rls-view-invoker "$FIXTURE")"
edit "$twentysix/migrations/0002_rls.sql" \
  'create view own_assets with (security_invoker = on) as' \
  'create view own_assets as'
expect_red 'a view that reads as its owner' "$twentysix" 'tenancy.rls-view-invoker' 'own_assets'

twentyseven="$(fresh_copy rls-unprotectable "$FIXTURE")"
edit "$twentyseven/migrations/0001_assets.sql" \
  'create table asset_variants (' \
  'create foreign table asset_variants ('
expect_red 'a policy on a relation row-level security cannot constrain' "$twentyseven" 'tenancy.rls-unprotectable' 'asset_variants'

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
  printf '  whose four policies per table are written by anywaye.protect_table:\n%s\n' "$substrate_out" >&2
  failures=$((failures + 1))
fi

substrate_no_call="$(fresh_copy substrate-no-call "$SUBSTRATE_FIXTURE")"
edit "$substrate_no_call/migrations/0002_substrate.sql" \
  "select anywaye.protect_table('assets');

-- The explicit spelling" \
  "-- deleted: the declaration still names what this call wrote.

-- The explicit spelling"
expect_red 'protect_table claimed for a table the migration never calls it on' \
  "$substrate_no_call" 'tenancy.rls-policy-absent' 'assets_anywaye_select'

substrate_typo="$(fresh_copy substrate-typo "$SUBSTRATE_FIXTURE")"
edit "$substrate_typo/tenancy.yml" 'assets_anywaye_select' 'assets_anywaye_read'
expect_red 'protect_table called for a table whose declaration spells the policy wrongly' \
  "$substrate_typo" 'tenancy.rls-policy-absent' 'assets_anywaye_read'

substrate_identity="$(fresh_copy substrate-identity "$SUBSTRATE_FIXTURE")"
edit "$substrate_identity/tenancy.yml" \
  '  identity: anywaye.current_account_id()' \
  '  identity: app.current_account()'
expect_red 'protect_table called for a table whose declaration names an identity no policy reads' \
  "$substrate_identity" 'tenancy.rls-permissive' 'protect_table'

expect_green 'the substrate, and the lines inside the template the entry-point scanner cannot classify' \
  "$SUBSTRATE_FIXTURE" 'enumeration-partial'

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
  printf '  a tree whose five policies on api_keys are written by anywaye.protect_credential_table:\n%s\n' \
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

credential_no_call="$(fresh_copy credential-no-call "$CREDENTIAL_FIXTURE")"
edit "$credential_no_call/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
-- deleted: the declaration still names what this call wrote."
expect_red 'protect_credential_table claimed for a table the migration never calls it on' \
  "$credential_no_call" 'tenancy.rls-policy-absent' 'api_keys_anywaye_resolve'

credential_four="$(fresh_copy credential-four "$CREDENTIAL_FIXTURE")"
edit "$credential_four/tenancy.yml" \
  "        - name: api_keys_anywaye_resolve
          command: select
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 742
" ""
expect_red 'a credential table whose declaration omits the resolve policy the template wrote' \
  "$credential_four" 'tenancy.rls-undeclared' 'api_keys_anywaye_resolve'

credential_no_digest="$(fresh_copy credential-no-digest "$CREDENTIAL_FIXTURE")"
edit "$credential_no_digest/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys');"
expect_red 'a protect_credential_table call the template refuses, resolved as no boundary at all' \
  "$credential_no_digest" 'tenancy.rls-policy-absent' 'api_keys_anywaye_resolve'

credential_wrong_table="$(fresh_copy credential-wrong-table "$CREDENTIAL_FIXTURE")"
edit "$credential_wrong_table/tenancy.yml" \
  "        - name: asset_variants_anywaye_delete
          command: delete
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
" "        - name: asset_variants_anywaye_delete
          command: delete
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
        - name: asset_variants_anywaye_resolve
          command: select
          clause: using
          roles: [tenant_fixture, tenant_fixture_app]
          constrained:
            file: migrations/0003_credential.sql
            line: 728
"
expect_red 'a resolve policy claimed on a table the ordinary call protects' \
  "$credential_wrong_table" 'tenancy.rls-policy-absent' 'asset_variants_anywaye_resolve'

credential_hand_written="$(fresh_copy credential-hand-written "$CREDENTIAL_FIXTURE")"
edit "$credential_hand_written/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
-- the call, removed: the five policies are written out by hand below.

create policy api_keys_anywaye_select on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (account_id = (select anywaye.current_account_id()));

create policy api_keys_anywaye_insert on api_keys
  for insert to tenant_fixture, tenant_fixture_app
  with check (account_id = (select anywaye.current_account_id()));

create policy api_keys_anywaye_update on api_keys
  for update to tenant_fixture, tenant_fixture_app
  using (account_id = (select anywaye.current_account_id()))
  with check (account_id = (select anywaye.current_account_id()));

create policy api_keys_anywaye_delete on api_keys
  for delete to tenant_fixture, tenant_fixture_app
  using (account_id = (select anywaye.current_account_id()));

create policy api_keys_anywaye_resolve on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (token_digest = (select anywaye.current_credential_digest()));

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


credential_widened="$(fresh_copy credential-widened "$CREDENTIAL_FIXTURE")"
edit "$credential_widened/migrations/0003_credential.sql" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys', 'token_digest');" \
  "is \`using (true)\` about four times in ten.
select anywaye.protect_credential_table('api_keys', 'token_digest');

-- A MIGRATION'S OWN WIDENING, after the call that had narrowed it.
drop policy api_keys_anywaye_resolve on api_keys;

create policy api_keys_anywaye_resolve on api_keys
  for select to tenant_fixture, tenant_fixture_app
  using (true);"
expect_red 'a resolve policy widened to admit every row, on the one policy exempt from the identity arm' \
  "$credential_widened" 'tenancy.rls-permissive' 'api_keys_anywaye_resolve'

expect_green 'the honest zero with the key only as a token claim — vouched for, bytecode skipped' \
  "$KEY_CLAIM_FIXTURE" 'enumeration-partial'

thirtyeight="$(fresh_copy key-claim-unnamed "$KEY_CLAIM_FIXTURE")"
edit "$thirtyeight/src/token.py" \
  '    return claims.get("account_id")' \
  '    return claims.get("account_id")


ACCOUNT_CLAIM = "account_id"'
expect_red 'a key-carrying site the declaration does not vouch for' \
  "$thirtyeight" 'tenancy.honest-zero' 'src/token.py:9'

thirtynine="$(fresh_copy key-claim-statement "$KEY_CLAIM_FIXTURE")"
printf 'select * from assets where id = $1 and account_id = $2\n' > "$thirtynine/src/queries.sql"
expect_red 'a genuinely account-scoped statement in a service that says it has none' \
  "$thirtynine" 'tenancy.honest-zero' 'assets'

expect_green 'a declared public read, with the policy and the role the DDL writes' \
  "$PUBLIC_READ_FIXTURE"

public_read_no_marker="$(fresh_copy public-read-no-marker "$PUBLIC_READ_FIXTURE")"
edit "$public_read_no_marker/tenancy.yml" \
  '  publicRead:
    - table: publishers
      policy: publishers_public_read
      role: public_reader
' ''
expect_red 'a public read nobody declared' \
  "$public_read_no_marker" 'tenancy.rls-permissive' 'publishers_public_read'

public_read_no_ddl="$(fresh_copy public-read-no-ddl "$PUBLIC_READ_FIXTURE")"
edit "$public_read_no_ddl/migrations/0002_rls.sql" \
  'create policy publishers_public_read on publishers
  for select to public_reader
  using (true);
' ''
expect_red 'a public read the migrations do not write' \
  "$public_read_no_ddl" 'tenancy.rls-public-read-absent' 'publishers_public_read'

public_read_wrong_role="$(fresh_copy public-read-wrong-role "$PUBLIC_READ_FIXTURE")"
edit "$public_read_wrong_role/tenancy.yml" \
  '  publicRead:
    - table: publishers
      policy: publishers_public_read
      role: public_reader' \
  '  publicRead:
    - table: publishers
      policy: publishers_public_read
      role: anon'
expect_red 'a public read declared for a role the DDL does not grant it to' \
  "$public_read_wrong_role" 'tenancy.rls-public-read-absent' 'public_reader'

public_read_wrong_command="$(fresh_copy public-read-wrong-command "$PUBLIC_READ_FIXTURE")"
edit "$public_read_wrong_command/migrations/0002_rls.sql" \
  'create policy publishers_public_read on publishers
  for select to public_reader' \
  'create policy publishers_public_read on publishers
  for insert to public_reader'
expect_red 'a public read claimed for a policy the DDL writes for insert' \
  "$public_read_wrong_command" 'tenancy.rls-public-read-absent' 'publishers_public_read'

expect_red 'a declaration that is valid, complete, and false' \
  "$LIAR_FIXTURE" 'tenancy.scope-lost' 'asset-fetch'

liar_out="$("$PY" "$HARNESS/tenancy_check.py" "$LIAR_FIXTURE" 2>&1)"
for lying in asset-fetch asset-list asset-pending; do
  if ! printf '%s' "$liar_out" | grep -q "tenancy.scope-lost: $lying "; then
    printf 'FAIL tenancy_self_test: the liar went red but never named %s, so the red is\n' \
      "$lying" >&2
    printf '  about some other statement and says nothing about this one:\n%s\n' "$liar_out" >&2
    failures=$((failures + 1))
  fi
done

for honest in asset-settle asset-delete asset-variant-fetch asset-checksum-bind; do
  if printf '%s' "$liar_out" | grep -q "$honest"; then
    printf 'FAIL tenancy_self_test: the liar named %s, an entry point whose enforcement is\n' \
      "$honest" >&2
    printf '  TRUE (a scoped write, the variant fetch, the bind in src/assets.rb). A red\n' >&2
    printf '  that cannot tell the lies from the honest rows is not a check:\n%s\n' \
      "$liar_out" >&2
    failures=$((failures + 1))
  fi
done

liar_repaired="$(fresh_copy liar-repaired "$LIAR_FIXTURE")"
edit "$liar_repaired/migrations/0001_assets.sql" \
  'select * from assets where id = $1' \
  'select * from assets where id = $1 and account_id = $2'
edit "$liar_repaired/migrations/0001_assets.sql" \
  'select id, checksum, status from assets order by created_at' \
  'select id, checksum, status from assets where account_id = $1 order by created_at'
edit "$liar_repaired/migrations/0001_assets.sql" \
  "select id from assets where status = 'pending'" \
  "select id from assets where account_id = \$1 and status = 'pending'"
expect_green 'the same declaration over the same code, with the predicate restored' \
  "$liar_repaired"

expect_warn 'an enumeration this checker cannot close, on a language it cannot read' \
  "$BLIND_FIXTURE" 'tenancy.enumeration-partial'
expect_warn 'the same service, and the key it found no statement for' \
  "$BLIND_FIXTURE" 'tenancy.scope-key-unused'

seventeen="$(fresh_copy scan-narrowed "$FIXTURE")"
edit "$seventeen/tenancy.yml" '    - migrations
    - src' '    - migrations
    - db/generated
    - src'
expect_warn 'a source path the declaration names that is not there' \
  "$seventeen" 'tenancy.scan-narrowed'

expect_green 'a service whose scoping this checker cannot read, reported as unread rather than as absent' \
  "$BLIND_FIXTURE" 'get-asset'

expect_green 'the honest zero: a service that declares no scoping and has none' \
  "$ZERO_FIXTURE" 'tenancy.scope-key-unused'


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

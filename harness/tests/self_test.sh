#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="$ROOT/harness"
FIXTURES="$HARNESS/tests/fixtures"
SELF_TEST="$HARNESS/tests/self_test.sh"
CONFORMANCE="bin/anywaye-contract"

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

fresh_copy() {
  copy_name="$1"
  local dst="$WORK/$copy_name"
  mkdir -p "$dst"
  cp -R "$HARNESS" "$dst/harness"
  chmod +x "$dst/harness/bin/anywaye-contract" "$dst/harness/tests/self_test.sh" 2>/dev/null || true
  printf '%s' "$dst"
}

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

run_harness() {
  local dir="$1" fixture="$2" core="${3:-$ROOT}"
  shift 3
  ( cd "$dir" && "$PY" "$dir/harness/anywaye_contract.py" \
      --core "$core" "$dir/harness/tests/fixtures/$fixture" "$@" 2>&1 )
}

expect_red() {
  local label="$1" dir="$2" fixture="$3" want="$4" core="${5:-$ROOT}"
  shift 5 2>/dev/null || shift 4
  local out ec=0
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

base="$(fresh_copy control)"
expect_green 'the control: the conforming fixture' "$base" conforming

openapi_base="$(fresh_copy control-openapi)"
expect_green 'the control: the conforming OpenAPI fixture' "$openapi_base" conforming-openapi

pin_base="$(fresh_copy control-postgres)"
expect_green 'the control: the conforming postgres-pin fixture, DSNs and all' \
  "$pin_base" conforming-postgres
expect_green 'the control: the conforming exception fixture, a different major DECLARED' \
  "$(fresh_copy control-postgres-exception)" conforming-postgres-exception

breakages=$((breakages + 1))
one="$(fresh_copy schema-name)"
edit "$one/harness/tests/fixtures/conforming/anywaye.yml" 'name: harness-fixture' 'name: Harness-Fixture'
expect_red 'breakage 1: a service name in the wrong case' "$one" conforming 'manifest.schema'

breakages=$((breakages + 1))
two="$(fresh_copy schema-core-range)"
edit "$two/harness/tests/fixtures/conforming/anywaye.yml" 'core: ^0.2.0' 'core: ^0.2'
expect_red 'breakage 2: a core constraint with no patch component' "$two" conforming 'manifest.schema'

breakages=$((breakages + 1))
three="$(fresh_copy schema-https-remote)"
edit "$three/harness/tests/fixtures/conforming/anywaye.yml" \
  'url: git@github.com:anywaye/harness-fixture.git' \
  'url: https://github.com/anywaye/harness-fixture.git'
expect_red 'breakage 3: an HTTPS remote' "$three" conforming 'manifest.schema'

breakages=$((breakages + 1))
four="$(fresh_copy convention-own-prefix)"
edit "$four/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - courier.email.queued'
expect_red 'breakage 4: a published type prefixed with another service' "$four" conforming 'event.own-prefix'

breakages=$((breakages + 1))
five="$(fresh_copy convention-self-consume)"
edit "$five/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - identity.user.created'
expect_red 'breakage 5: a service consuming its own events' "$five" conforming 'event.no-self-consume'

breakages=$((breakages + 1))
six="$(fresh_copy convention-unknown-consumed)"
edit "$six/harness/tests/fixtures/conforming/anywaye.yml" \
  '  - identity.user.created' '  - identity.no_such_event.ever_happened'
expect_red 'breakage 6: consuming an event type the catalog does not have' \
  "$six" conforming 'event.unknown-consumed'

breakages=$((breakages + 1))
seven="$(fresh_copy convention-unknown-published)"
edit "$seven/harness/tests/fixtures/conforming/anywaye.yml" \
  '  api: openapi/v1.yaml' \
  '  api: openapi/v1.yaml
  events:
    - harness-fixture.no_such_thing.happened'
expect_red 'breakage 7: publishing an event type the catalog does not have' \
  "$seven" conforming 'event.unknown-published'

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

breakages=$((breakages + 1))
nine="$(fresh_copy api-file-missing)"
edit "$nine/harness/tests/fixtures/conforming/anywaye.yml" 'api: openapi/v1.yaml' 'api: openapi/renamed.yaml'
expect_red 'breakage 9: exposes.api pointing at a file that does not exist' \
  "$nine" conforming 'manifest.api-file-missing'

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

breakages=$((breakages + 1))
eleven="$(fresh_copy openapi-unversioned-path)"
edit "$eleven/harness/tests/fixtures/conforming/openapi/v1.yaml" \
  '  /v1/widgets:' '  /widgets:'
expect_red 'breakage 11: a path with no /vN prefix' "$eleven" conforming 'openapi.paths-are-versioned'

breakages=$((breakages + 1))
twelve="$(fresh_copy openapi-no-info-version)"
edit "$twelve/harness/tests/fixtures/conforming/openapi/v1.yaml" '  version: 1.0.0' '  summary: no version here'
expect_red 'breakage 12: info.version removed' "$twelve" conforming 'openapi.info-version'

breakages=$((breakages + 1))
thirteen="$(fresh_copy openapi-30)"
edit "$thirteen/harness/tests/fixtures/conforming/openapi/v1.yaml" 'openapi: 3.1.0' 'openapi: 3.0.3'
expect_red 'breakage 13: an OpenAPI 3.0 document' "$thirteen" conforming 'openapi.document-is-31'

breakages=$((breakages + 1))
fourteen="$(fresh_copy digest-mismatch)"
mkdir -p "$fourteen/core"
cp -R "$ROOT/schemas" "$ROOT/docs" "$fourteen/core/"
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

breakages=$((breakages + 1))
seventeen="$(fresh_copy yaml-refused)"
expect_refused 'breakage 17: a legal YAML construct outside the declared subset' \
  "$seventeen" unsupported-yaml 'yaml.unsupported' 2

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

breakages=$((breakages + 1))
twenty="$(fresh_copy manifest-absent)"
mv "$twenty/harness/tests/fixtures/conforming/anywaye.yml" \
   "$twenty/harness/tests/fixtures/conforming/anywaye.yml.moved"
expect_refused 'breakage 20: a service root with no anywaye.yml' \
  "$twenty" conforming 'service.manifest-absent' 2

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
edit "$eight/$OPENAPI_FIXTURE" '      name: Idempotency-Key' '      name: X-Idempotency-Key'
expect_red 'breakage 36: a mutating POST whose key is X-Idempotency-Key' \
  "$eight" conforming-openapi 'openapi.idempotency-key'

breakages=$((breakages + 1))
nine="$(fresh_copy openapi-no-idempotency-conflict)"
edit "$nine/$OPENAPI_FIXTURE" '"409"' '"400"'
expect_red 'breakage 37: a POST that takes the key and declares no 409' \
  "$nine" conforming-openapi 'openapi.idempotency-conflict-documented'

breakages=$((breakages + 1))
thirty_eight="$(fresh_copy openapi-type-base-retired-host)"
edit "$thirty_eight/$OPENAPI_FIXTURE" \
  'type: https://docs.anywaye.com/errors/unauthorized' \
  'type: https://errors.anywaye.com/unauthorized'
expect_red "breakage 38: a problem \`type\` at the retired host" \
  "$thirty_eight" conforming-openapi 'openapi.problem-type-base'

breakages=$((breakages + 1))
thirty_nine="$(fresh_copy openapi-type-base-no-code)"
edit "$thirty_nine/$OPENAPI_FIXTURE" \
  'type: https://docs.anywaye.com/errors/unauthorized' \
  'type: https://docs.anywaye.com/errors/'
expect_red "breakage 39: a problem \`type\` that is the base and no code" \
  "$thirty_nine" conforming-openapi 'openapi.problem-type-base'

warning_case="$(fresh_copy warn-no-document)"
edit "$warning_case/harness/tests/fixtures/conforming-openapi/anywaye.yml" \
  'exposes:
  api: openapi/v1.yaml
' ''
rm -rf "$warning_case/harness/tests/fixtures/conforming-openapi/openapi"
expect_green_with_warning 'warning 38: a manifest with no exposes.api and no document' \
  "$warning_case" conforming-openapi 'openapi.no-document'

warning_case="$(fresh_copy warn-not-declared)"
edit "$warning_case/harness/tests/fixtures/conforming-openapi/anywaye.yml" \
  'exposes:
  api: openapi/v1.yaml
' ''
expect_green_with_warning 'warning 39: a document checked in that exposes.api does not name' \
  "$warning_case" conforming-openapi 'openapi.not-declared'

warning_case="$(fresh_copy warn-unresolved-ref)"
edit "$warning_case/$OPENAPI_FIXTURE" '#/components/responses/Unauthorized' './errors.yaml#/Unauthorized'
expect_green_with_warning 'warning 40: a $ref the harness cannot follow' \
  "$warning_case" conforming-openapi 'openapi.unresolved-ref'
expect_no_finding 'warning 40: and the unread response is not accused of anything' \
  "$warning_case" conforming-openapi 'openapi.errors-are-problems'

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

breakages=$((breakages + 1))
forty_three="$(fresh_copy postgres-exception-for-the-standard)"
edit "$forty_three/harness/tests/fixtures/conforming-postgres-exception/postgres-pin-exceptions.yaml" \
  '    image: postgres:16-alpine' '    image: postgres:17-alpine'
expect_red 'breakage 43: an exception declared for the tag core already publishes' \
  "$forty_three" conforming-postgres-exception 'compose.postgres-pin'

breakages=$((breakages + 1))
forty_four="$(fresh_copy postgres-tag-absent)"
mkdir -p "$forty_four/notag"
cp -R "$ROOT/schemas" "$ROOT/docs" "$forty_four/notag/"
cp "$ROOT/VERSION" "$forty_four/notag/VERSION"
expect_refused 'breakage 44: a core that publishes no postgres tag' \
  "$forty_four" conforming-postgres 'compose.postgres-tag-absent' 2 "$forty_four/notag"

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
printf 'PASS: self_test — %s breakages went red naming their rule, %s warning cases stayed green, and every control was green first.\n' "$breakages" "$warnings"

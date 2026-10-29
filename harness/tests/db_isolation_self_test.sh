#!/usr/bin/env bash

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harness_dir="$(dirname "$here")"
core="$(dirname "$harness_dir")"
checker="$core/harness/db_isolation_check.py"
fixtures="$here/fixtures"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

python="$(command -v python3 || true)"
if [ -z "$python" ]; then
  echo "db_isolation_self_test.sh: python3 not found on PATH — cannot run the checker" >&2
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

fresh() {
  rm -rf "$work/$2"
  cp -R "$fixtures/$1" "$work/$2"
}

for required in isolated_service shared_service serial_service double_service; do
  if [ ! -d "$fixtures/$required" ]; then
    echo "db_isolation_self_test.sh: the fixture $fixtures/$required is missing." >&2
    echo "  Without a known shape to break, every red below proves nothing: a" >&2
    echo "  checker that refused everything would satisfy all of them." >&2
    exit 2
  fi
done

note "control: the safe fixture, unbroken, which must be CLEAN"
fresh isolated_service control
expect_clean control

note "case 1: darkroom's pre-fix shape — a shared database and a blanket truncate"
fresh shared_service shared_truncate
cat > "$work/shared_truncate/tests/cleanup.rs" <<'RS'
async fn a_test_that_cleans_up_after_itself() {
    let pool = common::shared_pool().await;
    sqlx::query("truncate assets, asset_variants cascade")
        .execute(&pool)
        .await
        .unwrap();
}
RS
expect_red shared_truncate "db-isolation.hazard"

note "case 2: a table-wide DELETE, which no grep for truncate will ever see"
fresh shared_service table_wide_delete
cat > "$work/table_wide_delete/tests/cleanup.rs" <<'RS'
async fn every_test_deletes_the_same_table() {
    let pool = common::shared_pool().await;
    sqlx::query("DELETE FROM users")
        .execute(&pool)
        .await
        .unwrap();
}
RS
expect_red table_wide_delete "db-isolation.hazard"

note "case 3: two of three — shared database, blanket cleanup, no opt-in (LATENT)"
fresh serial_service latent_two_of_three
cat > "$work/latent_two_of_three/tests/cleanup_test.go" <<'GO'
package tests

import (
	"context"
	"os"
	"testing"
)

// No t.Parallel() anywhere: go test runs a package's tests in sequence unless
// one asks otherwise, so this suite is NOT the hazard yet.
func TestACleanupThatWouldDeleteAnotherTestsRows(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool := Pool(ctx)
	if _, err := pool.Exec(ctx, "TRUNCATE TABLE users CASCADE"); err != nil {
		t.Fatalf("truncating: %v", err)
	}
}
GO
expect_red latent_two_of_three "db-isolation.latent"

note "case 4 (negative control): a WHERE-narrowed delete must stay CLEAN"
fresh shared_service narrowed_delete
cat > "$work/narrowed_delete/tests/cleanup.rs" <<'RS'
async fn cleanup_keys_on_this_tests_own_row() {
    let pool = common::shared_pool().await;
    sqlx::query("delete from users where id = $1")
        .bind(self_id())
        .execute(&pool)
        .await
        .unwrap();
}
RS
expect_clean narrowed_delete

note "case 5 (negative control): prose about truncate must stay CLEAN"
fresh shared_service prose_only
cat > "$work/prose_only/tests/prose.rs" <<'RS'
// A long value is truncated to the attribute ceiling: a truncated leak is still a
// leak, and truncation must never be mistaken for "keep the usable part".
async fn a_truncated_string_is_still_reported() {
    assert_eq!(clip("x".repeat(9000)), 4096);
}
RS
expect_clean prose_only

note "case 6 (negative control): the SAME truncate is safe behind a per-test schema"
fresh isolated_service schema_scoped_truncate
cat > "$work/schema_scoped_truncate/tests/cleanup.rs" <<'RS'
async fn the_same_truncate_as_case_1() {
    let pool = common::test_pool().await;
    sqlx::query("truncate assets, asset_variants cascade")
        .execute(&pool)
        .await
        .unwrap();
}
RS
expect_clean schema_scoped_truncate

note "case 7 (negative control): a test DOUBLE cannot share a database"
fresh double_service double_database
expect_clean double_database

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
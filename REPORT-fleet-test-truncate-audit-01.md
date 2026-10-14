# REPORT — fleet-test-truncate-audit-01

**The question this report exists to answer, answered first.**

> Does any other service have darkroom's defect?

**No. Zero of the six services with database tests have it, and the reason is
different in every one of them.** Two are missing condition (3) outright, three
have a mechanism that collapses a condition, and one has no database to share.
That is a real result and it is reported in as much detail as a positive would
be, because the packet asked for exactly that and because the negative is only
worth anything if the measurement behind it is shown.

Nothing in any service was changed. `darkroom`'s fix was verified load-bearing by
planting the defect in the real repository and measuring it, not by reading the
report that claims it.

---

## 1. The packet's survey is wrong, and it is wrong twice

The packet supplied a table of "test files mentioning truncate" as a starting
point and asked me to confirm it. It does not survive confirmation, and two
services would otherwise have been audited against the wrong language's
concurrency rules.

| service | packet says | `grep -rlni truncate` | files with a **SQL `TRUNCATE`** |
|---|---|---|---|
| billing | 2 (Ruby, **ExUnit**) | 2 | **0** |
| courier | 4 (Elixir, ExUnit) | 4 | **0** |
| muse | 5 (**Go**) | 5 | **0** |
| pantry | 1 (**Python**, pytest) | 1 | **0** |
| identity | 0 | 9 | **0** |
| guard | 0 | 1 | **0** |

**Every hit in the fleet is a truncated STRING, not a truncated TABLE.**
`String#truncate` in billing's `app/models/processor_webhook.rb`,
`DateTime.truncate(:second, …)` in courier's `lib/courier/events.ex`, and test
comments such as `muse/tests/test_telemetry.py:249`
(*`test_a_long_value_is_truncated_to_the_attribute_ceiling`*) and
`courier/test/courier/telemetry_canary_test.exs:245` (*"that 'ignore' must not
mean 'truncate and keep the usable part'"*). Restricted to a real SQL `TRUNCATE`,
the count across all thirteen repositories — including `core` and `kit` — is
**zero**.

**The languages are wrong in both directions.** The packet says muse is Go and
pantry is Python. `muse/pyproject.toml` is a `[project]` with
`requires-python = ">=3.14"` and a `pytest` dev dependency; `pantry/Cargo.toml` is
a Rust crate. So the packet's `t.Parallel()` and `pytest-xdist` rules were aimed
at the wrong two repositories, and **neither has a database at all**.

**identity's row is the instructive one: the packet says 0 and the same grep
reports 9.** All nine are comments, and one of them is
`internal/platform/dbtest/dbtest.go:12`:

> there is deliberately no TRUNCATE helper called from ordinary tests: a global
> truncate from internal/users would delete internal/sessions' fixtures mid-run,
> and the failure looks like a non-deterministic bug in the code under test
> rather than in the harness.

That is the packet's own argument, already written down in the right place by
somebody who had reasoned it out, and the survey scored the file containing it as
a hit.

`courier` is the proof that the grep was never the question: **zero** `TRUNCATE` in
the repository, and it is still the most aggressively database-tested service in
the fleet.

---

## 2. The three conditions, and what is missing per service

The hazard needs all three. A service missing any one is safe, and **which one is
missing is the finding**.

| service | lang | (1) shared DB | (2) unscoped cleanup | (3) concurrent | missing | verdict |
|---|---|---|---|---|---|---|
| **billing** | Ruby | **no** — per-worker DB | **yes** (19 `delete_all`) | n/a | **(1)** | safe |
| **courier** | Elixir | yes | no | **yes** (49) | **(2)** | safe |
| **darkroom** | Rust | yes | no — per-test schema | **yes** (default) | **(2)** | safe |
| **identity** | Go | yes | no — 13 keyed, 0 blanket | **yes** (507) | **(2)** | safe |
| **muse** | Python | **n/a** — a dict | n/a | no (no xdist) | **(1)**, **(2)** | safe |
| **guard** | TS | **n/a** — no DB | n/a | no | all | safe |
| **pantry** | Rust | **n/a** — no DB | n/a | n/a | all | safe |
| **cafe**, **cafaye-rb** | Go, Ruby | no DB tests | — | — | all | safe |

Two services have conditions (1) and (2) both present in some form and are saved
only by a mechanism, and those mechanisms are the interesting part of this report.

### courier — 49 concurrent sites, and a rollback

`Courier.DataCase` starts a SQL Sandbox owner per test and `stop_owner`s it on
exit, so each test runs inside a transaction that is **rolled back**. Condition
(2) is missing because there is nothing left to delete after a test ends.

On the count: **59 occurrences** of `async: true` across `courier/test`, of which
the checker counts **49** as concurrency sites. The difference is ten occurrences
in comments and prose rather than in a `use …, async: true` line, and the checker
counts sites rather than occurrences on purpose — a word in a comment is not a
thing that opts a module into concurrent execution, which is the same lesson
§1's survey teaches the hard way.

Measured: **1282 passed, 0 failures, three runs out of three**, with concurrency
demonstrably in effect — `1.3s async, 2.8s sync`, then `1.5s/2.2s`, then
`1.7s/2.1s`.

### identity — 507 concurrency sites, and every cleanup keyed

`go test ./...` runs **packages** in parallel against one `TEST_DATABASE_URL`.
**508 `t.Parallel()` calls** across 144 test files, of which the checker counts
507 as concurrency sites — the one it misses is in a comment. Every cleanup in the
suite is keyed to a row. Measured across the suite:

```
internal/oauth/store_test.go:320        DELETE FROM users WHERE id = $1
internal/tenancy/tenancy_test.go:187    (a comment about dbtest's rule)
internal/recovery/…_test.go:234         DELETE FROM users WHERE id = $1
internal/apikeys/store_test.go:266      DELETE FROM account_users WHERE account_id = $1 AND user_id = $2
internal/admin/store_test.go:118        DELETE FROM account_audit_log WHERE id = $1
internal/mfa/challenge_test.go:315      DELETE FROM users WHERE id = $1
internal/httpapi/auth_routes_…:493      DELETE FROM users WHERE id = $1
internal/sessions/store_test.go:339     DELETE FROM users WHERE id = $1
internal/accounts/store_test.go:395     DELETE FROM users WHERE id = $1
```

**Every single one carries a predicate.** `dbtest.Reset` does hold a real 16-table
`TRUNCATE … CASCADE` — and has **zero callers**, measured:

```
$ grep -rn 'dbtest\.Reset' identity --include='*.go' | grep -v dbtest.go
(no output)
```

Measured: **21 of 22 packages green, three full runs out of three, an identical
failing set each time.** The one failure is `TestTheCoverageExclusionIsOnlyGeneratedCode`,
which reports `client/generated records lines=22435 and the tree holds 22411` — a
generated-code line count that has drifted. It is **pre-existing and unrelated to
databases**, and I did not touch it, because fixing it is a bookkeeping change to
an entry this packet has no reason to edit.

### billing — 19 unscoped cleanups, saved by per-worker databases

Four classes set `use_transactional_tests = false` and `delete_all` their tables
in `setup` **and** `teardown`. `concurrent_delivery_test.rb` says why it cannot be
transactional: two threads need two connections, and a connection cannot see
another connection's uncommitted work.

The saving grace is Rails' own. Measured by running its fork hook for four
workers in four processes:

```
worker 1 -> billing_audit_test_1
worker 2 -> billing_audit_test_2
worker 3 -> billing_audit_test_3
worker 4 -> billing_audit_test_4
```

Eight workers, **eight databases**. The workers cannot see each other's rows at
all, so (1) is genuinely missing.

**This is latent, and here is what would set it off.** The `delete_all` calls are
scoped to five tables (`Plan`, `Customer`, `Subscription`, `ProcessorWebhook`,
`OutboxEvent`) and are safe today because a worker never overlaps itself. Two
changes would make billing darkroom-shaped:

1. **`parallelize(workers: 1)`** — a single worker with five non-transactional
   classes is still serial, so this alone does not do it.
2. **threads inside a test reaching a table another class's `delete_all` covers.**
   `concurrent_delivery_test.rb` already spawns threads against its own tables. A
   test that spawned threads against `OutboxEvent` while a *different* class's
   `delete_all` ran in the same worker is the shape.
3. **removing `parallelize`** would not do it either — serial is the safe
   direction.

Honestly: the mechanism that protects billing is **Rails' per-worker database
split**, and it is not something this suite asserts. billing's suite has no test
that says "a worker's cleanup cannot reach another worker's rows", so a future
change to the parallelization strategy would not be caught by the suite. That is a
real gap and I am reporting it rather than closing it, because closing it means
writing billing tests and billing is not where this packet's work belongs.

### muse, pantry, guard — no database

**muse's 968 tests** (3 skipped) run against `tests/support/fake_database.py`, a
dict that answers `"delete from" in sql` by popping a key. There is no server, so
there is nothing to share. No `pytest-xdist` in `pyproject.toml`, `uv.lock` or CI,
so pytest is sequential.

**pantry** has 13 test files and no `DATABASE_URL`, `sqlx` or `postgres` anywhere.

**guard** has **467 pass, 0 fail, 15 skip** (the Redis tier, which `bin/prime`
skips by design).

---

## 3. darkroom's fix is load-bearing — proven by planting the defect

The packet asks for the flag to be proven before removing serialization, exactly
as darkroom's own report did. darkroom has no flag any more, so the equivalent
proof is to restore the defect and measure it.

I planted it in the real repository: `test_store()` stopped minting a schema per
test and used one shared schema instead, with `CREATE SCHEMA` made idempotent so
concurrent tests proceed into the same tables rather than aborting — which is
precisely the pre-fix shape.

`cargo test --no-fail-fast -- --ignored`, three runs:

| run | exit | distinct failing tests |
|---|---|---|
| 1 | 101 | **14** |
| 2 | 101 | **17** |
| 3 | 101 | **16** |

And **the failing set changed every run** — the signature of a race, not a bug:

```
run 1 → 2:  -a_cursor_from_another_account_pages_only_the_callers_own_rows
             +a_cross_tenant_variant_write_touches_nothing
             +a_failed_upload_emits_nothing
             +the_same_bytes_in_two_accounts_are_two_assets
             +the_same_key_with_a_different_body_is_idempotency_key_reused

run 2 → 3:  -the_same_key_with_a_different_body_is_idempotency_key_reused
```

The packet's symptom, reproduced exactly:

```
---- a_duplicate_upload_returns_the_existing_asset_with_a_usable_url stdout ----
assertion `left == right` failed: a duplicate must not create a second asset
  left: 5
 right: 1
```

`left: 5` — a test counting five assets of which it created one. Two other tests'
rows, read as its own. And darkroom's **own** guard tests fired, including
`one_tests_truncate_cannot_delete_anothers_rows` and
`two_stores_get_two_schemas_and_neither_can_fall_out_of_one`.

**Reverted, and re-measured: `exit 0`, 0 failing test results.** The fix is
load-bearing and `cargo test -- --ignored` needs no `--test-threads=1`.

---

## 4. The guard

`core/harness/db_isolation_check.py`, reached as `harness/bin/db-isolation-check`,
with `harness/db_isolation_findings.json`, `docs/db-isolation.md` and
`harness/tests/db_isolation_self_test.sh`.

It lives in `core` because a guard that lives in the service it guards is a guard
the next service does not have, and because `core/bin/prime` is where every
service's gate already reaches.

**Its verdict on the fleet is `0 failure(s)`** — six services with database tests,
none wrong. That line reads identically whether the checker can detect anything or
not, which is this packet's own premise, so the red proof is the point:

**3 reds**, each naming its finding:
1. a shared database and a blanket `truncate` → `db-isolation.hazard`
2. a table-wide `DELETE FROM users` → `db-isolation.hazard`
3. shared database, blanket cleanup, **no `t.Parallel()`** → `db-isolation.latent`

**5 clean controls**, which are what make the reds mean something:
* the unbroken fixture;
* a `WHERE`-narrowed delete — identity's entire suite is written this way;
* a comment using the word "truncate";
* the **same** truncate as case 1, behind a per-test schema;
* a test double.

`bin/prime` runs both and **reads the report** rather than trusting the exit code,
asserting ≥3 reds and ≥4 controls. Measured: `8 passed, 0 failed`, `bin/prime`
exit 0, suite **280/280**.

### Six false positives I had to fix first, each measured on this fleet

A guard is only worth its negative controls, and mine had six real ones — every
one of them a repository I had already measured green:

| what it read | what it was |
|---|---|
| `truncate assets, …` in `///` prose | a Rust doc comment *describing* the isolation |
| `DELETE FROM t` with `where` three lines below, in `r#"…"#` | a delete keyed three ways (`store.rs:774`) |
| `time.Now().UTC().Truncate(time.Microsecond)` | a clock — 15 such hits in identity |
| `t.Fatal("a DELETE from the audit trail SUCCEEDED")` | a failure **message** |
| `muse`'s `"delete from" in sql` | a dict, and no server to share |
| `tests/schema_isolation.rs` | a test **of** the isolation, not the isolation |

Two more were my own bugs, and the second is the one I would most want a reader to
check:

* **`next(...)` without a default inside a generator expression** raises
  `StopIteration` → `RuntimeError` on an **empty** string literal. billing has
  `t.Fatalf("")`. The checker **crashed on the very repository it was written to
  clear**, and reported every finding below the crash as zero. That is the false
  all-clear this packet warns about, reached by a different road.
* **a tautological condition.** `join_multiline_sql` asked
  `closer not in line.split(closer,1)[0] + closer`, which contains the delimiter
  by construction and is therefore always false. Nothing was ever folded. A
  correct-looking condition that can never be true is worse than a missing one,
  because it reads as coverage.

### Two of my own tests were wrong, and I fixed the tests

`test_the_db_isolation_checker_treats_rust_concurrency_as_the_default` asserted a
verdict the checker never produces for an unscanned report, and
`test_the_db_isolation_wrapper_never_lifts_the_exit_code` banned the string
`|| true` from a wrapper whose own header contains the words while explaining why
they are forbidden. Both corrected in the tests, with the reasons written down.
`gate.yml`'s floor moved **272 → 280** in the same commit, which is that ratchet
doing its job.

---

## 5. What I could not run, and what I did instead

**billing's suite could not be run as CI runs it.** `pg` 1.6.3 segfaults on fork
on this machine:

```
pg-1.6.3-arm64-darwin/lib/pg/connection.rb:944: [BUG] Segmentation fault
c:0060 CFUNC :connect_start
```

Reproduced at `PARALLEL_WORKERS=8`, at `2`, and on a single 5-test file. This is
the gem, not the suite — `PARALLEL_WORKERS=1` runs fine. So:

* **Ran:** `test/models` in full — **286 runs, 612 assertions, 0 failures, 0
  errors, 0 skips.**
* **Measured instead of run:** the per-worker database split, by executing
  Rails' own `create_and_load_schema` for four workers in four processes (§2), and
  the condition-2 inventory by the checker, which reads all 39 test files.
* **Did not claim:** that billing's full 999-test parallel suite is green. I am
  not reporting it either way.

**pantry's suite exits 101, and the failures are mine.** All three are registry
staleness — `every_example_in_core_s_valid_examples_is_classified_by_this_table`,
`the_registry_says_how_far_behind_each_copy_is_and_names_the_fix`,
`this_repository_says_how_far_behind_core_it_is`. pantry pins sibling repositories
to SHAs in `vendir.lock.yml`, and **creating a branch in nine siblings moved every
one of those SHAs.** Not a defect, not a database matter, and not something to fix
in this packet.

**Also honest about the guard:** it reads source, so it cannot see a cleanup
reached through an unrecognised helper, or a concurrency opt-in set by an
environment variable. `docs/db-isolation.md` says so and says to run the suite for
the service that matters. The check tells you which services have the shape; only
a run tells you the shape held.

---

## 6. Per-service summary

| service | suite run | result | verdict |
|---|---|---|---|
| **identity** | `go test -count=1 ./...` × 3 | 21/22 packages, identical set ×3 | **safe** — missing (2); every cleanup keyed; `Reset` uncalled |
| **courier** | `mix test` × 3 | 1282 passed ×3 | **safe** — missing (2); sandbox rollback per test |
| **darkroom** | `cargo test -- --ignored` | exit 0; **defect planted → 101 ×3 (14/17/16)** | **safe** — missing (2); per-test schema, proven load-bearing |
| **muse** | `bin/prime` | 968 passed, 3 skipped | **safe** — a dict, and no xdist |
| **guard** | `bin/prime` | 467 pass, 0 fail, 15 skip | **safe** — no database |
| **pantry** | `cargo test --no-fail-fast` | 101, 3 registry-staleness failures **caused by this packet's branches** | **safe** — no database |
| **billing** | `test/models` only; parallel **segfaults** | 286 runs, 0 failures | **safe** — missing (1); per-worker databases. **Full suite not run** |
| **cafe**, **cafaye-rb** | not run | — | no database tests to run |

**No service was changed. No service needed changing.** The only change to a
service repository is `darkroom`'s, and that was reverted byte-for-byte after the
measurement in §3 — `git diff` on that branch is empty.
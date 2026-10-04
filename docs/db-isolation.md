# Test isolation: can one test delete another's fixtures?

`harness/db_isolation_check.py` · `harness/bin/db-isolation-check` ·
`harness/tests/db_isolation_self_test.sh`

## The defect

`darkroom` shipped with 54 database tests that all shared one `TEST_DATABASE_URL`
and all ran

```sql
truncate assets, asset_variants, outbox_events, idempotency_keys
  restart identity cascade
```

in that same database. `cargo test` parallelizes test functions by default, so two
tests deleted each other's fixtures mid-assert. Measured on the pre-change tree,
`cargo test -- --ignored` exited **101 six times out of six**, with 12, 12 and 15
distinct failures — *a different set each run*, which is what makes it a race
rather than a bug.

The symptom was never a lock timeout. It was:

```
the_same_bytes_in_two_accounts_are_two_assets
assertion `left == right` failed
  left: 4        <- it created two assets and read four
 right: 2
```

That is two other tests' rows counted as its own. It reads as a product defect,
and it is the worst kind of test failure to debug.

The part that makes it a fleet question rather than a `darkroom` question:
`TEST_DATABASE_URL` names *the same database the service itself uses*. A truncate
that quietly empties the service's tables is not only a test bug; it is a way to
delete production rows from a test run.

## The three conditions

The hazard needs all three at once. A service missing any one of them is safe,
and **which one is missing is the finding** — "safe" is a claim about a mechanism,
and the mechanism is per-language.

| | condition | question |
|---|---|---|
| 1 | **tests share one database** | does every test in the suite reach the same tables? |
| 2 | **a cleanup deletes rows another test can see** | a table-wide `DELETE`/`TRUNCATE`/`delete_all`, or a transactional fixture turned off |
| 3 | **the runner executes them concurrently** | does the runner overlap tests at all? |

(3) is the one that gets guessed wrong in both directions, and it is the whole
reason this checker exists rather than a grep.

## (3), per language

Each rule below is a reading of a repository that was then RUN.

**Rust** — parallel **by default**. `#[test]` functions in one binary are threads
and `cargo` runs test binaries in parallel. Absence of an opt-in is not
isolation; this is why `darkroom` was the service that broke.

**Go** — `go test` does not parallelize within a package unless a test calls
`t.Parallel()`, but **packages** run in parallel up to `-p`. So the shape to look
for is two *packages* sharing a DSN and both opting in.

**ExUnit** — a module's cases run sequentially unless marked `async: true`, and
async modules run concurrently *with each other*. So the question is not "are
cases concurrent" but "are two `async: true` modules sharing a database" — and
whether Ecto SQL Sandbox wraps each test in a rolled-back transaction, which is a
real boundary and is why `courier` is safe with 49 async sites.

**minitest / Rails** — `parallelize` forks one process per worker and gives each
its own database. Measured by running Rails' own fork hook for four workers in
four processes:

```
worker 1 -> billing_audit_test_1
worker 2 -> billing_audit_test_2
worker 3 -> billing_audit_test_3
worker 4 -> billing_audit_test_4
```

So the workers cannot see each other's rows at all, whatever the cleanup does. The
hazard inside a Rails service is the tests that set
`use_transactional_tests = false`, because their rows outlive the test.

**pytest** — sequential unless `pytest-xdist` or `pytest-parallel` is installed
*and* asked for. The dependency is the evidence; intent in a comment is not.

**bun** — `bun test` runs files in one process, sequentially.

## What the checker reports

```
$ harness/bin/db-isolation-check ..
identity  (go)
  1. shares one database:            YES
  2. a cleanup can reach other rows: no  (0 site(s), 13 narrowed)
  3. runner is concurrent:           YES  (507 site(s))
     per-test isolation found in: internal/platform/dbtest/dbtest.go
  ok   the hazard needs all three and this service does not have all three
```

`db-isolation.latent` is the finding that matters most for a service nobody has
audited: conditions (1) and (2) are present and (3) is not, so the suite is one
`async: true`, one `t.Parallel()` or one `-p 8` away from `darkroom`'s bug.

Two mechanisms **collapse** a condition rather than being reported as findings:

* **per-worker databases** collapse (1) — see Rails above.
* **a per-test schema** collapses (2) — an unqualified `truncate assets` resolves
  through the connection's `search_path`, so with a schema named per test on that
  path the truncate empties one test's copy. This is `darkroom`'s fix.

## Why this is not a grep

The packet this checker answers arrived with a survey built from
`grep -rlni truncate` over the test trees, reporting 2 hits in `billing`, 4 in
`courier`, 5 in `muse`, 1 in `pantry`, 0 in `identity` and 0 in `gateway`.

**Every one of those hits is a truncated STRING, not a truncated TABLE.** They are
`String#truncate`, `DateTime.truncate(:second, …)`, and comments such as
`muse/tests/test_telemetry.py:249`, *"`test_a_long_value_is_truncated_to_the_attribute_ceiling`"*,
and `courier/test/courier/telemetry_canary_test.exs:245`, *"that 'ignore' must not
mean 'truncate and keep the usable part'"*. Across all thirteen repositories the
count of a real SQL `TRUNCATE` in a test file is **zero**.

`courier` is the proof that the grep is not the question: zero `TRUNCATE` in the
repository, and it is still the most aggressively database-tested service in the
fleet.

Four classes of thing had to be taught to the reader, and every one of them was a
measured false positive on this fleet before it was fixed:

| what it read | what it was | how it is now read |
|---|---|---|
| `truncate assets, …` in `///` prose | a Rust doc comment describing the isolation | comment state is carried down the file; a line inside a comment is blanked |
| `DELETE FROM t` then `where …` on the next line | a delete keyed three ways | multi-line SQL literals are folded onto the line that opens them |
| `time.Now().Truncate(time.Microsecond)` | a clock | a literal is only restored if its text looks like SQL |
| `t.Fatal("a DELETE from the audit trail SUCCEEDED")` | a failure *message* | as above — `DELETE from the` is not `DELETE FROM users` |

Two more, both about what a service IS:

* **a test double cannot share a database.** `muse`'s 968 tests all run against
  `tests/support/fake_database.py`, a dict that answers `"delete from" in sql` by
  popping a key. There is no server, so there is nothing to share.
* **a test OF the isolation is not the isolation.** `darkroom` keeps both
  `tests/common/mod.rs` (which isolates) and `tests/schema_isolation.rs` (which
  asserts it did), and an unordered scan reached the assertion first — reporting
  the one repository in the fleet that has fixed the defect as carrying it.

## What this checker does not claim

It reads source, so it can only see what is written down. A test that deletes
another's rows through a helper in an unrecognised location, or a concurrency
opt-in set by an environment variable rather than a literal, is not visible here.

So **run the suite for the service that matters.** This check tells you which
services have the shape; only a run tells you the shape held.

## The red proof

`harness/tests/db_isolation_self_test.sh` — 8 cases, and the counts are asserted
by `bin/prime`, not just printed.

**Three reds**, each naming its finding:

1. a shared database and a blanket truncate — `db-isolation.hazard`, and this is
   the shape that was *measured* in the real `darkroom` repository by planting it
   there (`left: 5, right: 1`; 14, 17 and 16 distinct failures over three runs).
2. a table-wide `DELETE` — `db-isolation.hazard`, and the spelling a grep for
   "truncate" will never see.
3. shared database, blanket cleanup, **no** `t.Parallel()` —
   `db-isolation.latent`. It needs a Go fixture, because a Rust base is
   concurrent by construction and could never express "two of three".

**Five clean controls**, which are the ones that make the reds mean something:

* the unbroken fixture;
* a `WHERE`-narrowed delete — `identity`'s entire suite is written this way and
  was measured green three times out of three;
* a comment using the word "truncate";
* the **same** truncate as case 1, behind a per-test schema — the difference
  between that one and case 1 is the entire checker;
* a test double.

A guard that cries wolf on a green suite is switched off, and being switched off
is how the real defect gets through next time.

### One fixture is not enough, and that was measured

The first version planted each hazard by adding a cleanup to the *safe* fixture.
All four reds came back clean — correctly, because that fixture stamps a
per-test `search_path` on every connection, so a truncate written beside it is
genuinely bounded.

**A hazard is a property of a suite's shape, not of one line added to it.** So the
reds are planted in fixtures that have the hazardous shape to begin with.

## Running it

```bash
harness/bin/db-isolation-check .            # this service
harness/bin/db-isolation-check ..           # the fleet
harness/bin/db-isolation-check --explain    # every finding, and its fix
bash harness/tests/db_isolation_self_test.sh # 8 cases: 3 reds, 5 clean
```

Exit codes are the whole contract: **0** clean, **1** a finding, **2** the check
could not run — never collapsed into 1.

`core/bin/prime` runs both, the check and its red proof, and reads the report
rather than trusting the exit code.
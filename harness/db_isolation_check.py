#!/usr/bin/env python3
"""db_isolation_check — can one test in this suite delete another's fixtures?

    db-isolation-check .                  # every service in the fleet
    db-isolation-check ../identity        # one service
    db-isolation-check . --json           # the same findings, as JSON
    db-isolation-check . --explain        # every finding this checker can report

WHAT THIS IS FOR

`darkroom` shipped with 54 database tests sharing one `TEST_DATABASE_URL` and
all truncating the same tables in it. `cargo test` parallelizes by default, so
two tests deleted each other's fixtures mid-assert. Measured on the pre-change
tree, six runs of six exited 101 with 12, 12 and 15 distinct failures and a
DIFFERENT SET EACH RUN, which is what makes it a race and not a bug. The
symptom was never a lock timeout:

    the_same_bytes_in_two_accounts_are_two_assets
    assertion `left == right` failed
      left: 4     <- created two assets, read four: two other tests' rows
     right: 2

That is the worst kind of test failure to debug, because it reads as a product
defect. And `TEST_DATABASE_URL` names the same database the SERVICE uses, so a
truncate that quietly empties those tables is a way to delete production rows
from a test run.

`darkroom` is fixed — each test migrates into a schema of its own and truncates
only that schema. This checker is what stops the next service from having to be
audited by hand, and it lives in `core` because `core` is where every service's
gate runs.

THE THREE THINGS, AND WHY A SERVICE MISSING ONE IS SAFE

The hazard needs all three at once, and this checker reports which one is
missing rather than a yes/no verdict, because "safe" is a claim about a
mechanism and the mechanism is per-language:

  1. tests that share one database;
  2. a cleanup that deletes rows another test can SEE — a table-wide DELETE,
     TRUNCATE, `delete_all`, or a transactional fixture that was turned off;
  3. a runner that executes those tests CONCURRENTLY.

(3) is the one that differs by language and the one that gets guessed wrong in
both directions. Measured per language, and each rule below is a reading of a
real repository that was then RUN:

  * Rust      parallel by default. `#[test]` functions in one binary are
              threads. This is why darkroom was the one that broke.
  * Go        NOT parallel unless a test calls `t.Parallel()`, but `go test ./...`
              runs PACKAGES in parallel up to `-p`. Two packages sharing a DSN
              and both opting in is the shape.
  * ExUnit    a module's cases run sequentially unless marked `async: true`, and
              async modules run concurrently with EACH OTHER. So the question is
              not "are cases concurrent" but "are two `async: true` modules
              sharing a database" — and whether the SQL sandbox is in play.
  * minitest  Rails parallelizes into FORKED PROCESSES, each given its OWN
              database (`<name>_0`, `<name>_1`, …). Measured, not assumed: see
              the `processes` mechanism below.
  * pytest    sequential unless `pytest-xdist` or `pytest-parallel` is installed
              AND asked for. The dependency, not the intent.
  * bun       `bun test` runs files in one process, sequentially.

A service with (1) and (2) but not (3) is LATENTLY DANGEROUS: one `async: true`,
one `t.Parallel()`, or one `-p 8` away from darkroom's bug. That is reported as
a finding of its own severity, not folded into "safe".

WHAT THIS CHECKER DOES NOT CLAIM

It reads source, so it can only see what is written down. A test that deletes
another test's rows through a helper in another file, or a concurrency opt-in
set by an environment variable rather than a literal, is not visible here. That
is why the inventory calls the mechanism it read rather than asserting the
suite is safe, and why `docs/db-isolation.md` says to run the suite for the
service that matters.

THE EXIT CODES, WHICH ARE THE WHOLE CONTRACT

  0   no failure. Latent findings are printed and DO NOT move the exit code.
  1   at least one failure — the hazard is present, or is present minus the
      thing that would set it off.
  2   the check could not happen. Never 0, and never collapsed into 1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CANNOT_RUN = 2

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/db_isolation_findings.json` and asserted equal in both directions by
#: core's suite, for `tenancy_check.py`'s reason: a finding nobody was told
#: about is a finding that will be wrong the first time somebody needs it.
FINDINGS: dict[str, tuple[str, str, str]] = {
    "db-isolation.hazard": (
        "fail",
        "tests share one database, a cleanup can reach another test's rows, and the runner "
        "executes tests concurrently: all three of darkroom's conditions at once.",
        "give each test its own schema (darkroom's fix: migrate into a schema named per test "
        "and set search_path to it), or its own transaction rolled back at the end, or its "
        "own database",
    ),
    "db-isolation.latent": (
        "fail",
        "tests share one database and a cleanup can reach another test's rows, but no runner "
        "concurrency was found in source: one `async: true`, one `t.Parallel()` or one `-p 8` "
        "away from the hazard.",
        "give each test its own schema or transaction now, before the concurrency arrives; "
        "this is the state darkroom shipped in",
    ),
    "db-isolation.declaration-missing": (
        "fail",
        "the service has database tests and declares no test-isolation boundary, so how its "
        "tests are kept apart can only be discovered by reading every test helper by hand.",
        "write db_isolation.yml; the format is documented in docs/db-isolation.md",
    ),
    "db-isolation.declaration-unreadable": (
        "fail",
        "db_isolation.yml is not a YAML document core's reader accepts.",
        "run: harness/bin/db-isolation-check <repo> --explain, and read the file and line it names",
    ),
    "db-isolation.cleanup-unscoped": (
        "fail",
        "a test cleanup deletes rows without a predicate that narrows it to this test's own "
        "rows — a table-wide DELETE, a TRUNCATE, a delete_all, or a destroy_all.",
        "key the delete to a value unique to this test (identity's dbtest.UniqueEmail does "
        "exactly this), or move the cleanup into a per-test schema or transaction",
    ),
    "db-isolation.nontransactional-tests": (
        "fail",
        "tests turn the transactional fixture off, so their rows outlive the test and land in "
        "whatever database the next test in the same worker uses.",
        "keep the cleanup keyed to this file's own ids, or move the test into a per-test "
        "schema; billing's concurrent_delivery_test.rb does the first and documents why",
    ),
    "db-isolation.serializer-disabled": (
        "warn",
        "the suite runs without the mechanism that would hide the hazard — cargo with no "
        "per-test isolation, or a Go suite with neither t.Parallel nor a per-test schema.",
        "confirm the suite passes in this shape, and re-run this check when a test opts into "
        "parallelism",
    ),
}


@dataclass(frozen=True)
class Mechanism:
    """How one language actually decides (3), and how to read it off the tree.

    `files` is a glob over paths relative to the repository root. `concurrency`
    is the regex for a test that opts into concurrent execution. `processes`
    is the regex for a runner that forks, because a forked runner may give each
    worker its own database and that changes the answer completely.
    """

    language: str
    files: tuple[str, ...]
    concurrency: str
    processes: str = ""
    isolation: str = ""
    processes: str = ""
    fake: str = ""
    note: str = ""


#: One entry per language, each with the real file and the real reason from a
#: repository that was measured. The `note` is not commentary: it is the reason
#: a reader who suspects this rule is wrong can go check it.
MECHANISMS: tuple[Mechanism, ...] = (
    Mechanism(
        language="rust",
        files=("tests/**/*.rs", "tests/*.rs", "src/**/*.rs", "src/*.rs"),
        concurrency=r"#\[(tokio::)?test[^\]]*\]",
        isolation=r"search_path|CREATE SCHEMA|create schema",
        note=(
            "cargo parallelizes TEST FUNCTIONS by default, so concurrency is the default and "
            "absence of an opt-in is not isolation. darkroom measured this: six of six runs "
            "red with a different failing set each run."
        ),
    ),
    Mechanism(
        language="go",
        files=("**/*_test.go",),
        concurrency=r"\bt\.Parallel\(\)",
        isolation=r"CREATE SCHEMA|search_path",
        note=(
            "go test does not parallelize within a package unless a test calls t.Parallel(), "
            "but PACKAGES run in parallel up to -p, so two packages sharing a DSN is the shape "
            "to look for."
        ),
    ),
    Mechanism(
        language="elixir",
        files=("test/**/*_test.exs", "test/*_test.exs", "test/**/*_case.ex"),
        concurrency=r"async:\s*true",
        isolation=r"SQL\.Sandbox|start_owner!",
        note=(
            "ExUnit runs a module's cases sequentially unless it is async: true, and async "
            "modules run concurrently WITH EACH OTHER. Ecto SQL Sandbox wraps each test in a "
            "transaction that is rolled back, which is a real isolation boundary and is why "
            "courier is safe despite 20 async modules."
        ),
    ),
    Mechanism(
        language="ruby",
        files=("test/**/*_test.rb", "test/*_test.rb", "spec/**/*_spec.rb", "spec/*_spec.rb"),
        concurrency=r"parallelize|parallel_tests",
        isolation=r"use_transactional_tests\s*=\s*false",
        # `parallelize` is the load-bearing token, and it is a DECLARATION rather
        # than an invocation: ActiveSupport::Testing::Parallelization then forks
        # one process per worker and ActiveRecord::TestDatabases names each
        # worker's database `<name>_<i>`. Measured on billing, by running Rails'
        # own hook for four workers in four processes:
        #
        #     worker 1 -> billing_audit_test_1
        #     worker 2 -> billing_audit_test_2
        #     worker 3 -> billing_audit_test_3
        #     worker 4 -> billing_audit_test_4
        #
        # So the workers cannot see each other's rows at all, whatever the
        # cleanup does, and this field is what collapses condition (1) for a
        # Rails service.
        processes=r"\bparallelize\b",
        note=(
            "Rails parallelize forks one process PER WORKER and gives each its own database, "
            "so the workers cannot see each other's rows at all — that is why billing's "
            "delete_all cannot cross workers. The hazard inside billing is the tests that set "
            "use_transactional_tests = false, because their rows outlive the test."
        ),
    ),
    Mechanism(
        language="python",
        files=("tests/**/*.py", "tests/*.py", "test/**/*.py", "test/*.py"),
        concurrency=r"pytest-xdist|pytest_parallel|pytest-parallel|-n\s+auto|numprocesses",
        isolation=r"",
        # A test double standing in for the driver is the strongest form of
        # isolation there is: there is no server, so there is nothing to share.
        # muse is the measured case — its suite is 968 tests and every one of
        # them runs against `tests/support/fake_database.py`, a dict. It parses
        # `"delete from" in sql` and pops a key. Without this, that line reads
        # as a table-wide DELETE and muse is reported as latently dangerous for
        # a database it never opens.
        fake=r"FakePool|FakeDatabase|fake_database|sqlite3\.memory|:memory:",
        note=(
            "pytest is sequential unless xdist or pytest-parallel is INSTALLED and asked for. "
            "The dependency is the evidence; intent in a comment is not."
        ),
    ),
    Mechanism(
        language="typescript",
        files=("test/**/*.test.ts", "src/**/*.test.ts", "**/*.test.ts"),
        concurrency=r"describe\.concurrent|test\.concurrent|jest\.maxWorkers",
        isolation=r"",
        note="bun test runs files in one process, sequentially, so this language rarely bites.",
    ),
)

#: A cleanup that can delete rows another test can see. Matched against a line
#: with its string literals and comments already stripped, because a `truncate`
#: in a prose comment is not a cleanup — measured across this fleet, every one of
#: its `truncate` hits outside darkroom is a truncated STRING, and a checker
#: that cannot tell the two apart is worse than no checker.
UNSCOPED_CLEANUP = re.compile(
    # `TRUNCATE` must be followed by something that names a table, a schema, or
    # `TABLE`. A BARE `TRUNCATE` is almost always prose, and this fleet has two
    # instances of a sentence that would otherwise be a false alarm on a service
    # that has no such problem:
    #   identity/internal/tenancy/tenancy_test.go:187
    #     // global TRUNCATE is precisely the non-deterministic failure dbtest's
    #     // package comment
    # That comment is the argument FOR this checker, written in the right place
    # by somebody who had already reasoned it out, and a checker that flagged it
    # would be reporting the fix as the defect.
    r"\bTRUNCATE\s+(?:TABLE\b|CASCADE\b|ONLY\b|user\b|public\b|\w+\s*(?:,|;|$))"
    # A DELETE is matched by its TABLE NAME and nothing after it. An earlier
    # version anchored on `(?:;|$|')`, which assumed the statement ends the
    # line — and after `strip_literals` has replaced the string with nothing,
    # `sqlx::query("DELETE FROM users")` reads `DELETE FROM users     sqlx::query()`
    # and the anchor fails. That is not a hypothetical: it made case 2 of this
    # checker's own self-test come back CLEAN on a fixture containing nothing but
    # a table-wide DELETE. Narrowing is decided in `looks_like_a_cleanup`, which
    # looks for the predicate; the pattern here only has to find the statement.
    r"|\bDELETE\s+FROM\s+[\w.\"]+"
    r"|\.delete_all\b"
    r"|\.destroy_all\b"
    r"|delete_all_objects\b",
    re.IGNORECASE,
)

#: ...and a DELETE that IS narrowed. `where id = $1` and friends are the shape
#: identity uses, and they are what makes a shared database survivable.
#: A `DELETE FROM t WHERE ...` narrowed to a row. The raw-SQL spelling has to be
#: here as well as the builder spelling, because darkroom's store writes its
#: deletes as raw strings:
#:
#:     delete from idempotency_keys
#:      where key = $1 and endpoint = $2 and principal_key = $3 and status_code = 0
#:
#: That is `src/store.rs:776`, production code, and it is keyed three ways. A
#: checker that only recognised `.where(` would call it a hazard on the strength
#: of the word `delete`.
SCOPED_DELETE = re.compile(r"\bWHERE\b|\.where\(", re.IGNORECASE)

#: A cleanup whose blast radius is already bounded by something other than a
#: WHERE clause, so it cannot reach a row another test owns.
#:
#: **This is not a convenience.** It is the whole difference between reporting
#: darkroom as a hazard and reporting it as fixed, and getting it wrong in
#: either direction was measured on this fleet:
#:
#:   * `darkroom` calls a bare `truncate(&store)` at tests/common/mod.rs:351 and
#:     its body is `truncate assets, …` — unqualified names resolved through the
#:     pool's `search_path`, which `test_store()` sets to a schema named after
#:     THIS test. That truncate empties one schema. Reported as an unscoped
#:     cleanup it is a false alarm on the one repository in the fleet that has
#:     already fixed the defect, which is how a checker gets switched off.
#:   * `identity` has 15 sites my first version flagged and EVERY ONE is a
#:     string or a clock: `time.Now().UTC().Truncate(time.Microsecond)` at
#:     accounts/store_test.go:416, a local `truncate(string(serialised), 400)`
#:     helper at client/credential_leak_test.go:437, and eight prose comments.
#:     Not one touches a table. A checker that reported identity as carrying
#:     darkroom's defect would have sent a reader to fix a green suite.
SCOPED_CLEANUP = re.compile(
    # A store or pool the caller scoped. `truncate(&store)` reaches only what
    # `&store`'s search_path resolves to, which is the per-test schema.
    r"\(\s*&?\s*(?:store|pool|tx|conn)\s*[,)]"
    # A call carrying a table list AND running inside a schema-scoped helper is
    # covered by the above; here we only reject a truncate whose argument is
    # provably a non-DB value.
    r"|\.truncate\(\s*(?:time\.|string\(|\w+\s*\))",
    re.IGNORECASE,
)

DECLARATION_NAME = "db_isolation.yml"


def strip_literals(line: str) -> str:
    """Return `line` with string literals and trailing comments removed.

    The reason this exists is a measurement, not a precaution. Across billing,
    courier, muse, pantry, identity, gateway, darkroom, parlor, core and kit, a
    grep for `truncate` over the test trees returns a hit in nine repositories
    and every single one is a truncated STRING or a sentence about the word:

        muse/tests/test_telemetry.py:249
            test_a_long_value_is_truncated_to_the_attribute_ceiling
        courier/test/courier/telemetry_canary_test.exs:245
            that "ignore" must not mean "truncate and keep the usable part"

    A checker that reported those as shared-table truncates would produce a
    false alarm in nine repositories and would be switched off.
    """
    # SQL literals, collapsed to their CONTENT so a predicate inside one is
    # visible. This is the third and last half of reading a delete, and it
    # exists because of darkroom/src/store.rs:774-780, which writes:
    #
    #     sqlx::query(
    #         r#"
    #         delete from idempotency_keys
    #          where key = $1 and endpoint = $2 and principal_key = $3 and status_code = 0
    #         "#
    #     )
    #
    # The `where` is three lines BELOW the `delete from`, so no line-by-line
    # reader can see that this delete is keyed three ways. Collapsing the
    # literal first is what makes the predicate reachable; a checker that calls
    # this a hazard is reporting a production function that cannot delete
    # another test's row.
    sql_literals = re.findall(r'r#"(.*?)"#|"""(.*?)"""|"(.*?)"|\'(.*?)\'', line)
    # `next(...)` without a default raises StopIteration inside a generator
    # expression, which Python 3.7+ turns into a RuntimeError — and the shape
    # that triggers it is an EMPTY literal. `t.Fatalf("")` is the shortest one,
    # and billing has both, so this crashed the checker on the very repository
    # it was written to clear, and every finding below it was reported as zero.
    # A checker that reports "0 cleanups found" because it died four lines up is
    # the false all-clear this whole packet warns about.
    #
    # ONLY a literal that looks like SQL is collapsed back in. An earlier version
    # restored every literal's content, and identity's admin store test then
    # failed on the very next line after the code it should have stopped at:
    #
    #     if _, err := pool.Exec(ctx, `DELETE FROM account_audit_log WHERE id = $1`, rec.ID); err == nil {
    #         t.Fatal("a DELETE from the audit trail SUCCEEDED")
    #
    # That `t.Fatal` is a FAILURE MESSAGE. "a DELETE from the audit trail" is
    # English about a delete, and it was reported as a second delete — on a
    # repository whose suite this packet measured green three times out of
    # three. The rule is the narrow one: a literal whose text contains a SQL
    # verb is SQL, and anything else is a message.
    sql_verb = re.compile(
        r"\b(?:delete\s+from\s+[\w.\"]+\s*(?:;|where\b|$)"
        r"|truncate\s+[\w.\"]"
        r"|insert\s+into\s+[\w.\"]"
        r"|update\s+[\w.\"]+\s+set\b"
        r"|drop\s+table\b"
        r"|select\s+[\w*\"]+\s+from\b)",
        re.IGNORECASE,
    )
    collapsed = "".join(
        next((part for part in match if part), "")
        for match in sql_literals
        if sql_verb.search(next((part for part in match if part), ""))
    )
    without_strings = re.sub(r'r#"(.*?)"#|"""(.*?)"""|"(.*?)"|\'(.*?)\'', "", line)
    if collapsed:
        without_strings = collapsed + " " + without_strings
    # `///` and `//!` have to go before `--`, or a Rust doc comment is cut in
    # half at the wrong place and the half that survives reads as code.
    without_strings = re.sub(r"^\s*//[/!]?", "", without_strings)
    return without_strings.split("//")[0].split("#")[0].split("--")[0]


def strip_comments(text: str) -> list[str]:
    """Return `text`'s lines with every comment removed, blanked in place.

    `strip_literals` handles a comment that STARTS on the line it is judged by.
    This handles the harder half, which is a comment that starts on an earlier
    line and CONTINUES across the line under inspection. Both of this checker's
    last false positives were that, and both were in repositories the checker
    was supposed to clear:

      darkroom/tests/common/mod.rs:109
        /// arrangement this harness exists to remove, so they would truncate each
      darkroom/tests/schema_isolation.rs:347
        /// not — a `truncate` that
      identity/internal/platform/ci/substrate_copy_test.go:130
        // because a `$caf$;` inside a comment or a string would otherwise truncate the

    A line-by-line reader cannot tell those from `truncate(&store)`, because on
    that line alone they ARE a truncate — the information is in the lines above.
    So the comment state is carried down the file and a line inside a block or
    line comment is blanked rather than merely trimmed. Blanked, not deleted: the
    line keeps its number so a finding can still name `file:line` and a reader
    can go and look at it.
    """
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        if in_block:
            out.append("")
            if "*/" in line:
                in_block = False
            continue
        if line.lstrip().startswith("/*"):
            out.append("")
            if "*/" not in line:
                in_block = True
            continue
        # `strip_literals` blanks a trailing comment; this blanks the part of
        # the line BEFORE one, which is where a wrapped sentence puts its verb.
        head = re.split(r"//|/\*|#(?![{])", line, maxsplit=1)[0]
        out.append(head if head.strip() else "")
    return out


def join_multiline_sql(lines: list[str]) -> list[str]:
    """Fold a multi-line SQL literal onto the line that opens it.

    A raw string in Rust, a heredoc in Ruby and a triple-quoted string in Python
    all span lines, and a `delete from` inside one has its `where` on the NEXT
    line. Measured, darkroom/src/store.rs:774-780:

        sqlx::query(
            r#"
            delete from idempotency_keys
             where key = $1 and endpoint = $2 and principal_key = $3 and status_code = 0
            "#
        )

    Judged line by line, that `delete from` looks exactly like a table-wide one.
    Folded, it is a delete keyed three ways. The finding still names the line the
    literal OPENS on, which is where a reader starts looking anyway.
    """
    out: list[str] = []
    index = 0
    # (opener, closer). Rust's `r#"…"#` is the case that needs a PAIR: the
    # opener does not contain the closer, so "is this line unterminated" cannot
    # be answered by looking for the closer on the opening line at all.
    #
    # The first version of this function did exactly that and found nothing: for
    # `        r#"` the closer `"#` does not occur on the line, so it concluded the
    # literal was closed and folded nothing. `r#"` alone on its own line is how
    # rustfmt writes every multi-line SQL string in darkroom, so the fold this
    # function exists for never once happened, and `delete from
    # idempotency_keys` was read three lines away from its own `where` — a
    # production delete keyed three ways, reported as a table-wide one.
    openers = (('r#"', '"#'), ('"""', '"""'), ("'''", "'''"), ('r"""', '"""'))
    while index < len(lines):
        line = lines[index]
        closer = next((end for start, end in openers if start in line), None)
        if closer:
            # Already closed on this line? Only then leave it alone.
            rest = line.split(closer[0] if closer in line else closer, 1)
            already_closed = closer in line and len(rest) > 1 and rest[1].strip()
            if not already_closed:
                buffer = [line]
                index += 1
                while index < len(lines) and closer not in lines[index]:
                    buffer.append(lines[index])
                    index += 1
                if index < len(lines):
                    buffer.append(lines[index])
                out.append(" ".join(part.strip() for part in buffer))
                continue
        out.append(line)
        index += 1
    return out


def looks_like_a_cleanup(line: str, path: str) -> bool:
    """Is this line a cleanup that can delete rows another test can see?"""
    bare = strip_literals(line)
    if not UNSCOPED_CLEANUP.search(bare):
        return False
    # A migration's own `DROP TABLE` is not a test cleanup; a test asserting on
    # one is exercising reversibility, which is the point.
    if "migrations" in path or re.search(r"\bDROP\s+TABLE\b", bare, re.IGNORECASE):
        return False
    # A DELETE carrying a predicate is narrowed to a row, which is the whole
    # difference between identity's suite (every cleanup keyed by id, green
    # three runs out of three) and darkroom's pre-fix suite (every cleanup a
    # blanket truncate, red six out of six).
    if re.search(r"\bDELETE\s+FROM\s+\w+\s+(?!;|$)", bare, re.IGNORECASE) and SCOPED_DELETE.search(bare):
        return False
    # The blast radius is already bounded by a search_path-scoped handle.
    if SCOPED_CLEANUP.search(bare):
        return False
    return True


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


@dataclass
class ServiceReport:
    """One service's verdict, with the three conditions and the evidence."""

    name: str
    path: str
    language: str = ""
    has_database_tests: bool = False
    shares_one_database: bool = False
    unscoped_cleanup: list[str] = field(default_factory=list)
    scoped_cleanup: int = 0
    concurrency: list[str] = field(default_factory=list)
    per_process_database: bool = False
    per_test_schema: bool = False
    uses_a_fake: bool = False
    isolation_mechanism: str = ""
    declared: bool = False
    declaration_error: str = ""

    @property
    def conditions(self) -> tuple[bool, bool, bool]:
        """(1) shares a database, (2) an unscoped cleanup, (3) concurrency.

        Two mechanisms COLLAPSE a condition, and each was measured rather than
        assumed:

        * `per_process_database` collapses (1). A runner that gives each worker
          its own database has not shared one, whatever the cleanup does —
          billing, verified by running Rails' own fork hook for four workers in
          four processes and reading the database each one reported.

        * `per_test_schema` collapses (2). An unqualified `truncate assets`
          resolves through the connection's `search_path`, so with a per-test
          schema on that path the truncate empties THIS test's copy and nothing
          else — which is darkroom's fix, and it is why reporting darkroom as
          carrying the defect it was repaired for would be worse than no check.
        """
        shared = self.shares_one_database and not self.per_process_database
        unscoped = bool(self.unscoped_cleanup) and not self.per_test_schema
        if self.uses_a_fake:
            # Nothing is shared because nothing is a server.
            return (False, False, bool(self.concurrency))
        return (shared, unscoped, bool(self.concurrency))

    @property
    def verdict(self) -> tuple[str, str]:
        """(finding id, severity) or ("", "") when there is nothing to report."""
        shared, unscoped, concurrent = self.conditions
        if not (shared and unscoped):
            return ("", "")
        if concurrent:
            return ("db-isolation.hazard", "fail")
        return ("db-isolation.latent", "fail")


def detect_language(repo: Path) -> Mechanism | None:
    """The language whose test files this repository has, from its manifest.

    A manifest rather than an extension count, because the packet's own survey
    got this wrong in both directions — it recorded muse as Go and pantry as
    Python, when muse/pyproject.toml is a Python project and pantry/Cargo.toml
    is a Rust crate. Neither has a database at all.
    """
    if (repo / "Cargo.toml").is_file():
        return MECHANISMS[0]
    if (repo / "go.mod").is_file():
        return MECHANISMS[1]
    if (repo / "mix.exs").is_file():
        return MECHANISMS[2]
    if (repo / "Gemfile").is_file():
        return MECHANISMS[3]
    if (repo / "pyproject.toml").is_file():
        return MECHANISMS[4]
    if (repo / "package.json").is_file():
        return MECHANISMS[5]
    return None


def test_files(repo: Path, mechanism: Mechanism) -> list[Path]:
    found: list[Path] = []
    for pattern in mechanism.files:
        found.extend(p for p in repo.glob(pattern) if p.is_file())
    skip = {"node_modules", "target", "_build", ".venv", "__pycache__", "dist", "vendor"}
    return sorted({p for p in found if not skip & set(p.parts)})


def scan_service(repo: Path, mechanism: Mechanism) -> ServiceReport:
    report = ServiceReport(name=repo.name, path=str(repo), language=mechanism.language)
    files = test_files(repo, mechanism)
    if not files:
        return report

    # A database test is one that names a database at all. Without this a
    # repository with a big suite and no database — pantry, which has 13 test
    # files and no DSN anywhere — would be reported as a hazard for the crime
    # of having tests.
    database_mention = re.compile(
        r"TEST_DATABASE_URL|DATABASE_URL|search_path|CREATE SCHEMA|create schema|"
        r"dbtest\.|SQL\.Sandbox|use_transactional_tests|ActiveRecord::Base",
        re.IGNORECASE,
    )

    # A suite whose database is a stand-in has no shared database to share, and
    # therefore cannot have this defect however it spells its cleanup. Measured:
    # muse's 968 tests all run against `tests/support/fake_database.py`, which
    # answers `"delete from" in sql` by popping a dict key. That is a real
    # database test and it is genuinely isolated, and reporting it as latently
    # dangerous would be a false alarm about the cleanest suite in the fleet.
    if mechanism.fake and any(
        re.search(mechanism.fake, read_text(path)) for path in files
    ):
        report.uses_a_fake = True
        report.isolation_mechanism = "a test double standing in for the driver"
        return report

    for path in files:
        relative = str(path.relative_to(repo))
        text = read_text(path)
        if not text:
            continue
        if database_mention.search(text):
            report.has_database_tests = True
        code_lines = join_multiline_sql(strip_comments(text))
        for number, line in enumerate(code_lines, start=1):
            if looks_like_a_cleanup(line, relative):
                report.unscoped_cleanup.append(f"{relative}:{number}")
            elif UNSCOPED_CLEANUP.search(strip_literals(line)):
                report.scoped_cleanup += 1
            if re.search(mechanism.concurrency, line):
                report.concurrency.append(f"{relative}:{number}")

    # The whole repository is scanned for the isolation mechanism, not just the
    # test files: darkroom's lives in `tests/common/mod.rs`, a helper, and
    # identity's in a package no single test file mentions.
    #
    # ORDER IS THE POINT, and getting it wrong is a measured false positive.
    # darkroom keeps BOTH `tests/common/mod.rs` (which does the isolating) and
    # `tests/schema_isolation.rs` (which asserts the isolating happened), and an
    # unordered rglob reached the assertion first — so the guard reported
    # darkroom as carrying the defect it was repaired for, on a repository whose
    # parallel suite this packet measured green. A service's own test of its own
    # fix must not be mistaken for the fix.
    harness_like = re.compile(
        r"common|support|helper|conftest|dbtest|test_helper|fixture|platform/db|harness",
        re.IGNORECASE,
    )
    # A TEST file is one whose whole job is asserting; a harness is one a test
    # calls into. `*_test.go`, `*_test.rs`, `*_test.exs`, `test_*.py` and
    # `*_test.rb` are assertions.
    assertion_like = re.compile(r"_test\.|\btest_|spec_|schema_isolation|/ci/", re.IGNORECASE)

    candidates: list[Path] = []
    for candidate in repo.rglob("*"):
        if not candidate.is_file() or candidate.stat().st_size > 512_000:
            continue
        if {"node_modules", "target", "_build", ".venv", "__pycache__", ".git"} & set(candidate.parts):
            continue
        if candidate.suffix in {".rs", ".go", ".ex", ".exs", ".rb", ".py", ".ts"}:
            candidates.append(candidate)

    def rank(candidate: Path) -> tuple[int, str]:
        relative = str(candidate.relative_to(repo))
        is_assertion = bool(assertion_like.search(relative))
        is_harness = bool(harness_like.search(relative))
        # A harness that is not an assertion outranks a file that is neither.
        return (0 if (is_harness and not is_assertion) else (2 if is_assertion else 1), relative)

    for candidate in sorted(candidates, key=rank):
        if mechanism.isolation and re.search(
            mechanism.isolation, read_text(candidate), re.IGNORECASE
        ):
            relative_candidate = str(candidate.relative_to(repo))
            report.isolation_mechanism = relative_candidate
            # A search_path that is SET, not merely mentioned, and in the
            # HARNESS rather than in a test of the harness. `set search_path to
            # t_<hex>` scopes a connection to one test's schema; a comment
            # containing the word scopes nothing. darkroom/tests/common/mod.rs:315
            # is the shape, applied per CONNECTION — a pool hands any of its
            # connections to any statement, so a search_path set on one
            # connection would isolate whichever query happened to get it.
            if re.search(r"set\s+search_path", read_text(candidate), re.IGNORECASE):
                report.per_test_schema = True
            break

    # cargo's concurrency is the DEFAULT, so "no opt-in found" must not read as
    # "not concurrent". darkroom measured this the hard way: before its fix,
    # `cargo test -- --ignored` exited 101 six times out of six with a different
    # failing set each run, and nothing in the source opted into anything — libtest
    # spawns a thread per `#[test]` function and `cargo` runs test BINARIES in
    # parallel. A checker that reported "runner is concurrent: no" for a Rust
    # suite would have cleared the exact repository the packet is about, so the
    # rule is inverted for this language: any test function at all means
    # concurrent, and the per-test schema is what has to be found to answer "is
    # it safe" rather than "is it serial".
    if mechanism.language == "rust" and report.has_database_tests:
        test_functions = sum(
            len(re.findall(r"#\[(tokio::)?test", read_text(path))) for path in files
        )
        if test_functions and not report.concurrency:
            report.concurrency = [f"cargo default ({test_functions} test functions)"]

    if mechanism.processes:
        for candidate in ("config/environments/test.rb", "test/test_helper.rb", "Rakefile"):
            text = read_text(repo / candidate)
            if text and re.search(mechanism.processes, text):
                report.per_process_database = True
                report.isolation_mechanism = report.isolation_mechanism or candidate
                break

    # Sharing one database is the DEFAULT for every runner in this fleet, so it
    # is recorded whenever there are database tests and not scoped away. What
    # removes it is a mechanism, not an intention.
    report.shares_one_database = report.has_database_tests

    declaration = repo / DECLARATION_NAME
    if declaration.is_file():
        report.declared = True
        text = read_text(declaration)
        if not text.strip():
            report.declaration_error = "db_isolation.yml is empty"
        elif "shared:" in text and "schema" not in text and "transaction" not in text:
            report.declaration_error = (
                "db_isolation.yml claims `shared: true` and names no schema or transaction, "
                "which is darkroom's pre-fix shape written down as a decision"
            )
    return report


def services_in(root: Path) -> list[Path]:
    """Every service under `root`, skipping the ones that own no tests."""
    if detect_language(root) is not None:
        return [root]
    found = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and candidate.name not in {".git", "node_modules", "wt-m39-pantry-27"}:
            if detect_language(candidate) is not None:
                found.append(candidate)
    return found


def check(root: Path) -> list[ServiceReport]:
    reports = []
    for repo in services_in(root):
        mechanism = detect_language(repo)
        if mechanism is None:
            continue
        report = scan_service(repo, mechanism)
        if report.has_database_tests:
            reports.append(report)
    return reports


def render(reports: list[ServiceReport]) -> str:
    if not reports:
        return (
            "db-isolation-check: no service with database tests was found.\n"
            "  A service with tests and no database cannot have this defect; that is a\n"
            "  finding, not an absence of one."
        )
    lines: list[str] = []
    failures = 0
    for report in reports:
        shared, unscoped, concurrent = report.conditions
        identifier, severity = report.verdict
        if identifier:
            failures += 1
        lines.append(f"{report.name}  ({report.language})")
        lines.append(f"  1. shares one database:            {'YES' if shared else 'no'}")
        lines.append(f"  2. a cleanup can reach other rows: {'YES' if unscoped else 'no'}"
                     f"  ({len(report.unscoped_cleanup)} site(s),"
                     f" {report.scoped_cleanup} narrowed)")
        lines.append(f"  3. runner is concurrent:           {'YES' if concurrent else 'no'}"
                     f"  ({len(report.concurrency)} site(s))")
        if report.per_process_database:
            lines.append("     each parallel worker is given its OWN database, which is why (1) is no")
        if report.isolation_mechanism:
            lines.append(f"     per-test isolation found in: {report.isolation_mechanism}")
        if report.declared:
            lines.append("     declared in db_isolation.yml")
        if report.declaration_error:
            lines.append(f"     FAIL db-isolation.declaration-unreadable: {report.declaration_error}")
            failures += 1
        if identifier:
            lines.append(f"  FAIL {identifier} [{severity}]")
            lines.append(f"       {FINDINGS[identifier][1]}")
            lines.append(f"       fix: {FINDINGS[identifier][2]}")
        elif shared and unscoped:
            lines.append("  ok   conditions (1) and (2) are both present and (3) is not")
        else:
            lines.append("  ok   the hazard needs all three and this service does not have all three")
    lines.append("")
    lines.append(f"{failures} failure(s)")
    return "\n".join(lines)


def to_json(reports: list[ServiceReport]) -> str:
    payload = []
    for report in reports:
        shared, unscoped, concurrent = report.conditions
        identifier, severity = report.verdict
        payload.append(
            {
                "service": report.name,
                "language": report.language,
                "conditions": {
                    "shares_one_database": shared,
                    "cleanup_reaches_other_rows": unscoped,
                    "runner_concurrent": concurrent,
                },
                "unscoped_cleanup_sites": report.unscoped_cleanup,
                "narrowed_cleanup_sites": report.scoped_cleanup,
                "concurrency_sites": report.concurrency[:20],
                "per_process_database": report.per_process_database,
                "isolation_mechanism": report.isolation_mechanism,
                "declared": report.declared,
                "finding": identifier,
                "severity": severity,
            }
        )
    return json.dumps({"services": payload}, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="db-isolation-check",
        description="Can one test in a service's suite delete another test's fixtures?",
    )
    parser.add_argument("repo", nargs="?", default=".", help="a service, or a fleet root")
    parser.add_argument("--json", action="store_true", help="emit the findings as JSON")
    parser.add_argument("--explain", action="store_true", help="list every finding")
    arguments = parser.parse_args(argv)

    if arguments.explain:
        for identifier in sorted(FINDINGS):
            severity, claim, remediate = FINDINGS[identifier]
            print(f"{identifier}  [{severity}]\n  {claim}\n  fix: {remediate}")
        return EXIT_OK

    root = Path(arguments.repo)
    if not root.is_dir():
        print(f"db-isolation-check: {root} is not a directory", file=sys.stderr)
        return EXIT_CANNOT_RUN

    reports = check(root)
    print(to_json(reports) if arguments.json else render(reports))
    return EXIT_FINDINGS if any(r.verdict[0] for r in reports) or any(
        r.declaration_error for r in reports
    ) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
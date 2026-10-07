#!/usr/bin/env python3
"""tenancy_check — is a service's account-isolation declaration still true?

    tenancy-check .                       # static: the declaration against the tree
    tenancy-check --json .                # the same findings, as JSON
    tenancy-check --explain               # every finding this checker can report

WHAT THIS IS

The platform is sold as self-hostable multi-tenant code. The defect that ends
that product is one customer reading another's data, and measured across the
fleet that defect is invisible from the outside:

    cross-tenant NEGATIVE tests — ones asserting account A is refused account B
    identity 7    courier 19
    billing 0   cafaye-rb 0   cafaye-ts 0   gateway 0
    darkroom 0  pantry 0     muse 0        cafaye-py 0

Two services prove isolation. Eight do not, and six of those scope by account
in production code. `darkroom` is the clean case: `assets` and `asset_variants`
carry `account_id uuid not null`, every query reads `where id = $1 and
account_id = $2`, and **zero** tests assert any of it. A refactor that drops
one `and account_id = $2` gives a customer another customer's files and the
whole suite stays green.

SO THE BOUNDARY IS DECLARED, IN `tenancy.yml`, AGAINST THIS SCHEMA

...and declared rather than inferred because inference is what just failed.
Counting account-scoped routes by pattern gives a different answer per
framework:

    gateway     route_defs=96     (TypeScript decorators)
    muse        route_defs=76
    cafaye-ts   route_defs=51
    darkroom    route_defs=0      (axum — a different syntax entirely)
    billing     route_defs=0      (Rails — a different syntax entirely)

A grep reporting "darkroom has no routes" when darkroom has account-scoped
queries against customer assets is **worse than no grep**, because it reads
like an answer. So this checker does not count routes. It reads the service's
own enumeration, checks that enumeration against the tree, and says out loud
what it could not classify.

WHAT THE DATABASE DOES ABOUT IT, AND THE ONE RULE THIS FILE EXISTS FOR

The declaration's second half, `rls`, says what Postgres itself does — and the
rule it exists for is one Postgres documents in the CREATE TABLE reference and
NOT in the row-level-security guide, and which **no lint anywhere checks**:

    Postgres does not apply row-level security to a table's OWNER unless the
    table is set FORCE ROW LEVEL SECURITY.

Supabase's database advisor is the reference for this problem and is worth
reading rather than reinventing. It collects `relforcerowsecurity` — the FORCE
bit — for its dashboard's table list and never judges it (measured:
`packages/pg-meta/src/sql/studio/advisor/lints.ts`). So the realistic bad
outcome is a team that ships policies, enables RLS, and is silently wrong on
exactly the tables a service owns in its own schema, while every gate is green.
Cafaye uses `FORCE` zero times today, which is why this is free to prevent
rather than expensive to retrofit.

    tenancy.rls-owner-bypass   a FAILURE, and the headline of this half.

Everything else in `tenancy.rls-*` is that rule's neighbours, adapted from
advisor lints 0003, 0007, 0008, 0010, 0011, 0016, 0017 and 0024 into static
text checks. `docs/tenancy.md` carries the ledger: every one of the advisor's
twenty-eight lints is marked adopted, adapted or left out, with a reason, and
the exclusions are a test.

CROSS-TENANT ACCESS IS ANSWERED AS NONEXISTENCE

The assertions the two proving services write are about **absence**, not
refusal:

    assert WebhookEndpoints.get(endpoint.id, @other_account_id) == nil
    assert WebhookEndpoints.list(@other_account_id) == []

A `403` tells an attacker the id exists; a `nil`/`[]`/`NotFound` tells them
nothing. So `schemas/tenant-isolation.schema.json` makes `negative.asserts` a
`const: absent`, and `tenancy.denial-refuses` is a FAILURE — if your contract
permits "forbidden" for another account's resource, it has reintroduced an
enumeration oracle, and a test must be able to catch that. See D33.

AND IT IS ANSWERED IN THREE DIRECTIONS, NOT ONE

"The request was refused" is satisfied by a table with no policy at all, by a
table with no predicate at all, and by a service whose database is switched off
— which is the BUG, not the fix. So `negative.cases` is exactly three arms:

    no-identity     nothing is acting             -> zero rows
    other-account   a VALID credential, other one -> zero rows
    own-account     this account's own credential -> ITS ROWS

The third is the load-bearing one. A service that returns nothing to everybody
satisfies the first two, and that is a broken service rather than an isolated
one, so `negative.cases[].asserts` is a `const: present` on that arm:
`tenancy.positive-control-refused` is a FAILURE when the arm is answered with
the language's own spelling of nothing.

WHAT IS PROVED, AND WHAT IS NOT

Four things, and the fourth is the one this packet exists for:

  * every declared entry point names a file that EXISTS and a line that is
    really there — a declaration pointing at nothing is worse than none;
  * the enforcement line still carries the tenancy key, so dropping the
    predicate is a red rather than a refactor;
  * the declared enumeration is CLOSED in both directions, against the SQL the
    scanner can read: a site it finds that nobody declared, and a declaration
    whose site it can no longer find;
  * each entry point's negative assertion is in the service's tests, on the
    line the declaration names, and asserts absence.

And one thing it deliberately does not do: **claim completeness for a language
it cannot read.** `tenancy.enumeration-partial` is a WARNING that names every
declared entry point the scanner could not classify and every account-scope
site it saw and could not attribute, and it says the declaration is not proven
closed. A warning never moves the exit code, so a Go service's CI stays green —
and the report cannot be read as "no routes found".

EXIT CODES

    0   no finding at severity `fail`. Warnings may still be printed.
    1   at least one `fail`.
    2   the check could not happen. Never 0, and never 1: a run that could not
        find the declaration has not checked the boundary, and converting an
        unknown into a green badge is the defect core exists to prevent.

PYTHON 3.9, AND WHY THIS FILE IS NOT 3.11

`harness/gate_check.py` needs 3.11 because it reads `mise.toml` and `tomllib`
is stdlib from 3.11. This one reads no TOML and runs no process, so it runs on
the same floor as `harness/cafaye_contract.py`. That is not a detail: a
contract check that needs an interpreter some service's CI does not have is a
contract check that runs nowhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from cafaye_contract import Refusal, read_yaml
except ModuleNotFoundError as _missing:  # pragma: no cover
    raise SystemExit(
        f"tenancy_check: cannot import cafaye_contract from {Path(__file__).resolve().parent}: "
        f"{_missing}. tenancy_check travels with the harness; a copy of one without the "
        "other would mean a second YAML dialect, which is the drift core exists to prevent."
    )

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

#: The declaration file. One per repository, at its root. Named for the same
#: reason `gate.yml` is: a boundary that is discovered by guessing its
#: filename is not a declaration.
DECLARATION = Path("tenancy.yml")

#: The schema the declaration is written against. This file is stdlib-only, so
#: it re-implements the handful of constraints that decide whether a
#: declaration is well-formed — core's own idiom for a document and its schema
#: being the same contract written twice.
TENANCY_SCHEMA_RELATIVE = Path("schemas") / "tenant-isolation.schema.json"

#: The floor. See the module docstring: this checker reads no TOML and runs no
#: process, so it does not inherit `gate_check`'s 3.11.
MINIMUM_PYTHON = (3, 9)

#: The modules this file may import beyond the contract harness's own list.
#: Everything here is stdlib and nothing else; there is no `tomllib`, no
#: `shlex` and no `tempfile`, which is the mechanical form of the version floor.
EXTRA_STDLIB: frozenset[str] = frozenset()

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
SUBJECT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXPECT_PATTERN = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_.]*|\[\])$")
#: `rls.identity`: a schema-qualified call taking no arguments. The `()` is the
#: whole constraint, and the reason it is there is in the schema — the per-row
#: rule is about the call being hoisted out of the row loop, and a call with
#: arguments cannot be hoisted.
IDENTITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\(\)$")
PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+$")
SCOPE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/tenancy_findings.json` and asserted equal in both directions by
#: core's suite, for the reason `harness/rules.json` and
#: `harness/gate_findings.json` are both asserted: a finding nobody was told
#: about is a finding that will be wrong the first time somebody needs it.
FINDINGS: dict[str, tuple[str, str, str]] = {
    "tenancy.declaration-missing": (
        "fail",
        "the service declares no account boundary, so its boundary can only be discovered by reading every query by hand.",
        "write tenancy.yml; schemas/tenant-isolation.schema.json is the format and docs/tenancy.md is the worked example",
    ),
    "tenancy.declaration-unreadable": (
        "fail",
        "the declaration is not a YAML document core's reader accepts.",
        "run: python3 harness/bin/tenancy-check <repo> --explain, and read the file and line it names",
    ),
    "tenancy.schema": (
        "fail",
        "the declaration does not satisfy schemas/tenant-isolation.schema.json.",
        "run: python3 harness/bin/tenancy-check <repo> --explain, for the constraint and the path",
    ),
    "tenancy.location-missing": (
        "fail",
        "a declaration names a file that is not in this repository, so the boundary it claims to enforce is nowhere.",
        "point enforced.file and negative.file at files that exist, or restore the files it names",
    ),
    "tenancy.line-missing": (
        "fail",
        "a declaration names a line past the end of the file.",
        "point enforced.line and negative.line at lines that exist; a line number nobody checked is the false green written down",
    ),
    "tenancy.scope-lost": (
        "fail",
        "the entry point is still account-scoped, but not on the line the declaration names.",
        "move the declaration to the line that carries the tenancy key, or put the key back where the declaration says it is",
    ),
    "tenancy.bind-missing": (
        "fail",
        "the mechanism is bind-parameter and the parameter that carries the account is not on the declared line.",
        "pass the account where the declaration says it is passed, or change the mechanism to the one actually enforced",
    ),
    "tenancy.entry-absent": (
        "fail",
        "an entry point is declared and the scanner can no longer find it: either the scoping was dropped or the code is gone.",
        "put the tenancy key back in the statement, or delete the entry point from the declaration",
    ),
    "tenancy.undeclared-entry": (
        "fail",
        "the scanner found account-scoped access nobody declared, so the enumeration is a summary rather than a contract.",
        "add the entry point to tenancy.yml with its mechanism, its line and its negative assertion",
    ),
    "tenancy.enumeration-empty": (
        "fail",
        "the service says it scopes by account and declares no way it does.",
        "declare the entry points, or set accountScoped: false if the service genuinely holds no customer data",
    ),
    "tenancy.honest-zero": (
        "fail",
        "the service declares no account scoping and its tenancy key appears in the declared sources at a site nobody vouched for, so its honest zero is not honest.",
        "declare the account-scoped statements it has, or vouch for each key-carrying site that is not a row scope in scope.nonRowSites with the reason; the check fails for any site not named, and an omission is not a zero",
    ),
    "tenancy.denial-missing": (
        "fail",
        "the negative assertion for an entry point is not on the line the declaration names, so nothing asserts that account A is refused account B.",
        "write the assertion — absent, not refused — and point negative.line at the line that carries it",
    ),
    "tenancy.denial-refuses": (
        "fail",
        "the declaration answers cross-tenant access with a refusal, which is an enumeration oracle: a 403 tells an attacker the id exists.",
        "assert absence instead (nil, [], NotFound) and say so in negative.expects; see D33",
    ),
    "tenancy.enumeration-partial": (
        "warn",
        "this checker cannot classify every account-scoped site, so this declaration is NOT proven closed and this machine cannot settle it.",
        "read the named files by hand and confirm each one is declared; the checker's scanner reads SQL and account-key predicates only",
    ),
    "tenancy.scan-narrowed": (
        "warn",
        "a source path the declaration names is not in this repository, so the scan read less than was declared.",
        "point the declaration's source list at paths that exist — scope.sources or rls.sources, whichever one the finding names — or add the one that is missing",
    ),
    "tenancy.scope-key-unused": (
        "warn",
        "no account-scoped statement this scanner can read carries the declared tenancy key, so it found nothing to close the enumeration against.",
        "check scope.key against the column or parameter this service really scopes by; a key nothing matches is either spelled differently or lives in a language this scanner cannot classify",
    ),
    # ---- the database half. Eleven findings, and `tenancy.rls-owner-bypass` is
    # the one this file's second half exists for.
    "tenancy.denial-shape": (
        "fail",
        "a denial arm is asserted with the wrong SHAPE — an exception where the `using` clause raises nothing, or `lives_ok` where only the row's own value proves anything — so the assertion passes for a reason other than the one it claims.",
        "match the assertion to how Postgres denies it: a `select`/`delete` cross-tenant read is a `using` clause filtering the row out, which raises NOTHING and matches zero rows, so it is asserted as an empty result and never as an exception; and the `own-account` arm must read the row's own value, because `lives_ok` passes when the write matched zero rows",
    ),
    "tenancy.denial-unpaired": (
        "fail",
        "a denied write is asserted without reading the row it was aimed at, so \"matched zero rows\" is indistinguishable from \"found nothing to do\" — which is the difference between an assertion and a coincidence.",
        "pair the denied write with a read of the victim's row, scoped to that row, and declare it: a denied `update`/`delete` is asserted as `rows_affected_zero` / `assert_unchanged`, never as an absent result, because an empty result is a lie about a row that exists",
    ),
    "tenancy.positive-control-refused": (
        "fail",
        "the third arm of the denial shape declares this language's spelling of NOTHING as the answer to whether an account sees its own rows, so a service that returns nothing to anybody satisfies all three cases at once.",
        "point own-account at a line that reads the row's own value (checksum, status, id); a table with no policy at all is precisely what the other two arms cannot tell apart from a correct one",
    ),
    "tenancy.rls-owner-bypass": (
        "fail",
        "a table this declaration covers is not set FORCE ROW LEVEL SECURITY, and Postgres does not apply row-level security to a table's OWNER — so the role that owns the table reads every row in it.",
        "add: alter table <table> force row level security; — the bit is called FORCE ROW LEVEL SECURITY, it is separate from `enable`, and a table that is enabled without it still lets its owner read every row",
    ),
    "tenancy.rls-not-enabled": (
        "fail",
        "a table this declaration covers has policies but no `alter table … enable row level security`, so the policies are never evaluated and nothing raises.",
        "add: alter table <table> enable row level security; — and keep the force line beside it, because enabling without forcing leaves the owner reading every row",
    ),
    "tenancy.rls-policy-absent": (
        "fail",
        "a policy this declaration names is not in the DDL, so the boundary is described and not enforced.",
        "write the `create policy` the declaration names, or delete it from rls.tables[].policies and let the table be what it is",
    ),
    "tenancy.rls-undeclared": (
        "fail",
        "row-level-security DDL exists in the declared sources for something this declaration does not cover, so half an adoption is in the database and nobody is accountable for it.",
        "add the table and its policies to rls.tables with forced: true, or delete the enable/force/policy lines and say databaseEnforced: false — a policy nobody declared is the state this finding is named after",
    ),
    "tenancy.rls-permissive": (
        "fail",
        "a policy clause on an account-scoped table admits every row, or a policy names no role and therefore applies to PUBLIC, or the roles the declaration names and the roles the DDL binds are not the same roles, so the table's policies read as a boundary and are not one.",
        "write `to <runtime role>` and scope the clause by the identity in rls.identity; `using (true)` is not a boundary, it is the absence of one. For the role disagreement, rls.tables[].policies[].roles must name every role the `for … to …` clause names and no others",
    ),
    "tenancy.rls-public-read-absent": (
        "fail",
        "rls.publicRead names a table, the policy that grants it a public read and the role that read is granted to, and the migrations do not write that policy, or write it for another command or another role — so the declaration asserts a public read the database does not have.",
        "write the `create policy` the declaration names — `for select to <role>` with the clause that grants the read — or delete the entry from rls.publicRead; a public read is a claim with evidence, and a claim the DDL does not back is a boundary asserted into existence",
    ),
    "tenancy.rls-per-row": (
        "fail",
        "a policy calls the identity function bare instead of as `(select …)`, so Postgres re-evaluates it once per row rather than once per statement.",
        "wrap it — `account_id = (select app.current_account())` — which is also the only spelling rls.identity's `()` requirement admits",
    ),
    "tenancy.rls-role-bypass": (
        "fail",
        "a policy applies to a role carrying BYPASSRLS or SUPERUSER, and such a role skips every policy on every table it can read.",
        "revoke bypassrls/superuser from the runtime role, or point the policy at a role that does not have it; the runtime role needs no superuser to read its own account's rows",
    ),
    "tenancy.rls-unprotectable": (
        "fail",
        "a policy is written on a foreign table or a materialized view, neither of which row-level security can constrain, so the policy is a comment on a relation that ignores it.",
        "make it a table and let the policy constrain it, or drop the policy and scope the query that reads it — a materialized snapshot of every tenant's rows is not a boundary",
    ),
    "tenancy.rls-definer-search-path": (
        "fail",
        "a SECURITY DEFINER function does not pin its search path, so a caller can create an object earlier in the path and have the function resolve to it with the owner's rights.",
        "add `set search_path = ''` to the function and schema-qualify every name inside it; this is advisor lint 0011, raised from WARN to a failure because in cafaye it is a tenant-crossing primitive rather than a hardening nit",
    ),
    "tenancy.rls-view-invoker": (
        "fail",
        "a view over a table this declaration covers is not `security_invoker`, so it reads with its OWNER's privileges and the table's policies never run for the reader.",
        "recreate the view with `with (security_invoker = on)`, which needs PostgreSQL 15 or newer; without it a view is security definer by default",
    ),
    "tenancy.rls-unreadable": (
        "warn",
        "row-level-security statements were found in a source file type this checker does not parse, so the database half of this declaration is NOT proven closed and this machine cannot settle it.",
        "read the named files and confirm each policy and force bit is declared; a Rails service's migrations are .rb files, and being named here is the difference between 'I cannot see this' and a confident zero",
    ),
}

SEVERITIES = ("ok", "warn", "fail")

#: Every key a tenancy declaration may carry. Mirrors the root `properties` of
#: `schemas/tenant-isolation.schema.json`, so a field added to the schema and
#: never taught to this file is a red rather than a silent acceptance.
TOP_LEVEL_KEYS = frozenset({"version", "service", "accountScoped", "scope", "entryPoints", "rls"})
REQUIRED_TOP_LEVEL_KEYS = ("version", "service", "accountScoped", "scope", "entryPoints", "rls")

OPERATIONS = ("select", "update", "delete", "call")
MECHANISMS = ("query-filter", "bind-parameter", "repository-method", "middleware")

# --------------------------------------------------------------------------
# the three-way denial shape, and the vocabulary that makes arm three real
# --------------------------------------------------------------------------

#: The three arms, in the order the schema requires them. `own-account` is the
#: one with the information in it, and `tests/test_specs.py` asserts the schema
#: pins its `asserts` to `present` — a service that answers "does this account
#: see its own rows" with nothing has satisfied the other two arms for free.
DENIAL_ARMS = ("no-identity", "other-account", "own-account")

#: The arm that has to be answered with a row rather than with an absence.
POSITIVE_ARM = "own-account"

#: What each arm's `asserts` may only be. Derived from the id in the schema and
#: restated here because the checker has to believe it independently: a checker
#: that took `asserts` from the declaration would let a declaration widen its own
#: contract, which is the shape every `additionalProperties: false` in this file
#: exists to prevent.
ARM_POLARITY = {
    "no-identity": "absent",
    "other-account": "absent",
    "own-account": "present",
}

#: Every spelling of "it RAISED" this checker will refuse on a `using`-denied arm.
#:
#: Postgres denies a cross-tenant access three ways and they raise different
#: things, which is the table `docs/tenancy.md` states. Two of them raise `42501`:
#: a missing grant, and a `with check` violation. The third — a `using` clause
#: filtering the row out — raises **nothing at all** and matches zero rows, and it
#: is the common one. A suite that asserts a raise on a read the `using` clause
#: filtered out is asserting a *privilege* failure, and a table with no policy at
#: all produces exactly that error, so the assertion passes for the wrong reason
#: while isolation is completely broken.
#:
#: It lives here rather than in the schema for the same reason `ABSENCE_TOKENS`
#: does — it is a fact about the SERVICE's test file, and no JSON Schema can ask
#: whether a line in another language contains `assert_raises`. The duplicated
#: constraint has the same test: every token satisfies the schema's own `expects`
#: pattern, so a service can declare the spelling this checker refuses.
RAISING_TOKENS = frozenset({
    "assert_raises", "assert_raise", "assert_raises_error", "assert_raises_with_message",
    "assert_error", "assert_throws", "must_raise", "raises", "raise_error",
    "throws_ok", "throws", "expect_error", "to_raise", "should_raise",
    "assert_rejects", "rejects", "expectException", "assertThrows", "assertPanics",
    "panics", "should_panic", "expectPanic", "raises_exception",
})

#: Every spelling of "it did NOT raise", i.e. a liveness assertion.
#:
#: This is the same silence wearing a different hat and the source says so
#: outright: *"Never prove an allowed write with `lives_ok` — it passes when the
#: write matched zero rows."* An `own-account` arm naming one of these is a
#: declaration that the account sees its own rows, pointed at a line that would be
#: equally happy matching nothing. `tenancy.denial-shape` refuses it for the same
#: reason `tenancy.positive-control-refused` refuses an absent spelling: the third
#: arm exists to separate isolation from a service that returns nothing, and a
#: liveness assertion cannot separate anything.
LIVENESS_TOKENS = frozenset({
    "lives_ok", "live_ok", "does_not_raise", "doesnt_raise", "not_to_raise",
    "no_error", "no_exception", "expect_no_error", "assert_no_error",
    "assert_silent", "assert_ok", "succeeds", "survives", "assert_nothing_raised",
})

#: Every spelling of "nothing" this checker will refuse on the positive control.
#:
#: It is a fact about the SERVICE's test file, not about the declaration, so it
#: lives here and not in the schema — no JSON Schema can ask whether a line in
#: another language contains `nil`. Which means it is a duplicated constraint,
#: and core's rule for those is a test:
#: `test_the_positive_control_cannot_be_satisfied_by_asserting_absence` asserts
#: every token here satisfies the schema's own `expects` pattern, and that the
#: write shapes and the positive arm's own spelling are NOT in it.
ABSENCE_TOKENS = frozenset({
    "nil", "None", "empty", "[]", "not_found", "notfound",
    "NotFound", "ErrNotFound", "ErrNoRows",
})

# --------------------------------------------------------------------------
# the database half — what Postgres itself does
# --------------------------------------------------------------------------

#: The commands a row-level-security policy may govern, and the clause each one
#: is denied by. This pairing is not documentation, it is the table
#: `docs/tenancy.md` tells a service author to assert against: a `USING` clause
#: filters the row out and raises NOTHING, so a read denial is asserted as an
#: empty result, while a `WITH CHECK` violation raises 42501. Asserting an
#: exception on the read arm asserts a privilege failure and passes for the wrong
#: reason, which is how a policy that admits every tenant gets a green test.
POLICY_COMMANDS = ("select", "insert", "update", "delete", "all")

#: What `clause` each command may only carry. `update` and `all` are absent
#: because either is legal, and a conditional with no arm is how an exception
#: gets in.
COMMAND_CLAUSE = {
    "select": "using",
    "delete": "using",
    "insert": "with check",
}

#: What `cafaye.protect_table` writes, as the TEMPLATE resolves it.
#:
#: This is not a second copy of the template and it is not a fork of it: these are
#: the four facts the scanner needs in order to read the ONE call a migration
#: makes, and they are the facts the template already states in its own comments
#: (four policies, one per command, named `<table>_cafaye_<command>`; enable and
#: force, in that order, before any policy). When the template changes shape, the
#: change lands here — a service's migration keeps calling `protect_table` and
#: says nothing about how it is written.
#:
#: `SUBSTRATE_QUALIFIER` is the template's own `qual` local, spelled out because
#: the clause checks read it: the identity is WRAPPED in it, which is the
#: per-row rule passing for the right reason rather than by exemption, and it
#: names `account_id`, which is why it is never an always-true clause.
SUBSTRATE_POLICY_COMMANDS = ("select", "insert", "update", "delete")
SUBSTRATE_POLICY_SUFFIX = "_cafaye_"
SUBSTRATE_IDENTITY = "cafaye.current_account_id()"
SUBSTRATE_QUALIFIER = f"account_id = (select {SUBSTRATE_IDENTITY})"
SUBSTRATE_WRITER = "cafaye.protect_table"

#: What `cafaye.protect_credential_table` writes ON TOP of that, and it is the
#: whole of the difference between the two calls (kit MD24, `fea8052`).
#:
#: One more policy, for ONE command, named `<table>_cafaye_resolve` — which is
#: why this cannot be read as a fifth entry in `SUBSTRATE_POLICY_COMMANDS`: the
#: four are `<command>` and the fifth is not a command. And it is scoped by the
#: value the CALLER PRESENTED, from a transaction-local GUC, rather than by the
#: account. A scanner that assumed `<table>_cafaye_<command>` means the account
#: predicate would read the resolve policy as an account policy, which is a
#: SECOND correction rather than a wider regex — and the wrong one, because the
#: account predicate is a WIDENING here: the resolve policy exists to hold a
#: credential lookup to one row, and scoping it by the account is the table-wide
#: SELECT kit's own comment refuses.
#:
#: `CREDENTIAL_QUALIFIER` is the template's second `qual` local, in its
#: `format('%I = (select cafaye.current_credential_digest())', p_digest_column)`
#: form. The column name is substituted per table, so the qualifier is BUILT and
#: not a constant — which is the second half of what the checker reads out of the
#: call: the digest column is named in the migration and nowhere else, so a call
#: whose second argument is not a string literal says nothing about which column
#: resolves a credential on this table.
CREDENTIAL_POLICY_SUFFIX = "resolve"
CREDENTIAL_POLICY_COMMAND = "select"
CREDENTIAL_IDENTITY = "cafaye.current_credential_digest()"
CREDENTIAL_WRITER = "cafaye.protect_credential_table"

#: Relations row-level security cannot constrain, whatever their policies say.
#: Supabase's `foreign_table_in_api` (0017) and `materialized_view_in_api` (0016)
#: are both this fact, and both are WARNs there because PostgREST reachability is
#: the thing being measured. Here a policy on one of them is a FAILURE: it reads
#: as a boundary and is not one.
UNPROTECTABLE_KINDS = frozenset({"foreign_table", "materialized_view"})

#: A clause that admits every row. Supabase normalises whitespace and compares
#: against exactly these four, and does so for UPDATE, DELETE and ALL only —
#: `USING (true)` on a SELECT is often deliberate public read. Cafaye has a public
#: read tier now (`rls.publicRead`), but it is a claim with evidence rather than
#: an exemption: this arm stands down for a policy the declaration names as its
#: public read, and fires for every other always-true clause, because a public
#: read nobody declared is the defect this checker exists for and not a lesser
#: form of one. The severity stays a FAILURE — docs/tenancy.md's ledger records
#: the ruling that the tier narrows the check and does not soften it.
ALWAYS_TRUE_CLAUSES = frozenset({"true", "(true)", "1=1", "(1=1)"})

#: File suffixes the DDL scanner reads. Deliberately narrower than
#: `TEXT_SUFFIXES` above: a `.rb` file may contain SQL, and a `.py` file may
#: contain a migration as a string, and this checker cannot tell which. Anything
#: else carrying row-level-security DDL is named by `tenancy.rls-unreadable`,
#: which is the warning that says *this machine cannot answer* rather than a
#: clean bill of health over a file nobody read.
RLS_SUFFIXES = frozenset({".sql"})

#: What makes a file this scanner cannot parse worth NAMING rather than skipping.
#: Deliberately coarse: the claim `tenancy.rls-unreadable` makes is "there is
#: row-level-security DDL here and this checker cannot parse it", and the honest
#: way to decide that is whether the text mentions row-level security at all. A
#: Rails service's `db/migrate/*.rb` does; its `app/models/*.rb` does not, and
#: naming that one would train a reader to ignore the warning.
_RLS_MARKER = re.compile(
    r"\b(row\s+level\s+security|create\s+policy|force\s+row\s+level|security\s+definer)\b",
    re.IGNORECASE,
)

#: The operations the scanner can find in SQL. `call` is not among them by
#: construction — a repository method is a `select` as far as the boundary is
#: concerned and something else as far as a text scanner is concerned — and the
#: schema says so in the same words.
SCANNER_OPERATIONS = frozenset({"select", "update", "delete"})

#: The operations whose denial is a `using` clause, and therefore raises NOTHING.
#:
#: `select` and `delete` have no `with check` — there is no new row to check — so
#: their policies carry only `using` and a cross-tenant attempt matches zero rows
#: silently. `update` is here for the same reason: the `using` clause filters the
#: victim's row out before the write is ever attempted, so the attempt is silent,
#: and an `update` policy's `with check` is only reached by a write that already
#: matched a row the caller owns.
#:
#: `call` is deliberately absent: a repository method's scoping is enforced above
#: the statement and this checker cannot see which clause does the denying, so it
#: has no opinion. Guessing there would be a failure invented rather than caught.
USING_DENIED_OPERATIONS = frozenset({"select", "update", "delete"})

#: The operations that MUTATE an existing row, and so need the victim read back.
#:
#: A denied `update`/`delete` raises nothing and matches nothing, so the row count
#: is the only thing that says it was refused — and the row count is zero for a
#: write that matched nothing for ANY reason, including a bug. Pairing the attempt
#: with a read of the row the attempt targeted is what makes "matched nothing"
#: mean "was refused" rather than "found nothing to do", which is the difference
#: between an assertion and a coincidence.
WRITE_OPERATIONS = frozenset({"update", "delete"})

#: The three spellings of a tenancy key this checker will look for on a declared
#: enforcement line. The fleet has three vocabularies already (D7) and a
#: checker that guessed which one a service uses would be guessing at the
#: boundary rather than at the data. The bare key first, because `account_id`
#: is what four of the services write and the camel spelling is the fallback.
KEY_SPELLINGS = ("{key}", "{key}_", "{key}Id")

#: How far above a tenancy-key line the scanner looks for the operation keyword
#: that names the statement. A SQL statement is routinely wrapped across lines,
#: and attributing the key to the nearest preceding `select`/`update`/`delete`
#: is a bounded rule rather than a guess. Beyond the window the site is
#: reported as a candidate the scanner could not attribute — never guessed at,
#: which is what `tenancy.enumeration-partial` is for.
ATTRIBUTION_WINDOW = 4

#: Directory names never walked. A checker that reads a dependency tree is a
#: checker whose answer depends on whether `node_modules` is installed, and
#: core's rule is that a check which could not run is not a pass.
#:
#: `__pycache__` is here for the same reason and a sharper one: a `.pyc` is
#: not in `TEXT_SUFFIXES`, so a walked one is reported as "a file type this
#: checker does not read" — and the bytecode carries the source's string
#: literals, tenancy key included. Measured on muse: 9 of the 24 sites in its
#: honest-zero finding were `.pyc` files, so the checker's answer depended on
#: whether the test suite had been run in the tree. A checker whose verdict
#: depends on a generated artifact is the `node_modules` case one language
#: over. The fleet's other languages generate nothing in-tree that carries the
#: key as text: `_build` (Elixir), `target` (Rust), `node_modules`/`dist`/
#: `.next` (TypeScript), `vendor` (Ruby) are already here, and `.ruff_cache`
#: was measured to hold no source text.
SKIPPED_DIRECTORIES = frozenset({
    ".git", ".venv", "node_modules", "vendor", "target", "deps", "_build",
    "dist", "build", ".next", ".tox", ".mypy_cache", ".pytest_cache", "coverage",
    "__pycache__",
})

#: File suffixes read by the scanner. Everything else in a declared source is
#: walked past and reported only if it carries a tenancy key, which is how a
#: Go or Elixir service gets `tenancy.enumeration-partial` instead of a
#: confident zero.
TEXT_SUFFIXES = frozenset({".sql", ".go", ".ex", ".exs", ".rb", ".py", ".ts", ".tsx",
                            ".rs", ".java", ".kt", ".php", ".cs", ".swift", ".js", ".mjs"})

_SQL_COMMENT = re.compile(r"--[^\n]*")

#: Line comments, per file type. Only used to decide whether a line *carries*
#: the tenancy key, so a comment that talks about `account_id` is not an
#: account-scoped statement. Stripping them for that purpose and nothing else is
#: deliberate: a `#` inside a string literal would hide a real site, which is why
#: the fixture's comments are written to avoid the token rather than relying on
#: this being cleverer than it is.
_HASH_COMMENT = re.compile(r"#.*$")
_SLASH_COMMENT = re.compile(r"//.*$")

#: A line that DEFINES the shape rather than reaching a row. `create table
#: assets ( … account_id uuid not null … )` names the tenancy key on the line
#: that declares the column, and skipping to the closing paren is what keeps a
#: schema from being reported as an enumeration of itself.
#:
#: `create function` joined them for the same reason and a worse one: a
#: SECURITY DEFINER helper reads rows, and its predicate line carries the tenancy
#: key, so leaving it in would report the identity function as an undeclared
#: account-scoped statement in every service that adopted this format.
#:
#: The `foreign table` / `materialized view` / `unlogged table` prefixes are here
#: for the same reason: `create foreign table assets (` names `account_id` on the
#: column line three lines down, and a scanner that does not know that is DDL
#: would report a column declaration as an unclassified account-scoped statement.
_DDL = re.compile(
    r"\b(create\s+(?:(?:foreign|materialized|unlogged|temporary|temp)\s+)?table"
    r"|alter\s+table|create\s+(unique\s+)?index|create\s+(materialized\s+)?view"
    r"|create\s+(or\s+replace\s+)?function)\b",
    re.IGNORECASE,
)

#: A `create policy` statement, which the entry-point scanner must NOT attribute.
#:
#: This is the "one statement, one owner" rule, and it is a rule rather than an
#: optimisation: `create policy … on assets for select … using (account_id = …)`
#: carries the tenancy key, so the entry-point scanner would see it, fail to find
#: a `select … from` on it, and report it through `tenancy.enumeration-partial` —
#: which would make every RLS-aware service permanently warning-shaped and, worse,
#: count the same statement in two checkers with two vocabularies. The RLS
#: scanner owns it, and `harness/tenancy_check.py`'s own self-test proves the
#: ownership from both sides.
_POLICY_STATEMENT = re.compile(r"\bcreate\s+policy\b", re.IGNORECASE)

#: Relations the DDL scanner reads, and the kinds it refuses. `foreign table` and
#: `materialized view` are here because `tenancy.rls-unprotectable` is about them:
#: row-level security cannot constrain either, so a policy on one is a comment.
_CREATE_RELATION = re.compile(
    r"^create\s+(?P<kind>foreign\s+table|unlogged\s+table|temporary\s+table|temp\s+table"
    r"|materialized\s+view|view|table)\s+(?:if\s+not\s+exists\s+)?(?P<name>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

#: `alter table … {force|enable|disable} row level security`. `force` and `enable`
#: are SEPARATE reloptions bits in Postgres and neither implies the other, which
#: is the mechanical reason `tenancy.rls-owner-bypass` can fire while
#: `tenancy.rls-not-enabled` does not, and why removing one line from a migration
#: moves exactly one finding.
_ALTER_RLS = re.compile(
    r"^alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?P<name>[a-z_][a-z0-9_]*)"
    r"\s+(?P<bit>force|enable|disable)\s+row\s+level\s+security",
    re.IGNORECASE,
)

_ALTER_OWNER = re.compile(
    r"^alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?P<name>[a-z_][a-z0-9_]*)"
    r"\s+owner\s+to\s+(?P<role>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

_CREATE_POLICY = re.compile(
    r"^create\s+policy\s+(?P<name>[a-z_][a-z0-9_]*)\s+on\s+(?P<table>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

#: kit's TWO entry points into row-level security:
#: `select cafaye.protect_table('<table>')` and
#: `select cafaye.protect_credential_table('<table>', '<digest_column>')`.
#:
#: The table name must be a STRING LITERAL. That is the whole boundary of this
#: recognition and it is deliberate in both directions:
#:
#:   * a literal is a fact about the migrations. The scanner is reading the same
#:     text Postgres would run, and a call whose argument is a variable or a
#:     `format(...)` says nothing about which tables it protects — resolving one
#:     would be a guess, and `harness/tenancy_findings.json` says by name that a
#:     guess is not one of this file's products.
#:   * a call it declines to resolve is the SAFE direction. Nothing is claimed,
#:     so the declaration's `<table>_cafaye_<command>` names resolve against
#:     nothing and `tenancy.rls-policy-absent` fires. A scanner that had guessed
#:     would have gone the other way, which is the way this packet's finding was
#:     facing before it was fixed.
#:
#: The schema qualifier is optional because a service may put the substrate in
#: another schema; the function NAME is not, because `protect_table` alone is a
#: name any service could have given something else.
#:
#: WHICH FUNCTION IT IS comes from the NAME and never from the argument list,
#: which is the one subtlety in this pattern. `protect_table('t', 'role')` and
#: `protect_credential_table('t', 'digest')` have the same shape — one string,
#: a comma, another string — and the second argument means a LOGIN ROLE in the
#: first and a DIGEST COLUMN in the second. Reading the second argument to
#: decide which function it is would give `asset_variants` a resolve policy
#: qualified by a string that is a role name, on the substrate fixture the
#: previous packet committed, and `tenancy.rls-undeclared` would fire about a
#: policy the template never wrote. So the function name is matched, the
#: credential spelling is captured as a group, and the second argument is read
#: only when the group matched.
_PROTECT_TABLE = re.compile(
    r"^select\s+(?:cafaye\.)?protect_(?:(?P<credential>credential_)?table)\s*\(\s*"
    r"'(?P<table>[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)'"
    r"(?:\s*,\s*'(?P<digest>[a-z_][a-z0-9_]*)')?",
    re.IGNORECASE,
)
_POLICY_COMMAND = re.compile(r"\bfor\s+(?P<command>select|insert|update|delete|all)\b", re.IGNORECASE)
_POLICY_ROLES = re.compile(r"\bto\s+(?P<roles>[a-z_][a-z0-9_]*(?:\s*,\s*[a-z_][a-z0-9_]*)*)\s*$",
                           re.IGNORECASE)
_POLICY_CLAUSE = re.compile(r"\b(using|with\s+check)\s*\(", re.IGNORECASE)

_ROLE_STATEMENT = re.compile(r"^(?:create|alter)\s+role\s+(?P<role>[a-z_][a-z0-9_]*)", re.IGNORECASE)
#: The role attributes that skip every policy on every table. `superuser` is here
#: rather than left implicit because a superuser is a bypass with no attribute
#: spelled on the line that says so.
_ROLE_BYPASS = re.compile(r"\b(bypassrls|superuser)\b", re.IGNORECASE)

_CREATE_FUNCTION = re.compile(
    r"^create\s+(?:or\s+replace\s+)?function\s+(?P<name>[a-z_][a-z0-9_.]*)", re.IGNORECASE
)
_SECURITY_DEFINER = re.compile(r"\bsecurity\s+definer\b", re.IGNORECASE)
_SET_SEARCH_PATH = re.compile(r"\bset\s+search_path\b", re.IGNORECASE)
_SECURITY_INVOKER = re.compile(r"\bsecurity_invoker\b", re.IGNORECASE)

#: How far a `create policy` / `create function` statement may run before this
#: checker says it could not read it. A bound rather than a search for the
#: terminating semicolon, because an unterminated statement would otherwise make
#: the scanner swallow the rest of the file and report a clean answer over
#: everything it skipped.
STATEMENT_LINE_BOUND = 64

#: An insert is not an entry point, and the schema says why in the same words:
#: it creates a row in the account the caller is already acting as, so it cannot
#: read or write another account's row. `Assets.insert(id: …, account_id: …)`
#: in a test factory is the same statement, and it is the most common line in
#: this fleet that carries the key.
_INSERT = re.compile(r"\binsert\b", re.IGNORECASE)

_SQL_KEYWORDS = {
    "select": r"select\s+.*?\s+from\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
    "update": r"update\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+set\b",
    "delete": r"delete\s+from\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
}


# --------------------------------------------------------------------------
# the format, re-implemented from schemas/tenant-isolation.schema.json
# --------------------------------------------------------------------------


def validate(declaration: Any) -> list[str]:
    """The well-formedness half, without `jsonschema`.

    Every message names the path and the constraint, because the point of this
    half is to tell a reader what to change. It mirrors the schema file for
    the same reason `gate_check.validate` does: a service's CI must be able to
    run this checker with nothing installed.
    """
    problems: list[str] = []

    def complain(path: str, constraint: str) -> None:
        problems.append(f"{path or '<root>'}: {constraint}")

    if not isinstance(declaration, dict):
        return ["<root>: type object"]

    for key in sorted(declaration):
        if key not in TOP_LEVEL_KEYS:
            complain("", f"additionalProperties: {key!r} is not a key of a tenancy declaration")
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in declaration:
            complain(key, "required")
    if declaration.get("version") != 1:
        complain("version", "const 1")
    service = declaration.get("service")
    if not isinstance(service, str) or not NAME_PATTERN.fullmatch(service) or len(service) > 40:
        complain("service", "pattern ^[a-z][a-z0-9-]*$, maxLength 40")
    account_scoped = declaration.get("accountScoped")
    if not isinstance(account_scoped, bool):
        complain("accountScoped", "type boolean")
    if "scope" in declaration:
        problems.extend(_validate_scope(declaration["scope"]))
    if "rls" in declaration:
        problems.extend(_validate_rls(declaration["rls"]))
    if "entryPoints" in declaration:
        problems.extend(_validate_entry_points(declaration["entryPoints"], account_scoped))
    return problems


def _validate_paths(items: Any, where: str) -> list[str]:
    """The `sources` constraint, said once for both lists that carry it.

    Two lists rather than one, for the reason `rls.sources`'s own description
    gives: the statement scan and the DDL scan read different trees. Sharing the
    validation is not sharing the field — `scope.sources` and `rls.sources` are
    declared separately, and a service names two paths in a Go repository because
    that is where its statements and its migrations are.
    """
    problems: list[str] = []
    if not isinstance(items, list):
        return [f"{where}: type array"]
    if not 1 <= len(items) <= 32:
        problems.append(f"{where}: minItems 1, maxItems 32")
    if len(set(map(str, items))) != len(items):
        problems.append(f"{where}: uniqueItems — the same path twice is one path")
    for index, item in enumerate(items):
        place = f"{where}/{index}"
        if not isinstance(item, str):
            problems.append(f"{place}: type string")
            continue
        if not 1 <= len(item) <= 200:
            problems.append(f"{place}: minLength 1, maxLength 200")
        elif not SCOPE_PATH_PATTERN.fullmatch(item):
            problems.append(f"{place}: pattern a repository-relative path")
        elif ".." in item.split("/"):
            problems.append(f"{place}: not — a path may not leave the repository")
    return problems


def _validate_rls(rls: Any) -> list[str]:
    """The `rls` block, re-implemented from the schema.

    The conditional is the part worth reading twice. `databaseEnforced: false`
    with a populated `tables` is refused for the same reason `accountScoped:
    false` with a populated `entryPoints` is: a service that says its database
    does nothing and then lists the tables it does something to is the same
    omission facing the other way. And `identity` is required only on the `true`
    arm, because "the thing the policies are scoped by" is a question only a
    service with policies has to answer.
    """
    problems: list[str] = []
    if not isinstance(rls, dict):
        return ["rls: type object"]
    allowed = {"databaseEnforced", "identity", "sources", "tables", "publicRead"}
    for key in sorted(rls):
        if key not in allowed:
            problems.append(f"rls: additionalProperties {key!r}")
    for key in ("databaseEnforced", "sources", "tables"):
        if key not in rls:
            problems.append(f"rls/{key}: required")
    enforced = rls.get("databaseEnforced")
    if not isinstance(enforced, bool):
        problems.append("rls/databaseEnforced: type boolean")
    identity = rls.get("identity")
    if identity is not None:
        if not isinstance(identity, str) or not 6 <= len(identity) <= 80 \
                or not IDENTITY_PATTERN.fullmatch(identity):
            problems.append(
                "rls/identity: pattern a schema-qualified zero-argument call, "
                "app.current_account(), maxLength 80"
            )
    elif enforced is True:
        problems.append("rls/identity: required when databaseEnforced is true")
    if "sources" in rls:
        problems.extend(_validate_paths(rls["sources"], "rls/sources"))
    tables = rls.get("tables")
    if tables is not None:
        if not isinstance(tables, list):
            problems.append("rls/tables: type array")
        elif enforced is True and not tables:
            problems.append(
                "rls/tables: minItems 1 — the service says the database enforces the "
                "boundary and names no table it is enforced on"
            )
        elif enforced is False and tables:
            problems.append(
                f"rls/tables: maxItems 0 — the service says the database enforces nothing "
                f"and lists {len(tables)} table(s)"
            )
        elif len(tables) > 256:
            problems.append("rls/tables: maxItems 256")
        else:
            names: set[str] = set()
            for index, item in enumerate(tables):
                where = f"rls/tables/{index}"
                if not isinstance(item, dict):
                    problems.append(f"{where}: type object")
                    continue
                for key in sorted(item):
                    if key not in {"table", "forced", "policies"}:
                        problems.append(f"{where}: additionalProperties {key!r}")
                for key in ("table", "forced", "policies"):
                    if key not in item:
                        problems.append(f"{where}/{key}: required")
                name = item.get("table")
                if name is not None:
                    if not isinstance(name, str) or not 2 <= len(name) <= 63 \
                            or not SUBJECT_PATTERN.fullmatch(name):
                        problems.append(
                            f"{where}/table: pattern ^[a-z][a-z0-9_]*$, minLength 2, maxLength 63"
                        )
                    elif name in names:
                        problems.append(f"{where}/table: unique — {name!r} appears twice")
                    else:
                        names.add(name)
                if "forced" in item and item["forced"] is not True:
                    problems.append(
                        f"{where}/forced: const true — {item['forced']!r} is the bug this block "
                        "exists to prevent, and a format that can describe it is a format that "
                        "will contain one"
                    )
                problems.extend(_validate_rls_policies(item.get("policies"), where))
    if "publicRead" in rls:
        problems.extend(_validate_public_read(rls["publicRead"]))
    return problems


def _validate_public_read(items: Any) -> list[str]:
    """The `rls.publicRead` constraint, re-implemented from the schema.

    A list of claims, each naming a table, the policy that grants the public
    read and the role it grants it to. The shape is the evidence and it is why
    this is a list of named things rather than a boolean: the checker compares
    each claim against the DDL, so a claim the migrations do not back is
    `tenancy.rls-public-read-absent` and a public read nobody declared is still
    `tenancy.rls-permissive`. `role` refuses `public` for the reason
    `rlsPolicy.roles` does — a policy that names no role applies to PUBLIC,
    and a public read granted to every role is the absence of a boundary.
    """
    problems: list[str] = []
    if not isinstance(items, list):
        return ["rls/publicRead: type array"]
    if len(items) > 256:
        problems.append("rls/publicRead: maxItems 256")
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        where = f"rls/publicRead/{index}"
        if not isinstance(item, dict):
            problems.append(f"{where}: type object")
            continue
        for key in sorted(item):
            if key not in {"table", "policy", "role"}:
                problems.append(f"{where}: additionalProperties {key!r}")
        for key in ("table", "policy", "role"):
            if key not in item:
                problems.append(f"{where}/{key}: required")
        table = item.get("table")
        if table is not None and (
            not isinstance(table, str) or not 2 <= len(table) <= 63
            or not SUBJECT_PATTERN.fullmatch(table)
        ):
            problems.append(
                f"{where}/table: pattern ^[a-z][a-z0-9_]*$, minLength 2, maxLength 63"
            )
        policy = item.get("policy")
        if policy is not None and (
            not isinstance(policy, str) or not 2 <= len(policy) <= 63
            or not SUBJECT_PATTERN.fullmatch(policy)
        ):
            problems.append(
                f"{where}/policy: pattern ^[a-z][a-z0-9_]*$, minLength 2, maxLength 63"
            )
        role = item.get("role")
        if role is not None:
            if not isinstance(role, str) or not 1 <= len(role) <= 63 \
                    or not SUBJECT_PATTERN.fullmatch(role):
                problems.append(f"{where}/role: pattern a role name, maxLength 63")
            elif role.lower() == "public":
                problems.append(
                    f"{where}/role: not const public — a policy that names no role applies "
                    "to PUBLIC, and a public read granted to every role is the absence of a "
                    "boundary"
                )
        if isinstance(table, str) and isinstance(policy, str):
            key = (table.lower(), policy.lower())
            if key in seen:
                problems.append(f"{where}: unique — {table!r} / {policy!r} appears twice")
            else:
                seen.add(key)
    return problems


def _validate_rls_policies(policies: Any, where: str) -> list[str]:
    problems: list[str] = []
    if policies is None:
        return problems
    if not isinstance(policies, list):
        return [f"{where}/policies: type array"]
    if not 1 <= len(policies) <= 32:
        problems.append(f"{where}/policies: minItems 1, maxItems 32")
    for index, item in enumerate(policies):
        place = f"{where}/policies/{index}"
        if not isinstance(item, dict):
            problems.append(f"{place}: type object")
            continue
        for key in sorted(item):
            if key not in {"name", "command", "clause", "roles", "constrained"}:
                problems.append(f"{place}: additionalProperties {key!r}")
        for key in ("name", "command", "clause", "roles", "constrained"):
            if key not in item:
                problems.append(f"{place}/{key}: required")
        name = item.get("name")
        if name is not None and (
            not isinstance(name, str) or not 2 <= len(name) <= 63
            or not SUBJECT_PATTERN.fullmatch(name)
        ):
            problems.append(f"{place}/name: pattern ^[a-z][a-z0-9_]*$, minLength 2, maxLength 63")
        command = item.get("command")
        if command is not None:
            if command not in POLICY_COMMANDS:
                problems.append(f"{place}/command: enum {list(POLICY_COMMANDS)}")
            else:
                clause = item.get("clause")
                expected = COMMAND_CLAUSE.get(command)
                if expected is not None and clause is not None and clause != expected:
                    problems.append(
                        f"{place}/clause: const {expected} for command {command} — a `for "
                        f"{command}` policy is denied by {expected}, and the two are not "
                        "interchangeable to the assertion"
                    )
        clause = item.get("clause")
        if clause is not None and clause not in ("using", "with check"):
            problems.append(f"{place}/clause: enum ['using', 'with check']")
        roles = item.get("roles")
        if roles is not None:
            if not isinstance(roles, list):
                problems.append(f"{place}/roles: type array")
            elif not 1 <= len(roles) <= 16:
                problems.append(f"{place}/roles: minItems 1, maxItems 16")
            elif len(set(map(str, roles))) != len(roles):
                problems.append(f"{place}/roles: uniqueItems")
            for position, role in enumerate(roles):
                where_role = f"{place}/roles/{position}"
                if not isinstance(role, str):
                    problems.append(f"{where_role}: type string")
                    continue
                if not 1 <= len(role) <= 63 or not SUBJECT_PATTERN.fullmatch(role):
                    problems.append(f"{where_role}: pattern a role name, maxLength 63")
                elif role.lower() == "public":
                    problems.append(
                        f"{where_role}: not const public — a policy that names no role applies "
                        "to PUBLIC, and a boundary nobody wrote is not a boundary"
                    )
        if "constrained" in item:
            problems.extend(_validate_file_and_line(item["constrained"], f"{place}/constrained"))
    return problems


def _validate_scope(scope: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(scope, dict):
        return ["scope: type object"]
    allowed = {"key", "sources", "nonRowSites"}
    for key in sorted(scope):
        if key not in allowed:
            problems.append(f"scope: additionalProperties {key!r}")
    for key in ("key", "sources"):
        if key not in scope:
            problems.append(f"scope/{key}: required")
    name = scope.get("key")
    if name is not None and (
        not isinstance(name, str)
        or not 3 <= len(name) <= 64
        or not IDENTIFIER_PATTERN.fullmatch(name)
    ):
        problems.append("scope/key: minLength 3, maxLength 64, pattern ^[A-Za-z_][A-Za-z0-9_]*$")
    if "sources" in scope:
        problems.extend(_validate_paths(scope["sources"], "scope/sources"))
    if "nonRowSites" in scope:
        problems.extend(_validate_non_row_sites(scope["nonRowSites"]))
    return problems


def _validate_non_row_sites(items: Any) -> list[str]:
    """The `scope.nonRowSites` constraint, re-implemented from the schema.

    A list of sites the declaration vouches for: the key appears there and is
    not a row scope. The shape is `located` plus a reason, and the reason is
    required because a site named with no reason is the "I cannot see this"
    this field exists to replace — the difference between an omission and a
    claim somebody looked at.
    """
    problems: list[str] = []
    if not isinstance(items, list):
        return ["scope/nonRowSites: type array"]
    if len(items) > 256:
        problems.append("scope/nonRowSites: maxItems 256")
    for index, item in enumerate(items):
        where = f"scope/nonRowSites/{index}"
        if not isinstance(item, dict):
            problems.append(f"{where}: type object")
            continue
        for key in sorted(item):
            if key not in {"file", "line", "reason"}:
                problems.append(f"{where}: additionalProperties {key!r}")
        for key in ("file", "line", "reason"):
            if key not in item:
                problems.append(f"{where}/{key}: required")
        file_name = item.get("file")
        if file_name is not None and (
            not isinstance(file_name, str)
            or not 3 <= len(file_name) <= 200
            or not PATH_PATTERN.fullmatch(file_name)
            or ".." in file_name.split("/")
        ):
            problems.append(f"{where}/file: pattern a repository-relative path, maxLength 200")
        line = item.get("line")
        if line is not None and (
            not isinstance(line, int) or isinstance(line, bool)
            or not 1 <= line <= 1000000
        ):
            problems.append(f"{where}/line: an integer between 1 and 1000000")
        reason = item.get("reason")
        if reason is not None and (
            not isinstance(reason, str) or not 8 <= len(reason) <= 200
        ):
            problems.append(f"{where}/reason: minLength 8, maxLength 200 — why this is not a row scope")
    return problems


def _validate_entry_points(entry_points: Any, account_scoped: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(entry_points, list):
        return ["entryPoints: type array"]
    if len(entry_points) > 512:
        problems.append("entryPoints: maxItems 512")
    if account_scoped is False and entry_points:
        problems.append(
            "entryPoints: maxItems 0 — the declaration says the service has no "
            f"account scoping and names {len(entry_points)} entry point(s)"
        )
    if account_scoped is True and not entry_points:
        problems.append(
            "entryPoints: minItems 1 — the declaration says the service scopes by "
            "account and names no way it does"
        )
    identifiers: set[str] = set()
    for index, item in enumerate(entry_points):
        where = f"entryPoints/{index}"
        if not isinstance(item, dict):
            problems.append(f"{where}: type object")
            continue
        for key in sorted(item):
            if key not in {"id", "operation", "subject", "enforced", "negative"}:
                problems.append(f"{where}: additionalProperties {key!r}")
        for key in ("id", "operation", "subject", "enforced", "negative"):
            if key not in item:
                problems.append(f"{where}/{key}: required")
        identifier = item.get("id")
        if identifier is not None:
            if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier) \
                    or len(identifier) > 60:
                problems.append(f"{where}/id: pattern ^[a-z][a-z0-9-]*$, maxLength 60")
            elif identifier in identifiers:
                problems.append(f"{where}/id: unique — {identifier!r} appears twice")
            else:
                identifiers.add(identifier)
        operation = item.get("operation")
        if operation is not None and operation not in OPERATIONS:
            problems.append(f"{where}/operation: enum {list(OPERATIONS)}")
        subject = item.get("subject")
        if subject is not None and (
            not isinstance(subject, str)
            or not SUBJECT_PATTERN.fullmatch(subject)
            or not 2 <= len(subject) <= 80
        ):
            problems.append(f"{where}/subject: pattern ^[a-z][a-z0-9_]*$, maxLength 80")
        if "enforced" in item:
            problems.extend(_validate_enforced(item["enforced"], f"{where}/enforced"))
        if "negative" in item:
            problems.extend(_validate_negative(item["negative"], f"{where}/negative"))
    return problems


def _validate_enforced(enforced: Any, where: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(enforced, dict):
        return [f"{where}: type object"]
    allowed = {"mechanism", "binds", "file", "line"}
    for key in sorted(enforced):
        if key not in allowed:
            problems.append(f"{where}: additionalProperties {key!r}")
    for key in ("mechanism", "file", "line"):
        if key not in enforced:
            problems.append(f"{where}/{key}: required")
    mechanism = enforced.get("mechanism")
    if mechanism is not None and mechanism not in MECHANISMS:
        problems.append(f"{where}/mechanism: enum {list(MECHANISMS)}")
    binds = enforced.get("binds")
    if binds is not None and (
        not isinstance(binds, str) or not 2 <= len(binds) <= 60
        or not IDENTIFIER_PATTERN.fullmatch(binds)
    ):
        problems.append(f"{where}/binds: pattern ^[A-Za-z_][A-Za-z0-9_]*$, maxLength 60")
    # The conditional, both arms. A bind-parameter with no parameter named is a
    # query scoped on paper; a parameter on any other mechanism is a field
    # nothing reads, which is how an exception gets in.
    if mechanism == "bind-parameter" and binds is None:
        problems.append(f"{where}/binds: required when mechanism is bind-parameter")
    if mechanism is not None and mechanism != "bind-parameter" and binds is not None:
        problems.append(
            f"{where}: not — binds belongs to bind-parameter, not to {mechanism}"
        )
    problems.extend(_validate_file_and_line(enforced, where))
    return problems


def _validate_negative(negative: Any, where: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(negative, dict):
        return [f"{where}: type object"]
    allowed = {"asserts", "cases"}
    for key in sorted(negative):
        if key not in allowed:
            problems.append(f"{where}: additionalProperties {key!r}")
    for key in ("asserts", "cases"):
        if key not in negative:
            problems.append(f"{where}/{key}: required")
    asserts = negative.get("asserts")
    if asserts is not None and asserts != "absent":
        problems.append(
            f"{where}/asserts: const absent — {asserts!r} tells an attacker the id exists"
        )
    cases = negative.get("cases")
    if cases is None:
        return problems
    if not isinstance(cases, list):
        return problems + [f"{where}/cases: type array"]
    if len(cases) != 3:
        problems.append(
            f"{where}/cases: exactly three arms, {len(cases)} given. Two negative arms and a "
            "positive control: a suite with one assertion satisfies a service that returns "
            "nothing to anybody"
        )
    seen: set[str] = set()
    for index, item in enumerate(cases):
        place = f"{where}/cases/{index}"
        if not isinstance(item, dict):
            problems.append(f"{place}: type object")
            continue
        for key in sorted(item):
            if key not in {"id", "asserts", "expects", "file", "line"}:
                problems.append(f"{place}: additionalProperties {key!r}")
        for key in ("id", "asserts", "expects", "file", "line"):
            if key not in item:
                problems.append(f"{place}/{key}: required")
        arm = item.get("id")
        if arm is not None:
            if arm not in ARM_POLARITY:
                problems.append(f"{place}/id: enum {list(DENIAL_ARMS)}")
            elif arm in seen:
                problems.append(f"{place}/id: unique — {arm!r} appears twice")
            else:
                seen.add(arm)
        polarity = ARM_POLARITY.get(arm) if isinstance(arm, str) else None
        arm_asserts = item.get("asserts")
        if polarity is not None and arm_asserts is not None and arm_asserts != polarity:
            problems.append(
                f"{place}/asserts: const {polarity} for the {arm} arm — got {arm_asserts!r}"
            )
        expects = item.get("expects")
        if expects is not None:
            if not isinstance(expects, str) or not 2 <= len(expects) <= 40 \
                    or not EXPECT_PATTERN.fullmatch(expects):
                problems.append(
                    f"{place}/expects: pattern an identifier or the two characters [], "
                    "maxLength 40"
                )
            elif arm == POSITIVE_ARM and expects in ABSENCE_TOKENS:
                problems.append(
                    f"{place}/expects: {expects!r} is this language's spelling of nothing, and "
                    "the third arm has to show the row. A table with no policy at all is "
                    "exactly what the other two arms cannot tell apart from a correct one"
                )
            elif arm == POSITIVE_ARM and expects == "[]":
                problems.append(
                    f"{place}/expects: the positive control cannot be an empty list"
                )
        problems.extend(_validate_file_and_line(item, place))
    missing = [arm for arm in DENIAL_ARMS if arm not in seen]
    if missing:
        problems.append(f"{where}/cases: missing the {missing} arm(s)")
    return problems


def _validate_file_and_line(block: Any, where: str) -> list[str]:
    problems: list[str] = []
    path = block.get("file")
    if path is not None:
        if not isinstance(path, str) or not 3 <= len(path) <= 200 or not PATH_PATTERN.fullmatch(path):
            problems.append(f"{where}/file: pattern a repository-relative path with a directory in it")
        elif ".." in path.split("/"):
            problems.append(f"{where}/file: not — a path may not leave the repository")
    line = block.get("line")
    if line is not None and (
        not isinstance(line, int) or isinstance(line, bool) or not 1 <= line <= 1_000_000
    ):
        problems.append(f"{where}/line: minimum 1, maximum 1000000")
    return problems


# --------------------------------------------------------------------------
# the shape, and the finding it produces
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One check's answer, in the shape gate_check uses and `caf` will read.

    `remediate` is not decoration: MD13's most transferable finding about
    yamine was that every check message carries the exact remediation, because a
    check that says only "not ok" makes the reader go and look.
    """

    id: str
    severity: str
    message: str
    remediate: str

    def render(self) -> str:
        return f"{self.severity.upper()} {self.id}: {self.message}\n    fix: {self.remediate}"


@dataclass
class Report:
    """Everything one run produced. `exit_code` is the only thing to branch on."""

    repo: Path
    findings: list[Finding]
    could_not_run: str | None = None

    def of(self, severity: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == severity]

    @property
    def exit_code(self) -> int:
        if self.could_not_run is not None:
            return EXIT_COULD_NOT_RUN
        if self.of("fail"):
            return EXIT_FAIL
        return EXIT_OK

    def render(self) -> str:
        lines = [finding.render() for finding in self.findings]
        lines.append("")
        if self.could_not_run is not None:
            lines.append(f"COULD NOT RUN {self.repo}: {self.could_not_run}")
            return "\n".join(lines)
        failed = len(self.of("fail"))
        warned = len(self.of("warn"))
        verdict = "FAIL" if failed else "OK"
        # Warnings counted separately, every time. A report that says "0
        # findings" when two of them were warnings is a report that lies.
        lines.append(
            f"{verdict} {self.repo}: {failed} failure(s), {warned} warning(s) — "
            + (
                "warnings do not move the exit code"
                if warned
                else "no warnings, so nothing was left unproven silently"
            )
        )
        return "\n".join(lines)


def finding(identifier: str, message: str) -> Finding:
    """Build a finding from the inventory, so an unknown id cannot be invented."""
    try:
        severity, _claim, remediate = FINDINGS[identifier]
    except KeyError:  # pragma: no cover - a test asserts the inventory is complete
        raise SystemExit(
            f"tenancy_check: {identifier} is not in FINDINGS. A finding the inventory "
            "does not describe is a finding nobody was told about."
        )
    return Finding(id=identifier, severity=severity, message=message, remediate=remediate)


# --------------------------------------------------------------------------
# reading the declaration, and the source it names
# --------------------------------------------------------------------------


def declaration_path(repo: Path) -> Path:
    return repo / DECLARATION


def read_declaration(repo: Path) -> tuple[Any, Finding | None]:
    path = declaration_path(repo)
    if not path.is_file():
        return None, finding("tenancy.declaration-missing", f"{DECLARATION} is not in {repo}")
    try:
        return read_yaml(path.read_text(encoding="utf-8"), path), None
    except Refusal as refusal:
        return None, finding(
            "tenancy.declaration-unreadable",
            f"{DECLARATION} could not be read: {refusal.detail} (at {refusal.path})",
        )
    except OSError as error:
        return None, finding("tenancy.declaration-unreadable", f"{DECLARATION} is unreadable: {error}")


def source_lines(path: Path) -> list[str]:
    """A file's lines, or an empty list if it cannot be read.

    A file that cannot be decoded as UTF-8 is not an error: it is a binary, and
    a binary in a declared source is something the checker walks past rather
    than a run that fails.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _statement_length(lines: list[str], index: int) -> int:
    """How many lines after `index` the statement opening there runs for.

    A DDL statement is terminated by a semicolon at the end of a line, which is a
    fact about how migrations are written rather than about SQL proper — so it is
    bounded (`STATEMENT_LINE_BOUND`) rather than trusted. An unterminated
    statement that ran to the end of the file would make every scanner that skips
    statements skip the rest of the tree and then report a clean answer over
    everything it skipped, which is the "darkroom has no routes" defect one level
    down. One line is returned when nothing terminates it, so the loop always
    makes progress.
    """
    if lines[index].rstrip().endswith(";"):
        return 1
    for offset in range(1, STATEMENT_LINE_BOUND + 1):
        ahead = index + offset
        if ahead >= len(lines):
            return 1
        if lines[ahead].rstrip().endswith(";"):
            return offset + 1
    return STATEMENT_LINE_BOUND


def declared_files(repo: Path, sources: Any) -> tuple[list[Path], list[str]]:
    """The files in the declared sources, and the ones that are not there."""
    files: list[Path] = []
    missing: list[str] = []
    for item in sources or []:
        if not isinstance(item, str):
            continue
        root = repo / item
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            for found in sorted(root.rglob("*")):
                if not found.is_file():
                    continue
                if SKIPPED_DIRECTORIES & set(found.relative_to(root).parts):
                    continue
                files.append(found)
        else:
            missing.append(item)
    return files, missing


# --------------------------------------------------------------------------
# the scanner — SQL, and nothing it cannot see
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    """One account-scoped statement the scanner recognised.

    `file`, `operation` and `subject` are the identity closure is checked on,
    and the line is deliberately NOT part of it: a refactor that moves a query
    down three lines must not turn ten declarations red, while a refactor that
    drops `and account_id = $2` must turn one red.
    """

    file: str
    line: int
    operation: str
    subject: str

    def key(self) -> tuple[str, str, str]:
        return (self.file, self.operation, self.subject)


def key_spelling(key: str) -> tuple[str, ...]:
    """The fleet spellings of a tenancy key, anchored at a word boundary.

    The boundary is what makes `account_id` not match inside `sub_account_id`. It
    is also why a declaration saying `expects: unchanged` cannot be satisfied by
    a line containing `assert_unchanged`: a token search with no boundary lets a
    declaration be met by a substring of a different identifier, which is the
    same false green as a proof pattern that matches a colour escape.
    """
    return tuple(
        re.compile(rf"(?<![A-Za-z0-9_]){spelling}(?![A-Za-z0-9_])")
        for spelling in (item.format(key=key) for item in KEY_SPELLINGS)
    )


def carries_key(line: str, matchers: tuple[re.Pattern[str], ...]) -> bool:
    return any(matcher.search(line) for matcher in matchers)


def sql_operation(line: str) -> tuple[str, str] | None:
    """`(operation, subject)` for a SQL statement opening on this line, or None.

    `select * from assets` and `delete from assets` name their table directly;
    a `select a.id from assets a where …` names it after the alias and is
    attributed to the nearest table this line or the ones above it names, which
    is the bounded rule `ATTRIBUTION_WINDOW` describes. A line that names two
    different tables is a join, and a join's boundary is the one this checker
    cannot see — so it is reported as unclassified rather than attributed to
    whichever table happened to be written first.
    """
    stripped = _SQL_COMMENT.sub("", line).strip()
    if not stripped:
        return None
    tables: list[str] = []
    for operation, pattern in _SQL_KEYWORDS.items():
        for match in re.finditer(pattern, stripped, re.IGNORECASE):
            tables.append(match.group(1).split(".")[-1].lower())
    if not tables:
        return None
    distinct = set(tables)
    if len(distinct) != 1:
        return None
    subject = tables[0]
    for operation in ("select", "update", "delete"):
        if re.search(_SQL_KEYWORDS[operation], stripped, re.IGNORECASE):
            return operation, subject
    return None


def strip_comment(line: str, suffix: str) -> str:
    """`line` without its comment, for deciding whether it CARRIES the key.

    Never used to decide whether a statement is scoped — only whether the key is
    mentioned at all — which is why the imprecision of "a `#` anywhere ends the
    line" is acceptable here and would not be one line up.
    """
    if suffix == ".sql":
        return _SQL_COMMENT.sub("", line)
    if suffix in {".rb", ".py", ".ex", ".exs", ".php"}:
        return _HASH_COMMENT.sub("", line)
    if suffix in {".go", ".ts", ".tsx", ".rs", ".java", ".kt", ".cs", ".js", ".mjs"}:
        return _SLASH_COMMENT.sub("", line)
    return line


def scan_file(repo: Path, path: Path, matchers: tuple[re.Pattern[str], ...]) -> tuple[
    list[Site], list[tuple[str, str]]
]:
    """Every account-scoped statement in one file, and what could not be attributed.

    The second list is the honest residue: a line carrying the tenancy key that
    this checker could not tie to a statement inside `ATTRIBUTION_WINDOW`. It is
    reported by name in `tenancy.enumeration-partial` and never silently
    counted as covered — the "darkroom has no routes" defect in its smallest
    form is a site this list would have hidden.
    """
    relative = path.relative_to(repo).as_posix()
    lines = source_lines(path)
    sites: list[Site] = []
    unattributed: list[tuple[str, str]] = []
    ddl_depth = 0
    policy_depth = 0
    for index, raw in enumerate(lines):
        line = index + 1
        if policy_depth > 0:
            policy_depth -= 1
            continue
        if ddl_depth > 0:
            ddl_depth += raw.count("(") - raw.count(")")
            continue
        if _POLICY_STATEMENT.search(raw):
            # The RLS scanner owns this statement — see `_POLICY_STATEMENT`.
            policy_depth = _statement_length(lines, index)
            continue
        if _DDL.search(raw):
            ddl_depth = max(raw.count("(") - raw.count(")"), 0)
            continue
        stripped = strip_comment(raw, path.suffix)
        if not carries_key(stripped, matchers) or _INSERT.search(stripped):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            unattributed.append((f"{relative}:{line}", "a file type this checker does not read"))
            continue
        resolved = sql_operation(stripped)
        if resolved is None:
            # The key is not on the statement's own line. Look above, within the
            # window, for the statement it belongs to.
            for back in range(1, ATTRIBUTION_WINDOW + 1):
                above = index - back
                if above < 0:
                    break
                resolved = sql_operation(strip_comment(lines[above], path.suffix))
                if resolved is not None:
                    break
        if resolved is None:
            unattributed.append((
                f"{relative}:{line}",
                f"no statement within {ATTRIBUTION_WINDOW} lines",
            ))
            continue
        operation, subject = resolved
        sites.append(Site(file=relative, line=line, operation=operation, subject=subject))
    return sites, unattributed


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------


def check_locations(repo: Path, entry_points: list) -> list[Finding]:
    """Every named file exists and every named line is really there.

    A declaration that points at nothing is worse than no declaration, because
    it reads as a boundary somebody looked at. This is the cheapest check in
    the file and the one that most often fails the day a service renames a
    directory.
    """
    found: list[Finding] = []
    for index, item in enumerate(entry_points):
        if not isinstance(item, dict):
            continue
        label = _label(item, index)
        blocks: list[tuple[str, Any]] = [("enforced", item.get("enforced"))]
        negative = item.get("negative")
        if isinstance(negative, dict) and isinstance(negative.get("cases"), list):
            blocks += [
                (f"negative.cases[{case.get('id') or position}]", case)
                for position, case in enumerate(negative["cases"])
                if isinstance(case, dict)
            ]
        for block_name, block in blocks:
            if not isinstance(block, dict):
                continue
            relative = block.get("file")
            line = block.get("line")
            if not isinstance(relative, str) or not isinstance(line, int) or isinstance(line, bool):
                continue
            target = repo / relative
            if not target.is_file():
                found.append(finding(
                    "tenancy.location-missing",
                    f"{label}.{block_name}.file names {relative!r}, which is not a file in "
                    f"this repository",
                ))
                continue
            total = len(source_lines(target))
            if line < 1 or line > total:
                found.append(finding(
                    "tenancy.line-missing",
                    f"{label}.{block_name}.line is {line} and {relative} has {total} line(s)",
                ))
    return found


def check_enforcement(repo: Path, entry_points: list, matchers: tuple[re.Pattern[str], ...]) -> list[Finding]:
    """The declared line still carries the tenancy key, or the bind it names.

    One fact per mechanism, which is why they are ordered rather than stacked. A
    `bind-parameter` entry point's line carries the key *through* the bind — the
    account is what is being passed — so the bind token is the whole check, and
    reporting `tenancy.scope-lost` as well would say the same thing twice. The
    other three mechanisms are enforced by a predicate on the line, and the key
    is the whole check.
    """
    found: list[Finding] = []
    for index, item in enumerate(entry_points):
        if not isinstance(item, dict):
            continue
        label = _label(item, index)
        enforced = item.get("enforced")
        if not isinstance(enforced, dict):
            continue
        relative = enforced.get("file")
        line = enforced.get("line")
        mechanism = enforced.get("mechanism")
        if not isinstance(relative, str) or not isinstance(line, int) or isinstance(line, bool):
            continue
        target = repo / relative
        if not target.is_file():
            continue  # check_locations already reported it, with the same line
        lines = source_lines(target)
        if not 1 <= line <= len(lines):
            continue
        text = strip_comment(lines[line - 1], target.suffix)
        if mechanism == "bind-parameter":
            binds = enforced.get("binds")
            if isinstance(binds, str) and not re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(binds)}(?![A-Za-z0-9_])", text
            ):
                found.append(finding(
                    "tenancy.bind-missing",
                    f"{label} declares mechanism bind-parameter with binds={binds!r} at "
                    f"{relative}:{line}, and that line does not pass it — {text.strip()!r}. A query "
                    "that still says `account_id = $2` while nothing passes $2 is scoped on paper "
                    "and unscoped in fact, which is the defect a predicate check cannot see",
                ))
            continue
        if not carries_key(text, matchers):
            found.append(finding(
                "tenancy.scope-lost",
                f"{label} declares {mechanism} at {relative}:{line} and that line does not carry "
                f"the tenancy key — {text.strip()!r}. Either the scoping moved to another line or "
                "it was dropped, and the two want different fixes",
            ))
    return found


def check_closure(repo: Path, entry_points: list, sites: list[Site],
                  unclassified: list[tuple[str, str]]) -> list[Finding]:
    """The enumeration is closed in BOTH directions — where it can be.

    A site the scanner found that nobody declared means the declaration is a
    summary. A declaration whose site the scanner can no longer find means the
    scoping was dropped, or the code was deleted, and both are the same event
    from the boundary's point of view. Either direction alone is a summary.

    A declared entry point the scanner cannot classify is NOT counted as either
    direction. It goes into `tenancy.enumeration-partial` with its name, which
    is the difference between "this service has no account scoping" and "this
    checker cannot read this service" — the difference between an answer and a
    shrug that reads like one.
    """
    found: list[Finding] = []
    scannable: list[tuple[str, tuple[str, str, str]]] = []
    for index, item in enumerate(entry_points):
        if not isinstance(item, dict):
            continue
        enforced = item.get("enforced")
        if not isinstance(enforced, dict):
            continue
        relative = enforced.get("file")
        operation = item.get("operation")
        subject = item.get("subject")
        if not all(isinstance(value, str) for value in (relative, operation, subject)):
            continue
        if operation not in SCANNER_OPERATIONS:
            unclassified.append((
                _label(item, index),
                f"{relative}:{enforced.get('line')} (operation {operation} is not a statement "
                "this checker's scanner reads)",
            ))
            continue
        if not _is_scannable(repo / relative, enforced.get("line"), operation):
            unclassified.append((
                _label(item, index),
                f"{relative}:{enforced.get('line')} (the scanner could not read this line as "
                f"a {operation})",
            ))
            continue
        scannable.append((_label(item, index), (relative, operation, subject)))

    declared = {key: label for label, key in scannable}
    found_keys = {site.key() for site in sites}
    for key, label in sorted(declared.items()):
        if key not in found_keys:
            found.append(finding(
                "tenancy.entry-absent",
                f"{label} declares {key[1]} on {key[2]} at {key[0]}: the tenancy key is no "
                "longer in that statement. The scoping was dropped or the code is gone, and "
                "both leave the boundary where it was",
            ))
    declared_keys = set(declared)
    for site in sorted(sites, key=lambda item: item.key()):
        if site.key() not in declared_keys:
            found.append(finding(
                "tenancy.undeclared-entry",
                f"{site.operation} on {site.subject} at {site.file}:{site.line} carries the "
                "tenancy key and nobody declared it",
            ))
    if unclassified:
        named = "; ".join(f"{label} at {where}" for label, where in sorted(unclassified))
        found.append(finding(
            "tenancy.enumeration-partial",
            f"this checker reads SQL statements and account-key predicates, and it could not "
            f"classify {len(unclassified)} account-scoped site(s): {named}. This declaration is "
            "NOT proven closed, and this is a warning rather than a failure because no language "
            "agnostic text scanner can settle it — read the named files and confirm each one is "
            "declared",
        ))
    return found


def _is_scannable(target: Path, line: Any, operation: str) -> bool:
    """Can the scanner read this exact line as this operation, right now?

    Asked about the DECLARED line, not about the file: the identity of an entry
    point is its subject and what it does, so a declaration is closure-checked
    when the scanner can still find that subject doing that thing anywhere in
    the declared sources — which is what makes a dropped predicate
    (`tenancy.entry-absent`) a different event from a moved one
    (`tenancy.scope-lost`).
    """
    if not isinstance(line, int) or isinstance(line, bool) or not target.is_file():
        return False
    lines = source_lines(target)
    if not 1 <= line <= len(lines):
        return False
    resolved = sql_operation(lines[line - 1])
    if resolved is not None:
        return resolved[0] == operation
    for back in range(1, ATTRIBUTION_WINDOW + 1):
        above = line - 1 - back
        if above < 0:
            return False
        resolved = sql_operation(lines[above])
        if resolved is not None:
            return resolved[0] == operation
    return False


def _denial_shape_fault(
    operation: Any, arm: str, expects: str
) -> tuple[str, str, str] | None:
    """`(finding id, what is wrong, what to do)` when an arm is the WRONG SHAPE.

    Three questions, in the order they can both apply, and each returns a
    different finding because each wants a different fix:

      1. a `using`-denied arm naming a RAISING token. `select`, `update` and
         `delete` are denied by `using`, which raises nothing — so an exception
         assertion here is asserting a *privilege* failure, and a table with no
         policy at all produces exactly that error. This is the trap the research
         names: the assertion passes while isolation is completely broken.
      2. the positive arm naming a LIVENESS token. `lives_ok` passes when the
         write matched zero rows, which is the same silence wearing a different
         hat, and the third arm exists precisely to separate isolation from a
         service that returns nothing.
      3. a denied WRITE named with an ABSENCE token. An empty result is a lie
         about a row that exists: the other account's row is still there, and
         "nothing came back" claims it is not. This is also the pairing clause —
         `assert_unchanged` and `rows_affected_zero` read the row back, an absent
         result does not, so accepting it is accepting an unpaired denial.

    `operation` is passed in rather than read from the case because it lives on
    the ENTRY POINT: the clause that denies an `update` is a property of the
    statement, not of the assertion about it. An operation this checker has no
    opinion about — `call` — returns `None`, because a check that invented a
    failure where it cannot see the mechanism would be a failure with no cause.
    """
    if arm != POSITIVE_ARM and operation in USING_DENIED_OPERATIONS \
            and expects in RAISING_TOKENS:
        return (
            "tenancy.denial-shape",
            f"a {operation} on another account's row is denied by a `using` clause, which "
            "filters the row out and raises NOTHING",
            "Postgres denies a cross-tenant access three ways and two of them raise 42501: a "
            "missing grant and a `with check` violation. This one is the third, and it matches "
            "zero rows silently — so an exception assertion here is asserting a privilege "
            "failure, which is exactly what a table with NO POLICY raises. Assert the empty "
            "result instead, and the test fails for the reason it claims",
        )
    if arm == POSITIVE_ARM and expects in LIVENESS_TOKENS:
        return (
            "tenancy.denial-shape",
            "it asserts only that nothing was raised, and that is true of a write that "
            "matched zero rows",
            "`lives_ok` passes when the write matched zero rows, so it cannot tell isolation "
            "from a service that returns nothing to anybody — which is the state the third "
            "arm exists to rule out. Point it at a line that reads the row's own value "
            "(checksum, status, id)",
        )
    if arm != POSITIVE_ARM and operation in WRITE_OPERATIONS \
            and (expects in ABSENCE_TOKENS or expects == "[]"):
        return (
            "tenancy.denial-unpaired",
            f"an absent result is a lie about a row that exists: the other account's {operation} "
            "target is still there, and nothing came back because nothing was matched, not "
            "because nothing was there",
            "Pair the denied write with a read of the row it was aimed at, scoped to that row, "
            "and declare THAT as the arm's token — `assert_unchanged` or `rows_affected_zero`. "
            "A row count of zero is also what a write which found nothing to do returns, so "
            "without the read the assertion cannot tell a refusal from a no-op",
        )
    return None


def check_denials(repo: Path, entry_points: list) -> list[Finding]:
    """All three arms are in the tests, on the lines named, asserting the right thing.

    Four facts per entry point, and each one is a separate failure because each
    one wants a different fix:

      * a refusal in the declaration is `tenancy.denial-refuses` — a `403`
        confirms the id exists, which is an enumeration oracle, and the contract's
        answer is nonexistence (D33);
      * an arm whose declared line does not carry its token is
        `tenancy.denial-missing`, and the message names WHICH ARM, because "your
        negative assertion moved" and "your positive control was never written" are
        not the same note to a reader;
      * the third arm answered with this language's spelling of nothing is
        `tenancy.positive-control-refused`, which is the only finding here about
        the arm that is SUPPOSED to succeed; and
      * an arm whose file or line is not there is `tenancy.location-missing` or
        `tenancy.line-missing`, reported once by `check_locations` and skipped
        here for the reason every other check skips it — saying the same thing
        twice about one mistake is how a reader starts ignoring the pair.
    """
    found: list[Finding] = []
    for index, item in enumerate(entry_points):
        if not isinstance(item, dict):
            continue
        label = _label(item, index)
        negative = item.get("negative")
        if not isinstance(negative, dict):
            continue
        if negative.get("asserts") != "absent":
            found.append(finding(
                "tenancy.denial-refuses",
                f"{label} answers another account's resource with "
                f"{negative.get('asserts')!r} rather than nonexistence. A refusal confirms the "
                "id exists, which is an enumeration oracle; assert nil, [] or NotFound instead",
            ))
            continue
        cases = negative.get("cases")
        if not isinstance(cases, list):
            continue
        operation = item.get("operation")
        for case in cases:
            if not isinstance(case, dict):
                continue
            arm = case.get("id")
            if not isinstance(arm, str):
                continue
            relative = case.get("file")
            line = case.get("line")
            expects = case.get("expects")
            polarity = ARM_POLARITY.get(arm)
            arm_asserts = case.get("asserts")
            if polarity is not None and arm_asserts != polarity:
                found.append(finding(
                    "tenancy.denial-refuses" if arm_asserts == "refused" else "tenancy.denial-missing",
                    f"{label} declares its {arm} arm as {arm_asserts!r}, and the {arm} arm is "
                    f"{polarity!r}. The two denial arms assert nonexistence and the third asserts "
                    "the account's own row; a suite whose shape disagrees with its declaration "
                    "proves the wrong thing",
                ))
                continue
            # ---- THE SHAPE, and it is a separate check from the four above
            # because it wants a different fix. Everything above asks whether the
            # declaration and the file agree. This asks whether the assertion a
            # service chose can fail for the reason it claims — which is a
            # different question, is the one Postgres's three denial mechanisms
            # decide, and is the one a suite asserting only "it threw" gets wrong
            # while staying green.
            if isinstance(expects, str):
                shape = _denial_shape_fault(operation, arm, expects)
                if shape is not None:
                    found.append(finding(
                        shape[0],
                        f"{label} asserts its {arm} arm with {expects!r}, and {shape[1]}. "
                        f"{shape[2]}",
                    ))
            if not isinstance(expects, str) or not isinstance(relative, str) \
                    or not isinstance(line, int) or isinstance(line, bool):
                continue
            target = repo / relative
            if not target.is_file():
                continue  # check_locations already reported it, with the same line
            lines = source_lines(target)
            if not 1 <= line <= len(lines):
                continue  # likewise
            if arm == POSITIVE_ARM and expects in ABSENCE_TOKENS:
                found.append(finding(
                    "tenancy.positive-control-refused",
                    f"{label} answers its {arm} arm with {expects!r}, which is this language's "
                    f"spelling of nothing, at {relative}:{line} — {lines[line - 1].strip()!r}. "
                    "That is the assertion a service returning nothing to EVERYBODY makes, and "
                    "it is indistinguishable from isolation until somebody checks what the "
                    "account's own credential gets back. Point the arm at a line that reads the "
                    "row's own value",
                ))
                continue
            if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(expects)}(?![A-Za-z0-9_])",
                             strip_comment(lines[line - 1], target.suffix)):
                found.append(finding(
                    "tenancy.denial-missing",
                    f"{label} declares its {arm} arm at {relative}:{line} with "
                    f"expects={expects!r}, and that line does not carry it — "
                    f"{lines[line - 1].strip()!r}. Nothing in the service's tests asserts what "
                    f"the {arm} identity is refused",
                ))
    return found


# --------------------------------------------------------------------------
# the DDL scanner — what Postgres itself was told, read out of the migrations
# --------------------------------------------------------------------------


@dataclass
class Policy:
    """One `create policy`, as the migrations wrote it.

    `clause_lines` maps `"using"` and `"with check"` to the line each clause
    OPENS on, because a migration wraps its policies across lines and the
    declaration names one line per clause. The line is the check, for the reason
    `enforced.line` is: a clause that moved is a clause nobody is reading.

    `roles` is empty when the policy names none, which in Postgres means PUBLIC.
    That is kept as an empty tuple rather than being normalised to `("public",)`
    so the message can say the thing that is actually wrong, which is that nothing
    was named.

    `generated` marks a policy that no migration wrote out: it is the one
    `cafaye.protect_table('<table>')` writes, resolved through
    `SUBSTRATE_POLICY_COMMANDS`. Such a policy has no clause on any line of any
    file, so `clause_lines` is empty and `qualifier` carries the template's
    resolved clause body instead — which is why the clause checks below read one
    or the other and never pretend to open a file for a line that is not there.

    `scoped_by` is the identity function the TEMPLATE resolved this policy by,
    and `writer` the function that wrote it. Both exist because of the fifth
    policy `protect_credential_table` adds: it is scoped by
    `CREDENTIAL_IDENTITY` and not by `rls.identity`, and a check that asked "is
    this policy scoped by the identity the declaration names?" without carrying
    the identity it IS scoped by would either demand a widening of the one policy
    that must not be widened, or skip the policy entirely and leave a resolve
    policy scoped by nothing unexamined. `account_policy` is False for that one
    and is the whole exemption: the other four on the same table still have to
    name `rls.identity`, so a credential table is not a table whose account
    policies stop being checked.
    """

    name: str
    table: str
    command: str
    roles: tuple[str, ...]
    clause_lines: dict[str, int]
    file: str
    line: int
    generated: bool = False
    qualifier: str = ""
    scoped_by: str = ""
    writer: str = ""
    account_policy: bool = True

    def where(self) -> str:
        return f"{self.file}:{self.line}"

    def clause_where(self, clause: str) -> str:
        return f"{self.file}:{self.clause_lines.get(clause, self.line)}"


@dataclass
class Relation:
    """One relation the migrations touched, and the two bits that decide anything.

    `enabled` and `forced` are separate booleans and must stay that way. In
    Postgres `relrowsecurity` and `relforcerowsecurity` are separate reloptions
    bits, neither of which implies the other — which is the mechanical reason
    `tenancy.rls-owner-bypass` and `tenancy.rls-not-enabled` can each fire alone,
    and why removing one line from a migration moves exactly one finding.
    """

    name: str
    kind: str
    file: str
    line: int
    enabled: bool = False
    forced: bool = False
    policies: dict[str, Policy] = field(default_factory=dict)
    security_invoker: bool = False
    reads: tuple[str, ...] = ()
    owner: str | None = None

    def where(self) -> str:
        return f"{self.file}:{self.line}"

    @property
    def protected(self) -> bool:
        """Does anything about this relation claim a row-level boundary?

        True for a table that is enabled, forced, or carries a policy. All three
        are claims: `tenancy.rls-undeclared` has to see a half-adoption whichever
        of the three it is.
        """
        return bool(self.enabled or self.forced or self.policies)


@dataclass
class Ddl:
    """Everything one run of the DDL scanner found, and everything it could not.

    `opaque` is the honest residue and it is the whole reason
    `tenancy.rls-unreadable` exists: a Rails migration is a `.rb` file and a
    Python migration is a `.py` file, both carrying the same DDL as a string, and
    a checker that passed over them would be reporting a clean answer over files
    it never read — which is the "darkroom has no routes" defect, one level down
    and in a language this checker can no longer even name.
    """

    relations: dict[str, Relation] = field(default_factory=dict)
    bypass_roles: dict[str, int] = field(default_factory=dict)
    definers_without_search_path: list[tuple[str, str, int]] = field(default_factory=list)
    opaque: list[tuple[str, str]] = field(default_factory=list)

    def relation(self, name: str) -> Relation | None:
        return self.relations.get(name.lower())

    def merge(self, other: Ddl) -> None:
        """Fold one file's findings into the run, and keep the first writer.

        First wins for a relation's position because a migration that re-`alter`s
        a table created by an earlier migration must not make the finding point
        at a line that does not define it. Everything else accumulates, because a
        policy created in one migration and forced in another is one boundary
        assembled from two files and both halves have to be read to see it.
        """
        for name, relation in other.relations.items():
            existing = self.relations.get(name)
            if existing is None:
                self.relations[name] = relation
                continue
            existing.enabled = existing.enabled or relation.enabled
            existing.forced = existing.forced or relation.forced
            existing.security_invoker = existing.security_invoker or relation.security_invoker
            existing.reads = tuple(sorted(set(existing.reads) | set(relation.reads)))
            existing.owner = existing.owner or relation.owner
            existing.policies.update(relation.policies)
        self.bypass_roles.update(other.bypass_roles)
        self.definers_without_search_path.extend(other.definers_without_search_path)
        self.opaque.extend(other.opaque)


#: The relation kinds `_normalised_kind` maps onto, longest prefix first.
#:
#: `_CREATE_RELATION` lives up in the constants block with every other pattern in
#: this file; only the vocabulary belongs here, because it is the vocabulary
#: `UNPROTECTABLE_KINDS` and `check_rls` reason about.
_RELATION_KINDS = (
    ("materialized", "materialized_view"),
    ("foreign", "foreign_table"),
    ("view", "view"),
)


def _normalised_kind(kind: str) -> str:
    flat = re.sub(r"\s+", " ", kind.strip().lower())
    for prefix, name in _RELATION_KINDS:
        if flat.startswith(prefix):
            return name
    return "table"


def read_ddl(repo: Path, path: Path) -> Ddl:
    """Read one file's row-level-security DDL, and record why it could not be read.

    A file whose suffix this scanner does not read is NOT an error and NOT a
    silent skip: it comes back as a `Ddl` whose `opaque` list says why, and the
    caller turns that into `tenancy.rls-unreadable`. The reason the file is
    recorded rather than dropped is that a name in the message is the difference
    between "I cannot see this" and a confident zero.
    """
    relative = path.relative_to(repo).as_posix()
    ddl = Ddl()
    if path.suffix not in RLS_SUFFIXES:
        # Only recorded when the file actually carries row-level-security DDL.
        # Naming every `.rb` file in a Rails service as unreadable would make the
        # warning fire on a repository that has no policies at all, and a warning
        # that fires on everybody is a warning nobody reads — the same defect as
        # a rule whose answer is "I cannot see this" about a tree with nothing in
        # it. So the file has to LOOK like it holds something before it is named.
        for line, text in enumerate(source_lines(path), start=1):
            if _RLS_MARKER.search(text):
                ddl.opaque.append((
                    f"{relative}:{line}",
                    "a file this checker does not parse, carrying row-level-security DDL",
                ))
                break
        return ddl
    lines = source_lines(path)
    index = 0
    while index < len(lines):
        statement = _SQL_COMMENT.sub("", lines[index]).strip()
        if not statement:
            index += 1
            continue

        relation = _CREATE_RELATION.match(statement)
        if relation:
            length = _statement_length(lines, index)
            _read_relation(ddl, relative, lines, index, length, relation)
            index += length
            continue

        policy = _CREATE_POLICY.match(statement)
        if policy:
            length = _statement_length(lines, index)
            _read_policy(ddl, relative, lines, index, length,
                         policy.group("name").lower(), policy.group("table").lower())
            index += length
            continue

        protected = _PROTECT_TABLE.match(statement)
        if protected:
            # The one call that stands for a table's whole boundary. A migration
            # that adopted kit's substrate writes its enable, its force and its
            # four policies through `execute format(...)` inside plpgsql, so no
            # line in the tree begins `create policy` on a service's behalf; this
            # branch is the only way those policies are visible to the checker,
            # and it is placed after `_CREATE_POLICY` because `select` opens
            # nothing else above.
            #
            # The CREDENTIAL call is resolved as the four it delegates PLUS the
            # fifth it adds, and it is NOT resolved at all without its digest
            # column as a string literal. That is the direction this declines in,
            # and the reason is the template's own: `protect_credential_table`
            # raises `undefined_column` when the second argument is missing, so
            # such a call protected NOTHING, and claiming the four would hand a
            # declaration naming them a green over a table with no policies on
            # it. Nothing is claimed instead, and the declared policy names
            # resolve against nothing — the same safe direction as a
            # runtime-built table name, for the same reason.
            credential = protected.group("credential") is not None
            # The second argument of the ORDINARY call is a login role, so it is
            # dropped rather than read as a digest column. Reading it is the
            # mistake this group exists to prevent: `protect_table('t', 'role')`
            # would hand `t` a resolve policy qualified by a string that is a
            # role name, and `tenancy.rls-undeclared` would fire about a policy
            # the template never wrote.
            digest = (protected.group("digest") or "").lower() if credential else ""
            length = _statement_length(lines, index)
            if not credential or digest:
                _read_substrate_protection(
                    ddl, relative, index + 1,
                    protected.group("table").split(".")[-1].lower(),
                    digest=digest,
                )
            index += length
            continue

        function = _CREATE_FUNCTION.match(statement)
        if function:
            length = _statement_length(lines, index)
            body = " ".join(lines[index:index + length])
            if _SECURITY_DEFINER.search(body) and not _SET_SEARCH_PATH.search(body):
                ddl.definers_without_search_path.append(
                    (function.group("name").lower(), relative, index + 1)
                )
            index += length
            continue

        bit = _ALTER_RLS.match(statement)
        if bit:
            name = bit.group("name").lower()
            verb = bit.group("bit").lower()
            target = ddl.relation(name)
            if target is None:
                # An `alter table` for a relation this file never created. It is
                # still evidence, so it becomes an ownerless relation rather than
                # being dropped — `tenancy.rls-undeclared` is exactly the finding
                # that has to be able to see it.
                target = Relation(name=name, kind="table", file=relative, line=index + 1)
                ddl.relations[name] = target
            if verb == "force":
                target.forced = True
            elif verb == "enable":
                target.enabled = True
            index += 1
            continue

        owner = _ALTER_OWNER.match(statement)
        if owner:
            target = ddl.relation(owner.group("name").lower())
            if target is not None:
                target.owner = owner.group("role").lower()
            index += 1
            continue

        role = _ROLE_STATEMENT.match(statement)
        if role and _ROLE_BYPASS.search(statement):
            ddl.bypass_roles.setdefault(role.group("role").lower(), index + 1)
            index += 1
            continue

        index += 1
    return ddl


def _read_relation(ddl: Ddl, relative: str, lines: list[str], index: int, length: int,
                   relation: re.Match[str]) -> None:
    """Record one `create …` of a relation, and what its body reads."""
    body = " ".join(
        _SQL_COMMENT.sub("", line) for line in lines[index:index + length]
    )
    ddl.relations[relation.group("name").lower()] = Relation(
        name=relation.group("name").lower(),
        kind=_normalised_kind(relation.group("kind")),
        file=relative,
        line=index + 1,
        security_invoker=bool(_SECURITY_INVOKER.search(lines[index])),
        reads=tuple(sorted({
            match.group(1).split(".")[-1].lower()
            for match in re.finditer(_SQL_KEYWORDS["select"], body, re.IGNORECASE)
        })),
    )


def _read_policy(ddl: Ddl, relative: str, lines: list[str], index: int, length: int,
                 name: str, table: str) -> None:
    """Fold one `create policy` statement into the DDL, across every line it spans."""
    window = [_SQL_COMMENT.sub("", line).strip() for line in lines[index:index + length]]
    statement = " ".join(part for part in window if part)
    command_match = _POLICY_COMMAND.search(statement)
    # Postgres's default when a policy omits `for` is `all`, and the schema
    # carries `all` for exactly that policy.
    command = command_match.group("command").lower() if command_match else "all"
    head = _POLICY_CLAUSE.split(statement, maxsplit=1)[0]
    roles_match = _POLICY_ROLES.search(head)
    roles = (
        tuple(token.strip().lower()
              for token in roles_match.group("roles").split(",") if token.strip())
        if roles_match else ()
    )
    clause_lines: dict[str, int] = {}
    for offset, text in enumerate(window):
        for clause in _POLICY_CLAUSE.finditer(text):
            clause_lines.setdefault(
                re.sub(r"\s+", " ", clause.group(1).lower()), index + offset + 1
            )
    target = ddl.relation(table)
    if target is None:
        target = Relation(name=table, kind="table", file=relative, line=index + 1)
        ddl.relations[table] = target
    target.policies[name] = Policy(
        name=name, table=table, command=command, roles=roles,
        clause_lines=clause_lines, file=relative, line=index + 1,
    )


def _read_substrate_protection(ddl: Ddl, relative: str, line: int, table: str,
                               digest: str = "") -> None:
    """Resolve one `select cafaye.protect_table(...)` into the boundary it writes.

    Four facts for `protect_table` and five for `protect_credential_table`, and
    the template's own numbering is the reason for the order: enable and force
    come before any policy is created, so a table the call protected is a table
    that is BOTH bits — `tenancy.rls-not-enabled` and `tenancy.rls-owner-bypass`
    cannot fire for it, which is the point, because they fired for every table of
    an adopting service before this existed and the database was correct
    throughout.

    `digest` is the second argument of the CREDENTIAL call and it is the whole of
    what that call adds beyond the four: `<table>_cafaye_resolve`, `for select`,
    scoped by `CREDENTIAL_IDENTITY` on the column the caller presents. It is not
    in `SUBSTRATE_POLICY_COMMANDS` because it is not a command, and it is not
    scoped by `SUBSTRATE_IDENTITY` because that would be the widening.

    A relation the file never created is still recorded, as elsewhere: a service
    that calls `protect_table` for a table another migration owns is a boundary
    with no declaration behind it, and `tenancy.rls-undeclared` is the finding
    that has to be able to see it.
    """
    target = ddl.relation(table)
    if target is None:
        target = Relation(name=table, kind="table", file=relative, line=line)
        ddl.relations[table] = target
    target.enabled = True
    target.forced = True
    for command in SUBSTRATE_POLICY_COMMANDS:
        name = f"{table}{SUBSTRATE_POLICY_SUFFIX}{command}"
        target.policies[name] = Policy(
            name=name, table=table, command=command, roles=(), clause_lines={},
            file=relative, line=line, generated=True, qualifier=SUBSTRATE_QUALIFIER,
            scoped_by=SUBSTRATE_IDENTITY, writer=SUBSTRATE_WRITER,
        )
    if not digest:
        return
    name = f"{table}{SUBSTRATE_POLICY_SUFFIX}{CREDENTIAL_POLICY_SUFFIX}"
    target.policies[name] = Policy(
        name=name, table=table, command=CREDENTIAL_POLICY_COMMAND, roles=(),
        clause_lines={}, file=relative, line=line, generated=True,
        qualifier=f"{digest} = (select {CREDENTIAL_IDENTITY})",
        scoped_by=CREDENTIAL_IDENTITY, writer=CREDENTIAL_WRITER, account_policy=False,
    )


def normalised_clause(text: str) -> str:
    """The clause's own body, wrapper and whitespace removed.

    Supabase's `rls_policy_always_true` normalises whitespace and compares
    against four spellings of "every row"; the wrapper is stripped here too so
    that `using (true)`, `using(true)` and `using (  true  )` are one answer
    rather than three, which is the whole reason a linter normalises at all.
    """
    body = _POLICY_CLAUSE.sub("", text, count=1).strip().rstrip(";").strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    return re.sub(r"\s+", "", body).lower()


def wrapped(identity: str) -> str:
    """`(select app.current_account())` — the spelling the per-row rule requires.

    Built rather than written out so the pattern and the message cannot disagree,
    and so the identity a service declares is the identity the check is about.
    """
    return f"(select {identity})"


def check_rls(repo: Path, rls: Any, ddl: Ddl) -> list[Finding]:
    """What the migrations did about row-level security, against what was declared.

    Every finding here is a FAILURE except `tenancy.rls-unreadable`, and that is a
    deliberate departure from the three warnings this checker already had. Those
    three all mean *this machine cannot answer that question*, and a warning that
    does not move the exit code exists because failing on it would get the checker
    disabled — a real argument, and one that does not transfer. Everything below
    is decidable from the DDL text, so a warning would be a finding whose severity
    nobody chose.
    """
    if not isinstance(rls, dict):
        return []
    found: list[Finding] = []
    tables = rls.get("tables")
    tables = tables if isinstance(tables, list) else []
    identity = rls.get("identity") if isinstance(rls.get("identity"), str) else ""
    declared: dict[str, dict] = {}
    for item in tables:
        if isinstance(item, dict) and isinstance(item.get("table"), str):
            declared[item["table"].lower()] = item
    public_reads = _public_read_claims(rls.get("publicRead"))

    for name in sorted(declared):
        found.extend(_check_declared_table(repo, name, declared[name], ddl, identity, public_reads))

    found += _check_public_read_claims(public_reads, ddl)

    for name in sorted(ddl.relations):
        relation = ddl.relations[name]
        if name not in declared and relation.protected:
            found.append(finding(
                "tenancy.rls-undeclared",
                f"the migrations enable, force or write a policy on {name!r} ({relation.where()}) "
                "and rls.tables does not list it. Either the table belongs in the declaration or "
                "the DDL does not belong in the migration, and a half-adopted boundary is worse "
                "than either: from inside the service it reads as a boundary, and from outside "
                "it is nothing",
            ))
        if relation.kind == "view":
            covered = sorted(set(relation.reads) & set(declared))
            if covered and not relation.security_invoker:
                found.append(finding(
                    "tenancy.rls-view-invoker",
                    f"view {name!r} ({relation.where()}) reads {', '.join(covered)} and is not "
                    "security_invoker, so it runs with its OWNER's privileges and the table's "
                    "policies never run for the reader. A view without security_invoker is "
                    "security definer by default, and that is true on every PostgreSQL version",
                ))

    for name, relative, line in ddl.definers_without_search_path:
        found.append(finding(
            "tenancy.rls-definer-search-path",
            f"SECURITY DEFINER function {name!r} ({relative}:{line}) does not pin its search "
            "path, so a caller can create an object earlier in that path and have the function "
            "resolve to it with the function owner's rights",
        ))
    if ddl.opaque:
        named = "; ".join(f"{where} ({why})" for where, why in ddl.opaque)
        found.append(finding(
            "tenancy.rls-unreadable",
            f"the declared row-level-security sources hold {len(ddl.opaque)} file(s) this "
            f"checker does not parse: {named}. The database half of this declaration is NOT "
            "proven closed, and this is a warning rather than a failure because no stdlib text "
            "scanner can settle a migration written as a Ruby or a Python string — read the "
            "named files and confirm each policy and force bit is declared",
        ))
    return found


def _public_read_claims(public_read: Any) -> dict[tuple[str, str], str]:
    """The declared public-read claims, as (table, policy) -> role.

    Only well-formed entries become claims. A malformed one is `tenancy.schema`
    and the checker does not guess at what it meant — the same rule every other
    half of this file runs on.
    """
    claims: dict[tuple[str, str], str] = {}
    if not isinstance(public_read, list):
        return claims
    for entry in public_read:
        if not isinstance(entry, dict):
            continue
        table = entry.get("table")
        policy = entry.get("policy")
        role = entry.get("role")
        if isinstance(table, str) and isinstance(policy, str) and isinstance(role, str):
            claims[(table.lower(), policy.lower())] = role.lower()
    return claims


def _check_public_read_claims(public_reads: dict[tuple[str, str], str], ddl: Ddl) -> list[Finding]:
    """Each public-read claim, against the DDL that has to back it.

    The tier is a claim with evidence, so the evidence is checked in both
    directions. The named policy has to exist on the named table, has to be a
    SELECT policy, and has to grant to the role the declaration names — and a
    claim the migrations do not write is `tenancy.rls-public-read-absent`, because
    a service that believes it has a public read it does not is a service whose
    boundary is a sentence, and the declaration cannot be asserted into existence.

    The check is mechanical on purpose: it asks whether the DDL writes the policy
    the declaration names, not whether the policy's clause is "really" public. A
    declared public read whose clause turns out to be account-scoped is a
    declaration that over-promises safety the boundary already has, and the
    permissive arms it exempts would not have fired anyway — which
    `harness/tenancy_findings.json`'s `notEnforced` list says out loud rather
    than leaving it to be discovered.
    """
    found: list[Finding] = []
    for (table, policy), role in sorted(public_reads.items()):
        relation = ddl.relation(table)
        if relation is None:
            found.append(finding(
                "tenancy.rls-public-read-absent",
                f"rls.publicRead names {table!r} as a public-readable table and the declared "
                "sources never create it, so the public read is asserted about a table the "
                "database does not have",
            ))
            continue
        written = relation.policies.get(policy)
        if written is None:
            found.append(finding(
                "tenancy.rls-public-read-absent",
                f"rls.publicRead names policy {policy!r} on {table!r} as the public read and the "
                f"migrations never write it — they create {sorted(relation.policies) or 'no policy at all'}",
            ))
            continue
        if written.command != "select":
            found.append(finding(
                "tenancy.rls-public-read-absent",
                f"rls.publicRead names policy {policy!r} on {table!r} as a public read and the "
                f"migrations write it `for {written.command}`, and a public read is a SELECT — an "
                "always-true or role-less INSERT, UPDATE, DELETE or ALL clause is still "
                "`tenancy.rls-permissive` under a public-read declaration",
            ))
            continue
        if role not in written.roles:
            found.append(finding(
                "tenancy.rls-public-read-absent",
                f"rls.publicRead names policy {policy!r} on {table!r} as a public read for role "
                f"{role!r} and the migrations bind it `to {list(written.roles)}`, which does not "
                "include that role — so the declaration names a grant the DDL does not write",
            ))
    return found


def _check_declared_table(repo: Path, name: str, spec: dict, ddl: Ddl,
                           identity: str, public_reads: dict[tuple[str, str], str]) -> list[Finding]:
    """One table the declaration covers, against what the migrations did to it."""
    found: list[Finding] = []
    relation = ddl.relation(name)
    if relation is None:
        found.append(finding(
            "tenancy.rls-policy-absent",
            f"rls.tables names {name!r} and the declared sources never create it, so the "
            "declaration describes a table the database does not have",
        ))
        return found

    if relation.kind in UNPROTECTABLE_KINDS:
        found.append(finding(
            "tenancy.rls-unprotectable",
            f"{name} is a {relation.kind.replace('_', ' ')} ({relation.where()}), and row-level "
            f"security cannot constrain one: the {len(relation.policies)} policy/policies "
            "written on it are a comment on a relation that ignores them",
        ))
    if not relation.enabled:
        found.append(finding(
            "tenancy.rls-not-enabled",
            f"{name} ({relation.where()}) carries {len(relation.policies)} policy/policies and "
            f"no `alter table {name} enable row level security`, so none of them is ever "
            "evaluated. A policy that is never evaluated is not a policy that raises",
        ))
    if not relation.forced:
        found.append(finding(
            "tenancy.rls-owner-bypass",
            f"{name} ({relation.where()}) is "
            f"{'enabled but ' if relation.enabled else ''}NOT set FORCE ROW LEVEL SECURITY. "
            f"Postgres does not apply row-level security to a table's OWNER unless the table is "
            f"forced, and a service owns the tables it created in its own schema — so the role "
            f"that owns {name} reads every row in it, while every policy on it sits in the "
            "catalog looking like a boundary",
        ))

    policies = spec.get("policies")
    policies = policies if isinstance(policies, list) else []
    named: set[str] = set()
    for policy in policies:
        if not isinstance(policy, dict) or not isinstance(policy.get("name"), str):
            continue
        policy_name = policy["name"].lower()
        named.add(policy_name)
        written = relation.policies.get(policy_name)
        if written is None:
            found.append(finding(
                "tenancy.rls-policy-absent",
                f"rls.tables names policy {policy_name!r} on {name} and the migrations do not "
                f"create it — they write {sorted(relation.policies) or 'no policy at all'}",
            ))
            continue
        found.extend(_check_policy(repo, policy, written, identity, ddl, public_reads))
    for policy_name in sorted(set(relation.policies) - named):
        found.append(finding(
            "tenancy.rls-undeclared",
            f"policy {policy_name!r} on {name} is in the migrations ({relation.where()}) and not "
            "in rls.tables, so it is a boundary nobody declared and nobody is accountable for. "
            "Permissive policies are OR-ed together, so an undeclared one can widen a declared "
            "one without changing a line anybody wrote",
        ))
    return found


def _check_policy(repo: Path, declared: dict, written: Policy,
                  identity: str, ddl: Ddl,
                  public_reads: dict[tuple[str, str], str]) -> list[Finding]:
    """One declared policy, against the one the migrations wrote.

    `public_reads` is the declared public-read tier, and it narrows three of the
    arms below — the always-true arm, the names-no-role arm and the
    identity-absent arm — for the ONE policy the declaration names as its
    public read, and only when the DDL backs the claim. Everything else about the
    policy is still checked: the role comparison, the bypass arm, the per-row
    rule, and the command the DDL wrote against the SELECT the tier requires.
    """
    found: list[Finding] = []
    where = written.where()
    # THE DECLARED PUBLIC READ, AND IT IS A CLAIM RATHER THAN A SWITCH. The
    # declaration names this policy as the table's public read; the claim is
    # earned only when the DDL wrote it `for select` and bound it to the role the
    # declaration names. A GENERATED policy cannot earn it — the template's `to`
    # clause is unnameable in the text, so its roles are empty and the role
    # comparison below fails — which is the safe direction, since kit's
    # template never writes a public read. And a policy the declaration does not
    # name is untouched by the tier: a public read nobody declared is the defect
    # this checker exists for, not a lesser form of one.
    public_role = public_reads.get((written.table.lower(), written.name.lower()))
    declared_public_read = (
        public_role is not None
        and written.command == "select"
        and public_role in written.roles
    )
    # A generated policy's clause body is the template's, resolved once
    # (`SUBSTRATE_QUALIFIER`); a written one is read off the line it opens on.
    # Both are read through one mapping so no check below has to ask which it is
    # holding, and so neither can open a file for a line that does not exist.
    clauses: dict[str, tuple[int, str]] = (
        {"using": (written.line, written.qualifier),
         "with check": (written.line, written.qualifier)}
        if written.generated else {}
    )
    if not written.generated:
        for clause, clause_line in written.clause_lines.items():
            target = repo / written.file
            lines = source_lines(target) if target.is_file() else []
            clauses[clause] = (
                clause_line,
                _SQL_COMMENT.sub("", lines[clause_line - 1])
                if 1 <= clause_line <= len(lines) else "",
            )
    # A DECLARED PUBLIC READ CANNOT REACH THIS ARM, and that is structural rather
    # than a suppression: the tier requires naming the role the read is granted to,
    # and the claim is only earned when the DDL binds that role, so `written.roles`
    # is non-empty for every policy the tier covers. A policy with no `to` clause
    # applies to PUBLIC — every role, including the migration role — and that is
    # not a public-read tier however the declaration spells it: it is the absence
    # of a boundary, and it is this finding whether or not a publicRead entry
    # names the table. The tier narrows the permissive arms; it does not touch
    # this one.
    if not written.roles and not written.generated:
        found.append(finding(
            "tenancy.rls-permissive",
            f"policy {written.name!r} ({where}) names no role, so it applies to PUBLIC: every "
            "role, including the migration role and every role this service adds later. A "
            "policy that applies to everything is a boundary nobody wrote",
        ))
    roles = declared.get("roles")
    # The roles the declaration names, against the roles the `for … to …` clause
    # names. BOTH directions are a leak and it is one finding rather than two,
    # because both are the same sentence with the subject swapped: the
    # declaration and the DDL disagree about which principals this policy binds,
    # and a service that has written down the wrong answer believes it is
    # isolated and is not.
    #
    #   written − declared   the DDL binds a principal nobody declared. `to
    #                        public, tenant_app` applies the policy to every role
    #                        in the database while the declaration says
    #                        `tenant_app`, which is the shape that looks narrow in
    #                        review and is wide in the database.
    #   declared − written   the declaration promises a boundary for a role the
    #                        policy does not govern, so that role reads every row.
    #
    # `public` cannot be declared (the schema refuses it in `roles`) so the first
    # direction is the one that reaches this most easily. A missing `to` clause is
    # already `rls-permissive` above, and comparing an empty `written.roles`
    # against a declaration here would say the same thing twice.
    #
    # A GENERATED policy is excluded from the comparison, and this is a real gap
    # rather than a formality: the template writes `to %I, %I` bound to
    # `current_user` and `coalesce(p_login_role, current_user || '_app')`, both
    # of which are decided by the session that ran the migration, so the two
    # principals are named in the template and unnameable in the text. What the
    # scanner can still settle it does: the template NEVER leaves `to` off, so
    # the PUBLIC arm above cannot apply, and the bypass arm below reads the
    # roles the DECLARATION names, which is the half a service can get wrong.
    # `harness/tenancy_findings.json` carries the same sentence in its
    # `notEnforced` list, where a reader looking for the gap will find it.
    named_roles = tuple(
        role.strip().lower()
        for role in roles
        if isinstance(role, str) and role.strip()
    ) if isinstance(roles, list) else ()
    if written.roles and named_roles and not written.generated:
        unbound = sorted(set(written.roles) - set(named_roles))
        undeclared = sorted(set(named_roles) - set(written.roles))
        if unbound or undeclared:
            said = ", ".join(repr(role) for role in (unbound + undeclared)) or "nothing"
            found.append(finding(
                "tenancy.rls-permissive",
                f"policy {written.name!r} ({where}) and rls.tables[].policies[].roles name "
                f"different roles, and the declaration is the one that is wrong: the DDL binds "
                f"{list(written.roles)} and the declaration names {list(named_roles)}"
                + (f", so {said} is a principal this boundary does not account for"
                   if unbound else
                   ", so the roles it does name are not governed by this policy at all"),
            ))
    for role in roles if isinstance(roles, list) else []:
        if isinstance(role, str) and role.lower() in ddl.bypass_roles:
            found.append(finding(
                "tenancy.rls-role-bypass",
                f"policy {written.name!r} ({where}) applies to role {role!r}, which the "
                "migrations give BYPASSRLS or SUPERUSER. Such a role skips every policy on "
                "every table it can read, so this policy is enforced on no read at all",
            ))
    # A GENERATED policy whose template scopes it by one identity while the
    # declaration names another. This is a different question from the clause
    # checks below, and it is asked ONCE rather than once per clause: what is
    # wrong is the declaration, not a line.
    #
    # It is also the only arm that can fire for a generated policy whose clause
    # does name the right identity — which is exactly the case the clause checks
    # cannot catch. `cafaye.protect_table` cannot be told to scope a policy by
    # anything except `cafaye.current_account_id()`, so a declaration naming
    # `app.current_account()` describes a boundary built from an identity no
    # policy on the table reads, and every clause of every one of them resolves
    # its identity perfectly. The checker has to notice the disagreement between
    # the two, not the absence of a string.
    if (identity and written.generated and written.scoped_by
            and written.account_policy and written.scoped_by != identity):
        found.append(finding(
            "tenancy.rls-permissive",
            f"policy {written.name!r} ({where}) is written by "
            f"`{written.writer or SUBSTRATE_WRITER}`, which scopes every policy it creates by "
            f"{written.scoped_by} and cannot be told to scope one by anything else, while "
            f"rls.identity names {identity} — so no account policy on {written.table} is scoped "
            "by the identity this declaration says the boundary is built from. Fix the "
            "declaration: the template's identity is a fact about the migration, not a choice",
        ))
    for clause in sorted(clauses):
        line, text = clauses[clause]
        # THE ALWAYS-TRUE ARM, AND THE PUBLIC-READ TIER IS THE ONE THING THAT
        # STANDS IT DOWN. A declared public read — a policy the declaration names
        # as the table's public read, written `for select` and bound to the named
        # role — is allowed to constrain nothing, because that is what a public
        # read IS. The exemption is the narrowest one in this file: the one named
        # policy on the one declared table, and only while the DDL backs the claim.
        # Every other always-true clause still fires, because a public read nobody
        # declared is the defect this checker exists for and not a lesser form of it.
        if normalised_clause(text) in ALWAYS_TRUE_CLAUSES and not declared_public_read:
            found.append(finding(
                "tenancy.rls-permissive",
                f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) is "
                f"always true, so it constrains nothing. {written.table} is a table this "
                "declaration covers, and this policy is not a declared public read — a public "
                "read nobody declared is the absence of a boundary, not a lesser form of one",
            ))
        # THE IDENTITY THIS POLICY MUST NAME, and it is per policy rather than
        # per table, which is the whole of the credential call's second half.
        #
        # A WRITTEN policy has to be scoped by `rls.identity`: that is the
        # declaration's claim about every policy on a table it covers. A
        # GENERATED one is scoped by whatever the template resolved it by, and for
        # the four account policies that is the declared identity's job to agree
        # with — the check below fires when it does not, and says so with the
        # substrate's reason rather than "scoped by nothing this checker can see".
        #
        # The resolve policy is the exception, and it is the narrowest one
        # available: it is scoped by the digest the CALLER PRESENTED and CANNOT be
        # scoped by the account, because scoping it by the account is not a
        # correction — it is the table-wide SELECT the mechanism exists to prevent.
        # `protect_credential_table` writes it
        # `using (<digest> = (select cafaye.current_credential_digest()))` and
        # cannot be told otherwise. So the exemption is `account_policy: False` and
        # it exempts this ONE identity arm. Everything else still runs on it: the
        # always-true arm above, the wrapping below, and the role arms. A policy
        # nobody checks is a policy that can be wrong.
        #
        # AND THE EXEMPTION IS ABOUT THE PREDICATE, NOT ABOUT WHO WROTE IT — which
        # is why a WRITTEN policy carrying `cafaye.current_credential_digest()` gets
        # the same treatment a generated one does. A service that wrote the five
        # policies out by hand rather than adopting `protect_credential_table` has
        # the same boundary and the same reason the fifth is not account-scoped,
        # and keying the exemption on `generated` would report a false failure
        # against it: the same defect this recognition exists to end, one level
        # down and wearing a different hat. The PREDICATE is what makes it a
        # credential policy, and the predicate is what this file reads.
        credential_scoped = CREDENTIAL_IDENTITY in text
        required = identity
        if written.generated and written.scoped_by:
            required = written.scoped_by
        elif credential_scoped:
            required = CREDENTIAL_IDENTITY
        identities = {required} if required else set()
        if identity and identity != required and written.account_policy and not credential_scoped:
            identities.add(identity)
        for named_identity in sorted(identities):
            if named_identity in text and wrapped(named_identity) not in text:
                found.append(finding(
                    "tenancy.rls-per-row",
                    f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) calls "
                    f"{named_identity} bare rather than as `{wrapped(named_identity)}`, so Postgres "
                    "evaluates it once per row the statement touches rather than once per statement",
                ))
        # THE IDENTITY-ABSENT ARM, AND HERE THE TIER IS DOING THE OPPOSITE OF
        # WHAT IT DID ABOVE: a public read's clause is SUPPOSED to be scoped by
        # nothing — that is the product, not the defect — so the arm stands down
        # for exactly the policy the declaration names. The per-row arm above is
        # untouched, because a public read never names the identity at all and so
        # cannot call it bare; and the credential exemption is untouched, because
        # a resolve policy is not a public read and the two never meet.
        if required and required not in text and not declared_public_read:
            found.append(finding(
                "tenancy.rls-permissive",
                _identity_absent(written, clause, required, identity),
            ))
    return found


def _identity_absent(written: Policy, clause: str, required: str, identity: str) -> str:
    """The clause-never-names-the-identity message, for the two kinds of policy.

    A WRITTEN policy that never mentions the identity it must be scoped by is
    scoped by nothing this checker can see, and that sentence is the finding. A
    GENERATED one cannot be: the template scopes every policy it writes, so what
    is wrong there is the DECLARATION or the template, and saying "scoped by
    nothing this checker can see" about a policy whose predicate this file
    resolved two hundred lines earlier would be the checker disagreeing with
    itself in one report.

    `required` is the identity the policy is actually scoped by, which is the
    declared one for a written policy and `cafaye.current_account_id()` or
    `cafaye.current_credential_digest()` for a generated one — so the message
    names the FUNCTION that resolved the predicate rather than only the function
    it disagrees with.
    """
    if not written.generated:
        if required == CREDENTIAL_IDENTITY:
            return (
                f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) names "
                "the credential digest nowhere, so it is not scoped by the value a caller "
                "presents and it is not scoped by the account either — which makes it a "
                "policy scoped by nothing this checker can see, on the one table where a "
                "credential table's narrowest read depends on the predicate being here"
            )
        return (
            f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) never "
            f"mentions {required}, so the policy is not scoped by the identity this "
            "declaration names and is scoped by nothing this checker can see"
        )
    return (
        f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) is written by "
        f"`{written.writer or SUBSTRATE_WRITER}`, which scopes this policy by {required} and "
        "cannot be told to scope one by anything else"
        + (f", while rls.identity names {identity} — so no account policy on {written.table} is "
           "scoped by the identity this declaration says the boundary is built from"
           if identity and identity != required else
           " — so the policy is scoped by a function that does not exist in this migration")
    )


def check_honest_zero(repo: Path, account_scoped: Any, sites: list[Site], entry_points: list,
                       unattributed: list[tuple[str, str]], non_row_sites: Any) -> list[Finding]:
    """`accountScoped: false` is a claim, and it is checked.

    Both halves. A service saying `true` with an empty list is the same omission
    wearing a declaration. And a service saying `false` has to have no
    account-scoped code AT ALL — including code the scanner could not classify,
    which is the half that matters: "the declared tenancy key appears in the
    declared sources" needs no parser, so the honest zero is checkable even for a
    language this checker cannot read. A service that legitimately holds no
    customer data — `kit` and `caf` are the fleet's two — says so here and is
    believed only while it stays true.

    The one exception is a site the declaration VOUCHES for, and the exception is
    the whole reason this check is not a false red on every language-neutral
    service. A key can appear in a source and not be a row scope: muse reads
    `account_id` as a verified token claim for metering, and no SQL statement in
    its tree carries it. Counting that as evidence against the zero made the zero
    UNREACHABLE — a format that cannot express a true answer is the defect, not
    the service that could not declare it. So `scope.nonRowSites` names each such
    site with the reason it is not a row scope, and a named site is not counted.

    What the field is NOT is an escape hatch, and the asymmetry is the point. It
    excuses only sites the scanner could NOT attribute to a statement — a key
    this scanner read in a `select` is a row scope by definition and naming it
    changes nothing. And it excuses only sites that are NAMED: a key-carrying
    line the declaration does not mention is still evidence, which is what keeps
    an omission a failure. The declaration vouches for what it can see and the
    check still fails for what it does not.
    """
    found: list[Finding] = []
    named: set[tuple[str, int]] = set()
    if isinstance(non_row_sites, list):
        for item in non_row_sites:
            if not isinstance(item, dict):
                continue
            file_name = item.get("file")
            line = item.get("line")
            if isinstance(file_name, str) and isinstance(line, int) and not isinstance(line, bool):
                named.add((file_name, line))
    # The scan's unattributed sites, partitioned into the ones the declaration
    # vouches for and the ones it does not. `unattributed` carries `(label, where)`
    # pairs whose label is `file:line` — the same shape `scan_file` builds — so the
    # partition is a tuple comparison and never a re-parse of a path.
    unnamed: list[tuple[str, str]] = []
    for label, where in unattributed:
        file_name, sep, line_text = label.rpartition(":")
        if not sep:
            continue
        try:
            line = int(line_text)
        except ValueError:
            continue
        if (file_name, line) not in named:
            unnamed.append((label, where))
    evidence = len(sites) + len(unnamed)
    if account_scoped is False:
        if evidence:
            parts = []
            if sites:
                parts.append(
                    f"{len(sites)} account-scoped statement(s) this scanner read, "
                    f"starting at {sites[0].file}:{sites[0].line}"
                )
            if unnamed:
                parts.append(
                    f"{len(unnamed)} place(s) carrying the key that the declaration does not "
                    f"vouch for, starting at {unnamed[0][0]}"
                )
            found.append(finding(
                "tenancy.honest-zero",
                f"the service declares no account scoping and the scan found {evidence} "
                f"place(s) carrying its tenancy key in the sources it declared: "
                + "; ".join(parts)
                + ". An omission is not a zero, and a key that appears in the source is a key "
                "this service is scoping by — whether or not this checker could classify the "
                "statement it appears in",
            ))
    elif account_scoped is True and not entry_points:
        found.append(finding(
            "tenancy.enumeration-empty",
            "the service says it scopes by account and declares no entry point that does it",
        ))
    return found


def check_scan(repo: Path, scope: Any, sites: list[Site], missing: list[str],
               missing_ddl: list[str]) -> list[Finding]:
    """Two warnings about the scan itself, because a scan that reads less than
    it was told to read must not read as a clean answer.

    Both declared source lists feed one finding rather than two. `scope.sources`
    and `rls.sources` are separate fields for a real reason — the statement scan
    and the DDL scan read different trees in a Go service — but "the scan read
    less than the declaration asked" is ONE claim, and a reader who has to work
    out which of two identically-worded warnings applies is a reader who
    eventually stops reading either.
    """
    found: list[Finding] = []
    narrowed = []
    if missing:
        narrowed.append(f"scope.sources names {missing}")
    if missing_ddl:
        narrowed.append(f"rls.sources names {missing_ddl}")
    if narrowed:
        found.append(finding(
            "tenancy.scan-narrowed",
            f"{', and '.join(narrowed)}, which is not in this repository, so the scan covered "
            "less than the declaration asked it to",
        ))
    if isinstance(scope, dict):
        key = scope.get("key")
        if isinstance(key, str) and not sites:
            found.append(finding(
                "tenancy.scope-key-unused",
                f"no account-scoped statement this scanner can read carries {key!r}. That is not "
                "proof the service has no scoping — it is usually a key spelled differently from "
                "the column it is really scoping by, and on a service written in a language this "
                "scanner cannot classify it is what an honest 'I cannot see this' looks like",
            ))
    return found


def _label(item: dict, index: int) -> str:
    identifier = item.get("id")
    return identifier if isinstance(identifier, str) and identifier else f"entryPoints[{index}]"


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


def check(repo: Path) -> Report:
    """Check one service's tenancy declaration against that service."""
    repo = repo.resolve()
    if not repo.is_dir():
        return Report(repo=repo, findings=[], could_not_run=f"{repo} is not a directory")
    if sys.version_info < MINIMUM_PYTHON:  # pragma: no cover
        return Report(
            repo=repo, findings=[],
            could_not_run=(
                f"tenancy_check needs python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer. "
                "This is exit 2 and never 0: a check that could not run has not checked "
                "anything."
            ),
        )

    declaration, problem = read_declaration(repo)
    if problem is not None:
        return Report(repo=repo, findings=[problem])
    if not isinstance(declaration, dict):
        return Report(repo=repo, findings=[finding("tenancy.schema", f"{DECLARATION} is not a mapping")])

    # NOTE, and it is a deliberate departure from gate_check: gate_check returns
    # as soon as the schema fails. This file does not, because the two
    # diagnoses it can add on top of a malformed declaration are the ones a
    # reader most needs. `negative.asserts: refused` is both a schema violation
    # and an enumeration oracle, and a reader who is told only "your file is
    # invalid" goes looking for a typo.
    problems = validate(declaration)
    found: list[Finding] = []
    if problems:
        found.append(finding(
            "tenancy.schema",
            f"{DECLARATION} does not satisfy schemas/tenant-isolation.schema.json: "
            + "; ".join(problems[:6])
            + (f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""),
        ))

    scope = declaration.get("scope") if isinstance(declaration.get("scope"), dict) else {}
    rls = declaration.get("rls") if isinstance(declaration.get("rls"), dict) else {}
    entry_points = declaration.get("entryPoints")
    if not isinstance(entry_points, list):
        entry_points = []
    non_row_sites = scope.get("nonRowSites")

    files, missing = declared_files(repo, scope.get("sources"))
    matchers = key_spelling(scope.get("key")) if isinstance(scope.get("key"), str) else ()
    sites: list[Site] = []
    unclassified: list[tuple[str, str]] = []
    for path in files:
        found_sites, unattributed = scan_file(repo, path, matchers)
        sites.extend(found_sites)
        unclassified.extend(unattributed)
    # A snapshot of the SCAN's unattributed sites, taken before `check_closure`
    # appends the declared entry points it could not classify. The honest zero is
    # about what the SCAN found carrying the key; a declared entry point the
    # scanner could not read is a different claim, and for a zero there are none
    # — the schema forbids an enumeration on the `accountScoped: false` arm.
    scan_unattributed = list(unclassified)

    # The database half, from its own declared sources, through the DDL scanner.
    # Both files lists come from the SAME walk helper and the same skipped
    # directories, which is why there is one shape of "the path is not there" and
    # one shape of "this file type is not read".
    ddl_files, missing_ddl = declared_files(repo, rls.get("sources"))
    ddl = Ddl()
    for path in ddl_files:
        ddl.merge(read_ddl(repo, path))

    found += check_locations(repo, entry_points)
    found += check_enforcement(repo, entry_points, matchers)
    found += check_closure(repo, entry_points, sites, unclassified)
    found += check_denials(repo, entry_points)
    found += check_honest_zero(
        repo, declaration.get("accountScoped"), sites, entry_points, scan_unattributed, non_row_sites
    )
    found += check_rls(repo, rls, ddl)
    found += check_scan(repo, scope, sites, missing, missing_ddl)
    return Report(repo=repo, findings=found)


def to_json(report: Report) -> str:
    return json.dumps(
        {
            "repo": str(report.repo),
            "exitCode": report.exit_code,
            "couldNotRun": report.could_not_run,
            "counts": {severity: len(report.of(severity)) for severity in SEVERITIES},
            "findings": [
                {
                    "id": item.id,
                    "severity": item.severity,
                    "message": item.message,
                    "remediate": item.remediate,
                }
                for item in report.findings
            ],
        },
        indent=2,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tenancy-check",
        description="Check a service's tenant-isolation declaration against that service.",
    )
    parser.add_argument("repo", nargs="?", default=".", help="the repository to check (default: .)")
    parser.add_argument("--json", action="store_true", help="emit the findings as JSON")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="list every finding this checker can report, and what each one means",
    )
    arguments = parser.parse_args(argv)

    if arguments.explain:
        for identifier in sorted(FINDINGS):
            severity, claim, remediate = FINDINGS[identifier]
            print(f"{identifier}  [{severity}]\n  {claim}\n  fix: {remediate}")
        return EXIT_OK

    report = check(Path(arguments.repo))
    print(to_json(report) if arguments.json else report.render())
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())

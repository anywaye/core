#!/usr/bin/env python3

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
    from anywaye_contract import Refusal, read_yaml
except ModuleNotFoundError as _missing:  # pragma: no cover
    raise SystemExit(
        f"tenancy_check: cannot import anywaye_contract from {Path(__file__).resolve().parent}: "
        f"{_missing}. tenancy_check travels with the harness; a copy of one without the "
        "other would mean a second YAML dialect, which is the drift core exists to prevent."
    )

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

DECLARATION = Path("tenancy.yml")

TENANCY_SCHEMA_RELATIVE = Path("schemas") / "tenant-isolation.schema.json"

MINIMUM_PYTHON = (3, 9)

EXTRA_STDLIB: frozenset[str] = frozenset()

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
SUBJECT_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EXPECT_PATTERN = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_.]*|\[\])$")
IDENTITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\(\)$")
PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+$")
SCOPE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")

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
        "add `set search_path = ''` to the function and schema-qualify every name inside it; this is advisor lint 0011, raised from WARN to a failure because in anywaye it is a tenant-crossing primitive rather than a hardening nit",
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

TOP_LEVEL_KEYS = frozenset({"version", "service", "accountScoped", "scope", "entryPoints", "rls"})
REQUIRED_TOP_LEVEL_KEYS = ("version", "service", "accountScoped", "scope", "entryPoints", "rls")

OPERATIONS = ("select", "update", "delete", "call")
MECHANISMS = ("query-filter", "bind-parameter", "repository-method", "middleware")


DENIAL_ARMS = ("no-identity", "other-account", "own-account")

POSITIVE_ARM = "own-account"

ARM_POLARITY = {
    "no-identity": "absent",
    "other-account": "absent",
    "own-account": "present",
}

RAISING_TOKENS = frozenset({
    "assert_raises", "assert_raise", "assert_raises_error", "assert_raises_with_message",
    "assert_error", "assert_throws", "must_raise", "raises", "raise_error",
    "throws_ok", "throws", "expect_error", "to_raise", "should_raise",
    "assert_rejects", "rejects", "expectException", "assertThrows", "assertPanics",
    "panics", "should_panic", "expectPanic", "raises_exception",
})

LIVENESS_TOKENS = frozenset({
    "lives_ok", "live_ok", "does_not_raise", "doesnt_raise", "not_to_raise",
    "no_error", "no_exception", "expect_no_error", "assert_no_error",
    "assert_silent", "assert_ok", "succeeds", "survives", "assert_nothing_raised",
})

ABSENCE_TOKENS = frozenset({
    "nil", "None", "empty", "[]", "not_found", "notfound",
    "NotFound", "ErrNotFound", "ErrNoRows",
})


POLICY_COMMANDS = ("select", "insert", "update", "delete", "all")

COMMAND_CLAUSE = {
    "select": "using",
    "delete": "using",
    "insert": "with check",
}

SUBSTRATE_POLICY_COMMANDS = ("select", "insert", "update", "delete")
SUBSTRATE_POLICY_SUFFIX = "_anywaye_"
SUBSTRATE_IDENTITY = "anywaye.current_account_id()"
SUBSTRATE_QUALIFIER = f"account_id = (select {SUBSTRATE_IDENTITY})"
SUBSTRATE_WRITER = "anywaye.protect_table"

CREDENTIAL_POLICY_SUFFIX = "resolve"
CREDENTIAL_POLICY_COMMAND = "select"
CREDENTIAL_IDENTITY = "anywaye.current_credential_digest()"
CREDENTIAL_WRITER = "anywaye.protect_credential_table"

UNPROTECTABLE_KINDS = frozenset({"foreign_table", "materialized_view"})

ALWAYS_TRUE_CLAUSES = frozenset({"true", "(true)", "1=1", "(1=1)"})

RLS_SUFFIXES = frozenset({".sql"})

_RLS_MARKER = re.compile(
    r"\b(row\s+level\s+security|create\s+policy|force\s+row\s+level|security\s+definer)\b",
    re.IGNORECASE,
)

SCANNER_OPERATIONS = frozenset({"select", "update", "delete"})

USING_DENIED_OPERATIONS = frozenset({"select", "update", "delete"})

WRITE_OPERATIONS = frozenset({"update", "delete"})

KEY_SPELLINGS = ("{key}", "{key}_", "{key}Id")

ATTRIBUTION_WINDOW = 4

SKIPPED_DIRECTORIES = frozenset({
    ".git", ".venv", "node_modules", "vendor", "target", "deps", "_build",
    "dist", "build", ".next", ".tox", ".mypy_cache", ".pytest_cache", "coverage",
    "__pycache__",
})

TEXT_SUFFIXES = frozenset({".sql", ".go", ".ex", ".exs", ".rb", ".py", ".ts", ".tsx",
                            ".rs", ".java", ".kt", ".php", ".cs", ".swift", ".js", ".mjs"})

_SQL_COMMENT = re.compile(r"--[^\n]*")

_HASH_COMMENT = re.compile(r"#.*$")
_SLASH_COMMENT = re.compile(r"//.*$")

_DDL = re.compile(
    r"\b(create\s+(?:(?:foreign|materialized|unlogged|temporary|temp)\s+)?table"
    r"|alter\s+table|create\s+(unique\s+)?index|create\s+(materialized\s+)?view"
    r"|create\s+(or\s+replace\s+)?function)\b",
    re.IGNORECASE,
)

_POLICY_STATEMENT = re.compile(r"\bcreate\s+policy\b", re.IGNORECASE)

_CREATE_RELATION = re.compile(
    r"^create\s+(?P<kind>foreign\s+table|unlogged\s+table|temporary\s+table|temp\s+table"
    r"|materialized\s+view|view|table)\s+(?:if\s+not\s+exists\s+)?(?P<name>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

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

_PROTECT_TABLE = re.compile(
    r"^select\s+(?:anywaye\.)?protect_(?:(?P<credential>credential_)?table)\s*\(\s*"
    r"'(?P<table>[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)'"
    r"(?:\s*,\s*'(?P<digest>[a-z_][a-z0-9_]*)')?",
    re.IGNORECASE,
)
_POLICY_COMMAND = re.compile(r"\bfor\s+(?P<command>select|insert|update|delete|all)\b", re.IGNORECASE)
_POLICY_ROLES = re.compile(r"\bto\s+(?P<roles>[a-z_][a-z0-9_]*(?:\s*,\s*[a-z_][a-z0-9_]*)*)\s*$",
                           re.IGNORECASE)
_POLICY_CLAUSE = re.compile(r"\b(using|with\s+check)\s*\(", re.IGNORECASE)

_ROLE_STATEMENT = re.compile(r"^(?:create|alter)\s+role\s+(?P<role>[a-z_][a-z0-9_]*)", re.IGNORECASE)
_ROLE_BYPASS = re.compile(r"\b(bypassrls|superuser)\b", re.IGNORECASE)

_CREATE_FUNCTION = re.compile(
    r"^create\s+(?:or\s+replace\s+)?function\s+(?P<name>[a-z_][a-z0-9_.]*)", re.IGNORECASE
)
_SECURITY_DEFINER = re.compile(r"\bsecurity\s+definer\b", re.IGNORECASE)
_SET_SEARCH_PATH = re.compile(r"\bset\s+search_path\b", re.IGNORECASE)
_SECURITY_INVOKER = re.compile(r"\bsecurity_invoker\b", re.IGNORECASE)

STATEMENT_LINE_BOUND = 64

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
            lines = source_lines(target)
            if not 1 <= line <= len(lines):
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
    `anywaye.protect_table('<table>')` writes, resolved through
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
            credential = protected.group("credential") is not None
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
    window = [_SQL_COMMENT.sub("", line).strip() for line in lines[index:index + length]]
    statement = " ".join(part for part in window if part)
    command_match = _POLICY_COMMAND.search(statement)
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
    found: list[Finding] = []
    where = written.where()
    public_role = public_reads.get((written.table.lower(), written.name.lower()))
    declared_public_read = (
        public_role is not None
        and written.command == "select"
        and public_role in written.roles
    )
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
    if not written.roles and not written.generated:
        found.append(finding(
            "tenancy.rls-permissive",
            f"policy {written.name!r} ({where}) names no role, so it applies to PUBLIC: every "
            "role, including the migration role and every role this service adds later. A "
            "policy that applies to everything is a boundary nobody wrote",
        ))
    roles = declared.get("roles")
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
        if normalised_clause(text) in ALWAYS_TRUE_CLAUSES and not declared_public_read:
            found.append(finding(
                "tenancy.rls-permissive",
                f"the {clause} clause of {written.name!r} ({written.clause_where(clause)}) is "
                f"always true, so it constrains nothing. {written.table} is a table this "
                "declaration covers, and this policy is not a declared public read — a public "
                "read nobody declared is the absence of a boundary, not a lesser form of one",
            ))
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
        if required and required not in text and not declared_public_read:
            found.append(finding(
                "tenancy.rls-permissive",
                _identity_absent(written, clause, required, identity),
            ))
    return found


def _identity_absent(written: Policy, clause: str, required: str, identity: str) -> str:
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
    scan_unattributed = list(unclassified)

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

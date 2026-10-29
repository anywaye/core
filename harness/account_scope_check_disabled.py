#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
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
        f"account_scope_check: cannot import anywaye_contract from "
        f"{Path(__file__).resolve().parent}: {_missing}. It travels with the harness; "
        "a copy of one without the other would mean a second YAML dialect in core."
    )

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

DECLARATION = Path("account_scope.yml")

ACCOUNT_SCOPE_SCHEMA_RELATIVE = Path("schemas") / "account-scope.schema.json"

MINIMUM_PYTHON = (3, 9)

EXTRA_STDLIB: frozenset[str] = frozenset()


SEVERITIES = ("ok", "warn", "fail")

FINDINGS: dict[str, tuple[str, str, str]] = {
    "account-scope.declaration-missing": (
        "fail",
        "the service reaches customer data and declares no account-scoped entry point, so "
        "which of its routes reach another account's rows is a question about route syntax.",
        "write account_scope.yml; the format is documented in docs/account-scope.md and "
        "the schema is schemas/account-scope.schema.json",
    ),
    "account-scope.declaration-unreadable": (
        "fail",
        "account_scope.yml is not a YAML document core's reader accepts.",
        "run: harness/bin/account-scope-check <repo> --explain, and read the file and line "
        "it names",
    ),
    "account-scope.schema": (
        "fail",
        "account_scope.yml does not satisfy schemas/account-scope.schema.json.",
        "run: harness/bin/account-scope-check <repo>, and fix the keys it names — an "
        "undeclared key is a silent no-op everywhere else",
    ),
    "account-scope.surface-missing": (
        "fail",
        "a file named in `surface.sources` is not in this repository, so the declaration "
        "points the checker at something that is not there and `undeclared` cannot be "
        "decided against it.",
        "fix the path, or drop it — a source that is read as itself and does not exist "
        "is a checker looking at nothing",
    ),
    "account-scope.surface-empty": (
        "fail",
        "the service declares entry points and names no file in which they are registered, "
        "so nothing can be checked against the enumeration. This is the D18 defect with the "
        "word `undeclared` attached: a surface nobody read.",
        "name the router file(s) under `surface.sources` — one file rather than a directory "
        "wherever the repository allows it, because `surface.minimum` counts what is in it",
    ),
    "account-scope.undeclared": (
        "fail",
        "a registration is in a file `surface.sources` names and no row of the declaration "
        "covers it. This is the finding the file exists to produce: an entry point nobody "
        "declared is an entry point nobody reviewed.",
        "add a row for it — `accountScoped: true` with `accountFrom`, or `accountScoped: "
        "false` with a `reason` — or move it out of the declared surface if it is a test's "
        "route table",
    ),
    "account-scope.stale": (
        "fail",
        "a declared entry point is no longer registered where the declaration says it is: "
        "the route was renamed, or its registration moved, or the file no longer holds it.",
        "update `registeredAt` to the line the route is registered on, or delete the row if "
        "the entry point is gone — line numbers do not participate in identity, so a "
        "refactor that moved it three lines down is the only thing this is for",
    ),
    "account-scope.account-key-lost": (
        "fail",
        "a declared account-scoped entry point names the line that resolves the caller's "
        "account, and that line no longer carries the account key. The route was scoped and "
        "is not, and this is the only version of a cross-tenant read a declaration can catch "
        "on its own.",
        "put the account back on that line, or move `accountFrom` to the line that does "
        "resolve it — and if the route genuinely stopped being account-scoped, change "
        "`accountScoped` to `false` with a reason rather than leaving the row",
    ),
    "account-scope.surface-thin": (
        "fail",
        "fewer entry-point registrations are in the declared sources than `surface.minimum` "
        "says there should be, so the surface has shrunk since the floor was set.",
        "read the diff that made it shrink and lower `minimum` to the number that is true "
        "now, with the reason in a comment — the floor exists to catch a route that moved "
        "into a file the checker cannot read, so lowering it needs a reason rather than a "
        "keystroke",
    ),
    "account-scope.duplicate-id": (
        "fail",
        "two declared entry points share an `id`, so a reader, a test and a failure message "
        "all name the same thing for two different routes.",
        "give each one its own id — `uniqueItems` cannot catch this because two rows that "
        "differ only in `line` are two objects",
    ),
    "account-scope.service-disagrees": (
        "warn",
        "this file and `tenancy.yml` name two different services, so the two declarations of "
        "one repository disagree about which repository they are about.",
        "make `service` agree, or delete whichever file is in the wrong repository — two "
        "files naming two services is a copy somebody made and nobody checked",
    ),
    "account-scope.nothing-scoped": (
        "warn",
        "the service enumerated its surface and not one entry point on it is "
        "`accountScoped: true`. Either the enumeration is short of the truth or the answer "
        "is that this service reaches no customer data, and only one of those is a decision.",
        "check the routes that read a customer row and are declared `false`; a service that "
        "holds other people's data and says so nowhere is the D18 defect in a form a "
        "checker can now see",
    ),
    "account-scope.scoping-bypassed": (
        "fail",
        "an entry point declared account-scoped names the function that resolves the "
        "caller's account, and the line registering the route does not go through it. The "
        "route was scoped and is not, with `accountFrom` still pointing at a middleware that "
        "nothing calls — which is the whole reason the declaration names the symbol rather "
        "than only a line.",
        "put `via` back on the registration, or change `accountScoped` to `false` with a "
        "reason — leaving a row that says a route is scoped when it is not is worse than "
        "having no file, because the file is what a reader trusts",
    ),
    "account-scope.scope-key-guessed": (
        "warn",
        "nothing in this repository names the tenancy key, so the account lines were "
        "searched for in four spellings this checker chose rather than one the service "
        "declared. A service whose key is spelled `tenant` passes every check here.",
        "declare `scope.key` in tenancy.yml — the checker reads it and searches for that — "
        "or in this file's own `surface.accountKey`, which is what the field is for",
    ),
    "account-scope.declaration-contradicts-code": (
        "fail",
        "an entry point declared `accountScoped: false` reaches another account's data: "
        "the request carries an account that was resolved on the caller's credential, or "
        "the handler reads one, or the handler lets the caller NAME one. The enumeration "
        "was complete and the answers were false, which is the D18 defect in the one form "
        "the omission check cannot see — a checker that asks `did the author enumerate "
        "their surface?` is answered yes by a declaration that lies.",
        "change `accountScoped` to `true` and name the line the evidence is on in "
        "`accountFrom` — or, if the route really is not account-scoped, remove what the "
        "evidence names, because the finding prints the file and line it found",
    ),
    "account-scope.contradiction-unreadable": (
        "warn",
        "an entry point declared `accountScoped: false` whose handler or account-resolving "
        "middleware this checker could not resolve to a file on disk, so no evidence "
        "could be sought or ruled out. Silence here is not a pass: the row was not "
        "verified, and it was not verified for a reason.",
        "name the router's middleware and controller modules the way this repository "
        "already spells them, and if a module is in another repository say so in a "
        "comment on the row — a checker that cannot resolve a symbol says so rather "
        "than trusting the declaration",
    ),
}

KEY_SPELLINGS: tuple[str, ...] = ("account_id", "accountId", "accountID", "account-id")


def key_spellings(repo: Path, key: str | None) -> tuple[str, ...]:
    """The account spellings to search for, preferring the one the service declared.

    `tenancy.yml`'s `scope.key` is the service's own answer and it is read rather
    than required, because a service that has not adopted the tenancy declaration is
    a real state and guessing around it is exactly what D18 measured going wrong.
    """
    if not isinstance(key, str) or not key:
        return KEY_SPELLINGS
    camel = re.sub(r"_([a-z])", lambda found: found.group(1).upper(), key)
    kebab = key.replace("_", "-")
    packed = key.replace("_", "")
    return tuple(dict.fromkeys((key, camel, kebab, packed)))


@dataclass(frozen=True)
class Recogniser:
    """One framework's route-registration syntax, and where it was read from.

    `pattern` carries two named groups, `verb` and `path`. `verb` may be absent
    from a match when the syntax puts the method somewhere the pattern cannot
    reach, which is why `verb_from_handler` exists: axum writes the method in the
    handler position, not in the `.route(` call.
    """

    id: str
    framework: str
    read_from: str
    pattern: re.Pattern[str]
    example: str
    verb_from_handler: re.Pattern[str] | None = None
    carries_handler: bool = True
    path_from_filename: bool = False

    def match(self, line: str, relative: str = "") -> tuple[str, str] | None:
        """`(method, path fragment)` for this line, or nothing."""
        found = self.pattern.search(line)
        if found is None:
            return None
        verb = found.groupdict().get("verb")
        if self.path_from_filename:
            if verb is None:
                return None
            path = route_path_from_filename(relative)
            return None if path == "/" else (verb.upper(), path)
        if verb is None and self.verb_from_handler is not None:
            handler = self.verb_from_handler.search(line)
            verb = handler.group(0) if handler is not None else "ANY"
        if verb is None:
            return None
        path = found.group("path")
        if " " in verb:
            verb, _, rest = verb.partition(" ")
            path = f"/{rest.lstrip('/')}"
        return verb.upper(), path


RECOGNISERS: tuple[Recogniser, ...] = (
    Recogniser(
        id="chi",
        framework="net/http chi",
        read_from="identity/internal/httpapi/accounts.go:586",
        pattern=re.compile(
            r"\b(?P<verb>[A-Za-z_][A-Za-z0-9_]*)\.(?:Get|Post|Put|Patch|Delete|Head|Options|"
            r"Handle|HandleFunc|Connect|Trace)\(\s*\"(?P<path>/[^\"]*)\""
        ),
        example='r.Get("/v1/accounts/{accountID}", o.requireAccountRole(accounts.RoleMember, o.handleGetAccount))',
    ),
    Recogniser(
        id="chi-1.22",
        framework="net/http (Go 1.22 pattern method)",
        read_from="harness/tests/fixtures/account-scope/conforming/internal/httpapi/router.go:11",
        pattern=re.compile(
            r"\.(?:Get|Post|Put|Patch|Delete|Head|Options|Handle|HandleFunc)\(\s*\""
            r"(?P<verb>[A-Z]{3,7})\s+(?P<path>/[^\"]*)\""
        ),
        example='mux.HandleFunc("GET /healthz", o.handleHealthz)',
    ),
    Recogniser(
        id="phoenix",
        framework="Phoenix / Plug.Router",
        read_from="courier/lib/courier_web/router.ex:115",
        pattern=re.compile(
            r"(?P<verb>get|post|put|patch|delete|head|options)\s+\"(?P<path>/[^\"]*)\""
        ),
        example='get "/webhook_endpoints", WebhookEndpointsController, :index',
        carries_handler=False,
    ),
    Recogniser(
        id="hono",
        framework="Hono / Express",
        read_from="gateway/src/index.ts:150",
        pattern=re.compile(
            r"\b(?:app|router|api|r|server)\.(?P<verb>get|post|put|patch|delete|head|options|all)"
            r"\(\s*[\"'`](?P<path>/[^\"'`]*)[\"'`]"
        ),
        example='app.get("/v1/me", (c) => c.json(c.get("principal")));',
    ),
    Recogniser(
        id="next-app",
        framework="Next.js App Router",
        read_from="site/src/app/v1/[...path]/route.ts:138",
        pattern=re.compile(
            r"^export\s+(?:async\s+)?function\s+(?P<verb>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"
        ),
        example=(
            "export function GET(request: Request, context: RouteContext): Promise<Response> {"
        ),
        # The handler is a named export and the middleware is applied inside the
        # function body or by a wrapper, so there is nothing on the LINE to read a
        # bypass from — same answer as Phoenix and axum.
        carries_handler=False,
        path_from_filename=True,
    ),
    Recogniser(
        id="axum",
        framework="axum",
        read_from="pantry/src/http.rs:99",
        pattern=re.compile(r"\.route\(\s*\"(?P<path>/[^\"]*)\""),
        verb_from_handler=re.compile(r"^\s*(get|post|put|patch|delete|head|options)\b"),
        example='.route("/v1/services", get(list_services))',
        carries_handler=False,
    ),
)


def recogniser(identifier: str) -> Recogniser | None:
    """The recogniser behind an id, or nothing. A `while` is a loop and this is a lookup."""
    for candidate in RECOGNISERS:
        if candidate.id == identifier:
            return candidate
    return None


def registrations(line: str, relative: str = "") -> list[tuple[str, str, str]]:
    """Every `(method, path fragment, recogniser)` this line registers."""
    found: list[tuple[str, str, str]] = []
    for recogniser in RECOGNISERS:
        matched = recogniser.match(line, relative)
        if matched is not None:
            verb, path = matched
            found.append((verb, path, recogniser.id))
    return found


COMMENT = re.compile(r"//|#")


def strip_comment(line: str) -> str:
    """The line with its trailing comment removed, at the first `//` or `#`.

    Not a full tokenizer, and it does not need to be: a `#` or `//` inside a route
    literal would be inside quotes at a position no recogniser matches, and the
    cost of being wrong about a line is one extra or one missing finding, not a
    wrong verdict on the repository.
    """
    found = COMMENT.search(line)
    return line if found is None else line[: found.start()]


def route_path_from_filename(relative: str) -> str:
    """Next.js' App Router path, which lives in the file's own name.

    `app/v1/[...path]/route.ts` is `/v1/{...path}` and `app/healthz/route.ts` is
    `/healthz`. The catch-all marker becomes `{}` like every other parameter,
    because `[id]` is a parameter and `[...path]` is a parameter that happens to
    match a slash — the same `{}` keeps it matching a route declared either way.
    A `route.ts` outside an `app/` tree yields `/` rather than an invented path,
    because a guess here becomes an `undeclared` finding against the wrong route.
    """
    parts = relative.split("/")
    if not parts or parts[-1] not in ("route.ts", "route.tsx", "route.js"):
        return "/"
    tail = parts[parts.index("app") + 1 : -1] if "app" in parts else []
    route = "/".join(tail)
    route = re.sub(r"\[\[?\.\.\.([A-Za-z0-9_]+)\]?\]", r"{\1}", route)
    route = re.sub(r"\[([A-Za-z0-9_]+)\]", r"{\1}", route)
    return "/" + route.strip("/")


def canonical(path: str) -> str:
    """A path with every parameter collapsed, so the fleet's two spellings meet.

    `:id` (Phoenix, Express) and `{id}` (axum, chi's Go 1.22 form) are the same
    parameter, and a trailing `$` is axum's match-anything marker rather than part
    of the path. Collapsing both here is what lets one declared path match four
    frameworks without any of them inventing the others' syntax.
    """
    without = re.sub(r"\{[A-Za-z0-9_]+\}|:[A-Za-z0-9_]+", "{}", path)
    return "/" + re.sub(r"/+", "/", without.strip("/")).rstrip("$")


def same_route(declared_method: str, declared_path: str, method: str, path: str) -> bool:
    """Whether a registration is the route a declaration names.

    The METHOD must match, exactly or by way of `ANY` on either side: a
    declaration that says `GET /v1/me` against `post "/v1/me"` is two different
    entry points and treating them as one would halve the enumeration.

    The PATH matches as a SUFFIX, on a segment boundary, because resolving a
    framework's `scope`/`mount` nesting is the guessing that produced three
    different answers across five repositories. `/v1/webhook_endpoints` and
    `/webhook_endpoints` both resolve to Phoenix's `get "/webhook_endpoints"`, and
    the declared full path is the caller's spelling rather than a claim about what
    the framework prepends.
    """
    if declared_method != "ANY" and method != "ANY" and declared_method != method:
        return False
    here, there = canonical(declared_path), canonical(path)
    return here == there or here.endswith("/" + there.lstrip("/"))


def _normalised_key(text: str) -> str:
    return re.sub(r"[_-]", "", text).lower()


def carries_key(line: str, spellings: tuple[str, ...] = KEY_SPELLINGS) -> bool:
    """Whether a line names the account, in any of the spellings searched for."""
    haystack = _normalised_key(line)
    for spelling in spellings:
        needle = _normalised_key(spelling)
        for found in re.finditer(re.escape(needle), haystack):
            before = haystack[found.start() - 1] if found.start() else ""
            after_index = found.end()
            after = haystack[after_index] if after_index < len(haystack) else ""
            if not before.isalnum() and not after.isalnum():
                return True
    return False


def source_lines(path: Path) -> list[str]:
    """A file's lines, or an empty list when it cannot be read.

    Not an error: a file that is not UTF-8 is a binary, and a binary in a declared
    surface is something this checker walks past rather than a run that fails.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def within(repo: Path, relative: str) -> Path:
    """Resolve a declared path INSIDE the repository. It may not leave it."""
    candidate = (repo / relative).resolve()
    root = repo.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"{relative} resolves outside {root}")
    return candidate



@dataclass(frozen=True)
class Finding:
    """One check's answer, in the shape `gate_check` uses and `caf` will read.

    `remediate` is not decoration: every check message in this harness carries the
    exact remediation, because a check that says only "not ok" makes the reader go
    and look, and the reader who does not look is why it is still broken next week.
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
    findings: list[Finding] = field(default_factory=list)
    entry_points: list[dict[str, Any]] = field(default_factory=list)
    could_not_run: str | None = None
    unverified: list[str] = field(default_factory=list)

    def of(self, severity: str) -> list[Finding]:
        return [item for item in self.findings if item.severity == severity]

    @property
    def counts(self) -> dict[str, int]:
        states = {"account-scoped": 0, "not-account-scoped": 0, "undeclared": 0}
        for entry in self.entry_points:
            states[entry["state"]] = states.get(entry["state"], 0) + 1
        states["failures"] = len(self.of("fail"))
        states["warnings"] = len(self.of("warn"))
        return states

    @property
    def exit_code(self) -> int:
        if self.could_not_run is not None:
            return EXIT_COULD_NOT_RUN
        if self.of("fail"):
            return EXIT_FAIL
        return EXIT_OK

    def render(self) -> str:
        lines = [item.render() for item in self.findings]
        if self.entry_points:
            lines.append("")
            for entry in self.entry_points:
                route = entry.get("path") or entry.get("name") or entry["id"]
                method = f"{entry['method']} " if entry.get("method") else ""
                where = entry.get("at", "not on the declared surface")
                lines.append(f"  {entry['state']:<18} {method}{route}  ({where})")
        lines.append("")
        if self.could_not_run is not None:
            lines.append(f"COULD NOT RUN {self.repo}: {self.could_not_run}")
            return "\n".join(lines)
        if self.unverified:
            lines.append(
                f"  not verified: {len(self.unverified)} pipeline symbol(s) the router "
                "names that resolve to no code in this repository — "
                + ", ".join(self.unverified)
            )
            lines.append("")
        failed = len(self.of("fail"))
        warned = len(self.of("warn"))
        counts = self.counts
        verdict = "FAIL" if failed else "OK"
        lines.append(
            f"{verdict} {self.repo}: {counts['account-scoped']} account-scoped, "
            f"{counts['not-account-scoped']} not-account-scoped, "
            f"{counts['undeclared']} undeclared — {failed} failure(s), {warned} warning(s)"
            + (
                "; warnings do not move the exit code"
                if warned
                else ", so nothing was left unproven silently"
            )
        )
        return "\n".join(lines)


def finding(identifier: str, message: str) -> Finding:
    """Build a finding from the inventory, so an unknown id cannot be invented."""
    try:
        severity, _claim, remediate = FINDINGS[identifier]
    except KeyError:  # pragma: no cover - a test asserts the inventory is complete
        raise SystemExit(
            f"account_scope_check: {identifier} is not in FINDINGS. A finding the inventory "
            "does not describe is a finding nobody was told about."
        )
    return Finding(id=identifier, severity=severity, message=message, remediate=remediate)


# --------------------------------------------------------------------------
# reading the declaration
# --------------------------------------------------------------------------


def declaration_path(repo: Path) -> Path:
    return repo / DECLARATION


def read_declaration(repo: Path) -> tuple[Any, Finding | None]:
    path = declaration_path(repo)
    if not path.is_file():
        return None, finding(
            "account-scope.declaration-missing", f"{DECLARATION} is not in {repo}"
        )
    try:
        return read_yaml(path.read_text(encoding="utf-8"), path), None
    except Refusal as refusal:
        return None, finding(
            "account-scope.declaration-unreadable",
            f"{DECLARATION} could not be read: {refusal.detail} (at {refusal.path})",
        )
    except OSError as error:
        return None, finding(
            "account-scope.declaration-unreadable", f"{DECLARATION} is unreadable: {error}"
        )


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PATH_PATTERN = re.compile(r"^[A-Za-z0-9._\[\]-]+/[A-Za-z0-9._\[\]/-]+$")
SURFACE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._\[\]-]+(/[A-Za-z0-9._\[\]-]+)*$")
ROUTE_PATTERN = re.compile(r"^/[A-Za-z0-9._~{}$:/-]*$")
NAME_OF_ENTRY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ANY")
REASONS = ("public", "platform-admin", "system", "unauthenticated-callback", "none")
KINDS = ("http", "job", "internal")
SURFACE_KINDS = ("http", "job", "both", "none")
ENTRY_KEYS = (
    "id",
    "kind",
    "method",
    "path",
    "name",
    "accountScoped",
    "accountFrom",
    "reason",
    "registeredAt",
)
ACCOUNT_FROM_KEYS = ("file", "line", "via")
TOP_LEVEL_KEYS = ("version", "service", "surface", "entryPoints")
SURFACE_KEYS = ("kind", "sources", "minimum", "accountKey")
SURFACE_REQUIRED = ("kind", "sources", "minimum")
LOCATION_KEYS = ("file", "line")
SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _location_problems(
    block: Any, where: str, allowed: tuple[str, ...] = LOCATION_KEYS
) -> list[str]:
    if not isinstance(block, dict):
        return [f"{where} is not a mapping"]
    problems = [f"{where}.{key} is undeclared" for key in block if key not in allowed]
    for key in ("file", "line"):
        if key not in block:
            problems.append(f"{where} is missing {key}")
    file_name = block.get("file")
    if file_name is not None and (
        not isinstance(file_name, str)
        or not PATH_PATTERN.match(file_name)
        or ".." in file_name.split("/")
    ):
        problems.append(f"{where}.file is not a repository-relative path")
    line = block.get("line")
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
        problems.append(f"{where}.line is not a 1-indexed line")
    return problems


def validate(declaration: Any) -> list[str]:
    """The schema's constraints, re-implemented — this file imports no jsonschema.

    core's own idiom: a document and its schema are the same contract written
    twice, and the harness must be able to run on a service's CI with nothing
    installed. `test_the_account_scope_checker_and_the_schema_agree_on_every
    _example` is what stops the two copies from drifting.
    """
    if not isinstance(declaration, dict):
        return ["account_scope.yml is not a mapping"]
    problems: list[str] = []
    for key in declaration:
        if key not in TOP_LEVEL_KEYS:
            problems.append(f"{key} is undeclared at the top level")
    for key in ("version", "service", "surface", "entryPoints"):
        if key not in declaration:
            problems.append(f"{key} is required")
    if declaration.get("version") != 1:
        problems.append("version is const 1")
    service = declaration.get("service")
    if service is not None and (not isinstance(service, str) or not NAME_PATTERN.match(service)):
        problems.append("service is not kebab-case")
    surface = declaration.get("surface")
    if isinstance(surface, dict):
        problems += _validate_surface(surface)
    elif surface is not None:
        problems.append("surface is not a mapping")
    points = declaration.get("entryPoints")
    if isinstance(points, list):
        seen: dict[str, int] = {}
        for index, entry in enumerate(points):
            where = f"entryPoints[{index}]"
            problems += _validate_entry_point(entry, where)
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                seen[entry["id"]] = index
        for identifier in sorted(seen):
            if list(seen).count(identifier) > 1:
                problems.append(f"entryPoints: {identifier} is declared more than once")
    elif points is not None:
        problems.append("entryPoints is not a list")
    return problems


def _validate_surface(surface: dict[str, Any]) -> list[str]:
    problems = [f"surface.{key} is undeclared" for key in surface if key not in SURFACE_KEYS]
    for key in SURFACE_REQUIRED:
        if key not in surface:
            problems.append(f"surface is missing {key}")
    kind = surface.get("kind")
    if kind is not None and kind not in SURFACE_KINDS:
        problems.append(f"surface.kind {kind!r} is not in {SURFACE_KINDS}")
    sources = surface.get("sources")
    if not isinstance(sources, list):
        problems.append("surface.sources is not a list")
    else:
        for item in sources:
            if not isinstance(item, str) or not SURFACE_PATH_PATTERN.match(item):
                problems.append(f"surface.sources: {item!r} is not a repository-relative path")
        if len(set(sources)) != len(sources):
            problems.append("surface.sources repeats a path")
        if kind != "none" and not sources:
            problems.append("surface.sources is empty, so nothing can be read to check")
        if kind == "none" and sources:
            problems.append("surface.kind is `none`, so it may not name sources")
    account_key = surface.get("accountKey")
    if account_key is not None and (
        not isinstance(account_key, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", account_key)
    ):
        problems.append("surface.accountKey is not an identifier")
    minimum = surface.get("minimum")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        problems.append("surface.minimum is not a count")
    elif kind == "none" and minimum != 0:
        problems.append("surface.kind is `none`, so surface.minimum is 0")
    return problems


def _validate_entry_point(entry: Any, where: str) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{where} is not a mapping"]
    problems = [f"{where}.{key} is undeclared" for key in entry if key not in ENTRY_KEYS]
    for key in ("id", "kind", "accountScoped", "registeredAt"):
        if key not in entry:
            problems.append(f"{where} is missing {key}")
    if "id" in entry and (not isinstance(entry["id"], str) or not ID_PATTERN.match(entry["id"])):
        problems.append(f"{where}.id is not kebab-case")
    kind = entry.get("kind")
    if kind is not None and kind not in KINDS:
        problems.append(f"{where}.kind {kind!r} is not in {KINDS}")
    if kind == "http":
        for key in ("method", "path"):
            if key not in entry:
                problems.append(f"{where} is missing {key} because kind is http")
        if "name" in entry:
            problems.append(f"{where}.name is forbidden because kind is http")
    if kind in ("job", "internal"):
        if "name" not in entry:
            problems.append(f"{where} is missing name because kind is {kind}")
        for key in ("method", "path"):
            if key in entry:
                problems.append(f"{where}.{key} is forbidden because kind is {kind}")
    method = entry.get("method")
    if method is not None and method not in METHODS:
        problems.append(f"{where}.method {method!r} is not in {METHODS}")
    path = entry.get("path")
    if path is not None and (not isinstance(path, str) or not ROUTE_PATTERN.match(path)):
        problems.append(f"{where}.path is not a request path")
    name = entry.get("name")
    if name is not None and (
        not isinstance(name, str) or not NAME_OF_ENTRY_PATTERN.match(name)
    ):
        problems.append(f"{where}.name is not a module or symbol name")
    scoped = entry.get("accountScoped")
    if not isinstance(scoped, bool):
        problems.append(f"{where}.accountScoped is not a boolean")
    elif scoped:
        if "accountFrom" not in entry:
            problems.append(
                f"{where} says accountScoped: true and names no accountFrom, so nothing can "
                "check the scoping later"
            )
    elif "accountFrom" in entry:
        problems.append(f"{where} is not account-scoped, so it may not carry accountFrom")
    if scoped is False:
        if "reason" not in entry:
            problems.append(f"{where} is not account-scoped and names no reason")
        elif entry["reason"] not in REASONS:
            problems.append(f"{where}.reason {entry['reason']!r} is not in {REASONS}")
    elif "reason" in entry:
        problems.append(f"{where} is account-scoped, so it may not carry a reason")
    if "accountFrom" in entry:
        problems += _location_problems(
            entry["accountFrom"], f"{where}.accountFrom", ACCOUNT_FROM_KEYS
        )
        account_from = entry["accountFrom"]
        if isinstance(account_from, dict):
            via = account_from.get("via")
            if via is None:
                problems.append(
                    f"{where}.accountFrom names no `via`, so nothing can tell whether the "
                    "route still goes through the thing that resolved its account"
                )
            elif not isinstance(via, str) or not SYMBOL_PATTERN.match(via):
                problems.append(f"{where}.accountFrom.via is not a symbol")
    if "registeredAt" in entry:
        problems += _location_problems(entry["registeredAt"], f"{where}.registeredAt")
    return problems




@dataclass(frozen=True)
class Registered:
    """One registration the checker can see, and where it saw it."""

    method: str
    path: str
    recogniser: str
    file: str
    line: int

    def at(self) -> str:
        return f"{self.file}:{self.line}"


def discover(repo: Path, sources: list[str]) -> tuple[list[Registered], list[Finding], list[str]]:
    """Read the declared sources and return what they register.

    Three values, and the third is the honest one: a source that is not on disk is
    a FAILURE (`surface-missing`) rather than a file skipped in silence, and the
    list of missing paths is returned so the caller can say which.
    """
    found: list[Registered] = []
    problems: list[Finding] = []
    missing: list[str] = []
    for source in sources:
        try:
            path = within(repo, source)
        except ValueError as error:
            missing.append(source)
            problems.append(finding("account-scope.surface-missing", str(error)))
            continue
        if not path.is_file():
            missing.append(source)
            problems.append(
                finding("account-scope.surface-missing", f"surface.sources names {source}, which is not in this repository")
            )
            continue
        if path.is_dir():
            targets = sorted(
                child
                for child in path.rglob("*")
                if child.is_file()
                and child.suffix in SOURCE_SUFFIXES
                and not SKIPPED & set(child.parts)
            )
        else:
            targets = [path]
        for target in targets:
            relative = str(target.relative_to(repo))
            for number, line in enumerate(source_lines(target), start=1):
                for method, fragment, recogniser in registrations(
                    strip_comment(line), relative
                ):
                    found.append(
                        Registered(
                            method=method,
                            path=fragment,
                            recogniser=recogniser,
                            file=relative,
                            line=number,
                        )
                    )
    return found, problems, missing


SOURCE_SUFFIXES = frozenset({".go", ".ex", ".exs", ".ts", ".tsx", ".js", ".mjs", ".rs", ".rb", ".py"})

SKIPPED = frozenset({"node_modules", "target", "_build", ".venv", "vendor", "dist", "__pycache__"})


def check(repo: Path) -> Report:
    """Check one service's account-scope declaration against that service."""
    repo = repo.resolve()
    report = Report(repo=repo, findings=[], entry_points=[])
    if not repo.is_dir():
        report.could_not_run = f"{repo} is not a directory"
        return report
    if sys.version_info < MINIMUM_PYTHON:  # pragma: no cover
        report.could_not_run = (
            f"account_scope_check needs python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer. "
            "This is exit 2 and never 0: a check that could not run has not checked anything."
        )
        return report

    declaration, problem = read_declaration(repo)
    if problem is not None:
        report.findings.append(problem)
        return report
    if not isinstance(declaration, dict):
        report.findings.append(
            finding("account-scope.schema", f"{DECLARATION} is not a mapping")
        )
        return report

    problems = validate(declaration)
    if problems:
        report.findings.append(
            finding(
                "account-scope.schema",
                f"{DECLARATION} does not satisfy {ACCOUNT_SCOPE_SCHEMA_RELATIVE.as_posix()}: "
                + "; ".join(problems[:6])
                + (f" (and {len(problems) - 6} more)" if len(problems) > 6 else ""),
            )
        )

    raw_surface = declaration.get("surface")
    surface: dict[str, Any] = raw_surface if isinstance(raw_surface, dict) else {}
    points = declaration.get("entryPoints")
    if not isinstance(points, list):
        points = []
    declared_sources = surface.get("sources")
    sources = [item for item in declared_sources if isinstance(item, str)] if isinstance(
        declared_sources, list
    ) else []

    if surface.get("kind") != "none" and not sources:
        report.findings.append(
            finding(
                "account-scope.surface-empty",
                f"{DECLARATION} declares {len(points)} entry point(s) and names no file in "
                "which they are registered, so none of them can be checked",
            )
        )
        surface_found: list[Registered] = []
    else:
        surface_found, missing_problems, _missing = discover(repo, sources)
        report.findings.extend(missing_problems)

    minimum = surface.get("minimum")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(surface_found) < minimum:
        report.findings.append(
            finding(
                "account-scope.surface-thin",
                f"the declared sources register {len(surface_found)} entry point(s) and "
                f"surface.minimum is {minimum}",
            )
        )

    report.entry_points, unmatched, matched = classify(repo, points, surface_found)
    for registration in unmatched:
        method = "" if registration.method == "ANY" else registration.method + " "
        report.entry_points.append(
            {
                "id": f"undeclared:{registration.method} {registration.path}",
                "kind": "http",
                "method": registration.method,
                "path": registration.path,
                "state": "undeclared",
                "at": registration.at(),
                "recogniser": registration.recogniser,
            }
        )
        report.findings.append(
            finding(
                "account-scope.undeclared",
                f"{registration.recogniser} registers {method}{registration.path} at "
                f"{registration.at()}, which is in a file surface.sources names and which no "
                "entry point covers",
            )
        )
    report.entry_points.sort(key=lambda item: (item["state"], item["at"], item["id"]))

    contradictions, unverified = [], []
    report.findings.extend(contradictions)
    report.unverified.extend(unverified)

    spellings, guessed = _key_spellings(repo, surface)
    if guessed:
        report.findings.append(
            finding(
                "account-scope.scope-key-guessed",
                "neither surface.accountKey nor tenancy.yml's scope.key names the tenancy key, "
                f"so the account lines were searched for in {list(KEY_SPELLINGS)}",
            )
        )
    for entry in points:
        report.findings.extend(_check_entry(repo, entry, spellings))

    report.findings.extend(_check_ids(points))
    report.findings.extend(_check_service(repo, declaration))
    if points and not any(
        isinstance(entry, dict) and entry.get("accountScoped") is True for entry in points
    ):
        report.findings.append(
            finding(
                "account-scope.nothing-scoped",
                f"all {len(points)} declared entry point(s) are accountScoped: false",
            )
        )
    return report


def classify(
    repo: Path, points: list[Any], surface_found: list[Registered]
) -> tuple[list[dict[str, Any]], list[Registered], dict[int, Registered]]:
    """Per entry point: account-scoped, not-account-scoped, or — the finding —
    undeclared. Returns the classified rows, the registrations nothing claimed, and
    which registration each row matched.

    `repo` is taken rather than used so the signature matches its siblings; the
    classification is a decision about two lists, and the disk is not consulted
    until `_check_entry`. The third value is new and the contradiction check needs
    it: `accountScoped: false` is only checkable against the registration its row
    matched, because a row whose route the checker cannot find on the declared
    surface is a row it did not verify — `stale` already says so, and saying it
    from two directions is the point.
    """
    rows: list[dict[str, Any]] = []
    taken: set[int] = set()
    matched: dict[int, Registered] = {}
    for entry in points:
        if not isinstance(entry, dict):
            continue
        scoped = entry.get("accountScoped")
        state = "account-scoped" if scoped is True else "not-account-scoped"
        where = ""
        for index, registration in enumerate(surface_found):
            if index in taken:
                continue
            method = entry.get("method")
            path = entry.get("path")
            if not isinstance(method, str) or not isinstance(path, str):
                continue
            if same_route(method, path, registration.method, registration.path):
                taken.add(index)
                matched[len(rows)] = registration
                where = registration.at()
                break
        if not where:
            registered = entry.get("registeredAt")
            if isinstance(registered, dict) and isinstance(registered.get("file"), str):
                where = f"{registered['file']}:{registered.get('line')}"
        rows.append(
            {
                "id": entry.get("id"),
                "kind": entry.get("kind"),
                "method": entry.get("method"),
                "path": entry.get("path"),
                "name": entry.get("name"),
                "state": state,
                "at": where or "not on the declared surface",
                "accountFrom": entry.get("accountFrom"),
                "reason": entry.get("reason"),
            }
        )
    unmatched = [
        registration
        for index, registration in enumerate(surface_found)
        if index not in taken
    ]
    return rows, unmatched, matched


def _line_at(repo: Path, block: Any) -> tuple[str | None, str | None]:
    if not isinstance(block, dict):
        return None, "the block is not a mapping"
    file_name = block.get("file")
    number = block.get("line")
    if not isinstance(file_name, str) or not isinstance(number, int):
        return None, "it names no file and a 1-indexed line"
    try:
        path = within(repo, file_name)
    except ValueError as error:
        return None, str(error)
    lines = source_lines(path)
    if not lines:
        return None, f"{file_name} is not readable as text"
    if number < 1 or number > len(lines):
        return None, f"{file_name} has {len(lines)} line(s), so {number} is not in it"
    return lines[number - 1], None


def _check_entry(repo: Path, entry: Any, spellings: tuple[str, ...]) -> list[Finding]:
    if not isinstance(entry, dict):
        return []
    found: list[Finding] = []
    label = entry.get("id") if isinstance(entry.get("id"), str) else "an entry point"
    kind = entry.get("kind")

    line, problem = _line_at(repo, entry.get("registeredAt"))
    if line is None:
        found.append(
            finding("account-scope.stale", f"{label}: registeredAt names nothing on disk ({problem})")
        )
    else:
        carries = False
        if kind == "http":
            path = entry.get("path")
            if isinstance(path, str):
                relative = ""
                registered = entry.get("registeredAt")
                if isinstance(registered, dict) and isinstance(registered.get("file"), str):
                    relative = registered["file"]
                carries = any(
                    same_route(entry.get("method", "ANY"), path, method, found_path)
                    for method, found_path, _recogniser in registrations(line, relative)
                ) or canonical(path).split("/")[-1] in line
        else:
            name = entry.get("name")
            carries = isinstance(name, str) and name in line
        if not carries:
            found.append(
                finding(
                    "account-scope.stale",
                    f"{label}: registeredAt points at a line that does not register it: "
                    f"{entry.get('registeredAt', {}).get('file')}:"
                    f"{entry.get('registeredAt', {}).get('line')}",
                )
            )

    if entry.get("accountScoped") is True:
        account_from = entry.get("accountFrom")
        via = account_from.get("via") if isinstance(account_from, dict) else None

        if isinstance(via, str) and isinstance(account_from, dict):
            named = account_from.get("file")
            whole = source_lines(within(repo, named)) if isinstance(named, str) else []
            if not any(
                re.search(rf"(?<![A-Za-z0-9_]){re.escape(via)}(?![A-Za-z0-9_])", text)
                for text in whole
            ):
                found.append(
                    finding(
                        "account-scope.account-key-lost",
                        f"{label}: accountFrom names {via}, which does not appear in {named}",
                    )
                )
            registration_line, _ = _line_at(repo, entry.get("registeredAt"))
            handler_is_readable = registration_line is not None and any(
                candidate.carries_handler
                for candidate in RECOGNISERS
                if candidate.match(registration_line) is not None
            )
            readable = (
                handler_is_readable
                and registration_line is not None
                and re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(via)}(?![A-Za-z0-9_])", registration_line
                )
                is None
            )
            if readable:
                found.append(
                    finding(
                        "account-scope.scoping-bypassed",
                        f"{label}: registered at "
                        f"{entry.get('registeredAt', {}).get('file')}:"
                        f"{entry.get('registeredAt', {}).get('line')}, which does not go "
                        f"through {via}",
                    )
                )

        line, problem = _line_at(repo, account_from)
        if line is None or not carries_key(line, spellings):
            found.append(
                finding(
                    "account-scope.account-key-lost",
                    f"{label}: accountFrom names "
                    f"{entry.get('accountFrom', {}).get('file')}:"
                    f"{entry.get('accountFrom', {}).get('line')}, which does not carry "
                    + (
                        f"any of {list(spellings)} ({problem})"
                        if problem
                        else f"any of {list(spellings)}"
                    ),
                )
            )
    return found


def _check_contradictions(
    repo: Path, points: list[Any], matched: dict[int, Registered]
) -> list[Finding]:
    rows = [
        (index, entry)
        for index, entry in enumerate(points)
        if isinstance(entry, dict) and entry.get("accountScoped") is False
    ]
    if not rows:
        return []

    resolvers = tuple(
        dict.fromkeys(
            entry["accountFrom"]["via"]
            for entry in points
            if isinstance(entry, dict)
            and isinstance(entry.get("accountFrom"), dict)
            and isinstance(entry["accountFrom"].get("via"), str)
        )
    )

    index = module_index(repo)
    found: list[Finding] = []
    unreachable: list[str] = []
    for row_index, entry in rows:
        label = entry.get("id") if isinstance(entry.get("id"), str) else "an entry point"
        verdict = contradiction(repo, entry, matched.get(row_index), index, resolvers)
        if verdict.evidence is not None:
            evidence = verdict.evidence
            found.append(
                finding(
                    "account-scope.declaration-contradicts-code",
                    f"{label} ({entry.get('method', '')} {entry.get('path', '')}) is "
                    f"declared accountScoped: false with reason {entry.get('reason')!r}, "
                    f"and {evidence.chain}: `{evidence.text}` — {evidence.kind} account "
                    f"evidence at {evidence.file}:{evidence.line}",
                )
            )
        elif verdict.row_gap is not None:
            found.append(
                finding(
                    "account-scope.contradiction-unreadable",
                    f"{label}: declared accountScoped: false and this checker could not "
                    f"read the code behind it — {verdict.row_gap}",
                )
            )
        unreachable.extend(verdict.unreachable)

    return (found, sorted(dict.fromkeys(unreachable)))


def _check_ids(points: list[Any]) -> list[Finding]:
    seen: set[str] = set()
    found: list[Finding] = []
    for entry in points:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        identifier = entry["id"]
        if identifier in seen:
            found.append(
                finding("account-scope.duplicate-id", f"{identifier} is declared more than once")
            )
        seen.add(identifier)
    return found


def _key_spellings(repo: Path, surface: dict[str, Any]) -> tuple[tuple[str, ...], bool]:
    declared = surface.get("accountKey")
    if isinstance(declared, str) and declared:
        return key_spellings(repo, declared), False
    tenancy = repo / "tenancy.yml"
    if tenancy.is_file():
        try:
            other = read_yaml(tenancy.read_text(encoding="utf-8"), tenancy)
        except (Refusal, OSError):
            other = None
        scope = other.get("scope") if isinstance(other, dict) else None
        key = scope.get("key") if isinstance(scope, dict) else None
        if isinstance(key, str) and key:
            return key_spellings(repo, key), False
    return KEY_SPELLINGS, True


def _check_service(repo: Path, declaration: dict[str, Any]) -> list[Finding]:
    tenancy = repo / "tenancy.yml"
    mine = declaration.get("service")
    if not tenancy.is_file() or not isinstance(mine, str):
        return []
    try:
        other = read_yaml(tenancy.read_text(encoding="utf-8"), tenancy)
    except (Refusal, OSError):
        return []
    theirs = other.get("service") if isinstance(other, dict) else None
    if isinstance(theirs, str) and theirs != mine:
        return [
            finding(
                "account-scope.service-disagrees",
                f"account_scope.yml says service {mine} and tenancy.yml says {theirs}",
            )
        ]
    return []




RESOLVED: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bassign\s*\(\s*\w+\s*,\s*:(?:current_)?(?:account|tenant)(?:_id)?\b"),
    re.compile(r"\.assigns\.(?:current_)?(?:account|tenant)(?:_id|_name)?\b"),
    re.compile(r"""\.\s*get\s*\(\s*["']principal["']\s*\)"""),
    re.compile(r"\.\s*get\s*\(\s*[\"'](?:current_)?(?:account|tenant)[\"']"),
    re.compile(
        r"\b(?:ctx|context|principal|claims|session|request|req|scopes?)\s*\.\s*"
        r"(?:current_)?(?:account|tenant)(?:_?id|ID|Id)?\b"
    ),
)

NAMED: tuple[re.Pattern[str], ...] = (
    re.compile(r"""\bparams\s*\[\s*["'](?:account|tenant)[_-]?(?:id|ID|Id)["']\s*\]"""),
    re.compile(r"""\b(?:path_params|query_params)\s*\.\s*(?:get|fetch)\s*\(\s*["'](?:account|tenant)[_-]?id["']"""),
    re.compile(r"""\.\s*re\.\s*query\s*\(\s*["'](?:account|tenant)[_-]?id["']"""),
    re.compile(r"\b(?:body|payload|params|query|input)\s*[.\[]\s*[\"']?(?:account|tenant)_?id[\"']?\s*[\]}]"),
)

HEREDOC = ('"""', "'''")

HASH_COMMENT_SUFFIXES = frozenset({".ex", ".exs", ".rb", ".py", ".rs", ".yml", ".yaml"})


def masked(text: str, suffix: str = "") -> list[str]:
    """The file's lines with every comment and docstring blanked out, in place.

    Line count and line numbers are preserved exactly, because every finding this
    module prints names a line and a finding whose line number moved because of the
    masking would be a finding about the wrong thing.

    What this is NOT is a tokenizer. A `//` or `#` inside a string literal is
    treated as a comment — the same simplification `strip_comment` makes and for
    the same stated reason — and the cost is one lost or one spurious match on one
    line, never a wrong verdict about a repository. A heredoc delimiter that opens
    on a line with code before it loses that code, which is a real loss: it is why
    the evidence patterns are written to match an ACT (an assignment, a read, a
    subscript) rather than a word.
    """
    blank = ""
    inside: str | None = None
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw
        if inside is not None:
            end = line.find(inside)
            lines.append(blank if end < 0 else blank * end + line[end + len(inside) :])
            if end >= 0:
                inside = None
            continue
        for opener in ("//",) + (("#",) if suffix in HASH_COMMENT_SUFFIXES else ()):
            at = line.find(opener)
            if at >= 0:
                line = line[:at] + blank * (len(line) - at)
        if line.lstrip().startswith(("/*", "*")):
            closer = line.find("*/")
            if closer < 0:
                lines.append(blank * len(line))
                inside = "*/"
                continue
            line = line[: line.find("/*")] + blank * (len(line) - line.find("/*"))
        for delimiter in HEREDOC:
            at = line.find(delimiter)
            if at >= 0:
                rest = line[at + len(delimiter) :]
                if delimiter in rest:
                    line = line[:at] + blank * (len(line) - at)
                    break
                line = line[:at] + blank * (len(line) - at)
                inside = delimiter
                break
        lines.append(line)
    return lines


def evidence_in(lines: list[str], skip: int = 0) -> tuple[str, int, str] | None:
    """`(kind, line number, the line)` for the first account evidence in MASKED code.

    `skip` leaves the first `skip` lines alone, which is how a definition line is
    excluded from its own body: naming the plug's `def` as the place the account is
    resolved would be pointing a reader at a function signature.
    """
    for number, line in enumerate(lines, start=1):
        if number <= skip:
            continue
        for pattern in RESOLVED:
            if pattern.search(line):
                return ("resolved", number, line.strip())
        for pattern in NAMED:
            if pattern.search(line):
                return ("named", number, line.strip())
    return None


@dataclass(frozen=True)
class Evidence:
    """One place the code shows an entry point reaches an account, and how it got there."""

    kind: str
    file: str
    line: int
    text: str
    chain: str


DEFINITION = (
    re.compile(r"^\s*(?:defmodule|defprotocol)\s+([A-Z][A-Za-z0-9_.]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?(?:class|interface|enum|struct|module|namespace)\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:type|record)\s+([A-Z][A-Za-z0-9_]*)\s+(?:struct|interface|\{)"),
    re.compile(r"^\s*def(?:p)?\s+([A-Z][A-Za-z0-9_]*)\s*[( ]"),
)

TEST_FILE = re.compile(r"(?:^|/).(?:[^/]*)(?:\.(?:test|spec)|_test|_spec|tests?)[^/]*$")

INDEX_SUFFIXES = frozenset({".go", ".ex", ".exs", ".ts", ".tsx", ".js", ".mjs", ".rs", ".rb", ".py"})


def module_index(repo: Path) -> dict[str, str]:
    """Every module this repository defines, and the file that defines it.

    One walk, one pass, built once per run and handed to every resolution below.
    A module in two files resolves to the lexicographically first, which is
    arbitrary and is recorded in the report as a hop that could not be trusted
    rather than silently preferred.
    """
    found: dict[str, str] = {}
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix not in INDEX_SUFFIXES:
            continue
        if SKIPPED & set(path.parts):
            continue
        relative = str(path.relative_to(repo))
        if TEST_FILE.search(relative):
            continue
        for line in source_lines(path):
            for pattern in DEFINITION:
                match = pattern.match(line)
                if match is not None:
                    found.setdefault(match.group(1), relative)
                    break
            else:
                continue
            break
    return found


def handler_for(repo: Path, registration: Registered, index: dict[str, str]) -> str | None:
    """The module or symbol a registration dispatches to, resolved to a FILE.

    Where the syntax puts the handler on the registration line — chi, Go 1.22,
    Hono — it is read off that line. Where it does not, the recogniser says so
    (`carries_handler` is False for Phoenix, axum and Next.js) and this is decided
    from the framework's own convention, resolved through the index rather than
    invented: a Phoenix route line is `get "/x", WebhookEndpointsController, :index`
    and the module is named on it.
    """
    line = strip_comment(source_lines(within(repo, registration.file))[registration.line - 1])
    if registration.recogniser == "phoenix":
        match = re.search(r"\"[^\"]*\"\s*,\s*([A-Z][A-Za-z0-9_.]*)", line)
        if match is None:
            return None
        return _phoenix_module(repo, registration.file, match.group(1), index)
    if registration.recogniser == "axum":
        match = re.search(r"\.(?:route|route_layer)\(.*?\b(?:get|post|put|patch|delete|head|options)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        return _file_defining(repo, index, match.group(1)) if match else None
    if registration.recogniser == "next-app":
        match = re.search(r"\bfunction\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", line)
        return registration.file if match else None
    found = _last_symbol(line)
    return _file_defining(repo, index, found) if found else None


def _phoenix_module(repo: Path, source: str, named: str, index: dict[str, str]) -> str | None:
    if "." in named and named in index:
        return index[named]
    router = ""
    for line in source_lines(within(repo, source)):
        found = re.match(r"^\s*defmodule\s+([A-Z][A-Za-z0-9_.]*)", line)
        if found is not None:
            router = found.group(1)
            break
    root = router.rsplit(".", 1)[0] if "." in router else router
    for candidate in (f"{root}.{named}", named):
        if candidate in index:
            return index[candidate]
    return None


def _last_symbol(line: str) -> str | None:
    for candidate in reversed(re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", line)):
        if candidate in ("HandleFunc", "Handle", "get", "post", "put", "patch", "delete", "head", "options"):
            continue
        return candidate
    return None


def _file_defining(repo: Path, index: dict[str, str], symbol: str) -> str | None:
    if symbol in index:
        return index[symbol]
    tail = symbol.rsplit(".", 1)[-1]
    if tail and tail != symbol:
        for path in sorted(repo.rglob("*")):
            if not path.is_file() or path.suffix not in INDEX_SUFFIXES:
                continue
            if SKIPPED & set(path.parts):
                continue
            relative = str(path.relative_to(repo))
            if TEST_FILE.search(relative):
                continue
            for line in source_lines(path):
                if re.search(rf"^\s*(?:def|func|fn|function|public|private|export)\b.*\b{re.escape(tail)}\b", line):
                    return relative
    return None



SCOPE = re.compile(r"^\s*scope\s+\"[^\"]*\"\s*,.*\bdo\s*$")
PIPE_THROUGH = re.compile(r"^\s*pipe_through\s+(.+?)\s*$")
PIPELINE = re.compile(r"^\s*pipeline\s+:([A-Za-z0-9_]+)\s+do\s*$")
PLUG = re.compile(r"^\s*plug\s+([A-Z][A-Za-z0-9_.]*)\b")
LOCAL_PLUG = re.compile(r"^\s*plug\s+:([A-Za-z0-9_]+)\b")
DEF_LOCAL = re.compile(r"^\s*defp?\s+([A-Za-z0-9_]+)\b")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _block(lines: list[str], start: int) -> range:
    depth = _indent(lines[start])
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > depth):
        end += 1
    return range(start + 1, end)


@dataclass(frozen=True)
class Verdict:
    """What the contradiction check concluded about one declared `false` row.

    Three fields and the split between the last two is the whole credibility
    argument:

      `evidence`   an account was resolved, at a file and a line. A FAILURE.
      `row_gap`    THIS row could not be checked — its registration did not match,
                   or its handler resolves to nothing in this repository. A
                   WARNING, because a row nobody read is not a row that passed.
      `unreachable` a plug or a pipeline this router names that resolves nowhere
                   here. NOT a row's fault and NOT reported per row: every Phoenix
                   router in existence plugs `:accepts`, so a finding per row would
                   fire on a hundred honest routes a day, and a check that warns
                   about correct code all morning is a check nobody reads by lunch.
                   Reported once, naming every symbol, because it is a fact about
                   the router and about this checker's reach — not about any row.
    """

    evidence: Evidence | None = None
    row_gap: str | None = None
    unreachable: tuple[str, ...] = ()


def pipeline_evidence(
    repo: Path, source: str, registration: Registered, index: dict[str, str]
) -> Verdict:
    """Follow a Phoenix registration's `scope` to its `pipe_through` to the plug.

    "I read the pipeline and no plug in it resolves an account" is a VERDICT and
    produces no finding. "The pipeline is not defined in this file" is a GAP and
    lands in `unreachable`. This is the layer that reaches courier's
    `MessagesController`: that file's own code names no account at all, and the
    account is put on the request by a plug two hops above the route.
    """
    lines = source_lines(within(repo, source))
    if registration.line - 1 >= len(lines):
        return Verdict(row_gap="the registration line is not in the file")
    code = masked("\n".join(lines), Path(source).suffix)
    at = registration.line - 1
    scope_at = next(
        (
            n
            for n in range(at, -1, -1)
            if SCOPE.match(code[n]) and _indent(code[n]) < _indent(code[at])
        ),
        None,
    )
    if scope_at is None:
        return Verdict(row_gap="the registration is not inside a scope this checker can read")
    unreachable: list[str] = []
    pipes = 0
    for number in _block(code, scope_at):
        match = PIPE_THROUGH.match(code[number])
        if match is None:
            continue
        for name in re.findall(r":([A-Za-z0-9_]+)", match.group(1)):
            pipes += 1
            head = next(
                (
                    n
                    for n, line in enumerate(code)
                    if PIPELINE.match(line) and PIPELINE.match(line).group(1) == name
                ),
                None,
            )
            if head is None:
                unreachable.append(f"pipeline :{name} is not defined in {source}")
                continue
            for inner in _block(code, head):
                plug = PLUG.match(code[inner]) or LOCAL_PLUG.match(code[inner])
                if plug is None:
                    continue
                found, why = _plug_evidence(repo, source, code, plug.group(1), index)
                if found is not None:
                    return Verdict(evidence=found)
                if why is not None:
                    unreachable.append(why)
    if pipes == 0:
        return Verdict(row_gap="the scope pipes through nothing this checker can read")
    return Verdict(unreachable=tuple(unreachable))


def _plug_evidence(
    repo: Path, source: str, code: list[str], name: str, index: dict[str, str]
) -> tuple[Evidence | None, str | None]:
    target = index.get(name)
    if target is None:
        defined = next(
            (
                n
                for n, line in enumerate(code)
                if DEF_LOCAL.match(line) and DEF_LOCAL.match(line).group(1) == name
            ),
            None,
        )
        if defined is None:
            return (None, f"plug {name}, which is not defined in this repository")
        span = _block(code, defined)
        body = code[: span.start] + [""] * (span.stop - span.start) + code[span.stop :]
        found = evidence_in(body, skip=span.start)
        if found is None:
            return (None, None)
        kind, number, text = found
        return (
            Evidence(
                kind=kind,
                file=source,
                line=number,
                text=text,
                chain=f"the scope pipes through {name}, and {source}:{number} resolves an account",
            ),
            None,
        )
    found = evidence_in(
        masked("\n".join(source_lines(within(repo, target))), Path(target).suffix)
    )
    if found is None:
        return (None, None)
    kind, number, text = found
    return (
        Evidence(
            kind=kind,
            file=target,
            line=number,
            text=text,
            chain=f"the scope pipes through {name}, and {target}:{number} resolves an account",
        ),
        None,
    )


def contradiction(
    repo: Path,
    entry: Any,
    registration: Registered | None,
    index: dict[str, str],
    resolvers: tuple[str, ...],
) -> Verdict:
    """One `accountScoped: false` row against the code it claims to describe.

    Layers, strongest first; the first that produces evidence wins:

      RESOLVER ON THE LINE   the registration line carries the symbol this
                            declaration itself uses to name an account resolver on
                            another row. The service's own vocabulary, so there is
                            no list of names this checker chose and can be wrong
                            about.
      PIPELINE               a Phoenix `scope`'s `pipe_through` reaches a plug
                            whose code resolves an account.
      HANDLER                the handler's own masked code resolves an account, or
                            lets the caller name one.
      ONE HOP                the handler delegates to a module in this repository
                            and THAT resolves an account.
    """
    if not isinstance(entry, dict) or entry.get("accountScoped") is not False:
        return Verdict()
    if registration is None:
        return Verdict(row_gap="no registration on the declared surface matched this row")

    if resolvers:
        lines = source_lines(within(repo, registration.file))
        line = lines[registration.line - 1] if registration.line - 1 < len(lines) else ""
        masked_line = masked(line, Path(registration.file).suffix)
        code = masked_line[0] if masked_line else ""
        for name in resolvers:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", code):
                return Verdict(
                    evidence=Evidence(
                        kind="resolver",
                        file=registration.file,
                        line=registration.line,
                        text=line.strip(),
                        chain=(
                            f"the registration goes through {name}, which this declaration "
                            "itself names as an account resolver"
                        ),
                    )
                )

    lines = source_lines(within(repo, registration.file))
    if 0 < registration.line <= len(lines):
        masked_line = masked(lines[registration.line - 1], Path(registration.file).suffix)
        here = evidence_in(masked_line)
        if here is not None and here[0] == "resolved":
            kind, _number, text = here
            return Verdict(
                evidence=Evidence(
                    kind=kind,
                    file=registration.file,
                    line=registration.line,
                    text=text,
                    chain=(
                        "the registration line itself resolves an account, in an inline "
                        "handler — the framework puts the whole handler here"
                    ),
                )
            )

    unreadable: tuple[str, ...] = ()
    if registration.recogniser == "phoenix":
        verdict = pipeline_evidence(repo, registration.file, registration, index)
        if verdict.evidence is not None:
            return verdict
        unreadable = verdict.unreachable

    target = handler_for(repo, registration, index)
    if target is None:
        return Verdict(
            row_gap="the handler could not be resolved to a file in this repository",
            unreachable=unreadable,
        )
    for relative in [target] + _hops(repo, target, index):
        found = evidence_in(
            masked("\n".join(source_lines(within(repo, relative))), Path(relative).suffix)
        )
        if found is not None:
            kind, number, text = found
            where = (
                "the handler" if relative == target else "a module the handler delegates to"
            )
            return Verdict(
                evidence=Evidence(
                    kind=kind,
                    file=relative,
                    line=number,
                    text=text,
                    chain=f"{where} resolves an account at {relative}:{number}",
                ),
                unreachable=unreadable,
            )
    return Verdict(unreachable=unreadable)


HOP = (
    re.compile(r"^\s*(?:alias|import|use)\s+([A-Z][A-Za-z0-9_]*(?:\.[A-Z][A-Za-z0-9_]*)*)"),
    re.compile(r"""^\s*import\s+(?:type\s+)?(?:\{[^}]*\}|[\w*]+)\s+from\s+["']([^"']+)["']"""),
)


def _hops(repo: Path, source: str, index: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen = {source}
    for line in masked(
        "\n".join(source_lines(within(repo, source))), Path(source).suffix
    ):
        for pattern in HOP:
            match = pattern.match(line)
            if match is None:
                continue
            resolved = index.get(match.group(1))
            if resolved is None and pattern is HOP[1]:
                base = within(repo, source).parent
                for suffix in ("", ".ts", ".tsx", ".js", ".ex", ".go", ".py"):
                    candidate = base / (match.group(1) + suffix)
                    if candidate.is_file():
                        resolved = str(candidate.relative_to(repo.resolve()))
                        break
            if resolved is not None and resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
            break
        if len(out) >= 4:
            break
    return out




def to_json(report: Report) -> str:
    return json.dumps(
        {
            "repo": str(report.repo),
            "exitCode": report.exit_code,
            "couldNotRun": report.could_not_run,
            "notVerified": report.unverified,
            "counts": report.counts,
            "entryPoints": report.entry_points,
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
        prog="account-scope-check",
        description="Check a service's account-scoped entry-point declaration against that service.",
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

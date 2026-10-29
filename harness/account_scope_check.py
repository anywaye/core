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
    "account-scope.registration-commented": (
        "fail",
        "the line a declaration row points at still NAMES the route and every mention of it "
        "is inside a comment, so the entry point is not mounted. This is not `undeclared` "
        "and it is not `stale`, and it is a failure rather than a warning because it is the "
        "one shape where the declaration and the file agree about a route that does not "
        "exist: a refactor commented the registration out, left the row, and the file still "
        "prints `r.Get(\"/healthz\", handleHealthz)` on the exact line `registeredAt` names. "
        "A reader skimming the file believes it as readily as the checker used to, so a "
        "checker that reads the comment and moves on reports a deleted route as a mounted "
        "one with a file and a line and exits 0.",
        "make that line register the route again — uncomment it, or delete the row if the "
        "entry point really is gone, and NOT by pointing `registeredAt` somewhere else: "
        "this line names the route and registers nothing, so there is no such line",
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
    "account-scope.surface-unreadable": (
        "warn",
        "a file `surface.sources` names registers routes whose PATH this checker cannot "
        "evaluate — the path argument is an expression rather than a string literal, so "
        "there is no path to read. They are counted neither as found nor as missing, so "
        "`undeclared` reads 0 over a surface this checker saw NONE of, and a reader "
        "takes that zero for coverage. It is the opposite. This is courier's "
        "`contradiction-unreadable` restated for a surface rather than for a row: a "
        "checker that cannot resolve a thing says so rather than reporting a count.",
        "make the path a literal at the registration, or say in a comment on each row "
        "the prefix hides what it is — and do NOT resolve it by looking up a default: "
        "`pantry`'s `options.BaseURL` is deployment configuration, and a default that "
        "happens to match a development compose file is a guess about a deployment, "
        "made by a checker that cannot see one",
    ),
    "account-scope.registration-path-unreadable": (
        "warn",
        "a declared entry point's `registeredAt` names a line that DOES register its "
        "route, and the path on that line is an expression this checker cannot evaluate. "
        "The row is mounted and unverified, which is not `stale`: `stale` claims the "
        "route is gone and it is here. Reporting a mounted route as not mounted is the "
        "wolf this file's `notEnforced` list exists to prevent, and it is a FAILURE — so "
        "a correct declaration behind an unevaluable prefix read exit 1 on `pantry` for "
        "a defect in the checker rather than in the service.",
        "read the path off the registration and check the row against it — this finding "
        "is about what this checker could not do, and there is nothing to fix in the "
        "declaration that would make it go away",
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
    chain_read: bool = True
    path_from_filename: bool = False
    concatenates: bool = False

    def match_all(self, line: str, relative: str = "") -> list[tuple[str, str]]:
        """Every `(method, path fragment)` on this line, in order.

        `match_all` rather than a single match because axum CHAINS: a router is
        built as `Router::new().route("/a", get(h)).route("/b", get(h2))`, and a
        `search` returning the first hit would see one route where there are two —
        so a correctly declared route is reported `undeclared` because its
        registration shared a line with another one. Silent on every fixture core
        ships, because each of those lines registers exactly one route.
        """
        return [
            found
            for found in (self._match_one(hit, line, relative) for hit in self.pattern.finditer(line))
            if found is not None
        ]

    def match(self, line: str, relative: str = "") -> tuple[str, str] | None:
        """The first `(method, path fragment)` on this line, or nothing."""
        matches = self.match_all(line, relative)
        return matches[0] if matches else None

    def _match_one(
        self, hit: re.Match[str], line: str, relative: str
    ) -> tuple[str, str] | None:
        groups = hit.groupdict()
        verb = groups.get("verb")
        path = groups.get("path")

        if self.path_from_filename:
            if verb is None:
                return None
            resolved = route_path_from_filename(relative)
            return None if resolved == "/" else (verb.upper(), resolved)

        if path is None:
            return ("ANY", groups["anypath"]) if groups.get("anypath") is not None else None

        if self.concatenates and verb is not None:
            joined = concatenated_path(line[hit.start() :])
            if joined is not None:
                path = joined
        if verb is None and self.verb_from_handler is not None:
            handler = self.verb_from_handler.search(line, hit.end())
            verb = handler.group(0) if handler is not None else "ANY"
        if verb is None:
            return None
        return verb.upper(), path


RECOGNISERS: tuple[Recogniser, ...] = (
    Recogniser(
        id="chi",
        framework="net/http chi",
        read_from="identity/internal/httpapi/accounts.go:590",
        pattern=re.compile(
            r"\.(?:(?P<verb>Get|Post|Put|Patch|Delete|Head|Options|Connect|Trace)"
            r'\(\s*"(?P<path>/[^"]*)"'
            r'(?:\s*\+\s*(?:"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*))*\s*,'
            r'|(?:Handle|HandleFunc)\(\s*"(?P<anypath>/[^"]*)"'
            r")"
        ),
        example='r.Get("/v1/accounts/{accountID}", o.requireAccountRole(accounts.RoleMember, o.handleGetAccount))',
        concatenates=True,
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
        chain_read=False,
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
        chain_read=False,
        path_from_filename=True,
    ),
    Recogniser(
        id="axum",
        framework="axum",
        read_from="pantry/src/http.rs:99",
        pattern=re.compile(r"\.route\(\s*\"(?P<path>/[^\"]*)\""),
        verb_from_handler=re.compile(r"\b(get|post|put|patch|delete|head|options)\b(?=\s*\()"),
        example='.route("/v1/services", get(list_services))',
        carries_handler=False,
        chain_read=False,
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
        for verb, path in recogniser.match_all(line, relative):
            found.append((verb, path, recogniser.id))
    return found


HANDLER_WINDOW = 3

COMMENT = re.compile(r"//|#")


def strip_comment(line: str) -> str:
    """The line with its trailing comment removed, at the first `//` or `#`.

    Not a full tokenizer, and it does not need to be: a `#` or `//` inside a route
    literal would be inside quotes at a position no recogniser matches, and the
    cost of being wrong about a line is one extra or one missing finding, not a
    wrong verdict on the repository.

    **THE comment seam, and every read of a source line for a match goes through
    it.** That is stated here rather than left to discipline because the two halves
    of this checker once read the same line two different ways: `discover` asked the
    stripped line, `_check_entry` asked the raw one, and the two disagreed about
    whether a registration existed. The disagreement had a direction, and it was the
    wrong one — the surface walk's answer was right and the row check's answer won,
    because the row check is what decides whether a row is `stale`. So a refactor
    that commented a route out produced a declaration the checker called mounted,
    a summary that said so with a file and a line, and exit 0. `line_registrations`
    is the same rule for the question callers actually ask; nothing else in this
    file is allowed to strip a comment by hand.
    """
    found = COMMENT.search(line)
    return line if found is None else line[: found.start()]


def line_registrations(line: str, relative: str = "") -> list[tuple[str, str, str]]:
    """Every `(method, path fragment, recogniser)` this line ACTUALLY registers.

    The seam, as a function rather than a convention, and for `strip_comment`'s
    reason: two callers of one function cannot disagree, and the two callers that
    used to disagree — the surface walk and the per-row check — are the two halves
    of one question ("does this source line mount a route?"). Called by both.
    """
    return registrations(strip_comment(line), relative)


CONCATENATED_PATH = re.compile(r'"(?P<first>/[^"]*)"((?:\s*\+\s*(?:"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*))*)')


def concatenated_path(text: str) -> str | None:
    """A Go path literal with its concatenation resolved to `{}` for each term."""
    found = CONCATENATED_PATH.search(text)
    if found is None:
        return None
    pieces = [found.group("first")]
    for term in re.findall(r'"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*', found.group(2)):
        pieces.append(term[1:-1] if term.startswith('"') else "{}")
    return "".join(pieces)


ROUTE_CALL = re.compile(
    r"\.\s*(?P<verb>Get|Post|Put|Patch|Delete|Head|Options|Connect|Trace|Mount"
    r"|Handle|HandleFunc)\s*\("
)

STRING_LITERAL = re.compile(r'"[^"]*"')

QUOTES = ('"', "'", "`")


def _first_argument(text: str) -> str:
    depth = 0
    quoted = ""
    out: list[str] = []
    position = 0
    while position < len(text):
        char = text[position]
        if quoted:
            if char == quoted:
                quoted = ""
        elif char in QUOTES:
            quoted = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            break
        out.append(char)
        position += 1
    return "".join(out)


def unreadable_registrations(line: str) -> list[str]:
    """The verbs of the route calls on this line whose path this checker cannot read.

    Three answers, and only the middle one is this finding:

    - a path that BEGINS with a string literal is readable. `RECOGNISERS` owns it, and
      `concatenated_path` has already named every unreadable term in the REST of it
      `{}` — the existing convention, and not changed here.
    - an EXPRESSION carrying a string literal is the finding: `options.BaseURL` plus
      `"/v1/services"` is a real route with a head nobody can evaluate.
    - an expression carrying NO string literal is neither. `pattern` and
      `o.panicOnRoute` are a helper mounting a path it was handed and a test route;
      they are not a path written in a shape this checker can half-read, and counting
      them would put this warning on correct code — which is what `notEnforced` in
      `harness/account_scope_findings.json` records, with the count.

    Returns VERBS, not paths, for the reason at the section header: there is no path
    to return.
    """
    verbs: list[str] = []
    for hit in ROUTE_CALL.finditer(line):
        argument = _first_argument(line[hit.end() :]).strip()
        if not argument or argument.startswith(QUOTES):
            continue
        if STRING_LITERAL.search(argument):
            verbs.append(hit.group("verb"))
    return verbs


MIDDLEWARE = re.compile(
    r"\b(?:app|router|api|r|server)\.use\(\s*[\"'`](?P<path>/[^\"'`]*)[\"'`]\s*,"
    r"(?P<handler>[^;]*)"
)


def mount_covers(text: str, path: str) -> tuple[bool, bool]:
    """`(covers, decided)` — does this mount's pattern cover this route, and could
    this checker decide it?

    THE THREE PATTERNS HONO DOCUMENTS for a subtree, plus the exact path. Anything
    else — a `*` in the middle, a RegExp, a trailing `:param` — is `(False, False)`:
    not covered AND NOT DECIDED, and the two are kept apart because they are two
    different answers. `decided` False means the caller must not read the absence of
    a gate as the absence of a gate, so the row stays reported as unreadable rather
    than as covered or as bare. The alternative — evaluating nothing and calling it
    "does not cover" — is how a `use` that matches nothing becomes the gate for every
    route in the file.

    `/v1/*` over `/v1/me` is the case that decided it, and it is gateway's own: the
    prefix is COMPARED, because a `/v1/*` mount clearing a `/v2` route is a false
    green with a real gate standing behind it (self-test case 39, and case 42 for
    the proof that the comparison is what stops it).
    """
    pattern = canonical(text)
    if pattern in ("/", "/*"):
        return True, True
    if text.endswith("/*"):
        prefix = canonical(text[:-2].rstrip("/"))
        return canonical(path).startswith(prefix.rstrip("/") + "/"), True
    if "*" in text:
        return False, False
    return pattern == canonical(path), True


def inline_handler(handler: str) -> bool:
    """Whether a mount's middleware is written HERE rather than named from elsewhere.

    `async (c, next) => {`, `(c, next) => limiter(c, next)` and `function (c, next)
    {` are this file's own text and what they do is readable. A bare identifier —
    `api.use("/*", accountGate)` — is a symbol, and resolving its type is a second
    resolution this file does not make. The honest answer to that is "I cannot see
    it", which is `composed`, and NOT "the route is unscoped".
    """
    text = handler.strip()
    return text.startswith(("(", "async", "function"))


@dataclass(frozen=True)
class Chain:
    """What this checker could read about the chain in FRONT of one registration.

    Two booleans and one line, and the booleans are two DIFFERENT questions — which
    is why this is a structure rather than one `readable` flag:

      `covers`    a mount ABOVE this route covers its path and names `via`, so the
                  route really is scoped through it. gateway's `/v1/me`, and the whole
                  of what this exists for.
      `composed`  a mount above it covers the route and names a middleware DEFINED
                  IN ANOTHER MODULE. What that middleware does is not in this file,
                  the chain cannot be followed, and the route is NOT called
                  unscoped — which is `Recogniser.carries_handler`'s own refusal
                  restated for a chain that left the file, and the alternative is
                  the wolf `hono_composed` exists to keep out of the output.
      `at`        the NEAREST covering mount's line, so a reader asking where the
                  gate is has an answer. Nothing here decides on it.
    """

    covers: bool = False
    composed: bool = False
    at: int | None = None


def chain_gate(repo: Path, where: str, at: Any, path: str, via: re.Pattern[str]) -> Chain:
    """The `app.use` mounts registered ABOVE line `at` that cover `path`.

    ABOVE, and only above, because registration order is the whole of the reason a
    `use` is in front of a route at all: gateway's own file says a limiter mounted
    after a route is a limiter that does not run, and a checker that accepted a
    mount from anywhere in the file would be wrong about exactly that.

    ONE FILE, and only the file the row names, because a `use` needs the `app`
    instance and the file holding it is the file the routes are in. A service that
    mounts its gate in a helper which takes `app` is in `notEnforced` with its
    numbers rather than guessed at.

    NEAREST first, by iterating downwards, so `at` names the gate a reader would
    look at and an unreadable mount does not shadow a readable one further up.
    """
    if not isinstance(at, int):
        return Chain()
    try:
        lines = source_lines(within(repo, where))
    except (ValueError, OSError):  # pragma: no cover - `where` was checked already
        return Chain()
    composed = False
    nearest: int | None = None
    for number in reversed(range(1, at)):
        if number > len(lines):
            continue
        for mount in MIDDLEWARE.finditer(strip_comment(lines[number - 1])):
            covers, decided = mount_covers(mount.group("path"), path)
            if not (covers and decided):
                continue
            if nearest is None:
                nearest = number
            window = "\n".join(
                strip_comment(text) for text in lines[number - 1 : number + HANDLER_WINDOW]
            )
            if via.search(window) is not None:
                return Chain(covers=True, at=number)
            if not inline_handler(mount.group("handler")):
                composed = True
    return Chain(composed=composed, at=nearest)


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
    unreadable: int = 0

    def of(self, severity: str) -> list[Finding]:
        return [item for item in self.findings if item.severity == severity]

    @property
    def counts(self) -> dict[str, int]:
        states = {
            "account-scoped": 0,
            "not-account-scoped": 0,
            "stale": 0,
            "undeclared": 0,
        }
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
            f"{counts['stale']} stale, "
            f"{counts['undeclared']} undeclared, "
            f"{self.unreadable} unreadable — {failed} failure(s), {warned} warning(s)"
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


@dataclass(frozen=True)
class Unreadable:
    """One registration call whose PATH this checker could not evaluate, and where.

    `verb` and `file` and `line` and nothing else. The absence of a path IS the
    finding, so a field here that held one would be the guess this whole section
    refuses to make — and `Surface.unreadable` is counted separately from
    `Surface.found` for the same reason, because folding the two together is how
    `surface.minimum` stops being a decrease-detector.
    """

    verb: str
    file: str
    line: int


@dataclass(frozen=True)
class Surface:
    """What one walk of `surface.sources` produced, in FOUR collections and not three.

    A named structure rather than a tuple for `Contradictions`' reason, which is the
    one this file has already paid for once: a 3-tuple is unpacked at the call site
    and nowhere else, so an early return of two values and a late return of three can
    both typecheck on one side of the file and disagree with the other. Every field
    defaults to empty so the "nothing to read" path cannot return a different shape
    from the "read everything" path.

    The fourth field is the one this packet is about. It was not a field: a route
    whose path is an expression returned nothing at all, so it was counted as absent
    from `found` and nothing anywhere recorded that it had been seen. `missing` is a
    list of paths the DECLARATION named and the disk did not have — an error. There
    was no collection for a registration the disk had and this checker could not
    evaluate, which is a different thing with a different remedy, and conflating it
    with `found` is what made `0 undeclared` mean "nothing to find" as well as
    "nothing to declare".
    """

    found: tuple[Registered, ...] = ()
    problems: tuple[Finding, ...] = ()
    missing: tuple[str, ...] = ()
    unreadable: tuple[Unreadable, ...] = ()

    def __len__(self) -> int:
        return len(self.found)


def discover(repo: Path, sources: list[str]) -> Surface:
    """Read the declared sources and return what they register.

    ONE walk, and it answers two questions per line, because the two halves of this
    checker once read the same line two different ways and the disagreement had a
    direction: `discover` asked the stripped line, `_check_entry` asked the raw one,
    and the row check won because the row check is what decides `stale`. So
    `line_registrations` is asked both questions here — "what does this line
    register" and "does this line register something whose path I cannot read" — and
    both answers come out of the same stripped line, computed once.

    A source that is not on disk is a FAILURE (`surface-missing`) rather than a file
    skipped in silence, and the list of missing paths is returned so the caller can
    say which.
    """
    found: list[Registered] = []
    problems: list[Finding] = []
    missing: list[str] = []
    unreadable: list[Unreadable] = []
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
                code = strip_comment(line)
                for method, fragment, recogniser in registrations(code, relative):
                    found.append(
                        Registered(
                            method=method,
                            path=fragment,
                            recogniser=recogniser,
                            file=relative,
                            line=number,
                        )
                    )
                for verb in unreadable_registrations(code):
                    unreadable.append(Unreadable(verb=verb, file=relative, line=number))
    return Surface(tuple(found), tuple(problems), tuple(missing), tuple(unreadable))


def surface_findings(scan: Surface) -> list[Finding]:
    """One `surface-unreadable` per source file that mounts unreadable paths.

    Per FILE and not per route, and the reason is the number of lines. pantry's four
    registrations are four rows in one file; printing four findings for them would
    make the one thing this warning has to say — *this checker read none of the
    surface you declared* — the fourth copy of itself, and a warning repeated four
    times is a warning a reader scrolls past. The lines are in the message instead, so
    nothing is lost.

    It is a `warn` and never a `fail`, and that is `Report.exit_code`'s own rule
    rather than a courtesy: this is "this machine cannot answer that question", and
    core's tenancy check refused to make that a failure for exactly the reason that
    failing on it gets the checker switched off — which would leave the fleet with no
    boundary check instead of an incomplete one. What it buys instead of a failure is
    the count on the summary line, which is the thing a reader who sees only the last
    line was never getting.
    """
    by_source: dict[str, list[Unreadable]] = {}
    for item in scan.unreadable:
        by_source.setdefault(item.file, []).append(item)
    found: list[Finding] = []
    for source, rows in sorted(by_source.items()):
        at = ", ".join(str(item.line) for item in rows)
        read = len(scan.found)
        verbs = sorted({item.verb for item in rows})
        found.append(
            finding(
                "account-scope.surface-unreadable",
                f"{source} mounts {len(rows)} registration(s) — {', '.join(verbs)} — whose "
                f"path this checker cannot evaluate, because the path argument is an "
                f"expression rather than a string literal (line(s) {at}). {read} of the "
                f"{read + len(scan.unreadable)} registration(s) in surface.sources were "
                f"read, so the `undeclared` and surface.minimum numbers below are "
                f"decided over the ones that were, not over this surface",
            )
        )
    return found


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
        scan = Surface()
    else:
        scan = discover(repo, sources)
        report.findings.extend(scan.problems)

    report.unreadable = len(scan.unreadable)
    report.findings.extend(surface_findings(scan))

    minimum = surface.get("minimum")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(scan.found) < minimum:
        unreachable = (
            f" — and {len(scan.unreadable)} further registration(s) in those sources could "
            "not be read at all, so this floor is not being violated, it is unfalsifiable"
            if scan.unreadable
            else ""
        )
        report.findings.append(
            finding(
                "account-scope.surface-thin",
                f"the declared sources register {len(scan.found)} entry point(s) and "
                f"surface.minimum is {minimum}{unreachable}",
            )
        )

    claims = claims_at(repo, points)
    report.entry_points, unmatched, matched = classify(repo, points, scan.found, claims)
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

    contradictions = _check_contradictions(repo, points, matched, claims)
    report.findings.extend(contradictions.findings)
    report.unverified.extend(contradictions.unverified)

    spellings, guessed = _key_spellings(repo, surface)
    if guessed:
        report.findings.append(
            finding(
                "account-scope.scope-key-guessed",
                "neither surface.accountKey nor tenancy.yml's scope.key names the tenancy key, "
                f"so the account lines were searched for in {list(KEY_SPELLINGS)}",
            )
        )
    for entry, claim in zip(points, claims):
        report.findings.extend(_check_entry(repo, entry, spellings, claim))

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
    repo: Path,
    points: list[Any],
    surface_found: list[Registered],
    claims: list[Claim],
) -> tuple[list[dict[str, Any]], list[Registered], dict[int, Registered]]:
    """Per entry point: account-scoped, not-account-scoped, stale, or — the finding
    — undeclared. Returns the classified rows, the registrations nothing claimed, and
    which registration each row matched.

    `claims` is what keeps the listing from lying. A row is printed as a mounted
    route or it is not, and the declaration's word for where it is mounted is
    `registeredAt` — so a row whose `registeredAt` line registers nothing is
    printed `stale` whatever the route table believed about it. `claims` is the
    SAME answer `_check_entry` reports a finding from, passed in rather than
    recomputed, because a summary that disagrees with the findings about whether a
    route exists is worse than no summary: it is read. The classification is a
    decision about two lists and about that one claim; the disk is not consulted
    again here.

    The third value is new and the contradiction check needs
    it: `accountScoped: false` is only checkable against the registration its row
    matched, because a row whose route the checker cannot find on the declared
    surface is a row it did not verify — `stale` already says so, and saying it
    from two directions is the point.
    """
    rows: list[dict[str, Any]] = []
    taken: set[int] = set()
    matched: dict[int, Registered] = {}
    for position, entry in enumerate(points):
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
            if position < len(claims) and claims[position].verdict in STALE_VERDICTS:
                state = STATE_STALE
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


VERDICT_REGISTERED = "registered"
VERDICT_MOVED = "moved"
VERDICT_COMMENTED = "commented"
VERDICT_UNREADABLE = "unreadable"
VERDICT_PATH_UNREADABLE = "path-unreadable"

STALE_VERDICTS = frozenset({VERDICT_MOVED, VERDICT_COMMENTED, VERDICT_UNREADABLE})

STATE_STALE = "stale"


@dataclass(frozen=True)
class Claim:
    """One declared row's `registeredAt`, and what the line there says about it.

    `code` is the line with its trailing comment removed — the seam, once, so the
    finding and the listing cannot be computed from different readings of the same
    line. `raw` is the line as written, kept for DIAGNOSIS only: it decides whether
    a missing route is `MOVED` or `COMMENTED`, and it is never allowed to decide
    that a route exists. That asymmetry is the fix. `problem` is set only for
    `UNREADABLE`, and it is `stale`'s own reason to print.
    """

    verdict: str
    code: str
    raw: str
    problem: str | None


def _mentions_on(entry: dict[str, Any], text: str, relative: str) -> bool:
    if entry.get("kind") != "http":
        name = entry.get("name")
        return isinstance(name, str) and name in text
    path = entry.get("path")
    if not isinstance(path, str):
        return False
    method = entry.get("method", "ANY")
    return any(
        same_route(method, path, found_method, found_path)
        for found_method, found_path, _recogniser in line_registrations(text, relative)
    ) or canonical(path).split("/")[-1] in text


def claims_at(repo: Path, points: list[Any]) -> list[Claim]:
    """One `Claim` per declared row, in declaration order — the disk read ONCE.

    Returned rather than recomputed at each use because the finding and the summary
    listing must agree about whether a row is still mounted, and the defect this
    replaces was exactly that disagreement arriving by two routes. `position` indexes
    this list directly, so it is aligned with `points` and not with the rows that
    survive `isinstance` filtering in `classify`.
    """
    claims: list[Claim] = []
    for entry in points:
        if not isinstance(entry, dict):
            claims.append(Claim(VERDICT_UNREADABLE, "", "", "the entry point is not a mapping"))
            continue
        line, problem = _line_at(repo, entry.get("registeredAt"))
        if line is None:
            claims.append(
                Claim(VERDICT_UNREADABLE, "", "", problem or "registeredAt names no line")
            )
            continue
        code = strip_comment(line)
        relative = ""
        registered = entry.get("registeredAt")
        if isinstance(registered, dict) and isinstance(registered.get("file"), str):
            relative = registered["file"]
        if _mentions_on(entry, code, relative):
            claims.append(Claim(VERDICT_REGISTERED, code, line, None))
        elif _mentions_on(entry, line, relative):
            claims.append(Claim(VERDICT_COMMENTED, code, line, None))
        elif unreadable_registrations(code):
            claims.append(Claim(VERDICT_PATH_UNREADABLE, code, line, None))
        else:
            claims.append(Claim(VERDICT_MOVED, code, line, None))
    return claims


def registration_findings(label: str, entry: Any, claim: Claim) -> list[Finding]:
    """The failure, if any, about the line this row says its route is mounted on.

    One question with three answers and one finding each, which is why it is its
    own function rather than three branches inside `_check_entry`: the summary
    listing needs the same question answered the same way, and one function that
    answers it is what makes the two agree. `harness/tests/account_scope_self_test.sh`
    case 28 deletes the call to this from a throwaway copy of the checker and
    requires a repository with a deleted route to go GREEN, so the check cannot be
    satisfied by the floor or by anything already there.
    """
    if not isinstance(entry, dict):
        return []
    registered = entry.get("registeredAt")
    where = ""
    if isinstance(registered, dict) and isinstance(registered.get("file"), str):
        where = f"{registered['file']}:{registered.get('line')}"
    if claim.verdict == VERDICT_UNREADABLE:
        return [
            finding(
                "account-scope.stale",
                f"{label}: registeredAt names nothing on disk ({claim.problem})",
            )
        ]
    if claim.verdict == VERDICT_COMMENTED:
        return [
            finding(
                "account-scope.registration-commented",
                f"{label}: registeredAt points at {where}, which is a comment naming "
                f"{_names(entry)} rather than a line that registers it — the entry point "
                "is not mounted",
            )
        ]
    if claim.verdict == VERDICT_MOVED:
        return [
            finding(
                "account-scope.stale",
                f"{label}: registeredAt points at a line that does not register it: {where}",
            )
        ]
    if claim.verdict == VERDICT_PATH_UNREADABLE:
        return [
            finding(
                "account-scope.registration-path-unreadable",
                f"{label}: registeredAt points at {where}, which DOES register a route — "
                "and its path is an expression this checker cannot evaluate, so the row "
                "is mounted and unverified rather than stale",
            )
        ]
    return []


def _names(entry: dict[str, Any]) -> str:
    path = entry.get("path")
    name = entry.get("name")
    if isinstance(path, str) and path:
        return path
    if isinstance(name, str) and name:
        return name
    return "this entry point"


def _check_entry(
    repo: Path, entry: Any, spellings: tuple[str, ...], claim: Claim
) -> list[Finding]:
    if not isinstance(entry, dict):
        return []
    found: list[Finding] = []
    label = entry.get("id") if isinstance(entry.get("id"), str) else "an entry point"

    found.extend(registration_findings(label, entry, claim))

    if entry.get("accountScoped") is True:
        account_from = entry.get("accountFrom")
        via = account_from.get("via") if isinstance(account_from, dict) else None

        if isinstance(via, str) and isinstance(account_from, dict):
            named = account_from.get("file")
            whole = source_lines(within(repo, named)) if isinstance(named, str) else []
            via_pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(via)}(?![A-Za-z0-9_])")
            if not any(via_pattern.search(text) for text in whole):
                found.append(
                    finding(
                        "account-scope.account-key-lost",
                        f"{label}: accountFrom names {via}, which does not appear in {named}",
                    )
                )
            reachable = claim.code
            registered = entry.get("registeredAt")
            where = registered.get("file") if isinstance(registered, dict) else ""
            at = registered.get("line") if isinstance(registered, dict) else None
            if isinstance(registered, dict) and isinstance(registered.get("file"), str):
                whole = source_lines(within(repo, registered["file"]))
                start = registered.get("line")
                if isinstance(start, int):
                    reachable = "\n".join(
                        strip_comment(text) for text in whole[start - 1 : start + HANDLER_WINDOW]
                    )
            matching = [
                candidate
                for candidate in RECOGNISERS
                if candidate.match(claim.code) is not None
            ]
            handler_is_readable = claim.verdict == VERDICT_REGISTERED and any(
                candidate.carries_handler for candidate in matching
            )
            chain_read = any(candidate.chain_read for candidate in matching)
            on_line = via_pattern.search(reachable) is not None
            chain = (
                chain_gate(
                    repo,
                    where,
                    at,
                    matching[0].match(claim.code)[1] if matching else "",
                    via_pattern,
                )
                if handler_is_readable
                else Chain()
            )
            in_chain = chain.covers
            composed = chain.composed
            readable = not composed
            if readable and handler_is_readable and chain_read and not (on_line or in_chain):
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


@dataclass(frozen=True)
class Contradictions:
    """What one run of the contradiction check produced: the findings, and the rest.

    Two collections that used to be a bare 2-tuple, which is the shape that let a
    merge pair a one-value definition with a two-value caller without a textual
    conflict. Named, because a name is a claim a reader and a checker can both
    look at; positional, because every consumer here destructures the same pair
    and a keyword at each call site would be noise. Both fields default to empty so
    the "nothing to check" path cannot return a *different shape* from the
    "checked everything" path — the arity of a dataclass constructor is checked at
    the constructor, which is inside the function, which is where the bug was.
    """

    findings: tuple[Finding, ...] = ()
    unverified: tuple[str, ...] = ()


def _check_contradictions(
    repo: Path, points: list[Any], matched: dict[int, Registered], claims: list[Claim]
) -> Contradictions:
    rows = [
        (index, entry)
        for index, entry in enumerate(points)
        if isinstance(entry, dict) and entry.get("accountScoped") is False
    ]
    if not rows:
        return Contradictions()

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
        verdict = contradiction(
            repo,
            entry,
            matched.get(row_index),
            index,
            resolvers,
            claim=claims[row_index] if row_index < len(claims) else None,
        )
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

    return Contradictions(tuple(found), tuple(sorted(dict.fromkeys(unreachable))))


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
    for candidate in _handler_candidates(line):
        resolved = _file_defining(repo, index, candidate)
        if resolved is not None:
            return resolved
    return None


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


ROUTER_METHODS = frozenset(
    {
        "HandleFunc", "Handle",
        "get", "post", "put", "patch", "delete", "head", "options",
        "Get", "Post", "Put", "Patch", "Delete", "Head", "Options",
        "connect", "trace", "all", "Connect", "Trace", "All",
    }
)

NOT_A_SYMBOL = frozenset({"func", "function", "def", "fn", "return", "if", "for", "case"})


_LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`")


def _without_literals(line: str) -> str:
    return _LITERAL.sub(lambda match: " " * len(match.group(0)), line)


def _handler_candidates(line: str) -> tuple[str, ...]:
    found: list[tuple[str, bool]] = []
    depth = 0
    at = 0
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_.]*", _without_literals(line)):
        between = line[at : match.start()]
        depth += between.count("(") - between.count(")")
        at = match.end()
        candidate = match.group(0)
        if candidate in NOT_A_SYMBOL:
            continue
        if candidate.rsplit(".", 1)[-1] in ROUTER_METHODS:
            continue
        if depth == 0:
            continue
        found.append((candidate, line[at:].lstrip().startswith("(")))

    ordered: list[str] = []
    for candidate, _callee in reversed(found):
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate, callee in found:
        if callee and candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


DEFINITION_KEYWORD = re.compile(
    r"^\s*(?:export\s+|public\s+|private\s+)?(?:defp|def|func|fn|function)\b"
)


def _whole_token(line: str, at: int, name: str) -> bool:
    before = line[at - 1] if at else ""
    after = line[at + len(name) : at + len(name) + 1]
    for character in (before, after):
        if character and (character.isalnum() or character in "_.$"):
            return False
    return True


def _defines(line: str, name: str) -> bool:
    if DEFINITION_KEYWORD.match(line) is None:
        return False
    depth = 0
    at = 0
    while at < len(line):
        character = line[at]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif depth == 0 and line.startswith(name, at) and _whole_token(line, at, name):
            return True
        at += 1
    return False


def _file_defining(repo: Path, index: dict[str, str], symbol: str) -> str | None:
    if symbol in index:
        return index[symbol]
    tail = symbol.rsplit(".", 1)[-1]
    if tail:
        for path in sorted(repo.rglob("*")):
            if not path.is_file() or path.suffix not in INDEX_SUFFIXES:
                continue
            if SKIPPED & set(path.parts):
                continue
            relative = str(path.relative_to(repo))
            if TEST_FILE.search(relative):
                continue
            for line in source_lines(path):
                if _defines(line, tail):
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
    claim: Claim | None = None,
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

    `claim` is the row's `registeredAt` verdict and it exists for ONE case: when no
    registration matched because the route's path is an expression this checker
    could not evaluate, "no registration on the declared surface matched this row" is
    the wrong reason to print. The registration IS on the declared surface; this
    checker could not read its path. Both are a `warn` and both are honest, and
    telling a reader that a route is not on the surface when it is on the surface and
    unreadable is the sort of message that sends somebody to look in the wrong place
    for an hour.
    """
    if not isinstance(entry, dict) or entry.get("accountScoped") is not False:
        return Verdict()
    if registration is None:
        unreadable = claim is not None and claim.verdict == VERDICT_PATH_UNREADABLE
        return Verdict(
            row_gap=(
                "its registration is mounted at a line whose path is an expression this "
                "checker cannot evaluate, so there is no path to check this row against"
                if unreadable
                else "no registration on the declared surface matched this row"
            )
        )

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

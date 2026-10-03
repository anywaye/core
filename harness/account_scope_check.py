#!/usr/bin/env python3
"""account_scope_check — is a service's account-scoped entry-point list still true?

    account-scope-check .                       # the declaration against the tree
    account-scope-check . --json                # the same findings, as JSON
    account-scope-check --explain               # every finding, and what it means

WHAT THIS IS, AND WHY IT IS NOT PART OF `tenancy.yml`

`tenancy.yml` already declares an enumeration, and this file does not replace it.
They answer different questions, and the difference is the whole reason this is a
separate file:

  tenancy.yml  `entryPoints`   the STATEMENTS that reach another account's row —
                               a `where id = $1 and account_id = $2`, a repository
                               method, a worker. The boundary at the DATA.
  account_scope.yml             the ENTRY POINTS a caller can arrive through —
                               a route, a queue consumer, a scheduled task. The
                               boundary at the EDGE.

D18 asked the second question and could not ask it. Counting account-scoped
routes by pattern gave three different answers depending on framework syntax:

    guard       route_defs=96    isolation_tests=0
    muse        route_defs=76    isolation_tests=0
    cafaye-ts   route_defs=51    isolation_tests=0
    darkroom    route_defs=0     acct_scoped_files=15   (axum — other syntax)
    billing     route_defs=0     acct_scoped_files=5    (Rails — other syntax)

A grep that reports "darkroom has no routes" for a service with fifteen
account-scoped queries against customer assets is **worse than no grep, because
it reads like an answer.** So the enumeration is DECLARED, entry point by entry
point, and the checker's job is to decide three states per entry point:

    account-scoped     declared true, and the line that resolves the account
                       still carries the account key on disk
    not-account-scoped declared false, with a reason from a closed vocabulary
    UNDECLARED         a registration the checker can see in a file the service
                       NAMED, that no row of the declaration covers

and undeclared is a FAILURE. An entry point nobody declared is the unknown this
file exists to surface, and a checker that reported it as a pass would be the
same defect as the grep, with better manners.

WHAT THIS CHECKER CANNOT SEE, STATED FIRST

It recognises FOUR registration shapes, declared in `RECOGNISERS` below and
taken from four real repositories of this fleet: chi (`r.Get("/v1/…", …)`),
Phoenix (`get "/webhook_endpoints", …`), Hono/Express (`app.get("/v1/me", …)`)
and axum (`.route("/v1/services", get(…))`). A route in a fifth syntax, or one
registered in a file `surface.sources` does not name, is INVISIBLE to it. That
is why `surface.minimum` exists: it is a ratchet on how many registrations the
declared sources must still contain, and it is the only thing in this format
that notices a route that appeared somewhere the recognisers cannot read. The
same is true of the SCOPE PREFIX: resolving `scope "/v1"` nesting is the guessing
that produced three answers, so a declared `path` is matched as a SUFFIX of the
registered fragment and no prefix is invented. `docs/account-scope.md` carries the
full list, and `harness/account_scope_findings.json` carries it as `notEnforced`
so a reader is told rather than left to discover.

EXIT CODES

    0   no finding at severity `fail`. Warnings may still be printed.
    1   at least one `fail`.
    2   the check could not happen. Never 0, and never 1: a run that could not
        find the declaration has not checked anything.

PYTHON 3.9, AND WHY THIS FILE IS NOT 3.11

`harness/gate_check.py` needs 3.11 for `tomllib`. This one reads no TOML and runs
no process, so it inherits the floor of `harness/tenancy_check.py`: a contract
check that needs an interpreter some service's CI does not have is a check that
runs nowhere.
"""

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
    from cafaye_contract import Refusal, read_yaml
except ModuleNotFoundError as _missing:  # pragma: no cover
    raise SystemExit(
        f"account_scope_check: cannot import cafaye_contract from "
        f"{Path(__file__).resolve().parent}: {_missing}. It travels with the harness; "
        "a copy of one without the other would mean a second YAML dialect in core."
    )

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COULD_NOT_RUN = 2

#: The declaration file. One per repository, at its root, named for the reason
#: `gate.yml` is: a boundary discovered by guessing its filename is not a
#: declaration.
DECLARATION = Path("account_scope.yml")

#: The schema the declaration is written against. This file is stdlib-only, so it
#: re-implements the handful of constraints that decide whether a declaration is
#: well-formed — core's own idiom for a document and its schema being the same
#: contract written twice.
ACCOUNT_SCOPE_SCHEMA_RELATIVE = Path("schemas") / "account-scope.schema.json"

#: The floor. See the module docstring: no TOML, no process, so not 3.11.
MINIMUM_PYTHON = (3, 9)

#: The modules this file may import beyond the contract harness's own list.
EXTRA_STDLIB: frozenset[str] = frozenset()

SEVERITIES = ("ok", "warn", "fail")

#: The findings this checker can report, and nothing else. Mirrored in
#: `harness/account_scope_findings.json` and asserted equal in both directions by
#: core's suite, for tenancy_check's reason: a finding nobody was told about is a
#: finding that will be wrong the first time somebody needs it.
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
}

#: The tenancy key spellings searched for when NOTHING in the repository names the
#: key. Three are measured across this fleet — `account_id` (SQL), `accountId`
#: (TypeScript), `account-id` (YAML) — and the fourth, `accountID`, is Go's and is
#: in here because identity's own router writes `o.requireAccount(...)` beside a
#: variable called `accountID`, and a checker that could not see the one language
#: this fleet's substrate is written in would report a scoped route as unscoped.
#: It is a FALLBACK and the declaration is not required to use it: `tenancy.yml`'s
#: `scope.key` names the key for the statements, and when this repository has one
#: it is read instead — see `key_spellings`.
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
    #: Whether this syntax puts the HANDLER on the same line as the path, which is
    #: what makes `account-scope.scoping-bypassed` decidable. chi, Go's 1.22 form
    #: and Hono all take the handler as an argument on the registration line, so a
    #: route that stopped calling its middleware is readable as a bypass. Phoenix
    #: puts the middleware in a `pipeline`/`pipe_through` block ABOVE the route, and
    #: axum takes a bare function reference, so for those two the registration line
    #: says nothing about scoping and the check must NOT fire — a rule that fires on
    #: a correct Phoenix router is a rule that gets the whole format switched off.
    carries_handler: bool = True
    #: Whether the PATH comes from the FILE NAME rather than from the line. Next.js'
    #: App Router is the case: a `route.ts` exports `GET`, `POST` and `DELETE` as
    #: named functions and carries its path in its own path on disk
    #: (`app/v1/[...path]/route.ts`). Nothing in the line says what it is, so a
    #: recogniser that required the path in the line would read every one of them as
    #: no route at all — the `route_defs=0` this whole packet exists to stop.
    path_from_filename: bool = False
    #: Whether this syntax concatenates a path out of several literals and
    #: identifiers, which Go does and no other language in this fleet's roster
    #: does. `True` reads the terms after the first literal and names each of them
    #: `{}`, because the checker cannot read an identifier's value and pretending
    #: otherwise invents a path.
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
            # No `path` GROUP in this pattern at all — the path is in the file's
            # name — so asking for one is an IndexError rather than a wrong answer.
            # Which is why this branch is FIRST: a recogniser whose pattern had a
            # group it did not use would raise on the first route it saw, and a
            # checker that raises on a route is a checker nobody runs.
            if verb is None:
                return None
            resolved = route_path_from_filename(relative)
            # A `GET` exported from a file that is NOT a `route.ts` is a helper, not
            # a route. A route whose path cannot be determined is refused rather
            # than published as `/`, because an invented path becomes an
            # `undeclared` finding against a route that does not exist.
            return None if resolved == "/" else (verb.upper(), resolved)

        if path is None:
            # `mux.HandleFunc("/legacy", h)` — no method anywhere in the call, so
            # the method is unknown rather than GET. It is `ANY` so an `ANY`
            # declaration can match it, and a declaration saying `GET` still
            # matches it because a route whose verb was never written down is not
            # evidence that the route is something other than what was declared.
            return ("ANY", groups["anypath"]) if groups.get("anypath") is not None else None

        if self.concatenates and verb is not None:
            # The whole call, so the terms AFTER the first literal are reachable.
            joined = concatenated_path(line[hit.start() :])
            if joined is not None:
                path = joined
        if verb is None and self.verb_from_handler is not None:
            # axum writes `.route("/v1/services", get(list_services))` — the method
            # is in the HANDLER position, mid-line. An anchored pattern found
            # nothing, every axum route read as `ANY`, and a declared `GET` was
            # then refused by `same_route`: pantry's four routes, all undeclared.
            # Searched from the END OF THIS MATCH, not from the start of the line:
            # a chained `Router::new().route("/a", get(h)).route("/b", post(h2))`
            # puts two methods on one line and searching from the start reads POST
            # as GET.
            handler = self.verb_from_handler.search(line, hit.end())
            verb = handler.group(0) if handler is not None else "ANY"
        if verb is None:
            return None
        return verb.upper(), path


#: The registration shapes this checker recognises — six, one per framework
#: syntax measured in this fleet. Each was READ OUT OF a real repository rather
#: than guessed, and each carries that repository because a pattern with no
#: repository behind it is a pattern that will match something it was not written
#: for. `test_every_recogniser_is_fired_by_the_shape_it_was_read_from` asserts
#: every entry below matches its own `example`, reads the METHOD off it correctly,
#: does not match any other recogniser's example, and that every example is a line
#: that exists in `fixtures/account-scope/shapes/`.
RECOGNISERS: tuple[Recogniser, ...] = (
    Recogniser(
        id="chi",
        framework="net/http chi",
        read_from="identity/internal/httpapi/accounts.go:590",
        # The verb group is the METHOD NAME and NOT the receiver. Capturing the
        # receiver — `r.Get("/v1/x", …)` — reads every route in identity as method
        # `r`, which makes `same_route` refuse every declared route and report all
        # forty-two of them `undeclared`: a false alarm on the largest surface in
        # the fleet, and invisible to a test that only asked whether the recogniser
        # matched AT ALL. Caught by measuring the fleet, not by the red proof.
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
        # The SAME framework and a DIFFERENT syntax, which is why it is a second
        # recogniser rather than an optional group in the first: Go 1.22 moved the
        # method into the pattern string, so `mux.HandleFunc("GET /v1/x", h)` has
        # no method anywhere in the call. A checker that recognised one and not
        # the other would report the fleet's newest Go services as having no
        # routes at all — which is D18, and the fixture below is measured green
        # by the same checker that reports this repository as having four.
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
        read_from="guard/src/index.ts:150",
        pattern=re.compile(
            r"\b(?:app|router|api|r|server)\.(?P<verb>get|post|put|patch|delete|head|options|all)"
            r"\(\s*[\"'`](?P<path>/[^\"'`]*)[\"'`]"
        ),
        example='app.get("/v1/me", (c) => c.json(c.get("principal")));',
    ),
    Recogniser(
        # Next.js' App Router is the case that made `path_from_filename` necessary,
        # and it is in scope: `site` and `parlor` both serve `/v1` through a single
        # catch-all `app/v1/[...path]/route.ts` that exports GET, POST, PATCH and
        # DELETE as named functions. The path is in the file's NAME. A recogniser
        # that needed the path in the LINE would have read both of this fleet's
        # Next.js services as having no routes at all — which is D18's
        # `route_defs=0`, reproduced by a checker written to prevent it.
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
        # NOT anchored to the start of the line: axum writes
        # `.route("/v1/services", get(list_services))`, so the method is in the
        # HANDLER position mid-line. An anchored pattern found nothing, every
        # axum route read as `ANY`, and a declared `GET` was then refused by
        # `same_route` — pantry's four routes, all of them undeclared.
        verb_from_handler=re.compile(r"\b(get|post|put|patch|delete|head|options)\b(?=\s*\()"),
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
        for verb, path in recogniser.match_all(line, relative):
            found.append((verb, path, recogniser.id))
    return found


#: A trailing `//` or `#` comment, which is how three of this fleet's four
#: languages comment a line out. Stripping it is not a nicety: identity's own
#: router documents the routes it removed (`// GET /v1/x was removed in…`), and a
#: recogniser that read a comment as a registration would report every removed
#: route as `undeclared` — which is a checker crying wolf on correct code, the
#: failure mode D12 recorded and the one that gets a guard switched off.
#: How far BELOW `registeredAt` the handler is looked for. Three, and it is not a
#: guess: identity's `internal/httpapi/admin.go:121-122` writes a route as
#:
#:     r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/audit-log",
#:         o.requireAdminToken(o.requireAccountRole(accounts.RoleAdmin, o.handleListAuditLog)))
#:
#: — the PATH on one line and the middleware on the next. A window of zero would
#: report every one of identity's admin routes as `scoping-bypassed`, on the very
#: repository this packet's successor is told to adopt first: a false alarm on the
#: first adopter is how a guard gets switched off.
HANDLER_WINDOW = 3

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


#: Go writes a path as a concatenation, and identity's admin router does:
#:
#:     r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/audit-log", handler)
#:
#: Reading only the first literal yields `/v1/accounts/{accountID}/` — a path that
#: exists nowhere, which no declaration could ever match, so three of identity's
#: admin routes would be permanently `undeclared`. Each non-literal term becomes
#: `{}`, so the fragment is `/v1/accounts/{accountID}/{}/audit-log` and a
#: declaration says exactly that. It is decidable and it is honest: the middle is
#: named `{}` because the checker cannot read `adminPrefix`'s value, and a reader
#: who wants it precise writes the path it produces.
CONCATENATED_PATH = re.compile(r'"(?P<first>/[^"]*)"((?:\s*\+\s*(?:"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*))*)')


def concatenated_path(text: str) -> str | None:
    """A Go path literal with its concatenation resolved to `{}` for each term."""
    found = CONCATENATED_PATH.search(text)
    if found is None:
        return None
    pieces = [found.group("first")]
    for term in re.findall(r'"[^"]*"|[A-Za-z_][A-Za-z0-9_.]*', found.group(2)):
        # A literal contributes its CONTENTS; an identifier contributes `{}`,
        # because its value is not in the source and a guess here is a path that
        # exists nowhere.
        pieces.append(term[1:-1] if term.startswith('"') else "{}")
    return "".join(pieces)


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
    # `src/app/healthz/route.ts` serves `/healthz`: `src` is the source root and is
    # not in the URL. Everything up to and including the `app` segment is dropped,
    # which is Next.js' own convention rather than a judgement about it.
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
    """Lowercase, and drop the separators the fleet varies on.

    This is what collapses `account_id`, `accountId`, `accountID` and `account-id`
    onto one another, and it is a decision rather than a convenience list of four:
    a checker that has to be told the fourth spelling of one identifier is a
    checker that reports the fifth language's routes as unscoped. The boundary in
    `carries_key` is what keeps `sub_account_id` from matching.
    """
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

# --------------------------------------------------------------------------
# findings, and the report shape every checker in this directory uses
# --------------------------------------------------------------------------


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
        failed = len(self.of("fail"))
        warned = len(self.of("warn"))
        counts = self.counts
        verdict = "FAIL" if failed else "OK"
        # The three counts are printed separately and always: a report that says
        # "0 failures" over an empty enumeration is indistinguishable from a report
        # that enumerated nothing, which is the D18 defect one level up.
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
#: `via` is not an entry-point key of its own: it lives inside `accountFrom`, and
#: it is required there for the reason `account-scope.scoping-bypassed` exists.
ACCOUNT_FROM_KEYS = ("file", "line", "via")
TOP_LEVEL_KEYS = ("version", "service", "surface", "entryPoints")
SURFACE_KEYS = ("kind", "sources", "minimum", "accountKey")
#: Three of the four are required and `accountKey` is not: a service that spells
#: its account `account_id` in every file does not have to say so twice, and the
#: fallback is a WARNING (`scope-key-guessed`) rather than a schema violation. The
#: schema says the same thing and the two are asserted to agree.
SURFACE_REQUIRED = ("kind", "sources", "minimum")
LOCATION_KEYS = ("file", "line")
SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _location_problems(
    block: Any, where: str, allowed: tuple[str, ...] = LOCATION_KEYS
) -> list[str]:
    """The file/line half's constraints, and `via` when it is present.

    `allowed` is a parameter rather than a constant because `accountFrom` carries a
    third key and the third key is not a location — it is checked for SHAPE here and
    for MEANING in `_check_entry`, and a rule that lived in one of those two places
    only would be a rule the other place does not have.
    """
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


# --------------------------------------------------------------------------
# the surface: what is registered where the service says it registers things
# --------------------------------------------------------------------------


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
            # A directory is walked rather than refused, for tenancy.yml's reason:
            # a service whose router is built up across four files should be able to
            # say so. It costs the `minimum` floor its precision, which is the trade
            # and is stated in the schema.
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


#: Which files a declared source DIRECTORY is walked for. A route table is in a
#: source file, and a JSON fixture in a directory called `router/` is not one.
SOURCE_SUFFIXES = frozenset({".go", ".ex", ".exs", ".ts", ".tsx", ".js", ".mjs", ".rs", ".rb", ".py"})

#: Directories never walked. The same list the db-isolation checker uses, for the
#: same reason: whether `node_modules` is installed must not change an answer.
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

    # The schema violations do not stop the scan, for tenancy_check's reason and
    # with its reason: a reader told only "your file is invalid" goes looking for
    # a typo, when what they most need is the second diagnosis on top of it.
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

    report.entry_points, unmatched = classify(repo, points, surface_found)
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
) -> tuple[list[dict[str, Any]], list[Registered]]:
    """Per entry point: account-scoped, not-account-scoped, or — the finding —
    undeclared. Returns the classified rows and the registrations nothing claimed.

    `repo` is taken rather than used so the signature matches its siblings; the
    classification is a decision about two lists, and the disk is not consulted
    until `_check_entry`.
    """
    rows: list[dict[str, Any]] = []
    taken: set[int] = set()
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
    return rows, unmatched


def _line_at(repo: Path, block: Any) -> tuple[str | None, str | None]:
    """`(line, problem)` for a declared file and line. `line` is None when absent."""
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
    """One declared entry point against the tree: is it still where it says it is,
    and does the line that resolved the account still resolve one?"""
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
                # A recogniser match first, and the bare last segment second, so a
                # route this checker cannot parse is still recognised by its own
                # name on the line. The second test is what keeps `registeredAt`
                # meaningful in a syntax core has not been taught.
                #
                # The file's own path goes in, because a Next.js `route.ts` says
                # nothing about what path it serves and the recogniser derives that
                # from its NAME — reading it without the path would report every
                # route in `site` and `parlor` as stale, which is a checker crying
                # wolf on two of the three repositories it is meant to serve.
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

        # `via` must EXIST in the file `accountFrom` names, and the line that
        # registers the route must go THROUGH it. Both halves are decidable from
        # two strings, and together they are the difference between a declaration
        # that catches a bypassed route and one that only notices when the
        # middleware itself is deleted.
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
            # The registration and its handler are not always on ONE line, and a
            # window of zero would call identity's own admin router unscoped. So the
            # handler is looked for in `HANDLER_WINDOW` lines BELOW the declared
            # line — bounded, because an unbounded window would find the middleware
            # for some other route further down and call a bypass covered.
            reachable = registration_line or ""
            registered = entry.get("registeredAt")
            if isinstance(registered, dict) and isinstance(registered.get("file"), str):
                whole = source_lines(within(repo, registered["file"]))
                start = registered.get("line")
                if isinstance(start, int):
                    reachable = "\n".join(whole[start - 1 : start + HANDLER_WINDOW])
            # `via` on the registration line is only READABLE where the syntax puts
            # the handler there at all. See `Recogniser.carries_handler`: a Phoenix
            # router mounts its middleware in a `pipeline` block above the route and
            # axum takes a bare function reference, so for those two the route's own
            # line says nothing about scoping, and reporting it would report
            # courier's real router as unscoped — a rule that cries wolf on correct
            # code is the same defect as one that stays quiet on broken code.
            # DECIDED FROM THE LINE, not from a global: whether the handler is
            # readable depends on which framework registered THIS route. A Phoenix
            # line carries no handler, so there is nothing on it to have lost.
            handler_is_readable = registration_line is not None and any(
                candidate.carries_handler
                for candidate in RECOGNISERS
                if candidate.match(registration_line) is not None
            )
            # `reachable` rather than `registration_line`: the handler may be on
            # the next line, but whether it is READABLE is still decided by the
            # line that registers the route.
            readable = (
                handler_is_readable
                and registration_line is not None
                and re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(via)}(?![A-Za-z0-9_])", reachable
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
    """`(spellings, guessed)` — the account spellings to search, and whether they
    were chosen by this checker rather than declared by the service.

    `surface.accountKey` wins; `tenancy.yml`'s `scope.key` is next; and only when
    neither exists does the checker fall back to the four spellings it knows. The
    second value is why the fallback is a WARNING rather than a silent default: a
    search for a name the service never said is a guess, and D18 is the record of
    what this fleet's guesses cost.
    """
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
    """Two declarations of one repository must name the same repository.

    `tenancy.yml` is read rather than required: a service that has not adopted the
    tenancy declaration yet is a state, and a checker that reported its absence
    would be reporting D18 rather than this format.
    """
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


def to_json(report: Report) -> str:
    return json.dumps(
        {
            "repo": str(report.repo),
            "exitCode": report.exit_code,
            "couldNotRun": report.could_not_run,
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

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

    gateway     route_defs=96    isolation_tests=0
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

#: There is deliberately NO way to switch the contradiction check off from the
#: outside. `test_the_account_scope_checker_reads_no_environment_and_runs_no_process`
#: forbids an environment variable in this file and it is right to: a boundary
#: check whose answer depends on who is asking is not an answer about the
#: repository, which is the defect this whole format exists to stop. The breaking
#: is proved instead on a throwaway COPY of this file with the call deleted —
#: `harness/tests/account_scope_self_test.sh` case 24 — which shows the same thing
#: without shipping a switch somebody could leave on.

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
    #: Whether this syntax's PRE-HANDLER CHAIN is readable, which is a different
    #: question from `carries_handler` and the one gateway's `GET /v1/me` turned out
    #: to be inside. That flag asks whether the handler is on the registration line.
    #: This one asks what runs BEFORE it, and Hono has an answer that is not on the
    #: line: `app.use("/v1/*", …)` is middleware, it is registered above the routes
    #: behind it, and Hono matches handlers in registration order — so a route
    #: registered after a `use` IS behind it and its own line says nothing either
    #: way. True wherever the chain is decidable: chi and Go's 1.22 form, where the
    #: handler argument is the only place a gate can go, and Hono, because the mount
    #: above the route is in the same file and is read (`chain_gate`). False for
    #: Phoenix, axum and Next.js, whose chain this checker does not follow — and
    #: False is the whole of what it means: `scoping-bypassed` stays silent rather
    #: than reporting courier's real router as unscoped.
    chain_read: bool = True
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
        chain_read=False,
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


# --------------------------------------------------------------------------
# A PATH PREFIX THIS CHECKER CANNOT EVALUATE
# --------------------------------------------------------------------------
#
# `oapi-codegen` writes `r.Get(options.BaseURL+"/v1/services/{name}", …)` and
# `RECOGNISERS` requires the path expression to BEGIN with a `/`-prefixed string
# literal, so every registration of that shape is INVISIBLE. `pantry`'s entire
# surface is four of them, and the consequence is not a missed route — it is a
# NUMBER: `undeclared` is 0 over a surface the checker saw none of, and 0 over
# nothing reads exactly like 0 over everything. A count of zero and a count of
# nothing print as the same line.
#
# So this is a reader, and what it reads is the ABSENCE of a decision rather than a
# path. It deliberately publishes no path and resolves no prefix, for the reason
# `REPORT-core-hono-inline-01.md` §3 gives: `options.BaseURL` is a struct field the
# caller fills from configuration, so there is no value in any tree, and a
# recogniser that produced one would be guessing a deployment's configuration out of
# the air. Naming the unknown is decidable. Inventing it is not.
#
# NOT a recogniser, and not in `RECOGNISERS`, because every entry there publishes a
# `(method, path)` pair and this publishes neither. It is asked a different question
# — "is there a registration here whose path you cannot evaluate" — and putting a
# question with a different answer in the same list is how `undeclared` starts firing
# against routes that do not exist.
ROUTE_CALL = re.compile(
    r"\.\s*(?P<verb>Get|Post|Put|Patch|Delete|Head|Options|Connect|Trace|Mount"
    r"|Handle|HandleFunc)\s*\("
)

#: A string literal, which is what separates `options.BaseURL+"/v1/x"` (a path with
#: an unreadable head) from `o.tenancy.Get(r.Context(), …)` and from
#: `t.chiRouter.Get(pattern, traced(h))` — a method call that happens to be spelled
#: `Get`, and a helper mounting a path it was handed. The second is why the reader
#: below needs this test and not merely "the first argument is not a literal": a
#: predicate that matched `pattern` would warn on four lines of identity's `auth.go`
#: and on every Go service that factors its route table into a helper, and a warning
#: that fires everywhere is a warning nobody reads.
STRING_LITERAL = re.compile(r'"[^"]*"')

#: The two characters that open and close a string in the languages in this fleet's
#: roster. A path literal may contain a comma or a closing bracket, so the reader
#: below has to know it is inside one before it decides that it has reached the end
#: of an argument.
QUOTES = ('"', "'", "`")


def _first_argument(text: str) -> str:
    """The text between a call's `(` and the comma that ends its first argument.

    Nesting-aware and string-aware, because both matter in this fleet: pantry's four
    registrations put a comma inside parentheses in the SECOND argument, and identity's
    `admin.go:121` splits one call across two lines with the middleware in the second
    of them. Splitting on the first `,` without counting depth reads
    `, wrapper.GetService)` into the middle of a path.
    """
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


#: A Hono/Express MIDDLEWARE registration — `app.use("/v1/*", …)`. NOT a route: it
#: is deliberately absent from `RECOGNISERS`, so it never becomes an `undeclared`
#: finding and never counts towards `surface.minimum`. A gate is not an entry point
#: a caller arrives at, and a `use` counted as one would put every Hono floor in the
#: fleet out by the number of middlewares it mounts.
#:
#: The handler argument is captured whole because ITS SHAPE is the question rather
#: than its name: `async (c, next) => {` is this repository's own text and can be
#: read, and a bare `accountGate` is a symbol defined in another module.
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
            # The mount's own line and `HANDLER_WINDOW` below it, for the reason the
            # registration line is read through a window: the middleware BODY is on
            # the lines after the `app.use(`, and a window of zero would read every
            # gate as mounting nothing.
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
    #: Symbols the router names that resolve to no code in this repository. NOT
    #: findings, and the reason is a measurement rather than a preference: every
    #: Phoenix router in existence plugs `:accepts`, which lives in Phoenix itself,
    #: so a warning for it would fire on every Phoenix service every day for ever.
    #: A warning that cannot be acted on trains people to read past warnings, and
    #: the row-level `contradiction-unreadable` — a handler this checker cannot
    #: resolve — is actionable, so that one stays a finding and this one is a line.
    unverified: list[str] = field(default_factory=list)
    #: Registrations in `surface.sources` whose PATH this checker could not evaluate.
    #: Its OWN field and not a fifth entry in `counts`, for two reasons. `counts` is
    #: asserted state-by-state and every state in it is a state a declared row or a
    #: found registration is IN; these have no path, so there is nothing to put in a
    #: listing row and no `id` to hang one off. And it is printed on EVERY summary
    #: line rather than only when it is non-zero, because the defect this packet
    #: fixes is a number that was ABSENT and read as a zero: `0 undeclared` was
    #: ambiguous between "every registration was declared" and "no registration was
    #: found, so none could be undeclared". A count that appears only when it is
    #: interesting cannot answer "was anything dropped?", which is the one question
    #: this field exists for.
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
        # The four counts are printed separately and always: a report that says
        # "0 failures" over an empty enumeration is indistinguishable from a report
        # that enumerated nothing, which is the D18 defect one level up. And
        # `stale` is one of the four because a summary that does not count the rows
        # the file contradicts reads as though every row it listed is mounted — the
        # listing is the output a human skims, so it is the one that must not
        # assert a route that is not there. `unreadable` is the FIFTH and it is the
        # one this packet added: a registration whose path is an expression is in no
        # listing row and in no state above, so without this number `undeclared: 0`
        # said nothing at all about a service whose routes the checker never saw.
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
        """The registrations a reader can check a declaration against."""
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
        scan = Surface()
    else:
        scan = discover(repo, sources)
        report.findings.extend(scan.problems)

    # The count is set BEFORE anything below can return, and it is the reason the
    # summary line grew a fifth number. `0 undeclared` was ambiguous between "every
    # registration was declared" and "no registration was found, so none could be
    # undeclared", and on a service written by `oapi-codegen` it was the second one
    # wearing the first one's clothes. Carried on the Report rather than folded into
    # `counts` because `counts` is asserted equal, state by state, and this is not a
    # state any row is in: these registrations have no path, so they cannot be listed.
    report.unreadable = len(scan.unreadable)
    report.findings.extend(surface_findings(scan))

    minimum = surface.get("minimum")
    if isinstance(minimum, int) and not isinstance(minimum, bool) and len(scan.found) < minimum:
        # The floor counts what this checker READ and nothing else. Counting unreadable
        # registrations towards it would turn pantry's exit 1 into an exit 0 with
        # `minimum: 4` and no warning at all — a coverage number manufactured out of
        # routes nobody read, which is the exact opposite of what the unreadable count
        # is for. So the comparison is unchanged and the MESSAGE grows instead: a floor
        # that is unreachable because the routes are invisible is not a floor that has
        # been violated, and a reader who cannot tell those two apart will lower it.
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

    # ONE read of every declared `registeredAt`, shared by the listing and by the
    # findings. They were two reads before this packet and the two disagreed about
    # whether a commented-out route was mounted, which is the whole defect: the
    # summary asserted a route existed on a line that is a comment, and the run
    # exited 0. Computed here so it is computed once and cannot be two answers.
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

    # Named fields, not `contradictions, unverified = ...`. The tuple unpack was
    # what made this call site and this definition two independent halves of one
    # contract; see `Contradictions`.
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
            # The declaration says the route is mounted HERE and the file does not
            # agree, so the row is printed stale. Reported for every verdict that says
            # the file CONTRADICTS the row rather than for every verdict that is not
            # `REGISTERED`, because the fifth verdict is neither: a line that mounts a
            # route whose path is an expression contradicts nothing. It is a route that
            # is there.
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


#: What the line a declaration row points at says about the route that row claims.
#: Four answers, and the two in the middle are the whole of this packet's defect:
#: they are both "this row is not mounted where it says it is" and they have
#: different fixes, so a reader has to be told which one they are looking at.
#:
#: `REGISTERED`   the line registers the route.
#: `MOVED`        the line is CODE and does not register it — renamed, moved, or
#:                gone from this file. `account-scope.stale`.
#: `COMMENTED`    the line mentions the route and every mention is inside a
#:                comment. `account-scope.registration-commented`, and the reason it
#:                is its own answer: the file still SAYS
#:                `r.Get("/healthz", handleHealthz)` on the exact line the
#:                declaration points at, so a reader skimming the file believes it
#:                as readily as the checker used to. One deletion of one character
#:                from `strip_comment`'s callers made the checker agree.
#: `UNREADABLE`   the line could not be read at all — wrong file, wrong number,
#:                a file that is not text. `account-scope.stale`, naming why.
#: `PATH_UNREADABLE`  the line DOES register a route and its path is an expression
#:                this checker cannot evaluate — `r.Get(options.BaseURL+"/x", …)`.
#:                The FIFTH answer, and the only one that is neither a contradiction
#:                between the row and the file nor a route this checker can check:
#:                the route is there and the path is not available, so the row is
#:                `account-scope.registration-path-unreadable` (a warning) and stays
#:                out of the stale count. Before it existed this line fell through to
#:                `MOVED`, and the result was `stale` — a FAILURE saying a mounted
#:                route is not mounted, on `pantry` and on every Go service written
#:                by a code generator.
VERDICT_REGISTERED = "registered"
VERDICT_MOVED = "moved"
VERDICT_COMMENTED = "commented"
VERDICT_UNREADABLE = "unreadable"
VERDICT_PATH_UNREADABLE = "path-unreadable"

#: The claim verdicts that make a declared row `stale`. Named rather than written as
#: `!= VERDICT_REGISTERED` because that expression is what let a fifth verdict be
#: added without anybody asking what it would do to every row that was not
#: `REGISTERED`: it would have made all of them stale.
STALE_VERDICTS = frozenset({VERDICT_MOVED, VERDICT_COMMENTED, VERDICT_UNREADABLE})

#: The listing state for a row the file contradicts. NOT `undeclared`, which is its
#: mirror image and reads the same way round: `undeclared` is a real registration
#: no row covers, `stale` is a row whose registration is not there. Both appear in
#: the same four columns of the same listing, so they cannot share a word.
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
    """Whether `text` NAMES this row's entry point, without saying what `text` is.

    One function for both halves of the decision, and called twice with two
    different `text` values, which is what makes the difference between a route
    that was renamed and a route that was commented out decidable rather than
    guessed: pass it the line's CODE and it answers "is this mounted here?", pass
    it the line AS WRITTEN and it answers "is this named here at all?".

    A recogniser match first, and the bare last segment second, so a route this
    checker cannot parse is still recognised by its own name on the line. The
    second test is what keeps `registeredAt` meaningful in a syntax core has not
    been taught. `relative` is the file's own path, because a Next.js `route.ts`
    says nothing about what path it serves and the recogniser derives that from its
    NAME — reading it without the path would report every route in `site` and
    `parlor` as stale, which is a checker crying wolf on two of the three
    repositories it is meant to serve.
    """
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
        # Two calls to one function, and the difference between them IS the verdict.
        # `line_registrations` strips `code`'s comment again, which is a no-op: the
        # seam is idempotent on an already-stripped line, and having it be so is
        # what lets one predicate answer both halves instead of two predicates
        # disagreeing, which is the defect this replaced.
        if _mentions_on(entry, code, relative):
            claims.append(Claim(VERDICT_REGISTERED, code, line, None))
        elif _mentions_on(entry, line, relative):
            # Named on this line and not in its code: the mention is the COMMENT.
            claims.append(Claim(VERDICT_COMMENTED, code, line, None))
        # THE FIFTH ANSWER, and it is asked before `MOVED` on purpose. The row does not
        # name this line and the line mounts a route whose path is an expression this
        # checker cannot evaluate — so the route may well be the one this row is about
        # and this checker cannot tell. That is neither `REGISTERED` (it is not
        # checked) nor `MOVED` (nothing has been shown to have moved), and it is what
        # stops `stale` from being a FAILURE about a route that is mounted.
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
        # NOT `stale`, and the difference is the whole finding: `stale` says the entry
        # point is no longer registered where the declaration says, and this line
        # registers it. It is a `warn` for the reason every unreadable answer in this
        # checker is a `warn` — a row nobody verified is not a row that passed, and a
        # FAILURE here would be a defect in this checker presented as a defect in a
        # service's declaration, which is how `pantry` read exit 1.
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
    """How to refer to one entry point in a message: its route, or its name."""
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
    """One declared entry point against the tree: is it still where it says it is,
    and does the line that resolved the account still resolve one?"""
    if not isinstance(entry, dict):
        return []
    found: list[Finding] = []
    label = entry.get("id") if isinstance(entry.get("id"), str) else "an entry point"

    found.extend(registration_findings(label, entry, claim))

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
            # ONE spelling of the symbol's boundary, used three times below, and the
            # reason it is a local is that a copy per use is three places for `via`'s
            # matching rule to drift — and the rule is what distinguishes
            # `requireJwt` from `requireJwtForAdmin`.
            via_pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(via)}(?![A-Za-z0-9_])")
            if not any(via_pattern.search(text) for text in whole):
                found.append(
                    finding(
                        "account-scope.account-key-lost",
                        f"{label}: accountFrom names {via}, which does not appear in {named}",
                    )
                )
            # `claim.code`, not `_line_at`'s raw line: the registration and its
            # handler are not always on ONE line, and a window of zero would call
            # identity's own admin router unscoped. So the handler is looked for in
            # `HANDLER_WINDOW` lines BELOW the declared line — bounded, because an
            # unbounded window would find the middleware for some other route
            # further down and call a bypass covered. The window is stripped for the
            # same reason the line is: a comment saying `o.requireAccount(...)` is
            # not a call to it, and letting one count here would let a commented-out
            # registration mask the bypass the row is really about.
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
            # `claim.code` again rather than the raw line, and for the same reason
            # as `reachable`: a line that is only a comment matches no recogniser,
            # so a route that is not mounted reports neither `scoping-bypassed` nor
            # a duplicate of the registration finding. `registration-commented` is
            # the whole truth about a row that is not mounted.
            matching = [
                candidate
                for candidate in RECOGNISERS
                if candidate.match(claim.code) is not None
            ]
            handler_is_readable = claim.verdict == VERDICT_REGISTERED and any(
                candidate.carries_handler for candidate in matching
            )
            # THE CHAIN, which is a DIFFERENT question from the one above and was
            # answered "no such thing" for a Hono route before this existed. gateway's
            # `GET /v1/me` is registered with an inline handler TWENTY-SEVEN LINES
            # BELOW `app.use("/v1/*", … jwt.requireJwt(c, next) …)`, and a checker
            # reading only the registration line called a JWT-gated route one that had
            # never seen a JWT. Both honest declarations were answered by a failure —
            # `accountScoped: true, via: requireJwt` by `scoping-bypassed`, and
            # `accountScoped: false` by `declaration-contradicts-code`, which is
            # CORRECT — so a service holding other people's identity could not say so
            # at all.
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
            # THE THIRD ANSWER, and the only one that is neither "yes" nor "no": the
            # route is behind a mount whose middleware lives in ANOTHER module, so the
            # chain left the file this checker read. `carries_handler`'s own answer
            # for a chain it cannot follow is silence, and silence here is what
            # `hono_composed` measures.
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
    """Every `accountScoped: false` row against the code it claims to describe.

    This is the half of the format that `undeclared` cannot be. A complete
    enumeration of fourteen rows, every one `false`, every `reason` valid and every
    `registeredAt` on a real line, is a schema-valid document saying a service
    holding other people's data reaches none of it — and `undeclared`, `stale`,
    `surface-*` and `duplicate-id` are all silent about it, because the author DID
    enumerate their surface. The author's answer is what is being checked here.

    The module index is built once, and only if there is a `false` row to check,
    because it walks the repository and a declaration that declares nothing false
    should not pay for a walk it does not need.

    IT RETURNS A `Contradictions`, NOT A TUPLE, and that is the whole point of
    this signature. A 2-tuple is unpacked at the call site and nowhere else, so
    the half that says "two values" is 60 lines away from the half that says "one
    value" and nothing connects them except a reader — which is exactly how
    `worker/core-account-scope-contradiction` and master each changed one side of
    this contract, git merged both halves without a textual conflict, `bin/prime`
    exited 0 and 295/295 tests passed, and the checker crashed on an input no
    gate reached. A named structure puts the arity next to the name, so an early
    `return []` and a late `return (found, unreachable)` cannot both typecheck, and
    `test_every_harness_function_returns_one_shape` fails on the disagreement
    rather than leaving it to be noticed.
    """
    rows = [
        (index, entry)
        for index, entry in enumerate(points)
        if isinstance(entry, dict) and entry.get("accountScoped") is False
    ]
    if not rows:
        return Contradictions()

    # The account resolvers this service NAMES, read off its own declaration rather
    # than off a list this checker chose. A row saying `accountFrom.via:
    # requireAccount` is the service telling every other row what an account
    # resolver is called HERE, and a registration carrying that symbol while being
    # declared `false` is a contradiction decided from the service's own vocabulary.
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

    # Once per repository, and NOT a finding. See `Report.unverified`.
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


# --------------------------------------------------------------------------
# THE CONTRADICTION CHECK: is a declared `false` true?
# --------------------------------------------------------------------------
#
# Everything above this line asks whether the author ENUMERATED their surface.
# `undeclared` cannot be satisfied by a liar, and neither can the schema: fourteen
# `accountScoped: false` rows with real reasons and real `registeredAt` lines is a
# complete, valid, entirely false document. This section asks the other question —
# ARE THE ANSWERS TRUE — and it is decidable, because the route itself says where
# the account comes from.
#
# THE SIGNAL IS THE RESOLUTION CHAIN, NOT THE WORD. `grep account_id` in the
# controller was measured on courier and rejected; the numbers are in
# REPORT-core-account-scope-contradiction.md and they are three facts about one
# repository:
#
#   1. It FIRES on `inbound_controller.ex`, a signed provider webhook that reaches
#      no customer row. One false positive on the repository the packet names, out
#      of one such controller.
#   2. On `messages_controller.ex` all three of its `account_id` hits are PROSE.
#      The action names no account at all: a plug put one on the request before the
#      function was entered. A signal that counts words is right about the file and
#      wrong about the code.
#   3. courier does not spell it `account_id` in a controller. It spells it
#      `conn.assigns.current_account`, and in `messages_controller.ex` that spelling
#      occurs exactly once, inside a docstring.
#
# So: (a) every file is read with comments and docstrings MASKED, so a match is a
# match in CODE by construction and prose can never be one; and (b) the evidence
# sought is the account being RESOLVED — put on the request by a plug the
# registration's pipeline names, or read out of one — which is what makes a route
# account-scoped whether or not its handler happens to say so.


#: An account read OUT OF SOMETHING THE CALLER DID NOT CHOOSE. Each pattern is a
#: spelling of one act — resolving who is calling — taken from a repository of this
#: fleet rather than guessed, and every one of them is matched against MASKED code
#: so that the same word in a moduledoc cannot be a hit.
#:
#: No bare `account_id` is in this list, and that omission is the measurement above
#: rather than an oversight: a bare `account_id` in courier's controllers is either
#: prose or a struct field being serialised, and a variable *named* account_id is
#: only evidence once something shows where its value came from.
RESOLVED: tuple[re.Pattern[str], ...] = (
    # Plug/Elixir, the assignment that puts a resolved account on the request:
    # `assign(conn, :current_account, accountID)`. courier's principal.ex:97 and
    # this file's principal.ex:19 are both this line and nothing else.
    re.compile(r"\bassign\s*\(\s*\w+\s*,\s*:(?:current_)?(?:account|tenant)(?:_id)?\b"),
    # Plug/Elixir, the read of it: `conn.assigns.current_account`.
    re.compile(r"\.assigns\.(?:current_)?(?:account|tenant)(?:_id|_name)?\b"),
    # Hono/Express/Next.js, the principal off the request context.
    re.compile(r"""\.\s*get\s*\(\s*["']principal["']\s*\)"""),
    re.compile(r"\.\s*get\s*\(\s*[\"'](?:current_)?(?:account|tenant)[\"']"),
    # A context/claim object naming the account — `ctx.AccountID`,
    # `principal.account`, `claims.account_id`, `session.tenant`. The receivers are
    # whole words on purpose: `c.` and `r.` are one letter in Go and would match
    # half a repository.
    re.compile(
        r"\b(?:ctx|context|principal|claims|session|request|req|scopes?)\s*\.\s*"
        r"(?:current_)?(?:account|tenant)(?:_?id|ID|Id)?\b"
    ),
)

#: An account the CALLER NAMES — `params["account_id"]`, `body.accountId`. A route
#: that reads one is not `reason: public`, and it is not account-scoped either: it
#: is account-SELECTED, which is a strictly worse thing to have declared either
#: way. Kept separate from `RESOLVED` because the remediation differs and because
#: its fire rate is measured on its own rather than hidden inside the total.
NAMED: tuple[re.Pattern[str], ...] = (
    re.compile(r"""\bparams\s*\[\s*["'](?:account|tenant)[_-]?(?:id|ID|Id)["']\s*\]"""),
    re.compile(r"""\b(?:path_params|query_params)\s*\.\s*(?:get|fetch)\s*\(\s*["'](?:account|tenant)[_-]?id["']"""),
    re.compile(r"""\.\s*re\.\s*query\s*\(\s*["'](?:account|tenant)[_-]?id["']"""),
    re.compile(r"\b(?:body|payload|params|query|input)\s*[.\[]\s*[\"']?(?:account|tenant)_?id[\"']?\s*[\]}]"),
)

#: Which delimiters open a heredoc, per language family. A `"""` run in Elixir, Go,
#: Python or TypeScript is a docstring or a doc comment, and a docstring that says
#: `account_id` is the single largest source of false positives this signal has,
#: measured at 3 of courier's 3 and 2 of its 2.
HEREDOC = ('"""', "'''")

#: `#` is a comment in Elixir, Ruby, Python and YAML, and is not one in Go, C or
#: TypeScript — where it is a private field. Masking it there would delete real
#: code, so the set of suffixes is declared rather than guessed per line.
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
        # A line comment, taken off first so that a `#` or `//` inside a heredoc
        # opener on the same line cannot open anything.
        for opener in ("//",) + (("#",) if suffix in HASH_COMMENT_SUFFIXES else ()):
            at = line.find(opener)
            if at >= 0:
                line = line[:at] + blank * (len(line) - at)
        if line.lstrip().startswith(("/*", "*")):
            # A block comment that OPENS here. The `*` on a continuation line is
            # this case too, and it is how a Go or TS doc comment is written.
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


#: A module DEFINITION, per language. `defmodule CourierWeb.HealthController do`,
#: `class Foo`, `type Foo struct`, `interface Foo`, `enum Foo`, `module Foo`.
#: This is the index that makes handler resolution a RESOLUTION rather than a
#: filename convention: Phoenix's `WebhookEndpointsController` is
#: `webhook_endpoints_controller.ex` in courier and `lib/x_web/controllers/x_controller.ex`
#: in a different repository, and guessing the second from the first is the class of
#: guess that produced three answers to one question in D18.
DEFINITION = (
    re.compile(r"^\s*(?:defmodule|defprotocol)\s+([A-Z][A-Za-z0-9_.]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?(?:class|interface|enum|struct|module|namespace)\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:type|record)\s+([A-Z][A-Za-z0-9_]*)\s+(?:struct|interface|\{)"),
    re.compile(r"^\s*def(?:p)?\s+([A-Z][A-Za-z0-9_]*)\s*[( ]"),
)

#: A file no module is ever resolved INTO. Measured on this fleet and not guessed:
#: before this list existed, gateway's `app.get("/auth/me", bff.me)` resolved to
#: `src/problem.test.ts`, because a bare symbol search finds the first definition
#: of that name anywhere in the repository and a test file is full of them. A
#: resolution that lands on a test is worse than no resolution: it produces a
#: confident wrong answer.
TEST_FILE = re.compile(r"(?:^|/).(?:[^/]*)(?:\.(?:test|spec)|_test|_spec|tests?)[^/]*$")

#: Directories never walked when indexing modules. The same list `discover` uses,
#: for the same reason: whether `node_modules` is installed must not change an
#: answer.
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
    # chi, chi-1.22 and hono all take the handler as an argument on this line. A
    # line can name SEVERAL candidates — a middleware wrapping a handler, or a
    # handler factory taking its dependency — and only the repository can say which
    # of them exists, so each is tried in turn and the first that resolves wins.
    # Taking the first that resolves rather than the first that parses is what makes
    # `r.Get("/readyz", o.handleReadyz(checks))` and
    # `mux.HandleFunc(…, o.requireAccount(o.handleGetMessage))` both correct when
    # they are syntactically indistinguishable; see `_handler_candidates`.
    for candidate in _handler_candidates(line):
        resolved = _file_defining(repo, index, candidate)
        if resolved is not None:
            return resolved
    return None


def _phoenix_module(repo: Path, source: str, named: str, index: dict[str, str]) -> str | None:
    """The file defining the module a Phoenix route line names, given the SHORT name.

    Phoenix routers write `get "/x", HealthController, :show` — the namespace is
    implied by the router's own `defmodule CourierWeb.Router`. Resolving that needs
    the router's namespace, read from the file itself rather than assumed to be the
    first path segment: the alternative is guessing
    `lib/<app>_web/controllers/<name>_controller.ex`, and guessing a path from a
    class name is the same class of guess that produced D18's three answers to one
    question.

    Fully-qualified first, then qualified under the router's namespace, then bare.
    Three lookups and no invention: an unresolvable module stays unresolved, and
    the row says so instead of being blamed on a file that does not exist.
    """
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


#: Tokens that are a router's own method, never a handler. `r.Get` and
#: `mux.HandleFunc` match as ONE token because a dot is a token character here, so
#: the comparison is made on the last dotted segment: without that, `r.Get` is not
#: in the set and a scan that returned "the innermost call" would return the ROUTER.
ROUTER_METHODS = frozenset(
    {
        "HandleFunc", "Handle",
        "get", "post", "put", "patch", "delete", "head", "options",
        "Get", "Post", "Put", "Patch", "Delete", "Head", "Options",
        "connect", "trace", "all", "Connect", "Trace", "All",
    }
)

#: Words that sit where a symbol could and are not one. `func` is here because
#: Go writes an inline handler as `func(http.ResponseWriter, *http.Request) {`,
#: which is a callee-shaped token opening a function literal rather than a call of
#: something named `func`.
NOT_A_SYMBOL = frozenset({"func", "function", "def", "fn", "return", "if", "for", "case"})


#: A string literal, in any of the three quotes this fleet's four languages use.
#: Only the CONTENT is blanked and the length is preserved exactly, because the
#: offsets this function computes against the blanked line are compared with
#: parentheses found on the original.
_LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`")


def _without_literals(line: str) -> str:
    """`line` with every string literal's CONTENTS blanked, same length.

    Not a tokenizer and not a lexer: a quote inside a quote opens nothing special
    and the cost of being wrong is one lost or one spurious CANDIDATE, which is a
    file that may or may not be the right one — so unlike `masked`, which decides
    findings, this one only decides an ORDER, and every candidate in it is tried
    against the repository before any of them is believed.
    """
    return _LITERAL.sub(lambda match: " " * len(match.group(0)), line)


def _handler_candidates(line: str) -> tuple[str, ...]:
    """The symbols on a registration line that could be its handler, INNERMOST FIRST.

    THE RULE: the handler is the innermost symbol that NAMES SOMETHING IN THIS
    REPOSITORY. A registration line offers several such symbols and this function
    cannot tell them apart by shape alone — measured on identity, the two lines that
    broke the previous version of this checker are

        r.Get("/readyz", o.handleReadyz(checks))          a handler FACTORY
        mux.HandleFunc(…, o.requireAccount(o.handleGetMessage))   a MIDDLEWARE

    and they are syntactically IDENTICAL: a call of a call, with a bare identifier
    as the inner argument. In the first the inner identifier is `checks`, a
    parameter, and the handler is the callee; in the second the inner identifier IS
    the handler and the callee is the middleware wrapping it. No rule about
    parentheses, depth or callee-ness separates those two, because there is nothing
    in the line that separates them.

    So the order is decided by the LINE and the CHOICE by the REPOSITORY, in that
    order, and the caller (`handler_for`) takes the first candidate that resolves to
    a file. That is what makes both shapes correct without either being special-
    cased, and it is why this returns a TUPLE rather than the single symbol the
    first version returned:

      innermost first   the symbol that is deepest in the argument lists, which is
                        the handler under a middleware and the factory under a
                        factory, so whichever of the two actually exists wins;
      then the callee   `o.handleReadyz`, the thing the router will call if the
                        inner argument turns out to be a parameter;
      then the argument  `handleHealthz`, which is a handler and nothing else.

    `checks` cannot be returned by accident on a line that also names a real
    handler, because it is the OUTERMOST of the three and the other two are tried
    first. And on a line where it IS the only candidate — `r.Get("/x", checks)` —
    it resolves to nothing, `_file_defining` says so, and the row is reported
    `contradiction-unreadable` rather than checked against a file chosen because it
    happened to be mentioned there.

    Router methods (`r.Get`, `mux.HandleFunc`) and language keywords are not
    candidates: a router method is never the handler and resolving it would point
    every route in the fleet at the router's own file.

    STRING LITERALS ARE BLANKED FIRST, and that is not tidiness. A path is a string,
    so `mux.HandleFunc("POST /v1/messages", …)` otherwise offers `POST`, `v1` and
    `messages` as candidates — and `messages` is a perfectly ordinary identifier in
    a Go service, so a service with a `messages` method would have its route
    resolved to whatever that method's file happens to be. The previous version hid
    this by accident: taking the LAST token on the line happened to be past the
    literal. A candidate list makes it visible, which is why it is stated here.
    """
    # (`identifier`, `is a callee`) innermost-first, deduplicated keeping the
    # innermost occurrence, because `o.handleSendMessage` appearing twice on one line
    # is one candidate and not two.
    found: list[tuple[str, bool]] = []
    depth = 0
    at = 0
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_.]*", _without_literals(line)):
        # The punctuation skipped since the previous identifier is where the
        # parentheses are, and counting them is what makes "innermost" a fact about
        # the line rather than a guess about which token looks handler-shaped. The
        # depth is recorded BEFORE the token is judged, so a token is at the depth of
        # the argument list it belongs to.
        between = line[at : match.start()]
        depth += between.count("(") - between.count(")")
        at = match.end()
        candidate = match.group(0)
        if candidate in NOT_A_SYMBOL:
            continue
        if candidate.rsplit(".", 1)[-1] in ROUTER_METHODS:
            continue
        if depth == 0:
            # `r`, `o` in `r.Get("/x", o.handleX)` — the receiver of a call, and not
            # the handler of anything.
            continue
        found.append((candidate, line[at:].lstrip().startswith("(")))

    ordered: list[str] = []
    # Innermost first: the last identifier seen is the deepest, and within one
    # depth the last is the one nearest the closing paren.
    for candidate, _callee in reversed(found):
        if candidate not in ordered:
            ordered.append(candidate)
    # Then the callees, for a line whose innermost argument is a parameter.
    for candidate, callee in found:
        if callee and candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered)


#: A keyword that OPENS a definition, in the four languages in this fleet's roster.
#: `defp` is here for the reason `module_index`'s own table carries it: `def`
#: followed by `p` is not a word boundary, so a pattern listing `def` alone drops
#: every Elixir private function on the floor, silently.
DEFINITION_KEYWORD = re.compile(
    r"^\s*(?:export\s+|public\s+|private\s+)?(?:defp|def|func|fn|function)\b"
)


def _whole_token(line: str, at: int, name: str) -> bool:
    """Is the text at `at` the whole token `name`, and not part of a longer one?

    Dots count as token characters because a receiver-qualified name is written
    with one: `handleReadyz` inside `o.handleReadyz` is not a declaration of
    `handleReadyz`, it is a mention of it from something else.
    """
    before = line[at - 1] if at else ""
    after = line[at + len(name) : at + len(name) + 1]
    for character in (before, after):
        if character and (character.isalnum() or character in "_.$"):
            return False
    return True


def _defines(line: str, name: str) -> bool:
    """Does this line DECLARE `name`, rather than merely mention it?

    Two conditions and a third that is new, and the third is the one that makes
    the first two safe:

      a definition keyword opens the line — `func`, `def`, `defp`, `fn`,
      `function`, with the `export`/`public`/`private` modifiers the fleet's four
      languages spell differently;
      `name` appears on it as a whole token; and
      `name` is not inside an argument list, decided by PAREN DEPTH rather than
      by a list of forbidden spellings.

    The third is load-bearing because the first two are not sufficient, and the
    case that shows it is measured rather than imagined. identity's
    `internal/httpapi/httpapi.go:154` is

        func New(checks []Check, opts ...Option) http.Handler {

    — `checks` follows a definition keyword and is followed by a bracket, so the
    looser test this replaces accepted it, and a search for the symbol `checks`
    came back with `httpapi.go` as though it had found a handler. It had found a
    PARAMETER. That is worse than finding nothing, for the reason the `SKIPPED`
    table higher in this module gives: a resolution that lands on the wrong file
    produces a confident wrong answer, and the whole reason
    `contradiction-unreadable` exists is that a row nobody verified must SAY SO.

    So the name has to sit at depth zero. A Go METHOD satisfies that with the
    receiver balanced ahead of it — `func (o options) handleReadyz(checks []Check)`
    is at depth 0, and so is `func handleHealthz(w http.ResponseWriter, …)`. Which
    is the measurement that matters here: the receiver was never the problem, and
    `.*` between the keyword and the name was already matching one. A parameter is
    the problem.
    """
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
    """The file in this repository that defines `symbol`, or nothing.

    A bare function name — `o.handleGetMessage`, `handleList` — is found by
    searching for its DEFINITION rather than its name, so that a symbol appearing
    in a hundred call sites does not resolve to the first of them.

    BARE AND QUALIFIED SPELLINGS ARE BOTH SEARCHED, and the guard that used to
    say otherwise read `if tail and tail != symbol` — which searched a symbol
    carrying a dot and skipped every one without, while the paragraph above named
    `handleList` as a case it handles. So the docstring and the code disagreed and
    the code was the one that ran. Measured on identity: `/healthz` registers as
    `r.Get("/healthz", handleHealthz)` and `handleHealthz` is defined at
    `internal/httpapi/httpapi.go:292`, in a file this checker had already read
    twice, and the row came back `contradiction-unreadable` — "the handler could
    not be resolved to a file in this repository". A docstring is not a test, and
    this one had been asserting a capability for as long as it was untrue.
    """
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


# --------------------------------------------------------------------------
# the account-resolving chain a Phoenix scope puts in front of its routes
# --------------------------------------------------------------------------

SCOPE = re.compile(r"^\s*scope\s+\"[^\"]*\"\s*,.*\bdo\s*$")
PIPE_THROUGH = re.compile(r"^\s*pipe_through\s+(.+?)\s*$")
PIPELINE = re.compile(r"^\s*pipeline\s+:([A-Za-z0-9_]+)\s+do\s*$")
PLUG = re.compile(r"^\s*plug\s+([A-Z][A-Za-z0-9_.]*)\b")
LOCAL_PLUG = re.compile(r"^\s*plug\s+:([A-Za-z0-9_]+)\b")
DEF_LOCAL = re.compile(r"^\s*defp?\s+([A-Za-z0-9_]+)\b")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _block(lines: list[str], start: int) -> range:
    """The lines of the `do` block opened on line `start`, by indentation.

    Indentation and not brace counting, and the reason is stated rather than
    hidden: Elixir has no braces, so a block is the set of lines indented at least
    as far as the line that opened it, and a file that does not indent its blocks
    is a file whose router this cannot read — which is reported as unreadable
    rather than guessed at.
    """
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
    """One `plug X` against the file that defines X.

    A module plug (`plug CourierWeb.Plugs.Principal`) resolves through the index to
    the file that defines it and is read whole. A local plug (`plug :accepts`) is a
    function in the router beside it, so only that function's own body is read —
    reading the whole router would make every plug in it evidence for every other,
    which is how a check ends up blaming `/healthz` for a plug only `/v1` carries.
    """
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

    # 1. The resolver, named by this same declaration somewhere else.
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

    # 1b. The registration line ITSELF, for the frameworks that put an inline
    # handler on it. gateway's own `app.get("/v1/me", (c) => c.json(c.get("principal")))`
    # resolves the caller's account on the line that registers the route, and
    # measured on the fleet before this layer existed the checker found NO evidence
    # on gateway at all — 0 of 7 routes — because it was looking in the handler file
    # for something that was on the router line the whole time.
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

    # 2. The pipeline a Phoenix scope puts in front of the route.
    unreadable: tuple[str, ...] = ()
    if registration.recogniser == "phoenix":
        verdict = pipeline_evidence(repo, registration.file, registration, index)
        if verdict.evidence is not None:
            return verdict
        unreadable = verdict.unreachable

    # 3. and 4. the handler, and the module one hop below it.
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
    # Everything above was READ and none of it resolved an account. That is a
    # verdict, not a gap, and reporting it as unreadable would make this finding
    # cry wolf on every honest row in the declaration.
    return Verdict(unreachable=unreadable)


#: A module reference the hop can follow. Each was read out of a repository of this
#: fleet, and each is followed ONLY when the module resolves through the index — an
#: unresolvable reference is not a hop and produces no evidence either way.
HOP = (
    re.compile(r"^\s*(?:alias|import|use)\s+([A-Z][A-Za-z0-9_]*(?:\.[A-Z][A-Za-z0-9_]*)*)"),
    re.compile(r"""^\s*import\s+(?:type\s+)?(?:\{[^}]*\}|[\w*]+)\s+from\s+["']([^"']+)["']"""),
)


def _hops(repo: Path, source: str, index: dict[str, str]) -> list[str]:
    """The files one hop below `source`: the modules it names and this repo has.

    ONE hop, deliberately. Two hops is where the chain stops being evidence and
    starts being a guess: courier's unsubscribe route reaches
    `Courier.Unsubscribes`, one hop from THAT is the mail adapter, and the adapter
    holds a customer's address. A check that followed the chain that far would
    report a token-authorised callback as account-scoped — right about the data,
    wrong about the route, and wrong in the direction that gets the guard switched
    off. Capped at four hops per file so a router cannot fan out into the tree.
    """
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

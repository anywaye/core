# `account_scope.yml` — which entry points reach another account's data

**One file per service, at its repository root. It says which of this service's
routes, queue consumers and scheduled tasks reach a customer's data, one at a
time, with the line at which each one resolves the caller's account and a reason
from a closed list for the ones that do not.**

The rule is `schemas/account-scope.schema.json`; the checker is
`harness/bin/account-scope-check`. If the two ever disagree, the schema is what a
service validates against and this document is what a person reads, so the suite
fails — which is the point of having both.

## Why this is a file and not a grep

`DEBT.md` D18 measured the gap directly. Counting account-scoped routes by
pattern gave three different answers depending on framework syntax:

```
  guard       route_defs=96    isolation_tests=0
  muse        route_defs=76    isolation_tests=0
  cafaye-ts   route_defs=51    isolation_tests=0
  darkroom    route_defs=0     acct_scoped_files=15   (axum — different syntax)
  billing     route_defs=0     acct_scoped_files=5    (Rails — different syntax)
```

A grep that says *darkroom has no account-scoped routes*, when darkroom has
account-scoped queries against customer assets, is **worse than no grep, because
it reads like an answer.** Every service that wants to prove isolation has to
answer "which routes are account-scoped?" and every answer so far has been a
guess, made by grep, in a different dialect per framework.

So the enumeration is **declared**, and the checker's job is to decide three
states per entry point and say which one it is:

| state | what it means |
|---|---|
| `account-scoped` | declared `true`, and the line that resolves the caller's account still carries the account key on disk |
| `not-account-scoped` | declared `false`, with a reason from a closed vocabulary |
| `account-scope.undeclared` | a registration in a file `surface.sources` names, that no row of the declaration covers |

**`undeclared` is a FAILURE, not a pass.** An entry point nobody declared is the
unknown this file exists to surface, and a checker that reported it as clean would
be the same defect as the grep with better manners.

## Why this is a *separate* file and not a fifth block of `tenancy.yml`

`tenancy.yml` already declares an enumeration and it is untouched by this packet.
They answer different questions, and the difference is the whole reason:

| file | block | the question |
|---|---|---|
| `tenancy.yml` | `entryPoints` | which **statements** reach another account's row — a `where id = $1 and account_id = $2`, a repository method, a worker |
| `account_scope.yml` | `entryPoints` | which **entry points** a caller arrives through — a route, a queue consumer, a scheduled task |

The boundary at the DATA and the boundary at the EDGE. `tenancy.yml` answers
"does this query constrain on the account, and does a test prove another account
is refused". This file answers "can a caller reach the handler at all, and does
it arrive as somebody's account". Neither can be derived from the other: darkroom
has fifteen account-scoped queries and no route table core can read, and a service
can have a route table and no account-scoped statements in it.

## The file

```yaml
version: 1
service: courier

surface:
  kind: http              # http | job | both | none
  sources:                # the files the checker reads looking for what is UNDECLARED
    - lib/courier_web/router.ex
  minimum: 19             # a floor on registrations found in those files
  accountKey: account_id  # optional; tenancy.yml's scope.key is read if this is absent

entryPoints:
  - id: send-message
    kind: http
    method: POST
    path: /v1/messages
    accountScoped: true
    accountFrom:
      via: require_account      # the symbol that resolves the account
      file: lib/courier_web/plugs/require_account.ex
      line: 8
    registeredAt:
      file: lib/courier_web/router.ex
      line: 142

  - id: healthz
    kind: http
    method: GET
    path: /healthz
    accountScoped: false
    reason: public             # the closed vocabulary, below
    registeredAt:
      file: lib/courier_web/router.ex
      line: 88

  - id: deliver-message
    kind: job
    name: MessageWorker
    accountScoped: true
    accountFrom: { via: resolve_account, file: lib/courier/workers/message_worker.ex, line: 22 }
    registeredAt: { file: lib/courier/application.ex, line: 41 }
```

**Every entry point is listed, including the ones that reach nothing.** A service
that lists only its dangerous entries has not enumerated its surface; it has
published a partial list under a heading that says otherwise, and a reader cannot
tell the difference. `/healthz` is declared `false` with a reason for that reason.

**The reasons are a closed list** — `public`, `platform-admin`, `system`,
`unauthenticated-callback`, `none` — because the alternative is a list of sentences
in which every one of them is a decision with no reader. A service that cannot
pick one of these has an entry point it has not reviewed, and there is no `other`.

**`surface.kind: none` is the honest zero.** `none` requires an empty
`entryPoints`, forbids `accountFrom` anywhere and pins `minimum` to 0. A shared
library says "there is no request entry here" in a field rather than in a comment;
a format without it forces one of two failures, both recorded in this fleet — a
service holding no customer rows omits itself (indistinguishable from having
forgotten) or declares a boundary it does not have. `kit` is the live case.

## `surface.sources` and `surface.minimum`, and why both are required

`entryPoints` is the authority for what this service has. `surface.sources` is
what the checker reads looking for something the authority left out — and it is
the only reason `undeclared` is decidable at all.

`minimum` is a **ratchet on how many registrations those sources must still
contain**, set to the count when the file was written. It exists because the
checker recognises six registration shapes:

| recogniser | syntax | path comes from | read from |
|---|---|---|---|
| `chi` | `r.Get("/v1/accounts", h)` | the line | `identity/internal/httpapi/accounts.go:586` |
| `chi-1.22` | `mux.HandleFunc("GET /healthz", h)` | the line | the conforming fixture's own router |
| `hono` | `app.get("/v1/me", handler)` | the line | `guard/src/index.ts:150` |
| `next-app` | `export function GET(...)` in `route.ts` | **the FILE NAME** | `site/src/app/v1/[...path]/route.ts:138` |
| `phoenix` | `get "/webhook_endpoints", C, :index` | the line | `courier/lib/courier_web/router.ex:115` |
| `axum` | `.route("/v1/services", get(h))` | the line | `pantry/src/http.rs:99` |

Two Go spellings are two recognisers on purpose: Go 1.22 moved the method into the
pattern string, and a checker that knew one and not the other would report the
fleet's newest Go services as having no routes at all — which is D18.

**Next.js is the one whose path is not in the line at all.** `site` and `parlor`
each serve their entire `/v1` surface from one catch-all
`src/app/v1/[...path]/route.ts` that exports `GET`, `POST`, `PATCH` and `DELETE`
as named functions, so `Recogniser.path_from_filename` exists and resolves
`src/app/v1/[...path]/route.ts` to `/v1/{path}`. A recogniser that required the
path in the line would report both of this fleet's Next.js services as having no
routes — D18's `route_defs=0`, reproduced by the checker written to stop it.

**Two consequences a service will hit**, both measured rather than predicted:
`surface.sources` and `registeredAt.file` accept `[` and `]` (the schema says so),
and a `[...path]` catch-all is declared as `{path}` like any other parameter.

**A route in a seventh syntax, or in a file `sources` does not name, is invisible to
the checker.** That is the honest cost and `surface.minimum` is the counterweight
to the second half of it: a route that appears somewhere the recognisers cannot
read lowers the count the floor can see. It is the same shape as
`gate.yml`'s `proof[].minimum`, and it is the same trade: a decrease-detector,
which is the only kind of floor worth having.

## What the checker decides, and what it cannot

The findings, all in `harness/account_scope_findings.json`:

| finding | severity | the defect |
|---|---|---|
| `account-scope.declaration-missing` | fail | the service reaches customer data and declares no entry point |
| `account-scope.declaration-unreadable` | fail | not a document the harness's own reader accepts |
| `account-scope.schema` | fail | does not satisfy `schemas/account-scope.schema.json` |
| `account-scope.surface-missing` | fail | `surface.sources` names a file that is not in the repository |
| `account-scope.surface-empty` | fail | entry points declared and no file named to check them against |
| `account-scope.undeclared` | fail | a registration in a declared source that no row covers |
| `account-scope.stale` | fail | a declared entry point is no longer registered where it says it is |
| `account-scope.account-key-lost` | fail | `accountFrom`'s line no longer carries the account key |
| `account-scope.scoping-bypassed` | fail | the route no longer goes through the `via` that scoped it |
| `account-scope.surface-thin` | fail | fewer registrations than `surface.minimum` |
| `account-scope.duplicate-id` | fail | two rows share an `id` |
| `account-scope.service-disagrees` | warn | this file and `tenancy.yml` name different services |
| `account-scope.nothing-scoped` | warn | the surface was enumerated and nothing on it is account-scoped |
| `account-scope.scope-key-guessed` | warn | nothing named the tenancy key, so four spellings were searched |

Two of them are worth their own paragraph.

### `scoping-bypassed` is why `accountFrom` carries `via`

A route declared `accountScoped: true` with an `accountFrom` **line** is a
declaration that a careful person can check by hand. It is not a check the tool can
perform: delete `o.requireAccount(...)` from a chi route and the middleware still
exists, still carries the account key, and is still called by the other three
routes. Every line-scoped check stays green and a customer reads another
customer's messages.

So `accountFrom` names the **symbol** as well as the line, and the checker reads
two strings: the symbol must appear in `accountFrom.file`, and the line that
registers the route must go through it. Together those are decidable, and together
they are the difference between a declaration that catches a bypassed route and one
that only notices when the middleware is deleted.

**The check is per-syntax, and it only fires where it is decidable.** chi, Go's
1.22 form and Hono all take the handler as an argument on the registration line.
Phoenix mounts its middleware in a `pipeline` block *above* the route, and axum
takes a bare function reference — so for those two the route's own line says
nothing about scoping, and reporting it would report courier's real router as
unscoped. A rule that cries wolf on correct code is the same defect as one that
stays quiet on broken code; both train the reader to ignore the finding.

### The scope prefix is NOT resolved

`/v1/webhook_endpoints` and `/webhook_endpoints` both resolve to Phoenix's
`get "/webhook_endpoints"`. A declared `path` is matched as a **suffix** on a
segment boundary, because resolving `scope`/`mount`/prefix nesting is the exact
guessing that produced three different answers across five repositories. Declare
the path your caller uses; the checker resolves the shortest thing that matches.

`:id` and `{id}` are the same parameter, collapsed before comparison — five
languages and four frameworks between them spell it both ways.

### The tenancy key is compared, not guessed — and says so when it has to

`account_key` search is case- and separator-insensitive with a word boundary, so
`account_id`, `accountId`, `accountID` and `account-id` are one identifier and
`sub_account_id` is not a match. That collapse is a decision rather than a
convenience list of four: a checker that has to be told the fifth spelling of one
identifier is a checker that reports a fifth language's routes as unscoped, and Go
is the language this fleet's substrate is written in.

The key is read from `surface.accountKey`, or from `tenancy.yml`'s `scope.key`. If
**neither** exists the checker falls back to the four spellings it knows and says
so — `account-scope.scope-key-guessed`, a warning. A service whose column is
`tenant` otherwise passes every check here without being wrong.

### The full list of what is not enforced

`harness/account_scope_findings.json` carries it as `notEnforced`, so a reader is
told rather than left to discover:

- a route in a framework syntax the six recognisers do not know — a Rails
  `routes.rb` is invisible and never becomes `undeclared`; an `http.ServeMux`
  registered through a variable rather than by method name reads as `ANY`;
- a route registered in a file `surface.sources` does not name;
- the scope prefix;
- whether a `reason` on an `accountScoped: false` row is **true** — the vocabulary
  is closed so that "I looked and it reaches no customer row" is a choice, but
  nothing checks the choice. The line the entry point is registered on *is*;
- the method inside a method list;
- any tenancy key other than the one declared;
- **whether an account-scoped handler actually scopes.** This file proves the
  declaration still describes the tree. Whether the statements behind the handler
  scope their rows is `tenancy.yml`'s `entryPoints` and
  `harness/tenancy_check.py`, which is why there are two files.

## Running it

```
harness/bin/account-scope-check .                 # this service
harness/bin/account-scope-check . --json          # machine-readable, incl. per entry point
harness/bin/account-scope-check --explain         # every finding, and what it means
```

Exit `0` no failure, `1` at least one failure, `2` **the check could not happen** —
never `0`. It is a check on a tree, so it runs no process and reads no environment
variable, and it needs nothing installed: standard library only, CPython ≥ 3.9.

Its own proof that it can fail is
`harness/tests/account_scope_self_test.sh`: **twenty-four cases, seventeen going
red naming the finding they expect and seven clean** — including the control that
runs first, and including three that exist because this checker's own bugs were
found by reading real repositories rather than by the proof:

- a **chained axum router**, `Router::new().route("/a", get(h)).route("/b", post(h2))`,
  which holds two routes on one line. A recogniser that returned the first match
  would miss the second, and one that read the handler method from the start of
  the line would call the second route's `POST` a `GET`. Both were real, both were
  silent on every fixture core ships, and neither is reachable from a fixture
  whose lines each register exactly one route.
- a **chi router with one GET and one POST on the same path**, plus the control
  that declaring them swapped goes red. The chi pattern once captured the
  *receiver* — `r.Get(...)` read as method `r` — which would have reported all
  forty-two of identity's routes `undeclared`. Every earlier version of the test
  asked "did it match?" and passed, because it never asked *what method* it read. Run the harness tests you touch, not the whole self-test suite.

## What is not here

- **No fleet adoption.** Nothing in `identity`, `courier`, `guard`, `site`,
  `parlor`, `pantry`, `caf`, `kit` or `core` declares an `account_scope.yml` yet;
  the numbers are in the packet's report. Adopting it is step 3 of D18 and a
  separate packet per repository.
- **No harness for the statements.** Step 2 of D18 — proving a service's own
  queries are scoped — belongs in `kit`, and is owed against this contract rather
  than in place of it.
- **No change to `tenancy.yml`.** Its schema, its twenty-four findings and
  identity's live declaration are untouched, and `service` disagreeing between the
  two files is a warning rather than an edit to either.
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

### What `surface.minimum` catches that no per-row check can

Re-derived after `account-scope.registration-commented` landed, because a floor
that duplicates the real check is a number that can be wrong in a second
direction — and before that finding landed, `surface.minimum` was not a duplicate
of anything, it was the only signal, which is exactly what made it unsafe: a
decrease-detector whose own floor can be edited down to match the decrease is not
a decrease-detector.

`stale` and `registration-commented` are both **per-row**. Each asks whether a row
the declaration *still has* points at a line that registers it. So:

| what the refactor did | caught by |
|---|---|
| registration deleted, row kept | `registration-commented`, `stale`, `surface-thin` |
| registration deleted **and its row deleted** | `surface-thin` only |
| registration moved out of `surface.sources`, row kept | `stale` or `registration-commented` |
| registration moved out of `surface.sources`, row deleted | `surface-thin` only |

The two right-hand rows are the floor's own, and they are not a corner: a route
that a refactor deleted *and cleaned up after* leaves no row for a per-row check to
be stale about. Measured on `harness/tests/fixtures/account-scope/conforming` with
the `/healthz` registration and its row both removed and `get-message` re-pointed at
its new line: `surface-thin` is the only finding, and `minimum: 4` → `3` turns it
green.

So it stays, it is a second and independent signal rather than the first and only
one, and lowering it is now a *second* edit a reviewer has to get wrong instead of
the first. It is still the one number in the declaration that can be wrong in the
dangerous direction, which is why its remediation asks for a reason rather than
accepting a keystroke.

### `registration-commented`: the line that names the route without mounting it

`stale` and `registration-commented` are the same missing route with two different
fixes, so they are two findings rather than one:

- **`stale`** — the line is *code* and does not register the route. Fix it by
  pointing `registeredAt` at the new line, or delete the row.
- **`registration-commented`** — the line *mentions* the route and every mention is
  inside a comment. There is no line to point at. Uncomment it, or delete the row.

The second shape is the one this repository got wrong, and got wrong in the worst
direction available. A Go refactor comments a route out and leaves the row:

```go
// r.Get("/healthz", handleHealthz)
```

`surface.sources` never saw a registration for it — `undeclared` is silent, and
correctly so, because the route genuinely is not registered. But the row check read
the **raw** line, found the route written there in a comment, and reported the row
as mounted. So the run was green with the floor lowered, and the summary printed the
deleted route as a live one:

```
not-account-scoped GET /healthz  (internal/httpapi/httpapi.go:245)
```

Three things were wrong at once: no finding fired, and the output a human reads
asserted something false. Both halves of the checker now read every source line
through `strip_comment`, and `harness/tests/account_scope_self_test.sh` cases
26–28 are the red proof: 26 is the finding, 27 is the same repository with
`surface.minimum` lowered so the row is all that is left, and 28 deletes the check
from a throwaway copy of the checker and requires 27's repository to go **clean**.

`registration-commented` is deliberately NOT `undeclared`. They read the same way
round and are opposite: `undeclared` is a real registration no row covers,
`registration-commented` is a row whose registration is not there. Both appear in
the same four columns of the same listing, so they cannot share a word — and the
listing prints a stale row as `stale`, because a summary that asserts a deleted
route is mounted is worse than no summary at all.

### What the checker decides, and what it cannot

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
| `account-scope.registration-commented` | fail | `registeredAt` points at a line that only *mentions* the route, in a comment |
| `account-scope.account-key-lost` | fail | `accountFrom`'s line no longer carries the account key |
| `account-scope.scoping-bypassed` | fail | the route no longer goes through the `via` that scoped it |
| `account-scope.surface-thin` | fail | fewer registrations than `surface.minimum` |
| `account-scope.duplicate-id` | fail | two rows share an `id` |
| `account-scope.declaration-contradicts-code` | fail | declared `accountScoped: false`, and the route resolves an account |
| `account-scope.service-disagrees` | warn | this file and `tenancy.yml` name different services |
| `account-scope.contradiction-unreadable` | warn | a `false` row whose handler resolves to no file here, so it was not checked |
| `account-scope.registration-path-unreadable` | warn | `registeredAt` names a line that DOES register the route, and its path is an expression this checker cannot evaluate |
| `account-scope.surface-unreadable` | warn | a declared source mounts routes whose path is an expression, so `undeclared` and `minimum` were decided over the ones that were read |
| `account-scope.nothing-scoped` | warn | the surface was enumerated and nothing on it is account-scoped |
| `account-scope.scope-key-guessed` | warn | nothing named the tenancy key, so four spellings were searched |

Five of them are worth their own paragraph.

### `declaration-contradicts-code`: is the `false` TRUE?

Everything above asks whether the author **enumerated** their surface.
`undeclared` cannot be satisfied by a liar, and neither can the schema: fourteen
rows, every one `accountScoped: false`, every `reason` from the closed vocabulary,
every `registeredAt` on a real line, is a complete, valid, entirely false
document. `undeclared`, `stale`, `surface-*` and `duplicate-id` are all silent
about it, because the author *did* enumerate their surface. So this finding checks
the author's **answer**.

It resolves the route's account and looks for evidence that it has one, in four
layers, strongest first:

1. **the resolver on the registration line** — named by *this declaration itself*,
   on another row's `accountFrom.via`. The service says what an account resolver is
   called here, so there is no list of names the checker chose and can be wrong
   about;
2. **the registration line**, for frameworks that put an inline handler on it
   (guard's `app.get("/v1/me", (c) => c.json(c.get("principal")))`);
3. **the pipeline** — a Phoenix `scope`'s `pipe_through` reaches
   `pipeline :authenticated`, which plugs `CourierWeb.Plugs.Principal`, whose
   line 97 is `assign(conn, :current_account, account_id)`;
4. **the handler, and one hop below it.**

Two decisions make it CODE rather than a word count, and both were forced by
measurement on courier:

- **Comments and docstrings are masked before any match** (`masked()`), preserving
  line numbers. In courier, `messages_controller.ex` mentions `account_id` three
  times and **all three are prose**; the action names no account at all, because a
  plug put one on the request before the function was entered. A signal that counts
  words is right about the file and wrong about the code.
- **Modules are resolved through an index, not a filename convention.**
  `module_index()` walks the repository and records where each `defmodule` / `class`
  / `type X struct` is defined. Guessing `lib/<app>_web/controllers/x_controller.ex`
  from a class name is the same class of guess that produced D18's three answers.

**Measured on courier, per route** — 14 routes declared `false`:

| | count |
|---|---|
| true positives (a resolved account) | **9** |
| false positives | **0** |
| routes it correctly does not name | 5 — `/healthz`, `/readyz`, `POST /inbound/resend`, both halves of `/unsubscribe/:token` |

and the comparison that decided the design, on the same fourteen:

| signal | fires on | verdict |
|---|---|---|
| `grep account_id` in the handler file | 10 routes | **wrong on `/inbound/resend`**, a signed provider webhook that reaches no customer row; and its 3 hits on `messages_controller.ex` are all prose |
| this check | 9 routes | 9 true positives, 0 false positives |

The five routes it does not name are the five that are honestly `false`, and one
of them — the token-authorised unsubscribe — **holds a customer's mailbox** and
still resolves no account. That is the false positive this signal is shaped to
avoid: a check that fired on "this handler reaches customer data" would be right
about the fact, wrong about the verdict, and still green on the liar, because
everything it said would be true.

**Why FAIL and not WARN.** A warning on courier has been printed on this build for
weeks and nothing happened, so a warning is not a severity, it is a habit. The
signal is decidable from a resolution rather than a heuristic: the evidence is a
line in a file the checker reached by following the framework's own wiring, and the
negative controls above are not an aspiration — they are cases 20, 22 and 23 of
`harness/tests/account_scope_self_test.sh`, and case 24 deletes the check and shows
the liar passing again. A gate that cries wolf gets disabled, and this one is not
measured crying.

**What it does not see**, in `notEnforced` with its numbers: a handler dispatched
as a property of an object the checker cannot resolve scores **1 of 5** on guard
(`bff.login`, `bff.me` — resolving those means resolving the type of the receiver,
a second resolution this checker does not make). That is four false negatives on
one repository, recorded rather than papered over by broadening the signal until it
fires on things it cannot justify.

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

### The chain IN FRONT of a Hono route, which is not on its line

`Recogniser.carries_handler` answers *is the handler on the registration line*.
That is not the only question `scoping-bypassed` has to ask, and for Hono the second
one has an answer the line does not carry:

```ts
app.use("/v1/*", async (c, next) => {          // guard/src/index.ts:160
  if (c.get("principal")) return next();
  return jwt.requireJwt(c, next);
});
// … twenty-seven lines …
app.get("/v1/me", (c) => c.json(c.get("principal")));   // :187
```

Hono matches handlers in **registration order**, so `/v1/me` is behind that gate, and
guard's own comment at `:157` says so. A checker that reads only the registration
line sees no gate at all and reports the route unscoped — on guard's only route that
resolves an account.

`Recogniser.chain_read` is that second question, declared per recogniser and False
for Phoenix, axum and Next.js exactly where `carries_handler` is. Where it is True,
`chain_gate` reads the `app.use` mounts registered **above** the row's own line in
the file the row names, and asks three things of each:

| question | why it has to be asked |
|---|---|
| is it **above**? | registration order is the only reason a `use` is in front of a route at all, and a gate mounted below the route it exists to guard is a gate that does not run — guard says so about its own rate limiter |
| does its pattern **cover** this path? | `/v1/*` over `/v1/me`, yes; `/v1/*` over a `/v2` route, **no**. A coverage test that ignored the prefix would clear a row nothing gates |
| does it name **`via`** on its own line or within `HANDLER_WINDOW` below it? | the middleware body is on the lines after the `app.use(`, and a window of zero would read every gate as mounting nothing |

`mount_covers` returns `(covers, decided)` and the two are kept apart, because they
are two answers: a `*` in the middle, a RegExp or a trailing `:param` is **neither**,
and reading an unevaluated pattern as "does not cover" is how a `use` that matches
nothing becomes the gate for every route in a file.

**And when the chain left the file, the answer is neither yes nor no.** A mount whose
middleware is a bare identifier defined in another module — `api.use("/*",
accountGate)` — cannot be followed, and the route is NOT called unscoped. That is
`carries_handler`'s own refusal restated for a chain this checker cannot read, and
the alternative is a wolf on a correct row. The price is a row that is silent in
both directions, which is [D45](../DECISIONS.md#d45-should-a-chain-the-checker-cannot-follow-say-so-or-be-silent).

**This is deliberately NOT `carries_handler=False` on Hono.** That is the change that
looks like it settles the question, and it settles it by silencing the check: it would
make `scoping-bypassed` permanently quiet about every inline-handler route in the
fleet, guard's `/v1/me` among them. Self-test case 49 measures it — on the repository
where the gate has genuinely been deleted, the flagged variant says nothing at all.
A false negative bought with a false positive is not a fix.

### The scope prefix is NOT resolved

`/v1/webhook_endpoints` and `/webhook_endpoints` both resolve to Phoenix's
`get "/webhook_endpoints"`. A declared `path` is matched as a **suffix** on a
segment boundary, because resolving `scope`/`mount`/prefix nesting is the exact
guessing that produced three different answers across five repositories. Declare
the path your caller uses; the checker resolves the shortest thing that matches.

`:id` and `{id}` are the same parameter, collapsed before comparison — five
languages and four frameworks between them spell it both ways.

### A path PREFIX is not resolved, and a route behind one is named rather than counted

The scope prefix above is not resolved for a reason. A **path** prefix is a different
question again, and the honest answer to it is a warning:

`r.Get(options.BaseURL+"/v1/services/{name}", …)` — `oapi-codegen`'s shape, and
pantry's whole surface — cannot be read, because the recognisers require the path
expression to **begin** with a `/`-prefixed string literal. `options.BaseURL` is a
struct field the caller fills from configuration, so there is no value in any tree and
a recogniser that produced a path from it would be guessing a deployment's
configuration out of the air. So the checker does not produce a path, and reports
instead:

- `account-scope.surface-unreadable` — per file, with the lines, naming how many of
  the registrations in `surface.sources` were read. This is `contradiction-unreadable`
  restated for a surface rather than for a row.
- `account-scope.registration-path-unreadable` — for a row whose `registeredAt` names
  such a line. The row is **mounted and unverified**, which is not `stale`: `stale`
  claims the route is gone and it is there.
- a fifth number on the summary line, printed on **every** run:

  ```
  OK …/pantry: 0 account-scoped, 6 not-account-scoped, 0 stale, 0 undeclared, 6 unreadable — 0 failure(s), 9 warning(s)
  ```

  `0 undeclared` used to mean both "every registration was declared" and "no
  registration was found, so none could be undeclared", and on a generated Go router it
  meant the second while reading as the first. Always printed rather than printed when
  non-zero, because an omitted number cannot be told from a computed zero — and
  `surface.minimum` still counts only what was **read**, so the floor cannot be
  satisfied by a route nobody saw.

A `const` prefix gets the same answer, not a better one. `probePrefix` and
`socialLoginPrefix` have their values in their trees; a rule that behaved differently
for them would be a rule that guesses harder when the value happens to be lying next to
it. `REPORT-core-hono-inline-01.md` §3 measured that and left it alone; this extends the
judgement rather than reversing it. The decision, the three alternatives and the cost of
flipping each are [D46](../DECISIONS.md#d46-what-does-a-registration-whose-path-prefix-cannot-be-evaluated-produce-and-what-may-a-warning-mean-about-the-surface).

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
- a handler dispatched as a property of an object the checker cannot resolve, which
  on guard means four of its five account-scoped routes;
- **a chain that left the file** — a mount whose middleware is a bare identifier from
  another module. The route is not accused and there is no warning either: 1 of 2
  mounts in the `hono_composed` fixture, 0 in the fleet's seven services today, and
  the gap is [D45](../DECISIONS.md#d45-should-a-chain-the-checker-cannot-follow-say-so-or-be-silent);
- **a mount whose path is not a string literal** — `app.use(ROUTE_MOUNT, proxy)`,
  which is 1 of guard's 4. It is neither credited nor treated as a barrier, so the
  finding still fires on a route behind it: the loud direction, deliberately;
- **a wildcard `mount_covers` cannot evaluate** — 0 in the fleet, where both of
  guard's wildcard mounts spell it as a bare `*` or a trailing `/*`;
- **`app.route("/v1", v1())` read as axum's `.route(path, handler)`**, so a Hono
  sub-application mount becomes an `undeclared` finding against `/v1`. 1 in the
  `hono_composed` fixture and 0 in the fleet, where the only other `.route(` is
  Playwright's `page.route` in two e2e specs. A separate real defect, recorded in
  `REPORT-core-hono-inline-01.md` §7 and left in the fixture rather than written
  around;
- a `do` block written without indentation, because that is how a Phoenix pipeline
  is found;
- a route registered in a file `surface.sources` does not name;
- the scope prefix;
- **the VALUE of a concatenated Go path segment.** `"/v1/accounts/{}/"+adminPrefix+
  "/audit-log"` is read as `/v1/accounts/{}/{}/audit-log` — the middle is `{}`
  because the identifier's value is not in the source, and a guess there is a path
  that exists nowhere. Declare it as `{}` and it matches;
- **a path argument that is an identifier with NO string literal in it** — 19 lines in
  identity, of which 4 are not route registrations at all (`o.tenancy.Get(r.Context(), …)`
  is a map field's method), 4 are its own `register`'s `pattern` parameter, 2 are
  `o.panicOnRoute` and `o.parameterizedRoute`, and **9 are real routes** whose paths
  are package constants this checker cannot see in any form. 0 in the other five
  services;
- **any prefix value, resolvable or not.** The section above reports it and names it;
  what it never does is read it, and a service whose prefix is a `const` gets the same
  warning as one whose prefix is configuration;
- **a scoped row behind an unevaluable prefix is not `scoping-bypassed`-checked**,
  because that finding reads the registration line through the recognisers and none of
  them matches. 0 rows in the fleet today, so it is a latent gap rather than a live
  one;
- whether a `reason` on an `accountScoped: false` row is **true**. This was the
  state until `declaration-contradicts-code`, and the check above now decides it
  against the route's account rather than against the reason's spelling. What it
  still cannot decide is whether the DATABASE is scoped when the route resolves an
  account and then does not use it — that is `tenancy.yml`'s `entryPoints`;
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
`harness/tests/account_scope_self_test.sh`: **thirty-two cases, twenty-four going
red naming the finding they expect and eight clean** — including the control that
runs first, and including three that exist because this checker's own bugs were
found by reading real repositories rather than by the proof:

**It runs inside `bin/prime`, not only in CI.** That is not a default: it was a
CI step and nothing else until 2026-10-03, and a merge went through with a green
`bin/prime` and `295/295 passed` over a tree on which this proof was **2 of 32
red**. Two branches had changed one contract — a caller that unpacked two values
and a definition that returned one — git merged them without a textual conflict,
and nothing in the local gate had an opinion about a shape. `bin/prime` runs the
proof last, reads its `32 passed, 0 failed` line rather than trusting the exit
code, and refuses a missing script, a too-old interpreter or a proof that stopped
running cases. See [DEBT.md](DEBT.md).

- a **chained axum router**, `Router::new().route("/a", get(h)).route("/b", post(h2))`,
  which holds two routes on one line. A recogniser that returned the first match
  would miss the second, and one that read the handler method from the start of
  the line would call the second route's `POST` a `GET`. Both were real, both were
  silent on every fixture core ships, and neither is reachable from a fixture
  whose lines each register exactly one route.
- **identity's own `admin.go` shape**, read out of the repository rather than
  invented: a path written on one line, the middleware on the next, and the path
  **concatenated** — `r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/audit-log", …)`.
  Reading one line gave a path that exists nowhere and a handler window of zero
  called three of identity's admin routes `scoping-bypassed`. Both were real, and
  both were false alarms on the very repository this packet's successor is told to
  adopt first. The concatenation resolves each non-literal term to `{}`, so the
  declared path is `/v1/accounts/{accountID}/{}/audit-log`.
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
# REPORT — core-tenancy-enum

**Packet:** D18 step 1 of 3. Which entry points in a service are account-scoped
becomes a declaration core owns, validates and reports on.
**Branch:** `worker/core-tenancy-enum` · **Four commits, never pushed.**
**Suite: 295/295** (was 280). **Red proof: 21/21**, 15 reds naming their finding,
6 clean. **`mypy --strict`: clean** on the new module.

---

## 1. The checker run across all nine in-scope repositories

`harness/bin/account-scope-check <repo> --json`, against each repository's
`master` at the commits recorded in the sweep. **Nothing is adopted yet, so every
row is the same row** — and that is the correct verdict, not a defect:

| repo | exit | account-scoped | not-account-scoped | undeclared | failures | warnings | finding |
|---|---|---|---|---|---|---|---|
| identity | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| courier | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| guard | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| site | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| parlor | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| pantry | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| caf | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| kit | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |
| core | 1 | 0 | 0 | 0 | 1 | 0 | `account-scope.declaration-missing` |

**9/9 in scope, 1 failure each, no other finding, zero warnings. 0 account-scoped
entry points declared anywhere in the fleet.** That is the number D18 asked for,
and it is a statement about declarations rather than about routes.

### The second measurement, which is the one with a defect in it

Running the checker's answer is uninformative when nothing is declared, so I also
measured **how many registrations the recognisers can SEE** in each repository.
This is a measurement of the *checker's reach*, not of the service's surface, and
it is emphatically **not** comparable to the route counts D18's grep produced:

| repo | registrations seen | files | by recogniser |
|---|---|---|---|
| identity | 42 | 9 | chi=42 |
| courier | 66 | 9 | phoenix=66 — **of which 52 are in `deps/`** |
| guard | 18 | 5 | hono=18 — **9 of which are in `*.test.ts`** |
| site | 6 | 3 | next-app=6 |
| parlor | 6 | 3 | next-app=6 |
| pantry | 4 | 1 | axum=4 |
| caf | 0 | 0 | (none) |
| kit | 0 | 0 | (none) |

Three things in that table are real and two of them found defects:

1. **`site` and `parlor` read as zero routes, and it was MY defect.** Both are
   Next.js; both serve their entire `/v1` surface from one catch-all
   `src/app/v1/[...path]/route.ts` whose methods are named exports, so the path is
   in the **file name**. A recogniser that needed the path in the line saw no
   routes — D18's `route_defs=0`, reproduced by the tool written to stop it, on
   two of the three Next.js-shaped repositories in scope. Fixed: `next-app`
   recogniser, `Recogniser.path_from_filename`, and the two costs that fixing it
   exposed (`[` and `]` are legal in a declared path; the `stale` check had to be
   given the file's path too or it called all four Next.js routes stale).
2. **`courier` reaches 66 because it vendors `deps/`, and 52 of those are
   Phoenix's and Plug's own router, not courier's.** This is a **consequence of
   how `surface.sources` is declared**, not a bug: a service names its own router
   *file*, so `deps/` is never read. It is recorded here because it is the number
   a reader would get from a naive whole-tree scan, and it is 78% wrong.
3. **`guard` reaches 18 of which 9 are in test files** — the same point. It is why
   the schema says *files rather than directories wherever the repository allows
   it*, and why `surface.minimum` is a count of one file.
4. **`caf` and `kit` reach 0, and I checked both by hand rather than reporting 0.**
   `caf`'s only HTTP surface is `internal/mcp/server.go`, which hands an SDK
   `StreamableHTTPHandler` a function and registers no route line this checker
   recognises. `kit` is a library: no router at all, and `examples/valid/
   account-scope.no-surface.yml` is its legal spelling (`surface.kind: none`).

### The checker has been seen to fail

Brief item 5, and the evidence is `harness/tests/account_scope_self_test.sh`:
**15 planted defects, each going red naming its finding**, over 6 clean controls
including the control that runs first. Every one of the 14 findings has a case.

---

## 2. What I deliberately did NOT do, and why

- **No fleet adoption.** Adopting `account_scope.yml` in any service is D18 step 3
  and a separate packet per repository. Every row in the table above is a
  `declaration-missing`, and that is the state this packet is supposed to leave.
- **No step 2.** The harness that proves a *service's own queries* are scoped
  belongs in `kit` and is owed against this contract. I did not write it.
- **`billing`, `darkroom`, `muse` were not developed, proposed for, or required
  by anything here.** I ran the reach measurement against `darkroom` and `muse`
  once while looking for recogniser shapes — it found no new syntax and changed no
  decision. Their numbers are not in the report above and are not a defect.
- **No change to `tenancy.yml`, `tenancy_check.py`, `gate_check.py`,
  `db_isolation_check.py` or `cafaye_contract.py`.** See §3.
- **`scoping-bypassed` was not made decidable for Phoenix or axum.** I would have
  had to model `pipeline` blocks and `Router::new().route(…, get(h), layer(…))`,
  and a guess about where middleware is attached is a checker crying wolf on
  correct code. Declared as `Recogniser.carries_handler` instead, with two
  negative controls proving it does not fire there.
- **No floor on the number of *undeclared* registrations.** `surface.minimum` is a
  floor on the *total*, which catches a route that appeared somewhere unreadable.
  It does not catch a service that declares eight of its thirty routes, and I
  chose not to invent a second number that would look like it does.
- **Ruff was not applied as a gate.** `core` has no ruff configuration, does not
  run it in `bin/prime` or CI, and every existing harness module fails its default
  rule set (ISC004 in `tenancy_check.py`: 8, `breaking_tiers.py`: 2). Mine matches
  house style at 26. Changing that is not this packet's business.
- **No `account_scope.yml` for core.** Core has no entry point of its own, so it
  would be a `kind: none` file that exists to say nothing. Recorded as the
  successor's call rather than decided here.

---

## 3. Conflicts with existing published schemas, and how I left them

**One real conflict, inside this packet, found and fixed in the same commit.** No
pre-existing schema was changed.

| conflict | what happened | left as |
|---|---|---|
| `sourcePath`'s pattern refused `[` and `]` | Next.js puts a bracketed parameter **in the file name**, so the schema refused two in-scope services' own routes. A pattern written for one framework's spelling refusing another's — the same class as the recognisers, one layer down. | Widened in `schemas/account-scope.schema.json` **and** in the checker's hand-rolled copy, in the same commit. `test_the_account_scope_checker_and_the_schema_agree_on_every_example` now covers nine documents including both extra fixtures, so a second widening has to be made twice. |

**Deliberate non-conflicts**, stated because a reader will wonder:

- **`accountScoped` means something different in the two files.** In
  `tenancy.yml` it is service-level ("does this service scope anything"); here it
  is per entry point. I did **not** rename either. The per-entry-point field is the
  one that has to carry a value per route, and renaming a published schema field
  because a new file uses a familiar word is a breaking change bought for tidiness.
  Instead the doc has a two-row table saying which is which, and
  `account-scope.service-disagrees` catches the failure that would actually bite:
  two files in one repository naming two different services.
- **`entryPoints` is the key name in both files.** Different shape entirely
  (`{via, file, line}` here; `{operation, subject, enforced, negative}` there).
  Same word, different contract, same as `version` and `name` — and identical in
  every existing cafaye schema pair, so this is the house convention rather than a
  new ambiguity.
- **`numeric-check` moved 31 → 34 numeric positions.** That test is a ratchet by
  design and it told me to re-measure rather than loosen the assertion. Re-measured:
  this schema's three bounded integers (`line` ≤ 1000000, `minimum` 0..4096) are
  all legal, warnings unmoved at four, `numeric.float64-unsafe` still fires on
  none. The number in the test and the reason it moved are in a comment beside it.

---

## 4. The successor's first move

**Adopt the format in `identity`, and measure it against identity's own
`tenancy.yml`.** It is the only in-scope repository with both files already in
existence (`tenancy.yml` landed with `identity-28`), and its router is 42
recognised chi registrations in 9 files — the largest single surface in scope.

The first thing to write down, before any other work:

> `identity`'s `internal/httpapi/accounts.go` registers **10** routes
> (`accounts.go:586-597`), of which **9** go through `o.requireAccount` /
> `o.requireAccountRole`. Every one of the 10 needs a row in
> `identity/account_scope.yml`, including the one that does not — and the
> question "which of the 10 reaches another account's data" is the one this
> packet makes answerable.

Then, in order:

1. **`identity/account_scope.yml`** against `schemas/account-scope.schema.json`,
   `surface.sources: [internal/httpapi/accounts.go, internal/httpapi/auth.go,
   internal/httpapi/recovery.go, …]` as **files**, `surface.minimum` set to what
   those files hold on the day it is written, and `accountKey` left out so
   `tenancy.yml`'s `scope.key` is read instead.
2. **Expect `scoping-bypassed` on at least one route, and decide whether that is
   a real bypass or a route scoped by a different mechanism.** `identity` wraps
   handlers in `o.sessionCredentialOnly(...)` as well as `o.requireAccount(...)`,
   so `via` will have to be `sessionCredentialOnly` for the routes that use it —
   and a finding here that is a false alarm means `via` needs a second
   mechanism per entry point rather than a looser check. **Write that down either
   way.** This is the successor's first real design question and it is not mine
   to pre-answer.
3. **`gate.yml` in identity** (`gate.yml:no` per D17) is independent and
   unchanged by this packet. Do not bundle it.
4. **Then one repository per worker**, with the same nine as scope.

**Not to be attempted here:** step 2 (the `kit` harness), which needs this
contract landed — it now is — and which must not be written against a format with
zero adopters, because D18's third step is seven different idioms and the packet
that writes the harness against one adoption is the one that makes that likely.

### If work remains, the handoff is this file

Nothing is half-landed. Every commit is green on 295/295, 21/21 and
`mypy --strict`; the four commits are independent and a manager can merge them as
one or read them separately.
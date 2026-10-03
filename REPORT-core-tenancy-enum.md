# REPORT — core-tenancy-enum

**Packet:** D18 step 1 of 3. Which entry points in a service are account-scoped
becomes a declaration core owns, validates and reports on.
**Branch:** `worker/core-tenancy-enum` · **Six commits, never pushed.**
**Suite: 295/295** (was 280). **Red proof: 26/26** — 19 going red naming their
finding, 7 clean. **`mypy --strict`: clean** on the new module.

---

## 1. The checker run across all nine in-scope repositories

`harness/bin/account-scope-check <repo> --json`, against each repository's
`master`. **Nothing is adopted yet, so every row is the same row** — and that is
the correct verdict, not a defect of the checker:

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

**9/9 in scope · 1 failure each · no other finding · zero warnings · 0 account-scoped
entry points declared anywhere in the fleet.** That is the number D18 asked for,
and it is a statement about declarations rather than about routes.

### The second measurement, and the five defects it found

Running the checker is uninformative when nothing is declared, so I also measured
**how many registrations the recognisers can SEE**. This is a measurement of the
*checker's reach*, not of the service's surface, and it is **not** comparable to
the route counts D18's grep produced:

| repo | registrations seen | files | by recogniser |
|---|---|---|---|
| identity | 42 (41 production + 1 in a `_test.go`) | 9 | chi=42 |
| courier | 66 | 9 | phoenix=66 — **52 of them in `deps/`** |
| guard | 18 | 5 | hono=18 — **9 of them in `*.test.ts`** |
| site | 6 | 3 | next-app=6 |
| parlor | 6 | 3 | next-app=6 |
| pantry | 4 | 1 | axum=4 |
| caf | 0 | 0 | (none) |
| kit | 0 | 0 | (none) |

**Five defects came out of this measurement and reading the real routers behind
it, and every one of them was a false alarm.** Not one of them is reachable from a
fixture whose lines each register one route in one framework's plainest syntax —
which is the shape every fixture core ships had:

1. **`site` and `parlor` read as zero routes.** Both are Next.js; both serve their
   whole `/v1` surface from one catch-all `src/app/v1/[...path]/route.ts` whose
   methods are named exports, so the path is in the **file name**. Fixed with
   `Recogniser.path_from_filename`. D18's `route_defs=0`, reproduced by the tool
   written to stop it, on two of the three Next.js-shaped repositories in scope.
2. **The chi pattern captured the RECEIVER.** `r.Get("/v1/x", h)` read as method
   `r`, so `same_route` refused every correctly declared route and would have
   reported **all forty-two of identity's** `undeclared`. Re-read across identity's
   router it is now 20 POST / 13 GET / 2 PATCH / 7 DELETE.
3. **axum chains.** `Router::new().route(a, get(h)).route(b, post(h2))` is two
   registrations on one line; a single-match recogniser saw one.
4. **axum's method sits in the handler position, mid-line**, and the pattern was
   anchored to the start of the line — so it read the first handler on the line
   and called the second route's `POST` a `GET`.
5. **identity's `admin.go` concatenates the path and splits it across two lines.**
   `r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/audit-log",` on one line and the
   middleware on the next. Reading one line gave a path that exists nowhere (three
   routes permanently undeclared) and a handler window of zero called the same
   three `scoping-bypassed`. **Both are false alarms on the very repository the
   successor is told to adopt first**, which is why I spent the time reading it
   rather than shipping after the suite went green.

**Defects 2–5 were invisible to the test that existed.** It asserted "the
recogniser matches its own example" and the example was a `mux.HandleFunc("GET
/…")` line, so it could not see a defect in the `r.Get(…)` branch; and every
fixture's lines each registered exactly one route. The test now asserts **the
method**, and the proof carries a chi router with one GET and one POST on the same
path — with the negative control that declaring them swapped goes red, because
without that control the green would pass for the wrong reason.

**`caf` and `kit` reach 0, and I checked both by hand rather than reporting 0.**
`caf`'s only HTTP surface is `internal/mcp/server.go`, which hands an SDK
`StreamableHTTPHandler` a function and registers no route line this checker
recognises. `kit` is a library with no router, and
`examples/valid/account-scope.no-surface.yml` is its legal spelling
(`surface.kind: none`).

**The checker has been seen to fail** — brief item 5. Every one of the 14 findings
has a case in `harness/tests/account_scope_self_test.sh`, each going red **naming
its finding**, with the control running first.

---

## 2. What I deliberately did NOT do, and why

- **No fleet adoption.** That is D18 step 3, one packet per repository. Every row
  above is a `declaration-missing` and that is the state this packet should leave.
- **No step 2.** The harness that proves a *service's own queries* are scoped
  belongs in `kit`, owed against this contract, and must not be written against a
  format with zero adopters — D18's own failure mode is seven different idioms and
  the seventh is the one somebody copies.
- **`billing`, `darkroom`, `muse` were not developed, proposed for, or required by
  anything here.** I looked at `darkroom` and `muse` once while hunting for
  recogniser shapes; it found no new syntax and changed no decision. Their numbers
  are absent from this report and are not defects.
- **No change to `tenancy.yml`, `tenancy_check.py`, `gate_check.py`,
  `db_isolation_check.py` or `cafaye_contract.py`.** See §3.
- **`scoping-bypassed` was not made decidable for Phoenix, axum or Next.js.** Doing
  so means modelling `pipeline` blocks, `Router::new().route(…, get(h), layer(…))`
  and Next.js middleware, and a guess about where middleware is attached is a
  checker crying wolf on correct code. Declared as `Recogniser.carries_handler`
  instead, with negative controls proving it does not fire there.
- **No floor on the number of *undeclared* registrations.** `surface.minimum` floors
  the *total*, which catches a route that appeared somewhere unreadable. It does
  not catch a service that declares eight of its thirty routes, and I did not want
  to invent a second number that reads as though it did.
- **Ruff was not applied as a gate.** `core` has no ruff configuration, runs it
  nowhere in `bin/prime` or CI, and every existing harness module fails its default
  rule set (ISC004 in `tenancy_check.py`: 8, `breaking_tiers.py`: 2). Mine matches
  house style at 26. Changing that is not this packet's business.
- **No `account_scope.yml` for core.** Core has no entry point of its own, so the
  file would exist to say nothing. Recorded as the successor's call, not mine.
- **I did not run the whole `self_test` suite**, per the brief. I ran
  `account_scope_self_test.sh` (26/26) and the narrow pytest target plus the full
  `tests/` suite, because the new tests assert things about the existing harness
  (stdlib-only, no-process, the CI step) and a narrow run would not have exercised
  them.

---

## 3. Conflicts with existing published schemas, and how I left them

**One real conflict, inside this packet, found and fixed in the same commit. No
pre-existing schema was changed.**

| conflict | what happened | left as |
|---|---|---|
| `sourcePath`'s pattern refused `[` and `]` | Next.js puts a bracketed parameter **in the file name**, so the schema refused two in-scope services' own routes. A pattern written for one framework's spelling refusing another's — the same class as the recognisers, one layer down. | Widened in `schemas/account-scope.schema.json` **and** in the checker's hand-rolled copy, in the same commit. The agreement test now covers nine documents including all three fixtures, so a second widening has to be made twice. |

**Deliberate non-conflicts**, recorded because a reader will wonder:

- **`accountScoped` means something different in the two files.** In
  `tenancy.yml` it is service-level ("does this service scope anything at all");
  here it is per entry point. I did **not** rename either. Renaming a published
  schema field because a new file uses a familiar word is a breaking change bought
  for tidiness, and the per-entry-point field is the one that must vary per route.
  The doc carries a two-row table saying which is which, and
  `account-scope.service-disagrees` catches the failure that would actually bite:
  two files in one repository naming two different services.
- **`entryPoints` is the key name in both files**, with a different shape
  (`{via, file, line}` here; `{operation, subject, enforced, negative}` there).
  Same word, different contract — exactly as `version` and `name` are, and
  identical in every existing cafaye schema pair, so this is the house convention
  rather than a new ambiguity.
- **`numeric-check` moved 31 → 34 numeric positions.** That test is a ratchet by
  design and it told me to re-measure rather than loosen the assertion. Re-measured:
  this schema's three bounded integers (`line` ≤ 1000000, `minimum` 0..4096) are
  all legal, warnings unmoved at four, `numeric.float64-unsafe` still fires on
  none. The new number and the reason it moved are in a comment beside it.

---

## 4. The successor's first move

**Adopt the format in `identity`, and measure it against identity's own
`tenancy.yml`.** It is the only in-scope repository where both files already exist
(`tenancy.yml` landed with `identity-28`), and it is the largest single surface in
scope: **41 production registrations in 9 files under `internal/httpapi`**.

Write this down before any other work — it is the measurement, and it is what the
declaration has to answer:

```
  internal/httpapi, measured 2026-10-03 at identity master:

    41 production registrations in 9 files
    methods: 20 POST · 13 GET · 7 DELETE · 2 PATCH  (was 41 × "r" before the fix)

    first wrapper on the registration line:
      sessionCredentialOnly   18
      requireAccountRole      12
      (none on the line)      10
      handleReadyz             1

    those 10, and they are the ones a declaration has to answer for:
      GET|DELETE|POST  /v1/accounts/{accountID}/{}/admin/...   admin.go:122,125,128
      POST  /v1/introspections                      apikeys.go:419
      POST  /v1/users                                auth.go:129
      POST  /v1/session                              auth.go:130
      GET   /v1/me                                   auth.go:140
      GET   /healthz                                 httpapi.go:236
      GET|DELETE /v1/accounts/{accountID}/oidc-clients/{clientID}   oidc.go:1269,1271
```

Then, in order:

1. **`identity/account_scope.yml`** — 41 rows plus the `_test.go` one if the test
   file is in scope. `surface.sources` as **files** (the nine under
   `internal/httpapi`, not the directory), `surface.minimum` set to what those hold
   today, and `accountKey` omitted so `tenancy.yml`'s `scope.key` is read.
2. **`via` is the first real design question and it is not mine to pre-answer.**
   identity wraps handlers in `sessionCredentialOnly` (18) and
   `requireAccountRole` (12), and the 12 admin routes nest one inside the other —
   `requireAdminToken(requireAccountRole(…))`. The format has exactly ONE `via`
   per entry point. **Either the three outer wrappers each get a row, or `via`
   grows a list, or a service is forced to name the innermost wrapper and lose the
   outer one.** All three are defensible and the choice changes the schema. Record
   the decision in `DECISIONS.md` with a number; do not resolve it in a comment.
   Note that `requireAccountRole` and `requireAccount` are matched on a word
   boundary and are correctly distinct symbols.
3. **The 10 routes with no wrapper on the registration line are the interesting
   ones.** `/healthz` is `public`. `/v1/me` and `/v1/session` reach the caller's
   own account and are the format's easy case. The two `oidc-clients/{clientID}`
   routes have NO wrapper on the line — read them before declaring them, because
   "no wrapper visible" and "not account-scoped" are different claims and only one
   of them is this checker's to make.
4. **`gate.yml` in identity** (`gate.yml:no` per D17) is independent. Do not
   bundle it.
5. **Then one repository per worker**, same nine as scope, so two workers never
   write the same file.

### The honest limit to hand the next person

Six syntaxes are recognised and a seventh is invisible. A service whose routes are
in a syntax core has not been read from gets a **clean** answer over the routes it
cannot see, and `surface.minimum` is the only thing that notices. If a second
framework shows up in the fleet, **add a recogniser with its line in
`harness/tests/fixtures/account-scope/shapes/`, not a broader pattern** — that is
what the last three defects in §1 were, and each of them looked like a pass.
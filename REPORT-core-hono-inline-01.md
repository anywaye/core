# REPORT-core-hono-inline-01

**What this packet is.** `guard` landed an `account_scope.yml` whose seventh route —
`GET /v1/me` — could not be declared, because both honest declarations were answered
by a failure, and one of the two failures was FALSE. This is the checker being
behind, not the declaration.

**Result.** `scoping-bypassed` now reads the chain a Hono app runs in front of a
handler. `guard` goes from deliberately-red to **exit 0** with its declaration
untouched by me, `scoping-bypassed` and `declaration-contradicts-code` are both
unchanged in strength, the self-test is **57 cases, 0 failed** (43 on master), and
core's gate is green at 299/299.

| | before | after |
|---|---|---|
| `guard`, seven rows, `via: requireJwt` | exit 1, `scoping-bypassed` | **exit 0** |
| `guard`, seven rows, `accountScoped: false` | exit 1, `declaration-contradicts-code` | exit 1, `declaration-contradicts-code` — **unchanged** |
| `guard`, six rows, route omitted | exit 1, `undeclared` | exit 1, `undeclared` — **unchanged** |
| `guard`, its own declaration on master | exit 1 | **exit 0** |
| `identity` | exit 0, 1 warning | exit 0, 1 warning — **inert** |
| `site`, `parlor` | exit 0 | exit 0 |
| red proof | 43 cases, 0 failed | **57 cases, 0 failed** |

Every number in that table was measured by running both checkers over the same
trees; §7 has the commands.

---

## 1. Does a Hono route with an inline handler join `carries_handler`'s set?

**No, and the reason is checkable rather than convenient.**

`carries_handler` is one flag with one job, and the job is decided by reading it:

```python
#: Whether this syntax puts the HANDLER on the same line as the path, which is
#: what makes `account-scope.scoping-bypassed` decidable.
carries_handler: bool = True
```

Its question is *is the handler on the registration line*. Hono's answer is yes —
for both shapes, `app.post("/auth/login", bff.requireSameOrigin, bff.login)` and
`app.get("/v1/me", (c) => c.json(c.get("principal")))`. Setting it `False` would be
asserting something untrue about Hono's syntax in order to obtain a silence the flag
was never a mechanism for.

The packet's framing — "a Hono route with an inline handler is a third member of that
set without being in it" — is the one thing I have to push back on, because the
membership test in that docstring is not *the handler is an inline function*. It is:

> "for those two the route's own line says nothing about scoping, and reporting it
> would report courier's real router as unscoped"

`app.get("/v1/me", (c) => c.json(c.get("principal")))` is not a member, because its
own line says a great deal about scoping. It says the handler does not call the gate.
That is a **true** statement about the line. What the line does not say is whether
some *other* line runs first — which is a different question with a different answer,
and that is what §2 is about.

**And the alternative is measurable rather than arguable.** `carries_handler=False` on
the Hono recogniser does silence the false positive — and it silences the check, on
every Hono route in the fleet, forever. Self-test **case 49** runs it: it takes the
repository from case 45, where the gate has been commented out and `/v1/me` really
does resolve no account while its declaration says it is scoped, patches the flag, and
requires the patched checker to find the bypass. It does not:

```
--- case 49 (THE DIRECTION): carries_handler=False on the Hono recogniser leaves a
  GENUINELY UNGATED route silent
  the rejected flag is blind here, which is why §1 says no
    a route with no gate at all, declared scoped, and the checker is quiet
```

So the flag would buy the false negative by accepting a real cross-account read. That
is the trade `carries_handler`'s own docstring refuses, and a case is the only way a
reader can check that instead of taking it on trust.

**What the flag became.** `carries_handler` stays `True` for Hono and a second,
different flag is declared beside it:

```python
chain_read: bool = True
```

`carries_handler` asks *is the handler on the registration line*. `chain_read` asks
*is the chain in front of it readable*. They agree across the current roster, and they
are still two questions: the pair `(True, True)` is chi, `(True, True)` is Hono once
`chain_gate` exists, and the two differ the moment a framework grows a mount —
`chain_read` is the field that would go `False` then, on one recogniser, with the
reason written next to it.

---

## 2. Making `GET /v1/me` declarable

**I took the `app.use` pipeline.** The other honest way — a recogniser that
understands an inline handler resolving a principal — is not a second option here, it
is the *opposite* of the fix, and it is worth saying why in full because the packet
offers it as a peer.

guard's `/v1/me` has two arms and only one of them is the bug:

- `accountScoped: true, via: requireJwt` → `scoping-bypassed`. **FALSE.** The route
  is behind the gate.
- `accountScoped: false` → `declaration-contradicts-code`. **TRUE.**
  `app.get("/v1/me", (c) => c.json(c.get("principal")))` puts the caller's principal
  on the wire, and the evidence the finding prints is the registration line. The route
  genuinely resolves an account and genuinely returns it.

So the honest declaration is the first arm, and the finding blocking it is
`scoping-bypassed`. A "recogniser that understands an inline handler" would have to
quiet *the second* finding — the true one — because there is nothing else it could
mean. That is precisely the outcome the packet names as the worst available: a fix
that makes the checker quiet about the route without making its account-resolution
visible. Self-test **case 48** asserts the second arm still fires, in the same
fixture, so the trade cannot be made quietly later either.

The route's account-resolution is not made invisible by anything here. `requireJwt`
verifies the bearer token, `principalOf` reads `payload.account_id` at
`src/middleware/jwt.ts:346`, `accountFrom` still names the symbol **and** the line, and
`account-key-lost` still checks that line carries the key. Nothing in this packet
touches that path.

### What was added

`chain_gate` reads the `app.use` mounts registered **above** the row's own line, in
the file the row names, and asks three questions of each:

| question | why it has to be asked, and what decided it |
|---|---|
| **is it above?** | registration order is the only reason a `use` is in front of a route at all. guard's own comment at `src/index.ts:157` says a limiter mounted after a route is a limiter that does not run. Case 46. |
| **does it cover this path?** | `/v1/*` over `/v1/me`, yes; `/v1/*` over a `/v2` route, **no**. Cases 39 and 42 — 42 deletes the comparison from a copy of the checker and shows the `/v2` row going green, which is the false green the comparison exists to prevent. |
| **does it name `via`?** | on the mount's own line or within `HANDLER_WINDOW` below it, because the middleware body is on the lines after the `app.use(`. Case 37. |

`mount_covers` returns `(covers, decided)` and keeps them apart, because they are two
answers. A `*` in the middle, a RegExp or a trailing `:param` is **neither** — not
covered *and not decided* — and the difference matters: reading an unevaluated pattern
as "does not cover" is how a `use` that matches nothing becomes the gate for every
route in a file. `notEnforced` carries the entry and its measurement.

### The third answer, which is neither yes nor no

A mount whose middleware is a bare identifier defined in **another module** —
`api.use("/*", accountGate)` in the `hono_composed` fixture — cannot be followed. The
route is **not** called unscoped. That is `carries_handler`'s own refusal restated
for a chain that left the file, and the alternative is a wolf on a correct row: case
40 asserts the finding is absent, case 43 asserts it comes back the moment the rule is
deleted from a copy of the checker.

The price is a row that is silent in **both** directions, with no warning. That is
**D45**, and I recommend leaving it silent and spending the next packet on the option
that removes the question — resolving the mounted middleware through the module index
— rather than the option that describes it, because the warning that would describe it
fires on **0 of the 61 rows** this fleet declares today, and a warning nobody reads is
worse than the silence it replaces because it looks like coverage.

### What did not change

`scoping-bypassed`'s message, its severity and its `remediate` text are byte-identical.
`declaration-contradicts-code` is not touched at all. The only change to the decision
is one more clause — "or a covering mount above it" — and each of its three terms is
something the checker decides rather than assumes.

---

## 3. The Go path constant: measured, and LEFT ALONE

Item 3 asks whether to recognise `r.Get(socialLoginPrefix+"/{provider}/callback", …)`
— a path whose first term is an **identifier** rather than a string literal. Four
registrations in identity are written that way:

```
internal/httpapi/oidc.go:142:  r.Get(oidc.PathLogin+"/{"+oidcRequestParam+"}", o.handleOIDCLogin)
internal/httpapi/oidc.go:143:  r.Post(oidc.PathLogin+"/{"+oidcRequestParam+"}", o.handleOIDCLogin)
internal/httpapi/oauth.go:161:  r.Get(socialLoginPrefix+"/{provider}", o.handleSocialStart)
internal/httpapi/oauth.go:162:  r.Get(socialLoginPrefix+"/{provider}/callback", o.handleSocialCallback)
```

I applied the smallest possible pattern change to a **copy** of the checker — an
optional identifier-first alternative in the chi recogniser, routed to the existing
`concatenated_path` — and ran it over `identity`. **It makes things worse**, and by a
number rather than a judgement:

| | shipped | identifier-first |
|---|---|---|
| `identity` exit | 0 | **1** |
| findings | 1 × `contradiction-unreadable` | 3 × `undeclared` |
| what is named | `social-login-callback` | `oidc.go:142` → `GET /{{}}`, `oidc.go:143` → `POST /{{}}`, and **`oidc.go:1269` → `GET /v1/accounts/{accountID}/oidc-clients/{clientID}`** |

Three things are wrong with that and only the first is obvious.

1. `oidc.go:142` is `oidc.PathLogin + "/{" + oidcRequestParam + "}"` — a Go path
   assembled from **fragments**, not from a leading literal and a concatenation.
   `concatenated_path` searches for the first `/`-starting literal, which is `"/{"`,
   and produces `/{{}}`: a path that exists nowhere and that no declaration can match,
   so the change converts one `contradiction-unreadable` **warning** into two
   `undeclared` **failures**.
2. `oidc.go:1269` is a route this checker reads **correctly today**, and the change
   makes it `undeclared`. A change whose first effect is a regression on a
   working row is not a small change.
3. Both need `socialLoginPrefix` and `oidc.PathLogin` resolved to their values to be
   honest, and `oidc.PathLogin` is declared in **another package** — the second
   resolution this file refuses to make everywhere else. Without it the leading
   identifier has to be dropped, which loses information the existing convention
   (`{}` for an unreadable term, stated in `notEnforced`) says not to lose.

So: **left, and said so.** The defect is real and is not this packet's. The one-line
follow-up that would take it honestly is resolving the identifier's value through the
index first — and then the fragments case (`"/{" + name + "}"`) is still a third
shape that has no `{}` convention yet.

---

## 4. The self-test

**57 cases, 0 failed** — 43 on master, so strictly more, and the fourteen new ones
are on three fixtures measured out of `guard/src/index.ts` rather than invented.

| | fixture | what it decides |
|---|---|---|
| 36–44 | `hono_pipeline` | what a chain reader may conclude once it can **see** a mount: the gate above the route, the gate on the line, a mount on another prefix, a mount in another file, and three THE BREAKING cases |
| 45–49 | `hono_surface` | every way a gate can be **absent**: commented out, below the route, not covering this path — plus the inline arm and the rejected flag |

The three THE BREAKING cases each delete a named piece of the checker from a
**throwaway copy** and require the defect to return:

- **41** deletes `and (on_line or in_chain)` and case 36's repository goes red.
- **42** replaces the prefix comparison with `return True, True` and the `/v2` row
  goes green — a false green, caught by the case.
- **43** replaces `readable = not composed` with `readable = True` and the mounted
  sub-application's route is accused, which is the wolf.

### Two things this suite got wrong before it got them right

Both are written down in the file, because a red proof that cannot tell "the fix is
absent" from "the case never ran" is the thing the file is for.

**A breakage that did not apply still got counted.** Case 46's first version swapped
the gate block with the route block. That moves `/v1/me`'s own registration up seven
lines, so the row's `registeredAt` ended up pointing inside the gate, the row stopped
being `REGISTERED`, `scoping-bypassed` became undecidable for it — and the case went
**clean**, for a reason that had nothing to do with order. It now MOVES the gate
(commenting it where it was, re-mounting it below the route, and re-pointing the three
rows the move shifts) and asserts the two facts the case is about: the route's line
did not move, and the gate is below it.

**And a failed precondition was silent.** A python breakage that raised on its own
`assert` exited non-zero, the shell carried on, and the assertion below it read the
**unpatched** fixture — so the case reported whatever the unpatched fixture happens to
say. Cases 37, 38, 39, 41, 43, 45, 46, 47, 48 and 49 are now wrapped in `if … then`,
and `unapplied` reports that a case did not run rather than letting it be scored. This
caught a real one: case 45's line-count edit was dropping 54 lines and the case passed
anyway.

### The numbers

```
51 → 57 cases
red proof        52 passed, 6 failed   (against HEAD's checker — commit 2519151)
red proof        57 passed, 0 failed   (against this one)
suite            299/299 passed
gate             green
```

---

## 5. What is still not decided

**D45 — a chain the checker cannot follow is silent in both directions.** Written up
with the measurement, the three alternatives and the cost of each. Recommendation:
leave it silent, and resolve the mounted middleware through the module index next.

**`app.route` is read as axum's `.route(path, handler)`.** `app.route("/v1", v1())`
becomes `undeclared: axum registers /v1`. This is a **real and separate defect** and
it is deliberately **left in** the `hono_composed` fixture rather than written around
with `app.mount`, because a fixture that dodged it would leave the next reader
believing the collision does not exist. Measured: **1** in the fixture, **0** in the
fleet's seven services — the only other `.route(` outside `node_modules` is
Playwright's `page.route` in two e2e specs, which no `surface.sources` names. The
collision is real and it is in `notEnforced`.

**A mount whose path is not a literal.** `app.use(ROUTE_MOUNT, proxy)` at
`guard/src/index.ts:207`, where `ROUTE_MOUNT = "/v1/*"`. **1 of guard's 4.** It is
neither credited nor treated as a barrier, so `scoping-bypassed` still fires on a
route behind it — the loud direction, deliberately, and one row in the fleet.

**A wildcard `mount_covers` cannot evaluate.** **0 in the fleet**, where both of
guard's wildcard mounts spell it as a bare `*` or a trailing `/*`. The gap is
theoretical today.

**Nothing was touched in `guard`, `identity` or any other service.** `guard` needed
nothing: its own master commit `ca7ca70` had already added the seventh row, and this
checker is what makes that row expressible.

---

## 6. Commits

| | |
|---|---|
| `2519151` | the red proof, before the fix — 3 fixtures, 14 cases, 52 passed / 6 failed against HEAD's checker |
| `4b25c12` | `chain_gate`, `mount_covers`, `Chain`, `Recogniser.chain_read` — 57 cases, 0 failed |
| `8cc81e5` | the doc, four `notEnforced` entries, D45, and the fifth and sixth controls |

Not merged and not pushed, as instructed.

---

## 7. Reproducing every number in this report

```bash
core=/Users/kaka/Code/any/moon/cafaye/wt-m39-core-hono-01
py=/opt/homebrew/bin/python3.12            # any 3.9+; mise's shim is fine too

# guard, its own declaration on master: 1 before, 0 after
cp $core/harness/account_scope_check.py /tmp/after.py   # the before is in commit 2519151^:
git -C $core show 2519151^:harness/account_scope_check.py > /tmp/before.py
cp /tmp/before.py $core/harness/_before.py              # beside the real one: the module's
                                                        # own import guard refuses to run a
                                                        # copy that cannot reach cafaye_contract
$py $core/harness/_before.py /Users/kaka/Code/any/moon/cafaye/guard; echo "before exit=$?"
$py $core/harness/account_scope_check.py /Users/kaka/Code/any/moon/cafaye/guard; echo "after  exit=$?"
rm $core/harness/_before.py

# the two arms of the seventh row, on guard's 7489090 declaration
git -C /Users/kaka/Code/any/moon/cafaye/guard show 7489090:account_scope.yml   # the six-row one

# item 3's measurement, on a copy, leaving the shipped checker alone
$py harness/account_scope_check.py /Users/kaka/Code/any/moon/cafaye/identity    # exit 0
# then apply the identifier-first alternative to a copy and watch it go to 1

# the proofs and the gate
cd $core && bin/prime                                     # 299/299, 57 cases, 0 failed
bash harness/tests/account_scope_self_test.sh             # 57 passed, 0 failed
```
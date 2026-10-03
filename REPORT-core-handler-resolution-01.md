# REPORT — `core-handler-resolution-01`

**Branch:** `worker/core-handler-resolution-01` (from `master` at `59c5ad0`)
**Packet:** `core-handler-resolution-01`
**Date:** 2026-10-03
**Verdict:** both stated defects are fixed and each is proved by removing the fix.
**One of the two stated diagnoses was wrong, and the warning it was attached to was
caused by something else entirely** — §2. **The third warning is a third defect and I
did not fix it**, with the measurement that says why fixing it here would be wrong
(§4). Nothing in `identity` was touched.

---

## 1. What was asked, and what was found

The packet named two defects in `harness/account_scope_check.py` and asked for each
to be fixed with a red-proof case that fails without the fix.

| # | as stated in the packet | verdict | where |
| --- | --- | --- | --- |
| 1 | `_file_defining`'s definition regex cannot match a Go **method**, because "the receiver sits between `func` and the name" | **the stated cause is false**; the row was unreadable for a different reason, which is a third defect and is fixed | `5607366` |
| 2 | `_last_symbol` returns the last token, which is `checks` — an argument — rather than the handler | **confirmed, exactly as stated** | `c9c1828` |
| 3 | the third warning, `healthz` | **not a third defect** — it was defect 1's real cause | `5607366` |
| 4 | the remaining warning after both fixes, `social-login-callback` | **a genuine third defect, in the recogniser, not in handler resolution — not fixed, argued in §4** | — |

Three findings on one declaration turned out to be **three unrelated causes**, and
the packet attributed them to two. Both stated defects were real *in their effect* —
a correct row was reported unverifiable — and one was wrong in its *mechanism*.

---

## 2. Defect 1 as stated is false; the row was unreadable anyway

The packet's claim, quoted:

> `_file_defining` (`harness/account_scope_check.py:1942`) falls back to searching
> for a definition when the bare symbol misses. Its regex is
> `^\s*(?:def|func|fn|function|public|private|export)\b.*\b{tail}\b`
> `func (o options) handleSocialCallback` — the receiver sits between `func` and the
> name. The regex does not match it, so the fallback returns `None`.

**Measured against that exact regex, on that exact line:**

```python
>>> rx = lambda tail: re.compile(rf"^\s*(?:def|func|fn|function|public|private|export)\b.*\b{re.escape(tail)}\b")
>>> bool(rx("handleSocialCallback").search(
...     'func (o options) handleSocialCallback(w http.ResponseWriter, r *http.Request) {'))
True
```

It matches. It matches the bare form too. The reason is the `.*` **between** the
keyword and the name: `func` matches at the start, `.*` consumes ` (o options) `,
and `\bhandleSocialCallback\b` then matches. A receiver is nothing to this pattern.

So the packet's *measured sub-claims* were both true — the index has no
`o.handleSocialCallback`, and a definition search for `handleSocialCallback` finds
`internal/httpapi/oauth.go` on the first try — and neither is why the warning fired.
The row was unreadable because **no registration on the declared surface matched it
at all**, which is a different finding with a different text
(`no registration on the declared surface matched this row`) and a different cause
(§4). The packet read the warning's subject — a Go method — as its mechanism.

This is worth stating plainly because the packet's reasoning about it was careful and
still wrong: it had the right file and the right line number in front of it, and
inferred the cause from the symbol involved rather than from the code path that
emits the finding.

### What actually caused `healthz`

`_file_defining` guarded itself with:

```python
tail = symbol.rsplit(".", 1)[-1]
if tail and tail != symbol:
```

`tail != symbol` is true only for a symbol **carrying a dot**. So the search ran for
`o.handleGetMessage` and was skipped for `handleHealthz` — and `handleHealthz` is
what `r.Get("/healthz", handleHealthz)` names. The docstring immediately above
named `handleList`, a bare name, as a case it handles:

> A bare function name — `o.handleGetMessage`, `handleList` — is found by searching
> for its DEFINITION

The docstring and the code had been disagreeing for as long as both existed. **A
docstring is not a test, and this one had been asserting a capability the code did
not have.** Identity's `/healthz` was reported unverifiable about
`internal/httpapi/httpapi.go` — a file the checker had already opened twice, in a
package whose bare functions it could not name.

### And the guard the removal needed

The test that search used was `func\b.*\btail\b`, and that matches a **parameter**:

```
internal/httpapi/httpapi.go:154:  func New(checks []Check, opts ...Option) http.Handler {
```

A search for the symbol `checks` came back with a file, as though it had found a
handler. It had found an argument. That is worse than finding nothing, for the
reason this codebase states elsewhere — a resolution that lands on the wrong file
produces a confident wrong answer. So a definition must now sit at **paren depth
zero**, which a Go method satisfies with its receiver balanced ahead of it.

---

## 3. Defect 2 is confirmed, and "prefer the callee" would have broken the fleet

The packet's diagnosis is right. `internal/httpapi/httpapi.go:246`:

```go
r.Get("/readyz", o.handleReadyz(checks))
```

`_last_symbol` returned the last identifier on the line. That is `checks`. Resolving
it found nothing, so a correct row was unreadable on the line **directly below**
`/healthz`, which resolved perfectly because `handleHealthz` is both bare and last —
right on one line, wrong on the next, for a reason with nothing to do with the
service.

The fix cannot be "prefer the callee", and this is the part that makes it more than
a regex. Identity also writes:

```go
mux.HandleFunc("GET /v1/x", o.requireAccount(o.handleGetMessage))
```

and there the callee is a **middleware** and the handler is its argument. The two
lines are syntactically identical — a call of a call with a bare identifier inside.
No rule about parentheses, depth or callee-ness separates them, because nothing *in
the line* separates them.

**So the line decides the order and the repository decides the choice.**
`_handler_candidates` returns the symbols that could be the handler, innermost
first, and `handler_for` takes the first that resolves to a file:

| rank | candidate | the line it wins on |
| --- | --- | --- |
| innermost | `checks`, `o.handleWrapped` | whichever of the two actually exists in the repository |
| then callee | `o.handleReadyz` | `/readyz`, where the inner argument is a parameter |
| then argument | `handleHealthz` | a bare handler, which is neither a callee nor nested |

`checks` cannot be returned by accident, because on that line it is the outermost of
the three and the other two are tried first. On a line where it *is* the only
candidate it resolves to nothing and the row is reported unreadable — rather than
checked against a file chosen because it happened to be mentioned there.

One consequence worth recording: **string literals are blanked before the scan.**
A path is a string, so `mux.HandleFunc("POST /v1/messages", …)` otherwise offers
`POST`, `v1` and `messages` as candidates — and `messages` is an ordinary Go
identifier, so a service with a `messages` method would have its route resolved to
whatever that method's file is. The single-symbol version hid this by accident,
because the path literal comes first; a candidate *list* makes it visible.

---

## 4. The third warning is a third defect, and I did not fix it

After both fixes, identity reports **one** warning:

```
WARN account-scope.contradiction-unreadable: social-login-callback: declared
accountScoped: false and this checker could not read the code behind it — no
registration on the declared surface matched this row
```

The row is correct. `internal/httpapi/oauth.go:162` really is:

```go
r.Get(socialLoginPrefix+"/{provider}/callback", o.handleSocialCallback)
```

**The cause is the recogniser, not handler resolution.** The chi pattern requires
the path expression to *begin* with a string literal, so a path built from a Go
constant is invisible to it. Measured:

```
registrations() sees:
  r.Get(socialLoginPrefix+"/{provider}/callback", …)   -> []            <- the gap
  r.Get("/v1/accounts/{accountID}/"+adminPrefix+"/…", …) -> [('GET', '/v1/accounts/{accountID}/{}/audit-log', 'chi')]
  r.Get("/healthz", handleHealthz)                      -> [('GET', '/healthz', 'chi')]
```

The second line is the shape that **is** read, and the difference is that it starts
with a literal. Identity's own declaration says this in as many words and enumerates
twelve routes the checker cannot see; this is that gap, and it is a real defect.

### Why I stopped rather than fixing it

I measured the fix, and it is not safe to land here. Relaxing the chi pattern to
accept a leading identifier, and resolving the constant to `{}` as the existing
concatenation machinery already does:

```
identity registrations: 41 -> 60
newly UNDECLARED: 19
   GET    {}                     internal/httpapi/oidc.go:134
   POST   {}                     internal/httpapi/oidc.go:135
   GET    {}/{provider}          internal/httpapi/oauth.go:161
   GET    {}/{provider}/callback internal/httpapi/oauth.go:162
   ... 15 more
```

Three things follow, and all three are reasons not to do it in this packet:

1. **It cannot fix the row it is aimed at.** The relaxed path is
   `{}/{provider}/callback`, and `same_route` against the declared
   `/v1/auth/oauth/{provider}/callback` is **False** — a `{}` where the prefix was.
   The relaxation makes the registration visible and still does not match, so the
   warning would survive while `undeclared` findings multiply. Reading the
   constant's **value** would be needed too, which is a second and larger feature.
2. **It would make identity red on 19 undeclared routes** the moment it landed, in
   a declaration owned by another session's branch. Fixing a checker by making the
   fleet's only adopter go red is not a fix that can be reviewed in isolation.
3. **It is not a handler-resolution defect**, so it does not belong in a packet
   named `core-handler-resolution`. The recogniser's grammar is a different
   subsystem with a different blast radius: it changes `discover()`, which decides
   `undeclared`, `stale` and `surface.minimum` for every service.

**Recommendation:** a separate packet, `core-recogniser-go-constants`, whose first
step is resolving `socialLoginPrefix`'s **value** rather than writing `{}` — because
`{}` is what makes the match fail, and a relaxation that cannot fix its own motivating
row should not be shipped. Identity's twelve-route enumeration is the specification
for it: those routes are the acceptance criteria, and they are already written down
in the file that needs them.

### The other fleet declarations did not move

Measured before and after, on every declaration in the repository:

| service | before | after | note |
| --- | --- | --- | --- |
| `identity` | 3 warnings | **1** | the two this packet fixed |
| `guard` | 1 failure, 7 warnings | 1 failure, 7 warnings | unchanged — see below |
| `site` | 1 warning | 1 warning | unchanged |
| `parlor` | 1 warning | 1 warning | unchanged |

Guard's six unreadable rows are **not** this defect and are not claimed by it. They
are Hono inline handlers — `app.get("/v1/me", (c) => c.json(c.get("principal")))` —
which name no function at all. There is nothing to resolve, and the honest answer
for an inline handler is what the checker already produces. Its one `undeclared`
failure predates this branch and is unchanged.

---

## 5. The red proof, and two cases that passed for the wrong reason

Cases 26–32 were added to `harness/tests/account_scope_self_test.sh`, on a new
`go_handlers` fixture carrying the spellings of a Go handler position. All three
that can fail without their fix are **breaking** cases in case 24's sense: the fix is
deleted from a *copy* of the checker and the defect is required to return.

| case | asserts | breaks without |
| --- | --- | --- |
| 26 | the fixture is clean | — (control: without it a checker that resolved *nothing* would satisfy 27 and 28) |
| 27 | a **bare** symbol resolves, and one that already resolved still does | the bare-symbol search |
| 28 | **THE BREAKING** — bare search deleted, `/healthz` unreadable again | ✓ |
| 29 | **THE BREAKING** — a *parameter* is not a definition | ✓ |
| 30 | `/readyz` is readable | — (absence of a warning, so a checker that stopped resolving cannot pass) |
| 31 | **THE BREAKING** — candidate list deleted, `/readyz` unreadable again | ✓ |
| 32 | the innermost candidate wins, so a middleware does not stand in for its handler | — (the direction a "prefer the callee" fix gets wrong) |

```
$ timeout 900 bash harness/tests/account_scope_self_test.sh
39 passed, 0 failed
```

### Two cases passed while testing nothing

Both are recorded in the file's header, because a red proof that cannot tell "the fix
is absent" from "the case never ran" is the thing this file exists to be, and these
two were not it.

**Case 29, first version.** It probed a *copy* of the checker by importing it. The
copy crashed on import — `@dataclass(frozen=True)` resolves its own module through
`sys.modules`, and a module not registered there raises `AttributeError` at import —
so the answer came back as an **empty string**. The assertion was
`[ "$guarded" != "NOTHING" ]`, and an empty string is not `NOTHING`, so it took the
**pass** branch. The probe now registers its module before executing it, and a
traceback in *either* answer is a failure.

**Case 31, three of four attempts.** A failed patch is silent, and
`$disabled_checker` is a **single shared path** — so a patch that threw left the
**previous** case's copy in place, and that copy was green. Three attempts patched
the wrong half of the file: the call site is in `handler_for`, which sits *above*
`_handler_candidates`, and my `partition` searched the other side of the anchor.
Each ran against case 29's leftover copy and reported "the defect did not return".

What turned every attempt red was an `assert` on the patch's **own preconditions** —
that the anchor text is present, that the loop is in the half being searched, that
the function really is gone afterwards. That is now what every patch in the file
does before it runs anything, and it is stated in the header next to case 29's
equivalent so the next writer inherits the rule rather than the scar.

---

## 6. What was not done, and why

- **`contradiction-unreadable` severity is untouched.** Still a `warn`, still does
  not move the exit code. The packet's instruction is right and the reasoning is
  worth repeating: its severity is a judgement about what a repository can
  realistically declare, and lowering it to make this packet's output greener would
  be the wrong move in the wrong direction. I have no case from this packet for
  changing it — §4's finding argues the opposite, that the warning is correct to
  fire and the checker is wrong not to.
- **`identity`, `pantry`, and every other worktree and branch: untouched.** All
  measurement was read-only. Reproduced against `core/harness/tests/fixtures/`.
- **No merge, no push, no remote.** Two commits on
  `worker/core-handler-resolution-01`, each with its own breaking case, each
  revertible alone.

## 7. Open decisions

None. The one judgement call — §4's refusal to relax the recogniser — is recorded
here with its measurement and is a recommendation for a named follow-up packet, not
a question for the manager. If the manager would rather have the relaxation landed
now, the one-line change and its consequence are both in §4 and the consequence is
19 new `undeclared` findings in identity's declaration.
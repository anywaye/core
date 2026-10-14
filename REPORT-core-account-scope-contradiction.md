# `core-account-scope-contradiction` — a declaration that lies is green

**Branch** `worker/core-account-scope-contradiction` · **base** `c01f074` (merge of
`worker/core-tenancy-enum`) · **committed, not pushed** · `bin/prime` 295/295, exit 0 ·
`account_scope_self_test` 27 passed / 0 failed.

---

## 1. What was wrong, measured rather than argued

`worker/core-tenancy-enum` shipped a checker that asks *"did the author enumerate
their surface?"* That question has exactly one failure mode left, and the packet
named it: **a complete, schema-valid, entirely false document answers yes.**

The falsification reproduced in this branch, as a committed fixture
(`harness/tests/fixtures/account-scope/liar/`), before the check existed:

```
WARN account-scope.nothing-scoped: all 10 declared entry point(s) are accountScoped: false
OK .../liar: 0 account-scoped, 10 not-account-scoped, 0 undeclared
   — 0 failure(s), 1 warning(s); warnings do not move the exit code
exit=0
```

Ten rows. Every `reason` from the closed vocabulary. Every `registeredAt` on a real
registration line. Five of them lie. **Exit 0, the word `OK`.**

---

## 2. The signal, and why it is not `grep account_id`

The brief's objection was that the obvious signal is too weak "on its own and will
be argued with". It is not weak — **it is wrong in a specific, measurable way**, and
the measurement is on courier's own controllers:

| courier controller | `account_id` refs | of those, **in code** |
|---|---|---|
| `webhook_endpoints_controller.ex` | 5 | 4 |
| `notification_preferences_controller.ex` | 3 | **0** |
| `messages_controller.ex` | 3 | **0** |
| `inbound_controller.ex` | 1 | **0** |
| `health_controller.ex` | 0 | 0 |
| `unsubscribe_controller.ex` | 0 | 0 |

Three facts fall out, and they decide the design:

1. **It fires on `inbound_controller.ex`** — a signed provider webhook that reaches
   no customer row and is honestly `accountScoped: false`. One false positive on the
   repository the packet names, out of one such controller.
2. **On `messages_controller.ex` all three hits are prose.** That is courier's door
   into the send path; its code names no account at all, because `CourierWeb.Plugs.
   Principal` put one on the request before the action was entered and the action
   calls `Deliver.email/2` with a payload. The brief's objection is measured, not
   hypothetical.
3. **courier does not spell it `account_id` in a controller.** It spells it
   `conn.assigns.current_account` — 4 uses in `webhook_endpoints_controller.ex` —
   and in `messages_controller.ex` that spelling occurs exactly **once, inside a
   docstring**.

So the shipped signal is the **resolution chain**, not the word:

| layer | what it reads |
|---|---|
| 1 | **the resolver on the registration line**, named by *this declaration itself* on another row's `accountFrom.via` — the service's own vocabulary, so there is no name list the checker chose and can be wrong about |
| 1b | **the registration line itself**, for frameworks that put an inline handler on it (guard's `app.get("/v1/me", (c) => c.json(c.get("principal")))`) |
| 2 | **the pipeline** — a Phoenix `scope`'s `pipe_through` → `pipeline :authenticated` → `plug CourierWeb.Plugs.Principal` → its line 97, `assign(conn, :current_account, account_id)` |
| 3 | **the handler, and one hop below it** |

Two mechanisms make it CODE rather than a word count:

- **`masked()`** blanks every comment and docstring before any match, preserving line
  numbers exactly. A match is a match in code by construction, and prose cannot be one.
- **`module_index()`** walks the repository and records where each `defmodule` /
  `class` / `type X struct` is defined. Resolution, not convention — guessing
  `lib/<app>_web/controllers/x_controller.ex` from a class name is the same class of
  guess that produced D18's three answers.

**One hop is the cap, and it is capped for a measured reason.** Two hops from
courier's unsubscribe route reaches `Courier.Unsubscribes`, one hop further reaches
the mail adapter, and the adapter holds a customer's address. A check that followed
the chain that far would report a token-authorised callback as account-scoped: right
about the data, wrong about the route.

---

## 3. The fleet measurement

Every registration on each repository's declared router, treated as if declared
`accountScoped: false` — the liar's shape. `truth` is read from each repository (in
courier's case, from its own router comments), not assumed.

```
repo       routes  signal truth   TP   FP   FN  misses
------------------------------------------------------
courier        14       9     9    9    0    0  -
guard           7       1     5    1    0    4  FN POST /auth/register; FN POST /auth/login; FN POST /auth/logout; FN GET /auth/me
pantry          4       0     0    0    0    0  -
parlor          4       0     0    0    0    0  -
site            4       0     0    0    0    0  -
------------------------------------------------------
TOTAL          33      10        10    0    4
```

**courier — the repository the packet names: 9 true positives, 0 false positives,
0 false negatives, out of 14.** The five it does not name are exactly the five that
are honestly `false`:

| route | pipeline | verdict |
|---|---|---|
| `GET /healthz`, `GET /readyz` | `pipe_through :api` | probe. Correctly unnamed. |
| `POST /inbound/resend` | `pipe_through [:api, :inbound]` | signature, not account. Correctly unnamed — **and this is the one the bare grep fires on.** |
| `GET`,`POST /unsubscribe/:token` | `pipe_through :api` | holds a mailbox, resolves no account. Correctly unnamed. |

The two-signal comparison on the same fourteen routes:

| signal | fires on | verdict |
|---|---|---|
| `grep account_id` | 10 routes | wrong on `/inbound/resend`; 3 of its 9 "correct" hits are prose |
| this check | 9 routes | 9 TP, 0 FP |

**pantry — 4 routes, 0 signals, and 0 account-scoped routes exist.** Grepping pantry's
source for `account` returns one hit, the word "accountable" in a doc comment. Four
true negatives, and they are the reason the check is not "flag anything near a
tenant".

**parlor and site are reported as NOT ESTABLISHED, not as 0.** Both serve all of
`/v1` from one Next.js catch-all `route.ts`, whose account handling I did not read to
the end in the budget. Their row in the table is a gap in the measurement and is
labelled as one. I would rather publish four rows and two blanks than four rows and
two invented zeros.

### The measured miss, stated rather than hidden

**guard scores 1 of 5.** The inline `/v1/me` route is caught on its registration
line. The four `bff.*` routes are not: `app.post("/auth/login", bff.requireSameOrigin,
bff.login)` means resolving `bff.login`, which means resolving the **type of the
receiver** — a second resolution this checker does not make.

That is 4 false negatives on one repository. It is in `notEnforced` with its numbers.
**I chose not to ship it.** The fix is to widen resolution until more things resolve,
and every version of that widening I can construct either fires on symbols whose
connection to an account I cannot justify, or stops being a resolution and becomes a
guess. A guess that produces a FAIL is worse than a recorded gap: it is the D18
pattern wearing a different hat. The gap is actionable — a reader can see the row is
unchecked — and a false FAIL is not.

---

## 4. FAIL or WARN — the argument

**FAIL.** Three reasons, in the order they would have changed my mind.

**A WARN is not a severity, it is a habit.** The packet's own case is the argument:
`nothing-scoped` has printed on courier for weeks and nothing happened, because a
warning that has been printed unchanged N times is read as background. Landing this
as a warning would have put a fifth un-acted-on line on the same build. The brief
named that outcome and asked for it not to happen; a FAIL is how it does not happen.

**The signal is decidable, not heuristic.** The difference matters and I want to be
precise about where it comes from. Not from the vocabulary — `RESOLVED` has patterns
in it and a pattern is a guess. It comes from the **chain**: the evidence is a line
in a file the checker reached by following the framework's own wiring, from a
registration, through a `scope`, through a `pipe_through`, through a `pipeline`, to a
`plug`, to a file resolved through an index of definitions. Every step is a lookup.
No step asks "does this look account-scoped". That is the whole argument, and it is
why I did not ship the receiver-type resolution when I could have made guard 5 of 5:
adding it would have made the chain end in an inference rather than a lookup.

**The negative controls are cases, not intentions.** Case 20 (a service that holds
nothing) stays green. Cases 22 and 23 assert the **absence** of a finding about a
liveness probe and about a route that *holds a customer's mailbox* and resolves no
account. Case 24 deletes the check and shows the liar passing again. A gate that
cries wolf gets switched off, and this one is not measured crying.

**The cost of being wrong is asymmetric and that argues the other way** — a service
with a false FAIL turns its CI red and loses an afternoon. I accept that cost, because
the alternative is a warning nobody reads, and the thing this packet measured is a
service that holds other people's data saying so nowhere, in a build that has been
green for weeks.

One thing that would change the argument: if the `guard` gap grows — if more than
about one repository in five has a receiver-shaped handler — the FAIL should become a
WARN. A gate that fires on a fifth of the fleet's routes without being able to justify
each one is a gate that gets disabled. At 1 of 5 on one repository it is not that yet,
and the number to watch is written down rather than left to be discovered.

---

## 5. Proven, separately from passes

Tally reported apart from passes, per the standing rule. **7 new cases; 27 total.**

| # | proof | expected | got |
|---|---|---|---|
| 20 | **control** — a service that holds no customer data | clean | `clean all_public` |
| 21 | **the liar** — 10 rows, all false, 5 lies | red, all 5 named with file:line | `red, and all 5 lies named with a file and a line` |
| 22 | **negative control** — `/healthz` is not accused | red, silent on it | `red, named account-scope.declaration-contradicts-code, silent on healthz (GET /healthz)` |
| 23 | **negative control** — the unsubscribe is not accused | red, silent on it | `red, named …, silent on unsubscribe-show` |
| 24 | **the breaking** — check deleted, liar passes | clean again | `clean, with the check gone liar_check_disabled` |
| 25 | an unresolvable `false` row | warn, green | `warn, and green handler_absent -> account-scope.contradiction-unreadable` |

Case 21 asserts **five specific routes** *and* that `lib/liar_web/plugs/principal.ex:19`
appears, so a finding that stopped printing its evidence fails rather than passing
quietly.

**Passes: 27 - 6 = 21 pre-existing cases, all still green.** `bin/prime` 295/295, exit 0.

---

## 6. Three of my own decisions were overturned by core's suite

Recorded because the packet's standing rule is that a check must be able to say no,
and twice it said no to me:

1. **I gave the check an environment off-switch** so case 24 could disable it.
   `test_the_account_scope_checker_reads_no_environment_and_runs_no_process` forbids
   it, correctly: an answer that depends on who is asking is not an answer about the
   repository. There is now **no way to switch the check off from outside**, and case
   24 proves the breaking on a throwaway **copy** with the call deleted — stronger,
   because it removes the code rather than configuring it away.
2. **My remediation began "spell the controller module"**, and the suite requires a
   remediation to name a command or an edit from a closed verb list. Rewritten.
3. **`test_the_checker_says_which_of_the_three_states...` asserted `warnings: 0`** on
   the conforming fixture and my change made it 1. The finding was working and **the
   fixture was wrong**: it never defined `handleHealthz`, so the checker honestly
   reported it could not verify that row. Added
   `harness/tests/fixtures/account-scope/conforming/internal/httpapi/handlers.go`.

---

## 7. What is left

- **`guard` at 1 of 5.** Receiver-type resolution is the named next step, and it is
  deliberately not shipped. In `notEnforced` with numbers.
- **parlor and site unmeasured.** Ground truth not established in this budget. The
  claim in §3 is deliberately two blanks, not four rows of invented zeros.
- **The other eight fleet repositories** (`identity`, `muse`, `darkroom`, `billing`,
  `cafaye-ts`, `cafaye-rb`, `cafaye-py`, `cafe`) — their routers were not located, so
  they are absent from §3 rather than counted as zero. `identity` in particular is
  the fleet's substrate and its Go router is the one this checker was written
  against; **measuring it is the single highest-value thing left in this packet.**
- **`account_scope.yml` exists in none of the fifteen fleet repositories**, so the
  contradiction check currently reports `declaration-missing` on all of them and has
  never been run against a real declaration in the fleet. The fixture is the proof
  that it works; nothing yet proves it is *adopted*. Adoption is a follow-up packet.

## 8. One correction to my own first commit message

`ce5527c` says `webhook_endpoints_controller` has "5 refs to account_id, 3 of them
code". The measured number is **4 in code** (`endpoint.account_id` at line 199 is
code, not prose). The conclusion does not change and the table in §2 is the measured
one; the commit message was written before the mask existed and was counting by eye.
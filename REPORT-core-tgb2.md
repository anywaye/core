# REPORT — core-tgb2: every service's gate has seen a liar fixture fail

Packet: **TG-B2**. Worktree `/Users/kaka/Code/any/moon/wt/core-tgb2`, branch
`tenancy/core-tgb2`. Dispatched on core; no service repository was edited.

## What was asked, and what this packet is

TG-B1 made core's tenancy checker unable to answer OK to a false declaration
(the account-scope contradiction check, with the liar at
`harness/tests/fixtures/account-scope/liar/` as its model). TG-B2 makes that
property *useful*: a repo that has never seen a failing declaration can believe
any of them, including its own. The deliverables named by the brief:

1. a liar fixture in core, reachable by every service;
2. a gate step a service can invoke in one line, asserting fail-on-liar **and**
   pass-on-truth;
3. at least two services running it, with real output;
4. `./bin/prime` green.

## Done, and verified

**1. The liar fixture** — `harness/tests/fixtures/tenancy/liar/` (commit
`1a2deff`). A service tree whose `tenancy.yml` is schema-valid, complete, and
FALSE: every named file is present, every named line is real, every denial arm
points at the assertion it names, the `rls` block says the true thing
(`databaseEnforced: false`, and this tree writes no DDL at all). The lie is in
the enumeration: `migrations/0001_assets.sql` dropped `and account_id = $2`
from its first three statements, and the declaration still says all seven entry
points are enforced there.

```
$ python3 harness/tenancy_check.py harness/tests/fixtures/tenancy/liar
FAIL tenancy.scope-lost: asset-fetch declares query-filter at migrations/0001_assets.sql:33 and that line does not carry the tenancy key — 'select * from assets where id = $1'. …
FAIL tenancy.scope-lost: asset-list  … migrations/0001_assets.sql:36 … 'select id, checksum, status from assets order by created_at' …
FAIL tenancy.scope-lost: asset-pending … migrations/0001_assets.sql:39 … "select id from assets where status = 'pending'" …
FAIL tenancy.entry-absent: asset-pending declares select on assets at migrations/0001_assets.sql: the tenancy key is no longer in that statement. …
FAIL /…/harness/tests/fixtures/tenancy/liar: 4 failure(s), 0 warning(s)
EXIT: 1
```

**2. The gate step** — `harness/bin/tenancy-proof` (commit `21c98c4`). One line
in a service's gate:

```
bash "$CAFAYE_CORE/harness/bin/tenancy-proof" .
```

Arm one: the liar must exit 1 **naming the finding it is built to trip**
(`--expect <finding-id>` for a service whose own liar trips a different one).
Arm two: the service's own declaration must exit 0 — the arm a checker that
reds on everything cannot satisfy, which is why a step that merely fails proves
nothing. Exit 2, never 0 and never 1, when the proof could not happen (no
python ≥ 3.9, a liar path that is not a directory, a repository that is not
there). Verified four ways in the suite (see below).

**3. Two services, real output** — `courier` and `identity`, run read-only
against their own worktrees (nothing in either repository was edited; the
per-service wiring is the manager's packet):

```
$ bash harness/bin/tenancy-proof /Users/kaka/Code/any/moon/wt/courier-tga2
tenancy-proof: the liar failed as required — 4 failure(s), tenancy.scope-lost named
tenancy-proof: the truth passed — /Users/kaka/Code/any/moon/wt/courier-tga2 has 0 failure(s), and 3 warning(s), which never move the exit code
tenancy-proof: both directions held. The tenancy check on this repository can fail, and did.
EXIT: 0

$ bash harness/bin/tenancy-proof /Users/kaka/Code/any/moon/wt/identity-tga1
tenancy-proof: the liar failed as required — 4 failure(s), tenancy.scope-lost named
tenancy-proof: the truth passed — /Users/kaka/Code/any/moon/wt/identity-tga1 has 0 failure(s), and 1 warning(s), which never move the exit code
tenancy-proof: both directions held. The tenancy check on this repository can fail, and did.
EXIT: 0
```

Both warnings are the documented Elixir/Python-language ones (`scope-key-unused`,
`enumeration-partial`), which never move the exit code. The narrow verification
the brief names — the checker against a liar planted in a **scratch copy** of a
service declaration — was also run: a scratch copy of courier (`.git`, `deps`,
`_build`, `node_modules` excluded) passes both arms unbroken, and dropping the
predicate from the line `webhook-endpoints-list` declares as its enforcement
(`lib/courier/webhook_endpoints.ex:114`) turns it red:

```
FAIL tenancy.scope-lost: webhook-endpoints-list declares query-filter at lib/courier/webhook_endpoints.ex:114 and that line does not carry the tenancy key — '|> where([endpoint], endpoint.inserted_at <= ^cutoff)'. …
```

**4. `./bin/prime` green** — see "Verification" below.

## The proofs that the proofs can fail

- `harness/tests/tenancy_self_test.sh` (commit `f38947b`) gains **case 46**
  (the liar red, `tenancy.scope-lost`, all three lying rows named) plus the
  assertion the whole packet turns on: the four **honest** rows — two scoped
  writes, the variant fetch, the bind in `src/assets.rb` — must be **absent**
  from the report, because a checker that reds on everything satisfies every
  red assertion ever written. **Green case 7** is the other direction: the same
  fixture with the predicate restored and nothing else changed must be green,
  so the red is proved to be about the dropped predicate and not about the
  fixture's shape.
- Teeth, proved rather than assumed: with `LIAR_FIXTURE` pointed at the
  conforming fixture, the four new assertions fail and the script exits 1
  (45 breakages, 4 failures, 0 skipped). The run as committed is 46 breakages,
  4 warnings, 9 green cases, 1 control, 0 skipped.
- `tests/test_specs.py` (commit `bf45122`) gains two tests:
  `test_the_liar_fixture_is_red_and_the_conforming_fixture_is_green` (in-process,
  both directions, exactly two finding ids, the three lies named, the four
  honest rows absent, the conforming fixture green and warning-free) and
  `test_the_tenancy_proof_step_asserts_both_directions` (the real script, four
  ways: both arms holding; the pass arm failing on a genuinely red tree; a liar
  path that is not there → exit 2; a red naming the wrong finding → exit 1). The
  second test also enforces the wrapper's own `|| true` prohibition against the
  wrapper, comments stripped first — and it caught a real one on its first run:
  `grep -c … || true` in the count lines, which is exactly the rescue the fleet
  forbids. The counts are now measured with `awk`, which exits 0 whatever it
  counted.
- `gate.yml`'s floor is raised `305 → 307` in the same commit, measured on this
  tree. The ratchet's other direction held without help: adding two tests
  before raising the floor is what fails, and the suite is 307/307 with the
  floor at 307.

## Half-done, and why

- **The per-service wiring is not in this repository.** The brief's "Done
  means 3" wants at least two services running the step in *their* gate, while
  its Rules section dispatches me on core and forbids editing service
  repositories. Both were honoured by running the step against the two real
  service trees read-only (output above) and handing the manager the wiring
  paragraph below. Nothing in a service changed.
- The wrapper defaults `--expect` to `tenancy.scope-lost`, which is what
  **core's** liar trips. A service that commits its own liar in its own
  language will usually trip a different finding (`tenancy.rls-owner-bypass`
  for a database-half lie, `tenancy.honest-zero` for a false zero) and will
  pass `--expect`. That flag is the whole reason it exists; it is documented in
  the script header and in `docs/tenancy.md` step 6.

## Verification, with real output

```
$ ./bin/prime                        # background, exit code captured separately
…
307/307 passed
==> the account-scope red proof passed: 67 cases and 0 failed, every
  red one naming the finding it planted.
```

Full log: `/tmp/gate-core-tgb2-final.log`. The suite reports `307/307 passed`;
every red proof in `bin/prime` (gate, reserved, db-isolation, account-scope)
passed; the tenancy checker's own red proof — which CI runs and `bin/prime`
deliberately does not — was run explicitly and passes at 46 breakages.

## The currently-failing command

None. `./bin/prime` is green, `bash harness/tests/tenancy_self_test.sh` is
green, and both arms of `harness/bin/tenancy-proof` behave as specified on
core's fixtures, on courier, on identity, and on a scratch copy of courier.

## Decisions, and why

- **The liar lies about `enforced`, not about `rls`.** A liar that lied about
  both halves would tell a reader nothing about which arm of the checker
  caught it. The database half says the true thing so the red is a statement
  about the enumeration and nothing else.
- **The lie is a dropped predicate in truthful-looking code, not an omission
  and not an invalid value.** Omissions are caught by `undeclared-entry` and
  invalid values by `tenancy.schema`; neither is the capability at risk. What
  is at risk is judging a *complete, valid* declaration, so that is the only
  thing the fixture makes false.
- **The honest rows are asserted as absences, not inferred from the count.**
  A checker that reds on everything satisfies every red assertion; the four
  true rows are what distinguish "the check caught the lie" from "the checker
  is broken", and asserting the count would prove neither.
- **The gate step is a new wrapper, not a flag on `tenancy_check.py`.** That
  file is TG-B1's surface and is off-limits to this packet; a wrapper is also
  the fleet's existing shape for a service-facing command (`harness/bin/*`).
- **The wrapper counts with `awk`, and forbids `|| true` in itself.** The
  first version used `grep -c … || true` and the new test refused it. A
  wrapper that turns a refusal into a pass is worse than no wrapper.

## What I deliberately did NOT do, and why

- **Did not edit any service repository.** Dispatched on core; the brief's
  Rules say so and its "Done means 3" wants the service-side run, so the two
  real service runs were read-only against their worktrees and the wiring is
  handed to the manager below.
- **Did not touch `harness/tenancy_check.py`, `schemas/*.json`, or
  `harness/tenancy_findings.json`.** TG-B1's surface. The liar is caught by
  findings TG-B1 already merged (`scope-lost`, `entry-absent`) — no new
  finding, no new severity, no loosened assertion.
- **Did not add the liar to `harness/rules.json`.** That file inventories the
  *contract* rules in `cafaye_contract.py`, asserted equal to `module.RULE_IDS`
  in both directions. A wrapper that runs an existing checker adds no rule; an
  entry there would break that assertion and mean something false.
- **Did not add a new CI step for the wrapper.** `tenancy_self_test.sh` (which
  CI runs as a step of its own) carries the liar's red proof, and
  `tests/test_specs.py` — which `bin/prime` runs — carries the wrapper's four
  verdicts. A third place asserting the same thing is drift waiting to happen.
- **Did not make the wrapper require a warning-free truth arm.** A Go or Elixir
  service is green *with* warnings by design; requiring zero warnings would
  red the two services that most need this check.

## The wiring, one paragraph per service (for the manager's per-service packet)

Add one line to the service's gate, after its own `tenancy-check .` step:

```
bash "$CAFAYE_CORE/harness/bin/tenancy-proof" . [path/to/own-liar] [--expect <finding-id>]
```

With no arguments beyond `.` it uses core's liar, which trips
`tenancy.scope-lost` — enough for any service that wants the both-directions
proof today. A service that wants its own lie in its own language copies
`harness/tests/fixtures/tenancy/liar/` into its test tree, rewrites the
migration and `enforced` lines so the lie is in the service's own idiom, and
passes the path plus the finding its lie trips. Exit 0 means both directions
held; exit 1 means the liar passed (the checker cannot fail — fix the checker
or the fixture, never the assertion) or the service's own declaration is red;
exit 2 means the step could not run, which is never a pass.

Suggested dispatch order: **courier** and **identity** first — both have real
`tenancy.yml` files with real `negative.cases`, and courier's is the fleet's
most exercised (33 entry points). Then **muse**, **gateway** (both honest
zeros today, so their lie is a false zero and their `--expect` is
`tenancy.honest-zero`), then **darkroom** if and when it adopts a declaration.

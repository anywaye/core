# REPORT — core-15: declare the tenant-isolation contract

Branch `worker/core-15-tenancy`. **Nothing pushed.** No adopter was fixed; see
§5, which is the point of that.

---

## 1. What this packet is

Cross-tenant access is **declared, never inferred**, and it is answered as
**nonexistence, never as a refusal**. Four new files make that a thing a tool
can read:

| file | what it is |
| --- | --- |
| `schemas/tenant-isolation.schema.json` | the format: `tenancy.yml`, one per service at its root |
| `harness/tenancy_check.py` + `harness/bin/tenancy-check` | the checker, stdlib only, `{ok, warn, fail}` |
| `harness/tenancy_findings.json` | 16 findings with the exact command that fixes each, + 5 `notEnforced` |
| `harness/tests/tenancy_self_test.sh` | the red proof: 16 breakages, 3 warnings, 2 green cases, 1 control |

Plus `docs/tenancy.md`, six examples (2 valid, 4 invalid with README tables),
**D33** in `DECISIONS.md`, a `CHANGELOG.md` section, two steps in core's CI, and
**thirteen tests in `tests/test_specs.py`** (the floor in `gate.yml` raised to
**186** in the same commit, as the ratchet demands).

**Not touched:** `harness/gate_check.py`, `bin/prime`, `harness/rules.json`.
`harness/rules.json` deliberately does **not** carry a tenancy finding — that
inventory is asserted equal to `cafaye_contract.RULE_IDS`, so one added there
would break a real assertion and mean something false. The tenancy inventory is
its own file, exactly as `gate_findings.json` is.

## 2. The two decisions in the schema

**`negative.asserts` is `const: absent`.** Not an enum with a discouraged
second value — a const. `403`/`ErrNotAuthorized` confirms the id exists and is
an enumeration oracle; `nil`/`[]`/`NotFound` tell an attacker nothing.
`tenancy.denial-refuses` is a **failure**, so weakening the assertion gets a red
that names the oracle rather than a style comment. This is the half of D33 that
somebody would otherwise relitigate in every service.

**`operation` has no `insert`.** An insert creates a row in the account the
caller is already acting as; it cannot read another account's row. Including it
would mean a legal declaration whose `enforced.line` does not carry the key —
an exception inside the contract, which is how the next exception gets in.

## 3. The checker's four checks, and where each one bites

| check | finding | the defect it catches |
| --- | --- | --- |
| named files and lines exist | `tenancy.location-missing`, `tenancy.line-missing` | a declaration pointing at nothing — worse than none, because it reads as a boundary somebody looked at |
| the declared line still scopes | `tenancy.scope-lost`, `tenancy.bind-missing` | a dropped predicate; and a `bind-parameter` whose `$2` nothing passes, which a predicate check cannot see |
| the enumeration is **closed both ways** | `tenancy.entry-absent`, `tenancy.undeclared-entry` | the scoping was dropped, or a new scoped query was added and nobody said |
| the negative is present and absent-shaped | `tenancy.denial-missing`, `tenancy.denial-refuses` | `nil` weakened to `403`, in the test or in the declaration |

Plus `tenancy.honest-zero` and `tenancy.enumeration-empty`, which is the
`accountScoped` boolean checked in both directions: a service with no boundary
says so explicitly, and gets caught leaving.

### The split that keeps a refactor cheap and a dropped predicate expensive

`enforced.line` is **exact** (so a stale line is a red that says which of two
things happened), but **closure does not use it** — an entry point's identity is
its `(file, operation, subject)`. So a query that moves three lines down is one
`scope-lost` to fix, while a query that loses `and account_id = $2` is one
`entry-absent` that cannot be argued with. Both are red; neither opens ten.

### The honesty requirement

A `warn` **never** moves the exit code, and all four warnings are the same
claim: *this machine cannot answer that question*. `tenancy.enumeration-partial`
names every account-scoped site the scanner saw and could not attribute, and
says the declaration is **not** proven closed. It does not say "no account-scoped
entry points found", ever — that is the `darkroom route_defs=0` defect, and a
report that says it is worse than no report because it reads like an answer.

## 4. The self-test, and the three things it found

`bash harness/tests/tenancy_self_test.sh` — **16 breakages red, each naming its
finding *and* its entry point; 3 warnings green; 2 green cases; 1 control; 0
skipped.** The control is asserted **warning-free**, not merely green: that is
what proves the scanner classifies everything the fixture holds, so the warning
cases are about a fixture's shape rather than an over-eager scanner.

**The suite cannot catch a deleted check. Measured, not asserted.** While this
packet was being written, `check_denials` was disabled in the working tree and
`bin/prime` reported **186/186 passed**; the self-test went red on exactly the
two cases that exercise it. Reproduced on a throwaway copy so the live tree was
never touched:

| | with `check_denials` disabled |
| --- | --- |
| `bin/prime` (`tests/test_specs.py`, 186 tests) | **186/186 passed** |
| `harness/tests/tenancy_self_test.sh` | **FAIL** — 2 of its 16 cases |

The thirteen tenancy tests that landed in `tests/test_specs.py` are schema-level,
inventory-level and textual: they prove the format is well-formed, the two
halves of every inventory agree, and the self-test *names* each finding. None of
them drives a behavioural check through `check()`. So the whole behavioural half
of the checker is currently held up by the one script that is **not** in the
gate. That is not an argument against those thirteen tests — they are the right
tests for what they assert, and each one covers a failure mode a self-test cannot
reach. It is an argument that **D15 is load-bearing for this packet**, and it is
the strongest evidence in this report.

All seven the brief names, plus five more:

| # | breakage | finding |
| --- | --- | --- |
| 1 | WHERE dropped on a read | `scope-lost` · asset-fetch |
| 2 | bind parameter dropped | `bind-missing` · asset-checksum-bind |
| 3 | unscoped list | `scope-lost` · asset-list |
| 4 | unscoped update | `entry-absent` · asset-settle |
| 5 | unscoped delete | `entry-absent` · asset-delete |
| 6 | IDOR on fetch-by-id | `entry-absent` · asset-variant-fetch |
| 7 | negative weakened to forbidden (test only) | `denial-missing` · asset-fetch |
| 8 | declared file does not exist | `location-missing` |
| 9 | declared line past the end of the file | `line-missing` |
| 10 | negative weakened to forbidden (declaration updated) | `denial-refuses` |
| 11 | an account-scoped query nobody declared | `undeclared-entry` · archive |
| 12 | declares no scoping and has one | `honest-zero` |
| 13 | no `tenancy.yml` at all | `declaration-missing` |
| 14 | a declaration the reader cannot parse | `declaration-unreadable` |
| 15 | says it scopes by account and declares no way it does | `enumeration-empty` |
| 16 | an undeclared key in the declaration | `schema` |

Breakages 1–6 resolve to two findings, which is why `expect_red` takes a fourth
argument: **"went red" would not distinguish a read that lost its predicate from
a delete that lost its predicate.** The finding id says which *check* fired; the
needle says which *entry point* it fired about, and that is the claim actually
being made.

**Two real defects the red proof caught before this report was written** — both
recorded here rather than quietly fixed, because a self-test that has never
caught anything is a self-test that has never been run:

1. **`tenancy.honest-zero` did not fire on unclassifiable code.** It was written
   against `sites` — the *classified* SQL — so a service declaring
   `accountScoped: false` and holding a Go function carrying `account_id` came
   back green with a warning. That is exactly the failure mode the whole packet
   exists to prevent, wearing a different hat. It now fires on `sites +
   unclassified`, because "the declared key appears in the declared sources"
   needs no parser — so the honest zero is checkable *even for a language the
   scanner cannot read*, which is the more valuable half of the fix.
2. **Breakage 13 (a source path that is not there) was red for the wrong
   reason.** Renaming `migrations` to `db/migrations` also stopped the scan
   finding four declared sites, so the verdict was four `entry-absent`
   failures — which proves nothing about `tenancy.scan-narrowed`. Changed to
   *adding* a missing path, so the scan reads exactly what it read before and
   the only finding is the one under test. The comment in the script says so,
   because that mistake is the obvious one.

## 5. The fleet against this contract today

Run: `harness/bin/tenancy-check <repo>` in each of the thirteen repositories.

| service | verdict | prod files carrying `account_id` | SQL sites the scanner classifies | account-key lines it could **not** classify | cross-tenant negative tests | of all cases |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| identity | `declaration-missing` | 19 | 21 | 86 | **17** | 810 |
| courier | `declaration-missing` | 9 | 0 | 124 | **17** | 629 |
| billing | `declaration-missing` | 4 | 0 | 38 | 0 | 600 |
| cafaye-rb | `declaration-missing` | 2 | 0 | 24 | 3 | 228 |
| cafaye-ts | `declaration-missing` | 7 | 0 | 18 | 2 | 188 |
| guard | `declaration-missing` | 4 | 0 | 10 | 0 | 478 |
| darkroom | `declaration-missing` | 7 | **10** | 72 | 0 | 19 |
| pantry | `declaration-missing` | 0 | 0 | 0 | 0 | 96 |
| muse | `declaration-missing` | 3 | 0 | 31 | 1 | 429 |
| cafaye-py | `declaration-missing` | 3 | 0 | 122 | 2 | 343 |
| parlor | `declaration-missing` | 2 | 0 | 16 | 0 | 449 |
| cafe | `declaration-missing` | 0 | 0 | 0 | 2 | 436 |
| kit | `declaration-missing` | 0 | 0 | 0 | 0 | 73 |

**13 of 13 fail, all with the same finding.** Not one repository publishes a
boundary. The method is in
`harness/tenancy_check.py` (`declared_files`, `scan_file`, `key_spelling`) and
the cross-tenant column counts test cases whose body mentions a second-account
fixture *and* asserts; it is looser than the brief's 7/19 (it counts a case that
mentions `elsewhere` and asserts anything), so read it as an upper bound. The
conclusion does not depend on the exact count: two services have coverage, and
eleven do not.

**Nothing was fixed. That is deliberate and it is the packet's most important
sentence.** A contract with no failing adopter is a contract nobody has tested
against reality, and a packet that quietly wrote darkroom's first tenancy tests
would have delivered a format validated against its own author.

Three readings the table supports that the brief's numbers did not:

- **`pantry`, `cafe` and `kit` are honest zeros, not gaps.** Zero production
  files carry `account_id`, and pantry's matches are all in the vendored
  registry of *other* services' manifests. Their `tenancy.yml` should say
  `accountScoped: false` — and the checker would then hold that true, because
  the honest zero is enforced, not merely permitted.
- **`guard` is the service the route-count grep was flattering.** 96 "routes" by
  decorator pattern, 4 production files carrying `account_id`, and the scoping
  genuinely happens in `middleware/jwt.ts` and `middleware/apiKey.ts` — i.e.
  `mechanism: middleware`, which is exactly the shape closure cannot check
  against. It is the case that proves `operation: call` earns its place.
- **`darkroom` is where this format pays for itself.** 10 classifiable scoped
  sites, 19 test cases in the whole repository, and zero of them asserting a
  cross-tenant refusal. Its statements are correct today and unprotected, which
  is the state this packet exists to move and did not move.

## 6. What the checker does NOT prove

Five entries in `tenancy_findings.json`'s `notEnforced`. The two that matter:

- **The negative assertion is READ, not run.** `denial-missing` proves it is
  written — a second account fixture, an absent-shaped result, at a line a reader
  can open. Running darkroom's suite needs its container and its Postgres;
  courier's needs a mix database. A checker that started containers would be red
  on a laptop and green on CI depending on what was running, which is
  `gate.requirement-unproven` in a new place. Running the test is the gate's
  job, in the service. This is a real gap: a test written and never run reads
  exactly like a test that passes.
- **`enforced.line` is not the only place the scoping can be.** A CTE, a
  subquery, a view, or a repository method three layers down is scoped, and this
  checker can be pointed at the wrong one line of it. Hence `operation: call`,
  and hence a service with two enforcement points declares two entry points.

## 7. Judgement calls, with the reasoning

No questions were asked; these are the calls I made and why.

- **`operation: call` exists and closes nothing.** A repository method is a
  `select` to a human deciding where a leak can happen and something else to a
  text scanner. Rather than pick one, the format says "I cannot check this" and
  the checker names every one it could not classify. Adding a second
  pseudo-operation (`repository`) would have been inference with better manners.
- **The scanner reads SQL only, and says so.** Closing the enumeration for eight
  of the eleven non-zero services needs a parser per framework. Failing on that
  would get the checker disabled in one release, leaving the fleet with *no*
  boundary check instead of an incomplete one. A `warn` that names its blind
  spot keeps CI green and keeps the report honest.
- **`enforced.line` is exact, and the drift is intended.** A window would have to
  choose a tolerance, and "the predicate is on the next line" and "the predicate
  is gone" land inside any window worth having.
- **The scanner skips `create table` blocks and `insert` lines.** A schema
  naming `account_id uuid not null` is not an enumeration of itself, and a test
  factory's `Assets.insert(account_id: …)` is the most common key-bearing line in
  this fleet. Both rules are commented at the point they are made.
- **A run that could not happen exits 2.** Inherited from `gate_check` and from
  core's own rule. There is no `--prove` phase here: this checker runs no
  process, which is also why its floor is Python **3.9** rather than 3.11.
- **`service` is not checked against the directory name**, for the reason
  `gate.yml`'s `name` is not: a worktree's directory is not the repository's
  name, and a check that fires on `darkroom-worker-darkroom-10` is a check
  everybody learns to ignore.
- **`check()` does not return early on a schema failure**, which is a deliberate
  departure from `gate_check`. `negative.asserts: forbidden` is both a schema
  violation and an enumeration oracle, and a reader told only "your file is
  invalid" goes looking for a typo.

## 8. Owed, and by whom — the hand-offs

`tests/test_specs.py` is core-14's file, so this packet did not edit it. While it
was being written, **thirteen tenancy tests landed there anyway** and `gate.yml`'s
floor was raised to 186 with them. They cover, one test each: the schema's four
headers and every level's closure; both valid examples; all four invalid examples
against their documented `(keyword, path)` pairs; checker-and-schema agreement on
every example; the findings inventory in both directions with severity, claim and
remediation byte-identical; a remediation on every finding plus a non-empty
`notEnforced`; that every finding is named by the self-test and that CI invokes
it; stdlib-only by AST walk **and** by `-I -S`; that the checker reads no
environment and runs no process; that a repository with no `tenancy.yml` fails
rather than passes; that a warning never moves the exit code; that the conforming
fixture is green **and** warning-free; and that this doc states the contract and
both alternatives. Suite: **186/186**.

Four more breakages were added to the self-test at the same time — the missing
declaration, an unreadable one, the empty enumeration, and an undeclared key —
which is why it reports 16 rather than the 12 this packet wrote.

**What is still owed, and it is the thing that matters most here:**

1. **`bin/prime` — core-14's file, and the one decision still open.** It runs
   **none** of the three self-test scripts (gate, harness, tenancy). **My view:
   all three belong in the gate**, and this is one decision owed in one place
   rather than three — the shape D15 is already taking. Not for this packet to
   decide unilaterally, so it is recorded here rather than acted on. CI runs all
   three as steps of their own in the meantime, which is why removing those
   steps would be a real loss and not a cosmetic one.
2. **Adoption is the next packet, not this one**, and should be paid for in the
   order the table in §5 implies: `darkroom` first (10 scoped sites, 19 test
   cases in the whole repository, zero coverage — the highest value per hour),
   then `guard` and `cafaye-ts` (7 production files each), then `identity` and
   `courier` (they already have the assertions; they need them *pointed at*,
   which is a day's work each), then `pantry`, `cafe` and `kit`, which are honest
   zeros and cost one line each.

### The false green this packet found in itself, and closed

This section previously listed as still owed the fact that **no test drove the
checker's behaviour through `check()`**. It is now closed, and the reason it was
owed is worth keeping, because the measurement is the argument:

```
check_denials deleted from harness/tenancy_check.py   ->  bin/prime: 186/186 passed
```

A green gate over a checker that no longer checks — the false green core exists
to end — and it was in the gate rather than only in a report. The self-test
caught the deletion, but the self-test is a **CI step, not `bin/prime`**, so the
command a developer runs and the badge core publishes were both green over it.
Thirteen failure-severity findings had nothing between them and the badge.

`test_every_behavioural_check_the_checker_has_is_proved_load_bearing` closes it
by running the same control-then-breakages idiom **in-process, where the gate can
see it**: one case per failure-severity finding, each labelled with the check
function it exercises, plus a finding-free control asserted first, plus the
assertion that no failure-severity finding is left unexercised. It is the
fourteenth test, and the floor in `gate.yml` is 187.

Measured — one function deleted at a time, `bin/prime` run each time, checker
restored to its baseline SHA after each:

| deleted | the gate |
| --- | --- |
| `check_locations` | red |
| `check_enforcement` | red |
| `check_closure` | red |
| `check_denials` | red |
| `check_honest_zero` | red |
| `check_scan` | red |
| the `validate()` call | red |

The expected exit code is read from each finding's own declared severity rather
than hardcoded, so a severity change in `tenancy_findings.json` is a change to
this test instead of a silent disagreement with it.

The lesson generalises past this packet, and it is the one worth carrying: **a
suite that asserts a checker's inventory, its documentation and its imports,
while never driving the checker, has proved the checker exists.**

## 9. Verification

```
bin/prime                                  187/187 passed, 0 failed, 0 skipped
bin/prime --pytest                         187 passed  (the two entry points agree)
bash harness/tests/tenancy_self_test.sh    16 breakages RED naming their finding
                                           3 warning cases stayed GREEN
                                           2 green cases named what it cannot see
                                           1 control, green and warning-free
                                           0 SKIPPED
harness/bin/tenancy-check <each service>   13/13 exit 1, all tenancy.declaration-missing
```

Every number above was **re-measured on the final tree**, not carried over from
an earlier draft. The fleet table in §5 was reproduced independently: 13 of 13
repositories exit 1 with `tenancy.declaration-missing`, and the scanner pointed
at each whole tree still classifies **21 sites in identity and 10 in darkroom
and 0 in the other eleven** — the same two numbers, which is the point, because a
table of thirteen rows that only holds for the machine that wrote it is a claim
rather than a measurement.

- The schema meta-validates as draft 2020-12, and all five of its levels close.
- The checker's re-implementation and the real `jsonschema` reach the **same
  verdict on all nine documents** core ships (2 valid examples, 4 invalid
  examples, 3 fixtures) — and that is now asserted by the suite, not merely
  observed once by hand.
- **The self-test's control was observed red, twice, on the final script.** With
  `check()` short-circuited to an empty `Report`, 16 of 16 breakages report
  "expected exit 1, got 0" and the script exits 1. With `check_denials`
  disabled alone, exactly the two denial breakages fail and the other fourteen
  still go red — which is the attribution claim, measured. The checker was
  restored to its baseline SHA (`9a75f7eb…`) after each experiment.
- **The gate was measured against a gutted checker** — one function deleted at a
  time, seven experiments, `bin/prime` red every time. The table is in §8.
- `gate.yml`'s floor is **187**, raised with the fourteen tests in
  `tests/test_specs.py` — thirteen for the contract, the fourteenth for the
  behavioural proof.
- The CI step that reads the self-test's log was run against a real log **and
  against a doctored one** (it fails with the named error rather than a bare
  `exit 1`; a missing `|| true` on that pipeline was a real bug, found by
  running it).
- **Nothing outside this worktree was touched, and nothing was pushed.**

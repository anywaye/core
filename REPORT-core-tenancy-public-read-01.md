# REPORT — core-w50-publicread: the tenancy format's declared public-read tier

**Branch:** `worker/core-w50-publicread` (base `4c957ba`, three commits, tree clean)
**Gate:** `mise exec -- ./bin/prime` — **exit 0** (output below)
**Status:** complete. The previous attempt's three commits were reviewed, kept
(they are correct), and independently re-verified in this run; nothing was
discarded.

---

## 1. The design, and why

### The key: `rls.publicRead` — a list of claims, each with three facts

```yaml
rls:
  publicRead:
    - table: publishers               # the table that is public-readable
      policy: publishers_public_read  # the policy that grants the read
      role: public_reader             # the role the read is granted to
```

The tier lives alongside `rls.tables`, `rls.identity` and `rls.enforced` — the
brief's "alongside them" — and each entry names **which policy** grants the
public read and **which role** it grants it to. A bare `publicRead: true` is
the thing this packet exists to avoid, and the schema makes it unrepresentable:
`table`, `policy` and `role` are all `required`, `additionalProperties:
false`, and `role` carries `not: {const: public}`.

**Why a list of named claims and not a boolean or a table set:** the checker
has to compare the claim against the DDL rather than trust it. The comparison
is mechanical and runs in both directions:

- **DDL → declaration (the arms):** in `_check_policy`, the always-true arm
  and the identity-absent arm of `tenancy.rls-permissive` stand down for
  exactly one policy — the `(table, policy)` pair the declaration names — and
  only while the DDL backs the claim (`written.command == "select"` and the
  named role is among `written.roles`). The names-no-role/PUBLIC arm is *not*
  exempted, and cannot be reached by a declared public read: the claim check
  requires a bound role, so `written.roles` is non-empty for every policy the
  tier covers.
- **Declaration → DDL (the earning):** `_check_public_read_claims` fires
  `tenancy.rls-public-read-absent` (FAILURE) when the named table is not
  created, the named policy is not written, the policy is written `for`
  another command, or the policy is bound `to` roles that do not include the
  named one. A public read cannot be asserted into existence.

**Why `role` refuses `public`:** a policy with no `to` clause applies to
`PUBLIC` — every role, including the migration role and every role the service
adds in a year. A public read granted to every role is the absence of a
boundary wearing a public-read declaration's clothes, and it would make the
tier evidence-free (the checker could no longer compare the claim against the
DDL). Refused in the schema, for the same reason `rls.tables[].policies[].roles`
refuses `public`.

**SELECT-only:** the exemption requires `written.command == "select"`, and the
claim check says the command out loud when the named policy is written `for
insert`/`update`/`delete`/`all`. An always-true or role-less write clause is
still `tenancy.rls-permissive` under a public-read declaration — verified
below (breakage 45).

**The named policy must also be in `rls.tables[].policies`** — a policy in the
migrations and not in `rls.tables` is `tenancy.rls-undeclared`. `publicRead` is
the evidence that the policy is a deliberate public read, not a replacement
for declaring it. The fixture declares it in both places, and the doc says so.

### What the claim check deliberately does not ask

Whether the clause is *really* public. The check asks whether the DDL writes
the named policy as a `SELECT` bound to the named role — the only facts a
migration file can settle. A declaration can name a policy that is
`for select to public_reader using (account_id = (select app.current_account()))`
— account-scoped, safe, and not a public read — and the claim check passes;
the permissive arms it exempts would not have fired anyway. Judging intent is
a judgement this stdlib text checker does not have, and a check that guesses
at intent is a check that gets disabled within one release. This is recorded
in `harness/tenancy_findings.json`'s `notEnforced` list and in
`docs/tenancy.md`, rather than left to be discovered.

---

## 2. The three directions — red-then-green evidence

The harness (`harness/tests/tenancy_self_test.sh`) has no single-case flag;
it runs all forty-five breakages in one pass. Each direction was therefore
proved **twice**: once in the committed self-test (which runs as a whole and
passes: 45 breakages / 8 green cases / 4 warning cases / 1 control / 0
skipped), and once by running the checker directly against fixture copies —
including against the **unmodified** checker extracted from the base commit
(`git show 4c957ba:harness/tenancy_check.py`), which is the red half of the
red-then-green proof.

### Direction 1 — a declared public read is accepted (and was red before)

Fixture `harness/tests/fixtures/tenancy/public-read/`: a conforming service
plus one deliberately public-readable table (pantry's `publishers` shape) —
`create policy publishers_public_read on publishers for select to public_reader
using (true);`, declared in `rls.publicRead` with the policy and role the DDL
writes, and also declared in `rls.tables[].policies`.

| run | result |
| --- | --- |
| modified checker vs committed fixture | **exit 0** — `OK … 0 failure(s), 0 warning(s)` |
| **unmodified** checker vs committed fixture | **exit 1** — `tenancy.schema: … rls: additionalProperties 'publicRead'` **and** `tenancy.rls-permissive: the using clause of 'publishers_public_read' … never mentions app.current_account()` |

The red half is two findings: the old schema refuses the unknown key, and the
old permissive arm fires on the always-true clause. The tier is what makes the
difference.

### Direction 2 — an UNDECLARED public read still fails, exactly as today

Same fixture, the `publicRead` block removed from `tenancy.yml`, everything
else untouched:

```
FAIL tenancy.rls-permissive: the using clause of 'publishers_public_read'
  (migrations/0002_rls.sql:112) never mentions app.current_account(), so the
  policy is not scoped by the identity this declaration names and is scoped by
  nothing this checker can see
exit 1
```

The finding is the same one the unmodified checker reports — the tier narrows
the check, it does not soften it. This is self-test breakage 42.

### Direction 3 — the declaration must be earned

Same fixture, the `create policy publishers_public_read …` statement removed
from `migrations/0002_rls.sql`, declaration untouched:

```
FAIL tenancy.rls-policy-absent: rls.tables names policy 'publishers_public_read'
  on publishers and the migrations do not create it — they write no policy at all
FAIL tenancy.rls-public-read-absent: rls.publicRead names policy
  'publishers_public_read' on 'publishers' as the public read and the migrations
  never write it — they create no policy at all
exit 1
```

Both findings are true: the declared policy is gone from the DDL
(`rls-policy-absent`), and the public read is asserted about a database that
does not have it (`rls-public-read-absent`). A service that believes it has a
public read it does not is a service whose boundary is a sentence. This is
self-test breakage 43.

### The two halves of the claim a boolean could not check (breakages 44–45)

- **Wrong role** — declaration names `role: anon`, DDL binds `to public_reader`:
  `tenancy.rls-public-read-absent` — "the migrations bind it `to
  ['public_reader']`, which does not include that role". Exit 1.
- **Wrong command** — DDL writes the policy `for insert to public_reader`:
  `tenancy.rls-public-read-absent` ("the migrations write it `for insert`, and
  a public read is a SELECT") **and** `tenancy.rls-permissive` still fires.
  Exit 1. The tier is not a public-write tier.

### The narrowing-not-softening constraint

The exemption key is the exact `(table, policy)` pair, and it requires the DDL
to back the claim (`command == "select"`, named role bound). No previously-red
fixture can go green without a declaration: the only behavioural changes are
(a) the schema/checker now *accept* the `publicRead` key (previously an
`additionalProperties` rejection), (b) the two arms stand down only for a
backed claim, (c) the new claim check, which only adds findings. The schema
still rejects unknown `rls` keys (`additionalProperties: false` preserved —
verified: `$.rls` rejects a bogus key).

---

## 3. The ledger change

`docs/tenancy.md`'s ledger row for `rls_policy_always_true` asserted "Cafaye
has no public read tier — every table in `rls.tables` is account-scoped by
construction". That sentence is now false and is rewritten to record the new
decision: the exclusion carries over **as a claim with evidence rather than a
blanket exemption** — the always-true arm stands down for the one policy the
declaration names as a table's public read (table, policy and role all checked
against the DDL) and fires for every other always-true clause, because a
public read nobody declared is the defect this checker exists for. The
severity for an undeclared public policy stays a FAILURE, and the ledger says
so. The stale comment above `ALWAYS_TRUE_CLAUSES` in
`harness/tenancy_check.py` (which said "Cafaye has no public read tier") is
rewritten to match.

The doc gains a full section — *The public-read tier: a claim with evidence* —
specifying the rule, the earning, SELECT-only, why `role` refuses `public`,
the both-places declaration rule, and what the claim check does not ask.

---

## 4. What was ruled out

- **A bare `publicRead: true` / a set of table names.** The brief names it as
  the thing to avoid; the schema's `required: [table, policy, role]` makes it
  unrepresentable.
- **Exempting the names-no-role/PUBLIC arm.** A public read granted to `PUBLIC`
  is the absence of a boundary; the schema refuses `role: public` and the arm
  keeps firing. The tier narrows the permissive arms; it does not touch that
  one.
- **Exempting write commands.** The exemption requires `for select`; the claim
  check names the command when the DDL writes another one (breakage 45).
- **Judging whether a clause is "really" public.** A stdlib text checker
  cannot; the checkable half (policy exists, is a SELECT, binds the named
  role) is what is enforced, and the gap is published in the `notEnforced`
  list rather than left to be discovered.
- **Fixing the always-true arm's normalisation.** See §5 — pre-existing, and
  fixing it would change fleet-wide behaviour this packet does not own.
- **Touching any service's `tenancy.yml` or the `account_scope.yml` handling.**
  Not touched; the diff is core's harness, schema, docs, examples and tests
  only.

---

## 5. Observations for the manager (not acted on)

1. **The brief says the gate "runs the tenancy self-test as one of its red
   proofs". It does not.** `bin/prime`'s header documents
   `tenancy_self_test.sh` as CI-only (it asserts facts about a checker, and
   those checkers have never taken this gate down; the four red proofs
   `bin/prime` runs are gate, reserved, db-isolation, account-scope). The
   self-test is wired into CI at `.github/workflows/ci.yml:273`, and the
   gate *does* exercise the new finding in-process via
   `test_every_behavioural_check_the_checker_has_is_proved_load_bearing`
   (extended with the `rls-public-read-absent` case). I changed nothing here;
   the repo's own documented split stands.
2. **The always-true arm is effectively dead code, and predates this packet.**
   `_POLICY_CLAUSE` (`\b(using|with\s+check)\s*\(`) consumes the opening
   paren, so `normalised_clause("using (true);")` returns `"true)"` — never in
   `ALWAYS_TRUE_CLAUSES`. The arm can only fire on a clause line the scanner
   never records. Verified identical at the base commit. Breakage 22 passes
   on the identity-absent arm, not the always-true arm. Fixing
   `normalised_clause` (regex without the `\(`) would make the arm fire
   fleet-wide — a real behaviour change outside this packet's scope, and
   exactly the kind of unrequested change a worker should not make. Flagging
   it for a decision, not fixing it.
3. **The gate floor needed no change.** `gate.yml` declares `minimum: 299`
   and the suite reports 299/299; the packet added cases to an existing test
   function, not new test functions, so the ratchet holds.

---

## 6. The gate

Command (exact): `mise exec -- ./bin/prime`, run in the background per the
quarterly contract, exit code captured:

```
GATE EXIT CODE: 0
```

Key lines from the run:

```
==> the gate is declared, and the declaration is true about this tree
299/299 passed
==> the red proof passed: 18 breakages went red naming their finding, 7 warning cases stayed green, 12 real-workflow spellings accepted, 4 extractor assertions, 3 colour-greens, 2 colour reds, the control green, and 0 skipped.
==> the reserved red proof passed: 6 breakages went red naming their finding, 2 controls green, including core's own tree.
==> db_isolation red proof: 3 breakages went red naming their finding,
  5 clean controls stayed clean, and the control passed first: 8 passed, 0 failed
==> the account-scope red proof passed: 67 cases and 0 failed, every
  red one naming the finding it planted.
```

Tenancy-specific suite lines from the same run:

```
pass test_a_new_tenancy_finding_needs_a_case_here_before_it_can_be_shipped
pass test_every_tenancy_finding_carries_the_exact_command_that_fixes_it
pass test_every_tenancy_finding_is_proved_able_to_go_red
pass test_every_tenancy_finding_the_checker_can_emit_is_declared
pass test_every_behavioural_check_the_checker_has_is_proved_load_bearing
pass test_the_invalid_tenancy_examples_are_rejected_for_the_reason_they_document
pass test_the_tenancy_checker_and_the_schema_agree_on_every_example
```

The tenancy self-test, run in full (`bash harness/tests/tenancy_self_test.sh`):

```
PASS tenancy_self_test: green case 6: a declared public read, with the policy and the role the DDL writes — exit 0
PASS tenancy_self_test: breakage 42: a public read nobody declared — caught by `tenancy.rls-permissive` about publishers_public_read
PASS tenancy_self_test: breakage 43: a public read the migrations do not write — caught by `tenancy.rls-public-read-absent` about publishers_public_read
PASS tenancy_self_test: breakage 44: a public read declared for a role the DDL does not grant it to — caught by `tenancy.rls-public-read-absent` about public_reader
PASS tenancy_self_test: breakage 45: a public read claimed for a policy the DDL writes for insert — caught by `tenancy.rls-public-read-absent` about publishers_public_read

  breakages that went RED and named their finding : 45
  warning cases that stayed GREEN                 : 4
  green cases, each of which named what it cannot see : 8
  controls (a true declaration, unbroken)          : 1
  SKIPPED                                           : 0
```

## 7. Examples

- `examples/valid/tenancy.public-read.yml` — validates against
  `schemas/tenant-isolation.schema.json` (verified independently with
  jsonschema).
- `examples/invalid/tenancy.public-read-role-public.yml` — rejected at
  `$.rls.publicRead[0].role` by the `not: {const: public}` keyword (verified
  independently), with a row in `examples/invalid/README.md`.

## 8. Commits

- `bc4049e` — the substrate: checker, schema, and a true fixture.
- `2310d1a` — the examples, the findings inventory, and the suite's count.
- `0c94632` — the three-direction proof, in the harness and the doc.

No merge, no push — the manager gates the merged result.

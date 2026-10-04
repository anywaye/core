# AGENTS.md — working in `cafaye/core`

Read this before changing anything here. `core` is the substrate every other
cafaye service compiles against, so a careless edit is a fleet-wide break.

## The one rule

**A rule that is not in `schemas/` is not a cafaye rule.**

Every convention is a JSON Schema constraint plus a test plus a doc paragraph.
If you find yourself writing a convention into a README and calling it done, it
is not done — it is documentation of a wish. The test is the enforcement.

## Order of work: tests first

Per PLAN.md §3. Concretely, in this repository:

1. Add or change the test in `tests/test_specs.py`.
2. Run `bin/prime` and **show it failing**. A test that has never failed has
   never been proven to test anything.
3. Make it green by changing the schema, an example, or a doc — not by
   loosening the assertion.
4. If the failure is the wrong failure, the test is wrong. Fix the test first.

Loosening an assertion, adding a skip, or bumping a retry to get to green is
how a spec silently stops being enforced. There are no sleeps in this suite
because there is nothing to wait for.

## Editing a schema

- Draft 2020-12. `$schema`, `$id`, `title` and `description` on every file.
- **Always** meta-validate before claiming done — `test_schemas_declare_draft_2020_12`
  calls `check_schema`, so a malformed schema fails loudly.
- Keep `additionalProperties: false` at every level. It is the reason an
  undeclared key is an error instead of a silent no-op.
- Do not duplicate a pattern between the two schemas. `eventType` and
  `serviceName` exist in both; `test_envelope_type_and_source_patterns_match_the_manifest`
  asserts the copies are byte-identical. Change one, change both.
- Every new constraint needs, in the same commit: a positive example under
  `examples/valid/`, a negative case under `examples/invalid/` if it is
  constraining, a row in `examples/invalid/README.md`, and a test.

## Editing docs

- A doc and its schema are the same contract written twice. When they disagree,
  the test fails — that is the point. Fix the wrong one; do not relax the test.
- `docs/contract-harness.md` and `harness/rules.json` are one more such pair, and
  a third list: the rule ids in `harness/cafaye_contract.py` are the same
  twenty-five again. Three statements, three tests. A rule the harness reaches and
  the inventory does not describe is a rule nobody was told about.
- The event catalog in `docs/event-naming.md` is checked against the schema
  pattern. Adding an event means a catalog row **and** a publisher entry in
  `exposes.events`, in the same commit.
- Every event type is `<service>.<entity>.<action>` — three segments, always
  prefixed, no exceptions. The pattern is duplicated byte-identically in
  `schemas/event-envelope.schema.json` and `schemas/cafaye.manifest.schema.json`
  and a test asserts the copies match, so change one, change both.
- `data` is **not** opaque any more: per-event payload schemas live in core at
  `schemas/events/<service>/<entity>/<action>.schema.json`, with a valid and a
  negative example each. Adding one means the schema, both examples, a row in
  the payload table in `docs/event-naming.md`, and a test.
- `docs/openapi-conventions.md` is capped at roughly two pages. It is a
  checklist, not a handbook. If it grows, something belongs in a service's own
  repo.
- `docs/observability.md` states a **contract**, not a collector. The seven
  schemas under `schemas/telemetry/` say what may go in a span, a metric and a
  log record, and what `*_OTEL_ENDPOINT` means when it is set and when it is
  not. Do **not** add the OpenTelemetry Collector, the LGTM stack, an exporter,
  or a per-language SDK to this repository — that is `kit` and the services, and
  an exporter here is core becoming a runtime, which is the one thing this
  repository is not. The same rule as the outbox: core owns the contract, each
  service ships its own implementation in its own language.
- **An SLO rule is a schema rule, and `docs/slo.md` is the other half.** A
  service's declaration is a Sloth `prometheus/v1` file at `slos/<service>.yaml`
  and nothing else may appear in it. Five of these rules are easy to undo by
  accident and each has a constraint behind it: the **tier alone decides whether
  a page is generated** (never let a service choose `page_alert.disable`); the
  burn-rate **windows are pinned once, in core**, and a per-service
  `--slo-period-windows-path` is the override `slo-windows.schema.json` exists to
  forbid; the **period is 28 days**, not 30; the **objective is never 100**; and
  the **SLI is good events over total events**, composed from
  `slo-metrics.schema.json`'s catalogue rather than written by hand — the metric
  names there are the Postgres-normalized spellings of the OpenTelemetry ones,
  which is the error six languages make.
- **The two denylists stay two denylists.** Unbounded dimensions (`tenant`,
  `user_id`, `account_id`, `request_id`) and infrastructure signals (`cpu`,
  `memory`, `pod`, `restart`) share one scan in the harness and are two rules in
  `harness/rules.json`, because the reasons differ and the reason is what a
  reader has at the moment they are about to add one. Merging them keeps the
  enforcement and loses the second reason.
- **The database half of a tenancy declaration is a required `rls` block, and
  `forced` is a `const: true`.** `tenancy.yml` says what the service's *code*
  scopes and, separately, what *Postgres* does. **Postgres does not apply
  row-level security to a table's OWNER unless the table is set `FORCE ROW LEVEL
  SECURITY`**, a service owns the tables it created in its own schema, and
  Supabase's database advisor collects `relforcerowsecurity` for its table list
  and never judges it. So a policy that is never evaluated raises nothing, nothing
  logs, and the role that matters reads every row. That is `tenancy.rls-owner-bypass`,
  a FAILURE, and it is proved by **deleting one line** from the fixture and
  asserting the finding fires about that table *and about nothing else* — the
  "nothing else" is what proves the two `reloptions` bits are separable. The other
  nine `tenancy.rls-*` findings came from Supabase's twenty-eight lints, and
  `docs/tenancy.md` carries a **machine-checked ledger** of every one of them:
  adopted, adapted or left out, with a reason, and a test that fails when a row is
  dropped or says "left out" with an empty reason. A rule that was examined and
  excluded on purpose is a decision; the same rule excluded silently is the defect
  this section exists to stop.
- **A warning in `harness/tenancy_check.py` means "this machine cannot answer
  that question", and nothing else.** All four of them say so, and they never
  move the exit code because failing on them would get the checker disabled —
  which leaves the fleet with no boundary check instead of an incomplete one.
  That argument does **not** transfer to a fact decidable from the migration text,
  which is why every `tenancy.rls-*` finding is a `fail` but one
  (`tenancy.rls-unreadable`, RLS DDL in a file the checker cannot parse — a Rails
  migration is a `.rb` file). A severity nobody chose is not a severity.
- **`negative.cases` is three arms and the third is a `const: present`.** "Does
  an unauthenticated request fail" is satisfied by a table with no policy at all,
  which is the bug. `own-account` asserts the account's own credential **sees its
  rows**, and two denial arms are satisfied perfectly by a service that returns
  nothing to anybody. This replaced a single `expects`/`file`/`line` triple in a
  published format with zero adopters in the fleet; `version` stayed at `1` and
  **that is a recorded defect, not a decision** — see
  [D41](DECISIONS.md#d41-how-is-the-force-rule-declared-and-what-may-a-warning-mean-in-the-tenancy-checker).
- **Three arms is not the same as three SHAPES, and the third shape is the one
  that raises nothing.** Postgres denies a cross-tenant access three ways and only
  two of them raise `42501`: a missing grant, and a `with check` violation. The
  third — a `using` clause filtering the row out — raises **nothing** and matches
  zero rows, so a suite asserting only "it threw" passes on it while isolation is
  completely broken, because a table with no policy at all raises exactly the
  privilege error it waits for. So `tenancy.denial-shape` refuses a
  `select`/`update`/`delete` arm naming a RAISING token, and refuses the
  `own-account` arm naming a LIVENESS one (`lives_ok` passes when the write
  matched zero rows), and `tenancy.denial-unpaired` refuses a denied write
  answered with an ABSENCE token — an empty result is a lie about a row that
  exists, and a zero row count is also what a write that found nothing to do
  returns. All three are decided from the declaration plus the line it names, so
  they are findings rather than a paragraph. Their vocabularies are closed lists
  of spellings this checker **knows** are wrong, not of correct ones: an
  unrecognised token passes, which is the first entry in
  `harness/tenancy_findings.json`'s `notEnforced` list and is stated with its
  measured consequence in `docs/tenancy.md` rather than left to be discovered.
- **"No SLA" is a test, not a sentiment.**
  `test_no_sla_token_appears_in_a_schema_or_an_example` walks every `const`,
  `enum` and `default` under `schemas/` and every example, and the `not` on any
  SLO prose refuses the acronym. An SLO describes intended behaviour on adequate
  hardware, measured by the operator, with the exclusions published — that
  sentence is the artifact.
- The **span-name pattern** is duplicated byte-identically in
  `span-naming.schema.json` and `traces.schema.json` on purpose, so a service
  can load either file alone. Change one, change both;
  `test_the_span_name_pattern_is_shared_with_the_traces_schema` says so.
- A **telemetry rule** is a schema plus a test plus a doc paragraph, exactly
  like any other. An attribute that is not on a signal's allowlist is not
  emitted; adding one is a spec change with an example, a README row and a test
  in the same commit.
- Prefer writing the recommendation down over asking. A reversible default with
  a stated trade-off beats a stalled packet.

## Open decisions

Specs are manager-owned: **you draft, the manager decides.**

- Never silently resolve a genuine design question.
- Never resolve it in a way that is hard to reverse either. When you draft a
  default, leave the cheapest possible path to the alternative — the pattern
  you chose, the one line that changes it.
- Mark it `> DECISION NEEDED (Dn):` in the affected doc: what the choice is,
  the alternatives, your recommendation, and the cost of flipping.
- Number sequentially per repository and reference decisions by number
  (`see D3`). One number per decision, ever — a reused number is a broken
  cross-reference, and a reference to a number that does not exist is worse
  than no reference at all.
- Report the open list in your worker report. Undecided and unreported is the
  only real failure.

## Git

- Primary branch is `master` everywhere (PLAN.md §1).
- Work on `worker/<packet-id>`. **Never push. Never create a remote.** The
  manager merges to `master` after reading the diff and running the suite.
- Remotes for anything cafaye owns are SSH (`git@github.com:cafaye/…`), never
  HTTPS — and the manifest schema rejects an HTTPS remote, so a bad habit
  fails the suite.

## Repo hygiene

- No runtime libraries, no services, no dependencies beyond `tests/requirements.txt`.
  `core` is schemas + docs + validators. If a change needs a runtime, it belongs
  in `caf`, not here.
- `docs/event-outbox.md` states a convention, not a library. Do not add a shared
  outbox implementation, migration or package to this repository — each service
  implements it in its own language, and core owns the contract only.
- **`harness/` is executable code, and the line it lives inside is "no runtime",
  not "no code".** It is the contract-test harness PLAN.md §4 Phase 0 named, and
  it reads `schemas/` — a harness in its own repository would have to vendor
  core's schemas, which is the four-way drift it exists to end. So while it is
  here:
  - **Standard library only.** Not `tests/requirements.txt`, not one more
    package. `test_the_harness_imports_nothing_outside_the_standard_library` and
    `test_the_harness_runs_with_site_packages_disabled` are the two proofs, and a
    harness that needs a package is a check a Go service's CI cannot run.
  - **No network, ever.** It reads a checkout of core and never fetches one. A
    contract check that needs the network is one nobody runs on an air-gapped
    runner, and one that gets a different answer on a different day.
  - **A run that could not happen exits `2`, never `0`.** The same rule as a
    skipped test: gateway's live-Redis tier, muse's `MUSE_CORE_SCHEMAS`, identity's
    `TEST_DATABASE_URL` and darkroom's `--ignored` are one defect in four
    repositories, and a contract check that cannot find the contract is *worse*
    than no contract check because it converts an unknown into a green badge.
  - **A rule the harness enforces is declared in `harness/rules.json`** with
    where it lives, and core's suite checks the declaration. If you add a rule,
    add the inventory entry in the same commit; if you move a rule into a schema,
    change the inventory entry and nothing else.
  - **`harness/tests/self_test.sh` must go red when the harness goes red.** A new
    rule with no breakage is a rule nobody has tested. It is not part of
    `bin/prime` — a self-test inside every gate invocation would be a second gate
    that can disagree with the first — and CI runs it as a step of its own.
    **The asymmetry with `harness/tests/gate_self_test.sh` is deliberate and
    dated:** core-14 put the *gate checker's* red proof inside `bin/prime` (it is
    a different checker, one `bin/prime` runs on the line above, so a developer
    who has just gated knows whether that answer was earned) and left the
    *contract* harness's here, in CI only. `docs/gate.md` argues it; do not
    "fix" the asymmetry by moving either one.
- **`harness/gate_check.py` is a checker of DECLARATIONS, and it is not
  `caf gate`.** It compares a repository's `gate.yml` to that repository, and
  with `--prove` it runs the declared gate and requires the declared proofs to
  appear. It has no tier logic, it has no `caf` commands, and it is **not** part
  of `harness/rules.json` — that file inventories the *contract* rules in
  `cafaye_contract.py` and its ids are asserted equal to `module.RULE_IDS`, so a
  gate finding in there would break that assertion and mean something false. Its
  inventory is `harness/gate_findings.json`, asserted equal to
  `gate_check.FINDINGS` in both directions, and it carries its own `notEnforced`
  list because a checker with no list of what it does not prove reads as covering
  everything. Adding a gate finding means: the finding, the inventory entry, and
  a breakage in `harness/tests/gate_self_test.sh` that names it — all three, or
  the finding is untested and the inventory is a wish.
  - **It is the one file in `harness/` that runs a process**, by design: a gate
    check that cannot tell a gate that ran from a command that exited 0 cannot do
    its job. The reason it is safe is the one it states — no network, no ambient
    environment of its own, and the gate's output written to a log rather than
    into the report.
  - **It needs Python 3.11 and the contract harness needs 3.9.** `tomllib` is
    stdlib from 3.11 and the checker reads `mise.toml`; the wrapper refuses an
    older interpreter with exit 2 and a sentence explaining why, rather than
    degrading to a green. See [D31](DECISIONS.md#d31-the-gate-checker-is-stdlib-only-and-needs-python-311-where-the-contract-harness-needs-39).
- **`gate.yml` is core's own declaration, and the gate checks it.** `bin/prime`
  runs the **static** half of `gate_check.py` and must never run `--prove`: the
  checker runs the gate, and the gate runs the checker, so a gate that verifies
  itself by running itself terminates. The proving half is a CI step, and
  `test_core_ci_runs_the_gate_checkers_proving_phase` fails if that step is
  deleted.
  - **`bin/prime` DOES run `harness/tests/gate_self_test.sh`, and must keep
    doing so.** The reasoning above is about `--prove` and does not apply here:
    the red proof runs the checker against *fixture* repositories whose gate is
    three lines long, never `bin/prime`, so there is no recursion — and it asks
    a question `--prove` structurally cannot (`--prove` cannot catch a checker
    that can only say yes, because a checker that can only say yes looks exactly
    like a passing gate). Its failure must move `bin/prime`'s exit code, a
    precondition it cannot meet must be a non-zero naming the precondition, and
    `bin/prime` must **read the report** rather than trust the status.
    `test_bin_prime_runs_the_gate_checkers_red_proof`,
    `test_bin_prime_runs_the_red_proof_on_the_pinned_interpreter`,
    `test_bin_prime_is_red_when_the_red_proof_is` and
    `test_bin_prime_is_not_a_pass_when_the_red_proof_says_nothing_or_skips` all
    fail if the step is deleted — proved by deleting it, not assumed.
  - **`gate.proof[].minimum` is a ratchet, and it is the only place in core that
    writes down how many tests there are.** A test added to `tests/test_specs.py`
    fails `test_the_gate_floor_is_not_below_the_suite_core_claims_to_have` until
    the floor in `gate.yml` is raised in the same commit. Do not "fix" that test
    by lowering the assertion; raise the number, which is the point of it.
- Do not touch anything outside this worktree.
- **Do not write SLOs for the seven services.** core ships the instrument and
  its checks; the declarations need the metrics `slo-metrics.schema.json` names
  to exist first, and `test_no_slo_example_declares_a_real_fleet_service` keeps
  the examples from quietly becoming one. **Which tier each service gets is
  [D29](DECISIONS.md#d29-which-tier-does-each-of-the-seven-services-get)**, and it
  is not a worker's call.
- Bound long or networked commands with `timeout N`.

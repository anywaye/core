The substrate every cafaye service compiles against: the service manifest

**Current direction (2026-10-19):** Ship is the product. The cafaye stack is internal infrastructure; we are not selling or supporting it as a standalone product as of this date. We continue to develop and improve it, treating the founder as the primary customer and keeping "build once, run everywhere" true, with the expectation that it may be offered again later.
format, the event envelope, the HTTP contract conventions, and the SLO
specification. Schemas, docs and validators — nothing else. There is no runtime
here, on purpose; a service's runtime is that service's problem.

```
schemas/   the machine-readable contract (JSON Schema, draft 2020-12)
  events/  one payload schema per event type, at schemas/events/<type>.schema.json
  telemetry/ the observability spec: span naming, the per-signal attribute
           allowlists, the redaction boundary, the *_OTEL_ENDPOINT contract,
           and the SLO and error-budget specification
docs/      the human contract: the same rules, with the reasoning
examples/  one valid and one invalid document per schema
tests/     the executable statement of every rule above
harness/   the contract-test harness: how a service checks itself against all
           of the above without writing the check
cafaye.yml core's own manifest, validated against core's own schema
fleet.yml  what the real service repositories publish, read at a named commit
```

## What core is for

`cafe init`, `cafe new`, `cafe dev`, `cafe gen` (SDKs), `pantry` (registry),
`gateway` (routing) and every service's contract tests all need the same handful
of facts about a service: what it is called, which language it is written in,
which spec version it was written against, what contracts it exposes and
consumes, and who owns it. Six tools answering six questions by reading six
bespoke config files is how cross-repo drift starts. One file, one schema, one
validator.

**A rule that is not in `schemas/` is not a cafaye rule.** If a convention is
real, it is a JSON Schema constraint with a test, and a document explaining why.
A convention that lives only in a README is a convention nobody enforces.

## The schemas

| File | Describes | Enforced by |
| --- | --- | --- |
| [`schemas/cafaye.manifest.schema.json`](schemas/cafaye.manifest.schema.json) | `cafaye.yml`, the per-service manifest | `test_every_example_manifest_is_covered_by_the_manifest_schema` + the cross-field rules below |
| [`schemas/event-envelope.schema.json`](schemas/event-envelope.schema.json) | the envelope every event travels in | `test_valid_event_envelope_example_validates` |
| [`schemas/events/<service>/<entity>/<action>.schema.json`](schemas/events/billing/payment/succeeded.schema.json) | the `data` payload of one event type | `test_payload_schema_examples_validate` + `test_valid_envelope_data_validates_against_its_payload_schema` |
| [`schemas/telemetry/span-naming.schema.json`](schemas/telemetry/span-naming.schema.json) | one span-name scheme, low-cardinality by construction | `test_span_names_are_low_cardinality_by_construction` + the invalid example |
| [`schemas/telemetry/{traces,metrics,logs}.schema.json`](schemas/telemetry/traces.schema.json) | the per-signal attribute allowlists, and the prohibition on unbounded identifiers as a measurement attribute | `test_every_signal_declares_an_allowlist` + `test_prohibited_identifiers_are_not_measurement_attributes` |
| [`schemas/telemetry/redaction.schema.json`](schemas/telemetry/redaction.schema.json) | the redaction boundary, and where it is enforced | `test_the_redaction_boundary_is_a_schema` + `test_the_redaction_policy_never_allowlists_a_content_attribute` |
| [`schemas/telemetry/otel-endpoint.schema.json`](schemas/telemetry/otel-endpoint.schema.json) | the `*_OTEL_ENDPOINT` contract and its no-op path | `test_unsetting_the_endpoint_declares_a_free_no_op` + the invalid example |
| [`schemas/telemetry/probes.schema.json`](schemas/telemetry/probes.schema.json) | `healthz` unconditional, `readyz` really checking | `test_a_readyz_that_checks_nothing_is_rejected` |
| [`schemas/telemetry/slo.schema.json`](schemas/telemetry/slo.schema.json) | one service's SLO declaration: the tier that alone decides whether a page is generated, a 28-day period, an objective that is never 100, and two PromQL strings | `test_the_tier_alone_decides_whether_a_page_is_generated` + `test_an_slo_at_one_hundred_percent_is_rejected` |
| [`schemas/telemetry/slo-windows.schema.json`](schemas/telemetry/slo-windows.schema.json) | the burn-rate window catalog — 14.4/6/3/1 at 5m+1h, 30m+6h, 2h+1d, 6h+3d — pinned once, in core | `test_the_window_catalog_is_the_workbooks_numbers` |
| [`schemas/telemetry/slo-metrics.schema.json`](schemas/telemetry/slo-metrics.schema.json) | the SLI catalogue, the label allowlist, and the two denylists | `test_the_two_denylists_are_two_prohibitions_and_the_schema_refuses_each` |
| [`schemas/gate.schema.json`](schemas/gate.schema.json) | [`gate.yml`](gate.yml) — what gates this repository, what it needs from the machine, and the proof its own output must carry before "passed" means anything | `test_core_declares_its_own_gate` + the 18 red proofs in `harness/tests/gate_self_test.sh` |
| [`schemas/fleet.schema.json`](schemas/fleet.schema.json) | [`fleet.yml`](fleet.yml) — what each service repository actually publishes, read at a named commit | `test_fleet_declaration_matches_its_schema` + the fleet section of `tests/test_specs.py` |

All are draft 2020-12, meta-validated by `check_schema` on every test run, and
all close themselves with `additionalProperties: false`. A key core does not
know about cannot be validated, so a producer cannot quietly invent one.

Some rules compare two properties of the same document, which JSON Schema
cannot express. Those live in `tests/test_specs.py` and in
[`docs/manifest-conventions.md`](docs/manifest-conventions.md) — for example, a
published event type must be prefixed with the publisher's own service name, a
service never consumes its own events, and every consumed type must exist in the
core catalog.

## Docs

| Document | Covers |
| --- | --- |
| [`docs/manifest-conventions.md`](docs/manifest-conventions.md) | manifest shape, namespace rules, semver constraints, the rules the schema cannot state |
| [`docs/event-naming.md`](docs/event-naming.md) | event grammar, action vocabulary, payload schemas, delivery guarantees, and the catalog of every event that exists |
| [`docs/event-outbox.md`](docs/event-outbox.md) | the transactional outbox: the table, the publisher loop, at-least-once, retention |
| [`docs/observability.md`](docs/observability.md) | span naming, the per-signal attribute allowlists, the prohibition on unbounded metric dimensions, the redaction boundary, the `*_OTEL_ENDPOINT` contract and its no-op path, and `healthz` vs `readyz` |
| [`docs/slo.md`](docs/slo.md) | what an SLO is here, what it may be computed from, the tier table, the burn-rate windows, the SLI catalogue, the two denylists, and what stands in place of an SLA |
| [`docs/openapi-conventions.md`](docs/openapi-conventions.md) | error envelope, pagination, versioning, idempotency, auth, deprecation |
| [`docs/gate.md`](docs/gate.md) | how a repository **declares** its gate: the format, what it needs from the machine, the proof that stops a false green, and the two alternatives that were measured and rejected |
| [`docs/contract-harness.md`](docs/contract-harness.md) | the contract-test harness: what it checks, how it pins core, where each rule lives, and what it does not check |
| [`docs/framework-tests.md`](docs/framework-tests.md) | behaviour tests vs framework tests: the seam, the two failure modes, what the checker can and cannot see, and the survey a person must judge |
| [`docs/core-version.md`](docs/core-version.md) | the `VERSION` file core publishes, the constraint grammar and its `0.x` caret rule, the three rules that resolve a service's `core:`, and the one supported way to fetch core — the pin, the vendored paths, the toolchain step, and what migrating costs |
| [`examples/invalid/README.md`](examples/invalid/README.md) | the expected failure of every negative example, field by field |
| [`DECISIONS.md`](DECISIONS.md) | every open question about the spec, numbered, with its recommendation |

`docs/event-outbox.md` is a convention, not a package. Every service implements
it in its own language against its own database; core states the table and the
loop and deliberately ships no shared code.

`docs/observability.md` is a contract, not a collector. The ten schemas under
`schemas/telemetry/` say what may go in a span, a metric and a log record, what
the `*_OTEL_ENDPOINT` variable means when it is set and when it is not, and what
an SLO may be computed from. **The OpenTelemetry Collector, the LGTM stack, the
Sloth binary and the per-language SDK setup are deliberately not here** — that is
`kit` and the services, and core shipping an exporter would be core becoming a
runtime, which is the one thing this repository is not.

## SLOs, in one paragraph

An SLO in cafaye is a **Sloth `prometheus/v1` file** at `slos/<service>.yaml` —
the one candidate spec whose validator walks a directory with no cluster, and
whose SLI is two PromQL strings all six languages can be checked against without
a parser. Four rules do most of the work: **the tier alone decides whether a
page is generated** (`critical | high | low | none`, required, derived into both
alert switches by the schema, because a page per SLO across seven services is
alert fatigue the self-hoster mutes within a week); **an SLO is scoped to a named
user-visible operation**, not to a service; **the burn-rate windows are pinned
once, in core**, at 14.4/6/3/1 over a 28-day period; and **the SLI is good events
over total events**, composed from a catalogue of metrics whose names are the
Postgres-normalized spellings of the OpenTelemetry ones. There is **no SLA** in
any of it: a self-hoster gets intended behaviour on adequate hardware, measured
by the operator, with the exclusions published. The full statement, the
arithmetic behind 14.4, the two denylists and the answer to "is an SLO
per-tenant?" are in [`docs/slo.md`](docs/slo.md).

## The contract-test harness

PLAN.md §4 Phase 0 named five deliverables for `core` v0. Four shipped. The
fifth — a **contract-test harness** — did not, and four services each wrote their
own instead: `muse` pins a core SHA in CI and compares bytes, `darkroom` tests
against its own vendored copy, `courier` holds its document to the router,
`pantry` has a byte-equality drift test. Four mechanisms, no shared harness.

```
harness/bin/cafaye-contract --core ../core .
harness/bin/cafaye-contract --core ../core --expect-digest <sha256> .
```

A service's CI, in three lines. Offline — core is read from a checkout, never
fetched. Standard library only, so a Go repository needs no Python package to run
it. It exits `0` for conforms, `1` for does-not-conform, and **`2` for "the run
could not happen"**, because a check that cannot find the contract and reports
success is worse than no check: it converts an unknown into a green badge.

It validates a service's *declared* contracts — its manifest against core's
schema, the cross-field rules JSON Schema cannot state, its event types against
core's catalog, its OpenAPI document against core's conventions, and its SLOs in
`slos/*.yaml` against the three SLO schemas. It does **not** validate live
responses against the event payload schemas, and
[`docs/contract-harness.md`](docs/contract-harness.md) says so in its own words
rather than leaving a reader to assume otherwise.

Twenty-five rules, and the honest answer to "where does each one live" is that
**two are JSON Schema constraints and twenty-three are in the harness's source** —
because [`docs/openapi-conventions.md`](docs/openapi-conventions.md) says itself
that those rules are review-enforced "until a future `cafe contract lint` lands".
[`harness/rules.json`](harness/rules.json) is where that stops being a summary:
every rule declares whether it is enforced by a schema, by a document, or by a
named function, and core's suite checks that each claim is true. Moving a rule
into a schema is a one-line inventory change, and the question is
[D23](DECISIONS.md#d23-do-the-openapi-and-cross-field-rules-become-a-schema).

The pin is a **sha256 over core's `schemas/`**, not a git ref: a ref names a
commit in a repository the harness is not allowed to fetch, and a digest names
bytes, which is what a service compiles against. It is printed on every run and
`--expect-digest` turns it into a red build. The same argument works on a laptop
and in CI because there is only one argument.

`bash harness/tests/self_test.sh` breaks the harness twenty-eight ways and
asserts twenty-eight reds, naming the rule each breakage must be caught by. CI
runs it — a comment claiming CI runs something is not CI running it.

## Spec versioning

`core` is pre-1.0 and versioned as a spec, not as a library — services
constrain it in their manifest (`core: ^0.2.0`) and CI pins it to a release
inside that range.

| Change | Bump |
| --- | --- |
| New event, new example, more documentation, a looser rule | **patch** |
| New manifest field, new optional `data` field, a new action in the vocabulary | **minor** |
| Tightening a pattern, making an optional field required, an enum value that invalidates an existing manifest, a removed event type, a changed envelope attribute | **major** (`0.x` majors are allowed while pre-1.0 — state the intent in the PR) |

`0.x` majors are legal but must be deliberate: a service pinned to `^0.1.0`
should never be broken by a `0.2.0` landing. A breaking change to a `0.1.x`
patch is a bug. The last major bump was v0.2.0, which changed the event type
format; the migration is in
[CHANGELOG.md](CHANGELOG.md#breaking).

**The absence of a major is a decision too, and gets the same treatment.** The
one deliberate non-major under this table is
[`identity.user.created`](schemas/events/identity/user/created.schema.json)'s
payload schema, rewritten to what identity actually emits: `user_id` loosened from
a `usr_`-prefixed pattern to `format: uuid`, and three optional properties
**deleted** rather than kept — properties no publisher has ever sent, since
identity's builder marshals a struct of two fields. It is a patch under the first
row of the table, not a major under the second, because the schema rejected 100%
of the publisher's real output and so had no working consumer to break.
[D35](DECISIONS.md#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
carries the reasoning and the escalation that asked for it.

## Governance — worker drafts, the manager decides

Specs are **manager-owned**. A worker never decides what the contract is.

1. A packet briefs a spec change.
2. The worker drafts it: schema, examples, docs, and tests written **first** and
   shown failing. Where a genuine choice exists, the worker picks a defensible
   default, implements it end to end, and marks the choice with a
   `> DECISION NEEDED (Dn):` callout in the doc it affects — stating the
   alternatives, the recommendation, and how expensive it is to flip.
3. The manager reads the diff, runs the suite, and either decides or sends it
   back. Open decisions are numbered `D1`, `D2`, … and referenced by number. A
   decision is folded into the spec as if it had always been the rule — no
   callout survives the merge, and `test_no_open_decision_callouts_remain_in_the_docs`
   fails the build if one does.
4. The manager merges to `master`. Workers commit to their own branch and never
   push.

Drafting a default rather than blocking on a question is deliberate: a worker
that stops to ask has stalled the phase, and a reversible default with a written
trade-off is cheaper than a stalled week. Nothing is merged undecided.

## Running the tests

```
bin/prime              # setup if needed, the suite, then the checker's red proof
bin/prime --pytest     # the same, with the suite collected by pytest
```

`bin/prime` creates `tests/.venv` on first run via `tests/setup.sh`, validates
every example — valid examples must validate, invalid ones must be rejected for
the exact reasons
[`examples/invalid/README.md`](examples/invalid/README.md) lists — and finishes
by running the gate checker's own red proof. There is nothing to run and nothing
to deploy: if `bin/prime` is green, core agrees with itself **and** its checker
has been shown able to fail.

Warm, that is about twenty seconds for the suite and about forty for the red
proof. A cold checkout adds the venv build and the PyPI install.

Python is pinned in `mise.toml`; `mise run prime` and `mise run setup` are thin
wrappers over the same two commands. `mise run test` also works and is an
**alias** for `mise run prime` (`depends`, not a second `run` string) — the
fleet's spelling of "run the gate" is `mise run prime`, so a task named anything
else is a task that gets discovered by getting it wrong.

The suite is **179 tests**, all of which run on every invocation, in a few
seconds, with no database, no network and no fixtures outside the tree — the only
network access is `tests/setup.sh` installing four packages from PyPI on first
run. Nothing in `tests/test_specs.py` reads an environment variable and nothing
in it skips. So a green result means 179 rules held.

**There is no second tier and no environment gate** — and there is now something
that looks like one, so the distinction is worth being exact about.

`harness/tests/gate_self_test.sh` is the gate checker's **red proof**: 18
deliberate breakages each asserting the checker goes red *and names the finding
it expects*, 7 warning cases asserting the exit code stays **0**, 3 green cases
against colour-bearing gates, 2 colour reds, 12 real `run:` spellings asserted
**accepted**, 4 extractor assertions, a leak case, and a control. Since core-14
`bin/prime` runs it, and its failure fails `bin/prime` — because until then a
developer could have replaced `harness/gate_check.py` with a function returning 0
and the local gate would still have printed `179/179 passed`. It is not a second
gate: it runs fixture repositories, never `bin/prime`, and it answers a
different question (`--prove` asks whether the gate ran; this asks whether the
checker could say no at all). The reasoning, and the cost — about forty seconds
per invocation — are in [`docs/gate.md`](docs/gate.md#the-third-thing-binprime-runs-and-why-it-is-not-the-recursion).

`harness/tests/self_test.sh` is still a *documented command* that CI runs and
`bin/prime` does not: 28 breakages of the **contract** harness, a different
checker on a different schedule. Neither script is gated on an environment
variable, and a self-test nobody runs is a claim rather than a proof — so
anything that ever *does* need a second tier has to arrive with the environment
that forces it, not with a default that leaves it dormant.

`tests/validate.sh` exists for one reason and one reason only: kit's reusable
workflow runs that exact path, and fails a build that asks for a gate and does
not ship one. It is `exec bin/prime "$@"` and nothing else. **Use `bin/prime`** —
`validate.sh` is the filename kit's contract looks for, not a second way in.

### The gate is declared, not guessed

[`gate.yml`](gate.yml) says what gates this repository, what it needs from the
machine that is not the repository, and what the gate's own output must contain
before the word "passed" means anything. `harness/gate_check.py` checks that
declaration against this tree, and **runs** the gate:

```
harness/bin/gate-check .               # static: the declaration against the tree
harness/bin/gate-check --prove .       # also run the gate, and require its proofs
bash harness/tests/gate_self_test.sh   # the checker's own red proof
```

A run that exits 0 **without emitting its declared proof is a failure**, not a
green. That is the difference between this and a file that says `mise run prime`,
and it is the one thing in this repository that would have caught the false green
this fleet has already shipped once. `bin/prime` runs the *static* half only,
because the proving half runs `bin/prime`; the proving half is a CI step of its
own. The format, the reasoning and the two rejected alternatives are in
[`docs/gate.md`](docs/gate.md).

## CI

```
ci/ci.yml                     calls kit's reusable workflow; owns the rest
```

Two jobs, and the job names are the claims they make:

| Job | Claim |
| --- | --- |
| `kit` | kit's workflow resolves from core, and the gate bootstraps from nothing on a clean runner |
| `gate` | the gate: `bin/prime` on the pinned interpreter (which itself ends with the gate checker's red proof), `bin/prime --pytest`, the drift guards, `gate-check --prove`, and the contract harness's own self-test |

**A red build in `core` is not "core is broken" — it is "a rule the fleet
depends on no longer holds".** core publishes no service and no API, but six
repositories' contract tests consume these schemas and vendor them, so a red
here is a spec regression until proven otherwise. Escalate it as one; do not
file it as a docs nit, and do not fix it by loosening a test.

The pin is read from `mise.toml` at run time and asserted against the
interpreter that arrives, rather than written into the workflow as a second
literal. That is not fussiness: `python-version-file: mise.toml` reads as if it
should work and **silently installs nothing**, because the action reads
`project.requires-python` or `tool.poetry.dependencies.python` and mise's
`[tools]` is neither.

Two things about this arrangement are open rather than settled, and both are in
[DECISIONS.md](DECISIONS.md) with their alternatives argued:
[**D20**](DECISIONS.md) is that kit's `none` job installs no interpreter, so the
`kit` job above runs the suite on the runner's own Python and only `gate` is
pinned; [**D21**](DECISIONS.md) is that a breaking schema change still has no
re-vendor fan-out, because core is the tree six services vendor and nothing
currently tells a service owner one is owed.

The self-test step is the one that reads its own log rather than only producing
it: it compares the number of breakages the script's footer *claims* went red
against the number of assertions actually logged, and requires the control to
have run exactly once. That check was proved able to fail — against a log with
three assertions removed, a log with no footer, and a log with the control
removed — because a guard that cannot find its target is not a guard, and a
footer nobody checks is the same claim core-06 got wrong about `uses:`.

## Status

`core` v0.3, unreleased. The five decisions carried in v0.1 are decided and
folded into `docs/`, and a doc that grows a `DECISION NEEDED` callout fails the
suite — the open questions live in
[DECISIONS.md](DECISIONS.md), numbered, and each one cites the files it affects.
Nine are open as of the observability work: **D13** (where the redaction boundary is
enforced), **D14** (`error.type` granularity), **D15** (the span-name form),
**D16** and **D17** (the endpoint variable, and a divergence between core,
PLAN.md §7b and muse), **D18**/**D19** (which classes are in the `error.type`
vocabulary, and whether the OTel `_OTHER` fallback belongs in a snake_case one),
and **D20**/**D21** (the unpinned interpreter in kit's `none` job, and the
missing re-vendor fan-out). Three more arrived with the harness: **D22** (core's
own suite does not assert `format: uri`, because no installed checker
implements it), **D23** (whether the sixteen rules the harness keeps in code
become a JSON Schema), **D24** (the event catalog
and the spec version are documents rather than data, which is why the harness
parses a markdown table and cannot resolve a `core:` constraint), and **D25**
(may a service document `/healthz` and `/readyz`? three do and one deliberately
does not, and core's OpenAPI conventions do not say which is right — found by
running the harness at the fleet). Four more arrived with the SLO spec:
**D26** (do the cafaye fields live inside the Sloth document or in a document kit
converts — Sloth's tolerance of unknown keys could not be checked offline),
**D27** (the burn factors are `0.02 x 720h`, which is a thirty-day budget, while
the period is twenty-eight days, so the fleet's alerts fire about 7% early),
**D28** (may core's gate take the `sloth` dependency — not taken, and PromQL
grammar is the named cost), and **D29** (which tier each of the seven services
gets — not built, because an SLO with no metric behind it is not yet a thing to
page on). See
[CHANGELOG.md](CHANGELOG.md#unreleased) for what changed and
[CHANGELOG.md](CHANGELOG.md#020--2026-09-30) for what v0.2 broke.

## License

MIT. See [LICENSE](LICENSE).

core holds the schemas and conventions every other cafaye repository adopts, so
the licence it ships under is the licence a consumer inherits by depending on
it. MIT keeps that a fact about this repository rather than about whoever
adopted it.

core is a Python harness plus data, not an installable distribution — there is
no `pyproject.toml` — so the `LICENSE` file is the entire grant. Nothing about
the package metadata carries it, because there is no package metadata.

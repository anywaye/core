# core-08 — the SLO and error-budget specification

**Branch** `worker/core-08` · **base** `38665cb` (core-07) · **gate** `bin/prime`,
140/140 · **self-test** 28 breakages, 28 reds, control green.

core now publishes what an SLO is in a cafaye deployment, what it may be computed
from, and what burning the budget means — as three schemas a self-hoster can run
in `bin/prime` or a service's own CI with no cluster, no Docker daemon and no
vendor contract.

## What I built

**Schemas (new, three files under `schemas/telemetry/`)**

| File | Decides |
| --- | --- |
| `slo.schema.json` | one service's declaration: `service`, required `tier`, `name`, `objective`, `period`, required `description`, `labels`, `sli.events.{total,error}_query`, `alerting.{name,annotations.runbook_url,page_alert,ticket_alert}`. `additionalProperties: false` at every level; `if`/`then` per tier derives both alert switches; `exclusiveMaximum: 100` on the objective; `const: 28d` on the period; `not: {pattern: "\bSLA\b"}` on SLO prose |
| `slo-windows.schema.json` | the normative burn-rate catalog: eight `prefixItems`, each pinning `window` **and** `factor` by `const`, with `items: false` |
| `slo-metrics.schema.json` | the SLI catalogue (five entries, four of them R6's candidates), `allowedLabels`, and `forbidden` with the two lists |

**The document** `docs/slo.md` — the artifact, why Sloth rather than OpenSLO, the
tier table, the arithmetic behind 14.4, the 28-day period, the SLI shape, the
four candidates, the two denylists with their two reasons, the multi-tenancy
answer, the spanmetrics migration, the "No SLA commitment" statement with its
exclusion list, the template, and what is not here yet.

**Examples** — `examples/valid/telemetry/slo.yaml` and `slo-windows.yaml`; four
negative cases (`slo.perfect`, `slo.page-on-low-tier`, `slo.window-override`,
`slo-metrics.denylisted`), each with a row in `examples/invalid/README.md`.

**The checker** — eight rules in `harness/cafaye_contract.py`, declared in
`harness/rules.json` with where each lives, each proved able to go red by a
breakage in `harness/tests/self_test.sh` that names the rule it expects:

| Rule | Where it lives |
| --- | --- |
| `slo.schema` | `schemas/telemetry/slo.schema.json` |
| `slo.window-token` | `check_slo_window_token` |
| `slo.unknown-metric` | `check_slo_metric_allowlist` |
| `slo.no-unbounded-dimension` | `check_slo_unbounded_dimension` |
| `slo.no-infrastructure-slo` | `check_slo_infrastructure_signal` |
| `slo.sli-canonical` | `check_slo_sli_is_canonical` |
| `slo.window-override` | `check_slo_window_override` |
| `slo.duplicate-name` | `check_slo_names_are_unique` |

Plus two fixtures (`conforming/slos/harness-fixture.yaml` and a new
`nonconforming-slos/`), the harness evaluator's two new keywords, and
`test_every_rule_the_harness_can_emit_is_proved_able_to_go_red`.

**File list**

```
schemas/telemetry/slo.schema.json                    (new)
schemas/telemetry/slo-windows.schema.json            (new)
schemas/telemetry/slo-metrics.schema.json            (new)
docs/slo.md                                          (new)
examples/valid/telemetry/slo.yaml                    (new)
examples/valid/telemetry/slo-windows.yaml            (new)
examples/invalid/telemetry/slo.perfect.invalid.yaml              (new)
examples/invalid/telemetry/slo.page-on-low-tier.invalid.yaml    (new)
examples/invalid/telemetry/slo.window-override.invalid.yaml     (new)
examples/invalid/telemetry/slo-metrics.denylisted.invalid.json   (new)
harness/cafaye_contract.py            +491   eight rules, two keywords
harness/rules.json                    +88   eight entries, two notEnforced
harness/tests/self_test.sh            +99   breakages 21-28
harness/tests/fixtures/conforming/slos/harness-fixture.yaml      (new)
harness/tests/fixtures/nonconforming-slos/**                     (new)
tests/test_specs.py                   +865   21 new tests, 4 widened
docs/contract-harness.md              +48   eight rows, the counts, the SLO section
examples/invalid/README.md            +60   four rows
CHANGELOG.md  README.md  AGENTS.md  DECISIONS.md   D26-D29 + the surfaces
```

## The gate, verbatim

```
$ bin/prime
…
140/140 passed

$ bin/prime --pytest
140 passed in 4.82s

$ bash harness/tests/self_test.sh
PASS self_test: breakage 27: an SLI that means the right thing and is spelled wrongly — caught by `slo.sli-canonical`
PASS self_test: breakage 28: the same SLO declared in two files — caught by `slo.duplicate-name`
PASS: self_test — all 28 breakages went red, and the unbroken tree is green.
```

Baseline was **119 passing** after core-07. Now **140**: twenty-one new tests,
none removed, none skipped, no assertion loosened, no sleep, no retry bump. Both
entry points agree at 140, which is what CI's guard checks. The CI self-test
guard, simulated locally: `claimed=28 logged=29 controls=1` — the extra assertion
is breakage 8, which asserts two rules because they are structurally coupled, and
the guard is `logged >= claimed` for exactly that reason.

The tests were written and shown failing first: 118/140 with every red naming a
missing file or a named constraint, then `test_the_harness_implements_every_keyword_core_schemas_use`
failing on its own with
`core's schemas use ['exclusiveMaximum', 'exclusiveMinimum'] and harness/cafaye_contract.py does not implement them`
before the evaluator grew them.

## The `sloth` dependency: **not taken**

**Taken? No.** Pinned how? It is not pinned into core's dependency story at all,
because it is not in it.

- `tests/requirements.txt` is unchanged. `bin/prime` remains one venv and four
  PyPI packages, installed once on first run.
- `harness/rules.json`'s `notEnforced` records the gap in the repository's own
  words, with the three alternatives and the recommendation.
- `docs/slo.md` gives the exact command for a service **that has network**:
  `sloth validate -i slos/`, plus the pinned
  `--slo-period-windows-path <core>/examples/valid/telemetry/slo-windows.yaml`.
  I have not pinned a Sloth *version* anywhere, because naming a version I cannot
  fetch would be a number nobody can check — D28 asks the manager to rule, and
  option 2 there names the cost (one line in `requirements.txt`, one CI step, a
  version to keep in step).

**What the harness does instead, so the check is not skipped:** it implements the
checks that matter in the standard library — `slo.sli-canonical` computes the one
legal composition from the catalogue and compares it **as a string**, which is
*stricter* about the shape than Sloth is (a query with correct semantics and
non-canonical spacing is refused, and self-test breakage 27 is that mistake), plus
the window token, the metric allowlist, both denylists and the duplicate-name
check.

**What is genuinely left, named rather than implied:** **PromQL grammar.** A query
that is the canonical string is by construction a valid expression in the shape
`sum(rate(m{a="b"}[window]))`, so the residual risk is small — but I am not
claiming a parser I did not write. It is in `notEnforced` and in D28.

**On a machine with no network:** nothing changes. `bin/prime` needs PyPI once
(unchanged), and the harness reads core from a checkout and never fetches. A
service that wants the grammar check adds one CI step and needs network for it;
a service that does not still gets eight rules.

## Decisions the brief left open

| # | Choice | Why |
| --- | --- | --- |
| 1 | **The schema describes the whole file** — `{version, service, slos[]}` — not one SLO object | The checked artifact is a Sloth file (`sloth validate -i <dir>` walks a directory of files), so a per-SLO schema would not be the shape anything validates. `service` at the root is also what binds every `service_name="…"` matcher. `version` is a `const` rather than absent, so a document cannot be read by a generator expecting another dialect |
| 2 | **`period` is per-SLO, not a generator flag** | R3 is a rule, and a rule nothing checks is not one. Sloth takes `--slo-period 28d` on the command line, where a service that forgets it silently gets `30d`. Carrying `period: 28d` in the file makes it a `const`; the flag stays in the documented command as well |
| 3 | **The SLI query is composed from a catalogue entry**, and the SLO names the entry in `sli.catalogEntry` | R7 constrains the *shape*, not the content — but a shape check on free text is a regex. Naming the entry makes the composition computable, which is what lets `slo.sli-canonical` be an equality rather than a pattern |
| 4 | **Labels sorted, comma-separated, no spaces**; `service_name` from the file's `service`, and refused in `labels` | A canonical *spelling* is what makes "exactly this string" checkable without a PromQL parser. Two spellings of `service` is two answers |
| 5 | **`allowedLabels` is an `enum`, not a pattern** | It is a closed list of eight bounded dimensions. A pattern admits `tenant_id`, which is the mistake the list exists to prevent |
| 6 | **The denylist lives inside `slo-metrics.schema.json`, as two properties — not its own file** | Both lists are consulted by the same check, on the same metric-and-labels, and the harness reads them from `schemas/` where the digest covers them. A separate file is a second file to load, pin and keep in step for nothing. **The separation that matters is the two lists, not two documents** — and they stay two properties with two reasons |
| 7 | **`errorSelector` is an object, capped at one matcher** | `{http_response_status_code_class: "5xx"}` rather than a PromQL fragment, so the schema can refuse an undeclared *key* without parsing. `maxProperties: 0` on the counter-based entries makes "empty" a decision rather than an omission |
| 8 | **A catalogue entry names two OTel names** (`otelName`, `errorOtelName`) | Three of the five candidates count their bad half on a *different* counter. With one name the error metrics could not be asserted as normalizations of anything — which is how I found it, when the test refused `email_dispatch_failed_total` |
| 9 | **Examples declare `example-service` and the fixture declares `harness-fixture`** | An example that named `courier` *would be* courier's SLO, and the boundary says those are the next packet's. `test_no_slo_example_declares_a_real_fleet_service` makes the boundary mechanical |
| 10 | **`slos/*.yaml`, optional directory** | Absence is not a failure, on the precedent of `worker-only.cafaye.yml` declaring no `exposes.api`. It is recorded in `notEnforced` so the absence cannot read as a pass over something |
| 11 | **The SLO rules are not gated behind `slo.schema`** (unlike the manifest rules) | Each reads a string, and a string is readable on a document whose tier is wrong. Gating would mean a service's first SLO failure is "your objective is 100" and never "your query has no `{{.window}}`" |

## Anything in R1–R8 I think is wrong — implemented as written anyway

**R2 and R3 are arithmetically inconsistent, and it is in the brief rather than
in the work.** `14.4 = 0.02 × 720h` — 720 hours is **thirty** days. R3 mandates a
**28-day** period, where 2% of the budget is **13.44**. So the workbook's factors
(which are also Sloth's shipped defaults) are about **7% conservative** under this
spec: the fast-burn alert fires slightly *early*. Both are implemented as ruled.
`test_the_window_catalog_is_the_workbooks_numbers` asserts the workbook's
arithmetic, the 28-day arithmetic, **and that the gap is in the conservative
direction**, so the inconsistency cannot harden into a number nobody recomputed.
**D27** records the alternatives (keep 14.4 / recompute to 13.44, 5.6, 2.8,
0.933 / revert to a 30-day period) and recommends keeping 14.4: the error is in
the safe direction, and 0.933 is a number the next person reads as a typo. The
whole point of publishing the arithmetic is that it can be checked — and it does
not check out, so I said so rather than choosing silently.

**Everything else in R1–R8 I could not fault**, with two notes rather than
objections:

- **R1's Sloth choice holds up** on the criteria it states, and I took it further
  than the brief did: `slo.sli-canonical` is a check Sloth has no equivalent of,
  so the harness is not merely standing in for `sloth validate` on the things that
  matter.
- **R4's derivation is the right shape, but the tier vocabulary has no stated
  meaning per tier.** `critical | high | low | none` is a judgment about how much
  of a deployment's traffic depends on the thing holding; the *mechanism* is
  mechanical and tested for all four tiers in both directions, but **which tier
  each of the seven services gets is a manager's call**, and it is **D29** with a
  recommendation. I did not guess.

One judgement worth flagging rather than defending: **`maxItems: 12` on `slos`.**
A self-hosted product with twenty users cannot have more than a dozen things a
user would notice, and a list that grows without bound is a list of charts. It is
my number, not the brief's, and it is one line to change.

## The self-test found two bugs in my own rules

Worth its own paragraph, because it is the argument for the whole apparatus. Self-test
breakages 23 and 24 — a `tenant_id` and a memory limit in the declared `labels` —
came back as `slo.sli-canonical` and `slo.schema`. Both were *true statements*: the
queries really had stopped matching the labels once a label was added. Both named
a **consequence instead of the mistake**, which is the failure mode of a rule that
is checking the wrong thing. The cause: `_denylisted` scanned the queries and not
the declaration's `labels` map — which is where the mistake arrives first, because
the labels are what the queries are supposed to be built from. It now scans three
places (query text, matchers inside the braces, labels names and values, since
`foo="tenant-42"` is the same dimension under another spelling), and both
breakages name their own rules. This is the second time in two packets that only
running a checker at its fixtures found the defect.

## Open decisions, all four reported

- **D26 — do the cafaye fields live inside the Sloth document, or in a cafaye
  document kit converts?** I could not check Sloth's tolerance of unknown keys
  without running it. Landed inside (four cafaye keys in a Sloth file,
  `additionalProperties: false` deciding), with a four-line transform in kit as
  the fallback and no rule changing.
- **D27 — the burn factors come from a 30-day budget and the period is 28 days.**
  Implemented as ruled, gap asserted, recommendation to keep 14.4.
- **D28 — may core's gate take the `sloth` dependency?** Not taken; the
  recommendation is that `sloth validate` belongs in a *service's* CI, where a
  network and a Go toolchain are ordinary.
- **D29 — which tier does each of the seven services get?** Not decided. A tier
  with no SLO behind it is a number with nothing to page on, and the packet that
  writes the SLOs is the first to meet a real self-hoster's traffic.

## What the next packet has to do, and what I left unbuilt

**Has to do**

1. **Emit the four counters the catalogue names** —
   `messaging_outbox_publish_total` / `…_failed_total`,
   `email_dispatch_attempted_total` / `email_dispatch_failed_total`,
   `invoice_compute_total` / `invoice_compute_failed_total` — in the language each
   service is written in. They are named in `slo-metrics.schema.json` and owed
   here; `http_server_request_duration_seconds_count` already exists by way of
   native instrumentation.
2. **Pin the collector version in the kit templates**, and treat a bump as a
   breaking change — the spanmetrics `ms`→`s` default is a fleet-wide metric
   rename that no service-level test can see.
3. **Write the declarations**, one `slos/<service>.yaml` per service, and settle
   the tiers (**D29**). Every rule is mechanical once the tier is chosen.
4. **Write the budget report**: how much of the budget is left over the 28 days.
   One page of PromQL over the recording rules Sloth generates; owed with the
   first real SLO, not before.

**Deliberately unbuilt**

- **No SLO for any of the seven services** — the packet boundary, now enforced by
  a test.
- **No PromQL parser.** Named in `notEnforced`, not skipped.
- **No per-tenant view.** Described (recording rules and logs and traces over the
  `resourceAttributes`) and not written; nothing in an SLI ever carries a tenant.
- **No metrics backend, no collector config, no exporter.** core specifies; kit
  deploys.
- **No `cafe contract lint`**, and D23 (sixteen rules the harness keeps in code
  becoming a JSON Schema) is still open — the harness has now made twenty-three,
  which is a finding the manager should weigh rather than a question this packet
  had to answer.
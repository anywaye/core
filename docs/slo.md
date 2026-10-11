# SLOs and error budgets

What a cafaye SLO is, what it may be computed from, and what burning the budget
means — as a self-hoster can run it in CI, with no Kubernetes cluster and no
vendor contract. The machine-readable half is three schemas under
[`schemas/telemetry/`](../schemas/telemetry/); this document is the same contract
written as prose, and `tests/test_specs.py` fails if the two disagree.

| Schema | Rule | Enforced by |
| --- | --- | --- |
| [`slo.schema.json`](../schemas/telemetry/slo.schema.json) | the shape of one service's SLO declaration, and the four failure modes | `test_the_tier_alone_decides_whether_a_page_is_generated` + the invalid examples |
| [`slo-windows.schema.json`](../schemas/telemetry/slo-windows.schema.json) | the burn-rate window catalog, pinned once | `test_the_window_catalog_is_the_workbooks_numbers` |
| [`slo-metrics.schema.json`](../schemas/telemetry/slo-metrics.schema.json) | the SLI catalogue, the label allowlist, and the two denylists | `test_the_two_denylists_are_two_prohibitions_and_the_schema_refuses_each` |

## Why Sloth, and what OpenSLO was for

**The checked artifact is a Sloth `prometheus/v1` file.** Three candidate specs
were researched — Sloth, OpenSLO and Pyrra — and Sloth is the one whose
validator is a single static binary that walks a directory with no cluster and
no Docker daemon:

```
sloth validate -i slos/
```

It also *generates* the recording rules and the burn-rate alerts rather than
describing them, and its SLI is two PromQL strings — **the one representation
all six of cafaye's languages can be checked against without a Go or Rust
parser**. That last property is the one that decided it. A shared client library
would be the alternative, and it is the thing six languages would each grow a
copy of; two strings are checkable by core's own harness with the standard
library.

**OpenSLO's vocabulary is adopted, its conformance is not the gate.** The words
in this document and in the schemas — objective, SLI, error budget, window,
burn rate, indicator type — are OpenSLO's, because they are the industry's and a
self-hoster will have read them. Its v1/v2alpha conformance is a bad CI gate:
its own spec page says the Go SDK requires exactly one time window while the
spec makes the window optional, and Sloth's importer is pinned to `v1alpha` by
regex. A gate whose two implementations disagree about whether a document is
valid is a gate that fails on somebody else's machine.

**D26** records the one question in this packet core could not answer offline:
whether the cafaye fields live *inside* the Sloth document or in a cafaye
document kit converts — Sloth's tolerance of unknown keys cannot be checked
without running it. See
[DECISIONS.md](../DECISIONS.md#d26-do-the-cafaye-fields-live-inside-the-sloth-document-or-in-a-cafaye-document-kit-converts).

## The failure modes, and the constraint that refuses each

Every rule below is a schema constraint plus a test. A convention that lives
only in a paragraph is a wish (AGENTS.md).

| The mistake | What refuses it |
| --- | --- |
| An SLO nobody is paged for — a chart, not a contract | `tier` is required, and it alone derives both alert switches |
| An SLO on `cpu` rather than on behaviour | the `infrastructureSignals` denylist, and the SLI catalogue's closed set of metrics |
| A per-tenant SLI, unaffordable at this traffic level | the `unboundedDimensions` denylist, and `metrics.schema.json`'s prohibition |
| A burn rate off by enough to fire early or late | the window catalog is a `const` per position, with the arithmetic published |
| An SLO at 100%, which can only ever be reacted to | `objective` has `exclusiveMaximum: 100` |
| An SLA for a tier the platform team does not operate | `not: {pattern: "\bSLA\b"}` on the prose, and the test that walks every schema value and every example |

## The tier, and the only thing it decides

`critical | high | low | none`, required, no default. **The tier alone decides
whether a page is generated**, and the schema derives both switches from it
rather than letting a service choose:

| Tier | `page_alert.disable` | `ticket_alert.disable` | What it means here |
| --- | --- | --- | --- |
| `critical` | `false` | `false` | Nobody can use the product. Paged on fast burn, ticketed on slow burn. |
| `high` | `false` | `false` | Most users cannot use the product. Same alerts, same silence. |
| `low` | `true` | `false` | A degradation a user might mention. A ticket, not a page. |
| `none` | `true` | `true` | Published as documentation. No alert is generated. |

This is the single most important rule in the packet. A page-level burn alert
per SLO across seven services is textbook alert fatigue: the self-hoster mutes
them within a week, and muting them costs the whole instrument — because the
`critical` SLO on the same service goes quiet in the same gesture. The
workbook's "alerting on scale" guidance buckets by how much of the traffic
depends on the thing holding, and most of a self-hosted private product's surface
is `low` or `none`. `page_alert.disable: false` on a `low` SLO does not
validate, and
[`examples/invalid/telemetry/slo.page-on-low-tier.invalid.yaml`](../examples/invalid/telemetry/slo.page-on-low-tier.invalid.yaml)
is that document.

**The slow-burn alert earns its keep.** `low` keeps `ticket_alert` because the
6h+3d pair at factor 1 is what catches an outage the fast windows never tripped
— the one that would otherwise stay invisible for a day.

## The window catalog, and why 14.4 is not 15

**14.4 / 6 / 3 / 1, at 5m+1h, 30m+6h, 2h+1d, 6h+3d.** Short window then long
window, four pairs: the fast pair is what a pager reads at 3am, the slow pair is
what a ticket reads on Monday, and the factor is the multiple of the whole error
budget being consumed per window.

**The arithmetic, published because the number will be questioned:**

```
14.4  =  0.02 x 720h          2% of the budget, in the 1-hour window
6     =  0.05 x 720h          5% of the budget, in the 6-hour window
3     =  0.10 x 720h          10% of the budget, in the 1-day window
1     =  0.10 x 720h x 4.32   10% of the budget, in the 3-day window
```

Rounded up to 15, the fast-burn alert fires **before** 2% of the budget is gone
— early about being early, which is the safe direction, and still wrong, because
the number on the dashboard no longer means what the spec says it means.

**The catalog is pinned once, in core, and a service may not carry its own.**
Sloth takes `--slo-period-windows-path` for exactly this, which is why the
declaration is closed and a `windows:` key on an SLO is an undeclared key:
[`examples/invalid/telemetry/slo.window-override.invalid.yaml`](../examples/invalid/telemetry/slo.window-override.invalid.yaml).
Two dashboards that both say "error budget" and disagree about the threshold is
worse than one.

**The arithmetic and the period disagree, and the disagreement is
conservative.** 14.4 is 2% of a **720-hour** budget, and 720 hours is thirty
days — but the period above is twenty-eight days, where 2% is 13.44. So the
workbook's factors, which Sloth ships as its defaults, fire ~7% *early* under
this spec. Early is the safe direction, and the number is still the workbook's;
**D27** records the arithmetic, both numbers, and the one-line cost of
recomputing them for a 28-day budget. See
[DECISIONS.md](../DECISIONS.md#d27-the-burn-factors-come-from-a-30-day-budget-and-the-period-is-28-days).

## The period: 28 days, not 30

**`period: 28d`, a `const`.** Integral weeks, so the window always contains
exactly four weekends — and a self-hoster does maintenance on weekends. A
30-day window contains 4.3 of them, so the same maintenance costs a different
fraction of the budget every month and the error budget stops being comparable
to itself. A period nobody wrote down is a period somebody assumed, and Sloth's
own default is 30d, so the assumption has to be refused rather than inherited.

## The SLI: good events over total events

**Every SLI is good events over total events.** R7 constrains the *shape* and
not the content, because every alerting rule, budget calculator and report we
will ever write assumes a numerator, a denominator and a threshold. The shape is
one expression:

```
sum(rate(<metric>{<label>="<value>",…}[{{.window}}]))
```

Labels are sorted, comma-separated, no spaces. **`{{.window}}` is required in
both queries** — Sloth substitutes it with each burn-rate window when it
generates the alerts, and a query without it computes over whatever window the
recording rule happens to use. Nothing anywhere reports that the two windows
differently, which is why it is a `pattern` in the schema *and*
`slo.window-token` in the harness.

**An SLO is scoped to a named user-visible operation, not to a service** (R6).
`http_route: /v1/auth/token` is the difference between "users can log in" and
"the identity service answered most of its requests". The second is true while
every login fails, which is the failure a service-scoped SLO hides rather than
catches — and it is why `requiredLabels` is not optional on the
operation-scoped entries and why `labels` is required and non-empty on every
SLO.

**The SLI catalogue replaces a shared client library.** A metric name in any
cafaye SLO must be one `slo-metrics.schema.json` names, and the names are the
**Postgres-normalized** spellings of the OpenTelemetry ones beside them:

| OpenTelemetry | In an SLO query |
| --- | --- |
| `service.name` | `service_name` |
| `http.response.status_code_class` | `http_response_status_code_class` |
| `http.route` | `http_route` |
| `http.server.request.duration` (count series) | `http_server_request_duration_seconds_count` |

Getting that normalization right by hand in six languages is the exact error
class this file exists to prevent, and it is why
`test_the_slo_catalog_declares_r6s_candidates_and_normalizes_every_name`
*derives* the expected name rather than comparing two lists.

### The four candidates, already written out

| Catalogue entry | The operation a user can notice | Metric |
| --- | --- | --- |
| `http_server_availability` | requests served without a server error | `http_server_request_duration_seconds_count` |
| `authentication_succeeds` | a caller can log in | the same, scoped to the auth route |
| `event_accepted_into_outbox` | an accepted event is published, not stranded | `messaging_outbox_publish_total` / `…_failed_total` |
| `email_dispatched` | a password reset reaches a provider | `email_dispatch_attempted_total` / `email_dispatch_failed_total` |
| `invoice_computed` | an invoice is computed, not failing to compute | `invoice_compute_total` / `invoice_compute_failed_total` |

Named after the **operation**, never after a service: a catalogue entry called
`identity` would be an SLO for identity written by a specification, with a
threshold nobody chose. The four counters are **named here and owed by the next
packet** — a service that declares an SLO on one of those entries emits the
metric the entry names, and this file is what makes that mechanical.

**Money is never a metric.** `metrics.schema.json` has no currency unit for
exactly this reason, so `invoice_computed` counts computations and never
amounts.

## Two denylists, because there are two reasons

Unbounded dimensions and infrastructure signals are **two prohibitions with two
reasons**, and they are kept apart because a reader who is about to add one of
these needs the reason, not the verdict.

**They live inside `slo-metrics.schema.json`, as two properties, and not in a
file of their own.** The reason is mechanical: both lists are consulted by the
same check, in the same place — a metric name and the labels around it in an SLI
query — and the harness reads them from `schemas/`, where `--expect-digest`
covers them. A separate `slo-denylist.schema.json` would be a second file to
load, pin and keep in step, with nothing gained by the separation, because the
thing being separated is *two lists*, not *two documents*. The two lists are
what matters, and they are two properties: `forbidden.unboundedDimensions` and
`forbidden.infrastructureSignals`, each with its own reason.

**Unbounded dimensions — `tenant`, `user_id`, `account_id`, `request_id`.**
OpenTelemetry caps aggregation at 2000 distinct attribute combinations per
metric stream and, on overflow, folds everything into one point and drops every
measurement attribute: totals stay right, every breakdown silently undercounts,
and nothing reports an error. `metrics.schema.json` already prohibits all four
as measurement attributes and *requires* `tenant_id` and `account_id` on
`resourceAttributes`, which are exempt from the cap. So a per-tenant SLI is not
merely discouraged here — it is unreachable.

**Infrastructure signals — `cpu`, `memory`, `pod`, `restart`.** An SLO on these
is not an SLO. They describe the machine a service runs on, not anything a user
can notice: a crash-restart loop on a service nobody is calling is green in
every user-visible measure and red in every infrastructure one. They are also
the measures a deployment has to keep well away from its limits, which is a
capacity decision with an owner and a lead time — not an error budget. They
belong in an alert on a *symptom* the service's own RED metrics show, and in a
runbook.

### One tenant, twenty users: where per-tenant answers come from

The multi-tenancy question is already answered in this repository, so it is
answered here rather than deferred.

**The metric is aggregate. Attribution is a logs-and-traces question.** An
SLO's `total_query` cannot carry `tenant_id`, because the measurement attributes
that count toward the 2000-combination cap are exactly where identity is
baranged out; identity belongs on `resourceAttributes`, which are attached once
per process, are exempt from the cap, and survive on the overflow point. That is
the whole mechanism, and it is why a per-tenant total stays *answerable* even
when the measurement has folded.

So a per-tenant view is not forbidden — it is **built the other way round**: as
**recording rules** and log-and-trace queries — logs and traces — over the
resource attributes, not as a metric dimension. A recording rule keeps its
dimensionality explicit and reviewable; putting `tenant_id` on the measurement
hides a per-tenant ratio in a fleet-wide average that renders perfectly and is
wrong. The next reader will ask whether an SLO is per-tenant, and "the metric
schema prohibits it" is the answer, with the destination attached.

## Native HTTP instrumentation, and the collector that moves

**A service derives its HTTP SLI from native OpenTelemetry HTTP instrumentation,
never from a `spanmetrics`-derived metric.** If a service derives RED metrics
through the `spanmetrics` connector, the collector's unit default is migrating
from `ms` to `s`, which renames `traces_span_metrics_duration_milliseconds_bucket`
to `…_seconds_bucket` and breaks **every latency query in every service at
once** — between the service and Prometheus, where no service-level test can see
it. Nothing a service writes catches a change that happens after the exporter.

`http.server.request.duration` is **Stable**, has recommended bucket
boundaries, and `http.route` is the route template rather than the concrete
path — which is precisely the low-cardinality rule `metrics.schema.json` already
encodes, and precisely why it is the right metric to build an SLO on.

**The collector version is pinned in the kit templates, and a bump is a
breaking change.** The move is the collector's, not the services': a fleet-wide
metric rename has to be one reviewed commit in one place, and "upgrade the
collector" is the kind of step that looks routine in a dependency bump and is
not.

## No SLA

**cafaye publishes no service-level agreement.** Not in a schema, not in a doc,
not in an example — `test_no_sla_token_appears_in_a_schema_or_an_example` walks
every `const`, `enum` and `default` in `schemas/` and every example file, and
`not: {pattern: "\bSLA\b"}` refuses the acronym in any SLO prose.

What a self-hosted deployment gets instead, stated in the shape of an honest
statement:

**No SLA commitment.** An SLO describes *intended behaviour on adequate
hardware, measured by the operator*, with the exclusions published. The
exclusions are the part that makes it honest, and they are:

- **adequate hardware** — the SLO holds on a deployment sized for the traffic
  it is given; it is not a capacity promise;
- **the operator measures** — cafaye ships the SLI, the burn-rate rules and the
  budget report; nobody is on call for this tier on your behalf;
- **excluded from the budget** — anything already visible as a dependency's own
  error, a customer's own bad input (a 4xx is never a failure, which is why the
  error selectors are `5xx` and `*_failed_total` only), maintenance on a
  weekend window inside the period, and third-party provider outages beyond the
  dispatch boundary (`email_dispatched` measures **dispatched**, not delivered:
  delivery is the provider's promise and this fleet does not operate it);
- **no contractual remedy** — there is nobody to claim one from. That is the
  difference between an SLO and an agreement, and pretending otherwise is what
  the acronym would have meant.

## The template

A service copies [`examples/valid/telemetry/slo.yaml`](../examples/valid/telemetry/slo.yaml)
to `slos/<service>.yaml`, which declares `example-service` and is therefore a
template and not a declaration — an example that named a real service *would be*
that service's SLO, and `test_no_slo_example_declares_a_real_fleet_service`
says so.

```yaml
version: prometheus/v1
service: example-service
slos:
  - tier: low                                   # the only thing that decides whether a page exists
    name: example-service-http-availability
    objective: 99.5                             # never 100
    period: 28d                                 # never 30
    description: Requests for a widget list return without a server error.
    labels:
      http_route: /v1/widgets                   # the operation, not the service
    sli:
      catalogEntry: http_server_availability    # the metric and its labels come from here
      events:
        total_query: 'sum(rate(http_server_request_duration_seconds_count{http_route="/v1/widgets",service_name="example-service"}[{{.window}}]))'
        error_query: 'sum(rate(http_server_request_duration_seconds_count{http_response_status_code_class="5xx",http_route="/v1/widgets",service_name="example-service"}[{{.window}}]))'
    alerting:
      name: ExampleServiceHttpAvailability
      annotations:
        summary: example-service is failing widget requests
        runbook_url: ../docs/runbooks/example-service/example-service-http-availability.md
      page_alert:
        disable: true                           # tier: low — a ticket, not a page
      ticket_alert:
        disable: false
```

### `runbook_url` is a path in the repository, never a host

PLAN §3 L6 retired `runbooks.cafaye.com`, and the shape now is
`../docs/runbooks/<service>/<slo-name>.md` — **a path from the declaring
`slos/<service>.yaml` to the runbook that sits beside it in the same
repository**. The schema's `runbookUrl` pattern is the whole rule:
`^\.\./docs/runbooks/[a-z][a-z0-9-]*/[a-z][a-z0-9-]*\.md$`.

Three things this buys, and the reason it is not a cosmetic change.

**It resolves where the pager already is.** The responder is in the
checkout, at 3am, with the service that is burning its budget in front of
them. A repo path opens there; a host asks for a browser, a login, and a
second place to be current.

**It cannot rot.** `runbooks.cafaye.com` was never served, so the old shape
was a link to a 404 with the responder's first move behind it. A path in the
repository cannot be lost to a DNS change, a decommissioned host or a
docs-site reorganisation — and PLAN §1's stability rules, which freeze the
error `type` base precisely because a client stores that URI for years, have
no equivalent for a runbook, because a runbook is not stored by anybody.

**It puts the runbook beside the change that broke it.** A runbook in the
service's repository travels with the service: the same diff that alters a
burn-rate path can alter the responder's first move, and reviewers see both.

**What it does NOT do is check the file exists.** `harness/rules.json`
records that as `notEnforced`, and it stays there for now. It is decidable —
the value is a repo path, so the harness could resolve it against the
checkout and report a missing file — and the reason it is not enforced is
the same reason `slo.schema` cannot carry it: nothing in the fleet declares
an SLO yet, because the metrics `slo-metrics.schema.json` names do not all
exist. A rule requiring an existing file would turn every future first SLO
red on a documentation gap rather than on a burn-rate mistake. It becomes
enforceable the moment the first real SLO lands; until then it is written
down.

Generating the rules, pinned to core's catalog:

```
sloth generate -i slos/ \
  --slo-period 28d \
  --slo-period-windows-path <core>/examples/valid/telemetry/slo-windows.yaml
```

## What the harness checks, and what `sloth` adds

`harness/` reads `slos/*.yaml` and applies eight rules, each one declared in
[`harness/rules.json`](../harness/rules.json) and proved able to go red by
`harness/tests/self_test.sh`:

| Rule | What it decides |
| --- | --- |
| `slo.schema` | the declaration satisfies `slo.schema.json` — objective, period, tier, the derived alerts, the closed object |
| `slo.window-token` | both queries carry `{{.window}}` |
| `slo.unknown-metric` | every metric in a query is one the catalogue names |
| `slo.no-unbounded-dimension` | no unbounded dimension in a query or a label |
| `slo.no-infrastructure-slo` | no infrastructure signal in a query or a label |
| `slo.sli-canonical` | each query is *exactly* what the catalogue entry composes to for this service's labels |
| `slo.window-override` | the declaration carries no window catalog of its own |
| `slo.duplicate-name` | no two SLOs share a name |

**`sloth validate` is not run by core's gate**, and that is a decision rather
than an omission. Taking the dependency would mean core's gate reaching the
network for a Go binary on a runner that may be air-gapped, and
`tests/requirements.txt` plus `bin/prime` is the repository's whole dependency
story. The harness instead implements the checks that matter here — the SLI
composition, the label allowlist and the two denylists — in the standard library,
and `slo.sli-canonical` is *stricter* than anything Sloth checks: it compares
the query against the canonical composition as a string. What `sloth validate`
adds, and what core therefore cannot check on an air-gapped runner, is
PromQL **parsing**: that the expressions are valid PromQL rather than merely the
canonical text. Run it as a second CI step in a service that has network:

```
sloth validate -i slos/
```

> **D28** records the `sloth`-dependency decision this packet made — not taken,
> with the exact command for a service that has network, and what a runner
> without one gets. See
> [DECISIONS.md](../DECISIONS.md#d28-may-cores-gate-take-the-sloth-dependency).

## What is not here yet

- **No service declares an SLO.** That is the next packet, and it needs the four
  counters above to exist. An SLO written before the metric exists is a
  commitment nobody can keep, which is the mistake this document spends 400
  words on from the other direction.
- **Which tier each of the seven services gets** is **D29** — the derivation is
  mechanical once the tiers are chosen, and the choice is a manager's.
- **The budget report** — how much of the budget is left, over the 28 days — is
  a query over the recording rules Sloth generates. It is one page of PromQL
  and it is owed with the first real SLO, not before.
- **Per-tenant views** are recording rules and log queries, described above and
  not written. Nothing in the SLI ever carries a tenant.
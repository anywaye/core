# Observability

What every anywaye service may put in a trace, a metric or a log record; what it
may never put there; and how the whole thing is turned off. The machine-readable
half is [`schemas/telemetry/`](../schemas/telemetry/), and this document is the
same contract written as prose. `tests/test_specs.py` fails if the two disagree,
which is the point — a rule that is not in `schemas/` is not a anywaye rule
(AGENTS.md), and a rule that is only in this file is a wish.

| Schema | Rule | Enforced by |
| --- | --- | --- |
| [`span-naming.schema.json`](../schemas/telemetry/span-naming.schema.json) | one span-name scheme, low-cardinality by construction | `test_span_names_are_low_cardinality_by_construction` + the invalid example |
| [`traces.schema.json`](../schemas/telemetry/traces.schema.json) | the trace attribute allowlist | `test_every_signal_declares_an_allowlist` |
| [`metrics.schema.json`](../schemas/telemetry/metrics.schema.json) | the measurement allowlist and the prohibition on unbounded identifiers | `test_prohibited_identifiers_are_not_measurement_attributes` + `test_a_tenant_id_measurement_attribute_is_rejected` |
| [`logs.schema.json`](../schemas/telemetry/logs.schema.json) | the log attribute allowlist | `test_every_signal_declares_an_allowlist` |
| [`redaction.schema.json`](../schemas/telemetry/redaction.schema.json) | the redaction boundary, and where it is enforced | `test_the_redaction_boundary_is_a_schema` + `test_the_redaction_policy_never_allowlists_a_content_attribute` |
| [`otel-endpoint.schema.json`](../schemas/telemetry/otel-endpoint.schema.json) | the `*_OTEL_ENDPOINT` contract and the no-op path | `test_unsetting_the_endpoint_declares_a_free_no_op` |
| [`probes.schema.json`](../schemas/telemetry/probes.schema.json) | `healthz` unconditional, `readyz` really checking | `test_a_readyz_that_checks_nothing_is_rejected` |

Three of these are decisions the manager owns: **D13** (where redaction is
enforced), **D14** (`error.type` granularity), **D15** (the span-name form). The
endpoint variable is **D16**, **D17** records a divergence this packet found
rather than fixed, and **D18**/**D19** are the two questions D14's implementation
raised rather than answered: which classes are in the vocabulary, and whether the
OTel fallback belongs in a snake_case one. All seven are in
[DECISIONS.md](../DECISIONS.md#d13-where-is-the-redaction-boundary-enforced--the-collector-or-each-service)
with the alternatives and the cost of flipping.

## Span names

```
span-name := <service> "." <operation> [ "." <target> [ "." <qualifier> ] ]
service   := anywaye namespace name — kebab-case, may contain a dash
operation := lowercase word, optional internal underscore, at most 15 characters
```

- **`muse.request`** · `muse.route` · `muse.provider.call` ·
  `identity.db.query` · `courier.email.deliver` · `gateway.request.authorize`
- **Never** `GET /users/:id` · `get_user` · `users.GET` ·
  `muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` ·
  `muse.request.4bf92f3577b34da6a3ce929d0e0e4736`

The prefix is mandatory and is the emitting service's own `name`, the same rule
as the event grammar's `<service>.<entity>.<action>` and for the same reason: an
unprefixed name says what happened and not who did it, so a query has to guess
which of six services to attribute it to. The form is deliberately the *same
shape* as an event type, because a fleet that has one dotted-lowercase grammar
for both is a fleet that has one thing to learn.

**Low-cardinality by construction.** A segment is at most fifteen characters, and
that bound is what does the work: `muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` is
rejected not because the grammar knows about anywaye id formats but because no
legal segment is twenty-six characters long. A name that interpolates a value is
a span per value, which is the metric-side failure below wearing a trace's
clothes, and it is worse on traces because a trace backend is a search engine
and nobody notices until the index is unusable.

**What goes in the name, what goes in an attribute.** The name is the operation.
Everything else is an attribute. This is not a stylistic preference: a name is
the grouping key in every trace UI, so an attribute in the name is an attribute
that cannot be filtered out, and a route template in the name is a cardinality
explosion with a `GET` attached.

| Signal | Worked example | In the name | On the span |
| --- | --- | --- | --- |
| traces | `muse.provider.call` | `muse` · `provider.call` | `llm.model`, `llm.tokens_in`, `http.route: /v1/route`, `error.type: provider_auth` |
| metrics | `http.server.request.duration` | `http.server` · `request` | `http.route: /v1/users/{id}`, `http.response.status_code_class: 2xx` |
| logs | `outbox.publish.failed` | `outbox` · `publish` | `log.severity: error`, `error.type: dependency_unavailable`, body `"outbox row 4471 exceeded 5 attempts"` |

`kind` — `internal`, `server`, `client`, `producer`, `consumer` — is a span
*field*, never part of the name. Two spans with one name and different kinds are
different work, and the name should stay the same; a name that encodes the kind
is a name that has to change when the relationship does.

## Attributes, per signal

Each signal has its own closed list. A name that is not on the list for its
signal is not emitted — default-deny, so an attribute added in a hurry is
dropped rather than shipped.

| Attribute | traces | metrics | logs | Cardinality |
| --- | :---: | :---: | :---: | --- |
| `http.request.method` | ✓ | ✓ | | 8 values (enum) |
| `http.response.status_code` | ✓ | | | 500 values (100–599) |
| `http.response.status_code_class` | | ✓ | | 4 values (`2xx`…`5xx`) |
| `http.route` | ✓ | ✓ | | one per endpoint — the **template**, never the concrete path |
| `db.system` | ✓ | ✓ | | 4 values |
| `db.operation` | ✓ | ✓ | | 6 values (closed verb vocabulary) |
| `messaging.system` | ✓ | ✓ | | 3 values |
| `messaging.operation` | ✓ | | | 5 values |
| `otel.status_code` | ✓ | | | 2 values |
| `error.type` | ✓ | ✓ | ✓ | **12 classes + `_OTHER`**, a closed `enum` — see below |
| `log.severity` | | | ✓ | 6 values |
| `service.name` | | | ✓ | bounded by the size of the fleet |

- **`error.type` is a closed vocabulary, not a bounded free string.** The same
  `enum` on all three signals. A `pattern` bounds the shape of a value and not
  the set of values, which is how `user_42_email_invalid` came to validate —
  see the [`error.type` section](#errortype).

Three things the table is shaped to say:

- **`http.route` is the template.** `/v1/users/{id}` has one value per endpoint.
  `/v1/users/usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` has one per request, and
  `url.path` and `url.full` are therefore not on any list.
- **Metrics are coarser than traces on purpose.** Traces carry the status code;
  metrics carry the status *class*. A metric multiplied by 500 codes and every
  route is how a service reaches the cap below in a week, and `4xx` answers the
  question a dashboard actually asks.
- **No allowlisted name contains a word that names content** — `prompt`,
  `completion`, `message`, `content`, `text`, `body`, `header`, `input`,
  `output`, `arguments`, `instructions`, `transcript`, `query`. This is
  muse's canary promoted to a spec assertion: `muse/tests/test_trace_propagation.py`
  asserts the same property of muse's `ALLOWED_SPAN_ATTRIBUTES`, and a real leak
  arrives as a well-meaning `muse.prompt` added in six months by someone
  debugging a routing decision, not as an attacker.

## The prohibition: no unbounded identifier on a measurement

> OpenTelemetry caps aggregation at **2000 distinct attribute combinations per
> metric stream**. On overflow the SDK folds everything into a single point
> carrying `otel.metric.overflow=true` and drops every measurement attribute.
> Totals stay correct; every per-dimension breakdown silently undercounts.

That is the worst shape a bug can have: the dashboard renders, the total looks
right, the breakdown is wrong, and nothing anywhere reports an error. So:

**Prohibited as a measurement attribute:** `tenant_id`, `user_id`, `account_id`,
`request_id`, `trace_id`, `span_id`, `session_id`, `message_id`,
`notification_id`, `email`. Also `error.message`, `error.stacktrace`, `url.full`
and `url.path` — unbounded or caller-influenced for the same reason.

**Required on `resourceAttributes` instead:** `tenant_id`, `account_id`,
`service.name`, `service.version`, `service.instance.id`, `deployment.environment`,
`service.namespace`, and the SDK's own `telemetry.sdk.name`, `.language` and
`.version`. Resource attributes are attached once per process rather than once
per measurement, so they are **exempt from the 2000-combination cap and survive
on the overflow point**. That is the whole mechanism: a per-tenant total stays
answerable when the measurement has folded, because the identity is not on the
measurement that folded.

**Four of those ten are there because a real span already carries them, and the
list was closed without them.** This is the only place in the spec where a
*closed* resource list has cost a publisher a validation, and it went unnoticed
because the two publishers whose resource the SDK contributes nothing to are the
two that validate: identity uses `resource.NewWithAttributes`
(`internal/telemetry/telemetry.go:542`), Go's **schemaless** constructor, which
does not merge the SDK's default resource, and courier builds its own resource map
(`lib/courier/telemetry.ex:277`) rather than letting one be assembled for it.
`service.namespace` is muse's own, set by hand at
`src/muse/telemetry.py:390` and asserted in `tests/test_resilience_config.py:355`;
the `telemetry.sdk.*` three are set by billing by hand at
`lib/kit/telemetry.rb:183-184` **and** added by every SDK whose `Resource.create`
merges. Measured, not quoted: against the 1.44.0 SDK in muse's own venv,
`Resource.create({'service.name': 'muse', 'service.namespace': 'anywaye'})` returns
six attributes, and four of them were refused by this list. All four are Stable
semconv resource attributes, bounded to one value per process, which is the
argument this section has been making for `service.name` all along.

The three lists are the same list in three files and
`tests/test_specs.py` now asserts they agree — the same rule
`test_the_span_name_pattern_is_shared_with_the_traces_schema` enforces on span
names, applied to the attribute list a service reads its resource contract out of.
See [D40](../DECISIONS.md#d40-is-the-resource-allowlist-missing-a-field-the-fleet-uses-or-is-a-service-emitting-something-it-should-not).

### What those two values actually look like — and the shape core does not type

**`tenant_id` is not an id.** It is an operator-set environment variable copied
verbatim onto the resource, never parsed: `IDENTITY_TENANT_ID`
(`identity/internal/telemetry/telemetry.go`), `COURIER_TENANT_ID`
(`courier/lib/courier/telemetry.ex`), `BILLING_TENANT_ID`
(`billing/lib/kit/telemetry.rb`). The producers' own tests give it `"acme"` and
`"tenant-abc"`. So core constrains its *shape* and not its value — dots, dashes
and alphanumerics, and **no underscore**, which is the one character in
`tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG` that nobody typing `acme` would produce. Typing
it as a uuid would have been wrong in the other direction: the next operator to
choose a non-uuid name would be rejected by core.

**`account_id` is a real id and it is a bare uuid** — `id.UUID.String()` in
identity's `internal/outbox/tenancy.go`, `Ecto.UUID` in courier — **on an event
payload. On a telemetry resource, no service in the fleet emits it.** Read across
the four services that export anything, `account_id` appears zero times in
identity's `telemetry.go`, courier's `telemetry.ex`, billing's
`kit/telemetry.rb` and muse's `telemetry.py`: identity appends
service.name/version/instance/environment/tenant_id, courier does
`maybe_put(:deployment)` and `maybe_put(:tenant_id)`, and muse's `_resource/1`
sets `service.name` and `service.namespace` and nothing else.

That second fact is why the examples under `examples/valid/telemetry/` no longer
carry an `account_id` on a resource, and why the rule that keeps them honest is a
**positive** check against a per-service ledger rather than a denylist of one
shape — a bare uuid in a field nobody populates is as much a fiction as a
prefixed ULID, and only a positive check can tell them apart. See
[D37](../DECISIONS.md#d37-how-does-core-check-that-an-examples-ids-are-the-ids-its-producer-mints).

**A gap this document does not close:** `metrics.schema.json` requires
`account_id` on nothing — it is permitted on the resource and prohibited on the
measurement, and that is all — while the list above says "required". The
permissive half is what let sixteen examples assert a value no producer emits.
Either the schema requires it and a service emits it, or the list drops it; the
first is a change to a contract with six publishers and is not core's to make
alone, so it is named here rather than decided in a comment.

The two lists are disjoint by construction and `tests/test_specs.py` asserts it
twice: that a resource name is never a measurement name, and that a resource
name is *rejected* when submitted as a measurement attribute. Moving identity
onto the measurement to get a per-tenant breakdown is the exact mistake that
produces a dashboard which looks right and is wrong, so the schema refuses it
rather than the document warning about it.

The prohibition is enforced twice in the schema on purpose: a prohibited name is
absent from the allowlist *and* named in a `not`, so adding it to the allowlist
later does not quietly succeed. It is also refused under its OTel spelling
(`error.message`, not just `error_message`), because a tracing SDK adds
`error.message` by default and a prohibition that only catches one spelling is
bypassed by a default rather than by a decision.

## The redaction boundary

**Prompt and completion content must never appear in a telemetry span.** This is
the hardest rule in the spec and the reason PLAN.md §7b describes the collector
as a chokepoint.

muse is an LLM gateway, so its spans will *naturally* want to record the prompt:
"which model, which prompt shape, how long" is the obvious thing to instrument,
and it is the obvious thing that writes every customer's content into a
searchable, retained, widely-readable log store. Encoding "don't log secrets" in
prose has been tried across this fleet and it does not hold. So the spec encodes
the **allowlist** instead.

**May be recorded about an LLM call** — the positive half, because a policy that
only says what may not be recorded is not implementable:

| Attribute | Type | Fact it is about |
| --- | --- | --- |
| `llm.model` | string | which model served the call |
| `llm.tokens_in` / `llm.tokens_out` | int | the **token count**, never the text it counted |
| `llm.latency_ms` | number | how long |
| `llm.finish_reason` | string | why generation stopped — the **finish reason** is a class (`stop`, `length`, `tool_call`) |
| `llm.provider`, `llm.cost_micros`, `llm.candidates_tried`, `llm.breaker_state` | | the routing decision |

**May never be recorded:** the prompt, the completion, message content, tool
arguments, system instructions, the transcript, anything a caller typed, a
credential, `error.message`, a stack trace.

Every entry in the first table is a fact about **how a call was served**. Every
entry in the second is a fact about **what the caller said**. That is the line,
and it is a line about the shape of the data rather than about intent — which is
what makes it enforceable by a collector that has no idea what a prompt is.

**Enforced at the collector, per PLAN.md §7b, with per-service allowlists as
defence in depth.** `redaction.schema.json` declares `enforcedAt: collector` as
an enum rather than describing it in prose, so kit's collector config and each
service's SDK setup are both checked against the same file, and a policy that
says "enforce it somewhere" is not checkable at all. The alternatives and the
cost of flipping are in **D13**.

`error.message` is the one attribute that is *already* on a natural allowlist —
every tracing SDK adds it by default — and it is the one attribute that could
carry a prompt: a vendor's content-policy rejection quotes the offending content
back at you. `error.type`, the exception's class, answers "what kind of failure"
with no content in it. That is why `error.message` is prohibited by name and not
merely absent.

**How a service proves it holds.** The house pattern is
`muse/tests/test_trace_propagation.py`: a canary string placed in *both* the
prompt and the completion, asserted absent from the rendered payload of every
span, and asserted **separately** from the key-name check so that truncation
cannot be what makes it pass. A span that records only `error.type` cannot carry
the message even if redaction were removed, which is the point of allowlisting
rather than scrubbing — two independent barriers to the same leak, because the
realistic failure is one of them being removed by a well-meaning change and
nobody noticing for a month.

## `error.type`

The user asked whether there is one place to see all errors for the whole
system. The answer is yes, and this attribute is the part of the spec that makes
it true rather than a wall of ungrouped text.

**First, the thing that is easy to get wrong.** The predicate for "this is an
error" in a fleet-wide view is **span status `Error`, not `error.type`.**
`error.type` is a classification *beneath* that predicate. So the dashboard is:
partition by `service.name`, filter on status `error`, and use `error.type` as a
**drill-down dimension inside a service** — valid under a service.name filter and
**never a global grouping key**, because semconv expects high cardinality there
when no filter is applied, and a global breakdown by class is exactly the wall of
ungrouped text this attribute exists to remove.

`error.type` is a **class**, from a **closed vocabulary of twelve classes plus
the OTel fallback `_OTHER`** — byte-identical on traces, metrics and logs. Never
a message, never a stack trace, never an interpolated value.

| Class | Why it earns its place |
| --- | --- |
| `invalid_request` | the caller to us gave us something that failed validation. The fix is a 400 and a caller-side correction, not a page. |
| `policy_denied` | a rule **anywaye itself** owns refused the operation — authorization, quota, our own content policy. Its rate is a business signal (misconfiguration, fraud), not an incident. |
| `provider_auth` | a third party refused **our credential**. The responder is whoever owns the key, and it is never an outage. |
| `provider_rejected` | the provider accepted the call and refused the request: bad parameters, or its content policy. Separate from `provider_auth` because rotating a key does not fix it, and separate from `policy_denied` because the rule being applied is theirs. |
| `rate_limited` | the peer asked us to slow down. Retryable, expected under load, and a different responder from `dependency_unavailable` — "later" is not "broken". |
| `timeout` | no answer inside the deadline. **One class, not one per dependency**: what timed out is the span's name and attributes, never the class. A class per target is how a twelve-value list becomes a hundred. |
| `connection_failed` | the call never left — DNS, refused, TLS handshake. "Did it go out at all?" is the first question on an incident and the answer changes the responder, which is why it is not folded into `dependency_unavailable`. |
| `circuit_open` | **we chose not to call.** Not a failure of the peer at all — it is our own breaker. Recorded so the fleet can see what a breaker suppressed, which is otherwise invisible. |
| `dependency_unavailable` | a dependency answered and said it is broken. In muse this is every provider candidate failing; it is the class that means "the vendor is down". |
| `conflict` | a uniqueness or concurrency conflict: duplicate write, lost race. The only class whose correct response is already known — retry, or tell the caller — and the most common non-crash error in a database-per-service fleet. |
| `cancelled` | the caller went away or the work was abandoned. It exists so the most common **non-incident** in an HTTP fleet does not land in `_OTHER` and inflate the error rate it is measured against. |
| `internal_error` | we are wrong: a nil dereference, an unhandled branch, a broken invariant. The class you page on, and the one that must trend to zero. |
| `_OTHER` | the OTel well-known fallback (**Stable**). It is the one member that is not snake_case, deliberately — see below. |

**Why a closed vocabulary and not a shape.** core-04 constrained `error.type` to
a `pattern` and a 64-character cap. That constrains the **shape** of the value
and says nothing about the **vocabulary**, so `error.type = "user_42_email_invalid"`
validated cleanly on all three signals — snake_case, twenty-two characters, and a
series per value. On metrics that is `tenant_id` on a measurement under a name
that sounds like a classification. The description promised a bounded vocabulary
and the schema did not have one, and a rule the schema does not enforce is not a
anywaye rule. It is an `enum` now, and
[`examples/invalid/telemetry/error-type.undeclared.invalid.json`](../examples/invalid/telemetry/error-type.undeclared.invalid.json)
is the shape of the mistake.

**Why the same list on all three signals.** A class that means one thing on
traces and another on metrics is three taxonomies wearing one name. It is also
what makes the cross-signal rule below enforceable at all: no JSON Schema can
compare two documents, so "identical on the span and its metric" has to be
structural rather than checked.

**`_OTHER`, and why it is here.** semconv defines `_OTHER` as the fallback for
instrumentation that has no custom value, and it is Stable. It does not fit the
snake_case shape, and it is in the vocabulary anyway: **a closed enum with no
escape hatch gets widened under pressure** the first time a real failure does not
fit, and a widened enum is how `_OTHER` becomes a permanent value nobody reads.
Carrying it is how instrumentation is never forced to invent a class. And an
alert on `_OTHER` is not noise — it is an alert that this service has
not classified its own errors, which is actionable and is the argument for
keeping it rather than omitting it.
**[D19](../DECISIONS.md#d19-does-_other-belong-in-a-snake_case-vocabulary)**
is that trade-off written down; **[D18](../DECISIONS.md#d18-which-classes-are-in-the-error-vocabulary)**
is why each of the twelve is in the list.

| A consumer **can** aggregate on | A consumer **cannot** aggregate on |
| --- | --- |
| span status `error` — the predicate for "this is an error" | `error.type` as a **global** grouping key (drill down under `service.name`) |
| `service.name` — a resource attribute, so it survives the overflow point | the message text (never recorded) |
| `error.type` × `service.name` — "every `provider_auth` in muse this hour" | a stack trace (never recorded) |
| | one series per request id (prohibited; see above) |

## When an error is recorded, and when it is not

Four rules the research behind PLAN.md §7b settled. All four are encoded rather
than described; the negative examples for three of them are in
`examples/invalid/telemetry/`.

1. **`error.type` is absent on success, and its absence is the load-bearing
   marker** — not an omission. On an operation duration histogram the samples
   carrying the class are the errors and every other sample is a success, which
   is how error rate is computable without putting a message in a label. So a
   span with status `ok` that carries a class does not add noise: it moves the
   **numerator**. Encoded both ways: status `error` **obliges** `error.type`, and
   `error.type` **obliges** a failed status.
2. **`error.type` is identical on the span and on the metric** for the same
   operation. Encoded as one shared `enum`, because the alternative — comparing
   two documents — is not something JSON Schema can do.
3. **Handled and retried errors are not recorded at all** (`SHOULD NOT` in
   semconv). A retry that succeeded is not an error, and recording it makes the
   error rate a lie. There is no schema keyword for `SHOULD NOT`, so this is
   encoded as **unrepresentable**: no signal allowlists an attribute a service
   could use to say "this attempt failed and I recovered", and the vocabulary
   itself has no class for it. The positive half is a retried-then-succeeded
   operation emitting one span with status `ok` and no class, which rule 1
   already validates.

   Two things that look like exceptions and are not. `cancelled` is a class
   because the operation genuinely *ended* in cancellation — not because anything
   recovered — and it exists so the most common non-incident in an HTTP fleet is
   not counted as one. `messaging.operation: nack` and `dead_letter` are
   deliberate protocol decisions: facts about what a span *did to a message*, in
   the same family as `policy_denied`, recorded on purpose and not because
   something broke.
4. **Span status `error` obliges `error.type`.** A status is a claim, and a claim
   has to be classifiable. `otel.status_code` exists as a mirror for log-indexed
   queries and may not contradict `status.code`, because a span with two statuses
   has no status to be obliged.

**Stability, marked honestly.** `error.type` and the trace status rules are
**Stable** in the OTel semantic conventions. The document that defines the
cross-signal coupling, **`recording-errors.md`, is Development**. Where this spec
encodes that coupling — rules 1, 2 and 3 — it is encoding something not yet
frozen, and each schema says so rather than implying the whole model has settled.

**`error.message` stays out, and stays out for the same reason.** It is
`NOT RECOMMENDED` for metrics and spans: unbounded cardinality, and it duplicates
span status. More concretely, `error.message` is the one attribute that is already
on a natural allowlist — every tracing SDK adds it by default — and the one that
could carry a prompt, because a provider's content-policy rejection quotes the
offending content back at you. A content-policy refusal is recorded as
`provider_rejected`, which says what happened with no content in it. A span that
records only `error.type` cannot carry the message even if redaction were
removed, which is the point of allowlisting rather than scrubbing.

### What is not migrated yet

**muse emits `error.type = "ProviderAuthError"` and `CircuitOpen` today**, and
`tests/test_trace_propagation.py` asserts both values. That is D14's stated cost
of flipping and it is a separate packet: this one changes the contract, it does
not migrate the callers. What the next author needs:

| Where | What |
| --- | --- |
| `muse/src/muse/router.py:399` | `{"error.type": type(error).__name__}` — one mapping function from muse's exception classes to the thirteen. |
| `muse/src/muse/router.py:335` | `{"error.type": CircuitOpen.__name__}` → `circuit_open`. |
| `muse/tests/test_trace_propagation.py:306` and `:412` | both assert `"ProviderAuthError"` → `"provider_auth"`. |
| `muse/src/muse/errors.py` | 21 error classes collapse onto 12. The ones needing a decision rather than a lookup: `ContentPolicyError` → `provider_rejected` (it is the *vendor's* rule), `CredentialUnavailable` / `VaultDecryptError` → `internal_error`, `AllCandidatesFailed` → `dependency_unavailable`, `ConfigError` → `invalid_request`, `ProviderIndeterminate` → `_OTHER`. |
| `muse/src/muse/telemetry.py:129` | `error.type` is on `ALLOWED_SPAN_ATTRIBUTES` already; the allowlist keeps working, the value vocabulary changes underneath it. |

The mapping is the whole cost, and it is one function in one language in the only
service that talks to a provider. The other five services emit no class yet, which
is the cheapest possible moment to make them all draw from one list.

## `*_OTEL_ENDPOINT`, and the no-op path

**`MUSE_OTEL_ENDPOINT`, `IDENTITY_OTEL_ENDPOINT`, `BILLING_OTEL_ENDPOINT`…** —
`<SERVICE>_OTEL_ENDPOINT`, uppercase, one name across all six languages, derived
from the service name so it is knowable without reading any code. **That
variable is the only contract.** The shipped collector is just its default
value.

```json
{
  "endpoint": {
    "variable": "MUSE_OTEL_ENDPOINT",
    "default": "http://otel-collector:4317",
    "required": false
  }
}
```

**Known drift, recorded not papered over (D17).** muse reads
`MUSE_OTEL_EXPORTER_OTLP_ENDPOINT` — the OTel standard spelling — while this
spec and `fleet.yml` say `MUSE_OTEL_ENDPOINT`, and PLAN.md §7b says muse honours
`MUSE_OTEL_ENDPOINT` too. Three places, three spellings, and muse agrees with
neither. This packet does not change muse: it is a read-only reference and no
service is instrumented here. The rename is one string in
`muse/src/muse/main.py` and one line in
`muse/tests/test_resilience_config.py`, and it is cheaper today than after three
more services have copied the spelling out of muse's code.

`required` is a `const: false` in the schema, and it is the field that separates
*on by default* from *mandatory*. A developer working on anywaye sees real traces,
real metrics and a real error view with nothing switched on, because the
default points at the collector that ships with the stack. A self-hoster who
already runs Datadog, Honeycomb or Grafana Cloud sets the variable and the
shipped stack goes quiet — a **supported deployment, not a degraded mode**, so
**bring your own** backend is documented with the same care as the default one.
A self-hoster who wants nothing sets nothing, and gets a genuine no-op.

### The no-op path is free, and that is asserted

> A "disabled" path that still dials out is worse than no telemetry support at
> all. (PLAN.md §7b)

So the schema does not accept the word "disabled". It accepts a declaration of
what does **not** happen, with four properties each pinned to `none`:

| Property | Value | What the alternative is |
| --- | --- | --- |
| `buffering` | `none` | a queue that accepts spans and retains them — a memory leak with a telemetry-shaped trigger |
| `retry` | `none` | a retry loop against an endpoint that is not there: a thread waking on a timer for the life of the process, invisible in every dashboard because nothing is being recorded |
| `warnings` | `none` | a warning per export attempt, filling the log store with the fact that telemetry is off — how a self-hoster discovers that turning it off is not supported |
| `startupCost` | `none` | a dial at boot, so a service's availability now depends on a component that ships with the product rather than with the deployment |

So the no-op path has four **no**s in it, and they are stated as negative
properties precisely so they can be checked: **no buffering**, **no retry**,
**no warning spam**, no dial at boot. A declaration that admits any of them is
rejected by the schema — there is no value other than `none`.

And it is pinned to the **OpenTelemetry spec's own switch**,
`OTEL_SDK_DISABLED=true`, rather than a anywaye mechanism invented here.
Re-implementing "disabled" in six languages is how six services acquire six
different definitions of it, and the difference between them is somebody's
production incident. The per-signal `OTEL_TRACES_EXPORTER=none` family is the
finer-grained half, and `disabledBy` requires at least three switches so a
declaration cannot document a no-op that only covers traces — a service that
still phones home for metrics is the failure discovered by a customer's invoice
rather than by a test.

Unsetting the endpoint and setting `OTEL_SDK_DISABLED=true` are the same
outcome, and the test is the same test: a span is created, nothing is queued,
nothing is sent, and no warning is logged.

## `healthz` and `readyz`

Liveness and **readiness**, the two halves of "what does green mean"
(PLAN.md §7b). darkroom is the pattern.

- **`/healthz` is unconditional liveness.** It consults *nothing* — the
  dependency list is constrained to be empty by `maxItems: 0`, so a `healthz`
  that starts checking the database cannot validate. A liveness probe that fails
  on a dependency tells the orchestrator to restart a process that is fine, which
  turns a database outage into a fleet-wide crash **restart loop** and destroys
  the evidence needed to diagnose it.
- **`/readyz` really checks dependencies.** `minItems: 1` on the check list, so
  **a service with a `readyz` that checks nothing fails the schema**. This is
  the failure the probes schema exists to prevent, and it is invisible because
  the endpoint returns 200 and looks perfect in every dashboard. Without it, a
  load balancer cheerfully routes traffic into a service whose database is gone.
- **Both are `exempt from authentication`**, by an explicit path allow-list
  rather than by route order. darkroom's README records the test that caught it:
  axum's `Router::layer` applies to every route the router holds, so registering
  the probes "before" the auth layer does not exempt them — a `/healthz` behind
  the auth middleware returns 401, every instance is marked unhealthy, and the
  deployment rolls back with no indication why.
- darkroom is the pattern: `/healthz` never touches a dependency, `/readyz`
  really runs `select 1`.

## What a service does with this

`cafe contract lint` reads these seven schemas alongside the event schemas, so a
service's telemetry declaration is checked against core the same way its
`anywaye.yml` is. `kit` consumes them for the six-language OTel templates and for
the collector's allowlist config; `fleet.yml` records per service which signals
it exports and which variable points at them.

**Three states, and the one `fleet.yml` records is the middle one.** Saying
"anywaye has no observability" is three claims wearing one coat, and only one of
them is a question `signals` answers:

- **Spec'd.** Core owns the contract and a rule exists. Every service has this.
- **Instrumented.** The service wires an OTel SDK and exports from its own code
  to whatever endpoint `<SERVICE>_OTEL_ENDPOINT` names. *This* is `signals`.
- **Deployed.** Something is running to receive it. Core deploys nothing, so no
  `fleet.yml` entry claims it and no field records it.

`signals: []` means a service emits no signal of its own. It does not mean the
service is uninstrumented in any way a reader would act on, and it does not mean
nothing is running — those are different sentences, and the second is not a
weaker form of the third. `test_a_service_recorded_as_exporting_nothing_asserts_no_fleet_wide_state`
is the assertion that keeps a per-service record from asserting a fleet-wide
fact, which is how the sentence "anywaye has no observability" got written at all.

The rules are not suggestions. A span named `get_user`, a `tenant_id` on a
metric, an `error.message` on a span, a `readyz` that checks nothing and a
"disabled" exporter that buffers each fail `bin/prime` in this repository, and
each has an invalid example under `examples/invalid/` naming the exact keyword
and the reason.

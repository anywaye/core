# Open decisions

Every question this spec has not been told the answer to, numbered, with the call
that was made so the work could continue and the cost of making the other one.

**These live here, not in `docs/`.** AGENTS.md asks for a
`> DECISION NEEDED (Dn):` callout in the affected document, and
`test_no_open_decision_callouts_remain_in_the_docs` fails if one is there. Those
two instructions cannot both be satisfied, and the test is the one to keep: it is
a merge gate whose whole job is that a spec on `master` reads as decided. The
other way round — weakening or skipping the gate — is exactly how a spec silently
stops being enforced. So the questions are numbered here and the affected
document cites the number, which `test_open_decisions_are_referenced_from_a_document`
enforces. A settled decision moves into the [CHANGELOG](CHANGELOG.md)'s decision
table and its entry here is deleted; the number is never reused.

| # | Question | Call made |
| --- | --- | --- |
| [D6](#d6-where-do-open-decisions-live) | where do open decisions live? | `DECISIONS.md` at the repository root |
| [D7](#d7-courier-keys-a-user-by-uuid-and-identity-publishes-a-usr_-id) | courier keys a user by uuid, identity publishes a `usr_` id — **the second half was never read out of identity and is false** | resolved by D35: one id vocabulary, a bare uuid, and a divergence between two services is a bug in one of them |
| [D8](#d8-what-is-the-subject-of-couriernotificationsuppressed) | what is the `subject` of `courier.notification.suppressed`? | the user id; both candidates stay in the payload |
| [D9](#d9-consumed-is-not-in-the-action-vocabulary-and-the-payload-has-no-account) | `consumed` is not in the action vocabulary, and the payload has no account | catalogue `consumed`; the missing account is muse's, not core's |
| [D10](#d10-billingsubscriptionstarteds-payload-schema-no-longer-describes-cafaye-ids) | `billing.subscription.started`'s payload schema required ids billing does not have | rewritten to the processor ids billing actually emits — a breaking change, recorded |
| [D11](#d11-billingpaymentsucceeded-has-two-payload-shapes) | `billing.payment.succeeded` is emitted from two sources with two shapes | `oneOf`, plus a rule for a payload with one type and two meanings |
| [D12](#d12-metadata-is-the-one-deliberately-open-object) | `additionalProperties: false` everywhere, but `metadata` is a free-form bag | open, and named as the only exception in the repo |
| [D13](#d13-where-is-the-redaction-boundary-enforced--the-collector-or-each-service) | is the redaction boundary enforced at the collector, or in each service? | at the collector, as one chokepoint; per-service allowlists are defence in depth |
| [D14](#d14-how-coarse-is-errortype) | how coarse is `error.type`, the fleet's error grouping key? | a bounded, fleet-wide class vocabulary — not a message, not a per-service exception class |
| [D15](#d15-the-span-name-form) | what shape is a span name? | dotted `<service>.<operation>[.<target>]` with a 15-character segment cap |
| [D16](#d16-which-variable-name-is-the-endpoint-contract) | which variable name is the endpoint contract? | `<SERVICE>_OTEL_ENDPOINT`; the collector is its default value, not a requirement |
| [D17](#d17-muses-endpoint-variable-and-the-two-names-core-now-has-for-it) | muse reads `MUSE_OTEL_EXPORTER_OTLP_ENDPOINT`; PLAN.md §7b says `MUSE_OTEL_ENDPOINT` | recorded, not papered over: muse is non-conforming to D16 and owes a one-line rename |
| [D18](#d18-which-classes-are-in-the-error-vocabulary) | D14 is ratified; which twelve classes are actually in the vocabulary? | twelve, grouped by who acts, with the test being whether a class's rate is worth an alert on its own |
| [D19](#d19-does-_other-belong-in-a-snake_case-vocabulary) | semconv's `_OTHER` fallback does not fit cafaye's snake_case shape — include it or omit it? | included, as the one documented exception; an alert on it is an alert that this service has not classified its own errors |
| [D20](#d20-kits-language-none-job-runs-the-gate-on-an-unpinned-interpreter) | kit's `language: none` job runs core's gate on an unpinned interpreter | accept the disclosure; the companion `gate` job carries the pin and asserts it |
| [D21](#d21-a-breaking-schema-change-has-no-re-vendor-fan-out-step) | a breaking schema change has no re-vendor fan-out step | record the gap; no packet should invent a mechanism that reaches into six repositories |
| [D22](#d22-should-cores-suite-assert-format-uri) | should core's suite assert `format: uri`, which no installed checker implements? | not built: no dependency added, and the gap is named in a test and here instead |
| [D23](#d23-do-the-openapi-and-cross-field-rules-become-a-schema) | do the OpenAPI conventions and the cross-field manifest rules become a JSON Schema? | not built: the harness makes sixteen rules executable, named and inventoried, and the schema question stays open |
| [D24](#d24-the-event-catalog-and-the-spec-version-are-documents-not-data) | the event catalog and the spec version are markdown and prose, not data | not built: the harness reads the document, which is right for now and is the second reader that argues against it |
| [D25](#d25-may-a-service-document-healthz-and-readyz) | may a service document `/healthz` and `/readyz` in its OpenAPI document? | not built: the harness reports what the document says, and the spec is silent |
| [D26](#d26-do-the-cafaye-fields-live-inside-the-sloth-document-or-in-a-cafaye-document-kit-converts) | do the cafaye fields live inside the Sloth document, or in a cafaye document kit converts? | inside, as landed; `additionalProperties: false` decides, and the fallback is a four-line transform in kit |
| [D27](#d27-the-burn-factors-come-from-a-30-day-budget-and-the-period-is-28-days) | the burn factors come from a 30-day budget and the period is 28 days | both as ruled, and the ~7% gap is asserted with its direction |
| [D28](#d28-may-cores-gate-take-the-sloth-dependency) | may core's gate take the `sloth` dependency? | not taken: the composition is checked in the harness, PromQL grammar is named as owed |
| [D29](#d29-which-tier-does-each-of-the-seven-services-get) | which tier does each of the seven services get? | not built and not decided: a tier with no SLO behind it is a number with nothing to page on |
<!-- The index above stops at D29, and D30-D33, D34 and D35 follow it in not
     being tabulated, rather than in being a fifth omission the next reader has
     to notice. Tabulating the recent ones and leaving the older ones out is the
     same mistake in a new place: the table stops being the index and becomes the
     list of decisions somebody happened to write down lately. -->
| [D34](#d34-how-does-the-fleet-record-a-type-core-has-not-finished-contracting-for) | how does the fleet record a type core has not finished contracting for? | a fourth constrained list, `pendingCoreContract`, and an assertion that rejects an entry core has already finished |
| [D35](#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit) | `identity.user.created`'s schema requires a `usr_` id and three fields its only publisher does not emit | **decided: rewrite it to reality, and release it as a PATCH** — a loosening, not a removed type, on a payload no consumer could satisfy — plus the three checks that would have caught it |
| [D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read) | what can core honestly check about a publisher it cannot read? | three in-core comparisons, each with its limit stated beside it, and the real check named as owed to the services rather than faked here |
| [D37](#d37-how-does-core-check-that-an-examples-ids-are-the-ids-its-producer-mints) | how does core check that an example's ids are the ids its producer mints? | **decided: a per-service ledger read out of each producer's own code at a named commit**, and every valid example required to match it — after twenty-one examples taught a prefixed ULID that core-24's denylist never looked at |
| [D38](#d38-does-a-declared-event-type-with-no-builder-stay-in-core-or-leave) | does a declared event type with no builder stay in core, or leave? | **decided: it stays, recorded as `declared-and-unimplemented` in the schema's own `description` and not only its `$comment`** — because deleting it makes `pendingCoreContract` assert that courier publishes it |
| [D39](#d39-does-a-payload-schema-follow-its-publisher-when-the-publisher-has-grown-the-feature-the-schema-predicted-it-would-not) | does a payload schema follow its publisher when the publisher has grown the feature the schema predicted it would not? | **decided as far as core's own claims: corrected now, in core's documents and in the schemas' `description`s. The schema rewrite is drafted and left to the manager** — it deletes four `required` properties shipped since v0.2 and partly reverses D10, and that is a decision about what `billing.subscription.*` means |
| [D45](#d45-should-a-chain-the-checker-cannot-follow-say-so-or-be-silent) | should a chain the checker cannot follow say so, or be silent? | **silent, and it is the price of not firing on a correct route** — recorded in `notEnforced` with its measurement, and the alternative is one warning that fires on 0 of the fleet's 42 | — `service.namespace` plus the three `telemetry.sdk.*` a merging SDK adds whether the caller asks, missed because the one publisher built schemaless was the only one that validated |

## D6: where do open decisions live?

Raised while reconciling the payload schemas. Affects
[`docs/event-naming.md`](docs/event-naming.md) and
[`tests/test_specs.py`](tests/test_specs.py)'s
`test_no_open_decision_callouts_remain_in_the_docs`.

**Choice:** open questions are numbered in this file at the repository root, and
the document that raises one cites the number inline. `docs/*.md` stays free of
undecided callouts, so the existing merge gate is untouched.

**Alternatives:**

1. Put `> DECISION NEEDED (Dn):` callouts in `docs/event-naming.md` as AGENTS.md
   literally says, and accept that the suite is red on the worker branch until
   the manager rules. Honest about the process, but it hands the manager a branch
   where `bin/prime` fails for a reason that is not a defect.
2. Put the callouts in `docs/` and relax
   `test_no_open_decision_callouts_remain_in_the_docs` to allow numbered ones.
   Rejected: it deletes the guarantee that a merged spec reads as decided, and a
   relaxation in a worker branch is how that guarantee is lost for good. Nothing
   else in this repository would notice.
3. Put the callouts in the doc and skip the test while they are open. Rejected for
   the same reason, and worse: a permanent skip is invisible in a diff.

**Recommendation:** option 1, as landed. It keeps the gate, keeps the decision
where a reader of the spec will find it, and makes the callout itself a citable
number — which is what AGENTS.md actually wants from a decision, and what the
`test_open_decisions_are_numbered_and_complete` assertions now check.

**Cost of flipping:** back to callouts in the doc is one commit — delete this
file, add the callouts, and decide what
`test_no_open_decision_callouts_remain_in_the_docs` should assert instead of
`not open_callouts`. Say what a *bad* state is for it (an unnumbered callout, a
duplicated number) and the gate can be rewritten to catch that without going
quiet.

## D7: courier keys a user by uuid and identity publishes a `usr_` id

Raised while writing courier's five payload schemas. Affects every
[`schemas/events/courier/`](schemas/events/courier) files and
[`schemas/events/identity/user/created.schema.json`](schemas/events/identity/user/created.schema.json).

**Choice:** `courier.*`'s `user_id` is `format: uuid`, because that is what
courier emits — `uuid` column, `priv/repo/migrations/…_create_notification_preferences.exs`
and `test/courier/deliver_test.exs:22`. `identity.user.created`'s `user_id` stays
`^usr_[0-9A-Z]{26}$`, because that is what identity emits. Both schemas name
this decision and point at it. Core does not pick a winner, and does not make
either schema accept the other's format.

> **THE PREMISE OF THE SECOND HALF IS FALSE, and [D35](#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
> is the correction.** "That is what identity emits" was never read out of
> identity; it was carried over from the id vocabulary core imagined before any
> publisher's code was looked at. At identity's `a20be0f` the publisher emits a
> bare uuid, and the eight schemas core-23 wrote beside this one all say so.
> **The two halves of this decision are therefore the same fact — uuid — and the
> mismatch it describes no longer exists between these two schemas.** What remains
> is a `usr_`-prefixed id in one file against a uuid in four, which is a
> contradiction inside core rather than a divergence between services. The
> recommendation below is superseded by D35's; the alternatives are kept, because
> the reasoning about accepting both formats — or accepting neither — still holds
> for whatever replaces the prefix.
>
> **RESOLVED, core-24, and the half above is kept as it was written because a
> reader needs to see that the claim was once made.** D35 is decided — **patch**,
> the reasoning in its `Choice:` paragraph — and
> [`schemas/events/identity/user/created.schema.json`](schemas/events/identity/user/created.schema.json)
> now says `format: uuid` with the citation the eight beside it use. So the
> "mismatch" this decision was raised to record was a contradiction inside core
> and is gone. **The vocabulary is now one thing: an id a service mints — a user,
> an account, a credential row — is a bare uuid, and every payload schema that
> carries one says `format: uuid`.** The two kinds of id that are *not* bare
> uuids are named in their own descriptions and are not counter-examples: an OIDC
> `client_id` is a client-supplied opaque string rather than a row id, and
> billing's `customer_id` and `subscription_id` are the payment processor's own,
> which D10 is about. What this decision leaves behind is the part that is still
> true and still useful: one id, one spelling, and a divergence between two
> services is a bug in one of them rather than a fact about the vocabulary. Three
> checks enforce it —
> [`docs/event-naming.md`](docs/event-naming.md#what-core-checks-against-the-publisher)
> says which, and [D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read)
> says what they cannot.

**Alternatives:**

1. One id vocabulary across the fleet. Either courier switches to `usr_…` or
   identity stops prefixing. Correct in the end, and not core's call — it is a
   change to identity's publisher and to courier's database column, in two
   repositories, and either way it is a breaking change to an emitted payload.
2. Accept both formats in both schemas (`pattern` with an alternation). Rejected:
   it converts a real, findable mismatch into a schema that agrees with everything
   and therefore detects nothing. A consumer joining these two payloads still
   has to try both spellings.
3. Say nothing and let each schema be locally true. Rejected: locally true and
   unjoinable is how a cross-service key mismatch becomes a 3am reconciliation
   bug. That is why this is written down rather than inferred.

**Recommendation:** call 1 as landed, and resolve the vocabulary in the identity
and courier repositories rather than here. Whichever way it goes, the change is a
**major** for the payload that moves (`usr_…` → uuid or the reverse), and the
alternative — a new event type, published alongside, with the old one deprecated
over six months — is available and cheaper to start than to finish.

**Cost of flipping:** in core, one line per schema (`format: uuid` ↔
`^usr_[0-9A-Z]{26}$`) plus the valid example in each. In the services, one column
type and one `Ecto`/Go cast in courier or identity, and a migration if the stored
ids are already prefixed. The expensive half is not in this repository.

## D8: what is the `subject` of `courier.notification.suppressed`?

Raised while writing the same five schemas. Affects
[`schemas/events/courier/notification/suppressed.schema.json`](schemas/events/courier/notification/suppressed.schema.json)
and the catalog row for the type in
[`docs/event-naming.md`](docs/event-naming.md).

**Choice:** the user id. The catalog calls the subject "the recipient", and both
readings of that are candidates — but the user id is the only one courier can
produce today from data it already holds, because it checks preferences by user
id before it ever looks at an address. The payload carries `user_id` and `email`,
so a consumer can join on whichever the manager picks, and switching costs a
payload-schema change and not a re-read of anyone's data.

**Alternatives:**

1. The address. Defensible: two reasons of the three (`address_suppressed`,
   `rate_limited`) are about the address, and the suppression list is keyed on it.
   Against it: an address is mutable, and `subject` is the per-entity ordering
   key, so a suppression list keyed on a value the recipient can change is a
   correlation key that moves under you.
2. courier grows a suppression-list row with its own id and the subject is that.
   Cleanest eventually, and it needs a table and a migration in courier that does
   not exist. Against it now: it invents an entity to have something to name.
3. The reserved literal `platform`. Rejected: `platform` means "no single entity
   yet", and a suppression is emphatically about one recipient. Using it would
   make every suppression correlate with every other one.

**Recommendation:** call 1 as landed, with option 2 as the destination. When
courier's suppression table lands, the subject moves to its row id, all five
courier payloads keep `user_id` and `email`, and the change is a **minor** for
the payload schema (an added required field is a minor) plus a breaking `subject`
change on every suppression event ever published — which, at the volume
suppressions happen, is a deprecation rather than an announcement.

**Cost of flipping:** to the address, change the catalog row's subject cell and
one sentence in the schema. Trivial now, and the reason it is cheap now is that
suppression volume is low; it is not cheap once real events exist, which is the
argument for deciding it before courier's receiver does. To option 2, it is a
suppression table in courier plus the subject change above, and the breaking part
is that every suppression event ever published reports a different entity.

## D9: `consumed` is not in the action vocabulary, and the payload has no account

Two questions in one, because both come from the same event and both are about
the same thing: whether `muse.tokens.consumed` is a thing the platform wants.
Affects the [action vocabulary](docs/event-naming.md#action-vocabulary), the
`muse` catalog row in [`docs/event-naming.md`](docs/event-naming.md), and
[`schemas/events/muse/tokens/consumed.schema.json`](schemas/events/muse/tokens/consumed.schema.json).

### The action

**Choice:** `consumed` joins the action vocabulary. The vocabulary is a list of
actions the platform has, not a list of verbs English has; `queued`,
`delivered`, `bounced` and `suppressed` are in it and none of them is a
"standard" eventing verb.

**Alternatives:**

1. Add `consumed`. The event is a real fact about a real spend, and the entity
   (`tokens`) names it as precisely as `plan` names a price.
2. Rename the type to `muse.usage.recorded`, which is already in the vocabulary
   and is what billing already means by usage. Against it: `recorded` is in the
   vocabulary for `billing.usage.recorded` with `subject: the account` and a
   period and a quantity. Reusing the same action for a different fact on a
   different subject is a naming collision with a real chance of being read as
   one. And muse's event is per-completion while billing's is per-period.
3. Leave the vocabulary alone and treat this as an exception. Rejected: the
   vocabulary's value is being exhaustive, and "except muse" is how it stops
   being one.

**Recommendation:** option 1. If the manager prefers option 2, the flip is one
word in `muse/src/muse/contracts.py` (`TOKENS_CONSUMED`), one in `cafaye.yml`,
one directory rename here and one catalog row — a **major**, because a published
type's name is never repurposed and the old one has to be deprecated for six
months, not renamed in place.

**Cost of flipping:** cheap in core, a deprecation cycle in every subscriber.

### The account

**Choice:** the payload stays at five fields with no account, and the envelope's
`subject` stays the reserved literal `platform`. muse's v1 auth stub does not
read a token, so there is no account to put in the payload — inventing one would
be a contract that lies in the way D7 does.

**Alternatives:**

1. Leave it. `platform` is honest: there is no single entity yet. The cost is
   real — a consumer cannot attribute the spend, so `billing` cannot invoice from
   this event as things stand.
2. Add `request_id`. The smallest field that makes aggregation possible: a
   consumer can still not say whose money it was, but it can tie cost to a
   request that guard or a caller already knows. Recommended as the *next* field,
   and a **minor** when it lands (a new required field is a minor).
3. Add `account_id`. What a consumer actually wants, and the one muse cannot
   produce today. It is muse's auth work, not core's, and a schema declaring it
   would be a schema requiring a field no publisher emits.

**Recommendation:** option 1 now, option 2 next, option 3 when muse reads a
token. Core's part is to not pretend otherwise, which is what the schema's
description says.

**Cost of flipping:** option 3 is a **minor** here and a large change in muse.

## D10: `billing.subscription.started`'s payload schema no longer describes cafaye ids

**Breaking.** Raised while writing billing's eight payload schemas. Affects
[`schemas/events/billing/subscription/started.schema.json`](schemas/events/billing/subscription/started.schema.json)
and the payload table in
[`docs/event-naming.md`](docs/event-naming.md).

**Choice:** the shipped v0.2 schema is rewritten. It required `subscription_id`
(`^sub_[0-9A-Z]{26}$`), `plan_id` (`^pln_[0-9A-Z]{26}$`) and `account_id`
(`^acc_[0-9A-Z]{26}$`) — a world in which billing holds cafaye-prefixed ids.
billing has no subscriptions table and cannot invent ids it does not have; its
webhook payloads carry the processor's `sub_…`, `cus_…` and `price_…`, and its
own primary keys are bare uuids. The schema now describes what billing emits,
with `processor` and `processor_event_id` on every payload so a consumer can tell
a fact billing knows from a fact billing was told.

**Alternatives:**

1. Rewrite it to reality, as landed. The packet's own rule — "a payload schema
   that guesses a field name the publisher never emits is worse than no schema:
   it is a contract that lies" — makes this the only option that leaves a
   *usable* schema behind. It is also a breaking change to a payload a consumer
   could have generated an SDK from in the four days since v0.2 shipped.
2. Leave the schema as it is and write the valid example with cafaye-prefixed
   ids. Rejected: that is inventing a payload. The example would validate, the
   suite would pass, and every real event billing publishes would fail the
   contract — the worst outcome in this repository, because it is invisible.
3. Loosen the patterns to accept both id vocabularies. Rejected for the same
   reason as **D7**: a schema that accepts everything detects nothing, and a
   consumer still has to try both spellings. It also hides the real decision
   instead of recording it.
4. Deprecate `billing.subscription.started` and ship a new type. Rejected as
   disproportionate: the *type* is not changing and its meaning has not changed.
   Only the payload's field vocabulary was wrong, and only for four days.

**Recommendation:** option 1, with billing told plainly that this is a spec major
and that the consumer obligation is a regenerated reader. Nothing has shipped
against v0.2's version of this schema, so the deprecation machinery exists for
events, not for a schema that was wrong on arrival. If the manager would rather
keep v0.2's text and treat the mismatch as billing's debt, that is option 2's
shape and it should be recorded in `docs/event-outbox.md`'s checklist as "validate
`data` against the payload schema where one exists and the publisher agrees with
it" — which is close to what billing's own contract test does today.

**Cost of flipping:** back to the v0.2 text is one file plus its two examples,
but it re-creates a schema no publisher satisfies. Forward, when billing grows a
subscriptions table, the shape moves again — cafaye `sub_…`/`pln_…`/`acc_…`
alongside or instead of the processor's ids — and that is a second breaking
change. The cheap way to avoid a third is for billing to decide the id question
before the table lands; that is billing's packet, not this one.

**Update, core-26: this decision was right and has gone stale, and those are
different corrections.** billing **did** grow a subscriptions table —
`db/migrate/20260930000007_create_subscriptions.rb`, `id: :uuid, default: ->
{ "gen_random_uuid()" }` — and `Subscriptions::Lifecycle#core_payload/1`
(`app/services/subscriptions/lifecycle.rb:353`) now writes `plan_id` and
`account_id` as **bare uuids** onto all three subscription payloads. So the
Choice above stands: the fields are still not cafaye-prefixed, `sub_…` is still
the processor's id and core must not forbid it, and `Identifiers::UUID` is still
case-insensitive on purpose. What is false now is the sentence the Choice rests
on — "billing has no subscriptions table and cannot invent ids it does not have"
— which was true of billing-03b and stopped being true when the table landed.
core's *own documents* repeated it, and a document in core stating the opposite
of what a service does is the defect; those sentences are corrected in core-26
rather than left to rot. The decision's own **cost of flipping** predicted this
exactly: "when billing grows a subscriptions table, the shape moves again … that
is a second breaking change." It moved. What that change *is* is
[D39](#d39-does-a-payload-schema-follow-its-publisher-when-the-publisher-has-grown-the-feature-the-schema-predicted-it-would-not),
and this paragraph is not rewritten because a decision record is a record of a
decision: editing the words a decision was made with would erase the fact that it
was sound on the day and that the world moved afterwards.

## D11: `billing.payment.succeeded` has two payload shapes

Raised while writing billing's eight payload schemas. Affects
[`schemas/events/billing/payment/succeeded.schema.json`](schemas/events/billing/payment/succeeded.schema.json)
and the `billing` catalog row in
[`docs/event-naming.md`](docs/event-naming.md).

**Choice:** the schema declares one `oneOf` over both shapes — invoice-backed
(`invoice_id` + `subscription_id`) and Checkout-backed (`checkout_session_id`) —
so exactly one is present and a consumer never has to guess. Both shapes are
covered by a valid example
(`succeeded.data.json` and `succeeded.checkout.data.json`), checked by
`test_payload_schema_variant_examples_validate` so neither is assumed.

**Alternatives:**

1. `oneOf`, as landed. The honest encoding, and it makes the distinction a
   machine-checked fact instead of a sentence in a description.
2. A new `billing.checkout.completed` type. This is what billing's own
   `cafaye.yml` asks for. It is the cleanest end state — one type, one shape,
   one normaliser — and it costs a catalog row here, one line in
   `Webhooks::StripeEvents.event_type_for`, and a decision about double
   counting: a Checkout session and an invoice for the same charge would both
   fire, so one of them has to be suppressed or a consumer counting settled
   payments counts every signup twice. billing's own DECISION NEEDED flags this
   and this packet cannot resolve it, because suppressing an invoice event is a
   revenue-path decision.
3. One flat schema with every field optional and no discriminator. Rejected:
   `invoice_id` is `null` for a one-off invoice, so "present" and "not null" are
   different questions and a consumer has to get both right. A schema that
   validates both shapes while being unable to tell them apart is the same lie
   as D7's alternative 2.

**Recommendation:** option 1 now, option 2 when billing is ready to make the
double-counting decision. The `oneOf` does not block option 2 — deleting one
branch and its fields is a patch once the type split exists, because no
subscriber has to migrate off a type that never changed.

**Cost of flipping:** option 2 is a new catalog row, a publisher change and a
revenue-path decision. Option 1 → 3 is free and worse; it is only listed because
it is what this schema would collapse into if somebody "simplified" the `oneOf`.

## D12: `metadata` is the one deliberately open object

Raised while writing
[`schemas/events/billing/customer/created.schema.json`](schemas/events/billing/customer/created.schema.json).
Affects that schema, and
[`tests/test_specs.py`](tests/test_specs.py)'s closing rule.

**Choice:** `billing.customer.created`'s `metadata` is `{"type": "object"}` with
no `additionalProperties` constraint, and its description says so in bold. Every
other object in every schema in this repository is closed.

**Alternatives:**

1. Leave it open, as landed. `metadata` is a `jsonb` bag the caller fills; the
   publisher normalises a null to `{}` and writes nothing else. Closing it would
   make the field permanently `{}`.
2. Close it. Rejected: it would be a schema requiring a field that can hold
   nothing, which is worse than an open one because it looks enforced.
3. Drop `metadata` from the schema. Rejected: the publisher emits it on every
   `billing.customer.created`, so a closed schema would reject a real payload.

**Recommendation:** option 1, and the next free-form field gets the same
treatment with the same sentence. The rule AGENTS.md states — close every level,
so an undeclared key is an error rather than a silent no-op — is right about
*known* fields and wrong about a bag whose contents are by definition unknown.
An open field that is named as open is a decision; an open field that is not
named is a hole.

**Cost of flipping:** closing it is one line, and it is a breaking change the
moment any caller puts a key in it — which is why it should not be done after
the first real customer rather than before.
## D13: where is the redaction boundary enforced — the collector, or each service?

Raised while writing
[`schemas/telemetry/redaction.schema.json`](schemas/telemetry/redaction.schema.json)
and [`docs/observability.md`](docs/observability.md). Affects the `enforcedAt`
enum, kit's collector config, and every service's SDK setup.

**Choice:** **the collector is the enforcing chokepoint**; each service's own
SDK allowlist is defence in depth, never the only line. `enforcedAt` is an enum
in the schema with `collector` as the only value a cafaye policy may carry, so
"enforce it somewhere" is not a state a config can express.

**Alternatives:**

1. The collector, as landed. One chokepoint in one process, auditable in one
   place, and a service cannot bypass it by forgetting to configure something.
2. **The service SDK.** Each service's allowlist is the enforcement point, as it
   already is in muse. Rejected as the *only* line: it is six independent
   implementations of a security control, and the failure mode of a control
   implemented six times is that one of the six is wrong and nobody finds out
   until a customer's prompt is in a log store. It also fails the moment a
   service ships an SDK that does not honour the allowlist — which is exactly
   what a self-hoster pointing `*_OTEL_ENDPOINT` at a vendor backend brings, since
   that backend's SDK knows nothing about our policy. **This is the argument that
   decided it:** the escape hatch and the chokepoint are in direct tension, and
   the chokepoint only holds if the escape hatch does not carry the redaction off
   with it.
3. **Both, with equal weight** — the collector re-checks and the service
   pre-checks, and the doc says the boundary is "the intersection". Rejected: it
   sounds stronger and is weaker to reason about. Two controls that must both pass
   have no single answer to "is this leak blocked?", and the debugging story for a
   partial failure is worse than either control alone.
4. **Neither; scrub at the exporter.** Rejected: a scrubber is downstream of the
   leak. It cannot tell a prompt from a stack trace that happens to contain one,
   and muse's own `redaction.py` argues against filters with a bypass — the same
   argument, applied to telemetry.

**Recommendation:** option 1, with the honest caveat recorded in the doc: a
collector-side policy cannot protect data that never leaves the SDK, which is
why the per-service allowlist is not redundant. They are a first line and a last
line, not one line and a spare.

**Cost of flipping:** in core, one enum value and one line in the doc. In **kit**,
it inverts the collector's role from filter to pass-through and every allowlist
moves into six per-language templates. In the services, each one has to be
trusted with the whole boundary. The expensive half is not in this repository —
the same shape as D7 and D10, and the same warning: the flip is cheap in core
and expensive everywhere else, so it is worth deciding before kit builds the
collector rather than after.

## D14: how coarse is `error.type`?

Raised while writing
[`schemas/telemetry/metrics.schema.json`](schemas/telemetry/metrics.schema.json)
and [`docs/observability.md`](docs/observability.md). Affects the `error.type`
definition on all three signals, and the answer to the user's question about one
place to see all errors for the whole system (PLAN.md §7b).

**Choice:** a **low-cardinality class in a bounded, fleet-wide vocabulary** —
snake_case, at most 64 characters, the same shape on every signal. Not a message,
not a stack trace, not a per-service exception class name.

**Alternatives:**

1. The bounded fleet vocabulary, as landed. `provider_auth`,
   `dependency_unavailable`, `rate_limited`, `timeout`, `circuit_open`.
2. **The language's own exception class name** — what muse emits today
   (`error.type = "ProviderAuthError"`). It is free: no mapping table, no
   decisions, and it is what the OTel convention literally suggests ("the
   fully-qualified class name"). Rejected for two reasons, one soft and one
   hard. Soft: it is only *low-cardinality* within one language — add a class and
   you have a new series. Hard: `ProviderAuthError` in Python, `ErrProviderAuth`
   in Go and `ProviderAuthError` in Elixir are one failure in three taxonomies,
   so "one place to see all errors for the whole system" becomes six places that
   need a mapping table to join. That is the user's actual question, and this is
   the only option that answers it.
3. **The HTTP status code.** Free, bounded, already ubiquitous. Rejected: it
   conflates a 503 from a dead provider with a 503 from a dead database, which
   are different incidents with different responders, and it is meaningless for
   an event consumer or a background job that has no status code at all.
4. **A free string.** Rejected: on the metrics side it is the same cardinality
   bomb as `tenant_id`, and on the traces side it is the wall of ungrouped text
   the user asked whether we could avoid.

**Recommendation:** option 1, and deliberately a **narrow** vocabulary — around a
dozen classes covering transport, dependency, policy and internal failures. A
narrow vocabulary means a class is worth alerting on; a broad one means every
value gets its own alert and the grouping key stops grouping.

**Cost of flipping:** in core, one definition per signal and the doc table. In
**muse**, one line: the `error.type` it sets on `muse.provider.call` is
`ProviderAuthError` today, and `tests/test_trace_propagation.py` asserts that
value — so flipping is a code change *and* a test change in another repository.
In the other five, nothing yet, which is the cheapest possible time to decide it.
The real cost is a mapping table somebody has to maintain, and that cost is only
worth paying once; paying it after six services each have their own class names
is what makes it permanent.

**Status: ratified by the manager, and implemented as a closed `enum` rather than
a pattern.** D14 promised "a bounded vocabulary"; core-04 delivered a `pattern`
and a 64-character cap, which bound the *shape* of the value and not the set of
values, so `user_42_email_invalid` validated cleanly on all three signals. The
two open questions D14's own implementation raised are **D18** (which classes)
and **D19** (whether `_OTHER` is in a snake_case vocabulary).

## D15: the span-name form

Raised while writing
[`schemas/telemetry/span-naming.schema.json`](schemas/telemetry/span-naming.schema.json).
Affects every span name in the fleet and kit's six OTel templates.

**Choice:** `<service>.<operation>[.<target>]` — dotted, lowercase, the same
*shape* as the event grammar's `<service>.<entity>.<action>`, with a mandatory
service prefix and a **fifteen-character segment cap**.

**Alternatives:**

1. The dotted cafaye form, as landed. One shape to learn for both events and
   spans; a span name always says which service produced it.
2. **The OTel HTTP convention** — `HTTP GET`, or `{method} {route}`, e.g.
   `GET /v1/users/{id}`. This is what a Grafana user expects to see and what
   every off-the-shelf OTel tool already understands. Rejected: it puts the route
   in the *name*, and a route with an id in it is a cardinality bomb with a `GET`
   attached — it is the first entry in the rejected list. It also has no room for
   a non-HTTP span, and some of the fleet's most interesting work (an outbox
   publish, a breaker decision) is not HTTP.
3. **The OpenInference dotted style** (`openinference.chain.invoke`). Same shape
   as option 1 but names a vendor, and it puts a third party's vocabulary in a
   spec core owns.
4. **A function name** — `get_user`. Rejected in one line: it is what a fleet
   produces when nobody has said, and it is unstable under refactoring, so every
   dashboard breaks when someone renames a function.

**Recommendation:** option 1, and the segment cap is the part worth defending in
review. It is what refuses an interpolated id *without core growing a cafaye-id
pattern to recognise one* — the grammar says nothing about ids, it says no
segment is longer than fifteen characters, and
`usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` therefore cannot be a span name. A pattern
listing our id prefixes would need editing every time identity mints a new
prefix, and would be bypassed by an id format core had not seen.

**Cost of flipping:** every span name in the fleet, every dashboard and alert
built on one, and kit's six templates. The cheap thing about this decision is
that it is cheap *now* — there is almost nothing to rename, because the fleet has
barely started — and that is the whole argument for making it before the first
service is instrumented rather than after the sixth.

## D16: which variable name is the endpoint contract?

Raised while reading muse's `Settings.from_env` against PLAN.md §7b. Affects
[`schemas/telemetry/otel-endpoint.schema.json`](schemas/telemetry/otel-endpoint.schema.json),
`fleet.yml`'s `endpointVariable`, and every service's configuration.

**Choice:** `<SERVICE>_OTEL_ENDPOINT` — uppercase, per-service, derived from the
service name. The shipped collector is that variable's *default value*, and
`required` is a `const: false`.

**Alternatives:**

1. `<SERVICE>_OTEL_ENDPOINT`, as landed. One name to know per service; a
   self-hoster can point one service at their existing backend and leave the rest
   on the collector, which is the whole escape hatch.
2. **The OTel standard names** — `OTEL_EXPORTER_OTLP_ENDPOINT` and
   `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, read by every OTel SDK in every
   language for free. **This is what muse actually implements today** (see D17).
   Rejected as the *only* name for one reason: it is global, so pointing one
   service at Datadog and the rest at the collector means two process
   environments rather than one, and a self-hoster's compose file grows a
   per-service override block for every service that differs.
3. **Both**, service-specific taking precedence. The most compatible answer, and
   the one with the most to explain. Rejected because it makes the precedence
   order itself part of the contract, and a contract with a precedence order is a
   contract with a bug report.

**Recommendation:** option 1 as landed, and the drift recorded in **D17** rather
than papered over: muse reads `MUSE_OTEL_EXPORTER_OTLP_ENDPOINT`, PLAN.md §7b
says `MUSE_OTEL_ENDPOINT`, and this spec says `<SERVICE>_OTEL_ENDPOINT`. Three
spellings of one variable in three places is precisely the cross-repo drift
`fleet.yml` exists to catch, and the honest move is to record it rather than
write a spec that quietly disagrees with the one service that ships.

**Cost of flipping:** one constant per service and one line in its settings test.
Cheap in core, cheap everywhere — which is why it should be settled now rather
than by whichever service is instrumented next, since each one will otherwise
pick the spelling it finds in its own neighbourhood.

## D17: muse's endpoint variable, and the two names core now has for it

Raised while transcribing muse into
[`fleet.yml`](fleet.yml) against
[`schemas/telemetry/otel-endpoint.schema.json`](schemas/telemetry/otel-endpoint.schema.json).
Affects muse's `Settings.from_env`, D16, and PLAN.md §7b.

**The fact first, because it is the reason this is open.**
`muse/src/muse/main.py` reads `MUSE_OTEL_EXPORTER_OTLP_ENDPOINT` — the
OpenTelemetry standard spelling — which is also what
`muse/tests/test_resilience_config.py::test_the_tracing_endpoint_is_read_from_the_standard_variable`
asserts, while its neighbour `muse/tests/test_telemetry.py:269` calls it
`MUSE_OTEL_ENDPOINT` in prose. PLAN.md §7b states that "muse already honours
`MUSE_OTEL_ENDPOINT`". **It does not.** Three places, three spellings, and the
code agrees with neither document.

**Choice:** core keeps `<SERVICE>_OTEL_ENDPOINT` (D16), `fleet.yml` records
`MUSE_OTEL_ENDPOINT` for muse **with a note saying which variable muse actually
reads**, and muse is marked non-conforming rather than quietly assumed
conforming. This packet does not change muse — it is a read-only reference and
no service is instrumented here.

**Alternatives:**

1. Record the divergence and rename muse in muse's next packet, as landed.
2. **Flip D16 and adopt the OTel standard names.** muse is then already
   conforming, PLAN.md §7b turns out to have been right about the name, and core
   stops maintaining a cafaye-specific spelling at all. Rejected *here* only
   because it is D16's call and D16 argues for the per-service name on
   self-hoster ergonomics — but it is a live option, and it is the one that makes
   this divergence disappear rather than get paid off.
3. Accept both spellings, cafaye first, as an alias. Rejected: two names for one
   variable is a precedence order, and a precedence order is a bug report (D16).
4. Say nothing and let each new service pick the spelling it finds next door.
   Rejected: that is how six services end up with six names for the one variable
   a self-hoster is told to set, which is the exact failure `fleet.yml` exists to
   catch.

**Recommendation:** option 1, and rule on D16 with option 2 in view — the two
decisions are the same decision seen from two ends. If the manager prefers the
standard names, this entry closes as "not a drift" and the only work is
`fleet.yml`.

**Cost of flipping:** one string in `muse/src/muse/main.py` and one line in
`muse/tests/test_resilience_config.py`, plus this entry and `fleet.yml`'s note.
Cheap in core and cheap in muse, which is exactly why it should be settled now
rather than after three more services have copied the OTel spelling out of
muse's code.

## D18: which classes are in the error vocabulary?

Raised while implementing D14 as an `enum` in
[`schemas/telemetry/traces.schema.json`](schemas/telemetry/traces.schema.json),
[`metrics.schema.json`](schemas/telemetry/metrics.schema.json) and
[`logs.schema.json`](schemas/telemetry/logs.schema.json). Affects the same
`error.type` definition on all three signals, the table in
[`docs/observability.md`](docs/observability.md#errortype), and the class muse
maps onto.

**Choice:** twelve classes plus `_OTHER`, grouped by **who acts** rather than by
which component failed:

- *the caller* — `invalid_request`, `policy_denied`
- *a third party* — `provider_auth`, `provider_rejected`, `rate_limited`
- *the wire* — `timeout`, `connection_failed`, `circuit_open`
- *a dependency* — `dependency_unavailable`, `conflict`
- *nobody, on purpose* — `cancelled`
- *us* — `internal_error`

The test for whether a class earns its place is D14's: **is this class's rate
worth an alert on its own?** Two consequences of that test are worth naming,
because they are the two places a vocabulary usually grows without deciding to:

- **`timeout` is one class, not one per dependency.** What timed out is the
  span's name and its attributes. A class per target — `provider_timeout`,
  `database_timeout`, `vault_timeout` — is how a twelve-value list becomes a
  hundred and the grouping key stops grouping.
- **`circuit_open` is a class even though nothing failed.** It records our own
  breaker refusing to call, which is otherwise invisible, and it separates "the
  vendor is down" from "we stopped trying".

**Alternatives:**

1. The twelve as landed, grouped by responder.
2. **A class per dependency.** `provider_timeout`, `database_timeout`,
   `vault_timeout`. Rejected: it is the vocabulary version of the span-name
   mistake D15 refuses — the thing that went wrong is already on the span, and
   repeating it in the class is one more dimension multiplying against every
   other one for no new question answered. It also makes the class list a list of
   cafaye's own services, so every new service edits core.
3. **A wider list, one class per exception shape.** `configuration_error`,
   `serialization_error`, `data_invariant`, `deserialization_error`. Rejected on
   D14's own criterion: each is a few occurrences a month, each would get its own
   alert, and a class you would page on at a rate of two a month is a class you
   would stop reading. They collapse into `internal_error`, which must trend to
   zero anyway.
4. **Per-service vocabularies**, each service's own list. Rejected: it is D14's
   rejected option 2 with a different spelling. It is also unenforceable by this
   repository, which is the problem: a class list per service is a list nobody
   compares.

**Recommendation:** option 1, and the *test* rather than the list is the part
worth defending in review — "is a rate worth an alert on its own?" is answerable
in a review, "does this class feel right?" is not. The bound is asserted
(`MIN_ERROR_CLASSES`/`MAX_ERROR_CLASSES`, 10–16) because "around a dozen, do not
pad it" is a judgement nobody makes twice the same way under deadline, and an
unbounded list is a list that grows one class per incident.

**Cost of flipping:** one `enum` per signal (three copies, deliberately
duplicated so a service's SDK setup can load one file alone), the doc table, and
the muse mapping. Adding a class is the cheap direction and is deliberately
cheap; **removing** one is not, because a class that has been emitted is data
someone has already grouped by, so a rename is a broken dashboard and a silent
gap in historical comparison. That asymmetry is the argument for settling the
list before kit builds the collector rather than after the first alert fires.

## D19: does `_OTHER` belong in a snake_case vocabulary?

Raised by the same work as **D18**, from a tension in the packet: include the
OTel well-known fallback "if it fits the shape". It does not — `_OTHER` is
upper-case with a leading underscore and cafaye's shape is
`^[a-z][a-z0-9]*(_[a-z0-9]+)*$`. Affects the `pattern` in
[`schemas/telemetry/traces.schema.json`](schemas/telemetry/traces.schema.json)
and its two copies, and whether the vocabulary has an escape hatch at all.

**Choice: include it, as the one documented exception to the shape.** The shape
becomes `^([a-z][a-z0-9]*(_[a-z0-9]+)*|_OTHER)$`, so every class but the fallback
is snake_case and the fallback is spelled the way the ecosystem spells it.

**Alternatives:**

1. Include it, as landed. The argument is about what a closed enum does under
   pressure: **a closed set with no escape hatch gets widened.** The first real
   failure that does not fit — a database driver error, a language-specific
   runtime failure — arrives during an incident, and the cheapest available
   action is to add a class rather than to file a spec change. A widened enum is
   how `_OTHER` becomes a permanent value nobody reads, because by then it is
   easier to keep using it than to find the class that was added for the case in
   front of you. Carrying the fallback is how instrumentation is never forced to
   invent a class. And the value of the alert does not depend on being rare: an
   alert on `_OTHER` is an alert that **this service has not classified its own
   errors**, which is actionable, owned, and specific.
2. **Omit it.** The vocabulary stays uniformly snake_case, and a service with a
   genuinely unclassifiable failure has two bad options: drop the class, which
   makes a status-error span that fails the obligation, or add a class, which is
   the widening from option 1 with an extra step. The tidiness of the shape is
   not worth either.
3. **Rename it** — `other`, or `unclassified`. Rejected: it forks a Stable OTel
   value. A backend someone at cafaye has never heard of would show `other` and
   `_OTHER` as two different classes for the same event, which is precisely the
   six-taxonomies failure D14 rejects.
4. **A per-service escape hatch** — a cafaye-specific value outside the enum,
   permitted by a `not`-guarded escape. Rejected: it is a free string with a
   friendly name, and it is the hole this packet exists to close.

**Recommendation:** option 1. The shape compromise is real and the test asserts
it explicitly — `_OTHER` is the only member allowed to break the shape, and the
vocabulary has no other member that does — so a later commit cannot quietly add a
second exception without a test failing.

**Cost of flipping:** in core, the pattern in three files, the doc, and the
`test_the_error_class_vocabulary_is_narrow_and_closed` exemption. Elsewhere it
costs a **no-op path that is not a no-op**: every service that would have used
`_OTHER` has to pick a class at the moment it has none, which is the widening
happening per-service and untracked. That is the expensive half, and it is why
the cheap half should be decided now.

## D20: kit's `language: none` job runs the gate on an unpinned interpreter

Raised by **core-06**, which adopted kit's reusable workflow and found that
core fits none of kit's eight `language` values cleanly. `none` is the documented
option for a repository with no service manifest, and it is the only one whose
job can be green here — but its job is four steps long and **installs no
interpreter**: it is `actions/checkout`, an existence check for
`tests/validate.sh`, and `bash tests/validate.sh`. So the `kit` job in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs core's 92 tests on
whatever Python `ubuntu-latest` happens to ship, which is a floating build by
the letter of the rule that says a suite that passes today must not depend on
which image was cached.

The seven language jobs cannot take this repository: each opens by reading a
manifest and installing from it, and `uv sync --frozen` exits 2 with "No
pyproject.toml found" in a repository that has never had one and should not. The
gap is not that kit's jobs are wrong; it is that kit models *service* repositories
and (via `none`) *kit itself*, and core is a third shape — a repository with a
real suite and a real pin, and no service at all.

**Choice: accept the disclosure, and let `gate` carry the pin.** The `kit` job
proves two things the companion job cannot — that the `uses:` line resolves, and
that the gate bootstraps from nothing on a clean runner — and it says in its own
name that it is not the pinned claim. The `gate` job reads the pin from
`mise.toml` at run time and **asserts** the interpreter that arrived against it.
The floating interpreter is disclosed in the README, in the CHANGELOG and in the
workflow file rather than left to be inferred from a green tick.

**Alternatives:**

1. Accept the disclosure, as landed. Cheapest, and honest because the claim is
   named rather than assumed. The cost is that two jobs run the same 92 tests on
   two different interpreters, which is the kind of redundancy that invites
   "delete the redundant one" from someone who has not read why it is there.
2. **Have kit read `inputs.versions` in the `none` job.** A two-line change to
   kit — `actions/setup-python` with the pin the input already carries — and it
   makes `none` correct for every configuration-only repository, not just this
   one. It also removes the duplicate run. This is the option core would
   recommend, and it is a kit packet, not a core one.
3. **A ninth `language` value** — `spec`, for a repository with a suite, a pin
   and no manifest. Honest about the third shape, and the most work: kit's gate
   requires a Dockerfile, a `bin/prime` and a `[tools]` pin per language, and core
   ships no Dockerfile because it builds nothing.
4. **Make the gate refuse to run on an unpinned interpreter.** Rejected: the
   `kit` job would go red on every runner whose default Python is not 3.14,
   which means the adoption PR is never green and the option cannot be chosen
   without also choosing 2 or 3.

**Recommendation:** option 1 now, and open option 2 as a kit packet. Option 1 is
the only choice that can be made without blocking on another repository, and it
is fully reversible: if kit adds the `setup-python` step, core deletes nothing —
the assertion in `gate` is what makes the pin load-bearing, and it stays either
way.

**Cost of flipping:** near zero in core, and that is the point of taking it in
this order. Moving to option 2 is a kit PR plus deleting the disclosure text in
three places. Moving to option 3 means kit grows a language it must then hold a
Dockerfile and a primer for, and core would have to ship an image for a
repository that builds nothing — which is the one thing core's AGENTS.md rules
out twice.

## D21: a breaking schema change has no re-vendor fan-out step

Raised by the same packet, from the question core-06 was asked directly: core is
the repository whose schemas other services **vendor**, so if a schema changes,
services have to re-vendor. Nothing in core-06 changes a schema, so nothing
triggers it — but the honest answer to "should this packet have a fan-out step?"
is that **it should not, and no packet should invent one quietly**. Today a
breaking change lands in the CHANGELOG's breaking section and relies on each
service noticing on its own schedule.

What exists: `CHANGELOG.md` records the break under a heading that says who it
breaks and why, and `muse` has a core-parity CI job that checks its vendored copy
against a pinned `CORE_REF` — which catches drift on muse's push, not on core's.
So the detection is per-service, the trigger is per-service, and nothing tells a
service owner that a fan-out is owed. That is a real gap with no owner.

**Choice: write the gap down and do not build the mechanism here.** A fan-out
step in core would have to reach into six repositories, choose a moment to push
to each, and decide what a service does when its vendored copy no longer matches
— and every one of those is a decision this repository does not own. So this is
recorded as an open question with its alternatives argued, and the cheap first
step (a spec'd `coreSpecRef` field, or a changelog machine-readable block) is
left for the packet that is actually about releases.

The nearest thing core already owns is
[`schemas/fleet.schema.json`](schemas/fleet.schema.json), which is what makes
`fleet.yml`'s per-service `sourceCommit` checkable: core already records *what
revision of a service a fact was read at*, asserted to be a full 40-character
SHA by `test_fleet_records_a_source_commit_per_service`. That is provenance in
exactly the wrong direction — it says what core knows about each service — and
what is missing is the record of what each service knows about core.

**Alternatives:**

1. Record the gap, as landed. Nothing is invented; the question is visible and
   numbered, which is the state AGENTS.md asks for. The cost is that the gap
   stays a gap until someone is given the time to close it.
2. **A machine-readable breaking-change block in `CHANGELOG.md`** — a fenced
   block listing the changed `$id`s and the new spec version. Cheap, lives in
   core, and a service can consume it without core pushing to anything. It is
   still a fan-*out* with no fan-*in*: it tells a service what changed, not that
   it must act, so each service still needs a job that checks.
3. **core pushes the re-vendor.** Rejected outright: core would gain write
   access to six repositories, and a spec repository that can change a service's
   working tree is a runtime with opinions, which AGENTS.md rules out in the same
   sentence it uses for the collector.
4. **Nothing, indefinitely.** Rejected: it is the status quo, and "no decision"
   is the one outcome AGENTS.md calls the only real failure.

**Recommendation:** option 1, with option 2 as the first step of whichever packet
closes it. Option 2 is small and does not require cross-repository write access,
so it is reachable without the decision this one is waiting on.

**Cost of flipping:** option 2 is additive — a block in a document, and a schema
if it becomes one, with its own test. Nothing about core-06's CI work changes
either way, which is why it is safe to record rather than build.

## D22: should core's suite assert `format: uri`, which no installed checker implements?

Raised by **core-07**, by accident and then on purpose. The contract-test harness
evaluates the keywords core's schemas use with the standard library alone, and
`test_the_harness_checks_the_format_vocabulary_core_uses` asks which `format`
values the harness decides. The answer is `date`, `date-time`, `email`, `uri` and
`uuid` — and `jsonschema`, in core's own venv, registers checkers for all of
those **except** `uri`. So
[`schemas/telemetry/otel-endpoint.schema.json`](schemas/telemetry/otel-endpoint.schema.json)'s
`format: uri` on the collector's default endpoint is a constraint that
`bin/prime` does not assert, and a document that is not a URI at all passes it
today.

This is not new and it is not the harness's fault.
[`tests/requirements.txt`](tests/requirements.txt) already carries a note saying
exactly this about `date-time` — "jsonschema only checks the date-time format
when one of these is present; without it an RFC3339 assertion in the suite would
silently pass everything" — and pins `rfc3339-validator` because of it. The same
argument applies to `uri` and nobody made it. The blast radius is small: the
field sits beside `pattern: "^https?://"`, so a value that is not a URL is
usually rejected anyway. The point is not the field; it is that a rule nobody
asserts is a comment, and core's own rule says a rule not in `schemas/` is not a
cafaye rule — this one is in `schemas/` and is still not a rule.

**Choice: do not add a dependency, and make the gap a named, tested fact
instead.** `jsonschema` needs `rfc3987-validator` to assert `uri`, and
`tests/requirements.txt` is deliberately minimal — "no runtime libraries, no
services, no dependencies beyond `tests/requirements.txt`" is AGENTS.md's line
and a fifth package for one keyword is not worth arguing about. So the harness
*does* check `uri` (it costs five lines and the standard library has what it
needs), and the divergence is stated in
[`docs/contract-harness.md`](docs/contract-harness.md) and asserted here. The
harness is the stricter of the two, deliberately: it is the thing a service runs
in CI, and a service should not get a weaker check than the spec repository
gives itself.

**Alternatives:**

1. Leave it, named and tested, as landed. No dependency, and the vacuity is
   visible in two documents and in this decision rather than invisible in a
   schema. The cost is that `bin/prime` is still weaker than it reads.
2. **Add `rfc3987-validator` to `tests/requirements.txt`.** One line, and
   `format: uri` starts being asserted everywhere — in `bin/prime`, in the
   harness's equivalence test, in every service that vendors the schema. It is
   the correct fix and the only argument against it is the dependency count,
   which is a policy rather than a fact.
3. **Drop `format: uri` from the schema** and rely on the `pattern` beside it.
   The smallest change and it loses nothing today — but it deletes a constraint
   rather than enforcing one, which is the wrong direction for a repository whose
   rule is that a constraint is a rule.
4. **Replace `format: uri` with a pattern** covering the shapes a collector
   endpoint can take. No dependency, fully asserted, and a worse rule: a pattern
   for "a URL" is a worse statement of "a URL" than `format: uri` is.

**Recommendation:** option 2, in a packet about dependencies, and option 1 until
then. Option 1 is fully reversible in one line and loses nothing while it stands,
which is exactly the property that makes it safe to leave open. If the manager
decides option 2, the only change here is removing the "deliberately stricter"
sentence from [`docs/contract-harness.md`](docs/contract-harness.md) — the harness
keeps checking `uri` either way.

**Cost of flipping:** one line in
[`tests/requirements.txt`](tests/requirements.txt), and one sentence in
[`docs/contract-harness.md`](docs/contract-harness.md). Nothing in
[`harness/cafaye_contract.py`](harness/cafaye_contract.py) changes, and nothing
in a service does.

## D23: do the OpenAPI conventions and the cross-field manifest rules become a JSON Schema?

Raised by **core-07** from the thing its own rule inventory turned up. core's one
rule is that a rule not in `schemas/` is not a cafaye rule. The harness enforces
seventeen rules, and **exactly one of them** is a JSON Schema constraint. The
other sixteen are in code — five cross-field manifest rules that
[`docs/manifest-conventions.md`](docs/manifest-conventions.md) lists under "Rules
the schema cannot state", five OpenAPI conventions that
[`docs/openapi-conventions.md`](docs/openapi-conventions.md) says in its own
words are "review-enforced, like every other convention here" until a future
`caf contract lint` lands, and six that are facts about a filesystem or a pin
rather than about a document at all.

Some of the sixteen can never be a schema. A path being under a `/vN` prefix is
a property of an OpenAPI document, and there is no JSON Schema for "an OpenAPI
document" that is worth writing — one could be written, and it would be a
validator for a specification core does not own. A digest is not a document. But
the *cross-field manifest* rules are a different matter: they compare two
properties of one instance, JSON Schema cannot do that directly, and it is a real
question whether `dependentSchemas` plus `$data` (a draft-07 extension) or a
generated schema per rule is the right answer, or whether "documented, named,
inventoried and tested in one place" is the right answer and the schema would be
a worse place.

**Choice: do not decide it here, and do the step that is not the decision.** The
harness makes each of the sixteen rules **executable, named, inventoried and
tested** — `harness/rules.json` says which document each one lives in,
`test_the_rule_inventory_says_where_every_rule_lives` checks that the document
and the heading exist, and `harness/tests/self_test.sh` proves each of the
seventeen can go red. A manager can now see the sixteen as a list and decide,
which was not possible before core-07: the rules were in six documents and in
`caf`'s Go package, in two languages, and `caf` had implemented three of the six
and said so in a comment. **Turning a rule executable is a strictly smaller step
than turning it into a schema, and it is the one that unblocks the decision
rather than pre-empting it.**

**Alternatives:**

1. Leave the rules in code, inventoried and tested, as landed. Cheapest, and it
   is already the step that was missing. The cost is that a rule's home is a
   Python function, and "in `schemas/`" stays true for one rule out of seventeen.
2. **A JSON Schema for OpenAPI documents** — `schemas/openapi.schema.json`, with
   `pathPattern`, `info.version` and the prefix rules as constraints over the
   parsed document. Everything the harness checks about a document would move into
   `schemas/` and the harness would carry one rule instead of five. The cost is
   a schema for a specification core does not own, which will need updating when
   the OAS moves, and `openapi.paths-are-versioned` is awkward to express over
   *path keys* rather than values.
3. **Generate per-rule schemas** from a table, for the cross-field manifest rules
   only. The rules become data. The cost is a code generator in a repository whose
   AGENTS.md says a change needing a runtime belongs in `caf`, and a manifest
   validator that is three layers deep before it says "not this service's name".
4. **`dependentSchemas` per rule**, with each rule as a subschema guarded by the
   presence of the fields it reads. No generator, and it lands inside
   `schemas/`. The cost is that five rules that read "the manifest as a whole"
   become five conditional subschemas, and the schema stops being readable as a
   description of a manifest.

**Recommendation:** option 1 now, and option 2 as the packet that actually
reaches the question. Option 1 is not a deferral dressed as a decision: it is
the only option under which the manager can make this decision at all, because
the list did not exist a week ago. If the manager wants the OpenAPI rules in
`schemas/`, option 2 is a clean, self-contained packet and the harness gets
*smaller*, not bigger.

**Cost of flipping:** low and local. Every rule has one named function and one
inventory entry, so moving a rule is deleting a function and adding a constraint
— and the inventory is written so that "this rule now lives in a schema" is a
one-line change with a test that checks it.

## D24: the event catalog and the spec version are documents, not data

Raised by **core-07**, by the two rules the harness has to implement that nobody
had costed. core publishes the set of event types that exist as a markdown table
in [`docs/event-naming.md`](docs/event-naming.md), and its own spec version as
prose in [`CHANGELOG.md`](CHANGELOG.md). The harness therefore **parses a
markdown table** to answer "does this consumed type exist in the catalog", and
cannot answer "is this `core:` constraint satisfied by the core it is reading" at
all, because there is no version to compare against.

Parsing the document is the right call *today* — the document is the spec, and a
harness that shipped its own copy of the catalog would be a second catalog whose
drift from the first is invisible. That is the same argument as
[`docs/event-outbox.md`](docs/event-outbox.md) not shipping an implementation, and
it is why `caf` says the same thing about the catalog in its own
`internal/contract/doc.go`: "until core publishes it as a machine-readable file,
a linter can only check a repository against itself." The cost is that the
harness is now a **second reader of a markdown table**, and a reader that has to
be maintained in a spec repository is exactly the thing
`test_no_open_decision_callouts_remain_in_the_docs` exists to prevent elsewhere.

**Choice: read the document, and record the two facts as owed.** The harness
reads the table, `test_the_harness_evaluator_agrees_with_jsonschema_on_every_example`
and the reader's own tests keep it honest, and the `core:` constraint rule is
listed in `harness/rules.json` under `notEnforced` with the reason — "core
publishes no machine-readable spec version, so there is nothing on either side of
the comparison". Publishing `schemas/catalog.json` and a `specVersion` are core
changes, not harness changes, and a worker should not invent a new file in
`schemas/` while a re-vendor fan-out is still undefined
([D21](DECISIONS.md#d21-a-breaking-schema-change-has-no-re-vendor-fan-out-step)).

**Alternatives:**

1. Read the document, as landed. No new file in `schemas/`, so no re-vendor
   obligation, and the catalog cannot drift from the table because there is only
   one copy. The cost is a markdown parser in the harness and a `core:`
   constraint nobody checks.
2. **Publish `schemas/catalog.json`**, generated from `docs/event-naming.md` and
   asserted equal to it by a test — the same "a doc and its schema are the same
   contract written twice" pattern core already uses for the manifest and the
   event-type pattern. The harness reads the data file and the table stays the
   spec. The cost is a second file under `schemas/`, which every vendoring
   service now has to re-vendor, and that is precisely the fan-out
   [D21](DECISIONS.md#d21-a-breaking-schema-change-has-no-re-vendor-fan-out-step)
   says has no owner.
3. **Publish the spec version in `schemas/`** — `schemas/spec.json` with
   `{"version": "0.3.0"}` — and resolve the `core:` constraint against it. Small,
   self-contained, and it closes a real gap: a service can then check that it was
   written against the core it is being tested against, which nobody can do today
   in any language.
4. **Both, in one file.** `schemas/catalog.json` carrying the version alongside
   the types. One file to vendor rather than two, at the cost of a file that is
   neither a schema nor a document and so has no obvious home in a repository
   whose rule is that rules live in `schemas/*.schema.json`.

**Recommendation:** option 3 first, and option 2 only after
[D21](DECISIONS.md#d21-a-breaking-schema-change-has-no-re-vendor-fan-out-step) has
an owner. The spec version is one small file that closes a check nobody can
perform today, and a new file under `schemas/` should not land while the
obligation to re-vendor one is undefined — that ordering is the whole of the
recommendation. Option 2 is right and premature, and the harness reading the
document is what makes it safe to be premature.

**Cost of flipping:** the harness's `event_catalog` function becomes a `json.load`
and the `notEnforced` entry for the `core:` constraint becomes a rule. Both are
inside one function and one inventory entry each, and
`test_the_harness_yaml_reader_refuses_a_named_list_of_core_documents` stops being
the place where "we read a document instead of data" is written down.

Raised by **core-07** from the harness's first run against the real fleet, and
this is the only one of the four open decisions that came from *running* the
thing rather than from building it. Pointing
[`docs/contract-harness.md`](docs/contract-harness.md)'s subject at the eleven
real service repositories produced exactly one class of finding that turned out
not to be a service's fault:

    FAIL openapi.paths-are-versioned openapi/v1.yaml: paths -> /healthz
    FAIL openapi.paths-are-versioned openapi/v1.yaml: paths -> /readyz

in `identity`, `darkroom` and `pantry`. All three document their two probes
alongside their versioned paths. `courier` does the opposite and says why in its
document header: "`/healthz` and `/readyz` are not in the document and are not
going to be. They run before auth, routing and the rest of the platform exist,
no customer codes against them, and the document's header says so." `muse`'s
`tests/test_openapi.py` asserts the same thing as a rule: "the probe endpoints
are not in the contract".

So the fleet has two opposite, deliberate, documented practices — and
[`docs/openapi-conventions.md`](docs/openapi-conventions.md) does not say which
one is right. Its checklist says "Path under `/v1`" with no exception, and its
"Versioning" section says "Every path is prefixed". Meanwhile
[`docs/observability.md`](docs/observability.md) and
[`schemas/telemetry/probes.schema.json`](schemas/telemetry/probes.schema.json)
say a great deal about the two probes, and neither mentions the OpenAPI document
at all. **The rule the harness enforces is real and correct; the spec is silent
about the case it lands on, and the harness is reporting the silence.**

**Choice: do not decide it here, and let the harness keep reporting it.** A
worker does not get to decide whether core's HTTP contract includes health
probes — that is a spec question with a customer-visible answer, and the three
services that document them are not wrong on the evidence available to them. So
the rule stands as written, the three services are reported as non-conforming,
and the question is numbered here. The alternative — quietly widening the rule to
exempt two paths — would be resolving a manager's decision inside a harness, and
`harness/rules.json`'s `notEnforced` block exists so that anything like it is
written down rather than done.

**Alternatives:**

1. Record the gap, as landed. The rule is unchanged, three services are red
   against it, and the question is visible. The cost is that a red build in
   three repositories has no fix in core yet, which is the state that makes a
   manager want to decide.
2. **Exempt `/healthz` and `/readyz` from the prefix rule**, stated in
   `docs/openapi-conventions.md` next to the versioning section and enforced as
   a named exception in `harness/rules.json`. It matches two services and
   contradicts three. The cost is that an unversioned path is now a *sanctioned*
   one, and `gateway`'s routing prefix and the SDK generators both read the same
   document — a generated client would gain a health-check method.
3. **Require the probes to be documented**, which is the other two services'
   practice, and change the two that do not. The cost is that an SDK generated
   from the document carries `/healthz`, and a customer can now depend on a probe
   that exists before auth, routing and the platform do.
4. **Leave it to each service, and say so** — no rule, no finding, and a note in
   `docs/openapi-conventions.md` that the document's contents are the service's
   decision. The cost is that the two practices stay divergent with nothing
   recording that they were chosen, which is the drift
   [`docs/event-naming.md`](docs/event-naming.md) spends its catalog preventing
   for event types.

**Recommendation:** option 2, and option 1 until it is decided. Option 2 matches
the argument `courier`'s header and `muse`'s test both make independently — a
probe is infrastructure, not contract — and an infrastructure endpoint under a
version prefix implies a stability promise about a route that runs before the
platform does. If the manager prefers option 3, it is a one-sentence change to
`docs/openapi-conventions.md` and three manifests, and nothing in the harness
changes; if option 4, the harness drops one rule and `harness/rules.json` loses
one entry.

**Cost of flipping:** one sentence in
[`docs/openapi-conventions.md`](docs/openapi-conventions.md) and one rule in the
harness — either a named exemption inside `openapi.paths-are-versioned` or its
deletion. The three services' manifests do not change under options 2 and 4, and
do under option 3.
## D26: do the cafaye fields live inside the Sloth document or in a cafaye document kit converts?

Raised while writing the SLO spec. Affects
[`schemas/telemetry/slo.schema.json`](schemas/telemetry/slo.schema.json),
[`examples/valid/telemetry/slo.yaml`](examples/valid/telemetry/slo.yaml) and
every `slos/*.yaml` a service will write.

The chosen artifact is a Sloth `prometheus/v1` file, because Sloth's validator is
a single static binary that walks a directory with no cluster and no Docker
daemon and because its SLI is two PromQL strings — the one representation all six
languages can be checked against without a Go or Rust parser. What core adds on
top of Sloth is `tier`, `period`, `labels` and `sli.catalogEntry`, and those four
fields are the question: **Sloth's YAML loader may or may not tolerate keys it
does not know, and core cannot find out offline.**

**Choice: the cafaye fields live inside the Sloth document**, and
`additionalProperties: false` decides what may appear in it. `docs/slo.md` and
the schema's own description say so.

**Alternatives:**

1. **One document, cafaye fields inside it**, as landed. The service commits one
   file, `sloth validate -i slos/` reads it, and the harness checks the same
   bytes. It relies on Sloth's loader ignoring the four keys it does not know.
2. **A cafaye document kit converts** — `slo.cafaye.yml` declares tier, period and
   labels, and kit emits `slos/<service>.yaml` for Sloth. Every field is one
   document with a schema that Sloth has never seen, and the strict-loud question
   disappears. The cost is two artifacts per service, a generator nobody has
   written, and a second copy of the SLI composition to keep in step.
3. **The cafaye fields live in a sidecar per SLO** (`slos/<service>.tier.yml`).
   Cheapest to make Sloth-compatibility certain, and it splits one fact across
   two files: an SLO with a tier in one file and an objective in the other is a
   mismatch nothing checks.

**Recommendation:** option 1, with option 2 as the fallback **only if** the first
`sloth validate` run against a real declaration reports an unknown key. The
evidence for option 1 is that Sloth resolves its spec with a non-strict
`yaml.Unmarshal` — which is how `--extra-labels` and the multi-file form work at
all — but core could not confirm it without network access, and an unverified
assumption about another project's parser is not something to bury in a spec.

**Cost of flipping:** one commit. `slo.schema.json` moves to describe a cafaye
document, the example moves with it, and kit gains a four-line transform that
strips the cafaye keys before `sloth validate`. The harness reads whichever
document the schema describes and none of the eight rules change. The window
catalog and the SLI catalogue are untouched either way.

## D27: the burn factors come from a 30-day budget and the period is 28 days

Raised by the arithmetic in packet core-08's own brief. Affects
[`schemas/telemetry/slo-windows.schema.json`](schemas/telemetry/slo-windows.schema.json),
`period` in [`schemas/telemetry/slo.schema.json`](schemas/telemetry/slo.schema.json),
and [`docs/slo.md`](docs/slo.md).

The rulings are: 14.4 / 6 / 3 / 1 at 5m+1h, 30m+6h, 2h+1d, 6h+3d, with the
arithmetic published as `14.4 = 0.02 x 720h`; and a 28-day period, not 30. **Those
two do not agree.** 720 hours is thirty days. Two percent of a 28-day (672-hour)
budget is **13.44**, so the workbook's factors — which are also Sloth's shipped
defaults — are about 7% conservative under this spec: the fast-burn alert fires
slightly *earlier* than the workbook intends.

**Choice: implement both as ruled.** 14.4 and `period: 28d`, and
`test_the_window_catalog_is_the_workbooks_numbers` asserts the workbook's
arithmetic, the 28-day arithmetic, **and the direction of the gap**, so the
inconsistency cannot quietly become a number nobody recomputed.

**Alternatives:**

1. **As landed** — the workbook's numbers, a 28-day period, ~7% conservative.
   Zero migration cost, and it matches what Sloth does by default, so an operator
   who has read the Sloth documentation sees the numbers they read.
2. **Recompute for 28 days** — 13.44 / 5.6 / 2.8 / 0.933. Each factor is
   `fraction x 672`, so every alert matches the budget it is measured against
   exactly. The cost is that the fleet's numbers differ from the published
   workbook's and from Sloth's defaults, and 0.933 is a threshold nobody can
   remember.
3. **Go back to a 30-day period.** Reverts R3, and loses the reason for it: four
   weekends in the window rather than 4.3, so the same weekend maintenance costs
   the same fraction of the budget every month.

**Recommendation:** option 1, until an operator notices. The error is 7% in the
safe direction — an alert that fires a little early rather than a little late —
and option 2's 0.933 is a number that will be "corrected" by the next person who
reads it as a typo. If the manager prefers exactness, option 2 is eight `const`
values and one paragraph, and `test_the_window_catalog_is_the_workbooks_numbers`
is the test that has to change with them.

**Cost of flipping:** eight numbers in
`slo-windows.schema.json`'s `prefixItems`, the arithmetic in `docs/slo.md`, and
the two constants in `tests/test_specs.py`. No service is affected: nothing
declares an SLO yet.

## D28: may core's gate take the `sloth` dependency?

Raised by packet core-08. Affects [`docs/slo.md`](docs/slo.md),
[`harness/rules.json`](harness/rules.json)'s `notEnforced`, and CI.

Ruling R1 makes Sloth the artifact because `sloth validate -i <dir>` is the one
validator that needs no cluster and no Docker daemon. That is true of the tool
and not of the *installation*: it is a Go binary, and core's gate would have to
fetch and build it.

**Choice: not taken.** The harness implements the checks that matter — the SLI
composition, the metric and label allowlists, the two denylists — in the standard
library, and `docs/slo.md` gives the pinned command for a service that has
network. `rules.json`'s `notEnforced` records, in the repository's own words,
what is left: PromQL *grammar*.

**Alternatives:**

1. **Not taken**, as landed. `bin/prime` stays a venv and four PyPI packages on
   first run; a Go toolchain never enters a spec repository; an air-gapped runner
   is unaffected. The cost is that a query that is the canonical *string* but
   invalid PromQL is not caught by core — `slo.sli-canonical` compares composition
   and says nothing about the grammar.
2. **Pin a released Sloth binary and download it in CI**, with the version in
   `tests/requirements.txt` next to the four PyPI packages. Real validation on
   every gate. The costs are that the gate needs the network for a tool rather
   than for a library, that the pin has to be bumped deliberately (a Sloth
   upgrade can change what "valid" means), and that every contributor's first
   `bin/prime` would depend on a Go release being reachable.
3. **A container image for the check**, run by a CI step that has Docker. It is
   the most honest gate and the least portable one, and it contradicts
   `docs/contract-harness.md`'s "no cluster, no daemon" argument for the harness.

**Recommendation:** option 1, and option 2 in a *service's* CI rather than
core's — which is where `sloth validate` already belongs, and where a network and
a Go toolchain are ordinary. Core's contribution is the composition check, which
is stricter about shape than Sloth is and is the part six languages get wrong.

**Cost of flipping:** one CI step, one line in `tests/requirements.txt`, and a
pinned version to keep in step. If the manager rules for option 2, this decision
moves to the CHANGELOG's decision table and `notEnforced` loses its third entry.

## D29: which tier does each of the seven services get?

Raised by packet core-08's boundary: the spec says the tier alone decides whether
a page is generated, and no service declares an SLO yet, so nobody has chosen a
tier. Affects every `slos/*.yaml` the next packet writes, and
[`docs/slo.md`](docs/slo.md)'s tier table.

The derivation is mechanical and tested — given a tier, the schema produces the
two alert switches. What is not decided is **which tier each of the seven
services gets**, and that is a judgement about how much of a self-hoster's
product stops working when each service stops working.

**Choice: not built, and not decided.** Packet core-08 was told not to write SLOs
for the seven services, and a tier without an SLO behind it is a number with
nothing to page on.

**Alternatives:**

1. **Decide it now, from the architecture.** `identity` and `muse` are the only
   services a private product cannot run without, so they are `high`; `billing` is
   `low` because an invoice can be recomputed tomorrow; `courier` is `low` for
   the same reason; `darkroom` and `gateway` are `none` until something depends on
   them. The cost is that this is a guess about a self-hoster's product made in a
   repository that has never been installed by one.
2. **Decide it per deployment.** The tier ships as configuration in the deployed
   `cafaye.yml` rather than in the committed SLO. Honest for a self-hoster — the
   same build can be `critical` for one cafe and `none` for another — and it
   breaks the whole packet's central claim, that the tier *alone* decides and is
   machine-checked, because a value that varies per deployment is a value the
   schema cannot pin.
3. **Default every tier to `low` and let the first real incident raise it.** Every
   SLO gets a ticket and no SLO gets a page, which is the safe default for alert
   fatigue and the useless default for detection.

**Recommendation:** option 1, in the packet that writes the SLOs, with the tiers
written into each service's committed declaration and stated in
[`fleet.yml`](fleet.yml)'s telemetry block. The packet that writes them is the
first one to meet a real self-hoster's traffic, and a tier guessed from an
architecture diagram is the same shape as an objective guessed from a dashboard.

**Cost of flipping:** one `tier:` line per SLO, and the alert switches follow
from the schema. There is nothing to migrate, which is the property that makes
option 2 tempting and wrong.
## D30: the gate declaration names an argv, and the checker runs it

Raised by packet core-09. Affects [`schemas/gate.schema.json`](schemas/gate.schema.json)'s
`$defs.proof`, [`gate.yml`](gate.yml), and
[`docs/gate.md`](docs/gate.md)'s "The format" section.

The question is what a gate declaration is *for*. It could describe a gate, or it
could be the thing that decides whether a gate counts as having run.

**Choice: it is the second, and that is the whole design.** A declaration carries
`gate.proof` — one or more patterns the gate's own output must contain, with an
optional `minimum` floor read from a single capture group. A run that exits 0
without emitting a declared proof is `gate.proof-missing`, and it is a failure.

**Alternatives:**

1. **Describe only** — the declaration says what the gate is and what it needs,
   and nothing runs it. Cheaper, and a checker for it is a linter: it can catch a
   command that no longer exists and it cannot catch a gate that does nothing.
   This is the alternative the packet's own measurement argues against, and the
   false green it cannot catch is the one this fleet has already shipped once.
2. **Require a machine-readable test report** and match on that (JUnit, pytest's
   `--junitxml`, `go test -json`). Stronger — it is a count, not a line of text —
   and it is MD12's direction for the right reason. The cost is that four
   languages in this fleet produce no such report, or produce it in four
   different dialects, and a format every repository can write has to be
   writable by all of them. `match` is a regular expression, which every one of
   them can satisfy by printing one line.
3. **Require a cryptographically signed report.** Refuses a restored cache, and
   answers a question nobody asked: the problem is not that a report is forged,
   it is that a report is *about a different run*. A report restored from another
   branch is a report with the wrong number in it, and a signature over it is
   still the wrong number.

**Recommendation:** option 1 now, and option 2 as a per-repository tightening —
`match` can already be `'<testsuite ... tests="1166"'` against a JUnit XML, so a
repository that has a real reporter gets a real report with no format change.
The line that changes if the manager rules for option 2 is `gate.proof[].match`,
and nothing else in the schema, the checker or the twenty-three breakages.

**Cost of flipping:** one property name and one regular expression per proof. The
checker already requires exactly one capture group when `minimum` is set, so
adopting a JUnit-based floor is a spelling change and not a redesign.

## D31: the gate checker is stdlib-only and needs Python 3.11, where the contract harness needs 3.9

Raised by packet core-09. Affects [`harness/bin/gate-check`](harness/bin/gate-check),
[`harness/gate_check.py`](harness/gate_check.py)'s `MINIMUM_PYTHON`, and every
repository whose CI would call it. See also
[`docs/gate.md`](docs/gate.md).

`harness/gate_check.py` reads `mise.toml`, and `tomllib` is standard library
from 3.11. `harness/cafaye_contract.py` accepts 3.9 because it reads no TOML.

**Choice: `gate-check` requires 3.11 and the wrapper exits 2 with a message on
anything older.** The two minimums differ and both are named.

**Alternatives:**

1. **Shell out to `mise tasks`.** Works on 3.9, and makes the checker's answer
   depend on which `mise` is installed — and on what happens when there is none,
   which is the state of `gateway`, `muse` and `kit`. A check whose answer depends
   on the day is the failure mode this packet exists to catch.
2. **Write a TOML subset reader, the way the YAML reader was written.** The YAML
   reader exists because a reader that cannot read the documents it exists to
   check is a demonstration. A TOML reader would be a second reader of a second
   language, in a repository whose rule is that a rule lives in exactly one place.
3. **Drop the mise cross-check** and verify only the entrypoint on disk. Loses
   `gate.task-missing` and `gate.task-unresolvable`, which are the two checks
   that would catch a repository's fleet spelling drifting away from its gate.

**Recommendation:** the choice as built. 3.11 is four years old, every language
in this fleet already has a newer interpreter, and the price is a refusal with a
sentence explaining it rather than a silent degradation to a green.

**Cost of flipping:** the alternative that is actually attractive is option 3,
and it costs one schema property, one code path and two of the twenty-three
breakages. If the manager rules that 3.9 support is worth more than the mise
cross-check, that is the change to make.

## D32: whether a repository with no CI is a warning or a failure

Raised by packet core-09. `docs` and `cafaye-py` have no `.github/workflows` at
all, and a `ci` block cannot be written for a file that does not exist. Affects
[`schemas/gate.schema.json`](schemas/gate.schema.json)'s `$defs.ci` and
`harness/gate_findings.json`. See also
[`docs/gate.md`](docs/gate.md)'s findings table.

**Choice: `gate.ci-undeclared` is a warning, and a warning never moves the exit
code.** A repository that gates locally and has no CI is a real state, and the
right response to it is to report it, not to fail a gate over it.

**Alternatives:**

1. **Fail it**, and require every repository to have a workflow. The strongest
   answer to "a CI job that silently skips the hard part is worse than no CI",
   and it makes the first adoption in `docs` require writing a workflow the
   packet was told not to write there.
2. **Make `ci` required with a declared `none`.** The declaration then says "this
   repository has no CI" in a machine-readable way instead of by omission. The
   cost is a value that is easy to leave in place after a workflow is added, and a
   stale `none` is a declaration quietly describing something that no longer
   exists — the exact failure mode core's own rule names.

**Recommendation:** the choice as built, with option 2 as the tightening once the
fleet has adopted the format everywhere. `none` is the one line that changes, and
`gate.ci-undeclared` becomes `gate.ci-none`, which is a smaller question than
whether CI agrees.

**Cost of flipping:** one enum value, one finding id, and the rename of one
breakage in `harness/tests/gate_self_test.sh`.

## D33: cross-tenant access is declared, never inferred, and answered as nonexistence

Raised by packet core-15. Measured across the fleet: cross-tenant negative tests
— ones asserting account A is refused account B — number 7 in identity and 19 in
courier, and **zero** in billing, cafaye-rb, cafaye-ts, gateway, darkroom, pantry,
muse and cafaye-py. Six of those eight scope by account in production code.
`darkroom` is the clean case: `assets` and `asset_variants` carry `account_id
uuid not null`, every statement reads `where id = $1 and account_id = $2`, and
no test asserts any of it. Counting account-scoped routes by pattern gives 96
for gateway, 76 for muse, 51 for cafaye-ts and **0** for darkroom and billing —
the last two because axum and Rails are not the syntax the pattern reads.
Affects [`schemas/tenant-isolation.schema.json`](schemas/tenant-isolation.schema.json),
[`docs/tenancy.md`](docs/tenancy.md) and `harness/tenancy_check.py`.

**Choice: cross-tenant access is DECLARED, never inferred; and it is answered as
NONEXISTENCE, never as a refusal.** A service publishes `tenancy.yml` naming
every entry point that reaches another account's data, the line at which each is
scoped, and the test that asserts account A gets nothing back for account B's
row. The checker reads that declaration against the tree. It does **not** derive
the enumeration: a checker that inferred it would answer per framework, and the
answer would be a syntax report wearing a security report's clothes.

The second half is the decision somebody will otherwise relitigate in every
service. `403`/`ErrNotAuthorized` tells an attacker the id exists; `nil`, `[]`,
`None`, `NotFound` tell them nothing. So `negative.asserts` is a `const: absent`
— not an enum with a discouraged second value — and `tenancy.denial-refuses` is
a **failure**, so a service that weakens the assertion gets a red that names the
enumeration oracle rather than a style comment.

**Alternatives:**

1. **Infer the enumeration.** Enumerate routes, queries and repository methods per
   framework and have the checker prove the boundary. Rejected on the measurement
   above: it returns 0 for darkroom and billing, and a report that says "no
   account-scoped routes" about a service with account-scoped queries against
   customer assets is **worse than no report**, because it reads like an answer.
   Any inference also has to choose a framework's syntax, and the fleet has
   axum, Rails, Ecto, sqlx and TypeScript decorators.
2. **A rule instead of a declaration** — "a query touching an account-prefixed
   table must carry an account predicate". It cannot see the join that drops the
   scope, the CTE that loses it between two `select`s, the repository method
   three layers down, or the middleware that resolves the account in the first
   place. And a rule right about 90% of sites reads as a boundary that holds.
3. **Allow `403` and document the trade-off.** Rejected: it is answerable per
   service with no cost, and the reason it keeps coming back is that "the resource
   exists but you may not have it" is a *more useful* answer to write. Naming it
   a `const` is the only thing that stops that conversation happening per
   service, which is the entire value of a contract.
4. **Require the negative assertion, say nothing about its shape.** That leaves
   `assert get(id, other) == 403` and
   `assert get(id, other) == nil` both counting as coverage, which is the
   defect the second half of this ruling exists to close.

**Recommendation:** the choice as built. The one place to revisit first is
closure for non-SQL languages: that needs a parser per language rather than a
pattern, it belongs in `caf`, and until it exists the honest answer is the
`tenancy.enumeration-partial` warning rather than a fail — which is also why the
warning exists and why it never moves the exit code.

**Cost of flipping:** to inference, the `entryPoints` array becomes computed, the
schema loses `enforced.file`/`enforced.line`/`negative` (they become check-time
conclusions rather than declarations), and `harness/tests/tenancy_self_test.sh`
loses its sixteen breakages — every one of which is a defect an inferred
enumeration would have to be *right about* to catch, which is the same argument
that has the fleet reading its own boundary from a text pattern today. To the
absence half: one `const` becomes an `enum`, one finding id disappears, one
breakage is renamed, and every service that adopted `absent` keeps it — the
schema change is cheap and the migration is the part that would take a release.

## D34: how does the fleet record a type core has not finished contracting for?

Raised by packet core-22, while correcting a registry that had been describing
yesterday's fleet. Measured at the identity repository's `master` on 2026-10-01
(`a20be0f`): its manifest declares **nine** event types in the conforming
three-segment form. `fleet.yml` recorded **one** of them as published and eleven
as `cataloguedOnly` — so eight of the eleven were, at the time of the claim,
both published by identity and marked as a promise nobody had made good. Six of
the eight have a row in `docs/event-naming.md` and no payload schema under
`schemas/events/identity/`; the two `identity.oidc_client.*` types have neither,
because no catalog row for either exists anywhere in core. The same packet found
the mirror case in courier, where a prose note denied an `exposes.api` courier
had declared since courier-05, because `fleet.schema.json` had no field to record
one in. Affects [`schemas/fleet.schema.json`](schemas/fleet.schema.json),
[`fleet.yml`](fleet.yml) and
[`tests/test_specs.py`](tests/test_specs.py)'s
`test_a_pending_core_contract_type_is_a_debt_core_really_owes`.

**Choice: the registry gains a FOURTH list, `pendingCoreContract`, and it is
constrained rather than free.** A conforming type the manifest declares and the
service publishes, for which core has not shipped both a catalog row and a
payload schema, goes in `pendingCoreContract` — never in `events`, which means
"core's contract for this type is finished" and is asserted to mean it. The list
is the exact mirror of `cataloguedOnly`: that one is a promise core made that
nobody has kept, this one is a promise a service kept that core has not answered.
And it is asserted in the direction that can be checked from inside core: an
entry that has both a row and a schema is **rejected**, because a debt with
nothing behind it is an excuse for work already done, and a registry carrying
excuses is how a reader stops believing the list that is telling the truth.

**Alternatives:**

1. **Write the eight missing payload schemas, and the two missing catalog rows,
   in this packet.** It is what `events` wants, and it is the state with no
   fourth list. Rejected on scope, not on merit: it means authoring core's
   payload contract for another repository's events — eight schemas read off
   identity's Go source, two rows invented for types core has never described —
   inside a packet whose job is a transcription. A payload schema is a promise
   to every consumer on the bus, and one written by somebody who did not ship
   the publisher is a promise made on the publisher's behalf. It is the right
   work and it is its own packet.
2. **Leave identity's `events` short of what its manifest declares, and say so
   in prose.** This is what the file did, and the cost is the whole packet: the
   reader sees `events: [identity.user.created]` against a `sourceCommit` that
   says otherwise, with nothing machine-checkable distinguishing "this service
   publishes one type" from "this registry got round to one type". Prose is not
   compared against anything, which is how courier's `exposes.api` sentence
   outlived two packets that edited the document it said did not exist.
3. **Add `pendingCoreContract` with no constraint on it.** Rejected: a list that
   means "core has not finished this" stops meaning that the first time a type in
   it is finished, and nothing would notice. This is the same defect as reading
   `signals: []` as "this service is not instrumented" — a field whose value
   teaches a reader a conclusion its absence supports.
4. **Make `events` mean "declared", and weaken the catalog assertion to exempt
   types with no row.** Rejected outright: it deletes the assertion that has
   teeth. That assertion is the reason the event types courier could not emit
   were caught at all, and an exemption keyed on "core has not got to it yet" is
   an exemption every type qualifies for.

**Recommendation:** the choice as built, and the constrained list is the part
that matters — option 3 is the same schema change with the teeth left out, and
it is the one that would rot. The cheap direction to revisit is option 1: the
day core writes identity's remaining payload schemas, every entry here moves to
`events` and the list empties, and the assertion above is what makes that move
safe to make without checking by hand.

**Cost of flipping:** to option 1, eight files under `schemas/events/identity/`
and two rows in `docs/event-naming.md`, after which `pendingCoreContract` is
empty and the list, its schema entry, its three pairwise-disjointness assertions
and this decision can all be deleted — the deletion is the acknowledgement, the
same convention `manifestViolations` follows. To option 2, the transcription
goes back to being a claim with no machine-checkable half, and this packet's
other four corrections would have had to be prose too. **What this decision does
not settle, and must not be read as settling:** whether the service really emits
each type in the list. That is `sourceCommit`'s job, it is not checkable from
inside core, and the schema's own description says so rather than implying a
check that does not exist.

**Update, core-23: the debt is paid and the list is empty, and the deletion D34
names was NOT taken in full.** Eight payload schemas and two catalog rows landed;
all nine of identity's declared types are in `fleet.yml`'s `events`; the
`pendingCoreContract` key is gone from every entry. What stayed is the schema
property, `fleet.yml`'s header and all three assertions, because the alternative
D34 priced was priced for a registry that could be deleted cleanly and this one
cannot: the next type a service declares and core has not answered needs a list
whose meaning is checkable in both directions, and a deleted list is a fourth
place to invent. D34 also priced removing the assertions, and that is where the
packet overrode it — with the list empty,
`test_a_pending_core_contract_type_is_a_debt_core_really_owes` had nothing left to
iterate and would have passed on anything, so the rule moved into
`pending_core_contract_debts` and a new test hands it a fleet carrying a type core
HAS finished. Shown red: with the schema half of the predicate removed, the new
test fails and the old one stays green, which is the entire reason it exists. The
"cost of flipping" line above is therefore still accurate about the schemas and
the rows, and wrong about the deletions.

## D35: `identity.user.created`'s payload schema describes a payload its only publisher does not emit

Raised by packet **core-23**, while writing the other eight identity payload
schemas. Read at identity's `master` on 2026-10-02, commit `a20be0f` — the same
commit `fleet.yml` already transcribes. Affects
[`schemas/events/identity/user/created.schema.json`](schemas/events/identity/user/created.schema.json),
its example at
[`examples/valid/events/identity/user/created.data.json`](examples/valid/events/identity/user/created.data.json),
and the premise of
[D7](#d7-courier-keys-a-user-by-uuid-and-identity-publishes-a-usr_-id).

**What the code says, read rather than remembered.**
`internal/outbox/envelope.go`'s `NewUserCreated(now, userID, email)` marshals a
struct of exactly two fields — `user_id` and `email` — and passes
`userID.String()`, which is `internal/platform/id/id.go`'s `String()`: RFC 4122
canonical form, eight-four-four-four-twelve lower hex, no prefix. So the shipped
schema is wrong in **four** places, not one:

| The schema says | The publisher emits |
| --- | --- |
| `user_id` matches `^usr_[0-9A-Z]{26}$` | a bare uuid, so **no value identity has ever produced satisfies this pattern** |
| `email_verified` is `false` | not present — the struct has two fields |
| `locale` is a BCP 47 tag | not present |
| `account_ids` is an array | not present |

The first is the serious one, and it is not a disagreement between two services —
it is a contradiction between two files in the same directory. core-23 wrote
`user_id` as `format: uuid` in eight schemas beside this one, with a description
saying why, and cited **D7** for it; D7's own text says the `usr_` half is "what
identity emits". One of those two sentences is false and the false one is the
older. The three absent fields are the milder version of the same defect, and
`docs/event-naming.md`'s rule — *a payload schema describes what a publisher
emits, not what it ought to emit* — is what all four violate.

**Choice: core-23's escalation, upheld and closed by the manager on 2026-10-02 as
option 1, released as a PATCH.** The three grounds below were right — core-23
shipped eight schemas and did not touch the ninth, because it is a change to a
**shipped** payload contract, because it is not one of the eight types the debt
was about, and because the fleet-wide question underneath it had already been
answered twice in the same direction and a third answer was not that packet's to
give. A change to a shipped contract belongs in a release rather than in a packet
whose brief is a debt list, and escalating it was the correct move rather than a
stall. What core-23 could not do is answer the version question, because README's
table is the rule and a worker resolving it quietly in a schema is a worker
deciding a spec. So the ruling is recorded here, with its reasoning, and the work
is in core-24.

**PATCH, and the table's three rows, applied to four changes at once:**

| README's row | This change | Verdict |
| --- | --- | --- |
| *a looser rule* | `user_id` from `pattern: ^usr_[0-9A-Z]{26}$` to `format: uuid` | **patch.** The new rule admits everything the old one admitted and every bare uuid besides. It invalidates nothing that previously validated. |
| *a removed event type* | three optional properties deleted from one event type | **not major.** These are not removed event types, and no publisher has ever emitted the fields: `internal/outbox/envelope.go:147-150` marshals a struct of exactly two. A consumer cannot depend on a field that has never once arrived, so nothing real breaks. |
| *tightening a pattern* | — | **nothing was tightened.** This is the row a reader will check, because a pattern *did* change, and the direction is what settles it. |

**The decisive fact, and the one that makes this safe rather than merely
convenient: the shipped schema rejected 100% of identity's real output.** The
pattern cannot match a bare uuid and identity emits nothing else, so there was no
working consumer to break. A major bump would have been signalling a break with
no recipient — and README says a `0.x` major must be *deliberate*, which is a
statement about the absence of one as much as about its presence. The absence is
recorded in [README.md](README.md#spec-versioning) and in
[CHANGELOG.md](CHANGELOG.md) rather than left to be inferred from a number nobody
bumped.

**The rules that made the absence safe, and they are the actual deliverable.**
D35 existed because **nothing compared a shipped payload schema against the code
that emits it.** Nine schemas sat under `schemas/events/identity/`, eight written
from identity's builders and one from an assumption, and the contradiction became
visible only because core-23 happened to write a second file in a directory the
first was already in — which is the generalisable form of the defect, since
nothing in core compared two payload schemas to each other. core-24 adds three checks and three witnesses, described
in [`docs/event-naming.md`](docs/event-naming.md#what-core-checks-against-the-publisher)
and each shown red on the file as it stood here: one publisher spells one id one
way; nothing core ships carries an id shape no publisher mints; and a payload
schema cites the commit its publisher was read at, checked against `fleet.yml`.
[D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read) is
the honest limit of all three — core reads no publisher, so they compare core
against core and cannot prove a schema describes the code it claims to have been
read from.

**Alternatives:**

1. **Rewrite it to reality, as core-23 did for the other eight.** `user_id`
   becomes `format: uuid`; the three never-emitted properties are deleted; the
   example loses `email_verified`, `locale` and `account_ids`; D7's second half
   is corrected rather than deleted, because a reader needs to see that the claim
   was once made — D35's own note said so, and core-24 kept the text and marked
   it false. **ADOPTED, as a patch**, and the version call is settled by the
   manager rather than left to a worker's judgement: README's table calls a
   removed *event type* major, and a field the only publisher never sent is not
   one. The reasoning is in the `Choice:` paragraph above.
2. **Leave it and let D7's cross-reference carry the weight.** Rejected, and it
   is the option this packet took only because the alternative is out of scope:
   a schema no publisher's output can satisfy rejects 100% of real traffic, and it
   does so *green*. `docs/event-naming.md` puts the cost of exactly this in
   writing — "a schema that names a field nobody emits is worse than no schema,
   because it is a contract that lies and it lies *green*."
3. **Accept both spellings** (`pattern` with an alternation). Rejected by D7 for
   courier's case and it is worse here: there is no second spelling in existence,
   so an alternation would accept a format no publisher emits and hide the defect
   behind a pattern that looks deliberate.
4. **Ask identity to emit `usr_`-prefixed ids.** Out of the question: it is a
   migration on every id in another repository, it breaks the join with courier
   and billing that already works, and core is the wrong repository to ask.

**Recommendation: option 1, in its own packet, with the test that would have
caught it — DONE, core-24, and the test is not the one sketched here.** The
sketch was: no file under `schemas/events/**` may require a cafaye-prefixed id,
walked as a list of prefixes (`usr_`, `acc_`, `sub_`, `pln_`, `inv_`). **The
prefix list is wrong and shipping it would have been the second half of this
defect in a new place** — `sub_` is a prefix cafaye does not mint and Stripe mints
on every subscription, and D10 says so in as many words, so the rule would have
gone red the first time billing constrained a processor id. A rule that fires on a
true fact is a rule that gets switched off. core-24 keys the rule on the *shape*
instead — a short lowercase prefix, an underscore, and a long run of uppercase
base32, which is a ULID behind a prefix and which a processor's mixed-case
`sub_1PZQaBcDeFgHiJkLmNoPqR1` is not — and adds the two comparisons that need no
new vocabulary at all: one publisher spells one id one way, and a schema cites the
commit its publisher was read at. All three are in
[`docs/event-naming.md`](docs/event-naming.md#what-core-checks-against-the-publisher);
all three are shown red on this file as it stood; and
[D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read)
records what none of them can prove.

**Cost of flipping:** spent, and recorded here so the next reader can price the
inverse. To option 1: one pattern became `format: uuid`, three properties were
deleted, one valid example and the valid envelope were rewritten, one
`INVALID_PAYLOAD_CASES` entry gained a `format` keyword, D7's second half was
marked false rather than deleted, two other schemas' descriptions that cited the
mismatch were corrected, and the floor in `gate.yml` moved from 224 to 230. Under
an hour, as priced. **To option 2 now, having shipped option 1:** reverse those
and expect the three checks to go red on `user_id`, on the id shape, and on nine
citations that would then name a commit the schemas were not read at. To option 2
at any point before this packet, it cost nothing and left a schema rejecting every
event its only publisher emits for as long as nobody looks at it.

## D36: what can a static check say about a publisher core has never read?

Raised by packet **core-24**, while writing the three checks
[D35](#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
asked for. Affects [`docs/event-naming.md`](docs/event-naming.md)'s *What core
checks against the publisher* section and
[`tests/test_specs.py`](tests/test_specs.py)'s `provenance_faults`,
`id_vocabulary_divergences` and `prefixed_id_uses`.

**The question underneath D35.** A payload schema's whole value is that it
describes what a publisher emits. core cannot import Go, reads no repository and
reaches no network, so the direct check is not available and never will be inside
this repository. Every option below is a weaker thing, and the failure mode of
each is the same: **a check that appears to prove more than it does is worse than
no check**, because core's own house rule — a rule no service implements is a rule
that lies — applies to core's own tests with no exemption.

**Choice: three in-core comparisons, each stated with its limit next to it, and
the real check named as owed to the services.** One publisher spells one id one
way. Nothing core ships carries an id shape no publisher mints. A payload schema
cites the commit its publisher was read at, and `fleet.yml` records the same one.
Each is paired with a witness that hands it the file as D35 shipped it, because a
rule that has never failed is a comment — the state core-23 found
`pendingCoreContract` in.

**Alternatives:**

1. **Ship the assertion D35 sketched and call it a day** — a prefix denylist over
   `schemas/events/**`. Rejected on measurement rather than taste: it fires on
   billing's legitimate processor ids, because `sub_` is Stripe's as much as
   cafaye's, and a rule that goes red on a true fact is switched off within a
   release. Keying on the *shape* (uppercase base32 behind a lowercase prefix)
   keeps the rule and loses the false positive, and one test asserts a processor
   id still passes so the distinction cannot be lost later.
2. **Require a citation on all twenty-three schemas and have the author invent
   the commit.** Rejected outright: the commit each of courier's, billing's and
   muse's payload schemas was read at is recorded nowhere in this repository, and
   writing one to satisfy a checker is inventing provenance — which is the exact
   failure the citation rule exists to catch. The obligation is scoped to
   identity, whose nine schemas were transcribed from `internal/outbox/` at the
   commit `fleet.yml` already records, and the other three are named as owed a
   re-read rather than faked.
3. **Require every payload schema to name its publisher's Go file and symbol.**
   Tempting and rejected: core-24 cannot read those files, so it could only check
   that a string *looks* like a path. That is a spell-check wearing a schema's
   clothes, and it would be satisfied by a wrong path.
4. **A publisher-side check — each service validates its own emitted events
   against core's schema — and nothing in core.** This is the check that would
   actually catch D35, and it is the destination. It is not core's to write: it
   belongs in `caf`'s lint or in each service's own test, it needs a checkout of
   both repositories, and a contract check requiring one is a check nobody runs on
   an air-gapped runner — the same argument that keeps the outbox and the
   OpenTelemetry collector out of this repository. Named as owed, not built.

**Recommendation:** option 1's shape with option 4 named as the real answer, which
is what shipped. The residue is worth stating plainly rather than discovering
later: **these three checks catch a lone schema that drifted, a stale or invented
citation, and a fleet-wide id vocabulary nobody read a publisher to confirm. They
cannot catch a publisher whose code changed without anybody re-reading it** — and
that is not a gap a fourth core-side check closes, because every remaining signal
is inside core and the drift is outside it.

**Cost of flipping:** each of the three is one function and one test in
`tests/test_specs.py`, so replacing or dropping one is a small diff — and dropping
the sibling-comparison rule specifically would leave the id vocabulary resting on
a single fact recorded in prose, which is the state D35 was found in. The expensive
half, option 4, is not in this repository at all.

## D37: how does core check that an example's ids are the ids its producer mints?

Raised by packet **core-25**, while correcting twenty-one examples that taught the
fleet an id shape no service emits. Read at identity's, courier's, billing's and
muse's `master` on 2026-10-02, at the commits `fleet.yml` already records for
each. Affects the sixteen examples under
[`examples/valid/telemetry/`](examples/valid/telemetry/),
[`examples/valid/events/billing/payment/succeeded.checkout.data.json`](examples/valid/events/billing/payment/succeeded.checkout.data.json),
three under [`examples/invalid/`](examples/invalid/), the `$comment` citations on
courier's five and billing's eight payload schemas under
[`schemas/events/`](schemas/events/), and the rules in
[`tests/test_specs.py`](tests/test_specs.py) — and it is the direct answer to the
question
[D35](#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
left as option 4.

**The finding, in one paragraph.** Sixteen examples under
`examples/valid/telemetry/` carried `tenant_id: "tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG"`
and `account_id: "acc_01J9Z8QK5M4N7P2R3T6V8W9X0A"` — a prefixed ULID, a shape no
publisher mints. core-24 shipped a rule saying exactly that, and it was **green
throughout**, because `valid_payload_documents()` globs `examples/valid/events/`
and never looked at the telemetry directory. Two independent reasons the same rule
missed all twenty-one: a directory it was not pointed at, and — for billing's
`client_reference_id` — an `IDENTIFIER_FIELD` regex admitting one underscore where
the field name has two.

**The real defect is upstream of the shape.** The prefix was the *symptom*.
`tenant_id` is not an id at all: it is an operator-set environment variable copied
verbatim onto the resource (`IDENTITY_TENANT_ID`, `COURIER_TENANT_ID`,
`BILLING_TENANT_ID`), and the producers' own tests give it `"acme"` and
`"tenant-abc"`. And `account_id` on a telemetry **resource** is emitted by nobody
— it appears zero times across identity's `telemetry.go`, courier's
`telemetry.ex`, billing's `kit/telemetry.rb` and muse's `telemetry.py`, while the
same field on an event payload is a bare uuid in four places. So "fix the prefix"
would have left two examples teaching a uuid `account_id` on a resource no service
produces, which is a fiction with a plausible face.

**Alternatives:**

1. **Point core-24's denylist at the telemetry directory too.** Cheapest, and
   insufficient. It fixes exactly the twenty-one values that are already in its
   shape and stops there: a denylist cannot know what a producer mints, so the
   next invented shape is green, and it cannot catch the `account_id` fiction
   because a bare uuid is not in its shape at all.
2. **Constrain the telemetry schemas** — `pattern` on `tenant_id` and
   `account_id`. Rejected on evidence: **no schema required the prefix, so there
   was no launch blocker to fix.** `tenant_id`/`account_id` are
   `{"type": "string", "maxLength": 64}` and nothing else, verified by walking
   every `pattern` in every file under `schemas/`. Typing `tenant_id` as a uuid
   would have been actively wrong — it is an operator label, and the next operator
   would have been rejected by core.
3. **Delete the offending attributes from the examples.** Done for `account_id`,
   because no producer emits it there. `tenant_id` was **kept and respelled**,
   because three services do emit it and the value is the point of the example.
   Spelling them correctly and removing them are different acts and the ledger
   records which is which.
4. **A per-service ledger, and require every example to match it.**

**Choice: option 4.**

**Recommendation: a per-service ledger, and require every example to match it.**
Each producer's id type is transcribed into
`PRODUCER_ID_SHAPES` from a **named file at a named commit**; each identifier
field is assigned one of those shapes in `IDENTIFIER_FIELD_SHAPES`; telemetry
resource attributes get their own table (`RESOURCE_ATTRIBUTE_SHAPES`) because a
resource attribute and a payload field under the same name are different
populations of values; and every identifier value in every valid example must
match the shape recorded for the field **of the service that emits that example**.

Two design points that were not obvious and are the reason it works:

- **The walk is in both directions.** A recorded shape that no example exercises
  is an assertion about code nobody re-reads, and it is a fault in its own right.
  Without this the ledger is a list, and lists rot.
- **The rule is keyed on the document, not the path.** `metric.json` is
  identity's, `log.json` is courier's, `span.muse.json` is muse's — all three sit
  in one directory. Attribution reads `service.name` off the example itself,
  because a directory-level rule would credit all sixteen to whichever service
  sorted first.

**A shape that accepts the fiction it exists to reject is worse than no shape.**
The first `operator-label` was `^[A-Za-z0-9][A-Za-z0-9._-]*$`, which includes the
underscore and therefore matched `tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG` exactly. The
witness test caught it by failing on a defect it was supposed to name. It is now
`^[A-Za-z0-9][A-Za-z0-9.-]*$` — dots and dashes are things operators write in
tenant names, an underscore is not.

**Cost of flipping:** the ledger is a Python constant and a regex per shape.
Dropping the rule returns core to a denylist pointed at one directory, which is
the state core-24 shipped and the reason twenty-one examples survived it. The
irreversible half is the **correction itself**: twenty-one examples now carry
values a real producer emits, and reverting them is easy while reverting the
*knowledge* is not — that came from reading four foreign codebases at named
commits, which is why every ledger entry names both.

**What this still cannot do**, stated so nobody has to infer it: core reaches no
publisher, so it cannot prove identity still generates version 4 uuids or that
courier still writes `message_id` as `"courier-" <> Ecto.UUID.generate()`. It
proves core's record of each producer and core's examples agree. Every entry
names the commit it was read at, so the day `fleet.yml` moves a `sourceCommit`,
the ledger is visibly stale — which is the same limit, and the same remedy, as
[D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read).

## D38: does a declared event type with no builder stay in core, or leave?

Raised by packet **core-26**, while checking whether `courier.email.queued`'s
publisher was *missing* or *misnamed*. Read at courier's `master` HEAD
`ae8a660f…` on 2026-10-02 and at `a8f15ccef11bd6148c71fbe38327d9fbebbfe2e2`,
which `fleet.yml` records and which is a reachable ancestor of that HEAD.
Affects
[`schemas/events/courier/email/queued.schema.json`](schemas/events/courier/email/queued.schema.json),
the `courier` section of [`docs/event-naming.md`](docs/event-naming.md) and the
`courier` entry in [`fleet.yml`](fleet.yml).

**The finding, and it is the packet's question answered from the other end.**
The packet asked core to work out whether the publisher was missing rather than
misnamed. It is **missing, and courier says so in courier's own words.**
`lib/courier/events.ex` at that HEAD still defines `delivered/1`, `bounced/1`,
`complained/1` and `suppressed/1` and **still has no `queued/1`**, and its
moduledoc states the reason: "`courier.email.queued` has no builder because
courier has no queue. The send path is synchronous and documented as such — the
provider is dialled inside the request — and that type exists to make a *backlog*
visible. With no backlog there is no moment at which courier could honestly emit
it." `AGENTS.md` and `cafaye.yml` repeat it, and `AGENTS.md` records that
`Courier.Workers` and `oban` exist and lost on one stated requirement: a 202
would answer before the suppression check has run.

Three checks, because "no builder" and "misnamed builder" are different answers
and only the state machine separates them:

1. **There is no queued state to have been misnamed.** courier's one state machine
   is `Courier.Suppressions`, whose states are `nil | :undeliverable |
   :suppressed` (`lib/courier/suppressions.ex` — the fold at lines 38-41,
   `state/1` at 236-247). The one bounded queue courier owns is the error relay's
   (`lib/courier/error_relay/sender.ex`), which carries error reports to
   GlitchTip and has nothing to do with mail.
2. **Acceptance and `courier.email.delivered` are the same moment.**
   `Courier.Deliver` mints `message_id = "courier-" <> Ecto.UUID.generate()` and
   dials the provider inside the open transaction, and `record/4` writes the
   delivered row in that same transaction (`lib/courier/deliver.ex:196` at that
   HEAD). There is no earlier event to publish, which is why the backlog this type
   would report is structurally zero rather than merely unmeasured.
3. **A builder is not an emission**, in courier's own phrase — which is why
   `courier.notification.suppressed` counted as uncalled until it did *not*, and
   why counting builders is not a proxy for counting publishers.

**Choice: the schema stays, and the type is recorded as
`declared-and-unimplemented` — core's own phrase, already in `fleet.yml`'s
courier note — in the schema's own `description` as well as its `$comment`.**

**Alternatives:**

1. **Delete `schemas/events/courier/email/queued.schema.json`.** Rejected, and the
   reason is not cost: deletion makes the registry assert something false. A
   declared type with no payload schema is exactly what
   [`D34`](#d34-how-does-the-fleet-record-a-type-core-has-not-finished-contracting-for)
   put in `pendingCoreContract`, and that list means *a service publishes this and
   core has not answered it*. courier does not publish it. Putting it there would
   convert an honest gap into a lie of the opposite direction, and D34 rejected
   its option 4 — exempting declared-but-uncontracted types from `events` — for
   the same reason. Removal also breaks `caf contract lint` in a consumer's
   build for an event that was never sent, which is the second cost the packet
   named and the smaller one.
2. **Leave it exactly as core-25 left it** — a `$comment` that admits the
   publisher does not exist, and a `description` that says "Emitted on acceptance,
   not on send, so a queue backlog is visible" as though it were a fact. Rejected:
   a `$comment` is metadata. `jsonschema` ignores it, `caf contract lint` ignores
   it, and an editor's hover shows `description`. So the admission was invisible
   to every reader it was written for, and the sentence that was visible was
   false.
3. **Add it to a tolerated-names list or an exclusion.** Not applicable and not
   offered: a type is not a name, and a list of types core will not check is a
   statement that core has decided not to look.

**Recommendation: the choice as built.** A consumer who subscribes to
`courier.email.queued` waits forever, and after this commit that is written where
the subscriber's tooling will show it — in the schema's `description`, in the
catalog row, and in `fleet.yml` — instead of living only in a comment. The
alternative that is actually available and cheap, when the want is for the event
rather than for the record, is for courier to build `queued/1` and wire a caller,
which is courier's packet and not core's.

**Cost of flipping:** to option 1, delete one file, its valid and invalid
examples, two rows in `examples/invalid/README.md`, the catalog row and the
payload table row, add the type to `fleet.yml`'s `pendingCoreContract`, and then
— the part that is not one commit — decide what to tell the two consumers who
generated a reader from it. To option 2, revert one sentence in one file, and put
the standing back where nothing displays it.

**The same read changed another sentence in core, and that is recorded here
because it was found by doing this one properly rather than by looking for it.**
`courier.notification.suppressed` **has a caller now.** `Courier.Unsubscribes.publish/1`
(`lib/courier/unsubscribes.ex:479-495`) writes an `outbox_events` row in the same
transaction as the `notification_preferences` row that turned the type off, with
`reason: preference_off`, the subject set to the user and no `message_id` — which
is core's
[D8](#d8-what-is-the-subject-of-couriernotificationsuppressed) and field-for-field
what `schemas/events/courier/notification/suppressed.schema.json` already
required. So courier publishes **four of five**, not three, and both
`fleet.yml` and `docs/event-naming.md` said three in sentences this packet was
editing anyway. courier still does not publish it for a *refused* send, and says
so in its own source. The schema needed no change, which is the outcome that
justifies having written its citation carefully in the first place.

**What this cannot do:** it cannot reach courier. It proves that core's record of
courier's builders and core's schemas agree on which builders exist at two named
commits. That is [D36](#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read)'s
limit and the same remedy, and this decision is the reason `fleet.yml`'s courier
entry now says out loud that its `sourceCommit` is behind the commit the prose
describes.

## D39: does a payload schema follow its publisher when the publisher has grown the feature the schema predicted it would not?

Raised by packet **core-26**, from core-25's finding that billing's subscription
payloads carry `plan_id` and `account_id` and that `examples/invalid/README.md`
cited D10 as saying billing has no such fields. Read at billing's `master` on
2026-10-02, commit `72519931c18773aacd66ff8dd942a209af10761e` — the commit
`fleet.yml` records, and billing's tree is verifiably AT it (clean tree, HEAD is
that commit). Affects
[`schemas/events/billing/subscription/started.schema.json`](schemas/events/billing/subscription/started.schema.json),
its `updated` and `canceled` siblings, the negative case for `subscription/started`
in [`examples/invalid/README.md`](examples/invalid/README.md), and the `billing`
section of [`docs/event-naming.md`](docs/event-naming.md).

**The finding, stated in both directions because that is the shape of it.**
`Subscriptions::Lifecycle#payload/2` (`app/services/subscriptions/lifecycle.rb:350`)
is `core_payload/1` merged with either `started_at` or `detail_payload`.
`core_payload/1` (line 353) writes, unconditionally, `subscription_id`
(billing's own `subscriptions.id`, a bare uuid), `plan_id` (`plans.id`, a bare
uuid), `account_id` (`customers.owner_id`, identity's uuid), `status` and
`currency`; `quantity` only when the processor sent an Integer, `trial_ends_at`
only while trialing. billing asserts a start's exact key set itself
(`test/services/subscriptions/lifecycle_test.rb:264-271`):
`account_id currency plan_id quantity started_at status subscription_id`.

So all three schemas — closed with `additionalProperties: false` — **reject fields
every real event carries** and **require fields they never receive**:

| | rejected, but emitted | required, but never emitted |
| --- | --- | --- |
| `subscription.started` | `plan_id`, `account_id`, `currency`, `started_at` | `processor`, `processor_event_id`, `kind`, `customer_id` |
| `subscription.updated` / `.canceled` | `plan_id`, `account_id`, `currency`, `processor_subscription_id`, `trial_ends_at` while trialing | `kind`, `customer_id` |

`processor` and `processor_event_id` *are* emitted on the update and cancellation
paths, by `detail_payload` rather than by `core_payload` — which is why they are
absent from the second column and why the three payloads are **no longer one
shape**, a fact `updated`'s `description` also asserted and no longer could.
billing has known both halves for some time and has said so in its own source:
`PENDING_PAYLOAD_ALIGNMENT` in `test/contract/outbox_envelope_contract_test.rb:66-88`
lists exactly these as `unexpected` and `missing` and is asserted in both
directions, and `lifecycle.rb:320-343` records that core's schemas "describe a
different payload, and this is recorded rather than matched" and that "when core
decides, the change lands here and in the contract test together". So this is a
**known, owned, two-sided gap and not an incident** — which is precisely why the
right response is a decision and not a panic.

**Why the citation is stale rather than the schema being wrong on arrival.**
core-25 transcribed these from `Subscriptions::Lifecycle#payload/2` at that commit,
and D10 rewrote them because billing had no subscriptions table. billing then grew
one (`db/migrate/20260930000007_create_subscriptions.rb`), so the schema was
correct when written and is behind its publisher now. See
[D10](#d10-billingsubscriptionstarteds-payload-schema-no-longer-describes-cafaye-ids)
for what D10 got right and for the dated update that says so.

**Choice: core's claims are corrected now; core's three subscription schemas are
NOT rewritten in this packet, and the disagreement is recorded in the schemas
themselves.** Every document in core that said billing has no such fields —
`examples/invalid/README.md`, `docs/event-naming.md`, and the `description` of
`subscription/started` — is corrected in this commit, and each of the three
schemas now says in its `description` (not only its `$comment`) that it does not
describe what its publisher emits, with the emitted key set, the source lines and
the commit beside it.

**Alternatives:**

1. **Rewrite the three schemas onto billing's live payload now.** This is what
   core's own doctrine says — "a payload schema describes what a publisher emits,
   not what it ought to emit" (`docs/event-naming.md`) — and
   [D35](#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
   is the precedent: rewrite it, loosen it, and release as a patch because the
   schema rejects 100% of the publisher's real output and so has no working
   consumer to break. The measurements above say the same thing. **Rejected on
   scope and on ownership, not on merit.** D35's rewrite only *loosened* — a
   pattern became `format: uuid` and three optional properties were deleted.
   This one **deletes four `required` properties** (`processor`,
   `processor_event_id`, `kind`, `customer_id`) that have shipped required since
   v0.2, on three of the fleet's busiest event types, with generated readers in
   consumers' hands. That is a change to a published contract with a consumer
   surface, and it partly reverses the replacement D10 made — which is a decision
   about what `billing.subscription.*` *means* on the bus, not a transcription.
   Per `README.md`'s governance a worker drafts it and the manager rules.
2. **Tell billing to drop `plan_id` and `account_id` and match core.** Rejected
   outright, and this is the correction the packet named: billing emits them
   because the feature exists, core's schema predates the feature, and
   `lifecycle.rb:339-341` names the two fields as "the two fields that make a
   subscription event actionable at all". A spec cannot make a publisher's payload
   smaller.
3. **Add the two fields as optional properties and leave the rest.** Rejected: it
   makes the schema accept an event shape it still cannot describe — billing also
   sends `currency`, `started_at` and `processor_subscription_id` — so it converts
   a loud failure into a quiet one, which is the failure mode `docs/event-naming.md`
   calls "a contract that lies and it lies *green*".

**Recommendation: option 1, in its own packet, as a patch, with the valid examples
moved in the same commit.** The drafted default and the work it implies:

- one `core_payload` shape for `started` and one `core_payload + detail_payload`
  shape for `updated`/`canceled`, i.e. the three schemas stop being copies of each
  other, which is a second breaking change for any consumer that shared one reader;
- `processor`, `processor_event_id`, `kind` and `customer_id` off `required`;
- `plan_id`, `account_id`, `currency`, `started_at`, `trial_ends_at` and
  `processor_subscription_id` in, all bare uuids, none cafaye-prefixed;
- the valid examples rewritten to billing's real payloads and the negative case's
  justification replaced with one that is true;
- billing's `PENDING_PAYLOAD_ALIGNMENT` emptied in billing's own commit, in the
  same PR that lands core's side — billing asked for exactly that pairing.

**Cost of flipping:** to option 1 as drafted, six schema/example files and two
documents, one patch release, and one PR in billing that this repository may only
describe. To leaving it as it is, **core ships three schemas whose `$comment`
claims a transcription that does not match the code it names** — which is the
provenance lie D36 exists to prevent, and which this packet reduces to a
documented standing rather than removing.

**What this cannot do:** core cannot ask billing whether this shape is intended or
provisional. `lifecycle.rb`'s own comment says the core-side change "lands here
and in the contract test together" when core decides, which is billing's
statement of what it will accept, and it is not a statement that the shape is
final. That is the question the manager's ruling has to put to billing.

## D40: is the resource allowlist missing a field the fleet uses, or is a service emitting something it should not?

Raised by packet **core-26**, from core-25's finding that muse emits
`service.namespace` and `traces.schema.json` refuses it. Read at muse's `master`
on 2026-10-02, commit `53b6ebb1947eeb1ff90a4cfaff75897f358dc2e9` — which
`fleet.yml` records and which is muse's HEAD — and at billing's `master` at
`72519931c18773aacd66ff8dd942a209af10761e`. The Python measurement was run
against the OpenTelemetry SDK **1.44.0** in muse's own `.venv`.
Affects [`schemas/telemetry/traces.schema.json`](schemas/telemetry/traces.schema.json),
its `logs` and `metrics` siblings, the `resource` block of
[`examples/valid/telemetry/span.muse.json`](examples/valid/telemetry/span.muse.json),
and the resource-attribute sections of
[`docs/observability.md`](docs/observability.md).

**Answer: the allowlist is missing fields the fleet demonstrably uses.** Not one
field — four, and the fourth is the reason the first three went unnoticed:

- **`service.namespace`** is set by muse **by hand** at
  `src/muse/telemetry.py:390` (`"cafaye"`) and asserted in
  `tests/test_resilience_config.py:355`. It is the only publisher that sets it.
  It is a **Stable** OTel semantic-convention resource attribute and the
  documented companion to `service.name`: it is what lets one collector group the
  fleet under a parent instead of listing seven unrelated services. A list that
  carries `service.name` and refuses `service.namespace` carries half of one
  semconv pair.
- **`telemetry.sdk.name`, `telemetry.sdk.language`, `telemetry.sdk.version`** —
  billing sets the first two **by hand** at `lib/kit/telemetry.rb:183-184`, so
  they are not an SDK artefact on billing at all; they are a fact about billing's
  source. And every SDK whose `Resource.create` merges its own default resource
  adds all three whether the caller asked. **Measured, not quoted**:
  `Resource.create({'service.name': 'muse', 'service.namespace': 'cafaye'})`
  against 1.44.0 returns
  `{telemetry.sdk.language, telemetry.sdk.name, telemetry.sdk.version,
  service.instance.id, service.name, service.namespace}` — six attributes, of
  which **four** the closed allowlist refused. A service cannot suppress those
  without opting out of the SDK's defaults, so an allowlist without them does not
  describe a span.
- **Why nothing caught it:** identity builds its resource with
  `resource.NewWithAttributes` (`internal/telemetry/telemetry.go:542`), Go's
  **schemaless** constructor, which does not merge the SDK default resource, and
  courier builds its own resource map (`lib/courier/telemetry.ex:277`) rather than
  letting one be assembled — so those two emit only attributes this list allowed
  and validated. The publishers whose SDK contributes to the resource are the ones
  that failed. A list that is right by accident on half the fleet is
  indistinguishable from a list that is right.

**Choice: add all four to the resource allowlist, on all three signals, and state
in each that an attribute on this list has a recorded publisher.**

**Alternatives:**

1. **Add the four.** A **looser rule**, so a **patch** under `README.md`'s table.
   All four are Stable semconv resource attributes, bounded to one value per
   process, which is the same argument `docs/observability.md` has been making
   for `service.name` being on the resource at all. Rejected as an alternative
   only in the sense that it is the choice.
2. **Refuse them and require muse to drop `service.namespace`.** This is what
   core's rule says on its face — "an attribute that is not on a signal's
   allowlist is not emitted" — so it is not a strawman. Rejected because it does
   not work for `telemetry.sdk.*`: the SDK adds those, and asking a Python service
   to remove them means opting out of the SDK's own defaults, which is a worse
   answer than one sentence of allowlist. For `service.namespace` alone it *would*
   work, and it is rejected for the other reason: core owns the contract, and
   deleting a Stable semconv attribute because one publisher added it early
   punishes the publisher for reading the conventions.
3. **Add only `service.namespace`, because it is the one the packet named.**
   Rejected: it would leave `telemetry.sdk.*` refused, so the same muse span still
   fails `caf contract lint` for three other reasons, and core would have fixed
   one quarter of a defect it had measured in full. Partial fixes to a closed list
   are how a closed list rots.
4. **A tolerated-names list or an exclusion.** Not applicable: these are real
   attributes on a real resource, not spellings to tolerate.

**Recommendation: the choice as built, released as a patch, with all four added to
all three signals rather than the one the packet named.** The part that is worth
restating is the *reason it went unnoticed*, because it generalises: the list was
correct by accident on exactly the publishers whose SDK contributed nothing to
their resource, and a list that is accidentally right is indistinguishable from a
list that is right. The reverse half of the new test is the part that keeps it
from happening again — an attribute can only join the list by arriving with a
named producer beside it, so "the SDK adds it" has to be measured and written
down rather than assumed, which is exactly the reasoning `process.pid` failed and
is why `process.pid` is not here.

**Also closed in this decision, because it was the same list:** the three signals'
resource attribute lists were three copies of one list with **nothing comparing
them** — the defect `test_the_span_name_pattern_is_shared_with_the_traces_schema`
exists to prevent, sitting on the attribute list a service reads its resource
contract out of. `test_the_three_signals_agree_on_the_resource_attribute_allowlist`
now asserts the copies agree, in both directions: the list carries everything the
fleet demonstrably emits and nothing it does not.

**One thing measured and deliberately NOT added: `process.pid`.** billing's
`lib/kit/telemetry.rb:195-199` says `Resource.create` "MERGES with the SDK's own
default resource — so a process still reports `telemetry.sdk.language` and a
`process.pid` even if every one of the keys below is absent". On the installed SDK
that is **false**: measured against `opentelemetry-sdk` 1.13.1,
`Resource.create({'service.name' => 'billing'})` returns exactly
`{"service.name" => "billing"}` — no merge, no `process.pid`. So `process.pid` has
one publisher's prose rather than a publisher's behaviour behind it, and one
service's comment about a default is not evidence that a default exists. billing
owes that comment a correction. It is recorded here rather than left out because
the packet's method is a positive record read from code, and "we checked this and
it is not there" is the half of that record nobody writes down.

**Cost of flipping:** to option 2, delete four properties from three schemas and
tell muse and billing to stop emitting attributes their SDKs emit for them — a
guarantee no library offers and one service would break silently. To option 3,
nothing to reverse; that is what makes it wrong.

**What this cannot do:** it does not prove the Elixir or Go SDKs add the same
three. identity's constructor is schemaless by choice and courier's Erlang
resource is built by the SDK's own configuration, neither of which core-26 ran.
What is recorded is what two publishers emit and one SDK was measured to add, and
the reverse half of the test means a fourth attribute can only join the list by
arriving with a named producer beside it.

## D41: how is the FORCE rule declared, and what may a warning mean in the tenancy checker?

Raised by packet core-tenancy-lint-01, which asked for the failure modes of
tenant isolation to become **detectable** and not the mechanism to be built.
Measured before anything was written: across all nine account-scoped services —
identity, courier, billing, gateway, darkroom, pantry, muse, cafaye-ts, cafaye-rb —
**zero** `ROW LEVEL SECURITY`, **zero** `CREATE POLICY`, **zero**
`NOINHERIT`/`SET ROLE`, and **zero** services declaring a `tenancy.yml`. The
declaration half already existed (`schemas/tenant-isolation.schema.json`,
`docs/tenancy.md`, `harness/tenancy_check.py`); nothing detected the ways
isolation silently fails. Affects
[`schemas/tenant-isolation.schema.json`](schemas/tenant-isolation.schema.json),
[`docs/tenancy.md`](docs/tenancy.md),
[`harness/tenancy_check.py`](harness/tenancy_check.py),
[`harness/tenancy_findings.json`](harness/tenancy_findings.json) and
[`harness/tests/tenancy_self_test.sh`](harness/tests/tenancy_self_test.sh).

**Choice: the database half is a REQUIRED `rls` block in the existing
`tenancy.yml`, `forced` is a `const: true`, the denial shape became THREE cases
with a `const: present` third arm, and every `tenancy.rls-*` finding except one
is a FAILURE.**

The rule the packet exists for: **Postgres does not apply row-level security to a
table's OWNER unless the table is set `FORCE ROW LEVEL SECURITY`.** A service
creates its tables in its own schema and therefore owns them. Verified against
the reference rather than from memory, and the verification is the finding:
Supabase's database advisor — twenty-eight lints and the obvious place to start —
**collects `relforcerowsecurity` for its dashboard's table list and never judges
it.** Postgres documents the behaviour in the CREATE TABLE reference and not in
the row-level-security guide. Cafaye uses `FORCE` zero times today, so this is
free to prevent rather than expensive to retrofit.

**Four sub-decisions, each a place the obvious answer was wrong.**

**1. `forced` is a `const: true`, not a checked boolean, and the DDL check is
`tenancy.rls-owner-bypass`.** The schema cannot see the migrations and the
checker cannot see the schema, so each holds one half and the finding is where
they meet. `const` rather than an enum because `forced: false` IS the bug, and a
format that can *describe* a half-enforced table is a format that will contain
one. Both halves are proved by deletion rather than by construction:
`harness/tests/tenancy_self_test.sh` breakage 18 and
`tests/test_specs.py::test_the_force_rule_is_a_failure_and_survives_the_force_line_being_removed`
each delete the single `alter table assets force row level security;` line and
assert `tenancy.rls-owner-bypass` fires **about that table and about nothing
else**. The "nothing else" is not decoration: `force` and `enable` are separate
`reloptions` bits and neither implies the other, which is what lets one finding be
proved by one deletion instead of by a diff that moved two things.

**2. The denial shape became three cases, and the third is a `const: present`.**
The packet's own argument: "does an unauthenticated request fail" is satisfied by
a table with no policy at all, which is the bug. So `negative.cases` is exactly
`no-identity` / `other-account` / `own-account` — and the third asserts that the
account's own credential **sees its rows**, because two denial arms are satisfied
perfectly and forever by a service that returns nothing to anybody. Answering the
third arm with the language's spelling of nothing is
`tenancy.positive-control-refused`, a FAILURE.

**3. Every `tenancy.rls-*` finding is a FAILURE except `tenancy.rls-unreadable`.**
This overrides a convention the three pre-existing warnings are built on, so it
needs the reasoning written down. Those three all mean *this machine cannot
answer that question*, and a warning that does not move the exit code exists
because failing on it would get the checker disabled — which would leave the
fleet with **no** boundary check instead of an incomplete one. That argument does
not transfer to facts that are fully decidable from the migration text. A
severity nobody chose is not a severity. Concretely, this is why
`tenancy.rls-per-row` is a failure and not the `WARN`/`PERFORMANCE` Supabase
gives the same lint: the wrapped-`(select …)` rule is 100% decidable by reading
`0002_rls.sql`. The one warning is `tenancy.rls-unreadable` — RLS DDL found in a
file this checker cannot parse, which is the honest "I cannot settle this" claim,
and it fires on a Rails service's `.rb` migrations.

**4. The advisor is a ledger, not a copy, and `FORCE` has no row in it.**
`docs/tenancy.md` carries all twenty-eight lints, each marked adopted, adapted or
left out with a reason, between two marker comments that
`test_the_row_level_security_rules_are_adopted_and_the_exclusions_are_written_down`
reads: a missing lint fails, a row naming no finding fails, and **a row saying
`left out` with an empty reason fails.** A rule examined and excluded on purpose
is a decision; the same rule excluded silently is the defect this packet exists to
stop. And `tenancy.rls-owner-bypass` has no row in that table, because it has no
Supabase ancestor and "adopted from Supabase" would claim a credit that does not
exist.

**Alternatives:**

1. **A new `rls.yml` and a new `harness/rls_check.py` with its own inventory.**
   Rejected: a second declaration file per service is a second thing to forget,
   and core's inventory story is already three files deep (`rules.json`,
   `gate_findings.json`, `tenancy_findings.json`). Extending the one declaration
   and the one checker keeps the migration cost at one edit per service and the
   proof cost at one more breakage in one more script. This is also what the
   packet asked for — *extend it, do not rebuild it*.
2. **Require RLS everywhere.** Rejected, and this is the packet's own scope
   line: the isolation mechanism belongs to a parallel `kit` worker, and a
   service whose repository scopes every statement is correct by construction.
   `databaseEnforced: false` with `tables: []` is the honest answer for the whole
   fleet today, and it is a **required** field — a claim, checked, with
   `tenancy.rls-undeclared` firing the moment a migration disagrees — rather than
   an omission.
3. **Leave `negative` as one assertion and put the three arms in the doc.**
   Rejected, and it is the reason this sub-decision is here: with one assertion
   the shape *reads as covered* while the arm with all the information in it is
   the one nobody writes. That is the whole defect.
4. **Keep `expects`/`file`/`line` and add `cases` beside them.** Rejected: two
   copies of one constraint with nothing comparing them, which is the drift core
   exists to end.
5. **`roles` may include `public`, with a warning.** Rejected: with one named
   runtime role there is no case where `PUBLIC` is the right answer, and a warning
   about it is a warning everybody learns to ignore. It is a `not`, and the DDL
   half (`tenancy.rls-permissive`, for a policy naming no role at all) is a
   failure.
6. **Derive `identity` from the fleet's three tenancy-key vocabularies.**
   Rejected for the reason D33 rejected inference: three vocabularies already, and
   a checker that picks one is guessing at the boundary rather than at the data.
   A service names its own `identity` and every policy must carry it.

**Recommendation: the choice as built.** The one place to revisit first is
`identity`'s `()` requirement. It exists so a policy's identity call can be
hoisted out of the row loop, and it rules out
`current_setting('app.account_id')` — a perfectly ordinary Postgres idiom that
several services will reach for. The alternative is a second identity form on
`rls.policies[].constrained`, which is one schema property, one checker branch
and one more thing to get right.

**Cost of flipping:** the three-way shape is the expensive one. Reverting
`negative.cases` to a single triple means deleting one `$defs` block, restoring
`expects`/`file`/`line`, deleting `tenancy.positive-control-refused` and its two
breakages, and rewriting five examples — and `version` stays `1`, so a reader
holding a v1 declaration written against the new shape gets a confusing set of
errors rather than a clean refusal. **That last point is a real defect and it is
recorded rather than hidden: the format was published at `^0.2.0` with the old
shape and changed under it.** It was done because the fleet has **zero**
adopters — the declaration is unread by every repository in it today, so the
migration cost is this repository and nothing else — and because the alternative
is leaving a published contract that documents a shape nobody should use. Bumping
`version` to `2` would make the break loud rather than confusing and is the
manager's call, not a worker's; the flip is one `const` in the schema and one in
`harness/tenancy_check.py`.
---

## D42: is a denial arm's SHAPE part of the contract, and who owns the vocabulary of six languages?

Raised by packet core-negative-01, which measured which of Postgres's three
cross-tenant denial shapes the fleet actually proves. Affects
[`harness/tenancy_check.py`](harness/tenancy_check.py),
[`harness/tenancy_findings.json`](harness/tenancy_findings.json),
[`schemas/tenant-isolation.schema.json`](schemas/tenant-isolation.schema.json)
and [`docs/tenancy.md`](docs/tenancy.md).

**Measured first, because a decision about a gap is not a measurement of it.**
Four mutations of `harness/tests/fixtures/tenancy/conforming/`, each a real
service writing something `docs/tenancy.md` forbids:

| what a service writes | the checker said |
| --- | --- |
| a `select` denial arm as `assert_raises` | 0 failures, exit 0 |
| an `update` denial arm as a bare `assert_equal 0` | 0 failures, exit 0 |
| an `own-account` write arm proven with `lives_ok` | 0 failures, exit 0 |
| an `own-account` arm proven with `nil` | refused |

So three of the four were open, and the one that was closed was the **positive**
arm. What core enforced was "do not claim absence where you claim presence", and
what it did not enforce was "match the assertion to the clause that denies you" —
which is the `using` shape, the one that raises nothing, and the common one.

**Choice: the shape IS part of the contract, as two findings decided from the
declaration plus the one line it names — `tenancy.denial-shape` and
`tenancy.denial-unpaired`.**

**Alternatives:** and why they lost.

1. **A schema `enum` for `expects` per operation.** Loses on the existing
   constraint `test_the_three_way_denial_shape_is_required_on_every_entry_point`
   asserts: `expects` is a pattern because "the vocabulary of six languages is not
   core's to close". An enum is that closure, done badly, in a published format.
2. **The reference proposal: pure pgTAP, one `.sql` file per RLS'd table,
   identical for all six languages, with `cafaye/tests/_helpers.sql` and
   `set local role` + `set local request.jwt.claim.sub` for impersonation.** This
   is the right destination and it is NOT this packet's job — it is migrating six
   languages. It is also, today, unreachable from here: `core` has no Postgres,
   and `harness/` may not take a dependency or open a connection. Recorded as the
   successor's first line rather than sketched.
3. **Doc-only — say it in `docs/tenancy.md` and move on.** Loses on core's one
   rule: a rule that is not in `schemas/` or the harness is a wish. The doc
   already carried the table; the table was simply not enforced.

**The one open question, stated rather than resolved: `operation: call`.** A
repository method's scoping is enforced above the statement, and this checker
cannot see which clause does the denying — so `call` is deliberately OUTSIDE both
`USING_DENIED_OPERATIONS` and `WRITE_OPERATIONS` and neither finding fires on it.
That is a refusal to guess, and it is also a real hole: a service that declares
every entry point as `call` gets no shape check at all. The cheapest form of
closing it is for `call` to carry the clause it is enforced by, which is one
enum on the entry point; the cost is a change to a published format at `version:
1` with one adopter, which is the same trade D41 recorded and is the manager's
call.

**What was NOT done, with the reason.** The reference's `authenticate_as`,
`authenticate_as_service_role`, `clear_authentication` and `freeze_time` helpers
are not here. They live in kit's template, which already carries the equivalent
(`pg_temp.cafaye_as`, `pg_temp.cafaye_observed`) and whose `isolation.sql` proves
all three shapes against a live cluster on every `kit/tests/tenancy_test.sh` run.
Duplicating them here would be a second copy to keep in step — the four-way drift
`harness/` exists to end — and this packet changed **no mechanism**, so a copy
embedded in a service (identity embeds one; `migrations/00017` refreshed a
function in it today) picks up nothing new and needs no action.

**The vocabulary is a closed list of what this checker KNOWS is wrong, not of
what is right.** An unrecognised token passes, and the measured consequence is
that an `update` denial arm declared as a bare `assert_equal 0` is accepted: it
counts zero rows, so it is not proof the row is intact. It is the first entry in
`harness/tenancy_findings.json`'s `notEnforced` list. The alternative — a rule
that can only fire on English-language identifiers — gets disabled within one
release and leaves the fleet with no check at all, which is the argument
`docs/tenancy.md` already makes under the honest-zero heading. What is enforced
is the direction with no good spelling in any language: every ABSENCE token is
refused on a denied write, because "nothing came back" is a claim about a row
that exists.

**Recommendation:** ship the two findings as they are, and take the `call` gap to
the manager as part of the pgTAP migration rather than as its own packet. The
shape check is most valuable exactly where the mechanism is enforced in the
database — `select`/`update`/`delete` statements — and that is where kit's live
`isolation.sql` already runs on every `tests/tenancy_test.sh`. A `call` entry
point is the *application's* boundary, enforced above the statement, and proving
its shape needs the test to run, which is the gate's job in the service rather
than a checker's job in core.

**Cost of flipping:** two directions, both cheap and both one edit:

- *Close the `call` hole.* Add one optional enum to the entry point naming the
  clause `call` is enforced by, fold `call` into `USING_DENIED_OPERATIONS` when
  it says `using`, and add a breakage. It is a change to a published format at
  `version: 1` with one adopter (identity), which is the same trade D41 recorded
  and the reason the call was left to the manager.
- *Drop either finding.* Delete the entry from `harness/tenancy_findings.json`
  and the code — the suite asserts the two sets are equal in both directions, so
  removing one without the other is a red rather than a silent loss. Costs the
  three shapes two of their four red proofs, and the measurement table in
  `docs/tenancy.md` goes back to describing a wish.

---

## D43: is a value that one language cannot represent a FINDING, and where do the numeric vocabularies live?

Raised by packet core-numeric-01, whose hazard is the one that breaks cafaye's
thesis: a value correct in the language that wrote it and silently wrong in the
language that read it. Affects
[`harness/numeric_check.py`](harness/numeric_check.py),
[`harness/bin/numeric-check`](harness/bin/numeric-check),
[`harness/tests/numeric_self_test.sh`](harness/tests/numeric_self_test.sh),
[`docs/numeric-conventions.md`](docs/numeric-conventions.md),
[`gate.yml`](gate.yml) and [`bin/prime`](bin/prime).

**Measured first, because a decision about a gap is not a measurement of it.**
Core's own contract surface is 31 numeric positions and 2 numeric enums; the
seven service OpenAPI specs add 66 more and 1 more enum. Every number below was
printed by `numeric-check --survey`, not counted by hand:

| rule | core's `schemas/` | the 7 service specs | severity chosen |
| --- | --- | --- | --- |
| `numeric.float64-unsafe` | **0** | **6** | **FINDING** |
| `numeric.float` | 2 | 0 | **WARNING** |
| `numeric.enum` | 2 | 1 | **WARNING** |
| `numeric.unsigned` | 45 | — | **NOT ENFORCED** |

**The number that drove this: one rule fires on zero of core's 31 positions.**
That is what lets `numeric.float64-unsafe` be a failure. A rule that fires on
every existing field is a rule that is disabled within one release, which leaves
the fleet with NO check rather than an incomplete one — the same conclusion
[`REPORT-core-negative-01.md` §5 reached about a different rule, and D42 wrote
down for the same reason.

**Choice: where each vocabulary lives is in the CHECKER, for all four rules.**

A JSON Schema can say `type: integer` and `maximum: 9007199254740991`. It cannot
ask whether a line of TypeScript holds an `int`, whether a Go `uint64` survived a
JSON round trip, or whether an enum is one a client may add to. Those are facts
about *languages*, and no keyword expresses them — which is the same reason
`harness/tenancy_check.py` keeps `RAISING_TOKENS` / `LIVENESS_TOKENS` /
`ABSENCE_TOKENS` in the checker rather than in `tenant-isolation.schema.json`.

**Choice, in one line: `numeric.float64-unsafe` is a FINDING, `numeric.float` and
`numeric.enum` are WARNINGS, `numeric.unsigned` is NOT ENFORCED, and all four
vocabularies live in the checker rather than in a schema.** The rest of this
entry is why, and what it costs to reverse.

**The cost of putting a vocabulary in the checker is duplication, and core's rule
makes duplication a TEST.** Two tests carry it here:

- `test_the_float64_limit_is_stated_once_in_the_checker_and_agrees_with_the_doc` —
  2^53 is one constant, the first unrepresentable value is derived as `+1` rather
  than typed, no third literal is hardcoded beside them, and the integer appears
  in the checker, in `--explain`, and in `docs/numeric-conventions.md`.
- `test_the_numeric_identity_names_are_declared_once_and_the_ledger_says_why` —
  `IDENTITY_NAME_TOKENS` is the sharpest form of the problem (a schema cannot tell
  a `byte_size` from a `retry_count`), so it is asserted non-empty,
  duplicate-free, and present in the doc, because a service author must be able to
  predict what will be refused *before* writing the field.

**Alternatives:** and why they lost.

1. **Make all four failures, and fix the 2 float positions.** Loses on the
   measurement: `slo.objective` and `slo-windows.factor` are *ratios*, and a ratio
   that cannot be a whole number is not a rounding bug. Failing them means either
   red on core's own contract today, or inventing a scaled-integer rewrite of the
   SLO schemas inside a packet about the checker — a format change at
   `version: 1` with the fleet's adopters already reading it.
2. **Warn on `numeric.float64-unsafe` too, on the argument that 6 of 97 fleet
   positions hit it.** Loses on the direction of that number: it is 6, not 6 of
   31, and 4 of the 6 are `created` / `byte_size` / `iat` / `exp` — unbounded
   integers on identity-named fields, which is precisely the case the reference
   says must be a string. Six findings against 97 fields is a signal; 45 (the
   unsigned case) is noise, and noise is what gets a checker switched off.
3. **Enforce `numeric.unsigned`.** Loses twice. It fires on 45 of 97 numeric
   positions, all of them counts, amounts in minor units and status codes — the
   fleet's own vocabulary. And it is **structurally invisible in any document**:
   there is no unsigned integer type in JSON at all, Go has no unsigned JSON,
   TypeScript has no unsigned number, and Python's `bool` **is** an `int`. It is
   enforceable only in a service's own types, which is the successor's first move.
4. **Put the float64 limit in the schema as `maximum`.** Loses on what a
   maximum *means*: it would forbid the value rather than require the string, so a
   schema could catch `snowflake_id` and could never catch the writer that
   produces 2^53 + 1 anyway. And it would put the number in a place that
   `test_schemas_declare_draft_2020_12` meta-validates, where the language fact
   would read as a format fact.

**Recommendation: keep all four as they are, and spend the next packet on the two
things this one cannot do — rewriting the two SLO float fields as scaled
integers, and getting the 6 adopter findings fixed in the services that own
them.** The reason to recommend no change at all is that the measured cost of the
status quo is *two warnings on two ratio fields that are correct*, and the
measured cost of a wrong-sized rule is a checker that gets switched off — which
is strictly worse than no checker.

**Recommendation to the manager, and this is the part that is genuinely open:**
whether `slo.objective` becomes `objective_milli` is a change to two published
schemas under the fleet's adopters, so **the manager decides it, not this
packet.** My recommendation is to do it, and to do it in one commit that also
promotes `numeric.float` to a failure — because a scaled integer that nothing
requires is a convention, and core's own rule is that a convention with no test
is documentation of a wish. **Cost of deferring it:** the two fields stay
warnings, which is a state that is honest today and quietly wrong the moment
somebody adds a float field whose values are not a ratio.

**What the two float fields should do instead, since that is the interesting
case.** The reference's "cannot be reliably round-tripped" does apply, but a
ratio whose values are always a multiple of 1/1000 is defensible and these are
not that — they are continuous. The envelope's own convention is the answer:
**a scaled integer**, and `docs/numeric-conventions.md` states it as
`objective_milli: {type: integer, minimum: 1, maximum: 1000}`. Sloth's
`prometheus/v1` block needs a fraction, so the *declaration* keeps one; what must
be an integer is anything a client reads and re-emits. That rewrite is **owed and
not done**, deliberately: it changes `slo.schema.json` and `slo-windows.schema.json`
under the fleet's adopters, and that is the manager's call, not a numeric
checker's.

**Cost of flipping:** two directions, both cheap and both one edit.

- *Promote `numeric.float` to a failure.* Change one severity constant and
  `bin/prime` goes red on core's own two SLO fields — which is the point, and
  means the SLO rewrite lands in the same commit or not at all.
- *Demote `numeric.float64-unsafe` to a warning.* One constant. Costs the fleet
  the only *enforced* rule in this checker, and leaves a hazard that bites one
  language and not five as a comment.

## D44: is an enum member past the float64 exact range a FAILURE, or a WARNING?

Raised by packet core-numeric-enum-53-01, whose gap is that
`numeric.float64-unsafe` decided itself from `maximum` and from an identity-shaped
NAME, and a field that is both `type: integer` and an `enum` reaches neither:
`walk()` files it in TWO lists, carries neither the members nor the name into the
position, and the enum list produced one `numeric.enum` WARNING about evolution.
Affects
[`harness/numeric_check.py`](harness/numeric_check.py),
[`harness/tests/numeric_self_test.sh`](harness/tests/numeric_self_test.sh),
[`docs/numeric-conventions.md`](docs/numeric-conventions.md) and
[`tests/test_specs.py`](tests/test_specs.py).

**Measured first, on the unedited tree, because a decision about a gap is not a
measurement of it.** `harness/numeric_check.py` against a scratch document, the
exit code printed:

| what the document said | what the checker said | exit |
| --- | --- | --- |
| `enum: [0, 1, 9007199254740993]` | `numeric.enum` warning | 0 |
| `enum: [-9007199254740993, 0]` | `numeric.enum` warning | 0 |
| `enum: [0, 9007199254740993]`, no `type` at all | `numeric.enum` warning | 0 |

9007199254740993 is 2^53 + 1. `JSON.stringify` in TypeScript rounds it, so every
`Number()` round trip through a generated client returns 9007199254740992, and
the only finding on the node was about *evolution*. The second row is the answer
to a question this packet was told to measure rather than assume:
**`float64_unsafe()` as written does NOT catch the negative member**, and the
reason is structural — it reads `maximum`, which is ONE NUMBER, and an enum is a
SET. There was no signed-comparison subtlety to find; there was no comparison at
all.

**Choice:** an integer enum with any member past the float64 exact
range is `numeric.float64-unsafe` at FAILURE, sharing the id rather than becoming a
fifth rule; the comparison is by MAGNITUDE; the declared `maximum` reports and the
enum yields where a node has both; and `numeric.enum` stays a WARNING on the same
node.**

**Why FAILURE and not a new warning.** An enum is a STRONGER statement than a
maximum, not a weaker one. A maximum *bounds a range*: it says how big the value
may get, and a writer that stays inside it produces nothing a reader cannot hold,
so the hazard is real but prospective. An enum *enumerates the complete set of
legal values*, so a member past the limit is not a possibility the contract
tolerates — it is a value the contract REQUIRES, and every one of those values is
a value a JavaScript client silently rounds. The distinction this checker draws
everywhere is *can this value cross the wire wrong*, and this one can, by one.

**Why the same id rather than `numeric.enum-unsafe`.** Two ids for one hazard is
one more thing to classify, and the classification is already done elsewhere:
`numeric.enum` is about evolution ("adding one is NOT a compatible change"),
`numeric.float64-unsafe` is about a value that is wrong today. One node can be
both, so it now carries both findings — an unrepresentable value AND a closed
union, which are two true statements about it rather than two copies of one.
Promoting `numeric.enum` itself is explicitly out of scope and would go red on
core's own three numeric enums and the fleet's one.

**Measured, the new trigger fires on nothing that exists.** Per service spec, and
over core's own `schemas/`: 6 `numeric.float64-unsafe` findings across the fleet
— the same six D43 recorded in June — of which **0** come from the enum branch, and
core's own surface is 0 failures / 4 warnings / 31 positions, unchanged. A
failure-severity rule that fires on zero of what exists can be a failure; one that
fires on everything gets switched off within a release and leaves the fleet with
no check.

**Alternatives:** and why they lost.

1. **A new id, `numeric.enum-unsafe`, at failure.** Loses on the taxonomy, not on
   the severity: it is a fifth id for the same hazard the fourth already covers,
   and the next reader has to learn which of two float64 rules applies to their
   field. Sharing the id means one grep finds every value that crosses the wire
   wrong, whatever shape declared it.
2. **Fold the enum members into the position dict and widen
   `float64_unsafe()`.** Loses on reach. `walk()` only files a node in
   `positions` when its `types` include `integer` or `number`, so
   `{"enum": [0, 9007199254740993]}` — legal draft 2020-12, no `type` at all —
   is in `enums` and not in `positions`, and no amount of widening a
   position-shaped rule can see it. Measured: silent today. The branch therefore
   lives where the two lists meet, in `check()`.
3. **Let the enum report and suppress the `maximum`.** Loses on the direction of
   the risk. The `maximum` branch is the one that already existed, so suppressing
   it is the edit that can lose a finding nobody re-reads; suppressing a NEW
   second copy of an id that was already there cannot. It is also
   `harness/reserved_check.py`'s `_cross_service_pairs` rule — a `reported` set,
   one finding per node, because a finding printed twice reads as two problems
   where there is one.
4. **Fire at `>=` in both branches, for symmetry.** This was the closest call and
   it is worth writing down rather than leaving as an implementation detail.
   2^53 = 9007199254740992 **is** exactly representable — `JSON.stringify` of it
   returns `"9007199254740992"` and `JSON.parse` of that returns 2^53 — so an
   enum whose largest member sits ON the boundary is a document that is correct,
   and refusing it is refusing a correct document. The `maximum` branch already
   fires at `>=` and is one value conservative; that is a published rule with a
   red proof behind it (case (1) of the numeric self-test) and it was left alone,
   so the two branches differ by exactly one value. **That difference is
   deliberate and it is the one asymmetry in this entry.** The cost is that a
   reader comparing the two branches has to be told; the mitigation is that
   `docs/numeric-conventions.md` says it in words, `enum_float64_unsafe()`'s
   docstring says it, and cases (11) and (13) are greens sitting exactly on the
   boundary from both directions so a future edit to either operator goes red.
5. **Widen the `maximum` branch to `abs()` while we are here.** Loses on scope
   and on the same boundary. It would close a real and separately-measured hole —
   `maximum: -9007199254740993` is silent today, because the comparison is
   signed — but `abs(maximum) >= FLOAT64_EXACT_LIMIT` is `maximum >=
   FLOAT64_EXACT_LIMIT` *union* `maximum <= -FLOAT64_EXACT_LIMIT`, so it would
   fire on `-9007199254740992`, which is exactly representable, while the enum
   branch stays silent on it. That trades a documented asymmetry for an
   undocumented one. The hole is named in
   `REPORT-core-numeric-enum-53-01.md` §6 with the one-line change, and it is
   not this packet's.

**Recommendation: keep the branch where it is, and spend the next packet on the
thing this one deliberately did not do — forbid 53-bit enum members in
`manifest.schema.json`.** That is a different and much larger claim: it would
change the SCHEMA rather than the checker, it applies to a different document,
and it would make the value unpublishable rather than merely refused at review.
Written up rather than built, in the report's last section.

**Cost of flipping:** three directions, all cheap and all one edit.

- *Demote the enum branch to a warning.* Change `_FAILURE` to `_WARNING` in the
  enum arm of `check()`. Costs the fleet the only enforced rule in this checker
  and puts the hazard back where it was: a value a TypeScript client cannot hold,
  reported as an opinion about evolution.
- *Promote `numeric.enum` to a failure.* One constant, and `bin/prime` goes red
  on core's own three numeric enums plus the fleet's one — which is the point,
  and means the closed-union rewrite lands in the same commit or not at all.
- *Make the `maximum` branch agree with the enum branch at the boundary* (i.e.
  `> ` rather than `>=`). One operator, and it reds case (1) of the numeric
  self-test, so it is a change to a published rule rather than to this packet.

## D45: should a chain the checker cannot follow say so, or be silent?

Raised by packet core-hono-inline-01, whose finding is that `scoping-bypassed` now
refuses to accuse a route behind a mount whose middleware is defined in ANOTHER
MODULE — and says nothing at all while refusing. Affects
[`harness/account_scope_check.py`](harness/account_scope_check.py),
[`harness/account_scope_findings.json`](harness/account_scope_findings.json),
[`harness/tests/account_scope_self_test.sh`](harness/tests/account_scope_self_test.sh),
[`docs/account-scope.md`](docs/account-scope.md) and
[`tests/test_specs.py`](tests/test_specs.py).

**Measured first.** `harness/tests/fixtures/account-scope/hono_composed` mounts a
sub-application: `app.route("/v1", v1())` in `src/index.ts`, `api.use("/*",
accountGate)` in `src/api.ts`, and `accountGate` calls `requireJwt` in
`src/middleware/gate.ts`. The route's own file says neither `requireJwt` nor
anything about scoping, so:

| what the reader does | what it says about `GET /me`, which IS behind a gate | exit |
| --- | --- | --- |
| reads only the registration line (before this packet) | `scoping-bypassed` — the wolf | 1 |
| reads the chain, cannot follow it (now) | nothing | 0 |

0 occurrences of this shape in the fleet's seven services, and the same file carries
the other measured gap: `app.route("/v1", v1())` is read as axum's `.route(path,
handler)` and becomes `undeclared` against `/v1`.

**Choice: silent, deliberately, and recorded.** The row is not accused because
`scoping-bypassed` is a failure and a false one on a correct route is the defect that
gets this finding switched off — the argument is already written down on
`Recogniser.carries_handler`, and this packet is the measurement of it. Silence is
therefore right for the FINDING. Whether silence is right for the ROW is the open
half, and it is open because the honest alternatives are both worse today:

**Alternatives:**

- *A new warning, `account-scope.chain-unreadable`, on every row behind a mount this
  checker cannot follow.* The correct shape — `contradiction-unreadable` is the same
  answer for the other half of the format, and "I could not check this" is not a
  pass. Against it: a warning that fires on **0 of the 61 rows** this fleet declares
  today is a warning nobody will ever read, and a warning nobody reads is worse than
  the silence it replaces because it looks like coverage.
- *Report it as `account-scope.scoping-bypassed` and let the reader adjudicate.* That
  is the behaviour this packet removed, and removing it is the packet.
- *Follow the chain into the other module*, resolving `accountGate` through
  `module_index` the way `handler_for` resolves a handler, and then one hop through
  `gate.ts`. That is the fix that removes the question, and it is a larger claim than
  this packet: `_hops` is deliberately capped at ONE hop, and a chain reader is a
  second traversal with its own evidence rules.

**Recommendation: leave it silent for now, and spend the next packet on the option
that removes the question rather than the one that describes it** — resolving the
mounted middleware through the module index, which turns "I cannot see it" into a
verdict. Until then the gap is in `notEnforced` with these numbers, so a reader is
told rather than left to discover, and the fixture that measures it is committed.

**Cost of flipping:**

- *Add the warning.* A new entry in `FINDINGS`, the same entry in
  `harness/account_scope_findings.json`, a severity the inventory and every test that
  compares the two must agree on, and a case in the red proof that goes red when it is
  deleted. Roughly the shape of `account-scope.registration-commented`. Cheap, and it
  buys a warning that measures 0 on this fleet.
- *Follow the chain.* `_hops`-style resolution plus a second evidence rule for what a
  middleware may do. Larger, and it is the version that makes the question disappear.

---

## D46: what does a registration whose path prefix cannot be evaluated produce, and what may a warning mean about the surface?

Raised by packet core-unresolvable-path-01, whose finding is that `pantry`'s four
registrations are `r.Get(options.BaseURL+"<literal>", …)` and the chi recogniser drops
all of them — so `undeclared` reads **0** over a surface the checker saw none of, and
`get-service` reads `stale`, a FAILURE about a route that is mounted. Affects
[`harness/account_scope_check.py`](harness/account_scope_check.py),
[`harness/account_scope_findings.json`](harness/account_scope_findings.json),
[`harness/tests/account_scope_self_test.sh`](harness/tests/account_scope_self_test.sh),
[`docs/account-scope.md`](docs/account-scope.md) and
[`tests/test_specs.py`](tests/test_specs.py). It is the surface-level companion of
[D45](#d45-should-a-chain-the-checker-cannot-follow-say-so-or-be-silent) and the
conclusion is the opposite one, for a measured reason.

**Measured first, on pantry's own tree and not on the numbers in the packet.** The
brief quotes `api.gen.go:707,710,713,716`; pantry's checkout has moved and the four
routes are now six, at `:852,855,858,861,864,867`, with a declaration of six rows.
`REPORT-core-unresolvable-path-01.md` re-derives every number in it, because a number
copied from a report is the defect this repository keeps refusing.

| | before | after |
| --- | --- | --- |
| `pantry` | exit 1, `1 stale`, `0 undeclared` — 7 warnings | **exit 0**, `0 stale`, `0 undeclared, 6 unreadable` — 9 warnings |
| `identity` | exit 0, 1 warning | exit 0, **3** warnings |
| `gateway` / `site` / `parlor` / `courier` | exit 0 | exit 0, `0 unreadable` |
| `caf` / `kit` / `core` | exit 1, `declaration-missing` | exit 1, unchanged |

**Choice: it produces a WARNING and a NUMBER, and never a path.** Two findings and one
count, because a reader can read the findings block or the last line and both have to
say it:

- `account-scope.surface-unreadable`, per FILE, naming the lines and how many of the
  registrations in `surface.sources` were read.
- `account-scope.registration-path-unreadable`, per ROW, replacing the false `stale`.
- a fifth number on the summary line, **printed on every run**.

**Alternatives:** the three, and why each was refused.

- *Match on the literal tail* — produce `"/v1/services/{name}"` from
  `options.BaseURL+"/v1/services/{name}"`. This is the guess the hono packet rejected
  and it is worse here, because the prefix is a deployment's configuration: the
  resulting path is a claim about what the service serves, derived from what it does
  not. `pantry/account_scope.yml` §3 also documents the concrete damage — the
  alternative spelling `/v1/services/name` exits 0 and is a route pantry does not
  serve, and three of six rows go green by the accident that their last segment is a
  substring of their own line.
- *Report it as `undeclared`.* A claim about the DECLARATION, and pantry's declaration
  covers all six routes. This is crying wolf on a correct declaration, which is the
  failure mode [D45](#d45-should-a-chain-the-checker-cannot-follow-say-so-or-be-silent)
  measured and the one that gets a guard switched off — and it is the argument written
  down on `Recogniser.carries_handler` in the first place.
- *Leave it, and say so with the argument sharpened.* `pantry` would stay permanently
  uncheckable, which is a real state and belongs in `notEnforced` rather than in
  another packet.

**Three decisions inside the choice, each with its own reason:**

- **`surface.minimum` still counts only what was READ.** Folding unreadable
  registrations into it would turn pantry's exit 1 into an exit 0 with `minimum: 6` and
  **no warning at all** — a coverage number manufactured out of routes nobody saw.
  Self-test case 55 exists to fail if anyone tries, and it is green on both sides of
  this packet on purpose.
- **The count is printed always, not only when non-zero.** An omitted number cannot be
  told from a computed zero, and a checker that can print a wrong zero about its own
  coverage is worse than one that prints nothing. Self-test case 58 is the copy that
  prints `0 unreadable` over a fixture with four.
- **A `const` prefix gets the SAME warning.** `probePrefix` and `socialLoginPrefix`
  have their values in their trees and `options.BaseURL` does not, and a rule that
  behaved differently for the const would be a rule that guesses harder when the value
  happens to be lying next to it. This **extends**
  `REPORT-core-hono-inline-01.md` §3 rather than reversing it; case 57 puts the const
  on a declared row and requires the same answer.

**Recommendation: ship it, and spend the next packet on the option that removes the
question rather than the one that describes it** — resolving an identifier's value
through the module index, which turns "I cannot read this path" into a path for the 9
`const` routes this checker cannot see in any form. It does **not** close `pantry`'s,
because `options.BaseURL` has no value in any tree; §3 is the measurement of that and no
amount of work in the recogniser changes it. Until then both halves are in `notEnforced`
with their counts, and both carry a warning, so a reader is told rather than left to
discover.

**Cost of flipping:**

- *To the literal tail.* Delete `unreadable_registrations` and route the chi recogniser
  at `concatenated_path` from the first `/`-prefixed literal wherever it appears. Two
  lines, and the price is a path this checker invented — plus the
  `oidc.go:1269` regression the hono packet measured, which a re-run would rediscover.
- *To `undeclared`.* Move `Surface.unreadable` into `Surface.found` with a `{}` prefix.
  One line, and pantry exits 1 on a declaration that is correct.
- *To a failure.* Change two severities in `FINDINGS` and four rows in
  `account_scope_findings.json`. Cheap, and it gets the checker switched off fleet-wide
  — which is the argument `harness/tenancy_check.py` already makes in its own header
  for the same class of warning.

# core-26 — three places core's schemas and real publishers disagree

**Branch:** `worker/core-26`
**Gate:** `bin/prime` green at **244/244** (was 236); red proof 18/18, 0 skipped.
Both entry points agree — `tests/.venv/bin/python -m pytest tests/test_specs.py`
prints `244 passed` and `bin/prime --pytest` collects 244.

Three of core-25's loose ends. Each one is a statement about the world rather than
about core's taste, so none of them is closed with a tolerated-names list or an
exclusion: each was settled by reading a publisher's own source at a named commit,
and each record says which file and which commit.

---

## 1. `courier.email.queued` — the publisher is missing, not misnamed → **D38**

The packet asked core to check one thing before concluding anything: whether
courier really does have a queued transition under another name. It does not, and
the way that is established matters more than the conclusion.

`lib/courier/events.ex` at courier's `master` HEAD **`ae8a660`** still defines
`delivered/1`, `bounced/1`, `complained/1` and `suppressed/1` and **still has no
`queued/1`**. `a8f15cc` — the commit `fleet.yml` records, and a reachable
ancestor of that HEAD — is identical on this point.

Three further facts, because *"no builder"* and *"misnamed builder"* are different
answers and only the state machine separates them:

1. **courier says so in courier's own words.** `events.ex`'s moduledoc at that
   HEAD: *"`courier.email.queued` has no builder because courier has no queue. The
   send path is synchronous and documented as such — the provider is dialled inside
   the request — and that type exists to make a **backlog** visible. With no
   backlog there is no moment at which courier could honestly emit it."*
   `AGENTS.md` and `cafaye.yml` repeat it, and `AGENTS.md` records that
   `Courier.Workers` and `oban` exist and lost on one stated requirement: a 202
   would answer before the suppression check has run.
2. **There is no queued state to have been misnamed.** courier's one state machine
   is `Courier.Suppressions`, states `nil | :undeliverable | :suppressed` (the
   fold at `suppressions.ex:38-41`, `state/1` at 236-247). The one bounded queue
   courier owns is the **error relay's** (`lib/courier/error_relay/sender.ex`) —
   error reports to GlitchTip, nothing to do with mail.
3. **Acceptance and `courier.email.delivered` are the same moment.**
   `Courier.Deliver` mints `message_id = "courier-" <> Ecto.UUID.generate()` and
   dials the provider inside the open transaction, and `record/4` writes the
   delivered row in that same transaction (`deliver.ex:196` at that HEAD). There is
   no *earlier* event to publish, which is why the backlog this type would report
   is structurally zero rather than merely unmeasured.

**Decision: it stays, recorded as `declared-and-unimplemented`** — `fleet.yml`'s
own phrase, already there — and the standing is now in the schema's
`description`, not only in its `$comment`. Deletion was rejected **on correctness,
not on cost**: a declared type with no payload schema is exactly what D34's
`pendingCoreContract` is for, and that list means *the service publishes it*.
courier does not. Deletion would convert an honest gap into a lie in the opposite
direction, and D34 rejected its option 4 for the same reason.

**The real defect core-25 left behind was smaller and worse than the one the
packet named: a fact living in `$comment`.** `jsonschema` ignores `$comment`,
`cafe contract lint` ignores it, and an editor's hover shows `description`. So
`courier.email.queued` had an honest, fully-cited admission that **nobody could
see**, and a `description` asserting "Emitted on acceptance, not on send, so a
queue backlog is visible" as though it were a fact. That is now one rule with two
instances, and it is closed.

## 2. billing's subscription payloads — a disagreement in BOTH directions → **D39**

**core's documents were wrong, and the wrongness is larger than core-25 recorded.**
`examples/invalid/README.md` row 2 said billing "has no subscriptions table, so it
has no `sub_…`, `pln_…` or `acc_…` to send", and `subscription/started`'s
`description` said "There is no cafaye `plan_id` or `account_id` here, because
billing has no subscriptions table". billing grew
`db/migrate/20260930000007_create_subscriptions.rb` and
`Subscriptions::Lifecycle#core_payload/1` (`lifecycle.rb:353`) now writes
`plan_id` and `account_id` as **bare uuids** onto all three subscription payloads.
billing asserts the exact key set itself (`lifecycle_test.rb:264-271`).

So all three schemas — closed with `additionalProperties: false` — reject fields
every real event carries **and** require fields they never receive:

| | rejected, but emitted | required, but never emitted |
| --- | --- | --- |
| `subscription.started` | `plan_id`, `account_id`, `currency`, `started_at` | `processor`, `processor_event_id`, `kind`, `customer_id` |
| `subscription.updated` / `.canceled` | `plan_id`, `account_id`, `currency`, `processor_subscription_id`, `trial_ends_at` while trialing | `kind`, `customer_id` |

**A real `billing.subscription.started` does not validate against core's schema for
it**, and it did not start by accident of a value. `processor` and
`processor_event_id` *are* emitted on the update and cancellation paths, by
`detail_payload` rather than `core_payload` — which is why the three payloads are
**no longer one shape**, a fact `updated`'s `description` also asserted.

**D10 was right when written and has gone stale, and that is a different
correction from the decision having been wrong.** Its Choice still holds — the
fields are still not cafaye-prefixed, `sub_…` is still the processor's id, and
`Identifiers::UUID` is still case-insensitive on purpose — and its own
**Cost of flipping** predicted this verbatim: *"when billing grows a subscriptions
table, the shape moves again … that is a second breaking change."* It moved. So
D10 gets a dated **Update** paragraph (the D34 convention) and **its words are not
rewritten**: a decision record is a record of a decision, and editing the words it
was made with would erase the fact that it was sound on the day and the world
moved afterwards.

**Decision: core's claims are corrected now; the three schemas are not rewritten
here.** Every document in core that said billing has no such fields is corrected
in this commit, and each schema now says in its `description` — not only its
`$comment` — that it does not describe what its publisher emits, with the emitted
key set, the source lines and the commit beside it. The rewrite is **drafted in
D39 and left to the manager**, because D35's remedy ("rewrite it to reality")
only *loosened* a pattern and deleted three optional properties, whereas this one
**deletes four `required` properties shipped since v0.2** across three of the
fleet's busiest types, and partly reverses the replacement D10 made. That is a
decision about what `billing.subscription.*` means on the bus, not a
transcription. Telling billing to drop the two fields — the other available move —
is refused outright: a spec cannot make a publisher's payload smaller, and
`lifecycle.rb:339-341` names them as "the two fields that make a subscription
event actionable at all".

billing has known both halves for some time: `PENDING_PAYLOAD_ALIGNMENT`
(`test/contract/outbox_envelope_contract_test.rb:66-88`) is asserted in both
directions, and `lifecycle.rb:320-343` records that core's schemas "describe a
different payload, and this is recorded rather than matched" and that "when core
decides, the change lands here and in the contract test together". So this is a
known, owned, two-sided gap and not an incident — which is why the right response
is a decision and not a panic.

## 3. muse's `service.namespace` — the allowlist is missing the field → **D40**

**Answer: the allowlist is missing fields the fleet demonstrably uses.** Not one —
four, and the fourth is why the first three went unnoticed.

- **`service.namespace`** is muse's, set **by hand** at
  `src/muse/telemetry.py:390` and asserted in `tests/test_resilience_config.py:355`.
  Stable OTel semconv, the documented companion to `service.name`. A list carrying
  `service.name` and refusing `service.namespace` carries half of one semconv pair.
- **`telemetry.sdk.name` / `.language` / `.version`** — billing sets the first two
  **by hand** at `lib/kit/telemetry.rb:183-184`, so on billing they are not an SDK
  artefact at all. And every SDK whose `Resource.create` merges its own default
  resource adds all three whether the caller asks. **Measured, not quoted**:
  against **opentelemetry-sdk 1.44.0** in muse's own `.venv`,
  `Resource.create({'service.name': 'muse', 'service.namespace': 'cafaye'})`
  returns
  `{telemetry.sdk.language, telemetry.sdk.name, telemetry.sdk.version,
  service.instance.id, service.name, service.namespace}` — six attributes, and the
  closed list **refused four of them**. A service cannot suppress those without
  opting out of its SDK's defaults, so a list without them does not describe a span.
- **Why nothing caught it:** identity builds its resource with
  `resource.NewWithAttributes` (`internal/telemetry/telemetry.go:542`), Go's
  **schemaless** constructor, which does not merge the SDK default resource, and
  courier builds its own resource map (`lib/courier/telemetry.ex:277`) rather than
  letting one be assembled — so those two emit only attributes the list allowed
  and **validated**. The publishers whose SDK contributes to the resource are the
  ones that failed. A list that is right by accident on half the fleet is
  indistinguishable from a list that is right.

All four are added to all three signals. **A looser rule, therefore a PATCH** under
`README.md`'s table, and stated as one in the CHANGELOG. `span.muse.json`'s
resource now carries what a real muse span carries.

The same packet also closed the hole that let the drift in: the three signals'
resource attribute lists were **three copies of one list with nothing comparing
them** — the defect `test_the_span_name_pattern_is_shared_with_the_traces_schema`
prevents, sitting on the attribute list a service reads its resource contract out
of. Asserted in both directions, so a fifth attribute can only join by arriving
with a named producer beside it.

## The fourth finding, and the fifth thing deliberately not done

Reading courier properly to answer question 1 turned up a sentence in core that
was **false in the same paragraph** the packet pointed at:
`courier.notification.suppressed` **has a caller now.** `Courier.Unsubscribes.publish/1`
(`lib/courier/unsubscribes.ex:479-495`) writes its `outbox_events` row in the same
transaction as the `notification_preferences` row that turned the type off, with
`reason: preference_off`, the subject set to the user and no `message_id` — core's
D8, and field-for-field the four fields
`schemas/events/courier/notification/suppressed.schema.json` **already required**.
So courier publishes **four of five**, not three, and both `fleet.yml` and
`docs/event-naming.md` said three. The schema needed no change — which is what
writing its citation carefully in the first place was for. courier still does not
publish it for a *refused* send, and says so in its own source.

**`process.pid` is deliberately NOT on the allowlist, and that is the interesting
half.** billing's `lib/kit/telemetry.rb:195-199` says `Resource.create` "MERGES
with the SDK's own default resource — so a process still reports
`telemetry.sdk.language` and a `process.pid` even if every one of the keys below
is absent". On the installed SDK that is **false**: measured against
`opentelemetry-sdk` **1.13.1**, `Resource.create({'service.name' => 'billing'})`
returns exactly `{"service.name" => "billing"}` — no merge, no `process.pid`. So
`process.pid` has one publisher's *prose* rather than a publisher's *behaviour*
behind it, and one service's comment about a default is not evidence that a default
exists. Recorded rather than left out, because "we checked this and it is not
there" is the half of a positive record nobody writes down.

## Two choices made rather than asked about

**`fleet.yml`'s courier `sourceCommit` was NOT moved** to `ae8a660`, even though
the prose now describes that commit. core-26 read `lib/courier/events.ex`,
`lib/courier/unsubscribes.ex` and `lib/courier/deliver.ex` — and confirmed the
three live payloads are unchanged in shape, `deliver.ex`'s `data/4` at HEAD being
the same four fields and `inbound_reports.ex` being byte-identical between the two
commits. It did **not** re-read courier's OpenAPI document, its telemetry
configuration or the rest of its surface. Moving the pin would claim a whole-registry
re-read nobody did, which is the invented-provenance failure D35 was. So the entry
now says out loud that its `sourceCommit` is behind the commit its prose
describes, and the next courier packet closes it. That is the state D36's remedy
exists for.

**The billing schema rewrite is drafted, not taken.** Stated above; the drafted
default, the six files it implies, and the paired billing PR are all in D39.

## New checks — red proofs done, not assumed

Eight new tests, floor **236 → 244**. Every rule below was shown going red **on
this repository's own files**, naming the exact schema or example, then restored.

| Defect reintroduced | What went red, and what it said |
|---|---|
| `declared-and-unimplemented` removed from the courier schema's `description`, left in `$comment` — **the actual defect** | `test_a_standing_against_a_publisher_is_stated_where_a_reader_sees_it`: *"a payload schema says in `$comment` that its publisher does not exist … and says nothing of the kind in the `description` a consumer's tooling actually shows"* |
| the marker removed from the file entirely | `test_the_standing_vocabulary_is_not_a_pair_of_words_nothing_uses` — a vocabulary nothing claims is a rule that cannot fail |
| `service.namespace` taken off `traces.schema.json`'s resource **only** | `test_the_three_signals_agree_on_the_resource_attribute_allowlist`, naming **all three lists** side by side |
| courier's ledger `at` drifted off `fleet.yml`'s `sourceCommit` | `test_the_producer_ledger_is_read_at_the_commit_the_registry_records`: *"the producer ledger and the fleet registry disagree about which commit each service was read at, so every id shape below is a claim about bytes nobody recorded"* |

Two rules were green on arrival and are guarded by witnesses that were shown to
have teeth on their own subjects: the standing rule's witness (it asserts the
shipped file passes before asserting the mutated one fails) and the resource
witness (it asserts `span.muse.json` validates as shipped, then that taking
`service.namespace` off the list makes that same example fail naming the
attribute). Both fail loudly if their fixture drifts, which is the failure mode a
witness is most often written to hide.

## Decisions

- **[D38](DECISIONS.md#d38-does-a-declared-event-type-with-no-builder-stay-in-core-or-leave)** — declared event type with no builder: **stays**, as
  `declared-and-unimplemented`, in `description` as well as `$comment`.
- **[D39](DECISIONS.md#d39-does-a-payload-schema-follow-its-publisher-when-the-publisher-has-grown-the-feature-the-schema-predicted-it-would-not)** — billing's
  subscription schemas: **core's claims corrected now, the rewrite drafted and left
  to the manager.** Records the emitted key sets, both directions, with shas.
- **[D40](DECISIONS.md#d40-is-the-resource-allowlist-missing-a-field-the-fleet-uses-or-is-a-service-emitting-something-it-should-not)** — resource allowlist:
  **missing four fields**, added to all three signals, released as a **patch**.
- **[D10](DECISIONS.md#d10-billingsubscriptionstarteds-payload-schema-no-longer-describes-cafaye-ids)** gains a dated **Update** — right when written,
  stale now, and D10's own cost-of-flipping line predicted it.

### Open decisions

**None new**, and no `> DECISION NEEDED (Dn):` callout was added anywhere.
`test_no_open_decision_callouts_remain_in_the_docs` scans `docs/*.md` and a
callout there fails the build, so the one genuinely open question — D39's schema
rewrite — is written as a numbered decision with its alternatives, a drafted
default and the cost of flipping, which is what that test's own failure message
asks for. **D39 is the one item the manager has to rule on**, and ruling on it
means putting one question to billing: is the subscriptions-table payload final,
or provisional?

## What each service needs, with shas and paths

Nothing outside `core` was edited. `identity`, `courier`, `billing` and `muse`
were read; `git show` at the recorded commits where a working tree had moved.

- **courier** (`master` HEAD `ae8a660`, recorded `a8f15cc`): nothing owed.
  `courier.email.queued` needs a builder **and** a caller; `AGENTS.md:353` already
  argues the queue design and says why it lost.
- **billing** (`7251993`, still HEAD): two comments are now known false.
  `lib/kit/telemetry.rb:195-199` claims `Resource.create` merges the SDK's
  default resource and reports a `process.pid`; on SDK 1.13.1 it does neither.
  Its own contract test names `billing.subscription.started` "the fields core's
  schema names" (`lifecycle_test.rb:264`) and core's schema has not named them
  since D10 — that test comment is stale for the same reason `fleet.yml` was.
- **muse** (`53b6ebb`, still HEAD): nothing owed. It set `service.namespace`
  correctly all along; core was the side that was wrong.

## Reported, not fixed — outside this packet

- **`fleet.yml`'s courier `sourceCommit` is behind its own prose** (§ above).
  courier has added `lib/courier/principal/introspection/document.ex`,
  `secret_box.ex` and `unsubscribe_token.ex` since `a8f15cc`, so its `api:` pointer
  and its telemetry note are both owed a re-read. A whole-registry re-read is a
  courier packet; core-26 moved the prose as far as its own evidence reaches and
  said so in the file.
- **`span.muse.json` and the twelve `error-type.*.json` examples carry three
  resource attributes muse does not emit** (`service.version`,
  `service.instance.id`, `deployment.environment`). `_resource/1` sets
  `service.name` and `service.namespace` and nothing else. core-25 removed
  `tenant_id` from them and recorded the *id* facts; the non-id ones were never in
  scope, and `RESOURCE_ATTRIBUTE_SHAPES` tracks identifiers only. Making thirteen
  examples say what muse actually emits is its own packet — and note that
  `service.namespace` being *added* by this packet makes those examples marginally
  truer, not less true, which is why it was not deferred.
- **courier's `Courier.Telemetry.resource/0` is computed but never wired into
  `config :opentelemetry`.** `sdk_config/0` does not carry `:resource` and
  `config/runtime.exs:72` writes only `sdk_config()`. The only caller is courier's
  own `span_collector.ex:155`. Whether courier's SDK-level spans therefore carry
  `telemetry.sdk.*` was **not** verified — the `:opentelemetry` deps are not
  vendored and core-26 did not boot the app — so no claim is made either way, and
  core's allowlist now permits them either way.
- **billing's `error.type` vocabulary** is still three values of its own and none
  is in core's thirteen (`fleet.yml`, recorded by core-22). Unchanged by this
  packet and billing's to fix.

## What I did not do

- **Did not push, merge to `master`, or tag.** Committed to `worker/core-26` only.
- **Edited nothing outside `core`.** No service repository was touched, and no
  excluded name was added to any list — every fix is a schema constraint, a
  document, or a test.
- **Did not move courier's `sourceCommit`** although the prose is now ahead of it,
  because the re-read behind that prose is three files rather than a registry.
- **Did not rewrite billing's three schemas.** Drafted in D39 with the six files
  and the paired billing PR enumerated; taken by the manager or not.
- **Did not loosen an assertion.** The gate floor went **up** (236 → 244). No test
  was skipped, no `if` added, no assertion relaxed to reach green. The only test
  that went red and stayed red was the **floor ratchet**, which is designed to and
  which was answered by raising the number.
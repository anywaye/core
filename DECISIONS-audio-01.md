# DECISIONS — core-audio-01

**A proposal, not a decision. Nothing here has been ruled.** Two questions that
are core's to settle before any service builds the audio plane, stated with the
options, the evidence and a recommendation each. The status of both is
**awaiting a ruling from the manager**, and the rulings needed are listed at the
end under [Awaiting a ruling](#awaiting-a-ruling).

**This is a packet-scoped record and it does not touch `DECISIONS.md`.** That
follows `DECISIONS-breaking-tiers-01.md` and `DECISIONS-reserved-tombstone-01.md`,
which both left the master file alone because the numbering there is the
manager's. It also does not take a `Dnn` of its own: those two predecessors
numbered themselves D43–D45 and D44–D47, and every one of those numbers already
belongs to a different decision in [`DECISIONS.md`](DECISIONS.md) (D43–D46) — so
reusing the sequence here would put two decisions under one citation, which is
exactly what `test_open_decisions_are_numbered_and_complete` exists to prevent.
A number is claimed when the ruling lands, in the same commit as the schema
change it authorises.

**Nothing in this record is enforced.** No schema, no document, no example and
no test changed with it. A question nobody has answered cannot be a rule, and a
proposal that edited the convention would hide its own existence from the reader
who comes back to check whether the question is still open.

---

## Q1: what are the capability scopes for speech and transcription?

### The question, precisely

A routed completion today requires a scope whose **resource** names that service's
own surface. `muse` requires `completions:write`
(`muse/src/muse/auth.py:88`, one constant, and its own docstring at `:81-88` calls
the name "provisional … a public API decision in the same family as the claim
name"). `darkroom` requires `assets:read` / `assets:write`, read off its own
`openapi/v1.yaml` (`darkroom/internal/auth/middleware.go:148-159`). identity's own
seven are read off its own routes (`identity/internal/apikeys/apikeys.go:135-269`).

The **shape** is core's and is stated: `resource:action`, lower case, in
[`docs/openapi-conventions.md:137`](docs/openapi-conventions.md) —
"`scopes` for capability (`invoices:write`)". That is a *grammar*, and every one
of the three services above honours it without disagreement.

**The vocabulary is not core's, and the packet's premise is worth stating exactly
because it is not.** identity mints a closed list of seven
(`apikeys.go:276-282`), `IsSupportedScope` is an exact-match membership test
(`:288-290`), and `TestAllScopesAreInCoreShape` only checks the *shape*
(`internal/apikeys/apikeys_test.go:254-268`). Nothing in core constrains what a
resource may be *called*, and `openapi-conventions.md` says nothing about who may
extend it. So the honest reading is: core owns the **grammar**, and the resource
names are each service's own surface — which is exactly what identity's block
says at `apikeys.go:143-146` ("THE SHAPE IS core's … The names are this service's
own surface, read off `openapi/v1.yaml` rather than invented").

**What core does own is the part the packet names**, and that part is load-bearing
downstream: a scope that appears in a **published payload schema** is carried
forever. `schemas/events/identity/api_key/created.schema.json:35-42` pins the
grant as a closed `enum` of six scope strings, and
[`examples/invalid/README.md:184`](examples/invalid/README.md) is the negative case
proving it — `accounts:admin` is refused rather than coerced to `accounts:read`,
because "a CI job that asks for `accounts:admin` and silently receives
`accounts:read` is a script that runs for a week and fails on the write it was
written to do."

So the decision is not "may audio have scopes". It is narrower and sharper:

> **Whose surface names the audio capability, and what happens to a published
> enum when the answer changes?**

### Evidence that constrains each candidate

| fact | where | what it forecloses |
|---|---|---|
| Scope shape is `resource:action`, lower case, no wildcard | `docs/openapi-conventions.md:137`; `identity/internal/apikeys/apikeys_test.go:254-268` (`TestAllScopesAreInCoreShape`), `:270-284` (`TestNoScopeGrantsEverything`) | `audio`, `tts*`, `speech*` as bare resources are legal in shape; `*` and `admin` never are |
| **The resource names the service's own surface, not the modality** | `muse` reads `completions:write` off a route named `/v1/route`; `darkroom` reads `assets:*` off `/v1/assets`; identity's seven are all identity routes | naming by modality (`audio:write`) puts a word in the resource that names no route on any service |
| A scope is refused unless it is in the issuer's closed list | `identity/internal/apikeys/apikeys.go:288-290`; `apikeys_test.go:238-252` requires every scope in `AllScopes()` to have a route listed in the test | a scope audio mints that identity cannot grant is unissuable on the only issuer in the fleet |
| Every scope in the vocabulary must be enforced on ≥1 route | `identity/internal/apikeys/apikeys_test.go:240-251` — a scope with no route fails as "a comment with a type" | a scope minted for a capability no route gates is a promise about the future, not a control |
| No scope grants tenancy | `apikeys.go:194-198`; mirrored in `schemas/events/identity/api_key/created.schema.json:14` | `audio:*` never carries an account. `account_id` does that, separately |
| A granted scope travels on the wire in a closed enum | `schemas/events/identity/api_key/created.schema.json:35-42` | adding an audio name is a **core release to a published payload schema**, not a one-line addition to a Go const |
| The enum has a negative case with a stated reason | `examples/invalid/README.md:184`; `examples/invalid/events/identity/api_key/created.data.json:4` | the enum is enforced, so widening it is a visible diff with a stated reason |
| `openapi-conventions.md` is capped at ~2 pages | `AGENTS.md`, "Editing docs" | the answer belongs in this record and later in `openapi-conventions.md`, not in a new document |
| Two claim names, `scopes` and `scope`, are still unruled | `muse/src/muse/auth.py:24-35` | a naming decision here compounds an open one rather than settling it |

### The candidates

**A. `speech:write` / `transcription:write`** — resource names the modality.

The strongest argument for it is that it is *self-explanatory to somebody reading
a token*. A human holding a list of grants sees `speech:write` and knows what the
credential can do without opening the issuer's route table. That is real, and it
is the argument the OIDC `SupportedScopes` list already answers to differently
(`identity/internal/oidc/scopes.go:35-51` — `openid`, `email`, `profile`,
`accounts`, `publish`: modality-flavoured, and a *different vocabulary for a
different thing*).

The argument against is the one the evidence table makes strongest: **the resource
names the service's own surface in three of three implementations in this fleet,
and none of them has a modality in it.** `completions` is what muse's route
produces, `assets` is what darkroom's route touches, `accounts` is what identity's
routes touch. A modality resource is the first case where the resource names
something *no route is named after*, which means a client cannot derive the
required scope by reading the endpoint it is about to call — which is the one thing
all three of them make easy today.

Cost of being wrong: low and cheap. Two more constants in one service, and if the
fleet later converges on surface-shaped names, the enum in
`identity/api_key/created.schema.json` has two more members to remove — a
**major** core release, because removing an `enum` member a published event has
carried is the "field removed" row of
[`docs/event-naming.md:118-123`](docs/event-naming.md).

**B. `completions:write` for speech, a new `transcriptions:write` for transcription
— extend muse's own surface.** *(the recommendation)*

Speech-to-text and text-to-speech are the same *capability* the token already
bought: "ask the model plane for a completion." Transcribing is not that — it
takes bytes in and returns text, has no prompt, and is billed on a different unit,
so it is a different resource.

The argument is that **B is the smallest answer that keeps the existing invariant
true**: a route's required scope is derivable from the route, every name in the
vocabulary is enforced somewhere, and one new name is added rather than a new
vocabulary introduced. It also matches what identity's own block says a scope is
for — "it names something this service actually does, and removing it removes
access to something that exists" (`apikeys.go:137-141`).

The argument against is real: **it over-loading `completions:write` to mean
"speech too" makes the name stop describing the thing**, and a credential granted
`completions:write` for chat would silently gain audio spend. A caller reading the
grant list would have no way to tell that a token it thought was cheap can now be
made expensive per-second. The honest reading of that objection is that **B needs
the separate scope for the second direction too** — `speech:write` and
`transcriptions:write` as two new names on muse's surface — which converges on C.

Cost of being wrong: one extra constant in one service, and zero core changes,
because neither name is in a published payload until identity's enum is widened —
which is a separate, later, deliberate commit.

**C. A modality resource per modality: `speech:write`, `transcriptions:write`,
`embeddings:write`** — the OIDC-style list, extended to capabilities.

The argument for it is that it scales past audio. The moment there are five
capability planes there is a list, a list wants a namespace, and the namespace
wants to be a scope resource. identity already maintains exactly such a list for
OIDC (`internal/oidc/scopes.go:51`), so the fleet has both shapes on disk and C is
the one that has somewhere to go.

The argument against is that **it is a decision about six capabilities made in a
packet about two**, and the cost of the first wrong name is a published enum
member. `openapi-conventions.md` is capped at two pages for exactly this reason.

Cost of being wrong: highest of the three, and it is the only one that costs core
a released change when it turns out wrong.

### Recommendation: **B, with the second name separate** — `speech:write` and
`transcriptions:write`, both naming muse's own surface, no modality resource

**Reasoning.** The evidence is one-directional: in three of three implementations
the resource names the service's own surface, a scope with no route behind it is a
test failure in identity (`apikeys_test.go:240-251`), and the shape is the only
thing core has ever constrained. B keeps that invariant true and adds exactly the
names the routes need.

**The one-line override.** If the ruling prefers A or C, the change is *the value
of the constants* — `muse/src/muse/auth.py:88` is one line per name, and nothing
else in muse depends on the spelling. The expensive part is not muse; it is
widening the enum at `schemas/events/identity/api_key/created.schema.json:35-42`,
and that cost is the same under every candidate. So the cheap way to flip this is
to rule *before* identity mints the names.

**Cost of being wrong under the recommendation:** two constants that have to be
renamed, in one repository, before any of them is published on the wire. Lowest of
the three, and the only one where being wrong costs nothing outside the service
that made the choice.

### Not decided here

**Whether audio is muse's surface at all.** This record assumes the audio plane is
muse's, because that is the service that meters (`src/muse/metering.py:1-34`) and
the one whose route is `/v1/route`. **Whether audio belongs to a new service is
`fleet.yml`'s question, and this packet does not edit `fleet.yml`** — no service is
added or changed here. If the answer is a new service, Q1's answer becomes that
service's surface name and the reasoning above still holds, because it is about the
*shape* of the argument rather than the service.

---

## Q2: how is non-token usage metered and published?

### The question, precisely

The existing usage event is `muse.tokens.consumed`, and its payload schema is
**closed**. `schemas/events/muse/tokens/consumed.schema.json:7-8` is
`additionalProperties: false` with `required` at exactly five fields — `model`,
`provider`, `tokens_in`, `tokens_out`, `cost_micros` — and the `description` at
`:5` states the reason in the packet's own words: *"Exactly five fields, because a
payload schema is closed and a field added now is one a future schema carries
forever."*

**Audio has no token count.** Transcription is billed per minute or per second of
audio; synthesis per character or per second of output. Neither `tokens_in` nor
`tokens_out` has a meaning. `cost_micros` does survive — it is an integer in
micro-dollars and is the one field that works unchanged for any modality
(`consumed.schema.json:30-33`) — but the **quantity** the cost was derived from
does not, and a consumer that cannot re-derive or even see the quantity cannot
reconcile an invoice.

So the question is:

> **What shape carries "this account was billed for 92 seconds of audio" onto the
> bus, given that the one event type that means "usage" is closed at five token
> fields?**

### Evidence that constrains each candidate

| fact | where | what it costs a candidate |
|---|---|---|
| `muse.tokens.consumed`'s `data` is closed at five token-shaped fields | `schemas/events/muse/tokens/consumed.schema.json:7-8`, and `:5` says why | every option except C is a change to a published, closed payload |
| The cost figure travels rather than being recomputed | `consumed.schema.json:30-33` — "A consumer that re-derives it and disagrees has found a real bug" | any shape that drops `cost_micros` in favour of "quantity + price table" is a **regression** against a stated property |
| A new optional field is a patch; a new required field is a minor | [`docs/event-naming.md:114-115`](docs/event-naming.md), cross-referenced at `:124-125` | adding `seconds` as optional is cheap; adding it as required is a minor release |
| A removed or retyped field is a **major** release and a new type | same table, `:116` | overloading `tokens_in` with seconds is the worst available move, and is listed here so it is visibly rejected |
| A publisher that wants a breaking payload change ships a new `type` and deprecates the old | `docs/event-naming.md:126-128` | this is the argument for A, and it is the repo's own rule rather than a preference |
| Every event type is `<service>.<entity>.<action>`, three segments, prefixed | `AGENTS.md`; `schemas/event-envelope.schema.json`; `docs/event-naming.md:66`; the machine-checked form is the `eventType` pattern (`:19`) | the entity for audio must be a noun that survives one directory segment. `transcription` does; `synthesize` and `stt` do not |
| The action vocabulary is closed for v0 and "anything else is a manager decision" | `docs/event-naming.md:100-108` — `recorded` and `completed` are **in** it; `transcribed` and `synthesized` are **not** | A and B need either an existing action or a vocabulary extension, which is a second ruling |
| The `usage.recorded` row already promises "quantity + window" | `docs/event-naming.md:275` — `billing.usage.recorded`, "Metered usage is accepted for a period; `data` carries quantity + window" | there is already an aggregator-facing event with a period and a quantity, and audio has to arrive in a shape that can aggregate into it |
| Content must never be recorded — and `transcript` is on the list | `docs/observability.md:110-112` (the twelve words), `:243-244` ("May never be recorded"); `schemas/telemetry/redaction.schema.json:49` | a transcription event **must not carry the transcribed text**. This is the strongest single constraint in this question and it is already decided |
| `platform` is the reserved subject literal for an entity-less event | `consumed.schema.json:5`; `docs/event-naming.md:328` | audio usage keeps the same subject problem, and D9's answer (add `account_id` to the payload) applies here too |
| billing consumes nothing yet | `grep -rn "muse\|consumed" billing/app billing/lib` returns **0 lines** at billing's `master` HEAD `0f936a4` (fleet.yml records `sourceCommit: 72519931`, so billing has moved on; the grep is this packet's, at HEAD, and says so) | the downstream consumer is **unwritten**. "What a consumer would have to do" is therefore a design cost, not a measured migration — and this is said rather than assumed |

### The candidates

**A. A new event type per audio modality: `muse.transcription.recorded`,
`speech.synthesized` — *(`muse.audio.recorded` is the single-type variant)***

The argument for it is the repo's own evolution rule: a removed or retyped field is
a major release, and "a publisher that wants a make a breaking payload change
ships a new `type` and deprecates the old one" (`docs/event-naming.md:128-130`).
Under A, `muse.tokens.consumed` is **untouched** — no consumer of it can break,
and no one has to re-vendor a schema that a hundred completions already validate
against.

The argument against: two new types means two new payload schemas, two rows in the
event catalog, two entries in `fleet.yml`'s `events` for muse the day it
publishes, and — the part that actually hurts — **two actions the closed
vocabulary does not contain**. `recorded` and `completed` are in it;
`transcribed` and `synthesized` are not (`docs/event-naming.md:100-108`), and
extending that list is a manager decision this packet cannot take. A is also the
option most likely to need a fourth type the day someone bills per character for
one modality and per second for the other.

Cost to consumers: **zero migration, one new subscription per consumer that wants
audio.** An aggregator subscribes to three types instead of one and sums them.

**B. Extend `muse.tokens.consumed` with per-modality optional fields:**
`audio_seconds`, `characters`, `modality`.

The argument for it is that a consumer wants *one* place to sum spend, and one
type with a `modality` discriminator is easier to aggregate than three types with
three shapes. The optional fields are a **patch** under the evolution table.

The argument against is stated in the schema's own words and is the reason to
reject it: *"Exactly five fields, because a payload schema is closed and a field
added now is one a future schema carries forever"* (`consumed.schema.json:5`). It
also puts `tokens_in: 0` on an audio event, which is a lie a consumer must be
taught to read — and core has already been taught this lesson once, in
[`D35`](DECISIONS.md) (a payload schema that required a field its only publisher
does not emit) and again in `D39`. **A usage event that says "zero tokens" about a
92-second transcription is the same defect in a new place.**

Cost to consumers: **a schema re-vendor and a changed `required` question** for
every existing consumer, and each new modality a field carried forever.

**C. A generalised usage payload — `quantity` + `unit` + `cost_micros`, and
`muse.tokens.consumed` becomes a special case of it.**

The argument for it is that it is the *only* candidate whose shape does not have
to change again for a modality nobody has thought of. Tokens are a unit. Seconds
are a unit. Characters are a unit. One `unit` field with a closed vocabulary and
one integer `quantity` covers all of them and the next three modalities, and
`cost_micros` — the one field already right — survives untouched.

The argument against is that it is the biggest change and it lands on the busiest
type in the fleet: it changes what `tokens_in` means for every existing consumer,
or it adds a second shape to a type that is documented as having one. Core already
had this exact argument about two payload shapes on one type and resolved it as a
`oneOf` with one valid example per shape
([`D11`](DECISIONS.md), `billing.payment.succeeded`; the rule is at
`docs/event-naming.md:418-422`), so C is not unprecedented — it is just early.

Cost to consumers: **the largest migration of the three**, and the only one where
a consumer that hard-codes `tokens_in` needs a code change rather than a new
subscription.

### Recommendation: **A — a new event type, never a widening of
`muse.tokens.consumed`**

**Reasoning.** Three reasons, and the third decides it.

1. **The rule already exists and says this.**
   [`docs/event-naming.md:126-128`](docs/event-naming.md): a publisher wanting a
   breaking payload change ships a new `type`. Audio is not a variation on "a
   completion", it is a different quantity on a different axis, and the repo has a
   mechanism for exactly that.
2. **`muse.tokens.consumed` must not acquire an audio-shaped field.** Every reason
   in the schema's own `description` (`consumed.schema.json:5`) applies, and
   `tokens_in: 0` on a billed transcription is the D35 defect wearing a new hat.
3. **The downstream consumer does not exist yet.** `grep -rn "muse\|consumed"`
   over billing's `app/` and `lib/` returns **0 lines** at its `master` HEAD
   `0f936a4`. So "what a consumer would have to do" is
   currently a *choice about the first implementation* rather than a migration —
   and the cheapest first implementation is a new type. This is the reason that
   decides it, and it is measured, not assumed; it is also the reason to re-decide
   C later rather than reject it forever. Once a consumer exists and sums three
   types, the cost of generalising is real and knowable.

**The one-line override.** To B or C instead: the change is one branch in the
payload-schema decision, not a schema edit — **this record lands no schema**, so
nothing has to be undone. What costs the same under every candidate is the later
commit that adds a payload schema plus a valid example, a negative example, a
catalog row and a `fleet.yml` entry.

**Cost of being wrong:** under A, two event types a consumer subscribed to that
turn out to be one. That is a subscription change, additive, and no published
payload changes meaning. **It is the only candidate whose being-wrong costs no
schema release at all.**

### The two sub-rulings A depends on, which the manager must make with it

- **The action word.** `recorded` and `completed` are in the closed v0 vocabulary;
  `transcribed` and `synthesized` are not. Either reuse `recorded` (one type per
  modality, distinguished by the entity) or extend the vocabulary — which is
  itself a manager decision at `docs/event-naming.md:102`.
- **The entity word.** It must be a noun, because the grammar is
  `<service>.<entity>.<action>`. `transcription` and `speech` both work;
  `synthesize` and `stt` do not, because they are verbs and abbreviations in the
  same position.

### One thing A does **not** fix, and D9 still owns

`muse.tokens.consumed` publishes `subject: platform` because a v1 auth stub read
no token, and the payload has no `account_id`
(`consumed.schema.json:5`; [`docs/event-naming.md:328`](docs/event-naming.md);
[`D9`](DECISIONS.md)). muse has known better since muse-06 — `require_bearer`
refuses a token without an `account_id` — and still cannot write it, for the
reason `muse/src/muse/metering.py:20-33` gives: core owns the schema and a
service publishing an account onto the envelope is publishing a contract core has
not agreed to.

**Any audio usage event inherits this.** The cheapest moment to fix it is *now*,
while the type does not exist: an audio usage type published with `account_id` in
`data` costs nothing, and the same fix applied to `muse.tokens.consumed` later is
a change to a payload consumers already read. **That is a third ruling and it is
listed as one below** — it is not folded into the recommendation because it
changes a shipped type rather than adding a new one.

---

## Awaiting a ruling

Four questions, each with the recommendation beside it so any of them can be
overruled in one line.

1. **Q1 — the scope vocabulary.** Are the audio capability scopes
   `speech:write` and `transcriptions:write`, naming **muse's own surface**
   (recommended), or a modality resource `audio:write`? The deciding sub-question
   the ruling must also answer: **is the resource half of a scope a surface name
   or a modality name?** Everything else follows from that. Recommended: surface,
   because three of three implementations in this fleet name a surface, and because
   a resource naming no route is a scope with no route behind it.

2. **Q1b — whose surface.** If audio is not muse's, this is `fleet.yml`'s
   question and no answer to Q1 survives it. Recommended: decide this **before**
   Q1, because the surface name is the resource name.

3. **Q2 — the usage shape.** A new event type per audio modality (recommended, and
   `muse.tokens.consumed` is never widened), a generalised `quantity`+`unit`
   payload, or per-modality fields on the existing type? Recommended: the new type,
   on the evidence that billing consumes nothing today so the first aggregator can
   be written against the cheap shape — and on the rule at
   `docs/event-naming.md:126-128`.

4. **Q3 — the action word and the account.** If Q2 lands as a new type: `recorded`
   reused or the v0 action vocabulary extended, and **does the new type carry
   `account_id` in `data` while it is cheap to add, or does it inherit D9's gap?**
   Recommended: carry it. Adding it now is free; adding it to a shipped type later
   is a patch release consumers re-vendor.

**What this packet deliberately does not decide.** Whether audio is a new service.
Whether a modality belongs in the resource half of a scope. Whether the action
vocabulary grows. All three are manager calls, and this record's job was to reach
them with options priced rather than to make them.

---

## The tree

| file | what |
|---|---|
| `DECISIONS-audio-01.md` | this record — two questions, four candidates priced, a recommendation each |
| everything else | **unchanged** — no schema, no doc, no example, no test, no `fleet.yml` |

Sibling repositories were read, not modified, each at the `master` HEAD it was
read at: `identity` `c228393`, `muse` `51145ba`, `darkroom` `2a43344`, `billing`
`0f936a4` (the last for the negative grep on `muse.tokens.consumed`, which is
0 lines). **Nothing in any of them was written.**
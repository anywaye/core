# REPORT — core-billing-payload-alignment-01: the recipient and the plan name on billing's money events

**Branch:** `worker/core-w46-billingpayload`
**Landed:** `b8ae8fb69c2baec83ec536a8d2af08832bd7b316` (on `83661ff`, the test-first commit)
**Gate:** `bin/prime` green — 300/300 passed, 0 failures, all red proofs pass (floor raised 299 → 300 in the same commit).

## What this packet is for

billing's W43 (`billing@7133643`, pushed 2026-10-07) added the facts a mail
needs to the fleet's money events: `email` on `billing.payment.succeeded` and
`billing.payment.failed`, and `email` + `plan_name` on
`billing.subscription.started` / `.updated` / `.canceled`. billing recorded
the gap against core rather than matching it — five entries in
`PENDING_PAYLOAD_ALIGNMENT` (asserted in both directions) and a DECISION NEEDED
in `cafaye.yml` — because core's payload schemas are closed with
`additionalProperties: false` and did not declare the fields. Every money event
was a field the spec refused, and courier (the fleet's only consumer, which acts
on the envelope and never looks up) could not mail any of them.

This packet is core deciding. It declares the fields on the five schemas, so
billing can drop the pending entries and courier can subscribe.

## What moved in core

- **The five payload schemas** under `schemas/events/billing/`:
  - `payment/succeeded.schema.json` and `payment/failed.schema.json` gain
    `email` — optional, never null, `format: email`.
  - `subscription/started.schema.json`, `subscription/updated.schema.json`,
    `subscription/canceled.schema.json` gain `email` and `plan_name` —
    `plan_name` required, `minLength: 1`.
- **Provenance.** All eight billing payload schemas now cite
  `7133643d8eebb4dd5de2d8df34c7ba20fda89f79`. The five money-event schemas were
  re-read at that commit (their producers changed: `StripeEvents.with_recipient`
  and `Subscriptions::Lifecycle#core_payload`). The three catalogue schemas
  (`customer/created`, `plan/created`, `plan/updated`) were re-read at the same
  commit and **confirmed unchanged**: `Customer#as_json` and `Plan#as_json` are
  byte-identical between `7251993` and `7133643`, verified by diff. All eight
  had to move together because `provenance_faults` requires every billing
  schema to cite the same commit `fleet.yml` records as billing's
  `sourceCommit` — a partial move is a fault, not a half-fix.
- **`fleet.yml`.** billing's `sourceCommit` moves `7251993…` → `7133643…`;
  `readOn` stays `2026-10-07` (the re-read happened today). The billing notes
  record the re-read, the unchanged catalogue schemas, and the fact that D39 is
  untouched.
- **`tests/test_specs.py`.** `PRODUCER_ID_SHAPES["billing"]["at"]` moves to
  `7133643…` to match the ledger. One new test,
  `test_the_recipient_fact_is_declared_the_way_billing_sends_it`, pins the two
  decisions and the negative case.
- **`gate.yml`.** the suite floor rises 299 → 300 for the new test, in the same
  commit.
- **Examples.** The five valid examples carry the new fields
  (`billing@example.com`, the corpus customer's address; `Pro monthly`, the
  fixture plan's name). A new negative example,
  `examples/invalid/events/billing/payment/succeeded.email.data.json`, refuses a
  wrong-typed `email` (`42`) on `type`, with its row in
  `examples/invalid/README.md`.

## The two decisions, from evidence

### 1. `email` is optional and never null

billing's producer is unambiguous. `StripeEvents.with_recipient` (payment
events) merges `email` only when `recipient_email` returns a non-blank value;
`Subscriptions::Lifecycle#core_payload` (subscription events) writes it only
when `customer.email.present?`. The field is **absent, never null**, and
**sometimes absent**: a customer created in the processor's dashboard has no
cafaye row, and one created through `/v1` has no email until the client sets
one (`customers.email` is nullable on purpose, validated against
`URI::MailTo::EMAIL_REGEXP` when present).

So `email` is declared **optional** (not in `required`) and **non-nullable**
(`type: "string"`, not `["string", "null"]`), with `format: email` — core's
convention for an address, per `billing.customer.created`. Required would
reject every event for a customer with no address; nullable would promise a
shape billing never sends. The schema descriptions say so, so a reader does not
have to guess.

The contrast with the fleet's other `email` is the point: `identity.session.revoked`
requires `email` because identity's publisher refuses to build the payload
without it. billing's publisher omits instead. Same field name, same reason (the
consumer cannot look it up), different requiredness — and the requiredness
follows the producer.

### 2. `plan_name` is required and non-empty

`core_payload` writes `plan_name` **unconditionally** from the plan row the
builder has already resolved, and `plans.name` is `null: false` in the database
with `validates :name, presence: true` in the model. So it is always present and
never blank on all three subscription events. Declared `type: "string"`,
`minLength: 1` (the way the neighbouring string fields do), and **required** —
optional would accept a real event's absence, which the producer cannot produce.

## What I ruled out

- **Resolving D39 in this packet.** The three subscription schemas still do not
  declare `account_id`, `currency`, `plan_id`, `started_at` or
  `processor_subscription_id`, so a real `billing.subscription.*` still does not
  validate against them. D39 is explicitly open, is referenced as open in the
  schemas' `$comment`s and in `fleet.yml`, and this packet's brief names only
  `email` and `plan_name` as what the subscription schemas gain. D39 stays open.
- **A nullable `email`.** billing never sends null; a field the publisher
  never nulls should not be null-able without a reason.
- **A required `email`.** the producer omits it for customers with no address;
  required would reject a real event.
- **A per-type negative case for every type.** one wrong-typed `email`
  demonstrates the constraint; the five types share the field's declaration.

## The handoff's "five entries" — an honest correction

The packet's handoff says billing removes the five `PENDING_PAYLOAD_ALIGNMENT`
entries. **That is only fully true for the two payment entries.**
`billing.payment.succeeded` and `billing.payment.failed` had `email` as their
only unexpected field; with `email` declared, billing can drop both. The three
subscription entries cannot be dropped: their unexpected lists still carry
`account_id`, `currency`, `plan_id`, `started_at` (started) and
`processor_subscription_id` (updated, canceled) — the D39 fields. billing
removes `email` and `plan_name` from those three lists and keeps the entries
until the D39 decision is made. The DECISION NEEDED in `cafaye.yml` (which
covers both the recipient fact and the older subscription-shape gap) stays
until D39 is decided.

## Follow-ups, unblocked by this commit

Both are in other repos; neither can be done from here.

1. **billing** — in the same commit that moves its `sourceCommit`-facing
   contract test to match core: remove the two payment entries from
   `PENDING_PAYLOAD_ALIGNMENT` (`billing.payment.succeeded`,
   `billing.payment.failed`), and remove `email` and `plan_name` from the
   unexpected lists of the three subscription entries (which stay for D39).
   The DECISION NEEDED in `cafaye.yml` covering the recipient fact can go; the
   one covering the subscription shape (D39) stays.
2. **courier** — subscribe to the money events and mail. The consumer's first
   move is already written in
   `billing/REPORT-billing-event-payloads-01.md` §"The first move for the
   courier consumer": a receipt for a settled charge, a warning for a failed
   one, a confirmation for a subscription change — each addressed to the
   `email` now on the envelope's `data`, with no billing client and no billing
   tables.

**Cite this packet as core commit `b8ae8fb69c2baec83ec536a8d2af08832bd7b316`.**

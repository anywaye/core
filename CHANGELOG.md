# Changelog

All notable changes to the anywaye **spec** are recorded here. This repository
is schemas, docs and validators, so "notable" means *a rule changed or a
document was clarified* — not a release of code. Bump guidance lives in
[README.md](README.md#spec-versioning).

Consumers pin a spec range in their manifest (`core: ^0.2.0`), so the
**breaking** section below is the one that matters when a service CI fails to
resolve.

## [Unreleased]

### Added

- **`db-isolation` — a guard for the defect `darkroom` shipped, applied to every
  service.** `harness/db_isolation_check.py`, reached as
  `harness/bin/db-isolation-check`, answers one question about a service: **can
  two tests in this suite delete each other's fixtures?**

  It needs all three of (1) tests that share one database, (2) a cleanup that
  deletes rows another test can see, and (3) a runner that executes them
  **concurrently**, and it reports *which one is missing* rather than a verdict,
  because "safe" is a claim about a mechanism and the mechanism is per-language.
  Those rules were read off repositories and then RUN:

  | language | (3) is in effect when | measured |
  |---|---|---|
  | Rust | **always** — libtest threads `#[test]` functions and `cargo` runs binaries in parallel | `darkroom` was red 6 of 6 before its fix |
  | Go | a test calls `t.Parallel()`, or two packages share a DSN under `-p` | `identity` green 3 of 3, every cleanup keyed by id |
  | ExUnit | two modules are `async: true` and share a database | `courier` 1282 passed 3 of 3, 49 async sites, SQL Sandbox per test |
  | Rails | `parallelize` forks per worker, **each given its own database** | four workers -> `billing_audit_test_1..4` |
  | pytest | `pytest-xdist` is installed *and* asked for | absent from `muse`, so sequential |
  | bun | never — one process, sequential | `guard` 467 pass, 0 fail |

  Two mechanisms **collapse** a condition rather than being reported: per-worker
  databases collapse (1), and a per-test `search_path` collapses (2), which is
  `darkroom`'s fix. `db-isolation.latent` is the one to watch for in a service
  nobody has audited — (1) and (2) present, (3) absent, one `async: true` away.

  **It is a check on core's own tree and runs from `bin/prime`, because a guard
  that lives in the service it guards is a guard the next service does not have.**
  Its verdict on the fleet as it stands is `0 failure(s)` — six services with
  database tests, none of them wrong — and a line that reads identically whether
  the checker can detect anything or not is exactly this packet's premise. So
  `harness/tests/db_isolation_self_test.sh` plants the defect: **3 reds** (the
  shared-truncate hazard, a table-wide `DELETE`, and a two-of-three latent Go
  suite) and **5 clean controls** (the unbroken fixture, a `WHERE`-narrowed
  delete, a comment using the word "truncate", the same truncate behind a
  per-test schema, and a test double). `bin/prime` reads that report rather than
  trusting its exit code.

  **Six things had to be taught to the reader, and every one was a measured false
  positive on this fleet first.** A `truncate` in a `///` doc comment; a `DELETE`
  whose `where` is three lines below it inside a raw string; `time.Now().
  Truncate(time.Microsecond)`; a `t.Fatal("a DELETE from the audit trail
  SUCCEEDED")` failure *message*; `muse`'s 968 tests, which run against a dict and
  cannot share a server; and `darkroom`'s `tests/schema_isolation.rs`, which is a
  test OF the isolation rather than the isolation. A guard that cries wolf on a
  green suite is switched off, and being switched off is how the real defect gets
  through next time. See `docs/db-isolation.md`.

- **`rls` — the database half of a service's account boundary, and the FORCE
  rule.** `tenancy.yml` gained a required `rls` block saying what **Postgres**
  does about the account boundary, as a separate claim from what the service's
  code does: `databaseEnforced`, `identity`, its own `sources` list, and per
  table the policies and `forced`.

  **`tenancy.rls-owner-bypass` is the rule the block exists for, and it is a
  FAILURE.** Postgres does not apply row-level security to a table's **OWNER**
  unless the table is set `FORCE ROW LEVEL SECURITY`; a service creates its
  tables in its own schema and therefore owns them. So a migration that writes
  `create policy`, then `alter table … enable row level security`, then stops has
  shipped a policy that is **never evaluated by the role that matters** — every
  query succeeds, every policy exists, nothing raises, and the runtime role reads
  every row. Postgres documents this in the CREATE TABLE reference and not in the
  row-level-security guide, and **Supabase's database advisor collects
  `relforcerowsecurity` for its table list and never judges it** (measured:
  twenty-eight lints, none of them this one). Anywaye uses `FORCE` zero times
  today across nine account-scoped services.

  Ten more findings came with it, adapted from the advisor's SECURITY lints and
  recorded one-for-one in `docs/tenancy.md`'s ledger — every one of the
  twenty-eight marked adopted, adapted or left out **with a reason**, and a test
  that fails when a row is dropped, names no finding, or says "left out" with an
  empty reason. The only severity raised above the reference is
  `tenancy.rls-policy-always-true`'s SELECT arm, and the ledger says so.

### Changed

- **The fleet's gateway is `gateway`. Every reference in core to the service
  formerly named `guard` now names `gateway`.**

  `fleet.yml` is the load-bearing edit, and the env var is **derived** rather
  than chosen: `test_specs.py` asserts
  `telemetry["endpointVariable"] == f"{name.upper()}_OTEL_ENDPOINT"`, so
  `name: gateway` forces `GATEWAY_OTEL_ENDPOINT`. Renaming the service without
  it would have been a red gate, which is the right way round — the contract
  should be able to say no.

  The **manifest fixture corpus** moves with it, because every validator in the
  fleet has to pass it. `examples/valid/telemetry/error-type.policy-denied.json`
  carried a span named `guard.request.authorize`, and the span-name grammar's
  ACCEPTED list moved with it: the prefix is cross-referenced against
  `fleet.yml`, so a span still named for a service `fleet.yml` no longer
  declares fails `test_span_names_name_a_service_the_fleet_has`.

  `test_a_service_core_has_not_read_is_reported_rather_than_assumed` keeps its
  whole argument and now asserts `"gateway" not in PRODUCER_ID_SHAPES`. Core has
  read gateway's ids out of no file at no commit, so the honest claim is still
  "unknown" and the rule still **reports** the gap rather than skipping it.

  **`guard` is mostly not the service in this repository either.** It is the
  word this fleet uses for a TRIPWIRE — *a guard that cannot find its target is
  not a guard* is a refrain core re-derives across nine files, and
  `account_scope_self_test.sh` has a Python local literally named `guard`.
  `via` in `schemas/account-scope.schema.json` is described as "the middleware,
  guard or decorator" — a guard is a THIRD thing there, and `tenantGuard` in the
  same file is a symbol. None of those moved.

  Measured: `./bin/prime` was **299/299 passed, exit 0** before this change and
  is **299/299 passed, exit 0** after. A rename that moved the count would have
  renamed a test or broken something, and the count did not move.
- **A 53-bit integer behind an `enum` is now a FAILURE, not a warning.**
  `numeric.float64-unsafe` decided itself from `maximum` and from an
  identity-shaped field NAME, and a field that is both `type: integer` and an
  `enum` reached neither: `walk()` filed it in two lists, carried neither the
  members nor the name into the position, and the enum list produced one
  `numeric.enum` warning about *evolution*. So `enum: [0, 1, 9007199254740993]`
  was silently accepted, and `9007199254740993` is 2^53 + 1 — a value
  `JSON.stringify` rounds, so every `Number()` round trip through a generated
  client returned `9007199254740992` and nothing logged.

  **An `enum` is a stronger statement than a `maximum`, not a weaker one.** A
  maximum bounds a range the writer may stay inside; an enum enumerates the
  *complete set of legal values*, so a member past the limit is a value the
  contract requires rather than one it tolerates. It is `numeric.float64-unsafe`
  at **failure**, sharing the id rather than becoming a fifth rule, and
  `numeric.enum` still fires on the same node — it is an unrepresentable value
  **and** a closed union, which are two true statements about it.

  Three decisions, each one a test rather than a paragraph:

  - **Magnitude, not sign.** Any member with `abs(value) > 9007199254740992` is
    refused, so `enum: [-9007199254740993, 0]` is refused. Measured before the
    change: the old rule did **not** catch it, and the reason is structural —
    it reads `maximum`, which is one number, and an enum is a set.
  - **Exactly `9007199254740992` is allowed**, in either direction, because it
    *is* exactly representable. The declared-`maximum` branch fires at `>=` and
    this one at `>`; the one-value difference is deliberate and
    [D44](DECISIONS.md#d44-is-an-enum-member-past-the-float64-exact-range-a-failure-or-a-warning)
    has the argument.
  - **One node, one finding.** Where a field has both a crossing `maximum` and a
    crossing `enum`, the `maximum` reports and the enum yields.

  A string enum, an enum of floats and an enum with one non-integer member are
  **unchanged**, and an `enum` with no `type` at all — legal draft 2020-12, and a
  shape the position-based rule structurally could not reach — is caught.
  **Measured: the new trigger fires on 0 of core's 31 positions and 0 of the 6
  findings across the fleet's service specs**, so it can be a failure rather than
  a warning. The floor moves 270 -> 272.

- **`negative` is now three cases, and the third is the one that carries the
  information.** It replaced a single `expects`/`file`/`line` triple.
  **This is a breaking change to a published format** and it is recorded as one:
  "does an unauthenticated request fail" is satisfied by a table with no policy at
  all, by a table with no predicate at all, and by a service whose database is
  switched off — all three are the **bug**. So `negative.cases` is exactly three
  arms: `no-identity` and `other-account` read zero rows, and **`own-account`
  asserts the account's own credential sees its rows**, because two denial arms
  are satisfied perfectly and forever by a service that returns nothing to
  anybody. `own-account` is `const: present` and its `expects` is refused to be an
  absent spelling: `tenancy.positive-control-refused` is a FAILURE.

  `version` is unchanged at `1`, which is a real defect and is recorded as one in
  [D41](DECISIONS.md#d41-how-is-the-force-rule-declared-and-what-may-a-warning-mean-in-the-tenancy-checker)
  rather than hidden: the fleet has **zero** adopters of `tenancy.yml`, so the
  migration cost is this repository and nothing else. Bumping to `2` would make
  the break loud rather than confusing and is the manager's call.

### Fixed

- **Twenty-four examples taught the fleet an id shape no service emits.** Every
  `tenant_id` and `account_id` under `examples/valid/telemetry/` carried a
  prefixed ULID (`tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG`,
  `acc_01J9Z8QK5M4N7P2R3T6V8W9X0A`), as did billing's
  `payment/succeeded.checkout` example. These examples are the reference every
  service author copies from.

  **The prefix was the symptom.** `tenant_id` is not an id: it is an
  operator-set environment variable copied verbatim onto the resource
  (`IDENTITY_TENANT_ID`, `COURIER_TENANT_ID`, `BILLING_TENANT_ID`), and the
  producers' own tests give it `"acme"` and `"tenant-abc"` — so it is now typed
  as an operator label, with **no underscore**, which is the one character
  nobody typing `acme` produces. And `account_id` on a telemetry *resource* is
  emitted by nobody at all: it appears zero times across identity's
  `telemetry.go`, courier's `telemetry.ex`, billing's `kit/telemetry.rb` and
  muse's `telemetry.py`, while the same field on an event payload is a bare
  uuid in four places. It is removed from the resource examples rather than
  respelled, because respelling it would have taught a plausible fiction.

  The clearest single piece of evidence is billing's `client_reference_id`:
  `create_checkout_session/1` sends `customer_reference` — billing's own
  customer id, a bare uuid, asserted as `11111111-1111-4111-8111-111111111111`
  in billing's own production test — while its webhook test carries
  `acc_01J9Z8RR7B2QK3M4N5P6Q7R8S9T`. The example had the **test fixture's**
  value, not the code's.

  Three prefixed ids **stay**, all under `examples/invalid/`, because there the
  fiction is the thing being rejected: `format: uuid` refusing `usr_…` is the
  entire demonstration of the case
  [D35](DECISIONS.md#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
  is about. A test now asserts that every surviving prefixed id sits in a file
  whose rejection is attributable to the id's own shape, so the survivors cannot
  drift into a habit.

- **core-24's id rule never looked at `examples/valid/telemetry/`.** It globs
  `examples/valid/events/` and stops, so twenty-one examples sat in the tree for
  the whole of core-24 with the rule green — it was correct about everything it
  looked at. Two independent reasons the same rule missed all of them: the
  directory it was pointed at, and an `IDENTIFIER_FIELD` regex admitting one
  underscore where billing's `client_reference_id` has two. Both are fixed, and
  a test now asserts the two example walkers **between them cover every valid
  JSON example**, so the next directory nobody looks at is a failing assertion
  rather than a silent blind spot.

- **Courier's five and billing's eight payload schemas now cite the commit
  their publisher was read at**, every one read at the commit `fleet.yml`
  already records for its service — billing's tree was verifiably *at* it. The
  five schemas the finding named were never the interesting subset:
  `billing.payment.succeeded` is the one whose example taught core a fictional
  id. `courier.email.queued` is cited with the fact that its publisher **does
  not exist** — `lib/courier/events.ex` has no `queued/1` at that commit — which
  is recorded in the citation itself rather than left to look like provenance.

  muse's one payload schema stays exempt: core did not read `metering.py` at
  muse's recorded commit, and citing it would be inventing provenance to satisfy
  a checker.

### Added

- **Every example's ids are the ids the service that emits it mints.** Each
  producer's id type is transcribed from a **named file at a named commit** into
  a ledger, each identifier field is assigned one of those shapes, and every
  identifier value in every valid example must match the shape recorded for that
  field of that service. Telemetry resource attributes have their own table,
  because a resource attribute and a payload field under the same name are
  different populations of values — `account_id` is real on one and emitted by
  nobody on the other, which no rule keyed on the field name can tell apart.

  **The walk is in both directions.** A recorded shape that no example exercises
  is a fault too, because a ledger of assertions nothing corroborates is a list,
  and lists rot. Attribution reads `service.name` off the example itself rather
  than off its directory, since `metric.json` is identity's, `log.json` is
  courier's and `span.muse.json` is muse's and all three sit in one directory.

  A service core has read nothing about is **reported**, not passed — `guard` is
  the standing witness. And a document carrying no identifier at all is *not*
  reported, because a rule that emits unfalsifiable noise is a rule nobody reads.

  **What it cannot do:** core reaches no publisher, so it cannot prove identity
  still generates version 4 uuids. It proves core's record of each producer and
  core's examples agree, and every entry names the commit it was read at so the
  ledger is visibly stale the day `fleet.yml` moves a `sourceCommit`. See
  [D37](DECISIONS.md#d37-how-does-core-check-that-an-examples-ids-are-the-ids-its-producer-mints).

  **No schema required the prefix, so there was no launch blocker to fix** —
  `tenant_id`/`account_id` were `{"type": "string", "maxLength": 64}` and nothing
  else, verified by walking every `pattern` in every file under `schemas/`.
  Typing `tenant_id` as a uuid would have been wrong in the other direction: the
  next operator to choose a non-uuid tenant name would be rejected by core.

### Changed

- **`docs/observability.md` no longer implies `account_id` is required on a
  telemetry resource.** It is permitted there and prohibited on the measurement,
  and nothing requires it — which is the permissive half that let sixteen
  examples assert a value no producer emits. Either the schema requires it and a
  service emits it, or the list drops it; the first is a change to a contract
  with six publishers and is not core's to make alone, so it is named rather
  than decided in a comment.

- **`courier.email.queued`'s payload schema says out loud that its publisher does
  not exist yet**, and that when courier builds `queued/1` the citation and the
  obligation it carries are what have to be revisited. It is the one schema here
  that describes something unbuilt, and it says so rather than letting the
  citation imply otherwise. **(core-26, below, moves that admission out of
  `$comment` and into `description`, because a `$comment` is metadata no tooling
  shows.)**

### Changed — core-26: three places core's schemas and real publishers disagree

core-25 built a check that every example carries an id shape its own producer
can mint, and in building it found three places where core's schemas and what
services actually emit are simply different. It recorded all three and fixed
none, because each is a decision about somebody else's contract. This is that
packet. **Every claim below was read out of a publisher's own source at a named
commit, and each says where.**

- **`courier.email.queued` stays, and is recorded as
  declared-and-unimplemented where a subscriber's tooling will show it.** The
  packet asked whether the publisher was missing or misnamed. It is **missing**,
  and courier says so in its own words: `lib/courier/events.ex` at `master` HEAD
  `ae8a660` still has `delivered/1`, `bounced/1`, `complained/1` and
  `suppressed/1` and no `queued/1`, and its moduledoc says the type "has no
  builder because courier has no queue — the send path is synchronous and
  documented as such … that type exists to make a *backlog* visible". The
  misnaming was ruled out from the state machine: `Courier.Suppressions` has
  states `nil | :undeliverable | :suppressed` and no `:queued`, and courier's one
  bounded queue is the error relay's. **Deleting the schema was rejected**, and
  not for cost: a declared type with no payload schema is what D34's
  `pendingCoreContract` is for, and that list means *the service publishes it* —
  so deletion would convert an honest gap into a lie of the opposite direction.
  See [D38](DECISIONS.md#d38-does-a-declared-event-type-with-no-builder-stay-in-core-or-leave).

- **A payload schema's standing against its publisher is now stated in
  `description`, not only in `$comment`.** The two instances core had were both
  invisible to every reader they were written for: `jsonschema` ignores
  `$comment`, `cafe contract lint` ignores it, and an editor's hover shows
  `description`. So `courier.email.queued` had an honest, fully-cited admission
  nobody could see and a `description` asserting an emission that never happens,
  and the three billing subscription schemas had a `$comment` claiming a
  transcription that does not match the code it names. The two standings are a
  closed vocabulary borrowed from core's own words — `fleet.yml`'s
  `declared-and-unimplemented`, and D35 restated as a predicate — and the
  vocabulary is itself asserted, because a standing nothing claims is a rule that
  cannot fail.

- **`billing`'s subscription payloads disagree with core's schemas in BOTH
  directions, and core's documents claimed the opposite.** billing grew a
  `subscriptions` table after D10 was written, and
  `Subscriptions::Lifecycle#core_payload/1` now emits `plan_id` and `account_id`
  as bare uuids onto all three subscription payloads — while core's schemas
  require `processor`, `processor_event_id`, `kind` and `customer_id`, which
  billing never sends. **A real `billing.subscription.started` does not validate
  against core's schema for it**, and it did not start by accident of a value.
  D10 was *right when written* and has gone stale; its update paragraph says so
  rather than rewriting the decision's own words. core's claims are corrected
  here — `examples/invalid/README.md`, `docs/event-naming.md` and the
  `subscription/started` `description` all said billing has no such fields. **The
  schema rewrite is drafted and left to the manager** (D39): it deletes four
  properties this schema has required since v0.2, it partly reverses D10, and that
  is a decision about what `billing.subscription.*` means on the bus.

- **The resource attribute allowlist was missing four attributes a real span
  carries, on all three signals.** `service.namespace`, set by muse by hand at
  `src/muse/telemetry.py:390` and asserted in its own tests; and
  `telemetry.sdk.name` / `.language` / `.version`, which billing sets two of **by
  hand** at `lib/kit/telemetry.rb:183-184` and which every merging SDK adds
  whether the caller asks — **measured**, not quoted: against the 1.44.0 SDK in
  muse's own venv, `Resource.create({'service.name': 'muse',
  'service.namespace': 'anywaye'})` returns six attributes and this list refused
  four of them. It went unnoticed because identity builds its resource with
  `resource.NewWithAttributes`, Go's schemaless constructor, and courier builds
  its own resource map, so the two publishers the SDK contributes nothing to are
  the two that validated. **This is a looser rule and therefore a PATCH** under
  `README.md`'s table. See
  [D40](DECISIONS.md#d40-is-the-resource-allowlist-missing-a-field-the-fleet-uses-or-is-a-service-emitting-something-it-should-not).

- **The three signals' resource attribute lists are asserted to be one list in
  three files.** They were three copies with nothing comparing them — the defect
  `test_the_span_name_pattern_is_shared_with_the_traces_schema` prevents, sitting
  on the attribute list a service reads its resource contract out of. Asserted in
  both directions: the list carries everything the fleet demonstrably emits and
  nothing it does not, so a fifth attribute can only join by arriving with a named
  producer beside it.

- **`PRODUCER_ID_SHAPES` is now pinned to `fleet.yml`'s `sourceCommit`.** D37
  claimed the ledger "is visibly stale" the day the registry moves a commit, and
  nothing made it visible — the `at` key had never been compared to anything, so
  every id shape in it was a claim about bytes nobody had recorded. This is
  D37's last sentence made mechanical.

- **`fleet.yml` and `docs/event-naming.md` said courier publishes three of five
  types. It publishes four.** Found by re-reading courier to answer the first
  question properly rather than by looking for it:
  `Courier.Unsubscribes.publish/1` writes the `courier.notification.suppressed`
  outbox row in the same transaction as the preference that turned the type off,
  with a payload field-for-field identical to what core's schema already required.
  courier still does not publish it for a *refused* send, and says so itself. The
  schema needed no change — which is what writing its citation carefully in the
  first place was for.

- **`fleet.yml`'s courier entry now says out loud that its `sourceCommit` is
  behind the commit its prose describes.** core-26 read three of courier's files
  and not its OpenAPI document, its telemetry configuration or the rest of its
  surface, so claiming the whole registry was re-read at `ae8a660` would be
  claiming a re-read nobody did. The pin and the prose are honest about being out
  of step, which is the state D36's remedy exists for and the next courier packet
  should close.

- **Two things measured and deliberately NOT changed, recorded because "we checked
  and it is not there" is the half of a positive record nobody writes down.**
  `process.pid` is not on the resource allowlist: billing's source says
  `Resource.create` merges the SDK's default resource and reports it, and on the
  installed SDK (1.13.1, measured) it does not merge and there is no
  `process.pid` — one service's comment about a default is not evidence that a
  default exists, so billing owes that comment a correction. And `courier`'s
  `sourceCommit` was not moved, for the reason above.

### Added (previous)

- **`LICENSE`: core is MIT.** Recorded here even though it is not a spec change,
  because this changelog's stated scope is *"a rule changed or a document was
  clarified"* and this is neither — it is the grant the whole repository was
  distributed under all along, now written down rather than assumed.

  core held no licence file, which is not "unlicensed, therefore free" — it is
  **all rights reserved**, the default copyright position when a public
  repository grants nothing. That matters more here than anywhere else in the
  fleet: core holds the schemas and conventions every other anywaye repository
  adopts, so the licence it ships under is the licence a consumer inherits by
  depending on it. MIT keeps that a fact about this repository rather than about
  whoever adopted it.

  There is no `pyproject.toml` — core is a Python harness plus data, run from a
  checkout rather than installed — so the `LICENSE` file is the entire grant and
  there is no package metadata that could disagree with it. The copyright line
  matches the three repositories that already shipped a licence exactly:
  `Copyright (c) 2026 anywaye`.

- **`kind: service | template` — one registry holds both running services and
  generate-time templates.** A template is consumed at *generate* time: `cafe init`
  renders it and the caller owns the output. It is versioned and pinned in a
  registry exactly like a service, and it is never a running process. This is
  what lets one `pantry` hold `identity` (a service) and `parlor` (a template)
  instead of forcing the two into different mechanisms. `kind` defaults to
  `service`, so every manifest written before this field existed keeps meaning
  what it meant.

  A template declares no `exposes` and no `consumes`, and the omission is the
  claim rather than an oversight: a template has no runtime contract to break,
  so an `exposes` block on one would assert a promise nothing can keep.

- **`environments:` — where each dependency runs, declared once per environment.**
  This is the only place self-host-vs-hosted is expressed, and it is a
  *declaration* rather than a flag discovered at runtime, which is the whole of
  "build once, deploy once, use everywhere": one file says what production looks
  like, and `cafe dev`, `cafe deploy` and CI all read that same answer.

  ```yaml
  environments:
    production:
      identity: hosted      # everything omitted is self-hosted
    development: {}         # no anywaye account needed to work locally
  ```

  Values are `self-hosted` or `hosted` and there is **no default on a value**,
  because a reader that invents an answer about who pays and who operates is the
  most expensive kind of wrong this file can contain. The default at the *key*
  level is omission-means-self-hosted, which is what makes the common case short:
  name the one service you pay for and leave the rest alone. `default:` is
  available for any environment not named explicitly.

  Both fields use only keywords `harness/anywaye_contract.py` already implements —
  the first draft used `patternProperties` and `propertyNames`, and
  `test_the_harness_implements_every_keyword_core_schemas_use` refused it,
  correctly: a schema using a keyword the validator does not implement means the
  validator accepts documents the schema rejects.

- **`fleet.yml` grew an `api` field, and the courier entry had to be rewritten
  around it.** `fleet.schema.json` transcribes each service's `exposes.api` and
  had nowhere to put it, so the only place that claim lived was prose — and
  courier's said *"declares no `exposes.api` because it has no OpenAPI document
  to point at yet"* while courier has carried `openapi.yaml` since courier-05
  and is at `info.version: 2.2.0` after courier-21 added a send operation and
  courier-22c an inbound webhook. Four of the five services now record the
  document (`identity`, `billing`, `courier`, `muse`); `guard` does not, because
  its manifest declares no `exposes` at all, and that stays a finding rather than
  a value — **guard now ships `openapi/v1.yaml` and still names no
  `exposes.api`**, which core's own harness already reports as
  `openapi.not-declared`. `api` is a transcription of the manifest, so recording
  a path guard does not declare would be core asserting a field guard does not
  have.

  The `openapiRef` `$defs` is duplicated from `anywaye.manifest.schema.json` for
  the same reason `eventType` is duplicated three times, and
  `test_the_fleet_and_manifest_agree_on_what_an_openapi_path_looks_like` asserts
  the copies match.

### Fixed

- **`identity.user.created`'s payload schema described a payload identity has
  never sent, and three checks now stand where the reviewer's memory was.**

  A **patch**, and the absence of a major is deliberate in the way README asks
  for. README's table calls *a looser rule* a patch and *a removed event type* a
  major. This is a loosening — `user_id` moves from `^usr_[0-9A-Z]{26}$` to
  `format: uuid`, which admits everything the old pattern admitted and every bare
  uuid besides, and invalidates nothing that previously validated — plus three
  optional properties of one event type, and **no publisher has ever emitted
  them**: `internal/outbox/envelope.go:147-150` marshals a struct of exactly
  `user_id` and `email`. Nothing was tightened; the pattern that changed is the
  one a reader will check, and the direction is what settles it.

  The decisive fact is that the old schema **rejected 100% of identity's real
  output** — the pattern cannot match a bare uuid and identity emits nothing
  else — so there was no working consumer to break and a major would have
  signalled a break with no recipient. `email_verified`, `locale` and
  `account_ids` are **deleted rather than left optional**: optional is the same
  lie in a softer form. The valid example and the valid envelope lose all three
  too, and the envelope's `subject` becomes the same bare uuid as its
  `data.user_id` — which is what the schema has always said they are.

  Three descriptions in other schemas said the mismatch was real, and said so
  about *this* file: `courier.email.queued`'s and `billing.customer.created`'s
  `user_id`, and the envelope schema's `subject`. They are corrected, and the
  two other courier payloads that cite D7 without repeating the claim are left
  alone because what they say is now true.

  **The check is the deliverable.** D35 existed because nothing compared a
  shipped payload schema against the code that emits it: nine schemas sat under
  `schemas/events/identity/`, eight of them read out of identity's builders and
  one written from an assumption, and the one that disagreed shared a directory
  with a correct one. Nothing noticed. `tests/test_specs.py` now asserts that
  **one publisher spells one id one way** across its payload schemas, that
  **nothing core ships carries an id shape no publisher mints** (a `pattern`,
  `const` or `enum` under `schemas/events/`, or an identifier in a valid
  example), and that **a payload schema cites the commit its publisher was read
  at**, checked against `fleet.yml`'s `sourceCommit` — so re-reading a publisher
  turns its payload schemas red until somebody re-reads those too. Each has a
  witness that hands it the file as it stood, because a rule that has never
  failed is a comment.

  What they cannot do is in
  [`docs/event-naming.md`](docs/event-naming.md#what-core-checks-against-the-publisher)
  and in [D36](../DECISIONS.md#d36-what-a-static-check-can-say-about-a-publisher-core-has-never-read):
  core reads no publisher, so these compare core against core and **cannot catch
  a publisher whose code changed without anybody re-reading it**. The check that
  would is a publisher-side one, and it is named as owed rather than faked here.
  See [D35](../DECISIONS.md#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit)
  for the escalation this answers and [D7](../DECISIONS.md#d7-courier-keys-a-user-by-uuid-and-identity-publishes-a-usr_-id)
  for the premise this corrects — D7's second half is **marked false, not
  deleted**, because a reader needs to see the claim was once made.

- **`fleet.yml` described yesterday's fleet, in four ways that were each
  verifiable in the service's own source.** Every claim below was checked
  against the repository at the commit now named beside it.

  - **courier publishes three of its five declared types, not one and not four.**
    `courier.email.delivered` is written by `Courier.Deliver` in the transaction
    that sent the mail. `courier.email.bounced` and `courier.email.complained`
    are written by `Courier.InboundReports` in the same transaction as the
    suppression row, chosen by that row's state, so `POST /inbound/resend` is
    what gave them a caller in courier-22c.
    `courier.notification.suppressed` is the correction to the correction: it
    **has a builder and no caller**. `Courier.Events.suppressed/1` is referenced
    only by its own module and its test, and `Courier.Deliver`'s moduledoc still
    promises *"no mail, no event, no record of a send that did not happen"* for
    both refusals. It is the fourth type, and the packet's premise was right about
    three of four rather than four of four.
  - **`manifestViolations` is empty.** courier's manifest and `Courier.Events`
    were corrected to the conforming three-segment spellings; the list still
    named the five two-segment strings, which is the entry this changelog's
    previous release recorded as fixed-in-the-source-but-not-in-the-record.
    Deleting it is the acknowledgement `docs/event-naming.md` asks for, and the
    doc's own claim that the list *"is courier's five two-segment types"* was
    corrected with it.
  - **The stale `core: ^0.1.0` note is gone, because the constraint is not
    stale.** courier declares `core: ^0.2.0` and `mix.exs` pins no anywaye
    dependency, so the manifest line is the only one there is.
  - **Every `sourceCommit` is current, and `readOn` moved to 2026-10-01.** The
    file previously carried a rule against bumping them — *"bumping it would date
    a transcription that was not re-made"* — which was right while the lists
    had not been re-read and stops being right the moment they are. All five
    manifests were re-read; the rule is gone because its premise is.

  Two things the packet asked about turned out to need no correction, and are
  recorded rather than changed: **503 is already two conventions with one
  number.** `unavailable` (503) is a reserved code for a customer operation
  (`docs/openapi-conventions.md`), `readyz.statusCode: 503` is a probe fact
  (`schemas/telemetry/probes.schema.json`), and D14 rejected the status code as
  an `error.type` class precisely because *"a 503 from a dead provider"* and
  *"a 503 from a dead database"* are different incidents with different
  responders. Nothing encoded the conflation; the registry now says so on
  courier's entry so a reader does not infer the other reading. And **core's
  error-code list is a floor, not a ceiling** — `RESERVED_ERROR_CODES` binds one
  way only (a reserved code carries one status), and `errors[].code` is
  deliberately not counted, so courier's thirteen-value field-level enum and its
  `bad_request`/`not_acceptable` envelope codes are inside the contract as
  written.

- **Two more false statements about the fleet, in `docs/`, corrected while the
  same evidence was in hand.** `docs/event-naming.md` §courier said *"courier's
  own manifest says `email.queued` and four siblings, which core v0.2's frozen
  grammar rejects"* — it stopped saying that when courier's manifest was
  corrected, and the catalog was still asserting the old grammar violation. The
  section now says the conforming spellings are what courier declares, records
  that `manifestViolations` is empty, and separates **declaring** a type from
  **emitting** one, which the catalog had never done and courier's own three-of-
  five made unavoidable.

  `docs/contract-harness.md` said *"three services declare `core: ^0.1.0`
  (`identity`, `courier`, `guard`) and none of the three has a workflow that
  checks out core at all"*. Re-measured on 2026-10-01: **all five services
  declare `^0.2.0`**, and the fetch side is now split three ways — `muse` pins a
  full commit, `billing` and `guard` fetch `master` unpinned, `identity` and
  `courier` still fetch nothing. The paragraph is rewritten around what is
  measurable, including the defect that **replaces** the one it described: two
  services fetch core at a moving ref, which a harness reading that checkout
  cannot distinguish from a correct pin.

- **`pendingCoreContract`: a fourth list, and the assertion that keeps it
  honest.** `events` now means "the manifest declares this **and** core has
  shipped a catalog row and a payload schema for it", because
  `test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema`
  asserts exactly that and a type without both halves cannot go there.

  identity's manifest declares nine conforming types and the registry recorded
  one, marking eight of them as `cataloguedOnly` — a promise core had made and
  nobody had kept, for types identity was already publishing. Finishing core's
  half means writing eight payload schemas and two catalog rows for another
  repository's events, which is core's own work and its own packet, so the eight
  went into `pendingCoreContract` and
  `test_a_pending_core_contract_type_is_a_debt_core_really_owes` **rejects** an
  entry that has both halves: a debt with nothing behind it is an excuse for work
  already done. The three lists are also asserted pairwise disjoint. Recorded as
  [D34](DECISIONS.md#d34-how-does-the-fleet-record-a-type-core-has-not-finished-contracting-for).

  **The list is empty as of core-23, below, and it was emptied rather than
  deleted** — so the "cost of flipping" D34 names was not taken in full. The
  schema property, the file header and all three assertions stay, because a list
  that appears when it is needed is worth more than one deleted when it is not,
  and because deleting the rule with the entries is how the next debtor invents a
  fifth place to record the same fact.

- **Eight payload schemas for identity, and the fleet's debt is paid.** Every one
  of the types `pendingCoreContract` held now has a row in
  [`docs/event-naming.md`](docs/event-naming.md) and a schema under
  `schemas/events/identity/`, and all nine of identity's declared types are in
  `fleet.yml`'s `events`. **Every published type in the fleet — 23 of them, across
  four services — has both halves**, which is the first time the fleet has been in
  that state and is now what
  `test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema`
  asserts across all of it rather than across four types.

  The two `identity.oidc_client.*` types had **no catalog row at all** before
  this, so they are the two rows that are new rather than the two schemas; the
  other six already had one.

  **Every field was read out of the emitting site, not out of the type's name.**
  `internal/outbox/{recovery,mfa,apikeys,oidc}.go` build the payloads and the
  service packages call them; where the shape was a fact about a table rather than
  about a struct, the table is the source (`mfa_credentials` carries
  `CHECK (method = 'totp')`, which is why `method` is a closed set of one, and the
  api-key scope vocabulary is identity's six constants, not a plausible-looking
  list). Ids are **bare uuids**: identity's `id.UUID.String()` is RFC 4122
  canonical form, which is what courier and billing already key users on and what
  [D7](DECISIONS.md#d7-courier-keys-a-user-by-uuid-and-identity-publishes-a-usr_-id)
  recorded — see **D35** below for the one place core still disagrees with itself
  about this.

  The negative cases carry the packet's real weight, and four of the eight are not
  the boilerplate pair. A `reason` outside identity's two, a `method` the
  `mfa_credentials` CHECK forbids, a scope outside the vocabulary, and the four
  credentials the publisher's own comments say it deliberately never emits — a
  verification token, an `otpauth://` URI, an api key's plaintext, an OIDC client
  secret — are each rejected by an example, so a constraint read out of a Go
  docstring in another repository is an **enforced** constraint rather than a
  sentence. `identity.api_key.revoked` and `identity.oidc_client.revoked` both
  reject `revoke_reason`, which is the column's own name and is exactly the field
  a payload grows by accident.

  `identity.user.created` is untouched and is now the only identity schema that
  disagrees with its publisher; that is [D35](DECISIONS.md),
  not something this packet resolved on the way past.

- **A note may no longer deny a fact a sibling field records.**
  `test_a_recorded_api_document_and_a_note_saying_there_is_none_are_not_both_true`
  is the assertion that would have caught courier's sentence the moment the field
  existed, and it fires on both the `notes` and the `telemetry.notes` of any
  service that records an `api`. Prose is not compared against anything, which is
  how a sentence written by courier-05 outlived two packets that edited the
  document it said did not exist.

  All three new tests were shown failing on the data they were written for before
  that data was fixed — the `api` one on courier's own note, the debt one on a
  billing type core has finished, and the catalog one on identity's six
  catalogued-and-published types — and the gate floor in `gate.yml` is raised
  from 220 to 223 in the same commit, as it must be.

- **`fleet.yml` said `signals: []` for courier, billing and identity, and all
  three ship a wired OTel SDK.** Read at `readOn` (`2026-09-30`) that was true;
  the three SDKs landed on `2026-10-01`, after the manifests were read, and
  nothing re-read them. The field now records `traces` for those three, each
  entry naming the commit it was read at and the file that carries the span
  processor.

  **Traces only, and that is read from the code rather than from a module
  name.** None of the three installs a meter: courier's Erlang SDK has no
  metrics API at all (it says so in `lib/courier/telemetry.ex`), billing
  installs no `MetricReader`, and identity imports no `sdkmetric`. kit's
  collector derives metrics from spans with the `spanmetrics` connector, so
  `signals` recording `traces` and not `metrics` is the accurate answer rather
  than a modest one.

  The misleading sentence was identity's `telemetry.notes`, which read *"core
  owns the contract and this build has no collector wired in, which is the
  honest record rather than claiming instrumentation that is not there"* — a
  fleet-wide statement sitting on one service, and muse's note claimed to be
  the only service exporting anything. Both are rewritten per service, and the
  fleet-wide statement moved to the file header where it belongs.
  `schemas/fleet.schema.json`'s `signals` description is the sentence that
  taught the error — it defined "empty" by reference to a collector — and now
  says what the field records instead.

  `test_a_service_recorded_as_exporting_nothing_asserts_no_fleet_wide_state` is
  the assertion. It cannot check that `signals` matches any service's code,
  because core reads `schemas/` and never a sibling checkout: `sourceCommit` is
  still what makes that transcription checkable rather than a claim, and this
  test checks the half that was wrong — that the record does not lie about what
  kind of fact it is.

- **Two more drifts in the same file are recorded rather than fixed, and
  `sourceCommit` is not bumped for any service.** Every service's `anywaye.yml`
  has moved since the commit named beside it, and two entries now contradict
  their manifest: identity declares nine event types where the entry records one
  published and eleven catalogued, and courier's grammar violations are fixed in
  the manifest and `Courier.Events` but still listed under
  `manifestViolations`.

  Neither is corrected here, and the reason is that doing it honestly means
  writing core's contract rather than transcribing it: seven of identity's
  newly-published types have no payload schema under `schemas/events/`, and
  `identity.oidc_client.created`/`.revoked` have no catalog row at all.
  Bumping `sourceCommit` to today's commit would date an event list that was
  not re-made — the same class of error as the one this entry records. The
  finding, with the counts, is in the `fleet.yml` header under `STALE`.

- **kit's dev compose default is `postgres:17-alpine`, not `16.6-alpine`.** A
  developer running `bin/dev` was getting postgres 16.6 while the rest of the
  fleet floated at 17. This was a recorded, known deviation; the recorded
  expectation in `tests/test_specs.py` and the table in `docs/postgres-pin.md` are
  updated in the same commit, because they are one claim stated twice.

  One deviation remains in kit and is now recorded instead of fixed: the deploy
  template's `services.app.image` is `${KIT_DEPLOY_IMAGE:?...}`, a variable the
  deploy tool sets rather than a postgres image. It is left visible because
  suppressing it would teach the rule to skip variables, and
  `${KIT_POSTGRES_TAG:-default}` is exactly the form the rule exists to resolve.

The payload reconciliation, the observability spec, the contract-test
harness, the SLO and error-budget specification, the gate declaration, and the
postgres image pin.

### Added — `compose.postgres-pin`, and the tag it compares against

**No schema a service consumes changed, and `contract_digest` is unchanged** —
deliberately, and the reason is in the report: the tag lives at core's root
beside `VERSION` rather than under `schemas/`, because a new file under
`schemas/` would change the sha256 every pinned service carries and turn them
all red for a file none of them consumes. Nothing to re-vendor; the cost of
adopting this is one line of CI.

- **`POSTGRES_TAG`** at core's root, holding exactly one tag —
  `17-alpine`, the platform decision recorded in DEBT.md D24. `VERSION`'s
  discipline, one commit later: missing, empty, two lines, or not a tag is a
  **refusal (exit 2)**, `compose.postgres-tag-absent`, because a core that
  publishes no standard leaves the rule with nothing to compare against and a run
  that cannot find what it is checking has converted an unknown into a pass.
  **`latest` is refused too** — it is the one value that would make the rule
  pass exactly the references it exists to fail.
- **`compose.postgres-pin`** — every postgres image reference a repository makes
  resolves to that tag. It reads **executable declarations only**: an `image:`
  key in a compose file or a workflow's `services:`, and a `docker run` line in a
  shell script. The rule says so in its own source, in
  [`docs/postgres-pin.md`](docs/postgres-pin.md) and in the inventory, because
  **prose is a named exclusion**: a `grep -r 'postgres:'` over the fleet's own
  history finds `postgres:17` in six CHANGELOGs and `postgres:18-alpine` in
  muse's, every one of them correct about when it was written, and a rule that
  read history would turn six changelogs red for being accurate.
- **`postgres-pin-exceptions.yaml`** — how a service that genuinely needs
  another major says so: a `file`, an `image`, a `reason`, an `owner` and an
  `until`. Matching is on the **exact path and exact reference** — no wildcard,
  because a blanket exemption is the thing a rule exists to prevent. Five
  properties, all findings: a missing field; an exception for the tag core
  already declares; an entry that names nothing this rule decides; a file that is
  not a path; and — the one that is easy to get wrong — **an entry that fails any
  of those does not GRANT.** It is reported *and* inert, so a suppression nobody
  can review cannot suppress. `until` is required and is **never compared to a
  date**: a rule whose answer depends on the day it runs is not a rule.
- **`compose.pin-scan-truncated`** (warning) — a compose-shaped file below the
  depth the rule reads. The bound exists so the walk does not enter
  `node_modules`; the warning is what stops the bound from being a silent pass
  over a pin nobody checked. The walk is unbounded and the *reading* is bounded —
  the first version bounded the descent too, so a compose file three levels down
  was never *found*, the warning could not fire, and the limit was invisible.
- **Four shapes the rule refuses to compare**, each a finding rather than a pass:
  a digest with no tag (`postgres@sha256:…`), a variable with no default
  (`postgres:${TAG}`), no tag at all (`postgres`), and `latest`. A bare major
  (`postgres:17`) gets its own sentence — the major is right and the minor
  floats.
- **Five fixtures** and **four breakages plus one warning case** in
  `harness/tests/self_test.sh` (41–44, 45), each naming the rule it must be
  caught by, and **two new controls**: the pin control carries all three
  declaration shapes *and* the four shapes that must not be read as a reference
  (a DSN with a password in it, a `postgres` used as a user, as a driver, and a
  `redis:` run), and a fourth control for "a different major, DECLARED", which is
  a green state a rule with no exception path could not produce.
- **Sixteen tests in `tests/test_specs.py`**, and the `gate.yml` floor raised to
  212 with them — measured, not summed: `bin/prime` prints 212/212 and
  `bin/prime --pytest` collects 212.

### Fixed — a CI step that failed on every run and blamed a passing self-test

`.github/workflows/ci.yml`'s "the self-test said what it did" step greps the
self-test's log to compare the count its footer **claims** with the number of
breakage assertions actually logged. It asked for `all N breakages went red`; the
footer has always printed `PASS: self_test — N breakages went red naming their
rule`. So the count came back **empty**, the `[ -z "$claimed" ]` guard below it
was true on every run, and the step **exited 1** — with a message blaming a
self-test that had just succeeded. The self-test's own count was correct
throughout.

A guard that cannot find its target is not a guard, and this one was not failing
open either: it failed on purpose, for a reason nobody could see, which is the
worst of the three shapes. It is fixed, and
`test_the_ci_self_test_step_reads_the_phrase_the_footer_prints` now pins the two
strings to each other — reading the step's own `run:` block with shell comments
stripped, because a check that a comment can satisfy is not a check, and writing
down what was wrong with this step put the broken phrase into its comments.

The same step required **exactly one** control (`-ne 1`), and this packet adds
two, so it now requires at least one **and** asserts the first control line
precedes the first breakage line. Order is the property it was for: a control that
runs after a breakage has not controlled it, because a tree that was already red
makes every assertion below it vacuous. A check that hard-codes a control count
fails on every addition, and the fix an engineer reaches for at 2am is to delete
the assertion.

### Fixed — the gate self-test reported "no python found" on machines that had one

**No schema changed, no declaration changed, and no consumer is affected.** The
candidate list, the order, the version floor and the `ANYWAYE_GATE_PYTHON`
override are all exactly as they were. What changed is one condition inside the
loop, and three cases that prove it. This **fixes a false negative** — it can
only turn a previous `exit 1` into a run, never the reverse.

- **`harness/tests/gate_self_test.sh` walks the whole candidate list and stops at
  the first interpreter that PASSES the version check**, rather than at the first
  one that merely *resolves*. The loop used to `break` out of
  `python3 python3.13 python3.12 python3.11 python` as soon as `command -v`
  succeeded and check the version afterwards, so a candidate that RESOLVES was
  mistaken for a candidate that QUALIFIES.
- **What that cost, on a real machine rather than a thought experiment.** Where
  `python3` is 3.9.6 the search took it, stopped, and printed
  `gate_self_test: no python >= 3.11 found; set ANYWAYE_GATE_PYTHON` while 3.13
  and 3.14 sat unused on the same PATH. A **false negative in the project's own
  proof-of-failure** — the one script whose job is to prove the gate checker can
  go red, reporting that it could not run at all — and indistinguishable from a
  machine that genuinely has nothing. That indistinguishability is why it
  survived: the only way to see it is to be the developer whose `python3` is
  3.9.6, while `bin/prime` exports `ANYWAYE_GATE_PYTHON` and CI runs on
  `setup-python`, so the machine that could show it was the one machine nobody
  ran it on.
- **`ANYWAYE_GATE_PYTHON` is honoured exactly as before**, including the half that
  is easy to break while fixing the other: an override that is **too old is still
  an error**, not a reason to go looking for a second interpreter. Quietly
  substituting a different program would make every `PASS` line below a claim
  about an interpreter nobody chose. Both halves are asserted, and the override
  case was proved load-bearing by breaking only the refusal: it then reports
  `exited 0` and answers with the host's own 3.14.
- **`resolve_interpreter` is the only place this decision is made**, and
  `--which-python` runs that decision and nothing else, so the cases drive the
  real search rather than a copy of it. One line, deliberately: asking the winner
  for its version too would probe it twice and put a second copy of its name in
  the trace the cases assert exactly.
- **`harness/tests/fixtures/interpreter-path/`** — two PATHs, no repository and no
  declaration in either, so nothing here is checked by `gate_check.py`. `stale-first`
  is a too-old `python3` followed by a qualifying `python3.13`; `stale-only` has
  all five names and every one too old. **The new-enough stub delegates to a real
  interpreter** (`sys.executable` of the one already running the script) rather
  than answering the version probe with a hardcoded `exit 0`: the bug is *when the
  loop stops*, not *what it decides about the interpreter it stopped at*, so only
  a real `sys.version_info` tells a fixed search from a broken one. For the same
  reason **no path to any interpreter is committed** — a red proof that passes on
  the machine that wrote it is not a red proof.
- **Three cases, all driving the real search through `--which-python`,** and the
  reason they all use that flag is a measurement rather than a preference. The
  `stale-first` case must end up on the *fixture's* `python3.13` and not merely on
  some new-enough interpreter — asserted on the whole path, because a bare
  `python3.13` would match the host's too. The `stale-only` case asserts exit 1,
  the **exact** refusal line, and **empty stdout** — empty because the exit has to
  come from the precondition rather than from some case failing forty lines in.
  The third pins a `ANYWAYE_GATE_PYTHON` that resolves and is too old, which stays
  an error rather than becoming a reason to go looking: that half is the easy one
  to lose while fixing the other, and a search that quietly answers with something
  else makes every `PASS` line in the script a claim about an interpreter nobody
  chose. It is a guard rather than a red proof — it stays green with the loop
  condition reverted, which is what a guard is for.
- **Every case asserts the trace — the ordered list of candidates actually
  consulted.** That is what separates *"tried the stale `python3`, rejected it,
  went on"* from *"happened to skip it"*, and on `stale-only` it is what proves
  the loop did not give up early. **An empty trace is the signature of this
  defect**: the probe is what makes a stub record itself, so a loop that stopped
  at the first name that *resolved* probes nothing at all. The failure message
  therefore says `<none — nothing was probed at all>` and carries the child's
  exit code and chosen path, because "consulted nothing" is otherwise
  indistinguishable from a broken fixture — the one diagnosis that would send
  someone to fix the wrong file.
- **All proved red before proved green, and the red is fast.** With the original
  condition restored: `stale-first` reports the 3.9.6 stub as the chosen
  interpreter at exit 0, `stale-only` reports the same stub at exit 0 instead of
  refusing, both with nothing probed. Nineteen seconds, ordinary non-zero exit,
  no leftover processes. `bin/prime` is green at `196/196 passed` both with
  `ANYWAYE_GATE_PYTHON` pinned and with it **unset**, and the self-test is also
  green run directly on a PATH whose `python3` answers `Python 3.9.6` with 3.13
  and 3.14 behind it — the run that used to print "no python found".
- **The `timeout` case no longer shells out to a bare `python3`,** which is a
  second-order fix this packet forced into the open. Its fixture gate used
  `python3` for a three-second CPU-bound wait, so on the developer whose
  `python3` is 3.9.6 the gate failed instantly and the case reported
  `gate.nonzero` where it meant to report `gate.timeout`. The search fix is what
  made that machine run the script at all, and the case then went red for a
  reason unrelated to the thing it tests. It is a pure-bash `SECONDS` wait now,
  because a case about the checker enforcing a budget has no business caring
  which python the gate happens to use. Still proved load-bearing: with the
  budget raised the case reports `expected exit 1, got 0`.
- **The obvious "stronger" test was a trap, and this is the sentence to keep.**
  The `stale-only` case was first written to run the **whole script** and assert
  its exit code, on the reasoning that with no qualifying interpreter the script
  exits at the precondition and there is nothing to recurse into. That reasoning
  is false the moment the search is broken — which is the only time the case
  matters. The child resolves the stub, the precondition lets it through, and the
  child runs every case down to that one and spawns another child. Measured:
  eighteen seconds in, `97132 -> 97666 -> 97667 -> 98130`, each link a
  `gate_self_test.sh` whose parent is the last, still growing, killed by hand. So
  it passed on green code and **exhausted a machine on broken code** — inside
  `bin/prime`, where the declaration allows 900 seconds, it would have spent
  those and reported a timeout that names nothing. Every case here drives
  `--which-python`, which runs the same search and the same refusal and stops
  before the first case; the flag's branch sits *after* the precondition, so on a
  PATH where the search finds nothing the two runs are the same execution up to
  and including the exit.
- **`gate.yml`'s floor is unchanged at `minimum: 196`, and that is measured.**
  These are cases in a shell script, not tests in `tests/test_specs.py`, and
  `test_the_gate_floor_is_not_below_the_suite_core_claims_to_have` counts
  `test_*` functions there. `bin/prime` prints `196/196 passed` on this tree.

### Added — the tenant-isolation declaration

**No schema a service consumes changed**, and no manifest, envelope, payload,
SLO or gate declaration is constrained by any of this. A service that vendors
`schemas/` picks up one new file it does not use and is unaffected. There is no
**contract change** and nothing to re-vendor; the cost of adopting this is
opt-in and is a file a service writes about itself.

- **`schemas/tenant-isolation.schema.json`** — one file per service at its root,
  `tenancy.yml`, declaring the account-scoped entry points, the **file and line**
  where each is scoped, the mechanism (`query-filter`, `bind-parameter`,
  `repository-method`, `middleware`), and the negative assertion each one
  requires — `negative.asserts` is a `const: absent`, because cross-tenant access
  is answered as **nonexistence**, never as a refusal. `accountScoped` is a
  required boolean so a service with no boundary says so with an explicit,
  checkable zero rather than by omission.
- **`harness/tenancy_check.py`** and `harness/bin/tenancy-check` — a checker of
  declarations, standard library only, reporting `{ok, warn, fail}` with
  **`warn` never moving the exit code**. It proves the declared files and lines
  exist, that each declared line still carries the tenancy key (or the bind it
  names), that the enumeration is **closed in both directions** against the SQL
  it can read, and that every negative assertion is in the service's tests and
  asserts absence. It runs on Python 3.9: no TOML, no subprocess, unlike
  `gate-check`'s 3.11 floor.
- **`harness/tenancy_findings.json`** — the sixteen findings, each with the claim
  it makes and the exact command that fixes it, plus five `notEnforced` entries
  saying what the checker does **not** prove — including that it reads the
  negative assertion rather than running it.
- **`harness/tests/tenancy_self_test.sh`** — the red proof: one conforming
  fixture and three more (an honest zero, and a language the scanner cannot
  read), sixteen deliberate breakages each asserting the checker goes red **and
  names the finding and the entry point**, three warning cases asserting a
  warning stays green, and two green cases asserting the report names what the
  checker cannot see. The control is asserted **warning-free**, not merely green.
- **Six worked examples** — `examples/valid/tenancy.account-scoped.yml`,
  `examples/valid/tenancy.honest-zero.yml`, and four negative cases with their
  tables in `examples/invalid/README.md`.
- **`docs/tenancy.md`** — why the enumeration is declared rather than inferred
  (counting account-scoped routes by pattern gives 96 for guard and **0** for
  darkroom, and a grep reporting "no routes" about a service with account-scoped
  queries is worse than no grep), why the line is exact, why `insert` is not an
  operation, and what the checker cannot prove.
- **core's CI runs the tenancy self-test as a step of its own**, beside the gate
  checker's and the harness's. A self-test nobody invokes is not a test.
- **Fourteen tests in `tests/test_specs.py`**, and the `gate.yml` floor raised to
  187 with them. They are not only inventory and documentation checks: the
  fourteenth drives **every failure-severity finding through `check()` in the
  suite itself**, one case per finding, because the self-test is a CI step and
  not part of `bin/prime`. Measured before that test existed, deleting
  `check_denials` from the checker left `bin/prime` reporting 186/186 passed —
  a green gate over a checker that no longer checked. Deleting any of the six
  check functions now turns the gate red.

Measured against the fleet, every repository fails with
`tenancy.declaration-missing`: none of the thirteen publishes a boundary. **No adopter
was fixed in this packet** — a contract with no failing adopter is a contract nobody
has tested against reality.

### Added — the gate declaration

**No schema a service consumes changed.** `schemas/gate.schema.json` is new and
nothing in it constrains a manifest, an envelope, a payload or an SLO, so a
service that vendors `schemas/` picks up a file it does not use and is
unaffected. The one **contract change** is core's own: `mise run test` is now an
alias for `mise run prime`, so the fleet's spelling of "run the gate" is right
here too, and `mise run test` keeps working.

- **`schemas/gate.schema.json`** — one file per repository at its root, `gate.yml`,
  declaring the gate command as an **argv** (never a shell string), whether the
  gate is self-contained or what it needs from the machine and the command that
  satisfies each thing, the CI workflow that must agree, and `gate.proof` — the
  patterns the gate's own output must contain, with an optional `minimum` floor.
- **`harness/gate_check.py`** and `harness/bin/gate-check` — a checker of
  declarations, standard library only, reporting `{ok, warn, fail}` with
  **`warn` never moving the exit code**. Two phases: the static one compares the
  declaration to the tree, and `--prove` also **runs** the gate and requires
  every declared proof to appear. A run that exits 0 having run nothing is
  `gate.proof-missing`, and it is a failure.
- **`harness/gate_findings.json`** — the twenty-two findings, each with the claim
  it makes and the exact command that fixes it, plus three `notEnforced` entries
  saying what the checker does **not** prove.
- **`harness/tests/gate_self_test.sh`** — the red proof: one conforming fixture
  copied twenty-three times, one breakage each, every red asserting the exit
  code is 1 **and** naming the finding it expects; five warning cases asserting
  the exit code is still **0**; and a case proving the checker's report does not
  carry a value out of the gate's environment.
- **`gate.yml`** and **`docs/gate.md`** — core's own declaration, and the
  document that measures the two alternatives it is not: mise tasks alone, which
  can be run but not checked, and a CI-only declaration, which cannot be run
  locally and has no second copy to drift against.
- **Two examples and four negative cases**, each with a row in
  [`examples/invalid/README.md`](examples/invalid/README.md).
- **A CI step for the proving phase and one for the red proof.** `bin/prime` runs
  the static half only, because the proving half runs `bin/prime`; a gate that
  verifies itself by running itself proves nothing and terminates.

**D30** (a proof, or a description), **D31** (3.11 for the gate checker, 3.9 for
the contract harness) and **D32** (no CI is a warning) are open.

### Fixed — a proof is matched against bytes that still carry terminal colour

**No schema changed.** `schemas/gate.schema.json` is untouched, so this is a
checker behaviour change and a documentation change. It **fixes a false red and a
false green**, and it can turn a previously-green declaration red — see below.

**Ruled as MD17** (manager-owned, in the workspace `DECISIONS.md`, not one of
core's `D` numbers): the checker strips ANSI from the gate's captured output
before applying any `proof[].match`. The direction is not re-opened here; the
implementation notes are in `harness/gate_check.py` and the format rules are in
[`docs/gate.md`](docs/gate.md#the-output-is-matched-colour-free).

- **`harness/gate_check.py` strips ANSI from the gate's captured output before
  applying any `proof[].match`.** One `strip_ansi` function, one call site, in
  `prove()` where the output is read; stripping inside each of the four checks
  that apply a pattern is four call sites that will drift. The gate's **log keeps
  the raw bytes** — stripping applies to matching only, because the log is the
  operator's evidence.
- **Why it was a defect in the checker and not in a declaration.** A person writes
  a proof pattern by reading their terminal, and a terminal does not show them the
  bytes. `^[ ]*Tests[ ]+([0-9]+) passed` is correct for the line a human sees and
  cannot match `\x1b[2m      Tests …`. That produced `gate.proof-missing` on a gate
  that had just proved, in the same log, that it ran 377 tests. Not vitest-specific:
  `cargo test`, `pytest`, `go test` under a TTY and colour-enabled `mix test` are
  the same shape.
- **The quieter false green this also removes.** `\x1b[38;5;208m` is a 256-colour
  **index**, so a gate that ran 3 tests and printed `\x1b[38;5;208m3 passed` matched
  `^.*?([0-9]+).* passed$` with group(1) equal to `38` — `minimum: 38` was green
  over a suite of three.
- **Sequences handled:** CSI (`ESC [ … final`, and 8-bit `0x9b`), OSC (`ESC ] …
  BEL`/`ST`, and 8-bit `0x9d`), DCS, and the two-character escapes. **An
  unterminated sequence is deliberately left in place** rather than consumed to
  end-of-input, which would delete every following line — the proof included — and
  manufacture a green.
- **What stripping does to a pattern, stated in
  [`docs/gate.md`](docs/gate.md#the-output-is-matched-colour-free) rather than left
  for an adopter to discover.** It can **broaden** an anchored pattern to a line it
  could not reach, and since `minimum` reads the **last match**, that can change
  the number the ratchet sees; and `.` counts escape bytes before and visible bytes
  after. What is unconditional is that stripping only ever **deletes**, so it
  cannot fabricate a match.
- **Three green cases and two colour reds** in
  `harness/tests/gate_self_test.sh` — a colourising gate that really ran, a proof
  behind an OSC hyperlink, a proof below an unterminated OSC, and two that must
  still go red (an absent proof, and a suite below its floor) so the stripper
  cannot swallow evidence.

**Adopters: re-read your `proof[].match` patterns.** They are now applied to
colour-free text. A pattern written to match escape-bearing bytes stops matching;
one that relied on `^` being blocked by an escape may now match more lines. Both
are documented above and in `docs/gate.md`.

### Fixed — the local gate was weaker than CI, and nothing said so

**No schema changed. No declaration format changed. Nothing an adopting
repository has to do.** `harness/gate_check.py` is untouched, `gate.yml` is
untouched apart from its proof floor, and a service's `gate.yml` means exactly
what it meant. What changed is **core's own `bin/prime`**, and one number in it.

- **`bin/prime` now runs `harness/tests/gate_self_test.sh`, the gate checker's own
  red proof, and its failure fails `bin/prime`.** It used to be a CI step only.
  So a developer on a clean checkout ran the one command core's own
  documentation and every adopting repository's `mise.toml` name, saw
  `179/179 passed`, exited 0 — and had learned **nothing** about whether
  `harness/gate_check.py` could detect anything. Replace the checker with a
  function that returns 0 and `bin/prime` stayed green while CI went red, which
  is the definition of a local gate that does not gate.
- **It is not the recursion the static half avoids.** `--prove` runs the declared
  gate, and core's declared gate is `bin/prime`, so `bin/prime` must never call
  it — that reasoning stands and is unchanged. The red proof is different in kind:
  it runs assertions about the checker in throwaway copies of
  `harness/tests/fixtures/gates/conforming`, a repository whose declared gate is
  three lines long and is not `bin/prime`. Nothing in it reads core, runs
  `bin/prime`, or knows this repository exists, so there is no cycle. They also
  answer different questions: `--prove` asks whether *this* gate ran, and a
  checker that could only say *yes* would look exactly like a passing gate to it.
- **It cannot skip, and its report is read.** A missing script, no `bash`, or an
  interpreter older than 3.11 is a non-zero exit naming the precondition — never
  the word "skipped". A red proof that exits 0 having printed **no counts** is
  refused, because an exit code is not a report. The counts block is parsed: every
  category must be present and non-empty, the control must have printed its own
  `PASS` line, the skip count must be zero, and the logged case lines must cover
  the counts. Pass and skip counts are printed **separately**, because a single
  number where there are two is how a skip hides inside a pass.
- **It runs on the pinned interpreter.** `bin/prime` exports
  `ANYWAYE_GATE_PYTHON` as the venv interpreter — the same one the suite runs on —
  instead of letting the script scan `PATH`. Without that, a local gate would
  depend on the machine: a laptop whose system Python is 3.9 fails a checkout CI
  is green on, and one on 3.13 proves something CI did not.
- **The red proof's own counts were wrong, and were fixed.** Its footer printed
  `breakages that went RED: 25`. **Eighteen** cases went red. The 25 was a
  hand-incremented *case label* — incremented before warnings too, so that
  printed lines can be referred to by the same number the comments use — printed
  as if it were a tally, and it counted seven warning cases that stayed green. Each
  category is now counted inside the function that runs it, every category has a
  row (three had none: the colour cases and the leak case), and the footer prints
  variables rather than literals. Measured now: **18 red, 7 warning-green, 3
  colour-green, 2 colour-red, 12 spellings accepted, 4 extractor assertions, 1
  leak case, 1 control, 0 skipped.**
- **Cost, stated because a cost nobody mentions is a cost somebody rediscovers:**
  `bin/prime` goes from about 20 seconds to about 58, warm. The red proof runs
  **last**, after the suite, so a red suite still costs 20 seconds and not 58. The
  proof floor in `gate.yml` is 900 seconds, so CI has room. Six tests were added
  to `tests/test_specs.py`, so the floor moved 173 → **179** in the same commit.
- **One sharp edge this introduces is closed.** `gate.proof` is matched against
  everything `bin/prime` prints with the floor reading the **last** match, and a
  second program now prints into that output — so a proof-shaped line from the red
  proof could satisfy the gate's proof or be read as the floor's number. Every
  literal `printf`/`echo` in the red proof is checked against every pattern
  `gate.yml` declares, with conversion specs filled in as digits.
- **Asymmetry, deliberate.** `harness/tests/self_test.sh` — the **contract**
  harness's red proof — is still CI-only. The gate checker's red proof runs
  locally because it guards the checker `bin/prime` ran on the line above.
  Reasoning in [`docs/gate.md`](docs/gate.md#the-third-thing-binprime-runs-and-why-it-is-not-the-recursion).

### Added — the SLO and error-budget spec

**No event, envelope or manifest changed; every existing schema is untouched.**
Three new files under `schemas/telemetry/`, so a service that vendors
`schemas/` picks them up when it re-vendors, and nothing in a conforming
service's world moved. What *is* a contract change is the thing this packet
specifies for the first time: what an SLO is.

- **Three schemas and one document.**
  [`slo.schema.json`](schemas/telemetry/slo.schema.json) is one service's
  declaration — a Sloth `prometheus/v1` file, which is the artifact R1 settles on
  because `sloth validate -i slos/` is a single static binary that walks a
  directory with no cluster and no Docker daemon, because it *generates* the
  recording rules and the burn-rate alerts, and because its SLI is two PromQL
  strings: **the one representation all six languages can be checked against
  without a Go or Rust parser.**
  [`slo-windows.schema.json`](schemas/telemetry/slo-windows.schema.json) is the
  burn-rate catalog, pinned once for the fleet.
  [`slo-metrics.schema.json`](schemas/telemetry/slo-metrics.schema.json) is the
  SLI catalogue and label allowlist — **the mechanical check that replaces a
  shared client library**, which is what six languages would otherwise each grow
  a copy of. [`docs/slo.md`](docs/slo.md) is all three written as prose.

- **The tier alone decides whether a page is generated** (R4), and the schema
  derives both alert switches from it. `critical` and `high` page and ticket,
  `low` tickets, `none` publishes nothing. Required, with no default. A page per
  SLO across seven services is textbook alert fatigue, and the cost is not the
  page: the self-hoster who mutes one at 3am about a twenty-user deployment has
  also muted the `critical` SLO, and the instrument is gone in one gesture.
  `page_alert.disable: false` on a `low` SLO does not validate, and the negative
  example is that document with nothing else changed.

- **The burn-rate windows are 14.4/6/3/1 at 5m+1h, 30m+6h, 2h+1d, 6h+3d**, pinned
  byte-wise by `prefixItems` — *order included*, because the generator consumes
  them in short/long pairs and a reordered catalog still validates as a set while
  producing four alerts with the wrong pairing. Per-service windows are refused:
  Sloth takes `--slo-period-windows-path` for exactly that, which is why the
  declaration is closed.

- **The arithmetic is published because the number will be questioned**, and
  **it does not agree with the period.** R2's `14.4 = 0.02 x 720h` is a *thirty*-day
  budget; R3's period is twenty-eight days, where 2% is 13.44. Both are
  implemented as ruled, so the fleet's fast-burn alerts fire about **7% early** —
  the safe direction — and
  `test_the_window_catalog_is_the_workbooks_numbers` asserts the workbook's
  arithmetic, the 28-day arithmetic *and the direction of the gap*, so the
  inconsistency cannot harden into a number nobody recomputed. **D27**.

- **An SLO is scoped to a named user-visible operation, not to a service.**
  `authentication_succeeds` therefore *requires* `http_route`: an SLO whose total
  is every request identity ever served can be green while nobody can log in.
  The four candidates are already written out — authentication, an event
  accepted into an outbox, an email dispatched, an invoice computed — each named
  after the **operation**, never after a service, and each with the Postgres-
  normalized metric names it needs. **No service declares one yet**: an SLO
  written before the metric exists is a commitment nobody can keep, so which tier
  each service gets is **D29** and the packet stops here.

- **An objective is never 100%**, as `exclusiveMaximum: 100` rather than a
  comment. An objective of 100% has an error budget of zero, so no burn rate is
  worth interrupting anyone for and the alert can only be *reacted to*. That
  needed two keywords the harness did not implement, so the evaluator grew
  `exclusiveMinimum`/`exclusiveMaximum` and
  `test_the_harness_evaluator_agrees_with_jsonschema_on_every_example` now covers
  all three SLO schemas — which is where `if`/`then` inside `prefixItems`,
  `const` beside a `$ref`, and `not` on a string get their receipts too. The
  keyword inventory asked for them by name before the harness had them:
  *core's schemas use ['exclusiveMaximum', 'exclusiveMinimum'] and
  harness/anywaye_contract.py does not implement them.*

- **Two denylists, because there are two reasons.** Unbounded dimensions
  (`tenant`, `user_id`, `account_id`, `request_id`) are barred on the
  2000-combination-cap grounds `metrics.schema.json` already established;
  infrastructure signals (`cpu`, `memory`, `pod`, `restart`) are barred because
  an SLO on them is not an SLO on behaviour. One merged list would keep the
  enforcement and lose the second reason, which is what a reader has at the
  moment they are about to add one. The schema's `not` is asserted to be exactly
  the union of the two lists, so neither can describe something the schema does
  not enforce.

- **The multi-tenancy question is answered here rather than deferred.** The
  metric is aggregate; per-tenant views are **recording rules and logs and
  traces** over the `resourceAttributes`, because the measurement attributes that
  count toward the cap are exactly where `tenant_id` is bargained out and the
  resource attributes are where it is exempt. `docs/slo.md` says so in one
  paragraph with the reason, because the next reader will ask and "the metric
  schema already prohibits it" is the answer.

- **The spanmetrics migration is specified, and the collector is what moves.** A
  service derives its HTTP SLI from **native** OpenTelemetry instrumentation, never
  from a `spanmetrics`-derived metric: the connector's unit default is migrating
  from `ms` to `s`, which renames
  `traces_span_metrics_duration_milliseconds_bucket` to `…_seconds_bucket` and
  breaks every latency query in every service at once — between the service and
  Prometheus, where no service-level test can see it. The collector version is
  pinned in the kit templates and **a bump is a breaking change**.
  `http.server.request.duration` is Stable with recommended bucket boundaries,
  and `http.route` is low-cardinality by construction, which is what
  `metrics.schema.json` already encodes.

- **No SLA, and it is a test.** The acronym appears in no `const`, `enum` or
  `default` under `schemas/` and in no example, and a `not` refuses it in any SLO
  prose. What a self-hoster gets instead is stated in the shape of an honest
  statement: **No SLA commitment.** Intended behaviour on adequate hardware,
  measured by the operator, with the exclusions published — which is the part
  that makes it honest, and which includes 4xx never counting as a failure and
  `email_dispatched` measuring *dispatched* rather than delivered.

- **Eight harness rules, twenty-eight breakages, and two the self-test caught
  in my own code.** `slo.schema`, `slo.window-token`, `slo.unknown-metric`,
  `slo.no-unbounded-dimension`, `slo.no-infrastructure-slo`,
  `slo.sli-canonical`, `slo.window-override` and `slo.duplicate-name`, each
  declared in `harness/rules.json` with where it lives and each proved able to go
  red by a breakage that **names the rule it expects**. The catalogue is read out
  of `schemas/` rather than copied into the harness, so `--expect-digest` covers
  it. Breakages 23 and 24 found that `_denylisted` scanned the queries and not the
  declaration's `labels` — where the mistake arrives first — so a `tenant_id` came
  back as `slo.sli-canonical`: a true statement about a consequence, reported in
  place of the mistake. It now scans three places.

- **`sloth validate` is not run by core's gate**, which is a decision and not an
  omission (**D28**). Taking the dependency would mean core's gate reaching the
  network for a Go binary on a runner that may be air-gapped, against a
  repository whose whole dependency story is one venv and four PyPI packages. The
  harness implements the checks that matter in the standard library, and
  `slo.sli-canonical` compares each query against the canonical composition *as a
  string* — stricter about the shape than Sloth is, blinder about the grammar.
  PromQL parsing is named in `harness/rules.json`'s `notEnforced`, and
  `docs/slo.md` gives the pinned command for a service that has network.

- **Twenty-one new tests, and the counts. Suite: 119 → 140.** Every schema has a
  valid document and a named invalid document per constraint; every harness rule
  has a breakage; `test_every_rule_the_harness_can_emit_is_proved_able_to_go_red`
  is new and asserts the self-test breaks *every* rule rather than a number of
  them. CI's two-entry-point guard reads the count out of both runs, so it moves
  in one place.

- **Four new open decisions: D26, D27, D28, D29.** **D26** — do the anywaye
  fields (`tier`, `period`, `labels`, `catalogEntry`) live inside the Sloth
  document or in a anywaye document kit converts? Sloth's tolerance of unknown
  keys could not be checked offline, so the answer is the one that leaves a
  four-line fallback. **D27** — the factors come from a 30-day budget and the
  period is 28. **D28** — may the gate take the `sloth` dependency? **D29** —
  which tier each of the seven services gets.
### Added — the contract-test harness

**No schema changed. No consumer has to re-vendor.** Nothing under `schemas/`
was touched, so there is nothing here that should make a service's vendored copy
stale. PLAN.md §4 Phase 0 named a contract-test harness among core v0's five
deliverables; three had shipped, the harness had not, and four services each
wrote their own version of it instead — muse's pinned-SHA byte comparison,
darkroom's vendored copy, courier's document-against-router test, pantry's drift
test.

- **`harness/`** — `bin/anywaye-contract`, `anywaye_contract.py`, `rules.json`,
  `tests/self_test.sh` and six fixtures. A service's CI is three lines:

  ```
  harness/bin/anywaye-contract --core ../core --expect-digest <sha256> .
  ```

  **Standard library only, no dependencies, offline.** A Python *package* would
  need a venv in a Go repository; a compiled binary would make core a release
  repository with per-platform artifacts, which is the one thing AGENTS.md rules
  out twice. A single file that imports nothing outside the standard library runs
  on every runner core and every service already builds on.

- **Exit `2` is a refusal, and it is not a soft `1`.** `0` conforms, `1` does
  not, `2` the run could not happen — no core, no manifest, or YAML outside the
  declared subset. A contract check that cannot find the contract and reports
  success is worse than no contract check, because it converts an unknown into a
  green badge. That is the defect behind guard's live-Redis tier, muse's
  `MUSE_CORE_SCHEMAS` tier, identity's `TEST_DATABASE_URL` tier and darkroom's
  `--ignored` tests, and
  `test_the_harness_fails_loudly_when_core_is_absent` is the assertion.

- **The pin is a sha256 over `schemas/`, not a git ref.** A ref names a commit in
  a repository the harness is not allowed to fetch; a digest names bytes, which
  is what a service compiles against. It covers all of `schemas/` rather than the
  two files a service happens to vendor, it is printed on every run, and
  `--expect-digest` turns "different" into a red build. muse's `CORE_REF` is the
  fleet's existing precedent and it is a *ref*; the digest is the same answer on
  a laptop and in CI, which a checkout step and a working directory are not.

- **Where each rule lives, field by field.** `harness/rules.json` gives every
  rule an `enforcedBy` — a schema file, a document and a heading, or a named
  function — and `test_the_rule_inventory_says_where_every_rule_lives` checks each
  claim is true. The honest answer is **one rule in `schemas/` and sixteen in the
  harness's own source**, and that is the finding rather than a failure of it:
  `docs/openapi-conventions.md` says in its own words that those rules are
  review-enforced "until a future `cafe contract lint` lands". See **D23**.

- **The evaluator and the YAML reader are receipts, not claims.** The standard
  library has no JSON Schema and no YAML, so core has a hand-written evaluator
  for the 27 keywords its schemas use and a reader for a declared subset of YAML.
  `test_the_harness_evaluator_agrees_with_jsonschema_on_every_example` compares
  violated keywords with `jsonschema` over every example in `examples/`, in both
  directions, and
  `test_the_harness_implements_every_keyword_core_schemas_use` holds the keyword
  list equal in both directions. It caught a real bug within the hour: a `type`
  array is a union, and the first version reported a violation per non-matching
  member, so the envelope's `data` — declared as any of seven types, correctly
  holding an object — produced six failures.

- **Twenty breakages, twenty reds, and a control first.**
  `harness/tests/self_test.sh` is kit's shape: every breakage names the rule id
  it expects, because "the harness went red" is a weak claim when seventeen
  checks can make it red. All seventeen rules have at least one. Writing it found
  that `event.payload-schema-missing` is structurally coupled to
  `event.unknown-published` — every catalogued type has a payload schema, so a
  published type without one is necessarily not catalogued — which is recorded in
  the inventory rather than papered over with a contrived fixture.

- **The self-test is a documented command CI also runs.** Not part of `bin/prime`:
  a self-test inside every gate invocation would be a second gate that can
  disagree with the first, which is what `tests/validate.sh` was written not to
  create. The CI step reads its own log and compares the breakages the footer
  claims against the assertions logged, and that guard was proved able to fail
  against three doctored logs.

- **Twenty-seven tests, and the counts. Suite: 92 → 119.** They are in a new
  section 7 of `tests/test_specs.py`, and the twenty-three that could be written
  before the harness existed were shown failing first, and the four added afterwards were shown
  failing against the reader they constrain — a named missing file each
  time, not a collection error. CI's two-entry-point guard reads the count out of
  both runs, so it moves in one place.

- **Four new open decisions.** **D22** (core's own suite does not assert
  `format: uri`, because `jsonschema` registers no checker for it without
  `rfc3987-validator` — the same gap `tests/requirements.txt` already documents
  for `date-time`, and the harness made it visible by checking it), **D23** (do
  the sixteen rules the harness keeps in code become a JSON Schema), **D24** (the
  event catalog and the spec version are markdown and prose, not data — so the
  harness parses a table and cannot resolve a `core:` constraint at all), and
  **D25** (may a service document `/healthz` and `/readyz`? three do, one
  deliberately does not with a paragraph explaining why, and
  `docs/openapi-conventions.md` does not say which is right — found by running
  the harness at the fleet, not by building it).

- **The YAML subset was reversed by the fleet, and that is the whole story of
  this packet.** The reader shipped reading a small subset and refusing
  everything else, on the reasoning that a guess means validating a document
  nobody wrote. Then it was pointed at the eleven real service repositories and
  **eight of eleven refused**: six on a `description:`, two on a leading `---`,
  the rest on `tags: [users]`.

  Guessing wrongly means a *schema* error printed against a value the harness
  invented, which sends a person to the wrong field. Refusing a document the
  whole fleet writes means the harness checks nothing at all. So the subset is
  now the one the fleet writes — block scalars with chomping and indentation
  indicators, plain scalars continued across lines, flow collections including
  across lines, floats, a leading `---` — and what is left is what no real
  document needed. Over the thirty-three real `anywaye.yml` and `openapi/*.yaml`
  files in the workspace: **thirty-three byte-identical to PyYAML, zero
  mismatched, zero refused.**

  The fold was the risky part and it was wrong twice: the first version tracked
  whether the *previous* line was more indented, the second whether the *next*
  one was, and billing's `change_plan` description is the document that showed
  both were wrong. YAML keeps the break on **both** sides of a more-indented
  line. `test_the_harness_yaml_reader_agrees_with_pyyaml_on_every_fold` is the
  receipt, and it is a separate test because a fold can be almost right.

- **What the harness found in the fleet on its first run.** Eight of eleven
  conform. `identity` publishes two OIDC client event types that core's catalog
  does not list and has no payload schema for, and `mfa.enabled`/`.disabled` have
  no payload schema either; `darkroom` publishes three event types with neither;
  and `identity`, `darkroom` and `pantry` all document `/healthz` and `/readyz`,
  which `courier` deliberately does not. Every one of those is checkable by hand
  today and none of it is checked by anything — which is the gap, in the only
  terms that matter. The probe finding is a spec gap rather than a service bug
  and it is **D25**.

- **What it does not do, in its own document.**
  [`docs/contract-harness.md`](docs/contract-harness.md) says so in the first
  third rather than at the end: it validates a service's *declared* contracts and
  never looks at a byte of live traffic, so PLAN.md §3's "each service's CI
  validates responses against the spec" — the richer reading of "contract test" —
  is **still owed**. `harness/rules.json`'s `notEnforced` block names four things
  it does not check and why.

- **This packet migrates no service.** One packet, one repository: a harness
  adopted by four services at once is four workers in four languages discovering
  four things nobody anticipated, and the manager would not be able to tell which
  of them found a bug in the harness.

### Added — CI, on kit's reusable workflow

**No schema changed. No consumer has to re-vendor.** This is build
configuration: nothing under `schemas/` was touched, so there is nothing here
that should make a service's vendored copy stale.

- **`.github/workflows/ci.yml`** calls
  `anywaye/kit/.github/workflows/ci.reusable.yml@master` with
  `language: 'none'`, plus a companion `gate` job that runs `bin/prime` on the
  interpreter `mise.toml` pins, `bin/prime --pytest`, and the drift guards.

  `none` rather than `python` because kit's `none` is documented for "a
  repository with **no service manifest at all**", which is what core is; the
  seven language jobs are not inapplicable here, they are red on arrival
  (`uv sync --frozen` exits 2 with "No pyproject.toml found" in a repository
  that has never had one and should not). `tests/validate.sh` is the three lines
  kit's contract looks for — an `exec bin/prime "$@"`, no logic — so there is
  still one gate and one suite.

- **Two tests, and the counts.** `test_the_ci_workflow_calls_kit_at_the_path_kit_documents`
  exact-matches the cross-repository `uses:` line, because a substring search is
  what let kit-02's unresolvable path through:
  `anywaye/kit/workflows/ci.reusable.yml@master` contains every interesting
  token and is the string that does not work.
  `test_core_declares_no_service_manifest` keeps `none` honest. Both were shown
  failing before the workflow existed, and the second was run against a scratch
  `pyproject.toml` to prove it can go red. Suite: **90 → 92**.

- **`git diff --exit-code` over the whole tracked tree**, which is kit's
  lockfile rule generalised. core has no lockfile, and the tree is what six
  services vendor: a gate that could rewrite a schema would put un-reviewed
  bytes into every one of them.

- **Both entry points must report the same number of tests.** Two entry points
  to one suite, and the cheap assertion is not "it exits 0" — it is that both
  collect 92. A renamed test or a module only the script runner imports is
  invisible in either log alone.

  Two bugs in that guard were found by running the step locally against real and
  doctored logs, not by reading it: `cut -d/ -f2` on `92/92 passed` yields `92
  passed`, and under `set -e` a `grep` matching nothing killed the step before
  its own emptiness check could explain itself.

**A red build here is not "core is broken"** — it is "a rule the fleet depends
on no longer holds", and the workflow says so at the top of the file, because six
repositories consume these schemas and a docs nit is the wrong escalation.

The pin is read from `mise.toml` and asserted against the interpreter that
arrives rather than written into the workflow twice. `python-version-file:
mise.toml` reads as if it should work and **silently installs nothing**: the
action looks for `project.requires-python` or `tool.poetry.dependencies.python`,
and mise's `[tools]` is neither.

There is **no environment-gated tier** in this repository, and none is
implied: 92 tests, no `os.environ` read anywhere in `tests/test_specs.py`, no
skip, no database, no network beyond `tests/setup.sh`'s four PyPI packages.

### Changed — `error.type` is a closed vocabulary, and the status error obliges it

**BREAKING for a service that emits a class, and for kit-03, which is reading
these schemas in parallel.** muse is the only service that emits one today and it
is **not** migrated here — see "not migrated" below.

- **`error.type` is an `enum`, not a `pattern`, on all three signals.** The
  twelve classes plus `_OTHER`, byte-identical in
  [`traces`](schemas/telemetry/traces.schema.json),
  [`metrics`](schemas/telemetry/metrics.schema.json) and
  [`logs`](schemas/telemetry/logs.schema.json).

  **Why.** The previous constraint was a `pattern` and a 64-character cap, which
  bound the **shape** of the value and not the **vocabulary** — so
  `error.type = "user_42_email_invalid"` validated cleanly on every signal.
  Snake_case, twenty-two characters, a series per value. On metrics that is
  `tenant_id` on a measurement under a name that sounds like a classification:
  the same 2000-combination cap, the same silent undercount, the same dashboard
  that renders and is wrong. The description promised a bounded vocabulary and
  the schema did not have one, and a rule the schema does not enforce is not a
  anywaye rule (**D14**, ratified, now implemented). The `pattern` and the cap
  stay alongside the `enum` as the second line — they cannot reject a value the
  `enum` accepts — and a test asserts all three copies are byte-identical.

  One `enum` on all three signals is not tidiness. It is what makes the semconv
  rule that `error.type` is **identical** on a span and on its metric for the
  same operation enforceable at all: no JSON Schema can compare two documents, so
  the coupling has to be structural.

- **Four semconv rules encoded rather than described.** core-04 stated these and
  enforced none of them; with `error.type` deleted from `span.muse.json` the file
  still validated. They are constraints now, with negative examples.

  - **Span status `error` obliges `error.type`, and `error.type` obliges a failed
    status.** The biconditional is the point: the class is present exactly when
    the span failed, so its **absence is the load-bearing not-an-error marker**
    rather than an omission. On a duration histogram the samples carrying the
    class are the errors; a success that carries one moves the numerator and
    makes the error rate a number nobody can trust.
  - **`otel.status_code` may not contradict `status.code`.** Not a fifth rule —
    without it the first one is about a span with two statuses, which has no
    status to be obliged.
  - **Handled and retried errors are not recorded at all.** `SHOULD NOT` has no
    schema keyword, so it is encoded as **unrepresentable**: no signal allowlists
    an attribute a service could use to say "this attempt failed and I
    recovered", and no class in the vocabulary names one. The realistic
    violation is a well-meaning `error.handled: true` added in six months, and it
    now fails the suite.
  - **`error.type` is required on the operation duration histogram and absent on
    success** — the doc states it and the first rule above encodes the
    success half of it.

- **`error.message` stays absent, and its reasoning is kept in full.** It is
  `NOT RECOMMENDED` for metrics and spans: unbounded cardinality, and it
  duplicates span status. More concretely it is the one attribute already on a
  natural allowlist — every tracing SDK adds it by default — and the one that
  could carry a prompt, because a provider's content-policy rejection quotes the
  offending content back. That refusal is now recorded as `provider_rejected`,
  which says what happened with no content in it.

- **Two structural claims that were described everywhere and asserted nowhere,
  now asserted.** Found by mutation against core-04: deleting
  `additionalProperties` from the traces allowlist left the suite **green**, and
  adding `critical` to the span-status enum left it **green**. The status enum is
  the fleet-wide error predicate, so a fourth value invented by one service is a
  dashboard that silently misses it — which is exactly what the schema's own
  description promised could not happen.

- **Two more decisions**, both four paragraphs and both raised by core-06 rather
  than by the observability work: **D20** (kit's `language: none` job installs no
  interpreter, so the `kit` job runs the suite on the runner's own Python and
  only `gate` is pinned) and **D21** (a breaking schema change still has no
  re-vendor fan-out, even though six services vendor these schemas). D21 changes
  nothing in this release: **nothing under `schemas/` was touched**, so no
  consumer needs to re-vendor, and the gap is recorded rather than closed.

- **Two new decisions**, both four paragraphs: **D18** (which twelve classes, and
  the test — is this class's rate worth an alert on its own? — rather than the
  list) and **D19** (whether semconv's `_OTHER` belongs in a snake_case
  vocabulary; it is the one documented exception, because a closed enum with no
  escape hatch gets widened under pressure and an alert on `_OTHER` is an alert
  that this service has not classified its own errors).

- **Stability marked honestly.** `error.type` and the trace status rules are
  **Stable**; the cross-signal coupling document, `recording-errors.md`, is
  **Development**. Where core encodes that coupling, each schema says so rather
  than implying the whole model has frozen.

- **The fleet-wide predicate is span status `Error`, not `error.type`** — stated
  plainly in [`docs/observability.md`](docs/observability.md#errortype) rather
  than left to be implied by the schema's shape. Partition by `service.name`,
  filter on status `error`, use `error.type` as a drill-down **inside** a
  service, and **never as a global grouping key**.

- **Not migrated, deliberately: muse.** It emits `error.type =
  "ProviderAuthError"` and `"CircuitOpen"`, and
  `tests/test_trace_propagation.py` asserts both. That is D14's stated cost of
  flipping and it is a separate packet; this one changes the contract. The
  file-by-file mapping a cold author needs is a table in
  [`docs/observability.md`](docs/observability.md#what-is-not-migrated-yet).

- **Sixteen new tests, and fifteen more examples** — one valid span per class,
  so `ls examples/valid/telemetry/error-type.*` is the whole vocabulary, plus
  five negative examples including the one that matters most: a well-shaped,
  snake_case, under-64-characters value that is not in the vocabulary, on traces
  and on metrics. The test asserts that value produces **exactly one** violation
  and that it is the `enum`, so it cannot pass because the pattern caught it —
  only the vocabulary can. The doc's class table is asserted against the schema
  too, so the two halves of the contract cannot drift apart quietly.

  Mutation-proved thirteen ways, all red. The one that caught a test of mine:
  deleting the `otel.status_code` mirror rule left its test green, because the
  document it built also tripped the rule above it — a test passing on someone
  else's constraint.

### Added — the observability spec

- **[`schemas/telemetry/`](schemas/telemetry/) and
  [`docs/observability.md`](docs/observability.md)** — the observability spec
  (PLAN.md §7b), as seven schemas and 33 tests. Core owns the event envelope the
  same way, so this is a contract and not a README paragraph: a rule that is not
  in `schemas/` is not a anywaye rule, and six services in six languages would each
  otherwise invent their own span names and their own idea of which attributes
  are safe.

  - **`span-naming.schema.json`** — one scheme, all six languages:
    `<service>.<operation>[.<target>]`, the same *shape* as the event grammar's
    `<service>.<entity>.<action>` and for the same reason. Low-cardinality **by
    construction**: a segment is at most fifteen characters, which is what
    refuses `muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` without core growing a
    anywaye-id pattern to recognise one. `GET /users/:id`, `get_user` and
    `users.GET` are all rejected, and `get_user` and `users.GET` are what a
    fleet ships when nobody has said. **D15** records the alternatives, including
    the OTel HTTP convention (`{method} {route}`), which is rejected for putting
    the route in the name.

  - **`metrics.schema.json`** — the part with teeth, and the reason this packet
    exists. OpenTelemetry caps a metric stream at **2000 distinct attribute
    combinations**; on overflow the SDK folds everything into a single
    `otel.metric.overflow=true` point and drops every measurement attribute.
    Totals stay correct, per-dimension breakdowns silently undercount, and
    nothing anywhere reports an error. So `tenant_id`, `user_id`, `account_id`,
    `request_id`, `trace_id` and eight more are **prohibited** as measurement
    attributes and **required** on `resourceAttributes` instead, which are
    attached once per process, exempt from the cap, and survive on the overflow
    point — so a per-tenant total stays answerable when the measurement has
    folded. The prohibition is enforced twice (absent from the allowlist *and*
    named in a `not`, so adding it to the allowlist later does not quietly
    succeed), the two lists are disjoint by construction, and a test asserts that
    a resource name is *rejected* when submitted as a measurement attribute.
    That last one is the mechanism: moving identity onto the measurement to get
    a per-tenant breakdown is what produces a dashboard that looks right and is
    wrong.

  - **`redaction.schema.json`** — prompt and completion content must never appear
    in a telemetry span, encoded as an **allowlist, default-deny**, because
    "don't log prompts" in prose has been tried across this fleet and does not
    hold. The realistic leak is not an attacker; it is a well-meaning
    `muse.prompt` added in six months by someone debugging a routing decision, in
    a service whose prompts are other customers' data. No allowlisted name on
    any of the three signals contains a word that names content — muse's canary
    at `muse/tests/test_trace_propagation.py`, promoted to a spec assertion.
    `error.message` is prohibited *by name* because a tracing SDK adds it by
    default and a content-policy rejection quotes the offending content back, so
    it is a prompt by another route. The may-record side is in the schema too
    (token counts, model id, latency, status, finish reason), because a policy
    that only says what may **not** be recorded is not implementable.
    `enforcedAt` is an enum with `collector` as the only value a anywaye policy may
    carry, so kit's collector config and a service's SDK setup are both checked
    against one file. **D13** argues the enforcement point with evidence.

  - **`otel-endpoint.schema.json`** — `*_OTEL_ENDPOINT` is the contract, the
    shipped collector is only its **default value**, and `required` is a
    `const: false`, which is the field that separates on-by-default from
    mandatory. The no-op path is four negative properties — **no buffering, no
    retry, no warning spam, no dial at boot** — each pinned to `none`, so a
    declaration that admits any of them does not validate. It is implemented by
    the OTel spec's own `OTEL_SDK_DISABLED`, not a anywaye invention, because
    re-implementing "disabled" in six languages is how six services acquire six
    definitions of it. `disabledBy` is keyed by signal and requires all four, so
    a declaration cannot document a no-op that covers only traces — a service
    still phoning home for metrics is discovered by a customer's invoice.

  - **`probes.schema.json`** — `healthz` gets `maxItems: 0` and `readyz` gets
    `minItems: 1`, so **a `readyz` that checks nothing fails the schema** and a
    `healthz` that starts consulting the database cannot validate. The second is
    the restart loop: a liveness probe that fails on a dependency restarts a
    process that is fine, turning a database outage into a fleet-wide crash loop
    and destroying the evidence needed to diagnose it. darkroom is the pattern
    (`/healthz` never touches a dependency, `/readyz` really runs `select 1`),
    and both probes are `auth: exempt` by explicit path allow-list, because a
    probe behind the auth middleware returns 401, every instance is marked
    unhealthy, and the rollback says nothing about authentication.

  - **`traces.schema.json` / `logs.schema.json`** — the other two per-signal
    allowlists, with the same rules applied. Logs are the smallest by design
    (`maxProperties: 12`, well under OTel's default 128): every log attribute is
    a candidate for a Loki label, every label is a stream, and streams are what a
    log store runs out of.

- **`error.type` as the fleet's error grouping key.** The user asked whether
  there is one place to see all errors for the whole system; this is the part of
  the spec that makes the answer yes rather than a wall of ungrouped text. It is
  a low-cardinality class — snake_case, ≤ 64 characters, the same shape on every
  signal — and never a message, a stack trace, or a per-service exception class
  name, because `ProviderAuthError` (Python), `ErrProviderAuth` (Go) and
  `ProviderAuthError` (Elixir) are one failure in three taxonomies, and three
  taxonomies means six places rather than one. **D14** has the alternatives and
  the cost, including the fact that flipping it touches a muse test.

- **`fleet.yml` gains a required `telemetry` block per service** — which
  signals it exports today, which `*_OTEL_ENDPOINT` variable points at it, and
  whether it serves HTTP. Required, so "what is instrumented across the fleet"
  has one answer rather than six, and so a service dropped from the declaration
  is a service nobody checks. Every service currently declares `signals: []`
  except muse, which is the honest record rather than claiming instrumentation
  that is not there.

- **Five new numbered decisions**, all with the four paragraphs AGENTS.md asks
  for: **D13** the redaction enforcement point, **D14** `error.type` granularity,
  **D15** the span-name form, **D16** the endpoint variable name, and **D17** a
  divergence this packet found rather than fixed.

### Fixed

- **A cross-repo drift the observability spec made visible.** `muse` reads
  `MUSE_OTEL_EXPORTER_OTLP_ENDPOINT` — the OpenTelemetry standard spelling,
  which is what `muse/tests/test_resilience_config.py` asserts — while
  `muse/tests/test_telemetry.py` and PLAN.md §7b both call it
  `MUSE_OTEL_ENDPOINT`. Three places, three spellings, and the code agrees with
  neither document. Core specifies `<SERVICE>_OTEL_ENDPOINT` (**D16**), `fleet.yml`
  records the divergence, and **D17** carries it as an open decision with the
  alternative (adopt the OTel standard names, in which case muse is already
  conforming and the divergence disappears) rather than leaving it only in a
  commit message. No service was modified: muse is a read-only reference here.

### Added — the payload reconciliation

- **[`fleet.yml`](fleet.yml) and
  [`schemas/fleet.schema.json`](schemas/fleet.schema.json)** — a machine-readable
  record, per service repository, of what that service's own `anywaye.yml`
  declares on `master`, with the full 40-character commit each one was read at
  and the day it was read. Per service, three lists: `events` (published today,
  in the conforming three-segment form), `cataloguedOnly` (a catalog row nobody
  publishes yet — a promise, not a claim), and `manifestViolations` (types a
  manifest spells in a way that breaks the grammar, transcribed verbatim).

  **Why.** The catalog was asserted only against core's own
  `examples/valid/*.anywaye.yml`, which core also writes, so the assertion could
  only ever catch core disagreeing with itself. A service could advertise
  anything. courier did: five types in the two-segment form v0.2 froze away
  reached master and are still there. `fleet.yml` is the missing other side of
  that comparison, and it gives `cafe contract lint` one file to consume instead
  of a re-derivation of the catalog that can disagree with this one.

  It is a record of other repositories, so it is versioned as one: `sourceCommit`
  and `readOn` are required, and `manifestViolations` entries are deleted when
  the publisher corrects its manifest.

- **Thirteen new per-event payload schemas**, plus one rewritten, for events the
  fleet already publishes but core had never described. See the payload table in
  [docs/event-naming.md](docs/event-naming.md#payload-schemas): courier's five,
  `muse.tokens.consumed`, and billing's seven more. Fifteen of the catalog's
  thirty rows now have a schema; the other fifteen belong to types no service
  publishes yet. The root cause of the gap was the same as the root cause of
  courier's violation — nothing compared a real service's manifest against core's
  catalog — so the schemas and the check land together.

  **courier's five**, `courier.email.queued`, `.delivered`, `.bounced`,
  `.complained` and `courier.notification.suppressed`. Four carry the four fields
  `Courier.Deliver` builds, which is `message_id`, `user_id`, `notification_type`
  and `email` — and nothing from the caller's payload, because the envelope goes
  to every subscriber on the bus and a verification token in there is a credential
  leak into a fan-out. `courier.notification.suppressed` has **no** `message_id`,
  because nothing was rendered, addressed or sent: the entity is the recipient,
  so the payload is `user_id`, `notification_type`, `email` and a `reason`. No
  provider diagnostic appears in the bounced or complained payloads, because
  courier has no webhook receiver yet and a field no publisher emits is a contract
  that lies.

  Two fields are deliberately absent across all five, each recorded in
  [DECISIONS.md](DECISIONS.md): a provider message id (real — courier's own test
  fixture carries `provider_id`, its `Deliver` module does not), and a recipient
  key the fleet can join on (**D7** — courier uses a bare uuid, identity
  publishes `usr_…`, and no schema can reconcile that).

  **`muse.tokens.consumed`**, exactly the five fields `muse/metering.py` builds:
  `model`, `provider`, `tokens_in`, `tokens_out`, `cost_micros`. No account, no
  request id, no price — a payload schema is closed, and a field added now is one
  a future schema carries forever. The negative example is the price table: the
  per-1k rates really are in the publisher's `Price` object and really do move,
  so an event carrying them would say the cost and the price were true at the same
  instant. `muse` gets a catalog section and
  `examples/valid/muse.anywaye.yml` to go with it.

  **`consumed` joins the action vocabulary.** muse has published this type since
  it existed and `consumed` was not on the list, which the vocabulary itself
  says is a manager decision (**D9**). `muse.usage.recorded` was the alternative
  and is rejected in D9: it already means a different fact on a different subject.
  The call is reversible in one word plus a deprecation cycle, and it is recorded
  rather than made quietly.

  **billing's seven more** — `billing.customer.created`, `billing.plan.created`,
  `billing.plan.updated`, `billing.subscription.updated`,
  `billing.subscription.canceled`, `billing.payment.succeeded`,
  `billing.payment.failed` — plus the rewrite above. Two of them earned their keep
  on their own.

  `billing.payment.succeeded` **has two shapes**: billing emits it from an
  invoice (`invoice_id`, `subscription_id`, `attempt_count`,
  `next_payment_attempt`) *and* from a one-time Checkout session
  (`checkout_session_id`, `client_reference_id`). Rather than flatten them into
  an optional-everything schema, the schema declares a `oneOf` — exactly one
  shape, never both, never neither — and both are covered by a valid example,
  checked by a new `test_payload_schema_variant_examples_validate` so neither is
  assumed (**D11**). The negative example claims to be both at once, which is the
  mistake `oneOf` exists to make impossible.

  `billing.payment.failed`'s `amount` is **what could not be collected** — the
  amount due, never the amount paid. Its negative example carries a second
  `amount_paid: 0` field, because on a failed charge that zero is truthy and
  reads as "nothing was collected" to a consumer that wants the charge size.
  billing's own source comment names this exact bug.

  `billing.customer.created`'s `metadata` is **the one deliberately open object in
  the repository** (**D12**): it is a free-form `jsonb` bag, and closing it would
  make the field permanently `{}`. Every other object in every schema here is
  closed, and that field's own description says it is the exception.

- **Every published event type now has a catalog row and a payload schema, checked
  against the services' real manifests.** `fleet.yml` is the input;
  `test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema` is
  the assertion, and it is the check courier's five types would have failed the
  day they were declared — the one with no equivalent anywhere else. Proven by
  hiding courier's payload schemas and watching it fail with all five named.

### Breaking

- **`billing.subscription.started`'s payload schema was rewritten.** The v0.2
  version required `subscription_id`, `plan_id` and `account_id` as
  `sub_…`/`pln_…`/`acc_…` — a world in which billing holds anywaye-prefixed ids.
  billing has no subscriptions table and cannot invent ids it does not have; its
  webhooks carry the processor's `sub_…`, `cus_…` and `price_…` and its primary
  keys are bare uuids. The schema now describes what billing emits, with
  `processor` and `processor_event_id` on every payload so a consumer can tell a
  fact billing knows from a fact billing was told. **D10**, with the alternatives
  and the cost of reversing it.

  The alternative was to keep the text and write a valid example full of ids
  billing never sends — which validates, passes the suite, and fails on every
  real event. That is the outcome the rewrite exists to prevent.

### Fixed

- **`billing.plan.updated` had no catalog row.** billing has published it from
  its own manifest since it existed, and core's suite could not see it for the
  reason above. Row added; `billing.plan.created` and `billing.customer.created`
  had rows and no payload schemas, which is the same gap one layer down.

- **`muse` had no catalog section at all.** The service publishes a type and core
  had never heard of it, for the same reason. Section added, and an example
  manifest so the bidirectional assertion covers the new publisher rather than
  skipping it.

- **The `eventType` and `serviceName` patterns now have a third copy to keep in
  step** (`schemas/fleet.schema.json`), and the parity test covers all three. A
  pattern that appears once is a rule; a pattern that appears three times with
  two assertions is still one rule, but the assertions have to name all three.

### Changed

- **Open decisions are tracked in [DECISIONS.md](DECISIONS.md), not as callouts
  in `docs/`.** `docs/` stays free of undecided callouts because
  `test_no_open_decision_callouts_remain_in_the_docs` is a merge gate: a spec on
  `master` must read as decided. A worker branch that opens a real question
  would trip it, and the tempting fix — weakening or skipping that test — is how
  a spec silently stops being enforced. So open questions are numbered in one
  file at the repository root, linked from the doc that raises them, and
  asserted well-formed by `test_open_decisions_are_numbered_and_complete`.

### Known gaps

- Fifteen payload schemas still absent, for catalogued types no service publishes
  yet: identity's other eleven, `billing.subscription.past_due`,
  `billing.payment.refunded`, `billing.invoice.created`,
  `billing.usage.recorded`. `fleet.yml` marks each as `cataloguedOnly` so the
  difference between a promise and a fact is mechanical rather than a judgement.

## [0.2.0] — 2026-09-30

The event grammar, the payload-schema home, and the OpenAPI versioning rule are
all decided. One of them breaks an existing manifest, so this is a spec major.

### Breaking

- **Event types are `<service>.<entity>.<action>`. Three segments, always
  prefixed, no exceptions.** v0.1 accepted a two-segment `user.created` and only
  required the prefix for generic entities (`identity.api_key.created`); that
  exception is gone.

  | v0.1 | v0.2 |
  | --- | --- |
  | `user.created` | `identity.user.created` |
  | `subscription.started` | `billing.subscription.started` |
  | `identity.api_key.created` | unchanged — it was already the canonical form |

  The service segment is a service name, so it is kebab-case and may contain a
  dash (`email-sender.email.queued`); an underscore in the first segment is now a
  schema violation. The entity and action segments stay lowercase snake_case.

  **Downstream action.** Every published and consumed event type in every
  `anywaye.yml` must be renamed to its three-segment form, and every
  subscription, route, SDK constant and dashboard filter keyed on a two-segment
  type must follow it. This is a follow-up packet per service: core's own
  examples are updated here, the service repositories are not. Bump `core` to
  `^0.2.0` in the same commit as the rename — a service pinned to `^0.1.0`
  cannot resolve this release and will fail CI rather than silently accept the
  old format.
- **`subject` is required on the envelope.** It was already documented as
  required and was in fact optional in the schema. Entity-less events use the
  literal `platform`; there is no absent-`subject` case any more.

### Added

- **`schemas/events/<service>/<entity>/<action>.schema.json`** — per-event
  `data` payload schemas, in core. Two ship as the pattern:
  [`identity/user/created`](schemas/events/identity/user/created.schema.json)
  and
  [`billing/subscription/started`](schemas/events/billing/subscription/started.schema.json).
  A payload schema is a promise to other services, so it has one home with one
  release cadence rather than a copy in each publisher's repository. Core churns
  on every payload change; that is the cost, paid in review instead of in a
  consumer breaking on a Tuesday.
- **`docs/event-outbox.md`** — the transactional outbox convention: the
  `outbox_events` table, the insert in the same transaction as the domain write,
  the publisher loop (`for update skip locked`, ack before `published_at`,
  `attempts` with exponential backoff), at-least-once and therefore mandatory
  consumer idempotency, retention, and a sequence diagram. A convention only:
  each service implements it in its own language, and there is deliberately no
  shared outbox library.
- **`billing.plan.created`** to the billing catalog (11 events, up from 10).
- **Negative examples** for the tightened grammar (`event-envelope.untagged.invalid.json`),
  for the now-required `subject` (`event-envelope.subjectless.invalid.json`), and
  for both payload schemas. A negative example now needs a row in
  `examples/invalid/README.md` keyed by repo-relative path, and the suite fails on
  any negative file that is not documented.

### Changed

- **`docs/openapi-conventions.md`** — `/v1` path prefix **and** `info.version` are
  both required, with the sync rule (breaking change bumps both together, a
  non-breaking change bumps only `info.version`) and a note that a future
  `cafe contract lint` will enforce it.
- **`docs/manifest-conventions.md`** — the semver mini-grammar stays. Full npm
  semver is out of scope: resolution belongs to a future `cafe contract`, and
  `>=1.0.0` against a `0.x` service is a range that lies. Added a sixth
  cross-field rule: a consumed event type must exist in the core catalog.
- **`docs/event-naming.md`** — the grammar section, the catalog and the envelope
  table are rewritten around the three-segment rule, with the reasoning for
  making `subject` required. The new [Payload schemas](docs/event-naming.md#payload-schemas)
  section states the path convention and lists every payload schema in core.
- **`examples/valid/event-envelope.json`** — `data.user_id` was a 27-character id
  and did not match `subject`; the account id in the same payload was also 27
  characters. Both are 26-character ULIDs now, and the payload example is the one
  `schemas/events/identity/user/created.schema.json` validates.

### Open decisions

None. D1–D5 are decided:

| # | Decision |
| --- | --- |
| D1 | One canonical form: `<service>.<entity>.<action>`, always prefixed. |
| D2 | `subject` stays required; `platform` is the escape hatch for entity-less events. |
| D3 | Payload schemas live in core, one per event type, at a path derived from the type. |
| D4 | Both `/v1` and `info.version` are required, with the sync rule documented. |
| D5 | The semver mini-grammar is kept; `cafe contract` resolves it. |

### Known gaps

- The reserved service-name list (`anywaye`, `cafe`, `kit`, `core`, `docs`,
  `pantry`) is a review rule, not a schema constraint — core's own manifest is
  `name: core`, so encoding the list would make core fail its own schema.
- Only 2 of the 28 catalogued events have a payload schema. Each lands with the
  packet that first needs one; the suite fails on a payload schema that is not
  listed, or a listed path that does not exist.
- No OpenAPI document is shipped. `core` supplies the conventions a service's
  own `openapi/openapi.yaml` must agree with, not the documents themselves, and
  `cafe contract lint` does not exist yet.
- The outbox convention is a document, not a schema: the column list is asserted
  out of the SQL block in `docs/event-outbox.md`, and nothing here checks a
  service's actual migration.

## [0.1.0] — 2026-09-30

> Superseded by [0.2.0](#020--2026-09-30), which changed the event type format.
> This section is the record of what 0.1.0 said, including the decisions that
> were still open when it shipped; all five were decided in 0.2.0.

First cut of the anywaye contract substrate. Everything below is a new rule, so
nothing here can break an existing service; a service pinned to `^0.1.0` may
move to any `0.1.x` without review.

### Added

- **`schemas/anywaye.manifest.schema.json`** — draft 2020-12 schema for
  `anywaye.yml`: `name` (anywaye namespace rules), `language` enum, the `core`
  spec constraint, `exposes` (OpenAPI path + published event types),
  `consumes`, `dependencies`, `repository` (SSH remotes, `master` default
  branch), and `owner`. Closed with `additionalProperties: false` at every
  level.
- **`schemas/event-envelope.schema.json`** — the envelope every event travels
  in: `id` (UUID), `type` (`<entity>.<action>` or
  `<service>.<entity>.<action>`), `source` (the publishing service), `subject`,
  `time` (RFC3339), opaque `data`, and `specversion`. CloudEvents 1.0 attribute
  names; `specversion` pins the dialect.
- **`docs/event-naming.md`** — the event grammar, the action vocabulary, the
  delivery guarantees, and the initial catalog for **identity** (12 events),
  **billing** (10) and **courier** (5).
- **`docs/openapi-conventions.md`** — the `application/problem+json` error
  envelope, cursor pagination, `/v1` versioning, the `Idempotency-Key` rule,
  JWT auth via identity with a JWKS URL, and the deprecation policy.
- **`docs/manifest-conventions.md`** — manifest shape, namespace rules, the
  core semver mini-grammar, and the five cross-field rules JSON Schema cannot
  express.
- **`examples/`** — four valid manifests (Go API, Ruby API, event-publishing
  worker, worker-only), a valid envelope, and one invalid document per schema
  with the expected failure documented field by field in
  [`examples/invalid/README.md`](examples/invalid/README.md).
- **`tests/`** — the contract suite: every valid example validates, every
  invalid example is rejected for its documented reasons, and the docs are
  checked against the schemas. `bin/prime` runs it; `tests/setup.sh` builds the
  venv. The catalog and the example manifests are asserted to agree in both
  directions, so an event cannot be published without being documented or
  documented without being published.
- **`anywaye.yml`** — core's own manifest, `language: spec`, validated against
  core's own schema on every test run.
- **`README.md`**, **`AGENTS.md`**, **`mise.toml`**, **`.gitignore`**.

### Open decisions

Numbered as in the docs. Each was drafted with a default so nothing was blocked.
**All five were decided in [0.2.0](#020--2026-09-30)**; the outcomes are in that
release's "Open decisions" table, and the drafted defaults below are the record
of what shipped in 0.1.0, not a statement of the spec today.

| # | Question | Drafted default |
| --- | --- | --- |
| D1 | two- or three-segment event types | both accepted; service prefix required only for generic entities |
| D2 | is `subject` required? | required, with `platform` as the no-single-entity escape hatch |
| D3 | where does a per-event `data` payload schema live? | none in v0 — the publisher owns it; recommends a future `contracts/` repo |
| D4 | `/v1` path prefix vs. document version | both required, with the sync footgun noted |
| D5 | anywaye's semver mini-grammar vs. full npm semver | keep the mini-grammar, resolve it in `cafe contract` |

### Known gaps

- The reserved service-name list (`anywaye`, `cafe`, `kit`, `core`, `docs`,
  `pantry`) is a review rule, not a schema constraint — core's own manifest is
  `name: core`, so encoding the list would make core fail its own schema.
- No per-event `data` payload schemas, by design pending D3. Contract tests
  validate the envelope; payload tests are the publisher's.
- No OpenAPI document is shipped. `core` supplies the conventions a service's
  own `openapi/openapi.yaml` must agree with, not the documents themselves.

[Unreleased]: https://anywaye.com/changelog/core
[0.2.0]: https://anywaye.com/changelog/core/v0.2.0
[0.1.0]: https://anywaye.com/changelog/core/v0.1.0

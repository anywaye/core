# REPORT — core-16: the readable half of the contract

**Branch** `worker/core-16-contract` · **base** `169721d` (the recovery commit
that captured the uncommitted work when the machine OOM'd mid-run; re-verified
green on top of it) · **not pushed**

**The one-paragraph version.** `docs/contract-harness.md` owed the readable half
of the HTTP contract — the reserved error codes, the pagination envelope,
`Idempotency-Key` on retryable `POST`s. That is built: **eight new rules and
three new warnings** in `harness/cafaye_contract.py`, declared in
`harness/rules.json`, tabled in `docs/contract-harness.md`, and proved by **nine
red-proof breakages and three green warning cases**. Run over the fleet, the new
rules find **18 violations across 5 services and 1 warning on a sixth**. **Not
wired into `bin/prime`** — core-14 owns that file; see *Wiring* below for how to
run these rules today.

---

## 1. The courier measurements, confirmed rather than inherited

The brief told me to reproduce its numbers before writing a line of checker. Two
of the six do not match, and one of them changes what this packet is *for*, so
both are here in full.

Measured on `master` (`35c6a27`) with core's own YAML reader:

| Brief's claim | Measured | |
| --- | --- | --- |
| operations: 6 | **8** | ✗ |
| declared error codes: 400, 401, 404, 422 | 400, 401, 404, 422 | ✓ |
| `application/problem+json` in components, lines 571–617 | lines 571, 586, 602, 617 | ✓ |
| …referenced by **ZERO** responses | **referenced by all 17** | ✗ |
| mutating POSTs: 2 | 2 (`createWebhookEndpoint`, `testWebhookEndpoint`) | ✓ |
| `Idempotency-Key` mentions: 0 | 0 | ✓ |
| reserved codes never appearing: conflict, idempotency_key_reused, rate_limited, forbidden, internal, unavailable | exactly those six | ✓ |

**"Referenced by zero responses" is wrong, and the way it is wrong matters.**
courier's document defines four responses in `components/responses`
(`BadRequest`, `Unauthorized`, `NotFound`, `ValidationFailed`) and every one of
them declares `application/problem+json` with a `code`, a `status` and a
`trace_id`. All **17** of courier's non-2xx responses reach them through
`$ref`. The brief's measurement did not follow local `$ref`s, so it saw four
unused schemas where there are four heavily-used ones. **courier's error
envelope is conformant**, and a packet built on "courier attaches its problem
schema to nothing" would have gone looking for a defect that is not there.

**What is actually wrong with courier** is the finding the rules do produce:

```
$ harness/bin/cafaye-contract --core ../core ../courier
FAIL openapi.idempotency-key openapi.yaml: paths -> /v1/webhook_endpoints POST -> parameters:
  createWebhookEndpoint is a mutating POST that does not accept an `Idempotency-Key` header.
FAIL openapi.idempotency-key openapi.yaml: paths -> /v1/webhook_endpoints/{id}/test POST -> parameters:
  testWebhookEndpoint is a mutating POST that does not accept an `Idempotency-Key` header.
```

Two findings on a document whose error envelope is exemplary. That is a better
result than the one the packet expected, and it took measurement to see it.

**Also refuted: "the only OpenAPI document checked into any of the thirteen
services."** There are **seven**, and six manifests name them:

| repo | `exposes.api` | document on disk | operations |
| --- | --- | --- | --- |
| billing | `openapi/v1.yaml` | yes | 15 |
| courier | `openapi.yaml` | yes | 8 |
| darkroom | `openapi/v1.yaml` | yes | 9 |
| **guard** | **none** | **yes** | 7 |
| identity | `openapi/v1.yaml` | yes | 23 |
| muse | `openapi/v1.yaml` | yes | 1 |
| pantry | `openapi/v1.yaml` | yes | 4 |

So the brief's *"twelve of thirteen check in no document at all"* is also wrong.
The accurate statement, which I have put in the code, the doc and the inventory:
**of thirteen repositories, six declare `exposes.api` and seven declare none;
seven check in a document; six name it; one — guard — ships one that no manifest
points at.** That last cell is what `openapi.not-declared` exists for, and it is
not hypothetical: guard has **eight** non-2xx responses carrying no
`application/problem+json` (all of them 500s and a 503) and **zero** of the new
rules can say so until a manifest names its file. One line in `guard/cafaye.yml`.

---

## 2. The eight rules, their authority, and their red proof

All eight are in `harness/cafaye_contract.py`, all eight cite
`docs/openapi-conventions.md`, all eight are in `harness/rules.json` with an
`implementedBy`, all eight are in the table in `docs/contract-harness.md`, and
all eight have a breakage that goes red *naming the rule*.

| Rule | Authority (`docs/openapi-conventions.md`) | Red proof |
| --- | --- | --- |
| `openapi.errors-are-problems` | "Error envelope": every non-2xx is `application/problem+json` | **29** — the 401's media type changed to `application/json` |
| `openapi.problem-code-matches-type` | "`code` is the same slug as the last segment of `type`, in `snake_case`" | **30** — `code: unauthorized` → `unauthenticated`, `type` untouched |
| `openapi.reserved-error-codes` | the nine reserved codes "with their statuses" | **31** — `validation_failed` (reserved for 422) shipped with `status: 400` |
| `openapi.problem-has-trace-id` | "`trace_id` is always present" | **32** — `trace_id` dropped from the problem schema's `required`, left in `properties` |
| `openapi.no-offset-pagination` | "Pagination": "Offset pagination does not scale past a few thousand rows and cannot be stable while rows are being inserted" | **33** — the `limit` parameter renamed `offset`, beside a cursor |
| `openapi.page-envelope` | "Pagination": `?limit&cursor&order` in, `{data, page{next_cursor, has_more}}` out | **34** and **35** — `cursor` renamed `before`; `page` renamed `next` |
| `openapi.idempotency-key` | "Idempotency": "Mutating `POST` endpoints that can be retried safely **must** accept `Idempotency-Key`" | **36** — `Idempotency-Key` → `X-Idempotency-Key` |
| `openapi.idempotency-conflict-documented` | "Replay with the same key but a different body returns 409 `idempotency_key_reused`" | **37** — the 409 renumbered to 400 while the header stays |

Breakage 36 is `X-` and not a deletion, because that is the mistake the
convention has to survive in practice: every other header in a document is
prefixed `X-`, so the author matched the local style. Breakage 34 is
identity's audit log verbatim — `limit` and `before` declared,
`{"entries": …, "next": …}` returned. It is a correct pagination design that is
not core's, and the rule says so by name.

### The design decision the eight share

**Not being able to read an answer must not produce a different output from
reading a wrong one.** Every node behind a `$ref` the harness cannot follow is
*skipped and reported* (`openapi.unresolved-ref`), never judged. A checker that
prints "no `application/problem+json` here" about a response defined in
`errors.yaml` is not strict, it is lying, and it sends a service owner to fix a
document that is already correct. Self-test warning 40 asserts both halves: the
warning appears, **and** `openapi.errors-are-problems` does not.

Two related honesty decisions, both recorded in code comments:

- **A composed problem schema (`allOf`/`anyOf`/`oneOf`) is not decided.** The
  `trace_id` requirement may be inherited from a member, and guessing would mean
  accusing a document of omitting something it declares one level down.
- **`reserved` is a floor, not a ceiling.** This is the one place where the obvious
  rule is wrong, and the fleet is what shows it. Measured over all seven
  documents, reading the envelope `code` of every problem example and the `code`
  enum of every problem schema:

  | doc | envelope codes outside the nine |
  | --- | --- |
  | billing | `bad_request` |
  | courier | `bad_request` |
  | darkroom | — |
  | guard | `account_locked`, `invalid_json`, `payload_too_large` |
  | identity | `account_locked`, `invalid_json`, `method_not_allowed`, `payload_too_large`, `service_unavailable` |
  | muse | — |
  | pantry | `method_not_allowed` |

  **Five of the seven.** A rule requiring every code to be one of the nine would
  be wrong about five of them. And **core's own conventions name two codes that
  are not on the list** — `cursor_expired` (400) and `gone` (410). `muse` and
  `darkroom` use only the nine, which is the other half of the argument: the
  floor is a floor rather than a formality, because two documents in this fleet
  already keep to it.

  `errors[].code` is **not** counted anywhere, and the reason matters: the
  conventions' own example holds `invalid_format` in that field. A field-level
  code names a *field's* failure class; the envelope `code` names the failure.
  Counting both would have inflated this answer to six of seven and rested the
  argument on the wrong evidence — which is why it was measured twice.

---

## 3. What the rules found in the fleet

`harness/bin/cafaye-contract --core <core> ../<service>`, per service, on
`master`:

| Service | New findings | New warnings |
| --- | --- | --- |
| identity | **13** — 10 × `idempotency-key`, 2 × `page-envelope` (audit log), 1 × `errors-are-problems` (`/readyz` 503) | — |
| courier | **2** — `idempotency-key` | — |
| billing | **1** — `idempotency-key` (`receiveStripeWebhook`) | — |
| darkroom | **1** — `idempotency-key` (`createVariant`) | — |
| muse | **1** — `idempotency-key` | — |
| **guard** | — | **1** — `openapi.not-declared` |
| pantry | 0 | — |
| **total** | **18** | **1** |

Two of the eighteen are worth a second look:

- **identity's audit log** declares `limit` and `before` and answers
  `{"entries": …, "next": …}`. That is a correct, deliberate keyset design — it is
  core's *envelope* it does not use, and it is the first thing `page-envelope`
  will ever have caught.
- **identity's 10 `idempotency-key` findings** are all of a piece: `POST /v1/session`,
  `/v1/users`, every MFA operation, API-key minting. The document mentions
  `Idempotency-Key` twice, so somebody thought about it, and ten operations did
  not get it.

I did not edit any service. Per the brief: a core packet that also fixed courier
is a packet whose two halves can each be wrong.

---

## 4. The self-test's real counts

`bash harness/tests/self_test.sh` → **exit 0**.

```
PASS: self_test — 37 breakages went red naming their rule,
                3 warning cases stayed green,
                and both controls were green first.
```

- **37 breakages, 37 reds, 0 stayed green.** Every one names the rule it must be
  caught by, so a red caught by the wrong check cannot read as a pass.
- **Of those, 9 are new** (29–37) for 8 rules — `page-envelope` has two
  independently reachable halves and a reader is owed both.
- **3 warning cases, all green, exit 0** (38–40): no `exposes.api` and no
  document; a document nobody declared; a `$ref` the harness cannot follow. Plus
  a fourth assertion — the unread `$ref` is **not** reported as
  `openapi.errors-are-problems`.
- **2 controls, both green before anything else.** The second one exists because
  of this packet: `fixtures/conforming` is "the smallest document that satisfies
  every rule the harness could decide" — one GET, one 200, no error path, no
  pagination, no POST — so `openapi.errors-are-problems` **cannot fail in it**,
  and a breakage aimed at it there would be proving that a rule cannot fire.
  `fixtures/conforming-openapi/` is new and carries all three families
  conforming, behind `$ref`s, the way all seven real documents are written.
- **0 skips.** Nothing in this packet is conditional.

### The controls did their job twice

Both failures were real, and both are the reason the counts above are real:

1. Breakage 37 first mutated the whole `"409": {$ref: …}` line and had to be
   re-written as a mutation of the status key alone, because the fixture's `$ref`
   spelling carries a single quote and the breakage needed four levels of shell
   quoting. A self-test whose mutation needs that much escaping is one nobody
   edits correctly.
2. Breakage 36 first deleted the `parameters:` block, leaving a dangling key —
   which is **not** valid YAML, and the harness correctly **refused** with
   `yaml.unsupported`. The self-test caught it as "red, but NOT via the rule I
   named". Replacing it with `X-Idempotency-Key` made it a decision about the
   rule rather than about the fixture.

Neither was visible in a red/green count. Both are visible in a count of *which*
rule.

---

## 5. Deliberately not built, and why

| Not built | Why |
| --- | --- |
| The document against the router | Needs the service's language — courier's ExUnit test stays. The `notEnforced` entry now says this half is what is *not* built, so the entry no longer implies the other half is. |
| `errors[]` only on 422 | Readable, but only from an **example**. A document with no examples has stated nothing, so the rule's answer would depend on how much prose an author wrote. |
| `page.next_cursor` accepts null | 3.1 spells it `type: [string, "null"]`, 3.0 spells it `nullable: true`, and **courier's 3.1 document uses the second**. Deciding it here would accuse a document of a *pagination* mistake for a *versioning* one. |
| "An operation must declare a non-2xx response" | **The real ceiling on the error rules, and the one judgement call worth flagging.** A document declaring no errors passes all four error rules *vacuously* — the same two-empty-sets shape `openapi.has-paths` exists for. I did not build it because it fires on `harness/tests/fixtures/nonconforming-openapi`, whose exact rule set `tests/test_specs.py` (core-14's) asserts, and because requiring every operation to declare a failure path is **a manager's call about what a document must contain**, not a worker's. It is in `notEnforced` in those words. |
| "Every reserved code is used" | A fact about the implementation, not the document. Same entry. |
| `errors[].code` checked against the nine | **Not reserved and not supposed to be** — the conventions' own example holds `invalid_format` there. Measured, then left alone; counting it would have made the "reserved is a floor" argument look stronger than it is. |
| Live-response validation | Not this packet; needs a running service. |
| Resolving the `core:` constraint | Not this packet; core publishes no version to resolve against. |
| Any edit to a service repository | The brief. |

**One judgement call inside a rule.** `openapi.idempotency-key` takes **every**
`POST`, because the convention says "that can be retried safely" and a document
cannot express "this one is not" — that is a property of the implementation. The
strict reading is the right one and it is named as strict in `rules.json`. The
cheapest way to loosen it is one `x-cafaye-no-idempotency` branch in
`check_idempotency_key`; it is not written because inventing a vendor extension
is a contract change and not mine to make.

**One judgement call about the rules themselves.** I put the three warnings in
`rules.json`'s new `warnings` array and kept them out of `RULE_IDS`. A warning
that cannot turn a build red is not a rule, and `RULE_IDS` is asserted equal to
`rules.json`'s `rules` — putting warnings in that list would make "the rules that
gate" describe something else. The cost is that core's suite does not check the
warning ids, so `_check_inventory_declares` does, from `load_rule_inventory`: it
**refuses (exit 2)** if either list drifts. Verified by hand — deleting one
warning from the inventory gives exit 2 with the id named.

---

## 6. The enforcement ceiling, stated plainly

**This is the deliberate trade the brief asked for, and its price is
measurable.**

The price: of the seven documents in the workspace, **six are checked in full
and one is not checked at all.** `guard`'s eight problem-less error responses are
real, are exactly what `openapi.errors-are-problems` reports everywhere else, and
are invisible to a harness that reads only what a manifest declares. Measured, by
pointing a copy of `guard/cafaye.yml` at its own document in a throwaway
directory — **not** by editing guard:

```
$ cafaye-contract --core . <a copy of guard with exposes.api added>
17 findings: 8 × openapi.errors-are-problems, 6 × openapi.paths-are-versioned,
             3 × openapi.idempotency-key        (exit 1)
```

All seventeen are one line away from being real. That line is
`exposes.api: openapi/v1.yaml` in `guard/cafaye.yml`.

The benefit: an enforced rule over the document would have turned **seven of
thirteen** repositories red the moment core updated — including `core` itself,
`cafe`, `cafaye-rb`, `cafaye-ts`, `docs` and `parlor`, none of which has a reason
to. That is not a fleet adopting a check; it is a fleet deleting one. So
absence is named in a `WARN` prefix a log can filter, and the run stays green.

---

## 7. Wiring — how to run these rules today

**Not wired into `bin/prime`.** The brief forbids it (core-14 owns that file) and
says the manager wires the rules in at merge time. They are runnable directly:

```console
$ harness/bin/cafaye-contract --core . ../courier
$ harness/bin/cafaye-contract --core . ../identity --json | jq '.findings[].rule'
$ harness/bin/cafaye-contract --core . --list-rules | jq '.warnings[].id'
```

Stdlib only, offline, Python ≥ 3.9 (verified: parses under
`ast.parse(..., feature_version=(3,9))`). No new imports —
`test_the_harness_imports_nothing_outside_the_standard_library` still passes.

**For the manager, at merge time**, `bin/prime` needs nothing: core's own suite
already exercises every rule through the fixtures, and the breakages live in
`harness/tests/self_test.sh`, which CI already runs as a step of its own. If
`bin/prime` is to *report* against a service repository rather than only against
fixtures, that is a core-14/manager decision and this packet deliberately did not
touch the file.

---

## 8. Files touched, and files not touched

**Touched (6):** `harness/cafaye_contract.py` · `harness/rules.json` ·
`docs/contract-harness.md` · `harness/tests/self_test.sh` ·
`harness/tests/fixtures/conforming-openapi/{cafaye.yml,openapi/v1.yaml}` (new)

Three of these are outside the brief's ownership list and I want to be explicit
about each, because they are all *load-bearing* obligations from core's own suite
rather than choices:

- `harness/rules.json` — `test_every_rule_the_harness_can_emit_is_declared_in_the_inventory`
  asserts `RULE_IDS == rules.json`'s ids in **both directions**. Adding a rule
  without its inventory entry fails `bin/prime`, and AGENTS.md makes the entry
  part of the same commit.
- `docs/contract-harness.md` — `test_the_contract_harness_doc_and_the_inventory_agree`
  asserts the rule table equals that same set in both directions. The doc and the
  inventory are "the same rule list written twice"; the test is the enforcement.
- `harness/tests/self_test.sh` — `test_every_rule_the_harness_can_emit_is_proved_able_to_go_red`
  asserts **every** id in `RULE_IDS` appears in that exact file's text. A new
  rule with its breakage only in a new script fails the suite.

The brief permits a *new* test file under `harness/tests/`; I did not use that
permission. One script proving the harness can fail is better than two proving
overlapping claims, because a reader cannot tell which is authoritative and
core's own doctrine is that two statements of one contract must agree. So the
breakages went into the script the suite actually reads, and this packet's own
self-test file does not exist.

**Not touched, as instructed:** `bin/prime` · `tests/test_specs.py` ·
`harness/gate_check.py` · `harness/gate_findings.json` · everything under
`schemas/` · `DECISIONS.md` · `CHANGELOG.md` · `harness/bin/cafaye-contract`
(unmodified: it is a pure wrapper and needed no change) · every service
repository.

---

## 9. Open decisions to report

1. **Should every operation be required to declare a failure path?** The ceiling
   in §5. It is a one-rule change to `check_errors_are_problems` plus a fixture,
   and it needs a manager's call because it fires on a fixture core-14's tests
   assert the exact rule set of. *My recommendation:* yes, eventually, and the
   same argument `openapi.has-paths` was made under applies verbatim.
2. **Should a `POST` be able to declare itself unsafe to retry?** §5. Needs a
   vendor extension, which is a contract change. *Recommendation:* yes, with a
   name that reads as core's rather than a service's, or the rule stays strict
   forever and `testWebhookEndpoint` stays a permanent finding.
3. **Should `nullable: true` in a 3.1 document be its own rule?** **courier's**
   document uses 3.0 spelling in a 3.1 document — seven times, for `next_cursor`
   and `instance` — and the other six documents use none. It is a real,
   currently-unreported defect, and `openapi.document-is-31` does not catch it
   because it only reads the version string. *Recommendation:* yes, as
   `openapi.no-3-0-nullable`, and it is a clean small packet that does not
   belong inside this one.
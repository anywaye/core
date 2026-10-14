# REPORT — core-breaking-tiers-01

**Branch** `worker/core-breaking-tiers-01` · **base** `d49e14c` · **floor**
254 → **263**, measured · **suite** 263/263 · **tenancy_self_test** 39, green

For someone who has not seen the packet: cafaye answers "is this change
breaking" with **one boolean**, and the packet replaces that boolean with three
separately selectable tiers, because a consumer needs to know *which* surface
broke, not *whether* something broke.

The answer turned out to be that **the boolean does not exist**, and that `cafe`
had already built the three tiers. Both of those are findings, not
disappointments, and both changed what the packet became.

---

## 1. The measurement (deliverable 1)

Where does `breaking` live? **Nowhere in core.** Measured on this tree at
`d49e14c`:

| probe | count |
|---|---|
| a `"breaking"` key in any file under `schemas/` | **0** |
| a `breaking:` key in any `.yml`/`.yaml` in core | **0** |
| a `### Breaking` heading in `CHANGELOG.md` | **2** |
| released versions in `CHANGELOG.md` | **3** |

The one bit is not a field. It is **the presence of a Markdown heading**, which
is why it is absent from one release in three, why no program in the tree can
read it, and why a consumer still opens the diff: there is nothing addressable to
read.

The declaration cafe actually classifies is `cafaye/core`'s OpenAPI documents and
its payload schemas; the classifier is in **`cafe`**, not core —
`cafe/internal/contract/breaking.go`, 623 lines, ten classified change kinds, each
already carrying a `Tiers` set, with `cafe contract breaking --tiers
source,json,wire` already selecting one.

**Can you name a change the bit called "breaking" when a consumer would not have
cared, or "not breaking" when one would have?** Yes, and it is not hypothetical:
**every field rename, for every WIRE consumer.** `property-same-name` stops
generated source compiling and changes the JSON key. It changes nothing about a
binary encoding, because the encoding keys on the slot and the name was never in
it. Under one boolean that change must be answered as both breaking and not, and
whichever answer it picks is wrong for half of a six-language fleet. This is
buf's `FIELD_SAME_NAME` row and it is the packet's entire argument.

The inverse also exists and is named in the table: `schema-no-delete` is
SOURCE-only, so a WIRE-only consumer is told a schema removal is fine — correctly,
and for a reason it could not have given under a boolean.

## 2. The tier table, as data and asserted (deliverable 2)

`harness/breaking_tiers.json` — **ten (change kind, tiers) pairs**, each with
buf's row beside it, the divergence where there is one, and the reason. Plus
`source` (the four buf categories and the collapse), `tiers` (what each one
means), `defaultTiers`, and a `notEnforced` list.

`harness/breaking_tiers.py` — the **only** code that reads it, so a table and its
reader cannot be two files that disagree. `parse_tiers`, `tiers_for`, `breaks`,
`default_tiers`, and a `check()`.

| change kind | SOURCE | JSON | WIRE |
|---|:-:|:-:|:-:|
| `schema-no-delete` | ● | | |
| `reserved-no-delete` | ● | ● | |
| `enum-value-no-delete` | ● | | |
| `operation-no-delete` | ● | | |
| **`property-same-name`** | **●** | **●** | |
| `response-no-delete` | ● | ● | |
| `property-no-delete` | ● | ● | ● |
| `property-same-type` | ● | ● | ● |
| `property-same-cardinality` | ● | ● | ● |
| `operation-same-request` | ● | ● | ● |

**The gate that fails when the rule changes without the table changing:**
`test_the_published_table_is_the_go_table_and_they_cannot_drift` reads
`cafe/internal/contract/breaking.go` and `tier.go` out of the checkout beside this
worktree and fails if the two tables disagree about a rule id, **a row's tier
set**, or **`DefaultTiers`**. The direction is deliberate: cafe is what a consumer
actually runs, so it is the thing that must not drift silently from core.

That pin **found a real bug in itself twice while being written** — which is the
argument for pinning prose with a real parser rather than a matcher. An unanchored
`DefaultTiers\s*=` was reading the *docstring* in `tier.go` instead of the `const`
declaration, and reporting a disagreement that did not exist. It is anchored to
`^const DefaultTiers = …` now, with the reason in a comment beside the search.

## 3. The proof that the tiers genuinely differ (deliverable 4 — the bar)

`test_a_field_rename_is_breaking_in_source_and_json_and_not_in_wire` says exactly
that, and the same change answers four ways:

| selection | `property-same-name` (rename) | `property-no-delete` |
|---|---|---|
| `--tiers source` | **breaking** | breaking |
| `--tiers json` | **breaking** | breaking |
| `--tiers wire` | **not breaking** | **breaking** |
| `--tiers all` | breaking | breaking |

The right-hand column is the control that makes the left one mean something: the
split is **not** "WIRE never fires." A deletion reaches all three, and a rename
reaches two.

Two more tests hold the shape rather than one row:
`test_two_rules_whose_answers_differ_for_the_same_selection_exist` requires some
rule to break a **strict subset** of another's tiers, and
`test_a_table_whose_tiers_all_agree_is_refused` is the **red proof** — it hands
the checker a table where every row breaks all three tiers, and one where every
row breaks exactly one, and requires `breaking.tiers-indistinguishable` both
times. A table like that would validate perfectly, name a tier in every row, and
have exactly one symptom: a consumer's selection would stop mattering. That is
the failure this packet exists to prevent, and it is refused rather than
documented.

**Red proofs in this packet, all in the repo's idiom:**

| what it proves | how it goes red |
|---|---|
| the tiers are separable | table collapsed to one tier set → `breaking.tiers-indistinguishable` |
| an unclassifiable table is a failure, not a skip | unknown tier name / duplicate id / default matching no row → `breaking.tiers-unreadable` or the named finding; a **missing file** is the same FAILURE |
| a selection cannot be emptied | `""`, `"   "`, `"source,"`, `","`, `None`, `"srouce"`, `"…nope"` all raise `TierError` |
| the table cannot drift from the tool | move a tier in `breaking.go` → the pin fails naming both rows |

The empty-selection refusal is the one judgement worth naming: the empty set
intersects nothing, so `--tiers ""` would be a way to **turn a gate green**. A
gate that can be passed by naming no tiers is not a gate.

## 4. The wiring, and what was NOT done

**Done:** the three tiers are selectable by a consumer
(`parse_tiers`, `all` accepted, empty refused) and the classification is a
published table a consumer's answer is derived from.

**NOT done — the producer side.** A *declaration* cannot yet say which surfaces
it cares about, because in core there is no such declaration to put it on. See
**D43**: there is no `breaking:` field anywhere in `schemas/`, so the packet's
migration question has no subject. Adding one now would mean adding a field to
`schemas/cafaye.manifest.schema.json` whose only correct value is a constant,
and `additionalProperties: false` means all nine services have to be edited to
add it or its later removal is a break. That is out of scope for one hour and is
recorded rather than half-built.

**The precise successor's change**, when it is wanted: add an optional
`breakingTiers` to `schemas/cafaye.manifest.schema.json` — `enum: ["SOURCE",
"JSON", "WIRE"]`, `uniqueItems`, absent meaning the published `defaultTiers`, in
the same commit as a positive example under `examples/valid/`, a negative case
and a README row under `examples/invalid/`, and a test that the absent spelling
and the explicit `["SOURCE","JSON"]` are the same selection. Then `cafe` reads it
and passes it as the default for `--tiers`.

**NOT done:** nothing classifies a diff. `cafe contract breaking` reads two
revisions of an OpenAPI document and does that. A second opinion computed here
would be two answers about one diff, which is the defect the tiers exist to
remove — it is in the table's `notEnforced` with the reason.

**NOT done:** a `cafe` change. The pin is one-directional (core reads cafe) and
cafe needed nothing.

**Honest caveat on the pin:** it resolves `cafe` as a **sibling of this
worktree's parent**, and it prints a skip line and returns when that checkout is
absent. That is deliberate — the packet forbids nesting this worktree, and a test
that fails because a sibling checkout is missing fails for a reason that has
nothing to do with the table. The cost is real and named: **core's suite is
weaker in CI than on this machine** unless CI checks out the fleet beside core.
`lint drift` already needs the fleet there, so it is probably satisfied; confirm
before merging.

## 5. The tree

| file | what |
|---|---|
| `harness/breaking_tiers.json` | the published table — ten rows, buf provenance, `notEnforced` |
| `harness/breaking_tiers.py` | the only reader; `parse_tiers` / `tiers_for` / `breaks` / `check` |
| `docs/breaking-tiers.md` | the three tiers and why three and not four |
| `tests/test_specs.py` | nine tests, four of them red proofs |
| `gate.yml` | floor 254 → **263**, measured on this tree |
| `DECISIONS-breaking-tiers-01.md` | D43, D44, D45 |

The module makes **no findings and declares no rules** in
`harness/rules.json`, and that is a decision rather than an omission: those ids
are asserted equal to `cafaye_contract.RULE_IDS`, and a finding about a table
that is not a manifest has no honest home in either file. Instead the module
*refuses to be wrong* — an unknown tier name, a rule with no tiers, a duplicate
id and a default matching no row all raise before a caller can read a tier and
believe it — and `tests/test_specs.py` is the enforcement.

**Verification, as measured:**

* `bin/prime` → `263/263 passed`, and the gate checker's own red proof: 18
  breakages red, control green, 0 skipped.
* `harness/tests/tenancy_self_test.sh` → **39 breakages**, 4 warning cases green,
  6 green cases named, control green, **0 skipped**.
* `harness/breaking_tiers.py --check .` → exit 0.
* The `gate.yml` ratchet went **red at 254** and forced the raise — the ratchet
  working, not a formality.
* No pre-existing failure was found, so none is attributed.

## 6. Open decisions for the manager

1. **D43's consequence** — does a service declaration get a `breakingTiers`
   field at all, given the consumer side already works and no field exists to
   migrate? The packet's answer is yes eventually and not this hour; the manager
   may prefer never.
2. **The pin's CI dependency** — core's suite silently weakens when `cafe` is not
   checked out beside it. Making that a hard requirement, or vendoring the table,
   is a real choice with a cost.
3. **`response-no-delete` has no buf analogue.** It is argued in the table, not
   copied, on the evidence of identity dropping a 409 from
   `POST /v1/email-verifications` in 1.6.0. A row argued rather than copied is a
   row a reviewer should look at hardest.
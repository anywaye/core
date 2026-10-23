# DECISIONS — core-breaking-tiers-01

## D43: the breaking boolean does not exist, so there is nothing to migrate

**Raised by** core-breaking-tiers-01, from the packet's own instruction to
"find the boolean and measure what it is currently wrong about".

**Measured, on this tree at `d49e14c`:**

| probe | count |
|---|---|
| a `"breaking"` key in any file under `schemas/` | **0** |
| a `breaking:` key in any `.yml`/`.yaml` in core | **0** |
| a `### Breaking` heading in `CHANGELOG.md` | **2** |
| released versions in `CHANGELOG.md` | **3** |

**The premise was right and the location was not.** cafe says whether a change is
breaking — `cafe contract breaking`, `internal/contract/breaking.go`, 623 lines,
ten classified change kinds. The *declaration* it reads does not exist in core at
all. The one bit a consumer has today is the presence of a `###` heading in a
Markdown document, which is not a field, is not machine-readable, and is absent
from one release in three.

**Choice: do not migrate anything, because there is nothing to migrate.** The
question the packet asks — "does the boolean become a synonym for all three, or
must declarations be migrated" — has no subject in this repository. Inventing a
`breaking: true|false` field in order to migrate it away would be a migration
that costs nine services a fleet-wide change and buys back the packet's starting
point.

**Alternative considered:** add `breaking: true|false` to
`schemas/anywaye.manifest.schema.json` now, accept it as a synonym for all three,
and deprecate it next packet. Rejected: it ships a field whose only correct value
is a constant, and `additionalProperties: false` means every one of the nine
services has to be edited to add it or the next packet's removal is a break.

**Cost of flipping:** zero. Nothing here is written against a field.

**Consequence, and it is the honest one:** deliverable (3) of the packet — "so a
DECLARATION can say which surfaces a change breaks" — is **not done**, because
in core there is no declaration to put it on yet. The selection is on the
*consumer* side and it already works: `cafe contract breaking --tiers
source,json,wire`. What is missing is the producer side, and it is
`REPORT`'s §4. This is recorded rather than half-built.

## D44: the tier table is published in core and pinned to the Go table

**Raised by** core-breaking-tiers-01.

buf's `bufcheckserverbuild.go:894-989` has four categories. anywaye has three,
because anywaye has no importable packages and so no `PACKAGE` distinct from
`FILE`: a consumer either regenerates code from the contract, or reads the
document, or reads the bytes. That collapse is recorded as data in the table's
`source.collapse` rather than in a comment, so a reader can check it against the
table instead of taking it.

**Choice: `harness/breaking_tiers.json` is the published table and
`harness/breaking_tiers.py` is the only code that reads it.** They are not two
files, because a table and a reader that disagree is a table reporting tiers
nobody classified.

**Choice: the Go table in `cafe/internal/contract/breaking.go` is pinned, not
copied.** `test_the_published_table_is_the_go_table_and_they_cannot_drift` reads
both and fails if they disagree about a rule id, a row's tier set, or
`DefaultTiers`. The direction is deliberate: **cafe is what a consumer actually
runs**, so it is the thing that must not drift silently from core, and the check
lives in core because core is the substrate and core's suite is the gate every
service inherits by pinning a spec range.

It found a real bug in itself twice while being written, which is the argument
for pinning prose with a real parser rather than a matcher: an unanchored
`DefaultTiers\s*=` read the *docstring* in `tier.go` rather than the `const`
declaration, and reported a disagreement that did not exist. The search is now
anchored to `^const DefaultTiers = …`, and the reason is a comment where the
search is.

**Alternatives:**

1. **Change the table in core and let `cafe` follow next packet.** The status quo
   for a table that has existed for one packet and is asserted by a pin. The pin
   is what makes it a next packet and not a forever.
2. **Have `cafe` read core's JSON at runtime.** Rejected: core's own AGENTS.md
   says a linter that fetches the contract it validates against gives a
   different answer on a different day, and `cafe`'s says the schema is vendored,
   never fetched. A pin plus a table beats a fetch for the same reason twice.
3. **No pin — one table, in `cafe`, core's doc linking to it.** Rejected: core is
   what a service pins (`core: ^0.2.0`). A table about breaking changes that
   lives where the pin cannot reach is a table the substrate does not own.

**Cost of flipping:** option 2 is the one that is expensive and it is not
recommended; option 1 costs one edit to `breaking.go` in the same commit as the
core edit, which is the discipline the pin enforces rather than a change of
architecture.

## D45: WIRE is classified, published and unreachable, and that is not a defect

No anywaye service has a protobuf or Avro schema derived from its OpenAPI
document. So a WIRE break has nothing to break for every current member.

**Choice: keep the WIRE row and say so in three places rather than drop it.**
`cafe`'s `DefaultTiers` is `TierSource | TierJSON` for exactly this reason and
says so; the published table's `defaultTiers` is `["SOURCE", "JSON"]` and a test
asserts the two are equal; and the table's `notEnforced` list carries "nothing
here can produce a WIRE break" with its reason.

The row that reaches WIRE at all is `property-no-delete`, and it earns its place
by argument rather than by reachability: **tombstoning a name is what stops a
slot being reused, so delete-and-tombstone is the wire-safe form and
delete-and-say-nothing is not.** A table that left WIRE out would have to be
rewritten the day the first binary encoding lands, and a rewrite under time
pressure is how a classification becomes a guess.

**Cost of flipping:** to make WIRE reachable today would mean inventing an Avro
or protobuf schema for a service that has none. That is `darkroom` or `muse`
deciding, and not this packet.
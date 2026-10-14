# Breaking tiers — the classification, as data

`cafe` answers "is this change breaking" with **one boolean** today. This document
is the table that says which surface each kind of change breaks, and
`harness/breaking_tiers.py` is the code that reads it. The three tiers are:

| tier      | the surface                                                | a field RENAME |
|-----------|------------------------------------------------------------|----------------|
| `SOURCE`  | generated code, types, clients                              | **breaking**   |
| `JSON`    | the serialized document's field names                       | **breaking**   |
| `WIRE`    | what the bytes actually carry (types, tags, numbering)      | not breaking   |

The reference is buf's `bufcheckserverbuild.go:894-989`, which classifies into
`FILE`, `PACKAGE`, `WIRE` and `WIRE_JSON`. The row that matters is the one this
table exists for: **`FIELD_SAME_NAME` is breaking in `FILE`, `PACKAGE` and
`WIRE_JSON` — and NOT in `WIRE`.** A rename breaks generated source and JSON; the
binary encoding never carried the name.

## Why a category model beats a boolean

A consumer needs to know **which** surface broke, not **whether** something
broke, because the right response differs per surface:

* a Go service regenerating from the contract **cannot care** about a rename's
  wire encoding — it never read a field name off the wire;
* a TypeScript client reading the JSON **cannot ignore** one.

Under one boolean both consumers get the same answer and both are wrong half the
time. That is why they still open the diff.

## Why three tiers and not four

buf has four because it is a Go toolchain and `PACKAGE` (the importable Go
package's exported surface) is not the same surface as `FILE` (a file's contents).
cafaye has no importable packages — a consumer either regenerates code from the
contract or reads the serialized document or reads the bytes — so `PACKAGE`
collapses into `SOURCE`: in both cases the consumer's *code* is what has to be
regenerated. `harness/breaking_tiers.py` says so in its own docstring, and the
mapping is a table rather than a comment so a reader can check it.

## What this is NOT

This is a **classification of change kinds**, not a verdict on a diff. It does
not read two revisions of the tree and decide anything — `cafe contract breaking`
does that, and it reads this table. A table that tried to answer "is THIS change
breaking" would be a second opinion about a diff, and two opinions about a diff
is the defect this file exists to remove.
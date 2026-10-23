# Numeric conventions — the contract's numbers across six languages

Read this if you are writing a schema or an OpenAPI document that core will hold
you to. It is a checklist, like `openapi-conventions.md`, and it is not a
handbook: if it grows past a couple of pages, something belongs in your own
repository.

The hazard it exists to prevent is the one that **bites one language and not the
others**. anywaye has TypeScript, Python and Ruby clients reading the same JSON.
A Go service that writes `9007199254740993` produces a document TypeScript cannot
represent — Python's `int` and Ruby's `Integer` are fine — so nothing fails,
nothing logs, and the value is wrong. That is exactly what a contract layer exists
to prevent.

**The checker is `harness/bin/numeric-check`.** It reads documents and decides
from static facts alone; it opens no connection, takes no dependency, and reads
no environment.

```console
$ numeric-check --explain          # every finding id, and the notEnforced ledger
$ numeric-check schemas/ …         # check a surface
$ numeric-check --survey …         # measure it instead of ruling on it
$ numeric-check --json …           # the same findings, as JSON
```

Exit codes: `0` nothing on this surface is wrong for a language that reads it;
`1` at least one failure; `2` the check could not happen, which is never `0`.

## The four rules, and where each one lives

**A JSON Schema cannot ask whether a line of TypeScript holds an `int`.** It can
say `type: integer` and it can say `maximum:`, but the fact that **2**^53 is the
boundary at which `JSON.stringify` starts rounding is a fact about a *language*,
not about a document. So all four vocabularies live in the checker
(`harness/numeric_check.py`) rather than in `schemas/` — the same reason
`harness/tenancy_check.py` keeps its token vocabularies in the checker rather
than in `tenant-isolation.schema.json`.

That is a duplicated constraint, and this repository makes duplication a test:
`test_the_float64_limit_is_stated_once_in_the_checker_and_agrees_with_the_doc`
asserts that the number below appears in the checker, in `--explain`, and here.

| rule | severity | what it refuses |
| --- | --- | --- |
| `numeric.float64-unsafe` | **failure** | an integer whose declared maximum reaches 9007199254740992, an unbounded integer on a field named like an identity, or an integer `enum` with a member past 9007199254740992 |
| `numeric.float` | warning | a bare `type: number` |
| `numeric.enum` | warning | an `enum` whose values are all integers |
| `numeric.unsigned` | **not enforced** | — see below |

### `numeric.float64-unsafe` — the one that bites exactly one language

Three ways to be unsafe, and the distinction is the whole rule:

- **a declared maximum at or past 9007199254740992.** The document already says
  the value gets that big, so this is a bug today rather than a possibility.
  9007199254740991 is fine and 9007199254740992 is not, because the limit is the
  last integer a binary64 holds *exactly*.

- **no maximum at all, on a field whose name says it carries an identity.**
  Unbounded is only alarming where the ceiling is reachable: a token count with
  no maximum cannot plausibly reach 9×10^15, so demanding a string of it would be
  inventing work; an `int64` `byte_size` can, because the only thing bounding it
  is whatever the writer felt like putting there.

- **an integer `enum` with any member past the limit.** See below; it is a
  different shape rather than a third bullet of the same shape.

#### An `enum` is a stronger statement than a `maximum`

A `maximum` **bounds a range**. It says how big the value may get, and a writer
that stays inside it produces nothing a reader cannot hold — the hazard is real
but prospective.

An `enum` **enumerates the complete set of legal values**. So a member past the
limit is not a possibility the contract tolerates; it is a value the contract
*requires*, and every one of those values is a value a JavaScript client silently
rounds. There is nothing prospective about it, which is why it is a **failure**
and why it shares the id with the `maximum` branch rather than becoming a fifth
rule. The distinction this checker draws everywhere is *can this value cross the
wire wrong*, and this one can.

Two things about that branch that are worth knowing before you write the field:

- **The comparison is by MAGNITUDE, and it is strict.** Any member with
  `abs(value) > 9007199254740992` is refused, so
  `enum: [-9007199254740993, 0]` is refused: a signed comparison would ask "is the
  largest member too big", which is a question about a `maximum`, and an `enum` is
  not a `maximum`. And **exactly `9007199254740992` is allowed**, in either
  direction, because it *is* exactly representable — `JSON.stringify` of it
  returns `"9007199254740992"` and `JSON.parse` of that returns `2**53`. The
  declared-`maximum` branch fires at `>=` and this one at `>`; the one-value
  difference is deliberate and [D44](../DECISIONS.md#d44-is-an-enum-member-past-the-float64-exact-range-a-failure-or-a-warning)
  has the argument.
- **A `type` is not required.** `{"enum": [0, 9007199254740993]}` with no `type`
  at all is legal draft 2020-12, permits the value, and is refused. A string
  enum, an enum of floats, and an enum with one non-integer member are all
  **unchanged**: the checker only considers an enum whose members are *all* JSON
  integers, because a value that is not a number is not a value `Number()`
  mangles.

```jsonc
// refused — one of these three values a TypeScript client cannot hold
"shard_id": { "type": "integer", "enum": [0, 1, 9007199254740993] }

// allowed: the boundary itself round-trips
"shard_id": { "type": "integer", "enum": [0, 1, 9007199254740992] }

// the convention: quote the value, and the closed union survives
"shard_id": { "type": "string", "enum": ["0", "1", "9007199254740993"] }
```

A node that is both a wide `maximum` and a wide `enum` gets **one**
`numeric.float64-unsafe` — the `maximum`'s — and still gets its `numeric.enum`
warning, because it is genuinely both an unrepresentable value and a closed
union.

The names the checker treats as identities are in `IDENTITY_NAME_TOKENS`:
`byte_size`, `bytes`, `iat`, `exp`, `nbf`, `created`, `last_used_at`,
`expires_at`, `issued_at`, `sequence`, `seq`, `offset`, `cursor`,
`timestamp_ns`, `micros`, `nanoseconds`. **You can predict whether a name will be
refused before you write the field** — that is the point of this table.

**What to do instead: a string.** Every one of the six languages represents a
decimal string exactly and none of them guesses at its width.

```jsonc
// refused — a value here is exact in Go, Python and Ruby and wrong in
// TypeScript by one, and nothing logs.
"byte_size": { "type": "integer", "minimum": 0 }

// the convention, and the only spelling the envelope has for this
"byte_size": { "type": "string", "pattern": "^[0-9]+$" }
```

A scaled integer is the other answer and it is a real one — nanoseconds instead
of seconds, cents instead of units. It keeps the field numeric, which is
sometimes what a consumer wants. **The pattern to follow is `IDENTITY_NAME_TOKENS`
plus a `maximum` below the limit**, and the one line that changes is
`IDENTITY_NAME_TOKENS` itself.

### `numeric.float` — a warning, and the two fields it fires on are ours

Floats "cannot be reliably round-tripped" across six languages. It is a warning
rather than a failure because **the two positions it fires on in core's own
schemas are ratios** — `slo.objective` and `slo-windows.factor` — and a ratio that
cannot be a whole number is not a rounding bug.

So the rule says what to do instead, and the envelope already has a convention:
**express an SLO objective in thousandths as an integer.** Sloth's
`prometheus/v1` block takes a target as a fraction, so the schema's `objective`
is a ratio while the *declaration* stays a ratio too — but anything a client
*reads and re-emits* wants thousandths:

```jsonc
// a ratio — warned about
"objective": { "type": "number", "exclusiveMinimum": 0, "maximum": 1 }

// the convention for anything that round-trips: thousandths, as an integer
"objective_milli": { "type": "integer", "minimum": 1, "maximum": 1000 }
```

A percentage that is always a multiple of 1/1000 is defensible; one that is not
is not. If you add a float field whose values are *not* ratios, that is a real
finding and the right move is to fix the field rather than to lower the severity.

### `numeric.enum` — a warning, and the cost is a closed union

The reference is explicit: adding a numeric enum value is **not** a compatible
change. Codegen turns the enum into a closed union in every language at once, so
adding `503` breaks six clients simultaneously.

Prefer a closed set of **words**, which codegen also turns into a closed union
but which a reader can log:

```jsonc
// warned about — a numeric enum
"status": { "type": "integer", "enum": [200, 503] }

// the convention, and what core's probes schema should say if it is ever rewritten
"status": { "type": "string", "enum": ["ok", "unavailable"] }
```

It is a warning rather than a failure because core's own two positions
(`probes.statusCode`) are status codes, and failing a gate over a status code is
how a gate gets disabled.

**A numeric enum can be BOTH a warning and a failure, and that is not a
contradiction.** A node carrying a member past the float64 exact range is an
unrepresentable value (a `numeric.float64-unsafe` failure, above) *and* a closed
union (this warning). The two answers are about different things — one is about
the value crossing the wire wrong today, the other is about what adding a value
costs later — so a single node reports both and the exit code is the failure's.
Fixing the float64 half by quoting the member does **not** silence this one, and
that is correct: the union is still closed.

### `numeric.unsigned` — deliberately NOT enforced

**45 numeric positions** across core's schemas and the seven service OpenAPI
specs declare `minimum: 0`, and every one of them is a count, an amount in minor
units, or a status code. Refusing them refuses the fleet's own vocabulary.

The part that decides it: **a rule that fires on 45 of 97 numeric positions is a
rule that is disabled within one release**, which leaves the fleet with *no*
unsigned check rather than an incomplete one — the same conclusion the previous
packet reached about a different rule.

It is also structurally invisible here: **there is no unsigned integer type in
JSON at all.** Go has no unsigned JSON, TypeScript has no unsigned number, and
Python's `bool` **is** an `int`. The rule is enforceable only in your own
language's types — which is where the successor's first move is, and where this
document's next revision should say something.

## Who owns these severities, and what is still open

The four severities, the four alternatives that lost, and the cost of flipping
each one are
[D43](../DECISIONS.md#d43-is-a-value-that-one-language-cannot-represent-a-finding-and-where-do-the-numeric-vocabularies-live).

**One question in D43 is the manager's rather than the checker's**, and it is
stated there rather than here: whether `slo.objective` and `slo-windows.factor`
are rewritten as scaled integers is a change to two published schemas under the
fleet's adopters. The three options are (a) leave both as ratios and keep
`numeric.float` a warning, which is the status quo and costs nothing today;
(b) rewrite them to `objective_milli` as an integer **and** promote the rule to
a failure; or (c) rewrite them and leave the warning. **Recommendation: (b)**,
in one commit, because a scaled integer that nothing requires is a convention and
core's own rule is that a convention with no test is documentation of a wish.

## What this checker does NOT do

- **It does not read a line of any of the six languages.** It reads documents.
  A value that round-trips wrongly inside one language is proved by that
  language's own typed client and its tests, not here.
- **It does not run any of the fleet's tests, and opens no connection.** For the
  same reason `harness/tenancy_check.py` does not: `harness/` may not take a
  dependency or reach a database.
- **It does not check that a service's `openapi.yaml` is in step with its Go
  types.** It checks the document, which is the half core owns.
- **It does not enforce unsignedness.** Above, and in the `notEnforced` ledger
  the checker prints on **every** run — a rule examined and excluded on purpose
  is a decision; the same rule excluded silently is the defect.
- **It cannot see a value it was never told about.** A schema that declares
  `type: object` with no properties has no numeric surface to check, and that is
  an honest zero rather than a pass.

## Red proofs and where they live

Every finding above has a breakage in `harness/tests/numeric_self_test.sh` that
goes red **and names the finding and the field**: the declared maximum at the
range, one past it, one short of it, and the two identity spellings. The enum
branch has its own group of cases, (10)–(18), and each of those mutations is
confined to the `enum` and the `type` — no `maximum`, no identity-shaped name —
so a rule that had lost the enum branch would keep cases (1)–(5) green and turn
them red. That is the property the group exists to establish, and it is the
opposite of the mistake the packet warned about: a mutation that reds the
*existing* `numeric.float64-unsafe` cases proves nothing about the enum path.

Two of those cases are **greens**, and they are the ones that decay: `enum` with a
member of exactly `9007199254740992`, and of exactly `-9007199254740992`. An
off-by-one at the boundary is invisible until a real client silently rounds.

`test_the_numeric_red_proof_and_its_header_name_the_same_rules_in_both_directions`
checks that script's header against its own cases in both directions, so a rule
in the header with no case beside it fails rather than reading as a promise.
CI runs that script as a step of its own, and
`test_every_numeric_finding_is_proved_able_to_go_red_and_CI_runs_the_proof`
fails if the step is deleted or a finding has no breakage.
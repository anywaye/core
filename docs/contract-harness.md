# The contract-test harness

`harness/` is how a service checks itself against core's contracts using
something core ships, rather than writing that check itself. It is the fifth of
core v0's five Phase 0 deliverables (PLAN.md §4) and the only one that did not
exist until now — which is why muse, darkroom, courier and pantry each wrote
their own version, differently.

```
harness/bin/cafaye-contract      what a service's CI calls
harness/cafaye_contract.py       the harness. One file, standard library only
harness/rules.json               the rule inventory, and where each rule lives
POSTGRES_TAG                     the fleet's postgres image, one line, machine-readable
harness/tests/self_test.sh       forty-one breakages, forty-one reds
harness/tests/fixtures/          three conforming services, eight that are not
```

## Running it

```
harness/bin/cafaye-contract --core ../core .
harness/bin/cafaye-contract --core ../core --expect-digest <sha256> .
harness/bin/cafaye-contract --list-rules
```

Offline, always. The harness never fetches a schema, resolves a `$ref` over the
network, or reads an environment variable other than `CAFAYE_CORE` — a contract
check that needs the network is one nobody runs on an air-gapped runner, and one
that reads a variable is two harnesses.

| Exit | Meaning |
| --- | --- |
| `0` | the service conforms |
| `1` | it does not; every broken rule is one `FAIL <rule-id> <path>:` line |
| `2` | **the run could not happen** — no core, no manifest, or YAML outside the declared subset |

Output order is always **findings, then warnings, then the verdict**: a line that
ends a build is above a line explaining why a check did less than it appears to,
and the verdict is last so a log that stops early has still shown the reason.
`WARN` is a distinct prefix from `FAIL` for the same reason — a log grepping for
problems does not pick up the sentence about what was not checked.

`2` is not a soft `1`, and a reader is meant to notice the difference. A run that
could not happen and a run that found nothing to complain about both produce
output; treating them as the same thing is how a check that could not find the
contract ends up reporting success. Four repositories in this fleet have shipped
that defect: gateway's live-Redis tier, muse's `MUSE_CORE_SCHEMAS` tier, identity's
`TEST_DATABASE_URL` tier, and darkroom's `--ignored` tests. **A contract check
that cannot find the contract is worse than no contract check, because it
converts an unknown into a green badge.**

`test_the_harness_fails_loudly_when_core_is_absent` and
`test_the_harness_fails_loudly_when_a_service_manifest_is_absent` are the two
assertions that keep `2` honest, and self-test breakages 15–18 and 20 are the
same five rules proved able to go red.

## Where it lives, and why it is in core

Inside core, not its own repository. Three reasons, in order of weight:

1. **It reads core's schemas.** A harness in its own repository would have to
   vendor them, which is the exact drift this packet exists to end — four
   vendored copies today, one per service, at four different SHAs. The harness
   is the thing that makes vendoring unnecessary, so it cannot be the fifth
   vendored copy.
2. **It is the executable form of a rule that already lives in `schemas/`.** It
   adds no new contract; it decides the existing one, and it is checked by the
   same suite that checks the schemas.
3. **core already contains executable code.** `bin/prime`, `tests/test_specs.py`,
   `tests/setup.sh` and `tests/validate.sh` are all programs. The line
   AGENTS.md draws is not *no code* — it is **no runtime**: no service, no
   framework, no library, no dependency. The harness starts nothing, listens on
   nothing, ships no packages, and imports only the standard library, which is a
   stricter reading of the rule than `tests/requirements.txt` is.

The alternative that loses is a compiled binary released from its own
repository: that makes core a release-engineering project with per-platform
artifacts and a version to keep in step with the spec, which is what
`refs/goreleaser` is on the reference shelf for and not what this is.

## Pinning

**The pin is a sha256 over everything under core's `schemas/`, path-sorted. The
same argument works on a laptop and in CI because there is only one argument.**

Not a git ref, and the reason is the fleet's own history. A ref names a commit
in a repository the harness is not allowed to fetch; `muse` pins `CORE_REF` in
CI and compares bytes, `pantry` reads `PANTRY_CAFAYE_ROOT`, `darkroom` uses "the
checked-out cafaye/core schema", and `courier` reads its router. Four ways to
answer "where is core", one of which is a `git` object and three of which are
directories. A digest names **bytes**, and bytes are the thing a service is
actually compiling against.

```console
$ harness/bin/cafaye-contract --core ../core --list-rules >/dev/null
$ python3 -c "import sys; sys.path.insert(0,'../core/harness'); \
    import cafaye_contract, pathlib; print(cafaye_contract.contract_digest(pathlib.Path('../core')))"
aaf8216e42b8…
```

What the digest gives, and what it does not:

- the same core commit digests identically in a worktree and in a runner, so a
  developer's local run and CI's step are the same check, with the same code and
  the same rules;
- one byte in one schema changes it — the smallest possible drift, and the one a
  re-vendor fan-out produces;
- it covers **all** of `schemas/`, not the two files a service happens to vendor,
  so a service cannot be pinned against a partial copy;
- it does **not** notice a dirty tree that has not been committed. A developer
  with an edited schema gets a different digest from CI, and that is the truth
  rather than a bug — their tree really is different. The git commit is
  *reported* in every run, never checked, because a name the harness cannot
  verify offline is not a pin.

`--expect-digest` is the opt-in that turns "different" into a red build, and it
is a **violation** (exit 1) rather than a refusal (exit 2): core was found and
read in full, it is simply not the core that was pinned. Refusing here would say
"I could not check", and a service owner would spend an afternoon on a checkout
problem they do not have.

## What it validates, and what it deliberately does not

PLAN.md §3 asks for two different things by the same name, and conflating them
is how a service ends up believing it has a check it does not have.

**Built: a service's *declared* contracts.** Its `cafaye.yml` against core's
manifest schema, the manifest's cross-field rules, its event types against
core's catalog, and its OpenAPI document against core's conventions. All of it
is decidable from files, offline, in any language.

**Not built, and still owed: a *live response* against the event envelope and the
per-type payload schema.** That is PLAN.md §3's "each service's CI validates
responses against the spec" — the richer reading of "contract test", and arguably
the more valuable one. It needs a running service, and core ships no runtime;
`darkroom`'s `tests/contract.rs` already says so in a comment, naming
`caf contract test` as the thing that was supposed to do it. A service can
already validate a payload by hand against
`schemas/events/<service>/<entity>/<action>.schema.json`; what is missing is
something that does it for every published type, in CI, without the service
writing the loop. **Until that lands, a reader of this document should assume the
harness does not look at a single byte of live traffic.**

Also not built, and named so it is not mistaken for an oversight:

- **The `core:` constraint is resolved — and that is new, so here is exactly
  what it does and does not do.** It was owed until core-17 and was named here
  as not built, because it needs a machine-readable core spec version on both
  sides and core published none. Core now publishes one, at `VERSION` at its
  root, holding exactly one `MAJOR.MINOR.PATCH` line. The resolver is
  `harness/core_version.py`, a transliteration of `caf`'s existing
  `internal/contract/version.go` rather than a second dialect, and the grammar
  is [`docs/core-version.md`](core-version.md). Three rules: a declared
  constraint that does not admit the published version is
  `core.constraint-unmet`; a constraint or field outside the grammar is
  `core.constraint-unresolvable`; and a core that publishes no version at all
  is `core.version-absent`, which is a **refusal and exits 2** — the run could
  not happen, and reporting it as a violation would tell a service owner to fix
  a manifest that was not the problem.

  What it still does not do: it reads the checkout it is given, so it says
  nothing about *which* core a service's CI fetched. **This paragraph was wrong
  about the whole fleet and is re-measured on 2026-10-01.** It used to say three
  services declare `core: ^0.1.0` (`identity`, `courier`, `gateway`) and that none
  of the three checks out core at all. Both halves have moved:

  - **No service declares `^0.1.0` any more.** All five — `identity`, `billing`,
    `courier`, `muse`, `gateway` — declare `core: ^0.2.0`, and courier's manifest
    records the resolution and which line is enforced by something outside that
    repository. So the contradiction this check exists to name is, for the
    moment, not one anybody has.
  - **Three of the five now fetch core in CI, and the three are not the same
    three.** `muse` checks out `cafaye/core` at a full pinned commit
    (`CORE_REF` in its workflow), which is the shape
    `docs/core-version.md` asks for. `billing` checks out `repository:
    cafaye/core` at `ref: master`, and `gateway` curls the manifest schema from
    `raw.githubusercontent.com/cafaye/core/master/…` — both real, both
    unpinned. `identity` and `courier` still reference core nowhere in CI.

  So the check's precondition — **core is 0.2.0 and the checkout is real** — is
  now met by a different set of services than when this was written, and the
  defect it cannot catch is no longer "nobody fetches core" but "two services
  fetch it at a moving ref". A harness reading `billing`'s checkout sees whatever
  `master` was on the run, which agrees with `^0.2.0` today and would not agree
  the day core publishes `0.3.0`. That is `docs/core-version.md`'s "The one way
  to fetch core" — including its toolchain half, which has the same shape and the
  same answer — and it is a convention with a document, not yet a rule.
- **The document is not compared to the service's router.** That half needs the
  service's language: courier reads `Router.__routes__/0` in ExUnit, muse
  compares against a live FastAPI app, and a language-neutral harness cannot
  read either. courier's test stays. The *readable* half — the reserved error
  codes, the pagination envelope, `Idempotency-Key` on retryable `POST`s — was
  owed and is **built**: it is the eight rules in the table above, and the
  section below is what they do and where they stop.
- **The YAML reader reads a subset, and refuses the rest.** See below.

## The readable half: eight rules, and the line they stop at

`docs/openapi-conventions.md` fixes three families — the error envelope, the
pagination envelope, and idempotency — and this is the machinery that decides
them from a file. Eight rules, and every one of them answers a question a client
could also ask by reading the same document.

**The engineering content of the eight is not what they check; it is what they
do when they cannot check.** Every node whose answer sits behind a `$ref` the
harness cannot read is *skipped and reported*, never judged — a checker that
says "no `application/problem+json` here" about a response defined in another
file is not strict, it is lying, and it sends a service owner to a document that
is already correct. Three consequences a reader should be able to see rather than
infer:

- A local `$ref` is followed, so `#/components/responses/Unauthorized` and
  `#/components/schemas/Problem` are read as themselves. **A non-local one is
  not**, and becomes `openapi.unresolved-ref`. core is offline by contract and
  this is the same rule applied to a service's own document.
- A problem schema built from `allOf`/`anyOf`/`oneOf` is **not decided**,
  because the requirement may be inherited from a member, and guessing would
  mean accusing a document of omitting something it declares one level down. It
  becomes the same warning.
- **`reserved` is a floor, not a ceiling, and the fleet proves it.** `gateway`
  enumerates `invalid_json`, `account_locked` and `payload_too_large` beside the
  nine; `identity` adds two more; `courier` documents `bad_request`; and core's
  own conventions name `cursor_expired` and `gone`, which are not on the list at
  all. A rule requiring every code to be one of the nine would be wrong about
  five of the seven documents in the workspace. What *is* decided is the binding
  in the other direction — a reserved code means one status, which is the whole
  reason it is worth reserving.

### Warnings, and why they are not rules

A **finding** turns a build red. A **warning** cannot, and `Result.exit_code`
never looks at one. They exist because the honest answer to "did the harness
check this?" is sometimes *no*, and a checker whose only output is a verdict has
exactly one way to say that, which is to look green.

Of the thirteen repositories in the cafaye workspace, six declare `exposes.api`
and seven declare none. Seven check in an OpenAPI document, and six of those
name it — one, **gateway**, ships a document no manifest points at. A rule that
*enforced* the document would therefore turn seven of them red the moment core
updated — which is not a fleet adopting a check, it is a fleet deleting one. So
absence is named, in a `WARN` prefix a log can filter out, and the run stays
green:

- `openapi.no-document` — the manifest declares no `exposes.api`. Not a pass over
  the document; **no document**.
- `openapi.not-declared` — a document *is* checked in beside the manifest, and no
  manifest names it. **This is the one that matters**: it is the difference
  between a service with no HTTP contract and a service whose HTTP contract
  nobody is checking, and `gateway` is the case in the workspace today. Its eight
  non-2xx responses that carry no `application/problem+json` are exactly the
  finding `openapi.errors-are-problems` would make, and exactly the finding it
  cannot make while nothing points at the file.
- `openapi.unresolved-ref` — a pointer the harness cannot read.
- `compose.pin-scan-truncated` — a compose-shaped file below the depth
  `compose.postgres-pin` reads, so nothing in it was read. **This is the one that
  matters for the pin rule**, and it exists because the first version of the walk
  stopped *descending* at the bound: the file was never found, so the warning
  could not fire, so a bound that could hide a pin was silent. The walk is now
  unbounded and the *reading* is bounded, which is the only shape in which the
  limit can be named.

This is a **deliberate ceiling on enforcement**, and the fleet cost of it is
measurable rather than hypothetical: of the seven documents in the workspace,
the six that a manifest names are checked in full, and the one that no manifest
names is not checked at all. Declaring it is a one-line change in one file.

The three ids are in [`rules.json`](../harness/rules.json)'s `warnings`, asserted
equal to `WARNING_IDS` by `_check_inventory_declares` — which **refuses**, rather
than warns, because an inventory that has drifted from the code is the same
defect as a schema that has drifted from its examples. They are deliberately not
in `rules` and deliberately not in the table above: a list that mixed the two
would make "the rules that gate" describe something else.

### Four things in these three families that are still not checked

Named here rather than left to look like a pass, and each with the reason in
[`rules.json`](../harness/rules.json)'s `notEnforced`:

- **An operation that declares no non-2xx response at all.** This is the real
  ceiling on the error rules: a document with no declared errors passes all four
  of them vacuously, which is the same two-empty-sets shape `openapi.has-paths`
  exists for. It is not enforced because requiring every operation to declare a
  failure path is a manager's call about what a document must contain, and
  enforcing it would fire on `harness/tests/fixtures/nonconforming-openapi`,
  whose exact rule set core's own suite asserts.
- **`errors[]` appears only on 422.** Readable, but only from an example, so the
  rule's answer would depend on how much prose an author wrote.
- **`page.next_cursor` accepts null.** `nullable: true` is 3.0 spelling and
  `type: [string, "null"]` is 3.1's; courier's 3.1 document uses the first, and
  deciding it here would accuse a document of a *pagination* mistake for a
  *versioning* one.
- **Every reserved code is used, and no undocumented failure path exists.** Both
  need the implementation, which is the router comparison above.

## Where each rule actually lives

This is core's own question turned on core's own tool, so the answer is
field-by-field rather than a summary. The honest answer is **"some in
`schemas/`, some in `docs/` and therefore in the harness's source, and some
about the filesystem"**, and
[`harness/rules.json`](../harness/rules.json) is where that stops being a
summary: every rule declares an `enforcedBy` with a kind, and
`test_the_rule_inventory_says_where_every_rule_lives` checks that a `schema`
claim names a real file under `schemas/`, that a `doc` claim names a real
heading in a real document, and that a `harness` claim names a function that
exists.

| Rule | What it decides | Where it lives |
| --- | --- | --- |
| `manifest.schema` | the manifest satisfies the manifest schema | `schemas/cafaye.manifest.schema.json` |
| `event.own-prefix` | a published type starts with the publisher's own name | `docs/manifest-conventions.md`, "Rules the schema cannot state" — **in the harness** |
| `event.no-self-consume` | a service never consumes its own events | same — **in the harness** |
| `event.unknown-consumed` | every consumed type is in core's catalog | same — **in the harness** |
| `event.unknown-published` | every published type is in core's catalog | same — **in the harness** |
| `event.payload-schema-missing` | every published type has a payload schema | `docs/event-naming.md` — **in the harness** |
| `manifest.api-file-missing` | `exposes.api` resolves inside the repository | **in the harness**; a fact about a filesystem, not a document |
| `openapi.document-is-31` | the document declares 3.1 | `docs/openapi-conventions.md` — **in the harness** |
| `openapi.info-version` | `info.version` is `MAJOR.MINOR.PATCH` | same — **in the harness** |
| `openapi.has-paths` | the document declares at least one path | same — **in the harness** |
| `openapi.paths-are-versioned` | every path is under a `/vN` prefix | same — **in the harness** |
| `openapi.one-version-prefix` | one `/vN` per document | same — **in the harness** |
| `openapi.errors-are-problems` | every non-2xx declares `application/problem+json` | `docs/openapi-conventions.md`, "Error envelope" — **in the harness** |
| `openapi.problem-code-matches-type` | `code` is the last segment of `type`, in `snake_case` | same — **in the harness** |
| `openapi.reserved-error-codes` | a reserved code carries its fixed status | same — **in the harness** |
| `openapi.problem-has-trace-id` | the problem schema requires `trace_id` | same — **in the harness** |
| `openapi.no-offset-pagination` | no `offset`, `page`, `skip`, … query parameter | `docs/openapi-conventions.md`, "Pagination" — **in the harness** |
| `openapi.page-envelope` | a cursor in, `{data, page{next_cursor, has_more}}` out | same — **in the harness** |
| `openapi.idempotency-key` | every mutating `POST` accepts `Idempotency-Key` | `docs/openapi-conventions.md`, "Idempotency" — **in the harness** |
| `openapi.idempotency-conflict-documented` | …and declares the 409 a reused key returns | same — **in the harness** |
| `core.digest-mismatch` | core's `schemas/` digests to the pin | **in the harness** |
| `core.not-a-checkout` | the directory named is a core checkout | **in the harness** |
| `core.absent` | the run says where it looked, and never skips | **in the harness** |
| `core.constraint-unmet` | the declared `core:` admits the version core publishes | `docs/core-version.md` — **in the harness**; the resolver is `harness/core_version.py` |
| `core.constraint-unresolvable` | a `core:` is present, is a string, and is in the grammar | same — **in the harness** |
| `core.version-absent` | core publishes exactly one readable version | same — **in the harness**; a refusal, exit 2, never green |
| `service.manifest-absent` | the service root carries a `cafaye.yml` | **in the harness** |
| `yaml.unsupported` | a construct outside the declared subset is refused | **in the harness** |
| `slo.schema` | a declaration satisfies core's SLO schema | `schemas/telemetry/slo.schema.json` — **in the schema** |
| `slo.window-token` | both SLI queries carry `{{.window}}` | **in the harness** |
| `slo.unknown-metric` | every metric in a query is in core's catalogue | **in the harness** |
| `slo.no-unbounded-dimension` | no unbounded dimension in a query or a label | **in the harness** |
| `slo.no-infrastructure-slo` | no infrastructure signal in a query or a label | **in the harness** |
| `slo.sli-canonical` | each query is exactly what its catalogue entry composes to | **in the harness** |
| `slo.window-override` | the declaration carries no burn-rate catalog of its own | **in the harness** |
| `slo.duplicate-name` | one name per SLO, across files too | **in the harness** |
| `compose.postgres-pin` | every postgres image reference in a repository resolves to the tag core declares | `docs/postgres-pin.md` — **in the harness**; a fact about a filesystem, and the tag is `POSTGRES_TAG` at core's root |
| `compose.postgres-tag-absent` | core publishes exactly one readable postgres tag, and it is not `latest` | same — **in the harness**; a refusal, exit 2, never green |

The inventory holds **38** rules: **2** are enforced by a `schemas/` file and
**36** are in the harness's own source — **18** of them reading documents and
**18** running from the harness's code. Of the seventeen that existed before the
SLO packet, one was a schema and sixteen were in code — and **that is not a
finding about the harness — it is the finding**:
`docs/openapi-conventions.md` says in its own words that "until a future
`caf contract lint` lands the rule is review-enforced, like every other
convention here", and sixteen of the rules a service is asked to live by have
never been mechanically checkable at all. The harness does not make them
schemas. It makes them *executable, named, tested and inventoried*, which is
the step before a schema and the step that a manager can now decide on —
[D23](https://github.com/cafaye/core/blob/master/DECISIONS.md) is that decision,
and it is open because the list of sixteen did not exist a week ago.

## The postgres pin, and the two facts it had to be told

`compose.postgres-pin` is the one rule here that is about a **filesystem** rather
than a document, and it is described in
[`docs/postgres-pin.md`](postgres-pin.md). Three things about it are worth having
in this file too, because they are the general shape rather than the pin's own:

- **The standard is a published fact, and a refusal guards it.** `POSTGRES_TAG` at
  core's root holds one tag, and `compose.postgres-tag-absent` **refuses (exit
  2)** when there is not exactly one — the same discipline as `VERSION`, and for
  the same reason. A core that publishes no standard leaves the rule with nothing
  to compare against, and a run that cannot find what it is checking has
  converted an unknown into a pass. `latest` is refused too, because it is the
  one value that would make the rule pass exactly the references it exists to
  fail. It is a **root** file and not one under `schemas/`, because putting it
  there would change `contract_digest` and turn every pinned service red on a
  file none of them consumes.
- **The rule reads executable declarations, and prose is a named exclusion.** An
  `image:` key in a compose file or a workflow's `services:`, and a
  `docker run` line in a script. **Not** prose: a `grep -r 'postgres:'` over the
  fleet's own history finds `postgres:17` in six CHANGELOGs and
  `postgres:18-alpine` in muse's, every one of them correct about when it was
  written. A rule that read history would turn six changelogs red for being
  accurate, and the fix a service owner reaches for is deleting the record. It is
  the same reasoning as `OFFSET_PARAMETER_NAMES` being a named list rather than a
  pattern.
- **A DSN is not an image reference, and that is a credential-safety property.**
  `postgres://user:pass@host/db` appears in scripts across this fleet and it
  carries a password. A scanner that read `postgres:` at the start of one as a
  floating image reference would print a **credential into a build log** as the
  evidence for a finding. The tag pattern cannot begin with `/`, so it cannot
  match, and `test_a_dsn_is_not_a_postgres_image_reference` runs the reader over
  core's own self-test scripts — which really do contain
  `postgres://gate:should-never-be-printed@localhost:5432/gate`.

**The adoption ceiling is nine of eleven, not eleven of eleven.** D24 and the
core-18 brief both recorded the fleet as uniform. Measured over the eleven image
declarations in the workspace, nine resolve to the declared tag; `identity`'s CI
pins `17.11-alpine` against its own compose file's `17-alpine`, and `kit`'s
template defaults to `16.6-alpine`. Both are real. The rule is a hard failure
anyway, because **a severity chosen to make today's tree green is a warning
wearing a rule's clothes** — and nothing adopts the harness yet, so no build turns
red today. `test_the_scan_reads_the_real_fleet_and_its_result_is_recorded_here`
holds the measurement, so the two go red together when a repository is fixed.

## SLOs, and the eight rules that decide them

A service declares its SLOs in `slos/*.yaml` as a Sloth `prometheus/v1` file, and
the harness reads them against core's three schemas. [`docs/slo.md`](slo.md) is
the specification; the shape of the arrangement is worth stating here too:

- **The catalogue is read out of `schemas/`, not copied into this file.** The SLI
  composition is computed from `slo-metrics.schema.json`, so `--expect-digest`
  covers it. A second copy would be a second answer to "which metrics exist",
  which is the drift the digest exists to prevent.
- **The SLO rules are not gated behind `slo.schema`.** Every one of them reads a
  string, and a string is readable on a document whose tier is wrong. A gate here
  would mean a service's first SLO failure is "your objective is 100" and never
  "your query has no `{{.window}}`".
- **`slo.sli-canonical` compares strings, not meaning.** It is stricter than
  Sloth about the shape of a query and blinder about the grammar, which is the
  trade recorded in [`rules.json`](../harness/rules.json)'s `notEnforced` and in
  [D28](https://github.com/cafaye/core/blob/master/DECISIONS.md).
- **A service with no `slos/` directory is checked on no SLO rules**, for the
  same reason a worker-only manifest is checked on no OpenAPI rules. That is in
  `notEnforced` too, so the absence cannot read as a pass over something.

Two of the eight are the same scan over the same query with different lists —
`slo.no-unbounded-dimension` and `slo.no-infrastructure-slo` share
`_denylisted`. They are two rules because they are two prohibitions with two
reasons, and the reason is what a reader has at the moment they are about to add
one. The coupling is recorded in the inventory, as `event.payload-schema-missing`'s
is.
`event.unknown-published` is not in
[`docs/manifest-conventions.md`](manifest-conventions.md) today; it is the other
half of rule 6 and this document and the inventory are its home until a manager
moves it. See [D22](https://github.com/cafaye/core/blob/master/DECISIONS.md).

Two structural notes a reader will otherwise have to discover:

- **`event.payload-schema-missing` cannot fire on its own.** Every catalogued
  type has a payload schema, so a published type without one is necessarily not
  in the catalog, and `event.unknown-published` fires alongside it. The two rules
  are coupled, self-test breakage 8 asserts both, and the coupling is recorded
  in the inventory.
- **The manifest schema is a gate, and the cross-field rules only run past it.**
  A document whose fields are the wrong type is a document whose cross-field
  comparisons would be comparing nothing. `caf`'s linter makes the same call, and
  the harness prints that it stopped rather than letting a quiet half-run read as
  a pass.

## The two hand-written pieces, and the receipts for them

The standard library has no JSON Schema and no YAML. Both are in this repository
rather than in a dependency, and both are receipts rather than claims.

**The evaluator.** 27 keywords, exactly the inventory of `schemas/`.
`test_the_harness_evaluator_agrees_with_jsonschema_on_every_example` compares
violated keywords with `jsonschema` over every example in `examples/`, in both
directions, and
`test_the_harness_implements_every_keyword_core_schemas_use` holds the keyword
list equal in both directions — a keyword nothing implements is an unenforced
rule, and a keyword nothing uses is a rule with no test. The equivalence test
found a real bug within the hour: a `type` array is a union, and the first
version reported a violation per non-matching member, so the envelope's `data` —
declared as any of seven types, correctly holding an object — produced six
failures. **Read that test before trusting the evaluator.**

One deliberate divergence: `CHECKED_FORMATS` includes `uri`, which `jsonschema`
does not check without `rfc3987-validator` installed. So on a `format: uri`
failure the two disagree and the harness is the stricter one. That is a gap in
core's own suite, the harness made it visible, and it is
[D22](https://github.com/cafaye/core/blob/master/DECISIONS.md) —
`tests/requirements.txt` already carries the same note about `date-time`.

**The YAML reader**, and the reversal that shaped it.

The first version read a deliberately small subset and refused everything else,
on the reasoning that a guess means validating a document nobody wrote. Then it
was pointed at the eleven real service repositories in the cafaye workspace and
**eight of eleven refused** — six on a `description:` field, two on a leading
`---`, the rest on `tags: [users]`.

That settled the argument, in the direction the argument had been arguing
against. Guessing wrongly means a *schema* error printed against a value the
harness invented, which sends a person to the wrong field. Refusing a document
the entire fleet writes means the harness checks nothing at all, which is worse
and is the failure this packet exists to end. So the subset is now the one the
fleet writes: block mappings and sequences, block scalars with their chomping
and indentation indicators, plain scalars continued across lines, quoted
scalars, flow collections of scalars including across lines, `[]` and `{}`, the
literals, integers and floats, a leading `---`, and comments. Every one of those
is in because a real document uses it.

What is left is what no real document needed: anchors, aliases, tags,
directives, merge keys, nested flow collections, a flow collection that never
closes, a tab, a duplicate key, and a second document in one file.
`YAML_REFUSALS` is the list, and
`test_the_harness_yaml_reader_refuses_only_what_it_declares` asserts it *and*
that the reader actually refuses each one.

The receipts, and they are the whole argument for the reader:

- `test_the_harness_yaml_reader_reads_every_document_in_this_repository` — every
  YAML file core owns, read, and equal to PyYAML's value. **One named
  exception**: PyYAML implements YAML 1.1, where the bare word `on` is the
  boolean `True`, and the harness implements the 1.2 core schema, where it is
  the string GitHub Actions means. Asserted, not excluded, because "agrees
  everywhere" should have exactly one visible exception and no silent ones.
- `test_the_harness_yaml_reader_reads_what_the_fleet_writes` — each newly
  supported construct, against PyYAML.
- `test_the_harness_yaml_reader_agrees_with_pyyaml_on_every_fold` — the folds,
  separately, because a fold can be *almost* right. The fourth case is the one
  worth knowing about: a more-indented line keeps the break on **both** sides
  of it, and the first version of the fold tracked the previous line while the
  second tracked the next. billing's `change_plan` description is the document
  that showed both were wrong, and the measured table is in the source.
- And outside this repository, over the thirty-three real `cafaye.yml` and
  `openapi/*.yaml` files in the cafaye workspace: **thirty-three identical, zero
  mismatched, zero refused.**


## What it found in the fleet, on its first run

The harness was pointed at the eleven real service repositories in the cafaye
workspace as soon as it could read their documents. Eight conform, and the three
that do not are the argument for the thing existing:

The repository names are plain text in the first column, not code font, on
purpose: that column is parsed as the rule inventory further up this document,
and a backticked `identity` in it reads as a rule the harness enforces and does
not.

| Service | What the harness found |
| --- | --- |
| identity | publishes `identity.oidc_client.created` and `.revoked`, which core's catalog does not list and which have no payload schema; `identity.mfa.enabled` and `.disabled` are catalogued but have no payload schema; `/healthz` and `/readyz` are documented and unversioned |
| darkroom | publishes `darkroom.asset.ready`, `.asset.deleted` and `.variant.created`, none catalogued and none with a payload schema; `/healthz` and `/readyz` documented and unversioned |
| pantry | `/healthz` and `/readyz` documented and unversioned |

Every one of those is checkable by hand today and none of it is checked by
anything. That is the gap, stated in the only terms that matter: the rules were
already in core and four services already had four bespoke mechanisms for
checking them.

The probe finding is a **spec gap rather than a service bug**, and it is
[D25](https://github.com/cafaye/core/blob/master/DECISIONS.md): `courier`
deliberately leaves `/healthz` and `/readyz` out of its document and says so in
the file header, `identity` and `pantry` document them, and
[`openapi-conventions.md`](openapi-conventions.md) does not say which is right.
The harness reports what the document says; the document needs a sentence.

## Proving the harness can fail

```
bash harness/tests/self_test.sh
```

Twenty deliberate breakages, twenty reds, and a control on the unbroken tree
first — without it the breakages prove nothing. Every breakage names the rule id
it expects, because "the harness went red" is a weak claim when seventeen checks
can make it red: a breakage caught by the wrong check still reads as a pass, and
the check it was written for can be dead code forever.

All seventeen rules have at least one breakage. The mutations are chosen the way
kit chose its own: not a typo a reviewer would see, but the mistake that looks
like diligence — an HTTPS remote, a core constraint with no patch component, a
second `/vN` prefix added beside the first, a one-byte change to a schema
against a pinned digest. The first version of the second-prefix breakage
*renamed* a path instead of adding one and the harness stayed green, correctly,
because a rename leaves one prefix behind; that is courier's route-count lesson
arriving three repositories later.

CI runs it. `bin/prime` runs the suite, which includes the harness's own tests
but not this script — the same split kit makes, because a self-test that ran
inside every gate invocation would be a second gate that can disagree with the
first. The `gate` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
has a step for it, and a comment claiming CI runs something is not CI running
it (PLAN.md §1).

## Adopting it

This packet deliberately migrates **no** service. One packet, one repository: a
harness adopted by four services at once is four workers in four languages
discovering four things nobody anticipated, and the manager would not be able to
tell which of them found a bug in the harness.

For a service that wants it, the whole thing is a CI step and a checkout:

```yaml
- uses: actions/checkout@v7          # cafaye/core at the ref you pinned
  with: { repository: cafaye/core, ref: <your pinned sha> }
- uses: actions/checkout@v7          # your service
- run: core/harness/bin/cafaye-contract --core core --expect-digest "$DIGEST" .
```

Add `--expect-digest` on the first run: run once without it, read the digest
off the `OK` line, and pin that. Until you do, the digest is still printed on
every run and the pin is still one argument away.

# REPORT — core-17: make `core:` mean something

**Branch:** `worker/core-17-pinversion` · **Not pushed. I created no tag.**

**This is the second pass.** The first was killed by an out-of-memory restart and
its work was committed as `recover(worker/core-17-pinversion)`. Everything below
was re-measured and re-run by me; where the first pass reached a conclusion, I
checked it rather than inheriting it, and §1 records where it was wrong.

## Result

| Suite | Pass | Fail | **Skip** |
| --- | --- | --- | --- |
| `bin/prime` | **176** | 0 | **0** |
| `harness/tests/core_version_test.sh` | **21** (+4 breakages proved red) | 0 | **0** |
| `harness/tests/self_test.sh` | 28 breakages red, control green | — | **0** |
| `harness/tests/gate_self_test.sh` | 25 breakages red, 7 warnings green, 12 shapes accepted, 4 extractor assertions, 1 control | — | **0** |

Pass and skip counts reported separately, as the brief requires. **No skip
exists anywhere in this packet and none was added** — a skip is the defect this
packet exists to remove, so `core_version_test.sh` prints its skip count and
fails the run if it is ever non-zero.

---

## 1. Re-verification: the brief, and the first pass

The brief said *"re-verify all of this yourself before building on it. If it does
not reproduce, that is the finding."* I re-measured all of it.

### Did not reproduce: `identity` does not publish `account.created`

> *brief: "identity publishes `account.created`, the two-segment form 0.2.0
> explicitly forbids, under a `^0.1.0` declaration."*

**There is no two-segment event anywhere in the fleet.** Measured:

```
$ rg 'Event\w+ *= *"' identity/internal --glob '!*_test.go'
AccountCreated  ->  identity.account.created        # three segments, correct
…12 types, all three-segment…
```

The bare string `account.created` appears only in comments and in a test map
key. The severity is therefore **lower than the brief stated**: the drift is a
mis-declaration of `^0.1.0`, not a published contract violation. No service
ships an event type the schema forbids.

**The first pass found this and was right. I confirmed it independently rather
than taking it on trust, and the `v0.2.0` tag message still repeats the false
claim** (see §1.4).

#### The worse, real defect in the same place

Since the specific claim was false, I measured the whole direction it pointed at:

```
published in Go (internal/, 12 types)   vs   declared in exposes.events (7)
```

**Five events `identity` publishes are not in its own manifest**, and core ships
**one** payload schema (`schemas/events/identity/user/created.schema.json`) for
twelve published types:

| Event | In `exposes.events`? | In core's catalog? | Payload schema? |
| --- | --- | --- | --- |
| `identity.account.created` | no | yes | **no** |
| `identity.member.invited` | no | yes | **no** |
| `identity.member.removed` | no | yes | **no** |
| `identity.member.role_changed` | no | yes | **no** |
| `identity.member.accepted` | no | **no** | **no** |

So the true defect is not a malformed event type; it is that **`exposes.events`
is not a complete declaration of what a service publishes** — a contract that
does not say what it means, one layer over. No core rule catches it, because
every rule reads the *manifest* and none reads a service's source. **Not this
packet's work** (it needs a decision about reading another language's code).
Flagged, not done.

### Did not reproduce: the CI ref census

> *brief: "Of five CI workflows checking out `cafaye/core`, three use `ref:
> ${{ env.CORE_REF }}` and two use `ref: master`."*

Measured across every `*/.github/workflows/*.yml`:

| Service | Mechanism | Ref |
| --- | --- | --- |
| `billing` | checkout | `ref: master` |
| `docs` | checkout | `ref: ${{ env.CORE_REF }}` where `CORE_REF: 'master'` |
| `muse` | checkout | `ref: ${{ env.CORE_REF }}` — a pinned **sha** `15e541cd` |
| `guard` | **raw URL, not a checkout** | `raw.githubusercontent.com/cafaye/core/master/<schema>` |
| `pantry` | **vendir** | `vendir.lock.yml`, `ref: master` + recorded sha |

**Four workflows reference core, three of them checkouts**; of those three it is
one `master` / two `CORE_REF`, not three / two. And `guard` is the one the brief
missed: not a checkout at all.

**This makes the finding worse, not better, and I corrected the docs accordingly.**
The brief implied `identity`, `courier` and `guard` were handed `master`. **None
of the three has a workflow that checks out core at all.** Their gates read core
from somewhere outside CI, so there is no ref in them to be wrong — the
declaration is false and *nothing in their CI can reveal it*. I fixed
`docs/contract-harness.md`, which still carried the brief's version of this
claim as shipped prose.

### Reproduced exactly

- `core:` declarations: `^0.1.0` in `identity`, `courier`, `guard`; `^0.2.0` in
  the nine that declare one; **`parlor` declares none**.
- `harness/cafaye_contract.py` said in its own docstring that it *"does not
  resolve a `core:` constraint"*, and `RULE_IDS` held only `core.absent`,
  `core.not-a-checkout`, `core.digest-mismatch` — presence, not version.
- The version existed only as a `## [0.2.0]` heading in `CHANGELOG.md`.
- The `vendir` count (2 real repositories) is right; the env-var counts are not
  (§5).

### 1.4 The tag now exists — and its message repeats the false claim

```
$ git ls-remote --tags origin
d43f3992ad691fbc352baafc670ba3931c8689fe  refs/tags/v0.2.0      # tag object
c63af27aaabb33f36a393f4f44dbe887505d78ed  refs/tags/v0.2.0^{}   # what it names
```

**`v0.2.0` is tagged and pushed. I did not create it and have not touched it.**
It names `c63af27` — this branch's base commit.

One thing I checked because it decides whether `VERSION` is telling the truth:
**`schemas/` is byte-identical between `c63af27` and `master`** (master is now
`0a711cf`, core-14's work). So master's contract bytes *are* 0.2.0's, and
`VERSION` reading `0.2.0` on a tree that has moved on is accurate. The next
change under `schemas/` is what makes the next version.

**Two published artefacts carry the false `account.created` claim** — the
`v0.2.0` tag message (*"identity still publishes the two-segment
`account.created`"*) and `DEBT.md` D22. Both are the brief's claim, and both are
wrong (§1). A service owner reading that release note will go looking for a
two-segment event that does not exist and will not find the five undeclared
events that do. **Amending a published tag is the owner's call, not mine; I am
reporting it because I am the one who measured it.**

### 1.5 `kit` already owns the fetch standard — the first pass declared a second one

**This is the substantive correction I made, and the first pass had it wrong.**

The first pass's `docs/core-version.md` declared `actions/checkout` at a tag
into `.cafaye/core` as "the one way to fetch core". That is a **fourth
mechanism**, and it competes with one that already exists, is already owned, and
is already verified:

- `kit/core/vendir/` ships three real per-service configs, a template, a Renovate
  policy and a release workflow, and `kit/core/vendir/README.md` records that
  every claim in it was checked by **running vendir 0.46.2 against the real
  repository** — including the three traps (an `includePaths` written as a child
  of `git:` is silently dropped and vendors the whole repo; a missing
  `vendir.lock.yml` makes Renovate emit a pin bump that does not re-copy bytes;
  a `git:` source resolves a tag to that tag's tree and records tag **and** sha).
- `kit/core/release/release.yml` is **core's own release gate**, written down and
  waiting to be installed at `core/.github/workflows/release.yml`. It computes
  the version from the previous tag and refuses to move a tag.

Declaring a competing mechanism from `core` would be the exact defect the
section exists to remove. I rewrote the section to adopt `vendir`, name the pin
as a tag, and contribute the **one thing kit's templates do not carry**.

### 1.6 What I found in `kit` that is now stale — and what core actually needs

**Every `kit/core/vendir/vendir.yml.*` vendors one schema file.** That is right
for a service that *embeds* a document (`muse` embeds `traces.schema.json`,
`pantry` the manifest schema — moving either is a source change, not a config
drop). It is the wrong shape for the other consumer: **the contract harness
itself**, which is a program that has to run and is handed a core through
`--core`.

So I measured which paths a harness consumer must vendor, by building core trees
out of candidate paths and running the harness until it was satisfied:

| Vendored | Harness |
| --- | --- |
| `VERSION`, `harness/`, `schemas/` | **exit 1** — wants `docs/` |
| + `docs/` in full | exit 0 |
| one `docs/` file at a time | **`docs/event-naming.md` alone → exit 0** |
| `examples/`, `fleet.yml` | not read; adding them changes nothing |

**Four paths: `VERSION`, `harness/**`, `schemas/**`, `docs/event-naming.md`** —
and each has a rule that needs it. That is core's contribution, and it is a fact
about *this* repository, so it holds.

**Stale in `kit`, and I did not edit it (not my repository):** `kit/core/README.md`
and `kit/core/release/release.yml` say in three places that `cafaye/core` has
zero tags and `ref: v0.3.0` therefore fails. All three were true when written and
are false now. All four vendir configs still say `ref: master` for the same
reason. The caveat they attach — "the tag half of the design is unproven" — is
no longer a reason to use `ref: master`.

**What I did not verify, stated plainly:** **vendir is not installed on this
machine, so the `vendir` config in the document was never run.** Unlike `kit`'s
documentation I make no claim about how vendir behaves; I inherit `kit`'s, which
was measured. Writing a config and running it are different claims.

---

## 2. The toolchain half — required, and now in the mechanism

The manager's note: *cafaye-rb's gate failed until mise's Ruby was on `PATH`, so
the fetch mechanism should cover toolchain discovery too.*

Measured the shape of it. `mise` writes shims into `~/.local/share/mise/shims`
and puts them on `PATH` only for an activated shell or a command run through
`mise exec` / `mise x`. On this machine `ruby` resolves to
`/Users/kaka/.local/share/mise/shims/ruby` — which is the whole failure in one
path: installed, and not on `PATH` until something activates it. **`mise install`
is not activation.**

So the mechanism now has two halves, and `docs/core-version.md` says a step that
does only the first is incomplete:

```yaml
- run: mise install
- run: mise exec -- python3 .cafaye/core/harness/bin/cafaye-contract --core .cafaye/core .
```

**I did not invent a rule for this, because core already owns both halves:**

- **The declaration half is enforced.** `gate.yml` + `harness/gate_check.py`:
  `gate.miseTask` must name a task that exists in the repository's `mise.toml`
  and resolve to the declared entrypoint (`gate.task-unresolvable`,
  `gate.task-undeclared`), and the workflow must reach the gate through that
  named task or say so (`gate.ci-disagrees`, `gate.ci-unproven`). A workflow
  calling `ruby` directly instead of `mise run <task>` is a finding.
- **The runtime half is already named as not enforced** — it is the **first
  entry in `harness/gate_findings.json`'s `notEnforced` list**: *"An external
  requirement is actually satisfied on the machine running the check."* `ruby`
  being on `PATH` is an instance. That is the correct home for it, and putting it
  there rather than writing a duplicate rule is the whole point of that list.
- **Core's own half is already a rule, not a hope.**
  `harness/bin/cafaye-contract` finds an interpreter or **exits 2 with a
  sentence**, and the resolver import is guarded so a copy of one file without
  the other **refuses rather than quietly checking less**.

So the honest summary, and it is a real limit rather than a hedge: **core can
prove a repository declares its toolchain and that CI reaches the gate through
that declaration. It cannot prove the runner had the interpreter installed.**

---

## 3. What the rules do, and where they fire

Three rules, wired into the existing idiom: `core.constraint-unmet` (exit 1) ·
`core.constraint-unresolvable` (exit 1) · `core.version-absent` (**exit 2**).

The 1-vs-2 split is the design: a service whose `core:` disagrees is **wrong**
(fix the manifest); a core publishing no version means the check **could not
happen** (fix the checkout). Reporting the second as the first would send an
owner to a manifest that was not the problem — the same defect shape as the four
skipped test tiers core already documents.

Read-only, against the live checkouts, run by me:

```
identity  ^0.1.0  exit=1  FAIL core.constraint-unmet
courier   ^0.1.0  exit=1  FAIL core.constraint-unmet
guard     ^0.1.0  exit=1  FAIL core.constraint-unmet
billing   ^0.2.0  exit=0
muse      ^0.2.0  exit=0
cafe       ^0.2.0  exit=0
cafaye-rb ^0.2.0  exit=0
cafaye-ts ^0.2.0  exit=0
docs      ^0.2.0  exit=0
pantry    ^0.2.0  exit=1  (pre-existing: openapi.paths-are-versioned ×2)
darkroom  ^0.2.0  exit=1  (pre-existing: event.unknown-published ×3,
                          event.payload-schema-missing ×3,
                          openapi.paths-are-versioned ×2)
```

Exactly the three the brief predicted, silent on the seven that declare `^0.2.0`.
I checked `pantry` and `darkroom`'s failures rule by rule: **none is a version
rule**, both are pre-existing and unrelated.

**No `core:` at all is deliberately not a rule here.** `core` is in `required` in
the manifest schema, so absence is `manifest.schema`'s finding; a second rule
would be two rules that could disagree about the same manifest. `check()` is total
anyway — handed a non-string it reports unresolvable rather than raising, so a
future loosening of the schema degrades to a finding, not a crash. `parlor` is
the live case and is already `manifest.schema`'s to report.

### The resolver is a transliteration, and I checked it against the Go source

`harness/core_version.py` re-derives nothing. I read
`cafe/internal/contract/version.go` and compared: `constraintPattern`,
`versionPattern`, `caretCeiling`, `Satisfies`, `Bounds`, `operatorOf` and
`Resolve` are the same functions, and the two patterns are byte-identical.

**One divergence, now documented rather than left as an accident:** the Python
parsers call `.strip()`; the Go ones do not. It cannot change an answer —
`semverRange` is anchored `^…$`, so a `core:` value with stray whitespace is not
schema-valid and never reaches the resolver — and the leniency earns its place by
letting `read_version` read a `VERSION` file that ends in a newline. The
load-bearing strictness, the refusal of a leading zero, is Go's exactly. I did not
add a cross-repository test that diffs the two files: core's suite deliberately
reads no sibling repository, and making `bin/prime` depend on `../cafe` existing
would be a worse trade than the comment.

---

## 4. The red proof, and the one gap I closed in it

`harness/tests/core_version_test.sh` — 21 passed, 0 failed, **0 skipped**, 4
breakages proved red.

**The proof is rot-proof by construction.** Every breakage in `self_test.sh` is
chosen to be *permanently* broken. This packet's central assertion is not:
**`^0.1.0` stops being a violation the moment core publishes 0.3.0.** A fixture
pinned to it goes quietly green and nobody re-reads it. So the script **derives**
the conflicting constraint from the version core actually publishes — a caret one
minor *ahead*, which no version of core can satisfy — and proves the red there. On
today's tree that is `^0.3.0` against a published `0.2.0`.

That is also why it is a separate file rather than a section of `self_test.sh`:
mixing them would give one file two owners.

### The gap: a dependency could arrive in the resolver uncaught by the static proof

The packet widens the harness's stdlib allowlist to cover `core_version`. Widening
a proof's *exemptions* without widening its *coverage* is how a proof quietly
stops proving, so I mutation-tested it rather than assuming.

| Mutation | Before | After |
| --- | --- | --- |
| `import jsonschema` in `cafaye_contract.py` | red (static proof) | red (static proof) |
| `import jsonschema` in **`core_version.py`** | **red only incidentally** — caught by the runtime `-I` proofs, not the static one | **red, by the static proof, naming the file** |
| `import jsonschema` in a **new** `harness/*.py` nothing imports | **nothing caught it** | red, naming the file |

The static proof walked exactly one file while claiming to speak for `harness/`.
`test_the_harness_imports_nothing_outside_the_standard_library` now walks **every
module in `harness/` except `gate_check.py`**, and the sibling exemption is
**computed from the tree** — a name is exempt exactly when a file of that name
exists — so an exemption cannot outlive the file that justified it.
`gate_check.py` is excluded on purpose: it is a separate tool with its own,
stricter proof, and one test covering both is a test whose exemptions belong to
neither. Three mutations, three reds, then the tree restored.

The two runtime proofs (`…site_packages_disabled`,
`…gate_checker_needs_nothing_core_does_not_ship`) still catch the sibling case
too, and both were confirmed still red under the mutation. **Nothing was
weakened to make this pass.**

---

## 5. The counts in the brief, measured

Counted as the **migration surface** — tracked, non-markdown files and their
occurrences — because the number that decides whether something is a one-line
change is the number of places a reader must learn a second way to find core.

| Brief said | Measured | Note |
| --- | --- | --- |
| `MUSE_CORE_SCHEMAS` — 10 uses | **9 files, 23 occurrences** | `ci.yml`×6, `gate.yml`×2, `pyproject.toml`, 2 `src/` modules, 4 test files |
| `PANTRY_CAFAYE_ROOT` — 6 uses | **8 files, 25 occurrences** | `ci.yml`×2, `bin/prime`, `registry/index.yml`, 5 test files |
| `vendir` — 2 | **2** ✓ | `pantry/`, `kit/core/release/release.yml` |
| 5 workflows / 3 `CORE_REF` / 2 `master` | **4 workflows, 3 checkouts, 1 `master`, 2 `CORE_REF`, + guard's raw fetch** | §1 |
| `identity` publishes `account.created` | **it does not** | §1 |
| 0 tags | **1 tag, pushed** — `v0.2.0` → `c63af27` | §1.4 |

Larger than the brief's because the brief counted mentions and I counted the
surface. **48 read sites** across the two variables is the number this section
exists to move, and it is not a one-line change.

---

## 6. Files touched — and the collisions, stated plainly

**New — no collision with any other worker:**

| File | What |
| --- | --- |
| `VERSION` | the published version, one line, `0.2.0` |
| `harness/core_version.py` | the resolver |
| `harness/tests/core_version_test.sh` | the rot-proof red proof (not `gate_self_test.sh`) |
| `harness/tests/fixtures/nonconforming-core-version/` | the fixture, `^0.1.0`, copied from the fleet |
| `docs/core-version.md` | version contract, grammar, rules, fetch mechanism, toolchain, migration |
| `REPORT-core-17.md` | this file |

**Edited — four shared files, each one forced and each one minimal:**

1. **`harness/cafaye_contract.py`** (core-16's, as the brief warned). **Four
   edits, all in or adjacent to the rule table**: the sibling `import` shim
   (mirroring `gate_check.py`'s existing precedent), 3 ids in `RULE_IDS`, 1 entry
   in `REFUSALS`, 1 `findings.extend` in `_check_service`. Plus a
   `check_core_version` adapter and the module docstring, which said "does not
   resolve a `core:` constraint" and no longer may.
   **Merge guidance:** `RULE_IDS`, `REFUSALS` and the `findings.extend` block are
   the three conflict points. `check_core_version` and the import shim are new
   identifiers and should apply cleanly.

2. **`tests/test_specs.py`** (core-14's). Three tests, plus one line
   (`siblings = {"core_version"}` in the AST walk, structurally unavoidable — a
   second module in `harness/` cannot be imported without it, and
   `gate_check.py` already carries the identical exemption for the same reason),
   plus **this pass's rewrite of the stdlib proof to cover every travelling
   module** (§4). None of it weakens anything; the stdlib proof is *stronger*
   than it was on `master`.

3. **`gate.yml`** — the `minimum:` ratchet, **173 → 176**. Raised because three
   tests were added, which is what the ratchet is *for*. **Not lowered. Not
   touched otherwise.** Most likely conflict point in this packet.

4. **`docs/contract-harness.md`** — +3 table rows, count 25→28, the "not built"
   section rewritten, and **this pass's correction of the false
   "three services' workflows fetched `master`" claim**. The table and the prose
   bullet are both places core-16 will be editing.

Also: `harness/rules.json` (+3 entries), `harness/tests/self_test.sh` (**one
line** — its synthetic core now copies `VERSION`), `README.md` (one docs row).

**Deliberately not touched: `CHANGELOG.md` and `DECISIONS.md`**, which the brief
assigns to `core-15-tenancy`, and `bin/prime` / `harness/gate_check.py`, which
the brief assigns to `core-14-localgate`. Also untouched: every service
repository, and `kit` (§1.5 — its stale tag claims are kit's to correct).

### One existing test legitimately had to change

`test_the_harness_digest_is_the_pin_and_it_notices_a_changed_schema` builds a
synthetic core from `schemas/` + `docs/` and asserts it is otherwise a pass. It
went red — **because the new refusal correctly rejected a core with no
`VERSION`.** The test now copies `VERSION` too, with a comment saying why: a copy
of core's contract surface is no longer a copy without it. **This was a real bug
in the test, caught by the new rule, and it is the best evidence the rule
works.** `self_test.sh`'s synthetic core got the same one-line fix — without it,
breakage 14 would have gone red via `core.version-absent` instead of
`core.digest-mismatch`, and a breakage caught by the wrong rule is exactly what
`expect_red` exists to reject.

---

## 7. For the manager, in priority order

1. **Sequencing — this makes three services red.** `identity`, `courier` and
   `guard` fail `core.constraint-unmet` the moment they adopt a core checkout.
   Each needs one line: `^0.1.0` → `^0.2.0`. **They need it anyway** — they are
   already compiling against 0.2.0 content, so the declaration is a lie today
   and the fix is a truth, not a concession. Land the three one-liners first;
   there is no reason to make three gates red for a fact that was already true.
2. **Merge order, by conflict risk:** `gate.yml`'s `minimum:` and the three edit
   sites in `harness/cafaye_contract.py` are where core-14 and core-16 collide
   with me. Everything else is new files.
3. **Two published artefacts carry a claim I measured to be false** — the
   `v0.2.0` tag message and `DEBT.md` D22, both repeating "identity publishes
   the two-segment `account.created`" (§1). Correcting a pushed tag is the
   owner's call.
4. **`kit` has three stale "core has zero tags" claims and four `ref: master`
   configs** (§1.6). Not mine to edit; worth an owner.
5. **`parlor`** declares no `core:` and is a `v0-draft` shape throughout. Already
   `manifest.schema`'s finding; reconciling it is its own packet. Nothing here
   blocks or enables it.

## 8. Decisions made, with the cost of flipping each

The brief says never ask, make the call, write down the reasoning. `AGENTS.md`
says specs are manager-owned and a genuine question must not be silently
resolved — and `test_no_open_decision_callouts_remain_in_the_docs` forbids a
`DECISION NEEDED` marker from surviving. So each is **decided, argued and priced**
in `docs/core-version.md`, which satisfies both. None blocks a merge:

- **`contract_digest` does not cover `VERSION`.** *Flip:* one line plus a
  fleet-wide `--expect-digest` re-pin. Default chosen because a docs-only release
  must not force six services to re-pin.
- **The fetch mechanism is `vendir`, kit's, not `actions/checkout`.** *This pass's
  correction* (§1.5). *Flip:* back to a checkout, but then core is declaring a
  fourth spelling and `kit`'s configs, template, Renovate policy and release
  workflow are all for a mechanism nothing uses.
- **`.cafaye/core` is the recommended path, not the rule**; the rule is *one
  directory, one committed lockfile, no bespoke env var*. *Flip:* make the path
  mandatory — which then orders a rename in every repository that already embeds
  a vendored document, for a path.
- **`>=` against a pre-1.0 core stays permitted**, as prose not rule.
  `docs/manifest-conventions.md` calls it "a lie" while its own grammar accepts
  it. The resolver matches `cafe` rather than inventing a third opinion. *Flip:*
  tighten `semverRange` (a published-schema break) or change `cafe` first.
- **A tag is the unit; a recorded commit sha is the accepted interim; a branch
  never is.** Now non-hypothetical — the tag exists.

**Nothing was weakened.** No severity lowered, no assertion loosened, no skip
added, no sleep, no retry raised, no token or key logged. The one allowlist the
first pass widened is now covered by a stronger static proof (§4), and the
`gate.yml` floor was raised, not lowered.

## 9. Two limits worth stating

- **The rules read the checkout they are given.** They cannot detect that CI
  fetched the wrong core and then passed `--core` a directory that agrees with
  it. For the three `^0.1.0` services there is not even a ref in their CI to be
  wrong (§1.2). That half is a **convention with a document, not yet a rule** —
  a rule for it would have to read a service's workflow or `vendir.yml`, which is
  a different repository with a different lifetime.
- **The toolchain's runtime half is not enforced**, and is named in
  `harness/gate_findings.json`'s `notEnforced` rather than left to be discovered
  (§2). The declaration half is enforced.
- **The `vendir` config in the document was never run** — vendir is not installed
  here (§1.6). The four vendored paths *were* measured, by building core trees
  and running the harness.

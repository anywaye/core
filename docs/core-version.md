# Core versions, and the one way to fetch them

Core is the substrate every anywaye service compiles against. A service says
which version of it it was written against:

```yaml
# anywaye.yml
core: ^0.2.0
```

Until core-17 that line was a comment with a pattern on it. Nothing resolved it,
because **there was nothing to resolve it against**: `git tag -l` in
`anywaye/core` was empty, and the version existed only as a `## [0.2.0]` heading
in `CHANGELOG.md`. The harness checked that `core` was *present*
(`core.absent`) and never compared it to anything. "One deploy, many services,
all compiling against one core" had no way to notice when core moved under a
service that had already said which core it wanted.

This document states the version contract, the grammar, the three rules that
enforce them, and the one supported way to fetch core. It is the document
`harness/rules.json` cites for `core.constraint-unmet`,
`core.constraint-unresolvable` and `core.version-absent`.

---

## What core publishes

One file, at the repository root, named `VERSION`, holding exactly one
`MAJOR.MINOR.PATCH` line and nothing else:

```
0.2.0
```

Read it with `harness/core_version.py`, or in a shell:

```sh
tr -d '[:space:]' < VERSION
```

Rules about the file, all of them enforced:

- **One line.** A `VERSION` that has been appended to is not a version, and
  reading only the first line would make it one again. `read_version` refuses
  a file with any other number of non-blank lines.
- **No prefix, no prerelease, no build metadata.** `v0.2.0` is not a version
  here. What a release is *tagged* is a separate question — see "The pin: a tag,
  and the tag is real".
- **No leading zeros in any component.** `0.02.0` is not a version. Two
  spellings of one number are two different strings, and a range that accepts
  both is a range nobody can reason about.
- **It agrees with `CHANGELOG.md`.** The topmost released `## [x.y.z]` heading
  is the published version; `## [Unreleased]` is not a version and is skipped.

### Why a file and not a tag, and not a schema

A git tag names a commit in a repository the harness cannot see, and the
harness is offline by contract — it reads a checkout and never fetches one. A
`core:` constraint resolves against *bytes*, and the bytes are the thing a
service is compiling against. That is the same reason `contract_digest` is a
sha256 over `schemas/` and not a commit id, and the same reason the harness
cannot verify a tag even if one existed.

A new schema under `schemas/` would be the wrong shape for a different reason:
`contract_digest` hashes everything under `schemas/`, so adding a file there
changes the pin that six services have already recorded. A version is not part
of the contract bytes; it is the *name* of a set of contract bytes. Putting it
in `schemas/` would conflate the two and force a fleet-wide re-pin for a
docs-only release.

### `contract_digest` does not cover `VERSION` — and should not

**Decided: no.** A release that changes no schema bumps `VERSION` and leaves
the digest alone, so a service pinned to a digest is not forced to re-pin for a
documentation change. A version is the *name* of a set of contract bytes, and
folding it into the hash would conflate the two.

The cost of this choice: a version bump with no schema change is invisible to a
digest-pinned consumer. That is correct — it changed nothing they consume — and
it is the reason this is a decision rather than an oversight.

**To flip:** add `VERSION` to the input of `contract_digest` in
`harness/anywaye_contract.py`, and re-pin every `--expect-digest` in the fleet.
That is one line and six service pull requests, which is why the default is the
other way.

---

## The constraint grammar

Unchanged by this packet, and stated here because the rules below are decided
by it. `docs/manifest-conventions.md` owns the grammar; this section is the
part a resolver needs.

| Form | Admits | Example |
| --- | --- | --- |
| `^A.B.C` | everything that does not change the **left-most non-zero** component | `^0.1.0` → `[0.1.0, 0.2.0)` |
| `~A.B.C` | the minor is pinned | `~1.2.3` → `[1.2.3, 1.3.0)` |
| `>=A.B.C` | open-ended floor | `>=0.1.0` → `[0.1.0, ∞)` |
| `A.B.C` | exactly that version | `0.2.0` → `{0.2.0}` |

**The caret rule for a `0.x` release is the one that matters.** Before 1.0 the
*minor* is the breaking surface, so `^0.1.0` admits `[0.1.0, 0.2.0)` and
**not** `[0.1.0, 1.0.0)`. A service that declares `^0.1.0` and compiles against
0.2.0 content is compiling against something it explicitly declined.

### One resolver, not two

`cafe` already resolves these strings, in Go, at
`cafe/internal/contract/version.go`, and `cafe contract resolve` prints the
answer. `harness/core_version.py` is a transliteration of that file rather than
a second dialect, and `harness/tests/core_version_test.sh` pins every row where
the two could drift — including `^0.0.3` pinning the patch, `~` pinning the
minor, `10.0.0` being newer than `9.0.0`, and the refusal of a leading zero.

A service must never be told it conforms by the Go tool and does not by the
Python one. If they ever disagree, that is a bug in the harness, not a choice.

The resolver is **stricter than the manifest schema**, on purpose. `semverRange`
in `schemas/anywaye.manifest.schema.json` uses `[0-9]+`, so `core: ^0.01.0` is a
schema-valid manifest with an unresolvable constraint. The schema has to accept
what people write; a resolver has to not be lied to. That gap is
`core.constraint-unresolvable`.

### `>=` against a pre-1.0 core is permitted, against this document's own argument

**Decided: permitted, as prose rather than as a rule.**
`docs/manifest-conventions.md` argues that `>=1.0.0` against a `0.x` service is
"not a range, it is a lie" — and the grammar it documents accepts exactly that
construct. The two statements contradict each other, and both are load-bearing:
the doc's argument is *why* the grammar is small.

`harness/core_version.py` therefore permits it, because that is what `cafe`'s Go
resolver does and matching it is the whole point of this section. Inventing a
stricter answer in the harness would be exactly the second dialect that
`harness/core_version.py`'s own docstring says it exists to prevent. So the
prose stands as a **recommendation against `>=` pre-1.0**, and nothing enforces
it, and that is stated rather than papered over.

**To flip:** either tighten `semverRange` in
`schemas/anywaye.manifest.schema.json` to reject `>=` on a `0.x` version — a
breaking change to a published schema, needing an `examples/invalid/` case and a
major bump — or add a rule in `harness/core_version.py` that reports it, which
would diverge from `cafe` and should not be done without changing `cafe` first.

---

## What the harness does about it

Three rules, in `harness/rules.json`, the table in
[`docs/contract-harness.md`](contract-harness.md), and `RULE_IDS` in
`harness/anywaye_contract.py` — three statements of one list, which core's suite
asserts agree.

| Rule | Fires when | Exit |
| --- | --- | --- |
| `core.constraint-unmet` | a declared constraint does not admit the version core publishes | 1 |
| `core.constraint-unresolvable` | `core` is absent, is not a string, or is outside the grammar | 1 |
| `core.version-absent` | core publishes no readable version | **2** |

The split between 1 and 2 is the design, not an implementation detail. A service
whose `core:` disagrees with what core publishes is **wrong** — fix the
manifest. A core that publishes no version means the check **could not happen**
— fix the checkout. Reporting the second as the first would tell a service owner
to change a manifest that was not the problem, which is the same shape of defect
as the four skipped test tiers this repository already documents: muse's
`MUSE_CORE_SCHEMAS`, pantry's `PANTRY_ANYWAYE_ROOT`, identity's
`TEST_DATABASE_URL` and darkroom's `--ignored`.

**No `core:` at all is deliberately not a rule here.** `core` is listed in
`required` by the manifest schema, so a manifest that validates has one, and
absence is `manifest.schema`'s finding. A second rule for the same fact would be
two rules that could disagree about the same manifest. `check()` is nonetheless
total: handed a non-string or missing field it reports
`core.constraint-unresolvable` rather than raising, so a future loosening of the
schema degrades to a clear finding instead of a crash. `parlor` is the live
case — its `anywaye.yml` is a `v0-draft` document with a different shape
throughout and no `core:` key — and it is already `manifest.schema`'s to report.

### What these rules do not do

They read the checkout they are given. They cannot detect that CI fetched the
wrong thing and then passed `--core` a directory that agrees with it. That
half is the next section, and it is a **convention with a document, not yet a
rule** — a rule for it would have to read a service's workflow, which is a
different repository and a different lifetime.

---

## The one way to fetch core

> **This section declares the mechanism. It does not migrate anything.** No
> service repository was touched by the packet that wrote this. Adoption is
> per-service follow-up, and each service is a separate pull request against a
> repository with its own owner.

### The pin: a tag, and the tag is real

```sh
$ git ls-remote --tags origin
d43f3992ad691fbc352baafc670ba3931c8689fe  refs/tags/v0.2.0       # the tag object
c63af27aaabb33f36a393f4f44dbe887505d78ed  refs/tags/v0.2.0^{}    # what it names
```

`v0.2.0` is published and pushed, and it dereferences to `c63af27` — `master`'s
tip at the time it was cut. **`schemas/` is byte-identical between `c63af27`
and `master`**, which is why `VERSION` still reads `0.2.0` on a tree that has
moved on since: master's contract bytes *are* 0.2.0's contract bytes. The next
change under `schemas/` is what makes the next version, not the next commit.

**A tag, never a branch.** `ref: master` compiles against whatever core is
today, which is the defect this whole section exists to remove. A **recorded
commit sha** is the accepted interim where a tag cannot be used yet, and the
fleet already has one: `pantry/vendir.lock.yml` records
`sha: 71d01fd90eae42d452db4431b999e4835949a548`. A sha has neither of the
branch's problems. A moving name has both.

### The fetch: `vendir`, because kit already standardized it

**The fleet has three fetch spellings and one mechanism.** `vendir`, an
`actions/checkout` at a `ref`, and a `curl` of one file over HTTPS are all the
same act — *take core's bytes at a stated pin* — spelled three ways. Declaring a
fourth spelling from `core` would be the exact defect this section is about, so
this document adopts the one that already exists and is owned.

That one is `vendir`, and it is not a proposal: `kit/core/vendir/` ships three
real per-service configs, a template for the rest, a Renovate policy, and a
release workflow, and `kit/core/vendir/README.md` records that every claim in it
was checked by **running vendir 0.46.2 against the real repository**. Three
things there are worth repeating because they are the parts that are silently
wrong if you do not know them:

- `includePaths` is an **exact glob**, and it is a sibling of `git:`, not a
  child. Written as a child it is **dropped without error** and vendir copies
  the entire upstream repository, exiting 0.
- A **committed `vendir.lock.yml` is not optional** — Renovate's extractor
  returns `null` without one, which produces a pull request that moves the pin
  and does not re-copy the bytes.
- A `git:` source resolves a tag to that tag's tree, and the lockfile records
  **both the tag and the sha**, so a tag that later moves is still detectable.

`kit`'s own documents are now stale in one place, and it is worth naming because
this document used to repeat it: `kit/core/README.md` and
`kit/core/release/release.yml` say in three places that `anywaye/core` has zero
tags and that `ref: v0.3.0` therefore fails. All three were true when written
and are false now. That is kit's to correct; the point here is that the caveat
they attach to — "the tag half of the design is unproven" — **is no longer the
reason to use `ref: master`**, which is what all four configs still say.

### What kit's templates do not carry, and this section declares

Every `kit/core/vendir/vendir.yml.*` vendors **one schema file**. That is the
right shape for a service that *embeds* a document in its own source — `muse`
embeds `traces.schema.json`, `pantry` embeds the manifest schema, and moving
either would be a source change, not a config drop.

It is the wrong shape for the other consumer: **the contract harness itself.**
The harness is not a schema, it is a program that has to run, and it reads core
through `--core`. So the paths a harness consumer must vendor were **measured**,
by building a core tree out of candidate paths and running the harness against
it until it was satisfied:

| Vendored | Harness result |
| --- | --- |
| `VERSION`, `harness/`, `schemas/` | **exit 1** — wants `docs/` |
| + `docs/` in full | exit 0 |
| one `docs/` file at a time | **`docs/event-naming.md` alone → exit 0** |
| `examples/`, `fleet.yml` | not read; adding them changes nothing |

So a harness consumer vendors **four paths**, and every one has a rule that
needs it:

```yaml
# .anywaye/core is where it lands. One directory, one record, no environment
# variable to find it with.
apiVersion: vendir.k14s.io/v1alpha1
kind: Config
minimumRequiredVersion: 0.32.0
directories:
  - path: .anywaye/core
    contents:
      - path: .
        includePaths:
          - VERSION               # what `core:` resolves against; without it, exit 2
          - harness/**             # the thing being run
          - schemas/**             # what `contract_digest` hashes and the rules validate
          - docs/event-naming.md   # the event catalog, read by five rules
        git:
          url: https://github.com/anywaye/core.git
          ref: v0.2.0              # a tag, never a branch
```

**`includePaths` is a sibling of `git:`** — see the trap above; this config is
the shape that vendors four paths rather than the whole repository.

Then, and always explicitly:

```sh
python3 .anywaye/core/harness/bin/anywaye-contract --core .anywaye/core .
```

`--core` is never omitted and the harness never searches. `core.absent` and
`core.not-a-checkout` exist because a check that cannot find core has to say
where it looked.

**The path `.anywaye/core` is the recommended default, not the rule.** The rule
is *one directory, one committed lockfile, and no bespoke environment variable*
— because a service that already embeds a vendored document in its own source
(`muse`, `pantry`, `cafe`) cannot move that without a source change, and this
document does not order a fleet-wide rename to tidy a path.

**What was verified and what was not, stated plainly:** the four paths above
were measured by constructing core trees and running the harness, which is a
statement about *which files the harness reads* — and that is a fact about this
repository, so it holds. **The `vendir` config itself was not run.** vendir is
not installed on the machine this was written on, so unlike `kit`'s own
documentation this section makes no claim about how vendir behaves; it inherits
`kit`'s, which was measured. Writing a config and running it are different
claims, and only the first is available here.

### The other half of the same step: the toolchain

Fetching core is half of what a contract step does. The other half is having an
interpreter, and **it failed in this fleet, measured**: `anywaye-rb`'s gate went
red until `mise`'s Ruby was on `PATH`. Nothing about Ruby, `bundler` or that
service was wrong. The toolchain was installed and not *activated*, and a gate
that cannot find its interpreter is a gate reporting on the machine rather than
on the repository.

The mechanism therefore has two halves, and a step that does only the first is
incomplete:

```yaml
- name: toolchain
  run: mise install          # installs the versions mise.toml pins
- name: contract
  run: mise exec -- python3 .anywaye/core/harness/bin/anywaye-contract --core .anywaye/core .
```

`mise install` is **not** activation. `mise` writes shims into
`~/.local/share/mise/shims` and puts them on `PATH` only for a shell that has
been activated or a command run through `mise exec` / `mise x`. That difference
is the whole of the anywaye-rb failure, and `mise exec --` is the spelling that
does not depend on the runner's shell.

**What core already enforces, and it is not nothing.** `gate.yml` and
`harness/gate_check.py` own the declaration half: `gate.miseTask` must name a
task that exists in the repository's `mise.toml` and resolve to the declared
entrypoint (`gate.task-unresolvable`, `gate.task-undeclared`), and the CI
workflow must reach the gate through that named task or say so
(`gate.ci-disagrees`, `gate.ci-unproven`). So "this repository declares its
toolchain, and CI gates through the declaration" is checked. A workflow that
calls `ruby` directly instead of `mise run <task>` is a finding.

**What core cannot enforce, and already says so.** Whether the requirement is
*actually satisfied on the machine running the check* is the first entry in
`harness/gate_findings.json`'s `notEnforced` list, and `ruby` being on `PATH`
is an instance of it. That is the correct place for it: satisfying an external
requirement is the caller's job, before gating, and a checker that shelled out
to test it would have an answer that depended on which machine asked. So the
runtime half stays a **convention with a document**, and the honest summary is:
core can prove a repository *declares* its toolchain and that CI *reaches the
gate through that declaration*; it cannot prove the runner had the interpreter
installed. `mise exec --` is what closes that gap in practice.

Core's own half of the same problem is already a rule rather than a hope, and
for the same reason: `harness/bin/anywaye-contract` finds an interpreter or
**exits 2 with a sentence**, and the harness's resolver import is guarded so a
copy of one file without the other **refuses rather than checking less**. A
harness that cannot find Python is not a green harness.

### What exists today, and what each one costs

Measured across the fleet's tracked, non-markdown files — the migration surface
rather than the number of mentions, because the number that decides whether
something is a one-line change is the number of places a reader has to learn a
second way to find core:

| Service | Mechanism | Shape | What migrating costs |
| --- | --- | --- | --- |
| `billing` | `actions/checkout` | `ref: master` — **a branch** | 1 workflow line; the cheapest real case |
| `docs` | `CORE_REF` env + checkout | `CORE_REF: 'master'` — **a branch, spelled as a pin** | 1 workflow line |
| `muse` | `CORE_REF` env + checkout | `CORE_REF` is a hand-bumped **sha** | 1 workflow line; the sha is already honest, so this is a rename to `v0.2.0` |
| `gateway` | `curl` over HTTPS | `raw.githubusercontent.com/anywaye/core/master/<schema>` — **not a checkout at all** | the largest: one schema, no tree, and `kit` records that fetching at test time was a **deliberate choice** here |
| `pantry` | `vendir` + `vendir.lock.yml` | vendors 2 files, records a sha, re-copies by hand | 1 workflow step; the lockfile is already the record |
| `muse` | bespoke env var | `MUSE_CORE_SCHEMAS` — **9 files, 23 occurrences** | in `ci.yml`, `gate.yml`, `pyproject.toml`, 2 modules, 4 test files |
| `pantry` | bespoke env var | `PANTRY_ANYWAYE_ROOT` — **8 files, 25 occurrences** | in `ci.yml`, `bin/prime`, `registry/index.yml`, 5 test files |

That is **five services, four ref strategies, and two bespoke environment
variables** — and the two variables are the expensive half, because they are not
one line each. They are read in a service's own source, in its tests, in its
gate declaration, in its build config and in its CI, and a test file that reads
`os.environ["MUSE_CORE_SCHEMAS"]` is a test that cannot be read by somebody who
does not already know the variable exists. **That is the number this section
exists to move**: 48 read sites, and a directory with a committed lockfile
retires the reason for every one of them.

**The migration, in order of cost:**

1. **`billing` and `docs`** — one line each. They already check out a tree, so
   they only need `ref: master` → `ref: v0.2.0`. Do these first: they are the
   two services most obviously compiling against a moving target, and the diff
   is unreadable in the bad way.
2. **`muse`** — `CORE_REF` becomes `v0.2.0`. Its sha pin is *more* precise than a
   tag and there is a real argument for keeping it; the resolution is that a tag
   is the platform's unit and a sha is a service's private refinement, so
   `v0.2.0` in the workflow and the sha in a comment if the service needs one.
3. **`pantry`** — keep `vendir.lock.yml`; it is already the honest record of
   *which* core, and it is what `pantry::pin` reads. Point it at the tag and
   retire `PANTRY_ANYWAYE_ROOT` behind it.
4. **`gateway`** — the only real work, because it has no checkout to rename. And it
   is a **decision, not a migration**: `kit/core/README.md` records that `gateway`
   and `billing` fetch core at test time *on purpose* — `gateway`'s own comment
   says the schema is fetched rather than vendored "so this tracks what core
   publishes today instead of freezing a copy that silently goes stale." A tag
   gives `gateway` exactly what it asked for and cannot lose: a named point that
   is not today. Ask before changing it; do not change it because this document
   exists.
5. **The environment variables last**, once the directory exists, because they
   exist only to *find* core and the directory removes the need.

### What is not done yet, and is not this packet's to do

- **No service was migrated.** Not one service repository was edited. Adoption is
  per-service, and per-service owners.
- **`kit`'s three vendir configs still say `ref: master`.** Correcting them is
  kit's edit to make, not core's, and it is one line in each. This document does
  not depend on it: the mechanism is declared here and adopting it is the
  migration.
- **The fetch mechanism is not yet a rule.** `harness/rules.json` says `harness`
  or `doc` for every rule, and a rule that read a service's `vendir.yml` would be
  reading another repository. This document is the convention; the enforcement is
  per-service CI configuration, and the honest statement is that it is
  review-enforced until someone owns the fan-out.
- **The toolchain's runtime half is not enforced**, and is named in
  `harness/gate_findings.json`'s `notEnforced` rather than left to be discovered.

### A tag is the unit; a recorded commit sha is the interim

**Decided: a tag is the unit, and a recorded commit sha is an acceptable
interim — but a branch never is.** `v0.2.0` now exists, so the first term is not
hypothetical; the second is what a service adopts in the window before it does,
and the fleet already has one in `pantry/vendir.lock.yml`.

So read `ref: v0.2.0` above as "**a tag, or a recorded sha, but never a
branch**". The defect this section fixes is not the absence of a tag — there is
one now — it is `ref: master`, which compiles against whatever core happens to
be today and cannot be reasoned about afterwards. A recorded sha has neither
problem.

**To flip:** if the platform owner would rather core never carry tags, the
mechanism becomes a `vendir.lock.yml`-style recorded sha everywhere and the tag
rows above become sha rows. Nothing in `harness/core_version.py` changes — it
resolves a *version*, and the sha is only ever the way a service finds the
checkout carrying it. That separation is the reason a version is a **file** and
not a tag, and the two decisions answer the same question from two ends.

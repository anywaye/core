# The postgres image pin

**One postgres image, fleet-wide: `postgres:17-alpine`. Decided by the platform
owner on 2026-10-01 (DEBT.md D24), and enforced here.**

`compose.postgres-pin` is the rule that makes it stick. Its claim, in one
sentence: **every postgres image reference a repository makes resolves to the
tag core declares in `POSTGRES_TAG`.**

```
POSTGRES_TAG                 one line, one tag, at core's root. The declaration.
harness/cafaye_contract.py   the rule, under "the postgres image pin"
docs/postgres-pin.md         this file: what it decides, and where it stops
```

## The declaration is a file, not a sentence

`POSTGRES_TAG` holds exactly one line — `17-alpine` — and the harness **refuses**
anything else. That is the same discipline as `VERSION`, and it is deliberate: a
tag file that has been appended to is not a tag, and reading only the first line
would make it one again.

It is a file at the repository root rather than a key in `schemas/`, and the
trade is worth naming because it cuts against core's own rule that a convention
not in `schemas/` is not a cafaye rule:

- **In `schemas/`** would have been more in that spirit, and it would have
  changed `contract_digest` — a sha256 over everything under `schemas/`. Every
  service that has pinned a digest goes red on that byte, for a file no service
  consumes. That is a fleet-wide break bought for tidiness.
- **At the root** is where `VERSION` put the other published fact, and it is
  protected the same way: by core's own suite, which fails if the file is
  missing, is not one line, or is not a tag.

The cost, stated rather than glossed: `POSTGRES_TAG` is covered by a test and
**not** by `--expect-digest`. A service that vendors only `schemas/` — which is
what "vendoring core" usually means — has no `POSTGRES_TAG` to read, and the
rule **refuses** (exit 2, `compose.postgres-tag-absent`) rather than passing
silently. That is the same exit-2 rule as `core.version-absent`, and for the same
reason: a run that cannot find the standard has converted an unknown into a pass.

## What counts as a reference, and what does not

The rule reads **executable declarations** — places where a program will pull an
image — and nothing else. Three shapes, all of them the `image:` key or an image
argument to a container command:

| Source | What is read | Measured in the fleet |
| --- | --- | --- |
| A compose file, matched by name, within two directory levels of the root | every `image:` key | 7 files, 7 keys |
| `ci/*.yml` (one level — the workflows directory is one level deep) | every `image:` key, which under a job's `services:` is the only place a workflow pulls one | 5 workflows, 4 keys |
| The repository's own root shell scripts and `Makefile` | a `docker run` / `docker create` / `docker compose run` line naming a postgres image with an explicit tag | 0 |

`image:` is the anchor rather than a fixed path, because it is what makes the
line a declaration: `services.db/image` in a compose file,
`jobs/gate/services/postgres/image` in a workflow and a compose file heredoc'd
into a script are three spellings of one thing. A sibling image is not this
rule's business — `redis:7.4.1-alpine`, `nats:…`, `grafana/grafana:11.3.0` and a
service's own `cafaye/muse:dev` are all in these files, and the repository name
is what excludes them.

### Prose is not a source, and that is a decision

A `grep -r 'postgres:'` over the fleet's history finds `postgres:17` in six
CHANGELOGs, `postgres:18-alpine` in muse's, and `postgres:16-alpine` in two of
the docs repository's runbooks. **Every one of them is correct** — they are
statements about what was true when they were written, and courier's
`REPORT-courier-13-pgimage` says so in a table.

A rule that read prose would turn six changelogs red for being accurate, and the
fix a service owner reaches for is deleting the record, which is strictly worse
than the drift it was meant to catch. It is also the mistake this harness has
already written down once: `OFFSET_PARAMETER_NAMES` is a named list and not a
pattern, because "a harness that bars every parameter containing `page` also bars
a customer's own `/v1/pages` filter".

A false accusation here costs more than a missed reference, and the misses are
the ones a *declaration* shape can find. It is in
[`rules.json`](../harness/rules.json)'s `notEnforced` under
"Prose that names a postgres image is checked".

## The four references the rule cannot compare

Each one is a finding rather than a pass, because the failure direction that
matters here is a check that quietly decides nothing.

- **A digest** — `postgres@sha256:…`. A *stronger* pin than a tag, and the rule
  has no business calling it weaker. But it has no tag to compare, and passing it
  would be a rule reporting that it decided something it did not.
  `identity`'s CI explains why the digest is not available there: the digest that
  resolves on an arm64 workstation is not the one that resolves on a
  linux/amd64 runner.
- **A variable with no default** — `postgres:${TAG}`. The tag is whatever the
  environment says. Undecidable from the file, so it is reported, not guessed.
- **No tag at all** — `postgres`, which resolves to `postgres:latest`. The one
  value a tag can hold that is guaranteed to change. `postgres:17`, a bare
  major, floats across minors and is reported by the same branch.
- **`latest`** — and note that core cannot declare it: `read_postgres_tag`
  **refuses** a `POSTGRES_TAG` of `latest`, so the standard cannot be set to the
  one value that would make the rule pass exactly the references it exists to
  fail.

## Exceptions: declared, never inferred

A service that legitimately needs another postgres major writes
**`postgres-pin-exceptions.yaml`** at its root:

```yaml
exceptions:
  - file: ci/ci.yml
    image: postgres:16-alpine
    reason: >
      One legacy reporting replica, retired with the 2026-Q4 data-store
      migration. It is the only container on the runner.
    owner: platform
    # QUOTED, and that is not a style choice. YAML's core schema resolves an
    # unquoted `2026-12-31` to a **date**, not to a string — so an unquoted
    # horizon is read as a date by PyYAML and as text by the harness, and the
    # field whose entire job is to be read by a human becomes two types
    # depending on who parsed it. This was found by
    # `test_the_harness_yaml_reader_reads_every_document_in_this_repository`,
    # which walks every YAML file core owns and demands the harness and PyYAML
    # agree: the fixture first carried an unquoted horizon and the two readers
    # disagreed on its *type*. The rule requires a string, so it would have
    # reported the unquoted form correctly; quoting it here is what makes the
    # example, the fixture and PyYAML agree.
    until: "2026-12-31"
```

The rule matches on the **exact path and the exact reference**. No wildcard, no
prefix, no "anything with postgres in it" — a blanket exemption is the thing a
rule exists to prevent, and a wildcard is a blanket exemption with a comment on
it.

Four ways an entry can be wrong, and all four are findings:

1. **It must carry `reason`, `owner` and `until`.** A bare entry is a
   suppression nobody can review.
2. **An exception for the declared tag is not an exception.** It grants nothing
   today and hides the *next* change to `POSTGRES_TAG` behind a line that looks
   reviewed. Delete it; if the pin it names is wrong, fix the pin.
3. **An entry that matches nothing on disk is a finding.** A stale exception is
   an escape hatch nobody re-reads, and deleting the pin must delete the
   permission. This is the rule kit enforces on its skip allowlist and identity
   on its coverage exclusions — "an entry matching nothing is a failure",
   modelled on ESLint's `reportUnusedDisableDirectives`.
4. **An entry aimed at something this rule does not decide is a finding.** A
   `file` that is not a path, or an `image` that is not a postgres image, is a
   line that reads like permission and grants none.

**And a fifth property, which is not a fifth finding: an entry that fails any of
the four does not GRANT.** It is reported *and* inert. A `postgres:16-alpine`
whose entry has no `owner` keeps the finding it was written to silence, and the
finding you are shown names the field that is missing. Reporting an entry and
honouring it at the same time would be a line that both looks reviewed and does
nothing, which is strictly worse than a line that looks unreviewed and does
nothing — so the harness splits the two questions (`_exception_is_reviewable`)
rather than answering both with one check.

**`until` is required and is never compared against a date.** The harness has one
answer for every input or it does not have a rule: it never resolves a `$ref`
over the network because a check that needs the network gets a different answer
on a different day. An exception list that expires by itself is that failure
wearing a calendar. A horizon is a promise to a reader, and the reader is a
human — which is also the cheaper thing to review.

**Nothing in the fleet declares an exception today.** The file is not required:
a service that needs none writes none, and a rule demanding an empty declaration
file would be a file every repository carries for no other reason.

## The adoption ceiling, measured — and it is not zero

D24 recorded the standard as uniform on 2026-10-01. It is not, and the two places
it is not are the rule working on the day it lands rather than a reason to soften
it.

| Repository | Declaration | Tag | |
| --- | --- | --- | --- |
| billing | `docker-compose.yml`, `ci.yml` `services:` | `postgres:17-alpine` | ✅ |
| courier | `docker-compose.yml`, `ci.yml` `services:` | `postgres:17-alpine` | ✅ |
| darkroom | `docker-compose.yml`, `ci.yml` `services:` | `postgres:17-alpine` | ✅ |
| muse | `docker-compose.yml` | `postgres:17-alpine` | ✅ |
| identity | `docker-compose.yml` | `postgres:17-alpine` | ✅ |
| identity | `ci.yml` `services:` | `postgres:17-alpine` | ✅ |
| parlor | `e2e/docker-compose.yml` | `postgres:17-alpine` | ✅ |
| kit | `templates/compose/docker-compose.yml` | `postgres:${KIT_POSTGRES_TAG:-17-alpine}` | ✅ |
| kit | `templates/deploy/compose.deploy.yml` | **`${KIT_DEPLOY_IMAGE:?...}`** | ❌ |

**Every postgres image reference in the fleet resolves to the declared tag but
one, and that one is not a postgres image.**

This used to be two real failures and both are now fixed, so it is worth saying
what each one cost, because the cost was not visible in the line that carried it:

- **kit's dev compose defaulted to 16.6.** `bin/dev` with nothing configured gave
  a developer postgres 16.6 while every CI runner in the fleet had 17. Now
  `17-alpine`.
- **identity's CI pinned `17.11-alpine` while its own compose floated at
  `17-alpine`.** This one was deliberate — pinned to the exact minor the numbers
  in its comments had been measured on — and that is exactly what made it worth
  recording. Pinning a minor is only a stronger guarantee if nothing else needs
  to agree with it. Here everything did: a machine running both the dev stack and
  anything CI-shaped stored **two postgres builds**, and a developer and a runner
  could sit on different ones. A digest is stronger still and cannot be used,
  because the digest that resolves on an arm64 workstation is not the one that
  resolves on a linux/amd64 runner — it would pin CI to a build no developer can
  run. `17-alpine` is the finest pin that still means "the fleet's image"
  everywhere, and it is what makes **one pull serve both**.

- **kit's deploy template names an image the rule cannot resolve.**
  `services.app.image` is `${KIT_DEPLOY_IMAGE:?...}`, a variable the deploy tool
  sets at run time. It is recorded rather than suppressed because suppressing it
  would teach the rule to skip variables, and `${KIT_POSTGRES_TAG:-default}` is
  exactly the form this rule exists to resolve — the default is what a developer
  with nothing configured gets. The cost of not distinguishing "a pin I should
  resolve" from "a value I should ignore" is this one honest row.

**Nothing turns red today**, and that is a fact about adoption rather than about
the rule: the harness deliberately migrates no service, so no service runs this
yet. When a service adopts it, this is what it finds. That is the desired shape
for a rule that lands after adoption — but it also means the ceiling is "all but
one reference", not "the fleet is uniform", and the honest report says so rather
than the comfortable one.

**A severity chosen to make today's tree green is a warning wearing a rule's
clothes.** The rule is a hard failure. The two entries above are findings for
their own repositories, and the cheapest path for either is a declared exception
with a reason, an owner and a horizon — not a softer rule.

## What the rule cannot see

Named here rather than left to look like a pass; each is in
[`rules.json`](../harness/rules.json)'s `notEnforced`:

- **Prose.** Above, with the measurement.
- **A third-party postgres.** `pgvector/pgvector:pg17`, `postgres-backup` and a
  private mirror are different images with different maintainers. The rule
  decides the `postgres` image; `docker.io/library/postgres` and
  `ghcr.io/anyone/postgres` are recognised as it, because they are it.
- **A compose file deeper than two levels.** The bound is what stops the walk
  entering `node_modules` and calling a vendored package's README this
  repository's pin — `courier` vendors hex packages into `deps/`, one of which
  documents postgres. The bound is **not** silent: every compose-shaped file
  below it is named in a `WARN compose.pin-scan-truncated`, so a repository that
  hides its stack three levels down gets a green that says what was not read.
- **An `extends:`-ed or `include:`-d compose file.** The `image:` key is read
  wherever it is in a file the harness parsed; a service that reaches its image
  through a reference to another file is a file the harness was not pointed at,
  and pointing it is a one-line change.
- **A pin assembled at run time.** A script that builds `postgres:$TAG` from an
  environment variable has made an undecidable declaration, and the rule reports
  the composition rather than the result.

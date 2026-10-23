# Manifest conventions

`anywaye.yml` is the one file every anywaye repository carries. Its schema is
[`schemas/anywaye.manifest.schema.json`](../schemas/anywaye.manifest.schema.json);
this document explains the parts a schema cannot.

## Shape

```yaml
name: billing                      # required — the anywaye namespace name
description: …                     # one sentence, shown by `cafe new` and pantry
language: ruby                     # required — go|ruby|elixir|python|typescript|rust|spec
core: ^0.2.0                       # required — the core spec range this service compiles against

exposes:                           # omit entirely for libraries and spec-only repos
  api: openapi/openapi.yaml        # repo-relative path to an OpenAPI 3.1 document
  events: [billing.subscription.started]   # event types this service publishes

consumes: [identity.user.created]  # event types this service subscribes to
dependencies:                      # other anywaye services, not packages
  - name: identity
    version: ^0.1.0                # the dependency's own contract version, not core's
    required: true                 # false = soft dependency, runs degraded without it

repository:
  url: git@github.com:anywaye/billing.git   # SSH only (PLAN.md §1)
  defaultBranch: master
  visibility: public

owner:
  team: billing
  contact: billing@anywaye.com
```

Event types are always `<service>.<entity>.<action>`, published and consumed
alike — see [event-naming.md](event-naming.md#grammar). `consumes` always names
a *different* service, and the `core` constraint is the spec range; a
`dependencies` entry's `version` is that service's own contract version.

## Namespace rules

A service `name` is lowercase kebab-case (`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, 2–40
characters). It is simultaneously the repository name, the Go module path
segment, the event envelope `source`, and the gateway routing prefix. Changing one
means changing all of them, which is why the rules are this strict.

Reserved, never usable as a service name: `anywaye`, `cafe`, `kit`, `core`,
`docs`, `pantry`.

The schema does **not** enforce the reserved list. `core` is the single
legitimate exception — this repository's own `anywaye.yml` is `name: core` — so
encoding the list as a `not`/`enum` in the schema would make core's manifest
fail the schema core publishes. Until core v1, the list is a review rule, and
`tests/test_specs.py` is the place to add it if the manager wants it
mechanically enforced.

## Semver constraints

The constraint grammar is deliberately tiny:

| Form | Meaning |
| --- | --- |
| `^1.2.3` | `>=1.2.3 <2.0.0` — the default. |
| `~1.2.3` | `>=1.2.3 <1.3.0` — pin the minor. |
| `>=1.2.3` | open-ended floor. |
| `1.2.3` | exactly. |

It stays tiny. Full npm-style semver — `||`, `x`-ranges, hyphen ranges,
prerelease comparators — is out of scope, for two reasons. The first is
arithmetic nobody needs: every range anywaye ships is a caret, and the one place
that actually resolves these strings will be a future `cafe contract`, which
needs one resolver rather than a dependency on someone else's grammar. The
second is a trap npm's own semantics contain: `>=1.0.0` against a `0.x` service
is not a range, it is a lie — `0.1.0` and `0.9.0` are both "before 1.0.0", and
only the pre-1.0 rule `^0.1.0` is `>=0.1.0 <0.2.0` says what a service author
means when they write it. A grammar with fewer surprises is worth more here than
a grammar with more features.

So: this is the whole grammar, enforced by the `semverRange` pattern in the
schema, and resolution is `cafe contract`'s job. If `cafe contract` ever needs a
form this table does not have, the fix is a manager decision and a schema
pattern change — not an ad-hoc parser in a service.

## Rules the schema cannot state

JSON Schema cannot compare two properties of the same instance, so these live in
`tests/test_specs.py` and in review:

1. **A published event type starts with the publisher's own name.** Every type
   is `<service>.<entity>.<action>` with no exceptions, so this is not a special
   case for generic entities any more: `identity.api_key.created` is legal in
   `identity` and is a bug anywhere else. A consumed type names a *different*
   service by the same rule.
2. **A service never consumes its own events.** If it needs to react to its own
   output, it should call itself in-process instead of paying for a bus.
3. **Any service that serves or receives traffic declares `exposes`.** A
   repository with no `exposes` is a library or a spec repo. `cafe dev` and
   `pantry` read this to decide what to run and what to route.
4. **`dependencies` are services, not packages.** A Ruby gem or an npm module
   belongs in the language's own lockfile, not here.
5. **`owner.team` is accountable, not an author.** Renaming a team is a
   changelog-worthy governance event.
6. **Every consumed type exists in the core catalog.** A subscription to a type
   no publisher declares is a typo that otherwise ships silently and fails at
   runtime, on someone else's deploy.

## Adding a field

A new top-level key is a **minor** bump of core and requires, in the same
commit: the schema, an example under `examples/valid/`, at least one
`examples/invalid/` case if it is constraining, and a test. Making an optional
field required, tightening a pattern, or adding an enum value that invalidates
an existing manifest is a **major** bump. `core` is pre-1.0, so `0.x` majors are
allowed; state the intent in the PR.

## Why a manifest at all

`cafe init`, `cafe new`, `cafe dev`, `cafe gen` (SDKs), `pantry` (registry) and
`gateway` (routing) all need the same six facts about a service. Six tools
answering six questions by reading six bespoke config files is how cross-repo
drift starts. One file, one schema, one validator.

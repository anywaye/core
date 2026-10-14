# HANDOFF — core-breaking-tiers-01

**Branch** `worker/core-breaking-tiers-01` · **base** `d49e14c` · green, not
pushed.

## Read this first, it decides your first move

Two facts change what the obvious next step is:

1. **The packet's premise was half wrong and the finding is the deliverable.**
   There is no `breaking: true|false` anywhere in core — 0 keys in `schemas/`, 0
   in any yml, and the one bit is the presence of a `### Breaking` heading in
   `CHANGELOG.md` (2 of 3 releases). So **there is nothing to migrate**, and the
   migration question the packet asks has no subject. See D43.
2. **`cafe` already had all three tiers** before this packet ran:
   `cafe/internal/contract/breaking.go` (ten classified change kinds, each with a
   `Tiers` set) and `--tiers source,json,wire`. So the consumer-side selection
   works. What was missing was that **core published nothing** — and core is what
   a service pins.

So this packet did not invent the tiers. It **made the substrate own them**, and
**pinned core's table to the Go one** so the two cannot drift.

## Your first move

Pick one. Both are honest; they are different packets.

### A. The producer side — a declaration says which surfaces it cares about

The one thing §3 of the packet asked for that is **not** done, and the reason is
recorded in D43 rather than worked around.

1. Add an **optional** `breakingTiers` to
   `schemas/cafaye.manifest.schema.json`: `type: array`,
   `items: {enum: [SOURCE, JSON, WIRE]}`, `uniqueItems: true`,
   `additionalProperties: false` at every level like every other file there.
2. **Absent means the published `defaultTiers`, `["SOURCE","JSON"]`.** Do not
   make it required: `additionalProperties: false` means making it required edits
   all nine services, and making it optional-but-meaningless is how a field dies.
3. A test that the absent spelling and an explicit `["SOURCE","JSON"]` are **the
   same selection**. That is the whole migration story and it is one assertion.
4. Same commit, per AGENTS.md: a positive example under `examples/valid/`, a
   negative case plus a README row under `examples/invalid/`, a test, and the
   `gate.yml` floor raised to the measured number.
5. Then `cafe` reads it and passes it as the default for `--tiers`. That is a
   **cafe** change, a different repository, a different branch.

### B. Close the pin's CI hole — the honest gap in what landed

`test_the_published_table_is_the_go_table_and_they_cannot_drift` resolves `cafe`
as a sibling of this worktree's parent and **prints a skip line and returns** if
it is absent. That is deliberate (the packet forbids nesting the worktree, and a
test that fails for a missing sibling checkout fails for a reason unrelated to
the table) but it means **core's suite is weaker in CI than on this machine**
unless CI checks the fleet out beside core. `lint drift` probably already needs
it there — **confirm that before you merge this branch.** If it does not,
decide: make it hard, vendor the table into core with a refresh procedure, or
accept the skip and write down what it costs.

## The two things to be careful about

* **Do not loosen `test_the_three_tiers_are…` or the separability test to make a
  future row fit.** The separability assertion and
  `breaking.tiers-indistinguishable` are the only things stopping this from
  becoming three names for one thing. If a new change kind cannot be given a
  tier set that differs from an existing one, that is a finding about the tier
  model, not a test to relax.
* **The pin reads Go source with regexes.** It found a real bug in itself twice
  while being written (it read `DefaultTiers` out of a docstring). If you touch
  `breaking.go`'s formatting, the pin may need re-anchoring — **fix the pin, do
  not skip it**, and the reason belongs in a comment beside the search.

## Commit map

| commit | what |
|---|---|
| `5faaa12` | the measurement, and the finding that the boolean does not exist |
| `f384d99` | the table as data, the reader, nine tests, the pin, floor 254 → 263 |
| (this one) | the decisions and these two documents |

## Unreviewed on purpose

`response-no-delete` is the one row with **no buf analogue**. It is argued, not
copied, on the evidence of identity dropping a 409 from
`POST /v1/email-verifications` in 1.6.0. A row argued rather than copied is the
row a reviewer should look at hardest, and it is the row most likely to be wrong.
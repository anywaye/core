# REPORT — core-audio-01

**A decision record, not a decision.** One file added, `DECISIONS-audio-01.md`,
carrying the two questions the audio plane has to have answered before any
service builds it, with every candidate priced against a cited line and a
recommendation the user can overrule in one line. **Nothing in the repository's
contract changed** — no schema, no document, no example, no test, no `fleet.yml`.

---

## 1. What was written

`DECISIONS-audio-01.md`, a packet-scoped record following the precedent of
`DECISIONS-breaking-tiers-01.md` and `DECISIONS-reserved-tombstone-01.md`, both
of which left `DECISIONS.md` alone because the numbering there is the manager's.

Two structural decisions inside the file, both deliberate:

**It takes no `Dnn`.** The two predecessors numbered themselves D43–D45 and
D44–D47, and **every one of those numbers is already taken** in `DECISIONS.md`
(D43–D46). Reusing the sequence would put two decisions under one citation, which
is what `test_open_decisions_are_numbered_and_complete`
(`tests/test_specs.py:5352-5385`) exists to prevent. A number is claimed when the
ruling lands, in the same commit as the schema change it authorises.

**It claims to enforce nothing.** A question nobody has answered cannot be a
rule. Editing `docs/openapi-conventions.md` or `docs/event-naming.md` now would
make the proposal invisible to the reader who comes back to check whether the
question is still open — the packet's own instruction, and the reason both docs
are untouched.

## 2. Q1 — the scope vocabulary

**What was measured before writing, not assumed.** The packet's premise says the
vocabulary is "explicitly core's to extend". **It is not, and saying so is the
first thing the record does.** Core owns the *grammar* — `resource:action`, lower
case, `docs/openapi-conventions.md:137` — and every service names *its own
surface*:

| service | scope | read from |
|---|---|---|
| muse | `completions:write` | `src/muse/auth.py:88`, one constant, docstring at `:81-88` calls the name "provisional" |
| darkroom | `assets:read` / `assets:write` | `internal/auth/middleware.go:148-159`, off its own `openapi/v1.yaml:105` |
| identity | seven, `accounts:*` … `sessions:write` | `internal/apikeys/apikeys.go:199-282`, off its own routes |

identity's own block says the same thing at `apikeys.go:143-146`: *"THE SHAPE IS
core's … The names are this service's own surface, read off `openapi/v1.yaml`
rather than invented."*

**The part core does own is load-bearing downstream**, and this is what makes the
question core's rather than muse's: a granted scope travels on the wire inside a
closed `enum` — `schemas/events/identity/api_key/created.schema.json:35-42` —
with a negative case and a stated reason at
`examples/invalid/README.md:184`. Adding an audio name is a **core release to a
published payload schema**, not a line in a Go const.

Three candidates, each priced:

- **A. `audio:write`** — self-explanatory to a human reading a grant, but the first
  case in this fleet where the resource names something **no route is named
  after**, so a client cannot derive the required scope from the endpoint it is
  calling. Cost of being wrong: a *major* release to remove an enum member.
- **B. surface-shaped, two names: `speech:write` and `transcriptions:write`**
  — the recommendation. Keeps the invariant true that a route's required scope is
  derivable from the route.
- **C. a modality list: `speech:*`, `transcriptions:*`, `embeddings:*`** — scales,
  and identity already keeps such a list for OIDC (`internal/oidc/scopes.go:35-51`).
  But it is a decision about six capabilities made in a packet about two.

**The finding that decides it**, and it is a test rather than an opinion:
`identity/internal/apikeys/apikeys_test.go:240-251` **fails** any scope in the
vocabulary that has no route behind it — "a comment with a type". A modality
resource has no route.

## 3. Q2 — usage metering

`schemas/events/muse/tokens/consumed.schema.json:7-8` is `additionalProperties:
false`, `required` at exactly five fields, and its own `description` at `:5` says
why: *"a field added now is one a future schema carries forever."*

Three candidates:

- **A. a new event type per modality** — the recommendation. The repo's own
  evolution table says it: a publisher wanting a breaking payload change ships a
  new `type` (`docs/event-naming.md:126-128`). `muse.tokens.consumed` is never
  widened.
- **B. optional per-modality fields on the existing type** — rejected, and the
  reason is recorded: `tokens_in: 0` on a billed transcription is
  [`D35`](DECISIONS.md)'s defect in a new place.
- **C. a generalised `quantity` + `unit` payload** — not unprecedented
  ([`D11`](DECISIONS.md) did the `oneOf` version), and explicitly **not rejected
  forever**.

**The reason that decides it, and it is measured:** `grep -rn "muse\|consumed"`
over billing's `app/` and `lib/` returns **0 lines** at billing's `master` HEAD
`0f936a4`. (fleet.yml records billing's `sourceCommit` as `72519931`, so billing
has moved on since core transcribed it; the grep is this packet's, at HEAD.) The
downstream consumer does not exist, so "what a consumer must do about it" is
currently a choice about a first implementation rather than a migration — which
makes A the cheapest *and* the one whose being-wrong costs no schema release at
all.

**A third ruling surfaced that the packet did not ask for.** `muse.tokens.consumed`
publishes `subject: platform` with no `account_id` ([`D9`](DECISIONS.md)), and
muse has known the account since muse-06 but cannot write it — `core` owns the
schema (`muse/src/muse/metering.py:20-33`). **Any new audio usage type inherits
this.** Carrying `account_id` while the type does not yet exist is free; adding
it to a shipped type later is a patch release every consumer re-vendors. The
record recommends carrying it and lists it as ruling #4 rather than folding it
into the recommendation, because it changes a shipped type rather than adding
one.

## 4. Sibling repositories, read and not modified

Read at these commits, cited by file and line, nothing written:

| repository | commit | what was read |
|---|---|---|
| identity | `c228393` | `internal/apikeys/apikeys.go:135-290`, `apikeys_test.go:238-284`, `internal/oidc/scopes.go`, `internal/httpapi/accounts.go:141-211` |
| muse | `51145ba` | `src/muse/auth.py:1-120`, `src/muse/metering.py:1-160`, `src/muse/providers/__init__.py:150-215` |
| darkroom | `master` HEAD `2a43344` | `internal/auth/middleware.go:108-159`, `openapi/v1.yaml:105,569` |
| billing | `master` HEAD `0f936a4` | `grep -rn "muse\|consumed" app/ lib/` → 0 lines. See §3 |

**Every `file:line` in the record was checked against the line it names**, and six
were corrected where the first draft cited a range that overshot its own content
(`event-naming.md:116-123` → `:114-115`, `:125-129` → `:126-128`, `:36-50` →
`:66`, `observability.md:243-245` → `:243-244`, `consumed.schema.json:30-34` →
`:30-33`).

## 5. Verification — as run

`bin/prime`, exit **0**, on the merged tree:

```
==> the gate is declared, and the declaration is true about this tree
OK /private/tmp/wt-core-audio: 0 failure(s), 1 warning(s) — warnings do not move the exit code
==> every tombstoned property name is still reserved, and every reservation resolves
OK /private/tmp/wt-core-audio: 0 failure(s) — every tombstoned name is still reserved
299/299 passed
==> the red proof passed: 18 breakages went red naming their finding, 7 warning cases
  stayed green, 12 real-workflow spellings accepted, 4 extractor assertions,
  3 colour-greens, 2 colour reds, the control green, and 0 skipped.
==> the contract's numeric surface is safe across six languages
numeric_check — 0 failure(s), 4 warning(s), over 34 numeric position(s) in 1 document(s).
PASS: reserved_self_test — 6 breakages went red naming their finding, 2 controls, 12 assertion(s) passed
==> no test in this suite can delete another test's fixtures
==> db_isolation red proof: 3 breakages went red naming their finding
==> the account-scope red proof passed: 67 cases and 0 failed
```

`299/299 passed` is unchanged from `master`, which is the correct answer for a
packet that adds no test. **`gate.yml`'s `proof[].minimum` ratchet was therefore
not raised** — it is a floor on the suite's size and this packet adds none. It was
checked rather than assumed: the run went green at 299 without a red ratchet,
whereas `REPORT-core-breaking-tiers-01.md` records the ratchet going red at 254
on a packet that added nine.

The one warning and the four numeric warnings are **pre-existing and unrelated** —
they are on `master` before this branch and are not attributed to this packet.

**No `HANDOFF-core-audio-01.md` is written**, because nothing here remains: the
record is the deliverable, the four rulings are the user's by design, and a
handoff whose body would be "wait for a ruling" is a file that outlives the reason
for it. If the rulings arrive as a later packet, the schema change each one
authorises is the spillover and it is already scoped by the record.

## 6. Deliberately not done

- **No schema touched.** The packet forbade it and the argument against is
  structural: a payload schema edited before the ruling would make the proposal
  unreadable.
- **`docs/openapi-conventions.md` and `docs/event-naming.md` untouched**, for the
  reason in §1.
- **`fleet.yml` untouched.** No service is added or changed. **Whether audio is
  muse's surface or a new service is left explicitly undecided** and is named as
  ruling #2, because the answer to Q1 *is* the resource name and it does not
  survive a change of service.
- **No `Dnn` claimed**, and `DECISIONS.md` not edited — see §1.
- **No sub-agent or subprocess** was spawned, and nothing outside this worktree
  was written.
- **No scope string was invented.** Every candidate in the record is either quoted
  from a sibling repository's own code or is a proposal *about* a name, and the
  record says which is which.

## 7. The four rulings, reduced

1. **Q1 — is a scope's resource half a surface name or a modality name?**
   Recommended: **surface** (`speech:write`, `transcriptions:write` on muse's own
   surface). Evidence: three of three implementations name a surface, and identity's
   own test fails a scope with no route behind it.
2. **Q1b — is audio muse's surface, or a new service?** Recommended: decide this
   **first**, because the surface name is the resource name. `fleet.yml`'s
   question, not this packet's.
3. **Q2 — a new event type, per-modality fields, or a generalised payload?**
   Recommended: **a new event type**, because the evolution table already rules
   that way and because billing consumes nothing today.
4. **Q3 — the action word (`recorded` reused, or the v0 vocabulary extended), and
   does the new type carry `account_id` while it is free to?** Recommended:
   carry it. Free now, a re-vendored patch later.
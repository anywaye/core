# core-09 — the gate is declared, and the declaration is checkable

**Branch** `worker/core-09` · **base** `39acaed` (core-08) · **gate**
`bin/prime` — **163/163 passed, 0 skipped, 0 failed, no test removed, no
assertion loosened, no sleep, no retry bump** · **the red proof**
`harness/tests/gate_self_test.sh` — **23 breakages, 23 red, 0 missed; 5 warning
cases, 5 exited 0; 1 control, green** · **the harness's own red proof, unchanged**
— 28 breakages, 28 red.

**Nothing was skipped, and nothing is skipped on the way to a green.** The gate
runs one tier, there is no environment-gated tier in this repository, and the
one thing in this packet that is *conditional* — `gate.requirement-unproven`,
an external requirement the checker reports but does not run — is a **warning
that never moves the exit code**, printed and counted separately, and it is the
only "unproven" anywhere in the work below. core's own `gate.yml` carries one
such warning on every run: it needs `mise` on `PATH`, and the checker says so
rather than guessing whether it is there.

## The problem, and what was measured about it

Fifteen repositories, five spellings of "run the gate", and two greens that were
false. Re-measured on the primary branch of each on 2026-09-30 rather than
recalled; the full table is at the bottom.

```
mise run prime    billing cafe cafaye-rb courier darkroom docs identity pantry parlor   (9)
mise x -- ./bin/prime    guard muse      — a bin/prime and NO [tasks] section at all     (2)
mise run test     core                   — a task named test, not prime                 (1)
bash tests/validate.sh  kit               — no mise.toml and no bin/ at all               (1)
mise run gate     cafaye-py              — run = "./bin/gate", a file that does not exist (1)
```

The last one is new, and it is the sharpest version of the defect: `cafaye-py`
has a real `bin/prime`, CI runs `./bin/prime`, and its mise task points at
`./bin/gate`, which is not in the tree. A manager who trusts the task runs a
command that cannot exist, and gets a shell error rather than a gate — which is
at least loud. The two **false** greens were worse:

- `… | tail -45; echo "PRIME EXIT=$?"` under **zsh**, which has no
  `PIPESTATUS`. `$?` was `tail`'s exit code, which is always 0. The log said
  `FAIL github.com/cafaye/identity/internal/users 604.552s`; the shell said
  `PRIME EXIT=0`; a person reading the log was the only mechanism that caught it.
- identity's `bin/prime` is `go mod download; go build ./...; go test ./...`. It
  does not migrate the database. CI runs `goose up` at `ci.yml:273` **before**
  the gate at `ci.yml:289` — so a manager (or CI) that creates a database and
  runs the gate gets 1254 tests green against a schema that was never loaded.

That is one mistake wearing three coats: **the gate is discovered by failure
instead of declared.** `wavecheck.sh` already records the same lesson for worker
liveness — *the roster is discovered, not maintained* — and its own comment says
three earlier versions of it were wrong. The fix there was to stop maintaining
the roster by hand. So:

```
schemas/gate.schema.json     the format
gate.yml                     core's own declaration
harness/gate_check.py        the checker
harness/bin/gate-check       the wrapper a service's CI calls
harness/gate_findings.json   every finding, with its fix, and what is NOT proved
harness/tests/gate_self_test.sh   the red proof
docs/gate.md                 the ruling, and the two alternatives that lost
```

## The format, and the three things that made it that shape

```yaml
version: 1
name: core
gate:
  command: [bin/prime]        # an argv. Never a shell string.
  miseTask: prime             # `mise run <task>` must resolve to `entrypoint`
  entrypoint: bin/prime       # a repository-relative path; exists, and executable
  timeoutSeconds: 900
  proof:
    - id: suite               # what "the gate ran" looks like in the gate's output
      match: '^([0-9]+)/[0-9]+ passed$'
      minimum: 163            # a decrease-detector, read from group 1
external:
  selfContained: false
  requirements:
    - kind: network           # database | service | toolchain | credential | network | filesystem
      name: PyPI, ONCE, on a cold checkout
      satisfy: { command: [tests/setup.sh], unmet: tests/.venv/bin/python does not exist }
ci:
  workflow: .github/workflows/ci.yml
  invokes: [bin/prime]
```

**An argv, never a shell string.** A command is a list of arguments, so its
first element is a file or a PATH name and nothing in it is a shell
metacharacter. The schema refuses `| & ; < > ( ) $ \` ' " * ? { } [ ] # ~` and a
newline in any argument; `= , : @ + %` and spaces stay, because a real argument
needs them (`postgres://u:p@localhost:5432/db` is an ordinary gate argument).
`examples/invalid/gate.shell-string.yml` is the exact command that produced this
fleet's false green, and the schema refuses it — the constraint is asserted as a
property over the whole refused set in both directions, not as one example.

**A proof, or the declaration is the false green written down.** `match` is a
Python regular expression applied with `re.MULTILINE` to the gate's combined
stdout and stderr. A run that exits 0 **without emitting every declared proof is
`gate.proof-missing`, and it is a failure.** `minimum` is read from the pattern's
single capture group and is a **decrease-detector**: `1/1 passed` and `3/3
passed` are the same claim without it. Two proofs is how two tiers stay
separately countable — a run in which only the unit-tier proof appeared is
`gate.proof-missing`, which is a different and more honest thing than "a green
with a smaller number in it".

**`external` is required, always.** Its absence *is* the identity defect, told
the other way round. `satisfy.command` is an argv you can paste, not a sentence.
When `satisfy.command[0]` contains a `/` the checker verifies the file is there,
because that is a claim about **this repository**. When it is a bare name it is a
claim about **this machine** and the checker deliberately does not settle it — it
prints `gate.requirement-unproven` and leaves the exit code alone.

## Why not mise tasks alone — measured, not recalled

The incumbent, and it works well as a **runner**. In this repository, after the
one change the packet permits:

```
$ mise tasks
prime  The gate: validate every example against the core schemas (bin/prime)
setup  Create tests/.venv and install the validator dependencies
test   Alias for `mise run prime`; kept so existing muscle memory and scripts still work
```

A mise task stays, and it stays the thing you run. What it cannot do is hold the
three things this packet needs:

1. **External requirements.** `[tasks.prime] run = "bin/prime"` has nowhere to
   say that `bin/prime` needs an interpreter and one fetch from PyPI on a cold
   checkout. identity's unmigrated database is exactly this hole, and the honest
   answer in `mise.toml` is a comment, which is not checkable.
2. **Whether a gate ran.** A task is a command. Nothing in mise can tell
   `bin/prime` apart from `true`.
3. **Agreement with CI.** A task and a workflow are two files in two languages
   describing one gate, and mise has no opinion about whether they still agree.

So a mise task is a **claim** and this format is the one thing in the repository
that can be **checked**.

## Why not a CI-only declaration — measured, and it is already drifting

kit already publishes `ci.reusable.yml` and a GitHub Actions job *is* a
machine-readable statement of how a repository is gated. Thirteen of the fifteen
have a workflow; the two that do not are `docs` and — as of an hour ago —
`cafaye-py`, which is one of the two whose gate nobody could find. That is the
argument for it.

Rejected for two reasons, the first structural:

1. **A workflow cannot be run.** `gh` is not on a developer's machine, a
   workflow is not a local command, and the question this format exists to answer
   — *what gates this repository* — has to be answerable with nothing installed.
2. **The local gate and the CI gate can drift, and it has already happened.**
   There is no relationship between a workflow and a local script for anything
   to assert, and a CI-only declaration cannot detect that CI stopped running
   the gate, because CI **is** the declaration — there is no second copy to
   disagree with. This is not hypothetical: **`darkroom`'s mise task runs
   `./bin/prime` and its CI runs `./bin/prime --db`** (`mise.toml` vs
   `ci.yml:164`). Those are two different gates in one repository, and neither
   file says so.

The two are complements. `ci.workflow` + `ci.invokes` is checked **against** the
workflow, so `darkroom`'s drift becomes a `gate.ci-disagrees` on adoption rather
than a fact nobody notices.

## Why not a second task runner

Because the fleet already has five spellings and this would be a sixth. **This is
not a task runner**, and that is a design boundary rather than a naming
preference: `gate.yml` declares, `mise` and `bin/prime` run, and the checker has
exactly one job — compare the declaration to the tree. The one time it runs
anything is when you ask it to prove a gate, which is a question about a gate
rather than a way to gate. If you find yourself wanting tier logic in it, you
have left this packet's scope, and `harness/gate_findings.json` says so under
`notEnforced`.

## The checker

`{ok, warn, fail}` — yamine's shape, as MD13 recorded it — and **`warn` never
moves the exit code**. All five warnings are the same kind of thing (*this
machine could not answer that*) and a checker that promoted them to failures
would be red on a laptop and green on CI, which is the same defect in a new
place. Every finding carries **the exact command that fixes it**, which is the
one thing from a 7,000-line file MD13 called the most valuable thing in it.

| | |
| --- | --- |
| findings | 22 — 17 `fail`, 5 `warn` |
| static phase | the declaration against the tree. Nothing is run. |
| `--prove` | also **runs** the gate and requires every declared proof |
| exit codes | 0 no failure · 1 at least one failure · 2 the check could not happen |
| dependencies | none. Standard library only, like the contract harness. |
| Python | **3.11** (`tomllib`), where the contract harness accepts 3.9 — see D31 |
| YAML | the harness's own reader. One dialect, not two. |

Two design properties worth stating because they are the packet's own failure
modes, closed structurally rather than by convention:

- **It never pipes.** `subprocess.run(argv, shell=False)` with no pipeline, so the
  exit code it reads is the gate's own. The zsh `PIPESTATUS` mistake is not
  possible for it. The caller who *does* pipe gets the bash spelling from
  `docs/gate.md`, and `test_the_gate_doc_states_the_rule_the_false_green_was_built_from`
  fails if that section ever loses `${PIPESTATUS[0]}`, `set -o pipefail` or the
  word `zsh` — the easiest line in a repository to lose to an edit six months
  from now, so it is a test.
- **It never prints the gate's environment, or the gate's output.** No
  off-the-shelf tool detects a secret leaked at runtime into a log or an error
  string — 0 of 268 Semgrep rules intersect CWE-532, gosec has no
  `ast.CallExpr` case, Bandit is `ast.Constant`-only. So a finding carries the
  command **as written** and never its expansion, and the gate's stdout goes to
  a log file whose path is reported. Reading it is the reader's decision, and a
  CI log is kept forever and read by people who were not there.

### Two phases, and why there are two

`bin/prime` runs the **static** half and must not run `--prove`: the checker
runs the gate, and the gate runs the checker, so a gate that verifies itself by
running itself terminates and the termination is all it proves. The proving half
is a **step of core's CI of its own**, and
`test_core_ci_runs_the_gate_checkers_proving_phase` fails if that step is deleted
or if `--prove` appears in `bin/prime`.

## The red proof

`harness/tests/gate_self_test.sh` copies **one** conforming fixture — a small
repository that declares its gate and tells the truth about all of it —
twenty-three times, breaks exactly one thing in each copy, and asserts the
checker goes red **and names the finding it expects**. A control on the unbroken
fixture runs first, because without it twenty-three reds prove nothing: a
checker that refused everything would satisfy every expectation. Nothing in the
committed tree is a deliberately broken repository; the breakages are diffs
applied by the script, so a reviewer reads what is being broken.

```
PASS gate_self_test: the control — a repository whose declaration is true — is green in both phases
PASS gate_self_test: breakage 1: a repository that declares no gate at all — caught by `gate.declaration-missing`
PASS gate_self_test: breakage 2: a gate command naming a file this repository does not have — caught by `gate.command-missing`
PASS gate_self_test: breakage 3: a gate entrypoint this repository does not have, while the command still does — caught by `gate.entrypoint-missing`
PASS gate_self_test: breakage 4: a gate nobody is allowed to execute — caught by `gate.entrypoint-not-executable`
PASS gate_self_test: breakage 5: a mise task that is not in the mise config — caught by `gate.task-missing`
PASS gate_self_test: breakage 6: a mise task that resolves to a different file than the declaration names — caught by `gate.task-unresolvable`
PASS gate_self_test: breakage 7: a mise task named in a repository that has no mise config — caught by `gate.task-config-missing`
PASS gate_self_test: breakage 8: a declaration that is entirely true about a gate that exited 0 without running anything — caught by `gate.proof-missing`
PASS gate_self_test: breakage 9: a gate that proves one test where the declaration promised forty — caught by `gate.floor`
PASS gate_self_test: breakage 10: a gate that ran the suite, printed its proof, and failed — caught by `gate.nonzero`
PASS gate_self_test: breakage 11: a CI workflow that never runs the gate — caught by `gate.ci-disagrees`
PASS gate_self_test: breakage 12: a proof whose pattern does not compile, which would otherwise read as "no proof required" — caught by `gate.schema`
PASS gate_self_test: breakage 13: a gate that says it is not self-contained and names no way to satisfy what it needs — caught by `gate.schema`
PASS gate_self_test: breakage 14: an external requirement satisfied by a file that is not in this repository — caught by `gate.requirement-path-missing`
PASS gate_self_test: breakage 15: a declaration using a YAML construct core's reader refuses — caught by `gate.declaration-unreadable`
PASS gate_self_test: warning 1: a gate command that is a bare name this machine does not have — said `gate.command-unknown` and still exited 0
PASS gate_self_test: warning 2: a mise task whose run string is a pipeline, so only a shell could say what it runs — said `gate.task-unreadable` and still exited 0
PASS gate_self_test: warning 3: a repository with mise tasks and a declaration that names none of them — said `gate.task-undeclared` and still exited 0
PASS gate_self_test: breakage 19: a declaration naming a CI workflow that is not in this repository — caught by `gate.ci-missing`
PASS gate_self_test: warning 4: a declaration that says nothing about CI — said `gate.ci-undeclared` and still exited 0
PASS gate_self_test: warning 5: an external requirement nobody ran, which is reported and never acted on — said `gate.requirement-unproven` and still exited 0
PASS gate_self_test: breakage 22: a gate that outlived the budget its own declaration gave it — caught by `gate.timeout`
PASS gate_self_test: breakage 23: a proof with a floor and no capture group to read the floor from — caught by `gate.proof-invalid`
PASS gate_self_test: the gate that leaked at runtime: the report stayed clean and the log held it

PASS: gate_self_test — all 23 breakages went red, all 5 warning cases stayed green, the control is green, and the report carried no secret.
```

The five `warning` lines interleave with the breakages because `expect_warn`
counts its own five; they consume no breakage number.

### The false green, reproduced deliberately and caught

Breakage 8 is the one the packet asked for and the one the other twenty-two are
not. Twelve of them prove the checker can compare two files. This one proves it
can tell **a gate ran** from **a command exited 0**.

The declaration is **entirely true**. `command: [bin/gate]` exists and is
executable; `miseTask: prime` is in `mise.toml` and its `run` resolves to
`bin/gate`; `ci.invokes: [bin/gate]` appears in a `run:` body of the workflow;
`external.selfContained` is honest; the schema is satisfied. And `bin/gate` is:

```bash
#!/usr/bin/env bash
# A well-formed gate that runs nothing and says nothing, and exits 0.
exit 0
```

```
$ harness/bin/gate-check --prove <the repository>

FAIL gate.proof-missing: proof 'suite' never appeared; the gate's output contains no line matching '^([0-9]+)/[0-9]+ passed$'
    fix: make the gate print the line gate.proof[].match names, or delete the proof if the gate genuinely never prints it

the gate's own output is in /tmp/gate-check.XXXX/gate.log and is not printed here
FAIL <the repository>: 1 failure(s), 0 warning(s) — no warnings, so nothing was left unproven silently
EXIT=1
```

Nothing in the declaration is wrong and the repository is ungated. The only
thing that catches it is asking the gate to say what it did. The same three red
proofs — the missing command, the missing task, and this one — are **also** in
`tests/test_specs.py`, so `bin/prime` itself goes red if any of them stops being
caught and not only when somebody remembers to run the script.

### The red proof can itself go red

A red proof that has only ever been green is a claim. Taken on a throwaway copy
of this worktree, with the single line that reports an absent proof disabled
(`if not matches:` → `if False:`), the self-test goes red and says which
breakage it lost:

```
FAIL gate_self_test: a declaration that is entirely true about a gate that exited 0 without running anything — went red as something else but never said gate.proof-missing
FAIL gate.proof-invalid: proof 'suite' sets a minimum but its capture group is not a number
    fix: fix gate.proof[].match as a Python regular expression, with exactly one capture group when `minimum` is set

FAIL: gate_self_test — 1 of 23 breakages and 5 warning cases the gate checker did not get right.
GATE_SELF_TEST EXIT=1
```

Note what it caught **instead**: the neutered checker went on to report a
different, also-true complaint about the same empty output. A red for the wrong
reason is still a red here, because `expect_red` asserts the *named* finding —
and that is exactly why a red proof has to name the finding rather than assert
"something went red".

### Two defects the red proof found in my own checker

Both were found by running the thing, not by reading it, and both are the reason
the self-test exists.

1. **`gate.task-unresolvable` never fired.** `check_mise_task` compared the
   task's `run` head to the entrypoint only when the head did *not* start with
   `/` or `.` — which is true of `go test ./...` and false of `bin/something-else`,
   so a task that had drifted onto a different repo-relative file was reported as
   fine. The condition was inverted in intent: a head **containing** a `/` is the
   comparable case, and a head with no `/` is the PATH case. Breakage 5 caught it
   because breakage 4 (a task that is not in the config) had already gone red and
   masked nothing — but breakage 5 is the one that found it, and it is the only
   check in the list that can catch a mise task and a declaration quietly
   disagreeing about what the gate is.
2. **`gate.proof-invalid` was half dead, and a finding turned out to be entirely
   dead.** I expected an uncompilable pattern to surface as
   `gate.proof-invalid`; the checker refuses it earlier, at the schema layer,
   which is the *better* answer — a broken pattern fails without spending the
   gate's runtime. The live half of `gate.proof-invalid` is the floor with no
   capture group, and that is now breakage 23. And `gate.requirement-empty` was
   unreachable: `validate()` already refuses a requirement with no `satisfy`, so
   the finding was deleted from the inventory rather than left as a rule with no
   test. **A finding nothing exercises is a finding that will be wrong the first
   time somebody needs it** — that is `harness/rules.json`'s argument, and it
   applied to my own file.

## Core's own gate, declared, and the checker green on it

`gate.yml` is the worked example and `examples/valid/gate.self-contained.yml` and
`examples/valid/gate.external.yml` are the two shapes a repository copies. Four
negative cases with a row each in `examples/invalid/README.md` and an
`assert_keywords` pair each in `tests/test_specs.py`.

```
$ harness/bin/gate-check .
WARN gate.requirement-unproven: external requirement 'CPython that can create a venv, and mise to install the pinned 3.14' is satisfied by 'mise', a command on PATH; this checker did not run it and cannot say whether it is there
    fix: satisfy it with the declared command before gating; a requirement nobody ran is not a requirement met

OK core: 0 failure(s), 1 warning(s) — warnings do not move the exit code
EXIT=0

$ harness/bin/gate-check --prove .
OK core: 0 failure(s), 1 warning(s) — warnings do not move the exit code
EXIT=0
```

That warning is the packet's own doctrine applied to the checker rather than to
the gates: a requirement nobody ran is not a requirement met, and the honest
thing is to say so and keep the verdict.

### The one change outside the checker

`mise run test` → `mise run prime`, with `mise run test` kept as a **mise
`depends` alias** so the old spelling still works and there is still exactly one
command. Nine of the fifteen repositories already answer to `mise run prime`, so
a task named anything else is a task that gets discovered by getting it wrong,
and this is the one normalisation the packet permits. It is asserted, not
promised: `test_core_s_mise_task_is_the_fleet_s_spelling_and_test_is_an_alias`
fails if `test` ever grows a `run` of its own.

### The floor is a ratchet, and it is the only test count in core

`minimum: 163` is a decrease-detector — a suite that lost forty tests cannot
report itself as passing. But a floor nobody raises decays into a lie the other
way, so
`test_the_gate_floor_is_not_below_the_suite_core_claims_to_have` asserts the
floor is **not below** the number of tests the suite contains. Adding a test to
`tests/test_specs.py` therefore fails the gate until `gate.yml` is raised in the
same commit. It fired twice during this packet, at 152 and at 163, which is what
it is for.

## The conformance report — fifteen repositories, read-only

**Nothing outside `core` was changed.** No file in `kit`, `guard`, `muse`,
`cafaye-py`, `docs` or any other repository was written, and none was gated,
run, or installed into. The manager dispatches the fixes from this table; this
packet does not.

Read on 2026-09-30 at the commit named, from each repository's own checkout.

| Repository | commit | the gate a human must guess | `mise run prime`? | names its external requirements? | CI agrees? |
| --- | --- | --- | --- | --- | --- |
| `billing` | `bd6ac84` | `mise run prime` | **yes** | no — `db:prepare` is inside `bin/prime`; a reachable postgres is a requirement the gate does not satisfy and nothing records | yes, `./bin/prime` at `ci.yml:519`, plus four tier steps |
| `cafe` | `460acf3` | `mise run prime` | **yes** | no — and there is nothing to name: a Go toolchain and no service | yes, `./bin/prime` at `ci.yml:126` |
| `cafaye-py` | `bd1785d` | **`mise run gate` names `./bin/gate`, which does not exist.** `bin/prime` does, and CI runs it | **no** — the task is `gate`, and its `run` is a dangling path | no — uv + PyPI on a cold checkout | yes, and it runs `./bin/prime` (`ci.yml:63`) — **so CI and the mise task already disagree**, plus a separate `bin/live` env-gated tier at `:135` |
| `cafaye-rb` | `ae32b3d` | `mise run prime` | **yes** | no — `db:prepare` inside `bin/prime`; a reachable postgres is unrecorded | yes, `./bin/prime` at `ci.yml:60` |
| `core` | `39acaed` | `mise run test` (→ `bin/prime`) | **no** — renamed in this branch | no — CPython + one PyPI fetch; **this branch declares both** in `gate.yml` | yes, `bin/prime` at `ci.yml:180` |
| `courier` | `59247b6` | `mise run prime` | **yes** | no — `mix ecto.setup` is inside `bin/prime`; a reachable postgres is unrecorded | yes, `./bin/prime` at `ci.yml:195` |
| `darkroom` | `bcaa2fe` | `mise run prime` | **yes** | no — `TEST_DATABASE_URL` and a `--db` flag, neither recorded | **NO, and it already drifted:** CI runs `./bin/prime --db` (`ci.yml:164`) and the task runs `./bin/prime`. Two different gates, one repository |
| `docs` | `0d16731` | `mise run prime` | **yes** | no — node + npm and nothing else | **no `.github` at all** |
| `guard` | `fa84fb7` | `mise x -- ./bin/prime` | **no** — `mise.toml` has `[tools]` and `[env]` and **no `[tasks]`** | no — a live-Redis tier in a separate CI job (`ci.yml:95-133`), not in `bin/prime` | yes, `bin/prime` at `ci.yml:65` |
| `identity` | `e500262` | `mise run prime` | **yes** | no — and this is the expensive one: postgres **and `goose up`** are CI steps (`ci.yml:253-275`) that happen *before* the gate at `:289`. `TEST_DATABASE_URL` gates 1166 of 1254 tests. Nothing in the repository says so | yes, `./bin/prime` at `ci.yml:289` |
| `kit` | `d3f8898` | `bash tests/validate.sh` | **no** — no `mise.toml` and no `bin/` at all | no — seven language toolchains, one per job; `tests/validate.sh` is the only gate contract it defines (`ci.reusable.yml:148`) | yes, in the reusable workflow; and the requirement it enforces is the *existence* of `tests/validate.sh` |
| `muse` | `1f0797f` | `mise x -- ./bin/prime` | **no** — `[tools]` and `[env]`, **no `[tasks]`** | no — a `MUSE_CORE_SCHEMAS` env-gated tier; `bin/prime` is `uv sync --locked && ruff && pytest` | yes, `bin/prime -q -rs` at `ci.yml:166` |
| `pantry` | `63f0b83` | `mise run prime` | **yes** | no — and there is a **silent skip**: when `../cafe` is not a checkout, `bin/prime` prints `skipped:` and exits 0 without running the contract lint | yes, `./bin/prime` at `ci.yml:254` |
| `parlor` | `49c9cf3` | `mise run prime` | **yes** | no — postgres + goose for `./bin/e2e`, in a **separate workflow** (`e2e.yml`) | yes, `./bin/prime` at `ci.yml:81` |

**Column totals.** `mise run prime` is the gate in **9 of 15**. **0 of 15**
repositories name their external requirements in anything a machine can read —
not because the requirements are unknown (every row above names them, read out of
the scripts) but because **until this branch there was no format in which to
name them**, which is the whole point. **12 of 15** have a CI workflow that runs
their gate; `docs` has none and `cafaye-py` grew one during this packet. **Two**
already disagree with their own mise task (`darkroom`, `cafaye-py`) and neither
file says so.

**Ranked for dispatch, worst first.** `identity` (the requirement that has
already cost a 604-second run), `pantry` (a skip that exits 0), `darkroom`
(two gates), `cafaye-py` (a dangling `run` plus two CI jobs), `kit` (no mise, no
`bin/`), `guard` and `muse` (no `[tasks]` at all), then the four that need only a
`gate.yml` written against a format they already satisfy.

## Open decisions — three, all reported

- **[D30](DECISIONS.md#d30-the-gate-declaration-names-an-argv-and-the-checker-runs-it)** — a
  **proof** (what I built) or only a description of the gate. The alternatives
  are a machine-readable test report (stronger, and four of this fleet's
  languages have no such report) and a signed report (which answers a question
  nobody asked: the problem is not a forged report, it is a report *about a
  different run*). **Cost of flipping:** one property name and one regex per
  proof, and nothing in the schema, the checker or the twenty-three breakages.
- **[D31](DECISIONS.md#d31-the-gate-checker-is-stdlib-only-and-needs-python-311-where-the-contract-harness-needs-39)** — 3.11
  for the gate checker where the contract harness accepts 3.9, because
  `tomllib` is stdlib from 3.11 and the checker reads `mise.toml`. The
  alternative that is actually attractive is dropping the mise cross-check
  entirely, which costs one schema property, one code path and two breakages.
  **Cost of flipping:** that, or nothing — 3.11 is four years old and every
  language in this fleet has a newer interpreter.
- **[D32](DECISIONS.md#d32-whether-a-repository-with-no-ci-is-a-warning-or-a-failure)** — a
  repository with no CI is `gate.ci-undeclared`, a **warning**, not a failure.
  `docs` and (until an hour ago) `cafaye-py` are in that state, and failing
  them would make adoption require writing a workflow this packet was told not
  to write there. **Cost of flipping:** one enum value and one rename.

## What I could not verify

Everything below is a claim I did **not** check against real source or a real
run, and it is kept out of the confident part of this report on purpose.

- **mise's own guarantees.** I verified by running `mise tasks` and
  `mise run --dry-run test` in this repository that `[tasks.prime]` lists, that
  `[tasks.test] depends = ["prime"]` resolves to `bin/prime`, and that
  `mise tasks` prints the descriptions. I did **not** verify mise's behaviour for
  `[tasks.x] run` given as an **argv list** rather than a string, for a task that
  has both `run` and `depends`, for a task whose `depends` chain is two deep, or
  for `depends` on a task defined *after* it. The checker's own `depends`
  following is one level deep with a cycle guard, and the fixture does not test a
  chain — the claim in `gate_check.mise_task_run`'s docstring ("follows one chain
  of `depends`") is a description of the code, not a verified fact about mise.
- **GitHub Actions' metadata.** I read the workflows as text and asked one
  question of them — does any `run:` body mention the declared argv. I did
  **not** evaluate Actions: a step can branch on an event, be filtered by a path,
  or sit in a job that does not run on a given branch, and none of that is
  visible from the file. The claim that core's two new CI steps pass is a claim
  about YAML, not a green run — **I have not run core's CI.** I read the
  workflow's existing conventions and followed them, and
  `test_core_ci_runs_the_gate_checkers_proving_phase` asserts the steps are
  present, which is a check on the file and not on a build.
- **The other fourteen repositories' gates.** I read their `mise.toml`,
  `bin/prime`, and `.github/workflows/`. I did **not run any of them.** Every
  statement in the conformance table about what a gate *does* comes from reading
  its script; every statement about what it *needs* is my reading of the script
  plus its CI, and a gate that needs something neither file mentions would not
  show up in this table. Specifically unverified: whether `pantry`'s
  `../cafe is not a checkout` branch is hit in practice (it is a conditional, and
  I did not create the condition); whether `guard`'s and `muse`'s env-gated tiers
  skip or fail in their current state; and whether `kit`'s `ci.yml` — as opposed
  to its reusable workflow — invokes `tests/validate.sh` anywhere.
- **The commit pins in the conformance table** are each repository's checked-out
  `HEAD` at the time I read it. `cafaye-py` moved twice while this packet ran
  (its rescue landed at 17:57 and its gate commit at 18:00), so its row is a
  snapshot of a repository under active work and will be stale by the time this
  is merged. `kit`, `cafe` and `docs` I read from the working tree, which for
  `kit` means its checked-out `master` rather than anything a worker has open.
- **`sys.stdlib_module_names` as a definition of the standard library.** The
  gate test asserts the checker's three extra allowlist entries are in it on the
  interpreter that ran the suite. That is true here (3.14) and I did not check
  it on any other.
- **The 0-of-268 Semgrep / gosec / Bandi figures** are MD10's, carried forward.
  I did not re-run those tools; the *design consequence* — that the checker
  prints no environment and no gate output — is tested here, and the historical
  figure behind it is not.
- **The timeout breakage (21) took 1.2s** of the self-test's runtime on this
  machine. It is a three-second CPU-bound wait against a one-second budget, so
  the only way it can fail to fire is if the clock is wrong; but the *duration* is
  machine-dependent and a much slower runner will spend proportionally longer.
  There is no `sleep` anywhere in this packet, deliberately: `sleep 5` would make
  the result depend on the scheduler rather than on the checker.

## Deliberately not built

- **No second task runner.** The ruling above, and it is a success, not a
  compromise.
- **No tier logic.** `cafe gate` is MD12, it is owed in `cafe`, and `cafe` has a
  worker in it. This is a checker of **declarations**; making `gate.proof`
  strong enough to prove a database tier was actually *hit* is MD12's
  collect-then-run machinery, and `harness/gate_findings.json` says so under
  `notEnforced` rather than implying it. I did not build it and I did not
  pretend to.
- **No fix outside `core`.** The table above is the deliverable for the other
  fourteen.
- **No rule in `harness/rules.json`.** That file inventories the *contract* rules
  in `cafaye_contract.py` and its ids are asserted equal to `module.RULE_IDS`, so
  a gate finding in there would break that assertion and mean something false.
  `harness/gate_findings.json` is a separate inventory, asserted equal to
  `gate_check.FINDINGS` **in both directions** — a finding nothing exercises is
  a finding that will be wrong the first time somebody needs it, and that is the
  argument `rules.json` already makes, applied to my own file.
- **No `gate.yml` written anywhere but here**, and no `examples/` entry that
  names a real fleet service — same boundary core-08 held for SLOs, and
  `test_no_slo_example_declares_a_real_fleet_service` is the precedent.

## One unrelated defect found and not fixed

`harness/tests/self_test.sh` ends with two `printf '\n'` calls on one line, so
its final line reads `printfPASS: self_test — all 28 breakages went red…`. It is
cosmetic, it is pre-existing, it is in a file this packet did not otherwise
touch, and fixing it would change a log core's CI asserts against. Left for the
manager rather than folded into a packet about gates.

# docs/gate.md — how a anywaye repository declares its gate

**The rule.** A repository declares its gate in a file called `gate.yml` at its
root, written against [`schemas/gate.schema.json`](../schemas/gate.schema.json)
and checked against the repository by
[`harness/gate_check.py`](../harness/gate_check.py). A gate that has to be
discovered by getting it wrong is not a gate.

## Why this file exists

Measured across the fifteen repositories in the anywaye workspace, there were
five different spellings of "run the gate":

| Spelling | Repositories |
| --- | --- |
| `mise run prime` | billing, cafe, anywaye-rb, courier, darkroom, docs, identity, pantry, parlor (9) |
| `mise x -- ./bin/prime` — a `bin/prime` and **no `[tasks]` section at all** | gateway, muse (2) |
| a mise task named `test`, not `prime` | core (1) |
| `bash tests/validate.sh` — no `mise.toml` and no `bin/` at all | kit (1) |
| a mise task named `gate` whose `run` names a file that does not exist | anywaye-py (1) |

And two of the three times the gate was run badly in this fleet, it went green
while failing:

- `… | tail -45; echo "PRIME EXIT=$?"` under **zsh**, which has no
  `PIPESTATUS`. `$?` was the exit code of `tail`, which is always 0. The log
  said `FAIL github.com/anywaye/identity/internal/users 604.552s`; the shell
  said `PRIME EXIT=0`; the only thing that caught it was a person reading the
  log, which is not a mechanism.
- `kit` was dispatched with the fleet-standard gate, in a repository with no
  `bin/`. The command named in the packet could never have run.

And the third failure was not a mistake at all, it was a gap: identity's
`bin/prime` does not migrate the database. A gate that creates a database and
does not migrate it is a suite that is entirely green against an empty schema —
1430 tests proving they do not notice an empty database. Recovering it cost one
604-second run.

Those are three mistakes wearing three coats. It is one mistake: **the gate is
discovered by failure instead of declared.** `wavecheck.sh` already encodes the
same lesson for worker liveness — *the roster is discovered, not maintained* —
and its own comment records that three earlier versions of it were wrong. The
fix there was to stop maintaining the roster by hand.

## Why not mise tasks alone

This is the incumbent, generalised: nine of the fifteen repositories already do
it, and it works well as a **runner**. Measured here, in this repository:

```
$ mise tasks
prime  The gate: validate every example against the core schemas (bin/prime)
setup  Create tests/.venv and install the validator dependencies
test   Alias for `mise run prime`; kept so existing muscle memory and scripts still work
```

mise can be made to give a machine the *list* of tasks. What it cannot do is
hold the three things this packet needs:

1. **External requirements.** `[tasks.prime] run = "bin/prime"` has nowhere to
   say that `bin/prime` needs an interpreter and one fetch from PyPI on a cold
   checkout. The honest answer today lives in a comment at the top of
   `mise.toml`, and a comment is not checkable — which is the entire
   uncomfortable history of identity's unmigrated database.
2. **Whether a gate ran.** A task is a command. Nothing in mise can tell
   `bin/prime` that ran 140 tests apart from `true`.
3. **Agreement with CI.** A task and a workflow are two files in two languages
   describing one gate, and mise has no opinion about whether they still agree.

So a mise task stays, and it stays the thing you run. What it cannot hold is a
**declaration**, and the objection to mise-alone is not that mise is bad — it is
that a task is a *claim* and this format is the one thing in the repository that
can be **checked**.

## Why not a CI-only declaration

kit already publishes `ci.reusable.yml`, and a GitHub Actions job *is* a
machine-readable statement of how a repository is gated. Measured, in the
fifteen repositories: thirteen have a workflow, and the two that do not
(`docs`, `anywaye-py`) are exactly the two whose gate nobody can find. That is
the argument for it.

It is rejected for two reasons, and the first is structural:

1. **A workflow cannot be run.** `gh` is not on a developer's machine, a
   workflow is not a local command, and the question this format exists to
   answer — *what gates this repository* — has to be answerable with nothing
   installed. A developer who has to push a branch to find out what the gate is
   has already lost.
2. **The local gate and the CI gate can then drift, and nothing sees it.** The
   two are separate files in separate languages with separate syntaxes. There is
   no relationship between them to assert. A CI-only declaration cannot detect
   that CI stopped running the gate, because CI *is* the declaration — there is
   no second copy to disagree with. This is measurable in this fleet: twelve of
   the fifteen declare a `gate` job, and `darkroom`'s runs `./bin/prime --db`
   while its local task runs `./bin/prime`, so the local gate and the CI gate are
   **already two different gates** in the same repository, and neither one says
   so.

The two are complements, and the format takes the part of each that is
checkable. `ci.workflow` + `ci.invokes` in `gate.yml` is checked *against* the
workflow, so the drift above becomes `gate.ci-disagrees` rather than a fact
nobody notices.

## Why not a second task runner

Because the fleet already has three spellings and this would be a fourth. A
declaration that *runs* things is a task runner, and adopting one is adopting
the maintenance of one. So: this is **not a task runner**, and the distinction
is not a naming preference. `gate.yml` declares; `mise` and `bin/prime` run.
The checker has exactly one job — compare the declaration to the tree — and the
one time it runs anything is when you ask it to prove the gate, which is a
question about a gate, not a way to gate.

## The format

`gate.yml`, at the repository root. Four required keys and one optional.

Three questions about this format are open, and the manager rules on them:
**D30** — a proof, or only a description of the gate
([DECISIONS.md](../DECISIONS.md#d30-the-gate-declaration-names-an-argv-and-the-checker-runs-it));
**D31** — 3.11 for this checker where the contract harness accepts 3.9
([DECISIONS.md](../DECISIONS.md#d31-the-gate-checker-is-stdlib-only-and-needs-python-311-where-the-contract-harness-needs-39));
**D32** — whether a repository with no CI is a warning or a failure
([DECISIONS.md](../DECISIONS.md#d32-whether-a-repository-with-no-ci-is-a-warning-or-a-failure)).

```yaml
version: 1
name: core

gate:
  command: [bin/prime]          # an argv. What a person or a tool runs.
  miseTask: prime               # `mise run <task>` must resolve to `entrypoint`
  entrypoint: bin/prime         # a repository-relative path; must exist, be executable
  timeoutSeconds: 900
  proof:
    - id: suite                 # what "the gate ran" looks like
      match: '^([0-9]+)/[0-9]+ passed$'
      minimum: 140              # a floor, read from group 1

external:
  selfContained: false
  requirements:
    - kind: network             # database | service | toolchain | credential | network | filesystem
      name: PyPI, ONCE, on a cold checkout
      satisfy:
        command: [tests/setup.sh]
        unmet: tests/.venv/bin/python does not exist

ci:
  workflow: ci/ci.yml
  invokes: [bin/prime]
```

Three choices in there are load-bearing and each has a reason.

**An argv, never a shell string.** A command is a list of arguments, so the
first one is a file or a PATH name and nothing in it is a shell metacharacter.
The schema refuses `| & ; < > ( ) $ backtick ' " * ? { } [ ] # ~` and a newline
in any argument, and allows `= , : @ + %` and spaces. A gate argument never
legitimately needs the first set; a real one routinely needs the second
(`postgres://u:p@localhost:5432/db` is a perfectly ordinary argument). The
`examples/invalid/gate.shell-string.yml` file is the exact command that produced
this fleet's false green, and the schema refuses it.

**A proof, or the declaration is the false green written down.** `match` is a
Python regular expression applied with `re.MULTILINE` to the gate's combined
stdout and stderr, **with terminal escapes stripped** — see
[the output is matched colour-free](#the-output-is-matched-colour-free) below,
which is a rule with a consequence and not a detail. A run that exits 0 without
emitting every declared proof is `gate.proof-missing`, and it is a **failure**.
`minimum` is read from the pattern's single capture group, and it is a
**decrease-detector**: a suite that quietly lost forty tests cannot report itself
as passing. `1/1 passed` and `3/3 passed` are the same claim without it.

Two proofs is how two tiers stay separately countable. A repository with a unit
tier and a database tier declares both; a run in which only the first appeared
is `gate.proof-missing`, which is a different and more honest thing than "a
green with a smaller number in it".

## The output is matched colour-free

**Write your `match` patterns against the line a terminal SHOWS, not the bytes a
log holds.** The checker removes ANSI escape sequences from the gate's captured
output before it applies any `proof[].match`, so `^[ ]*Tests[ ]+([0-9]+) passed`
is the right pattern for `vitest` even though the captured line begins with
`\x1b[2m` and not with a space.

This is not a convenience. It was a false red on the first repository to adopt
this format with a colourising runner: the suite really ran and really printed
`Tests  377 passed`, the declared pattern could not match the escaped bytes, and
core answered `gate.proof-missing` about a gate that had just proved — in the
same log — that it ran 377 tests.

The reason the fix lives here and not in the declaration is the point of the
format. The alternative is `NO_COLOR=1` in the gate, or an escape-tolerant regex
in each repository. Both make the **gate** or the **declaration** carry the cost
of a defect in the **checker**, and the first quietly changes what a developer
sees when they run the gate by hand. This is one place, in the checker.

Stripping happens in `harness/gate_check.py`, once, where the output is read.

### What is stripped

| Sequence | Shape | Emitted by |
| --- | --- | --- |
| **CSI** | `ESC [ … final`, and 8-bit `0x9b` | SGR colour, cursor moves, erase-line, private modes — `vitest`, `cargo test`, `pytest`, `go test`, colour-enabled `mix test` |
| **OSC** | `ESC ] … BEL` or `ESC ] … ST`, and 8-bit `0x9d` | window titles (OSC 0/2), hyperlinks (OSC 8) |
| **DCS** | `ESC P … ST` | device control, wrapped payloads |
| **two-character** | `ESC ( B`, `ESC 7`, … | charset selection, keypad mode |

**Not handled, deliberately: an unterminated sequence.** A string sequence with
no terminator is left in place rather than consumed to end-of-input. The
tempting alternative consumes everything after it — including the proof line —
and turns an absent proof into a green, which is the exact class of defect this
format exists to end. A gate that leaves a sequence unterminated is malformed,
and a malformed gate is allowed to fail loudly. If you hit this, the fix is in
the gate's runner flags, not in a wider regex.

The gate's **log keeps the raw bytes**. Stripping applies to matching only: the
log is the operator's evidence, and a log that disagreed with the output it
records would be a worse lie than the one being fixed.

### What stripping does to a pattern

Stripping **can broaden a pattern**, and it is worth knowing how, because the
summary ("colour carries no assertion, so nothing is weakened") is reassuring
until you know the mechanism. Two consequences, both real:

1. **An anchored pattern can reach a line it could not reach.** `^` binds to the
   start of the line. With the escape present, `^[ ]*Tests` cannot match
   `\x1b[2m Tests`; stripped, it can. So a declaration may match **more** lines
   than it did. Since `minimum` reads the **last match**, a broadened pattern can
   change the number the ratchet sees: given a plain `Tests  377 passed` followed
   by a colourised `Tests  2 passed`, the raw bytes yield `377` and the stripped
   bytes yield `2`. **Write patterns specific enough that this cannot bite** —
   anchor the whole line, and do not let one pattern cover two different
   summary lines.

2. **`.` counts different bytes on each side.** A pattern that positions itself
   with a fixed number of `.` sees escape bytes before and visible bytes after,
   so `^.{6}Tests` matches one line raw and a different line stripped. Do not
   count characters to find a position; match the words.

The property that *is* unconditional, and the reason the ruling still stands:
stripping only ever **deletes**. It never inserts or reorders a byte, so it
cannot fabricate a match out of nothing.

Stripping also removes a quieter defect in the other direction. `\x1b[38;5;208m`
is a 256-colour **index**, and a gate that ran 3 tests and printed
`\x1b[38;5;208m3 passed` matches `^.*?([0-9]+).* passed$` with group(1) equal to
`38` — so `minimum: 38` was green over a suite of three. Colour-free matching is
what makes the number in the log the number the gate printed.

**`external` is required, always.** Its absence is the defect that let
identity's suite be green against an empty schema. And `satisfy.command` is an
argv you can paste, not a sentence: a pointer to a wiki page that does not exist
is exactly what this field replaced. When `satisfy.command[0]` contains a `/` the
checker verifies the file is there, because that is a claim about **this**
repository. When it is a bare name it is a claim about **this machine**, and the
checker deliberately does not settle it — it reports `gate.requirement-unproven`
and leaves the exit code alone.

## Reading a gate's exit code without inventing the false green

```bash
#!/usr/bin/env bash
set -o pipefail          # NOT `set -e` alone: that does not see through a pipe

bin/prime 2>&1 | tee "$RUNNER_TEMP/prime.log"
status=${PIPESTATUS[0]}  # NOT `$?`, which is tail's, and tail is always 0
exit "$status"
```

`PIPESTATUS` is a **bash** array. **zsh has no `PIPESTATUS`**, and this is not
a documentation detail: it has already produced one green over a red gate in
this fleet. If your shell is zsh, either run it under `bash` as above or do not
pipe at all. A script you leave behind must carry `set -o pipefail` at the top
too — `harness/bin/gate-check` does, and so does every other script in this
repository.

`harness/gate_check.py` itself never pipes: it calls `subprocess.run` with the
argv and no shell, so its exit code is the gate's own and the whole class of
defect above is structurally impossible for it.

## What the checker reports

`{ok, warn, fail}`, which is yamine's shape as MD13 recorded it, and
**`warn` never moves the exit code**. A gate built on booleans forces a choice
between "fail on warnings" (noisy, gets disabled) and "ignore them" (the report
is a lie). All five warnings here are the same kind of thing — *this machine
could not answer that* — and a checker that turned them into failures would be
red on a laptop and green on CI, which is the same defect in a new place.

| id | severity | what it catches |
| --- | --- | --- |
| `gate.declaration-missing` | fail | the repository declares no gate at all |
| `gate.declaration-unreadable` | fail | the declaration is YAML core's reader refuses |
| `gate.schema` | fail | the declaration does not satisfy `schemas/gate.schema.json` |
| `gate.command-missing` | fail | `command[0]` names a file this repository does not have |
| `gate.command-unknown` | warn | `command[0]` is a bare name not on PATH **here** |
| `gate.entrypoint-missing` | fail | `entrypoint` is not a file |
| `gate.entrypoint-not-executable` | fail | `entrypoint` cannot be run |
| `gate.task-config-missing` | fail | a `miseTask` is named and there is no `mise.toml` |
| `gate.task-missing` | fail | the named task is not in the mise config |
| `gate.task-unresolvable` | fail | the task's `run` resolves to a different file |
| `gate.task-unreadable` | warn | the task's `run` is a shell string, not an argv |
| `gate.task-undeclared` | warn | a mise config with tasks, and no `miseTask` named |
| `gate.ci-missing` | fail | the named workflow is not a file |
| `gate.ci-disagrees` | fail | the workflow never invokes the gate, and nothing in it defers to a task runner either |
| `gate.ci-unproven` | warn | no step reads as the gate, but the workflow defers to a task runner this checker cannot follow |
| `gate.ci-undeclared` | warn | the declaration says nothing about CI |
| `gate.proof-invalid` | fail | a pattern that will not compile, or a floor with no group to read it from |
| `gate.proof-missing` | fail | **the gate exited 0 and did not emit a declared proof** |
| `gate.floor` | fail | the proof's count is below the promised floor |
| `gate.nonzero` | fail | the gate exited nonzero |
| `gate.timeout` | fail | the gate outlived `gate.timeoutSeconds` |
| `gate.requirement-path-missing` | fail | a requirement's command names a file that is not there |
| `gate.requirement-unproven` | warn | a requirement nobody ran, by design |

Exit codes: **0** no failure (warnings may still be printed), **1** at least
one failure, **2** the check could not happen. Never 0 and never 1 for a run
that could not read the declaration — a missing checkout is not a clean bill of
health, it is an unknown, and core's rule about skipped tests is the same rule.

`harness/gate_findings.json` is the inventory, every finding with the claim it
makes and the exact command that fixes it, plus a `notEnforced` list of what
this checker does **not** prove. Every message carries its remediation because
that is the single most transferable thing in yamine's 7,000 lines, and the
reason the fleet decided not to copy the rest of it.

### How many times, and through what

`gate.ci-disagrees` is the check whose entire job is noticing that CI stopped
running the gate. It had no written-down answer for the two most common shapes a
workflow can take, and it guessed wrong on both. So here is the answer, in full,
with the reasoning. The teeth are in `tests/test_specs.py`
(`test_gate_ci_multi_invocation_and_indirect_invocation_have_a_stated_policy`)
and in `harness/tests/gate_self_test.sh`; this is the prose they came from.

**A PASS in three shapes.**

1. Every element of `invokes` appears in some `run:` body — **once, or any number
   of times.** `invokes` is a claim that the gate is *reachable* from CI, not a
   count of how often it is reached. core's own workflow runs `bin/prime` at
   ci.yml:186 and `bin/prime --pytest` at ci.yml:338 — two entry points to one
   suite, asserted to report the same number of tests — and the declaration names
   only the first. A checker that read multiplicity as drift would fire on the
   repository that wrote the rule. One is not "more correct" than two; the
   question is never *how many*.
2. The workflow calls the mise task the declaration names — `mise run prime`,
   where `mise.toml`'s `[tasks.prime]` resolves to the declared `entrypoint`.
   This is a pass because it is *provable*, not because it is plausible:
   `check_task` has already read `mise.toml` and established the resolution for
   `gate.task-unresolvable`, and this reuses that proof to read a second spelling
   of the same command. Nothing is taken on trust. (If that task does *not*
   resolve, `gate.task-unresolvable` is already a failure, so a repository cannot
   buy its way to green through this path.)
3. A job that only calls a reusable workflow, sitting beside a step that runs the
   gate. That is `gateway` and `parlor` both, and it needs no special case: the
   `uses:` line is simply not a `run:` body, so it is not read, and the step that
   *is* one is.

**A WARNING when the gate is behind a wrapper nobody declared.** `make gate`,
`./scripts/ci.sh`, a task the declaration does not name. This checker reads no
Makefile and no shell script, so a wrapper that calls the gate and a wrapper whose
target was emptied are *the same text* to it. Failing there is the false red this
checker shipped for a fleet release — the one that made `anywaye-rb` rewrite its
own workflow to satisfy it. Staying silent is the false green. So it is
`gate.ci-unproven`, it prints what it could not see, and it exits 0.

**Its leak, named rather than hidden.** The warning fires on *any* task-runner
step, so a workflow whose only task call is unrelated warns instead of failing —
which means deleting the gate step from such a repository costs a warning, not a
red. That is the price of not crying wolf, and it is a real price. The
alternative was measured, not assumed: `gate.ci-disagrees` failing on every
wrapper-gated repository is precisely what made this standard harder to adopt
than the thing it standardises. Anyone who wants the strict reading back gets it
by deleting the `TASK_RUNNER_CALL` branch in `check_ci` — one `if`, and the
warning goes with it.

**A FAILURE when the run bodies contain nothing that gates at all.** No step, no
task runner, no declaration of any kind. CI plainly does not run the gate, and
that is the whole job of this check. This stays a failure precisely *because* the
warning tier above is narrow: a plain workflow that lost its gate step still goes
red, which is the case the check exists for.

**What is not in this policy, and why.** The obvious alternative — a declared
`ci.indirect` list, so a repository could name its own wrapper and get a
straight pass — was rejected *for this packet*, and the one-line path to it is
recorded rather than left in a discussion: adding an optional string array to the
`ci` block of `schemas/gate.schema.json` plus three lines in `check_ci`. The
reason to wait is that the standard is being adopted right now, and asking every
adopting repository to learn a new key on day one to dodge a false red is a worse
migration than a warning that explains itself. The warning names the fix in its
own text, so nobody has to guess.

### The spellings `run:` is read in

The other half of the same story, and the reason the false red reached three
repositories. `workflow_run_lines` used to match `run:` only when the key was
bare or carried a `|`/`>` block scalar, so **every one-line `run:` was invisible**
— including `gateway/ci.yml:65` (`run: bin/prime`) and `parlor/ci.yml:81`
(`run: ./bin/prime`), both of which run the gate and were both reported as not
running it. Across the twelve workflow trees this standard was written for, 139
`run:` keys: 101 block scalars and 38 one-liners. The 38 were the invisible ones.

Read now: `run: |` and its `>`/`-`/`+` variants; `run: <command>` with any
arguments and any quoted variables; `- run: <command>` (zero occurrences here,
included anyway — a shape absent from today's tree is not a shape that should be
invisible); and a bare `run:` whose value is on the lines below it.

One shape is deliberately **not** read as a command, and it is the reason the
anchor is not simply deleted: a `run:` whose whole value is a comment. PyYAML
reads `run: # TODO: wire up bin/gate` as `None` — there is no command on that
line at all — so treating the comment as one is a green badge on a workflow that
runs nothing. A trailing comment on a line that *does* carry a command is kept,
because removing it would truncate the only part that matters.

And one thing a correct pattern costs, named because it did not exist while the
pattern was wrong: `workflow_run_lines` tracks indentation inside a `run:` block
and nothing else, so a line reading `run: bin/gate` *nested under another
mapping* — an `env:` value, a `with:` input — is read as a command. Measured
across the 139 `run:` keys in those twelve trees: every one is a direct child of
a step's `- name:`/`- uses:`, and not one is nested. Closing it properly means
parsing, which is the second YAML dialect this file exists to avoid, so it is
recorded in `gate_findings.json` rather than half-fixed.

### The two phases, and why there are two

- **Static** (the default): the declaration against the tree. Nothing is run.
- **`--prove`**: runs the declared gate and requires every proof to appear.

`bin/prime` runs the **static** half and must not run the proving half: the
checker runs the gate, and the gate runs the checker, so a gate that verifies
itself by running itself terminates and the termination is all it proves. The
proving half is a step of core's CI of its own.

### The third thing `bin/prime` runs, and why it is not the recursion

`bin/prime` also runs **`harness/tests/gate_self_test.sh`**, the checker's own
red proof. Until core-14 it ran in CI only, and that made the local gate weaker
than CI in the one place a weaker gate is invisible: a developer could have
replaced `harness/gate_check.py` with a function that returns 0, run
`bin/prime`, seen `179/179 passed`, exited 0, and learned nothing about whether
the checker could detect anything.

It is not the recursion the paragraph above warns about, and the difference is
mechanical rather than a matter of arrangement:

| | `--prove` | the red proof |
| --- | --- | --- |
| runs | **the declared gate** — for core, `bin/prime` | **fixture repositories** — `harness/tests/fixtures/gates/conforming`, whose gate is three lines and is not `bin/prime` |
| reads core's own tree | yes | no; it copies the fixture into a temp directory and never looks at the repository it was invoked from |
| asks | did *this* gate run, and did it say so | could the checker have said **no** about anything at all |

Nothing in the red proof runs `bin/prime`, so there is no cycle for the
termination to travel round. And the two answer different questions: `--prove`
looks at one run and asks whether the proof appeared, so a checker that could
only say *yes* would look exactly like a passing gate to it. You cannot catch a
checker that can only say yes by asking it about a run that passed — which is
what the red proof is for.

**What it costs, stated because a cost nobody mentions is a cost the next person
rediscovers:** about forty seconds of wall clock per `bin/prime`, which takes it
from about twenty seconds to under a minute. `gate.timeoutSeconds` is 900, so
CI has room. The red proof runs **last**, after the suite, so a red suite costs
the suite's runtime and not the suite's runtime plus forty seconds of work about
something else.

**Three rules govern how it is allowed to be quiet**, and each of them is a
refusal this project has made before — gateway's live-Redis tier, muse's
`MUSE_CORE_SCHAMAS`, identity's `TEST_DATABASE_URL`, darkroom's `--ignored`:
four repositories that shipped a check which quietly did not run, and every one
of them read exactly like a pass.

1. **Its failure fails `bin/prime`.** Not a warning. A warning that does not
   move the exit code is a comment, and this step's whole claim is that the
   checker can fail.
2. **It cannot skip.** A missing script, no `bash` on `PATH`, or an interpreter
   older than 3.11 are each a non-zero exit naming the precondition that is
   missing — never the word "skipped".
3. **Its report is read, not trusted.** The exit code is the floor of the
   evidence. A red proof that exits 0 having printed no counts has proved
   nothing, so `bin/prime` parses the counts block and requires every category
   present and non-empty, the control to have printed its own `PASS` line, the
   skip count to be zero, and the number of logged case lines to cover the
   counts. Pass and skip counts are then printed **separately**, because a single
   number where there are two is how a skip hides inside a pass.

**The interpreter is pinned.** The red proof otherwise scans `PATH` for an
interpreter new enough, which is right for a script a service copies out of core
and wrong inside core's own gate — the local gate would then depend on the
machine, and a laptop whose system Python is 3.9 would fail a checkout CI is
green on. `bin/prime` exports `ANYWAYE_GATE_PYTHON` as the venv interpreter, the
same pinned one the suite runs on, and the log says which interpreter answered.

**One sharp edge this introduces, and it is closed.** `gate.proof` is matched
against **everything** `bin/prime` prints, with the floor reading the **last**
match, and a second program is now printing into that output. So a line shaped
like a proof printed by the red proof could satisfy the gate's proof or be read
as the floor's number. Nothing the red proof prints is of that shape today, and
that is an accident waiting to be edited into — so
`test_the_red_proof_cannot_satisfy_the_gate_s_own_proof` takes every literal
`printf`/`echo` in `harness/tests/gate_self_test.sh`, fills in its conversion
specs with digits, and requires each one to fail to match every pattern
`gate.yml` declares, compiled by the checker's own `_compile`.

**Asymmetry, deliberate, and it is a judgement about which checkers have crashed a
merge.** `harness/tests/self_test.sh` — the *contract* harness's red proof — is
still a CI step only. The gate checker's red proof runs locally because it guards
the checker `bin/prime` ran on the line above, so a developer who has just run the
gate knows whether that answer was earned. The contract harness's 28 breakages
are about a different checker, on a different schedule, and adding them would add
their runtime to every local run for a claim the gate does not make about itself.

**And then the account-scope checker's red proof moved in, for the opposite
reason.** `harness/tests/account_scope_self_test.sh` — 32 cases — was also CI-only,
and on 2026-10-03 `bin/prime` exited 0 on a tree on which **2 of those 32 were
red**, because the checker had crashed with `ValueError: not enough values to
unpack` on a case no gate ran. Nothing about "cheap enough" was the test: that
checker had taken this gate down and the gate had not been watching.
`numeric_self_test.sh`, `tenancy_self_test.sh` and `self_test.sh` stay CI-only
until one of them does the same. The entry is in
[DEBT.md](DEBT.md) — "the gate that did not run the proof" — because the next
person to merge two branches will read this paragraph only if it is here and will
otherwise rediscover it from a green.

### It never prints the gate's environment, or the gate's output

No off-the-shelf tool detects a secret *leaked at runtime* into a log or an error
string — 0 of 268 Semgrep rules intersect CWE-532, gosec has no
`ast.CallExpr` case, Bandit is `ast.Constant`-only. So this checker prints the
command **as written** and never its expansion, and the gate's stdout goes to a
log file whose path is reported. A finding that quoted a failing test's output
would be a new place a credential lands, and a CI log is kept forever and read
by people who were not there.
`test_the_gate_checker_never_prints_a_value_read_from_the_environment` runs a
gate that prints a connection string and asserts the report is clean and the log
holds it.

### The red proof

`harness/tests/gate_self_test.sh` copies one conforming fixture into a temporary
directory, breaks exactly one thing in each copy, and asserts the checker goes
red **and names the finding it expects**. A control on the unbroken fixture runs
first — without it, the reds prove nothing.

It reports **every category separately, and every category has a number in the
counts block**, because a case kind with no number is a case kind nobody can tell
stopped running. Measured on this tree:

| Category | Count |
| --- | --- |
| breakages that went **red** and named their finding | **18** |
| warning cases that stayed **green** (exit 0 asserted) | **7** |
| green cases that matched a colour-bearing gate | **3** |
| colour reds that still went red | **2** |
| real-workflow `run:` spellings **accepted** | **12** |
| extractor assertions (must / must-not) | **4** |
| the case that kept a secret out of the report | **1** |
| the control (a true declaration, unbroken) | **1** |
| **skipped** | **0** |

Two of those numbers are not obvious and both are enforced rather than hoped
for. The red cases are 18, not 25: `breakages` in that script is a hand-
incremented **case label** so printed lines can be referred to by the same
number the comments use, and it counts the seven warning cases too — so printing
it as "breakages that went RED" claimed seven reds that did not happen, on the
one number a reader has most reason to trust. Each category is now counted
inside the function that runs its case, and
`test_the_red_proof_counts_every_case_it_runs` requires the increment to live
there and the counts block to print that variable rather than a literal.

And the skip count is a literal `0`, which is honest only because of what can be
checked rather than believed: nothing in that script is conditional. Every case
runs unconditionally at the top level, and the two preconditions that can fail —
an interpreter, the fixture — exit non-zero before any case runs. The same test
requires every case call to be unindented and unchained, which is what "nothing
here skips" means in a shell script. `bin/prime` reads the row and fails the
gate on a non-zero, because the first time a case *can* be skipped the answer
has to be a red build and not a smaller number.

Breakage 8 is the one that is not string matching: a repository whose
declaration is **entirely true** about a gate that exits 0 without running
anything. The command exists, it is executable, the mise task resolves to it, CI
calls it — and the repository is ungated. Nothing in the declaration is wrong.
The only thing that catches it is asking the gate to say what it did.

## What this does not prove

Recorded in `harness/gate_findings.json` under `notEnforced`, and repeated here
because a gate check that claims more than it can is the defect it exists to
remove:

- **That an external requirement is satisfied.** The checker reads the
  declaration; it does not start Postgres to find out. A requirement is the
  operator's to satisfy, before gating.
- **That the tests touched the dependency they claim to.** A proof is a line of
  output. 1430/1430 against an empty database proves 1430 tests ran. Making the
  proof strong — a collect-then-run set diff, an assertion that a connection was
  opened — is MD12's machinery and it is owed in `cafe` as `cafe gate`, by a
  different worker. This is a checker of **declarations**; if you find yourself
  wanting tier logic in it, you have left its scope.
- **That a CI workflow does what it says, in the order it says.** The workflow
  is read textually and one question is asked of it: does any step's `run:`
  body mention the declared argv. A step can branch on an event, be filtered by
  a path, or live in a job that does not run on this branch, and none of that is
  visible from the text. core's own CI therefore runs the proving half as a real
  step, which is the check the text cannot do.

## Adopting it in another repository

1. Write `gate.yml`. Copy [`gate.yml`](../gate.yml) and change four lines, or
   start from [`examples/valid/gate.self-contained.yml`](../examples/valid/gate.self-contained.yml).
2. Run `harness/bin/gate-check .` — the static half, and it does not need a venv
   or a package.
3. Run `harness/bin/gate-check --prove .` — this runs your gate. It is the
   step that is not optional.
4. If the gate is not `mise run prime`, either rename the task (and leave a
   `depends` alias if anything already used the old name — that is what core
   did) or accept a `gate.task-undeclared` warning and say so in the
   declaration's comment.
5. If the gate needs a database, a service, a credential or a network, list it
   under `external.requirements` with a `satisfy.command`. **If it needs one
   and does not say so, that is the identity defect, and it is the one this
   format exists to prevent.**

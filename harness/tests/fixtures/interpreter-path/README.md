# `harness/tests/fixtures/interpreter-path` — two PATHs for the search

`harness/tests/gate_self_test.sh` has to pick a CPython before it can run a
single case, and it looks for one in this order:

    python3  python3.13  python3.12  python3.11  python

unless `ANYWAYE_GATE_PYTHON` names one, which it honours as given.

That search used to stop at the first name that **resolved**, which is not the
same as the first name that **qualified**. On a machine whose `python3` is
3.9.6 the loop took it, stopped, and printed

    gate_self_test: no python >= 3.11 found; set ANYWAYE_GATE_PYTHON

while 3.13 and 3.14 sat on the same PATH, unused. A false negative in the
project's own proof-of-failure: the one script whose job is to prove the gate
checker can go red, reporting that it could not run at all.

These two directories are the PATHs that make that reproducible on any machine,
including one where `python3` is new enough and the bug is invisible.

| directory | what is on it | the correct answer |
| --- | --- | --- |
| `stale-first/bin` | `python3` **too old**, then `python3.13` new enough | keep walking, take `python3.13` |
| `stale-only/bin` | all five names, **every one too old** | walk the whole list, exit 1 |

`stale-first/bin` doubles as the fixture for a **too-old `ANYWAYE_GATE_PYTHON`**:
the same 3.9.6 `python3`, named directly instead of resolved, which must be an
error rather than a reason to go looking for a second interpreter. Those are
different files with the same name, which is why the case asserts the exit code
and stdout rather than the trace alone — see the third case in
`expect_python_search`.

## What the stubs are, and what they are not

Every file here is a 20-line `sh` script. **None of them is a Python.**

- The **too-old** stubs answer `--version` with `Python 3.9.6` — honestly, so a
  case can assert the stub really is what it claims instead of trusting a
  comment — and exit 1 for the version probe the search actually makes. A real
  3.9 answers that probe by exiting 1 too, which is the entire behaviour under
  test.
- The **new-enough** stub (`stale-first/bin/python3.13`) delegates to a real
  interpreter named by `$ANYWAYE_FIXTURE_PYTHON`, which the case sets to
  `sys.executable` of the interpreter already running the self-test.

That delegation is the load-bearing decision. A stub that answered the probe
with a hardcoded `exit 0` would pass the fixed search and the broken one
alike, because the bug is *when the loop stops*, not *what it decides about the
interpreter it stopped at*. Only a real `sys.version_info` can tell those two
apart. For the same reason nothing here hardcodes a path to a python: a
committed interpreter path makes a red proof that passes on the machine that
wrote it and fails everywhere else.

## The trace

Each stub appends its own name to `$ANYWAYE_FIXTURE_TRACE` when that is set, so
the cases can assert **the order the candidates were consulted in**:

    python3
    python3.13

That is the difference between "the loop happened to skip the stale `python3`"
and "the loop tried the stale `python3`, rejected it, and went on" — two
different answers to the only question this fixture exists to ask. In
`stale-only` the expected trace is all five names, which is what proves the
search did not give up early either.

**An empty trace is the signature of the original defect, and it reads like
nothing at all.** The probe is what makes a stub append, so a loop that stopped
at the first name that *resolved* never probes anything and leaves the trace
empty. The case reports an empty trace as `<none — nothing was probed at all>`
together with the child's exit code and the path it answered with, because
"consulted nothing" on its own is indistinguishable from a broken fixture, and
the two need opposite fixes.

Measured, with the original loop condition restored: the `stale-first` case
reports the 3.9.6 stub as the chosen interpreter, at exit 0, having consulted
nobody; the `stale-only` case reports the same stub at exit 0. Both in about
twenty seconds, both ending in a plain non-zero exit.

**Do not add a case here that runs the whole script on one of these PATHs.**
That was the first version of the `stale-only` case and it is a trap worth
writing down. With the search broken, the child resolves the stub, the
precondition lets it through, and the child runs every case down to that one,
which spawns another child: measured, eighteen seconds in, the tree was
`97132 -> 97666 -> 97667 -> 98130`, each link a `gate_self_test.sh` whose parent
is the last, still growing. It only terminates on a fixed search, so the case
passes on green code and consumes a machine on broken code — the one failure
mode a red proof may not have. Drive `--which-python` instead; it runs the same
search and the same refusal and stops before the first case.

## Not a fixture repository

Neither directory is a repository and neither is checked by `gate_check.py`.
They are PATHs, not projects: there is no `gate.yml`, no `bin/gate` and no
declaration, because nothing here is supposed to be gated. Adding one would put
a fixture for the checker's preconditions inside the checker's own subject
matter, which is the recursion this directory sits outside of.
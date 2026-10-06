# REPORT — core-python-portability-01

**Date:** 2026-10-07
**Branch:** `worker/core-w37-pythonport`
**Packet:** the account-scope red proof runs on a `python` this machine does not have

## Starting state

`git status` on entry: **clean tree, nothing to salvage.** The previous attempt
left no partial work in this worktree; everything below was measured and fixed
from scratch on master `e1e4853`.

## The defect, measured

`harness/tests/account_scope_self_test.sh` resolves its interpreter once, at
lines 342–355: `CAFAYE_ACCOUNT_SCOPE_PYTHON` if set (and `bin/prime` does set
it — `bin/prime:340`, `export CAFAYE_ACCOUNT_SCOPE_PYTHON="$interpreter"`),
else `command -v python3`, with a >= 3.9 check and an exit-2 if neither exists.
It then **ignored that variable at 41 call sites**, invoking bare `python` or
`python3`:

- **34 bare `python` sites** — 19 at line start (548, 563, 576, 591, 608, 626,
  637, 658, 668, 992, 1055, 1081, 1113, 1136, 1223, 1260, 1368, 1453, 1725),
  14 after `if ` (1580, 1597, 1688, 1757, 1838, 1886, 1944, 1969, 2006, 2074,
  2125, 2176, 2223, 2304), and 1 indented inside a function (1619).
- **7 bare `python3` sites** (682, 697, 709, 808, 861, 905, 921).

The packet said "34 sites … three more sites call bare `python3`". The 34 is
exact; the `python3` count is **7, not 3** — the packet undercounted. Total
fixed: **41 sites**.

On a machine whose `python` is absent (stock macOS ships `python3` only), every
one of those 41 fixture-planting steps fails to apply, each prints
`THE BREAKAGE DID NOT APPLY`, and the red proof — the thing that proves the
checker can say NO — cannot run. The gate's honesty depended on a binary the
script never requires. The three `python3` sites were the same pinning bug in
milder form: they happened to work on this machine but defeated the
`CAFAYE_ACCOUNT_SCOPE_PYTHON` pin, so the proof would have run against
whatever `python3` the laptop has rather than the venv interpreter `bin/prime`
chose.

## The fix

Every one of the 41 sites now invokes the already-resolved `"$python"`. No
re-resolution, no second variable, no change to the resolution block at
342–355. A comment was added above the resolution block recording why the
variable exists and why every call site — including the indented ones inside
functions — must use it. No case was weakened, skipped, or renumbered; the
checker itself was not touched.

## The other seven self-tests — measured, not assumed

| File | Resolution | Verdict |
|---|---|---|
| `numeric_self_test.sh` | candidate loop (line 123) | clean |
| `reserved_self_test.sh` | pins `CAFAYE_RESERVED_PYTHON` (line 61) | **SHARED THE BUG — fixed** |
| `self_test.sh` | candidate loop (line 67) | clean |
| `tenancy_self_test.sh` | candidate loop (line 114) | clean |
| `gate_self_test.sh` | candidate loop (line 161) + `--which-python` | clean |
| `core_version_test.sh` | candidate loop (line 46) | clean |
| `db_isolation_self_test.sh` | resolves `python` (line 109), uses `"$python"` (line 123) | clean |

`reserved_self_test.sh` exported `CAFAYE_RESERVED_PYTHON` (so the
`reserved-check` wrapper it shells to is pinned) but then called **bare
`python3` at lines 181 and 200** for its own fixture-planting steps. The
packet listed this file as clean; the measurement says otherwise. Fixed the
same way: both sites now invoke `"$CAFAYE_RESERVED_PYTHON"`. Verified green
under the python-less PATH: `PASS: reserved_self_test — 6 breakages went red
naming their finding, 2 controls, 12 assertion(s) passed`.

## Non-test harness files — measured

- `bin/prime` — resolves `python="$venv/bin/python"` (line 62) and uses
  `"$python"` at every invocation. Clean. Its `python3` mentions are comments
  and echo strings.
- `harness/bin/account-scope-check`, `cafaye-contract`, `tenancy-check`,
  `gate-check`, `reserved-check`, `db-isolation-check`, `numeric-check` — all
  resolve through candidate loops. Clean.
- `harness/bin/floors-check` — **measured, deliberately NOT touched.** Line 73
  invokes bare `python3`, but this is a different defect shape: the file never
  resolves an interpreter to ignore. It preconditions on `command -v python3`
  (line 68) and exits 2 with a clear message on a python-only machine — the
  fleet-standard honest "could not happen" failure, not a silent wrong
  interpreter. Adopting the candidate-loop pattern its seven siblings use
  would be a scope expansion this packet did not ask for. Recorded here as an
  observation; the cheapest path to the alternative is a three-line change to
  its resolution block, if the manager wants it.

## The proof

### The python-less PATH

The packet's literal construction —
`PATH="$(dirname "$(command -v python3)"):/usr/bin:/bin:/usr/sbin:/sbin"` —
does **not** produce a python-less PATH on this machine, because
`command -v python3` resolves into the mise shims directory, which contains
both names:

```
$ env PATH="$(dirname "$(command -v python3)"):/usr/bin:/bin:/usr/sbin:/sbin" \
    bash -c 'command -v python; echo "exit: $?"'
/Users/kaka/.local/share/mise/shims/python
exit: 0
```

So the precondition was built the way the packet intends — a PATH with
`python3` and no `python` — using a temp directory holding only a `python3`
symlink to the real interpreter (3.14.7):

```
$ env PATH="$tmpbin:/usr/bin:/bin:/usr/sbin:/sbin" bash -c \
    'command -v python; echo "command -v python exit: $?"; command -v python3'
command -v python exit: 1
/private/var/folders/3b/kt90wy3d66lftws_dwtxxglm0000gn/T/opencode/pythonless.GW6XpE/python3
```

`command -v python` is empty (exit 1); `python3` resolves. That is the PATH
the two runs below used.

### The red proof, green

```
$ env PATH="$tmpbin:/usr/bin:/bin:/usr/sbin:/sbin" \
    bash harness/tests/account_scope_self_test.sh
...
67 passed, 0 failed
```

**67 passed, 0 failed** — the packet's honest count, on a PATH with no
`python`. Every case ran; every red one named the finding it planted.

### `bin/prime`, green

```
$ env PATH="$tmpbin:/usr/bin:/bin:/usr/sbin:/sbin" bash bin/prime
$ echo $?
0
```

The packet asks for the `Result:` line verbatim. **This tree's `bin/prime`
prints no `Result:` line** — `grep -c 'Result:'` over the full 764-line log
returns 0. Its verdict is the exit code plus the `==>` summary lines, which
are pasted verbatim:

```
==> the account-scope red proof passed: 67 cases and 0 failed, every
  red one naming the finding it planted.
```

The suite half of the gate: `299/299 passed`. The reserved red proof inside
the same run: `==> the reserved red proof passed: 6 breakages went red naming
their finding, 2 controls green, including core's own tree.`

### Regression

Under the normal PATH (mise `python` present), the same red proof still
reports `67 passed, 0 failed` — the fix does not depend on the absence of
`python`, and the previously-working machine still works.

## What was deliberately not changed

- The resolution block at `account_scope_self_test.sh:342–355` — untouched.
- The checker (`harness/account_scope_check.py`) — untouched; only how its
  red proof finds its interpreter changed.
- No case weakened, skipped, or renumbered; counts unchanged (67/0).
- `harness/bin/floors-check` — measured, left as-is (reason above).
- No other repository touched.

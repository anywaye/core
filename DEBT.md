# DEBT.md — things this repository owes, written down so a merge does not rediscover them.

Each entry is a debt **with a mechanism already in place**, not a wish. A debt
here is something that has already cost a merge, so the entry is the record of
the cost and the pointer to what now stops it recurring.

---

## The gate that did not run the proof

**Owed.** A gate that does not run a checker's red proof reports on the parts it
happens to look at — and the report it produces reads exactly like the report of
a gate that ran everything. On 2026-10-03 that was not a hypothetical.

`worker/core-account-scope-contradiction` changed the caller of
`harness/account_scope_check.py`'s `_check_contradictions` to unpack **two**
values. `master` already had the definition annotated `-> list[Finding]`,
returning **one**. Each half was internally consistent, so git merged them with
no textual conflict:

```console
$ bin/prime          # exit 0
$ 295/295 passed
$ bash harness/tests/account_scope_self_test.sh
30 passed, 2 failed          # ValueError: not enough values to unpack
```

`harness/tests/account_scope_self_test.sh` is thirty-two cases with a fixture
tree and it was a **CI step and nothing else**. The manager merged two branches on
the strength of a green that had never seen the proof. It was not a slow step
nobody minded adding — it was the whole gate.

**Now.** `bin/prime` runs it, last, under the same three rules as the other three
red proofs it runs: its failure moves the exit code, a missing script or a
too-old interpreter is a non-zero naming the precondition rather than a skip, and
**its report is read** (`32 passed, 0 failed`, with a floor of 32 cases so a proof
that quietly stops running cases cannot pass). Delete the step and
`test_bin_prime_runs_the_account_scope_checkers_red_proof` and
`test_bin_prime_is_red_when_the_account_scope_red_proof_is` both go red.

**The rule, for the next person merging two branches.** A green is a claim about
the gate that produced it. Before you merge on one, ask what the gate did *not*
run, and check that list yourself if the answer is not empty. `bin/prime` prints
what it runs; the red proofs it does *not* run are `numeric_self_test.sh`,
`tenancy_self_test.sh` and `self_test.sh`, and they are CI-only because their
checkers have never taken this gate down. That is a judgement about which
checkers have crashed a merge, not a general principle — when one does, it moves
into `bin/prime` the same afternoon.

---

## A contract whose halves came from two branches

**Owed.** Nothing in the tooling knew that two branches had changed one
*contract*. Git knows about lines; this defect was about a shape, and each half
of the shape was internally consistent, so there was nothing for a textual merge
to object to. `mypy --strict` would have caught the arity; core does not run mypy
and adding it to a repository whose harness is standard-library-only is a larger
change than the defect, and it is defeatable with one `# type: ignore` on the
same line as the lie.

**Now.** Two changes, and the second is the one that matters:

1. `_check_contradictions` returns a named structure, `Contradictions`, rather
   than a bare 2-tuple. The arity of a dataclass constructor is checked at the
   constructor, inside the function, which is where the bug was.
2. `test_every_harness_function_returns_one_shape` walks **every** module in
   `harness/` and asserts, per function, that all its value-returning arms yield
   the same number of values and that the return annotation says the same. It is
   proved by re-introducing the exact bug — the stale `-> list[Finding]` with the
   two-valued body — and watching it go red on two counts in one function.

**The blind spot, stated rather than hidden.** A return the walk cannot resolve
statically — a starred unpack, a conditional whose arms disagree, a call to a
name with two shapes of its own — is exempt, and the count of them is printed in
the failure message so the exemption stays visible. Ninety-two returns are in
that state on the tree as of this writing. The rule covers the module-local,
single-return, plainly-typed case, which is where a merge defect has room to
hide; it does not replace a type checker and is not claimed to.
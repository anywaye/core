# REPORT — `core-merge-resolution-01`

**Branch:** `worker/core-merge-resolution-01` (from `master` at `f3cb9b2`)
**Merges:** `worker/core-handler-resolution-01` (`5607366`, `c9c1828`, `7f859dd`)
**Packet:** `core-merge-resolution-01`
**Date:** 2026-10-03
**Verdict:** both sides kept. 35 numbered cases, one sequence, no gaps, no
duplicates. **43 passed, 0 failed** where master alone was **36 passed, 0 failed**.
`bin/prime` exits 0 with 299/299. `master` is **not** merged — that is the manager's.
Nothing was pushed and no other repository was modified.

The two blocks turned out to be genuinely independent: different fixtures, different
checker functions, no shared line. Details and the one non-mechanical repair in §3.

---

## 1. What collided, and why git could not anchor it

One file: `harness/tests/account_scope_self_test.sh`. Both packets appended their
cases to the tail of the same script and both appended a listing block to the same
region of the header, so git found no shared context line and produced one content
conflict spanning the case bodies (lines 906–1395).

| side | cases added | commit |
| --- | --- | --- |
| `master` (`core-stale-declaration-01`) | 26, 27, 28 — `registration-commented` | `01124f7`, merged `f3cb9b2` |
| `worker/core-handler-resolution-01` | 26, 27, 28, 29, 30, 31, 32 — Go handler resolution | `5607366`, `c9c1828` |

**Both sides used the numbers 26–28.** Three of the seven cases the handler packet
brought were numbered *identically* to three of master's, and two of those three
(`27`, `28`) are prose cross-references as well as case labels — case 28's own body
says "27's repository PASSES", and master's header entry for 28 says the same. A
merge that kept master's text and appended the handler's would have produced a file
with two different case 26s, two different case 28s, and a cross-reference in each
one pointing at the other's subject.

Everything else merged itself. `harness/account_scope_check.py` auto-merged with no
conflict and carries **both** fixes — `registration_findings` (line 1528) and
`_handler_candidates` (line 2195) — and `harness/account_scope_findings.json`,
`gate.yml`, `docs/account-scope.md` and `tests/test_specs.py` needed no attention.
The two packets touched disjoint functions in the checker, so there was no semantic
conflict hiding behind the textual one; §5 shows both fixes live at once.

---

## 2. The renumbering, and why master's numbers stayed

**Decision: master's 26–28 keep their numbers; the handler's 26–32 become 29–35.**

The reasons, in the order they mattered:

1. **Master is already merged and shipped.** `f3cb9b2` is on `master`, its report is
   read, and its numbers appear in the checker's own docstring
   (`registration_findings`: *"case 28 deletes the call to this from a throwaway
   copy of the checker"*). Renumbering master would have made a shipped file's
   docstring point at the wrong case — and the packet's own instruction is that the
   manager merges to master, so master's numbering is the one with an audience.
2. **Order of arrival in the file.** Master's cases sit physically before the
   handler's in the merged body, so its numbers come first with no reshuffle.
3. **The handler's cases were authored last**, so theirs move. A +3 shift on 26–32.

Every reference moved with its case, not just the label. That is 16 references in
the handler's two regions — `note "case N`, `#   NN.` listing entries, the
`CASES 26-29` / `CASES 30-32` range headers, and the prose cross-references
("would satisfy 27 and 28", "which is what 31 is for", "Without it, 31 could be
satisfied by always answering with the OUTERMOST symbol", "Case 29's first version
PASSED FOR THE WRONG REASON"). They were renumbered in a **single pass** so no
number could be shifted twice, and the region was first checked by hand to contain
nothing but case references — no line number, no fixture constant. `httpapi.go:246`,
router lines 40/42 and the middleware's line 83 are untouched.

Verified mechanically afterwards, over the resolved file:

```
body case labels : 1..35, contiguous, no gaps
duplicate numbers: 10 only (10 / 10b) — pre-existing, both sides, untouched
listing vs body  : identical sets, 15 excepted (15 is the family parent of 15a-e,
                   which was already the case before this conflict)
every cross-ref  : resolves to a case that exists
```

**The header was also reordered.** Git concatenated the two listing blocks, so the
merged header read: cases 1–24, master's 26–28, the handler's 26–32, and *then*
master's closing paragraphs about case 12 and case 27. Both blocks' prose now sits
with their own entries.

**One addition, disclosed:** case 25 (`handler_absent`, a warning) had been in the
body since before this conflict with **no listing entry** — the packet asks for a
file that reads as one sequence with no gaps, and a body case absent from the
listing is a gap. Six comment lines were added at the top. No assertion was touched.

---

## 3. The one thing that was not a renumbering: three `trap`s, and a file left behind

This is the part of the merge that was a real hazard rather than bookkeeping, and it
is why the merged run was verified for leaked files rather than only for its exit
code.

Both packets clean up their throwaway copies of the checker by **re-registering the
EXIT trap**:

- case 24 (base, `core-account-scope-contradiction`): `trap 'rm -rf "$work" "$disabled_checker"' EXIT`
- case 28 (master, `core-stale-declaration-01`): the same, plus a forward reference to the handler's copy name
- case 31 (handler): the same

**A second `trap ... EXIT` replaces the first; it does not add to it.** Case 24 runs
before both blocks, so the last registration won, and at exit the trap removed
`$work` and whatever `$disabled_checker` happened to hold — which by then was the
handler's path. Master's copy, `harness/_account_scope_registration_disabled.py`,
survived every run. Measured, not reasoned: after one run of the resolved file the
tree carried a **133KB untracked file** in `harness/`.

It was silent for a second reason worth recording: `tests/test_specs.py`'s
`_harness_modules()` skips every `*.py` whose name ends in `_disabled.py`, so the
throwaways are invisible to the arity suite whether or not they are present. The
leak could not have been caught by any test in this repository.

**Repair, and the reasoning:** both copies are now named once at the top, beside the
original `trap` the file already had, and each case only assigns `$disabled_checker`:

```bash
disabled_checkers="$harness_dir/_account_scope_registration_disabled.py $harness_dir/_account_scope_check_disabled.py"
trap 'rm -rf "$work" $disabled_checkers' EXIT
```

Declaring it before the first copy is written also covers a run interrupted between
two cases. **No assertion was weakened**: the three `trap` lines removed were
cleanup, and each case still builds, patches and runs its own copy exactly as
before. Case 24's comment said the copy is "deleted immediately", which is no longer
true — it is removed by the one trap at exit — so that sentence was corrected rather
than left as a small lie.

Verified: `harness/` after a run contains only `account_scope_check_disabled.py`,
which is **committed** (see §7) and pre-existing.

---

## 4. The proof

`bash harness/tests/account_scope_self_test.sh`

```
--- case 26: the registration commented out, declaration and floor untouched
  red, named account-scope.registration-commented, silent on not-account-scoped GET /healthz

--- case 27: the same repository with the floor lowered — the check alone must hold it
  red, named account-scope.registration-commented, silent on account-scope.surface-thin
  listed                   registration_commented_floor_lowered

--- case 28 (THE BREAKING): with the registration check deleted, the defect passes
  clean, with the check gone  registration_check_disabled

--- case 29 (control): the go_handlers fixture, unbroken, which must be CLEAN
  clean                    go_control

--- case 30: a BARE handler symbol resolves, and so does one already resolved
  clean, and both rows read  healthz, livez

--- case 31 (THE BREAKING): with the bare-symbol search deleted, /healthz is unreadable again
  the defect is back         healthz is unreadable with the search gone

--- case 32 (THE BREAKING): a PARAMETER is not a definition, and the guard is what stops the
  search returning one
  nothing, and the guard is what does it
    shipped:   NOTHING
    unguarded: RESOLVED internal/httpapi/probes.go

--- case 33: /readyz is readable — the callee, not its argument
  clean, and the row read   readyz

--- case 34 (THE BREAKING): with the candidate list deleted, /readyz is unreadable again
  the defect is back         readyz is unreadable with the list gone

--- case 35 (THE DIRECTION): the INNERMOST candidate wins, so a middleware does not stand
  in for the handler it wraps
  innermost first, and it is right both ways
    readyz  -> o.handleReadyz      (outer; `checks` is not a definition)
    wrapped -> o.handleWrapped     (inner; not the middleware at :83)

43 passed, 0 failed
```

`36 + 7 = 43`, exactly. Master's 36 are all still there and no case changed shape;
the seven added passes are the handler's seven cases, one pass each.

### 4.1 The two named THE BREAKING cases, reproduced by hand

The script printing a pass is evidence; it is not the same as the defect being
demonstrable. Both were therefore reproduced outside the script, against the merged
checker, so the merge cannot be hiding a case that only passes because of where it
sits in the file.

**Case 28 — the registration check deleted from a copy of the checker.** Repository:
a copy of `fixtures/account-scope/conforming` with `/healthz`'s registration
commented out and `minimum: 4` lowered to `3`.

| checker | exit | said |
| --- | --- | --- |
| the real, merged one | **1** | `FAIL account-scope.registration-commented: healthz: registeredAt points at internal/httpapi/router.go:11, which is a comment naming /healthz rather than a line that registers it — the entry point is not mounted` |
| copy with `found.extend(registration_findings(label, entry, claim))` deleted | **0** | `OK …: 0 failure(s), 1 warning(s)` — and `registration-commented` appears **0** times |

**Case 34 — the handler-resolution logic deleted from a copy.** Repository: the new
`fixtures/account-scope/go_handlers`, whose `/readyz` line is
`r.Get("/readyz", o.handleReadyz(checks))`.

| checker | exit | `contradiction-unreadable` warnings |
| --- | --- | --- |
| the real, merged one | 0 | **0** |
| copy with `_handler_candidates` and the candidate loop removed | 0 | **1** — `readyz: … the handler could not be resolved to a file in this repository` |

Three further red proofs in the merged file also pass on their own terms: **case 24**
(contradiction check deleted), **case 31** (bare-symbol search deleted) and **case
32** (the definition guard removed — `shipped: NOTHING` vs
`unguarded: RESOLVED internal/httpapi/probes.go`). **Case 35** additionally pins its
own premise (`requireSession` must still be at `probes.go:83`), so a fixture edit
cannot make it pass vacuously.

---

## 5. The other three adopters, and identity's third defect

Run from the worktree; exit codes read directly, not through a pipe.

| repository | exit | verdict | before the merge (`master`'s checker) |
| --- | --- | --- | --- |
| `../identity` | **0** | `OK … 0 failure(s), 1 warning(s)` | 0, but **3** unreadable warnings |
| `../site` | **0** | `OK … 0 failure(s), 1 warning(s)` | 0, 1 warning — unchanged |
| `../parlor` | **0** | `OK … 0 failure(s), 1 warning(s)` | 0, 1 warning — unchanged |
| `../guard` | **1** | `FAIL account-scope.undeclared: hono registers GET /v1/me at src/index.ts:187, which is in a file surface.sources names and which no entry point covers` | 1, identical finding |

**identity's one remaining `contradiction-unreadable` is the Go path constant**, and
it is a third, separate defect which this merge deliberately leaves as a finding:

```
WARN account-scope.contradiction-unreadable: social-login-callback: declared accountScoped:
false and this checker could not read the code behind it — no registration on the
declared surface matched this row
```

`identity/internal/httpapi/oauth.go:162` registers
`r.Get(socialLoginPrefix+"/{provider}/callback", o.handleSocialCallback)`: the path is
built from a **constant**, and core's chi recogniser requires the path expression to
begin with a string literal. It is the same shape as the fixture's deliberately
omitted `/internal/whoami` (`r.Get(probePrefix+"/whoami", …)`), which the fixture
documents in place. Not fixed here — see §6.

The merge is also what makes identity's number go **down**, from 3 to 1: master's
checker could not resolve `healthz` or `readyz` either. That is the clearest single
piece of evidence that both halves of the checker survived the merge.

**guard's exit 1 was not weakened.** The finding is byte-identical before and after,
`surface.sources` still names the file, and nothing in the merged checker touches
the hono recogniser. Six of guard's warnings are `contradiction-unreadable` for TS
handlers that resolve outside `surface.sources`; that count is also unchanged, so
the merge neither caused nor hid them.

---

## 6. `bin/prime`

```
bin/prime exit=0    (56s wall clock)

==> the gate is declared, and the declaration is true about this tree
OK …: 0 failure(s), 1 warning(s)
==> every tombstoned property name is still reserved
OK …: 0 failure(s)
299/299 passed
==> the gate checker can fail — its own red proof, on python 3.14.7
    18 breakages red naming their finding, 7 warning cases green, 12 real-workflow
    spellings accepted, 4 extractor assertions, 3 colour-greens, 2 colour reds,
    the control green, and 0 skipped
==> the contract's numeric surface is safe across six languages
==> the reserved checker can fail — its own red proof, on python 3.14.7
    6 breakages red naming their finding, 2 controls green
==> no test in this suite can delete another test's fixtures
==> db_isolation red proof: 3 breakages red naming their finding, 5 clean controls,
    8 passed, 0 failed
==> the account-scope checker can fail — its own red proof, on python 3.14.7
    43 cases and 0 failed, every red one naming the finding it planted
```

Note the last line: `bin/prime` **runs** this proof and **reads its report**, so the
43 is read out of the proof's own footer rather than assumed, and its floor of 32 is
cleared by 11.

---

## 7. What was deliberately not done

| not done | why |
| --- | --- |
| **Merged to `master`** | The packet reserves that for the manager. The branch is ready to merge. |
| **Pushed, or created a remote** | Never, per `AGENTS.md`. |
| **Touched `harness/account_scope_check.py`** | Not needed: it auto-merged and both fixes are live (§1, §5). The packet allowed an edit only if a conflict forced one. |
| **Fixed identity's path constant** | It is a recogniser limitation, it is a *third* defect, and `REPORT-core-handler-resolution-01.md` §4 already argues why fixing it inside this packet would be wrong. A merge is not the place to take it on. |
| **Weakened anything to make a case pass** | Nothing was skipped, retried or loosened. Every one of the 43 passes is an assertion that was already in one of the two branches. |
| **Renumbered master** | See §2: master's numbers are on `master` and in the shipped checker's docstring. |
| **Touched `harness/account_scope_check_disabled.py`** | Pre-existing, committed, and *not* one of this merge's throwaways. `tests/test_specs.py`'s `_harness_modules()` documents it as a deliberate fixture — a committed copy of the checker with the contradiction check removed, kept so the difference between the two files is diffable. It is excluded from the module walk by name and from the arity suite by the `_disabled.py` suffix. Whether it should exist at all is already an open question from `REPORT-core-account-scope-unpack.md` §5 — §8, decision 2. |
| **Raised `bin/prime`'s case floor** | See §8, decision 1. |

---

## 8. Open decisions — the manager's

1. **`bin/prime`'s account-scope floor is `32`, and the merged proof delivers `43`.**
   The floor exists so "a proof that quietly stops running cases" is caught. It is
   now 11 below the truth, which is the same shape of slack `gate.proof[].minimum`
   is a ratchet against. **Recommendation: raise it to 43**, one line:
   ```bash
   # bin/prime:389
   if [ "$cases" -lt 32 ]; then
   ```
   I did not apply it: it is a gate decision, and `bin/prime` was not in this
   packet's scope. Cost of the change: one integer. Cost of leaving it: the next
   packet that loses five cases silently stays green.
2. **`harness/account_scope_check_disabled.py` is now a staler pinned fixture, and
   this merge is not what should decide its fate.** It is the checker minus
   `_check_contradictions`, committed so the two files can be diffed — except that
   `REPORT-core-account-scope-unpack.md` §5 already found it has **no reader at all**
   (case 24 builds its own copy at runtime under a `_`-prefixed name since
   `core-account-scope-contradiction`) and recommended deleting it; the manager has
   not acted. After this merge it also lacks the registration check and the handler
   resolution, so diffing it against the live file no longer shows *only* the
   contradiction change — and it was already differing by the `match_all` recogniser
   besides. **Recommendation: delete it rather than re-cut it**, which is the prior
   packet's own conclusion, and do it in a packet that owns the file rather than in
   a merge. I did not touch it: it is committed on `master`, and deleting a tracked
   file is not a merge resolution.
3. **Whether the two self-test fixtures should be one.** `conforming` and
   `go_handlers` overlap — `conforming` carries a chi router, `go_handlers` carries
   four more spellings. Both are needed: master's cases assert *absence* of
   `registration-commented` and *presence* of a stale listing, and the handler's
   cases need four handler spellings on named lines at 40 and 42. Merging them
   would couple two packets' floor counts to one fixture. **Recommendation: leave
   them apart.** No decision needed unless a third packet needs a fifth spelling —
   at which point `go_handlers` is the file to extend.
4. **A brittleness that is documented and left:** the handler's cases hard-code
   `router.go:40`, `:42`, `probes.go:83` and the literal `minimum: 4` /
   `replace("minimum: 4", "minimum: 3")`. Case 35 guards its own premise (the
   middleware's line) and case 32 guards the probe's; the `minimum: 4` literal has
   no such guard and would silently stop lowering anything if the fixture's floor
   moved. **Recommendation:** add that guard when a packet next touches
   `conforming`, not here — this merge changed neither the fixture nor the case.
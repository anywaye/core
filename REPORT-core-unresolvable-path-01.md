# REPORT-core-unresolvable-path-01

**What this packet is.** `pantry` declares its whole surface and reads **exit 1**, with
`0 undeclared` — the count that is supposed to mean "every registration was declared".
It means the opposite: all four of its registrations are
`r.Get(options.BaseURL+"<literal>", …)`, the chi recogniser drops every one of them, and
a checker that found nothing has nothing to call undeclared.

**Result.** A registration whose path prefix cannot be evaluated is now **reported as
unreadable rather than dropped and rather than guessed**. `pantry` goes from exit 1 to
**exit 0**, and the 0 is the point of the packet rather than a by-product of it: the
summary line carries a fifth number, `6 unreadable`, and the false `stale` — a FAILURE
about a route that is mounted — is gone. `identity` stays exit 0 and gains two warnings
it should have had. The self-test is **67 cases, 0 failed** (57 on master), core's gate
is green at 299/299.

| | before | after |
|---|---|---|
| `pantry` | exit 1, `1 stale`, `0 undeclared`, 7 warnings | **exit 0**, `0 stale`, `0 undeclared, 6 unreadable`, 9 warnings |
| `identity` | exit 0, 1 warning | exit 0, **3** warnings, `4 unreadable` |
| `guard` / `site` / `parlor` / `courier` | exit 0 | exit 0, **`0 unreadable`** — inert |
| `cafe` / `kit` / `core` | exit 1, `declaration-missing` | exit 1 — unchanged |
| red proof | 57 cases, 0 failed | **67 cases, 0 failed** |

Every number in that table was produced by running both checkers over the same trees;
§7 has the commands and §3 shows the 0 is earned rather than manufactured.

---

## 1. The packet's numbers are stale, and everything below is re-derived

The brief quotes `pantry/internal/api/api.gen.go:707,710,713,716` and four rows.
**pantry's checkout has moved**, and a number copied from a packet is the defect this
repository keeps refusing:

```
$ grep -n 'r\.\(Get\|Post\|Put\|Patch\|Delete\)(' internal/api/api.gen.go
852:		r.Get(options.BaseURL+"/v1/services", wrapper.ListServices)
855:		r.Get(options.BaseURL+"/v1/services/{name}", wrapper.GetService)
858:		r.Get(options.BaseURL+"/v1/services/{name}/requirements", wrapper.ListServiceRequirements)
861:		r.Get(options.BaseURL+"/v1/services/{name}/required-by", wrapper.ListServiceRequiredBy)
864:		r.Get(options.BaseURL+"/healthz", wrapper.Healthz)
867:		r.Get(options.BaseURL+"/readyz", wrapper.Readyz)
```

Six registrations and a six-row declaration. Every measurement below is against
`pantry` as it stands, and the fixture is measured out of **these** lines.

**And what the checker saw, before anything was changed:**

```
$ python3 -c "import sys;sys.path.insert(0,'harness');from pathlib import Path;\
  import account_scope_check as m;print(m.discover(Path('../pantry').resolve(),['internal/api/api.gen.go']).found)"
()
```

**Zero.** A file that registers six routes reads as a file that registers none.

---

## 2. The decision

**It produces a warning and a number, and never a path.**

`courier`'s three `kind: job` rows already get `contradiction-unreadable` — *"a
checker that cannot resolve a symbol says so rather than trusting the declaration."*
A route whose prefix is a runtime value is that situation wearing a path, and today it
is worse than a row that cannot be read, because the drop is **silent**: nothing
distinguishes "this source file registers nothing" from "this source file registers
routes in a shape I cannot read". Both return `[]`. That collapse is the defect.

Three mechanisms, because a reader can read the findings block or the last line and
both have to say it:

```
$ python3 harness/account_scope_check.py ../pantry | head -4
WARN account-scope.surface-unreadable: internal/api/api.gen.go mounts 6 registration(s) — Get — whose
    path this checker cannot evaluate, because the path argument is an expression rather than a
    string literal (line(s) 852, 855, 858, 861, 864, 867). 0 of the 6 registration(s) in
    surface.sources were read, so the `undeclared` and surface.minimum numbers below are decided over
    the ones that were, not over this surface
WARN account-scope.contradiction-unreadable: list-services: … no registration on the declared surface matched this row
WARN account-scope.contradiction-unreadable: get-service: … its registration is mounted at a line whose path
    is an expression this checker cannot evaluate, so there is no path to check this row against
…
WARN account-scope.registration-path-unreadable: get-service: registeredAt points at internal/api/api.gen.go:855,
    which DOES register a route — and its path is an expression this checker cannot evaluate, so the row is
    mounted and unverified rather than stale
```

- **`account-scope.surface-unreadable`** — per FILE, naming the lines and how many of
  the registrations in `surface.sources` were read. This is `contradiction-unreadable`
  restated for a surface instead of for a row.
- **`account-scope.registration-path-unreadable`** — per ROW, replacing a `stale` that
  was **FALSE about the code**: `stale` claims the route is gone and `api.gen.go:855`
  mounts it. That false failure is the whole of pantry's exit 1.
- **a fifth number on the summary line**, printed on **every** run:

```
OK …/pantry: 0 account-scoped, 6 not-account-scoped, 0 stale, 0 undeclared, 6 unreadable — 0 failure(s), 9 warning(s)
```

Both are `warn`, never `fail`, and that is `Report.exit_code`'s own rule rather than a
courtesy: this is *"this machine cannot answer that question"*, and
`harness/tenancy_check.py`'s header refuses to make that a failure for the reason that
failing on it gets the checker switched off — which leaves the fleet with no boundary
check instead of an incomplete one.

### The alternative this EXTENDS rather than reverses

`REPORT-core-hono-inline-01.md` §3 measured the identifier-first recogniser and left it
alone: recognising `r.Get(socialLoginPrefix+"/{provider}/callback", …)` would need
`socialLoginPrefix` and `oidc.PathLogin` resolved, and *a recogniser that guesses them
would be worse than one that cannot see them*. That judgement is right and it stands.

What this packet does is ask what the **unresolvable** half produces, and the answer is
the same for both halves: **name it**. `concatenated_path`'s `{}` convention already
covers an unreadable term in the MIDDLE of a literal path —
`/v1/accounts/{accountID}/{}/audit-log`, decidable and honest. A prefix *before* the
first literal is a different question and gets the same treatment: a name, not a value.

And a `const` gets **the same warning**, which is what stops this from being "guessing
is fine when the value happens to be lying next to you":

| prefix | what it is | answer |
|---|---|---|
| `probePrefix`, `socialLoginPrefix` | a `const`; the value IS in the tree | `registration-path-unreadable` + `surface-unreadable` |
| `options.BaseURL` | a struct field the caller fills from configuration; there is NO value in any tree | **the same two findings** |

Self-test **case 57** puts a `const` on a declared row and requires the identical
answer. A rule that behaved differently for the const would be a rule that guesses
harder when it happens to be able to.

---

## 3. The forbidden move, measured rather than asserted

The brief forbids resolving `options.BaseURL` by looking up its default. **There is no
default to look up, and the tree says so:**

```
$ grep -rn 'HandlerFromMuxWithBaseURL' ../pantry --include='*.go'
../pantry/internal/api/api.gen.go:826:func HandlerFromMuxWithBaseURL(si ServerInterface, r chi.Router, baseURL string) http.Handler {
$ … | grep -vc 'func HandlerFromMuxWithBaseURL'
0
```

**Zero call sites.** The generator emits a function whose entire purpose is to set the
prefix, and nothing in pantry calls it. The field is exported and settable:

```
$ sed -n '811,818p' ../pantry/internal/api/api.gen.go
type ChiServerOptions struct {
	BaseURL          string
	BaseRouter       chi.Router
	…
$ grep -n 'BaseURL' ../pantry/internal/httpapi/httpapi.go
(no mention of BaseURL in internal/httpapi/httpapi.go)
```

pantry's own `New` never sets it, so **today** it is the zero value `""` — and here is
the measurement that makes "today" the whole of it. `chi.Walk`, on pantry's own router:

```
$ cd /tmp/pantry-walk && go test ./internal/httpapi/ -run TestPrintWhatTheRouterServes -v
MOUNTED GET /healthz
MOUNTED GET /readyz
MOUNTED GET /v1/services
MOUNTED GET /v1/services/{name}
MOUNTED GET /v1/services/{name}/required-by
MOUNTED GET /v1/services/{name}/requirements
```

**One line** — `BaseURL: "/api",` in `ChiServerOptions` — and the same router serves
something else entirely (on a copy of pantry, `go.mod` and all):

```
MOUNTED GET /api/healthz
MOUNTED GET /api/readyz
MOUNTED GET /api/v1/services
MOUNTED GET /api/v1/services/{name}
MOUNTED GET /api/v1/services/{name}/required-by
MOUNTED GET /api/v1/services/{name}/requirements
```

That is the "default that happens to match" in its purest form: `chi.Walk` and a
literal-tail recogniser agree **today** and disagree the moment a deployment sets the
field it is named after. A checker that resolves the prefix has published a claim about
a deployment it cannot see.

---

## 4. What the alternatives do, measured on copies

Both were applied to a **throwaway copy** of the checker; the shipped file is untouched.

### Option A — match on the literal tail

The smallest possible change: let the chi recogniser's first term be an expression, so
`concatenated_path` finds the first `/`-prefixed literal and drops the prefix that is
not there. **One line.** It works — pantry goes green, six rows matched:

```
$ python3 harness/_optA.py ../pantry | tail -1
OK …/pantry: 0 account-scoped, 6 not-account-scoped, 0 stale, 0 undeclared, 6 unreadable — 0 failure(s), 2 warning(s)
```

**And on a deployment with a prefix it is wrong in the direction this whole packet
exists to prevent.** One line — `BaseURL: "/api",` — on a **copy** of pantry, and the
router serves `/api/v1/services` instead of `/v1/services`. Raise pantry's floor to
`6`, the number the router actually serves, and the two checkers part company:

| `/api` tree, `surface.minimum: 6` | what it says |
|---|---|
| **pantry's own `chi.Walk` test** | **FAIL**, all six rows: *"declares `GET /v1/services`, and the router does not serve it"* |
| **Option A** | **exit 0**, 2 warnings — the floor is satisfied by **six paths it invented** |
| **core's shipped checker** | **exit 1**, `surface-thin`: *"the declared sources register 0 entry point(s) … this floor is not being violated, it is unfalsifiable"* |

**Option A turns an honest exit 1 into a false exit 0.** That is "a coverage number
manufactured out of routes nobody saw" in its purest form, and it is not this packet's
invention: it is what happens the moment unreadable registrations are counted instead
of named. Nine warnings become two, because six routes stopped being unreadable and
became fabrications; the declaration is right, the tree is right, and the alternative
answers both questions with a guess about a deployment.

What Option A does **not** do is become silent — the sixth number is still printed, so a
reader who knows to look can still catch it. The claim is narrower and it is the one
that holds: Option A makes `undeclared` and `surface.minimum` **decidable against
invented paths**, and a number decided against an invention is not a weaker number than
no number. It is a number pointing the wrong way.

The brief's other documented hazard, measured: the spelling `/v1/services/name`, which
pantry does **not** serve, is caught by Option A (`undeclared`, exit 1) but **not** by
the shipped checker (exit 0, `registration-path-unreadable`) — because the shipped
checker never produced a path to match it. Which is the point: the alternative is only
safe against the *wrong spelling* and silently wrong against the *right deployment*.

### Option B — report it as `undeclared`

One line in `discover`: publish each unreadable registration as a `Registered` on its
literal tail. Result on pantry, whose declaration covers **all six** routes:

```
FAIL account-scope.undeclared: chi registers Get /v1/services at internal/api/api.gen.go:852, … no entry point covers it
FAIL account-scope.undeclared: chi registers Get /v1/services/{name} at internal/api/api.gen.go:855, … no entry point covers it
… 6 in all …
FAIL …: 0 account-scoped, 6 not-account-scoped, 0 stale, 6 undeclared, 6 unreadable — 6 failure(s), 9 warning(s)
```

Six FAILUREs accusing a correct declaration of omitting its own routes. `undeclared` is
a claim about the DECLARATION, and this declaration is complete — crying wolf on correct
code, which is the failure mode that gets a guard switched off.

### Option C — leave it, and sharpen the argument

`pantry` would stay permanently uncheckable, its exit code permanently 1 on a defect in
core. That is a real state and it belongs in `notEnforced`; it is not a decision about
what a checker owes a reader who has already declared their surface honestly.

---

## 5. Why pantry's exit 0 is honest, and not a recogniser that stopped looking

Four independent checks, each of which fails if the change is the wrong one.

**1. The number that was ambiguous is now on the line.**
`0 undeclared, 6 unreadable` cannot be read as coverage. Before, the two readings — "no
registration was found, so none could be undeclared" and "every registration was
declared" — printed identically.

**2. `surface.minimum` still counts only what was READ.** Self-test **case 55**, green
on both sides of this packet and green on purpose: widening the floor to
`found + unreadable` would turn pantry's exit 1 into an exit 0 with `minimum: 6` and **no
warning at all** — a coverage number manufactured out of routes nobody saw. The floor's
comparison is byte-identical; only its message grew, to say *unfalsifiable* rather than
*violated*:

```
FAIL account-scope.surface-thin: the declared sources register 0 entry point(s) and surface.minimum is 4
  — and 4 further registration(s) in those sources could not be read at all, so this floor is not being
  violated, it is unfalsifiable
```

**3. The rows are still listed, at their real lines.** Self-test **case 52**. A fix that
turned the finding off would satisfy case 51 without it:

```
  not-account-scoped GET /v1/services                      (internal/api/api.gen.go:852)
  not-account-scoped GET /v1/services/{name}               (internal/api/api.gen.go:855)
  not-account-scoped GET /v1/services/{name}/requirements  (internal/api/api.gen.go:858)
  not-account-scoped GET /v1/services/{name}/required-by   (internal/api/api.gen.go:861)
  not-account-scoped GET /healthz                          (internal/api/api.gen.go:864)
  not-account-scoped GET /readyz                           (internal/api/api/gen.go:867)
```

`get-service` is no longer `stale`. It is **mounted and unverified**, which is what it is.

**4. The count itself is falsified in the direction that matters.** Self-test **case
58** deletes the line that sets it from a copy, and the copy prints the wrong zero:

```
OK …/go_runtime_prefix_no_count: 0 account-scoped, 4 not-account-scoped, 0 stale, 0 undeclared, 0 unreadable — 0 failure(s), 7 warning(s)
   the wrong zero, and it is the defect, restated in the new field
```

Which is why the count is printed **always** and not only when non-zero: an omitted
number cannot be told from a computed zero, and a checker that can print a wrong zero
about its own coverage is worse than one that prints nothing.

### And the strongest one: the honest 0 is still not a pass on pantry's routes

On the `/api` tree, pantry's own `chi.Walk` test is red and core's checker is green with
`6 unreadable`. **Core verified none of pantry's routes and says so on every line of
its output.** The exit 0 is a statement about the *declaration* — "there is nothing wrong
with this file" — and the six warnings are the statement about the *surface*. A reader
who treats exit 0 as "pantry's routes are checked" is reading it wrongly, and the fifth
number is what makes that mistake harder.

---

## 6. The self-test

**67 cases, 0 failed** — 57 on master. Ten new, on one fixture measured out of
`pantry/internal/api/api.gen.go:852-867` (with the wrapper struct renamed) plus
identity's own route-table helper.

| | fixture | what it decides |
|---|---|---|
| 50 | `go_runtime_prefix` | the control: four unreadable registrations, four correct rows, the finding named **and exit 0** |
| 51 | | NOT `stale` — the false `stale` is gone |
| 52 | | and the row is **still listed**, at line 57 — so a fix that turned the finding off cannot satisfy 51 |
| 53 | | **THE BREAKING**: delete the fifth claim verdict from a copy, and `stale` is back |
| 54 | | **THE BREAKING**: delete the per-file report, and the run is green with only the count left saying so |
| 55 | | `surface.minimum: 4` is still `surface-thin` — **the control on case 50's green** |
| 56 | | `t.chiRouter.Get(pattern, traced(h))` is NOT this finding — 1 line here, 4 in identity |
| 57 | `go_handlers` | the **resolvable** half: a `const` prefix on a declared row gets the same warning |
| 58 | | **THE BREAKING**: delete the count and the summary prints `0 unreadable` over four |

Cases 55 and 56 are green **before** and **after**, and that is what a control is for.
55 is the case that fails if anyone widens the floor to `found + unreadable`.

### Three things this suite got wrong on the way, written down because they are the file's purpose

**A fixture's prose is measured against its own line numbers.** Rewriting `go_handlers`'
comment block — the paragraph explaining why `/internal/whoami` is not declared — moved
all four of its registrations by ten lines. All four rows went `stale` and cases 29-35
failed with `READYZ RESOLVED ELSEWHERE NOTHING`, which has nothing to do with which symbol
wins. Case 35 now reads its two line numbers **out of the fixture's own declaration**
rather than writing `40` and `42` down, so it cannot drift again.

**The first version of case 57 was satisfied by the accident this packet is about.**
`/internal/whoami`'s last canonical segment is `whoami`, and `_mentions_on`'s second test
is `canonical(path).split("/")[-1] in text` — so the word `whoami` in its own registration
line passes the substring test and the row prints as mounted without the checker ever
having matched it. That is **why three of pantry's six rows go quiet today and only
`get-service` goes red**, and it is the same accident `pantry/account_scope.yml` §3
documents. So case 57 appends a route whose path **ends in a parameter**, whose last
canonical segment is `{}`, which appears in no Go file.

**Case 54 needed two cases, and the first one was not the case.** Deleting both
mechanisms does not make the fixture green: deleting the claim branch puts
`get-service` back to `stale`, which is exit 1. The defect that passes clean is the
*surface* half on its own — and case 58 exists because the two halves fail differently.
The grep is on `undeclared, N unreadable` and not on `unreadable`, because
`contradiction-unreadable` is four lines of that very output and is **not** the defect.

---

## 7. The fleet, re-run

```
$ cd cafaye && ls */account_scope.yml | sed 's#/account_scope.yml##'
courier  guard  identity  pantry  parlor  site
```

| service | declares | before (`5fd6c5c`) | after (this branch) |
|---|---|---|---|
| `identity` | 42 rows | exit 0 — 17 scoped, 25 not, 0 stale, 0 undeclared, **1** warning | exit 0 — 17 scoped, 25 not, 0 stale, 0 undeclared, **4 unreadable**, **3** warnings |
| `guard` | 7 rows | exit 0 — 1 scoped, 6 not, 0 stale, 0 undeclared, 6 warnings | exit 0 — …, **0 unreadable**, 6 warnings — **inert** |
| `site` | 6 rows | exit 0 — 0 scoped, 6 not, 0 stale, 0 undeclared, 1 warning | exit 0 — …, **0 unreadable**, 1 warning — **inert** |
| `parlor` | 6 rows | exit 0 — 0 scoped, 6 not, 0 stale, 0 undeclared, 1 warning | exit 0 — …, **0 unreadable**, 1 warning — **inert** |
| `courier` | 19 rows | exit 0 — 9 scoped, 10 not, 0 stale, 0 undeclared, 3 warnings | exit 0 — …, **0 unreadable**, 3 warnings — **inert** |
| `pantry` | 6 rows | **exit 1** — 0 scoped, 5 not, **1 stale**, 0 undeclared, 7 warnings | **exit 0** — 0 scoped, 6 not, **0 stale**, 0 undeclared, **6 unreadable**, 9 warnings |
| `cafe` | no file | exit 1 — `declaration-missing` | exit 1 — unchanged |
| `kit` | no file | exit 1 — `declaration-missing` | exit 1 — unchanged |
| `core` | no file | exit 1 — `declaration-missing` | exit 1 — unchanged |

**Six declare and three do not**, and the three that do not are unchanged: a service with
no `account_scope.yml` is `account-scope.declaration-missing`, a FAILURE, and this packet
does not make a missing declaration cheaper.

**`identity` is the resolvable half and it got quieter in the right direction:** 1
warning → 3, `0 unreadable` → `4 unreadable`, exit 0 → exit 0. Its two
`surface-unreadable` findings name `internal/httpapi/oauth.go:161,162` and
`oidc.go:142,143`, and each says *41 of the 45 registration(s) in surface.sources were
read* — which is the sentence that makes the other four a fact about the checker rather
than a gap in the reader's attention. Nothing about its counts of scoped and unscoped routes moved, which
is the property that matters: nothing was reclassified to get there.

### Tallies kept separate from passes

`self-test 57 → 67 cases, 0 failed`. `suite 299/299 passed`. `gate green, exit 0`.
Those are passes. The measurements above are **tallies** and they do not say anything is
proven: `identity`'s 42 rows are 4-unreadable and this packet did not read the other 9
routes whose paths are bare package constants, and `pantry`'s 6 rows are 6-unreadable
and this packet did not read **any** of them. What it did is stop reporting those two
numbers as coverage.

---

## 8. What is still open

**D46** in `DECISIONS.md` records the decision, the three alternatives with their
measurements, and the cost of flipping each.

- **No path prefix is resolved, and the unresolvable half cannot be.** In
  `notEnforced` with the counts: 10 registrations with a literal behind an unevaluable
  prefix (4 identity, 6 pantry), plus **9 real identity routes whose paths are bare
  package constants** (`oidc.go:134,135,137,138,139,140,156,157,158`) which this checker
  cannot see in any form. That is the resolvable half, and closing it means resolving an
  identifier's value through the module index — which is the follow-up
  `REPORT-core-hono-inline-01.md` §3 already named.
- **A path argument with no string literal in it** is not this finding.
  19 lines in identity, of which **4 are not route registrations at all**
  (`o.tenancy.Get(r.Context(), …)` is a map field's method), 4 are `register`'s own
  `pattern` parameter, 2 are `o.panicOnRoute`/`o.parameterizedRoute`. Case 56 is the
  control on that width, because without it the warning fires on four lines of correct
  code in the repository this format was written for.
- **A scoped row behind an unevaluable prefix is not `scoping-bypassed`-checked** — that
  finding reads the registration line through the recognisers and none of them matches.
  **0 rows in this fleet**, so it is latent, and the day a service declares a `true` row
  behind `options.BaseURL` the bypass check silently stops existing for it.
- **`pantry`'s `account_scope.yml` still says `minimum: 0`**, and its header still
  documents `api.gen.go:707-716` and four rows. **I did not touch it**: a declaration
  edited to suit the checker inverts the relationship and hides the finding, and the
  brief says to say so loudly and stop. What it should say is on record above — six
  routes at 852-867 — and correcting a service's own documentation is that service's
  commit.

---

## 9. Commits

| | |
|---|---|
| `4123ab2` | the red proof, before the fix — one fixture, ten cases, **59 passed / 6 failed** against `5fd6c5c`'s checker |
| `30e3a75` | the decision — `unreadable_registrations`, `Surface`, `surface_findings`, the fifth claim verdict, two findings, the count — **67 cases, 0 failed**, 299/299 |
| `e68d852` | D46, and the decision with its three refusals and three costs of flipping |

Not merged and not pushed, as instructed.

---

## 10. Reproducing every number in this report

```bash
core=/Users/kaka/Code/any/moon/cafaye/wt-m39-core-unrespath-01
py=/opt/homebrew/bin/python3.12          # any 3.9+; mise's shim is fine too
cd "$core"

# 0. what the checker saw before, on pantry as it stands
$py - <<'EOF'
import sys; sys.path.insert(0,'harness')
from pathlib import Path; import account_scope_check as m
print(m.discover(Path('../pantry').resolve(), ['internal/api/api.gen.go']).found)
EOF

# 1. the fleet, before and after. The before is in 4123ab2^:
git show 4123ab2^:harness/account_scope_check.py > harness/_before.py  # == 5fd6c5c
                                                                 # beside the real
                                                                 # one: the module's own
                                                                 # import guard refuses to
                                                                 # run a copy that cannot
                                                                 # reach cafaye_contract
for r in identity guard site parlor courier pantry cafe kit; do
  for c in _before account_scope_check; do
    out=$($py "harness/$c.py" "../$r" 2>&1); rc=$?
    printf '%-9s %-22s exit=%s  %s\n' "$r" "$c" "$rc" \
      "$(printf '%s' "$out" | grep -E '^(OK|FAIL) ')"
  done
done
rm harness/_before.py

# 2. the proofs and the gate
bash harness/tests/account_scope_self_test.sh       # 67 passed, 0 failed
bin/prime                                            # 299/299, gate green

# 3. the forbidden move: the prefix is a parameter with no call site
grep -rn 'HandlerFromMuxWithBaseURL' ../pantry --include='*.go'
grep -n 'BaseURL' ../pantry/internal/httpapi/httpapi.go   # (no match)

# 4. the ground truth, and the /api arm — on a COPY, never on pantry
rm -rf /tmp/pantry-walk && cp -R ../pantry /tmp/pantry-walk
cat > /tmp/pantry-walk/internal/httpapi/zz_walk_print_test.go <<'GO'
package httpapi

import (
	"net/http"
	"testing"

	"github.com/go-chi/chi/v5"
)

func TestPrintWhatTheRouterServes(t *testing.T) {
	router := New(nil).(chi.Router)
	_ = chi.Walk(router, func(method, route string, _ http.Handler,
		_ ...func(http.Handler) http.Handler) error {
		t.Logf("MOUNTED %s %s", method, route)
		return nil
	})
}
GO
(cd /tmp/pantry-walk && go test ./internal/httpapi/ -run TestPrintWhatTheRouterServes -v -count=1)
# …then add `BaseURL: "/api",` beside `BaseRouter: r,` in
# /tmp/pantry-walk/internal/httpapi/httpapi.go and run it again.

# 5. the rejected alternatives, each on a throwaway copy of the CHECKER
#    §4 has the two one-line patches; /tmp/optA.py and /tmp/optB.py are them.
```

### Two things this report's own numbers do not show

- **`identity`'s 9 constant-prefixed routes** are not in any count above, because this
  checker cannot see them at all and this packet did not change that.
- **`pantry`'s exit 0 is not a claim about pantry's routes.** It is a claim about
  `pantry/account_scope.yml`. The six `unreadable` registrations are the absence of the
  other claim, and they are on every line of the output for exactly that reason.

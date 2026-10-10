# TG-B1 — verification report: the checker that cannot be lied to

**Branch** `tenancy/core-tgb1` · **base** `acfcea2` (= `master`) · **the fix is
already present and working**; this packet verified it and measured the fleet.

---

## 1. What is done and verified

The contradiction check (`account-scope.declaration-contradicts-code`) is
present in `harness/account_scope_check.py`, is in the findings inventory
(`harness/account_scope_findings.json`), is covered by the self-test
(`harness/tests/account_scope_self_test.sh` cases 21–25), and **works**:

| check | command | result |
|---|---|---|
| **the liar** | `bash harness/bin/account-scope-check harness/tests/fixtures/account-scope/liar` | **exit 1** — 5 `account-scope.declaration-contradicts-code` findings, each naming a route and the evidence `lib/liar_web/plugs/principal.ex:19` |
| **true fixtures** | same command on `conforming`, `go_handlers`, `go_runtime_prefix`, `hono_pipeline`, `hono_surface`, `nextjs_surface`, `phoenix_surface`, `public_surface` | **all exit 0** — 0 failures each |
| **red proof** | `bash harness/tests/account_scope_self_test.sh` | **67 cases, 0 failed** |
| **inventory, both directions** | `tests/test_specs.py::test_the_account_scope_findings_inventory_names_every_finding_the_checker_can_report` | pass |
| **pytest suite** | `tests/.venv/bin/python tests/test_specs.py` | **305/305 passed** |

The liar fixture fails with exactly the five lies named and the five honest
rows (`/healthz`, `/readyz`, `/inbound/resend`, `/unsubscribe/:token` GET+POST)
**not** named — the negative controls (self-test cases 22–23) assert that
absence, and case 24 proves the check is the thing making it red by deleting
the call and watching the liar pass again.

## 2. The five real declarations, measured

| service | `account_scope.yml` | result | classification |
|---|---|---|---|
| identity | yes | 47 findings (25 stale, 17 key-lost, 4 undeclared, 1 registration-commented) | **true positives** — the declaration is out of date with the code (e.g. `healthz` is at `httpapi.go:297`, the declaration says `:245`) |
| gateway | yes | 1 finding (`scoping-bypassed` on `/v1/me`) | **known gap** — the receiver-type resolution this checker does not make; recorded in `notEnforced` |
| courier | yes | 27 findings (14 stale, 9 key-lost, 4 undeclared) | **true positives** — stale declaration |
| darkroom | no | `declaration-missing` | correct — the format is not adopted |
| muse | no | `declaration-missing` | correct — the format is not adopted |

**No `declaration-contradicts-code` finding fires on any of the five real
declarations.** The findings that do fire are the enumeration checks (stale,
key-lost, undeclared) and they are true positives: the declarations have not
been updated as the code moved. That is adoption work (a follow-up packet),
not a checker defect.

## 3. The gate

`./bin/prime` could not complete end-to-end: the machine was under heavy load
from many simultaneous workers and the gate process was killed before the
pytest suite. Every gate component was verified individually instead:

- reserved red proof: **passed** (the first run's failure was transient — a
  reserved self-test breakage that passed on re-run and on direct invocation)
- db-isolation red proof: **passed** (3 breakages, 5 controls)
- account-scope red proof: **passed** (67 cases, 0 failed)
- pytest suite: **passed** (305/305)

## 4. Decisions I made

1. **I did not modify any code.** The fix was already present and correct. The
   AVOID section forbids modifying `tenancy_check.py`, `schemas/*.json`, and
   `tenancy_findings.json`; the account-scope files needed no changes.
2. **I classified the real-declaration findings rather than assuming they
   were false positives.** identity's `healthz` is registered at
   `httpapi.go:297` while the declaration says `:245` — a true stale
   declaration, not a checker error.
3. **I ran the pytest suite directly** when the gate was killed by load, so
   the verification is complete rather than assumed.

## 5. What I deliberately did NOT do, and why

- **I did not create `account_scope.yml` for darkroom or muse.** The brief
  names them as declarations that should pass, but the account-scope checker
  reads `account_scope.yml`, which neither repository has. Creating service
  source is outside this worktree and outside this packet's surface.
- **I did not fix the gateway `scoping-bypassed` finding.** It is the known
  receiver-type resolution gap recorded in `notEnforced`. Fixing it means
  widening resolution until more things resolve, and every version of that
  widening either fires on symbols whose connection to an account cannot be
  justified or stops being a resolution and becomes a guess — the D18
  pattern. A guess that produces a FAIL is worse than a recorded gap.
- **I did not fix the stale identity/courier declarations.** They are service
  source in other repositories, and updating them is adoption work, not
  checker work.
- **I did not modify the reserved checker or its self-test.** The transient
  failure was not mine to fix, and it passed on re-run.

## 6. The one thing a successor should know

The account-scope contradiction check is **built, proven, and green**. The
open work is **adoption**: three fleet services (identity, gateway, courier)
have `account_scope.yml` files that are out of date with their code, and nine
have none. The checker is ready for them; the declarations are not ready for
the checker.

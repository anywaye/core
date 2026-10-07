# REPORT — core-42: behaviour tests, not framework tests

**Branch:** `worker/core-w42-frameworktests`
**Commits:** `94027d0`, `d543c8f`, `a8e2530`, `66948a6` (on top of `fcdd301`)
**Gate:** `bin/prime` green — 304/304 passed, all four red proofs green, 0 skipped.

## What the packet asked for

A rule in core's standards, a checker for the mechanical cases with a red
proof, a measured survey of the fleet, and the wiring. All four are delivered.

## The case-3 settlement — which one was wrong

The stall was case 3 (`plug_framework`): a test whose setup line is
`pipeline = MyApp.Router.__pipelines__()` and whose assertion is
`assert :authenticated in pipeline`. The old classifier carried a
`behaviour_patterns` whitelist, and `Ecto.Changeset.change` on that list matched
the setup line — so a file whose every assertion was about the framework was
classified as having a product claim.

**The classifier was wrong, not case 3.** Case 3's fixture is a framework test:
its only assertion is about the framework's routing mechanism, reached through
a variable. The whitelist was the defect — it classified files by the tokens on
any line, including setup, and it was inherently incomplete (every framework
token not on it is a misclassification waiting to happen).

The fix inverts the logic. An assertion is a framework assertion only when it
matches a framework pattern directly, **or** mentions a variable that a setup
line assigned from a framework-pattern call. Every other assertion is a product
claim, and one product claim anywhere in the file keeps the file green. The
seam is what the assertion is about, not which line the token sits on. Case 3's
expectation was correct and is unchanged; the classifier now meets it.

## The rule

`docs/framework-tests.md` — the distinction, the seam, the two failure modes,
what the checker can and cannot see, the four findings, the fleet measurement,
the red proof, and how to run it. The README docs table carries the row.

## The checker and its honest limit

`harness/framework_test_check.py` · `harness/bin/framework-test-check` ·
`harness/tests/framework_test_self_test.sh` (8 cases) ·
`harness/framework_test_findings.json` (4 findings, 2 notEnforced).

**It can** flag a test file that asserts nothing but a framework's own
behaviour — every assertion in the file is about the framework's internal
representation or its configuration.

**It cannot** tell a behaviour test that uses a test double from a framework
test. A test that drives the product and then asserts on the response, the
persisted row, or the refusal reason is a behaviour test whatever it is
written against. This is stated in the tool's own header, in the findings
inventory's `notEnforced` list, and in the doc.

It is also silent on: a model's own refusal (`assert_not event.valid?` — the
model is the product at the model level), an assertion on the response, an
assertion on an error value (a product sentinel and a framework error are
spelled the same), and `expect(...)`-spelled suites (the vitest/jest spelling
is read but not pattern-matched — the silent direction).

**A checker that flags legitimate tests is worse than no checker.** The bias is
toward silence, and the red proof's four clean controls are the ones that make
the four reds mean anything.

## The survey — measured, and every lead is legitimate

The manager's grep leads, each inspected in context:

| lead | files | verdict | why |
|---|---|---|---|
| `changeset.errors` | 3 | **behaviour** | each asserts the refusal *names a field* (`assert :account_name in fields`), which the packet lists as "a refusal with a reason". The `changeset.errors` read is the extraction mechanism. |
| `assert … Repo.` | 22 files, 69 occurrences | **behaviour** | every file drives the product and observes the persisted row (`assert Repo.get!(WebhookDelivery, id).status == :succeeded`). Highest Repo-to-assertion ratio is 13/58; no file is a Repo round-trip. |
| `Ecto.Changeset` | 7 | **behaviour** | `Ecto.Changeset.change/2` appears only as fixture setup (`|> Ecto.Changeset.change(attempt_count: …)`); the assertions are on the worker's observable effect. |
| `plug … pipeline` | 2 | **not assertions** | one is a comment ("tested without a plug pipeline"), one is a comment quoting the `plug/2` macro. |
| `Swoosh.Adapters.Test` | 6 | **behaviour** | two are comments; the rest are `Application.put_env` setup or assertions on courier's *own* `MailerAdapter.deliverable?` / `verify_boot!` — the product at the module level. |

**The checker's verdict on all nine services: 0 failures.** That is the honest
mechanical result, and it is not the same as "the fleet is clean" — the checker
sees only the mechanical cases. The survey above is the judgment layer, and it
finds no framework tests in the fleet today.

### The one false positive, found and fixed

The python pattern `assert.*patch` matched `assert … dispatched` — "patch" is a
substring of "dispatched" — and flagged a docstring in `muse/tests/test_providers.py:391`
("So a test can assert what was dispatched…") as a framework assertion. The
file-level verdict stayed green (the file has 1354 product assertions), but the
report was polluted. Fixed with `\bpatch\b`; `\bmock` keeps its trailing side
open because `mock_calls` and `call_count` are one word in Python's vocabulary.

## The demonstration on one real repo

`courier` (Elixir, 49 async test sites, the fleet's most aggressively
database-tested service):

```
$ harness/bin/framework-test-check /Users/kaka/Code/any/moon/cafaye/courier
courier  (elixir)
  framework assertions: 73
  behaviour assertions: 3125
  ok   framework patterns found, and product assertions beside them

0 failure(s)
```

It finds nothing. That is because the repo is clean, not because the checker is
blind — proved by planting a framework test in a throwaway copy:

```
$ # planted: test/courier/planted_framework_test.exs asserting on
$ # Router.__pipelines__() and changeset.errors, with no product assertion
courier  (elixir)
  framework assertions: 75
  behaviour assertions: 3125
  FAIL framework-test.changeset-assertion [fail]
  files with framework tests:
    test/courier/planted_framework_test.exs

1 failure(s)
```

The planted file is flagged and named; the 73 pre-existing framework
assertions in courier's real suite are not, because each sits beside product
assertions.

## The red proof — both directions

`harness/tests/framework_test_self_test.sh`: **8 passed, 0 failed**, 0 skipped.

**Four reds**, each naming its finding:
1. `changeset.errors` → `framework-test.changeset-assertion`
2. `Swoosh.Adapters.Test.deliver` → `framework-test.swoosh-adapter-assertion`
3. `Router.__pipelines__()` → `framework-test.plug-pipeline-assertion`
4. `assert Repo.get!(…).name == "Alice"` as the only assertion → `framework-test.repo-assertion`

**Four clean controls**:
- the unbroken fixture;
- a behaviour test **using** `Swoosh.Adapters.Test` to assert the email content;
- a behaviour test **using** `Repo.insert!` for setup and asserting the response;
- a behaviour test **using** `Ecto.Changeset.change` for setup and asserting the refusal.

## The wiring

**CI step, opt-in per service** — the tenancy precedent, not the db-isolation
one. The red proof runs as a step of core's own CI
(`.github/workflows/ci.yml`), asserted by
`test_every_framework_test_finding_is_proved_able_to_go_red`. The check itself
is opt-in: a service runs `harness/bin/framework-test-check .` against a pinned
core.

It is deliberately **not** in `bin/prime`. The db-isolation red proof is in
`bin/prime` because that checker crashed the gate before; this one is new and
has not. The tenancy red proof — the closest analogue, a new checker — is
CI-only for the same reason. If this checker ever takes the gate down, the
account-scope precedent says the red proof moves into `bin/prime` in the same
commit as the fix.

## The gate

`bin/prime` green. The suite grew 299 → 304 (five tests for the checker), and
the floor ratchet did its job: it went red on 304 collected tests against a
declared 299, and the raise to 304 is in the same commit as the tests.

```
304/304 passed
==> the red proof passed: 18 breakages went red … 0 skipped.          (gate)
==> the reserved red proof passed: 6 breakages … 2 controls green.    (reserved)
==> db_isolation red proof: 3 breakages … 5 clean controls … 8 passed, 0 failed.
==> the account-scope red proof passed: 67 cases and 0 failed.
```

## Ranked per-repo conversion packets

**None to dispatch.** The survey found no framework tests in the fleet. The
manager's leads were all legitimate uses — setup lines, refusal-name
assertions, persisted-row observations, and comments. The per-repo conversions
the packet anticipated do not exist, and that is the finding.

The follow-up worth dispatching instead: **nothing today.** If the fleet adopts
a new framework (a new HTTP router, a new ORM), the checker's `LANGUAGES` table
gains the patterns for it and the survey is re-run. The rule, the checker and
the red proof are the durable deliverable; the survey is a snapshot of a clean
fleet.

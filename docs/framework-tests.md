# Behaviour tests, not framework tests

`harness/framework_test_check.py` · `harness/bin/framework-test-check` ·
`harness/tests/framework_test_self_test.sh`

## The distinction

A **behaviour test** asserts what the *product* does for a caller: a request's
response, an observable effect, a persisted row, a refusal with a reason. It
fails when the product is wrong, and it survives a library upgrade that changes
nothing a caller can see.

A **framework test** asserts that a *library is configured*: that a plug is in a
pipeline, that `Ecto.Changeset` produced an error tuple, that a route table
contains a path, that a template rendered, that `Swoosh.Adapters.Test` received
mail. It passes while the product is wrong, and it breaks on a library upgrade
for no product reason.

The seam is whether the assertion is about **the product's contract** or about
**the library's internals**. A test that uses `Swoosh.Adapters.Test` to assert
*the notice reached the person at the right address with a working link* is a
behaviour test using a framework's test double. The adapter is the observation
mechanism, not the subject.

## The two failure modes

1. **A test that cannot fail for the reason it names.** It passes while the
   product is wrong, because it is asserting the library did something rather
   than the product did something. `assert :authenticated in pipeline` is green
   whether or not the endpoint refuses an anonymous caller — the pipeline is
   the framework's routing mechanism, not the product's contract.
2. **A test that breaks on a library upgrade for no product reason.** It is
   coupled to the framework's internal representation rather than to the
   product's observable contract. `assert {:error, changeset} = Repo.insert(…)`
   fails when Ecto changes its error tuple shape, and nothing a caller can see
   has changed.

## What the checker can and cannot see

It reads source, so it can only see what is written down. It flags a test
file that asserts nothing but a framework's own behaviour — every assertion
in the file is about the framework's internal representation or its
configuration. It **cannot** tell a behaviour test that uses a test double
from a framework test: a test that drives the product and then asserts on the
response, the persisted row, or the refusal reason is a behaviour test
whatever it is written against, and one product assertion anywhere in the file
is enough to keep the file green.

So this checker is deliberately conservative. It flags the mechanical cases
and stays silent on the ones that require judgment. **A checker that flags
legitimate tests is worse than no checker: it teaches people to ignore it.**

What it is silent on, by design:

* A behaviour test that observes the product through the framework's handle
  (`assert Repo.get!(Row, id).field == value` after driving the use case).
  The packet calls this "a persisted row"; the Repo read is the observation
  mechanism, not the subject. Only a file whose *every* assertion is a Repo
  read — a round-trip test of the framework itself — is flagged.
* A model's own refusal (`assert_not event.valid?`,
  `assert_includes event.errors.attribute_names, :field`). The model is the
  product at the model level; its errors are what a controller serializes
  into the 422. Asserting the refusal names a field is "a refusal with a
  reason", which is behaviour.
* An assertion on the response (`assert response.status_code == 401`). The
  status and the headers are what the caller sees.
* An assertion on an error value (`assert err != nil`, `assert err == E`).
  A product sentinel and a framework error are spelled the same; telling them
  apart is a judgment, and the bias is toward silence.
* `expect(...)` — the vitest/jest spelling. This checker recognises the
  `assert`/`refute` keyword; an expect-style suite is read but its assertions
  are not pattern-matched, which is the silent direction.

## What the checker reports

```
$ harness/bin/framework-test-check ..
courier  (elixir)
  framework assertions: 73
  behaviour assertions: 3125
  ok   framework patterns found, and product assertions beside them

0 failure(s)
```

A file is flagged only when **every** assertion in it is a framework assertion.
One product assertion, anywhere in the file, means the file is making a claim
about the product, and the framework assertions in it are observations rather
than the subject.

The four findings, and the seam each one guards:

| finding | flags | the behaviour test instead |
|---|---|---|
| `framework-test.changeset-assertion` | `changeset.errors`, `traverse_errors`, `%Ecto.Changeset{}` | the refusal reason, the error message, or the fact that no row was written |
| `framework-test.swoosh-adapter-assertion` | `Swoosh.Adapters.Test.deliver`, `assert.*mock/patch/spy` | what the recipient sees: the content, the delivery status, the recorded notification |
| `framework-test.plug-pipeline-assertion` | `plug … pipeline`, `__pipelines__`, route tables | the response status, the response body, the refusal reason |
| `framework-test.repo-assertion` | `assert Repo.…` as the primary assertion | the API response, the observable side effect, the persisted state through the product's own query interface |

## The fleet, measured

Run across all nine services with test suites, the checker reports **0
failures**. That is the honest mechanical result, and it is not the same as
"the fleet is clean": the checker sees only the mechanical cases. The survey
in `REPORT-core-framework-tests-01.md` names the instances a person must judge,
and every one of the manager's measured leads — `changeset.errors` in 3 files,
`assert … Repo.` in 22, `Ecto.Changeset` in 6, `plug … pipeline` in 2,
`Swoosh.Adapters.Test` in 6 — is a **legitimate** use on inspection. The
leads are where to look, not what to find.

## The red proof

`harness/tests/framework_test_self_test.sh` — 8 cases, and the counts are
asserted by `bin/prime`, not just printed.

**Four reds**, each naming its finding:

1. a test that asserts on `changeset.errors` — `framework-test.changeset-assertion`;
2. a test that asserts on `Swoosh.Adapters.Test.deliver` —
   `framework-test.swoosh-adapter-assertion`;
3. a test that asserts on `Router.__pipelines__()` —
   `framework-test.plug-pipeline-assertion`;
4. a test whose only assertion is `assert Repo.get!(…).name == "Alice"` —
   `framework-test.repo-assertion`.

**Four clean controls**, which are the ones that make the reds mean something:

* the unbroken fixture;
* a behaviour test **using** `Swoosh.Adapters.Test` to assert the email content;
* a behaviour test **using** `Repo.insert!` for setup and asserting the response;
* a behaviour test **using** `Ecto.Changeset.change` for setup and asserting
  the refusal.

The clean controls are not optional. This checker's most likely failure is a
false positive on a legitimate behaviour test that happens to use a framework's
test double, and a checker that does that teaches people to ignore it.

## Running it

```bash
harness/bin/framework-test-check .            # this service
harness/bin/framework-test-check ..           # the fleet
harness/bin/framework-test-check --explain    # every finding, and its fix
bash harness/tests/framework_test_self_test.sh # 8 cases: 4 reds, 4 clean
```

Exit codes are the whole contract: **0** clean, **1** a finding, **2** the
check could not run — never collapsed into 1.

`core/bin/prime` runs the red proof and reads the report rather than trusting
the exit code. The check itself is opt-in per service, like the tenancy job:
a service runs `harness/bin/framework-test-check .` in its own CI against a
pinned core.

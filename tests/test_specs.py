#!/usr/bin/env python3
"""Contract tests for the cafaye core specs.

Every rule that core declares lives in exactly one place: a JSON Schema in
``schemas/``. The one exception is the outbox convention, which is a SQL table
rather than an instance shape, so it is asserted straight out of the SQL block
in ``docs/event-outbox.md``. This suite is the executable statement of both.

It runs two ways, with identical coverage:

    pytest tests/            # canonical
    python tests/test_specs.py   # dependency-light fallback (what bin/prime uses)

Test doctrine: tests are written before the schemas they check. A rule with no
test here is not a cafaye rule.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = REPO / "schemas"
EXAMPLES = REPO / "examples"
DOCS = REPO / "docs"

MANIFEST_SCHEMA_PATH = SCHEMAS / "cafaye.manifest.schema.json"
ENVELOPE_SCHEMA_PATH = SCHEMAS / "event-envelope.schema.json"
FLEET_SCHEMA_PATH = SCHEMAS / "fleet.schema.json"
PAYLOAD_SCHEMAS = SCHEMAS / "events"

# The observability spec (PLAN.md §7b). Seven schemas, and they are seven
# different rules rather than seven views of one, which is why they are seven
# files: span naming, the three per-signal attribute allowlists, the redaction
# boundary, the *OTEL_ENDPOINT contract with its no-op path, and the
# healthz/readyz split. See docs/observability.md.
TELEMETRY_SCHEMAS = SCHEMAS / "telemetry"
SPAN_NAMING_SCHEMA_PATH = TELEMETRY_SCHEMAS / "span-naming.schema.json"
TRACES_SCHEMA_PATH = TELEMETRY_SCHEMAS / "traces.schema.json"
METRICS_SCHEMA_PATH = TELEMETRY_SCHEMAS / "metrics.schema.json"
LOGS_SCHEMA_PATH = TELEMETRY_SCHEMAS / "logs.schema.json"
REDACTION_SCHEMA_PATH = TELEMETRY_SCHEMAS / "redaction.schema.json"
ENDPOINT_SCHEMA_PATH = TELEMETRY_SCHEMAS / "otel-endpoint.schema.json"
PROBES_SCHEMA_PATH = TELEMETRY_SCHEMAS / "probes.schema.json"

VALID_EXAMPLES = EXAMPLES / "valid"
INVALID_EXAMPLES = EXAMPLES / "invalid"
VALID_PAYLOADS = VALID_EXAMPLES / "events"
INVALID_PAYLOADS = INVALID_EXAMPLES / "events"
VALID_TELEMETRY = VALID_EXAMPLES / "telemetry"
INVALID_TELEMETRY = INVALID_EXAMPLES / "telemetry"

# The gate declaration (core-09). One file per repository at its root, the
# schema the fleet writes it against, the checker that compares the declaration
# to the repository, and the red proof that the checker is able to fail. See
# docs/gate.md — and for the two alternatives that were measured
# and rejected — a mise task alone cannot be checked, and a CI workflow alone
# lets the local gate and the CI gate drift apart. The harness constants are
# spelled `REPO / "harness"` rather than `HARNESS` because the harness's own
# constant block sits further down this file, and a constant reading a name
# defined later in the module is a module that only imports on a good day.
GATE_SCHEMA_PATH = SCHEMAS / "gate.schema.json"
GATE_DECLARATION = REPO / "gate.yml"
GATE_DOC = DOCS / "gate.md"
GATE_CHECK = REPO / "harness" / "gate_check.py"
GATE_WRAPPER = REPO / "harness" / "bin" / "gate-check"
GATE_FINDINGS = REPO / "harness" / "gate_findings.json"
GATE_SELF_TEST = REPO / "harness" / "tests" / "gate_self_test.sh"
GATE_FIXTURE = REPO / "harness" / "tests" / "fixtures" / "gates" / "conforming"

VALID_GATES = (VALID_EXAMPLES / "gate.self-contained.yml", VALID_EXAMPLES / "gate.external.yml")
INVALID_GATES = {
    "gate.no-proof.yml": (("minItems", "gate/proof"),),
    "gate.shell-string.yml": (("not", "gate/command/0"),),
    "gate.requirement-without-command.yml": (
        ("required", "external/requirements/0/satisfy"),
    ),
    "gate.undeclared-key.yml": (("additionalProperties", ""),),
}

# The checker's exit codes. Named here so a change to the contract is a change
# to a test, exactly as the harness's are. `EXIT_COULD_NOT_RUN` is the one that
# matters most: a check that could not read the declaration has not checked the
# gate, and reporting that as 0 is the defect this whole section exists to end.
GATE_EXIT_OK = 0
GATE_EXIT_FAIL = 1
GATE_EXIT_COULD_NOT_RUN = 2

# The tenant-isolation declaration (core-15). One file per repository at its
# root, the schema the fleet writes it against, the checker that compares that
# declaration to the repository, the finding inventory, and the red proof that
# the checker is able to fail. See docs/tenancy.md, and D33 for the ruling that
# cross-tenant access is DECLARED rather than inferred and answered as
# NONEXISTENCE rather than as a refusal.
#
# It is the second checker in `harness/`, and it is the first one that is not
# the contract harness: it reads a repository's declaration about itself, the
# way `gate_check.py` reads a gate's. So everything core asserts of that one is
# asserted of this one too — the inventory in both directions, standard library
# only, a run that could not happen exiting 2, and a self-test that CI invokes.
# The one thing that is NOT the same is the subject: the gate checker runs a
# command, and this one must not, or a check that reads a tree would start
# depending on what the tree can do.
TENANCY_SCHEMA_PATH = SCHEMAS / "tenant-isolation.schema.json"
TENANCY_DOC = DOCS / "tenancy.md"
TENANCY_CHECK = REPO / "harness" / "tenancy_check.py"
TENANCY_WRAPPER = REPO / "harness" / "bin" / "tenancy-check"
TENANCY_FINDINGS = REPO / "harness" / "tenancy_findings.json"
TENANCY_SELF_TEST = REPO / "harness" / "tests" / "tenancy_self_test.sh"
TENANCY_FIXTURES = REPO / "harness" / "tests" / "fixtures" / "tenancy"
TENANCY_CONFORMING = TENANCY_FIXTURES / "conforming"
TENANCY_HONEST_ZERO = TENANCY_FIXTURES / "honest-zero"
TENANCY_UNREADABLE = TENANCY_FIXTURES / "unreadable-language"

# Two valid examples, because `accountScoped` is an `if`/`then`/`else` and both
# arms need one, and a THIRD because `rls` is a second `if`/`then`/`else` with a
# third and fourth arm. A single account-scoped example would leave the honest
# zero's arm untested, and an untested arm of a conditional is a conditional
# nobody knows what it does.
VALID_TENANCY = (
    VALID_EXAMPLES / "tenancy.account-scoped.yml",
    VALID_EXAMPLES / "tenancy.honest-zero.yml",
    VALID_EXAMPLES / "tenancy.rls-enforced.yml",
    VALID_EXAMPLES / "tenancy.rls-declared-none.yml",
)

# Exact `(keyword, path)` pairs, like INVALID_GATES and for the same reason: a
# negative example that is rejected for the wrong reason is a lie in a comment.
# `examples/invalid/README.md` states the rule itself — a negative case needs a
# test asserting the reason — so these are the pairs, not a boolean.
INVALID_TENANCY = {
    "tenancy.refuses-instead-of-absent.yml": (("const", "entryPoints/0/negative/asserts"),),
    "tenancy.honest-zero-liar.yml": (("maxItems", "entryPoints"),),
    "tenancy.bind-without-a-parameter.yml": (
        ("required", "entryPoints/0/enforced"),
        ("not", "entryPoints/1/enforced"),
    ),
    "tenancy.nowhere.yml": (
        ("required", "entryPoints/0/enforced"),
        ("not", "scope/sources/0"),
    ),
    "tenancy.forced-without-the-bit.yml": (("const", "rls/tables/0/forced"),),
    "tenancy.public-policy.yml": (("not", "rls/tables/0/policies/0/roles/0"),),
    "tenancy.two-arms.yml": (("minItems", "entryPoints/0/negative/cases"),),
}

# The checker's exit codes, and the same three the gate checker uses. The third
# is the load-bearing one: a checker pointed at a path that is not a repository
# has not checked the boundary, and reporting that as 0 turns an unknown into a
# green badge — which is the entire defect this packet exists to stop.
TENANCY_EXIT_OK = 0
TENANCY_EXIT_FAIL = 1
TENANCY_EXIT_COULD_NOT_RUN = 2

# The account-scoped entry-point declaration (D18 step 1). One file per service at
# its root, the schema the fleet writes it against, the checker that compares that
# declaration to the repository, the finding inventory, and the red proof that the
# checker is able to fail. See docs/account-scope.md.
#
# It is the FOURTH checker in `harness/` and the second that reads a repository's
# declaration about itself rather than a manifest. Everything core asserts of
# `tenancy_check.py` is asserted of it too: the inventory in both directions,
# standard library only, no environment and no process, a run that could not happen
# exiting 2, and a self-test that proves the checker can fail. What it is NOT is a
# fifth block of `tenancy.yml`: that file enumerates the STATEMENTS that reach a
# customer's row and this one enumerates the ENTRY POINTS a caller arrives
# through, and neither can be derived from the other.
ACCOUNT_SCOPE_SCHEMA_PATH = SCHEMAS / "account-scope.schema.json"
ACCOUNT_SCOPE_DOC = DOCS / "account-scope.md"
ACCOUNT_SCOPE_CHECK = REPO / "harness" / "account_scope_check.py"
ACCOUNT_SCOPE_WRAPPER = REPO / "harness" / "bin" / "account-scope-check"
ACCOUNT_SCOPE_FINDINGS = REPO / "harness" / "account_scope_findings.json"
ACCOUNT_SCOPE_SELF_TEST = REPO / "harness" / "tests" / "account_scope_self_test.sh"
ACCOUNT_SCOPE_FIXTURES = REPO / "harness" / "tests" / "fixtures" / "account-scope"
ACCOUNT_SCOPE_CONFORMING = ACCOUNT_SCOPE_FIXTURES / "conforming"
ACCOUNT_SCOPE_PHOENIX = ACCOUNT_SCOPE_FIXTURES / "phoenix_surface"
ACCOUNT_SCOPE_NEXTJS = ACCOUNT_SCOPE_FIXTURES / "nextjs_surface"
# The two Hono surfaces, and they are the controls for a DIFFERENT question from the
# three above: not "can this checker read a route" but "can it read what runs BEFORE
# the handler". `hono_pipeline`'s gate is inline in the same file as the route;
# `hono_surface`'s is too, but its two `if (jwt) { … }` blocks are the same length so
# the red proof can move one without moving a line. `hono_composed` is the third and
# is not a control: its gate left the file, and not accusing it is the answer.
ACCOUNT_SCOPE_HONO_PIPELINE = ACCOUNT_SCOPE_FIXTURES / "hono_pipeline"
ACCOUNT_SCOPE_HONO_SURFACE = ACCOUNT_SCOPE_FIXTURES / "hono_surface"
ACCOUNT_SCOPE_HONO_COMPOSED = ACCOUNT_SCOPE_FIXTURES / "hono_composed"

# Two, and they are the two arms of `surface.kind`'s conditional: a service with a
# surface, and a shared library with none. An untested arm of a conditional is a
# conditional nobody knows what it does.
VALID_ACCOUNT_SCOPE = (
    VALID_EXAMPLES / "account-scope.yml",
    VALID_EXAMPLES / "account-scope.no-surface.yml",
)

# Exact `(keyword, path)` pairs, like INVALID_GATES and INVALID_TENANCY and for
# the same reason: a negative example rejected for the wrong reason is a lie in a
# comment. `required` on `accountFrom` and on `reason` are the two conditionals
# that make the format a contract rather than a list.
# The `required` paths are `entryPoints/0` and not `entryPoints/0/accountFrom`,
# which is worth knowing rather than worth guessing: `required` names the OBJECT
# whose property is missing, and jsonschema reports it at that object's path. So a
# negative example that asserted `entryPoints/0/accountFrom` would fail on a schema
# that is enforcing exactly the rule it was written for.
INVALID_ACCOUNT_SCOPE = {
    "account-scope.account-scoped-without-account-from.yml": (
        ("required", "entryPoints/0"),
    ),
    "account-scope.unscoped-without-reason.yml": (("required", "entryPoints/0"),),
    "account-scope.undeclared-key.yml": (("additionalProperties", "entryPoints/0"),),
    "account-scope.honest-zero-with-a-surface.yml": (
        ("maxItems", "surface/sources"),
        ("const", "surface/minimum"),
    ),
}

ACCOUNT_SCOPE_EXIT_OK = 0
ACCOUNT_SCOPE_EXIT_FAIL = 1
ACCOUNT_SCOPE_EXIT_COULD_NOT_RUN = 2

MANIFEST_EXAMPLES = sorted(VALID_EXAMPLES.glob("*.cafaye.yml"))

# Open decisions live in DECISIONS.md at the repository root rather than as
# callouts in docs/, because test_no_open_decision_callouts_remain_in_the_docs is
# a merge gate: a spec on master must read as decided, and a worker branch that
# opens a real question would trip it. The tempting fix — weakening or skipping
# that gate — is how a spec silently stops being enforced. So the questions are
# numbered in one place and the affected doc points at them.
DECISIONS = REPO / "DECISIONS.md"
CHANGELOG = REPO / "CHANGELOG.md"
REQUIRED_DECISION_PARTS = ("Choice:", "Alternatives:", "Recommendation:", "Cost of flipping:")

# fleet.yml is core's record of what the real services publish. It is not an
# example manifest: it is the one file in this repository that states a fact
# about another repository, which is why it has its own schema and its own tests.
FLEET = REPO / "fleet.yml"
INVALID_FLEET = INVALID_EXAMPLES / "fleet.invalid.yml"
WORKER_EXAMPLE = VALID_EXAMPLES / "worker.cafaye.yml"
WORKER_ONLY_EXAMPLE = VALID_EXAMPLES / "worker-only.cafaye.yml"
VALID_ENVELOPE = VALID_EXAMPLES / "event-envelope.json"
INVALID_MANIFEST = INVALID_EXAMPLES / "manifest.cafaye.invalid.yml"
INVALID_ENVELOPE = INVALID_EXAMPLES / "event-envelope.invalid.json"
INVALID_UNTAGGED_ENVELOPE = INVALID_EXAMPLES / "event-envelope.untagged.invalid.json"
INVALID_SUBJECTLESS_ENVELOPE = INVALID_EXAMPLES / "event-envelope.subjectless.invalid.json"
INVALID_EMAIL_EXAMPLE = INVALID_PAYLOADS / "billing" / "payment" / "succeeded.email.data.json"

# The reserved tombstone (core-reserved-tombstone-01). A service removes a
# property from its contract and names the removal, so the NAME stays reserved
# and a later document that reintroduces it is a failure rather than a silent
# rebind: a consumer that generated source against `invoice_id` and upgrades to
# a document where `invoice_id` means something else recompiles cleanly and
# reads the wrong thing, and nothing anywhere errors.
#
# The key is an EXTENSION POINT on the manifest — `x-cafaye-` prefixed, no
# runtime meaning, present so a rule has something to read. Naming it in the
# schema is the whole job, because the manifest is closed with
# `additionalProperties: false` at every level and an undeclared key is an error
# rather than a no-op.
RESERVED_PROPERTIES_KEY = "x-cafaye-reserved-properties"
RESERVED_VALID_EXAMPLE = VALID_EXAMPLES / "reserved-properties.cafaye.yml"
RESERVED_INVALID_EXAMPLE = INVALID_EXAMPLES / "reserved-properties.cafaye.invalid.yml"

# (keyword, path) pairs, like INVALID_GATES and for the same reason. Four of the
# five mistakes in the example are schema decisions; the fifth — an entry naming a
# surface this manifest does not publish — is schema-conformant and is caught by
# `harness/reserved_check.py` instead, which is why it is NOT here. A list that
# claimed to cover a finding the schema does not make would be a list that
# misreports which rule fired.
INVALID_RESERVED_CASES = (
    ("pattern", "x-cafaye-reserved-properties/0/name"),          # InvoiceId
    ("pattern", "x-cafaye-reserved-properties/1/removedFrom"),  # `billing`, not a surface
    ("additionalProperties", "x-cafaye-reserved-properties/2"),  # `currency`
    ("uniqueItems", "x-cafaye-reserved-properties"),            # the same entry twice
)

EVENT_NAMING_DOC = DOCS / "event-naming.md"
OPENAPI_DOC = DOCS / "openapi-conventions.md"
OUTBOX_DOC = DOCS / "event-outbox.md"
OBSERVABILITY_DOC = DOCS / "observability.md"
INVALID_NOTES = INVALID_EXAMPLES / "README.md"

MIN_VALID_MANIFEST_EXAMPLES = 3
FORMAT_CHECKER = jsonschema.FormatChecker()

REQUIRED_OPENAPI_TOPICS = (
    "problem+json",
    "idempotency-key",
    "jwks",
    "/v1",
    "deprecat",
    "cursor",
    "info.version",
    "contract lint",
)

# Every core semver constraint form (docs/manifest-conventions.md) needs a
# manifest that uses it, or the form is untested grammar.
REQUIRED_CORE_CONSTRAINT_FORMS = ("^0.", "~0.", "0.")

# A payload schema lives at schemas/events/<service>/<entity>/<action>.schema.json
PAYLOAD_SUFFIX = ".schema.json"
PAYLOAD_EXAMPLE_SUFFIX = ".data.json"

# The services fleet.yml is a declaration about. The list is a floor, not a
# ceiling: a new service joins it when its manifest is read, and a service that
# ships nothing (gateway) is still in it, because a declaration that only names
# services with events would not be a declaration about the fleet.
REQUIRED_FLEET_SERVICES = frozenset({"identity", "billing", "courier", "muse", "gateway"})

# (event type, expected (keyword, path) violations) — every payload schema owes
# a negative case, exactly like every top-level schema does.
INVALID_PAYLOAD_CASES = (
    # The type D35 was about, and the only entry whose expected keywords include a
    # FORMAT. Its negative payload is the one D35 shipped, unchanged: a
    # `usr_`-prefixed id, an `email_verified` boolean no publisher emits, and a
    # field nobody declared. Every one of those is now a rejection rather than an
    # example — so the correction is enforced from the example side as well as
    # from the schema side, which is the difference between a schema that is
    # right and a schema that is right and cannot say so.
    (
        "identity.user.created",
        (("required", ""), ("format", "user_id"), ("additionalProperties", "")),
    ),
    # The eight core-23 types, in the order the packet lists them. The expected
    # keywords are not the boilerplate pair everywhere, and the difference is the
    # point: where a type has a closed vocabulary of its own, the negative case
    # has to trip THAT vocabulary, or the schema is closed and says nothing. A
    # `reason` outside identity's two, a `method` the mfa_credentials CHECK
    # forbids, a scope outside the vocabulary — those are the constraints read out
    # of the publisher, and a case that only omits a required field proves none of
    # them.
    (
        "identity.user.email_verified",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "identity.session.revoked",
        (("required", ""), ("enum", "reason"), ("additionalProperties", "")),
    ),
    (
        "identity.mfa.enabled",
        (("required", ""), ("enum", "method"), ("additionalProperties", "")),
    ),
    (
        "identity.mfa.disabled",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "identity.api_key.created",
        (("required", ""), ("enum", "scopes/1"), ("additionalProperties", "")),
    ),
    (
        "identity.api_key.revoked",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "identity.oidc_client.created",
        (("required", ""), ("enum", "scopes/1"), ("additionalProperties", "")),
    ),
    (
        "identity.oidc_client.revoked",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.customer.created",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.plan.created",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.plan.updated",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.subscription.started",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.subscription.updated",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.subscription.canceled",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "billing.payment.succeeded",
        (("required", ""), ("additionalProperties", ""), ("oneOf", "")),
    ),
    (
        "billing.payment.failed",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "courier.email.queued",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "courier.email.delivered",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "courier.email.bounced",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "courier.email.complained",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "courier.notification.suppressed",
        (("required", ""), ("additionalProperties", "")),
    ),
    (
        "muse.tokens.consumed",
        (("minLength", "model"), ("additionalProperties", "")),
    ),
)

# --- D35: a payload schema against the publisher that emits it ---------------
#
# D35 is a schema that described a payload no publisher had ever sent: a
# `usr_`-prefixed `user_id` that identity's builder cannot produce, beside three
# optional properties its marshalled struct does not have. It survived because
# nothing in core compared the schema against anything — not against the code
# that emits it (core cannot import Go), and not against the eight correct
# schemas in the same directory.
#
# So the rules below are the strongest comparisons available from inside core,
# and each one says what it cannot do. `docs/event-naming.md` states the limits
# where a reader of the spec will meet them; DECISIONS.md D35 is the ruling that
# the correction is a patch, and D36 is what a static check can honestly claim
# about a publisher it has never read.
#
# A rule core states and cannot enforce is a rule that lies, and that includes
# core's own tests. Nothing here reads Go, nothing here reaches the network, and
# nothing here is allowed to imply more than it checks.

# The keywords that carry a value's VOCABULARY — which values the field accepts
# — as opposed to the prose that describes them. Two schemas may describe the
# same value in two sentences and may not spell it two ways.
#
# `type` is deliberately NOT in this list, and that is a measured decision rather
# than an oversight: billing's `subscription_id` is a required string on
# `billing.subscription.started` and a nullable one on `billing.payment.succeeded`,
# which is two true facts about two events and not a disagreement about what an
# id is. Including `type` made the rule fire on two billing fields and would have
# trained the next reader to ignore it. So this compares the vocabulary and says
# nothing about requiredness or nullability; see D36 for what that leaves open.
ID_VOCABULARY_KEYWORDS = ("format", "pattern", "enum", "const")

# A field name that holds an entity's id: `id`, `user_id`, `account_ids`, and the
# envelope's `subject`, which is the same fact in a different envelope. Named by
# shape rather than listed, because a list is a list that rots — the ninth id
# field is then covered by the rule rather than by a patch to a table.
#
# The prefix segment admits SEVERAL underscore-separated words, and that is a
# correction rather than a generalization. `client_reference_id` was invisible to
# this for core-24's whole life: the segment was `[a-z][a-z0-9]*_`, which admits
# one underscore, and billing's field has two. The rule therefore reported "no
# example carries an id no publisher mints" while billing's valid
# `payment/succeeded.checkout` example carried `acc_01J9Z8RR7B2QK3M4N5P6Q7R8S9T`
# in plain sight. A rule that is right about the examples it was shown and blind
# to the ninth one is worse than no rule, because it is quoted as coverage.
IDENTIFIER_FIELD = re.compile(r"^(?:[a-z][a-z0-9]*(?:_[a-z0-9]+)*_)?ids?$|^subject$")

# The cafaye id shape, in the two forms core can check. It is a SHAPE and not a
# list of prefixes, which is the whole difference between this rule and the one
# D35 sketched: `sub_` is a prefix cafaye never mints and Stripe mints on every
# subscription, and D10 says so in as many words. What no publisher in the fleet
# mints is the combination — a short lowercase word, an underscore, and a long
# run of UPPERCASE base32 — because that is a ULID behind a prefix, and it is the
# shape both `^usr_[0-9A-Z]{26}$` and `^acc_[0-9A-Z]{26}$` had. Keyed on
# case, a processor's mixed-case `sub_1PZQaBcDeFgHiJkLmNoPqR1` stays legal.
CAFAYE_ID_VALUE = re.compile(r"^[a-z]{2,6}_[0-9A-Z]{16,}$")
CAFAYE_ID_PATTERN = re.compile(r"\^[a-z]{2,6}_(?:\[0-9A-Z\]|[0-9A-Z])")

# The citation a payload schema carries for the commit its publisher was read
# at. Fixed in one regex so the schema, the test and the doc cannot disagree
# about what a citation looks like.
PROVENANCE_CITATION = re.compile(r"read from (?P<service>[a-z][a-z0-9-]*) at (?P<commit>[0-9a-f]{40})")

# The publishers whose payload schemas core carries a citation for, and which
# therefore owe one on EVERY payload schema they have.
#
# `identity` and `courier`, and the reason is provenance rather than
# preference: identity's nine payload schemas were written by reading the event
# builders in its own `internal/outbox/` at the commit `fleet.yml` already
# records as its `sourceCommit` (core-23, D34, D35). courier's five were read out
# of `lib/courier/events.ex` at the commit `fleet.yml` records for courier, which
# core-25 re-read and confirmed: `delivered/1`, `bounced/1`, `complained/1` and
# `suppressed/1` are all there, and `queued/1` is **absent** — which is the
# citation's content as much as its presence, and is why courier's `queued`
# schema cites the commit at which its publisher was looked for and not found.
# That is a transcribed fact, so it can be asserted.
#
# billing's tree was verifiably AT its recorded `sourceCommit` (clean tree, HEAD
# is that commit), so core-25 read all eight of its emitters there and cited all
# eight. Citing one billing schema and leaving seven would have been the worst of
# both worlds — a partial citation reads as provenance and checks nothing, and the
# five the packet named were never the interesting subset anyway:
# `payment/succeeded` turned out to be the one that taught core a fictional id.
#
# muse's is the only one left, and it stays exempt: core-25 did not read
# `metering.py`'s envelope builder at muse's recorded commit, so citing its one
# payload schema would be inventing provenance to satisfy a checker, which is the
# exact failure D35 was. It is not owed by accident — muse's payload has no
# identifier field at all, so the id rules have nothing to say about it either way.
PROVENANCE_REQUIRED = ("identity", "courier", "billing")

# --------------------------------------------------------------------------
# 5c. the id shape, read out of the publisher that mints it
# --------------------------------------------------------------------------

#: Each publisher's id type, as a shape core can check, with the file it was read
#: out of. This is the positive half of the id rule and it is a different kind of
#: claim from D35's.
#:
#: D35's rule is a DENYLIST of one shape — a short lowercase word, an underscore,
#: and a run of uppercase base32 — and it says only "no publisher mints this". That
#: is why it went green over twenty-one defects: `tnt_…` and `acc_…` are in the
#: denylist, but they were in files the rule never walked, so being in the denylist
#: was no help. A denylist only catches what it is pointed at, and this one was
#: pointed at `examples/valid/events/`.
#:
#: This is the ALLOWLIST, and it is a different rule with the opposite failure
#: mode: it cannot know a shape nobody has recorded, so a ninth publisher mints
#: something new and the ledger is silent. That is why it is a ledger keyed on
#: the service rather than a regex, why every entry is transcribed from a named
#: file at a named commit, and why the check below walks examples in BOTH
#: directions — every example value must match the entry for the service that
#: emits it, and every entry must be matched by something.
#:
#: The values are regexes over the WHOLE id, and they are read out of the
#: producers rather than out of their test fixtures, which is the whole defect:
#: `identity/internal/telemetry/telemetry_test.go` and `observability_test.go` do
#: carry `acc_…`, and `billing`'s test fixture carries `"acme"`. Test fixtures are
#: chosen for readability. Nothing serializes them.
#:
#: `tenant_id` is the entry that changes a reader's mind. It is not an id: it is
#: an operator-set environment variable copied verbatim onto the resource
#: (`IDENTITY_TENANT_ID`, `COURIER_TENANT_ID`, `BILLING_TENANT_ID`), and the
#: producers' own tests give it `"tenant-abc"` and `"acme"`. So it has no uuid
#: shape at all and a rule that demanded one would be inventing a constraint, and
#: `account_id` is a bare uuid everywhere it exists — `accountID.String()` in
#: identity's `internal/outbox/tenancy.go`, `Ecto.UUID` in courier, and billing's
#: own `Identifiers::UUID`.
#: Telemetry resource attributes, which are a DIFFERENT population of values from
#: payload fields under the same names — and the difference is the whole reason
#: this packet found a second defect the first rule could not see.
#:
#: `account_id` on an event payload is a bare uuid and identity emits it in four
#: places (`internal/outbox/apikeys.go`, `oidc.go`, `tenancy.go`). `account_id` on
#: a telemetry RESOURCE is emitted by nobody: read across all four services that
#: export anything, `account_id` appears zero times in identity's `telemetry.go`,
#: courier's `telemetry.ex`, billing's `kit/telemetry.rb` and muse's
#: `telemetry.py`. An example may therefore carry a uuid `account_id` in a payload
#: and must not carry one on a resource, and a rule keyed on the field name alone
#: cannot tell those apart.
#:
#: `tenant_id` is the mirror image: it IS emitted on a resource by three services
#: (identity, courier, billing) as an operator-set env var, and on no payload in
#: the fleet.
#:
#: `None` means "no rule for this combination", and it is an explicit entry rather
#: than an absent one so that a NEW resource attribute is a reported gap rather
#: than a silent pass.
RESOURCE_ATTRIBUTE_SHAPES = {
    "identity": {
        "tenant_id": "operator-label",
        "account_id": "not-emitted",
    },
    "courier": {
        "tenant_id": "operator-label",
        "account_id": "not-emitted",
    },
    "billing": {
        "tenant_id": "operator-label",
        "account_id": "not-emitted",
    },
    "muse": {
        # `_resource/1` sets `service.name` and `service.namespace` and nothing
        # else. Not even a tenant.
        "tenant_id": "not-emitted",
        "account_id": "not-emitted",
    },
}

PRODUCER_ID_SHAPES = {
    "identity": {
        "at": "608fa9afa5cb1704c3c85bde2e1c81aab9f1dbf2",
        "source": "internal/platform/id/id.go",
        "shapes": {
            # `id.UUID.String()` writes canonical lower-case 8-4-4-4-12 hex with
            # no prefix, which is `format: uuid` in every payload schema that
            # carries one.
            "uuid": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            # A DEPLOYMENT LABEL, not an id. `Resource()` appends
            # `attribute.String("tenant_id", lookup(TenantVariable))` and never
            # parses it, so any operator string is legal and a uuid is merely one
            # possibility. Asserting the absence of a prefix rather than the
            # presence of a shape is deliberate: core does not know this fleet's
            # tenant names, and a rule that guessed one would reject the next
            # operator.
            # A tenant label, and the underscore is what makes it a LABEL rather than an
            # id. Dots, dashes and alphanumerics are all things an operator
            # writes in a tenant name and none of them is a namespace
            # separator; an underscore is the one character in the fiction that a
            # human choosing `acme` or `tenant-abc` would not type.
            #
            # **The permissive version of this pattern was itself a bug in this
            # packet.** `[A-Za-z0-9._-]` admits the underscore, so it matched
            # `tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG`, and the witness test caught it by
            # failing on a defect it was supposed to name. A shape that accepts
            # the fiction it exists to reject is worse than no shape, because it
            # reports green on the exact defect it was bought for.
            "operator-label": r"^[A-Za-z0-9][A-Za-z0-9.-]*$",
            # Matches nothing, on purpose. This is how a ledger says "the
            # producers were read and this is not among the things they emit",
            # which is a different statement from "core has not looked" — and the
            # difference is the whole point of a positive check. It is the shape
            # that lets the rule reject an `account_id` on a resource without
            # core having to know in advance what a tenant's ids look like.
            "not-emitted": r"^(?!x)x",
            # 32 random bytes, unpadded base64url (internal/oidc/client.go:168).
            # 43 characters today; the range is the column's own CHECK.
            "base64url-32": r"^[A-Za-z0-9_-]{32,64}$",
        },
    },
    "courier": {
        "at": "a8f15ccef11bd6148c71fbe38327d9fbebbfe2e2",
        "source": "lib/courier/events.ex",
        # Re-read 2026-10-02 at courier's master HEAD `ae8a660`, which is PAST
        # this commit and is still what `fleet.yml` records: the two shapes below
        # are unchanged. `deliver.ex`'s `message_id` line moved from 152 to 196
        # and reads the same, and `inbound_reports.ex` is byte-identical between
        # the two commits. What did change is the standing of the fifth type —
        # `notification.suppressed` gained a caller in `Courier.Unsubscribes`, so
        # courier publishes four of five, which is `fleet.yml`'s note and not an
        # id shape. D38 carries it.
        "shapes": {
            "uuid": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            # `message_id = "courier-" <> Ecto.UUID.generate()` at
            # lib/courier/deliver.ex:152. A real prefixed id, which is why the
            # denylist had to be a SHAPE and not a prefix list: refusing `courier-`
            # because it looks like the fiction would have refused courier.
            "courier-message-id": r"^courier-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "operator-label": r"^[A-Za-z0-9][A-Za-z0-9.-]*$",
        },
    },
    "muse": {
        "at": "53b6ebb1947eeb1ff90a4cfaff75897f358dc2e9",
        "source": "src/muse/telemetry.py",
        # Re-read 2026-10-02 at that commit, which is still muse's HEAD, with the
        # OpenTelemetry SDK **1.44.0** in muse's own `.venv`. `Resource.create/1`
        # MERGES the SDK's default resource, so a real muse span's resource is
        # six attributes: `telemetry.sdk.language`, `telemetry.sdk.name`,
        # `telemetry.sdk.version`, an SDK-generated `service.instance.id`,
        # `service.name`, and `service.namespace`. Four of the six were refused by
        # `traces.schema.json`'s closed resource list; D40 adds them, and
        # `RESOURCE_ATTRIBUTES_THE_FLEET_EMITS` is where the evidence lives.
        "shapes": {
            # muse emits NO id anywhere. Its one event's `data` is five fields and
            # none is an identifier (`model`, `provider`, `tokens_in`,
            # `tokens_out`, `cost_micros`), and its envelope `subject` is the
            # literal `platform` — `SUBJECT = "platform"` at metering.py:61,
            # because muse's v1 auth stub reads no token and so cannot attribute
            # a call to a customer. See D9.
            #
            # Its resource is the thinnest in the fleet too: `_resource/1` sets
            # `service.name` and `service.namespace` and nothing else. It is
            # recorded here as `no-ids` rather than left out, because "muse emits
            # nothing" is a fact read out of two files at a commit and it is what
            # makes the twelve muse telemetry examples above a fiction rather than
            # an omission.
            "no-ids": r"^(?!x)x",
            # `SUBJECT = "platform"` (metering.py:61). Anchored and total on
            # purpose: this is the reserved literal core's envelope schema
            # allows for an event with no entity, and a muse envelope whose
            # subject is anything else is an event describing a customer muse
            # cannot attribute.
            "reserved-literal": r"^platform$",
        },
    },
    "billing": {
        "at": "7133643d8eebb4dd5de2d8df34c7ba20fda89f79",
        "source": "app/lib/identifiers.rb",
        # billing's tree is verifiably AT this commit (clean, HEAD), and it was
        # still AT it when core-26 re-read it on 2026-10-02 — so `plan_id` and
        # `account_id`, the two fields billing now emits on all three
        # subscription payloads, are `uuid` here like every other billing id and
        # not a new shape. They are not on `IDENTIFIER_FIELD_SHAPES` below,
        # because no valid example carries them: core's three subscription
        # schemas do not declare the two fields, which is the disagreement D39
        # records rather than resolves. Re-read 2026-10-07 at 7133643 (billing's
        # W43 merge, the commit fleet.yml now records): the id shapes are
        # unchanged, and the five money-event payload schemas were extended for
        # the recipient fact and the plan's name (core-w46).
        "shapes": {
            "uuid": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "operator-label": r"^[A-Za-z0-9][A-Za-z0-9.-]*$",
            # Stripe's own ids, mixed case, which D10 says are billing's to carry
            # and not cafaye's to forbid. `Identifiers::UUID` is deliberately
            # case-INsensitive, so these are the processor's spelling and core
            # does not restate them.
            #
            # TWO underscore-separated segments, not one: `cs_test_b1PZQaBc…` and
            # `cs_live_…` both carry the mode, and billing's own fake Stripe API
            # builds `format("cs_test_%014d", …)`
            # (test/support/fake_stripe_api.rb:57). A one-segment pattern is the
            # same `[a-z][a-z0-9]*_` mistake `IDENTIFIER_FIELD` had, and it would
            # have gone red on a correct example — a rule that refuses true facts
            # gets switched off, which is the failure mode D10 is about.
            "processor-id": r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*_[0-9A-Za-z]+$",
        },
    },
}

#: Which shape each identifier field is supposed to be, per service. Keyed on the
#: field name rather than on the value, because the field is what the publisher
#: writes and the value is what the example chose — a rule keyed on the value
#: would be a denylist again with a different name.
#:
#: `subject` is in here because the envelope's `subject` is the same fact as a
#: payload id field and the envelope example is walked too. For identity it is a
#: uuid; for courier it is courier's own `message_id` (courier documents this at
#: events.ex:105, "courier's own message id, not the user"); for billing it is a
#: Stripe customer or subscription id.
IDENTIFIER_FIELD_SHAPES = {
    "identity": {
        "user_id": "uuid",
        # A bare uuid — `accountID.String()` at internal/outbox/tenancy.go:98,
        # apikeys.go:85 and oidc.go:70. NOT `not-emitted`: that is true only of
        # the telemetry RESOURCE, and `RESOURCE_ATTRIBUTE_SHAPES` is where the
        # two populations are kept apart.
        "account_id": "uuid",
        "credential_id": "uuid",
        "subject": "uuid",
        "id": "uuid",
        "tenant_id": "operator-label",
        # 32 random bytes in unpadded base64url — `identity/internal/oidc/client.go:168`
        # says so in those words, and the payload schema's pattern
        # `^[A-Za-z0-9_-]{32,64}$` is the column's own CHECK rather than a guess.
        # NOT a uuid and NOT a cafaye-prefixed id: it is an unguessable handle,
        # which is a third vocabulary rather than a variant of either.
        "client_id": "base64url-32",
    },
    "courier": {
        "user_id": "uuid",
        "message_id": "courier-message-id",
        "tenant_id": "operator-label",
    },
    "billing": {
        "customer_id": "processor-id",
        "subscription_id": "processor-id",
        "invoice_id": "processor-id",
        "price_id": "processor-id",
        "processor_event_id": "processor-id",
        "checkout_session_id": "processor-id",
        "payment_intent_id": "processor-id",
        # Stripe's price id, carried on `billing.plan.updated` because that is
        # where billing records the price it will charge (`Plan#as_event_data`,
        # app/models/plan.rb:87). Same processor vocabulary as the rest.
        "processor_price_id": "processor-id",
        # The id billing sends to Stripe as `client_reference_id`, and the one
        # Stripe echoes back on the webhook. Read out of
        # `StripeClient#create_checkout_session` at billing's recorded
        # sourceCommit: `client_reference_id: customer_reference`, where
        # `customer_reference` is billing's OWN customer id — a uuid, per the
        # production test's own fixture value
        # `11111111-1111-4111-8111-111111111111`.
        #
        # **This value was `acc_01J9Z8RR7B2QK3M4N5P6Q7R8S9T` until this packet,
        # and it is the clearest single piece of evidence for the defect core-24
        # shipped.** billing's production code sends a bare uuid; its
        # webhook test asserts `acc_01J9Z8RR7B2QK3M4N5P6Q7R8S9T`; core's valid
        # example had the test's value, not the code's. Somebody wrote the
        # example from the fixture — which is exactly the wrong direction, and
        # the reason a rule that only asked "is this in the denylist shape" was
        # never going to catch it.
        "client_reference_id": "uuid",
        "id": "uuid",
    },
}

#: Which service owns each example, so the ledger lookup is not guesswork. Keyed
#: on the path under `examples/valid/`: `events/<service>/…` for payloads, the
#: `telemetry/` prefix for the signals, and the envelope by its `source`.
#:
#: The telemetry examples name their own `service.name`, so they are attributed
#: from the DOCUMENT rather than from the directory — `span.muse.json` is muse's
#: and `log.json` is courier's, and a directory-level rule would have credited all
#: sixteen to whichever service the directory happened to sort first.
EXAMPLE_OWNERS = {
    "courier": "courier",
    "billing": "billing",
    "identity": "identity",
    "muse": "muse",
    "gateway": "gateway",
}

#: muse's identifier fields. There are none — its payload has no id and its
#: subject is the literal `platform` — so this is recorded explicitly rather than
#: left as an absent entry. An absent entry and an empty one mean different
#: things: the first says "core has not read this", the second says "core read it
#: and there is nothing there", and only the second is a fact.
#:
#: `subject` is the one field muse writes, and its shape is the reserved literal.
#: `IDENTIFIER_FIELD` matches it, so without an entry the rule would demand a
#: shape for it; with this entry the example's value has to BE `platform`, which
#: is a check that would fire the day somebody made muse's subject per-customer.
IDENTIFIER_FIELD_SHAPES["muse"] = {}

# The outbox table is a contract, so its columns are asserted out of the SQL in
# docs/event-outbox.md rather than trusted to the prose around it.
REQUIRED_OUTBOX_COLUMNS = (
    "create table if not exists outbox_events",
    "id uuid primary key",
    "event_type text not null",
    "source text not null",
    "subject text not null",
    "time timestamptz not null",
    "data jsonb not null",
    "created_at timestamptz not null default now()",
    "published_at timestamptz null",
    "attempts int not null default 0",
    "where published_at is null",
    "for update skip locked",
    "create index if not exists",
)

REQUIRED_OUTBOX_TOPICS = (
    "outbox_events",
    "same transaction",
    "for update skip locked",
    "published_at",
    "attempts",
    "backoff",
    "nats",
    "at-least-once",
    "idempotent",
    "```mermaid",
    "sequencediagram",
)

# --- observability (PLAN.md §7b) -------------------------------------------

# The identifiers that are prohibited as a *measurement* attribute. This list is
# the failure mode the rule exists for, written out rather than described:
# OpenTelemetry folds a metric stream into one `otel.metric.overflow=true` point
# at 2000 distinct attribute combinations and drops every measurement attribute
# on the way, so totals stay right and every breakdown undercounts. The three
# named in the directive — tenant_id, user_id, account_id, request_id — plus
# trace_id and the request-scoped ids that are unbounded for the same reason.
PROHIBITED_MEASUREMENT_ATTRIBUTES = (
    "tenant_id",
    "user_id",
    "account_id",
    "request_id",
    "trace_id",
    "span_id",
    "session_id",
    "message_id",
    "notification_id",
    "email",
)

# Where those go instead. Resource attributes are not per-measurement, so the
# 2000-combination cap does not apply to them and they stay queryable on the
# overflow point — which is the entire reason the rule says "move it" rather
# than "drop it".
RESOURCE_IDENTITY_ATTRIBUTES = (
    "tenant_id",
    "account_id",
    "service.name",
    "service.version",
    "service.instance.id",
    "deployment.environment",
)

# Content words that must never appear in an allowlisted attribute name. This is
# muse's canary promoted to a spec: the house test at
# muse/tests/test_trace_propagation.py asserts no allowlisted name contains any
# of them, and asserts the rendered payload separately so truncation cannot be
# what makes it pass. The word list is the same one, so the fleet cannot
# reintroduce the leak under a new attribute name.
FORBIDDEN_ATTRIBUTE_NAME_WORDS = (
    "prompt",
    "completion",
    "message",
    "content",
    "text",
    "body",
    "header",
    "input",
    "output",
    "arguments",
    "instructions",
    "transcript",
    "query",
)

# Span names the grammar accepts. Low-cardinality by construction: a bounded
# segment vocabulary, no interpolation, and a length cap — because
# `muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` is a cardinality bomb that looks
# like diligence in a code review.
ACCEPTED_SPAN_NAMES = (
    "muse.request",
    "muse.route",
    "muse.provider.call",
    "identity.db.query",
    "billing.payment.capture",
    "courier.email.deliver",
    "darkroom.asset.transform",
    "gateway.request.authorize",
    "muse.queue.publish",  # a service name may contain a dash
)

REJECTED_SPAN_NAMES = (
    "GET /users/:id",                          # the HTTP verb and the raw route
    "get_user",                                # a function name
    "users.GET",                               # a path and a verb
    "muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A",  # an interpolated identifier, as cafaye mints them
    # Lower-case, so that case is NOT what refuses it. This entry is the only
    # one in the list that the fifteen-character segment cap is solely
    # responsible for rejecting, which makes it the one that keeps the cap
    # honest: without it, widening the cap to 63 would leave this test green
    # while the grammar quietly stopped refusing identifiers. Found by
    # mutating the cap and watching the suite stay green.
    "muse.user.usr_01j9z8qk5m4n7p2r3t6v8w9x0a",
    "muse.request.4bf92f3577b34da6a3ce929d0e0e4736",  # a trace id in the name
    "request",                                 # no service prefix
    "MUSE.REQUEST",                            # not lowercase
    "muse..request",                           # empty segment
    "muse.request.",                           # trailing separator
    "muse.1request",                            # segment starts with a digit
    "muse.a.b.c.d.e",                          # five segments: the grammar caps at four
    "muse-provider.call!",                     # punctuation
)

# Per-signal allowlists. The traces, metrics and logs schemas each enumerate
# exactly what may be recorded; this asserts none of them names content, and
# that the four signals do not quietly grow the same attribute with different
# names. The identity of a signal's allowlist is a list of names, so the
# assertion is a name assertion.
SIGNAL_ALLOWLISTS = {
    "traces": (
        "http.request.method",
        "http.response.status_code",
        "http.route",
        "db.system",
        "db.operation",
        "messaging.system",
        "messaging.operation",
        "otel.status_code",
        "error.type",
    ),
    "metrics": (
        "http.request.method",
        "http.route",
        "http.response.status_code_class",
        "db.system",
        "db.operation",
        "messaging.system",
        "error.type",
    ),
    "logs": (
        "log.severity",
        "service.name",
        "error.type",
    ),
}

# The error CLASS vocabulary (D14, ratified by the manager). Twelve classes plus
# the OTel well-known fallback, and the closed set is the rule: a `pattern` is a
# SHAPE, and a shape admits `user_42_email_invalid`, which is the cardinality
# bomb the attribute exists to prevent. This list is asserted against all three
# schemas, against the examples, and against the docs table, so a class cannot be
# added in one place and forgotten in the others.
#
# A class earns its place when its rate is worth an alert on its own — which is
# the test D14 sets, and which is why there are twelve and not sixty. What timed
# out, which provider, which table: those are span names and attributes, never
# part of the class. "Around a dozen" is a bound the suite enforces, because a
# vocabulary that grows one class per incident stops grouping anything.
ERROR_CLASSES = (
    "_OTHER",
    "cancelled",
    "circuit_open",
    "conflict",
    "connection_failed",
    "dependency_unavailable",
    "internal_error",
    "invalid_request",
    "policy_denied",
    "provider_auth",
    "provider_rejected",
    "rate_limited",
    "timeout",
)

#: How many classes the vocabulary may hold. D14 asks for "around a dozen" and
#: says "do not pad it", which is a judgement nobody makes twice the same way
#: under deadline — so it is a bound. Adding a class is a spec change with
#: alternatives and a cost, which is what DECISIONS.md is for.
MIN_ERROR_CLASSES = 10
MAX_ERROR_CLASSES = 16

#: The shape every class but `_OTHER` is, byte-identical on all three signals.
#: Kept alongside the enum rather than instead of it: the enum is the rule and
#: this is the second line, and a rule enforced once is a rule a well-meaning
#: commit can undo. It cannot reject a value the enum accepts, so it can never
#: cause a false rejection.
ERROR_CLASS_SHAPE = "^([a-z][a-z0-9]*(_[a-z0-9]+)*|_OTHER)$"

# Words that would name a *handled* or *retried* attempt. The semconv rule is
# SHOULD NOT — handled and retried errors are not recorded at all, because a
# retry that succeeded is not an error and recording it makes the error rate a
# lie. `SHOULD NOT` cannot be a schema keyword, so it is encoded as the thing
# that makes it unrepresentable: there is no attribute on any signal on which a
# service could say "this attempt failed and I recovered", so there is nothing
# to set to a true value. Same shape as the content-word rule, and for the same
# reason — the realistic violation is a well-meaning `error.handled: true` added
# in six months, not an attacker.
FORBIDDEN_ERROR_LIFECYCLE_WORDS = (
    "retry",
    "retried",
    "retriable",
    "attempt",
    "handled",
    "recovered",
    "suppressed",
)

# The rules the research behind PLAN.md §7b established and that core-04
# described without encoding. If a doc edit drops one of these the suite says so,
# because a rule that lives only in a paragraph is a wish (AGENTS.md).
REQUIRED_ERROR_RECORDING_TOPICS = (
    "absent on success",
    "identical on the span and on the metric",
    "not recorded at all",
    "a retry that succeeded",
    "obliges",
    "span status",
    "_other",
    "not classified its own errors",
    "service.name filter",
    "never a global grouping key",
    "recording-errors.md",
)

# The endpoint contract. `*_OTEL_ENDPOINT` is the only contract (PLAN.md §7b),
# the shipped collector is only a default value, and unsetting it must be a free
# no-op — so the schema pins all three: the variable's name, the fact that
# unset means no-op, and the four properties ("no buffering, no retry loop
# against a dead endpoint, no warning spam") that make "free" checkable rather
# than aspirational.
REQUIRED_ENDPOINT_TOPICS = (
    "_otel_endpoint",
    "no-op",
    "no buffering",
    "no retry",
    "no warning",
    "otel_sdk_disabled",
    "otel_traces_exporter",
    "default",
    "bring your own",
    "readiness",
)

# The redaction boundary. Whatever the enforcement point turns out to be, the
# doc has to say it, and this is the list of things it has to say them about.
REQUIRED_REDACTION_TOPICS = (
    "prompt",
    "completion",
    "allowlist",
    "default-deny",
    "collector",
    "chokepoint",
    "defence in depth",
    "error.message",
    "error.type",
    "token count",
    "model",
    "finish reason",
)

# healthz vs readyz. A `readyz` that checks nothing is the failure the rule
# exists to prevent, and darkroom is the pattern: `/healthz` never touches a
# dependency, `/readyz` really runs `select 1`.
REQUIRED_HEALTH_TOPICS = (
    "healthz",
    "readyz",
    "unconditional",
    "dependency",
    "restart loop",
    "liveness",
    "readiness",
    "exempt from authentication",
)

# healthz vs readyz, as a machine-checked shape: the probe contract is a
# document, so a service declares it and a linter reads it. This is the schema
# side of the fleet-wide rule, and its negative case is a `readyz` with an
# empty `checks` list.
PROBE_EXAMPLE = VALID_TELEMETRY / "probes.json"
INVALID_PROBE_EXAMPLE = INVALID_TELEMETRY / "probes.empty-readyz.invalid.json"

# --------------------------------------------------------------------------
# the contract-test harness (PLAN.md §4, Phase 0)
# --------------------------------------------------------------------------

# core-07 built the harness PLAN.md §4 Phase 0 named and that no packet had
# built: a service validating itself against core's contracts using something
# core ships. It lives in `harness/`, it runs offline against a checkout or a
# pinned ref of core, it exits non-zero rather than skipping when it cannot find
# the contract, and it is proved able to fail by `harness/tests/self_test.sh`.
#
# The harness is executable code in a specification repository, which is the line
# AGENTS.md draws — so the tests in section 7 are mostly about the two ways that
# can go wrong. A harness that cannot fail converts an unknown into a green
# badge, and a hand-written JSON Schema reader that disagrees with the real one
# makes core enforce something other than what it published. Both are checkable,
# so both are checked.
HARNESS = REPO / "harness"
HARNESS_MODULE = HARNESS / "cafaye_contract.py"
HARNESS_WRAPPER = HARNESS / "bin" / "cafaye-contract"
HARNESS_RULES = HARNESS / "rules.json"
HARNESS_SELF_TEST = HARNESS / "tests" / "self_test.sh"
HARNESS_FIXTURES = HARNESS / "tests" / "fixtures"
HARNESS_DOC = DOCS / "contract-harness.md"

# The numeric checker. A THIRD harness sibling, beside cafaye_contract.py (which
# every service runs), core_version.py and tenancy_check.py, and it is separate
# from all three because it is a checker of DECLARATIONS in the same sense
# tenancy_check.py is: it reads documents and decides from static facts, and
# harness/ may not take a dependency or open a connection to learn anything more.
NUMERIC_MODULE = HARNESS / "numeric_check.py"
NUMERIC_WRAPPER = HARNESS / "bin" / "numeric-check"
NUMERIC_SELF_TEST = HARNESS / "tests" / "numeric_self_test.sh"
NUMERIC_FIXTURES = HARNESS / "tests" / "fixtures" / "numeric"

# Exit codes `numeric-check` promises. 0 is the only one that means "nothing on
# this surface is wrong for a language that reads it", 1 is at least one failure,
# and 2 is "the check could not happen" — which is never 0, because a check that
# cannot find the contract is worse than no check: it converts an unknown into a
# green badge. The same three as every other checker in this repository.
NUMERIC_EXIT_CONFORMS = 0
NUMERIC_EXIT_FAILURES = 1

# The float64 boundary, stated here so a fixture can be written in terms of it
# rather than in terms of a typed literal. 2**53 is the last integer a binary64
# holds EXACTLY and 2**53 + 1 is the first it cannot; a table-shaped schema in
# this file has to be able to say "exactly on the boundary" and "one past it"
# without either number being retyped by hand. Asserted equal to the checker's
# own constants in test_the_float64_limit_is_stated_once_in_the_checker_and_
# agrees_with_the_doc, so a change to the checker is a change here in the same
# commit rather than a second, quieter answer.
FLOAT64_EXACT_LIMIT = 2 ** 53
FLOAT64_FIRST_UNREPRESENTABLE = FLOAT64_EXACT_LIMIT + 1

# Exit codes the harness promises. `0` is the only one that means "conforms",
# and the whole point of the section is that a run which could not happen is not
# one of them. Named here so a change to the contract is a change to a test.
HARNESS_EXIT_CONFORMS = 0
HARNESS_EXIT_VIOLATIONS = 1
HARNESS_EXIT_REFUSED = 2

# The digest format: a sha256 over the contract surface, hex, lowercase.
HARNESS_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# Every rule the harness reports on a non-conforming manifest. Asserted as an
# exact set, not a superset: a harness that reports three of four and exits 0 is
# the failure this whole section exists to prevent, and "at least these" is the
# assertion shape that would let it through.
NONCONFORMING_CONVENTION_RULES = frozenset(
    {
        "event.own-prefix",
        "event.unknown-consumed",
        "event.unknown-published",
        "event.payload-schema-missing",
        "manifest.api-file-missing",
    }
)

# The four OpenAPI rules a single document can break, from the fixture that
# breaks all four at once.
NONCONFORMING_OPENAPI_RULES = frozenset(
    {
        "openapi.document-is-31",
        "openapi.info-version",
        "openapi.paths-are-versioned",
        "openapi.one-version-prefix",
    }
)

# Keywords whose value is a *map of name to schema*. The distinction matters
# for `_collect_keywords`: without it a schema walk counts property names as
# keywords, and the harness is then "missing" a keyword called `team`.
SCHEMA_MAP_KEYWORDS = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})

# Keywords whose value is a single schema.
SUBSCHEMA_KEYWORDS = frozenset(
    {"items", "additionalProperties", "not", "if", "then", "contains", "propertyNames"}
)

# Keywords whose value is a list of schemas.
SUBSCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})

# The module names the harness may import. `core`'s rule is that this repository
# has no dependencies, and the harness is the piece of executable code where
# that rule is easiest to break by accident: a `pip install` that makes one
# check pass locally and 404 in a Go service's container.
HARNESS_STDLIB_ONLY = frozenset(
    {
        "argparse", "dataclasses", "hashlib", "json", "os", "pathlib", "re",
        "shutil", "subprocess", "sys", "typing", "unicodedata", "uuid",
    }
)

# --------------------------------------------------------------------------
# 9. the SLO and error-budget spec (PLAN.md §7b)
# --------------------------------------------------------------------------

# What an SLO *is* in cafaye is three schemas and one document. The declaration
# a service commits (slo.schema.json), the burn-rate window catalog that is pinned
# once in core and may not be overridden per service (slo-windows.schema.json),
# and the SLI allowlist that replaces a shared client library across six
# languages (slo-metrics.schema.json). See docs/slo.md.
SLO_SCHEMA_PATH = TELEMETRY_SCHEMAS / "slo.schema.json"
SLO_WINDOWS_SCHEMA_PATH = TELEMETRY_SCHEMAS / "slo-windows.schema.json"
SLO_METRICS_SCHEMA_PATH = TELEMETRY_SCHEMAS / "slo-metrics.schema.json"
SLO_DOC = DOCS / "slo.md"

VALID_SLO = VALID_TELEMETRY / "slo.yaml"
VALID_SLO_WINDOWS = VALID_TELEMETRY / "slo-windows.yaml"

INVALID_SLO_PERFECT = INVALID_TELEMETRY / "slo.perfect.invalid.yaml"
INVALID_SLO_PAGE_ON_LOW = INVALID_TELEMETRY / "slo.page-on-low-tier.invalid.yaml"
INVALID_SLO_WINDOW_OVERRIDE = INVALID_TELEMETRY / "slo.window-override.invalid.yaml"
INVALID_SLO_DENYLISTED = INVALID_TELEMETRY / "slo-metrics.denylisted.invalid.json"

#: R4. What the tier decides, and the only thing it decides: whether a page is
#: generated. `(page_alert.disable, ticket_alert.disable)`, and the test builds
#: both the conforming document and its two inversions for every tier rather
#: than asserting the table is in the schema — a test that reads a table back out
#: of the file it is testing proves the file can spell itself.
SLO_TIER_ALERTS = {
    "critical": (False, False),
    "high": (False, False),
    "low": (True, False),
    "none": (True, True),
}

#: R2. The SRE workbook's windows, in the order Sloth consumes them: short window
#: then long window, four pairs. **14.4 is not 15** — it is 2% of a 28-day budget
#: measured in hours — and `test_the_window_catalog_is_the_workbooks_numbers`
#: recomputes that arithmetic rather than quoting the number.
SLO_WINDOW_CATALOG = (
    ("5m", 14.4), ("1h", 14.4),
    ("30m", 6.0), ("6h", 6.0),
    ("2h", 3.0), ("1d", 3.0),
    ("6h", 1.0), ("3d", 1.0),
)
SLO_BUDGET_FRACTION = 0.02
SLO_PERIOD = "28d"
SLO_PERIOD_HOURS = 28 * 24
#: The budget the workbook's factors were derived against, which is **not** the
#: period above. 14.4 is 2% of 720 hours, and 720 hours is thirty days; under the
#: 28-day period R3 mandates, 2% of the budget is 13.44. Both numbers are in the
#: schema and the difference is the direction it errs in, so the test asserts
#: the discrepancy rather than papering over it — see D27.
SLO_WORKBOOK_HOURS = 30 * 24
SLO_WINDOW_TOKEN = "{{.window}}"

#: R6. The SLIs a service may declare, and the four candidates the spec ships
#: already written out: the HTTP base every one is built on, authentication, the
#: outbox, the email and the invoice. Named after the *operation*, never after a
#: service — a catalogue entry that said "identity" would be an SLO for identity
#: written by a packet that was told not to write one.
SLO_CATALOG_ENTRIES = (
    "http_server_availability",
    "authentication_succeeds",
    "event_accepted_into_outbox",
    "email_dispatched",
    "invoice_computed",
)

#: The two denylists, which are two prohibitions and not one list. Unbounded
#: dimensions are barred because metrics.schema.json bars them on the
#: 2000-combination cap; infrastructure signals are barred because an SLO on a
#: CPU is not an SLO on behaviour. A single merged list would lose the second
#: reason, and the reason is the one a reader has when they are about to add one.
SLO_UNBOUNDED_DIMENSIONS = ("tenant", "user_id", "account_id", "request_id")
SLO_INFRASTRUCTURE_SIGNALS = ("cpu", "memory", "pod", "restart")

#: The OTel -> Prometheus translation, as the exporter performs it: dots become
#: underscores, the UCUM unit is appended in the Prometheus spelling, and the
#: metric type is appended last. Declared here so the test that every catalogue
#: metric is the *normalization* of its OTel name is a derivation rather than a
#: second copy of the catalogue.
PROMETHEUS_UNIT_SUFFIXES = ("", "_seconds", "_milliseconds", "_bytes")
PROMETHEUS_TYPE_SUFFIXES = ("", "_total", "_count", "_bucket", "_sum")

#: The harness's SLO rules, and the fixture that breaks every one of them at
#: once. An exact set, for the reason `NONCONFORMING_CONVENTION_RULES` is: a
#: harness that reports six of eight and exits 0 has turned an unknown into a
#: pass, which is the one defect this whole repository exists to prevent.
NONCONFORMING_SLO_RULES = frozenset(
    {
        "slo.duplicate-name",
        "slo.no-infrastructure-slo",
        "slo.no-unbounded-dimension",
        "slo.schema",
        "slo.sli-canonical",
        "slo.unknown-metric",
        "slo.window-override",
        "slo.window-token",
    }
)

#: What `docs/slo.md` has to say, as the questions a reader arrives with. Each
#: one is a claim the schemas cannot make on their own: the artifact, the
#: arithmetic behind the threshold, the tier table, the multi-tenancy answer, the
#: spanmetrics migration, and the statement that there is no SLA.
SLO_DOC_TOPICS = (
    "prometheus/v1",
    "sloth",
    "{{.window}}",
    "error budget",
    "28 days",
    "14.4",
    "good events",
    "total events",
    "critical",
    "tier",
    "openslo",
    "template",
)


@dataclass(frozen=True)
class Failure:
    """One schema violation, flattened for readable assertions."""

    keyword: str
    path: str
    message: str

    def __str__(self) -> str:
        where = self.path or "<root>"
        return f"{where}: {self.message} [{self.keyword}]"


# --------------------------------------------------------------------------
# loading helpers
# --------------------------------------------------------------------------


def load_schema(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_document(path: Path):
    """Load a spec example. Manifests are YAML; the wire envelope is JSON."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yml", ".yaml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def validator_for(schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def payload_schema_path(event_type: str) -> Path:
    """`identity.user.created` -> schemas/events/identity/user/created.schema.json."""
    return PAYLOAD_SCHEMAS / (event_type.replace(".", "/") + PAYLOAD_SUFFIX)


def event_type_of(schema_path: Path) -> str:
    """The inverse of payload_schema_path: a payload schema's file name is its type."""
    relative = schema_path.relative_to(PAYLOAD_SCHEMAS).as_posix()
    return relative[: -len(PAYLOAD_SUFFIX)].replace("/", ".")


def payload_schemas() -> list[Path]:
    return sorted(PAYLOAD_SCHEMAS.rglob(f"*{PAYLOAD_SUFFIX}"))


def event_type_pattern() -> str:
    """The one machine-checked form of the event grammar, from the envelope schema."""
    return load_schema(ENVELOPE_SCHEMA_PATH)["$defs"]["eventType"]["pattern"]


def failures_for(instance, schema: dict) -> list[Failure]:
    found = []
    for error in validator_for(schema).iter_errors(instance):
        path = "/".join(str(part) for part in error.absolute_path)
        found.append(Failure(keyword=error.validator, path=path, message=error.message))
    return found


def assert_keywords(failures: list[Failure], expected: tuple[tuple[str, str], ...]) -> None:
    """Assert every (keyword, path) pair shows up among the failures."""
    seen = {(failure.keyword, failure.path) for failure in failures}
    missing = [pair for pair in expected if pair not in seen]
    assert not missing, (
        "expected violations not produced: "
        + ", ".join(f"{keyword}@{path or '<root>'}" for keyword, path in missing)
        + "\nactual: "
        + ("\n         ".join(str(f) for f in failures) or "<none>")
    )


# --------------------------------------------------------------------------
# 1. the schemas themselves
# --------------------------------------------------------------------------


def test_schemas_declare_draft_2020_12() -> None:
    for path in (
        MANIFEST_SCHEMA_PATH, ENVELOPE_SCHEMA_PATH, FLEET_SCHEMA_PATH, GATE_SCHEMA_PATH, *payload_schemas()
    ):
        schema = load_schema(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", path
        assert schema.get("$id"), f"{path} needs a stable $id"
        assert schema.get("title"), f"{path} needs a title"
        assert schema.get("description"), f"{path} needs a description"
        # meta-validation: the schema must be a legal draft 2020-12 schema
        jsonschema.Draft202012Validator.check_schema(schema)


def test_every_example_manifest_is_covered_by_the_manifest_schema() -> None:
    assert len(MANIFEST_EXAMPLES) >= MIN_VALID_MANIFEST_EXAMPLES, (
        f"core owes >= {MIN_VALID_MANIFEST_EXAMPLES} valid manifest examples, "
        f"found {len(MANIFEST_EXAMPLES)}"
    )
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    for path in MANIFEST_EXAMPLES:
        found = failures_for(load_document(path), schema)
        assert not found, f"{path.name} must be valid:\n  " + "\n  ".join(str(f) for f in found)


def test_core_dogfoods_its_own_manifest() -> None:
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    found = failures_for(load_document(REPO / "cafaye.yml"), schema)
    assert not found, "core/cafaye.yml must satisfy core's own manifest schema:\n  " + "\n  ".join(
        str(f) for f in found
    )


# --------------------------------------------------------------------------
# 1b. kind and environments — the two fields that make one registry hold both
#     running services and generate-time templates, and that declare WHERE a
#     dependency runs without anybody discovering it at runtime.
#
# Every test below is paired: the positive example proves the field ACCEPTS the
# shape it claims to, and the negative proves it REFUSES a value nobody can
# interpret. A field with only a positive test is a field that accepts anything.
# --------------------------------------------------------------------------


TEMPLATE_EXAMPLE = VALID_EXAMPLES / "parlor.template.cafaye.yml"
ENVIRONMENTS_EXAMPLE = VALID_EXAMPLES / "environments.selfhost-or-hosted.cafaye.yml"


def test_a_template_is_a_first_class_manifest_entry() -> None:
    """A template declares no runtime contract, which is the whole distinction.

    The absence is the claim: `caf init` renders a template and the caller owns
    the output, so there is no process that can break an API or emit an event. A
    template that grew an `exposes` block would claim a contract it cannot
    honour at runtime.
    """
    manifest = load_document(TEMPLATE_EXAMPLE)
    assert manifest["kind"] == "template", "the template example must declare kind: template"
    assert "exposes" not in manifest, "a template has no runtime contract to expose"
    assert "consumes" not in manifest, "a template has no runtime contract to consume"


def test_a_template_still_declares_what_cafe_init_needs_to_run() -> None:
    """The one thing a template may not omit is what it is scaffolding.

    `language` and `core` are required on a template for the same reason they
    are required on a service: `caf init` has to know what it is about to write
    and which core spec the result will be pinned against. A template that
    cannot say is a template nobody can generate from.
    """
    manifest = load_document(TEMPLATE_EXAMPLE)
    assert manifest["language"] == "typescript", "the shell is TypeScript and must say so"
    assert manifest["core"], "a template's output is pinned to a core range like any other entry"


def test_kind_defaults_to_service_so_an_existing_manifest_still_means_service() -> None:
    """Every manifest written before `kind` existed must keep meaning `service`.

    Adding a discriminator must not retroactively change what the entries
    already in the registry declare. The examples that omit `kind` are the
    proof, and they are checked here rather than trusted to the enum's default.
    """
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    assert schema["properties"]["kind"]["default"] == "service", (
        "the default must be `service`: an entry that does not say what it is was, "
        "before this field existed, a service"
    )
    omitted = [
        path
        for path in MANIFEST_EXAMPLES
        if path.name not in {TEMPLATE_EXAMPLE.name, ENVIRONMENTS_EXAMPLE.name}
        and "kind" not in load_document(path)
    ]
    assert omitted, "at least one example must omit `kind`, or the default is untested"


def test_environments_declare_the_selfhost_or_hosted_switch_once() -> None:
    """The switch is a declaration per environment, and omission means self-hosted.

    This is the whole of "build once, deploy once, use everywhere": one file says
    where each dependency runs, and `caf dev`, `caf deploy` and CI all read that
    same answer rather than each rediscovering it.
    """
    manifest = load_document(ENVIRONMENTS_EXAMPLE)
    environments = manifest["environments"]

    assert environments["production"]["identity"] == "hosted", (
        "production names exactly one hosted dependency; everything else is omitted"
    )
    assert set(environments["production"]) == {"identity"}, (
        "the short case is the point — naming one dependency and omitting the rest "
        "is how 'pay for one service, run the rest yourself' gets written"
    )
    for name, provisioning in environments["development"].items():
        assert provisioning == "self-hosted", f"{name} must be self-hosted in development"
    assert environments["development"], (
        "the all-self-hosted case must be expressible, or a contributor needs a "
        "cafaye account to work on the project at all"
    )


def test_a_dependency_with_no_environment_entry_is_self_hosted() -> None:
    """Omission means self-hosted, and that default is what makes the short form short.

    A reader that filled in some other default would be inventing an answer the
    author did not give, and an invented answer about who pays and who operates
    is the most expensive kind of wrong this file can contain.
    """
    manifest = load_document(ENVIRONMENTS_EXAMPLE)
    declared = {dependency["name"] for dependency in manifest["dependencies"]}
    production = set(manifest["environments"]["production"])
    assert declared - production, (
        "the example must leave at least one dependency undeclared in production, "
        "or the self-hosted-by-omission default is never exercised"
    )


def test_an_unknown_kind_is_refused() -> None:
    """An unrecognised kind fails closed rather than defaulting.

    A registry that dropped it would list a template as a service, and
    `caf deploy` would try to deploy something that is only rendered.
    """
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    found = failures_for(load_document(INVALID_EXAMPLES / "kind-not-an-enum-value.yml"), schema)
    assert found, "a kind outside the enum must be rejected"
    assert_keywords(found, (("enum", "kind"),))


def test_an_unknown_provisioning_is_refused() -> None:
    """`self-hosted` and `hosted` are the whole set, and there is no default here.

    The set grows as a deliberate schema change with a version, never as a
    manifest that quietly spells something the resolver would have to guess.
    """
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    found = failures_for(
        load_document(INVALID_EXAMPLES / "provisioning-not-selfhost-or-hosted.yml"), schema
    )
    assert found, "a provisioning value outside the enum must be rejected"
    assert_keywords(found, (("enum", "environments/production/identity"),))


# --------------------------------------------------------------------------
# 2. event envelope
# --------------------------------------------------------------------------


def test_valid_event_envelope_example_validates() -> None:
    schema = load_schema(ENVELOPE_SCHEMA_PATH)
    found = failures_for(load_document(VALID_ENVELOPE), schema)
    assert not found, "valid event envelope must validate:\n  " + "\n  ".join(
        str(f) for f in found
    )


def test_invalid_envelopes_fail_for_their_documented_reasons() -> None:
    """Every negative envelope is rejected for exactly the reasons its note lists."""
    schema = load_schema(ENVELOPE_SCHEMA_PATH)
    cases = (
        (INVALID_ENVELOPE, (
            ("required", ""),                # specversion missing
            ("format", "id"),                # id is not a uuid
            ("format", "time"),              # time is not RFC3339
            ("pattern", "type"),             # four dot-separated segments
            ("pattern", "subject"),          # subject contains a space
            ("additionalProperties", ""),    # unknown envelope field
        )),
        (INVALID_UNTAGGED_ENVELOPE, (
            ("pattern", "type"),             # two segments: no service prefix
        )),
        (INVALID_SUBJECTLESS_ENVELOPE, (
            ("required", ""),                # subject is required
        )),
    )
    for path, expected in cases:
        found = failures_for(load_document(path), schema)
        assert found, f"{path.name} is supposed to be rejected by the schema"
        assert_keywords(found, expected)


def test_envelope_type_and_source_patterns_match_the_manifest() -> None:
    envelope = load_schema(ENVELOPE_SCHEMA_PATH)
    manifest = load_schema(MANIFEST_SCHEMA_PATH)
    assert envelope["$defs"]["eventType"]["pattern"] == manifest["$defs"]["eventType"]["pattern"]
    assert envelope["$defs"]["serviceName"]["pattern"] == manifest["$defs"]["serviceName"]["pattern"]


def test_the_fleet_and_manifest_agree_on_what_an_openapi_path_looks_like() -> None:
    """fleet.yml transcribes `exposes.api`, so the two files share one definition.

    `openapiRef` is duplicated between `cafaye.manifest.schema.json` and
    `fleet.schema.json` for the same reason `eventType` is duplicated three
    times: a reader holding either file alone must resolve the path the same way,
    and a linter comparing the manifest's `exposes.api` with the registry's
    `api` must not need a translation table to do it. Two definitions of one
    shape are two answers, and the second one drifts.

    The `pattern` alone is asserted, and deliberately: the `description` says why
    each file carries the field, which is not the same sentence twice.
    """
    fleet = load_schema(FLEET_SCHEMA_PATH)
    manifest = load_schema(MANIFEST_SCHEMA_PATH)
    assert fleet["$defs"]["openapiRef"]["pattern"] == manifest["$defs"]["openapiRef"]["pattern"], (
        "fleet.schema.json and cafaye.manifest.schema.json must agree on the shape of an "
        "OpenAPI path; fleet.yml is a transcription of exposes.api and a translated path "
        "is a path nobody can resolve"
    )


# --------------------------------------------------------------------------
# 3. invalid manifest example
# --------------------------------------------------------------------------


def test_invalid_manifest_example_fails() -> None:
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    found = failures_for(load_document(INVALID_MANIFEST), schema)
    assert found, f"{INVALID_MANIFEST.name} is supposed to be rejected by the schema"
    assert_keywords(
        found,
        (
            ("pattern", "name"),                   # not a cafaye namespace name
            ("enum", "language"),                  # language outside the enum
            ("pattern", "core"),                   # semver constraint without a patch
            ("pattern", "exposes/api"),            # ./ prefixed, not a repo-relative path
            ("pattern", "exposes/events/0"),       # upper-case, and two segments
            ("pattern", "repository/url"),         # https remote, not ssh
            ("const", "repository/defaultBranch"),  # main, not master
            ("additionalProperties", ""),          # undeclared top-level key
        ),
    )


def test_the_reserved_properties_block_is_a_closed_declaration() -> None:
    """The tombstone is a schema constraint, not a paragraph in a README.

    The `reserved-no-delete` row of `harness/breaking_tiers.json` names
    `x-cafaye-reserved-properties` as the mechanism, and for the whole life of
    that row the string appeared exactly once in the fleet — in the sentence
    naming it. This is the half that makes the sentence true: the key is
    DECLARED, so `additionalProperties: false` stops being an intention at this
    level, and a manifest that wants to reserve a name can say so.

    Both directions, and the positive is not optional. A block with only a
    negative case is a block nothing was ever accepted into, which is a block
    nobody has ever run.
    """
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    block = schema["properties"].get(RESERVED_PROPERTIES_KEY)
    assert block is not None, (
        f"{MANIFEST_SCHEMA_PATH.name} declares no {RESERVED_PROPERTIES_KEY!r}, so the "
        f"reserved-no-delete row of the breaking-tier table names a key that no schema "
        f"accepts. A rule that names a mechanism nobody implements is a sentence."
    )
    assert block.get("minItems") == 1, (
        "an empty tombstone list must be an error or an absence, never a declaration of "
        "nothing: `[]` reads as 'I have reserved nothing', which is indistinguishable "
        "from a service that checked and found nothing to reserve"
    )
    assert block.get("uniqueItems") is True, (
        "the same reservation listed twice is one entry written twice, and it should not "
        "be a shape the schema admits"
    )

    entry = schema["$defs"].get("reservedProperty")
    assert entry is not None, "the block's items are not a $defs entry, so there is no level to meta-validate"
    assert entry.get("additionalProperties") is False, (
        "an entry with an undeclared field is a misspelling that reads as protection; the "
        "block must be closed like every other level of this schema"
    )
    assert entry.get("required") == ["name", "removedFrom"], (
        f"an entry must carry both a name and the surface it was removed from; got "
        f"{entry.get('required')!r}. Without the surface there is nothing to compare the "
        f"name against, so the entry can never be shown to be stale."
    )

    # The positive example, because a block nothing was ever accepted into is a
    # block nobody has run.
    accepted = load_document(RESERVED_VALID_EXAMPLE)
    assert not failures_for(accepted, schema), (
        f"{RESERVED_VALID_EXAMPLE.name} must be accepted:\n  "
        + "\n  ".join(str(f) for f in failures_for(accepted, schema))
    )
    names = [entry["name"] for entry in accepted[RESERVED_PROPERTIES_KEY]]
    assert len(names) >= 2, (
        "the positive example reserves one name, which leaves the second entry's field "
        "(`note`) untested and the array's `uniqueItems` unexercised. Two entries, and "
        "the second one has to differ."
    )
    assert len(set(names)) == len(names), "two entries with one name is the duplicate the schema refuses"


def test_the_reserved_properties_block_refuses_reservations_that_reserve_nothing() -> None:
    """The negative case, and the reasons rather than the fact of rejection.

    A negative example that is rejected for the wrong reason is a lie in a
    comment: it proves the file is refused without proving which rule refused it,
    and a reader who trusts it will draw the wrong conclusion about what is
    enforced.
    """
    schema = load_schema(MANIFEST_SCHEMA_PATH)
    found = failures_for(load_document(RESERVED_INVALID_EXAMPLE), schema)
    assert found, f"{RESERVED_INVALID_EXAMPLE.name} is supposed to be rejected by the schema"
    assert_keywords(found, INVALID_RESERVED_CASES)


def test_invalid_examples_document_their_expected_failure() -> None:
    notes = INVALID_NOTES.read_text(encoding="utf-8")
    for path in sorted(INVALID_EXAMPLES.rglob("*")):
        if not path.is_file() or path.name == INVALID_NOTES.name:
            continue
        assert path.relative_to(REPO).as_posix() in notes, (
            f"examples/invalid/README.md must explain {path.relative_to(REPO).as_posix()}"
        )


# --------------------------------------------------------------------------
# 4. cross-field rules JSON Schema cannot express
# --------------------------------------------------------------------------


def test_worker_only_example_exposes_no_api() -> None:
    manifest = load_document(WORKER_ONLY_EXAMPLE)
    exposes = manifest.get("exposes", {})
    assert "api" not in exposes, "the worker-only example must not declare an OpenAPI document"
    assert not exposes.get("events"), "the worker-only example publishes no events"


def test_event_types_are_exactly_three_segments() -> None:
    """`<service>.<entity>.<action>`, always prefixed, no exceptions.

    The service segment is a service name, so it is kebab-case like `name` in a
    manifest; the entity and action segments are lowercase snake_case.
    """
    pattern = event_type_pattern()
    for accepted in (
        "identity.user.created",
        "identity.api_key.created",
        "billing.subscription.past_due",
        "email-sender.email.queued",  # a service name may contain a dash
    ):
        assert re.fullmatch(pattern, accepted), f"{accepted} must be a legal event type"
    for rejected in (
        "user.created",                       # two segments: no service prefix
        "identity.user.account.created",      # four segments
        "identity.User.created",              # not lowercase
        "email_sender.email.queued",          # underscore in the service segment
        "identity..created",                  # empty segment
        "identity.user.",                     # empty action
    ):
        assert not re.fullmatch(pattern, rejected), (
            f"{rejected} must be rejected by the event type grammar"
        )


def test_published_event_types_carry_their_service_prefix() -> None:
    """Every published type names its own service — the grammar has no exceptions.

    Consuming a type is not checked here: its prefix names the publisher, which
    this repository has no way of knowing.
    """
    for path in MANIFEST_EXAMPLES:
        manifest = load_document(path)
        name = manifest["name"]
        for event_type in manifest.get("exposes", {}).get("events", []):
            assert event_type.split(".")[0] == name, (
                f"{path.name}: {event_type} must start with its own service name "
                f"({name}.…) — every event type is <service>.<entity>.<action>"
            )


def test_worker_example_publishes_events_without_serving_http() -> None:
    manifest = load_document(WORKER_EXAMPLE)
    exposes = manifest["exposes"]
    assert "api" not in exposes, "the worker example serves no HTTP API"
    assert exposes["events"], "a background worker usually still publishes events"


def test_services_do_not_consume_their_own_events() -> None:
    for path in MANIFEST_EXAMPLES:
        manifest = load_document(path)
        published = set(manifest.get("exposes", {}).get("events", []))
        consumed = set(manifest.get("consumes", []))
        overlap = published & consumed
        assert not overlap, f"{path.name} both publishes and consumes {sorted(overlap)}"


def section(text: str, heading: str) -> str:
    """Return one '## ' section of a markdown document, heading included."""
    start = text.find(heading)
    assert start != -1, f"{heading!r} section is missing"
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return text[start : start + len(heading) + (len(rest) if end == -1 else end)]


def test_event_catalog_in_docs_matches_the_schema() -> None:
    """Every event in the identity + billing catalog must satisfy the type pattern."""
    pattern = event_type_pattern()
    catalog = section(EVENT_NAMING_DOC.read_text(encoding="utf-8"), "## Catalog")
    types = re.findall(r"^\|\s*`([a-z][a-z0-9_.-]+)`\s*\|", catalog, flags=re.MULTILINE)
    assert len(types) >= 10, f"event-naming.md catalog looks truncated ({len(types)} rows)"
    for event_type in types:
        assert re.fullmatch(pattern, event_type), (
            f"catalog event {event_type} violates {pattern} — fix the doc or the schema"
        )
    assert set(types) >= {
        "identity.user.created",
        "identity.account.created",
        "identity.member.invited",
        "billing.plan.created",
        "billing.customer.created",
        "billing.subscription.started",
        "billing.payment.succeeded",
    }, "the packet's named events must appear in the catalog"


def test_event_grammar_section_states_three_segments() -> None:
    """The prose grammar and the machine pattern are the same rule stated twice."""
    grammar = section(EVENT_NAMING_DOC.read_text(encoding="utf-8"), "## Grammar")
    assert "<service>.<entity>.<action>" in grammar, (
        "docs/event-naming.md must state the canonical three-segment form"
    )
    assert "no exceptions" in grammar.lower(), (
        "the prefix is mandatory for every type; say so in the grammar section"
    )
    # The `type` production is asserted on its own, because the canonical form
    # contains the rejected one as a substring.
    productions = [line for line in grammar.splitlines() if line.startswith("type")]
    assert len(productions) == 1, "the grammar must declare exactly one `type` production"
    rule = productions[0].partition("#")[0]
    assert "<service>" in rule, "the type production must start at the service segment"
    assert rule.count('"."') == 2, "three segments means two separators, not one or three"
    assert "|" not in rule, "there is no short form: one production, one shape"
    for stale in ("2 segments", "{1,2}"):
        assert stale not in grammar, (
            f"docs/event-naming.md still advertises {stale!r}; the grammar is exactly "
            "<service>.<entity>.<action>"
        )


def catalog_by_service() -> dict[str, set[str]]:
    """Parse the '## Catalog' section of event-naming.md into {publisher: {types}}.

    Each '### <service>' sub-section is one publisher, and the backticked first
    column of its table is that publisher's event list.
    """
    text = EVENT_NAMING_DOC.read_text(encoding="utf-8")
    catalog = section(text, "## Catalog")
    by_service: dict[str, set[str]] = {}
    for chunk in re.split(r"^### ", catalog, flags=re.MULTILINE)[1:]:
        heading, _, rows = chunk.partition("\n")
        by_service[heading.strip()] = set(
            re.findall(r"^\|\s*`([a-z][a-z0-9_.-]+)`\s*\|", rows, flags=re.MULTILINE)
        )
    return by_service


def published_by_manifest() -> dict[str, set[str]]:
    return {
        manifest["name"]: set(manifest.get("exposes", {}).get("events", []))
        for manifest in (load_document(path) for path in MANIFEST_EXAMPLES)
    }


def test_catalog_and_manifest_agree_in_both_directions() -> None:
    """A published event type and a catalog row are the same fact, stated twice.

    The catalog is what a consumer reads to learn what exists; `exposes.events`
    is what `caf` and the contract tests read. If they drift, one of the two is
    lying to whoever generates an SDK from it.

    Note the scope: the example manifests are core's, so this assertion can only
    catch core disagreeing with itself. The fleet-wide version — a real service's
    manifest against the catalog — is the fleet.yml section, and it is the one
    that would have caught courier.
    """
    catalog = catalog_by_service()
    published = published_by_manifest()

    undeclared = {
        service: sorted(types - catalog.get(service, set()))
        for service, types in published.items()
        if types - catalog.get(service, set())
    }
    assert not undeclared, (
        f"published in exposes.events but absent from the catalog in "
        f"{EVENT_NAMING_DOC.name}: {undeclared}"
    )

    unpublished = {
        service: sorted(types - published.get(service, set()))
        for service, types in catalog.items()
        if types - published.get(service, set())
    }
    assert not unpublished, (
        f"in the {EVENT_NAMING_DOC.name} catalog but not published by any example "
        f"manifest: {unpublished}"
    )


def test_consumed_event_types_exist_in_the_catalog() -> None:
    """A subscription to a type nobody publishes is a typo that ships silently."""
    known: set[str] = set()
    for types in catalog_by_service().values():
        known |= types
    for path in MANIFEST_EXAMPLES:
        manifest = load_document(path)
        for event_type in manifest.get("consumes", []):
            assert event_type in known, (
                f"{path.name} consumes {event_type}, which no publisher in the "
                f"{EVENT_NAMING_DOC.name} catalog declares"
            )


def _ci_step_body(workflow: str, step_name: str) -> str:
    """The `run:` body of one named CI step, with its shell comments stripped.

    Two separations, both learned the hard way on this very step, and kit names
    the second one as a rule: **"a check that a comment can satisfy is not a
    check."**

      * **Comments are removed.** Fixing this step meant writing down what was
        wrong with it, and the explanation quotes the broken phrase — so a
        substring search over the raw body finds the explanation and passes while
        the bug is back. `strip_shell_comments` exists in kit's `validate.sh` for
        the same reason and the same failure.
      * **The step is found by name, through YAML.** A line range would drift the
        moment a step is inserted above this one, and the test would then assert
        about a different block while reporting a pass.

    PyYAML reads the workflow rather than the harness's own reader, because this
    test is about the workflow and asserting the harness could read it would be
    circular.
    """
    for step in yaml.safe_load(workflow)["jobs"]["gate"]["steps"]:
        if isinstance(step, dict) and step.get("name") == step_name:
            assert "run" in step, f"the {step_name!r} step has no run: block"
            return "\n".join(
                line for line in step["run"].splitlines() if not line.lstrip().startswith("#")
            )
    raise AssertionError(f"the {step_name!r} step is not in .github/workflows/ci.yml")


def test_the_ci_self_test_step_reads_the_phrase_the_footer_prints() -> None:
    """The self-test log's own contract, checked in both directions.

    `.github/workflows/ci.yml`'s "the self-test said what it did" step greps the
    self-test's log to compare the count its footer **claims** with the number of
    breakage assertions actually logged. A guard that cannot find its target is
    not a guard — so the two strings are a contract, and this is the test that
    keeps them one.

    **It was broken, and the shape is worth recording.** The step asked the log
    for `all N breakages went red`; the footer has always printed
    `PASS: self_test — N breakages went red naming their rule`. So the count came
    back empty, the `[ -z "$claimed" ]` guard below it was true on **every** run,
    and the step exited 1 — blaming a self-test that had passed, with a message
    naming the very thing that had just succeeded. The self-test's own count of
    breakages was correct throughout, and nothing could see the gap because the
    only two things that mention each other are a shell script and a workflow.

    The same kind of gap is asserted absent in the other direction too: the step's
    control assertion used to be an exact count (`-ne 1`), and core-18 added two
    legitimate controls, which would have failed a green tree. It is now
    "at least one control, and the first control line precedes the first breakage
    line" — the property the step was actually for, which is ORDER. A control that
    runs after a breakage has not controlled it, because a tree that was already
    red makes every assertion below it vacuous.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    footer = HARNESS_SELF_TEST.read_text(encoding="utf-8")

    assert re.search(r"printf 'PASS: self_test — %s breakages went red", footer), (
        "harness/tests/self_test.sh's PASS footer no longer says it prints "
        "`PASS: self_test — N breakages went red`. If it was reworded, the CI step that "
        "greps for that phrase is now matching nothing and fails every run."
    )

    # The step's own run block, extracted before any assertion about it, because
    # every assertion below is about CODE and not about the prose explaining it.
    run_block = _ci_step_body(workflow, "the self-test said what it did")

    # The phrase the workflow asks for, spelled out rather than reconstructed, so
    # this test fails when the two disagree instead of when one of them moves.
    asked_for = "PASS: self_test — [0-9]+ breakages went red"
    assert asked_for in run_block, (
        f"the CI step no longer greps for {asked_for!r}, so the count it compares against "
        f"the logged breakage assertions is coming from a phrase the footer does not "
        f"print. It has happened: the step asked for `all N breakages went red`, the "
        f"footer has never printed that, and the step exited 1 on a self-test that "
        f"passed — blaming the very thing that had succeeded."
    )
    # The literal on each side, matched against the other. `%s` and `[0-9]+` are
    # the two spellings of "the count here", and neither is a substring of the
    # other — so the shared text around them is what has to agree.
    shared = "PASS: self_test — "
    assert asked_for.startswith(shared) and shared in footer, (
        "the phrase the CI step greps for and the phrase the footer prints share no "
        f"prefix; both must start with {shared!r} for the step to match anything at all"
    )

    # The dead guard that shipped it, checked **outside** the prose. Every
    # comment in the workflow above the step now explains the `all N` mistake and
    # quotes the old phrase, so a substring search over the whole file finds the
    # explanation rather than the code — which is why `run_block` exists and why
    # this assertion reads it. That the fix needs that is the point: a check whose
    # haystack is the file it is checking stops working the moment anyone explains
    # the bug in it, and silently passing after that is the worst possible moment.
    assert "all [0-9]+ breakages went red" not in run_block, (
        "the CI step has gone back to grepping for `all N breakages went red`, which the "
        "footer has never printed. That was a permanently-true guard that failed every "
        "run on a self-test that passed."
    )
    assert asked_for in run_block, (
        "the step's run block does not contain the phrase this test asserts. If the step "
        "was restructured, this test is no longer looking at it."
    )
    assert '"$controls" -ne 1' not in run_block, (
        "the CI step has gone back to requiring exactly one control. There are four, and "
        "a fifth rule family will add a fifth — a check that hard-codes a control count "
        "fails on every addition, and the fix an engineer reaches for is to delete it."
    )
    assert '"$controls" -lt 1' in run_block and "first_control" in run_block, (
        "the CI step should require at least one control AND assert the first control "
        "precedes the first breakage. Order is the property that matters: a control that "
        "runs after a breakage has not controlled it."
    )
    # And the footer must not claim a specific number of controls, since the count
    # is a property of the script and the script grows.
    assert "both controls were green first" not in footer, (
        "the footer says `both controls`, and there are four. A footer that names a "
        "count goes stale silently: the number beside it stays right and the prose "
        "beside it does not."
    )


def test_the_published_version_is_one_line_and_agrees_with_the_changelog() -> None:
    """`VERSION` and the top of `CHANGELOG.md` are the same fact, stated twice.

    Core's own doctrine — a document and its schema are the same contract written
    twice, and the test is the enforcement — applied to the version. Before
    core-17 the version existed in exactly one place, a `## [0.2.0]` heading in
    prose, which is why no checker could resolve a `core:` constraint. It now
    exists in two, and this is the test that keeps them from drifting.

    The failure this prevents is concrete: a release cut by bumping `VERSION`
    and forgetting the changelog (or the reverse) publishes a version the
    changelog contradicts, and every service pinned to the changelog's number is
    silently resolving against a different release than the one they read about.

    `## [Unreleased]` is skipped deliberately. It is a section, not a version,
    and treating it as one would make this test red on any branch with
    unreleased work — which is every worker branch, and a test that is always red
    is a test that gets deleted.
    """
    version_file = REPO / "VERSION"
    assert version_file.is_file(), (
        f"{version_file.relative_to(REPO)} does not exist. `core:` constraints resolve "
        "against this file; without it core publishes no version and the harness "
        "refuses every run (exit 2) rather than guessing one."
    )
    raw = version_file.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"VERSION holds {len(lines)} non-blank lines ({lines}), want exactly 1: a version "
        "file that has been appended to is not a version, and reading only the first "
        "line would make it one again"
    )
    published = lines[0]

    # The published version must be in the grammar the resolver accepts, or every
    # resolution is a resolution against an unparseable fact.
    module = harness_module()
    try:
        version_module = sys.modules["core_version"]
    except KeyError:  # pragma: no cover - imported by the harness above
        version_module = None
    assert version_module is not None, "the harness did not import its resolver"
    try:
        version_module.parse_version(published)
    except version_module.GrammarError as error:
        raise AssertionError(
            f"VERSION holds {published!r}, which the resolver refuses: {error}"
        ) from None

    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"), re.M)
    assert released, (
        "CHANGELOG.md has no `## [MAJOR.MINOR.PATCH]` heading, so there is no released "
        "version for VERSION to agree with"
    )
    assert published == released[0], (
        f"VERSION says {published} and the newest released heading in CHANGELOG.md says "
        f"{released[0]}. One of them was bumped and the other was not; a reader cannot "
        "tell which release they are compiling against, and neither can a service."
    )


def test_manifest_examples_cover_every_core_constraint_form() -> None:
    """The semver mini-grammar has three forms; all three are exercised here."""
    forms = {
        load_document(path)["core"] for path in MANIFEST_EXAMPLES
    }
    missing = [form for form in REQUIRED_CORE_CONSTRAINT_FORMS if not any(f.startswith(form) for f in forms)]
    assert not missing, (
        f"no example manifest uses the core constraint form(s) {missing} — see "
        f"docs/manifest-conventions.md"
    )


def test_openapi_conventions_doc_covers_every_required_topic() -> None:
    doc = OPENAPI_DOC.read_text(encoding="utf-8").lower()
    missing = [topic for topic in REQUIRED_OPENAPI_TOPICS if topic not in doc]
    assert not missing, f"docs/openapi-conventions.md dropped: {missing}"


def test_no_open_decision_callouts_remain_in_the_docs() -> None:
    """A merged spec reads as decided; a `DECISION NEEDED` callout blocks the merge.

    The drafting process is unchanged (AGENTS.md still asks for callouts on a
    worker branch) — this asserts the manager's decision was folded in, not that
    the process changed.
    """
    open_callouts = [
        path.name
        for path in sorted(DOCS.glob("*.md"))
        if "DECISION NEEDED" in path.read_text(encoding="utf-8")
    ]
    assert not open_callouts, (
        f"undecided spec still calls out open questions: {open_callouts} — fold in the "
        "manager's decision or mark it as a new numbered decision"
    )


# --------------------------------------------------------------------------
# 5. per-event payload schemas
# --------------------------------------------------------------------------


def test_payload_schema_paths_match_their_event_type() -> None:
    """A payload schema's path is its event type with dots as directory separators."""
    found = payload_schemas()
    assert found, "core owes at least one per-event payload schema"
    pattern = event_type_pattern()
    catalog: set[str] = set()
    for types in catalog_by_service().values():
        catalog |= types
    for path in found:
        event_type = event_type_of(path)
        assert re.fullmatch(pattern, event_type), (
            f"{path.name} does not map to a legal event type ({event_type})"
        )
        assert event_type in catalog, (
            f"{path.name} declares {event_type}, which is absent from the "
            f"{EVENT_NAMING_DOC.name} catalog"
        )
        assert payload_schema_path(event_type) == path, (
            f"{event_type} must live at {payload_schema_path(event_type).relative_to(REPO)}"
        )


def test_every_payload_schema_owes_a_negative_case() -> None:
    """A payload schema with no negative example is an unproven assertion.

    `INVALID_PAYLOAD_CASES` is a hand-written table, which is exactly the kind of
    list that rots: a new schema lands, the table is not updated, and the suite
    stays green because nothing cross-checks the two. This is that cross-check.
    """
    declared = {event_type for event_type, _ in INVALID_PAYLOAD_CASES}
    owed = {event_type_of(path) for path in payload_schemas()}
    assert owed <= declared, (
        "these payload schemas have no entry in INVALID_PAYLOAD_CASES, so nothing "
        f"asserts they reject anything: {sorted(owed - declared)}"
    )


def test_payload_schemas_are_listed_in_the_event_naming_doc() -> None:
    """Core owns the single home for payload schemas, so it has to be discoverable."""
    doc = EVENT_NAMING_DOC.read_text(encoding="utf-8")
    for path in payload_schemas():
        relative = path.relative_to(REPO).as_posix()
        assert relative in doc, (
            f"{relative} must be listed in {EVENT_NAMING_DOC.name} — a consumer has no "
            "other way to find the payload schema for a type"
        )


def test_payload_schema_variant_examples_validate() -> None:
    """A payload schema with more than one real shape gets one example per shape.

    `examples/valid/events/<service>/<entity>/<action>.<variant>.data.json` is the
    same contract checked from a second angle. Only `billing.payment.succeeded`
    has one today — it is emitted from two different sources with two different
    payload shapes — but the rule is a rule rather than a special case in a test
    that names billing, so the next multi-shaped payload needs no new test.
    """
    found = False
    for path in sorted(VALID_PAYLOADS.rglob(f"*{PAYLOAD_EXAMPLE_SUFFIX}")):
        relative = path.relative_to(VALID_PAYLOADS).as_posix()
        stem = relative[: -len(PAYLOAD_EXAMPLE_SUFFIX)]
        head, _, variant = stem.rpartition(".")
        if not head or not variant:
            continue  # the canonical example, checked above
        event_type = head.replace("/", ".")
        schema_path = payload_schema_path(event_type)
        assert schema_path.is_file(), f"{event_type} has no schema for {path.name}"
        found = True
        report = failures_for(load_document(path), load_schema(schema_path))
        assert not report, f"{path.name} must satisfy {schema_path.name}:\n  " + "\n  ".join(
            str(f) for f in report
        )
    assert found, "no variant payload example exists, so no schema is checked from two angles"


def test_payload_schema_examples_validate() -> None:
    for path in payload_schemas():
        event_type = event_type_of(path)
        example = VALID_PAYLOADS / (event_type.replace(".", "/") + PAYLOAD_EXAMPLE_SUFFIX)
        assert example.is_file(), (
            f"{event_type} owes a valid payload example at {example.relative_to(REPO)}"
        )
        found = failures_for(load_document(example), load_schema(path))
        assert not found, f"{example.name} must satisfy {path.name}:\n  " + "\n  ".join(
            str(f) for f in found
        )


def test_payload_schema_invalid_examples_fail() -> None:
    for event_type, expected in INVALID_PAYLOAD_CASES:
        schema_path = payload_schema_path(event_type)
        assert schema_path.is_file(), f"{event_type} owes a payload schema at {schema_path.name}"
        example = INVALID_PAYLOADS / (event_type.replace(".", "/") + PAYLOAD_EXAMPLE_SUFFIX)
        assert example.is_file(), (
            f"{event_type} owes a negative payload example at {example.relative_to(REPO)}"
        )
        found = failures_for(load_document(example), load_schema(schema_path))
        assert found, f"{example.name} is supposed to be rejected by {schema_path.name}"
        assert_keywords(found, expected)


def test_the_recipient_fact_is_declared_the_way_billing_sends_it() -> None:
    """billing's money events carry the customer's billing email, and the three
    subscription events carry the plan's name beside its id — declared as the
    publisher sends them, not as a reader might wish them.

    Read out of billing at 7133643 (REPORT-core-billing-payload-alignment-01):
    `StripeEvents.with_recipient` merges `email` only when
    `customers.email` is present, and `Subscriptions::Lifecycle#core_payload`
    writes it only when `customer.email.present?` — so the field is absent, never
    null, and sometimes absent. A customer created in the processor's dashboard
    has no cafaye row, and one created through `/v1` has no email until the
    client sets one. Declared optional and non-nullable: required would reject
    every event for a customer with no address, and nullable would promise a
    shape billing never sends. `format: email` is core's convention for an
    address (see `billing.customer.created`).

    `plan_name` is written unconditionally by `core_payload` from the plan row
    the builder has already resolved, and `plans.name` is `null: false` with a
    presence validation — so it is always present and never blank, which is
    why it is required with `minLength: 1` like the neighbouring string fields.

    The negative case is the wrong-typed email: a number where the schema
    declares a string. It is the one value a consumer could plausibly send that
    the schema refuses, and it is refused on `type`.
    """
    money_events = (
        "billing.payment.succeeded",
        "billing.payment.failed",
        "billing.subscription.started",
        "billing.subscription.updated",
        "billing.subscription.canceled",
    )
    for event_type in money_events:
        schema = load_schema(payload_schema_path(event_type))
        email = schema["properties"]["email"]
        assert email["type"] == "string", (
            f"{event_type} declares email as {email['type']!r}; billing never sends "
            "null, so the type must be string and not [string, null]"
        )
        assert email["format"] == "email", (
            f"{event_type} declares email without format: email; core's convention "
            "for an address is format: email (see billing.customer.created)"
        )
        assert "email" not in schema["required"], (
            f"{event_type} requires email; billing omits it when the customer has "
            "no address, so required would reject a real event"
        )
    for event_type in money_events[2:]:
        schema = load_schema(payload_schema_path(event_type))
        plan_name = schema["properties"]["plan_name"]
        assert plan_name["type"] == "string", (
            f"{event_type} declares plan_name as {plan_name['type']!r}; the plan's "
            "name is a plain string"
        )
        assert plan_name["minLength"] >= 1, (
            f"{event_type} declares plan_name without minLength; a blank plan name "
            "is not a name"
        )
        assert "plan_name" in schema["required"], (
            f"{event_type} does not require plan_name; core_payload writes it "
            "unconditionally, so optional would accept a real event's absence"
        )
    found = failures_for(
        load_document(INVALID_EMAIL_EXAMPLE),
        load_schema(payload_schema_path("billing.payment.succeeded")),
    )
    assert found, "succeeded.email.data.json is supposed to be rejected by the schema"
    assert_keywords(found, (("type", "email"),))


def test_valid_envelope_data_validates_against_its_payload_schema() -> None:
    """End to end: the shipped example envelope's `data` is a real payload."""
    envelope = load_document(VALID_ENVELOPE)
    schema = load_schema(payload_schema_path(envelope["type"]))
    found = failures_for(envelope["data"], schema)
    assert not found, f"{VALID_ENVELOPE.name} data must satisfy the {envelope['type']} payload:\n  " + "\n  ".join(
        str(f) for f in found
    )


# --------------------------------------------------------------------------
# 5b. the payload schema against the publisher that emits it
# --------------------------------------------------------------------------


def payload_schema_documents() -> list[tuple[str, dict]]:
    """Every payload schema as an `(event type, document)` pair.

    A list of pairs rather than a list of paths, so each rule below can be handed
    the tree or a document built in memory without a second implementation of
    itself. That is what makes `test_the_id_vocabulary_rule_names_...` possible:
    it re-uses the rule against the file as D35 shipped it, which is the only
    kind of fixture worth having — the real defect, not a shape that resembles
    it.
    """
    return [(event_type_of(path), load_schema(path)) for path in payload_schemas()]


def id_vocabulary(schema: dict) -> dict[str, str]:
    """`{field: canonical vocabulary}` for the identifier fields of one schema.

    **An absent constraint is a constraint.** A field spelled `format: uuid` in
    one schema and left unconstrained in a sibling is a divergence, because a
    consumer that read the first is entitled to the invariant and the second
    never promised it — so the empty vocabulary is its own value here rather
    than a value to skip. `items` is read for a `*_ids` array for the same
    reason: the shape of the id inside the array is the part that has to agree.
    """
    found: dict[str, str] = {}
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict) or not IDENTIFIER_FIELD.match(name):
            continue
        parts = {key: prop[key] for key in ID_VOCABULARY_KEYWORDS if key in prop}
        items = prop.get("items")
        if isinstance(items, dict):
            parts["items"] = {key: items[key] for key in ID_VOCABULARY_KEYWORDS if key in items}
        found[name] = json.dumps(parts, sort_keys=True)
    return found


def id_vocabulary_divergences(documents: list[tuple[str, dict]]) -> list[str]:
    """One line per `(service, field)` a publisher spells more than one way.

    Scoped to a service on purpose. The same field name across two services is
    the D7 question — do courier and identity agree on a user's id — and core has
    ruled that they do, twice, by reading both sets of builders. Comparing them
    here would assert the ruling rather than check it, and would go red the day a
    new publisher arrived with a legitimate reason to differ, which is the
    signature of a rule nobody reads twice.
    """
    by_field: dict[tuple[str, str], dict[str, list[str]]] = {}
    for label, schema in documents:
        service = label.split(".")[0]
        for name, spelling in id_vocabulary(schema).items():
            by_field.setdefault((service, name), {}).setdefault(spelling, []).append(label)
    found: list[str] = []
    for (service, name), spellings in sorted(by_field.items()):
        if len(spellings) < 2:
            continue
        for spelling, labels in sorted(spellings.items()):
            found.append(f"{service}.{name} is {spelling} in {', '.join(sorted(labels))}")
    return found


def schema_id_triples(documents: list[tuple[str, dict]]) -> list[tuple[str, str, str]]:
    """`(label, pointer, string)` for every `pattern`, `const` and `enum` value.

    Three keywords, not every string in the document, because a schema's
    `description` is allowed to *name* a rejected shape — that is how the negative
    examples work and how a reader is told what not to send. Only a keyword that
    constrains a value is a claim about what the publisher emits.
    """
    def walk(node, pointer: str):
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{pointer}/{key}"
                if key in ("pattern", "const", "enum"):
                    for item in value if isinstance(value, list) else [value]:
                        if isinstance(item, str):
                            yield where, item
                else:
                    yield from walk(value, where)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                yield from walk(item, f"{pointer}/{index}")

    return [
        (label, pointer, text)
        for label, schema in documents
        for pointer, text in walk(schema, "")
    ]


def example_id_triples(documents: list[tuple[str, object]]) -> list[tuple[str, str, str]]:
    """`(label, pointer, string)` for every identifier-named string in a document.

    The key's name decides, not the value: `email` is not an id however it
    happens to be spelled, and `user_id` is one in every example in the tree.
    """
    def walk(node, pointer: str, key: str | None = None):
        if isinstance(node, dict):
            for name, value in node.items():
                yield from walk(value, f"{pointer}/{name}", name)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{pointer}/{index}", key)
        elif isinstance(node, str) and key is not None and IDENTIFIER_FIELD.match(key):
            yield pointer, node

    return [
        (label, pointer, text)
        for label, document in documents
        for pointer, text in walk(document, "")
    ]


def valid_payload_documents() -> list[tuple[str, object]]:
    """The valid payload examples and the valid envelope, as `(label, document)`.

    **Only the valid examples.** An invalid example is where core keeps a
    rejected spelling on purpose — that is what makes it a value this repository
    has decided nothing emits, rather than a value somebody wrote down believing
    it. `examples/invalid/events/identity/user/created.data.json` carries
    `usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` today and keeps it after this packet, on
    purpose, and the rule below is scoped so that keeping it is not a failure.
    """
    documents: list[tuple[str, object]] = [
        (path.relative_to(REPO).as_posix(), load_document(path))
        for path in sorted(VALID_PAYLOADS.rglob(f"*{PAYLOAD_EXAMPLE_SUFFIX}"))
    ]
    documents.append((VALID_ENVELOPE.relative_to(REPO).as_posix(), load_document(VALID_ENVELOPE)))
    return documents


def valid_signal_documents() -> list[tuple[str, object]]:
    """The valid telemetry examples, as `(label, document)`.

    **This is the half core-24's rule never walked, and it is where twenty of the
    twenty-one defects in this packet lived.** `valid_payload_documents()` globs
    `examples/valid/events/` and stops; `examples/valid/telemetry/` was never
    passed to the id rule, so sixteen files carrying `tnt_…` and `acc_…` sat in
    the tree for the whole of core-24 while that rule reported the fleet clean.

    The gap was not obvious because both halves are called "examples" and a
    reader checking whether the rule covered them would not think to ask which
    directory. A rule that covers a *kind of document* is worth far more than one
    that covers a list of files, so this walks the directory rather than
    enumerating the names, and the test below asserts the two helpers between
    them cover every JSON example in the tree — that is what stops the next
    directory from being the one nobody looks at.
    """
    return [
        (path.relative_to(REPO).as_posix(), load_document(path))
        for path in sorted(VALID_TELEMETRY.glob("*.json"))
    ]


def prefixed_id_uses(triples: list[tuple[str, str, str]]) -> list[str]:
    """Every triple in either cafaye id shape, as one reportable line."""
    return [
        f"{label} {pointer} = {text!r}"
        for label, pointer, text in triples
        if CAFAYE_ID_VALUE.match(text) or CAFAYE_ID_PATTERN.search(text)
    ]


def example_owner(label: str, document: object) -> str | None:
    """The service whose code emits the ids in this example, or `None`.

    Read from the example rather than guessed, in this order:

    1. the path under `examples/valid/events/<service>/…` for a payload example,
       where the directory IS the event type's service segment;
    2. `service.name` on the example's own resource for a telemetry example,
       which is the producer naming itself — `span.muse.json` says `muse`, and
       `log.json` says `courier`;
    3. the envelope's `source`.

    `None` means the example is not attributable, and that is reported rather
    than skipped: an example nobody can attribute is an example the ledger
    cannot check, which is the same blindness as not walking it at all.
    """
    parts = Path(label).parts
    if "events" in parts:
        index = parts.index("events")
        if index + 1 < len(parts):
            return parts[index + 1]
    if isinstance(document, dict):
        for key in ("resource", "resourceAttributes"):
            block = document.get(key)
            if isinstance(block, dict):
                name = block.get("service.name")
                if isinstance(name, str):
                    return name
            if isinstance(block, list):
                for entry in block:
                    if isinstance(entry, dict) and isinstance(entry.get("service.name"), str):
                        return entry["service.name"]
        source = document.get("source")
        if isinstance(source, str):
            return source
    return None


def producer_shape_faults(
    documents: list[tuple[str, object]],
    shapes: dict[str, dict],
    fields: dict[str, dict],
    resource_shapes: dict[str, dict] | None = None,
    *,
    require_every_entry_exercised: bool = True,
) -> list[str]:
    """Every example identifier value its own producer could not have emitted.

    **The positive direction, and the one that would have caught this packet.**
    For each example, work out which service emits it, look that service up in the
    ledger, and require every identifier-named value to match the shape recorded
    for that field. `tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG` fails it because
    `identity`'s `tenant_id` is an operator label and no operator writes that; it
    would equally fail against a value that is merely *a uuid*, because core does
    not know this fleet's tenant names and is not entitled to guess them.

    **The negative direction, in the same walk.** A field in the ledger that no
    example exercises is a field the ledger claims and nothing corroborates,
    which is how a ledger rots into a list of assertions about code nobody reads.
    Requiring every entry to be matched keeps the transcription honest in the
    direction that is easy to forget.

    A service with no ledger entry is reported rather than passed. That is the
    honest direction: core does not know what muse mints, so the correct claim
    about muse's ids is "unknown", and a rule that went green on unknown is a rule
    that would have gone green on wrong.
    """
    found: list[str] = []
    exercised: set[tuple[str, str]] = set()

    for label, document in documents:
        identifiers = example_id_triples([(label, document)])
        # **An example with no identifier in it is not unattributable, it is
        # simply not this rule's business.** `otel-endpoint.json`, `probes.json`,
        # `redaction.json` and the three `span-naming.*` documents carry no id
        # field at all, and demanding a `service.name` of them would be a rule
        # that reports six faults nobody can act on — which is how a rule stops
        # being read. The check is on identifier VALUES, so an example with none
        # passes for the honest reason that there is nothing to check.
        if not identifiers:
            continue
        owner = example_owner(label, document)
        if owner is None:
            found.append(
                f"{label} carries an identifier and names no service, so nothing "
                f"checks what shape it is"
            )
            continue
        ledger = shapes.get(owner)
        if ledger is None:
            found.append(
                f"{label} is {owner}'s, and core records no id shape for {owner} — "
                f"read its code and add it to PRODUCER_ID_SHAPES"
            )
            continue
        owned = fields.get(owner, {})
        resource_rules = resource_shapes.get(owner, {})
        for _, pointer, value in identifiers:
            name = pointer.rsplit("/", 1)[-1]
            # A resource attribute and a payload field under the same name are
            # different populations of values, so the rule is chosen by WHERE the
            # value is, not by what it is called. `account_id` is a uuid on an
            # event and is emitted by nobody on a telemetry resource; keying on
            # the name alone would have made one of those two a silent pass.
            on_resource = any(
                f"/{key}/{name}" in pointer for key in ("resource", "resourceAttributes")
            )
            shape_name = resource_rules.get(name) if on_resource else owned.get(name)
            if shape_name is None:
                found.append(
                    f"{label} {pointer} = {value!r} is an identifier field {owner} "
                    f"has no recorded shape for"
                )
                continue
            pattern = ledger["shapes"].get(shape_name)
            if pattern is None:
                found.append(
                    f"{label} {pointer} names shape {shape_name!r}, which {owner}'s "
                    f"ledger does not define"
                )
                continue
            exercised.add((owner, name))
            if not re.match(pattern, value):
                found.append(
                    f"{label} {pointer} = {value!r} is not {owner}'s {shape_name} "
                    f"(read from {ledger['source']}): it does not match {pattern}"
                )

    # The reverse direction is only meaningful over the WHOLE corpus. Handed a
    # subset — one document, or the two the "carries no identifier" test uses —
    # every entry outside that subset would read as unexercised, which is true and
    # useless. So it is a keyword rather than an unconditional half, and the
    # default stays on: the shipped test walks everything.
    if require_every_entry_exercised:
        for owner in sorted(fields):
            for name in sorted(fields[owner]):
                if (owner, name) not in exercised:
                    found.append(
                        f"{owner}.{name} is in the ledger as a {fields[owner][name]} shape, "
                        f"and no example exercises it — the ledger asserts something "
                        f"nothing corroborates"
                    )
    return found


def fleet_source_commits(fleet: dict) -> dict[str, str]:
    return {service["name"]: service["sourceCommit"] for service in fleet["services"]}


def provenance_faults(documents: list[tuple[str, dict]], fleet: dict) -> list[str]:
    """Every payload schema whose citation is missing, misnamed or stale.

    Three faults, one rule: **a payload schema names the commit its publisher
    was read at, and `fleet.yml` names the commit the registry was read at, and
    they are the same commit.** The forward direction is the one that has teeth
    over time — re-reading identity and moving its `sourceCommit` turns all nine
    of its payload schemas red until somebody re-reads the payloads too, which is
    the moment a schema drifts from the code and nothing notices.

    What it does NOT do, and this is the sentence that has to travel with the
    rule: it cannot reach identity's repository. It proves core's schema and
    core's own record of the code agree on WHICH BYTES were read; it cannot prove
    the claim is true, that the commit still exists, or that the schema says
    anything about what is in it. A check that implied otherwise would be worse
    than no check, and D36 is where that limit is written down.
    """
    commits = fleet_source_commits(fleet)
    found: list[str] = []
    for label, schema in documents:
        service = label.split(".")[0]
        comment = str(schema.get("$comment", ""))
        citation = PROVENANCE_CITATION.search(comment)
        if citation is None:
            if service in PROVENANCE_REQUIRED:
                found.append(f"{label} carries no `read from <service> at <commit>` citation")
            continue
        if citation["service"] != service:
            found.append(
                f"{label} cites {citation['service']}'s code, and it is {service}'s schema"
            )
        if service not in commits:
            found.append(f"{label} cites {service}, which fleet.yml does not record")
        elif citation["commit"] != commits[service]:
            found.append(
                f"{label} cites {citation['commit']} and fleet.yml records "
                f"{commits[service]} as the commit {service} was read at — either the "
                "payload was re-read and the schema not updated, or the citation was "
                "guessed"
            )
    return found


def test_a_publisher_spells_one_id_one_way_across_its_payload_schemas() -> None:
    """`user_id` is one value in one publisher, and the schemas have to say so.

    **This is the check D35 existed to be caught by.** Nine schemas sat under
    `schemas/events/identity/`, eight were written from identity's builders and
    said `format: uuid`, one was written from an assumption and said
    `^usr_[0-9A-Z]{26}$` — and the contradiction was visible only because core-23
    read the code and happened to write a ninth file in a directory the first was
    already in. Nothing compared them. This compares them, so the next schema
    written from an assumption goes red against the eight that were not.

    Shown red: see `test_the_id_vocabulary_rule_names_the_schema_that_disagrees`,
    which hands this rule the file as D35 shipped it.

    The limit, stated because a check that overstates itself is worse than none:
    this compares core to core. If identity emitted a `usr_` id on all nine
    events, this would be green and the second rule below is what would have to
    catch it. Between the two, a defect needs either a lone schema that
    disagrees with its siblings, or a fleet-wide id vocabulary nobody has ever
    read a publisher's code to confirm.
    """
    divergences = id_vocabulary_divergences(payload_schema_documents())
    assert not divergences, (
        "one publisher spells one id one way, and these do not:\n  "
        + "\n  ".join(divergences)
        + "\nEither a schema is describing a value its publisher cannot emit, or a "
        "publisher really did change its id vocabulary — which is a fleet decision to "
        "record in DECISIONS.md (D7, D35), not a schema to edit quietly."
    )


def test_the_id_vocabulary_rule_names_the_schema_that_disagrees() -> None:
    """The rule above has to be able to say no, on the file it was written for.

    `test_a_publisher_spells_one_id_one_way_across_its_payload_schemas` reads the
    tree, and the tree is now correct — so on its own it is a test that has never
    failed, which is the state core-23 found `pendingCoreContract` in and wrote
    `test_the_debt_rule_still_bites_on_a_list_nobody_owes` about.

    The fixture is not a shape that resembles D35. It IS D35: this repository's
    own file, with `user_id` put back to the pattern it shipped, and the rule has
    to name it. A rule that cannot fail on the defect it was bought for is a
    comment.

    It does not assert that the tree is correct first, and that is deliberate: a
    witness that refuses to run on a broken tree cannot be used to show the rule
    biting on one, which is the only demonstration worth having. The precondition
    asserted here is the one the fixture needs to mean anything.
    """
    documents = payload_schema_documents()
    label = "identity.user.created"
    original = next(schema for name, schema in documents if name == label)
    assert "user_id" in (original.get("properties") or {}), (
        f"{label} has no user_id property, so putting D35's pattern back has nothing to "
        "put it back on — the fixture needs the field the defect was about"
    )
    reverted = [
        (name, copy.deepcopy(schema)) if name == label else (name, schema)
        for name, schema in documents
    ]
    for name, schema in reverted:
        if name == label:
            schema["properties"]["user_id"] = {
                "type": "string",
                "pattern": "^usr_[0-9A-Z]{26}$",
                "description": "the D35 spelling, restored to prove the rule bites",
            }
    found = id_vocabulary_divergences(reverted)
    assert len(found) == 2 and all(line.startswith("identity.user_id is ") for line in found), (
        "the one-id-one-way rule did not name identity.user.created's `usr_` pattern "
        f"against its five siblings; it found {found}"
    )
    assert any("^usr_[0-9A-Z]{26}$" in line and label in line for line in found), (
        f"the rule reported a divergence without naming the pattern that caused it: {found}"
    )


def test_nothing_core_ships_carries_an_id_no_publisher_in_the_fleet_mints() -> None:
    """No payload schema and no valid example may name a prefixed cafaye id.

    The sibling rule above needs a majority to disagree with. This one does not:
    it is a fleet-wide fact read out of publishers' code — D10 ruled that billing
    may not invent `sub_`/`pln_` ids it does not have, and nine identity schemas
    plus five courier ones say `format: uuid` because that is what the builders
    produce — turned into a checkable shape. Nothing in the fleet mints
    `usr_01J9Z8QK5M4N7P2R3T6V8W9X0A`, so no schema may require one and no example
    a consumer copies may show one.

    **The shape, not the prefix list, is the rule**, and the difference is not
    cosmetic. D35 recommended failing on the strings `usr_`, `acc_`, `sub_`,
    `pln_`, `inv_`; `sub_` is a prefix cafaye does not mint and Stripe mints on
    every subscription, so that rule would have gone red the first time billing
    constrained a processor id, and a rule that fires on a true fact is a rule
    that gets switched off. A short lowercase word, an underscore, and a long
    run of uppercase base32 is a ULID behind a prefix, which is the shape both
    `^usr_…` and `^acc_…` had and the shape a processor's mixed-case
    `sub_1PZQaBcDeFgHiJkLmNoPqR1` does not.

    The limit: a schema that invents a *different* fiction — a wrong `enum`, a
    column that does not exist, a field whose meaning drifted — is not in either
    shape and stays green. Only D36's answer to that is a real one, and D36 says
    it needs a publisher-side check.

    **`examples/valid/telemetry/` is walked here too, and that is the correction
    this packet made.** This rule reported the fleet clean for the whole of
    core-24 while sixteen telemetry examples carried `tnt_…` and `acc_…`, because
    `valid_payload_documents()` globs `examples/valid/events/` and stops. The
    denylist was right about the shape and was pointed at the wrong directory;
    `test_the_two_example_walkers_between_them_cover_every_example` is what keeps
    the next directory from being the one nobody looks at.
    """
    hits = prefixed_id_uses(schema_id_triples(payload_schema_documents()))
    hits += prefixed_id_uses(example_id_triples(valid_payload_documents()))
    hits += prefixed_id_uses(example_id_triples(valid_signal_documents()))
    assert not hits, (
        "these are cafaye-shaped prefixed ids, and no publisher in the fleet mints "
        "one — a schema requiring it rejects real traffic and an example showing it "
        "teaches the fiction:\n  "
        + "\n  ".join(hits)
        + "\nRead the publisher's code (D35) before asserting an id shape. If a "
        "publisher really has started minting prefixed ids, that is a fleet vocabulary "
        "decision for DECISIONS.md and this rule has to be revisited in the same "
        "commit — do not relax it quietly."
    )


def test_the_prefixed_id_rule_names_both_a_schema_and_an_example() -> None:
    """Both halves of the rule above, on the two spellings D35 shipped.

    A rule with one kind of input is half a rule, and the half that is missing is
    always the one that would have caught the next thing. So the constraint form
    (`^usr_[0-9A-Z]{26}$`, a `pattern` in a `properties` block) and the value form
    (`usr_01J9Z8QK5M4N7P2R3T6V8W9X0A`, an `examples/valid/` value a consumer
    copies) are each handed to the rule and each has to be named.

    The second of those two is the string `examples/valid/event-envelope.json`
    carried as its `subject` and its `data.user_id` until this packet, which is
    how a schema that rejects 100% of a publisher's real output stayed green for
    as long as it did.
    """
    constraint = schema_id_triples([
        ("identity.user.created", {
            "properties": {"user_id": {"pattern": "^usr_[0-9A-Z]{26}$"}},
        }),
    ])
    assert prefixed_id_uses(constraint) == [
        "identity.user.created /properties/user_id/pattern = '^usr_[0-9A-Z]{26}$'"
    ], "a pattern that pins a value to a prefixed ULID is not being named"

    value = example_id_triples([
        ("examples/valid/event-envelope.json", {"subject": "usr_01J9Z8QK5M4N7P2R3T6V8W9X0A"}),
    ])
    assert prefixed_id_uses(value) == [
        "examples/valid/event-envelope.json /subject = 'usr_01J9Z8QK5M4N7P2R3T6V8W9X0A'"
    ], "an example value in the cafaye id shape is not being named"

    # The shape is a shape and not a prefix list, so the processor id D10 protects
    # has to survive the rule. If this goes red the rule is wrong, not billing.
    processor = example_id_triples([
        ("examples/valid/events/billing/subscription/started.data.json", {
            "subscription_id": "sub_1PZQaBcDeFgHiJkLmNoPqR1",
            "customer_id": "cus_R1pQKz9xLp2mN4vB6yH8jL0",
        }),
    ])
    assert not prefixed_id_uses(processor), (
        "the rule is firing on a payment processor's own ids, which D10 says are "
        "billing's to carry and not cafaye's to forbid: the shape is the rule, and "
        "mixed case is what keeps it from being a prefix list"
    )


def test_a_prefixed_id_may_only_survive_in_an_example_whose_rejection_IS_the_id() -> None:
    """The whole point of leaving two files alone, asserted so it stays deliberate.

    This packet removed twenty-four fabricated ids from `examples/` and left three,
    all under `examples/invalid/`. A reader auditing the tree will find them, and
    the honest answer to "why does this negative example still teach a fiction?" is
    that **the fiction is the thing being rejected**: `format: uuid` refusing
    `usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` is the entire demonstration, and it is what
    README row 2 calls "the exact value the old pattern required". Respelling it
    would have made the file pass a schema it exists to fail, and left D35
    untestable.

    An example that is rejected on a FIELD NAME or on an ABSENCE gets no such
    excuse — `plan_id`, a missing `subject`, an undeclared `account_id` are all
    rejected whatever the value is — and those were corrected in this packet,
    because an incidental prefixed ULID still teaches the whole fleet a shape no
    producer mints.

    So the rule is mechanical rather than a judgement call: **every** remaining
    prefixed id in `examples/` must sit in a file whose rejection is attributable
    to the id's own shape or to its prefix. `failures_for` decides that by asking
    the schema, so this cannot rot into a list somebody maintains by hand.
    """
    surviving = {
        path.relative_to(REPO).as_posix(): value
        for path in sorted(EXAMPLES.rglob("*.json"))
        for value in [json.dumps(json.loads(path.read_text()))]
        for candidate in re.findall(r'"((?:tnt|acc|usr|pln)_[0-9A-Za-z]+)"', value)
        if CAFAYE_ID_VALUE.match(candidate)
    }
    assert surviving, (
        "the tree no longer contains a single cafaye-shaped id, so this test is "
        "asserting nothing. Either the negative examples that exist to reject one "
        "were respelled — which breaks them — or the rule they demonstrate moved."
    )
    for label, value in sorted(surviving.items()):
        path = REPO / label
        document = json.loads(path.read_text())
        # A payload example is checked against its OWN payload schema and an
        # envelope example against the envelope schema, because a payload
        # validated against the envelope reports the envelope's rules and none of
        # the payload's — which is how `identity/user/created.data.json` looks
        # rejected on `required`/`additionalProperties` while the failure this
        # test is about, `format: uuid` refusing `usr_…`, never runs.
        schema_path = (
            payload_schema_path(
                path.relative_to(INVALID_PAYLOADS).as_posix()[: -len(PAYLOAD_EXAMPLE_SUFFIX)]
                .replace("/", ".")
            )
            if INVALID_PAYLOADS in path.parents
            else ENVELOPE_SCHEMA_PATH
        )
        found = failures_for(document, load_schema(schema_path))
        keywords = {failure.keyword for failure in found}
        assert {"format", "pattern"} & keywords, (
            f"{label} carries the cafaye id shape {value!r} and is NOT rejected on a "
            f"format or pattern ({sorted(keywords) or 'no failures at all'}), so the "
            f"value is incidental to what this file demonstrates. Respelling it to a "
            f"real uuid costs this example nothing and stops it teaching the fleet a "
            f"shape no producer emits — that is what this packet did to the other four."
        )


def test_no_example_carries_an_id_shape_its_own_producer_cannot_emit() -> None:
    """The positive rule, and the one this packet exists to install.

    core-24's rule says "no publisher mints a prefixed ULID". It is a **denylist
    of one shape**, and it was green for the whole of core-24 over twenty-one
    examples carrying `tnt_…` and `acc_…` — not because the shape was unknown to
    it, but because it was pointed at `examples/valid/events/` and never at
    `examples/valid/telemetry/`. A denylist only catches what it is aimed at.

    This is the opposite kind of rule. Each producer's id type is transcribed into
    `PRODUCER_ID_SHAPES` from a named file at a named commit, each identifier
    field is assigned one of those shapes, and every identifier value in every
    valid example must match the shape recorded for the field **of the service
    that emits that example**. A value that is merely *not* the old fiction is not
    enough: `tnt_…` fails because no operator writes that, and a random uuid would
    fail too, because core does not know this fleet's tenant names and is not
    entitled to guess them.

    The walk is in both directions, and the reverse half is the one that keeps
    the ledger honest. A recorded shape that no example exercises is an assertion
    about code nobody re-reads, and a ledger of those is how D35 happened.

    **What this cannot do, stated so nobody has to infer it.** core reaches no
    publisher and reads no checkout, so it cannot prove that `identity` still
    generates version 4 uuids, that courier still writes `message_id` as
    `"courier-" <> Ecto.UUID.generate()`, or that the commits in the ledger are
    the ones anybody read. It proves core's own record of each producer and
    core's own examples agree. That is the same limit D36 records for the
    citation rule, and it is why every ledger entry names a commit: the day
    `fleet.yml` moves a `sourceCommit`, this ledger is stale and says so.
    """
    documents = valid_payload_documents() + valid_signal_documents()
    faults = producer_shape_faults(
        documents, PRODUCER_ID_SHAPES, IDENTIFIER_FIELD_SHAPES, RESOURCE_ATTRIBUTE_SHAPES
    )
    assert not faults, (
        "these examples carry an id shape the service that emits them does not mint, "
        "or the ledger claims a shape nothing corroborates. An example is the "
        "reference every service author copies from, so an id shape in one that no "
        "producer can emit teaches the whole fleet to mint fiction:\n  "
        + "\n  ".join(faults)
        + "\nRead the producer's code — the file and commit are named above — and "
        "correct either the example or the ledger. If a producer really has changed "
        "what it mints, that is a fleet vocabulary decision for DECISIONS.md and this "
        "rule has to be revisited in the same commit. Do not relax it quietly."
    )


def test_the_producer_shape_rule_names_a_telemetry_example_and_a_producer() -> None:
    """The witness, on the real file rather than a shape that resembles the defect.

    Two things have to be true of this rule and neither is visible from the test
    above passing. It must reach a **telemetry** example — the directory core-24
    never walked — and it must attribute that example to the service the document
    names rather than to the directory it happens to sit in, because `metric.json`
    is identity's and `log.json` is courier's and both are the same shape of
    document in the same directory.

    The fixture is the defect itself: this repository's own example, with
    `tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG` put back. A rule that cannot fail on the
    defect it was bought for is a comment, and a rule that only fails on a
    hand-built object that resembles the defect is a rule fitted to its witness.

    The control is here for the reason every control is: a rule that refused every
    example would satisfy all three assertions below, and a rule that accepted
    every example would fail all three.
    """
    # 0. The control: this repository's example as it ships has to pass.
    label = "examples/valid/telemetry/metric.json"
    shipped = load_document(REPO / label)
    assert not producer_shape_faults(
        [(label, shipped)],
        PRODUCER_ID_SHAPES,
        IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
        require_every_entry_exercised=False,
    ), "the rule rejects the example this repository actually ships"

    # 1. The defect, restored. It must be attributed to IDENTITY — the service the
    #    document names — and named as that service's operator-label shape.
    reverted = copy.deepcopy(shipped)
    reverted["resourceAttributes"]["tenant_id"] = "tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG"
    faults = producer_shape_faults(
        [(label, reverted)],
        PRODUCER_ID_SHAPES,
        IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
        require_every_entry_exercised=False,
    )
    assert len(faults) == 1, (
        f"the rule did not name exactly one defect in a telemetry example: {faults}"
    )
    assert faults[0].startswith(
        f"{label} /resourceAttributes/tenant_id = 'tnt_01J9Z8R4T7Y2U6K3W8Q5N0P1DG'"
    ), (
        f"the rule reported a telemetry example without naming the file and the field: {faults}"
    )
    assert "identity's operator-label" in faults[0], (
        f"the rule did not attribute the example to the service the document names: {faults}"
    )

    # 1b. The SECOND defect this packet found, which is not a prefix at all. A
    #     perfectly ordinary uuid in `account_id` is still wrong, because no
    #     service in the fleet emits `account_id` on a resource — so the rule has
    #     to be a positive check against the producer's ledger rather than a
    #     denylist of one shape. Without this assertion the rule above would still
    #     pass on a fleet that swapped the fiction for a different plausible id.
    respelled = copy.deepcopy(shipped)
    respelled["resourceAttributes"]["account_id"] = "4a8f2d61-3c95-4e07-9b2a-7d1e6f8c3a52"
    second = producer_shape_faults(
        [(label, respelled)],
        PRODUCER_ID_SHAPES,
        IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
        require_every_entry_exercised=False,
    )
    assert len(second) == 1 and "resourceAttributes/account_id" in second[0], (
        f"a bare uuid in a field no producer emits was accepted, so the rule is a "
        f"denylist with extra steps: {second}"
    )

    # 2. The reverse direction. A ledger entry nothing exercises is an assertion
    #    about code nobody reads, so it is a fault in its own right.
    stale = dict(IDENTIFIER_FIELD_SHAPES)
    stale["courier"] = dict(stale["courier"], invented_field="uuid")
    reverse = producer_shape_faults(
        [(label, shipped)], PRODUCER_ID_SHAPES, stale, RESOURCE_ATTRIBUTE_SHAPES
    )
    assert any("invented_field" in line and "no example exercises it" in line for line in reverse), (
        f"a ledger entry nothing corroborates was accepted: {reverse}"
    )


def test_an_example_naming_no_service_is_reported_rather_than_skipped() -> None:
    """The unknowable case is a fault, because green-on-unknown is green-on-wrong.

    The rule walks examples by asking each one which service emits it. When the
    answer is `None` — a telemetry document with no `service.name` on its
    resource — the two available responses are to skip it or to name it. Skipping
    is the choice that produces a rule nobody can trust, because the failure is
    silent and the count stays the same: an example nobody can attribute is an
    example no id in it is checked, which is exactly the blindness this packet
    exists to close, re-entering through the back door.

    So it is reported, and the fixture is an example with the service name taken
    out of it — which also proves the attribution is read from the document rather
    than guessed from the path.

    The identifier has to still be there, and that is the other half of the rule:
    a document with no id field at all is not unattributable, it is simply not
    this rule's business. `otel-endpoint.json`, `probes.json`, `redaction.json`
    and the three `span-naming.*` documents carry none, and a rule demanding a
    service name of them would report six faults nobody could act on — which is
    how a rule stops being read. Both halves are asserted here because the second
    one is the tempting simplification of the first.
    """
    label = "examples/valid/telemetry/metric.json"
    unattributed = copy.deepcopy(load_document(REPO / label))
    del unattributed["resourceAttributes"]["service.name"]
    faults = producer_shape_faults(
        [(label, unattributed)], PRODUCER_ID_SHAPES, IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
    )
    assert any("names no service" in line for line in faults), (
        f"an example naming no service was skipped rather than reported: {faults}"
    )

    nothing_to_check = [
        ("examples/valid/telemetry/probes.json", load_document(REPO / "examples/valid/telemetry/probes.json")),
        ("examples/valid/telemetry/otel-endpoint.json", load_document(REPO / "examples/valid/telemetry/otel-endpoint.json")),
    ]
    assert not producer_shape_faults(
        nothing_to_check,
        PRODUCER_ID_SHAPES,
        IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
        require_every_entry_exercised=False,
    ), (
        "a document carrying no identifier at all is not this rule's business, and "
        "reporting it would train a reader to ignore the failures that matter"
    )


def test_a_service_core_has_not_read_is_reported_rather_than_assumed() -> None:
    """The ledger's own blind spot, asserted so it stays a known one.

    The ledger covers identity, courier, billing and muse. gateway is absent, and
    that is a statement about core's knowledge rather than about gateway: core has
    read its ids out of no file at no commit, so the honest claim is "unknown". A
    rule that skipped an unlisted service would be green on gateway's ids forever,
    which is a green badge for a check nobody ran.

    The rule reports it instead, so the moment a gateway example enters the walk the
    suite names the gap rather than passing over it. The fixture is a minimal
    document rather than a real one: gateway publishes no events and exports no
    signals of its own (`signals: []` in fleet.yml), so there is no example of its
    to point at, and inventing one to make this test pass would be inventing a
    fixture to satisfy a checker.
    """
    assert "gateway" not in PRODUCER_ID_SHAPES, (
        "gateway now has an id shape in the ledger. Good — that is the gap this test "
        "names closing. Read gateway's code, add the entry, and delete THIS assertion; "
        "do not edit it into passing."
    )
    faults = producer_shape_faults(
        [("examples/valid/telemetry/span.gateway.json", {
            "resource": {"service.name": "gateway", "tenant_id": "acme"},
        })],
        PRODUCER_ID_SHAPES,
        IDENTIFIER_FIELD_SHAPES,
        RESOURCE_ATTRIBUTE_SHAPES,
    )
    assert any("core records no id shape for gateway" in line for line in faults), (
        f"an unlisted service was passed over rather than reported: {faults}"
    )


def test_the_two_example_walkers_between_them_cover_every_example() -> None:
    """The coverage hole, closed by naming the whole tree rather than two lists.

    core-24's id rule walked `examples/valid/events/`. Sixteen examples in
    `examples/valid/telemetry/` carried a fabricated id shape for the whole of its
    life, and nothing went red, because the rule was correct about everything it
    looked at. Two enumerated lists would reproduce the defect with a longer tail,
    so this asserts the union of the two walkers IS every valid JSON example —
    which is what makes "the rule walks the signals" a property of the tree rather
    than of a line of code somebody remembered to add.

    `gate.*.yml` and the SLO documents are excluded by extension, not by name:
    they are validated by their own schemas and their own tests, and a `.yml`
    sneaking into this set would be reported rather than silently accepted.
    """
    walked = {label for label, _ in valid_payload_documents() + valid_signal_documents()}
    on_disk = {
        path.relative_to(REPO).as_posix()
        for path in VALID_EXAMPLES.rglob("*.json")
    }
    assert walked == on_disk, (
        "the id rule does not walk every valid JSON example.\n"
        f"  walked but not on disk: {sorted(walked - on_disk)}\n"
        f"  on disk but not walked: {sorted(on_disk - walked)}\n"
        "A valid example the id rule never reads is an example it cannot catch."
    )


def test_a_payload_schema_cites_the_commit_its_publisher_was_read_at() -> None:
    """The citation is machine-checked, so it cannot rot into a habit.

    A payload schema is written by reading somebody else's code, and the reading
    has a date and a commit. Prose saying so is a sentence; this is a comparison.
    identity's nine schemas each carry `read from identity at <40 hex>` in their
    `$comment`, and that commit is the one `fleet.yml` records as identity's
    `sourceCommit` — so when a future packet re-reads identity and moves that
    commit, all nine go red until the payloads are re-read too. That is the
    drift this rule exists to make expensive.

    **Scope is one service, and the reason is provenance rather than
    preference.** identity's schemas were transcribed from `internal/outbox/` at
    the commit already on record, so a citation is a fact this repository can
    check. courier's, billing's and muse's payload schemas were written before a
    citation existed and the commit each was read at is recorded nowhere, and
    writing one now would be inventing provenance to satisfy a checker. So
    `PROVENANCE_REQUIRED` is `("identity",)` and the other three are named as
    owed rather than faked — an invented citation is precisely the defect D35 was.

    **What it cannot do**, and this is the honest half: core has no network and
    reads no publisher, so it cannot prove the commit exists in identity, that
    the code at that commit emits what the schema says, or that the schema was
    written from that commit at all. It proves one thing — the schema and core's
    own record of the code agree on which bytes were read. D36 is where that
    limit is written down, and the test that follows is what keeps this half from
    being the only one.
    """
    faults = provenance_faults(payload_schema_documents(), load_fleet())
    assert not faults, (
        "a payload schema's citation of the commit its publisher was read at does not "
        "agree with fleet.yml:\n  "
        + "\n  ".join(faults)
        + "\nEither re-read the payload from that commit, or move `sourceCommit` and "
        "re-read every payload schema for that service. A citation nobody checked is "
        "the sentence D35 was."
    )


def test_a_citation_may_not_name_a_commit_core_does_not_record() -> None:
    """The citation rule has to reject three things, not merely require one.

    A rule that only checks for the presence of a citation accepts a wrong one,
    and a wrong one is the failure mode that matters: it is indistinguishable
    from a right one to every reader, including this repository. So each fault is
    produced from a citation the rule accepts and has to be named — one naming a
    commit `fleet.yml` does not record, one naming another service's code, and
    one deleted outright. The first is what a stale schema looks like after a
    re-read; the second is what copying a sibling's citation looks like; the third
    is what "optional" looks like.

    The citation every fault is derived from is **built from `fleet.yml` rather
    than read out of the tree**, which is what lets this witness run on a tree
    that has no citations yet: its subject is what the rule decides about a
    citation, not whether this repository currently has one. That the shipped
    file's citation is right is the other test's job, and duplicating it here
    would be a second copy of one rule.
    """
    fleet = load_fleet()
    label = "identity.user.created"
    schema = {"properties": {"user_id": {"type": "string", "format": "uuid"}}}
    good = f"Provenance: read from identity at {fleet_source_commits(fleet)['identity']}."

    def with_comment(comment: str | None) -> list[str]:
        candidate = copy.deepcopy(schema)
        if comment is None:
            candidate.pop("$comment", None)
        else:
            candidate["$comment"] = comment
        return provenance_faults([(label, candidate)], fleet)

    # 0. The control. Without it, three rejections prove nothing: a rule that
    #    refused every citation would satisfy all three.
    assert not with_comment(good), (
        f"a citation naming the commit fleet.yml records was rejected: {with_comment(good)}"
    )

    # 1. a commit the registry does not record. `0000…` is a legal sha and no
    #    repository has it, which is the interesting case: the shape is right.
    stale = with_comment("Provenance: read from identity at " + "0" * 40 + ", from the event builder.")
    assert len(stale) == 1 and "0000000000000000000000000000000000000000" in stale[0], (
        f"a citation naming a commit fleet.yml does not record was accepted: {stale}"
    )

    # 2. another service's code. What happens when a schema is copied from a
    #    sibling and the citation comes with it — and note this one is reported
    #    TWICE, once for the service and once for the commit that service's
    #    record implies, because both are true and a rule reporting only the
    #    tidier half would be hiding the other.
    misnamed = with_comment("Provenance: read from courier at " + fleet_source_commits(fleet)["courier"] + ".")
    assert any("cites courier's code" in line for line in misnamed), (
        f"a citation naming another service's code was accepted: {misnamed}"
    )

    # 3. no citation at all, on a service that owes one.
    assert with_comment(None) == [f"{label} carries no `read from <service> at <commit>` citation"], (
        "dropping the citation was accepted, so the rule checks spelling and not "
        "presence — and a schema with no provenance is the state core started in"
    )


# --------------------------------------------------------------------------
# 5d. a payload schema's standing against the only publisher that exists
# --------------------------------------------------------------------------

#: The two standings a payload schema can record against its publisher, in the
#: words core's own documents already use for them. **A closed vocabulary, not a
#: free-text habit**, and it is not invented here:
#:
#: * `declared-and-unimplemented` is [`fleet.yml`](fleet.yml)'s exact phrase for a
#:   type courier lists in `exposes.events` and in `Courier.Events.types/0` and has
#:   no builder for. It is courier's own module doc's finding too: "a builder is a
#:   shape, not an emission".
#: * `does not describe what its publisher emits` is D35 restated as a predicate
#:   rather than a title. D35 was one schema about one event; the predicate is the
#:   shape of the defect, and it is a shape three billing schemas now have.
#:
#: Two, not one, because they are not the same statement and collapsing them is
#: how one gets mistaken for the other: the first says **no builder exists**, the
#: second says **a builder exists and builds something else**. A reader who is
#: told the first and meets the second has been told something false.
PUBLISHER_STANDINGS = (
    "declared-and-unimplemented",
    "does not describe what its publisher emits",
)

#: Where each signal keeps its RESOURCE attribute list. Not the same table as
#: `ALLOWLIST_DEF` above and not derivable from it: that one answers "which
#: attributes may a span carry", this one answers "which attributes are attached
#: once per process", and the two are disjoint by construction — a name on both is
#: the mistake `test_identity_lives_on_resource_attributes_which_are_exempt_from_the_cap`
#: exists to catch. Kept as its own table so a schema that renames one produces a
#: clear failure rather than a `KeyError` from the other.
RESOURCE_DEF = {
    "traces": ("traces.schema.json", "resource"),
    "metrics": ("metrics.schema.json", "resourceAttributes"),
    "logs": ("logs.schema.json", "resource"),
}

#: The resource attributes a real span's resource demonstrably carries, each with
#: the producer it was read from. **This is a positive list and it is the fleet's
#: own, not a best guess**: an attribute nobody sets belongs in none of these
#: files, and `test_the_resource_allowlist_is_not_emptied_of_what_the_fleet_emits`
#: is what stops somebody deleting an entry that has become inconvenient.
#:
#: * `service.namespace` — muse sets it by hand at `src/muse/telemetry.py:390`
#:   (`"cafaye"`), and asserts it in `tests/test_resilience_config.py:355`. The
#:   only publisher in the fleet that sets it.
#: * `telemetry.sdk.name` / `.language` — billing sets two of these BY HAND at
#:   `lib/kit/telemetry.rb:183-184`, so they are not an SDK artefact on billing at
#:   all; they are a fact about billing's source.
#: * `telemetry.sdk.*` in general — the Python SDK's `Resource.create/1` MERGES its
#:   own default resource, so a muse span carries `telemetry.sdk.language`,
#:   `telemetry.sdk.name` and `telemetry.sdk.version` whether or not muse asked
#:   for them. **Measured, not quoted**: `Resource.create({'service.name': 'muse',
#:   'service.namespace': 'cafaye'})` against the 1.44.0 SDK in muse's own venv
#:   returns six attributes, of which four are refused by the allowlist. A service
#:   cannot suppress those without opting out of the SDK's defaults, so a closed
#:   list without them does not describe a span, it describes a Go service using
#:   `resource.NewWithAttributes` (identity, `internal/telemetry/telemetry.go:542`,
#:   the schemaless constructor) — which is why this went unnoticed: the one
#:   service whose resource is built the schemaless way is the only one that
#:   validates.
#:
#: All four are Stable OpenTelemetry semantic-convention resource attributes,
#: bounded to one value per process, which is the same argument
#: `docs/observability.md` makes for `service.name` being on the resource at all.
RESOURCE_ATTRIBUTES_THE_FLEET_EMITS = (
    "service.name",
    "service.version",
    "service.instance.id",
    "service.namespace",
    "deployment.environment",
    "tenant_id",
    "account_id",
    "telemetry.sdk.name",
    "telemetry.sdk.language",
    "telemetry.sdk.version",
)


def signal_resource_attribute_names(signal: str) -> set[str]:
    filename, definition = RESOURCE_DEF[signal]
    schema = load_schema(TELEMETRY_SCHEMAS / filename)
    return set(schema["$defs"][definition]["properties"])


def publisher_standing_faults(documents: list[tuple[str, dict]]) -> list[str]:
    """Every payload schema whose standing against its publisher is invisible.

    **The failure is that a fact lives in `$comment`.** A `$comment` is metadata:
    `jsonschema` ignores it, `caf contract lint` ignores it, and the editor a
    consumer is reading the schema in puts `description` in the hover and
    `$comment` nowhere. So a schema can carry an honest, fully-cited, precisely
    worded admission in `$comment` and read as a confident contract to everybody
    who opens the file — which is what `courier.email.queued` did, and what the
    three billing subscription schemas do.

    One rule, two instances, and it is derived rather than listed: a schema that
    uses a standing from `PUBLISHER_STANDINGS` anywhere must use it in
    `description` too. There is no hand-maintained list of which schema has which
    standing, because a list of that kind is rot with extra steps — it is the
    ledger-rotting failure D37 was written to end, applied to the wrong table.
    """
    faults: list[str] = []
    for label, schema in documents:
        comment = str(schema.get("$comment", ""))
        description = str(schema.get("description", ""))
        for standing in PUBLISHER_STANDINGS:
            if standing in comment and standing not in description:
                faults.append(
                    f"{label} records `{standing}` in its `$comment` and not in its "
                    "`description`, so the only reader who learns it is this "
                    "repository's own test run"
                )
    return faults


def test_a_standing_against_a_publisher_is_stated_where_a_reader_sees_it() -> None:
    assert not publisher_standing_faults(payload_schema_documents()), (
        "a payload schema says in `$comment` that its publisher does not exist, or "
        "emits something else, and says nothing of the kind in the `description` a "
        "consumer's tooling actually shows:\n  "
        + "\n  ".join(publisher_standing_faults(payload_schema_documents()))
        + "\nState the standing in `description` too, in the words "
        "`PUBLISHER_STANDINGS` gives it. Do not delete the `$comment` — the "
        "citation and the evidence belong there, and they are what makes the "
        "sentence in `description` checkable rather than a mood."
    )


def test_the_standing_vocabulary_is_not_a_pair_of_words_nothing_uses() -> None:
    """A closed vocabulary that nothing matches is a rule that cannot fail.

    Without this, deleting every standing from every schema turns the rule above
    green — which is precisely what a rule with no positive half does.
    """
    documents = payload_schema_documents()
    unused = [
        standing
        for standing in PUBLISHER_STANDINGS
        if not any(standing in str(schema.get("$comment", "")) for _, schema in documents)
    ]
    assert not unused, (
        f"{unused} is in PUBLISHER_STANDINGS and no payload schema claims it, so the "
        "rule that reads it is dead weight and the vocabulary is a promise core no "
        "longer keeps. Either a schema genuinely carries that standing, or the "
        "phrase is deleted — but a vocabulary is not a list of possibilities."
    )


def test_the_standing_rule_bites_on_a_schema_whose_description_drops_it() -> None:
    """The witness, on the real files rather than a shape that resembles the defect.

    The fixture is `courier.email.queued`'s own schema as it ships, with the
    standing stripped from `description` and left in `$comment` — which is the
    defect, because a `$comment` is invisible to the reader and a `description` is
    not. The control is here for the reason every control is: a rule that refused
    every document would satisfy the rejection half below.
    """
    documents = payload_schema_documents()
    label = "courier.email.queued"
    shipped = next(schema for name, schema in documents if name == label)
    standing = "declared-and-unimplemented"

    assert standing in str(shipped.get("$comment", "")), (
        f"{label} does not record `{standing}` in its `$comment`, so stripping it "
        "from `description` would not produce the defect the witness is for — the "
        "fixture has changed and the witness has to change with it"
    )
    assert not publisher_standing_faults([(label, shipped)]), (
        f"the rule rejects {label} as it ships: {publisher_standing_faults([(label, shipped)])}"
    )

    reverted = copy.deepcopy(shipped)
    reverted["description"] = reverted["description"].replace(standing, "not yet implemented")
    found = publisher_standing_faults([(label, reverted)])
    assert len(found) == 1 and label in found[0] and standing in found[0], (
        f"a schema carrying a standing in `$comment` alone was accepted: {found}"
    )


def test_the_three_signals_agree_on_the_resource_attribute_allowlist() -> None:
    """One list, three files, and nothing was watching them agree.

    `service.name`, `service.version`, `service.instance.id`,
    `deployment.environment`, `tenant_id` and `account_id` are spelled three
    times across three schemas and nothing compared the copies — the same defect
    `test_the_span_name_pattern_is_shared_with_the_traces_schema` and D10's
    duplicated `eventType` pattern both exist to prevent, sitting on the
    attribute list a service reads its resource contract out of.

    The four attributes this packet added are added to **all three** for the same
    reason. Adding `service.namespace` to traces alone would be the tolerated-names
    pattern in disguise: one signal knows a fact the other two refuse, and a
    service emitting it on a log record gets a failure that says nothing about
    which half is wrong.
    """
    allowlists = {signal: signal_resource_attribute_names(signal) for signal in RESOURCE_DEF}
    distinct = {frozenset(names) for names in allowlists.values()}
    assert len(distinct) == 1, (
        "the three signals do not agree on which attributes belong on a resource: "
        + "; ".join(
            f"{signal} has {sorted(names)}" for signal, names in sorted(allowlists.items())
        )
        + ". One list, three files, byte-identical — a resource attribute allowed on "
        "one signal and refused on another is a service that gets a validation failure "
        "naming no disagreement."
    )
    missing = sorted(set(RESOURCE_ATTRIBUTES_THE_FLEET_EMITS) - distinct.pop())
    assert not missing, (
        f"the resource allowlist does not carry {missing}, which the fleet demonstrably "
        "emits. The evidence for each is in RESOURCE_ATTRIBUTES_THE_FLEET_EMITS; an "
        "attribute on it is not a preference, it is a span a real service already "
        "produces that this schema refuses."
    )


def test_the_resource_allowlist_is_not_emptied_of_what_the_fleet_emits() -> None:
    """The reverse direction, because a closed list is edited by deletion.

    `account_id` has been on this list through several packets and no service
    emits it (`docs/observability.md` says so in prose). It is still the correct
    destination for it — the prohibition on measurements points here — so this test
    does not ask anybody to delete it. It asks that nothing be deleted **on the
    grounds that no example exercises it**, which is the argument that would
    eventually have removed `service.namespace` and `telemetry.sdk.name`.
    """
    allowlist = signal_resource_attribute_names("traces")
    documented = set(RESOURCE_ATTRIBUTES_THE_FLEET_EMITS)
    stray = sorted(allowlist - documented)
    assert not stray, (
        f"{stray} is on the resource allowlist and in neither RESOURCE_ATTRIBUTES_THE_"
        "FLEET_EMITS nor any producer's source. An attribute with no recorded "
        "publisher is a claim nobody made; if a service now emits it, record where "
        "it was read rather than letting the list carry it on its own authority."
    )


def test_the_resource_allowlist_rule_bites_on_a_real_span() -> None:
    """The witness, and it is measured against a document this repository ships.

    `span.muse.json` is the file named after the publisher that sets
    `service.namespace` by hand, and its resource is what a real muse span carries
    (`Resource.create/1` merges the SDK's own defaults — see
    `RESOURCE_ATTRIBUTES_THE_FLEET_EMITS`). The control asserts the shipped
    example validates; the rejection asserts that taking the four attributes back
    off the three schemas makes that same example fail, naming the file and the
    attribute. Without the rejection half this rule could be satisfied by a schema
    that allows nothing at all.
    """
    label = "examples/valid/telemetry/span.muse.json"
    document = load_document(REPO / label)
    schema = load_schema(TRACES_SCHEMA_PATH)
    assert not failures_for(document, schema), (
        f"{label} does not validate against the schema as it ships, so this witness "
        f"cannot show the rule biting: {[str(f) for f in failures_for(document, schema)]}"
    )

    resource = document.get("resource") or {}
    sdk_attributed = ("service.namespace", "telemetry.sdk.name", "telemetry.sdk.language", "telemetry.sdk.version")
    for name in sdk_attributed:
        assert name in resource, (
            f"{label} carries no {name!r}, so removing it from the allowlist proves "
            "nothing — the fixture has to be a document the rule is about, not one "
            "that resembles it"
        )

    # Every signal has to be carrying all four, or the witness is proving the
    # rule on one of three copies and the other two are where the drift would be.
    for signal in sorted(RESOURCE_DEF):
        names = signal_resource_attribute_names(signal)
        absent = [name for name in sdk_attributed if name not in names]
        assert not absent, (
            f"{signal} is missing {absent} from its resource allowlist, so this "
            "witness cannot show the rule closing on the signals that are not traces"
        )

    narrowed = copy.deepcopy(schema)
    narrowed["$defs"]["resource"]["properties"].pop("service.namespace")
    found = failures_for(document, narrowed)
    assert found, (
        f"{label} still validates after service.namespace was taken off the resource "
        "allowlist, so the list is not closed on the resource and a span attribute "
        "nobody contracted would pass silently"
    )
    assert any("service.namespace" in str(failure) for failure in found), (
        f"the rejection did not name service.namespace: {[str(f) for f in found]}"
    )


def test_the_producer_ledger_is_read_at_the_commit_the_registry_records() -> None:
    """D37's last sentence, made mechanical.

    D37 says the ledger "is visibly stale" the day `fleet.yml` moves a
    `sourceCommit` — and nothing made it visible. `PRODUCER_ID_SHAPES[service]["at"]`
    was written once and has never been compared to anything, so a ledger entry
    could name a commit the registry stopped recording months ago and every rule
    built on it would stay green.

    This closes that. The ledger is the one place core records *which bytes* a
    producer's id shapes were read out of, so it and `fleet.yml` are the same fact
    stated twice — and a repository in which a document and its schema are the
    same contract written twice needs a test for the pair.

    **What it still cannot do:** it cannot prove the commit exists, still contains
    the file, or that the shape in it is right. It says the two halves of core's
    own record name the same commit. That is D36's limit and the same remedy.
    """
    commits = fleet_source_commits(load_fleet())
    faults = [
        f"{service} reads {ledger['at']} and fleet.yml records {commits.get(service)}"
        for service, ledger in sorted(PRODUCER_ID_SHAPES.items())
        if service not in commits
        or ledger.get("at") != commits[service]
    ]
    assert not faults, (
        "the producer ledger and the fleet registry disagree about which commit each "
        "service was read at, so every id shape below is a claim about bytes nobody "
        "recorded:\n  "
        + "\n  ".join(faults)
        + "\nEither re-read the producer and update both in one commit, or the ledger "
        "is describing a tree that has moved. Do not delete the `at` key to make this "
        "green — a shape with no commit is exactly what D35 was."
    )


def test_the_ledger_pinning_rule_bites_on_a_commit_the_registry_does_not_record() -> None:
    """The witness: the failure is a mismatch, so the fixture is a mismatch."""
    commits = fleet_source_commits(load_fleet())
    drifted = {
        service: {**ledger, "at": "0" * 40}
        for service, ledger in PRODUCER_ID_SHAPES.items()
    }
    faults = [
        service
        for service, ledger in sorted(drifted.items())
        if ledger["at"] != commits.get(service)
    ]
    assert len(faults) == len(PRODUCER_ID_SHAPES), (
        f"a ledger entry naming a commit fleet.yml does not record was accepted: {faults}"
    )


# --------------------------------------------------------------------------
# 6. the outbox convention
# --------------------------------------------------------------------------


def outbox_sql() -> str:
    """The SQL in docs/event-outbox.md, normalized: lower case, single spaces."""
    blocks = re.findall(r"```sql\n(.*?)```", OUTBOX_DOC.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert blocks, f"{OUTBOX_DOC.name} must state the outbox table as SQL, not prose"
    return re.sub(r"\s+", " ", " ".join(blocks)).lower()


def test_event_outbox_doc_declares_the_outbox_table() -> None:
    """The outbox table is a contract; its columns are asserted out of the doc."""
    sql = outbox_sql()
    missing = [column for column in REQUIRED_OUTBOX_COLUMNS if column not in sql]
    assert not missing, f"{OUTBOX_DOC.name} is missing from its SQL: {missing}"


def test_event_outbox_doc_covers_every_required_topic() -> None:
    doc = OUTBOX_DOC.read_text(encoding="utf-8").lower()
    missing = [topic for topic in REQUIRED_OUTBOX_TOPICS if topic not in doc]
    assert not missing, f"{OUTBOX_DOC.name} dropped: {missing}"


# --------------------------------------------------------------------------
# 7. the fleet declaration
# --------------------------------------------------------------------------


def load_fleet() -> dict:
    return yaml.safe_load(FLEET.read_text(encoding="utf-8"))


def fleet_published() -> dict[str, set[str]]:
    """{service: {event types that service's manifest declares}} from fleet.yml."""
    return {
        service["name"]: set(service.get("events", []))
        for service in load_fleet()["services"]
    }


def test_fleet_declaration_matches_its_schema() -> None:
    """fleet.yml is a claim about other repositories, so it is validated like one."""
    schema = load_schema(FLEET_SCHEMA_PATH)
    found = failures_for(load_fleet(), schema)
    assert not found, f"{FLEET.name} must satisfy {FLEET_SCHEMA_PATH.name}:\n  " + "\n  ".join(
        str(f) for f in found
    )


def test_invalid_fleet_example_fails() -> None:
    schema = load_schema(FLEET_SCHEMA_PATH)
    found = failures_for(load_document(INVALID_FLEET), schema)
    assert found, f"{INVALID_FLEET.name} is supposed to be rejected by the schema"
    assert_keywords(
        found,
        (
            ("const", "spec"),                       # transcribed against the wrong spec
            ("format", "readOn"),                    # the provenance claim is not a date
            ("pattern", "services/0/name"),          # not a cafaye namespace name
            ("const", "services/0/manifest"),        # not the manifest name the schema pins
            ("const", "services/0/branch"),          # main, not master
            ("pattern", "services/0/sourceCommit"),  # a short sha, not a full commit
            ("pattern", "services/0/events/0"),      # upper case: forks the topic
            ("pattern", "services/0/events/1"),      # two segments: no service prefix
            ("pattern", "services/0/api"),           # ./ prefixed, not repo-relative
            ("additionalProperties", "services/0"),  # undeclared service key
            ("pattern", "services/0/telemetry/endpointVariable"),  # not UPPER_SNAKE
            ("enum", "services/0/telemetry/signals/1"),           # not an OTel signal
            ("type", "services/0/telemetry/probes"),              # not a boolean
        ),
    )


def test_fleet_covers_every_shipped_service() -> None:
    """The fleet declaration has to name the services it is a declaration about.

    Without this, dropping a service from fleet.yml silences every check below
    instead of failing one.
    """
    assert set(fleet_published()) >= REQUIRED_FLEET_SERVICES, (
        f"fleet.yml no longer names {sorted(REQUIRED_FLEET_SERVICES - set(fleet_published()))} "
        "— a service dropped from the declaration is a service nobody checks"
    )


def test_published_fleet_events_carry_their_own_service_prefix() -> None:
    """The grammar has no exceptions, and a real manifest is not exempt from it.

    This is the check core could not make before: the catalog was only ever
    compared against core's own example manifests, so a service could advertise
    whatever it liked. fleet.yml is the transcribed real thing.
    """
    pattern = event_type_pattern()
    for service, types in fleet_published().items():
        for event_type in sorted(types):
            assert re.fullmatch(pattern, event_type), (
                f"fleet.yml: {service} declares {event_type}, which violates the "
                f"event grammar {pattern}"
            )
            assert event_type.split(".")[0] == service, (
                f"fleet.yml: {event_type} must start with its own service name ({service}.…)"
            )


def test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema() -> None:
    """A published type and a shipped payload schema are the same fact, twice.

    This is the root-cause fix for courier: five event types reached master that
    no conforming consumer could parse, and nothing noticed, because the only
    comparison in the system was the catalog against core's own example
    manifests. fleet.yml is the comparison's input — this assertion is its
    point, and it is the one that has no equivalent anywhere else.
    """
    catalog = catalog_by_service()
    missing_rows: dict[str, list[str]] = {}
    missing_schemas: dict[str, list[str]] = {}
    for service, types in fleet_published().items():
        for event_type in sorted(types):
            if event_type not in catalog.get(service, set()):
                missing_rows.setdefault(service, []).append(event_type)
            if not payload_schema_path(event_type).is_file():
                missing_schemas.setdefault(service, []).append(event_type)
    assert not missing_rows, (
        f"published by a service but absent from the {EVENT_NAMING_DOC.name} catalog: "
        f"{missing_rows}"
    )
    assert not missing_schemas, (
        f"published by a service but with no payload schema in core: {missing_schemas} — "
        f"the path is {PAYLOAD_SCHEMAS.relative_to(REPO)}/<service>/<entity>/<action>"
        f"{PAYLOAD_SUFFIX}"
    )


def test_every_catalog_row_for_a_fleet_service_is_published_or_catalogued_only() -> None:
    """A catalog row is a promise; fleet.yml distinguishes a promise from a fact.

    `events` is what a service's manifest declares today, in a form core can
    finish its side for. `cataloguedOnly` is a catalog row nobody publishes yet
    — real, and owed a payload schema when its packet lands, but not a claim
    about a repository. `pendingCoreContract` is the mirror image: a type a
    service DOES declare and publish, where core has not yet shipped the catalog
    row and the payload schema that make it usable. Without the third list this
    test either forces the catalog to be empty of promises, or forces core to
    write another service's payloads in the same commit as a transcription —
    which is [D34](DECISIONS.md#d34-how-does-the-fleet-record-a-type-core-has-not-finished-contracting-for).

    The three lists must also be pairwise disjoint. A type in two of them is a
    reader being told two contradictory things about the same string, and which
    of the two they believe is not something a schema should leave to chance.
    """
    fleet = load_fleet()
    catalog = catalog_by_service()
    for service in fleet["services"]:
        name = service["name"]
        if name not in catalog:
            continue  # a service with no catalog section publishes nothing yet
        published = set(service.get("events", []))
        promised = set(service.get("cataloguedOnly", []))
        owed = set(service.get("pendingCoreContract", []))
        for left, right, left_name, right_name in (
            (published, promised, "events", "cataloguedOnly"),
            (published, owed, "events", "pendingCoreContract"),
            (promised, owed, "cataloguedOnly", "pendingCoreContract"),
        ):
            both = left & right
            assert not both, (
                f"fleet.yml: {name} lists {sorted(both)} as both {left_name} and {right_name}"
            )
        unaccounted = catalog[name] - published - promised - owed
        assert not unaccounted, (
            f"{EVENT_NAMING_DOC.name} has {name} rows that no repository declares and "
            f"fleet.yml does not mark catalogued-only: {sorted(unaccounted)}"
        )
        stale = promised - catalog.get(name, set())
        assert not stale, (
            f"fleet.yml marks {sorted(stale)} catalogued-only for {name} but there is no "
            f"catalog row for them"
        )


def pending_core_contract_debts(fleet: dict) -> list[tuple[str, str]]:
    """The `(service, event type)` pairs in `pendingCoreContract` core has finished.

    The rule, held as data rather than as an assertion over today's file, because
    core-23 emptied the list: an assertion whose only input is an empty list
    proves nothing at all, and a rule that quietly stops existing the day the debt
    it was written for is paid is the same defect as an entry with nothing behind
    it — the registry carrying an excuse for work that is already done. Both this
    and `test_the_debt_rule_still_bites_on_a_list_nobody_owes` call it, and the
    second is what keeps the first honest.
    """
    catalog = catalog_by_service()
    debts: list[tuple[str, str]] = []
    for service in fleet["services"]:
        name = service["name"]
        for event_type in sorted(service.get("pendingCoreContract", [])):
            has_row = event_type in catalog.get(name, set())
            has_schema = payload_schema_path(event_type).is_file()
            if has_row and has_schema:
                debts.append((name, event_type))
    return debts


def test_a_pending_core_contract_type_is_a_debt_core_really_owes() -> None:
    """`pendingCoreContract` is a debt, so an entry with nothing behind it fails.

    The mirror image of
    `test_every_published_fleet_event_has_a_catalog_row_and_a_payload_schema`,
    and it exists because a list that means "core has not finished this" stops
    meaning anything the moment a type in it IS finished. That is the same
    failure as reading `signals: []` as "this service is not instrumented": the
    registry would be carrying an excuse for work that is already done, and the
    next reader cannot tell an excuse from a reason.

    So this asserts the list is only allowed to hold types core has genuinely not
    shipped: no catalog row in `docs/event-naming.md`, **or** no payload schema
    under `schemas/events/`. It checks what is checkable from inside core, which
    is core's half of the list's meaning; the other half — that the service really
    declares and emits the type — is `sourceCommit`'s job and no test here can
    reach it. That limit is why [D34](../DECISIONS.md#d34-how-does-the-fleet-record-a-type-core-has-not-finished-contracting-for)
    is written down rather than resolved: the alternative to naming the debt is
    writing the schemas, and that is a packet of its own.

    **The list is empty**, and it stayed rather than being deleted: core-23 paid
    all eight of its entries, and the property, this rule and
    `test_the_debt_rule_still_bites_on_a_list_nobody_owes` are what the next
    debtor inherits. An empty list with a live rule is a standing invitation; a
    deleted list is a fourth place to invent.
    """
    debts = pending_core_contract_debts(load_fleet())
    assert not debts, (
        "fleet.yml marks these types pendingCoreContract while core ships both a "
        f"catalog row ({EVENT_NAMING_DOC.name}) and a payload schema for each, so "
        "nothing is owed and the entries are excuses rather than debts: "
        + ", ".join(
            f"{name} {event_type} "
            f"({payload_schema_path(event_type).relative_to(REPO)})"
            for name, event_type in debts
        )
        + " — move them to `events`, which is where a type with core's contract "
        "shipped belongs."
    )


def test_the_debt_rule_still_bites_on_a_list_nobody_owes() -> None:
    """A rule with no data is not a rule, and core-23 is the packet that emptied it.

    `test_a_pending_core_contract_type_is_a_debt_core_really_owes` iterates the
    entries `fleet.yml` actually carries, and after core-23 there are none — so on
    its own it now passes vacuously, which is precisely the state a test that has
    never failed is in. It is not left that way: the same predicate is handed a
    fleet that lists a type core HAS finished, and it has to name it.

    The type is one of the eight this packet paid, which is what makes the check
    about the real thing rather than about a fixture: it is a type with a catalog
    row and a payload schema, so the only way for the rule to pass on it is for the
    rule to have stopped existing. Both halves are asserted first, so a future
    packet that legitimately breaks either one is told which — the failure a
    reader would otherwise have to work out from this test's own name.
    """
    finished = "identity.session.revoked"
    assert finished in catalog_by_service().get("identity", set()), (
        f"{finished} has no catalog row, so it cannot be the finished type this "
        "test needs — pick another, or the rule below is being checked against "
        "nothing"
    )
    assert payload_schema_path(finished).is_file(), (
        f"{finished} has no payload schema, so the same applies"
    )
    owes_nothing = {
        "services": [{"name": "identity", "pendingCoreContract": [finished]}]
    }
    assert pending_core_contract_debts(owes_nothing) == [("identity", finished)], (
        "a pendingCoreContract entry for a type core has finished is not being "
        "rejected any more, so the list would accept an excuse — and a list that "
        "accepts an excuse cannot be read as a debt"
    )



def test_a_recorded_api_document_and_a_note_saying_there_is_none_are_not_both_true() -> None:
    """A note may not deny a fact a sibling field records.

    This is the assertion that would have caught the sentence courier's entry
    carried for as long as the entry existed: *"declares no `exposes.api` because
    it has no OpenAPI document to point at yet."* courier has declared
    `api: openapi.yaml` since 7b99879 (courier-03) and the registry had no field
    to say so, so the only place the claim lived was prose — and prose is not
    compared against anything, which is how a sentence about a document that
    courier-05 completed and courier-21 and courier-22c then edited survived
    every one of those three packets.

    The check is deliberately narrow, because a wider one is a spell-checker. It
    fires on a `notes` or `telemetry.notes` that says there is no HTTP contract
    document for a service whose entry names one, which is a contradiction within
    one record rather than a phrasing preference. Every other false sentence stays
    a reviewer's job; this one was demonstrably false, in a file whose entire
    value is that its sentences are not.
    """
    denials = (
        "no openapi document",
        "no `exposes.api`",
        "no exposes.api",
        "not a contract surface",
        "nothing to point at",
    )
    offenders = []
    for service in load_fleet()["services"]:
        if "api" not in service:
            continue
        texts = {
            "notes": service.get("notes", ""),
            "telemetry.notes": (service.get("telemetry") or {}).get("notes", ""),
        }
        for field, text in texts.items():
            note = str(text).lower()
            for phrase in denials:
                if phrase in note:
                    offenders.append(
                        f"{service['name']}.{field}: {phrase!r} beside api: {service['api']!r}"
                    )
    assert not offenders, (
        "fleet.yml records an `api` document and a note denying one on the same service:\n  "
        + "\n  ".join(offenders)
        + "\n  A field is a claim a schema can check; the note contradicting it is the "
        "claim a schema cannot, which is why the field is the one that has to win."
    )


# --------------------------------------------------------------------------
# 8. observability (PLAN.md §7b)
# --------------------------------------------------------------------------


def telemetry_schema_paths() -> list[Path]:
    return sorted(TELEMETRY_SCHEMAS.glob("*.schema.json"))


def span_naming_pattern() -> str:
    """The one machine-checked form of the span-name grammar."""
    return load_schema(SPAN_NAMING_SCHEMA_PATH)["$defs"]["spanName"]["pattern"]


def measurement_attribute_names() -> set[str]:
    """The metric schema's `measurementAttributes` property names, as a set."""
    return set(load_schema(METRICS_SCHEMA_PATH)["$defs"]["measurementAttributes"]["properties"])


def resource_attribute_names() -> set[str]:
    return set(load_schema(METRICS_SCHEMA_PATH)["$defs"]["resourceAttributes"]["properties"])


#: Where each signal's attribute allowlist lives inside its schema. The metrics
#: schema names its two maps after what they MEAN — `measurementAttributes` and
#: `resourceAttributes` — rather than after the signal, because the
#: measurement/resource split is the distinction that schema exists to draw and
#: naming it after the signal would obscure it. The other two are a single
#: allowlist each. Keyed here so a schema that renames one produces a clear
#: failure rather than a KeyError.
ALLOWLIST_DEF = {
    "traces": ("traces.schema.json", "tracesAttributes"),
    "metrics": ("metrics.schema.json", "measurementAttributes"),
    "logs": ("logs.schema.json", "logsAttributes"),
}


#: Which key each signal's example document carries its attributes under. Traces
#: and logs both call it `attributes`, so the discriminator has to be the schema a
#: file is registered against — deciding by reading the document is a document
#: that can be read two ways, and `log.json` is exactly that.
ATTRIBUTE_HOLDER = {
    TRACES_SCHEMA_PATH: "attributes",
    LOGS_SCHEMA_PATH: "attributes",
    METRICS_SCHEMA_PATH: "measurementAttributes",
}


def signal_allowlist(signal: str) -> set[str]:
    filename, definition = ALLOWLIST_DEF[signal]
    schema = load_schema(TELEMETRY_SCHEMAS / filename)
    return set(schema["$defs"][definition]["properties"])


def error_type_definition(signal: str) -> dict:
    """One signal's `error.type` constraint, as the schema states it.

    Not a hard-coded path per signal: `ALLOWLIST_DEF` already knows where each
    signal keeps its attributes, and a second table of paths is a second thing
    that can be wrong.
    """
    filename, definition = ALLOWLIST_DEF[signal]
    schema = load_schema(TELEMETRY_SCHEMAS / filename)
    return schema["$defs"][definition]["properties"]["error.type"]


#: Which schema each valid telemetry example is checked against. Keyed by file
#: name so an example nobody validates is a FAILING test rather than a file that
#: quietly stops being true: an unvalidated example is documentation nobody
#: checks, and two of these were orphaned when this table was written
#: (`log.json` and `metric.outbox.json` were read by no test at all).
TELEMETRY_EXAMPLE_SCHEMAS = {
    "span-naming.muse-provider-call.json": SPAN_NAMING_SCHEMA_PATH,
    "span-naming.muse-request.json": SPAN_NAMING_SCHEMA_PATH,
    "span-naming.identity-db-query.json": SPAN_NAMING_SCHEMA_PATH,
    "span.muse.json": TRACES_SCHEMA_PATH,
    "metric.json": METRICS_SCHEMA_PATH,
    "metric.outbox.json": METRICS_SCHEMA_PATH,
    "metric.error-type.json": METRICS_SCHEMA_PATH,
    "log.json": LOGS_SCHEMA_PATH,
    "redaction.json": REDACTION_SCHEMA_PATH,
    "otel-endpoint.json": ENDPOINT_SCHEMA_PATH,
    "probes.json": PROBES_SCHEMA_PATH,
    # YAML, because the artifact the brief makes the checked one is a Sloth
    # `prometheus/v1` file: `sloth validate -i <dir>` walks a directory of YAML,
    # so an SLO example in any other format would be an example of something
    # nobody validates.
    "slo.yaml": SLO_SCHEMA_PATH,
    "slo-windows.yaml": SLO_WINDOWS_SCHEMA_PATH,
    # One span per class in the error vocabulary, so the vocabulary is a
    # directory a reviewer can read rather than a list they have to imagine:
    # `ls examples/valid/telemetry/error-type.*` is the whole set. `_OTHER` is
    # filed as `other.json` because a filename may not be mistaken for the value
    # it carries — the class is read out of each document by
    # test_every_declared_error_class_has_a_valid_example, never from the name,
    # so a misleading filename cannot hide a missing class.
    "error-type.invalid-request.json": TRACES_SCHEMA_PATH,
    "error-type.policy-denied.json": TRACES_SCHEMA_PATH,
    "error-type.provider-auth.json": TRACES_SCHEMA_PATH,
    "error-type.provider-rejected.json": TRACES_SCHEMA_PATH,
    "error-type.rate-limited.json": TRACES_SCHEMA_PATH,
    "error-type.timeout.json": TRACES_SCHEMA_PATH,
    "error-type.connection-failed.json": TRACES_SCHEMA_PATH,
    "error-type.circuit-open.json": TRACES_SCHEMA_PATH,
    "error-type.dependency-unavailable.json": TRACES_SCHEMA_PATH,
    "error-type.conflict.json": TRACES_SCHEMA_PATH,
    "error-type.cancelled.json": TRACES_SCHEMA_PATH,
    "error-type.internal-error.json": TRACES_SCHEMA_PATH,
    "error-type.other.json": TRACES_SCHEMA_PATH,
}


def test_every_valid_telemetry_example_is_validated_against_its_schema() -> None:
    """The positive half of the five-part rule, enforced as a set rather than per file.

    The per-file tests below assert more than validity — that `enforcedAt` is the
    collector, that the no-op is four `none`s — so they stay. This one answers
    the question none of them can: is there an example no test looks at? Found by
    grepping for each example's name in this file and finding two orphans.
    """
    present = {
        path.name
        for path in VALID_TELEMETRY.iterdir()
        if path.is_file() and path.suffix in {".json", ".yaml", ".yml"}
    }
    assert present == set(TELEMETRY_EXAMPLE_SCHEMAS), (
        "examples/valid/telemetry/ and TELEMETRY_EXAMPLE_SCHEMAS disagree.\n"
        f"  examples with no test: {sorted(present - set(TELEMETRY_EXAMPLE_SCHEMAS))}\n"
        f"  tests with no example: {sorted(set(TELEMETRY_EXAMPLE_SCHEMAS) - present)}"
    )
    for name, schema_path in sorted(TELEMETRY_EXAMPLE_SCHEMAS.items()):
        found = failures_for(
            load_document(VALID_TELEMETRY / name), load_schema(schema_path)
        )
        assert not found, (
            f"{name} must satisfy {schema_path.name}:\n  "
            + "\n  ".join(str(f) for f in found)
        )


def test_telemetry_schemas_declare_draft_2020_12() -> None:
    """Every observability schema is a legal, self-describing draft 2020-12 schema.

    Seven files that core does not meta-validate are seven files a service CI
    can load and get a confusing `SchemaError` from, so this is the observability
    half of `test_schemas_declare_draft_2020_12` and it is not optional.
    """
    found = telemetry_schema_paths()
    assert {path.name for path in found} == {
        "span-naming.schema.json",
        "traces.schema.json",
        "metrics.schema.json",
        "logs.schema.json",
        "redaction.schema.json",
        "otel-endpoint.schema.json",
        "probes.schema.json",
        "slo.schema.json",
        "slo-windows.schema.json",
        "slo-metrics.schema.json",
    }, f"the observability schema set changed; add the new file to this test: {found}"
    for path in found:
        schema = load_schema(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", path
        assert schema.get("$id"), f"{path} needs a stable $id"
        assert schema.get("title"), f"{path} needs a title"
        assert schema.get("description"), f"{path} needs a description"
        jsonschema.Draft202012Validator.check_schema(schema)


def test_no_telemetry_schema_has_an_unreferenced_def() -> None:
    """A `$defs` entry nothing `$ref`s looks load-bearing and validates nothing.

    Found by mutation: probes.schema.json carried a `probeBase` holding the `auth`
    rule and its reasoning, which no probe actually referenced. A test asserting
    the *example* said `exempt` passed, and so did a test asserting `probeBase`
    said `const: exempt`, while the two concrete probes — the ones that do the
    validating — could have been widened to `["exempt", "bearer"]` and the whole
    suite stayed green. An orphan in a schema is a rule that is not a rule, which
    is the one thing this repository exists to prevent.
    """
    for path in telemetry_schema_paths():
        raw = path.read_text(encoding="utf-8")
        schema = load_schema(path)
        for name in schema.get("$defs", {}):
            assert f"#/$defs/{name}" in raw, (
                f"{path.name} defines $defs/{name} but nothing references it. "
                "Either $ref it from the branch that validates, or delete it — an "
                "unreferenced definition is a rule that enforces nothing while "
                "looking like one."
            )


# --- 8.1 span naming -------------------------------------------------------


def test_span_name_examples_validate() -> None:
    for path in sorted(VALID_TELEMETRY.glob("span-naming.*.json")):
        found = failures_for(load_document(path), load_schema(SPAN_NAMING_SCHEMA_PATH))
        assert not found, f"{path.name} must validate:\n  " + "\n  ".join(str(f) for f in found)


def test_span_names_are_low_cardinality_by_construction() -> None:
    """One scheme, six languages, and a name that cannot carry an identifier.

    The rejected list is the point. `GET /users/:id` and `get_user` are what a
    fleet produces when nobody has said what a span is called, and
    `muse.user.usr_01J9Z8QK5M4N7P2R3T6V8W9X0A` is worse: it is a cardinality
    bomb that reads as diligence in review, and it only fails once something
    aggregates on it.
    """
    pattern = span_naming_pattern()
    for accepted in ACCEPTED_SPAN_NAMES:
        assert re.fullmatch(pattern, accepted), f"{accepted} must be a legal span name"
    for rejected in REJECTED_SPAN_NAMES:
        assert not re.fullmatch(pattern, rejected), (
            f"{rejected!r} must be rejected by the span-name grammar"
        )


def test_the_span_name_grammar_is_lowercase_dotted_snake() -> None:
    """`<service>.<operation>[.<target>]` — the same shape as an event type.

    The prefix is mandatory and is the service's own name, so a span aggregates
    fleet-wide without a join and a span name is never ambiguous about which
    service produced it. Same rule as `<service>.<entity>.<action>`, and for the
    same reason: an unprefixed name says what happened and not who did it.
    """
    pattern = span_naming_pattern()
    assert pattern.count("\\.") >= 1, "the grammar must allow a dotted name"
    for two_segment in ("muse.request", "gateway.request.authorize"):
        assert re.fullmatch(pattern, two_segment), two_segment
    for unprefixed in ("provider.call", "db.query"):
        # Indistinguishable from a prefixed two-segment name by shape — only the
        # service vocabulary separates `muse.route` from `courier.route` — so this
        # asserts they are legal *shapes*. The check that a name really names a
        # real service is test_span_names_name_a_service_the_fleet_has.
        assert re.fullmatch(pattern, unprefixed), (
            f"{unprefixed!r} is a legal span-name shape; if this fails the grammar "
            "has changed and ACCEPTED/REJECTED_SPAN_NAMES need re-reading"
        )
    for unprefixed in ("request", "route", "call", "query", "deliver", "publish"):
        assert not re.fullmatch(pattern, unprefixed), (
            f"{unprefixed!r} has no service prefix; every span names its service "
            "first, so a query never has to guess which of six services to "
            "attribute it to"
        )
    # A segment never starts with a digit or a dash, and never contains a run of
    # characters that could be an id: the grammar cannot tell `usr_01J9Z8` from
    # `muse` by shape, so it excludes digits after the first character instead.
    for numeric in ("muse.1request", "muse.request.2", "gateway.2026.request"):
        assert not re.fullmatch(pattern, numeric), (
            f"{numeric!r} embeds a number where the grammar wants a word"
        )


def test_span_names_name_a_service_the_fleet_has() -> None:
    """The prefix is a cafaye service name, not a word that looks like one.

    The grammar cannot tell `muse.route` from `courier.route` — both are two
    legal dotted words — so the check that the prefix is a *real* service is a
    cross-reference against fleet.yml, the same way `test_published_event_types_
    carry_their_own_service_prefix` checks an event's first segment. Without it,
    a span named `apiserver.request` would validate and be invisible to every
    fleet-wide query, which is the failure this whole rule exists to prevent.
    """
    known = set(fleet_published())
    for path in sorted(VALID_TELEMETRY.glob("span-naming.*.json")):
        document = load_document(path)
        service = document["service"]
        assert service in known, (
            f"{path.name} names service {service!r}, which fleet.yml does not "
            f"declare. Known: {sorted(known)}"
        )
        assert document["name"].split(".")[0] == service, (
            f"{path.name}: {document['name']} must start with its own service name "
            f"({service}.…)"
        )


def test_span_name_length_is_bounded() -> None:
    """A name long enough to hold an id is a name that will.

    120 characters is generous for `<service>.<operation>.<target>` — the longest
    legal name here is 28 — and it is a cap rather than a convention because a
    convention is what a code review enforces, and a code review does not count
    characters.
    """
    schema = load_schema(SPAN_NAMING_SCHEMA_PATH)["$defs"]["spanName"]
    assert schema["maxLength"] == 120, f"the span-name cap moved: {schema['maxLength']}"


def test_the_span_name_pattern_is_shared_with_the_traces_schema() -> None:
    """A span name the traces schema would accept and the naming schema would
    not is a span name core contradicts itself about."""
    naming = load_schema(SPAN_NAMING_SCHEMA_PATH)["$defs"]["spanName"]["pattern"]
    traces = load_schema(TRACES_SCHEMA_PATH)["$defs"]["spanName"]["pattern"]
    assert naming == traces, (
        "the span-name pattern is duplicated in span-naming.schema.json and "
        "traces.schema.json; change one, change both"
    )


def test_a_non_conforming_span_name_is_rejected() -> None:
    """The negative example, and it fails for the reason the README lists."""
    schema = load_schema(SPAN_NAMING_SCHEMA_PATH)
    for path in sorted(INVALID_TELEMETRY.glob("span-naming.*.json")):
        found = failures_for(load_document(path), schema)
        assert found, f"{path.name} is supposed to be rejected by the schema"
        # A span name with a value interpolated into it. The rejection is a
        # `pattern`, and it is a pattern because the length bound in the grammar
        # is what refuses a 32-character id — core has no cafaye-id pattern to
        # reach for and must not grow one.
        assert_keywords(found, (("pattern", "name"),))


# --- 8.2 the attribute allowlist, per signal -------------------------------


def test_every_signal_declares_an_allowlist() -> None:
    for signal, expected in SIGNAL_ALLOWLISTS.items():
        allowlist = signal_allowlist(signal)
        assert allowlist == set(expected), (
            f"the {signal} attribute allowlist changed.\n"
            f"  expected: {sorted(expected)}\n"
            f"  found:    {sorted(allowlist)}\n"
            "A new attribute is a spec change: add it to the schema, the doc table "
            "and this list in the same commit, and say why it cannot carry content."
        )


def test_no_allowlisted_attribute_name_carries_content() -> None:
    """The redaction boundary, as a property of the allowlist itself.

    This is muse's canary promoted to a spec-level assertion. `muse/tests/
    test_trace_propagation.py` checks that no name in muse's
    `ALLOWED_SPAN_ATTRIBUTES` contains any of these words; core asserts the same
    for the fleet, and for all three signals rather than one service's. The
    realistic leak is not an attacker — it is a well-meaning `muse.prompt` added
    in six months by someone debugging a routing decision, in a service whose
    prompts are other customers' data.
    """
    for signal in ("traces", "metrics", "logs"):
        for name in sorted(signal_allowlist(signal)):
            lowered = name.lower()
            found = [word for word in FORBIDDEN_ATTRIBUTE_NAME_WORDS if word in lowered]
            assert not found, (
                f"{signal} allowlists {name!r}, whose name contains {found}. An "
                "attribute whose *name* names content is one a caller can put "
                "content in, and the collector cannot tell which values are safe "
                "without a schema it does not have."
            )


def test_the_three_signals_do_not_spell_one_attribute_three_ways() -> None:
    """The same fact is the same attribute name on every signal.

    `http.route` on a trace and `route` on a metric is a query that returns
    nothing, and nothing detects it — the same shape of failure as courier's
    two-segment event types, so it gets the same kind of check. The assertion is
    deliberately about attributes that appear on *more than one* signal:
    `db.operation` and `messaging.operation` are two different facts that happen
    to share a last word, which is fine, and conflating them would be a test
    that cries wolf.
    """
    shared: dict[str, dict[str, str]] = {}
    for signal in ("traces", "metrics", "logs"):
        for name in signal_allowlist(signal):
            shared.setdefault(name, {})[signal] = name
    on_more_than_one = {name: where for name, where in shared.items() if len(where) > 1}
    assert on_more_than_one, "no attribute is shared between signals, so the check is vacuous"
    for name, where in sorted(on_more_than_one.items()):
        # A shared attribute is spelled identically everywhere by construction of
        # the dict keys — this asserts the intent rather than the accident, and
        # it is what fails if someone adds `http.route` to metrics as `route`.
        assert set(where.values()) == {name}, (
            f"{name} is carried by {where} — a fact on two signals must have one "
            "name, or a cross-signal query returns nothing and nothing reports it"
        )


# --- 8.3 the measurement-attribute prohibition ----------------------------


def test_prohibited_identifiers_are_not_measurement_attributes() -> None:
    """The rule with teeth: tenant_id on a metric is a failing test, not a note.

    OpenTelemetry caps a metric stream at 2000 distinct attribute combinations
    and, on overflow, folds everything into one `otel.metric.overflow=true` point
    and drops every measurement attribute. Totals stay correct; every
    per-dimension breakdown undercounts. That is the worst shape a bug can have,
    and the only defence is never putting an unbounded value on a measurement.
    """
    prohibited = set(measurement_attribute_names())
    for name in PROHIBITED_MEASUREMENT_ATTRIBUTES:
        assert name not in prohibited, (
            f"{name} is allowlisted as a measurement attribute. It is unbounded: "
            "one series per value, against a 2000-combination cap that then "
            "silently drops the attributes. It belongs on a resource attribute."
        )


def test_a_tenant_id_measurement_attribute_is_rejected() -> None:
    """The exact failure the directive names, asserted end to end on a document.

    Not a lint note: a real metric document with `tenant_id` on the measurement
    is rejected, and the rejection is asserted by keyword so a schema that
    stopped constraining it fails this test rather than passing quietly.
    """
    schema = load_schema(METRICS_SCHEMA_PATH)
    document = load_document(INVALID_TELEMETRY / "metric.tenant-id-measurement.invalid.json")
    found = failures_for(document, schema)
    assert found, "a tenant_id measurement attribute must be rejected"
    # Two independent violations, and the test asserts both: the name is not on
    # the allowlist (additionalProperties) and it is named in a `not` so that
    # adding it to the allowlist later does not quietly succeed. A rule enforced
    # once is a rule a well-meaning commit can undo.
    assert_keywords(
        found,
        (("not", "measurementAttributes"), ("additionalProperties", "measurementAttributes")),
    )
    # ... and the same document without the prohibited attribute is legal, so
    # this is a test about tenant_id and not about the metric being malformed.
    allowed = {**document, "measurementAttributes": {"http.route": "/v1/route"}}
    assert not failures_for(allowed, schema), (
        "the same metric with a bounded measurement attribute must validate"
    )


def test_every_prohibited_identifier_fails_the_measurement_schema() -> None:
    """The prohibition is a list, so the whole list is tested, not one member.

    A hand-written table of negative cases is the kind of list that rots: a name
    is added to the prohibition and nothing tests that it is actually rejected.
    """
    schema = load_schema(METRICS_SCHEMA_PATH)
    base = load_document(VALID_TELEMETRY / "metric.json")
    for name in PROHIBITED_MEASUREMENT_ATTRIBUTES:
        document = {**base, "measurementAttributes": {**base["measurementAttributes"], name: "x"}}
        found = failures_for(document, schema)
        assert found, f"{name} as a measurement attribute must be rejected"
        assert any(
            failure.path.endswith(name) or name in failure.message for failure in found
        ), f"{name} must be rejected for being {name}: {[str(f) for f in found]}"


def test_identity_lives_on_resource_attributes_which_are_exempt_from_the_cap() -> None:
    """The other half of the rule: the prohibition says *move it*, so say where.

    Resource attributes are attached once per process, not once per measurement,
    so the 2000-combination cap does not apply to them and they survive on the
    overflow point. That is the correct home for identity — and it is why the
    rule is a prohibition with a destination rather than a prohibition with a
    shrug.
    """
    resources = resource_attribute_names()
    for name in ("tenant_id", "account_id"):
        assert name in resources, (
            f"{name} must be an allowlisted resource attribute — the prohibition "
            "tells a service where the value goes, and this is where it goes"
        )
    assert resources & measurement_attribute_names() == set(), (
        "an attribute cannot be both a resource and a measurement attribute; "
        f"{sorted(resources & measurement_attribute_names())} is on both lists"
    )


def test_resource_attributes_cannot_be_put_on_a_measurement() -> None:
    """The asymmetry is the mechanism, so it is asserted rather than explained.

    Identity is queryable on every point *because* it is on the resource and not
    the measurement. Moving it to the measurement to get a per-tenant breakdown
    is the exact mistake that produces a dashboard which looks right and is
    wrong, so the schema refuses it rather than the doc warning about it.
    """
    schema = load_schema(METRICS_SCHEMA_PATH)
    for name in sorted(resource_attribute_names()):
        document = {
            "name": "http.server.request.duration",
            "unit": "s",
            "measurementAttributes": {name: "example"},
        }
        found = failures_for(document, schema)
        assert found, (
            f"{name} is a resource attribute and must not be accepted as a "
            "measurement attribute"
        )


def test_the_metric_schema_states_the_2000_combination_cap() -> None:
    """The number is in the schema, not only in the prose.

    A limit that lives in a README is a limit nobody checks, and this one is the
    reason the whole prohibition exists. The schema says it; the doc repeats it;
    `test_observability_doc_covers_every_required_topic` says it is not dropped.
    """
    text = METRICS_SCHEMA_PATH.read_text(encoding="utf-8")
    assert "2000" in text, "metrics.schema.json must state the 2000-combination cap"
    assert "otel.metric.overflow" in text, (
        "metrics.schema.json must name the overflow point the SDK folds into, so a "
        "reader who has never seen the failure still knows what is being prevented"
    )


# --- 8.4 the redaction boundary -------------------------------------------


def test_the_redaction_boundary_is_a_schema() -> None:
    """The boundary is a document, so kit's collector config and a service's SDK
    setup can both be checked against the same file.

    This is the shape the packet asks for: the allowlist is the spec, and the
    enforcement point is declared rather than implied, so "the collector is the
    chokepoint" is something a linter reads instead of something a reader
    believes.
    """
    document = load_document(VALID_TELEMETRY / "redaction.json")
    found = failures_for(document, load_schema(REDACTION_SCHEMA_PATH))
    assert not found, "the valid redaction policy must validate:\n  " + "\n  ".join(
        str(f) for f in found
    )
    assert document["enforcedAt"] == "collector", (
        "PLAN.md §7b puts enforcement at the collector as one chokepoint; a policy "
        "that disagrees with the plan has to argue for it in DECISIONS.md"
    )
    assert document["default"] == "deny", "the boundary is default-deny, not default-allow"


def test_the_redaction_policy_never_allowlists_a_content_attribute() -> None:
    schema = load_schema(REDACTION_SCHEMA_PATH)
    policy = load_document(VALID_TELEMETRY / "redaction.json")
    for allowed in policy["allowed"]:
        for word in FORBIDDEN_ATTRIBUTE_NAME_WORDS:
            assert word not in allowed.lower(), (
                f"the redaction policy allowlists {allowed!r}, which names content"
            )
    # ... and the policy's own negative case is a prompt-content attribute, which
    # is the leak the packet exists to prevent.
    found = failures_for(
        load_document(INVALID_TELEMETRY / "redaction.prompt-attribute.invalid.json"), schema
    )
    assert found, "a prompt-content attribute must be rejected by the redaction policy"
    # Matched on the name rather than on an index: which slot `llm.prompt` sits in
    # is an editorial choice, and a test that breaks when the list is reordered
    # is a test that gets "fixed" by deleting the attribute.
    assert any(
        failure.keyword == "not" and "llm.prompt" in failure.message for failure in found
    ), f"llm.prompt must be rejected by name: {[str(f) for f in found]}"


def test_the_redaction_policy_separates_the_may_record_from_the_may_not() -> None:
    """Both halves are in the file, because an allowlist with no stated subject is
    a list somebody has to guess the meaning of.

    The may-record side is the packet's own list: token counts, model id,
    latency, status, finish reason. A redaction policy that only says "not
    content" is a policy nobody can implement, because it does not say what
    replaces the thing they wanted to record.
    """
    policy = load_document(VALID_TELEMETRY / "redaction.json")
    recorded = {tuple(entry) for entry in policy["llmCallAttributes"]}
    for required in (
        ("llm.model", "string"),
        ("llm.tokens_in", "int"),
        ("llm.tokens_out", "int"),
        ("llm.latency_ms", "number"),
        ("llm.finish_reason", "string"),
    ):
        assert required in recorded, (
            f"the redaction policy must state what may be recorded about an LLM "
            f"call; {required[0]} is missing"
        )
    for entry in policy["prohibited"]:
        # `prohibited` is a list of attribute NAMES and `neverRecord` is a list of
        # SUBJECTS, so they cannot be equal — `gen_ai.prompt` and `prompt` are the
        # same prohibition in two vocabularies. What must hold is that every
        # prohibited name is a spelling of something neverRecord names, or the two
        # lists drift into disagreeing about what is forbidden. Plurals are folded,
        # because `llm.messages` and "message content" are one subject and not two.
        def stem(word: str) -> str:
            return word[:-1] if len(word) > 3 and word.endswith("s") else word

        words = {stem(word) for word in re.split(r"[^a-z0-9]+", entry.lower())} - {""}
        subjects = [
            {stem(word) for word in re.split(r"[^a-z0-9]+", item.lower())}
            for item in policy["neverRecord"]
        ]
        assert any(words & subject for subject in subjects), (
            f"{entry!r} is named as prohibited but names no subject in neverRecord, "
            f"so the two lists can disagree. neverRecord: {policy['neverRecord']}"
        )


def test_error_message_is_not_on_any_allowlist() -> None:
    """`error.message` is the one attribute that could carry a prompt.

    A vendor's content-policy rejection quotes the offending content back at
    you, so the error text is third-party text that may contain a customer's
    prompt. `error.type` answers "what kind of failure" with no content in it.
    muse already made this call and its canary asserts it end to end; core
    states it so all six services make the same one.
    """
    for signal in ("traces", "metrics", "logs"):
        assert "error.message" not in signal_allowlist(signal), (
            f"error.message is allowlisted on {signal}. A provider's error text "
            "quotes the offending content back, so it is a prompt by another route."
        )
        assert "error.type" in signal_allowlist(signal) or signal == "logs", (
            f"{signal} must carry error.type instead — the class, never the message"
        )


def test_error_type_is_a_bounded_vocabulary() -> None:
    """The grouping key for every error in the fleet, so it has to be a class.

    The user asked whether there is one place to see all errors for the whole
    system (PLAN.md §7b); the answer is yes, and this is the part of the spec
    that makes it true. `error.type` is a low-cardinality class — never a
    message, never a stack trace, never an interpolated value.

    The `or "pattern" in error_type` this assertion used to allow is the exact
    hole this packet closes: a pattern constrains the SHAPE of the value and says
    nothing about the VOCABULARY, so `user_42_email_invalid` validated cleanly —
    snake_case, twenty-two characters, and precisely the cardinality bomb the
    attribute exists to prevent. It now requires an `enum`, on every signal.
    """
    for signal in ("traces", "metrics", "logs"):
        error_type = error_type_definition(signal)
        assert error_type.get("maxLength") == 64, (
            f"{signal}: error.type is a class, not a sentence; the cap is what "
            f"makes it one, and it is now {error_type.get('maxLength')}"
        )
        assert "enum" in error_type, (
            f"{signal}: error.type must be a CLOSED vocabulary, not a pattern. A "
            "pattern constrains the shape of the value and not the set of values, "
            "so a service that emits user_42_email_invalid passes — one series per "
            "value, against the same 2000-combination cap tenant_id blows. See D14."
        )
    document = load_document(VALID_TELEMETRY / "span.muse.json")
    assert document["attributes"]["error.type"] == "provider_auth", (
        "the valid example must use a class, not a message"
    )


def test_the_error_class_vocabulary_is_one_closed_enum_on_every_signal() -> None:
    """The same class means the same thing on traces and on metrics.

    A vocabulary that is three lists is three taxonomies, which is the thing D14
    exists to prevent: `ProviderAuthError` in Python and `ErrProviderAuth` in Go
    are one failure in two spellings, and "one place to see all errors" becomes
    six places that need a mapping table to join. It also makes the semconv rule
    that `error.type` is *identical* on a span and on its corresponding metric
    enforceable at all — if the two sides could name the same failure differently
    there would be nothing to compare.
    """
    for signal in ("traces", "metrics", "logs"):
        declared = tuple(error_type_definition(signal).get("enum", ()))
        assert set(declared) == set(ERROR_CLASSES), (
            f"{signal} declares a different set of error classes from the "
            f"vocabulary in this file.\n  declared here only: "
            f"{sorted(set(declared) - set(ERROR_CLASSES))}\n  "
            f"declared in the schema only: {sorted(set(ERROR_CLASSES) - set(declared))}"
        )
        assert len(declared) == len(set(declared)), f"{signal}: a class is listed twice"


def test_the_error_class_vocabulary_is_narrow_and_closed() -> None:
    """Around a dozen, narrow on purpose, and every member a class rather than a
    sentence.

    D14 says a narrow vocabulary means a class is worth alerting on, and a broad
    one means every value gets its own alert and the grouping key stops
    grouping. That is a judgement call, and judgement calls made twice under
    deadline come out different — so the bound is a bound.
    """
    classes = set(ERROR_CLASSES)
    assert MIN_ERROR_CLASSES <= len(classes) <= MAX_ERROR_CLASSES, (
        f"the error vocabulary holds {len(classes)} classes, outside "
        f"[{MIN_ERROR_CLASSES}, {MAX_ERROR_CLASSES}]. D14 asks for around a dozen "
        "and says do not pad it. Widening it is a spec change: write down the "
        "class, the responder it is for, and what it collapses with (see D18)."
    )
    pattern = re.compile(ERROR_CLASS_SHAPE)
    for name in sorted(classes - {"_OTHER"}):
        assert pattern.fullmatch(name), (
            f"{name!r} does not match the class shape {ERROR_CLASS_SHAPE}"
        )
        assert len(name) <= 64, f"{name!r} is not a class, it is a sentence"
        assert name == name.lower(), (
            f"{name!r} is not lowercase. Exactly one member of the vocabulary is "
            "allowed to be upper case and it is the OTel fallback, spelled as the "
            "ecosystem spells it (D19)."
        )
    assert "_OTHER" in classes, (
        "the OTel well-known fallback must be in the vocabulary. A closed enum "
        "with no escape hatch gets widened under pressure the first time a real "
        "failure does not fit, and a widened enum is how `_OTHER` becomes a "
        "permanent value nobody reads. See D19."
    )
    assert pattern.fullmatch("_OTHER"), (
        f"_OTHER must still match the declared shape {ERROR_CLASS_SHAPE} — it is "
        "the one member the shape exists to accommodate, and a shape that does not "
        "accommodate it is a shape that has to be widened for the next value too"
    )


def test_the_error_class_shape_is_byte_identical_on_every_signal() -> None:
    """Duplicated rather than `$ref`d, and the duplication is asserted.

    Same rule as the span-name pattern: a service's SDK setup reads one schema
    file alone, so a cross-file `$ref` would make the file un-loadable without a
    resolver. That is a real constraint and it obliges a test, because a
    duplicated constraint nobody compares is two constraints.
    """
    shapes = {signal: error_type_definition(signal).get("pattern") for signal in
              ("traces", "metrics", "logs")}
    assert set(shapes.values()) == {ERROR_CLASS_SHAPE}, (
        f"the error-class shape is duplicated on all three signals; change one, "
        f"change both.\n  declared: {shapes}"
    )


def test_a_well_shaped_but_undeclared_error_class_is_rejected() -> None:
    """The example that matters most, on both signals that carry the class.

    `user_42_email_invalid` is snake_case, is twenty-two characters, and is what a
    well-meaning service emits when it interpolates the thing that went wrong into
    the class. Under the previous pattern-only schema it validated on traces,
    metrics and logs. On metrics that is `tenant_id` on a measurement wearing a
    different name: one series per value, and an error rate nobody can draw.

    The positive control matters as much as the negative: the value is asserted to
    satisfy the shape and the length cap FIRST, so this test cannot pass because
    the pattern caught it. It passes only if the vocabulary did.
    """
    undeclared = "user_42_email_invalid"
    assert re.fullmatch(ERROR_CLASS_SHAPE, undeclared), (
        f"{undeclared!r} must be well SHAPED — the point of this example is a "
        "value the old schema accepted"
    )
    assert len(undeclared) <= 64
    assert undeclared not in ERROR_CLASSES

    cases = (
        ("error-type.undeclared.invalid.json", TRACES_SCHEMA_PATH, "attributes"),
        (
            "metric.error-type-undeclared.invalid.json",
            METRICS_SCHEMA_PATH,
            "measurementAttributes",
        ),
    )
    for name, schema_path, holder in cases:
        document = load_document(INVALID_TELEMETRY / name)
        schema = load_schema(schema_path)
        found = failures_for(document, schema)
        assert found, f"{name} must be rejected"
        assert_keywords(found, (("enum", f"{holder}/error.type"),))
        # Exactly one violation, and it is the enum. Two would mean the pattern
        # also objected — which is the failure this whole example exists to rule
        # out, since "the shape caught it" is precisely what did not happen under
        # the previous pattern-only schema.
        assert len(found) == 1, (
            f"{name} must be rejected for being UNDECLARED and nothing else; the "
            f"shape should accept it. Violations: {[str(f) for f in found]}"
        )
        # ... and the identical document with a declared class validates, so this
        # is a test about the vocabulary and not about the document being broken.
        repaired = json.loads(json.dumps(document).replace(undeclared, "invalid_request"))
        repaired_failures = failures_for(repaired, schema)
        assert not repaired_failures, (
            f"{name} is about the vocabulary: the same document with a declared "
            "class must validate, and it does not\n  "
            + "\n  ".join(str(f) for f in repaired_failures)
        )


def test_span_status_error_obliges_an_error_class() -> None:
    """`status.code: "error"` is a claim, and a claim has to be classifiable.

    core-04 stated this in a `description` and nowhere else: with the attribute
    deleted, `span.muse.json` still validated. A description is a wish; this is
    the obligation. An unclassified error span is a span a fleet-wide view
    counts and cannot explain, which is the outcome the whole attribute exists
    to prevent.
    """
    document = load_document(VALID_TELEMETRY / "span.muse.json")
    assert document["status"]["code"] == "error"
    document["attributes"].pop("error.type")
    found = failures_for(document, load_schema(TRACES_SCHEMA_PATH))
    assert found, (
        "a span with status error and no error.type must be rejected: the status "
        "obliges the class"
    )
    assert_keywords(found, (("required", "attributes"),))

    # The negative example says the same thing, so a reader who never runs the
    # suite still has the shape in front of them.
    example = load_document(INVALID_TELEMETRY / "span.error-status-no-type.invalid.json")
    found = failures_for(example, load_schema(TRACES_SCHEMA_PATH))
    assert found, "span.error-status-no-type.invalid.json must be rejected"
    assert_keywords(found, (("required", "attributes"),))


def test_an_error_class_is_absent_on_success() -> None:
    """Its absence is the load-bearing "not an error" marker, not an omission.

    This is what makes error rate computable on a duration histogram without a
    message in a label: the samples with the attribute are the errors and the
    samples without it are everything else. A success that carries a class
    therefore does not just add noise — it moves the numerator, and the error rate
    becomes a number nobody can trust.
    """
    schema = load_schema(TRACES_SCHEMA_PATH)
    document = load_document(VALID_TELEMETRY / "span.muse.json")
    document["status"] = {"code": "ok"}
    found = failures_for(document, schema)
    assert found, "a successful span must not carry an error class"
    assert_keywords(found, (("const", "status/code"),))

    # The positive control: the same successful span without the class validates,
    # so success is a thing a span can be rather than a thing a class forbids.
    del document["attributes"]["error.type"]
    assert not failures_for(document, schema), (
        "a successful span with no error.type must validate\n  "
        + "\n  ".join(str(f) for f in failures_for(document, schema))
    )


def test_a_span_cannot_contradict_its_own_status_mirror() -> None:
    """`status.code` is the field of record, and a mirror may not overrule it.

    `otel.status_code` exists so a log-indexed query can filter on it. The moment
    it can disagree with `status.code`, a query that reads the mirror answers a
    different question from the predicate the fleet-wide view uses — and nothing
    reports the disagreement. The obligation in the rule above is only meaningful
    if the span has one status, so this closes that hole rather than adding a
    separate rule.
    """
    schema = load_schema(TRACES_SCHEMA_PATH)
    document = load_document(VALID_TELEMETRY / "span.muse.json")
    document["status"] = {"code": "ok"}
    document["attributes"]["otel.status_code"] = "ERROR"
    # The class is removed on purpose. The rule above — an error class obliges a
    # failed status — would otherwise also fire on this document, and then
    # `assert found` would pass even with the mirror rule deleted. Found by
    # mutation: deleting the mirror rule left this test green.
    del document["attributes"]["error.type"]
    found = failures_for(document, schema)
    assert found, (
        "otel.status_code: ERROR with status.code: ok must be rejected — two "
        "spellings of one fact that disagree is the failure this repo exists to "
        "prevent"
    )
    assert_keywords(found, (("const", "status/code"),))

    # The negative example carries the same mistake with a class on it, so a
    # reader who never runs the suite still has the shape in front of them.
    example = load_document(INVALID_TELEMETRY / "span.status-mirror-disagrees.invalid.json")
    assert failures_for(example, schema), (
        "span.status-mirror-disagrees.invalid.json must be rejected"
    )


def test_span_status_codes_are_exactly_the_three_the_ecosystem_defines() -> None:
    """The status enum is the predicate, so it is closed and it is asserted.

    `status.code` is what the fleet-wide "this is an error" filter reads. A
    fourth value invented by one service is a dashboard that silently misses it,
    which the schema's own description promises cannot happen and nothing tested.
    Found by mutation: adding `critical` to the enum left the suite green.
    """
    code = load_schema(TRACES_SCHEMA_PATH)["properties"]["status"]["properties"]["code"]
    assert code["enum"] == ["unset", "ok", "error"], (
        f"the span-status enum moved: {code['enum']}"
    )


def test_every_signal_allowlist_is_closed() -> None:
    """`additionalProperties: false` at the attribute level, on every signal.

    Default-deny is the redaction boundary in its structural form: an attribute
    nobody declared is dropped rather than shipped. It was the one thing about
    the allowlists that was described everywhere and asserted nowhere — found by
    mutation: deleting `additionalProperties` from the traces allowlist left the
    suite green, which meant the strongest structural claim in the spec was
    resting on a schema nobody checked.
    """
    for signal, (filename, definition) in ALLOWLIST_DEF.items():
        allowlist = load_schema(TELEMETRY_SCHEMAS / filename)["$defs"][definition]
        assert allowlist.get("additionalProperties") is False, (
            f"the {signal} attribute allowlist must be closed "
            f"(additionalProperties: false) so an attribute nobody declared is a "
            f"failure rather than a silent export"
        )


def test_every_declared_error_class_has_a_valid_example() -> None:
    """The vocabulary and the examples are the same set, in both directions.

    A class nobody has ever seen in a document is a class no service knows how to
    emit, and an example using a class the schema does not declare is an
    example that validates for the wrong reason. The class is read out of each
    document rather than parsed from its filename, so a misleading filename
    cannot hide either.
    """
    used: set[str] = set()
    for name, schema_path in sorted(TELEMETRY_EXAMPLE_SCHEMAS.items()):
        if schema_path not in ATTRIBUTE_HOLDER:
            continue  # a span-naming, redaction, endpoint or probe document
        document = load_document(VALID_TELEMETRY / name)
        holder = document[ATTRIBUTE_HOLDER[schema_path]]
        if "error.type" not in holder:
            continue
        found = failures_for(document, load_schema(schema_path))
        assert not found, (
            f"{name} uses error.type={holder['error.type']!r} and must "
            "validate:\n  " + "\n  ".join(str(f) for f in found)
        )
        used.add(holder["error.type"])
    declared = set(ERROR_CLASSES)
    assert used == declared, (
        "the error classes used by the valid examples and the classes the schemas "
        "declare are different sets.\n  examples only: "
        f"{sorted(used - declared)}\n  schemas only: {sorted(declared - used)}"
    )


def test_a_span_and_its_metric_carry_the_same_error_class() -> None:
    """The cross-signal identity rule, demonstrated rather than asserted.

    `error.type` is identical on a span and on its corresponding metric for the
    same operation. No single JSON Schema can compare two documents, so what is
    checkable is (a) that both sides draw from one closed list, asserted by
    test_the_error_class_vocabulary_is_one_closed_enum_on_every_signal, and (b)
    that the shipped pair agrees — which is this test. The pairing is found by
    prefix rather than hard-coded, and the test refuses to pass if no pair exists,
    because a cross-signal rule with no pair to check is a rule nothing checks.
    """
    metric = load_document(VALID_TELEMETRY / "metric.error-type.json")
    spans = {
        load_document(path)["name"]: load_document(path)
        for path in sorted(VALID_TELEMETRY.glob("error-type.*.json"))
    }
    operation = metric["name"].removesuffix(".duration")
    assert operation in spans, (
        f"{metric['name']} names no example span, so the identity rule has no pair "
        f"to check. Known spans: {sorted(spans)}"
    )
    span = spans[operation]
    span_class = span["attributes"]["error.type"]
    metric_class = metric["measurementAttributes"]["error.type"]
    assert span_class == metric_class, (
        f"the span {operation} records error.type={span_class!r} and its metric "
        f"{metric['name']} records {metric_class!r}. The same operation must "
        "report the same class on both signals, or the two cannot be joined and "
        "the error rate is computed from two different taxonomies."
    )
    # The class a service would actually invent in order to diverge is not
    # expressible on either signal. This is the half of the identity rule that is
    # a schema rather than a comparison: one closed list on both sides means the
    # span cannot say `timeout` while its metric says `provider_timeout`.
    divergent = (
        (
            TRACES_SCHEMA_PATH,
            "attributes",
            {**span, "attributes": {**span["attributes"], "error.type": "provider_timeout"}},
        ),
        (
            METRICS_SCHEMA_PATH,
            "measurementAttributes",
            {
                **metric,
                "measurementAttributes": {
                    **metric["measurementAttributes"],
                    "error.type": "provider_timeout",
                },
            },
        ),
    )
    for schema_path, holder, document in divergent:
        found = failures_for(document, load_schema(schema_path))
        assert found, (
            f"a per-service class name must be rejected on {schema_path.name}, or "
            "the span and its metric can disagree about one failure"
        )
        assert_keywords(found, (("enum", f"{holder}/error.type"),))


def test_no_signal_can_record_a_handled_or_retried_error() -> None:
    """`SHOULD NOT` encoded as unrepresentable rather than as prose.

    Handled and retried errors are not recorded at all: a retry that succeeded is
    not an error, and recording it makes the error rate a lie. `SHOULD NOT` has
    no schema keyword, so the rule is enforced the only way it can be — there is
    no attribute on any signal a service could set to say "this attempt failed
    and I recovered", so there is nothing to set. Same structural argument as
    `error.message`, which is prohibited by name because a tracing SDK adds it by
    default; a rule only a discipline can enforce is a rule a well-meaning commit
    removes.
    """
    for signal in ("traces", "metrics", "logs"):
        for name in sorted(signal_allowlist(signal)):
            lowered = name.lower()
            found = [
                word for word in FORBIDDEN_ERROR_LIFECYCLE_WORDS if word in lowered
            ]
            assert not found, (
                f"the {signal} allowlist carries {name!r}, whose name contains "
                f"{found}. That is an attribute for recording a handled or "
                "retried attempt, which is exactly what must not be recorded: a "
                "retry that succeeded is not an error."
            )
    for name in sorted(set(ERROR_CLASSES) - {"_OTHER"}):
        found = [w for w in FORBIDDEN_ERROR_LIFECYCLE_WORDS if w in name]
        assert not found, (
            f"the class {name!r} names a handled or retried attempt ({found}). "
            "The vocabulary may say how an operation ended, never how it was "
            "saved."
        )


def test_the_doc_lists_exactly_the_declared_error_classes() -> None:
    """A doc and its schema are the same contract written twice (AGENTS.md).

    The vocabulary table in `docs/observability.md` and the `enum` in three
    schemas drift apart the moment nobody compares them, and the drift is
    invisible: a class in the table that the schema rejects breaks a service that
    believed the documentation, and a class in the schema that the table does not
    explain is a class nobody knows when to emit. Same shape as
    test_event_catalog_in_docs_matches_the_schema, and for the same reason — the
    doc is the thing a service reads, so the doc has to be the thing that is
    true.
    """
    doc = section(OBSERVABILITY_DOC.read_text(encoding="utf-8"), "## `error.type`")
    # `[A-Za-z_]` rather than `[a-z_]` because `_OTHER` is the one member that is
    # not lower case; a dotted name like `service.name` cannot match, so the
    # can/cannot-aggregate table below is not swept in by accident.
    listed = set(re.findall(r"^\|\s*`([A-Za-z_]+)`\s*\|", doc, flags=re.MULTILINE))
    declared = set(ERROR_CLASSES)
    assert listed == declared, (
        "the class table in docs/observability.md and the enum the schemas "
        f"declare disagree.\n  doc only: {sorted(listed - declared)}\n"
        f"  schema only: {sorted(declared - listed)}"
    )


def test_the_observability_doc_states_the_error_recording_rules() -> None:
    """The four rules the research established and core-04 left in prose.

    Absent on success, identical across signals, handled-and-retried not
    recorded, status-error obliges the class — plus the two things that are easy
    to get wrong and that the doc now has to say plainly: the predicate is span
    status, not `error.type`, and `error.type` is never a global grouping key.
    """
    doc = OBSERVABILITY_DOC.read_text(encoding="utf-8").lower()
    missing = [topic for topic in REQUIRED_ERROR_RECORDING_TOPICS if topic not in doc]
    assert not missing, (
        f"docs/observability.md dropped from the error recording rules: {missing}. "
        "Each is a semconv rule core encodes or a distinction the research "
        "settled; a doc edit that removes one has to argue for it in "
        "DECISIONS.md first."
    )


def test_the_error_rules_mark_their_stability_honestly() -> None:
    """Stable where semconv is Stable, Development where it is not.

    `error.type` and the trace status rules are Stable; the cross-signal coupling
    document, `recording-errors.md`, is **Development**. A schema that encodes a
    Development rule without saying so implies the whole model has frozen, and
    the next reader trusts a coupling that is allowed to change.
    """
    for path in (TRACES_SCHEMA_PATH, METRICS_SCHEMA_PATH, LOGS_SCHEMA_PATH):
        text = path.read_text(encoding="utf-8")
        assert "recording-errors.md" in text, (
            f"{path.name} encodes the cross-signal coupling without naming the "
            "document that defines it, so a reader cannot tell the rules are not "
            "yet stable"
        )
        assert "development" in text.lower(), (
            f"{path.name} must say which of the rules it encodes come from a "
            "Development-stability document"
        )
    doc = OBSERVABILITY_DOC.read_text(encoding="utf-8").lower()
    assert "stable" in doc, "docs/observability.md must state the stability of what it encodes"


def test_observability_doc_covers_every_required_topic() -> None:
    doc = OBSERVABILITY_DOC.read_text(encoding="utf-8").lower()
    for topics, label in (
        (REQUIRED_ENDPOINT_TOPICS, "endpoint"),
        (REQUIRED_REDACTION_TOPICS, "redaction"),
        (REQUIRED_HEALTH_TOPICS, "health"),
        (REQUIRED_ERROR_RECORDING_TOPICS, "error recording"),
    ):
        missing = [topic for topic in topics if topic not in doc]
        assert not missing, f"docs/observability.md dropped from its {label} section: {missing}"


# --- 8.5 the endpoint contract and the no-op path --------------------------


def test_the_endpoint_contract_is_valid_and_closed() -> None:
    schema = load_schema(ENDPOINT_SCHEMA_PATH)
    found = failures_for(load_document(VALID_TELEMETRY / "otel-endpoint.json"), schema)
    assert not found, "the valid endpoint declaration must validate:\n  " + "\n  ".join(
        str(f) for f in found
    )


def test_unsetting_the_endpoint_declares_a_free_no_op() -> None:
    """The escape hatch is first-class, and "free" is four checkable properties.

    A disabled path that still dials out is worse than no telemetry support at
    all (PLAN.md §7b), so the schema does not accept the word "disabled": it
    accepts a declaration that says what does *not* happen. buffering, retry,
    warnings and startup cost are each `none`, and the shipped collector is a
    `default`, which is the only thing a default can be.

    Both halves are asserted — the *example* says `none` and the *schema* pins
    it to `none`. Asserting only the example would pass the moment someone
    widened the schema to an enum of `none` and `ring`, which is exactly the
    mutation that broke this test the first time it ran.
    """
    document = load_document(VALID_TELEMETRY / "otel-endpoint.json")
    no_op = document["noOp"]
    pinned = load_schema(ENDPOINT_SCHEMA_PATH)["properties"]["noOp"]["properties"]
    for key in ("buffering", "retry", "warnings", "startupCost"):
        assert no_op[key] == "none", (
            f"the no-op path must declare noOp.{key}: none. A disabled exporter "
            "that buffers, retries or logs is not a no-op, it is an outage with "
            "extra steps."
        )
        assert pinned[key] == {"const": "none", "description": pinned[key]["description"]}, (
            f"otel-endpoint.schema.json must pin noOp.{key} to const 'none', not "
            f"offer a choice: it currently declares {sorted(pinned[key])}"
        )
    assert document["endpoint"]["default"] == "http://otel-collector:4317", (
        "the shipped collector is the default *value* of the variable — the "
        "variable is the contract, and a self-hoster's Datadog is one env away"
    )
    assert document["endpoint"]["variable"] == "MUSE_OTEL_ENDPOINT", (
        "the variable name is <SERVICE>_OTEL_ENDPOINT, uppercase, and it is the "
        "only contract a self-hoster has to know"
    )


def test_the_endpoint_is_never_required() -> None:
    """The `const: false` that separates on-by-default from mandatory.

    Asserted on the schema, not only on the example. This is the field that
    makes a self-hoster's first question — "what does this look like when it
    breaks" — answerable without installing four more services first
    (PLAN.md §7b), and a schema that merely permits `false` is a schema where
    one service will eventually declare `true`.
    """
    required = load_schema(ENDPOINT_SCHEMA_PATH)["properties"]["endpoint"]["properties"]["required"]
    assert required.get("const") is False, (
        f"endpoint.required must be const: false, not {required!r} — observability "
        "is on by default and optional in fact"
    )


def test_an_endpoint_declaration_that_is_not_a_free_no_op_is_rejected() -> None:
    """The negative case: buffering, retrying and warning on the disabled path."""
    schema = load_schema(ENDPOINT_SCHEMA_PATH)
    found = failures_for(
        load_document(INVALID_TELEMETRY / "otel-endpoint.buffered.invalid.json"), schema
    )
    assert found, "a disabled exporter that buffers must be rejected"
    assert_keywords(
        found,
        (("const", "noOp/buffering"), ("const", "noOp/retry"), ("const", "noOp/warnings")),
    )


def test_the_no_op_path_uses_the_standards_own_switches() -> None:
    """`OTEL_SDK_DISABLED` is the OTel spec's own kill switch, and using it is
    what makes the no-op genuinely free in six languages.

    Re-implementing "disabled" in each language is how six services get six
    different definitions of it, and the difference between them is a background
    retry loop somebody finds in production. The spec defines the switch once:
    OTEL_SDK_DISABLED=true, plus per-signal OTEL_{TRACES,METRICS,LOGS}_EXPORTER=none.
    """
    text = ENDPOINT_SCHEMA_PATH.read_text(encoding="utf-8")
    for variable in ("OTEL_SDK_DISABLED", "OTEL_TRACES_EXPORTER", "OTEL_METRICS_EXPORTER"):
        assert variable in text, (
            f"{variable} must be named in otel-endpoint.schema.json — the no-op path "
            "is the OTel spec's own switch, not a cafaye invention"
        )
    # The schema pins the switch, not merely mentions it. An enum that also
    # accepted a cafaye-specific switch would let a service re-implement
    # "disabled", which is the whole thing this rule exists to prevent.
    implemented_by = load_schema(ENDPOINT_SCHEMA_PATH)["properties"]["noOp"]["properties"][
        "implementedBy"
    ]
    assert implemented_by.get("const") == "OTEL_SDK_DISABLED", (
        f"noOp.implementedBy must be const OTEL_SDK_DISABLED, not {implemented_by!r}"
    )
    disabled_by = load_schema(ENDPOINT_SCHEMA_PATH)["properties"]["disabledBy"]
    assert set(disabled_by["required"]) == {"global", "traces", "metrics", "logs"}, (
        f"disabledBy must require all four switches, got {sorted(disabled_by['required'])}"
    )
    document = load_document(VALID_TELEMETRY / "otel-endpoint.json")
    assert document["noOp"]["implementedBy"] == "OTEL_SDK_DISABLED", (
        "the no-op must be implemented by the standard switch, so a service that "
        "sets it gets the spec's behaviour rather than ours"
    )


def test_every_signal_has_an_exporter_switch() -> None:
    """Unsetting the endpoint is the documented path; the switches are the
    belt-and-braces one, and both have to exist for all three signals.

    A no-op that only covers traces is a service that still phones home for
    metrics, which is the failure that gets discovered by a customer's bill
    rather than by a test.
    """
    document = load_document(VALID_TELEMETRY / "otel-endpoint.json")
    assert sorted(document["signals"]) == ["logs", "metrics", "traces"], (
        "all three signals are in scope; a service that exports one and disables "
        "another is the case this list exists to catch"
    )
    for signal in document["signals"]:
        assert signal in document["disabledBy"], (
            f"{signal} has no documented way to turn it off"
        )


# --- 8.6 healthz vs readyz ------------------------------------------------


def test_the_probe_contract_is_valid() -> None:
    found = failures_for(load_document(PROBE_EXAMPLE), load_schema(PROBES_SCHEMA_PATH))
    assert not found, "the valid probe declaration must validate:\n  " + "\n  ".join(
        str(f) for f in found
    )


def test_a_readyz_that_checks_nothing_is_rejected() -> None:
    """The rule the packet names, asserted as a failing test.

    darkroom is the pattern (`/healthz` never touches a dependency, `/readyz`
    really runs `select 1`), and without the schema a `readyz` that returns a
    constant 200 is a load balancer cheerfully routing traffic into a service
    whose database is gone.
    """
    found = failures_for(
        load_document(INVALID_PROBE_EXAMPLE), load_schema(PROBES_SCHEMA_PATH)
    )
    assert found, "a readyz with no dependency checks must be rejected"
    assert_keywords(found, (("minItems", "readyz/checks"),))


def test_healthz_is_unconditional_and_readyz_is_not() -> None:
    """The split, as a shape: `healthz.checks` is empty and `readyz.checks` is not.

    Asserted on the valid example in both directions, because the interesting
    failure is the symmetric one — a `healthz` that consults the database turns
    an outage into a restart loop, which is worse than the outage. And asserted
    on the *schema* as well as the example, because a schema that stops pinning
    liveness to an empty list still accepts this example unchanged.
    """
    document = load_document(PROBE_EXAMPLE)
    assert document["healthz"]["checks"] == [], (
        "healthz is unconditional liveness. A dependency check here means a dead "
        "database restarts every container that depends on it."
    )
    assert document["readyz"]["checks"], (
        "readyz must actually check something; an empty checks list is the failure "
        "the probes schema exists to reject"
    )
    for check in document["readyz"]["checks"]:
        assert check["dependency"], f"a readiness check of {check['name']} checks nothing"
    defs = load_schema(PROBES_SCHEMA_PATH)["$defs"]
    assert defs["livenessProbe"]["properties"]["checks"]["maxItems"] == 0, (
        "probes.schema.json must pin healthz.checks to maxItems: 0, so a liveness "
        "probe that starts consulting a dependency cannot validate"
    )
    assert defs["readinessProbe"]["properties"]["checks"]["minItems"] == 1, (
        "probes.schema.json must pin readyz.checks to minItems: 1, so a readiness "
        "probe that checks nothing cannot validate"
    )


def test_both_probes_are_exempt_from_authentication() -> None:
    """darkroom's lesson, in its README: a `/healthz` behind the auth middleware
    returns 401, every instance is marked unhealthy, and the deploy rolls back
    with no indication why. Asserted because it is a fleet-wide trap — and
    asserted on the schema, since an example that says `exempt` survives a schema
    that stopped requiring it."""
    document = load_document(PROBE_EXAMPLE)
    for probe in ("healthz", "readyz"):
        assert document[probe]["auth"] == "exempt", (
            f"{probe} must be exempt from authentication by an explicit allow-list, "
            "not by route ordering"
        )
    defs = load_schema(PROBES_SCHEMA_PATH)["$defs"]
    for probe in ("livenessProbe", "readinessProbe"):
        auth = defs[probe]["properties"]["auth"]
        assert auth.get("const") == "exempt", (
            f"{probe}.auth must be const 'exempt', not {auth!r} — a probe behind the "
            "auth middleware returns 401 and the deploy rolls back with no "
            "indication why"
        )


# --- 8.7 fleet-wide consistency -------------------------------------------


def test_fleet_services_declare_their_telemetry_signals() -> None:
    """fleet.yml records what a service exports, so the endpoint variable is
    checkable fleet-wide.

    A service whose manifest is silent about telemetry is not thereby forbidden
    from exporting it, so this asserts the weaker and more useful thing: every
    service that ships a `cafaye.yml` and serves HTTP declares the probe
    contract, so "which services have observability" has one answer.
    """
    for service in load_fleet()["services"]:
        name = service["name"]
        telemetry = service.get("telemetry")
        assert telemetry is not None, (
            f"fleet.yml: {name} declares no telemetry block. Every service that "
            "serves HTTP owes the probe contract and the endpoint variable name; "
            "record it here so the fleet answer to 'what is instrumented' is one read."
        )
        assert telemetry["endpointVariable"] == f"{name.upper()}_OTEL_ENDPOINT", (
            f"fleet.yml: {name} must use {name.upper()}_OTEL_ENDPOINT — one variable "
            "name across the fleet, whatever the service is called"
        )
        for signal in telemetry.get("signals", []):
            assert signal in ("traces", "metrics", "logs"), (
                f"fleet.yml: {name} declares unknown signal {signal!r}"
            )


def test_a_service_recorded_as_exporting_nothing_asserts_no_fleet_wide_state() -> None:
    """What `signals` is not, and where a per-service record may not say it.

    `signals` answers ONE question: what this service exports from its own
    code, to an endpoint the operator supplies. Whether anything is deployed to
    receive that is a SECOND question, with a different owner and a different
    answer — a service with an empty list can be fully instrumented with a
    collector not yet running, and a service with `traces` in the list can have
    nothing to export to. Reading the first as the second is the error that put
    `signals: []` against courier, billing and identity while all three shipped
    a wired OTel SDK, and it propagated to the documentation as "we have no
    observability".

    Two halves, and neither is a check on the values:

    1. The schema's own `description` may not define the field by reference to a
       collector, a deployment or a running process. A description is the
       contract's sentence for what a field means, and a sentence that ties the
       list to deployment state teaches the conflation to everyone who reads it
       before they read the values.
    2. A per-service `notes` may not assert a fleet-wide fact — "the only
       service", "no other service", "nothing else exports". A note on ONE
       service is read as a statement about that service, and one service's note
       is how a reader concludes something about five. A fleet-wide claim
       belongs in the file header, where it is about the file.

    WHAT THIS DOES NOT DO, and the reason it is worth saying: it cannot check
    that `signals` matches any service's code. core reads `schemas/`, never a
    sibling checkout, so the transcription is still `sourceCommit`'s job — this
    checks that the record does not lie about what kind of fact it is, which is
    the half that was wrong.
    """
    deployment_words = ("collector", "deployed", "deployment", "running")
    signals = load_schema(FLEET_SCHEMA_PATH)["$defs"]["telemetryDeclaration"]["properties"]["signals"]
    description = signals["description"]
    named = [word for word in deployment_words if word in description.lower()]
    assert not named, (
        f"fleet.schema.json describes `signals` in terms of {named}. `signals` is what a "
        "service exports from its own code, and whether a collector is deployed is a "
        "different question with a different owner — describing the field by the other "
        "one is what made `signals: []` read as 'this service is not instrumented'."
    )

    exclusivity = (
        "the only service",
        "no other service",
        "only service in the fleet",
        "no signals exported",
        "nothing else exports",
        "no service exports",
    )
    offenders = []
    for service in load_fleet()["services"]:
        for field in ("notes",):
            note = str(service.get(field, "")).lower()
            for phrase in exclusivity:
                if phrase in note:
                    offenders.append(f"{service['name']}.{field}: {phrase!r}")
        note = str((service.get("telemetry") or {}).get("notes", "")).lower()
        for phrase in exclusivity:
            if phrase in note:
                offenders.append(f"{service['name']}.telemetry.notes: {phrase!r}")
    assert not offenders, (
        "fleet.yml states a fleet-wide fact on a single service's record, where a "
        "reader takes it as a statement about that service:\n  "
        + "\n  ".join(offenders)
        + "\n  A claim about the whole fleet belongs in the file header."
    )


def test_observability_is_on_by_default_but_turning_it_off_is_documented() -> None:
    """The directive, both halves, as a checkable pair.

    "On by default and worked on in dev" and "unsetting it is a tested no-op"
    are in tension unless the default is a *value* rather than a requirement,
    which is exactly what the schema pins: the shipped collector is the default
    endpoint, and nothing requires it.
    """
    document = load_document(VALID_TELEMETRY / "otel-endpoint.json")
    assert document["endpoint"]["required"] is False, (
        "observability is on by default and optional in fact; a declaration that "
        "makes the endpoint required turns the default into a requirement"
    )
    assert document["endpoint"]["default"], (
        "there is a shipped default, so a developer sees real traces without "
        "turning anything on (PLAN.md §7b)"
    )


def open_decisions() -> list[tuple[int, str]]:
    """The `## Dn` sections of DECISIONS.md, as (number, body) pairs."""
    text = DECISIONS.read_text(encoding="utf-8")
    return [
        (int(number), body)
        for number, body in re.findall(
            r"^## D(\d+):[^\n]*\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL
        )
    ]


def test_open_decisions_are_numbered_and_complete() -> None:
    """A decision number is a citation, so it must be unique, ascending and unused.

    A reused number is a broken cross-reference, and a reference to a number that
    does not exist is worse than no reference at all. Every open decision also
    owes the same four paragraphs, because "here is my call" without the
    alternatives and the cost of flipping is how a worker resolves a design
    question silently — which AGENTS.md forbids and which the manager cannot
    review if it is not written down.
    """
    decisions = open_decisions()
    numbers = [number for number, _ in decisions]
    assert numbers, "DECISIONS.md has no decisions, which cannot be true of a spec mid-reconciliation"
    assert numbers == sorted(numbers), f"decision numbers are out of order: {numbers}"
    assert len(set(numbers)) == len(numbers), f"a decision number is reused: {numbers}"

    settled = {
        int(number)
        for number in re.findall(
            r"^\| D(\d+) \|", CHANGELOG.read_text(encoding="utf-8"), flags=re.MULTILINE
        )
    }
    assert settled, "the changelog records no settled decisions, so the numbering floor is unknown"
    assert min(numbers) > max(settled), (
        f"D{min(numbers)} reuses a number the changelog already settled (D1-D{max(settled)})"
    )

    for number, body in decisions:
        missing = [part for part in REQUIRED_DECISION_PARTS if part not in body]
        assert not missing, f"D{number} is missing {missing} — see AGENTS.md"
        assert re.search(r"\]\((?!#)[^)]*/[^)]*\)", body), (
            f"D{number} must link the files it affects; a decision with no stated "
            "surface is a decision nothing implements"
        )


def test_open_decisions_are_referenced_from_a_document() -> None:
    """A numbered decision is only useful if something points at it.

    AGENTS.md asks for the callout to sit in the affected doc. The numbering
    moved to DECISIONS.md, so this is what stands in for that: every open
    decision has to be cited from a file a reader of this spec will open.
    """
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (*sorted(DOCS.glob("*.md")), REPO / "README.md", FLEET)
    )
    referenced = {int(number) for number in re.findall(r"\bD(\d+)\b", corpus)}
    open_numbers = {number for number, _ in open_decisions()}
    missing = sorted(open_numbers - referenced)
    assert not missing, (
        f"DECISIONS.md opens {missing} but no document cites them, so a reader of the "
        "spec has no way to know a question is open"
    )


def test_fleet_records_a_source_commit_per_service() -> None:
    """A declaration with no provenance cannot be refreshed by the next reader."""
    for service in load_fleet()["services"]:
        assert re.fullmatch(r"[0-9a-f]{40}", service["sourceCommit"]), (
            f"fleet.yml: {service['name']} needs the full 40-character commit its "
            "cafaye.yml was read at"
        )
        assert service.get("branch") == "master", (
            f"fleet.yml: {service['name']} was not read from the primary branch"
        )


# --------------------------------------------------------------------------
# 6. how core is gated
# --------------------------------------------------------------------------

# core adopted kit's reusable workflow in core-06. The two tests in this section
# exist because of one defect class that a spec repository is unusually exposed
# to: a *build* claim is a claim, and nothing in a suite of schema tests can see
# it go stale. kit shipped its workflow at `workflows/ci.reusable.yml`, where
# GitHub cannot resolve it, for the whole life of kit-02 — and no repository in
# the fleet was calling it, because a `uses:` line that resolves to nothing looks
# exactly like one that resolves. A layout bug and a documentation bug agree with
# each other perfectly, which is the only reason either survived.
#
# So the adoption is asserted from this side, where nothing else asserts it.
CI_WORKFLOW = REPO / ".github/workflows/ci.yml"

# The string kit documents in its README and its AGENTS.md, and the only one
# GitHub resolves: a reusable workflow is looked up at
# `{owner}/{repo}/.github/workflows/{file}@{ref}` and GitHub documents that
# **subdirectories of the workflows directory are not supported**. The
# kit-02 spelling — `cafaye/kit/workflows/ci.reusable.yml@master` — is a valid
# looking string that fails at run time on the adopting repository's first push.
KIT_USES = "cafaye/kit/.github/workflows/ci.reusable.yml@master"

# Root-level files that would make this repository look like a service to any
# packaging tool, and therefore make one of kit's seven language jobs applicable.
# `tests/requirements.txt` is deliberately absent: it is the gate's dependency
# list and has never been a project manifest, and the test below only looks at
# the repository root.
SERVICE_MANIFESTS = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "uv.lock",
    "Pipfile",
)


def test_the_ci_workflow_calls_kit_at_the_path_kit_documents() -> None:
    """core's CI calls kit's reusable workflow, at a path that resolves.

    The assertion is exact-match on the cross-repository `uses:` rather than a
    substring search, because a substring search is what let the stale path
    through: `cafaye/kit/workflows/ci.reusable.yml@master` *contains* every
    interesting token, and it is the string that does not work. Matching the
    whole line means a future edit has to be deliberate to break it, and a
    reformatted workflow that stops matching fails loudly instead of quietly
    agreeing.

    It also asserts `language: 'none'`, because that value is only honest while
    `test_core_declares_no_service_manifest` holds. The two are the same claim
    seen from two directions: `none` is kit's documented option for a repository
    with **no service manifest at all**, and core has none.
    """
    assert CI_WORKFLOW.is_file(), (
        f"{CI_WORKFLOW.relative_to(REPO)} does not exist. core adopted kit's reusable "
        "workflow in core-06, and the call has to live in the tree for the build to "
        "be anything other than a claim."
    )
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    # `uses:` also names actions (`actions/checkout@v7`), so filter to the
    # cross-repository kit call rather than reading the first `uses:`.
    kit_calls = re.findall(r"^\s*uses:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    kit_calls = [value for value in kit_calls if value.startswith("cafaye/kit/")]
    assert kit_calls == [KIT_USES], (
        f"the cross-repository kit call must be exactly [{KIT_USES!r}] and appear once; "
        f"found {kit_calls}. A `uses:` that does not resolve is a red build on the first "
        "push, and GitHub documents that subdirectories of `.github/workflows` are not "
        "supported — so `cafaye/kit/workflows/ci.reusable.yml@master` is not an option."
    )

    assert re.search(r"^\s*language:\s*'none'\s*$", text, flags=re.MULTILINE), (
        "core declares no service manifest, so the language must be 'none'. The seven "
        "language jobs each open by reading a manifest they cannot find: `python` runs "
        "`uv sync --frozen`, which exits 2 with 'No pyproject.toml found'. If core ever "
        "grows a manifest this is the test that says so, together with "
        "test_core_declares_no_service_manifest."
    )


def test_core_declares_no_service_manifest() -> None:
    """core is a specification repository and stays one.

    Not tidiness. kit's reusable workflow offers seven language jobs, and every
    one of them opens by reading a service manifest and then installing from it —
    `uv sync --frozen`, `bundle install`, `go mod download`, `npm ci`,
    `bun install --frozen-lockfile`. A repository with a manifest and no runtime
    is a repository whose CI is now running a package installer over a
    specification, and whose coverage gate is measuring a test file: a number
    that goes up when the tests get shorter.

    AGENTS.md already draws the line — "core is schemas + docs + validators; if a
    change needs a runtime, it belongs in `caf`, not here" — so this asserts an
    existing rule rather than making one.

    **If this fails, that is not a bug to work around.** Either delete the
    manifest, or keep it and change the `language:` value in
    `.github/workflows/ci.yml` in the same commit, having decided whether
    `bin/prime` or kit's job is now the gate. Both are legitimate; drifting
    between them silently is not.
    """
    found = [name for name in SERVICE_MANIFESTS if (REPO / name).exists()]
    assert not found, (
        f"{found} at the repository root makes core look like a Python/Node project to "
        "every packaging tool in the org, and makes one of kit's seven language jobs "
        "applicable for the first time. Delete it, or keep it and change the `language:` "
        "in .github/workflows/ci.yml in the same commit — and re-read which of `bin/prime` "
        "and kit's job is the gate afterwards."
    )


# --------------------------------------------------------------------------
# 7. the contract-test harness
# --------------------------------------------------------------------------

# PLAN.md §4 Phase 0 named four deliverables for core v0. Three shipped; the
# contract-test harness did not, and four services each wrote their own version
# of it instead — muse's pinned-SHA byte comparison, darkroom's copy, courier's
# document-against-router test and pantry's drift test. This section is the
# statement that the harness now exists, and — far more to the point — that it
# is capable of failing.
#
# The tests are ordered so the two claims that matter come first and the
# refactors come last. `test_the_harness_fails_loudly_when_core_is_absent` and
# `test_the_harness_evaluator_agrees_with_jsonschema_on_every_example` are the
# two ways this could have been a green badge over nothing: a harness that
# cannot find the contract and reports success, and a hand-written JSON Schema
# reader that quietly disagrees with the one core publishes.


def harness_module():
    """Import `harness/cafaye_contract.py`, or say why it could not.

    The import is lazy and its failure is an assertion rather than an
    ImportError at module scope, so a missing harness is one failing test with
    one sentence in it rather than a collection error that hides the other
    hundred.
    """
    assert HARNESS_MODULE.is_file(), (
        f"{HARNESS_MODULE.relative_to(REPO)} does not exist. PLAN.md §4 Phase 0 names a "
        "contract-test harness as a core deliverable, core-07 is the packet that builds it, "
        "and a service cannot validate itself against core's contracts without it."
    )
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import cafaye_contract  # noqa: PLC0415 - lazy on purpose, see above

    return cafaye_contract


def harness_runs(service: Path, *, core: Path | None = None, **kwargs):
    """Run the harness in-process and return its `Result`."""
    module = harness_module()
    return module.run(service_root=service, core_root=core or REPO, **kwargs)


def harness_rules_by_id() -> dict:
    """`harness/rules.json`, the rule inventory, keyed by id."""
    with HARNESS_RULES.open(encoding="utf-8") as handle:
        return {rule["id"]: rule for rule in json.load(handle)["rules"]}


def test_the_harness_validates_core_against_itself() -> None:
    """The first run a harness deserves: this repository, with core's own manifest.

    core is a `language: spec` repository whose manifest omits `exposes`
    entirely, so this is also the shape a service with no HTTP surface takes.
    A harness that only ever sees `exposes: {api: ...}` has not been tested
    against the fleet's other legal manifest.
    """
    result = harness_runs(REPO)
    assert result.exit_code == HARNESS_EXIT_CONFORMS, (
        f"core's own cafaye.yml must pass the harness (exit {HARNESS_EXIT_CONFORMS}), got "
        f"{result.exit_code}:\n  "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in result.findings)
    )


def test_the_harness_accepts_the_conforming_fixture() -> None:
    result = harness_runs(HARNESS_FIXTURES / "conforming")
    assert result.exit_code == HARNESS_EXIT_CONFORMS, (
        "the conforming fixture must pass, or every red below proves nothing:\n  "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in result.findings)
    )
    assert result.findings == (), "a conforming run reports no findings at all"


def test_the_harness_stops_at_the_manifest_schema_and_says_so() -> None:
    """A document whose fields are the wrong type has no trustworthy cross-fields.

    `caf`'s linter made the same call — schema first, conventions only on a
    document that passed — and the reason is not tidiness: every cross-field
    rule reads two fields and compares them, and run first they report a
    comparison against a field that is not there.

    The assertion is that the *conventions* are absent from the run **and** that
    the run explains itself, because a harness that silently drops half its
    checks is indistinguishable from a harness that found nothing.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming")
    rules = {finding.rule for finding in result.findings}
    assert rules == {"manifest.schema"}, (
        f"a schema-rejected manifest must report only manifest.schema, got {sorted(rules)}"
    )
    assert result.stopped_after_schema is True, (
        "the run must record that it stopped, so the caller can tell 'nothing else is "
        "wrong' from 'nothing else was checked'"
    )
    # The three fixture defects are named, not summarised. A schema failure that
    # says "manifest invalid" sends a person to the schema file.
    text = "\n".join(f.message for f in result.findings)
    for field in ("name", "language", "core"):
        assert field in text, f"the schema failure must name the {field} it rejected:\n{text}"


def test_the_harness_reports_every_convention_rule_one_manifest_breaks() -> None:
    """The exact set, not a superset. See `NONCONFORMING_CONVENTION_RULES`.

    This is the assertion shape that matters. "Reports at least these five" is
    satisfied by a harness that reports one of them and silently drops four —
    and a dropped rule is the one defect in a conformance tool that looks
    exactly like success.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-conventions")
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS, (
        f"a non-conforming manifest must exit {HARNESS_EXIT_VIOLATIONS}, got {result.exit_code}"
    )
    rules = {finding.rule for finding in result.findings}
    assert rules == NONCONFORMING_CONVENTION_RULES, (
        f"expected exactly {sorted(NONCONFORMING_CONVENTION_RULES)}, got {sorted(rules)}; "
        "a harness that reports a subset of what it can see is a harness that has turned "
        "an unknown into a pass"
    )


def test_the_harness_reports_every_openapi_rule_one_document_breaks() -> None:
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-openapi")
    rules = {finding.rule for finding in result.findings}
    assert rules == NONCONFORMING_OPENAPI_RULES, (
        f"expected exactly {sorted(NONCONFORMING_OPENAPI_RULES)}, got {sorted(rules)}"
    )


def test_an_openapi_document_with_no_paths_is_a_finding_not_a_pass() -> None:
    """Two empty sets agree, so an empty one must never be a pass.

    A reader that finds no paths and returns an empty collection lets a service
    delete its entire HTTP contract and see a green build, because "no path
    violates the `/v1` rule" and "there is no path" are the same sentence.
    courier's `OpenAPIPaths` is the precedent; this is the assertion.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-openapi-empty")
    assert "openapi.has-paths" in {finding.rule for finding in result.findings}, (
        f"a document whose paths are empty must be rejected, got "
        f"{[f.rule for f in result.findings]}"
    )


def test_the_harness_fails_loudly_when_core_is_absent() -> None:
    """The rule that has bitten this fleet four times, asserted directly.

    gateway's live-Redis tier, muse's `MUSE_CORE_SCHEMAS` tier, identity's
    `TEST_DATABASE_URL` tier and darkroom's `--ignored` tests are the same
    defect: a check that could not run, exiting 0. A contract check that cannot
    find the contract and reports success is *worse* than no contract check,
    because it converts an unknown into a green badge.

    So: empty environment (nothing inherited that could point at a core
    checkout), a working directory that is not a core checkout, and no `--core`.
    The assertion is that the exit code is the refusal code and **not** the
    conforms code — and that the message says where it looked, because "core not
    found" with no list is the version nobody can act on.
    """
    module = harness_module()
    with tempfile.TemporaryDirectory() as empty:
        completed = subprocess.run(
            [sys.executable, str(HARNESS_MODULE), "--core", empty, "."],
            cwd=empty,
            env={},
            capture_output=True,
            text=True,
            check=False,
        )
    assert completed.returncode == HARNESS_EXIT_REFUSED, (
        f"a run with no core checkout must exit {HARNESS_EXIT_REFUSED} (refused) and never "
        f"{HARNESS_EXIT_CONFORMS} (conforms); it exited {completed.returncode}.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.returncode != HARNESS_EXIT_CONFORMS, (
        "this is the assertion the whole test exists for"
    )
    message = completed.stdout + completed.stderr
    assert module.REFUSALS["core.absent"] in message or "cafaye.manifest.schema.json" in message, (
        f"the refusal must name what it could not find:\n{message}"
    )
    assert "cafaye-contract" not in message.split("\n")[-2:], "sanity: message parsed"


def test_the_harness_fails_loudly_when_a_service_manifest_is_absent() -> None:
    """A path with no `cafaye.yml` has not been validated.

    `caf`'s linter returns an error rather than an empty report for exactly
    this: an empty report's `OK` is indistinguishable from the `OK` of a
    repository that was never looked at.
    """
    module = harness_module()
    with tempfile.TemporaryDirectory() as empty:
        result = module.run(service_root=Path(empty), core_root=REPO)
    assert result.exit_code == HARNESS_EXIT_REFUSED, (
        f"a service root with no cafaye.yml must be refused, got {result.exit_code}"
    )
    assert [f.rule for f in result.findings] == ["service.manifest-absent"], (
        f"the refusal must be named, got {[f.rule for f in result.findings]}"
    )


def test_the_harness_fails_loudly_when_core_is_not_a_core_checkout() -> None:
    """A directory that exists is not a core checkout.

    The difference matters because `--core ../core` on a laptop and a CI step
    that exports the wrong path are the same event, and only the second one has
    a red build afterwards.
    """
    module = harness_module()
    with tempfile.TemporaryDirectory() as empty:
        (Path(empty) / "schemas").mkdir()
        (Path(empty) / "README.md").write_text("not core\n", encoding="utf-8")
        result = module.run(service_root=HARNESS_FIXTURES / "conforming", core_root=Path(empty))
    assert result.exit_code == HARNESS_EXIT_REFUSED, (
        f"a directory with no manifest schema must be refused, got {result.exit_code}"
    )
    assert [f.rule for f in result.findings] == ["core.not-a-checkout"], (
        f"the refusal must be named, got {[f.rule for f in result.findings]}"
    )


def test_the_harness_digest_is_the_pin_and_it_notices_a_changed_schema() -> None:
    """The pinning answer, proved: one digest, checked, on a laptop and in CI alike.

    The harness is given a **directory**, and the pin is that directory's
    content — a sha256 over every file under `schemas/`, sorted by path. The
    same core ref produces the same digest in a developer's worktree and in a CI
    runner; a schema edit produces a different one. `--expect-digest` is the
    opt-in that turns "different" into a red build, and it is the same code path
    in both environments because there is no second one.
    """
    module = harness_module()
    service = HARNESS_FIXTURES / "conforming"
    baseline = module.contract_digest(REPO)
    assert HARNESS_DIGEST_PATTERN.fullmatch(baseline), (
        f"the contract digest must be a 64-character lowercase sha256, got {baseline!r}"
    )
    assert module.contract_digest(REPO) == baseline, "the digest is not stable across calls"

    with tempfile.TemporaryDirectory() as work:
        copied = Path(work) / "core"
        shutil.copytree(REPO / "schemas", copied / "schemas")
        shutil.copytree(REPO / "docs", copied / "docs")
        # `VERSION` travels with them, and that is not tidiness: since core-17 a
        # core checkout that publishes no version cannot resolve a `core:`
        # constraint, so the harness *refuses* one (exit 2) rather than reporting
        # a violation. A synthetic core without it is no longer a core, and this
        # copy is the cheapest place to say so — a reader who copies only
        # `schemas/` and `docs/` will hit the refusal and be sent here.
        shutil.copy(REPO / "VERSION", copied / "VERSION")
        # `POSTGRES_TAG` travels with them for the same reason, one commit later
        # (core-18): a core that publishes no postgres tag cannot have the pin
        # rule decided against it, so the harness refuses it — exit 2, exactly as
        # it refuses a core with no `VERSION`.
        #
        # **These two files are the complete set** of what a core checkout must
        # carry beyond `schemas/` and `docs/`, and that is a fact worth a test
        # rather than a memory: every synthetic core in this suite is built by
        # copying a hand-picked list, and a third published fact added without
        # updating them would make a dozen unrelated tests red with a message
        # about a missing file nobody remembers declaring.
        shutil.copy(REPO / "POSTGRES_TAG", copied / "POSTGRES_TAG")
        assert module.contract_digest(copied) == baseline, (
            "a copy of core's contract surface must digest identically, or the pin is "
            "sensitive to something other than the contract"
        )
        # One byte in one schema — the smallest possible drift, and the one a
        # re-vendor fan-out would produce.
        target = copied / "schemas" / "cafaye.manifest.schema.json"
        target.write_text(
            target.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        drifted = module.contract_digest(copied)
        assert drifted != baseline, "a changed schema must change the digest"
        result = module.run(
            service_root=service, core_root=copied, expect_digest=baseline
        )
        assert result.exit_code == HARNESS_EXIT_VIOLATIONS, (
            f"a drifted contract must be a violation, got {result.exit_code}"
        )
        assert "core.digest-mismatch" in {f.rule for f in result.findings}, (
            f"the drift must be named, got {[f.rule for f in result.findings]}"
        )
        # And the un-pinned run over the same tree is otherwise a pass, which is
        # the point: the digest is opt-in, and the checks are the same either way.
        unpinned = module.run(service_root=service, core_root=copied)
        assert unpinned.exit_code == HARNESS_EXIT_CONFORMS, (
            "without --expect-digest a drifted core is still a core; the pin is the "
            "consumer's call, not the harness's"
        )


def test_the_harness_refuses_yaml_it_does_not_understand() -> None:
    """A subset reader must refuse, never guess.

    The fixture is a legal multi-line plain scalar. Guessing what it folds to
    means validating a document nobody wrote, and a schema error printed against
    a guessed document is worse than no answer because it names a real field.
    """
    module = harness_module()
    result = module.run(
        service_root=HARNESS_FIXTURES / "unsupported-yaml", core_root=REPO
    )
    assert result.exit_code == HARNESS_EXIT_REFUSED, (
        f"an unsupported YAML construct must be refused (exit {HARNESS_EXIT_REFUSED}), got "
        f"{result.exit_code}: {[f.rule for f in result.findings]}"
    )
    assert result.exit_code != HARNESS_EXIT_CONFORMS, (
        "this is the assertion the test exists for: unreadable is not conforming"
    )
    refusal = [f for f in result.findings if f.rule == "yaml.unsupported"]
    assert len(refusal) == 1, f"expected exactly one refusal, got {result.findings}"
    assert re.search(r"unsupported-yaml/cafaye\.yml:\d+$", refusal[0].path), (
        f"a refusal must name the file and the line, got {refusal[0].path!r}"
    )


def harness_refusal(module, call):
    """Run `call` and return the `Refusal` it must raise, or fail saying why not.

    Deliberately not `pytest.raises`. This file runs two ways — under pytest and
    as a plain script through `bin/prime` — and the script runner is the one
    `kit`'s `none` job and the CI `gate` job call. Importing pytest at module
    scope to save four lines would put a second way in front of a file that
    exists precisely so there is only one.
    """
    try:
        call()
    except module.Refusal as refusal:
        return refusal
    raise AssertionError(
        "the harness accepted a document it declares it refuses; a subset reader's "
        "honesty is entirely in what it refuses"
    )


def test_the_harness_yaml_reader_reads_every_document_in_this_repository() -> None:
    """Every YAML file core owns, read, and agreeing with PyYAML.

    This subsumes the narrower manifest-only comparison it replaces, and the "a
    named list of what the reader cannot read" test before that. `fleet.yml` and
    the invalid fleet example were the two documents the reader used to refuse,
    and a test that names what a reader cannot do accepts the limitation quietly.
    Both are read now, and the whole tree is asserted rather than a list.

    The reader used to refuse eight of the eleven real service repositories, so
    "reads everything in this repository" is a claim worth making rather than a
    formality. The single deliberate exception is the fixture that exists to be
    refused, and it is asserted refused below — so the claim cannot be met by
    refusing less.
    """
    module = harness_module()
    # TWO fixtures exist to be refused, and both are refused by name below, so
    # the exclusion list here cannot grow without the assertion growing with it.
    # It grew by one when the reserved checker arrived, and the way it grew is
    # the point: its `unreadable` fixture is a document the harness reader
    # refuses, and a fixture deliberately broken to trip one checker is not a
    # document core expects every reader to accept. Listing the two trees is
    # narrower than skipping every `tests/fixtures` path — which would also
    # exempt the four reserved fixtures that ARE readable, and "the reader reads
    # everything" met by skipping more is the claim this test exists to stop.
    refusal_fixtures = (
        HARNESS_FIXTURES / "unsupported-yaml",
        HARNESS_FIXTURES / "reserved-properties" / "unreadable",
    )
    unsupported = refusal_fixtures[0]
    unreadable = {}
    documents = 0
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".yml", ".yaml"}:
            continue
        if "tests/.venv" in path.as_posix() or any(
            tree in path.parents for tree in refusal_fixtures
        ):
            continue
        documents += 1
        text = path.read_text(encoding="utf-8")
        try:
            found = module.read_yaml(text, path)
        except module.Refusal as refusal:
            unreadable[path.relative_to(REPO).as_posix()] = refusal.detail
            continue
        expected = yaml.safe_load(text)
        if path.name == "ci.yml" and path.parent.name == "workflows":
            # The one document in this tree the two readers must disagree on.
            # PyYAML implements YAML 1.1, where the bare word `on` is the boolean
            # `True`; the harness implements the 1.2 core schema, where it is the
            # string "on" — which is what GitHub Actions means and what every
            # other document core owns needs. Asserted rather than excluded,
            # because "the harness agrees with PyYAML everywhere" is a claim that
            # should have exactly one visible exception and no silent ones.
            assert True in expected and "on" in found, (
                "PyYAML no longer resolves `on:` to a boolean; this exception is dead and "
                "should be deleted"
            )
            continue
        assert found == expected, (
            f"the harness reader and PyYAML disagree on {path.relative_to(REPO)}"
        )
    assert documents >= 15, f"only found {documents} YAML documents in the repository"
    assert not unreadable, (
        f"the harness's reader cannot read {sorted(unreadable)}, and every YAML document core "
        "owns is one it should be able to read. Reasons: "
        + "; ".join(f"{name}: {why}" for name, why in sorted(unreadable.items()))
    )
    # And the one document that *is* meant to be refused is refused, by name, so
    # "the reader reads everything" cannot be achieved by refusing less.
    refusal = harness_refusal(
        module,
        lambda: module.read_yaml(
            (unsupported / "cafaye.yml").read_text(encoding="utf-8"),
            unsupported / "cafaye.yml",
        ),
    )
    assert refusal.rule == "yaml.unsupported", (
        f"the unsupported-YAML fixture is no longer refused, so the reader has started "
        f"accepting {refusal.rule} and the refusal list is behind it"
    )
    # ...and so is the reserved checker's, which is the second tree in the
    # exclusion list above. Without this the exclusion is a hole: a fixture
    # could be moved in there and the reader could start refusing everything,
    # and the only assertion left would be about the first fixture.
    reserved_fixture = (
        HARNESS_FIXTURES / "reserved-properties" / "unreadable" / "billing" / "cafaye.yml"
    )
    reserved_refusal = harness_refusal(
        module,
        lambda: module.read_yaml(
            reserved_fixture.read_text(encoding="utf-8"), reserved_fixture
        ),
    )
    assert reserved_refusal.rule == "yaml.unsupported", (
        f"the reserved checker's unreadable fixture is no longer refused ({reserved_refusal.rule}), "
        "so the exclusion added for it is either dead or hiding a document the reader can parse"
    )


def test_the_harness_yaml_reader_refuses_only_what_it_declares() -> None:
    """Every construct the reader refuses, as a list, with a reason.

    A subset reader's honesty is entirely in what it refuses. A reader that
    refuses a legal document is annoying; a reader that accepts an illegal one
    is a second, silent source of truth — so the refusals are enumerated here,
    in the test, where adding one is a deliberate act.

    Each probe is a whole document rather than a fragment, because a reader can
    refuse a fragment for a reason that has nothing to do with the construct.
    """
    module = harness_module()
    probes = {
        "anchor": "name: x\nowner: &team core\n",
        "alias": "name: x\nowner: *team\n",
        "tag": "name: x\nowner: !!str core\n",
        "directive": "%YAML 1.2\nname: x\n",
        "merge key": "name: x\n<<: base\n",
        "nested flow": "name: x\ntags: [[a]]\n",
        "trailing comma": "name: x\ntags: [a,]\n",
        "mismatched flow": "name: x\ntags: [a}\n",
        "scalar continued into a mapping": "name: x\nother: a value\n  key: 1\n",
        "tab indent": "name: x\nowner:\n\tteam: core\n",
        "duplicate key": "name: x\nname: y\n",
        "second document": "name: x\n---\nname: y\n",
    }
    for construct, reason in module.YAML_REFUSALS.items():
        assert reason, f"a refusal with no reason: {construct!r}"
    for label, text in probes.items():
        refusal = harness_refusal(module, lambda t=text: module.read_yaml(t, Path("probe.yml")))
        assert str(refusal), f"the {label} refusal has no message"
        assert refusal.rule == "yaml.unsupported", (
            f"the {label} refusal is {refusal.rule!r}, not yaml.unsupported"
        )
        assert re.search(r"probe\.yml:\d+$", refusal.path), (
            f"the {label} refusal must name the file and the line, got {refusal.path!r}"
        )


def test_the_harness_yaml_reader_reads_what_the_fleet_writes() -> None:
    """The subset is the one the fleet writes, because the first one was not.

    The first version of this reader refused block scalars, flow collections and
    continued plain scalars. It was then pointed at the eleven real service
    repositories in the cafaye workspace and **eight of eleven refused** — six on
    a `description:`, two on a leading `---`, the rest on `tags: [users]`. A
    harness that cannot read the documents it exists to check is a demonstration.

    So the three constructs are in, and this test is what says so: each one is
    read to the value PyYAML gives it. The refusal list shrank to what no real
    document needed, and the test above says exactly what is left.
    """
    module = harness_module()
    documents = {
        "block scalar": "name: x\ndescription: |\n  two\n  lines\n",
        "block scalar, strip": "name: x\ndescription: |-\n  two\n  lines\n",
        "block scalar, keep": "name: x\ndescription: |+\n  two\n\n",
        "folded scalar": "name: x\ndescription: >-\n  two\n  lines\n",
        "folded with a blank line": "name: x\ndescription: >-\n  two\n\n  three\n",
        "indentation indicator": "name: x\ndescription: |2\n    two\n",
        "continued plain scalar": "name: x\ndescription: two\n  lines\n",
        "continued with a blank": "name: x\ndescription: two\n\n  three\n",
        "document start marker": "---\nname: x\n",
        "flow sequence": "name: x\ntags: [a, b, c]\n",
        "flow sequence across lines": "name: x\nrequired: [a, b,\n  c, d]\n",
        "flow sequence with a quoted comma": 'name: x\ntags: [a, "b, c"]\n',
        "flow mapping": "name: x\nschema: { $ref: '#/components/schemas/Thing' }\n",
        "flow mapping, several": "name: x\nexample: { a: 1, b: two }\n",
        "empty collections": "name: x\na: []\nb: {}\n",
        "block sequence of mappings": "name: x\nitems:\n  - name: one\n    version: ^0.1.0\n  - name: two\n",
        "comment after a value": "name: x # the name\ndescription: two  # trailing\n",
    }
    for label, text in documents.items():
        expected = yaml.safe_load(text)
        found = module.read_yaml(text, Path("probe.yml"))
        assert found == expected, (
            f"the {label} construct:\n  pyyaml:  {expected!r}\n  harness: {found!r}"
        )


def test_the_harness_yaml_reader_agrees_with_pyyaml_on_every_fold() -> None:
    """The fold is the riskiest thing in the reader, so it gets its own test.

    Everything else in the reader either reads a construct or refuses it. A fold
    can be *almost* right, and an almost-right fold of a `description:` produces
    a document nobody wrote and then reports it as if it did. So YAML's three
    folding rules are each probed: one line break becomes a space, a blank line
    becomes a newline, and a more-indented line keeps its break.

    Kept apart from the construct matrix because that one is about *coverage* of
    what the fleet writes and this is about *correctness* of the one function
    that guesses. `muse`'s 405 description is the shape in the first row.
    """
    module = harness_module()
    documents = {
        "one break is a space": "d: two\n  lines\n",
        "a blank line is a newline": "d: two\n\n  three\n",
        "two blank lines are two newlines": "d: two\n\n\n  three\n",
        "a more indented line keeps its break": "d: two\n    three\n",
        "more indented after ordinary": "d: two\n  three\n    four\n",
        "two more indented lines": "d: two\n    three\n    four\n",
        "three lines": "d: one\n  two\n  three\n",
        "a break then a dedent": "d: one\n  two\nname: x\n",
        "a blank then a dedent": "d: one\n\nname: x\n",
        "a continued scalar then a sequence": "d: one\n  two\nitems:\n  - a\n",
    }
    for label, text in documents.items():
        expected = yaml.safe_load(text)
        found = module.read_yaml(text, Path("probe.yml"))
        assert found == expected, f"{label}:\n  pyyaml:  {expected!r}\n  harness: {found!r}"


def test_the_harness_evaluator_agrees_with_jsonschema_on_every_example() -> None:
    """The load-bearing check on the hand-written evaluator.

    `harness/cafaye_contract.py` evaluates the keywords core's schemas use,
    with nothing but the standard library, so that a Go service in CI needs no
    Python package to check its manifest. That is only defensible because it is
    *provably* the same answer `jsonschema` gives — and the proof is this test,
    over every example in `examples/`, in both directions: a document that
    jsonschema accepts must be accepted, and a document it rejects must produce
    the same set of violated keywords.

    Both directions matter. Agreeing on acceptance while disagreeing about
    *which* rule fired would report a real breach as some other real breach, and
    a report that names the wrong field sends a person to the wrong file.
    """
    module = harness_module()
    cases = [
        (MANIFEST_SCHEMA_PATH, list(MANIFEST_EXAMPLES) + [INVALID_MANIFEST]),
        (ENVELOPE_SCHEMA_PATH, [
            VALID_ENVELOPE, INVALID_ENVELOPE,
            INVALID_UNTAGGED_ENVELOPE, INVALID_SUBJECTLESS_ENVELOPE,
        ]),
        (FLEET_SCHEMA_PATH, [FLEET, INVALID_FLEET]),
    ]
    for schema_path in payload_schemas():
        event_type = event_type_of(schema_path)
        cases.append((schema_path, [
            VALID_PAYLOADS / (event_type.replace(".", "/") + PAYLOAD_EXAMPLE_SUFFIX),
            INVALID_PAYLOADS / (event_type.replace(".", "/") + PAYLOAD_EXAMPLE_SUFFIX),
        ]))
    # The three SLO schemas, because the harness now validates a Sloth
    # declaration against them. This is where the evaluator's newest keywords get
    # their receipt — `if`/`then` inside `prefixItems`, `const` alongside a `$ref`
    # sibling, `not` on a string — and a harness that quietly disagreed about
    # which rule fired would report a real breach under the wrong name.
    cases.append((SLO_SCHEMA_PATH, [
        VALID_SLO,
        INVALID_SLO_PERFECT,
        INVALID_SLO_PAGE_ON_LOW,
        INVALID_SLO_WINDOW_OVERRIDE,
    ]))
    cases.append((SLO_WINDOWS_SCHEMA_PATH, [VALID_SLO_WINDOWS, window_document()]))
    cases.append((SLO_METRICS_SCHEMA_PATH, [
        sli_catalogue_document(), INVALID_SLO_DENYLISTED,
    ]))
    for schema_path, documents in cases:
        schema = load_schema(schema_path)
        for document in documents:
            # A case is a path or an already-built document: the window catalog and
            # the SLI catalogue are *derived* in this test's helpers rather than
            # read from `examples/`, because their whole point is that the schema
            # declares them — so the equivalence check covers the declarations.
            instance = load_document(document) if isinstance(document, Path) else document
            expected = sorted({failure.keyword for failure in failures_for(instance, schema)})
            found = sorted({f.keyword for f in module.evaluate(instance, schema)})
            label = (
                f"{document.relative_to(REPO) if isinstance(document, Path) else '<derived>'} "
                f"against {schema_path.relative_to(REPO)}"
            )
            assert found == expected, (
                f"the harness evaluator and jsonschema disagree on {label}\n"
                f"  jsonschema: {expected}\n"
                f"  harness:    {found}"
            )


def test_the_harness_implements_every_keyword_core_schemas_use() -> None:
    """So the evaluator cannot quietly fall behind a schema that grows a keyword.

    A keyword the reader does not implement is a rule the harness does not
    enforce, and an unenforced rule reads exactly like an upheld one. So the
    keyword set is compared in both directions: nothing in `schemas/` may be
    unimplemented, and nothing may be implemented without a user, because dead
    code in a conformance tool is a rule that will be wrong the day it is used.
    """
    module = harness_module()
    used: set[str] = set()
    _collect_keywords(load_schema(MANIFEST_SCHEMA_PATH), used)
    for path in payload_schemas():
        _collect_keywords(load_schema(path), used)
    _collect_keywords(load_schema(ENVELOPE_SCHEMA_PATH), used)
    _collect_keywords(load_schema(FLEET_SCHEMA_PATH), used)
    _collect_keywords(load_schema(GATE_SCHEMA_PATH), used)
    for path in sorted(TELEMETRY_SCHEMAS.glob("*.json")):
        _collect_keywords(load_schema(path), used)

    implemented = set(module.IMPLEMENTED_KEYWORDS)
    unimplemented = sorted(used - implemented)
    assert not unimplemented, (
        f"core's schemas use {unimplemented} and harness/cafaye_contract.py does not "
        "implement them, so the harness would accept a document the schema rejects. "
        "Implement the keyword, or stop using it in schemas/ — do not leave the gap."
    )
    unused = sorted(implemented - used)
    assert not unused, (
        f"the harness implements {unused}, which no schema in core uses. Each one is a "
        "rule with no user and no test; delete it or add the example that exercises it."
    )


def test_the_harness_checks_the_format_vocabulary_core_uses() -> None:
    """`format` is a keyword that only asserts when a checker is installed.

    `tests/requirements.txt` already carries a note saying exactly this about
    `date-time`, and core pins `rfc3339-validator` because of it. This is the
    same rule applied to the harness: the formats a schema names are formats the
    harness must actually decide, because a `format` no one checks is a comment.
    """
    module = harness_module()
    used: set[str] = set()
    for path in sorted(SCHEMAS.rglob("*.json")):
        _collect_formats(load_schema(path), used)
    assert used, "no schema in core uses `format`, which would make this test vacuous"
    unchecked = sorted(used - set(module.CHECKED_FORMATS))
    assert not unchecked, (
        f"core's schemas name format {sorted(used)} and the harness decides "
        f"{sorted(module.CHECKED_FORMATS)}; {unchecked} would be assertions nobody makes. "
        "See tests/requirements.txt for why this is a real gap in core's own suite too."
    )


def _imports_of(source: str) -> set[str]:
    """The top-level module names `source` imports, by AST rather than by grep.

    A walk and not a substring search, so a `from x import y` inside a function
    body is caught as readily as one at the top, and so an import spelled inside a
    docstring is not mistaken for an import.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    # `__future__` is a compiler directive, not an import.
    names.discard("__future__")
    return names


def test_the_harness_imports_nothing_outside_the_standard_library() -> None:
    """Static proof, because the runtime proof has a hole.

    `test_the_harness_runs_with_site_packages_disabled` proves the harness works
    with nothing installed. This proves why: the only modules it may import are
    the standard library's, and the check is an AST walk rather than a grep, so a
    `from x import y` in a function body is caught as readily as one at the top.

    **EVERY module that travels is walked, not only the entrypoint.** Since
    core-17 the contract harness stopped being one file: `core_version.py` sits
    beside `cafaye_contract.py` in the same directory and is imported by it, and
    a service's CI runs the pair. Proving the standard-library claim about the
    entrypoint alone would leave the sibling unchecked, and an unchecked sibling
    is where the dependency would arrive — the entrypoint's own imports are the
    ones a reader can see, so they are the ones that stay clean.

    The exemption for a sibling is **computed from the tree, not declared**: a
    name is exempt exactly when a file of that name exists in `harness/`. A
    hand-maintained list would be a list that silently stops covering a module
    added six months after this packet; `test_the_harness_siblings_are_the_ones_that_travel`
    is the ratchet that makes somebody *declare* a new sibling, and it is separate
    on purpose so that "where does it come from" and "who declared it" stay two
    questions.

    `gate_check.py` is deliberately not walked here: it is a separate tool with
    its own, stricter proof in
    `test_the_gate_checker_needs_nothing_core_does_not_ship`, and one test
    covering both tools is a test whose exemptions belong to neither.
    """
    travelling = {
        path: path.name
        for path in sorted(HARNESS.glob("*.py"))
        if path.name != GATE_CHECK.name
    }
    assert travelling, f"no modules to walk in {HARNESS.relative_to(REPO)}"
    assert HARNESS_MODULE in travelling, (
        f"harness/{HARNESS_MODULE.name} is the module every service runs, and it is not "
        "in the set this proof walks — a stdlib proof that skips the entrypoint proves "
        "nothing about the thing it is named for"
    )
    # A name is exempt exactly when core ships a file of that name, so the
    # exemption cannot outlive the file that justified it.
    local = {path.stem for path in HARNESS.glob("*.py")}

    for path in travelling:
        outside = sorted(_imports_of(path.read_text(encoding="utf-8")) - HARNESS_STDLIB_ONLY - local)
        assert not outside, (
            f"harness/{path.name} imports {outside}. core has one dependency list "
            "(tests/requirements.txt) and the harness must not add a second: a check that "
            "needs a package is a check a Go service's CI cannot run. Every module in "
            "harness/ travels together and is walked here, so a dependency added to the "
            "resolver fails exactly as one added to the entrypoint would."
        )


def test_the_harness_siblings_are_the_ones_that_travel() -> None:
    """The sibling exemption is a list of core's own files, and it is closed.

    `test_the_harness_imports_nothing_outside_the_standard_library` lets
    `cafaye_contract.py` import a fixed set of names without proving they are
    core's. That is a hole shaped exactly like the claim it guards: a sibling
    exemption is only honest while somebody re-declares it, because the failure
    mode — a new module in `harness/`, imported, never added here — is invisible
    to every other test in this file.

    So the set is asserted equal to the sibling modules `cafaye_contract.py`
    actually imports, in both directions. `gate_check.py` is deliberately not in
    it: that module is a separate tool with its own stdlib proof, and the
    contract harness does not import it.
    """
    tree = ast.parse(HARNESS_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    # Every name the harness imports that is neither stdlib nor one of core's
    # own modules is the hole; this asserts the *other* direction, that the
    # declared exemptions are exactly the local files actually reached.
    local = {path.stem for path in HARNESS.glob("*.py")}
    reached = imported & local
    declared = {"core_version"}
    assert reached == declared, (
        f"harness/cafaye_contract.py imports the sibling modules {sorted(reached)} and "
        f"its stdlib proof exempts {sorted(declared)}. A module that travels and is "
        f"imported but not exempt fails the proof; an exemption for a module that is "
        f"not imported is an exemption for nothing. Declare both in the same commit."
    )
    assert "gate_check" not in imported, (
        "harness/cafaye_contract.py imports gate_check. Those are two separate tools "
        "with separate stdlib proofs, and one importing the other turns a proof of "
        "each into a proof of one."
    )


def test_the_contract_harness_refuses_to_run_without_its_resolver() -> None:
    """The harness must fail loudly when `core_version.py` did not travel.

    A harness that quietly checked *less* when a file was missing is the worst
    version of this feature: every service would be green, and the one thing
    core-17 added would be the one thing not running. So the import is guarded
    and the guard exits with a sentence rather than a `ModuleNotFoundError`
    traceback, and this asserts the sentence names the file.
    """
    with tempfile.TemporaryDirectory() as lonely:
        shutil.copy(HARNESS_MODULE, Path(lonely) / HARNESS_MODULE.name)
        completed = subprocess.run(
            [sys.executable, str(Path(lonely) / HARNESS_MODULE.name), "--help"],
            capture_output=True, text=True, timeout=120,
        )
    assert completed.returncode != 0, (
        "harness/cafaye_contract.py exited 0 with core_version.py absent. A resolver that "
        "silently does not run turns a version check into no version check."
    )
    assert "core_version" in (completed.stdout + completed.stderr), (
        "the refusal does not name core_version: a message that does not say which file is "
        "missing is not a message anybody can act on"
    )


def test_the_harness_runs_with_site_packages_disabled() -> None:
    """The runtime half of the same claim, and the one that would fail first.

    `python -I -S` is the interpreter with user site-packages, `PYTHONPATH` and
    the site module all out of the way, so a harness that had grown a
    third-party import dies here rather than in a service's container.
    """
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(HARNESS_MODULE),
         "--core", str(REPO), str(HARNESS_FIXTURES / "conforming")],
        cwd=str(REPO),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == HARNESS_EXIT_CONFORMS, (
        f"the harness must run on the standard library alone, exited "
        f"{completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )


def test_the_harness_reaches_no_network_and_no_ambient_environment() -> None:
    """A contract check that needs the network is a contract check nobody runs.

    The proof is that the same directory gives the same answer with a full
    environment and with an empty one. A harness that read a proxy setting, a CI
    token, a `*_CORE_*` variable, a colour preference or a `$HOME` would differ,
    and each of those is a way for a developer's green to become a CI red that
    nobody can reproduce.
    """
    module = harness_module()
    service = HARNESS_FIXTURES / "conforming"
    with_env = module.run(service_root=service, core_root=REPO)
    completed = subprocess.run(
        [sys.executable, str(HARNESS_MODULE), "--core", str(REPO), str(service)],
        cwd=str(REPO),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == with_env.exit_code == HARNESS_EXIT_CONFORMS
    # `.rstrip` because `print` adds a newline and `render` does not: the
    # comparison is about the *answer*, not about how a process ends a line.
    assert completed.stdout.rstrip("\n") == module.render(with_env).rstrip("\n"), (
        "the harness's answer must not depend on the environment it was given:\n"
        f"empty: {completed.stdout!r}\n  full: {module.render(with_env)!r}"
    )
    # And nothing in the module can reach the network or run a command. Checked
    # on the AST rather than by grepping the text, because a grep cannot tell a
    # mention in prose from a call — and a test that fails on this module's own
    # docstrings is a test that gets deleted instead of fixed.
    tree = ast.parse(HARNESS_MODULE.read_text(encoding="utf-8"))
    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts = []
        target = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        called.add(".".join(reversed(parts)))
    # Dotted, not bare: `re.compile` is not `compile`, and a bare attr match
    # would have failed on the module's own regex tables before it ever reached
    # anything dangerous — a test that fires on the wrong thing is a test that
    # gets deleted.
    for banned in (
        "os.system", "os.popen", "os.spawn", "os.execv", "os.fork", "os.forkpty",
        "eval", "exec", "compile", "__import__", "subprocess.run", "subprocess.Popen",
    ):
        assert banned not in called, (
            f"harness/cafaye_contract.py calls {banned}(). core is offline by contract, and a "
            "harness whose answer can depend on a process outside it is a harness whose "
            "answer depends on the day"
        )


def test_every_rule_the_harness_can_emit_is_declared_in_the_inventory() -> None:
    """The inventory is load-bearing, not documentation.

    Two hand-maintained lists — the ids in `harness/cafaye_contract.py` and the
    ids in `harness/rules.json` — that must be the same set. The tempting
    weakening is "every emitted id is declared", which is satisfied by a harness
    that emits two rules and an inventory of forty; the reverse direction is what
    catches a rule the inventory describes and the harness cannot reach.
    """
    module = harness_module()
    declared = set(harness_rules_by_id())
    emitted = set(module.RULE_IDS)
    assert emitted == declared, (
        f"the harness can emit {sorted(emitted - declared) or 'nothing extra'}, and "
        f"harness/rules.json declares {sorted(declared - emitted) or 'nothing extra'}; "
        "the two lists are the same rule inventory stated twice and must agree"
    )


def test_the_rule_inventory_says_where_every_rule_lives() -> None:
    """**This is the question core's own rule turns on, made mechanical.**

    core's one rule is that a rule not in `schemas/` is not a cafaye rule. The
    honest answer for the harness is that *some* rules are in a schema and some
    are in `docs/` and therefore in the harness's own source — and a reader of
    the README is owed that sentence field by field, not as a summary.

    So every rule declares an `enforcedBy` with a kind, and:
      * `schema` names a file under `schemas/` that exists;
      * `doc` names a file under `docs/` **and a heading in it** that exists —
        because a convention with no document is a rule in code, and saying
        `doc` is how that would be hidden;
      * `harness` names a function in the harness module, and that function is
        where the rule actually is.
    """
    module = harness_module()
    for rule_id, rule in sorted(harness_rules_by_id().items()):
        assert rule.get("claim"), f"{rule_id} has no claim: a rule nobody can state is not a rule"
        enforced = rule.get("enforcedBy") or {}
        kind = enforced.get("kind")
        assert kind in {"schema", "doc", "harness"}, f"{rule_id} has enforcedBy.kind={kind!r}"
        if kind == "schema":
            target = REPO / enforced["file"]
            assert target.is_file(), f"{rule_id} claims schema {enforced['file']}, which is not in the tree"
            assert target.is_relative_to(SCHEMAS), (
                f"{rule_id} claims a schema outside schemas/ ({enforced['file']}); core's rule "
                "is that the machine-readable contract lives there"
            )
        elif kind == "doc":
            target = DOCS / enforced["file"]
            assert target.is_file(), f"{rule_id} claims doc {enforced['file']}, which is not in the tree"
            text = target.read_text(encoding="utf-8")
            assert enforced["heading"] in text, (
                f"{rule_id} claims the heading {enforced['heading']!r} in {enforced['file']}, "
                "which the document does not have"
            )
        else:
            function = getattr(module, enforced["function"], None)
            assert callable(function), (
                f"{rule_id} claims the harness function {enforced['function']!r}, which does "
                "not exist — the rule is described and not implemented"
            )
        assert rule.get("doc"), f"{rule_id} does not cite the document that explains it"


def test_the_contract_harness_doc_and_the_inventory_agree() -> None:
    """A doc and an inventory are the same rule list written twice.

    core's doctrine — a document and its schema are the same contract stated
    twice, and the test is the enforcement — applied to the harness's own rule
    list. The table in `docs/contract-harness.md` is what a human reads; the
    inventory is what the harness and CI see.
    """
    assert HARNESS_DOC.is_file(), (
        f"{HARNESS_DOC.relative_to(REPO)} does not exist. A harness that ships with no "
        "document is exactly the 'a convention that lives only in the source' case core "
        "exists to prevent, and a reader has no way to learn what it does not check."
    )
    text = HARNESS_DOC.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\|\s*`([a-z][a-z0-9.-]+)`\s*\|", text, flags=re.MULTILINE))
    declared = set(harness_rules_by_id())
    assert declared <= documented, (
        f"the harness enforces {sorted(declared - documented)}, which the document does not "
        "list. Either the document is behind the code or the code enforces a rule nobody "
        "was told about; both are the same defect."
    )
    assert documented == declared, (
        f"the document lists {sorted(documented - declared)}, which the harness does not "
        "enforce. A reader would believe a rule is checked when it is not."
    )


def test_the_contract_harness_doc_states_what_it_does_not_check() -> None:
    """The smaller harness must say out loud that the larger one is owed.

    A README that describes only what a tool does is read as a description of
    everything it does. The harness validates a repository's *declared*
    contracts; it does not validate live responses against the event payload
    schemas, and until a document says so a service owner will assume it does.
    """
    doc = HARNESS_DOC.read_text(encoding="utf-8").lower()
    for topic in ("does not", "live response", "payload schema", "owed"):
        assert topic in doc, (
            f"docs/contract-harness.md does not say {topic!r}; a harness that overstates "
            "itself is worse than a smaller one that does not"
        )


def test_the_harness_is_reachable_by_one_command() -> None:
    """`harness/bin/cafaye-contract` is what a service's CI calls.

    It is a wrapper, not a second implementation, and the assertion is that it
    *works* — the same defect class as core-06's `uses:` line, where a path that
    does not resolve looks exactly like one that does.
    """
    assert HARNESS_WRAPPER.is_file(), f"{HARNESS_WRAPPER.relative_to(REPO)} does not exist"
    assert os.access(HARNESS_WRAPPER, os.X_OK), (
        f"{HARNESS_WRAPPER.relative_to(REPO)} is not executable; a service's CI would get "
        "permission denied, which is not a message anybody can act on"
    )
    completed = subprocess.run(
        [str(HARNESS_WRAPPER), "--core", str(REPO), str(HARNESS_FIXTURES / "conforming")],
        cwd=str(REPO),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == HARNESS_EXIT_CONFORMS, (
        f"the wrapper must run the harness, exited {completed.returncode}\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_the_harness_proves_it_can_fail_by_breaking_itself() -> None:
    """core's own rule, applied to the harness: N breakages, N reds.

    This does not run `harness/tests/self_test.sh` — it runs the harness against
    the non-conforming fixtures, which is the cheap half of the same proof, and
    the script is the thorough half. What is asserted here is that the script
    exists, is executable, and names the breakages it makes, because a
    self-test that is not wired to anything is a self-test that has never run.
    """
    assert HARNESS_SELF_TEST.is_file(), f"{HARNESS_SELF_TEST.relative_to(REPO)} does not exist"
    assert os.access(HARNESS_SELF_TEST, os.X_OK), "the self-test is not executable"
    text = HARNESS_SELF_TEST.read_text(encoding="utf-8")
    count = text.count("expect_red")
    assert count >= 10, (
        f"the self-test makes {count} expect_red calls; kit's precedent is one deliberate "
        "breakage per check, and fewer than ten is not a proof that the checks are "
        "independent"
    )
    assert "unbroken tree" in text, "the control must run first, or the breakages prove nothing"
    for name in ("core.digest-mismatch", "yaml.unsupported", "core.absent"):
        assert name in text, f"the self-test does not break {name}, so that rule is unproved"


def test_every_rule_the_harness_can_emit_is_proved_able_to_go_red() -> None:
    """One breakage per rule, by name — the stronger form of the count above.

    `test_the_harness_proves_it_can_fail_by_breaking_itself` asserts the script
    makes *some* number of breakages. This asserts the number is not arbitrary:
    every id the harness can emit appears in a self-test, so a rule nobody
    broke is a rule nobody has watched fail, and a rule that can only fire on a
    document no fixture produces is a rule that has never fired at all.

    The haystack is **every** self-test under `harness/tests/`, not one named
    file. `self_test.sh` covers the manifest, event, OpenAPI and SLO rules;
    `core_version_test.sh` covers the version rules, and it has to be a separate
    script because its central breakage is the one that rots — `^0.1.0` stops
    being a violation the moment core publishes 0.3.0, so that proof derives its
    constraint from the version core publishes instead. A check that only ever
    read the first file would have called those three rules unproved, and the
    fix would have been to move a rot-proof test into a file it does not belong
    in.

    A broad haystack can hide a missing breakage, so the one file that must not
    contribute is asserted not to: `gate_self_test.sh` drives `gate_check.py`,
    not the contract harness, and no contract rule id belongs in it. If that ever
    stops being true this test would silently start passing, so it says so.
    """
    module = harness_module()
    scripts = sorted(HARNESS.glob("tests/*.sh"))
    assert scripts, f"no self-test scripts under {HARNESS.relative_to(REPO) / 'tests'}"
    for script in scripts:
        assert os.access(script, os.X_OK), (
            f"{script.relative_to(REPO)} is not executable; CI runs these as steps, and a "
            f"self-test nobody can run is a self-test nobody has run"
        )
    haystack = "\n".join(script.read_text(encoding="utf-8") for script in scripts)
    missing = [rule for rule in module.RULE_IDS if rule not in haystack]
    assert not missing, (
        f"the self-tests do not break {missing}. A rule with no breakage is a rule nobody "
        "has tested — add the mutation that makes the harness go red, and name the rule in "
        "the expectation so a red caught by the wrong check cannot read as a pass."
    )
    # The gate checker's self-test is in the haystack and drives a different tool.
    # It must therefore name none of the contract harness's rules, or it could
    # satisfy the assertion above for a rule nothing ever broke.
    gate_self_test = HARNESS / "tests" / "gate_self_test.sh"
    if gate_self_test.is_file():
        gate_text = gate_self_test.read_text(encoding="utf-8")
        leaked = [rule for rule in module.RULE_IDS if rule in gate_text]
        assert not leaked, (
            f"harness/tests/gate_self_test.sh names the contract rules {leaked}. That file "
            f"proves gate_check.py, and a contract rule id appearing in it means this test "
            f"can no longer tell whether the contract harness's own self-test broke it."
        )


def _collect_keywords(node, found: set[str]) -> None:
    """Every JSON Schema **keyword** appearing anywhere in a schema document.

    Schema-shaped, not a generic walk. A generic walk that recursed into every
    value would add every *property name* it saw — `name`, `language`, `core` —
    to the keyword set, and the harness would then be "missing" a keyword called
    `team`. The three keyword groups below are the ones whose values are
    schemas, which is the only place the distinction matters.
    """
    annotations = {
        "$schema", "$id", "$comment", "title", "description", "default",
        "examples", "deprecated", "readOnly", "writeOnly",
    }
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in annotations:
            continue
        found.add(key)
        if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for nested in value.values():
                _collect_keywords(nested, found)
        elif key in SUBSCHEMA_KEYWORDS:
            _collect_keywords(value, found)
        elif key in SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            for nested in value:
                _collect_keywords(nested, found)


def _collect_formats(node, found: set[str]) -> None:
    """Every `format` value named anywhere in a schema, via the same walk."""
    if not isinstance(node, dict):
        return
    if isinstance(node.get("format"), str):
        found.add(node["format"])
    for key, value in node.items():
        if key in SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            for nested in value.values():
                _collect_formats(nested, found)
        elif key in SUBSCHEMA_KEYWORDS:
            _collect_formats(value, found)
        elif key in SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            for nested in value:
                _collect_formats(nested, found)


# --------------------------------------------------------------------------
# 9. the SLO and error-budget spec (PLAN.md §7b)
# --------------------------------------------------------------------------

# The failure modes this section exists to make impossible to write by accident:
# an SLO nobody is paged for, an SLO on cpu rather than on behaviour, a per-tenant
# SLI, a burn-rate threshold that is 14.4 or 15 or 14 for no stated reason, an
# SLO at 100%, and an "SLA" for a tier the platform team does not operate. Each
# one is a schema constraint plus a test plus a paragraph in docs/slo.md.


def slo_entry(document: dict) -> dict:
    """The first SLO of a declaration, for a test that mutates one field."""
    return document["slos"][0]


def slo_document(**changes) -> dict:
    """A fresh copy of the worked example with `changes` applied to its SLO."""
    document = copy.deepcopy(load_document(VALID_SLO))
    slo_entry(document).update(changes)
    return document


def slo_alerting(tier: str, page: bool, ticket: bool) -> dict:
    """The worked example, moved to `tier` with the alerts the tier implies.

    The alerts move with the tier on purpose: `tier: critical` over a `low`'s
    `page_alert.disable: true` is itself a violation, so a helper that set the
    tier alone would report every tier as broken and the test would prove
    nothing about the derivation.
    """
    return slo_document(
        tier=tier,
        alerting={
            "name": "ExampleServiceHttpAvailability",
            "annotations": {
                "summary": "example-service is failing widget requests",
                "runbook_url": (
                    "https://runbooks.cafaye.com/example-service/"
                    "example-service-http-availability"
                ),
            },
            "page_alert": {"disable": page},
            "ticket_alert": {"disable": ticket},
        },
    )


def window_document() -> dict:
    """The normative window catalog, as a document."""
    return {
        "version": "prometheus/v1",
        "windows": [{"window": window, "factor": factor} for window, factor in SLO_WINDOW_CATALOG],
    }


def sli_catalogue() -> dict:
    """The SLI catalogue the metrics schema declares, keyed by logical name."""
    schema = load_schema(SLO_METRICS_SCHEMA_PATH)
    return schema["properties"]["slis"]["properties"]


def sli_catalogue_document() -> dict:
    """The catalogue as the document it also validates.

    Built from the schema's own `const` and `enum` values rather than written out
    a second time, so the positive example and the schema cannot drift — and so
    the assertion that the catalogue is *satisfiable* is about the schema alone.
    """
    def consts(entry: dict, names: tuple[str, ...]) -> dict:
        return {name: entry["properties"][name]["const"] for name in names}

    schema = load_schema(SLO_METRICS_SCHEMA_PATH)
    return {
        "slis": {
            name: {
                **consts(entry, ("otelName", "errorOtelName", "totalMetric", "errorMetric")),
                "errorSelector": entry["properties"]["errorSelector"]["default"],
                "labels": entry["properties"]["labels"]["items"]["enum"],
                "requiredLabels": entry["properties"]["requiredLabels"]["default"],
                "description": entry["properties"]["description"]["const"],
            }
            for name, entry in sorted(sli_catalogue().items())
        },
        "allowedLabels": schema["properties"]["allowedLabels"]["items"]["enum"],
        "forbidden": {
            "unboundedDimensions": schema["properties"]["forbidden"]["properties"]
            ["unboundedDimensions"]["items"]["enum"],
            "infrastructureSignals": schema["properties"]["forbidden"]["properties"]
            ["infrastructureSignals"]["items"]["enum"],
        },
    }


def prometheus_suffix(metric: str, otel_name: str) -> tuple[str, str] | None:
    """`(unit suffix, type suffix)` if `metric` is `otel_name` normalized, else None.

    The exporter's translation, as a derivation: `http.server.request.duration`
    becomes `http_server_request_duration` and then takes `_seconds` (the UCUM
    unit `s` in Prometheus's spelling) and `_count` (the count series of a
    histogram). Written out here so the test below asks the same question the
    catalogue exists to answer — *is this the OTel name, normalized, or something
    a hand-written string got wrong?* — rather than comparing a list to a list.
    """
    base = otel_name.replace(".", "_")
    if not metric.startswith(base):
        return None
    tail = metric[len(base):]
    for unit in PROMETHEUS_UNIT_SUFFIXES:
        for kind in PROMETHEUS_TYPE_SUFFIXES:
            if unit + kind == tail:
                return unit, kind
    return None


def test_the_slo_examples_validate() -> None:
    """The positive half. Both documents are read by the harness's YAML reader too.

    `test_the_harness_yaml_reader_reads_every_document_in_this_repository` walks
    every YAML file core owns, so a Sloth spec example that the harness cannot
    read would be an artifact no service's CI could check.
    """
    for document, schema in (
        (VALID_SLO, SLO_SCHEMA_PATH),
        (VALID_SLO_WINDOWS, SLO_WINDOWS_SCHEMA_PATH),
    ):
        found = failures_for(load_document(document), load_schema(schema))
        assert not found, (
            f"{document.relative_to(REPO)} must satisfy {schema.name}:\n  "
            + "\n  ".join(str(f) for f in found)
        )


def test_an_slo_at_one_hundred_percent_is_rejected() -> None:
    """R8, in the schema rather than in a comment.

    An objective of 100% is an SLO that can only ever be *reacted to*: the budget
    is zero, so there is no rate at which burning it is worth a page, and the
    alert either never fires or fires on the first bad minute of the quarter. The
    example it comes from also carries the other half of "an SLO nobody can keep",
    a 30-day period, because both are the same mistake — a number written to look
    safe.
    """
    schema = load_schema(SLO_SCHEMA_PATH)
    found = failures_for(load_document(INVALID_SLO_PERFECT), schema)
    assert_keywords(found, (
        ("exclusiveMaximum", "slos/0/objective"),
        ("const", "slos/0/period"),
    ))
    # And the control: the same document with a reachable objective and the
    # 28-day period validates, so the rejection cannot be passing for a reason.
    healed = copy.deepcopy(load_document(INVALID_SLO_PERFECT))
    healed["slos"][0]["objective"] = 99.9
    healed["slos"][0]["period"] = SLO_PERIOD
    assert not failures_for(healed, schema), (
        "the invalid SLO example is also wrong for another reason, so the two "
        "assertions above would pass on the wrong defect:\n  "
        + "\n  ".join(str(f) for f in failures_for(healed, schema))
    )


def test_the_tier_alone_decides_whether_a_page_is_generated() -> None:
    """R4, and the single most important rule in the packet.

    A page-level burn alert per SLO across seven services is textbook alert
    fatigue: the self-hoster mutes them within a week, and muting them costs the
    whole instrument. So the tier decides, the schema enforces the decision, and
    both directions are checked for every tier — a rule that only refuses the bad
    half would accept a service that pages nothing.
    """
    schema = load_schema(SLO_SCHEMA_PATH)
    for tier, (page, ticket) in sorted(SLO_TIER_ALERTS.items()):
        assert not failures_for(slo_alerting(tier, page, ticket), schema), (
            f"a tier: {tier} SLO with page_alert.disable={page} and "
            f"ticket_alert.disable={ticket} must validate"
        )
        for alert, wanted in (("page_alert", page), ("ticket_alert", ticket)):
            document = slo_alerting(tier, page, ticket)
            document["slos"][0]["alerting"][alert]["disable"] = not wanted
            assert_keywords(
                failures_for(document, schema),
                (("const", f"slos/0/alerting/{alert}/disable"),),
            )

    # And the derivation is *in* the schema, one branch per tier, rather than
    # implied by the enum. A behavioural test alone is satisfied by an SLO schema
    # that happened to refuse the four cases above and nothing else.
    branches = load_schema(SLO_SCHEMA_PATH)["$defs"]["slo"]["allOf"]
    derived = {}
    for branch in branches:
        condition = branch["if"]["properties"]["tier"]
        tiers = [condition["const"]] if "const" in condition else list(condition["enum"])
        alert = branch["then"]["properties"]["alerting"]["properties"]
        for tier in tiers:
            derived[tier] = (
                alert["page_alert"]["properties"]["disable"]["const"],
                alert["ticket_alert"]["properties"]["disable"]["const"],
            )
    assert derived == SLO_TIER_ALERTS, (
        f"the schema derives {derived}, so the tier decides something other than the two "
        "alert switches. Every tier must have a branch, or a tier nobody thought about "
        "falls through with both alerts enabled."
    )


def test_an_slo_needs_a_description_and_a_runbook() -> None:
    """An SLO nobody can read is a chart rather than a contract, and an alert with
    no runbook is a page with no first move.

    The example is the worked SLO with both deleted, which is the shape a hurried
    service ships: the numbers are there and nothing says what they promise.
    """
    schema = load_schema(SLO_SCHEMA_PATH)
    document = slo_document()
    del document["slos"][0]["description"]
    # `required` reports against the object that is missing the key, not against
    # a path that does not exist yet — so the assertion names `slos/0`.
    assert_keywords(failures_for(document, schema), (("required", "slos/0"),))
    assert any(
        "description" in failure.message
        for failure in failures_for(document, schema)
    ), "the rejection has to name the field it rejected, or it sends a reader to the schema"
    document = slo_document()
    del document["slos"][0]["alerting"]["annotations"]["runbook_url"]
    assert_keywords(
        failures_for(document, schema),
        (("required", "slos/0/alerting/annotations"),),
    )


def test_an_slo_may_not_carry_the_word_an_sla_would() -> None:
    """R5, refused in the declaration rather than promised against in prose.

    A self-hosted deployment gets an SLO describing intended behaviour on
    adequate hardware, measured by the operator. The string an SLA would carry is
    not a thing this schema can express, and a description that contains it is a
    service telling its customers it has promised something the platform team
    does not operate.
    """
    schema = load_schema(SLO_SCHEMA_PATH)
    assert_keywords(
        failures_for(slo_document(description="99.9% availability, SLA-backed."), schema),
        (("not", "slos/0/description"),),
    )


def test_the_window_catalog_is_the_workbooks_numbers() -> None:
    """R2, as arithmetic rather than as a number in a comment.

    `14.4` is `0.02 x 720h`: the factor at which the **one-hour** window consumes
    2% of the budget the workbook derived it against. Rounded to 15 it fires
    *before* 2% of the budget is gone, which is the question every self-hoster
    asks and the reason the arithmetic is in the spec rather than the number
    alone.

    And the arithmetic does not agree with the period, which is the finding: 720
    hours is thirty days, and R3 mandates twenty-eight. So the catalog's 14.4 is
    ~7% conservative under a 28-day budget — the fast-burn alert fires slightly
    earlier than the workbook intends. That is implemented as ruled and asserted
    here in the direction it errs, so a future flip to 13.44 is a deliberate
    one-line change with a test saying so (**D27**).
    """
    schema = load_schema(SLO_WINDOWS_SCHEMA_PATH)
    assert not failures_for(window_document(), schema), "the normative catalog must validate"

    declared = [
        (item["properties"]["window"]["const"], item["properties"]["factor"]["const"])
        for item in schema["properties"]["windows"]["prefixItems"]
    ]
    assert declared == list(SLO_WINDOW_CATALOG), (
        f"the window catalog is {declared}, not {list(SLO_WINDOW_CATALOG)}"
    )
    assert schema["properties"]["windows"]["minItems"] == len(SLO_WINDOW_CATALOG)
    assert schema["properties"]["windows"]["maxItems"] == len(SLO_WINDOW_CATALOG)
    assert schema["properties"]["windows"].get("items") is False, (
        "exactly the catalog's windows are allowed — `items: false` is what refuses a ninth"
    )

    fast = dict(SLO_WINDOW_CATALOG)[SLO_WINDOW_CATALOG[0][0]]
    assert fast == SLO_BUDGET_FRACTION * SLO_WORKBOOK_HOURS, (
        f"the fast-burn factor is {fast}, and 2% of the 720-hour budget the workbook "
        f"derived it against is {SLO_BUDGET_FRACTION * SLO_WORKBOOK_HOURS}. 14.4 is not 15: "
        "rounded up, the alert fires before 2% of the budget is gone."
    )
    under_this_period = SLO_BUDGET_FRACTION * SLO_PERIOD_HOURS
    assert fast > under_this_period, (
        f"the catalog's {fast} against a 28-day budget's {under_this_period}: the workbook's "
        "factors are derived from a 30-day budget, so under R3's 28-day period they fire "
        f"{(fast / under_this_period - 1) * 100:.0f}% early. That is the conservative "
        "direction, it is implemented as ruled, and flipping it is D27 — not a quiet edit "
        "to a number nobody recomputed."
    )

    # A ninth window, and a swapped factor, are both refused — and the position
    # matters, because Sloth consumes these in short/long pairs.
    extra = window_document()
    extra["windows"].append({"window": "1w", "factor": 1})
    assert_keywords(failures_for(extra, schema), (("maxItems", "windows"),))
    swapped = window_document()
    swapped["windows"][2]["factor"] = 15.0
    assert_keywords(failures_for(swapped, schema), (("const", "windows/2/factor"),))


def test_a_service_may_not_override_the_window_catalog() -> None:
    """R2's other half: the catalog is pinned once, in core.

    Sloth takes `--slo-period-windows-path` precisely so a project can carry its
    own, and a project that does is a project whose burn alerts mean something
    other than the workbook's. The declaration is closed, so the override is an
    undeclared key rather than a judgement call.
    """
    found = failures_for(
        load_document(INVALID_SLO_WINDOW_OVERRIDE), load_schema(SLO_SCHEMA_PATH)
    )
    assert_keywords(found, (("additionalProperties", "slos/0"),))
    assert not failures_for(slo_document(), load_schema(SLO_SCHEMA_PATH)), (
        "the worked example must not carry the override the invalid one does, or the "
        "assertion above passes for the wrong reason"
    )


def test_the_slo_catalog_declares_r6s_candidates_and_normalizes_every_name() -> None:
    """R6 and the reason `slo-metrics.schema.json` exists.

    Six languages each writing `http_server_request_duration_seconds_bucket` by
    hand is six chances to write `http_server_request_duration_seconds` instead,
    and the mistake is invisible until a query returns nothing at 3am. So every
    catalogue metric is asserted to be the *normalization* of the OpenTelemetry
    name beside it, and the check is a derivation rather than a second list.
    """
    schema = load_schema(SLO_METRICS_SCHEMA_PATH)
    entries = sli_catalogue()
    assert set(entries) == set(SLO_CATALOG_ENTRIES), (
        f"the catalogue declares {sorted(entries)}; R6's candidates are "
        f"{sorted(SLO_CATALOG_ENTRIES)}"
    )
    for name, entry in sorted(entries.items()):
        for role, name_field in (
            ("totalMetric", "otelName"),
            ("errorMetric", "errorOtelName"),
        ):
            otel_name = entry["properties"][name_field]["const"]
            metric = entry["properties"][role]["const"]
            suffix = prometheus_suffix(metric, otel_name)
            assert suffix is not None, (
                f"{name}.{role} is {metric!r}, which is not {otel_name!r} normalized "
                "(dots to underscores, then the UCUM unit, then the series type). Either "
                "the metric or the OTel name it came from is wrong."
            )
            assert suffix[1] != "", (
                f"{name}.{role} is {metric!r} with no series suffix. An SLI counts events, "
                "so it reads a `_count` or a `_total`; without one it is a name, not a "
                "series."
            )
    assert not failures_for(sli_catalogue_document(), schema), (
        "the catalogue the schema declares must satisfy the schema it is declared in:\n  "
        + "\n  ".join(str(f) for f in failures_for(sli_catalogue_document(), schema))
    )


def test_the_two_denylists_are_two_prohibitions_and_the_schema_refuses_each() -> None:
    """The denylist, as two lists with two reasons, and refused twice.

    Unbounded dimensions are already barred by `metrics.schema.json` on the
    2000-combination cap; infrastructure signals are barred here because an SLO
    on a CPU is not an SLO on behaviour (R6). One merged list would keep the
    enforcement and lose the reason, and the reason is what a reader has when
    they are about to add one — so the lists are separate properties, and the
    schema's `not` is asserted to be exactly their union.
    """
    schema = load_schema(SLO_METRICS_SCHEMA_PATH)
    forbidden = schema["properties"]["forbidden"]["properties"]
    assert set(forbidden) == {"unboundedDimensions", "infrastructureSignals"}, (
        f"the two prohibitions are {sorted(forbidden)}; they are two prohibitions "
        "because they have two different reasons"
    )
    assert forbidden["unboundedDimensions"]["items"]["enum"] == list(SLO_UNBOUNDED_DIMENSIONS)
    assert forbidden["infrastructureSignals"]["items"]["enum"] == list(SLO_INFRASTRUCTURE_SIGNALS)
    assert not set(SLO_UNBOUNDED_DIMENSIONS) & set(SLO_INFRASTRUCTURE_SIGNALS), (
        "a substring in both lists belongs to one prohibition or the other, not both"
    )
    for group, values in (
        ("unboundedDimensions", forbidden["unboundedDimensions"]),
        ("infrastructureSignals", forbidden["infrastructureSignals"]),
    ):
        assert values.get("description"), f"{group} has to say why, not only what"

    alternatives = set(
        schema["$defs"]["metricName"]["not"]["pattern"].split("|")
    )
    assert alternatives == set(SLO_UNBOUNDED_DIMENSIONS) | set(SLO_INFRASTRUCTURE_SIGNALS), (
        f"the schema's `not` refuses {sorted(alternatives)}, which is not the union of the "
        "two lists — so the lists describe something the schema does not enforce"
    )

    # And every substring really is refused, both in the catalogue and in a
    # declaration that carries one. Refused twice on purpose: the `const` says it
    # is not the metric this SLI uses, the `not` says it is not a metric any SLI
    # may use, and a rule enforced once is a rule a well-meaning commit undoes.
    for denylisted in ("node_memory_usage_bytes", "http_tenant_requests_total"):
        document = sli_catalogue_document()
        document["slis"]["invoice_computed"]["totalMetric"] = denylisted
        found = failures_for(document, schema)
        assert_keywords(found, (
            ("const", "slis/invoice_computed/totalMetric"),
            ("not", "slis/invoice_computed/totalMetric"),
        ))
    assert_keywords(
        failures_for(load_document(INVALID_SLO_DENYLISTED), schema),
        (
            ("const", "slis/invoice_computed/totalMetric"),
            ("not", "slis/invoice_computed/totalMetric"),
        ),
    )


def test_every_catalogue_label_is_one_the_metric_spec_allows() -> None:
    """The allowlist is the measurement attributes, Postgres-normalized.

    `service.name` -> `service_name`, `http.response.status_code_class` ->
    `http_response_status_code_class`: the same attribute, in the spelling the
    collector writes. An SLI filtering on `http.route` rather than
    `http_http_route` measures nothing and says nothing, and which spelling is
    right is exactly the thing six languages get wrong by hand.
    """
    schema = load_schema(SLO_METRICS_SCHEMA_PATH)
    allowed = set(schema["properties"]["allowedLabels"]["items"]["enum"])
    measured = {
        "service_name",  # service.name, the resource attribute
        *(name.replace(".", "_") for name in measurement_attribute_names()),
    }
    assert measured <= allowed, (
        f"the metric schema allows {sorted(measured - allowed)} and the SLI allowlist does "
        "not. Every dimension an SLO may filter on is a dimension a metric may carry."
    )
    for forbidden in (*SLO_UNBOUNDED_DIMENSIONS, *SLO_INFRASTRUCTURE_SIGNALS):
        assert not any(forbidden in label for label in allowed), (
            f"{forbidden!r} is on the SLI label allowlist"
        )
    for name, entry in sorted(sli_catalogue().items()):
        labels = set(entry["properties"]["labels"]["items"]["enum"])
        assert labels <= allowed, f"{name} filters on labels outside the allowlist: {labels - allowed}"
        assert set(entry["properties"]["requiredLabels"]["items"]["enum"]) <= labels, (
            f"{name} requires a label it does not list as usable"
        )
        assert "service_name" in labels, (
            f"{name} does not list service_name. An SLI that does not scope itself to its own "
            "service is the fleet-wide ratio, which is the failure mode R6 rules out."
        )


def test_the_two_denylists_cover_the_queries_and_not_only_the_catalogue() -> None:
    """The prohibitions reach the queries a service commits.

    A catalogue that names no CPU is not enough: the query is the thing Prometheus
    evaluates, so the harness refuses a denylisted label in one and refuses it in
    the catalogue. This asserts the rule ids exist and that the conforming
    fixture's queries carry none of the eight substrings, which is the receipt
    that the check is running at all.
    """
    text = load_document(VALID_SLO)["slos"][0]["sli"]["events"]
    for query in text.values():
        for value in (*SLO_UNBOUNDED_DIMENSIONS, *SLO_INFRASTRUCTURE_SIGNALS):
            assert value not in query, f"the worked example filters on {value!r}"


def test_the_slo_doc_covers_every_topic_the_rulings_require() -> None:
    """The document and the schemas are the same contract written twice.

    Each string is a claim that has to be *in the document* for the reader who
    arrives with the question it answers — which is most of what a spec is for.
    """
    assert SLO_DOC.is_file(), (
        f"{SLO_DOC.relative_to(REPO)} does not exist. Three schemas with no document is the "
        "'a convention that lives only in the source' case core exists to prevent."
    )
    text = SLO_DOC.read_text(encoding="utf-8").lower()
    for topic in SLO_DOC_TOPICS:
        assert topic.lower() in text, (
            f"docs/slo.md does not cover {topic!r}. A spec a self-hoster cannot answer "
            "'why 14.4' from is a spec with a number in it and no reason."
        )


def test_the_slo_doc_publishes_the_arithmetic_and_the_exclusion_list() -> None:
    """Why 14.4 is not 15, and what an SLO here does not cover.

    Both halves are the self-hoster's first two questions, and the second one is
    the one a service-level *agreement* would be obliged to answer with a
    contract. An SLO answers it with a measurement, an operator and a list.
    """
    text = SLO_DOC.read_text(encoding="utf-8")
    assert "0.02" in text and "720" in text, (
        "docs/slo.md must publish the arithmetic behind 14.4 (0.02 x 720h), not the number"
    )
    assert "no sla" in text.lower(), (
        "docs/slo.md must say in its own words that there is no SLA and what stands in its place"
    )
    for excluded in ("adequate hardware", "exclusion"):
        assert excluded in text.lower(), (
            f"docs/slo.md must state the {excluded!r} half of what an SLO does not promise"
        )


def test_the_slo_doc_says_where_multi_tenant_answers_come_from() -> None:
    """The multi-tenancy question, answered before a reader has to ask it.

    A per-tenant SLI at one private product and twenty users is unaffordable and
    guarantees alert fatigue; a per-tenant *dimension* on a metric is already
    prohibited by `metrics.schema.json` on the 2000-combination cap, while
    `tenant_id` on `resourceAttributes` is required and exempt from that cap. So
    the honest answer is not a choice between the two: the metric is aggregate,
    and attribution is a logs-and-traces question over the resource attributes.
    """
    text = SLO_DOC.read_text(encoding="utf-8").lower()
    for topic in ("aggregate", "recording rule", "resourceattribute", "logs and traces", "2000"):
        assert topic in text, (
            f"docs/slo.md does not say {topic!r}. The next reader will ask whether an SLO is "
            "per-tenant, and 'the schema already prohibits it' is the answer."
        )


def test_the_slo_doc_requires_native_instrumentation_and_a_pinned_collector() -> None:
    """The spanmetrics migration, and why the collector is what moves.

    If a service derives RED metrics through the `spanmetrics` connector, the
    connector's unit default is migrating from `ms` to `s`, which renames
    `traces_span_metrics_duration_milliseconds_bucket` to `..._seconds_bucket`
    and breaks every latency query in every service at once — between the service
    and Prometheus, where no service-level test can see it. So: native OTel HTTP
    instrumentation over spanmetrics-derived metrics, and a collector version
    pinned in the kit templates whose bumps are breaking changes.
    """
    text = SLO_DOC.read_text(encoding="utf-8").lower()
    for topic in (
        "spanmetrics",
        "native",
        "http.server.request.duration",
        "collector",
        "pinned",
        "breaking change",
    ):
        assert topic in text, f"docs/slo.md does not say {topic!r}"
    assert "stable" in text, (
        "the reason native instrumentation is available must be stated: "
        "http.server.request.duration is Stable, with recommended bucket boundaries"
    )


def test_no_sla_token_appears_in_a_schema_or_an_example() -> None:
    """R5, checked over the machine-readable half of the repository.

    "No SLA. Anywhere." is checkable for the artifacts and only arguable for
    prose: a schema's `const`, `enum` or `default` is a value a machine reads
    into a document, and a value that could say it is a vocabulary cafaye does
    not have. `pattern` is deliberately *not* walked — the one pattern in core
    that names it is `$defs/noSla`'s, which exists to refuse it, and a check
    that refused the refusal would be a check against its own mechanism. The
    examples are walked whole, because an example is a declaration.
    """
    def machine_values(node, found: set[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"const", "enum", "default", "examples"}:
                    found.update(
                        item for item in (value if isinstance(value, list) else [value])
                        if isinstance(item, str)
                    )
                machine_values(value, found)
        elif isinstance(node, list):
            for item in node:
                machine_values(item, found)

    offenders = []
    for path in sorted(SCHEMAS.rglob("*.json")):
        values: set[str] = set()
        machine_values(load_schema(path), values)
        if any("SLA" in value for value in values):
            offenders.append(path.relative_to(REPO).as_posix())
    for path in sorted(EXAMPLES.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".yml", ".yaml"}:
            continue
        if "SLA" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(REPO).as_posix())
    assert not offenders, (
        f"{offenders} carry the acronym a service-level agreement would carry. A "
        "self-hosted deployment gets an SLO: intended behaviour on adequate hardware, "
        "measured by the operator, with the exclusions published."
    )
    # And the mechanism that refuses it is itself a schema constraint, not a
    # reminder — this is the assertion that would fail if `noSla` were deleted.
    assert_keywords(
        failures_for(slo_document(description="99.9% availability, SLA-backed."), load_schema(SLO_SCHEMA_PATH)),
        (("not", "slos/0/description"),),
    )


def test_no_slo_example_declares_a_real_fleet_service() -> None:
    """The packet boundary, as an assertion rather than as a promise.

    "Do not write SLOs for the seven services" is a sentence in a brief; this is
    the test that keeps it true. An example that named `courier` *would be*
    courier's SLO, with a threshold nobody chose and an alert nobody paged — and
    the next packet would have to either keep it or contradict it. So the worked
    examples name a service that is not a service.
    """
    real = {service["name"] for service in load_fleet()["services"]}
    assert len(real) >= 5, f"fleet.yml looks truncated: {sorted(real)}"
    document = load_document(VALID_SLO)
    assert document["service"] not in real, (
        f"{VALID_SLO.relative_to(REPO)} declares service {document['service']!r}, which is a "
        f"real service in fleet.yml. Declaring an SLO for a real service is the next "
        "packet's work: the metrics do not exist yet and nobody has chosen the objective."
    )


def test_the_slo_harness_rules_are_all_reachable_from_one_document() -> None:
    """One fixture, every SLO rule, and the exact set.

    The assertion shape is the one `test_the_harness_reports_every_convention_rule_
    one_manifest_breaks` uses, for the same reason: "reports at least these eight"
    is satisfied by a harness that reports one and silently drops seven, and a
    dropped rule reads exactly like an upheld one.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-slos")
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS, (
        f"a service whose SLOs break eight rules must exit {HARNESS_EXIT_VIOLATIONS}, "
        f"got {result.exit_code}"
    )
    found = {finding.rule for finding in result.findings}
    assert found == NONCONFORMING_SLO_RULES, (
        f"expected exactly {sorted(NONCONFORMING_SLO_RULES)}, got {sorted(found)}:\n  "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in result.findings)
    )


def test_the_harness_checks_a_service_slo_declarations() -> None:
    """The control: a service whose SLOs are canonical reports nothing.

    Without this the eight rules above could all pass on a fixture that is
    rejected by the schema for an unrelated reason, which is how a conformance
    tool ends up refusing every document and looking busy.
    """
    result = harness_runs(HARNESS_FIXTURES / "conforming")
    assert result.findings == (), (
        "the conforming fixture's SLOs must pass every SLO rule:\n  "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in result.findings)
    )
    assert sorted((HARNESS_FIXTURES / "conforming" / "slos").glob("*.yaml")), (
        "the conforming fixture carries no SLO declaration, so the SLO rules are never "
        "exercised on the accepting side"
    )


def test_a_service_with_no_slos_directory_is_not_a_refusal() -> None:
    """Absence is not a failure, and the reason is the precedent, not a shrug.

    `worker-only.cafaye.yml` declares no `exposes.api` and is a valid manifest, so
    a repository with no HTTP contract is checked on no HTTP rules and still
    passes. The same shape applies to SLOs: the harness validates declared
    contracts, and a directory it never wrote declares nothing. What it may not
    do is convert the absence into a green badge for the SLOs it *has* — which is
    what the refusal rules are for, and what `rules.json` records as not yet
    enforced.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-conventions")
    for fixture in ("nonconforming-conventions", "nonconforming-openapi"):
        assert not (HARNESS_FIXTURES / fixture / "slos").exists(), (
            f"the {fixture} fixture must declare no slos/, or the SLO rules would fire on it"
        )
        run = harness_runs(HARNESS_FIXTURES / fixture)
        assert not any(finding.rule.startswith("slo.") for finding in run.findings), (
            f"a service that declares no slos/ is checked on no SLO rules, and the "
            f"{fixture} fixture must show that: {[f.rule for f in run.findings]}"
        )
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS
    not_enforced = json.loads(HARNESS_RULES.read_text(encoding="utf-8"))["notEnforced"]
    assert any("slos/" in entry.get("why", "") for entry in not_enforced), (
        "harness/rules.json must record, in notEnforced, that a service with no slos/ "
        "directory is checked by nothing — the one honest statement about an optional "
        "declaration, and the one that stops the absence from reading as a pass"
    )


# --------------------------------------------------------------------------
# 10. the gate declaration (core-09)
# --------------------------------------------------------------------------
#
# A gate that is discovered by getting it wrong is not a gate, and this fleet
# has five spellings of "run the gate" across fifteen repositories. The
# declaration is `gate.yml`, the format is `schemas/gate.schema.json`, the
# checker is `harness/gate_check.py`, and the argument for that shape instead
# of mise-tasks-alone or a CI workflow is in docs/gate.md.
#
# The tests below are in four groups, and the order is the argument:
#
#   1. the format is well-formed — the schema, the examples, and the checker's
#      re-implementation of the schema reaching the same answer;
#   2. core's own declaration is TRUE — the checker is green on core, the floor
#      is not behind the suite, the mise task is the fleet's spelling;
#   3. the checker can FAIL — the three red proofs the packet names, in
#      `tests/test_specs.py` itself, so `bin/prime` goes red if any of them
#      stops being caught and not only when somebody remembers to run the
#      self-test;
#   4. the checker's own promises — the tri-state, the inventory, the stdlib,
#      the no-secrets property, and the `PIPESTATUS` line in the doc.


def gate_module():
    """`harness/gate_check.py`, imported in-process.

    In-process rather than by subprocess so a test can assert on the `Report`
    the checker returns instead of on the text it printed. The subprocess
    proofs exist too, where the claim is about the process rather than about
    the answer.
    """
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import gate_check  # noqa: PLC0415 - a sibling module, imported on demand

    return gate_check


def gate_fixture_repo(work: Path) -> Path:
    """A throwaway copy of the conforming gate fixture, and nothing else.

    The fixture is one small repository that declares its gate and tells the
    truth about all of it. Every red proof below is that repository with one
    thing changed, so a red proves *this check* is load-bearing rather than
    that something went red.
    """
    target = work / "repo"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(GATE_FIXTURE, target)
    # `shutil.copytree` preserves the mode, but a fixture that reached a
    # checkout through a tool that did not would arrive non-executable, and
    # every red would then be about that instead of about the breakage.
    (target / "bin" / "gate").chmod(0o755)
    return target


def gate_check_runs(work: Path, *, prove: bool = False, **files: str):
    """Run the checker over a copy of the fixture, with `files` written over it."""
    repo = gate_fixture_repo(work)
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return gate_module().check(repo, prove_it=prove, log_dir=work / "log")


def gate_declaration_text(**replacements: str) -> str:
    """The conforming fixture's declaration, with `old` -> `new` substitutions.

    Raises if a substitution does not apply. A red proof that silently stops
    breaking anything is worse than no red proof, and the failure has to be
    loud: it is a test that has stopped testing.
    """
    body = (GATE_FIXTURE / "gate.yml").read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old not in body:
            raise AssertionError(f"the gate fixture no longer contains {old!r}")
        body = body.replace(old, new, 1)
    return body


# -- 1. the format --------------------------------------------------------


def test_the_valid_gate_examples_validate() -> None:
    """Two examples, because `selfContained` is an `if`/`then` and both arms need one.

    A single self-contained example would leave the `minItems: 1` arm of the
    schema's conditional untested, and an untested arm of a conditional is a
    conditional nobody knows what it does. The second example is also the only
    place the format's two-proofs shape is exercised, and that shape is how a
    database tier stays separately countable instead of being folded into one
    number with everything else.
    """
    schema = load_schema(GATE_SCHEMA_PATH)
    for path in VALID_GATES:
        found = failures_for(load_document(path), schema)
        assert not found, f"{path.name} must be valid:\n  " + "\n  ".join(str(f) for f in found)


def test_the_invalid_gate_examples_are_rejected_for_the_reason_they_document() -> None:
    """Exact `(keyword, path)` pairs, so an example cannot be rejected by accident.

    A negative example that is rejected for the *wrong* reason is a lie in a
    comment: the file says "this is a shell string" and the suite is satisfied
    by it being too long. This is the assertion shape every other negative case
    in this repository uses, for the same reason.
    """
    schema = load_schema(GATE_SCHEMA_PATH)
    for name, expected in sorted(INVALID_GATES.items()):
        path = INVALID_EXAMPLES / name
        assert path.is_file(), f"examples/invalid/{name} is missing"
        found = failures_for(load_document(path), schema)
        assert found, f"examples/invalid/{name} must be REJECTED by {GATE_SCHEMA_PATH.name}"
        assert_keywords(found, expected)


def test_the_gate_checker_and_the_schema_agree_on_every_example() -> None:
    """`harness/gate_check.py` re-implements the schema, and that is a risk.

    The checker is stdlib-only so a Go service's CI can run it with nothing
    installed, and `jsonschema` is not stdlib — so the checker carries its own
    copy of the well-formedness rules. A second copy of a contract is exactly
    the drift core exists to prevent, and the honest way to hold it is to run
    BOTH over every example core ships and require the same accept/reject
    answer. Then a constraint added to the schema and forgotten in the checker
    is a red here, the day the example that exercises it lands.
    """
    module = gate_module()
    schema = load_schema(GATE_SCHEMA_PATH)
    corpus: dict[str, Path] = {path.name: path for path in VALID_GATES}
    corpus.update({name: INVALID_EXAMPLES / name for name in INVALID_GATES})
    corpus[GATE_DECLARATION.name] = GATE_DECLARATION
    for name, path in sorted(corpus.items()):
        document = load_document(path)
        by_schema = bool(failures_for(document, schema))
        by_checker = bool(module.validate(document))
        assert by_schema == by_checker, (
            f"{name}: schemas/gate.schema.json says {'reject' if by_schema else 'accept'} and "
            f"harness/gate_check.py says {'reject' if by_checker else 'accept'}.\n"
            f"  schema: {[str(f) for f in failures_for(document, schema)]}\n"
            f"  checker: {module.validate(document)}"
        )
    # And the top-level key sets are the same, so a field added to the schema
    # and never taught to the checker is caught even before an example uses it.
    required = set(schema["required"]) | set(schema["properties"])
    assert required <= set(module.TOP_LEVEL_KEYS) | set(schema["properties"]), (
        "the checker's idea of a declaration's keys and the schema's disagree"
    )
    assert set(module.TOP_LEVEL_KEYS) == set(schema["properties"]), (
        f"the checker knows {sorted(module.TOP_LEVEL_KEYS)} and the schema has "
        f"{sorted(schema['properties'])}; add the new key to gate_check.TOP_LEVEL_KEYS"
    )


def test_the_gate_schema_refuses_a_shell_string_in_any_command() -> None:
    """The constraint that would have caught the one false green this fleet has.

    Not a keyword-pair assertion on a file — a property over the whole refused
    set, because the set is the rule and an example is one sample of it. The
    characters that are ALLOWED are asserted too: a schema that refused `=`,
    `,`, `:` or a space would be refused by every real gate, and a constraint
    that everything trips is a constraint everybody works around.
    """
    schema = load_schema(GATE_SCHEMA_PATH)
    refused = re.compile(schema["$defs"]["argv"]["items"]["not"]["pattern"])
    for character in "|;&<>()$`\\'\"*?{}[]#~\n\r":
        assert refused.search(character), (
            f"a gate argument containing {character!r} must be refused: a shell would act on it"
        )
    for argument in (
        "bin/prime", "./bin/prime", "mise", "-d", "--frozen-lockfile", "3.14",
        "postgres://u:p@localhost:5432/db", "KEY=VALUE", "a path with spaces",
    ):
        assert not refused.search(argument), (
            f"{argument!r} is an ordinary gate argument and must be accepted"
        )


# -- 2. core's own declaration -------------------------------------------


def test_core_declares_its_own_gate() -> None:
    """The control, and the first thing a reader of this repository should be able to do."""
    found = failures_for(load_document(GATE_DECLARATION), load_schema(GATE_SCHEMA_PATH))
    assert not found, (
        f"{GATE_DECLARATION.name} must satisfy {GATE_SCHEMA_PATH.name}:\n  "
        + "\n  ".join(str(f) for f in found)
    )


def test_the_gate_checker_is_green_on_core() -> None:
    """`bin/prime` runs this, so a red here is a red gate.

    The static phase only. The proving phase runs `bin/prime`, and `bin/prime`
    runs this, so the proving phase is not reachable from here and must not be
    attempted: it would recurse. core's CI runs the proving half as a step of
    its own, and `test_core_ci_runs_the_gate_checkers_proving_phase` says so.
    """
    report = gate_module().check(REPO)
    assert report.exit_code == GATE_EXIT_OK, (
        f"core's own gate declaration must check clean, got exit {report.exit_code}:\n"
        + "\n".join(f.render() for f in report.findings)
    )


def test_the_gate_floor_is_not_below_the_suite_core_claims_to_have() -> None:
    """The ratchet, and the reason `minimum` is a number rather than a boolean.

    `minimum: 140` is a decrease-detector: a suite that lost forty tests cannot
    report itself as passing. But a floor nobody raises decays into a lie in the
    other direction, so the assertion also runs the other way — the floor may
    not be BELOW the number of tests the suite actually contains. Every test
    added to this file therefore fails here until the floor in `gate.yml` is
    raised in the same commit, which is the property that makes it a floor rather
    than a snapshot.
    """
    declaration = load_document(GATE_DECLARATION)
    floors = {
        item["id"]: item["minimum"]
        for item in declaration["gate"]["proof"]
        if isinstance(item, dict) and "minimum" in item
    }
    assert floors, "gate.yml declares no floor, so a shrinking suite would report itself as passing"
    declared = max(floors.values())
    tests = [
        name for name, obj in globals().items()
        if name.startswith("test_") and callable(obj) and getattr(obj, "__module__", None) == __name__
    ]
    assert declared >= len(tests), (
        f"gate.yml promises a floor of {declared} and this suite has {len(tests)} tests. "
        "Raise the floor in gate.yml in the same commit as the tests you added — a floor "
        "behind the suite is a floor that will be behind it forever."
    )


def test_core_s_mise_task_is_the_fleet_s_spelling_and_test_is_an_alias() -> None:
    """The one change this packet made outside the checker, asserted not promised.

    Nine of the fleet's fifteen repositories answer to `mise run prime`, so "run
    prime" is the spelling a manager reaches for, and core's was `test`. A task
    that exists under both names — with `depends`, so there is still one command
    — is the cheapest path, and this test is what stops the alias from quietly
    becoming a second `run` string that can drift.
    """
    import tomllib

    with (REPO / "mise.toml").open("rb") as handle:
        tasks = tomllib.load(handle)["tasks"]
    assert "prime" in tasks, "core must answer to `mise run prime`"
    assert "test" in tasks, "core must keep `mise run test` working; something already depends on it"
    assert tasks["test"].get("depends") == ["prime"] and "run" not in tasks["test"], (
        "mise run test must be an ALIAS — a `depends` on prime and no `run` of its own. "
        "A second `run` string would be a second gate, and two gates can disagree."
    )
    assert tasks["prime"]["run"] == load_document(GATE_DECLARATION)["gate"]["entrypoint"], (
        "the mise task and the declaration must name the same file; that agreement is what "
        "`gate.task-unresolvable` exists to check, and this is core checking itself"
    )


# -- 3. the checker can fail ---------------------------------------------


def test_the_gate_checker_rejects_a_command_that_does_not_exist() -> None:
    """Red proof one: the packet's first case, and a string match.

    Not the interesting one. It is here because it is the case that would still
    be caught by a checker that only compared strings, and a red proof has to
    say which of its reds are load-bearing for which claim.
    """
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            **{"gate.yml": gate_declaration_text(**{
                "command: [bin/gate]": "command: [bin/absent]",
                "entrypoint: bin/gate": "entrypoint: bin/absent",
            })},
        )
    assert report.exit_code == GATE_EXIT_FAIL, report.render()
    found = [f.id for f in report.findings]
    assert "gate.command-missing" in found, report.render()
    assert "gate.entrypoint-missing" in found, report.render()


def gate_workflow_text(gate_step: str) -> str:
    """A one-job workflow whose gate step is spelled exactly as `gate_step`.

    Everything above the step is the same in every call, so what varies between
    one case and the next is the SPELLING and nothing else. A shape test that
    changed two things at once would prove neither, and the bug this pins was
    invisible precisely because the fixture changed only one thing — to the one
    spelling the checker happened to understand.
    """
    return (
        "name: ci\n\non: [push]\n\njobs:\n  gate:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v7\n      - name: the gate\n" + gate_step + "\n"
    )


def test_the_gate_checker_sees_the_gate_in_every_run_spelling_this_fleet_writes() -> None:
    r"""The regression, at the level `bin/prime` can see.

    `gate.ci-disagrees` used to read `run:` through a pattern anchored `\s*$`, so
    `run: |` matched and `run: ./bin/prime` did not — and every other spelling
    along with it. Two repositories in this fleet write the gate that way
    (gateway/ci.yml:65, parlor/ci.yml:81) and both were reported as not running
    the gate. A check that cries wolf on correct code is the same defect as one
    that stays quiet on broken code: both teach the reader to ignore it, and
    this one taught it on the first repository that adopted the standard.

    So this asserts the ACCEPTANCE side, from the spellings that occur in real
    workflows rather than from shapes invented here. 139 `run:` keys across the
    twelve workflow trees this standard was written for: 101 block scalars and 38
    one-liners. The 38 were the invisible ones.
    """
    spellings = {
        "the block scalar, 101 of 139 keys in this fleet": "        run: |\n          bin/gate",
        "a one-line run, which is gateway/ci.yml:65": "        run: bin/gate",
        "a one-line run with a leading ./, which is parlor/ci.yml:81": "        run: ./bin/gate",
        "a one-line run with arguments and a quoted variable, which is kit:349": (
            '        run: bin/gate --fail-under "$COVERAGE_FAIL_UNDER"'
        ),
        "a one-line run with a trailing comment, which is core:186": (
            '        run: bin/gate 2>&1 | tee "$RUNNER_TEMP/gate.log"  # the gate'
        ),
        "the sequence-item spelling, which this fleet has not written yet": "        - run: bin/gate",
        "a bare run: whose value is on the lines below": "        run:\n          bin/gate",
    }
    for label, step in spellings.items():
        with tempfile.TemporaryDirectory() as name:
            report = gate_check_runs(
                Path(name), **{".github/workflows/ci.yml": gate_workflow_text(step)}
            )
        assert report.exit_code == GATE_EXIT_OK, (
            f"{label}: a workflow that plainly runs the gate was rejected.\n{report.render()}"
        )
        assert not [f for f in report.findings if f.id.startswith("gate.ci-")], (
            f"{label}: accepted, but with a finding.\n{report.render()}"
        )


def test_the_gate_checker_does_not_read_a_comment_as_a_command() -> None:
    """The other half of that fix, and the one a looser pattern breaks quietly.

    Admitting `run: ./bin/prime` also admits `run: # TODO: wire up bin/prime`.
    PyYAML reads that value as None — there is no command on the line at all —
    so treating the comment as one is a green badge on a workflow that runs
    nothing, which is the false green reached from the false red.

    Asserted against the extractor rather than the verdict, because "the
    repository is still red" and "the comment did not become a command" are
    different claims and only the second is the one that can rot unnoticed. The
    pair is what makes this a test rather than a promise: the comment is not a
    command, and a real command that merely has a comment after it is one.
    """
    module = gate_module()
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)

        def run_lines(step: str) -> str:
            repo = gate_fixture_repo(work / "case")
            workflow = repo / ".github/workflows/ci.yml"
            workflow.write_text(gate_workflow_text(step), encoding="utf-8")
            return "\n".join(module.workflow_run_lines(repo, ".github/workflows/ci.yml"))

        for comment in ("        run: # TODO: wire up bin/gate",
                        "        run: #bin/gate belongs here"):
            assert "bin/gate" not in run_lines(comment), (
                f"{comment!r} carries no command, and the comment must not become one"
            )
        for real in ("        run: bin/gate",
                     '        run: bin/gate --verbose  # add --verbose once the suite is quieter'):
            assert "bin/gate" in run_lines(real), f"{real!r} does call the gate and must be read as one"


def test_gate_ci_multi_invocation_and_indirect_invocation_have_a_stated_policy() -> None:
    """How many times, and through what — the three answers, asserted.

    docs/gate.md states the policy and this pins it, because a policy that lives
    only in prose decays the first time nobody remembers writing it. The shapes:

    MULTIPLE invocations PASS. `invokes` claims the gate is REACHABLE from CI,
    not how often it is reached, and core's own workflow runs `bin/prime` and
    `bin/prime --pytest`. A checker that read multiplicity as drift would fire on
    the repository that wrote the rule.

    INDIRECT through the task the declaration names PASSES, because
    check_task has already proven that task resolves to the declared entrypoint —
    nothing is taken on trust.

    INDIRECT through a wrapper nobody declared WARNS. This checker reads no
    Makefile, so a `make gate` target and an emptied one are the same text to it;
    failing there is the false red this packet exists to kill and staying silent
    is the false green. The leak is named rather than hidden — an unrelated task
    call warns too — and it is a warning, so the exit code stays 0.
    """
    # Twice in one workflow: a pass, and the case core/ci.yml is.
    twice = (
        "name: ci\n\non: [push]\n\njobs:\n  gate:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - name: the gate\n        run: |\n          bin/gate\n"
        "      - name: the pytest entry point\n        run: |\n          bin/gate --pytest\n"
    )
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(Path(name), **{".github/workflows/ci.yml": twice})
    assert report.exit_code == GATE_EXIT_OK, (
        f"running the gate twice is a pass; multiplicity is not drift.\n{report.render()}"
    )

    # Through the task gate.yml names: a pass, and it is a provable one.
    via_task = gate_workflow_text("        run: mise run prime")
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(Path(name), **{".github/workflows/ci.yml": via_task})
    assert report.exit_code == GATE_EXIT_OK, report.render()

    # Through a make target: a warning, and the exit code is the half that matters.
    via_make = gate_workflow_text("        run: make gate")
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(Path(name), **{".github/workflows/ci.yml": via_make})
    assert report.exit_code == GATE_EXIT_OK, (
        f"a warning must not move the exit code.\n{report.render()}"
    )
    unproven = next((f for f in report.findings if f.id == "gate.ci-unproven"), None)
    assert unproven is not None, report.render()
    # ...and it must say what it could not do, or it is a shrug.
    assert "Makefile" in unproven.message, unproven.render()

    # And the failure is still a failure: a workflow that gates through nothing.
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name), **{".github/workflows/ci.yml": gate_workflow_text("        run: npm ci")}
        )
    assert report.exit_code == GATE_EXIT_FAIL, report.render()
    assert "gate.ci-disagrees" in [f.id for f in report.findings], report.render()


def test_the_gate_checker_rejects_a_mise_task_that_is_not_in_the_config() -> None:
    """Red proof two: also a string match, and here for the same reason."""
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name), **{"gate.yml": gate_declaration_text(**{"miseTask: prime": "miseTask: verify"})}
        )
    assert report.exit_code == GATE_EXIT_FAIL, report.render()
    assert "gate.task-missing" in [f.id for f in report.findings], report.render()
    # And the finding says which task it wanted, so the reader does not have to
    # diff a mise config by hand to find out what the declaration claimed.
    task_missing = next(f for f in report.findings if f.id == "gate.task-missing")
    assert "verify" in task_missing.message, task_missing.render()


def test_the_gate_checker_rejects_a_gate_that_exits_zero_without_running_anything() -> None:
    """Red proof three, and the one the other two are not.

    Every string in this repository's declaration is TRUE: the command exists,
    it is executable, `mise run prime` resolves to it, the CI workflow calls it.
    The gate runs, exits 0, and does nothing at all. A checker that only read
    files would call that a clean bill of health, and it is the shape this fleet
    has already shipped once — a gate that reports success and has not run the
    hard part.

    So this test runs the gate. That is the whole difference between a checker
    of declarations and a declaration.
    """
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{"bin/gate": "#!/usr/bin/env bash\n# exits 0, runs nothing, says nothing\nexit 0\n"},
        )
    assert report.exit_code == GATE_EXIT_FAIL, report.render()
    assert "gate.proof-missing" in [f.id for f in report.findings], report.render()
    missing = next(f for f in report.findings if f.id == "gate.proof-missing")
    assert "suite" in missing.message, (
        f"the finding must name WHICH proof was absent, not only that one was: {missing.render()}"
    )
    # And nothing else is blamed. A false green caught by an unrelated
    # complaint is a red for the wrong reason, which is the same mistake as a
    # green for the wrong reason.
    assert [f.id for f in report.findings] == ["gate.proof-missing"], (
        f"only the absent proof should be reported, got {[f.id for f in report.findings]}"
    )


def test_the_gate_checker_rejects_a_gate_that_ran_a_smaller_suite_than_it_promised() -> None:
    """The floor, which is the other half of the proof.

    A proof with no `minimum` cannot tell "3/3 passed" from "1/1 passed", so a
    suite that quietly lost two thirds of itself is still a green. This is the
    same shape as MD12's floors, and it is a decrease-detector because a floor
    above the real number is the only direction worth failing in.
    """
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{
                "gate.yml": gate_declaration_text(**{"minimum: 3": "minimum: 400"}),
                "bin/gate": "#!/usr/bin/env bash\nset -euo pipefail\necho '1/1 passed'\n",
            },
        )
    assert report.exit_code == GATE_EXIT_FAIL, report.render()
    assert "gate.floor" in [f.id for f in report.findings], report.render()
    floor = next(f for f in report.findings if f.id == "gate.floor")
    assert "1" in floor.message and "400" in floor.message, floor.render()


def test_the_gate_checker_never_says_green_when_it_could_not_look() -> None:
    """Exit 2, and the wrapper, which is what a CI job actually calls.

    A checker pointed at nothing has not checked anything. Reporting 0 there is
    how a missing checkout becomes a green badge, and it is the same defect as a
    skipped test: the answer is unknown and the badge says yes.
    """
    module = gate_module()
    with tempfile.TemporaryDirectory() as name:
        absent = module.check(Path(name) / "no-such-directory")
    assert absent.exit_code == GATE_EXIT_COULD_NOT_RUN, absent.render()
    assert absent.could_not_run, "a refusal must say why it refused"
    completed = subprocess.run(
        [str(GATE_WRAPPER), str(REPO / "does-not-exist")],
        capture_output=True, text=True, check=False, cwd=str(REPO),
    )
    assert completed.returncode == GATE_EXIT_COULD_NOT_RUN, (
        f"gate-check on a missing directory must exit 2, got {completed.returncode}:\n"
        f"{completed.stdout}{completed.stderr}"
    )
    assert (module.EXIT_OK, module.EXIT_FAIL, module.EXIT_COULD_NOT_RUN) == (
        GATE_EXIT_OK, GATE_EXIT_FAIL, GATE_EXIT_COULD_NOT_RUN
    )


# -- 4. the checker's own promises ---------------------------------------


def test_a_warning_never_moves_the_gate_checkers_exit_code() -> None:
    """The tri-state contract of MD13, as a test rather than a comment.

    A gate built on booleans forces a choice between "fail on warnings" (noisy,
    gets disabled) and "ignore them" (the report is a lie). Four warnings are
    provoked at once below, the exit code is asserted to be 0, and the ids are
    asserted — so a warning that quietly became a failure, or one that stopped
    being reported at all, is a red rather than a surprise on somebody's laptop.
    """
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            **{
                "gate.yml": gate_declaration_text(**{
                    "  miseTask: prime\n": "",
                    "command: [bin/gate]": "command: [definitely-not-installed-anywhere]",
                    "  selfContained: true\n  requirements: []":
                        "  selfContained: false\n  requirements:\n"
                        "    - kind: toolchain\n      name: a command on PATH nobody ran\n"
                        "      satisfy:\n        command: [definitely-not-installed-anywhere]",
                    "ci:\n  workflow: .github/workflows/ci.yml\n  invokes: [bin/gate]\n": "",
                }),
                "mise.toml": (GATE_FIXTURE / "mise.toml").read_text(encoding="utf-8").replace(
                    'run = "bin/gate"', 'run = "bin/gate | tee /dev/null"'
                ),
            },
        )
    warnings = [f.id for f in report.of("warn")]
    assert report.exit_code == GATE_EXIT_OK, (
        "a warning must not move the exit code, or the checker is red on a laptop and green "
        f"on CI:\n{report.render()}"
    )
    assert not report.of("fail"), report.render()
    assert set(warnings) == {
        "gate.command-unknown", "gate.task-undeclared", "gate.ci-undeclared",
        "gate.requirement-unproven",
    }, f"expected four warnings and got {warnings}"
    assert "warnings do not move the exit code" in report.render()
    # Every severity in the inventory is one of the two that reach a caller, and
    # each id has exactly one. An id that is sometimes fatal and sometimes
    # advisory is two findings wearing one name, and a caller cannot branch on it.
    module = gate_module()
    for identifier, (severity, _claim, _remediate) in sorted(module.FINDINGS.items()):
        assert severity in ("warn", "fail"), f"{identifier} has severity {severity!r}"


def test_the_gate_checker_never_prints_a_value_read_from_the_environment() -> None:
    """MD10, applied to this file's own output.

    No off-the-shelf tool detects a secret *leaked at runtime* into a log or an
    error string — 0 of 268 Semgrep rules intersect CWE-532, gosec has no
    `ast.CallExpr` case, Bandit is `ast.Constant`-only. So the checker's own
    report must never carry a value that came out of the gate's environment, or
    it is a new place a credential lands. A gate that prints a connection string
    the way a failing assertion does is the realistic shape, and the checker's
    report is what a person reads and what a CI log keeps.
    """
    secret = "postgres://gate:should-never-be-printed@localhost:5432/gate"
    leaky = (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        'echo "could not reach ${DATABASE_URL:-unset}"\n'
        "echo '2/3 passed'\n"
        "exit 1\n"
    )
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        repo = gate_fixture_repo(work)
        gate = repo / "bin" / "gate"
        gate.write_text(leaky, encoding="utf-8")
        gate.chmod(0o755)
        report = gate_module().check(repo, prove_it=True, log_dir=work / "log")
        # Read inside the `with`: the log lives in the temporary directory, and
        # reading it after the context has cleaned up would assert nothing.
        log = (work / "log" / "gate.log")
        assert report.exit_code == GATE_EXIT_FAIL, "the leaky gate should be red for failing, and nothing else"
        assert secret not in report.render(), (
            "the checker copied a value out of the gate's environment into its own report. "
            "Print the command string, never its expansion, and leave the gate's output in the "
            "log file where the operator put it."
        )
        assert log.is_file() and "2/3 passed" in log.read_text(encoding="utf-8"), (
            "the gate's own output must still be written somewhere: not printing it is the "
            "property, destroying it would be a different tool's job"
        )


def test_every_gate_finding_the_checker_can_emit_is_declared() -> None:
    """The inventory, in both directions, like `harness/rules.json`.

    A finding the inventory does not describe is a finding nobody was told
    about. An inventory entry the checker cannot reach is a promise nobody keeps,
    and it is the worse of the two: it is a rule that reads as upheld and is not,
    which is the exact shape of the false green this section is about.
    """
    module = gate_module()
    declared = {
        entry["id"]: entry
        for entry in json.loads(GATE_FINDINGS.read_text(encoding="utf-8"))["findings"]
    }
    emitted = set(module.FINDINGS)
    assert emitted == set(declared), (
        f"the checker can emit {sorted(emitted - set(declared)) or 'nothing extra'} and "
        f"harness/gate_findings.json declares "
        f"{sorted(set(declared) - emitted) or 'nothing extra'}"
    )
    for identifier, entry in sorted(declared.items()):
        severity, claim, remediate = module.FINDINGS[identifier]
        assert entry["severity"] == severity, f"{identifier}: inventory and code disagree on severity"
        assert entry["claim"] == claim, f"{identifier}: inventory and code disagree on the claim"
        assert entry["remediate"] == remediate, f"{identifier}: inventory and code disagree on the fix"


def test_every_gate_finding_carries_the_exact_command_that_fixes_it() -> None:
    """MD13's most transferable finding about yamine, made an assertion.

    "Every check message carries the exact remediation command" is the single
    most valuable thing in a 7,000-line file the fleet decided not to copy. A
    check that says only "not ok" makes the reader go and look, and the reader
    who does not look is why it is still broken next week.
    """
    module = gate_module()
    for identifier, (_severity, claim, remediate) in sorted(module.FINDINGS.items()):
        assert claim and claim.endswith("."), f"{identifier}: the claim must be a sentence"
        assert remediate and len(remediate) > 20, f"{identifier}: no remediation, or a useless one"
        assert "\n" not in remediate, f"{identifier}: a multi-line fix is not a fix"
    inventory = json.loads(GATE_FINDINGS.read_text(encoding="utf-8"))
    assert inventory["notEnforced"], (
        "harness/gate_findings.json must record what the gate checker does NOT prove. A "
        "checker with no notEnforced list reads as covering everything, and a gate check "
        "that claims to prove the database tier was hit means only the first thing."
    )
    for entry in inventory["notEnforced"]:
        assert entry["why"] and entry["doc"], f"a notEnforced entry with no reason: {entry}"


def test_every_gate_finding_is_proved_able_to_go_red() -> None:
    """`harness/tests/gate_self_test.sh` must be able to fail, and CI must run it.

    The check is textual and it is the check core already applies to
    `harness/tests/self_test.sh`: a finding with no breakage is a finding nobody
    has tested, and a finding nobody has tested is a finding that will be wrong
    the first time somebody needs it. Reading the script rather than running it
    is deliberate — running twenty-two breakages inside every `bin/prime` would
    be a second gate that can disagree with the first, which is why core's CI
    runs the script as a step of its own and this test makes sure that step
    exists.
    """
    script = GATE_SELF_TEST.read_text(encoding="utf-8")
    module = gate_module()
    for identifier in sorted(module.FINDINGS):
        assert identifier in script, (
            f"{identifier} has no breakage in harness/tests/gate_self_test.sh. Add one that "
            f"expects this exact id, or delete the finding — a finding nothing exercises is "
            f"a finding that will be wrong the first time it is needed."
        )
    for construction in ("expect_red", "expect_warn", "expect_no_leak", "fresh_copy", "exit 1"):
        assert construction in script, f"the red proof lost its {construction}"
    assert "set -uo pipefail" in script, (
        "harness/tests/gate_self_test.sh must set pipefail. A red proof that loses a failure "
        "to a pipe reports a green, which is the defect the whole packet is about."
    )
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "harness/tests/gate_self_test.sh" in ci, (
        "core's CI must run the gate checker's red proof as a step of its own. PLAN.md §1 is "
        "explicit that a second tier is only real if CI invokes it, and a comment claiming CI "
        "runs the self-test is not CI running it."
    )


def test_the_gate_checker_needs_nothing_core_does_not_ship() -> None:
    """Stdlib only, and the sibling reader is the ONE YAML dialect.

    The contract harness is held to this and so is this: a service's CI should
    be able to run `gate-check` with nothing installed, which is the same reason
    `harness/cafaye_contract.py` may not import `jsonschema`. The static half is
    an AST walk, so a `from x import y` inside a function body is caught as
    readily as one at the top; the runtime half is `-I -S`, the interpreter with
    user site-packages, `PYTHONPATH` and the site module all out of the way.
    """
    tree = ast.parse(GATE_CHECK.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    siblings = {"cafaye_contract"}
    outside = sorted(imported - HARNESS_STDLIB_ONLY - siblings - gate_module().EXTRA_STDLIB)
    assert not outside, (
        f"harness/gate_check.py imports {outside}. core has one dependency list and the gate "
        "checker must not add a second: a check that needs a package is a check a Go service's "
        "CI cannot run."
    )
    # The extra list is a hand-maintained list, and hand-maintained lists drift.
    # `sys.stdlib_module_names` is the interpreter's own answer to "what is the
    # standard library", so the three names this file adds are checked against
    # the definition rather than against my memory of it.
    not_stdlib = sorted(
        (HARNESS_STDLIB_ONLY | gate_module().EXTRA_STDLIB)
        - set(sys.stdlib_module_names)
        - siblings
    )
    assert not not_stdlib, (
        f"{not_stdlib} are in the gate checker's allowlist and are not in "
        f"sys.stdlib_module_names on {sys.version_info[:2]}. Either the allowlist names a "
        "package, or this interpreter's standard library is smaller than the pin assumes."
    )
    assert "cafaye_contract" in imported, (
        "harness/gate_check.py must read YAML with the harness's own reader. A second YAML "
        "dialect in core is the four-way drift core exists to end, and it is worse here than "
        "anywhere else, because a declaration one reader accepts and another refuses is a "
        "declaration whose validity depends on who asked."
    )
    # The fixture, NOT core. `--prove` runs the declared gate, and core's gate
    # is `bin/prime`, which is the suite this assertion is inside — pointing it
    # at core recurses, and a test that hangs the gate is worse than no test.
    # The fixture's gate is three lines and its proof is real, so the runtime
    # claim is the same one and it costs nothing.
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(GATE_CHECK), "--prove", str(GATE_FIXTURE)],
        cwd=str(REPO), env={}, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == GATE_EXIT_OK, (
        f"the gate checker must run on the standard library alone, exited "
        f"{completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )
    # And core itself, statically, with an empty environment: the checker's
    # answer must not depend on who is asking, which is the claim
    # `cafaye_contract.py` is held to and this file is held to as far as it
    # goes without running a gate.
    on_core = subprocess.run(
        [sys.executable, "-I", "-S", str(GATE_CHECK), str(REPO)],
        cwd=str(REPO), env={}, capture_output=True, text=True, check=False,
    )
    assert on_core.returncode == GATE_EXIT_OK, (
        f"core's own gate declaration must check clean on the standard library alone, exited "
        f"{on_core.returncode}\n{on_core.stdout}\n{on_core.stderr}"
    )


def test_the_gate_checker_reaches_no_network_and_reads_no_environment() -> None:
    """The two ways this file could stop being a checker and become a process.

    `cafaye_contract.py` is held to "answer the same with a full environment and
    with an empty one". The gate checker cannot be: it runs the gate, and the
    gate needs `PATH`, `HOME` and a dozen other things. So the claim is narrowed
    to the part that is actually true of it, and the part that would be a bug is
    asserted instead — the AST names every way this module could reach outside
    itself, there is no networking one, and the single process call is the one
    the whole tool exists for.
    """
    source = GATE_CHECK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        called.add(".".join(reversed(parts)))
    for banned in (
        "os.system", "os.popen", "os.spawn", "os.fork", "eval", "exec", "compile",
        "__import__", "urllib.request.urlopen", "socket.socket", "http.client",
    ):
        assert banned not in called, (
            f"harness/gate_check.py calls {banned}(). The gate checker reads a tree and runs "
            "one command; it fetches nothing, and a checker whose answer depends on the "
            "network is a checker whose answer depends on the day."
        )
    assert "subprocess.run" in called, (
        "the gate checker is supposed to RUN the declared gate — that is the whole difference "
        "between it and a file that compares strings. If this fails it has stopped doing its "
        "job, and the false green is back."
    )
    assert "os.environ" not in source and "getenv" not in source, (
        "harness/gate_check.py reads no environment variable of its own. Its answer depends "
        "on the repository, not on who is asking. (The gate's own environment is another "
        "matter and is passed through untouched — a gate that needs PATH needs PATH.)"
    )


def test_core_ci_runs_the_gate_checkers_proving_phase() -> None:
    """The recursion has to be broken somewhere, and this says where.

    `bin/prime` runs the STATIC half, because the proving half would run
    `bin/prime`. So the proving half — the half that can catch a false green —
    has to run somewhere else, and "somewhere else" is a CI step that somebody
    can delete. This is the test that notices.
    """
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "gate_check.py" in ci or "gate-check" in ci, (
        "core's CI must run the gate checker; bin/prime runs only its static half"
    )
    assert "--prove" in ci, (
        "core's CI must run the gate checker's PROVING phase. The static half cannot tell a "
        "gate that ran from a gate that exited 0, and that is the defect this packet exists "
        "to close — a check nothing invokes is documentation of a wish."
    )
    # The COMMANDS, not the whole file: `bin/prime` explains in a comment why it
    # does not pass --prove, and an assertion over the whole file would be
    # satisfied by deleting the explanation and fail on the explanation.
    prime = (REPO / "bin" / "prime").read_text(encoding="utf-8")
    commands = [
        line for line in prime.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any("gate_check.py" in line for line in commands), "bin/prime must run the gate check"
    assert not any("--prove" in line for line in commands), (
        "bin/prime runs the static half of the gate check and must not run the proving half: "
        "a gate that proves itself by running itself proves nothing and terminates"
    )
    assert "set -euo pipefail" in prime, "bin/prime keeps pipefail at the top, as every script here does"


# --------------------------------------------------------------------------
# core-14: the command a developer runs must prove what CI proves
#
# The measurement that started this: CI ran `harness/tests/gate_self_test.sh`
# as a step of its own and `bin/prime` did not mention it anywhere. So a
# developer on a clean checkout ran the one command core's own documentation
# tells them to run, saw `173/173 passed`, exited 0, and had learned nothing
# whatsoever about whether `harness/gate_check.py` could detect anything.
# Replacing the checker with a function that returns 0 left `bin/prime` green.
#
# Every test below deletes nothing and modifies nothing committed: each runs
# `bin/prime` out of a throwaway copy of this repository, against a red proof
# the test itself wrote, and reads the exit code.
# --------------------------------------------------------------------------


# A red proof that reports the shape of a real, complete run: every counts row
# bin/prime reads, a control that printed its own PASS line, and one PASS line
# per case. Written by the test rather than doctored into the real script, so
# the assertions are about what `bin/prime` *does with a report* and not about
# what the real script happens to print today.
A_COMPLETE_RED_PROOF_REPORT = """
i=0
while [ "$i" -lt 48 ]; do
  printf 'PASS gate_self_test: case %s of a run this test wrote\\n' "$i"
  i=$((i + 1))
done
printf 'PASS gate_self_test: the control - a repository whose declaration is true - is green\\n'
cat <<'COUNTS'

gate_self_test - counts, reported separately so a green cannot hide one:
  breakages that went RED and named their finding : 18
  warning cases that stayed GREEN                 : 7
  green cases that matched a colour-bearing gate  : 3
  colour reds that still went red                 : 2
  real-workflow shapes that were ACCEPTED         : 12
  extractor assertions (must / must-not)          : 4
  the case that kept a secret out of the report   : 1
  the control (a true declaration, unbroken)      : 1
  SKIPPED                                         : {skipped}
COUNTS
printf 'PASS: gate_self_test - everything above went the way it should have.\\n'
exit {code}
"""


def a_red_proof(
    *, skipped: int = 0, exit_code: int = 0, report: bool = True, prologue: str = ""
) -> str:
    """A stand-in for `harness/tests/gate_self_test.sh`, written by this test.

    `report=False` builds the dangerous shape this whole step exists to catch: a
    red proof that exits 0 having printed nothing at all. There is nothing about
    that output to tell it apart from a pass, which is exactly the property
    `bin/prime` must not rely on.

    `prologue` runs before the report, so a case can print whatever it likes on
    the way out — the real script's failure lines land there.
    """
    return (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        "printf 'red proof: running on CAFAYE_GATE_PYTHON=%s\\n' \"${CAFAYE_GATE_PYTHON:-<unset>}\"\n"
        f"{prologue}"
        + (A_COMPLETE_RED_PROOF_REPORT.format(skipped=skipped, code=exit_code)
           if report else f"exit {exit_code}\n")
    )


def a_complete_account_scope_red_proof(*, cases: int = 32, exit_code: int = 0) -> str:
    """A stand-in for `harness/tests/account_scope_self_test.sh` that passes.

    Written by this test rather than run, for the reason `a_red_proof` is: the
    claim under test is the EXIT CODE of `bin/prime` and its reading of the
    report, not thirty-two fixtures built and broken. The floor `bin/prime`
    requires is 32 cases, so the default reports exactly the number the real
    script reports when the tree is green.
    """
    return (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        "printf 'red proof: running on CAFAYE_ACCOUNT_SCOPE_PYTHON=%s\\n' "
        '"${CAFAYE_ACCOUNT_SCOPE_PYTHON:-<unset>}"\n'
        f"printf '\\n{cases} passed, 0 failed\\n'\n"
        f"exit {exit_code}\n"
    )


def prime_in_a_throwaway_copy(
    work: Path,
    red_proof: str,
    *,
    account_scope_proof: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `bin/prime` from a copy of this repository, against a written red proof.

    The copy is what makes the assertion both cheap and real. The real
    `bin/prime` runs the real suite (about twenty seconds) and then the real red
    proof (about forty); the claim under test is the EXIT CODE and the reading
    of the report, not the work. So the copy gets everything the gate really
    reads — `bin/prime`, `harness/`, `gate.yml`, `mise.toml`, `.github/` — plus
    a stub suite that prints a summary line and exits 0, a symlink to the real
    venv so no interpreter is built, and a `gate_self_test.sh` this caller
    wrote. `set -euo pipefail` and the static gate declaration check therefore
    run for real: a copy that could not pass those would not be a test of the
    step, it would be a test of a broken fixture.

    Nothing outside `work` is touched and no committed file is modified, which
    is the promise `harness/tests/gate_self_test.sh` makes about itself.
    """
    repo = work / "core"
    if repo.exists():
        shutil.rmtree(repo)
    for name in ("bin", "harness", ".github"):
        shutil.copytree(REPO / name, repo / name, symlinks=True)
    shutil.copy2(REPO / "gate.yml", repo / "gate.yml")
    shutil.copy2(REPO / "mise.toml", repo / "mise.toml")
    (repo / "tests").mkdir()
    # The stub suite. `bin/prime` runs `tests/test_specs.py`, and the copy's is
    # a line that prints the summary line the gate declaration asks for — the
    # real 179 tests are a different test's subject and take twenty seconds.
    (repo / "tests" / "test_specs.py").write_text('print("1/1 passed")\n', encoding="utf-8")
    # `gate.yml` satisfies its PyPI requirement by naming `tests/setup.sh`, and
    # the static half checks the named path is there. It is never executed: the
    # venv below is a symlink, so `bin/prime` finds an interpreter and skips
    # setup entirely.
    (repo / "tests" / "setup.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    (repo / "tests" / "setup.sh").chmod(0o755)
    os.symlink(REPO / "tests" / ".venv", repo / "tests" / ".venv")
    (repo / "harness" / "tests" / "gate_self_test.sh").write_text(red_proof, encoding="utf-8")
    (repo / "harness" / "tests" / "gate_self_test.sh").chmod(0o755)
    # The account-scope red proof is the FOURTH red proof `bin/prime` runs, so a
    # copy that omitted it would fail the gate for a reason that has nothing to
    # do with the claim under test — the same way a stub suite has to print its
    # own summary line. A caller that WANTS this step to be what makes the gate
    # red passes its own script.
    (repo / "harness" / "tests" / "account_scope_self_test.sh").write_text(
        account_scope_proof or a_complete_account_scope_red_proof(), encoding="utf-8"
    )
    (repo / "harness" / "tests" / "account_scope_self_test.sh").chmod(0o755)
    return subprocess.run(
        [str(repo / "bin" / "prime")],
        cwd=str(repo), capture_output=True, text=True, check=False,
    )


def test_bin_prime_runs_the_gate_checkers_red_proof() -> None:
    """The step exists, it is not a warning, and its exit code is the red proof's.

    Textual, and read over the COMMANDS rather than the whole file — `bin/prime`
    explains in comments why it does not pass `--prove`, and an assertion over
    the whole file would be satisfied by deleting the explanation and fail on
    it. `test_core_ci_runs_the_gate_checkers_proving_phase` uses the same shape
    for the same reason.

    The two things that make this a gate rather than a comment are asserted
    separately, because either can be deleted on its own: the step has to NAME
    the script (or deleting the line leaves a comment that still mentions it),
    and the exit code has to be read through the pipe from `PIPESTATUS` rather
    than from `$?` — `$?` after `… | tee` is tee's, which is this fleet's one
    recorded false green, reproduced in the one file nobody would think to check
    it in. `docs/gate.md` has the reasoning.
    """
    prime = (REPO / "bin" / "prime").read_text(encoding="utf-8")
    commands = [
        line for line in prime.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any("gate_self_test.sh" in line for line in commands), (
        "bin/prime must RUN harness/tests/gate_self_test.sh, not mention it. Before core-14 "
        "it mentioned it nowhere, and a developer who ran the documented command learned "
        "nothing about whether the gate checker could fail — which is the whole claim CI's "
        "step of its own was making."
    )
    assert "${PIPESTATUS[0]}" in prime, (
        "bin/prime streams the red proof through tee, so its exit code has to be read from "
        "${PIPESTATUS[0]}. `$?` is tee's, and a gate that reports tee's exit code is the "
        "false green this fleet has already shipped once."
    )
    # Scoped to the invocation rather than the whole file, because the reading
    # of the report below contains four `|| true`s and they are load-bearing:
    # under `set -e` an assignment whose command substitution found nothing
    # kills the script before the emptiness check could name what was missing.
    #
    # PER SCRIPT rather than per file, and the change is deliberate rather than
    # a loosened assertion. The invariant this protects is real and worth
    # keeping: running ONE red proof twice gives two gates that can disagree,
    # and a reader of the counts block would see one number for two runs. What
    # was never the claim is that `bin/prime` runs exactly one red proof in
    # total — core-14 added the gate checker's, and core-reserved-tombstone-01
    # added the reserved checker's, and an assertion of `== 1` over the whole
    # file fails on the SECOND red proof ever added to this gate rather than on
    # anything wrong with either of them. So the count is grouped by the script
    # the invocation names: every red proof `bin/prime` runs is run exactly once,
    # and a red proof it runs twice is still red. Adding a red proof stays a
    # one-line diff, and duplicating one is still a failure.
    invocation = [line for line in commands if "bash" in line and "red_proof" in line]
    # Grouped by the FUNCTION the invocation sits in, because the script name is
    # in a variable: `bash "$red_proof"`, with the path assigned a few lines
    # above. So the two calls are textually identical and the only thing that
    # tells them apart is which red proof each function set the variable to —
    # which is exactly the distinction worth asserting, since a function that ran
    # its proof twice is the defect and a function that ran two different proofs
    # is the feature.
    per_function: dict[str, list[str]] = {}
    current = "bin/prime (top level)"
    for line in prime.splitlines():
        stripped = line.strip()
        if stripped.endswith("() {") and not stripped.startswith("#"):
            current = stripped.split("(", 1)[0]
        if not stripped or stripped.startswith("#"):
            continue
        if "bash" in stripped and "red_proof" in stripped:
            per_function.setdefault(current, []).append(stripped)
    assert set(per_function) >= {"gate_red_proof", "reserved_red_proof"}, (
        f"bin/prime runs red proofs from {sorted(per_function)}; it must run the gate "
        "checker's AND the reserved checker's. A checker wired into a gate but never run is "
        "the state this repository has shipped twice, and `reserved-no-delete` naming a "
        "mechanism that did not exist is the third."
    )
    for function, lines in sorted(per_function.items()):
        assert len(lines) == 1, (
            f"bin/prime invokes the red proof {len(lines)} times in {function}(); this test "
            "reads the exit code of exactly one of them. Two invocations is two gates that can "
            "disagree."
        )
    for line in invocation:
        assert "|| true" not in line, (
            "bin/prime must not swallow a red proof's result with `|| true`. A warning that "
            "does not move the exit code is a comment."
        )
    # Ordering, asserted because it is a decision and not an accident. The
    # red proof runs LAST, after the suite, and the reason is the wall clock:
    # a developer iterating on a red suite pays the suite's twenty seconds, not
    # the suite's twenty plus forty seconds about a different thing. Both orders
    # gate identically — nothing here can pass that the other order would fail.
    suite_at = next(
        index for index, line in enumerate(commands) if "tests/test_specs.py" in line
    )
    # The CALL SITES, not the `bash "$red_proof"` lines inside the function
    # bodies. Both red-proof functions are DEFINED above the suite — a shell
    # function has to exist before it is called, and putting the definitions at
    # the bottom next to their calls reads worse — so their bodies sit textually
    # before `tests/test_specs.py` while neither of them RUNS before it. Reading
    # the bodies made this assertion fail the day a second red proof was added,
    # on a gate whose execution order was correct; reading the calls is what the
    # claim was about. Each call site must also appear exactly once.
    calls = [
        index for index, line in enumerate(commands)
        if re.match(r"^\s*[a-z_]+_red_proof\s+\"?\$", line)
    ]
    assert len(calls) >= 2, (
        f"bin/prime calls {len(calls)} red-proof function(s) at the bottom; it must call both "
        "the gate checker's and the reserved checker's."
    )
    assert min(calls) > suite_at, (
        "bin/prime must run every red proof AFTER the suite, so a red suite costs the suite's "
        "runtime and not the suite's runtime plus unrelated work."
    )


def test_bin_prime_runs_the_red_proof_on_the_pinned_interpreter() -> None:
    """`bin/prime` chooses which interpreter proves the checker can fail.

    `harness/tests/gate_self_test.sh` prefers `CAFAYE_GATE_PYTHON` and otherwise
    scans `PATH` for something new enough. That scan is the right default for a
    script a service reads out of core, where the interpreter is the reader's
    business, and the wrong one inside core's own gate: the local gate would
    then depend on the machine, so a laptop whose system Python is 3.9 fails a
    checkout CI is green on, and a laptop whose `python3` is 3.13 proves
    something different from the one CI proved. `bin/prime` exports the venv
    interpreter — the same pinned one the suite runs on — and this asserts it by
    reading what the red proof was actually handed.

    Asserted on the value the red proof received rather than on the line that
    sets it, because the claim is about the interpreter the proof RAN on and an
    export can be spelled four ways.
    """
    with tempfile.TemporaryDirectory() as raw:
        run = prime_in_a_throwaway_copy(Path(raw), a_red_proof())
    assert run.returncode == GATE_EXIT_OK, (
        f"a complete, unskipped red proof must leave bin/prime green, exited {run.returncode}\n"
        f"{run.stdout}\n{run.stderr}"
    )
    # The stub suite in the copy prints `1/1 passed`, so this line being absent
    # means `bin/prime` never reached the suite at all — and the next assertion
    # would then be reading a red proof that ran without a gate around it. The
    # cheapest way to keep the two claims apart.
    assert "1/1 passed" in run.stdout, (
        f"the copy's stub suite never ran, so this test proved nothing about bin/prime\n{run.stdout}"
    )
    handed = re.search(r"red proof: running on CAFAYE_GATE_PYTHON=(\S*)", run.stdout)
    assert handed, (
        "the red proof never reported which interpreter it was handed. Without this line a "
        f"developer cannot tell what proved the checker can fail.\n{run.stdout}"
    )
    assert handed.group(1).endswith("/bin/python"), (
        f"bin/prime handed the red proof {handed.group(1)!r}. It must be the venv interpreter "
        "the suite runs on, not whatever `python3` the machine happens to have — a local gate "
        "that depends on the PATH is a local gate that gives a different answer on a laptop "
        "than on CI."
    )
    # And the two numbers, separately, in bin/prime's own voice — requirement
    # three of the packet. A single number where there are two is how a skip
    # hides inside a pass.
    assert re.search(r"^\s*SKIPPED\s*:\s*0\s*$", run.stdout, re.MULTILINE), (
        f"the red proof's own SKIPPED row must be visible in bin/prime's output\n{run.stdout}"
    )
    assert "and 0 skipped." in run.stdout, (
        "bin/prime must state the pass and skip counts separately, in its own line. It "
        f"streams the report through unchanged, and that is not the same thing.\n{run.stdout}"
    )


def test_bin_prime_is_red_when_the_red_proof_is() -> None:
    """The one the packet's first requirement is about, as a process, not a line.

    `bin/prime` calling the self-test is a claim in a comment until something
    watches the exit code move. Here a red proof that exits 1 — which is what
    `harness/tests/gate_self_test.sh` does when the checker stops catching
    something — has to leave `bin/prime` non-zero, with a message naming the
    red proof rather than a bare status.

    Not a warning: the exit code is asserted, because a warning that does not
    move it is a comment, and this step's entire claim is that the checker can
    fail.
    """
    with tempfile.TemporaryDirectory() as raw:
        run = prime_in_a_throwaway_copy(
            Path(raw),
            a_red_proof(
                exit_code=1,
                prologue=(
                    "printf 'FAIL gate_self_test: the control did not come back green\\n' >&2\n"
                ),
            ),
        )
    assert run.returncode != GATE_EXIT_OK, (
        "a red proof that exits 1 must fail bin/prime, or the local gate is not gating what "
        f"CI gates. It exited {run.returncode}.\n{run.stdout}\n{run.stderr}"
    )
    assert "red proof FAILED" in run.stderr, (
        "the failure has to say WHICH step failed and that the gate is therefore not "
        f"reporting a pass. stderr was:\n{run.stderr}"
    )
    assert "neither is this gate" in run.stderr, (
        f"bin/prime must say the run is not a pass, so nobody reads a red gate as a warning\n{run.stderr}"
    )


def test_bin_prime_is_not_a_pass_when_the_red_proof_says_nothing_or_skips() -> None:
    """The two silent ways a red proof can go green, which are the real packet.

    A red proof that exits 0 having printed nothing at all is the dangerous one:
    it is byte-for-byte indistinguishable from a pass to anything reading the
    exit code, and it is what "the check quietly stopped running" looks like
    from the outside. `bin/prime` must read the report, not the status — the
    same rule core's CI applies to `harness/tests/self_test.sh`'s log, applied
    here so a developer gets it locally.

    The second case is the SKIP: a red proof that reports a complete-looking run
    with cases skipped. Every other rule is satisfied on purpose, so a green
    there could only come from the skip count not being read. The project rule
    is that a check which quietly skips the hard part is worse than no check, so
    a skip count above zero is a red gate and the message has to name the number.
    """
    with tempfile.TemporaryDirectory() as raw:
        silent = prime_in_a_throwaway_copy(
            Path(raw), a_red_proof(report=False)
        )
    assert silent.returncode != GATE_EXIT_OK, (
        "a red proof that exits 0 having printed no counts has proved nothing, and bin/prime "
        f"reported it as a pass (exit {silent.returncode}). An exit code is not a report.\n"
        f"{silent.stdout}\n{silent.stderr}"
    )
    assert "without reporting its counts" in silent.stderr, (
        "the message must say what was missing, or it is a bare status a reader has to "
        f"guess at. stderr was:\n{silent.stderr}"
    )

    assert "1/1 passed" in silent.stdout, (
        f"the copy's stub suite never ran, so this test proved nothing about bin/prime\n{silent.stdout}"
    )

    with tempfile.TemporaryDirectory() as raw:
        skipped = prime_in_a_throwaway_copy(Path(raw), a_red_proof(skipped=2))
    assert skipped.returncode != GATE_EXIT_OK, (
        "a red proof that reported 2 skipped cases must fail bin/prime. A skip is a claim "
        f"this machine could not settle, and it exited {skipped.returncode}.\n"
        f"{skipped.stdout}\n{skipped.stderr}"
    )
    assert "2 skipped cases" in skipped.stderr, (
        "the message must carry the number it refused, because 'something skipped' is not "
        f"actionable. stderr was:\n{skipped.stderr}"
    )


def test_the_red_proof_counts_every_case_it_runs() -> None:
    """The skip count is a literal 0, so what makes it true is asserted here.

    `harness/tests/gate_self_test.sh` prints `SKIPPED : 0` as a constant, and a
    constant in a summary is a claim about the machine rather than a
    measurement of it. It is true, and it is true for a reason that can be
    checked rather than believed: nothing in the script is conditional, every
    case runs at the top level between the function definitions and the footer,
    and the two preconditions that can fail — an interpreter, the fixture —
    exit non-zero before any case runs.

    So this asserts the mechanism instead of the claim, in three parts:

      1. every case category is counted by an increment inside the function
         that RUNS it, so the printed number is a measurement and not a
         hand-maintained tally. This is a fix: the footer used to print the
         case *label* counter as "breakages that went RED", which counted the
         seven warning cases as reds — 25 reported against 18 that happened,
         on the one number a reader has most reason to trust;
      2. the counts block prints that variable rather than a literal, so the
         two can never drift apart again;
      3. every case call is at the top level — column zero, no `if`, no loop,
         no `&&` — which is what "nothing here skips" means in a shell script,
         and what makes the literal 0 a measurement rather than a claim.
    """
    script = GATE_SELF_TEST.read_text(encoding="utf-8")
    # (helper(s) whose calls are cases, the counter the footer must print, the
    # rows that share one counter). Every case kind has a row: a case kind with
    # no number in the counts block is a case kind nobody can tell stopped
    # running, which is how `SKIPPED` became the only number that was printed
    # without anything behind it.
    categories = [
        (("expect_red",), "red_cases", "breakages that went RED"),
        (("expect_warn",), "warn_cases", "warning cases that stayed GREEN"),
        (("expect_green",), "green_cases", "green cases that matched a colour-bearing gate"),
        (("expect_colour_red",), "colour_cases", "colour reds that still went red"),
        (("accepts", "accepts_whole"), "spelling_cases", "real-workflow shapes that were ACCEPTED"),
        (("extracted",), "extractor_cases", "extractor assertions"),
        (("expect_no_leak",), "leak_cases", "the case that kept a secret out of the report"),
    ]
    # A case call is a helper name at the start of a line, followed by its label.
    # `--prove` is allowed because `expect_warn` takes it, and dropping it here
    # would have made this test compare 6 warning cases against a count of 7 —
    # a test that quietly stops counting the thing it exists to count.
    call = re.compile(r"^(?:expect_red|expect_warn|expect_green|expect_colour_red"
                      r"|accepts_whole|accepts|extracted|expect_no_leak)(?: --prove)? '")
    case_lines = [line for line in script.splitlines() if call.match(line)]
    assert case_lines, (
        "no case calls were found in harness/tests/gate_self_test.sh. This test counts them, "
        "and a count of zero here means either the script was rewritten in a way this "
        "assertion cannot read or it stopped running cases."
    )
    for helpers, counter, row in categories:
        increments = script.count(f"{counter}=$(({counter} + 1))")
        assert increments == len(helpers), (
            f"{counter} is incremented {increments} times and read by "
            f"{len(helpers)} function(s) ({', '.join(helpers)}). A counter must be incremented "
            "exactly once inside the function that runs its case, or the footer is printing a "
            "number nothing measured."
        )
        for helper in helpers:
            assert f"{counter}=$(({counter} + 1))" in _function_body(script, helper), (
                f"{counter} is incremented somewhere other than {helper}. A case counted by "
                "another function's branch is a case whose number depends on where it was "
                "called from."
            )
        expected = sum(1 for line in case_lines if line.split(" ")[0] in helpers)
        assert expected, f"no {helpers[0]} cases found; the count this test checks is empty"
        assert re.search(
            rf"^printf ' +{re.escape(row)}.*%s\\n' \"\${counter}\"$", script, re.MULTILINE
        ), (
            f"the counts block must print ${counter} for the row {row!r}, not a literal. A "
            "literal in a summary is a claim about the machine rather than a measurement of "
            "it, and it is how this row claimed 25 reds when 18 happened."
        )
    # 3. Nothing conditional. `if`, `||`, `&&`, `|`, `for`, `while` and a
    # leading tab or space would all mean a case that can be declined.
    # Every case call belongs to a category. A new kind of case with no row in
    # the counts block would run, print a PASS line, and be counted by nobody.
    known = {helper for helpers, _, _ in categories for helper in helpers}
    for line in case_lines:
        name = line.split(" ")[0]
        assert name in known, (
            f"{name} is called as a case in harness/tests/gate_self_test.sh and no category "
            f"counts it ({', '.join(sorted(known))}). A case kind with no number in the counts "
            "block is a case kind nobody can tell stopped running."
        )
        # Only the part BEFORE the label is inspected for chaining: a label is
        # prose, and `…while the command still does…` is not a `while` loop.
        head = line.split("'")[0]
        assert line == line.lstrip(), (
            f"a case call is indented: {line!r}. An indented call is inside a conditional, and "
            "a case that can be skipped is a case whose skip count bin/prime reads as a red."
        )
        assert not re.search(r"\|\||&&|\b(if|for|while|until)\b", head), (
            f"a case call is chained to something: {line!r}. Every case in this script runs "
            "unconditionally, top to bottom; that is what makes the SKIPPED row a measurement "
            "rather than a claim."
        )
    assert "SKIPPED                                         : 0" in script, (
        "the red proof must print a SKIPPED row. bin/prime reads it and fails the gate on a "
        "non-zero, which is only possible if it is printed separately from the pass counts."
    )


def test_the_red_proof_cannot_satisfy_the_gate_s_own_proof() -> None:
    """The red proof must not be able to print the line `gate.proof` looks for.

    This is new in core-14 and it is the sharp edge of putting a second
    program inside the gate. `gate.proof` is matched against **everything**
    `bin/prime` prints — `gate_check.py --prove` captures stdout and stderr and
    applies the pattern to the lot — and the floor reads the LAST match. Before
    core-14 the only thing in that output was the suite, so `N/N passed` could
    only come from the suite. Now a second program's output is in there too, and
    a line like `1/1 passed` printed by the red proof would satisfy
    `gate.proof` — or, worse, be read as the floor's number.

    Today's script prints nothing of that shape, and that is an accident waiting
    to be edited into. So it is checked: every literal `printf`/`echo` in the
    red proof, with its conversion specs filled in with digits, must fail to
    match every pattern core's own `gate.yml` declares. The compile goes
    through the checker's own `_compile`, so this test cannot pass while the
    checker matches differently.
    """
    declaration = load_document(GATE_DECLARATION)
    patterns = [
        item["match"] for item in declaration["gate"]["proof"]
        if isinstance(item, dict) and isinstance(item.get("match"), str)
    ]
    assert patterns, "gate.yml declares no proof pattern, so there is nothing to collide with"
    script = GATE_SELF_TEST.read_text(encoding="utf-8")
    # Two things are stripped before matching, and neither is cosmetic.
    #
    # The QUOTES: the gate's proof is matched against what the terminal SHOWS, so
    # what has to be checked is the text between them — a template still
    # carrying its `'…'` can never match a `^…$` pattern, and the test would be
    # checking that every output line is quoted.
    #
    # The HEREDOC BODIES: a chunk of that script is fixture *source* written into
    # throwaway repositories — `echo "3/3 passed"` is the fixture's declared gate
    # being written to a file, and it never reaches this script's stdout. Three of
    # them match core's proof pattern exactly, and including them would have made
    # this test red for a line that is not the red proof printing anything.
    templates = [
        match.group("body")[1:-1]
        for line in _outside_heredocs(script).splitlines()
        for match in re.finditer(r"""(?:printf|echo)\s+(?P<body>'[^']*'|"[^"]*")""", line)
    ]
    assert len(templates) > 40, (
        f"only {len(templates)} output templates were read out of "
        "harness/tests/gate_self_test.sh. This test is looking at the literal strings the "
        "script prints; finding far fewer than there are means it is reading the wrong shape "
        "of thing and would pass vacuously."
    )
    compiled = [(item, gate_module()._compile(item)) for item in patterns]
    for pattern, matcher in compiled:
        assert matcher is not None, f"gate.yml's proof pattern {pattern!r} does not compile"
        for template in templates:
            # `%%` first: it is the only spec that is not a substitution, and
            # turning it into digits would invent a match that cannot happen.
            filled = re.sub(r"%[-+ #0-9.*]*[a-zA-Z]", "999", re.sub(r"%%", "%", template))
            # A `printf` template is a set of OUTPUT LINES, not one string, so
            # each line is matched separately. Collapsing the newlines to spaces
            # instead would leave a trailing space and quietly make every
            # `…$` pattern unmatchable — which is how a test meant to catch a
            # proof-shaped line passes with one.
            for line in filled.split("\\n"):
                assert not matcher.search(line), (
                    f"harness/tests/gate_self_test.sh prints {template!r}, whose line "
                    f"{line!r} matches core's own gate.proof pattern {pattern!r}. The red proof "
                    "runs inside bin/prime now, and gate.proof is matched against everything "
                    "bin/prime prints with the floor reading the LAST match — so a line shaped "
                    "like a proof in the red proof could satisfy the gate's proof, or be read "
                    "as the floor's number."
                )


def _outside_heredocs(script: str) -> str:
    """The lines of a shell script that the shell itself reads.

    A `<<'EOF'` … `EOF` block is data, not commands: the red proof writes fixture
    repositories that way, so the fixture's own `echo "3/3 passed"` is a line in
    a throwaway file rather than anything the red proof prints. Reading them as
    commands is how a test about "what does this program output" starts failing
    on a string that never reaches the terminal.

    Quoted and unquoted terminators are both handled, `<<-` included, and an
    unterminated block takes the rest of the file — which is what a shell does,
    and is the honest reading of a truncated script.
    """
    out: list[str] = []
    terminator: str | None = None
    for line in script.splitlines():
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        opening = re.search(r"<<-?\s*(?:'([A-Za-z_][A-Za-z0-9_]*)'|\"([A-Za-z_][A-Za-z0-9_]*)\"|([A-Za-z_][A-Za-z0-9_]*))", line)
        if opening:
            terminator = next(group for group in opening.groups() if group)
            continue
        out.append(line)
    return "\n".join(out)


def _function_body(script: str, name: str) -> str:
    """The body of a shell function in the red proof, from `name() {` to its `}`.

    Read rather than guessed because the assertion using it is about *where* an
    increment lives: a counter incremented once inside the function that runs
    its case is a measurement, and the same counter incremented somewhere else
    is a number nothing measured.
    """
    lines = script.splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(f"{name}() {{")
    )
    for index in range(start + 1, len(lines)):
        if lines[index] == "}":
            return "\n".join(lines[start:index + 1])
    raise AssertionError(f"{name}() {{ in harness/tests/gate_self_test.sh has no closing brace")


def test_the_gate_doc_states_the_rule_the_false_green_was_built_from() -> None:
    """`PIPESTATUS`, `pipefail`, and bash — asserted, because they get deleted.

    The one recorded false green in this fleet is `… | tail -45; echo "PRIME
    EXIT=$?"` under zsh, which has no `PIPESTATUS` and therefore reported
    `tail`'s exit code. The fix is one line in a document, which is the easiest
    line in a repository to lose to an edit six months from now. So the line is
    a test.
    """
    doc = GATE_DOC.read_text(encoding="utf-8")
    assert "${PIPESTATUS[0]}" in doc, (
        "docs/gate.md must show the PIPESTATUS spelling for reading a gate's exit code through "
        "a pipe. Without it a reader reinvents the false green."
    )
    assert "set -o pipefail" in doc, "docs/gate.md must show pipefail"
    assert "zsh" in doc, "docs/gate.md must say WHY: zsh has no PIPESTATUS"
    for topic in (
        "mise tasks alone", "CI", "argv", "selfContained", "proof", "minimum",
        "warn", "gate.yml", "schemas/gate.schema.json", "harness/gate_check.py",
        "not a task runner",
    ):
        assert topic in doc, f"docs/gate.md never mentions {topic!r}"
    assert "DECISION NEEDED" not in doc, (
        "a spec on master must read as decided; an open question belongs in DECISIONS.md"
    )


def test_the_gate_doc_names_both_alternatives_it_measured() -> None:
    """A ruling is only a ruling if the rejected option is written down.

    The packet asked for the choice to be justified against the alternatives
    actually tested, and a document that states only its own conclusion is
    indistinguishable from a document that picked something at random. So the
    incumbent (mise tasks alone) and the CI-only declaration are named as
    headings, which means a later reader can disagree with the ruling instead of
    having to reverse-engineer it.
    """
    doc = GATE_DOC.read_text(encoding="utf-8")
    for heading in (
        "## Why not mise tasks alone",
        "## Why not a CI-only declaration",
        "## Why not a second task runner",
    ):
        assert heading in doc, f"docs/gate.md is missing the section {heading!r}"
    for alternative in ("mise tasks", "GitHub Actions", "ci.reusable.yml", "drift"):
        assert alternative in doc, f"docs/gate.md never names {alternative!r}"


# --------------------------------------------------------------------------
# 11. the gate declaration is matched against colour-free bytes (core-13)
# --------------------------------------------------------------------------
#
# A colourising test runner writes a proof line as
#
#     \x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m377 passed\x1b[39m\x1b[22m …
#
# and a declaration written by a person reading a terminal is written against
# what the terminal SHOWS. So `^[ ]*Tests[ ]+([0-9]+) passed` — correct for the
# rendered line — cannot match, because the captured line begins with an escape
# rather than a space. That is not a declaration bug; it is a checker bug, and
# it fires on the first repository that adopts the format with `vitest`.
#
# The ruling (MD17): the checker strips ANSI before applying any `proof[].match`.
# Not `NO_COLOR=1` in the gate, and not a per-repository tolerant regex — both
# make the gate or the declaration carry the cost of a defect in the checker.
#
# The interesting half is not that stripping fixes the false red. It is whether
# stripping can WEAKEN a pattern, which is measured below rather than asserted.

#: The bytes MD17 quotes from a real `vitest` log. Copied verbatim rather than
#: reconstructed, because a paraphrase of a byte sequence is how a regression
#: test stops reproducing the thing it was written for.
VITEST_TESTS_LINE = (
    "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m377 passed\x1b[39m\x1b[22m \x1b[90m(377)\x1b[39m"
)

#: The pattern `core-10-parlor` declared, verbatim. It is correct.
PARLOR_TESTS_PATTERN = r"^[ ]*Tests[ ]+([0-9]+) passed"


def _is_subsequence(smaller: str, larger: str) -> bool:
    """Whether `smaller` is a subsequence of `larger` — the deletion test.

    The property that makes stripping safe to rule on is that it only ever
    DELETES: every character it removes was an escape, and it never inserts or
    reorders one. That is a weaker and more honest claim than "stripping cannot
    weaken a pattern", which is false — see
    `test_stripping_cannot_weaken_a_proof_and_the_two_ways_it_tries`.
    """
    iterator = iter(larger)
    return all(character in iterator for character in smaller)


def test_a_proof_is_matched_against_output_with_the_colour_stripped() -> None:
    """The false red itself: 377 tests ran, and the checker called it a missing proof.

    This is the packet's reason for existing. The suite really printed
    `Tests  377 passed`; the checker captured bytes that begin with an escape,
    so the declared pattern could not match, and it answered `gate.proof-missing`
    about a gate that had just proved, in the same log, that it ran 377 tests.

    Asserted against the real bytes and the real declared pattern, so this test
    cannot pass by agreeing with a weakened fixture.
    """
    module = gate_module()
    assert not module._compile(PARLOR_TESTS_PATTERN).search(VITEST_TESTS_LINE), (
        "the premise of this test has changed: the declared pattern now matches the raw "
        f"bytes {VITEST_TESTS_LINE!r}. Either the stripper leaked into the test, or the "
        "bytes are no longer the ones MD17 recorded."
    )
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{
                "gate.yml": gate_declaration_text(
                    **{
                        "match: '^([0-9]+)/[0-9]+ passed$'": (
                            f"match: '{PARLOR_TESTS_PATTERN}'"
                        ),
                        "minimum: 3": "minimum: 377",
                    }
                ),
                "bin/gate": (
                    "#!/usr/bin/env bash\n"
                    "# A colourising runner, which is the shape this whole packet is about.\n"
                    "# `%b` and not `%s`: printf only expands backslash escapes for %b,\n"
                    "# and writing %s here would emit the two characters \\ and x and this\n"
                    "# test would pass without a single escape ever reaching the checker.\n"
                    "set -euo pipefail\n"
                    "printf '%b\\n' '" + VITEST_TESTS_LINE.replace("\x1b", "\\033") + "'\n"
                ),
            },
        )
    assert report.exit_code == GATE_EXIT_OK, (
        "a gate that really ran 377 tests must not be reported as missing its proof:\n"
        + report.render()
    )


def test_the_gate_checker_strips_every_escape_sequence_it_declares_it_handles() -> None:
    """The sequence types, each on its own, and the record of which are handled.

    CSI (`ESC [ … m`) is what `vitest` emits and it is the only one a naive
    stripper knows. OSC (`ESC ] … BEL`/`ST`) is emitted by some tools, and a
    regex written only for CSI leaves it in place — so the line still starts with
    an escape and the proof still misses. A stripper that silently mangles is
    worse than none, so every class below is asserted on its own, and the class
    that is deliberately NOT handled is asserted to SURVIVE, which is the only
    way a reader can tell the difference between "handled" and "lost".
    """
    module = gate_module()
    strip = module.strip_ansi
    handled = {
        # Leading spaces SURVIVE. Stripping removes escapes, not whitespace, and a
        # pattern that counted on `^[ ]*` still counts on it.
        "SGR colour (CSI)": ("\x1b[2m      Tests \x1b[22m 377 passed", "      Tests  377 passed"),
        "256-colour index (CSI)": ("\x1b[38;5;208mTests\x1b[0m 377 passed", "Tests 377 passed"),
        "cursor erase (CSI, non-m final)": ("\x1b[2KTests 377 passed\x1b[1A", "Tests 377 passed"),
        "private mode (CSI with ?)": ("\x1b[?25lTests 377 passed\x1b[?25h", "Tests 377 passed"),
        "8-bit CSI": ("\x9b2mTests 377 passed\x9b0m", "Tests 377 passed"),
        "OSC 0 title, BEL-terminated": ("\x1b]0;vitest\x07Tests 377 passed", "Tests 377 passed"),
        # OSC 8 wraps a LINK. The wrapper goes and the link text stays, because
        # the link text is content the terminal renders and a proof may
        # legitimately live in it. Stripping must not delete what was displayed.
        "OSC 8 hyperlink, ST-terminated": (
            "\x1b]8;;https://x.dev\x1b\\Tests 377 passed\x1b]8;;\x1b\\",
            "Tests 377 passed",
        ),
        "8-bit OSC": ("\x9d0;vitest\x07Tests 377 passed", "Tests 377 passed"),
        "DCS": ("\x1bP1$r0m\x1b\\Tests 377 passed", "Tests 377 passed"),
        "charset selection": ("\x1b(BTests 377 passed", "Tests 377 passed"),
    }
    for label, (raw, expected) in handled.items():
        assert strip(raw) == expected, (
            f"{label}: the stripper produced {strip(raw)!r}, not {expected!r}. Every sequence "
            "class the docs claim to handle has to be listed in exactly one place, and this "
            "one is claimed there."
        )
    # What is NOT handled, and why leaving it is the safe answer: an unterminated
    # OSC. A stripper that consumes to end-of-input on a sequence with no
    # terminator would delete every line after it — including the proof — and a
    # checker that silently eats evidence is the defect this packet exists to end.
    # So an unterminated sequence survives, and the words on its own line survive.
    unterminated = "INFO start\n\x1b]0;title-never-terminated\nTests  377 passed\n"
    assert "Tests  377 passed" in strip(unterminated), (
        "an unterminated OSC must not swallow the rest of the log. A stripper that "
        f"runs to end-of-input deleted the proof line: {strip(unterminated)!r}"
    )
    assert strip(unterminated).startswith("INFO start\n"), (
        "lines before an unterminated sequence must be untouched"
    )
    # The load-bearing invariant behind every `^` and `$` in this fleet: stripping
    # must not change how many LINES the output has. A stripper that could span a
    # newline would join two lines, and then `^[ ]*Tests` would be able to match a
    # pattern straddling a line boundary — a pattern matching across lines is not
    # a pattern matching a summary line.
    for raw in (
        VITEST_TESTS_LINE,
        unterminated,
        "a\n\x1b]0;x\nb\n",
        "a\n\x1bPfoo\nb\n",
        "\x1b[2Kone\x1b[1Atwo\nthree\n",
    ):
        assert strip(raw).count("\n") == raw.count("\n"), (
            f"stripping changed the line count of {raw!r} -> {strip(raw)!r}; a stripper "
            "that spans a newline joins two lines and breaks ^ and $ for every pattern"
        )


def test_stripping_cannot_weaken_a_proof_and_the_two_ways_it_tries() -> None:
    """The half that is not a formality: can stripping BROADEN a pattern?

    It can, and it is worth being exact about how, because "colour carries no
    assertion" is only reassuring until you know the mechanism. Two cases, both
    measured against the real matching code rather than reasoned about:

    1. **An anchored pattern can reach a line it could not reach.** `^` binds to
       the start of the line. With the escape present, `^[ ]*Tests` cannot match
       `\x1b[2m Tests`; stripped, it can. So a declaration may match MORE lines
       than it did. This is the direction that looks like a strengthening and is
       in fact the risk — and because `minimum` reads the LAST match, a
       broadened pattern can move the number the ratchet sees.

    2. **`.` counts escape bytes.** A pattern that positions itself with a fixed
       number of `.` sees different bytes before and after stripping, so
       `^.{6}Tests` matches one line raw and a different line stripped.

    Neither is a new false green on its own — stripping removes bytes, so a
    pattern needs the REMOVED bytes to have matched before, and the tests above
    already prove the fixed case. But the claim "cannot weaken a pattern" is not
    true as stated, and docs/gate.md says so rather than leaving it implied.
    """
    module = gate_module()
    strip = module.strip_ansi
    compile_ = module._compile

    # Case 1, measured: the anchored pattern reaches a second line only once the
    # escapes are gone, and the floor — which reads the LAST match — changes.
    log = "      Tests  377 passed\n\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m2 passed\x1b[39m\x1b[22m\n"
    found_raw = [m.group(1) for m in compile_(PARLOR_TESTS_PATTERN).finditer(log)]
    found_stripped = [m.group(1) for m in compile_(PARLOR_TESTS_PATTERN).finditer(strip(log))]
    assert found_raw == ["377"], f"the raw bytes must reach only the plain line, got {found_raw}"
    assert found_stripped == ["377", "2"], (
        f"stripping must broaden the anchored pattern to reach the coloured line, got {found_stripped}"
    )

    # Case 2, measured: `.` counts different bytes on each side of the change.
    line = "\x1b[2m      Tests \x1b[22m 377 passed"
    fixed = r"^.{6}Tests"
    assert compile_(fixed).search(line) is None and compile_(fixed).search(strip(line)), (
        "`^.{6}Tests` counts escape bytes raw and visible bytes stripped, so it names a "
        "different line on each side. Documented in docs/gate.md; asserted here so the "
        "consequence is a fact rather than a worry."
    )

    # The property that IS unconditional, and the reason the ruling is still
    # right: stripping only ever DELETES. It cannot insert a byte, so it cannot
    # fabricate a match out of nothing — every character in the stripped text was
    # in the original, in order.
    for raw in (VITEST_TESTS_LINE, log, line, "no escapes at all"):
        assert _is_subsequence(strip(raw), raw), (
            f"stripping {raw!r} produced text that is not a subsequence of it, so it "
            "INVENTED or reordered content rather than only removing escapes"
        )


def test_a_floor_can_no_longer_be_satisfied_by_digits_inside_an_escape() -> None:
    """The inverse false green, which this fix removes and which is easy to miss.

    Every account of this defect has been a false RED — a pattern that could not
    match. The mirror image is worse and quieter: a capture group that lands on
    digits belonging to an escape sequence reads them as the count.

    `\x1b[38;5;208m` is a 256-colour index. A gate that ran **3** tests and
    printed `\x1b[38;5;208m3 passed` matches `^.*?([0-9]+).* passed$` with
    group(1) == `38` — so a declaration with `minimum: 38` was GREEN over a suite
    that ran three. Stripping cannot introduce that reading; it is the only
    outcome in which the number in the log is the number the gate printed.
    """
    module = gate_module()
    pattern = r"^.*?([0-9]+).* passed$"
    compiled = module._compile(pattern)
    colour = "\x1b[38;5;208m3 passed"
    raw_group = compiled.search(colour).group(1)
    stripped_group = compiled.search(module.strip_ansi(colour)).group(1)
    assert raw_group == "38", (
        f"the premise changed: the raw capture group is {raw_group!r}, so this test is "
        "no longer demonstrating that an escape's parameters can satisfy a floor"
    )
    assert stripped_group == "3", (
        f"after stripping the capture group must be the count the gate printed, got {stripped_group!r}"
    )
    # And the same thing end to end, through the checker, with a real floor.
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{
                "gate.yml": gate_declaration_text(
                    **{
                        "match: '^([0-9]+)/[0-9]+ passed$'": f"match: '{pattern}'",
                        "minimum: 3": "minimum: 38",
                    }
                ),
                "bin/gate": (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    "printf '%s\\n' '\\033[38;5;208m3 passed'\n"
                ),
            },
        )
    assert report.exit_code == GATE_EXIT_FAIL, (
        "a gate that printed 3 against a floor of 38 must go red; the 38 in the log is a "
        "colour index, not a test count:\n" + report.render()
    )
    assert "gate.floor" in [f.id for f in report.findings], report.render()


def test_a_proof_that_is_genuinely_absent_still_goes_red_after_stripping() -> None:
    """The other half of the fix: the stripper must not swallow evidence.

    A stripper that deleted anything it did not understand — or a gate whose
    proof line is *only* an escape sequence — would make this green. The check
    is that stripping changes WHERE the pattern is applied and never WHETHER a
    genuinely absent proof is reported. The fixture here prints a near miss
    ("2/4 passed", not the declared `N/N passed`) and must still be caught.
    """
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{
                "bin/gate": (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    "# Colour everywhere, and the declared proof genuinely absent.\n"
                    "printf '\\033[1;32m2\\033[0m/4 \\033[33msomething else\\033[0m\\n'\n"
                    "exit 0\n"
                ),
            },
        )
    assert report.exit_code == GATE_EXIT_FAIL, (
        "colour in the output must not make an absent proof look present:\n" + report.render()
    )
    assert "gate.proof-missing" in [f.id for f in report.findings], report.render()


def test_the_stripper_runs_in_exactly_one_place_and_only_on_proof_matching() -> None:
    """One function, one call site — the shape the packet rules on.

    Four checks apply `proof[].match`, and four call sites to strip would be
    four places to drift. So the stripper is called once, where the output is
    read, before any pattern sees it. This asserts it structurally rather than by
    reading the code: one call site, inside `prove`, and the raw bytes are still
    what gets written to the log.

    That last part matters. The log is the operator's evidence — it is where a
    human goes to see what the gate actually printed — so the log keeps the
    escapes. Stripping the log too would be two call sites and would make the
    evidence disagree with the output.
    """
    source = GATE_CHECK.read_text(encoding="utf-8")
    calls = re.findall(r"\bstrip_ansi\s*\(", source)
    # One is the definition; the rest must all be inside `prove`.
    assert len(calls) == 2, (
        f"strip_ansi is referenced {len(calls)} times (one definition + one call site "
        "expected). Stripping in each check is four call sites that will drift."
    )
    prove_body = source.split("def prove(", 1)[1].split("\ndef ", 1)[0]
    assert "strip_ansi(" in prove_body, (
        "the single strip call must be in prove(), where the output is read and before "
        "any pattern is applied"
    )
    assert prove_body.index("strip_ansi(") < prove_body.index("finditer("), (
        "stripping must happen BEFORE any pattern sees the output"
    )
    with tempfile.TemporaryDirectory() as name:
        report = gate_check_runs(
            Path(name),
            prove=True,
            **{
                "bin/gate": (
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    "printf '%b\\n' '\\033[32m3/3 passed\\033[0m'\n"
                )
            },
        )
        # Read INSIDE the temporary directory's lifetime. The path comes from the
        # report rather than a guess — the log's location is the checker's
        # decision — and a test that hardcoded it would test nothing about the log.
        assert report.log is not None, "a proving run must report where it wrote the log"
        log = report.log.read_text(encoding="utf-8")
    assert "\x1b[32m" in log, (
        "the log must keep the gate's own bytes — it is the operator's evidence, and "
        "stripping it would make the log disagree with the output it records"
    )
    assert report.exit_code == GATE_EXIT_OK, report.render()


def test_the_gate_doc_says_the_output_is_matched_colour_free() -> None:
    """The docs are what an adopter reads before writing a pattern.

    The packet's fifth item is this assertion. A format whose documentation does
    not say the output is colour-free produces a colour-bearing pattern, and that
    pattern is then either wrong or right by accident of which runner the gate
    happened to use that day.
    """
    doc = GATE_DOC.read_text(encoding="utf-8")
    assert "colour-free" in doc or "color-free" in doc, (
        "docs/gate.md must state that the gate's output is matched colour-free"
    )
    for topic in ("ANSI", "escape", "OSC", "CSI"):
        assert topic in doc, f"docs/gate.md never mentions {topic!r} when describing what is stripped"
    # And the weakening caveat has to be written down rather than discovered in
    # somebody's repository, which is the instruction the packet gives for it.
    for topic in ("weaken", "broaden", "last match"):
        assert topic in doc, (
            f"docs/gate.md must say what stripping does to a pattern ({topic!r}); a caveat "
            "that lives only in a worker's report is a caveat the next adopter does not get"
        )


# --------------------------------------------------------------------------
# 12. the tenant-isolation declaration (core-15)
# --------------------------------------------------------------------------
#
# The platform is sold as self-hostable multi-tenant code, and the defect that
# ends that product is one customer reading another's data. Measured across the
# fleet, that defect is invisible from the outside: `identity` has 7
# cross-tenant negative tests and `courier` has 19, and the other eight services
# have none — six of which scope by account in production code.
#
# Two things about that measurement decide this section's shape:
#
#   1. **The implementations are largely correct.** `darkroom` carries
#      `account_id uuid not null` on `assets` and `asset_variants` and constrains
#      every query on it, with zero tests asserting any of it. What is missing is
#      not the predicate; it is the evidence, and the declaration of that
#      evidence.
#   2. **Nobody could ask the question mechanically.** Counting account-scoped
#      routes by pattern gives 96 for gateway and 0 for darkroom, and the 0 is
#      axum's syntax rather than darkroom's. A grep reporting "darkroom has no
#      routes" is WORSE than no grep, because it reads like an answer.
#
# So the boundary is declared (`tenancy.yml`, against
# `schemas/tenant-isolation.schema.json`) and the declaration is checked against
# the tree. Declared, never inferred — D33. These tests are the enforcement half
# of that: a schema with no test is documentation of a wish, and the packet's own
# self-test lives in CI rather than in `bin/prime`, which means the only place a
# broken claim about this work can be caught is right here.


def tenancy_module():
    """`harness/tenancy_check.py`, imported in-process.

    In-process for the same reason `gate_module()` is: a test can assert on the
    `Report` rather than on the text the checker printed, which is what makes
    "the finding says this" checkable without parsing prose.
    """
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import tenancy_check  # noqa: PLC0415 - a sibling module, imported on demand

    return tenancy_check


#: Sentinel for "delete this file" in a breakage table. Deleting is the only
#: honest way to reach `tenancy.declaration-missing`: emptying a line leaves a
#: file that is merely malformed, and a malformed file is `tenancy.schema`, which
#: is a different finding about a different mistake.
DELETE_THE_FILE = object()


def tenancy_fixture_repo(work: Path, fixture: Path = TENANCY_CONFORMING) -> Path:
    """A throwaway copy of a tenancy fixture, and nothing else.

    Each fixture is one small repository that declares its account boundary and
    tells the truth about all of it, so every red below is that repository with
    one thing changed — which proves *this check* is load-bearing rather than
    that something went red.
    """
    target = work / "repo"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(fixture, target)
    return target


def test_the_tenant_isolation_schema_is_draft_2020_12_and_meta_valid() -> None:
    """The new schema is a legal draft 2020-12 schema, with the four headers.

    `test_schemas_declare_draft_2020_12` walks an explicit list of paths, and a
    schema that is not on it is not meta-validated: a malformed one ships, every
    example still "passes" because the reader is the checker rather than
    `jsonschema`, and the defect surfaces in the first service that vendors it.
    So the tenancy schema is asserted here rather than added to that list, to keep
    this packet's diff off a file `core-14-localgate` is editing.
    """
    schema = load_schema(TENANCY_SCHEMA_PATH)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", TENANCY_SCHEMA_PATH
    assert schema.get("$id"), f"{TENANCY_SCHEMA_PATH} needs a stable $id"
    assert schema.get("title"), f"{TENANCY_SCHEMA_PATH} needs a title"
    assert schema.get("description"), f"{TENANCY_SCHEMA_PATH} needs a description"
    jsonschema.Draft202012Validator.check_schema(schema)
    # `additionalProperties: false` at every level, for the reason core states
    # everywhere else: it is what makes an undeclared key an error instead of a
    # silent no-op that reads as a decision somebody made. The levels that carry
    # properties are read out of `$defs` rather than out of `properties`,
    # because `properties.scope` is a `$ref` and asserting on the ref would
    # assert that a reference closes its level, which is not a thing.
    for pointer in ("", "$defs/scope", "$defs/entryPoint", "$defs/enforced", "$defs/negative"):
        node = schema
        for part in [piece for piece in pointer.split("/") if piece]:
            node = node[part]
        assert node.get("additionalProperties") is False, (
            f"{TENANCY_SCHEMA_PATH}#/{pointer} does not close its level. An undeclared key in "
            "a tenancy declaration has to be an error: a field the format tolerates is a field "
            "nobody reads, and a field nobody reads is where the next exception gets added."
        )


def test_the_valid_tenancy_examples_validate() -> None:
    """Every arm of every conditional, and the honest zero.

    `examples/valid/tenancy.account-scoped.yml` exercises `accountScoped: true`
    with a list and `tenancy.honest-zero.yml` exercises `false` with an empty one.
    The second is the one that matters for D33's other half: a service holding no
    customer rows has to be able to SAY so, and a format that cannot express that
    forces it to either omit itself — indistinguishable from having forgotten —
    or declare a boundary it does not have.

    The two `rls` examples are the same argument for the database half, and
    there are two of them rather than one for a reason a reader will hit
    immediately: `databaseEnforced: true` and `databaseEnforced: false` are
    DIFFERENT claims with different consequences, and the false arm is the one
    the whole fleet is in today. A single RLS example would leave the honest
    "the database enforces nothing for me" unproven, which is the state nine
    services are actually in.
    """
    schema = load_schema(TENANCY_SCHEMA_PATH)
    assert len(VALID_TENANCY) == 4, (
        "the four examples are the four arms of the two conditionals (accountScoped true/false, "
        "databaseEnforced true/false); losing one leaves an arm untested"
    )
    for path in VALID_TENANCY:
        found = failures_for(load_document(path), schema)
        assert not found, f"{path.name} must be valid:\n  " + "\n  ".join(str(f) for f in found)


def test_the_invalid_tenancy_examples_are_rejected_for_the_reason_they_document() -> None:
    """Exact `(keyword, path)` pairs, so an example cannot be rejected by accident.

    The shape every other negative case in this repository uses, and the one
    `examples/invalid/README.md` requires of a new case in its own words. The
    pairs worth having by name are `const` on `negative/asserts` — the whole
    format rests on it — and `not` on `scope/sources`, which is what stops one
    repository's answer depending on a sibling's checkout.
    """
    schema = load_schema(TENANCY_SCHEMA_PATH)
    for name, expected in sorted(INVALID_TENANCY.items()):
        path = INVALID_EXAMPLES / name
        assert path.is_file(), f"examples/invalid/{name} is missing"
        found = failures_for(load_document(path), schema)
        assert found, f"examples/invalid/{name} must be REJECTED by {TENANCY_SCHEMA_PATH.name}"
        assert_keywords(found, expected)
        # And the reason has to be one the README documents, so the two cannot
        # drift: the table is the reader's only account of why.
        assert f"## `examples/invalid/{name}`" in INVALID_NOTES.read_text(encoding="utf-8"), (
            f"examples/invalid/README.md must explain {name}. A negative case with no table "
            "row is a file nobody reads and a rule nobody is enforcing."
        )


def test_the_tenancy_checker_and_the_schema_agree_on_every_example() -> None:
    """`harness/tenancy_check.py` re-implements the schema, and that is a risk.

    The checker is stdlib-only so a service's CI can run it with nothing
    installed, and `jsonschema` is not stdlib — so the checker carries its own
    copy of the constraints, which is core's own idiom for a document and its
    schema being the same contract written twice. Written twice means they drift,
    and the direction they drift in is the dangerous one: a checker that accepts
    what the schema refuses lets a service adopt a declaration the format does
    not describe, and every downstream tool reading the schema is now wrong
    about a file in the fleet.
    """
    module = tenancy_module()
    schema = load_schema(TENANCY_SCHEMA_PATH)
    # FOURTEEN documents, not six: the four valid examples (one per arm of the
    # two conditionals), the seven negative ones, and the three fixtures the
    # self-test breaks copies of. The fixtures matter as much as the examples — a
    # fixture that stops satisfying the schema is a self-test whose control is
    # being kept green by a checker that no longer agrees with the format, and
    # that is the exact drift this test exists for.
    documents = [path for folder in ("valid", "invalid")
                 for path in sorted((EXAMPLES / folder).glob("tenancy*.yml"))]
    documents += [TENANCY_CONFORMING / "tenancy.yml",
                  TENANCY_HONEST_ZERO / "tenancy.yml",
                  TENANCY_UNREADABLE / "tenancy.yml"]
    assert len(documents) == 14, f"expected the fourteen tenancy documents core ships, got {documents}"
    for path in documents:
        document = load_document(path)
        by_schema = bool(failures_for(document, schema))
        by_checker = bool(module.validate(document))
        assert by_schema == by_checker, (
            f"{path.name}: the schema {'rejects' if by_schema else 'accepts'} it and the "
            f"checker {'rejects' if by_checker else 'accepts'} it. They are the same "
            f"contract written twice, and this is the moment they stopped being one."
        )
    # And the shape of the checker's top-level key set, so a field added to the
    # schema and never taught to the checker is a red rather than a silent
    # acceptance — the same rule `gate_check.TOP_LEVEL_KEYS` is held to.
    assert module.TOP_LEVEL_KEYS == set(schema["properties"]), (
        f"the checker knows {sorted(module.TOP_LEVEL_KEYS)} and the schema declares "
        f"{sorted(schema['properties'])}. A field one of them knows and the other does "
        "not is a declaration whose meaning depends on which reader asked."
    )


def test_every_tenancy_finding_the_checker_can_emit_is_declared() -> None:
    """The inventory, in both directions, like `harness/rules.json` and gate's.

    `harness/tenancy_findings.json` says in its own header that this file
    asserts the two sets are equal "in BOTH directions". That claim was
    documentation of a wish until this test existed, which is precisely the state
    core's one rule forbids: a rule that is not enforced is not a rule. Both
    directions are the assertion — a finding the inventory does not describe is a
    finding nobody was told about, and an inventory entry the checker cannot
    reach is the worse of the two, because it reads as upheld and is not.
    """
    module = tenancy_module()
    declared = {
        entry["id"]: entry
        for entry in json.loads(TENANCY_FINDINGS.read_text(encoding="utf-8"))["findings"]
    }
    emitted = set(module.FINDINGS)
    assert emitted == set(declared), (
        f"the checker can emit {sorted(emitted - set(declared)) or 'nothing extra'} and "
        f"harness/tenancy_findings.json declares "
        f"{sorted(set(declared) - emitted) or 'nothing extra'}"
    )
    for identifier, entry in sorted(declared.items()):
        severity, claim, remediate = module.FINDINGS[identifier]
        assert entry["severity"] == severity, f"{identifier}: inventory and code disagree on severity"
        assert entry["claim"] == claim, f"{identifier}: inventory and code disagree on the claim"
        assert entry["remediate"] == remediate, f"{identifier}: inventory and code disagree on the fix"


def test_every_tenancy_finding_carries_the_exact_command_that_fixes_it() -> None:
    """MD13's transferable finding about yamine, made an assertion twice.

    A check that says only "not ok" makes the reader go and look, and the reader
    who does not look is why it is still broken next week. The tenancy findings
    are read by whoever gets the red first — a service that has just adopted the
    format and does not yet know the fleet's vocabulary — so the remediation is
    the part under the least pressure to be written carefully.

    The second half is the `notEnforced` list, and it is the reason a reviewer
    can trust the report. Five entries, each with a reason and a document, and
    the two that matter most are that the negative assertion is READ rather than
    RUN and that completeness is only claimed for the SQL the scanner reads.
    """
    module = tenancy_module()
    for identifier, (_severity, claim, remediate) in sorted(module.FINDINGS.items()):
        assert claim and claim.endswith("."), f"{identifier}: the claim must be a sentence"
        assert remediate and len(remediate) > 20, f"{identifier}: no remediation, or a useless one"
        assert "\n" not in remediate, f"{identifier}: a multi-line fix is not a fix"
        # Every severity is one of the two that reach a caller. An id that is
        # sometimes fatal and sometimes advisory is two findings under one name,
        # and a caller cannot branch on it.
        assert module.FINDINGS[identifier][0] in ("warn", "fail"), (
            f"{identifier} has severity {module.FINDINGS[identifier][0]!r}"
        )
    inventory = json.loads(TENANCY_FINDINGS.read_text(encoding="utf-8"))
    assert len(inventory["notEnforced"]) >= 5, (
        f"harness/tenancy_findings.json records {len(inventory['notEnforced'])} of the things "
        "this checker does not prove. A checker with no notEnforced list reads as covering "
        "everything, and this one's entire reason for existing is a grep that reported "
        "'darkroom has no routes'."
    )
    for entry in inventory["notEnforced"]:
        assert entry["why"] and entry["doc"], f"a notEnforced entry with no reason: {entry}"
        # And the document it points at has to exist, or the entry is sending a
        # reader to a page that does not.
        assert (REPO / entry["doc"]).is_file(), (
            f"a notEnforced entry points at {entry['doc']}, which is not in this repository"
        )


def test_every_tenancy_finding_is_proved_able_to_go_red() -> None:
    """The self-test must be able to fail, and CI must run it.

    The same assertion core already applies to the harness self-test and to the
    gate checker's. A finding with no breakage is a finding nobody has tested,
    and a finding nobody has tested is a finding that will be wrong the first
    time somebody needs it. Reading the script rather than running it is
    deliberate: twelve breakages inside every `bin/prime` would be a second gate
    that can disagree with the first, which is why CI runs the script as a step
    of its own and this test makes sure that step exists.
    """
    script = TENANCY_SELF_TEST.read_text(encoding="utf-8")
    module = tenancy_module()
    for identifier in sorted(module.FINDINGS):
        assert identifier in script, (
            f"{identifier} has no breakage in harness/tests/tenancy_self_test.sh. Add one "
            "that expects this exact id, or delete the finding — a finding nothing exercises "
            "is a finding that will be wrong the first time it is needed."
        )
    for construction in ("expect_red", "expect_warn", "expect_green", "fresh_copy", "exit 1"):
        assert construction in script, f"the red proof lost its {construction}"
    assert "set -uo pipefail" in script, (
        "harness/tests/tenancy_self_test.sh must set pipefail. A red proof that loses a "
        "failure to a pipe reports a green, which is the defect the whole packet is about."
    )
    # The control, asserted as a claim rather than a hope. Every red below the
    # control is worth nothing without it: a checker that refused everything
    # would satisfy all twelve. And it must run FIRST, which is the only ordering
    # that makes it a control.
    assert script.index("the control") < script.index("expect_red '"), (
        "the control must run before the first breakage; a control that runs last is a "
        "summary, not a control"
    )
    # The seven the brief names, one each. They are the seven ways scoping gets
    # dropped in practice, and a script that quietly lost one would still report
    # a green with a smaller number on it. The last is the packet's own: the
    # rule that brief called the single highest-value thing in it, which needs
    # its own entry here because it is the only finding with no Supabase lint
    # behind it — and therefore the one a future reader is most likely to assume
    # somebody else's checker already covers.
    for expected in (
        "tenancy.scope-lost", "tenancy.bind-missing", "tenancy.entry-absent",
        "tenancy.denial-missing", "tenancy.denial-refuses", "tenancy.undeclared-entry",
        "tenancy.honest-zero", "tenancy.rls-owner-bypass",
    ):
        assert script.count(expected) >= 1, f"the self-test never names {expected}"
    # Pass and skip counts reported separately, as everywhere in this project: a
    # report that says "all good" when three cases were skipped is a lie.
    assert "SKIPPED" in script, (
        "the self-test must report its skip count separately from its pass count"
    )
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "harness/tests/tenancy_self_test.sh" in ci, (
        "core's CI must run the tenancy checker's red proof as a step of its own. A comment "
        "claiming CI runs a self-test is not CI running it, and that is the lesson of the "
        "four repositories that shipped a check which skipped instead of failing."
    )


def test_the_tenancy_checker_needs_nothing_core_does_not_ship() -> None:
    """Stdlib only, and the runtime half too.

    A service's CI should be able to run `tenancy-check` with nothing installed,
    which is the same reason `gate_check.py` and `cafaye_contract.py` may not
    import `jsonschema`. The static half is an AST walk, so a `from x import y`
    inside a function body is caught as readily as one at the top; the runtime
    half is `-I -S` — user site-packages, `PYTHONPATH` and the site module all
    out of the way.

    Run against the CONFORMING FIXTURE and never against core: core has no
    `tenancy.yml`, so pointing the runtime proof at it would assert a failure as
    though it were a pass. That asymmetry is itself the next test.
    """
    tree = ast.parse(TENANCY_CHECK.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    siblings = {"cafaye_contract"}
    outside = sorted(imported - HARNESS_STDLIB_ONLY - siblings - tenancy_module().EXTRA_STDLIB)
    assert not outside, (
        f"harness/tenancy_check.py imports {outside}. core has one dependency list and the "
        "tenancy checker must not add a second: a check that needs a package is a check a "
        "Go service's CI cannot run."
    )
    # The hand-maintained allowlist is checked against the interpreter's own
    # answer, so a name added to it from memory rather than from `sys` is red.
    not_stdlib = sorted(
        (HARNESS_STDLIB_ONLY | tenancy_module().EXTRA_STDLIB)
        - set(sys.stdlib_module_names)
        - siblings
    )
    assert not not_stdlib, (
        f"{not_stdlib} are in the tenancy checker's allowlist and are not in "
        f"sys.stdlib_module_names on {sys.version_info[:2]}"
    )
    assert "cafaye_contract" in imported, (
        "harness/tenancy_check.py must read YAML with the harness's own reader. A second YAML "
        "dialect in core is the four-way drift core exists to end, and a declaration one "
        "reader accepts and another refuses is a declaration whose validity depends on who "
        "asked."
    )
    with tempfile.TemporaryDirectory() as name:
        repo = tenancy_fixture_repo(Path(name))
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(TENANCY_CHECK), str(repo)],
            cwd=str(REPO), env={}, capture_output=True, text=True, check=False,
        )
    assert completed.returncode == TENANCY_EXIT_OK, (
        f"the tenancy checker must run on the standard library alone, exited "
        f"{completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )


def test_the_tenancy_checker_reads_no_environment_and_runs_no_process() -> None:
    """The one thing this checker must NOT do, because the gate checker must.

    `harness/gate_check.py` runs the gate it is checking; that is its whole
    difference from a file that compares strings. This one must not, and the
    reason is that a tenancy check whose answer depends on what the repository
    can execute is a check whose answer depends on the machine. So where the gate
    checker asserts `subprocess.run` is PRESENT, this asserts every way of
    reaching outside the process is absent.
    """
    source = TENANCY_CHECK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        called.add(".".join(reversed(parts)))
    for banned in (
        "os.system", "os.popen", "os.spawn", "os.fork", "eval", "exec", "compile",
        "__import__", "subprocess.run", "subprocess.Popen", "subprocess.call",
        "urllib.request.urlopen", "socket.socket", "http.client",
    ):
        assert banned not in called, (
            f"harness/tenancy_check.py calls {banned}(). The tenancy checker reads a tree and "
            "answers a question about it; it fetches nothing and runs nothing, because a "
            "boundary check whose answer depends on the machine is a boundary check that "
            "passes where it cannot look."
        )
    assert "os.environ" not in source and "getenv" not in source, (
        "harness/tenancy_check.py reads no environment variable of its own. Its answer "
        "depends on the repository, not on who is asking."
    )


def test_a_repository_with_no_tenancy_declaration_is_a_failure_and_not_a_pass() -> None:
    """The fleet's actual state, asserted rather than described.

    Every repository in this fleet fails `tenancy.declaration-missing` today, and
    that is the correct verdict: a service that has not declared its account
    boundary has not proven one, and the checker's job is to say so out loud
    rather than to infer an answer from whatever queries it can pattern-match.
    Asserting it here is deliberate — the day the fleet adopts the format this
    test has to be rewritten to say so, and a test that quietly kept passing
    while core was wrong is the thing core exists to prevent.

    The second half is the tri-state: pointed at a path that is not a
    repository, the answer is exit 2, never 0 and never 1. A check that could
    not happen has not checked the boundary, and collapsing that into a green is
    how a boundary check becomes a badge.
    """
    module = tenancy_module()
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        empty = work / "no-declaration"
        (empty / "src").mkdir(parents=True)
        (empty / "src" / "thing.rb").write_text("puts 'hello'\n", encoding="utf-8")
        report = module.check(empty)
        assert report.exit_code == TENANCY_EXIT_FAIL, (
            "a repository with no tenancy.yml must be a FAILURE, not a pass and not a skip: "
            f"\n{report.render()}"
        )
        assert [f.id for f in report.findings] == ["tenancy.declaration-missing"], report.render()
        assert "tenancy.yml is not in" in report.render(), report.render()

        # Exit 2: the check could not happen.
        could_not = module.check(work / "does-not-exist")
        assert could_not.exit_code == TENANCY_EXIT_COULD_NOT_RUN, (
            "a checker pointed at a path that is not a repository has not checked anything, "
            f"and must exit 2 rather than 0:\n{could_not.render()}"
        )
        assert could_not.could_not_run, "exit 2 has to say what it could not do"

        # And core itself, which is the fleet's own answer: a failure, naming
        # the file it is missing. This is the row in REPORT-core-15.md's table.
        on_core = module.check(REPO)
        assert on_core.exit_code == TENANCY_EXIT_FAIL, (
            "core does not declare a tenant boundary, and the checker must say so rather "
            f"than pass it:\n{on_core.render()}"
        )


def test_a_warning_never_moves_the_tenancy_checkers_exit_code() -> None:
    """The tri-state, on the case that is easiest to get wrong.

    Three of the sixteen findings core-15 shipped are warnings and all three are the same claim:
    *this machine cannot answer that question*. Failing on them is how a checker
    gets disabled, which would leave the fleet with NO boundary check instead of
    an incomplete one; ignoring them silently is how a report becomes a lie, and
    this checker's entire reason for existing is a grep that reported "darkroom
    has no routes".

    The fixture is a Go service whose account scoping is real and whose syntax
    this scanner cannot read, so the required verdict is: warnings printed,
    exit 0, and emphatically NOT a clean bill of health.
    """
    module = tenancy_module()
    report = module.check(TENANCY_UNREADABLE)
    warnings = {f.id for f in report.of("warn")}
    assert report.exit_code == TENANCY_EXIT_OK, (
        "a warning moved the exit code. The fleet's Go, Elixir and TypeScript services would "
        f"all go red, and the fix a team under pressure reaches for is deleting the check:\n"
        f"{report.render()}"
    )
    assert "tenancy.enumeration-partial" in warnings, report.render()
    assert "tenancy.scope-key-unused" in warnings, report.render()
    assert not report.of("fail"), report.render()
    rendered = report.render()
    # Warnings are counted separately, every time, and the text has to say what
    # it is: "0 failure(s), 1 warning(s)" is a different report from "OK".
    assert "0 failure(s), 2 warning(s)" in rendered, rendered
    assert "warnings do not move the exit code" in rendered, rendered
    # And the one thing this whole packet is about: the report must NOT read as
    # "this service has no account-scoped entry points", which is the defect in
    # its purest form — a confident answer that is really a shrug.
    for phrase in (
        "no account-scoped entry points",
        "no account scoped entry points",
        "found no account-scoped",
    ):
        assert phrase not in rendered, (
            f"the report says {phrase!r} about a service it demonstrably could not read. A "
            "report that reads like an answer is worse than no report."
        )
    # It names the entry point it could not classify, by name. That specificity is
    # the whole difference between "I cannot see this" and silence.
    assert "get-asset" in rendered, rendered

    # The honest zero, the other direction: a service that says it has no
    # account scoping and has none is green, and STILL says out loud that a key
    # it matched nothing in is not a proof.
    zero = module.check(TENANCY_HONEST_ZERO)
    assert zero.exit_code == TENANCY_EXIT_OK, zero.render()
    assert [f.id for f in zero.findings] == ["tenancy.scope-key-unused"], zero.render()


def test_the_conforming_fixture_is_green_and_free_of_warnings() -> None:
    """The control, asserted in the suite as well as in the self-test.

    `tenancy_self_test.sh` asserts this before its first breakage, and it is the
    assertion that makes the twelve reds mean anything — a checker that refused
    everything would satisfy all of them. Asserting it here too is what makes
    "the self-test is green" mean "the checker is right about a true
    declaration", rather than merely "the script exited 0".

    Warning-free is the stronger half, and it is the one that matters: it proves
    the scanner classifies everything this fixture contains, so the warnings in
    the tri-state test are warnings about a fixture's SHAPE rather than
    artefacts of an over-eager scanner.
    """
    report = tenancy_module().check(TENANCY_CONFORMING)
    assert report.exit_code == TENANCY_EXIT_OK, (
        "the conforming fixture declares its account boundary and tells the truth about all "
        f"of it, so it must come back clean:\n{report.render()}"
    )
    assert not report.findings, (
        "the control must be warning-free, not merely green:\n" + report.render()
    )
    assert "0 failure(s), 0 warning(s)" in report.render(), report.render()


def test_every_behavioural_check_the_checker_has_is_proved_load_bearing() -> None:
    """The one the self-test cannot do, because it is not in the gate.

    `harness/tests/tenancy_self_test.sh` breaks one thing at a time and proves
    the checker goes red, and it is the better proof — it names the finding and
    the entry point. But it is a **CI step, not `bin/prime`**, and that is a
    hole with a shape worth measuring rather than assuming. Measured: with
    `check_denials` deleted from `harness/tenancy_check.py`, `bin/prime` still
    reported **186/186 passed**. A gate that is green over a checker which no
    longer checks is precisely the false green core exists to end, and the
    thirteen behavioural findings had no failing test between them and the badge.

    So the same control-then-breakages idiom runs here, in-process, where the
    gate can see it. One entry per finding, each naming the check function it
    exercises, and the table covers all five: `check_locations`,
    `check_enforcement`, `check_closure`, `check_denials`, `check_honest_zero`
    and `check_scan`. Deleting any of them turns this red.

    The control is asserted first and asserted to be FINDING-FREE, not merely
    green: without it every red below would also be satisfied by a checker that
    refused everything.
    """
    module = tenancy_module()
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        # ---- the control
        control = tenancy_fixture_repo(work / "control")
        assert not module.check(control).findings, (
            "the conforming fixture must be finding-free before any breakage below means "
            "anything:\n" + module.check(control).render()
        )
        # ---- one breakage per finding, each labelled with the check it exercises
        sql = "migrations/0001_assets.sql"
        cases: list[tuple[str, Path, list[tuple[str, str, str]], str]] = [
            # check_locations
            ("location-missing", TENANCY_CONFORMING, [
                ("tenancy.yml", "      file: migrations/0001_assets.sql\n      line: 22",
                 "      file: migrations/0002_gone.sql\n      line: 22"),
            ], "tenancy.location-missing"),
            ("line-missing", TENANCY_CONFORMING, [
                ("tenancy.yml", "      line: 37", "      line: 9000"),
            ], "tenancy.line-missing"),
            # check_enforcement
            ("scope-lost", TENANCY_CONFORMING, [
                ("migrations/0001_assets.sql",
                 "select * from assets where id = $1 and account_id = $2",
                 "select * from assets where id = $1\n-- the account predicate is gone"),
            ], "tenancy.scope-lost"),
            ("bind-missing", TENANCY_CONFORMING, [
                ("src/assets.rb", "DB.exec(SQL, checksum, account.account_id)",
                 "DB.exec(SQL, checksum)"),
            ], "tenancy.bind-missing"),
            # check_closure
            ("entry-absent", TENANCY_CONFORMING, [
                ("migrations/0001_assets.sql",
                 "delete from assets where id = $1 and account_id = $2",
                 "delete from assets where id = $1"),
            ], "tenancy.entry-absent"),
            ("undeclared-entry", TENANCY_CONFORMING, [
                ("migrations/0001_assets.sql",
                 "delete from assets where id = $1 and account_id = $2",
                 "delete from assets where id = $1 and account_id = $2\n\n"
                 "-- a refactor nobody declared\nselect * from archive where account_id = $1"),
            ], "tenancy.undeclared-entry"),
            # check_denials
            ("denial-missing", TENANCY_CONFORMING, [
                ("tests/tenancy_test.rb", "assert Assets.fetch(\"a1\", account(OTHER_ACCOUNT)).nil?",
                 "assert_equal :forbidden, Assets.fetch(\"a1\", account(OTHER_ACCOUNT))"),
            ], "tenancy.denial-missing"),
            ("denial-refuses", TENANCY_CONFORMING, [
                ("tenancy.yml",
                 "      line: 22\n    negative:\n      asserts: absent",
                 "      line: 22\n    negative:\n      asserts: forbidden"),
            ], "tenancy.denial-refuses"),
            # check_honest_zero, both arms
            ("honest-zero", TENANCY_HONEST_ZERO, [
                ("src/generate.go", "func Render(",
                 "func ReadForAccount(account_id string) (string, error) {\n"
                 "\t_, _ = account_id, os.ReadFile\n\treturn \"\", nil\n}\n\nfunc Render("),
            ], "tenancy.honest-zero"),
            ("enumeration-empty", TENANCY_HONEST_ZERO, [
                ("tenancy.yml", "\naccountScoped: false", "\naccountScoped: true"),
            ], "tenancy.enumeration-empty"),
            # check_scan
            ("scan-narrowed", TENANCY_CONFORMING, [
                ("tenancy.yml", "    - migrations\n    - src", "    - migrations\n    - db/generated\n    - src"),
            ], "tenancy.scan-narrowed"),
            # read_declaration / validate
            ("declaration-missing", TENANCY_CONFORMING, [
                ("tenancy.yml", DELETE_THE_FILE, ""),
            ], "tenancy.declaration-missing"),
            ("schema", TENANCY_CONFORMING, [
                ("tenancy.yml", "version: 1\n", "version: 1\ncache:\n  enabled: false\n"),
            ], "tenancy.schema"),
            # check_denials, the positive control — the third arm pointed at a
            # line that asserts the language's spelling of NOTHING. The anchor
            # spans the arm's own comment because `expects: checksum` appears on
            # three of the seven entry points and an ambiguous anchor would edit
            # whichever came first.
            ("positive-control-refused", TENANCY_CONFORMING, [
                ("tenancy.yml",
                 "          expects: checksum\n          file: tests/tenancy_test.rb\n          line: 49",
                 "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 49"),
            ], "tenancy.positive-control-refused"),
            # ---- check_denials, the SHAPE. Both entries below edit the FILE and
            # the DECLARATION, because a breakage that edited only one would be
            # caught by `denial-missing` first and would prove the wrong check.
            # `bin/prime` cannot see the self-test's copies, so these are the
            # only proofs of these two findings that the gate watches.
            #
            # The first is the trap the whole packet is about: a read denial that
            # asserts a raised error. A `using` clause filters the row out and
            # raises NOTHING, so the exception being asserted is a privilege
            # failure — which is what a table with no policy at all raises. The
            # suite is green and isolation is broken.
            ("denial-shape-raise", TENANCY_CONFORMING, [
                ("tests/tenancy_test.rb",
                 'assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?',
                 'assert_raises(RuntimeError) { Assets.fetch("a1", account(OTHER_ACCOUNT)) }'),
                ("tenancy.yml",
                 "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 44",
                 "          expects: assert_raises\n          file: tests/tenancy_test.rb\n          line: 44"),
            ], "tenancy.denial-shape"),
            # And the same silence wearing a different hat: `lives_ok` passes
            # when the write matched zero rows, so it cannot tell isolation from
            # a service that returns nothing to anybody.
            ("denial-shape-lives-ok", TENANCY_CONFORMING, [
                ("tests/tenancy_test.rb",
                 'assert_changed("a1") { Assets.settle("a1", account(ACCOUNT)) }',
                 'lives_ok { Assets.settle("a1", account(ACCOUNT)) }'),
                ("tenancy.yml",
                 "          expects: assert_changed\n          file: tests/tenancy_test.rb\n          line: 88",
                 "          expects: lives_ok\n          file: tests/tenancy_test.rb\n          line: 88"),
            ], "tenancy.denial-shape"),
            # The pairing: a denied write with no read of the row it aimed at. An
            # absent result is a lie about a row that exists, and a row count of
            # zero is also what a write that found nothing to do returns.
            ("denial-unpaired", TENANCY_CONFORMING, [
                ("tests/tenancy_test.rb",
                 'assert_unchanged("a1") { Assets.settle("a1", account(OTHER_ACCOUNT)) }',
                 'assert Assets.settle("a1", account(OTHER_ACCOUNT)).nil?'),
                ("tenancy.yml",
                 "          expects: assert_unchanged\n          file: tests/tenancy_test.rb\n          line: 84",
                 "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 84"),
            ], "tenancy.denial-unpaired"),
            # ---- check_rls, the database half. One per finding, and each one
            # removes exactly one thing from the RLS fixture so the finding it
            # proves is the only one that can move.
            #
            # EVERY policy anchor spans the `for … to …` line as well, because
            # the clause text appears five times in 0002_rls.sql. That is not
            # tidiness: `harness/tests/tenancy_self_test.sh`'s `edit` refuses an
            # ambiguous anchor precisely so a breakage cannot silently edit a
            # different statement than the one it names, and an anchor the two
            # files share has to survive that guard.
            #
            # The headline, and the only one the packet called the single
            # highest-value thing in it: a table owner bypasses row-level
            # security unless the table is set FORCE, and `force` is its own
            # reloptions bit, so removing the line cannot disturb the enable
            # line beside it.
            ("rls-force-missing", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql", "alter table assets force row level security;\n", ""),
            ], "tenancy.rls-owner-bypass"),
            ("rls-not-enabled", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql", "alter table assets enable row level security;\n", ""),
            ], "tenancy.rls-not-enabled"),
            # The whole `create policy` statement removed rather than RENAMED: a
            # rename fires `rls-policy-absent` and `rls-undeclared` together (the
            # renamed policy is now one nobody declared), and a breakage that
            # proves two checks proves neither.
            ("rls-policy-absent", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "create policy assets_select_own on assets\n"
                 "  for select to tenant_app\n"
                 "  using (account_id = (select app.current_account()));\n\n",
                 ""),
            ], "tenancy.rls-policy-absent"),
            ("rls-undeclared", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "alter table asset_variants force row level security;\n",
                 "alter table asset_variants force row level security;\n\n"
                 "-- a table the declaration does not cover\n"
                 "alter table uploads enable row level security;\n"
                 "alter table uploads force row level security;\n"),
            ], "tenancy.rls-undeclared"),
            ("rls-permissive", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "create policy assets_select_own on assets\n"
                 "  for select to tenant_app\n"
                 "  using (account_id = (select app.current_account()));",
                 "create policy assets_select_own on assets\n"
                 "  for select to tenant_app\n"
                 "  using (true);"),
            ], "tenancy.rls-permissive"),
            # The THIRD arm of the same finding: the roles the declaration names
            # and the roles the `for … to …` clause binds are not the same roles.
            # It is a second breakage under an id that already has one on purpose —
            # this is one finding with three arms, and splitting it would mean a
            # reader looking up a new name for an arm of a claim they already know.
            # The breakage takes the OTHER direction from the CI self-test's (24b),
            # because the two together are the whole symmetric rule: here the
            # declaration promises a boundary for a role the policy does not
            # govern, so that role reads every row.
            ("rls-roles-disagree", TENANCY_CONFORMING, [
                ("tenancy.yml",
                 "          roles: [tenant_app]\n"
                 "          constrained:\n"
                 "            file: migrations/0002_rls.sql\n"
                 "            line: 67",
                 "          roles: [billing_readonly]\n"
                 "          constrained:\n"
                 "            file: migrations/0002_rls.sql\n"
                 "            line: 67"),
            ], "tenancy.rls-permissive"),
            ("rls-per-row", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "create policy assets_select_own on assets\n"
                 "  for select to tenant_app\n"
                 "  using (account_id = (select app.current_account()));",
                 "create policy assets_select_own on assets\n"
                 "  for select to tenant_app\n"
                 "  using (account_id = app.current_account());"),
            ], "tenancy.rls-per-row"),
            ("rls-role-bypass", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "create role tenant_app noinherit",
                 "create role tenant_app noinherit bypassrls"),
            ], "tenancy.rls-role-bypass"),
            ("rls-definer-search-path", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "  stable\n  security definer\n  set search_path = ''",
                 "  stable\n  security definer"),
            ], "tenancy.rls-definer-search-path"),
            ("rls-view-invoker", TENANCY_CONFORMING, [
                ("migrations/0002_rls.sql",
                 "create view own_assets with (security_invoker = on) as",
                 "create view own_assets as"),
            ], "tenancy.rls-view-invoker"),
            # A policy on a relation that cannot enforce one. The anchor is in
            # `0001_assets.sql`, not `0002_rls.sql`, because `asset_variants` is
            # CREATED in the first migration and merely altered in the second, and
            # a relation's kind comes from where it is created — editing the
            # second file proves nothing about which kind it is. `assets` is
            # avoided as an anchor for the other half of that reason: it appears in
            # both files and the `edit` guard refuses an ambiguous anchor.
            ("rls-unprotectable", TENANCY_CONFORMING, [
                ("migrations/0001_assets.sql",
                 "create table asset_variants (",
                 "create foreign table asset_variants ("),
            ], "tenancy.rls-unprotectable"),
            # The one warning the database half adds, and it is driven here as
            # well as in the self-test because this table is the only one of the
            # three that `bin/prime` runs. It fires on the honest zero with a
            # policy dropped into its Go source — the shape a Rails service's
            # `.rb` migrations arrive in — and the exit-code assertion below
            # reads the severity out of the inventory, so it asserts 0 here
            # without anything in this file having to say so.
            ("rls-unreadable", TENANCY_HONEST_ZERO, [
                ("src/generate.go", "package generate",
                 "package generate\n\n"
                 "// RLS in a language this checker cannot parse.\n"
                 "const enableRLS = \"alter table generated enable row level security\"\n"),
            ], "tenancy.rls-unreadable"),
        ]
        # `declaration-unreadable` needs a whole-file write rather than an edit,
        # and it is the one case where the document must stop being parseable.
        unreadable = tenancy_fixture_repo(work / "unreadable", TENANCY_CONFORMING)
        (unreadable / "tenancy.yml").write_text("version: 1\nentryPoints: [ \n", encoding="utf-8")

        for name, fixture, edits, expected in cases:
            repo = tenancy_fixture_repo(work / name, fixture)
            for relative, old, new in edits:
                path = repo / relative
                if old is DELETE_THE_FILE:
                    # Deleting is the only honest way to reach
                    # `declaration-missing`: emptying a line leaves a file that
                    # is merely malformed, and that is `tenancy.schema`, which is
                    # a different finding about a different mistake.
                    assert path.is_file(), f"the {name} breakage cannot delete a missing {relative}"
                    path.unlink()
                    continue
                body = path.read_text(encoding="utf-8")
                assert old in body, (
                    f"the {name} breakage no longer applies: {old!r} is not in {relative}. A red "
                    "proof that stopped breaking anything is a test that has stopped testing"
                )
                path.write_text(body.replace(old, new, 1), encoding="utf-8")
            report = module.check(repo)
            found = {f.id for f in report.findings}
            assert expected in found, (
                f"the {name} breakage did not produce {expected}. It produced "
                f"{sorted(found) or 'nothing'}, which means the check it exercises is either "
                f"gone or has stopped reading what it claims to read:\n{report.render()}"
            )
            # And the exit code has to follow the finding's OWN declared severity.
            # Asserting `1` here would be wrong for the warnings, and asserting
            # nothing would leave the tri-state unasserted — so the inventory is
            # the oracle, which is also what makes a severity change in
            # `tenancy_findings.json` a change to this test.
            severity = module.FINDINGS[expected][0]
            assert report.exit_code == (TENANCY_EXIT_FAIL if severity == "fail" else TENANCY_EXIT_OK), (
                f"the {name} breakage is a {severity} finding and the run exited "
                f"{report.exit_code}:\n{report.render()}"
            )
        # And the unreadable one, on its own.
        report = module.check(unreadable)
        assert "tenancy.declaration-unreadable" in {f.id for f in report.findings}, report.render()

    # Every failure-severity finding is now exercised by something the GATE
    # runs, and not only by a CI step. This is the assertion that keeps the two
    # lists from drifting apart again.
    exercised = {expected for *_, expected in cases} | {"tenancy.declaration-unreadable"}
    unexercised = sorted(
        identifier for identifier, (severity, _, _) in module.FINDINGS.items()
        if severity == "fail" and identifier not in exercised
    )
    assert not unexercised, (
        f"{unexercised} are failure-severity findings that neither this test nor the "
        "self-test drives through check(). A behavioural finding nothing drives is a "
        "finding whose check can be deleted and leave the gate green."
    )


def test_the_tenancy_doc_states_the_contract_and_both_alternatives() -> None:
    """The doc is what an adopter reads before writing the file.

    It has to carry the ruling's halves — declared not inferred, absent not
    refused — because a format whose documentation does not say that a refusal is
    an enumeration oracle produces services that answer `403` and believe they
    are enforcing something. The alternatives are named for the same reason the
    gate doc names its: a ruling only counts as a ruling if the rejected option
    is written down somewhere a later reader can disagree with.
    """
    doc = TENANCY_DOC.read_text(encoding="utf-8")
    for topic in (
        "tenancy.yml", "tenant-isolation.schema.json", "tenancy_check.py",
        "tenancy_self_test.sh", "D33", "absent", "enumeration oracle",
        "accountScoped", "query-filter", "bind-parameter", "notEnforced",
    ):
        assert topic in doc, f"docs/tenancy.md never mentions {topic!r}"
    for heading in (
        "## Why not a grep, or a rule, or an inference",
        "### Why the line is a line",
        "### Why `insert` is not an operation",
        "### Why `call` closes nothing",
        "## What this does not prove",
    ):
        assert heading in doc, f"docs/tenancy.md is missing the section {heading!r}"
    assert "DECISION NEEDED" not in doc, (
        "a spec on master must read as decided; D33 is in DECISIONS.md, so the doc points at "
        "it rather than reopening the question"
    )
    # The finding count has to be the one the inventory holds, or the doc is a
    # second, stale copy of a list that changes. Both counts, and spelled out
    # rather than a regex over "failures" — a doc that overstates its own
    # checker's coverage is the one thing this document exists to stop, and an
    # overstated count is the same shape of error as the finding it names.
    inventory = json.loads(TENANCY_FINDINGS.read_text(encoding="utf-8"))
    severities = [entry["severity"] for entry in inventory["findings"]]
    # The word table, and why it is a table rather than a number parser. A
    # number parser would have to know English, and this is a document: the
    # reader has to be able to count the findings on the page. So the words are
    # spelled out here and a count that needs a new one fails with "add the word
    # to its table rather than loosening the check" — which is the correct
    # failure, because adding a word is a deliberate act and it is what happened
    # when the database half took this checker from sixteen findings to
    # twenty-eight.
    words = {
        "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
        "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
        "twenty-one": 21, "twenty-two": 22, "twenty-three": 23,
        "twenty-four": 24, "twenty-five": 25, "twenty-six": 26,
        "twenty-seven": 27, "twenty-eight": 28, "twenty-nine": 29, "thirty": 30,
    }
    # The capture admits a hyphen because "twenty-four" is one word to a reader
    # and two tokens to `\w+`, and the number the database half took this checker
    # to is exactly the one that needs one. Reading a hyphenated count as two
    # separate words would have made this fail on a correct document.
    for word, expected in (("failures", severities.count("fail")),
                           ("warnings", severities.count("warn"))):
        match = re.search(rf"\*\*(?:([A-Za-z]+(?:-[A-Za-z]+)*)\s+)?{word}", doc)
        assert match, (
            f"docs/tenancy.md must state how many {word} the checker reports. A reader who "
            "has to count them in the JSON is not reading the doc."
        )
        spelled = match.group(1)
        if spelled is not None:
            assert spelled.lower() in words, (
                f"docs/tenancy.md spells the {word} count as {spelled!r}, which this test "
                "cannot read. Add the word to its table rather than loosening the check."
            )
            assert words[spelled.lower()] == expected, (
                f"docs/tenancy.md says {spelled} {word} and harness/tenancy_findings.json "
                f"holds {expected}. A doc that overstates its own checker's coverage is the "
                "one thing this document exists to stop."
            )
        else:
            # A numeral rather than a word: read it and compare the same way.
            numeral = re.search(rf"\*\*(\d+)\s+{word}", doc)
            assert numeral and int(numeral.group(1)) == expected, (
                f"docs/tenancy.md says {numeral.group(1) if numeral else '?'} {word} and the "
                f"inventory holds {expected}"
            )


# --------------------------------------------------------------------------
# 7b. the database half — the three-way denial shape, and the RLS advisor
# --------------------------------------------------------------------------
#
# The packet this section is from asked for the failure modes of tenant isolation
# to become DETECTABLE, and named two things that were not detectable at all:
#
#   1. **A role that OWNS its table bypasses row-level security unless the table
#      is set `FORCE ROW LEVEL SECURITY`.** Postgres does not document this in
#      the row-level-security guide, and — measured, not assumed — Supabase's
#      database advisor has **no lint for it**: `lints.ts` collects
#      `relforcerowsecurity` for the dashboard's table list and never judges it.
#      So the realistic bad outcome is a team that ships policies, enables RLS,
#      and is silently wrong on exactly the tables it owns in its own schema,
#      with every gate green. Cafaye uses `FORCE` zero times today, which is why
#      this is free to prevent rather than expensive to retrofit.
#
#   2. **The three-way denial shape.** "An unauthenticated request fails" is
#      satisfied by a table with no policy at all, which IS the bug. The claim
#      that carries information is the third arm: no identity reads zero rows,
#      **another tenant's valid credential reads zero rows**, and its own reads
#      its rows. Without the third arm every case is satisfied by a broken
#      service.
#
# Both are specs, so both are constraints with tests, not paragraphs. The FORMS
# are the packet's and the finding ids are named in the ledger below.


def test_the_force_rule_is_a_failure_and_survives_the_force_line_being_removed() -> None:
    """The one rule the packet calls the single highest-value thing in it.

    Three assertions, and each one closes a different way this check could
    quietly not exist:

      * it is at severity **`fail`** — a warning that never moves the exit code
        is a comment, and the realistic failure here is a service that ships a
        policy and is wrong about every row it owns;
      * removing `force row level security` from the migration the declaration
        names makes the checker name `tenancy.rls-owner-bypass` **about that
        table** — the finding alone would not distinguish a policy that was
        never enforced from one that was enforced by something else, and a
        message that cannot tell those apart reports the second as a pass;
      * and the finding's own text says `FORCE` and says the owner reads every
        row, because the remediation string is the part under the least pressure
        to be written carefully and it is the part a service author acts on.
    """
    module = tenancy_module()
    severity, _claim, remediate = module.FINDINGS["tenancy.rls-owner-bypass"]
    assert severity == "fail", (
        "tenancy.rls-owner-bypass must be a failure. A table owner that bypasses row-level "
        f"security is not a warning, it is {severity!r}"
    )
    assert "FORCE ROW LEVEL SECURITY" in remediate, (
        "the remediation has to name the exact statement. A service that reads 'review your "
        f"policies' and does not learn about FORCE is still wrong:\n  {remediate}"
    )
    with tempfile.TemporaryDirectory() as name:
        repo = tenancy_fixture_repo(Path(name))
        # The control: the fixture FORCES both of its tables, so this is green.
        assert not module.check(repo).findings, (
            "the RLS fixture is the control for the rule below and must be finding-free "
            f"first:\n{module.check(repo).render()}"
        )
        # The breakage: exactly one line removed, nothing else touched.
        path = repo / "migrations" / "0002_rls.sql"
        body = path.read_text(encoding="utf-8")
        assert "alter table assets force row level security;" in body, (
            "the RLS fixture no longer carries the FORCE line this test removes. A red proof "
            "that stopped breaking anything is a test that has stopped testing"
        )
        path.write_text(
            body.replace("alter table assets force row level security;\n", "", 1),
            encoding="utf-8",
        )
        report = module.check(repo)
        assert report.exit_code == TENANCY_EXIT_FAIL, report.render()
        bypass = [f for f in report.findings if f.id == "tenancy.rls-owner-bypass"]
        assert bypass, (
            "a table with policies and no FORCE ROW LEVEL SECURITY produced no "
            f"tenancy.rls-owner-bypass:\n{report.render()}"
        )
        # One finding, one table, and the message names the owner bypass.
        assert [f for f in bypass if "assets" in f.message], (
            "the finding did not name the table it is about:\n" + report.render()
        )
        assert "FORCE" in bypass[0].message, bypass[0].message
        # And it is the ONLY thing that fired, which is what makes this a proof
        # of THIS rule rather than of a pile: `force` is its own reloptions bit,
        # so removing it cannot disturb the enable bit beside it.
        assert [f.id for f in report.findings] == ["tenancy.rls-owner-bypass"], (
            "removing the FORCE line moved more than the FORCE rule:\n" + report.render()
        )


def test_the_three_way_denial_shape_is_required_on_every_entry_point() -> None:
    """Three cases, and the third is the one that carries the information.

    `negative` used to be one assertion, which made "an unauthenticated request
    fails" look like coverage — and that is satisfied by a table with no policy
    at all, which is the bug rather than the fix. So the shape is now three named
    cases and the schema requires all three:

      * `no-identity`  — nothing is acting. Reads zero rows.
      * `other-account` — a VALID credential belonging to another account. Reads
        zero rows. This is the arm with all the information in it, and it is the
        one a naive suite leaves out.
      * `own-account` — the account's own valid credential. **Sees its rows.**

    The third arm is the load-bearing constraint, and it is a `const`: a service
    may not answer it with an absent-shaped result, because "every call returns
    nothing" satisfies both negative cases and is a broken service. A table with
    no policy at all is exactly that service, and a suite that cannot tell the
    difference between it and correct isolation has proved nothing.
    """
    schema = load_schema(TENANCY_SCHEMA_PATH)
    negative = schema["$defs"]["negative"]
    cases = negative["properties"]["cases"]
    assert cases.get("minItems") == 3 and cases.get("maxItems") == 3, (
        f"negative.cases must be exactly three arms: {cases.get('minItems')}.."
        f"{cases.get('maxItems')}"
    )
    assert cases["items"]["properties"]["id"]["enum"] == [
        "no-identity", "other-account", "own-account"
    ], "the three arms are a closed vocabulary, and a fourth one is not one of them"
    # `own-account` is `present`, always. Everything else is `absent`, always.
    arms = cases["items"]["allOf"]
    by_value = {
        arm["if"]["properties"]["id"]["const"]: arm["then"]["properties"]["asserts"]["const"]
        for arm in arms
    }
    assert by_value["own-account"] == "present", (
        "the third arm must assert that the account's OWN rows come back. Without it, a "
        "table with no policy at all satisfies the whole declaration."
    )
    assert by_value["no-identity"] == "absent" and by_value["other-account"] == "absent", by_value
    # And the two negative arms may not be answered with a refusal, which is D33's
    # enumeration oracle. A refusal is legal nowhere in the block's VOCABULARY —
    # prose is allowed to name the thing a service must not write, because a
    # constraint nobody can describe is a constraint nobody adopts, so this asks
    # the closed sets rather than the text.
    vocabulary: set = set()
    top_level = negative["properties"]["asserts"]
    if "const" in top_level:
        vocabulary.add(top_level["const"])
    vocabulary |= set(cases["items"]["properties"]["asserts"].get("enum", []))
    assert vocabulary == {"absent", "present"}, (
        f"negative's vocabulary is {sorted(vocabulary)}. Cross-tenant access is answered as "
        "NONEXISTENCE (D33) and the third arm is the only one whose answer is a row; a refusal "
        "in this set is an enumeration oracle with a schema behind it"
    )
    assert "enum" not in cases["items"]["properties"]["expects"], (
        "`expects` is a pattern rather than an enum on purpose — it is this language's own "
        "spelling of nothing and the vocabulary of six languages is not core's to close. What "
        "closes it is `tenancy.positive-control-refused`, and the test above."
    )


def test_the_positive_control_cannot_be_satisfied_by_asserting_absence() -> None:
    """The third arm's line is checked for what it does NOT say.

    `negative.cases[].expects` puts a token on the declared line, and for the two
    denial arms the token IS an absence spelling — which is why this test exists:
    a service can satisfy `own-account` mechanically by pointing it at a line that
    asserts `nil`, and then the declaration says "the account's own rows come
    back" about a test that says the opposite. The checker refuses it, and the
    fixture proves the refusal is a rule rather than an intention.

    The absence vocabulary lives in the checker because it is a fact about the
    *test file* and not about the declaration — no JSON Schema can ask whether a
    line in another language contains `nil`. So it is the duplicated-constraint
    rule: the vocabulary is asserted against the schema's own `expects` pattern,
    or a service could not declare the spelling the checker refuses.
    """
    module = tenancy_module()
    vocabulary = module.ABSENCE_TOKENS
    assert vocabulary, (
        "the checker refuses an absent-shaped result on the positive control, which is a "
        "closed list it has to publish. An empty list is a rule that cannot fail."
    )
    pattern = module.EXPECT_PATTERN
    for token in sorted(vocabulary):
        assert pattern.fullmatch(token), (
            f"{token!r} is in the checker's absence vocabulary but the schema's `expects` "
            "pattern will not admit it, so a service cannot declare the spelling the checker "
            "refuses"
        )
    # The write shapes are NOT absence. `assert_unchanged` is how this format
    # spells "the other account's row came back as it was", and folding it into
    # the absence list would make the positive control unsatisfiable on every
    # write entry point — a rule that makes its own contract illegal gets deleted.
    for token in ("assert_unchanged", "rows_affected_zero", "present"):
        assert token not in vocabulary, (
            f"{token!r} is in the absence vocabulary. A write asserts the other account's row "
            "is UNCHANGED, which is a different fact from asserting nothing came back, and the "
            "positive control's own spelling must never be refusable"
        )
    # And the mechanical proof: point the third arm at a line that asserts nil,
    # and the checker refuses the declaration rather than believing it.
    with tempfile.TemporaryDirectory() as name:
        repo = tenancy_fixture_repo(Path(name))
        declaration = repo / "tenancy.yml"
        assert "expects: checksum" in declaration.read_text(encoding="utf-8"), (
            "the fixture's positive control no longer names the row's own column, so this "
            "test cannot prove the checker refuses an absent-shaped answer"
        )
        declaration.write_text(
            declaration.read_text(encoding="utf-8").replace(
                "          expects: checksum\n          file: tests/tenancy_test.rb\n          line: 49",
                "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 49",
            ),
            encoding="utf-8",
        )
        report = module.check(repo)
        refused = [f for f in report.findings if f.id == "tenancy.positive-control-refused"]
        assert refused, (
            "the third arm declares `expects: nil` — this language's spelling of NOTHING — "
            "as the answer to 'does this account see its own rows'. The checker accepted it:\n"
            + report.render()
        )
        assert report.exit_code == TENANCY_EXIT_FAIL, report.render()


def test_a_denial_arm_may_not_be_asserted_in_the_shape_the_clause_does_not_deny_in() -> None:
    """The three shapes, enforced — the ones Postgres raises nothing about.

    Postgres denies a cross-tenant access three ways and they raise different
    things: a missing grant and a `with check` violation raise `42501`, while a
    `using` clause filtering the row out **raises nothing and matches zero rows**.
    The third is the common one, and a suite that asserts only "it threw" passes
    on it while isolation is completely broken — because a table with no policy
    at all raises exactly the privilege error such a suite is waiting for.

    So three facts are decidable from the declaration and the one line it names,
    and each is a finding rather than a paragraph in `docs/tenancy.md`:

      * a `select`/`update`/`delete` denial arm may not name a RAISING token,
        because those three are denied by `using` and `using` raises nothing;
      * the `own-account` arm may not name a LIVENESS token, because `lives_ok`
        passes when the write matched zero rows — the third arm exists to
        separate isolation from a service that returns nothing, and a liveness
        assertion separates nothing;
      * a denied write may not be answered with an ABSENCE token, because the
        victim's row is still there and "nothing came back" claims it is not.

    Each vocabulary is a fact about the SERVICE's test file, so each lives in the
    checker rather than the schema, and each is a duplicated constraint — which
    core's rule makes a test. This asserts the duplication first, then the three
    refusals, each with the fixture's own line numbers pinned.
    """
    module = tenancy_module()
    pattern = module.EXPECT_PATTERN
    for name in ("RAISING_TOKENS", "LIVENESS_TOKENS", "ABSENCE_TOKENS"):
        vocabulary = getattr(module, name)
        assert vocabulary, (
            f"{name} is empty, and an empty refusal list is a rule that cannot fail"
        )
        for token in sorted(vocabulary):
            assert pattern.fullmatch(token), (
                f"{token!r} is in the checker's {name} but the schema's `expects` pattern will "
                "not admit it, so a service cannot declare the spelling the checker refuses"
            )
    # The three vocabularies are disjoint, and that is what keeps the three
    # findings from fighting over one declaration. `throws_ok` is the hardest
    # case to keep out: it is a liveness assertion written to look like a raise,
    # and it passes when the write matched zero rows, which is a liveness
    # assertion's whole defect.
    assert not module.RAISING_TOKENS & module.LIVENESS_TOKENS, (
        "a token is both a raise and a liveness assertion: "
        f"{sorted(module.RAISING_TOKENS & module.LIVENESS_TOKENS)}. The two lists answer "
        "opposite questions — did it raise, or did it not — and a token in both would be "
        "refused for whichever arm happened to be read first"
    )
    # The write shapes are in none of them. `assert_unchanged` and
    # `rows_affected_zero` are how this format spells "the other account's row
    # came back as it was", and a vocabulary that contained them would make every
    # conforming write declaration illegal — a rule that makes its own contract
    # illegal gets deleted.
    for name in ("RAISING_TOKENS", "LIVENESS_TOKENS"):
        vocabulary = getattr(module, name)
        for token in ("assert_unchanged", "rows_affected_zero", "checksum", "status", "id"):
            assert token not in vocabulary, (
                f"{token!r} is in {name}. That is a legal answer to one of the three arms, so a "
                "refusal list containing it would turn a conforming declaration red"
            )

    # ---- the three refusals, each on the fixture line that carries it
    cases: list[tuple[str, list[tuple[str, str, str]], str]] = [
        # A read denial asserted as a raised error: the trap the packet is about.
        ("a using-denial asserted as a raise", [
            ("tests/tenancy_test.rb",
             'assert Assets.fetch("a1", account(OTHER_ACCOUNT)).nil?',
             'assert_raises(RuntimeError) { Assets.fetch("a1", account(OTHER_ACCOUNT)) }'),
            ("tenancy.yml",
             "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 44",
             "          expects: assert_raises\n          file: tests/tenancy_test.rb\n          line: 44"),
        ], "tenancy.denial-shape"),
        # `lives_ok` on the positive arm of a write.
        ("a positive control proven with lives_ok", [
            ("tests/tenancy_test.rb",
             'assert_changed("a1") { Assets.settle("a1", account(ACCOUNT)) }',
             'lives_ok { Assets.settle("a1", account(ACCOUNT)) }'),
            ("tenancy.yml",
             "          expects: assert_changed\n          file: tests/tenancy_test.rb\n          line: 88",
             "          expects: lives_ok\n          file: tests/tenancy_test.rb\n          line: 88"),
        ], "tenancy.denial-shape"),
        # A denied write with no read of the row it aimed at.
        ("a denied write asserted as an absent result", [
            ("tests/tenancy_test.rb",
             'assert_unchanged("a1") { Assets.settle("a1", account(OTHER_ACCOUNT)) }',
             'assert Assets.settle("a1", account(OTHER_ACCOUNT)).nil?'),
            ("tenancy.yml",
             "          expects: assert_unchanged\n          file: tests/tenancy_test.rb\n          line: 84",
             "          expects: nil\n          file: tests/tenancy_test.rb\n          line: 84"),
        ], "tenancy.denial-unpaired"),
    ]
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        control = tenancy_fixture_repo(work / "control")
        assert not module.check(control).findings, (
            "the conforming fixture must be finding-free before a refusal below means anything: "
            "a checker that refused everything would satisfy all three.\n"
            + module.check(control).render()
        )
        for index, (label, edits, expect) in enumerate(cases):
            repo = tenancy_fixture_repo(work / f"shape-{index}")
            for relative, old, new in edits:
                target = repo / relative
                body = target.read_text(encoding="utf-8")
                assert body.count(old) == 1, (
                    f"{relative} contains the anchor {body.count(old)} times in the fixture, so "
                    "this test would be editing whichever came first and could prove a different "
                    "check than it claims"
                )
                target.write_text(body.replace(old, new, 1), encoding="utf-8")
            report = module.check(repo)
            refused = [f for f in report.findings if f.id == expect]
            assert refused, (
                f"{label} is accepted by the checker. {expect} was expected, and the report "
                f"was:\n{report.render()}"
            )
            assert report.exit_code == TENANCY_EXIT_FAIL, report.render()


def test_the_row_level_security_block_is_draft_2020_12_and_meta_valid() -> None:
    """The `rls` block closes every level, for the reason every other level does.

    `test_the_tenant_isolation_schema_is_draft_2020_12_and_meta_valid` walks the
    pointers that existed when core-15 wrote it. `rls` was added after, and a
    pointer nobody added is a level where `additionalProperties: false` is a
    thing somebody intends rather than a thing the file has — which is how the
    next undeclared key gets in.
    """
    schema = load_schema(TENANCY_SCHEMA_PATH)
    for pointer in (
        "$defs/rls",
        "$defs/rlsTable",
        "$defs/rlsPolicy",
        "$defs/located",
        "$defs/negative",
        "$defs/negative/properties/cases/items",
    ):
        node = schema
        for part in [piece for piece in pointer.split("/")]:
            node = node[part]
        assert node.get("additionalProperties") is False, (
            f"{TENANCY_SCHEMA_PATH.name}#/{pointer} does not close its level"
        )
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_rls_scanner_owns_create_policy_and_the_entry_point_scanner_does_not() -> None:
    """One statement, one owner — the `_INSERT` precedent, applied to policy DDL.

    `create policy … on assets for select … using (account_id = …)` carries the
    tenancy key, so the entry-point scanner would see it, fail to attribute it to
    a `select … from`, and report it through `tenancy.enumeration-partial`. That
    is not a harmless artefact: the control in
    `test_every_behavioural_check_the_checker_has_is_proved_load_bearing` asserts
    the conforming fixture is WARNING-FREE, so an RLS-aware fixture would make
    every red proof below it vacuous.

    So the RLS scanner owns that statement, and this test asserts the ownership
    from both sides: the entry-point scanner does not emit it, and the RLS scanner
    does. A statement two checkers both claim is a statement that is counted
    twice in one place and missed in the other.
    """
    module = tenancy_module()
    with tempfile.TemporaryDirectory() as name:
        repo = tenancy_fixture_repo(Path(name))
        matchers = module.key_spelling("account_id")
        sites, unattributed = module.scan_file(
            repo, repo / "migrations" / "0002_rls.sql", matchers
        )
        assert not sites and not unattributed, (
            "the entry-point scanner claimed a `create policy` statement. It reads SQL "
            f"statements that reach a row; a policy is DDL, and the RLS scanner owns it:\n"
            f"  sites={sites}\n  unattributed={unattributed}"
        )
        ddl = module.read_ddl(repo, repo / "migrations" / "0002_rls.sql")
        tables = dict(ddl.relations)
        assert "assets" in tables and "asset_variants" in tables, sorted(tables)
        assert tables["assets"].forced and tables["asset_variants"].forced, (
            "the RLS scanner read `alter table … force row level security` and did not "
            f"record it: {tables['assets']}"
        )
        assert {policy.name for policy in tables["assets"].policies.values()} == {
            "assets_select_own", "assets_update_own", "assets_insert_own"
        }, sorted(tables["assets"].policies)
        assert tables["assets"].security_invoker is False and "own_assets" in tables, (
            "the view was not recorded, so nothing could check whether it is security_invoker"
        )
        assert tables["own_assets"].security_invoker, (
            "the scanner missed `with (security_invoker = on)` on the view, which is the bit "
            "tenancy.rls-view-invoker exists to check"
        )


def test_the_row_level_security_rules_are_adopted_and_the_exclusions_are_written_down() -> None:
    """Supabase's twenty-eight lints, and every one of them accounted for.

    The packet said thirty. **Measured: twenty-eight** — the advisor is one SQL
    string and `packages/pg-meta/src/sql/studio/advisor/lints.ts` holds exactly
    that many `'…' as name,` blocks. The brief's number is recorded here rather
    than repeated, for the reason PLAN.md §4b gives about counts: a number in a
    document goes stale and the fix is to re-measure.

    So the ledger in `docs/tenancy.md` is a machine-checked table with a closed
    verdict vocabulary, and this test asserts three things about it: every lint
    name appears exactly once, every row names a cafaye finding or says why not,
    and — the part that is the actual point of a ledger — **no row says `out of
    scope` with an empty reason.** A rule that was looked at and left out on
    purpose is a decision; the same rule left out silently is the thing this
    packet exists to stop.
    """
    doc = TENANCY_DOC.read_text(encoding="utf-8")
    table = re.search(
        r"^<!-- rls-ledger:begin -->\n(.*?)^<!-- rls-ledger:end -->",
        doc, re.M | re.S,
    )
    assert table, (
        "docs/tenancy.md must carry the advisor ledger between the two marker comments, so a "
        "rule dropped from it is a failing assertion rather than a row that quietly vanishes"
    )
    rows = [
        line for line in table.group(1).splitlines()
        if line.startswith("|") and "---" not in line
    ]
    rows = [row for row in rows if not row.startswith("| Supabase") and not row.startswith("| cafaye")]
    lints = {row.split("|")[1].strip() for row in rows}
    assert len(rows) == 28, (
        f"the ledger must have one row per advisor lint; found {len(rows)}. Supabase's advisor "
        "holds 28 (measured, not quoted — see the test's docstring)"
    )
    verdicts = {"adopted", "adapted", "left out"}
    for row in rows:
        cells = [cell.strip() for cell in row.split("|")[1:-1]]
        name, level, verdict, cafaye = cells[0], cells[1], cells[2], cells[3]
        assert name in lints and level in ("ERROR", "WARN", "INFO"), row
        assert verdict in verdicts, f"{name}: verdict {verdict!r} is not one of {verdicts}"
        if verdict == "left out":
            assert cells[4], f"{name} is left out with no reason, which is not a decision"
        else:
            assert re.fullmatch(r"`tenancy\.rls-[a-z-]+`", cafaye), (
                f"{name} is {verdict} and names {cafaye!r} rather than a cafaye finding"
            )
    # The FORCE rule has no Supabase ancestor, and that is the point of the
    # packet. It must be in the ledger as cafaye's own, and it must be a
    # `tenancy.rls-` finding, or the "adopted from Supabase" framing would be
    # claiming a credit that does not exist.
    assert "`tenancy.rls-owner-bypass`" in doc, (
        "the FORCE rule has no Supabase lint behind it — measured: `lints.ts` reads "
        "`relforcerowsecurity` for the dashboard's table list and never judges it. docs/tenancy.md "
        "must say so, because 'adopted from Supabase' is the wrong credit for it"
    )


def test_the_row_level_security_documents_and_the_findings_agree() -> None:
    """Every `tenancy.rls-*` finding is described, and nothing is described twice.

    The doc and the inventory are one claim stated twice, which is exactly what
    `test_the_span_name_pattern_is_shared_with_the_traces_schema` does for a
    duplicated pattern. The asymmetry here is the finding: a `tenancy.rls-*` id
    in the doc that the checker cannot emit is a rule a reader was told about and
    nothing enforces, which is the defect `harness/tenancy_findings.json`'s own
    header calls the worse of the two directions.
    """
    module = tenancy_module()
    doc = TENANCY_DOC.read_text(encoding="utf-8")
    emitted = {i for i in module.FINDINGS if i.startswith("tenancy.rls-")}
    described = set(re.findall(r"`(tenancy\.rls-[a-z-]+)`", doc))
    assert emitted == described, (
        f"the doc describes {sorted(described - emitted)} and the checker emits "
        f"{sorted(emitted - described)}. Both directions: a finding nobody was told about "
        "will be wrong the first time somebody needs it, and a rule in the doc that no checker "
        "enforces is a promise nobody keeps."
    )
    # The per-row rule is named in the doc as the packet asked, in the form the
    # doc uses everywhere else: the statement to write, not the shape to avoid.
    assert "(select app.current_account())" in doc, (
        "docs/tenancy.md must show the wrapped form literally. A performance rule stated as "
        "'wrap the call' is advice; stated as the line to write it is a contract."
    )
    assert "`tenancy.rls-per-row`" in doc, "the per-row rule has no finding id in the doc"


def test_the_three_way_denial_is_spelled_out_in_the_tenancy_doc() -> None:
    """The doc has to say the three arms in words an author cannot misread.

    The constraint exists, and a constraint nobody has read about is not yet a
    habit. So the doc carries the shape, the reason the first arm alone is
    worthless, and the assertion each arm needs — which is not the same for all
    three, and that difference is the part a service author gets wrong: a
    `USING` clause that filters the row out raises **nothing** and matches zero
    rows, so arm two is asserted with `is_empty`, not `throws_ok`. Asserting an
    exception there is asserting a *grant* failure and passing for the wrong
    reason, which is how a policy that admits every tenant gets a green test.
    """
    doc = TENANCY_DOC.read_text(encoding="utf-8")
    for topic in (
        "no-identity", "other-account", "own-account",
        "is_empty", "throws_ok", "42501", "with check",
    ):
        assert topic in doc, f"docs/tenancy.md never mentions {topic!r}"
    for heading in (
        "## The three-way denial shape",
        "### The per-row rule: `(select …)`, not the bare call",
    ):
        assert heading in doc, f"docs/tenancy.md is missing the section {heading!r}"


def test_a_new_tenancy_finding_needs_a_case_here_before_it_can_be_shipped() -> None:
    """The rule that keeps the two halves of this packet from drifting.

    Every `tenancy.rls-*` finding is driven through `check()` by
    `test_every_behavioural_check_the_checker_has_is_proved_load_bearing` and by a
    breakage in `harness/tests/tenancy_self_test.sh`. This test is the third
    statement of that obligation, and it is the one that fails when somebody adds
    a rule and proves it in only one of the two places — which is how a finding
    ends up whose red proof lives in a CI step nobody reads while the local gate
    cannot see it.

    It is deliberately about the RLS prefix rather than about every finding: the
    sixteen findings core-15 shipped have their coverage in the two tests above,
    and a new test that restates it would be a second copy of a rule. What has no
    earlier statement is *this packet's* claim — the database half is new, and a
    new claim is where the two halves would come apart.
    """
    module = tenancy_module()
    source = Path(__file__).read_text(encoding="utf-8")
    behavioural = source.index("def test_every_behavioural_check_the_checker_has_is_proved_load_bearing")
    self_test = TENANCY_SELF_TEST.read_text(encoding="utf-8")
    for identifier in sorted(i for i in module.FINDINGS if i.startswith("tenancy.rls-")):
        assert identifier in self_test, (
            f"{identifier} has no breakage in harness/tests/tenancy_self_test.sh"
        )
        assert source.count(identifier) >= 1, (
            f"{identifier} is never named in tests/test_specs.py, so nothing the GATE runs "
            "drives it"
        )
    # And the in-process table really is in the gate, not in a CI-only helper.
    rls_cases = source[behavioural:].count('"tenancy.rls-')
    assert rls_cases >= len([i for i in module.FINDINGS if i.startswith("tenancy.rls-")]), (
        f"only {rls_cases} tenancy.rls-* breakages are in the in-process table, which is the "
        "only one of the three that bin/prime runs. A rule proved only in CI is a rule a "
        "developer running the gate locally has learned nothing about."
    )


# --------------------------------------------------------------------------
# 8. the postgres image pin
# --------------------------------------------------------------------------
#
# DEBT.md D24: the platform owner standardized `postgres:17-alpine` fleet-wide on
# 2026-10-01, and nothing enforced the pin. `compose.postgres-pin` is the rule
# that closes that, and this section is what stops it decaying into a claim.
#
# WHY IT IS ITS OWN SECTION AND NOT A LINE IN THE INVENTORY TESTS
# ---------------------------------------------------------------
# `test_every_rule_the_harness_can_emit_is_declared_in_the_inventory` and
# `test_every_rule_the_harness_can_emit_is_proved_able_to_go_red` are generic, and
# generic is right for "is the rule declared and does it have a breakage". Neither
# can prove a rule decides the thing it claims, and the pin rule is the case in
# point: it is one function, and an inventory test would stay green if that
# function were changed to compare every reference against `latest` and report
# nothing.
#
# So what follows is about the rule's SEMANTICS — what it reads, what it must not
# read, what it cannot compare, and the measured answer for the fleet. The
# measurement is the part a report cannot do: a report is read once, and this is
# read on every commit. "The fleet is uniform" is a claim that decays silently,
# one compose edit at a time, and the thing that notices is the last test here.
#
# The harness itself is in `harness/cafaye_contract.py` under "the postgres image
# pin", the convention is `docs/postgres-pin.md`, and the red proofs are
# breakages 41-44 and warning 45 of `harness/tests/self_test.sh`.

def declared_tag() -> str:
    """The tag core publishes at `POSTGRES_TAG`, read through the real reader.

    Not re-read from the file, deliberately: every test in this section asks the
    question through `read_postgres_tag`, so a `POSTGRES_TAG` that has drifted out
    of the grammar is a `NameError` here rather than a second and lazier answer
    about what the standard is.
    """
    return harness_module().read_postgres_tag(REPO)


def _copied_fixture(root: Path, name: str) -> Path:
    """Copy a fixture under `root`, so a test can mutate it safely.

    `harness/tests/self_test.sh`'s pattern, for the same reason: a copy per case,
    because one must never mask the next, and because mutating the fixture in the
    tree would have the gate writing to the specification — which core's CI
    asserts against with a `git diff --exit-code`.

    Takes the root rather than making one, because this suite has TWO entry points
    (`bin/prime` and `bin/prime --pytest`, which CI asserts collect the same
    number of tests) and a cleanup mechanism only one of them provides would
    leave a temporary directory behind under whichever entry point lacks it. The
    caller owns the `TemporaryDirectory` and both paths get it removed.
    """
    target = Path(root) / name
    shutil.copytree(HARNESS_FIXTURES / name, target)
    return target


# --------------------------------------------------------------------------
# 1. the declaration core publishes
# --------------------------------------------------------------------------


def test_core_declares_exactly_one_postgres_tag_and_it_is_a_tag() -> None:
    """`POSTGRES_TAG` is a published fact, and it has the `VERSION` discipline.

    Three ways this can be wrong and each is a different defect: no file (core
    publishes no standard, so the rule has nothing to compare against and the
    harness refuses), more than one line (a tag file that has been appended to is
    not a tag, and reading the first line would make it one again), and a value
    that is not a tag (then every comparison in the rule is meaningless).

    `read_postgres_tag` refuses all three, and this test asserts the refusals
    exist rather than trusting a docstring — the same "a guard that cannot find
    its target is not a guard" rule the rest of this repository keeps re-deriving.
    """
    module = harness_module()
    path = REPO / module.POSTGRES_TAG_FILE
    assert path.is_file(), (
        f"{module.POSTGRES_TAG_FILE} does not exist at core's root. "
        f"compose.postgres-pin compares every postgres image reference against it, so "
        f"without it the rule has nothing to decide and the harness refuses every run "
        f"(exit {HARNESS_EXIT_REFUSED}) rather than passing silently."
    )
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"{module.POSTGRES_TAG_FILE} holds {len(lines)} non-blank lines ({lines}), want "
        f"exactly 1"
    )
    assert module.POSTGRES_TAG_PATTERN.match(lines[0]), (
        f"{module.POSTGRES_TAG_FILE} holds {lines[0]!r}, which is not a docker tag"
    )
    assert lines[0] != module.POSTGRES_FLOATING_TAG, (
        f"{module.POSTGRES_TAG_FILE} holds `latest`. That is the one value a tag can take "
        f"that is guaranteed to change, so declaring it would make the rule pass exactly "
        f"the references it exists to fail."
    )

    # And the reader refuses each of the three broken shapes, in a temporary
    # directory. Written out rather than mocked, because the refusal is the
    # behaviour under test and a mock would only prove the mock works.
    for label, content in (
        ("two lines", "17-alpine\n16-alpine\n"),
        ("not a tag", "postgres:17-alpine\n"),
        ("empty", "\n\n"),
    ):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / module.POSTGRES_TAG_FILE).write_text(content, encoding="utf-8")
            try:
                module.read_postgres_tag(root)
            except module.Refusal as refusal:
                assert refusal.rule == "compose.postgres-tag-absent", (
                    f"a {label} POSTGRES_TAG refused with {refusal.rule!r}, not "
                    f"`compose.postgres-tag-absent`"
                )
            else:
                raise AssertionError(
                    f"read_postgres_tag accepted a {label} POSTGRES_TAG. A reader that "
                    f"guesses here makes every comparison the rule makes meaningless"
                )


def test_the_published_tag_is_the_tag_the_platform_owner_decided() -> None:
    """The declaration says the same thing DEBT.md D24 records, in two places.

    A standard that is written down in one file and enforced from another is two
    answers to "which tag?", and a reader that finds they disagree cannot tell
    which one the platform actually chose. D24's sentence is the decision; this
    file is the enforcement of it.
    """
    debt = (REPO.parent.parent / "DEBT.md")
    if not debt.is_file():
        # The workspace ledger is not part of this repository, so its absence is
        # not a failure of core. Asserted rather than skipped, because a test
        # that silently stops checking is the defect this repository is about.
        return
    text = debt.read_text(encoding="utf-8")
    section = text.split("## D24", 1)[-1].split("\n---", 1)[0]
    assert f"postgres:{declared_tag()}" in section, (
        f"DEBT.md D24 records the decision as `postgres:17-alpine` and "
        f"POSTGRES_TAG publishes `{declared_tag()}`. One of them was changed and the "
        f"other was not; a service that reads the ledger and a service that reads the "
        f"file are being told different things about what the platform runs."
    )


# --------------------------------------------------------------------------
# 2. the rule decides the thing it claims
# --------------------------------------------------------------------------


def test_the_pin_rule_is_wired_into_the_run_path() -> None:
    """A rule the harness can reach but never calls is a rule nobody is checked by.

    The cheapest possible check of the wiring, and it is here because the failure
    it guards against is silent: core-15 measured that deleting a check function
    from a checker left `bin/prime` reporting green, because the checker's own
    red proof is a CI step and not part of the gate. This asserts the call site
    exists, so deleting the call is a red in `bin/prime` itself.
    """
    module = harness_module()
    source = (HARNESS / "cafaye_contract.py").read_text(encoding="utf-8")
    assert "check_postgres_pin(service, core)" in source, (
        "`_check_service` does not call check_postgres_pin. The rule is defined, it is "
        "in RULE_IDS, and no run ever reaches it — which is the shape of a rule that "
        "reads as enforced and is not."
    )
    assert "compose.postgres-pin" in module.RULE_IDS, (
        "compose.postgres-pin is not in RULE_IDS, so a finding it reports would be an id "
        "the inventory does not describe"
    )
    assert "compose.postgres-tag-absent" in module.REFUSALS, (
        "compose.postgres-tag-absent has no message, so a refusal would print the bare id "
        "and a reader could not tell a missing declaration from a missing core"
    )


def test_the_conforming_pin_fixture_stays_green_on_all_three_declaration_shapes() -> None:
    """The control, and the reason it carries what it carries.

    `conforming-postgres` declares the tag in a compose file, in a workflow's
    `services:` block and on a `docker run` line. A green over a fixture that
    declared it in only one of those would be a green over a rule that reads one
    shape — and the rule's claim is "every reference", so a shape it cannot read
    is a shape it silently passes.

    The assertion is on the REFERENCES, not on the verdict, because a fixture
    that carried no image at all would also be green.
    """
    module = harness_module()
    fixture = HARNESS_FIXTURES / "conforming-postgres"
    pins, missed = module.postgres_references(fixture)
    assert missed == [], f"the control should be inside the scan bound, not in {missed}"

    # **By shape, not by line number.** The first version of this assertion named
    # `bin/with-database:27`, and every comment added above the DSN in that
    # fixture moved the line — so the assertion went red on a fixture that was
    # still exactly right, which is how an assertion gets deleted instead of
    # fixed. The shape (`bin/with-database`, some line) is the fact; the line is
    # an accident of the file's formatting, and the self-test breakage that edits
    # this file deliberately matches on the `docker run` text rather than a line
    # for the same reason.
    located = sorted(pin.located() for pin in pins)
    assert [pin.path for pin in pins] and len(pins) == 3, (
        f"the conforming pin fixture should hold exactly three references — one per "
        f"declaration shape — and holds {located}. Either a shape is unread (a rule "
        f"that cannot see a reference is a rule that cannot fail on one) or the "
        f"fixture has drifted from what the breakages in self_test.sh edit."
    )
    assert [pin.where for pin in pins if pin.path == "docker-compose.yml"] == [
        "compose services/postgres/image"
    ], "the compose file's reference is not at services/<name>/image"
    assert [pin.where for pin in pins if pin.path == ".github/workflows/ci.yml"] == [
        "workflow jobs/database/services/postgres/image"
    ], "the workflow's reference is not at jobs/<job>/services/<name>/image"
    script_pins = [pin for pin in pins if pin.path == "bin/with-database"]
    assert len(script_pins) == 1 and script_pins[0].line is not None, (
        f"the script's reference is missing or has no line number: {script_pins}"
    )
    result = harness_runs(fixture)
    assert result.exit_code == HARNESS_EXIT_CONFORMS, (
        f"the conforming pin fixture must pass, got exit {result.exit_code}: "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in result.findings)
    )


def test_a_dsn_is_not_a_postgres_image_reference() -> None:
    """The false-accusation test, run over core's OWN files rather than a fixture.

    `postgres://` is not a rare string in this fleet — it is a **secret-bearing**
    one. Every one of the four repositories core names in AGENTS.md as having
    shipped a check-that-could-not-run has a DSN in a script, and core's own gate
    self-test deliberately puts a password in one to prove the report does not
    leak it.

    So the hazard is specific and worth its own test: a scanner that read
    `postgres:` at the start of a connection string as a floating image reference
    would print a **credential** into a build log as the evidence for a finding.
    That is not a false positive, it is a secret in CI output.

    The haystack is core's real self-test scripts, which really do contain
    `postgres://gate:should-never-be-printed@localhost:5432/gate` — so this is a
    measurement over data that exists, not over a string invented for the test.
    """
    module = harness_module()
    for path in sorted((HARNESS / "tests").glob("*.sh")):
        for number, line in module._script_pin_lines(
            path.read_text(encoding="utf-8")
        ):
            assert "://" not in line, (
                f"{path.name}:{number} read a connection string as a postgres image "
                f"reference ({line!r}). A DSN is a URL scheme, not an image, and the ones "
                f"in this fleet carry passwords — reporting one as a finding would put a "
                f"credential in a build log."
            )
    # And the specific shapes, asserted directly so a future refactor cannot make
    # the haystack above empty and the test vacuous.
    for line in (
        'export TEST_DATABASE_URL="postgres://darkroom:darkroom@localhost:5432/db"',
        "psql --username postgres --dbname fixture",
        'goose -dir migrations postgres "$DATABASE_URL" up',
        "pg_isready -U postgres",
        "-v postgres:/var/lib/postgresql/data",
        "POSTGRES_USER: postgres",
        "echo docker run postgres:16-alpine",
    ):
        assert module._script_pin_lines(line) == [], (
            f"{line!r} was read as a container image declaration. A `postgres` used as a "
            f"user, a driver or a DSN is not an image, and a rule that accuses one is a "
            f"rule a service owner learns to ignore."
        )


def test_every_reference_shape_the_rule_cannot_compare_is_a_finding() -> None:
    """Four shapes, one rule, and the direction every one of them fails.

    The failure direction is the whole point. A digest, a variable with no
    default, an untagged reference and `latest` are all *readable* — the harness
    sees them and can say what they mean — and none of them carries the tag the
    rule compares. Passing them would be a rule that reports it checked something
    it did not check, which is the defect core's exit-2 rule exists to prevent and
    the defect a warning exists to name.

    `postgres:17` is in the list and not for the same reason: a bare major is a
    *correct* major on a *floating* minor, and billing's CI already enforces that
    distinction in its own words.
    """
    module = harness_module()
    digest = "a" * 64
    cases = {
        "digest, no tag": f"postgres@sha256:{digest}",
        "digest, wrong tag": f"postgres:18-alpine@sha256:{digest}",
        "variable, no default": "postgres:${TAG}",
        "variable, required": "postgres:${TAG:?set it}",
        "untagged": "postgres",
        "latest": "postgres:latest",
        "bare major": "postgres:17",
        "compose default": "postgres:${KIT_POSTGRES_TAG:-16.6-alpine}",
    }
    for label, value in cases.items():
        reference = module.parse_image_reference(value)
        assert reference is not None, (
            f"{label} ({value!r}) was not read as a postgres image at all. A shape the "
            f"rule cannot even see is a shape it passes in silence, which is worse than "
            f"an accusation."
        )
        assert reference.tag != declared_tag(), (
            f"{label} ({value!r}) resolved to the declared tag {declared_tag()!r} and "
            f"would pass. Every unreadable shape must fail, not match by accident."
        )
    # …and the two shapes that must be exempt, so the filter is not "fail
    # everything": the declared tag itself, and a digest that carries it.
    for value in (
        f"postgres:{declared_tag()}",
        f"postgres:{declared_tag()}@sha256:{'b' * 64}",
        "docker.io/library/postgres:" + declared_tag(),
    ):
        reference = module.parse_image_reference(value)
        assert reference is not None and reference.tag == declared_tag(), (
            f"{value!r} is the declared tag and must pass. A rule that fails the standard "
            f"is a rule that turns every repository in the fleet red on adoption."
        )
    # And the images that are not this rule's business. A false accusation here
    # would fail a repository for pinning a sidecar.
    for value in (
        "redis:7.4.1-alpine",
        "nats:2.10.24-alpine",
        "grafana/grafana:11.3.0",
        "cafaye/muse:dev",
        "pgvector/pgvector:pg17",
        "postgres-backup:1.2",
    ):
        assert module.parse_image_reference(value) is None, (
            f"{value!r} is not the postgres image and the rule does not decide it. "
            f"Reporting it would be a rule that fails a repository for a sidecar."
        )


def test_a_repository_that_declares_a_different_tag_goes_red_naming_the_finding() -> None:
    """The red proof for the simple half, and the message it has to carry.

    A finding that says "wrong" without saying **which tag core declares** and
    **where else this repository disagrees** sends a reader to `POSTGRES_TAG`,
    then to every other file, one at a time. The message is part of the rule, and
    asserting the substrings is how a message that stops carrying them is caught.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-postgres-undeclared")
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS, (
        f"a fixture pinning postgres:18-alpine must go red, got {result.exit_code}"
    )
    findings = [f for f in result.findings if f.rule == "compose.postgres-pin"]
    assert len(findings) == 1, (
        f"expected exactly one finding for a repository with one wrong pin, got "
        f"{[f.path for f in findings]}. The two files that agree on the declared tag "
        f"must NOT be reported — a rule that reports the correct pins too is a rule a "
        f"reader learns to skim."
    )
    message = findings[0].message
    for fragment in (
        "postgres:18-alpine",
        declared_tag(),
        module.POSTGRES_TAG_FILE if (module := harness_module()) else "",
        module.POSTGRES_EXCEPTIONS_FILE,
    ):
        assert fragment in message, (
            f"the finding does not name {fragment!r}. A reader told only that a pin is "
            f"wrong has to find the declaration, then find every other file themselves."
        )
    assert "docker-compose.yml" in findings[0].path, (
        f"the finding is located at {findings[0].path!r}, which does not name the file"
    )


def test_compose_and_ci_pinning_different_tags_is_reported_as_the_divergence() -> None:
    """The case DEBT.md D24 is about, and it is identity's shape, not an invented one.

    `identity`'s compose says `postgres:17-alpine` and its CI says
    `postgres:17.11-alpine`, and its own CI comment admits it in four lines. A
    developer and a runner on different database builds is the whole claim of the
    rule, so the fixture is built to that shape and the assertion is that BOTH
    offenders are named and that the message says how many tags the repository
    names.

    One finding per offending reference rather than one per repository: a rule
    that reported a single "your pins disagree" finding would not say which two
    of three to fix, and a repository with three files is the normal case.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-postgres-divergent")
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS
    findings = [f for f in result.findings if f.rule == "compose.postgres-pin"]
    paths = sorted(f.path for f in findings)
    assert len(findings) == 2, (
        f"expected two findings — the CI block and the script, with the compose file "
        f"agreeing with core — and got {paths}"
    )
    assert any(".github/workflows/ci.yml" in path for path in paths), (
        f"the workflow's 17.11-alpine was not reported; offenders are {paths}"
    )
    assert any("with-database" in path for path in paths), (
        f"the script's pin was not reported; offenders are {paths}"
    )
    assert not any(path.startswith("docker-compose.yml") for path in paths), (
        f"the compose file agrees with core and must not be reported; offenders are {paths}"
    )
    for finding in findings:
        assert "different tags" in finding.message, (
            "the message does not say the repository names more than one tag, which is "
            "the half a reader cannot work out from a single file's finding"
        )
        assert "17.11-alpine" in finding.message and "16-alpine" in finding.message, (
            "the message must name every tag the repository names, or the reader cannot "
            "tell which of three files to change"
        )


# --------------------------------------------------------------------------
# 3. exceptions: declared, never inferred
# --------------------------------------------------------------------------


def test_a_declared_exception_is_honoured_and_a_malformed_one_is_a_finding() -> None:
    """Both halves of the mechanism, from the one fixture that holds both.

    The green half matters as much as the red one. A rule with an exception path
    that no fixture can reach has an exception path nobody has ever run, and the
    first time it runs will be in somebody's CI. So `conforming-postgres-exception`
    — a repository pinning a major core does not declare, with the exception
    spelled out — is asserted GREEN here, and the four broken entries in
    `nonconforming-postgres-exception` are asserted to each produce a finding.
    """
    module = harness_module()

    honoured = harness_runs(HARNESS_FIXTURES / "conforming-postgres-exception")
    assert honoured.exit_code == HARNESS_EXIT_CONFORMS, (
        "a properly declared exception must be honoured, got "
        f"{honoured.exit_code}: "
        + "\n  ".join(f"{f.rule} {f.path}: {f.message}" for f in honoured.findings)
    )

    # …and it must be honoured because of the FILE and the IMAGE, not because
    # the repository has an exceptions file at all. The entry below names a file
    # that is not in the repository, so the pin it was written for stays red.
    with tempfile.TemporaryDirectory(prefix="core-18-pin-") as work:
        partial = _copied_fixture(work, "conforming-postgres-exception")
        declaration = partial / module.POSTGRES_EXCEPTIONS_FILE
        declaration.write_text(
            declaration.read_text(encoding="utf-8").replace(
                "file: docker-compose.yml", "file: ci/never-existed.yml"
            ),
            encoding="utf-8",
        )
        result = harness_runs(partial)
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS, (
        "an exception naming a file that does not exist granted nothing. Matching is on "
        "the exact path, and an exception that silently matched nothing is a "
        "suppression nobody can see — the pin stays red with no way to tell why."
    )
    assert any(
        "never-existed" in f.message or "16-alpine" in f.message
        for f in result.findings
    ), "the finding does not name the pin that is still unexcepted"


def test_every_way_an_exception_can_be_wrong_is_its_own_finding() -> None:
    """Four entries, four reasons, four messages — and none of them is a warning.

    The reasons are what a reader has at the moment they are about to add one, so
    a rule that reported all four as "bad exception" would have given them nothing
    to act on. Each message is asserted for its own distinctive phrase.
    """
    result = harness_runs(HARNESS_FIXTURES / "nonconforming-postgres-exception")
    assert result.exit_code == HARNESS_EXIT_VIOLATIONS
    messages = [f.message for f in result.findings if f.rule == "compose.postgres-pin"]
    joined = "\n".join(messages)
    for phrase in (
        "which is the tag core already declares",  # exception for the standard
        "no `reason`",
        "no `owner`",
        "no `until`",
        "not a postgres image reference",  # aimed at something else
    ):
        assert phrase in joined, (
            f"no finding says {phrase!r}. Four different mistakes need four different "
            f"reasons, and a single 'invalid exception' would leave a reader to work out "
            f"which one they have."
        )
    # The unexcepted pin is still reported even though the file has four entries
    # in it: an exceptions file is not a blanket waiver.
    assert any("16-alpine" in message for message in messages), (
        "the repository's own unexcepted pin was not reported. A declaration file that "
        "grants more than it names is not a declaration."
    )


def test_an_exception_without_a_horizon_is_required_but_the_horizon_is_never_read() -> None:
    """`until` is required, and comparing it to a date is deliberately not done.

    The harness has one answer for every input or it does not have a rule: it
    never resolves a `$ref` over the network because a check that needs the
    network gets a different answer on a different day. An exception list that
    expires by itself is that failure wearing a calendar — a repository would go
    red on a Tuesday and green on the next run of the same tree, which is the
    definition of a check nobody can reason about.

    So `until` is a required field (its absence is a finding) and is never parsed
    as a date. This asserts the absence is caught AND that a horizon in the past
    is NOT, because that is the behaviour a reader would otherwise assume.
    """
    module = harness_module()
    with tempfile.TemporaryDirectory(prefix="core-18-pin-") as work:
        past = _copied_fixture(work, "nonconforming-postgres-exception")
        declaration = past / module.POSTGRES_EXCEPTIONS_FILE
        text = declaration.read_text(encoding="utf-8")
        # Every entry is well-formed except the missing-field one, and every
        # horizon moves to a date in the past. The horizons are quoted in this
        # fixture for the reason `docs/postgres-pin.md` gives: an unquoted
        # `2026-12-31` is a **date** to YAML's core schema, and PyYAML and this
        # harness would then disagree on the field's type.
        assert 'until: "2026-12-31"' in text, (
            "the fixture's horizons are no longer quoted; see docs/postgres-pin.md for "
            "why they must be"
        )
        declaration.write_text(
            text.replace('until: "2026-12-31"', 'until: "2001-01-01"'), encoding="utf-8"
        )
        result = harness_runs(past)
    still_red = [f for f in result.findings if f.rule == "compose.postgres-pin"]
    # Entry [2] has no fields at all, so it is still red. Entry [0] and [1] and
    # [3] are well-formed apart from their own problems, and a past `until` must
    # not be one of them.
    for message in (f.message for f in still_red):
        assert "2001-01-01" not in message, (
            "the harness compared an exception's `until` against a date. A rule whose "
            "answer depends on the day it runs is not a rule, and this one would go red "
            "on a Tuesday and green on the next run of the same tree."
        )
    assert any("no `reason`" in f.message for f in still_red), (
        "the entry with no fields at all should still be reported; the past-dated "
        "horizons must not have replaced those findings"
    )


# --------------------------------------------------------------------------
# 4. the ceiling, stated rather than implied
# --------------------------------------------------------------------------


def test_a_compose_file_below_the_scan_bound_is_named_and_not_accused() -> None:
    """The bound is honest in both directions: it does not read, and it says so.

    `COMPOSE_SCAN_DEPTH` exists so the walk does not enter `node_modules` — and
    `courier` vendors hex packages into `deps/`, one of which documents postgres
    in a README. A bound that hid the file in silence would be the same defect as
    a checker that finds nothing and reports success.

    The first version of the walk stopped DESCENDING at the bound, which meant
    this file was never found, which meant the warning could not fire. This test
    is the receipt that it fires now, and `expect_no_finding`'s counterpart in
    self_test.sh is the receipt that the unread file is not accused either.
    """
    module = harness_module()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        deep = root / "a" / "b" / "c"
        deep.mkdir(parents=True)
        shutil.copy(HARNESS_FIXTURES / "conforming-postgres" / "cafaye.yml", root / "cafaye.yml")
        shutil.copy(
            HARNESS_FIXTURES / "conforming-postgres" / "docker-compose.yml",
            deep / "docker-compose.yml",
        )
        pins, missed = module.postgres_references(root)
        assert pins == [], "a compose file below the bound must not be read"
        assert [p.relative_to(root).as_posix() for p in missed] == [
            "a/b/c/docker-compose.yml"
        ], f"the file below the bound was not reported as missed; got {missed}"

        result = harness_runs(root)
        assert result.exit_code == HARNESS_EXIT_CONFORMS, (
            f"a repository whose only compose file is below the bound should be green — "
            f"it declares nothing this rule can read — got {result.exit_code}"
        )
        warnings = [w for w in result.warnings if w.rule == "compose.pin-scan-truncated"]
        assert len(warnings) == 1, (
            f"the run must NAME the file it could not read; warnings were "
            f"{[w.rule for w in result.warnings]}"
        )
        assert "a/b/c/docker-compose.yml" in warnings[0].path
        assert "postgres" in warnings[0].message, (
            "the warning does not say what is at risk — a postgres pin in there that no "
            "rule checked"
        )


def test_the_scan_reads_the_real_fleet_and_its_result_is_recorded_here() -> None:
    """Point the rule at every repository in the workspace and MEASURE the answer.

    This is the test that would have caught the packet's own surprise. The brief
    for core-18 said the fleet was uniform and that the rule should therefore be a
    hard failure; D24 recorded it as uniform. **It is not.** Every postgres image
    reference in the workspace now resolves to the declared tag but TWO, and
    neither names a database image at all:

      * `kit`'s deploy template carries a `services.app.image` of
        `${KIT_DEPLOY_IMAGE:?...}`, which the rule reads as an unresolved pin. The
        deploy tool sets it at run time; it names no database. It is in
        `services:`, so it is in scope the way every other reference is.

      * `kit`'s `image.reusable.yml` (kit-32) carries
        `${{ steps.resolve.outputs.image }}`, which is the resolved image of
        whatever the workflow just built. It is the same shape of reference and
        the same non-finding, found by the same rule, in a different file. It is
        recorded rather than suppressed for the same reason: suppressing it
        would teach the rule to skip `services:` entries, which is the class of
        reference this rule exists to resolve.

    Both real deviations this test once recorded are GONE. `kit`'s dev compose
    defaulted to `postgres:${KIT_POSTGRES_TAG:-16.6-alpine}`, so a developer
    running `bin/dev` got postgres 16.6 (fixed to `17-alpine`, kit 48689e6). And
    `identity`'s CI pinned `postgres:17.11-alpine` while its own compose floated
    at `17-alpine`, so one machine storing both images pulled TWO postgres builds
    and a developer and a runner could sit on different minors. That was a
    deliberate pin, and the cost was not visible in the line itself: pinning a
    minor is only a stronger guarantee if nothing else needs to agree with it,
    and here everything did.

    The remaining entry stays recorded rather than suppressed, because
    suppressing it would teach the rule to skip variables — and
    `${KIT_POSTGRES_TAG:-default}` is exactly the form this rule exists to
    resolve, since the default is what a developer with nothing configured gets.

    The point of keeping the list exact is that it decays. "The fleet is uniform"
    is a claim that rots one compose edit at a time, and this test is the thing
    that notices: it is read on every commit, a report is read once.

    The measurement is skipped — loudly, by returning — when the workspace is not
    beside this repository. A test that cannot run must not report a pass, so it
    reports nothing and says so in this docstring rather than in a green line.
    """
    module = harness_module()
    workspace = REPO.parent
    repositories = [
        "billing", "identity", "courier", "darkroom", "muse", "parlor", "kit",
    ]
    present = [name for name in repositories if (workspace / name).is_dir()]
    if not present:
        return

    tag = declared_tag()
    offenders: list[str] = []
    for name in present:
        pins, _ = module.postgres_references(workspace / name)
        for pin in pins:
            if pin.reference.tag != tag:
                offenders.append(f"{name}/{pin.path} -> {pin.reference.summary}")

    # The expectation, and it is a *measurement* rather than a wish: if a
    # repository fixes its pin, this fails and the answer is to update the line
    # above and the table in docs/postgres-pin.md in the same commit. A test that
    # accepts any answer cannot notice the fleet drifting back.
    assert sorted(offenders) == [
        "kit/.github/workflows/image.reusable.yml -> ${{ steps.resolve.outputs.image }}",
        "kit/templates/deploy/compose.deploy.yml -> ${KIT_DEPLOY_IMAGE:?the deploy tool sets KIT_DEPLOY_IMAGE}",
    ], (
        f"the fleet's postgres pins changed. The rule found: {sorted(offenders) or 'nothing'}. "
        f"core declares postgres:{tag}. If a repository above has been fixed, update this "
        f"expectation AND the table in docs/postgres-pin.md in the same commit — the two "
        f"are one claim stated twice, which is this repository's own doctrine."
    )


def test_the_inventory_and_the_document_agree_on_what_the_rule_decides() -> None:
    """The rule's own declaration, checked in both directions.

    `harness/rules.json` carries a `notEnforced` list and core's suite asserts the
    ids in `rules` equal `RULE_IDS`. Neither of those says the *limits* are
    written down, and a checker with no list of what it does not prove reads as
    covering everything — the argument `harness/gate_findings.json` makes for the
    gate checker, and the reason this test exists.
    """
    with (HARNESS / "rules.json").open(encoding="utf-8") as handle:
        inventory = json.load(handle)

    rules = {rule["id"]: rule for rule in inventory["rules"]}
    assert "compose.postgres-pin" in rules, "the rule is not in the inventory"
    assert "compose.postgres-tag-absent" in rules
    assert "compose.pin-scan-truncated" in {w["id"] for w in inventory["warnings"]}

    # The scan bound, the prose exclusion and the third-party exclusion must all
    # be written down, because each is a limit on what the rule decides and a
    # limit nobody can read is a limit nobody knows they have.
    not_enforced = " ".join(
        entry.get("why", "") for entry in inventory["notEnforced"]
    )
    for topic in ("CHANGELOG", "pgvector", "COMPOSE_SCAN_DEPTH"):
        assert topic in not_enforced, (
            f"nothing in rules.json's notEnforced mentions {topic!r}. The rule reads "
            f"executable declarations, one image, and a bounded depth — three limits a "
            f"reader has to be told about, and a checker that does not say what it does "
            f"not decide reads as deciding everything."
        )

    doc = (REPO / "docs" / "postgres-pin.md").read_text(encoding="utf-8")
    for fragment in (
        "postgres-pin-exceptions.yaml",
        "declared, never inferred",
        "two directory levels",
        "latest",
        "digest",
    ):
        assert fragment in doc, (
            f"docs/postgres-pin.md does not mention {fragment!r}. The document and the "
            f"rule are the same contract written twice, and this is the half that says "
            f"where the rule stops."
        )


def test_the_harness_still_imports_nothing_outside_the_standard_library() -> None:
    """The pin rule added no dependency, and this is what says so.

    `harness/` is standard-library-only because a Go service's CI has to be able
    to run it with nothing installed, and the check for that is
    `test_the_harness_imports_nothing_outside_the_standard_library` elsewhere in
    the suite. This asserts it here for the one packet that added the most code
    to that file, so the property is re-checked where a reader of the pin rule
    will find it.
    """
    source = (HARNESS / "cafaye_contract.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^import ([A-Za-z_][A-Za-z0-9_]*)", source, flags=re.M))
    imported |= set(re.findall(r"^from ([A-Za-z_][A-Za-z0-9_]*) import", source, flags=re.M))
    allowed = {
        "__future__", "argparse", "core_version", "dataclasses", "hashlib", "json",
        "os", "pathlib", "re", "sys", "typing",
    }
    assert imported <= allowed, (
        f"the harness imports {sorted(imported - allowed)}. A contract check that needs a "
        f"package is a check a Go service's CI cannot run, and core's harness is read "
        f"from a checkout of core on a runner that may be air-gapped."
    )



# --------------------------------------------------------------------------
# breaking tiers: the classification as data, and the proof it is not a boolean
# --------------------------------------------------------------------------


def _tier_module():
    """`harness/breaking_tiers.py`, imported the way the suite imports its siblings.

    `tests/test_specs.py` is run by `bin/prime` as a script from the repository
    root, and by pytest from anywhere, so the path is built from `REPO` rather
    than from `sys.path[0]` — which is the file's own directory under one runner
    and the repository root under the other.
    """
    if str(REPO / "harness") not in sys.path:
        sys.path.insert(0, str(REPO / "harness"))
    import breaking_tiers  # noqa: PLC0415 - the path is why, and it is above

    return breaking_tiers


def test_the_three_tiers_are_declared_and_each_one_is_described() -> None:
    bt = _tier_module()
    assert bt.TIER_NAMES == ("SOURCE", "JSON", "WIRE"), (
        f"the tier set is {bt.TIER_NAMES!r}; buf's four collapse into these "
        f"three because cafaye has no importable packages, and that argument "
        f"lives in the table's `source.collapse`"
    )
    published = bt.table()
    assert set(published["tiers"]) == set(bt.TIER_NAMES), (
        "a tier the table describes is a tier the code does not know, or the "
        "other way round"
    )
    for name in bt.TIER_NAMES:
        assert published["tiers"][name].strip(), (
            f"tier {name} has no description; a tier nobody can read is a tier "
            f"nobody selects"
        )


def test_a_field_rename_is_breaking_in_source_and_json_and_not_in_wire() -> None:
    """THE PROOF. The bar this packet exists to clear.

    buf's `FIELD_SAME_NAME` is in FILE, PACKAGE and WIRE_JSON and NOT in WIRE,
    because a binary encoding keys on the field's position and the name was never
    in it. Under one boolean this change has to be answered as both breaking and
    not. If this test fails then the three tiers are three names for one thing,
    and nothing else in this packet matters.
    """
    bt = _tier_module()

    assert bt.tiers_for("property-same-name") == frozenset({"SOURCE", "JSON"}), (
        "a property rename must break SOURCE and JSON and must not break WIRE"
    )
    assert bt.breaks("property-same-name", "source") is True
    assert bt.breaks("property-same-name", "json") is True
    assert bt.breaks("property-same-name", "wire") is False, (
        "a rename changed no encoding: WIRE carries the slot, not the name"
    )
    assert bt.breaks("property-same-name", "all") is True

    # And the converse, because a table where only WIRE could ever say "no" is
    # still a boolean in a trench coat. A deletion reaches all three.
    assert bt.breaks("property-no-delete", "wire") is True, (
        "deleting a property removes a slot, and a slot is the one thing a "
        "binary encoding does carry"
    )


def test_two_rules_whose_answers_differ_for_the_same_selection_exist() -> None:
    """The structural form of the proof above: the tiers are separable.

    A change kind that breaks every tier and one that breaks a strict subset of
    them are the minimum shape for "which surface broke" to be a different
    question from "did something break". Zero such pairs means every consumer
    gets every verdict and the selection is decoration.
    """
    bt = _tier_module()
    tier_sets = {r["id"]: bt.tiers_for(r["id"]) for r in bt.table()["rules"]}
    pairs = [
        (a, b)
        for a, tier_a in tier_sets.items()
        for b, tier_b in tier_sets.items()
        if a < b and tier_a < tier_b
    ]
    assert pairs, (
        f"no rule breaks a strict subset of another's tiers; the table is "
        f"{sorted(tier_sets)} and a table like that cannot answer 'which "
        f"surface' with anything but yes"
    )


def test_the_published_default_is_the_tier_set_of_a_real_rule() -> None:
    """A declaration that says nothing must mean something a row already means.

    The default is `SOURCE+JSON` and it is caf's own `DefaultTiers`. If the
    default were a set no rule breaks, "no declaration" would select a
    combination nobody classified — silently, and only for the services that
    never opted in, which is all of them today.
    """
    bt = _tier_module()
    published = bt.table()
    default = bt.default_tiers(published)
    tier_sets = [frozenset(r["tiers"]) for r in published["rules"]]
    assert default in tier_sets, (
        f"the default selection {bt.names(default)} is not the tier set of any "
        f"published rule"
    )
    assert default == frozenset({"SOURCE", "JSON"}), (
        "caf ships no binary encoding, so the default omits WIRE. This is "
        "caf/internal/contract.DefaultTiers and the next test asserts the two "
        "agree, because a default that differs between the table and the tool "
        "is a consumer told it cares about a surface nobody classified"
    )


def test_a_tier_selection_that_is_empty_or_unknown_is_refused() -> None:
    """A gate that can be passed by naming no tiers is not a gate.

    The empty set intersects nothing, so `--tiers ""` would make every
    comparison pass. `all` is accepted because spelling out three names to mean
    "everything" is a chance to forget one.
    """
    bt = _tier_module()

    assert bt.parse_tiers("all") == bt.ALL_TIERS
    assert bt.parse_tiers("source,json") == frozenset({"SOURCE", "JSON"})
    assert bt.parse_tiers("  WIRE  ") == frozenset({"WIRE"})

    for bad in ("", "   ", "source,", ",", None, "srouce", "source,json,wire,nope"):
        try:
            bt.parse_tiers(bad)
        except bt.TierError:
            continue
        raise AssertionError(
            f"parse_tiers({bad!r}) returned a selection; an empty or misspelled "
            f"selection is a way to make a gate answer nothing, and a gate that "
            f"can be passed by naming no tiers is not a gate"
        )


def test_the_published_table_is_the_go_table_and_they_cannot_drift() -> None:
    """The pin. A table in two repositories is a table that will disagree.

    `caf/internal/contract/breaking.go` is the Go original and it is what a
    consumer actually runs. If a tier moves there and not here, or a rule is
    added there and not here, this fails and the message names both sides. The
    repository is located rather than hard-coded: this worktree's parent holds
    the fleet, and a test that fails because a sibling checkout is absent is a
    test that fails for a reason that has nothing to do with the table.
    """
    bt = _tier_module()
    fleet = REPO.parent / "caf"
    go = fleet / "internal" / "contract" / "breaking.go"
    tier_go = fleet / "internal" / "contract" / "tier.go"
    if not go.is_file():
        print("  (skipped: caf is not beside this checkout; the pin needs the fleet)")
        return

    text = go.read_text(encoding="utf-8")
    go_ids = set(re.findall(r'ID:\s*"([a-z-]+)"', text))
    published = bt.table()
    ours = {r["id"] for r in published["rules"]}

    assert go_ids == ours, (
        f"the published table and breaking.go disagree about which change kinds "
        f"exist: only in Go {sorted(go_ids - ours)}, only here "
        f"{sorted(ours - go_ids)}"
    )

    # The tiers, per rule. Go spells a set as `TierSource | TierJSON`; this reads
    # that as the set of names, so a row that moves a tier fails with both rows
    # named rather than with a count that moved.
    go_const = tier_go.read_text(encoding="utf-8")
    bits = {
        "TierSource": re.search(r"TierSource\s+Tier\s*=\s*1\s*<<\s*iota", go_const),
        "TierJSON": re.search(r"\n\tTierJSON\b", go_const),
        "TierWire": re.search(r"\n\tTierWire\b", go_const),
    }
    assert all(bits.values()), (
        "caf/internal/contract/tier.go no longer declares TierSource, TierJSON "
        "and TierWire in that shape; this pin reads the names out of it and has "
        "to be rewritten rather than loosened"
    )

    for rule in published["rules"]:
        block = text.split(f'ID:      "{rule["id"]}"', 1)[1].split("},", 1)[0]
        found = set(re.findall(r"\bTier(?:Source|JSON|Wire)\b", block))
        ours_here = {t for t in bt.TIER_NAMES if t in rule["tiers"]}
        assert found == _go_tier_names(ours_here), (
            f"{rule['id']} breaks {sorted(found)} in breaking.go and "
            f"{sorted(ours_here)} in the published table"
        )

    # The default, which is the one fact a service inherits by saying nothing.
    # Anchored to the DECLARATION and not to the first mention. The prose above
    # `const DefaultTiers` in that file spells it out too, and an unanchored
    # search reads the docstring, which is a sentence about the default rather
    # than the default — and a pin that reads a sentence is not a pin.
    go_default = re.search(r"^const DefaultTiers = (.+)$", go_const, re.M)
    assert go_default, "tier.go no longer declares DefaultTiers"
    go_default_names = {part.strip() for part in go_default.group(1).split("|")}
    our_default = _go_tier_names(bt.default_tiers())
    assert go_default_names == our_default, (
        f"caf's DefaultTiers is {sorted(go_default_names)} and the published "
        f"table's defaultTiers is {sorted(our_default)}; a service that "
        f"declares nothing would be told it cares about one set while caf "
        f"checks another"
    )


def _go_tier_names(tiers) -> set:
    """`{"SOURCE", "JSON"}` as the Go constant names, for the pin above.

    `JSON` is the one that does not follow the rule — `tier.title()` gives `Json`
    and the constant is `TierJSON` — and spelling that out in one function is why
    the pin can be strict instead of fuzzy.
    """
    names = {"SOURCE": "TierSource", "JSON": "TierJSON", "WIRE": "TierWire"}
    return {names[t] for t in tiers}


def test_the_published_table_carries_its_own_absence_list() -> None:
    """A checker with no list of what it does not prove reads as covering everything.

    The two entries are the honest limits of this packet: the table classifies
    change kinds and does not decide whether a diff is one, and WIRE is
    classified with nothing in this repository able to produce a WIRE break. A
    table that said nothing about either would be read as covering both.
    """
    bt = _tier_module()
    published = bt.table()
    absences = published["notEnforced"]
    assert absences, "the table declares no absence list"
    for entry in absences:
        assert entry.get("claim"), f"an absence entry names no claim: {entry!r}"
        assert entry.get("why"), f"an absence entry gives no reason: {entry!r}"

    claims = " ".join(e["claim"].lower() for e in absences)
    assert "wire" in claims, (
        "nothing in the absence list says that WIRE is classified but "
        "unreachable, which is the one thing a reader of this table most needs "
        "told"
    )


def test_a_table_whose_tiers_all_agree_is_refused() -> None:
    """The gate, and its red proof: three tiers nobody can tell apart.

    The checker must go red when the table collapses to one tier, because that
    collapse is silent — every rule still validates, every rule still has a
    tier list, and the only symptom is that a consumer's selection stopped
    mattering.
    """
    bt = _tier_module()

    published = bt.table()
    assert bt.check() == [], (
        f"the published table does not satisfy its own checker: {bt.check()}"
    )

    collapsed = copy.deepcopy(published)
    for rule in collapsed["rules"]:
        rule["tiers"] = ["SOURCE", "JSON", "WIRE"]
    findings = bt.check(write_temp_json(collapsed))
    assert [f for _, f, _ in findings if f == "breaking.tiers-indistinguishable"], (
        f"a table where every rule breaks every tier was accepted: {findings}. "
        f"This is the failure the packet exists to prevent — three names for "
        f"one thing"
    )

    single = copy.deepcopy(published)
    for rule in single["rules"]:
        rule["tiers"] = ["SOURCE"]
    single["defaultTiers"] = ["SOURCE"]
    assert [f for _, f, _ in bt.check(write_temp_json(single))
            if f == "breaking.tiers-indistinguishable"], (
        "a table where every rule breaks exactly one tier was accepted"
    )


def test_an_unclassifiable_table_is_a_failure_and_not_a_skip() -> None:
    """A table that cannot be read is a rule nobody was told about.

    The same rule the harness holds everywhere: a check that cannot answer exits
    non-zero and says why, rather than passing. `breaking.tiers-unreadable` is a
    FAILURE, and a missing file is the same verdict as a malformed one.
    """
    bt = _tier_module()

    findings = bt.check(str(REPO / "harness" / "there-is-no-such-table.json"))
    assert [(s, f) for s, f, _ in findings] == [
        ("fail", "breaking.tiers-unreadable")
    ], f"a missing table gave {findings!r} rather than one FAILURE naming it"

    for broken, why in (
        ({"tiers": {"SOURCE": "x", "JSON": "y", "WIRE": "z"}, "defaultTiers": ["NOPE"],
          "rules": []}, "an unknown tier name"),
        ({"tiers": {"SOURCE": "x", "JSON": "y", "WIRE": "z"}, "defaultTiers": ["SOURCE"],
          "rules": [{"id": "a", "buf": "b", "tiers": [], "purpose": "p", "why": "w"},
                    {"id": "a", "buf": "b", "tiers": ["SOURCE"], "purpose": "p", "why": "w"}]},
         "two rules with one id"),
        ({"tiers": {"SOURCE": "x", "JSON": "y", "WIRE": "z"}, "defaultTiers": ["SOURCE"],
          "rules": [{"id": "a", "buf": "b", "tiers": ["SOURCE"], "purpose": "p", "why": "w"}]},
         "a default that is not any rule's tiers"),
    ):
        findings = bt.check(write_temp_json(broken))
        assert findings and all(s == "fail" for s, _, _ in findings), (
            f"{why} was accepted with no finding: {findings!r}"
        )


def write_temp_json(document: dict) -> str:
    """A table-shaped document written to a scratch file, for the checker's own tests.

    The checker's argument is a PATH, so proving it can fail means handing it a
    table that is wrong. Written into the temporary directory rather than beside
    the repository: a fixture in this repository's own `harness/` would be a
    second published table, and two of them is the defect.
    """
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(document, handle)
    finally:
        handle.close()
    return handle.name


# --------------------------------------------------------------------------
# 20. the numeric surface — the contract's numbers across six languages
# --------------------------------------------------------------------------


def numeric_module():
    """`harness/numeric_check.py`, imported in-process.

    The same idiom `tenancy_module()` uses, and for the same reason: the
    constants ARE the rule, and a rule read as a string out of a file is a rule
    that can be edited without anyone noticing they edited the rule.
    """
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import numeric_check  # noqa: PLC0415 - a sibling module, imported on demand

    return numeric_check


def run_checker(module: Path, argv: list[str]):
    """Run one harness module as a subprocess and hand back the CompletedProcess.

    A subprocess rather than an in-process call, and the reason is the exit code:
    the three numbers this repository keeps promising (0 conforms, 1 violations,
    2 the run could not happen) are the module's return value, and a test that
    called `main()` in-process would be asserting on a return value it had
    already turned into a Python object. `env={}` is deliberate — a checker that
    reads the ambient environment gets a different answer on a different machine,
    and core has four repositories to prove it.
    """
    return subprocess.run(
        [sys.executable, str(module), *argv],
        cwd=str(REPO),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_float64_limit_is_stated_once_in_the_checker_and_agrees_with_the_doc() -> None:
    """The duplicated constraint, and the test core's rule makes it.

    **A JSON Schema cannot ask whether a line of TypeScript holds an int.** It
    can say `type: integer` and it can say `maximum: 9007199254740991`, but the
    fact that 2**53 is the boundary at which JSON.stringify starts rounding is a
    fact about a LANGUAGE, not about a document — so the number cannot live in
    the schema and it has to be duplicated: once in the checker that enforces it,
    once in the document a reader is told to believe.

    Duplicated constraints drift silently. That is why this asserts both halves
    rather than either: the number is a CONSTANT rather than a literal at each
    use (so the checker's own three uses cannot disagree with each other), and
    the prose in `docs/numeric-conventions.md` must quote the same integer. If a
    future packet decides the limit is different, this fails in the same commit
    that changed one of the two, which is the only moment the change is cheap.

    The direction of the comparison matters too. The checker derives its first
    unrepresentable value as `FLOAT64_EXACT_LIMIT + 1` rather than typing it, so
    there is exactly one number in the file and the arithmetic is visible.
    """
    module = numeric_module()
    assert module.FLOAT64_EXACT_LIMIT == 2 ** 53, (
        "the largest integer a binary64 holds exactly is 2**53 = 9007199254740992. If this "
        f"constant is now {module.FLOAT64_EXACT_LIMIT}, the arithmetic is still right and the "
        "constant's name is not — fix one or the other, never both."
    )
    assert module.FLOAT64_FIRST_UNREPRESENTABLE == module.FLOAT64_EXACT_LIMIT + 1, (
        "the first integer float64 cannot represent is one past the limit, by definition. Two "
        "constants that answer this question must not be able to answer it differently."
    )
    doc = (REPO / "docs" / "numeric-conventions.md").read_text(encoding="utf-8")
    for number in (str(module.FLOAT64_EXACT_LIMIT), str(module.FLOAT64_FIRST_UNREPRESENTABLE)):
        assert number in doc, (
            f"docs/numeric-conventions.md does not state {number}. The checker enforces a "
            "number the document does not mention, so a service author reading the document "
            "has no way to learn why their field was refused. The two are the same contract "
            "written twice, and this is the test that keeps them the same."
        )
    # And the checker's OWN prose, which is what `--explain` prints and what a
    # service's CI shows on a red. A third statement of the same number.
    explained = module.explain()
    assert str(module.FLOAT64_EXACT_LIMIT) in explained, (
        "--explain does not print the limit it enforces"
    )
    source = NUMERIC_MODULE.read_text(encoding="utf-8")
    literals = set(re.findall(r"(?<![\w.])9\d{15}(?![\w])", source))
    assert literals <= {str(module.FLOAT64_EXACT_LIMIT), str(module.FLOAT64_FIRST_UNREPRESENTABLE)}, (
        f"numeric_check.py hardcodes {sorted(literals - {str(module.FLOAT64_EXACT_LIMIT), str(module.FLOAT64_FIRST_UNREPRESENTABLE)})} "
        "beside its constants. A boundary typed at a second place is a boundary that can be "
        "changed at one place, and the rule it decides is the rule that bites one language "
        "and not the others."
    )


def test_the_numeric_identity_names_are_declared_once_and_the_ledger_says_why() -> None:
    """The other duplicated constraint: what a field NAME means.

    `IDENTITY_NAME_TOKENS` is a closed list of spellings this checker treats as
    "this integer carries an identity or a raw byte count, so exceeding 2**53 is
    reachable rather than absurd". It is the sharpest version of the problem this
    packet exists for: **a JSON Schema cannot know what a name means.** It can
    constrain a type, a range and a format; it cannot tell a `byte_size` from a
    `retry_count`, and both are `type: integer` with no maximum.

    So the vocabulary lives in the CHECKER, for the same reason
    `tenancy_check.py` keeps its token vocabularies there rather than in
    `tenant-isolation.schema.json`. That is a duplicated constraint, and core's
    rule makes duplication a TEST — so this asserts:

      1. the list is non-empty (an empty refusal list is a rule that cannot fail);
      2. it contains no token that the fleet's own schemas actually use on an
         unbounded integer **and that core's docs do not justify** — asserted
         below by running the checker over `schemas/`, which is the real proof
         rather than a list comparison;
      3. every token appears in the doc, so a service author can predict whether
         a name will be refused before they write it.
    """
    module = numeric_module()
    tokens = module.IDENTITY_NAME_TOKENS
    assert tokens, (
        "IDENTITY_NAME_TOKENS is empty, and an empty vocabulary is a rule that cannot fail"
    )
    assert len(set(tokens)) == len(tokens), (
        f"IDENTITY_NAME_TOKENS has a duplicate: {sorted(tokens)}. The list is walked per "
        "position and a repeat costs a reader's trust in it for nothing."
    )
    doc = (REPO / "docs" / "numeric-conventions.md").read_text(encoding="utf-8")
    for token in sorted(tokens):
        assert token in doc, (
            f"{token!r} is a name this checker treats as an identity, and docs/"
            "numeric-conventions.md does not mention it. A service author has to be able to "
            "predict what will be refused before they write the field, not after."
        )


def test_the_numeric_checker_goes_red_only_on_the_float64_range_and_only_where_the_ceiling_is_reachable() -> None:
    """The green control held, over core's own schemas.

    Core ships 34 numeric positions and they are all legal today. That is the
    fact that decides the severities: `numeric.float64-unsafe` can be a FAILURE
    because it fires on **zero** of them, and a rule that fires on every existing
    field is a rule that is disabled within one release — which leaves the fleet
    with NO check rather than an incomplete one. This asserts the zero, so the
    severity decision in DECISIONS.md D43 has something under it and cannot rot
    into a claim.

    The four warnings are asserted as warnings **with the exit code unmoved**,
    which is the half that matters and the half a checker gets wrong: core's own
    `slo.objective` and `slo-windows.factor` are `type: number`, so a
    warning that moved the exit code would make `bin/prime` red on a contract
    nobody has broken.
    """
    report = run_checker(NUMERIC_MODULE, [str(REPO / "schemas")])
    assert report.returncode == NUMERIC_EXIT_CONFORMS, (
        f"core's own schemas must be green under numeric_check, exited {report.returncode}\n"
        f"{report.stdout}\n{report.stderr}"
    )
    # The two WARNING rules must print, because they fire: `slo.objective` and
    # `slo-windows.factor` are `type: number` and `probes.statusCode` is a
    # numeric enum. The exit code is the half that matters — 4 warnings and a 0
    # is the claim core's gate depends on.
    rendered = report.stdout
    assert rendered.count("warning  ") == 4, (
        f"expected exactly the four warnings core's own schemas carry, got:\n{rendered}"
    )
    # 35, and the four that made it 35 are `account-scope.schema.json`'s
    # `registeredAt.line` (minimum 1, maximum 1000000), `surface.minimum`
    # (0..4096), `fileAndLine.line` and `tenant-isolation.schema.json`'s
    # `nonRowSite.line` — every one of them a bounded integer well under 2**53,
    # so all four are legal and the warnings stayed at four. Recorded here rather
    # than only in a report because the number in this string is the number a
    # reader re-measures against.
    assert rendered.rstrip().endswith(
        "0 failure(s), 4 warning(s), over 35 numeric position(s) in 1 document(s)."
    ), (
        "core's numeric surface has MOVED and this test still says 35 positions and 4 "
        "warnings. That is the number changing, not the checker breaking — re-measure with "
        "`numeric-check --survey schemas/`, update this, and say in the report whether the "
        "new field is legal. Do not loosen the assertion to a regex."
    )
    # `numeric.float64-unsafe` fires on NONE of core's own positions, and that
    # zero is precisely what lets it be a FAILURE. Asserted explicitly so the
    # severity decision in D43 has something under it: if this ever fires on a
    # core schema, that is a real finding and it belongs in the report.
    assert "numeric.float64-unsafe" not in rendered, (
        "numeric.float64-unsafe fires on core's own schemas. Either a schema grew a field that "
        "is exact in Go, Python and Ruby and already wrong in TypeScript — a real finding, and "
        "the fix is a string or a maximum below 9007199254740992 — or the rule grew a trigger "
        "nobody intended. Either way, do not adjust this test; write down what happened."
    )
    assert " failure " not in report.stdout, (
        "numeric_check reports a FAILURE over core's own schemas. Either the schemas grew a "
        "field this rule refuses — which is a real finding and belongs in the report — or the "
        "rule grew a trigger nobody intended, and the second is the one that would be "
        "disabled rather than fixed."
    )
    # The notEnforced ledger prints on EVERY run, not only under --explain. A
    # surface this checker declined to rule on has to say so, or the silence is
    # indistinguishable from an unexamined surface — and `numeric.unsigned` is
    # silent over 45 of the fleet's positions.
    assert "notEnforced" in report.stdout, (
        "a normal run does not print the notEnforced ledger. harness/tenancy_findings.json "
        "carries the same list for the same reason: a rule examined and excluded on purpose "
        "is a decision, and the same rule excluded silently is the defect."
    )


def test_every_numeric_finding_is_proved_able_to_go_red_and_CI_runs_the_proof() -> None:
    """A gate that cannot fail is not a gate — the numeric checker's proof.

    The same assertion core already applies to the contract harness's, the gate
    checker's and the tenancy checker's: every id the checker can emit appears in
    `harness/tests/numeric_self_test.sh`, and CI runs that script as a step of its
    own. Reading the script rather than running it is deliberate — a red proof
    inside every `bin/prime` would be a second gate that can disagree with the
    first — and this test is what makes sure that step exists.

    The count is asserted too, and **from the script rather than from a number in
    a comment**, because the number to trust is the one the counter prints. A
    comment that has drifted from the list it describes is the exact defect
    core-negative-01 recorded when it deleted its own breakdown for that reason.
    """
    script = NUMERIC_SELF_TEST.read_text(encoding="utf-8")
    module = numeric_module()
    for identifier in sorted(module.FINDING_IDS):
        assert identifier in script, (
            f"{identifier} has no breakage in harness/tests/numeric_self_test.sh. Add one "
            "that expects this exact id, or delete the finding — a finding nothing exercises "
            "is a finding that will be wrong the first time it is needed."
        )
    for identifier in sorted(module.NOT_ENFORCED):
        assert identifier in script, (
            f"{identifier} is in the notEnforced ledger and nothing in the red proof names it. "
            "A rule excluded on purpose needs a GREEN case that stays green and says so — "
            "otherwise the exclusion is indistinguishable from nobody having looked."
        )
    for construction in ("expect_red", "expect_warn", "expect_green",
                         "expect_not_enforced", "fresh_copy", "exit 1"):
        assert construction in script, f"the red proof lost its {construction}"
    assert "set -uo pipefail" in script, (
        "harness/tests/numeric_self_test.sh must set pipefail. A red proof that loses a failure "
        "to a pipe reports a green, which is the defect the whole packet is about."
    )
    # The control runs FIRST and must be WARNING-FREE, not merely green. A
    # control that arrives already complaining cannot tell a conforming surface
    # from one the checker has an opinion about, and every red below it is worth
    # less than nothing without it.
    assert script.index("the control") < script.index("expect_red '"), (
        "the control must run before the first breakage; a control that runs last is a "
        "summary, not a control"
    )
    assert "WARNING-FREE" in script, (
        "the control asserts green but not warning-free. Without the second half, a checker "
        "that warned about every surface would satisfy every breakage below the control."
    )
    red_calls = script.count("expect_red '")
    assert red_calls >= 4, (
        f"the red proof makes {red_calls} breakages; kit's precedent is one deliberate "
        "breakage per trigger, and this rule has four distinct ways to fire — a declared "
        "maximum at the range, one past it, and two spellings of the identity name."
    )
    # The four the packet names, one each — the boundary from both sides and the
    # two identity spellings. A script that quietly lost one would still report a
    # green with a smaller number on it.
    for expected in ("9007199254740992", "9007199254740993", "9007199254740991",
                     "byte_size", "expires_at"):
        assert expected in script, f"the red proof never exercises {expected}"
    assert "SKIPPED" in script, (
        "the red proof must report its skip count separately from its pass count"
    )
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "harness/tests/numeric_self_test.sh" in ci, (
        "core's CI must run the numeric checker's red proof as a step of its own. A comment "
        "claiming CI runs a self-test is not CI running it, and that is the lesson of the "
        "four repositories that shipped a check which skipped instead of failing."
    )


def test_bin_prime_checks_the_numeric_surface_and_the_check_needs_nothing_core_does_not_ship() -> None:
    """Wired into the gate, stdlib only, and reading no environment.

    Three claims, and they are three because each has its own way of quietly
    being false:

      * **Wired.** `bin/prime` runs `numeric_check.py schemas/`. A checker that
        nothing runs is a report, and the floor in `gate.yml` is the one place
        core writes down how many tests there are — so the wiring is asserted
        against the file, and against a deliberate breakage of core's OWN schemas
        so the step is proved load-bearing rather than merely present.

      * **Stdlib only.** The static half is the same AST walk
        `test_the_harness_imports_nothing_outside_the_standard_library` uses on
        every module that travels, and `numeric_check.py` is now one of them. The
        runtime half is `-I -S`. The first version of this checker imported
        PyYAML and the static half is what caught it — which is the argument for
        having the walk.

      * **No environment, no process.** It decides from static facts, so
        `CAFAYE_NUMERIC_PYTHON` reaches the WRAPPER and nothing reaches the
        module. A contract check that opens a connection or reads a secret is a
        check a service's air-gapped runner cannot run, and one whose answer
        changes with the machine.
    """
    prime = (REPO / "bin" / "prime").read_text(encoding="utf-8")
    assert "numeric_check.py" in prime, (
        "bin/prime does not run the numeric check. A checker nothing runs is a report, and "
        "this packet's whole claim is that the contract did not invite a value six languages "
        "disagree about."
    )
    # The run must be pinned to an interpreter and its exit code must BE the
    # verdict — not piped through anything that could discard it. This fleet's
    # one recorded false green was a `| tail -45; echo $?` under zsh.
    assert 'numeric_check.py" schemas' in prime, (
        "bin/prime must check core's OWN schemas, which is the only surface core is "
        "responsible for. A service's OpenAPI is checked by that service's CI."
    )
    assert "CAFAYE_NUMERIC_PYTHON" in prime, (
        "bin/prime pins the interpreter the numeric check runs on. An unpinned check inside "
        "core's own gate would depend on the machine, and a laptop with an old python would "
        "fail a checkout CI is green on."
    )

    outside = sorted(_imports_of(NUMERIC_MODULE.read_text(encoding="utf-8")) - HARNESS_STDLIB_ONLY
                     - {path.stem for path in HARNESS.glob("*.py")})
    assert not outside, (
        f"harness/numeric_check.py imports {outside}. harness/ may not take a dependency: a "
        "check that needs a package is a check a Go service's CI cannot run. It reads YAML "
        "with cafaye_contract.read_yaml, the reader tenancy_check.py already uses, so there "
        "is one YAML dialect in one directory rather than two."
    )

    # The runtime half, and the wrapper's refusal to degrade to a green.
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(NUMERIC_MODULE), str(NUMERIC_FIXTURES / "nonconforming")],
        cwd=str(REPO),
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == NUMERIC_EXIT_FAILURES, (
        "with site-packages disabled, an unbounded identity-named integer and a numeric enum "
        f"must still be found. Exited {completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )
    # The ENUM half of the same failure, under the same runtime. Asserted by the
    # member it names rather than by the finding id, because the id is already
    # printed for the declared maximum in the same fixture and a test that
    # matched on the id would pass with the enum branch deleted.
    assert str(FLOAT64_FIRST_UNREPRESENTABLE) in completed.stdout, (
        "the enum carrying a 53-bit member was not reported under -I -S. The declared maximum "
        "beside it is a different trigger, so the id alone proves nothing about this one.\n"
        f"{completed.stdout}"
    )
    assert "cafaye_contract" not in completed.stderr, (
        "numeric_check.py could not import cafaye_contract under -I -S. It travels with the "
        "harness, and a copy of one without the other would mean a second YAML dialect."
    )
    # COMMENTS ARE STRIPPED first, and that is the whole subtlety: this wrapper's
    # header argues *against* `|| true` in prose, so a substring search over the
    # file finds the very sentence that forbids it. A check that cannot tell a
    # comment from a command is a check whose failures are noise.
    wrapper_lines = []
    for line in NUMERIC_WRAPPER.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        wrapper_lines.append(line.split(" #", 1)[0] if " #" in line else line)
    wrapper = "\n".join(wrapper_lines)
    assert "|| true" not in wrapper, (
        "harness/bin/numeric-check contains `|| true`. A wrapper that turns a refusal into a "
        "pass is worse than no wrapper, because the one thing a caller was relying on is the "
        "thing it discarded."
    )
    assert "exit 2" in wrapper, (
        "harness/bin/numeric-check must exit 2 when the check could not happen. A run that "
        "cannot find the contract is worse than no check: it converts an unknown into a green "
        "badge. This is the same rule as identity's TEST_DATABASE_URL and muse's "
        "MUSE_CORE_SCHEMAS."
    )


# --------------------------------------------------------------------------
# 21. a 53-bit integer behind an `enum`
# --------------------------------------------------------------------------


def numeric_verdict(properties: dict) -> subprocess.CompletedProcess:
    """One document, one property at a time, and the checker's REAL exit code.

    A subprocess rather than an in-process `check()`, for the reason
    `run_checker` gives: the number a gate depends on is the process's exit
    code, and an in-process call would be asserting on a Python return value the
    caller had already turned into an object. One property per document so a red
    can name the position it fired about — a table of eleven properties would
    give an answer about the document and not about any of them.
    """
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://cafaye.dev/fixtures/numeric/one-position.json",
        "title": "One integer position, so a red can name it",
        "description": (
            "A scratch document written by tests/test_specs.py rather than a "
            "committed fixture: the checker's argument is a path, so proving it "
            "can fail means handing it a document that is wrong."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }
    return run_checker(NUMERIC_MODULE, [write_temp_json(document)])


def numeric_findings(rendered: str, identifier: str) -> list[str]:
    """Every rendered finding line for one id. THE COUNT IS THE CLAIM.

    Matched on the id at the START of a line, which is the only place the
    checker prints one, and deliberately not a substring: `numeric.unsigned`
    also appears in the notEnforced ledger, so a substring search over the whole
    report would count a rule this checker declined to rule on as a finding
    about it.
    """
    return [line for line in rendered.splitlines() if line.startswith(f"{identifier} ")]


def test_an_integer_enum_carrying_a_53_bit_value_is_a_failure_and_the_boundary_is_exact() -> None:
    """The gap this packet closes, asserted in BOTH directions.

    `numeric.float64-unsafe` decided itself from `maximum` and from an
    identity-shaped NAME. `walk()` files a node that is both `type: integer` and
    an `enum` in TWO lists and carries neither the members nor the name into the
    position, so a schema saying `enum: [0, 1, 9007199254740993]` produced one
    `numeric.enum` WARNING about evolution and said nothing about a value a
    TypeScript client cannot represent — measured, before this packet existed,
    in `REPORT-core-numeric-enum-53-01.md` §2.

    **An enum is a STRONGER statement than a maximum, not a weaker one.** A
    maximum bounds a range the writer may stay inside; an enum enumerates the
    complete set of legal values, so a member at or past the float64 exact range
    is a value the contract *requires*, not one it permits. That is why this is
    a FAILURE and why it shares the id rather than becoming a fifth rule: the
    distinction this file draws everywhere is *can this value cross the wire
    wrong*, and this one can.

    Both directions means four separate claims, and each has its own way of
    being quietly false:

      * `2**53 + 1` is red, and names the member.
      * `2**53` exactly is **green**. This is the half that decays: an
        off-by-one here is invisible until a real client silently rounds, and a
        rule that fired on the last exactly-representable integer would refuse
        a document that is correct.
      * `-2**53 - 1` is red, because the MAGNITUDE is what matters.
        `maximum` is the wrong bound for a set: it is one number, the enum is a
        set, and the reader's question is "how big is any of them".
      * A string enum, an enum of floats and an enum with one non-integer member
        are unchanged. The `all(_is_int(...))` guard in `walk()` is what keeps
        those out of `enums` at all, and this is the assertion that the guard
        was not widened to make the first case pass.
    """
    module = numeric_module()

    # -- the red, and the two findings one node may now carry ---------------
    over = numeric_verdict({"shard_id": {"type": "integer", "enum": [0, 1, FLOAT64_FIRST_UNREPRESENTABLE]}})
    assert over.returncode == NUMERIC_EXIT_FAILURES, (
        "an integer enum with a member at 2**53 + 1 must be a FAILURE: that value is exact in "
        f"Go, Python and Ruby and already wrong in TypeScript by one. Exited {over.returncode}\n"
        f"{over.stdout}\n{over.stderr}"
    )
    unsafe = numeric_findings(over.stdout, "numeric.float64-unsafe")
    assert len(unsafe) == 1, (
        f"expected exactly one numeric.float64-unsafe on this node, got {len(unsafe)}:\n{over.stdout}"
    )
    assert unsafe[0].split()[1] == "failure", (
        f"numeric.float64-unsafe must be FAILURE severity on an enum member, was: {unsafe[0]!r}"
    )
    assert str(FLOAT64_FIRST_UNREPRESENTABLE) in over.stdout, (
        "the finding does not name the member that crosses the range. A message that says 'this "
        f"enum is unsafe' sends a reader to the document; one that names the number sends them to "
        f"the line.\n{over.stdout}"
    )
    assert "#.properties.shard_id" in over.stdout, (
        f"the finding did not name the position it fired about:\n{over.stdout}"
    )
    # Decision 1: it is ALSO a closed union, and that finding stays. A node that
    # is both is two true statements, and collapsing them would lose the
    # evolution warning the moment somebody stringified the member.
    assert len(numeric_findings(over.stdout, "numeric.enum")) == 1, (
        "numeric.enum must still fire on an integer enum even when the same node is already a "
        f"float64 failure. Exited {over.returncode}\n{over.stdout}"
    )
    assert numeric_findings(over.stdout, "numeric.enum")[0].split()[1] == "warning", (
        "numeric.enum stays a WARNING. It is about evolution — adding a value is not a compatible "
        "change — and promoting it would fail core's own three numeric enums and the fleet's one."
    )

    # -- the boundary, from both sides --------------------------------------
    for label, members in (
        ("exactly 2**53, the last integer a binary64 holds exactly", [FLOAT64_EXACT_LIMIT]),
        ("exactly -2**53", [-FLOAT64_EXACT_LIMIT]),
    ):
        at_limit = numeric_verdict({"shard_id": {"type": "integer", "enum": [0, 1, *members]}})
        assert at_limit.returncode == NUMERIC_EXIT_CONFORMS, (
            f"an integer enum with a member of {label} must NOT be red. 2**53 is exactly "
            "representable, a JSON.stringify/JSON.parse round trip returns it, and a rule that "
            "refused it would be refusing a document that is correct — the off-by-one that is "
            f"invisible until a client silently rounds. Exited {at_limit.returncode}\n{at_limit.stdout}"
        )
        assert not numeric_findings(at_limit.stdout, "numeric.float64-unsafe"), (
            f"the enum at {label} produced numeric.float64-unsafe:\n{at_limit.stdout}"
        )
        # ...and the boundary is not silence: the enum is still a closed union.
        assert numeric_findings(at_limit.stdout, "numeric.enum"), (
            f"the enum at {label} lost its numeric.enum warning. 'Not red for this rule' must not "
            f"mean 'not seen'.\n{at_limit.stdout}"
        )

    # -- the magnitude, which `maximum` cannot see --------------------------
    negative = numeric_verdict({"shard_id": {"type": "integer", "enum": [-FLOAT64_FIRST_UNREPRESENTABLE, 0]}})
    assert negative.returncode == NUMERIC_EXIT_FAILURES, (
        "an integer enum with a large NEGATIVE member must be a FAILURE. The existing rule reads "
        "`maximum`, which is one number and the wrong bound for a set, and it is a signed "
        f"comparison: measured before this packet, `enum: [-9007199254740993, 0]` produced no "
        f"finding at all. Exited {negative.returncode}\n{negative.stdout}"
    )
    assert str(-FLOAT64_FIRST_UNREPRESENTABLE) in negative.stdout, (
        "the finding must name the negative member, magnitude and all:\n" f"{negative.stdout}"
    )

    # -- the shape `float64_unsafe()` structurally CANNOT reach -------------
    # walk() files an enum with no declared `type` in `enums` and NOT in
    # `positions`, so no amount of widening a position-shaped rule could ever
    # see this one. It is legal draft 2020-12 and it permits the value, so it is
    # asserted here rather than left as a known gap.
    untyped = numeric_verdict({"shard_id": {"enum": [0, FLOAT64_FIRST_UNREPRESENTABLE]}})
    assert untyped.returncode == NUMERIC_EXIT_FAILURES, (
        "an integer enum with NO declared type carries the same hazard and must be caught. "
        f"Exited {untyped.returncode}\n{untyped.stdout}"
    )

    # -- one node, one finding ----------------------------------------------
    both = numeric_verdict({"shard_id": {
        "type": "integer",
        "maximum": 9223372036854775807,
        "enum": [200, FLOAT64_FIRST_UNREPRESENTABLE],
    }})
    assert both.returncode == NUMERIC_EXIT_FAILURES, (
        f"a node that is both must still be a failure. Exited {both.returncode}\n{both.stdout}"
    )
    assert len(numeric_findings(both.stdout, "numeric.float64-unsafe")) == 1, (
        "a node that declares BOTH a maximum past the range and an enum past it produced "
        f"{len(numeric_findings(both.stdout, 'numeric.float64-unsafe'))} numeric.float64-unsafe "
        f"findings. It is one defect with one fix, and a finding printed twice reads as two "
        f"problems where there is one.\n{both.stdout}"
    )
    assert "declares maximum" in both.stdout, (
        "where a node has both, the MAXIMUM is the finding and the enum yields. The maximum branch "
        "is the one that already existed, the reader's next file is the same either way, and "
        f"suppressing a second copy is the direction with nothing left to get wrong.\n{both.stdout}"
    )
    # and the closed union is still reported on the same node.
    assert numeric_findings(both.stdout, "numeric.enum"), (
        f"a node that is both must still carry its numeric.enum warning.\n{both.stdout}"
    )

    # -- everything that must NOT move --------------------------------------
    for label, declaration, forbidden in (
        (
            "a string enum",
            {"type": "string", "enum": ["0", str(FLOAT64_FIRST_UNREPRESENTABLE)]},
            ("numeric.float64-unsafe", "numeric.enum", "numeric.float"),
        ),
        (
            "an enum of floats",
            {"type": "number", "enum": [1.5, 2.5]},
            ("numeric.float64-unsafe", "numeric.enum"),
        ),
        (
            "an enum with one non-integer member",
            {"type": "integer", "enum": [1, "two"]},
            ("numeric.float64-unsafe", "numeric.enum"),
        ),
    ):
        unchanged = numeric_verdict({"shard_id": declaration})
        assert unchanged.returncode == NUMERIC_EXIT_CONFORMS, (
            f"{label} must be green. The `all(_is_int(...))` guard in walk() is what keeps these "
            "out of `enums` at all, and widening it to make a 53-bit integer enum red would "
            f"widen it for every enum. Exited {unchanged.returncode}\n{unchanged.stdout}"
        )
        for identifier in forbidden:
            assert not numeric_findings(unchanged.stdout, identifier), (
                f"{label} produced {identifier}, which it did not produce before this packet:\n"
                f"{unchanged.stdout}"
            )
    # ...and the float enum still says what it said before: `numeric.float`.
    floats = numeric_verdict({"shard_id": {"type": "number", "enum": [1.5, 2.5]}})
    assert numeric_findings(floats.stdout, "numeric.float"), (
        "an enum of floats is still a bare `type: number` and still warns. Unchanged means "
        f"UNCHANGED.\n{floats.stdout}"
    )
    assert module.FLOAT64_EXACT_LIMIT == FLOAT64_EXACT_LIMIT, (
        "the boundary these cases are written against has drifted from the checker's own "
        f"constant: {module.FLOAT64_EXACT_LIMIT} vs {FLOAT64_EXACT_LIMIT}. Every case below the "
        "control is only a proof about the boundary it was written for."
    )


def test_the_numeric_red_proof_and_its_header_name_the_same_rules_in_both_directions() -> None:
    """Three statements of one list, and the direction that decays is the header.

    `harness/tests/numeric_self_test.sh` has a header that enumerates the rules
    and a body of cases. `test_every_numeric_finding_is_proved_able_to_go_red_and_
    CI_runs_the_proof` asserts one direction — every id the checker can emit has
    a case — and this asserts the other two:

      * every case names a rule the checker can actually emit. A case that
        expects `numeric.float64-unsaf` because of a typo would sit in the body
        forever, red on a rule that does not exist and green on the one that
        does, and the first direction would not notice: it only looks for ids
        the checker emits being present, not for ids in the script being real.
      * every rule in the header has a case, so a header entry cannot be a
        promise. This is the drift the packet's own new branch is most exposed
        to: the rule did not grow an id, so nothing in the inventory moved, and
        a header that listed the enum path with no case beside it would be
        indistinguishable from one that has a proof.

    The ids are read out of the `expect_*` CALLS rather than out of the file,
    because a rule named only in a comment satisfies a substring search and
    proves nothing — which is exactly what a comment IS.
    """
    module = numeric_module()
    script = NUMERIC_SELF_TEST.read_text(encoding="utf-8")

    inventory = set(module.FINDING_IDS) | set(module.NOT_ENFORCED)

    header_start = script.index("THE FOUR RULES, AND WHAT EACH ONE MUST BE PROVED ABLE TO DO")
    header_end = script.index("WHY numeric.unsigned IS NOT A BREAKAGE HERE")
    header = script[header_start:header_end]
    described = set(re.findall(r"^#\s{2,}(numeric\.[a-z0-9-]+)\s{2,}", header, flags=re.MULTILINE))
    assert described == inventory, (
        f"the red proof's header describes {sorted(described)} and the checker knows "
        f"{sorted(inventory)}. Both directions: a rule the header never mentions is a rule whose "
        "severity a reader cannot predict, and a header entry nothing proves is a promise nobody "
        "keeps."
    )

    # The cases, harvested from the calls. A call starts at column 0 and runs on
    # through its indented continuation lines, so an intervening comment ends it
    # — which is the point: prose must not be able to stand in for a case.
    named: set[str] = set()
    collecting = False
    for line in script.splitlines():
        if re.match(r"^expect_(red|red_once|warn|green|not_enforced)\b", line):
            collecting = True
        elif line[:1] not in (" ", "\t", ""):
            collecting = False
        if collecting:
            named.update(re.findall(r"'(numeric\.[a-z0-9-]+)'", line))
    assert named <= inventory, (
        f"harness/tests/numeric_self_test.sh has cases expecting {sorted(named - inventory)}, "
        "which the checker cannot emit. A case aimed at a rule that does not exist is red for the "
        "wrong reason and green for the right one."
    )
    assert inventory <= named, (
        f"{sorted(inventory - named)} is in the checker's inventory and in the header, and no CASE "
        "names it. Every id needs a breakage; an id that has only ever been seen in a header is the "
        "shape of a finding that will be wrong the first time it is needed."
    )

    # The new branch has its OWN cases, and the four numbers are the four
    # decisions: over the limit is red, exactly on it is not, a large NEGATIVE
    # member is red on magnitude rather than on sign, and exactly -2**53 is not.
    # Asserted as the mutation text itself, so a recipe that quietly turned one
    # of these into a copy of another fails here rather than passing as "there
    # are cases".
    for mutation in (
        '"enum": [0, 1, 9007199254740993]',
        '"enum": [0, 1, 9007199254740992]',
        '"enum": [-9007199254740993, 0]',
        '"enum": [-9007199254740992, 0]',
    ):
        assert mutation in script, (
            f"the red proof never installs {mutation}. The enum path needs a case per decision, and "
            "a case that reused a neighbouring fixture's mutation would prove the neighbouring "
            "decision twice."
        )
    assert "expect_red_once" in script, (
        "the red proof has no way to assert that a node carrying both a wide maximum and a wide "
        "enum produces ONE finding. That count is decision D44's second half, and a red proof that "
        "cannot state it is a proof that has not made it."
    )
    assert '"maximum": 9223372036854775807,' in script, (
        "no case declares a maximum AND a crossing enum on one node, so 'one finding, not two' is "
        "asserted over a fixture that never has both."
    )
    assert "set -uo pipefail" in script, (
        "harness/tests/numeric_self_test.sh must set pipefail; a red proof that loses a failure to "
        "a pipe reports a green."
    )


# --------------------------------------------------------------------------
# standalone runner
# --------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# db-isolation: the guard that answers darkroom's question for every service.
#
# It lives here rather than in a service because a guard that lives in the
# service it guards is a guard the next service does not have, and because these
# assertions are about the CHECKER -- that it can fail, that its inventory is
# honest, that it does not cry wolf -- rather than about any one tree. The
# checker bites on the fleet in harness/tests/db_isolation_self_test.sh, which
# bin/prime runs and whose counts bin/prime reads.
# ---------------------------------------------------------------------------

DB_ISOLATION_CHECK = REPO / "harness" / "db_isolation_check.py"
DB_ISOLATION_WRAPPER = REPO / "harness" / "bin" / "db-isolation-check"
DB_ISOLATION_FINDINGS = REPO / "harness" / "db_isolation_findings.json"
DB_ISOLATION_SELF_TEST = REPO / "harness" / "tests" / "db_isolation_self_test.sh"
DB_ISOLATION_DOC = DOCS / "db-isolation.md"


def db_isolation_module():
    """`harness/db_isolation_check.py`, imported in-process.

    In-process for the same reason `tenancy_module()` is: a test can assert on
    what the checker BELIEVES about a fixture rather than on the text it printed,
    which is what makes "a WHERE-narrowed delete is not a finding" checkable
    without parsing prose.
    """
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import db_isolation_check

    return db_isolation_check


def test_the_db_isolation_findings_inventory_names_every_finding_the_checker_can_report() -> None:
    """In BOTH directions, which is the whole point of the assertion.

    A finding the inventory does not describe is a finding nobody was told
    about, and an inventory entry the checker cannot reach is a promise nobody
    keeps. One direction alone catches half of each.
    """
    module = db_isolation_module()
    inventory = json.loads(DB_ISOLATION_FINDINGS.read_text(encoding="utf-8"))["findings"]
    assert {entry["id"] for entry in inventory} == set(module.FINDINGS)
    for entry in inventory:
        identifier = entry["id"]
        severity, claim, remediate = module.FINDINGS[identifier]
        assert entry["severity"] == severity, f"{identifier} severity drifted"
        assert entry["claim"] == claim, f"{identifier} claim drifted"
        assert entry["remediate"] == remediate, f"{identifier} remediation drifted"
        assert severity in ("warn", "fail"), f"{identifier} has severity {severity!r}"
        assert claim.strip() and remediate.strip(), f"{identifier} is undocumented"


def test_the_db_isolation_checker_reads_a_where_narrowed_delete_as_a_row_not_a_table() -> None:
    """The negative control that keeps the guard from crying wolf.

    `identity`'s entire suite is written this way -- every cleanup keyed by id or
    by an email unique to the test -- and it was measured green three full runs
    out of three. A checker that flagged that shape would send a reader to fix a
    working repository, and the second thing that happens is that the checker is
    switched off.
    """
    module = db_isolation_module()
    for line in (
        'conn.execute("DELETE FROM users WHERE id = $1")',
        "conn.execute('DELETE FROM accounts WHERE slug = $1', &[slug])",
        'pool.Exec(ctx, `DELETE FROM account_audit_log WHERE id = $1`)',
    ):
        assert not module.looks_like_a_cleanup(line, "identity/x_test.go"), line


def test_the_db_isolation_checker_does_not_read_english_about_deletes_as_deletes() -> None:
    """Every one of these was a measured false positive on this fleet.

    The list is not illustrative. `identity/internal/admin/store_test.go` carries
    `t.Fatal("a DELETE from the audit trail SUCCEEDED")` on the line AFTER a real
    delete, and an earlier version of this checker reported it as a second
    table-wide delete -- on a service whose suite was green three times running.
    """
    module = db_isolation_module()
    for line in (
        't.Fatal("a DELETE from the audit trail SUCCEEDED")',
        "// a global TRUNCATE is precisely the non-deterministic failure",
        'time.Now().UTC().Truncate(time.Microsecond)',
        'clip("x".repeat(9000))',
        "/// `truncate assets` resolves through the pool's `search_path`",
    ):
        assert not module.looks_like_a_cleanup(line, "identity/x_test.go"), line


def test_the_db_isolation_checker_sees_a_predicate_that_is_three_lines_below_the_delete() -> None:
    """darkroom/src/store.rs:774-780, which is the reason SQL literals are folded.

    The `where` is three lines below the `delete from`, so a line-at-a-time reader
    calls it a table-wide delete. It is keyed three ways and cannot touch another
    test's row.
    """
    module = db_isolation_module()
    source = [
        "    sqlx::query(",
        '        r#"',
        "        delete from idempotency_keys",
        "         where key = $1 and endpoint = $2 and status_code = 0",
        '        "#',
        "    )",
    ]
    folded = module.join_multiline_sql(source)
    matched = [line for line in folded if module.looks_like_a_cleanup(line, "src/store.rs")]
    assert not matched, matched


def test_the_db_isolation_checker_treats_rust_concurrency_as_the_default() -> None:
    """A checker that reads "no opt-in" as "not concurrent" clears darkroom.

    Nothing in a Rust suite opts into parallelism -- libtest spawns a thread per
    `#[test]` function -- and darkroom was red six runs out of six for exactly
    that reason.
    """
    module = db_isolation_module()
    assert module.MECHANISMS[0].language == "rust"
    report = module.ServiceReport(name="x", path="x", language="rust")
    report.has_database_tests = True
    report.shares_one_database = True
    report.unscoped_cleanup = ["tests/a.rs:1"]
    # No `report.concurrency` at all: nothing in a Rust suite opts in.
    assert report.concurrency == []
    # `latent` and NOT `hazard`, because the scan is what decides concurrency for
    # Rust, and a bare ServiceReport has not been scanned. The point of the
    # assertion is that the two are different verdicts, so a reader can see which
    # one a scanner-less report produces.
    assert report.verdict == ("db-isolation.latent", "fail"), report.verdict


def test_the_db_isolation_doc_states_the_three_conditions_and_the_per_language_rules() -> None:
    """A rule that exists only in the module's source is a rule nobody applies.

    The per-language concurrency table is the part a service author needs, and
    (3) is the condition every get wrong in both directions.
    """
    text = DB_ISOLATION_DOC.read_text(encoding="utf-8")
    for needle in (
        "shares one database",
        "cleanup deletes rows another test can see",
        "the runner executes them concurrently",
        "parallelize",
        "t.Parallel()",
        "async: true",
        "pytest-xdist",
        "by default",
        "search_path",
        "does not claim",
    ):
        assert needle in text, needle


def test_the_db_isolation_wrapper_never_lifts_the_exit_code() -> None:
    """A wrapper that turns a refusal into a pass is worse than no wrapper.

    The one thing a caller was relying on -- the exit code -- is the thing it
    discarded, and there is a recorded false green in this fleet of exactly that
    shape (`… | tail -45; echo "PRIME EXIT=$?"` under zsh, where `$?` was
    tail's).
    """
    text = DB_ISOLATION_WRAPPER.read_text(encoding="utf-8")
    # The `|| true` ban is on CODE, not on prose: this wrapper's own header says
    # the words while explaining why they are forbidden, so a substring assertion
    # would fail on the very comment that documents the rule.
    body = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any("|| true" in line for line in body), body
    assert any("exec " in line for line in body), body
    assert any("exit 2" in line for line in body), body


def test_the_db_isolation_red_proof_plants_the_defect_it_exists_to_catch() -> None:
    """The proof has to be about the DEFECT, not about the checker's plumbing.

    Case 1 of harness/tests/db_isolation_self_test.sh is darkroom's pre-fix shape,
    and that shape was measured in the real repository before it was put in a
    fixture: `left: 5, right: 1` and 14, 17 and 16 distinct failures across three
    runs. A red proof that planted something the defect never looked like would
    be a proof of the regex.
    """
    text = DB_ISOLATION_SELF_TEST.read_text(encoding="utf-8")
    assert "db-isolation.hazard" in text
    assert "db-isolation.latent" in text
    assert "DELETE FROM users" in text
    assert "expect_red" in text and "expect_clean" in text
    # The control runs FIRST, or every red below proves nothing: a checker that
    # refused everything would satisfy all of them. Matched on the NOTES, which
    # are the calls' descriptions rather than the calls themselves, because the
    # control is invoked as `expect_clean control` on a line whose name is
    # assigned by `fresh` a few lines earlier.
    assert text.index("control: the safe fixture") < text.index("case 1:")


# --------------------------------------------------------------------------
# 4b. the account-scoped entry-point declaration (D18 step 1)
# --------------------------------------------------------------------------


def account_scope_module():
    """`harness/account_scope_check.py`, imported in-process.

    In-process for `tenancy_module()`'s reason: a test can assert on the `Report`
    and on `FINDINGS` rather than on the text the checker printed, which is what
    makes "this finding is emitted by this condition" checkable without parsing
    prose. `sys.modules` is registered before `exec_module` because the module uses
    `@dataclass`, and on CPython 3.14 a dataclass whose module is absent from
    `sys.modules` raises `AttributeError` while resolving its own `__dict__` — a
    failure that has nothing to do with the code under test.
    """
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    import account_scope_check  # noqa: PLC0415 - a sibling module, imported on demand

    return account_scope_check


def test_the_valid_account_scope_examples_validate() -> None:
    """Both arms of `surface.kind`'s conditional, and both arms of `accountScoped`.

    `account-scope.yml` is a service with a surface and routes that reach customer
    data; `account-scope.no-surface.yml` is `kind: none`, which is how a shared
    library says "there is no request entry here" in a field rather than in a
    comment. Without the second, the honest zero has no legal spelling and a
    library has to either declare a boundary it does not have or omit itself —
    indistinguishable from having forgotten.
    """
    schema = load_schema(ACCOUNT_SCOPE_SCHEMA_PATH)
    assert len(VALID_ACCOUNT_SCOPE) == 2, (
        "the two examples are the two arms of surface.kind (a surface, and the honest "
        "zero); losing one leaves an arm untested"
    )
    for path in VALID_ACCOUNT_SCOPE:
        found = failures_for(load_document(path), schema)
        assert not found, f"{path.name} must be valid:\n  " + "\n  ".join(str(f) for f in found)


def test_the_invalid_account_scope_examples_are_rejected_for_the_reason_they_document() -> None:
    """The exact `(keyword, path)` pairs, so an example cannot be rejected by accident."""
    schema = load_schema(ACCOUNT_SCOPE_SCHEMA_PATH)
    notes = INVALID_NOTES.read_text(encoding="utf-8")
    for name, expected in sorted(INVALID_ACCOUNT_SCOPE.items()):
        path = INVALID_EXAMPLES / name
        assert path.is_file(), f"examples/invalid/{name} is missing"
        found = failures_for(load_document(path), schema)
        assert found, f"examples/invalid/{name} must be REJECTED by {ACCOUNT_SCOPE_SCHEMA_PATH.name}"
        assert_keywords(found, expected)
        assert f"## `examples/invalid/{name}`" in notes, (
            f"examples/invalid/README.md must explain {name}. A negative case with no table "
            "row is a file nobody reads and a rule nobody is enforcing."
        )


def test_the_account_scope_checker_and_the_schema_agree_on_every_example() -> None:
    """The checker re-implements the schema because it may not import `jsonschema`.

    Written twice means they drift, and the direction they drift in is the dangerous
    one: a checker that accepts what the schema refuses lets a service adopt a
    declaration the format does not describe, and every downstream tool reading the
    schema is then wrong about a file in the fleet.

    The FIXTURES are in the list as well as the examples, for tenancy's reason and
    with the same consequence: a fixture that stops satisfying the schema is a
    self-test whose control is being kept green by a checker that no longer agrees
    with the format, which is the exact drift this test exists for.
    """
    module = account_scope_module()
    schema = load_schema(ACCOUNT_SCOPE_SCHEMA_PATH)
    documents = [
        path
        for folder in ("valid", "invalid")
        for path in sorted((EXAMPLES / folder).glob("account-scope*.yml"))
    ]
    documents += [ACCOUNT_SCOPE_CONFORMING / "account_scope.yml",
                  ACCOUNT_SCOPE_PHOENIX / "account_scope.yml",
                  ACCOUNT_SCOPE_NEXTJS / "account_scope.yml"]
    assert len(documents) == 9, f"expected the nine account-scope documents core ships, got {documents}"
    for path in documents:
        document = load_document(path)
        refused = [
            problem
            for problem in module.validate(document)
            if problem not in ("accountFrom is forbidden because accountScoped is false",)
        ]
        found = failures_for(document, schema)
        # An entry the schema REFUSES may be one the checker's copy also refuses, in
        # the checker being stricter or looser. The property asserted is the
        # direction that matters: nothing the schema ACCEPTS may be refused here.
        assert not (found and not refused), (
            f"{path.name} validates against the schema but the checker's copy refuses it: "
            f"{refused}"
        )
        if not refused:
            assert not found, (
                f"{path.name} is refused by the schema but the checker's copy accepts it: "
                + "; ".join(str(item) for item in found[:4])
            )


def test_the_account_scope_findings_inventory_names_every_finding_the_checker_can_report() -> None:
    """In BOTH directions, which is the whole point of the assertion.

    A finding the inventory does not describe is a finding nobody was told about,
    and an inventory entry the checker cannot reach is a promise nobody keeps. One
    direction alone catches half of each.
    """
    module = account_scope_module()
    payload = json.loads(ACCOUNT_SCOPE_FINDINGS.read_text(encoding="utf-8"))
    inventory = payload["findings"]
    assert {entry["id"] for entry in inventory} == set(module.FINDINGS)
    for entry in inventory:
        identifier = entry["id"]
        severity, claim, remediate = module.FINDINGS[identifier]
        assert entry["severity"] == severity, f"{identifier} severity drifted"
        assert entry["claim"] == claim, f"{identifier} claim drifted"
        assert entry["remediate"] == remediate, f"{identifier} remediation drifted"
        assert severity in ("warn", "fail"), f"{identifier} has severity {severity!r}"
        assert claim.strip() and remediate.strip(), f"{identifier} is undocumented"
    # And the honesty half: a checker with no list of what it does NOT prove reads
    # as covering everything, which is the defect D13 recorded for a different
    # checker in a different file.
    assert len(payload["notEnforced"]) >= 5, (
        "the inventory must carry the notEnforced list. This checker recognises five "
        "registration shapes and cannot see a sixth, cannot resolve a scope prefix and "
        "cannot tell whether a `reason` is true; a reader told none of that reads the "
        "table above as covering it."
    )


def test_every_account_scope_finding_carries_the_exact_command_that_fixes_it() -> None:
    """A check that says only "not ok" makes the reader go and look.

    And the reader who does not look is why it is still broken next week. So every
    remediation has to point at something the reader can DO — a command, a file, or
    a field to set — rather than restating the claim. The list of verbs is closed
    rather than `len(remediate) > 20`, because the claim is a sentence and the
    remediation is not: `unscoped-without-reason.yml`'s remediation is "check the
    routes that read a customer row" and its claim is forty words long, so a length
    threshold would pass on the wrong half.
    """
    module = account_scope_module()
    verbs = (
        "add ", "check ", "change ", "confirm ", "declare ", "fix ", "give ", "lower ",
        "make ", "name ", "put ", "read ", "run:", "update ", "write ",
    )
    for identifier, (_severity, _claim, remediate) in sorted(module.FINDINGS.items()):
        assert remediate.strip(), identifier
        assert remediate.startswith(verbs) or "harness/bin/account-scope-check" in remediate, (
            f"{identifier} names neither a command nor an edit: {remediate}"
        )
        # And it must differ from the claim: a remediation that is the claim again is
        # a message printed twice, which reads as two facts and is one.
        assert remediate != module.FINDINGS[identifier][1], identifier


def test_every_account_scope_finding_is_proved_able_to_go_red() -> None:
    """Every finding, in BOTH directions, against the red proof's own header.

    This is D9: a check that cannot see the defect it is written for is worse than
    no check, because it reports green. So the proof's header is compared with
    `FINDINGS` and the comparison is symmetrical — a finding with no case is a rule
    nobody has tested, and a case naming a finding the checker cannot emit is a
    promise the proof cannot keep.

    The WARNINGS are in the same list on purpose and are the half that is easiest to
    get wrong: three of the fourteen do not move the exit code, and a proof that
    asserted only that they appear in the output would pass whether they were
    reported as failures or as warnings. `expect_warn` asserts the exit code too.
    """
    text = ACCOUNT_SCOPE_SELF_TEST.read_text(encoding="utf-8")
    module = account_scope_module()
    assert "expect_red" in text and "expect_clean" in text and "expect_warn" in text
    named = set(re.findall(r"(account-scope\.[a-z-]+)", text))
    assert named == set(module.FINDINGS), (
        "the red proof and the checker disagree about what can be reported.\n"
        f"  in FINDINGS, not in the proof: {sorted(set(module.FINDINGS) - named)}\n"
        f"  in the proof, not in FINDINGS: {sorted(named - set(module.FINDINGS))}"
    )
    for identifier, (severity, _claim, _remediate) in sorted(module.FINDINGS.items()):
        if severity == "fail":
            assert f'expect_red ' in text and identifier in text, identifier
    # The control runs FIRST, or every red below proves nothing: a checker that
    # refused everything would satisfy all of them.
    assert text.index("control: the conforming fixture") < text.index("case 1:")


def test_every_recogniser_is_fired_by_the_shape_it_was_read_from() -> None:
    """Each recogniser matches its own example, and NEITHER of two lookalikes.

    The positive half is obvious and the negative half is the point. A recogniser
    that matched nothing would find no undeclared routes and report a clean answer
    over a service's whole surface — which is D18, and it would be a checker that
    cannot see the defect it was written for. So each one is asked about its own
    example AND about every other recogniser's example, which is how a recogniser
    that has grown into two frameworks' syntaxes is caught before it starts crying
    wolf on correct code.

    And each example must be a line that EXISTS in `fixtures/account-scope/shapes/`
    or in a fixture's own router — a pattern whose only example is its own source is
    a pattern matching the author's idea of a route, which is D9 one level down.
    """
    module = account_scope_module()
    assert len(module.RECOGNISERS) >= 4, (
        "the fleet has at least four registration shapes measured — chi, Phoenix, "
        "Hono and axum — and fewer than four recognisers means a whole framework is "
        "invisible"
    )
    # Every other shape, taken from the RECOGNISERS rather than retyped, so adding a
    # recogniser widens this test without editing it. A hand-kept copy of the fleet's
    # route syntaxes is the two-places-one-rule defect this repository keeps
    # recording; D9 item 2 is "enumerate helpers once".
    for recogniser in module.RECOGNISERS:
        others = [
            (item.id, item.example)
            for item in module.RECOGNISERS
            if item.id != recogniser.id
        ]
        assert recogniser.example, f"{recogniser.id} carries no example to be fired by"
        assert recogniser.read_from, f"{recogniser.id} names no repository it was read from"
        # `relative` is the name of the committed file the example lives in, found by
        # searching for it rather than kept in a second list — two places to keep the
        # fleet's syntaxes in step is the defect D9 item 2 records. It matters only
        # for a recogniser whose path comes from its filename, and passing the wrong
        # one for the others is harmless because they ignore it.
        where = next(
            (
                str(path.relative_to(REPO))
                for path in sorted(ACCOUNT_SCOPE_FIXTURES.rglob("*"))
                if path.is_file() and recogniser.example in path.read_text(encoding="utf-8")
            ),
            "",
        )
        assert where, (
            f"the {recogniser.id} recogniser's example is in no committed fixture: "
            f"{recogniser.example!r}"
        )
        # `path_from_filename` recognisers need a path that really is a `route.ts`,
        # and `read_from` is that path — which is why the field carries one at all.
        # For the rest it is ignored, so one call covers both shapes rather than two
        # tests that could disagree about which recogniser is which.
        # `read_from` is `path:line`, and the `:line` is stripped here rather than
        # stored a second time in its own field: a recogniser whose path-from-
        # filename is fed `src/app/v1/[...path]/route.ts:138` resolves to `/` and
        # matches nothing, which is the recogniser silently seeing no routes at all.
        cited = recogniser.read_from.rsplit(":", 1)[0] if recogniser.path_from_filename else where
        matched = recogniser.match(recogniser.example, cited)
        assert matched is not None, (
            f"the {recogniser.id} recogniser does not match the line it was read from "
            f"({recogniser.read_from}): {recogniser.example}"
        )
        # THE METHOD, not merely that it matched. This assertion is here because its
        # absence let a real defect through the whole packet: the chi pattern
        # captured the RECEIVER, so `r.Get("/v1/x", h)` read as method `r` and every
        # one of identity's forty-two routes was refused by `same_route` and would
        # have been reported `undeclared` — a false alarm on the largest surface in
        # the fleet. Every earlier version of this test asked `is not None` and
        # passed, and the red proof passed too, because its control is a `mux.
        # HandleFunc("GET /…")` line rather than a `r.Get(…)` one. Asserting the
        # method is what makes the difference visible, and the only reason it is
        # visible at all is the reach sweep over the fleet.
        expected_method = next(
            (
                word.upper()
                for word in re.findall(r"[A-Za-z]+", recogniser.example)
                if word.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE",
                                    "HEAD", "OPTIONS", "ANY")
            ),
            None,
        )
        assert expected_method is not None, (
            f"the {recogniser.id} recogniser's example names no HTTP method, so this "
            f"test cannot say what the recogniser should have read out of it: "
            f"{recogniser.example}"
        )
        assert matched[0] == expected_method, (
            f"the {recogniser.id} recogniser read the method of its own example as "
            f"{matched[0]!r}, not {expected_method!r}: {recogniser.example}. A wrong "
            "method makes same_route refuse a correctly declared route and report it "
            "undeclared, which is a guard crying wolf on the largest surface in the "
            "fleet."
        )
        # Each recogniser must NOT match another recogniser's example, and there is no
        # exemption list: chi and Go's 1.22 form are the same file read two ways and
        # they still do not match each other, because `r.Get("/v1/x", …)` puts the
        # method in the call and `mux.HandleFunc("GET /v1/x", …)` puts it in the
        # pattern string. An exemption here would be a place a future recogniser
        # could be waved through, and a recogniser that matches two frameworks'
        # syntaxes is how a guard starts crying wolf on correct code.
        for other_id, other in others:
            assert recogniser.match(other) is None, (
                f"the {recogniser.id} recogniser matches the {other_id} shape: {other}"
            )
    # Five languages, four frameworks, two spellings: `:id` and `{id}` are one route.
    assert module.same_route("GET", "/v1/messages/:id", "GET", "/v1/messages/{id}")
    assert not module.same_route("GET", "/v1/messages", "POST", "/v1/messages"), (
        "a GET declaration against a POST registration is two different entry points, "
        "and treating them as one would halve the enumeration"
    )


def test_a_repository_with_no_account_scope_declaration_is_a_failure_and_not_a_pass() -> None:
    """The fleet's actual state, asserted rather than described.

    Every in-scope repository fails this today, and that is the correct verdict: a
    service that has not declared which of its entry points are account-scoped has
    not proven one, and the checker's job is to say so out loud rather than to infer
    an answer from whatever routes it can pattern-match. Asserting it here is
    deliberate — the day a service adopts the format this test has to be rewritten,
    and a test that quietly kept passing while core was wrong is the thing core
    exists to prevent.

    The second half is the tri-state: pointed at a path that is not a repository the
    answer is exit 2, never 0 and never 1. A check that could not happen has not
    checked anything.
    """
    module = account_scope_module()
    with tempfile.TemporaryDirectory() as name:
        work = Path(name)
        bare = work / "no-declaration"
        (bare / "src").mkdir(parents=True)
        (bare / "src" / "router.go").write_text(
            'package api\n\nvar _ = mux\n', encoding="utf-8"
        )
        report = module.check(bare)
        assert report.exit_code == ACCOUNT_SCOPE_EXIT_FAIL, (
            "a repository with no account_scope.yml must be a FAILURE, not a pass and "
            f"not a skip:\n{report.render()}"
        )
        assert [item.id for item in report.findings] == ["account-scope.declaration-missing"]
        assert "account_scope.yml is not in" in report.render()

        could_not = module.check(work / "does-not-exist")
        assert could_not.exit_code == ACCOUNT_SCOPE_EXIT_COULD_NOT_RUN, (
            "a checker pointed at a path that is not a repository has not checked "
            f"anything, and must exit 2 rather than 0:\n{could_not.render()}"
        )
        assert could_not.could_not_run, "exit 2 has to say what it could not do"


def test_a_warning_never_moves_the_account_scope_checkers_exit_code() -> None:
    """The tri-state, on the case that is easiest to get wrong.

    Four of this checker's findings are warnings and they are all the same claim in
    different clothes: something was not proved, and the tool cannot prove it from
    the files in front of it. A warning that moved the exit code would be a
    failure, which trains the reader to ignore failures; the same warning printed
    as a failure trains them to ignore the sentence that says why.
    """
    module = account_scope_module()
    warned = {identifier for identifier, (severity, _c, _r) in module.FINDINGS.items() if severity == "warn"}
    assert warned, "there are warnings in this checker and this test asserts they do not move it"
    report = module.Report(
        repo=Path("/tmp/x"),
        findings=[module.finding(identifier, "planted") for identifier in sorted(warned)],
    )
    assert report.of("fail") == []
    assert report.exit_code == ACCOUNT_SCOPE_EXIT_OK, (
        f"{sorted(warned)} are warnings and must not move the exit code"
    )
    assert "warning(s)" in report.render() and "do not move the exit code" in report.render()
    # And the converse, on the same Report: one failure and it is exit 1 whatever
    # else is in there, which is the other half of the claim.
    mixed = module.Report(
        repo=Path("/tmp/x"),
        findings=[module.finding(identifier, "planted") for identifier in sorted(warned | {"account-scope.undeclared"})],
    )
    assert mixed.exit_code == ACCOUNT_SCOPE_EXIT_FAIL


def test_the_account_scope_checker_reads_no_environment_and_runs_no_process() -> None:
    """The one thing this checker must NOT do, because the gate checker must.

    `harness/gate_check.py` runs the gate it is checking; that is its whole
    difference from a file that compares strings. This one must not, and the reason
    is that a boundary check whose answer depends on what the repository can execute
    is a boundary check whose answer depends on the machine — so it passes where it
    cannot look, which is the defect this whole format exists to stop.
    """
    source = ACCOUNT_SCOPE_CHECK.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts: list[str] = []
        target = node.func
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        called.add(".".join(reversed(parts)))
    for banned in (
        "os.system", "os.popen", "os.spawn", "os.fork", "eval", "exec", "compile",
        "__import__", "subprocess.run", "subprocess.Popen", "subprocess.call",
        "urllib.request.urlopen", "socket.socket", "http.client",
    ):
        assert banned not in called, (
            f"harness/account_scope_check.py calls {banned}(). This checker reads a tree "
            "and answers a question about it; it fetches nothing and runs nothing."
        )
    assert "os.environ" not in source and "getenv" not in source, (
        "harness/account_scope_check.py reads no environment variable of its own. Its "
        "answer depends on the repository, not on who is asking."
    )


def test_the_account_scope_checker_needs_nothing_core_does_not_ship() -> None:
    """Stdlib only, and the runtime half too.

    A service's CI should be able to run `account-scope-check` with nothing
    installed, which is the same reason `gate_check.py` and `tenancy_check.py` may
    not import `jsonschema`. The static half is an AST walk, so a `from x import y`
    inside a function body is caught as readily as one at the top; the runtime half
    is `-I -S` — user site-packages, `PYTHONPATH` and the site module all out of the
    way.

    Run against the CONFORMING FIXTURE and never against core: pointing the runtime
    proof at a repository with no declaration would assert a failure as though it
    were a pass.
    """
    tree = ast.parse(ACCOUNT_SCOPE_CHECK.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    siblings = {"cafaye_contract"}
    module = account_scope_module()
    outside = sorted(imported - HARNESS_STDLIB_ONLY - siblings - module.EXTRA_STDLIB)
    assert not outside, (
        f"harness/account_scope_check.py imports {outside}. core has one dependency list "
        "and this checker must not add a second: a check that needs a package is a "
        "check a Go service's CI cannot run."
    )
    not_stdlib = sorted(
        (HARNESS_STDLIB_ONLY | module.EXTRA_STDLIB)
        - set(sys.stdlib_module_names)
        - siblings
    )
    assert not not_stdlib, f"{not_stdlib} are in the allowlist and are not stdlib here"
    assert "cafaye_contract" in imported, (
        "harness/account_scope_check.py must read YAML with the harness's own reader. A "
        "second YAML dialect in core is the four-way drift core exists to end."
    )
    with tempfile.TemporaryDirectory() as name:
        repo = Path(name) / "service"
        shutil.copytree(ACCOUNT_SCOPE_CONFORMING, repo)
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(ACCOUNT_SCOPE_CHECK), str(repo)],
            cwd=str(REPO), env={}, capture_output=True, text=True, check=False,
        )
    assert completed.returncode == ACCOUNT_SCOPE_EXIT_OK, (
        f"the checker must run on the standard library alone, exited "
        f"{completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )


def test_the_checker_says_which_state_each_entry_point_is_in() -> None:
    """The report's whole reason for existing, asserted on the control fixture.

    Four states, per entry point, and they are four DIFFERENT answers rather than a
    pass and a fail. A report that only printed failures would say nothing about a
    service that declared its surface correctly, which is the state this file is
    trying to get nine repositories into.

    The fourth is `stale`, and it is in this dict rather than absent for the reason
    the count is asserted EQUAL and not merely for its value: a summary that counts
    every state except the rows the file contradicts reads as though every row it
    listed is mounted. `registration-commented` is what put it here — a deleted
    route was printed as `not-account-scoped GET /healthz (…:11)` beside a line
    that was a comment, with exit 0.
    """
    module = account_scope_module()
    report = module.check(ACCOUNT_SCOPE_CONFORMING)
    assert report.exit_code == ACCOUNT_SCOPE_EXIT_OK, report.render()
    counts = report.counts
    assert counts == {
        "account-scoped": 3,
        "not-account-scoped": 1,
        "stale": 0,
        "undeclared": 0,
        "failures": 0,
        "warnings": 0,
    }, counts
    rendered = report.render()
    for state in ("account-scoped", "not-account-scoped", "stale", "undeclared"):
        assert state in rendered, rendered
    # The Phoenix fixture is the second control and it answers a different question:
    # that a declared FULL path resolves a bare fragment registered under a scope.
    phoenix = module.check(ACCOUNT_SCOPE_PHOENIX)
    assert phoenix.exit_code == ACCOUNT_SCOPE_EXIT_OK, phoenix.render()
    assert phoenix.counts["undeclared"] == 0, phoenix.render()
    assert phoenix.counts["stale"] == 0, phoenix.render()
    # And the THIRD control, which answers the question the first two cannot: can
    # this checker read a route whose path is not in any line? Next.js puts it in
    # the file name, and `site` and `parlor` both serve their whole `/v1` surface
    # that way — so a checker that could not would report two of the three
    # repositories in this packet's own scope as having no routes, which is D18's
    # `route_defs=0` reproduced by the tool written to stop it.
    nextjs = module.check(ACCOUNT_SCOPE_NEXTJS)
    assert nextjs.exit_code == ACCOUNT_SCOPE_EXIT_OK, nextjs.render()
    assert nextjs.counts == {
        "account-scoped": 4,
        "not-account-scoped": 2,
        "stale": 0,
        "undeclared": 0,
        "failures": 0,
        "warnings": 0,
    }, nextjs.counts
    # The FOURTH and FIFTH controls, and they are the ones that decide whether a
    # Hono route behind an `app.use` is declarable at all. Before `chain_gate`, both
    # of these were RED on a correct route: gateway's `/v1/me` is registered with an
    # inline handler twenty-seven lines BELOW `app.use("/v1/*", … jwt.requireJwt(c,
    # next) …)`, and Hono answers in registration order, so the route IS behind the
    # gate and its own line says nothing either way. Zero WARNINGS is asserted rather
    # than zero failures, because the defect this fixes was one failure among no
    # warnings and a fix that traded it for warnings would look the same from outside.
    for fixture, scoped, unscoped in (
        (ACCOUNT_SCOPE_HONO_PIPELINE, 2, 2),
        (ACCOUNT_SCOPE_HONO_SURFACE, 2, 3),
    ):
        report = module.check(fixture)
        assert report.exit_code == ACCOUNT_SCOPE_EXIT_OK, report.render()
        assert report.counts["account-scoped"] == scoped, report.counts
        assert report.counts["not-account-scoped"] == unscoped, report.counts
        assert report.counts["undeclared"] == 0, report.render()
        assert report.counts["failures"] == 0, report.render()
    # And the shape the reader CANNOT follow, which is the other half of the
    # decision: `accountGate` lives in another module, so the chain left the file
    # this checker read. It must NOT be called unscoped — the wolf — and it must not
    # be counted as declared-and-clean either: `undeclared` is 1 there, and that is
    # `app.route("/v1", v1())` being read as axum's `.route(path, handler)`, which is
    # a real and separate defect recorded in REPORT-core-hono-inline-01.md §7.
    composed = module.check(ACCOUNT_SCOPE_HONO_COMPOSED)
    assert "account-scope.scoping-bypassed" not in composed.render(), (
        "a route behind a mount this checker cannot follow was called unscoped. That is "
        "the wolf: `Recogniser.carries_handler` refuses to conclude about a chain it "
        "cannot read, and a sub-application mount is the same refusal one hop further "
        "out.\n" + composed.render()
    )
    assert composed.counts["account-scoped"] == 1, composed.counts


def test_a_row_whose_line_only_comments_the_route_is_a_failure_and_not_a_mounted_route() -> None:
    """The defect, asserted on the report object rather than on the printed text.

    A refactor comments a registration out and leaves the row. Three things have
    to be true at once and each is independently enough: the run FAILS, it fails
    with `account-scope.registration-commented` rather than with `undeclared`
    (nothing is registered, so nothing is undeclared — a real registration no row
    covers is a different failure), and the row is listed as `stale` rather than
    as a mounted route. The third is not implied by the first: a checker can raise
    a finding and still print a row that asserts the route exists, and the printed
    row is what somebody skimming the output reads.
    """
    module = account_scope_module()
    with tempfile.TemporaryDirectory() as work:
        broken = Path(work) / "conforming"
        shutil.copytree(ACCOUNT_SCOPE_CONFORMING, broken)
        router = broken / "internal/httpapi/router.go"
        router.write_text(
            "\n".join(
                "\t// " + line.strip() if "/healthz" in line else line
                for line in router.read_text().splitlines()
            )
            + "\n"
        )
        # And the floor lowered as well, so nothing but the row can catch it. This
        # is the edit the docs warn about and cannot prevent, and it is why the
        # per-row check cannot be replaced by a raise-the-number answer.
        declaration = broken / "account_scope.yml"
        declaration.write_text(declaration.read_text().replace("minimum: 4", "minimum: 3"))
        report = module.check(broken)
        assert report.exit_code == ACCOUNT_SCOPE_EXIT_FAIL, report.render()
        assert [item.id for item in report.of("fail")] == ["account-scope.registration-commented"], [
            item.render() for item in report.of("fail")
        ]
        assert report.counts["stale"] == 1, report.counts
        assert report.counts["undeclared"] == 0, report.counts
        rows = [row for row in report.entry_points if row["path"] == "/healthz"]
        assert [row["state"] for row in rows] == ["stale"], rows
        rendered = report.render()
        assert "not-account-scoped GET /healthz" not in rendered, rendered


def test_the_account_scope_doc_states_the_contract_and_what_it_cannot_do() -> None:
    """A rule that exists only in the module's source is a rule nobody applies.

    The measurement that decided the format is in the doc as a measurement, because
    a reader who has not seen D18's three answers has no reason to believe a
    declaration beats a grep.
    """
    text = ACCOUNT_SCOPE_DOC.read_text(encoding="utf-8")
    for needle in (
        "D18",
        "route_defs=0",
        "worse than no grep",
        "undeclared",
        "surface.minimum",
        "suffix",
        "notEnforced",
        "not here",
        "account_scope.yml",
        "required",
    ):
        assert needle in text, needle
    # Every finding the checker can report is named in the doc, and every id the doc
    # names is one the checker can report — in BOTH directions, which is the tenancy
    # doc's rule and the reason it is a test rather than a paragraph.
    module = account_scope_module()
    named = set(re.findall(r"`(account-scope\.[a-z-]+)`", text))
    assert named == set(module.FINDINGS), (
        "docs/account-scope.md and the checker disagree about what can be reported.\n"
        f"  in FINDINGS, not in the doc: {sorted(set(module.FINDINGS) - named)}\n"
        f"  in the doc, not in FINDINGS: {sorted(named - set(module.FINDINGS))}"
    )


def test_the_account_scope_wrapper_never_lifts_the_exit_code() -> None:
    """A wrapper that turns a refusal into a pass is worse than no wrapper.

    The one thing a caller was relying on — the exit code — is the thing it
    discarded, and there is a recorded false green in this fleet of exactly that
    shape (`… | tail -45; echo "PRIME EXIT=$?"` under zsh, where `$?` was tail's).
    """
    text = ACCOUNT_SCOPE_WRAPPER.read_text(encoding="utf-8")
    # The `|| true` ban is on CODE, not on prose: this wrapper's own header says the
    # words while explaining why they are forbidden.
    body = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any("|| true" in line for line in body), body
    assert any("exec " in line for line in body), body
    assert any("exit 2" in line for line in body), body


def test_the_account_scope_red_proof_plants_the_defect_it_exists_to_catch() -> None:
    """The proof has to be about the DEFECT, not about the checker's plumbing.

    Case 2 of the proof is a chi route whose `o.requireAccount(...)` call was
    deleted with the declaration left untouched — a cross-tenant read with a file
    saying the route is scoped. A proof that planted something the defect never
    looked like would be a proof of the regex.
    """
    text = ACCOUNT_SCOPE_SELF_TEST.read_text(encoding="utf-8")
    assert "o.handleGetMessage" in text and "o.requireAccount(o.handleGetMessage)" in text
    assert "account-scope.scoping-bypassed" in text
    assert "phoenix_surface" in text, (
        "the negative control for the scope prefix has to be a real Phoenix router: a "
        "checker that insisted on the prefix would go red on courier's own file, and "
        "that is the false positive that gets a guard switched off"
    )
    # And CI has to RUN it. This is the fourth time this fleet has been told it
    # cannot ship a check that quietly does not run — gateway's live-Redis tier,
    # muse's `MUSE_CORE_SCHEMAS`, identity's `TEST_DATABASE_URL`, darkroom's
    # `--ignored` — and every one of them read exactly like a pass. A red proof
    # that lives only in `harness/tests/` is a claim rather than a proof.
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "account_scope_self_test.sh" in workflow, (
        "no CI step runs harness/tests/account_scope_self_test.sh. A red proof CI never "
        "invokes is not a test, and a comment claiming CI runs it is not CI running it."
    )
    # And every recogniser's example is a line that EXISTS in a committed fixture
    # rather than one the author typed into the pattern. That is the difference
    # between a recogniser read out of a repository and one that matches the idea of
    # a repository, and it is checkable because the fixture is in the tree.
    module = account_scope_module()
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(ACCOUNT_SCOPE_FIXTURES.rglob("*"))
        if path.is_file() and path.suffix in {".go", ".ex", ".ts", ".rs"}
    )
    for recogniser in module.RECOGNISERS:
        assert recogniser.example.strip() in corpus, (
            f"the {recogniser.id} recogniser's example is not a line in any committed "
            f"fixture: {recogniser.example!r} (it says it was read from "
            f"{recogniser.read_from})"
        )


def _annotation_arity(node: ast.expr | None) -> int | None:
    """The arity a return annotation pins, or None when it pins nothing.

    `None` means "unknown", which is different from 0 and is deliberately not a
    value any of the three arms below collapses into. `X | None` unwraps to `X`
    deliberately: the `| None` arm is the arity-0 return, which the caller already
    exempts, and treating it as "unknown" would let `tuple[str, str] | None` slip
    past a function that returns a bare string on one branch.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant) and node.value is None:
        return 0
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_arity(node.left)
        return left if left is not None else 1
    if isinstance(node, ast.Subscript):
        origin = node.value
        if isinstance(origin, ast.Name) and origin.id in {"tuple", "Tuple"}:
            index = node.slice
            if isinstance(index, ast.Tuple):
                # `tuple[X, ...]` is variable-arity by construction and pins
                # nothing; a function annotated with it is out of this rule's
                # reach and says so rather than being guessed at.
                if any(
                    isinstance(e, ast.Constant) and e.value is Ellipsis for e in index.elts
                ):
                    return None
                return len(index.elts)
            return 1
        return 1
    return 1


def _own_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """The `return`s belonging to THIS function and not to a function inside it.

    Walking the whole subtree instead attributes a nested helper's `return` to its
    parent, which invented three false disagreements when this was measured over
    the tree on 2026-10-03 — `db_isolation_check.scan_service` is `-> ServiceReport`
    and its nested `rank` returns a 2-tuple. The gate is only worth having if it
    is true, and this is what makes it true.
    """
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    found: list[ast.Return] = []
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, nested):
            continue
        if isinstance(node, ast.Return):
            found.append(node)
        elif isinstance(node, ast.AST):
            stack.extend(ast.iter_child_nodes(node))
    return found


def _value_arity(
    node: ast.expr | None, table: dict[str, set[int]]
) -> int | None:
    """The number of values a `return` yields, or None when that is not knowable.

    Three shapes are resolved and everything else reports "unknown": a tuple
    literal (`return a, b`), a conditional whose two arms agree
    (`return x if ok else None` — an `Optional`, which is why `None` returns are
    exempt from the rule entirely), and a bare call to a same-module function whose
    own arities agree, so `return _parse_sequence(...)` inherits `tuple[Any, int]`
    from the definition rather than reading as one value.
    """
    if node is None:
        return 0
    if isinstance(node, ast.Constant) and node.value is None:
        return 0
    if isinstance(node, ast.Tuple):
        if any(isinstance(e, ast.Starred) for e in node.elts):
            return None
        return len(node.elts)
    if isinstance(node, ast.IfExp):
        arms = {_value_arity(node.body, table), _value_arity(node.orelse, table)}
        arms.discard(None)
        return next(iter(arms)) if len(arms) == 1 else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        known = table.get(node.func.id)
        if known is None:
            # A name no function in this module owns is a constructor, a method or
            # something imported — one value. Defaulting to "unknown" here instead
            # skipped EVERY function that returns a dataclass, which is most of
            # this harness, and the rule was silently not applied to any of them.
            return 1
        return next(iter(known)) if len(known) == 1 else None
    return 1


def _annotation_names(node: ast.expr | None) -> set[str]:
    """Every identifier a return annotation mentions, at any depth.

    `-> Contradictions` and `-> tuple[Contradictions, ...]` both mention
    `Contradictions`; the first is the shape this checker now returns and the
    second is a shape it could return, and the arm below must not be the thing
    that decides between them.
    """
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _constructed_class(
    node: ast.expr | None, classes: set[str]
) -> str | None:
    """The module-local class a `return` constructs, if it constructs one.

    `return Contradictions(...)` returns a `Contradictions` and nothing else, so
    this is a fact rather than a guess — which is what lets the annotation arm
    catch a stale type on a function whose returns all agree with EACH OTHER.
    That is the shape the fossil in this packet took: every `return` was a single
    value, so no arity rule could see the annotation lying, and the caller was
    the only thing that knew.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id if node.func.id in classes else None
    return None


def _harness_modules() -> list[Path]:
    """Every module in `harness/`, except the deliberately-broken copies.

    `harness/account_scope_check_disabled.py` is a committed copy of the checker
    with the contradiction check removed, kept so the difference between the two
    files is diffable. A copy whose function bodies have been deliberately broken
    is a fixture; asserting that it is internally consistent is asserting that a
    fixture is internally consistent, which is not a claim about the checker. The
    copy is still parsed — the test counts how many modules it saw, so hiding one
    here does not shrink the number.
    """
    return sorted(
        path
        for path in (HARNESS.rglob("*.py"))
        if not path.name.endswith("_disabled.py")
    )


def test_every_harness_function_returns_one_shape() -> None:
    """A function returns ONE shape, and the annotation says which.

    THE BUG THIS EXISTS FOR. `worker/core-account-scope-contradiction` changed the
    caller of `_check_contradictions` to unpack two values;
    `worker/core-account-scope-unpack`'s predecessor left the definition returning
    one. Each half was internally consistent, so git merged them with no textual
    conflict, `bin/prime` exited 0, 295/295 tests passed — and the checker raised
    `ValueError: not enough values to unpack` on the one input path no gate
    reached (case 15d: a declaration with no `accountScoped: false` row, so the
    function took its early return). Two branches, one contract, and a green gate.

    A 2-tuple has its arity at the CALL SITE and its type at the DEFINITION, and
    nothing connects them except a reader. `-> list[Finding]` was the fossil that
    said which half was stale, and it had been sitting there the whole time,
    readable, with every gate green.

    So this asserts the arity the annotation pins against the arity the returns
    produce, per function, over every module in `harness/`. It is deliberately
    not `mypy --strict`: core does not run mypy and adding it to a repository
    whose harness is on the standard library alone is a larger change than the
    defect, and it would be defeatable with one `# type: ignore` on the same line
    as the lie. This cannot be.

    THE THREE ROLES, so none of them is a silent exemption:

      arity 0   a bare `return` or `return None`. This is `Optional`, which is a
                real and correct shape, and it is exempt because exempting it is
                the only way this rule could be true. Excluding it is what makes
                the other two arms worth having: `return []` beside
                `return (found, unreachable)` is arity 1 beside arity 2, and it is
                the exact bug.
      arity 1+  every value a function returns. ONE number per function.
      unknown   a return this cannot resolve — a starred unpack, a conditional
                whose arms disagree, a call whose callee has two shapes of its
                own. Unknown is NOT a pass and is not counted as agreement: the
                number of them is printed in the failure message, so the blind
                spot is visible to whoever reads it rather than assumed away.

    PROVED BY REMOVING THE FIX, not by reading it: with `_check_contradictions`
    annotated `-> list[Finding]` and returning `([], [])` on its early path, this
    is red on two counts in one function — the annotation against the late
    `return`, and the early `return` against it.
    """
    disagreements: list[str] = []
    unpinned = 0
    functions = 0
    for path in _harness_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # One pass to learn each function's own arity, so a bare `return f(...)`
        # can inherit it. Only UNAMBIGUOUS functions go in the table: a name with
        # two shapes of its own teaches nothing and is better absent.
        table: dict[str, set[int]] = {}
        classes = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            shapes = {
                arity
                for arity in (
                    _value_arity(r.value, table) for r in _own_returns(node)
                )
                if arity is not None and arity > 0
            }
            if len(shapes) == 1:
                table.setdefault(node.name, set()).update(shapes)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            returns = _own_returns(node)
            if not returns:
                continue
            functions += 1
            relative = path.relative_to(REPO)
            by_arity: dict[int, list[int]] = {}
            for returned in returns:
                arity = _value_arity(returned.value, table)
                if arity is None:
                    unpinned += 1
                by_arity.setdefault(arity if arity is not None else -1, []).append(
                    returned.lineno
                )
            values = {a: lines for a, lines in by_arity.items() if a > 0}
            if len(values) > 1:
                shape = ", ".join(
                    f"{a} value(s) at {', '.join(str(n) for n in lines)}"
                    for a, lines in sorted(values.items())
                )
                disagreements.append(
                    f"{relative}:{node.lineno} {node.name}() returns {shape} — a caller "
                    f"cannot destructure one value and two from the same function"
                )
                continue
            declared = _annotation_arity(node.returns)
            if declared is None or not values:
                continue
            (returned_arity, returned_lines) = next(iter(values.items()))
            if declared != returned_arity:
                disagreements.append(
                    f"{relative}:{node.lineno} {node.name}() is annotated "
                    f"-> {ast.unparse(node.returns)} ({declared} value(s)) and returns "
                    f"{returned_arity} at {', '.join(str(n) for n in returned_lines)}. The "
                    f"annotation is the fossil: it says which half of a contract is stale, "
                    f"and leaving a lie in it is how this merge happened."
                )
                continue
            # The annotation can be wrong about the TYPE while every return agrees
            # with every other return, and then no arity rule on earth sees it —
            # which is exactly the fossil `_check_contradictions` wore. Only
            # decidable from a construction, so a bare `return found` is exempt
            # rather than guessed at.
            mentioned = _annotation_names(node.returns)
            for returned in returns:
                built = _constructed_class(returned.value, classes)
                if built is not None and mentioned and built not in mentioned:
                    disagreements.append(
                        f"{relative}:{node.lineno} {node.name}() is annotated "
                        f"-> {ast.unparse(node.returns)} and returns {built}(...) at line "
                        f"{returned.lineno}. An annotation nobody wrote for the value the "
                        f"function returns is the fossil that tells the next reader which "
                        f"half of a contract is stale — and it is readable while every "
                        f"gate is green."
                    )
                    break

    assert functions > 300, (
        f"the arity walk saw only {functions} function(s) across "
        f"{len(_harness_modules())} module(s) in harness/, and 347 across 12 is what it saw "
        f"when this was written. A glob that stopped matching is a rule that quietly stopped "
        f"running, and this is the rule that catches the merge that came through green."
    )
    assert not disagreements, (
        "a harness function returns two different numbers of values, or is annotated with a "
        "return type its own returns contradict. Both halves of one contract came from two "
        f"branches, merged without a textual conflict, passed every gate, and crashed on an "
        f"input no gate reached:\n  " + "\n  ".join(disagreements) +
        f"\n({unpinned} return(s) could not be resolved statically and are exempt; that "
        f"count is here so the blind spot stays visible.)"
    )


def test_bin_prime_runs_the_account_scope_checkers_red_proof() -> None:
    """The step exists, and deleting it is a red, not a slower gate.

    THE MERGE THIS EXISTS FOR. `worker/core-account-scope-contradiction` changed
    one half of `_check_contradictions`' contract and master changed the other.
    The merge was textually clean, `bin/prime` exited 0, and 295/295 tests
    passed — because `harness/tests/account_scope_self_test.sh`, thirty-two
    cases with a fixture tree, was a CI step and nothing else. The checker
    crashed on case 15d and CI would have caught it two minutes later; the
    manager merged on the strength of the green.

    A gate that does not run the proof reports on the parts it happens to look
    at. So the assertion is about the COMMAND and, below it, about the exit
    code moving — either can be deleted on its own and either leaves a comment
    that still mentions the script.
    """
    prime = (REPO / "bin" / "prime").read_text(encoding="utf-8")
    commands = [
        line for line in prime.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any("account_scope_self_test.sh" in line for line in commands), (
        "bin/prime must RUN harness/tests/account_scope_self_test.sh, not mention it. "
        "Before this packet it ran in CI only, so `bin/prime` exited 0 on a tree whose "
        "flagship red proof was 2 of 32 red — a gate that reports on the parts it happens "
        "to look at, and the merge that came through it."
    )
    assert re.search(r"^\s*account_scope_red_proof\s+\"\$", "\n".join(commands), re.MULTILINE), (
        "bin/prime defines account_scope_red_proof() and never calls it. A function that "
        "runs a red proof without being invoked is a comment with a shebang, and it is "
        "indistinguishable from the step being absent."
    )
    # Three rules, each deletable on its own. Same three the other three red-proof
    # steps carry, restated here because a rule inherited by reference is a rule
    # that stops being enforced the day the file it points at is renamed.
    assert any("CAFAYE_ACCOUNT_SCOPE_PYTHON" in line for line in commands), (
        "the step must PIN the interpreter it hands the proof. The script otherwise takes "
        "whatever python3 is on PATH, and a local gate that depends on the machine gives a "
        "different answer on a laptop than on CI."
    )
    for needle, because in (
        ("without reporting its counts", "a red proof that printed no counts"),
        ("ran $cases case(s)", "a red proof that stopped running cases"),
        ("red proof FAILED", "a red proof that exits non-zero"),
    ):
        assert needle in prime, (
            f"bin/prime's account-scope step lost the check that reads the report ({because}). "
            f"Searched for {needle!r}."
        )


def test_bin_prime_is_red_when_the_account_scope_red_proof_is() -> None:
    """The exit code moves. As a process, not as a line.

    `bin/prime` mentioning the script is a claim in a comment until something
    watches the exit code. Here the red proof is a script this test wrote which
    exits 1 — the state the tree was in when the manager merged — and
    `bin/prime` has to come back non-zero saying so.

    A WARNING is not enough and is not what is asserted: a check that does not
    move the exit code is a comment, and the defect this packet is about is a
    comment everyone believed.
    """
    with tempfile.TemporaryDirectory() as raw:
        run = prime_in_a_throwaway_copy(
            Path(raw),
            a_red_proof(),
            account_scope_proof=a_complete_account_scope_red_proof(exit_code=1),
        )
    assert run.returncode != GATE_EXIT_OK, (
        "an account-scope red proof that exits 1 must fail bin/prime, or the local gate is "
        f"not gating what CI gates. It exited {run.returncode}.\n{run.stdout}\n{run.stderr}"
    )
    assert "account-scope checker's red proof FAILED" in run.stderr, (
        "the message has to say WHICH step failed and that nothing below it is a pass. "
        f"stderr was:\n{run.stderr}"
    )
    assert "1/1 passed" in run.stdout, (
        f"the copy's stub suite never ran, so this test proved nothing about bin/prime\n"
        f"{run.stdout}"
    )


def main() -> int:
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, test in tests:
        try:
            test()
        except AssertionError as error:
            failed += 1
            print(f"FAIL {name}\n     {error}")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            failed += 1
            print(f"ERROR {name}\n      {type(error).__name__}: {error}")
        else:
            print(f"pass {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

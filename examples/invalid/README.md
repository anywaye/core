# Invalid examples — expected failures

One negative example per rule that constrains, per schema. Every file here is
**supposed to fail** validation: the errors below are the contract, not
accidents. If one of these files starts validating, either a schema got looser
or an example stopped being a real mistake — both are review events.

`tests/test_specs.py` asserts the exact `(keyword, path)` pairs listed here, so
the tables cannot drift from the schemas silently. It also walks this directory
and fails on any file whose repo-relative path is missing from this document,
which is what keeps a new negative example from landing as an unreviewed
comment.

Reproduce with:

```
bin/prime                                  # every file here must be reported as rejected
```

or, to see the raw validator output:

```
tests/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "tests")
import test_specs as t
for schema, doc in ((t.MANIFEST_SCHEMA_PATH, t.INVALID_MANIFEST),
                    (t.ENVELOPE_SCHEMA_PATH, t.INVALID_ENVELOPE),
                    (t.ENVELOPE_SCHEMA_PATH, t.INVALID_UNTAGGED_ENVELOPE),
                    (t.ENVELOPE_SCHEMA_PATH, t.INVALID_SUBJECTLESS_ENVELOPE)):
    print(doc.name)
    for f in t.failures_for(t.load_document(doc), t.load_schema(schema)):
        print("   ", f)
PY
```

## `examples/invalid/manifest.cafaye.invalid.yml`

Rejected by [`schemas/cafaye.manifest.schema.json`](../../schemas/cafaye.manifest.schema.json).
It is a realistic bad manifest — the mistakes a service actually ships with,
all at once — not a single deliberate typo.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `name: Billing_Service` | `pattern` | Names are lowercase kebab-case. The `name` is also the repo name, the event `source` and the routing prefix, so it cannot carry case or underscores. |
| 2 | `language: python3` | `enum` | Not a cafaye language. The enum is `go`, `ruby`, `elixir`, `python`, `typescript`, `rust`, `spec`. |
| 3 | `core: ^0.1` | `pattern` | A core constraint must be a full `MAJOR.MINOR.PATCH`. A missing patch version silently widens the range. |
| 4 | `exposes.api: ./openapi.yaml` | `pattern` | Must be a repository-relative path with no `./` prefix, no absolute path and no URL — the path is resolved inside the repo by `caf` and by contract tests. |
| 5 | `exposes.events[0]: user.Created` | `pattern` | Two violations in one value. The type is **two** segments, and the grammar is exactly `<service>.<entity>.<action>`; and `Created` is not lowercase snake_case, which would fork the topic away from every existing `identity.user.created` subscription. |
| 6 | `repository.url: https://github.com/…` | `pattern` | SSH remotes only, for anything cafaye or anywaye owns (PLAN.md §1). |
| 7 | `repository.defaultBranch: main` | `const` | The cafaye primary branch is `master` everywhere. |
| 8 | `ports:` | `additionalProperties` | Undeclared top-level key. Manifests are closed on purpose: a key core does not know about cannot be validated, and cannot be enforced. Ports are deployment configuration, not contract surface. |

## `examples/invalid/kind-not-an-enum-value.yml`

Rejected by [`schemas/cafaye.manifest.schema.json`](../../schemas/cafaye.manifest.schema.json).

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `kind: library` | `enum` | Not `service` or `template`. `kind` is what tells a registry reader whether an entry is a running service or a generate-time template. Dropping an unrecognised kind would list a template as a service, and every consumer downstream would resolve it the wrong way — `caf deploy` would try to deploy something that is only rendered. |

## `examples/invalid/provisioning-not-selfhost-or-hosted.yml`

Rejected by [`schemas/cafaye.manifest.schema.json`](../../schemas/cafaye.manifest.schema.json).

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `environments.production.identity: managed` | `enum` | Not `self-hosted` or `hosted`. Provisioning is the switch the whole ethos rests on. A third value is not a future feature, it is an ambiguity at the one place the platform promises to be unambiguous. The set grows as a deliberate schema change with a version, never as a manifest that quietly spells something the resolver has to guess. |

## `examples/invalid/event-envelope.invalid.json`

Rejected by [`schemas/event-envelope.schema.json`](../../schemas/event-envelope.schema.json).
JSON has no comment syntax, so this table is the expected-failure note for
this file.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `specversion` | `required` | The envelope dialect is not optional. A consumer that cannot tell which envelope it is reading cannot decode the rest. |
| 2 | `id: "usr-01J9Z8QK5M4N7P2R3T6V8W9X0A"` | `format` | `id` is a UUID, not a business id. Consumers dedupe on `id`, and business ids are reused across entities — they belong in `subject`/`data`. |
| 3 | `type: "identity.user.account.created"` | `pattern` | Four segments. The grammar is exactly three: there is no room for a container level. |
| 4 | `subject: "user usr_01J9Z8QK5M4N7P2R3T6V8W9X0A"` | `pattern` | `subject` is a bare identifier, never prose. A space also breaks per-entity ordering guarantees, which correlate on this value. |
| 5 | `time: "2026-13-45T99:99:00Z"` | `format` | Not a valid RFC3339 timestamp (month 13, hour 99). |
| 6 | `trace_id: "0af7651916cd43dd8448eb211c80319c"` | `additionalProperties` | Undeclared envelope attribute. The envelope is closed: transport metadata travels in transport headers, so a producer that needs it added must go through a spec change, not a private field. |

## `examples/invalid/event-envelope.untagged.invalid.json`

Rejected by [`schemas/event-envelope.schema.json`](../../schemas/event-envelope.schema.json).
Every field is legal except the `type`, which is the mistake the file exists to
pin down — the pre-v0.2 short form, still in every subscription from before the
grammar change.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `type: "user.created"` | `pattern` | Two segments. There is no short form: the publisher's own name is the first segment of every event type, because an unprefixed type says what changed and not who changed it. `identity.user.created`, not `user.created`. |

## `examples/invalid/event-envelope.subjectless.invalid.json`

Rejected by [`schemas/event-envelope.schema.json`](../../schemas/event-envelope.schema.json).
A well-formed envelope that simply forgot `subject` — the failure mode of
writing the field from an optional CloudEvents mental model.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `subject` | `required` | `subject` is required, not optional. It is the correlation key that carries per-entity ordering, and an event with no single entity uses the literal `platform` — a required field with a reserved value, never a missing one. |

## `examples/invalid/events/identity/user/created.data.json`

Rejected by [`schemas/events/identity/user/created.schema.json`](../../schemas/events/identity/user/created.schema.json).
**This file is the payload D35 shipped, unchanged, and it is now the evidence
that D35 was wrong.** All three of its fields are rejections, so the correction is
enforced from the example side as well as the schema side — a schema that is
right and an example that still teaches the fiction is half a fix, and the
example is the half a consumer copies.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `email` | `required` | The address is not optional — a consumer that cannot send verification mail has nothing to do with this event. |
| 2 | `user_id: "usr_01J9Z8QK5M4N7P2R3T6V8W9X0A"` | `format` | **`format: uuid`, and this string is the exact value the old pattern required.** identity's `id.UUID.String()` emits a bare uuid, so the old `^usr_[0-9A-Z]{26}$` pattern rejected 100% of the publisher's real output. See [D35](../../DECISIONS.md#d35-identityusercreateds-payload-schema-describes-a-payload-its-only-publisher-does-not-emit). |
| 3 | `email_verified` | `additionalProperties` | Not merely undeclared: **deleted**, because identity's builder marshals a struct of two fields and never sent this one. An optional property would have been the same lie in a softer form. A schema that names a field nobody emits is a contract that lies, and it lies *green*. |
| 4 | `favourite_colour` | `additionalProperties` | Undeclared payload field. Payload schemas are closed, so an unknown field is a contract difference to resolve in core, not something a publisher adds in a hurry. |

## `examples/invalid/events/identity/user/email_verified.data.json`

Rejected by [`schemas/events/identity/user/email_verified.schema.json`](../../schemas/events/identity/user/email_verified.schema.json).
The only field is missing and a credential arrived in its place. This is the shape
of the most tempting wrong payload on the bus: somebody helpfully forwards the
link they just redeemed so a consumer can tell verification from signup.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `user_id` | `required` | The one field the payload has. Without it there is nothing on the event to correlate on, and `subject` carries the same value. |
| 2 | `verification_token` | `additionalProperties` | **A credential on an event that reaches every subscriber on the platform.** The raw token exists exactly once, in the response to whoever redeemed it, and the row holds a digest; the publisher's builder takes a user id and nothing else. A schema that grew this field would be a contract that lies, and it lies *green*. |

## `examples/invalid/events/identity/session/revoked.data.json`

Rejected by [`schemas/events/identity/session/revoked.schema.json`](../../schemas/events/identity/session/revoked.schema.json).
Four violations in one payload, and the second is the one that matters: a
**third** reason. The publisher validates its reason against a closed set of two
before it appends, because a free-text reason on the bus is a field every consumer
learns to ignore — and a consumer that switches on it needs to know an
unrecognised value is a bug rather than a new flow.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `user_id` | `required` | Whose credentials are gone. A revocation nobody can be attributed to is not actionable, and the envelope's `subject` is the same value. |
| 2 | `reason: "admin revoked"` | `enum` | **A reason outside the publisher's set of two** — a password reset, or an email address changed. identity has no admin revocation at all, so emitting this type for one is how a consumer ends up waiting for an event that cannot arrive. The publisher refuses a reason it does not implement at the write, which is what makes the closed set safe to switch on. |
| 3 | `sessions_ended` | `additionalProperties` | A count of what ended. Tempting and wrong twice: the sessions are already gone by the time the row commits, and a number frozen onto the bus is a second thing to keep in sync with a store that has a different lifetime. |
| 4 | *(absent)* `email` | `required` | The address both notices this event triggers are mailed to. The consumer that mails them is cross-service — no identity client, no identity tables — so the publisher carries the address on the event rather than leaving the consumer to re-read the user row (REPORT-courier-consumer-invite-01.md §2.6). |

## `examples/invalid/events/identity/mfa/enabled.data.json`

Rejected by [`schemas/events/identity/mfa/enabled.schema.json`](../../schemas/events/identity/mfa/enabled.schema.json).
The credential id is missing, the factor is one the publisher cannot store, and
the payload carries the enrolment URI — which contains the shared secret. The
third is the one worth reading twice.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `credential_id` | `required` | The factor that went live. The subject is the *user*, so without this nothing here distinguishes a rotation from a first enrollment — the two are one fact to a consumer that has seen the earlier event, and two different rows here. |
| 2 | `method: "sms"` | `enum` | **A factor method the publisher's table cannot hold**: `mfa_credentials` carries `CHECK (method = 'totp')`, so no other value can reach the row this is read out of. A closed set of one is a promise a consumer can switch on, and widening it is a core release that adds a value rather than an edit made in a hurry. |
| 3 | `otpauth_uri` | `additionalProperties` | **The shared secret, in a query parameter, on an event that reaches every subscriber.** No TOTP secret, no `otpauth://` URI, no recovery code and no digest of one travels on this payload; the raw values exist once, in the response to whoever enrolled. |

## `examples/invalid/events/identity/mfa/disabled.data.json`

Rejected by [`schemas/events/identity/mfa/disabled.schema.json`](../../schemas/events/identity/mfa/disabled.schema.json).
The factor is unnamed and a reason was added. The reason is the interesting
refusal: it is the field a support conversation wants and the field no consumer
can use.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `method` | `required` | Which kind of factor went off. With the row deleted in the same transaction and no id on the payload, this is all a consumer still knows — a time-based code stopped working, which is the fact a support turn turns on. |
| 2 | `reason: "lost phone"` | `additionalProperties` | **Operator-typed context.** "Why" is what somebody said at a call site — a lost phone, a support ticket, another person telling them — so its values vary per operator, and a field whose values vary per operator is a field every consumer learns to ignore. The publisher omits it on purpose on both MFA events. |

## `examples/invalid/events/identity/api_key/created.data.json`

Rejected by [`schemas/events/identity/api_key/created.schema.json`](../../schemas/events/identity/api_key/created.schema.json).
The account is missing, a scope outside the vocabulary arrived, and the payload
carries the credential itself. The payload is the *grant*; a grant is not the
secret, and a schema that let the two blur could not be fixed without a major
bump.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `account_id` | `required` | The account the credential acts on. A token is granted capability and never tenancy, so this is the only field saying which account the scopes may be exercised against — and why a token presented elsewhere is refused even holding every scope. |
| 2 | `scopes[1]: "accounts:admin"` | `enum` | **A scope outside the publisher's closed set of six.** identity *refuses* rather than curates here: a CI job that asks for `accounts:admin` and silently receives `accounts:read` is a script that runs for a week and fails on the write it was written to do. There is also no scope meaning "everything" — not `*`, not `accounts:*`, not one named `admin` — because a token is granted exactly what it names. |
| 3 | `token` | `additionalProperties` | **The credential, in the clear, on an event that reaches every subscriber.** The plaintext exists exactly once, in the 201 body; the row holds a SHA-256 digest. Nor is there a `token_digest` here: not a secret either, but of no use to a consumer and a second copy of the row's most sensitive column in a store with a different retention policy. |

## `examples/invalid/events/identity/api_key/revoked.data.json`

Rejected by [`schemas/events/identity/api_key/revoked.schema.json`](../../schemas/events/identity/api_key/revoked.schema.json).
The actor is missing and the row's own reason column was copied onto the bus. The
spelling is the point: the column is `revoke_reason`, the field is not, and the
gap between them is a decision rather than an oversight.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `revoked_by` | `required` | Who withdrew it, and not necessarily who minted it — an owner may withdraw a credential another owner minted, because a live credential in an account is the account's problem. A revocation with no actor could not be attributed, and the row sets its revocation columns together or not at all. |
| 2 | `revoke_reason` | `additionalProperties` | **A field copied off the row because it exists there.** Its values are open, it is operator-typed, and it is not a fact about the credential — so it belongs to identity's own support, which is a different consumer with a different need, and not on an event every subscriber reads. |

## `examples/invalid/events/identity/oidc_client/created.data.json`

Rejected by [`schemas/events/identity/oidc_client/created.schema.json`](../../schemas/events/identity/oidc_client/created.schema.json).
The registrant is missing, a scope the provider cannot fill arrived, and the
client secret is in the payload. The scope is the subtle one: this registration
path **curates** rather than refuses, so a client is told what it got rather than
what it asked for — and a consumer reading the event needs the curated set, not
the wish.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `registered_by` | `required` | Who registered the relying party. The subject is the registration rather than the person, so without this the event says a credential exists and nothing about who put it there. |
| 2 | `scopes[1]: "phone"` | `enum` | **A claim identity cannot fill.** It has no phone column, no address column and no refresh-token store, so advertising `phone`, `address` or `offline_access` would be advertising a promise it does not keep. The registration path drops unsupported names rather than refusing the set, so this payload is what the client *got* — which is why it is a subset of the four rather than an echo of the request. |
| 3 | `client_secret` | `additionalProperties` | **Half of a credential pair, on an event that reaches every subscriber.** The raw secret exists exactly once, in the 201 response to whoever registered it, and the row holds a SHA-256 digest. No digest either: a digest of 256 random bits is of no use to anybody holding both the row and the source code. |

## `examples/invalid/events/identity/oidc_client/revoked.data.json`

Rejected by [`schemas/events/identity/oidc_client/revoked.schema.json`](../../schemas/events/identity/oidc_client/revoked.schema.json).
The actor is missing and the row's reason was copied over, exactly as on
`identity.api_key.revoked` — the same omission, the same reasoning, and the same
`revoke_reason` spelling the two schemas deliberately do not carry.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `revoked_by` | `required` | Who revoked the registration. A registration whose revocation cannot be attributed is a credential that stopped working for reasons nobody can reconstruct, and the row's `(revoked_at IS NULL) = (revoked_by IS NULL)` CHECK is the database's half of the same rule. |
| 2 | `revoke_reason` | `additionalProperties` | Operator-typed context, kept on the row where identity reads it. The row is kept rather than deleted precisely so this and the redirect URIs it held survive — an argument for the *row*, not for the bus. |

## `examples/invalid/events/billing/subscription/started.data.json`

Rejected by [`schemas/events/billing/subscription/started.schema.json`](../../schemas/events/billing/subscription/started.schema.json).
The tenancy field is missing and a money field arrived that no schema declares.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `account_id` | `required` | Without the account, the subscription cannot be correlated with the identity-side account, and every query downstream needs a lookup that will not exist. |
| 2 | `amount_minor` | `additionalProperties` | Undeclared money field. Amounts belong to the charge that is actually attempted, which is `billing.payment.succeeded`; a price here would be a second, competing source of truth for what a plan costs. |

Note on the `format` assertions: `jsonschema` silently skips `format` checks
unless a format implementation is installed. `tests/requirements.txt` pins
`rfc3339-validator` precisely so the RFC3339 assertion above cannot pass
vacuously — without it, row 5 would report no violation and this example would
look valid. The `date` format in the fleet case below is checked by
`jsonschema` itself, so it needs nothing extra; the same would not be true of an
RFC3339 assertion, which is why that one is pinned.

## `examples/invalid/fleet.invalid.yml`

Rejected by [`schemas/fleet.schema.json`](../../schemas/fleet.schema.json).
A fleet declaration written by a human, with the mistakes a human makes: the
namespace rule, the wrong manifest path, the wrong branch, a short sha, the
two-segment event types courier shipped, an OpenAPI path that resolves against
the reader's shell, an undeclared key and a read date that is not a date.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `spec: "0.1"` | `const` | Transcribed against the wrong spec. The field exists so a reader can tell how stale the numbers are, and a wrong value answers that confidently and wrongly. |
| 2 | `readOn: "not-a-date"` | `format` | The one thing that makes `fleet.yml` checkable rather than a claim is that it says when it was true. A value that is not a date has no truth to check. |
| 3 | `name: Billing_Service` | `pattern` | Names are lowercase kebab-case. A fleet entry's name is matched against the first segment of every type the service publishes, so an underscore here silently disables that comparison instead of failing it. |
| 4 | `manifest: manifest.yml` | `const` | Every cafaye service names its manifest `cafaye.yml`. A linter resolving a service's declaration needs one pinned path, not a convention it has to know. |
| 5 | `branch: main` | `const` | The cafaye primary branch is `master` everywhere (PLAN.md §1). A declaration read from any other branch is not a declaration about the fleet. |
| 6 | `sourceCommit: "5475352"` | `pattern` | A short sha is enough to read by and not enough to re-read. The point of recording a commit is that the next reader can re-read the exact bytes the claim was made from. |
| 7 | `events[0]: billing.customer.Created` | `pattern` | `Created` is not lowercase snake_case, which forks the topic away from every existing subscription to the type. |
| 8 | `events[1]: plan.created` | `pattern` | Two segments: no service prefix. This is courier's mistake five times over, and it is the reason `fleet.yml` exists rather than a checklist — the difference between catching it here and shipping it to master. |
| 9 | `publishes:` | `additionalProperties` | Undeclared key. A fleet declaration is closed for the same reason a manifest is: a key the schema does not know about cannot be validated, and a linter that ignores it reports a clean fleet. |
| 10 | `api: ./openapi.yaml` | `pattern` | A `./` prefix resolves against the reader's working directory, not the repository root. `api` transcribes what the service's manifest declares in `exposes.api`, so a path that does not open in that service's checkout is a claim about a document nobody can read. An absolute path and a bare URL fail here for the same reason. |
| 11 | `telemetry.endpointVariable: muse-otel-endpoint` | `pattern` | The one contract a self-hoster is told to set is `<SERVICE>_OTEL_ENDPOINT` — **uppercase**. A lower-case or hyphenated spelling is an environment variable nothing reads, and six services each spelling it their own way is the exact failure core's observability spec exists to prevent. |
| 12 | `telemetry.signals[1]: telepatry` | `enum` | Not one of the three OTel signals. A closed enum is what lets `caf contract lint` tell a service which signals a collector config has to accept, and a typo here would otherwise be a signal nobody configures. |
| 13 | `telemetry.probes: maybe` | `type` | Not a boolean. Whether a service serves HTTP is a fact with two answers, and `maybe` is how "nobody has checked" gets written down. |

## `examples/invalid/events/courier/email/queued.data.json`

Rejected by [`schemas/events/courier/email/queued.schema.json`](../../schemas/events/courier/email/queued.schema.json).
The notification id is missing and a credential leaked into a fan-out. Both are
real: courier's own `Courier.DeliverTest` asserts the second (`refute "url" in
Map.keys(event.data)`), which is why the shape is here rather than left to
review.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `message_id` | `required` | A queued message with no notification id cannot be joined to its `courier.email.delivered`, which is the entire reason the event exists: measuring how long a message waited. |
| 2 | `url` | `additionalProperties` | A verification link is a credential, and this envelope goes to every subscriber on the bus. It is in the caller's payload, not in the event. |

## `examples/invalid/events/courier/email/delivered.data.json`

Rejected by [`schemas/events/courier/email/delivered.schema.json`](../../schemas/events/courier/email/delivered.schema.json).
The recipient is missing and a provider's own message id turned up — the field
that exists in courier's test fixture and in no line of courier's code.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `user_id` | `required` | Without the recipient, a consumer cannot answer "who got this?" without asking courier, and cannot correlate the send with anything identity knows about. |
| 2 | `provider_id` | `additionalProperties` | A field the publisher never emits. `Courier.EventsTest` carries `provider_id` in its fixture map, but `Courier.Deliver` builds the payload from four values and one of them is not this. Declaring it in core would be a contract that promises a value no message carries. |

## `examples/invalid/events/courier/email/bounced.data.json`

Rejected by [`schemas/events/courier/email/bounced.schema.json`](../../schemas/events/courier/email/bounced.schema.json).
The address that bounced is missing, and a provider's SMTP diagnostic arrived
anyway.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `email` | `required` | The hard-bounce suppression list is keyed on the address. A bounce without one is an event nobody can act on, which is the worst kind. |
| 2 | `smtp_response` | `additionalProperties` | The provider's diagnostic is real and belongs in the payload eventually — but courier has no receiver for it yet, and core does not declare a field no publisher emits. It arrives with the webhook handler, and a new optional field is a patch. |

## `examples/invalid/events/courier/email/complained.data.json`

Rejected by [`schemas/events/courier/email/complained.schema.json`](../../schemas/events/courier/email/complained.schema.json).
The recipient's display name is in a fan-out payload, and the message type is
gone.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `notification_type` | `required` | A complaint suppresses every type immediately, so the type is not what a consumer acts on — it is what they tell the user they objected to. Without it the event says a person was angry and not about what. |
| 2 | `name` | `additionalProperties` | The display name comes from the mail payload, and `Courier.DeliverTest` asserts it is not in the event. It is the recipient's name on every subscriber's bus, for a message about a complaint they did not raise. |

## `examples/invalid/events/courier/notification/suppressed.data.json`

Rejected by [`schemas/events/courier/notification/suppressed.schema.json`](../../schemas/events/courier/notification/suppressed.schema.json).
A `message_id` on an event about a send that never happened — the payload is the
`delivered` one with a `reason` bolted on.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `reason` | `required` | The whole event is the reason. A suppression with no reason is indistinguishable from a delivery that was lost, and the two want opposite responses. |
| 2 | `message_id` | `additionalProperties` | Nothing was rendered, addressed or sent, so there is no notification and no id for one. This is the mistake the catalog's subject row exists to prevent — the entity is the recipient — and it is why this payload is not the `delivered` payload with one more field. |

## `examples/invalid/events/muse/tokens/consumed.data.json`

Rejected by [`schemas/events/muse/tokens/consumed.schema.json`](../../schemas/events/muse/tokens/consumed.schema.json).
A nameless model, and the price table that produced the cost travelling with it.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `model: ""` | `minLength` | A blank model id is not a model. Every consumer of this event groups spend by model, and a blank groups every unrouted call together with nothing. |
| 2 | `input_micros`, `output_micros` | `additionalProperties` | The per-1k price is real, it is in the publisher's own `Price` object, and it is deliberately **not** in the event: a price moves, and a payload that carries one says the cost and the price were true at the same instant. The cost is already here. A price in the payload is a field every consumer would read as authoritative and that is wrong the next time the price table changes. |

## `examples/invalid/events/billing/customer/created.data.json`

Rejected by [`schemas/events/billing/customer/created.schema.json`](../../schemas/events/billing/customer/created.schema.json).
The owner is gone and a flat `account_id` turned up in its place — the shape a
consumer would ask for, and one billing cannot produce.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `owner` | `required` | `owner` is the only field on the payload that says who pays. Without it a customer cannot be attached to a user or an account, and no other field fills the gap. |
| 2 | `account_id` | `additionalProperties` | A cafaye account id, flat. The owner is `{type, id}` and the id is a uuid, because the owner may be a `User` as well as an `Account` and the payload has to say which. A flat `account_id` is the third vocabulary in a fleet that already has two (**D7**), and it is not one billing emits. |

## `examples/invalid/events/billing/plan/created.data.json`

Rejected by [`schemas/events/billing/plan/created.schema.json`](../../schemas/events/billing/plan/created.schema.json).
Money at the top level instead of inside `price` — the flattening that turns a
price into two fields nobody can require together.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `price` | `required` | Without a price the plan is a name and a cadence. Splitting it into `amount_minor` and `currency` at the top level is how a consumer ends up reading a price with no currency attached. |
| 2 | `amount_minor`, `currency` | `additionalProperties` | Undeclared money fields at the root. A currency is not a property of a plan; it is a property of an amount, and nesting it is what stops `1900` from ever being read as dollars, yen or anything else. |

## `examples/invalid/events/billing/plan/updated.data.json`

Rejected by [`schemas/events/billing/plan/updated.schema.json`](../../schemas/events/billing/plan/updated.schema.json).
The plan's own id is missing and the payload carries a diff — the shape most
tempting for an `updated` event, and the one that makes a consumer merge state.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `id` | `required` | The plan. Without it the event cannot be attributed, and a `billing.plan.updated` nobody can attach to a plan is a plan that changed somewhere. |
| 2 | `changed_fields` | `additionalProperties` | A list of what moved. The payload is the plan's whole current state and there is no diff: a consumer replaces its copy, and a `changed_fields` list would make it merge one — into state that can drift from the publisher's on every field the list forgot. The publisher also only emits this event when something really changed, so the list is redundant as well as wrong. |

## `examples/invalid/events/billing/subscription/started.data.json`

Rejected by [`schemas/events/billing/subscription/started.schema.json`](../../schemas/events/billing/subscription/started.schema.json).
The subscription is gone, and the two ids that v0.2's shipped schema required are
in its place. This is the schema rewrite recorded as **D10**, and this file is
the mistake it exists to prevent.

**The row below is right and its reason used to be wrong, and both halves of that
are the point.** The rejection is real: this schema is closed with
`additionalProperties: false` and it refuses `plan_id` and `account_id` today. The
reason it used to give — that billing has no subscriptions table and so has no
such fields to send — stopped being true when billing grew one, and the
correction is recorded in **D39** and in the schema's own `$comment`. An invalid
example whose *rejection* is right and whose *justification* is false teaches a
reader the same falsehood as a valid example would, one layer further from the
schema that is entitled to know.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `subscription_id` | `required` | The subscription, and the envelope's `subject`. Without it there is nothing to correlate, nothing to join a later `updated` or `canceled` to, and nothing a consumer can act on. |
| 2 | `plan_id`, `account_id` | `additionalProperties` | The two fields v0.2's shipped schema **required** and this one does not name. What replaced them was `price_id` and `customer_id` — the processor's ids, on the reasoning in **D10** — and for four days that was the whole story: billing had no subscriptions table, so it had no `sub_…`, `pln_…` or `acc_…` to send, and a schema requiring them described a world billing did not live in. **billing now has a `subscriptions` table** (`db/migrate/20260930000007_create_subscriptions.rb`) and emits both fields as bare uuids, so "billing has no such fields" is false and this file is no longer entitled to say it. The rejection is unchanged and the disagreement is now bigger than these two fields: the publisher's real payload carries `currency` and `started_at` as well, and this schema requires `processor`, `processor_event_id`, `kind` and `customer_id`, which it never receives. **D39** is the open decision about whether core's contract follows billing's payload; the evidence, the source lines and the commit are in the schema's `$comment`. The *values* here are bare uuids rather than the `pln_…`/`acc_…` they used to carry, and that remains a correction rather than a loosening: what this example demonstrates is that the FIELD is rejected, so a second fiction in the value only taught the fleet an id shape no publisher mints (**D37**). |

## `examples/invalid/events/billing/subscription/updated.data.json`

Rejected by [`schemas/events/billing/subscription/updated.schema.json`](../../schemas/events/billing/subscription/updated.schema.json).
The customer is missing and a delta arrived instead — the second half of the
same merge trap as `plan.updated`.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `customer_id` | `required` | A change nobody is charged. Without the customer, an update cannot be attributed to a subscription's owner, which is the only reason anyone would want to know the quantity changed. |
| 2 | `delta` | `additionalProperties` | `{quantity: 1}` — what moved, not where it is now. Applying a delta to state the consumer may not have (replay, out-of-order delivery, a consumer that started reading halfway) silently produces a wrong quantity. The payload is the processor's current state; there is nothing to merge. |

## `examples/invalid/events/billing/subscription/canceled.data.json`

Rejected by [`schemas/events/billing/subscription/canceled.schema.json`](../../schemas/events/billing/subscription/canceled.schema.json).
The final status is missing, and the moment somebody *asked* for the cancellation
turned up next to the moment it happened.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `status` | `required` | The subscription's final state. This type exists to say a cancellation took effect, and `canceled_at` alone says when without saying what the subscription then was. |
| 2 | `cancel_requested_at` | `additionalProperties` | The request, not the effect — and the whole distinction this event is named for. A consumer that acts on a request stops serving a subscription that is still running and still paid for; the catalog row for this type says so in one clause. If the platform wants the request time it belongs in a request, not smuggled into the effect. |

## `examples/invalid/events/billing/payment/succeeded.data.json`

Rejected by [`schemas/events/billing/payment/succeeded.schema.json`](../../schemas/events/billing/payment/succeeded.schema.json).
Three faults in one: the amount is gone, a cafaye plan id turned up, and the
payload claims to be *both* source shapes at once — which is the mistake the
`oneOf` exists to make impossible.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `amount` | `required` | The money. A settled charge with no amount is an event a consumer can log and not reconcile, which is the same as an event that was never published. |
| 2 | `plan_id` | `additionalProperties` | A plan id on a **payment**. A settled charge is not about a plan — the subscription it belongs to already names it, and this type's two shapes name an invoice or a Checkout session, not a plan. (`billing.payment.succeeded` is the one billing payload where D10's reasoning still holds end to end: billing emits no `plan_id` on a payment. It does on the three **subscription** payloads, and **D39** records why that sentence stopped being true for those.) |
| 3 | `invoice_id` *and* `checkout_session_id` | `oneOf` | A charge is either invoice-backed or Checkout-backed, never both. Flattening the two shapes lets this through, and then every consumer has to work out which it got — by checking for a field that may be present and may be null, which is the ambiguity `oneOf` removes (**D11**). |

## `examples/invalid/events/billing/payment/succeeded.email.data.json`

Rejected by [`schemas/events/billing/payment/succeeded.schema.json`](../../schemas/events/billing/payment/succeeded.schema.json).
The recipient fact arrived as a number. Everything else on the payload is the
valid invoice-backed shape; this is the one field whose type is wrong, and it is
the field billing adds only when the customer has an address on file.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `email: 42` | `type` | The recipient fact is a string when it is present, and absent — never null — when it is not. A number is neither: not an address, and not the absence of one. Declared `type: string` (not `[string, null]`) because billing never sends null, so a consumer that reads `email` as possibly-null is reading a shape the publisher cannot produce. |

## `examples/invalid/events/billing/payment/failed.data.json`

Rejected by [`schemas/events/billing/payment/failed.schema.json`](../../schemas/events/billing/payment/failed.schema.json).
The invoice is missing, and a second amount arrived — the one that says zero.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `invoice_id` | `required` | The invoice whose collection failed. Without it a decline cannot be attributed to a charge, retried, or escalated — and a failed payment with no identity is a failed payment with no follow-up. |
| 2 | `amount_paid` | `additionalProperties` | A second money field, and the dangerous one: on a failed charge it is `0`, which is truthy and reads as "nothing was collected" to a consumer that wants the charge size. The publisher's own comment names this exact bug — the naive `amount_paid \|\| amount_due` fallback reports a declined 29.00 as a settled 0.00. `amount` is the amount due; there is no second amount. |

<!-- telemetry block: added by the observability packet -->

Added by the observability packet. Every file here is a mistake the directive
names, and the reason each one matters is in [docs/observability.md](../../docs/observability.md).

## `examples/invalid/telemetry/span-naming.identifier.invalid.json`

Rejected by [`schemas/telemetry/span-naming.schema.json`](../../schemas/telemetry/span-naming.schema.json).
A span name with a user id interpolated into the last segment — the mistake that
reads as diligence in a code review.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `name: "muse.user.usr_01j9z8qk5m4n7p2r3t6v8w9x0a"` | `pattern` | A span name is `<service>.<operation>[.<target>]`, and a segment is at most fifteen characters. `usr_01j9z8qk5m4n7p2r3t6v8w9x0a` is thirty-two. The length bound is doing the work, not a cafaye-id pattern: a name that interpolates a value is one span per value, and a trace backend is a search engine whose index stops being useful well before anyone reports an error. |
| 2 | `target: "usr_01j9z8qk5m4n7p2r3t6v8w9x0a"` | `pattern` | Same value in the field that exists to disambiguate the operation. A target is a *class* of thing (`provider`, `db`, `queue`), never an instance of one. |

## `examples/invalid/telemetry/metric.tenant-id-measurement.invalid.json`

Rejected by [`schemas/telemetry/metrics.schema.json`](../../schemas/telemetry/metrics.schema.json).
The failure mode the whole prohibition exists for, in the shape a well-meaning
engineer writes on a Friday.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `measurementAttributes.tenant_id` | `not` | **The specific failure the directive names.** OpenTelemetry caps a metric stream at 2000 distinct attribute combinations and, on overflow, folds everything into one `otel.metric.overflow=true` point and **drops every measurement attribute**. Totals stay correct and every per-dimension breakdown silently undercounts — the dashboard renders, the total looks right, the breakdown is wrong, and nothing anywhere reports an error. `tenant_id` is on the resource list, which is exempt from the cap and survives on the overflow point; the prohibition is a prohibition *with a destination*. |
| 2 | `measurementAttributes.tenant_id` | `additionalProperties` | Refused twice on purpose. It is absent from the allowlist *and* named in a `not`, so adding it to the allowlist later does not quietly succeed. A rule enforced once is a rule a well-meaning commit can undo. |

The rest of the document is legal — the same metric with
`measurementAttributes: {http.route: /v1/users/{id}}` validates, which
`test_a_tenant_id_measurement_attribute_is_rejected` asserts, so this example is
about `tenant_id` and not about the metric being malformed.

## `examples/invalid/telemetry/redaction.prompt-attribute.invalid.json`

Rejected by [`schemas/telemetry/redaction.schema.json`](../../schemas/telemetry/redaction.schema.json).
An allowlist with a prompt attribute on it — the single hardest rule in the
packet, in the shape it actually arrives.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `allowed[2]: "llm.prompt"` | `not` | The redaction boundary is encoded as an **allowlist**, default-deny, so a span attribute that is not on the list is not emitted. "Don't log prompts" in prose has been tried across this fleet and does not hold; the realistic leak is not an attacker, it is a well-meaning `llm.prompt` added in six months by someone debugging a routing decision, in a service whose prompts are other customers' data. The whole file is a valid policy except this one name, which is the point: a policy is not safe because its author was careful. |

Note the other half: the same example still declares the correct
`llmCallAttributes` — model, token counts, latency, finish reason. The positive
side is in the schema because a policy that only says what may **not** be
recorded is not implementable; somebody debugging a routing decision needs to
know what to reach for instead.

## `examples/invalid/telemetry/otel-endpoint.buffered.invalid.json`

Rejected by [`schemas/telemetry/otel-endpoint.schema.json`](../../schemas/telemetry/otel-endpoint.schema.json).
A "disabled" exporter that is not actually disabled.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `noOp.buffering: "ring"` | `const` | A queue that accepts spans and retains them is a memory leak with a telemetry-shaped trigger: requests succeed normally while the heap fills with spans nobody will ever read. A disabled path that still dials out is worse than no telemetry support at all. |
| 2 | `noOp.retry: "exponential-backoff"` | `const` | A retry loop against an endpoint that is not there is a thread waking on a timer for the life of the process — and it is invisible in every dashboard, because nothing is being recorded. |
| 3 | `noOp.warnings: "per-attempt"` | `const` | A warning per export attempt fills the service's own log store with the news that telemetry is off. That is how a self-hoster discovers turning telemetry off is unsupported, which is the exact opposite of what an escape hatch is for. |
| 4 | `noOp.startupCost: "dial"` | `const` | A dial at boot makes a service's availability depend on a component that ships with the product rather than with the deployment. |
| 5 | `disabledBy` | `minItems` | Only three entries, and `OTEL_LOGS_EXPORTER` is missing. The floor exists so a declaration cannot document a no-op that covers only some signals — a service that still phones home for metrics is a failure discovered by a customer's invoice rather than by a test. |

## `examples/invalid/telemetry/probes.empty-readyz.invalid.json`

Rejected by [`schemas/telemetry/probes.schema.json`](../../schemas/telemetry/probes.schema.json).
A `readyz` that checks nothing — the failure the probes schema exists to
prevent, and the one that is invisible because the endpoint returns 200.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `readyz.checks: []` | `minItems` | `readyz` **actually checks dependencies**. Without it a load balancer cheerfully routes traffic into a service whose database is gone, and every health dashboard shows green. darkroom is the pattern to standardise on: `/healthz` never touches a dependency, `/readyz` really runs `select 1`. |
| 2 | `healthz.checks: []` | — | **Valid, and deliberately.** Liveness is *unconditional*: a liveness probe that fails on a dependency tells the orchestrator to restart a process that is fine, turning a database outage into a fleet-wide crash loop and destroying the evidence needed to diagnose it. The schema pins this with `maxItems: 0`, so a `healthz` that starts consulting the database cannot validate either. |

## `examples/invalid/telemetry/error-type.undeclared.invalid.json`

Rejected by [`schemas/telemetry/traces.schema.json`](../../schemas/telemetry/traces.schema.json).
**The example this whole vocabulary exists for.** A span that is correct in every
other respect, whose error class is well-shaped and not in the fleet's list.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `attributes.error.type: "user_42_email_invalid"` | `enum` | `user_42_email_invalid` is snake_case, is twenty-two characters, and satisfies the pattern and the length cap perfectly — which is exactly why it is the right example. It is a class with a **user's id interpolated into it**, and on the metric side that is one series per user against the same 2000-combination cap `tenant_id` blows, with the same silent undercount and the same rendering dashboard. Nothing about the *shape* of a value can catch this; only a closed set can. `test_a_well_shaped_but_undeclared_error_class_is_rejected` asserts the value passes the shape and the cap **before** asserting the rejection, so it cannot pass because the pattern caught it — it passes only if the vocabulary did. |

## `examples/invalid/telemetry/metric.error-type-undeclared.invalid.json`

Rejected by [`schemas/telemetry/metrics.schema.json`](../../schemas/telemetry/metrics.schema.json).
The same undeclared class, on the signal where it actually does the damage. Traces
survive an unbounded value as an expensive index; a metric does not.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `measurementAttributes.error.type: "user_42_email_invalid"` | `enum` | Byte-identical `enum` to the traces and logs signals. They have to be: a class that means one thing on traces and another on metrics is three taxonomies wearing one name, and it is also what makes the semconv rule that `error.type` is *identical* on a span and on its metric for the same operation enforceable — no JSON Schema can compare two documents, so the coupling has to be structural. |

## `examples/invalid/telemetry/span.error-status-no-type.invalid.json`

Rejected by [`schemas/telemetry/traces.schema.json`](../../schemas/telemetry/traces.schema.json).
`status.code: "error"` with no class — the claim with nothing behind it.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | *(absent)* `attributes.error.type` | `required` | A status of `error` is a claim that the operation failed, and the fleet-wide "is this an error" filter reads that claim. A span that makes it without saying what went wrong is counted by every error-rate query and cannot be explained by any of them — the wall of ungrouped text the user asked whether cafaye could avoid. core-04 stated this obligation in a `description`; with the attribute deleted, `span.muse.json` still validated, so this is a constraint now rather than a sentence. |

## `examples/invalid/telemetry/span.success-with-error-class.invalid.json`

Rejected by [`schemas/telemetry/traces.schema.json`](../../schemas/telemetry/traces.schema.json).
A successful span carrying an error class — the other direction of the same rule.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `attributes.error.type: "timeout"` with `status.code: "ok"` | `const` | **The absence is the load-bearing marker, not an omission.** On a duration histogram the samples carrying the class are the errors and every other sample is a success; that is how error rate is computable without putting a message in a label. So a success that carries one does not add noise — it moves the **numerator**, and the error rate becomes a number nobody can trust. |

## `examples/invalid/telemetry/span.status-mirror-disagrees.invalid.json`

Rejected by [`schemas/telemetry/traces.schema.json`](../../schemas/telemetry/traces.schema.json).
`otel.status_code: "ERROR"` on a span whose own status says `ok`.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `attributes.otel.status_code: "ERROR"` with `status.code: "ok"` | `const` | `otel.status_code` exists so a log-indexed query can filter without parsing the span, and `status.code` is the field of record. The moment the mirror can disagree with the field, a query that reads the mirror answers a different question from the predicate the fleet-wide view uses — and nothing anywhere reports that they differ. This is not a separate rule: without it the obligation in the row above is about a span with two statuses, which has no status to be obliged. |

<!-- SLO block: added by the SLO and error-budget packet -->

Added by the SLO packet. Each file is one mistake the rulings name, and each
one differs from its valid sibling in as few lines as the mistake takes — see
[docs/slo.md](../../docs/slo.md).

## `examples/invalid/telemetry/slo.perfect.invalid.yaml`

Rejected by [`schemas/telemetry/slo.schema.json`](../../schemas/telemetry/slo.schema.json).
The SLO nobody can keep: an objective of 100% and a thirty-day period. Both are
the same mistake — a number chosen to look safe rather than chosen to be met —
and both are the numbers a service reaches for by accident, because they are
what a template's defaults usually are.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `objective: 100` | `exclusiveMaximum` | An objective of 100% has an error budget of **zero**, so no burn rate is worth interrupting anyone for and the alert can only ever be *reacted to* — noticed after the fact rather than paged before it. `exclusiveMaximum`, not `maximum`, is the whole rule (R8); with a comment instead of a keyword, deleting the comment deletes it. |
| 2 | `period: 30d` | `const` | Thirty days contains 4.3 weekends, so the same weekend maintenance costs a different fraction of the budget every month and the error budget stops being comparable to itself (R3). 28 days is integral weeks: always four weekends. A period nobody wrote down is a period somebody assumed, and Sloth's own default is `30d`, so the assumption has to be refused rather than inherited. |

## `examples/invalid/telemetry/slo.page-on-low-tier.invalid.yaml`

Rejected by [`schemas/telemetry/slo.schema.json`](../../schemas/telemetry/slo.schema.json).
A `low` SLO that pages. **Nothing else about this document is wrong** — which is
what makes it the example: the mistake that reaches production is the one made
in the one field nobody reads carefully.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `tier: low` with `page_alert.disable: false` | `const` | **The tier alone decides whether a page is generated**, and the schema derives the switch rather than letting the service choose it (R4). The cost is not the page: the self-hoster who has to mute a 3am page about a twenty-user deployment has also muted the `critical` SLO on the same service, and the whole instrument is gone in one gesture. |

## `examples/invalid/telemetry/slo.window-override.invalid.yaml`

Rejected by [`schemas/telemetry/slo.schema.json`](../../schemas/telemetry/slo.schema.json).
A service that carries its own burn-rate windows. Sloth accepts
`--slo-period-windows-path` precisely so a project can, and the resulting rules
look completely ordinary — which is the problem: two dashboards that both say
"error budget" and disagree about the threshold.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `windows:` | `additionalProperties` | The window catalog is pinned **once, in core** (R2), for the whole fleet, and a per-service override is how the fleet ends up with two definitions of a burn rate. `additionalProperties: false` rather than a bespoke rule, because an undeclared key is exactly what this object refuses everywhere else. |

## `examples/invalid/telemetry/slo-metrics.denylisted.invalid.json`

Rejected by [`schemas/telemetry/slo-metrics.schema.json`](../../schemas/telemetry/slo-metrics.schema.json).
The catalogue with an infrastructure metric in it — `node_memory_usage_bytes`
counted as the invoice SLI's denominator.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `slis.invoice_computed.totalMetric: "node_memory_usage_bytes"` | `const` | Not the metric this SLI counts. The whole catalogue is `const` per field, so a service cannot invent a numerator. |
| 2 | the same field | `not` | **Refused twice on purpose**, as `metrics.schema.json` refuses `tenant_id` twice: the `const` says it is not this SLI's metric and the `not` says it is not *any* SLI's metric. A rule enforced once is a rule a well-meaning commit undoes — adding an entry for "CPU headroom" would otherwise validate on the strength of a `const` nobody re-read. An SLO on a CPU is not an SLO on behaviour (R6). |

The second denylist — the unbounded dimensions — is the other half of the same
`not`, and it is why the two lists are separate properties with separate
reasons: `metrics.schema.json` already bars `tenant`, `user_id`, `account_id`
and `request_id` on the 2000-combination-cap grounds, and the reasons a reader
needs are *different*. See
[`docs/slo.md`](../../docs/slo.md#two-denylists-because-there-are-two-reasons).

## `examples/invalid/gate.no-proof.yml`

Rejected by [`schemas/gate.schema.json`](../../schemas/gate.schema.json).
A well-formed repository whose declaration says `bin/prime` is its gate and
declares no proof — so nothing in the format would ever distinguish a gate that
ran from a command that exited zero. This is the false green written down.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `gate.proof: []` | `minItems` | A gate with no proof is a claim, and a claim is what this file exists to stop being. There is no legal empty list, deliberately: a `minItems: 0` here would make "I forgot to say how you know it ran" a valid declaration. |

## `examples/invalid/gate.shell-string.yml`

Rejected by [`schemas/gate.schema.json`](../../schemas/gate.schema.json).
The exact command that produced this fleet's one recorded false green:
`… | tail -45; echo "PRIME EXIT=$?"` under zsh, where there is no `PIPESTATUS`
and `$?` is the exit code of `tail`, which is always zero.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `gate.command[0]` | `not` | A command is an **argv**, so an argument may not contain anything a shell would have acted on. A pipeline is something that happened to an argv somewhere upstream, and a declaration that records it has recorded the accident rather than the gate. The allowed set is asserted in both directions by `test_the_gate_schema_refuses_a_shell_string_in_any_command`: `= , : @ + %` and spaces stay, because a real argument needs them. |

## `examples/invalid/gate.requirement-without-command.yml`

Rejected by [`schemas/gate.schema.json`](../../schemas/gate.schema.json).
A gate that admits it is not self-contained, names a migrated PostgreSQL, and
then gives the reader nothing to run. This is the identity defect in a
different costume: a requirement that cannot be executed is a pointer to a page
that does not exist.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `external.requirements[0].satisfy.command` | `required` | `satisfy` must carry a **command**, not an `unmet` description of what happens without one. `satisfy.command[0]` containing a `/` is checked against this repository; a bare name is a claim about the machine and is reported as unproven rather than guessed at. |

## `examples/invalid/gate.undeclared-key.yml`

Rejected by [`schemas/gate.schema.json`](../../schemas/gate.schema.json).
A declaration carrying a `cache` block — the most tempting key in the world to
reach for, because an `actions/cache` `restore-keys` restores across branches
and a cached test report from another branch is a report about another branch.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `cache` (at the root) | `additionalProperties` | The same reason every other core schema closes its levels: an undeclared key should be an error, not a silent no-op that reads as a decision somebody made. The rule against caching a report lives in `docs/gate.md` and in MD12; leaving the key legal would leave a way to write it. |

<!-- tenancy block: added by the tenant-isolation packet (core-15) -->

Added by the tenant-isolation packet. Four mistakes, and each one is a way the
declaration stops describing the boundary. See
[docs/tenancy.md](../../docs/tenancy.md) for why this format exists instead of a
grep.

## `examples/invalid/tenancy.refuses-instead-of-absent.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
A service that scopes correctly on every statement and asserts the wrong thing
in its tests. Nothing else about this file is wrong, which is what makes it the
example: the mistake that reaches production is the one made in the one field
nobody reads carefully.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `negative.asserts: forbidden` | `const` | **The constraint the whole format is built on.** Cross-tenant access must be *indistinguishable from nonexistence*: `nil`, `[]`, `None`, `NotFound`, an empty list — anything that could also mean "there is no such row". A `403` confirms the id exists, and a caller walking ids learns exactly which ones do. That is an enumeration oracle, and the fleet already ships one. identity's own `TestRevokeCannotCrossTenants` documents the rule from the other side: `ErrNotAuthorized` is right for "you are not a member of this account", and `ErrNotFound` is right for "here is a key in an account you *are* a member of, and it is not this one". The second must not confirm existence. See **D33**. |

## `examples/invalid/tenancy.honest-zero-liar.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
`accountScoped: false` with four declared entry points — the omission wearing a
declaration. It is the shape that made eight of this fleet's ten services
unaskable: silent, indistinguishable from a service that simply forgot, and
therefore nobody's job until a customer reads another customer's data.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `accountScoped: false` with `entryPoints` non-empty | `maxItems` | A zero is a claim, and the claim is checked in both directions. An empty list is legal **only** when `accountScoped` is false, so a service that genuinely holds no customer rows can say so with an explicit zero instead of omitting itself. The reverse — `true` with nothing listed — is refused by `minItems: 1` on the same array, because a service that says it scopes by account and names no way it does is the same omission facing the other way. |

## `examples/invalid/tenancy.bind-without-a-parameter.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
Both halves of the one scoping failure a predicate check cannot see:
`account_id = $2` is still in the statement and nothing passes `$2`, so every
"does this query scope" check in the fleet answers yes.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `mechanism: bind-parameter` with no `binds` | `required` | A bind-parameter mechanism with no parameter named is a query scoped on paper. The name is what makes `tenancy.bind-missing` checkable: the account has to be identifiable on the declared line, or "the account is passed here" is a claim. |
| 2 | `mechanism: query-filter` **with** `binds` | `not` | **Refused on purpose, the way `metrics.schema.json` refuses `tenant_id` twice.** Row 1 makes `binds` required for one mechanism; without this, adding it to the others would quietly validate, and a field that is load-bearing for one mechanism and decoration for three is how a reader starts believing it is checked everywhere. |

## `examples/invalid/tenancy.nowhere.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
A declaration written from memory that stops at `subject`, and a service whose
boundary is "enforced" in a sibling repository's tree.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `enforced.file` (absent) | `required` | The file and the line are the difference between a declaration and a description. A declaration that points at nothing is worse than no declaration, because it reads as a boundary somebody looked at — `tenancy.location-missing` and `tenancy.line-missing` exist for exactly this, and a format that made the file optional would have nothing to check. |
| 2 | `scope.sources[0]: ../billing/db/queries.sql` | `not` | The checker reads inside the repository it was pointed at and never fetches one. A boundary enforced in a *different service's* query file is not this service's boundary, and a `..` in a declared source would make one repository's answer depend on a sibling's checkout. |

<!-- rls block: added by the database-half packet (core-tenancy-lint-01) -->

Added by the database-half packet. Three more mistakes, and each one is a way the
database half of the declaration stops describing anything. See
[docs/tenancy.md](../../docs/tenancy.md) for the ledger of Supabase's database
advisor these adapt, and for why the FORCE rule is cafaye's own.

## `examples/invalid/tenancy.forced-without-the-bit.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
**The mistake the whole packet exists for**, and nothing else in the file is
wrong: the policies are real, the roles are named, the clause carries the
identity wrapped in `(select …)`, the denial shape has all three arms.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `rls.tables[0].forced: false` | `const` | **Postgres does not apply row-level security to a table's OWNER unless the table is set `FORCE ROW LEVEL SECURITY`.** A service owns the tables it created in its own schema, so this service's runtime role reads every row in `assets` while three policies sit in `pg_catalog` looking like a boundary. Nothing errors and no query returns a wrong answer, because a policy that is never evaluated is not a policy that fails. Postgres documents this in the CREATE TABLE reference and **not** in the row-level-security guide, and Supabase's advisor collects `relforcerowsecurity` for its table list and never judges it. `forced: false` cannot be *described* here, because a format that can describe a half-enforced table is a format that will contain one. The DDL half is `tenancy.rls-owner-bypass`, a FAILURE, proved by deleting one `force` line from the fixture and watching that finding name that table and nothing else. |

## `examples/invalid/tenancy.public-policy.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
A policy applied to `PUBLIC`, which is what you get by not writing a `to` clause
at all — the most common spelling, because nothing is the easiest thing to type.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `rls.tables[0].policies[0].roles[0]: public` | `not` | A `create policy` with no `to` clause applies to `PUBLIC`: every role, including the migration role and every role this service adds in a year when somebody needs a read-only role for a support query. Supabase's guide says to name the role and its advisor has **no lint for it** — a gap rather than a decision, since a lint that existed for every other unnamed role would have caught this. Cafaye closes it because with one named runtime role there is no case where PUBLIC is right. The DDL half — a policy naming no role at all — is `tenancy.rls-permissive`, a FAILURE. |

## `examples/invalid/tenancy.two-arms.yml`

Rejected by [`schemas/tenant-isolation.schema.json`](../../schemas/tenant-isolation.schema.json).
Two denial arms, no positive control. Every arm present is correct on its own
terms; what is missing is the one with the information in it.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `negative.cases` (2 entries) | `minItems` | **The shape that looks like coverage.** "Does an unauthenticated request fail" is satisfied by a table with no policy at all, by a table with no predicate at all, and by a service whose database is switched off — all three are the BUG rather than the fix. The claim that carries information is the third arm: `own-account` asserts the account's own valid credential **sees its rows**. Without it, two negative arms are satisfied perfectly and forever by a service that returns nothing to anybody. `maxItems: 3` sits beside the `minItems` for the other reason: an open upper bound is how a fourth arm gets added, and a fourth arm would be a case about something this format has no opinion on. |

## `examples/invalid/reserved-properties.cafaye.invalid.yml`

Rejected by [`schemas/cafaye.manifest.schema.json`](../../schemas/cafaye.manifest.schema.json).
Four reservations that read as protection and protect nothing. The failure mode
this rule has to catch is not a tombstone that is missing — it is a tombstone
that looks like it holds a name and does not, which is indistinguishable from a
service that checked and found nothing to reserve.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `name: InvoiceId` | `pattern` | Not a property name. Property names are lowercase snake_case — the grammar every `properties` key in `schemas/events/**` uses. A camelCase reservation reserves a string no generated source ever carried, so the real name stays free for exactly the reuse this block exists to prevent. |
| 2 | `removedFrom: billing` | `pattern` | Not a contract surface. A surface is an event type (`<service>.<entity>.<action>`) or an OpenAPI components schema path. Without one there is nothing to compare the name against, so the entry can never be shown to be stale and never can be shown to be real — the shape the checker cannot answer, which this repository treats as a failure rather than a pass. |
| 3 | `currency` on an entry | `additionalProperties` | Undeclared field inside a reservation entry. The block is closed at every level like the rest of this schema, so a misspelt field is an error rather than a field nobody read. |
| 4 | the same `customer_ref` entry twice | `uniqueItems` | A double-paste, not a second reservation. Note what it does **not** catch: the two copies have to be byte-identical, so a reworded `note` makes a different entry and the array accepts it. Exact equality is the check that is available, not the one that would be ideal. |

A fifth mistake is in this file and is **not** schema-caught: entry 3's real
defect is that `billing.invoice.paid` is a surface this manifest does not
publish, so nothing was ever removed from it and `paid_at` is not reserved at
all. That is the stale entry — it will block a legitimate future `paid_at`
forever and nothing reports it while it does — and it is
`harness/reserved_check.py`'s finding to make, not a schema pattern's. See
`harness/tests/fixtures/reserved-properties/` for a fleet where it fires.

## Adding a negative case

A new `examples/invalid/` file needs, in the same commit: the file itself, its
row in the table above, and an `assert_keywords` entry in
`tests/test_specs.py` — a negative example that no test asserts is a comment,
and a table row that no file backs is a rule nobody is enforcing.

---

## `examples/invalid/account-scope.account-scoped-without-account-from.yml`

Rejected by [`schemas/account-scope.schema.json`](../../schemas/account-scope.schema.json).
The omission this file exists to make impossible: a service that agrees with itself
and stops one field short.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `entryPoints[0].accountFrom` (absent) | `required` | `accountScoped: true` with nothing saying **where** the caller's account comes from. The consequence is not that the file is incomplete — it is that nothing can check the scoping later. A route whose `requireAccount` call is deleted keeps this declaration green, and it is then a cross-tenant read with a file saying it is not one. |

## `examples/invalid/account-scope.unscoped-without-reason.yml`

Rejected by [`schemas/account-scope.schema.json`](../../schemas/account-scope.schema.json).
The unstated case, which is the dangerous one.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `entryPoints[0].reason` (absent) | `required` | A route listed and not classified. A reader cannot tell a route that was reviewed and found harmless from one nobody looked at, and the difference between those two is exactly the difference between an isolated service and an unknown one. This is D18's grep in a form a checker can see: an entry point with no answer reads like an answer. |

## `examples/invalid/account-scope.undeclared-key.yml`

Rejected by [`schemas/account-scope.schema.json`](../../schemas/account-scope.schema.json).
What somebody writes after reading the prose and not the schema.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `entryPoints[0].scopedByAccount` | `additionalProperties` | An undeclared key is a **silent no-op** everywhere except here. A checker that ignored it is how `entryPoints` ends up meaning something nobody wrote down — the same shape as `gate.undeclared-key.yml`, for the same reason: `additionalProperties: false` is the reason an undeclared key is an error rather than a field nobody validates. |

## `examples/invalid/account-scope.honest-zero-with-a-surface.yml`

Rejected by [`schemas/account-scope.schema.json`](../../schemas/account-scope.schema.json).
The dishonest zero, which is worse than the omission.

| # | Field | Keyword | Why it is rejected |
| --- | --- | --- | --- |
| 1 | `surface.sources` | `maxItems` | `kind: none` says "this service has no entry point of its own"; naming a file to read inside it says the opposite. A shared library has to be able to say so in a field rather than in a comment, and a format without `none` forces one of two failures, both recorded in this fleet — a service holding no customer rows omits itself, which is indistinguishable from having forgotten. |
| 2 | `surface.minimum` | `const` | `minimum: 4` beside `kind: none` reads as "I have no entry points and I expect you to find four", which is a contradiction rather than a typo. Pinning it to `0` is what makes the two fields mean the same thing. |

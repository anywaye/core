# OpenAPI conventions

The HTTP contract rules every cafaye service follows. Concise on purpose: a
service that invents its own error shape or pagination style is a service that
needs a bespoke SDK. `schemas/cafaye.manifest.schema.json` points at a repo's
OpenAPI 3.1 document via `exposes.api`; this document is what that document must
already agree with.

## Versioning

Two version numbers, both required, and they move together.

- **`/v1` in the path.** Every path is prefixed: `/v1/users`,
  `/v1/accounts/{account_id}/members`.
- **`info.version` in the document.** Every OpenAPI document states
  `info.version: 1.0.0`. It is the document's own semantic version, and it
  follows the service's own release line, not the API prefix.

The two are different questions and both answers are needed. The path prefix is
what a client compiles against: it says *which* contract, and it is the only
version that can ever be frozen, because a published endpoint cannot change
shape. `info.version` says *which build of the document* this is, so a
consumer generating a client or diffing two documents can tell "nothing moved"
from "the whole document was regenerated", and so a deprecated endpoint can be
attributed to a release.

- The prefix is the *API* version. It changes only for a breaking change, and a
  breaking change means a **new prefix alongside the old one** — `/v1` is never
  mutated in place.
- Non-breaking additions (new endpoint, new optional request field, new response
  field) ship inside the current prefix without a version bump.
- No version in the body, no `Accept`-header versioning, no `?version=`.
- `defaultBranch` is `master`; specs are versioned by their path prefix, not by
  git tags.
- **Sync rule:** a breaking API change bumps the prefix *and* the document
  version in the same commit. A non-breaking change bumps only `info.version`.
  Bumping `info.version` while `/v1` changes shape is the mistake this rule
  exists to prevent — a reader of the document has no other signal.
- A future `cafe contract lint` will enforce both: every path under a single
  `/vN` prefix, an `info.version` present and parseable, and a major bump in
  `info.version` on the commit that adds a new prefix. Until that lands the rule
  is review-enforced, like every other convention here.

## Error envelope

Every non-2xx response is `application/problem+json` (RFC 9457) with the cafaye
extensions below. No service invents its own error body.

```json
{
  "type": "https://docs.cafaye.com/errors/validation_failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "email is not a deliverable address",
  "instance": "/v1/users",
  "code": "validation_failed",
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "errors": [{ "field": "email", "code": "invalid_format" }]
}
```

- `type` is a stable `https://docs.cafaye.com/errors/<code>` URI — the machine-readable
  contract. `title` is a fixed, human-readable summary for that code; it may be
  reworded without a version bump. `detail` is specific to this occurrence and
  is not parsed by clients.
  The base is **contract infrastructure and it is never redesigned**: PLAN
  §1 stability rule 2 freezes `docs.cafaye.com/errors/<code>` for the life of
  the platform, so a docs-site reorganisation, a path rewrite or a migration to
  a versioned section may not move it. A client stores this URI and dereferences
  it years later; the only permitted change is the addition of a new `<code>`.
  The retired `errors.cafaye.com` host served nothing and is not redirected —
  the URI is an identifier, and a client that hard-codes the old one was always
  reading a value nobody published.
- `code` is the same slug as the last segment of `type`, in `snake_case`.
- `trace_id` is always present and always matches the `X-Trace-Id` response
  header. Support starts from this id.
- `errors[]` appears only for 422 and lists per-field failures.

Reserved codes: `unauthorized` (401), `forbidden` (403), `not_found` (404),
`conflict` (409), `validation_failed` (422), `rate_limited` (429),
`idempotency_key_reused` (409), `internal` (500), `unavailable` (503).

Status conventions: 400 only for malformed syntax the client could not have
known; anything semantically wrong is 422. Never 404 for authorization
failures on a resource the caller cannot see — 404 is correct there, 403 is not
allowed to leak existence.

## Pagination

Cursor-based everywhere, including for admin and export endpoints. Offset
pagination does not scale past a few thousand rows and cannot be stable while
rows are being inserted.

Request: `?limit=50&cursor=<opaque>&order=asc|desc`. `limit` defaults to 25 and
is capped at 100. `cursor` is an **opaque** base64url string; clients must not
parse it, and its encoding may change without notice.

```json
{
  "data": [ { "id": "usr_01JJ9Z8" } ],
  "page": { "next_cursor": "eyJpZCI6InVzcl8wMUpKOVo4In0", "has_more": true }
}
```

- `data` is always an array, empty rather than absent.
- `page.next_cursor` is `null` on the last page.
- Cursors expire after **24 hours**; an expired cursor returns 400
  `cursor_expired` rather than silently restarting at page one.

## Idempotency

Mutating `POST` endpoints that can be retried safely **must** accept
`Idempotency-Key`:

- Header: `Idempotency-Key: <uuid>`, chosen by the client.
- Scope: the `(endpoint, principal, key)` triple. The same key on a different
  endpoint or principal is a different key.
- Retention: 24 hours, stored with the response.
- Replay with the same key **and** the same request body returns the original
  response and `Idempotency-Replayed: true`.
- Replay with the same key but a different body returns 409
  `idempotency_key_reused`.
- Requests without the key are processed normally. Retrying without a key is
  the client's bug, and money-moving endpoints are the client's problem.

Every webhook handler and every event consumer in cafaye is idempotent for the
same reason (delivery is at-least-once, and at-least-once is a property of the
outbox that publishes it — see [event-outbox.md](event-outbox.md)).

## Auth

- Bearer JWTs only: `Authorization: Bearer <jwt>`. No cookies for API traffic;
  browser sessions use `Secure`/`HttpOnly`/`SameSite=Lax` cookies and a CSRF
  token, and those are a *different* surface, not an API exception.
- **identity is the only issuer.** Services verify locally against the JWKS URL
  (default `https://identity.cafaye.com/.well-known/jwks.json`), cache keys by
  `kid` with a bounded TTL, and refresh on unknown `kid` — no per-request call
  to identity on the hot path. `gateway` does this for the public edge.
- Accepted algorithms: RS256 and ES256. `alg: none`, symmetric HS256, and any
  algorithm not advertised by the JWKS are rejected outright.
- Required claims: `iss`, `aud`, `sub`, `exp`, `iat`, `jti`, plus `account_id`
  and `scopes` for authenticated service traffic.
- Access tokens live ≤ 15 minutes. Refresh tokens are rotating, stored
  server-side, and reuse of a rotated token revokes the whole family.
- Authorization: `scopes` for capability (`invoices:write`), `account_id` for
  tenancy. Every query is scoped by `account_id` from the token, never from the
  request body. Services do not parse roles out of a `roles` claim — they check
  scopes, or ask identity.
- Service-to-service calls carry a token issued to the calling service with
  scopes narrowed to what it needs (`least privilege`, see PLAN.md §1's review
  requirements for `identity` and `billing`).
- Inbound webhooks are **not** JWT-authenticated: they are signed, per the
  sender's convention (`X-Cafaye-Signature`, HMAC-SHA256 over
  `timestamp.body`, with a replay window), and the receiver checks the signature
  before parsing.

## Deprecation

1. Announce: CHANGELOG entry, `docs/` note, and email to every consumer that
   called the endpoint in the last 90 days.
2. Response headers on every call to the deprecated surface:
   `Deprecation: Sat, 01 Nov 2026 00:00:00 GMT` and
   `Sunset: Tue, 01 May 2027 00:00:00 GMT` (RFC 8594).
3. Minimum notice: **6 months** between `Deprecation` and `Sunset`.
4. Sunset is real: the old surface returns 410 `gone` with a `Link` to its
   replacement.
5. Events follow the same window — see
   [event-naming.md](event-naming.md#evolution).

## Checklist for a new endpoint

- [ ] Path under `/v1`, no trailing slash, plural nouns, kebab-case for multi-word.
- [ ] Documented in the service's OpenAPI 3.1 file, which is what `exposes.api` points at.
- [ ] `info.version` present and bumped if anything else in the document moved.
- [ ] Auth: required scopes + `account_id` scoping stated in the security scheme.
- [ ] Errors: `problem+json` with a `code` from the reserved list.
- [ ] Pagination: cursor in, `data` + `page` out.
- [ ] Idempotency: `Idempotency-Key` accepted on every safe-to-retry `POST`.
- [ ] `X-Trace-Id` echoed in both header and body.

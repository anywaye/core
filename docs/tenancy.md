# docs/tenancy.md — how a cafaye service declares its account boundary

The format is `tenancy.yml` at the service's repository root, written against
[`schemas/tenant-isolation.schema.json`](../schemas/tenant-isolation.schema.json),
checked by [`harness/tenancy_check.py`](../harness/tenancy_check.py), and proved
able to fail by [`harness/tests/tenancy_self_test.sh`](../harness/tests/tenancy_self_test.sh).
This document is the reasoning, including the things it will not do for you.

A declaration has **two** halves and they are separate claims about separate
things. `entryPoints` says where the service's **code** draws the boundary and
which test proves it. `rls` says what **Postgres** does — and the rule that
block exists for is one Postgres does not document where anybody looks for it and
**no lint in the world checks**: a table's owner bypasses row-level security
unless the table is set `FORCE ROW LEVEL SECURITY`, and a service owns the tables
it created. Start at [The three-way denial shape](#the-three-way-denial-shape)
for the test side and [What the database does about it](#what-the-database-does-about-it--rls)
for the FORCE bit.

## Why this file exists

The platform is sold as self-hostable multi-tenant code. The defect that ends
that product is one customer reading another's data, and nothing in the fleet
made it visible:

```
cross-tenant NEGATIVE tests — ones asserting account A is refused account B
  identity 7    courier 19
  billing 0   cafaye-rb 0   cafaye-ts 0   gateway 0
  darkroom 0  pantry 0     muse 0        cafaye-py 0
```

Two services prove isolation. Eight do not, and six of those scope by account
in production code.

**The implementations are largely correct.** `darkroom` is the clean example:
`assets` and `asset_variants` carry `account_id uuid not null`, there is a
`unique (account_id, checksum)`, and every query constrains on it —

```sql
where id = $1 and account_id = $2
update assets where id = $1 and account_id = $2 and status = 'pending'
delete from assets where id = $1 and account_id = $2
```

— with **zero** tests asserting any of it. A refactor that drops one
`and account_id = $2` gives a customer another customer's files and the whole
suite stays green. Correct by construction, unprotected by test.

## Why not a grep, or a rule, or an inference

The part that matters more than the missing tests is that **nobody can ask the
question mechanically**. Counting account-scoped routes by pattern gives a
different answer per framework:

```
  gateway     route_defs=96     (TypeScript decorators)
  muse        route_defs=76
  cafaye-ts   route_defs=51
  darkroom    route_defs=0      (axum — a different syntax entirely)
  billing     route_defs=0      (Rails — a different syntax entirely)
```

A grep that reports "darkroom has no routes" when darkroom has account-scoped
queries against customer assets is **worse than no grep**, because it reads
like an answer. Someone runs it, believes it, and stops looking.

So the fix is not "grep harder". It is the same move that made
[the gate](gate.md) work: `core` publishes a format, `kit` distributes it, and
services adopt one shape. Cross-tenant access is **declared, never inferred**
(**D33**).

There is also a rule-shaped version of the question that does not work, and
worth naming so nobody writes it later: "every query touching a
`tenant`-prefixed table must have a `tenant_id` predicate". It cannot see the
join that drops the scope, the repository method three layers down, the CTE that
loses it between two `select`s, or the middleware that resolves the account in
the first place — and a rule that is right about 90% of the sites reads as a
boundary that is enforced.

## What already worked, and what this copies

Two services already write the right test, and this format is their shape:

- `courier/test/courier/webhook_endpoints_test.exs` and
  `courier/test/courier/workers/dispatch_webhooks_worker_test.exs`
- `identity/internal/apikeys/service_test.go` (`TestRevokeCannotCrossTenants`)
- `identity/internal/httpapi/admin_integration_test.go`
  (`TestAnAdminCannotReadAnotherAccountsTrail`)
- `identity/internal/httpapi/oidc_test.go` (the `otherAccount` fixture)

What they share, and what the format preserves:

1. **A second account fixture** — `f.otherAccount(t)`, `@other_account_id`,
   `f.elsewhere`.
2. **A negative assertion per entry point** — and the assertions are about
   **absence, not refusal**:

```elixir
assert WebhookEndpoints.get(endpoint.id, @other_account_id) == nil
assert WebhookEndpoints.list(@other_account_id) == []
assert WebhookEndpoints.enabled(@other_account_id) == []
```

That second half is the load-bearing decision and it is **D33**: cross-tenant
access must be *indistinguishable from nonexistence*. A `403` tells an attacker
the id exists; a `nil`/`[]`/`NotFound` tells them nothing. If your contract
permits a service to answer "forbidden" for another account's resource, it has
reintroduced an enumeration oracle, and a test must be able to catch that —
which is why `negative.asserts` is a `const: absent` rather than an enum with a
discouraged second value.

## The three-way denial shape

**The question is not "does an unauthenticated request fail".** That question is
satisfied by a table with no policy at all, by a table with no predicate at all,
and by a service whose database is switched off — and all three of those are the
**bug**, not the fix. A service that answers "nothing" to everybody passes that
test perfectly and forever, and so does a service that answers "everything" to
everybody if its table has no policy and no `FORCE` bit.

So the boundary has to answer three questions, and `negative.cases` is exactly
three entries, one per question:

| `id` | who is acting | what must come back |
| --- | --- | --- |
| `no-identity` | nothing at all — no session, no credential | **zero rows** |
| `other-account` | a **valid** credential belonging to a *different* account | **zero rows** |
| `own-account` | this account's own valid credential | **its own rows** |

**`other-account` is the arm with all the information in it**, and it is the one
a naive suite leaves out. `no-identity` is nearly free: refusing an
unauthenticated request is what an absent predicate or an absent policy does by
accident. `other-account` is the only arm that requires the credential to be
*real* and the scope to be *checked*.

**`own-account` is the control, and `cases` is `minItems: 3`/`maxItems: 3`
because of it.** Without the third arm the first two are satisfied by a service
that returns nothing to anybody — a broken service. So `own-account` is
`const: present`, and `negative.cases[].expects` on that arm is **a column or
field the assertion reads off the row that came back** (`checksum`, `status`,
`object_key`), not merely "the call did not raise". `lives_ok` passes when the
write matched zero rows, which is exactly the failure the third arm exists to
catch. And it is refused to be an absent spelling: pointing the arm at a line
that asserts `nil` is `tenancy.positive-control-refused`, a **FAILURE**, because
it is a declaration that says "this account sees its own rows" about a test that
says the opposite.

### Match the assertion to how the request is denied

The three arms are not three of the same assertion. Postgres denies a row two
different ways and they want different assertions, and getting this wrong is how
a policy that admits every tenant gets a green test:

| Denied by | Postgres | Assert with |
| --- | --- | --- |
| a missing grant | raises `42501` | an exception assertion (`throws_ok`, `assert_raises`) |
| a `with check` violation | raises `42501` | an exception assertion |
| a `using` clause filtering the row out | **raises nothing, matches zero rows** | an empty-result assertion (`is_empty`, `assert … .empty?`) |

So `rls.policies[].clause` records which mechanism each policy uses, and the
schema **derives it from `command`** rather than letting a service choose:
`for select` and `for delete` are denied by `USING`; `for insert` is denied by
`with check`; `update` and `all` may carry either. Asserting an exception on a
read that a `using` clause filtered out is asserting a *privilege* failure — and
if the table has no policy at all, that is exactly the error you get, so the test
passes for the wrong reason.

And **a denied write is never proved by the write alone.** Pair every denied
write with a read proving the target row is intact, scoped to that row: a suite
that asserts on everything a role can see breaks the moment the table holds more
than one customer's data. `negative.cases[].expects` for a write is therefore
the assertion's own name — `rows_affected_zero`, `assert_unchanged` — rather
than an empty result, which would be a lie about a row that exists.

#### What the fleet actually proves, measured

The table above is what a service **should** write. This is what the fleet
**does** write, read out of four places on 2026-10-03 — `kit/tests/tenancy_test.sh`
(39 assertions), `identity/internal/tenancy/isolation.sql`, this file's schema and
`harness/tenancy_check.py` — and reproduced by pointing `harness/tenancy_check.py`
at four mutated copies of `harness/tests/fixtures/tenancy/conforming/`. Each
mutation is one real service writing one of the shapes the table says it must not.

| # | what a service writes | denied by | the assertion should be | what the checker said | |
| --- | --- | --- | --- | --- | --- |
| 1 | `select` denial arm as `assert_raises` | `using` — **raises nothing** | an absent result | **0 failures, exit 0** | the shape that passes while isolation is broken |
| 2 | `update` denial arm as a bare `assert_equal 0` | `using` — **raises nothing** | zero rows **and** the row intact | 0 failures, exit 0 | the pairing clause, unenforced |
| 3 | `own-account` on a write as `lives_ok` | — | the row's own value | 0 failures, exit 0 | `lives_ok` passes when the write matched zero rows |
| 4 | `own-account` as `nil` | — | the row's own value | `tenancy.positive-control-refused` | **already refused** |

Row 4 is the only one closed, and it is closed on the **positive** arm only. So
the shape core enforces today is *"don't claim absence where you claim presence"*,
and the shape it does not enforce is *"match the assertion to the clause that
denies you"* — which is the third row of the table above, the one that raises
nothing, and it is the common one.

Nothing here needs Postgres to see. All three facts are decidable from the
declaration plus the line it names, which is why they are findings in
`harness/tenancy_check.py` and not a note here: `tenancy.denial-shape` for rows
1 and 3, `tenancy.denial-unpaired` for row 2. A suite that asserts only "it threw"
is a green suite, and this is the table that says so in the place a service author
is already reading when they reach for `negative.cases`.

## What the database does about it — `rls`

`tenancy.yml` has a second half, and it is required. `accountScoped` says what
the service's code does; `rls` says what **Postgres** does, and the two claims
are independent: every line of the `rls` block could be deleted and the
`entryPoints` predicates would still hold.

```yaml
rls:
  databaseEnforced: true          # false + tables: [] is the honest "the DB does nothing"
  identity: app.current_account()  # the stable, zero-argument call every policy reads
  sources:
    - migrations                   # a SEPARATE list from scope.sources — see below
  tables:
    - table: assets
      forced: true                 # const. this is the load-bearing field in the file.
      policies:
        - name: assets_select_own
          command: select
          clause: using
          roles: [tenant_app]      # `public` is refused
          constrained:
            file: migrations/0002_rls.sql
            line: 67
```

**`forced` is a `const: true`, and it is the single highest-value thing in this
document.** Postgres does not apply row-level security to a table's **OWNER**
unless the table is set `FORCE ROW LEVEL SECURITY`. A service creates its tables
in its own schema and therefore **owns them**. So a migration that writes

```sql
create policy assets_select_own on assets for select to tenant_app using (…);
alter table assets enable row level security;
-- and stops
```

has shipped a policy that is **never evaluated by the role that matters**. Every
query still succeeds. Every policy still exists in `pg_catalog`. Nothing raises,
because a policy that is never evaluated is not a policy that fails — and the
runtime role reads every row in the table.

Two things make this the rule to have. **Postgres documents it in the CREATE
TABLE reference and not in the row-level-security guide**, and **no lint checks
it**: Supabase's database advisor — the reference for this whole problem —
collects `relforcerowsecurity` for its dashboard's table list and never judges
it (measured: `packages/pg-meta/src/sql/studio/advisor/lints.ts`, which holds
twenty-eight lints and none of them is this one). Cafaye uses `FORCE` zero times
today across nine account-scoped services, which is why this is free to prevent
rather than expensive to retrofit.

`force` is a **separate `reloptions` bit** from `enable` and neither implies the
other, which is why the schema constrains one thing and the checker checks the
other: the schema cannot see the migrations, and the checker cannot see the
schema. `tenancy.rls-owner-bypass` is where they meet, and
`harness/tests/tenancy_self_test.sh` proves it by deleting the one `force` line
from the fixture and asserting that finding appears **about that table and
nothing else**.

### Why `rls.sources` is a second list

`scope.sources` is where the account-scoped **statements** are; `rls.sources` is
where the **DDL** is. In a Go service those are `internal/` and `migrations/`,
and one list naming both is a list that ends up naming the whole repository —
which is the dependency-tree answer `harness/tenancy_findings.json`'s
`notEnforced` entry names as this checker's sharpest limit. Two lists, each
naming exactly what its own check reads, and one `tenancy.scan-narrowed`
warning for "a declared path is not there".

### `databaseEnforced: false` is a claim, not a gap

Six of this fleet's account-scoped services scope every statement in their
repository and enable row-level security on nothing. That is a legitimate design
— `darkroom`'s is the clean example — and
[`examples/valid/tenancy.rls-declared-none.yml`](../examples/valid/tenancy.rls-declared-none.yml)
is what saying so looks like.

It cannot simply be **left out**, for the same reason `accountScoped` cannot: an
omitted block and a block saying `false` are the same file to a reader who has
not been told which one they are looking at. And it is not inert — a policy, a
`force` bit or an `enable` line anywhere in `rls.sources` is
`tenancy.rls-undeclared`, a **FAILURE**. So `false` is a claim, the claim is
checked, and the day somebody writes the first migration they have to say so.

`identity` must be a **zero-argument call**. That is not tidiness: the rule below
is about the call being hoisted out of the row loop, and a call with arguments
cannot be hoisted. `current_setting('app.account_id')` is deliberately not
declarable here — it is the shape this field exists to steer away from, and
[**D41**](DECISIONS.md#d41-how-is-the-force-rule-declared-and-what-may-a-warning-mean-in-the-tenancy-checker)
records that as the first thing to revisit.

### The per-row rule: `(select …)`, not the bare call

Write the identity wrapped:

```sql
-- RIGHT. One evaluation per statement; the planner treats it as an InitPlan.
using (account_id = (select app.current_account()));

-- WRONG. Re-evaluated for every row the statement touches.
using (account_id = app.current_account());
```

**The reason, and why it is a failure.** Supabase's note on this lint is "this
produces suboptimal query performance at scale", which is true and is not the
reason core made it a **failure** rather than a warning. The reason is what a
warning means *in this checker*: the three warnings `tenancy_check.py` already
had all say *this machine cannot answer that question*, and a warning that does
not move the exit code exists because failing on it would get the checker
disabled. That argument does not transfer to a fact that is fully decidable from
the migration text. A severity nobody chose is not a severity, so the finding is
`tenancy.rls-per-row` and it is a failure.

The wrapped form is also what makes the plan reusable: Postgres evaluates the
`stable` function once and the planner can cache the result, so the policy's
predicate stops being a per-row call into `current_setting`. And it composes with
the `identity` requirement — a zero-argument call can be hoisted, a call with
arguments cannot, which is why the declaration's pattern ends in `()`.

### The public-read tier: a claim with evidence

Most tables in `rls.tables` are account-scoped by construction, and for them an
always-true `SELECT` clause is the absence of a boundary. But some tables are
**deliberately public-readable** — pantry's `publishers` is the shape: published
publishers and their services are readable by anyone, and that is the product
rather than a leak. The format has to be able to say that honestly, because the
alternative is a service that either lies about the table or weakens the check
for everyone else.

`rls.publicRead` is how. It is a list of claims, and each claim names three
things:

```yaml
rls:
  publicRead:
    - table: publishers               # the table that is public-readable
      policy: publishers_public_read  # the policy that grants the read
      role: public_reader             # the role the read is granted to
```

**The tier is a claim with evidence, not a blanket exemption.** The checker
compares each entry against the DDL: the named policy has to exist on the named
table, has to be written `for select`, and has to be bound `to` the named role.
A claim the migrations do not write — wrong policy, wrong command, wrong role,
or a table the migrations never create — is `tenancy.rls-public-read-absent`, a
FAILURE. A service that believes it has a public read it does not is a service
whose boundary is a sentence, and the declaration cannot be asserted into
existence.

**And the tier narrows the check; it does not soften it.** A public `SELECT`
policy on a table the declaration does **not** mark public-readable is still
`tenancy.rls-permissive`, exactly as before — the always-true arm, the
names-no-role arm and the identity-absent arm all still fire. The exemption is
the narrowest one in this checker: the one named policy on the one declared
table, and only while the DDL backs the claim. The severity for an undeclared
public policy stays where it is, and the ledger below records why.

**The tier is SELECT-only.** An always-true or role-less `INSERT`, `UPDATE`,
`DELETE` or `ALL` clause is still `tenancy.rls-permissive` under a public-read
declaration — a public read is not a public write. The claim check says the
command out loud when the named policy is written for another one.

**`role` refuses `public`**, for the reason `rls.tables[].policies[].roles` does:
a policy with no `to` clause applies to `PUBLIC`, which is every role including
the migration role and every role this service adds in a year when somebody
needs a read-only role for a support query. A public read granted to every role
is the absence of a boundary wearing a public-read declaration's clothes, and
the schema refuses it rather than letting the tier become evidence-free.

The named policy must **also** be declared in `rls.tables[].policies`, because
a policy in the migrations and not in `rls.tables` is `tenancy.rls-undeclared`.
`publicRead` is the evidence that the policy is a deliberate public read, not a
replacement for declaring it.

**What the claim check does not ask** is whether the clause is *really* public.
It asks whether the DDL writes the policy the declaration names, as a `SELECT`,
bound to the role the declaration names — because those are the only facts a
migration file can settle. A declaration can name a policy that is
`for select to public_reader using (account_id = (select app.current_account()))`
— account-scoped, safe, and not a public read — and the claim check passes,
because the policy exists, is a `SELECT`, and binds the named role. The
permissive arms it exempts would not have fired anyway, so the boundary is safe
and the declaration is wrong about what it is. Judging whether a clause is
"really" public is a judgement this stdlib text checker does not have, and a
check that guesses at intent is a check that gets disabled within one release.
`harness/tenancy_findings.json`'s `notEnforced` list says so rather than
leaving it to be discovered.

## The ledger — Supabase's twenty-eight lints, and this one

Supabase's [database advisor][advisor] is the reference for this problem and is
worth reading rather than reinventing: **twenty-eight** lints, of which
**thirteen** are `SECURITY` and several of those are exactly the shapes a
database-per-service fleet gets wrong. The brief that asked for this said thirty;
**measured, it is twenty-eight** — the advisor is one SQL string and `lints.ts`
holds exactly that many `'…' as name,` blocks. The number is recorded here rather
than repeated because a number in a document goes stale and the fix is to
re-measure, which is the lesson PLAN.md §4b draws about counts.

`test_the_row_level_security_rules_are_adopted_and_the_exclusions_are_written_down`
reads the table below and fails if a lint is missing from it, if a row names no
cafaye finding, or if a row says `left out` with no reason. **A rule that was
looked at and left out on purpose is a decision; the same rule left out silently
is the thing this whole document exists to stop.**

<!-- rls-ledger:begin -->

| Supabase lint | Level | Verdict | cafaye finding | Why |
| --- | --- | --- | --- | --- |
| `policy_exists_rls_disabled` | ERROR | adopted | `tenancy.rls-not-enabled` | Policies with RLS never enabled: the policies are never evaluated and nothing raises. Adopted whole — the fact is the same in a service's own migration. |
| `rls_enabled_no_policy` | INFO | adapted | `tenancy.rls-policy-absent` | Supabase rates this INFO because a deny-all table is fail-closed and harmless. In cafaye it is folded into *closure*: a declared table with no policy in the DDL is `rls-policy-absent`, and a policy in the DDL that the declaration does not name is `rls-undeclared`. The severity comes from closure rather than from a judgement about deny-all. |
| `rls_policy_always_true` | WARN | adapted | `tenancy.rls-permissive` | Adopted with **one deliberate change**: Supabase excludes `USING (true)` on a SELECT because deliberate public read is a real thing on their platform. Cafaye has the public-read tier now (`rls.publicRead`), and the exclusion carries over **as a claim with evidence rather than a blanket exemption**: the always-true arm stands down for the one policy the declaration names as a table's public read — table, policy and role all checked against the DDL — and fires for every other always-true clause, because a public read nobody declared is the defect this checker exists for and not a lesser form of one. This is the one place a severity goes **up**, and it is recorded here rather than buried. |
| `auth_rls_initplan` | WARN | adapted | `tenancy.rls-per-row` | Their `auth.uid()` becomes our declared `identity`, and their `WARN`/`PERFORMANCE` becomes a FAILURE: see *The per-row rule* above for why a warning in this checker means "this machine cannot answer" and this one can. |
| `function_search_path_mutable` | WARN | adapted | `tenancy.rls-definer-search-path` | Adopted whole and raised from WARN. In cafaye the runtime role can create objects in its own schema, so an unpinned `search_path` on a `security definer` function is a tenant-crossing primitive rather than a hardening nit. |
| `security_definer_view` | ERROR | adapted | `tenancy.rls-view-invoker` | Their question is "can `anon` reach this view", which is a **privilege** question about `has_table_privilege` and this checker has no database. Ours is "does the reader's policy run", which is a fact about the DDL: a view without `security_invoker` is security definer by default on every PostgreSQL version. |
| `foreign_table_in_api` | WARN | adapted | `tenancy.rls-unprotectable` | Their WARN is about PostgREST reachability. Ours is the underlying fact, which is stronger and needs no API: a foreign table has no policies to enforce, so a policy on one is a comment. |
| `materialized_view_in_api` | WARN | adapted | `tenancy.rls-unprotectable` | The same finding and the same reason: a materialized view cannot carry row-level security at all, and a snapshot of every tenant's rows is not a boundary. Merged with the foreign-table rule because it is one fact about Postgres. |
| `multiple_permissive_policies` | WARN | left out | — | A **performance** lint: several permissive policies for one (role, command) each run. The security consequence — that permissive policies are OR-ed, so an undeclared one can widen a declared one — is real, and it is already covered: an undeclared policy on a declared table is `tenancy.rls-undeclared`. Counting policies would be a fact this checker can determine and is not a defect, and core's finding vocabulary is for defects. |
| `rls_references_user_metadata` | ERROR | left out | — | Specific to Supabase's `auth.users.user_metadata`, which cafaye has no equivalent of: identity is cafaye's own service and the account arrives as a verified JWT claim. The *shape* of the defect — a policy whose identity input the caller can change — is not checkable from a migration, because whether `app.current_account()` is set from a verified claim or from a header is a fact about a service's middleware and not about its DDL. |
| `anon_security_definer_function_executable` | WARN | left out | — | Asks whether the `anon` role can `EXECUTE` a function. cafaye has no `anon`; the runtime role is named per service, and a `security definer` function the runtime role can call is not itself the defect. What closes the hole — the `search_path` pin — is `tenancy.rls-definer-search-path`. |
| `authenticated_security_definer_function_executable` | WARN | left out | — | The same rule against the other role. Same reasoning, and the second copy of it would double the findings without adding a fact. |
| `auth_users_exposed` | ERROR | left out | — | Entirely about views over Supabase's `auth.users` reaching PostgREST. There is no `auth.users` here and no PostgREST; identity's tables are reached by its own API, not by a generic data plane. |
| `rls_disabled_in_public` | ERROR | left out | — | The predicate is "a role the API can reach has RLS disabled", which is `has_table_privilege` against a schema list this checker does not have. Its *intent* — a table carrying the tenancy key and no RLS — is what `tenancy.rls-undeclared` names in the direction cafaye can close, which is the one where a service claims a boundary it did not declare. |
| `fkey_to_auth_unique` | ERROR | left out | — | Foreign keys into Supabase's `auth` schema. Cafaye's identity-side tables are reached by id across services rather than by a cross-database foreign key, so the shape has no instance here. |
| `sensitive_columns_exposed` | ERROR | left out | — | A column-name denylist (`password`, `api_key`, …) combined with "the table is API-exposed". Both halves are wrong for cafaye: the exposure question needs `has_table_privilege`, and core has no column denylist anywhere — `docs/observability.md`'s vocabulary is a closed **allow**list for exactly this reason, and a denylist of secret-ish words catches nothing that a well-named column is not already safe from. |
| `insecure_queue_exposed_in_api` | ERROR | left out | — | `pgmq` queue tables in the `pgmq` schema. cafaye uses no Postgres queue extension; the outbox convention is a plain table drained by the service's own code (`docs/event-outbox.md`). |
| `unindexed_foreign_keys` | INFO | left out | — | Performance, not boundary. It belongs with the query-path lints kit already ships, not with a check whose reason for existing is one customer reading another's data. |
| `no_primary_key` | INFO | left out | — | Performance. The same answer. |
| `unused_index` | INFO | left out | — | Performance, and the one lint here whose answer legitimately requires running the database's statistics rather than reading a migration. |
| `duplicate_index` | WARN | left out | — | Performance. The same answer. |
| `extension_in_public` | WARN | left out | — | A schema-hygiene rule about where extensions install. Nothing to do with an account boundary. |
| `extension_versions_outdated` | WARN | left out | — | A supply-chain check against `pg_available_extensions`, which needs a database connection and says nothing about tenancy. |
| `unsupported_reg_types` | WARN | left out | — | An upgrade-tooling rule about `reg*` column types blocking `pg_upgrade`. Nothing to do with an account boundary. |
| `table_bloat` | INFO | left out | — | Maintenance. Needs `pg_stats`, needs a database, and says nothing about tenancy. |
| `public_bucket_allows_listing` | WARN | left out | — | Supabase Storage buckets. darkroom's objects are in S3/R2 behind presigned URLs, and there is no bucket with a `SELECT` policy on it. |
| `pg_graphql_anon_table_exposed` | WARN | left out | — | Requires the `pg_graphql` extension, which cafaye does not use and should not. |
| `pg_graphql_authenticated_table_exposed` | WARN | left out | — | The second copy of the same rule against the other role. Same answer, and the reason is the extension rather than the role. |

<!-- rls-ledger:end -->

**And the one with no Supabase ancestor at all**, which is why it has no row in
the table above: **`tenancy.rls-owner-bypass`**. It is the FORCE rule, there is
no lint behind it anywhere, and "adopted from Supabase" would be claiming a
credit that does not exist. It is the reason this half of the format is here.

[advisor]: https://supabase.com/docs/guides/database/database-linter## The format

```yaml
version: 1
service: darkroom

# Required, and a boolean. "I have no boundary" is a claim, and a format that
# cannot express it forces every service to either invent one or omit itself.
accountScoped: true

scope:
  key: account_id        # the tenancy key THIS service scopes by
  sources:               # exactly what the checker may read
    - migrations
    - src

rls:
  databaseEnforced: false   # true when Postgres holds the boundary; see `rls` above
  sources:                  # the DDL, which is NOT the same tree as scope.sources
    - migrations
  tables: []                # empty exactly when databaseEnforced is false
  publicRead: []            # optional — the declared public-read tier; see its section above

entryPoints:
  - id: asset-fetch
    operation: select        # select | update | delete | call
    subject: assets
    enforced:
      mechanism: query-filter # query-filter | bind-parameter | repository-method | middleware
      file: migrations/0001_assets.sql
      line: 22
    negative:
      asserts: absent        # const. the only legal value at this level.
      cases:                 # EXACTLY three — see the three-way section above
        - id: no-identity    # nothing is acting            -> zero rows
          asserts: absent
          expects: nil       # this language's spelling of nothing
          file: tests/tenancy_test.rb
          line: 39
        - id: other-account  # a VALID credential, other one -> zero rows
          asserts: absent
          expects: nil
          file: tests/tenancy_test.rb
          line: 44
        - id: own-account    # this account's own credential -> ITS ROWS
          asserts: present   # const. the third arm is a control, not a denial
          expects: checksum  # a column read off the row that came back
          file: tests/tenancy_test.rb
          line: 49
```

Three things per entry point, and all three are required:

- **where the scoping happens** — `mechanism` from a closed vocabulary, plus the
  file and the line. `mechanism: bind-parameter` additionally names the
  parameter, because a query that still says `account_id = $2` while nothing
  passes `$2` any more is scoped on paper and unscoped in fact.
- **the three denial cases**, each on the line it names, and the third of them
  asserting that the account's own rows come back.
- **an id**, because a finding, a test and a human all need to name the same
  thing.

### Why the line is a line

`enforced.line` is **exact**, and the drift it causes is the intended trade. A
refactor that moves a query three lines down is `tenancy.scope-lost` until the
declaration moves with it, and the message says which of two things happened:
the scoping moved, or the scoping was dropped. Those want different fixes and a
checker that cannot tell them apart reports the second as a pass.

**Closure does not use the line.** An entry point's identity is its file, its
operation and its subject, so:

- a query that moves → the declaration's line is stale (`scope-lost`) and the
  entry point still exists;
- a query that loses its predicate → the site disappears and `entry-absent`
  fires, which is the red that matters;
- adding a new scoped query → `undeclared-entry`, which is the other red.

That split is what keeps a refactor from opening ten failures while still
catching the one that ends a customer's data.

### Why `insert` is not an operation

An insert creates a row in the account the caller is already acting as. It
cannot read or write another account's row, so it is not a place a cross-tenant
leak can happen — and including it would mean a legal declaration whose
`enforced.line` does not carry the tenancy key, because the account is in the
column list rather than in a predicate. An exception inside the contract is how
the next exception gets added.

### Why `call` closes nothing

`operation: call` is for a repository method, a worker or a route whose scoping
is enforced above the statement. Closure cannot be checked against it: the same
line is a `select` to a human deciding where a leak can happen and something
else entirely to a text scanner. Guessing between those is the failure this
whole format exists to stop, so `call` closes nothing and the checker says so —
`tenancy.enumeration-partial` names every `call` it could not classify.

## What the checker reports

`tenancy-check <repo>`, thirty findings in
[`harness/tenancy_findings.json`](../harness/tenancy_findings.json), each with
the exact command that fixes it. Exit codes are the three the gate checker uses:
`0` clean, `1` at least one failure, `2` the check could not happen — and `2` is
never collapsed into `0`, because a check that could not find the declaration
has not checked the boundary.

**Twenty-seven failures**, in three groups. The three that say the declaration
describes nothing that is there:

| id | what it means |
| --- | --- |
| `tenancy.declaration-missing` | there is no `tenancy.yml` |
| `tenancy.declaration-unreadable` | it is not a YAML document core's reader accepts |
| `tenancy.schema` | it does not satisfy the schema |

And the thirteen that say the declaration no longer matches the code — which is
the whole contract:

| id | what it means |
| --- | --- |
| `tenancy.location-missing` | a declaration names a file this service does not have |
| `tenancy.line-missing` | a declaration names a line past the end of the file |
| `tenancy.scope-lost` | the entry point is still scoped, but not on the line it names |
| `tenancy.bind-missing` | the mechanism is `bind-parameter` and the parameter is not on the line |
| `tenancy.entry-absent` | declared, and the scanner can no longer find it — the scoping was dropped |
| `tenancy.undeclared-entry` | the scanner found account-scoped access nobody declared |
| `tenancy.denial-missing` | a denial arm is not on the line the declaration names, and the message says WHICH ARM |
| `tenancy.denial-refuses` | the declaration answers cross-tenant access with a refusal |
| `tenancy.denial-shape` | **the assertion is the wrong shape for the clause that denies it — an exception where `using` raises nothing, or `lives_ok` where only the row's own value proves anything** |
| `tenancy.denial-unpaired` | a denied write is asserted without reading the row it was aimed at, so "matched zero rows" cannot be told from "found nothing to do" |
| `tenancy.positive-control-refused` | the third arm is answered with this language's spelling of nothing, so a service returning nothing to everybody passes all three |
| `tenancy.honest-zero` | the service declares no scoping and its tenancy key appears in the declared sources at a site nobody vouched for |
| `tenancy.enumeration-empty` | the service says it scopes by account and declares no way it does |

And the eleven that say what the **database** does does not match the declaration.
This group is new, it is the whole of the second half, and
`tenancy.rls-owner-bypass` is the one it exists for:

| id | what it means |
| --- | --- |
| `tenancy.rls-owner-bypass` | **the table is not set `FORCE ROW LEVEL SECURITY`, so its OWNER — the role this service connects as — reads every row in it** |
| `tenancy.rls-not-enabled` | policies exist and RLS is not enabled, so none of them is ever evaluated |
| `tenancy.rls-policy-absent` | the declaration names a policy the migrations do not create |
| `tenancy.rls-undeclared` | row-level-security DDL exists for a table (or a policy) the declaration does not cover — the half-adopted boundary |
| `tenancy.rls-permissive` | a clause is always true, or a policy names no role and therefore applies to `PUBLIC`, **or the roles the declaration names and the roles the DDL binds are not the same roles** |
| `tenancy.rls-per-row` | the identity is called bare instead of as `(select …)`, so it runs once per row |
| `tenancy.rls-role-bypass` | a policy applies to a role carrying `BYPASSRLS` or `SUPERUSER` |
| `tenancy.rls-unprotectable` | a policy is on a foreign table or a materialized view, neither of which row-level security can constrain |
| `tenancy.rls-definer-search-path` | a `SECURITY DEFINER` function does not pin its `search_path` |
| `tenancy.rls-view-invoker` | a view over an account-scoped table is not `security_invoker`, so the reader's policies never run |
| `tenancy.rls-public-read-absent` | `rls.publicRead` names a table, the policy that grants it a public read and the role that read is granted to, and the migrations do not write that policy — or write it for another command or another role — so the declaration asserts a public read the database does not have |

**The third arm of `rls-permissive` is the one to read twice.** `roles:` in the
declaration and `to …` in the DDL are two statements about the same thing, and
neither implies the other. `to public, tenant_app` applies the policy to every
role in the database while `roles: [tenant_app]` says the boundary binds one, and
that is the shape that looks narrow in review and is wide in the database. The
other direction leaks the same way round: declaring a role the policy does not
govern promises a boundary that role does not have, so it reads every row. It is
one finding and not two because it is one sentence with the subject swapped —
which is also why `public`, the most common way to reach it, cannot be written in
`roles` at all: the schema refuses it rather than letting a service declare the
thing it is not checking.

The other two arms — the always-true clause and the absent identity — have exactly
one exemption each, and it is the public-read tier above: the one policy the
declaration names as a table's public read, written `for select` and bound to the
role the declaration names. Every other always-true or identity-absent clause still
fires. See **The public-read tier**.

**Four warnings**, and none of them moves the exit code. All of them are the same
claim — *this machine cannot answer that question*:

| id | what it means |
| --- | --- |
| `tenancy.enumeration-partial` | the scanner could not classify every site; the enumeration is **not** proven closed |
| `tenancy.scan-narrowed` | a declared source path is not there, so the scan read less than declared |
| `tenancy.scope-key-unused` | no statement the scanner can read carries the declared key |
| `tenancy.rls-unreadable` | row-level-security DDL was found in a file this checker cannot parse — a Rails migration is a `.rb` file, a Python migration is a `.py` file, and both are **named** rather than passed over |

A warning is a claim about the machine, it is printed and counted separately, and
it leaves the verdict alone. Failing on those is how a checker gets disabled,
which would leave the fleet with **no** boundary check instead of an incomplete
one; ignoring them silently is how a report becomes a lie — and this checker's
entire reason for existing is a grep that reported "darkroom has no routes".

### What the scanner reads, and what it says it cannot

The scanner reads **SQL statements** whose line carries the tenancy key, or a
line within `ATTRIBUTION_WINDOW` (four) above one. It skips `create table`
blocks — which name the column rather than reach a row — and `insert`, for the
reason above. The key itself is **declared by the service**, never guessed: the
fleet already has three vocabularies for it (**D7**), and a checker that picked
one would be guessing at the boundary rather than at the data.

Everything else is reported by name and not counted as covered. Measured over the
thirteen repositories in this fleet with the scanner pointed at each whole tree:

| | services | of which the scanner can classify |
| --- | --- | --- |
| SQL-heavy (identity, darkroom) | 2 | 21 and 10 classifiable sites |
| language-neutral or framework-scoped (courier, billing, cafaye-py, muse, gateway, cafaye-ts, cafaye-rb, parlor) | 8 | 10–124 account-key lines, **0** classifiable |

The second row is the whole point of `enumeration-partial`. Those eight services
get a warning naming every file and line the scanner saw and could not attribute,
an exit code of `0`, and **never** a line reading "no account-scoped entry
points found".

**And the honest zero is expressible in those eight, which was not true before.**
A service whose key appears only where it is not a row scope — a verified token
claim, a docstring, a vendored schema — can name each such site in
`scope.nonRowSites` with the reason it is not a row scope, and the zero becomes
checkable in a language this checker cannot read. The field is the difference
between "I cannot see this" and "I know the key is here and it is not a
boundary", and the difference is load-bearing: the check still **fails** for any
key-carrying site not named, and a site the scanner attributed to a statement
cannot be excused at all — a key this checker read in a `select` is a row scope
by definition. So the declaration vouches for what it can see and the zero is
still caught leaving. muse reads `account_id` as a verified token claim for
metering and no SQL statement in its tree carries it; before this field the
honest zero was **unreachable** for that shape, because the checker counted
every key-carrying line as evidence against it — a format that cannot express a
true answer is the defect, not the service that could not declare it. **D47** records the decision and its alternatives.

### The other scanner: row-level-security DDL

`check_rls` is a second, independent reader, and it reads DDL rather than
statements. It matches `create policy <name> on <table>` and `alter table <name>
enable|force row level security` **as statement starts** — which is the whole
extent of what a line of SQL can say, and it is why removing one line from a
migration moves exactly one finding.

That has a consequence worth stating before an adopter hits it. kit's
`templates/database/tenancy/substrate.sql` writes its DDL through
`execute format(...)` inside plpgsql:

```sql
execute format('alter table %s enable row level security', p_table);
execute format('alter table %s force row level security', p_table);
execute format('create policy %I on %s for select to %I, %I using (%s)', …);
```

No line in a service's tree begins `create policy`. So a service that adopted the
substrate, and whose database has `relforcerowsecurity` true and twenty policies
in `pg_policy`, was reported as carrying **no policy at all**, not enabled and
not forced — and `identity-isolation-01` could not write its `tenancy.yml`
without either lying or failing. **Decided:** the checker resolves the call, so
`select cafaye.protect_table('<table>')` **is** the enable bit, the FORCE bit and
the four `<table>_cafaye_<command>` policies, and a declaration naming those
policies resolves against them.

**There are two calls, and the second is not the first with an argument.**
`cafaye.protect_credential_table('<table>', '<digest_column>')` (kit MD24) is the
one call a credential table makes, and it delegates — it calls `protect_table`
for the same four policies and the same two reloptions bits — and then adds ONE
more: `<table>_cafaye_resolve`, `for select`, qualified by
`<digest_column> = (select cafaye.current_credential_digest())`. That predicate is
the value the **caller presented**, not the account acting on it, and an
authentication request has no account: it has a credential it is trying to
resolve. `identity-isolation-04` adopted it and got seven failures against a
table whose `relforcerowsecurity` is true and whose five policies exist.

Two consequences follow, and both are things a wider regex would have got wrong:

- **The fifth policy is not a fifth entry in the four commands, and it is not
  scoped by the account.** It is named `resolve`, not a command, and it is scoped
  by the digest. Scoping it by `account_id` is not a correction — it is the
  table-wide `SELECT` kit's own comment refuses, because permissive policies are
  OR-ed and the resolve policy exists to hold a credential lookup to one row. So
  the checker carries, per policy, **which identity the template resolved it by**
  and **whether `rls.identity` must also appear**, and asks the question per
  policy rather than per table.
- **The exemption is one arm on one policy, and it is about the PREDICATE.** The
  resolve policy still runs the always-true check, the `(select …)` wrapping
  check, the role checks, and a new one: it must name
  `cafaye.current_credential_digest()`, so a template that stopped writing the
  digest predicate goes red on a policy nobody is exempt from. The other four
  policies on the same table still have to name `rls.identity`, so adopting the
  credential call does not switch the account checks off.

  And the exemption keys off **the predicate rather than the call**, because a
  service that wrote the five policies out by hand has the same boundary and the
  same reason the fifth is not account-scoped. Keying it on "was this generated?"
  would report a false failure against the second — which is the same defect
  above, one level down and wearing a different hat. A resolve policy written by
  hand and scoped by `cafaye.current_credential_digest()` reads green, and the
  self-test asserts that as a green case.

**A warning was considered for "a credential table whose declaration omits the
resolve policy" and rejected.** A warning in this file means *this machine cannot
answer that question*; this machine can — it resolved the call and knows the
table has five policies. So the omission is a FAILURE on the finding that already
means it: `tenancy.rls-undeclared`, "a boundary nobody declared and nobody is
accountable for". A warning there would have been a severity nobody chose over a
fact that is decidable from the migration text, which is the exact thing AGENTS.md
says the `tenancy.rls-*` severities exist to prevent.

Four consequences of the first call, in the order a service meets them:

- **The one entry point stays one.** A service does not write a literal
  `create policy` beside the call, and there is no second, weaker spelling to
  choose from. `protect_table` has no `protect_table_lite` because a template
  that offers the weaker version is a template the weaker version gets chosen
  from; a checker that needed a literal policy line to see the boundary would be
  the same defect wearing a linter's clothes.
- **`rls.identity` is `cafaye.current_account_id()`** for a table the substrate
  protects, because that is the only function the template can scope by. A
  declaration naming anything else gets `tenancy.rls-permissive` with the
  substrate's own reason in the message, rather than a sentence claiming the
  policy is scoped by nothing the checker can see — this file resolved its
  predicate two hundred lines earlier.
- **The roles are the honest gap.** The template writes `to %I, %I` bound to
  `current_user` and `coalesce(p_login_role, current_user || '_app')`, both
  decided by the session that ran the migration, so the principals a generated
  policy binds are named in the template and unnameable in the text. The
  written-versus-declared role comparison is skipped for a generated policy and
  the JSON says so. What still runs is the half a service can get wrong: the
  template never leaves `to` off, so a generated policy can never apply to
  PUBLIC, and `tenancy.rls-role-bypass` reads the roles the **declaration**
  names.

The table name must be a **string literal**, and for the credential call the
**digest column must be one too**. A call built from a variable or a
`format(...)` is not resolved, so nothing is claimed about it and
`tenancy.rls-policy-absent` fires — the safe direction. Guessing which tables a
runtime-built name protects would be reporting an answer the checker does not
have, which is the defect this whole document exists against.

**A `protect_credential_table` with no digest column resolves NOTHING**, and that
is the direction it declines in. The template raises `undefined_column` without
its second argument, so such a call protected no table at all — and a scanner
that read it as `protect_table` would claim four policies for a table with none on
it and hand a declaration naming them a green. Five `tenancy.rls-policy-absent`
findings instead, the same way a runtime-built name gets none.

**Which function a call is comes from its NAME, never from its argument list**,
and that is worth stating because the two spellings have the same shape:
`protect_table('t', 'role')` and `protect_credential_table('t', 'digest')` are
one string, a comma, another string. The second argument means a login ROLE in
the first and a DIGEST COLUMN in the second, so reading it to decide which
function it is gives `t` a resolve policy qualified by a string that is a role
name. A migration that passes its login role explicitly — the spelling kit's own
comment recommends — is the ordinary case, not the exotic one.

`fixtures/tenancy/substrate/` is the first shape: the template copied into a
migration, one call per table, and a declaration that describes exactly what the
template writes. `fixtures/tenancy/credential/` is the second, and it is that
fixture plus **one call and one table** — because a fixture that carried more
would stop proving which difference mattered. `harness/tests/tenancy_self_test.sh`
runs the first as a **control** — zero `tenancy.rls-*` findings, asserted as a
count rather than as an exit code — then breaks it three ways, because a scanner
that learned the template and now passes an unprotected table is worse than the
bug being fixed.

The credential fixture's control asserts a **count of three** rather than an exit
code, and the three are all `tenancy.undeclared-entry` naming `pg_attribute`
inside kit's template: the entry-point scanner's documented gap, below. It has
three because its template copy is kit master and the substrate fixture's
predates MD24's sweep. The control pins the total *and* the subset, so a fourth
red cannot hide inside "still the known gap".

## What this does not prove

The nine entries in `harness/tenancy_findings.json`'s `notEnforced` list are
the honest inventory, and the two worth stating here are these.

There are two, and they are the ones a service author will hit.

**A negative assertion is READ, not run.** `tenancy.denial-missing` proves the
assertion is *written* — a second account fixture, an absent-shaped result, at a
line a reader can open. Running darkroom's suite needs its container and its
Postgres; running courier's needs a mix database. A checker that started
containers to see whether an isolation test passed would be red on a laptop and
green on CI depending on what happened to be running, which is the defect
`gate.requirement-unproven` already exists to name. Running the test is the
gate's job, in the service. This is a real gap and it is the same one MD12
names: a test that is written and never run reads exactly like a test that
passes. **The database half adds to it rather than fixing it:** a `.sql`
migration is read as text, so `tenancy.rls-owner-bypass` proves the migration
says `force`, not that the deployed database has the bit. The two are kept in
step by running the migrations, which is the same obligation.

**`enforced.line` is the only place the scoping happens.** The checker reads one
line and asks whether it carries the key. A statement that scopes in a CTE, a
subquery, a view, or a repository method three layers down is scoped, and this
checker can be pointed at the wrong one line of it — which is why `call` exists,
and why a service with two enforcement points declares two entry points.

The other seven — completeness for a language the scanner cannot read, the
database half's four (`.sql` only, `SECURITY DEFINER` bodies, a table with no
account column, and `protect_table`'s two runtime-bound roles), and the line's
exactness — are in the JSON with their reasoning.

**One thing this checker does not know, and a service that adopted the substrate
will hit it.** The scanner above — the entry-point one — reads a plpgsql body as
ordinary SQL. It cannot tell that `select 1 from pg_attribute where attname =
'account_id'` inside a function is a template's guard rather than a statement
reaching a customer's rows, so a service that copies kit's template into its
migrations gets `tenancy.undeclared-entry` findings naming `pg_attribute` and an
`enumeration-partial` warning, on a database that is correctly isolated.
Measured on `identity-isolation-01`'s own `migrations/00016_account_isolation.sql`:
**3 findings and 11 unattributable sites, every one of them inside the template.**
The fix belongs to that scanner — a dollar-quoted function body is not a
statement source — and it is a different check from the one the substrate needed,
so it is left as the successor's rather than folded in here.
`fixtures/tenancy/substrate/` carries the same warning on purpose, asserted by
token, so the gap stays visible in the one place a reader looks for it.

**And the fixture that adopted kit's CURRENT template has the three findings, so
the gap is stated with a count rather than a description.**
`fixtures/tenancy/credential/` copies kit master's `substrate.sql` and therefore
carries MD24's sweep, which is where the three `pg_attribute` findings come from;
the substrate fixture has none because its copy predates that sweep. Its control
in the self-test pins **3 findings, all of them naming `pg_attribute`, and zero
`tenancy.rls-*`** — three assertions rather than one, because a control that only
checked the subset would pass on a tree that had started failing for a reason
nobody wrote down.

**Two more things this file's checker does not read, both pre-existing, both
measured and both left alone** because a fix changes which finding several
verified cases report, and neither is a regression from the credential work:

- **`ALWAYS_TRUE_CLAUSES` does not match its own ordinary spelling.**
  `normalised_clause` strips the opening paren with `_POLICY_CLAUSE` and then
  only strips a wrapping pair when the body STARTS with one, so `using (true);`
  normalises to `true)` and matches none of the four spellings. The always-true
  arm of `tenancy.rls-permissive` therefore does not fire for `using (true)` —
  and breakage (22) has been green through that hole, because it fires the
  identity arm too and its needle cannot tell the two apart.
- **`rls.tables[].policies[].command` is never compared against the command the
  migration wrote.** Declaring `assets_cafaye_select` as `command: insert` with
  `clause: with check` reports zero `tenancy.rls-*` findings, and so does
  declaring `api_keys_cafaye_resolve` that way — and for the resolve policy that
  is the property kit's own comment rests on, "`for select` and nothing else … so
  a resolution session meets the ordinary account policies on the write side".

Both are written into `harness/tests/tenancy_self_test.sh` next to the cases they
touch, with the measurements, because a reader of that file is exactly the person
who would otherwise assume these fields are checked.

## Adopting it in a service

1. Write `tenancy.yml` at the root. Start from
   [`examples/valid/tenancy.account-scoped.yml`](../examples/valid/tenancy.account-scoped.yml)
   — or the honest zero in
   [`examples/valid/tenancy.honest-zero.yml`](../examples/valid/tenancy.honest-zero.yml)
   if the service holds no customer rows. Do not skip step 2.
2. **Write the negative assertions first**, then point `negative.cases[]` at
   them. Two account fixtures and **three** assertions per entry point: two that
   assert absence and one that asserts the account's own row comes back. The
   third is the one with the information in it. This is the deliverable;
   `enforced` is the claim.
3. **Then the `rls` block**, and it is a question rather than a chore: does the
   database hold this boundary or does the repository? `false` with an empty
   `tables` is a legitimate answer and the honest one for most services today —
   write it down. `true` means writing `alter table … enable row level security`
   **and `force row level security`** for every table you list, plus an
   `identity` function and a policy per command, and it is worth doing: the
   FORCE bit is the one rule in this whole document that nothing anywhere checks.
   See [`examples/valid/tenancy.rls-enforced.yml`](../examples/valid/tenancy.rls-enforced.yml).
4. `tenancy-check .` and fix what it names. A Go or Elixir service will get
   warnings; that is the expected verdict, not a failure to fix. A service whose
   key appears in its sources and is never a row scope — a verified token claim,
   a docstring, a vendored schema — names each such site in `scope.nonRowSites`
   with the reason, and the honest zero is expressible; see
   [`examples/valid/tenancy.honest-zero.yml`](../examples/valid/tenancy.honest-zero.yml)
   and **D47**.
5. Add it to the gate once it is green. Until then it is a second thing to
   remember, which is how it will be forgotten.
6. **Then gate the gate.** Run
   `bash "$CAFAYE_CORE/harness/bin/tenancy-proof" .` in the same gate, and
   nothing else — one line. It runs the checker twice and asserts both
   directions: the liar fixture must come back **exit 1 naming
   `tenancy.scope-lost`**, and this repository's own declaration must come back
   **exit 0**. The second direction is the one that carries the information: a
   checker that reds on everything satisfies the first and fails the second, so
   a step that merely fails proves nothing. A service that writes its own liar
   passes the path as the second argument
   (`tenancy-proof . test/fixtures/tenancy-liar --expect <finding-id>`), which
   is the shape the per-service wiring uses — the lie in the service's own
   language, in the service's own tree. Exit 2, never 0, when the proof could
   not happen: no python ≥ 3.9, a liar path that is not a directory.

## The red proof

[`harness/tests/tenancy_self_test.sh`](../harness/tests/tenancy_self_test.sh)
takes one conforming fixture, copies it, and breaks exactly one thing in each
copy: a missing `WHERE` on a read, a missing bind parameter, an unscoped list,
an unscoped update, an unscoped delete, an IDOR on fetch-by-id, a negative
assertion weakened from *absent* to *forbidden*, a file that is not there, a
line past the end of the file, a refusal in the declaration, an undeclared
query, and a service whose honest zero is not honest. Each asserts the checker
goes red **and names the finding and the entry point** — "something went red" is
not the claim, "this check is still the one that catches this defect" is, and
the two decay differently.

Four more break the declaration rather than the code, and they cover the four
findings that fire *before* a boundary is even declared — which is where the
fleet starts, since every repository in it produces
`tenancy.declaration-missing` today. A `tenancy.yml` that is not there, one the
reader cannot parse, a service that claims to scope by account and names no way
it does, and a declaration carrying a key the format does not declare.

**Twelve more break the database half**, and they are the eleven
`tenancy.rls-*` failures plus the positive control. Two of them are worth
naming because they are the packet in miniature:

- **breakage 17 deletes one line** — `alter table assets force row level
  security;` — and asserts that `tenancy.rls-owner-bypass` fires **about that
  table and about nothing else**. `force` is a separate `reloptions` bit from
  `enable`, so removing it cannot disturb the line beside it, which is what lets
  one finding be proved by one deletion rather than by a diff that moved two
  things;
- **breakage 7b points the third arm at a line asserting `nil`** and asserts
  `tenancy.positive-control-refused`. The other two arms are untouched and still
  green: the defect is one nobody notices, because every case a suite usually
  writes still passes.

The rest are the nine neighbours: policies that are never evaluated, a declared
policy the migrations do not create, DDL for a table nobody declared, `using
(true)`, the bare identity call, a policy applied to a `BYPASSRLS` role, a
policy on a foreign table, an unpinned `search_path` on a `SECURITY DEFINER`
function, and a view that reads as its owner. The eleventh is the public-read
tier's own: a declaration that names a public read the migrations do not write.

**Every one of the twenty-seven failure-severity findings has a breakage naming
it**, and `test_every_tenancy_finding_is_proved_able_to_go_red` in
[`tests/test_specs.py`](../tests/test_specs.py) is what keeps that true: a
finding added without a breakage is red rather than shipped untested. That
assertion is the reason the four above exist — they were the four that did not,
and every repository in the fleet was about to hit them. The same twelve RLS
breakages are ALSO driven in-process by
`test_every_behavioural_check_the_checker_has_is_proved_load_bearing`, which is
the only one of the three proofs `bin/prime` runs; a rule proved only in CI is a
rule a developer running the gate locally has learned nothing about.

**And three more are about the honest zero in a language this checker cannot
read** — the shape muse, gateway and site are written in. A green control proves
the vouched-for zero is expressible and that generated bytecode carrying the key
is not counted; a red proves a key-carrying site the declaration does not name
still fails; and a red proves a genuinely account-scoped statement dropped into
the same service still fails, which is the constraint the whole change is bounded
by. See **D47**.

### What `denial-shape` and `denial-unpaired` do not prove

The two vocabularies they refuse are a closed list of spellings this checker
**knows** are the wrong shape, not a closed list of correct ones. An
unrecognised token passes, and that has a measured consequence worth stating
rather than leaving to be discovered:

> An `update` denial arm declared as a bare `assert_equal 0, Assets.settle(...)`
> is **accepted**. It counts zero rows, so it is not proof the row is intact, and
> this checker cannot tell that apart from `rows_affected_zero` without owning the
> vocabulary of six languages' assertion libraries — which
> `test_the_three_way_denial_shape_is_required_on_every_entry_point` refuses on
> purpose, because `expects` is a pattern rather than an enum.

The alternative is a rule that fires only on English-language identifiers, which
is a rule that gets disabled within one release and leaves the fleet with no
check instead of an incomplete one. What **is** enforced is the direction that
has no good spelling: every ABSENCE token is refused on a denied write, in every
language at once, because "nothing came back" is a claim about a row that exists
and no language has a better way to phrase that claim. The row is in
[`harness/tenancy_findings.json`](../harness/tenancy_findings.json)'s
`notEnforced` list as the first entry, for the reason every other admitted gap is
there: a checker that reads as covering everything is the failure.

**The operation set deliberately stops at `call`,** and that is a hole rather than
a tidiness: a service that declares every entry point as `call` gets no shape
check at all, because this checker cannot see which clause denies a method call —
its scoping is enforced above the statement. See
[D42](DECISIONS.md#d42-is-a-denial-arms-shape-part-of-the-contract-and-who-owns-the-vocabulary-of-six-languages)
for the recommendation — fold it into the pgTAP migration rather than give it its
own packet — and for the one-enum cost of closing it.

Four cases assert a **warning stays green**: the unreadable-language service, a
declared source path that is not there, a key nothing matches, and row-level
security written in a language this checker cannot parse. All four exit `0`. Seven
green cases assert the report *names what it cannot see*, because a checker that
printed nothing at all about a service it cannot read would pass those too — the
substrate's counted baseline, the credential fixture's counted baseline, the same
five policies written by hand, the unreadable-language service, the honest zero,
and the liar with its predicate restored.

### The liar, and why a service's gate runs it in both directions

Every breakage above **breaks** something: a line is deleted, a value changed, a
file pointed at one that is not there. So none of them proves the checker can
judge a *declaration*, which is a different capability. A repository that has
never seen a failing declaration can believe any of them, including its own, and
the shape that belief takes is a document that is **schema-valid, complete, and
FALSE** — nothing omitted to catch and nothing invalid to catch.

[`harness/tests/fixtures/tenancy/liar/`](../harness/tests/fixtures/tenancy/liar/)
is that shape, committed whole, in the same spirit as
`fixtures/account-scope/liar/` before it. Its migration dropped
`and account_id = $2` from three of its six statements; its `tenancy.yml` still
says all seven entry points are enforced, every file named is present, every
line named is real, every denial arm points at the assertion it names, and the
`rls` block says the true thing. The verdict must be — and is — **4 failures, 0
warnings**: three `tenancy.scope-lost` naming `asset-fetch`, `asset-list` and
`asset-pending`, and one `tenancy.entry-absent`.

**The four honest rows are the half that makes the red worth anything.** Two
scoped writes, the variant fetch, and the bind in `src/assets.rb` are all TRUE,
and a checker that reds on everything satisfies every red assertion ever
written, including this fixture's. So the self-test asserts their **absence**
from the report rather than trusting the finding count, and green case 7 is the
other direction: the same fixture with the predicate restored on those three
statements and nothing else changed must come back green, which proves the red
is about the dropped predicate and not about the fixture's shape.

[`harness/bin/tenancy-proof`](../harness/bin/tenancy-proof) is that pair of
directions packaged as the one line a service's gate runs. The exit codes are
the whole contract: `0` both arms held, `1` an arm did not (the report says
which, and prints what fired), `2` the proof could not happen — never `0` and
never collapsed into `1`. It never lifts an exit code and never adds a
`|| true`; its counts are measured with `awk` rather than `grep -c || true`,
because `grep -c` exits 1 on a count of zero and that rescue is the one the
fleet forbids. `tests/test_specs.py` runs the real script four ways — both arms
holding, the pass arm failing on a genuinely red tree, a liar path that is not
there, and a red that names the wrong finding — so a wrapper that could only
say yes cannot ship.

The control runs first and is asserted **warning-free**, not merely green: that
is what proves the scanner classifies everything the fixture contains, so the
warning cases are warnings about a fixture's shape rather than artefacts of an
over-eager scanner.

**The credential fixture's control is a COUNT and not an exit code**, which is
worth stating as a shape rather than as a number. Its committed baseline is three
reds, all `tenancy.undeclared-entry` naming `pg_attribute` inside kit's template
— the entry-point scanner's gap below. A control that asserted "exited 0" would
be asserting a property this fixture **cannot have**, and one that asserted only
"zero `tenancy.rls-*`" would pass on a tree that had started failing for a reason
nobody wrote down. So it pins the total, pins that none of them is an RLS finding,
and pins that every one it carries names `pg_attribute`.

One detail in the script is worth naming because it is the bug this packet is
about, in miniature. Each breakage is applied by a textual `edit` that **fails
loudly when its anchor is missing, and equally when its anchor is ambiguous** —
when the file contains that text more than once. It did not used to, and the
first run of the stricter version caught a breakage that had been editing a
`#` comment instead of the line beneath it: green, reporting a check it had
never exercised. That is the same failure as a grep reporting "darkroom has no
routes", and the guard against it is a tool that says *I could not tell which
one you meant* rather than picking the first.

**It caught four more the day the database half landed**, and that is the
argument for it in one sentence: a policy's clause text
(`account_id = (select app.current_account())`) appears five times in the RLS
fixture, and a declaration's `expects: checksum` appears on three of its seven
entry points. Every RLS anchor therefore spans the `for … to …` line above the
clause, or the `create policy … on <table>` line above that, and the same anchors
are used in `tests/test_specs.py` so the two proofs cannot drift. A breakage that
had quietly edited the wrong policy would have reported a pass for a check it had
not exercised — the exact defect this script exists to prevent, discovered by the
guard rather than by a reviewer reading carefully.

It is deliberately not inside `bin/prime`. A self-test in every gate invocation
is a second gate that can disagree with the first, which is why core's CI runs it
as a step of its own.

**The guards caught three more, and the last two are the credential call's.**
The substrate's migration shows `select cafaye.protect_table('assets');` in
kit's own comment as the example of the call, and shows
`select cafaye.protect_credential_table('api_keys', 'token_digest');` the same
way, so both anchors are **two lines** and a one-line form is refused. When the
credential call's own breakage was first written with the one-line anchor it
reported *"went red as something else"* — and the alternative was editing the
template's prose, which would have left the table protected and reported a red
for nothing.

**A control that goes GREEN is a control working, and one of them was.**
Breakage (31) — the substrate fixture declaring an identity no policy reads —
turned green the moment the recogniser learned the second call, because every
clause of every generated policy resolved its identity perfectly while the
declaration named a different one. Nothing about the fixture changed and the
database was still protected; what was missing was a check that the **declaration
and the template disagree**, which is a different question from whether a clause
mentions the identity, and no regex over clause text can answer it.

## Open questions, left open deliberately

- **Should closure cover non-SQL languages?** It should, and it will need a
  parser per language rather than a pattern, which is `caf`'s job rather than
  core's. Until then the honest answer is the warning.
- **Should a `call` entry point's closure be checked by name?** A service could
  declare its repository method names and have the scanner check that each name
  appears in the sources. That is a real improvement and it is not this
  packet's, because it starts to be inference.
- **Does `expects` belong in the declaration at all?** It is a token the
  checker looks for, which makes the assertion present. A stronger version would
  assert the *shape* of the absence rather than a substring of it, and that
  needs to run the language's test.
- **Should `identity` admit `current_setting('app.account_id')`?** The `()`
  requirement exists so a policy's identity call can be hoisted out of the row
  loop, and it rules out an idiom several services will reach for. It is the
  first thing to revisit and it is named in
  [**D41**](DECISIONS.md#d41-how-is-the-force-rule-declared-and-what-may-a-warning-mean-in-the-tenancy-checker).

None of the four is urgent enough to hold the format up, and all four are
cheaper to answer once a service has adopted it and can say which one bites.

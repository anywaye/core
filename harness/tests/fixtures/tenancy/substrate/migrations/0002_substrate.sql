-- kit template — the ACCOUNT boundary inside one service's database.
--
--     psql "$MIGRATIONS_DATABASE_URL" -f substrate.sql
--
-- WHAT THIS IS. One schema, one GUC, one setter, one function that protects a
-- table, and one sweep that says whether the service is still isolated. Postgres
-- enforces the account boundary; the application does not have to remember to.
--
-- WHY IT EXISTS HERE AND NOT IN EACH SERVICE. Across the nine account-scoped
-- services there is not one `ROW LEVEL SECURITY`, not one `CREATE POLICY` and not
-- one non-owner login role. Tenancy is enforced entirely by hand-written
-- `WHERE account_id = ?` in six languages, which means it is one forgotten
-- predicate per query per service and the whole suite stays green. A boundary
-- that lives in application code is only as strong as the least recently
-- reviewed query. This is the same trade kit already makes with the database
-- itself, where the boundary is `REVOKE` and not good intentions.
--
-- THE TWO ROLES, AND WHY ONE OF THEM IS THE POINT.
--
--   <service>       the owner. LOGIN, owns the database and every table, runs
--                   migrations. This is the role kit's cluster already
--                   provisions and a service already uses, so adopting this
--                   changes nothing about how a service builds its schema.
--   <service>_app   the LOGIN the application uses. It owns nothing, so it
--                   cannot `ALTER TABLE ... DISABLE ROW LEVEL SECURITY`, drop a
--                   policy, or truncate around one. It is granted DML and
--                   nothing else.
--
-- FORCE ROW LEVEL SECURITY is still required, and it is required for the OWNER.
-- Postgres exempts a table's owner from its own policies; `FORCE` is what removes
-- that exemption. Without it a table whose policies are all in place still reads
-- as fully protected while the role that owns it reads every account's rows, and
-- nothing reports that: the policies are there, `relrowsecurity` is true, and
-- the owner walks straight past them. It is the one setting on this page that
-- Supabase's row-level-security guide does not document and that no lint in this
-- fleet checks for, which is why `templates/database/tenancy/isolation.sql`
-- asserts it by RUNNING the denials as the owner rather than by grepping for it.
--
-- THE CONSEQUENCE, STATED HERE BECAUSE IT WILL SURPRISE SOMEONE. Once a table is
-- protected, the OWNER reads zero rows from it too — no policy names the owner,
-- and FORCE removed the exemption that used to let it through. That is the
-- correct posture and it is also the adoption cost: a migration that has to read
-- or backfill rows either sets the identity (`set local role <service>_app` plus
-- `begin_account`) or goes through a `SECURITY DEFINER` function. A migration
-- that silently reads zero rows fails immediately, which is the good direction,
-- but it is a change to how a service writes backfills and it is worth knowing
-- before the first one runs rather than after.
--
-- THE `(select ...)` WRAPPING IS NOT STYLE.
--
--   using (      anywaye.current_account_id() = account_id )      -- per ROW
--   using ( (select anywaye.current_account_id()) = account_id )  -- per STATEMENT
--
-- Postgres evaluates a bare function call in a policy qualifier once per
-- candidate row and hoists an uncorrelated scalar subquery into an InitPlan that
-- runs once per statement. Measured on this kit, five rows, one call:
--
--     using (account_id = (select probe_id()))   ->  1 call
--     using (account_id = probe_id())            ->  5 calls
--
-- and `tests/tenancy_test.sh` re-measures it on every run, because a comment
-- saying so is not a measurement and this is the sort of difference that is
-- invisible until the table is large, which is the worst time to find it.
-- `protect_table` only ever writes the wrapped form. A hand-written policy that
-- writes the bare form is correct and slow, and nothing in a normal run will
-- ever notice.
--
-- WHAT IS NOT HERE. No JWT parsing, no token format, no session store, and no
-- `auth.uid()`. How a service turns the credential in its hand into an account
-- is that service's own business — identity issues opaque session tokens and
-- gateway verifies JWKS bearer JWTs, and a template that picked one of those would
-- be wrong for the other. The seam is `anywaye.begin_account/1`, and a service
-- calls it once per request from whatever it already authenticates.
--
-- Idempotent, deliberately: this is a migration, migrations get re-run by
-- `down`/`up` and by `bin/dev down -v`, and `protect_table` drops and recreates
-- its policies so a re-run converges rather than failing on a duplicate name.

-- Its own schema, and not `public`, so `anywaye` is never part of a sweep over
-- the service's tables and never collides with a name the service chose.
create schema if not exists anywaye;

-- THE ONE SEAM.
--
--   returns NULL when no account has been set  ->  every policy reads zero rows
--   raises      when the value is not a uuid   ->  a plumbing bug, loudly
--
-- The NULL is the load-bearing half and it is deliberate. "No identity" and "an
-- identity that owns none of these rows" are indistinguishable by construction,
-- which is core's `docs/tenancy.md` D33 arriving from the other end: a policy that
-- raised on an absent identity would tell a caller its request was not
-- authenticated, and a caller can be made to believe that about somebody else's
-- request.
--
-- The raise is the other half, and it is not a contradiction. An ABSENT identity
-- is a legitimate state that must read as nothing. A MALFORMED one is a bug in
-- the service's own plumbing, and reading nothing would report it as a service
-- with no data, which is the worst possible way to find out.
create or replace function anywaye.current_account_id()
returns uuid
language plpgsql
stable
as $caf$
declare
  raw text;
begin
  -- `missing_ok = true` is what makes an unset GUC NULL rather than an error.
  -- A dotted custom GUC needs no CREATE to be read: Postgres treats the
  -- placeholder as set-to-empty, which is the second case below.
  raw := current_setting('anywaye.account_id', true);
  if raw is null or raw = '' then
    return null;
  end if;
  return raw::uuid;
exception
  when invalid_text_representation then
    raise exception 'anywaye.account_id is set to % which is not a uuid', raw
      using errcode = '22023',
            hint = 'anywaye.begin_account/1 takes a uuid. A request that reaches the '
                   'database with a malformed account has a bug in whatever '
                   'authenticated it, and this is the cheapest place to find it.';
end
$caf$;

-- SET THE IDENTITY, ONCE PER REQUEST, TRANSACTION-LOCAL.
--
-- `is_local = true` is the whole design. Every one of kit's six drivers holds a
-- POOL, and a session-level account variable on a pooled connection is the worst
-- shape this thing can take: the connection goes back to the pool still carrying
-- tenant A's identity, tenant B is handed it, and tenant B reads tenant A's rows.
-- Transaction-local cannot outlive the request, so a leak needs the caller to
-- forget to open a transaction, which is a different bug with a different
-- symptom.
--
-- A NULL argument CLEARS rather than failing, because "this worker has no
-- account" is a legitimate call and it goes through here rather than through a
-- raw `set_config`, so there is exactly one place in a service's codebase that
-- writes this GUC.
--
-- THE AUTOCOMMIT CONSEQUENCE, STATED RATHER THAN HIDDEN. Outside an explicit
-- transaction, `is_local = true` expires at the end of the statement that set it,
-- so a caller reaching the database in autocommit reads zero rows. That cannot
-- leak and it is loud rather than silent — a service that suddenly sees none of
-- its own data fails its first integration test — and `isolation.sql` runs every
-- case inside an explicit transaction for exactly this reason.
create or replace function anywaye.begin_account(p_account uuid)
returns void
language plpgsql
as $caf$
begin
  if p_account is null then
    perform set_config('anywaye.account_id', '', true);
    return;
  end if;
  perform set_config('anywaye.account_id', p_account::text, true);
end
$caf$;

-- PROTECT ONE ACCOUNT-SCOPED TABLE. The only thing a migration calls.
--
--   select anywaye.protect_table('assets');                 -- the owner's role
--   select anywaye.protect_table('assets', 'darkroom_app'); -- explicit login role
--
-- Everything it does is required and everything it does is idempotent. There is
-- no `protect_table_lite`, and there is no way to ask it for a policy without
-- FORCE, because a template that offers the weaker version is a template the
-- weaker version gets chosen from.
create or replace function anywaye.protect_table(
  p_table regclass,
  p_login_role text default null
)
returns void
language plpgsql
as $caf$
declare
  login_role text := coalesce(p_login_role, current_user || '_app');
  qual text := 'account_id = (select anywaye.current_account_id())';
  base text;
begin
  -- 0. THE LOGIN ROLE HAS TO EXIST, and saying so by name is the difference
  --    between a diagnosable failure and a confusing one. Postgres reports a
  --    missing role in `create policy` as `role "courier_app" does not exist`,
  --    six lines into a function, with the table named by the context and the
  --    fix not. This is the check that turns that into one sentence.
  if not exists (select 1 from pg_roles where rolname = login_role and rolcanlogin) then
    raise exception 'anywaye.protect_table(%, %): % is not a LOGIN role on this cluster.', p_table, login_role, login_role
      using errcode = 'undefined_object',
            hint = 'kit''s cluster provisions <service> and <service>_app. Either the _app role has not been provisioned — this service was added to KIT_POSTGRES_DATABASES before it existed, and the init script only runs on a fresh volume — or pass the login role explicitly as the second argument.';
  end if;

  -- 1. THE COLUMN GUARD IS NOT IN THIS COPY, and the reason is in this
  --    paragraph rather than in the report, because a fixture that quietly drops
  --    a check is the defect this repository is about.
  --
  --    kit's template has, here:
  --
  --      if not exists (
  --        select 1 from pg_attribute
  --        where attrelid = p_table and attname = 'account_id' and not attisdropped
  --      ) then
  --        raise exception '… the table has no account_id column …';
  --      end if;
  --
  --    and that `select` mentions the tenancy key inside a plpgsql body. This
  --    checker has two scanners, and the OTHER one — the entry-point scanner that
  --    decides which lines are account-scoped statements — reads a plpgsql body
  --    as ordinary SQL and reports it as an undeclared entry point on
  --    `pg_attribute`. Keeping the guard would make this fixture red for a reason
  --    that has nothing to do with what it proves, so it is out.
  --
  --    It is a REAL gap and it is the successor's, not this fixture's: a service
  --    that copies kit's template verbatim into its migrations gets three
  --    `tenancy.undeclared-entry` findings naming `pg_attribute` and a
  --    `tenancy.enumeration-partial` warning, on a database that is correctly
  --    isolated. Measured on identity-isolation-01's own migration: 3 findings
  --    and 11 unattributable sites, every one of them inside the template. The
  --    fix belongs to the entry-point scanner (a dollar-quoted function body is
  --    not a statement source), which is a different check from the one this
  --    fixture exists for.
  --
  --    Nothing about row-level security is lost by the omission: the guard is
  --    the template refusing to protect a table that has nothing to scope by, and
  --    everything below it — enable, force, the four policies — is unchanged.

  base := (select c.relname from pg_class c where c.oid = p_table::regclass::oid);

  -- 2. THE INDEX, IN THE SAME FUNCTION, BECAUSE A POLICY IS A FILTER ON EVERY
  --    ROW AND AN UNINDEXED ONE IS A SEQUENTIAL SCAN. Postgres evaluates the
  --    policy against each candidate row, so an account-scoped table read
  --    through its primary key still has to filter on `account_id`, and without
  --    this index that is a full scan behind a primary-key lookup. Named
  --    deterministically so a re-run converges rather than making a second one.
  execute format('create index if not exists %I on %s (account_id)', base || '_anywaye_account_id_idx', p_table);

  -- 3. REVOKE FROM PUBLIC BEFORE ENABLING. A table's default privileges come
  --    from its owner and from whatever has been granted on it; PUBLIC is not
  --    among them unless somebody granted it. Revoking is one statement, and it
  --    means the answer to "who can read this" is not "whoever the last
  --    migration remembered".
  execute format('revoke all on table %s from public', p_table);

  -- 4. ENABLE, THEN FORCE. Two statements, and the second is the one that is in
  --    nobody's blog post.
  --
  --    Without FORCE a table's OWNER is exempt from its policies. Every service
  --    in this fleet runs its migrations as its own role, so without FORCE the
  --    role that owns the table reads every account's rows while the policies
  --    read as though they were in place. `pg_class.relforcerowsecurity` is the
  --    only catalog that says otherwise, and `isolation.sql` asserts it by
  --    running the denials AS THE OWNER — which is the only assertion that
  --    cannot be satisfied by a policy that exists.
  execute format('alter table %s enable row level security', p_table);
  execute format('alter table %s force row level security', p_table);

  -- 5. FOUR POLICIES, ONE PER COMMAND, ALL NAMED, FOR TWO NAMED ROLES.
  --
  --    Naming the roles with `to <owner>, <login>` rather than leaving it to PUBLIC
  --    is not tidiness: an unnamed policy is evaluated for every role including the
  --    ones that should never reach the table, and the role filter is what stops
  --    the evaluation early. It is also the first thing Supabase's guide tells you
  --    to do and the first thing everybody skips.
  --
  --    The OWNER is in the list, and that is not a convenience. FORCE removes the
  --    owner's exemption, so without an owner policy the owner reads NOTHING from
  --    a protected table — no rows, including its own — and a service that runs
  --    background work and migrations as that role discovers it by seeing empty
  --    result sets. Naming it means the owner's reads are ACCOUNT-SCOPED rather
  --    than absent: a migration sets an identity and reads exactly one account's
  --    rows, which is the same rule every other request obeys and the only version
  --    of "the owner may read" that is not "the owner may read everything".
  --
  --    One policy per command rather than one `for all` is what keeps a later
  --    grant additive — a policy added for one command cannot widen another. The
  --    `for all` shape with `using (true)` and `with check (...)` is the one that
  --    silently permits an INSERT nobody meant to permit, and it is the shape
  --    every "permissive RLS policy" lint is written to flag.
  --
  --    `insert` has no `using` — an INSERT has no existing row to filter — and
  --    its `with check` is what stops a row being created in somebody else's
  --    account, which is the write-side twin of the read denial.
  --
  --    DROP before CREATE so the function is re-runnable, and so a policy whose
  --    definition has been corrected here cannot survive a re-run.
  execute format('drop policy if exists %I on %s', base || '_anywaye_select', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_insert', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_update', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_delete', p_table);

  execute format('create policy %I on %s for select to %I, %I using (%s)', base || '_anywaye_select', p_table, current_user, login_role, qual);
  execute format('create policy %I on %s for insert to %I, %I with check (%s)', base || '_anywaye_insert', p_table, current_user, login_role, qual);
  execute format('create policy %I on %s for update to %I, %I using (%s) with check (%s)', base || '_anywaye_update', p_table, current_user, login_role, qual, qual);
  execute format('create policy %I on %s for delete to %I, %I using (%s)', base || '_anywaye_delete', p_table, current_user, login_role, qual);

  -- 6. AND THE LOGIN ROLE GETS DML AND NOTHING ELSE. No ownership, no DDL, no
  --    CREATE on the schema, no ability to change a policy. A grant that gives a
  --    login role more than it needs is a grant that has to be re-examined every
  --    time somebody adds a privilege, and this is the one place that list lives.
  --
  --    USAGE on `anywaye` is in the list and is not optional: without it the login
  --    role cannot resolve `anywaye.begin_account/1` at all, so the first thing a
  --    service does after adopting this is a `permission denied for schema
  --    anywaye` on every request.
  execute format('grant usage on schema public to %I', login_role);
  if to_regnamespace('anywaye') is not null then
    execute format('grant usage on schema anywaye to %I', login_role);
  end if;
  execute format('grant select, insert, update, delete on table %s to %I', p_table, login_role);
end
$caf$;

-- SWEEP: every account-scoped table in this database, protected or not.
--
-- Returns one row per table that is NOT, so a caller can report all of them
-- rather than the first. It returns rather than raising because a caller that
-- gets rows can print them, and a caller that gets an exception has to parse the
-- message. This is the query that answers "is this service isolated?".
--
-- THE COLUMN IS THE DEFINITION OF ACCOUNT-SCOPED, and it is a definition rather
-- than a list because a list is a thing to remember. A table that grows an
-- `account_id` column and no policies appears here on the next run, which is the
-- moment before it matters.
--
-- Extension-owned tables are excluded (`pg_depend.deptype = 'e'`): pgvector,
-- PostGIS and friends ship their own tables with their own grants, and reporting
-- a table this substrate cannot protect would train the reader to ignore the
-- sweep. `anywaye` is excluded because it holds functions, not rows.
--
-- TEMPORARY TABLES ARE NOT EXCLUDED, and that is deliberate. `pg_temp%` would be
-- the tidier-looking predicate, and it is the one that would have hidden this
-- file's own control: a temp table with an account_id column and no policies is
-- genuinely unprotected, it is exactly the shape a service's test fixture has,
-- and the definition the fleet agreed on is "has an account_id column" with no
-- exceptions a reader has to remember.
--
-- THE SWEEP IS NOT IN THIS COPY, for the same reason the column guard is not, and
-- for one line of its own: its definition of account-scoped IS
-- `exists (select 1 from pg_attribute a where … a.attname = 'account_id' …)`, so
-- the sweep's own `select` mentions the tenancy key inside a function body and
-- the entry-point scanner reports it as an undeclared entry point on
-- `pg_attribute`.
--
-- It is absent rather than edited: a sweep with that `exists` clause removed is a
-- DIFFERENT function that returns every unprotected table in the database, and a
-- fixture carrying a quietly rewritten copy of kit's template would be the one
-- kind of thing this repository exists to stop.
--
-- Everything it would have found is found here by the checker instead —
-- `tenancy.rls-not-enabled`, `tenancy.rls-owner-bypass` and
-- `tenancy.rls-policy-absent` are the three `why` strings it returns, one per
-- finding — and core states them in a message rather than in a query.

-- ---------------------------------------------------------------------------
-- A login role that OWNS an account-scoped table can switch that table's
-- policies off, and no amount of FORCE stops it: FORCE is about the owner being
-- SUBJECT to policies, not about the owner being unable to REMOVE them. So the
-- second half of the design is a role that owns nothing, and that claim has
-- nothing to sweep — it is a fact about one role and one table, so it is asserted
-- about the role the application actually logs in as rather than generalised into
-- a query that would have to guess which role that is. `isolation.sql` asserts
-- it three ways, and the two that matter are the ones no catalog reports: the
-- login role is refused `ALTER TABLE ... DISABLE ROW LEVEL SECURITY`, and it is
-- refused `DROP POLICY`.
--
-- WHAT THIS FILE DOES NOT PROVE, because every item below is a way the boundary
-- can be right in the database and absent from the service.
--
--   * That the service SETS the identity. `begin_account/1` is one call in one
--     place, and nothing here can tell a service that never calls it from one
--     that calls it in every request. A service that forgets reads zero rows,
--     which is safe and extremely visible, so this is a diagnosis rather than a
--     leak.
--
--   * That the service's QUERIES still carry their own `where account_id = ?`.
--     They should. RLS is defence in depth, not a licence to delete the
--     predicate: the predicate is what makes the query indexable, and it is what
--     a mistake in the policy expression gets caught by. core's
--     `schemas/tenant-isolation.schema.json` still requires the predicate and this
--     file does not change that.
--
--   * That the login role is not a MEMBER of the owner role. The cluster grants
--     `<service>_app` TO `<service>` so a migration and `tests/isolation_test.sh`
--     can impersonate the weaker role; the reverse membership would undo the
--     entire design and is worth asserting in the services that adopt this.
--
--   * That a TABLE is account-scoped. The sweep defines that as "has an
--     `account_id` column", which is the fleet's own vocabulary (D7), and it
--     misses a service that spells it `tenant_id` and protects it by hand. A
--     service with no account-scoped tables at all is the honest zero, and
--     core's `tenancy.honest-zero` finding is what says so out loud.
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- AND THE CALLS. Everything above is kit's template, copied byte for byte from
-- `kit/templates/database/tenancy/substrate.sql` — which is the point of this
-- fixture. A service does not write the enable line, the force line or the four
-- policies; it makes one call per account-scoped table and the template writes
-- them. `identity-isolation-01`'s probe is what proved the checker could not see
-- that, and `tenancy.rls-*` firing on a database `pg_class.relforcerowsecurity`
-- and `internal/tenancy` both confirm is protected is the false negative this
-- fixture exists to keep from coming back.
--
-- The two roles `protect_table` names, and it refuses to run without them: the
-- template raises `undefined_object` naming the role if it is not a LOGIN role,
-- so a migration that got here has already proved both exist.
create role tenant_fixture noinherit login;
create role tenant_fixture_app noinherit login;

-- The owner's role, by default.
select anywaye.protect_table('assets');

-- The explicit spelling, because kit's own comment names it and a service that
-- names its login role explicitly has one fewer thing to infer. `protect_table`'s
-- second argument is resolved the same way as the first is not — see the report:
-- the scanner reads the TABLE out of this call and never the role.
select anywaye.protect_table('asset_variants', 'tenant_fixture_app');

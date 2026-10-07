-- 0002_rls.sql — the DATABASE half of the boundary, for `tenant-fixture`.
--
-- 0001_assets.sql scopes every statement in the repository layer. This file is
-- the second, independent enforcement: row-level security, so a query the
-- repository forgot to scope still cannot reach another account's rows. The two
-- are independent on purpose — every line here could be deleted and the
-- repository predicates would still hold, and every repository predicate could be
-- dropped and these policies would still hold.
--
-- Every construct below is a rule, and the reason is in its comment:
--
--   * `enable row level security` — without it the policies below are never
--     evaluated at all, and a policy that is never evaluated raises nothing.
--   * `force row level security` — **the line this whole packet exists for.**
--     Postgres does not apply row-level security to a table's OWNER unless the
--     table is forced, and this service owns the tables it created in its own
--     schema. Omit it and every policy on this table is decoration: the queries
--     still succeed, the policies still exist, and `tenant_app` reads every row
--     in the database. `force` is its own reloptions bit, so it can be present
--     without the enable bit above it — which is why the schema says `forced`
--     and the checker looks for it rather than assuming it.
--   * `to tenant_app` — a policy with no `to` clause applies to PUBLIC.
--   * `(select app.current_account())` — wrapped, so Postgres evaluates it once
--     per statement. The bare call is re-evaluated for every row.
--   * `set search_path = ''` on the SECURITY DEFINER function — otherwise a
--     caller can point an unqualified name at an object they created and have
--     the function resolve to it with the owner's rights.
--   * `security_invoker = on` on the view — a view without it reads with its
--     OWNER's privileges, so the reader's policies never run.

create schema if not exists app;

-- The identity every policy reads. SECURITY DEFINER so the runtime role cannot
-- read arbitrary settings out of the session, and `set search_path = ''` because
-- without a pinned search path a caller can point an unqualified name at their
-- own object and run it with this function's owner's rights. The GUC is
-- `app.current_account` rather than `app.account_id` so that this file's own
-- text cannot be mistaken for a statement scoping a row.
create function app.current_account() returns uuid
  language sql
  stable
  security definer
  set search_path = ''
as $$ select nullif(current_setting('app.current_account', true), '')::uuid $$;

create role tenant_app noinherit login;

-- The public reader: a named role the public read is granted to. It is NOT
-- PUBLIC — a policy with no `to` clause applies to every role including the
-- migration role, and that is `tenancy.rls-permissive` however the declaration
-- spells it. Naming the role is what makes the read a claim with evidence.
create role public_reader noinherit;

create table assets (
  id         uuid primary key,
  account_id uuid not null,
  checksum   text        not null,
  status     text        not null default 'pending'
);

create table asset_variants (
  id         uuid primary key,
  account_id uuid not null,
  asset_id   uuid not null
);

-- The reads. `USING` filters the rows a command may SEE, so a denied statement
-- matches zero rows and raises NOTHING — which is what the `other-account` arm
-- of the denial shape asserts with `is_empty`, and why asserting an exception
-- there would be asserting a privilege failure and passing for the wrong reason.
create policy assets_select_own on assets
  for select to tenant_app
  using (account_id = (select app.current_account()));

create policy assets_update_own on assets
  for update to tenant_app
  using (account_id = (select app.current_account()))
  with check (account_id = (select app.current_account()));

create policy asset_variants_select_own on asset_variants
  for select to tenant_app
  using (account_id = (select app.current_account()));

-- The write a caller could aim at somebody else. `WITH CHECK` is evaluated
-- against the row being WRITTEN, so a violation raises 42501 rather than
-- matching zero rows — the other denial mechanism, and the other assertion.
create policy assets_insert_own on assets
  for insert to tenant_app
  with check (account_id = (select app.current_account()));

-- A view over an account-scoped table, with `security_invoker` so the reader's
-- own privileges apply. Without it the view runs as its owner, the owner's
-- policies are what get evaluated, and the table's are not — which is a policy
-- that never fires on the way nobody was looking.
create view own_assets with (security_invoker = on) as select id, checksum, status from assets where account_id = (select app.current_account());

alter table assets enable row level security;
alter table assets force row level security;
alter table asset_variants enable row level security;
alter table asset_variants force row level security;

-- The public read, and it is a claim with evidence rather than a switch. The
-- table is declared in rls.publicRead, the policy is named there, and the role
-- it grants to is named there too — so the checker compares the claim against
-- this DDL rather than trusting a boolean. `to public_reader` is the load-bearing
-- line: a policy with no `to` clause applies to PUBLIC, which is every role
-- including the migration role, and that is `tenancy.rls-permissive` however
-- the declaration spells it. The clause is `using (true)` because a public read
-- IS a read scoped by nothing — that is the product, not the defect.
create policy publishers_public_read on publishers
  for select to public_reader
  using (true);

alter table publishers enable row level security;
alter table publishers force row level security;

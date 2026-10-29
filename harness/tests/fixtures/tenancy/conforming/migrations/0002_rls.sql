
create schema if not exists app;

create function app.current_account() returns uuid
  language sql
  stable
  security definer
  set search_path = ''
as $$ select nullif(current_setting('app.current_account', true), '')::uuid $$;

create role tenant_app noinherit login;

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

create policy assets_insert_own on assets
  for insert to tenant_app
  with check (account_id = (select app.current_account()));

create view own_assets with (security_invoker = on) as select id, checksum, status from assets where account_id = (select app.current_account());

alter table assets enable row level security;
alter table assets force row level security;
alter table asset_variants enable row level security;
alter table asset_variants force row level security;


create schema if not exists anywaye;

create or replace function anywaye.current_account_id()
returns uuid
language plpgsql
stable
as $caf$
declare
  raw text;
begin
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
  if not exists (select 1 from pg_roles where rolname = login_role and rolcanlogin) then
    raise exception 'anywaye.protect_table(%, %): % is not a LOGIN role on this cluster.', p_table, login_role, login_role
      using errcode = 'undefined_object',
            hint = 'kit''s cluster provisions <service> and <service>_app. Either the _app role has not been provisioned — this service was added to KIT_POSTGRES_DATABASES before it existed, and the init script only runs on a fresh volume — or pass the login role explicitly as the second argument.';
  end if;


  base := (select c.relname from pg_class c where c.oid = p_table::regclass::oid);

  execute format('create index if not exists %I on %s (account_id)', base || '_anywaye_account_id_idx', p_table);

  execute format('revoke all on table %s from public', p_table);

  execute format('alter table %s enable row level security', p_table);
  execute format('alter table %s force row level security', p_table);

  execute format('drop policy if exists %I on %s', base || '_anywaye_select', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_insert', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_update', p_table);
  execute format('drop policy if exists %I on %s', base || '_anywaye_delete', p_table);

  execute format('create policy %I on %s for select to %I, %I using (%s)', base || '_anywaye_select', p_table, current_user, login_role, qual);
  execute format('create policy %I on %s for insert to %I, %I with check (%s)', base || '_anywaye_insert', p_table, current_user, login_role, qual);
  execute format('create policy %I on %s for update to %I, %I using (%s) with check (%s)', base || '_anywaye_update', p_table, current_user, login_role, qual, qual);
  execute format('create policy %I on %s for delete to %I, %I using (%s)', base || '_anywaye_delete', p_table, current_user, login_role, qual);

  execute format('grant usage on schema public to %I', login_role);
  if to_regnamespace('anywaye') is not null then
    execute format('grant usage on schema anywaye to %I', login_role);
  end if;
  execute format('grant select, insert, update, delete on table %s to %I', p_table, login_role);
end
$caf$;


create role tenant_fixture noinherit login;
create role tenant_fixture_app noinherit login;

select anywaye.protect_table('assets');

select anywaye.protect_table('asset_variants', 'tenant_fixture_app');

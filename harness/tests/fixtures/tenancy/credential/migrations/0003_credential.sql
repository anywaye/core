
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


create or replace function anywaye.current_credential_digest()
returns text
language plpgsql
stable
as $caf$
declare
  raw text;
begin
  raw := current_setting('anywaye.credential_digest', true);
  if raw is null or raw = '' then
    return null;
  end if;
  return raw;
end
$caf$;

create or replace function anywaye.begin_credential(p_digest text)
returns void
language plpgsql
as $caf$
begin
  if p_digest is null then
    perform set_config('anywaye.credential_digest', '', true);
    return;
  end if;
  perform set_config('anywaye.credential_digest', p_digest, true);
end
$caf$;

create or replace function anywaye.protect_credential_table(
  p_table regclass,
  p_digest_column text,
  p_login_role text default null
)
returns void
language plpgsql
as $caf$
declare
  login_role text := coalesce(p_login_role, current_user || '_app');
  base text;
  qual text;
begin
  if p_digest_column is null
     or p_digest_column !~ '^[A-Za-z_][A-Za-z0-9_$]*$' then
    raise exception 'anywaye.protect_credential_table(%, %): the digest column must be one bare column name, and % is not one.', p_table, coalesce(p_digest_column, '<null>'), coalesce(p_digest_column, 'null')
      using errcode = 'undefined_column',
            hint = 'The second argument is the column a caller presents to resolve a credential on this table — `token_digest` for a hashed API key, `token` for a hashed invitation. It is a column of this table and nothing else.';
  end if;

  if not exists (
    select 1 from pg_attribute
    where attrelid = p_table and attname = p_digest_column and not attisdropped
  ) then
    raise exception 'anywaye.protect_credential_table(%, %): the table has no % column.', p_table, login_role, p_digest_column
      using errcode = 'undefined_column',
            hint = 'A credential table resolves by the column a caller presents. Name the one this table has; if it has none, this table is not resolved by an unguessable value and does not want this mechanism.';
  end if;

  perform anywaye.protect_table(p_table, p_login_role);

  base := (select c.relname from pg_class c where c.oid = p_table::regclass::oid);

  execute format('create index if not exists %I on %s (%I)',
                 base || '_anywaye_' || p_digest_column || '_idx', p_table, p_digest_column);

  qual := format('%I = (select anywaye.current_credential_digest())', p_digest_column);

  execute format('drop policy if exists %I on %s', base || '_anywaye_resolve', p_table);
  execute format('create policy %I on %s for select to %I, %I using (%s)',
                 base || '_anywaye_resolve', p_table, current_user, login_role, qual);

  if to_regnamespace('anywaye') is not null then
    execute format('grant usage on schema anywaye to %I', login_role);
  end if;
end
$caf$;

create or replace function anywaye.credential_tables()
returns table (table_schema text, table_name text, digest_column text)
language sql
stable
as $caf$
  select n.nspname::text,
         c.relname::text,
         (regexp_match(
            lower(coalesce(pg_get_expr(p.polqual, p.polrelid), '')),
            '^ *\(?([a-z_][a-z0-9_$]*) = \( *select anywaye\.current_credential_digest\(\)'
          ))[1]::text
    from pg_policy p
    join pg_class c on c.oid = p.polrelid
    join pg_namespace n on n.oid = c.relnamespace
   where p.polname like '%!_anywaye!_resolve' escape '!'
     and p.polcmd = 'r'
     and lower(coalesce(pg_get_expr(p.polqual, p.polrelid), ''))
         like '%anywaye.current_credential_digest()%'
   order by n.nspname, c.relname
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

  if not exists (
    select 1 from pg_attribute
    where attrelid = p_table and attname = 'account_id' and not attisdropped
  ) then
    raise exception 'anywaye.protect_table(%, %): the table has no account_id column, so there is nothing to scope it by.', p_table, login_role
      using errcode = 'undefined_column',
            hint = 'Either the column is spelled something else — write the policy yourself and name the fleet''s key — or this table is not account-scoped and should not be protected. A service holding no customer rows is core''s honest zero and needs none of this.';
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

create or replace function anywaye.unprotected_tables()
returns table (table_schema text, table_name text, why text)
language sql
stable
as $caf$
  with scoped(nspname) as (
    select 'anywaye'::name
    union
    select n.nspname
      from pg_namespace n
     where n.nspname = 'pg_temp' or left(n.nspname, 8) = 'pg_temp_'
    union
    select n.nspname
      from pg_namespace n
      join pg_class c on c.relnamespace = n.oid
      join pg_policy p on p.polrelid = c.oid
     where c.relkind = 'r'
       and p.polname ~ '_anywaye_(select|insert|update|delete)$'
  )
  select n.nspname::text,
         c.relname::text,
         case
           when not c.relrowsecurity then 'row level security is not enabled'
           when not c.relforcerowsecurity then 'row level security is not FORCED, so the table owner bypasses it'
           when not exists (select 1 from pg_policy p where p.polrelid = c.oid) then 'row level security is enabled with no policy, so every row is hidden'
           else ''
         end
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  left join pg_depend d on d.objid = c.oid and d.deptype = 'e'
  where c.relkind = 'r'
    and d.objid is null
    and n.nspname in (select s.nspname from scoped s)
    and exists (
      select 1 from pg_attribute a
      where a.attrelid = c.oid and a.attname = 'account_id' and not a.attisdropped
    )
    and (
      not c.relrowsecurity
      or not c.relforcerowsecurity
      or not exists (select 1 from pg_policy p where p.polrelid = c.oid)
    )
  order by n.nspname, c.relname
$caf$;

create role tenant_fixture noinherit login;
create role tenant_fixture_app noinherit login;

select anywaye.protect_table('assets');

select anywaye.protect_table('asset_variants', 'tenant_fixture_app');

select anywaye.protect_credential_table('api_keys', 'token_digest');

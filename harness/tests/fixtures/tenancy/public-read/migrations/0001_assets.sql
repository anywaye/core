-- 0001_assets.sql — customer-owned rows, and every statement that reaches them.
--
-- `account_id` is NOT NULL and every statement that touches a row carries it.
-- tenancy.yml names each one; this file is the fixture those declarations are
-- checked against, so it is written to be broken on purpose by the self-test.

create table assets (
  id         uuid primary key,
  account_id uuid not null,
  checksum   text        not null,
  status     text        not null default 'pending',
  unique (account_id, checksum)
);

create table asset_variants (
  id         uuid primary key,
  account_id uuid not null,
  asset_id   uuid not null references assets (id)
);

-- one asset, by id
select * from assets where id = $1 and account_id = $2

-- the account's own list, oldest first
select id, checksum, status from assets where account_id = $1 order by created_at

-- the pending window a settlement job polls
select id from assets where account_id = $1 and status = 'pending'

-- mark one asset settled
update assets set status = 'settled' where id = $1 and account_id = $2

-- remove one asset
delete from assets where id = $1 and account_id = $2

-- one variant, by id
select * from asset_variants where id = $1 and account_id = $2

-- A DELIBERATELY PUBLIC-READABLE table, the shape pantry's `publishers` is in:
-- published publishers and their services are readable by anyone, so this table
-- carries no account column at all and its only policy grants SELECT to a
-- named public reader role. It is the reason `rls.publicRead` exists — without
-- a declared tier, the always-true clause in 0002_rls.sql is
-- `tenancy.rls-permissive` and the only ways to go green are to lie or to
-- weaken the check. It is LAST in this file on purpose: every line number
-- tenancy.yml declares above is pinned, and a table inserted in the middle
-- would shift them all.
create table publishers (
  id   uuid primary key,
  name text not null
);

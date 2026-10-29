
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

select * from assets where id = $1 and account_id = $2

select id, checksum, status from assets where account_id = $1 order by created_at

select id from assets where account_id = $1 and status = 'pending'

update assets set status = 'settled' where id = $1 and account_id = $2

delete from assets where id = $1 and account_id = $2

select * from asset_variants where id = $1 and account_id = $2

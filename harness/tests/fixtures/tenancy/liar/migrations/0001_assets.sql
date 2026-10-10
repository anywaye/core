-- 0001_assets.sql — customer-owned rows, and the statements that reach them.
--
-- THE LIAR'S CODE HALF. This file is the conforming fixture's, with the
-- predicate dropped from three of the six statements — the refactor this
-- checker's own docstring names: "A refactor that drops one
-- `and account_id = $2` gives a customer another customer's files and the whole
-- suite stays green." Three of these six lost it. The other three kept it, and
-- they are the honest half: a finding that fired on all six would be a checker
-- that reds on everything, which is exactly what the self-test's control rules
-- out.
--
-- Nothing in here is omitted and nothing in here is invalid. The create tables
-- are the conforming fixture's, the update, the delete and the variant fetch
-- still carry `account_id`, and `src/assets.rb` still binds it. What is false
-- is the CLAIM tenancy.yml makes about lines 22, 25 and 28 — and a claim is
-- what this fixture exists to catch.

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

-- one asset, by id — the IDOR, waiting for the predicate to come back
select * from assets where id = $1

-- the account's own list, oldest first
select id, checksum, status from assets order by created_at

-- the pending window a settlement job polls
select id from assets where status = 'pending'

-- mark one asset settled
update assets set status = 'settled' where id = $1 and account_id = $2

-- remove one asset
delete from assets where id = $1 and account_id = $2

-- one variant, by id
select * from asset_variants where id = $1 and account_id = $2

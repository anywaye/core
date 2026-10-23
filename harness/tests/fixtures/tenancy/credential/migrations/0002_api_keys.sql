-- 0002_api_keys.sql — the one table holding a machine credential.
--
-- TWO COLUMNS THAT ARE NOT THE SAME KIND OF COLUMN, and the whole fixture is the
-- difference between them. `account_id` is the fleet's tenancy key (D7): a row
-- belongs to exactly one account, and every statement that reaches it carries
-- it. `token_digest` is a value the CALLER HAS ALREADY PROVED IT HOLDS — the
-- digest of an API key the service hashed off the request before any query ran.
--
-- That second column is why this table gets a call and the other two do not.
-- `protect_table` scopes a table by the account acting on it, and an
-- authentication request has no account yet: it has a credential it is trying
-- to resolve. `protect_credential_table` protects the table exactly as
-- `protect_table` does — same four policies, same ENABLE, same FORCE — and then
-- adds ONE `for select` policy qualified by the digest, which is what lets the
-- request read the one row whose digest it presented and nothing else in the
-- database.
--
-- The column is NOT NULL and it is UNIQUE, because a mechanism that widens a
-- read to "the row whose value you presented" is only sound while the value
-- identifies one row. Two rows sharing a digest would make the predicate admit
-- both, and the second is another tenant's credential.
create table api_keys (
  id           uuid primary key,
  account_id   uuid not null,
  token_digest text not null unique,
  name         text not null,
  created_at   timestamptz not null default now()
);

create index api_keys_anywaye_account_id_idx on api_keys (account_id);

-- WHERE THE RESOLUTION QUERY IS NOT, and the omission is this file's second
-- claim rather than a shortcut.
--
-- In `identity` the resolution is `select id, account_id, name from api_keys
-- where token_digest = $1` — the predicate is in the caller's query AND in the
-- policy, which is the whole reason a resolution session that dropped the WHERE
-- would read one row rather than the table. It is not written here, because
-- core's ENTRY-POINT scanner reads the `account_id` in its select list as an
-- account-scoped statement about an undeclared table and answers
-- `tenancy.undeclared-entry` — and this fixture's claim is that the ONLY
-- difference from `fixtures/tenancy/substrate/` is the call. Adding a second,
-- unrelated red here would make a finding that moved between the fixtures
-- unattributable, which is the property the three fixtures exist to keep.
--
-- The query is absent from `entryPoints[]` for the same reason and not by
-- omission: an entry point is a statement reached as an ACCOUNT, and this one is
-- reached before there is an account — that is what the fifth policy is for.
-- `identity` measures the behaviour itself in `internal/tenancy`, in a database
-- this file cannot run; what is declared HERE is the boundary, and the boundary
-- on this table is five policies and one call.

create table api_keys (
  id           uuid primary key,
  account_id   uuid not null,
  token_digest text not null unique,
  name         text not null,
  created_at   timestamptz not null default now()
);

create index api_keys_anywaye_account_id_idx on api_keys (account_id);


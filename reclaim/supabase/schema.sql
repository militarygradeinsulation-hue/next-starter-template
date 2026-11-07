-- OPTIONAL FUTURE MIGRATION. Apply ONLY in a new, dedicated Supabase project.
-- The local-first MVP uses SQLite, not this schema.
-- Compatible with Supabase Auth / current RLS best practices.
create table if not exists public.reclaim_wallets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  chain text not null check (chain in ('ethereum','base','arbitrum','polygon')),
  address text not null check (address ~ '^0x[0-9a-fA-F]{40}$'),
  label text not null default '',
  source text not null default 'manual',
  created_at timestamptz not null default now(),
  unique(owner_id, chain, address)
);
create index if not exists reclaim_wallets_owner_idx on public.reclaim_wallets(owner_id);
create table if not exists public.reclaim_observations (
  id uuid primary key default gen_random_uuid(),
  wallet_id uuid not null references public.reclaim_wallets(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  scanned_at timestamptz not null default now(),
  native_balance numeric(78,18) not null check (native_balance >= 0),
  usdc_balance numeric(78,6) not null check (usdc_balance >= 0),
  estimated_usd numeric(78,2),
  price_status text not null check (price_status in ('spot_estimate','unavailable')),
  last_activity timestamptz
);
create index if not exists reclaim_observations_owner_idx on public.reclaim_observations(owner_id,scanned_at desc);
create index if not exists reclaim_observations_wallet_idx on public.reclaim_observations(wallet_id,scanned_at desc);
alter table public.reclaim_wallets enable row level security;
alter table public.reclaim_observations enable row level security;
revoke all on public.reclaim_wallets from anon, authenticated;
revoke all on public.reclaim_observations from anon, authenticated;
grant select, insert, update, delete on public.reclaim_wallets to authenticated;
grant select on public.reclaim_observations to authenticated;
create policy "owner reads own wallets" on public.reclaim_wallets for select to authenticated
  using ((select auth.uid()) = owner_id);
create policy "owner inserts own wallets" on public.reclaim_wallets for insert to authenticated
  with check ((select auth.uid()) = owner_id);
create policy "owner updates own wallets" on public.reclaim_wallets for update to authenticated
  using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy "owner deletes own wallets" on public.reclaim_wallets for delete to authenticated
  using ((select auth.uid()) = owner_id);
create policy "owner reads own observations" on public.reclaim_observations for select to authenticated
  using ((select auth.uid()) = owner_id and exists (
    select 1 from public.reclaim_wallets w where w.id=wallet_id and w.owner_id=(select auth.uid())
  ));
-- Writes to observations must go through a separately authenticated backend worker.
-- Never expose a service key to the browser.

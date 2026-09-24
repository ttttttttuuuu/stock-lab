-- Supabase schema for the US weekly-options paper trading system.
-- Run this in the Supabase SQL editor once, then set SUPABASE_URL and
-- SUPABASE_SERVICE_KEY in .env to enable sync.

create table if not exists backtest_runs (
  id bigint generated always as identity primary key,
  run_at timestamptz not null,
  symbol text not null,
  strategy text not null,
  metrics jsonb not null
);

create table if not exists trades (
  id bigint generated always as identity primary key,
  run_id bigint,
  source text not null default 'backtest',   -- backtest | paper | live
  symbol text not null,
  strategy text not null,
  kind text not null,                        -- call | put
  strike double precision,
  entry_date date,
  entry_underlying double precision,
  entry_price double precision,
  qty double precision,
  iv_entry double precision,
  exit_date date,
  exit_underlying double precision,
  exit_price double precision,
  exit_reason text,
  pnl double precision,
  pnl_pct double precision,
  hold_days integer
);

create table if not exists signals (
  id bigint generated always as identity primary key,
  created_at timestamptz not null,
  symbol text not null,
  strategy text not null,
  signal integer not null,                   -- +1 call / -1 put / 0 flat
  close double precision,
  details jsonb
);

create table if not exists prices (
  symbol text not null,
  date date not null,
  open double precision,
  high double precision,
  low double precision,
  close double precision,
  volume double precision,
  primary key (symbol, date)
);

create table if not exists paper_positions (
  symbol text primary key,
  data jsonb not null
);

create table if not exists equity_snapshots (
  date date primary key,
  realized double precision,
  unrealized double precision,
  total double precision,
  positions_count integer,
  marked_at timestamptz
);

create table if not exists strategy_alerts (
  id bigint generated always as identity primary key,
  created_at timestamptz not null,
  strategy text not null,
  level text not null,                       -- insufficient | ok | watch | critical
  reasons jsonb,
  n integer,                                 -- closed paper trades at evaluation
  win_rate double precision,
  avg_pnl double precision
);

-- helpful indexes
create index if not exists idx_trades_symbol on trades (symbol);
create index if not exists idx_trades_strategy on trades (strategy);
create index if not exists idx_trades_entry on trades (entry_date desc);
create index if not exists idx_signals_symbol on signals (symbol, created_at desc);

-- read access for the anon key (adjust to your security needs)
alter table backtest_runs enable row level security;
alter table trades enable row level security;
alter table signals enable row level security;
alter table prices enable row level security;
alter table paper_positions enable row level security;
alter table equity_snapshots enable row level security;
alter table strategy_alerts enable row level security;

create policy "public read backtest_runs" on backtest_runs for select using (true);
create policy "public read trades" on trades for select using (true);
create policy "public read signals" on signals for select using (true);
create policy "public read prices" on prices for select using (true);
create policy "public read paper_positions" on paper_positions for select using (true);
create policy "public read equity_snapshots" on equity_snapshots for select using (true);
create policy "public read strategy_alerts" on strategy_alerts for select using (true);

-- write access for the anon key so the local engine can sync without a
-- service_role key. NOTE: anyone with the public anon key could write or
-- delete these tables. Acceptable for a personal project; for anything
-- shared, remove these and use a service_role key in .env instead.
create policy "anon insert backtest_runs" on backtest_runs for insert with check (true);
create policy "anon delete backtest_runs" on backtest_runs for delete using (true);
create policy "anon insert trades" on trades for insert with check (true);
create policy "anon delete trades" on trades for delete using (true);
create policy "anon insert signals" on signals for insert with check (true);
create policy "anon delete signals" on signals for delete using (true);
create policy "anon insert prices" on prices for insert with check (true);
create policy "anon delete prices" on prices for delete using (true);
create policy "anon insert paper_positions" on paper_positions for insert with check (true);
create policy "anon delete paper_positions" on paper_positions for delete using (true);
create policy "anon insert equity_snapshots" on equity_snapshots for insert with check (true);
create policy "anon delete equity_snapshots" on equity_snapshots for delete using (true);
create policy "anon insert strategy_alerts" on strategy_alerts for insert with check (true);
create policy "anon delete strategy_alerts" on strategy_alerts for delete using (true);

-- ============================================================
-- Stock Lab: strategy x symbol stock-price backtest (added 2026-09-19)
-- Run this section in the Supabase SQL editor to enable cloud sync
-- and the /lab pages. Until applied, the frontend falls back to
-- local exported JSON automatically.
-- ============================================================

create table if not exists stock_runs (
  id bigint generated always as identity primary key,
  run_at timestamptz not null,
  symbol text not null,
  strategy text not null,
  metrics jsonb not null
);

create table if not exists stock_trades (
  id bigint generated always as identity primary key,
  run_id bigint,
  symbol text not null,
  strategy text not null,
  side text not null,                        -- long | short
  entry_date date,
  entry_price double precision,
  shares double precision,
  exit_date date,
  exit_price double precision,
  exit_reason text,
  pnl double precision,
  pnl_pct double precision,
  hold_days integer
);

create index if not exists idx_stock_trades_pair on stock_trades (strategy, symbol);
create index if not exists idx_stock_runs_runat on stock_runs (run_at desc);

alter table stock_runs enable row level security;
alter table stock_trades enable row level security;

create policy "public read stock_runs" on stock_runs for select using (true);
create policy "public read stock_trades" on stock_trades for select using (true);
create policy "anon insert stock_runs" on stock_runs for insert with check (true);
create policy "anon delete stock_runs" on stock_runs for delete using (true);
create policy "anon insert stock_trades" on stock_trades for insert with check (true);
create policy "anon delete stock_trades" on stock_trades for delete using (true);

-- ============================================================
-- Stock Paper: live verification book for top stock-lab pairs
-- (added 2026-09-21). Run in the Supabase SQL editor.
-- ============================================================

create table if not exists stock_paper_trades (
  id bigint generated always as identity primary key,
  symbol text not null,
  strategy text not null,
  side text not null,                        -- long | short
  entry_date date,
  entry_price double precision,
  shares double precision,
  exit_date date,
  exit_price double precision,
  exit_reason text,
  pnl double precision,
  pnl_pct double precision,
  hold_days integer
);

create table if not exists stock_paper_positions (
  key text primary key,                      -- "symbol|strategy"
  data jsonb not null
);

create index if not exists idx_stock_paper_trades_pair on stock_paper_trades (strategy, symbol);

alter table stock_paper_trades enable row level security;
alter table stock_paper_positions enable row level security;

create policy "public read stock_paper_trades" on stock_paper_trades for select using (true);
create policy "public read stock_paper_positions" on stock_paper_positions for select using (true);
create policy "anon insert stock_paper_trades" on stock_paper_trades for insert with check (true);
create policy "anon delete stock_paper_trades" on stock_paper_trades for delete using (true);
create policy "anon insert stock_paper_positions" on stock_paper_positions for insert with check (true);
create policy "anon delete stock_paper_positions" on stock_paper_positions for delete using (true);

-- ============================================================
-- Param Opt: strategy parameter grid-search results
-- (added 2026-09-21). Run in the Supabase SQL editor.
-- ============================================================

create table if not exists param_runs (
  id bigint generated always as identity primary key,
  run_at timestamptz not null,
  symbol text not null,
  strategy text not null,
  params jsonb not null,                   -- the param combo
  is_default integer not null default 0,   -- 1 = production default baseline
  metrics jsonb not null
);

create index if not exists idx_param_runs_runat on param_runs (run_at desc);
create index if not exists idx_param_runs_pair on param_runs (strategy, symbol);

alter table param_runs enable row level security;

create policy "public read param_runs" on param_runs for select using (true);
create policy "anon insert param_runs" on param_runs for insert with check (true);
create policy "anon delete param_runs" on param_runs for delete using (true);

-- ============================================================
-- Exit Opt: take-profit / stop-loss grid-search results
-- (added 2026-09-21). Run in the Supabase SQL editor.
-- ============================================================

create table if not exists exit_runs (
  id bigint generated always as identity primary key,
  run_at timestamptz not null,
  symbol text not null,
  strategy text not null,
  take_profit double precision not null,
  stop_loss double precision not null,
  max_hold_days integer not null,
  is_default integer not null default 0,
  metrics jsonb not null
);

create index if not exists idx_exit_runs_runat on exit_runs (run_at desc);
create index if not exists idx_exit_runs_pair on exit_runs (strategy, symbol);

alter table exit_runs enable row level security;

create policy "public read exit_runs" on exit_runs for select using (true);
create policy "anon insert exit_runs" on exit_runs for insert with check (true);
create policy "anon delete exit_runs" on exit_runs for delete using (true);

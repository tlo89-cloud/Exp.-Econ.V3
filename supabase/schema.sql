-- Supabase schema for Signals + Outreach (minimal v1)
-- Run in Supabase SQL Editor.

create table if not exists public.signals (
  id text primary key,
  link text not null unique,
  title text not null,
  summary text,
  source text,
  layer int,
  access text,
  score int,
  moments jsonb,
  published_text text,
  ingested_at timestamptz not null default now()
);

create table if not exists public.signal_triage (
  user_id uuid not null references auth.users (id) on delete cascade,
  signal_id text not null references public.signals (id) on delete cascade,
  relevance boolean,
  tags text[] not null default '{}'::text[],
  note text,
  updated_at timestamptz not null default now(),
  primary key (user_id, signal_id)
);

create table if not exists public.outreach_targets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  signal_id text references public.signals (id) on delete set null,
  target_type text not null check (target_type in ('company','fund','person')),
  name text not null,
  role text,
  firm text,
  status text not null default 'to_contact' check (status in ('to_contact','contacted','in_progress','passed')),
  next_step text,
  last_contacted_at date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);


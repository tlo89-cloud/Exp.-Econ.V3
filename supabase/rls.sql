-- Supabase RLS policies for Signals + Outreach (minimal v1)
-- Run after schema.sql in Supabase SQL Editor.

alter table public.signals enable row level security;
alter table public.signal_triage enable row level security;
alter table public.outreach_targets enable row level security;

-- Signals are globally readable to authenticated users.
drop policy if exists "signals_read_auth" on public.signals;
create policy "signals_read_auth"
on public.signals
for select
to authenticated
using (true);

-- signal_triage: each user can read/write only their rows.
drop policy if exists "triage_read_own" on public.signal_triage;
create policy "triage_read_own"
on public.signal_triage
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "triage_write_own" on public.signal_triage;
create policy "triage_write_own"
on public.signal_triage
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "triage_update_own" on public.signal_triage;
create policy "triage_update_own"
on public.signal_triage
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

-- outreach_targets: each user can read/write only their rows.
drop policy if exists "outreach_read_own" on public.outreach_targets;
create policy "outreach_read_own"
on public.outreach_targets
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "outreach_write_own" on public.outreach_targets;
create policy "outreach_write_own"
on public.outreach_targets
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "outreach_update_own" on public.outreach_targets;
create policy "outreach_update_own"
on public.outreach_targets
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);


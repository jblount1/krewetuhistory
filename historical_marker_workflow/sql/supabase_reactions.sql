create extension if not exists pgcrypto;

create table if not exists public.submissions (
  id uuid primary key default gen_random_uuid(),
  airtable_id text unique not null,
  story_slug text unique,
  headline text,
  "Response QR" text,
  "Response Link" text,
  "Avg Rating" numeric,
  "Number of Responses" integer,
  "Clicks" integer default 0
);

alter table public.submissions
  add column if not exists "Response QR" text,
  add column if not exists "Response Link" text,
  add column if not exists "Avg Rating" numeric,
  add column if not exists "Number of Responses" integer,
  add column if not exists "Clicks" integer default 0;

create table if not exists public.responses (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid references public.submissions(id) on delete cascade,
  "Response" text,
  "Show response" boolean default false,
  airtable_id text unique
);

alter table public.responses
  add column if not exists "Show response" boolean default false;

create index if not exists submissions_story_slug_idx
  on public.submissions (story_slug);

create index if not exists responses_submission_id_idx
  on public.responses (submission_id);

create or replace function public.increment_clicks(story_id uuid)
returns void
language sql
security definer
set search_path = public
as $$
  update public.submissions
  set "Clicks" = coalesce("Clicks", 0) + 1
  where id = story_id;
$$;

create or replace function public.get_submission_id_by_slug(lookup_story_slug text)
returns uuid
language sql
security definer
set search_path = public
as $$
  select id
  from public.submissions
  where story_slug = lookup_story_slug
  limit 1;
$$;

alter table public.submissions enable row level security;
alter table public.responses enable row level security;

grant select on public.responses to anon, authenticated;
grant execute on function public.increment_clicks(uuid) to anon, authenticated;
grant execute on function public.get_submission_id_by_slug(text) to anon, authenticated;

drop policy if exists responses_read_public on public.responses;
create policy responses_read_public
  on public.responses
  for select
  to anon, authenticated
  using ("Show response" is true);

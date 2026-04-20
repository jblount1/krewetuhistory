create table if not exists public.stories_public (
  story_slug text primary key,
  headline text not null,
  workflow_status text not null,
  date_received timestamptz null,
  payload jsonb not null,
  synced_at timestamptz not null default timezone('utc', now())
);

create index if not exists stories_public_workflow_status_idx
  on public.stories_public (workflow_status);

create index if not exists stories_public_date_received_idx
  on public.stories_public (date_received desc);

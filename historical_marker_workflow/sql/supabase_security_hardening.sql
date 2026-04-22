alter table if exists public.stories_public enable row level security;
alter table if exists public.submissions enable row level security;
alter table if exists public.responses enable row level security;

revoke all on public.submissions from anon, authenticated;
revoke all on public.responses from anon, authenticated;
revoke all on public.stories_public from anon, authenticated;

grant select on public.stories_public to anon, authenticated;
grant select on public.responses to anon, authenticated;
grant execute on function public.increment_clicks(uuid) to anon, authenticated;

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

grant execute on function public.get_submission_id_by_slug(text) to anon, authenticated;

drop policy if exists stories_public_read_approved on public.stories_public;
create policy stories_public_read_approved
  on public.stories_public
  for select
  to anon, authenticated
  using (lower(coalesce(workflow_status, '')) in ('approved', 'approved and published'));

drop policy if exists responses_read_public on public.responses;
create policy responses_read_public
  on public.responses
  for select
  to anon, authenticated
  using ("Show response" is true);

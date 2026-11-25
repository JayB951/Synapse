-- WORLD SHARDS – anonymous article feedback
-- Run once in Supabase SQL Editor.

create table if not exists public.shard_article_feedback (
    id uuid primary key default gen_random_uuid(),
    edition_item_id uuid not null references public.shard_edition_items(id) on delete cascade,
    voter_token uuid not null,
    vote smallint not null check (vote in (-1, 1)),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint shard_article_feedback_one_vote_per_reader
        unique (edition_item_id, voter_token)
);

create index if not exists shard_article_feedback_item_idx
    on public.shard_article_feedback (edition_item_id);

alter table public.shard_article_feedback enable row level security;

revoke all on public.shard_article_feedback from anon, authenticated;
grant select, insert, update, delete on public.shard_article_feedback to anon;

drop policy if exists "Anonymous readers can read feedback" on public.shard_article_feedback;
create policy "Anonymous readers can read feedback"
    on public.shard_article_feedback for select to anon
    using (voter_token::text = coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', ''));

drop policy if exists "Anonymous readers can add feedback" on public.shard_article_feedback;
create policy "Anonymous readers can add feedback"
    on public.shard_article_feedback for insert to anon
    with check (voter_token::text = coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', ''));

drop policy if exists "Anonymous readers can update feedback" on public.shard_article_feedback;
create policy "Anonymous readers can update feedback"
    on public.shard_article_feedback for update to anon
    using (voter_token::text = coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', ''))
    with check (voter_token::text = coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', ''));

drop policy if exists "Anonymous readers can remove feedback" on public.shard_article_feedback;
create policy "Anonymous readers can remove feedback"
    on public.shard_article_feedback for delete to anon
    using (voter_token::text = coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', ''));

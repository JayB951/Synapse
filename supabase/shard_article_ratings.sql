-- WORLD SHARDS – 1–5 csillagos cikkértékelések
-- Futtasd a Supabase SQL Editorban. A régi shard_article_feedback táblát nem módosítja.

create table if not exists public.shard_article_ratings (
    id uuid primary key default gen_random_uuid(),
    edition_item_id uuid not null references public.shard_edition_items(id) on delete cascade,
    voter_token uuid not null,
    rating smallint not null check (rating between 1 and 5),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint shard_article_ratings_one_per_reader
        unique (edition_item_id, voter_token)
);

create index if not exists shard_article_ratings_item_idx
    on public.shard_article_ratings (edition_item_id);

alter table public.shard_article_ratings enable row level security;

revoke all on public.shard_article_ratings from anon, authenticated;
grant select, insert, update, delete on public.shard_article_ratings to anon;

drop policy if exists "Readers can read their own article ratings" on public.shard_article_ratings;
create policy "Readers can read their own article ratings"
    on public.shard_article_ratings for select to anon
    using (
        voter_token::text =
        coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', '')
    );

drop policy if exists "Readers can add their own article ratings" on public.shard_article_ratings;
create policy "Readers can add their own article ratings"
    on public.shard_article_ratings for insert to anon
    with check (
        voter_token::text =
        coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', '')
    );

drop policy if exists "Readers can update their own article ratings" on public.shard_article_ratings;
create policy "Readers can update their own article ratings"
    on public.shard_article_ratings for update to anon
    using (
        voter_token::text =
        coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', '')
    )
    with check (
        voter_token::text =
        coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', '')
    );

drop policy if exists "Readers can remove their own article ratings" on public.shard_article_ratings;
create policy "Readers can remove their own article ratings"
    on public.shard_article_ratings for delete to anon
    using (
        voter_token::text =
        coalesce(current_setting('request.headers', true)::json ->> 'x-reader-token', '')
    );

-- Publikus összesítés: csak az átlagot és a darabszámot adja vissza,
-- az egyéni olvasói azonosítókat nem teszi lekérdezhetővé.
create or replace function public.get_article_rating_summaries(p_item_ids uuid[])
returns table (
    edition_item_id uuid,
    average_rating numeric,
    rating_count bigint
)
language sql
stable
security definer
set search_path = public
as $$
    select
        r.edition_item_id,
        round(avg(r.rating)::numeric, 2) as average_rating,
        count(*)::bigint as rating_count
    from public.shard_article_ratings r
    where r.edition_item_id = any(p_item_ids)
    group by r.edition_item_id;
$$;

revoke all on function public.get_article_rating_summaries(uuid[]) from public, authenticated;
grant execute on function public.get_article_rating_summaries(uuid[]) to anon;

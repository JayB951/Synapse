-- WORLD SHARDS 26 – frontend image repair
-- Run once in Supabase SQL Editor. Safe to re-run.

ALTER TABLE public.shard_content_items
  ADD COLUMN IF NOT EXISTS image_url TEXT;

ALTER TABLE public.shard_content_items
  ADD COLUMN IF NOT EXISTS gallery_images JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Restore image URLs already stored in collector metadata for existing rows.
UPDATE public.shard_content_items
SET image_url = NULLIF(metadata ->> 'image_url', '')
WHERE section_code IN ('art_of_the_day', 'battlefield', 'world_explorer')
  AND image_url IS NULL
  AND metadata IS NOT NULL
  AND NULLIF(metadata ->> 'image_url', '') IS NOT NULL;

-- Restore World Explorer galleries if an earlier collector stored them in metadata.
UPDATE public.shard_content_items
SET gallery_images = (metadata -> 'gallery_images')
WHERE section_code = 'world_explorer'
  AND (gallery_images IS NULL OR gallery_images = '[]'::jsonb)
  AND jsonb_typeof(metadata -> 'gallery_images') = 'array';

-- The public edition reader needs these source fields and image fields.
GRANT SELECT (
  id,
  title,
  summary,
  body,
  source_name,
  source_url,
  source_published_at,
  image_url,
  gallery_images
)
ON public.shard_content_items TO anon;

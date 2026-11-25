-- WORLD SHARDS – World Explorer három kiegészítő cikkképe
-- Futtasd le egyszer a Supabase SQL Editorban.

ALTER TABLE public.shard_content_items
ADD COLUMN IF NOT EXISTS gallery_images JSONB NOT NULL DEFAULT '[]'::jsonb;

GRANT SELECT (id, source_name, source_url, source_published_at, image_url, gallery_images)
ON public.shard_content_items TO anon;

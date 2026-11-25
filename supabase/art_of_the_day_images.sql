-- WORLD SHARDS – Art of the Day képek
-- Futtasd le egyszer a Supabase SQL Editorban.

ALTER TABLE public.shard_content_items
ADD COLUMN IF NOT EXISTS image_url TEXT;

-- A már összegyűjtött műalkotások képURL-jének visszatöltése
UPDATE public.shard_content_items
SET image_url = metadata ->> 'image_url'
WHERE section_code = 'art_of_the_day'
  AND image_url IS NULL
  AND metadata ? 'image_url'
  AND NULLIF(metadata ->> 'image_url', '') IS NOT NULL;

-- A nyilvános frontend csak a publikált tartalom képcímét olvashatja.
GRANT SELECT (id, source_name, source_url, source_published_at, image_url)
ON public.shard_content_items TO anon;

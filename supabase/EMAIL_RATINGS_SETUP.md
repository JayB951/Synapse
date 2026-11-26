# WORLD SHARDS – csillagos értékelés telepítése

A webes felület már az új `shard_article_ratings` táblát használja. Az e-mailes értékeléshez az Edge Function és a két titok beállítása is szükséges. A régi `shard_article_feedback` tábla változatlan marad.

## 1. Adatbázis

1. Nyisd meg a Supabase projekt SQL Editorát.
2. Másold be és futtasd a `supabase/shard_article_ratings.sql` teljes tartalmát.
3. Ellenőrizd, hogy létrejött a `shard_article_ratings` tábla és a `get_article_rating_summaries(uuid[])` függvény.

## 2. Edge Function

A Supabase projektben hozz létre egy `email-rating` nevű Edge Functiont, és a teljes `supabase/functions/email-rating/index.ts` tartalmat használd.

A függvény nyilvános GET kérést fogad, de az csak a megerősítő oldalt jeleníti meg. Az adatbázisba kizárólag a külön POST megerősítés ír.

A függvény JWT-ellenőrzését ki kell kapcsolni, mert az e-mailből érkező olvasó nem rendelkezik Supabase bejelentkezési tokennel. A repó `supabase/config.toml` fájlja CLI-s telepítésnél ezt már beállítja (`verify_jwt = false`).

A Supabase Edge Function környezetében legyen elérhető:
- `SUPABASE_URL` (Supabase által biztosított)
- `SUPABASE_SERVICE_ROLE_KEY` (Supabase által biztosított, titkos marad)
- `EMAIL_RATING_SECRET` (általad beállított, legalább 32 karakteres titok)

## 3. GitHub Actions titkok

A GitHub repóban: Settings → Secrets and variables → Actions → New repository secret.

Hozd létre:
- `EMAIL_RATING_SECRET`: ugyanaz a titok, mint amit a Supabase Edge Function titkai közé felvettél.
- `EMAIL_RATING_VOTER_TOKEN`: egy általad generált UUID, például PowerShellben: `[guid]::NewGuid().ToString()`. Ezt egyszer kell létrehozni, és később változatlanul kell hagyni.

A meglévő `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD` és `WORLD_SHARDS_NOTIFY_EMAIL` titkok továbbra is szükségesek.

**A titkokat ne küldd el chatben, és ne tedd be a GitHub-kódba.**

## 4. Működés ellenőrzése

- A GitHub Actions `WORLD SHARDS – Rating Tests` workflow automatikusan ellenőrzi a Python e-mailteszteket és a frontend JavaScript szintaxisát.
- A következő tényleges e-mailküldés előtt ellenőrizd, hogy az SQL és az Edge Function telepítése kész, és a két új GitHub Actions secret is be van állítva.
- Az e-mailben egy csillagra kattintás csak a megerősítő oldalt nyitja meg. A mentéshez külön rá kell kattintani az „Értékelés véglegesítése” gombra.
- A megerősítés után a „Vissza a WORLD SHARDS magazinhoz” link átviszi az e-mailes olvasói azonosítót a böngészőbe, így a webes és e-mailes értékelések ugyanahhoz az olvasóhoz tartoznak.

Az új rendszer élesítése előtt ne indítsd el az e-mailküldő workflow-t, amíg az adatbázis és az Edge Function telepítése nincs kész.

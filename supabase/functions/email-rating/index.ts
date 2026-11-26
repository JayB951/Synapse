import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function response(body: string, status = 200, contentType = "text/html; charset=utf-8") {
  return new Response(body, {
    status,
    headers: { ...corsHeaders, "Content-Type": contentType, "Cache-Control": "no-store" },
  });
}

function validUuid(value: string | null): value is string {
  return Boolean(value && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value));
}

function safeInteger(value: string | null): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

async function verifySignature(message: string, signature: string, secret: string): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const bytes = Uint8Array.from(atob(signature.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
    return await crypto.subtle.verify("HMAC", key, bytes, new TextEncoder().encode(message));
  } catch {
    return false;
  }
}

function confirmationPage(itemId: string, rating: number, voterToken: string, expires: number, signature: string) {
  const payload = JSON.stringify({ item_id: itemId, rating, voter_token: voterToken, exp: expires, sig: signature });
  return `<!doctype html>
<html lang="hu"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WORLD SHARDS – értékelés megerősítése</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#090d14;color:#edf2f7;font:16px/1.6 Arial,sans-serif}
main{width:min(520px,calc(100% - 40px));padding:36px;background:#101722;border:1px solid #55482f;text-align:center}
.brand{font:12px Arial,sans-serif;letter-spacing:4px;color:#c5a66b}
h1{font:28px Georgia,serif;font-weight:400;margin:24px 0 8px}
.stars{font-size:38px;letter-spacing:5px;color:#c5a66b;margin:22px 0}
p{color:#aab6c4}
button{margin-top:16px;padding:13px 22px;background:#c5a66b;color:#101722;border:0;font-weight:bold;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}
#status{min-height:28px;margin-top:18px}
</style></head><body><main>
<div class="brand">WORLD SHARDS</div>
<h1>Értékelés megerősítése</h1>
<div class="stars" aria-label="${rating} az 5 csillagból">${"★".repeat(rating)}${"☆".repeat(5-rating)}</div>
<p>A cikket ${rating}/5 csillagra értékeled. Az értékelés csak a megerősítő gomb megnyomásakor kerül mentésre.</p>
<button id="confirm">Értékelés véglegesítése</button>
<div id="status" role="status"></div>
</main><script>
const payload = ${payload};
const button = document.getElementById("confirm");
const status = document.getElementById("status");
button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Mentés folyamatban…";
  try {
    const result = await fetch(location.pathname + location.search, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await result.json();
    if (!result.ok) throw new Error(data.error || "A mentés nem sikerült.");
    status.textContent = "Köszönjük! Az értékelésedet elmentettük.";
    button.hidden = true;
  } catch (error) {
    status.textContent = error.message || "Hiba történt.";
    button.disabled = false;
  }
});
</script></body></html>`;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  const url = new URL(req.url);
  const itemId = url.searchParams.get("item_id");
  const rating = safeInteger(url.searchParams.get("rating"));
  const voterToken = url.searchParams.get("voter_token");
  const expires = safeInteger(url.searchParams.get("exp"));
  const signature = url.searchParams.get("sig");

  if (!validUuid(itemId) || !validUuid(voterToken) || rating === null || rating < 1 || rating > 5 ||
      expires === null || !signature || signature.length > 128) {
    return response("Érvénytelen vagy hiányos értékelési hivatkozás.", 400);
  }

  const secret = Deno.env.get("EMAIL_RATING_SECRET") || "";
  if (secret.length < 32) return response("Az értékelési szolgáltatás nincs megfelelően konfigurálva.", 503);

  const signedMessage = `${itemId}|${rating}|${voterToken}|${expires}`;
  if (!(await verifySignature(signedMessage, signature, secret))) {
    return response("Az értékelési hivatkozás érvénytelen.", 403);
  }
  const now = Math.floor(Date.now() / 1000);
  if (expires < now || expires > now + 31 * 24 * 60 * 60) {
    return response("Az értékelési hivatkozás lejárt vagy érvénytelen időtartamú.", 410);
  }

  if (req.method === "GET") {
    return response(confirmationPage(itemId, rating, voterToken, expires, signature));
  }

  if (req.method !== "POST") return response("Nem támogatott metódus.", 405);

  let submitted: Record<string, unknown>;
  try {
    submitted = await req.json();
  } catch {
    return response(JSON.stringify({ error: "Hibás kérés." }), 400, "application/json");
  }
  if (submitted.item_id !== itemId || submitted.rating !== rating ||
      submitted.voter_token !== voterToken || submitted.exp !== expires || submitted.sig !== signature) {
    return response(JSON.stringify({ error: "A megerősítés adatai nem egyeznek." }), 400, "application/json");
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) {
    return response(JSON.stringify({ error: "Az adatbázis-kapcsolat nincs konfigurálva." }), 503, "application/json");
  }

  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { error } = await supabase.from("shard_article_ratings").upsert(
    { edition_item_id: itemId, voter_token: voterToken, rating, updated_at: new Date().toISOString() },
    { onConflict: "edition_item_id,voter_token" },
  );

  if (error) {
    console.error("Email rating save failed:", error.message);
    return response(JSON.stringify({ error: "Az értékelés mentése nem sikerült." }), 500, "application/json");
  }

  return response(JSON.stringify({ ok: true }), 200, "application/json");
});

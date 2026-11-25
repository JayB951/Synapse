const sections = [
  ["01","research_frontier","RESEARCH FRONTIER","A tudomány legfrissebb felismerései"],
  ["02","art_of_the_day","ART OF THE DAY","Egy alkotás, amely megérdemli a figyelmet"],
  ["03","the_thinker","THE THINKER","Eszmék és gondolatok a világról"],
  ["04","battlefield","BATTLEFIELD","Konfliktusok, stratégiák, történelem"],
  ["05","fundamentals","FUNDAMENTALS","A világ működésének alapjai"],
  ["06","world_explorer","WORLD EXPLORER","Helyek és jelenségek a bolygónkról"],
  ["07","unsolved","UNSOLVED","Nyitott kérdések és megfejtetlen rejtélyek"],
  ["08","music_of_the_day","MUSIC OF THE DAY","A nap témájához kapcsolódó zenei felfedezés"],
  ["09","closing","CLOSING","Egy könnyedebb lezárás: képregény és humor"]
];

const grid = document.querySelector("#section-grid");
const statusTitle = document.querySelector("#edition-status-title");
const statusText = document.querySelector("#edition-status-text");
const statusCode = document.querySelector("#edition-status-code");
const dateNode = document.querySelector("#edition-date");
const headerDate = document.querySelector("#header-date");
const yearNode = document.querySelector("#year");
const countNode = document.querySelector("#edition-count");

function renderSections(items = []) {
  if (!grid) return;
  const counts = Object.fromEntries(sections.map(([, code]) => [code, 0]));
  items.forEach(item => {
    if (Object.hasOwn(counts, item.section_code)) counts[item.section_code]++;
  });
  grid.innerHTML = sections.map(([number, code, title, description]) => {
    const count = counts[code];
    return `
      <article class="section-card">
        <span class="card-number">${number} / ${String(count).padStart(2, "0")}</span>
        <span class="card-arrow" aria-hidden="true">↗</span>
        <h3>${title}</h3>
        <p>${description}</p>
      </article>
    `;
  }).join("");
}

function showStatus(title, message, code = "SUPABASE · READ ONLY") {
  if (statusTitle) statusTitle.textContent = title;
  if (statusText) statusText.textContent = message;
  if (statusCode) statusCode.textContent = code;
}

function formatEditionDate(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("hu-HU", {
    year: "numeric", month: "long", day: "numeric",
    timeZone: "Europe/Budapest"
  }).format(new Date(value + "T12:00:00"));
}

async function loadPublishedEdition() {
  const config = window.WORLD_SHARDS_CONFIG || {};
  const supabaseUrl = (config.supabaseUrl || "").replace(/\/$/, "");
  const anonKey = config.supabaseAnonKey || "";

  if (!supabaseUrl || !anonKey || supabaseUrl.includes("IDE_") || anonKey.includes("IDE_")) {
    showStatus(
      "A Supabase-kapcsolat konfigurálásra vár",
      "A frontend elkészült az olvasási kapcsolattal. A Supabase projekt URL-jét és nyilvános anon kulcsát még be kell állítani.",
      "F1 · CONFIG REQUIRED"
    );
    renderSections();
    return;
  }

  const headers = {
    apikey: anonKey,
    Authorization: `Bearer ${anonKey}`,
    Accept: "application/json"
  };

  try {
    showStatus("Kapcsolódás a napi kiadáshoz", "A publikált kiadás ellenőrzése folyamatban…");
    const editionsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_editions?select=id,edition_date,title,introduction,status&status=eq.published&order=edition_date.desc&limit=1`,
      { headers }
    );
    if (!editionsResponse.ok) throw new Error(`Kiadáslekérdezés: HTTP ${editionsResponse.status}`);
    const editions = await editionsResponse.json();

    if (!editions.length) {
      showStatus(
        "Jelenleg nincs publikált napi kiadás",
        "A rendszer kapcsolata él. Amint egy kiadás published státuszt kap, itt automatikusan megjelenik. A piszkozatok nem nyilvánosak.",
        "SUPABASE · CONNECTED"
      );
      renderSections();
      if (countNode) countNode.textContent = "— TARTALOM · 9 ROVAT";
      return;
    }

    const edition = editions[0];
    const itemsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_edition_items?select=id,section_code,position,display_title,display_summary,display_body,processing_status&edition_id=eq.${encodeURIComponent(edition.id)}&processing_status=eq.completed&order=position.asc`,
      { headers }
    );
    if (!itemsResponse.ok) throw new Error(`Tartalomlekérdezés: HTTP ${itemsResponse.status}`);
    const items = await itemsResponse.json();

    const formatted = formatEditionDate(edition.edition_date);
    if (dateNode) dateNode.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (headerDate) headerDate.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (countNode) countNode.textContent = `${items.length} TARTALOM · 9 ROVAT`;
    showStatus(
      edition.title || "A napi kiadás elérhető",
      edition.introduction || "A mai kiadás betöltődött.",
      `PUBLISHED · ${items.length} ITEMS`
    );
    renderSections(items);
  } catch (error) {
    console.error("WORLD SHARDS Supabase error:", error);
    showStatus(
      "A napi kiadás most nem tölthető be",
      "A Supabase-kapcsolat vagy az anon olvasási jogosultság ellenőrzést igényel. A piszkozatok ettől függetlenül nem kerülnek nyilvánosságra.",
      "SUPABASE · CONNECTION ERROR"
    );
    renderSections();
  }
}

const now = new Date();
if (yearNode) yearNode.textContent = now.getFullYear();
loadPublishedEdition();

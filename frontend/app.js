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
const feed = document.querySelector("#article-feed");
const statusTitle = document.querySelector("#edition-status-title");
const statusText = document.querySelector("#edition-status-text");
const statusCode = document.querySelector("#edition-status-code");
const dateNode = document.querySelector("#edition-date");
const headerDate = document.querySelector("#header-date");
const yearNode = document.querySelector("#year");
const countNode = document.querySelector("#edition-count");
const reader = document.querySelector("#article-reader");
const readerTitle = document.querySelector("#reader-title");
const readerSummary = document.querySelector("#reader-summary");
const readerBody = document.querySelector("#reader-body");
const readerSection = document.querySelector("#reader-section");

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

function makeElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function renderSections(items = []) {
  if (!grid) return;
  const counts = Object.fromEntries(sections.map(([, code]) => [code, 0]));
  items.forEach(item => {
    if (Object.hasOwn(counts, item.section_code)) counts[item.section_code]++;
  });
  grid.replaceChildren();
  sections.forEach(([number, code, title, description]) => {
    const card = makeElement("article", "section-card");
    card.append(
      makeElement("span", "card-number", number + " / " + String(counts[code]).padStart(2, "0")),
      makeElement("span", "card-arrow", "↗"),
      makeElement("h3", "", title),
      makeElement("p", "", description)
    );
    grid.append(card);
  });
}

function openArticle(item, sectionName) {
  readerTitle.textContent = item.display_title || "Cím nélkül";
  readerSummary.textContent = item.display_summary || "";
  readerBody.textContent = item.display_body || "Ehhez az elemhez nem érhető el cikk szöveg.";
  readerSection.textContent = sectionName;
  if (typeof reader.showModal === "function") reader.showModal();
  else reader.setAttribute("open", "");
}

function renderArticles(items = []) {
  if (!feed) return;
  feed.replaceChildren();

  if (!items.length) {
    feed.append(makeElement("p", "empty-feed", "A publikált kiadás tartalma itt jelenik majd meg."));
    return;
  }

  sections.forEach(([number, code, title, description]) => {
    const sectionItems = items.filter(item => item.section_code === code)
      .sort((a, b) => (a.position || 0) - (b.position || 0));
    if (!sectionItems.length) return;

    const group = makeElement("section", "article-group");
    group.id = "rovat-" + code;
    const heading = makeElement("div", "article-group-heading");
    const headingCopy = makeElement("div", "");
    headingCopy.append(makeElement("span", "eyebrow", number + " · " + title));
    headingCopy.append(makeElement("p", "group-description", description));
    heading.append(headingCopy, makeElement("span", "group-total", String(sectionItems.length).padStart(2, "0")));
    group.append(heading);

    const cards = makeElement("div", "article-cards");
    sectionItems.forEach((item, index) => {
      const card = makeElement("article", "article-card");
      const meta = makeElement("div", "article-meta");
      meta.append(
        makeElement("span", "", number + "." + String(index + 1).padStart(2, "0")),
        makeElement("span", "", code === "closing" ? "ZÁRÓTARTALOM" : "WORLD SHARDS")
      );
      const titleNode = makeElement("h3", "", item.display_title || "Cím nélkül");
      const summary = makeElement("p", "article-summary", item.display_summary || "");
      const button = makeElement("button", "read-article", "Cikk olvasása  ↗");
      button.type = "button";
      button.addEventListener("click", () => openArticle(item, title));
      card.append(meta, titleNode, summary, button);
      cards.append(card);
    });
    group.append(cards);
    feed.append(group);
  });
}

async function loadPublishedEdition() {
  const config = window.WORLD_SHARDS_CONFIG || {};
  const supabaseUrl = (config.supabaseUrl || "").replace(/\/$/, "");
  const anonKey = config.supabaseAnonKey || "";

  if (!supabaseUrl || !anonKey || supabaseUrl.includes("IDE_") || anonKey.includes("IDE_")) {
    showStatus("A Supabase-kapcsolat konfigurálásra vár", "A nyilvános adatkapcsolat beállítása hiányzik.", "F1 · CONFIG REQUIRED");
    renderSections();
    renderArticles();
    return;
  }

  const headers = { apikey: anonKey, Authorization: `Bearer ${anonKey}`, Accept: "application/json" };

  try {
    showStatus("Kapcsolódás a napi kiadáshoz", "A publikált kiadás ellenőrzése folyamatban…");
    const editionsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_editions?select=id,edition_date,title,introduction,status&status=eq.published&order=edition_date.desc&limit=1`,
      { headers }
    );
    if (!editionsResponse.ok) throw new Error(`Kiadáslekérdezés: HTTP ${editionsResponse.status}`);
    const editions = await editionsResponse.json();

    if (!editions.length) {
      showStatus("Jelenleg nincs publikált napi kiadás", "A rendszer kapcsolata él. Amint egy kiadás published státuszt kap, itt automatikusan megjelenik. A piszkozatok nem nyilvánosak.", "SUPABASE · CONNECTED");
      renderSections();
      renderArticles();
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
    showStatus(edition.title || "A napi kiadás elérhető", edition.introduction || "A mai kiadás betöltődött.", `PUBLISHED · ${items.length} ITEMS`);
    renderSections(items);
    renderArticles(items);
  } catch (error) {
    console.error("WORLD SHARDS Supabase error:", error);
    showStatus("A napi kiadás most nem tölthető be", "A Supabase-kapcsolat vagy az anon olvasási jogosultság ellenőrzést igényel. A piszkozatok ettől függetlenül nem kerülnek nyilvánosságra.", "SUPABASE · CONNECTION ERROR");
    renderSections();
    renderArticles();
  }
}

if (reader) {
  reader.querySelector(".reader-close")?.addEventListener("click", () => reader.close());
  reader.addEventListener("click", event => {
    if (event.target === reader) reader.close();
  });
}

if (yearNode) yearNode.textContent = new Date().getFullYear();
loadPublishedEdition();

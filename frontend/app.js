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
const readerImage = document.querySelector("#reader-image");
const readerBody = document.querySelector("#reader-body");
const readerSection = document.querySelector("#reader-section");
const readerSource = document.querySelector("#reader-source");
const readerFeedback = document.querySelector("#reader-feedback");
const feedbackVotes = new Map();
let feedbackHeaders = null;
let feedbackApiUrl = "";
let readerFeedbackItemId = null;
let readerFeedbackSectionName = "";

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

function getSourceRecord(item) {
  return Array.isArray(item.shard_content_items)
    ? item.shard_content_items[0]
    : item.shard_content_items;
}

function makeSectionImage(source, title, className, altPrefix) {
  const imageUrl = source?.image_url;
  if (!imageUrl) return null;

  try {
    const url = new URL(imageUrl);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;

    const image = makeElement("img", className);
    image.src = url.href;
    image.alt = title ? `${altPrefix}: ${title}` : altPrefix;
    image.loading = "lazy";
    image.decoding = "async";
    return image;
  } catch (_) {
    return null;
  }
}

function getVoterToken() {
  const storageKey = "world-shards-reader-token";
  let token = localStorage.getItem(storageKey);
  if (!token) {
    token = crypto.randomUUID();
    localStorage.setItem(storageKey, token);
  }
  return token;
}

function feedbackLabel(vote) {
  if (vote === 1) return "👍 Érdekes";
  if (vote === -1) return "👎 Nem releváns";
  return "♡ Visszajelzés";
}

function createFeedbackButton(itemId, className = "feedback-toggle") {
  const button = makeElement("button", className, feedbackLabel(feedbackVotes.get(itemId) || 0));
  button.type = "button";
  button.dataset.feedbackItem = itemId;
  button.setAttribute("aria-label", "Cikk relevanciájának értékelése");
  button.setAttribute("aria-pressed", String(Boolean(feedbackVotes.get(itemId))));
  button.title = "Kattintással válthatsz: érdekes → nem releváns → nincs értékelés";
  button.addEventListener("click", () => saveFeedback(itemId, button));
  return button;
}

async function saveFeedback(itemId, button) {
  if (!feedbackHeaders || !feedbackApiUrl) return;
  const current = feedbackVotes.get(itemId) || 0;
  const next = current === 0 ? 1 : current === 1 ? -1 : 0;
  button.disabled = true;
  try {
    const voterToken = getVoterToken();
    const endpoint = `${feedbackApiUrl}/rest/v1/shard_article_feedback`;
    if (next === 0) {
      const response = await fetch(
        `${endpoint}?edition_item_id=eq.${encodeURIComponent(itemId)}&voter_token=eq.${encodeURIComponent(voterToken)}`,
        { method: "DELETE", headers: feedbackHeaders }
      );
      if (!response.ok) throw new Error(`Feedback törlése: HTTP ${response.status}`);
      feedbackVotes.delete(itemId);
    } else {
      const response = await fetch(`${endpoint}?on_conflict=edition_item_id,voter_token`, {
        method: "POST",
        headers: { ...feedbackHeaders, "Content-Type": "application/json", Prefer: "resolution=merge-duplicates,return=minimal" },
        body: JSON.stringify({ edition_item_id: itemId, voter_token: voterToken, vote: next, updated_at: new Date().toISOString() })
      });
      if (!response.ok) throw new Error(`Feedback mentése: HTTP ${response.status}`);
      feedbackVotes.set(itemId, next);
    }
    syncFeedbackButtons(itemId);
  } catch (error) {
    console.error("WORLD SHARDS feedback error:", error);
    button.textContent = "Nem sikerült menteni";
  } finally {
    button.disabled = false;
  }
}

function syncFeedbackButtons(itemId) {
  const vote = feedbackVotes.get(itemId) || 0;
  document.querySelectorAll("[data-feedback-item]").forEach(button => {
    if (button.dataset.feedbackItem !== itemId) return;
    button.textContent = feedbackLabel(vote);
    button.setAttribute("aria-pressed", String(Boolean(vote)));
    button.classList.toggle("is-positive", vote === 1);
    button.classList.toggle("is-negative", vote === -1);
  });
}

async function loadFeedbackVotes(items, headers, supabaseUrl) {
  feedbackVotes.clear();
  feedbackHeaders = headers;
  feedbackApiUrl = supabaseUrl;
  const token = getVoterToken();
  feedbackHeaders = { ...headers, "x-reader-token": token };
  const response = await fetch(
    `${supabaseUrl}/rest/v1/shard_article_feedback?select=edition_item_id,vote&voter_token=eq.${encodeURIComponent(token)}`,
    { headers: feedbackHeaders }
  );
  if (!response.ok) throw new Error(`Feedback lekérdezés: HTTP ${response.status}`);
  const rows = await response.json();
  rows.forEach(row => feedbackVotes.set(row.edition_item_id, row.vote));
}

function renderArticleBody(container, body, galleryImages = []) {
  container.replaceChildren();
  const paragraphs = String(body || "")
    .split(/\n\s*\n/)
    .map(value => value.trim())
    .filter(Boolean);

  if (!paragraphs.length) {
    container.textContent = "Ehhez az elemhez nem érhető el cikk szöveg.";
    return;
  }

  const images = Array.isArray(galleryImages)
    ? galleryImages.filter(image => image && typeof image.url === "string").slice(0, 3)
    : [];
  const imagePositions = new Map();

  images.forEach((image, index) => {
    const position = Math.min(
      paragraphs.length - 1,
      Math.max(0, Math.floor(((index + 1) * paragraphs.length) / (images.length + 1)))
    );
    if (!imagePositions.has(position)) imagePositions.set(position, []);
    imagePositions.get(position).push(image);
  });

  paragraphs.forEach((paragraph, index) => {
    container.append(makeElement("p", "reader-paragraph", paragraph));
    const imagesHere = imagePositions.get(index) || [];
    imagesHere.forEach(imageData => {
      try {
        const url = new URL(imageData.url);
        if (url.protocol !== "https:" && url.protocol !== "http:") return;
        const figure = makeElement("figure", "reader-inline-figure");
        const image = makeElement("img", "reader-inline-image");
        image.src = url.href;
        image.alt = imageData.caption || "A bemutatott helyszín részlete";
        image.loading = "lazy";
        image.decoding = "async";
        figure.append(image);
        if (imageData.caption) {
          figure.append(makeElement("figcaption", "reader-image-caption", imageData.caption));
        }
        if (imageData.license) {
          figure.append(makeElement("span", "reader-image-license", imageData.license));
        }
        container.append(figure);
      } catch (_) {}
    });
  });
}

function openArticle(item, sectionName) {
  readerTitle.textContent = item.display_title || "Cím nélkül";
  readerSummary.textContent = item.display_summary || "";
  const source = getSourceRecord(item);
  if (readerImage) {
    readerImage.replaceChildren();
    if (item.section_code === "art_of_the_day") {
      const image = makeSectionImage(source, item.display_title, "reader-artwork-image", "A műalkotás");
      if (image) readerImage.append(image);
    } else if (item.section_code === "world_explorer") {
      const image = makeSectionImage(source, item.display_title, "reader-place-image", "A bemutatott helyszín");
      if (image) readerImage.append(image);
    } else if (item.section_code === "battlefield") {
      const image = makeSectionImage(source, item.display_title, "reader-battle-image", "A csata történelmi ábrázolása");
      if (image) readerImage.append(image);
    }
  }
  renderArticleBody(readerBody, item.display_body, item.section_code === "world_explorer" ? source?.gallery_images : []);
  readerSection.textContent = sectionName;
  readerFeedbackItemId = item.id;
  readerFeedbackSectionName = sectionName;
  if (readerFeedback) {
    readerFeedback.replaceChildren(createFeedbackButton(item.id, "feedback-toggle reader-feedback-toggle"));
  }
  if (readerSource) {
    readerSource.replaceChildren();
    if (source && (source.source_name || source.source_url || source.source_published_at)) {
      const label = makeElement("span", "source-label", "EREDETI FORRÁS");
      readerSource.append(label);
      if (source.source_name) readerSource.append(makeElement("span", "source-name", source.source_name));
      if (source.source_published_at) {
        const published = new Date(source.source_published_at);
        if (!Number.isNaN(published.getTime())) {
          readerSource.append(makeElement("span", "source-date", "Forrás dátuma: " + new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "long", day: "numeric" }).format(published)));
        }
      }
      if (source.source_url) {
        try {
          const url = new URL(source.source_url);
          if (url.protocol === "https:" || url.protocol === "http:") {
            const link = makeElement("a", "source-link", "Eredeti forrás megnyitása ↗");
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            readerSource.append(link);
          }
        } catch (_) {}
      }
    }
  }
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
      const feedback = createFeedbackButton(item.id);
      feedback.dataset.feedbackItem = item.id;
      const source = getSourceRecord(item);
      let sectionImage = null;
      if (code === "art_of_the_day") {
        sectionImage = makeSectionImage(source, item.display_title, "article-artwork-image", "A műalkotás");
      } else if (code === "world_explorer") {
        sectionImage = makeSectionImage(source, item.display_title, "article-place-image", "A bemutatott helyszín");
      } else if (code === "battlefield") {
        sectionImage = makeSectionImage(source, item.display_title, "article-battle-image", "A csata történelmi ábrázolása");
      }
      if (sectionImage) card.append(sectionImage);
      card.append(meta, titleNode, summary, feedback, button);
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
      renderArticles();
      if (countNode) countNode.textContent = "— TARTALOM · 9 ROVAT";
      return;
    }

    const edition = editions[0];
    const itemsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_edition_items?select=id,section_code,position,display_title,display_summary,display_body,processing_status,shard_content_items(source_name,source_url,source_published_at,image_url,gallery_images)&edition_id=eq.${encodeURIComponent(edition.id)}&processing_status=eq.completed&order=position.asc`,
      { headers }
    );
    if (!itemsResponse.ok) throw new Error(`Tartalomlekérdezés: HTTP ${itemsResponse.status}`);
    const items = await itemsResponse.json();

    try {
      await loadFeedbackVotes(items, headers, supabaseUrl);
    } catch (feedbackError) {
      console.warn("WORLD SHARDS feedback is temporarily unavailable:", feedbackError);
      feedbackHeaders = { ...headers, "x-reader-token": getVoterToken() };
      feedbackApiUrl = supabaseUrl;
    }

    const formatted = formatEditionDate(edition.edition_date);
    if (dateNode) dateNode.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (headerDate) headerDate.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (countNode) countNode.textContent = `${items.length} TARTALOM · 9 ROVAT`;
    showStatus(edition.title || "A napi kiadás elérhető", edition.introduction || "A mai kiadás betöltődött.", `PUBLISHED · ${items.length} ITEMS`);
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

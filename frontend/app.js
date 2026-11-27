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
const agoraFeed = document.querySelector("#agora-feed");
const sectionNav = document.querySelector("#section-nav");


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
const articleRatings = new Map();
const ratingSummaries = new Map();
let ratingHeaders = null;
let ratingApiUrl = "";
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
  const metadata = source?.metadata && typeof source.metadata === "object"
    ? source.metadata
    : {};
  const gallery = Array.isArray(source?.gallery_images) ? source.gallery_images : [];
  // Older collector records may have the image only in metadata or the
  // World Explorer gallery. Prefer the canonical column, then use those
  // persisted fallbacks so a missing image_url column value does not hide it.
  const candidates = [
    { url: source?.image_url, caption: "" },
    { url: metadata.image_url, caption: "" },
    ...gallery.map(entry => ({
      url: typeof entry === "string" ? entry : entry?.url,
      caption: typeof entry === "object" ? entry?.caption : ""
    }))
  ];

  const validCandidates = candidates.flatMap(candidate => {
    if (!candidate.url) return [];
    try {
      const url = new URL(candidate.url);
      if (url.protocol !== "https:" && url.protocol !== "http:") return [];
      return [{ url: url.href, caption: candidate.caption }];
    } catch (_) {
      return [];
    }
  });
  if (!validCandidates.length) return null;

  const image = makeElement("img", className);
  image.loading = "lazy";
  image.decoding = "async";
  let candidateIndex = 0;
  const loadNextImage = () => {
    const candidate = validCandidates[candidateIndex++];
    if (!candidate) {
      image.remove();
      return;
    }
    image.src = candidate.url;
    image.alt = candidate.caption || (title ? `${altPrefix}: ${title}` : altPrefix);
  };
  image.addEventListener("error", loadNextImage);
  loadNextImage();
  return image;
}

function getVoterToken() {
  const storageKey = "world-shards-reader-token";
  const transferMatch = location.hash.match(/^#rating-reader=([0-9a-f-]{36})$/i);
  if (transferMatch && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(transferMatch[1])) {
    localStorage.setItem(storageKey, transferMatch[1]);
    history.replaceState(null, "", location.pathname + location.search);
  }
  let token = localStorage.getItem(storageKey);
  if (!token) {
    token = crypto.randomUUID();
    localStorage.setItem(storageKey, token);
  }
  return token;
}

function createRatingWidget(itemId, className = "article-rating") {
  const widget = makeElement("div", className);
  widget.dataset.ratingItem = itemId;
  const label = makeElement("span", "rating-label", "ÉRTÉKELD A CIKKET");
  const stars = makeElement("div", "rating-stars");
  for (let score = 1; score <= 5; score++) {
    const button = makeElement("button", "rating-star", "★");
    button.type = "button";
    button.dataset.ratingScore = String(score);
    button.setAttribute("aria-label", `${score} csillag`);
    button.title = `${score}/5 csillag`;
    button.addEventListener("click", () => saveArticleRating(itemId, score, widget));
    stars.append(button);
  }
  const current = articleRatings.get(itemId) || 0;
  stars.querySelectorAll(".rating-star").forEach(button => {
    const score = Number(button.dataset.ratingScore);
    button.classList.toggle("is-selected", score <= current);
    button.setAttribute("aria-pressed", String(score === current));
  });
  const storedSummary = ratingSummaries.get(itemId);
  const summaryText = storedSummary && storedSummary.count
    ? `Átlag: ${Number(storedSummary.average).toFixed(2)} / 5 · ${storedSummary.count} értékelés`
    : "Még nincs értékelés";
  const summary = makeElement("span", "rating-summary", summaryText);
  widget.append(label, stars, summary);
  return widget;
}

function syncRatingWidget(itemId) {
  const current = articleRatings.get(itemId) || 0;
  const summary = ratingSummaries.get(itemId);
  document.querySelectorAll("[data-rating-item]").forEach(widget => {
    if (widget.dataset.ratingItem !== itemId) return;
    widget.querySelectorAll(".rating-star").forEach(button => {
      const score = Number(button.dataset.ratingScore);
      button.classList.toggle("is-selected", score <= current);
      button.setAttribute("aria-pressed", String(score === current));
    });
    const text = summary && summary.count
      ? `Átlag: ${Number(summary.average).toFixed(2)} / 5 · ${summary.count} értékelés`
      : "Még nincs értékelés";
    const summaryNode = widget.querySelector(".rating-summary");
    if (summaryNode) summaryNode.textContent = text;
  });
}

async function loadArticleRatingSummaries(itemIds) {
  if (!ratingHeaders || !ratingApiUrl || !itemIds.length) return;
  const response = await fetch(`${ratingApiUrl}/rest/v1/rpc/get_article_rating_summaries`, {
    method: "POST",
    headers: { ...ratingHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({ p_item_ids: itemIds })
  });
  if (!response.ok) throw new Error(`Értékelési összesítés: HTTP ${response.status}`);
  const rows = await response.json();
  itemIds.forEach(id => ratingSummaries.delete(id));
  rows.forEach(row => ratingSummaries.set(row.edition_item_id, {
    average: row.average_rating,
    count: Number(row.rating_count)
  }));
}

async function loadArticleRatings(items, headers, supabaseUrl) {
  articleRatings.clear();
  ratingSummaries.clear();
  ratingApiUrl = supabaseUrl;
  const token = getVoterToken();
  ratingHeaders = { ...headers, "x-reader-token": token };
  const ids = items.map(item => item.id);
  if (!ids.length) return;
  const ownResponse = await fetch(
    `${supabaseUrl}/rest/v1/shard_article_ratings?select=edition_item_id,rating&voter_token=eq.${encodeURIComponent(token)}`,
    { headers: ratingHeaders }
  );
  if (!ownResponse.ok) throw new Error(`Saját értékelések: HTTP ${ownResponse.status}`);
  const ownRows = await ownResponse.json();
  ownRows.forEach(row => articleRatings.set(row.edition_item_id, row.rating));
  await loadArticleRatingSummaries(ids);
}

async function saveArticleRating(itemId, rating, widget) {
  if (!ratingHeaders || !ratingApiUrl) return;
  widget.querySelectorAll("button").forEach(button => button.disabled = true);
  try {
    const voterToken = getVoterToken();
    const response = await fetch(
      `${ratingApiUrl}/rest/v1/shard_article_ratings?on_conflict=edition_item_id,voter_token`,
      {
        method: "POST",
        headers: {
          ...ratingHeaders,
          "Content-Type": "application/json",
          Prefer: "resolution=merge-duplicates,return=minimal"
        },
        body: JSON.stringify({
          edition_item_id: itemId,
          voter_token: voterToken,
          rating,
          updated_at: new Date().toISOString()
        })
      }
    );
    if (!response.ok) throw new Error(`Értékelés mentése: HTTP ${response.status}`);
    articleRatings.set(itemId, rating);
    await loadArticleRatingSummaries([itemId]);
    syncRatingWidget(itemId);
  } catch (error) {
    console.error("WORLD SHARDS rating error:", error);
    const summary = widget.querySelector(".rating-summary");
    if (summary) summary.textContent = "Nem sikerült menteni";
  } finally {
    widget.querySelectorAll("button").forEach(button => button.disabled = false);
  }
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
    } else if (item.section_code === "closing" && source?.source_name === "xkcd") {
      const image = makeSectionImage(source, item.display_title, "reader-xkcd-image", "xkcd képregény");
      if (image) readerImage.append(image);
    }
  }
  renderArticleBody(readerBody, item.display_body, item.section_code === "world_explorer" ? source?.gallery_images : []);
  readerSection.textContent = sectionName;
  readerFeedbackItemId = item.id;
  readerFeedbackSectionName = sectionName;
  if (readerFeedback) {
    readerFeedback.replaceChildren(createRatingWidget(item.id, "article-rating reader-rating"));
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

let sectionNavigationObserver = null;

function renderSectionNavigation() {
  if (!sectionNav) return;
  if (sectionNavigationObserver) sectionNavigationObserver.disconnect();
  sectionNav.replaceChildren();
  sectionNav.append(new Option("Válassz rovatot…", ""));

  const targets = [];
  document.querySelectorAll(".agora-column[id]").forEach(column => {
    targets.push({ id: column.id, label: column.dataset.navLabel || column.querySelector("h3")?.textContent || "AGORA" });
  });
  feed.querySelectorAll(".article-group").forEach(group => {
    const heading = group.querySelector(".article-group-heading .eyebrow");
    const label = (heading?.textContent || group.id.replace("rovat-", "")).replace(/^\d+\s*[·.]\s*/, "").trim();
    targets.push({ id: group.id, label });
    if (group.id === "rovat-closing") {
      group.querySelectorAll(".article-card[id]").forEach(card => {
        const source = card.querySelector(".article-meta span:last-child")?.textContent || "";
        const cardTitle = card.querySelector("h3")?.textContent || "";
        const navLabel = card.id === "rovat-joke" ? "Vicc" : card.id === "rovat-xkcd" ? "xkcd" : cardTitle;
        targets.push({ id: card.id, label: navLabel });
      });
    }
  });

  targets.forEach(({ id, label }) => {
    if (!document.getElementById(id)) return;
    sectionNav.append(new Option(label, id));
  });

  sectionNav.onchange = () => {
    const target = document.getElementById(sectionNav.value);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if ("IntersectionObserver" in window) {
    sectionNavigationObserver = new IntersectionObserver(entries => {
      const visible = entries
        .filter(entry => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) sectionNav.value = visible.target.id;
    }, { rootMargin: "-18% 0px -68% 0px", threshold: [0, 0.15, 0.4, 0.7] });
    targets.forEach(({ id }) => {
      const target = document.getElementById(id);
      if (target) sectionNavigationObserver.observe(target);
    });
  }
}

function getRelatedContent(item) {
  return Array.isArray(item.shard_content_items)
    ? item.shard_content_items[0]
    : item.shard_content_items;
}

function renderAgoraBody(container, body) {
  container.replaceChildren();
  const blocks = String(body || "").split(/\n\s*\n/).map(part => part.trim()).filter(Boolean);
  blocks.forEach(block => {
    const heading = block.match(/^(#{2,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(5, heading[1].length + 1);
      container.append(makeElement("h" + level, "agora-body-heading", heading[2]));
    } else {
      const paragraph = makeElement("p", "agora-body-paragraph");
      paragraph.textContent = block.replace(/\*\*/g, "");
      container.append(paragraph);
    }
  });
  if (!blocks.length) container.append(makeElement("p", "agora-empty", "Ehhez az AGORA-rovatcikkhez nem érhető el szöveg."));
}

function getAgoraContentType(item) {
  if (item?.editor_note === "MAGYAR AGORA") return "agora_hungary";
  if (item?.editor_note === "WORLD AGORA") return "agora_world";
  const source = getRelatedContent(item);
  const metadata = source?.metadata && typeof source.metadata === "object" ? source.metadata : {};
  if (metadata.content_type === "agora_hungary" || metadata.content_type === "agora_world") {
    return metadata.content_type;
  }
  if (source?.source_name === "MAGYAR AGORA") return "agora_hungary";
  if (source?.source_name === "WORLD AGORA") return "agora_world";
  return null;
}

function renderAgora(items = []) {
  if (!agoraFeed) return;
  agoraFeed.replaceChildren();
  const definitions = [
    { code: "agora_hungary", id: "agora-hungary", title: "MAGYAR AGORA", subtitle: "A nap magyarországi eseménye" },
    { code: "agora_world", id: "agora-world", title: "WORLD AGORA", subtitle: "A nap nemzetközi eseménye" }
  ];
  definitions.forEach(definition => {
    const item = items.find(row => getAgoraContentType(row) === definition.code);
    const column = makeElement("article", "agora-column");
    column.id = definition.id;
    column.dataset.navLabel = definition.title;
    const top = makeElement("div", "agora-column-top");
    top.append(makeElement("span", "agora-kicker", "AGORA · TÖRTÉNELMI NÉZŐPONTOK"));
    top.append(makeElement("span", "agora-index", definition.code === "agora_hungary" ? "01 / 02" : "02 / 02"));
    column.append(top, makeElement("h3", "agora-column-title", definition.title));
    column.append(makeElement("p", "agora-column-subtitle", definition.subtitle));
    if (!item) {
      column.append(makeElement("p", "agora-empty", "A mai kiadásban ez az AGORA-rovat még nem érhető el."));
    } else {
      column.append(makeElement("h4", "agora-news-title", item.display_title || "Cím nélkül"));
      if (item.display_summary) column.append(makeElement("p", "agora-news-summary", item.display_summary));
      const body = makeElement("div", "agora-body");
      renderAgoraBody(body, item.display_body);
      column.append(body);
      const sourceRecord = getRelatedContent(item);
      const metadata = sourceRecord?.metadata && typeof sourceRecord.metadata === "object" ? sourceRecord.metadata : {};
      const references = Array.isArray(metadata.source_references) ? metadata.source_references : [];
      if (references.length) {
        const sourceList = makeElement("div", "agora-sources");
        sourceList.append(makeElement("span", "agora-sources-label", "FELHASZNÁLT HÍRFORRÁSOK"));
        references.forEach(reference => {
          if (!reference?.url) return;
          try {
            const url = new URL(reference.url);
            if (url.protocol !== "https:" && url.protocol !== "http:") return;
            const link = makeElement("a", "agora-source-link", reference.publisher || reference.title || "Eredeti cikk");
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            sourceList.append(link);
          } catch (_) {}
        });
        if (sourceList.querySelector("a")) column.append(sourceList);
      }
    }
    agoraFeed.append(column);
  });
}

function renderArticles(items = []) {
  if (!feed) return;
  feed.replaceChildren();

  if (!items.length) {
    feed.append(makeElement("p", "empty-feed", "A publikált kiadás tartalma itt jelenik majd meg."));
    return;
  }

  sections.forEach(([number, code, title, description]) => {
    const sectionItems = items.filter(item =>
      item.section_code === code && !(code === "research_frontier" && getAgoraContentType(item))
    ).sort((a, b) => (a.position || 0) - (b.position || 0));
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
      const cardSource = getSourceRecord(item);
      if (code === "closing" && cardSource?.source_name === "JokeAPI") card.id = "rovat-joke";
      if (code === "closing" && cardSource?.source_name === "xkcd") card.id = "rovat-xkcd";
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
      const feedback = createRatingWidget(item.id);
      const source = getSourceRecord(item);
      let sectionImage = null;
      if (code === "art_of_the_day") {
        sectionImage = makeSectionImage(source, item.display_title, "article-artwork-image", "A műalkotás");
      } else if (code === "world_explorer") {
        sectionImage = makeSectionImage(source, item.display_title, "article-place-image", "A bemutatott helyszín");
      } else if (code === "battlefield") {
        sectionImage = makeSectionImage(source, item.display_title, "article-battle-image", "A csata történelmi ábrázolása");
      } else if (code === "closing" && source?.source_name === "xkcd") {
        sectionImage = makeSectionImage(source, item.display_title, "article-xkcd-image", "xkcd képregény");
      }
      if (sectionImage) card.append(sectionImage);
      card.append(meta, titleNode, summary, feedback, button);
      cards.append(card);
    });
    group.append(cards);
    feed.append(group);
  });
  renderSectionNavigation();
}

const archiveList = document.querySelector("#archive-list");
const archiveCount = document.querySelector("#archive-count");
let publishedEditions = [];
let activeEditionId = null;

function renderArchive(editions) {
  if (!archiveList) return;
  archiveList.replaceChildren();
  if (archiveCount) archiveCount.textContent = `${editions.length} KIADÁS`;
  if (!editions.length) {
    archiveList.append(makeElement("p", "archive-empty", "Még nincs korábbi publikált kiadás."));
    return;
  }

  editions.forEach((edition, index) => {
    const button = makeElement("button", "archive-entry");
    button.type = "button";
    button.classList.toggle("is-active", edition.id === activeEditionId);
    button.setAttribute("aria-pressed", String(edition.id === activeEditionId));
    const date = makeElement("span", "archive-entry-date", formatEditionDate(edition.edition_date));
    const title = makeElement("strong", "archive-entry-title", edition.title || "WORLD SHARDS – napi kiadás");
    const label = makeElement("span", "archive-entry-label", index === 0 ? "LEGFRISSEBB KIADÁS" : "KIADÁS MEGNYITÁSA");
    button.append(date, title, label);
    button.addEventListener("click", () => loadEdition(edition));
    archiveList.append(button);
  });
}

async function loadEdition(edition) {
  const config = window.WORLD_SHARDS_CONFIG || {};
  const supabaseUrl = (config.supabaseUrl || "").replace(/\/$/, "");
  const anonKey = config.supabaseAnonKey || "";
  const headers = { apikey: anonKey, Authorization: `Bearer ${anonKey}`, Accept: "application/json" };

  try {
    activeEditionId = edition.id;
    renderArchive(publishedEditions);
    showStatus("A kiadás betöltése", `${formatEditionDate(edition.edition_date)} – a tartalom betöltése folyamatban…`);
    // Load edition rows and source records separately. This avoids relying on
    // PostgREST's nested relationship expansion, which can fail independently
    // of the edition table and leave the page showing only the AGORA shell.
    const itemsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_edition_items?select=id,content_item_id,section_code,editor_note,position,display_title,display_summary,display_body,processing_status&edition_id=eq.${encodeURIComponent(edition.id)}&order=position.asc`,
      { headers }
    );
    if (!itemsResponse.ok) throw new Error(`Tartalomlekérdezés: HTTP ${itemsResponse.status}`);
    const items = await itemsResponse.json();

    const sourceIds = [...new Set(items.map(item => item.content_item_id).filter(Boolean))];
    if (sourceIds.length) {
      const sourceFilter = `in.(${sourceIds.join(",")})`;
      const sourceResponse = await fetch(
        `${supabaseUrl}/rest/v1/shard_content_items?select=id,title,summary,body,source_name,source_url,source_published_at&id=${encodeURIComponent(sourceFilter)}`,
        { headers }
      );
      if (sourceResponse.ok) {
        const sources = await sourceResponse.json();
        const sourceById = new Map(sources.map(source => [source.id, source]));

        // Image columns are schema extensions and are intentionally fetched
        // independently. A missing image_url or gallery_images column/grant
        // must never invalidate the core source lookup for the whole edition.
        for (const [field, select] of [
          ["image_url", "id,image_url"],
          ["gallery_images", "id,gallery_images"]
        ]) {
          try {
            const imageResponse = await fetch(
              `${supabaseUrl}/rest/v1/shard_content_items?select=${select}&id=${encodeURIComponent(sourceFilter)}`,
              { headers }
            );
            if (imageResponse.ok) {
              const imageRows = await imageResponse.json();
              imageRows.forEach(row => {
                const source = sourceById.get(row.id);
                if (source) source[field] = row[field] || (field === "gallery_images" ? [] : null);
              });
            } else {
              console.warn(`WORLD SHARDS optional ${field} unavailable:`, imageResponse.status);
            }
          } catch (imageError) {
            console.warn(`WORLD SHARDS optional ${field} lookup failed:`, imageError);
          }
        }

        items.forEach(item => {
          item.shard_content_items = sourceById.get(item.content_item_id) || null;
        });
      } else {
        // Edition rows already contain the display text and editor_note.
        // Source metadata only enriches images and citations; it must not
        // prevent the actual published articles from appearing.
        console.warn("WORLD SHARDS source metadata unavailable:", sourceResponse.status);
        items.forEach(item => { item.shard_content_items = null; });
      }
    }
    // A published edition can contain rows still marked pending/failed after
    // a partial editorial run. Keep those rows visible using their source text
    // instead of silently filtering the entire section out.
    items.forEach(item => {
      const source = getRelatedContent(item);
      if (!item.display_title) item.display_title = source?.title || "Feldolgozás alatt";
      if (!item.display_summary) item.display_summary = source?.summary || "";
      if (!item.display_body) item.display_body = source?.body || "";
    });

    try {
      await loadArticleRatings(items, headers, supabaseUrl);
    } catch (ratingError) {
      console.warn("WORLD SHARDS article ratings are temporarily unavailable:", ratingError);
      ratingHeaders = { ...headers, "x-reader-token": getVoterToken() };
      ratingApiUrl = supabaseUrl;
    }

    const formatted = formatEditionDate(edition.edition_date);
    if (dateNode) dateNode.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (headerDate) headerDate.textContent = formatted.toLocaleUpperCase("hu-HU");
    if (countNode) countNode.textContent = `${items.length} TARTALOM · 11 ROVAT`;
    showStatus(edition.title || "A kiadás elérhető", edition.introduction || "A kiválasztott kiadás betöltődött.", `PUBLISHED · ${items.length} ITEMS`);
    renderAgora(items);
    renderArticles(items);
    renderArchive(publishedEditions);
    document.querySelector("#edition")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    console.error("WORLD SHARDS edition error:", error);
    showStatus("A kiválasztott kiadás most nem tölthető be", "A kiadás vagy a hozzá tartozó forrástartalmak lekérdezése hibát adott; próbáld újra később.", "EDITION · LOAD ERROR");
    renderAgora([]);
    renderArticles([]);
    if (sectionNav) sectionNav.replaceChildren(new Option("A rovatok most nem érhetők el", ""));
  }
}

async function loadPublishedEdition() {
  const config = window.WORLD_SHARDS_CONFIG || {};
  const supabaseUrl = (config.supabaseUrl || "").replace(/\/$/, "");
  const anonKey = config.supabaseAnonKey || "";

  if (!supabaseUrl || !anonKey || supabaseUrl.includes("IDE_") || anonKey.includes("IDE_")) {
    showStatus("A Supabase-kapcsolat konfigurálásra vár", "A nyilvános adatkapcsolat beállítása hiányzik.", "F1 · CONFIG REQUIRED");
    renderAgora([]);
    renderArticles();
    if (archiveList) archiveList.replaceChildren(makeElement("p", "archive-empty", "Az archívumhoz adatbázis-kapcsolat szükséges."));
    return;
  }

  const headers = { apikey: anonKey, Authorization: `Bearer ${anonKey}`, Accept: "application/json" };

  try {
    showStatus("Kapcsolódás a kiadásokhoz", "A publikált lapszámok ellenőrzése folyamatban…");
    const editionsResponse = await fetch(
      `${supabaseUrl}/rest/v1/shard_editions?select=id,edition_date,title,introduction,status&status=eq.published&order=edition_date.desc&limit=365`,
      {
        headers: { ...headers, "Cache-Control": "no-cache", Pragma: "no-cache" },
        cache: "no-store"
      }
    );
    if (!editionsResponse.ok) throw new Error(`Kiadáslekérdezés: HTTP ${editionsResponse.status}`);
    publishedEditions = await editionsResponse.json();
    renderArchive(publishedEditions);

    if (!publishedEditions.length) {
      showStatus("Jelenleg nincs publikált napi kiadás", "A rendszer kapcsolata él. Amint egy kiadás published státuszt kap, itt automatikusan megjelenik. A piszkozatok nem nyilvánosak.", "SUPABASE · CONNECTED");
      renderAgora([]);
      renderArticles();
      if (countNode) countNode.textContent = "— TARTALOM · 11 ROVAT";
      return;
    }

    await loadEdition(publishedEditions[0]);
  } catch (error) {
    console.error("WORLD SHARDS Supabase error:", error);
    showStatus("A kiadások most nem tölthetők be", "A Supabase-kapcsolat vagy az anon olvasási jogosultság ellenőrzést igényel. A piszkozatok ettől függetlenül nem kerülnek nyilvánosságra.", "SUPABASE · CONNECTION ERROR");
    renderArticles();
    if (archiveList) archiveList.replaceChildren(makeElement("p", "archive-empty", "Az archívum most nem érhető el."));
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

const sections = [
  ["01","RESEARCH FRONTIER","A tudomány legfrissebb felismerései","05"],
  ["02","ART OF THE DAY","Egy alkotás, amely megérdemli a figyelmet","01"],
  ["03","THE THINKER","Eszmék és gondolatok a világról","01"],
  ["04","BATTLEFIELD","Konfliktusok, stratégiák, történelem","01"],
  ["05","FUNDAMENTALS","A világ működésének alapjai","01"],
  ["06","WORLD EXPLORER","Helyek és jelenségek a bolygónkról","01"],
  ["07","UNSOLVED","Nyitott kérdések és megfejtetlen rejtélyek","01"],
  ["08","MUSIC OF THE DAY","A nap témájához kapcsolódó zenei felfedezés","01"],
  ["09","CLOSING","Egy könnyedebb lezárás: képregény és humor","02"]
];

const grid = document.querySelector("#section-grid");
if (grid) {
  grid.innerHTML = sections.map(([number, title, description, count]) => `
    <article class="section-card">
      <span class="card-number">${number} / ${count}</span>
      <span class="card-arrow" aria-hidden="true">↗</span>
      <h3>${title}</h3>
      <p>${description}</p>
    </article>
  `).join("");
}

const now = new Date();
const formattedDate = new Intl.DateTimeFormat("hu-HU", {
  year: "numeric", month: "long", day: "numeric"
}).format(now);

const dateNode = document.querySelector("#edition-date");
const headerDate = document.querySelector("#header-date");
const yearNode = document.querySelector("#year");
if (dateNode) dateNode.textContent = formattedDate.toLocaleUpperCase("hu-HU");
if (headerDate) headerDate.textContent = formattedDate.toUpperCase();
if (yearNode) yearNode.textContent = now.getFullYear();

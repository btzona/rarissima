(() => {
  "use strict";

  const grid = document.getElementById("articles");
  const statusEl = document.getElementById("status");
  const updatedEl = document.getElementById("updated");
  const countEl = document.getElementById("count");
  const searchInput = document.getElementById("search");
  const filterBtns = Array.from(document.querySelectorAll("[data-filter]"));

  const pageSize = 18;

  let data = null;
  let filter = "all";
  let query = "";
  let visibleCount = pageSize;

  const monthNames = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function italicizeSpecies(text, speciesList) {
    let out = escapeHtml(text || "");
    const names = (speciesList || [])
      .slice()
      .sort((a, b) => b.length - a.length);
    for (const name of names) {
      const esc = escapeHtml(name).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp(`\\b(${esc})\\b`, "g"), "<em>$1</em>");
    }
    // Heuristic: Genus species in titles when no list
    if (!names.length) {
      out = out.replace(
        /\b([A-Z][a-z]{2,}\s+[a-z]{3,}(?:\s+[a-z]{3,})?)\b/g,
        (m, g1) => {
          const first = g1.split(/\s+/)[0];
          const block = new Set([
            "The", "This", "These", "From", "With", "After", "Using", "Based",
            "Open", "Early", "Royal", "Journal", "Nature", "Science", "Frontiers",
            "Systematic", "Entomology", "New", "South", "North", "East", "West",
            "September", "October", "November", "December", "January", "February",
            "March", "April", "August", "June", "July", "United", "Puerto", "Costa",
            "Hong", "Bee", "First", "Late", "Early", "Recent", "Global", "Molecular",
          ]);
          if (block.has(first)) return m;
          return `<em>${g1}</em>`;
        }
      );
    }
    return out;
  }

  function formatDate(iso) {
    if (!iso) return "Date unknown";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "Date unknown";
    // Display in America/Phoenix-ish local via Intl
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Phoenix",
        year: "numeric",
        month: "short",
        day: "numeric",
      }).format(d);
    } catch {
      return `${monthNames[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
    }
  }

  function formatUpdated(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    try {
      return new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Phoenix",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      }).format(d);
    } catch {
      return d.toISOString();
    }
  }

  function phoenixYearMonth(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "unknown";
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Phoenix",
      year: "numeric",
      month: "2-digit",
    }).formatToParts(d);
    const year = parts.find((part) => part.type === "year");
    const month = parts.find((part) => part.type === "month");
    if (!year || !month) return "unknown";
    return `${year.value}-${month.value}`;
  }

  function monthLabel(key) {
    if (key === "unknown") return "Date unknown";
    const [year, month] = key.split("-");
    const index = Number(month) - 1;
    if (!year || index < 0 || index > 11) return "Date unknown";
    return `${monthNames[index]} ${year}`;
  }

  function setStatus(msg, state) {
    statusEl.textContent = msg;
    if (state) statusEl.dataset.state = state;
    else delete statusEl.dataset.state;
  }

  function matches(article) {
    if (filter === "rare" && !article.rare) return false;
    if (filter === "research" && article.rare) return false;
    if (!query) return true;
    const blob = [
      article.title,
      article.summary,
      article.source,
      ...(article.species || []),
    ]
      .join(" ")
      .toLowerCase();
    return blob.includes(query);
  }

  function cardHtml(article) {
    const badge = article.rare
      ? '<span class="badge">Rare / cryptic</span>'
      : '<span class="badge muted">Entomology</span>';
    const species =
      article.species && article.species.length
        ? `<p class="species"><span>Taxa</span>${article.species
            .map((name) => `<em>${escapeHtml(name)}</em>`)
            .join(" · ")}</p>`
        : "";
    return `
<article class="card">
  <div class="card-top">
    ${badge}
    <span class="source">${escapeHtml(article.source)}</span>
  </div>
  <h3><a href="${escapeHtml(article.link)}" rel="noopener noreferrer" target="_blank">${italicizeSpecies(
      article.title,
      article.species
    )}</a></h3>
  <p class="excerpt">${italicizeSpecies(article.summary, article.species)}</p>
  ${species}
  <div class="card-foot">
    <time class="date" datetime="${escapeHtml(article.date || "")}">${formatDate(article.date)}</time>
    <a class="outlink" href="${escapeHtml(article.link)}" rel="noopener noreferrer" target="_blank">Original</a>
  </div>
</article>`;
  }

  function render() {
    if (!data) return;
    const items = (data.articles || []).filter(matches);
    countEl.textContent = String(items.length);

    if (!items.length) {
      grid.innerHTML =
        '<div class="empty" role="status">No specimens match this filter. Try “All” or clear search.</div>';
      return;
    }

    const shown = items.slice(0, visibleCount);
    const groups = [];
    for (const article of shown) {
      const key = article.date ? phoenixYearMonth(article.date) : "unknown";
      const last = groups[groups.length - 1];
      if (!last || last.key !== key) groups.push({ key, items: [article] });
      else last.items.push(article);
    }

    const more =
      items.length > shown.length
        ? `<div class="more-wrap"><button type="button" class="more" id="load-more">Show earlier specimens</button><p class="more-note">${shown.length} of ${items.length}</p></div>`
        : "";

    grid.innerHTML =
      groups
        .map(
          (group) => `<section class="month">
  <h2 class="month-label">${monthLabel(group.key)}</h2>
  <div class="grid">${group.items.map(cardHtml).join("")}</div>
</section>`
        )
        .join("") + more;

    const moreBtn = document.getElementById("load-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", () => {
        visibleCount += pageSize;
        render();
      });
    }
  }

  async function load() {
    setStatus("Loading ledger…");
    try {
      const res = await fetch("data/articles.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
      updatedEl.textContent = formatUpdated(data.updated);
      const rare = data.rare_count ?? (data.articles || []).filter((a) => a.rare).length;
      const dated = (data.articles || [])
        .map((article) => article.date)
        .filter(Boolean)
        .sort();
      const span = dated.length
        ? `${formatDate(dated[0])} – ${formatDate(dated[dated.length - 1])}`
        : "dates unrecorded";
      setStatus(
        `Catalogued ${data.article_count} items · ${rare} rare/cryptic-tagged · ${span}`
      );
      render();
    } catch (err) {
      console.error(err);
      setStatus(
        "Could not load data/articles.json. Run python3 fetch.py then reload.",
        "error"
      );
      grid.innerHTML =
        '<div class="empty" role="alert">Missing article data. Refresh feeds with <code>python3 fetch.py</code>.</div>';
    }
  }

  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filter = btn.dataset.filter;
      visibleCount = pageSize;
      filterBtns.forEach((b) =>
        b.setAttribute("aria-pressed", String(b === btn))
      );
      render();
    });
  });

  let t = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      query = searchInput.value.trim().toLowerCase();
      visibleCount = pageSize;
      render();
    }, 120);
  });

  load();
})();

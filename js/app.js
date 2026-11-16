(() => {
  "use strict";

  const grid = document.getElementById("articles");
  const statusEl = document.getElementById("status");
  const updatedEl = document.getElementById("updated");
  const countEl = document.getElementById("catalog");
  const rareTotalEl = document.getElementById("rare-total");
  const spanEl = document.getElementById("span");
  const sparkEl = document.getElementById("spark");
  const searchInput = document.getElementById("search");
  const filterBtns = Array.from(document.querySelectorAll("[data-filter]"));

  const pageSize = 18;

  let data = null;
  let filter = "all";
  let query = "";
  let visibleCount = pageSize;
  let spanText = "";

  const orderCache = new WeakMap();

  const ORDERS = [
    { name: "Coleoptera", re: /\b(coleoptera|beetles?|weevils?)\b/i },
    { name: "Lepidoptera", re: /\b(lepidoptera|butterflies|butterfly|moths?)\b/i },
    { name: "Hymenoptera", re: /\b(hymenoptera|bees?|wasps?|ants?|sawflies|sawfly)\b/i },
    { name: "Diptera", re: /\b(diptera|mosquito(?:e)?s?|midges?|drosophila|fruit flies|fruit fly)\b/i },
    { name: "Hemiptera", re: /\b(hemiptera|aphids?|cicadas?|leafhoppers?|planthoppers?|true bugs?)\b/i },
    { name: "Orthoptera", re: /\b(orthoptera|crickets?|grasshoppers?|katydids?)\b/i },
    { name: "Odonata", re: /\b(odonata|dragonflies|dragonfly|damselflies|damselfly)\b/i },
    { name: "Trichoptera", re: /\b(trichoptera|caddisflies|caddisfly)\b/i },
    { name: "Neuroptera", re: /\b(neuroptera|lacewings?)\b/i },
    { name: "Blattodea", re: /\b(blattodea|cockroaches?|termites?)\b/i },
    { name: "Mantodea", re: /\b(mantodea|mantids?|mantises|mantis)\b/i },
    { name: "Phasmatodea", re: /\b(phasmida|phasmatodea|stick insects?|walking sticks?)\b/i },
  ];

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

  function detectOrder(article) {
    const title = article.title || "";
    const rest = `${article.summary || ""} ${(article.species || []).join(" ")}`;
    for (const blob of [title, `${title} ${rest}`]) {
      for (const order of ORDERS) {
        if (order.re.test(blob)) return order.name;
      }
    }
    return "";
  }

  function orderOf(article) {
    if (orderCache.has(article)) return orderCache.get(article);
    const name = detectOrder(article);
    orderCache.set(article, name);
    return name;
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
      orderOf(article),
      ...(article.species || []),
    ]
      .join(" ")
      .toLowerCase();
    return blob.includes(query);
  }

  function indexLabel(n) {
    return String(n).padStart(3, "0");
  }

  function orderHtml(article) {
    const name = orderOf(article);
    if (!name) return "";
    return `<span class="order" data-order="${escapeHtml(name)}"><i aria-hidden="true"></i>${escapeHtml(name)}</span>`;
  }

  function flagHtml(article) {
    return article.rare ? '<span class="flag">Rare</span>' : "";
  }

  function footHtml(article) {
    return `<p class="entry-foot">
      <span class="source">${escapeHtml(article.source || "Source unknown")}</span>
      <time datetime="${escapeHtml(article.date || "")}">${formatDate(article.date)}</time>
      <a class="outlink" href="${escapeHtml(article.link)}" rel="noopener noreferrer" target="_blank">Original</a>
    </p>`;
  }

  function heroHtml(article) {
    const newest = (data.articles || [])
      .map((item) => item.date)
      .filter(Boolean)
      .sort()
      .at(-1);
    let kicker = "Lead story";
    if (article.rare) {
      const days = newest && article.date
        ? (new Date(newest) - new Date(article.date)) / 86400000
        : Infinity;
      kicker = days <= 10 ? "Specimen of the week" : "Featured specimen";
    }
    return `<article class="hero">
      <p class="hero-kicker">
        <span>${escapeHtml(kicker)}</span>
        ${flagHtml(article)}
        ${orderHtml(article)}
      </p>
      <h2><a href="${escapeHtml(article.link)}" rel="noopener noreferrer" target="_blank">${italicizeSpecies(article.title, article.species)}</a></h2>
      <p class="excerpt">${italicizeSpecies(article.summary, article.species)}</p>
      ${footHtml(article)}
    </article>`;
  }

  function entryHtml(article, index, feature) {
    return `<article class="entry${feature ? " feature" : ""}">
      <p class="entry-kicker">
        <span class="idx">${indexLabel(index)}</span>
        ${flagHtml(article)}
        ${orderHtml(article)}
      </p>
      <h3><a href="${escapeHtml(article.link)}" rel="noopener noreferrer" target="_blank">${italicizeSpecies(article.title, article.species)}</a></h3>
      <p class="excerpt">${italicizeSpecies(article.summary, article.species)}</p>
      ${footHtml(article)}
    </article>`;
  }

  function pickLead(items) {
    if (filter !== "research") {
      const rare = items.find((article) => article.rare);
      if (rare) return rare;
    }
    return items[0];
  }

  function monthKey(article) {
    return article.date ? phoenixYearMonth(article.date) : "unknown";
  }

  function monthSeries(articles) {
    const counts = new Map();
    for (const article of articles) {
      if (!article.date) continue;
      const key = phoenixYearMonth(article.date);
      if (key === "unknown") continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.keys()].sort().map((key) => ({
      key,
      label: monthLabel(key).split(" ")[0],
      count: counts.get(key),
    }));
  }

  function sparkHtml(series) {
    if (!series.length) return "";
    const label = series.map((point) => `${monthLabel(point.key)}: ${point.count}`).join(", ");
    const w = 160;
    const h = 36;
    const pad = 3;
    const max = Math.max(...series.map((point) => point.count), 1);
    const coords = series.map((point, i) => {
      const x = series.length === 1
        ? w / 2
        : pad + (i * (w - pad * 2)) / (series.length - 1);
      const y = h - pad - (point.count / max) * (h - pad * 2);
      return [x, y];
    });
    const points = coords.map((pair) => `${pair[0].toFixed(1)},${pair[1].toFixed(1)}`).join(" ");
    const last = coords[coords.length - 1];
    const shown = series.length <= 8
      ? series
      : [series[0], series[Math.floor((series.length - 1) / 2)], series[series.length - 1]];
    const labels = shown
      .map((point) => `<span>${escapeHtml(point.label)}</span>`)
      .join("");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" role="img" aria-label="Papers per month. ${escapeHtml(label)}">
      <polyline fill="none" stroke="currentColor" stroke-width="1.6" points="${points}" />
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.4" fill="currentColor" />
    </svg>
    <div class="spark-labels">${labels}</div>`;
  }

  function render(focusAt) {
    if (!data) return;
    const items = (data.articles || []).filter(matches);
    const rareShown = items.filter((article) => article.rare).length;
    if (query || filter !== "all") {
      setStatus(`Showing ${items.length} of ${data.article_count} · ${rareShown} rare/cryptic in this view`);
    } else if (spanText) {
      setStatus(`Catalogued ${data.article_count} items · ${data.rare_count ?? rareShown} rare/cryptic-tagged · ${spanText}`);
    }

    if (!items.length) {
      grid.innerHTML =
        '<div class="empty" role="status">No specimens match this filter. Try “All” or clear the search.</div>';
      return;
    }

    const lead = pickLead(items);
    const rest = items.filter((article) => article !== lead);
    const restBudget = Math.max(0, visibleCount - 1);
    const shown = rest.slice(0, restBudget);
    const totals = new Map();
    for (const article of rest) {
      const key = monthKey(article);
      totals.set(key, (totals.get(key) || 0) + 1);
    }

    const groups = [];
    for (const article of shown) {
      const key = monthKey(article);
      const last = groups[groups.length - 1];
      if (!last || last.key !== key) groups.push({ key, items: [article] });
      else last.items.push(article);
    }

    const shownTotal = 1 + shown.length;
    const more = items.length > shownTotal
      ? `<div class="more-wrap"><button type="button" class="more" id="load-more">Show earlier specimens</button><p class="more-note">${shownTotal} of ${items.length}</p></div>`
      : "";

    const months = groups
      .map((group) => {
        const total = totals.get(group.key) || group.items.length;
        const countLabel = group.items.length === total
          ? `${total} ${total === 1 ? "item" : "items"}`
          : `${group.items.length} of ${total}`;
        const entries = group.items
          .map((article, i) => entryHtml(article, rest.indexOf(article) + 1, i === 0))
          .join("");
        return `<section class="month">
          <div class="month-head">
            <h2 class="month-label">${monthLabel(group.key)}</h2>
            <p class="month-count">${countLabel}</p>
          </div>
          <div class="month-grid">${entries}</div>
        </section>`;
      })
      .join("");

    grid.innerHTML = heroHtml(lead) + months + more;

    const moreBtn = document.getElementById("load-more");
    if (moreBtn) {
      moreBtn.addEventListener("click", () => {
        const before = shownTotal;
        visibleCount += pageSize;
        render(before);
      });
    }

    if (typeof focusAt === "number") {
      const entries = grid.querySelectorAll(".hero, .entry");
      const next = entries[focusAt] || moreBtn;
      if (next) {
        if (next.classList && (next.classList.contains("hero") || next.classList.contains("entry"))) {
          next.tabIndex = -1;
        }
        next.focus();
      }
    }
  }

  async function load() {
    setStatus("Loading ledger…");
    try {
      const res = await fetch("data/articles.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
      updatedEl.textContent = formatUpdated(data.updated);
      const articles = data.articles || [];
      const rare = data.rare_count ?? articles.filter((article) => article.rare).length;
      countEl.textContent = String(data.article_count ?? articles.length);
      rareTotalEl.textContent = String(rare);
      const dated = articles.map((article) => article.date).filter(Boolean).sort();
      spanText = dated.length
        ? `${formatDate(dated[0])} – ${formatDate(dated[dated.length - 1])}`
        : "dates unrecorded";
      spanEl.textContent = spanText;
      sparkEl.innerHTML = sparkHtml(monthSeries(articles));
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

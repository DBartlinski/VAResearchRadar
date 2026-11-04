"use strict";

const STEP = 25;
const TIERS = ["High", "Medium", "Low"];
const MINOR_RE = /conference abstract|meeting abstract|erratum|correction|editorial|letter|comment/i;
const FLAG_STORE = "vadaily.flags";
const $ = (id) => document.getElementById(id);

const state = {
  all: [], meta: null, view: [], days: [], latestDay: null,
  day: null,
  flags: new Set(JSON.parse(localStorage.getItem(FLAG_STORE) || "[]")),
  open: { High: true, Medium: true, Low: false },
  shown: { High: STEP, Medium: STEP, Low: STEP },
  byKey: new Map(),
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
const localIso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function dayLabel(iso) {
  const today = new Date();
  const yesterday = new Date(Date.now() - 86400000);
  if (iso === localIso(today)) return "Today";
  if (iso === localIso(yesterday)) return "Yesterday";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

function shortType(r) {
  const types = (r.doc_type || r.pub_type || "").split(";").map((s) => s.trim())
    .filter((s) => s && s !== "Journal Article" && s !== "Article");
  return types.slice(0, 2).join(", ");
}

function topicChips(r) {
  return (r.score_reasons || [])
    .map((s) => /^\+\d+ (?:Topic|Design): (.+)$/.exec(s)?.[1])
    .filter(Boolean).slice(0, 4);
}

const jtClass = (t) => (t === "Not rated" ? "NotRated" : esc(t));
const jtLabel = (t) => (t === "Top" || t === "Mid" || t === "Lower" ? `${t} journal` : t || "Not rated");

function showStatus(msg, isError = false) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status" + (isError ? " error" : "");
  el.hidden = !msg;
}

function saveFlags() {
  localStorage.setItem(FLAG_STORE, JSON.stringify([...state.flags]));
}

async function loadData() {
  try {
    const [pubs, meta] = await Promise.all([
      fetch("data/publications.json", { cache: "no-store" }).then((r) => (r.ok ? r.json() : [])),
      fetch("data/meta.json", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)),
    ]);
    state.all = pubs;
    state.meta = meta;
    state.byKey = new Map(pubs.map((r) => [r.key, r]));
    for (const r of pubs) {
      r.added = r.added || (r.first_seen || "").slice(0, 10);
      r._search = [r.title, r.abstract, r.authors, r.journal, r.funder, r.funding_text, r.mesh_terms, r.doi, r.pmid,
        ...(r.author_affiliations?.affiliations || [])]
        .filter(Boolean).join(" ").toLowerCase();
    }
    state.days = [...new Set(pubs.map((r) => r.added).filter(Boolean))].sort().reverse();
    state.latestDay = state.days[0] || null;
    if (!state.day || (state.day !== "7d" && state.day !== "all" && !state.days.includes(state.day))) {
      state.day = state.latestDay || "all";
    }
    renderMeta();
    renderDays();
    applyFilters();
    if (!pubs.length) showStatus("No data has been published yet.");
  } catch (e) {
    showStatus("Could not load data: " + e.message, true);
  }
}

function renderMeta() {
  const m = state.meta;
  if (!m) {
    $("meta").textContent = "No data published yet.";
    renderMethod(null);
    return;
  }
  const when = m.finished ? new Date(m.finished).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }) : "";
  $("meta").textContent = `Last refreshed ${when} · ${m.total ?? 0} publications since ${fmtDate(m.start_date)}`;
  if (m.warnings?.length) showStatus("Notes from last refresh:\n• " + m.warnings.join("\n• "), true);
  renderMethod(m.scoring);
}

const PENALTY_LABELS = {
  preprint: "Preprint (not peer reviewed)",
  conference_abstract: "Conference or meeting abstract",
  editorial_or_letter: "Editorial, letter or comment",
  erratum: "Correction or erratum",
  retracted: "Retraction or expression of concern",
  non_health: "No health or veteran signals (e.g., engineering, chemistry)",
};

function pts(n) {
  return `<td class="pts ${n >= 0 ? "pos" : "neg"}">${n >= 0 ? "+" : ""}${n}</td>`;
}

function keywordText(list) {
  const plain = list.filter((k) => !k.startsWith("re:")).map((k) => k.replace(/\*/g, "…"));
  const patterns = list.length - plain.length;
  return esc(plain.join(", ")) + (patterns ? `${plain.length ? ", " : ""}<em>+${patterns} pattern rule${patterns > 1 ? "s" : ""}</em>` : "");
}

function ruleRows(rules) {
  return [...rules].sort((a, b) => b.weight - a.weight)
    .map((r) => `<tr>${pts(r.weight)}<td><strong>${esc(r.name)}</strong><div class="kw">${keywordText(r.keywords)}</div></td></tr>`).join("");
}

function renderMethod(s) {
  if (!s) {
    $("method").innerHTML = "<h2>How newsworthiness is calculated</h2><p>Run a refresh to load the scoring rules.</p>";
    return;
  }
  const jt = s.journal_tiers;
  const vt = s.veteran_in_title;
  $("method").innerHTML = `
    <h2>How newsworthiness is calculated</h2>
    <p>Each publication gets a score by adding points for every signal it matches. Topics and study designs are matched
      against the title, abstract, MeSH terms and publication type. Points from different topics add up, so a randomized
      trial on suicide prevention in a top-tier journal scores far higher than a single-topic paper.</p>
    <div class="tierline">
      <span><span class="dot High"></span> <strong>High</strong>: ${s.tiers.high}+ points</span>
      <span><span class="dot Medium"></span> <strong>Medium</strong>: ${s.tiers.medium}–${s.tiers.high - 1}</span>
      <span><span class="dot Low"></span> <strong>Low</strong>: below ${s.tiers.medium}</span>
    </div>
    <p>Open any publication to see exactly which signals it matched under “Why it was flagged”.</p>

    <div class="grid2">
      <div>
        <h3>Topics</h3>
        <table><tr><th>Points</th><th>Topic and matching terms</th></tr>${ruleRows(s.topics)}</table>
      </div>
      <div>
        <h3>Study design</h3>
        <table><tr><th>Points</th><th>Design and matching terms</th></tr>${ruleRows(s.study_designs)}</table>

        <h3>Journal tier</h3>
        <p>Based on the journal's OpenAlex 2-year mean citedness (an impact-factor-like measure), refreshed monthly.</p>
        <table>
          <tr>${pts(jt.top_weight)}<td><span class="jt Top">Top journal</span> citedness ${jt.top_min_citedness}+</td></tr>
          <tr>${pts(jt.mid_weight)}<td><span class="jt Mid">Mid journal</span> citedness ${jt.mid_min_citedness}–${jt.top_min_citedness}</td></tr>
          <tr>${pts(0)}<td><span class="jt Lower">Lower journal</span> citedness below ${jt.mid_min_citedness}; <span class="jt Preprint">Preprint</span>; <span class="jt NotRated">Not rated</span></td></tr>
        </table>
        <p class="kw">Always Top: ${esc(jt.always_top.join(", "))}. Always Mid: ${esc(jt.always_mid.join(", ") || "none")}.</p>

        <h3>Funding and other signals</h3>
        <table>
          <tr>${pts(s.funding.ord_funded)}<td>Funded by VA Office of Research and Development (BLR&amp;D, CSR&amp;D, HSR&amp;D, RR&amp;D, CSP)</td></tr>
          <tr>${pts(s.funding.va_funded_only)}<td>VA funded, but not identified as ORD</td></tr>
          <tr>${pts(vt.weight)}<td>Veterans or military in the title<div class="kw">${keywordText(vt.keywords)}</div></td></tr>
          <tr>${pts(s.other.open_access)}<td>Open access</td></tr>
          <tr>${pts(s.other.cited_5_plus)}<td>Already cited 5 or more times</td></tr>
        </table>

        <h3>Deductions</h3>
        <table>${Object.entries(s.penalties).map(([k, v]) => `<tr>${pts(v)}<td>${esc(PENALTY_LABELS[k] || k)}</td></tr>`).join("")}</table>
      </div>
    </div>

    <h3>How funding is identified</h3>
    <p>ORD service comes from VA award numbers (BX = BLR&amp;D, CX = CSR&amp;D, HX = HSR&amp;D, RX = RR&amp;D), the funder list,
      and VA support statements in the funding and acknowledgement text. Standard disclaimers (“views do not represent the
      Department of Veterans Affairs”) and use of VA facilities are not counted as funding. Each publication lists the evidence used.</p>
    <p class="kw">Weights and terms are set in config/settings.yaml and take effect on the next refresh.</p>`;
}

function renderDays() {
  const count = (d) => state.all.filter((r) => r.added === d).length;
  const weekAgo = localIso(new Date(Date.now() - 6 * 86400000));
  const pills = state.days.slice(0, 10).map((d) => ({ id: d, label: dayLabel(d), n: count(d) }));
  pills.push({ id: "7d", label: "Last 7 days", n: state.all.filter((r) => r.added >= weekAgo).length });
  pills.push({ id: "all", label: "All", n: state.all.length });
  $("days").innerHTML = pills.map((p) =>
    `<button class="pill${p.id === state.day ? " active" : ""}" data-day="${esc(p.id)}">${esc(p.label)}<span class="n">${p.n}</span></button>`
  ).join("");
}

function checkedValues(name) {
  return new Set([...document.querySelectorAll(`input[name=${name}]:checked`)].map((i) => i.value));
}

function applyFilters() {
  const q = $("q").value.trim().toLowerCase();
  const tiers = checkedValues("tier");
  const jtiers = checkedValues("jtier");
  const service = $("service").value;
  const source = $("source").value;
  const from = $("from").value;
  const weekAgo = localIso(new Date(Date.now() - 6 * 86400000));
  const f = {
    va: $("vaFunded").checked, ord: $("ordFunded").checked,
    flagged: $("flaggedOnly").checked, hideMinor: $("hideMinor").checked,
  };

  state.view = state.all.filter((r) => {
    if (state.day === "7d" ? r.added < weekAgo : state.day !== "all" && r.added !== state.day) return false;
    if (!tiers.has(r.tier)) return false;
    if (!jtiers.has(r.journal_tier || "Not rated")) return false;
    if (q && !q.split(/\s+/).every((w) => r._search.includes(w))) return false;
    if (service && !(r.ord_services || []).includes(service)) return false;
    if (source && !r.sources.includes(source)) return false;
    if (from && r.pub_date < from) return false;
    if (f.va && !r.va_funded) return false;
    if (f.ord && !r.ord_funded) return false;
    if (f.flagged && !state.flags.has(r.key)) return false;
    if (f.hideMinor && (MINOR_RE.test(`${r.pub_type || ""} ${r.doc_type || ""}`) || /^(corrigendum|erratum)/i.test(r.title || ""))) return false;
    return true;
  });

  const sortKey = $("sort").value;
  state.view.sort((a, b) => sortKey === "pub_date"
    ? (b.pub_date || "").localeCompare(a.pub_date || "") || b.score - a.score
    : b.score - a.score || (b.pub_date || "").localeCompare(a.pub_date || ""));
  state.shown = { High: STEP, Medium: STEP, Low: STEP };
  renderSummary();
  renderSections();
}

function renderSummary() {
  const v = state.view;
  const n = (fn) => v.filter(fn).length;
  const stats = [
    ["", v.length, "Shown"],
    ["High", n((r) => r.tier === "High"), "High"],
    ["Medium", n((r) => r.tier === "Medium"), "Medium"],
    ["Top", n((r) => r.journal_tier === "Top"), "Top journals"],
    ["", n((r) => r.ord_funded), "ORD funded"],
    ["", n((r) => r.journal_tier === "Preprint"), "Preprints"],
    ["", n((r) => state.flags.has(r.key)), "Flagged ★"],
  ];
  $("summary").innerHTML = stats.map(([cls, num, lbl]) =>
    `<div class="stat ${cls}"><div class="num">${num}</div><div class="lbl">${esc(lbl)}</div></div>`).join("");
}

function cardHtml(r) {
  const flagged = state.flags.has(r.key);
  const tags = [];
  if (r.added === state.latestDay) tags.push('<span class="tag new">NEW</span>');
  if (r.journal_tier === "Preprint") tags.push('<span class="tag preprint">PREPRINT · not peer reviewed</span>');
  if (r.retraction) tags.push('<span class="tag warn">Retraction / notice</span>');
  if (r.ord_funded) (r.ord_services || []).forEach((s) => tags.push(`<span class="tag ord">ORD · ${esc(s)}</span>`));
  else if (r.va_funded) tags.push('<span class="tag va">VA funded</span>');
  topicChips(r).forEach((t) => tags.push(`<span class="tag topic">${esc(t)}</span>`));

  const meta = [
    r.journal ? `<span class="journal">${esc(r.journal)}</span>` : "",
    r.pub_date ? `Published ${esc(fmtDate(r.pub_date))}` : "",
    esc(shortType(r)),
  ].filter(Boolean).join(" · ");

  return `
    <article class="card ${esc(r.tier)}${flagged ? " flagged" : ""}" data-key="${esc(r.key)}">
      <button class="flag" aria-pressed="${flagged}" title="${flagged ? "Unflag" : "Flag for follow-up"}">${flagged ? "★" : "☆"}</button>
      <div>
        <div class="card-title">${esc(r.title || "(untitled)")}</div>
        <div class="card-meta"><span class="jt ${jtClass(r.journal_tier)}">${esc(jtLabel(r.journal_tier))}</span> ${meta}</div>
        ${r.first_va_author ? `<div class="card-affil" title="${esc(r.first_va_author.cleaned ? "First VA-affiliated author" : "First VA-affiliated author (affiliation shown as published)")}">First VA author: <strong>${esc(r.first_va_author.name)}</strong> · ${esc(r.first_va_author.facility)}</div>` : ""}
        <div class="card-tags">${tags.join("")}</div>
      </div>
      <div class="card-score"><div class="num">${r.score}</div><div class="lbl">${esc(r.tier)}</div></div>
    </article>`;
}

function renderSections() {
  if (!state.view.length) {
    $("sections").innerHTML = '<div class="empty">No publications match these filters for the selected day.</div>';
    return;
  }
  $("sections").innerHTML = TIERS.map((tier) => {
    const items = state.view.filter((r) => r.tier === tier);
    if (!items.length) return "";
    const shown = items.slice(0, state.shown[tier]);
    const remaining = items.length - shown.length;
    return `
      <section class="group${state.open[tier] ? "" : " collapsed"}" data-tier="${tier}">
        <button class="group-head ${tier}"><span class="chev">▼</span><span class="dot ${tier}"></span>
          ${tier} newsworthiness <span class="count">${items.length}</span></button>
        <div class="cards">${shown.map(cardHtml).join("")}</div>
        ${remaining > 0 ? `<button class="more" data-tier="${tier}">Show ${Math.min(STEP, remaining)} more (${remaining} remaining)</button>` : ""}
      </section>`;
  }).join("");
}

function toggleFlag(key) {
  if (state.flags.has(key)) state.flags.delete(key);
  else state.flags.add(key);
  saveFlags();
}

function link(label, url) {
  const u = safeUrl(url);
  return u ? `<li>${esc(label)}: <a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a></li>` : "";
}

function authorsHtml(r, authorNames) {
  const aa = r.author_affiliations;
  const limit = 25;
  if (!aa?.authors?.length) {
    return `<h3>Authors</h3><p>${esc(authorNames.slice(0, limit).join("; "))}${authorNames.length > limit ? ` … (+${authorNames.length - limit} more)` : ""}</p>`;
  }
  const va = new Set(r.va_affil_idx || []);
  const shown = aa.authors.slice(0, limit);
  const used = [...new Set(shown.flatMap((a) => a.aff))].sort((a, b) => a - b);
  const names = shown.map((a) => {
    const marks = a.aff.map((i) => i + 1).join(",");
    return `${esc(a.name)}${marks ? `<sup>${marks}</sup>` : ""}`;
  }).join("; ");
  const more = aa.authors.length > limit ? ` … (+${aa.authors.length - limit} more)` : "";
  const items = used.map((i) => `<li value="${i + 1}">${va.has(i) ? `<strong>${esc(aa.affiliations[i])}</strong>` : esc(aa.affiliations[i])}</li>`).join("");
  return `<h3>Authors</h3><p>${names}${more}</p>
    <h3>Affiliations</h3><ol class="affils">${items}</ol>
    <p class="muted">VA affiliations are in bold.</p>`;
}

function showDetail(r) {
  const flagged = state.flags.has(r.key);
  const ev = (r.funding_evidence || []).map((e) =>
    `<li><strong>${esc(e.label)}</strong> <span class="muted">[${esc(e.source)}]</span> ${esc(e.snippet)}</li>`).join("");
  const links = [
    link("DOI", r.doi ? `https://doi.org/${r.doi}` : null),
    link("PubMed", r.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${r.pmid}/` : null),
    link("PMC", r.pmcid ? `https://pmc.ncbi.nlm.nih.gov/articles/${r.pmcid}/` : null),
    link("Publisher", r.source_linkout),
    link("Open access copy", r.oa_url),
    link("OpenAlex", r.openalex_id ? `https://openalex.org/${r.openalex_id}` : null),
  ].join("");
  const authors = (r.authors || "").split(";").map((s) => s.trim()).filter(Boolean);
  const citedness = r.journal_citedness != null ? ` (2-yr mean citedness ${Number(r.journal_citedness).toFixed(1)})` : "";
  const funding = r.ord_funded ? `ORD funded: ${(r.ord_services || []).map(esc).join(", ")}` : r.va_funded ? "VA funded (not ORD)" : "No VA funding identified";

  $("detailBody").innerHTML = `
    <p><span class="jt ${jtClass(r.journal_tier)}">${esc(jtLabel(r.journal_tier))}</span>
      ${r.journal_tier === "Preprint" ? '<span class="tag preprint">PREPRINT · not peer reviewed</span>' : ""}
      ${r.retraction ? `<span class="tag warn">${esc(r.retraction)}</span>` : ""}</p>
    <h2>${esc(r.title)}</h2>
    <button id="detailFlag" data-key="${esc(r.key)}">${flagged ? "★ Flagged – click to unflag" : "☆ Flag for follow-up"}</button>
    <dl class="facts">
      <dt>Newsworthiness</dt><dd><strong>${esc(r.tier)}</strong> (score ${r.score})</dd>
      <dt>Journal</dt><dd>${esc(r.journal || "–")}${esc(citedness)}</dd>
      <dt>Published</dt><dd>${esc(fmtDate(r.pub_date))}</dd>
      <dt>Added to tracker</dt><dd>${esc(fmtDate(r.added))}</dd>
      <dt>Type</dt><dd>${esc(r.doc_type || r.pub_type || "–")}</dd>
      <dt>Funding</dt><dd>${funding}</dd>
      <dt>VA affiliated</dt><dd>${r.va_affiliated ? "Yes" : "No"}</dd>
    </dl>
    <h3>Why it was flagged</h3>
    <ul>${(r.score_reasons || []).map((s) => `<li>${esc(s)}</li>`).join("") || "<li>No signals</li>"}</ul>
    ${ev ? `<h3>Funding evidence</h3><ul>${ev}</ul>` : ""}
    <h3>Links</h3>
    <ul>${links || "<li>None</li>"}</ul>
    ${authorsHtml(r, authors)}
    ${r.corresponding_authors ? `<p class="muted">Corresponding: ${esc(r.corresponding_authors)}</p>` : ""}
    ${r.abstract ? `<h3>Abstract</h3><p class="abstract">${esc(r.abstract)}</p>` : ""}
    ${r.funding_text ? `<h3>Funding statement</h3><p>${esc(r.funding_text)}</p>` : ""}
    ${r.mesh_terms ? `<h3>MeSH terms</h3><p class="muted">${esc(r.mesh_terms)}</p>` : ""}
    <p class="muted">Sources: ${r.sources.map(esc).join(", ")}</p>`;
  $("detail").hidden = false;
}

const CSV_COLUMNS = [
  ["Newsworthiness", "tier"], ["Score", "score"], ["Added", "added"], ["Publication date", "pub_date"],
  ["Title", "title"], ["Journal", "journal"], ["Journal tier", "journal_tier"],
  ["Publication type", "pub_type"], ["Document type", "doc_type"],
  ["VA affiliated", "va_affiliated"], ["VA funded", "va_funded"], ["ORD funded", "ord_funded"],
  ["ORD services", "ord_services"], ["Score reasons", "score_reasons"], ["Authors", "authors"],
  ["First VA author", "first_va_author_name"], ["First VA author facility", "first_va_author_facility"],
  ["DOI", "doi"], ["PMID", "pmid"], ["PMCID", "pmcid"], ["Open access URL", "oa_url"],
  ["Publisher link", "source_linkout"], ["Sources", "sources"],
];

function csvCell(v) {
  if (Array.isArray(v)) v = v.join("; ");
  else if (typeof v === "boolean") v = v ? "Yes" : "No";
  v = v == null ? "" : String(v);
  // Stop spreadsheet apps from treating text as a formula.
  if (/^[=+\-@\t\r]/.test(v)) v = "'" + v;
  return `"${v.replace(/"/g, '""')}"`;
}

function csvField(r, f) {
  if (f === "first_va_author_name") return r.first_va_author?.name;
  if (f === "first_va_author_facility") return r.first_va_author?.facility;
  return r[f];
}

function exportView() {
  const ordered = TIERS.flatMap((t) => state.view.filter((r) => r.tier === t));
  if (!ordered.length) return showStatus("Nothing to export with the current filters.", true);
  const lines = [CSV_COLUMNS.map(([h]) => csvCell(h)).join(",")];
  for (const r of ordered) lines.push(CSV_COLUMNS.map(([, f]) => csvCell(csvField(r, f))).join(","));
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `va-research-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  showStatus("");
}

function resetFilters() {
  document.querySelectorAll("input[name=tier], input[name=jtier]").forEach((i) => (i.checked = true));
  ["vaFunded", "ordFunded", "flaggedOnly"].forEach((id) => ($(id).checked = false));
  $("hideMinor").checked = true;
  ["q", "from", "service", "source"].forEach((id) => ($(id).value = ""));
  $("sort").value = "score";
  applyFilters();
}

document.querySelector(".sidebar").addEventListener("change", applyFilters);
$("q").addEventListener("input", applyFilters);
$("sort").addEventListener("change", applyFilters);
$("reset").addEventListener("click", resetFilters);
$("export").addEventListener("click", exportView);

$("days").addEventListener("click", (e) => {
  const pill = e.target.closest("[data-day]");
  if (!pill) return;
  state.day = pill.dataset.day;
  renderDays();
  applyFilters();
});

$("sections").addEventListener("click", (e) => {
  const flag = e.target.closest(".flag");
  if (flag) {
    const card = flag.closest(".card");
    toggleFlag(card.dataset.key);
    const flagged = state.flags.has(card.dataset.key);
    card.classList.toggle("flagged", flagged);
    flag.textContent = flagged ? "★" : "☆";
    flag.setAttribute("aria-pressed", flagged);
    renderSummary();
    return;
  }
  const more = e.target.closest(".more");
  if (more) {
    state.shown[more.dataset.tier] += STEP;
    renderSections();
    return;
  }
  const head = e.target.closest(".group-head");
  if (head) {
    const tier = head.closest(".group").dataset.tier;
    state.open[tier] = !state.open[tier];
    head.closest(".group").classList.toggle("collapsed", !state.open[tier]);
    return;
  }
  const card = e.target.closest(".card");
  if (card) showDetail(state.byKey.get(card.dataset.key));
});

$("detail").addEventListener("click", (e) => {
  const btn = e.target.closest("#detailFlag");
  if (!btn) return;
  toggleFlag(btn.dataset.key);
  showDetail(state.byKey.get(btn.dataset.key));
  renderSummary();
  renderSections();
});
$("closeDetail").addEventListener("click", () => ($("detail").hidden = true));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("detail").hidden = true; });

loadData();

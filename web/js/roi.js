// Strona „ROI”: EV najbliższego losowania, EV vs kumulacja, progi gry, symulator polityki.
const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const num = (x, d = 2) => x == null ? "–" : x.toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x, d = 1) => x == null ? "–" : (x > 0 ? "+" : "") + num(100 * x, d) + "%";
const mln = x => x == null ? "–" : num(x / 1e6, x >= 1e7 ? 0 : 1) + " mln zł";
let evData = null, sim = null, charts = {};
const tile = (label, value, sub) => el("div", { class: "tile" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "sub" }, sub));

function chart(id, cfg) { charts[id]?.destroy(); charts[id] = new Chart($(id), cfg); }

async function loadEV() {
  const e = evData = await api("/api/ev");
  const n = e.next, be = e.break_even;
  const ok = n.jackpot && n.anti_popular && n.anti_popular.roi >= 0;
  $("verdict").className = "card verdict " + (ok ? "alert" : "ok");
  $("v-label").textContent = `Najbliższe losowanie · zakład ${fmt.zl(e.price)}`;
  $("v-text").textContent = !n.jackpot ? "Brak zapowiadanej kumulacji – zsynchronizuj dane"
    : ok ? `Kumulacja ${mln(n.jackpot)}: zakład ma dodatnią wartość oczekiwaną` : `Kumulacja ${mln(n.jackpot)}: gra się nie opłaca`;
  $("v-sub").textContent = n.jackpot
    ? `Z każdych ${fmt.zl(e.price)} wraca średnio ${fmt.zl(n.random.ev)} (zakład losowy) albo ${fmt.zl(n.anti_popular.ev)} (niepopularny). ` +
      `Próg opłacalności: ${mln(be.anti_popular)} dla zakładów niepopularnych, ${mln(be.random)} dla losowych. Najwyższa kumulacja od 2014 r.: ${mln(e.history.max_jackpot)}.`
    : "";
  $("kpis").replaceChildren(
    tile("ROI zakładu losowego", n.random ? pct(n.random.roi) : "–", "przy zapowiadanej kumulacji"),
    tile("ROI zakładu niepopularnego", n.anti_popular ? pct(n.anti_popular.roi) : "–", `wygrana ×${num(e.anti_multipliers.prize4)} za 4, ×${num(e.anti_multipliers.prize5)} za 5`),
    tile("Próg opłacalności", mln(be.anti_popular), `kumulacja dla zakładów niepopularnych (losowe: ${mln(be.random)})`),
    tile("Lotto Plus", pct(e.lotto_plus.roi), `EV ${fmt.zl(e.lotto_plus.ev)} za ${fmt.zl(e.lotto_plus.price)}: nie opłaca się nigdy`),
  );
  $("ev-note").textContent = `Wartość oczekiwana zakładu (${fmt.zl(e.price)}, linia przerywana) przy obecnych zasadach: trójka ${fmt.zl(e.prize3)}, mediana czwórki ${fmt.zl(e.prize4_median)} i piątki ${fmt.zl(e.prize5_median)} z ${e.recent_draws} ostatnich losowań, podatek 10%. ` +
    `Przy wyższej kumulacji rośnie sprzedaż, więc rośnie szansa podziału szóstki. Punkt: zapowiadana kumulacja.`;
  renderEV();
}

function renderEV() {
  const e = evData, text = css("--muted");
  const xs = e.curve.map(c => c.jackpot / 1e6);
  const pts = (key) => e.curve.map(c => ({ x: c.jackpot / 1e6, y: c[key] }));
  const datasets = [
    { label: "Zakład niepopularny", data: pts("ev_anti"), borderColor: css("--series-2"), backgroundColor: css("--series-2"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
    { label: "Zakład losowy", data: pts("ev"), borderColor: css("--series-1"), backgroundColor: css("--series-1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
    { label: `Cena zakładu (${fmt.zl(e.price)})`, data: [{ x: xs[0], y: e.price }, { x: xs[xs.length - 1], y: e.price }], borderColor: css("--ref"), borderDash: [6, 4], borderWidth: 2, pointRadius: 0 },
  ];
  if (e.next.jackpot) datasets.push({ label: "_Zapowiadana kumulacja", type: "scatter", data: [{ x: e.next.jackpot / 1e6, y: e.next.anti_popular.ev }],
    backgroundColor: css("--series-2"), borderColor: css("--surface"), borderWidth: 2, pointRadius: 7, pointHoverRadius: 8 });
  chart("c-ev", {
    type: "line", data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: true,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 14, boxHeight: 2, filter: i => !i.text.startsWith("_") } },
        tooltip: { callbacks: { title: it => `Kumulacja ${num(it[0].parsed.x, 0)} mln zł`, label: c => `${c.dataset.label.replace(/^_/, "")}: ${fmt.zl(c.parsed.y)}` } } },
      scales: {
        x: { type: "linear", title: { display: true, text: "kumulacja (mln zł)", color: text }, ticks: { color: text }, grid: { display: false } },
        y: { title: { display: true, text: "EV zakładu (zł)", color: text }, ticks: { color: text }, grid: { color: css("--grid") }, border: { display: false } },
      },
    },
  });
}

async function loadGrid() {
  const rows = await api("/api/roi/grid?period=" + $("g-period").value);
  const by = {};
  rows.forEach(r => { (by[r.min_jackpot] ??= {})[r.strategy] = r; });
  const any = rows[0];
  $("grid-note").textContent = `ROI oczekiwane przy faktycznych poziomach wygranych i odtworzonej kumulacji w ${fmt.int(any.draws_available)} losowaniach. Ceny i zasady z dnia każdego losowania.`;
  $("grid").replaceChildren(...Object.entries(by).map(([thr, s]) => el("tr", {},
    el("td", {}, Number(thr) ? mln(Number(thr)) : "każde losowanie"),
    el("td", { class: "num" }, fmt.int(s.random.draws_played)),
    el("td", { class: "num" }, pct(s.random.roi)),
    el("td", { class: "num" + (s.anti_popular.roi > 0 ? " sig" : "") }, pct(s.anti_popular.roi)),
    el("td", { class: "num hide-sm" }, s.anti_popular.net_per_year == null ? "–" : (s.anti_popular.net_per_year > 0 ? "+" : "") + fmt.zl(s.anti_popular.net_per_year)))));
}

async function simulate() {
  const body = { strategy: $("strategy").value, tickets: Number($("tickets").value), min_jackpot: Number($("minj").value) * 1e6,
    monthly_budget: $("budget").value ? Number($("budget").value) : null, lotto_plus: $("plus").value === "1", period: $("period").value };
  $("sim-btn").disabled = true;
  $("status").textContent = "Symuluję…";
  try {
    const r = await fetch("/api/roi", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    sim = data;
    renderSim();
    $("status").textContent = "";
  } catch (e) { $("status").textContent = "Błąd: " + e.message; }
  finally { $("sim-btn").disabled = false; }
}

function renderSim() {
  const r = sim;
  $("sim").hidden = false;
  if (!r.draws_played) {
    $("sim-kpis").replaceChildren(tile("Rozegrane losowania", "0", "żadne losowanie nie spełniło warunków"));
    $("sim-note").textContent = "";
    charts["c-sim"]?.destroy();
    return;
  }
  const e = r.expected, z = r.realized;
  $("sim-kpis").replaceChildren(
    tile("Rozegrane losowania", fmt.int(r.draws_played), `z ${fmt.int(r.draws_available)} · ${fmt.date(r.range[0])} – ${fmt.date(r.range[1])}`),
    tile("Koszt", fmt.zl(r.cost), `${fmt.zl(r.cost_per_year)} rocznie`),
    tile("ROI oczekiwane", pct(e.roi), `netto ${fmt.zl(e.net)} (${fmt.zl(e.net_per_year)} rocznie)`),
    tile("ROI zrealizowane", pct(z.roi), `H0: mediana ${pct(z.roi_h0_median)}, 95%: ${pct(z.roi_h0_ci[0], 0)}…${pct(z.roi_h0_ci[1], 0)}`),
    tile("Największe obsunięcie", fmt.zl(z.max_drawdown), "spadek salda od szczytu"),
    tile("Trafienia 3 / 4 / 5 / 6", z.tiers.map(t => t.observed).join(" / "), "w rozegranych losowaniach"),
  );
  $("sim-note").textContent = z.lotto_plus_note || "";
  const c = z.curve, text = css("--muted"), band = css("--ref");
  chart("c-sim", {
    type: "line",
    data: { labels: c.dates.map(fmt.date), datasets: [
      { label: "_lo", data: c.h0_lo, borderColor: "transparent", pointRadius: 0, fill: false },
      { label: "H0: 90% wyników", data: c.h0_hi, borderColor: "transparent", backgroundColor: band + "33", pointRadius: 0, fill: "-1" },
      { label: "H0: mediana", data: c.h0_median, borderColor: band, borderDash: [6, 4], borderWidth: 2, pointRadius: 0 },
      { label: "Polityka", data: c.net, borderColor: css("--series-1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 14, boxHeight: 2, filter: i => !i.text.startsWith("_") } },
        tooltip: { filter: i => i.datasetIndex > 1, callbacks: { label: x => `${x.dataset.label}: ${fmt.zl(x.parsed.y)}` } } },
      scales: { x: { ticks: { color: text, maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } },
        y: { title: { display: true, text: "saldo (zł)", color: text }, ticks: { color: text }, grid: { color: css("--grid") }, border: { display: false } } },
    },
  });
}

$("sim-btn").addEventListener("click", simulate);
$("g-period").addEventListener("change", loadGrid);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { evData && renderEV(); sim && renderSim(); });
loadEV();
loadGrid();
simulate();

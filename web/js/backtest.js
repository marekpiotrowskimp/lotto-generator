// Strona „Backtest”: uruchamianie strategii, wynik na tle H0, porównanie strategii.
const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const num = (x, d = 3) => x == null || Number.isNaN(x) ? "–" : x.toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pval = p => p == null ? "–" : p < 0.001 ? "< 0,001" : num(p, 3);
const pct = (x, d = 1) => x == null ? "–" : (x > 0 ? "+" : "") + num(100 * x, d) + "%";
let strategies = [], chart = null, last = null;

async function init() {
  strategies = await api("/api/strategies");
  $("strategy").replaceChildren(...strategies.map(s => el("option", { value: s.name }, s.label)));
  $("strategy").addEventListener("change", renderParams);
  renderParams();
  fromHash();
}

// Ustawienia w adresie strony: #strategy=hot&window=50&tickets=5&period=test&compare=1
function fromHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (![...h.keys()].length) return;
  if (h.has("strategy") && strategies.some(s => s.name === h.get("strategy"))) { $("strategy").value = h.get("strategy"); renderParams(); }
  for (const k of ["tickets", "period", "sims", "seed"]) if (h.has(k)) $(k).value = h.get(k);
  for (const [k, v] of h) if ($("p-" + k)) $("p-" + k).value = v;
  if (h.get("compare") === "1") compare(); else run();
}

function toHash(q) {
  const h = new URLSearchParams({ strategy: q.strategy, ...q.params, tickets: q.tickets, period: q.period, sims: q.sims, seed: q.seed });
  history.replaceState(null, "", "#" + h);
}

function renderParams() {
  const s = strategies.find(x => x.name === $("strategy").value);
  $("strategy-desc").textContent = s.description;
  $("params").replaceChildren(...s.params.map(p => el("label", {}, p.label,
    el("input", { type: "number", id: "p-" + p.name, min: p.min, max: p.max, value: p.default, step: Number.isInteger(p.default) ? 1 : "any" }))));
}

function request() {
  const s = strategies.find(x => x.name === $("strategy").value);
  const params = Object.fromEntries(s.params.map(p => [p.name, Number($("p-" + p.name).value)]));
  return { strategy: s.name, params, tickets: Number($("tickets").value), period: $("period").value,
           sims: Number($("sims").value), seed: Number($("seed").value) };
}

async function busy(label, fn) {
  $("run-btn").disabled = $("cmp-btn").disabled = true;
  $("status").textContent = label;
  try { await fn(); $("status").textContent = ""; }
  catch (e) { $("status").textContent = "Błąd: " + e.message; }
  finally { $("run-btn").disabled = $("cmp-btn").disabled = false; }
}

async function run() {
  await busy("Liczę…", async () => {
    const q = request();
    toHash(q);
    const r = await fetch("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(q) });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || r.status);
    last = body;
    render(body);
  });
}

function render(r) {
  $("result").hidden = false;
  const better = r.beats_random, m = r.money;
  $("verdict").className = "card verdict " + (better ? "alert" : "ok");
  $("v-label").textContent = `${r.strategy.label} · ${r.period === "test" ? "okres testowy" : "okres treningowy"} ${fmt.date(r.range[0])} – ${fmt.date(r.range[1])}`;
  $("v-text").textContent = better ? "Trafia częściej niż losowość" : "Nie trafia częściej niż losowość";
  $("v-sub").textContent = `Średnio ${num(r.mean_hits, 4)} trafień na zakład; przy H0 ${num(r.mean_hits_h0, 4)} (95%: ${num(r.mean_hits_ci[0], 4)}–${num(r.mean_hits_ci[1], 4)}), p = ${pval(r.p_mean_hits)}. ` +
    (better ? "Uwaga: przy wielu próbach część „sukcesów” to przypadek. Sprawdź wynik w porównaniu z korektą." : "") +
    ` · ${r.sims} symulacji · ${r.runtime_s} s`;

  const tile = (label, value, sub) => el("div", { class: "tile" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "sub" }, sub));
  $("kpis").replaceChildren(
    tile("Zakłady", fmt.int(r.tickets), `${fmt.int(r.draws)} losowań × ${r.tickets_per_draw}`),
    tile("Wygrane (≥ 3 trafienia)", fmt.int(r.wins_ge3), `przy H0 95%: ${num(r.wins_ge3_ci[0], 0)}–${num(r.wins_ge3_ci[1], 0)}`),
    tile("Koszt / wygrane", `${fmt.zl(m.cost)}`, `wygrane netto: ${fmt.zl(m.winnings)}`),
    tile("ROI", m.roi == null ? "–" : pct(m.roi), m.roi == null ? "brak danych o wygranych" : `H0: mediana ${pct(m.roi_h0_median)}, 95%: ${pct(m.roi_h0_ci[0], 0)}…${pct(m.roi_h0_ci[1], 0)}`),
  );

  $("tiers").replaceChildren(...r.tiers.map(t => el("tr", {},
    el("td", {}, String(t.hits)), el("td", { class: "num" }, fmt.int(t.observed)),
    el("td", { class: "num" }, num(t.expected, 1)), el("td", { class: "num" }, `${num(t.ci[0], 0)}–${num(t.ci[1], 0)}`))));

  $("best").replaceChildren(...(r.best_draws.length ? r.best_draws.map(b => {
    const drawn = new Set(b.numbers);
    return el("tr", {}, el("td", {}, String(b.draw_no)), el("td", {}, fmt.date(b.date)),
      el("td", {}, el("span", { class: "balls" }, ...b.ticket.map(n => el("span", { class: drawn.has(n) ? "ball" : "ball plain" }, String(n))))),
      el("td", {}, balls(b.numbers, true)), el("td", { class: "num" }, String(b.hits)), el("td", { class: "num" }, fmt.zl(b.won)));
  }) : [el("tr", {}, el("td", { colspan: 6, class: "muted" }, "Brak losowań z co najmniej 3 trafieniami."))]));

  renderCurve(r);
}

function renderCurve(r) {
  if (chart) chart.destroy();
  const c = r.curve, text = css("--muted"), band = css("--ref");
  chart = new Chart($("c-curve"), {
    type: "line",
    data: { labels: c.dates.map(fmt.date), datasets: [
      { label: "H0: 5. percentyl", data: c.h0_lo, borderColor: "transparent", pointRadius: 0, fill: false },
      { label: "H0: 90% wyników", data: c.h0_hi, borderColor: "transparent", backgroundColor: band + "33", pointRadius: 0, fill: "-1" },
      { label: "H0: mediana", data: c.h0_median, borderColor: band, borderDash: [6, 4], borderWidth: 2, pointRadius: 0 },
      { label: r.strategy.label, data: c.net, borderColor: css("--series-1"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: text, boxWidth: 14, boxHeight: 2, filter: i => i.datasetIndex > 0 } },
        tooltip: { filter: i => i.datasetIndex > 1, callbacks: { label: ctx => `${ctx.dataset.label}: ${fmt.zl(ctx.parsed.y)}` } },
      },
      scales: {
        x: { ticks: { color: text, maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } },
        y: { title: { display: true, text: "saldo (zł)", color: text }, ticks: { color: text }, grid: { color: css("--grid") }, border: { display: false } },
      },
    },
  });
}

async function compare() {
  await busy("Porównuję wszystkie strategie (około minuty)…", async () => {
    const q = request();
    const rows = await api(`/api/backtest/compare?tickets=${q.tickets}&period=${q.period}&sims=${Math.min(q.sims, 2000)}`, { method: "POST" });
    $("compare").hidden = false;
    $("cmp-note").textContent = `${rows[0].period === "test" ? "Okres testowy" : "Okres treningowy"} ${fmt.date(rows[0].range[0])} – ${fmt.date(rows[0].range[1])}, ${q.tickets} zakł. na losowanie, parametry domyślne. ` +
      `Przy ${rows.length} porównaniach wartość p mnożymy przez ${rows.length} (Bonferroni), żeby przypadkowy „sukces” jednej strategii nie wyglądał na odkrycie.`;
    $("cmp").replaceChildren(...rows.map(r => el("tr", {},
      el("td", {}, r.strategy.label),
      el("td", { class: "num" }, num(r.mean_hits, 4)),
      el("td", { class: "num" }, `${num(r.mean_hits_ci[0], 3)}–${num(r.mean_hits_ci[1], 3)}`),
      el("td", { class: "num" }, pval(r.p_mean_hits)),
      el("td", { class: "num" }, pval(r.p_mean_hits_bonf)),
      el("td", { class: "num" }, fmt.int(r.wins_ge3)),
      el("td", { class: "num" }, r.money.roi == null ? "–" : pct(r.money.roi)),
      el("td", { class: "num hide-sm" }, r.money.roi_h0_median == null ? "–" : pct(r.money.roi_h0_median)),
      el("td", {}, el("span", { class: "pill " + (r.beats_random_corrected ? "confirmed" : "none") }, r.beats_random_corrected ? "lepsza" : "jak losowa")))));
  });
}

$("run-btn").addEventListener("click", run);
$("cmp-btn").addEventListener("click", compare);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => last && renderCurve(last));
init();

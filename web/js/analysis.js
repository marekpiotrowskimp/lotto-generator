// Strona „Analiza”: werdykt H0, wykresy detektorów, tabela hipotez, moc, walidacja.
const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const VERDICT = { confirmed: "potwierdzona", train_only: "tylko train", none: "brak" };
let report = null;
let charts = [];

const num = (x, d = 3) => x == null || Number.isNaN(x) ? "–" : x.toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pval = p => p == null ? "–" : p < 0.001 ? "< 0,001" : num(p, 3);
const pct = (x, d = 1) => x == null ? "–" : (x > 0 ? "+" : "") + num(100 * x, d) + "%";

function plural(n, one, few, many) {
  if (n === 1) return one;
  const d = n % 10, dd = n % 100;
  return d >= 2 && d <= 4 && !(dd >= 12 && dd <= 14) ? few : many;
}

function effectText(h, eff) {
  if (eff == null) return "–";
  return /względn/.test(h.effect_label) ? pct(eff) : num(eff, 3);
}

// --- wykresy -------------------------------------------------------------------

function baseOptions(xTitle, yTitle, extra = {}) {
  const text = css("--muted"), grid = css("--grid");
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: text, boxWidth: 14, boxHeight: 2, filter: i => !i.text.startsWith("_") } },
      tooltip: { callbacks: {} },
    },
    scales: {
      x: { title: { display: !!xTitle, text: xTitle, color: text }, ticks: { color: text, autoSkip: true, maxRotation: 0 }, grid: { display: false } },
      y: { title: { display: !!yTitle, text: yTitle, color: text }, ticks: { color: text }, grid: { color: grid }, border: { display: false } },
    },
    ...extra,
  };
}

const refLine = (label, data, dash = [6, 4]) => ({
  type: "line", label, data, borderColor: css("--ref"), borderWidth: 2, borderDash: dash,
  pointRadius: 0, pointHoverRadius: 0, fill: false, order: 0,
});

const bars = (label, data, color) => ({
  type: "bar", label, data, backgroundColor: color || css("--series-1"),
  borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start",
  categoryPercentage: 0.85, barPercentage: 0.9, order: 1,
});

function make(id, config) {
  const c = new Chart($(id), config);
  charts.push(c);
  return c;
}

function renderCharts() {
  charts.forEach(c => c.destroy());
  charts = [];
  const ch = report.charts;

  // częstość liczb: odchylenie od oczekiwanej w odchyleniach standardowych (słupki od zera)
  const f = ch.frequency, labels = f.counts.map((_, i) => String(i + 1));
  const z = f.counts.map(c => (c - f.expected) / f.sd);
  const lim = Math.max(3, Math.ceil(Math.max(...z.map(Math.abs))));
  make("c-freq", {
    data: { labels, datasets: [
      { ...bars("Odchylenie liczby wystąpień (σ)", z), borderRadius: 4, borderSkipped: false },
      refLine("±2σ (przedział typowy przy H0)", labels.map(() => 2), [2, 3]),
      refLine("_-2σ", labels.map(() => -2), [2, 3]),
    ] },
    options: baseOptions("liczba", "odchylenie (σ)", {
      plugins: { legend: { labels: { color: css("--muted"), boxWidth: 14, boxHeight: 2, filter: i => !i.text.startsWith("_") } },
        tooltip: { filter: i => i.datasetIndex === 0, callbacks: {
          label: ctx => `wystąpień: ${fmt.int(f.counts[ctx.dataIndex])} (oczekiwane ${num(f.expected, 0)}, ${z[ctx.dataIndex] > 0 ? "+" : ""}${num(z[ctx.dataIndex], 2)}σ)` } } },
      scales: { ...baseOptions().scales,
        x: { ...baseOptions("liczba").scales.x, ticks: { color: css("--muted"), autoSkip: innerWidth < 900, maxRotation: 0, font: { size: 10 } } },
        y: { ...baseOptions("", "odchylenie (σ)").scales.y, min: -lim, max: lim } },
    }),
  });

  // przerwy
  const g = ch.gaps, gl = g.observed.map((_, i) => i + 1 === g.observed.length ? `${i + 1}+` : String(i + 1));
  make("c-gaps", {
    data: { labels: gl, datasets: [bars("Obserwowane", g.observed), refLine("Oczekiwane (geometryczny)", g.expected)] },
    options: baseOptions("przerwa (losowań)", "liczba przerw"),
  });

  // powtórki
  const r = ch.repeats;
  make("c-repeats", {
    data: { labels: r.observed.map((_, i) => String(i)), datasets: [
      bars("Obserwowane", r.observed),
      { ...refLine("Oczekiwane (H0)", r.expected), pointRadius: 5, pointHoverRadius: 6, pointBackgroundColor: css("--ref"), borderWidth: 0, showLine: false },
    ] },
    options: baseOptions("wspólnych liczb z poprzednim losowaniem", "losowań"),
  });

  // odstępy
  const L = ch.lags;
  const lagSeries = {
    type: "line", label: "Średnia obserwowana", data: L.rows.map(x => x.mean),
    borderColor: css("--series-1"), backgroundColor: css("--series-1"), borderWidth: 2,
    pointRadius: 4, pointHoverRadius: 6, pointBorderColor: css("--surface"), pointBorderWidth: 2, order: 1,
  };
  make("c-lags", {
    data: { labels: L.rows.map(x => String(x.lag)), datasets: [
      lagSeries,
      refLine("H0 (36/49)", L.rows.map(() => L.h0)),
      refLine("95% przedział H0", L.rows.map(x => L.h0 + x.ci), [2, 3]),
      refLine("_dolny", L.rows.map(x => L.h0 - x.ci), [2, 3]),
    ] },
    options: baseOptions("odstęp k (losowań)", "średnio wspólnych liczb"),
  });

  // pozycje kul
  const P = ch.positions;
  if (P.means.length) {
    $("pos-note").textContent = `Średnia wartość kuli wylosowanej jako 1., 2., … 6. (${fmt.int(P.n)} losowań od 2004 r.). Pas: 95% przedział przy H0 (25).`;
    make("c-pos", {
      data: { labels: P.means.map((_, i) => `${i + 1}.`), datasets: [
        { ...lagSeries, label: "Średnia wartość kuli", data: P.means },
        refLine("H0 (25)", P.means.map(() => P.h0)),
        refLine("95% przedział H0", P.means.map(() => P.h0 + P.ci), [2, 3]),
        refLine("_dolny", P.means.map(() => P.h0 - P.ci), [2, 3]),
      ] },
      options: baseOptions("pozycja w kolejności losowania", "średnia wartość"),
    });
  }

  // model vs permutacje
  const ml = report.hypotheses.find(h => h.id === "ml.logistic");
  if (ml && ml.test.extra.null_gain_per_10k.length) {
    const nulls = ml.test.extra.null_gain_per_10k, obs = ml.test.stat;
    const lo = Math.min(...nulls, obs), hi = Math.max(...nulls, obs), B = 20, w = (hi - lo) / B || 1;
    const counts = Array(B).fill(0);
    nulls.forEach(v => counts[Math.min(B - 1, Math.floor((v - lo) / w))]++);
    const obsBin = Math.min(B - 1, Math.floor((obs - lo) / w));
    const labelsMl = counts.map((_, i) => num(lo + (i + 0.5) * w, 2));
    const colors = counts.map((_, i) => i === obsBin ? css("--series-2") : css("--series-1"));
    $("ml-note").textContent = `Zysk modelu względem 6/49 na danych testowych (log-loss ×10⁴; > 0 = lepszy od losowości). ` +
      `Pomarańczowy słupek: prawdziwy wynik ${num(obs, 2)}; niebieskie: ${nulls.length} permutacji bez struktury w czasie. p = ${pval(ml.test.p)}.`;
    make("c-ml", {
      data: { labels: labelsMl, datasets: [{ ...bars("Permutacje", counts), backgroundColor: colors }] },
      options: baseOptions("zysk modelu (log-loss ×10⁴)", "liczba permutacji", {
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          afterLabel: ctx => ctx.dataIndex === obsBin ? "← w tym przedziale wynik prawdziwego modelu" : "" } } },
      }),
    });
  }
}

// --- werdykt, KPI, grupy ----------------------------------------------------------

function renderSummary() {
  const s = report.summary, d = report.data, p = report.params;
  const rejected = s.h0_rejected;
  $("verdict").className = "card verdict " + (rejected ? "alert" : "ok");
  $("v-text").textContent = rejected ? `H0 odrzucona: potwierdzone anomalie (${s.n_confirmed})` : "Brak podstaw do odrzucenia H0";
  $("v-sub").textContent = `Raport z ${report.generated_at.replace("T", " ")} · ostatnie losowanie nr ${d.last_draw_no ?? "–"} · ` +
    `${p.sims} symulacji Monte Carlo, ${p.perms} permutacji · ${report.runtime_s} s`;

  const tile = (label, value, sub) => el("div", { class: "tile" },
    el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "sub" }, sub));
  $("kpis").replaceChildren(
    tile("Dane treningowe", fmt.int(d.n_train), `${fmt.date(d.train_range[0])} – ${fmt.date(d.train_range[1])}`),
    tile("Dane testowe", fmt.int(d.n_test), `${fmt.date(d.test_range[0])} – ${fmt.date(d.test_range[1])}`),
    tile("Hipotez", fmt.int(s.n_hypotheses), `p ≤ 0,05 na train: ${s.n_train_p05} (przy H0 ~${num(s.expected_false_train_p05, 0)})`),
    tile("Istotne / potwierdzone", `${s.n_selected_train} / ${s.n_confirmed}`, "na train po korekcie / na test"),
  );

  $("v-explain").textContent = rejected
    ? "Co najmniej jedna anomalia przeszła wykrycie na danych treningowych i potwierdzenie na niezależnych danych testowych. Sprawdź ją w tabeli hipotez i na wykresach; to kandydat do strategii „discovered” (etap 5)."
    : `Na danych treningowych ${s.n_train_p05} z ${s.n_hypotheses - 1} testów ma p ≤ 0,05; przy prawdziwej H0 spodziewamy się około ${num(s.expected_false_train_p05, 0)} takich wyników przez przypadek. ` +
      `Po korekcie na wielokrotne porównania istotnych zostaje ${s.n_selected_train}. Model przewidujący nie pobija losowości. Losowania zachowują się jak losowe w granicach mocy testów (tabela „Moc testów”).`;

  $("groups").replaceChildren(...Object.entries(s.groups).map(([name, g]) => el("div", { class: "card" },
    el("h3", {}, name),
    el("div", { class: "big" }, g.confirmed ? `${g.confirmed} potwierdzone` : "brak anomalii"),
    el("div", { class: "muted small" }, `${g.tests} ${plural(g.tests, "test", "testy", "testów")} · najmniejsze p (train): ${pval(g.min_p_train)} · istotne na train: ${g.selected}`),
  )));
}

function renderHypotheses() {
  const fg = $("f-group").value, fs = $("f-show").value;
  let rows = report.hypotheses.filter(h => !fg || h.group === fg);
  if (fs === "p05") rows = rows.filter(h => h.train && h.train.p <= 0.05);
  if (fs === "selected") rows = rows.filter(h => h.selected && h.train);
  rows.sort((a, b) => (a.train ? a.train.p : (a.test ? a.test.p : 1)) - (b.train ? b.train.p : (b.test ? b.test.p : 1)));
  $("h-count").textContent = rows.length;
  $("hyps").replaceChildren(...rows.map(h => el("tr", {},
    el("td", {}, el("span", { class: "hyp-group" }, h.group), h.name),
    el("td", { class: "hide-sm muted small" }, h.method),
    el("td", { class: "num", title: h.effect_label }, effectText(h, h.train ? h.train.effect : h.test && h.test.effect)),
    el("td", { class: "num" + (h.train && h.train.p <= 0.05 ? " sig" : "") }, h.train ? pval(h.train.p) : "–"),
    el("td", { class: "num" + (h.train && h.train.q <= report.params.alpha ? " sig" : "") }, h.train ? pval(h.train.q) : "–"),
    el("td", { class: "num" }, h.test ? pval(h.test.p) : "–"),
    el("td", {}, el("span", { class: "pill " + h.verdict }, VERDICT[h.verdict])),
  )));
}

function renderPower() {
  $("power").replaceChildren(...report.power.map(p => el("tr", {},
    el("td", {}, p.test), el("td", { class: "num" }, "±" + num(100 * p.min_effect, 1) + "%"),
    el("td", { class: "num hide-sm" }, "±" + num(100 * p.single_stage_full, 1) + "%"),
    el("td", { class: "hide-sm muted small" }, p.unit))));
}

async function loadValidation() {
  let v;
  try { v = await api("/api/validation"); } catch { return; }
  const fa = v.false_alarms;
  const ok = fa.rate_any_confirmed <= v.params.alpha;
  $("validation").replaceChildren(
    el("p", {}, el("span", { class: "pill " + (ok ? "none" : "train_only") }, ok ? "OK" : "UWAGA"), " ",
      `Fałszywe alarmy: ${num(100 * fa.rate_any_confirmed, 0)}% z ${fa.reps} symulowanych historii zgodnych z H0 dało „potwierdzoną” anomalię (cel ≤ ${num(100 * v.params.alpha, 0)}%). ` +
      `Odsetek p ≤ 0,05: ${num(100 * fa.share_p_le_005, 1)}% (cel ≈ 5%).`),
    el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Wstrzyknięta anomalia"), el("th", { class: "num" }, "Efekt"), el("th", { class: "num" }, "Wykryto"), el("th", { class: "num hide-sm" }, "Powtórzeń"))),
      el("tbody", {}, ...v.positive_control.map(s => el("tr", {},
        el("td", {}, s.scenario), el("td", { class: "num" }, s.effect == null ? "–" : pct(s.effect)),
        el("td", { class: "num" }, num(100 * s.detected_target, 0) + "%"), el("td", { class: "num hide-sm" }, String(s.reps))))))),
    el("p", { class: "muted small" }, `Walidacja z ${v.generated_at.replace("T", " ")}, ${v.params.sims} symulacji Monte Carlo na powtórzenie.`),
  );
}

// --- uruchamianie zadań ---------------------------------------------------------------

function showJob(prefix, j) {
  $(prefix + "-btn").disabled = j.running;
  $(prefix + "-progress").hidden = !j.running;
  if (j.running) {
    $(prefix + "-bar").style.width = (j.total ? Math.round(100 * j.done / j.total) : 3) + "%";
    $(prefix + "-text").textContent = j.total ? `${j.phase}: ${j.done} / ${j.total}` : `${j.phase}…`;
  }
  if (j.error) { $(prefix + "-progress").hidden = false; $(prefix + "-text").textContent = "Błąd: " + j.error; }
}

async function poll() {
  const s = await api("/api/analysis/status");
  showJob("run", s.analysis);
  showJob("val", s.validation);
  if (s.analysis.running || s.validation.running) setTimeout(poll, 1000);
  if (!s.analysis.running && s.analysis.finished_at && s.analysis.finished_at !== poll.lastA) { poll.lastA = s.analysis.finished_at; await load(); }
  if (!s.validation.running && s.validation.finished_at && s.validation.finished_at !== poll.lastV) { poll.lastV = s.validation.finished_at; await loadValidation(); }
}

async function load() {
  try {
    report = await api("/api/analysis");
  } catch {
    $("v-text").textContent = "Brak raportu";
    $("v-sub").textContent = "Uruchom analizę (około 1,5 minuty).";
    return;
  }
  const groups = [...new Set(report.hypotheses.map(h => h.group))];
  $("f-group").replaceChildren(el("option", { value: "" }, "Wszystkie grupy"), ...groups.map(g => el("option", { value: g }, g)));
  renderSummary();
  renderHypotheses();
  renderPower();
  renderCharts();
}

$("run-btn").addEventListener("click", async () => { await api("/api/analysis/run", { method: "POST" }); poll(); });
$("val-btn").addEventListener("click", async () => { await api("/api/validation/run", { method: "POST" }); poll(); });
$("f-group").addEventListener("change", renderHypotheses);
$("f-show").addEventListener("change", renderHypotheses);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => report && renderCharts());

load().then(loadValidation).then(poll);

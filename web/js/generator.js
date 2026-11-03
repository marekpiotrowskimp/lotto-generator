// Strona „Generator”: kupon na najbliższe losowanie, pokrycie puli, popularność liczb.
const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const num = (x, d = 2) => x == null ? "–" : x.toLocaleString("pl-PL", { minimumFractionDigits: d, maximumFractionDigits: d });
let strategies = [], last = null, chart = null;

async function init() {
  [strategies] = await Promise.all([api("/api/strategies")]);
  const g = await api("/api/wheel/guarantees");
  $("strategy").replaceChildren(...strategies.map(s => el("option", { value: s.name }, s.label)));
  $("strategy").value = "anti_popular";
  $("guarantee").append(...g.map(x => el("option", { value: x.id }, x.label)));
  $("strategy").addEventListener("change", renderParams);
  $("guarantee").addEventListener("change", toggleWheel);
  renderParams();
  toggleWheel();
  generate();
}

function renderParams() {
  const s = strategies.find(x => x.name === $("strategy").value);
  $("strategy-desc").textContent = s.description;
  $("params").replaceChildren(...s.params.map(p => el("label", {}, p.label,
    el("input", { type: "number", id: "p-" + p.name, min: p.min, max: p.max, value: p.default }))));
}

function toggleWheel() {
  const on = !!$("guarantee").value;
  $("tickets-label").hidden = on;
  $("pool-size-label").hidden = $("pool-label").hidden = !on;
}

async function generate() {
  const s = strategies.find(x => x.name === $("strategy").value);
  const body = {
    strategy: s.name, params: Object.fromEntries(s.params.map(p => [p.name, Number($("p-" + p.name).value)])),
    tickets: Number($("tickets").value), guarantee: $("guarantee").value || null,
    wheel_pool: $("guarantee").value ? Number($("pool-size").value) : null,
    pool: $("pool").value.trim() ? $("pool").value.split(/[^0-9]+/).filter(Boolean).map(Number) : null,
  };
  $("gen-btn").disabled = true;
  $("status").textContent = "Generuję…";
  try {
    const r = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    last = data;
    render(data);
    $("status").textContent = "";
  } catch (e) { $("status").textContent = "Błąd: " + e.message; }
  finally { $("gen-btn").disabled = false; }
}

function render(r) {
  $("result").hidden = false;
  const tile = (label, value, sub) => el("div", { class: "tile" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "sub" }, sub));
  const avg4 = r.tickets.reduce((a, t) => a + t.prize_mult4, 0) / r.tickets.length;
  $("kpis").replaceChildren(
    tile("Losowanie", fmt.date(r.draw_date), `po losowaniu nr ${r.last_draw_no}`),
    tile("Zakładów", fmt.int(r.tickets.length), r.guarantee ? `system z puli ${r.pool.length} liczb` : r.strategy.label),
    tile("Koszt", r.cost == null ? "–" : fmt.zl(r.cost), r.price ? `${fmt.zl(r.price)} za zakład` : ""),
    tile("Wygrana za 4 przy trafieniu", "×" + num(avg4), "średnio względem przeciętnego zakładu"),
  );
  $("pool-info").textContent = r.pool
    ? `Pula: ${r.pool.join(", ")}. Gwarancja sprawdzona na wszystkich kombinacjach puli. Pełny system: ${fmt.int(r.full_system_size)} zakładów (${fmt.zl(r.full_system_size * r.price)}).`
    : "";
  $("tickets-body").replaceChildren(...r.tickets.map((t, i) => el("tr", {},
    el("td", { class: "muted" }, String(i + 1)),
    el("td", {}, el("span", { class: "ticket-cell" }, balls(t.numbers), copyButton(t.numbers.join(" ")))),
    el("td", { class: "num" }, t.rarer_than >= 0.999 ? "> 99,9%" : num(100 * t.rarer_than, 1) + "%"),
    el("td", { class: "num" }, "×" + num(t.prize_mult4)),
    el("td", { class: "num hide-sm" }, "×" + num(t.prize_mult5)))));
  renderPopularity(r);
}

function renderPopularity(r) {
  if (chart) chart.destroy();
  const beta = r.number_popularity, rel = beta.map(b => 100 * (Math.exp(b) - 1));
  const pm = r.popularity_model;
  $("pop-note").textContent = `Szacowana zmiana liczby graczy typujących liczbę względem przeciętnej (model z liczby zwycięzców, 2014–2026). ` +
    `Sprawdzian poza próbą (${pm.n_test} losowań 2021–2026, model z ${pm.n_train} wcześniejszych): korelacja ${num(pm.corr_combo_test)}, ${pm.p_corr_combo < 0.001 ? "p < 0,001" : "p = " + num(pm.p_corr_combo, 3)}. ` +
    `Mediana wygranej za 4: ${fmt.zl(pm.prize4_unpopular)} w losowaniach z najmniej popularnymi liczbami vs ${fmt.zl(pm.prize4_popular)} z najpopularniejszymi.`;
  const text = css("--muted");
  chart = new Chart($("c-pop"), {
    type: "bar",
    data: { labels: rel.map((_, i) => String(i + 1)), datasets: [{
      label: "Popularność", data: rel, borderRadius: 4, borderSkipped: false,
      backgroundColor: rel.map(v => v >= 0 ? css("--series-2") : css("--series-1")),
      categoryPercentage: 0.85, barPercentage: 0.9,
    }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: items => `Liczba ${items[0].label}`,
        label: ctx => `${ctx.parsed.y >= 0 ? "+" : ""}${num(ctx.parsed.y, 1)}% graczy względem przeciętnej` } } },
      scales: {
        x: { ticks: { color: text, autoSkip: innerWidth < 900, maxRotation: 0, font: { size: 10 } }, grid: { display: false } },
        y: { title: { display: true, text: "popularność (%)", color: text }, ticks: { color: text }, grid: { color: css("--grid") }, border: { display: false } },
      },
    },
  });
}

// Kopiowanie: Clipboard API, a gdy odmówi (np. karta bez fokusu po powrocie z innej karty)
// zapasowo przez zaznaczenie ukrytego pola. Potwierdzenie na samym przycisku.
async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* zapasowo niżej */ }
  const ta = el("textarea", { readonly: "", style: "position:fixed;top:0;left:0;opacity:0" }, text);
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

async function copyWithFeedback(button, text) {
  const label = button.dataset.label || (button.dataset.label = button.textContent);
  const ok = await copy(text);
  button.textContent = ok ? "Skopiowano ✓" : "Nie udało się";
  clearTimeout(button._t);
  button._t = setTimeout(() => { button.textContent = label; }, 1500);
  if (!ok) $("status").textContent = "Przeglądarka zablokowała schowek. Zaznacz liczby i skopiuj ręcznie (Cmd+C).";
}

function copyButton(text) {
  const b = el("button", { class: "secondary small-btn", type: "button", title: "Kopiuj ten zakład" }, "Kopiuj");
  b.addEventListener("click", () => copyWithFeedback(b, text));
  return b;
}

function csv() {
  const rows = [["zaklad", "n1", "n2", "n3", "n4", "n5", "n6", "rzadszy_niz_proc", "mnoznik_4"]];
  last.tickets.forEach((t, i) => rows.push([i + 1, ...t.numbers, (100 * t.rarer_than).toFixed(0), t.prize_mult4.toFixed(2)]));
  const blob = new Blob([rows.map(r => r.join(";")).join("\n")], { type: "text/csv" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `kupon-${last.draw_date}.csv` });
  a.click();
  URL.revokeObjectURL(a.href);
}

$("gen-btn").addEventListener("click", generate);
// wszystkie zakłady w jednej linii, oddzielone średnikiem: okienko zakładki na lotto.pl jest jednoliniowe
$("copy-btn").addEventListener("click", e =>
  copyWithFeedback(e.currentTarget, last.tickets.map(t => t.numbers.join(" ")).join("; ")));
$("csv-btn").addEventListener("click", csv);

// zakładka (bookmarklet) do lotto.pl: kod z js/bookmarklet.js jako adres javascript:
fetch("js/bookmarklet.js").then(r => r.text()).then(code => {
  // bez komentarzy i nowych linii: niektóre przeglądarki usuwają nowe linie z adresów zakładek
  const oneLine = code.replace(/(^|\s)\/\/[^\n]*/g, "$1").replace(/\s*\n\s*/g, " ").trim();
  $("bookmarklet").href = "javascript:" + encodeURIComponent(oneLine);
});
$("bookmarklet").addEventListener("click", e => {
  e.preventDefault();
  $("bm-hint").hidden = false;
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => last && renderPopularity(last));
init();

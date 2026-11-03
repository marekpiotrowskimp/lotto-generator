// Dashboard: status bazy, synchronizacja, ostatnie losowania, rozbieżności.
const $ = id => document.getElementById(id);

async function loadStatus() {
  const s = await api("/api/status");
  $("t-draws").textContent = fmt.int(s.draws);
  $("t-range").textContent = s.first_date ? `od ${fmt.date(s.first_date)}` : "";
  if (s.last_draw) {
    $("t-last").textContent = "nr " + s.last_draw.draw_no;
    $("t-last-date").textContent = fmt.date(s.last_draw.date);
  }
  $("t-jackpot").textContent = s.next_jackpot ? fmt.zl(s.next_jackpot) : "–";
  $("t-price").textContent = s.ticket_price ? `zakład: ${fmt.zl(s.ticket_price)}` : "";
  $("t-extra").textContent = `${fmt.int(s.draws_with_prizes)} z wygranymi`;
  $("t-extra-sub").textContent = `${fmt.int(s.draws_with_order)} z kolejnością kul · ${s.disputes} spornych`;
  if (s.last_sync) {
    $("sync-info").textContent = `Ostatnia synchronizacja: ${s.last_sync.ts.replace("T", " ")} (${s.last_sync.source}, ${s.last_sync.status})`;
  }
  renderJob(s.sync_job);
  return s;
}

function renderJob(j) {
  $("sync-btn").disabled = j.running;
  $("sync-progress").hidden = !j.running;
  if (j.running) {
    const pct = j.total ? Math.round(100 * j.done / j.total) : 5;
    $("sync-bar").style.width = pct + "%";
    $("sync-text").textContent = j.phase === "wygrane"
      ? `Pobieranie wygranych: ${j.done} / ${j.total} stron`
      : "Pobieranie losowań…";
  }
  if (j.error) $("sync-result").textContent = "Błąd: " + j.error;
  else if (j.result) {
    const r = j.result, p = r.prizes;
    $("sync-result").textContent = `Dodano ${r.added} losowań (ostatnie nr ${r.last_draw_no}).` +
      (p ? ` Wygrane: pobrano ${p.ok}, bez danych ${p.no_data}, błędów ${p.error}.` : "");
  }
}

async function sync() {
  $("sync-result").textContent = "";
  await api("/api/sync", { method: "POST" });
  const poll = async () => {
    const j = await api("/api/sync/status");
    renderJob(j);
    if (j.running) setTimeout(poll, 1000);
    else { await loadStatus(); await loadDraws(); }
  };
  poll();
}

function prizeCell(p) {
  if (!p) return el("td", { class: "num muted" }, "–");
  return el("td", { class: "num prize" }, fmt.int(p.winners), el("small", {}, p.winners ? fmt.zl(p.amount) : ""));
}

async function loadDraws() {
  const rows = await api("/api/draws?limit=" + $("limit").value);
  $("draws").replaceChildren(...rows.map(d => el("tr", {},
    el("td", { class: d.disputed ? "disputed" : "", title: d.disputed ? "źródła się różnią" : "" }, String(d.draw_no)),
    el("td", {}, fmt.date(d.date)),
    el("td", {}, balls(d.numbers)),
    el("td", { class: "hide-sm" }, d.order ? balls(d.order, true) : "–"),
    ...[6, 5, 4, 3].map(t => prizeCell(d.prizes && d.prizes[t])),
    el("td", { class: "num hide-sm" }, d.total_pool ? fmt.zl(d.total_pool) : "–"),
  )));
}

async function loadDisputes() {
  const rows = await api("/api/disputes");
  $("disputes-count").textContent = rows.length;
  $("disputes").replaceChildren(...rows.map(d => {
    const other = new Set(d.other_numbers), main = new Set(d.numbers);
    return el("tr", {},
      el("td", {}, String(d.draw_no)), el("td", {}, fmt.date(d.date)),
      el("td", {}, d.numbers.map(n => other.has(n) ? n : `[${n}]`).join(", ")),
      el("td", {}, d.other_numbers.map(n => main.has(n) ? n : `[${n}]`).join(", ") + ` · ${d.other_source}`));
  }));
}

$("sync-btn").addEventListener("click", sync);
$("limit").addEventListener("change", loadDraws);
loadStatus().then(s => { if (s.sync_job.running) sync(); });
loadDraws();
loadDisputes();

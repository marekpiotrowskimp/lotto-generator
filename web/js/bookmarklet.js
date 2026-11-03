// Zakładka (bookmarklet) do wypełniania zakładu na lotto.pl liczbami z generatora.
// Tylko zaznacza kule w otwartym oknie „Wybierz 6 liczb z 49”; zapis i zapłata należą do gracza.
//
// Działanie:
// 1. Pierwsze kliknięcie: pyta o zakłady (6 liczb; zakłady oddzielone średnikiem) i zapamiętuje je w tej karcie.
// 2. Każde kliknięcie wypełnia kolejny zakład: odznacza inne liczby, zaznacza 6 liczb z kolejki.
// 3. Wpisanie pustego tekstu w okienku czyści kolejkę.
//
// Siatkę rozpoznajemy po treści (kule z napisami 1..49 po kolei), nie po klasach CSS strony.
(function () {
  var KEY = "lottoGeneratorQueue";

  // komunikat w rogu strony zamiast alert(): nie blokuje karty, znika sam
  function toast(msg, warn) {
    var old = document.getElementById("lotto-gen-toast");
    if (old) old.remove();
    var t = document.createElement("div");
    t.id = "lotto-gen-toast";
    t.textContent = msg;
    t.setAttribute("style", "position:fixed;top:16px;right:16px;z-index:2147483647;max-width:360px;white-space:pre-line;" +
      "padding:12px 16px;border-radius:8px;font:14px/1.4 sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);cursor:pointer;" +
      (warn ? "background:#fff4e5;color:#7a3300;border:1px solid #e3b341;" : "background:#e3f5e3;color:#0a4a0a;border:1px solid #0ca30c;"));
    t.onclick = function () { t.remove(); };
    document.body.appendChild(t);
    setTimeout(function () { if (t.parentNode) t.remove(); }, 9000);
  }

  if (!/(^|\.)lotto\.pl$/.test(location.hostname) && !window.__lottoGenAnyHost) {   // __lottoGenAnyHost: tylko testy
    toast("Ta zakładka działa tylko na lotto.pl, w otwartym oknie „Wybierz 6 liczb z 49”.", true);
    return;
  }

  function load() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch (e) { return []; }
  }
  function save(q) {
    try { sessionStorage.setItem(KEY, JSON.stringify(q)); } catch (e) { /* tryb prywatny */ }
  }
  // zakłady oddzielone nową linią, średnikiem albo „|”; okienko prompt() jest jednoliniowe i usuwa
  // nowe linie, więc gdy separatorów brak, a liczb jest 12, 18, … — dzielimy je po 6
  function parse(text) {
    var out = [];
    var parts = (text || "").split(/[\n;|]+/);
    if (parts.length === 1) {
      var all = (text.match(/\d+/g) || []).map(Number);
      if (all.length > 6 && all.length % 6 === 0) {
        parts = [];
        for (var i = 0; i < all.length; i += 6) parts.push(all.slice(i, i + 6).join(" "));
      }
    }
    parts.forEach(function (line) {
      var nums = (line.match(/\d+/g) || []).map(Number).filter(function (n) { return n >= 1 && n <= 49; });
      var uniq = nums.filter(function (n, i) { return nums.indexOf(n) === i; });
      if (uniq.length === 6) out.push(uniq);
    });
    return out;
  }
  function visible(el) {
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  }
  function numberLeaves(root) {
    var all = root.querySelectorAll("*"), out = [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      if (el.children.length === 0 && /^\d{1,2}$/.test(el.textContent.trim()) && visible(el)) out.push(el);
    }
    return out;
  }
  function findGrid() {
    var leaves = numberLeaves(document.body);
    for (var i = 0; i + 49 <= leaves.length; i++) {
      var ok = true;
      for (var k = 0; k < 49; k++) {
        if (Number(leaves[i + k].textContent.trim()) !== k + 1) { ok = false; break; }
      }
      if (ok) return leaves.slice(i, i + 49);
    }
    return null;
  }
  function commonAncestor(a, b) {
    var p = a;
    while (p && !p.contains(b)) p = p.parentElement;
    return p;
  }
  function click(el) {
    var opts = { bubbles: true, cancelable: true, view: window };
    ["pointerdown", "mousedown", "pointerup", "mouseup"].forEach(function (t) {
      el.dispatchEvent(new (t.indexOf("pointer") === 0 && window.PointerEvent ? PointerEvent : MouseEvent)(t, opts));
    });
    el.click();
  }

  var grid = findGrid();
  if (!grid) {
    toast("Nie znaleziono siatki liczb 1–49.\nOtwórz okno wyboru liczb zakładu („Wybierz 6 liczb z 49”) i kliknij zakładkę ponownie.", true);
    return;
  }

  var queue = load();
  if (!queue.length) {
    var text = prompt("Wklej zakłady z generatora (6 liczb w zakładzie, zakłady oddzielone średnikiem):", "");
    if (text === null) return;
    queue = parse(text);
    if (!queue.length) {
      save([]);
      toast("Nie znaleziono zakładów (6 różnych liczb 1–49). Lista zakładów wyczyszczona.", true);
      return;
    }
  }
  var total = queue.length + (Number(sessionStorage.getItem(KEY + "Done")) || 0);
  var ticket = queue.shift();

  // obecnie zaznaczone: kule leżące w dokumencie między nagłówkiem „Moje liczby” a siatką
  // (niezależnie od tego, jak strona zagnieżdża elementy)
  function myHeading() {
    var all = document.body.querySelectorAll("*"), head = null;
    for (var i = 0; i < all.length; i++) {
      if (/^Moje liczby$/i.test(all[i].textContent.trim()) && visible(all[i])) head = all[i];   // najgłębszy
    }
    return head;
  }
  function readSelected() {
    var head = myHeading();
    grid = findGrid() || grid;            // strona mogła przerysować siatkę
    var gridSet = new Set(grid);
    if (!head) return null;
    var FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING;
    return numberLeaves(document.body).filter(function (el) {
      return !gridSet.has(el) && !head.contains(el)
        && (head.compareDocumentPosition(el) & FOLLOWING)
        && (el.compareDocumentPosition(grid[0]) & FOLLOWING);
    }).map(function (el) { return Number(el.textContent.trim()); });
  }

  var selected = readSelected();
  if (selected === null) {
    toast("Nie znaleziono sekcji „Moje liczby”. Zaznaczam liczby bez odznaczania; sprawdź wynik przed zapisem.", true);
    selected = [];
  }
  // kliknięcia po kolei, z przerwą na przerysowanie widoku; siatkę odszukujemy przed każdym kliknięciem
  var toClick = selected.filter(function (n) { return ticket.indexOf(n) < 0; })
    .concat(ticket.filter(function (n) { return selected.indexOf(n) < 0; }));
  function next(i) {
    if (i >= toClick.length) return setTimeout(report, 400);
    var g = findGrid();
    if (g) click(g[toClick[i] - 1]);
    setTimeout(function () { next(i + 1); }, 80);
  }
  next(0);

  save(queue);
  var done = total - queue.length;
  try { sessionStorage.setItem(KEY + "Done", queue.length ? String(done) : "0"); } catch (e) { /* tryb prywatny */ }

  // sprawdzenie po odświeżeniu widoku przez stronę
  function report() {
    var now = readSelected();
    var ok = now && now.length === 6 && ticket.every(function (n) { return now.indexOf(n) >= 0; });
    toast((ok ? "✔ " : "⚠ UWAGA: zaznaczenie nie zgadza się z zakładem (" + (now || []).join(", ") + ").\n") +
          "Zakład " + done + " z " + total + ": " + ticket.join(", ") +
          "\nSprawdź zaznaczone kule i kliknij „Zapisz”." +
          (queue.length ? "\nZostało zakładów: " + queue.length + " (otwórz kolejny zakład i kliknij zakładkę)." : "\nTo był ostatni zakład."), !ok);
  }
})();

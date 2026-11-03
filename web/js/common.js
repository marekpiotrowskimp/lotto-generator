// Wspólne funkcje frontendu.
const fmt = {
  int: n => n == null ? "–" : n.toLocaleString("pl-PL"),
  zl: n => n == null ? "–" : n.toLocaleString("pl-PL", { maximumFractionDigits: n >= 1000 ? 0 : 2 }) + " zł",
  date: s => s ? new Date(s + "T12:00:00").toLocaleDateString("pl-PL") : "–",
};

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const c of children) e.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return e;
}

function balls(nums, plain = false) {
  return el("span", { class: "balls" }, ...nums.map(n => el("span", { class: plain ? "ball plain" : "ball" }, String(n))));
}

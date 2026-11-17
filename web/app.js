// Minimal, dependency-free front end for the honestbt API.
const $ = (id) => document.getElementById(id);
const pct = (x, d = 2) => (x == null || isNaN(x) ? "–" : (100 * x).toFixed(d) + "%");
const num = (x, d = 2) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(d));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
}

// ---------- patch bay graph ----------
function collectRefs(obj, out = []) {
  if (obj && typeof obj === "object") {
    if ("$map" in obj) out.push(["m", obj.$map]);
    else if ("$feature" in obj) out.push(["f", obj.$feature]);
    else Object.values(obj).forEach((v) => collectRefs(v, out));
  }
  return out;
}

function drawGraph(cfg) {
  const svg = $("graph");
  const W = svg.clientWidth || 600, H = 280;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const feats = Object.keys(cfg.features || {});
  const maps = Object.keys(cfg.mappings || {});
  const sp = (cfg.strategy || {}).params || {};
  const colX = [10, W * 0.36, W * 0.68], bw = Math.min(150, W * 0.3), bh = 24;
  const pos = {};
  const place = (names, col, prefix) => names.forEach((n, i) => {
    const gap = H / (names.length + 1);
    pos[prefix + n] = { x: colX[col], y: gap * (i + 1) - bh / 2 };
  });
  place(feats, 0, "f:");
  place(maps, 1, "m:");
  pos["s"] = { x: colX[2], y: H / 2 - 40 };
  let html = "";
  const edge = (a, b, bHeight = bh) => {
    if (!a || !b) return;
    const x1 = a.x + bw, y1 = a.y + bh / 2, x2 = b.x, y2 = b.y + bHeight / 2;
    html += `<path class="edge" d="M${x1},${y1} C${x1 + 40},${y1} ${x2 - 40},${y2} ${x2},${y2}"/>`;
  };
  maps.forEach((m) => {
    const inp = cfg.mappings[m].input;
    edge(pos["f:" + inp] || pos["m:" + inp], pos["m:" + m]);
  });
  const named = ["rank_by", "price_feature", "liquidity_feature"].map((k) => sp[k]).filter(Boolean);
  named.forEach((f) => edge(pos["f:" + f], pos.s, 80));
  collectRefs(sp).forEach(([k, n]) => edge(pos[k + ":" + n], pos.s, 80));
  // exit signals reference ATR-like features by name too
  JSON.stringify(sp).replace(/"atr_feature":"([^"]+)"/g, (_, f) => edge(pos["f:" + f], pos.s, 80));
  const box = (p, label, sub, fill, h = bh) =>
    `<rect x="${p.x}" y="${p.y}" width="${bw}" height="${h}" rx="5" fill="${fill}" stroke="${css("--line")}"/>` +
    `<text x="${p.x + 6}" y="${p.y + 15}">${label}</text>` +
    (sub ? `<text x="${p.x + 6}" y="${p.y + 30}" opacity=".7">${sub}</text>` : "");
  feats.forEach((f) => (html += box(pos["f:" + f], f, null, css("--node-f"))));
  maps.forEach((m) => (html += box(pos["m:" + m], `${m} (${cfg.mappings[m].plugin})`, null, css("--node-m"))));
  const exit = (sp.exit || {}).plugin || "";
  html += box(pos.s, cfg.strategy?.plugin || "strategy", `top ${sp.top_n ?? "?"} by ${sp.rank_by ?? "?"}`, css("--node-s"), 80);
  html += `<text x="${pos.s.x + 6}" y="${pos.s.y + 48}" opacity=".7">exit: ${exit}</text>`;
  const sweep = Object.keys(cfg.sweep || {});
  html += `<text x="${pos.s.x + 6}" y="${pos.s.y + 66}" opacity=".7">sweep axes: ${sweep.length}</text>`;
  svg.innerHTML = html;
}

function onEdit() {
  try {
    const cfg = JSON.parse($("configEditor").value);
    $("problems").textContent = "";
    drawGraph(cfg);
    return cfg;
  } catch (e) {
    $("problems").textContent = "JSON error: " + e.message;
    return null;
  }
}

// ---------- results ----------
function drawEquity(series) {
  const c = $("equity"), ctx = c.getContext("2d");
  const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = 260;
  c.width = W * dpr; c.height = H * dpr; ctx.scale(dpr, dpr); ctx.clearRect(0, 0, W, H);
  const all = series.flatMap((s) => s.v);
  if (!all.length) return;
  const lo = Math.min(...all, 1), hi = Math.max(...all, 1), pad = 34;
  const n = Math.max(...series.map((s) => s.v.length));
  const X = (i) => pad + (i / Math.max(1, n - 1)) * (W - pad - 8);
  const Y = (v) => H - 20 - ((v - lo) / (hi - lo || 1)) * (H - 36);
  ctx.strokeStyle = css("--line"); ctx.beginPath(); ctx.moveTo(pad, Y(1)); ctx.lineTo(W - 8, Y(1)); ctx.stroke();
  ctx.fillStyle = css("--muted"); ctx.font = "11px system-ui";
  ctx.fillText(hi.toFixed(2), 2, Y(hi) + 4); ctx.fillText(lo.toFixed(2), 2, Y(lo)); 
  series.forEach((s, k) => {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
    s.v.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
    ctx.stroke();
    ctx.fillStyle = s.color; ctx.fillText(s.label, pad + 6 + k * 130, 12);
  });
}

function renderSweep(sweep) {
  if (!sweep.length || !Object.keys(sweep[0].point).length) { $("sweep").innerHTML = '<p class="muted">No sweep.</p>'; return; }
  const axes = Object.keys(sweep[0].point);
  const short = (a) => a.split(".").slice(-2).join(".");
  let h = "<div class='tablewrap'><table><tr>" + axes.map((a) => `<th>${short(a)}</th>`).join("") +
    "<th>mean/period</th><th>Sharpe</th><th>max DD</th><th>trades</th></tr>";
  for (const s of sweep) {
    const m = s.metrics, good = m.mean_period_return > 0;
    h += "<tr>" + axes.map((a) => `<td>${s.point[a]}</td>`).join("") +
      `<td style="color:${good ? css("--pass") : css("--fail")}">${pct(m.mean_period_return, 3)}</td>` +
      `<td>${num(m.sharpe)}</td><td>${pct(m.max_drawdown, 1)}</td><td>${m.n_trades}</td></tr>`;
  }
  $("sweep").innerHTML = h + "</table></div>";
}

function renderTrades(trades) {
  let h = "<table><tr><th>symbol</th><th>entry</th><th>exit</th><th>held (min)</th><th>reason</th><th>score</th><th>net</th></tr>";
  for (const t of trades.slice(0, 200)) {
    h += `<tr><td>${t.symbol}</td><td>${t.entry_time.slice(0, 16)}</td><td>${t.exit_time.slice(0, 16)}</td>` +
      `<td>${t.minutes_held}</td><td>${t.reason}</td><td>${pct(t.score)}</td>` +
      `<td style="color:${t.net_return > 0 ? css("--pass") : css("--fail")}">${pct(t.net_return)}</td></tr>`;
  }
  $("trades").innerHTML = h + "</table>";
}

function render(out) {
  const s = out.summary, ok = s.evaluated && s.survived === s.evaluated;
  $("summary").className = "summary " + (ok ? "pass" : "fail");
  $("summary").innerHTML = `<b>Survived ${s.survived} of ${s.evaluated} tests: ${s.overall}.</b><br>` +
    `<span class="muted">Selected variant ${JSON.stringify(out.selected_point)} · ${out.data} · ${out.elapsed_s}s. ${s.note}</span>`;
  $("verdicts").innerHTML = out.verdicts.map((v) => {
    const cls = v.passed === true ? "pass" : v.passed === false ? "fail" : "";
    const tag = v.passed === true ? "PASS" : v.passed === false ? "FAIL" : "N/A";
    return `<div class="verdict ${cls}"><span class="tag">${tag}</span><b>${v.name}: ${v.headline}</b><p>${v.explanation}</p></div>`;
  }).join("");
  const series = [{ label: "strategy", v: out.selected.equity.v, color: css("--accent") }];
  const bm = out.verdicts.find((v) => v.name === "Benchmark");
  if (bm && bm.details.benchmark_equity) series.push({ label: "buy universe", v: bm.details.benchmark_equity.v, color: css("--muted") });
  drawEquity(series);
  renderSweep(out.sweep);
  renderTrades(out.selected.trades);
}

async function run() {
  const cfg = onEdit();
  if (!cfg) return;
  $("runBtn").disabled = true; $("runBtn").textContent = "Running…";
  try { render(await api("/api/run", cfg)); }
  catch (e) { $("problems").textContent = e.message; }
  finally { $("runBtn").disabled = false; $("runBtn").textContent = "Run"; }
}

async function loadConfig(name) {
  const cfg = await api("/api/configs/" + name);
  $("configEditor").value = JSON.stringify(cfg, null, 2);
  onEdit();
}

async function init() {
  const cat = await api("/api/plugins");
  $("catalogue").innerHTML = Object.entries(cat).map(([kind, items]) =>
    `<div class="cat-kind">${kind}</div>` + items.map((p) =>
      `<div class="cat-item"><code>${p.name}</code> ${p.doc}${p.params.length ? " <span class='muted'>(" + p.params.map((q) => q.name).join(", ") + ")</span>" : ""}</div>`).join("")).join("");
  const names = await api("/api/configs");
  $("configSelect").innerHTML = names.map((n) => `<option>${n}</option>`).join("");
  $("configSelect").onchange = (e) => loadConfig(e.target.value);
  $("configEditor").oninput = onEdit;
  $("runBtn").onclick = run;
  if (names.length) await loadConfig(names[0]);
}
init();

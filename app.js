/* Momentum Sniper — live dashboard client (WebSocket + fallback polling) */
"use strict";

const $ = (id) => document.getElementById(id);
const fmtPrice = (v) => {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const n = Number(v);
  if (n === 0) return "0";
  if (n >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (n >= 1) return n.toFixed(4);
  return n.toPrecision(4);
};
const fmtQty = (v) => (v === null || v === undefined || isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 6 }));
const fmtUsd = (v) => (v === null || v === undefined || isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }));
const fmtPct = (v) => (v === null || v === undefined || isNaN(v) ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`);
const cls = (v) => (Number(v) > 0 ? "pos-color" : Number(v) < 0 ? "neg-color" : "zero-color");
const timeStr = (ts) => new Date(ts * 1000).toLocaleTimeString("ar", { hour12: false });
const FACTORS = {
  mom_5m: "زخم 5 دقائق", mom_15m: "زخم 15 دقيقة", mom_1h: "زخم ساعة", mom_4h: "زخم 4 ساعات",
  mom_24h: "زخم 24 ساعة", spike_5m: "انفجار الحجم (5د)", liquidity: "السيولة (24س)",
  rsi_15m: "مؤشر RSI (15د)", social: "ضجة اجتماعية/إخبارية", pressure: "ضغط أوامر الشراء",
  new_listing: "🚀 إدراج جديد",
};
const SRC_LABELS = {
  coingecko_trending: "ترند CoinGecko", coingecko_mover: "صاعد عالمي", new_listing: "إدراج جديد",
  binance: "بينانس", reddit: "ريديت", announcement: "إعلان رسمي", "announcement-pending": "إعلان رسمي",
};

/* ── state ─────────────────────────────────────────── */
let ws = null, wsTries = 0, lastSnap = null;
const seenEvents = new Set();
let lastEquity = [];

/* ── websocket ─────────────────────────────────────── */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch { return scheduleReconnect(); }
  ws.onopen = () => { wsTries = 0; setStatus(true); };
  ws.onmessage = (m) => {
    let data; try { data = JSON.parse(m.data); } catch { return; }
    if (data.type === "snapshot") { lastSnap = data; renderSnapshot(data); }
    else if (data.type === "event") addEvent(data, true);
  };
  ws.onclose = () => { setStatus(false); scheduleReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
function scheduleReconnect() {
  wsTries += 1;
  if (wsTries >= 4) { startPolling(); return; }
  setTimeout(connectWS, Math.min(1000 * wsTries, 4000));
}
function setStatus(on) {
  const dot = $("status-dot"), t = $("status-text");
  if (!dot) return;
  dot.className = "dot " + (on ? "on" : "off");
  t.textContent = on ? "متصل — بث حي" : "انقطع الاتصال…";
}

/* fallback: HTTP polling if WS is blocked (e.g. behind proxies) */
let pollTimer = null;
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/state");
      const data = await r.json();
      lastSnap = data; renderSnapshot(data);
      const ev = await (await fetch("/api/events?limit=80")).json();
      (ev.events || []).slice().reverse().forEach((e) => addEvent(e, false));
    } catch {}
  }, 5000);
}

/* ── renderers ─────────────────────────────────────── */
function renderSnapshot(s) {
  // header
  const modeBadge = $("mode-badge");
  modeBadge.textContent = s.mode === "paper" ? "وضع المحاكاة PAPER" : s.mode === "testnet" ? "تجريبي TESTNET" : s.mode === "live" ? "حقيقي LIVE 🔥" : s.mode;
  modeBadge.className = "badge mode-" + s.mode;
  const running = s.status === "running";
  $("status-dot").className = "dot " + (running ? "on" : "off");
  $("status-text").textContent = running ? "الروبوت يعمل" : s.status;

  const up = s.uptime_sec || 0;
  $("uptime").textContent = up > 86400 ? `${Math.floor(up / 86400)}ي ${Math.floor((up % 86400) / 3600)}س` :
    up > 3600 ? `${Math.floor(up / 3600)}س ${Math.floor((up % 3600) / 60)}د` : `${Math.floor(up / 60)} دقيقة`;

  // F&G
  if (s.fng && s.fng.value !== null && s.fng.value !== undefined) {
    $("fng-value").textContent = `${s.fng.value} ${s.fng_ctx?.label || ""}`;
    $("fng-needle").style.right = `${100 - s.fng.value}%`;
  }

  // KPIs
  const total = s.equity_total, bal = s.balance_quote;
  $("kpi-equity").textContent = fmtUsd(total);
  $("kpi-balance").textContent = fmtUsd(bal);
  if (s.mode === "paper" && s.start_balance) {
    const pnl = total - s.start_balance, pct = (total / s.start_balance - 1) * 100;
    const el = $("kpi-pnl");
    el.textContent = `${pnl >= 0 ? "+" : ""}${fmtUsd(pnl)} (${fmtPct(pct)})`;
    el.className = "value num " + cls(pnl);
    $("kpi-equity-sub").textContent = `رأس المال الابتدائي ${fmtUsd(s.start_balance)} USDT`;
  } else {
    const rt = s.stats?.realized_total || 0;
    const el = $("kpi-pnl");
    el.textContent = fmtUsd(rt);
    el.className = "value num " + cls(rt);
    $("kpi-equity-sub").textContent = "محفظة حقيقية عبر Binance API";
  }
  $("kpi-mode-sub").textContent = s.mode === "paper" ? "أموال وهمية — أسعار حية" : "أموال حقيقية — أوامر فعلية";
  $("kpi-open").textContent = s.stats?.open ?? 0;
  $("kpi-open-sub").textContent = `الحد الأقصى ${s.config?.max_concurrent ?? "—"}`;
  const wins = s.stats?.wins || 0, closedN = s.stats?.closed || 0;
  const wr = closedN ? (wins / closedN) * 100 : null;
  $("kpi-winrate").textContent = wr === null ? "—" : `${wr.toFixed(0)}%`;
  $("kpi-winrate-sub").textContent = `${wins} رابحة من ${closedN} مغلقة`;

  renderEquity(s.equity_curve || []);
  renderPositions(s.positions || []);
  renderCandidates(s.candidates || []);
  renderClosed(s.closed_positions || []);
  renderConfig(s.config || {}, s.learned || {});
  renderWatchlist(s.watchlist || []);
  renderRejections(s.rejections || []);
  renderLearned(s.learned || {});

  // first load: fill feed from snapshot history (WS also replays; dedupe handles overlap)
  (s.events || []).slice().reverse().forEach((e) => addEvent(e, false));
}

function renderEquity(curve) {
  if (!curve || curve.length < 2) return;
  if (JSON.stringify(curve.map((p) => p.ts)) === JSON.stringify(lastEquity.map((p) => p.ts))) return;
  lastEquity = curve;
  const cv = $("equity-canvas"), dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 130;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const vals = curve.map((p) => p.total);
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min) * 0.12 || max * 0.02 || 1;
  const lo = min - pad, hi = max + pad;
  const x = (i) => (i / (vals.length - 1)) * (W - 8) + 4;
  const y = (v) => H - 8 - ((v - lo) / (hi - lo)) * (H - 20);
  const up = vals[vals.length - 1] >= vals[0];
  const col = up ? "#17dd8b" : "#ff5470";
  // fill
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, up ? "#17dd8b33" : "#ff547033");
  grad.addColorStop(1, "#0000");
  ctx.beginPath();
  ctx.moveTo(x(0), y(vals[0]));
  vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.lineTo(x(vals.length - 1), H); ctx.lineTo(x(0), H); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();
  // line
  ctx.beginPath();
  ctx.moveTo(x(0), y(vals[0]));
  vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke();
  // last point
  ctx.beginPath();
  ctx.arc(x(vals.length - 1), y(vals[vals.length - 1]), 3.2, 0, 7);
  ctx.fillStyle = col; ctx.fill();
}

function renderPositions(positions) {
  const wrap = $("positions-wrap");
  if (!positions.length) { wrap.innerHTML = '<div class="empty">لا توجد صفقات مفتوحة — البوت يراقب السوق…</div>'; return; }
  const rows = positions.map((p) => {
    const gain = p.gain_pct;
    const ladder = p.ladder || [];
    const nextIdx = ladder.findIndex((l) => !l.done);
    const tp = p.next_tp;
    const tpTrack = (ladder.length ? ladder : [0, 1, 2]).map((l, i) =>
      `<i class="${l && l.done ? "done" : i === nextIdx ? "next" : ""}"></i>`).join("");
    return `<tr>
      <td><span class="sym">${p.base}</span><span class="num" style="color:var(--muted)">/${p.symbol.replace(p.base, "")}</span>
          ${p.new_listing ? '<span class="tag new">🚀 إدراج جديد</span>' : ""}</td>
      <td class="num">${fmtPrice(p.mark)}</td>
      <td class="num">${fmtPrice(p.entry_price)}</td>
      <td class="num ${cls(gain)}"><b>${fmtPct(gain)}</b></td>
      <td class="num pos-color">+${fmtPct(p.max_gain_pct).replace("+", "")}</td>
      <td class="num">${fmtUsd(p.value_quote)}</td>
      <td>
        <div class="tp-track">${tpTrack}</div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">
          ${p.trailing_armed ? `🛡 متحرك @ ${fmtPrice(p.trail_stop_price)}` : (tp ? `🎯 الهدف +${tp.gain}% → بيع ${tp.sell}%` : "🎯 الأهداف انتهت — الترailing فقط")}
        </div>
      </td>
      <td style="font-size:10.5px;color:var(--muted);max-width:150px;white-space:normal">${(p.reasons || []).map((r) => SRC_LABELS[r] || r).join("، ") || "—"}</td>
    </tr>`;
  }).join("");
  wrap.innerHTML = `<table><thead><tr><th>العملة</th><th>السعر الحالي</th><th>متوسط الشراء</th><th>الربح</th><th>أعلى قمة</th><th>القيمة</th><th>الحماية</th><th>سبب الدخول</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderCandidates(cands) {
  const wrap = $("candidates-wrap");
  if (!cands.length) { wrap.innerHTML = '<div class="empty">جارٍ أول فحص للسوق…</div>'; return; }
  const rows = cands.map((c) => {
    const tags = (c.sources || []).filter((s) => s !== "binance").map((s) => `<span class="tag ${s === "new_listing" ? "new" : "social"}">${SRC_LABELS[s] || s}</span>`).join("");
    const scoreBar = `<div class="bar ${c.score >= 78 ? "" : c.score >= 60 ? "amber" : "red"}" style="width:70px"><i style="width:${Math.min(100, c.score)}%"></i></div>`;
    return `<tr>
      <td><span class="sym">${c.base}</span>${c.new_listing ? '<span class="tag new">🚀</span>' : ""}${tags}</td>
      <td><div style="display:flex;align-items:center;gap:8px">${scoreBar}<b class="num">${c.score?.toFixed(0)}</b></div></td>
      <td class="num">${fmtPrice(c.price)}</td>
      <td class="num ${cls(c.change_24h)}">${fmtPct(c.change_24h)}</td>
      <td class="num" style="color:${c.spike_5m >= 3 ? "var(--green)" : "var(--muted)"}">${c.spike_5m ? c.spike_5m + "x" : "—"}</td>
      <td class="num">${c.rsi_15m ?? "—"}</td>
      <td><button class="why" data-sym="${c.symbol}">لماذا؟</button></td>
    </tr>`;
  }).join("");
  wrap.innerHTML = `<table><thead><tr><th>العملة</th><th>درجة الزخم</th><th>السعر</th><th>24س</th><th>انفجار حجم</th><th>RSI</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  wrap.querySelectorAll(".why").forEach((b) => b.onclick = (ev) => showWhy(b.dataset.sym, ev));
}

function showWhy(symbol, ev) {
  const c = (lastSnap?.candidates || []).find((x) => x.symbol === symbol);
  document.querySelectorAll(".why-box").forEach((n) => n.remove());
  if (!c || !c.breakdown) return;
  const box = document.createElement("div");
  box.className = "why-box";
  const rows = Object.entries(c.breakdown)
    .filter(([k, v]) => k !== "_meta" && v && typeof v === "object" && "grade" in v)
    .map(([k, v]) => {
      const name = FACTORS[k] || k;
      const pct = Math.round((v.grade || 0) * 100);
      return `<div class="why-row"><span class="k">${name}</span>
        <div class="bar ${pct >= 60 ? "" : pct >= 35 ? "amber" : "red"}"><i style="width:${pct}%"></i></div>
        <span class="v num">${v.value}</span></div>`;
    }).join("");
  box.innerHTML = `<h3>🧪 تفكيك درجة ${c.base}: <span class="num">${c.score?.toFixed(0)}</span>/100</h3>${rows}
    <div style="color:var(--muted);font-size:10.5px;margin-top:6px">كل عامل موزون — الدرجة النهائية = مجموع (الوزن × التقييم) − عقوبات الخوف والطمع</div>`;
  document.body.appendChild(box);
  const r = ev.target.getBoundingClientRect();
  box.style.top = Math.min(window.innerHeight - box.offsetHeight - 10, r.bottom + 6) + "px";
  const rightPx = Math.max(8, Math.min(window.innerWidth - box.offsetWidth - 8, window.innerWidth - r.right - 40));
  box.style.right = rightPx + "px";
  setTimeout(() => document.addEventListener("click", function h(e) {
    if (!box.contains(e.target)) { box.remove(); document.removeEventListener("click", h); }
  }), 10);
}

function renderClosed(list) {
  const wrap = $("closed-wrap");
  if (!list.length) { wrap.innerHTML = '<div class="empty">لم تُغلق أي صفقة بعد</div>'; return; }
  const rows = list.map((p) => {
    const holdMin = (p.closed_ts - p.opened_ts) / 60;
    return `<tr>
      <td><span class="sym">${p.symbol.replace("USDT", "")}</span></td>
      <td class="num">${fmtPrice(p.avg_entry)}</td>
      <td class="num">${fmtPrice(p.exit_avg)}</td>
      <td class="num ${cls(p.realized_quote)}"><b>${p.realized_quote >= 0 ? "+" : ""}${fmtUsd(p.realized_quote)}</b></td>
      <td class="num ${cls(p.realized_pct)}">${fmtPct(p.realized_pct)}</td>
      <td class="num pos-color">+${p.max_gain_pct?.toFixed(1) ?? "—"}%</td>
      <td style="font-size:10.5px;color:var(--muted);max-width:180px;white-space:normal">${p.exit_reason || "—"}</td>
      <td class="num" style="color:var(--muted)">${holdMin < 90 ? holdMin.toFixed(0) + " د" : (holdMin / 60).toFixed(1) + " س"}</td>
    </tr>`;
  }).join("");
  wrap.innerHTML = `<table><thead><tr><th>العملة</th><th>الدخول</th><th>الخروج</th><th>النتيجة USDT</th><th>النتيجة %</th><th>أعلى قمة</th><th>سبب الخروج</th><th>المدة</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderConfig(cfg, learned) {
  if (!cfg.mode) return;
  const items = [
    ["وضع التشغيل", cfg.mode.toUpperCase()],
    ["دورية الفحص", `${cfg.scan_sec} ثانية`],
    ["حد الدخول (الدرجة)", learned.entry_threshold_delta ? `${cfg.entry_threshold?.toFixed(0)} (معدّل ${learned.entry_threshold_delta > 0 ? "+" : ""}${learned.entry_threshold_delta.toFixed(0)})` : cfg.entry_threshold?.toFixed(0)],
    ["نسبة كل صفقة", `${cfg.allocation_pct}% من الرصيد`],
    ["حد الصفقات المتزامنة", cfg.max_concurrent],
    ["حد الصفقات اليومي", cfg.max_per_day],
    ["وقف الخسارة الصارم", `${cfg.hard_sl}%`],
    ["سلّم الأهداف", (cfg.tp_ladder || []).map((t) => `+${t[0]}%→بيع${t[1]}%`).join(" · ")],
    ["الوقف المتحرك", `يُسلّح عند +${cfg.trail_trigger}% ويحمي بهامش ${cfg.trail_drop}%`],
    ["درع FOMO", `رفض الدخول فوق +${cfg.fomo_block?.toFixed(0)}%`],
    ["أدنى سيولة 24س", `${fmtUsd(cfg.min_volume)} USDT`],
    ["قنص الإدراج الجديد", cfg.sniper_on ? "مفعّل 🚀" : "معطّل"],
  ];
  $("config-list").innerHTML = items.map(([k, v]) => `<div><span>${k}</span><b class="num">${v ?? "—"}</b></div>`).join("");
}

function renderWatchlist(list) {
  const wrap = $("watchlist");
  if (!list.length) { wrap.innerHTML = '<span class="empty">لا يوجد إعلانات إدراج مرصودة حالياً</span>'; return; }
  wrap.innerHTML = list.map((w) => `<span class="chip">📢 <b>${w.symbol.replace("USDT", "")}</b> ${SRC_LABELS[w.source] || w.source} · ${timeStr(w.added_ts)}</span>`).join("");
}

function renderRejections(list) {
  const wrap = $("rejections");
  if (!list || !list.length) { wrap.innerHTML = '<div class="empty">لا مرفوضات بعد</div>'; return; }
  wrap.innerHTML = list.slice().reverse().map((r) =>
    `<div class="rej"><span><b>${r.base}</b> <span class="num" style="color:var(--muted)">${r.score?.toFixed(0)}</span></span><span class="r">${r.reason}</span></div>`).join("");
}

function renderLearned(l) {
  const box = $("learned-box");
  const parts = [];
  if (l.entry_threshold_delta) parts.push(`حد الدخول ${l.entry_threshold_delta > 0 ? "أكثر" : "أقل"} صرامة بـ ${Math.abs(l.entry_threshold_delta).toFixed(0)} نقاط`);
  if (l.trail_drop_delta) parts.push(`الوقف المتحرك ${l.trail_drop_delta < 0 ? "أشد" : "أكثر"} إحكاماً بـ ${Math.abs(l.trail_drop_delta).toFixed(0)}%`);
  if (l.fomo_block_delta) parts.push(`درع FOMO أشد بـ +${l.fomo_block_delta.toFixed(0)}%`);
  box.innerHTML = parts.length
    ? `🧠 بعد تشريح صفقاته، عدّل البوت معاييره بنفسه:<br>${parts.map((p) => `• ${p}`).join("<br>")}`
    : "بانتظار أول صفقة مغلقة لتكتب البوت تقرير التشريح…";
}

/* ── events feed ───────────────────────────────────── */
function addEvent(e, live) {
  const key = `${Math.round((e.ts || 0) * 1000)}|${(e.msg || "").slice(0, 60)}`;
  if (seenEvents.has(key)) return;
  seenEvents.add(key);
  if (seenEvents.size > 600) { const it = seenEvents.values(); for (let i = 0; i < 200; i++) seenEvents.delete(it.next().value); }
  const feed = $("feed");
  const div = document.createElement("div");
  div.className = `ev ${e.level || "info"}`;
  const cat = { scanner: "ماسح السوق", entry: "تنفيذ", exit: "خروج", system: "النظام", external: "مصادر خارجية", autopsy: "تشريح ذاتي" }[e.category] || e.category;
  div.innerHTML = `<div class="meta"><span>${timeStr(e.ts)}</span><span class="cat">${cat}</span>${live ? '<span style="color:var(--green)">● حي</span>' : ""}</div><div>${e.msg}</div>`;
  feed.prepend(div);
  while (feed.children.length > 120) feed.lastChild.remove();
}

/* ── boot ──────────────────────────────────────────── */
connectWS();

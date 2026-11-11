// ファンダ分析（5軸のレーダーチャートと、30項目のチェック）の画面。
// 逆張り・順張りの候補判定には使わない、参考情報。
import { esc, number, shortDate } from "./format.js";

export const AXIS_NAME = { value: "割安度", growth: "成長", past: "過去実績", health: "財務健全性", dividend: "配当" };
const AXIS_SHORT = { value: "割", growth: "成", past: "実", health: "財", dividend: "配" };
const AXIS_NOTE = {
  value: "ほかの銘柄と比べて割安かどうか。理論株価の計算ではありません。",
  growth: "アナリストの業績予想にもとづきます。予想は外れることがあります。",
  past: "過去の決算（年次）の実績です。",
  health: "借金の重さと支払い能力です。銀行・保険などは対象外にしています。",
  dividend: "配当の水準と、続けられそうかどうかです。",
};

const ui = { sort: "total", sector: "", query: "", listScroll: 0, market: null };
let current = null;
let getJSON = null;

const times = (v, d = 1) => (v == null ? "—" : `${number(v, d)}倍`);
const pc = (v, d = 1) => (v == null ? "—" : `${v < 0 ? "−" : ""}${number(Math.abs(v), d)}%`);

// 項目ごとの「条件の説明」と「この銘柄の数値」
function describe(key, m, d, sector) {
  const c = d.config, st = d.stats;
  const per = m.loss ? "赤字のためPERなし" : `PER ${times(m.per)}`;
  switch (key) {
    case "per_vs_market": return [`PERが対象銘柄の中央値（${times(st.per)}）より低い`, per];
    case "per_vs_sector": return [`PERが同じセクターの中央値（${times(st.sector_per[sector])}）より低い`, per];
    case "pbr_vs_market": return [`PBRが対象銘柄の中央値（${times(st.pbr, 2)}）より低い`, `PBR ${times(m.pbr, 2)}`];
    case "peg": return [`PEG（PER ÷ 予想EPS成長率）が${c.value.peg_max}未満`, `PEG ${m.peg == null ? "—" : number(m.peg, 2)}`];
    case "ev_ebitda_vs_market": return [`EV/EBITDAが対象銘柄の中央値（${times(st.ev_ebitda)}）より低い`, m.financial ? "金融業は対象外" : `EV/EBITDA ${times(m.ev_ebitda)}`];
    case "fcf_yield": return [`フリーキャッシュフロー利回りが${c.value.fcf_yield_min_pct}%以上`, m.financial ? "金融業は対象外" : pc(m.fcf_yield)];
    case "eps_growth_positive": return ["予想EPS成長率がプラス", pc(m.eps_g_next)];
    case "eps_growth_high": return [`予想EPS成長率が${c.growth.eps_growth_min_pct}%以上`, pc(m.eps_g_next)];
    case "eps_growth_vs_market": return [`予想EPS成長率が対象銘柄の中央値（${pc(st.eps_growth)}）より高い`, pc(m.eps_g_next)];
    case "rev_growth_high": return [`予想売上成長率が${c.growth.revenue_growth_min_pct}%以上`, pc(m.rev_g_next)];
    case "rev_growth_vs_market": return [`予想売上成長率が対象銘柄の中央値（${pc(st.rev_growth)}）より高い`, pc(m.rev_g_next)];
    case "growth_both_years": return ["今期・来期とも増益予想", `今期 ${pc(m.eps_g0)} ／ 来期 ${pc(m.eps_g1)}`];
    case "eps_cagr_positive": return [`EPSの${c.past.cagr_years}年成長率（年率）がプラス`, pc(m.eps_cagr)];
    case "eps_accelerating": return [`直近年のEPS成長が${c.past.cagr_years}年平均より高い`, `直近 ${pc(m.eps_g_last)} ／ 平均 ${pc(m.eps_cagr)}`];
    case "roe": return [`ROEが${c.past.roe_min_pct}%以上`, pc(m.roe)];
    case "roa": return [`ROAが${c.past.roa_min_pct}%以上`, pc(m.roa)];
    case "margin_improved": return ["純利益率が前年より改善", `${pc(m.margin)}（前年 ${pc(m.margin_prev)}）`];
    case "cash_backed": return ["営業キャッシュフローが純利益以上", ""];
    case "current_ratio": return [`流動比率（流動資産 ÷ 流動負債）が${c.health.current_ratio_min}倍以上`, times(m.current_ratio, 2)];
    case "debt_to_equity": return [`有利子負債が自己資本の${c.health.debt_to_equity_max}倍以下`, m.no_debt ? "有利子負債なし" : times(m.de, 2)];
    case "debt_reduced": return ["負債の比率が数年前より下がった", m.no_debt ? "有利子負債なし" : `${times(m.de, 2)}（以前 ${times(m.de_old, 2)}）`];
    case "ocf_to_debt": return [`営業キャッシュフローが有利子負債の${c.health.ocf_to_debt_min * 100}%以上`, m.no_debt ? "有利子負債なし" : pc(m.ocf_to_debt == null ? null : m.ocf_to_debt * 100, 0)];
    case "interest_cover": return [`利益が支払利息の${c.health.interest_cover_min}倍以上`, times(m.interest_cover)];
    case "equity_ratio": return [`自己資本比率が${c.health.equity_ratio_min_pct}%以上`, pc(m.equity_ratio)];
    case "yield_notable": return [`配当利回りが、配当のある銘柄の下位${c.dividend.low_quantile}%の水準（${pc(st.yield_low, 2)}）以上`, m.payer ? pc(m.div_yield, 2) : "無配"];
    case "yield_high": return [`配当利回りが上位の水準（${pc(st.yield_high, 2)}）以上`, m.payer ? pc(m.div_yield, 2) : "無配"];
    case "payout": return [`配当性向が${c.dividend.payout_max_pct}%以下`, m.payer ? pc(m.payout, 0) : "無配"];
    case "fcf_cover": return ["配当をフリーキャッシュフローで賄えている", m.payer ? "" : "無配"];
    case "stable": return [`${c.dividend.stable_years}年間、減配していない`, m.payer && !m.div_full_history ? `配当の履歴が${c.dividend.stable_years}年に足りません` : m.payer ? "" : "無配"];
    case "growing": return [`${c.dividend.stable_years}年前より増配している`, m.payer && !m.div_full_history ? `配当の履歴が${c.dividend.stable_years}年に足りません` : m.payer ? "" : "無配"];
    default: return [key, ""];
  }
}

const total = (s) => s.s.reduce((sum, v) => sum + (v ?? 0), 0);

// ------------------------------------------------------------ レーダーチャート

export function radarSVG(d, s) {
  const cx = 150, cy = 128, radius = 84, n = d.axes.length;
  const point = (i, r) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  };
  const ring = (level) => d.axes.map((_, i) => point(i, (radius * level) / 6).map((v) => v.toFixed(1)).join(",")).join(" ");
  const shape = d.axes.map((_, i) => point(i, (radius * (s.s[i] ?? 0)) / 6).map((v) => v.toFixed(1)).join(",")).join(" ");
  const spokes = d.axes.map((_, i) => { const [x, y] = point(i, radius); return `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join("");
  const labels = d.axes.map((axis, i) => {
    const [x, y] = point(i, radius + 20);
    const anchor = Math.abs(x - cx) < 5 ? "middle" : x > cx ? "start" : "end";
    const score = s.s[i] == null ? "—" : `${s.s[i]}/6`;
    return `<text x="${x.toFixed(1)}" y="${(y - 2).toFixed(1)}" text-anchor="${anchor}">${AXIS_NAME[axis]}</text>
      <text class="score" x="${x.toFixed(1)}" y="${(y + 12).toFixed(1)}" text-anchor="${anchor}">${score}</text>`;
  }).join("");
  return `<svg class="radar" viewBox="0 0 300 262" role="img" aria-label="5軸のレーダーチャート。${d.axes.map((a, i) => `${AXIS_NAME[a]} ${s.s[i] ?? "採点なし"}`).join("、")}">
    <g class="grid"><polygon points="${ring(6)}"/><polygon points="${ring(4)}"/><polygon points="${ring(2)}"/>${spokes}</g>
    <polygon class="shape" points="${shape}"/>${labels}</svg>`;
}

// ------------------------------------------------------------ 銘柄ごとのカード

function axisHTML(d, s, axis, i, open) {
  const results = s.c[axis];
  const rows = d.checks[axis].map((key, j) => {
    const [label, value] = describe(key, s.m, d, s.sector);
    const r = results[j];
    const state = r == null ? `<span class="muted">判定不可</span>` : r ? `<span class="state on">● 合格</span>` : `<span class="muted">✕</span>`;
    return `<tr><td>${esc(label)}${value ? `<br><span class="small muted num">${esc(value)}</span>` : ""}</td><td>${state}</td></tr>`;
  }).join("");
  const score = s.s[i] == null ? "採点なし" : `${s.s[i]} / 6`;
  return `<details class="axis" ${open ? "open" : ""}>
    <summary><span>${AXIS_NAME[axis]}</span><span class="num">${score}</span></summary>
    <p class="small muted">${AXIS_NOTE[axis]}</p>
    <table class="kv exit">${rows}</table>
  </details>`;
}

export function fundCardHTML(d, s, { open = false } = {}) {
  const notes = [];
  if (s.m.financial) notes.push("銀行・保険などの金融業は、財務健全性と、キャッシュフローを使う項目を判定していません（事業の形が一般の会社と違うため）。");
  if (s.s[1] == null) notes.push("アナリスト予想がないため、成長は採点していません。");
  if (s.m.loss) notes.push("直近は赤字のため、PERを使う項目は不合格にしています。");
  return `<section class="card">
    <h2>ファンダ分析　<span class="num">合計 ${total(s)} / 30</span></h2>
    ${radarSVG(d, s)}
    ${notes.map((t) => `<p class="small muted">${t}</p>`).join("")}
    ${d.axes.map((axis, i) => axisHTML(d, s, axis, i, open)).join("")}
    <p class="small muted">財務データは ${shortDate(s.fetched)} 取得（週1回更新）。株価で変わる指標は ${shortDate(d.as_of)} の終値で計算しています。
      比べる相手は ${esc(d.universe)} の銘柄です。データは Yahoo Finance 由来で、誤りや欠けを含むことがあります。重要な数値は決算資料で確かめてください。</p>
  </section>`;
}

// 逆張り・順張りの詳細画面に、ファンダ分析のカードを差し込む
export async function mountFundCard(el, market, code) {
  if (!el) return;
  try {
    const d = await getJSON(`data/${market}_fund.json`);
    const s = d.stocks.find((x) => x.code === code);
    if (el.isConnected) el.innerHTML = s ? fundCardHTML(d, s) : "";
  } catch {
    el.innerHTML = ""; // ファンダのデータがなくても、他の表示は続ける
  }
}

// ------------------------------------------------------------ 一覧

function sortValue(s, key, axes) {
  return key === "total" ? total(s) : s.s[axes.indexOf(key)] ?? -1;
}

function rowHTML(d, s) {
  const chips = d.axes.map((axis, i) => {
    const v = s.s[i];
    const cls = v == null ? "" : v >= 5 ? "good" : "";
    return `<span class="badge ${cls}">${AXIS_SHORT[axis]} ${v ?? "—"}</span>`;
  }).join("");
  return `<li><a class="row" href="#${d.market}/f/${encodeURIComponent(s.code)}">
    <div class="row-top">
      <span class="row-name"><span class="code">${esc(s.code)}</span>${esc(s.name)}</span>
      <span class="row-price num">合計 <strong>${total(s)}</strong></span>
    </div>
    <div class="row-bottom">${chips}</div>
  </a></li>`;
}

function listHTML(d) {
  const q = ui.query.trim().toLowerCase();
  const rows = d.stocks
    .filter((s) => !ui.sector || s.sector === ui.sector)
    .filter((s) => !q || s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    .sort((a, b) => sortValue(b, ui.sort, d.axes) - sortValue(a, ui.sort, d.axes) || total(b) - total(a) || a.code.localeCompare(b.code));
  const head = `<p class="small muted">${d.stocks.length}銘柄中 ${rows.length}銘柄を表示</p>`;
  if (!rows.length) return head + `<p class="muted pad">当てはまる銘柄はありません。</p>`;
  return head + `<ul class="list">${rows.map((s) => rowHTML(d, s)).join("")}</ul>`;
}

function controlsHTML(d) {
  const option = (value, label, selected) => `<option value="${esc(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`;
  const sectors = [...new Set(d.stocks.map((s) => s.sector))].sort();
  return `<div class="filters">
    <select data-fu-control="sector" aria-label="セクター">${option("", "セクター", ui.sector)}${sectors.map((s) => option(s, s, ui.sector)).join("")}</select>
    <select data-fu-control="sort" aria-label="並び順">
      ${option("total", "合計が高い順", ui.sort)}${d.axes.map((a) => option(a, `${AXIS_NAME[a]}が高い順`, ui.sort)).join("")}
    </select>
    <input type="search" data-fu-control="query" placeholder="銘柄を検索" value="${esc(ui.query)}">
  </div>`;
}

export function renderFundList(app, d) {
  if (ui.market !== d.market) Object.assign(ui, { sector: "", query: "", listScroll: 0, market: d.market });
  current = d;
  app.innerHTML = `
    <section class="card">
      <h2>ファンダ分析</h2>
      <p class="small">対象: ${esc(d.universe)}（${d.stocks.length} 銘柄）。割安度・成長・過去実績・財務健全性・配当の5つを、それぞれ6項目のチェックで採点します（各6点、合計30点）。</p>
      <p class="small muted">点数は会社の中身を見るための参考情報で、逆張り・順張りの候補判定には使っていません。点数が高いことは、株価が上がることを意味しません。</p>
      <p class="small muted">割＝割安度、成＝成長、実＝過去実績、財＝財務健全性、配＝配当。「—」は採点なし（データ不足や対象外）。</p>
    </section>
    ${controlsHTML(d)}<div id="fu-list">${listHTML(d)}</div>`;
  window.scrollTo(0, ui.listScroll);
}

export async function renderFundDetail(app, d, code, links) {
  current = d;
  const s = d.stocks.find((x) => x.code === code);
  if (!s) {
    app.innerHTML = `<p class="pad">銘柄が見つかりません。<a href="#${d.market}/f">一覧へ戻る</a></p>`;
    return;
  }
  const buttons = links.map(([href, label]) => `<a class="btn" href="${href}">${label}</a>`).join("");
  app.innerHTML = `
    <a class="btn back" href="#${d.market}/f">← 一覧へ戻る</a>
    <section class="card">
      <div class="small muted">${esc(s.code)}　${esc(s.sector)}</div>
      <h2>${esc(s.name)}</h2>
      ${buttons ? `<div class="actions">${buttons}</div>` : ""}
    </section>
    ${fundCardHTML(d, s, { open: true })}`;
  window.scrollTo(0, 0);
}

export function initFund(app, loader) {
  getJSON = loader;
  const refresh = () => (document.getElementById("fu-list").innerHTML = listHTML(current));
  app.addEventListener("click", (event) => {
    if (event.target.closest("#fu-list a.row")) ui.listScroll = window.scrollY;
  });
  app.addEventListener("input", (event) => {
    if (event.target.dataset.fuControl === "query") {
      ui.query = event.target.value;
      refresh();
    }
  });
  app.addEventListener("change", (event) => {
    const key = event.target.dataset.fuControl;
    if (key === "sector" || key === "sort") {
      ui[key] = event.target.value;
      refresh();
    }
  });
}

// 画面全体の制御。データ（JSON）を読んで表示するだけで、判定はしない。
import { store } from "./store.js";
import { LABEL, REVERSAL, WARNING } from "./labels.js";
import { esc, price, number, pct, signClass, shortDate, todayISO, daysBetween } from "./format.js";
import { drawChart, legendHTML } from "./chart.js";
import { earningsInfo as earningsOf, overrideKey } from "./earnings.js";
import { renderPortfolio, renderNewPosition, initPortfolio, loadPositions } from "./portfolio.js";
import { renderMomentumList, renderMomentumDetail, initMomentum } from "./momentum.js";

const MARKETS = ["jp", "us"];
const app = document.getElementById("app");
const cache = new Map();
const ui = { filter: "all", theme: "", sort: "count", query: "", listScroll: 0 };
let current = null; // 表示中の市場のデータ

async function getJSON(path) {
  if (!cache.has(path)) {
    const res = await fetch(path, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path} を読み込めませんでした（${res.status}）`);
    cache.set(path, await res.json());
  }
  return cache.get(path);
}

// ------------------------------------------------------------ 銘柄ごとの状態

const recentOf = (stock, kind) => stock.recent.filter((e) => e.k === kind).map((e) => e.d).pop();
const isStop = (s) => s.warnings.includes("two_black");
const hasWarning = (s) => s.warnings.length > 0 || s.trend.exit_warning;

const earningsInfo = (stock) => earningsOf(current.market, stock);

// 決算の直後（4日以内）に出たギャップアップかどうか
function eventLabel(stock, event) {
  const last = stock.earnings?.last;
  if (event.k === "gap_up" && last) {
    const days = daysBetween(last, event.d);
    if (days >= 0 && days <= 4) return "ギャップアップ（決算直後）";
  }
  return LABEL[event.k] ?? event.k;
}

// ------------------------------------------------------------ 市場の温度計

function thermoState(d) {
  const t = d.thermometer, limit = d.config.thermometer;
  const saved = store.get(`thermo:${d.market}`, {});
  const auto = t.vol.auto;
  const fg = saved.fg ?? null;
  const vol = auto ? auto.value : saved.vol ?? null;
  const chance = fg != null && vol != null && fg < limit.fear_greed_max && vol > limit.vol_index_min;
  return { t, limit, saved, auto, fg, vol, chance };
}

function verdictHTML(d) {
  const { t, limit, fg, vol, chance } = thermoState(d);
  const rule = `Fear & Greed が${limit.fear_greed_max}未満、かつ${esc(t.vol.name)}が${limit.vol_index_min}超`;
  if (fg == null || vol == null) {
    const missing = [fg == null ? "Fear & Greed" : null, vol == null ? t.vol.name : null].filter(Boolean).join(" と ");
    return `<div class="verdict">未判定<small>${esc(missing)} を入力すると判定します（${rule}で「大チャンス」）</small></div>`;
  }
  const values = `Fear & Greed ${number(fg, 0)} ／ ${esc(t.vol.name)} ${number(vol, 2)}`;
  if (chance) return `<div class="verdict chance">大チャンス<small>${values}（${rule}）</small></div>`;
  return `<div class="verdict">通常<small>${values}（${rule}で「大チャンス」）</small></div>`;
}

function thermometerHTML(d) {
  const { t, saved, auto } = thermoState(d);
  const ix = t.index, ma = d.config.ma;
  const lineBox = (key, days) => {
    const above = ix.above[key], rising = ix.rising[key];
    return `<div>${days}日線 ${rising ? "↗" : "↘"}<b class="num">${number(ix.ma[key], 0)}</b>
      <span class="${above ? "up" : "down"}">株価は${above ? "上" : "下"}</span></div>`;
  };
  const stamp = (date) => (date ? `入力日 ${shortDate(date)}${date !== todayISO() ? "（古い値かも）" : ""}` : "手入力・未入力");
  const link = (url) => (url ? ` <a href="${esc(url)}" target="_blank" rel="noopener">値を見る</a>` : "");
  const volField = auto
    ? `<label>${esc(t.vol.name)}</label><input type="number" value="${auto.value}" disabled>
       <span class="small muted">自動取得 ${shortDate(auto.date)}</span>`
    : `<label>${esc(t.vol.name)}${link(t.vol.url)}</label>
       <input type="number" inputmode="decimal" step="0.01" data-thermo="vol" value="${saved.vol ?? ""}" placeholder="例: 25.3">
       <span class="small muted">${stamp(saved.volDate)}</span>`;
  return `
  <section class="card">
    <h2>市場の温度計</h2>
    <div id="verdict">${verdictHTML(d)}</div>
    <div class="index-head">
      <span>${esc(ix.name)} <span class="small muted">${shortDate(ix.date)}</span></span>
      <span><span class="price num">${number(ix.close, 0)}</span>
        <span class="num ${signClass(ix.change_pct)}">${pct(ix.change_pct)}</span></span>
    </div>
    <div class="lines">${lineBox("short", ma.short)}${lineBox("mid", ma.mid)}${lineBox("long", ma.long)}</div>
    <p class="small ${ix.perfect_order ? "up" : "muted"}">${
      ix.perfect_order ? "指数はパーフェクトオーダー（3本の線が上から順に並び、すべて上向き）" : "指数はパーフェクトオーダーではありません"
    }</p>
    <button type="button" data-action="index-chart">指数のチャートを表示</button>
    <div id="index-chart"></div>
    <div class="inputs">
      <div>
        <label>Fear &amp; Greed${link(t.fear_greed.url)}</label>
        <input type="number" inputmode="decimal" min="0" max="100" data-thermo="fg" value="${saved.fg ?? ""}" placeholder="0〜100">
        <span class="small muted">${stamp(saved.fgDate)}</span>
      </div>
      <div>${volField}</div>
    </div>
  </section>`;
}

// ------------------------------------------------------------ 一覧

const FILTERS = [
  ["all", "すべて", () => true],
  ["entry", "エントリー候補", (s) => s.entry],
  ["recent", "最近の候補", (s) => !s.entry && Boolean(recentOf(s, "entry"))],
  ["lit", "条件点灯", (s) => s.count > 0],
  ["warn", "警戒", hasWarning],
  ["hold", "保有継続ゾーン", (s) => s.trend.perfect_order],
];

const SORTS = {
  count: (a, b) => Number(b.entry) - Number(a.entry) || b.count - a.count || a.change_pct - b.change_pct,
  change: (a, b) => a.change_pct - b.change_pct,
  deviation: (a, b) => a.deviation_pct - b.deviation_pct,
  code: (a, b) => a.code.localeCompare(b.code),
};

function lightsHTML(stock) {
  const dots = [1, 2, 3, 4]
    .map((i) => {
      const on = stock.conds.includes(i);
      const strong = i === 3 && stock.bb_level === 3;
      return `<span class="light ${on ? "on" : ""} ${strong ? "strong" : ""}">${i}</span>`;
    })
    .join("");
  const band = stock.bb_level ? `<span class="badge">−${stock.bb_level}σ</span>` : "";
  return `<span class="lights" aria-label="買い条件の点灯 ${stock.count}個">${dots}</span>${band}`;
}

function badgesHTML(stock) {
  const out = [];
  const recentEntry = recentOf(stock, "entry");
  if (isStop(stock)) out.push(`<span class="badge danger">最優先で損切り</span>`);
  if (stock.entry) out.push(`<span class="badge entry">エントリー候補</span>`);
  else if (recentEntry) out.push(`<span class="badge">候補 ${shortDate(recentEntry)}</span>`);
  for (const k of stock.warnings) if (k !== "two_black") out.push(`<span class="badge warn">${LABEL[k]}</span>`);
  if (stock.trend.exit_warning) out.push(`<span class="badge warn">手仕舞い警戒</span>`);
  if (stock.trend.perfect_order) out.push(`<span class="badge good">保有継続ゾーン</span>`);
  if (stock.bounce) out.push(`<span class="badge">100日線で反発</span>`);
  if (stock.divergence) out.push(`<span class="badge">ダイバージェンス</span>`);
  if (stock.watch_only) out.push(`<span class="badge">見るだけ</span>`);
  if (earningsInfo(stock).soon) out.push(`<span class="badge warn">決算前</span>`);
  if (stock.stale) out.push(`<span class="badge">データが古い</span>`);
  for (const theme of stock.themes) out.push(`<span class="badge tag">${esc(theme)}</span>`);
  return out.join("");
}

function rowHTML(d, s) {
  const cls = isStop(s) ? "stop" : s.entry ? "entry" : "";
  return `<li><a class="row ${cls}" href="#${d.market}/${encodeURIComponent(s.code)}">
    <div class="row-top">
      <span class="row-name"><span class="code">${esc(s.code)}</span>${esc(s.name)}</span>
      <span class="row-price num">${price(s.close, d.market)}
        <span class="${signClass(s.change_pct)}">${pct(s.change_pct)}</span></span>
    </div>
    <div class="row-bottom">${lightsHTML(s)}${badgesHTML(s)}</div>
  </a></li>`;
}

function listHTML(d) {
  const test = FILTERS.find((f) => f[0] === ui.filter)[2];
  const q = ui.query.trim().toLowerCase();
  const rows = d.stocks
    .filter((s) => test(s))
    .filter((s) => !ui.theme || s.themes.includes(ui.theme) || s.sector === ui.theme)
    .filter((s) => !q || s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    .sort(SORTS[ui.sort]);
  const head = `<p class="small muted">${d.stocks.length}銘柄中 ${rows.length}銘柄を表示</p>`;
  if (!rows.length) return head + `<p class="muted pad">当てはまる銘柄はありません。</p>`;
  return head + `<ul class="list">${rows.map((s) => rowHTML(d, s)).join("")}</ul>`;
}

function controlsHTML(d) {
  const chips = FILTERS.map(([key, label, test]) => {
    const n = d.stocks.filter(test).length;
    return `<button type="button" data-filter="${key}" class="${ui.filter === key ? "on" : ""}">${label} ${n}</button>`;
  }).join("");
  const themes = [...new Set(d.stocks.flatMap((s) => s.themes))].sort();
  const sectors = Object.keys(d.sectors).sort();
  const option = (value, label) => `<option value="${esc(value)}" ${ui.theme === value ? "selected" : ""}>${esc(label)}</option>`;
  const sortOption = (value, label) => `<option value="${value}" ${ui.sort === value ? "selected" : ""}>${label}</option>`;
  return `
    <div class="chips">${chips}</div>
    <div class="filters">
      <select data-control="theme" aria-label="テーマ・セクター">
        ${option("", "テーマ・業種")}
        <optgroup label="テーマ">${themes.map((t) => option(t, t)).join("")}</optgroup>
        <optgroup label="セクター">${sectors.map((s) => option(s, s + (d.sectors[s].downtrend ? "（下落中）" : ""))).join("")}</optgroup>
      </select>
      <select data-control="sort" aria-label="並び順">
        ${sortOption("count", "点灯数が多い順")}${sortOption("change", "前日比が低い順")}
        ${sortOption("deviation", "乖離が大きい順")}${sortOption("code", "コード順")}
      </select>
      <input type="search" data-control="query" placeholder="銘柄を検索" value="${esc(ui.query)}">
    </div>`;
}

function rulesHTML(d) {
  const b = d.config.buy;
  return `<section class="card small">
    <h2>見送りルール</h2>
    <ul class="plain">
      <li>下落トレンド中のセクターの銘柄は「見るだけ」。</li>
      <li>条件1（前日比 ${b.drop_pct}%以下の急落）は「材料なし」が前提。悪材料の有無は必ず自分で確認する。</li>
      <li>買い条件が点灯しただけでは買わない。反転のサインを待つ。</li>
      <li>決算はまたがない。</li>
      <li>迷ったら入らない。入るなら小ロット。</li>
    </ul>
    <p class="muted">1〜4の丸は買い条件の点灯（1: 急落、2: ${d.config.ma.mid}日線からの乖離、3: ボリンジャーバンド、4: RCI）。赤い3は −3σ 到達。</p>
  </section>`;
}

function renderList(d) {
  app.innerHTML = thermometerHTML(d) + `<div id="controls">${controlsHTML(d)}</div><div id="list">${listHTML(d)}</div>` + rulesHTML(d);
  window.scrollTo(0, ui.listScroll);
}

const refreshList = () => (document.getElementById("list").innerHTML = listHTML(current));

// ------------------------------------------------------------ 銘柄の詳細

function alertsHTML(d, s) {
  const out = [];
  const today = s.reversal.map((k) => eventLabel(s, { k, d: s.date })).join("・");
  const earn = earningsInfo(s);
  if (isStop(s)) out.push(`<div class="alert danger">最優先で損切り<small>下放れ二本黒（窓を開けて下落し、陰線が2本）が出ています。</small></div>`);
  if (s.entry) out.push(`<div class="alert entry">エントリー候補<small>買い条件の点灯後に反転サイン（${esc(today)}）が出ました。</small></div>`);
  if (s.trend.exit_warning)
    out.push(`<div class="alert warn">手仕舞い警戒<small>${d.config.ma.short}日線と${d.config.ma.mid}日線の接近が${s.trend.approach_count}回目で、高値を更新できていません。</small></div>`);
  if (earn.soon) out.push(`<div class="alert warn">決算はまたがない<small>決算発表の予定日は ${shortDate(earn.next)} です。</small></div>`);
  if (s.watch_only) out.push(`<div class="alert info">見るだけ：セクター（${esc(s.sector)}）が下落トレンド中です。</div>`);
  if (s.stale) out.push(`<div class="alert info">最新の株価を取得できませんでした。${shortDate(s.date)} 時点のデータです。</div>`);
  return out.join("");
}

function conditionsHTML(d, s) {
  const b = d.config.buy, ma = d.config.ma;
  const state = (on, text) => `<span class="state ${on ? "on" : "muted"}">${on ? "● " + (text ?? "点灯") : "—"}</span>`;
  const row = (label, value, on, text) => `<tr><td>${label}<br><span class="small muted num">${value}</span></td><td>${state(on, text)}</td></tr>`;
  const key = `news:${d.market}:${s.code}:${s.date}`;
  const newsCheck = s.conds.includes(1)
    ? `<label class="check"><input type="checkbox" data-check="${esc(key)}" ${store.get(key) ? "checked" : ""}>
        <span>悪材料（不祥事・下方修正など）がないことを自分で確認した<br>
        <span class="small muted">条件1は「材料のない急落」が前提です。材料がある下げは対象外にします。</span></span></label>`
    : "";
  return `<section class="card">
    <h2>買いの条件　<span class="num">${s.count} / 4</span> 点灯</h2>
    <table class="kv">
      ${row(`条件1　前日比 ${b.drop_pct}%以下`, pct(s.change_pct), s.conds.includes(1))}
      ${row(`条件2　${ma.mid}日線からの乖離 ${b.ma_deviation_pct}%以下`, pct(s.deviation_pct), s.conds.includes(2))}
      ${row(`条件3　ボリンジャーバンド（${b.bb_period}日）`, `−2σ ${price(s.levels.bb_l2, d.market)} ／ −3σ ${price(s.levels.bb_l3, d.market)}`, s.conds.includes(3), `−${s.bb_level}σ 到達`)}
      ${row(`条件4　RCI（${b.rci_period}日）${b.rci_max}%以下`, number(s.rci, 1) + "%", s.conds.includes(4))}
      ${row(`補助　${ma.mid}日線割れ後、${ma.long}日線で反発`, `${ma.long}日線 ${price(s.levels.ma_long, d.market)}`, s.bounce, "強いサイン")}
      ${row("補助　−2σのダイバージェンス", "1番底が−2σ割れ、2番底は内側", s.divergence, "検出")}
    </table>
    ${newsCheck}
  </section>`;
}

function eventListHTML(s, table, empty) {
  const items = s.recent.filter((e) => e.k in table);
  if (!items.length) return `<p class="muted small">${empty}</p>`;
  return `<ul class="plain">${items
    .map((e) => `<li><span class="num">${shortDate(e.d)}</span>　${esc(eventLabel(s, e))}${e.d === s.date ? "（最新日）" : ""}</li>`)
    .join("")}</ul>`;
}

function signsHTML(d, s) {
  const days = d.config.display.recent_days, entry = d.config.entry;
  const lit = s.lit_days_ago == null ? `直近${entry.lookback_days}営業日に点灯なし` : s.lit_days_ago === 0 ? "最新日に点灯" : `${s.lit_days_ago}営業日前に点灯`;
  const t = s.trend, ma = d.config.ma;
  const approach = !t.in_trend
    ? "上昇トレンドではありません"
    : `${t.approach_count}回` + (t.warning_cleared ? "（高値更新中のため警戒を解除）" : t.exit_warning ? "（手仕舞い警戒）" : "");
  return `
  <section class="card">
    <h2>反転の確認</h2>
    <p class="small muted">買い条件が点灯してから${entry.lookback_days}営業日以内に、下のサインが出たら「エントリー候補」になります。買い条件: ${lit}。</p>
    <h3>直近${days}営業日のサイン</h3>
    ${eventListHTML(s, REVERSAL, "反転のサインは出ていません。")}
  </section>
  <section class="card">
    <h2>警戒・売りサイン</h2>
    <h3>直近${days}営業日のサイン</h3>
    ${eventListHTML(s, WARNING, "警戒のサインは出ていません。")}
  </section>
  <section class="card">
    <h2>トレンド継続モード</h2>
    <table class="kv">
      <tr><td>保有継続ゾーン<br><span class="small muted">${ma.short}日 ＞ ${ma.mid}日 ＞ ${ma.long}日線で、3本とも上向き</span></td>
          <td><span class="state ${t.perfect_order ? "on" : "muted"}">${t.perfect_order ? "● ゾーン内" : "—"}</span></td></tr>
      <tr><td>${ma.short}日線と${ma.mid}日線の接近回数<br><span class="small muted">${d.config.trend.exit_warning_count}回目で手仕舞い警戒</span></td><td>${approach}</td></tr>
      <tr><td>上放れ並び赤（上昇継続）</td><td><span class="state ${t.two_white ? "on" : "muted"}">${t.two_white ? "● 最新日に出現" : "—"}</span></td></tr>
    </table>
  </section>`;
}

function infoHTML(d, s) {
  const zone = d.config.zone;
  const where = s.zone == null ? "—" : s.zone <= zone.low_pct ? "安値圏" : s.zone >= zone.high_pct ? "高値圏" : "中間";
  const sector = d.sectors[s.sector];
  return `<section class="card">
    <h2>その他</h2>
    <table class="kv">
      <tr><td>過去${zone.lookback_days}日の値幅の中での位置</td><td>${where}（下から${number(s.zone, 0)}%）</td></tr>
      <tr><td>${d.config.ma.mid}日線</td><td class="num">${price(s.levels.ma_mid, d.market)}</td></tr>
      <tr><td>${d.config.ma.long}日線</td><td class="num">${price(s.levels.ma_long, d.market)}</td></tr>
      <tr><td>決算発表</td><td>${earningsInfo(s).text}</td></tr>
      <tr><td>セクター</td><td>${esc(s.sector)}${sector?.downtrend ? "（下落トレンド）" : ""}</td></tr>
    </table>
    <p class="small muted">決算日は自動取得した予定日で、変更されることがあります。企業の発表で確認してください。</p>
    <label class="small muted" for="earn-override">決算日を自分で入力する（自動取得より優先。空にすると自動に戻ります）</label>
    <input type="date" id="earn-override" data-earn="${esc(overrideKey(d.market, s.code))}" value="${esc(store.get(overrideKey(d.market, s.code), ""))}">
  </section>`;
}

async function renderDetail(d, code) {
  const s = d.stocks.find((x) => x.code === code);
  if (!s) {
    app.innerHTML = `<p class="pad">銘柄が見つかりません。<a href="#${d.market}">一覧へ戻る</a></p>`;
    return;
  }
  const held = loadPositions().some((p) => !p.sell && p.market === d.market && p.code === code);
  app.innerHTML = `
    <a class="btn back" href="#${d.market}">← 一覧へ戻る</a>
    <section class="card">
      <div class="detail-head">
        <div><div class="small muted">${esc(s.code)}　${esc(s.sector)}</div><h2>${esc(s.name)}</h2></div>
        <div class="num" style="text-align:right"><div class="price">${price(s.close, d.market)}</div>
          <div class="${signClass(s.change_pct)}">${pct(s.change_pct)}<span class="small muted">　${shortDate(s.date)}</span></div></div>
      </div>
      <div class="row-bottom">${badgesHTML(s)}</div>
      ${alertsHTML(d, s)}
      <div id="stock-chart" class="chart tall"><p class="muted small">チャートを読み込み中…</p></div>
      ${legendHTML(d.config)}
      <p class="small muted">▲ エントリー候補　▼ 警戒・売りサイン　● 補助サイン</p>
    </section>
    ${conditionsHTML(d, s)}${signsHTML(d, s)}${infoHTML(d, s)}
    <section class="card">
      <h2>ポジション</h2>
      ${held ? `<p class="small">この銘柄を保有中です。<a href="#portfolio">保有・記録を見る</a></p>` : ""}
      <p class="small muted">迷ったら入らない。入るなら小ロット。買った理由に合わせて出口（利確・損切り）を表示します。</p>
      <a class="btn primary" href="#portfolio/new/${d.market}/${encodeURIComponent(s.code)}">ポジションを登録</a>
    </section>`;
  window.scrollTo(0, 0);
  const el = document.getElementById("stock-chart");
  try {
    const data = await getJSON(`data/${d.market}/${encodeURIComponent(code)}.json`);
    if (el.isConnected) drawChart(el, data, { digits: d.decimals, labelDays: d.config.display.recent_days });
  } catch (err) {
    el.innerHTML = `<p class="muted small">チャートを表示できません。${esc(err.message)}</p>`;
  }
}

// ------------------------------------------------------------ 画面の切り替え

async function loadPortfolioContext() {
  const [jp, us] = await Promise.all(MARKETS.map((m) => getJSON(`data/${m}.json`)));
  const [mjp, mus] = await Promise.all(MARKETS.map((m) => getJSON(`data/${m}_momentum.json`).catch(() => null)));
  const fx = await getJSON("data/fx.json").catch(() => null);
  return { markets: { jp, us }, momentum: { jp: mjp, us: mus }, fx };
}

// 上部のタブ（市場）と、その下の切り替え（逆張り／順張り）の表示を合わせる
function showTabs(market, mode) {
  for (const tab of document.querySelectorAll("#market-tabs a")) {
    tab.classList.toggle("on", tab.dataset.market === (market ?? "portfolio"));
    if (MARKETS.includes(tab.dataset.market)) tab.href = `#${tab.dataset.market}${mode === "momentum" ? "/m" : ""}`;
  }
  const modes = document.getElementById("mode-tabs");
  modes.hidden = !market;
  for (const tab of modes.querySelectorAll("a")) {
    tab.classList.toggle("on", tab.dataset.mode === mode);
    tab.href = `#${market}${tab.dataset.mode === "momentum" ? "/m" : ""}`;
  }
}

async function route() {
  const [first, second, third, fourth, fifth] = decodeURIComponent(location.hash.slice(1)).split("/");
  const isPortfolio = first === "portfolio";
  const market = isPortfolio ? null : MARKETS.includes(first) ? first : store.get("market", "jp");
  const mode = !isPortfolio && second === "m" ? "momentum" : "contrarian";
  showTabs(market, mode);
  try {
    if (isPortfolio) {
      const context = await loadPortfolioContext();
      document.getElementById("as-of").textContent = "";
      if (second === "new" && MARKETS.includes(third) && fourth) {
        const kind = fifth === "m" ? "momentum" : "contrarian";
        current = context.markets[third];
        const folder = kind === "momentum" ? `${third}/m` : third;
        const chart = await getJSON(`data/${folder}/${encodeURIComponent(fourth)}.json`).catch(() => null);
        renderNewPosition(app, context, third, fourth, chart, kind);
      } else {
        renderPortfolio(app, context);
      }
      return;
    }
    store.set("market", market);
    if (mode === "momentum") {
      const data = await getJSON(`data/${market}_momentum.json`);
      current = await getJSON(`data/${market}.json`);
      document.getElementById("as-of").textContent = `${shortDate(data.as_of)} 終値時点`;
      if (third) renderMomentumDetail(app, data, third);
      else renderMomentumList(app, data);
      return;
    }
    if (current && current.market !== market) Object.assign(ui, { theme: "", query: "", listScroll: 0 });
    current = await getJSON(`data/${market}.json`);
  } catch (err) {
    app.innerHTML = `<p class="pad">データを読み込めませんでした。時間をおいて開き直してください。<br><span class="small muted">${esc(err.message)}</span></p>`;
    return;
  }
  document.getElementById("as-of").textContent = `${shortDate(current.as_of)} 終値時点`;
  if (second) renderDetail(current, second);
  else renderList(current);
}

app.addEventListener("click", async (event) => {
  const filter = event.target.closest("[data-filter]");
  if (filter && document.getElementById("controls")) {
    ui.filter = filter.dataset.filter;
    document.getElementById("controls").innerHTML = controlsHTML(current);
    refreshList();
    return;
  }
  if (event.target.closest("#list a.row")) ui.listScroll = window.scrollY;
  const action = event.target.closest("[data-action='index-chart']");
  if (action) {
    const box = document.getElementById("index-chart");
    if (box.classList.toggle("chart")) {
      action.textContent = "指数のチャートを閉じる";
      const data = await getJSON(`data/${current.market}/_index.json`);
      drawChart(box, data, { digits: 0, showBands: false });
    } else {
      action.textContent = "指数のチャートを表示";
      box.innerHTML = "";
    }
  }
});

app.addEventListener("input", (event) => {
  const el = event.target;
  if (el.dataset.thermo) {
    const key = `thermo:${current.market}`;
    const saved = store.get(key, {});
    const value = el.value === "" ? null : Number(el.value);
    saved[el.dataset.thermo] = value;
    saved[el.dataset.thermo + "Date"] = value == null ? null : todayISO();
    store.set(key, saved);
    document.getElementById("verdict").innerHTML = verdictHTML(current);
  } else if (el.dataset.control === "query") {
    ui.query = el.value;
    refreshList();
  }
});

app.addEventListener("change", (event) => {
  const el = event.target;
  if (el.dataset.control === "theme" || el.dataset.control === "sort") {
    ui[el.dataset.control] = el.value;
    refreshList();
  } else if (el.dataset.earn) {
    if (el.value) store.set(el.dataset.earn, el.value);
    else store.remove(el.dataset.earn);
    route();
  } else if (el.dataset.check) {
    if (el.checked) store.set(el.dataset.check, true);
    else store.remove(el.dataset.check);
  }
});

initPortfolio(app, route);
initMomentum(app, getJSON);
window.addEventListener("hashchange", route);
route();

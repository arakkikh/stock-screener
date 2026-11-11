// 順張りモード（ミネルヴィニ式）の画面。逆張りの一覧とは混ぜない。
import { esc, price, number, pct, signClass, shortDate } from "./format.js";
import { drawChart, legendItems, LINE_COLORS } from "./chart.js";
import { earningsInfo } from "./earnings.js";
import { loadPositions } from "./portfolio.js";

const ui = { filter: "passed", theme: "", sort: "rs", query: "", listScroll: 0, market: null };
let current = null;
let getJSON = null;

export const VCP_STATUS = {
  forming: "VCP形成中",
  breakout: "ブレイクアウト",
  weak: "上抜け（出来高不足）",
  failed: "上抜け後に反落",
};

const FILTERS = [
  ["passed", "全条件合格", (s) => s.passed],
  ["vcp", "VCP", (s) => Boolean(s.vcp)],
  ["breakout", "ブレイクアウト", (s) => s.vcp?.status === "breakout"],
  ["near", "7条件以上", (s) => s.count >= 7],
  ["all", "すべて", () => true],
];

const SORTS = {
  rs: (a, b) => (b.rs ?? 0) - (a.rs ?? 0) || b.count - a.count,
  high: (a, b) => b.from_high_pct - a.from_high_pct,
  pivot: (a, b) => Math.abs(a.vcp?.to_pivot_pct ?? 999) - Math.abs(b.vcp?.to_pivot_pct ?? 999) || (b.rs ?? 0) - (a.rs ?? 0),
  count: (a, b) => b.count - a.count || (b.rs ?? 0) - (a.rs ?? 0),
  code: (a, b) => a.code.localeCompare(b.code),
};

function conditionList(cfg) {
  const m = cfg.momentum, t = m.template, ma = m.ma;
  return [
    `株価 ＞ ${ma.mid}日線 かつ 株価 ＞ ${ma.slow}日線`,
    `${ma.mid}日線 ＞ ${ma.slow}日線`,
    `${ma.slow}日線が1か月以上上向き`,
    `${ma.fast}日線 ＞ ${ma.mid}日線 かつ ${ma.fast}日線 ＞ ${ma.slow}日線`,
    `株価 ＞ ${ma.fast}日線`,
    `52週安値から +${t.above_low_pct}% 以上`,
    `52週高値から −${t.within_high_pct}% 以内`,
    `相対強度（RS）が ${t.rs_min} 以上`,
  ];
}

// ------------------------------------------------------------ 一覧

function badgesHTML(d, s) {
  const out = [];
  out.push(`<span class="badge ${s.passed ? "good" : ""}">${s.count}/8</span>`);
  out.push(`<span class="badge">RS ${s.rs ?? "—"}</span>`);
  out.push(`<span class="badge">高値から ${pct(s.from_high_pct, 1)}</span>`);
  if (s.vcp) {
    const v = s.vcp;
    const cls = v.status === "breakout" ? "entry" : v.status === "failed" ? "warn" : "";
    const extra = v.status === "forming" ? `　ピボットまで ${pct(v.to_pivot_pct, 1)}` : "";
    out.push(`<span class="badge ${cls}">${VCP_STATUS[v.status]}${extra}</span>`);
  }
  if (s.ma_break) out.push(`<span class="badge warn">${d.config.momentum.ma.fast}日線割れ</span>`);
  if (s.earnings && earningsInfo(d.market, s).soon) out.push(`<span class="badge warn">決算前</span>`);
  if (s.stale) out.push(`<span class="badge">データが古い</span>`);
  for (const theme of s.themes) out.push(`<span class="badge tag">${esc(theme)}</span>`);
  return out.join("");
}

function rowHTML(d, s) {
  const cls = s.vcp?.status === "breakout" ? "entry" : "";
  return `<li><a class="row ${cls}" href="#${d.market}/m/${encodeURIComponent(s.code)}">
    <div class="row-top">
      <span class="row-name"><span class="code">${esc(s.code)}</span>${esc(s.name)}</span>
      <span class="row-price num">${price(s.close, d.market)}
        <span class="${signClass(s.change_pct)}">${pct(s.change_pct)}</span></span>
    </div>
    <div class="row-bottom">${badgesHTML(d, s)}</div>
  </a></li>`;
}

function listHTML(d) {
  const test = FILTERS.find((f) => f[0] === ui.filter)[2];
  const q = ui.query.trim().toLowerCase();
  const rows = d.stocks
    .filter(test)
    .filter((s) => !ui.theme || s.themes.includes(ui.theme) || s.sector === ui.theme)
    .filter((s) => !q || s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    .sort(SORTS[ui.sort]);
  const head = `<p class="small muted">${d.stocks.length}銘柄中 ${rows.length}銘柄を表示</p>`;
  if (!rows.length) return head + `<p class="muted pad">当てはまる銘柄はありません。</p>`;
  return head + `<ul class="list">${rows.map((s) => rowHTML(d, s)).join("")}</ul>`;
}

function controlsHTML(d) {
  const chips = FILTERS.map(
    ([key, label, test]) => `<button type="button" data-mo-filter="${key}" class="${ui.filter === key ? "on" : ""}">${label} ${d.stocks.filter(test).length}</button>`
  ).join("");
  const themes = [...new Set(d.stocks.flatMap((s) => s.themes))].sort();
  const sectors = [...new Set(d.stocks.map((s) => s.sector))].sort();
  const option = (value, label, selected) => `<option value="${esc(value)}" ${selected === value ? "selected" : ""}>${esc(label)}</option>`;
  return `
    <div class="chips">${chips}</div>
    <div class="filters">
      <select data-mo-control="theme" aria-label="テーマ・セクター">
        ${option("", "テーマ・業種", ui.theme)}
        <optgroup label="テーマ">${themes.map((t) => option(t, t, ui.theme)).join("")}</optgroup>
        <optgroup label="セクター">${sectors.map((s) => option(s, s, ui.theme)).join("")}</optgroup>
      </select>
      <select data-mo-control="sort" aria-label="並び順">
        ${option("rs", "RSが高い順", ui.sort)}${option("high", "高値に近い順", ui.sort)}
        ${option("pivot", "ピボットに近い順", ui.sort)}${option("count", "合格数が多い順", ui.sort)}${option("code", "コード順", ui.sort)}
      </select>
      <input type="search" data-mo-control="query" placeholder="銘柄を検索" value="${esc(ui.query)}">
    </div>`;
}

function introHTML(d) {
  const passed = d.stocks.filter((s) => s.passed).length;
  const v = d.config.momentum.vcp;
  return `<section class="card">
    <h2>順張りモード（ミネルヴィニ式）</h2>
    <p class="small">対象: ${esc(d.universe)}（判定できた ${d.stocks.length} 銘柄）。トレンドテンプレートの8条件すべてに合格したのは <strong>${passed} 銘柄</strong>です。</p>
    <p class="small muted">強い上昇トレンドの銘柄が、値動きを小さくしながら（VCP）高値を抜けるところを狙う考え方です。逆張りとは逆の発想なので、候補は別のリストにしています。RSは、この対象銘柄の中での強さの順位（1〜99）です。</p>
    <p class="small muted">VCPの機械判定は目安です（直近${v.lookback_days}営業日のベースで、押しが${v.min_contractions}〜${v.max_contractions}回、段階的に浅くなる形）。必ずチャートで確かめてください。</p>
  </section>`;
}

function rulesHTML(d) {
  const x = d.config.momentum.exit, ma = d.config.momentum.ma, v = d.config.momentum.vcp;
  return `<section class="card small">
    <h2>順張りのルール</h2>
    <ul class="plain">
      <li>買うのは、ピボットを出来高増（${v.volume_avg_days}日平均の${v.breakout_volume_ratio}倍以上）で上抜けたとき。</li>
      <li>損切りは買値から ${x.stop_loss_pct}%。${x.stop_warn_pct}% で警告します。</li>
      <li>${ma.fast}日線を出来高を伴って割ったら警戒。</li>
      <li>買う理由と売る理由は同じ種類にする。順張りで買ったものを、下がったからと逆張りの理屈で持ち続けない。</li>
      <li>決算はまたがない。迷ったら入らない。入るなら小ロット。</li>
    </ul>
  </section>`;
}

function refreshList() {
  document.getElementById("mo-list").innerHTML = listHTML(current);
}

export function renderMomentumList(app, d) {
  if (ui.market !== d.market) Object.assign(ui, { theme: "", query: "", listScroll: 0, market: d.market });
  current = d;
  app.innerHTML = introHTML(d) + `<div id="mo-controls">${controlsHTML(d)}</div><div id="mo-list">${listHTML(d)}</div>` + rulesHTML(d);
  window.scrollTo(0, ui.listScroll);
}

// ------------------------------------------------------------ 詳細

function alertsHTML(d, s) {
  const out = [];
  const v = s.vcp, ma = d.config.momentum.ma;
  if (v?.status === "breakout")
    out.push(`<div class="alert entry">ブレイクアウト<small>${shortDate(v.breakout_date)} にピボット ${price(v.pivot, d.market)} を、平均の${number(v.volume_ratio, 1)}倍の出来高で上抜けました。</small></div>`);
  if (v?.status === "weak")
    out.push(`<div class="alert info">ピボットを上抜けましたが、出来高が足りません（平均の${number(v.volume_ratio, 1)}倍）。</div>`);
  if (v?.status === "failed")
    out.push(`<div class="alert warn">上抜け後に反落<small>${shortDate(v.breakout_date)} にピボットを上抜けましたが、終値がピボット以下に戻っています。</small></div>`);
  if (s.ma_break)
    out.push(`<div class="alert warn">${ma.fast}日線割れ<small>${shortDate(s.ma_break)} に、出来高を伴って${ma.fast}日線を割りました。</small></div>`);
  const earn = s.earnings ? earningsInfo(d.market, s) : null;
  if (earn?.soon) out.push(`<div class="alert warn">決算はまたがない<small>決算発表の予定日は ${shortDate(earn.next)} です。</small></div>`);
  if (s.stale) out.push(`<div class="alert info">最新の株価を取得できませんでした。${shortDate(s.date)} 時点のデータです。</div>`);
  return out.join("");
}

function templateHTML(d, s) {
  const values = [
    `${d.config.momentum.ma.mid}日線 ${price(s.ma_mid, d.market)} ／ ${d.config.momentum.ma.slow}日線 ${price(s.ma_slow, d.market)}`,
    "", "", `${d.config.momentum.ma.fast}日線 ${price(s.ma_fast, d.market)}`, "",
    pct(s.from_low_pct, 1), pct(s.from_high_pct, 1), `RS ${s.rs ?? "—"}`,
  ];
  const rows = conditionList(d.config)
    .map((label, i) => `<tr><td>${i + 1}　${label}${values[i] ? `<br><span class="small muted num">${values[i]}</span>` : ""}</td>
      <td><span class="state ${s.conds[i] ? "on" : "muted"}">${s.conds[i] ? "● 合格" : "✕"}</span></td></tr>`)
    .join("");
  return `<section class="card">
    <h2>トレンドテンプレート　<span class="num">${s.count} / 8</span>${s.passed ? "　全条件合格" : ""}</h2>
    <table class="kv exit">${rows}</table>
  </section>`;
}

function vcpHTML(d, s) {
  if (!s.passed) return `<section class="card"><h2>VCP</h2><p class="small muted">VCPは、トレンドテンプレートに全条件合格した銘柄だけを判定します。</p></section>`;
  const v = s.vcp;
  if (!v) return `<section class="card"><h2>VCP</h2><p class="small muted">VCP（押しが段階的に浅くなる形）は検出されていません。</p></section>`;
  const legs = v.legs
    .map((leg, i) => `<tr><td>収縮${i + 1}<br><span class="small muted num">${shortDate(leg.hd)} ${price(leg.high, d.market)} → ${shortDate(leg.ld)} ${price(leg.low, d.market)}</span></td>
      <td class="num">−${number(leg.depth, 1)}%</td></tr>`)
    .join("");
  return `<section class="card">
    <h2>VCP　${VCP_STATUS[v.status]}</h2>
    <table class="kv exit">
      ${legs}
      <tr><td>収縮に合わせて出来高が減っている</td><td><span class="state ${v.volume_dry ? "on" : "muted"}">${v.volume_dry ? "● はい" : "✕ いいえ"}</span></td></tr>
      <tr><td>ピボット（直近の収縮の高値）<br><span class="small muted">${shortDate(v.pivot_date)} の高値</span></td><td class="num"><strong>${price(v.pivot, d.market)}</strong></td></tr>
      <tr><td>${v.to_pivot_pct >= 0 ? "現在値からピボットまで" : "ピボットを上回っている幅"}</td><td class="num">${pct(Math.abs(v.to_pivot_pct), 1)}</td></tr>
    </table>
    <p class="small muted">機械判定は目安です。チャートの点線（ピボット）と ①②… の印で、押しが浅くなっているかを確かめてください。</p>
  </section>`;
}

function chartOptions(d, s) {
  const ma = d.config.momentum.ma;
  const lines = [
    { key: "m_f", color: LINE_COLORS.ma_s, width: 2 },
    { key: "m_m", color: LINE_COLORS.ma_m, width: 2 },
    { key: "m_s", color: LINE_COLORS.ma_l, width: 2 },
  ];
  const style = getComputedStyle(document.documentElement);
  const accent = style.getPropertyValue("--accent").trim(), muted = style.getPropertyValue("--muted").trim();
  const markers = [], priceLines = [];
  if (s.vcp) {
    s.vcp.legs.forEach((leg, i) => {
      markers.push({ time: leg.hd, position: "aboveBar", color: muted, shape: "arrowDown", text: "①②③④"[i] });
      markers.push({ time: leg.ld, position: "belowBar", color: muted, shape: "circle", text: `−${number(leg.depth, 0)}%` });
    });
    if (s.vcp.breakout_date) markers.push({ time: s.vcp.breakout_date, position: "belowBar", color: accent, shape: "arrowUp", text: "上抜け" });
    markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    priceLines.push({ price: s.vcp.pivot, title: "ピボット", color: accent });
  }
  const legend = legendItems([
    [LINE_COLORS.ma_s, `${ma.fast}日線`], [LINE_COLORS.ma_m, `${ma.mid}日線`], [LINE_COLORS.ma_l, `${ma.slow}日線`],
    ...(s.vcp ? [[accent, "ピボット（点線）"]] : []),
  ]);
  return { options: { digits: d.decimals, lines, markers, priceLines, bars: 130 }, legend };
}

export async function renderMomentumDetail(app, d, code) {
  current = d;
  const s = d.stocks.find((x) => x.code === code);
  if (!s) {
    app.innerHTML = `<p class="pad">銘柄が見つかりません。<a href="#${d.market}/m">一覧へ戻る</a></p>`;
    return;
  }
  const held = loadPositions().some((p) => !p.sell && p.market === d.market && p.code === code);
  const { options, legend } = chartOptions(d, s);
  app.innerHTML = `
    <a class="btn back" href="#${d.market}/m">← 一覧へ戻る</a>
    <section class="card">
      <div class="detail-head">
        <div><div class="small muted">${esc(s.code)}　${esc(s.sector)}</div><h2>${esc(s.name)}</h2></div>
        <div class="num" style="text-align:right"><div class="price">${price(s.close, d.market)}</div>
          <div class="${signClass(s.change_pct)}">${pct(s.change_pct)}<span class="small muted">　${shortDate(s.date)}</span></div></div>
      </div>
      <div class="row-bottom">${badgesHTML(d, s)}</div>
      ${alertsHTML(d, s)}
      ${s.passed
        ? `<div id="mo-chart" class="chart tall"><p class="muted small">チャートを読み込み中…</p></div>${legend}`
        : `<p class="small muted">チャートは、全条件に合格した銘柄だけ表示します。</p>`}
    </section>
    ${templateHTML(d, s)}${vcpHTML(d, s)}
    <section class="card">
      <h2>その他</h2>
      <table class="kv">
        <tr><td>今日の出来高（${d.config.momentum.vcp.volume_avg_days}日平均との比）</td><td class="num">${s.volume_ratio == null ? "—" : number(s.volume_ratio, 2) + "倍"}</td></tr>
        <tr><td>決算発表</td><td>${s.earnings ? earningsInfo(d.market, s).text : "未取得（合格銘柄だけ取得）"}</td></tr>
        <tr><td>セクター</td><td>${esc(s.sector)}</td></tr>
      </table>
    </section>
    <section class="card">
      <h2>ポジション</h2>
      ${held ? `<p class="small">この銘柄を保有中です。<a href="#portfolio">保有・記録を見る</a></p>` : ""}
      <p class="small muted">迷ったら入らない。入るなら小ロット。順張りで買ったら、出口も順張りのルール（損切り ${d.config.momentum.exit.stop_loss_pct}%）で決めます。</p>
      <a class="btn primary" href="#portfolio/new/${d.market}/${encodeURIComponent(s.code)}/m">ポジションを登録</a>
    </section>`;
  window.scrollTo(0, 0);
  const el = document.getElementById("mo-chart");
  if (!el) return;
  try {
    const data = await getJSON(`data/${d.market}/m/${encodeURIComponent(code)}.json`);
    if (el.isConnected) drawChart(el, data, options);
  } catch (err) {
    el.innerHTML = `<p class="muted small">チャートを表示できません。${esc(err.message)}</p>`;
  }
}

// ------------------------------------------------------------ 操作

export function initMomentum(app, loader) {
  getJSON = loader;
  app.addEventListener("click", (event) => {
    const filter = event.target.closest("[data-mo-filter]");
    if (filter) {
      ui.filter = filter.dataset.moFilter;
      document.getElementById("mo-controls").innerHTML = controlsHTML(current);
      refreshList();
    } else if (event.target.closest("#mo-list a.row")) {
      ui.listScroll = window.scrollY;
    }
  });
  app.addEventListener("input", (event) => {
    if (event.target.dataset.moControl === "query") {
      ui.query = event.target.value;
      refreshList();
    }
  });
  app.addEventListener("change", (event) => {
    const key = event.target.dataset.moControl;
    if (key === "theme" || key === "sort") {
      ui[key] = event.target.value;
      refreshList();
    }
  });
}

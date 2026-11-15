// 検証結果（バックテスト）のページ。過去10年のデータで、各サインのその後の成績を見る。
import { esc, number, shortDate } from "./format.js";
import { LABEL, REVERSAL, WARNING } from "./labels.js";

const ui = { horizon: null, hold: null, mohold: null, query: "" };
let current = null;
let currentForward = null, currentCfg = null;

const BUY = {
  cond1: "条件1（急落）", cond2: "条件2（25日線乖離）", cond3: "条件3（−2σ以下）", bb3: "条件3（−3σ到達）", cond4: "条件4（RCI）",
  count1: "点灯1個以上", count2: "点灯2個以上", count3: "点灯3個以上", count4: "4個すべて点灯",
  bounce: LABEL.bounce, divergence: LABEL.divergence,
};
const STRATEGY = {
  c1: "条件1で買い → −2.5%の水準で利確", c2: "条件2で買い → 25日線で利確",
  c3_2: "−2σで買い → 中央線で利確（−3σ割れで損切り）", c3_3: "−3σで買い → 中央線で利確",
  count2: "点灯2個以上で買い → 25日線で利確", count3: "点灯3個以上で買い → 25日線で利確",
  entry: "エントリー候補で買い → 25日線で利確",
};

const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${number(Math.abs(v), 2)}%`);
const count = (n) => n.toLocaleString("ja-JP");

// 成績1つ分のセル。base（何もしないで買った場合の平均）より良ければ色を付ける
function cell(stats, base) {
  if (!stats) return `<td class="muted">—</td>`;
  const cls = base == null ? "" : stats.mean > base ? "better" : "worse";
  return `<td><b class="num ${cls}">${pct(stats.mean)}</b><br><span class="small muted num">勝率${number(stats.win, 0)}%<br>${count(stats.n)}回</span></td>`;
}

function tradeCell(stats) {
  if (!stats) return `<td class="muted">—</td>`;
  return `<td><b class="num">${pct(stats.mean)}</b><br><span class="small muted num">勝率${number(stats.win, 0)}%・${count(stats.n)}回<br>
    平均${number(stats.days, 0)}日保有<br>利確${number(stats.take, 0)}%・損切${number(stats.stop, 0)}%</span></td>`;
}

function head(d, first = "サイン") {
  const p = d.period;
  return `<tr><th>${first}</th><th>古い期間<br><span class="small">〜${p.split.slice(0, 7)}</span></th><th>直近2年<br><span class="small">${p.split.slice(0, 7)}〜</span></th></tr>`;
}

function signalTable(d, signals, table, h) {
  const base = { train: signals.baseline.train.h[h]?.mean, test: signals.baseline.test.h[h]?.mean };
  const rows = Object.entries(table)
    .filter(([key]) => signals[key])
    .map(([key, label]) => `<tr><td>${esc(label)}</td>${cell(signals[key].train.h[h], base.train)}${cell(signals[key].test.h[h], base.test)}</tr>`)
    .join("");
  return `<div class="scroll"><table class="bt">${head(d)}
    <tr class="base"><td>いつ買っても（比較の基準）</td>${cell(signals.baseline.train.h[h])}${cell(signals.baseline.test.h[h])}</tr>${rows}</table></div>`;
}

const select = (name, values, selected, label) =>
  `<label class="small muted">${label} <select data-bt="${name}">${values
    .map((v) => `<option value="${v}" ${String(v) === String(selected) ? "selected" : ""}>${v}日</option>`)
    .join("")}</select></label>`;

// ------------------------------------------------------------ 逆張り

function contrarianHTML(d) {
  const c = d.contrarian, b = d.config.backtest;
  const h = String(ui.horizon ?? b.main_horizon), hold = Number(ui.hold ?? 20);
  const trades = c.trades.filter((t) => t.max_hold === hold);
  const tradeRows = Object.entries(STRATEGY)
    .map(([key, label]) => {
      const group = trades.filter((t) => t.strategy === key).sort((a, b2) => (a.stop ?? 0) - (b2.stop ?? 0) || 0);
      const order = [null, ...b.stop_pcts.filter((s) => s != null).sort((x, y) => y - x)];
      return order
        .map((stop, i) => {
          const t = group.find((x) => x.stop === stop);
          if (!t) return "";
          return `<tr><td>${i === 0 ? `<b>${esc(label)}</b><br>` : ""}<span class="small muted">${stop == null ? "損切りなし" : `損切り ${stop}%`}</span></td>${tradeCell(t.train)}${tradeCell(t.test)}</tr>`;
        })
        .join("");
    })
    .join("");
  const sweeps = c.sweeps
    .map((s) => `<h3>${esc(s.label)}</h3><div class="scroll"><table class="bt">${head(d, "値")}${s.rows
      .map((r) => `<tr class="${r.current ? "base" : ""}"><td>${esc(String(r.value))}${r.current ? "<br><span class='small muted'>現在の設定</span>" : ""}</td>${cell(r.train)}${cell(r.test)}</tr>`)
      .join("")}</table></div>`)
    .join("");
  return `
  <section class="card">
    <h2>逆張り：サインが出たあとの成績</h2>
    <p class="small muted">サインの翌営業日の始値で買い、${select("horizon", b.horizons, h, "")}後の終値で売った場合の平均です。対象は ${esc(d.universe.contrarian)} の ${c.stocks} 銘柄。
      <b class="better">色つき</b>は「いつ買っても」の平均を上回ったもの。</p>
    <h3>買いの条件</h3>${signalTable(d, c.signals, BUY, h)}
    <h3>反転の確認サイン</h3>${signalTable(d, c.signals, { ...REVERSAL, entry: LABEL.entry }, h)}
    <h3>警戒・売りサイン</h3>
    <p class="small muted">警戒サインは「その後に下がる」ことを期待するものなので、基準より<b>低い</b>ほうが当たっています。</p>
    ${signalTable(d, c.signals, { ...WARNING, exit_warning: "手仕舞い警戒", two_white: LABEL.two_white }, h)}
  </section>
  <section class="card">
    <h2>逆張り：出口ルールつきの売買</h2>
    <p class="small muted">出口ルールどおりに売買した場合の1回あたりの成績です。最大 ${select("hold", b.max_hold_days, hold, "")} 持ったら手仕舞い。同じ銘柄は同時に1回分だけ持ちます。「シナリオ崩壊」は機械的に判定できないため、損切り%で代用しています。</p>
    <div class="scroll"><table class="bt">${head(d, "買い方と損切り")}${tradeRows}</table></div>
  </section>
  <section class="card">
    <h2>逆張り：しきい値を変えた場合</h2>
    <p class="small muted">${b.main_horizon}営業日後の成績です。古い期間で良かった値が、直近2年でも通用しているかを見ます。</p>
    ${sweeps}
  </section>`;
}

function rciHTML(d) {
  const b = d.config.backtest;
  const q = ui.query.trim().toLowerCase();
  const rows = d.contrarian.rci
    .filter((r) => !q || r.code.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
    .map((r) => {
      const cells = b.rci_levels
        .map((lv) => {
          const s = r.levels[String(lv)];
          if (!s) return `<td class="muted">—</td>`;
          const weak = s.n < b.rci_min_samples;
          return `<td class="${r.best === lv ? "best" : ""}"><span class="num ${weak ? "muted" : ""}">${pct(s.mean)}</span><br><span class="small muted num">${s.n}回</span></td>`;
        })
        .join("");
      return `<tr><td>${esc(r.name)}<br><span class="small muted">${esc(r.code)}</span></td>${cells}</tr>`;
    })
    .join("");
  return `<section class="card">
    <h2>銘柄ごとの RCI の水準</h2>
    <p class="small muted">RCI がその水準以下に入った最初の日に買い、${b.main_horizon}営業日後に売った場合の平均（全期間）。<b>太枠</b>は、${b.rci_min_samples}回以上ある水準の中でいちばん良かったもの。
      1銘柄だけだと回数が少なく、偶然に左右されます。参考程度に見てください。</p>
    <input type="search" data-bt="query" placeholder="銘柄を検索" value="${esc(ui.query)}">
    <div class="scroll" id="bt-rci"><table class="bt"><tr><th>銘柄</th>${b.rci_levels.map((lv) => `<th>${lv}%</th>`).join("")}</tr>${rows}</table></div>
  </section>`;
}

// ------------------------------------------------------------ 順張り

function momentumHTML(d) {
  const m = d.momentum, b = d.config.backtest;
  if (!m) return "";
  const hs = b.momentum_horizons.map(String);
  const h = hs.includes(String(ui.mohorizon)) ? String(ui.mohorizon) : hs[1];
  const base = { train: m.baseline.train.h[h]?.mean, test: m.baseline.test.h[h]?.mean };
  const variantRows = m.variants
    .map((v) => `
      <tr class="${v.current ? "base" : ""}"><td><b>${esc(v.label)}</b><br><span class="small muted">出来高を伴う上抜け</span></td>${cell(v.breakout.train.h[h], base.train)}${cell(v.breakout.test.h[h], base.test)}</tr>
      <tr><td><span class="small muted">出来高不足の上抜け</span></td>${cell(v.weak.train.h[h], base.train)}${cell(v.weak.test.h[h], base.test)}</tr>`)
    .join("");
  const now = m.variants.find((v) => v.current);
  const trades = (now?.trades ?? [])
    .map((t) => `<tr><td>最大 ${t.max_hold}日</td>${tradeCell(t.train)}${tradeCell(t.test)}</tr>`)
    .join("");
  const x = d.config.momentum.exit;
  return `
  <section class="card">
    <h2>順張り：VCPの上抜けのあとの成績</h2>
    <p class="small muted">トレンドテンプレート合格中の銘柄が、VCPのピボットを上抜けた翌営業日の始値で買い、${select("mohorizon", b.momentum_horizons, h, "")}後に売った場合。対象は ${esc(d.universe.momentum)} の ${m.stocks} 銘柄。</p>
    <div class="scroll"><table class="bt">${head(d, "条件")}
      <tr class="base"><td>いつ買っても（比較の基準）</td>${cell(m.baseline.train.h[h])}${cell(m.baseline.test.h[h])}</tr>
      <tr><td>テンプレート合格中の全日</td>${cell(m.template.train.h[h], base.train)}${cell(m.template.test.h[h], base.test)}</tr>
      ${variantRows}</table></div>
    <h3>出口ルールつきの売買（現在の設定）</h3>
    <p class="small muted">出来高を伴う上抜けで買い、買値から ${x.stop_loss_pct}% で損切り、${d.config.momentum.ma.fast}日線を出来高を伴って割ったら手仕舞い。</p>
    <div class="scroll"><table class="bt">${head(d, "保有の上限")}${trades}</table></div>
  </section>`;
}

// ------------------------------------------------------------ 実運用での成績（フォワードテスト）

const FORWARD_GROUPS = [
  ["entry", "逆張り：エントリー候補", "contrarian"],
  ["breakout", "順張り：ブレイクアウト（出来高を伴う上抜け）", "momentum"],
  ["warn", "逆張り：警戒サイン（すべて）", "contrarian"],
];

// 成績のセル（実運用）。警戒サインは「下がった割合」を的中率として出す
function liveCell(stats, warn) {
  if (!stats) return `<td class="muted">—</td>`;
  const rate = warn ? `的中${number(stats.hit, 0)}%` : `勝率${number(stats.win, 0)}%`;
  return `<td><b class="num">${pct(stats.mean)}</b><br><span class="small muted num">${rate}<br>${count(stats.n)}件</span></td>`;
}

function backtestCell(stats, warn) {
  if (!stats) return `<td class="muted">—</td>`;
  const rate = warn ? "" : `勝率${number(stats.win, 0)}%<br>`;
  return `<td><span class="num">${pct(stats.mean)}</span><br><span class="small muted num">${rate}${count(stats.n)}回</span></td>`;
}

// 警戒サインは「下がれば当たり」なので、指数より低いほうに色を付ける
function excessCell(stats, warn = false) {
  if (!stats || stats.excess == null) return `<td class="muted">—</td>`;
  const good = warn ? stats.excess < 0 : stats.excess > 0;
  return `<td><b class="num ${good ? "better" : "worse"}">${pct(stats.excess)}</b><br><span class="small muted num">指数 ${pct(stats.index)}</span></td>`;
}

// バックテストの、同じシグナル・同じ出口の成績（直近2年）
function backtestFor(d, group, cfg) {
  const f = cfg.forward;
  if (group === "entry") {
    const trade = d.contrarian.trades.find((t) => t.strategy === "entry" && t.max_hold === f.entry_max_hold && t.stop === f.entry_stop_pct);
    return { h: d.contrarian.signals.entry?.test.h ?? {}, trade: trade?.test ?? null };
  }
  if (group === "breakout") {
    const v = d.momentum?.variants.find((x) => x.current);
    const trade = v?.trades.find((t) => t.max_hold === f.breakout_max_hold);
    return { h: v?.breakout.test.h ?? {}, trade: trade?.test ?? null };
  }
  return { h: {}, trade: null };
}

function forwardGroupHTML(d, f, cfg, [group, label, mode]) {
  const warn = group === "warn";
  const minSamples = cfg.forward.min_samples;
  const list = f.groups.filter((g) => g.group === group);
  const current = list.find((g) => g.version === f.current[mode]);
  const older = list.filter((g) => g !== current);
  const bt = backtestFor(d, group, cfg);
  const table = (g) => {
    const main = g.h["10"];
    const judge = (main?.n ?? 0) < minSamples
      ? `<div class="alert info">まだ判断できない<small>10営業日後まで分かったシグナルが ${main?.n ?? 0}件です（${minSamples}件以上で判断の目安にします）。今の数字は偶然に大きく左右されます。</small></div>`
      : "";
    const rows = f.horizons
      .map((h) => `<tr><td>${h}営業日後</td>${liveCell(g.h[String(h)], warn)}${warn ? "" : backtestCell(bt.h[String(h)], warn)}${excessCell(g.h[String(h)], warn)}</tr>`)
      .join("");
    const exitRow = warn ? "" : `<tr class="base"><td>出口ルールどおり<br><span class="small muted">${group === "entry" ? `25日線で利確・最大${cfg.forward.entry_max_hold}日` : `${cfg.momentum.exit.stop_loss_pct}%で損切り・50日線割れ・最大${cfg.forward.breakout_max_hold}日`}</span></td>
      ${g.exit ? `<td><b class="num">${pct(g.exit.mean)}</b><br><span class="small muted num">勝率${number(g.exit.win, 0)}%・${count(g.exit.n)}件<br>平均${number(g.exit.days, 0)}日</span></td>` : `<td class="muted small">決済待ち</td>`}
      ${bt.trade ? `<td><span class="num">${pct(bt.trade.mean)}</span><br><span class="small muted num">勝率${number(bt.trade.win, 0)}%<br>${count(bt.trade.n)}回</span></td>` : `<td class="muted">—</td>`}<td></td></tr>`;
    return `${judge}<p class="small muted">シグナル ${count(g.signals)}件（${shortDate(g.first)}〜${shortDate(g.last)}）${g.lost ? `・追跡できなくなった ${g.lost}件を除く` : ""}</p>
      <div class="scroll"><table class="bt"><tr><th></th><th>実運用</th>${warn ? "" : "<th>バックテスト<br><span class='small'>直近2年</span></th>"}<th>指数との差<br><span class="small">実運用</span></th></tr>${rows}${exitRow}</table></div>`;
  };
  let body = current ? table(current) : `<p class="small muted">今の設定になってから、まだこのシグナルは出ていません。</p>`;
  if (warn && current && Object.keys(f.warn_types).length) {
    const typeRows = Object.entries(f.warn_types)
      .map(([key, t]) => `<tr><td>${esc(LABEL[key] ?? key)}</td>${liveCell(t.h10, true)}${backtestCell(d.contrarian.signals[key]?.test.h["10"], true)}</tr>`)
      .join("");
    body += `<h3>警戒サインの種類別（10営業日後・全期間）</h3><div class="scroll"><table class="bt"><tr><th>サイン</th><th>実運用</th><th>バックテスト<br><span class="small">直近2年</span></th></tr>${typeRows}</table></div>`;
  }
  if (older.length) {
    body += `<details><summary class="small">以前の設定でのシグナル（${older.length}）</summary>${older
      .map((g) => `<h3>設定 ${esc(g.version)}（${shortDate(f.versions[g.version]?.first)}〜）</h3>${table(g)}`)
      .join("")}</details>`;
  }
  return `<h3>${esc(label)}</h3>${body}`;
}

function forwardHTML(d, f, cfg) {
  if (!f) {
    return `<section class="card"><h2>実運用での成績（フォワードテスト）</h2>
      <p class="small muted">まだ追跡を始めていません。次の毎日の更新から、その日に出たシグナルを記録していきます。</p></section>`;
  }
  const changedSinceBacktest = JSON.stringify(d.config.entry) !== JSON.stringify(cfg.entry) || JSON.stringify(d.config.buy) !== JSON.stringify(cfg.buy);
  return `<section class="card">
    <h2>実運用での成績（フォワードテスト）</h2>
    <p class="small"><strong>追跡開始 ${f.started.replaceAll("-", "/")}</strong>。毎日の更新で出たシグナルをすべて記録し、その後の値動きを自動で埋めています（${shortDate(f.as_of)} 時点・成績を待っているもの ${count(f.pending)}件）。</p>
    <p class="small muted">数え方はバックテストと同じで、シグナルの翌営業日の始値で買った場合の騰落率です。「指数との差」は、同じ日に${d.market === "us" ? "S&amp;P 500" : "日経平均"}を同じ方法で売買した場合との差。
      しきい値を変えると、変更前のシグナルは「以前の設定」として分けて集計します（今の設定: 逆張り ${esc(f.current.contrarian)}・順張り ${esc(f.current.momentum)}）。手数料・税金は含みません。</p>
    ${changedSinceBacktest ? `<div class="alert info">バックテストは、しきい値を変える前の設定で計算した数字です<small>比べるときは目安にしてください。バックテストを今の設定で計算し直すと、正確に比べられます。</small></div>` : ""}
    ${FORWARD_GROUPS.map((g) => forwardGroupHTML(d, f, cfg, g)).join("")}
    <p class="small muted">結果は目安です。投資助言ではありません。過去の成績は将来を保証しません。</p>
  </section>`;
}

// ------------------------------------------------------------ 画面

// forward = 実運用での成績（なければ null）、cfg = 今のしきい値（市場のデータに入っているもの）
export function renderBacktest(app, d, forward = null, cfg = null) {
  current = d;
  currentForward = forward;
  currentCfg = cfg;
  const p = d.period;
  app.innerHTML = `
    <a class="btn back" href="#${d.market}">← 一覧へ戻る</a>
    <section class="card">
      <h2>検証結果（バックテスト）</h2>
      <p class="small">${p.start.slice(0, 7)} 〜 ${p.end.slice(0, 7)} の約${d.config.backtest.years}年分の日足で、各サインが出たあとの値動きを集計しました（${shortDate(d.as_of)} 時点）。</p>
      <div class="alert warn">結果は実際より良く出ています<small>今の構成銘柄だけで検証しているため、過去に指数から外れた銘柄や上場廃止の銘柄が含まれません。手数料・税金・売買時の価格のずれも含みません。過去の成績は将来を保証しません。</small></div>
      <p class="small muted">「古い期間」でしきい値を選び、「直近2年」で通用するかを確かめる、という見方をします。両方で基準を上回っていれば、偶然ではない可能性が高まります。
        ただし、相場全体が急落した日には多くの銘柄で同時にサインが出るため、回数ほどには独立した例は多くありません。</p>
    </section>
    ${cfg?.forward ? forwardHTML(d, forward, cfg) : ""}
    ${contrarianHTML(d)}${rciHTML(d)}${momentumHTML(d)}`;
}

export function initBacktest(app) {
  app.addEventListener("change", (event) => {
    const key = event.target.dataset.bt;
    if (!key || key === "query" || !current) return;
    ui[key] = event.target.value;
    const y = window.scrollY;
    renderBacktest(app, current, currentForward, currentCfg);
    window.scrollTo(0, y);
  });
  app.addEventListener("input", (event) => {
    if (event.target.dataset.bt !== "query" || !current) return;
    ui.query = event.target.value;
    const box = document.createElement("div");
    box.innerHTML = rciHTML(current);
    document.getElementById("bt-rci").innerHTML = box.querySelector("#bt-rci").innerHTML;
  });
}

// 「成績」の画面。決済済みの取引から、勝率・期待値・R倍数・ルール違反・指数との比較を表示する。
import { esc, number, pct, jpy, signedJpy, signClass, shortDate, todayISO } from "./format.js";
import { reasonLabel } from "./exits.js";
import { VIOLATIONS, tradeOf, summarize, groupStats, kindOf, vsIndex, ytdVsIndex } from "./stats.js";
import { DISCLAIMER } from "./sizer.js";

const r = (value) => (value == null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}${number(Math.abs(value), 2)}R`);
const fewBadge = `<span class="badge warn">件数が少なく参考値</span>`;

function overallHTML(s, minSamples) {
  const row = (label, value, note = "") => `<tr><td>${label}${note ? `<br><span class="small muted">${note}</span>` : ""}</td><td class="num">${value}</td></tr>`;
  return `<section class="card">
    <h2>成績のまとめ（全期間・${s.n}件）</h2>
    ${s.few ? `<div class="alert info">件数が少なく参考値です<small>${minSamples}件未満のうちは、偶然の影響が大きく、実力とは言えません。</small></div>` : ""}
    <table class="kv">
      ${row("勝率", s.win == null ? "—" : number(s.win, 1) + "%", "損益ゼロは勝ちにも負けにも数えません")}
      ${row("平均利益", `<span class="up">${s.avgWin == null ? "—" : signedJpy(s.avgWin)}</span>`)}
      ${row("平均損失", `<span class="down">${s.avgLoss == null ? "—" : signedJpy(s.avgLoss)}</span>`)}
      ${row("損益比", s.payoff == null ? "—" : number(s.payoff, 2), "平均利益 ÷ 平均損失")}
      ${row("期待値（1回あたりの平均損益）", `<strong class="${signClass(s.expect)}">${signedJpy(s.expect)}</strong>`)}
      ${row("期待値（R倍数）", r(s.avgR), s.rN < s.n ? `損切り価格のある ${s.rN}件で計算` : "損切り幅を1Rとした平均")}
      ${row("最大連敗", `${s.streak}回`)}
      ${row("平均保有日数", s.days == null ? "—" : number(s.days, 1) + "日", "カレンダーの日数")}
      ${row("損益の合計", `<span class="${signClass(s.totalJpy)}">${signedJpy(s.totalJpy)}</span>`)}
    </table>
    ${s.unconverted ? `<p class="small muted">為替レートがないため、米国株 ${s.unconverted}件を金額の集計から外しています。</p>` : ""}
    <p class="small muted">金額は円換算（米国株は現在の為替レート）で、入力した手数料を差し引いています。税金は含みません。</p>
  </section>`;
}

function cutTable(title, rows, labelOf, note = "") {
  if (!rows.length) return "";
  const body = rows
    .map(({ key, stats: s }) => `<tr>
      <td>${esc(labelOf(key))}${s.few ? `<br>${fewBadge}` : ""}</td>
      <td class="num">${s.n}件<br><span class="small muted">勝率 ${s.win == null ? "—" : number(s.win, 0) + "%"}</span></td>
      <td class="num"><b class="${signClass(s.expect)}">${signedJpy(s.expect)}</b><br><span class="small muted">損益比 ${s.payoff == null ? "—" : number(s.payoff, 2)}</span></td>
      <td class="num">${r(s.avgR)}<br><span class="small muted">${s.streak}連敗・${s.days == null ? "—" : number(s.days, 0)}日</span></td>
    </tr>`)
    .join("");
  return `${title ? `<h3>${title}</h3>` : ""}${note}<div class="scroll"><table class="bt">
    <tr><th>切り口</th><th>件数<br>勝率</th><th>期待値<br>損益比</th><th>平均R<br>最大連敗・保有</th></tr>${body}</table></div>`;
}

function indexHTML(closed, indexes, usdjpy) {
  const year = todayISO().slice(0, 4);
  const y = ytdVsIndex(closed, year, indexes, usdjpy);
  let verdict = `<div class="alert info">${year}年に決済した取引がまだありません。</div>`;
  if (y.count) {
    verdict = y.beat
      ? `<div class="alert entry">指数に勝っています<small>${year}年の累計で、指数を ${jpy(Math.abs(y.diff))} 上回っています。</small></div>`
      : `<div class="alert warn">指数に負けています<small>${year}年の累計で、指数を ${jpy(Math.abs(y.diff))} 下回っています。指数を買っておいたほうが良かった、ということです。</small></div>`;
  } else if (y.missing) {
    verdict = `<div class="alert info">比べられる取引がありません（指数のデータは直近2年分です）。</div>`;
  }
  const rows = [...closed]
    .sort((a, b) => (a.sell.date < b.sell.date ? 1 : -1))
    .map((p) => {
      const v = vsIndex(p, indexes[p.market]);
      const cur = (x) => (p.market === "us" ? `${x < 0 ? "−" : x > 0 ? "+" : ""}$${number(Math.abs(x), 2)}` : signedJpy(x));
      if (!v) return `<tr><td>${esc(p.name)}<br><span class="small muted">${shortDate(p.buyDate)}→${shortDate(p.sell.date)}</span></td><td colspan="2" class="muted small">比べられません</td></tr>`;
      return `<tr><td>${esc(p.name)}<br><span class="small muted">${shortDate(p.buyDate)}→${shortDate(p.sell.date)}</span></td>
        <td class="num ${signClass(v.actual)}">${cur(v.actual)}</td>
        <td class="num ${signClass(v.index)}">${cur(v.index)}<br><span class="small muted">${pct(v.indexRet)}</span></td></tr>`;
    })
    .join("");
  return `<section class="card">
    <h2>指数との比較</h2>
    <p class="small muted">同じ日に同じ金額で指数（日本株は日経平均、米国株は S&amp;P 500）を買い、同じ日に売った場合と比べます。</p>
    ${verdict}
    <table class="kv">
      <tr><td>${year}年の実際の損益（累計）</td><td class="num ${signClass(y.actual)}"><strong>${signedJpy(y.actual)}</strong></td></tr>
      <tr><td>同じ売買を指数でした場合</td><td class="num ${signClass(y.index)}">${signedJpy(y.index)}</td></tr>
      <tr><td>差</td><td class="num ${signClass(y.diff)}">${signedJpy(y.diff)}</td></tr>
    </table>
    <p class="small muted">${y.count}件で比較${y.missing ? `（${y.missing}件は指数のデータがなく比べられません）` : ""}。<strong>手数料と税金は、実際の損益・指数のどちらにも含みません。</strong>米国株は現在の為替レートで円に換算しています。</p>
    <details><summary class="small">取引ごとに見る</summary>
      <div class="scroll"><table class="bt"><tr><th>銘柄</th><th>実際</th><th>指数なら</th></tr>${rows}</table></div>
    </details>
  </section>`;
}

// ctx = { markets, fx }, indexes = { jp, us }（指数の日足）
export function statsHTML(positions, ctx, indexes) {
  const cfg = ctx.markets.jp.config;
  const minSamples = cfg.stats?.min_samples ?? 10;
  const usdjpy = ctx.fx?.usdjpy ?? null;
  const closed = positions.filter((p) => p.sell);
  if (!closed.length) {
    return `<section class="card"><h2>成績</h2><p class="small muted">決済済みの取引がまだありません。決済を記録すると、ここに勝率や期待値が表示されます。</p>${DISCLAIMER}</section>`;
  }
  const trades = closed.map((p) => tradeOf(p, usdjpy));
  const overall = summarize(trades, minSamples);
  // 表の幅に収まるよう、買った理由は短い名前で出す
  const SHORT_REASON = { c1: "条件1（急落）", c2: `条件2（${cfg.ma.mid}日線）`, c3: "条件3（バンド）", theme: "テーマ・業績", mo: "順張り" };
  const reasonText = (key) => SHORT_REASON[key] ?? reasonLabel(key, cfg);
  const violated = trades.filter((t) => t.violated);
  const counts = Object.entries(VIOLATIONS)
    .map(([key, label]) => [label, closed.filter((p) => p.sell.violations?.[key]).length])
    .filter(([, n]) => n > 0)
    .map(([label, n]) => `<li>${esc(label)}：${n}件</li>`)
    .join("");
  return `
    ${overallHTML(overall, minSamples)}
    ${indexHTML(closed, indexes, usdjpy)}
    <section class="card">
      <h2>切り口別の成績</h2>
      <p class="small muted">期待値は1回あたりの平均損益（円換算）。R倍数は「損切り幅（買値 − 登録時の損切り価格）」を1Rとして、何R勝った／負けたか。${minSamples}件未満の切り口は参考値です。</p>
      ${cutTable("買った理由別", groupStats(trades, (t) => t.pos.reason, minSamples), reasonText)}
      ${cutTable("市場別", groupStats(trades, (t) => t.pos.market, minSamples, ["jp", "us"]), (k) => (k === "us" ? "米国株" : "日本株"))}
      ${cutTable("逆張り／順張り別", groupStats(trades, (t) => kindOf(t.pos), minSamples, ["contrarian", "momentum"]), (k) => (k === "momentum" ? "順張り" : "逆張り"))}
      ${cutTable("月別（決済した月）", groupStats(trades, (t) => t.pos.sell.date.slice(0, 7), minSamples).sort((a, b) => (a.key < b.key ? 1 : -1)), (k) => `${k.slice(0, 4)}年${Number(k.slice(5))}月`)}
    </section>
    <section class="card">
      <h2>ルール違反あり／なし</h2>
      <p class="small muted">決済のときのチェックで分けています。違反ありの成績が悪ければ、ルールを守る意味が数字で分かります。</p>
      ${cutTable("", groupStats(trades, (t) => (t.violated ? "yes" : "no"), minSamples, ["no", "yes"]), (k) => (k === "yes" ? "違反あり" : "違反なし"))}
      ${violated.length ? `<h3>違反の内訳</h3><ul class="plain small">${counts}</ul>` : `<p class="small">ルール違反の記録はありません。</p>`}
      <p class="small muted">チェックは「保有・記録」の決済済みの記録から直せます。</p>
    </section>
    <section class="card">${DISCLAIMER}</section>`;
}

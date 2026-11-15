// セクター・テーマの強弱ランキングの画面と、一覧の絞り込み・「見るだけ」ラベルとの連動。
import { esc, pct, shortDate } from "./format.js";

const cache = {}; // { jp: データ, us: データ }
export const setSectors = (market, data) => (cache[market] = data);
export const getSectors = (market) => cache[market] ?? null;

const find = (list, name) => list?.find((g) => g.name === name);

// 「見るだけ」: セクター強弱の集計（約500銘柄）で下落トレンドなら true。集計がなければ従来の判定
export function watchOnly(market, stock) {
  const g = find(getSectors(market)?.sectors, stock.sector);
  return g ? g.downtrend : Boolean(stock.watch_only);
}

export function sectorDowntrend(market, name, fallback = false) {
  const g = find(getSectors(market)?.sectors, name);
  return g ? g.downtrend : fallback;
}

// 強いセクター・テーマに入っている銘柄か
export function inStrong(market, stock) {
  const d = getSectors(market);
  if (!d) return false;
  if (find(d.sectors, stock.sector)?.strong) return true;
  return (stock.themes ?? []).some((t) => find(d.themes, t)?.strong);
}

const TREND = { up: `<span class="up">↑ 上昇中</span>`, down: `<span class="down">↓ 下降中</span>`, flat: `<span class="muted">→</span>` };

function rowHTML(g, periods, showRef) {
  const badges = [
    g.strong ? `<span class="badge good">強い</span>` : "",
    g.few ? `<span class="badge warn" title="銘柄が少なく参考値">少数・参考値</span>` : "",
    g.downtrend ? `<span class="badge">下落トレンド</span>` : "",
  ].join(" ");
  const cells = periods.map((p) => {
    const x = g.x[String(p)];
    return `<td class="num"><b class="${x > 0 ? "up" : x < 0 ? "down" : ""}">${pct(x, 1)}</b><br><span class="small muted">${pct(g.r[String(p)], 1)}</span></td>`;
  }).join("");
  const ref = showRef && g.ref
    ? `<br><span class="small muted">${esc(g.ref.ticker)} ${pct(g.ref.x["21"], 1)}</span>` : "";
  const move = g.trend ? `${TREND[g.trend]}${g.rank_prev ? `<br><span class="small muted">前 ${g.rank_prev}位</span>` : ""}` : "";
  return `<tr class="${g.strong ? "strong-row" : ""}">
    <td class="num"><b>${g.rank ?? "—"}</b><br><span class="small">${move}</span></td>
    <td>${esc(g.name)} <span class="small muted">${g.count}銘柄</span><br>${badges}${ref}</td>
    ${cells}
    <td class="num">${g.p_above == null ? "—" : Math.round(g.p_above) + "%"}</td></tr>`;
}

function tableHTML(list, d, showRef) {
  if (!list.length) return `<p class="small muted">データがありません。</p>`;
  const periods = d.config.periods;
  const name = { 5: "1週間", 21: "1か月", 63: "3か月" };
  return `<div class="scroll"><table class="bt sector-table">
    <tr><th>順位</th><th>名前</th>${periods.map((p) => `<th>${name[p] ?? p + "日"}</th>`).join("")}<th>25日<br>線上</th></tr>
    ${list.map((g) => rowHTML(g, periods, showRef)).join("")}</table></div>`;
}

export function renderSectors(app, d) {
  if (!d) {
    app.innerHTML = `<p class="pad">セクター強弱のデータがまだありません。次のデータ更新のあとに表示されます。</p>`;
    return;
  }
  const c = d.config, ix = d.index;
  const hasRef = d.sectors.some((g) => g.ref);
  app.innerHTML = `
    <section class="card">
      <h2>セクター・テーマの強弱</h2>
      <p class="small">${esc(d.universe)} の銘柄を、セクター・テーマごとに等金額で平均した値動きを、${esc(d.index_name)}と比べています（${shortDate(d.as_of)} 時点）。</p>
      <p class="small muted">太字は${esc(d.index_name)}との差、その下の小さい数字は騰落率そのもの。順位は1週間・1か月・3か月の「指数との差」の平均で決め、${c.rank_change_days}営業日前の順位から${c.rank_change_min}つ以上動いたら上昇中／下降中とします。
        上位${c.strong_top_pct}%が「強い」。${c.min_stocks}銘柄未満のグループは「少数・参考値」（銘柄が少なく参考値）として、「強い」から除きます。基準は仮置きです。</p>
      <p class="small">${esc(d.index_name)}: 1週間 ${pct(ix["5"], 1)}・1か月 ${pct(ix["21"], 1)}・3か月 ${pct(ix["63"], 1)}</p>
      ${d.market === "jp" ? `<div class="alert info">日経平均は値がさ株の影響が大きいため、等金額で平均したセクターとの差は大きく出やすくなります<small>順位（どのセクターが相対的に強いか）は、比べる指数を変えても変わりません。</small></div>` : ""}
    </section>
    <section class="card"><h2>セクター</h2>${tableHTML(d.sectors, d, hasRef)}
      ${hasRef ? `<p class="small muted">名前の下の XLV などは、公式のセクターETF（Select Sector SPDR、時価総額加重）の1か月の指数との差。等金額平均と大きく違うときは、大型株だけが強い（弱い）状態です。</p>` : ""}
      <p class="small muted">「下落トレンド」のセクターの銘柄は、逆張りの一覧で「見るだけ」になります。</p></section>
    <section class="card"><h2>テーマ</h2>${tableHTML(d.themes, d, false)}
      <p class="small muted">テーマは銘柄リストの themes 列で付けたものです。テーマが付いている銘柄が少ないため、多くは参考値です。</p></section>
    <section class="card"><p class="small muted">集計は目安です。投資助言ではありません。過去の値動きは将来を保証しません。</p></section>`;
  window.scrollTo(0, 0);
}

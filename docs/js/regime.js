// 相場環境（逆張り向き／順張り向き／様子見）の表示。判定はデータ更新のときに済ませてあり、ここでは表示するだけ。
import { esc, number, shortDate } from "./format.js";

export const REGIME_LABEL = { contrarian: "逆張り向き", momentum: "順張り向き", wait: "様子見" };
const cache = {}; // { jp: データ, us: データ }

export const setRegime = (market, data) => (cache[market] = data);
export const getRegime = (market) => cache[market] ?? null;

// そのモードの候補が、今の環境と合っているか。合っていなければ注意の文言を返す
export function mismatch(market, mode) {
  const r = getRegime(market)?.latest;
  if (!r) return null;
  if (r.regime === "wait") return { level: "info", short: "様子見の環境", text: "今は「様子見」の環境です。候補が出ても、慎重に判断してください。" };
  if (mode === "contrarian" && r.regime === "momentum")
    return { level: "warn", short: "今の環境とは逆", text: "今は「順張り向き」の環境です。逆張りの候補は、今の環境とは逆です。" };
  if (mode === "momentum" && r.regime === "contrarian")
    return { level: "warn", short: "今の環境とは逆", text: "今は「逆張り向き」（売られすぎ）の環境です。順張りの候補は、今の環境とは逆です。" };
  return null;
}

function reasonText(r, c) {
  switch (r.reason) {
    case "oversold":
      return r.p_short <= c.oversold_pct
        ? `売られすぎ：25日線より上の銘柄が ${number(r.p_short, 1)}%（${c.oversold_pct}%以下）`
        : `売られすぎ：VIX が ${number(r.vix, 1)}（${c.vix_high}超）`;
    case "uptrend":
      return `上昇トレンド：指数が上向きの200日線より上にあり、200日線より上の銘柄が ${number(r.p_long, 1)}%（${c.uptrend_pct}%以上）`;
    case "downtrend":
      return "下降トレンド：指数が下向きの200日線より下にあり、反転の兆し（指数の25日線回復・52週安値の更新数の減少）がありません";
    default:
      return "方向感なし：売られすぎでも、はっきりした上昇トレンドでもありません";
  }
}

// ------------------------------------------------------------ 推移グラフ（SVG）

const W = 340, H = 110, PAD = 4;

function lineChart(title, t, series, { min = null, max = null, lines = [], regime = null } = {}) {
  const all = series.flatMap((s) => s.values).filter((v) => v != null);
  if (!all.length) return "";
  const lo = min ?? Math.min(...all), hi = max ?? Math.max(...all);
  const x = (i) => PAD + (i / Math.max(1, t.length - 1)) * (W - PAD * 2);
  const y = (v) => H - 14 - ((v - lo) / (hi - lo || 1)) * (H - 24);
  const path = (values) => {
    let d = "", pen = false;
    values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  // 下の帯: その日の判定（色）
  const strip = regime
    ? regime.map((g, i) => (g ? `<rect x="${x(i).toFixed(1)}" y="${H - 8}" width="${(W / t.length + 0.6).toFixed(2)}" height="6" class="rg-${g}"/>` : "")).join("")
    : "";
  const guides = lines
    .map((l) => `<line x1="${PAD}" x2="${W - PAD}" y1="${y(l.value).toFixed(1)}" y2="${y(l.value).toFixed(1)}" class="guide"/><text x="${W - PAD}" y="${(y(l.value) - 2).toFixed(1)}" text-anchor="end" class="guide-text">${esc(l.label)}</text>`)
    .join("");
  const paths = series.map((s) => `<path d="${path(s.values)}" class="line ${s.cls}"/>`).join("");
  const legend = series.map((s) => `<span><i class="${s.cls}"></i>${esc(s.label)}</span>`).join("");
  return `<div class="mini-chart"><div class="small">${esc(title)}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">${guides}${paths}${strip}</svg>
    <div class="mini-legend">${legend}<span class="muted">${shortDate(t[0])}〜${shortDate(t[t.length - 1])}</span></div></div>`;
}

function chartsHTML(d) {
  const h = d.history, c = d.config;
  const vix = h.vix.some((v) => v != null);
  return `
    ${lineChart("25日線・200日線より上にある銘柄の割合（%）", h.t, [
      { values: h.p_short, cls: "s1", label: "25日線より上" },
      { values: h.p_long, cls: "s2", label: "200日線より上" },
    ], { min: 0, max: 100, lines: [{ value: c.oversold_pct, label: `${c.oversold_pct}%` }, { value: c.uptrend_pct, label: `${c.uptrend_pct}%` }], regime: h.regime })}
    ${lineChart("52週高値・安値を更新した銘柄数", h.t, [
      { values: h.highs, cls: "s1", label: "高値更新" },
      { values: h.lows, cls: "s3", label: "安値更新" },
    ], { min: 0, regime: h.regime })}
    ${lineChart("指数と200日線", h.t, [
      { values: h.close, cls: "s1", label: "指数" },
      { values: h.ma_long, cls: "s2", label: "200日線" },
    ], { regime: h.regime })}
    ${vix ? lineChart("VIX", h.t, [{ values: h.vix, cls: "s3", label: "VIX" }], { min: 0, lines: [{ value: c.vix_high, label: String(c.vix_high) }], regime: h.regime }) : ""}
    <p class="small muted">グラフの下の帯は、その日の判定です（<span class="rg-key rg-contrarian"></span>逆張り向き　<span class="rg-key rg-momentum"></span>順張り向き　<span class="rg-key rg-wait"></span>様子見）。</p>`;
}

// ------------------------------------------------------------ カード

// d = 相場環境のデータ（指数の名前と対象銘柄の呼び名も入っている）
export function regimeHTML(d) {
  if (!d?.latest) return "";
  const indexName = d.index_name ?? "指数", universe = d.universe ?? "対象銘柄";
  const r = d.latest, c = d.config;
  const dir = (key, days) => {
    const above = r.close > r[`ma_${key}`];
    return `<tr><td>${days}日線 <span class="small muted">${r[`rising_${key}`] ? "↗ 上向き" : "↘ 下向き"}</span></td>
      <td class="num">${number(r[`ma_${key}`], 0)}<br><span class="small ${above ? "up" : "down"}">指数は${above ? "上" : "下"}</span></td></tr>`;
  };
  const pending = r.raw && r.raw !== r.regime
    ? `<p class="small muted">今日の判定は「${REGIME_LABEL[r.raw]}」でした。${c.confirm_days}日続いたら切り替えます。</p>` : "";
  return `<section class="card">
    <div class="regime-head">
      <span class="regime-badge rg-${r.regime}">${REGIME_LABEL[r.regime]}</span>
      <span class="small muted">相場環境　${shortDate(r.since)}から（${shortDate(r.date)} 時点）</span>
    </div>
    <p class="small">${esc(reasonText(r, c))}</p>
    ${pending}
    <table class="kv">
      <tr><td>25日線より上にある銘柄<br><span class="small muted">${c.oversold_pct}%以下で「売られすぎ」</span></td><td class="num"><strong>${number(r.p_short, 1)}%</strong></td></tr>
      <tr><td>200日線より上にある銘柄<br><span class="small muted">${c.uptrend_pct}%以上が順張り向きの条件</span></td><td class="num"><strong>${number(r.p_long, 1)}%</strong></td></tr>
      <tr><td>52週高値／安値を更新した銘柄</td><td class="num"><span class="up">${r.highs ?? "—"}</span> ／ <span class="down">${r.lows ?? "—"}</span></td></tr>
      <tr><td>${esc(indexName)}</td><td class="num">${number(r.close, 0)}</td></tr>
      ${dir("short", c.ma.short)}${dir("mid", c.ma.mid)}${dir("long", c.ma.long)}
      ${r.vix != null ? `<tr><td>VIX<br><span class="small muted">${c.vix_high}超で「売られすぎ」</span></td><td class="num">${number(r.vix, 2)}</td></tr>` : ""}
    </table>
    <details><summary class="small">指標の推移を見る</summary>${chartsHTML(d)}</details>
    <p class="small muted">${esc(universe)} の ${r.n} 銘柄で計算。判定の基準は仮置きで、目安です。投資助言ではありません。
      ${d.market === "jp" ? "Fear &amp; Greed と日経VI（どちらも手入力）" : "Fear &amp; Greed（手入力）"}は判定に使っていません（温度計で確認できます）。</p>
  </section>`;
}

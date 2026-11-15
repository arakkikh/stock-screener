// 「資金設定」の画面と、保有全体のリスクの表示。
// 資金額はこの端末のブラウザ（localStorage）にだけ保存し、どこにも送らない。
import { store } from "./store.js";
import { esc, number, jpy, usd, shortDate } from "./format.js";
import { SETTINGS_KEY, capitalJpy, riskPctOf, portfolioRisk } from "./sizing.js";
import { DISCLAIMER } from "./sizer.js";

export const loadSettings = () => store.get(SETTINGS_KEY, {});

// ------------------------------------------------------------ 資金設定

export function settingsHTML(cfg, fx) {
  const s = loadSettings();
  const capital = capitalJpy(s, fx?.usdjpy);
  return `<section class="card">
    <h2>資金設定</h2>
    <p class="small muted">ここに入れた金額は、この端末のこのブラウザの中にだけ保存されます。インターネット上には送られません。エクスポートしたファイルには含まれます。</p>
    <form class="form" id="money-form" novalidate>
      <div class="grid2">
        <div><label for="money-jpy">運用資金（円）</label><input type="number" id="money-jpy" min="0" step="1" inputmode="numeric" value="${s.jpy ?? ""}" placeholder="例: 3000000"></div>
        <div><label for="money-usd">運用資金（ドル）</label><input type="number" id="money-usd" min="0" step="0.01" inputmode="decimal" value="${s.usd ?? ""}" placeholder="例: 10000"></div>
        <div><label for="money-risk">1回の取引で許容する損失（資金の%）</label>
          <input type="number" id="money-risk" min="0" max="100" step="0.1" inputmode="decimal" value="${s.riskPct ?? ""}" placeholder="${cfg.sizing.risk_pct}"></div>
      </div>
      <p class="small muted">許容損失を空にすると、初期値の${cfg.sizing.risk_pct}%を使います（初期値は仮置きです）。円とドルの資金は円に換算して合計し、その合計に対する割合で計算します。</p>
      <div id="money-errors"></div>
      <div class="actions"><button type="submit" class="primary">保存する</button></div>
    </form>
    <table class="kv">
      <tr><td>運用資金の合計（円換算）<br><span class="small muted">${fx ? `1ドル = ${number(fx.usdjpy, 2)}円（${shortDate(fx.date)}）` : "為替レートなし"}</span></td>
        <td class="num"><strong>${capital == null ? "換算できません" : jpy(capital)}</strong></td></tr>
      <tr><td>1回の取引で許容する損失</td><td class="num">${capital > 0 ? jpy((capital * riskPctOf(s, cfg)) / 100) : "—"}<br><span class="small muted">${number(riskPctOf(s, cfg), 1)}%</span></td></tr>
    </table>
    ${DISCLAIMER}
  </section>`;
}

// 入力チェックして保存する。問題があれば、その説明の一覧を返す
export function saveSettingsFromForm() {
  const read = (id) => {
    const raw = document.getElementById(id).value.trim();
    return raw === "" ? null : Number(raw);
  };
  const next = { jpy: read("money-jpy"), usd: read("money-usd"), riskPct: read("money-risk") };
  const errors = [];
  if (next.jpy != null && !(next.jpy >= 0)) errors.push("運用資金（円）は0以上の数で入力してください。");
  if (next.usd != null && !(next.usd >= 0)) errors.push("運用資金（ドル）は0以上の数で入力してください。");
  if (next.riskPct != null && !(next.riskPct > 0 && next.riskPct <= 100)) errors.push("許容損失は0より大きく100以下の%で入力してください。");
  if (!errors.length) {
    const clean = Object.fromEntries(Object.entries(next).filter(([, v]) => v != null));
    store.set(SETTINGS_KEY, { ...clean, updatedAt: new Date().toISOString() });
  }
  return errors;
}

// ------------------------------------------------------------ 全体リスク

function barsHTML(groups, title, note = "") {
  if (!groups.length) return "";
  const max = Math.max(...groups.map((g) => g.pct), 1);
  const rows = groups
    .map((g) => `<div class="bar-row"><div class="bar-label"><span>${esc(g.name)}</span><span class="num">${number(g.pct, 1)}%</span></div>
      <div class="bar"><i style="width:${Math.min(100, (g.pct / max) * 100)}%"></i></div></div>`)
    .join("");
  return `<h3>${title}</h3>${note}<div class="bars">${rows}</div>`;
}

// positions … 保有中のポジション、info(pos) … { price, sector, themes }
export function riskHTML(open, cfg, fx, info) {
  if (!open.length) return "";
  const settings = loadSettings();
  const capital = capitalJpy(settings, fx?.usdjpy);
  const r = portfolioRisk(open, { capitalJpy: capital, usdjpy: fx?.usdjpy, cfg, info });
  const alerts = [];
  if (!(capital > 0)) alerts.push(`<div class="alert info">「<a href="#portfolio/settings">資金設定</a>」で運用資金を入れると、資金に対する割合で表示します。今は保有額の合計に対する割合です。</div>`);
  for (const w of r.warnings) {
    const what = w.type === "stock" ? "1銘柄" : "1セクター";
    alerts.push(`<div class="alert warn">${what}への集中：${esc(w.name)}<small>${r.base === "capital" ? "資金" : "保有額の合計"}の${number(w.pct, 1)}%（基準 ${w.limit}%）を占めています。</small></div>`);
  }
  if (r.margin.over)
    alerts.push(`<div class="alert danger">信用建玉が現金を超えています<small>信用で建てた額 ${jpy(r.margin.marginJpy)} が、現金（運用資金 − 現物で買った額）${jpy(r.margin.cashJpy)} を上回っています。</small></div>`);
  if (r.noStop.length)
    alerts.push(`<div class="alert info">損切り価格が未設定のポジションが ${r.noStop.length} 件あります。各ポジションの欄で入力すると、下の合計に含まれます。</div>`);
  if (r.noFx.length) alerts.push(`<div class="alert info">為替レートがないため、米国株 ${r.noFx.length} 件を集計から外しています。</div>`);
  const lossPct = r.lossPct == null ? "" : `<br><span class="small">資金の ${number(r.lossPct, 2)}%</span>`;
  return `<section class="card">
    <h2>保有全体のリスク</h2>
    ${alerts.join("")}
    <table class="kv">
      <tr><td>全部が損切りになった場合の合計損失<br><span class="small muted">買値から損切り価格まで下げた場合</span></td><td class="num"><strong>${jpy(r.totalLossJpy)}</strong>${lossPct}</td></tr>
      <tr><td>保有額の合計（現在値）</td><td class="num">${jpy(r.totalValueJpy)}</td></tr>
      ${r.margin.count ? `<tr><td>信用建玉の合計（${r.margin.count}件）</td><td class="num">${jpy(r.margin.marginJpy)}</td></tr>` : ""}
    </table>
    <p class="small muted">割合は${r.base === "capital" ? "運用資金" : "保有額の合計"}に対するものです。米国株は現在の為替レートで円に換算しています。</p>
    ${barsHTML(r.byMarket, "市場別（円／ドル）")}
    ${barsHTML(r.bySector, "セクター別")}
    ${barsHTML(r.byTheme, "テーマ別", `<p class="small muted">1銘柄が複数のテーマに入ることがあるので、合計は100%を超えることがあります。</p>`)}
    ${barsHTML(r.byStock, "銘柄別")}
    <p class="small muted">集中の警告の基準: 1銘柄 ${cfg.sizing.max_stock_pct}%、1セクター ${cfg.sizing.max_sector_pct}%（仮置き）</p>
    ${DISCLAIMER}
  </section>`;
}

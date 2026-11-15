// 株数の計算機（画面部品）。銘柄の詳細画面と、ポジションの登録画面に置く。
// 資金額は localStorage から読むだけで、どこにも送らない。
import { store } from "./store.js";
import { esc, price, number, jpy, usd } from "./format.js";
import { SETTINGS_KEY, capitalJpy, riskPctOf, stopCandidates, positionSize } from "./sizing.js";

export const DISCLAIMER = `<p class="small muted">計算結果は目安です。投資助言ではありません。最終判断はご自身で行ってください。</p>`;

// el に計算機を描く。
//   opts.market / cfg / digits / fx（1ドルの円。なければ null）
//   opts.kind      … "contrarian" / "momentum"
//   opts.levels    … 損切り候補に使う水準 { bb_l3, ma_fast }
//   opts.buyPrice  … 買値の初期値（計算機の中に買値の入力欄を置く場合）
//   opts.form      … 登録フォームの中に置くとき { getBuy(), getReason(), onUse(qty) }
//                    このときは買値をフォームから読み、損切り価格の入力欄に id="pf-stop" を付ける
// 戻り値の refresh() を呼ぶと、買値や買った理由の変更を反映する
export function mountSizer(el, opts) {
  const { market, cfg, digits, fx, kind, levels = {}, form } = opts;
  if (!cfg?.sizing) {
    el.innerHTML = `<h2>株数の計算</h2><p class="small muted">設定を読み込めませんでした。次のデータ更新のあとに表示されます。</p>`;
    return { refresh() {} };
  }
  const settings = store.get(SETTINGS_KEY, {});
  const usdjpy = fx?.usdjpy ?? null;
  const capital = capitalJpy(settings, usdjpy);
  const riskPct = riskPctOf(settings, cfg);
  const rate = market === "us" ? usdjpy : 1;
  const lot = cfg.sizing.lot;
  const step = digits >= 2 ? "0.01" : "0.1";

  const capitalLine = capital > 0
    ? `運用資金 ${jpy(capital)}${settings.usd > 0 ? "（円換算）" : ""} × 許容損失 ${number(riskPct, 1)}% ＝ <strong>1回 ${jpy((capital * riskPct) / 100)} まで</strong>`
    : capital === null
      ? "為替レートを取得できないため、ドルの資金を円に換算できません。"
      : "運用資金がまだ入力されていません。";
  el.innerHTML = `
    <h2>株数の計算</h2>
    <p class="small">${capitalLine}　<a href="#portfolio/settings">資金設定</a></p>
    <div class="grid2">
      ${form ? "" : `<div><label class="small muted" for="sz-buy">買値</label><input type="number" id="sz-buy" step="${step}" inputmode="decimal" value="${opts.buyPrice ?? ""}"></div>`}
      <div><label class="small muted" for="${form ? "pf-stop" : "sz-stop"}">損切り価格</label>
        <input type="number" id="${form ? "pf-stop" : "sz-stop"}" class="sz-stop" step="${step}" inputmode="decimal" data-auto="1"></div>
    </div>
    <div class="sz-cands chips" aria-label="損切り価格の候補"></div>
    <div class="sz-out"></div>
    <p class="small muted">${market === "jp" ? `日本株は${lot}株単位で切り捨てます。` : "米国株は1株単位です。"}損切り時の損失は「(買値 − 損切り価格) × 株数」で、手数料と税金は含みません。</p>
    ${DISCLAIMER}`;

  const stopInput = el.querySelector(".sz-stop");
  const buyOf = () => (form ? form.getBuy() : Number(el.querySelector("#sz-buy").value || NaN));
  const money = (localValue, yenValue) => (market === "us" ? `${usd(localValue)}<br><span class="small muted">約 ${jpy(yenValue)}</span>` : jpy(yenValue));

  function renderResult() {
    const out = el.querySelector(".sz-out");
    const stopValue = stopInput.value === "" ? NaN : Number(stopInput.value);
    const r = positionSize({ buyPrice: buyOf(), stopPrice: stopValue, capitalJpy: capital, riskPct, fx: rate, lot });
    if (r.error) {
      out.innerHTML = `<p class="small muted">${esc(r.error)}</p>`;
      return;
    }
    const unit = `${number(lot, 0)}株`;
    if (r.tooLarge) {
      out.innerHTML = `<div class="alert danger">この銘柄は資金に対して大きすぎる<small>${unit}だけでも、損切りになると ${jpy(r.lossJpy)}（資金の${number(r.lossPct, 2)}%）の損失で、許容の ${jpy(r.budgetJpy)}（${number(riskPct, 1)}%）を超えます。</small></div>`;
      return;
    }
    if (r.unaffordable) {
      out.innerHTML = `<div class="alert warn">運用資金では${unit}も買えません<small>${unit}の必要資金は ${market === "us" ? usd(r.cost) + "（約 " + jpy(r.costJpy) + "）" : jpy(r.costJpy)} です。</small></div>`;
      return;
    }
    out.innerHTML = `
      <table class="kv">
        <tr><td>買ってよい株数</td><td class="num"><strong>${number(r.qty, 0)}株</strong></td></tr>
        <tr><td>必要資金</td><td class="num">${money(r.cost, r.costJpy)}</td></tr>
        <tr><td>損切りになったときの損失</td><td class="num">${money(r.loss, r.lossJpy)}<br><span class="small">資金の ${number(r.lossPct, 2)}%</span></td></tr>
      </table>
      ${r.cashLimited ? `<p class="small muted">許容損失の範囲ではもっと買えますが、運用資金に収まる株数に減らしています。</p>` : ""}
      ${form ? `<div class="actions"><button type="button" class="sz-use">この株数（${number(r.qty, 0)}株）を入力する</button></div>` : ""}`;
    out.querySelector(".sz-use")?.addEventListener("click", () => form.onUse(r.qty));
  }

  function refresh() {
    const { reason, aim } = form ? form.getReason() : {};
    const cands = stopCandidates({ kind, reason, aim, buyPrice: buyOf(), levels, cfg, digits });
    el.querySelector(".sz-cands").innerHTML = cands.length
      ? cands.map((c) => `<button type="button" data-sz-stop="${c.price}">${esc(c.label)} ${price(c.price, market)}</button>`).join("")
      : "";
    // 自分で入力していなければ、いちばん上の候補を入れておく
    if (stopInput.dataset.auto) stopInput.value = cands[0]?.price ?? "";
    renderResult();
  }

  el.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sz-stop]");
    if (!button) return;
    stopInput.value = button.dataset.szStop;
    stopInput.dataset.auto = "";
    renderResult();
  });
  el.addEventListener("input", (event) => {
    if (event.target === stopInput) {
      stopInput.dataset.auto = stopInput.value === "" ? "1" : "";
      renderResult();
    } else if (event.target.id === "sz-buy") {
      refresh();
    }
  });
  refresh();
  return { refresh };
}

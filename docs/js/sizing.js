// 資金管理の計算（ポジションサイズ・全体リスク）。画面に依存しない計算だけを置く（tests/js でテストする）。
// 資金額や保有の情報は、この端末のブラウザ（localStorage）の中だけで扱い、どこにも送らない。

export const SETTINGS_KEY = "settings:money";

// 運用資金の合計（円換算）。ドルの資金があるのに為替が分からなければ null
export function capitalJpy(settings, usdjpy) {
  const jpy = Number(settings?.jpy) || 0;
  const usd = Number(settings?.usd) || 0;
  if (usd > 0 && !(usdjpy > 0)) return null;
  return jpy + usd * (usdjpy || 0);
}

// 1回の取引で許容する損失（%）。自分で決めた値がなければ設定ファイルの初期値
export function riskPctOf(settings, cfg) {
  const own = Number(settings?.riskPct);
  return own > 0 ? own : cfg.sizing.risk_pct;
}

const roundTo = (value, digits) => Math.round(value * 10 ** digits) / 10 ** digits;

// 損切り価格の候補を「買った理由」から作る。
//   kind    … "contrarian" 逆張り / "momentum" 順張り
//   reason  … 買った理由（未選択なら空）。aim は条件3の −2σ／−3σ 狙い
//   levels  … 銘柄の水準 { bb_l3: −3σ, ma_fast: 50日線 }（ないものは省く）
// 戻り値は [{ key, label, price }]。買値より低いものだけを返す。
export function stopCandidates({ kind, reason, aim, buyPrice, levels = {}, cfg, digits = 2 }) {
  if (!(buyPrice > 0)) return [];
  const at = (pct) => roundTo(buyPrice * (1 + pct / 100), digits);
  const list = [];
  if (kind === "momentum" || reason === "mo") {
    const p = cfg.momentum.exit.stop_loss_pct;
    list.push({ key: "mo", label: `順張りの損切りルール（買値の${p}%）`, price: at(p) });
    if (levels.ma_fast != null) list.push({ key: "ma_fast", label: `${cfg.momentum.ma.fast}日線`, price: roundTo(levels.ma_fast, digits) });
  } else {
    const bb3 = levels.bb_l3 != null ? { key: "bb3", label: "−3σの価格", price: roundTo(levels.bb_l3, digits) } : null;
    const pct = { key: "pct", label: `買値の${cfg.sizing.stop_pct}%`, price: at(cfg.sizing.stop_pct) };
    if (reason === "c3" && aim === "2" && bb3) list.push({ ...bb3, label: "−3σの価格（−2σ狙いの損切りルール）" }, pct);
    else list.push(...[bb3, pct].filter(Boolean));
  }
  return list.filter((c) => c.price > 0 && c.price < buyPrice);
}

// 買ってよい株数を求める。
//   fx  … 1ドルの円換算（日本株は 1）
//   lot … 売買単位（日本株 100、米国株 1）
// 株数は「損切りになったときの損失が、資金 × 許容% 以下」かつ「必要資金が運用資金以下」になる最大の数。
// 1単位でも許容損失を超えるときは tooLarge、1単位も買えないときは unaffordable。
// 金額は、買える株数（0株のときは1単位）で計算する。
export function positionSize({ buyPrice, stopPrice, capitalJpy, riskPct, fx = 1, lot = 1 }) {
  if (!(buyPrice > 0)) return { error: "買値を入力してください。" };
  if (!(stopPrice > 0)) return { error: "損切り価格を入力してください。" };
  if (stopPrice >= buyPrice) return { error: "損切り価格は買値より低くしてください。" };
  if (!(capitalJpy > 0)) return { error: "「資金設定」で運用資金を入力してください。" };
  if (!(riskPct > 0)) return { error: "許容損失の割合を入力してください。" };
  if (!(fx > 0)) return { error: "為替レートを取得できないため計算できません。" };

  const budgetJpy = (capitalJpy * riskPct) / 100;
  const units = (value) => Math.floor(value / lot + 1e-9) * lot; // 割り切れる値が誤差で1つ減らないように
  const byRisk = units(budgetJpy / ((buyPrice - stopPrice) * fx));
  const byCash = units(capitalJpy / (buyPrice * fx));
  const qty = Math.max(0, Math.min(byRisk, byCash));
  const basisQty = qty > 0 ? qty : lot;
  const lossJpy = (buyPrice - stopPrice) * basisQty * fx;
  return {
    qty,
    lot,
    basisQty,
    budgetJpy,
    tooLarge: byRisk < lot,
    unaffordable: byRisk >= lot && byCash < lot,
    cashLimited: byCash < byRisk && byCash >= lot,
    cost: buyPrice * basisQty,
    costJpy: buyPrice * basisQty * fx,
    loss: (buyPrice - stopPrice) * basisQty,
    lossJpy,
    lossPct: (lossJpy / capitalJpy) * 100,
  };
}

// 保有全体のリスクと配分。
//   open … 保有中のポジション
//   info … ポジションごとに { price: 現在値（なければ null）, sector, themes } を返す関数
// 保有額は現在値（なければ買値）で、損切り時の損失は「買値 − 損切り価格」で計算する。
export function portfolioRisk(open, { capitalJpy: capital, usdjpy, cfg, info }) {
  const rows = [];
  const noStop = [], noFx = [];
  for (const pos of open) {
    const fx = pos.market === "us" ? usdjpy : 1;
    if (!(fx > 0)) {
      noFx.push(pos);
      continue;
    }
    const meta = info(pos) || {};
    const now = meta.price ?? pos.buyPrice;
    const hasStop = pos.stop > 0;
    if (!hasStop) noStop.push(pos);
    rows.push({
      pos,
      valueJpy: now * pos.qty * fx,
      costJpy: pos.buyPrice * pos.qty * fx,
      lossJpy: hasStop ? (pos.buyPrice - pos.stop) * pos.qty * fx : null,
      sector: meta.sector || "不明",
      themes: meta.themes?.length ? meta.themes : ["テーマなし"],
    });
  }
  const sum = (list, key) => list.reduce((acc, r) => acc + (r[key] ?? 0), 0);
  const totalValueJpy = sum(rows, "valueJpy");
  const totalLossJpy = sum(rows, "lossJpy");
  const base = capital > 0 ? capital : totalValueJpy; // 資金が未設定なら保有合計に対する割合
  const share = (value) => (base > 0 ? (value / base) * 100 : 0);

  const group = (keyOf) => {
    const map = new Map();
    for (const r of rows) for (const key of [keyOf(r)].flat()) map.set(key, (map.get(key) ?? 0) + r.valueJpy);
    return [...map.entries()].map(([name, valueJpy]) => ({ name, valueJpy, pct: share(valueJpy) })).sort((a, b) => b.valueJpy - a.valueJpy);
  };
  const byStock = group((r) => `${r.pos.name}（${r.pos.code}）`);
  const bySector = group((r) => r.sector);
  const byTheme = group((r) => r.themes);
  const byMarket = group((r) => (r.pos.market === "us" ? "米国株（ドル）" : "日本株（円）"));

  const s = cfg.sizing;
  const warnings = [];
  for (const g of byStock) if (g.pct > s.max_stock_pct) warnings.push({ type: "stock", name: g.name, pct: g.pct, limit: s.max_stock_pct });
  for (const g of bySector) if (g.pct > s.max_sector_pct) warnings.push({ type: "sector", name: g.name, pct: g.pct, limit: s.max_sector_pct });

  // 信用取引: 信用で建てた額の合計が、現金（運用資金 − 現物で買った額）を超えたら警告
  const marginRows = rows.filter((r) => r.pos.margin);
  const marginJpy = sum(marginRows, "costJpy");
  const cashJpy = capital > 0 ? capital - sum(rows.filter((r) => !r.pos.margin), "costJpy") : null;
  const marginOver = marginRows.length > 0 && cashJpy != null && marginJpy > cashJpy;

  return {
    count: rows.length,
    totalValueJpy,
    totalLossJpy,
    lossPct: capital > 0 ? (totalLossJpy / capital) * 100 : null,
    base: capital > 0 ? "capital" : "holdings",
    noStop,
    noFx,
    byStock,
    bySector,
    byTheme,
    byMarket,
    warnings,
    margin: { count: marginRows.length, marginJpy, cashJpy, over: marginOver },
  };
}

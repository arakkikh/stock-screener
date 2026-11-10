// 出口ルール。「買った理由」ごとに、利確と損切りの条件を決める。
// 画面に依存しない計算だけを置く（tests/js でテストする）。

export const REASON_KEYS = ["c1", "c2", "c3", "theme"];

export function reasonLabel(key, cfg, aim) {
  switch (key) {
    case "c1": return `条件1（前日比 ${cfg.buy.drop_pct}%以下の急落）`;
    case "c2": return `条件2（${cfg.ma.mid}日線割れ）`;
    case "c3": return `条件3（ボリンジャーバンド${aim ? ` −${aim}σ狙い` : ""}）`;
    case "theme": return "テーマ・業績";
    default: return key;
  }
}

// 条件1で買ったときの利確水準を求める。
// 買った日から数日さかのぼって急落日を探し、「急落前日の終値 × (1 − 2.5%)」を返す。
export function findDropReference(chart, buyDate, cfg, digits = 1) {
  const drop = cfg.buy.drop_pct;
  let last = chart.t.length - 1;
  while (last >= 0 && chart.t[last] > buyDate) last--;
  for (let i = last; i >= 1 && i > last - cfg.exit.drop_lookback_days; i--) {
    const change = (chart.c[i] / chart.c[i - 1] - 1) * 100;
    if (change <= drop + 1e-9) {
      const scale = 10 ** digits;
      return {
        dropDate: chart.t[i],
        refClose: chart.c[i - 1],
        target: Math.round(chart.c[i - 1] * (1 + drop / 100) * scale) / scale,
      };
    }
  }
  return null;
}

// ポジションの出口（利確・損切り）を返す。
//   level = 目安の値段（なければ null）
//   hit   = 最新の終値で条件に到達しているか（判定できなければ null）
//   manual = 自分で判断する条件か
export function exitPlan(pos, stock, cfg, today) {
  const close = stock ? stock.close : null;
  const lv = stock ? stock.levels : {};
  const reached = (level) => (close == null || level == null ? null : close >= level);
  const scenario = { text: "シナリオが崩れたら損切り（メモの「何が起きたら負けか」）", level: null, hit: null, manual: true };

  switch (pos.reason) {
    case "c1":
      return {
        take: { text: `急落前の終値から ${cfg.buy.drop_pct}% の水準まで戻したら利確`, level: pos.target, hit: reached(pos.target) },
        stop: scenario,
      };
    case "c2":
      return {
        take: { text: `${cfg.ma.mid}日線まで戻したら利確`, level: lv.ma_mid ?? null, hit: reached(lv.ma_mid) },
        stop: scenario,
      };
    case "c3": {
      const take = { text: `ボリンジャーバンドの中央線（${cfg.buy.bb_period}日線）まで戻したら利確`, level: lv.bb_mid ?? null, hit: reached(lv.bb_mid) };
      if (pos.aim !== "2") return { take, stop: scenario };
      const broke = close == null || lv.bb_l3 == null ? null : close < lv.bb_l3;
      return { take, stop: { text: "−3σを終値で下に抜けたら損切り", level: lv.bb_l3 ?? null, hit: broke, manual: false } };
    }
    case "theme":
      return {
        take: { text: `自分で決めた期限（${pos.deadline}）が来たら手仕舞い`, level: null, hit: today >= pos.deadline },
        stop: { text: "買った根拠が崩れたら損切り", level: null, hit: null, manual: true },
      };
    default:
      throw new Error(`買った理由が不明です: ${pos.reason}`);
  }
}

// 登録フォームの入力チェック。問題があれば、その説明の一覧を返す。
export function validatePosition(p) {
  const errors = [];
  const positive = (v) => typeof v === "number" && Number.isFinite(v) && v > 0;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(p.buyDate || "")) errors.push("買った日を入力してください。");
  if (!positive(p.buyPrice)) errors.push("買値を正の数で入力してください。");
  if (!positive(p.qty)) errors.push("株数を正の数で入力してください。");
  if (!REASON_KEYS.includes(p.reason)) errors.push("買った理由を選んでください。");
  if (p.reason === "c1" && !positive(p.target)) errors.push("利確の水準を入力してください。");
  if (p.reason === "c3" && !["2", "3"].includes(p.aim)) errors.push("−2σ狙いか −3σ狙いかを選んでください。");
  if (p.reason === "theme" && !/^\d{4}-\d{2}-\d{2}$/.test(p.deadline || "")) errors.push("手仕舞いの期限を入力してください。");
  const memo = p.memo || {};
  if (!(memo.why || "").trim()) errors.push("メモ「なぜこの銘柄か」は必須です。");
  if (!(memo.basis || "").trim()) errors.push("メモ「根拠は何か」は必須です。");
  if (!(memo.lose || "").trim()) errors.push("メモ「何が起きたら負けか」は必須です。");
  return errors;
}

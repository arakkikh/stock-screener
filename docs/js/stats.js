// 売買成績の分析（決済済みの取引から）。画面に依存しない計算だけを置く（tests/js でテストする）。
// 売買記録はこの端末のブラウザ（localStorage）の中だけで扱い、どこにも送らない。

// ------------------------------------------------------------ ルール違反

export const VIOLATIONS = {
  earnings: "決算をまたいだ",
  switch: "買った理由と違う理由で売った／持ち続けた",
  ignoredStop: "損切りラインを過ぎても売らなかった",
  noMemo: "理由メモなしで買った",
};
export const SWITCH_REASON = "ルール外（理由のすり替え）";

// 自動で判定できるルール違反を調べる。判定できないものは null（自己申告にまかせる）。
//   earningsDates … 決算発表日の一覧（分かる範囲で）。なければ null
//   chart         … 日足 { t: 日付, c: 終値 }。なければ null
// 決算をまたいだ: 買った日から売った日の前日までに決算発表日がある（発表日に売れば、またいでいない）
// 損切りラインを過ぎても売らなかった: 終値が損切り価格を下回った日の、翌営業日より後に売った
export function autoViolations(pos, sell, { earningsDates = null, chart = null } = {}) {
  const memo = pos.memo || {};
  const result = {
    noMemo: !(memo.why || "").trim() || !(memo.basis || "").trim() || !(memo.lose || "").trim(),
    switch: sell.reason === SWITCH_REASON ? true : null,
    earnings: null,
    ignoredStop: null,
  };
  if (earningsDates) result.earnings = earningsDates.some((d) => d >= pos.buyDate && d < sell.date);
  const stop = pos.stop > 0 ? pos.stop : null;
  if (stop && chart?.t?.length && chart.t[0] <= pos.buyDate) {
    result.ignoredStop = false;
    for (let i = 0; i < chart.t.length; i++) {
      const day = chart.t[i];
      if (day < pos.buyDate) continue;
      if (day >= sell.date) break;
      if (chart.c[i] != null && chart.c[i] < stop) {
        const nextDay = chart.t[i + 1];
        result.ignoredStop = nextDay != null && sell.date > nextDay;
        break;
      }
    }
  }
  return result;
}

export const hasViolation = (sell) => Object.values(sell?.violations ?? {}).some(Boolean);

// ------------------------------------------------------------ 1回分の取引

const DAY = 86400000;

// 決済済みポジション1件を、集計しやすい形にする。
//   pnl     … 損益（その市場の通貨。手数料を引く）
//   pnlJpy  … 円換算（ドル建てで為替がなければ null）
//   r       … R倍数（登録時の損切り幅を1Rとする。損切り価格がなければ null）
export function tradeOf(p, usdjpy) {
  const pnl = (p.sell.price - p.buyPrice) * p.qty - (p.sell.fee || 0);
  const fx = p.market === "us" ? usdjpy : 1;
  const stop0 = p.stop0 > 0 ? p.stop0 : p.stop > 0 ? p.stop : null;
  const risk = stop0 && stop0 < p.buyPrice ? p.buyPrice - stop0 : null;
  return {
    pos: p,
    pnl,
    pnlJpy: fx > 0 ? pnl * fx : null,
    ret: (p.sell.price / p.buyPrice - 1) * 100,
    days: Math.round((new Date(p.sell.date) - new Date(p.buyDate)) / DAY),
    r: risk ? (p.sell.price - p.buyPrice) / risk : null,
    violated: hasViolation(p.sell),
  };
}

// ------------------------------------------------------------ 集計

const mean = (list) => (list.length ? list.reduce((a, b) => a + b, 0) / list.length : null);

// 取引の一覧を成績にまとめる。金額はすべて円換算（為替がなく換算できないものは金額の集計から外す）。
//   win      … 勝率(%)。損益ゼロは勝ちにも負けにも数えない
//   payoff   … 損益比 = 平均利益 ÷ 平均損失の大きさ
//   expect   … 期待値 = 1回あたりの平均損益
//   streak   … 最大連敗（決済日の順）
//   few      … 件数が minSamples 未満なら true（参考値）
export function summarize(trades, minSamples) {
  const n = trades.length;
  const money = trades.filter((t) => t.pnlJpy != null);
  const wins = money.filter((t) => t.pnlJpy > 0).map((t) => t.pnlJpy);
  const losses = money.filter((t) => t.pnlJpy < 0).map((t) => t.pnlJpy);
  const avgWin = mean(wins), avgLoss = mean(losses);
  const ordered = [...trades].sort((a, b) => cmp(a.pos.sell.date, b.pos.sell.date) || cmp(a.pos.buyDate, b.pos.buyDate));
  let streak = 0, run = 0;
  for (const t of ordered) {
    run = t.pnl < 0 ? run + 1 : 0;
    streak = Math.max(streak, run);
  }
  const rs = trades.filter((t) => t.r != null).map((t) => t.r);
  return {
    n,
    win: n ? (trades.filter((t) => t.pnl > 0).length / n) * 100 : null,
    avgWin,
    avgLoss,
    payoff: avgWin != null && avgLoss != null ? avgWin / Math.abs(avgLoss) : null,
    expect: mean(money.map((t) => t.pnlJpy)),
    totalJpy: money.reduce((a, t) => a + t.pnlJpy, 0),
    streak,
    days: mean(trades.map((t) => t.days)),
    rN: rs.length,
    avgR: mean(rs),
    unconverted: n - money.length,
    few: n < minSamples,
  };
}

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// keyOf(trade) で分けて、それぞれ集計する。order を渡すとその順に並べる（なければ件数の多い順）
export function groupStats(trades, keyOf, minSamples, order = null) {
  const map = new Map();
  for (const t of trades) {
    const key = keyOf(t);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(t);
  }
  const rows = [...map.entries()].map(([key, list]) => ({ key, stats: summarize(list, minSamples) }));
  if (order) return rows.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  return rows.sort((a, b) => b.stats.n - a.stats.n || cmp(a.key, b.key));
}

export const kindOf = (p) => (p.kind === "momentum" || p.reason === "mo" ? "momentum" : "contrarian");

// ------------------------------------------------------------ 指数との比較

// その日（なければ直前の営業日）の指数の終値。データより前なら null
function closeOn(index, date) {
  let found = null;
  for (let i = 0; i < index.t.length && index.t[i] <= date; i++) if (index.c[i] != null) found = index.c[i];
  return found;
}

// 同じ日に同じ金額で指数を買い、同じ日に売った場合の損益（その市場の通貨）。
// 比べやすいように、実際の損益も手数料を含めない値を返す。
export function vsIndex(p, index) {
  if (!index?.t?.length || p.buyDate < index.t[0]) return null;
  const from = closeOn(index, p.buyDate), to = closeOn(index, p.sell.date);
  if (from == null || to == null) return null;
  const amount = p.buyPrice * p.qty;
  const cents = (value) => Math.round(value * 100) / 100; // 小数の計算誤差を落とす
  return {
    actual: cents((p.sell.price - p.buyPrice) * p.qty),
    index: cents(amount * (to / from - 1)),
    indexRet: Math.round((to / from - 1) * 1e6) / 1e4,
  };
}

// 指定した年に決済した取引の、実際の損益と指数の損益の累計（円換算）。
// indexes = { jp: 日経平均, us: S&P 500 }。比べられない取引は missing に数える
export function ytdVsIndex(positions, year, indexes, usdjpy) {
  let actual = 0, index = 0, count = 0, missing = 0;
  for (const p of positions) {
    if (!p.sell || !p.sell.date.startsWith(String(year))) continue;
    const fx = p.market === "us" ? usdjpy : 1;
    const v = vsIndex(p, indexes[p.market]);
    if (!v || !(fx > 0)) {
      missing++;
      continue;
    }
    actual += v.actual * fx;
    index += v.index * fx;
    count++;
  }
  return { actual, index, diff: actual - index, count, missing, beat: count ? actual > index : null };
}

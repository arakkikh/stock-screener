// 確定損益の集計と、撤退ルールの判定。画面に依存しない計算だけを置く。

// 決済済みポジション1件の損益（その市場の通貨）
export function pnl(p) {
  return (p.sell.price - p.buyPrice) * p.qty - (p.sell.fee || 0);
}

// 年初からの確定損益。
//   jp / us    … 市場ごとの合計（円／ドル）
//   totalJpy   … 円換算の合計（ドル建ての損益があるのに為替が取れないときは null）
//   peakJpy    … 年初来でいちばん利益が多かった時点の額
//   status     … "none" 決済なし / "ok" / "warn" ゼロに近づいた / "retreat" ゼロ以下（撤退）
export function ytd(positions, year, usdjpy, warnRemainingPct) {
  const closed = positions
    .filter((p) => p.sell && p.sell.date.startsWith(String(year)))
    .sort((a, b) => (a.sell.date < b.sell.date ? -1 : a.sell.date > b.sell.date ? 1 : 0));
  const result = { jp: 0, us: 0, totalJpy: 0, peakJpy: 0, count: closed.length, status: "none" };
  if (!closed.length) return result;

  const needFx = closed.some((p) => p.market === "us");
  let total = 0, peak = 0;
  for (const p of closed) {
    const value = pnl(p);
    result[p.market] += value;
    total += p.market === "us" ? value * (usdjpy || 0) : value;
    peak = Math.max(peak, total);
  }
  if (needFx && !usdjpy) return { ...result, totalJpy: null, peakJpy: null, status: "unknown" };

  result.totalJpy = total;
  result.peakJpy = peak;
  if (total <= 0) result.status = "retreat";
  else if (total <= (peak * warnRemainingPct) / 100) result.status = "warn";
  else result.status = "ok";
  return result;
}

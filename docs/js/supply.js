// 需給メモの計算（信用残・空売り比率・投資部門別）。画面に依存しない計算だけを置く（tests/js でテストする）。
// 値は自分で公式サイトを見て手入力したもので、この端末のブラウザ（localStorage）の中だけに保存する。
// 取得元の規約で再配布が認められていないため、リポジトリ・GitHub Actions・通知には出さない。

export const MARKET_KEY = "sd:mkt:jp";
export const stockKey = (market, code) => `sd:stock:${market}:${code}`;

const byDate = (a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0);
const daysBetween = (from, to) => Math.round((new Date(to) - new Date(from)) / 86400000);

// 同じ日付の記録は置き換え、日付順に並べる
export function upsert(list, entry) {
  return [...(list ?? []).filter((e) => e.d !== entry.d), entry].sort(byDate);
}

export function removeDate(list, d) {
  return (list ?? []).filter((e) => e.d !== d);
}

// date（その日がなければ直前の営業日）までの days 営業日の平均出来高。足りなければ null
export function avgVolume(chart, date, days = 25) {
  if (!chart?.t?.length || !chart.v) return null;
  let end = chart.t.length - 1;
  while (end >= 0 && chart.t[end] > date) end--;
  if (end + 1 < days) return null;
  const part = chart.v.slice(end + 1 - days, end + 1).filter((v) => v != null && v > 0);
  return part.length < days * 0.8 ? null : part.reduce((a, b) => a + b, 0) / part.length;
}

// 信用残の状態。entries = [{ d: 週末の日付, buy: 買い残(株), sell: 売り残(株), vol: 25日平均出来高(あれば) }]
//   ratio    … 信用倍率（売り残がゼロなら null）
//   buyDays  … 買い残が平均出来高の何日分か（出来高が分からなければ null）
//   rising   … 買い残が rising_weeks 週続けて増えている
//   signals  … overhang「戻り売りが出やすい」/ squeeze「買い戻しが入りやすい」
export function marginState(entries, cfg, today) {
  const list = [...(entries ?? [])].sort(byDate);
  if (!list.length) return null;
  const s = cfg.supply;
  const latest = list[list.length - 1];
  const prev = list.length >= 2 ? list[list.length - 2] : null;
  const ratio = latest.sell > 0 ? latest.buy / latest.sell : null;
  const buyDays = latest.vol > 0 ? latest.buy / latest.vol : null;
  const sellDays = latest.vol > 0 ? latest.sell / latest.vol : null;
  const recent = list.slice(-(s.rising_weeks + 1));
  const rising = recent.length === s.rising_weeks + 1 && recent.every((e, i) => i === 0 || e.buy > recent[i - 1].buy);
  const heavy = buyDays != null ? buyDays >= s.buy_days_high - 1e-9 : ratio != null && ratio >= s.ratio_high - 1e-9;
  const signals = [];
  if (heavy && rising) signals.push({ key: "overhang", text: "戻り売りが出やすい", why: buyDays != null ? `買い残が平均出来高の${buyDays.toFixed(1)}日分あり、${s.rising_weeks}週続けて増加` : `信用倍率${ratio.toFixed(1)}倍で、買い残が${s.rising_weeks}週続けて増加` });
  if ((ratio != null && ratio <= s.ratio_low + 1e-9) || (sellDays != null && sellDays >= s.sell_days_high - 1e-9))
    signals.push({ key: "squeeze", text: "買い戻しが入りやすい", why: ratio != null && ratio <= s.ratio_low + 1e-9 ? `信用倍率${ratio.toFixed(2)}倍（${s.ratio_low}倍以下）` : `売り残が平均出来高の${sellDays.toFixed(1)}日分` });
  const pct = (a, b) => (b > 0 ? (a / b - 1) * 100 : null);
  return {
    latest,
    prev,
    ratio,
    buyDays,
    sellDays,
    buyChange: prev ? pct(latest.buy, prev.buy) : null,
    sellChange: prev ? pct(latest.sell, prev.sell) : null,
    rising,
    signals,
    stale: today ? daysBetween(latest.d, today) > s.stale_days : false,
  };
}

// 空売り比率の状態。list = [{ d, v: 空売り比率(%) }]
export function shortRatioState(list, cfg, today) {
  const sorted = [...(list ?? [])].sort(byDate);
  if (!sorted.length) return null;
  const s = cfg.supply;
  const latest = sorted[sorted.length - 1];
  const before = sorted.slice(-6, -1);
  const avg = before.length ? before.reduce((a, e) => a + e.v, 0) / before.length : null;
  return {
    latest,
    avg,
    high: latest.v >= s.short_high - 1e-9,
    jump: avg != null && latest.v - avg >= s.short_jump_pt - 1e-9,
    stale: today ? daysBetween(latest.d, today) > s.stale_days : false,
  };
}

// 投資部門別（週次）の集計。list = [{ d: 週の最終日, foreign, individual, trust }]（差し引き、億円。空欄は null）
export function flowSummary(list, weeks = 4) {
  const sorted = [...(list ?? [])].sort(byDate);
  if (!sorted.length) return null;
  const part = sorted.slice(-weeks);
  const sum = (key) => {
    const values = part.map((e) => e[key]).filter((v) => v != null);
    return values.length ? values.reduce((a, b) => a + b, 0) : null;
  };
  return { latest: sorted[sorted.length - 1], weeks: part.length, from: part[0].d, foreign: sum("foreign"), individual: sum("individual"), trust: sum("trust") };
}

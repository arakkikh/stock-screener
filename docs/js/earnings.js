// 決算発表日の扱い。「決算はまたがない」警告の判定。
import { store } from "./store.js";
import { shortDate, todayISO } from "./format.js";

// earnings = { next, prev_session, last }（自動取得）、override = 手入力した決算日
// 警告を出すのは、決算日の前営業日から決算日当日まで。
export function earningsStatus(earnings, today, override = null) {
  const e = earnings || {};
  if (override) {
    if (override < today) return { soon: false, text: `${shortDate(override)}（手入力・終了）`, manual: true };
    // 手入力の場合は前営業日が分からないので、4日前から警告する（週末をまたいでも前営業日を含む）
    const from = new Date(new Date(override).getTime() - 4 * 86400000).toISOString().slice(0, 10);
    return { soon: today >= from, text: `${shortDate(override)} 予定（手入力）`, next: override, manual: true };
  }
  if (!e.next) return { soon: false, text: e.last ? `直近 ${shortDate(e.last)}（次回は未定）` : "不明" };
  return { soon: today >= e.prev_session && today <= e.next, text: `${shortDate(e.next)} 予定`, next: e.next };
}

export const overrideKey = (market, code) => `earn:${market}:${code}`;

export function earningsInfo(market, stock) {
  return earningsStatus(stock.earnings, todayISO(), store.get(overrideKey(market, stock.code)));
}

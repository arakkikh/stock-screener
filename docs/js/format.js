// 数値や日付の表示用の整形。

export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function price(value, market) {
  if (value == null) return "—";
  const us = market === "us";
  const text = value.toLocaleString("ja-JP", { minimumFractionDigits: us ? 2 : 0, maximumFractionDigits: us ? 2 : 1 });
  return us ? "$" + text : text + "円";
}

export function number(value, digits = 2) {
  if (value == null) return "—";
  return value.toLocaleString("ja-JP", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(value, digits = 2) {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return sign + Math.abs(value).toFixed(digits) + "%";
}

export function signClass(value) {
  return value > 0 ? "up" : value < 0 ? "down" : "";
}

// "2026-11-10" → "11/10"
export function shortDate(iso) {
  if (!iso) return "—";
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
}

export function todayISO() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export function daysBetween(fromISO, toISO) {
  return Math.round((new Date(toISO) - new Date(fromISO)) / 86400000);
}

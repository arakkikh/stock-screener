// イベントカレンダーの画面と、画面上部の注意（重要イベント・保有銘柄の決算）。
// 保有銘柄はブラウザ内の記録（localStorage）と組み合わせるだけで、どこにも送らない。
import { esc, shortDate, todayISO } from "./format.js";
import { earningsStatus, overrideKey } from "./earnings.js";
import { store } from "./store.js";

const WEEK = ["日", "月", "火", "水", "木", "金", "土"];
const MARKET = { jp: "日本", us: "米国" };
const DAYS = 31; // 画面に出す日数

const dayLabel = (iso) => `${shortDate(iso)}（${WEEK[new Date(iso + "T00:00:00").getDay()]}）`;
const addDays = (iso, n) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// 決算予定を集める。markets = { jp, us }（逆張りのデータ）、momentum = { jp, us }（順張りのデータ。合格銘柄のみ決算あり）
export function earningsEvents(markets, momentum, positions, from, to) {
  const held = new Set(positions.filter((p) => !p.sell).map((p) => `${p.market}:${p.code}`));
  const seen = new Map();
  for (const m of ["jp", "us"]) {
    for (const source of [markets[m], momentum?.[m]]) {
      for (const s of source?.stocks ?? []) {
        const key = `${m}:${s.code}`;
        const manual = store.get(overrideKey(m, s.code));
        const date = manual || s.earnings?.next;
        if (!date || date < from || date > to || seen.has(key)) continue;
        seen.set(key, { date, market: m, code: s.code, name: s.name, held: held.has(key), manual: Boolean(manual) });
      }
    }
  }
  // 保有中なのに対象銘柄から外れた銘柄も、手入力の決算日があれば出す
  for (const p of positions.filter((x) => !x.sell)) {
    const key = `${p.market}:${p.code}`;
    const manual = store.get(overrideKey(p.market, p.code));
    if (!seen.has(key) && manual && manual >= from && manual <= to) seen.set(key, { date: manual, market: p.market, code: p.code, name: p.name, held: true, manual: true });
  }
  return [...seen.values()];
}

function dayHTML(date, items, earnings, today) {
  const rows = items
    .map((e) => `<li class="${e.important ? "important" : ""}"><span class="badge ${e.market === "jp" ? "" : "tag"}">${MARKET[e.market]}</span>
      ${e.important ? "<b>" : ""}${esc(e.name)}${e.important ? "</b>" : ""}${e.note ? `<br><span class="small muted">${esc(e.note)}</span>` : ""}</li>`)
    .join("");
  const heldFirst = [...earnings].sort((a, b) => Number(b.held) - Number(a.held) || a.market.localeCompare(b.market));
  const earn = earnings.length
    ? `<li><span class="badge">決算</span> ${heldFirst.slice(0, 12)
        .map((e) => `${e.held ? `<b class="warn-text">${esc(e.name)}（保有中）</b>` : esc(e.name)}`)
        .join("、")}${earnings.length > 12 ? ` ほか${earnings.length - 12}社` : ""}</li>`
    : "";
  return `<div class="cal-day ${date === today ? "today" : ""}"><div class="cal-date">${dayLabel(date)}${date === today ? "　今日" : ""}</div>
    <ul class="plain cal-items">${rows}${earn}</ul></div>`;
}

export function renderCalendar(app, data, markets, momentum, positions) {
  if (!data) {
    app.innerHTML = `<p class="pad">イベントのデータがまだありません。次のデータ更新のあとに表示されます。</p>`;
    return;
  }
  const today = todayISO();
  const to = addDays(today, DAYS);
  const events = data.events.filter((e) => e.date >= today && e.date <= to);
  const earnings = earningsEvents(markets, momentum, positions, today, to);
  const dates = [...new Set([...events.map((e) => e.date), ...earnings.map((e) => e.date)])].sort();
  const heldSoon = earnings.filter((e) => e.held);
  const sources = Object.values(data.sources ?? {})
    .map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>（${esc(s.checked)} 確認）</li>`)
    .join("");
  app.innerHTML = `
    <section class="card">
      <h2>イベントカレンダー（今後${DAYS}日）</h2>
      <p class="small muted">重要イベント（太字）は、前営業日と当日に画面上部へ注意を出します。米国のイベントは米国の日付で、日本時間では夜〜翌朝の発表です。</p>
      ${(data.warnings ?? []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("")}
      ${heldSoon.length ? `<div class="alert warn">保有中の銘柄の決算が${DAYS}日以内にあります<small>${heldSoon.map((e) => `${esc(e.name)}（${shortDate(e.date)}）`).join("、")}。決算はまたがない。</small></div>` : ""}
    </section>
    <section class="card">${dates.length ? dates.map((d) => dayHTML(d, events.filter((e) => e.date === d), earnings.filter((e) => e.date === d), today)).join("") : `<p class="small muted">イベントはありません。</p>`}</section>
    <section class="card small">
      <h2>日程の出典</h2>
      <ul class="plain">${sources}</ul>
      <p class="muted">FOMC・日銀会合・CPI・雇用統計の日程は年に1回、公式サイトで確認して手で更新しています（config/events.yaml）。SQ・オプション満期日・休場日は自動で計算しています。
        決算日は自動取得した予定日で、変わることがあります（逆張りの対象銘柄と、順張りの全条件合格銘柄のみ）。</p>
      <p class="muted">日程は目安です。投資助言ではありません。</p>
    </section>`;
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------ 画面上部の注意

// 重要イベントの前営業日・当日と、保有銘柄の決算が近いときの注意。
export function bannerHTML(data, markets, positions, today = todayISO()) {
  const out = [];
  for (const e of data?.events ?? []) {
    if (!e.important) continue;
    if (e.date === today) out.push(`今日は${esc(e.name)}${e.market === "us" ? "（発表は日本時間の今夜〜明朝）" : ""}`);
    else if (e.prev === today) out.push(`次の営業日（${shortDate(e.date)}）は${esc(e.name)}`);
  }
  for (const p of positions.filter((x) => !x.sell)) {
    const stock = markets?.[p.market]?.stocks.find((s) => s.code === p.code);
    const status = earningsStatus(stock?.earnings, today, store.get(overrideKey(p.market, p.code)));
    if (status.soon) out.push(`保有中の${esc(p.name)}の決算が近い（${shortDate(status.next)}）`);
  }
  if (!out.length) return "";
  return `<div class="alert warn banner">${out.join("<br>")}<small><a href="#calendar">カレンダーを見る</a>　目安です。投資助言ではありません。</small></div>`;
}

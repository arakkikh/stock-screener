// 需給メモの画面（市場全体と個別銘柄）。値は自分で公式サイトを見て手入力し、この端末のブラウザにだけ保存する。
// 取得元の規約で再配布が認められていないため、リポジトリ・GitHub Actions・通知には出さない。
import { store } from "./store.js";
import { esc, number, pct, shortDate, todayISO } from "./format.js";
import { lineChart } from "./regime.js";
import { MARKET_KEY, stockKey, upsert, removeDate, avgVolume, marginState, shortRatioState, flowSummary } from "./supply.js";

const NOTE = `<p class="small muted">自分で公式サイトを見て入力した値です。この端末のブラウザにだけ保存され、インターネット上には送られません（エクスポートには含まれます）。表示は目安で、投資助言ではありません。</p>`;
const SOURCE = `<p class="small muted">数字は日本取引所グループ（<a href="https://www.jpx.co.jp/" target="_blank" rel="noopener">jpx.co.jp</a>）の「マーケット情報」→「統計情報（株式関連）」にある「空売り集計」「投資部門別売買状況」「信用取引残高」で確認できます。</p>`;

const loadMarket = () => store.get(MARKET_KEY, { short: [], flows: [] });
export const loadStock = (market, code) => store.get(stockKey(market, code), []);

// 直近の金曜日（信用残は週末＝金曜申込み分で公表される）
export function lastFriday(today = todayISO()) {
  const d = new Date(today + "T00:00:00");
  d.setDate(d.getDate() - ((d.getDay() + 2) % 7));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const oku = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${number(Math.abs(v), 0)}億円`);
const shares = (v) => (v == null ? "—" : `${number(v, 0)}株`);

// ------------------------------------------------------------ 市場全体（日本株）

export function marketMemoHTML(cfg) {
  if (!cfg?.supply) return "";
  const m = loadMarket();
  const today = todayISO();
  const sr = shortRatioState(m.short, cfg, today);
  const fl = flowSummary(m.flows, 4);
  const srLine = sr
    ? `空売り比率 <b>${number(sr.latest.v, 1)}%</b>（${shortDate(sr.latest.d)}時点）${sr.high ? ` <span class="badge warn">高い</span>` : ""}${sr.jump ? ` <span class="badge warn">急上昇</span>` : ""}${sr.stale ? ` <span class="badge">入力が古い</span>` : ""}`
    : "空売り比率: データなし";
  const flLine = fl
    ? `直近${fl.weeks}週の売買差額（${shortDate(fl.from)}〜${shortDate(fl.latest.d)}の週）: 海外投資家 <b>${oku(fl.foreign)}</b>・個人 <b>${oku(fl.individual)}</b>${fl.trust != null ? `・信託銀行 ${oku(fl.trust)}` : ""}`
    : "投資部門別: データなし";
  const shortRows = [...m.short].reverse().slice(0, 10)
    .map((e) => `<tr><td>${shortDate(e.d)}</td><td class="num">${number(e.v, 1)}%</td><td><button type="button" class="link" data-sd="del-short" data-d="${e.d}">削除</button></td></tr>`).join("");
  const flowRows = [...m.flows].reverse().slice(0, 8)
    .map((e) => `<tr><td>${shortDate(e.d)}週</td><td class="num">${oku(e.foreign)}</td><td class="num">${oku(e.individual)}</td><td><button type="button" class="link" data-sd="del-flow" data-d="${e.d}">削除</button></td></tr>`).join("");
  const s = cfg.supply;
  return `<section class="card" id="sd-market">
    <h2>需給メモ（手入力）</h2>
    <p class="small">${srLine}<br>${flLine}</p>
    <details><summary class="small">入力する・推移を見る</summary>
      <form class="form" data-sd-form="short">
        <div class="grid2">
          <div><label>空売り比率の日付</label><input type="date" name="d" value="${today}"></div>
          <div><label>空売り比率（%）</label><input type="number" name="v" step="0.1" inputmode="decimal" placeholder="例: 42.5"></div>
        </div>
        <div class="actions"><button type="submit">空売り比率を保存</button></div>
      </form>
      <form class="form" data-sd-form="flow">
        <div class="grid2">
          <div><label>週の最終日</label><input type="date" name="d" value="${lastFriday(today)}"></div>
          <div><label>海外投資家の差し引き（億円）</label><input type="number" name="foreign" step="1" inputmode="numeric" placeholder="買い越しは＋、売り越しは−"></div>
          <div><label>個人の差し引き（億円）</label><input type="number" name="individual" step="1" inputmode="numeric"></div>
          <div><label>信託銀行の差し引き（億円・任意）</label><input type="number" name="trust" step="1" inputmode="numeric"></div>
        </div>
        <div class="actions"><button type="submit">投資部門別を保存</button></div>
      </form>
      ${m.short.length >= 2 ? lineChart("空売り比率（%）", m.short.map((e) => e.d), [{ values: m.short.map((e) => e.v), cls: "s3", label: "空売り比率" }], { lines: [{ value: s.short_high, label: `${s.short_high}%` }] }) : ""}
      ${m.flows.length >= 2 ? lineChart("投資部門別の売買差額（億円）", m.flows.map((e) => e.d), [
        { values: m.flows.map((e) => e.foreign), cls: "s1", label: "海外投資家" },
        { values: m.flows.map((e) => e.individual), cls: "s2", label: "個人" },
      ], { lines: [{ value: 0, label: "0" }] }) : ""}
      ${shortRows ? `<h3>空売り比率（新しい順）</h3><table class="kv">${shortRows}</table>` : ""}
      ${flowRows ? `<h3>投資部門別（新しい順）</h3><table class="bt"><tr><th>週</th><th>海外投資家</th><th>個人</th><th></th></tr>${flowRows}</table>` : ""}
      <p class="small muted">基準（仮置き）: 空売り比率 ${s.short_high}%以上で「高い」、直近5回の平均より${s.short_jump_pt}ポイント以上高いと「急上昇」。相場環境の判定には使っていません。</p>
      ${SOURCE}
    </details>
    ${NOTE}
  </section>`;
}

// ------------------------------------------------------------ 個別銘柄

export function stockState(market, code, cfg) {
  return cfg?.supply ? marginState(loadStock(market, code), cfg, todayISO()) : null;
}

// 一覧の行に付ける印
export function supplyBadges(market, stock, cfg) {
  const st = stockState(market, stock.code, cfg);
  if (!st) return "";
  return st.signals
    .map((g) => `<span class="badge ${g.key === "overhang" ? "warn" : "good"}">${g.key === "overhang" ? "戻り売り注意" : "買い戻し期待"}</span>`)
    .join("");
}

export function stockMemoHTML(market, stock, cfg) {
  if (market !== "jp" || !cfg?.supply) return "";
  const list = loadStock(market, stock.code);
  const st = marginState(list, cfg, todayISO());
  const s = cfg.supply;
  const summary = st
    ? `<table class="kv">
        <tr><td>信用倍率<br><span class="small muted">${shortDate(st.latest.d)}の週時点</span></td><td class="num"><strong>${st.ratio == null ? "—（売り残なし）" : number(st.ratio, 2) + "倍"}</strong></td></tr>
        <tr><td>信用買い残</td><td class="num">${shares(st.latest.buy)}<br><span class="small muted">前週比 ${pct(st.buyChange, 1)}${st.buyDays != null ? `・平均出来高の${number(st.buyDays, 1)}日分` : ""}</span></td></tr>
        <tr><td>信用売り残</td><td class="num">${shares(st.latest.sell)}<br><span class="small muted">前週比 ${pct(st.sellChange, 1)}${st.sellDays != null ? `・平均出来高の${number(st.sellDays, 1)}日分` : ""}</span></td></tr>
      </table>
      ${st.signals.map((g) => `<div class="alert ${g.key === "overhang" ? "warn" : "info"}">${g.text}<small>${esc(g.why)}（基準は仮置き）</small></div>`).join("")}
      ${st.stale ? `<div class="alert info">最後の入力（${shortDate(st.latest.d)}の週）から${s.stale_days}日以上たっています。最新の数字を入力してください。</div>` : ""}`
    : `<p class="small muted">データなし。週末ごとに公表される信用残を入力すると、信用倍率と推移を表示します。</p>`;
  const rows = [...list].reverse().slice(0, 12)
    .map((e) => `<tr><td>${shortDate(e.d)}週</td><td class="num">${shares(e.buy)}</td><td class="num">${shares(e.sell)}</td><td class="num">${e.sell > 0 ? number(e.buy / e.sell, 2) : "—"}</td><td><button type="button" class="link" data-sd="del-stock" data-d="${e.d}">削除</button></td></tr>`)
    .join("");
  return `<section class="card" id="sd-stock" data-market="${market}" data-code="${esc(stock.code)}">
    <h2>需給（信用残・手入力）</h2>
    ${summary}
    ${list.length >= 2 ? lineChart("信用残の推移（株）", list.map((e) => e.d), [
      { values: list.map((e) => e.buy), cls: "s1", label: "買い残" },
      { values: list.map((e) => e.sell), cls: "s3", label: "売り残" },
    ], { min: 0 }) : ""}
    <details><summary class="small">入力する・記録を見る</summary>
      <form class="form" data-sd-form="stock">
        <div class="grid2">
          <div><label>週末の日付（申込み日）</label><input type="date" name="d" value="${lastFriday()}"></div>
          <div><label>信用買い残（株）</label><input type="number" name="buy" step="1" min="0" inputmode="numeric"></div>
          <div><label>信用売り残（株）</label><input type="number" name="sell" step="1" min="0" inputmode="numeric"></div>
        </div>
        <div class="actions"><button type="submit">保存</button></div>
      </form>
      ${rows ? `<table class="bt"><tr><th>週</th><th>買い残</th><th>売り残</th><th>倍率</th><th></th></tr>${rows}</table>` : ""}
      <p class="small muted">基準（仮置き）: 信用倍率${s.ratio_low}倍以下、または売り残が平均出来高の${s.sell_days_high}日分以上で「買い戻しが入りやすい」。買い残が平均出来高の${s.buy_days_high}日分以上（出来高が分からなければ信用倍率${s.ratio_high}倍以上）で、${s.rising_weeks}週続けて増えていたら「戻り売りが出やすい」。候補の判定には使っていません。</p>
      ${SOURCE}
    </details>
    ${NOTE}
  </section>`;
}

// ------------------------------------------------------------ 操作

export function initSupply(app, rerender, getJSON) {
  const num = (form, name) => {
    const raw = String(new FormData(form).get(name) ?? "").trim();
    return raw === "" ? null : Number(raw);
  };
  app.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-sd-form]");
    if (!form) return;
    event.preventDefault();
    const kind = form.dataset.sdForm;
    const d = String(new FormData(form).get("d") || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return alert("日付を入力してください。");
    if (kind === "short") {
      const v = num(form, "v");
      if (!(v >= 0 && v <= 100)) return alert("空売り比率は0〜100の%で入力してください。");
      const m = loadMarket();
      store.set(MARKET_KEY, { ...m, short: upsert(m.short, { d, v }) });
    } else if (kind === "flow") {
      const entry = { d, foreign: num(form, "foreign"), individual: num(form, "individual"), trust: num(form, "trust") };
      if ([entry.foreign, entry.individual, entry.trust].every((v) => v == null)) return alert("少なくとも1つの金額を入力してください。");
      if ([entry.foreign, entry.individual, entry.trust].some((v) => v != null && !Number.isFinite(v))) return alert("金額は数字で入力してください。");
      const m = loadMarket();
      store.set(MARKET_KEY, { ...m, flows: upsert(m.flows, entry) });
    } else if (kind === "stock") {
      const box = form.closest("#sd-stock");
      const buy = num(form, "buy"), sell = num(form, "sell");
      if (!(buy >= 0) || !(sell >= 0)) return alert("買い残と売り残を0以上の数で入力してください。");
      const { market, code } = box.dataset;
      // 「平均出来高の何日分か」を出すため、その週の25日平均出来高も一緒に保存する（株価データは公開データ）
      const chart = await getJSON(`data/${market}/${encodeURIComponent(code)}.json`)
        .catch(() => getJSON(`data/${market}/m/${encodeURIComponent(code)}.json`)).catch(() => null);
      const vol = avgVolume(chart, d);
      store.set(stockKey(market, code), upsert(loadStock(market, code), { d, buy, sell, ...(vol ? { vol: Math.round(vol) } : {}) }));
    }
    const y = window.scrollY;
    await rerender();
    window.scrollTo(0, y);
  });
  app.addEventListener("click", async (event) => {
    const el = event.target.closest("[data-sd^='del-']");
    if (!el) return;
    if (!confirm("この記録を削除します。よろしいですか？")) return;
    const d = el.dataset.d;
    if (el.dataset.sd === "del-stock") {
      const { market, code } = el.closest("#sd-stock").dataset;
      store.set(stockKey(market, code), removeDate(loadStock(market, code), d));
    } else {
      const m = loadMarket();
      const key = el.dataset.sd === "del-short" ? "short" : "flows";
      store.set(MARKET_KEY, { ...m, [key]: removeDate(m[key], d) });
    }
    const y = window.scrollY;
    await rerender();
    window.scrollTo(0, y);
  });
}

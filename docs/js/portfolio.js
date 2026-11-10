// 「保有・記録」の画面。ポジション登録、出口ルールの表示、決済、年初来損益、エクスポート／インポート。
import { store, exportAll, importAll } from "./store.js";
import { esc, price, number, pct, signClass, shortDate, todayISO } from "./format.js";
import { LABEL } from "./labels.js";
import { REASON_KEYS, reasonLabel, exitPlan, findDropReference, validatePosition } from "./exits.js";
import { pnl, ytd } from "./ledger.js";
import { earningsInfo } from "./earnings.js";

const KEY = "positions";
export const loadPositions = () => store.get(KEY, []);
const savePositions = (list) => store.set(KEY, list);
const SELL_REASONS = ["利確（ルールどおり）", "損切り（ルールどおり）", "悪材料が出たため", "決算をまたがないため", "ルール外（理由のすり替え）"];

let ctx = null; // { markets: { jp, us }, fx }

const yen = (value) => (value == null ? "—" : `${value < 0 ? "−" : value > 0 ? "+" : ""}${Math.abs(Math.round(value)).toLocaleString("ja-JP")}円`);
const money = (value, market) => (market === "us" ? `${value < 0 ? "−" : value > 0 ? "+" : ""}$${number(Math.abs(value), 2)}` : yen(value));
const num = (id) => {
  const raw = document.getElementById(id)?.value ?? "";
  return raw === "" ? NaN : Number(raw);
};
const val = (id) => document.getElementById(id)?.value ?? "";

const PRINCIPLES = `
  <ul class="plain">
    <li><strong>買う理由と売る理由は、必ず同じ種類にする。</strong>途中ですり替えない（例: 急落の反発狙いで買ったのに、下がったら「長期保有」に変える、は禁止）。</li>
    <li>悪材料（不祥事・下方修正）が出たら、チャートに関係なく売る。</li>
    <li>決算はまたがない。</li>
    <li>迷ったら入らない。入るなら小ロット。</li>
  </ul>`;

// ------------------------------------------------------------ 資金管理

function moneyHTML(positions) {
  const year = todayISO().slice(0, 4);
  const cfg = ctx.markets.jp.config;
  const fx = ctx.fx;
  const r = ytd(positions, year, fx?.usdjpy ?? null, cfg.money.warn_remaining_pct);
  const banner = {
    none: `<div class="alert info">今年の決済はまだありません。</div>`,
    ok: `<div class="alert info">年初来の確定損益はプラスです。</div>`,
    warn: `<div class="alert warn">利益が減っています<small>年初来の最高 ${yen(r.peakJpy)} から ${yen(r.totalJpy)} まで減りました（最高額の${cfg.money.warn_remaining_pct}%以下）。ゼロになったら撤退です。</small></div>`,
    retreat: `<div class="alert danger">撤退ルールに該当<small>年初来の確定損益がゼロ以下です。ルールでは、利益がゼロになったら撤退です。</small></div>`,
    unknown: `<div class="alert info">為替レートを取得できないため、円換算の合計を出せません。</div>`,
  }[r.status];
  return `<section class="card">
    <h2>資金管理（${year}年の確定損益）</h2>
    ${banner}
    <table class="kv">
      <tr><td>日本株</td><td class="num ${signClass(r.jp)}">${yen(r.jp)}</td></tr>
      <tr><td>米国株</td><td class="num ${signClass(r.us)}">${money(r.us, "us")}</td></tr>
      <tr><td><strong>合計（円換算）</strong><br><span class="small muted">${
        fx ? `1ドル = ${number(fx.usdjpy, 2)}円（${shortDate(fx.date)}）で換算` : "為替レートなし"
      }</span></td><td class="num ${signClass(r.totalJpy ?? 0)}"><strong>${yen(r.totalJpy)}</strong></td></tr>
    </table>
    <p class="small muted">決済 ${r.count} 件。円換算は決済時ではなく現在のレートを使うため、実際の損益とは少しずれます。税金は含みません。</p>
  </section>`;
}

// ------------------------------------------------------------ 保有中

function positionAlerts(pos, d, stock, plan) {
  const out = [];
  if (pos.badNews) out.push(["danger", "悪材料あり：チャートに関係なく売る"]);
  if (!stock) return out;
  if (stock.warnings.includes("two_black")) out.push(["danger", "最優先で損切り：下放れ二本黒"]);
  if (plan.stop.hit) out.push(["danger", `損切りの条件に到達：${plan.stop.text}`]);
  if (plan.take.hit) out.push(["entry", `利確の条件に到達：${plan.take.text}`]);
  const earn = earningsInfo(d.market, stock);
  if (earn.soon) out.push(["warn", `決算はまたがない：決算発表は ${shortDate(earn.next)} の予定`]);
  if (stock.trend.exit_warning) out.push(["warn", "手仕舞い警戒（トレンド継続モード）"]);
  const warns = stock.warnings.filter((k) => k !== "two_black").map((k) => LABEL[k]);
  if (warns.length) out.push(["warn", `警戒サイン：${warns.join("・")}`]);
  return out;
}

function exitRow(title, item, market) {
  const level = item.level != null ? `（目安 ${price(item.level, market)}）` : "";
  const state = item.manual ? `<span class="muted">自分で判断</span>` : item.hit == null ? `<span class="muted">判定できません</span>` : item.hit ? `<span class="state on">● 到達</span>` : `<span class="muted">未到達</span>`;
  return `<tr><td><span class="small muted">${title}</span><br>${esc(item.text)}${level}</td><td>${state}</td></tr>`;
}

function openCardHTML(pos) {
  const d = ctx.markets[pos.market];
  const stock = d.stocks.find((s) => s.code === pos.code);
  const plan = exitPlan(pos, stock, d.config, todayISO());
  const gain = stock ? (stock.close / pos.buyPrice - 1) * 100 : null;
  const amount = stock ? (stock.close - pos.buyPrice) * pos.qty : null;
  const alerts = positionAlerts(pos, d, stock, plan)
    .map(([level, text]) => `<div class="alert ${level}">${esc(text)}</div>`)
    .join("");
  return `<section class="card" data-pos="${esc(pos.id)}">
    <div class="detail-head">
      <div><div class="small muted">${esc(pos.code)}　${d.label}</div>
        <h2><a href="#${pos.market}/${encodeURIComponent(pos.code)}">${esc(pos.name)}</a></h2></div>
      <div class="num" style="text-align:right">${
        stock
          ? `<div><strong>${price(stock.close, pos.market)}</strong></div>
             <div class="${signClass(gain)}">${pct(gain)}（${money(amount, pos.market)}）</div>`
          : `<div class="muted small">対象銘柄から外れたため現在値なし</div>`
      }</div>
    </div>
    <p class="small">買い: ${shortDate(pos.buyDate)}　${price(pos.buyPrice, pos.market)} × ${number(pos.qty, 0)}株<br>
      買った理由: <strong>${esc(reasonLabel(pos.reason, d.config, pos.aim))}</strong></p>
    ${alerts}
    <table class="kv exit">${exitRow("利確", plan.take, pos.market)}${exitRow("損切り", plan.stop, pos.market)}</table>
    <label class="check"><input type="checkbox" data-pf="bad-news" ${pos.badNews ? "checked" : ""}>
      <span>悪材料（不祥事・下方修正）が出た<br><span class="small muted">チェックすると「チャートに関係なく売る」を表示します。</span></span></label>
    <details><summary class="small">理由メモを見る</summary>
      <p class="small"><span class="muted">なぜこの銘柄か</span><br>${esc(pos.memo.why)}</p>
      <p class="small"><span class="muted">根拠は何か</span><br>${esc(pos.memo.basis)}</p>
      <p class="small"><span class="muted">何が起きたら負けか</span><br>${esc(pos.memo.lose)}</p>
    </details>
    <div class="actions">
      <button type="button" data-pf="toggle-close">決済を記録する</button>
      <button type="button" data-pf="delete">削除</button>
    </div>
    <form class="form" data-pf-form="close" hidden>
      <div class="grid2">
        <div><label>売った日</label><input type="date" name="date" value="${todayISO()}" required></div>
        <div><label>売値</label><input type="number" name="price" step="any" inputmode="decimal" value="${stock ? stock.close : ""}" required></div>
        <div><label>手数料（合計・任意）</label><input type="number" name="fee" step="any" inputmode="decimal" placeholder="0"></div>
        <div><label>売った理由</label><select name="reason">${SELL_REASONS.map((r) => `<option>${r}</option>`).join("")}</select></div>
      </div>
      <label>ひとこと（任意）</label><input type="text" name="note" placeholder="次に活かすこと">
      <p class="small muted">買った理由は「${esc(reasonLabel(pos.reason, d.config, pos.aim))}」でした。売る理由も同じ種類ですか？</p>
      <div class="actions"><button type="submit" class="primary">決済を保存</button></div>
    </form>
  </section>`;
}

// ------------------------------------------------------------ 決済済み

function closedHTML(closed) {
  if (!closed.length) return `<p class="muted small">決済済みの記録はありません。</p>`;
  const rows = [...closed]
    .sort((a, b) => (a.sell.date < b.sell.date ? 1 : -1))
    .map((p) => {
      const d = ctx.markets[p.market];
      const value = pnl(p);
      const off = p.sell.reason.startsWith("ルール外");
      return `<details class="closed" data-pos="${esc(p.id)}">
        <summary><span>${shortDate(p.sell.date)}　${esc(p.name)}${off ? `　<span class="badge warn">ルール外</span>` : ""}</span>
          <span class="num ${signClass(value)}">${money(value, p.market)}</span></summary>
        <p class="small">${shortDate(p.buyDate)} ${price(p.buyPrice, p.market)} → ${shortDate(p.sell.date)} ${price(p.sell.price, p.market)}　× ${number(p.qty, 0)}株
          （${pct((p.sell.price / p.buyPrice - 1) * 100)}）<br>
          買った理由: ${esc(reasonLabel(p.reason, d.config, p.aim))}<br>売った理由: ${esc(p.sell.reason)}${p.sell.note ? `<br>ひとこと: ${esc(p.sell.note)}` : ""}</p>
        <p class="small"><span class="muted">なぜこの銘柄か</span> ${esc(p.memo.why)}<br><span class="muted">根拠</span> ${esc(p.memo.basis)}<br><span class="muted">負けの条件</span> ${esc(p.memo.lose)}</p>
        <div class="actions"><button type="button" data-pf="delete">この記録を削除</button></div>
      </details>`;
    });
  return rows.join("");
}

// ------------------------------------------------------------ 画面

export function renderPortfolio(app, context) {
  ctx = context;
  const positions = loadPositions();
  const open = positions.filter((p) => !p.sell);
  const closed = positions.filter((p) => p.sell);
  app.innerHTML = `
    ${moneyHTML(positions)}
    <section class="card small"><h2>守るルール</h2>${PRINCIPLES}</section>
    <h3>保有中（${open.length}）</h3>
    ${open.length ? open.map(openCardHTML).join("") : `<p class="muted small pad">保有中のポジションはありません。銘柄の詳細画面の「ポジションを登録」から追加できます。</p>`}
    <h3>決済済み（${closed.length}）</h3>
    <section class="card">${closedHTML(closed)}</section>
    <section class="card">
      <h2>データの保存と復元</h2>
      <p class="small muted">記録はこの端末のこのブラウザの中にだけ保存されます。ブラウザのデータを消すと記録も消えるので、ときどきエクスポートして保管してください。機種変更のときもこれで移せます。</p>
      <div class="actions">
        <button type="button" data-pf="export">エクスポート（ファイルに保存）</button>
        <label class="btn">インポート（ファイルから復元）<input type="file" accept="application/json,.json" data-pf="import" hidden></label>
      </div>
    </section>`;
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------ 登録フォーム

function suggestTarget(d, chart, buyDate) {
  return chart && buyDate ? findDropReference(chart, buyDate, d.config, d.decimals) : null;
}

function updateReasonFields(d, chart) {
  const reason = val("pf-reason");
  for (const el of document.querySelectorAll("[data-for]")) el.hidden = el.dataset.for !== reason;
  if (reason === "c1") {
    const found = suggestTarget(d, chart, val("pf-date"));
    const input = document.getElementById("pf-target");
    const hint = document.getElementById("pf-target-hint");
    if (found) {
      if (!input.dataset.edited) input.value = found.target;
      hint.textContent = `${shortDate(found.dropDate)} の急落を検出。前日の終値 ${price(found.refClose, d.market)} の ${d.config.buy.drop_pct}% の水準を入れています。`;
    } else {
      if (!input.dataset.edited) input.value = "";
      hint.textContent = `直近${d.config.exit.drop_lookback_days}営業日に急落が見つかりません。「急落前日の終値 ×（1 ${d.config.buy.drop_pct}%）」を自分で計算して入力してください。`;
    }
  }
}

export function renderNewPosition(app, context, market, code, chart) {
  ctx = context;
  const d = ctx.markets[market];
  const s = d.stocks.find((x) => x.code === code);
  if (!s) {
    app.innerHTML = `<p class="pad">銘柄が見つかりません。<a href="#portfolio">戻る</a></p>`;
    return;
  }
  const options = REASON_KEYS.map((k) => `<option value="${k}">${esc(reasonLabel(k, d.config))}</option>`).join("");
  app.innerHTML = `
    <a class="btn back" href="#${market}/${encodeURIComponent(code)}">← 銘柄へ戻る</a>
    <section class="card">
      <div class="small muted">${esc(s.code)}　${d.label}</div>
      <h2>${esc(s.name)} のポジションを登録</h2>
      <div class="alert info">迷ったら入らない。入るなら小ロット。</div>
      <form class="form" id="pf-new" data-market="${market}" data-code="${esc(code)}" novalidate>
        <div class="grid2">
          <div><label for="pf-date">買った日</label><input type="date" id="pf-date" value="${todayISO()}"></div>
          <div><label for="pf-price">買値</label><input type="number" id="pf-price" step="any" inputmode="decimal" value="${s.close ?? ""}"></div>
          <div><label for="pf-qty">株数</label><input type="number" id="pf-qty" step="any" inputmode="decimal" placeholder="例: 100"></div>
        </div>

        <label for="pf-reason">買った理由（あとから変更できません）</label>
        <select id="pf-reason"><option value="">選んでください</option>${options}</select>
        <p class="small muted">買う理由と売る理由は、必ず同じ種類にします。ここで選んだ理由に合わせて、利確と損切りの条件が決まります。</p>

        <div data-for="c1" hidden>
          <label for="pf-target">利確の水準（この値段まで戻したら利確）</label>
          <input type="number" id="pf-target" step="any" inputmode="decimal">
          <p class="small muted" id="pf-target-hint"></p>
          <p class="small">損切り: シナリオが崩れたとき（下のメモ「何が起きたら負けか」）</p>
        </div>
        <div data-for="c2" hidden>
          <p class="small">利確: ${d.config.ma.mid}日線まで戻したとき（現在 ${price(s.levels.ma_mid, market)}。日々動きます）<br>
            損切り: シナリオが崩れたとき（下のメモ「何が起きたら負けか」）</p>
        </div>
        <div data-for="c3" hidden>
          <label for="pf-aim">どちらを狙って買いましたか</label>
          <select id="pf-aim"><option value="">選んでください</option><option value="2">−2σ 狙い</option><option value="3">−3σ 狙い</option></select>
          <p class="small">利確: ボリンジャーバンドの中央線まで戻したとき（現在 ${price(s.levels.bb_mid, market)}）<br>
            損切り: −2σ狙いの場合は、−3σ（現在 ${price(s.levels.bb_l3, market)}）を終値で下に抜けたとき。−3σ狙いの場合は、シナリオが崩れたとき</p>
        </div>
        <div data-for="theme" hidden>
          <label for="pf-deadline">手仕舞いの期限（自分で決める）</label>
          <input type="date" id="pf-deadline">
          <p class="small">利確: 期限が来たとき<br>損切り: 買った根拠が崩れたとき</p>
        </div>

        <h3>理由メモ（3つとも必須）</h3>
        <label for="pf-why">なぜこの銘柄か</label><textarea id="pf-why" rows="2"></textarea>
        <label for="pf-basis">根拠は何か</label><textarea id="pf-basis" rows="2"></textarea>
        <label for="pf-lose">何が起きたら負けか</label><textarea id="pf-lose" rows="2"></textarea>

        <div id="pf-errors"></div>
        <div class="actions"><button type="submit" class="primary">登録する</button></div>
      </form>
    </section>`;
  window.scrollTo(0, 0);
  const form = document.getElementById("pf-new");
  form.addEventListener("input", (event) => {
    if (event.target.id === "pf-target") event.target.dataset.edited = "1";
    if (event.target.id === "pf-date" || event.target.id === "pf-reason") updateReasonFields(d, chart);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const reason = val("pf-reason");
    const pos = {
      id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
      market, code, name: s.name,
      buyDate: val("pf-date"), buyPrice: num("pf-price"), qty: num("pf-qty"), reason,
      memo: { why: val("pf-why").trim(), basis: val("pf-basis").trim(), lose: val("pf-lose").trim() },
      badNews: false, createdAt: new Date().toISOString(),
    };
    if (reason === "c1") pos.target = num("pf-target");
    if (reason === "c3") pos.aim = val("pf-aim");
    if (reason === "theme") pos.deadline = val("pf-deadline");
    const errors = validatePosition(pos);
    if (errors.length) {
      document.getElementById("pf-errors").innerHTML = `<div class="alert danger">${errors.map(esc).join("<br>")}</div>`;
      return;
    }
    savePositions([...loadPositions(), pos]);
    location.hash = "#portfolio";
  });
}

// ------------------------------------------------------------ 操作

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function initPortfolio(app, rerender) {
  const idOf = (el) => el.closest("[data-pos]")?.dataset.pos;
  const update = (id, change) => savePositions(loadPositions().map((p) => (p.id === id ? change(p) : p)));

  app.addEventListener("click", (event) => {
    const el = event.target.closest("[data-pf]");
    if (!el) return;
    const action = el.dataset.pf;
    if (action === "toggle-close") {
      const form = el.closest("[data-pos]").querySelector("[data-pf-form='close']");
      form.hidden = !form.hidden;
    } else if (action === "delete") {
      if (!confirm("この記録を削除します。元に戻せません。よろしいですか？")) return;
      const id = idOf(el);
      savePositions(loadPositions().filter((p) => p.id !== id));
      rerender();
    } else if (action === "export") {
      download(`stock-screener-${todayISO()}.json`, JSON.stringify(exportAll(), null, 2));
    }
  });

  app.addEventListener("change", async (event) => {
    const el = event.target;
    if (el.dataset.pf === "bad-news") {
      update(idOf(el), (p) => ({ ...p, badNews: el.checked }));
      rerender();
    } else if (el.dataset.pf === "import" && el.files[0]) {
      try {
        const payload = JSON.parse(await el.files[0].text());
        const count = (payload?.data?.positions ?? []).length;
        if (!confirm(`今の記録をすべて消して、ファイルの内容（ポジション・記録 ${count} 件）に置き換えます。よろしいですか？`)) return;
        importAll(payload);
        rerender();
      } catch (err) {
        alert(`インポートできませんでした。${err.message}`);
      } finally {
        el.value = "";
      }
    }
  });

  app.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-pf-form='close']");
    if (!form) return;
    event.preventDefault();
    const data = new FormData(form);
    const sellPrice = Number(data.get("price")), fee = Number(data.get("fee") || 0);
    if (!data.get("date") || !(sellPrice > 0) || !(fee >= 0)) {
      alert("売った日と売値を正しく入力してください。");
      return;
    }
    update(idOf(form), (p) => ({
      ...p,
      sell: { date: data.get("date"), price: sellPrice, fee, reason: data.get("reason"), note: String(data.get("note") || "").trim() },
    }));
    rerender();
  });
}

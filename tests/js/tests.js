// 画面側の計算（出口ルール・損益集計・決算警告）のテスト。
// 実行: python -m pytest tests/test_js.py （ブラウザで tests/js/index.html を開いても結果が見られる）
import { exitPlan, findDropReference, validatePosition, reasonLabel, REASONS_BY_KIND } from "../../docs/js/exits.js";
import { pnl, ytd } from "../../docs/js/ledger.js";
import { earningsStatus } from "../../docs/js/earnings.js";
import { store, exportAll, importAll } from "../../docs/js/store.js";

const results = { passed: 0, failed: [] };
function test(name, fn) {
  try { fn(); results.passed++; } catch (err) { results.failed.push(`${name}: ${err.message}`); }
}
function eq(actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a !== e) throw new Error(`期待 ${e} / 実際 ${a}`);
}

const cfg = {
  buy: { drop_pct: -2.5, bb_period: 20 },
  ma: { short: 5, mid: 25, long: 100 },
  exit: { drop_lookback_days: 10 },
  momentum: { exit: { stop_warn_pct: -7, stop_loss_pct: -8, ma_break_volume_ratio: 1.5 } },
};
const stock = (close, levels = {}) => ({ close, levels: { ma_mid: 110, bb_mid: 108, bb_l2: 96, bb_l3: 92, ...levels } });

// ---- 条件1の利確水準 ----
const chart = {
  t: ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
  c: [1000, 1005, 940, 950, 955],
};
test("急落日を見つけ、前日終値の−2.5%を利確水準にする", () => {
  eq(findDropReference(chart, "2026-11-05", cfg, 1), { dropDate: "2026-11-04", refClose: 1005, target: 979.9 });
});
test("急落日に買った場合も同じ水準になる", () => {
  eq(findDropReference(chart, "2026-11-04", cfg, 1).target, 979.9);
});
test("買った日より後の急落は使わない", () => {
  eq(findDropReference(chart, "2026-11-03", cfg, 1), null);
});
test("データの最終日より後に買った場合は、最終日からさかのぼる", () => {
  eq(findDropReference(chart, "2026-11-10", cfg, 1).dropDate, "2026-11-04");
});
test("さかのぼる日数を過ぎた急落は使わない", () => {
  eq(findDropReference(chart, "2026-11-06", { ...cfg, exit: { drop_lookback_days: 2 } }, 1), null);
});
test("ちょうど−2.5%は急落とみなす", () => {
  eq(findDropReference({ t: ["a", "b"], c: [100, 97.5] }, "b", cfg, 2).target, 97.5);
});
test("急落がなければ null", () => {
  eq(findDropReference({ t: ["a", "b", "c"], c: [100, 99, 98] }, "c", cfg, 1), null);
});

// ---- 出口ルール ----
test("条件1: 利確水準に届いたら到達、損切りは自分で判断", () => {
  const pos = { reason: "c1", target: 980 };
  eq(exitPlan(pos, stock(985), cfg, "2026-11-10").take.hit, true);
  eq(exitPlan(pos, stock(979), cfg, "2026-11-10").take.hit, false);
  eq(exitPlan(pos, stock(979), cfg, "2026-11-10").take.level, 980);
  eq(exitPlan(pos, stock(979), cfg, "2026-11-10").stop.manual, true);
});
test("条件2: 25日線まで戻したら利確", () => {
  const plan = exitPlan({ reason: "c2" }, stock(110), cfg, "2026-11-10");
  eq([plan.take.level, plan.take.hit], [110, true]);
  eq(exitPlan({ reason: "c2" }, stock(109.9), cfg, "2026-11-10").take.hit, false);
});
test("条件3: 中央線まで戻したら利確", () => {
  const plan = exitPlan({ reason: "c3", aim: "3" }, stock(108), cfg, "2026-11-10");
  eq([plan.take.level, plan.take.hit], [108, true]);
});
test("条件3（−2σ狙い）: −3σを終値で下抜けたら損切り", () => {
  eq(exitPlan({ reason: "c3", aim: "2" }, stock(91.9), cfg, "2026-11-10").stop.hit, true);
  eq(exitPlan({ reason: "c3", aim: "2" }, stock(92), cfg, "2026-11-10").stop.hit, false);
  eq(exitPlan({ reason: "c3", aim: "2" }, stock(92), cfg, "2026-11-10").stop.level, 92);
});
test("条件3（−3σ狙い）: 損切りは自分で判断", () => {
  const plan = exitPlan({ reason: "c3", aim: "3" }, stock(80), cfg, "2026-11-10");
  eq([plan.stop.manual, plan.stop.hit], [true, null]);
});
test("テーマ・業績: 期限が来たら手仕舞い", () => {
  const pos = { reason: "theme", deadline: "2026-12-31" };
  eq(exitPlan(pos, stock(100), cfg, "2026-12-30").take.hit, false);
  eq(exitPlan(pos, stock(100), cfg, "2026-12-31").take.hit, true);
  eq(exitPlan(pos, stock(100), cfg, "2026-12-31").stop.manual, true);
});
test("銘柄データがなくても落ちない", () => {
  eq(exitPlan({ reason: "c2" }, undefined, cfg, "2026-11-10").take.hit, null);
  eq(exitPlan({ reason: "c3", aim: "2" }, undefined, cfg, "2026-11-10").stop.hit, null);
});
test("買った理由の表示名", () => {
  eq(reasonLabel("c1", cfg), "条件1（前日比 -2.5%以下の急落）");
  eq(reasonLabel("c3", cfg, "2"), "条件3（ボリンジャーバンド −2σ狙い）");
});

const valid = {
  buyDate: "2026-11-05", buyPrice: 950, qty: 100, reason: "c2",
  memo: { why: "大型で流動性がある", basis: "25日線から−6%", lose: "悪材料が出たら" },
};

// ---- 順張りの出口 ----
test("順張り: 買値から−8%で損切り、−7%で警告", () => {
  const pos = { reason: "mo", buyPrice: 1000 };
  const at = (close) => exitPlan(pos, { close }, cfg, "2026-11-10").stop;
  eq([at(940).warn, at(940).hit], [false, false]);
  eq([at(930).warn, at(930).hit], [true, false]);   // ちょうど −7%
  eq([at(925).warn, at(925).hit], [true, false]);
  eq([at(920).warn, at(920).hit], [true, true]);    // ちょうど −8%
  eq([at(900).warn, at(900).hit], [true, true]);
  eq([at(920).level, at(920).warnLevel, at(920).manual], [920, 930, false]);
});
test("順張り: 損切りの%は設定から読む", () => {
  const other = { ...cfg, momentum: { exit: { stop_warn_pct: -4, stop_loss_pct: -5 } } };
  const stop = exitPlan({ reason: "mo", buyPrice: 200 }, { close: 191 }, other, "2026-11-10").stop;
  eq([stop.level, stop.warn, stop.hit], [190, true, false]);
});
test("順張り: 利確は自分で判断。銘柄データがなくても落ちない", () => {
  eq(exitPlan({ reason: "mo", buyPrice: 100 }, { close: 150 }, cfg, "2026-11-10").take.manual, true);
  eq(exitPlan({ reason: "mo", buyPrice: 100 }, undefined, cfg, "2026-11-10").stop.hit, null);
});
test("逆張りと順張りで、選べる買った理由を分ける", () => {
  eq(REASONS_BY_KIND.contrarian.includes("mo"), false);
  eq(REASONS_BY_KIND.momentum.includes("mo"), true);
  eq(REASONS_BY_KIND.momentum.some((k) => ["c1", "c2", "c3"].includes(k)), false);
  eq(reasonLabel("mo", cfg), "順張り（ブレイクアウト）");
  eq(validatePosition({ ...valid, reason: "mo" }), []);
});

// ---- 入力チェック ----
test("正しい入力はエラーなし", () => eq(validatePosition(valid), []));
test("理由メモは3つとも必須", () => {
  eq(validatePosition({ ...valid, memo: { why: "a", basis: " ", lose: "" } }).length, 2);
  eq(validatePosition({ ...valid, memo: undefined }).length, 3);
});
test("数値の誤りを見つける", () => {
  eq(validatePosition({ ...valid, buyPrice: 0, qty: NaN }).length, 2);
});
test("理由ごとの必須項目", () => {
  eq(validatePosition({ ...valid, reason: "c1" }).length, 1);
  eq(validatePosition({ ...valid, reason: "c1", target: 980 }), []);
  eq(validatePosition({ ...valid, reason: "c3" }).length, 1);
  eq(validatePosition({ ...valid, reason: "c3", aim: "2" }), []);
  eq(validatePosition({ ...valid, reason: "theme" }).length, 1);
  eq(validatePosition({ ...valid, reason: "theme", deadline: "2027-03-31" }), []);
  eq(validatePosition({ ...valid, reason: "c4" }).length, 1);
});

// ---- 損益の集計 ----
const trade = (market, date, buy, sell, qty = 100, fee = 0) => ({ market, buyPrice: buy, qty, sell: { date, price: sell, fee } });
test("損益 = (売値 − 買値) × 株数 − 手数料", () => {
  eq(pnl(trade("jp", "2026-03-01", 1000, 1100, 100, 500)), 9500);
  eq(pnl(trade("jp", "2026-03-01", 1000, 900, 100)), -10000);
});
test("市場ごとに集計し、合計は円換算する", () => {
  const r = ytd([trade("jp", "2026-02-01", 1000, 1100), trade("us", "2026-03-01", 100, 110, 10)], 2026, 150, 30);
  eq([r.jp, r.us, r.totalJpy, r.count, r.status], [10000, 100, 25000, 2, "ok"]);
});
test("去年の決済と保有中のポジションは含めない", () => {
  const open = { market: "jp", buyPrice: 1000, qty: 100 };
  const r = ytd([trade("jp", "2025-12-30", 1000, 2000), open, trade("jp", "2026-01-05", 1000, 1010)], 2026, 150, 30);
  eq([r.jp, r.count], [1000, 1]);
});
test("決済がなければ none", () => eq(ytd([], 2026, 150, 30).status, "none"));
test("利益が最高額の30%以下に減ったら警告", () => {
  const up = trade("jp", "2026-02-01", 1000, 1100);          // +10,000
  eq(ytd([up, trade("jp", "2026-03-01", 1000, 931)], 2026, 150, 30).status, "ok");    // 残り 3,100
  eq(ytd([up, trade("jp", "2026-03-01", 1000, 930)], 2026, 150, 30).status, "warn");  // 残り 3,000
});
test("利益がゼロ以下になったら撤退", () => {
  const up = trade("jp", "2026-02-01", 1000, 1100);
  eq(ytd([up, trade("jp", "2026-03-01", 1000, 900)], 2026, 150, 30).status, "retreat");
  eq(ytd([trade("jp", "2026-03-01", 1000, 990)], 2026, 150, 30).status, "retreat");
});
test("最高額は決済日の順にたどって求める", () => {
  const r = ytd([trade("jp", "2026-03-01", 1000, 950), trade("jp", "2026-02-01", 1000, 1100)], 2026, 150, 30);
  eq([r.peakJpy, r.totalJpy], [10000, 5000]);
});
test("ドル建ての損益があるのに為替がなければ判定しない", () => {
  const r = ytd([trade("us", "2026-03-01", 100, 110, 10)], 2026, null, 30);
  eq([r.us, r.totalJpy, r.status], [100, null, "unknown"]);
  eq(ytd([trade("jp", "2026-03-01", 1000, 1100)], 2026, null, 30).status, "ok");
});

// ---- 決算の警告 ----
const earn = { next: "2026-11-13", prev_session: "2026-11-12", last: "2026-08-07" };
test("決算の前営業日と当日だけ警告する", () => {
  eq(earningsStatus(earn, "2026-11-11").soon, false);
  eq(earningsStatus(earn, "2026-11-12").soon, true);
  eq(earningsStatus(earn, "2026-11-13").soon, true);
  eq(earningsStatus(earn, "2026-11-14").soon, false);
});
test("次回が未定なら警告しない", () => {
  eq(earningsStatus({ next: null, last: "2026-10-29" }, "2026-11-11").soon, false);
  eq(earningsStatus(undefined, "2026-11-11").soon, false);
});
test("手入力の決算日が優先される", () => {
  eq(earningsStatus(earn, "2026-11-12", "2026-11-20").soon, false);
  eq(earningsStatus(earn, "2026-11-16", "2026-11-20").soon, true);   // 月曜が決算なら金曜から警告
  eq(earningsStatus(earn, "2026-11-21", "2026-11-20").soon, false);  // 過ぎたら警告しない
});

// ---- エクスポート／インポート ----
test("エクスポートしたデータをインポートすると元に戻る", () => {
  store.set("positions", [{ id: "a", code: "7203" }]);
  store.set("thermo:jp", { fg: 15 });
  const saved = JSON.parse(JSON.stringify(exportAll()));
  store.set("positions", []);
  store.set("extra", 1);
  importAll(saved);
  eq(store.get("positions"), [{ id: "a", code: "7203" }]);
  eq(store.get("thermo:jp"), { fg: 15 });
  eq(store.get("extra"), null);
});
test("関係のないファイルはインポートを断り、今のデータを消さない", () => {
  store.set("positions", [{ id: "keep" }]);
  for (const bad of [null, {}, { app: "other", data: {} }, { app: "stock-screener", data: { positions: "x" } }]) {
    let threw = false;
    try { importAll(bad); } catch { threw = true; }
    eq(threw, true);
  }
  eq(store.get("positions"), [{ id: "keep" }]);
});

document.getElementById("out").textContent =
  `合格 ${results.passed} 件 / 失敗 ${results.failed.length} 件\n` + results.failed.join("\n");
window.__results = results;

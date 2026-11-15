// 画面側の計算（出口ルール・損益集計・決算警告・資金管理）のテスト。
// 実行: python -m pytest tests/test_js.py （ブラウザで tests/js/index.html を開いても結果が見られる）
import { exitPlan, findDropReference, validatePosition, reasonLabel, REASONS_BY_KIND } from "../../docs/js/exits.js";
import { pnl, ytd } from "../../docs/js/ledger.js";
import { earningsStatus } from "../../docs/js/earnings.js";
import { store, exportAll, importAll } from "../../docs/js/store.js";
import { tradeOf, summarize, groupStats, kindOf, autoViolations, hasViolation, vsIndex, ytdVsIndex, SWITCH_REASON } from "../../docs/js/stats.js";
import { earningsEvents, bannerHTML } from "../../docs/js/calendar.js";
import { upsert, removeDate, avgVolume, marginState, shortRatioState, flowSummary } from "../../docs/js/supply.js";
import { lastFriday } from "../../docs/js/supplyview.js";
import { SETTINGS_KEY, capitalJpy, riskPctOf, stopCandidates, positionSize, portfolioRisk } from "../../docs/js/sizing.js";

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

// ---- フェーズ5A: 株数の計算 ----
const scfg = {
  ...cfg,
  momentum: { ...cfg.momentum, ma: { fast: 50 } },
  sizing: { risk_pct: 1, stop_pct: -7, lot: 100, max_stock_pct: 25, max_sector_pct: 40 },
};
test("資金の合計は円換算。ドルがあるのに為替がなければ null", () => {
  eq(capitalJpy({ jpy: 1000000, usd: 10000 }, 150), 2500000);
  eq(capitalJpy({ jpy: 1000000 }, null), 1000000);
  eq(capitalJpy({ jpy: 1000000, usd: 1 }, null), null);
  eq(capitalJpy(null, 150), 0);
});
test("許容損失は自分の設定、なければ設定ファイルの初期値", () => {
  eq(riskPctOf({ riskPct: 2 }, scfg), 2);
  eq(riskPctOf({}, scfg), 1);
  eq(riskPctOf({ riskPct: 0 }, scfg), 1);
});
test("日本株: 100株単位に切り捨てる", () => {
  // 資金300万円・1% → 3万円。1株あたり 100円 の損失 → 300株
  const r = positionSize({ buyPrice: 1000, stopPrice: 900, capitalJpy: 3000000, riskPct: 1, lot: 100 });
  eq([r.qty, r.cost, r.loss, r.lossPct, r.tooLarge], [300, 300000, 30000, 1, false]);
  // 1株あたり 70円 → 428株 → 400株
  eq(positionSize({ buyPrice: 1000, stopPrice: 930, capitalJpy: 3000000, riskPct: 1, lot: 100 }).qty, 400);
});
test("割り切れる株数が計算誤差で1単位減らない", () => {
  eq(positionSize({ buyPrice: 0.3, stopPrice: 0.2, capitalJpy: 1000, riskPct: 3, lot: 1 }).qty, 300);
});
test("100株でも許容損失を超えるなら「大きすぎる」", () => {
  // 3万円まで。1株あたり 400円 × 100株 = 4万円
  const r = positionSize({ buyPrice: 5000, stopPrice: 4600, capitalJpy: 3000000, riskPct: 1, lot: 100 });
  eq([r.qty, r.tooLarge, r.basisQty, r.lossJpy], [0, true, 100, 40000]);
});
test("ちょうど許容損失と同じなら買える", () => {
  const r = positionSize({ buyPrice: 5000, stopPrice: 4700, capitalJpy: 3000000, riskPct: 1, lot: 100 });
  eq([r.qty, r.tooLarge, r.lossJpy], [100, false, 30000]);
});
test("必要資金が運用資金を超えないように減らす", () => {
  // 損失の面では 3000株 まで買えるが、資金100万円では 1000株 まで
  const r = positionSize({ buyPrice: 1000, stopPrice: 999, capitalJpy: 1000000, riskPct: 3, lot: 100 });
  eq([r.qty, r.cashLimited, r.unaffordable], [1000, true, false]);
  const poor = positionSize({ buyPrice: 50000, stopPrice: 49999, capitalJpy: 1000000, riskPct: 1, lot: 100 });
  eq([poor.qty, poor.unaffordable, poor.tooLarge], [0, true, false]);
});
test("米国株: 1株単位で、円換算も出す", () => {
  // 資金300万円・1% → 3万円 = 200ドル。1株あたり 8ドル → 25株
  const r = positionSize({ buyPrice: 100, stopPrice: 92, capitalJpy: 3000000, riskPct: 1, fx: 150, lot: 1 });
  eq([r.qty, r.cost, r.costJpy, r.loss, r.lossJpy, r.lossPct], [25, 2500, 375000, 200, 30000, 1]);
});
test("入力の誤りは計算せずに理由を返す", () => {
  const base = { buyPrice: 1000, stopPrice: 900, capitalJpy: 3000000, riskPct: 1, lot: 100 };
  eq(Boolean(positionSize({ ...base, stopPrice: 1000 }).error), true);
  eq(Boolean(positionSize({ ...base, stopPrice: NaN }).error), true);
  eq(Boolean(positionSize({ ...base, capitalJpy: 0 }).error), true);
  eq(Boolean(positionSize({ ...base, fx: null }).error), true);
  eq(positionSize(base).error, undefined);
});

// ---- 損切り価格の候補 ----
test("逆張り: −3σと買値の−7%を候補にする", () => {
  const c = stopCandidates({ kind: "contrarian", reason: "c2", buyPrice: 1000, levels: { bb_l3: 912.34 }, cfg: scfg, digits: 1 });
  eq(c.map((x) => [x.key, x.price]), [["bb3", 912.3], ["pct", 930]]);
});
test("−2σ狙いは、−3σ（損切りルール）を先頭にする", () => {
  const c = stopCandidates({ kind: "contrarian", reason: "c3", aim: "2", buyPrice: 1000, levels: { bb_l3: 950 }, cfg: scfg, digits: 1 });
  eq(c[0].key, "bb3");
  eq(c[0].label.includes("損切りルール"), true);
});
test("買値より高い候補は出さない", () => {
  const c = stopCandidates({ kind: "contrarian", reason: "c2", buyPrice: 1000, levels: { bb_l3: 1010 }, cfg: scfg, digits: 1 });
  eq(c.map((x) => x.key), ["pct"]);
});
test("順張り: 損切りルール（−8%）と50日線", () => {
  const c = stopCandidates({ kind: "momentum", buyPrice: 200, levels: { ma_fast: 190.123 }, cfg: scfg, digits: 2 });
  eq(c.map((x) => [x.key, x.price]), [["mo", 184], ["ma_fast", 190.12]]);
});
test("買値がなければ候補なし", () => {
  eq(stopCandidates({ kind: "contrarian", buyPrice: NaN, cfg: scfg }), []);
});
test("損切り価格は、入力があるときだけ確かめる", () => {
  eq(validatePosition(valid), []);
  eq(validatePosition({ ...valid, stop: 900 }), []);
  eq(validatePosition({ ...valid, stop: NaN }).length, 1);
  eq(validatePosition({ ...valid, stop: 950 }).length, 1);
});

// ---- 全体リスク ----
const holding = (code, market, buyPrice, qty, extra = {}) => ({ code, name: code, market, buyPrice, qty, ...extra });
const infoOf = (table) => (pos) => table[pos.code] ?? {};
test("全部が損切りになった場合の合計損失（円換算）", () => {
  const open = [holding("A", "jp", 1000, 100, { stop: 900 }), holding("B", "us", 100, 10, { stop: 90 })];
  const r = portfolioRisk(open, { capitalJpy: 1000000, usdjpy: 150, cfg: scfg, info: infoOf({}) });
  eq([r.totalLossJpy, r.lossPct, r.totalValueJpy], [25000, 2.5, 250000]);
});
test("損切り価格が未設定のものは合計に含めず、件数を知らせる", () => {
  const open = [holding("A", "jp", 1000, 100, { stop: 900 }), holding("B", "jp", 1000, 100)];
  const r = portfolioRisk(open, { capitalJpy: 1000000, usdjpy: 150, cfg: scfg, info: infoOf({}) });
  eq([r.totalLossJpy, r.noStop.length], [10000, 1]);
});
test("配分は現在値で計算し、セクター・テーマ・市場ごとにまとめる", () => {
  const open = [holding("A", "jp", 1000, 100), holding("B", "jp", 1000, 100), holding("C", "us", 10, 100)];
  const info = infoOf({
    A: { price: 1500, sector: "電気機器", themes: ["半導体"] },
    B: { price: 500, sector: "電気機器", themes: [] },
    C: { price: 10, sector: "Energy", themes: ["半導体", "AI"] },
  });
  const r = portfolioRisk(open, { capitalJpy: 1000000, usdjpy: 150, cfg: scfg, info });
  eq(r.bySector.map((g) => [g.name, g.valueJpy, g.pct]), [["電気機器", 200000, 20], ["Energy", 150000, 15]]);
  eq(r.byTheme.map((g) => [g.name, g.valueJpy]), [["半導体", 300000], ["AI", 150000], ["テーマなし", 50000]]);
  eq(r.byMarket.map((g) => g.name), ["日本株（円）", "米国株（ドル）"]);
});
test("1銘柄・1セクターへの集中を警告する（基準を超えたとき）", () => {
  const info = infoOf({ A: { sector: "銀行業" }, B: { sector: "銀行業" } });
  const at = (qtyA, qtyB) =>
    portfolioRisk([holding("A", "jp", 1000, qtyA), holding("B", "jp", 1000, qtyB)], { capitalJpy: 1000000, usdjpy: 150, cfg: scfg, info }).warnings.map((w) => w.type);
  eq(at(250, 150), []);                  // 25% ちょうど・セクター40% ちょうど
  eq(at(260, 100), ["stock"]);           // 26%
  eq(at(200, 210), ["sector"]);          // セクター 41%
});
test("資金が未設定なら、保有額の合計に対する割合", () => {
  const r = portfolioRisk([holding("A", "jp", 1000, 100), holding("B", "jp", 1000, 300)], { capitalJpy: 0, usdjpy: 150, cfg: scfg, info: infoOf({}) });
  eq([r.base, r.byStock[0].pct, r.lossPct], ["holdings", 75, null]);
});
test("信用建玉の合計が現金（資金 − 現物の買付額）を超えたら警告", () => {
  const info = infoOf({});
  const run = (marginQty) =>
    portfolioRisk([holding("A", "jp", 1000, 600), holding("B", "jp", 1000, marginQty, { margin: true })], { capitalJpy: 1000000, usdjpy: 150, cfg: scfg, info }).margin;
  eq(run(400), { count: 1, marginJpy: 400000, cashJpy: 400000, over: false });
  eq(run(500).over, true);
});
test("為替がなければ米国株を集計から外す", () => {
  const r = portfolioRisk([holding("A", "us", 100, 10, { stop: 90 })], { capitalJpy: 1000000, usdjpy: null, cfg: scfg, info: infoOf({}) });
  eq([r.count, r.noFx.length, r.totalLossJpy], [0, 1, 0]);
});
test("資金設定もエクスポート／インポートの対象になる", () => {
  store.set(SETTINGS_KEY, { jpy: 3000000, usd: 10000, riskPct: 1 });
  const saved = JSON.parse(JSON.stringify(exportAll()));
  store.remove(SETTINGS_KEY);
  importAll(saved);
  eq(store.get(SETTINGS_KEY), { jpy: 3000000, usd: 10000, riskPct: 1 });
  store.remove(SETTINGS_KEY);
});

// ---- フェーズ5B: 売買成績 ----
const closedPos = (buyDate, buyPrice, sellDate, sellPrice, extra = {}) => ({
  market: "jp", code: "X", name: "X", reason: "c2", qty: 100, buyDate, buyPrice, memo: { why: "a", basis: "b", lose: "c" },
  ...extra, sell: { date: sellDate, price: sellPrice, fee: 0, reason: "利確（ルールどおり）", ...(extra.sell || {}) },
});
test("1回分: 損益・保有日数・R倍数", () => {
  const t = tradeOf(closedPos("2026-03-01", 1000, "2026-03-11", 1150, { stop0: 950, stop: 980, sell: { fee: 500 } }), 150);
  eq([t.pnl, t.pnlJpy, t.days, t.r], [14500, 14500, 10, 3]); // R は登録時の損切り幅 50円 で計算
  eq(tradeOf(closedPos("2026-03-01", 1000, "2026-03-02", 900), 150).r, null);
  eq(tradeOf(closedPos("2026-03-01", 1000, "2026-03-02", 900, { stop: 950 }), 150).r, -2); // 古い記録は今の損切り価格
});
test("米国株は円換算。為替がなければ金額の集計から外す", () => {
  const p = closedPos("2026-03-01", 100, "2026-03-02", 110, { market: "us", qty: 10 });
  eq(tradeOf(p, 150).pnlJpy, 15000);
  eq(tradeOf(p, null).pnlJpy, null);
  eq(summarize([tradeOf(p, null)], 10).unconverted, 1);
});
test("勝率・平均利益・平均損失・損益比・期待値", () => {
  const trades = [
    closedPos("2026-01-05", 1000, "2026-01-10", 1100), // +10,000
    closedPos("2026-01-05", 1000, "2026-01-12", 1300), // +30,000
    closedPos("2026-01-05", 1000, "2026-01-14", 900),  // −10,000
    closedPos("2026-01-05", 1000, "2026-01-16", 1000), // 0（勝ちにも負けにも数えない）
  ].map((p) => tradeOf(p, 150));
  const s = summarize(trades, 10);
  eq([s.n, s.win, s.avgWin, s.avgLoss, s.payoff, s.expect, s.totalJpy, s.few], [4, 50, 20000, -10000, 2, 7500, 30000, true]);
});
test("最大連敗は決済日の順に数え、引き分けで途切れる", () => {
  const seq = [["01-10", 900], ["01-05", 900], ["01-20", 900], ["01-15", 1100], ["01-25", 900], ["01-26", 900], ["01-27", 1000]];
  const trades = seq.map(([d, price]) => tradeOf(closedPos("2026-01-01", 1000, `2026-${d}`, price), 150));
  eq(summarize(trades, 10).streak, 3); // 1/5・1/10 で2連敗 → 1/15 勝ち → 1/20・1/25・1/26 で3連敗
  const more = [...trades, tradeOf(closedPos("2026-01-01", 1000, "2026-01-28", 900), 150)];
  eq(summarize(more, 10).streak, 3); // 1/27 の引き分けで途切れるので、1/28 の負けは1連敗目
});
test("件数が基準以上なら参考値の印は付けない", () => {
  const trades = Array.from({ length: 10 }, () => tradeOf(closedPos("2026-01-01", 1000, "2026-01-02", 1010), 150));
  eq(summarize(trades, 10).few, false);
  eq(summarize(trades.slice(1), 10).few, true);
});
test("切り口ごとに分けて集計する", () => {
  const trades = [
    closedPos("2026-01-01", 1000, "2026-01-02", 1100, { reason: "c1" }),
    closedPos("2026-01-01", 1000, "2026-02-02", 900, { reason: "mo", kind: "momentum" }),
    closedPos("2026-01-01", 1000, "2026-02-03", 950, { reason: "c1" }),
  ].map((p) => tradeOf(p, 150));
  eq(groupStats(trades, (t) => t.pos.reason, 10).map((g) => [g.key, g.stats.n]), [["c1", 2], ["mo", 1]]);
  eq(groupStats(trades, (t) => kindOf(t.pos), 10, ["contrarian", "momentum"]).map((g) => g.key), ["contrarian", "momentum"]);
  eq(groupStats(trades, (t) => t.pos.sell.date.slice(0, 7), 10).map((g) => [g.key, g.stats.n]), [["2026-02", 2], ["2026-01", 1]]);
});

// ---- ルール違反の自動判定 ----
const daily = { t: ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"], c: [1000, 960, 940, 930, 950] };
test("決算発表日が保有期間にあれば「決算をまたいだ」。発表日に売ればまたいでいない", () => {
  const pos = closedPos("2026-03-02", 1000, "2026-03-06", 950);
  eq(autoViolations(pos, pos.sell, { earningsDates: ["2026-03-04"] }).earnings, true);
  eq(autoViolations(pos, pos.sell, { earningsDates: ["2026-03-06"] }).earnings, false);
  eq(autoViolations(pos, pos.sell, { earningsDates: ["2026-03-02"] }).earnings, true);  // 買った日の引け後に発表
  eq(autoViolations(pos, pos.sell, { earningsDates: ["2026-02-10", "2026-05-10"] }).earnings, false);
  eq(autoViolations(pos, pos.sell, {}).earnings, null); // 決算日が分からなければ自己申告
});
test("損切りラインを下回った翌営業日までに売れば違反ではない", () => {
  const pos = closedPos("2026-03-02", 1000, "2026-03-04", 940, { stop: 970 });
  eq(autoViolations(pos, pos.sell, { chart: daily }).ignoredStop, false);  // 3/3 に割り、3/4 に売った
  const late = closedPos("2026-03-02", 1000, "2026-03-06", 950, { stop: 970 });
  eq(autoViolations(late, late.sell, { chart: daily }).ignoredStop, true);  // 3/3 に割ったのに 3/6 まで持った
  const safe = closedPos("2026-03-02", 1000, "2026-03-06", 950, { stop: 900 });
  eq(autoViolations(safe, safe.sell, { chart: daily }).ignoredStop, false);
});
test("損切り価格や日足がなければ、損切りの違反は自己申告", () => {
  const pos = closedPos("2026-03-02", 1000, "2026-03-06", 950);
  eq(autoViolations(pos, pos.sell, { chart: daily }).ignoredStop, null);
  const withStop = closedPos("2026-03-02", 1000, "2026-03-06", 950, { stop: 950 });
  eq(autoViolations(withStop, withStop.sell, {}).ignoredStop, null);
  const old = closedPos("2026-01-05", 1000, "2026-03-06", 950, { stop: 950 }); // 日足より前に買った
  eq(autoViolations(old, old.sell, { chart: daily }).ignoredStop, null);
});
test("理由メモなし・理由のすり替えの判定", () => {
  const pos = closedPos("2026-03-02", 1000, "2026-03-06", 950, { memo: { why: "a", basis: "", lose: "c" } });
  eq(autoViolations(pos, pos.sell).noMemo, true);
  eq(autoViolations(closedPos("2026-03-02", 1000, "2026-03-06", 950), pos.sell).noMemo, false);
  eq(autoViolations(pos, { ...pos.sell, reason: SWITCH_REASON }).switch, true);
  eq(autoViolations(pos, pos.sell).switch, null);
});
test("違反ありかどうか", () => {
  eq(hasViolation({ violations: { earnings: false, switch: true } }), true);
  eq(hasViolation({ violations: { earnings: false } }), false);
  eq(hasViolation({}), false);
});

// ---- 指数との比較 ----
const nikkei = { t: ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-06"], c: [40000, 40400, 41000, 42000] };
test("同じ日に同じ金額で指数を売買した場合の損益", () => {
  const v = vsIndex(closedPos("2026-03-02", 1000, "2026-03-06", 1100, { sell: { fee: 300 } }), nikkei);
  eq([v.actual, v.index, v.indexRet], [10000, 5000, 5]); // 実際の損益も手数料を含めない
});
test("休場日は直前の営業日の終値を使い、データより前の取引は比べない", () => {
  eq(vsIndex(closedPos("2026-03-02", 1000, "2026-03-05", 1100), nikkei).index, 2500); // 3/5 は 3/4 の終値
  eq(vsIndex(closedPos("2026-02-01", 1000, "2026-03-05", 1100), nikkei), null);
  eq(vsIndex(closedPos("2026-03-02", 1000, "2026-03-05", 1100), null), null);
});
test("年初来の累計で指数に勝っているか", () => {
  const sp = { t: ["2026-03-02", "2026-03-06"], c: [5000, 5500] };
  const list = [
    closedPos("2026-03-02", 1000, "2026-03-06", 1100),                                   // 実際 +10,000 ／ 指数 +5,000
    closedPos("2026-03-02", 100, "2026-03-06", 105, { market: "us", qty: 10 }),          // +$50 ／ +$100（×150円）
    closedPos("2025-03-02", 1000, "2025-03-06", 2000),                                   // 去年は数えない
    closedPos("2026-01-05", 1000, "2026-03-06", 1100),                                   // 指数のデータより前
    { ...closedPos("2026-03-02", 1000, "2026-03-06", 1100), sell: undefined },          // 保有中
  ];
  const y = ytdVsIndex(list, 2026, { jp: nikkei, us: sp }, 150);
  eq([y.actual, y.index, y.diff, y.count, y.missing, y.beat], [17500, 20000, -2500, 2, 1, false]);
});

// ---- フェーズ6C: イベントカレンダー ----
const calMarkets = {
  jp: { stocks: [
    { code: "7203", name: "トヨタ", earnings: { next: "2026-12-05", prev_session: "2026-12-04" } },
    { code: "6758", name: "ソニー", earnings: { next: "2027-02-01", prev_session: "2027-01-29" } },
  ] },
  us: { stocks: [{ code: "AAPL", name: "Apple", earnings: { next: "2026-12-02", prev_session: "2026-12-01" } }] },
};
const calMomentum = { jp: { stocks: [{ code: "7203", name: "トヨタ", earnings: { next: "2026-12-05" } }, { code: "8035", name: "東エレク", earnings: { next: "2026-12-10" } }] } };
const openPos = [{ market: "jp", code: "7203", name: "トヨタ" }, { market: "jp", code: "9999", name: "外れた銘柄" }];
test("決算予定は期間内だけ、重複なしで集め、保有中に印を付ける", () => {
  const found = earningsEvents(calMarkets, calMomentum, openPos, "2026-12-01", "2026-12-31");
  eq(found.map((e) => [e.code, e.date, e.held]).sort(), [["7203", "2026-12-05", true], ["8035", "2026-12-10", false], ["AAPL", "2026-12-02", false]]);
});
test("手入力の決算日を優先し、対象から外れた保有銘柄も出す", () => {
  store.set("earn:jp:7203", "2026-12-20");
  store.set("earn:jp:9999", "2026-12-15");
  const found = earningsEvents(calMarkets, calMomentum, openPos, "2026-12-01", "2026-12-31");
  eq(found.find((e) => e.code === "7203").date, "2026-12-20");
  eq(found.find((e) => e.code === "9999").held, true);
  store.remove("earn:jp:7203"); store.remove("earn:jp:9999");
});
const calEvents = { events: [
  { date: "2026-12-09", prev: "2026-12-08", name: "FOMC", market: "us", important: true },
  { date: "2026-12-18", prev: "2026-12-17", name: "オプション満期日", market: "us", important: false },
] };
test("重要イベントの前営業日と当日だけ注意を出す", () => {
  eq(bannerHTML(calEvents, calMarkets, [], "2026-12-07"), "");
  eq(bannerHTML(calEvents, calMarkets, [], "2026-12-08").includes("次の営業日（12/9）はFOMC"), true);
  eq(bannerHTML(calEvents, calMarkets, [], "2026-12-09").includes("今日はFOMC"), true);
  eq(bannerHTML(calEvents, calMarkets, [], "2026-12-17"), ""); // 重要でないイベント
});
test("保有銘柄の決算が近いと注意を出す（決算前営業日と当日）", () => {
  eq(bannerHTML(calEvents, calMarkets, openPos, "2026-12-04").includes("保有中のトヨタの決算が近い"), true);
  eq(bannerHTML(calEvents, calMarkets, openPos, "2026-12-03"), "");
  eq(bannerHTML(calEvents, calMarkets, [{ ...openPos[0], sell: { date: "2026-11-01" } }], "2026-12-04"), ""); // 決済済み
});

// ---- フェーズ7: 需給メモ ----
const sdCfg = { supply: { ratio_low: 1.0, sell_days_high: 2, buy_days_high: 5, ratio_high: 5.0, rising_weeks: 2, short_high: 50, short_jump_pt: 5, stale_days: 14 } };
test("同じ日付は置き換え、日付順に並べる", () => {
  const list = upsert(upsert([{ d: "2026-11-06", v: 1 }], { d: "2026-10-30", v: 2 }), { d: "2026-11-06", v: 3 });
  eq(list, [{ d: "2026-10-30", v: 2 }, { d: "2026-11-06", v: 3 }]);
  eq(removeDate(list, "2026-10-30"), [{ d: "2026-11-06", v: 3 }]);
});
test("25日平均出来高は、その日までの日足で計算する", () => {
  const t = Array.from({ length: 30 }, (_, i) => `2026-10-${String(i + 1).padStart(2, "0")}`);
  const chart = { t, v: t.map((_, i) => (i < 5 ? 1000 : 100)) };
  eq(avgVolume(chart, "2026-10-30"), 100);          // 6日目〜30日目
  eq(avgVolume(chart, "2026-10-25"), 1000 * 5 / 25 + 100 * 20 / 25);
  eq(avgVolume(chart, "2026-10-10"), null);          // 25日分ない
  eq(avgVolume(null, "2026-10-30"), null);
});
const wk = (d, buy, sell, vol) => ({ d, buy, sell, ...(vol ? { vol } : {}) });
test("信用倍率と前週比", () => {
  const st = marginState([wk("2026-10-30", 1000, 500), wk("2026-11-06", 1200, 400)], sdCfg, "2026-11-10");
  eq([st.ratio, Math.round(st.buyChange), Math.round(st.sellChange), st.latest.d], [3, 20, -20, "2026-11-06"]);
  eq(marginState([], sdCfg, "2026-11-10"), null);
});
test("買い残が多く増加中なら「戻り売りが出やすい」（出来高の日数で判定）", () => {
  const up = [wk("2026-10-23", 400, 100, 100), wk("2026-10-30", 450, 100, 100), wk("2026-11-06", 500, 100, 100)];
  eq(marginState(up, sdCfg, "2026-11-10").signals.map((g) => g.key), ["overhang"]);            // 5日分ちょうど・2週連続増加
  eq(marginState(up.slice(1), sdCfg, "2026-11-10").signals, []);                                 // 増加が1週だけ
  const flat = [wk("2026-10-23", 500, 100, 100), wk("2026-10-30", 450, 100, 100), wk("2026-11-06", 500, 100, 100)];
  eq(marginState(flat, sdCfg, "2026-11-10").signals, []);
  const light = [wk("2026-10-23", 100, 100, 100), wk("2026-10-30", 200, 100, 100), wk("2026-11-06", 300, 100, 100)];
  eq(marginState(light, sdCfg, "2026-11-10").signals, []);                                       // 3日分で少ない
});
test("出来高が分からなければ信用倍率で「買い残が多い」を判定する", () => {
  const up = [wk("2026-10-23", 300, 100), wk("2026-10-30", 400, 100), wk("2026-11-06", 500, 100)];
  eq(marginState(up, sdCfg, "2026-11-10").signals.map((g) => g.key), ["overhang"]);  // 5倍ちょうど
});
test("信用倍率が低い、または売り残が多いと「買い戻しが入りやすい」", () => {
  eq(marginState([wk("2026-11-06", 100, 100)], sdCfg, "2026-11-10").signals.map((g) => g.key), ["squeeze"]);   // 1倍ちょうど
  eq(marginState([wk("2026-11-06", 300, 200, 100)], sdCfg, "2026-11-10").signals.map((g) => g.key), ["squeeze"]); // 売り残2日分
  eq(marginState([wk("2026-11-06", 300, 100, 100)], sdCfg, "2026-11-10").signals, []);
  eq(marginState([wk("2026-11-06", 300, 0)], sdCfg, "2026-11-10").ratio, null);   // 売り残ゼロ
});
test("入力から日数がたつと「入力が古い」", () => {
  eq(marginState([wk("2026-11-06", 300, 100)], sdCfg, "2026-11-20").stale, false);
  eq(marginState([wk("2026-11-06", 300, 100)], sdCfg, "2026-11-21").stale, true);
});
test("空売り比率: 高い・急上昇", () => {
  const base = ["01", "02", "03", "04", "05"].map((d) => ({ d: `2026-11-${d}`, v: 40 }));
  const st = shortRatioState([...base, { d: "2026-11-06", v: 45 }], sdCfg, "2026-11-06");
  eq([st.avg, st.jump, st.high], [40, true, false]);
  eq(shortRatioState([...base, { d: "2026-11-06", v: 44.9 }], sdCfg, "2026-11-06").jump, false);
  eq(shortRatioState([{ d: "2026-11-06", v: 50 }], sdCfg, "2026-11-06").high, true);
  eq(shortRatioState([], sdCfg, "2026-11-06"), null);
});
test("投資部門別: 直近4週の合計（空欄は数えない）", () => {
  const list = [
    { d: "2026-10-09", foreign: 9999, individual: 1 },
    { d: "2026-10-16", foreign: 100, individual: -50, trust: null },
    { d: "2026-10-23", foreign: -300, individual: 200, trust: 10 },
    { d: "2026-10-30", foreign: 50, individual: null, trust: 20 },
    { d: "2026-11-06", foreign: 25, individual: -10, trust: null },
  ];
  const f = flowSummary(list, 4);
  eq([f.weeks, f.from, f.foreign, f.individual, f.trust], [4, "2026-10-16", -125, 140, 30]);
  eq(flowSummary([], 4), null);
});
test("直近の金曜日", () => {
  eq(lastFriday("2026-11-13"), "2026-11-13");  // 金曜
  eq(lastFriday("2026-11-15"), "2026-11-13");  // 日曜
  eq(lastFriday("2026-11-19"), "2026-11-13");  // 木曜
});

document.getElementById("out").textContent =
  `合格 ${results.passed} 件 / 失敗 ${results.failed.length} 件\n` + results.failed.join("\n");
window.__results = results;

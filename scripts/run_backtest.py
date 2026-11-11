"""バックテストを実行し、結果を docs/data/<市場>_backtest.json に書き出す。

使い方:  python scripts/run_backtest.py --market jp   （または us）
  --skip-momentum   順張り（VCP）の検証を省く（時間がかかるため）

毎日は実行しない。しきい値を見直したいときに手動で実行する。
結果には限界がある: 今の構成銘柄だけで検証している（過去に指数から外れた銘柄は含まない）ので、
成績は実際より良く出る。手数料・税金・売買時の価格のずれも含まない。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import markets  # noqa: E402
from markets import fetch  # noqa: E402
from screener import backtest as bt  # noqa: E402
from screener import indicators as ind  # noqa: E402
from screener import momentum as mo  # noqa: E402
from screener.config import load_thresholds  # noqa: E402

DATA = ROOT / "docs" / "data"
PERIODS = ("train", "test")

# しきい値を動かして比べる項目: (説明, 設定の場所, 試す値, 成績を見るサイン)
SWEEPS = [
    ("条件1: 急落の大きさ（前日比 %）", ("buy", "drop_pct"), [-2.0, -2.5, -3.0, -4.0, -5.0], "cond1"),
    ("条件2: 25日線からの乖離（%）", ("buy", "ma_deviation_pct"), [-3.0, -5.0, -7.0, -10.0], "cond2"),
    ("条件3: バンド到達の見方", ("buy", "bb_touch"), ["low", "close"], "cond3"),
    ("条件4: RCI の水準（%）", ("buy", "rci_max"), [-80, -90, -95], "cond4"),
    ("エントリー候補: 必要な買い条件の点灯数", ("entry", "min_conditions"), [1, 2, 3], "entry"),
    ("エントリー候補: 点灯から反転サインまでの日数", ("entry", "lookback_days"), [3, 5, 10], "entry"),
    ("安値圏の広さ（下から %）", ("zone", "low_pct"), [15, 25, 35], "entry"),
]

# 順張り: VCP の条件をゆるめた場合の比較
VCP_VARIANTS = [
    ("現在の設定", {}),
    ("出来高の減少を必須にしない", {"require_volume_dry": False}),
    ("山の切り上げを8%まで許す", {"max_high_rise_pct": 8}),
    ("上の2つを両方", {"require_volume_dry": False, "max_high_rise_pct": 8}),
]


def load_prices(market, universe_file: str, as_of: dt.date, years: int):
    universe = pd.read_csv(ROOT / "config" / universe_file, dtype=str, keep_default_na=False)
    tickers = {code: market.ticker(code) for code in universe["code"]}
    prices = fetch.download_daily(list(tickers.values()), as_of, period=f"{years}y")
    frames = {code: prices[t] for code, t in tickers.items() if t in prices and len(prices[t]) >= 300}
    return universe, frames


class Collector:
    """サインごと・期間ごとに、その後の騰落率をためていく。"""

    def __init__(self, horizons):
        self.horizons = horizons
        self.returns = defaultdict(lambda: {p: {h: [] for h in horizons} for p in PERIODS})
        self.drawdowns = defaultdict(lambda: {p: [] for p in PERIODS})

    def add(self, key, mask: np.ndarray, is_test: np.ndarray, forward: pd.DataFrame, drawdown: pd.Series):
        for period, in_period in (("train", ~is_test), ("test", is_test)):
            chosen = mask & in_period
            if not chosen.any():
                continue
            for h in self.horizons:
                self.returns[key][period][h].append(forward[h].to_numpy()[chosen])
            self.drawdowns[key][period].append(drawdown.to_numpy()[chosen])

    def stats(self, key) -> dict:
        out = {}
        for period in PERIODS:
            by_h = {}
            for h in self.horizons:
                parts = self.returns[key][period][h]
                by_h[str(h)] = bt.summarize(np.concatenate(parts)) if parts else None
            parts = self.drawdowns[key][period]
            dd = bt.summarize(np.concatenate(parts)) if parts else None
            out[period] = {"h": by_h, "drawdown": None if dd is None else {"mean": dd["mean"], "p10": dd["p10"]}}
        return out


def with_value(cfg: dict, path, value) -> dict:
    changed = copy.deepcopy(cfg)
    changed[path[0]][path[1]] = value
    return changed


def run_contrarian(market, cfg: dict, as_of: dt.date, split: pd.Timestamp) -> dict:
    b = cfg["backtest"]
    horizons, main = b["horizons"], b["main_horizon"]
    universe, frames = load_prices(market, f"universe_{market.key}.csv", as_of, b["years"])
    names = dict(zip(universe["code"], universe["name"]))
    print(f"[{market.key}・検証] 逆張り: {len(frames)} 銘柄")

    collector = Collector(horizons)
    trades = defaultdict(lambda: {p: [] for p in PERIODS})
    prepared = {}
    for code, df in frames.items():
        is_test = np.asarray(df.index >= split)
        forward = bt.forward_returns(df, horizons)
        drawdown = bt.worst_drawdown(df, main)
        prepared[code] = (is_test, forward, drawdown)
        flags = bt.signal_flags(df, cfg)
        collector.add("baseline", np.ones(len(df), dtype=bool), is_test, forward, drawdown)
        for key in flags.columns:
            collector.add(key, flags[key].to_numpy(), is_test, forward, drawdown)

        # 出口ルールつきの売買
        close = df["close"]
        ma_mid = ind.sma(close, cfg["ma"]["mid"])
        bands = ind.bollinger(close, cfg["buy"]["bb_period"], cfg["buy"]["bb_ddof"])
        strategies = {
            "c1": dict(entries=flags["cond1"], take_fixed=close.shift(1) * (1 + cfg["buy"]["drop_pct"] / 100)),
            "c2": dict(entries=flags["cond2"], take_dynamic=ma_mid),
            "c3_2": dict(entries=flags["cond3"], take_dynamic=bands["mid"], stop_flag=close < bands["lower3"]),
            "c3_3": dict(entries=flags["bb3"], take_dynamic=bands["mid"]),
            "count2": dict(entries=flags["count2"], take_dynamic=ma_mid),
            "count3": dict(entries=flags["count3"], take_dynamic=ma_mid),
            "entry": dict(entries=flags["entry"], take_dynamic=ma_mid),
        }
        for name, args in strategies.items():
            for hold in b["max_hold_days"]:
                for stop in b["stop_pcts"]:
                    for trade in bt.simulate(df, stop_pct=stop, max_hold=hold, **args):
                        period = "test" if is_test[trade["entry_i"]] else "train"
                        trades[(name, hold, stop)][period].append(trade)

    signals = {key: collector.stats(key) for key in ["baseline"] + [k for k in collector.returns if k != "baseline"]}
    trade_rows = [
        {"strategy": name, "max_hold": hold, "stop": stop,
         **{p: bt.summarize_trades(by_period[p]) for p in PERIODS}}
        for (name, hold, stop), by_period in trades.items()
    ]

    # しきい値を動かして比べる
    sweeps = []
    for label, path, values, key in SWEEPS:
        rows = []
        for value in values:
            changed = with_value(cfg, path, value)
            sweep = Collector([main])
            for code, df in frames.items():
                is_test, forward, drawdown = prepared[code]
                sweep.add(key, bt.signal_flags(df, changed)[key].to_numpy(), is_test, forward[[main]], drawdown)
            stats = sweep.stats(key)
            rows.append({"value": value, "current": cfg[path[0]][path[1]] == value,
                         **{p: stats[p]["h"][str(main)] for p in PERIODS}})
        sweeps.append({"label": label, "param": ".".join(path), "signal": key, "rows": rows})
        print(f"  比較: {label}")

    # 銘柄ごとの RCI の水準
    rci_rows = []
    for code, df in frames.items():
        study = bt.rci_level_study(df, b["rci_levels"], cfg, main, b["rci_min_samples"])
        rci_rows.append({"code": code, "name": names[code], "best": study["best"],
                         "levels": {str(lv): s and {"n": s["n"], "win": s["win"], "mean": s["mean"]} for lv, s in study["levels"].items()}})
    return {"stocks": len(frames), "signals": signals, "trades": trade_rows, "sweeps": sweeps, "rci": rci_rows}


def run_momentum(market, cfg: dict, as_of: dt.date, split: pd.Timestamp) -> dict:
    b = cfg["backtest"]
    horizons = b["momentum_horizons"]
    universe, frames = load_prices(market, f"universe_{market.key}_momentum.csv", as_of, b["years"])
    print(f"[{market.key}・検証] 順張り: {len(frames)} 銘柄")
    close = pd.DataFrame({c: f["close"] for c, f in frames.items()})
    high = pd.DataFrame({c: f["high"] for c, f in frames.items()})
    low = pd.DataFrame({c: f["low"] for c, f in frames.items()})
    passed = bt.template_history(close, high, low, cfg)

    prepared = {}
    base = Collector(horizons)
    for code, df in frames.items():
        is_test = np.asarray(df.index >= split)
        forward = bt.forward_returns(df, horizons)
        drawdown = bt.worst_drawdown(df, horizons[1])
        prepared[code] = (is_test, forward, drawdown)
        base.add("baseline", np.ones(len(df), dtype=bool), is_test, forward, drawdown)
        base.add("template", passed[code].reindex(df.index, fill_value=False).to_numpy(), is_test, forward, drawdown)

    variants = []
    for label, change in VCP_VARIANTS:
        started = time.time()
        changed = copy.deepcopy(cfg)
        changed["momentum"]["vcp"].update(change)
        collector = Collector(horizons)
        trades = defaultdict(lambda: {p: [] for p in PERIODS})
        for code, df in frames.items():
            is_test, forward, drawdown = prepared[code]
            days = bt.vcp_breakout_days(df, passed[code], changed)
            for key in ("breakout", "weak"):
                collector.add(key, days[key].to_numpy(), is_test, forward, drawdown)
            if not change:  # 売買シミュレーションは現在の設定だけ
                ma_fast = ind.sma(df["close"], cfg["momentum"]["ma"]["fast"])
                for hold in b["momentum_max_hold_days"]:
                    found = bt.simulate(df, days["breakout"], stop_pct=cfg["momentum"]["exit"]["stop_loss_pct"],
                                        stop_flag=mo.ma_break_with_volume(df, cfg), max_hold=hold)
                    for trade in found:
                        trades[hold]["test" if is_test[trade["entry_i"]] else "train"].append(trade)
                del ma_fast
        variants.append({
            "label": label, "current": not change,
            "breakout": collector.stats("breakout"), "weak": collector.stats("weak"),
            "trades": [{"max_hold": hold, **{p: bt.summarize_trades(by[p]) for p in PERIODS}} for hold, by in trades.items()],
        })
        print(f"  VCP: {label}（{time.time() - started:.0f}秒）")
    return {"stocks": len(frames), "baseline": base.stats("baseline"), "template": base.stats("template"), "variants": variants}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    parser.add_argument("--skip-momentum", action="store_true")
    args = parser.parse_args()

    market = markets.get(args.market)
    cfg = load_thresholds(market.key)
    b = cfg["backtest"]
    now = dt.datetime.now(dt.timezone.utc)
    as_of = fetch.last_completed_session(market, now)
    split = pd.Timestamp(as_of) - pd.DateOffset(years=b["test_years"])
    start = pd.Timestamp(as_of) - pd.DateOffset(years=b["years"])

    result = {
        "market": market.key,
        "label": market.label,
        "as_of": as_of.isoformat(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {"start": start.strftime("%Y-%m-%d"), "split": split.strftime("%Y-%m-%d"), "end": as_of.isoformat()},
        "universe": {"contrarian": market.universe_name, "momentum": market.momentum_universe_name},
        "config": cfg,
        "contrarian": run_contrarian(market, cfg, as_of, split),
        "momentum": None if args.skip_momentum else run_momentum(market, cfg, as_of, split),
    }
    path = DATA / f"{market.key}_backtest.json"
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[{market.key}・検証] 完了: {path.name}（{path.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""バックテストを相場環境別に集計し直し、docs/data/<市場>_regime_study.json に書き出す。

使い方:  python scripts/run_regime_study.py --market jp   （または us）
  --skip-momentum   順張り（VCP）の集計を省く（時間がかかるため）

過去10年の各営業日について相場環境（逆張り向き／順張り向き／様子見）を判定し、
各サインが出た日の環境ごとに、その後の成績を分けて集計する。数え方はバックテストと同じ。
毎日は実行しない。相場環境の判定基準を見直したいときに手動で実行する。

限界: 相場環境の計算に使う銘柄も「今の構成銘柄」なので、昔ほど対象銘柄が少なく、
上昇してきた銘柄に偏る（200日線より上の銘柄の割合が実際より高めに出やすい）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import markets  # noqa: E402
from markets import fetch  # noqa: E402
from run_backtest import load_prices  # noqa: E402
from screener import backtest as bt  # noqa: E402
from screener import indicators as ind  # noqa: E402
from screener import momentum as mo  # noqa: E402
from screener import regime as rg  # noqa: E402
from screener.config import load_thresholds  # noqa: E402

DATA = ROOT / "docs" / "data"
PERIODS = ("all", "test")  # 全期間 / 直近2年
CONTRARIAN_SIGNALS = ["entry", "count2", "count3", "cond1", "cond3", "bb3",
                      "hanging_man", "harami_top", "double_top", "island_top", "two_black"]


class ByRegime:
    """サイン × 環境 × 期間 ごとに、その後の騰落率をためる。"""

    def __init__(self, horizons):
        self.horizons = horizons
        self.values = defaultdict(lambda: {h: [] for h in horizons})

    def add(self, key, mask, regimes, is_test, forward):
        for reg in rg.LABELS:
            for period, in_period in (("all", np.ones(len(mask), dtype=bool)), ("test", is_test)):
                chosen = mask & (regimes == reg) & in_period
                if chosen.any():
                    for h in self.horizons:
                        self.values[(key, reg, period)][h].append(forward[h].to_numpy()[chosen])

    def stats(self, key):
        out = {}
        for reg in rg.LABELS:
            out[reg] = {}
            for period in PERIODS:
                parts = self.values.get((key, reg, period))
                out[reg][period] = None if not parts else {
                    str(h): bt.summarize(np.concatenate(parts[h])) if parts[h] else None for h in self.horizons
                }
        return out


def trade_stats(trades):
    out = {}
    for reg in rg.LABELS:
        out[reg] = {p: bt.summarize_trades([t for t in trades if t["regime"] == reg and (p == "all" or t["test"])]) for p in PERIODS}
    return out


def regime_history(market, cfg, as_of, years):
    universe, frames = load_prices(market, f"universe_{market.key}_momentum.csv", as_of, years)
    extra = [market.index_ticker] + ([market.vol_ticker] if market.vol_ticker else [])
    side = fetch.download_daily(extra, as_of, period=f"{years}y")
    table = rg.compute(frames, side[market.index_ticker], side.get(market.vol_ticker) if market.vol_ticker else None, cfg)
    print(f"[{market.key}・環境別] 相場環境を判定: {len(frames)} 銘柄、{table['regime'].notna().sum()} 営業日")
    return table["regime"], frames


def run_contrarian(market, cfg, as_of, split, regime):
    b = cfg["backtest"]
    _, frames = load_prices(market, f"universe_{market.key}.csv", as_of, b["years"])
    collector = ByRegime(b["horizons"])
    trades = []
    for code, df in frames.items():
        regimes = regime.reindex(df.index).to_numpy()
        is_test = np.asarray(df.index >= split)
        forward = bt.forward_returns(df, b["horizons"])
        flags = bt.signal_flags(df, cfg)
        collector.add("baseline", np.ones(len(df), dtype=bool), regimes, is_test, forward)
        for key in CONTRARIAN_SIGNALS:
            collector.add(key, flags[key].to_numpy(), regimes, is_test, forward)
        # エントリー候補 → 25日線で利確（最大20日・損切りなし。検証結果ページの基本と同じ）
        for t in bt.simulate(df, flags["entry"], take_dynamic=ind.sma(df["close"], cfg["ma"]["mid"]),
                             stop_pct=cfg["forward"]["entry_stop_pct"], max_hold=cfg["forward"]["entry_max_hold"]):
            signal_i = t["entry_i"] - 1
            trades.append({**t, "regime": regimes[signal_i], "test": bool(is_test[signal_i])})
    print(f"[{market.key}・環境別] 逆張り: {len(frames)} 銘柄")
    return {"stocks": len(frames), "signals": {k: collector.stats(k) for k in ["baseline"] + CONTRARIAN_SIGNALS},
            "entry_trades": trade_stats(trades)}


def run_momentum(market, cfg, as_of, split, regime, frames):
    b = cfg["backtest"]
    horizons = b["momentum_horizons"]
    close = pd.DataFrame({c: f["close"] for c, f in frames.items()})
    high = pd.DataFrame({c: f["high"] for c, f in frames.items()})
    low = pd.DataFrame({c: f["low"] for c, f in frames.items()})
    passed = bt.template_history(close, high, low, cfg)
    collector = ByRegime(horizons)
    trades = []
    for code, df in frames.items():
        regimes = regime.reindex(df.index).to_numpy()
        is_test = np.asarray(df.index >= split)
        forward = bt.forward_returns(df, horizons)
        collector.add("baseline", np.ones(len(df), dtype=bool), regimes, is_test, forward)
        days = bt.vcp_breakout_days(df, passed[code], cfg)
        collector.add("breakout", days["breakout"].to_numpy(), regimes, is_test, forward)
        for t in bt.simulate(df, days["breakout"], stop_pct=cfg["momentum"]["exit"]["stop_loss_pct"],
                             stop_flag=mo.ma_break_with_volume(df, cfg), max_hold=cfg["forward"]["breakout_max_hold"]):
            signal_i = t["entry_i"] - 1
            trades.append({**t, "regime": regimes[signal_i], "test": bool(is_test[signal_i])})
    print(f"[{market.key}・環境別] 順張り: {len(frames)} 銘柄")
    return {"stocks": len(frames), "signals": {k: collector.stats(k) for k in ("baseline", "breakout")},
            "breakout_trades": trade_stats(trades)}


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
    regime, mo_frames = regime_history(market, cfg, as_of, b["years"])
    known = regime.dropna()
    result = {
        "market": market.key,
        "as_of": as_of.isoformat(),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {"start": known.index[0].strftime("%Y-%m-%d"), "split": split.strftime("%Y-%m-%d"), "end": as_of.isoformat()},
        "universe": {"contrarian": market.universe_name, "momentum": market.momentum_universe_name},
        "config": {"regime": cfg["regime"], "forward": cfg["forward"], "backtest": b},
        "days": {reg: {"all": int((known == reg).sum()), "test": int((known[known.index >= split] == reg).sum())} for reg in rg.LABELS},
        "contrarian": run_contrarian(market, cfg, as_of, split, regime),
        "momentum": None if args.skip_momentum else run_momentum(market, cfg, as_of, split, regime, mo_frames),
    }
    path = DATA / f"{market.key}_regime_study.json"
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[{market.key}・環境別] 完了: {path.name}（{path.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

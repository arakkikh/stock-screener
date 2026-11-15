"""相場環境の判定基準を変えた場合に、環境別の成績がどう変わるかを比べる（基準は自動では書き換えない）。

使い方:  python scripts/run_regime_sweep.py --market jp   （または us）

比べる基準（ほかの基準は今のまま）:
  案A … 順張り向きの条件「200日線より上の銘柄が uptrend_pct 以上」を 60（今）・50・条件なし で比べる
  案B … 逆張り向きの条件「25日線より上の銘柄が oversold_pct 以下」を 20（今）・25・30 で比べる
銘柄ごとのサインとその後の騰落率は1回だけ計算し、相場環境の判定だけを基準ごとに計算し直す。
結果は docs/data/<市場>_regime_sweep.json（検証結果ページに表示）。限界は run_regime_study.py と同じ。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import markets  # noqa: E402
from markets import fetch  # noqa: E402
from run_backtest import load_prices  # noqa: E402
from run_regime_study import ByRegime, trade_stats  # noqa: E402
from screener import backtest as bt  # noqa: E402
from screener import indicators as ind  # noqa: E402
from screener import momentum as mo  # noqa: E402
from screener import regime as rg  # noqa: E402
from screener.config import load_thresholds  # noqa: E402

DATA = ROOT / "docs" / "data"

VARIANTS = [
    ("current", "今の基準", {}),
    ("A", "順張り向き: 200日線より上が50%以上", {"uptrend_pct": 50}),
    ("A", "順張り向き: 200日線より上の条件なし（指数の位置と向きだけ）", {"uptrend_pct": 0}),
    ("B", "逆張り向き: 25日線より上が25%以下", {"oversold_pct": 25}),
    ("B", "逆張り向き: 25日線より上が30%以下", {"oversold_pct": 30}),
]


def prepare(market, cfg, as_of, split):
    """基準によらない部分（騰落の広がり・各銘柄のサインとその後の騰落率・売買）を1回だけ計算する。"""
    b = cfg["backtest"]
    _, mo_frames = load_prices(market, f"universe_{market.key}_momentum.csv", as_of, b["years"])
    extra = [market.index_ticker] + ([market.vol_ticker] if market.vol_ticker else [])
    side = fetch.download_daily(extra, as_of, period=f"{b['years']}y")
    index_df = side[market.index_ticker]
    vix = side[market.vol_ticker]["close"] if market.vol_ticker and market.vol_ticker in side else None
    days = index_df.index
    close = pd.DataFrame({c: f["close"] for c, f in mo_frames.items()})
    high = pd.DataFrame({c: f["high"] for c, f in mo_frames.items()})
    low = pd.DataFrame({c: f["low"] for c, f in mo_frames.items()})
    breadth = rg.breadth(close.reindex(days), high.reindex(days), low.reindex(days), cfg)
    print(f"[{market.key}・基準比較] 騰落の広がり: {len(mo_frames)} 銘柄")

    _, c_frames = load_prices(market, f"universe_{market.key}.csv", as_of, b["years"])
    contrarian = []
    for code, df in c_frames.items():
        flags = bt.signal_flags(df, cfg)
        trades = bt.simulate(df, flags["entry"], take_dynamic=ind.sma(df["close"], cfg["ma"]["mid"]),
                             stop_pct=cfg["forward"]["entry_stop_pct"], max_hold=cfg["forward"]["entry_max_hold"])
        contrarian.append((df.index, np.asarray(df.index >= split), bt.forward_returns(df, b["horizons"]),
                           flags["entry"].to_numpy(), trades))
    print(f"[{market.key}・基準比較] 逆張り: {len(c_frames)} 銘柄")

    passed = bt.template_history(close, high, low, cfg)
    momentum = []
    for code, df in mo_frames.items():
        breakout = bt.vcp_breakout_days(df, passed[code], cfg)["breakout"]
        trades = bt.simulate(df, breakout, stop_pct=cfg["momentum"]["exit"]["stop_loss_pct"],
                             stop_flag=mo.ma_break_with_volume(df, cfg), max_hold=cfg["forward"]["breakout_max_hold"])
        momentum.append((df.index, np.asarray(df.index >= split), bt.forward_returns(df, b["momentum_horizons"]),
                         breakout.to_numpy(), trades))
    print(f"[{market.key}・基準比較] 順張り: {len(mo_frames)} 銘柄")
    return breadth, index_df["close"], vix, contrarian, momentum


def evaluate(regime: pd.Series, split, prepared_rows, horizons, key):
    """1つの基準について、環境別の「いつ買っても」「サイン」「出口ルールつき売買」を集計する。"""
    collector = ByRegime(horizons)
    trades = []
    for index, is_test, forward, mask, found in prepared_rows:
        regimes = regime.reindex(index).to_numpy()
        collector.add("baseline", np.ones(len(index), dtype=bool), regimes, is_test, forward)
        collector.add(key, mask, regimes, is_test, forward)
        for t in found:
            i = t["entry_i"] - 1
            trades.append({**t, "regime": regimes[i], "test": bool(is_test[i])})
    return {"baseline": collector.stats("baseline"), "signal": collector.stats(key), "trades": trade_stats(trades)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    args = parser.parse_args()
    market = markets.get(args.market)
    cfg = load_thresholds(market.key)
    b = cfg["backtest"]
    now = dt.datetime.now(dt.timezone.utc)
    as_of = fetch.last_completed_session(market, now)
    split = pd.Timestamp(as_of) - pd.DateOffset(years=b["test_years"])
    breadth, index_close, vix, contrarian, momentum = prepare(market, cfg, as_of, split)

    rows = []
    for group, label, change in VARIANTS:
        changed = copy.deepcopy(cfg)
        changed["regime"].update(change)
        regime = rg.classify(breadth, index_close, vix, changed)["regime"]
        known = regime.dropna()
        rows.append({
            "group": group, "label": label, "change": change,
            "days": {r: {"all": int((known == r).sum()), "test": int((known[known.index >= split] == r).sum())} for r in rg.LABELS},
            "entry": evaluate(regime, split, contrarian, b["horizons"], "entry"),
            "breakout": evaluate(regime, split, momentum, b["momentum_horizons"], "breakout"),
        })
        print(f"  {label}: " + "・".join(f"{r} {rows[-1]['days'][r]['all']}日" for r in rg.LABELS))
    result = {
        "market": market.key, "as_of": as_of.isoformat(), "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {"split": split.strftime("%Y-%m-%d")},
        "horizon": {"entry": str(b["main_horizon"]), "breakout": str(b["momentum_horizons"][1])},
        "current": {"uptrend_pct": cfg["regime"]["uptrend_pct"], "oversold_pct": cfg["regime"]["oversold_pct"]},
        "variants": rows,
    }
    path = DATA / f"{market.key}_regime_sweep.json"
    path.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[{market.key}・基準比較] 完了: {path.name}（{path.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

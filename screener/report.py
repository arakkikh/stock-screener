"""判定結果を、画面が読む JSON の形にまとめる。市場に依存しない。"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import indicators as ind
from . import signals as sig


def _num(value, digits: int) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _column(series: pd.Series, digits: int) -> list:
    return [_num(v, digits) for v in series.to_numpy()]


def _dates(index: pd.Index) -> List[str]:
    return [d.strftime("%Y-%m-%d") for d in index]


def _events(flags: pd.DataFrame, dates: List[str]) -> List[dict]:
    """True の付いた日を {"d": 日付, "k": サインの種類} の並びにする。"""
    rows, cols = np.nonzero(flags.to_numpy())
    return [{"d": dates[r], "k": flags.columns[c]} for r, c in zip(rows, cols)]


def chart_payload(df: pd.DataFrame, cfg: dict, digits: int) -> dict:
    """チャート用のデータ（ローソク足・出来高・移動平均線・ボリンジャーバンド）。"""
    ma, buy = cfg["ma"], cfg["buy"]
    close = df["close"]
    bb = ind.bollinger(close, buy["bb_period"], buy["bb_ddof"])
    return {
        "t": _dates(df.index),
        "o": _column(df["open"], digits),
        "h": _column(df["high"], digits),
        "l": _column(df["low"], digits),
        "c": _column(close, digits),
        "v": [None if pd.isna(v) else int(v) for v in df["volume"].to_numpy()],
        "ma_s": _column(ind.sma(close, ma["short"]), digits),
        "ma_m": _column(ind.sma(close, ma["mid"]), digits),
        "ma_l": _column(ind.sma(close, ma["long"]), digits),
        "bb_u2": _column(bb["upper2"], digits),
        "bb_l2": _column(bb["lower2"], digits),
        "bb_l3": _column(bb["lower3"], digits),
    }


def analyze_stock(df: pd.DataFrame, cfg: dict, digits: int) -> Tuple[dict, dict]:
    """1銘柄分の判定をまとめる。戻り値は (一覧用の要約, チャート用のデータ)。"""
    ma, b = cfg["ma"], cfg["buy"]
    close = df["close"]
    dates = _dates(df.index)
    ma_mid, ma_long = ind.sma(close, ma["mid"]), ind.sma(close, ma["long"])
    bb = ind.bollinger(close, b["bb_period"], b["bb_ddof"])

    buy = sig.buy_conditions(df, cfg)
    reversal = sig.reversal_signs(df, cfg)
    warning = sig.warning_signs(df, cfg)
    trend = sig.trend_mode(df, cfg)
    flags = pd.concat(
        [
            reversal,
            warning,
            trend[["two_white"]],
            sig.entry_candidates(buy, reversal, cfg).rename("entry"),
            sig.ma100_bounce(df, ma_mid, ma_long, cfg).rename("bounce"),
            sig.mark_days(sig.bb_divergences(df, bb["lower2"], cfg), df.index).rename("divergence"),
        ],
        axis=1,
    )
    today = flags.iloc[-1]

    # 買い条件が最後に点灯してから何営業日たったか（昇格の対象期間を過ぎていれば None）
    lit = (buy["count"] >= cfg["entry"]["min_conditions"]).to_numpy()[-cfg["entry"]["lookback_days"] :]
    lit_days_ago = int(len(lit) - 1 - np.flatnonzero(lit)[-1]) if lit.any() else None

    last_buy, last_trend = buy.iloc[-1], trend.iloc[-1]
    recent_from = max(0, len(df) - cfg["display"]["recent_days"])
    summary = {
        "date": dates[-1],
        "close": _num(close.iloc[-1], digits),
        "change_pct": _num(last_buy["change_pct"], 2),
        "deviation_pct": _num(last_buy["deviation_pct"], 2),
        "rci": _num(last_buy["rci"], 1),
        "conds": [i for i in (1, 2, 3, 4) if last_buy[f"cond{i}"]],
        "count": int(last_buy["count"]),
        "bb_level": int(last_buy["bb_level"]),
        "lit_days_ago": lit_days_ago,
        "entry": bool(today["entry"]),
        "bounce": bool(today["bounce"]),
        "divergence": bool(today["divergence"]),
        "reversal": [k for k in reversal.columns if today[k]],
        "warnings": [k for k in warning.columns if today[k]],
        "recent": _events(flags.iloc[recent_from:], dates[recent_from:]),
        "zone": _num(sig.pat.zone_position(df, cfg).iloc[-1], 0),
        "trend": {
            "perfect_order": bool(last_trend["perfect_order"]),
            "in_trend": bool(last_trend["in_trend"]),
            "approach_count": int(last_trend["approach_count"]),
            "exit_warning": bool(last_trend["exit_warning"]),
            "warning_cleared": bool(last_trend["warning_cleared"]),
            "two_white": bool(last_trend["two_white"]),
        },
        # 出口ルールの表示に使う、最新日の水準
        "levels": {
            "ma_mid": _num(ma_mid.iloc[-1], digits),
            "ma_long": _num(ma_long.iloc[-1], digits),
            "bb_mid": _num(bb["mid"].iloc[-1], digits),
            "bb_l2": _num(bb["lower2"].iloc[-1], digits),
            "bb_l3": _num(bb["lower3"].iloc[-1], digits),
            "low": _num(df["low"].iloc[-1], digits),
            "high": _num(df["high"].iloc[-1], digits),
        },
    }
    chart = chart_payload(df, cfg, digits)
    chart["cnt"] = [int(v) for v in buy["count"].to_numpy()]
    chart["marks"] = _events(flags, dates)
    return summary, chart


def index_state(df: pd.DataFrame, cfg: dict, digits: int = 2) -> dict:
    """基準指数の状態（5日・25日・100日線との位置関係と向き）。"""
    close = df["close"]
    days = cfg["trend"]["slope_days"]
    lines = {name: ind.sma(close, cfg["ma"][name]) for name in ("short", "mid", "long")}
    rising = {name: bool(ind.is_rising(line, days).iloc[-1]) for name, line in lines.items()}
    last = {name: line.iloc[-1] for name, line in lines.items()}
    return {
        "date": _dates(df.index)[-1],
        "close": _num(close.iloc[-1], digits),
        "change_pct": _num(ind.change_pct(close).iloc[-1], 2),
        "ma": {name: _num(value, digits) for name, value in last.items()},
        "above": {name: bool(close.iloc[-1] > value) for name, value in last.items()},
        "rising": rising,
        "perfect_order": bool(last["short"] > last["mid"] > last["long"] and all(rising.values())),
    }


def sector_trends(closes: pd.DataFrame, sector_of: Dict[str, str], cfg: dict) -> Dict[str, dict]:
    """セクターごとの方向。属する銘柄の値動きを平均した指数で判定する。

    下落トレンド = 指数が25日線より下、かつ25日線が100日線より下。
    closes は列が銘柄コード、行が日付の終値の表。
    """
    returns = closes.pct_change(fill_method=None)
    result = {}
    for sector in sorted(set(sector_of.values())):
        codes = [c for c in closes.columns if sector_of.get(c) == sector]
        if not codes:
            continue
        index = (1 + returns[codes].mean(axis=1).fillna(0)).cumprod()
        mid = ind.sma(index, cfg["ma"]["mid"]).iloc[-1]
        long_ = ind.sma(index, cfg["ma"]["long"]).iloc[-1]
        result[sector] = {
            "count": len(codes),
            "change_pct": _num(returns[codes].iloc[-1].mean() * 100, 2),
            "downtrend": bool(index.iloc[-1] < mid < long_),
        }
    return result

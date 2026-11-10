"""テクニカル指標の計算。市場に依存しない。

どの関数も、古い日付 → 新しい日付の順に並んだ pandas.Series を受け取り、
同じ長さの Series（または DataFrame）を返す。データが足りない日は NaN になる。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, period: int) -> pd.Series:
    """単純移動平均。"""
    return close.rolling(period).mean()


def change_pct(close: pd.Series) -> pd.Series:
    """前日比（%）。"""
    return close.pct_change(fill_method=None) * 100


def deviation_pct(close: pd.Series, period: int) -> pd.Series:
    """移動平均線からの乖離率（%）。マイナスなら線より下。"""
    ma = sma(close, period)
    return (close - ma) / ma * 100


def bollinger(close: pd.Series, period: int, ddof: int = 0) -> pd.DataFrame:
    """ボリンジャーバンド。mid（中央線）と ±2σ・±3σ の線を返す。"""
    mid = sma(close, period)
    sd = close.rolling(period).std(ddof=ddof)
    return pd.DataFrame(
        {
            "mid": mid,
            "upper2": mid + 2 * sd,
            "lower2": mid - 2 * sd,
            "upper3": mid + 3 * sd,
            "lower3": mid - 3 * sd,
        }
    )


def _rci_window(values: np.ndarray) -> float:
    n = len(values)
    if np.isnan(values).any():
        return np.nan
    # 日付の順位: 最新が1位
    date_rank = np.arange(n, 0, -1)
    # 価格の順位: 高いほうが1位。同じ値は順位の平均を割り当てる
    higher = (values[None, :] > values[:, None]).sum(axis=1)
    same = (values[None, :] == values[:, None]).sum(axis=1)
    price_rank = 1 + higher + (same - 1) / 2
    d = ((date_rank - price_rank) ** 2).sum()
    return (1 - 6 * d / (n * (n**2 - 1))) * 100


def rci(close: pd.Series, period: int) -> pd.Series:
    """RCI（順位相関指数）。-100〜+100。上がり続けると+100、下がり続けると-100。"""
    return close.rolling(period).apply(_rci_window, raw=True)


def is_rising(series: pd.Series, lookback: int = 1) -> pd.Series:
    """lookback 日前より値が大きければ True（線が上向き）。"""
    return series > series.shift(lookback)

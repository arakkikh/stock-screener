import pandas as pd

from screener.config import load_thresholds


def cfg(market="jp"):
    return load_thresholds(market)


def make_df(close, open_=None, high=None, low=None):
    """テスト用の株価データを作る。省略した列は終値から自動で補う。"""
    close = pd.Series(close, dtype=float)
    open_ = close.shift(1).fillna(close) if open_ is None else pd.Series(open_, dtype=float)
    top = pd.concat([open_, close], axis=1).max(axis=1)
    bottom = pd.concat([open_, close], axis=1).min(axis=1)
    high = top if high is None else pd.Series(high, dtype=float)
    low = bottom if low is None else pd.Series(low, dtype=float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def candles(rows):
    """(始値, 高値, 安値, 終値) の並びからテスト用の株価データを作る。"""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], dtype=float)

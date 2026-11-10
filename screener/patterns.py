"""チャートの形（パターン）の検出。市場に依存しない。

df は open / high / low / close の列を持ち、古い日付 → 新しい日付の順に並んでいること。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def swing_lows(low: pd.Series, window: int) -> pd.Series:
    """谷（前後 window 日の中でいちばん安い日）に True を付ける。

    後ろ window 日分の値動きを見ないと谷かどうか決まらないので、
    直近 window 日は必ず False になる。
    """
    lowest_around = low.rolling(2 * window + 1, center=True).min()
    lowest_before = low.shift(1).rolling(window).min()
    return (low == lowest_around) & (low < lowest_before)


def swing_highs(high: pd.Series, window: int) -> pd.Series:
    """山（前後 window 日の中でいちばん高い日）に True を付ける。"""
    highest_around = high.rolling(2 * window + 1, center=True).max()
    highest_before = high.shift(1).rolling(window).max()
    return (high == highest_around) & (high > highest_before)


# ---------------------------------------------------------------- 安値圏・高値圏

def zone_position(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """過去の値幅の中での終値の位置（0 = 最安値, 100 = 最高値）。"""
    days = cfg["zone"]["lookback_days"]
    lowest = df["low"].rolling(days).min()
    highest = df["high"].rolling(days).max()
    width = (highest - lowest).where(highest > lowest)
    return (df["close"] - lowest) / width * 100


def in_low_zone(df: pd.DataFrame, cfg: dict) -> pd.Series:
    return zone_position(df, cfg) <= cfg["zone"]["low_pct"]


def in_high_zone(df: pd.DataFrame, cfg: dict) -> pd.Series:
    return zone_position(df, cfg) >= cfg["zone"]["high_pct"]


# ---------------------------------------------------------------- ローソク足の部品

def _body(df):
    return (df["close"] - df["open"]).abs()


def _body_top(df):
    return df[["open", "close"]].max(axis=1)


def _body_bottom(df):
    return df[["open", "close"]].min(axis=1)


def _bullish(df):
    return df["close"] > df["open"]


def _bearish(df):
    return df["close"] < df["open"]


def window_up(df: pd.DataFrame, min_pct: float) -> pd.Series:
    """窓を開けて上昇（当日の安値が前日の高値より上）。"""
    return df["low"] > df["high"].shift(1) * (1 + min_pct / 100)


def window_down(df: pd.DataFrame, min_pct: float) -> pd.Series:
    """窓を開けて下落（当日の高値が前日の安値より下）。"""
    return df["high"] < df["low"].shift(1) * (1 - min_pct / 100)


# ---------------------------------------------------------------- 1〜3本の形

def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """抱き線（陽線が前日の陰線の実体を包む）。"""
    prev = df.shift(1)
    return (
        _bearish(prev)
        & _bullish(df)
        & (df["open"] <= prev["close"])
        & (df["close"] >= prev["open"])
        & (_body(df) > _body(prev))
    )


def _harami(df: pd.DataFrame, cfg: dict, first_is_bullish: bool) -> pd.Series:
    prev = df.shift(1)
    first = _bullish(prev) if first_is_bullish else _bearish(prev)
    long_first = _body(prev) >= prev["open"] * cfg["candle"]["long_body_pct"] / 100
    inside = (_body_top(df) <= _body_top(prev)) & (_body_bottom(df) >= _body_bottom(prev))
    return first & long_first & inside & (_body(df) < _body(prev))


def bullish_harami(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """はらみ線（大きな陰線の実体の中に、翌日の実体が収まる）。"""
    return _harami(df, cfg, first_is_bullish=False)


def bearish_harami(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """はらみ線（大きな陽線の実体の中に、翌日の実体が収まる）。"""
    return _harami(df, cfg, first_is_bullish=True)


def doji(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """十字線（始値と終値がほぼ同じ）。"""
    width = df["high"] - df["low"]
    return (width > 0) & (_body(df) <= width * cfg["candle"]["doji_body_ratio"])


def hanging_man(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """首吊り線の形（長い下ひげ、上ひげはほとんどない）。高値圏かどうかは別に判定する。"""
    c = cfg["candle"]
    width = df["high"] - df["low"]
    lower = _body_bottom(df) - df["low"]
    upper = df["high"] - _body_top(df)
    return (
        (width > 0)
        & (_body(df) > 0)
        & (lower >= _body(df) * c["hanging_shadow_ratio"])
        & (upper <= width * c["hanging_upper_max_ratio"])
    )


def downside_gap_two_black(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """下放れ二本黒（窓を開けて下落し、陰線が2本続く）。2本目の日に True。"""
    w = cfg["candle"]["window_min_pct"]
    gap_yesterday = window_down(df, w).shift(1, fill_value=False)
    still_below = df["high"] < df["low"].shift(2)
    return gap_yesterday & _bearish(df.shift(1)) & _bearish(df) & still_below


def upside_gap_two_white(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """上放れ並び赤（窓を開けて上昇し、同じくらいの陽線が2本並ぶ）。2本目の日に True。"""
    c = cfg["candle"]
    prev = df.shift(1)
    gap_yesterday = window_up(df, c["window_min_pct"]).shift(1, fill_value=False)
    still_above = df["low"] > df["high"].shift(2)
    bodies = pd.concat([_body(df), _body(prev)], axis=1)
    similar = bodies.min(axis=1) >= bodies.max(axis=1) * c["similar_body_ratio"]
    return gap_yesterday & _bullish(prev) & _bullish(df) & still_above & similar


def gap_up(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """大きめの窓を開けて上昇した日。決算や悪材料の後かどうかは人が確認する。"""
    return window_up(df, cfg["gap_up"]["min_pct"])


# ---------------------------------------------------------------- アイランド

def _islands(far: np.ndarray, near: np.ndarray, cfg: dict) -> list:
    """底のアイランドを探す。far = 高値, near = 安値 を渡す。

    天井を探すときは符号を反転した (-安値, -高値) を渡す。
    """
    w = cfg["candle"]["window_min_pct"] / 100
    max_days = cfg["island"]["max_days"]
    n = len(far)
    found = []
    for start in range(1, n):
        edge = near[start - 1]  # 窓の手前の日の安値
        if not far[start] < edge - abs(edge) * w:
            continue  # 窓を開けて下落していない
        top = -np.inf
        for end in range(start, min(n - 1, start + max_days)):
            top = max(top, far[end])
            if top >= edge:
                break  # 窓を埋めたので小島ではない
            if near[end + 1] > top + abs(top) * w:
                found.append({"start": start, "end": end, "signal": end + 1})
                break
    return found


def island_bottoms(df: pd.DataFrame, cfg: dict) -> list:
    """アイランドボトム（窓を開けて下落 → 横ばい → 窓を開けて上昇）。

    戻り値の各要素は行番号の辞書: start〜end が小島、signal が窓を開けて上昇した日。
    """
    return _islands(df["high"].to_numpy(), df["low"].to_numpy(), cfg)


def island_tops(df: pd.DataFrame, cfg: dict) -> list:
    """アイランドリバーサル（天井）。窓を開けて上昇 → 横ばい → 窓を開けて下落。"""
    return _islands(-df["low"].to_numpy(), -df["high"].to_numpy(), cfg)


# ---------------------------------------------------------------- ダブル／トリプル

def _multi_bottoms(ext, opp, close, is_ext, cfg: dict) -> list:
    """ダブル／トリプルボトムのネックライン上抜けを探す。

    ext = 安値, opp = 高値, is_ext = 谷の位置。
    天井を探すときは符号を反転した値を渡す。
    """
    c = cfg["double"]
    window = cfg["swing"]["window"]
    tol = c["similar_pct"] / 100
    points = np.flatnonzero(is_ext)
    n = len(ext)
    found = []
    for j, last in enumerate(points):
        level = ext[last]
        chain = [last]  # 新しい底 → 古い底の順
        for prev in points[:j][::-1]:
            gap = chain[-1] - prev
            if gap > c["max_gap_days"]:
                break
            diff = (ext[prev] - level) / abs(level)
            if diff < -tol:
                break  # もっと深い谷がある → 同じ水準の底が並んだ形ではない
            if diff > tol or gap < c["min_gap_days"]:
                continue  # 浅すぎる谷・近すぎる谷は飛ばす
            chain.append(prev)
            if len(chain) == 3:
                break
        for count in (2, 3):
            if len(chain) < count:
                continue
            bottoms = chain[:count][::-1]
            neckline = opp[bottoms[0] + 1 : last].max()
            if (neckline - level) / abs(level) < c["min_depth_pct"] / 100:
                continue
            breakout = None
            for t in range(last + 1, min(n, last + 1 + c["max_breakout_days"])):
                if ext[t] < level:
                    break  # 底を割った
                if close[t] > neckline:
                    breakout = t
                    break
            if breakout is None:
                continue
            found.append(
                {
                    "count": count,
                    "points": [int(b) for b in bottoms],
                    "neckline": float(neckline),
                    "breakout": int(breakout),
                    # 最後の底が谷だと確定する前にはサインを出さない
                    "confirmed": int(max(breakout, last + window)),
                }
            )
    return found


def multi_bottoms(df: pd.DataFrame, cfg: dict) -> list:
    """ダブルボトム（count=2）・トリプルボトム（count=3）のネックライン上抜け。

    戻り値の各要素: points = 底の日, neckline = ネックラインの値段,
    breakout = 終値がネックラインを上抜けた日, confirmed = サインとして使える日
    """
    is_low = swing_lows(df["low"], cfg["swing"]["window"]).to_numpy()
    return _multi_bottoms(
        df["low"].to_numpy(), df["high"].to_numpy(), df["close"].to_numpy(), is_low, cfg
    )


def multi_tops(df: pd.DataFrame, cfg: dict) -> list:
    """ダブルトップ（count=2）・トリプルトップ（count=3）のネックライン割れ。"""
    is_high = swing_highs(df["high"], cfg["swing"]["window"]).to_numpy()
    found = _multi_bottoms(
        -df["high"].to_numpy(), -df["low"].to_numpy(), -df["close"].to_numpy(), is_high, cfg
    )
    for event in found:
        event["neckline"] = -event["neckline"]
    return found

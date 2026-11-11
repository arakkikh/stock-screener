"""順張りモード（ミネルヴィニ式）の判定。市場に依存しない。

df は open / high / low / close / volume の列を持ち、古い日付 → 新しい日付の順に並んでいること。
cfg は screener.config.load_thresholds() の戻り値（cfg["momentum"] を使う）。
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from . import indicators as ind
from . import patterns as pat

EPS = 1e-9


# ---------------------------------------------------------------- 相対強度（RS）

def rs_scores(closes: pd.DataFrame, cfg: dict) -> pd.Series:
    """銘柄ごとの強さの点数。期間ごとの騰落率に重みを掛けて合計する。

    closes は列が銘柄コード、行が日付の終値の表。
    必要な日数のデータがない銘柄は NaN になる。
    """
    rs = cfg["momentum"]["rs"]
    closes = closes.ffill()
    if len(closes) <= max(rs["periods"]):
        return pd.Series(np.nan, index=closes.columns)
    last = closes.iloc[-1]
    score = pd.Series(0.0, index=closes.columns)
    for days, weight in zip(rs["periods"], rs["weights"]):
        score = score + weight * (last / closes.iloc[-1 - days] - 1)
    return score


def rs_ratings(scores: pd.Series) -> pd.Series:
    """点数を、対象銘柄内の順位にもとづく 1〜99 の値に直す（99 がいちばん強い）。

    点数が NaN の銘柄は戻り値に含まれない。
    """
    valid = scores.dropna()
    if valid.empty:
        return pd.Series(dtype=int)
    percentile = valid.rank(pct=True, method="average")
    return (percentile * 99).map(math.ceil).clip(1, 99).astype(int)


# ---------------------------------------------------------------- トレンドテンプレート

def trend_template(df: pd.DataFrame, rs: Optional[float], cfg: dict) -> Optional[dict]:
    """トレンドテンプレートの8条件を、最新日について判定する。

    データが足りない銘柄（上場から1年未満など）は None を返す。
    戻り値: conds = 8条件の合否, count = 満たした数, passed = 全合格か, と判定に使った数値
    """
    m = cfg["momentum"]
    t, ma = m["template"], m["ma"]
    need = max(ma["slow"] + t["slow_rising_days"], t["year_days"])
    if len(df) < need:
        return None

    close = df["close"]
    price = close.iloc[-1]
    fast = ind.sma(close, ma["fast"]).iloc[-1]
    mid = ind.sma(close, ma["mid"]).iloc[-1]
    slow_line = ind.sma(close, ma["slow"])
    slow, slow_before = slow_line.iloc[-1], slow_line.iloc[-1 - t["slow_rising_days"]]
    year_low = df["low"].iloc[-t["year_days"] :].min()
    year_high = df["high"].iloc[-t["year_days"] :].max()
    from_low = (price / year_low - 1) * 100
    from_high = (price / year_high - 1) * 100

    conds = [
        bool(price > mid and price > slow),
        bool(mid > slow),
        bool(slow > slow_before),
        bool(fast > mid and fast > slow),
        bool(price > fast),
        bool(from_low >= t["above_low_pct"] - EPS),
        bool(from_high >= -t["within_high_pct"] - EPS),
        bool(rs is not None and not pd.isna(rs) and rs >= t["rs_min"]),
    ]
    return {
        "conds": conds,
        "count": sum(conds),
        "passed": all(conds),
        "ma_fast": float(fast),
        "ma_mid": float(mid),
        "ma_slow": float(slow),
        "year_low": float(year_low),
        "year_high": float(year_high),
        "from_low_pct": float(from_low),
        "from_high_pct": float(from_high),
    }


# ---------------------------------------------------------------- VCP

def find_vcp(df: pd.DataFrame, cfg: dict) -> Optional[dict]:
    """VCP（押しの深さが段階的に小さくなる形）を探す。見つからなければ None。

    戻り値（行番号は 0 始まり）:
      legs … 収縮の一覧。各要素は high_i / low_i（山と谷の日）, high / low（値段）,
              depth（押しの深さ %）, volume（その間の平均出来高）
      pivot / pivot_i … 最後の収縮の高値とその日
      status … "forming" = ピボットの手前 / "breakout" = 出来高を伴って上抜け /
               "weak" = 上抜けたが出来高が足りない /
               "failed" = 上抜けたあと、ピボット以下に押し戻された
      breakout_i … ピボットを終値で上抜けた日（なければ None）
      volume_ratio … 上抜けた日の出来高が、平均の何倍か
      volume_dry … 最後の収縮の出来高が、最初の収縮より少ないか
    """
    v = cfg["momentum"]["vcp"]
    n = len(df)
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    close, volume = df["close"].to_numpy(), df["volume"].to_numpy(dtype=float)
    start = max(0, n - v["lookback_days"])
    peaks = [int(i) for i in np.flatnonzero(pat.swing_highs(df["high"], v["swing_window"]).to_numpy()) if i >= start]
    if len(peaks) < v["min_contractions"]:
        return None

    pivot_i = peaks[-1]
    pivot = high[pivot_i]
    above = np.flatnonzero(close[pivot_i + 1 :] > pivot)
    breakout_i = int(pivot_i + 1 + above[0]) if len(above) else None
    if breakout_i is not None and breakout_i < n - v["breakout_recent_days"]:
        return None  # 上抜けてから日数がたった。もう買い場の形ではない

    last_day = breakout_i if breakout_i is not None else n - 1
    legs = []
    for j, peak in enumerate(peaks):
        end = peaks[j + 1] if j + 1 < len(peaks) else last_day
        if end <= peak:
            continue
        low_i = peak + 1 + int(low[peak + 1 : end + 1].argmin())
        depth = (high[peak] - low[low_i]) / high[peak] * 100
        is_last = j == len(peaks) - 1
        if depth < v["min_depth_pct"] and not is_last:
            continue  # 途中のごく浅い押しは数えない
        legs.append(
            {
                "high_i": peak,
                "low_i": low_i,
                "high": float(high[peak]),
                "low": float(low[low_i]),
                "depth": float(depth),
                "volume": float(volume[peak : low_i + 1].mean()),
            }
        )
    if not legs or legs[-1]["high_i"] != pivot_i:
        return None

    chosen = None
    for count in range(v["max_contractions"], v["min_contractions"] - 1, -1):
        if len(legs) < count:
            continue
        cand = legs[-count:]
        pairs = list(zip(cand, cand[1:]))
        shrinking = all(b["depth"] < a["depth"] * v["shrink_ratio"] for a, b in pairs)
        higher_lows = all(b["low"] > a["low"] for a, b in pairs)
        flat_highs = all(b["high"] <= a["high"] * (1 + v["max_high_rise_pct"] / 100) for a, b in pairs)
        within = cand[0]["depth"] <= v["max_first_depth_pct"] and cand[-1]["depth"] <= v["max_last_depth_pct"]
        dry = cand[-1]["volume"] < cand[0]["volume"]
        if shrinking and higher_lows and flat_highs and within and (dry or not v["require_volume_dry"]):
            chosen = cand
            break
    if chosen is None:
        return None

    status, ratio = "forming", None
    if breakout_i is not None:
        average = df["volume"].rolling(v["volume_avg_days"]).mean().shift(1).iloc[breakout_i]
        ratio = float(volume[breakout_i] / average) if average and not pd.isna(average) else None
        status = "breakout" if ratio is not None and ratio >= v["breakout_volume_ratio"] - EPS else "weak"
        if close[-1] <= pivot:
            status = "failed"  # 上抜けたあと、終値がピボット以下に押し戻された
    return {
        "legs": chosen,
        "pivot": float(pivot),
        "pivot_i": pivot_i,
        "status": status,
        "breakout_i": breakout_i,
        "volume_ratio": ratio,
        "volume_dry": bool(chosen[-1]["volume"] < chosen[0]["volume"]),
    }


# ---------------------------------------------------------------- 50日線割れ

def ma_break_with_volume(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """出来高を伴って50日線を割った日に True。

    条件: 前日は終値が50日線以上 / 当日は終値が50日線より下 /
          当日の出来高が、前日までの平均出来高の一定倍以上
    """
    m = cfg["momentum"]
    line = ind.sma(df["close"], m["ma"]["fast"])
    average = df["volume"].rolling(m["vcp"]["volume_avg_days"]).mean().shift(1)
    crossed = (df["close"] < line) & (df["close"].shift(1) >= line.shift(1))
    return crossed & (df["volume"] >= average * m["exit"]["ma_break_volume_ratio"] - EPS)

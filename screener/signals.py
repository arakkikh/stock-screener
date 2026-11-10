"""売買サインの判定。市場に依存しない（市場ごとの差は cfg の値だけ）。

df は open / high / low / close の列を持ち、古い日付 → 新しい日付の順に並んでいること。
cfg は screener.config.load_thresholds() の戻り値。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind
from . import patterns as pat
from .patterns import swing_lows

# 小数の計算誤差で「ちょうど -2.5%」が外れないようにするための余裕
EPS = 1e-9


def buy_conditions(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """買いの条件1〜4を日ごとに判定する。

    戻り値の列:
      change_pct / deviation_pct / rci … 判定に使った数値
      cond1〜cond4 … 各条件が点灯しているか
      bb_level … 0 = 未到達, 2 = -2σ到達, 3 = -3σ到達
      count … 点灯している条件の数（0〜4）
    """
    ma, buy = cfg["ma"], cfg["buy"]
    close = df["close"]
    bb = ind.bollinger(close, buy["bb_period"], buy["bb_ddof"])
    touch = df[buy["bb_touch"]]

    out = pd.DataFrame(index=df.index)
    out["change_pct"] = ind.change_pct(close)
    out["deviation_pct"] = ind.deviation_pct(close, ma["mid"])
    out["rci"] = ind.rci(close, buy["rci_period"])

    # 値動きがまったくない期間はバンドの幅がゼロになるので、到達とはみなさない
    has_width = bb["upper2"] > bb["lower2"]
    hit2 = has_width & (touch <= bb["lower2"] + EPS)
    hit3 = has_width & (touch <= bb["lower3"] + EPS)
    out["cond1"] = out["change_pct"] <= buy["drop_pct"] + EPS
    out["cond2"] = out["deviation_pct"] <= buy["ma_deviation_pct"] + EPS
    out["cond3"] = hit2
    out["cond4"] = out["rci"] <= buy["rci_max"] + EPS
    out["bb_level"] = np.where(hit3, 3, np.where(hit2, 2, 0))
    out["count"] = out[["cond1", "cond2", "cond3", "cond4"]].sum(axis=1)
    return out


def ma100_bounce(
    df: pd.DataFrame, ma_mid: pd.Series, ma_long: pd.Series, cfg: dict
) -> pd.Series:
    """25日線の下にいるが、100日線まで下げたところで反発した日に True。

    条件: 終値が25日線より下 / 直近数日のうちに安値が100日線へ接近 /
          終値は100日線より上 / 当日は陽線で、前日の終値より高い
    """
    c = cfg["ma100_bounce"]
    near = (df["low"] <= ma_long * (1 + c["near_pct"] / 100)).astype(float)
    touched = near.rolling(c["lookback_days"], min_periods=1).max() > 0
    rebound = (df["close"] > df["open"]) & (df["close"] > df["close"].shift(1))
    return (df["close"] < ma_mid) & touched & (df["close"] > ma_long) & rebound


def bb_divergences(df: pd.DataFrame, lower2: pd.Series, cfg: dict) -> list:
    """1番底が-2σを割り、2番底が-2σの内側で止まった形を探す。

    戻り値は見つかった形のリスト。各要素は行番号（0始まり）の辞書:
      first = 1番底の日, second = 2番底の日,
      confirmed = 2番底が谷だと確定した日（この日からサインとして使える）
    """
    c = cfg["bb_divergence"]
    window = cfg["swing"]["window"]
    low = df["low"].to_numpy()
    high = df["high"].to_numpy()
    band = lower2.to_numpy()
    bottoms = np.flatnonzero(swing_lows(df["low"], window).to_numpy())

    found = []
    for j, second in enumerate(bottoms):
        if not low[second] > band[second]:
            continue  # 2番底は-2σの内側
        for first in bottoms[:j][::-1]:
            gap = second - first
            if gap < c["min_gap_days"]:
                continue
            if gap > c["max_gap_days"]:
                break
            if not low[first] < band[first]:
                continue  # 1番底は-2σを割っている
            if high[first + 1 : second].max() < low[first] * (1 + c["min_rebound_pct"] / 100):
                continue  # 底と底の間でしっかり戻していない
            if low[second] > low[first] * (1 + c["retest_tolerance_pct"] / 100):
                continue  # 2番底が浅すぎる（1番底の水準を試していない）
            found.append(
                {"first": int(first), "second": int(second), "confirmed": int(second + window)}
            )
            break
    return found


def mark_days(events: list, index: pd.Index, key: str = "confirmed") -> pd.Series:
    """形のリストを「その日にサインが出たか」の True/False の列に直す。"""
    marks = pd.Series(False, index=index)
    for event in events:
        if event[key] < len(index):
            marks.iloc[event[key]] = True
    return marks


def _near_zone(zone: pd.Series) -> pd.Series:
    """当日か前日のどちらかが圏内なら True（反転の足そのもので圏外に出ることがあるため）。"""
    return zone | zone.shift(1, fill_value=False)


def _marks(events: list, index: pd.Index, key: str, count=None) -> pd.Series:
    chosen = [e for e in events if count is None or e["count"] == count]
    return mark_days(chosen, index, key)


def reversal_signs(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """反転の確認サインを日ごとに判定する（列ごとに True/False）。"""
    low_zone = _near_zone(pat.in_low_zone(df, cfg))
    bottoms = pat.multi_bottoms(df, cfg)
    out = pd.DataFrame(index=df.index)
    out["engulfing"] = pat.bullish_engulfing(df) & low_zone
    out["harami"] = pat.bullish_harami(df, cfg) & low_zone
    out["doji"] = pat.doji(df, cfg) & low_zone
    out["double_bottom"] = _marks(bottoms, df.index, "confirmed", count=2)
    out["triple_bottom"] = _marks(bottoms, df.index, "confirmed", count=3)
    out["island_bottom"] = mark_days(pat.island_bottoms(df, cfg), df.index, "signal")
    out["gap_up"] = pat.gap_up(df, cfg)
    return out


def warning_signs(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """警戒・売りサインを日ごとに判定する。two_black は「最優先で損切り」。"""
    high_zone = _near_zone(pat.in_high_zone(df, cfg))
    tops = pat.multi_tops(df, cfg)
    out = pd.DataFrame(index=df.index)
    out["hanging_man"] = pat.hanging_man(df, cfg) & high_zone
    out["harami_top"] = pat.bearish_harami(df, cfg) & high_zone
    out["double_top"] = _marks(tops, df.index, "confirmed", count=2)
    out["triple_top"] = _marks(tops, df.index, "confirmed", count=3)
    out["island_top"] = mark_days(pat.island_tops(df, cfg), df.index, "signal")
    out["two_black"] = pat.downside_gap_two_black(df, cfg)
    return out


def entry_candidates(buy: pd.DataFrame, reversal: pd.DataFrame, cfg: dict) -> pd.Series:
    """エントリー候補。買い条件の点灯から数日以内に、反転サインが出た日に True。

    買い条件が点灯しただけ、反転サインが出ただけ、では候補にしない。
    """
    c = cfg["entry"]
    lit = (buy["count"] >= c["min_conditions"]).astype(float)
    lit_recently = lit.rolling(c["lookback_days"], min_periods=1).max() > 0
    return lit_recently & reversal.any(axis=1)


def trend_state(
    high: pd.Series, ma_short: pd.Series, ma_mid: pd.Series, ma_long: pd.Series, cfg: dict
) -> pd.DataFrame:
    """トレンド継続モードの状態を日ごとに求める。

    戻り値の列:
      perfect_order … 5日 > 25日 > 100日線で、3本とも上向き（保有継続ゾーン）
      in_trend … 上昇トレンドが続いている（下の「トレンドの区切り」を参照）
      near … 5日線と25日線が接近している
      approach_count … 今のトレンドの中で、5日線が25日線に接近した回数
      exit_warning … 手仕舞い警戒（規定回数の接近。高値更新中なら出さない）
      warning_cleared … 規定回数に達したが、高値更新中のため警戒を解除している

    トレンドの区切り:
      始まり = パーフェクトオーダーになった日
      終わり = 5日線が25日線をはっきり下回った日（接近の幅を超えて下）、
               または25日線が100日線を下回った日
    接近は「いったん離れてから近づいた」ときだけ1回と数える。
    """
    t = cfg["trend"]
    near_pct, need = t["approach_pct"], t["exit_warning_count"]
    days = t["slope_days"]
    rising = ind.is_rising(ma_short, days) & ind.is_rising(ma_mid, days) & ind.is_rising(ma_long, days)
    perfect = ((ma_short > ma_mid) & (ma_mid > ma_long) & rising).to_numpy()
    gap = ((ma_short - ma_mid) / ma_mid * 100).to_numpy()
    mid, long_, highs = ma_mid.to_numpy(), ma_long.to_numpy(), high.to_numpy()

    rows = []
    in_trend = False
    for i in range(len(highs)):
        if in_trend and not (gap[i] > -near_pct and mid[i] >= long_[i]):
            in_trend = False
        if not in_trend and perfect[i]:
            in_trend = True
            count, separated = 0, False
            leg_high = -np.inf  # 直前の接近から今までの最高値
            last_peak = prev_peak = None  # 直近の上昇の高値 / その1つ前の上昇の高値
        if not in_trend:
            rows.append((False, False, 0, False, False))
            continue

        leg_high = max(leg_high, highs[i])
        near = abs(gap[i]) < near_pct
        if not near:
            separated = True
        elif separated:
            count += 1
            separated = False
            prev_peak, last_peak, leg_high = last_peak, leg_high, highs[i]

        reached = count >= need
        new_high = prev_peak is not None and max(last_peak, leg_high) > prev_peak
        rows.append((True, near, count, reached and not new_high, reached and new_high))

    out = pd.DataFrame(
        rows,
        index=high.index,
        columns=["in_trend", "near", "approach_count", "exit_warning", "warning_cleared"],
    )
    out.insert(0, "perfect_order", perfect)
    return out


def trend_mode(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """株価データからトレンド継続モードの状態を求める。two_white = 上放れ並び赤。"""
    ma = cfg["ma"]
    close = df["close"]
    out = trend_state(
        df["high"], ind.sma(close, ma["short"]), ind.sma(close, ma["mid"]), ind.sma(close, ma["long"]), cfg
    )
    out["two_white"] = pat.upside_gap_two_white(df, cfg)
    return out

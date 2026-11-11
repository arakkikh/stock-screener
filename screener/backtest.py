"""バックテスト（過去のデータでサインの成績を確かめる）の計算。市場に依存しない。

前提をそろえるための決まり:
  ・サインはその日の引け後に分かるので、買うのは翌営業日の始値
  ・売るのは終値
  ・手数料・税金・売買時の価格のずれは含めない
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import indicators as ind
from . import momentum as mo
from . import signals as sig


# ---------------------------------------------------------------- その後の値動き

def forward_returns(df: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    """サインが出た日ごとに、「翌日の始値で買い、h 営業日後の終値で売った」ときの騰落率(%)。

    列が保有日数 h。先のデータがまだない日は NaN。
    """
    entry = df["open"].shift(-1)
    return pd.DataFrame({h: (df["close"].shift(-h) / entry - 1) * 100 for h in horizons}, index=df.index)


def worst_drawdown(df: pd.DataFrame, horizon: int) -> pd.Series:
    """買ってから h 営業日のあいだに、買値から最大で何%下げたか（安値ベース。0以下の値）。"""
    entry = df["open"].shift(-1)
    lowest = df["low"][::-1].rolling(horizon).min()[::-1].shift(-1)  # 翌日から h 日間の最安値
    return ((lowest / entry - 1) * 100).clip(upper=0)


def summarize(values) -> Optional[dict]:
    """騰落率(%)の並びを、回数・勝率・平均・中央値などにまとめる。1件もなければ None。"""
    values = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    if len(values) == 0:
        return None
    return {
        "n": int(len(values)),
        "win": round(float((values > 0).mean() * 100), 1),
        "mean": round(float(values.mean()), 2),
        "median": round(float(np.median(values)), 2),
        "p10": round(float(np.percentile(values, 10)), 2),  # 悪いほうから1割の水準
        "worst": round(float(values.min()), 2),
    }


# ---------------------------------------------------------------- サインの一覧

def signal_flags(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """検証するサインを、日ごとの True/False の表にする（逆張りモード）。"""
    ma, b = cfg["ma"], cfg["buy"]
    close = df["close"]
    buy = sig.buy_conditions(df, cfg)
    reversal = sig.reversal_signs(df, cfg)
    warning = sig.warning_signs(df, cfg)
    trend = sig.trend_mode(df, cfg)
    bb = ind.bollinger(close, b["bb_period"], b["bb_ddof"])
    ma_mid, ma_long = ind.sma(close, ma["mid"]), ind.sma(close, ma["long"])

    out = pd.DataFrame(index=df.index)
    for i in (1, 2, 3, 4):
        out[f"cond{i}"] = buy[f"cond{i}"]
    out["bb3"] = buy["bb_level"] == 3
    for k in (1, 2, 3, 4):
        out[f"count{k}"] = buy["count"] >= k
    for column in reversal.columns:
        out[column] = reversal[column]
    out["entry"] = sig.entry_candidates(buy, reversal, cfg)
    out["bounce"] = sig.ma100_bounce(df, ma_mid, ma_long, cfg)
    out["divergence"] = sig.mark_days(sig.bb_divergences(df, bb["lower2"], cfg), df.index)
    for column in warning.columns:
        out[column] = warning[column]
    out["exit_warning"] = trend["exit_warning"] & ~trend["exit_warning"].shift(1, fill_value=False)
    out["two_white"] = trend["two_white"]
    return out.fillna(False).astype(bool)


# ---------------------------------------------------------------- 売買のシミュレーション

def simulate(
    df: pd.DataFrame,
    entries: pd.Series,
    take_dynamic: Optional[pd.Series] = None,
    take_fixed: Optional[pd.Series] = None,
    stop_pct: Optional[float] = None,
    stop_flag: Optional[pd.Series] = None,
    max_hold: int = 20,
) -> List[dict]:
    """出口ルールつきの売買を1銘柄について再現する。同時に持つのは1回分だけ。

    entries      … 買いサインの日（翌営業日の始値で買う）
    take_dynamic … 終値がこの線以上になったら利確（25日線のように日々動く水準）
    take_fixed   … サインの日の値を利確の水準として固定する（条件1の「−2.5%の水準」など）
    stop_pct     … 終値が買値からこの%以下になったら損切り（例: -8）
    stop_flag    … True の日に損切り（「−3σを終値で下抜け」など）
    max_hold     … この営業日数を持ったら手仕舞い

    戻り値は売買の一覧。entry_i / exit_i は行番号、ret は騰落率(%)、
    reason は "take" 利確 / "stop" 損切り / "time" 期限。
    データの終わりまでに決済できなかったものは含めない。
    """
    open_, close = df["open"].to_numpy(), df["close"].to_numpy()
    signal = entries.to_numpy(dtype=bool)
    dynamic = None if take_dynamic is None else take_dynamic.to_numpy(dtype=float)
    fixed = None if take_fixed is None else take_fixed.to_numpy(dtype=float)
    flag = None if stop_flag is None else stop_flag.to_numpy(dtype=bool)
    n = len(df)
    trades = []
    t = 0
    while t < n - 1:
        if not signal[t]:
            t += 1
            continue
        start = t + 1
        price = open_[start]
        target = fixed[t] if fixed is not None else None
        closed = None
        for j in range(start, n):
            change = (close[j] / price - 1) * 100
            if stop_pct is not None and change <= stop_pct + 1e-9:  # 計算誤差で「ちょうど −8%」が外れないように
                closed = (j, "stop")
            elif flag is not None and flag[j]:
                closed = (j, "stop")
            elif target is not None and not math.isnan(target) and close[j] >= target:
                closed = (j, "take")
            elif dynamic is not None and not math.isnan(dynamic[j]) and close[j] >= dynamic[j]:
                closed = (j, "take")
            elif j - start + 1 >= max_hold:
                closed = (j, "time")
            if closed:
                break
        if closed is None:
            break  # データの終わりまで決済できなかった
        j, reason = closed
        trades.append(
            {"entry_i": start, "exit_i": j, "ret": float((close[j] / price - 1) * 100), "reason": reason, "days": j - start + 1}
        )
        t = j + 1  # 決済した翌日から、次のサインを探す
    return trades


def summarize_trades(trades: List[dict]) -> Optional[dict]:
    """売買の一覧を、成績と決済理由の内訳にまとめる。"""
    stats = summarize([t["ret"] for t in trades])
    if stats is None:
        return None
    n = len(trades)
    stats["days"] = round(sum(t["days"] for t in trades) / n, 1)
    for reason in ("take", "stop", "time"):
        stats[reason] = round(sum(1 for t in trades if t["reason"] == reason) / n * 100, 1)
    return stats


# ---------------------------------------------------------------- 順張り（過去の全日程）

def template_history(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """トレンドテンプレートに全条件合格していたかを、過去の全営業日について求める。

    close / high / low は、列が銘柄コード、行が日付の表。
    最新日の結果は momentum.trend_template（毎日の判定に使うもの）と一致する。
    """
    m = cfg["momentum"]
    t, ma, rs = m["template"], m["ma"], m["rs"]
    close = close.ffill()
    fast = close.rolling(ma["fast"]).mean()
    mid = close.rolling(ma["mid"]).mean()
    slow = close.rolling(ma["slow"]).mean()
    year_low = low.rolling(t["year_days"]).min()
    year_high = high.rolling(t["year_days"]).max()

    score = sum(w * (close / close.shift(n) - 1) for n, w in zip(rs["periods"], rs["weights"]))
    rating = np.ceil(score.rank(axis=1, pct=True) * 99).clip(1, 99)

    eps = mo.EPS
    passed = (
        (close > mid) & (close > slow)
        & (mid > slow)
        & (slow > slow.shift(t["slow_rising_days"]))
        & (fast > mid) & (fast > slow)
        & (close > fast)
        & ((close / year_low - 1) * 100 >= t["above_low_pct"] - eps)
        & ((close / year_high - 1) * 100 >= -t["within_high_pct"] - eps)
        & (rating >= t["rs_min"])
    )
    return passed.fillna(False)


def vcp_breakout_days(df: pd.DataFrame, passed: pd.Series, cfg: dict, window: int = 320) -> pd.DataFrame:
    """VCPのピボットを上抜けた日を、過去にさかのぼって探す。

    その日までのデータだけで判定する（先のデータは使わない）。
    戻り値の列: breakout = 出来高を伴う上抜け, weak = 出来高不足の上抜け
    """
    close = df["close"].to_numpy()
    flags = passed.reindex(df.index, fill_value=False).to_numpy(dtype=bool)
    strong = np.zeros(len(df), dtype=bool)
    weak = np.zeros(len(df), dtype=bool)
    for t in range(1, len(df)):
        # ピボットを初めて上抜けた日は、必ず前日より終値が高い。それ以外の日は調べなくてよい
        if not flags[t] or not close[t] > close[t - 1]:
            continue
        part = df.iloc[max(0, t - window + 1) : t + 1]
        found = mo.find_vcp(part, cfg)
        if found is None or found["breakout_i"] != len(part) - 1:
            continue
        if found["status"] == "breakout":
            strong[t] = True
        elif found["status"] == "weak":
            weak[t] = True
    return pd.DataFrame({"breakout": strong, "weak": weak}, index=df.index)


# ---------------------------------------------------------------- 銘柄ごとの RCI の水準

def rci_level_study(df: pd.DataFrame, levels: List[float], cfg: dict, horizon: int, min_samples: int) -> dict:
    """RCI がどの水準まで下がったときに買うと、その後の成績が良かったかを銘柄ごとに調べる。

    「その水準以下に入った最初の日」をサインとして数える。
    best は、回数が min_samples 以上ある水準の中で平均がいちばん高かったもの（なければ None）。
    """
    rci = ind.rci(df["close"], cfg["buy"]["rci_period"])
    returns = forward_returns(df, [horizon])[horizon]
    by_level = {}
    for level in levels:
        below = rci <= level
        first_day = below & ~below.shift(1, fill_value=False)
        by_level[level] = summarize(returns[first_day])
    usable = {lv: s for lv, s in by_level.items() if s and s["n"] >= min_samples}
    best = max(usable, key=lambda lv: usable[lv]["mean"]) if usable else None
    return {"levels": by_level, "best": best}

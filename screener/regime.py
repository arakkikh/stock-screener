"""相場環境の判定（逆張り向き／順張り向き／様子見）。市場に依存しない。

材料は、対象銘柄（順張りモードの約500銘柄）の株価と、基準指数・VIX（あれば）。
  ・25日線より上にある銘柄の割合、200日線より上にある銘柄の割合
  ・52週高値／52週安値を更新した銘柄数
  ・指数と25日・100日・200日線の位置関係と向き
過去の全営業日について同じ計算をするので、推移グラフやバックテストの環境別集計にも使える。
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

LABELS = ("contrarian", "momentum", "wait")  # 逆張り向き / 順張り向き / 様子見


def breadth(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """日ごとの「騰落の広がり」。close / high / low は、列が銘柄、行が日付の表。

    p_short / p_long … 25日線／200日線より上にある銘柄の割合(%)。線を引けるだけの日数がある銘柄で数える
    highs / lows     … その日に52週高値／安値を更新した銘柄数（前日までの1年間の高値を上回った・安値を下回った）
    n                … 200日線を引ける銘柄数（少なすぎる日は割合を出さない）
    """
    r = cfg["regime"]
    ma_s = close.rolling(r["ma"]["short"]).mean()
    ma_l = close.rolling(r["ma"]["long"]).mean()
    ok_s, ok_l = ma_s.notna() & close.notna(), ma_l.notna() & close.notna()
    n_s, n_l = ok_s.sum(axis=1), ok_l.sum(axis=1)
    p_short = ((close > ma_s) & ok_s).sum(axis=1) / n_s.where(n_s > 0) * 100
    p_long = ((close > ma_l) & ok_l).sum(axis=1) / n_l.where(n_l > 0) * 100

    year = r["year_days"]
    prev_high = high.rolling(year - 1, min_periods=year - 1).max().shift(1)
    prev_low = low.rolling(year - 1, min_periods=year - 1).min().shift(1)
    out = pd.DataFrame({
        "p_short": p_short,
        "p_long": p_long,
        "highs": (high > prev_high).sum(axis=1),
        "lows": (low < prev_low).sum(axis=1),
        "n": n_l,
    })
    enough = out["n"] >= r["min_stocks"]
    out.loc[~enough, ["p_short", "p_long"]] = np.nan
    out.loc[prev_high.notna().sum(axis=1) < r["min_stocks"], ["highs", "lows"]] = np.nan
    return out


def index_lines(index_close: pd.Series, cfg: dict) -> pd.DataFrame:
    """指数と25日・100日・200日線。rising_* は「slope_days 前より線が高い」（上向き）。"""
    r = cfg["regime"]
    out = pd.DataFrame({"close": index_close})
    for key in ("short", "mid", "long"):
        line = index_close.rolling(r["ma"][key]).mean()
        out[f"ma_{key}"] = line
        out[f"rising_{key}"] = line > line.shift(r["slope_days"][key])
    return out


def confirm(raw: pd.Series, days: int) -> pd.Series:
    """判定が days 日続いてから切り替える（毎日ころころ変わらないように）。空の日は前の判定を引き継ぐ。"""
    state, candidate, run = None, None, 0
    result = []
    for value in raw.to_numpy():
        if value is None or (isinstance(value, float) and np.isnan(value)):
            result.append(state)
            continue
        if state is None:
            state = value
        elif value == state:
            candidate, run = None, 0
        else:
            run = run + 1 if value == candidate else 1
            candidate = value
            if run >= days:
                state, candidate, run = value, None, 0
        result.append(state)
    return pd.Series(result, index=raw.index, dtype=object)


def classify(b: pd.DataFrame, index_close: pd.Series, vix: Optional[pd.Series], cfg: dict) -> pd.DataFrame:
    """日ごとに相場環境を判定する。

    逆張り向き … 売られすぎ: 25日線より上の銘柄が oversold_pct 以下、または VIX が vix_high 超
    順張り向き … 指数が200日線より上で200日線が上向き、かつ200日線より上の銘柄が uptrend_pct 以上
    様子見     … それ以外。reason で「下降トレンドで反転の兆しなし（downtrend）」と「方向感なし（flat）」を分ける
    反転の兆し … 指数が25日線より上、または52週安値の更新数（5日平均）が5日前より減っている
    判定は confirm_days 日続いてから切り替える（raw は毎日の判定そのもの）。
    """
    r = cfg["regime"]
    lines = index_lines(index_close, cfg).reindex(b.index)
    df = b.join(lines)
    df["vix"] = vix.reindex(b.index).ffill() if vix is not None else np.nan
    lows_avg = df["lows"].rolling(5).mean()
    df["lows_avg"] = lows_avg

    oversold = (df["p_short"] <= r["oversold_pct"]) | (df["vix"] > r["vix_high"])
    uptrend = (df["close"] > df["ma_long"]) & df["rising_long"] & (df["p_long"] >= r["uptrend_pct"])
    downtrend = (df["close"] < df["ma_long"]) & ~df["rising_long"]
    reversal = (df["close"] > df["ma_short"]) | (lows_avg < lows_avg.shift(r["reversal_compare_days"]))
    known = df["p_short"].notna() & df["p_long"].notna() & df["ma_long"].notna()

    raw = np.select([oversold, uptrend], ["contrarian", "momentum"], "wait").astype(object)
    reason = np.select([oversold, uptrend, downtrend & ~reversal], ["oversold", "uptrend", "downtrend"], "flat").astype(object)
    raw[~known.to_numpy()] = None
    reason[~known.to_numpy()] = None
    df["raw"], df["reason"] = raw, reason
    df["regime"] = confirm(df["raw"], r["confirm_days"])
    df["oversold"], df["uptrend"], df["downtrend"], df["reversal"] = oversold, uptrend, downtrend, reversal
    return df


def compute(frames: Dict[str, pd.DataFrame], index_df: pd.DataFrame, vix_df: Optional[pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """銘柄ごとの日足（frames）と指数・VIX の日足から、日ごとの判定表を作る。指数のある日だけを使う。"""
    close = pd.DataFrame({c: f["close"] for c, f in frames.items()})
    high = pd.DataFrame({c: f["high"] for c, f in frames.items()})
    low = pd.DataFrame({c: f["low"] for c, f in frames.items()})
    days = index_df.index
    b = breadth(close.reindex(days), high.reindex(days), low.reindex(days), cfg)
    return classify(b, index_df["close"], vix_df["close"] if vix_df is not None else None, cfg)


def since(df: pd.DataFrame) -> Optional[str]:
    """今の判定になった日（判定の続いている最初の日）。"""
    regime = df["regime"].dropna()
    if regime.empty:
        return None
    changed = regime.ne(regime.shift())
    return regime.index[changed.to_numpy().nonzero()[0][-1]].strftime("%Y-%m-%d")


def _num(value, digits=1):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def payload(df: pd.DataFrame, cfg: dict, as_of: str, generated_at: str) -> dict:
    """画面用の JSON。最新日の判定と根拠、推移グラフ用の履歴（直近 history_days 営業日）。"""
    df = df[df["regime"].notna()]
    last = df.iloc[-1]
    part = df.iloc[-cfg["regime"]["history_days"]:]
    col = lambda name, digits=1: [_num(v, digits) for v in part[name].to_numpy()]
    return {
        "as_of": as_of,
        "generated_at": generated_at,
        "config": cfg["regime"],
        "latest": {
            "date": df.index[-1].strftime("%Y-%m-%d"),
            "regime": last["regime"],
            "raw": last["raw"],
            "reason": last["reason"],
            "since": since(df),
            "p_short": _num(last["p_short"]),
            "p_long": _num(last["p_long"]),
            "highs": None if pd.isna(last["highs"]) else int(last["highs"]),
            "lows": None if pd.isna(last["lows"]) else int(last["lows"]),
            "n": int(last["n"]),
            "close": _num(last["close"], 2),
            **{f"ma_{k}": _num(last[f"ma_{k}"], 2) for k in ("short", "mid", "long")},
            **{f"rising_{k}": bool(last[f"rising_{k}"]) for k in ("short", "mid", "long")},
            "vix": _num(last["vix"], 2),
            "oversold": bool(last["oversold"]),
            "uptrend": bool(last["uptrend"]),
            "downtrend": bool(last["downtrend"]),
            "reversal": bool(last["reversal"]),
        },
        "history": {
            "t": [d.strftime("%Y-%m-%d") for d in part.index],
            "p_short": col("p_short"),
            "p_long": col("p_long"),
            "highs": col("highs", 0),
            "lows": col("lows", 0),
            "close": col("close", 2),
            "ma_long": col("ma_long", 2),
            "vix": col("vix", 2),
            "regime": list(part["regime"]),
        },
    }


def by_date(df: pd.DataFrame) -> Dict[str, str]:
    """{日付: 判定} の対応表（シグナル追跡の履歴に環境を書き込むのに使う）。"""
    regime = df["regime"].dropna()
    return {d.strftime("%Y-%m-%d"): v for d, v in regime.items()}

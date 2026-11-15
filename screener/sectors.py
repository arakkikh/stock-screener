"""セクター・テーマの強弱ランキング。市場に依存しない。

順張りモードの対象銘柄（約500銘柄）を、セクターとテーマごとにまとめ、
等金額で平均した値動き（グループ指数）を作って比べる。
  ・1週間・1か月・3か月の騰落率と、基準指数との差（相対的な強さ）
  ・相対的な強さの順位と、rank_change_days 営業日前の順位からの変化
  ・25日線より上にある銘柄の割合
  ・下落トレンド（グループ指数が25日線より下、かつ25日線が100日線より下。逆張りの「見るだけ」と同じ基準）
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def group_index(closes: pd.DataFrame) -> pd.Series:
    """銘柄の終値の表（列が銘柄）から、日々の騰落率を等金額で平均した指数を作る（最初の日 = 1）。"""
    returns = closes.pct_change(fill_method=None)
    return (1 + returns.mean(axis=1).fillna(0)).cumprod()


def _ret(series: pd.Series, days: int, end: int) -> Optional[float]:
    """end 行目（負の数は後ろから）までの days 営業日の騰落率(%)。"""
    n = len(series)
    e = n + end if end < 0 else end
    s = e - days
    if s < 0 or e >= n or e < 0:
        return None
    a, b = series.iloc[s], series.iloc[e]
    return None if pd.isna(a) or pd.isna(b) or a == 0 else float((b / a - 1) * 100)


def _score(x: Dict[int, Optional[float]], periods: List[int], weights: List[float]) -> Optional[float]:
    """期間ごとの「指数との差」を重み付きで平均する。1つでも欠けていれば None。"""
    values = [x.get(p) for p in periods]
    if any(v is None for v in values):
        return None
    return float(np.average(values, weights=weights))


def _ranks(scores: Dict[str, Optional[float]]) -> Dict[str, int]:
    """点数の高い順に 1, 2, … の順位（点数がないものは順位なし）。"""
    order = sorted((name for name, s in scores.items() if s is not None), key=lambda n: -scores[n])
    return {name: i + 1 for i, name in enumerate(order)}


def strength(closes: pd.DataFrame, groups: Dict[str, List[str]], index_close: pd.Series, cfg: dict,
             ref: Optional[Dict[str, pd.Series]] = None) -> List[dict]:
    """グループ（セクターまたはテーマ）ごとの強弱。順位の高い順に並べて返す。

    closes = 銘柄の終値の表（行は日付、列は銘柄）、groups = {グループ名: [銘柄コード]}
    ref    = {グループ名: 参考の値動き}（米国株のセクターETFなど。あれば同じ計算をして並べる）
    銘柄が min_stocks 未満のグループは few=True（参考値）とし、「強い」には数えない。
    """
    s = cfg["sectors"]
    periods, weights, back = s["periods"], s["rank_weights"], s["rank_change_days"]
    index_close = index_close.reindex(closes.index).ffill()
    ma_mid, ma_long = cfg["ma"]["mid"], cfg["ma"]["long"]
    rows = {}
    for name, codes in groups.items():
        codes = [c for c in codes if c in closes.columns]
        if not codes:
            continue
        part = closes[codes]
        gi = group_index(part)
        x_now, x_prev, r_now = {}, {}, {}
        for p in periods:
            r_now[p] = _ret(gi, p, -1)
            ix = _ret(index_close, p, -1)
            x_now[p] = None if r_now[p] is None or ix is None else r_now[p] - ix
            rp, ixp = _ret(gi, p, -1 - back), _ret(index_close, p, -1 - back)
            x_prev[p] = None if rp is None or ixp is None else rp - ixp
        ma_s = part.rolling(cfg["regime"]["ma"]["short"]).mean().iloc[-1]
        last = part.iloc[-1]
        ok = ma_s.notna() & last.notna()
        mid, long_ = gi.rolling(ma_mid).mean().iloc[-1], gi.rolling(ma_long).mean().iloc[-1]
        row = {
            "name": name,
            "count": len(codes),
            "few": len(codes) < s["min_stocks"],
            "r": {str(p): _round(r_now[p]) for p in periods},
            "x": {str(p): _round(x_now[p]) for p in periods},
            "score": _round(_score(x_now, periods, weights)),
            "_prev": _score(x_prev, periods, weights),
            "p_above": _round(float((last[ok] > ma_s[ok]).mean() * 100)) if ok.any() else None,
            "downtrend": bool(gi.iloc[-1] < mid < long_) if not (pd.isna(mid) or pd.isna(long_)) else False,
        }
        if ref and name in ref and ref[name] is not None:
            series = ref[name]["close"].reindex(closes.index).ffill()
            rr = {p: _ret(series, p, -1) for p in periods}
            row["ref"] = {
                "ticker": ref[name].attrs.get("ticker"),
                "r": {str(p): _round(rr[p]) for p in periods},
                "x": {str(p): _round(None if rr[p] is None or _ret(index_close, p, -1) is None else rr[p] - _ret(index_close, p, -1)) for p in periods},
            }
        rows[name] = row

    now = _ranks({n: r["score"] for n, r in rows.items()})
    prev = _ranks({n: r["_prev"] for n, r in rows.items()})
    eligible = [n for n in now if not rows[n]["few"]]
    strong_n = int(np.ceil(len(eligible) * s["strong_top_pct"] / 100)) if eligible else 0
    strong = set(sorted(eligible, key=lambda n: now[n])[:strong_n])
    out = []
    for name, row in rows.items():
        row.pop("_prev")
        row["rank"], row["rank_prev"] = now.get(name), prev.get(name)
        move = None if row["rank"] is None or row["rank_prev"] is None else row["rank_prev"] - row["rank"]
        row["move"] = move
        row["trend"] = None if move is None else "up" if move >= s["rank_change_min"] else "down" if move <= -s["rank_change_min"] else "flat"
        row["strong"] = name in strong
        out.append(row)
    return sorted(out, key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))


def _round(value, digits: int = 2):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def groups_from_universe(universe: pd.DataFrame) -> Dict[str, Dict[str, List[str]]]:
    """銘柄リスト（code・sector・themes 列）から、セクターとテーマのグループを作る。"""
    sectors: Dict[str, List[str]] = {}
    themes: Dict[str, List[str]] = {}
    for row in universe.itertuples(index=False):
        sectors.setdefault(row.sector, []).append(row.code)
        for theme in [t for t in str(row.themes).split("|") if t]:
            themes.setdefault(theme, []).append(row.code)
    return {"sectors": sectors, "themes": themes}


def index_returns(index_close: pd.Series, cfg: dict) -> Dict[str, Optional[float]]:
    return {str(p): _round(_ret(index_close, p, -1)) for p in cfg["sectors"]["periods"]}

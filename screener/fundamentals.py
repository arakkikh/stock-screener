"""ファンダ分析（5軸 × 6項目）の採点。市場に依存しない。

facts（markets/fundamentals.py が返す財務データ）と株価から指標を計算し、
対象銘柄全体の中央値などと比べて、項目ごとに 合格 / 不合格 / 判定不可 を決める。
"""
from __future__ import annotations

import datetime as dt
from statistics import median
from typing import Dict, List, Optional

import numpy as np

AXES = ["value", "growth", "past", "health", "dividend"]
CHECKS = {
    "value": ["per_vs_market", "per_vs_sector", "pbr_vs_market", "peg", "ev_ebitda_vs_market", "fcf_yield"],
    "growth": ["eps_growth_positive", "eps_growth_high", "eps_growth_vs_market",
               "rev_growth_high", "rev_growth_vs_market", "growth_both_years"],
    "past": ["eps_cagr_positive", "eps_accelerating", "roe", "roa", "margin_improved", "cash_backed"],
    "health": ["current_ratio", "debt_to_equity", "debt_reduced", "ocf_to_debt", "interest_cover", "equity_ratio"],
    "dividend": ["yield_notable", "yield_high", "payout", "fcf_cover", "stable", "growing"],
}


def _div(a, b) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pct(value) -> Optional[float]:
    return None if value is None else value * 100


# ---------------------------------------------------------------- 指標の計算

def metrics(facts: dict, price: Optional[float], cfg: dict, today: dt.date, financial: bool = False) -> dict:
    """1銘柄の指標を計算する。計算できないものは None。割合は % で返す。"""
    f = cfg["fundamentals"]
    price = price or facts.get("price")
    annual = facts.get("annual") or []
    latest = annual[0] if annual else {}
    est = facts.get("est") or {}
    currencies = (facts.get("currency"), facts.get("price_currency"))
    # 決算の通貨と株価の通貨が違う銘柄は、時価総額と決算の金額を比べられない
    same_currency = None in currencies or currencies[0] == currencies[1]

    eps, bvps, shares = facts.get("eps"), facts.get("bvps"), facts.get("shares")
    market_cap = price * shares if price and shares else None
    loss = eps is not None and eps <= 0
    per = price / eps if price and eps and eps > 0 else None
    pbr = price / bvps if price and bvps and bvps > 0 else None

    eps_g0, eps_g1 = _pct(est.get("eps_growth_0y")), _pct(est.get("eps_growth_1y"))
    rev_g0, rev_g1 = _pct(est.get("rev_growth_0y")), _pct(est.get("rev_growth_1y"))
    eps_g_next = eps_g1 if eps_g1 is not None else eps_g0
    rev_g_next = rev_g1 if rev_g1 is not None else rev_g0
    peg = per / eps_g_next if per and eps_g_next and eps_g_next > 0 else None

    ev_ebitda = fcf_yield = None
    if same_currency and market_cap:
        ebitda = facts.get("ebitda")
        if ebitda and ebitda > 0:
            ev_ebitda = (market_cap + (facts.get("total_debt") or 0) - (facts.get("total_cash") or 0)) / ebitda
        # フリーキャッシュフローは年次決算の値を使う（直近値は欠けや不自然な値が多い）
        fcf = latest.get("fcf") if latest.get("fcf") is not None else facts.get("fcf")
        fcf_yield = _pct(_div(fcf, market_cap))

    # ---- 過去実績 ----
    eps_history = [y.get("eps") for y in annual]
    span = min(f["past"]["cagr_years"], len(eps_history) - 1)
    eps_cagr = None
    if span >= 2 and eps_history[0] and eps_history[span] and eps_history[0] > 0 and eps_history[span] > 0:
        eps_cagr = ((eps_history[0] / eps_history[span]) ** (1 / span) - 1) * 100
    eps_g_last = None
    if len(eps_history) >= 2 and eps_history[0] is not None and eps_history[1] and eps_history[1] > 0:
        eps_g_last = (eps_history[0] / eps_history[1] - 1) * 100
    margins = [_pct(_div(y.get("net_income"), y.get("revenue"))) for y in annual[:2]]
    margins += [None] * (2 - len(margins))

    # ---- 財務健全性 ----
    def debt_ratio(year: dict) -> Optional[float]:
        equity, debt = year.get("equity"), year.get("debt")
        if equity is None or equity <= 0:
            return None
        return (debt or 0) / equity if "debt" in year else None

    debt = latest.get("debt")
    no_debt = bool(annual) and (debt is None or debt == 0) and "debt" in latest and latest.get("equity") is not None
    interest = latest.get("interest")
    cover = _div(latest.get("ebit"), abs(interest)) if interest else None

    # ---- 配当 ----
    by_year = {int(y): v for y, v in (facts.get("div_by_year") or {}).items()}
    last_full = today.year - 1
    years = f["dividend"]["stable_years"]
    history = [by_year.get(y) for y in range(last_full - years, last_full + 1)]
    full_history = all(v is not None and v > 0 for v in history)
    # 1株配当は、実際の支払い履歴（直近12か月）から求める。
    # 履歴の合計がないデータでは、今年の支払い済みの額と昨年の額の大きいほうで代用する
    div_rate = facts.get("div_ttm")
    if div_rate is None:
        div_rate = max(by_year.get(today.year) or 0, by_year.get(last_full) or 0) or facts.get("div_rate")
    payer = bool(div_rate and div_rate > 0)

    # ROE・ROA が取れていない銘柄は、年次決算から計算する
    roe = _pct(facts.get("roe"))
    roa = _pct(facts.get("roa"))
    if roe is None and latest.get("equity") and latest["equity"] > 0:
        roe = _pct(_div(latest.get("net_income"), latest["equity"]))
    if roa is None:
        roa = _pct(_div(latest.get("net_income"), latest.get("assets")))
    paid = latest.get("dividends_paid")

    return {
        "financial": financial,
        "loss": loss,
        "per": per,
        "pbr": pbr,
        "negative_equity": bvps is not None and bvps <= 0,
        "peg": peg,
        "ev_ebitda": ev_ebitda,
        "fcf_yield": fcf_yield,
        "eps_g0": eps_g0,
        "eps_g1": eps_g1,
        "eps_g_next": eps_g_next,
        "rev_g_next": rev_g_next,
        "analysts": est.get("analysts"),
        "eps_cagr": eps_cagr,
        "eps_g_last": eps_g_last,
        "roe": roe,
        "roa": roa,
        "margin": margins[0],
        "margin_prev": margins[1],
        "ocf": latest.get("ocf"),
        "net_income": latest.get("net_income"),
        "current_ratio": _div(latest.get("cur_assets"), latest.get("cur_liab")),
        "de": debt_ratio(latest) if annual else None,
        "de_old": debt_ratio(annual[-1]) if len(annual) >= 3 else None,
        "no_debt": no_debt,
        "ocf_to_debt": _div(latest.get("ocf"), debt) if debt else None,
        "interest_cover": cover,
        "equity_ratio": _pct(_div(latest.get("equity"), latest.get("assets"))),
        "payer": payer,
        "div_yield": (div_rate / price * 100 if div_rate and price else 0.0) if payer else 0.0,
        "payout": _pct(facts.get("payout")),
        "div_paid": abs(paid) if paid is not None else None,
        "fcf_annual": latest.get("fcf"),
        "div_full_history": full_history,
        # 1% 未満の減少は端数とみなして減配に数えない
        "div_stable": full_history and all(b >= a * 0.99 for a, b in zip(history, history[1:])),
        "div_growing": full_history and history[-1] > history[0],
    }


# ---------------------------------------------------------------- 対象銘柄全体の基準

def _median(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return float(median(values)) if values else None


def universe_stats(all_metrics: Dict[str, dict], sectors: Dict[str, str], cfg: dict) -> dict:
    """比べる相手になる数値（中央値や配当利回りの水準）を、対象銘柄全体から求める。"""
    f = cfg["fundamentals"]
    rows = list(all_metrics.values())
    by_sector: Dict[str, List[float]] = {}
    for code, m in all_metrics.items():
        if m["per"] is not None:
            by_sector.setdefault(sectors.get(code, ""), []).append(m["per"])
    yields = [m["div_yield"] for m in rows if m["payer"] and m["div_yield"]]
    quantile = lambda q: float(np.percentile(yields, q)) if yields else None  # noqa: E731
    return {
        "per": _median(m["per"] for m in rows),
        "pbr": _median(m["pbr"] for m in rows),
        "ev_ebitda": _median(m["ev_ebitda"] for m in rows),
        "eps_growth": _median(m["eps_g_next"] for m in rows),
        "rev_growth": _median(m["rev_g_next"] for m in rows),
        "sector_per": {s: float(median(v)) for s, v in by_sector.items() if len(v) >= f["sector_min_stocks"]},
        "yield_low": quantile(f["dividend"]["low_quantile"]),
        "yield_high": quantile(f["dividend"]["high_quantile"]),
    }


# ---------------------------------------------------------------- 採点

def _below(value, limit):
    return None if value is None or limit is None else value < limit


def _above(value, limit):
    return None if value is None or limit is None else value > limit


def _at_least(value, limit):
    return None if value is None or limit is None else value >= limit


def checks(m: dict, stats: dict, sector: str, cfg: dict) -> Dict[str, list]:
    """項目ごとの判定。True = 合格, False = 不合格, None = 判定不可（データなし・対象外）。"""
    f = cfg["fundamentals"]
    v, g, p, h, d = f["value"], f["growth"], f["past"], f["health"], f["dividend"]
    loss, fin = m["loss"], m["financial"]

    value = [
        False if loss else _below(m["per"], stats["per"]),
        False if loss else _below(m["per"], stats["sector_per"].get(sector)),
        False if m["negative_equity"] else _below(m["pbr"], stats["pbr"]),
        False if loss or (m["eps_g_next"] is not None and m["eps_g_next"] <= 0) else _below(m["peg"], v["peg_max"]),
        # 銀行・保険などは、事業の利益やキャッシュフローの形が一般の会社と違うので判定しない
        None if fin else _below(m["ev_ebitda"], stats["ev_ebitda"]),
        None if fin else _at_least(m["fcf_yield"], v["fcf_yield_min_pct"]),
    ]
    both = None if m["eps_g0"] is None or m["eps_g1"] is None else (m["eps_g0"] > 0 and m["eps_g1"] > 0)
    growth = [
        _above(m["eps_g_next"], 0),
        _at_least(m["eps_g_next"], g["eps_growth_min_pct"]),
        _above(m["eps_g_next"], stats["eps_growth"]),
        _at_least(m["rev_g_next"], g["revenue_growth_min_pct"]),
        _above(m["rev_g_next"], stats["rev_growth"]),
        both,
    ]
    past = [
        _above(m["eps_cagr"], 0),
        _above(m["eps_g_last"], m["eps_cagr"]),
        _at_least(m["roe"], p["roe_min_pct"]),
        _at_least(m["roa"], p["roa_min_pct"]),
        _above(m["margin"], m["margin_prev"]),
        None if fin else _at_least(m["ocf"], m["net_income"]),
    ]
    if fin:
        # 銀行・保険などは負債の意味が一般の会社と違うので、同じ物差しでは測らない
        health = [None] * 6
    else:
        no_debt = m["no_debt"]
        health = [
            _at_least(m["current_ratio"], h["current_ratio_min"]),
            None if m["de"] is None else m["de"] <= h["debt_to_equity_max"],
            True if no_debt else _below(m["de"], m["de_old"]),
            True if no_debt else _at_least(m["ocf_to_debt"], h["ocf_to_debt_min"]),
            True if no_debt and m["interest_cover"] is None else _at_least(m["interest_cover"], h["interest_cover_min"]),
            _at_least(m["equity_ratio"], h["equity_ratio_min_pct"]),
        ]
    if not m["payer"]:
        dividend = [False] * 6
    else:
        payout = m["payout"]
        dividend = [
            _at_least(m["div_yield"], stats["yield_low"]),
            _at_least(m["div_yield"], stats["yield_high"]),
            False if loss else (None if payout is None else 0 < payout <= d["payout_max_pct"]),
            None if fin else _at_least(m["fcf_annual"], m["div_paid"]),
            bool(m["div_stable"]),
            bool(m["div_growing"]),
        ]
    return {"value": value, "growth": growth, "past": past, "health": health, "dividend": dividend}


def axis_score(results: list, cfg: dict) -> Optional[int]:
    """合格した項目の数。判定不可が多すぎる軸は点数を付けない（None）。"""
    if sum(1 for r in results if r is None) > cfg["fundamentals"]["max_unknown_checks"]:
        return None
    return sum(1 for r in results if r)


def score_universe(
    facts_by_code: Dict[str, dict], prices: Dict[str, float], sectors: Dict[str, str], cfg: dict, today: dt.date
) -> dict:
    """対象銘柄すべてを採点する。

    戻り値: stats = 比べる基準, stocks = {コード: {"s": 5軸の点数, "c": 項目ごとの判定, "m": 指標}}
    """
    financial = set(cfg["fundamentals"]["financial_sectors"])
    all_metrics = {
        code: metrics(facts, prices.get(code), cfg, today, sectors.get(code) in financial)
        for code, facts in facts_by_code.items()
    }
    stats = universe_stats(all_metrics, sectors, cfg)
    stocks = {}
    for code, m in all_metrics.items():
        result = checks(m, stats, sectors.get(code, ""), cfg)
        stocks[code] = {"s": [axis_score(result[a], cfg) for a in AXES], "c": result, "m": m}
    return {"stats": stats, "stocks": stocks}

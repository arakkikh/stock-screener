"""財務データの取得（yfinance）。ネットワークに触る。

取得した内容は「facts」という決まった形の辞書にそろえて返す。
別のデータ源（EDINET や SEC EDGAR など）に替えるときは、同じ形の辞書を返す関数を用意すればよい。

facts の形:
  fetched … 取得日 / price … 取得時の株価 / currency・price_currency … 決算と株価の通貨
  shares, eps, bvps, ebitda, total_debt, total_cash, roe, roa, payout, div_rate, fcf, ocf … 直近の値
  est … アナリスト予想（今期 0y・来期 1y の EPS 成長率と売上成長率、アナリスト数）
  annual … 年次決算（新しい順）。売上・純利益・EPS・資産・負債・キャッシュフローなど
  div_by_year … 暦年ごとの1株配当の合計 / div_ttm … 直近12か月の1株配当の合計
"""
from __future__ import annotations

import datetime as dt
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

ANNUAL_ROWS = {
    "financials": {
        "revenue": "Total Revenue",
        "net_income": "Net Income",
        "eps": "Diluted EPS",
        "ebit": "EBIT",
        "interest": "Interest Expense",
    },
    "balance_sheet": {
        "assets": "Total Assets",
        "equity": "Stockholders Equity",
        "debt": "Total Debt",
        "cur_assets": "Current Assets",
        "cur_liab": "Current Liabilities",
    },
    "cashflow": {
        "ocf": "Operating Cash Flow",
        "fcf": "Free Cash Flow",
        "dividends_paid": "Cash Dividends Paid",
    },
}
INFO_KEYS = {
    "price": "currentPrice",
    "shares": "sharesOutstanding",
    "eps": "trailingEps",
    "bvps": "bookValue",
    "ebitda": "ebitda",
    "total_debt": "totalDebt",
    "total_cash": "totalCash",
    "roe": "returnOnEquity",
    "roa": "returnOnAssets",
    "payout": "payoutRatio",
    "div_rate": "dividendRate",
    "fcf": "freeCashflow",
    "ocf": "operatingCashflow",
}


def _number(value) -> Optional[float]:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def _annual(ticker: yf.Ticker) -> List[dict]:
    """年次決算を、決算日ごとの辞書の並び（新しい順）にする。"""
    by_date: Dict[str, dict] = {}
    for statement, rows in ANNUAL_ROWS.items():
        frame = getattr(ticker, statement)
        if frame is None or frame.empty:
            continue
        for column in frame.columns:
            date = pd.Timestamp(column).strftime("%Y-%m-%d")
            entry = by_date.setdefault(date, {"date": date})
            for key, row in rows.items():
                entry[key] = _number(frame.at[row, column]) if row in frame.index else None
    years = sorted(by_date.values(), key=lambda e: e["date"], reverse=True)
    # 売上も純利益もない年（データの端によくある空の列）は捨てる
    return [y for y in years if y.get("revenue") is not None or y.get("net_income") is not None][:5]


def _estimates(ticker: yf.Ticker) -> dict:
    out = {"eps_growth_0y": None, "eps_growth_1y": None, "rev_growth_0y": None, "rev_growth_1y": None, "analysts": None}
    for prefix, name in (("eps", "earnings_estimate"), ("rev", "revenue_estimate")):
        try:
            frame = getattr(ticker, name)
        except Exception:
            frame = None
        if frame is None or frame.empty or "growth" not in frame.columns:
            continue
        for label, period in (("0y", "0y"), ("1y", "+1y")):
            if period in frame.index:
                out[f"{prefix}_growth_{label}"] = _number(frame.at[period, "growth"])
        if prefix == "eps" and "+1y" in frame.index and "numberOfAnalysts" in frame.columns:
            out["analysts"] = _number(frame.at["+1y", "numberOfAnalysts"])
    return out


def _dividends(ticker: yf.Ticker) -> tuple:
    """(暦年ごとの1株配当の合計, 直近12か月の1株配当の合計) を返す。"""
    series = ticker.dividends
    if series is None or series.empty:
        return {}, 0.0
    yearly = series.groupby(series.index.year).sum()
    by_year = {str(year): round(float(value), 6) for year, value in yearly.items() if year >= dt.date.today().year - 12}
    since = pd.Timestamp.now(tz=series.index.tz) - pd.Timedelta(days=365)
    return by_year, round(float(series[series.index > since].sum()), 6)


def fetch_facts(symbol: str, retries: int = 1) -> Optional[dict]:
    """1銘柄分の財務データを取得する。取得できなければ None。"""
    for attempt in range(retries + 1):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            if not info.get("currentPrice") and not info.get("trailingEps") and not info.get("bookValue"):
                raise ValueError("基本情報が空です")
            facts = {key: _number(info.get(source)) for key, source in INFO_KEYS.items()}
            by_year, trailing = _dividends(ticker)
            facts.update(
                {
                    "fetched": dt.date.today().isoformat(),
                    "currency": info.get("financialCurrency"),
                    "price_currency": info.get("currency"),
                    "est": _estimates(ticker),
                    "annual": _annual(ticker),
                    "div_by_year": by_year,
                    "div_ttm": trailing,  # Yahoo の「年間配当」は不正確なことがあるので、支払い履歴から求める
                }
            )
            return facts
        except Exception:
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    return None


def fetch_many(symbols: List[str], workers: int = 4, progress_every: int = 50) -> Dict[str, Optional[dict]]:
    """複数銘柄をまとめて取得する。進み具合を表示する。"""
    result: Dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (symbol, facts) in enumerate(zip(symbols, pool.map(fetch_facts, symbols)), 1):
            result[symbol] = facts
            if i % progress_every == 0 or i == len(symbols):
                ok = sum(1 for v in result.values() if v)
                print(f"  {i}/{len(symbols)} 銘柄（取得できた {ok}）", flush=True)
    return result

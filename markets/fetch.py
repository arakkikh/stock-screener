"""データ取得（yfinance と取引所カレンダー）。ネットワークに触るのはこのファイルだけ。"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import exchange_calendars as xc
import pandas as pd
import yfinance as yf

from . import Market

COLUMNS = ["open", "high", "low", "close", "volume"]


def last_completed_session(market: Market, now: dt.datetime) -> dt.date:
    """now の時点で取引が終わっている、いちばん新しい営業日。

    土日・祝日は取引所カレンダーで除く。引けから settle_minutes が過ぎるまでは
    その日を「まだ終わっていない」とみなし、作りかけの日足を使わないようにする。
    """
    cal = xc.get_calendar(market.calendar)
    ts = pd.Timestamp(now)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    today = ts.tz_convert(cal.tz).tz_localize(None).normalize()
    sessions = cal.sessions_in_range(today - pd.Timedelta(days=14), today)
    settle = pd.Timedelta(minutes=market.settle_minutes)
    for session in reversed(sessions):
        if cal.session_close(session) + settle <= ts:
            return session.date()
    raise RuntimeError("直近2週間に営業日が見つかりません")


def previous_session(market: Market, day: dt.date) -> dt.date:
    """day より前の、いちばん近い営業日（決算日の前営業日を求めるのに使う）。"""
    cal = xc.get_calendar(market.calendar)
    end = pd.Timestamp(day) - pd.Timedelta(days=1)
    return cal.sessions_in_range(end - pd.Timedelta(days=14), end)[-1].date()


# 株価の「断絶」（値動きではなくデータの異常）の見分け方
BREAK_UP_RATIO = 1.8        # 前日比がこの倍率を超えて上がる（大型株では実際には起きない）
BREAK_DOWN_RATIO = 0.1      # 前日比がこの倍率を下回る（10分の1未満）
SPLIT_RATIOS = (1 / 2, 1 / 3, 1 / 4, 1 / 5)   # 株式分割が反映されていないときに現れる倍率
SPLIT_TOLERANCE = 0.03      # 上の倍率からのずれがこの割合以内なら、分割の未反映とみなす


def drop_before_break(frame: pd.DataFrame) -> pd.DataFrame:
    """株価の「断絶」より前の履歴を捨てる。

    取得元のデータには、株式分割が過去の株価に反映されていない・値が壊れている、
    といった異常がまれにある（1日でちょうど3分の1になる、数億倍になる、など）。
    そのまま使うと移動平均線や騰落率が狂うので、最後の断絶より後だけを使う。
    断絶の日そのものは、新しい水準の最初の日として残す。

    実際の暴落（1日で −50% など）は捨てない。捨てると、いちばん損をする場面が
    検証から消えてしまうため。分割の未反映は、始値が前日終値のちょうど
    2分の1・3分の1…になることで見分ける。
    """
    prev_close = frame["close"].shift(1)
    open_ratio = frame["open"] / prev_close
    close_ratio = frame["close"] / prev_close
    jump = (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
    for ratio in (open_ratio, close_ratio):
        jump |= (ratio > BREAK_UP_RATIO) | (ratio < BREAK_DOWN_RATIO)
    for split in SPLIT_RATIOS:
        jump |= ((open_ratio / split - 1).abs() <= SPLIT_TOLERANCE) & ((close_ratio / split - 1).abs() <= 0.15)
    if not jump.any():
        return frame
    return frame.loc[jump[jump].index[-1] :]


def _clean(frame: pd.DataFrame, last_day: dt.date) -> Optional[pd.DataFrame]:
    frame = frame.rename(columns=str.lower)
    if "close" not in frame:
        return None
    frame = frame.dropna(subset=["open", "high", "low", "close"])[COLUMNS]
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None).normalize()
    frame = frame[frame.index.date <= last_day]
    frame = drop_before_break(frame)
    return frame if len(frame) else None


def download_daily(tickers: List[str], last_day: dt.date, period: str = "2y") -> Dict[str, pd.DataFrame]:
    """日足をまとめて取得する。取れなかったティッカーは戻り値に入らない。

    株式分割は調整し、配当は調整しない（チャートに表示される値段と同じ）。
    """
    raw = yf.download(
        tickers, period=period, auto_adjust=False, group_by="ticker", progress=False, threads=True
    )
    result = {}
    for ticker in tickers:
        try:
            frame = _clean(raw[ticker], last_day)
        except KeyError:
            frame = None
        if frame is not None:
            result[ticker] = frame
    return result


def _earnings_dates(ticker: str) -> Optional[List[dt.date]]:
    try:
        calendar = yf.Ticker(ticker).calendar
        return sorted(calendar.get("Earnings Date") or [])
    except Exception:
        return None


def earnings_dates(tickers: List[str]) -> Dict[str, Optional[List[dt.date]]]:
    """決算発表日。発表前なら次回の予定日、発表直後なら済んだ日付が返る。

    取得に失敗したティッカーは None。
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(tickers, pool.map(_earnings_dates, tickers)))

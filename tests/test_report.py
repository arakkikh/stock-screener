import datetime as dt
import json

import numpy as np
import pandas as pd

import markets
from markets import fetch
from screener import report
from tests.helpers import cfg


def price_df(close):
    close = pd.Series(close, dtype=float, index=pd.bdate_range("2026-01-05", periods=len(close)))
    open_ = close.shift(1).fillna(close)
    return pd.DataFrame(
        {
            "open": open_,
            "high": pd.concat([open_, close], axis=1).max(axis=1) + 0.5,
            "low": pd.concat([open_, close], axis=1).min(axis=1) - 0.5,
            "close": close,
            "volume": 1000.0,
        }
    )


def wavy(days=150):
    rng = np.random.default_rng(1)
    return list(100 + np.cumsum(rng.normal(0, 1.2, days)))


def utc(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=dt.timezone.utc)


# ---- JSON の形 ----

def test_output_is_valid_json_without_nan():
    summary, chart = report.analyze_stock(price_df(wavy()), cfg(), 1)
    json.dumps([summary, chart], allow_nan=False)  # NaN が混ざっていると例外になる
    assert chart["ma_l"][0] is None                # データが足りない日は null
    assert len(chart["t"]) == len(chart["c"]) == len(chart["cnt"]) == 150


def test_summary_reports_sharp_drop():
    summary, _ = report.analyze_stock(price_df([100.0] * 149 + [90.0]), cfg(), 1)
    assert summary["conds"] == [1, 2, 3]
    assert summary["count"] == 3
    assert summary["bb_level"] == 3
    assert summary["lit_days_ago"] == 0
    assert summary["entry"] is False  # 条件が点灯しただけでは候補にしない


def test_lit_days_ago_counts_sessions_and_expires():
    c = cfg()
    recent, _ = report.analyze_stock(price_df([100.0] * 140 + [90.0] + [90.0] * 4), c, 1)
    assert recent["lit_days_ago"] is not None
    quiet, _ = report.analyze_stock(price_df([100.0] * 150), c, 1)
    assert quiet["lit_days_ago"] is None
    assert quiet["count"] == 0


def test_chart_marks_match_recent_events():
    summary, chart = report.analyze_stock(price_df(wavy()), cfg(), 1)
    last_days = set(chart["t"][-cfg()["display"]["recent_days"] :])
    assert summary["recent"] == [m for m in chart["marks"] if m["d"] in last_days]


def test_index_state():
    up = report.index_state(price_df([100 + 0.5 * i for i in range(150)]), cfg())
    assert up["perfect_order"] and all(up["above"].values()) and all(up["rising"].values())
    down = report.index_state(price_df([200 - 0.5 * i for i in range(150)]), cfg())
    assert not down["perfect_order"] and not any(down["above"].values())


def test_sector_downtrend():
    n = 150
    closes = pd.DataFrame(
        {
            "A": [200 - 0.5 * i for i in range(n)],
            "B": [150 - 0.3 * i for i in range(n)],
            "C": [100 + 0.5 * i for i in range(n)],
        }
    )
    result = report.sector_trends(closes, {"A": "下げ", "B": "下げ", "C": "上げ"}, cfg())
    assert result["下げ"] == {"count": 2, "change_pct": result["下げ"]["change_pct"], "downtrend": True}
    assert result["上げ"]["downtrend"] is False


# ---- 営業日の判定 ----

JP, US = markets.get("jp"), markets.get("us")


def test_jp_after_close_uses_today():
    assert fetch.last_completed_session(JP, utc("2026-11-10T07:30")) == dt.date(2026, 11, 10)  # 16:30 JST


def test_jp_during_trading_uses_previous_day():
    assert fetch.last_completed_session(JP, utc("2026-11-10T04:00")) == dt.date(2026, 11, 9)  # 13:00 JST


def test_jp_holiday_and_weekend_are_skipped():
    assert fetch.last_completed_session(JP, utc("2026-11-03T07:30")) == dt.date(2026, 11, 2)  # 文化の日
    assert fetch.last_completed_session(JP, utc("2026-11-08T07:30")) == dt.date(2026, 11, 6)  # 日曜


def test_us_730_jst_is_after_close_in_winter_and_summer():
    # 7:30 JST = 前日の 22:30 UTC
    assert fetch.last_completed_session(US, utc("2026-11-10T22:30")) == dt.date(2026, 11, 10)  # 冬時間
    assert fetch.last_completed_session(US, utc("2026-07-07T22:30")) == dt.date(2026, 7, 7)    # 夏時間


def test_us_saturday_morning_jst_gets_friday():
    assert fetch.last_completed_session(US, utc("2026-11-13T22:30")) == dt.date(2026, 11, 13)


def test_us_holiday_is_skipped():
    assert fetch.last_completed_session(US, utc("2026-11-26T22:30")) == dt.date(2026, 11, 25)  # 感謝祭


def test_us_during_trading_uses_previous_day():
    assert fetch.last_completed_session(US, utc("2026-11-10T18:00")) == dt.date(2026, 11, 9)


def test_previous_session_skips_weekend_and_holiday():
    assert fetch.previous_session(JP, dt.date(2026, 11, 9)) == dt.date(2026, 11, 6)   # 月曜 → 金曜
    assert fetch.previous_session(JP, dt.date(2026, 11, 4)) == dt.date(2026, 11, 2)   # 祝日をまたぐ
    assert fetch.previous_session(US, dt.date(2026, 11, 27)) == dt.date(2026, 11, 25)


def test_ticker_format():
    assert JP.ticker("7203") == "7203.T"
    assert US.ticker("BRK-B") == "BRK-B"


# ---- 決算日の記録 ----

def merge(entry, fetched, today="2026-11-10"):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "update.py"
    spec = importlib.util.spec_from_file_location("update_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.merge_earnings(entry, fetched, today)


def test_upcoming_earnings_date_is_next():
    assert merge({}, ["2026-11-18"]) == {"next": "2026-11-18", "past": []}


def test_earnings_on_the_day_still_counts_as_next():
    assert merge({}, ["2026-11-10"])["next"] == "2026-11-10"


def test_just_reported_date_goes_to_past():
    assert merge({}, ["2026-10-29"]) == {"next": None, "past": ["2026-10-29"]}


def test_remembered_date_moves_to_past_and_new_one_becomes_next():
    result = merge({"next": "2026-11-05", "past": ["2026-08-05"]}, ["2027-02-04"])
    assert result == {"next": "2027-02-04", "past": ["2026-08-05", "2026-11-05"]}


def test_failed_fetch_keeps_what_we_knew():
    entry = {"next": "2026-11-18", "past": ["2026-08-20"]}
    assert merge(entry, None) == entry


# ---- 順張りモードの出力 ----

def volume_df(close, volume):
    df = price_df(close)
    df["volume"] = volume
    return df


def test_momentum_summary_for_passing_stock():
    summary, chart = report.analyze_momentum(price_df(list(np.linspace(100, 200, 300))), 90, cfg(), 1)
    json.dumps([summary, chart], allow_nan=False)
    assert summary["passed"] and summary["count"] == 8 and summary["conds"] == [1] * 8
    assert summary["rs"] == 90
    assert len(chart["t"]) == 260 and chart["m_s"][-1] is not None


def test_momentum_no_chart_or_vcp_for_failing_stock():
    summary, chart = report.analyze_momentum(price_df(list(np.linspace(100, 200, 300))), 50, cfg(), 1)
    assert summary["count"] == 7 and not summary["passed"]
    assert chart is None and summary["vcp"] is None


def test_momentum_skips_stock_without_enough_history():
    assert report.analyze_momentum(price_df(list(np.linspace(100, 200, 200))), 90, cfg(), 1) == (None, None)


def test_momentum_reports_vcp_with_dates():
    # 1年かけて 40→100 と上げたあと、−20% → −9% → −4% と押しが浅くなる
    points = [(0, 40), (250, 100), (260, 80), (270, 98), (278, 89), (286, 97), (292, 93), (298, 96)]
    days, prices = zip(*points)
    close = list(np.interp(range(days[-1] + 1), days, prices))
    volume = [1000.0] * 270 + [600.0] * 16 + [300.0] * 13
    summary, chart = report.analyze_momentum(volume_df(close, volume), 95, cfg(), 1)
    json.dumps([summary, chart], allow_nan=False)
    vcp = summary["vcp"]
    assert summary["passed"]
    assert vcp["status"] == "forming" and len(vcp["legs"]) == 3
    assert vcp["pivot"] == 97.5 and vcp["to_pivot_pct"] > 0
    assert vcp["legs"][0]["depth"] > vcp["legs"][1]["depth"] > vcp["legs"][2]["depth"]
    assert vcp["pivot_date"] == vcp["legs"][-1]["hd"] and vcp["pivot_date"] in chart["t"]


def test_momentum_reports_recent_ma_break():
    close = list(np.linspace(100, 200, 299)) + [150.0]
    summary, _ = report.analyze_momentum(volume_df(close, [1000.0] * 299 + [3000.0]), 90, cfg(), 1)
    assert summary["ma_break"] == summary["date"]
    assert summary["volume_ratio"] == 3.0


# ---- 株価データの断絶（分割の未反映・壊れた値）----

def ohlc(close):
    close = pd.Series(close, dtype=float, index=pd.bdate_range("2026-01-05", periods=len(close)))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1000.0})


def test_normal_prices_are_kept_as_they_are():
    df = ohlc([100, 97, 103, 80, 120])   # 1日で −22% や +50% は、値動きとしてありうる
    assert len(fetch.drop_before_break(df)) == 5


def test_history_before_an_unadjusted_split_is_dropped():
    df = ohlc([11000, 11050, 11040, 3713, 3628, 3700])   # 1:3 の分割が過去に反映されていない
    kept = fetch.drop_before_break(df)
    assert list(kept["close"]) == [3713, 3628, 3700]


def test_history_before_garbage_values_is_dropped():
    df = ohlc([2796, 2798, 5.59e10, 5.53e10, 2800, 2810])   # 壊れた値が2日続き、元に戻る
    assert list(fetch.drop_before_break(df)["close"]) == [2800, 2810]


def test_unadjusted_two_for_one_split_is_also_detected():
    df = ohlc([2000, 2010, 1004, 1010])
    assert list(fetch.drop_before_break(df)["close"]) == [1004, 1010]


def test_real_crash_is_not_treated_as_a_break():
    # 1日で −45% の暴落（倍率 0.55。2分の1・3分の1のどれにも当たらない）は実際の値動きとして残す
    df = ohlc([100, 101, 55.5, 57, 60])
    assert len(fetch.drop_before_break(df)) == 5
    # −60%（倍率 0.4）も同じ
    assert len(fetch.drop_before_break(ohlc([100, 101, 40.4, 42]))) == 4


def test_only_history_after_the_last_break_is_used():
    df = ohlc([100, 500, 510, 30, 31, 32])   # 5倍になり、のちに 0.06倍になる（どちらも異常）
    assert list(fetch.drop_before_break(df)["close"]) == [30, 31, 32]


def test_non_positive_price_counts_as_a_break():
    df = ohlc([100, 101, 0, 102, 103])
    assert list(fetch.drop_before_break(df)["close"]) == [102, 103]

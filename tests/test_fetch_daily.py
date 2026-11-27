"""日足の取得（期間の指定と日付のそろえ方）のテスト。通信はしない。"""
import datetime as dt

import pandas as pd
import pytest

from markets import fetch
from scripts.update import latest_dates_hint


def test_window_ends_the_day_after_the_last_completed_session():
    start, end = fetch.download_window(dt.date(2026, 11, 26), "2y")
    assert (start, end) == (dt.date(2024, 11, 26), dt.date(2026, 11, 27))
    assert fetch.download_window(dt.date(2026, 11, 26), "10y")[0] == dt.date(2016, 11, 26)
    with pytest.raises(ValueError):
        fetch.download_window(dt.date(2026, 11, 26), "6mo")


def frame(days):
    idx = pd.DatetimeIndex(days, name="Date")
    return pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 100}, index=idx)


def test_download_asks_for_an_explicit_date_range(monkeypatch):
    seen = {}

    def fake_download(tickers, **kwargs):
        seen.update(kwargs)
        data = {t: frame(["2026-11-25", "2026-11-26"]) for t in tickers}
        return pd.concat(data, axis=1)

    monkeypatch.setattr(fetch.yf, "download", fake_download)
    result = fetch.download_daily(["7203.T", "6758.T"], dt.date(2026, 11, 26))
    assert "period" not in seen
    assert (seen["start"], seen["end"]) == ("2024-11-26", "2026-11-27")
    assert list(result) == ["7203.T", "6758.T"]
    assert result["7203.T"].index[-1] == pd.Timestamp("2026-11-26")


def test_rows_after_the_last_session_are_dropped():
    cleaned = fetch._clean(frame(["2026-11-25", "2026-11-26", "2026-11-27"]), dt.date(2026, 11, 26))
    assert cleaned.index[-1] == pd.Timestamp("2026-11-26")


def test_hint_summarizes_latest_dates():
    prices = {"A.T": frame(["2026-11-25"]).rename(columns=str.lower), "B.T": frame(["2026-11-25"]).rename(columns=str.lower),
              "C.T": frame(["2026-11-26"]).rename(columns=str.lower)}
    hint = latest_dates_hint(prices, {"A": "A.T", "B": "B.T", "C": "C.T", "D": "D.T"})
    assert hint.startswith("データの最新日 2026-11-26: 1銘柄、2026-11-25: 2銘柄")
    assert "A=2026-11-25" in hint
    assert latest_dates_hint({}, {"A": "A.T"}) == "データを1件も取得できませんでした"

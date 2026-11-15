"""相場環境の判定のテスト。"""
import copy

import numpy as np
import pandas as pd
import pytest

from screener import regime as rg
from tests.helpers import cfg


def small_cfg(**change):
    c = copy.deepcopy(cfg())
    c["regime"].update({"ma": {"short": 3, "mid": 4, "long": 5}, "slope_days": {"short": 1, "mid": 1, "long": 2},
                        "year_days": 6, "min_stocks": 2, "confirm_days": 1, "reversal_compare_days": 2, **change})
    return c


def table(rows):
    """行が日付、列が銘柄の表。"""
    return pd.DataFrame(rows, index=pd.bdate_range("2026-01-05", periods=len(rows)), dtype=float)


# ---- 騰落の広がり ----

def test_breadth_counts_stocks_above_lines():
    # A は上がり続け、B は下がり続け、C は横ばい（線と同じ値は「上」に数えない）
    close = table([[10 + i, 20 - i, 5] for i in range(8)])
    b = rg.breadth(close, close, close, small_cfg())
    assert np.isnan(b["p_short"].iloc[1])           # 3日線がまだ引けない
    assert b["p_short"].iloc[-1] == pytest.approx(100 / 3)
    assert b["p_long"].iloc[-1] == pytest.approx(100 / 3)
    assert b["n"].iloc[-1] == 3


def test_breadth_skips_stocks_without_enough_history():
    close = table([[10 + i, np.nan if i < 6 else 50] for i in range(8)])
    b = rg.breadth(close, close, close, small_cfg(min_stocks=1))
    assert b["n"].iloc[-1] == 1 and b["p_long"].iloc[-1] == 100.0
    assert np.isnan(rg.breadth(close, close, close, small_cfg(min_stocks=2))["p_long"].iloc[-1])


def test_new_highs_and_lows_compare_with_previous_year():
    high = table([[10, 10], [11, 10], [12, 10], [13, 10], [14, 10], [15, 10], [16, 10], [15, 10]])
    low = table([[9, 9], [9, 9], [9, 9], [9, 9], [9, 9], [9, 9], [9, 8], [9, 9]])
    b = rg.breadth(high, high, low, small_cfg())
    assert b["highs"].iloc[6] == 1 and b["lows"].iloc[6] == 1   # A が高値更新、B が安値更新
    assert b["highs"].iloc[7] == 0 and b["lows"].iloc[7] == 0
    assert np.isnan(b["highs"].iloc[4])                         # 1年分そろっていない


# ---- 判定 ----

def breadth_row(p_short, p_long, lows=0, n=100, days=1):
    return pd.DataFrame({"p_short": [p_short] * days, "p_long": [p_long] * days, "highs": [0] * days,
                         "lows": [lows] * days, "n": [n] * days})


def classify_last(index_values, p_short, p_long, vix=None, lows=None, **change):
    c = small_cfg(**change)
    days = len(index_values)
    idx = pd.bdate_range("2026-01-05", periods=days)
    b = pd.DataFrame({"p_short": p_short if isinstance(p_short, list) else [p_short] * days,
                      "p_long": [p_long] * days, "highs": [0] * days,
                      "lows": lows if lows is not None else [0] * days, "n": [100] * days}, index=idx)
    vix_series = None if vix is None else pd.Series([vix] * days, index=idx)
    return rg.classify(b, pd.Series(index_values, index=idx, dtype=float), vix_series, c).iloc[-1]


UP = [100 + i for i in range(10)]
DOWN = [120 - 2 * i for i in range(10)]


def test_uptrend_with_broad_participation_is_momentum():
    last = classify_last(UP, 50, 70)
    assert (last["regime"], last["reason"]) == ("momentum", "uptrend")


def test_uptrend_needs_enough_stocks_above_200_day_line():
    assert classify_last(UP, 50, 59.9)["regime"] == "wait"
    assert classify_last(UP, 50, 60)["regime"] == "momentum"


def test_oversold_is_contrarian_even_in_downtrend():
    limit = cfg()["regime"]["oversold_pct"]
    last = classify_last(DOWN, limit, 30)
    assert (last["regime"], last["reason"]) == ("contrarian", "oversold")
    assert classify_last(DOWN, limit + 0.1, 30)["regime"] == "wait"
    assert classify_last(DOWN, 20.1, 30, oversold_pct=20)["regime"] == "wait"


def test_high_vix_is_contrarian():
    assert classify_last(UP, 50, 70, vix=30.5)["regime"] == "contrarian"
    assert classify_last(UP, 50, 70, vix=30)["regime"] == "momentum"


def test_downtrend_without_reversal_is_wait():
    last = classify_last(DOWN, 40, 30)
    assert (last["regime"], last["reason"]) == ("wait", "downtrend")


def test_reversal_sign_turns_downtrend_into_flat_wait():
    # 下落中だが最後に指数が3日線を上回った
    values = DOWN[:-1] + [120]
    last = classify_last(values, 40, 30)
    assert last["reversal"] and last["regime"] == "wait" and last["reason"] == "flat"


def test_decreasing_new_lows_is_a_reversal_sign():
    lows = [30] * 8 + [0, 0]  # 5日平均の安値更新数が2日前より減った
    assert bool(classify_last(DOWN, 40, 30, lows=lows)["reversal"]) is True
    assert bool(classify_last(DOWN, 40, 30, lows=[30] * 10)["reversal"]) is False


def test_unknown_days_have_no_regime():
    last = classify_last(UP[:3], 50, 70)  # 5日線がまだ引けない
    assert last["regime"] is None and last["raw"] is None


# ---- 切り替えの確認 ----

def test_confirm_waits_for_consecutive_days():
    raw = pd.Series(["wait", "wait", "momentum", "wait", "momentum", "momentum", None, "contrarian"])
    assert list(rg.confirm(raw, 2)) == ["wait", "wait", "wait", "wait", "wait", "momentum", "momentum", "momentum"]
    assert list(rg.confirm(raw, 1)) == ["wait", "wait", "momentum", "wait", "momentum", "momentum", "momentum", "contrarian"]


def test_since_returns_start_of_current_regime():
    idx = pd.bdate_range("2026-01-05", periods=4)
    df = pd.DataFrame({"regime": ["wait", "momentum", "momentum", "momentum"]}, index=idx)
    assert rg.since(df) == "2026-01-06"


# ---- 全体 ----

def test_compute_and_payload_from_daily_frames():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2025-01-01", periods=320)
    frames = {}
    for k in range(60):
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, len(idx)))), index=idx)
        frames[f"S{k}"] = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close})
    index = pd.DataFrame({"close": pd.Series(np.linspace(1000, 1300, len(idx)), index=idx)})
    c = cfg()
    df = rg.compute(frames, index, None, c)
    assert set(df["regime"].dropna()) <= set(rg.LABELS)
    p = rg.payload(df, c, idx[-1].strftime("%Y-%m-%d"), "2026-01-01T00:00:00Z")
    assert p["latest"]["regime"] in rg.LABELS
    assert len(p["history"]["t"]) == len(p["history"]["p_short"]) <= c["regime"]["history_days"]
    assert p["latest"]["n"] == 60 and p["latest"]["rising_long"] is True
    assert rg.by_date(df)[p["latest"]["date"]] == p["latest"]["regime"]

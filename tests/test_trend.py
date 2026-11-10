import pandas as pd

from screener.signals import trend_mode, trend_state
from tests.helpers import cfg, make_df

# 5日線と25日線の差(%)の並び。3%で離れ、1%で接近（しきい値は1.5%）
THREE_APPROACHES = [0.5, 1, 2, 3, 1, 3, 1, 3, 1]


def state(gaps, highs=None, long_start=50.0, long_step=0.01):
    """25日線はゆるやかに上昇。5日線は gaps(%) の分だけ25日線から離す。"""
    n = len(gaps)
    mid = pd.Series([100 + 0.1 * i for i in range(n)])
    short = mid * (1 + pd.Series(gaps, dtype=float) / 100)
    long_ = pd.Series([long_start + long_step * i for i in range(n)])
    high = pd.Series(highs if highs is not None else [100.0] * n, dtype=float)
    return trend_state(high, short, mid, long_, cfg())


# ---- パーフェクトオーダー ----

def test_perfect_order_when_lines_are_ordered_and_rising():
    result = state([1, 2, 3])
    assert list(result["perfect_order"]) == [False, True, True]  # 初日は向きが分からない


def test_not_perfect_order_if_long_line_is_falling():
    assert not state([1, 2, 3], long_step=-0.01)["perfect_order"].any()


def test_not_perfect_order_if_short_line_turns_down():
    result = state([1, 3, 2.5])
    assert list(result["perfect_order"]) == [False, True, False]
    assert result["in_trend"].iloc[-1]  # 5日線が下を向いただけではトレンドは終わらない


def test_not_perfect_order_if_order_is_wrong():
    assert not state([1, 2, 3], long_start=150.0)["perfect_order"].any()


# ---- 接近回数 ----

def test_counts_approaches():
    result = state(THREE_APPROACHES)
    assert list(result["approach_count"]) == [0, 0, 0, 0, 1, 1, 2, 2, 3]


def test_start_of_trend_is_not_counted_as_approach():
    # トレンドの始まりは2本の線が近いが、離れる前なので接近には数えない
    result = state([0.5, 1, 1.2, 1.4])
    assert result["near"].iloc[-1]
    assert result["approach_count"].iloc[-1] == 0


def test_staying_near_counts_once():
    result = state([0.5, 1, 3, 1, 1.2, 0.8, 1.4])
    assert result["approach_count"].iloc[-1] == 1


def test_small_dip_below_mid_line_is_still_an_approach():
    result = state([0.5, 1, 3, -0.5, 3])
    assert result["in_trend"].iloc[-1]
    assert result["approach_count"].iloc[-1] == 1


def test_trend_ends_on_clear_dead_cross_and_count_resets():
    result = state([0.5, 1, 3, 1, 3, -2, -1, 2, 3])
    assert result["approach_count"].iloc[4] == 1
    assert not result["in_trend"].iloc[5]
    assert not result["in_trend"].iloc[6]   # 並びが戻るまでは対象外
    assert result["in_trend"].iloc[7]
    assert result["approach_count"].iloc[8] == 0


def test_trend_ends_when_mid_line_falls_below_long_line():
    # 100日線が途中から25日線を上回る
    result = state([0.5, 1, 3, 3, 3], long_start=99.9, long_step=0.15)
    assert result["in_trend"].iloc[1]
    assert not result["in_trend"].iloc[-1]


# ---- 手仕舞い警戒 ----

def test_exit_warning_on_third_approach_without_new_high():
    #                     接近1      接近2      接近3
    highs = [100, 101, 105, 110, 108, 120, 115, 118, 114]
    result = state(THREE_APPROACHES, highs)
    assert list(result["exit_warning"]) == [False] * 8 + [True]
    assert not result["warning_cleared"].any()


def test_no_warning_before_third_approach():
    highs = [100, 101, 105, 110, 108, 104, 103, 102, 101]
    result = state(THREE_APPROACHES[:7], highs[:7])
    assert result["approach_count"].iloc[-1] == 2
    assert not result["exit_warning"].any()


def test_warning_cleared_when_latest_high_beats_previous_high():
    highs = [100, 101, 105, 110, 108, 120, 115, 125, 121]  # 直近の高値125 > 前回の高値120
    result = state(THREE_APPROACHES, highs)
    assert result["approach_count"].iloc[-1] == 3
    assert not result["exit_warning"].iloc[-1]
    assert result["warning_cleared"].iloc[-1]


def test_warning_cleared_later_by_new_high():
    highs = [100, 101, 105, 110, 108, 120, 115, 118, 114, 119, 121]
    result = state(THREE_APPROACHES + [3, 3], highs)
    assert list(result["exit_warning"].iloc[-3:]) == [True, True, False]
    assert result["warning_cleared"].iloc[-1]


def test_warning_continues_on_fourth_approach():
    highs = [100, 101, 105, 110, 108, 120, 115, 118, 114, 116, 113]
    result = state(THREE_APPROACHES + [3, 1], highs)
    assert result["approach_count"].iloc[-1] == 4
    assert result["exit_warning"].iloc[-1]


def test_warning_count_comes_from_config():
    c = cfg()
    c["trend"]["exit_warning_count"] = 2
    n = 7
    mid = pd.Series([100 + 0.1 * i for i in range(n)])
    short = mid * (1 + pd.Series(THREE_APPROACHES[:n]) / 100)
    long_ = pd.Series([50 + 0.01 * i for i in range(n)])
    high = pd.Series([100, 101, 105, 110, 108, 107, 106], dtype=float)
    assert trend_state(high, short, mid, long_, c)["exit_warning"].iloc[-1]


# ---- 株価データからの判定 ----

def test_steady_uptrend_is_holding_zone():
    result = trend_mode(make_df([100 + 0.5 * i for i in range(150)]), cfg())
    assert result["perfect_order"].iloc[-1]
    assert result["in_trend"].iloc[-1]
    assert not result["exit_warning"].iloc[-1]


def test_downtrend_is_not_holding_zone():
    result = trend_mode(make_df([200 - 0.5 * i for i in range(150)]), cfg())
    assert not result["perfect_order"].any()
    assert not result["in_trend"].any()

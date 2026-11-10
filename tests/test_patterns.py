import pandas as pd

from screener import patterns as pat
from screener.signals import entry_candidates, reversal_signs, warning_signs
from tests.helpers import candles, cfg, make_df

# ---- 谷と山 ----

def test_swing_low_and_high():
    low = pd.Series([10, 9, 8, 7, 8, 9, 10, 11, 10, 9], dtype=float)
    assert list(pat.swing_lows(low, 3)[lambda s: s].index) == [3]
    assert list(pat.swing_highs(-low, 3)[lambda s: s].index) == [3]


def test_swing_needs_days_after_to_confirm():
    low = pd.Series([10, 9, 8, 7, 8, 9], dtype=float)  # 谷の後がまだ2日しかない
    assert not pat.swing_lows(low, 3).any()


# ---- 安値圏・高値圏 ----

def zone_df(last_close):
    close = [90.0, 110.0] * 30 + [last_close]
    return make_df(close, open_=close)


def test_low_and_high_zone():
    assert pat.in_low_zone(zone_df(92), cfg()).iloc[-1]       # 下から10%
    assert not pat.in_high_zone(zone_df(92), cfg()).iloc[-1]
    assert pat.in_high_zone(zone_df(108), cfg()).iloc[-1]     # 下から90%
    assert not pat.in_low_zone(zone_df(100), cfg()).iloc[-1]  # 真ん中
    assert not pat.in_high_zone(zone_df(100), cfg()).iloc[-1]


def test_zone_boundary_is_25_percent():
    assert pat.in_low_zone(zone_df(95), cfg()).iloc[-1]       # ちょうど25%
    assert not pat.in_low_zone(zone_df(95.5), cfg()).iloc[-1]


# ---- 抱き線 ----

def test_bullish_engulfing():
    df = candles([(100, 100.5, 96.5, 97), (96.5, 101.5, 96, 101)])
    assert list(pat.bullish_engulfing(df)) == [False, True]


def test_not_engulfing_if_body_not_covered():
    df = candles([(100, 100.5, 96.5, 97), (96.5, 99.5, 96, 99)])
    assert not pat.bullish_engulfing(df).any()


def test_not_engulfing_if_previous_day_was_bullish():
    df = candles([(97, 100.5, 96.5, 100), (96.5, 101.5, 96, 101)])
    assert not pat.bullish_engulfing(df).any()


# ---- はらみ線 ----

def test_bullish_harami():
    df = candles([(100, 100.5, 95.5, 96), (97, 98.5, 96.5, 98)])
    assert list(pat.bullish_harami(df, cfg())) == [False, True]
    assert not pat.bearish_harami(df, cfg()).any()


def test_bearish_harami():
    df = candles([(100, 104.5, 99.5, 104), (103, 103.5, 101.5, 102)])
    assert list(pat.bearish_harami(df, cfg())) == [False, True]
    assert not pat.bullish_harami(df, cfg()).any()


def test_not_harami_if_first_candle_is_small():
    df = candles([(100, 100.5, 99, 99.5), (99.6, 99.9, 99.5, 99.8)])  # 1本目の実体 0.5%
    assert not pat.bullish_harami(df, cfg()).any()


def test_not_harami_if_second_body_sticks_out():
    df = candles([(100, 100.5, 95.5, 96), (97, 101.5, 96.5, 101)])
    assert not pat.bullish_harami(df, cfg()).any()


# ---- 十字線 ----

def test_doji():
    df = candles([(100, 102, 98, 100.1), (100, 102, 98, 101.5), (100, 100, 100, 100)])
    assert list(pat.doji(df, cfg())) == [True, False, False]


# ---- 首吊り線 ----

def test_hanging_man_shape():
    df = candles([(100, 100.1, 97, 99.5)])  # 実体0.5、下ひげ2.5、上ひげ0.1
    assert pat.hanging_man(df, cfg()).iloc[0]


def test_not_hanging_man_with_long_upper_shadow():
    df = candles([(100, 102, 97, 99.5)])
    assert not pat.hanging_man(df, cfg()).iloc[0]


def test_not_hanging_man_with_short_lower_shadow():
    df = candles([(100, 100.1, 99, 99.5)])
    assert not pat.hanging_man(df, cfg()).iloc[0]


# ---- 下放れ二本黒 ----

def test_downside_gap_two_black():
    df = candles([(100, 101, 99, 100), (97, 98, 95.5, 96), (96, 97, 94, 95)])
    assert list(pat.downside_gap_two_black(df, cfg())) == [False, False, True]


def test_not_two_black_without_window():
    df = candles([(100, 101, 99, 100), (99.5, 99.8, 95.5, 96), (96, 97, 94, 95)])
    assert not pat.downside_gap_two_black(df, cfg()).any()


def test_not_two_black_if_second_candle_is_bullish():
    df = candles([(100, 101, 99, 100), (97, 98, 95.5, 96), (95, 97, 94, 96.5)])
    assert not pat.downside_gap_two_black(df, cfg()).any()


def test_not_two_black_if_window_is_filled():
    df = candles([(100, 101, 99, 100), (97, 98, 95.5, 96), (98, 99.5, 94, 95)])
    assert not pat.downside_gap_two_black(df, cfg()).any()


# ---- 上放れ並び赤 ----

def test_upside_gap_two_white():
    df = candles([(100, 101, 99, 100), (103, 105, 102.5, 104.5), (104, 106, 103.5, 105.5)])
    assert list(pat.upside_gap_two_white(df, cfg())) == [False, False, True]


def test_not_two_white_if_bodies_differ_too_much():
    df = candles([(100, 101, 99, 100), (103, 105, 102.5, 104.5), (104, 106, 103.5, 104.3)])
    assert not pat.upside_gap_two_white(df, cfg()).any()


def test_not_two_white_without_window():
    df = candles([(100, 101, 99, 100), (100.5, 105, 100.2, 104.5), (104, 106, 103.5, 105.5)])
    assert not pat.upside_gap_two_white(df, cfg()).any()


# ---- ギャップアップ ----

def test_gap_up_needs_one_percent_window():
    big = candles([(100, 101, 99, 100), (103, 104, 102.5, 103.5)])   # 窓 1.5%
    small = candles([(100, 101, 99, 100), (102, 103, 101.5, 102.5)])  # 窓 0.5%
    assert pat.gap_up(big, cfg()).iloc[1]
    assert not pat.gap_up(small, cfg()).iloc[1]


# ---- アイランド ----

def island(rows):
    return candles([(100, 101, 99, 100)] + rows)


def test_island_bottom():
    df = island([(96, 97, 95, 96), (96, 96.8, 95.2, 96.2), (96.2, 97, 95.5, 96.5), (99, 100, 98.5, 99.5)])
    assert pat.island_bottoms(df, cfg()) == [{"start": 1, "end": 3, "signal": 4}]
    assert pat.island_tops(df, cfg()) == []


def test_one_day_island_bottom():
    df = island([(96, 97, 95, 96), (99, 100, 98.5, 99.5)])
    assert pat.island_bottoms(df, cfg()) == [{"start": 1, "end": 1, "signal": 2}]


def test_no_island_if_window_gets_filled():
    df = island([(96, 97, 95, 96), (96, 99.5, 95.2, 99), (101, 102, 100.5, 101.5)])
    assert pat.island_bottoms(df, cfg()) == []


def test_no_island_without_gap_up():
    df = island([(96, 97, 95, 96), (96, 96.8, 95.2, 96.2), (96.5, 98, 96.4, 97.8)])
    assert pat.island_bottoms(df, cfg()) == []


def test_no_island_if_too_long():
    df = island([(96, 97, 95, 96)] * 11 + [(99, 100, 98.5, 99.5)])
    assert pat.island_bottoms(df, cfg()) == []


def test_island_top():
    df = island([(104, 105, 103, 104), (104, 104.8, 103.2, 103.8), (101, 101.5, 100, 100.5)])
    assert pat.island_tops(df, cfg()) == [{"start": 1, "end": 2, "signal": 3}]
    assert pat.island_bottoms(df, cfg()) == []


# ---- ダブルボトム・トリプルボトム ----

def bottoms_df(bottoms, length=60, breakout_day=None, breakout_close=103.0):
    """高さ100の横ばいに、V字の底を作る。bottoms = {日: 安値}。"""
    low = [100.0] * length
    for day, bottom in bottoms.items():
        low[day - 2], low[day - 1] = min(100, bottom + 3), bottom + 1.5
        low[day] = bottom
        low[day + 1], low[day + 2] = bottom + 1.6, min(100, bottom + 3.1)
    df = pd.DataFrame({"low": low})
    df["high"] = df["low"] + 2
    df["close"] = df["low"] + 1
    df["open"] = df["close"]
    if breakout_day is not None:
        df.loc[breakout_day, ["close", "high"]] = [breakout_close, breakout_close + 1]
    return df


def test_double_bottom_neckline_break():
    df = bottoms_df({10: 95, 20: 96}, breakout_day=26)
    assert pat.multi_bottoms(df, cfg()) == [
        {"count": 2, "points": [10, 20], "neckline": 102.0, "breakout": 26, "confirmed": 26}
    ]


def test_no_double_bottom_without_neckline_break():
    assert pat.multi_bottoms(bottoms_df({10: 95, 20: 96}), cfg()) == []


def test_no_double_bottom_if_close_only_touches_neckline():
    df = bottoms_df({10: 95, 20: 96}, breakout_day=26, breakout_close=102.0)
    assert pat.multi_bottoms(df, cfg()) == []


def test_no_double_bottom_if_bottoms_are_at_different_levels():
    df = bottoms_df({10: 90, 20: 96}, breakout_day=26)
    assert pat.multi_bottoms(df, cfg()) == []


def test_no_double_bottom_if_breakout_is_too_late():
    df = bottoms_df({10: 95, 20: 96}, breakout_day=45)  # 2番底から25日後
    assert pat.multi_bottoms(df, cfg()) == []


def test_no_double_bottom_if_price_falls_through_before_breakout():
    df = bottoms_df({10: 95, 20: 96, 30: 91}, breakout_day=36)
    assert [e for e in pat.multi_bottoms(df, cfg()) if e["points"] == [10, 20]] == []


def test_double_bottom_signal_waits_until_bottom_is_confirmed():
    # 2番底の翌日にネックラインを抜けても、底の確定（3日後）まではサインにしない
    df = bottoms_df({10: 95, 20: 96}, breakout_day=21)
    assert pat.multi_bottoms(df.iloc[:23], cfg()) == []
    events = pat.multi_bottoms(df.iloc[:24], cfg())
    assert events[0]["breakout"] == 21 and events[0]["confirmed"] == 23


def test_triple_bottom():
    df = bottoms_df({10: 95, 20: 96, 30: 95.5}, breakout_day=35)
    events = pat.multi_bottoms(df, cfg())
    triple = [e for e in events if e["count"] == 3]
    assert triple == [
        {"count": 3, "points": [10, 20, 30], "neckline": 102.0, "breakout": 35, "confirmed": 35}
    ]
    assert [e["points"] for e in events if e["count"] == 2] == [[20, 30]]


# ---- ダブルトップ ----

def tops_df(tops, breakdown_day=None, length=60):
    """bottoms_df を上下逆にしたもの（高さ100の横ばいに逆V字の天井）。"""
    mirror = bottoms_df({day: 200 - high for day, high in tops.items()}, length)
    df = pd.DataFrame({"high": 200 - mirror["low"], "low": 200 - mirror["high"]})
    df["close"] = df["high"] - 1
    df["open"] = df["close"]
    if breakdown_day is not None:
        df.loc[breakdown_day, ["close", "low"]] = [97.0, 96.0]
    return df


def test_double_top_neckline_break():
    df = tops_df({10: 105, 20: 104}, breakdown_day=26)
    assert pat.multi_tops(df, cfg()) == [
        {"count": 2, "points": [10, 20], "neckline": 98.0, "breakout": 26, "confirmed": 26}
    ]
    assert pat.multi_bottoms(df, cfg()) == []


def test_no_double_top_without_neckline_break():
    assert pat.multi_tops(tops_df({10: 105, 20: 104}), cfg()) == []


# ---- 圏との組み合わせ ----

def falling_then(extra):
    return make_df([130 - 0.5 * i for i in range(60)] + [c for _, c in extra],
                   open_=[130.5 - 0.5 * i for i in range(60)] + [o for o, _ in extra])


def rising_then(extra):
    return make_df([100 + 0.5 * i for i in range(60)] + [c for _, c in extra],
                   open_=[99.5 + 0.5 * i for i in range(60)] + [o for o, _ in extra])


def test_engulfing_counts_only_in_low_zone():
    low = reversal_signs(falling_then([(100.5, 98), (97.5, 101)]), cfg())
    high = reversal_signs(rising_then([(129.5, 127), (126.5, 130)]), cfg())
    assert low["engulfing"].iloc[-1]
    assert not high["engulfing"].iloc[-1]


def test_harami_is_reversal_at_bottom_and_warning_at_top():
    bottom = falling_then([(100.5, 96), (97, 98)])
    top = rising_then([(129.5, 134), (133, 132)])
    assert reversal_signs(bottom, cfg())["harami"].iloc[-1]
    assert not warning_signs(bottom, cfg())["harami_top"].iloc[-1]
    assert warning_signs(top, cfg())["harami_top"].iloc[-1]
    assert not reversal_signs(top, cfg())["harami"].iloc[-1]


def test_hanging_man_counts_only_in_high_zone():
    def with_last(base):
        df = base.copy()
        o = df["close"].iloc[-2]
        df.iloc[-1] = [o, o + 0.1, o - 3, o - 0.5]  # open, high, low, close
        return df

    top = with_last(rising_then([(129.5, 130)]))
    bottom = with_last(falling_then([(100.5, 100)]))
    assert warning_signs(top, cfg())["hanging_man"].iloc[-1]
    assert not warning_signs(bottom, cfg())["hanging_man"].iloc[-1]


def test_two_black_is_reported_as_warning():
    df = candles([(100, 101, 99, 100)] * 60 + [(97, 98, 95.5, 96), (96, 97, 94, 95)])
    assert warning_signs(df, cfg())["two_black"].iloc[-1]


# ---- エントリー候補への昇格 ----

def entry(counts, reversal_days):
    index = range(len(counts))
    buy = pd.DataFrame({"count": counts}, index=index)
    rev = pd.DataFrame({"engulfing": [d in reversal_days for d in index], "doji": False}, index=index)
    return list(entry_candidates(buy, rev, cfg())[lambda s: s].index)


def test_entry_needs_both_condition_and_reversal():
    assert entry([0, 2, 0, 0, 0], reversal_days=[3]) == [3]


def test_condition_alone_is_not_entry():
    assert entry([0, 2, 3, 1, 0], reversal_days=[]) == []


def test_reversal_alone_is_not_entry():
    assert entry([0, 0, 0, 0, 0], reversal_days=[3]) == []


def test_entry_expires_after_lookback():
    counts = [1] + [0] * 14
    assert entry(counts, reversal_days=[9]) == [9]    # 点灯した日を含めて10日目
    assert entry(counts, reversal_days=[10]) == []

import pandas as pd

from screener import indicators as ind
from screener.signals import bb_divergences, buy_conditions, ma100_bounce, mark_days
from tests.helpers import cfg, make_df

FLAT = [100.0] * 30


def last(df):
    return buy_conditions(df, cfg()).iloc[-1]


# ---- 条件1: 急落 ----

def test_cond1_lights_at_exactly_minus_2_5():
    assert last(make_df(FLAT + [97.5]))["cond1"]


def test_cond1_off_for_smaller_drop():
    assert not last(make_df(FLAT + [97.6]))["cond1"]


# ---- 条件2: 25日線からの乖離 ----

def test_cond2_lights_when_far_below_ma25():
    row = last(make_df(FLAT + [94.0]))  # 25日平均 99.76 → 乖離 -5.8%
    assert row["cond2"]
    assert row["deviation_pct"] < -5


def test_cond2_off_when_close_to_ma25():
    assert not last(make_df(FLAT + [96.0]))["cond2"]  # 乖離 -3.9%


# ---- 条件3: ボリンジャーバンド ----

WAVY = [98.0, 102.0] * 15  # 標準偏差 2 前後で上下する株価


def test_cond3_off_inside_band():
    row = last(make_df(WAVY + [97.0]))
    assert not row["cond3"]
    assert row["bb_level"] == 0


def test_cond3_distinguishes_2_sigma_and_3_sigma():
    two = last(make_df(WAVY + [95.0]))
    three = last(make_df(WAVY + [90.0]))
    assert two["cond3"] and two["bb_level"] == 2
    assert three["cond3"] and three["bb_level"] == 3


def test_cond3_levels_match_the_bands():
    for price, level in ((95.0, 2), (90.0, 3)):
        df = make_df(WAVY + [price])
        bb = ind.bollinger(df["close"], 20, 0).iloc[-1]
        if level == 2:
            assert bb["lower3"] < price <= bb["lower2"]
        else:
            assert price <= bb["lower3"]


def test_cond3_uses_low_by_default_and_close_when_configured():
    # 安値だけが-2σに触れ、終値はバンドの内側に戻した日
    df = make_df(WAVY + [99.0], low=WAVY + [94.0])
    assert buy_conditions(df, cfg()).iloc[-1]["cond3"]
    c = cfg()
    c["buy"]["bb_touch"] = "close"
    assert not buy_conditions(df, c).iloc[-1]["cond3"]


def test_cond3_off_when_price_has_not_moved_at_all():
    # 売買停止などで値段が動かないと、バンドの幅がゼロになる。到達とはみなさない
    row = last(make_df(FLAT))
    assert not row["cond3"]
    assert row["count"] == 0


# ---- 条件4: RCI ----

def test_cond4_lights_after_nine_falling_days():
    falling = [100 - i * 0.5 for i in range(1, 10)]
    row = last(make_df(FLAT + falling))
    assert row["cond4"]
    assert row["rci"] <= -90


def test_cond4_off_when_flat_then_up():
    assert not last(make_df(FLAT + [101.0]))["cond4"]


# ---- 点灯数 ----

def test_count_is_zero_on_quiet_day():
    assert last(make_df(FLAT + [100.5]))["count"] == 0


def test_count_all_four():
    # 9日続落の最後に急落 → 4条件すべて点灯。条件3は-3σでも1つとして数える
    falling = [100 - i * 0.5 for i in range(1, 9)] + [90.0]
    row = last(make_df(FLAT + falling))
    assert row["cond1"] and row["cond2"] and row["cond3"] and row["cond4"]
    assert row["count"] == 4


def test_no_signal_while_data_is_too_short():
    result = buy_conditions(make_df([100.0, 90.0, 80.0]), cfg())
    assert not result[["cond2", "cond3", "cond4"]].any().any()


def test_us_uses_same_logic_with_its_own_thresholds():
    c = cfg("us")
    c["buy"]["drop_pct"] = -4.0
    df = make_df(FLAT + [97.0])
    assert not buy_conditions(df, c).iloc[-1]["cond1"]
    assert buy_conditions(df, cfg("jp")).iloc[-1]["cond1"]


# ---- 補助: 100日線での反発 ----

def bounce(close, open_, low, ma_mid=110.0, ma_long=100.0):
    df = make_df(close, open_=open_, low=low)
    mid = pd.Series(ma_mid, index=df.index)
    long_ = pd.Series(ma_long, index=df.index)
    return ma100_bounce(df, mid, long_, cfg())


def test_bounce_detected():
    # 100日線(100)まで下げ、翌日に陽線で反発。25日線(110)はまだ下回っている
    result = bounce(close=[108, 104, 101, 103], open_=[109, 107, 104, 101], low=[107, 103, 100.5, 101])
    assert list(result) == [False, False, False, True]


def test_no_bounce_if_never_near_ma100():
    result = bounce(close=[108, 106, 105, 107], open_=[109, 108, 106, 105], low=[107, 105, 104, 105])
    assert not result.any()


def test_no_bounce_if_closed_below_ma100():
    result = bounce(close=[104, 101, 98, 99], open_=[107, 104, 101, 98], low=[103, 100, 97, 98])
    assert not result.any()


def test_no_bounce_if_above_ma25():
    result = bounce(
        close=[108, 104, 101, 103], open_=[109, 107, 104, 101], low=[107, 103, 100.5, 101], ma_mid=102.0
    )
    assert not result.any()


def test_no_bounce_on_bearish_day():
    result = bounce(close=[108, 104, 101, 100.8], open_=[109, 107, 104, 102], low=[107, 103, 100.5, 100.6])
    assert not result.any()


def test_bounce_expires_after_lookback():
    # 100日線に触れてから6日以上たった反発は対象外（lookback_days = 5）
    close = [101, 104, 104, 104, 104, 104, 103, 105]
    open_ = [104, 101, 104, 104, 104, 104, 104, 103]
    low = [100.5, 102, 103, 103, 103, 103, 102.5, 103]
    result = bounce(close, open_, low)
    assert result.iloc[1]
    assert not result.iloc[-1]


# ---- 補助: -2σのダイバージェンス ----

def two_bottoms(first, second, gap=10, length=40):
    """高さ100の横ばいに、V字の底を2つ作る。-2σの線は95で固定。"""
    low = [100.0] * length
    for day, bottom in ((10, first), (10 + gap, second)):
        if day + 2 >= length:
            continue
        low[day - 2], low[day - 1] = min(100, bottom + 3), bottom + 1.5
        low[day] = bottom
        low[day + 1], low[day + 2] = bottom + 1.6, min(100, bottom + 3.1)
    df = pd.DataFrame({"low": low})
    df["high"] = df["low"] + 2
    df["open"] = df["close"] = df["low"] + 1
    return df, pd.Series(95.0, index=df.index)


def test_divergence_detected():
    df, band = two_bottoms(first=94, second=96)
    events = bb_divergences(df, band, cfg())
    assert events == [{"first": 10, "second": 20, "confirmed": 23}]
    marks = mark_days(events, df.index)
    assert marks.iloc[23] and marks.sum() == 1


def test_no_divergence_if_second_bottom_also_breaks_band():
    df, band = two_bottoms(first=94, second=94.5)
    assert bb_divergences(df, band, cfg()) == []


def test_no_divergence_if_first_bottom_stays_inside_band():
    df, band = two_bottoms(first=95.5, second=96)
    assert bb_divergences(df, band, cfg()) == []


def test_no_divergence_if_second_bottom_too_shallow():
    df, band = two_bottoms(first=94, second=97.5)  # 94 の +3% = 96.82 より上
    assert bb_divergences(df, band, cfg()) == []


def test_no_divergence_if_bottoms_too_far_apart():
    df, band = two_bottoms(first=94, second=96, gap=45, length=70)
    assert bb_divergences(df, band, cfg()) == []


def test_no_divergence_without_rebound_between_bottoms():
    # 底と底の間の高値は102（1番底から+8.5%）。必要な戻りを10%にすると検出されない
    df, band = two_bottoms(first=94, second=96)
    c = cfg()
    c["bb_divergence"]["min_rebound_pct"] = 10.0
    assert bb_divergences(df, band, c) == []


def test_divergence_not_known_before_confirmation_day():
    # 2番底の3日後（確定日）より前のデータだけでは検出されない
    df, band = two_bottoms(first=94, second=96)
    assert bb_divergences(df.iloc[:23], band.iloc[:23], cfg()) == []
    assert len(bb_divergences(df.iloc[:24], band.iloc[:24], cfg())) == 1

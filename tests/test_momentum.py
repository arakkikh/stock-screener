import numpy as np
import pandas as pd
import pytest

from screener import momentum as mo
from tests.helpers import cfg


def frame(close, volume=1000.0):
    """終値の並びから株価データを作る（高値 = 終値+0.5、安値 = 終値−0.5）。"""
    close = pd.Series(close, dtype=float)
    volume = pd.Series(volume, index=close.index, dtype=float) if np.isscalar(volume) else pd.Series(volume, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": volume})


def path(points):
    """(日, 値段) の点を直線でつないだ終値の並びを作る。"""
    days, prices = zip(*points)
    return list(np.interp(range(days[-1] + 1), days, prices))


def line(start, end, days=300):
    return list(np.linspace(start, end, days))


# ---- 相対強度（RS）----

def closes_table(ends):
    """253日分。1年前はすべて100で、最後の値だけが違う銘柄の表。"""
    return pd.DataFrame({name: line(100, end, 253) for name, end in ends.items()})


def test_rs_ranks_stronger_stocks_higher():
    ratings = mo.rs_ratings(mo.rs_scores(closes_table({"A": 200, "B": 150, "C": 100, "D": 80}), cfg()))
    assert ratings["A"] > ratings["B"] > ratings["C"] > ratings["D"]
    assert ratings["A"] == 99


def test_rs_rating_range_is_1_to_99():
    table = closes_table({f"S{i:03d}": 100 + i for i in range(100)})
    ratings = mo.rs_ratings(mo.rs_scores(table, cfg()))
    assert ratings.min() == 1 and ratings.max() == 99
    assert ratings["S099"] == 99 and ratings["S000"] == 1
    assert ratings["S069"] == 70  # 上から30%の位置


def test_rs_weights_recent_three_months_double():
    # どちらも1年で +20%。A は直近3か月だけで上げ、B は最初の9か月で上げた
    a = [100.0] * 190 + line(100, 120, 63)
    b = line(100, 120, 190) + [120.0] * 63
    scores = mo.rs_scores(pd.DataFrame({"A": a, "B": b}), cfg())
    assert scores["A"] > scores["B"]
    # A: 3か月 +20% を2倍、6・9か月は +20%、12か月 +20% → 0.2*2 + 0.2 + 0.2 + 0.2
    assert scores["A"] == pytest.approx(1.0)


def test_rs_uses_weights_from_config():
    c = cfg()
    c["momentum"]["rs"]["weights"] = [1, 0, 0, 0]
    a = [100.0] * 190 + line(100, 120, 63)
    assert mo.rs_scores(pd.DataFrame({"A": a}), c)["A"] == pytest.approx(0.2)


def test_rs_excludes_stocks_without_one_year_of_data():
    table = closes_table({"A": 200, "B": 150})
    table["NEW"] = [np.nan] * 100 + line(100, 300, 153)
    scores = mo.rs_scores(table, cfg())
    assert np.isnan(scores["NEW"])
    assert "NEW" not in mo.rs_ratings(scores).index


def test_rs_needs_enough_rows():
    assert mo.rs_scores(closes_table({"A": 200}).iloc[:200], cfg()).isna().all()


# ---- トレンドテンプレート ----

def test_template_all_pass_in_strong_uptrend():
    result = mo.trend_template(frame(line(100, 200)), 85, cfg())
    assert result["conds"] == [True] * 8
    assert result["count"] == 8 and result["passed"]


def test_template_rs_below_70_fails_only_condition_8():
    result = mo.trend_template(frame(line(100, 200)), 69, cfg())
    assert result["conds"] == [True] * 7 + [False]
    assert result["count"] == 7 and not result["passed"]


def test_template_rs_exactly_70_passes():
    assert mo.trend_template(frame(line(100, 200)), 70, cfg())["conds"][7]


def test_template_without_rs_fails_condition_8():
    assert not mo.trend_template(frame(line(100, 200)), None, cfg())["conds"][7]


def test_template_downtrend_fails():
    result = mo.trend_template(frame(line(200, 100)), 99, cfg())
    assert result["conds"][:7] == [False] * 7
    assert not result["passed"]


def test_template_slow_rise_fails_only_condition_6():
    # 1年で +8% ほど。線の並びは良いが、52週安値から +30% に届かない
    result = mo.trend_template(frame(line(100, 110)), 90, cfg())
    assert result["conds"] == [True, True, True, True, True, False, True, True]
    assert result["from_low_pct"] < 30


def test_template_deep_pullback_fails_high_and_ma_conditions():
    # 200まで上げてから140へ（高値から −30%）。50日線・150日線の下
    result = mo.trend_template(frame(line(100, 200, 260) + line(198, 140, 40)), 90, cfg())
    assert not result["conds"][6]   # 条件7: 52週高値から −25% 以内
    assert not result["conds"][4]   # 条件5: 株価 > 50日線
    assert result["from_high_pct"] == pytest.approx((140 / 200.5 - 1) * 100)


def test_template_200_day_line_must_be_rising():
    # 長く下げたあと急反発。株価は線の上だが、200日線はまだ下向き
    result = mo.trend_template(frame(line(200, 100, 270) + line(102, 190, 30)), 90, cfg())
    assert result["conds"][0]       # 株価は150日・200日線の上
    assert not result["conds"][2]   # 200日線は下向き
    assert not result["conds"][1]   # 150日線 < 200日線


def test_template_thresholds_come_from_config():
    c = cfg()
    c["momentum"]["template"]["above_low_pct"] = 5
    assert mo.trend_template(frame(line(100, 110)), 90, c)["passed"]


def test_template_returns_none_without_enough_history():
    assert mo.trend_template(frame(line(100, 200, 221)), 90, cfg()) is None
    assert mo.trend_template(frame(line(100, 200, 252)), 90, cfg()) is not None


# ---- VCP ----

# 50→100 と上げたあと、−20% → −9% → −4% と押しが浅くなるベース
BASE = [(0, 50), (30, 100), (40, 80), (50, 98), (58, 89), (66, 97), (72, 93), (78, 96)]


def vcp_frame(points=BASE, extra=(), volumes=None):
    close = path(points) + [c for c, _ in extra]
    if volumes is None:
        # 収縮に合わせて出来高が減っていく
        volumes = [1000.0] * 50 + [600.0] * 16 + [300.0] * (points[-1][0] + 1 - 66)
    return frame(close, list(volumes) + [v for _, v in extra])


def test_vcp_forming():
    result = mo.find_vcp(vcp_frame(), cfg())
    assert result["status"] == "forming"
    assert [(leg["high_i"], leg["low_i"]) for leg in result["legs"]] == [(30, 40), (50, 58), (66, 72)]
    depths = [leg["depth"] for leg in result["legs"]]
    assert depths[0] > depths[1] > depths[2]
    assert depths[0] == pytest.approx((100.5 - 79.5) / 100.5 * 100)
    assert result["pivot"] == 97.5 and result["pivot_i"] == 66
    assert result["breakout_i"] is None
    assert result["volume_dry"]


def test_vcp_breakout_with_volume():
    result = mo.find_vcp(vcp_frame(extra=[(99, 2000)]), cfg())
    assert result["status"] == "breakout"
    assert result["breakout_i"] == 79
    assert result["volume_ratio"] >= 1.5


def test_vcp_breakout_without_volume_is_weak():
    result = mo.find_vcp(vcp_frame(extra=[(99, 400)]), cfg())
    assert result["status"] == "weak"
    assert result["volume_ratio"] < 1.5


def test_vcp_close_must_exceed_pivot():
    # 終値がピボット（97.5）ちょうどでは上抜けとみなさない
    assert mo.find_vcp(vcp_frame(extra=[(97.5, 2000)]), cfg())["status"] == "forming"


def test_vcp_breakout_stays_for_a_few_days_then_expires():
    recent = mo.find_vcp(vcp_frame(extra=[(99, 2000), (100, 500), (101, 500)]), cfg())
    assert recent["status"] == "breakout" and recent["breakout_i"] == 79
    old = mo.find_vcp(vcp_frame(extra=[(99, 2000)] + [(100 + i * 0.1, 500) for i in range(6)]), cfg())
    assert old is None


def test_vcp_breakout_that_falls_back_below_pivot_is_failed():
    result = mo.find_vcp(vcp_frame(extra=[(99, 2000), (97, 500)]), cfg())
    assert result["status"] == "failed"
    assert result["breakout_i"] == 79
    # 押し戻されても、終値がピボットより上なら「ブレイクアウト」のまま
    assert mo.find_vcp(vcp_frame(extra=[(99, 2000), (98, 500)]), cfg())["status"] == "breakout"


def test_no_vcp_when_pullbacks_get_deeper():
    points = [(0, 50), (30, 100), (36, 96), (44, 99), (52, 90), (62, 98), (72, 80), (80, 90)]
    assert mo.find_vcp(vcp_frame(points, volumes=[1000.0] * 81), cfg()) is None


def test_no_vcp_when_lows_are_not_rising():
    # 2回目の押しは1回目より浅いが、安値は1回目を割っている（切り上がっていない）
    c = cfg()
    c["momentum"]["vcp"]["max_last_depth_pct"] = 15
    volumes = [1000.0] * 50 + [300.0] * 15
    lower_low = [(0, 50), (30, 100), (40, 88), (50, 97), (58, 87), (64, 93)]
    higher_low = [(0, 50), (30, 100), (40, 88), (50, 97), (58, 89), (64, 93)]
    assert mo.find_vcp(vcp_frame(lower_low, volumes=volumes), c) is None
    assert mo.find_vcp(vcp_frame(higher_low, volumes=volumes), c) is not None


def test_no_vcp_without_volume_dry_up_when_required():
    flat = [1000.0] * 79
    assert mo.find_vcp(vcp_frame(volumes=flat), cfg()) is None
    c = cfg()
    c["momentum"]["vcp"]["require_volume_dry"] = False
    result = mo.find_vcp(vcp_frame(volumes=flat), c)
    assert result is not None and not result["volume_dry"]


def test_no_vcp_with_single_contraction():
    points = [(0, 50), (30, 100), (40, 92), (48, 98)]
    assert mo.find_vcp(vcp_frame(points, volumes=[1000.0] * 49), cfg()) is None


def test_vcp_skips_first_pullback_that_is_too_deep():
    # −40% の押しはベースに含めず、その後の2回（−9% → −4%）だけを収縮として数える
    points = [(0, 50), (30, 100), (40, 60), (50, 98), (58, 89), (66, 97), (72, 93), (78, 96)]
    result = mo.find_vcp(vcp_frame(points), cfg())
    assert [(leg["high_i"], leg["low_i"]) for leg in result["legs"]] == [(50, 58), (66, 72)]


def test_no_vcp_when_last_contraction_is_too_deep():
    c = cfg()
    c["momentum"]["vcp"]["max_last_depth_pct"] = 3
    assert mo.find_vcp(vcp_frame(), c) is None


def test_no_vcp_when_highs_keep_rising_like_stairs():
    # 山が毎回大きく切り上がるのは上昇の途中で、ベースではない
    points = [(0, 50), (30, 100), (40, 85), (50, 115), (58, 105), (66, 130), (72, 125), (78, 128)]
    assert mo.find_vcp(vcp_frame(points), cfg()) is None


def test_vcp_ignores_peaks_older_than_lookback():
    c = cfg()
    c["momentum"]["vcp"]["lookback_days"] = 35  # 30日目・40日目あたりの山が範囲外になる
    result = mo.find_vcp(vcp_frame(), c)
    assert [(leg["high_i"], leg["low_i"]) for leg in result["legs"]] == [(50, 58), (66, 72)]


def test_vcp_does_not_use_future_data():
    # 途中までのデータで判定した結果は、その時点で確定している山だけを使う
    full = vcp_frame()
    early = mo.find_vcp(full.iloc[:70], cfg())  # 66日目の山は、まだ確定していない
    assert early is None or early["pivot_i"] <= 64


# ---- 50日線割れ ----

def test_ma_break_with_volume():
    close = [100.0] * 60 + [95.0]
    result = mo.ma_break_with_volume(frame(close, [1000.0] * 60 + [1500.0]), cfg())
    assert result.iloc[-1] and result.sum() == 1


def test_ma_break_without_volume_is_ignored():
    close = [100.0] * 60 + [95.0]
    assert not mo.ma_break_with_volume(frame(close, [1000.0] * 60 + [1400.0]), cfg()).any()


def test_ma_break_only_on_the_day_it_crosses():
    close = [100.0] * 60 + [95.0, 94.0]
    result = mo.ma_break_with_volume(frame(close, [1000.0] * 60 + [1500.0, 3000.0]), cfg())
    assert list(result.iloc[-2:]) == [True, False]


def test_no_ma_break_while_above_the_line():
    close = line(100, 130, 80)
    assert not mo.ma_break_with_volume(frame(close, [1000.0] * 79 + [5000.0]), cfg()).any()

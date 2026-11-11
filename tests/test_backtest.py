import copy

import numpy as np
import pandas as pd
import pytest

from screener import backtest as bt
from screener import momentum as mo
from tests.helpers import candles, cfg, make_df


def flags(index, days):
    return pd.Series([i in days for i in range(len(index))], index=index)


def level(index, value):
    return pd.Series(float(value), index=index)


# ---- その後の値動き ----

def test_forward_return_buys_next_open_and_sells_at_close():
    #            始値 高値 安値 終値
    df = candles([(100, 101, 99, 100), (102, 104, 101, 103), (103, 106, 102, 105), (105, 111, 104, 110)])
    result = bt.forward_returns(df, [1, 2, 3])
    # 0日目のサイン → 1日目の始値102で買う
    assert result[1].iloc[0] == pytest.approx((103 / 102 - 1) * 100)   # 1日後の終値で売る
    assert result[2].iloc[0] == pytest.approx((105 / 102 - 1) * 100)
    assert result[3].iloc[0] == pytest.approx((110 / 102 - 1) * 100)


def test_forward_return_is_nan_when_future_is_unknown():
    df = candles([(100, 101, 99, 100)] * 4)
    result = bt.forward_returns(df, [2])
    assert not np.isnan(result[2].iloc[1])
    assert np.isnan(result[2].iloc[2]) and np.isnan(result[2].iloc[3])


def test_forward_return_does_not_use_signal_day_close_as_entry():
    # サインの日に急騰していても、買値は翌日の始値
    df = candles([(100, 120, 100, 120), (121, 122, 119, 120), (120, 121, 119, 121)])
    assert bt.forward_returns(df, [1])[1].iloc[0] == pytest.approx((120 / 121 - 1) * 100)


def test_worst_drawdown_uses_lows_after_entry():
    df = candles([(100, 101, 50, 100), (100, 101, 95, 100), (100, 101, 90, 100), (100, 101, 99, 100), (100, 101, 80, 100)])
    result = bt.worst_drawdown(df, 2)
    assert result.iloc[0] == pytest.approx(-10.0)   # 1〜2日目の最安値90。サイン当日の安値50は関係ない
    assert result.iloc[1] == pytest.approx(-10.0)   # 2〜3日目
    assert result.iloc[2] == pytest.approx(-20.0)   # 3〜4日目


def test_worst_drawdown_is_never_positive():
    df = candles([(100, 101, 99, 100), (100, 120, 100, 119), (119, 130, 118, 129)])
    assert bt.worst_drawdown(df, 2).iloc[0] == 0


def test_summarize():
    stats = bt.summarize([10.0, -5.0, 2.0, np.nan, 3.0])
    assert stats["n"] == 4 and stats["win"] == 75.0
    assert stats["mean"] == pytest.approx(2.5) and stats["median"] == pytest.approx(2.5)
    assert stats["worst"] == -5.0
    assert bt.summarize([]) is None and bt.summarize([np.nan]) is None


# ---- サインの一覧 ----

def test_signal_flags_match_the_live_signals():
    rng = np.random.default_rng(3)
    close = list(100 + np.cumsum(rng.normal(0, 2.0, 400)))
    df = make_df(close)
    table = bt.signal_flags(df, cfg())
    from screener import signals as sig
    buy = sig.buy_conditions(df, cfg())
    assert (table["cond1"] == buy["cond1"]).all()
    assert (table["count2"] == (buy["count"] >= 2)).all()
    assert (table["bb3"] == (buy["bb_level"] == 3)).all()
    assert (table["entry"] == sig.entry_candidates(buy, sig.reversal_signs(df, cfg()), cfg())).all()
    assert table.dtypes.eq(bool).all()
    assert table["count1"].sum() >= table["count2"].sum() >= table["count3"].sum()


# ---- 売買のシミュレーション ----

def prices(rows):
    return candles([(o, max(o, c) + 1, min(o, c) - 1, c) for o, c in rows])


def test_simulate_takes_profit_at_dynamic_level():
    df = prices([(100, 100), (100, 101), (101, 103), (103, 106), (106, 107)])
    trades = bt.simulate(df, flags(df.index, [0]), take_dynamic=level(df.index, 105), max_hold=20)
    assert trades == [{"entry_i": 1, "exit_i": 3, "ret": pytest.approx(6.0), "reason": "take", "days": 3}]


def test_simulate_fixed_target_is_taken_from_the_signal_day():
    df = prices([(100, 100), (100, 101), (101, 103), (103, 106), (106, 107)])
    target = pd.Series([102.0, 999, 999, 999, 999], index=df.index)   # サインの日(0日目)の値だけ使う
    trades = bt.simulate(df, flags(df.index, [0]), take_fixed=target)
    assert trades[0]["exit_i"] == 2 and trades[0]["reason"] == "take"


def test_simulate_stop_loss_on_close():
    df = prices([(100, 100), (100, 97), (97, 93), (93, 91), (91, 100)])
    trades = bt.simulate(df, flags(df.index, [0]), take_dynamic=level(df.index, 150), stop_pct=-8)
    assert trades[0]["exit_i"] == 3 and trades[0]["reason"] == "stop"
    assert trades[0]["ret"] == pytest.approx(-9.0)


def test_simulate_stop_exactly_at_the_limit():
    df = prices([(100, 100), (100, 92), (92, 95)])
    assert bt.simulate(df, flags(df.index, [0]), stop_pct=-8)[0]["reason"] == "stop"


def test_simulate_stop_flag():
    df = prices([(100, 100), (100, 99), (99, 98), (98, 97)])
    trades = bt.simulate(df, flags(df.index, [0]), stop_flag=flags(df.index, [2]), max_hold=20)
    assert trades[0]["exit_i"] == 2 and trades[0]["reason"] == "stop"


def test_simulate_time_exit():
    df = prices([(100, 100)] + [(100, 101)] * 6)
    trades = bt.simulate(df, flags(df.index, [0]), take_dynamic=level(df.index, 150), max_hold=3)
    assert trades[0]["exit_i"] == 3 and trades[0]["reason"] == "time" and trades[0]["days"] == 3


def test_simulate_holds_one_position_at_a_time():
    df = prices([(100, 100)] * 12)
    trades = bt.simulate(df, flags(df.index, [0, 1, 2, 6]), max_hold=3)
    # 0日目のサインで 1〜3日目を保有。保有中の 1・2日目のサインは無視し、6日目のサインで買い直す
    assert [(t["entry_i"], t["exit_i"]) for t in trades] == [(1, 3), (7, 9)]


def test_simulate_drops_trades_still_open_at_the_end():
    df = prices([(100, 100)] * 4)
    assert bt.simulate(df, flags(df.index, [2]), max_hold=10) == []
    assert bt.simulate(df, flags(df.index, [3]), max_hold=1) == []   # 翌日がないので買えない


def test_simulate_can_exit_on_the_entry_day():
    df = prices([(100, 100), (100, 110), (110, 111)])
    trades = bt.simulate(df, flags(df.index, [0]), take_dynamic=level(df.index, 105))
    assert trades[0]["entry_i"] == 1 and trades[0]["exit_i"] == 1 and trades[0]["days"] == 1


def test_summarize_trades():
    trades = [
        {"ret": 5.0, "reason": "take", "days": 4},
        {"ret": -8.0, "reason": "stop", "days": 2},
        {"ret": 1.0, "reason": "time", "days": 20},
        {"ret": 3.0, "reason": "take", "days": 6},
    ]
    stats = bt.summarize_trades(trades)
    assert stats["n"] == 4 and stats["win"] == 75.0 and stats["days"] == 8.0
    assert (stats["take"], stats["stop"], stats["time"]) == (50.0, 25.0, 25.0)
    assert bt.summarize_trades([]) is None


# ---- 順張り: 過去の全日程 ----

def random_universe(n_stocks=8, days=420, seed=5):
    rng = np.random.default_rng(seed)
    frames = {}
    for i in range(n_stocks):
        drift = 0.0005 * (i - 2)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, 0.015, days))))
        frames[f"S{i}"] = pd.DataFrame(
            {"open": close.shift(1).fillna(close), "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1000.0}
        )
    return frames


def test_template_history_matches_the_daily_judgement():
    frames = random_universe()
    close = pd.DataFrame({c: f["close"] for c, f in frames.items()})
    high = pd.DataFrame({c: f["high"] for c, f in frames.items()})
    low = pd.DataFrame({c: f["low"] for c, f in frames.items()})
    history = bt.template_history(close, high, low, cfg())
    # いくつかの日について、その日までのデータで毎日の判定をやり直し、結果が同じことを確かめる
    checked = passed = 0
    for day in (300, 350, 380, 419):
        ratings = mo.rs_ratings(mo.rs_scores(close.iloc[: day + 1], cfg()))
        for code, frame in frames.items():
            live = mo.trend_template(frame.iloc[: day + 1], ratings.get(code), cfg())
            assert history[code].iloc[day] == live["passed"], (code, day)
            checked += 1
            passed += live["passed"]
    assert checked == 32 and passed > 0   # 合格の例も不合格の例も含まれている


def test_template_history_is_false_without_enough_history():
    frames = random_universe(days=300)
    close = pd.DataFrame({c: f["close"] for c, f in frames.items()})
    history = bt.template_history(close, close * 1.01, close * 0.99, cfg())
    assert not history.iloc[:252].any().any()


def test_vcp_breakout_days_finds_the_breakout_without_looking_ahead():
    points = [(0, 50), (30, 100), (40, 80), (50, 98), (58, 89), (66, 97), (72, 93), (78, 96)]
    days, values = zip(*points)
    close = list(np.interp(range(days[-1] + 1), days, values)) + [99.0, 100.0, 101.0]
    volume = [1000.0] * 50 + [600.0] * 16 + [300.0] * 13 + [2000.0, 500.0, 500.0]
    close = pd.Series(close)
    df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": volume})
    always = pd.Series(True, index=df.index)
    result = bt.vcp_breakout_days(df, always, cfg())
    assert list(result.index[result["breakout"]]) == [79]   # 上抜けた日だけ。翌日以降は数えない
    assert not result["weak"].any()
    # トレンドテンプレートに合格していない日は対象外
    assert not bt.vcp_breakout_days(df, ~always, cfg()).any().any()


def test_vcp_breakout_days_separates_low_volume_breakouts():
    points = [(0, 50), (30, 100), (40, 80), (50, 98), (58, 89), (66, 97), (72, 93), (78, 96)]
    days, values = zip(*points)
    close = pd.Series(list(np.interp(range(days[-1] + 1), days, values)) + [99.0])
    volume = [1000.0] * 50 + [600.0] * 16 + [300.0] * 13 + [400.0]
    df = pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": volume})
    result = bt.vcp_breakout_days(df, pd.Series(True, index=df.index), cfg())
    assert list(result.index[result["weak"]]) == [79] and not result["breakout"].any()


# ---- 銘柄ごとの RCI の水準 ----

def test_rci_level_study_counts_first_day_below_level_and_picks_best():
    rng = np.random.default_rng(11)
    df = make_df(list(100 + np.cumsum(rng.normal(0, 1.5, 600))))
    study = bt.rci_level_study(df, [-70, -80, -90], cfg(), horizon=10, min_samples=5)
    n = {lv: study["levels"][lv]["n"] for lv in (-70, -80, -90)}
    assert n[-70] >= n[-80] >= n[-90] > 0          # 水準が深いほど回数は減る
    assert study["best"] in (-70, -80, -90)
    best = study["levels"][study["best"]]
    assert all(best["mean"] >= s["mean"] for s in study["levels"].values() if s["n"] >= 5)


def test_rci_level_study_ignores_levels_with_too_few_samples():
    rng = np.random.default_rng(11)
    df = make_df(list(100 + np.cumsum(rng.normal(0, 1.5, 600))))
    assert bt.rci_level_study(df, [-70, -80, -90], cfg(), horizon=10, min_samples=10_000)["best"] is None

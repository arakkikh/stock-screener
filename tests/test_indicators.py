import numpy as np
import pandas as pd
import pytest

from screener import indicators as ind


def s(values):
    return pd.Series(values, dtype=float)


def test_sma():
    result = ind.sma(s([1, 2, 3, 4, 5]), 3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_change_pct():
    result = ind.change_pct(s([100, 97.5, 99.45]))
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(-2.5)
    assert result.iloc[2] == pytest.approx(2.0)


def test_deviation_pct():
    # 3日平均 = (100+100+85)/3 = 95 → 乖離率 = (85-95)/95
    result = ind.deviation_pct(s([100, 100, 85]), 3)
    assert result.iloc[2] == pytest.approx(-10 / 95 * 100)


def test_bollinger_hand_calculated():
    # 平均3、標準偏差 √2（母標準偏差）
    bb = ind.bollinger(s([1, 2, 3, 4, 5]), 5, ddof=0).iloc[-1]
    sd = 2**0.5
    assert bb["mid"] == pytest.approx(3.0)
    assert bb["lower2"] == pytest.approx(3 - 2 * sd)
    assert bb["upper2"] == pytest.approx(3 + 2 * sd)
    assert bb["lower3"] == pytest.approx(3 - 3 * sd)
    assert bb["upper3"] == pytest.approx(3 + 3 * sd)


def test_bollinger_ddof_changes_width():
    close = s([1, 2, 3, 4, 5])
    narrow = ind.bollinger(close, 5, ddof=0).iloc[-1]
    wide = ind.bollinger(close, 5, ddof=1).iloc[-1]
    assert wide["upper2"] > narrow["upper2"]


def test_rci_rising_is_plus_100():
    assert ind.rci(s(range(1, 10)), 9).iloc[-1] == pytest.approx(100.0)


def test_rci_falling_is_minus_100():
    assert ind.rci(s(range(9, 0, -1)), 9).iloc[-1] == pytest.approx(-100.0)


def test_rci_hand_calculated():
    # 日付順位 3,2,1 / 価格順位 3,1,2 → d = 0+1+1 = 2 → (1 - 12/24) * 100 = 50
    assert ind.rci(s([10, 12, 11]), 3).iloc[-1] == pytest.approx(50.0)


def test_rci_ties_use_average_rank():
    # 全部同じ値 → 価格順位はすべて2 → d = 1+0+1 = 2 → 50
    assert ind.rci(s([5, 5, 5]), 3).iloc[-1] == pytest.approx(50.0)


def test_rci_needs_full_window():
    result = ind.rci(s([1, 2, 3, 4]), 3)
    assert np.isnan(result.iloc[1])
    assert not np.isnan(result.iloc[2])


def test_rci_stays_in_range():
    rng = np.random.default_rng(0)
    result = ind.rci(s(rng.normal(100, 5, 200)), 9).dropna()
    assert result.between(-100, 100).all()


def test_is_rising():
    result = ind.is_rising(s([1, 2, 2, 1]))
    assert list(result) == [False, True, False, False]

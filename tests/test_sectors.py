"""セクター・テーマの強弱ランキングのテスト。"""
import copy

import numpy as np
import pandas as pd
import pytest

from screener import sectors as sc
from tests.helpers import cfg


def small_cfg(**change):
    c = copy.deepcopy(cfg())
    c["sectors"].update({"periods": [2, 4], "rank_weights": [1, 1], "rank_change_days": 2, "rank_change_min": 1,
                         "min_stocks": 2, "strong_top_pct": 50, **change})
    c["ma"].update({"mid": 3, "long": 5})
    c["regime"]["ma"]["short"] = 3
    return c


def closes_table(columns):
    days = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=pd.bdate_range("2026-01-05", periods=days), dtype=float)


def test_group_index_is_equal_weighted_average_of_daily_returns():
    closes = closes_table({"A": [100, 110, 121], "B": [100, 90, 81]})
    gi = sc.group_index(closes)
    assert list(gi.round(6)) == [1.0, 1.0, 1.0]  # +10% と −10% の平均は 0%


def test_returns_and_excess_over_index():
    closes = closes_table({"A": [100, 100, 100, 110, 120], "B": [100, 100, 100, 110, 120]})
    index = pd.Series([1000, 1000, 1000, 1000, 1050], index=closes.index)
    row = sc.strength(closes, {"機械": ["A", "B"]}, index, small_cfg())[0]
    assert row["r"]["2"] == pytest.approx(20.0)        # 100 → 120
    assert row["x"]["2"] == pytest.approx(15.0)        # 指数は +5%
    assert row["x"]["4"] == pytest.approx(15.0)
    assert row["score"] == pytest.approx(15.0)
    assert row["count"] == 2 and row["few"] is False


def test_ranking_strong_groups_and_rank_change():
    n = 8
    rise = [100 * 1.02 ** i for i in range(n)]
    fall = [100 * 0.98 ** i for i in range(n)]
    late = [100] * (n - 2) + [104, 110]     # 最後に急に強くなる
    flat = [100.0] * n
    closes = closes_table({"A1": rise, "A2": rise, "B1": fall, "B2": fall, "C1": late, "C2": late, "D1": flat})
    index = pd.Series(flat, index=closes.index)
    rows = sc.strength(closes, {"上昇": ["A1", "A2"], "下落": ["B1", "B2"], "急伸": ["C1", "C2"], "少数": ["D1"]},
                       index, small_cfg())
    by = {r["name"]: r for r in rows}
    assert [r["name"] for r in rows][:2] == ["急伸", "上昇"]
    assert by["急伸"]["trend"] == "up" and by["急伸"]["move"] >= 1
    assert by["下落"]["rank"] > by["少数"]["rank"] or by["下落"]["rank"] == 4
    # 上位50%（参考値の「少数」を除く3グループ → 2つ）が強い
    assert {r["name"] for r in rows if r["strong"]} == {"急伸", "上昇"}
    assert by["少数"]["few"] is True and by["少数"]["strong"] is False


def test_percent_above_moving_average_and_downtrend():
    falling = [100, 99, 98, 97, 96, 95, 94, 93]
    closes = closes_table({"A": falling, "B": falling[:-1] + [99]})
    index = pd.Series([100.0] * 8, index=closes.index)
    row = sc.strength(closes, {"X": ["A", "B"]}, index, small_cfg())[0]
    assert row["p_above"] == 50.0       # B だけが3日線より上
    rows = sc.strength(closes_table({"A": falling, "B": falling}), {"X": ["A", "B"]}, index, small_cfg())
    assert rows[0]["downtrend"] is True


def test_missing_history_gives_no_rank():
    closes = closes_table({"A": [100, 101], "B": [100, 102]})
    row = sc.strength(closes, {"X": ["A", "B"]}, pd.Series([1, 1], index=closes.index), small_cfg())[0]
    assert row["score"] is None and row["rank"] is None and row["strong"] is False


def test_reference_series_such_as_sector_etf():
    closes = closes_table({"A": [100, 100, 100, 100, 110], "B": [100, 100, 100, 100, 110]})
    index = pd.Series([100.0] * 5, index=closes.index)
    etf = pd.DataFrame({"close": [50, 50, 50, 50, 52]}, index=closes.index)
    etf.attrs["ticker"] = "XLK"
    row = sc.strength(closes, {"Information Technology": ["A", "B"]}, index, small_cfg(), {"Information Technology": etf})[0]
    assert row["ref"]["ticker"] == "XLK" and row["ref"]["x"]["2"] == pytest.approx(4.0)


def test_groups_from_universe_reads_sector_and_themes():
    universe = pd.DataFrame({"code": ["1", "2", "3"], "sector": ["銀行業", "銀行業", "電気機器"],
                             "themes": ["", "高配当", "半導体|AI"]})
    g = sc.groups_from_universe(universe)
    assert g["sectors"] == {"銀行業": ["1", "2"], "電気機器": ["3"]}
    assert g["themes"] == {"高配当": ["2"], "半導体": ["3"], "AI": ["3"]}

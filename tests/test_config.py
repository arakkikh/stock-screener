import pytest

from screener.config import _merge, load_thresholds


def test_market_overrides_default():
    assert load_thresholds("jp")["thermometer"]["vol_index_min"] == 50
    assert load_thresholds("us")["thermometer"]["vol_index_min"] == 30


def test_values_not_overridden_come_from_default():
    for market in ("jp", "us"):
        cfg = load_thresholds(market)
        assert cfg["thermometer"]["fear_greed_max"] == 20
        assert cfg["buy"]["drop_pct"] == -2.5
        assert cfg["ma"] == {"short": 5, "mid": 25, "long": 100}


def test_merge_does_not_change_the_original():
    base = {"a": {"x": 1, "y": 2}}
    merged = _merge(base, {"a": {"y": 9}})
    assert merged == {"a": {"x": 1, "y": 9}}
    assert base == {"a": {"x": 1, "y": 2}}


def test_unknown_market_is_rejected():
    with pytest.raises(ValueError):
        load_thresholds("uk")


def test_sizing_lot_differs_by_market():
    # 日本株は100株単位、米国株は1株単位。その他の資金管理の値は共通
    jp, us = load_thresholds("jp")["sizing"], load_thresholds("us")["sizing"]
    assert (jp["lot"], us["lot"]) == (100, 1)
    assert jp["risk_pct"] == us["risk_pct"] == 1.0
    assert jp["max_stock_pct"] < jp["max_sector_pct"]


def test_stats_min_samples_is_positive():
    assert load_thresholds("jp")["stats"]["min_samples"] >= 1

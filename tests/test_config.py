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

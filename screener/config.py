"""しきい値の読み込み。default に市場ごとの値を上書きして返す。"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS_PATH = ROOT / "config" / "thresholds.yaml"
MARKETS = ("jp", "us")


def _merge(base: dict, override: dict) -> dict:
    """override の値で base を上書きする（入れ子の辞書は中身ごとに上書き）。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_thresholds(market: str, path: Path = THRESHOLDS_PATH) -> dict:
    if market not in MARKETS:
        raise ValueError(f"市場は {MARKETS} のどちらかを指定してください: {market!r}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _merge(raw["default"], raw.get(market))

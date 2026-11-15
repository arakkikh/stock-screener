"""フォワードテスト（シグナルの自動追跡）のテスト。"""
import copy
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from screener import backtest as bt
from screener import forward as fw
from tests.helpers import cfg, make_df

COL = fw.COL


def dated(df, start="2026-01-05"):
    """テスト用の株価データに営業日の日付を付け、出来高も入れる。"""
    df = df.copy()
    df.index = pd.bdate_range(start, periods=len(df))
    df["volume"] = 1000.0
    return df


def day(df, i):
    return df.index[i].strftime("%Y-%m-%d")


def new_row(date, code="A", kind="entry", close=100.0, version="v1"):
    rows = []
    fw.add_signals(rows, [(code, kind, close)], date, {"contrarian": version, "momentum": version})
    return rows


# ---- その日のシグナル ----

def test_contrarian_signals_collects_entries_and_warnings_of_the_day():
    stocks = [
        {"code": "A", "date": "2026-11-13", "close": 100, "entry": True, "warnings": []},
        {"code": "B", "date": "2026-11-13", "close": 200, "entry": False, "warnings": ["hanging_man", "two_black"]},
        {"code": "C", "date": "2026-11-12", "close": 300, "entry": True, "warnings": [], "stale": True},  # 古いデータ
        {"code": "D", "date": "2026-11-13", "close": 400, "entry": False, "warnings": []},
    ]
    assert fw.contrarian_signals(stocks, "2026-11-13") == [
        ("A", "entry", 100), ("B", "warn:hanging_man", 200), ("B", "warn:two_black", 200),
    ]


def test_momentum_signals_only_counts_breakouts_of_the_day():
    stocks = [
        {"code": "A", "date": "2026-11-13", "close": 1, "vcp": {"status": "breakout", "breakout_date": "2026-11-13"}},
        {"code": "B", "date": "2026-11-13", "close": 2, "vcp": {"status": "breakout", "breakout_date": "2026-11-11"}},  # 前に上抜け済み
        {"code": "C", "date": "2026-11-13", "close": 3, "vcp": {"status": "weak", "breakout_date": "2026-11-13"}},       # 出来高不足
        {"code": "D", "date": "2026-11-13", "close": 4, "vcp": None},
    ]
    assert fw.momentum_signals(stocks, "2026-11-13") == [("A", "breakout", 1)]


def test_add_signals_records_version_by_mode_and_skips_duplicates():
    rows = []
    versions = {"contrarian": "c1", "momentum": "m1"}
    signals = [("A", "entry", 100.0), ("B", "breakout", 50.0)]
    assert fw.add_signals(rows, signals, "2026-11-13", versions) == 2
    assert fw.add_signals(rows, signals, "2026-11-13", versions) == 0  # やり直しても重複しない
    assert [(r[COL["c"]], r[COL["v"]], r[COL["s"]]) for r in rows] == [("A", "c1", fw.PENDING), ("B", "m1", fw.PENDING)]
    assert len(rows[0]) == len(fw.FIELDS)


# ---- 設定の番号 ----

def test_config_version_changes_only_when_related_thresholds_change():
    base = cfg()
    v = fw.config_version(base, "contrarian")
    assert v == fw.config_version(copy.deepcopy(base), "contrarian")
    changed = copy.deepcopy(base)
    changed["buy"]["rci_max"] = -80
    assert fw.config_version(changed, "contrarian") != v
    assert fw.config_version(changed, "momentum") == fw.config_version(base, "momentum")  # 順張りには関係ない
    unrelated = copy.deepcopy(base)
    unrelated["sizing"]["risk_pct"] = 2  # 資金管理の値は判定に関係しない
    assert fw.config_version(unrelated, "contrarian") == v
    mo = copy.deepcopy(base)
    mo["momentum"]["template"]["rs_min"] = 80
    assert fw.config_version(mo, "momentum") != fw.config_version(base, "momentum")


# ---- その後の成績 ----

def test_fill_outcomes_matches_backtest_forward_returns_and_index():
    rng = np.random.default_rng(0)
    df = dated(make_df(100 + rng.normal(0, 1, 60).cumsum()))
    index = dated(make_df(1000 + rng.normal(0, 5, 60).cumsum()))
    i = 10
    rows = new_row(day(df, i), kind="warn:hanging_man")
    fw.fill_outcomes(rows, {"A": df}, index, cfg(), "contrarian", dt.date(2026, 4, 1))
    expected = bt.forward_returns(df, list(fw.HORIZONS)).iloc[i]
    expected_index = bt.forward_returns(index, list(fw.HORIZONS)).iloc[i]
    for h in fw.HORIZONS:
        assert rows[0][COL[f"r{h}"]] == pytest.approx(expected[h], abs=0.01)
        assert rows[0][COL[f"i{h}"]] == pytest.approx(expected_index[h], abs=0.01)
    assert rows[0][COL["s"]] == fw.DONE  # 警戒サインは売買しないので、騰落率がそろえば完了
    assert rows[0][COL["xr"]] is None


def test_fill_outcomes_fills_step_by_step_as_data_arrives():
    df = dated(make_df([100.0] * 30))
    rows = new_row(day(df, 20), kind="warn:doji")
    fw.fill_outcomes(rows, {"A": df.iloc[:27]}, None, cfg(), "contrarian", dt.date(2026, 2, 13))
    assert rows[0][COL["r5"]] == 0.0 and rows[0][COL["r10"]] is None and rows[0][COL["s"]] == fw.PENDING
    assert rows[0][COL["i5"]] is None  # 指数のデータがなければ空のまま
    fw.fill_outcomes(rows, {"A": df}, None, cfg(), "contrarian", dt.date(2026, 2, 17))
    assert rows[0][COL["r10"]] is None  # まだ10営業日たっていない


def test_fill_outcomes_records_exit_rule_trade_for_entry():
    # 25日線より下で買い、25日線まで戻ったら利確
    closes = [100.0] * 30 + [90.0] * 5 + [92, 94, 96, 99, 101] + [101.0] * 20
    df = dated(make_df(closes))
    i = 34  # 90 が続いた最後の日
    rows = new_row(day(df, i), kind="entry")
    fw.fill_outcomes(rows, {"A": df}, None, cfg(), "contrarian", dt.date(2026, 6, 1))
    trades = bt.simulate(df, pd.Series([k == i for k in range(len(df))], index=df.index),
                         take_dynamic=df["close"].rolling(25).mean(), max_hold=20)
    assert rows[0][COL["xe"]] == "take"
    assert rows[0][COL["xr"]] == pytest.approx(trades[0]["ret"], abs=0.01)
    assert rows[0][COL["xd"]] == trades[0]["days"]
    assert rows[0][COL["s"]] == fw.DONE


def test_fill_outcomes_uses_momentum_stop_for_breakout():
    closes = [100.0] * 60 + [100, 95, 91, 90] + [90.0] * 30
    df = dated(make_df(closes))
    rows = new_row(day(df, 59), kind="breakout")
    c = cfg()
    fw.fill_outcomes(rows, {"A": df}, None, c, "contrarian", dt.date(2026, 9, 1))
    assert rows[0][COL["r5"]] is None  # 逆張りの更新では、順張りのシグナルは埋めない
    fw.fill_outcomes(rows, {"A": df}, None, c, "momentum", dt.date(2026, 9, 1))
    assert rows[0][COL["xe"]] == "stop"  # −8% の損切り（100 → 91 で −9%）
    assert rows[0][COL["xr"]] == pytest.approx(-9.0)


def test_fill_outcomes_gives_up_after_limit():
    rows = new_row("2026-01-05")
    fw.fill_outcomes(rows, {}, None, cfg(), "contrarian", dt.date(2026, 3, 1))
    assert rows[0][COL["s"]] == fw.PENDING
    fw.fill_outcomes(rows, {}, None, cfg(), "contrarian", dt.date(2026, 6, 1))  # 120日を過ぎた
    assert rows[0][COL["s"]] == fw.LOST


# ---- 集計 ----

def finished(date, kind, version, returns, index=None, exit_=None):
    row = new_row(date, kind=kind, version=version)[0]
    for h, value in zip(fw.HORIZONS, returns):
        row[COL[f"r{h}"]] = value
    for h, value in zip(fw.HORIZONS, index or [None] * 3):
        row[COL[f"i{h}"]] = value
    if exit_:
        row[COL["xr"]], row[COL["xd"]], row[COL["xe"]] = exit_
    row[COL["s"]] = fw.DONE
    return row


def test_summary_separates_kinds_and_versions_and_compares_with_index():
    rows = [
        finished("2026-11-02", "entry", "old", [1, 2, 3], [0, 1, 1], (2.0, 5, "take")),
        finished("2026-11-09", "entry", "new", [2, -2, 4], [1, 1, 1], (-1.0, 20, "time")),
        finished("2026-11-10", "entry", "new", [4, 6, 8], [1, 2, None], (3.0, 3, "take")),
        finished("2026-11-10", "warn:doji", "new", [-1, -2, 1]),
    ]
    lost = new_row("2026-07-01", kind="entry", version="new")[0]
    lost[COL["s"]] = fw.LOST
    s = fw.summarize_rows(rows + [lost])
    groups = {(g["group"], g["version"]): g for g in s["groups"]}
    assert set(groups) == {("entry", "old"), ("entry", "new"), ("warn", "new")}
    new = groups[("entry", "new")]
    assert (new["signals"], new["lost"], new["first"]) == (3, 1, "2026-07-01")
    assert new["h"]["5"]["n"] == 2 and new["h"]["5"]["mean"] == 3.0 and new["h"]["5"]["win"] == 100.0
    assert new["h"]["10"]["mean"] == 2.0 and new["h"]["10"]["index"] == 1.5 and new["h"]["10"]["excess"] == 0.5
    assert new["h"]["20"]["index"] == 1.0  # 指数がそろっている1件だけで比べる
    assert new["exit"]["n"] == 2 and new["exit"]["mean"] == 1.0 and new["exit"]["take"] == 50.0
    warn = groups[("warn", "new")]
    assert warn["h"]["10"]["hit"] == 100.0 and warn["exit"] is None
    assert s["warn_types"]["doji"]["signals"] == 1


# ---- 保存 ----

def test_update_writes_yearly_files_versions_and_summary(tmp_path):
    rng = np.random.default_rng(1)
    df = dated(make_df(100 + rng.normal(0, 1, 60).cumsum()), start="2026-10-01")
    as_of = df.index[20].date()
    c = cfg()
    now = dt.datetime(2026, 11, 15, tzinfo=dt.timezone.utc)
    signals = [("A", "warn:doji", 100.0), ("A", "entry", 100.0)]
    r = fw.update(tmp_path, "jp", c, as_of, "contrarian", signals, {"A": df.iloc[:21]}, df.iloc[:21], now)
    assert r == {"added": 2, "finished": 0, "total": 2}
    # 翌日以降の更新で成績が埋まる。同じ日をやり直しても重複しない
    later = df.index[59].date()
    r = fw.update(tmp_path, "jp", c, later, "contrarian", [], {"A": df}, df, now)
    assert r["total"] == 2 and r["finished"] >= 1

    data = json.loads((tmp_path / f"jp_{as_of.year}.json").read_text())
    assert data["fields"] == fw.FIELDS and len(data["rows"]) == 2
    text = (tmp_path / f"jp_{as_of.year}.json").read_text()
    assert text.count("\n") == len(data["rows"]) + 2  # 1行に1件
    summary = json.loads((tmp_path / "jp_summary.json").read_text())
    assert summary["started"] == as_of.isoformat()
    assert summary["current"]["contrarian"] in summary["versions"]
    assert {g["group"] for g in summary["groups"]} == {"entry", "warn"}

    # しきい値を変えると、新しい番号が登録され、使い始めた日が記録される
    changed = copy.deepcopy(c)
    changed["entry"]["min_conditions"] = 3
    fw.update(tmp_path, "jp", changed, later, "contrarian", [("B", "entry", 50.0)], {"A": df}, df, now)
    versions = json.loads((tmp_path / "jp_versions.json").read_text())
    new = fw.config_version(changed, "contrarian")
    assert versions[new]["first"] == later.isoformat() and versions[new]["config"]["entry"]["min_conditions"] == 3
    summary = json.loads((tmp_path / "jp_summary.json").read_text())
    assert {g["version"] for g in summary["groups"] if g["group"] == "entry"} == {new, fw.config_version(c, "contrarian")}


def test_loading_a_file_with_different_fields_is_refused(tmp_path):
    (tmp_path / "jp_2026.json").write_text(json.dumps({"fields": ["d"], "rows": []}))
    with pytest.raises(ValueError):
        fw.load_rows(tmp_path, "jp", [2026])

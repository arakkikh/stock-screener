"""イベントカレンダーのテスト。"""
import datetime as dt

import pytest

from screener import events as ev

D = dt.date


def test_nth_weekday():
    assert ev.nth_weekday(2026, 12, 4, 2) == D(2026, 12, 11)   # 2026年12月の第2金曜
    assert ev.nth_weekday(2026, 11, 4, 3) == D(2026, 11, 20)   # 2026年11月の第3金曜
    assert ev.nth_weekday(2027, 1, 4, 2) == D(2027, 1, 8)


def test_sq_dates_mark_major_months():
    s = ev.Sessions("jp")
    found = ev.sq_dates(s, D(2026, 11, 1), D(2027, 3, 31))
    assert [(e["date"], e["kind"]) for e in found] == [
        (D(2026, 11, 13), "sq"), (D(2026, 12, 11), "major_sq"), (D(2027, 1, 8), "sq"),
        (D(2027, 2, 12), "sq"), (D(2027, 3, 12), "major_sq"),
    ]


def test_sq_moves_to_previous_session_on_holiday():
    s = ev.Sessions("jp")
    # 2027年2月12日(金)は営業日。休場の場合の扱いは、休場日に当たる金曜を作って確かめる
    holiday_friday = next(h["date"] for h in s.holidays(D(2026, 1, 1), D(2027, 11, 1)) if h["date"].weekday() == 4)
    assert s.on_or_before(holiday_friday) == s.previous(holiday_friday) < holiday_friday


def test_us_option_expiration_is_third_friday():
    s = ev.Sessions("us")
    found = ev.opex_dates(s, D(2026, 11, 1), D(2026, 12, 31))
    assert [(e["date"], e["name"]) for e in found] == [
        (D(2026, 11, 20), "オプション満期日"), (D(2026, 12, 18), "オプション満期日（先物も満期）"),
    ]


def test_holidays_have_japanese_names():
    jp = {h["date"]: h["name"] for h in ev.Sessions("jp").holidays(D(2026, 11, 1), D(2027, 1, 15))}
    assert jp[D(2026, 11, 3)] == "文化の日" and jp[D(2026, 11, 23)] == "勤労感謝の日"
    assert jp[D(2026, 12, 31)] == "年末年始" and jp[D(2027, 1, 11)] == "成人の日"
    us = {h["date"]: h["name"] for h in ev.Sessions("us").holidays(D(2026, 11, 1), D(2026, 12, 31))}
    assert us == {D(2026, 11, 26): "感謝祭", D(2026, 12, 25): "クリスマス"}


def test_previous_session_skips_weekend_and_holiday():
    s = ev.Sessions("jp")
    assert s.previous(D(2026, 11, 24)) == D(2026, 11, 20)  # 11/23(月)は祝日、その前は金曜
    assert ev.next_session("us", D(2026, 11, 25)) == D(2026, 11, 27)  # 感謝祭の翌日


MANUAL = {
    "fomc": {"name": "FOMC", "market": "us", "covered_until": "2027-12-31", "dates": ["2026-12-09"]},
    "boj": {"name": "日銀", "market": "jp", "covered_until": D(2026, 12, 1), "dates": [D(2026, 12, 18)]},
}


def test_build_merges_events_in_date_order_with_prev_and_importance():
    out = ev.build(D(2026, 12, 1), 31, MANUAL)
    items = out["events"]
    assert [e["date"] for e in items] == sorted(e["date"] for e in items)
    fomc = next(e for e in items if e["kind"] == "fomc")
    assert fomc["date"] == "2026-12-09" and fomc["prev"] == "2026-12-08" and fomc["important"] is True
    major = next(e for e in items if e["kind"] == "major_sq")
    assert major["date"] == "2026-12-11" and major["important"] is True
    assert next(e for e in items if e["kind"] == "opex")["important"] is False
    assert any(e["kind"] == "holiday" and e["market"] == "us" and e["date"] == "2026-12-25" for e in items)


def test_build_warns_when_manual_schedule_is_not_covered():
    out = ev.build(D(2026, 12, 1), 31, MANUAL)
    assert len(out["warnings"]) == 1 and "日銀" in out["warnings"][0]


def test_events_yaml_has_source_and_check_date_for_every_event():
    manual = ev.load_manual()
    for kind in ("fomc", "boj", "cpi", "nfp"):
        entry = manual[kind]
        assert entry["source"].startswith("https://") and entry["checked"] and entry["dates"]
        dates = [str(d) for d in entry["dates"]]
        assert dates == sorted(dates) and len(set(dates)) == len(dates)

"""イベントカレンダー（FOMC・日銀・CPI・雇用統計・SQ・オプション満期日・休場日）。

  ・日程が計算で決まるもの（SQ・米国のオプション満期日・休場日）は取引所カレンダーから自動で作る
  ・自動で取得できない日程は config/events.yaml（年に1回、公式サイトで確認して手で更新）から読む
決算発表日は毎日のデータ更新で取得済みのものを、画面と通知の側で組み合わせる。
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

import exchange_calendars as xc
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / "config" / "events.yaml"
CALENDARS = {"jp": "XTKS", "us": "XNYS"}

# 重要イベント（前営業日と当日に、画面上部へ注意を出し、通知にも入れる）
IMPORTANT = {"fomc", "boj", "cpi", "nfp", "major_sq"}

HOLIDAY_NAMES = {
    "New Year's Day": "元日", "Coming of Age Day": "成人の日", "National Foundation Day": "建国記念の日",
    "Emperor's Birthday": "天皇誕生日", "Vernal Equinox Day": "春分の日", "Showa Day": "昭和の日",
    "Constitution Memorial Day": "憲法記念日", "Greenery Day": "みどりの日", "Children's Day": "こどもの日",
    "Marine Day": "海の日", "Mountain Day": "山の日", "Respect for the Aged Day": "敬老の日",
    "Autumnal Equinox Day": "秋分の日", "Health and Sports Day": "スポーツの日", "Sports Day": "スポーツの日",
    "Culture Day": "文化の日", "Labor Thanksgiving Day": "勤労感謝の日", "New Year's Holiday": "年末年始",
    "Dr. Martin Luther King Jr. Day": "キング牧師記念日", "Washington's Birthday": "大統領の日",
    "Presidents' Day": "大統領の日", "Good Friday": "聖金曜日", "Memorial Day": "戦没将兵追悼記念日",
    "Juneteenth": "奴隷解放記念日", "Independence Day": "独立記念日", "Labor Day": "労働者の日",
    "Thanksgiving": "感謝祭", "Christmas": "クリスマス",
}


def _holiday_name(raw: str) -> str:
    for key, name in HOLIDAY_NAMES.items():
        if raw.startswith(key):
            return name
    return raw


class Sessions:
    """取引所の営業日。ライブラリが持っている範囲（last）を超える日は判定できない。"""

    def __init__(self, market: str):
        self.cal = xc.get_calendar(CALENDARS[market])
        self.first = self.cal.first_session.date()
        self.last = self.cal.last_session.date()

    def is_session(self, day: dt.date) -> bool:
        return self.cal.is_session(pd.Timestamp(day))

    def previous(self, day: dt.date) -> dt.date:
        """day より前の、いちばん近い営業日。"""
        d = day - dt.timedelta(days=1)
        while not self.is_session(d):
            d -= dt.timedelta(days=1)
        return d

    def on_or_before(self, day: dt.date) -> dt.date:
        return day if self.is_session(day) else self.previous(day)

    def holidays(self, start: dt.date, end: dt.date) -> List[dict]:
        """平日の休場日（祝日・年末年始など）。"""
        end = min(end, self.last)
        if start > end:
            return []
        sessions = set(d.date() for d in self.cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end)))
        try:
            names = {k.date(): v for k, v in self.cal.regular_holidays.holidays(pd.Timestamp(start), pd.Timestamp(end), return_name=True).items()}
        except Exception:  # noqa: BLE001  名前が取れなくても日付は出す
            names = {}
        out = []
        for day in pd.bdate_range(start, end):
            d = day.date()
            if d not in sessions:
                out.append({"date": d, "name": _holiday_name(names.get(d, "休場日"))})
        return out


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """その月の n 回目の weekday（月曜 = 0 … 金曜 = 4）。"""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def sq_dates(sessions: Sessions, start: dt.date, end: dt.date) -> List[dict]:
    """日本の SQ（毎月第2金曜。休場なら前の営業日）。3・6・9・12月はメジャーSQ。"""
    out = []
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            day = nth_weekday(year, month, 4, 2)
            if day > sessions.last:
                continue
            day = sessions.on_or_before(day)
            if start <= day <= end:
                major = month in (3, 6, 9, 12)
                out.append({"date": day, "kind": "major_sq" if major else "sq", "name": "メジャーSQ" if major else "SQ（ミニ・オプション）"})
    return out


def opex_dates(sessions: Sessions, start: dt.date, end: dt.date) -> List[dict]:
    """米国のオプション満期日（毎月第3金曜。休場なら前の営業日）。3・6・9・12月は株価指数先物も満期（クアドルプル・ウィッチング）。"""
    out = []
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            day = nth_weekday(year, month, 4, 3)
            if day > sessions.last:
                continue
            day = sessions.on_or_before(day)
            if start <= day <= end:
                quad = month in (3, 6, 9, 12)
                out.append({"date": day, "kind": "opex", "name": "オプション満期日" + ("（先物も満期）" if quad else "")})
    return out


def load_manual(path: Path = EVENTS_PATH) -> Dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def manual_events(manual: Dict[str, dict], start: dt.date, end: dt.date) -> List[dict]:
    out = []
    for kind, entry in manual.items():
        for day in entry.get("dates") or []:
            day = day if isinstance(day, dt.date) else dt.date.fromisoformat(str(day))
            if start <= day <= end:
                out.append({"date": day, "kind": kind, "name": entry["name"], "market": entry["market"], "note": entry.get("note")})
    return out


def coverage_warnings(manual: Dict[str, dict], until: dt.date) -> List[str]:
    """手で入れる日程が until まで確認済みでなければ、その説明を返す。"""
    out = []
    for kind, entry in manual.items():
        covered = entry.get("covered_until")
        covered = covered if isinstance(covered, dt.date) else (dt.date.fromisoformat(str(covered)) if covered else None)
        if covered is None or covered < until:
            out.append(f"{entry.get('name', kind)} の日程が {until.isoformat()} まで登録されていません（config/events.yaml を更新してください）")
    return out


def build(today: dt.date, days: int, manual: Optional[Dict[str, dict]] = None) -> dict:
    """today から days 日先までのイベント一覧（日付順）。前営業日（prev）と重要かどうか（important）も付ける。"""
    manual = load_manual() if manual is None else manual
    end = today + dt.timedelta(days=days)
    sessions = {m: Sessions(m) for m in CALENDARS}
    items = []
    for m, s in sessions.items():
        for h in s.holidays(today, end):
            items.append({"date": h["date"], "kind": "holiday", "market": m, "name": f"{'東証' if m == 'jp' else '米国市場'} 休場（{h['name']}）"})
    items += [{**e, "market": "jp"} for e in sq_dates(sessions["jp"], today, end)]
    items += [{**e, "market": "us"} for e in opex_dates(sessions["us"], today, end)]
    items += manual_events(manual, today, end)
    out = []
    for e in sorted(items, key=lambda e: (e["date"], e["market"], e["kind"])):
        s = sessions[e["market"]]
        prev = s.previous(e["date"]).isoformat() if s.first < e["date"] <= s.last + dt.timedelta(days=1) else None
        out.append({**e, "date": e["date"].isoformat(), "prev": prev, "important": e["kind"] in IMPORTANT})
    limit = min(s.last for s in sessions.values())
    warnings = coverage_warnings(manual, end)
    if limit < end:
        warnings.append(f"休場日・SQ は {limit.isoformat()} までしか計算できません（取引所カレンダーのライブラリを更新してください）")
    return {"from": today.isoformat(), "to": end.isoformat(), "events": out, "warnings": warnings,
            "sources": {k: {"name": v.get("name"), "url": v.get("source"), "checked": str(v.get("checked"))} for k, v in manual.items()}}


def next_session(market: str, day: dt.date) -> Optional[dt.date]:
    """day の次の営業日（通知の「翌営業日のイベント」に使う）。"""
    s = Sessions(market)
    d = day + dt.timedelta(days=1)
    while d <= s.last:
        if s.is_session(d):
            return d
        d += dt.timedelta(days=1)
    return None

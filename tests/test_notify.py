"""通知の文面のテスト。"""
from screener import notify as nt


def test_parse_watchlist_by_market():
    raw = "jp:7203, us:aapl\n8035, JP:6758 ,, us:MSFT"
    assert nt.parse_watchlist(raw, "jp") == ["7203", "8035", "6758"]
    assert nt.parse_watchlist(raw, "us") == ["AAPL", "8035", "MSFT"]
    assert nt.parse_watchlist(None, "jp") == [] and nt.parse_watchlist("", "us") == []


def regime(states, vix=None, high=30):
    return {"latest": {"regime": states[-1]}, "history": {"regime": states, "vix": vix or [None] * len(states)},
            "config": {"vix_high": high}}


def test_regime_change_and_vix_crossing():
    assert nt.regime_lines(regime(["wait", "wait"])) == []
    assert nt.regime_lines(regime(["wait", "momentum"])) == ["相場環境が「順張り向き」に切り替わりました（前は「様子見」）"]
    lines = nt.regime_lines(regime(["wait", "wait"], vix=[29.0, 31.2]))
    assert lines == ["VIX が 31.2 になり、30 を超えました（恐怖指数が高い）"]
    assert nt.regime_lines(regime(["wait", "wait"], vix=[31.0, 32.0])) == []  # 前日から超えている
    assert nt.regime_lines(None) == []


def stock(code, **kw):
    return {"code": code, "name": f"銘柄{code}", "date": "2026-11-13", **kw}


def test_candidates_lists_today_only_and_limits_names():
    contrarian = {"as_of": "2026-11-13", "stocks": [
        stock("A", entry=True, count=2), stock("B", entry=True, count=4), stock("C", entry=False),
        stock("D", entry=True, count=3, stale=True), stock("E", entry=True, count=3, date="2026-11-12"),
    ]}
    momentum = {"as_of": "2026-11-13", "stocks": [
        stock("X", rs=80, vcp={"status": "breakout", "breakout_date": "2026-11-13"}),
        stock("Y", rs=95, vcp={"status": "breakout", "breakout_date": "2026-11-13"}),
        stock("Z", rs=99, vcp={"status": "breakout", "breakout_date": "2026-11-10"}),
        stock("W", rs=99, vcp={"status": "weak", "breakout_date": "2026-11-13"}),
    ]}
    lines = nt.candidate_lines(contrarian, momentum, 1)
    assert lines == ["逆張りのエントリー候補 2件: 銘柄B（B） ほか1銘柄", "順張りのブレイクアウト 2件: 銘柄Y（Y） ほか1銘柄"]
    assert nt.candidate_lines(None, None, 5) == []


def test_next_session_important_events_only():
    events = {"events": [
        {"date": "2026-12-09", "name": "FOMC", "important": True},
        {"date": "2026-12-09", "name": "オプション満期日", "important": False},
        {"date": "2026-12-10", "name": "CPI", "important": True},
    ]}
    assert nt.event_lines(events, "2026-12-09") == ["FOMC（12/09）"]
    assert nt.event_lines(events, None) == []


def test_watchlist_warnings_and_earnings_tomorrow():
    contrarian = {"as_of": "2026-11-13", "stocks": [
        stock("7203", warnings=["hanging_man"], trend={"exit_warning": True}),
        stock("6758", warnings=[], earnings={"next": "2026-11-16"}),
        stock("9984", warnings=[]),
    ]}
    momentum = {"as_of": "2026-11-13", "stocks": [stock("8035", ma_break="2026-11-13")]}
    lines = nt.watchlist_lines(["7203", "6758", "9984", "8035", "0000"], contrarian, momentum, "2026-11-16")
    assert lines == [
        "銘柄7203（7203）: 首吊り線・手仕舞い警戒",
        "銘柄6758（6758）: 次の営業日（11/16）に決算",
        "銘柄8035（8035）: 50日線割れ（出来高あり）",
    ]


def test_message_is_none_when_nothing_to_say_and_has_disclaimer():
    assert nt.build_message("日本株", "2026-11-13", {"regime": [], "candidates": []}) is None
    text = nt.build_message("日本株", "2026-11-13", {"candidates": ["逆張りのエントリー候補 1件: X"]}, "https://example.com/")
    assert text.startswith("**株スクリーナー 日本株（11/13 終値）**")
    assert "■ 新しい候補\n・逆張りのエントリー候補 1件: X" in text
    assert nt.DISCLAIMER in text and text.endswith("https://example.com/")
    assert nt.DISCLAIMER in nt.empty_message("米国株", "2026-11-13")


def test_long_message_is_cut_but_keeps_disclaimer():
    lines = [f"銘柄{i}" * 20 for i in range(100)]
    text = nt.build_message("米国株", "2026-11-13", {"watch": lines})
    assert len(text) <= nt.LIMIT and text.endswith(nt.DISCLAIMER)

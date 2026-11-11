"""財務データのまとめ取得（拒否されたら待って取り直す）のテスト。通信はしない。"""
from markets import fundamentals


def run(monkeypatch, answers, **kwargs):
    """answers = {銘柄: [1回目の結果, 2回目の結果, …]}。待ち時間は記録するだけ。"""
    calls, sleeps = {}, []

    def fake_fetch(symbol, retries=1):
        n = calls.get(symbol, 0)
        calls[symbol] = n + 1
        results = answers[symbol]
        return results[min(n, len(results) - 1)]

    monkeypatch.setattr(fundamentals, "fetch_facts", fake_fetch)
    monkeypatch.setattr(fundamentals.time, "sleep", sleeps.append)
    result = fundamentals.fetch_many(list(answers), workers=1, **kwargs)
    return result, calls, sleeps


def test_all_succeed_without_waiting(monkeypatch):
    result, calls, sleeps = run(monkeypatch, {s: [{"ok": 1}] for s in "ABCD"}, chunk_size=2)
    assert all(result.values()) and sleeps == []
    assert all(n == 1 for n in calls.values())


def test_waits_and_retries_when_most_of_a_chunk_fails(monkeypatch):
    answers = {"A": [None, {"ok": 1}], "B": [None, {"ok": 1}], "C": [{"ok": 1}], "D": [{"ok": 1}]}
    result, calls, sleeps = run(monkeypatch, answers, chunk_size=4, cooldown_seconds=300)
    assert sleeps == []            # 4銘柄中2銘柄の失敗は「半分以上」ではないので待たない
    assert result["A"] is None

    answers = {"A": [None, {"ok": 1}], "B": [None, {"ok": 1}], "C": [None, {"ok": 1}], "D": [{"ok": 1}]}
    result, calls, sleeps = run(monkeypatch, answers, chunk_size=4, cooldown_seconds=300)
    assert sleeps == [300]
    assert all(result.values())
    assert calls == {"A": 2, "B": 2, "C": 2, "D": 1}   # 取れていた銘柄は取り直さない


def test_a_few_failures_do_not_trigger_waiting(monkeypatch):
    answers = {"A": [None], "B": [{"ok": 1}], "C": [{"ok": 1}], "D": [{"ok": 1}]}
    result, _, sleeps = run(monkeypatch, answers, chunk_size=4)
    assert sleeps == [] and result["A"] is None


def test_gives_up_waiting_after_the_limit(monkeypatch):
    answers = {s: [None] for s in "ABCDEF"}
    result, calls, sleeps = run(monkeypatch, answers, chunk_size=2, cooldown_seconds=10, max_cooldowns=2)
    assert sleeps == [10, 10]      # 3かたまりあるが、待つのは2回まで
    assert not any(result.values())

"""通知の文面を作る（毎日のデータ更新のあとに、市場ごとに1通）。市場に依存しない。

入れるのは公開してよい市場データだけ:
  ・相場環境の切り替わり、VIX が基準を超えた日（米国株の「恐怖指数が高い」）
  ・その日の新しいエントリー候補とブレイクアウト（多い日は上位だけ）
  ・翌営業日の重要イベント
  ・ウォッチリスト（GitHub Secrets に置いた銘柄コード）の警戒サインと、翌営業日の決算
保有銘柄・資金・売買記録はサーバー側にないので、通知には入らない。
"""
from __future__ import annotations

from typing import Dict, List, Optional

REGIME_LABEL = {"contrarian": "逆張り向き", "momentum": "順張り向き", "wait": "様子見"}
WARNING_LABEL = {
    "hanging_man": "首吊り線", "harami_top": "高値圏のはらみ線", "double_top": "ダブルトップ割れ",
    "triple_top": "トリプルトップ割れ", "island_top": "アイランドリバーサル", "two_black": "下放れ二本黒",
}
DISCLAIMER = "※ 機械的な判定による目安です。投資助言ではありません。"
LIMIT = 1900  # Discord の1通の上限（2000文字）より少し短く


def parse_watchlist(raw: Optional[str], market: str) -> List[str]:
    """「jp:7203, us:AAPL」の形の文字列から、その市場の銘柄コードを取り出す。市場を書かないコードは両方の市場で探す。"""
    codes = []
    for item in (raw or "").replace("\n", ",").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            m, code = item.split(":", 1)
            if m.strip().lower() == market:
                codes.append(code.strip().upper())
        else:
            codes.append(item.upper())
    return list(dict.fromkeys(codes))


def regime_lines(regime: Optional[dict]) -> List[str]:
    """相場環境が今日切り替わった、または VIX が今日基準を超えたときの文面。"""
    if not regime or not regime.get("latest"):
        return []
    out = []
    latest, hist, cfg = regime["latest"], regime.get("history", {}), regime.get("config", {})
    states = [s for s in hist.get("regime", []) if s]
    if len(states) >= 2 and states[-1] != states[-2]:
        out.append(f"相場環境が「{REGIME_LABEL[states[-1]]}」に切り替わりました（前は「{REGIME_LABEL[states[-2]]}」）")
    vix = [v for v in hist.get("vix", []) if v is not None]
    high = cfg.get("vix_high")
    if high is not None and len(vix) >= 2 and vix[-1] > high >= vix[-2]:
        out.append(f"VIX が {vix[-1]:.1f} になり、{high} を超えました（恐怖指数が高い）")
    return out


def _names(items: List[dict], limit: int) -> str:
    shown = "、".join(f"{s['name']}（{s['code']}）" for s in items[:limit])
    return shown + (f" ほか{len(items) - limit}銘柄" if len(items) > limit else "")


def candidate_lines(contrarian: Optional[dict], momentum: Optional[dict], limit: int) -> List[str]:
    out = []
    if contrarian:
        day = contrarian["as_of"]
        entries = [s for s in contrarian["stocks"] if s.get("entry") and s.get("date") == day and not s.get("stale")]
        entries.sort(key=lambda s: (-s.get("count", 0), s.get("change_pct", 0)))
        if entries:
            out.append(f"逆張りのエントリー候補 {len(entries)}件: {_names(entries, limit)}")
    if momentum:
        day = momentum["as_of"]
        breakouts = [s for s in momentum["stocks"]
                     if (s.get("vcp") or {}).get("status") == "breakout" and s["vcp"].get("breakout_date") == day and not s.get("stale")]
        breakouts.sort(key=lambda s: -(s.get("rs") or 0))
        if breakouts:
            out.append(f"順張りのブレイクアウト {len(breakouts)}件: {_names(breakouts, limit)}")
    return out


def event_lines(events: Optional[dict], next_day: Optional[str]) -> List[str]:
    if not events or not next_day:
        return []
    found = [e for e in events.get("events", []) if e["date"] == next_day and e.get("important")]
    return [f"{e['name']}（{e['date'][5:].replace('-', '/')}）" for e in found]


def watchlist_lines(codes: List[str], contrarian: Optional[dict], momentum: Optional[dict], next_day: Optional[str]) -> List[str]:
    """ウォッチリストの銘柄の、今日の警戒サインと、翌営業日の決算。"""
    if not codes:
        return []
    out = []
    by_code: Dict[str, dict] = {}
    for data in (momentum, contrarian):  # 逆張りのデータ（警戒サインあり）を優先
        for s in (data or {}).get("stocks", []):
            by_code[s["code"]] = {**by_code.get(s["code"], {}), **s}
    for code in codes:
        s = by_code.get(code)
        if not s:
            continue
        notes = []
        if s.get("date") == (contrarian or {}).get("as_of"):
            notes += [WARNING_LABEL.get(k, k) for k in s.get("warnings") or []]
            if (s.get("trend") or {}).get("exit_warning"):
                notes.append("手仕舞い警戒")
        if s.get("ma_break") and s.get("ma_break") == (momentum or {}).get("as_of"):
            notes.append("50日線割れ（出来高あり）")
        earnings = (s.get("earnings") or {}).get("next")
        if next_day and earnings == next_day:
            notes.append(f"次の営業日（{next_day[5:].replace('-', '/')}）に決算")
        if notes:
            out.append(f"{s['name']}（{code}）: {'・'.join(notes)}")
    return out


def build_message(market_label: str, as_of: str, sections: Dict[str, List[str]], site_url: str = "") -> Optional[str]:
    """セクションごとの行から1通の文面を作る。中身がなければ None。"""
    titles = {"regime": "相場環境", "candidates": "新しい候補", "events": "次の営業日の重要イベント", "watch": "ウォッチリスト"}
    parts = [f"**株スクリーナー {market_label}（{as_of[5:].replace('-', '/')} 終値）**"]
    filled = False
    for key, title in titles.items():
        lines = sections.get(key) or []
        if lines:
            filled = True
            parts.append(f"■ {title}\n" + "\n".join(f"・{line}" for line in lines))
    if not filled:
        return None
    parts.append(DISCLAIMER + (f"\n{site_url}" if site_url else ""))
    text = "\n\n".join(parts)
    if len(text) > LIMIT:
        text = text[: LIMIT - len(DISCLAIMER) - 20] + "\n…（長いので省略）\n" + DISCLAIMER
    return text


def empty_message(market_label: str, as_of: str) -> str:
    return f"**株スクリーナー {market_label}（{as_of[5:].replace('-', '/')} 終値）**\n\n今日はお知らせする内容はありません。\n\n{DISCLAIMER}"

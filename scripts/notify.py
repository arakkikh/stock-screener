"""毎日のデータ更新のあとに、Discord へ通知を1通送る。

使い方:  python scripts/notify.py --market jp   （または us）
  --dry-run   送らずに、文面を画面に出すだけ（手元で確かめる用）

送り先（Webhook の URL）は環境変数 DISCORD_WEBHOOK_URL から読む。GitHub Actions では Secrets に置く。
ウォッチリストは環境変数 WATCHLIST（例: "jp:7203, us:AAPL"）から読む。これも Secrets に置く。
公開リポジトリの Actions のログは誰でも見られるので、文面・URL・ウォッチリストはログに出さない。
通知に失敗しても、データ更新は失敗扱いにしない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import markets  # noqa: E402
from screener import events as ev  # noqa: E402
from screener import notify  # noqa: E402
from screener.config import load_thresholds  # noqa: E402

DATA = ROOT / "docs" / "data"


def read(name: str):
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def compose(market_key: str, cfg: dict, watchlist_raw: str | None):
    market = markets.get(market_key)
    contrarian = read(f"{market_key}.json")
    momentum = read(f"{market_key}_momentum.json")
    if momentum and contrarian and momentum.get("as_of") != contrarian.get("as_of"):
        momentum = None  # 順張りの更新に失敗した日は、古い候補を送らない
    regime = read(f"{market_key}_regime.json")
    if regime and contrarian and regime.get("as_of") != contrarian.get("as_of"):
        regime = None
    as_of = contrarian["as_of"]
    nxt = ev.next_session(market_key, dt.date.fromisoformat(as_of))
    next_day = nxt.isoformat() if nxt else None
    n = cfg["notify"]
    sections = {
        "regime": notify.regime_lines(regime),
        "candidates": notify.candidate_lines(contrarian, momentum, n["max_names"]),
        "events": notify.event_lines(read("events.json"), next_day),
        "watch": notify.watchlist_lines(notify.parse_watchlist(watchlist_raw, market_key), contrarian, momentum, next_day),
    }
    text = notify.build_message(market.label, as_of, sections, n.get("site_url", ""))
    if text is None and n["send_empty"]:
        text = notify.empty_message(market.label, as_of)
    return text, {k: len(v) for k, v in sections.items()}


def send(url: str, text: str) -> None:
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "stock-screener-notify"})
    with urllib.request.urlopen(req, timeout=20) as res:
        if res.status >= 300:
            raise RuntimeError(f"送信先の応答が {res.status} でした")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_thresholds(args.market)
    if not cfg["notify"]["enabled"]:
        print(f"[{args.market}・通知] この市場の通知はオフです（config/thresholds.yaml の notify.enabled）")
        return 0
    try:
        text, counts = compose(args.market, cfg, os.environ.get("WATCHLIST"))
    except Exception as err:  # noqa: BLE001
        print(f"::warning::[{args.market}] 通知の文面を作れませんでした: {err!r}", file=sys.stderr)
        return 0
    if args.dry_run:
        print(text or "（送る内容がありません）")
        return 0
    # ログには項目の件数だけ出す（文面やウォッチリストの銘柄は出さない）
    summary = "、".join(f"{k} {v}" for k, v in counts.items())
    if text is None:
        print(f"[{args.market}・通知] 送る内容がないので送りません（{summary}）")
        return 0
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print(f"[{args.market}・通知] 送り先（DISCORD_WEBHOOK_URL）が未設定なので送りません")
        return 0
    try:
        send(url, text)
        print(f"[{args.market}・通知] 送りました（{summary}）")
    except Exception as err:  # noqa: BLE001
        # URL がエラー文に含まれないよう、種類だけを出す
        print(f"::warning::[{args.market}] 通知を送れませんでした（{type(err).__name__}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

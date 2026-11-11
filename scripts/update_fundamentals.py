"""財務データを取得して data/fundamentals_<市場>.json に保存する（週1回）。

使い方:  python scripts/update_fundamentals.py --market jp   （または us）
  --max-age-days N   N日以内に取得済みの銘柄は取り直さない（既定 5。途中で失敗したときの続きに使える）
  --limit N          先頭の N 銘柄だけ（動作確認用）

決算は四半期ごとなので、毎日は取得しない。PER など株価で変わる指標は、
毎日の更新（scripts/update.py --mode fundamentals）で計算し直す。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import markets  # noqa: E402
from markets import fundamentals  # noqa: E402

STORE = ROOT / "data"


def store_path(market_key: str) -> Path:
    return STORE / f"fundamentals_{market_key}.json"


def load_universe(market_key: str) -> pd.DataFrame:
    """ファンダ分析の対象 = 順張りの対象（逆張りの対象もすべて含まれる）に、逆張りだけの銘柄を足したもの。"""
    frames = [
        pd.read_csv(ROOT / "config" / name, dtype=str, keep_default_na=False)
        for name in (f"universe_{market_key}_momentum.csv", f"universe_{market_key}.csv")
    ]
    return pd.concat(frames).drop_duplicates("code").sort_values("code").reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    parser.add_argument("--max-age-days", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    market = markets.get(args.market)
    path = store_path(market.key)
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    codes = list(load_universe(market.key)["code"])[: args.limit]

    cutoff = (dt.date.today() - dt.timedelta(days=args.max_age_days)).isoformat()
    todo = [c for c in codes if stored.get(c, {}).get("fetched", "") <= cutoff]
    print(f"[{market.key}・財務] 対象 {len(codes)} 銘柄のうち {len(todo)} 銘柄を取得します")
    fetched = fundamentals.fetch_many([market.ticker(c) for c in todo])

    failed = []
    for code in todo:
        facts = fetched.get(market.ticker(code))
        if facts:
            stored[code] = facts
        else:
            failed.append(code)  # 前回のデータがあればそのまま残る

    STORE.mkdir(exist_ok=True)
    kept = {code: stored[code] for code in sorted(stored) if code in set(codes) or args.limit}
    path.write_text(json.dumps(kept, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"[{market.key}・財務] 完了: 保存 {len(kept)} 銘柄、今回の取得失敗 {len(failed)} {failed[:20]}")
    # 半数以上が失敗したら、取得元の制限とみなして知らせる（取れた分は保存済み）
    return 1 if todo and len(failed) > len(todo) / 2 else 0


if __name__ == "__main__":
    sys.exit(main())

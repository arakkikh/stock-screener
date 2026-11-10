"""株価を取得して判定し、画面用の JSON を docs/data に書き出す。

使い方:  python scripts/update.py --market jp   （または us）
  --force を付けると、新しい営業日のデータがなくても作り直す。
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
from markets import fetch  # noqa: E402
from screener import report  # noqa: E402
from screener.config import load_thresholds  # noqa: E402

DATA = ROOT / "docs" / "data"
MIN_DAYS = 120  # これより日数の少ない銘柄は判定しない（100日線が引けない）


def read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def merge_earnings(entry: dict, fetched, today: str) -> dict:
    """覚えている決算日に、新しく取得した日付を反映する。

    entry = {"next": 次回の予定日, "past": 済んだ決算日の一覧}
    fetched = 取得した日付の一覧（取得に失敗したときは None）
    当日が決算日の場合は、その日の引け後まで「次回」として扱う。
    """
    known = set(entry.get("past") or [])
    if entry.get("next"):
        known.add(entry["next"])
    known.update(fetched or [])
    upcoming = sorted(d for d in known if d >= today)
    past = sorted(d for d in known if d < today)
    return {"next": upcoming[0] if upcoming else None, "past": past[-8:]}


def update_earnings(market, tickers: dict, as_of: dt.date, folder: Path) -> dict:
    """決算日を取得し、過ぎた決算日は「過去の決算日」として覚えておく。"""
    state = read_json(folder / "_earnings.json", {})
    fetched = fetch.earnings_dates(list(tickers.values()))
    for code, ticker in tickers.items():
        dates = fetched.get(ticker)
        dates = None if dates is None else [d.isoformat() for d in dates]
        state[code] = merge_earnings(state.get(code, {}), dates, as_of.isoformat())
    return state


def earnings_summary(market, entry: dict) -> dict:
    nxt = entry.get("next")
    prev = fetch.previous_session(market, dt.date.fromisoformat(nxt)).isoformat() if nxt else None
    past = entry.get("past") or []
    return {"next": nxt, "prev_session": prev, "last": past[-1] if past else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    market = markets.get(args.market)
    cfg = load_thresholds(market.key)
    folder = DATA / market.key
    summary_path = DATA / f"{market.key}.json"
    previous = read_json(summary_path, {})

    now = dt.datetime.now(dt.timezone.utc)
    as_of = fetch.last_completed_session(market, now)
    if previous.get("as_of") == as_of.isoformat() and not args.force:
        print(f"[{market.key}] {as_of} のデータは作成済みです（休場日などで新しい営業日がありません）")
        return 0

    universe = pd.read_csv(ROOT / "config" / f"universe_{market.key}.csv", dtype=str, keep_default_na=False)
    tickers = {code: market.ticker(code) for code in universe["code"]}
    extra = [market.index_ticker, "JPY=X"] + ([market.vol_ticker] if market.vol_ticker else [])
    print(f"[{market.key}] {as_of} 時点のデータを取得します（{len(tickers)} 銘柄）")
    prices = fetch.download_daily(list(tickers.values()) + extra, as_of)

    if market.index_ticker not in prices:
        print("基準指数を取得できませんでした。更新を中止します", file=sys.stderr)
        return 1

    old_stocks = {s["code"]: s for s in previous.get("stocks", [])}
    earnings = update_earnings(market, tickers, as_of, folder)
    stocks, closes, failed, charts = [], {}, [], {}
    for row in universe.itertuples(index=False):
        base = {
            "code": row.code,
            "name": row.name,
            "sector": row.sector,
            "themes": [t for t in row.themes.split("|") if t],
            "earnings": earnings_summary(market, earnings.get(row.code, {})),
        }
        df = prices.get(tickers[row.code])
        if df is None or len(df) < MIN_DAYS:
            failed.append(row.code)
            if row.code in old_stocks:  # 前回のデータを残し、古いことが分かるようにする
                stocks.append({**old_stocks[row.code], **base, "stale": True})
            continue
        closes[row.code] = df["close"]
        old = old_stocks.get(row.code)
        if old and old.get("date", "") > df.index[-1].strftime("%Y-%m-%d"):
            # 取得元の不調で前回より古いデータしか取れなかった。前回の結果を残す
            stocks.append({**old, **base, "stale": old["date"] != as_of.isoformat()})
            continue
        summary, chart = report.analyze_stock(df, cfg, market.decimals)
        charts[row.code] = chart
        stocks.append({**base, **summary, "stale": summary["date"] != as_of.isoformat()})

    # 取得元の不調を見分ける。半数以上が取得できない・最新日のデータがないときは何も書き換えない
    stale = [s["code"] for s in stocks if s["stale"]]
    if len(failed) > len(universe) / 2 or len(stale) > len(universe) / 2:
        print(
            f"取得失敗 {len(failed)} 銘柄、{as_of} のデータがない銘柄 {len(stale)} 銘柄。"
            "取得元の不調とみなして更新を中止します（前回のデータはそのまま残ります）",
            file=sys.stderr,
        )
        return 1
    for code, chart in charts.items():
        write_json(folder / f"{code}.json", {"code": code, **chart})
    write_json(folder / "_earnings.json", earnings)

    sectors = report.sector_trends(pd.DataFrame(closes), dict(zip(universe["code"], universe["sector"])), cfg)
    for stock in stocks:
        stock["watch_only"] = sectors.get(stock["sector"], {}).get("downtrend", False)

    index_df = prices[market.index_ticker]
    write_json(folder / "_index.json", {"code": "_index", **report.chart_payload(index_df, cfg, 2)})

    vol = None
    if market.vol_ticker and market.vol_ticker in prices:
        vol_df = prices[market.vol_ticker]
        vol = {"value": round(float(vol_df["close"].iloc[-1]), 2), "date": vol_df.index[-1].strftime("%Y-%m-%d")}

    write_json(
        summary_path,
        {
            "market": market.key,
            "label": market.label,
            "currency": market.currency,
            "decimals": market.decimals,
            "as_of": as_of.isoformat(),
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "config": cfg,
            "thermometer": {
                "index": {"name": market.index_name, **report.index_state(index_df, cfg)},
                "vol": {"name": market.vol_name, "url": market.vol_url, "auto": vol},
                "fear_greed": {"url": market.fear_greed_url},
            },
            "sectors": sectors,
            "stocks": stocks,
            "failed": failed,
        },
    )

    if "JPY=X" in prices:
        fx = prices["JPY=X"]
        write_json(
            DATA / "fx.json",
            {"usdjpy": round(float(fx["close"].iloc[-1]), 2), "date": fx.index[-1].strftime("%Y-%m-%d")},
        )

    print(f"[{market.key}] 完了: {len(charts)} 銘柄を更新、取得失敗 {failed or 'なし'}、最新日のデータなし {stale or 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

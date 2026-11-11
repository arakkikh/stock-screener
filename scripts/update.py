"""株価を取得して判定し、画面用の JSON を docs/data に書き出す。

使い方:  python scripts/update.py --market jp   （または us）
  --mode contrarian   逆張りだけ更新（docs/data/jp.json など）
  --mode momentum     順張りだけ更新（docs/data/jp_momentum.json など）
  --mode fundamentals ファンダ分析だけ更新（docs/data/jp_fund.json など）。保存済みの財務データと
                      最新の株価から計算し直すだけで、通信はしない
  --mode all          すべて（既定）
  --force             新しい営業日のデータがなくても作り直す
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
from screener import fundamentals, momentum, report  # noqa: E402
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


def run_contrarian(market, cfg: dict, as_of: dt.date, now: dt.datetime, force: bool) -> int:
    """逆張りスクリーナーのデータを更新する。戻り値は終了コード（0 = 成功）。"""
    folder = DATA / market.key
    summary_path = DATA / f"{market.key}.json"
    previous = read_json(summary_path, {})
    if previous.get("as_of") == as_of.isoformat() and not force:
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


def run_momentum(market, cfg: dict, as_of: dt.date, now: dt.datetime, force: bool) -> int:
    """順張りモードのデータを更新する。戻り値は終了コード（0 = 成功）。

    対象銘柄が多いので、チャート用ファイルと決算日はトレンドテンプレート合格銘柄だけ作る。
    """
    tag = f"{market.key}・順張り"
    folder = DATA / market.key / "m"
    summary_path = DATA / f"{market.key}_momentum.json"
    previous = read_json(summary_path, {})
    if previous.get("as_of") == as_of.isoformat() and not force:
        print(f"[{tag}] {as_of} のデータは作成済みです")
        return 0

    universe = pd.read_csv(
        ROOT / "config" / f"universe_{market.key}_momentum.csv", dtype=str, keep_default_na=False
    )
    tickers = {code: market.ticker(code) for code in universe["code"]}
    print(f"[{tag}] {as_of} 時点のデータを取得します（{len(tickers)} 銘柄）")
    prices = fetch.download_daily(list(tickers.values()), as_of)

    frames = {code: prices[t] for code, t in tickers.items() if t in prices}
    closes = pd.DataFrame({code: df["close"] for code, df in frames.items()})
    ratings = momentum.rs_ratings(momentum.rs_scores(closes, cfg)) if len(closes.columns) else {}

    old_stocks = {s["code"]: s for s in previous.get("stocks", [])}
    stocks, charts, failed, skipped = [], {}, [], []
    for row in universe.itertuples(index=False):
        base = {
            "code": row.code,
            "name": row.name,
            "sector": row.sector,
            "themes": [t for t in row.themes.split("|") if t],
        }
        df = frames.get(row.code)
        old = old_stocks.get(row.code)
        if df is None:
            failed.append(row.code)
            if old:
                stocks.append({**old, **base, "stale": True})
            continue
        if old and old.get("date", "") > df.index[-1].strftime("%Y-%m-%d"):
            stocks.append({**old, **base, "stale": old["date"] != as_of.isoformat()})
            continue
        summary, chart = report.analyze_momentum(df, ratings.get(row.code), cfg, market.decimals)
        if summary is None:
            skipped.append(row.code)  # 上場から1年未満などで、判定に必要な日数がない
            continue
        if chart is not None:
            charts[row.code] = chart
        stocks.append({**base, **summary, "stale": summary["date"] != as_of.isoformat()})

    stale = [s["code"] for s in stocks if s["stale"]]
    if len(failed) > len(universe) / 2 or len(stale) > len(universe) / 2:
        print(
            f"[{tag}] 取得失敗 {len(failed)} 銘柄、{as_of} のデータがない銘柄 {len(stale)} 銘柄。"
            "取得元の不調とみなして更新を中止します（前回のデータはそのまま残ります）",
            file=sys.stderr,
        )
        return 1

    # 決算日は合格銘柄だけ取得する（1銘柄ずつ問い合わせるため）
    passed = {s["code"]: tickers[s["code"]] for s in stocks if s.get("passed")}
    earnings = update_earnings(market, passed, as_of, folder)
    earnings = {code: entry for code, entry in earnings.items() if code in passed}
    for stock in stocks:
        entry = earnings.get(stock["code"])
        stock["earnings"] = earnings_summary(market, entry) if entry else None

    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.glob("*.json"):  # 合格から外れた銘柄のチャートは消す
        if path.stem not in charts and not path.stem.startswith("_"):
            path.unlink()
    for code, chart in charts.items():
        write_json(folder / f"{code}.json", {"code": code, **chart})
    write_json(folder / "_earnings.json", earnings)
    write_json(
        summary_path,
        {
            "market": market.key,
            "label": market.label,
            "universe": market.momentum_universe_name,
            "currency": market.currency,
            "decimals": market.decimals,
            "as_of": as_of.isoformat(),
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "config": cfg,
            "stocks": stocks,
            "failed": failed,
            "skipped": skipped,
        },
    )
    vcp = sum(1 for s in stocks if s.get("vcp"))
    print(
        f"[{tag}] 完了: 判定 {len(stocks)} 銘柄、全条件合格 {len(passed)}、VCP {vcp}、"
        f"取得失敗 {len(failed)}、日数不足 {len(skipped)}、最新日のデータなし {len(stale)}"
    )
    return 0


def _rounded(value, digits: int = 2):
    if isinstance(value, bool) or value is None:
        return value
    return round(float(value), digits)


# 画面に出す指標（計算の途中で使うだけの金額などは出力しない）
FUND_METRICS = [
    "financial", "loss", "payer", "no_debt", "per", "pbr", "peg", "ev_ebitda", "fcf_yield", "eps_g0", "eps_g1",
    "eps_g_next", "rev_g_next", "analysts", "eps_cagr", "eps_g_last", "roe", "roa", "margin", "margin_prev",
    "current_ratio", "de", "de_old", "ocf_to_debt", "interest_cover", "equity_ratio", "div_yield", "payout",
    "div_full_history",
]


def run_fundamentals(market, cfg: dict, as_of: dt.date, now: dt.datetime) -> int:
    """ファンダ分析（5軸の採点）を作り直す。

    財務データは週1回 scripts/update_fundamentals.py が data/ に保存したものを使う。
    PER など株価で変わる指標は、ここで最新の終値から計算する。
    """
    tag = f"{market.key}・ファンダ"
    store = ROOT / "data" / f"fundamentals_{market.key}.json"
    if not store.exists():
        print(f"[{tag}] 財務データがまだありません（scripts/update_fundamentals.py を先に実行します）")
        return 0
    facts = read_json(store, {})

    names, sectors, prices, price_date = {}, {}, {}, None
    for name in (f"universe_{market.key}_momentum.csv", f"universe_{market.key}.csv"):
        table = pd.read_csv(ROOT / "config" / name, dtype=str, keep_default_na=False)
        names.update(dict(zip(table["code"], table["name"])))
        sectors.update(dict(zip(table["code"], table["sector"])))
    for name in (f"{market.key}.json", f"{market.key}_momentum.json"):  # 後に読むほうを優先
        data = read_json(DATA / name, {})
        price_date = data.get("as_of", price_date)
        prices.update({s["code"]: s["close"] for s in data.get("stocks", []) if s.get("close")})

    facts = {code: f for code, f in facts.items() if code in names}
    scored = fundamentals.score_universe(facts, prices, sectors, cfg, as_of)
    stocks = []
    for code in sorted(scored["stocks"]):
        entry = scored["stocks"][code]
        stocks.append(
            {
                "code": code,
                "name": names[code],
                "sector": sectors[code],
                "s": entry["s"],
                "c": {axis: [None if r is None else int(r) for r in results] for axis, results in entry["c"].items()},
                "m": {key: _rounded(entry["m"][key]) for key in FUND_METRICS},
                "fetched": facts[code].get("fetched"),
            }
        )
    stats = scored["stats"]
    write_json(
        DATA / f"{market.key}_fund.json",
        {
            "market": market.key,
            "label": market.label,
            "universe": market.momentum_universe_name,
            "decimals": market.decimals,
            "as_of": price_date,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "config": cfg["fundamentals"],
            "axes": fundamentals.AXES,
            "checks": fundamentals.CHECKS,
            "stats": {
                **{k: _rounded(v) for k, v in stats.items() if k != "sector_per"},
                "sector_per": {s: _rounded(v) for s, v in stats["sector_per"].items()},
            },
            "stocks": stocks,
        },
    )
    scored_all = sum(1 for s in stocks if all(v is not None for v in s["s"]))
    print(f"[{tag}] 完了: {len(stocks)} 銘柄を採点（5軸すべて採点できた {scored_all}）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["jp", "us"])
    parser.add_argument("--mode", default="all", choices=["all", "contrarian", "momentum", "fundamentals"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    market = markets.get(args.market)
    cfg = load_thresholds(market.key)
    now = dt.datetime.now(dt.timezone.utc)
    as_of = fetch.last_completed_session(market, now)
    code = 0
    if args.mode in ("all", "contrarian"):
        code = max(code, run_contrarian(market, cfg, as_of, now, args.force))
    if args.mode in ("all", "momentum"):
        code = max(code, run_momentum(market, cfg, as_of, now, args.force))
    if args.mode in ("all", "fundamentals"):
        code = max(code, run_fundamentals(market, cfg, as_of, now))
    return code


if __name__ == "__main__":
    sys.exit(main())

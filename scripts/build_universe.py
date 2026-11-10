"""銘柄リスト（config/universe_jp.csv, universe_us.csv）を公式の構成銘柄から作り直す。

使い方:  python scripts/build_universe.py jp   （または us）

すでにあるファイルの themes 列（手動で付けたテーマ）は引き継ぐ。
指数の銘柄入れ替えがあったときに手動で実行する。
"""
from __future__ import annotations

import io
import sys
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
JPX_URL = "https://www.jpx.co.jp/automation/markets/indices/topix/files/topixweight_j.csv"
SP100_URL = "https://en.wikipedia.org/wiki/S%26P_100"
COLUMNS = ["code", "name", "sector", "themes"]


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stock-screener"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def build_jp() -> pd.DataFrame:
    """JPX 公式の TOPIX 構成銘柄から Core30 と Large70 を取り出す。"""
    text = _download(JPX_URL).decode("cp932")
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df = df[df["ニューインデックス区分"].isin(["TOPIX Core30", "TOPIX Large70"])]
    return pd.DataFrame(
        {
            "code": df["コード"].str.strip(),
            # 全角の英数字を半角にそろえる
            "name": df["銘柄名"].map(lambda v: unicodedata.normalize("NFKC", v).strip()),
            "sector": df["業種"].str.strip(),
        }
    )


def build_us() -> pd.DataFrame:
    """Wikipedia の S&P 100 構成銘柄の表を読む。"""
    html = _download(SP100_URL).decode("utf-8")
    tables = pd.read_html(io.StringIO(html))
    table = next(t for t in tables if {"Symbol", "Name", "Sector"} <= set(map(str, t.columns)))
    return pd.DataFrame(
        {
            # yfinance は BRK.B を BRK-B と書く
            "code": table["Symbol"].str.strip().str.replace(".", "-", regex=False),
            "name": table["Name"].str.strip(),
            "sector": table["Sector"].str.strip(),
        }
    )


def main(market: str) -> None:
    new = {"jp": build_jp, "us": build_us}[market]()
    path = ROOT / "config" / f"universe_{market}.csv"
    themes = {}
    if path.exists():
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        themes = dict(zip(old["code"], old["themes"]))
        added = sorted(set(new["code"]) - set(old["code"]))
        removed = sorted(set(old["code"]) - set(new["code"]))
        print(f"追加: {added or 'なし'} / 除外: {removed or 'なし'}")
    new["themes"] = new["code"].map(lambda c: themes.get(c, ""))
    new = new.sort_values("code")[COLUMNS]
    new.to_csv(path, index=False, encoding="utf-8")
    print(f"{path.name}: {len(new)} 銘柄を書き出しました")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("jp", "us"):
        sys.exit("使い方: python scripts/build_universe.py jp|us")
    main(sys.argv[1])

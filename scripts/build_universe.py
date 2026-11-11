"""銘柄リストを公式の構成銘柄から作り直す。

使い方:
  python scripts/build_universe.py jp            逆張り用（TOPIX Core30 + Large70）→ config/universe_jp.csv
  python scripts/build_universe.py us            逆張り用（S&P 100）→ config/universe_us.csv
  python scripts/build_universe.py jp momentum   順張り用（TOPIX 500）→ config/universe_jp_momentum.csv
  python scripts/build_universe.py us momentum   順張り用（S&P 500）→ config/universe_us_momentum.csv

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
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
JP_SEGMENTS = {
    "contrarian": ["TOPIX Core30", "TOPIX Large70"],
    "momentum": ["TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"],
}
COLUMNS = ["code", "name", "sector", "themes"]


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 stock-screener"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def build_jp(kind: str) -> pd.DataFrame:
    """JPX 公式の TOPIX 構成銘柄から、規模区分で取り出す。"""
    text = _download(JPX_URL).decode("cp932")
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df = df[df["ニューインデックス区分"].isin(JP_SEGMENTS[kind])]
    return pd.DataFrame(
        {
            "code": df["コード"].str.strip(),
            # 全角の英数字を半角にそろえる
            "name": df["銘柄名"].map(lambda v: unicodedata.normalize("NFKC", v).strip()),
            "sector": df["業種"].str.strip(),
        }
    )


def build_us(kind: str) -> pd.DataFrame:
    """Wikipedia の S&P 100 / S&P 500 構成銘柄の表を読む。"""
    url, name_col, sector_col = (
        (SP500_URL, "Security", "GICS Sector") if kind == "momentum" else (SP100_URL, "Name", "Sector")
    )
    tables = pd.read_html(io.StringIO(_download(url).decode("utf-8")))
    table = next(t for t in tables if {"Symbol", name_col, sector_col} <= set(map(str, t.columns)))
    return pd.DataFrame(
        {
            # yfinance は BRK.B を BRK-B と書く
            "code": table["Symbol"].str.strip().str.replace(".", "-", regex=False),
            "name": table[name_col].str.strip(),
            "sector": table[sector_col].str.strip(),
        }
    )


def _themes(path: Path) -> dict:
    if not path.exists():
        return {}
    old = pd.read_csv(path, dtype=str, keep_default_na=False)
    return {code: themes for code, themes in zip(old["code"], old["themes"]) if themes}


def main(market: str, kind: str) -> None:
    new = {"jp": build_jp, "us": build_us}[market](kind)
    base = ROOT / "config" / f"universe_{market}.csv"
    path = base if kind == "contrarian" else ROOT / "config" / f"universe_{market}_momentum.csv"
    # 手動で付けたテーマを引き継ぐ（順張り用は、逆張り用に付けたテーマも使う）
    themes = {**_themes(base), **_themes(path)}
    if path.exists():
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        added = sorted(set(new["code"]) - set(old["code"]))
        removed = sorted(set(old["code"]) - set(new["code"]))
        print(f"追加: {added or 'なし'} / 除外: {removed or 'なし'}")
    new["themes"] = new["code"].map(lambda c: themes.get(c, ""))
    new = new.drop_duplicates("code").sort_values("code")[COLUMNS]
    new.to_csv(path, index=False, encoding="utf-8")
    print(f"{path.name}: {len(new)} 銘柄を書き出しました")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("jp", "us") or args[1:] not in ([], ["momentum"]):
        sys.exit("使い方: python scripts/build_universe.py jp|us [momentum]")
    main(args[0], "momentum" if args[1:] else "contrarian")

"""市場ごとの違い（ティッカーの書き方・基準指数・取引所カレンダーなど）をまとめる。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Market:
    key: str                 # "jp" / "us"
    label: str               # 画面のタブ名
    currency: str            # 表示通貨
    decimals: int            # 株価の小数点以下の桁数
    calendar: str            # 取引所カレンダー（exchange_calendars の名前）
    ticker_suffix: str       # yfinance のティッカーに付ける文字
    index_ticker: str        # 基準指数
    index_name: str
    vol_ticker: Optional[str]  # 恐怖指数（自動取得できない市場は None → 画面で手入力）
    vol_name: str
    vol_url: str             # 恐怖指数を確認できるページ
    fear_greed_url: str      # Fear & Greed を確認できるページ（手入力用）
    settle_minutes: int = 60  # 引けからこの分数が過ぎたら、その日のデータを確定とみなす

    def ticker(self, code: str) -> str:
        return code + self.ticker_suffix


def get(key: str) -> Market:
    from . import jp, us

    return {"jp": jp.MARKET, "us": us.MARKET}[key]

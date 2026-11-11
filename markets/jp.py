from . import Market

MARKET = Market(
    key="jp",
    label="日本株",
    currency="JPY",
    decimals=1,
    calendar="XTKS",
    ticker_suffix=".T",
    index_ticker="^N225",
    index_name="日経平均",
    # 日経VIは日経の著作物で再配布できないため自動取得しない（画面で手入力）
    vol_ticker=None,
    vol_name="日経VI",
    vol_url="https://indexes.nikkei.co.jp/nkave/index/profile?idx=nk225vi",
    fear_greed_url="",
    universe_name="TOPIX Core30 + Large70",
    momentum_universe_name="TOPIX 500",
)

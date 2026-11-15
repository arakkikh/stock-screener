from . import Market

MARKET = Market(
    key="us",
    label="米国株",
    currency="USD",
    decimals=2,
    calendar="XNYS",
    ticker_suffix="",
    index_ticker="^GSPC",
    index_name="S&P 500",
    vol_ticker="^VIX",
    vol_name="VIX",
    vol_url="https://www.cboe.com/tradable_products/vix/",
    fear_greed_url="https://edition.cnn.com/markets/fear-and-greed",
    universe_name="S&P 100",
    momentum_universe_name="S&P 500",
    # 公式のセクターETF（Select Sector SPDR）。GICS のセクター名と1対1に対応する
    sector_etfs=(
        ("Communication Services", "XLC"), ("Consumer Discretionary", "XLY"), ("Consumer Staples", "XLP"),
        ("Energy", "XLE"), ("Financials", "XLF"), ("Health Care", "XLV"), ("Industrials", "XLI"),
        ("Information Technology", "XLK"), ("Materials", "XLB"), ("Real Estate", "XLRE"), ("Utilities", "XLU"),
    ),
)

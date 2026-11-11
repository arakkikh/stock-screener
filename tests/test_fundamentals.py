import copy
import datetime as dt

import pytest

from screener import fundamentals as fu
from tests.helpers import cfg

TODAY = dt.date(2026, 11, 11)


def year(date, **over):
    base = {
        "date": date, "revenue": 1000.0, "net_income": 100.0, "eps": 100.0, "ebit": 150.0, "interest": -10.0,
        "assets": 2000.0, "equity": 1000.0, "debt": 400.0, "cur_assets": 800.0, "cur_liab": 400.0,
        "ocf": 150.0, "fcf": 90.0, "dividends_paid": -30.0,
    }
    return {**base, **over}


def company(**over):
    """健全な会社の財務データ。over で一部を書き換える。"""
    base = {
        "price": 1500.0, "shares": 1.0, "eps": 100.0, "bvps": 1000.0, "ebitda": 200.0,
        "total_debt": 400.0, "total_cash": 100.0, "roe": 0.12, "roa": 0.06, "payout": 0.3,
        "div_rate": 30.0, "div_ttm": 30.0, "fcf": 90.0, "ocf": 150.0, "currency": "JPY", "price_currency": "JPY",
        "est": {"eps_growth_0y": 0.08, "eps_growth_1y": 0.2, "rev_growth_0y": 0.05, "rev_growth_1y": 0.06, "analysts": 10},
        "annual": [
            year("2026-03-31"),
            year("2025-03-31", eps=90.0, net_income=85.0, debt=450.0),
            year("2024-03-31", eps=80.0, net_income=80.0, debt=500.0),
            year("2023-03-31", eps=70.0, net_income=70.0, debt=600.0),
        ],
        "div_by_year": {str(y): 10.0 + (y - 2015) for y in range(2015, 2027)},
    }
    merged = copy.deepcopy(base)
    merged.update(over)
    return merged


STATS = {"per": 20.0, "pbr": 2.0, "ev_ebitda": 12.0, "eps_growth": 10.0, "rev_growth": 4.0,
         "sector_per": {"製造": 18.0}, "yield_low": 1.0, "yield_high": 3.0}


def m_of(facts, price=1500.0, financial=False):
    return fu.metrics(facts, price, cfg(), TODAY, financial)


def result(facts, price=1500.0, financial=False, stats=STATS, sector="製造"):
    return fu.checks(m_of(facts, price, financial), stats, sector, cfg())


# ---- 指標の計算 ----

def test_valuation_metrics():
    m = m_of(company())
    assert m["per"] == pytest.approx(15.0)
    assert m["pbr"] == pytest.approx(1.5)
    assert m["peg"] == pytest.approx(15.0 / 20.0)             # PER ÷ 来期の予想EPS成長率(20%)
    assert m["ev_ebitda"] == pytest.approx((1500 + 400 - 100) / 200)
    assert m["fcf_yield"] == pytest.approx(6.0)
    assert m["div_yield"] == pytest.approx(2.0)


def test_metrics_use_the_given_price_not_the_stored_one():
    assert m_of(company(), price=3000.0)["per"] == pytest.approx(30.0)
    assert fu.metrics(company(), None, cfg(), TODAY)["per"] == pytest.approx(15.0)  # 株価がなければ取得時の値


def test_loss_making_company_has_no_per():
    m = m_of(company(eps=-5.0))
    assert m["per"] is None and m["peg"] is None and m["loss"]


def test_growth_falls_back_to_this_year_when_next_year_is_missing():
    est = {"eps_growth_0y": 0.08, "eps_growth_1y": None, "rev_growth_0y": 0.05, "rev_growth_1y": None, "analysts": 2}
    m = m_of(company(est=est))
    assert m["eps_g_next"] == pytest.approx(8.0) and m["rev_g_next"] == pytest.approx(5.0)


def test_eps_growth_history():
    m = m_of(company())
    assert m["eps_cagr"] == pytest.approx(((100 / 70) ** (1 / 3) - 1) * 100)
    assert m["eps_g_last"] == pytest.approx((100 / 90 - 1) * 100)


def test_eps_cagr_needs_positive_start_and_two_years():
    assert m_of(company(annual=[year("2026-03-31"), year("2025-03-31")]))["eps_cagr"] is None
    turnaround = [year("2026-03-31"), year("2025-03-31"), year("2024-03-31"), year("2023-03-31", eps=-10.0)]
    assert m_of(company(annual=turnaround))["eps_cagr"] is None


def test_health_metrics():
    m = m_of(company())
    assert m["current_ratio"] == pytest.approx(2.0)
    assert m["de"] == pytest.approx(0.4) and m["de_old"] == pytest.approx(0.6)
    assert m["ocf_to_debt"] == pytest.approx(150 / 400)
    assert m["interest_cover"] == pytest.approx(15.0)
    assert m["equity_ratio"] == pytest.approx(50.0)


def test_currency_mismatch_blocks_market_cap_ratios():
    m = m_of(company(currency="USD", price_currency="JPY"))
    assert m["ev_ebitda"] is None and m["fcf_yield"] is None
    assert m["per"] is not None  # 1株あたりの数値どうしは比べられる


def test_dividend_history():
    m = m_of(company())
    assert m["payer"] and m["div_stable"] and m["div_growing"]
    cut = {str(y): (5.0 if y == 2020 else 10.0 + (y - 2015)) for y in range(2015, 2027)}
    assert not m_of(company(div_by_year=cut))["div_stable"]
    short = {str(y): 10.0 for y in range(2020, 2027)}
    m_short = m_of(company(div_by_year=short))
    assert not m_short["div_full_history"] and not m_short["div_stable"] and not m_short["div_growing"]


def test_dividend_history_ignores_the_unfinished_current_year():
    # 今年（2026年）はまだ途中なので、少なくても減配とみなさない
    partial = {str(y): 10.0 + (y - 2015) for y in range(2015, 2026)}
    partial["2026"] = 1.0
    assert m_of(company(div_by_year=partial))["div_stable"]


def test_non_payer():
    m = m_of(company(div_rate=None, div_ttm=0.0, div_by_year={}, payout=0.0))
    assert not m["payer"] and m["div_yield"] == 0.0


def test_dividend_yield_uses_payment_history_not_the_quoted_rate():
    # Yahoo の「年間配当」(div_rate) が実際と違っていても、支払い履歴の合計を使う
    assert m_of(company(div_rate=5.0, div_ttm=60.0))["div_yield"] == pytest.approx(4.0)


def test_dividend_yield_fallback_when_trailing_sum_is_missing():
    facts = company(div_rate=5.0)
    del facts["div_ttm"]
    # 今年の支払い済み 21円、昨年 20円 → 大きいほうの 21円 を使う
    assert m_of(facts)["div_yield"] == pytest.approx(21.0 / 1500 * 100)


def test_fcf_yield_prefers_annual_statement():
    assert m_of(company(fcf=-9999.0))["fcf_yield"] == pytest.approx(6.0)      # 年次決算の 90 を使う
    no_annual_fcf = [year("2026-03-31", fcf=None), year("2025-03-31"), year("2024-03-31")]
    assert m_of(company(annual=no_annual_fcf, fcf=45.0))["fcf_yield"] == pytest.approx(3.0)


def test_roe_and_roa_fall_back_to_annual_statement():
    m = m_of(company(roe=None, roa=None))
    assert m["roe"] == pytest.approx(10.0)   # 純利益 100 ÷ 自己資本 1000
    assert m["roa"] == pytest.approx(5.0)    # 純利益 100 ÷ 総資産 2000


# ---- 項目ごとの判定 ----

def test_healthy_company_passes_most_checks():
    r = result(company())
    assert r["value"] == [True, True, True, True, True, True]
    assert r["growth"] == [True, True, True, True, True, True]
    assert r["past"] == [True, False, True, True, True, True]   # 直近の成長(11%)は3年平均(12.6%)より低い
    assert r["health"] == [True, True, True, True, True, True]
    assert r["dividend"] == [True, False, True, True, True, True]  # 利回り2%は上位水準(3%)に届かない


def test_expensive_stock_fails_value_checks():
    r = result(company(), price=6000.0)   # PER 60、PBR 6
    assert r["value"][:3] == [False, False, False]
    assert r["value"][3] is False          # PEG = 60 ÷ 20 = 3
    assert r["value"][5] is False          # FCF利回り 1.5%


def test_loss_making_company_fails_per_checks_instead_of_unknown():
    r = result(company(eps=-5.0))
    assert r["value"][0] is False and r["value"][1] is False and r["value"][3] is False


def test_sector_check_is_unknown_without_sector_median():
    assert result(company(), sector="その他")["value"][1] is None


def test_shrinking_earnings_fail_growth_checks():
    est = {"eps_growth_0y": -0.1, "eps_growth_1y": -0.05, "rev_growth_0y": -0.02, "rev_growth_1y": 0.01, "analysts": 5}
    r = result(company(est=est))
    assert r["growth"] == [False, False, False, False, False, False]
    assert r["value"][3] is False  # 減益予想なら PEG は不合格


def test_no_analyst_estimates_means_unknown_growth():
    est = {"eps_growth_0y": None, "eps_growth_1y": None, "rev_growth_0y": None, "rev_growth_1y": None, "analysts": None}
    r = result(company(est=est))
    assert r["growth"] == [None] * 6
    assert fu.axis_score(r["growth"], cfg()) is None


def test_weak_balance_sheet_fails_health_checks():
    weak = [
        year("2026-03-31", debt=1500.0, equity=500.0, assets=3000.0, cur_assets=300.0, cur_liab=600.0, ocf=100.0, ebit=30.0),
        year("2025-03-31", debt=1200.0, equity=500.0),
        year("2024-03-31", debt=1000.0, equity=500.0),
    ]
    assert result(company(annual=weak))["health"] == [False, False, False, False, False, False]


def test_debt_free_company_passes_debt_checks():
    clean = [year(d, debt=0.0, interest=None) for d in ("2026-03-31", "2025-03-31", "2024-03-31")]
    r = result(company(annual=clean))
    assert r["health"][1:5] == [True, True, True, True]


def test_financial_sector_health_is_not_scored():
    r = result(company(), financial=True)
    assert r["health"] == [None] * 6
    assert fu.axis_score(r["health"], cfg()) is None
    assert r["past"][5] is None and r["dividend"][3] is None
    assert r["value"][4] is None and r["value"][5] is None   # EV/EBITDA と FCF利回りも判定しない
    assert fu.axis_score(r["value"], cfg()) == 4             # 残りの4項目で採点する
    assert fu.axis_score(r["past"], cfg()) is not None


def test_non_payer_scores_zero_on_dividend():
    r = result(company(div_rate=None, div_ttm=0.0, div_by_year={}, payout=0.0))
    assert r["dividend"] == [False] * 6
    assert fu.axis_score(r["dividend"], cfg()) == 0


def test_payout_above_limit_fails():
    assert result(company(payout=0.9))["dividend"][2] is False
    assert result(company(payout=0.7))["dividend"][2] is True


def test_dividend_not_covered_by_free_cash_flow_fails():
    annual = [year("2026-03-31", fcf=20.0, dividends_paid=-30.0), year("2025-03-31"), year("2024-03-31")]
    assert result(company(annual=annual))["dividend"][3] is False


def test_thresholds_come_from_config():
    c = cfg()
    c["fundamentals"]["past"]["roe_min_pct"] = 15
    assert fu.checks(m_of(company()), STATS, "製造", c)["past"][2] is False
    assert cfg("jp")["fundamentals"]["financial_sectors"] != cfg("us")["fundamentals"]["financial_sectors"]


# ---- 軸の点数 ----

def test_axis_score_counts_passes():
    assert fu.axis_score([True, True, False, None, True, False], cfg()) == 3


def test_axis_score_is_none_when_mostly_unknown():
    assert fu.axis_score([True, None, None, None, True, False], cfg()) == 2   # 判定不可3つまでは採点
    assert fu.axis_score([True, None, None, None, None, False], cfg()) is None


# ---- 対象銘柄全体 ----

def test_universe_medians_and_scoring():
    facts = {
        "CHEAP": company(),                          # PER 10
        "MID": company(),                            # PER 20
        "RICH": company(),                           # PER 40
        "LOSS": company(eps=-5.0),
        "NODIV": company(div_rate=None, div_ttm=0.0, div_by_year={}, payout=0.0),
    }
    prices = {"CHEAP": 1000.0, "MID": 2000.0, "RICH": 4000.0, "LOSS": 1500.0, "NODIV": 3000.0}
    sectors = {code: "製造" for code in facts}
    out = fu.score_universe(facts, prices, sectors, cfg(), TODAY)
    stats = out["stats"]
    assert stats["per"] == pytest.approx(25.0)             # 10, 20, 30, 40 の中央値（赤字は除く）
    assert stats["sector_per"]["製造"] == pytest.approx(25.0)
    assert stats["yield_low"] < stats["yield_high"]        # 無配の銘柄は基準に入れない
    cheap, rich = out["stocks"]["CHEAP"], out["stocks"]["RICH"]
    assert cheap["c"]["value"][0] is True and rich["c"]["value"][0] is False
    assert cheap["s"][0] > rich["s"][0]
    assert out["stocks"]["NODIV"]["s"][4] == 0
    assert out["stocks"]["LOSS"]["c"]["value"][0] is False
    assert len(cheap["s"]) == 5 and all(len(v) == 6 for v in cheap["c"].values())


def test_sector_median_needs_enough_stocks():
    facts = {"A": company(), "B": company()}
    out = fu.score_universe(facts, {"A": 1000.0, "B": 2000.0}, {"A": "製造", "B": "製造"}, cfg(), TODAY)
    assert out["stats"]["sector_per"] == {}
    assert out["stocks"]["A"]["c"]["value"][1] is None


def test_financial_sector_comes_from_config():
    facts = {"BANK": company(), "MAKER": company()}
    out = fu.score_universe(facts, {}, {"BANK": "銀行業", "MAKER": "電気機器"}, cfg("jp"), TODAY)
    assert out["stocks"]["BANK"]["s"][3] is None
    assert out["stocks"]["MAKER"]["s"][3] == 6

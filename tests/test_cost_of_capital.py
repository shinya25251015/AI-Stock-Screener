"""株主資本コストの解決のテスト。

最重要の性質は「**未検証の市場では黙って計算しない**」こと。海外株の資本コストは
現地10年国債利回りに依存し、記憶で埋めると§8違反になる。
"""

import pytest

from screener import cost_of_capital


def test_japan_is_eight_percent():
    coe = cost_of_capital.resolve("JP")
    assert coe.pct == 8.0
    assert coe.pct == cost_of_capital.JP_COST_OF_EQUITY_PCT
    assert coe.asof  # 根拠と日付が空でないこと
    assert coe.source


def test_unverified_market_raises(tmp_path):
    with pytest.raises(cost_of_capital.UnverifiedMarketError):
        cost_of_capital.resolve("US")


def test_unknown_market_raises():
    with pytest.raises(cost_of_capital.UnknownMarketError):
        cost_of_capital.resolve("ZZ")


def test_verified_overseas_market_is_risk_free_plus_erp(tmp_path):
    config = tmp_path / "coc.yaml"
    config.write_text(
        "markets:\n"
        "  US:\n"
        "    name: 米国\n"
        "    risk_free_pct: 4.2\n"
        "    erp_pct: 5.5\n"
        "    verified: true\n"
        '    asof: "2026-08-12"\n'
        '    source: "米財務省 Daily Treasury Yield Curve"\n'
        '    currency: "USD"\n',
        encoding="utf-8",
    )
    coe = cost_of_capital.resolve("US", config_path=config)
    assert coe.pct == pytest.approx(9.7)
    assert "4.20%" in coe.basis and "5.50%" in coe.basis


def test_override_bypasses_verification_but_is_labelled():
    coe = cost_of_capital.resolve("US", override_pct=9.5)
    assert coe.pct == 9.5
    assert "上書き" in coe.basis


def test_market_from_ticker_suffix():
    assert cost_of_capital.market_for_ticker("6258.T") == "JP"
    assert cost_of_capital.market_for_ticker("6623.N") == "JP"  # 名証
    assert cost_of_capital.market_for_ticker("MSFT") == "US"
    with pytest.raises(ValueError):
        cost_of_capital.market_for_ticker("ASML.AS")

"""finance.yahoo.co.jp のHTMLパースのテスト。ネットワークには一切触らない。

fixture は 2026-08-12 に実際に取得した 3769.T のページから、指標部分だけを抜き出して
クラス名・入れ子構造をそのまま残したもの。ページ構造が変わるとここが落ちるので、
落ちたら parse_quote() のセレクタを直す（＝構造変更に気づける仕掛け）。
"""

from pathlib import Path

import pytest

from screener import yahoo_jp

FIXTURE = Path(__file__).parent / "fixtures" / "quote_3769_trimmed.html"


@pytest.fixture(scope="module")
def quote():
    return yahoo_jp.parse_quote(FIXTURE.read_text(encoding="utf-8"), ticker="3769.T")


def test_price_comes_from_the_price_board_not_the_previous_close(quote):
    # 前日終値 10,235 ではなく、株価 10,175 を拾うこと。
    assert quote.price == 10175.0


def test_core_metrics(quote):
    assert quote.pbr == 6.59
    assert quote.roe_pct == 20.22
    assert quote.bps == 1544.26
    assert quote.per == 33.01
    assert quote.eps == 308.27
    assert quote.equity_ratio_pct == 27.8


def test_market_cap_is_converted_to_yen(quote):
    # 778,973百万円 → 7,789.73億円
    assert quote.market_cap_yen == 778_973 * 1_000_000
    assert round(quote.market_cap_yen / 100_000_000) == 7790


def test_shares_outstanding(quote):
    assert quote.shares_outstanding == 76_557_545


def test_name_is_extracted(quote):
    # 証券コードの【】・「：株価・株式情報」・サイト名を落として社名だけにする。
    assert quote.name == "ＧＭＯペイメントゲートウェイ(株)"


def test_forecast_roe_is_derived_from_eps_over_bps(quote):
    """Yahoo!は予想ROEを持たないため EPS(会社予想)÷BPS(実績) で近似する。

    308.27 / 1,544.26 = 19.96%。実績ROE20.22%とほぼ同水準＝"山"ではない。
    あくまで概算であり、B-4判定には使わない（比は実績ROEで計算する）。
    """
    assert round(quote.forecast_roe_pct, 2) == 19.96


def test_pbr_is_consistent_with_price_over_bps(quote):
    # 取得値の内部整合チェック。乖離が大きいときは verified_fundamentals での上書きを疑う。
    assert abs(quote.price / quote.bps - quote.pbr) < 0.05


def test_yen_unit_conversion():
    assert yahoo_jp._to_yen("778,973百万円(15:30)") == 778_973_000_000
    assert yahoo_jp._to_yen("1,234億円") == 123_400_000_000
    assert yahoo_jp._to_yen("2.5兆円") == 2_500_000_000_000
    assert yahoo_jp._to_yen("") is None


def test_number_parsing_strips_prefix_and_suffix():
    assert yahoo_jp._to_number("(連)6.59倍(15:30)") == 6.59
    assert yahoo_jp._to_number("---") is None
    assert yahoo_jp._to_number("-1.23%") == -1.23


def test_unparseable_page_sets_error_instead_of_raising():
    quote = yahoo_jp.parse_quote("<html><body>maintenance</body></html>", ticker="9999.T")
    assert quote.error
    assert quote.pbr is None

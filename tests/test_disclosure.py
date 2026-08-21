"""決算短信の原本ルートと特別損益パーサのテスト。ネットワークには一切触らない。

fixture はすべて 2026-08-21 に実際に取得したものを抜き出したもの:

- `disclosure_yahoo_4483_trimmed.html`  … JMDCの開示一覧（Yahoo）
- `disclosure_kabupro_3038_trimmed.html`… 神戸物産の開示一覧（kabupro。href が引用符なし）
- `tanshin_1414_trimmed.txt`            … ショーボンドHD 26/6期 短信（百万円・非支配が行またぎ）
- `tanshin_3778_trimmed.txt`            … さくらインターネット 26/3期 短信（千円・特別損益が相殺）

取得元のHTML構造が変わればここが落ちる（＝構造変更に気づける仕掛け）。
"""

from pathlib import Path

import pytest

from screener import disclosure, valuation

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------
# 開示一覧のパース
# --------------------------------------------------------------------------


def test_yahoo_disclosures_pair_title_with_link():
    html = (FIXTURES / "disclosure_yahoo_4483_trimmed.html").read_text(encoding="utf-8")
    items = disclosure.parse_yahoo_disclosures(html)
    assert len(items) == 2
    assert all(d.url.endswith(".pdf") for d in items)
    assert all(d.source == "yahoo" for d in items)
    titles = [d.title for d in items]
    assert any("第１四半期決算短信" in t for t in titles)
    assert any(t.startswith("2026年３月期 決算短信") for t in titles)


def test_kabupro_reads_hrefs_without_quotes():
    # kabupro は `href=http://...` と引用符が無い。引用符を前提にすると0件になる。
    html = (FIXTURES / "disclosure_kabupro_3038_trimmed.html").read_text(encoding="utf-8")
    items = disclosure.parse_kabupro_disclosures(html)
    assert len(items) == 3
    assert all(d.url.startswith("http://ke.kabupro.jp/") for d in items)
    assert items[0].date == "2026-06-12"


def test_annual_tanshin_excludes_quarterly_and_corrections():
    items = [
        disclosure.Disclosure("2026-08-06", "2027年3月期 第1四半期決算短信〔日本基準〕（連結）", "a"),
        disclosure.Disclosure("2026-01-30", "（訂正・数値データ訂正）「2025年10月期 決算短信」", "b"),
        disclosure.Disclosure("2025-12-12", "2025年10月期 決算短信〔日本基準〕（連結）", "c"),
        disclosure.Disclosure("2026-06-12", "2026年10月期 第２四半期（中間期）決算短信", "d"),
    ]
    annual = disclosure.latest_annual_tanshin(items)
    assert annual is not None
    assert annual.url == "c"


def test_annual_tanshin_returns_none_when_only_quarterly_survive():
    # Yahoo側は保存が約1年なので、3月期・9月期の本決算は落ちることがある。
    # そのときは None を返し、CLI が kabupro を促す（推測で四半期を使わない）。
    items = [disclosure.Disclosure("2026-08-06", "2027年3月期 第1四半期決算短信", "a")]
    assert disclosure.latest_annual_tanshin(items) is None


def test_ifrs_flag_reads_the_full_width_notation():
    assert disclosure.Disclosure("", "2026年３月期 決算短信〔ＩＦＲＳ〕（連結）", "").is_ifrs
    assert not disclosure.Disclosure("", "2026年６月期 決算短信〔日本基準〕（連結）", "").is_ifrs


# --------------------------------------------------------------------------
# 特別損益のパース
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shobond():
    return disclosure.parse_special_items(
        (FIXTURES / "tanshin_1414_trimmed.txt").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def sakura():
    return disclosure.parse_special_items(
        (FIXTURES / "tanshin_3778_trimmed.txt").read_text(encoding="utf-8")
    )


def test_reads_the_table_row_not_the_narrative_sentence(shobond):
    # 原本の本文には「税金等調整前当期純利益による22,572百万円及び売上債権の減少による
    # 6,004百万円の……」という行があり、素朴に拾うと 6,004 を掴む。表の行を採ること。
    assert shobond.pretax_income == 22572
    assert shobond.unit_label == "百万円"


def test_reads_minority_interest_split_across_lines(shobond):
    # 「非支配株主に帰属する当期純利益又は非支配株主に／帰属する当期純損失（△） △24 72」
    assert shobond.minority_interest == 72


def test_special_items_and_equity(shobond):
    assert shobond.special_gains == 1138  # 投資有価証券売却益
    assert shobond.special_losses == 51
    assert shobond.equity_end == 106922
    assert shobond.equity_begin == 105101
    assert shobond.equity_average == pytest.approx(106011.5)
    assert shobond.complete


def test_evidence_is_always_returned(shobond):
    # §14 完全引用ルール: 引用を示せない判定は無効。根拠の行を必ず持ち帰る。
    assert any("特別利益合計" in line for line in shobond.evidence)
    assert any("（参考）自己資本" in line for line in shobond.evidence)


def test_actual_roe_is_reproduced_from_the_primary_source(shobond):
    # Yahoo（準一次）の実績ROE 14.56% を原本の実額から再現できること。
    net = (shobond.pretax_income - shobond.tax_total) - shobond.minority_interest
    assert net / shobond.equity_average * 100 == pytest.approx(14.56, abs=0.02)


def test_normalized_roe_drops_when_gains_are_one_off(shobond):
    normalized = valuation.normalized_roe_from_special_items(
        pretax_income=shobond.pretax_income,
        special_gains=shobond.special_gains,
        special_losses=shobond.special_losses,
        equity=shobond.equity_average,
        tax_total=shobond.tax_total,
        minority_interest=shobond.minority_interest,
    )
    assert normalized == pytest.approx(13.86, abs=0.02)  # 実績14.56%から-0.70pt


def test_equity_unit_is_converted_to_the_table_unit(sakura):
    # 表は千円、（参考）自己資本は百万円。揃えないとROEが1000倍ずれる。
    assert sakura.unit_label == "千円"
    assert sakura.equity_end == 30_101_000
    assert sakura.pretax_income == 244_322


def test_offsetting_subsidy_and_impairment_are_both_removed(sakura):
    # 国庫補助金等収入14,311,693千円と固定資産圧縮損14,311,693千円は相殺関係にある。
    # 片方だけ除くとROEが跳ねる。純額だけを戻すこと。
    assert sakura.special_gains == 14_467_348
    assert sakura.special_losses == 14_328_503
    normalized = valuation.normalized_roe_from_special_items(
        pretax_income=sakura.pretax_income,
        special_gains=sakura.special_gains,
        special_losses=sakura.special_losses,
        equity=sakura.equity_average,
        tax_total=sakura.tax_total,
        minority_interest=sakura.minority_interest,
    )
    assert normalized == pytest.approx(0.27, abs=0.02)  # 実績0.72%より更に低い


def test_ifrs_text_is_refused_instead_of_guessed():
    # IFRSに「特別損益」は無い。「その他の収益/費用」で代用すると§8違反になる。
    ifrs = "売上収益 100\nその他の収益 5\n税引前利益 30\n法人所得税費用 9\n"
    items = disclosure.parse_special_items(ifrs)
    assert items is not None
    assert items.is_ifrs
    assert not items.complete


def test_non_tanshin_text_returns_none():
    assert disclosure.parse_special_items("ただのお知らせです") is None


def test_missing_items_are_reported_not_filled_in():
    text = "（単位：百万円）\n税金等調整前当期純利益 100 200\n法人税等合計 30 60\n"
    items = disclosure.parse_special_items(text)
    assert items.pretax_income == 200
    # 特別利益・特別損失の区分が無い期は 0（実在する。GSX4417の26/3期は特別利益なし）
    assert items.special_gains == 0
    # 自己資本が読めなければ missing に出す。推測で埋めない。
    assert "（参考）自己資本" in items.missing
    assert not items.complete


# --------------------------------------------------------------------------
# 実効税率の前年比較（特別損益欄に出ない嵩上げ）
# --------------------------------------------------------------------------


def test_previous_period_values_are_kept_for_the_tax_check(shobond):
    # 短信の連結P/Lは「前期／当期」の2列。前期を捨てると税率の比較ができない。
    assert shobond.pretax_income_prev == 21801
    assert shobond.tax_total_prev == 6765
    assert shobond.special_gains_prev == 813  # 前期も投資有価証券売却益がある（2期連続）


def test_effective_tax_rate_is_stable_for_shobond(shobond):
    check = valuation.TaxRateCheck(
        current_pct=valuation.effective_tax_rate_pct(
            shobond.pretax_income, shobond.tax_total
        ),
        previous_pct=valuation.effective_tax_rate_pct(
            shobond.pretax_income_prev, shobond.tax_total_prev
        ),
    )
    assert check.current_pct == pytest.approx(31.28, abs=0.02)
    assert check.previous_pct == pytest.approx(31.03, abs=0.02)
    assert not check.anomalous


def test_non_consolidated_tanshin_uses_a_different_pretax_label():
    # 非連結（個別）の短信は「税引前当期純利益」。連結の「税金等調整前当期純利益」を
    # 前提にすると読めない（第一建設工業1799が非連結で実例）。
    # IFRSの「税引前利益」とは別物なので、IFRS扱いに落としてもいけない。
    text = (
        "（参考）自己資本 2026年３月期 74,702百万円 2025年３月期 71,657百万円\n"
        "(単位：千円)\n"
        "経常利益 7,604,601 7,508,553\n"
        "特別利益合計 3,822 7,069\n"
        "特別損失合計 69,188 30,187\n"
        "税引前当期純利益 7,539,235 7,485,435\n"
        "法人税等合計 2,296,522 2,261,536\n"
    )
    items = disclosure.parse_special_items(text)
    assert items is not None
    assert not items.is_ifrs
    assert items.pretax_income == 7_485_435
    assert items.complete
    net = items.pretax_income - items.tax_total
    assert net / items.equity_average * 100 == pytest.approx(7.14, abs=0.02)

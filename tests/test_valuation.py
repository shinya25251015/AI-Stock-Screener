"""安さ足切りロジックのテスト。ネットワーク不要。

実在の銘柄の実測値を使い、Future100 側の記録と同じ数字が出ることを確認する。
数字の出典は各テストの docstring に書いてある（§8）。
"""

import pytest

from screener import valuation
from screener.valuation import RoeInput


def test_fair_pbr_is_roe_over_cost_of_equity():
    assert valuation.fair_pbr(16.0, 8.0) == 2.0


def test_ratio_and_verdict_boundaries():
    # 比1.0ちょうどは「中間帯」、1.5ちょうどは「発見済み」。
    assert valuation.verdict_for_ratio(0.99) == valuation.VERDICT_PRE_IGNITION
    assert valuation.verdict_for_ratio(1.00) == valuation.VERDICT_MIDDLE
    assert valuation.verdict_for_ratio(1.49) == valuation.VERDICT_MIDDLE
    assert valuation.verdict_for_ratio(1.50) == valuation.VERDICT_DISCOVERED


def test_overseas_cost_of_equity_changes_the_verdict():
    """同じPBR/ROEでも資本コストが上がると発見済み側に寄る。

    ROE12%・PBR1.8倍の会社は、日本(8%)なら妥当PBR1.5倍で比1.20＝中間帯。
    資本コスト10%の市場では妥当PBR1.2倍で比1.50＝発見済み。
    """
    assert valuation.verdict_for_ratio(valuation.discovered_ratio(1.8, 12.0, 8.0)) == valuation.VERDICT_MIDDLE
    assert valuation.verdict_for_ratio(valuation.discovered_ratio(1.8, 12.0, 10.0)) == valuation.VERDICT_DISCOVERED


def test_quality_floor_blocks_low_roe():
    result = valuation.screen(
        code="1376", name="カネコ種苗", ticker="1376.T", market="JP",
        cost_of_equity_pct=8.0, pbr=0.63, roe=RoeInput(actual_pct=5.87),
    )
    assert result.quality_floor_passed is False
    assert result.passed is False
    assert any("品質フロア割れ" in f for f in result.flags)


def test_normalized_roe_can_make_a_cheap_looking_stock_expensive():
    """日東紡(3110): 固定資産売却益込みの実績ROE27.54%だと発火前に見える。

    正常化ROE11.4%で引き直すと発見済み。歪みが「割安に見せる」方向に効いた例。
    出典: Future100 config/watchlist.yaml 3110 の roe_caution / normalized_roe_pct。
    """
    naive = valuation.screen(
        code="3110", name="日東紡", ticker="3110.T", market="JP",
        cost_of_equity_pct=8.0, pbr=2.91, roe=RoeInput(actual_pct=27.54),
    )
    assert naive.verdict == valuation.VERDICT_PRE_IGNITION

    corrected = valuation.screen(
        code="3110", name="日東紡", ticker="3110.T", market="JP",
        cost_of_equity_pct=8.0, pbr=2.91,
        roe=RoeInput(actual_pct=27.54, normalized_pct=11.4, caution="固定資産売却益による一過性"),
    )
    assert corrected.verdict == valuation.VERDICT_DISCOVERED
    assert round(corrected.ratio, 2) == 2.04
    assert any("正常化ROEで判定" in f for f in corrected.flags)


def test_normalized_roe_can_make_an_expensive_looking_stock_cheaper():
    """品川リフラ(5351): 一過性の資産売却益で実績ROEが嵩上げされた逆方向の例。

    歪みが「割高に見せる」方向にも効くことを、同じ関数で扱えることの確認。
    """
    normalized = valuation.screen(
        code="5351", name="品川リフラクトリーズ", ticker="5351.T", market="JP",
        cost_of_equity_pct=8.0, pbr=0.89,
        roe=RoeInput(actual_pct=26.6, normalized_pct=8.0, caution="固定資産売却益372億の一過性"),
    )
    assert normalized.verdict == valuation.VERDICT_PRE_IGNITION
    assert round(normalized.ratio, 2) == 0.89


def test_forecast_roe_is_used_only_as_a_peak_check():
    """東亜建設工業(1885): 実績ROE17.36%では比0.61＝発火前に見えるが、

    会社予想ROE11.0%で引き直すと比約0.97＝中間帯の入口。合否は実績ROE側で決まるが、
    山リスクがフラグとして立つこと。出典: Future100 watchlist.yaml 1885 の2026-08-10記録。
    """
    result = valuation.screen(
        code="1885", name="東亜建設工業", ticker="1885.T", market="JP",
        cost_of_equity_pct=8.0, pbr=1.33,
        roe=RoeInput(actual_pct=17.36, forecast_pct=11.0),
    )
    assert result.verdict == valuation.VERDICT_PRE_IGNITION
    assert round(result.ratio, 2) == 0.61
    assert round(result.forecast_ratio, 2) == 0.97
    assert any("山リスク" in f for f in result.flags)


def test_missing_data_does_not_raise():
    result = valuation.screen(
        code="5352", name="黒崎播磨", ticker="5352.T", market="JP",
        cost_of_equity_pct=8.0, pbr=None, roe=RoeInput(actual_pct=14.52),
    )
    assert result.error
    assert result.passed is False
    assert any("上場状態" in f for f in result.flags)


def test_size_band_labels():
    assert "主軸サイズ帯" in valuation.size_band_label(20_000_000_000)
    assert "帯下" in valuation.size_band_label(5_000_000_000)
    assert "別枠級" in valuation.size_band_label(500_000_000_000)
    assert valuation.size_band_label(None) == "時価総額不明"


def test_verified_fundamentals_override_fetched_values():
    entry = {
        "verified_fundamentals": {"bvps_yen": 2556.32, "roe_pct": 8.37},
    }
    assert round(valuation.effective_pbr(entry, price=3865.0, fetched_pbr=9.99), 2) == 1.51
    roe = valuation.roe_from_entry(entry, fetched_roe_pct=99.0)
    assert roe.actual_pct == 8.37
    assert roe.effective_source() == "実績ROE"


def test_normalized_entry_round_trip():
    entry = {
        "verified_fundamentals": {"roe_pct": 27.54},
        "normalized_roe_pct": 11.4,
        "roe_caution": "固定資産売却益による一過性",
        "normalized_roe_basis": "27/3期の営業利益予想300億から純利益約210億を見込み",
    }
    roe = valuation.roe_from_entry(entry)
    assert roe.effective_pct() == 11.4
    assert roe.effective_source() == "正常化ROE"
    assert "一過性" in roe.caution


# ---------------------------------------------------------------------------
# 特別損益による実績ROEの嵩上げ（2026-08-18追加）
#
# 大同信号(6743)で、①の原本確認を終えてから品質フロア割れが判明した。
# 実績ROE6.87%は投資有価証券売却益による嵩上げで、正常化すると5.93%だった。
# 同型は日本カーボン(5302)でも起きており、どちらも補正前は「発火前・フロア通過」に
# 見えていた。以下は原本の実額での回帰テスト。
# ---------------------------------------------------------------------------


def test_normalized_roe_nippon_carbon_falls_below_quality_floor():
    """日本カーボン(5302) 25/12期決算短信原本（2026-02-10開示）の実額。

    特別利益3,530（全額 投資有価証券売却益）・特別損失803（火災損失）。
    実績ROEは原本記載の9.1%だが、一過性を除くと5.55%でフロア割れ。
    """
    normalized = valuation.normalized_roe_from_special_items(
        pretax_income=7829,
        special_gains=3530,
        special_losses=803,
        tax_total=2441,
        minority_interest=557,
        equity=(52014 + 54393) / 2,  # 24/12期末と25/12期末の平均
    )
    assert 5.4 < normalized < 5.7
    assert normalized < valuation.QUALITY_FLOOR_ROE_PCT
    # 補正前の実績9.08%はフロアを通ってしまう＝これが見落としの正体
    assert 9.08 > valuation.QUALITY_FLOOR_ROE_PCT


def test_screen_flags_unverified_special_items_on_otherwise_passing_stock():
    """安さ・品質を通っていても、特別損益が未確認なら未確認として出す。

    大同信号(6743)の補正前の姿（PBR0.62／実績ROE6.87%／比0.72）。
    「発火前・フロア通過」で passed になるが、needs_primary_check が立つ。
    """
    result = valuation.screen(
        code="6743",
        name="大同信号",
        ticker="6743.T",
        market="東証S",
        cost_of_equity_pct=8.0,
        pbr=0.62,
        roe=valuation.RoeInput(actual_pct=6.87),
        market_cap_yen=19_300_000_000,
    )
    assert result.verdict == valuation.VERDICT_PRE_IGNITION
    assert result.quality_floor_passed is True
    assert result.passed is True
    # 通ってはいるが、①の原本確認へ進む前に潰すべき宿題が残っている
    assert result.special_items_unverified is True
    assert result.needs_primary_check is True
    assert any("特別損益チェック未実施" in f for f in result.flags)


def test_screen_does_not_flag_when_special_items_confirmed_absent():
    """陰性の確認（原本を見た結果、特別損益が無かった）は未確認扱いにしない。"""
    result = valuation.screen(
        code="9999",
        name="テスト",
        ticker="9999.T",
        market="東証P",
        cost_of_equity_pct=8.0,
        pbr=0.9,
        roe=valuation.RoeInput(actual_pct=10.0, special_items_checked=True),
    )
    assert result.passed is True
    assert result.special_items_unverified is False
    assert result.needs_primary_check is False
    assert not any("特別損益チェック未実施" in f for f in result.flags)


def test_screen_with_normalized_roe_is_never_unverified():
    """正常化ROEがある＝すでに原本を見ているので、未確認フラグは立たない。"""
    result = valuation.screen(
        code="5302",
        name="日本カーボン",
        ticker="5302.T",
        market="東証P",
        cost_of_equity_pct=8.0,
        pbr=0.99,
        roe=valuation.RoeInput(
            actual_pct=9.08, normalized_pct=5.55, caution="投資有価証券売却益"
        ),
    )
    assert result.special_items_unverified is False
    assert result.quality_floor_passed is False  # 正常化5.55%でフロア割れ
    assert result.passed is False


def test_roe_from_entry_reads_special_items_checked_flag():
    entry = {"verified_fundamentals": {"roe_pct": 12.0, "special_items_checked": True}}
    assert valuation.roe_from_entry(entry).special_items_checked is True
    assert valuation.roe_from_entry({"verified_fundamentals": {"roe_pct": 12.0}}).special_items_checked is False
    # normalized_roe_pct があれば当然確認済み
    assert valuation.roe_from_entry({"normalized_roe_pct": 8.0}).special_items_checked is True


# --------------------------------------------------------------------------
# 実効税率の前年比較（2026-08-21 追加。引き継ぎ書§3パターン2＝フィックスターズ型）
# --------------------------------------------------------------------------


def test_tax_rate_drop_is_flagged_as_inflating_roe():
    # フィックスターズ(3687): 25/9期3Q 19.9% → 26/9期3Q 31.3%。
    # 「前期のROEが税で嵩上げされていた」形なので、前期側から見ると当期比-11.4pt。
    check = valuation.TaxRateCheck(current_pct=19.9, previous_pct=31.3)
    assert check.anomalous
    assert check.delta_pt == pytest.approx(-11.4, abs=0.01)
    assert check.conservative_pct == 31.3  # 保守側＝高いほうの税率


def test_normal_tax_rate_year_is_not_flagged():
    check = valuation.TaxRateCheck(current_pct=31.3, previous_pct=29.8)
    assert not check.anomalous


def test_tax_check_without_two_periods_says_so_instead_of_guessing():
    check = valuation.TaxRateCheck(current_pct=30.0, previous_pct=None)
    assert check.delta_pt is None
    assert not check.anomalous
    assert "前期比較ができない" in check.describe()


def test_effective_tax_rate_refuses_a_loss_year():
    # 税前が0以下の期は率の意味が壊れる。埋めずに None を返すこと（§8）。
    assert valuation.effective_tax_rate_pct(-100, 30) is None
    assert valuation.effective_tax_rate_pct(0, 30) is None
    assert valuation.effective_tax_rate_pct(1000, 300) == pytest.approx(30.0)


def test_roe_at_tax_rate_removes_the_tax_benefit():
    # 税前1,000・自己資本5,000。実効税率20%ならROE16%、正常な30%なら14%。
    assert valuation.roe_at_tax_rate(
        pretax_income=1000, equity=5000, tax_rate_pct=20
    ) == pytest.approx(16.0)
    assert valuation.roe_at_tax_rate(
        pretax_income=1000, equity=5000, tax_rate_pct=30
    ) == pytest.approx(14.0)


def test_roe_at_tax_rate_handles_special_items_in_both_directions():
    # 特別利益200を除き、かつ税率30%で引き直す＝(1000-200)*0.7/5000
    assert valuation.roe_at_tax_rate(
        pretax_income=1000, equity=5000, tax_rate_pct=30, special_gains=200
    ) == pytest.approx(11.2)
    # 押し下げ側（本社移転費用のような特別損失）は戻すと上がる
    assert valuation.roe_at_tax_rate(
        pretax_income=1000, equity=5000, tax_rate_pct=30, special_losses=200
    ) == pytest.approx(16.8)

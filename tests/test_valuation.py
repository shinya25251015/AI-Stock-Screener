"""安さ足切りロジックのテスト。ネットワーク不要。

実在の銘柄の実測値を使い、Future100 側の記録と同じ数字が出ることを確認する。
数字の出典は各テストの docstring に書いてある（§8）。
"""

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

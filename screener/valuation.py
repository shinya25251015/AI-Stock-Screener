"""安さ足切り（発見済み比）と品質フロアの判定。

    妥当PBR       = ROE ÷ 株主資本コスト        （残余利益モデル）
    発見済み比     = 実PBR ÷ 妥当PBR
      比 < 1.0        → 発火前
      1.0 ≤ 比 < 1.5  → 中間帯
      1.5 ≤ 比        → 発見済み

規律（Future100 docs/2035_Future_監視銘柄_引き継ぎ_2026-08-12.md §1）:

* **比は必ず実績ROEで計算する。** 予想ROEで妥当PBRを膨らませると発見済みを
  取り逃がす（東光高岳・ベイカレントで2回同じ誤りが起きた）。予想ROEは
  `forecast_roe_pct` として渡し、**検算にのみ**使う。
* **一過性・循環でROEが歪む銘柄は正常化ROEで計算する。** 歪みは両方向に効く:
  - 割高に見せる例＝品川リフラ（資産売却益込み実績26.6% → 正常化8%で比0.49→0.89）
  - 割安に見せる例＝日東紡（売却益込み実績27.54% → 正常化11.4%で比0.80→2.18）
* **§0**: 株価変動そのもの・テクニカル指標は合否の根拠にしない。この module は
  テクニカルを一切扱わない。急騰・急落は「安さの再計算」の引き金にすぎない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 発見済みの閾値（実PBR ÷ 妥当PBR）。Future100 PBR_FAIR_VALUE_RATIO_THRESHOLD と対。
DISCOVERED_RATIO_THRESHOLD = 1.5
#: 発火前の上限。これ未満なら「まだ値段がついていない」側。
PRE_IGNITION_RATIO_MAX = 1.0
#: 品質フロア。実績ROEがこれ未満なら資本コスト割れ＝価値破壊。
QUALITY_FLOOR_ROE_PCT = 6.0
#: 会社予想ROEで引き直した比が実績比のこの倍率以上に悪化したら「山」フラグを立てる。
PEAK_RISK_RATIO_MARGIN = 1.2
#: 実効税率の既定値。特別損益を除いた正常化ROEを概算するときの税率
#: （原本の「法人税等合計 ÷ 税金等調整前当期純利益」が取れるならそちらを渡すこと）。
DEFAULT_EFFECTIVE_TAX_RATE = 0.30
#: 主軸サイズ帯（円）。ハード足切りではないが、外れると別枠級＝バガー余地が小さい。
SIZE_BAND_YEN = (10_000_000_000, 30_000_000_000)  # 100億〜300億

VERDICT_PRE_IGNITION = "発火前"
VERDICT_MIDDLE = "中間帯"
VERDICT_DISCOVERED = "発見済み"


def fair_pbr(roe_pct: float, cost_of_equity_pct: float) -> float:
    """妥当PBR＝ROE ÷ 株主資本コスト。どちらも％で渡す。"""
    if cost_of_equity_pct <= 0:
        raise ValueError("株主資本コストは正の値でなければならない")
    return roe_pct / cost_of_equity_pct


def discovered_ratio(pbr: float, roe_pct: float, cost_of_equity_pct: float) -> float:
    """発見済み比＝実PBR ÷ 妥当PBR。"""
    fair = fair_pbr(roe_pct, cost_of_equity_pct)
    if fair <= 0:
        raise ValueError("ROEが0以下では妥当PBRを定義できない（品質フロアで先に落とすこと）")
    return pbr / fair


def verdict_for_ratio(ratio: float) -> str:
    if ratio >= DISCOVERED_RATIO_THRESHOLD:
        return VERDICT_DISCOVERED
    if ratio < PRE_IGNITION_RATIO_MAX:
        return VERDICT_PRE_IGNITION
    return VERDICT_MIDDLE


def size_band_label(market_cap_yen: float | None) -> str:
    """時価総額（円換算）を主軸サイズ帯と比べたラベル。"""
    if market_cap_yen is None:
        return "時価総額不明"
    lo, hi = SIZE_BAND_YEN
    oku = market_cap_yen / 100_000_000
    if market_cap_yen < lo:
        return f"{oku:,.0f}億円（帯下・超小型）"
    if market_cap_yen <= hi:
        return f"{oku:,.0f}億円（主軸サイズ帯）"
    if market_cap_yen <= hi * 3:
        return f"{oku:,.0f}億円（帯外・やや大きい）"
    return f"{oku:,.0f}億円（帯外＝別枠級）"


@dataclass
class RoeInput:
    """B-4判定に使うROEと、その素性。

    Attributes:
        actual_pct: 実績ROE（％）。**比の計算はこれが原則**。
        normalized_pct: 一過性・循環を除いた正常化ROE（％）。指定されると
            こちらが比の計算に使われる（品川リフラ／日東紡の型）。
        forecast_pct: 会社予想ROE（％）。**比の計算には使わない**。
            ピーク益（"山"）の検算専用。
        caution: 正常化が必要な理由（一過性利益の内容など）。
        basis: 正常化ROEの算出根拠。
        special_items_checked: **直近2期の特別損益を原本で確認したか**。
            `normalized_pct` を出すには当然これが済んでいるが、
            「確認した結果、特別損益が無かった＝実績ROEをそのまま使ってよい」
            という**陰性の確認**も記録できるようにするためのフラグ。
            False のままだと `screen()` が「未確認」フラグを立てる（下記）。
    """

    actual_pct: float | None = None
    normalized_pct: float | None = None
    forecast_pct: float | None = None
    caution: str = ""
    basis: str = ""
    special_items_checked: bool = False

    def effective_pct(self) -> float | None:
        """比の計算に実際に使うROE。正常化値があればそれを優先する。"""
        if self.normalized_pct is not None:
            return self.normalized_pct
        return self.actual_pct

    def effective_source(self) -> str:
        if self.normalized_pct is not None:
            return "正常化ROE"
        return "実績ROE"


def normalized_roe_from_special_items(
    *,
    pretax_income: float,
    special_gains: float,
    special_losses: float,
    equity: float,
    tax_total: float | None = None,
    minority_interest: float = 0.0,
    effective_tax_rate: float | None = None,
) -> float:
    """特別損益を除いた**正常化ROE（％）**を、決算短信原本の数値から算出する。

    実績ROEが一過性の特別利益で嵩上げされている例が繰り返し出ているため、
    その補正手順を関数に固定した。**確認済み4例**:

    ==================  ==========  ============  ==========================================
    銘柄                 実績ROE     正常化ROE      一過性の中身（原本）
    ==================  ==========  ============  ==========================================
    品川リフラ(5351)      26.6%       8%            資産売却益（割"高"に見せていた側の訂正）
    日東紡(3110)         27.54%      11.28%        固定資産売却益
    日本カーボン(5302)    9.08%       5.55%         投資有価証券売却益3,530百万円
    大同信号(6743)       6.87%       5.93%         投資有価証券売却益379,498千円（2期連続）
    ==================  ==========  ============  ==========================================

    日本カーボン・大同信号は、この補正を入れて初めて**品質フロア割れ**が見える。
    どちらも補正前は「発火前・フロア通過」に見えていた。

    引数はすべて決算短信の連結損益計算書・貸借対照表の実額（単位は揃っていれば何でもよい）:

    Args:
        pretax_income: 税金等調整前当期純利益。
        special_gains: 特別利益合計。
        special_losses: 特別損失合計。
        equity: 自己資本（純資産から非支配株主持分を除いた額）。
            期首期末の平均が取れるならそちらが望ましい。
        tax_total: 法人税等合計。渡すと実効税率を
            ``tax_total / pretax_income`` で原本から算出する（推奨）。
        minority_interest: 非支配株主に帰属する当期純利益。連結でのみ必要。
        effective_tax_rate: 実効税率を直接指定する場合（0〜1）。
            ``tax_total`` が渡されていればそちらが優先される。

    Returns:
        正常化ROE（％）。

    Raises:
        ValueError: 自己資本が0以下のとき。
    """
    if equity <= 0:
        raise ValueError("自己資本が0以下では正常化ROEを定義できない")

    if tax_total is not None and pretax_income:
        rate = tax_total / pretax_income
    elif effective_tax_rate is not None:
        rate = effective_tax_rate
    else:
        rate = DEFAULT_EFFECTIVE_TAX_RATE
    # 実効税率が異常値（税効果の戻し等で負・過大）になる期があるため上下を切る。
    rate = min(max(rate, 0.0), 0.6)

    normalized_pretax = pretax_income - (special_gains - special_losses)
    normalized_net = normalized_pretax * (1 - rate) - minority_interest
    return normalized_net / equity * 100


@dataclass
class ScreenResult:
    """1銘柄の安さ足切り結果。"""

    code: str
    name: str
    ticker: str
    market: str
    cost_of_equity_pct: float
    pbr: float | None = None
    roe: RoeInput = field(default_factory=RoeInput)
    market_cap_yen: float | None = None
    fair_pbr: float | None = None
    ratio: float | None = None
    verdict: str = ""
    forecast_ratio: float | None = None
    forecast_verdict: str = ""
    quality_floor_passed: bool | None = None
    size_label: str = ""
    flags: list[str] = field(default_factory=list)
    error: str = ""
    special_items_unverified: bool = False

    @property
    def passed(self) -> bool:
        """安さ足切り＋品質フロアの通過可否。

        「発見済み（比1.5以上）」または「品質フロア割れ」で不通過。中間帯は通過扱い
        （観察候補として残す）だが、発火前の安さは無い旨が verdict に出る。

        **`special_items_unverified` は passed を落とさない**——落とすと
        「未確認」と「本当に不合格」が区別できなくなるため。通過したうえで
        `needs_primary_check` が立つ、という二段構えにしている。
        """
        if self.error or self.ratio is None or self.quality_floor_passed is None:
            return False
        return self.quality_floor_passed and self.verdict != VERDICT_DISCOVERED

    @property
    def needs_primary_check(self) -> bool:
        """**①の原本確認に進む前に、実績ROEの裏取りが必要か。**

        安さ足切りを通ったのに特別損益の確認が済んでいない銘柄は、
        「発火前・フロア通過」に見えていても正常化で覆る可能性がある。
        大同信号(6743)は**①の原本確認を終えてから**フロア割れが判明した——
        この順序だと重い作業が無駄になるので、先にこちらを潰す。
        """
        return self.passed and self.special_items_unverified


def screen(
    *,
    code: str,
    name: str,
    ticker: str,
    market: str,
    cost_of_equity_pct: float,
    pbr: float | None,
    roe: RoeInput,
    market_cap_yen: float | None = None,
) -> ScreenResult:
    """安さ足切り（B-4）＋品質フロア＋サイズを一度に判定する。

    取得失敗（pbr / roe が None）は例外にせず ``error`` に格納する。
    Future100 の fetch_metrics() と同じ "never raises" の契約を踏襲し、
    1銘柄の欠損でスクリーニング全体を止めない。
    """
    result = ScreenResult(
        code=code,
        name=name,
        ticker=ticker,
        market=market,
        cost_of_equity_pct=cost_of_equity_pct,
        pbr=pbr,
        roe=roe,
        market_cap_yen=market_cap_yen,
        size_label=size_band_label(market_cap_yen),
    )

    eff_roe = roe.effective_pct()
    if pbr is None or eff_roe is None:
        missing = []
        if pbr is None:
            missing.append("PBR")
        if eff_roe is None:
            missing.append("ROE")
        result.error = f"判定不能（{'・'.join(missing)}を取得できず）"
        result.flags.append("要確認: 取得失敗が続く場合は上場状態と取引所サフィックスを確認する")
        return result

    # 品質フロアは「実績ROE」で見る。正常化ROEがある場合は正常化後で見る
    # （一過性で嵩上げされた実績で通してしまわないため）。
    result.quality_floor_passed = eff_roe >= QUALITY_FLOOR_ROE_PCT
    if not result.quality_floor_passed:
        result.flags.append(
            f"品質フロア割れ（{roe.effective_source()} {eff_roe:.2f}% < {QUALITY_FLOOR_ROE_PCT:.0f}%）"
        )

    if eff_roe <= 0:
        result.error = f"ROE {eff_roe:.2f}% では妥当PBRを定義できない（品質フロア割れで却下）"
        return result

    result.fair_pbr = fair_pbr(eff_roe, cost_of_equity_pct)
    result.ratio = discovered_ratio(pbr, eff_roe, cost_of_equity_pct)
    result.verdict = verdict_for_ratio(result.ratio)

    if roe.normalized_pct is not None:
        result.flags.append(f"正常化ROEで判定（{roe.caution or '一過性・循環の補正'}）")
    elif not roe.special_items_checked:
        # 実績ROEをそのまま使っているのに、それが特別損益で嵩上げされていないかを
        # 誰も確認していない状態。**黙って通さない**——これを黙って通した結果が
        # 日本カーボン(5302)と大同信号(6743)で、どちらも補正すると品質フロア割れだった。
        # 「想定内注記で覆い隠さない」のと同じ理由で、未確認は未確認として出す。
        result.special_items_unverified = True
        result.flags.append(
            "実績ROEの特別損益チェック未実施——直近2期の特別利益を原本で確認すること"
            "（確認済み4例すべてで正常化ROEが下振れ。うち2例はフロア割れ）"
        )

    # 会社予想ROEでの検算＝ピーク益（"山"）の検出。合否には使わない。
    if roe.forecast_pct is not None and roe.forecast_pct > 0:
        result.forecast_ratio = discovered_ratio(pbr, roe.forecast_pct, cost_of_equity_pct)
        result.forecast_verdict = verdict_for_ratio(result.forecast_ratio)
        # 判定区分が変わる場合だけでなく、比が2割以上悪化する場合も「山」とみなす。
        # 東亜建設(比0.61→0.97)のように区分は同じでも安全余裕が消える例があるため。
        worsens = result.forecast_ratio >= result.ratio * PEAK_RISK_RATIO_MARGIN
        if result.forecast_verdict != result.verdict or worsens:
            result.flags.append(
                f"山リスク: 会社予想ROE {roe.forecast_pct:.2f}% で引き直すと"
                f" 比{result.forecast_ratio:.2f}＝{result.forecast_verdict}"
            )

    if result.verdict == VERDICT_DISCOVERED:
        result.flags.append(f"発見済み（比{result.ratio:.2f} ≧ {DISCOVERED_RATIO_THRESHOLD}）")

    return result


def roe_from_entry(entry: dict[str, Any], fetched_roe_pct: float | None = None) -> RoeInput:
    """watchlist.yaml のエントリ（＋取得値）から RoeInput を組み立てる。

    優先順位は Future100 の effective_pbr_roe() に合わせる:
        verified_fundamentals.roe_pct（一次/準一次で確認済み） > 取得値
    normalized_roe_pct / roe_caution があれば正常化ROEとして載せる。
    """
    verified = entry.get("verified_fundamentals") or {}
    actual = verified.get("roe_pct")
    if actual is None:
        actual = fetched_roe_pct
    # `special_items_checked: true` を verified_fundamentals に書けば、
    # 「原本を見た結果、特別損益は無かった（＝実績ROEをそのまま使ってよい）」という
    # **陰性の確認**を記録できる。normalized_roe_pct がある銘柄は当然確認済み扱い。
    checked = bool(verified.get("special_items_checked")) or (
        entry.get("normalized_roe_pct") is not None
    )
    return RoeInput(
        actual_pct=float(actual) if actual is not None else None,
        normalized_pct=(
            float(entry["normalized_roe_pct"]) if entry.get("normalized_roe_pct") is not None else None
        ),
        caution=str(entry.get("roe_caution") or "").strip(),
        basis=str(entry.get("normalized_roe_basis") or "").strip(),
        special_items_checked=checked,
    )


def effective_pbr(entry: dict[str, Any], price: float | None, fetched_pbr: float | None) -> float | None:
    """verified_fundamentals.bvps_yen があれば PBR を「その日の株価 ÷ BVPS」で再計算する。

    Future100 の effective_pbr_roe() と同じ契約。自動取得のPBRは銘柄によって
    実態と大幅に乖離することがあるため（神島化学・助川電気の実例）。
    """
    verified = entry.get("verified_fundamentals") or {}
    bvps = verified.get("bvps_yen")
    if bvps and price:
        try:
            bvps_f = float(bvps)
            if bvps_f > 0:
                return float(price) / bvps_f
        except (TypeError, ValueError):
            pass
    return fetched_pbr

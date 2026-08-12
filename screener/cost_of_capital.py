"""市場ごとの株主資本コスト（妥当PBRの分母）を解決する。

妥当PBR = ROE ÷ 株主資本コスト。日本株は8%固定だが、海外株は
「現地10年国債利回り ＋ ERP5〜6%」で計算し直さなければならない
（Future100 docs/discovery_mission.md §1-1）。

§8（一次情報主義）の実装上の要請:
    国債利回りは時間とともに変わるので、モデルの記憶で埋めてはいけない。
    未検証（verified: false）の市場を指定した場合、この module は
    UnverifiedMarketError を送出して**計算を止める**。黙って古い値や
    推測値で妥当PBRを出すことはしない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "cost_of_capital.yaml"

#: 日本株の株主資本コスト。Future100 scripts/market_data.py の REQUIRED_RETURN=0.08 と対。
JP_COST_OF_EQUITY_PCT = 8.0


class UnverifiedMarketError(Exception):
    """未検証の市場で妥当PBRを計算しようとしたときに送出する。

    「使う日にWeb検索で当日の10年国債利回りを確認し、config/cost_of_capital.yaml を
    埋めてから使う」ことを強制するための例外。握りつぶさないこと。
    """


class UnknownMarketError(Exception):
    """config/cost_of_capital.yaml に定義の無い市場を指定した。"""


@dataclass(frozen=True)
class CostOfEquity:
    """解決済みの株主資本コストと、その根拠。"""

    market: str
    pct: float
    basis: str
    asof: str
    source: str
    currency: str

    def describe(self) -> str:
        parts = [f"{self.market} {self.pct:.2f}%"]
        if self.basis:
            parts.append(self.basis)
        if self.asof:
            parts.append(f"asof={self.asof}")
        return " / ".join(parts)


def load_markets(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("markets") or {}


def resolve(
    market: str = "JP",
    config_path: str | os.PathLike[str] | None = None,
    override_pct: float | None = None,
) -> CostOfEquity:
    """市場コードから株主資本コストを解決する。

    Args:
        market: "JP" / "US" / "EU" など config/cost_of_capital.yaml のキー。
        config_path: 設定ファイルのパス（省略時はリポジトリ同梱の config/）。
        override_pct: 明示的に上書きする％値。感応度分析（正常化ROEの当てはめ等）で
            一時的に別の資本コストを試すときに使う。指定するとYAMLの検証を迂回するため、
            **記録に残す判断には使わない**こと。

    Raises:
        UnknownMarketError: 未定義の市場。
        UnverifiedMarketError: verified: false のまま利回りが埋まっていない市場。
    """
    markets = load_markets(config_path)
    key = market.upper()
    if key not in markets:
        raise UnknownMarketError(
            f"市場 '{market}' は config/cost_of_capital.yaml に定義されていない。"
            f" 定義済み: {sorted(markets)}"
        )
    entry = markets[key] or {}

    if override_pct is not None:
        return CostOfEquity(
            market=key,
            pct=float(override_pct),
            basis=f"呼び出し側による明示的な上書き（{override_pct}%）",
            asof="",
            source="override_pct",
            currency=str(entry.get("currency") or ""),
        )

    explicit = entry.get("cost_of_equity_pct")
    risk_free = entry.get("risk_free_pct")
    erp = entry.get("erp_pct")

    if entry.get("verified") and explicit is not None:
        pct = float(explicit)
    elif entry.get("verified") and risk_free is not None and erp is not None:
        pct = float(risk_free) + float(erp)
    else:
        raise UnverifiedMarketError(
            f"市場 '{key}' の株主資本コストは未検証。"
            " 当日の10年国債利回りをWeb検索で確認し、config/cost_of_capital.yaml の"
            " risk_free_pct / erp_pct / asof / source を埋めて verified: true にすること（§8）。"
        )

    basis = str(entry.get("basis") or "")
    if not basis and risk_free is not None and erp is not None:
        basis = f"現地10年国債{float(risk_free):.2f}% ＋ ERP{float(erp):.2f}%"

    return CostOfEquity(
        market=key,
        pct=pct,
        basis=basis,
        asof=str(entry.get("asof") or ""),
        source=str(entry.get("source") or ""),
        currency=str(entry.get("currency") or ""),
    )


def market_for_ticker(ticker: str) -> str:
    """ティッカーのサフィックスから市場コードを推定する。

    判定できないサフィックスは "JP" にフォールバックせず ValueError にする。
    誤って日本株の8%を海外株に当ててしまうのを防ぐため（§8）。
    """
    t = ticker.strip().upper()
    suffix = t.rsplit(".", 1)[-1] if "." in t else ""
    mapping = {
        "T": "JP",   # 東証
        "N": "JP",   # 名証（例: 愛知電機 6623.N）
        "S": "JP",   # 札証
        "F": "JP",   # 福証
        "TW": "TW",
        "KS": "KR",
        "KQ": "KR",
    }
    if suffix in mapping:
        return mapping[suffix]
    if suffix == "":
        # サフィックス無し＝米国上場が慣例だが、断定はしない。
        return "US"
    raise ValueError(
        f"ティッカー '{ticker}' のサフィックス '{suffix}' から市場を判定できない。"
        " 呼び出し側で market を明示すること。"
    )

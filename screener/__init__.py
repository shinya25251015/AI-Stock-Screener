"""2035 Future 発掘・監視エンジン。

Future100 プロジェクトの「銘柄発見担当」が使う、安さ足切り（発見済み比）を中心とした
スクリーニング基盤。詳細は README.md / CLAUDE.md を参照。
"""

from .cost_of_capital import CostOfEquity, UnverifiedMarketError, resolve
from .valuation import (
    DISCOVERED_RATIO_THRESHOLD,
    QUALITY_FLOOR_ROE_PCT,
    RoeInput,
    ScreenResult,
    discovered_ratio,
    fair_pbr,
    screen,
    verdict_for_ratio,
)

__all__ = [
    "CostOfEquity",
    "UnverifiedMarketError",
    "resolve",
    "DISCOVERED_RATIO_THRESHOLD",
    "QUALITY_FLOOR_ROE_PCT",
    "RoeInput",
    "ScreenResult",
    "discovered_ratio",
    "fair_pbr",
    "screen",
    "verdict_for_ratio",
]

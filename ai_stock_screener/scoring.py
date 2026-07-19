"""Quantitative multi-factor scoring.

Each stock gets three factor scores in [0, 1] (percentile-based within the
screened universe) and a weighted composite:

- value:    低PER・低PBR・高配当利回り
- quality:  高ROE・高利益率
- momentum: 3ヶ月・6ヶ月リターン

Missing metrics contribute a neutral 0.5 so stocks with sparse data are
neither rewarded nor punished.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data import StockMetrics

WEIGHTS = {"value": 0.4, "quality": 0.35, "momentum": 0.25}
NEUTRAL = 0.5


@dataclass
class ScoredStock:
    metrics: StockMetrics
    value: float
    quality: float
    momentum: float
    composite: float


def percentile_ranks(values: list[float | None], higher_is_better: bool = True) -> list[float]:
    """Rank values into [0, 1]; None gets the neutral 0.5.

    The best value maps to 1.0 and the worst to 0.0. With a single non-None
    value, that value gets 0.5 (no information about relative standing).
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    ranks = [NEUTRAL] * len(values)
    n = len(present)
    if n < 2:
        return ranks
    ordered = sorted(present, key=lambda iv: iv[1], reverse=higher_is_better)
    for rank, (i, _) in enumerate(ordered):
        ranks[i] = 1.0 - rank / (n - 1)
    return ranks


def _mean(parts: list[float]) -> float:
    return sum(parts) / len(parts)


def score_stocks(stocks: list[StockMetrics]) -> list[ScoredStock]:
    """Score and rank stocks, best composite first."""
    per = percentile_ranks([s.per for s in stocks], higher_is_better=False)
    pbr = percentile_ranks([s.pbr for s in stocks], higher_is_better=False)
    dy = percentile_ranks([s.dividend_yield for s in stocks])
    roe = percentile_ranks([s.roe for s in stocks])
    margin = percentile_ranks([s.profit_margin for s in stocks])
    r3 = percentile_ranks([s.return_3m for s in stocks])
    r6 = percentile_ranks([s.return_6m for s in stocks])

    scored = []
    for i, s in enumerate(stocks):
        value = _mean([per[i], pbr[i], dy[i]])
        quality = _mean([roe[i], margin[i]])
        momentum = _mean([r3[i], r6[i]])
        composite = (
            WEIGHTS["value"] * value
            + WEIGHTS["quality"] * quality
            + WEIGHTS["momentum"] * momentum
        )
        scored.append(ScoredStock(s, value, quality, momentum, composite))
    scored.sort(key=lambda x: x.composite, reverse=True)
    return scored

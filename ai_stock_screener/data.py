"""Fetching and loading of per-stock fundamental / price metrics."""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, fields
from pathlib import Path

from .universe import DEFAULT_UNIVERSE, UniverseEntry

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample_stocks.csv"


@dataclass
class StockMetrics:
    code: str
    name: str
    sector: str
    price: float | None = None          # 株価(円)
    market_cap: float | None = None     # 時価総額(円)
    per: float | None = None            # 株価収益率(実績)
    pbr: float | None = None            # 株価純資産倍率
    dividend_yield: float | None = None # 配当利回り(小数, 0.03 = 3%)
    roe: float | None = None            # 自己資本利益率(小数)
    profit_margin: float | None = None  # 純利益率(小数)
    return_3m: float | None = None      # 3ヶ月リターン(小数)
    return_6m: float | None = None      # 6ヶ月リターン(小数)


_FLOAT_FIELDS = [f.name for f in fields(StockMetrics) if f.name not in ("code", "name", "sector")]


def load_csv(path: Path | str = SAMPLE_CSV) -> list[StockMetrics]:
    """Load stock metrics from a CSV file (columns match StockMetrics fields)."""
    stocks: list[StockMetrics] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kwargs: dict = {
                "code": row["code"],
                "name": row["name"],
                "sector": row.get("sector", ""),
            }
            for name in _FLOAT_FIELDS:
                raw = row.get(name, "")
                kwargs[name] = float(raw) if raw not in ("", None) else None
            stocks.append(StockMetrics(**kwargs))
    return stocks


def fetch_yfinance(universe: list[UniverseEntry] | None = None) -> list[StockMetrics]:
    """Fetch live metrics for the universe from Yahoo Finance.

    Requires network access to finance.yahoo.com. Tickers that fail to load
    are skipped with a warning on stderr.
    """
    import yfinance as yf

    universe = universe or DEFAULT_UNIVERSE
    stocks: list[StockMetrics] = []
    for entry in universe:
        try:
            ticker = yf.Ticker(entry.yahoo_symbol)
            info = ticker.info
            hist = ticker.history(period="6mo")["Close"]
            price = float(hist.iloc[-1]) if len(hist) else None
            ret_3m = _trailing_return(hist, 63)
            ret_6m = _trailing_return(hist, 126)
            stocks.append(
                StockMetrics(
                    code=entry.code,
                    name=entry.name,
                    sector=entry.sector,
                    price=price,
                    market_cap=info.get("marketCap"),
                    per=info.get("trailingPE"),
                    pbr=info.get("priceToBook"),
                    dividend_yield=info.get("dividendYield"),
                    roe=info.get("returnOnEquity"),
                    profit_margin=info.get("profitMargins"),
                    return_3m=ret_3m,
                    return_6m=ret_6m,
                )
            )
        except Exception as e:  # noqa: BLE001 - per-ticker failures shouldn't kill the run
            print(f"warning: {entry.code} {entry.name} の取得に失敗: {e}", file=sys.stderr)
    return stocks


def _trailing_return(closes, trading_days: int) -> float | None:
    if len(closes) <= trading_days:
        return None
    past = float(closes.iloc[-1 - trading_days])
    if past == 0:
        return None
    return float(closes.iloc[-1]) / past - 1.0

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-Stock-Screener is an AI-powered Japanese stock screener. It screens major Tokyo Stock Exchange stocks with a quantitative multi-factor score (value / quality / momentum), then asks Claude (Anthropic API) to select stocks from the top candidates, with Japanese-language output.

## Commands

- Install: `pip install -r requirements-dev.txt` (runtime only: `requirements.txt`)
- Run: `python -m ai_stock_screener` (live data + AI) / `python -m ai_stock_screener --source sample --no-ai` (offline, no API key)
- Tests: `python -m pytest tests/`
- Single test: `python -m pytest tests/test_scoring.py::TestScoreStocks::test_missing_data_is_neutral`

There is no linter or build step configured.

## Architecture

Pipeline: universe → data fetch → quantitative scoring → AI selection, wired together in `cli.py`.

- `ai_stock_screener/universe.py` — hardcoded default universe of ~30 major TSE stocks (4-digit codes; Yahoo symbols are `<code>.T`)
- `ai_stock_screener/data.py` — `StockMetrics` dataclass plus two sources: `fetch_yfinance()` (live) and `load_csv()` (defaults to `data/sample_stocks.csv` for offline/demo use)
- `ai_stock_screener/scoring.py` — pure functions; percentile-ranks each metric within the universe (missing values get neutral 0.5) and combines into a weighted composite (value 40% / quality 35% / momentum 25%)
- `ai_stock_screener/ai.py` — Claude call (`claude-opus-4-8`, streaming, adaptive thinking); returns `None` on missing credentials or network failure so the CLI can degrade to the quantitative ranking alone
- `tests/test_scoring.py` — covers only the pure scoring logic; no network or API mocking

## Conventions

- User-facing CLI output, prompts, and warnings are in Japanese; code identifiers, comments, and docstrings are in English (dataclass field comments note the Japanese metric names).
- Dividend yield, ROE, margins, and returns are stored as decimals (0.03 = 3%), not percentages.
- Both external dependencies (Yahoo Finance, Anthropic API) must fail soft: per-ticker fetch failures warn and skip; AI unavailability falls back to `--no-ai` behavior. Preserve this when modifying `data.py` / `ai.py`.
- AI output must always end with the investment disclaimer (see `SYSTEM_PROMPT` in `ai.py`); the CLI prints it in README too.

## Environment Notes

- In the Claude Code remote environment, finance.yahoo.com is blocked by the network policy — use `--source sample` there. yfinance works in normal local environments.
- The AI step needs `ANTHROPIC_API_KEY` (or an `ant auth login` profile). Without credentials it prints a warning and skips.

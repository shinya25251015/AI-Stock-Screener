"""Command-line interface."""

from __future__ import annotations

import argparse
import sys

from . import ai, data, scoring


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-stock-screener",
        description="AIによる日本株スクリーニング・銘柄選定ツール",
    )
    p.add_argument(
        "--source",
        choices=["yfinance", "sample"],
        default="yfinance",
        help="データソース(yfinance: Yahoo Financeから取得 / sample: 同梱サンプルデータ)",
    )
    p.add_argument("--csv", help="任意のCSVファイルから読み込む(--sourceより優先)")
    p.add_argument("--top", type=int, default=15, help="AIに渡す上位候補数(default: 15)")
    p.add_argument("--picks", type=int, default=5, help="AIが選定する銘柄数(default: 5)")
    p.add_argument("--no-ai", action="store_true", help="AI分析を行わず定量ランキングのみ表示")
    p.add_argument("--model", default=ai.DEFAULT_MODEL, help=f"使用するClaudeモデル(default: {ai.DEFAULT_MODEL})")
    return p


def print_ranking(scored: list[scoring.ScoredStock]) -> None:
    print(f"{'順位':>3} {'コード':>5} {'銘柄名':<18} {'総合':>6} {'バリュー':>6} {'クオリティ':>6} {'モメンタム':>6}")
    for i, s in enumerate(scored, 1):
        print(
            f"{i:>4} {s.metrics.code:>6} {s.metrics.name:<20} "
            f"{s.composite:>7.3f} {s.value:>8.3f} {s.quality:>9.3f} {s.momentum:>9.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.csv:
        stocks = data.load_csv(args.csv)
    elif args.source == "sample":
        stocks = data.load_csv()
    else:
        try:
            stocks = data.fetch_yfinance()
        except Exception as e:  # noqa: BLE001
            print(f"error: Yahoo Financeからの取得に失敗しました({e})", file=sys.stderr)
            print("ネットワークが使えない場合は --source sample をお試しください。", file=sys.stderr)
            return 1

    if not stocks:
        print("error: 銘柄データがありません", file=sys.stderr)
        return 1

    scored = scoring.score_stocks(stocks)
    candidates = scored[: args.top]

    print(f"=== 定量スクリーニング結果(上位{len(candidates)}銘柄)===")
    print_ranking(candidates)

    if not args.no_ai:
        print(f"\n=== AI銘柄選定({args.picks}銘柄)===")
        result = ai.select_stocks(candidates, picks=args.picks, model=args.model)
        if result is None:
            print("(AI分析は利用できませんでした。上の定量ランキングをご参照ください。)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

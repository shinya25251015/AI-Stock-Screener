"""コマンドラインから安さ足切りを回す。

    # 未検証リードを実データで足切り（実績ROEで比を計算する）
    python -m screener.cli screen 3769.T 1414.T 3762.T --market JP

    # Future100 の watchlist を丸ごと洗い替え
    python -m screener.cli watchlist --refresh

    # 監視・保有と重複していないかだけ確認（ネットワーク不要）
    python -m screener.cli leads

§0 により、テクニカル指標は一切出力しない。合否は「安さ（発見済み比）」と
「品質フロア（実績ROE6%）」のみで決まる。
"""

from __future__ import annotations

import argparse
import json
import sys

from . import candidates as candidates_mod
from . import cost_of_capital, valuation, watchlist, yahoo_jp


def _fmt(value: float | None, digits: int = 2) -> str:
    return "---" if value is None else f"{value:.{digits}f}"


def _print_results(results: list[valuation.ScreenResult], as_json: bool = False) -> None:
    if as_json:
        payload = []
        for r in results:
            payload.append(
                {
                    "code": r.code,
                    "name": r.name,
                    "ticker": r.ticker,
                    "market": r.market,
                    "cost_of_equity_pct": r.cost_of_equity_pct,
                    "pbr": r.pbr,
                    "roe_pct": r.roe.effective_pct(),
                    "roe_source": r.roe.effective_source(),
                    "actual_roe_pct": r.roe.actual_pct,
                    "forecast_roe_pct": r.roe.forecast_pct,
                    "fair_pbr": r.fair_pbr,
                    "ratio": r.ratio,
                    "verdict": r.verdict,
                    "forecast_ratio": r.forecast_ratio,
                    "forecast_verdict": r.forecast_verdict,
                    "market_cap_yen": r.market_cap_yen,
                    "quality_floor_passed": r.quality_floor_passed,
                    "passed": r.passed,
                    "flags": r.flags,
                    "error": r.error,
                }
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    header = (
        f"{'コード':<8}{'銘柄':<22}{'PBR':>7}{'ROE%':>8}{'妥当PBR':>9}"
        f"{'比':>7}  {'判定':<8}{'時価総額':<22}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.code:<8}{r.name[:20]:<22}{_fmt(r.pbr):>7}"
            f"{_fmt(r.roe.effective_pct()):>8}{_fmt(r.fair_pbr):>9}"
            f"{_fmt(r.ratio):>7}  {(r.verdict or '判定不能'):<8}{r.size_label:<22}"
        )
        for flag in r.flags:
            print(f"    ! {flag}")
        if r.error:
            print(f"    x {r.error}")


def _screen_ticker(ticker: str, coe: cost_of_capital.CostOfEquity, entry: dict | None,
                   sleep_sec: float) -> valuation.ScreenResult:
    quote = yahoo_jp.fetch_quote(ticker, sleep_sec=sleep_sec)
    entry = entry or {}
    code = str(entry.get("code") or ticker.split(".")[0])
    name = str(entry.get("name") or quote.name or "")
    if quote.error:
        result = valuation.ScreenResult(
            code=code, name=name, ticker=ticker, market=coe.market,
            cost_of_equity_pct=coe.pct, error=quote.error,
        )
        return result
    roe = valuation.roe_from_entry(entry, fetched_roe_pct=quote.roe_pct)
    if roe.forecast_pct is None:
        roe.forecast_pct = quote.forecast_roe_pct
    pbr = valuation.effective_pbr(entry, quote.price, quote.pbr)
    return valuation.screen(
        code=code,
        name=name,
        ticker=ticker,
        market=coe.market,
        cost_of_equity_pct=coe.pct,
        pbr=pbr,
        roe=roe,
        market_cap_yen=quote.market_cap_yen,
    )


def _print_header(coe: cost_of_capital.CostOfEquity, as_json: bool) -> None:
    # --json のときは stdout をJSONだけに保つ（パイプでそのまま食えるように）。
    stream = sys.stderr if as_json else sys.stdout
    print(f"# 株主資本コスト: {coe.describe()}", file=stream)
    if coe.source:
        print(f"# 出典: {coe.source.strip()}", file=stream)
    print(file=stream)


def cmd_screen(args: argparse.Namespace) -> int:
    coe = cost_of_capital.resolve(args.market, override_pct=args.cost_of_equity)
    _print_header(coe, args.json)
    results = [
        _screen_ticker(t, coe, entry=None, sleep_sec=args.sleep)
        for t in args.tickers
    ]
    _print_results(results, as_json=args.json)
    return 0


def cmd_watchlist(args: argparse.Namespace) -> int:
    wl = watchlist.load(args.path)
    stream = sys.stderr if args.json else sys.stdout
    print(f"# {wl.path}", file=stream)
    print(f"# 監視 {len(wl.entries)} 銘柄 / 未検証リード {len(wl.leads)} 件", file=stream)
    if not args.refresh:
        for entry in wl.entries:
            print(f"{entry.get('code'):<8}{str(entry.get('name'))[:24]:<26}{entry.get('status','')}")
        return 0
    coe = cost_of_capital.resolve(args.market, override_pct=args.cost_of_equity)
    _print_header(coe, args.json)
    results = []
    for entry in wl.entries:
        ticker = str(entry.get("ticker") or f"{entry.get('code')}.T")
        results.append(_screen_ticker(ticker, coe, entry=entry, sleep_sec=args.sleep))
    _print_results(results, as_json=args.json)
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    """候補リスト（社名＋コードの仮説）を検証しつつ安さ足切りにかける。"""
    clist = candidates_mod.load(args.path)
    coe = cost_of_capital.resolve(args.market, override_pct=args.cost_of_equity)
    stream = sys.stderr if args.json else sys.stdout
    print(f"# {clist.title}（{clist.asof}）", file=stream)
    print(f"# 候補 {len(clist.candidates)} 件 / {clist.source_note}".rstrip(), file=stream)
    _print_header(coe, args.json)

    results: list[valuation.ScreenResult] = []
    known = set()
    if args.exclude_known:
        try:
            known = watchlist.known_codes()
        except FileNotFoundError:
            print("# 既存コードの参照に失敗（Future100が見つからない）", file=stream)

    for cand in clist.candidates:
        if cand.code in known:
            print(f"# skip {cand.code} {cand.name}: 既に監視/保有/リードに存在", file=stream)
            continue
        quote = yahoo_jp.fetch_quote(cand.resolved_ticker(), sleep_sec=args.sleep)
        result = valuation.ScreenResult(
            code=cand.code, name=cand.name, ticker=cand.resolved_ticker(),
            market=coe.market, cost_of_equity_pct=coe.pct,
        )
        if quote.error:
            result.error = quote.error
            result.flags.append("要確認: 取得失敗が続く場合は上場状態と取引所を確認する")
            results.append(result)
            continue
        # §8: コードは仮説。取得した社名と一致しなければ「未確認」として扱う。
        if not candidates_mod.names_match(cand.name, quote.name):
            result.error = (
                f"社名不一致（仮説「{cand.name}」/ 取得「{quote.name}」）"
                "＝証券コード未確認。config/へ記録してはいけない"
            )
            results.append(result)
            continue
        roe = valuation.RoeInput(
            actual_pct=quote.roe_pct, forecast_pct=quote.forecast_roe_pct
        )
        screened = valuation.screen(
            code=cand.code, name=quote.name, ticker=cand.resolved_ticker(),
            market=coe.market, cost_of_equity_pct=coe.pct,
            pbr=quote.pbr, roe=roe, market_cap_yen=quote.market_cap_yen,
        )
        results.append(screened)

    _print_results(results, as_json=args.json)
    return 0


def cmd_leads(args: argparse.Namespace) -> int:
    wl = watchlist.load(args.path)
    print(f"# 未検証リード {len(wl.leads)} 件（理由はYAMLコメントから復元）\n")
    last_section = None
    for lead in wl.leads:
        if lead.section != last_section:
            last_section = lead.section
            if last_section:
                print(f"\n[{last_section}]")
        print(f"  {lead.code:<8}{lead.name:<24}{lead.reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="screener", description="2035 Future 発掘・監視エンジン")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--market", default="JP", help="市場コード（既定 JP）")
    common.add_argument(
        "--cost-of-equity", type=float, default=None,
        help="株主資本コスト%%の明示的な上書き（感応度分析用。記録に残す判断には使わない）",
    )
    common.add_argument("--sleep", type=float, default=yahoo_jp.DEFAULT_SLEEP_SEC,
                        help="1銘柄ごとのスリープ秒（レート制限対策）")
    common.add_argument("--json", action="store_true", help="JSONで出力")

    p_screen = sub.add_parser("screen", parents=[common], help="ティッカーを指定して足切り")
    p_screen.add_argument("tickers", nargs="+", help="例: 3769.T 6623.N")
    p_screen.set_defaults(func=cmd_screen)

    p_watch = sub.add_parser("watchlist", parents=[common], help="Future100のwatchlistを読む")
    p_watch.add_argument("--path", default=None, help="watchlist.yaml のパス")
    p_watch.add_argument("--refresh", action="store_true", help="実データを取得して比を洗い替える")
    p_watch.set_defaults(func=cmd_watchlist)

    p_cand = sub.add_parser("candidates", parents=[common],
                            help="候補リストのコードを検証しつつ足切り")
    p_cand.add_argument("path", help="候補リストYAMLのパス")
    p_cand.add_argument("--exclude-known", action="store_true",
                        help="既に監視/保有/リードにあるコードを飛ばす")
    p_cand.set_defaults(func=cmd_candidates)

    p_leads = sub.add_parser("leads", help="未検証リードと理由（YAMLコメント）を表示")
    p_leads.add_argument("--path", default=None, help="watchlist.yaml のパス")
    p_leads.set_defaults(func=cmd_leads)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except cost_of_capital.UnverifiedMarketError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2
    except cost_of_capital.UnknownMarketError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""AI stock selection: ask Claude to pick from the quantitatively screened candidates."""

from __future__ import annotations

import sys

from .scoring import ScoredStock

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
あなたは日本株を専門とする経験豊富な証券アナリストです。
定量スクリーニングを通過した候補銘柄の中から、投資魅力度の高い銘柄を選定してください。

出力は日本語で、以下の構成に従ってください:
1. 選定銘柄(指定された数): 銘柄ごとに「証券コード・銘柄名」「選定理由(バリュエーション・収益性・モメンタムの観点)」「主なリスク」
2. 総評: 候補全体から読み取れる市場環境や選定方針の要約(3〜5文)

注意事項:
- 提示されたデータに基づいて判断し、データにない事実を断定しないこと
- 最後に必ず「本情報は投資助言ではなく、投資判断はご自身の責任で行ってください。」と記載すること
"""


def format_candidates(scored: list[ScoredStock]) -> str:
    """Render screened candidates as a Markdown table for the prompt."""
    lines = [
        "| コード | 銘柄名 | セクター | PER | PBR | 配当利回り | ROE | 純利益率 | 3ヶ月リターン | 6ヶ月リターン | 総合スコア |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scored:
        m = s.metrics
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {:.3f} |".format(
                m.code,
                m.name,
                m.sector,
                _num(m.per),
                _num(m.pbr),
                _pct(m.dividend_yield),
                _pct(m.roe),
                _pct(m.profit_margin),
                _pct(m.return_3m),
                _pct(m.return_6m),
                s.composite,
            )
        )
    return "\n".join(lines)


def select_stocks(
    scored: list[ScoredStock],
    picks: int = 5,
    model: str = DEFAULT_MODEL,
    stream_to_stdout: bool = True,
) -> str | None:
    """Ask Claude to select stocks from the screened candidates.

    Returns the analysis text, or None if the API is unavailable
    (no credentials / no network) — callers should fall back to the
    quantitative ranking alone.
    """
    try:
        import anthropic
    except ImportError:
        print("warning: anthropic パッケージ未導入のためAI分析をスキップします", file=sys.stderr)
        return None

    prompt = (
        f"以下は定量スクリーニング(バリュー40%・クオリティ35%・モメンタム25%の複合スコア)"
        f"の上位候補です。この中から{picks}銘柄を選定してください。\n\n"
        f"{format_candidates(scored)}"
    )

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            if stream_to_stdout:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                print()
            message = stream.get_final_message()
    except (anthropic.AuthenticationError, TypeError):
        # The SDK raises TypeError at request time when no credentials are configured.
        print(
            "warning: Anthropic APIの認証情報がありません。ANTHROPIC_API_KEY を設定するか "
            "`ant auth login` を実行してください。AI分析をスキップします。",
            file=sys.stderr,
        )
        return None
    except anthropic.APIConnectionError as e:
        print(f"warning: Anthropic APIに接続できません({e})。AI分析をスキップします。", file=sys.stderr)
        return None

    return next((b.text for b in message.content if b.type == "text"), "")


def _num(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "-"


def _pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "-"

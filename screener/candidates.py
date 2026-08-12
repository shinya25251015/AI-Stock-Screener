"""発掘候補リスト（社名＋証券コードの仮説）を読み、取得した社名と突き合わせる。

**なぜこれが要るのか（§8）**: 証券コードを一般知識から推測して記録してはいけない。
一方で発掘の初期段階では「たぶん東鉄工業は1835」という仮説からしか始められない。
そこで **仮説として書く → 取得ページの社名と突き合わせて検証する** という手順を
コードに落とす。社名が一致しなければ `name_mismatch` を立て、その候補は
**証券コード未確認として扱う**（`config/` へ記録してはいけない）。

Future100 側の `code_verified: true` は、この突合を通ったものにだけ付ける。
なお本突合は金融DB（finance.yahoo.co.jp）との照合＝**準一次**であり、
昇格判断の前には有報・短信の原本でコードを確認すること。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Candidate:
    """発掘候補1件。`code` は**仮説**であって確定値ではない。"""

    name: str
    code: str
    ticker: str = ""
    theme: str = ""
    note: str = ""
    group: str = ""

    def resolved_ticker(self) -> str:
        """取得に使うティッカー。未指定なら東証(.T)を仮定する。

        **名証・札証・福証の銘柄は `ticker` を明示すること**（愛知電機は `6623.N`）。
        .T で404が返ったら、上場廃止か取引所サフィックス誤りを疑う。
        """
        return self.ticker or f"{self.code}.T"


def _normalize(name: str) -> str:
    """社名の突合用に正規化する。

    全角/半角、株式会社・(株)・ＨＤ等の表記ゆれを吸収する。
    Yahoo!側は「(株)東鉄工業」「東鉄工業(株)」のように接頭・接尾が揺れるため。
    """
    text = unicodedata.normalize("NFKC", name)
    text = re.sub(r"株式会社|\(株\)|（株）", "", text)
    text = re.sub(r"ホールディングス|ホールディング", "HD", text)
    text = re.sub(r"[\s・,、。\.]", "", text)
    return text.upper()


def names_match(hypothesis: str, fetched: str) -> bool:
    """仮説の社名と取得した社名が同一企業を指すか。

    どちらかがもう一方を含めば一致とみなす（「ID&EHD」と「ID&EホールディングスHD」等）。
    """
    a, b = _normalize(hypothesis), _normalize(fetched)
    if not a or not b:
        return False
    return a in b or b in a


@dataclass
class CandidateList:
    path: Path
    title: str
    asof: str
    source_note: str
    candidates: list[Candidate] = field(default_factory=list)

    def groups(self) -> list[str]:
        seen: list[str] = []
        for c in self.candidates:
            if c.group not in seen:
                seen.append(c.group)
        return seen


def load(path: str | os.PathLike[str]) -> CandidateList:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items: list[Candidate] = []
    for group in data.get("groups") or []:
        label = str(group.get("label") or "")
        theme = str(group.get("theme") or "")
        for raw in group.get("candidates") or []:
            items.append(
                Candidate(
                    name=str(raw.get("name") or ""),
                    code=str(raw.get("code") or ""),
                    ticker=str(raw.get("ticker") or ""),
                    theme=str(raw.get("theme") or theme),
                    note=str(raw.get("note") or ""),
                    group=label,
                )
            )
    return CandidateList(
        path=Path(path),
        title=str(data.get("title") or ""),
        asof=str(data.get("asof") or ""),
        source_note=str(data.get("source_note") or ""),
        candidates=items,
    )

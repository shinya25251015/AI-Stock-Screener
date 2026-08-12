"""Future100 の config/watchlist.yaml を読み込む。

普通に yaml.safe_load するだけでは **`leads_unverified` の判断理由が失われる**。
理由がYAMLコメントとして書かれているため:

    leads_unverified:
      # ---- 2026-08-04「成長継続軸」第1パスの未検証候補 ----
      - { name: "戸田工業", code: "4100" }  # PBR0.86だが予想ROE5.5%<6%で品質フロア僅か割れ

この module は YAML 本体に加えて生テキストも走査し、各リードに
「直前のコメント塊（節見出し）」と「行末のコメント（個別理由）」を復元する。
watchlist 側の銘柄間コメント（昇格の記録など）も `standalone_notes` として拾う。

Future100 側は書き換えない。**このリポジトリは読み取り専用で参照する**
（Future100 CLAUDE.md 担当範囲: watchlist.yaml は日次レポートのために残置されており、
 発掘側の記録は①一次確認が済んだものだけを Future100 セッション経由で書き戻す）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: 既定の探索先。環境変数 FUTURE100_DIR で上書きできる。
DEFAULT_RELATIVE_PATHS = (
    "../Future100/config/watchlist.yaml",
    "../Future100/config/holdings.yaml",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_watchlist_path() -> Path:
    env = os.environ.get("FUTURE100_DIR")
    if env:
        return Path(env) / "config" / "watchlist.yaml"
    return (_repo_root() / "../Future100/config/watchlist.yaml").resolve()


def default_holdings_path() -> Path:
    env = os.environ.get("FUTURE100_DIR")
    if env:
        return Path(env) / "config" / "holdings.yaml"
    return (_repo_root() / "../Future100/config/holdings.yaml").resolve()


@dataclass
class Lead:
    """`leads_unverified` の1件＋コメントから復元した理由。"""

    name: str
    code: str
    inline_comment: str = ""
    section_comments: list[str] = field(default_factory=list)
    line_no: int = 0

    @property
    def reason(self) -> str:
        """個別理由（行末コメント）。無ければ空文字。"""
        return self.inline_comment

    @property
    def section(self) -> str:
        """節見出し（直前のコメント塊）を1行に畳んだもの。"""
        return " ".join(self.section_comments).strip()


@dataclass
class Watchlist:
    path: Path
    entries: list[dict[str, Any]]
    leads: list[Lead]
    standalone_notes: list[str]

    def by_code(self, code: str) -> dict[str, Any] | None:
        for entry in self.entries:
            if str(entry.get("code")) == str(code):
                return entry
        return None

    def lead_by_code(self, code: str) -> Lead | None:
        for lead in self.leads:
            if lead.code == str(code):
                return lead
        return None

    def codes(self) -> list[str]:
        return [str(e.get("code")) for e in self.entries]


_LEAD_RE = re.compile(
    r"""^\s*-\s*\{\s*name:\s*["']?(?P<name>[^"',}]+)["']?\s*,\s*"""
    r"""code:\s*["']?(?P<code>[^"',}\s]+)["']?\s*\}\s*(?:\#\s?(?P<comment>.*))?$"""
)
_COMMENT_RE = re.compile(r"^\s*#\s?(?P<text>.*)$")
_TOP_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):\s*$")


def _clean_comment(text: str) -> str:
    """飾り（---- で囲んだ節見出し）を落として読みやすくする。"""
    return text.strip().strip("-").strip()


def parse_leads(raw: str) -> tuple[list[Lead], list[str]]:
    """生テキストから leads_unverified の各件＋コメントを復元する。

    Returns:
        (leads, standalone_notes)
        standalone_notes は leads_unverified より前（＝watchlist セクション）にある
        独立コメント行。昇格の記録などが書かれているため捨てずに保持する。
    """
    leads: list[Lead] = []
    standalone_notes: list[str] = []
    pending: list[str] = []
    section: list[str] = []
    in_leads = False

    for line_no, line in enumerate(raw.splitlines(), start=1):
        top = _TOP_KEY_RE.match(line)
        if top:
            in_leads = top.group("key") == "leads_unverified"
            pending = []
            section = []
            continue

        comment = _COMMENT_RE.match(line)
        if comment:
            text = _clean_comment(comment.group("text"))
            if text:
                pending.append(text)
                if not in_leads:
                    standalone_notes.append(text)
            continue

        if not in_leads:
            pending = []
            continue

        lead = _LEAD_RE.match(line)
        if lead:
            if pending:
                # 直前のコメント塊は節見出しとみなし、次の塊が現れるまで持ち回す。
                section = pending
                pending = []
            leads.append(
                Lead(
                    name=lead.group("name").strip(),
                    code=lead.group("code").strip(),
                    inline_comment=_clean_comment(lead.group("comment") or ""),
                    section_comments=list(section),
                    line_no=line_no,
                )
            )
        else:
            pending = []

    return leads, standalone_notes


def load(path: str | os.PathLike[str] | None = None) -> Watchlist:
    """watchlist.yaml を構造＋コメント込みで読み込む。"""
    target = Path(path) if path else default_watchlist_path()
    raw = Path(target).read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    entries = data.get("watchlist") or []
    leads, notes = parse_leads(raw)
    return Watchlist(path=Path(target), entries=entries, leads=leads, standalone_notes=notes)


def load_holdings(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """holdings.yaml の銘柄一覧（重複を避けるための参照用）。

    積立額（monthly_amount 等）はこのリポジトリからは**絶対に書き換えない**
    （Future100 CLAUDE.md セッション運用ルール1）。読み取りのみ。
    """
    target = Path(path) if path else default_holdings_path()
    data = yaml.safe_load(Path(target).read_text(encoding="utf-8")) or {}
    return data.get("holdings") or []


def known_codes(
    watchlist_path: str | os.PathLike[str] | None = None,
    holdings_path: str | os.PathLike[str] | None = None,
) -> set[str]:
    """既に監視・保有している証券コードの集合（同じ穴を掘らないため）。"""
    codes: set[str] = set()
    wl = load(watchlist_path)
    codes.update(wl.codes())
    codes.update(lead.code for lead in wl.leads)
    try:
        codes.update(str(h.get("code")) for h in load_holdings(holdings_path))
    except FileNotFoundError:
        pass
    return {c for c in codes if c and c != "None"}

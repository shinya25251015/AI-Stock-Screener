"""決算短信の**原本**へ到達し、実績ROEの特別損益チェックを機械化する。

`docs/special_items_check_2026-08-18.md` で新設した判定順——

    安さ足切り → 品質フロア → ★実績ROEの特別損益チェック → ①一次確認

——の★を、手作業（PDFを開いて目で読む）から関数に落とす。確認済みの実例では
**実績ROEをそのまま信じると判定が覆る**ことが繰り返し起きている
（日本カーボン5302: 9.08%→5.55%／大同信号6743: 6.87%→5.93%＝どちらも品質フロア割れ）。

## この文書が扱う2段

1. **原本の所在**（`fetch_disclosures`）——決算短信PDFのURLを引く。2ルートある:

   - `yahoo`: `finance.yahoo.co.jp/quote/<code>/disclosure` の**直近1年ぶん**。
     新しい開示に強いが、**3月期・9月期・10月期の本決算のように1年以上前の開示は落ちる**。
   - `kabupro`: `ke.kabupro.jp/code/<code>.htm` の**数年ぶん**。古い本決算に強い。
     Shift-JIS（cp932）で、`href` が**引用符なし**という癖がある。
     httpsは証明書のホスト名不一致で失敗するため **http で叩く**。

   2026-08-21のF-4再検証では、9社中4社（3038・3769・3762・6544）が
   Yahoo側では本決算に届かず、kabupro側で取得できた。**両方を持っていないと届かない。**

2. **原本からの数値**（`parse_special_items`）——連結損益計算書の
   「特別利益合計／特別損失合計／税金等調整前当期純利益／法人税等合計／非支配株主に帰属する
   当期純利益」と、サマリーの「（参考）自己資本」を拾う。
   拾った**根拠の行そのもの**（`evidence`）を必ず一緒に返す——§14（完全引用ルール）により、
   引用を提示できない判定は無効だから。

**日本基準（JGAAP）専用。** IFRS採用会社には「特別損益」の区分が無く、
近いのは「その他の収益／その他の費用」だが**同義ではない**ので自動では扱わない
（`parse_special_items` は IFRS 短信に対して `None` を返す）。IFRSは原本を人が読む。

このモジュールは §0 に従いテクニカル指標を一切扱わない。また `yahoo_jp` と同じく
**取得系の関数は例外を投げず**、失敗は戻り値の `error` に入れてレポート生成を止めない。
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

#: Yahoo・kabupro とも普通のブラウザ以外を弾くことがある。
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "ja,en;q=0.8"}

YAHOO_URL = "https://finance.yahoo.co.jp/quote/{ticker}/disclosure"
#: httpsは証明書のホスト名不一致で落ちる（`docs/data_access.md`）。httpで叩く。
KABUPRO_URL = "http://ke.kabupro.jp/code/{code}.htm"

DEFAULT_SLEEP_SEC = 4.0

#: 本決算短信の判定から外すもの。四半期・中間・訂正・説明資料。
_NOT_ANNUAL = ("四半期", "中間", "訂正", "説明資料", "補足")

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ 　\t]+")


@dataclass
class Disclosure:
    """適時開示1件。"""

    date: str
    title: str
    url: str
    source: str = ""

    @property
    def is_tanshin(self) -> bool:
        return "決算短信" in self.title

    @property
    def is_annual_tanshin(self) -> bool:
        """**本決算**の短信か（四半期・中間・訂正を除く）。"""
        if not self.is_tanshin:
            return False
        return not any(word in self.title for word in _NOT_ANNUAL)

    @property
    def is_ifrs(self) -> bool:
        # 短信のタイトルは「〔ＩＦＲＳ〕」＝全角。半角表記も念のため見る。
        return "ＩＦＲＳ" in self.title or "IFRS" in self.title


@dataclass
class SpecialItems:
    """連結損益計算書から拾った特別損益まわりの実額。

    単位は `unit_label` に揃えて返す（原本の表の単位。百万円 or 千円）。
    ただし `equity_*` だけはサマリーの「（参考）自己資本」由来で
    **原本上の単位が表と異なることがある**ため、`unit_label` へ換算して返す。
    """

    pretax_income: float | None = None
    special_gains: float = 0.0
    special_losses: float = 0.0
    tax_total: float | None = None
    minority_interest: float = 0.0
    #: 前期の値。短信の連結P/Lは「前期／当期」の2列なので同時に取れる。
    #: **実効税率の前年比較**（`valuation.TaxRateCheck`）に使う——税負担の軽減は
    #: 特別損益欄に出ないため、これが無いとフィックスターズ型の嵩上げを検出できない。
    pretax_income_prev: float | None = None
    tax_total_prev: float | None = None
    special_gains_prev: float = 0.0
    special_losses_prev: float = 0.0
    equity_end: float | None = None
    equity_begin: float | None = None
    unit_label: str = ""
    is_ifrs: bool = False
    #: 根拠の行そのもの（§14 完全引用ルール）。
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def equity_average(self) -> float | None:
        """期首期末平均の自己資本。ROEの分母はこちらが原本の定義に近い。"""
        if self.equity_end is None or self.equity_begin is None:
            return None
        return (self.equity_end + self.equity_begin) / 2

    @property
    def complete(self) -> bool:
        return not self.missing


# --------------------------------------------------------------------------
# 1. 原本の所在
# --------------------------------------------------------------------------


def _http_get(url: str, timeout: float = 40.0) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 (URLは定数由来)
        return res.read()


def parse_yahoo_disclosures(html: str) -> list[Disclosure]:
    """`finance.yahoo.co.jp/quote/<t>/disclosure` のHTMLから開示一覧を取り出す。

    1件が `<article class="...DisclosureItem">` で、その中に
    `<a href="....pdf">` と `<h3 class="...DisclosureItem__heading">` と
    `<time datetime="...">` が入っている。**HTML埋め込みJSONではない**
    （`yahoo_jp` と同じく、ページはサーバサイドレンダリング）。
    """
    out: list[Disclosure] = []
    for block in html.split("DisclosureItem\"")[1:]:
        link = re.search(r'href="(https://[^"]+\.pdf)"', block)
        if not link:
            continue
        heading = re.search(r'DisclosureItem__heading">(.*?)</h3>', block, re.S)
        stamp = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', block)
        title = _WS_RE.sub(" ", _TAG_RE.sub("", heading.group(1))).strip() if heading else ""
        out.append(
            Disclosure(
                date=stamp.group(1) if stamp else "",
                title=title,
                url=link.group(1),
                source="yahoo",
            )
        )
    return out


def parse_kabupro_disclosures(html: str) -> list[Disclosure]:
    """`ke.kabupro.jp/code/<code>.htm` から開示一覧を取り出す。

    癖が2つある: **`href` に引用符が無い**（`href=http://...pdf`）ことと、
    日付が `2026/03/13` 形式でリンクの外側にあること。
    """
    out: list[Disclosure] = []
    for row in re.findall(r"<tr.*?</tr>", html, re.S):
        link = re.search(r"href=\"?(https?://[^\s>\"]+\.pdf)\"?", row)
        if not link:
            continue
        text = _WS_RE.sub(" ", _TAG_RE.sub(" ", row)).strip()
        stamp = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
        title = ""
        cell = re.search(r"CellBrownName[^>]*>(.*?)</td>", row, re.S)
        if cell:
            title = _WS_RE.sub(" ", _TAG_RE.sub("", cell.group(1))).strip()
        out.append(
            Disclosure(
                date=f"{stamp.group(1)}-{stamp.group(2)}-{stamp.group(3)}" if stamp else "",
                title=title,
                url=link.group(1),
                source="kabupro",
            )
        )
    return out


def fetch_disclosures(
    code: str,
    *,
    source: str = "both",
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    ticker: str | None = None,
) -> tuple[list[Disclosure], str]:
    """開示一覧を引く。**例外を投げない**（失敗は戻り値の error 文字列に入る）。

    Args:
        code: 証券コード（"3778" / "575A"）。
        source: ``"yahoo"`` / ``"kabupro"`` / ``"both"``。
            ``both`` は Yahoo（直近1年・新しい開示に強い）を先に、
            kabupro（数年ぶん・古い本決算に強い）を後に連結する。
        sleep_sec: 取得前スリープ。連続アクセスはレート制限を受ける。
        ticker: Yahoo側のティッカー。名証銘柄は ``"1869.N"`` のように渡す
            （`.T` では404になる。愛知電機・名工建設で実際に踏んだ）。

    Returns:
        (開示のリスト, エラー文字列)。片方だけ失敗した場合は取れたぶんを返しつつ
        error に理由を書く。
    """
    errors: list[str] = []
    found: list[Disclosure] = []
    wanted = ("yahoo", "kabupro") if source == "both" else (source,)

    for src in wanted:
        if sleep_sec:
            time.sleep(sleep_sec)
        try:
            if src == "yahoo":
                raw = _http_get(YAHOO_URL.format(ticker=ticker or f"{code}.T"))
                found.extend(parse_yahoo_disclosures(raw.decode("utf-8", "replace")))
            elif src == "kabupro":
                raw = _http_get(KABUPRO_URL.format(code=code))
                found.extend(parse_kabupro_disclosures(raw.decode("cp932", "replace")))
            else:
                errors.append(f"未知のsource: {src}")
        except urllib.error.HTTPError as exc:
            hint = "（上場廃止か取引所サフィックス誤りを疑う）" if exc.code == 404 else ""
            errors.append(f"{src}: HTTP {exc.code}{hint}")
        except Exception as exc:  # noqa: BLE001 — 取得失敗でレポートを止めない契約
            errors.append(f"{src}: {type(exc).__name__}: {exc}")

    return found, " / ".join(errors)


def latest_annual_tanshin(disclosures: list[Disclosure]) -> Disclosure | None:
    """本決算短信のうち最も新しいものを返す。"""
    annual = [d for d in disclosures if d.is_annual_tanshin]
    if not annual:
        return None
    return max(annual, key=lambda d: d.date)


def pdf_to_text(data: bytes) -> str:
    """PDFのバイト列をテキストへ。pypdf は**この関数の中でだけ**import する。

    pypdf は必須依存にしていない（日次の足切りには要らない）。
    サンドボックスでは `pip install pypdf` に加えて
    `pip install --upgrade cffi` が要ることがある（`docs/data_access.md`）。
    """
    from pypdf import PdfReader  # 遅延import: 未インストールでも他機能は動く
    from io import BytesIO

    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def fetch_tanshin_text(url: str, *, sleep_sec: float = DEFAULT_SLEEP_SEC) -> tuple[str, str]:
    """短信PDFを取得してテキスト化する。**例外を投げない**。"""
    if sleep_sec:
        time.sleep(sleep_sec)
    try:
        return pdf_to_text(_http_get(url, timeout=90.0)), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# 2. 原本からの数値
# --------------------------------------------------------------------------

_NUM = r"[△▲\-]?[\d,]+"

#: 「ラベル 前期 当期」の並び。短信の連結P/Lは左が前期・右が当期。
_PL_LABELS = {
    "pretax_income": "税金等調整前当期純利益",
    "special_gains": "特別利益合計",
    "special_losses": "特別損失合計",
    "tax_total": "法人税等合計",
}
#: 前期の値も保持するフィールド（実効税率の前年比較に要る）。
_PREV_FIELDS = ("pretax_income", "tax_total", "special_gains", "special_losses")
_UNIT_RE = re.compile(r"単位[：:]\s*(百万円|千円|円)")
_EQUITY_RE = re.compile(
    r"[（(]参考[)）]\s*自己資本\s*\S+?\s*(?P<end>[\d,]+)(?P<unit>百万円|千円)"
    r"\s*\S+?\s*(?P<begin>[\d,]+)(?:百万円|千円)"
)
_UNIT_SCALE = {"円": 1, "千円": 1_000, "百万円": 1_000_000}


def _to_number(text: str) -> float | None:
    text = text.strip().replace(",", "")
    sign = -1 if text[:1] in "△▲-" else 1
    digits = text.lstrip("△▲-")
    if not digits.isdigit():
        return None
    return sign * float(digits)


#: 表の行かどうかの判定。ラベルの後ろが数値・脚注記号・ダッシュだけなら表。
#: これを見ないと「税金等調整前当期純利益による22,572百万円及び…」のような
#: **本文の文章**を表と取り違える（ショーボンドHD1414・神戸物産3038で実際に踏んだ）。
_ONLY_NUMBERS_RE = re.compile(r"^[\s　\d,.△▲\-－ー()（）%％]*$")


def _numbers_in(fragment: str) -> list[float]:
    fragment = re.sub(r"※\s*\d*", " ", fragment)  # 「※４」等の脚注番号を落とす
    return [v for v in (_to_number(t) for t in re.findall(_NUM, fragment)) if v is not None]


def _table_values(lines: list[str], label: str) -> tuple[int, list[float]] | None:
    """連結損益計算書の**表の行**から「前期 当期」を拾う。文章の行は採らない。"""
    for i, line in enumerate(lines):
        if label not in line:
            continue
        tail = re.sub(r"※\s*\d*", " ", line.split(label, 1)[1])
        if not _ONLY_NUMBERS_RE.match(tail):
            continue
        values = _numbers_in(tail)
        if len(values) >= 2:
            return i, values
    return None


def _minority_interest(text: str) -> tuple[float, str] | None:
    """非支配株主に帰属する当期純利益（当期）を拾う。

    短信によってはラベルが行をまたぐ——ショーボンドHD(1414)の原本は
    「非支配株主に帰属する当期純利益又は非支配株主に／帰属する当期純損失（△） △24 72」。
    そこで行単位ではなく、**ラベルから次の「親会社株主に帰属する当期純利益」まで**を
    切り出して数値を拾う。
    """
    start = text.find("非支配株主に帰属する当期純利益")
    if start < 0:
        return None
    rest = text[start:]
    end = rest.find("親会社株主に帰属する当期純利益")
    fragment = rest[:end] if end > 0 else rest[:200]
    values = _numbers_in(fragment)
    if len(values) < 2:
        return None
    return values[-1], _WS_RE.sub(" ", fragment.replace("\n", " ")).strip()


def parse_special_items(text: str) -> SpecialItems | None:
    """短信のテキストから特別損益まわりの実額を拾う。

    **日本基準の短信専用。** IFRS短信（「税引前利益」「その他の収益」）を渡すと
    `is_ifrs=True` だけを立てた `SpecialItems` を返す——特別損益の区分が無いものを
    無理に読み替えると、まさに§8が禁じている「〜のはず」になるため。

    見つからなかった項目は `missing` に名前が入る。**推測で埋めない。**
    特別利益・特別損失は「合計行が無い＝その期は特別損益が無い」ことが実際にあるため
    （グローバルセキュリティエキスパート4417の26/3期は特別利益の区分そのものが無い）、
    欠けていても `missing` には入れず 0 として扱う。

    Returns:
        `SpecialItems`。テキストが短信に見えないときは None。
    """
    if "税金等調整前当期純利益" not in text:
        if "税引前利益" in text or "その他の収益" in text:
            return SpecialItems(is_ifrs=True, missing=["JGAAPの特別損益区分なし（IFRS）"])
        return None

    lines = text.splitlines()
    items = SpecialItems()

    anchor = len(lines)
    for field_name, label in _PL_LABELS.items():
        hit = _table_values(lines, label)
        if hit is None:
            if field_name in ("special_gains", "special_losses"):
                continue  # その期に区分が無いだけ。0のままにする
            items.missing.append(label)
            continue
        index, values = hit
        setattr(items, field_name, values[-1])  # 右端＝当期
        if field_name in _PREV_FIELDS:  # 左＝前期。実効税率の前年比較に使う
            setattr(items, f"{field_name}_prev", values[-2])
        items.evidence.append(_WS_RE.sub(" ", lines[index]).strip())
        if field_name == "pretax_income":
            anchor = index

    # 表の単位は、連結P/Lの「税金等調整前当期純利益」の行より前で最後に現れた「単位：X円」。
    for line in lines[:anchor]:
        unit = _UNIT_RE.search(line)
        if unit:
            items.unit_label = unit.group(1)
    if not items.unit_label:
        items.missing.append("表の単位")

    minority = _minority_interest(text)
    if minority is not None:
        items.minority_interest, evidence = minority
        items.evidence.append(evidence)

    # 「（参考）自己資本 2026年３月期 4,401百万円 2025年３月期 3,078百万円」
    # 最初の一致＝連結（2つ目は個別）。
    equity = _EQUITY_RE.search(_WS_RE.sub(" ", text))
    if equity:
        scale = _UNIT_SCALE[equity.group("unit")] / _UNIT_SCALE.get(items.unit_label, 1)
        items.equity_end = (_to_number(equity.group("end")) or 0) * scale
        items.equity_begin = (_to_number(equity.group("begin")) or 0) * scale
        items.evidence.append(_WS_RE.sub(" ", equity.group(0)).strip())
    else:
        items.missing.append("（参考）自己資本")

    return items

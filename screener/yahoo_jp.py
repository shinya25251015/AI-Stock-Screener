"""finance.yahoo.co.jp から株価・PBR・BPS・ROE・時価総額を取得する。

**なぜ yfinance ではないのか**: 開発サンドボックスからは query1.finance.yahoo.com
（yfinance のバックエンド）へ到達できないことが多い。Future100 側で確立した迂回路が
finance.yahoo.co.jp の HTML 直読みで、こちらはサンドボックスからも到達できる。

**ページ構造について（2026-08-12 実測）**: Future100 の引き継ぎには
「HTML埋め込みJSON（`"pbr":{..."value":"1.12"...}`）から抽出する」と書かれているが、
2026-08-12 時点のページに**その JSON は存在しない**。現在はサーバサイドレンダリングされた
HTML で、各指標が次の形で並んでいる:

    <dl class="_DataListItem_...">
      <dt><span class="_DataListItem__name_...">PBR</span>
          <span class="_DataListItem__sub_...">（実績）</span></dt>
      <dd class="_DataListItem__description_...">(連)<span class="_StyledNumber__value_...">6.59</span>倍</dd>
    </dl>

株価は `_CommonPriceBoard__price_` を含む `_StyledNumber__value_` から取る。
クラス名にはビルドごとのハッシュが付くため、**ハッシュを含まない前方一致**で拾う。
構造が変わったら `parse_quote()` のテスト（tests/test_yahoo_jp.py）が落ちるので、
そこを直すこと。

契約:
    ``fetch_quote()`` は **例外を投げない**。ネットワーク断・レート制限・構造変更は
    いずれも戻り値の ``error`` に文字列で入る（Future100 fetch_metrics() と同じ契約）。
    連続アクセスで HTTP 500（レート制限）になるため、既定で1件ごとに数秒スリープする。
"""

from __future__ import annotations

import gzip
import html as html_mod
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE_URL = "https://finance.yahoo.co.jp/quote/{ticker}"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

#: 1銘柄ごとの既定スリープ秒。連続アクセスでHTTP 500になるため短くしない。
DEFAULT_SLEEP_SEC = 4.0
DEFAULT_RETRIES = 3

_TAG_RE = re.compile(r"<[^>]+>")
_UNIT_MAN = 10_000
_UNIT_OKU = 100_000_000


@dataclass
class Quote:
    ticker: str
    name: str = ""
    price: float | None = None
    pbr: float | None = None
    per: float | None = None
    bps: float | None = None
    eps: float | None = None
    roe_pct: float | None = None
    forecast_roe_pct: float | None = None
    equity_ratio_pct: float | None = None
    market_cap_yen: float | None = None
    shares_outstanding: float | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "price": self.price,
            "pbr": self.pbr,
            "per": self.per,
            "bps": self.bps,
            "eps": self.eps,
            "roe_pct": self.roe_pct,
            "forecast_roe_pct": self.forecast_roe_pct,
            "equity_ratio_pct": self.equity_ratio_pct,
            "market_cap_yen": self.market_cap_yen,
            "shares_outstanding": self.shares_outstanding,
            "source_url": self.source_url,
            "error": self.error,
        }


def _strip_tags(fragment: str) -> str:
    return html_mod.unescape(_TAG_RE.sub("", fragment)).strip()


def _to_number(text: str) -> float | None:
    """'(連)6.59倍(15:30)' → 6.59 のように、最初の数値を取り出す。"""
    if not text:
        return None
    cleaned = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _to_yen(text: str) -> float | None:
    """'778,973百万円(15:30)' → 778973000000.0。単位付きの金額を円に直す。"""
    value = _to_number(text)
    if value is None:
        return None
    if "兆" in text:
        return value * 1_000_000_000_000
    if "百万円" in text:
        return value * 1_000_000
    if "億" in text:
        return value * _UNIT_OKU
    if "万" in text:
        return value * _UNIT_MAN
    return value


def parse_quote(html: str, ticker: str = "") -> Quote:
    """銘柄ページのHTMLから指標を抽出する。ネットワークには触らない（テスト可能）。"""
    quote = Quote(ticker=ticker, source_url=BASE_URL.format(ticker=ticker) if ticker else "")

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    if title:
        # 例: 「ＧＭＯペイメントゲートウェイ(株)【3769】：株価・株式情報 - Yahoo!ファイナンス」
        text = _strip_tags(title.group(1))
        text = re.split(r"\s+-\s+|｜", text)[0]
        text = re.sub(r"^【[^】]*】", "", text)  # 【コード】が先頭に来る表記にも備える
        quote.name = re.split(r"【|：", text)[0].strip()

    price_match = re.search(
        r'_CommonPriceBoard__price_[^"]*"[^>]*>.*?_StyledNumber__value_[^"]*">([^<]+)<',
        html,
        re.S,
    )
    if price_match:
        quote.price = _to_number(price_match.group(1))

    fields: dict[str, str] = {}
    for block in re.split(r'<dl class="_DataListItem_', html)[1:]:
        name_match = re.search(r'_DataListItem__name_[^"]*">([^<]*)</span>', block)
        if not name_match:
            continue
        sub_match = re.search(r'_DataListItem__sub_[^"]*">([^<]*)</span>', block)
        dd_match = re.search(r'<dd class="_DataListItem__description_.*?</dd>', block, re.S)
        if not dd_match:
            continue
        label = _strip_tags(name_match.group(1))
        if sub_match:
            label += _strip_tags(sub_match.group(1))
        value = _strip_tags(dd_match.group(0))
        # 同名ラベル（始値/高値など現物とPTSで重複）は先勝ちにする。
        fields.setdefault(label, value)

    quote.raw_fields = fields

    def pick(*labels: str) -> str:
        for lab in labels:
            if lab in fields:
                return fields[lab]
        # 前方一致でも探す（サブラベルの表記ゆれ対策）。
        for lab in labels:
            for key, val in fields.items():
                if key.startswith(lab):
                    return val
        return ""

    quote.pbr = _to_number(pick("PBR（実績）", "PBR"))
    quote.per = _to_number(pick("PER（会社予想）", "PER"))
    quote.bps = _to_number(pick("BPS（実績）", "BPS"))
    quote.eps = _to_number(pick("EPS（会社予想）", "EPS"))
    quote.roe_pct = _to_number(pick("ROE（実績）", "ROE"))
    quote.equity_ratio_pct = _to_number(pick("自己資本比率（実績）", "自己資本比率"))
    quote.market_cap_yen = _to_yen(pick("時価総額"))
    shares = pick("発行済株式数")
    quote.shares_outstanding = _to_number(shares) if shares else None

    # 会社予想ROEの近似 ＝ EPS（会社予想）÷ BPS（実績）。
    # Yahoo!は予想ROEを直接持たないため導出する。**あくまで概算**であり、
    # 期中の自己資本増加を織り込まないぶん実際よりやや高めに出る。
    # B-4判定には使わず（比は実績ROEで計算する）、"山"の検算にのみ使うこと。
    if quote.eps is not None and quote.bps:
        quote.forecast_roe_pct = quote.eps / quote.bps * 100

    if quote.price is None and quote.pbr is None and quote.roe_pct is None:
        quote.error = "指標を1つも抽出できなかった（ページ構造が変わった可能性・上場状態も確認する）"

    return quote


def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def fetch_quote(
    ticker: str,
    retries: int = DEFAULT_RETRIES,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    timeout: float = 30.0,
) -> Quote:
    """1銘柄を取得する。**例外は投げない**。失敗は Quote.error に入る。

    Args:
        ticker: "3769.T" のような形式。**名証は .N**（例: 愛知電機 6623.N）。
    """
    url = BASE_URL.format(ticker=ticker)
    last_error = ""
    for attempt in range(retries):
        try:
            body = _http_get(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code == 404:
                # 404は上場廃止 or 取引所サフィックス誤りの可能性が高い。リトライしない。
                return Quote(
                    ticker=ticker,
                    source_url=url,
                    error=(
                        "HTTP 404: 上場廃止か取引所サフィックス誤りの可能性。"
                        " api都合と決めつけず上場状態と市場（東証=.T／名証=.N）を確認すること"
                    ),
                )
        except Exception as exc:  # noqa: BLE001 - "never raises" の契約を守る
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            quote = parse_quote(body.decode("utf-8", errors="replace"), ticker=ticker)
            if not quote.error:
                return quote
            last_error = quote.error
        if attempt < retries - 1:
            time.sleep(sleep_sec * (attempt + 1))
    return Quote(ticker=ticker, source_url=url, error=f"取得失敗（{retries}回リトライ）: {last_error}")


def fetch_many(
    tickers: list[str],
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    retries: int = DEFAULT_RETRIES,
) -> list[Quote]:
    """複数銘柄を1件ずつスリープを挟んで取得する（レート制限対策）。"""
    quotes: list[Quote] = []
    for index, ticker in enumerate(tickers):
        if index:
            time.sleep(sleep_sec)
        quotes.append(fetch_quote(ticker, retries=retries, sleep_sec=sleep_sec))
    return quotes

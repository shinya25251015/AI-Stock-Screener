# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## リポジトリの目的

**2035 Future プロジェクトの「発掘・監視エンジン」**。
[Future100](https://github.com/shinya25251015/Future100) が「保有13銘柄の運用判断」を担うのに対し、
本リポジトリは**監視側**——発掘・スクリーニング・安さ足切り・①一次確認——を担う。
2026-08-12に、監視作業をFuture100の外＝別のコードで行うとユーザーが決定したことを受けて、
それまでグリーンフィールドだったこのリポジトリを受け皿として実装した。
（旧CLAUDE.mdの「初期コミットのみのグリーンフィールド」記述はこの実装で置き換え済み。
`jp-stock-screener` との関係は依然として未文書化であり、推測で前提を持ち込まないこと。）

探しているのは「良い会社」ではなく「**まだ値段がついていない良い会社**」。スコープは全世界株。

## よく使うコマンド

```bash
pip install -r requirements.txt

python -m screener.cli screen 3769.T 1414.T 6623.N     # ティッカー指定で安さ足切り
python -m screener.cli screen AAPL --market US          # 未検証市場はエラーで止まる（§8）
python -m screener.cli watchlist                        # Future100のwatchlistを一覧
python -m screener.cli watchlist --refresh --json       # 実データで全件洗い替え
python -m screener.cli candidates config/candidates_<日付>_<軸>.yaml --exclude-known  # 候補リストを検証＋足切り
python -m screener.cli leads                            # 未検証リード＋YAMLコメントの却下理由

# テスト（ネットワーク不要・モックとfixtureのみ）
pip install -r requirements-dev.txt
python -m pytest -q
python -m pytest tests/test_valuation.py -v
python -m py_compile screener/*.py
```

CIは `.github/workflows/tests.yml` が push/PR 時に `py_compile` → YAML構造検証 → `pytest`。

## まず読むべきドキュメント

作業を始める前に、Future100側の以下を必ず読む（このリポジトリはその規律の実装である）:

1. `../Future100/docs/discovery_mission.md` — **発掘の鉄則・出力形式・軸ごとの地質調査結果**。
   「テーマから入らない」「記憶で銘柄を語らない」「床＋オプション型を探す」「全滅しても掘り続ける」。
2. `../Future100/docs/2035_Future_監視銘柄_引き継ぎ_2026-08-21.md` — 監視21銘柄＋未検証リード52件の
   単独完結版引き継ぎ（前版は `..._2026-08-12.md`）。**§4を読んでから掘る**（同じ穴を掘らないため）。
   **§3「横断再分析で見つかった5つのパターン」は本リポジトリの実装に直結する**——特に
   パターン2（実績ROEの嵩上げは特別損益だけでなく**税**もある。`normalized_roe_from_special_items()`
   では検出できないので**実効税率の前年比較**を足す）と、§1の「**どのROEを分母に採るかは
   保守側＝比が最大になるものを採る**」という2026-08-21に固定したルール。
3. `../Future100/config/watchlist.yaml` / `holdings.yaml` — 既存の監視・保有。重複を避ける。

本リポジトリ側の記録は `docs/`（スクリーニング実施記録）と `reports/`（実行結果JSON）。

## 判断の背骨（コード・判定を変更するときに必ず踏まえる）

| 規律 | 内容 |
|---|---|
| **§0** | 株価変動そのもの・テクニカル指標は**合否の根拠にしない**。参考表示のみ。ただし急騰・急落後は「安さ」の再計算が必要 |
| **§8（一次情報主義）** | 二次情報の「〜のはず」は採用しない。原本に書いていないことは根拠にしない。**証券コード・取引所サフィックスも同じ扱い** |
| **教訓⑧** | 自分のルールを自分に都合よく曲げない。ルールを外れた判断は「裁量」と明記して記録する |

**時事情報は必ずWeb検索で当日時点の最新を確認する。** 国の政策・金利・制度・企業の開示は
モデルの記憶で答えない。学習カットオフ以降に重要な決定が出ている前提で振る舞う。

## アーキテクチャ / データフロー

```
../Future100/config/*.yaml （読み取り専用の参照元）
        │  watchlist.py が YAML本体＋YAMLコメント（leads_unverifiedの却下理由）を復元
        ▼
screener/watchlist.py ── Watchlist(entries, leads, standalone_notes)
        │
        ├── screener/yahoo_jp.py    finance.yahoo.co.jp から株価/PBR/BPS/ROE/時価総額
        │                            "never raises" — 失敗は Quote.error に格納
        │                            EPS(会社予想)÷BPS(実績)で予想ROEを導出（山の検算専用）
        │
        ├── screener/cost_of_capital.py  市場→株主資本コスト。未検証市場は例外で停止
        │
        ▼
screener/valuation.py  ── screen() が 発見済み比・品質フロア・サイズ・山リスクを判定
        │                  ScreenResult（例外を投げず error に格納）
        ▼
screener/cli.py        ── 表 / JSON 出力 → reports/
```

## 重要な設計原則（変更時に必ず踏まえる）

- **B-4判定は必ず実績ROEで行う。** 予想ROEで妥当PBRを膨らませない。東光高岳(6617)・
  ベイカレント(6532)で**2回同じ誤り**が起きている。予想ROEは `RoeInput.forecast_pct` に入れ、
  「山」（循環ピーク）の検算にのみ使う。合否は変えない。
- **一過性ROEの歪みは両方向に効く。** `normalized_pct` を渡すとそちらで比を計算する。
  品川リフラ＝割高に見せる／日東紡＝割安に見せる。`tests/test_valuation.py` に両方の実例がある。
- **海外の株主資本コストを記憶で埋めない。** `config/cost_of_capital.yaml` の
  `verified: false` な市場は `UnverifiedMarketError` で計算を止める。この例外を握りつぶす変更をしない。
  使う日にWeb検索で当日の10年国債利回りを確認し、`risk_free_pct`/`erp_pct`/`asof`/`source` を埋める。
- **`fetch_quote()` は例外を投げない。** ネットワーク断・レート制限・構造変更はすべて
  `Quote.error` に文字列で入る。この契約を壊す変更をしない（Future100 `fetch_metrics()` と同じ）。
- **証券コードを推測のまま記録しない。** 候補リストの `code` は仮説として書き、
  `screener/candidates.py` の `names_match()` が取得社名と突合して検証する。
  不一致は「コードが違う」だけでなく「**こちらの社名が古い**」でも起きる
  （2026-08-12: 九電工1959は正しく、2025-10-01に「クラフティア」へ商号変更していた）。
  **名証・札証・福証は `ticker` を明示する**（名工建設は `1869.N`。`.T` は404）。
- **株価が取れないのを「api都合」で片付けない。** 404は上場廃止か取引所サフィックス誤りとして
  明示する。Future100で前澤工業(6489→上場廃止)・愛知電機(名証なので`6623.N`)の誤診の実例がある。
- **株式分割の前後が混在する。** 異常な騰落率・PBR/BPSの不整合を見たらまず分割を疑う
  （日東紡は2026-07-01に1:5、ショーボンドHDは2026-01-01に1:4）。
- **`verified_fundamentals` を尊重する。** `bvps_yen` があればPBRは「その日の株価 ÷ BVPS」で
  毎回再計算する。自動取得のPBR/ROEは銘柄によって実態と大幅に乖離する。
- **判定ロジック（閾値・計算式）を変えたら README.md の「中核の数式」も更新する。**
  Future100 の `scripts/market_data.py`（`REQUIRED_RETURN=0.08`・
  `PBR_FAIR_VALUE_RATIO_THRESHOLD=1.5`）と定数がずれると、両者の判定が食い違う。

## 書いてよいファイル / 絶対に書かないファイル

**書いてよい**: 本リポジトリ配下すべて。Future100側は `config/watchlist.yaml` の
①一次確認結果の書き戻しのみ（準一次か原本かを明示する）。

**絶対に書かない**:

- `../Future100/config/holdings.yaml` の `monthly_amount` / `sbi_actual` /
  `base_monthly_total_yen`。**積立配分の変更はユーザーの承認を得てから、Future100側が記録する。**
  「増額すべき」と判断してこちらから書き換えることはしない。
- ユーザーの**保有資産**・他口座・資産総額。発掘候補の記録は日本株・海外株を問わず可だが、
  保有内容は `config/`・`docs/`・コミットメッセージに書かない。

## 昇格の受け渡し

```
本リポジトリ: 安さ足切り → ①一次確認（原本） → 全記録を残す → 「①成立・昇格候補」と報告
  → ユーザーがSBIに設定
  → Future100側: スクリーンショットを受けて holdings.yaml へ記録
```

**監視側から積立を"開始"することはしない。** 帳簿が実態を追認する方式。

## テストについて

- `tests/test_valuation.py` — 発見済み比・品質フロア・正常化ROE・山検算。
  **実在銘柄の実測値を使い、Future100側の記録と同じ数字が出ることを確認している**（出典はdocstring）。
- `tests/test_cost_of_capital.py` — 最重要は「未検証市場では黙って計算しない」こと。
- `tests/test_yahoo_jp.py` — `tests/fixtures/quote_3769_trimmed.html`（2026-08-12実取得）に対する
  パース。**ページ構造が変わるとここが落ちる**＝構造変更に気づける仕掛け。落ちたらセレクタを直す。
- `tests/test_watchlist.py` — YAMLコメントからの却下理由の復元。
- 新しい判定ロジックを追加したら対応するテストを追加する。

## 既知の制約・注意点

- **finance.yahoo.co.jp は連続アクセスでHTTP 500（レート制限）**。既定4秒スリープでも
  9銘柄を続けて叩くと制限がかかることを実測で確認済み。制限がかかったら数分空ける。
- **Future100の引き継ぎにある「HTML埋め込みJSON（`"pbr":{..."value":...}`）から抽出」は
  2026-08-12時点で成立しない**。現在はサーバサイドレンダリングされたHTMLで、
  `_DataListItem_*` / `_CommonPriceBoard__price_*` を読む（`screener/yahoo_jp.py` 冒頭に詳述）。
- **決算短信の原本PDF**: `pip install pypdf`（＋`pip install --upgrade cffi`。
  cffiを上げないと `_cffi_backend` が無くて `PdfReader` が落ちる）。WebFetchはPDFバイナリを
  解釈できないので、curlで取ったバイトを `PdfReader` に渡す。
- **適時開示の探し方**: TDnetの日付別一覧
  `https://www.release.tdnet.info/inbs/I_list_0<NN>_<YYYYMMDD>.html`（**UTF-8**。ページ番号は
  01から。銘柄名でgrepする）→ PDFは `https://www.release.tdnet.info/inbs/<id>.pdf`。
  `ke.kabupro.jp` は本セッションでは空を返した。kabutan / minkabu / irbank / stooq は403。
- **Yahoo!の企業IRサイト経由が403のときは、Yahoo!ファイナンスの開示ミラー**
  `https://finance-frontend-pc-dist.west.edge.storage-yahoo.jp/disclosure/<YYYYMMDD>/<id>.pdf` が使える。
- 企業サイトのIRライブラリはJS描画で、curl/WebFetchではPDFリンクが取れないことが多い
  （ショーボンドHDで実例）。TDnetから辿るほうが確実。

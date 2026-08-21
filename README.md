# AI-Stock-Screener — 2035 Future 発掘・監視エンジン

[Future100](https://github.com/shinya25251015/Future100) プロジェクトの**銘柄発見担当**が使う
スクリーニング基盤。2026-08-12に、監視作業（発掘・スクリーニング・安さ足切り・①一次確認）を
Future100リポジトリの外へ切り出す決定に伴い、その受け皿としてこのリポジトリを実装した。

探しているのは「良い会社」ではなく「**まだ値段がついていない良い会社**」。
2035年に社会インフラとして不可欠になる企業を、市場がその企業固有の利益化道筋を
評価していないうち（＝**発火前**）に見つける。スコープは日本株に限らず**全世界株**。

## 中核の数式

```
妥当PBR   = ROE ÷ 株主資本コスト        （残余利益モデル）
発見済み比 = 実PBR ÷ 妥当PBR

  比 < 1.0        → 発火前  （まだ値段がついていない）
  1.0 ≤ 比 < 1.5  → 中間帯  （観察。発火前の安さは無い）
  1.5 ≤ 比        → 発見済み（狙う窓が閉じた）

品質フロア: 実績ROE ≥ 6%（下回れば資本コスト割れ＝価値破壊）
サイズ:     時価総額100〜300億円級を主軸（海外は円換算）
```

株主資本コストは**日本株8%固定**、海外株は**現地10年国債利回り＋ERP5〜6%**で計算し直す。
海外分は `config/cost_of_capital.yaml` が未検証のままだと**計算を止める**（後述）。

## セットアップと実行

```bash
pip install -r requirements.txt

# 1) ティッカーを指定して安さ足切り（実データ取得）
python -m screener.cli screen 3769.T 1414.T 6623.N
python -m screener.cli screen AAPL --market US        # 未検証市場はエラーで止まる（§8）

# 2) Future100 の watchlist を読む / 実データで洗い替え
python -m screener.cli watchlist
python -m screener.cli watchlist --refresh --json > reports/screen_$(date +%F).json

# 3) 候補リスト（社名＋コードの仮説）を検証しつつ足切り
python -m screener.cli candidates config/candidates_2026-08-12_axis6_uncovered.yaml --exclude-known

# 4) 未検証リードと「YAMLコメントに書かれた却下理由」を復元して表示
python -m screener.cli leads

# 5) ①の原本確認に進む前に、実績ROEの特別損益＋実効税率を原本で潰す
python -m screener.cli special-items 1815 1799 1869.N

# テスト（ネットワーク不要）
pip install -r requirements-dev.txt
python -m pytest -q
```

Future100 リポジトリの場所は既定で `../Future100`。別の場所にあるときは
環境変数 `FUTURE100_DIR` か `--path` で指定する。

## 構成

| ファイル | 役割 |
|---|---|
| `screener/valuation.py` | 発見済み比・品質フロア・サイズ判定。**正常化ROE**と**会社予想ROEでの山検算**を持つ |
| `screener/cost_of_capital.py` | 市場ごとの株主資本コスト。未検証市場は `UnverifiedMarketError` で停止 |
| `screener/yahoo_jp.py` | finance.yahoo.co.jp から株価/PBR/BPS/ROE/時価総額を取得。**例外を投げない** |
| `screener/watchlist.py` | Future100 の `config/watchlist.yaml` を**コメント込み**で読む |
| `screener/candidates.py` | 発掘候補リスト。**証券コードは仮説として扱い、取得社名と突合して検証**（§8） |
| `screener/disclosure.py` | **決算短信の原本**へ到達し、特別損益・実効税率を拾って正常化ROEを出す |
| `screener/cli.py` | 上記を束ねるCLI |
| `config/cost_of_capital.yaml` | 市場ごとの資本コストと**その根拠・確認日** |
| `reports/` | 実行結果の記録（JSON） |
| `docs/` | スクリーニングの実施記録 |

## 設計上、意図的にこうしている点

**① B-4判定は必ず実績ROEで行う。** 予想ROEで妥当PBRを膨らませると発見済みを取り逃がす。
Future100側で東光高岳(6617)・ベイカレント(6532)の2回、同じ誤りが起きている。
予想ROEは `RoeInput.forecast_pct` に入れ、**「山」（循環ピーク）の検算にのみ**使う。
`screen()` は予想で引き直した比が実績比より2割以上悪化するか判定区分が変わると
「山リスク」フラグを立てる（合否は変えない）。

**② 一過性ROEは両方向に効く。** `RoeInput.normalized_pct` を渡すとそちらで比を計算する。

- 割高に見せる例＝品川リフラ(5351): 資産売却益込み実績26.6% → 正常化8%で比0.49→0.89
- 割安に見せる例＝日東紡(3110): 売却益込み実績27.54% → 正常化11.4%で比0.80→2.04

**②-b 嵩上げは特別損益欄の外でも起きる＝税。** フィックスターズ(3687)は
「前年同期に子会社の清算に伴う税金負担軽減があった」（原本）で実効税率19.9%→31.3%。
`valuation.TaxRateCheck` が**原本2期ぶんの実効税率**を比べ、当期が5pt以上低ければ
`roe_at_tax_rate()` で保守側（高いほうの税率）に引き直す。
**法定実効税率を記憶で置かない**——原本から取れる実績だけで判断する（§8）。
2026-08-21のF-4再検証で初適用し、さくらインターネット(3778)の当期実効税率3.90%を検出した。

**②-c 原本へのルートは2本要る。** `disclosure.py` は開示一覧を
Yahoo（`quote/<t>/disclosure`・**直近1年**）と kabupro（`ke.kabupro.jp`・**数年ぶん**）の
両方から引く。2026-08-21のF-4再検証では9社中4社（3月期・9月期・10月期の本決算）が
Yahoo側では期限切れで届かず、kabupro側で取れた。**片方だけでは半分に届かない。**
kabupro は cp932・`href` が引用符なし・httpsは証明書のホスト名不一致でhttpのみ、という3つの癖がある。

**③ 海外の資本コストを記憶で埋めない。** 10年国債利回りは時間とともに変わる。
`config/cost_of_capital.yaml` の `verified: false` な市場を指定すると例外で止まり、
使う日にWeb検索で当日値を確認して `risk_free_pct` / `asof` / `source` を埋めることを強制する。

**④ §0 — テクニカルは合否に使わない。** このリポジトリはテクニカル指標を計算も出力もしない。
（既存の `jp-stock-screener` の `combined_score` はテクニカル中心のため合否には流用しない。
同リポジトリは東証専用＝`.T`前提・`min_close_price=100`が円建て前提で、全世界株スコープにも合わない。）

**⑤ 取得失敗で全体を止めない。** `fetch_quote()` は例外を投げず `Quote.error` に格納する。
ただし **404は「上場廃止か取引所サフィックス誤り」として明示する**——Future100側で
前澤工業(6489・上場廃止)と愛知電機(名証なので`6623.N`)を「api都合」と誤診した実例があるため。

**⑥ 自動取得値を鵜呑みにしない。** `verified_fundamentals.bvps_yen` があれば
PBRを「その日の株価 ÷ BVPS」で毎回再計算する（Future100 `effective_pbr_roe()` と同じ契約）。

**⑦ 証券コードは仮説として扱う。** 発掘の初期は「たぶん東鉄工業は1835」からしか始められない。
`candidates` サブコマンドは取得ページの社名と突き合わせ、一致しなければ「コード未確認」として弾く。
2026-08-12にこれが2件を検知した——名工建設(1869)は`.T`が404で**名証(`1869.N`)**、
九電工(1959)は**コードが正しく社名のほうが古かった**（2025-10-01に「クラフティア」へ商号変更）。
不一致は「コードが違う」だけでなく「こちらの社名が古い」でも起きる。

**⑧ YAMLコメントを捨てない。** `leads_unverified` の却下理由はYAMLコメントとして
書かれておりパーサでは読めない。`screener/watchlist.py` が生テキストも走査して
「行末コメント＝個別理由」「直前のコメント塊＝節見出し」を復元する。

## 取得元について（2026-08-12 実測）

`yfinance`（query1.finance.yahoo.com）はサンドボックスから到達できないことがあるため、
`finance.yahoo.co.jp` のHTMLを直読みする。**Future100の引き継ぎには「HTML埋め込みJSONから
抽出する」と書かれているが、2026-08-12時点のページにそのJSONは存在しない**。現在は
サーバサイドレンダリングされたHTML（`_DataListItem_*` / `_CommonPriceBoard__price_*`）で、
`screener/yahoo_jp.py` はそちらを読む。構造が変わると `tests/test_yahoo_jp.py` が落ちる。

連続アクセスするとHTTP 500（レート制限）になるため**1件ごとに数秒スリープ＋リトライ**する
（既定4秒。9銘柄以上を続けて叩くと制限がかかることを実測で確認済み）。
名証銘柄は `.N`（例: 愛知電機 `6623.N`。`.T` は404）。

## Future100 との関係

- このリポジトリは Future100 の `config/*.yaml` を**読み取りのみ**で参照する。
- 積立額（`monthly_amount` / `sbi_actual` / `base_monthly_total_yen`）は**絶対に書き換えない**。
  昇格は必ずユーザーがSBIに設定してから、Future100側のセッションが記録する。
- ①一次確認が済んだ候補の記録は、Future100 の `config/watchlist.yaml` へ書き戻す
  （準一次か原本かを必ず明示する）。

---

*本リポジトリは個人用の運用支援であり投資助言ではない。判定は各社の一次情報のみを根拠とすること。*

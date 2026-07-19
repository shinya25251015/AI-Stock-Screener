# AI-Stock-Screener

AIを活用した日本株スクリーナー。東証主要銘柄を定量スクリーニング(バリュー・クオリティ・モメンタムの複合スコア)で絞り込み、Claude APIによるAI銘柄選定を行います。

## セットアップ

```bash
pip install -r requirements.txt
```

AI銘柄選定を使う場合は Anthropic APIキーを設定してください:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## 使い方

```bash
# Yahoo Financeから最新データを取得してスクリーニング + AI銘柄選定
python -m ai_stock_screener

# ネットワークやAPIキーがない場合: 同梱サンプルデータで定量ランキングのみ
python -m ai_stock_screener --source sample --no-ai

# オプション
python -m ai_stock_screener --top 15 --picks 5   # 上位15候補からAIが5銘柄選定
python -m ai_stock_screener --csv mydata.csv      # 任意のCSVを入力に使う
```

## 仕組み

1. **ユニバース**: 東証プライム主要30銘柄(`ai_stock_screener/universe.py`で編集可能)
2. **データ取得**: yfinanceでPER・PBR・配当利回り・ROE・利益率・3/6ヶ月リターンを取得
3. **定量スコアリング**: ユニバース内パーセンタイルで バリュー40% + クオリティ35% + モメンタム25% の複合スコアを算出
4. **AI銘柄選定**: 上位候補をClaude(既定: `claude-opus-4-8`)に渡し、選定理由・リスク付きで銘柄を選定(日本語出力)

## 開発

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

## 免責事項

本ツールの出力は情報提供のみを目的としており、投資助言ではありません。投資判断はご自身の責任で行ってください。

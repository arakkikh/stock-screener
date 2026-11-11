# 株スクリーナー

日本株と米国株を対象にした、個人用の株スクリーナーです。

- 逆張りモード: TOPIX Core30 + Large70 ／ S&P 100
- 順張りモード（ミネルヴィニ式）: TOPIX 500 ／ S&P 500
売買の自動執行はしません。判断材料を表示するだけです。

**このサイトは投資助言ではありません。最終判断は自己責任で行ってください。**

## 仕組み

1. GitHub Actions が毎営業日の引け後に株価を取得し、判定結果を `docs/data/` の JSON に保存します。
   - 日本株: 平日 16:30 JST（予備 18:30）
   - 米国株: 火〜土 7:30 JST（予備 9:30）
2. GitHub Pages が `docs/` を公開します。画面は JSON を読んで表示するだけです。
3. ポジションやトレード記録は、見ている端末のブラウザの中にだけ保存されます（このリポジトリには入りません）。

## フォルダ

| 場所 | 内容 |
|---|---|
| `config/thresholds.yaml` | しきい値。すべてここに集約。`jp:` / `us:` に書くと市場ごとに上書きできる |
| `config/universe_jp.csv`, `universe_us.csv` | 逆張りの対象銘柄。`themes` 列にテーマを `|` 区切りで書ける |
| `config/universe_jp_momentum.csv`, `universe_us_momentum.csv` | 順張りの対象銘柄 |
| `screener/` | 判定ロジック（市場に依存しない）。順張りは `momentum.py` |
| `markets/` | 市場ごとの違いとデータ取得 |
| `scripts/update.py` | データ更新 |
| `scripts/build_universe.py` | 銘柄リストを公式の構成銘柄から作り直す |
| `docs/` | 公開される画面とデータ |
| `tests/` | テスト |

## よく使う操作（ターミナルで、このフォルダに移動してから）

```
# 最初の1回だけ: 作業用の環境を作る
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install webkit

# テスト
.venv/bin/python -m pytest -q

# 手元でデータを更新（--force で作り直し）
.venv/bin/python scripts/update.py --market jp
.venv/bin/python scripts/update.py --market us

# 手元で画面を見る → ブラウザで http://localhost:8000
python3 -m http.server 8000 --directory docs

# 銘柄の入れ替えを反映（momentum を付けると順張り用）
.venv/bin/python scripts/build_universe.py jp
.venv/bin/python scripts/build_universe.py jp momentum
```

## しきい値を変えるには

`config/thresholds.yaml` を書き換えて保存し、GitHub に反映（push）します。次のデータ更新から新しい値で判定されます。
「仮置き」と書いてある値は、バックテスト（フェーズ4）で見直す前提のものです。

## 順張りモードについて

- トレンドテンプレート8条件、相対強度（RS）、VCP を判定します。しきい値は `config/thresholds.yaml` の `momentum:` にあります。
- チャート用のデータと決算日は、8条件すべてに合格した銘柄だけ作ります（リポジトリが大きくなりすぎないようにするため）。
- 順張りの更新に失敗しても、逆張りの結果は保存されます。

## データについて

- 株価・指数・VIX・為替・決算予定日は Yahoo Finance（yfinance 経由、非公式）。遅れや誤りを含むことがあります。
- 日経VI と Fear & Greed は自動取得していません。画面で手入力します。
- チャートは TradingView Lightweight Charts（Apache License 2.0）を同梱しています。

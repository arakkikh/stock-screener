# 株スクリーナー

日本株と米国株を対象にした、個人用の株スクリーナーです。

- 逆張りモード: TOPIX Core30 + Large70 ／ S&P 100
- 順張りモード（ミネルヴィニ式）: TOPIX 500 ／ S&P 500
- ファンダ分析（5軸のレーダーチャート）: TOPIX 500 ／ S&P 500
売買の自動執行はしません。判断材料を表示するだけです。

**このサイトは投資助言ではありません。最終判断は自己責任で行ってください。**

## 仕組み

1. GitHub Actions が毎営業日の引け後に株価を取得し、判定結果を `docs/data/` の JSON に保存します。
   - 日本株: 平日 16:30 JST（予備 18:30）
   - 米国株: 火〜土 7:30 JST（予備 9:30）
2. 財務データは週1回（土曜 11:00 JST）取得し、`data/` に保存します。PER など株価で変わる指標は毎日計算し直します。
3. GitHub Pages が `docs/` を公開します。画面は JSON を読んで表示するだけです。
4. ポジションやトレード記録は、見ている端末のブラウザの中にだけ保存されます（このリポジトリには入りません）。

## フォルダ

| 場所 | 内容 |
|---|---|
| `config/thresholds.yaml` | しきい値。すべてここに集約。`jp:` / `us:` に書くと市場ごとに上書きできる |
| `config/universe_jp.csv`, `universe_us.csv` | 逆張りの対象銘柄。`themes` 列にテーマを `|` 区切りで書ける |
| `config/universe_jp_momentum.csv`, `universe_us_momentum.csv` | 順張りの対象銘柄 |
| `screener/` | 判定ロジック（市場に依存しない）。順張りは `momentum.py`、ファンダ分析は `fundamentals.py` |
| `markets/` | 市場ごとの違いとデータ取得 |
| `scripts/update.py` | データ更新（毎日） |
| `scripts/update_fundamentals.py` | 財務データの取得（週1回） |
| `scripts/run_backtest.py` | バックテスト（手動で実行） |
| `data/` | 取得した財務データ（採点のもと。画面には直接出ない） |
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

## ファンダ分析について

- 割安度・成長・過去実績・財務健全性・配当の5軸を、それぞれ6項目のチェックで採点します。しきい値は `config/thresholds.yaml` の `fundamentals:` にあります。
- 割安度は他の銘柄との比較で、理論株価（DCF）の計算はしていません。成長はアナリスト予想にもとづきます。
- 銀行・保険などの金融業は、財務健全性などの一部の項目を判定しません。
- 点数は参考情報で、逆張り・順張りの候補判定には使っていません。
- 財務データを手元で取り直すには: `.venv/bin/python scripts/update_fundamentals.py --market jp` のあと `.venv/bin/python scripts/update.py --market jp --mode fundamentals`

## バックテストについて

- 過去10年の日足で、各サインが出たあとの成績を集計します。結果は画面の「検証結果」で見られます。
- 自動では実行しません。しきい値を見直したいときに手元で実行します（1市場あたり3〜4分）。
  ```
  .venv/bin/python scripts/run_backtest.py --market jp
  .venv/bin/python scripts/run_backtest.py --market us
  ```
- 古い8年でしきい値を選び、直近2年で通用するかを確かめる、という見方をします。しきい値は自動では書き換えません。
- 限界: 今の構成銘柄だけで検証しているため、成績は実際より良く出ます。手数料・税金・売買時の価格のずれも含みません。

## データについて

- 株価・指数・VIX・為替・決算予定日・財務データ・アナリスト予想は Yahoo Finance（yfinance 経由、非公式）。遅れや誤りを含むことがあります。
- 取得元のデータには、株式分割が過去の株価に反映されていない・値が壊れている、といった異常がまれにあります。そうした「断絶」より前の履歴は使いません（`markets/fetch.py` の `drop_before_break`）。
- 日経VI と Fear & Greed は自動取得していません。画面で手入力します。
- チャートは TradingView Lightweight Charts（Apache License 2.0）を同梱しています。

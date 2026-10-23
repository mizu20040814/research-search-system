## Code Review Rules

### 全般
- レビューコメントは日本語で書く

### 実験の再現性
- 乱数シードの固定を外す変更や、絶対パスのハードコードを指摘する。
  安全な形: このリポジトリに設定ファイルはなく、入出力は各スクリプトのコマンドライン引数（argparse）で渡す（例: `python -m confprog.generic <URL> --conference ANLP --html data/raw/xxx.html --out data/out/xxx.json`、`python -m confprog.trial --targets eval/trial_targets.csv`）。既定値はリポジトリ直下からの相対パス（`data/raw/`・`data/out/`・`eval/`）にする。乱数を使う処理を足すときは、シードを `--seed` のような引数で受け取り既定値を固定する。

### データ処理
- 評価用データが学習や前処理に混入する変更（データリーク）を指摘する。
  このリポジトリでは、正解データ `eval/gold_*.csv` は `confprog.evaluate` で比べるときだけ読み、抽出処理（`confprog/generic.py` など）からは読まない。MIRU・ANLP は開発用で調整に使ってよいが、評価用の大会（MIRU・ANLP 以外の未見の大会）の正解や結果を見て抽出規則やしきい値を調整する変更は指摘する。また、学会別抽出器（`confprog/extractors/`）の出力をそのまま正解にしない。
- 入力データを上書き・破壊する処理を指摘する。
  安全な形: 処理結果は別のファイルやディレクトリに出力する。取得した HTML のキャッシュ（`data/raw/`・`data/rendered/`）は `confprog/fetch.py`・`confprog/render.py` 以外から書き換えたり消したりせず、正解データ（`eval/gold_*.csv`）は読むだけにする。抽出・評価の結果は `data/out/` 以下（`--out` で指定）に書く。

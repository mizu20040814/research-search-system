# Research-system（学会プログラム横断検索・卒業研究）

分散した学会プログラムを収集し、共通形式の JSON に構造化するプログラムです。

> 2026-10-07：`confprog/extractors/` の学会別抽出器（MIRU・ANLP）は**正解データ作成の補助と開発用**です。
> 研究の本体は、学会ごとの個別実装なしにプログラムを抽出する汎用手法 `confprog/generic.py`（構造推定）。方針は `CLAUDE.md`。

## 導入

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

- Python 3.10 以上。学会別抽出器と評価は標準ライブラリだけで動きます
- playwright は汎用抽出の描画に使います。入れたあとに `python -m playwright install chromium` を実行します
- numpy・sentence-transformers は関連度（`rank`・`demo`）で使います。モデル `intfloat/multilingual-e5-base`（約1.1GB）は初回に自動で取得されます
- `requirements.txt` は Windows の pip が文字コード（cp932）で読めるよう、英数字だけで書いています

## 汎用の抽出（構造推定・基準手法）

どの学会にも同じ方法をかけます。学会ごとのタグ名・クラス名は持たず、描画後の HTML で繰り返し現れる欄から
タイトル・著者・発表番号・セッション名を推定します（仕組みは `confprog/generic.py` の冒頭）。

```powershell
# 初回だけ：ページを描画するためのブラウザを入れる
pip install playwright
python -m playwright install chromium

# プログラムページの URL を渡す → data/out/generic_miru2026.json
python -m confprog.generic https://miru-committee.github.io/miru2026/program/timetable/ --conference MIRU --year 2026
python -m confprog.generic https://www.anlp.jp/proceedings/annual_meeting/2026/ --conference ANLP --year 2026

# 正解データと比べる（--show で取りこぼし・余分・属性違いを表示）
python -m confprog.evaluate data/out/generic_miru2026.json eval/gold_miru2026.csv --show
# ページ全体を学会別抽出器の出力と比べる（参考値）
python -m confprog.evaluate data/out/generic_miru2026.json data/out/miru2026.json --all
```

本体の HTML は `fetch()`（robots.txt・7秒間隔・`data/raw/`）で取り、描画後の HTML は `data/rendered/` に保存します。

## プログラムページの特定（大会トップURL → 発表一覧ページ）

```bash
# 1大会：見つけたページと、たどった記録（各ページの点数・判定・理由）を表示 → data/out/locate/single.json
python -m confprog.locate https://www.anlp.jp/nlp2026/
# 学会リスト（eval/conferences.csv の 学会,年,トップURL,メモ）を全部 → data/out/locate/<学会><年>.json と summary.csv
python -m confprog.locate --list eval/conferences.csv
```

リンクを「プログラム」などの一般的な語で点数づけして2段までたどり、抽出器が発表一覧と判定したページを返します。
リンク先も発表一覧のページ（目次・セッション一覧）は「ハブ」とみなし、リンク先のほうを返します。
設計は Vault の `01_Research/卒論テーマ_関連資料/プログラムページ特定_設計_2026-10-25.md`。

## 一括実行とデモ（学会リスト → 発表DB → 関連度）

```powershell
# 学会リスト（eval/conferences.csv）の全学会について、ページ特定 → 各ページの汎用抽出 → 発表DB まで
python -m confprog build
python -m confprog build --only MIRU ANLP      # 一部だけ流す（ほかの学会は前回分を使う）

# 研究課題文を続けて入れて、関連する発表を見る（モデルは起動時に1回だけ読む）
python -m confprog demo
python -m confprog demo --top 20 --with-session

# 1件だけ調べる・発表DBだけ作り直す
python -m confprog rank "研究課題の文章"
python -m confprog db build --out-dir data/out/batch
```

- `build` はページごとの抽出結果を `data/out/batch/generic_<学会><年>_<番号>.json`、ページ特定の記録を `locate_<学会><年>.json` に書き、最後に `data/db/presentations.jsonl` を作ります
- 学会ごとの結果は `data/out/batch/summary.csv` に出ます。状態は次の4つです
  - 成功：今回の結果に入れ替えた
  - 前回分を使用：今回は失敗したので、前回の結果をそのまま使った
  - 失敗（前回分なし）：今回も失敗し、前回の結果もない（発表DBに入らない）
  - 前回分：今回は流していない（`--only` で外した）
- 描画したページは `data/rendered/` にキャッシュされるので、2回目以降は新しいページの分しか時間がかかりません。初回は6大会で約1時間です
- `demo` では、課題文を入れて空行（Enter を2回）で検索します。`:top N` で表示件数を変え、`:q` か Ctrl+C で終わります。結果は1件ごとに `data/runs/` に保存されます

## 学会別抽出器（正解データ作りの補助。Python 3.10 以上、追加ライブラリ不要）

```powershell
# 1. MIRU 2026 のタイムテーブルを取得して抽出 → data/out/miru2026.json
python -m confprog miru --year 2026
python -m confprog anlp --year 2026     # ANLP(言語処理学会)→ data/out/anlp2026.json

# ページを保存するだけ(新しい学会の HTML を調べるとき)
python -m confprog.fetch <URL>

# 2. 2回目以降は data/raw/ のキャッシュを使う（通信しない）。取り直すときは
python -m confprog miru --year 2026 --refresh

# 3. 保存済みの HTML から抽出する
python -m confprog miru --html data/raw/<ファイル名>.html

# テスト
python -m unittest discover -s tests -v
```

実行すると、抽出件数・セッション数・著者が空の件数と、先頭3件が表示されます。

## 出力スキーマ

ノートで確定したスキーマ `{学会, 大会, 年, セッション, タイトル, 著者[], URL}` に対応します。

| キー | 意味 | 例 |
|---|---|---|
| `conference` | 学会 | `MIRU` |
| `event` | 大会 | `MIRU2026` |
| `year` | 年 | `2026` |
| `session` | セッション | `オーラル1：認識` |
| `title` | タイトル | |
| `authors` | 著者（所属を除いた氏名のリスト） | `["山田 太郎", "佐藤 花子"]` |
| `url` | 発表へのリンク（無ければ `null`） | |

評価（RQ1）用の補助情報として `presentation_id`, `date`, `time`, `affiliations`, `authors_raw`（分割前の著者文字列）, `source_url` も保存します。

## 構成

```
confprog/
  schema.py            共通スキーマ（Presentation）
  fetch.py             取得（robots.txt 確認・7秒間隔・キャッシュ・UA 明示）
  authors.py           著者文字列 → 氏名リスト／所属リスト
  generic.py           汎用の抽出（構造推定）と発表一覧かどうかの判定
  links.py             ページ特定：リンクの収集と点数づけ
  locate.py            ページ特定：トップURLから発表一覧ページをたどる
  extractors/miru.py   MIRU の抽出器
  __main__.py          コマンド
tests/                 テスト（架空データの HTML で動作確認）
data/raw/, data/out/   取得した HTML と抽出結果（Git 管理外）
```

## MIRU の抽出方法

MIRU2026 のサイトは Hugo 製です。プログラムは Google スプレッドシートの内容がビルド時に
ページ内の `<script>` に JSON（`embeddedScheduleData` / `embeddedPresentationsData` /
`embeddedSessionItemsData`）として埋め込まれ、Vue で表示されます。
そのため HTML の表を解析するのではなく、この JSON を取り出して結合しています
（結合ルールはページの表示用 JS に合わせています）。
本番ページは JS が圧縮されていてデータが厳密な JSON ではない（キーに引用符が無い、`true` が `!0` など）ため、
`confprog/jsliteral.py` の小さなパーサーで読み取っています。

2026-10-07 時点の結果：1280 枠（異なる発表 991 件）、30 セッション。著者が空の 157 枠は企業展示と交流会です。

## ANLP の抽出方法

静的 HTML で、全プログラムが1ページにあります。「一般発表」以降のセッション見出し（`session_title`）と、
発表ごとの2行（発表番号＋タイトル／PDFリンク＋著者）を読み取っています。
チュートリアル・招待講演・招待論文は書式が違うため、今は対象外です。

2026-10-07 時点の結果（NLP2026）：829 枠（異なる発表 797 件）、49 セッション、著者が空の発表 0 件。
口頭発表セッション（A1 など）にはポスター発表の再掲が含まれるため、枠と発表の数が違います。

## 新しい学会を足すとき

`confprog/extractors/<学会>.py` に `CONFERENCE`, `DEFAULT_URL`, `ExtractError`,
`extract(html, source_url, year) -> list[Presentation]` を書き、`extractors/__init__.py` の `REGISTRY` に登録します。

## アクセスマナー

- robots.txt を確認し、Disallow のページは取得しない
- 同じサイトへのアクセスは 7 秒以上空ける（IEICE の Crawl-delay: 7 に合わせた共通基準）
- 取得した HTML はキャッシュし、同じページを何度も取りに行かない
- 取得データは研究目的に限り、再配布の可否が未確認なので Git にはコミットしない

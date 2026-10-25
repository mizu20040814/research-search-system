"""発表DBの作成と関連度ランキングのコマンド。

  python -m confprog db build                          # data/out/generic_*.json から発表DBを作る
  python -m confprog rank "研究課題の文章" [--top 20]   # 関連する発表を並べる
  python -m confprog rank --query-file 課題.txt [--model M] [--with-session]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from .db import DEFAULT_DB_PATH, DEFAULT_OUT_DIR, build_db, db_hash, load_db

# relevance は numpy を読むので、db build だけのときは読み込まない
DEFAULT_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_CACHE_DIR = Path("data/db/emb")
DEFAULT_RUNS_DIR = Path("data/runs")


def _default_factory(model: str):
    from .relevance import load_sentence_transformer
    return load_sentence_transformer(model)


def _positive(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("1 以上を指定してください")
    return n


def _authors(names: list[str]) -> str:
    return ", ".join(names[:3]) + (" ほか" if len(names) > 3 else "")


def main(argv: list[str], embed_factory: Callable[[str], Callable] = _default_factory,
         db_path: Path = DEFAULT_DB_PATH, out_dir: Path = DEFAULT_OUT_DIR,
         cache_dir: Path = DEFAULT_CACHE_DIR, runs_dir: Path = DEFAULT_RUNS_DIR) -> int:
    ap = argparse.ArgumentParser(prog="confprog")
    sub = ap.add_subparsers(dest="cmd", required=True)
    db = sub.add_parser("db", help="発表DBを作る")
    db.add_argument("action", choices=["build"])
    rk = sub.add_parser("rank", help="研究課題の文章に関連する発表を並べる")
    rk.add_argument("query", nargs="?", default="", help="研究課題の文章")
    rk.add_argument("--query-file", type=Path, help="研究課題の文章を書いたファイル(UTF-8)")
    rk.add_argument("--top", type=_positive, default=20)
    rk.add_argument("--model", default=DEFAULT_MODEL)
    rk.add_argument("--with-session", action="store_true", help="タイトルにセッション名を足して埋め込む")
    args = ap.parse_args(argv)

    if args.cmd == "db":
        records, warnings = build_db(out_dir, db_path)
        counts = Counter((r["event"], r["kind"]) for r in records)
        for event in sorted({r["event"] for r in records}):
            print(f"{event}: 一般 {counts[(event, 'general')]} / 招待 {counts[(event, 'invited')]}"
                  f" / チュートリアル {counts[(event, 'tutorial')]}")
        for w in warnings:
            print(f"警告: {w}", file=sys.stderr)
        print(f"発表DB: {len(records)} 件 → {db_path}")
        return 0

    try:
        query = args.query_file.read_text(encoding="utf-8-sig") if args.query_file else args.query
    except FileNotFoundError:
        print(f"エラー: {args.query_file} が見つかりません", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print(f"エラー: {args.query_file} を読めません。UTF-8 で保存してください", file=sys.stderr)
        return 1
    query = query.strip()
    if not query:
        print("エラー: 研究課題の文章が空です", file=sys.stderr)
        return 1
    if not db_path.exists():
        print(f"エラー: 発表DB {db_path} がありません。先に python -m confprog db build を実行してください",
              file=sys.stderr)
        return 1
    try:
        embed = embed_factory(args.model)
    except ImportError:
        print("エラー: sentence-transformers が入っていません。pip install sentence-transformers を実行してください",
              file=sys.stderr)
        return 1
    except Exception as e:  # ネットワーク・プロキシ・モデル名の誤りなど、ライブラリごとに例外の型が違う
        print(f"エラー: モデル {args.model} を読めませんでした: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    from .relevance import load_or_build_embeddings, method_name, rank, save_run

    records = load_db(db_path)
    if not records:
        print(f"エラー: 発表DB {db_path} が空です。data/out に抽出結果を置いて db build し直してください", file=sys.stderr)
        return 1
    digest = db_hash(db_path)
    emb = load_or_build_embeddings(records, digest, args.model, args.with_session, embed, cache_dir)
    if hasattr(embed, "warn_if_long"):
        embed.warn_if_long(query)
    results = rank(query, records, emb, args.model, embed, args.top)
    for r in results:
        print(f"{r['rank']:>2}. {r['score']:.3f} [{r['event']}] {r['title']} / {_authors(r['authors'])}")
        print(f"    {r['session'] or ''}")
    path = save_run(query, method_name(args.model, args.with_session), digest, args.top, results, runs_dir)
    print(f"保存先: {path}")
    return 0

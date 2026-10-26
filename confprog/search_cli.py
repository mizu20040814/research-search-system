"""発表DBの作成と関連度ランキングのコマンド。

  python -m confprog db build                          # data/out/generic_*.json から発表DBを作る
  python -m confprog rank "研究課題の文章" [--top 20]   # 関連する発表を並べる
  python -m confprog rank --query-file 課題.txt [--model M] [--with-session]
  python -m confprog demo [--top 10]                    # モデルを1回だけ読み、課題文を続けて受け付ける
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Iterator, TextIO

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


def read_query(lines: Iterator[str]) -> str | None:
    """空行までの行をつないで1件の課題文にする。空行だけなら ""、行が尽きて何もなければ None。
    最初の行が ":" で始まるときはコマンド(:q・:top N)として、その1行だけを返す。"""
    got: list[str] = []
    for line in lines:
        if not line.strip():
            return "\n".join(got).strip()
        if not got and line.lstrip().startswith(":"):
            return line.strip()
        got.append(line.rstrip("\n"))
    return "\n".join(got).strip() if got else None


def breakdown(results: list[dict]) -> str:
    counts = Counter(r["event"] for r in results)
    parts = "／".join(f"{e} {n}件" for e, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return f"上位{len(results)}件の内訳：{parts}"


def _print_results(results: list[dict]) -> None:
    for r in results:
        print(f"{r['rank']:>2}. {r['score']:.3f} [{r['event']}] {r['title']} / {_authors(r['authors'])}")
        print(f"    {r['session'] or ''}")


def _load_embed(model: str, embed_factory: Callable[[str], Callable]) -> Callable | None:
    try:
        return embed_factory(model)
    except ImportError:
        print("エラー: sentence-transformers が入っていません。pip install sentence-transformers を実行してください",
              file=sys.stderr)
    except Exception as e:  # ネットワーク・プロキシ・モデル名の誤りなど、ライブラリごとに例外の型が違う
        print(f"エラー: モデル {model} を読めませんでした: {type(e).__name__}: {e}", file=sys.stderr)
    return None


def _load_records(db_path: Path) -> list[dict] | None:
    if not db_path.exists():
        print(f"エラー: 発表DB {db_path} がありません。先に python -m confprog db build を実行してください",
              file=sys.stderr)
        return None
    records = load_db(db_path)
    if not records:
        print(f"エラー: 発表DB {db_path} が空です。data/out に抽出結果を置いて db build し直してください", file=sys.stderr)
        return None
    return records


BREAKDOWN_TOP = 50  # デモで学会別の内訳を数える件数


def _demo(args, embed_factory: Callable[[str], Callable], stdin: TextIO) -> int:
    started = time.monotonic()
    records = _load_records(args.db)
    if records is None:
        return 1
    embed = _load_embed(args.model, embed_factory)
    if embed is None:
        return 1
    from .relevance import load_or_build_embeddings, method_name, rank, save_run

    digest = db_hash(args.db)
    emb = load_or_build_embeddings(records, digest, args.model, args.with_session, embed, args.cache_dir)
    events = sorted({r["event"] for r in records})
    print(f"準備完了：{len(records)}件（{', '.join(events)}）、{time.monotonic() - started:.1f}秒")
    top = args.top
    lines = iter(stdin.readline, "")
    try:
        while True:
            print("研究課題文（空行で検索、:q で終了）>", flush=True)
            query = read_query(lines)
            if query is None or query == ":q":
                return 0
            if query.startswith(":top"):
                n = query[4:].strip()
                if n.isdigit() and int(n) >= 1:
                    top = int(n)
                    print(f"表示件数: {top}")
                else:
                    print("使い方: :top N（N は1以上）")
                continue
            if not query:
                continue
            if hasattr(embed, "warn_if_long"):
                embed.warn_if_long(query)
            results = rank(query, records, emb, args.model, embed, max(top, BREAKDOWN_TOP))
            _print_results(results[:top])
            print(breakdown(results[:BREAKDOWN_TOP]))
            save_run(query, method_name(args.model, args.with_session), digest, top, results[:top], args.runs_dir)
    except KeyboardInterrupt:
        print()
        return 0


def main(argv: list[str], embed_factory: Callable[[str], Callable] = _default_factory,
         db_path: Path = DEFAULT_DB_PATH, out_dir: Path = DEFAULT_OUT_DIR,
         cache_dir: Path = DEFAULT_CACHE_DIR, runs_dir: Path = DEFAULT_RUNS_DIR, stdin: TextIO | None = None) -> int:
    ap = argparse.ArgumentParser(prog="confprog")
    sub = ap.add_subparsers(dest="cmd", required=True)
    db = sub.add_parser("db", help="発表DBを作る")
    db.add_argument("action", choices=["build"])
    db.add_argument("--out-dir", type=Path, default=out_dir, help=f"抽出結果のディレクトリ(既定: {out_dir})")
    db.add_argument("--db", type=Path, default=db_path, help=f"発表DBの保存先(既定: {db_path})")
    rk = sub.add_parser("rank", help="研究課題の文章に関連する発表を並べる")
    rk.add_argument("query", nargs="?", default="", help="研究課題の文章")
    rk.add_argument("--query-file", type=Path, help="研究課題の文章を書いたファイル(UTF-8)")
    rk.add_argument("--top", type=_positive, default=20)
    rk.add_argument("--model", default=DEFAULT_MODEL)
    rk.add_argument("--with-session", action="store_true", help="タイトルにセッション名を足して埋め込む")
    rk.add_argument("--db", type=Path, default=db_path, help=f"発表DB(既定: {db_path})")
    rk.add_argument("--cache-dir", type=Path, default=cache_dir, help=f"埋め込みのキャッシュ(既定: {cache_dir})")
    rk.add_argument("--runs-dir", type=Path, default=runs_dir, help=f"結果の保存先(既定: {runs_dir})")
    dm = sub.add_parser("demo", help="モデルを1回だけ読み、研究課題文を続けて受け付ける")
    dm.add_argument("--top", type=_positive, default=10)
    dm.add_argument("--model", default=DEFAULT_MODEL)
    dm.add_argument("--with-session", action="store_true", help="タイトルにセッション名を足して埋め込む")
    dm.add_argument("--db", type=Path, default=db_path, help=f"発表DB(既定: {db_path})")
    dm.add_argument("--cache-dir", type=Path, default=cache_dir, help=f"埋め込みのキャッシュ(既定: {cache_dir})")
    dm.add_argument("--runs-dir", type=Path, default=runs_dir, help=f"結果の保存先(既定: {runs_dir})")
    args = ap.parse_args(argv)
    db_path = args.db
    if args.cmd == "demo":
        return _demo(args, embed_factory, stdin or sys.stdin)

    if args.cmd == "db":
        records, warnings = build_db(args.out_dir, db_path)
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
        _load_records(db_path)
        return 1
    embed = _load_embed(args.model, embed_factory)
    if embed is None:
        return 1

    from .relevance import load_or_build_embeddings, method_name, rank, save_run

    records = _load_records(db_path)
    if records is None:
        return 1
    digest = db_hash(db_path)
    emb = load_or_build_embeddings(records, digest, args.model, args.with_session, embed, args.cache_dir)
    if hasattr(embed, "warn_if_long"):
        embed.warn_if_long(query)
    results = rank(query, records, emb, args.model, embed, args.top)
    _print_results(results)
    path = save_run(query, method_name(args.model, args.with_session), digest, args.top, results, args.runs_dir)
    print(f"保存先: {path}")
    return 0

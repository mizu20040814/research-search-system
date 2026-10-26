"""使い方:
  python -m confprog miru --year 2026                 # 取得して data/out/miru2026.json に保存
  python -m confprog miru --html data/raw/xxx.html    # 保存済み HTML から抽出(通信しない)
  python -m confprog miru --year 2026 --refresh       # キャッシュを無視して取り直す
  python -m confprog build                            # 学会リスト(eval/conferences.csv)から発表DBまで一括で作る
  python -m confprog db build                         # 抽出結果から発表DB(data/db/presentations.jsonl)を作る
  python -m confprog demo                             # 研究課題文を続けて入れて関連する発表を見る(対話式)
  python -m confprog rank "研究課題の文章"             # 関連する発表を並べる(詳しくは search_cli.py)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .extractors import REGISTRY
from .fetch import FetchError, fetch


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Windows のコンソール(cp932)で表示できない文字があっても落ちないようにする
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if argv and argv[0] == "build":
        from .pipeline import main as build_main
        return build_main(argv)
    if argv and argv[0] in ("db", "rank", "demo"):
        from .search_cli import main as search_main
        return search_main(argv)
    ap = argparse.ArgumentParser(prog="confprog", description="学会プログラムを共通形式の JSON にする")
    ap.add_argument("conference", choices=sorted(REGISTRY), help="対象の学会")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--url", help="プログラムページの URL(省略時は学会ごとの既定 URL)")
    ap.add_argument("--html", type=Path, help="保存済み HTML ファイルから抽出する")
    ap.add_argument("--out", type=Path, help="出力先(既定: data/out/<学会><年>.json)")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを使わずに取り直す")
    args = ap.parse_args(argv)

    module = REGISTRY[args.conference]
    url = args.url or module.DEFAULT_URL.format(year=args.year)

    if args.html:
        html = args.html.read_text(encoding="utf-8")
    else:
        print(f"取得中: {url}", file=sys.stderr)
        try:
            html = fetch(url, refresh=args.refresh)
        except FetchError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1

    try:
        items = module.extract(html, source_url=url, year=args.year)
    except module.ExtractError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    out = args.out or Path("data/out") / f"{args.conference}{args.year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "conference": module.CONFERENCE,
        "year": args.year,
        "source_url": url,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(items),
        "presentations": [p.to_dict() for p in items],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 目視チェック用のまとめ
    # 同じ発表がオーラルとインタラクティブの両方に載ることがあるので、枠の数と発表の数を分けて出す
    sessions = Counter(p.session for p in items)
    unique = {p.presentation_id or p.title for p in items}
    no_author = Counter(p.session for p in items if not p.authors)
    print(f"抽出件数: {len(items)} 枠 / 異なる発表: {len(unique)} 件 / セッション数: {len(sessions)}")
    print(f"著者が空の枠: {sum(no_author.values())} 件 {dict(no_author)}")
    for p in items[:3]:
        print(f"  - [{p.session}] {p.title} / {', '.join(p.authors)}")
    print(f"保存先: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

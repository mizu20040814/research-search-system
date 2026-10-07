"""汎用抽出を複数の学会に試しにかけ、結果を一覧にする。

使い方:
  python -m confprog.trial                       # eval/trial_targets.csv の全件
  python -m confprog.trial --only YANS IEICE     # 一部だけ

各ページの結果は data/out/trial/<学会>_<番号>.json、一覧は data/out/trial/summary.csv に保存する。
1件が失敗しても残りは続ける。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from pathlib import Path

from .fetch import FetchError
from .generic import extract
from .render import RenderError, render

OUT = Path("data/out/trial")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="confprog.trial")
    ap.add_argument("--targets", type=Path, default=Path("eval/trial_targets.csv"))
    ap.add_argument("--only", nargs="*", help="学会名で絞る")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    with args.targets.open(encoding="utf-8-sig", newline="") as f:
        targets = list(csv.DictReader(f))
    if args.only:
        targets = [t for t in targets if t["学会"] in args.only]

    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, t in enumerate(targets, 1):
        name, year, url = t["学会"], int(t["年"]), t["URL"]
        print(f"[{i}/{len(targets)}] {name} {url}", flush=True)
        row = {"no": i, "conference": name, "url": url, "status": "ok"}
        try:
            html = render(url)
            items, inf = extract(html, name, year, url)
            d = inf.describe()
            row.update({
                "count": len(items),
                "unique_titles": len({p.title for p in items}),
                "no_author": sum(not p.authors for p in items),
                "no_session": sum(not p.session for p in items),
                "title_path": d["title_path"], "author_path": d["author_path"],
                "id_path": d["id_path"], "session_path": d["session_path"],
                "sample": " | ".join(p.title[:40] for p in items[:3]),
            })
            (OUT / f"{name.lower()}_{i}.json").write_text(json.dumps({
                "conference": name, "year": year, "source_url": url, "inference": d,
                "count": len(items), "presentations": [p.to_dict() for p in items],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"    {len(items)} 件 / 著者なし {row['no_author']} / タイトル欄 {d['title_path']}")
            for p in items[:2]:
                print(f"    - [{p.session[:20]}] {p.presentation_id or ''} {p.title[:50]} / {', '.join(p.authors[:3])}")
        except (FetchError, RenderError, ValueError) as e:
            row.update(status="error", error=str(e)[:300])
            print(f"    エラー: {e}")
        except Exception as e:  # 想定外でも残りは続ける
            row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
            traceback.print_exc()
        rows.append(row)

    keys = ["no", "conference", "status", "count", "unique_titles", "no_author", "no_session",
            "title_path", "author_path", "id_path", "session_path", "sample", "url", "error"]
    with (OUT / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"一覧: {OUT / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""抽出結果を正解データと比べて精度を出す。

使い方:
  python -m confprog.evaluate <予測.json> eval/gold_miru2026.csv            # 正解データ(一部のセッション)と比べる
  python -m confprog.evaluate <予測.json> eval/gold_miru2026.csv --show     # 取りこぼし・余分・著者違いも表示
  python -m confprog.evaluate <予測.json> data/out/miru2026.json --all      # ページ全体を学会別抽出器の出力と比べる(参考値)

正解データは一部のセッションだけを完全に書き出したもの。そこで予測のうち
「正解と同じセッションに入っているもの」だけを比べる(セッション名は前方一致)。

- 掲載枠：同じ発表が複数のセッションに載る場合は、載った回数ぶん数える
- 固有の発表：タイトルが同じものは1件と数える
- タイトルの照合は NFKC・小文字化・空白除去だけを行う(記号は残す)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path


def norm_title(text: str | None) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", "", s)


def norm_session(text: str | None) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\W_]+", "", s)


def norm_name(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def load(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        rows = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("確認") or "").strip().lower() == "exclude":
                    continue
                rows.append({
                    "session": r.get("セッション", ""),
                    "presentation_id": r.get("発表ID") or None,
                    "title": r.get("タイトル", ""),
                    "authors": [a.strip() for a in (r.get("著者") or "").split(";") if a.strip()],
                })
        return rows
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["presentations"] if isinstance(data, dict) else data


def in_scope(pred: list[dict], gold: list[dict]) -> list[dict]:
    sessions = {norm_session(g["session"]) for g in gold if g.get("session")}
    return [p for p in pred if any(norm_session(p.get("session")).startswith(s) for s in sessions)]


def _prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def evaluate(pred: list[dict], gold: list[dict], whole_page: bool = False) -> dict:
    scoped = pred if whole_page else in_scope(pred, gold)
    pc = Counter(norm_title(p["title"]) for p in scoped)
    gc = Counter(norm_title(g["title"]) for g in gold)
    tp_slots = sum((pc & gc).values())
    tp_unique = len(set(pc) & set(gc))

    pred_by = {norm_title(p["title"]): p for p in scoped}
    gold_by = {norm_title(g["title"]): g for g in gold}
    matched = set(pred_by) & set(gold_by)
    author_bad = [
        t for t in matched
        if [norm_name(a) for a in pred_by[t].get("authors", [])] != [norm_name(a) for a in gold_by[t].get("authors", [])]
    ]
    id_ok = sum(
        (pred_by[t].get("presentation_id") or "") == (gold_by[t].get("presentation_id") or "") for t in matched
    )
    n = len(matched) or 1
    return {
        "scope": "whole page" if whole_page else "gold sessions",
        "slots": {"gold": sum(gc.values()), "pred": sum(pc.values()), "matched": tp_slots,
                  **_prf(tp_slots, sum(pc.values()), sum(gc.values()))},
        "unique": {"gold": len(gc), "pred": len(pc), "matched": tp_unique,
                   **_prf(tp_unique, len(pc), len(gc))},
        "authors_exact": round((len(matched) - len(author_bad)) / n, 4),
        "id_exact": round(id_ok / n, 4),
        "pred_total": len(pred),
        "errors": {
            "missing": [gold_by[t]["title"] for t in gc if t not in pc],
            "extra": [pred_by[t]["title"] for t in pc if t not in gc],
            "authors": [
                {"title": gold_by[t]["title"], "pred": pred_by[t].get("authors"), "gold": gold_by[t].get("authors")}
                for t in author_bad
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="confprog.evaluate")
    ap.add_argument("pred", type=Path)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--all", action="store_true", help="セッションで絞らずページ全体で比べる")
    ap.add_argument("--show", action="store_true", help="誤りの一覧も表示する")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    res = evaluate(load(args.pred), load(args.gold), whole_page=args.all)
    errors = res.pop("errors")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"取りこぼし {len(errors['missing'])} 件 / 余分 {len(errors['extra'])} 件 / 著者違い {len(errors['authors'])} 件")
    if args.show:
        for k in ("missing", "extra"):
            for t in errors[k][:20]:
                print(f"  [{k}] {t}")
        for e in errors["authors"][:20]:
            print(f"  [authors] {e['title']}\n      予測: {e['pred']}\n      正解: {e['gold']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""抽出結果を正解データと比べて精度を出す。

使い方:
  python -m confprog.evaluate <予測.json> eval/gold_miru2026.csv            # 正解データ(一部のセッション)と比べる
  python -m confprog.evaluate <予測.json> eval/gold_miru2026.csv --show     # 取りこぼし・余分・属性違いも表示
  python -m confprog.evaluate <予測.json> data/out/miru2026.json --all      # ページ全体を学会別抽出器の出力と比べる(参考値)

正解データは一部のセッションだけを完全に書き出したもの。比べる範囲(評価範囲)は
予測したセッション名ではなく、ページ上の位置で決める。

- 評価範囲：正解のセッションごとに、そのセッションの正解タイトルをすべて含む
  「予測の並びの中で最も短い区間」を取り、その和集合とする。区間の中にある予測は、
  セッション名が空でも間違っていても評価に入る(区間内の誤抽出は余分として数える)
- 掲載枠：同じ発表が複数のセッションに載る場合は、載った回数ぶん数える。
  予測と正解の掲載枠を1対1に対応づけ(同じタイトルなら同じセッションのものを優先)、
  対応した枠ごとにセッション・著者・発表番号を比べる
- 異なる正規化タイトル：正規化したタイトルが同じものは1件と数える(同名の別発表も1件になる)
- タイトルの照合は NFKC・小文字化・空白除去だけを行う(記号は残す)。正規化しない一致も併記する
- 正解CSVの「確認」列が ok / fix / missing でない行があれば「下書き」として警告する
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

VERIFIED = {"ok", "fix", "missing"}


def norm_title(text: str | None) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", "", s)


def norm_session(text: str | None) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", "", s)


def norm_name(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def session_match(pred: str | None, gold: str | None) -> bool:
    """予測のセッション名が正解のセッション名で始まり、その直後で区切れていれば一致とみなす。

    予測には座長名や部屋名が続くことがあるので前方一致にするが、
    `A1` と `A10` を区別するため、直後が英数字なら一致にしない。
    """
    p, g = norm_session(pred), norm_session(gold)
    if not g or not p.startswith(g):
        return False
    return len(p) == len(g) or not re.match(r"[0-9a-z]", p[len(g)])


def load(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        rows = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                status = (r.get("確認") or "").strip().lower()
                if status == "exclude":
                    continue
                rows.append({
                    "session": r.get("セッション", ""),
                    "presentation_id": r.get("発表ID") or None,
                    "title": r.get("タイトル", ""),
                    "authors": [a.strip() for a in (r.get("著者") or "").split(";") if a.strip()],
                    "status": status,
                })
        return rows
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["presentations"] if isinstance(data, dict) else data


def _min_window(positions: dict[str, list[int]]) -> tuple[int, int] | None:
    """各タイトルの出現位置から、全タイトルを1回以上含む最短区間 [lo, hi] を返す。"""
    events = sorted((i, t) for t, ps in positions.items() for i in ps)
    need = len(positions)
    if not need:
        return None
    have: Counter = Counter()
    best = None
    lo = 0
    for hi in range(len(events)):
        have[events[hi][1]] += 1
        while len(have) == need:
            span = (events[lo][0], events[hi][0])
            if best is None or span[1] - span[0] < best[1] - best[0]:
                best = span
            t = events[lo][1]
            have[t] -= 1
            if not have[t]:
                del have[t]
            lo += 1
    return best


def scope_indices(pred: list[dict], gold: list[dict]) -> set[int]:
    """正解セッションに当たる予測の位置(並び順の添字)を返す。予測のセッション名は使わない。"""
    titles_by_session: dict[str, set[str]] = defaultdict(set)
    for g in gold:
        titles_by_session[g.get("session") or ""].add(norm_title(g["title"]))
    pred_titles = [norm_title(p.get("title")) for p in pred]
    out: set[int] = set()
    for titles in titles_by_session.values():
        positions = {t: [i for i, pt in enumerate(pred_titles) if pt == t] for t in titles}
        positions = {t: ps for t, ps in positions.items() if ps}
        w = _min_window(positions)
        if w:
            out.update(range(w[0], w[1] + 1))
    return out


def _prf(tp: int, n_pred: int, n_gold: int) -> dict:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def align(pred: list[dict], gold: list[dict]) -> list[tuple[dict, dict]]:
    """タイトルが同じ掲載枠を1対1に対応づける。同じタイトルが複数あればセッションが合うものを先に組む。"""
    free: dict[str, list[dict]] = defaultdict(list)
    for p in pred:
        free[norm_title(p.get("title"))].append(p)
    pairs = []
    rest = []
    for g in gold:
        cands = free.get(norm_title(g["title"]), [])
        hit = next((p for p in cands if session_match(p.get("session"), g.get("session"))), None)
        if hit is not None:
            cands.remove(hit)
            pairs.append((hit, g))
        else:
            rest.append(g)
    for g in rest:
        cands = free.get(norm_title(g["title"]), [])
        if cands:
            pairs.append((cands.pop(0), g))
    return pairs


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def evaluate(pred: list[dict], gold: list[dict], whole_page: bool = False) -> dict:
    if whole_page:
        scoped = list(pred)
    else:
        idx = scope_indices(pred, gold)
        scoped = [p for i, p in enumerate(pred) if i in idx]

    pc = Counter(norm_title(p.get("title")) for p in scoped)
    gc = Counter(norm_title(g["title"]) for g in gold)
    tp_slots = sum((pc & gc).values())
    tp_unique = len(set(pc) & set(gc))
    raw_tp = sum((Counter((p.get("title") or "").strip() for p in scoped)
                  & Counter(g["title"].strip() for g in gold)).values())

    pairs = align(scoped, gold)
    sess_ok = auth_ok = id_ok = all_ok = 0
    bad = []
    for p, g in pairs:
        s = whole_page or session_match(p.get("session"), g.get("session"))
        a = [norm_name(x) for x in p.get("authors") or []] == [norm_name(x) for x in g.get("authors") or []]
        i = (p.get("presentation_id") or "") == (g.get("presentation_id") or "")
        sess_ok += s
        auth_ok += a
        id_ok += i
        all_ok += s and a and i
        if not (s and a and i):
            bad.append({"title": g["title"], "session": None if s else (p.get("session"), g.get("session")),
                        "authors": None if a else (p.get("authors"), g.get("authors")),
                        "id": None if i else (p.get("presentation_id"), g.get("presentation_id"))})

    n_gold = len(gold)
    drafts = sum(1 for g in gold if g.get("status") is not None and g["status"] not in VERIFIED)
    return {
        "scope": "whole page" if whole_page else "gold sessions (by position)",
        "gold_status": "verified" if not drafts else f"DRAFT ({drafts} rows unverified)",
        "slots": {"gold": n_gold, "pred": sum(pc.values()), "matched": tp_slots,
                  **_prf(tp_slots, sum(pc.values()), n_gold)},
        "unique_normalized_titles": {"gold": len(gc), "pred": len(pc), "matched": tp_unique,
                                     **_prf(tp_unique, len(pc), len(gc))},
        "raw_title_matched": raw_tp,
        # 分母が「対応した枠」と「正解の全枠」の2通り
        "of_matched": {"n": len(pairs), "session": _rate(sess_ok, len(pairs)),
                       "authors": _rate(auth_ok, len(pairs)), "id": _rate(id_ok, len(pairs)),
                       "all_fields": _rate(all_ok, len(pairs))},
        "of_gold": {"n": n_gold, "session": _rate(sess_ok, n_gold), "authors": _rate(auth_ok, n_gold),
                    "id": _rate(id_ok, n_gold), "all_fields": _rate(all_ok, n_gold)},
        "pred_total": len(pred),
        "errors": {
            "missing": sorted((gc - pc).elements()),
            "extra": sorted((pc - gc).elements()),
            "fields": bad,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="confprog.evaluate")
    ap.add_argument("pred", type=Path)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--all", action="store_true", help="範囲で絞らずページ全体で比べる")
    ap.add_argument("--show", action="store_true", help="誤りの一覧も表示する")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    res = evaluate(load(args.pred), load(args.gold), whole_page=args.all)
    if res["gold_status"] != "verified":
        print(f"警告: 正解が下書きです({res['gold_status']})。結果は下書きとの一致として扱ってください。",
              file=sys.stderr)
    errors = res.pop("errors")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"取りこぼし {len(errors['missing'])} 枠 / 余分 {len(errors['extra'])} 枠 / 属性違い {len(errors['fields'])} 枠")
    if args.show:
        for k in ("missing", "extra"):
            for t in errors[k][:20]:
                print(f"  [{k}] {t}")
        for e in errors["fields"][:20]:
            print(f"  [fields] {e['title']}")
            for k in ("session", "authors", "id"):
                if e[k] is not None:
                    print(f"      {k}: 予測 {e[k][0]} / 正解 {e[k][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

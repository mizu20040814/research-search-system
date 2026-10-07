"""汎用の抽出：どの学会のプログラムページにも同じ方法をかける(基準手法)。

学会ごとのタグ名・クラス名・正規表現は一切持たない。描画後の HTML の「構造の繰り返し」だけを使う。

1. 文字を持つ要素ごとに、ルートからのタグ・クラスの並び(パス)を求める
   (表のセルは何列目かもパスに入れる。span などの連続はひとつにまとめる)
2. 同じパスの要素をまとめて「欄の候補」とし、文字の特徴を数える
   (長さ・重複のなさ・番号らしさ・時刻らしさ・人名の並びらしさ)
3. いちばんタイトルらしい欄を「タイトル」とし、各タイトルを1件の発表とみなす
4. タイトルの直後に毎回現れて人名の並びらしい欄を「著者」、
   直前に毎回現れて番号らしい欄を「発表番号」とする
5. 数件のタイトルごとに1回ずつ前に現れる欄を「セッション名」とする

使い方:
  python -m confprog.generic <プログラムページのURL> --conference MIRU --year 2026
  python -m confprog.generic <URL> --conference ANLP --html data/raw/xxx.html   # 保存済みHTMLを描画して読む
  python -m confprog.generic --conference ANLP --html data/rendered/xxx.html --no-render
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .authors import parse_authors, split_top_level
from .dom import Node, parse
from .schema import Presentation

INLINE_TAGS = {"span", "a", "b", "i", "em", "strong", "small", "font", "sup", "sub", "u", "mark", "label"}
MIN_COUNT = 5

_ID_RE = re.compile(r"^[A-Za-z]{0,8}[\s\-_]?[A-Za-z]{0,3}\d+[A-Za-z]?([\-–_.:][A-Za-z0-9]+)*$")
_TIME_RE = re.compile(r"\d{1,2}[:：]\d{2}")
_HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "caption", "dt", "th", "summary", "legend"}
_HEAD_WORDS = ("title", "head", "session", "caption")


# ---------- 1. 要素とパス ----------

CLASS_DEPTH = 2  # クラス名を見るのは末端から何段までか(上の段は交互の色分けなどで変わりやすい)


def _step(n: Node, with_class: bool) -> str:
    s = n.tag + ("".join("." + c for c in n.classes) if with_class else "")
    if n.tag in ("td", "th") and n.parent is not None:
        same = [c for c in n.parent.children if isinstance(c, Node) and c.tag == n.tag]
        s += f"[{same.index(n) + 1}]"
    return s


def _path(n: Node) -> tuple[str, ...]:
    steps = []
    while n is not None and n.tag != "#root":
        steps.append(_step(n, len(steps) < CLASS_DEPTH))
        n = n.parent
    return tuple(reversed(steps))


@dataclass
class Unit:
    order: int
    path: tuple[str, ...]
    text: str
    node: Node
    href: str | None = None


def units(root: Node) -> list[Unit]:
    """自分の直下に文字を持つ要素を文書順に並べる。同じ親の下で同じパスの inline 要素は1つにまとめる。"""
    out: list[Unit] = []
    merged: dict[tuple, Unit] = {}
    for n in root.iter():
        if n.tag == "#root":
            continue
        own = "".join(c for c in n.children if isinstance(c, str)).strip()
        if not own:
            continue
        text = n.text()
        if not text:
            continue
        path = _path(n)
        a = n if n.tag == "a" else None
        p = n.parent
        while a is None and p is not None and p.tag != "#root":
            a = p if p.tag == "a" else None
            p = p.parent
        href = a.attrs.get("href") if a is not None else None
        key = (path, id(n.parent))
        if n.tag in INLINE_TAGS and key in merged:
            merged[key].text += " " + text
            continue
        u = Unit(len(out), path, text, n, href)
        out.append(u)
        if n.tag in INLINE_TAGS:
            merged[key] = u
    return out


# ---------- 2. 欄の候補と特徴 ----------

def _namelike(t: str) -> float:
    parts = split_top_level(t)
    names = [re.sub(r"[(（\[【].*?[)）\]】]", "", p).strip() for p in parts]
    names = [x for x in names if x]
    if len(names) >= 2 and statistics.mean(len(x) for x in names) <= 25:
        return 1.0
    if len(names) == 1 and re.search(r"[(（]", t) and len(names[0]) <= 20:
        return 0.5
    return 0.0


def _lenscore(length: float) -> float:
    # 人名(5〜10字)や番号より長く、要旨(数百字)より短いものをタイトルらしいとする
    if length < 20:
        return (length / 20) ** 2
    if length > 200:
        return 200 / length
    return 1.0


@dataclass
class Field:
    path: tuple[str, ...]
    members: list[Unit] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [u.text for u in self.members]

    def stats(self) -> dict:
        t = self.texts
        n = len(t)
        return {
            "count": n,
            "uniq": len(set(t)) / n,
            "median_len": statistics.median(len(x) for x in t),
            "id": sum(bool(_ID_RE.match(x)) for x in t) / n,
            "time": sum(bool(_TIME_RE.search(x)) for x in t) / n,
            "name": sum(_namelike(x) for x in t) / n,
        }

    def headish(self) -> bool:
        last = self.path[-3:]
        return any(s.split(".")[0].split("[")[0] in _HEAD_TAGS for s in last) or any(
            w in s.lower() for s in last for w in _HEAD_WORDS
        )


def title_score(s: dict) -> float:
    return (
        s["count"] * s["uniq"] * _lenscore(s["median_len"])
        * (1 - s["id"]) * (1 - s["time"]) * (1 - s["name"])
    )


# ---------- 3〜5. 役割の推定 ----------

@dataclass
class Inference:
    title: Field
    author: Field | None
    pid: Field | None
    session: Field | None
    candidates: list[tuple[float, Field, dict]]

    def describe(self) -> dict:
        def p(f):
            return " > ".join(f.path[-4:]) if f else None
        return {
            "title_path": p(self.title),
            "author_path": p(self.author),
            "id_path": p(self.pid),
            "session_path": p(self.session),
            "title_candidates": [
                {"path": p(f), "score": round(sc, 1), **{k: round(v, 3) for k, v in st.items()}}
                for sc, f, st in self.candidates[:5]
            ],
        }


def infer(us: list[Unit]) -> Inference:
    by_path: dict[tuple, Field] = {}
    for u in us:
        by_path.setdefault(u.path, Field(u.path)).members.append(u)
    cands = []
    for f in by_path.values():
        if len(f.members) < MIN_COUNT:
            continue
        st = f.stats()
        cands.append((title_score(st), f, st))
    if not cands:
        raise ValueError("繰り返し現れる文字の欄が見つかりません")
    cands.sort(key=lambda x: -x[0])
    title = cands[0][1]

    pos = [u.order for u in title.members]
    bounds = pos + [len(us)]

    def after_cov(f: Field) -> float:
        hit = 0
        orders = sorted(u.order for u in f.members)
        j = 0
        for a, b in zip(bounds, bounds[1:]):
            while j < len(orders) and orders[j] <= a:
                j += 1
            hit += j < len(orders) and orders[j] < b
        return hit / len(pos)

    def before_cov(f: Field) -> float:
        prev = [-1] + pos
        orders = set(u.order for u in f.members)
        hit = 0
        for a, b in zip(prev, pos):
            # 直前のタイトルとの間の、タイトルに近い側で見る
            hit += any(o in orders for o in range(max(a + 1, b - 3), b))
        return hit / len(pos)

    others = [f for f in by_path.values() if f is not title and len(f.members) >= 2]

    author = None
    best = 0.0
    for f in others:
        st = f.stats()
        sc = after_cov(f) * st["name"]
        if st["name"] >= 0.3 and sc > best:
            best, author = sc, f
    if best < 0.3:
        author = None

    pid = None
    best = 0.0
    for f in others:
        if f is author:
            continue
        st = f.stats()
        sc = before_cov(f) * st["id"]
        if st["id"] >= 0.8 and sc > best:
            best, pid = sc, f
    if best < 0.5:
        pid = None

    # セッション名：数件のタイトルごとに1回ずつ前に現れる欄。
    # 日付の見出しなど粗い区切りも条件を満たすので、十分に当てはまる候補のうち最も細かい区切りを選ぶ
    scored = []
    for f in others:
        if f in (author, pid) or len(f.members) > len(pos) / 2:
            continue
        st = f.stats()
        if st["median_len"] > 150:
            continue
        orders = sorted(u.order for u in f.members)
        nxt = orders[1:] + [len(us)]
        interleave = sum(any(o < p < q for p in pos) for o, q in zip(orders, nxt)) / len(orders)
        coverage = sum(1 for p in pos if orders[0] < p) / len(pos)
        sc = interleave * coverage * st["uniq"] * (1 - st["time"]) * (1.5 if f.headish() else 1.0)
        scored.append((sc, f))
    session = None
    if scored:
        best = max(sc for sc, _ in scored)
        good = [f for sc, f in scored if sc >= max(0.3, best * 0.5)]
        if good:
            session = max(good, key=lambda f: len(f.members))

    return Inference(title, author, pid, session, cands)


def _clean_id(text: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", text.split()[0] if text.split() else text)


def extract(html: str, conference: str, year: int | None = None, source_url: str | None = None):
    us = units(parse(html))
    inf = infer(us)
    pos = [u.order for u in inf.title.members]
    bounds = pos + [len(us)]

    def first_after(f, a, b):
        if f is None:
            return None
        for u in f.members:
            if a < u.order < b:
                return u
        return None

    def last_before(f, a, b):
        if f is None:
            return None
        hit = None
        for u in f.members:
            if a < u.order < b:
                hit = u
        return hit

    # 次の発表番号やセッション名が出たら、そこから先は別の発表(著者を探すのはその手前まで)
    stops = sorted(u.order for f in (inf.pid, inf.session) if f for u in f.members)

    def stop_after(a, b):
        for o in stops:
            if a < o < b:
                return o
        return b

    items = []
    prev = -1
    for t, a, b in zip(inf.title.members, bounds, bounds[1:]):
        au = first_after(inf.author, a, stop_after(a, b))
        idu = last_before(inf.pid, max(prev, a - 4), a)
        se = last_before(inf.session, -1, a)
        names, affs = parse_authors(au.text if au else None)
        items.append(Presentation(
            conference=conference,
            event=f"{conference}{year}" if year else conference,
            year=year or 0,
            session=se.text if se else "",
            title=t.text,
            authors=names,
            url=t.href,
            presentation_id=_clean_id(idu.text) if idu else None,
            affiliations=affs,
            authors_raw=au.text if au else None,
            source_url=source_url,
        ))
        prev = a
    return items, inf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="confprog.generic", description="汎用の抽出(構造推定)")
    ap.add_argument("url", nargs="?", help="プログラムページの URL")
    ap.add_argument("--conference", required=True, help="学会名(出力に入れるだけ。抽出には使わない)")
    ap.add_argument("--year", type=int)
    ap.add_argument("--html", type=Path, help="保存済みの HTML を使う")
    ap.add_argument("--no-render", action="store_true", help="ブラウザで描画せずにそのまま読む")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if not args.url and not args.html:
        ap.error("URL か --html のどちらかが必要です")

    from .fetch import FetchError, fetch
    from .render import RenderError, render

    try:
        html = args.html.read_text(encoding="utf-8") if args.html else None
        if not args.no_render:
            html = render(args.url, html=html) if args.url else render(None, html=html)
        elif html is None:
            html = fetch(args.url)
    except (FetchError, RenderError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    try:
        items, inf = extract(html, args.conference, args.year, args.url)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    name = f"{args.conference.lower()}{args.year or ''}"
    out = args.out or Path("data/out") / f"generic_{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": "generic-structure-v1",
        "conference": args.conference,
        "year": args.year,
        "source_url": args.url,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inference": inf.describe(),
        "count": len(items),
        "presentations": [p.to_dict() for p in items],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    d = inf.describe()
    print(f"抽出件数: {len(items)} 件 / 異なるタイトル: {len({p.title for p in items})} 件")
    for k in ("title_path", "author_path", "id_path", "session_path"):
        print(f"  {k:13s}: {d[k]}")
    print(f"  著者なし: {sum(not p.authors for p in items)} 件 / セッションなし: {sum(not p.session for p in items)} 件")
    for p in items[:3]:
        print(f"  - [{p.session}] {p.presentation_id or ''} {p.title} / {', '.join(p.authors)}")
    print(f"保存先: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

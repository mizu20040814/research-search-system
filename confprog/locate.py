"""プログラムページの特定：大会トップURLから発表一覧のページ(1つまたは複数)を返す。

学会ごとの分岐は持たない。どの大会にも次の同じ手順をかける。
1. トップを開いて判定する(トップ自体が発表一覧のこともある)
2. リンクに「プログラム」などの語で点数をつけ、高い順に開いて判定する(2段まで)
3. 発表一覧と判定したページは、リンク先も発表一覧なら「ハブ」(一覧の一覧)とみなし、
   リンク先のほうを返す(目次から分野別ページへ、セッション一覧から各セッションへ)
4. 同じ一覧を別ルートで見つけたら1つにまとめる

ページは必ず get(既定は render)で取る。robots.txt・7秒間隔・キャッシュはそちらが守る。
"""
from __future__ import annotations

import heapq
from dataclasses import asdict, dataclass, field
from typing import Callable

from .fetch import FetchError
from .generic import ListVerdict, judge_list
from .links import collect_links, group_by_shape, url_key, url_shape
from .render import RenderError, render

TOP_K = 8  # 各ページから開く候補リンクの数
HUB_MIN_GROUP = 3  # ハブとみなすリンクのまとまりの最小の大きさ
HUB_MAX_GROUPS = 3  # 1ページで試すまとまりの数
HUB_SAMPLES = 2  # まとまりごとに試し開きする数
DUP_OVERLAP = 0.8  # タイトルがこの割合以上同じなら同じ一覧


@dataclass
class Visit:
    url: str
    depth: int
    link_score: float
    verdict: str  # "list" | "hub" | "none" | "error" | "duplicate"
    title_count: int
    reason: str


@dataclass
class LocateResult:
    top_url: str
    pages: list[str]
    visits: list[Visit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"top_url": self.top_url, "pages": self.pages, "visits": [asdict(v) for v in self.visits]}


def locate(top_url: str, *, get: Callable[[str], str] = render, max_depth: int = 2,
           max_pages: int = 25, max_hub_pages: int = 200) -> LocateResult:
    visits: list[Visit] = []
    cache: dict[str, tuple[str | None, ListVerdict | None, str]] = {}  # キーは url_key
    budget = {"normal": 0, "hub": 0}
    seen: set[str] = set()

    def open_page(url: str, kind: str) -> tuple[str | None, ListVerdict | None, str]:
        """取得して判定する。同じページは1回しか取らない。"""
        key = url_key(url)
        if key not in cache:
            budget[kind] += 1
            try:
                html = get(url)
            except (FetchError, RenderError) as e:
                cache[key] = (None, None, str(e)[:200])
            else:
                cache[key] = (html, judge_list(html), "")
        return cache[key]

    def find_hub(html: str, url: str, depth: int) -> list[tuple[str, list[str]]] | str | None:
        """リンク先が発表一覧のまとまりを全部 (形, URL のリスト) で返す(口頭とポスターのように複数ありうる)。
        1つも確かめられないうちに上限に達したら "limit"。"""
        groups = [g for g in group_by_shape(collect_links(html, url, top_url, positive_only=False))
                  if len(g[1]) >= HUB_MIN_GROUP][:HUB_MAX_GROUPS]
        hubs: list[tuple[str, list[str]]] = []
        for shape, links in groups:
            ok = True
            for link in links[:HUB_SAMPLES]:
                key = url_key(link.url)
                if budget["normal"] >= max_pages and key not in cache:
                    return hubs or "limit"
                h, v, err = open_page(link.url, "normal")
                if v is not None and v.is_list:
                    continue
                ok = False
                if key not in seen:  # 試し開きで一覧でなかったページも記録する
                    seen.add(key)
                    verdict = "error" if h is None else "none"
                    visits.append(Visit(link.url, depth + 1, link.score, verdict,
                                        v.title_count if v else 0, f"試し開き: {err or v.reason}"))
                break
            if ok:
                hubs.append((shape, [l.url for l in links]))
        return hubs or None

    found: list[tuple[str, int, float, ListVerdict]] = []

    def adopt_members(members: list[str], depth: int) -> None:
        for i, m in enumerate(members):
            key = url_key(m)
            if key in seen:
                continue
            if budget["hub"] >= max_hub_pages and key not in cache:
                visits.append(Visit(m, depth, 0.0, "none", 0,
                                    f"ハブのリンク先の上限 {max_hub_pages} 枚で打ち切り(残り {len(members) - i})"))
                return
            seen.add(key)
            h, mv, merr = open_page(m, "hub")
            if h is None:
                visits.append(Visit(m, depth, 0.0, "error", 0, merr))
            elif mv.is_list:
                found.append((m, depth, 0.0, mv))
            else:
                visits.append(Visit(m, depth, 0.0, "none", mv.title_count, mv.reason))

    queue: list[tuple[float, int, str, int]] = [(0.0, 0, top_url, 0)]
    expanded: dict[str, tuple[str, int]] = {}  # 一覧でなかったページの HTML と、たどった深さ

    def push_links(html: str, url: str, depth: int, order: int) -> int:
        for link in collect_links(html, url, top_url)[:TOP_K]:
            k = url_key(link.url)
            if k not in seen or (k in expanded and depth + 1 < expanded[k][1]):
                heapq.heappush(queue, (-link.score, order, link.url, depth + 1))
                order += 1
        return order

    order = 1
    while queue:
        neg, _, url, depth = heapq.heappop(queue)
        score = -neg + 0.0  # -0.0 を出さない
        key = url_key(url)
        if key in seen:
            # 深い経路で先に開いた「一覧でない」ページに浅い経路で来たら、リンクをたどり直す(取得はしない)
            if key in expanded and depth < expanded[key][1] and depth < max_depth:
                expanded[key] = (expanded[key][0], depth)
                order = push_links(expanded[key][0], url, depth, order)
            continue
        if budget["normal"] >= max_pages and key not in cache:
            visits.append(Visit(url, depth, score, "none", 0,
                                f"上限 {max_pages} 枚で終了(残り候補 {len(queue) + 1})"))
            break
        seen.add(key)
        html, v, err = open_page(url, "normal")
        if html is None:
            visits.append(Visit(url, depth, score, "error", 0, err))
            continue
        if v.is_list:
            hub = find_hub(html, url, depth)
            if hub == "limit":
                visits.append(Visit(url, depth, score, "none", v.title_count, "上限のためハブ判定できず"))
                break
            if hub is None:
                found.append((url, depth, score, v))
                continue
            shapes = [shape for shape, _ in hub]
            if url_shape(url) in shapes:
                # 一覧どうしが互いにリンクしている(分野別ページなど)。自分も一覧の1つ
                found.append((url, depth, score, v))
            else:
                visits.append(Visit(url, depth, score, "hub", v.title_count,
                                    f"{', '.join(shapes)} の {HUB_SAMPLES} 件が一覧"))
            for _, members in hub:
                adopt_members(members, depth)
            continue
        visits.append(Visit(url, depth, score, "none", v.title_count, v.reason))
        expanded[key] = (html, depth)
        if depth < max_depth:
            order = push_links(html, url, depth, order)

    pages: list[str] = []
    kept: list[set[str]] = []
    for url, depth, score, v in found:
        titles = set(v.titles)
        dup = next((p for p, t in zip(pages, kept)
                    if titles and t and len(titles & t) / min(len(titles), len(t)) >= DUP_OVERLAP), None)
        if dup:
            visits.append(Visit(url, depth, score, "duplicate", v.title_count, f"{dup} とタイトルが同じ"))
            continue
        visits.append(Visit(url, depth, score, "list", v.title_count, v.reason))
        pages.append(url)
        kept.append(titles)
    return LocateResult(top_url, pages, visits)


def _print(name: str, r: LocateResult) -> None:
    print(f"{name}: 発表一覧 {len(r.pages)} ページ")
    for p in r.pages:
        print(f"  - {p}")
    for v in r.visits:
        print(f"    {v.depth} {v.verdict:9s} {v.link_score:4.1f} {v.url}  {v.reason}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import csv
    import json
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="confprog.locate", description="大会トップURLから発表一覧ページを特定する")
    ap.add_argument("url", nargs="?", help="大会トップURL")
    ap.add_argument("--out", type=Path, help="1件のときの保存先(既定 data/out/locate/single.json)")
    ap.add_argument("--list", type=Path, help="学会リストの CSV(列: 学会,年,トップURL,メモ)")
    ap.add_argument("--only", nargs="*", help="学会名で絞る")
    ap.add_argument("--out-dir", type=Path, default=Path("data/out/locate"), help="--list のときの保存先")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if not args.url and not args.list:
        ap.error("URL か --list のどちらかが必要です")

    if args.url:
        r = locate(args.url, get=render)
        _print(args.url, r)
        out = args.out or args.out_dir / "single.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"保存先: {out}")
        return 0

    with args.list.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.only:
        rows = [row for row in rows if row["学会"] in args.only]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for i, row in enumerate(rows, 1):
        name, year, url = row["学会"], row["年"], row["トップURL"]
        print(f"[{i}/{len(rows)}] {name} {year} {url}", flush=True)
        try:
            r = locate(url, get=render)
        except Exception as e:  # 1大会が失敗しても残りは続ける
            print(f"    エラー: {type(e).__name__}: {e}")
            summary.append([name, year, 0, 0, f"{type(e).__name__}: {e}"[:200]])
            continue
        _print(name, r)
        (args.out_dir / f"{name.lower()}{year}.json").write_text(
            json.dumps(r.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append([name, year, len(r.pages), len(r.visits), row.get("メモ", "")])
    with (args.out_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["学会", "年", "ページ数", "記録数", "メモ"])
        w.writerows(summary)
    print(f"一覧: {args.out_dir / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

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
from .links import collect_links, group_by_shape, normalize_url
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
    cache: dict[str, tuple[str | None, ListVerdict | None, str]] = {}
    budget = {"normal": 0, "hub": 0}

    def open_page(url: str, kind: str) -> tuple[str | None, ListVerdict | None, str]:
        """取得して判定する。同じ URL は1回しか取らない。"""
        if url not in cache:
            budget[kind] += 1
            try:
                html = get(url)
            except (FetchError, RenderError) as e:
                cache[url] = (None, None, str(e)[:200])
            else:
                cache[url] = (html, judge_list(html), "")
        return cache[url]

    def find_hub(html: str, url: str, depth: int, score: float) -> list[str] | None:
        """リンク先が発表一覧なら、そのまとまりの URL を返す。"""
        groups = [g for g in group_by_shape(collect_links(html, url, top_url, positive_only=False))
                  if len(g[1]) >= HUB_MIN_GROUP][:HUB_MAX_GROUPS]
        for shape, links in groups:
            ok = True
            for link in links[:HUB_SAMPLES]:
                if budget["normal"] >= max_pages and link.url not in cache:
                    return None
                h, v, err = open_page(link.url, "normal")
                if h is None:
                    visits.append(Visit(link.url, depth, link.score, "error", 0, err))
                    seen.add(link.url)
                if v is None or not v.is_list:
                    ok = False
                    break
            if ok:
                visits.append(Visit(url, depth, score, "hub", 0, f"{shape} の {HUB_SAMPLES} 件が一覧"))
                return [l.url for l in links]
        return None

    found: list[tuple[str, int, float, ListVerdict]] = []
    seen: set[str] = set()
    top = normalize_url(top_url)
    queue: list[tuple[float, int, str, int]] = [(0.0, 0, top, 0)]
    order = 1
    while queue:
        neg, _, url, depth = heapq.heappop(queue)
        if url in seen:
            continue
        if budget["normal"] >= max_pages and url not in cache:
            break
        seen.add(url)
        html, v, err = open_page(url, "normal")
        if html is None:
            visits.append(Visit(url, depth, -neg, "error", 0, err))
            continue
        if v.is_list:
            members = find_hub(html, url, depth, -neg)
            if members is None:
                found.append((url, depth, -neg, v))
                continue
            for m in members:
                if m in seen:
                    continue
                if budget["hub"] >= max_hub_pages and m not in cache:
                    break
                seen.add(m)
                h, mv, merr = open_page(m, "hub")
                if h is None:
                    visits.append(Visit(m, depth, 0.0, "error", 0, merr))
                elif mv.is_list:
                    found.append((m, depth, 0.0, mv))
                else:
                    visits.append(Visit(m, depth, 0.0, "none", mv.title_count, mv.reason))
            continue
        visits.append(Visit(url, depth, -neg, "none", v.title_count, v.reason))
        if depth < max_depth:
            for link in collect_links(html, url, top_url)[:TOP_K]:
                if link.url not in seen:
                    heapq.heappush(queue, (-link.score, order, link.url, depth + 1))
                    order += 1

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

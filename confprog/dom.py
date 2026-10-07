"""HTML を簡単な木にする(標準ライブラリの html.parser だけを使う)。

汎用抽出は「ブラウザで描画した後の HTML」を読む前提なので、
タグの閉じ忘れなどへの対処は最小限にしている。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

# 中身を読まない要素
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "iframe", "select"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    parent: "Node | None" = None
    children: list["Node | str"] = field(default_factory=list)

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(sorted(self.attrs.get("class", "").split()))

    def text(self) -> str:
        out: list[str] = []
        stack: list[Node | str] = [self]
        while stack:
            n = stack.pop()
            if isinstance(n, str):
                out.append(n)
            elif n.tag == "sup":
                # 上付き文字は所属や脚注の番号(「久野 証¹、中島 研吾²˒³」)なので読まない
                out.append(" ")
            elif n.tag in ("br", "p", "div", "li", "tr"):
                # ブロック境界は空白にする
                out.append(" ")
                stack.extend(reversed(n.children))
            else:
                stack.extend(reversed(n.children))
        return " ".join("".join(out).split())

    def iter(self):
        """要素を文書順にたどる。"""
        stack: list[Node] = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(c for c in reversed(n.children) if isinstance(c, Node))


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag in SKIP_TAGS:
                self.skip_depth += 1
            return
        if tag in SKIP_TAGS:
            self.skip_depth = 1
            return
        node = Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        if not self.skip_depth and tag not in SKIP_TAGS:
            self.cur.children.append(Node(tag, {k: v or "" for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag in SKIP_TAGS:
                self.skip_depth -= 1
            return
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if not self.skip_depth:
            self.cur.children.append(data)


def parse(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root

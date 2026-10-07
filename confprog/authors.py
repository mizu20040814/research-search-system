"""著者文字列を氏名リストと所属リストに分ける。

学会ごとに書式が違うので、よくある形をまとめて扱う。
  "山田 太郎 (東大), 佐藤 花子 (京大)"
  "山田太郎（東大）・佐藤花子（京大）"
  "山田太郎, 佐藤花子 (東大), 鈴木一郎 (京大)"   ← 所属が後ろにまとまる形
  "Taro Yamada (UTokyo), Hanako Sato and Ichiro Suzuki (Kyoto U.)"
"""
from __future__ import annotations

import re

_OPEN = "(（[【"
_CLOSE = ")）]】"
# 括弧の外にあるときだけ区切りとして扱う
_SEPARATORS = (",", "，", "、", "・", ";", "；", "／", "/")
_AND_RE = re.compile(r"\s+(?:and|&)\s+", re.IGNORECASE)
_AFFIL_RE = re.compile(r"[(（\[【]([^)）\]】]*)[)）\]】]")
_MARK_RE = re.compile(r"[○◯◎〇◊*＊†‡§💻📰]")


def split_top_level(text: str) -> list[str]:
    """括弧の外にある区切り文字で分割する。"""
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        if depth == 0 and ch in _SEPARATORS:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out = []
    for p in parts:
        # 括弧の外の " and " も区切りにする
        out.extend(_AND_RE.split(p) if not _AFFIL_RE.search(p) else _split_and_outside(p))
    return [p.strip() for p in out if p.strip()]


def _split_and_outside(part: str) -> list[str]:
    head = _AFFIL_RE.split(part, maxsplit=1)[0]
    rest = part[len(head):]
    names = _AND_RE.split(head)
    names[-1] = names[-1] + rest
    return names


def _strip_parens(part: str) -> tuple[str, list[str]]:
    """括弧の外の文字列と、いちばん外側の括弧の中身を分ける(入れ子の括弧に対応)。"""
    outside, groups, buf, depth = [], [], [], 0
    for ch in part:
        if ch in _OPEN:
            if depth:
                buf.append(ch)
            depth += 1
        elif ch in _CLOSE and depth:
            depth -= 1
            if depth:
                buf.append(ch)
            else:
                groups.append("".join(buf))
                buf = []
        elif depth:
            buf.append(ch)
        else:
            outside.append(ch)
    if buf:  # 閉じていない括弧
        groups.append("".join(buf))
    return "".join(outside), groups


def parse_authors(raw: str | None) -> tuple[list[str], list[str]]:
    """著者文字列 → (氏名リスト, 所属リスト[重複なし・出現順])。"""
    if not raw:
        return [], []
    text = re.sub(r"\s+", " ", str(raw)).strip()
    names: list[str] = []
    affiliations: list[str] = []
    for part in split_top_level(text):
        name, groups = _strip_parens(part)
        for aff in groups:
            # "東大, 京大" のように複数所属が入る場合もある(括弧の中の括弧は所属名の一部)
            for a in split_top_level(aff):
                a = a.strip()
                if a and a not in affiliations:
                    affiliations.append(a)
        name = _MARK_RE.sub("", name).strip(" 　")
        if name:
            names.append(name)
    return names, affiliations

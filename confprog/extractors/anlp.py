"""言語処理学会 年次大会(ANLP / NLP20XX)のプログラムページから発表を抽出する。

ページは静的 HTML で、全プログラムが1ページにある。「一般発表」以降は次の形が続く。
  <span class="session_title" id="B1">B1:NLPモデルの評価・安全性・信頼性</span>
  　3/10 (火) 9:30-11:00 &nbsp; B会場(...)　座長: ...<br></div>
  <table>
    <tr><td class="pid"><span id="B1-1">B1-1</span></td><td><span class="title">タイトル</span></td></tr>
    <tr><td><a href=".../pdf_dir/B1-1.pdf">...</a></td><td>○著者 (所属), 著者 (所属)</td></tr>
    ...
口頭発表セッション(A1 など)にはポスター発表の再掲(B2-3 📰 など)も含まれる。
チュートリアル・招待講演・招待論文は書式が違うので、今は対象外。
"""
from __future__ import annotations

import html as htmlmod
import re
from urllib.parse import urljoin

from ..authors import parse_authors
from ..schema import Presentation

CONFERENCE = "ANLP"
DEFAULT_URL = "https://www.anlp.jp/proceedings/annual_meeting/{year}/"


class ExtractError(RuntimeError):
    pass


_SESSION_RE = re.compile(r'<span class="?session_title"?[^>]*>(.*?)</span>(.*?)</div>', re.S)
_ROW_RE = re.compile(
    r'<td class="pid">(?P<pid>.*?)</td>\s*<td>\s*<span class="title">(?P<title>.*?)</span>\s*</td>\s*</tr>\s*'
    r'<tr>\s*<td>(?P<link>.*?)</td>\s*<td>(?P<authors>.*?)</td>',
    re.S,
)
_DATETIME_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s*\([^)]*\)\s*(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})")


def _text(fragment: str) -> str:
    s = re.sub(r"<[^>]+>", "", fragment)
    s = htmlmod.unescape(s).replace("　", " ")
    return re.sub(r"\s+", " ", s).strip()


def extract(html: str, source_url: str | None = None, year: int | None = None) -> list[Presentation]:
    if year is None:
        m = re.search(r"/(\d{4})/?", source_url or "")
        year = int(m[1]) if m else 0
    m = re.search(r'<h3 id="general"', html)
    if not m:
        raise ExtractError("「一般発表」の見出しが見つかりません(ページの構成が変わった可能性)")
    body = html[m.start():]

    heads = list(_SESSION_RE.finditer(body))
    if not heads:
        raise ExtractError("セッションが見つかりません")

    out: list[Presentation] = []
    for i, h in enumerate(heads):
        block = body[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        session = _text(h.group(1))
        info = _text(h.group(2))
        dt = _DATETIME_RE.search(info)
        date = f"{year}-{int(dt[1]):02d}-{int(dt[2]):02d}" if dt else None
        time = dt[3].replace(" ", "").replace("-", "–") if dt else None
        for row in _ROW_RE.finditer(block):
            pid = _text(row["pid"]).split(" ")[0] or None
            href = re.search(r'href="([^"]+)"', row["link"])
            authors_raw = _text(row["authors"])
            names, affs = parse_authors(authors_raw)
            out.append(Presentation(
                conference=CONFERENCE,
                event=f"NLP{year}",
                year=year,
                session=session,
                title=_text(row["title"]),
                authors=names,
                url=urljoin(source_url or "", href[1]) if href else None,
                presentation_id=pid,
                session_type="oral" if re.match(r"[A-C]\d", session) else
                             "poster" if re.match(r"[PQ]\d", session) else None,
                date=date,
                time=time,
                affiliations=affs,
                authors_raw=authors_raw or None,
                source_url=source_url,
            ))
    if not out:
        raise ExtractError("発表が1件も抽出できませんでした")
    return out

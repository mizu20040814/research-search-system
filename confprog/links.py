"""ページ特定の候補リンク：ページからリンクを集め、点数をつける(通信しない)。

点数は、リンク文字と URL に「プログラム」「timetable」などの語があるかで決める。
語は学会サイト一般でプログラムを指すものだけで、学会名やサイト固有の語は入れない。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from .dom import parse

POSITIVE_WORDS = (
    "プログラム", "program", "発表一覧", "講演一覧", "タイムテーブル", "timetable", "schedule",
    "日程", "セッション", "session", "一般発表", "口頭", "ポスター", "accepted",
)
NEGATIVE_WORDS = (
    "参加登録", "registration", "会場", "アクセス", "スポンサー", "sponsor", "お知らせ", "news",
    "投稿", "募集", "call for", "宿泊", "委員", "committee", "表彰", "award", "招待講演",
    "チュートリアル", "過去",
)
POSITIVE_POINT = 1.0
NEGATIVE_POINT = -2.0  # 「プログラム委員」「過去のプログラム」を確実に外す
UNDER_TOP_BONUS = 0.5  # 必須にはしない(トップと別の階層に一覧を置く大会がある)

_FILE_EXTS = (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg",
              ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx")


@dataclass
class Link:
    url: str
    text: str
    score: float


def normalize_url(url: str) -> str:
    """# 以降を落とし、末尾の index.html / index.htm を / にそろえる。"""
    url = urldefrag(url)[0]
    for idx in ("/index.html", "/index.htm"):
        if url.endswith(idx):
            return url[: -len(idx) + 1]
    return url


def url_key(url: str) -> str:
    """同じページかを比べるためのキー。normalize_url に加えて末尾の / をそろえる。"""
    url = normalize_url(url)
    return url[:-1] if url.endswith("/") and urlparse(url).path not in ("", "/") else url


def _dir(url: str) -> str:
    p = urlparse(url)
    return p.path if p.path.endswith("/") else p.path.rsplit("/", 1)[0] + "/"


def score_link(text: str, url: str, top_url: str) -> float:
    hay = f"{text} {url}".lower()
    score = sum(POSITIVE_POINT for w in POSITIVE_WORDS if w.lower() in hay)
    score += sum(NEGATIVE_POINT for w in NEGATIVE_WORDS if w.lower() in hay)
    if urlparse(url).netloc == urlparse(top_url).netloc and urlparse(url).path.startswith(_dir(top_url)):
        score += UNDER_TOP_BONUS
    return score


def collect_links(html: str, page_url: str, top_url: str, *, positive_only: bool = True) -> list[Link]:
    """同じホストの HTML ページへのリンクを集め、点数の高い順に返す。
    positive_only なら点数が正のものだけ(候補リンク)。ハブの判定では False にして全部使う。"""
    root = parse(html)
    base = page_url
    for n in root.iter():
        if n.tag == "base" and n.attrs.get("href"):
            base = urljoin(page_url, n.attrs["href"])
            break
    host = urlparse(top_url).netloc
    skip = {url_key(page_url), url_key(top_url)}
    texts: dict[str, list[str]] = {}
    first: dict[str, str] = {}  # キー → 最初に見つけた URL(取得にはこちらを使う)
    for n in root.iter():
        href = n.attrs.get("href", "").strip() if n.tag == "a" else ""
        if not href or href.startswith("#"):
            continue
        url = normalize_url(urljoin(base, href))
        p = urlparse(url)
        text = n.text()
        key = url_key(url)
        if p.scheme not in ("http", "https") or p.netloc != host or key in skip:
            continue
        if p.path.lower().endswith(_FILE_EXTS):
            continue
        if "login" in p.path.lower() or "login" in text.lower() or "ログイン" in text:
            continue
        first.setdefault(key, url)
        lst = texts.setdefault(key, [])
        if text and text not in lst:
            lst.append(text)
    links = [Link(first[k], " / ".join(t), 0.0) for k, t in texts.items()]
    for link in links:
        link.score = score_link(link.text, link.url, top_url)
    if positive_only:
        links = [l for l in links if l.score > 0]
    links.sort(key=lambda l: -l.score)  # 同点は文書順(安定ソート)
    return links


def url_shape(url: str) -> str:
    """パスの最後の部分を * にした形(クエリは落とす)。同じ形のリンクを1つのまとまりとみなす。"""
    p = urlparse(url)
    head = p.path.rsplit("/", 1)[0]
    return f"{p.scheme}://{p.netloc}{head}/*"


def group_by_shape(links: list[Link]) -> list[tuple[str, list[Link]]]:
    groups: dict[str, list[Link]] = {}
    for link in links:
        groups.setdefault(url_shape(link.url), []).append(link)
    return sorted(groups.items(), key=lambda kv: -len(kv[1]))

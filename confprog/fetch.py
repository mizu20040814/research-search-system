"""マナーを守ってページを取得する。

- robots.txt を確認し、Disallow なら取得しない(robots.txt が無い場合は許可扱い)
- 同じホストへのアクセスは最低 MIN_INTERVAL 秒空ける(IEICE の Crawl-delay: 7 に合わせる)
- robots.txt の Crawl-delay がそれより長ければそちらに従う
- 取得した HTML は data/raw/ にキャッシュし、2回目以降はネットワークに出ない
- User-Agent を明示する(Confit はボット的な UA を 403 で弾くため、ブラウザ相当の UA にする)
"""
from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

MIN_INTERVAL = 7.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 "
    "conf-program-search/0.1 (academic research; non-commercial)"
)

_last_access: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class FetchError(RuntimeError):
    pass


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser | None:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base in _robots:
        return _robots[base]
    rp = urllib.robotparser.RobotFileParser()
    req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            rp.parse(res.read().decode("utf-8", errors="replace").splitlines())
    except urllib.error.HTTPError as e:
        # 404 などは「制限なし」と扱う(RFC 9309)
        rp = None if e.code >= 400 else rp
    except urllib.error.URLError:
        rp = None
    _robots[base] = rp
    _last_access[p.netloc] = time.monotonic()
    return rp


def _wait(host: str, delay: float) -> None:
    last = _last_access.get(host)
    if last is not None:
        remain = delay - (time.monotonic() - last)
        if remain > 0:
            time.sleep(remain)


def cache_path(url: str, cache_dir: Path) -> Path:
    p = urlparse(url)
    slug = (p.netloc + p.path).strip("/").replace("/", "_") or "index"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return cache_dir / f"{slug[:80]}_{digest}.html"


def fetch(url: str, cache_dir: Path | str = "data/raw", refresh: bool = False) -> str:
    """URL の HTML を返す。キャッシュがあればそれを使う。"""
    cache_dir = Path(cache_dir)
    cached = cache_path(url, cache_dir)
    if cached.exists() and not refresh:
        return cached.read_text(encoding="utf-8")

    host = urlparse(url).netloc
    rp = _robots_for(url)
    delay = MIN_INTERVAL
    if rp is not None:
        if not rp.can_fetch(USER_AGENT, url):
            raise FetchError(f"robots.txt で取得が禁止されています: {url}")
        crawl_delay = rp.crawl_delay(USER_AGENT)
        if crawl_delay:
            delay = max(delay, float(crawl_delay))

    _wait(host, delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            html = res.read().decode(charset, errors="replace")
    except urllib.error.URLError as e:
        raise FetchError(f"取得に失敗しました: {url} ({e})") from e
    finally:
        _last_access[host] = time.monotonic()

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(html, encoding="utf-8")
    return html


if __name__ == "__main__":
    # 使い方: python -m confprog.fetch <URL>   (ページを data/raw/ に保存するだけ)
    import sys

    for target in sys.argv[1:]:
        html = fetch(target)
        print(f"保存しました: {cache_path(target, Path('data/raw'))} ({len(html):,} 文字)")

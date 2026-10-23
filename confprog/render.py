"""ブラウザ(Chromium)でページを描画し、描画後の HTML を返す。

MIRU や Confit のように JavaScript で発表一覧を組み立てるページもあるので、
汎用抽出はどの学会でも「描画後の HTML」を読む。

- 本体の HTML は fetch() 経由で取る(robots.txt 確認・7秒間隔・data/raw/ へのキャッシュ)
- fetch() で取れないページ(証明書の検証に失敗する、ブラウザ以外には空の本文を返す)は、
  ブラウザで robots.txt を確認してから、ブラウザで直接開く
- 描画後の HTML は data/rendered/ にキャッシュする
- 必要なもの: pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

from . import fetch as fetchmod
from .fetch import MIN_INTERVAL, USER_AGENT, FetchError, cache_path, fetch

WAIT_MS = 3000


class RenderError(RuntimeError):
    pass


def render(url: str | None, html: str | None = None, cache_dir: Path | str = "data/rendered",
           refresh: bool = False) -> str:
    """url のページを描画した HTML を返す。html を渡すと、本体はその HTML を使う(通信しない)。"""
    cache_dir = Path(cache_dir)
    if url and html is not None:
        # 渡された HTML ごとに別のキャッシュにする(同じ URL でも中身を変えたら描画し直す)
        cached = cache_path(f"{url}#input={hashlib.sha1(html.encode()).hexdigest()[:12]}", cache_dir)
    elif url:
        cached = cache_path(url, cache_dir)
    else:
        cached = cache_dir / f"local_{hashlib.sha1((html or '').encode()).hexdigest()[:8]}.html"
    # 前回の描画が空だったもの(200字未満)は使わずに描画し直す
    if cached.exists() and not refresh and cached.stat().st_size >= 200:
        return cached.read_text(encoding="utf-8")
    direct = False  # True ならブラウザで直接開く
    if html is None:
        try:
            html = fetch(url, refresh=refresh)
        except FetchError as e:
            if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                raise
            direct = True
    if html is not None and len(html.strip()) < 200:
        direct = True  # 本文が空(JavaScript だけで組み立てるサイトが、ブラウザ以外に空を返す場合)
    if direct and not url:
        raise RenderError("保存済みの HTML が空です")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RenderError(
            "playwright が入っていません。次を実行してください:\n"
            "  pip install playwright\n  python -m playwright install chromium"
        ) from e

    target = url or "http://localhost.invalid/"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CONFPROG_CHROMIUM") or None)
        page = browser.new_page(user_agent=USER_AGENT)
        if direct:
            _check_robots_in_browser(page, url)
        else:
            # 本体だけはキャッシュ済みの HTML を返す(CSS・JS などはブラウザが普通に読み込む)
            page.route(target, lambda r: r.fulfill(body=html, content_type="text/html; charset=utf-8"))
        try:
            page.goto(target, wait_until="load", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(WAIT_MS)
            rendered = page.content()
        except Exception as e:
            raise RenderError(f"描画に失敗しました: {target} ({e})") from e
        finally:
            browser.close()

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(rendered, encoding="utf-8")
    return rendered


def _check_robots_in_browser(page, url: str) -> None:
    """ブラウザで robots.txt を読み、禁止されていれば止める。同じホストへの間隔も守る。"""
    p = urlparse(url)
    host = p.netloc
    rp = urllib.robotparser.RobotFileParser()
    fetchmod._wait(host, MIN_INTERVAL)
    try:
        res = page.goto(f"{p.scheme}://{host}/robots.txt", timeout=30000)
        if res is not None and res.ok:
            rp.parse(page.inner_text("body").splitlines())
            if not rp.can_fetch(USER_AGENT, url):
                raise RenderError(f"robots.txt で取得が禁止されています: {url}")
            delay = rp.crawl_delay(USER_AGENT)
        else:
            delay = None
    finally:
        fetchmod._last_access[host] = time.monotonic()
    fetchmod._wait(host, max(MIN_INTERVAL, float(delay or 0)))
    fetchmod._last_access[host] = time.monotonic()

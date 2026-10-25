"""ページ特定(locate.py)のテスト。取得は偽の関数に差し替え、小さなサイトをたどらせる。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from confprog.fetch import FetchError
from confprog.locate import locate, main

TOP = "https://example.org/conf2026/"
S1, S2, S3 = (f"{TOP}session/s{i}" for i in (1, 2, 3))


def fake(pages):
    def get(url):
        if url not in pages:
            raise FetchError(f"取得に失敗しました: {url}")
        return pages[url]
    return get


def list_page(tag, hrefs=None):
    """発表一覧：タイトル(20字以上)と著者2名の行が3つある表。hrefs があればタイトルをリンクにする。"""
    rows = []
    for i in range(3):
        title = f"{tag}に関する研究の第{i + 1}報告と提案手法の評価"
        if hrefs:
            title = f'<a href="{hrefs[i]}">{title}</a>'
        rows.append(f'<tr><td class="t">{title}</td></tr><tr><td class="a">山田 太郎, 佐藤 花子 (架空大)</td></tr>')
    return f"<html><body><table>{''.join(rows)}</table></body></html>"


def top_with(*links):
    """一覧ではないページ(リンクと挨拶だけ)。links は (URL, 文字) の組。"""
    a = "".join(f'<a href="{u}">{t}</a>' for u, t in links)
    return f'<html><body><nav>{a}<a href="{TOP}access.html">アクセス</a></nav><p>ようこそ</p></body></html>'


LIST_A = list_page("画像認識")
SESSIONS = {S1: list_page("音声"), S2: list_page("言語"), S3: list_page("検索")}
HUB = list_page("セッション", hrefs=[S1, S2, S3])

HUB_SITE = {TOP: top_with((TOP + "program/", "プログラム")),
            TOP + "program/": top_with((TOP + "program/sessions.html", "一般セッション")),
            TOP + "program/sessions.html": HUB, **SESSIONS}
DETAIL_SITE = {TOP: top_with((TOP + "program.html", "プログラム")),
               TOP + "program.html": list_page("詳細", hrefs=[f"{TOP}p/{i}.html" for i in (1, 2, 3)]),
               **{f"{TOP}p/{i}.html": f"<html><body><h1>詳細に関する研究の第{i}報告と提案手法の評価</h1><p>山田 太郎</p></body></html>"
                  for i in (1, 2, 3)}}
JA_EN_SITE = {TOP: top_with((TOP + "program.html", "プログラム"), (TOP + "en/program.html", "Program")),
              TOP + "program.html": LIST_A, TOP + "en/program.html": LIST_A}
MANY_LINKS_SITE = {TOP: top_with(*[(f"{TOP}p{i}.html", f"プログラム{i}") for i in range(10)]),
                   **{f"{TOP}p{i}.html": top_with((f"{TOP}q{i}.html", "日程")) for i in range(10)}}
DEEP_SITE = {TOP: top_with((TOP + "a.html", "プログラム")), TOP + "a.html": top_with((TOP + "b.html", "プログラム")),
             TOP + "b.html": top_with((TOP + "c.html", "プログラム")), TOP + "c.html": LIST_A}
LOOP_SITE = {TOP: top_with((TOP + "a.html", "プログラム")),
             TOP + "a.html": top_with((TOP, "プログラム"), (TOP + "b.html", "日程")),
             TOP + "b.html": top_with((TOP + "a.html", "プログラム"))}
TOP_HUB_SITE = {TOP: HUB, **SESSIONS}
HUB_SAMPLE_ERROR_SITE = {TOP: HUB, S2: SESSIONS[S2], S3: SESSIONS[S3]}


class LocateTest(unittest.TestCase):
    def test_top_is_list(self):
        r = locate(TOP, get=fake({TOP: LIST_A}))
        self.assertEqual(r.pages, [TOP])

    def test_list_outside_top_dir(self):
        url = "https://example.org/proceedings/2026/"
        r = locate(TOP, get=fake({TOP: top_with((url, "プログラム")), url: LIST_A}))
        self.assertEqual(r.pages, [url])

    def test_hub_two_levels(self):
        r = locate(TOP, get=fake(HUB_SITE))
        self.assertEqual(r.pages, [S1, S2, S3])
        self.assertIn("hub", [v.verdict for v in r.visits])

    def test_detail_links_are_not_hub(self):
        r = locate(TOP, get=fake(DETAIL_SITE))
        self.assertEqual(r.pages, [TOP + "program.html"])

    def test_not_found(self):
        r = locate(TOP, get=fake({TOP: top_with()}))
        self.assertEqual(r.pages, [])

    def test_error_page_recorded(self):
        r = locate(TOP, get=fake({TOP: top_with((TOP + "missing.html", "プログラム"))}))
        self.assertEqual(r.pages, [])
        self.assertEqual([v.verdict for v in r.visits if v.url.endswith("missing.html")], ["error"])

    def test_duplicate_removed(self):
        r = locate(TOP, get=fake(JA_EN_SITE))
        self.assertEqual(r.pages, [TOP + "program.html"])
        self.assertIn("duplicate", [v.verdict for v in r.visits])

    def test_page_limit(self):
        r = locate(TOP, get=fake(MANY_LINKS_SITE), max_pages=5)
        self.assertLessEqual(len(r.visits), 5)

    def test_depth_limit(self):
        r = locate(TOP, get=fake(DEEP_SITE), max_depth=2)
        self.assertEqual(r.pages, [])

    def test_no_loop(self):
        r = locate(TOP, get=fake(LOOP_SITE))
        urls = [v.url for v in r.visits]
        self.assertEqual(len(urls), len(set(urls)))

    def test_top_is_hub(self):
        r = locate(TOP, get=fake(TOP_HUB_SITE))
        self.assertEqual(r.pages, [S1, S2, S3])

    def test_hub_sample_error(self):
        r = locate(TOP, get=fake(HUB_SAMPLE_ERROR_SITE))
        self.assertEqual(r.pages, [TOP])
        self.assertIn("error", [v.verdict for v in r.visits if v.url == S1])


class MainTest(unittest.TestCase):
    def test_single_url_writes_json(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("confprog.locate.render", fake({TOP: LIST_A})):
            out = Path(d) / "r.json"
            self.assertEqual(main([TOP, "--out", str(out)]), 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["pages"], [TOP])
            self.assertEqual(data["visits"][0]["verdict"], "list")

    def test_list_continues_after_failure(self):
        other = "https://other.example.org/"
        with tempfile.TemporaryDirectory() as d, mock.patch("confprog.locate.render", fake({TOP: LIST_A})):
            csv_path = Path(d) / "conferences.csv"
            csv_path.write_text(f"学会,年,トップURL,メモ\nBAD,2026,{other},\nOK,2026,{TOP},\n", encoding="utf-8")
            self.assertEqual(main(["--list", str(csv_path), "--out-dir", d]), 0)
            self.assertEqual(json.loads((Path(d) / "ok2026.json").read_text(encoding="utf-8"))["pages"], [TOP])
            summary = (Path(d) / "summary.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(summary), 3)
            self.assertTrue(summary[1].startswith("BAD,2026,0,"))


if __name__ == "__main__":
    unittest.main()

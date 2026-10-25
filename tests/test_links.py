"""ページ特定の候補リンク(links.py)のテスト。通信はしない。"""
import unittest

from confprog.links import Link, collect_links, group_by_shape, normalize_url, score_link

TOP = "https://example.org/conf2026/"


class ScoreTest(unittest.TestCase):
    def test_positive_with_bonus(self):
        # リンク文字の「プログラム」と URL の "program"、トップの階層の下
        self.assertEqual(score_link("プログラム", "https://example.org/conf2026/program.html", TOP), 1 + 1 + 0.5)

    def test_negative_outweighs(self):
        self.assertLess(score_link("プログラム委員", "https://example.org/conf2026/committee.html", TOP), 0)

    def test_case_insensitive_outside_top(self):
        self.assertEqual(score_link("Timetable", "https://example.org/x/t", TOP), 1)


class CollectTest(unittest.TestCase):
    HTML = """<html><head><base href="https://example.org/conf2026/"></head><body>
      <a href="program.html">プログラム</a><a href="program.html#day1">1日目</a>
      <a href="../conf2026/index.html">トップ</a><a href="Proc.PDF">プログラム(PDF)</a>
      <a href="a.pdf?v=1">プログラム</a><a href="mailto:x@example.org">連絡</a>
      <a href="#top">上へ</a><a href="https://other.example.com/program">プログラム</a>
      <a href="login">ログイン</a><a href="registration.html">参加登録</a></body></html>"""

    def test_only_same_host_html_pages(self):
        urls = [l.url for l in collect_links(self.HTML, TOP, TOP)]
        self.assertEqual(urls, ["https://example.org/conf2026/program.html"])

    def test_texts_joined(self):
        l = collect_links(self.HTML, TOP, TOP)[0]
        self.assertEqual(l.text, "プログラム / 1日目")

    def test_relative_without_base(self):
        html = '<a href="../sub/program.html">プログラム</a>'
        urls = [l.url for l in collect_links(html, TOP + "news/", TOP)]
        self.assertEqual(urls, ["https://example.org/conf2026/sub/program.html"])

    def test_all_links_for_hub_check(self):
        # ハブの判定ではリンクの点数を問わず、同じホストのページを全部使う
        html = '<a href="/ev/s/a1">基礎理論</a><a href="/ev/s/b2">応用</a>'
        self.assertEqual(collect_links(html, TOP, TOP), [])
        self.assertEqual(len(collect_links(html, TOP, TOP, positive_only=False)), 2)

    def test_trailing_slash_merged(self):
        html = '<a href="/conf2026/program">プログラム</a><a href="/conf2026/program/">日程</a><a href="/conf2026">トップ</a>'
        links = collect_links(html, TOP, TOP)
        self.assertEqual([l.url for l in links], ["https://example.org/conf2026/program"])

    def test_sorted_by_score(self):
        html = '<a href="/x/timetable">日程</a><a href="/conf2026/program">プログラム</a>'
        urls = [l.url for l in collect_links(html, TOP, TOP)]
        self.assertEqual(urls[0], "https://example.org/conf2026/program")


class NormalizeTest(unittest.TestCase):
    def test_index_and_fragment(self):
        self.assertEqual(normalize_url("https://e.org/a/index.html#x"), "https://e.org/a/")
        self.assertEqual(normalize_url("https://e.org/a/index.htm"), "https://e.org/a/")


class ShapeTest(unittest.TestCase):
    def test_group(self):
        ls = [Link(f"https://e.org/ev/session/{k}", "", 0) for k in ("a1", "b2", "c3")]
        ls.append(Link("https://e.org/ev/table/d1", "", 0))
        groups = group_by_shape(ls)
        self.assertEqual(groups[0][0], "https://e.org/ev/session/*")
        self.assertEqual(len(groups[0][1]), 3)

    def test_query_dropped(self):
        self.assertEqual(group_by_shape([Link("https://e.org/p/x?id=1", "", 0)])[0][0], "https://e.org/p/*")


if __name__ == "__main__":
    unittest.main()

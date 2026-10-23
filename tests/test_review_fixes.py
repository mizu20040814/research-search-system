"""外部レビュー(2026-10-07)で見つかった誤りの再発を防ぐテスト。"""
import tempfile
import unittest
from pathlib import Path

from confprog.authors import parse_authors
from confprog.fetch import cache_path
from confprog.generic import _split_lead_id, extract
from confprog.render import render


def _page(rows: str) -> str:
    return f"<html><body><h2>セッション1</h2><table>{rows}</table></body></html>"


class LeadIdTest(unittest.TestCase):
    def test_words_without_digits_are_not_ids(self):
        for t in ("Self-supervised depth estimation", "Semi-supervised learning for X", "Multi-task learning"):
            self.assertEqual(_split_lead_id(t), (None, t))

    def test_bracketed_id_is_split(self):
        self.assertEqual(_split_lead_id("[S1-P01] 画像の超解像"), ("S1-P01", "画像の超解像"))

    def test_titles_starting_with_hyphenated_words_are_kept(self):
        titles = ["Self-supervised depth estimation from video",
                  "Semi-supervised segmentation with few labels",
                  "Multi-task learning for driving scenes"]
        rows = "".join(f"<tr><td>{t}</td><td>山田 太郎, 佐藤 花子</td></tr>" for t in titles)
        items, _ = extract(_page(rows), "TEST", 2026)
        self.assertEqual([p.title for p in items], titles)


class SuperscriptTest(unittest.TestCase):
    def test_superscript_kept_in_title_removed_in_authors(self):
        rows = "".join(
            f"<tr><td>H<sup>{k}</sup> 制御による頑健な推定の研究 第{k}報</td>"
            f"<td>山田 太郎<sup>1</sup>、佐藤 花子<sup>2</sup></td></tr>" for k in (1, 2, 3))
        items, _ = extract(_page(rows), "TEST", 2026)
        self.assertEqual(items[1].title, "H2 制御による頑健な推定の研究 第2報")
        self.assertEqual(len({p.title for p in items}), 3)
        self.assertEqual(items[0].authors, ["山田 太郎", "佐藤 花子"])


class AndAfterAffiliationTest(unittest.TestCase):
    def test_and_after_parenthesis(self):
        names, affs = parse_authors("Alice Smith (University A) and Bob Jones (University B)")
        self.assertEqual(names, ["Alice Smith", "Bob Jones"])
        self.assertEqual(affs, ["University A", "University B"])

    def test_and_inside_parenthesis_is_not_split(self):
        names, _ = parse_authors("Alice Smith (Research and Development Lab)")
        self.assertEqual(names, ["Alice Smith"])


class RenderCacheTest(unittest.TestCase):
    def test_given_html_has_its_own_cache(self):
        url = "https://example.org/program"
        with tempfile.TemporaryDirectory() as d:
            # URL だけのキャッシュ(古い描画結果)があっても、渡した HTML の描画結果を返す
            cache_path(url, Path(d)).write_text("old" * 100, encoding="utf-8")
            html = "<html><body>new</body></html>" * 10
            self.assertNotEqual(cache_path(url, Path(d)), cache_path(url + "#input=x", Path(d)))
            import hashlib
            key = f"{url}#input={hashlib.sha1(html.encode()).hexdigest()[:12]}"
            cache_path(key, Path(d)).write_text("new" * 100, encoding="utf-8")
            self.assertEqual(render(url, html=html, cache_dir=d), "new" * 100)


if __name__ == "__main__":
    unittest.main()

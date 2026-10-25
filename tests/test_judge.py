"""発表一覧かどうかの判定(judge_list)のテスト。ページ特定で、開いたページを採用するかの判断に使う。"""
import unittest
from pathlib import Path

from confprog.generic import judge_list

FIX = Path(__file__).parent / "fixtures"


class JudgeListTest(unittest.TestCase):
    def test_program_pages_are_lists(self):
        # miru_sample.html(描画前で発表は JS の中)と anlp_sample.html(発表2件)は対象外。
        # 実物の MIRU・ANLP のページは PC の data/ で確かめる
        for name in ("generic_table.html", "generic_list.html", "generic_br.html"):
            v = judge_list((FIX / name).read_text(encoding="utf-8"))
            self.assertTrue(v.is_list, f"{name}: {v.reason}")
            self.assertEqual(v.reason, "ok")

    def test_menu_is_not_list(self):
        v = judge_list((FIX / "locate_menu.html").read_text(encoding="utf-8"))
        self.assertFalse(v.is_list)
        self.assertIn("長さ", v.reason)

    def test_news_is_not_list(self):
        v = judge_list((FIX / "locate_news.html").read_text(encoding="utf-8"))
        self.assertFalse(v.is_list)
        self.assertIn("著者", v.reason)

    def test_no_repeated_field(self):
        v = judge_list("<html><body><p>ようこそ</p></body></html>")
        self.assertFalse(v.is_list)
        self.assertEqual(v.title_count, 0)
        self.assertEqual(v.reason, "繰り返しの欄なし")

    def test_titles_returned(self):
        v = judge_list((FIX / "generic_table.html").read_text(encoding="utf-8"))
        self.assertEqual(v.titles[0], "深層学習による画像の超解像に関する研究")


if __name__ == "__main__":
    unittest.main()

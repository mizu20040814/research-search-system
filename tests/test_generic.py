"""汎用抽出(構造推定)のテスト。MIRU・ANLP とは違う形の小さなページで、学会別の設定なしに動くかを見る。"""
import unittest
from pathlib import Path

from confprog.authors import parse_authors
from confprog.generic import extract

FIX = Path(__file__).parent / "fixtures"


class GenericTableTest(unittest.TestCase):
    """表の各列に 番号・タイトル・著者 が並ぶ形"""

    def setUp(self):
        self.items, self.inf = extract((FIX / "generic_table.html").read_text(encoding="utf-8"), "TEST", 2026)

    def test_titles(self):
        self.assertEqual(len(self.items), 6)
        self.assertEqual(self.items[0].title, "深層学習による画像の超解像に関する研究")

    def test_authors_and_session(self):
        self.assertEqual(self.items[0].authors, ["山田 太郎", "佐藤 花子"])
        self.assertEqual(self.items[3].session, "セッション2：音声とロボット")
        self.assertEqual(self.items[4].presentation_id, "2-2")


class GenericListTest(unittest.TestCase):
    """dt にタイトル(リンク)、dd に著者が入る形"""

    def setUp(self):
        self.items, self.inf = extract((FIX / "generic_list.html").read_text(encoding="utf-8"), "TEST", 2026)

    def test_titles_and_links(self):
        self.assertEqual([p.title for p in self.items][2], "Graph Neural Networks for Traffic Forecasting")
        self.assertEqual(self.items[2].url, "/p/1-3.pdf")

    def test_authors_and_session(self):
        self.assertEqual(self.items[2].authors, ["Taro Yamada", "Hanako Sato"])
        self.assertEqual(self.items[5].session, "一般セッション B")


class GenericBrTest(unittest.TestCase):
    """1つの要素の中に「[番号] タイトル <br> 著者」が入り、見出しに時刻を含む形(YANS 型)"""

    def setUp(self):
        self.items, self.inf = extract((FIX / "generic_br.html").read_text(encoding="utf-8"), "TEST", 2026)

    def test_split_lines(self):
        self.assertEqual(len(self.items), 6)
        self.assertEqual(self.items[1].title, "大規模言語モデルを用いた要約の評価手法")
        self.assertEqual(self.items[1].presentation_id, "S1-P02")
        self.assertEqual(self.items[0].authors, ["山田 太郎", "佐藤 花子"])

    def test_session_with_time(self):
        self.assertEqual(self.items[4].session, "[11:00-12:00] ポスターセッション (2)")


class NestedAffiliationTest(unittest.TestCase):
    def test_nested_parens(self):
        names, affs = parse_authors("A Lima (Federal Univ., Instituto (IMPA)), B Novello (IMPA)")
        self.assertEqual(names, ["A Lima", "B Novello"])
        self.assertIn("Instituto (IMPA)", affs)


if __name__ == "__main__":
    unittest.main()

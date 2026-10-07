import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from confprog.extractors import anlp  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "anlp_sample.html"
URL = "https://www.anlp.jp/proceedings/annual_meeting/2026/"


class TestAnlp(unittest.TestCase):
    def setUp(self):
        self.items = anlp.extract(FIXTURE.read_text(encoding="utf-8"), source_url=URL)

    def test_count(self):
        # 「一般発表」より前の空の表は拾わない
        self.assertEqual([p.presentation_id for p in self.items], ["B2-3", "P1-1"])

    def test_fields(self):
        p = self.items[0]
        self.assertEqual((p.conference, p.event, p.year), ("ANLP", "NLP2026", 2026))
        self.assertEqual(p.session, "A1:口頭発表1")
        self.assertEqual(p.title, "架空の口頭発表 & 再掲")
        self.assertEqual(p.authors, ["山田 太郎", "佐藤 花子", "鈴木 一郎"])
        self.assertEqual(p.affiliations, ["東大", "京大", "NII"])
        self.assertEqual(p.url, "https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/B2-3.pdf")
        self.assertEqual((p.date, p.time, p.session_type), ("2026-03-10", "9:30–11:00", "oral"))

    def test_markers_removed(self):
        p = self.items[1]
        self.assertEqual(p.authors, ["Taro Yamada", "Hanako Sato"])
        self.assertEqual(p.session_type, "poster")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from confprog.authors import parse_authors  # noqa: E402
from confprog.extractors import miru  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "miru_sample.html"
URL = "https://miru-committee.github.io/miru2026/program/timetable/"


class TestMiru(unittest.TestCase):
    def setUp(self):
        self.items = miru.extract(FIXTURE.read_text(encoding="utf-8"), source_url=URL)

    def test_count_and_order(self):
        # 非公開セッション・休憩・presentations に無い ID は除外される
        self.assertEqual([p.presentation_id for p in self.items], ["OS1-1", "OS1-2", "IS1-001"])

    def test_schema_fields(self):
        p = self.items[0]
        self.assertEqual((p.conference, p.event, p.year), ("MIRU", "MIRU2026", 2026))
        self.assertEqual(p.session, "オーラル1：認識")
        self.assertEqual(p.title, "拡散モデルによる少数ショット物体検出")
        self.assertEqual(p.authors, ["山田 太郎", "佐藤 花子"])
        self.assertEqual(p.url, "https://example.org/os1-1")
        self.assertEqual(p.date, "2026-07-30")
        self.assertEqual(p.time, "9:30–10:50")
        self.assertEqual(p.session_type, "oral")

    def test_title_falls_back_to_english(self):
        self.assertEqual(self.items[1].title, "Self-supervised depth estimation")

    def test_sheets_serial_values(self):
        p = self.items[2]
        self.assertEqual(p.date, "2026-07-30")
        self.assertEqual(p.time, "13:30–15:00")

    def test_empty_data_raises(self):
        html = FIXTURE.read_text(encoding="utf-8")
        start = html.index("const embeddedPresentationsData")
        end = html.index(";", start)
        html = html[:start] + "const embeddedPresentationsData = []" + html[end:]
        with self.assertRaises(miru.ExtractError):
            miru.extract(html, source_url=URL)


class TestMinifiedPage(unittest.TestCase):
    """本番ページは JS が圧縮されていて、キーに引用符が無く true が !0 になっている。"""

    def test_minified_literals(self):
        html = (
            '<script>const embeddedScheduleData=[{active:!0,date:"2026-08-03",start:"9:00",end:"10:00",'
            'session_code:"OS-1A",title_jp:"オーラル 1A",type:"oral",show_program:!0},'
            '{active:!1,date:"2026-08-03",start:"9:00",end:"10:00",session_code:"X",show_program:!0}],'
            'embeddedPresentationsData=[{"":"dup",authors:"山田太郎（東大）",presentation_id:"OS1A-01",'
            'title_jp:"タイトル",n:1e3}],'
            'embeddedSessionItemsData=[{order:1,presentation_id:"OS1A-01",session_code:"OS-1A"}],'
            'CURRENT_LANG="ja";init(embeddedScheduleData||[],embeddedPresentationsData||[])</script>'
        )
        items = miru.extract(html, source_url=URL)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "タイトル")
        self.assertEqual(items[0].authors, ["山田太郎"])


class TestAuthors(unittest.TestCase):
    def test_japanese_separators(self):
        names, affs = parse_authors("鈴木一郎・高橋次郎（大阪大学）、田中三郎（NII）")
        self.assertEqual(names, ["鈴木一郎", "高橋次郎", "田中三郎"])
        self.assertEqual(affs, ["大阪大学", "NII"])

    def test_english_and(self):
        names, _ = parse_authors("Taro Yamada and Hanako Sato (UTokyo), Ichiro Suzuki (Kyoto U.)")
        self.assertEqual(names, ["Taro Yamada", "Hanako Sato", "Ichiro Suzuki"])

    def test_comma_inside_affiliation(self):
        names, affs = parse_authors("○山田太郎 (東大, 理研), 佐藤花子 (京大)")
        self.assertEqual(names, ["山田太郎", "佐藤花子"])
        self.assertEqual(affs, ["東大", "理研", "京大"])


if __name__ == "__main__":
    unittest.main()

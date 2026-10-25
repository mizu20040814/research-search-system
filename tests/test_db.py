import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from confprog.db import build_db, build_records, classify_kind, detect_lang, load_db, normalize_title


def payload(items, event="EV2026", year=2026, method="generic-structure-v2.2"):
    base = {"conference": "EV", "event": event, "year": year, "session": "S", "authors": [],
            "affiliations": [], "url": None, "presentation_id": None, "source_url": "u"}
    return {"method": method, "conference": "EV", "year": year, "source_url": "u",
            "extracted_at": "2026-10-23T00:00:00+00:00",
            "presentations": [dict(base, **it) for it in items]}


class BuildRecordsTest(unittest.TestCase):
    def test_same_pid_merged(self):
        recs, _ = build_records([payload([{"title": "T", "presentation_id": "A-1"},
                                          {"title": "T", "presentation_id": "A-1"}])])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["slots"], 2)
        self.assertEqual(recs[0]["id"], "EV2026:A-1")

    def test_same_title_without_pid_merged(self):
        recs, _ = build_records([payload([{"title": "深層学習 の 評価"},
                                          {"title": "深層学習　の  評価 "}])])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["slots"], 2)

    def test_id_without_pid(self):
        recs, _ = build_records([payload([{"title": "深層学習 の 評価"}])])
        digest = hashlib.sha1(normalize_title("深層学習 の 評価").encode("utf-8")).hexdigest()[:10]
        self.assertEqual(recs[0]["id"], "EV2026:t-" + digest)

    def test_pid_conflict_gets_suffix(self):
        recs, warns = build_records([payload([{"title": "T1", "presentation_id": "A-1"},
                                              {"title": "T2", "presentation_id": "A-1"}])])
        self.assertEqual([r["id"] for r in recs], ["EV2026:A-1", "EV2026:A-1#2"])
        self.assertEqual(len(warns), 1)

    def test_session_from_first_slot(self):
        recs, _ = build_records([payload([{"title": "T", "session": "オーラル"},
                                          {"title": "T", "session": "インタラクティブ"}])])
        self.assertEqual(recs[0]["session"], "オーラル")

    def test_blank_title_is_skipped(self):
        recs, warns = build_records([payload([{"title": "  "}, {"title": "T"}])])
        self.assertEqual(len(recs), 1)
        self.assertEqual(sum("空のタイトル" in w for w in warns), 1)

    def test_year_zero_warns(self):
        recs, warns = build_records([payload([{"title": "T"}], event="IEICE", year=0)])
        self.assertEqual(len(recs), 1)
        self.assertTrue(any("year" in w for w in warns))

    def test_extractor_fields(self):
        recs, _ = build_records([payload([{"title": "T"}])])
        self.assertEqual(recs[0]["extractor"], "generic-structure-v2.2")
        self.assertEqual(recs[0]["extracted_at"], "2026-10-23T00:00:00+00:00")
        self.assertEqual(list(recs[0])[0], "id")


class HelpersTest(unittest.TestCase):
    def test_kind(self):
        for s in ["招待講演 1A", "招待論文", "基調講演", "Invited Talk", "KEYNOTE"]:
            self.assertEqual(classify_kind(s), "invited", s)
        for s in ["チュートリアル", "tutorial"]:
            self.assertEqual(classify_kind(s), "tutorial", s)
        self.assertEqual(classify_kind("オーラル 1A"), "general")
        self.assertEqual(classify_kind(None), "general")

    def test_lang(self):
        self.assertEqual(detect_lang("深層学習"), "ja")
        self.assertEqual(detect_lang("Deep Learning"), "en")
        self.assertEqual(detect_lang("CLIPの評価"), "ja")


class BuildDbTest(unittest.TestCase):
    def test_build_db_files(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            write = lambda name, p: (out / name).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            write("generic_a.json", payload([{"title": "旧"}]))
            write("generic_b.json", payload([{"title": "新1"}, {"title": "新2"}]))
            write("generic_a_eval.json", {"slots": {}})
            db = Path(d) / "db" / "presentations.jsonl"
            recs, warns = build_db(out, db)
            self.assertEqual(sorted(r["title"] for r in recs), ["新1", "新2"])
            self.assertEqual(sum("EV2026" in w for w in warns), 1)
            self.assertEqual(len(load_db(db)), 2)

    def test_build_db_merges_pages_of_same_event(self):
        # IPSJ の program1・program3 のように、同じ大会の別ページは結合する
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            out.mkdir()
            p1 = payload([{"title": "A"}, {"title": "共通"}])
            p1["source_url"] = "https://example.org/program1.html"
            p3 = payload([{"title": "B"}, {"title": "共通"}])
            p3["source_url"] = "https://example.org/program3.html"
            for name, p in [("generic_ev_p1.json", p1), ("generic_ev_p3.json", p3)]:
                (out / name).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
            recs, warns = build_db(out, Path(d) / "db.jsonl")
            self.assertEqual(sorted(r["title"] for r in recs), ["A", "B", "共通"])
            self.assertEqual(next(r for r in recs if r["title"] == "共通")["slots"], 2)
            self.assertEqual(warns, [])


if __name__ == "__main__":
    unittest.main()

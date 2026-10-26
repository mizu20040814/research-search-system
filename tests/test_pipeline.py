import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from confprog import pipeline
from confprog.locate import LocateResult
from confprog.schema import Presentation


class FakeInference:
    def describe(self):
        return {"title_path": "li > a"}


class Fakes:
    """pages: トップURL → 見つかったページ。counts: ページ → 発表の件数(例外なら投げる)。"""

    def __init__(self, pages, counts):
        self.pages = pages
        self.counts = counts
        self.located = []

    def locate_fn(self, url, year):
        self.located.append((url, year))
        p = self.pages[url]
        if isinstance(p, Exception):
            raise p
        return LocateResult(url, list(p))

    def render_fn(self, url):
        return url  # HTML の代わりに URL をそのまま渡す

    def extract_fn(self, html, conference, year, source_url):
        n = self.counts[html]
        if isinstance(n, Exception):
            raise n
        items = [Presentation(conference, f"{conference}{year}", year, "S", f"{source_url} の発表{i}", ["A"],
                              source_url=source_url) for i in range(n)]
        return items, FakeInference()

    def fns(self):
        return dict(locate_fn=self.locate_fn, render_fn=self.render_fn, extract_fn=self.extract_fn)


def row(name="EV", year="2026", url="top"):
    return {"学会": name, "年": year, "トップURL": url, "メモ": ""}


def write_prev(out_dir, key, n, count=1, conference="EV", year=2026):
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"method": "old", "conference": conference, "year": year, "source_url": f"old{n}", "count": count,
               "presentations": [{"conference": conference, "event": f"{conference}{year}", "year": year,
                                  "session": "S", "title": f"前回{n}-{i}", "authors": []} for i in range(count)]}
    (out_dir / f"generic_{key}_{n:02d}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BuildOneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "batch"

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, key="ev2026"):
        return sorted(p.name for p in self.out.glob(f"generic_{key}_*.json"))

    def test_conf_key(self):
        self.assertEqual(pipeline.conf_key("MIRU", 2026), "miru2026")

    def test_success_writes_pages_and_locate(self):
        f = Fakes({"top": ["p1", "p2"]}, {"p1": 2, "p2": 3})
        r = pipeline.build_one(row(), self.out, **f.fns())
        self.assertEqual((r.status, r.pages_found, r.pages_extracted, r.count), ("成功", 2, 2, 5))
        self.assertEqual(f.located, [("top", 2026)])
        self.assertEqual(self.files(), ["generic_ev2026_01.json", "generic_ev2026_02.json"])
        self.assertTrue((self.out / "locate_ev2026.json").exists())
        d = json.loads((self.out / "generic_ev2026_02.json").read_text(encoding="utf-8"))
        self.assertEqual((d["conference"], d["year"], d["source_url"], d["count"]), ("EV", 2026, "p2", 3))
        self.assertEqual(d["method"], "generic-structure-v2.2")
        self.assertEqual(d["inference"], {"title_path": "li > a"})
        self.assertEqual(len(d["presentations"]), 3)

    def test_page_with_no_items_is_skipped(self):
        f = Fakes({"top": ["p1", "p2"]}, {"p1": 0, "p2": 3})
        r = pipeline.build_one(row(), self.out, **f.fns())
        self.assertEqual((r.status, r.pages_extracted, r.count), ("成功", 1, 3))
        self.assertEqual(self.files(), ["generic_ev2026_01.json"])
        self.assertIn("p1", r.reason)

    def test_failure_keeps_previous(self):
        write_prev(self.out, "ev2026", 1)
        before = (self.out / "generic_ev2026_01.json").read_text(encoding="utf-8")
        r = pipeline.build_one(row(), self.out, **Fakes({"top": []}, {}).fns())
        self.assertEqual(r.status, "前回分を使用")
        self.assertEqual((self.out / "generic_ev2026_01.json").read_text(encoding="utf-8"), before)

    def test_failure_without_previous(self):
        f = Fakes({"top": ["p1", "p2"]}, {"p1": ValueError("x"), "p2": ValueError("y")})
        r = pipeline.build_one(row(), self.out, **f.fns())
        self.assertEqual(r.status, "失敗（前回分なし）")
        self.assertEqual(self.files(), [])

    def test_success_replaces_old_files(self):
        for n in (1, 2, 3):
            write_prev(self.out, "ev2026", n)
        r = pipeline.build_one(row(), self.out, **Fakes({"top": ["p1", "p2"]}, {"p1": 1, "p2": 1}).fns())
        self.assertEqual(r.status, "成功")
        self.assertEqual(self.files(), ["generic_ev2026_01.json", "generic_ev2026_02.json"])
        d = json.loads((self.out / "generic_ev2026_01.json").read_text(encoding="utf-8"))
        self.assertEqual(d["source_url"], "p1")

    def test_other_conference_files_untouched(self):
        write_prev(self.out, "ev20261", 1)  # キーの前方一致で消さない
        pipeline.build_one(row(), self.out, **Fakes({"top": ["p1"]}, {"p1": 1}).fns())
        self.assertEqual(self.files("ev20261"), ["generic_ev20261_01.json"])

    def test_unexpected_exception_is_recorded(self):
        r = pipeline.build_one(row(), self.out, **Fakes({"top": RuntimeError("boom")}, {}).fns())
        self.assertEqual(r.status, "失敗（前回分なし）")
        self.assertIn("RuntimeError: boom", r.reason)

    def test_bad_year(self):
        f = Fakes({"top": ["p1"]}, {"p1": 1})
        r = pipeline.build_one(row(year="abc"), self.out, **f.fns())
        self.assertEqual(r.status, "失敗（前回分なし）")
        self.assertEqual(f.located, [])

    def test_previous_result_counts(self):
        write_prev(self.out, "ev2026", 1, count=3)
        write_prev(self.out, "ev2026", 2, count=4)
        (self.out / "locate_ev2026.json").write_text(json.dumps({"top_url": "t", "pages": ["a", "b", "c"]}),
                                                     encoding="utf-8")
        r = pipeline.previous_result("ev2026", self.out)
        self.assertEqual((r.conference, r.year, r.status, r.pages_found, r.pages_extracted, r.count),
                         ("EV", 2026, "前回分", 3, 2, 7))
        self.assertIsNone(pipeline.previous_result("none2026", self.out))

    def test_row_missing_url(self):
        r = pipeline.build_one({"学会": "EV", "年": "2026", "トップURL": None}, self.out,
                               **Fakes({}, {}).fns())
        self.assertEqual(r.status, "失敗（前回分なし）")
        self.assertIn("トップURL", r.reason)

    def test_swap_failure_restores_previous(self):
        from unittest import mock
        write_prev(self.out, "ev2026", 1)
        write_prev(self.out, "ev2026", 2)
        before = {p.name: p.read_text(encoding="utf-8") for p in self.out.glob("generic_*.json")}
        real_move = pipeline.shutil.move
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if "_new" in str(src) and len([c for c in calls if "_new" in str(c)]) == 2:
                raise PermissionError("locked")
            return real_move(src, dst)

        f = Fakes({"top": ["p1", "p2"]}, {"p1": 1, "p2": 1})
        with mock.patch.object(pipeline.shutil, "move", side_effect=flaky):
            r = pipeline.build_one(row(), self.out, **f.fns())
        self.assertEqual(r.status, "前回分を使用")
        self.assertIn("PermissionError", r.reason)
        after = {p.name: p.read_text(encoding="utf-8") for p in self.out.glob("generic_*.json")}
        self.assertEqual(after, before)

    def test_temp_dir_is_removed(self):
        pipeline.build_one(row(), self.out, **Fakes({"top": ["p1"]}, {"p1": 1}).fns())
        pipeline.build_one(row(), self.out, **Fakes({"top": RuntimeError("x")}, {}).fns())
        self.assertFalse((self.out / "_new" / "ev2026").exists())


class RunBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out, self.db = root / "batch", root / "db" / "p.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def summary(self):
        with (self.out / "summary.csv").open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def db_titles(self):
        return [json.loads(line)["title"] for line in self.db.read_text(encoding="utf-8").splitlines()]

    def test_run_build_makes_db_and_summary(self):
        f = Fakes({"t1": ["a"], "t2": ["b"]}, {"a": 2, "b": 1})
        results, n = pipeline.run_build([row("EV", url="t1"), row("FW", url="t2")], self.out, self.db, **f.fns())
        self.assertEqual(n, 3)
        self.assertEqual(len(self.db_titles()), 3)
        raw = (self.out / "summary.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.decode("utf-8-sig").splitlines()[0], "学会,年,状態,見つけたページ数,抽出できたページ数,発表件数,理由")
        self.assertEqual([(r["学会"], r["状態"]) for r in self.summary()], [("EV", "成功"), ("FW", "成功")])

    def test_one_failure_does_not_stop_others(self):
        f = Fakes({"t1": RuntimeError("down"), "t2": ["b"]}, {"b": 1})
        results, n = pipeline.run_build([row("EV", url="t1"), row("FW", url="t2")], self.out, self.db, **f.fns())
        self.assertEqual([r.status for r in results], ["失敗（前回分なし）", "成功"])
        self.assertEqual(n, 1)

    def test_only_keeps_others_in_db_and_summary(self):
        f = Fakes({"t1": ["a"], "t2": ["b"]}, {"a": 2, "b": 1})
        pipeline.run_build([row("EV", url="t1"), row("FW", url="t2")], self.out, self.db, **f.fns())
        results, n = pipeline.run_build([row("FW", url="t2")], self.out, self.db, **f.fns())
        self.assertEqual(n, 3)
        self.assertEqual([(r["学会"], r["状態"]) for r in self.summary()], [("FW", "成功"), ("EV", "前回分")])

    def test_main_cli(self):
        lst = Path(self.tmp.name) / "list.csv"
        lst.write_text("学会,年,トップURL,メモ\nEV,2026,t1,x\nFW,2026,t2,y\n", encoding="utf-8-sig")
        f = Fakes({"t1": ["a"], "t2": ["b"]}, {"a": 2, "b": 1})
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = pipeline.main(["build", "--list", str(lst), "--only", "FW", "--out-dir", str(self.out),
                                  "--db", str(self.db)], **f.fns())
        self.assertEqual(code, 0)
        self.assertIn("FW 2026", out.getvalue())
        self.assertNotIn("EV 2026", out.getvalue())
        self.assertIn("発表DB: 1 件", out.getvalue())

    def test_main_returns_1_when_db_empty(self):
        lst = Path(self.tmp.name) / "list.csv"
        lst.write_text("学会,年,トップURL,メモ\nEV,2026,t1,x\n", encoding="utf-8-sig")
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = pipeline.main(["build", "--list", str(lst), "--out-dir", str(self.out), "--db", str(self.db)],
                                 **Fakes({"t1": []}, {}).fns())
        self.assertEqual(code, 1)

    def test_short_row_does_not_stop_others(self):
        f = Fakes({"t2": ["b"]}, {"b": 1})
        results, n = pipeline.run_build([{"学会": "EV", "年": "2026", "トップURL": None}, row("FW", url="t2")],
                                        self.out, self.db, **f.fns())
        self.assertEqual([r.status for r in results], ["失敗（前回分なし）", "成功"])

    def test_locked_summary_is_a_warning(self):
        (self.out / "summary.csv").mkdir(parents=True)  # 開けないファイルの代わり
        f = Fakes({"t1": ["a"]}, {"a": 1})
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            results, n = pipeline.run_build([row("EV", url="t1")], self.out, self.db, **f.fns())
        self.assertEqual(n, 1)
        self.assertIn("summary.csv", err.getvalue())

    def test_main_rejects_non_utf8_list(self):
        lst = Path(self.tmp.name) / "list.csv"
        lst.write_bytes("学会,年,トップURL,メモ\nEV,2026,t1,x\n".encode("cp932"))
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = pipeline.main(["build", "--list", str(lst), "--out-dir", str(self.out), "--db", str(self.db)],
                                 **Fakes({}, {}).fns())
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", out.getvalue())

    def test_dunder_main_dispatches_build(self):
        from confprog import __main__ as entry
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            entry.main(["build", "--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--only", out.getvalue())


if __name__ == "__main__":
    unittest.main()

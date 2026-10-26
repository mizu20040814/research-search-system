import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

from confprog import search_cli


def payload(titles):
    return {"method": "generic-structure-v2.2", "conference": "EV", "year": 2026, "source_url": "u",
            "extracted_at": "x",
            "presentations": [{"conference": "EV", "event": "EV2026", "year": 2026, "session": "S", "title": t,
                               "authors": ["A", "B", "C", "D"], "presentation_id": None} for t in titles]}


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return np.vstack([np.array([1.0, len(t) % 3, 0.5], dtype="float32") / 2 for t in texts])


class SearchCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.paths = dict(db_path=root / "db" / "p.jsonl", out_dir=root / "out", cache_dir=root / "emb",
                          runs_dir=root / "runs")
        self.paths["out_dir"].mkdir()
        (self.paths["out_dir"] / "generic_ev.json").write_text(
            json.dumps(payload(["深層学習", "画像認識", "音声"]), ensure_ascii=False), encoding="utf-8")
        self.fake = Fake()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv, factory=None):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = search_cli.main(argv, embed_factory=factory or (lambda m: self.fake), **self.paths)
        return code, out.getvalue()

    def test_db_build_then_rank(self):
        self.assertEqual(self.run_cli(["db", "build"])[0], 0)
        code, out = self.run_cli(["rank", "Q", "--top", "2"])
        self.assertEqual(code, 0)
        self.assertIn(" 1.", out)
        self.assertIn("[EV2026]", out)
        self.assertIn("ほか", out)
        self.assertEqual(len(list(self.paths["runs_dir"].glob("*.json"))), 1)

    def test_paths_can_be_given_on_command_line(self):
        root = Path(self.tmp.name)
        other_out = root / "out2"
        other_out.mkdir()
        (other_out / "generic_x.json").write_text(json.dumps(payload(["別の発表"]), ensure_ascii=False),
                                                  encoding="utf-8")
        db = root / "exp" / "db.jsonl"
        self.assertEqual(self.run_cli(["db", "build", "--out-dir", str(other_out), "--db", str(db)])[0], 0)
        self.assertEqual(len(db.read_text(encoding="utf-8").splitlines()), 1)
        runs = root / "exp" / "runs"
        code, out = self.run_cli(["rank", "Q", "--db", str(db), "--cache-dir", str(root / "exp" / "emb"),
                                  "--runs-dir", str(runs)])
        self.assertEqual(code, 0)
        self.assertIn("別の発表", out)
        self.assertEqual(len(list(runs.glob("*.json"))), 1)
        self.assertEqual(len(list((root / "exp" / "emb").glob("*.npy"))), 1)

    def test_rank_without_db_fails(self):
        code, out = self.run_cli(["rank", "Q"])
        self.assertEqual(code, 1)
        self.assertIn("db build", out)

    def test_empty_query_fails(self):
        self.run_cli(["db", "build"])
        self.assertEqual(self.run_cli(["rank", "   "])[0], 1)

    def test_query_file_with_bom(self):
        self.run_cli(["db", "build"])
        f = Path(self.tmp.name) / "q.txt"
        f.write_text("﻿課題", encoding="utf-8")
        self.assertEqual(self.run_cli(["rank", "--query-file", str(f)])[0], 0)
        self.assertEqual(self.fake.calls[-1], ["query: 課題"])

    def test_missing_sentence_transformers(self):
        self.run_cli(["db", "build"])

        def factory(model):
            raise ImportError("No module named 'sentence_transformers'")

        code, out = self.run_cli(["rank", "Q"], factory=factory)
        self.assertEqual(code, 1)
        self.assertIn("pip install sentence-transformers", out)

    def test_model_load_failure(self):
        self.run_cli(["db", "build"])

        def factory(model):
            raise RuntimeError("403 Forbidden")

        code, out = self.run_cli(["rank", "Q", "--model", "x/y"], factory=factory)
        self.assertEqual(code, 1)
        self.assertIn("モデル x/y を読めませんでした", out)

    def test_rank_results_are_sorted(self):
        self.run_cli(["db", "build"])
        self.run_cli(["rank", "Q"])
        run = json.loads(next(self.paths["runs_dir"].glob("*.json")).read_text(encoding="utf-8"))
        scores = [r["score"] for r in run["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_db_fails(self):
        (self.paths["out_dir"] / "generic_ev.json").unlink()
        code, out = self.run_cli(["db", "build"])
        self.assertEqual(code, 0)
        self.assertIn("generic_*.json がありません", out)
        code, out = self.run_cli(["rank", "Q"])
        self.assertEqual(code, 1)
        self.assertIn("空です", out)

    def test_top_must_be_positive(self):
        self.run_cli(["db", "build"])
        with self.assertRaises(SystemExit):
            self.run_cli(["rank", "Q", "--top", "0"])

    def test_query_file_errors(self):
        self.run_cli(["db", "build"])
        self.assertEqual(self.run_cli(["rank", "--query-file", "nai.txt"])[0], 1)
        f = Path(self.tmp.name) / "sjis.txt"
        f.write_bytes("研究課題".encode("cp932"))
        code, out = self.run_cli(["rank", "--query-file", str(f)])
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", out)

    def test_long_query_warning_hook(self):
        self.run_cli(["db", "build"])
        seen = []
        self.fake.warn_if_long = seen.append
        self.run_cli(["rank", "Q"])
        self.assertEqual(seen, ["Q"])


class DemoTest(unittest.TestCase):
    setUp, tearDown, run_cli = SearchCliTest.setUp, SearchCliTest.tearDown, SearchCliTest.run_cli

    def run_demo(self, text, argv=()):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = search_cli.main(["demo", *argv], embed_factory=lambda m: self.fake, stdin=io.StringIO(text),
                                   **self.paths)
        return code, out.getvalue()

    def test_read_query_multiline(self):
        lines = iter(["a\n", "b\n", "\n", "c\n"])
        self.assertEqual(search_cli.read_query(lines), "a\nb")
        self.assertEqual(search_cli.read_query(lines), "c")
        self.assertIsNone(search_cli.read_query(lines))
        # コマンドは空行を待たずに1行で返す
        self.assertEqual(search_cli.read_query(iter([":top 3\n", "x\n"])), ":top 3")

    def test_breakdown(self):
        results = [{"event": "B"}, {"event": "A"}, {"event": "B"}]
        self.assertEqual(search_cli.breakdown(results), "上位3件の内訳：B 2件／A 1件")

    def test_demo_runs_two_queries_then_quits(self):
        self.run_cli(["db", "build"])
        code, out = self.run_demo("深層\n\n音声\n\n:q\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("準備完了"), 1)
        self.assertEqual(out.count(" 1. "), 2)
        self.assertEqual(out.count("の内訳："), 2)
        self.assertEqual(len(list(self.paths["runs_dir"].glob("*.json"))), 2)
        passage_calls = [c for c in self.fake.calls if c and c[0].startswith("passage: ")]
        query_calls = [c for c in self.fake.calls if c and c[0].startswith("query: ")]
        self.assertEqual((len(passage_calls), len(query_calls)), (1, 2))

    def test_demo_top_command(self):
        self.run_cli(["db", "build"])
        code, out = self.run_demo(":top 1\n深層\n\n")
        self.assertEqual(code, 0)
        self.assertIn(" 1. ", out)
        self.assertNotIn(" 2. ", out)
        self.assertIn("上位3件の内訳：", out)

    def test_demo_bad_top(self):
        self.run_cli(["db", "build"])
        code, out = self.run_demo(":top abc\n:top 0\n:q\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.count(":top N（N は1以上）"), 2)

    def test_demo_empty_input_ignored(self):
        self.run_cli(["db", "build"])
        code, out = self.run_demo("\n\n:q\n")
        self.assertEqual(code, 0)
        self.assertNotIn(" 1. ", out)
        self.assertEqual(list(self.paths["runs_dir"].glob("*.json")), [])

    def test_demo_without_db(self):
        code, out = self.run_demo(":q\n")
        self.assertEqual(code, 1)
        self.assertIn("db build", out)


class MainDispatchTest(unittest.TestCase):
    def test_db_and_rank_go_to_search_cli(self):
        from unittest import mock
        from confprog import __main__ as entry
        with mock.patch("confprog.search_cli.main", return_value=7) as m:
            self.assertEqual(entry.main(["db", "build"]), 7)
            self.assertEqual(entry.main(["rank", "Q"]), 7)
            self.assertEqual(entry.main(["demo"]), 7)
        self.assertEqual(m.call_count, 3)

    def test_conference_command_still_parsed(self):
        from confprog import __main__ as entry
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):
            entry.main(["miru", "--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

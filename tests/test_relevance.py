import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from confprog.relevance import load_or_build_embeddings, method_name, passage_text, rank, save_run

E5 = "intfloat/multilingual-e5-base"


class FakeEmbed:
    """文字列の中身で決まるベクトルを返す。呼ばれた文字列を記録する。"""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            body = t.split(": ", 1)[-1]
            v = np.array(self.table.get(body, [0.0, 0.0, 1.0]), dtype="float32")
            out.append(v / np.linalg.norm(v))
        return np.vstack(out)


def R(rid, title, kind="general", session="S"):
    return {"id": rid, "event": "EV", "title": title, "session": session, "authors": ["A"], "kind": kind}


class RelevanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "emb"
        self.recs = [R("a", "近い"), R("b", "遠い"), R("c", "招待", kind="invited")]
        self.embed = FakeEmbed({"近い": [1, 0, 0], "遠い": [0, 1, 0], "招待": [1, 0, 0], "Q": [1, 0.1, 0]})

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, recs=None, digest="h1", with_session=False):
        return load_or_build_embeddings(recs or self.recs, digest, E5, with_session, self.embed, self.cache)

    def test_passage_text(self):
        self.assertEqual(passage_text({"title": "T", "session": "S"}, False), "T")
        self.assertEqual(passage_text({"title": "T", "session": "S"}, True), "T（S）")
        self.assertEqual(passage_text({"title": "T", "session": ""}, True), "T")

    def test_method_name(self):
        self.assertEqual(method_name(E5, False), E5 + "|title")
        self.assertEqual(method_name(E5, True), E5 + "|title+session")

    def test_prefix_applied(self):
        emb = self.build()
        rank("Q", self.recs, emb, E5, self.embed)
        self.assertEqual(self.embed.calls[0][0], "passage: 近い")
        self.assertEqual(self.embed.calls[-1], ["query: Q"])

    def test_rank_orders_and_excludes(self):
        res = rank("Q", self.recs, self.build(), E5, self.embed)
        self.assertEqual([r["id"] for r in res], ["a", "b"])
        self.assertEqual([r["rank"] for r in res], [1, 2])
        self.assertGreater(res[0]["score"], res[1]["score"])

    def test_ties_are_ordered_by_id(self):
        recs = [R("z", "近い"), R("y", "近い")]
        res = rank("Q", recs, self.build(recs), E5, self.embed)
        self.assertEqual([r["id"] for r in res], ["y", "z"])

    def test_top_k(self):
        self.assertEqual(len(rank("Q", self.recs, self.build(), E5, self.embed, top=1)), 1)

    def test_cache_reused(self):
        first = self.build()
        second = self.build()
        self.assertEqual(len(self.embed.calls), 1)
        np.testing.assert_array_equal(first, second)

    def test_cache_rebuilt_when_hash_changes(self):
        self.build(digest="h1")
        self.build(digest="h2")
        self.assertEqual(len(self.embed.calls), 2)

    def test_cache_rebuilt_when_ids_differ(self):
        self.build()
        emb = self.build(recs=list(reversed(self.recs)))
        self.assertEqual(len(self.embed.calls), 2)
        self.assertEqual(emb.shape[0], 3)

    def test_cache_separate_for_session(self):
        self.build(with_session=False)
        self.build(with_session=True)
        self.assertEqual(len(list(self.cache.glob("*.npy"))), 2)

    def test_save_run(self):
        res = rank("Q", self.recs, self.build(), E5, self.embed)
        path = save_run("Q", method_name(E5, False), "h1", 20, res, Path(self.tmp.name) / "runs")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["query"], "Q")
        self.assertEqual(data["method"], E5 + "|title")
        self.assertEqual(data["db_hash"], "h1")
        self.assertEqual(data["top"], 20)
        self.assertEqual([r["id"] for r in data["results"]], ["a", "b"])
        self.assertIn("score", data["results"][0])


if __name__ == "__main__":
    unittest.main()

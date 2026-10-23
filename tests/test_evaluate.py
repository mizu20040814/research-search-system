import unittest

from confprog.evaluate import evaluate, session_match


def P(title, session="S1", authors=("A",), pid=None):
    return {"title": title, "session": session, "authors": list(authors), "presentation_id": pid}


def G(title, session="S1", authors=("A",), pid=None, status="ok"):
    return {"title": title, "session": session, "authors": list(authors), "presentation_id": pid, "status": status}


class EvaluateTest(unittest.TestCase):
    def test_extra_inside_gold_region_counts_even_with_other_session(self):
        # 正しい1件の間に、別のセッション名を付けた誤抽出が挟まっている
        pred = [P("t1"), P("ゴミ", session="X"), P("t2")]
        res = evaluate(pred, [G("t1"), G("t2")])
        self.assertEqual(res["slots"]["recall"], 1.0)
        self.assertLess(res["slots"]["precision"], 1.0)
        self.assertEqual(res["errors"]["extra"], ["ゴミ"])

    def test_items_outside_gold_region_are_ignored(self):
        pred = [P("menu"), P("t1"), P("t2"), P("other", session="S9")]
        res = evaluate(pred, [G("t1"), G("t2")])
        self.assertEqual(res["slots"]["precision"], 1.0)

    def test_session_prefix_respects_boundary(self):
        self.assertTrue(session_match("A1 : 口頭発表1", "A1"))
        self.assertTrue(session_match("オーラル 1A 座長 山田", "オーラル1A"))
        self.assertFalse(session_match("A10", "A1"))

    def test_swapped_sessions_are_detected(self):
        pred = [P("t1", session="S2"), P("t2", session="S1")]
        res = evaluate(pred, [G("t1", "S1"), G("t2", "S2")])
        self.assertEqual(res["slots"]["recall"], 1.0)
        self.assertEqual(res["of_matched"]["session"], 0.0)

    def test_repeated_title_attributes_are_checked_per_slot(self):
        pred = [P("t1", "S1", authors=("X",)), P("t2", "S1"), P("t1", "S2"), P("t3", "S2")]
        gold = [G("t1", "S1"), G("t2", "S1"), G("t1", "S2"), G("t3", "S2")]
        res = evaluate(pred, gold)
        self.assertEqual(res["of_gold"]["authors"], 0.75)

    def test_missing_repeated_slot_is_listed(self):
        pred = [P("t1", "S1"), P("t2", "S1"), P("t3", "S2")]
        gold = [G("t1", "S1"), G("t2", "S1"), G("t1", "S2"), G("t3", "S2")]
        res = evaluate(pred, gold)
        self.assertEqual(res["slots"]["recall"], 0.75)
        self.assertEqual(res["errors"]["missing"], ["t1"])

    def test_draft_gold_is_flagged(self):
        res = evaluate([P("t1")], [G("t1", status="")])
        self.assertTrue(res["gold_status"].startswith("DRAFT"))
        res = evaluate([P("t1")], [G("t1", status="fix")])
        self.assertEqual(res["gold_status"], "verified")


if __name__ == "__main__":
    unittest.main()

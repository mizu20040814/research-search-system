"""ページ特定(locate.py)のテスト。取得は偽の関数に差し替え、小さなサイトをたどらせる。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from confprog.fetch import FetchError
from confprog.locate import locate, main

TOP = "https://example.org/conf2026/"
S1, S2, S3 = (f"{TOP}session/s{i}" for i in (1, 2, 3))


def fake(pages, calls=None):
    def get(url):
        if calls is not None:
            calls.append(url)
        if url not in pages:
            raise FetchError(f"取得に失敗しました: {url}")
        return pages[url]
    return get


def list_page(tag, hrefs=None):
    """発表一覧：タイトル(20字以上)と著者2名の行が3つある表。hrefs があればタイトルをリンクにする。"""
    rows = []
    for i in range(3):
        title = f"{tag}に関する研究の第{i + 1}報告と提案手法の評価"
        if hrefs:
            title = f'<a href="{hrefs[i]}">{title}</a>'
        rows.append(f'<tr><td class="t">{title}</td></tr><tr><td class="a">山田 太郎, 佐藤 花子 (架空大)</td></tr>')
    return f"<html><body><table>{''.join(rows)}</table></body></html>"


def top_with(*links):
    """一覧ではないページ(リンクと挨拶だけ)。links は (URL, 文字) の組。"""
    a = "".join(f'<a href="{u}">{t}</a>' for u, t in links)
    return f'<html><body><nav>{a}<a href="{TOP}access.html">アクセス</a></nav><p>ようこそ</p></body></html>'


LIST_A = list_page("画像認識")
SESSIONS = {S1: list_page("音声"), S2: list_page("言語"), S3: list_page("検索")}
HUB = list_page("セッション", hrefs=[S1, S2, S3])

HUB_SITE = {TOP: top_with((TOP + "program/", "プログラム")),
            TOP + "program/": top_with((TOP + "program/sessions.html", "一般セッション")),
            TOP + "program/sessions.html": HUB, **SESSIONS}
DETAIL_SITE = {TOP: top_with((TOP + "program.html", "プログラム")),
               TOP + "program.html": list_page("詳細", hrefs=[f"{TOP}p/{i}.html" for i in (1, 2, 3)]),
               **{f"{TOP}p/{i}.html": f"<html><body><h1>詳細に関する研究の第{i}報告と提案手法の評価</h1><p>山田 太郎</p></body></html>"
                  for i in (1, 2, 3)}}
JA_EN_SITE = {TOP: top_with((TOP + "program.html", "プログラム"), (TOP + "en/program.html", "Program")),
              TOP + "program.html": LIST_A, TOP + "en/program.html": LIST_A}
MANY_LINKS_SITE = {TOP: top_with(*[(f"{TOP}p{i}.html", f"プログラム{i}") for i in range(10)]),
                   **{f"{TOP}p{i}.html": top_with((f"{TOP}q{i}.html", "日程")) for i in range(10)}}
DEEP_SITE = {TOP: top_with((TOP + "a.html", "プログラム")), TOP + "a.html": top_with((TOP + "b.html", "プログラム")),
             TOP + "b.html": top_with((TOP + "c.html", "プログラム")), TOP + "c.html": LIST_A}
LOOP_SITE = {TOP: top_with((TOP + "a.html", "プログラム")),
             TOP + "a.html": top_with((TOP, "プログラム"), (TOP + "b.html", "日程")),
             TOP + "b.html": top_with((TOP + "a.html", "プログラム"))}
TOP_HUB_SITE = {TOP: HUB, **SESSIONS}
HUB_SAMPLE_ERROR_SITE = {TOP: HUB, S2: SESSIONS[S2], S3: SESSIONS[S3]}


class LocateTest(unittest.TestCase):
    def test_top_is_list(self):
        r = locate(TOP, get=fake({TOP: LIST_A}))
        self.assertEqual(r.pages, [TOP])

    def test_list_outside_top_dir(self):
        url = "https://example.org/proceedings/2026/"
        r = locate(TOP, get=fake({TOP: top_with((url, "プログラム")), url: LIST_A}))
        self.assertEqual(r.pages, [url])

    def test_hub_two_levels(self):
        r = locate(TOP, get=fake(HUB_SITE))
        self.assertEqual(r.pages, [S1, S2, S3])
        self.assertIn("hub", [v.verdict for v in r.visits])

    def test_detail_links_are_not_hub(self):
        r = locate(TOP, get=fake(DETAIL_SITE))
        self.assertEqual(r.pages, [TOP + "program.html"])

    def test_not_found(self):
        r = locate(TOP, get=fake({TOP: top_with()}))
        self.assertEqual(r.pages, [])

    def test_error_page_recorded(self):
        r = locate(TOP, get=fake({TOP: top_with((TOP + "missing.html", "プログラム"))}))
        self.assertEqual(r.pages, [])
        self.assertEqual([v.verdict for v in r.visits if v.url.endswith("missing.html")], ["error"])

    def test_duplicate_removed(self):
        r = locate(TOP, get=fake(JA_EN_SITE))
        self.assertEqual(r.pages, [TOP + "program.html"])
        self.assertIn("duplicate", [v.verdict for v in r.visits])

    def test_depth_limit(self):
        r = locate(TOP, get=fake(DEEP_SITE), max_depth=2)
        self.assertEqual(r.pages, [])

    def test_no_loop(self):
        r = locate(TOP, get=fake(LOOP_SITE))
        urls = [v.url for v in r.visits]
        self.assertEqual(len(urls), len(set(urls)))

    def test_top_is_hub(self):
        r = locate(TOP, get=fake(TOP_HUB_SITE))
        self.assertEqual(r.pages, [S1, S2, S3])

    def test_hub_sample_error(self):
        r = locate(TOP, get=fake(HUB_SAMPLE_ERROR_SITE))
        self.assertEqual(r.pages, [TOP])
        self.assertIn("error", [v.verdict for v in r.visits if v.url == S1])


P = [f"{TOP}prog/p{i}.html" for i in (1, 2, 3, 4)]
_NAV = "".join(f'<a href="{u}">第{i + 1}部</a>' for i, u in enumerate(P))
SIBLING_SITE = {TOP: top_with((P[0], "プログラム")),
                **{u: list_page(f"分野{i}").replace("<table>", f"<nav>{_NAV}</nav><table>") for i, u in enumerate(P)}}


class ReviewFixTest(unittest.TestCase):
    """全体レビューの指摘(2026-10-25)の再現"""

    def test_sibling_lists_all_returned(self):
        # 一覧どうしが互いにリンクしていても、最初に着いた一覧を落とさない(IPSJ の program1〜8)
        r = locate(TOP, get=fake(SIBLING_SITE))
        self.assertEqual(r.pages, P)

    def test_hub_check_cut_by_limit_not_adopted(self):
        # 上限で試し開きを打ち切ったページは、ハブか分からないので採用しない
        r = locate(TOP, get=fake(TOP_HUB_SITE), max_pages=2)
        self.assertEqual(r.pages, [])
        self.assertTrue(any("上限" in v.reason for v in r.visits if v.url == TOP))

    def test_samples_recorded(self):
        calls = []
        r = locate(TOP, get=fake(DETAIL_SITE, calls))
        self.assertEqual(len(r.visits), len(calls))
        self.assertTrue(any("試し開き" in v.reason for v in r.visits if v.url.endswith("p/1.html")))

    def test_page_limit_counts_gets_and_records_stop(self):
        calls = []
        r = locate(TOP, get=fake(MANY_LINKS_SITE, calls), max_pages=5)
        self.assertLessEqual(len(calls), 5)
        self.assertIn("上限", r.visits[-1].reason)

    def test_trailing_slash_same_page(self):
        calls = []
        top_noslash = TOP.rstrip("/")
        site = {top_noslash: top_with((TOP, "トップ"), (TOP + "program", "プログラム"), (TOP + "program/", "プログラム")),
                TOP + "program": LIST_A}
        r = locate(top_noslash, get=fake(site, calls))
        self.assertEqual(r.pages, [TOP + "program"])
        self.assertEqual(calls, [top_noslash, TOP + "program"])


    def test_shallower_path_reexpanded(self):
        # 深い経路で先に開いたページでも、浅い経路で来たらリンクをたどる(Codex 指摘)
        a, b, lst = TOP + "a.html", TOP + "b.html", TOP + "list.html"
        site = {TOP: top_with((a, "大会"), (b, "プログラム 日程")),
                b: top_with((a, "プログラム 日程 セッション")),
                a: top_with((lst, "プログラム")), lst: LIST_A}
        r = locate(TOP, get=fake(site), max_depth=2)
        self.assertEqual(r.pages, [lst])

    def test_hub_with_two_groups(self):
        # ハブが口頭とポスターのように別の形の一覧群にリンクしていれば両方返す(Codex 指摘)
        oral = [f"{TOP}oral/s{i}" for i in (1, 2, 3)]
        poster = [f"{TOP}poster/s{i}" for i in (1, 2, 3)]
        hub = list_page("口頭", hrefs=oral).replace("</body>", "".join(f'<a href="{u}">ポスター{i}</a>' for i, u in enumerate(poster)) + "</body>")
        site = {TOP: hub, **{u: list_page(f"口頭{i}") for i, u in enumerate(oral)},
                **{u: list_page(f"ポスター{i}") for i, u in enumerate(poster)}}
        r = locate(TOP, get=fake(site))
        self.assertEqual(sorted(r.pages), sorted(oral + poster))

    def test_hub_with_directory_urls(self):
        # /session/a/ のようなディレクトリ形式のリンクも1つのまとまりにする(Codex 指摘)
        dirs = [f"{TOP}session/{k}/" for k in "abc"]
        site = {TOP: list_page("セッション", hrefs=dirs), **{u: list_page(f"分科{i}") for i, u in enumerate(dirs)}}
        r = locate(TOP, get=fake(site))
        self.assertEqual(r.pages, dirs)


def numbered_list(tag, n):
    rows = "".join(f'<tr><td class="t">{tag}に関する研究の第{i + 1}報告と提案手法の評価</td></tr>'
                   f'<tr><td class="a">山田 太郎, 佐藤 花子 (架空大)</td></tr>' for i in range(n))
    return f"<html><body><table>{rows}</table></body></html>"


class ReviewFix2Test(unittest.TestCase):
    """Codex 再レビューの指摘(2026-10-25)の再現"""

    def test_superset_list_kept(self):
        # 先に見つけた日別一覧(3件)が、後の全体一覧(6件)の部分集合でも、全体一覧を捨てない
        day, all_ = TOP + "day1.html", TOP + "all.html"
        site = {TOP: top_with((day, "プログラム 日程"), (all_, "プログラム")),
                day: numbered_list("画像", 3), all_: numbered_list("画像", 6)}
        r = locate(TOP, get=fake(site))
        self.assertIn(all_, r.pages)
        self.assertNotIn(day, r.pages)

    def test_sampled_page_still_expanded(self):
        # ハブ判定の試し開きで一覧でなかったページも、通常の探索ではリンクをたどる
        a, lst = TOP + "a.html", TOP + "list.html"
        b, c, d = (f"{TOP}x/{k}.html" for k in "bcd")
        site = {TOP: top_with((a, "プログラム 日程"), (b, "プログラム")),
                a: list_page("画像認識", hrefs=[b, c, d]),
                b: top_with((lst, "プログラム")), lst: list_page("音声")}
        r = locate(TOP, get=fake(site))
        self.assertIn(lst, r.pages)
        self.assertEqual(len([v for v in r.visits if v.url == b]), 1)


class ReviewFix3Test(unittest.TestCase):
    """Codex 3回目のレビューの指摘(2026-10-25)の再現"""

    def test_adopted_non_list_member_still_expanded(self):
        # ハブのリンク先に混ざった一覧でないページも、通常の探索ではリンクをたどる
        a, lst = TOP + "a.html", TOP + "list.html"
        b, c, d = (f"{TOP}x/{k}.html" for k in "bcd")
        site = {TOP: top_with((a, "プログラム 日程"), (d, "プログラム")),
                a: list_page("目次", hrefs=[b, c, d]), b: list_page("音声"), c: list_page("言語"),
                d: top_with((lst, "プログラム")), lst: list_page("検索")}
        r = locate(TOP, get=fake(site))
        self.assertEqual(sorted(r.pages), sorted([b, c, lst]))
        self.assertEqual(len([v for v in r.visits if v.url == d]), 1)

    def test_two_level_hub(self):
        # 目次 → 日別目次 → セッション別一覧の二段のハブでも、セッション別一覧まで返す
        days = [f"{TOP}day/d{i}" for i in (1, 2, 3)]
        sess = {d: [f"{TOP}s/d{i}-{k}" for k in (1, 2, 3)] for i, d in enumerate(days, 1)}
        site = {TOP: list_page("日程", hrefs=days),
                **{d: list_page(f"第{i}日", hrefs=sess[d]) for i, d in enumerate(days, 1)},
                **{s_: list_page(f"分科{s_[-3:]}") for d in days for s_ in sess[d]}}
        r = locate(TOP, get=fake(site))
        self.assertEqual(sorted(r.pages), sorted(s_ for d in days for s_ in sess[d]))

    def test_member_kept_when_hub_check_hits_limit(self):
        # ハブのリンク先は一覧と分かっているので、上限で二段目を確かめられなくても捨てない
        days = [f"{TOP}day/d{i}" for i in (1, 2, 3)]
        site = {TOP: list_page("日程", hrefs=days),
                **{d: list_page(f"第{i}日", hrefs=[f"{TOP}s/d{i}-{k}" for k in (1, 2, 3)])
                   for i, d in enumerate(days, 1)}}
        r = locate(TOP, get=fake(site), max_pages=3)
        self.assertEqual(r.pages, days)

    def test_failed_shape_not_resampled(self):
        # 詳細ページの形は一度「一覧でない」と分かれば、別のページでは試し開きしない
        ss = [f"{TOP}session/s{i}" for i in (1, 2, 3)]
        site = {TOP: list_page("セッション", hrefs=ss),
                **{u: list_page(f"分科{i}", hrefs=[f"{TOP}p/{i}-{k}.html" for k in (1, 2, 3)])
                   for i, u in enumerate(ss, 1)}}
        calls = []
        r = locate(TOP, get=fake(site, calls))
        self.assertEqual(r.pages, ss)
        self.assertEqual(len(calls), 5)  # トップ、セッション3つ、詳細ページの試し開き1つ


class ReviewFix4Test(unittest.TestCase):
    """Codex 4回目のレビューの指摘(2026-10-25)の再現"""

    def test_hub_result_not_reused_for_other_links(self):
        # 同じ URL の形でも、別のリンク集合が一覧かどうかは改めて確かめる
        a, b = TOP + "a.html", TOP + "b.html"
        items = [f"{TOP}item/{i}" for i in range(6)]
        site = {TOP: top_with((a, "プログラム 日程"), (b, "プログラム")),
                a: list_page("目次", hrefs=items[:3]), b: list_page("詳細", hrefs=items[3:]),
                **{u: list_page(f"分科{i}") for i, u in enumerate(items[:3])},
                **{u: f"<html><body><h1>詳細ページ{i}</h1></body></html>" for i, u in enumerate(items[3:])}}
        r = locate(TOP, get=fake(site))
        self.assertEqual(sorted(r.pages), sorted(items[:3] + [b]))


class RealRunFixTest(unittest.TestCase):
    """6大会の実行(2026-10-25)で見つかった問題の再現"""

    def test_invalid_url_recorded_not_raised(self):
        def get(url):
            if url == TOP:
                return top_with((TOP + "program.html", "プログラム"))
            raise ValueError("URL can't contain control characters")
        r = locate(TOP, get=get)
        self.assertEqual([v.verdict for v in r.visits if v.url.endswith("program.html")], ["error"])

    def test_top_list_does_not_adopt_same_shape_pages(self):
        # トップ自体が一覧なら、同じ形のリンク先(他の開催回のプログラム)は採用しない(IEICE)
        top = "https://example.org/program/index.php?id=a"
        others = [f"https://example.org/program/index.php?id={k}" for k in "bcd"]
        page = lambda tag, hrefs=None: list_page(tag, hrefs).replace(
            "</body>", "".join(f'<a href="{u}">第{i}回</a>' for i, u in enumerate(others)) + "</body>")
        site = {top: page("今回"), **{u: list_page(f"別の回{i}") for i, u in enumerate(others)}}
        r = locate(top, get=fake(site))
        self.assertEqual(r.pages, [top])

    def test_other_year_links_skipped(self):
        # 学会リストの年と違う年が URL に入ったリンクはたどらない(YANS の過去・翌年の記事)
        top = "https://example.org/entry/conf2025"
        p25, p23 = "https://example.org/entry/conf2025program", "https://example.org/entry/conf2023program"
        site = {top: top_with((p25, "プログラム"), (p23, "プログラム")), p25: list_page("今年"), p23: list_page("昔")}
        self.assertEqual(locate(top, get=fake(site), year=2025).pages, [p25])
        self.assertEqual(sorted(locate(top, get=fake(site)).pages), sorted([p25, p23]))


class CycleTest(unittest.TestCase):
    def test_links_back_to_ancestors_do_not_make_hub(self):
        # セッション一覧が日別目次へ戻るリンクを持っていても、それだけでハブとみなして捨てない(Codex 指摘)
        days = [f"{TOP}day/d{i}" for i in (1, 2, 3)]
        sess = {d: [f"{TOP}s/d{i}-{k}" for k in (1, 2, 3)] for i, d in enumerate(days, 1)}
        site = {TOP: list_page("日程", hrefs=days),
                **{d: list_page(f"第{i}日", hrefs=sess[d]) for i, d in enumerate(days, 1)},
                **{s_: list_page(f"分科{s_[-3:]}", hrefs=days) for d in days for s_ in sess[d]}}
        r = locate(TOP, get=fake(site))
        self.assertEqual(sorted(r.pages), sorted(s_ for d in days for s_ in sess[d]))


class MainTest(unittest.TestCase):
    def test_single_url_writes_json(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("confprog.locate.render", fake({TOP: LIST_A})):
            out = Path(d) / "r.json"
            self.assertEqual(main([TOP, "--out", str(out)]), 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["pages"], [TOP])
            self.assertEqual(data["visits"][0]["verdict"], "list")

    def test_list_continues_after_failure(self):
        other = "https://other.example.org/"
        with tempfile.TemporaryDirectory() as d, mock.patch("confprog.locate.render", fake({TOP: LIST_A})):
            csv_path = Path(d) / "conferences.csv"
            csv_path.write_text(f"学会,年,トップURL,メモ\nBAD,2026,{other},\nOK,2026,{TOP},\n", encoding="utf-8")
            self.assertEqual(main(["--list", str(csv_path), "--out-dir", d]), 0)
            self.assertEqual(json.loads((Path(d) / "ok2026.json").read_text(encoding="utf-8"))["pages"], [TOP])
            summary = (Path(d) / "summary.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(summary), 3)
            self.assertTrue(summary[1].startswith("BAD,2026,0,"))


if __name__ == "__main__":
    unittest.main()

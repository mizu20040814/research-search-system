"""一括実行：学会リストから、ページ特定 → 各ページの描画と汎用抽出 → 発表DB までを1コマンドで行う。

使い方:
  python -m confprog build                         # eval/conferences.csv の全学会
  python -m confprog build --only MIRU ANLP        # 一部だけ(ほかの学会は前回分を使う)

学会ごとに、ページごとの抽出結果を data/out/batch/generic_<学会><年>_<番号>.json に書く。
発表が1件以上取れたページが1枚でもあれば成功とし、そのときだけ前回分と入れ替える。
失敗した学会は前回分をそのまま使う(11/6 のデモで学会が消えないように)。
最後に data/out/batch/ から発表DBを作り、一覧を summary.csv に書く。
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .fetch import FetchError
from .generic import METHOD
from .locate import LocateResult
from .render import RenderError

OK, PREV_USED, FAILED, PREV = "成功", "前回分を使用", "失敗（前回分なし）", "前回分"


@dataclass
class ConfResult:
    conference: str
    year: int | None
    key: str
    status: str
    pages_found: int = 0
    pages_extracted: int = 0
    count: int = 0
    reason: str = ""


def conf_key(conference: str, year: int) -> str:
    return f"{conference.lower()}{year}"


def _own_files(out_dir: Path, key: str) -> list[Path]:
    """その学会の抽出結果のファイル(キーの前方一致で別の学会を拾わない)。"""
    pat = re.compile(rf"generic_{re.escape(key)}_\d+\.json")
    return sorted(p for p in out_dir.glob(f"generic_{key}_*.json") if pat.fullmatch(p.name))


def previous_result(key: str, out_dir: Path) -> ConfResult | None:
    files = _own_files(out_dir, key)
    if not files:
        return None
    conference, year, count = key, None, 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        conference, year = d.get("conference") or conference, d.get("year") or year
        count += d.get("count", len(d.get("presentations") or []))
    loc = out_dir / f"locate_{key}.json"
    found = len(json.loads(loc.read_text(encoding="utf-8")).get("pages") or []) if loc.exists() else len(files)
    return ConfResult(conference, year, key, PREV, found, len(files), count)


def _failed(name: str, year: int | None, key: str, out_dir: Path, reason: str, found: int = 0) -> ConfResult:
    prev = previous_result(key, out_dir) if year is not None else None
    if prev:
        return ConfResult(name, year, key, PREV_USED, prev.pages_found, prev.pages_extracted, prev.count, reason)
    return ConfResult(name, year, key, FAILED, found, 0, 0, reason)


def build_one(row: dict, out_dir: Path, *, locate_fn: Callable[[str, int], LocateResult],
              render_fn: Callable[[str], str], extract_fn: Callable) -> ConfResult:
    # 列が足りない行は DictReader が None を入れるので、空文字として扱う
    name, ystr, top = ((row.get(k) or "").strip() for k in ("学会", "年", "トップURL"))
    try:
        year: int | None = int(ystr)
    except ValueError:
        year = None
    if not name or not top:
        # 学会名と年が分かれば前回分を探す(DB に残る前回分と一覧を食い違わせない)
        key = conf_key(name, year) if name and year is not None else f"{name.lower()}{ystr}"
        return _failed(name or "?", year if name else None, key, out_dir, "学会名かトップURLが空です")
    if year is None:
        return _failed(name, None, f"{name.lower()}{ystr}", out_dir, f"年が数字ではありません: {ystr!r}")
    key = conf_key(name, year)
    tmp = out_dir / "_new" / key
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        pages: list[str] = []
        reasons: list[str] = []
        done = total = 0
        try:
            loc = locate_fn(top, year)
            pages = list(loc.pages)
            (tmp / f"locate_{key}.json").write_text(json.dumps(loc.to_dict(), ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
            if not pages:
                reasons.append("発表一覧のページが見つかりませんでした")
            for url in pages:
                try:
                    items, inf = extract_fn(render_fn(url), name, year, url)
                except (FetchError, RenderError, ValueError) as e:
                    reasons.append(f"{url}: {e}")
                    continue
                if not items:
                    reasons.append(f"{url}: 発表が0件")
                    continue
                done += 1
                total += len(items)
                payload = {
                    "method": METHOD, "conference": name, "year": year, "source_url": url,
                    "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "inference": inf.describe(), "count": len(items),
                    "presentations": [p.to_dict() for p in items],
                }
                (tmp / f"generic_{key}_{done:02d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # 想定外でも記録して次の学会に進む
            return _failed(name, year, key, out_dir, f"{type(e).__name__}: {e}", len(pages))
        if not done:
            return _failed(name, year, key, out_dir, "; ".join(reasons), len(pages))
        try:
            _swap(out_dir, key, tmp)
        except OSError as e:  # OneDrive やエディタがファイルを開いていて動かせないなど。前回分は戻してある
            return _failed(name, year, key, out_dir, f"入れ替えに失敗: {type(e).__name__}: {e}", len(pages))
        return ConfResult(name, year, key, OK, len(pages), done, total, "; ".join(reasons))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for d in ("_new", "_old"):
            try:
                (out_dir / d).rmdir()
            except OSError:
                pass


def _swap(out_dir: Path, key: str, tmp: Path) -> None:
    """前回分を _old/<キー> に退避してから今回分を移す(前回よりページが減っても古いファイルを残さない)。
    途中で失敗したら、移した今回分を消して前回分を元に戻し、例外をそのまま投げる。"""
    backup = out_dir / "_old" / key
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True)
    olds = [p for p in _own_files(out_dir, key) + [out_dir / f"locate_{key}.json"] if p.exists()]
    moved_old: list[Path] = []
    moved_new: list[Path] = []
    try:
        for p in olds:
            shutil.move(str(p), str(backup / p.name))
            moved_old.append(p)
        for f in sorted(tmp.iterdir()):
            shutil.move(str(f), str(out_dir / f.name))
            moved_new.append(out_dir / f.name)
    except OSError:
        for p in moved_new:
            p.unlink(missing_ok=True)
        for p in moved_old:
            shutil.move(str(backup / p.name), str(p))
        shutil.rmtree(backup, ignore_errors=True)
        raise
    shutil.rmtree(backup, ignore_errors=True)


SUMMARY_COLUMNS = ["学会", "年", "状態", "見つけたページ数", "抽出できたページ数", "発表件数", "理由"]
_FILE_KEY = re.compile(r"generic_(.+)_\d+\.json")


def _default_locate(url: str, year: int) -> LocateResult:
    from .locate import locate
    from .render import render
    return locate(url, get=render, year=year)


def _default_render(url: str) -> str:
    from .render import render
    return render(url)


def _default_extract(html: str, conference: str, year: int, url: str):
    from .generic import extract
    return extract(html, conference, year, url)


def write_summary(results: list[ConfResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_COLUMNS)
        for r in results:
            w.writerow([r.conference, r.year if r.year is not None else "", r.status, r.pages_found,
                        r.pages_extracted, r.count, r.reason])


def run_build(rows: list[dict], out_dir: Path, db_path: Path, *,
              locate_fn: Callable[[str, int], LocateResult] = _default_locate,
              render_fn: Callable[[str], str] = _default_render,
              extract_fn: Callable = _default_extract) -> tuple[list[ConfResult], int]:
    """全学会を流して発表DBを作る。戻り値は(summary に出す全学会の結果, DB の件数)。"""
    from .db import build_db

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.get('学会') or ''} {row.get('年') or ''} {row.get('トップURL') or ''}", flush=True)
        r = build_one(row, out_dir, locate_fn=locate_fn, render_fn=render_fn, extract_fn=extract_fn)
        print(f"    {r.status} ページ {r.pages_extracted}/{r.pages_found} 発表 {r.count}"
              + (f"  ({r.reason[:200]})" if r.reason else ""), flush=True)
        results.append(r)
    # 今回流していない学会も、前回分として一覧に出す(--only で一覧が上書きされて消えないように)
    ran = {r.key for r in results}
    keys = sorted({m.group(1) for p in out_dir.glob("generic_*.json") if (m := _FILE_KEY.fullmatch(p.name))})
    results += [prev for k in keys if k not in ran and (prev := previous_result(k, out_dir))]
    records, warnings = build_db(out_dir, db_path)
    for w in warnings:
        print(f"警告: {w}", file=sys.stderr)
    try:
        write_summary(results, out_dir / "summary.csv")
    except OSError as e:  # Excel で開いたままなど。発表DBはできているので止めない
        print(f"警告: {out_dir / 'summary.csv'} を書けませんでした({type(e).__name__}: {e})。"
              "開いていれば閉じてから流し直してください", file=sys.stderr)
    return results, len(records)


def main(argv: list[str] | None = None, **fns) -> int:
    import argparse

    from .db import DEFAULT_DB_PATH

    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="confprog build", description="学会リストから発表DBまでを一括で作る")
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--list", type=Path, default=Path("eval/conferences.csv"),
                    help="学会リストの CSV(列: 学会,年,トップURL,メモ。既定: eval/conferences.csv)")
    ap.add_argument("--only", nargs="*", help="学会名で絞る(ほかの学会は前回分を使う)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/out/batch"), help="抽出結果の置き場(既定: data/out/batch)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"発表DBの保存先(既定: {DEFAULT_DB_PATH})")
    args = ap.parse_args(argv)
    try:
        with args.list.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"エラー: 学会リスト {args.list} が見つかりません", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print(f"エラー: 学会リスト {args.list} を読めません。UTF-8(Excel なら「CSV UTF-8」)で保存してください",
              file=sys.stderr)
        return 1
    if args.only:
        rows = [r for r in rows if (r.get("学会") or "").strip() in args.only]
    results, n = run_build(rows, args.out_dir, args.db, **fns)
    print(f"発表DB: {n} 件 → {args.db}")
    print(f"一覧: {args.out_dir / 'summary.csv'}")
    return 0 if n else 1

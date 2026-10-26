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
    name, ystr, top = row["学会"].strip(), (row.get("年") or "").strip(), row["トップURL"].strip()
    try:
        year = int(ystr)
    except ValueError:
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
        # 成功したときだけ前回分と入れ替える(前回よりページが減っても古いファイルを残さない)
        for old in _own_files(out_dir, key) + [out_dir / f"locate_{key}.json"]:
            old.unlink(missing_ok=True)
        for f in tmp.iterdir():
            shutil.move(str(f), str(out_dir / f.name))
        return ConfResult(name, year, key, OK, len(pages), done, total, "; ".join(reasons))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            (out_dir / "_new").rmdir()
        except OSError:
            pass

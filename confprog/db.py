"""発表DB: 汎用抽出の結果(data/out/generic_*.json)を1大会内の異なる発表ごとに1件へまとめる。

DB は抽出結果からいつでも作り直せる派生物なので、毎回全体を作り直す(追記しない)。
学会別抽出器の出力(miru2026.json など)は正解データ用なので読まない。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

DEFAULT_OUT_DIR = Path("data/out")
DEFAULT_DB_PATH = Path("data/db/presentations.jsonl")

# セッション名に入っていたら対象外の印を付ける語(形式の一般知識。学会名では分岐しない)
_INVITED = re.compile(r"招待講演|招待論文|基調講演|invited|keynote", re.IGNORECASE)
_TUTORIAL = re.compile(r"チュートリアル|tutorial", re.IGNORECASE)
_JA = re.compile(r"[぀-ヿ一-鿿]")


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", title)).strip()


def classify_kind(session: str | None) -> str:
    if session and _INVITED.search(session):
        return "invited"
    if session and _TUTORIAL.search(session):
        return "tutorial"
    return "general"


def detect_lang(title: str) -> str:
    return "ja" if _JA.search(title) else "en"


def _title_id(event: str, title: str) -> str:
    return f"{event}:t-" + hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:10]


def build_records(payloads: list[dict]) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    warnings: list[str] = []
    by_key: dict[tuple, dict] = {}
    used_ids: set[str] = set()
    for payload in payloads:
        blank = 0
        year_zero = False
        for p in payload.get("presentations", []):
            title = (p.get("title") or "").strip()
            if not title:
                blank += 1
                continue
            event = p.get("event") or payload.get("conference", "")
            norm = normalize_title(title)
            pid = p.get("presentation_id")
            # 番号があれば番号とタイトルの組、なければタイトルで同じ発表とみなす
            key = (event, pid, norm) if pid else (event, None, norm)
            if key in by_key:
                by_key[key]["slots"] += 1
                continue
            rid = f"{event}:{pid}" if pid else _title_id(event, title)
            if rid in used_ids:
                # 同じ発表番号に別のタイトル(番号の付け間違いなど)。別の発表として残す
                n = 2
                while f"{rid}#{n}" in used_ids:
                    n += 1
                warnings.append(f"{event}: 発表番号 {pid} が別のタイトルにも付いています → {rid}#{n}")
                rid = f"{rid}#{n}"
            year = p.get("year", payload.get("year"))
            if not year:
                year_zero = True
            rec = {
                "id": rid,
                "conference": p.get("conference") or payload.get("conference"),
                "event": event,
                "year": year,
                "title": title,
                "authors": p.get("authors") or [],
                "affiliations": p.get("affiliations") or [],
                "session": p.get("session"),
                "presentation_id": pid,
                "kind": classify_kind(p.get("session")),
                "slots": 1,
                "lang": detect_lang(title),
                "url": p.get("url"),
                "source_url": p.get("source_url") or payload.get("source_url"),
                "extractor": payload.get("method"),
                "extracted_at": payload.get("extracted_at"),
            }
            by_key[key] = rec
            used_ids.add(rid)
            records.append(rec)
        if blank:
            warnings.append(f"{payload.get('conference')}: 空のタイトルを {blank} 件除きました")
        if year_zero:
            warnings.append(f"{payload.get('conference')}: year が 0 の発表があります(抽出側の不具合の可能性)")
    return records, warnings


def build_db(out_dir: Path = DEFAULT_OUT_DIR, db_path: Path = DEFAULT_DB_PATH) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    # 同じ大会でも別ページ(IPSJ の program1〜8 など)の抽出結果は結合する。
    # 同じページを抽出し直したファイルが複数あるときだけ、ファイル名順で後のものを使う
    by_page: dict[tuple[str, str], tuple[Path, dict]] = {}
    files = [f for f in sorted(out_dir.glob("generic_*.json")) if not f.name.endswith("_eval.json")]
    if not files:
        warnings.append(f"{out_dir} に generic_*.json がありません(リポジトリ直下で実行しているか確認してください)")
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        items = payload.get("presentations") or []
        # build_records と同じ決め方にする
        event = (items[0].get("event") if items else None) or payload.get("conference") or f.stem
        page = payload.get("source_url") or f.name
        if (event, page) in by_page:
            warnings.append(f"{event}: 同じページの抽出結果が複数あります({by_page[(event, page)][0].name} と {f.name})。"
                            f"{f.name} を使います")
        by_page[(event, page)] = (f, payload)
    records, more = build_records([p for _, p in by_page.values()])
    warnings.extend(more)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return records, warnings


def load_db(db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    with db_path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def db_hash(db_path: Path = DEFAULT_DB_PATH) -> str:
    return hashlib.sha256(db_path.read_bytes()).hexdigest()

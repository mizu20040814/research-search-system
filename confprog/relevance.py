"""関連度ランキング: 発表タイトルの埋め込みと研究課題文の埋め込みの類似度で並べる。

埋め込み関数(EmbedFn)は差し替えられるようにしてあり、テストでは偽物を使う。
発表側の埋め込みは data/db/emb/ にキャッシュし、DB が変わったときだけ作り直す。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_CACHE_DIR = Path("data/db/emb")
DEFAULT_RUNS_DIR = Path("data/runs")

# 文(行)ごとに正規化したベクトルを返す関数
EmbedFn = Callable[[list[str]], np.ndarray]

# モデルごとの前置き(課題文側, 発表側)。表にないモデルは前置きなし
PREFIXES: dict[str, tuple[str, str]] = {
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
}


def passage_text(rec: dict, with_session: bool) -> str:
    if with_session and rec.get("session"):
        return f"{rec['title']}（{rec['session']}）"
    return rec["title"]


def method_name(model: str, with_session: bool) -> str:
    return f"{model}|{'title+session' if with_session else 'title'}"


def _cache_paths(cache_dir: Path, model: str, with_session: bool) -> tuple[Path, Path]:
    stem = model.replace("/", "__") + ("__title+session" if with_session else "__title")
    return cache_dir / f"{stem}.npy", cache_dir / f"{stem}.meta.json"


def load_or_build_embeddings(records: list[dict], db_digest: str, model: str, with_session: bool,
                             embed: EmbedFn, cache_dir: Path = DEFAULT_CACHE_DIR) -> np.ndarray:
    npy, meta_path = _cache_paths(cache_dir, model, with_session)
    ids = [r["id"] for r in records]
    if npy.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("db_hash") == db_digest and meta.get("ids") == ids:
            return np.load(npy)
    # kind に関係なく全件を埋め込む(並べるときに除外する)
    prefix = PREFIXES.get(model, ("", ""))[1]
    print(f"埋め込みを作成中: {len(records)} 件({method_name(model, with_session)})", file=sys.stderr)
    emb = np.asarray(embed([prefix + passage_text(r, with_session) for r in records]), dtype="float32")
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(npy, emb)
    meta = {"model": model, "with_session": with_session, "db_hash": db_digest, "ids": ids,
            "created_at": datetime.now().isoformat(timespec="seconds")}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return emb


def rank(query: str, records: list[dict], emb: np.ndarray, model: str, embed: EmbedFn,
         top: int = 20) -> list[dict]:
    q = np.asarray(embed([PREFIXES.get(model, ("", ""))[0] + query]), dtype="float32")[0]
    scores = emb @ q
    cands = [(float(scores[i]), r) for i, r in enumerate(records) if r.get("kind") == "general"]
    cands.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [{"rank": n, "score": round(s, 3), "id": r["id"], "event": r["event"], "title": r["title"],
             "authors": r.get("authors") or [], "session": r.get("session")}
            for n, (s, r) in enumerate(cands[:top], start=1)]


def save_run(query: str, method: str, db_digest: str, top: int, results: list[dict],
             runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path, n = runs_dir / f"{stamp}.json", 2
    while path.exists():
        path, n = runs_dir / f"{stamp}-{n}.json", n + 1
    data = {"query": query, "method": method, "db_hash": db_digest, "top": top,
            "results": [{"id": r["id"], "score": r["score"], "event": r["event"], "title": r["title"]}
                        for r in results]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sentence_transformer(model: str) -> EmbedFn:
    from sentence_transformers import SentenceTransformer  # 重いので使うときだけ読む

    st = SentenceTransformer(model, device="cpu")

    def embed(texts: list[str]) -> np.ndarray:
        if len(texts) == 1:
            n = len(st.tokenizer(texts[0])["input_ids"])
            if n > st.max_seq_length:
                print(f"課題文が長いので先頭 {st.max_seq_length} トークンだけを使います({n} トークン)", file=sys.stderr)
        return st.encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 1)

    return embed

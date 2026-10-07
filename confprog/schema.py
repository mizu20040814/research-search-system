"""共通スキーマ。

ノートで確定したスキーマ {学会, 大会, 年, セッション, タイトル, 著者[], URL} に対応する。
評価(RQ1)で使うため、元の著者文字列や取得元URLなどの補助情報も残す。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Presentation:
    # --- 確定スキーマ ---
    conference: str              # 学会 (例: "MIRU")
    event: str                   # 大会 (例: "MIRU2026")
    year: int                    # 年
    session: str                 # セッション名
    title: str                   # タイトル
    authors: list[str]           # 著者(所属を除いた氏名のリスト)
    url: Optional[str] = None    # 発表ページ/論文へのリンク(無ければ None)

    # --- 補助情報(評価・デバッグ用) ---
    presentation_id: Optional[str] = None
    session_type: Optional[str] = None   # oral / interactive / invited など(学会側の分類)
    date: Optional[str] = None           # YYYY-MM-DD
    time: Optional[str] = None           # "9:30–10:50"
    affiliations: list[str] = field(default_factory=list)
    authors_raw: Optional[str] = None    # 抽出前の著者文字列
    source_url: Optional[str] = None     # 取得元のプログラムページ

    def to_dict(self) -> dict:
        return asdict(self)

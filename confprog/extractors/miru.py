"""MIRU のタイムテーブルページから発表を抽出する。

MIRU2026 のサイトは Hugo 製で、プログラムは Google スプレッドシートの内容が
ビルド時にページ内の <script> へ JSON として埋め込まれ、Vue で描画される。
  const embeddedScheduleData = [...];       セッション(日付・時刻・セッション名)
  const embeddedPresentationsData = [...];  発表(タイトル・著者・リンク)
  const embeddedSessionItemsData = [...];   どの発表がどのセッションに何番目で入るか
そのため HTML を解析するのではなく、この JSON を取り出して結合する。
(ページを描画する JS と同じ結合ルールに合わせている)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from ..authors import parse_authors
from ..jsliteral import JSLiteralError, parse_at
from ..schema import Presentation

CONFERENCE = "MIRU"
DEFAULT_URL = "https://miru-committee.github.io/miru{year}/program/timetable/"

_JST = timezone(timedelta(hours=9))
_SHEETS_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)


class ExtractError(RuntimeError):
    pass


def _embedded(html: str, name: str):
    # 開発版: "const embeddedXxxData = [...];"
    # 本番(圧縮版): "...,embeddedXxxData=[{active:!0,...}],..." (キーに引用符が無い JS)
    # 代入の右辺がデータ([ / { / 文字列)の箇所だけを探す(使用箇所 "embeddedXxxData||[]" は除く)
    m = re.search(rf"\b{name}\s*=\s*(?=[\[{{\"'])", html)
    if not m:
        raise ExtractError(f"{name} がページ内に見つかりません(サイトの構成が変わった可能性)")
    try:
        value, _ = parse_at(html, m.end())
    except JSLiteralError as e:
        raise ExtractError(f"{name} を読み取れません: {e}") from e
    if isinstance(value, str):  # JSON 文字列として二重に埋め込まれている場合
        value = json.loads(value)
    return value


def _normalize(raw) -> list[dict]:
    """オブジェクト配列 / 2次元配列 / {values: [...]} のどれでも小文字キーの dict 配列にする。"""
    if isinstance(raw, dict):
        raw = raw.get("values") or raw.get("data") or []
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return [{str(k).lower().strip(): v for k, v in r.items()} for r in raw]
    if isinstance(raw[0], list):
        headers = [str(h).lower().strip() for h in raw[0]]
        return [dict(zip(headers, row)) for row in raw[1:]]
    return []


def _truthy(v) -> bool:
    return str(v).lower().strip() == "true"


def _localized(obj: dict, base: str) -> str:
    for key in (f"{base}_jp", f"{base}_en", base):
        v = obj.get(key)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _date(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) or re.fullmatch(r"\d+(\.\d+)?", str(v).strip()):
        d = _SHEETS_EPOCH + timedelta(days=float(v))
        return (d + timedelta(hours=9)).strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone(_JST)
    return d.strftime("%Y-%m-%d")


def _minutes(v) -> int | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return round((v % 1 if v >= 1 else v) * 24 * 60)
    s = str(v).strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", s)
    if m:
        return int(m[1]) * 60 + int(m[2])
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone(_JST)
    return d.hour * 60 + d.minute


def _hm(minutes: int | None) -> str:
    return "" if minutes is None else f"{minutes // 60}:{minutes % 60:02d}"


def extract(html: str, source_url: str | None = None, year: int | None = None) -> list[Presentation]:
    schedule = _normalize(_embedded(html, "embeddedScheduleData"))
    presentations = _normalize(_embedded(html, "embeddedPresentationsData"))
    items = _normalize(_embedded(html, "embeddedSessionItemsData"))
    if not presentations:
        raise ExtractError("発表データが空です(ページのビルド時にデータが取得できていない可能性)")

    if year is None:
        m = re.search(r"miru(\d{4})", source_url or "")
        year = int(m[1]) if m else 0
    event = f"{CONFERENCE}{year}"

    pres_by_id = {str(p.get("presentation_id", "")).strip(): p for p in presentations}
    pres_by_id.pop("", None)

    items_by_session: dict[str, list[dict]] = {}
    for it in items:
        code = str(it.get("session_code", "")).strip()
        if code:
            items_by_session.setdefault(code, []).append(it)

    sessions = [
        s for s in schedule
        if _truthy(s.get("active")) and _truthy(s.get("show_program"))
        and str(s.get("session_code", "")).strip()
    ]
    sessions.sort(key=lambda s: (_date(s.get("date")) or "", _minutes(s.get("start")) or 0))

    out: list[Presentation] = []
    for s in sessions:
        code = str(s["session_code"]).strip()
        session_name = _localized(s, "title") or _localized(s, "label") or code
        start, end = _minutes(s.get("start")), _minutes(s.get("end"))
        ordered = sorted(items_by_session.get(code, []), key=lambda i: float(i.get("order") or 0))
        for it in ordered:
            pid = str(it.get("presentation_id", "")).strip()
            if pid not in pres_by_id:  # ページ側も presentations に無い ID は表示しない
                continue
            p = {**it, **{k: v for k, v in pres_by_id[pid].items() if v not in (None, "")}}
            authors_raw = p.get("authors") or p.get("authors_jp") or p.get("authors_en") or ""
            names, affs = parse_authors(authors_raw)
            out.append(Presentation(
                conference=CONFERENCE,
                event=event,
                year=year,
                session=session_name,
                title=_localized(p, "title") or pid,
                authors=names,
                url=_localized(p, "link") or None,
                presentation_id=pid,
                session_type=str(s.get("type") or "") or None,
                date=_date(s.get("date")),
                time=f"{_hm(start)}–{_hm(end)}" if start is not None else None,
                affiliations=affs,
                authors_raw=str(authors_raw) or None,
                source_url=source_url,
            ))
    return out

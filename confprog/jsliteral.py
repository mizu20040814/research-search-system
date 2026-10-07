"""JavaScript のデータリテラル(配列・オブジェクト)を Python の値に変換する。

本番のページはビルド時に JS が圧縮(minify)されており、埋め込みデータが厳密な JSON ではない。
  {active:!0,title_jp:"受付",n:1e3}   ← キーに引用符が無い、true が !0 になる など
json モジュールでは読めないので、データ部分に出てくる書き方だけを扱う小さなパーサーを用意する。
関数呼び出しや変数参照などの「データでない JS」は扱わない(見つけたらエラーにする)。
"""
from __future__ import annotations

import json
import re

_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_KEYWORDS = {"true": True, "false": False, "null": None, "undefined": None}


class JSLiteralError(ValueError):
    pass


class _Parser:
    def __init__(self, text: str, pos: int):
        self.s = text
        self.i = pos

    def error(self, msg: str) -> JSLiteralError:
        snippet = self.s[self.i:self.i + 40]
        return JSLiteralError(f"{msg} (位置 {self.i}: {snippet!r})")

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise self.error("データの途中で終わっています")
        c = self.s[self.i]
        if c == "[":
            return self.array()
        if c == "{":
            return self.object()
        if c in "\"'`":
            return self.string()
        if self.s.startswith("!0", self.i):
            self.i += 2
            return True
        if self.s.startswith("!1", self.i):
            self.i += 2
            return False
        if self.s.startswith("void 0", self.i):
            self.i += 6
            return None
        m = _NUMBER.match(self.s, self.i)
        if m:
            self.i = m.end()
            num = m.group()
            return float(num) if any(ch in num for ch in ".eE") else int(num)
        m = _IDENT.match(self.s, self.i)
        if m and m.group() in _KEYWORDS:
            self.i = m.end()
            return _KEYWORDS[m.group()]
        raise self.error("データとして読めない値です")

    def array(self) -> list:
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.ws()
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "]":
                raise self.error("配列の区切りが見つかりません")

    def object(self) -> dict:
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.s[self.i] == "}":
                self.i += 1
                return out
            if self.s[self.i] in "\"'`":
                key = self.string()
            else:
                m = _IDENT.match(self.s, self.i) or _NUMBER.match(self.s, self.i)
                if not m:
                    raise self.error("オブジェクトのキーが読めません")
                key = m.group()
                self.i = m.end()
            self.ws()
            if self.s[self.i] != ":":
                raise self.error("':' が見つかりません")
            self.i += 1
            out[key] = self.value()
            self.ws()
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "}":
                raise self.error("オブジェクトの区切りが見つかりません")

    def string(self) -> str:
        quote = self.s[self.i]
        if quote == '"':
            # ダブルクオートの文字列は JSON とほぼ同じなので json に任せる
            value, end = json.JSONDecoder().raw_decode(self.s, self.i)
            self.i = end
            return value
        self.i += 1
        buf = []
        while True:
            if self.i >= len(self.s):
                raise self.error("文字列が閉じていません")
            c = self.s[self.i]
            if c == quote:
                self.i += 1
                return "".join(buf)
            if quote == "`" and self.s.startswith("${", self.i):
                raise self.error("テンプレート文字列の式は扱えません")
            if c == "\\":
                nxt = self.s[self.i + 1]
                if nxt == "u":
                    buf.append(chr(int(self.s[self.i + 2:self.i + 6], 16)))
                    self.i += 6
                    continue
                buf.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0"}.get(nxt, nxt))
                self.i += 2
                continue
            buf.append(c)
            self.i += 1


def parse_at(text: str, pos: int):
    """text[pos:] から始まる JS リテラルを1つ読み、(値, 終了位置) を返す。"""
    p = _Parser(text, pos)
    value = p.value()
    return value, p.i

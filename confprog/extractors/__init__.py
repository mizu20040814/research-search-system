"""学会ごとの抽出器。新しい学会は extract(html, source_url, year) を持つモジュールを足して REGISTRY に登録する。"""
from . import anlp, miru

REGISTRY = {
    "anlp": anlp,
    "miru": miru,
}

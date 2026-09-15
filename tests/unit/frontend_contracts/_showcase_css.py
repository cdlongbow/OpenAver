"""共用 helper：把 pages/showcase/ 底下的 part 依檔名排序串接成完整字串。

刻意不 parse web/templates/_showcase_css.html：
「template 清單 == 本目錄排序」這條不變式由 scripts/css-guard.mjs 的 CG-148A-PARTS-01
在 `npm run lint` 強制（順序／完整性／幽靈條目三者一次鎖住），所以目錄排序就是正典順序。
測試端再自己 parse 一次 HTML 只會多一份會分岔的實作，且要追著合法 HTML 的表示形式跑
（屬性順序、單雙引號、大小寫、自閉合……）——那是 2026-09-15 Codex 兩輪 review 的根因。
"""
from pathlib import Path


def read_showcase_css_full(static_dir: Path) -> str:
    """把 pages/showcase/ 底下的 part 依檔名排序串接成完整字串（逐 byte 等於拆檔前的 showcase.css）。

    刻意不 parse web/templates/_showcase_css.html：
    「template 清單 == 本目錄排序」這條不變式由 scripts/css-guard.mjs 的 CG-148A-PARTS-01
    在 `npm run lint` 強制（順序／完整性／幽靈條目三者一次鎖住），所以目錄排序就是正典順序。
    測試端再自己 parse 一次 HTML 只會多一份會分岔的實作，且要追著合法 HTML 的表示形式跑
    （屬性順序、單雙引號、大小寫、自閉合……）——那是 2026-09-15 Codex 兩輪 review 的根因。
    """
    parts_dir = static_dir / "css" / "pages" / "showcase"
    names = sorted(p.name for p in parts_dir.glob("*.css"))
    if not names:
        raise AssertionError(
            f"read_showcase_css_full: {parts_dir} 底下找不到任何 .css part 檔"
        )
    return "".join((parts_dir / n).read_text(encoding="utf-8") for n in names)

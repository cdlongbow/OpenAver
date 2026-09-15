"""共用 helper：從 _showcase_css.html 解析 part 清單，串接成拆檔前逐 byte 相同的完整字串。

單一來源＝ web/templates/_showcase_css.html（CD-148a-3）。比照 scripts/css-guard.mjs 的
showcasePartsFromTemplate()（CD-148a-6/7）與 Node 端同構邏輯（本 task 另外兩份）——三處都是
執行期解析同一份 _showcase_css.html，不是各自維護一份靜態陣列，權威來源只有一個。
"""
import re
from pathlib import Path

_LINK_RE = re.compile(r'<link\s+href="/static/css/(pages/showcase/[^"]+\.css)"')


def _showcase_parts_from_template(templates_dir: Path) -> list[str]:
    html = (templates_dir / "_showcase_css.html").read_text(encoding="utf-8")
    parts = _LINK_RE.findall(html)
    if not parts:
        raise AssertionError(
            "_showcase_parts_from_template: _showcase_css.html 內找不到任何 "
            "pages/showcase/*.css <link>（template 格式被改了？）"
        )
    return parts


def read_showcase_css_full(static_dir: Path, templates_dir: Path) -> str:
    """依 _showcase_css.html 的 <link> 順序，把 8 個 part 串接成一份完整字串（逐 byte 等於拆檔前的 showcase.css）。"""
    parts = _showcase_parts_from_template(templates_dir)
    return "".join((static_dir / "css" / p).read_text(encoding="utf-8") for p in parts)

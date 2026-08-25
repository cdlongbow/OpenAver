"""粗顆粒源碼守衛：餵給 `get_enabled_source_ids()` 的 map 必須來自 `routing_availability_map()`。

**為什麼是函式作用域，不是「前 3 行的 window」**（PR #157 Codex P2 抓到，實測重現）：
初版用「呼叫點往上 3 行」當比對範圍，有兩個已知假陽性——
  (a) 把 `routing_availability_map()` 的賦值往上挪超過 3 行（中間插日誌／驗證）→ 誤紅；
  (b) window 內任何**註解**提到舊的 `availability_map()` → 誤紅。
兩者都不改變行為，卻會讓 pytest 無理由轉紅、卡住開發迴圈。

現在改成：以 `ast` 取**函式邊界**，並用 `tokenize` 把 **COMMENT 與 STRING 都剝掉**（＝只看可執行文字，
Codex 要的 "code-aware"），再對整個函式本體做兩條斷言。行距與註解措辭再也影響不了它。

**刻意維持粗顆粒**：不做「引數 → 變數 → 反向找賦值」的資料流分析（那是重型 AST 矩陣，
CLAUDE.md 的 lint 守衛 north-star 要避免的東西）。這條不變式破了的後果是
「抖過一次的來源永遠回不來、搜尋結果安靜地變少」——值得一支守衛，但不值得一套會在每次重構時擋路的。

**它與 4 支行為測試的分工**：目前 4 個呼叫點各自都有行為測試在守（見下方 `_BEHAVIOUR_TESTS`），
那些抓得比本守衛更準。本守衛守的是**未來新增第 5 個呼叫點、而作者忘了寫行為測試**的那個瞬間——
也就是 `gotchas-backend.md` `BE-ASYNC-02` 記的那個形狀：契約建立了但沒有全面接線。
"""
import ast
import io
import re
import tokenize
from pathlib import Path

_TARGETS = ("core/scraper.py", "web/routers/scraper_sources.py")

# 期望至少有這麼多支函式餵 get_enabled_source_ids —— 防止 target 改名／搬走之後
# 守衛變成空掃還一片綠（BE-TEST-09／BE-TEST-13 記的那個形狀）。
_MIN_FEEDING_FUNCS = 4

# 目前覆蓋這些呼叫點的行為測試（僅供讀碼者對照，不參與斷言）
_BEHAVIOUR_TESTS = (
    "tests/unit/test_scraper_routing.py::test_auto_fanout_uses_routing_map_expired_source_retried",
    "tests/unit/test_scraper_uncensored.py::test_uncensored_sources_uses_routing_map_expired_source_retried",
    "tests/unit/test_scraper_routing.py::test_exact_cascade_uses_routing_map_expired_source_retried",
    "tests/integration/test_scraper_sources_api.py::test_expired_cooldown_source_appears_in_capabilities",
)

# 裸的 availability_map( —— 前面緊接 routing_ 的不算
_BARE_MAP_RE = re.compile(r"(?<!routing_)availability_map\s*\(")


def _code_only_lines(src: str) -> list[str]:
    """回傳把 COMMENT 與 STRING token 都抹掉之後的逐行文字（1-based 索引請自行 -1）。

    只抹不刪，維持行號對齊，這樣才能用 ast 的 lineno/end_lineno 直接切函式。
    """
    lines = src.split("\n")
    out = list(lines)
    readline = io.StringIO(src).readline
    for tok in tokenize.generate_tokens(readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        if srow == erow:
            line = out[srow - 1]
            out[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
        else:
            out[srow - 1] = out[srow - 1][:scol]
            for r in range(srow, erow - 1):
                out[r] = ""
            out[erow - 1] = " " * ecol + out[erow - 1][ecol:]
    return out


# [lint-guard: pytest-justified] Python 源碼語意（哪個呼叫點餵哪一張 map），lint 表達不了
class TestMetatubeRoutingGuard:
    """路由端傳進 get_enabled_source_ids 的 availability map 一律來自 routing_availability_map()。"""

    def test_functions_feeding_get_enabled_source_ids_use_routing_map(self):
        repo_root = Path(__file__).resolve().parents[2]
        feeding = []

        for rel in _TARGETS:
            src = (repo_root / rel).read_text(encoding="utf-8")
            code_lines = _code_only_lines(src)

            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                body = "\n".join(code_lines[node.lineno - 1:node.end_lineno])
                if "get_enabled_source_ids(" not in body:
                    continue

                feeding.append(f"{rel}::{node.name}")
                assert "routing_availability_map(" in body, (
                    f"{rel}::{node.name}（第 {node.lineno} 行起）呼叫了 get_enabled_source_ids，"
                    f"但整個函式裡找不到 routing_availability_map()。\n"
                    f"路由端一律要吃 routing_availability_map()——吃顯示用的那張，"
                    f"抖過一次的來源就再也回不來，而使用者只會發現搜尋結果安靜地變少。"
                )
                assert not _BARE_MAP_RE.search(body), (
                    f"{rel}::{node.name}（第 {node.lineno} 行起）出現了裸的 availability_map()。\n"
                    f"那是顯示端的地圖（『最後一次真正驗證過的結果』），不得餵給路由 gate。"
                )

        assert len(feeding) >= _MIN_FEEDING_FUNCS, (
            f"只找到 {len(feeding)} 支餵 get_enabled_source_ids 的函式（期望 >= {_MIN_FEEDING_FUNCS}）："
            f"{feeding}\n這通常代表被守的碼改名或搬家了，守衛正在空掃——"
            f"請更新 _TARGETS／_MIN_FEEDING_FUNCS，不要放著讓它假綠。"
        )

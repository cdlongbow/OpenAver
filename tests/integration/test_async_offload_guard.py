"""
Async-offload 回歸守衛（feature/66 T5）

AST-based 靜態掃描 web/routers/*.py：
  1. 每個 async def 路由的「直接 body」不得裸跑偵測清單中的阻塞慢 I/O 呼叫
     （直接 body = 不下潛 nested FunctionDef / AsyncFunctionDef；
      已包在 await asyncio.to_thread(...) 內的呼叫天然不算裸呼叫，
      因為 to_thread 的 target 是 Name 節點而非 Call 節點）
  2. T1–T3 轉 def 的 handler 確認為 FunctionDef（非 AsyncFunctionDef），
     防止 refactoring 意外把它們改回 async def 而重新卡 event loop

CD-66-5：本守衛屬 pytest C 類（Python API contract / 行為），不走 eslint。
形式參考：tests/integration/test_api_scanner.py::test_jellyfin_check_uses_to_thread
"""
import ast
import pathlib
from typing import Optional

ROUTERS_DIR = pathlib.Path(__file__).parents[2] / "web" / "routers"


# ============================================================
# 偵測清單
# ============================================================

# 直接函式名（ast.Name 的 id，或 ast.Attribute 的 attr）
BLOCKING_FUNC_NAMES = frozenset({
    # File I/O
    "realpath", "getsize", "open",
    # DB
    "init_db", "get_db_path", "VideoRepository", "ActressRepository",
    # Config
    "load_config", "save_config",
    # Sync HTTP（metatube）
    "MetatubeHttpClient", "list_providers", "_verify_token_canary",
})

# Attribute-call 後綴（接在任意物件後 .exists() / .stat() / .iterdir() / .save()）
BLOCKING_ATTR_CALL_NAMES = frozenset({
    "exists", "stat", "iterdir", "save",
})

# 白名單：{(file_stem, func_name)} — 豁免整個函式。
# 目前為空：偵測清單夠精確（只命中具名慢 I/O / repo.* / 檔案 stat），
# in-memory state 操作（state.disconnect / status_dict / _fire_probe）天然不命中，
# 無需豁免。刻意保持空集合 → 連 settings_metatube 的 in-memory 路由都受保護：
# 若它們未來新增裸 load_config/repo 呼叫，守衛會立即報錯而非被白名單放生。
# 只有「確實會命中偵測、但刻意留 loop」的路由才該加入（並附理由）。
WHITELIST: frozenset = frozenset()


# ============================================================
# AST 工具
# ============================================================

def _is_route_handler(node: ast.AsyncFunctionDef) -> bool:
    """確認 node 有 @router.<method>(...) 裝飾器。"""
    for dec in node.decorator_list:
        # @router.get(...) / @router.post(...) 等
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            if isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router":
                return True
        # @router.get（無括號，防禦）
        if isinstance(dec, ast.Attribute):
            if isinstance(dec.value, ast.Name) and dec.value.id == "router":
                return True
    return False


def _collect_direct_calls(func_node: ast.AsyncFunctionDef) -> list:
    """收集 func_node 直接 body 的所有 Call 節點。

    「直接 body」= 不下潛 nested FunctionDef / AsyncFunctionDef
    （nested 函式不是 to_thread target 就是內層 SSE generator，CD-66-3 不在範圍）。
    """
    calls = []

    def _walk(nodes):
        for node in nodes:
            if isinstance(node, ast.Call):
                calls.append(node)
            # 停止條件：遇到巢狀函式定義即不下潛
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _walk(ast.iter_child_nodes(node))

    _walk(ast.iter_child_nodes(func_node))
    return calls


def _call_name(call: ast.Call) -> Optional[str]:
    """取 Call node 的「函式名」用於偵測：
    - ast.Name      → .id    (e.g. load_config())
    - ast.Attribute → .attr  (e.g. db_path.exists(), repo.save())
    """
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_blocking_call(call: ast.Call) -> bool:
    """判斷 call 是否為偵測清單中的裸阻塞呼叫。"""
    name = _call_name(call)
    if name is None:
        return False

    # 直接函式名 / Attribute attr 命中
    if name in BLOCKING_FUNC_NAMES:
        return True
    # Attribute-call 後綴命中（.exists / .stat / .iterdir / .save）
    if name in BLOCKING_ATTR_CALL_NAMES:
        return True
    # repo.* / *_repo.* pattern：value 是 Name 且 id == "repo" 或結尾 "_repo"
    if isinstance(call.func, ast.Attribute):
        val = call.func.value
        if isinstance(val, ast.Name) and (val.id == "repo" or val.id.endswith("_repo")):
            return True
    return False


def _iter_async_route_handlers():
    """yield (py_file, AsyncFunctionDef) for every async route handler in web/routers/*.py."""
    for py_file in sorted(ROUTERS_DIR.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and _is_route_handler(node):
                yield py_file, node


# ============================================================
# 守衛測試
# ============================================================

class TestAsyncOffloadGuard:
    """AST 回歸守衛：async def 路由直接 body 不得裸跑慢 I/O。"""

    def test_no_bare_blocking_in_async_routes(self):
        """主守衛：掃 web/routers/*.py 每個 async 路由，直接 body 不得有裸阻塞呼叫。"""
        violations = []
        for py_file, node in _iter_async_route_handlers():
            if (py_file.stem, node.name) in WHITELIST:
                continue
            for call in _collect_direct_calls(node):
                if _is_blocking_call(call):
                    violations.append(
                        f"{py_file.name}:{node.name}() — bare blocking call: {_call_name(call)}()"
                    )
        assert not violations, (
            "Async route handlers have bare blocking calls on the event loop "
            "(wrap in `await asyncio.to_thread(...)` or convert to `def`):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_whitelist_entries_exist(self):
        """白名單防腐：每個白名單條目對應的函式必須真實存在（避免殭屍豁免）。"""
        found = {(py.stem, n.name) for py, n in _iter_async_route_handlers()}
        missing = [w for w in WHITELIST if w not in found]
        assert not missing, f"WHITELIST 指向不存在的 async 路由（應清理）: {missing}"


class TestConvertedHandlersAreDef:
    """正斷言：T1–T3 轉 def 的 handler 確認為同步 def（不可回退 async def）。"""

    @staticmethod
    def _func_type(filename: str, func_name: str) -> type:
        py_file = ROUTERS_DIR / filename
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                return type(node)
        raise AssertionError(f"{filename}:{func_name} not found")

    # T1 — hot path
    def test_t1_get_image_is_def(self):
        assert self._func_type("scanner.py", "get_image") is ast.FunctionDef

    def test_t1_get_video_is_def(self):
        assert self._func_type("scanner.py", "get_video") is ast.FunctionDef

    # T2 — 純讀 DB 路由
    def test_t2_get_stats_is_def(self):
        assert self._func_type("scanner.py", "get_stats") is ast.FunctionDef

    def test_t2_clear_cache_is_def(self):
        assert self._func_type("scanner.py", "clear_cache") is ast.FunctionDef

    def test_t2_check_update_is_def(self):
        assert self._func_type("scanner.py", "check_update") is ast.FunctionDef

    def test_t2_check_missing_is_def(self):
        assert self._func_type("scanner.py", "check_missing") is ast.FunctionDef

    def test_t2_view_list_is_def(self):
        assert self._func_type("scanner.py", "view_list") is ast.FunctionDef

    def test_t2_get_actress_stats_is_def(self):
        assert self._func_type("scanner.py", "get_actress_stats") is ast.FunctionDef

    def test_t2_showcase_get_videos_is_def(self):
        assert self._func_type("showcase.py", "get_videos") is ast.FunctionDef

    def test_t2_showcase_get_video_is_def(self):
        assert self._func_type("showcase.py", "get_video") is ast.FunctionDef

    def test_t2_get_favorite_files_is_def(self):
        assert self._func_type("search.py", "get_favorite_files") is ast.FunctionDef

    def test_t2_get_local_status_is_def(self):
        assert self._func_type("search.py", "get_local_status") is ast.FunctionDef

    def test_t2_motion_lab_data_is_def(self):
        assert self._func_type("motion_lab.py", "motion_lab_data") is ast.FunctionDef

    # T3 — config / 設定檔 I/O 路由
    def test_t3_get_config_is_def(self):
        assert self._func_type("config.py", "get_config") is ast.FunctionDef

    def test_t3_update_config_is_def(self):
        assert self._func_type("config.py", "update_config") is ast.FunctionDef

    def test_t3_reset_config_is_def(self):
        assert self._func_type("config.py", "reset_config") is ast.FunctionDef

    def test_t3_get_tutorial_status_is_def(self):
        assert self._func_type("config.py", "get_tutorial_status") is ast.FunctionDef

    def test_t3_mark_tutorial_completed_is_def(self):
        assert self._func_type("config.py", "mark_tutorial_completed") is ast.FunctionDef

    def test_t3_reset_tutorial_is_def(self):
        assert self._func_type("config.py", "reset_tutorial") is ast.FunctionDef

    def test_t3_update_general_field_is_def(self):
        assert self._func_type("config.py", "update_general_field") is ast.FunctionDef

    def test_t3_get_scraper_sources_is_def(self):
        assert self._func_type("scraper_sources.py", "get_scraper_sources") is ast.FunctionDef

    def test_t3_get_favorite_scanner_link_is_def(self):
        assert self._func_type("settings_link.py", "get_favorite_scanner_link") is ast.FunctionDef


class TestT4OffloadHousePattern:
    """T4 to_thread 包裝的 house-pattern substring 守衛（延續既有 test_jellyfin_check_uses_to_thread）。"""

    @staticmethod
    def _src(filename: str) -> str:
        return (ROUTERS_DIR / filename).read_text(encoding="utf-8")

    def test_jellyfin_check_uses_to_thread_helper(self):
        src = self._src("scanner.py")
        assert "asyncio.to_thread(_check_jellyfin_needed" in src
        assert "def _check_jellyfin_needed(" in src
        assert "db_path.exists()" in src
        assert "VideoRepository(db_path)" in src
        assert "check_jellyfin_images_needed(repo)" in src

    def test_connect_uses_to_thread_helper(self):
        src = self._src("settings_metatube.py")
        assert "asyncio.to_thread(_connect_sync" in src
        assert "def _connect_sync(" in src
        assert "MetatubeHttpClient" in src
        assert "_verify_token_canary" in src

    def test_actress_crop_uses_to_thread(self):
        src = self._src("actress.py")
        assert "asyncio.to_thread(_check_cover_path" in src
        assert "asyncio.to_thread(crop_video_cover" in src

    def test_set_actress_photo_uses_to_thread(self):
        src = self._src("actress.py")
        assert "asyncio.to_thread(_load_actress" in src
        assert "asyncio.to_thread(_get_actress_videos" in src
        assert "asyncio.to_thread(_write_actress_photo" in src

    def test_search_stream_load_config_offloaded(self):
        assert "await asyncio.to_thread(load_config)" in self._src("search.py")

    def test_filter_files_uses_to_thread(self):
        src = self._src("search.py")
        assert "asyncio.to_thread(_filter_files_sync" in src
        assert "def _filter_files_sync(" in src

    def test_batch_enrich_load_config_offloaded(self):
        assert "await asyncio.to_thread(load_config)" in self._src("scraper.py")

    def test_translate_routes_load_config_offloaded(self):
        assert "await asyncio.to_thread(load_config)" in self._src("translate.py")

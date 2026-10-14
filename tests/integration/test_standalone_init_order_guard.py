"""
Standalone init-order AST 守衛（CD-70c-1 + CD-70c-2 Layer 1 防回退；168d-T4 改寫）

視窗建立與關閉守衛已搬到 windows/cf_windows.py（168d CD-7），本檔因此掃兩棵樹：
  - standalone.py：``main()`` 直屬恰一次 ``cf_windows.build_cf_windows(...)`` 與恰一次
    ``cf_agent.announce()``，皆在 ``webview.start`` 之前、build 在 announce 前、皆不在 ``startup()`` 內；
    ``attach_close_guards`` 恰一次；``_on_main_closing`` 仍銷毀 jl_win／javten_win（B1 殭屍行程）。
  - cf_windows.py：``build_cf_windows`` 內兩個 hidden=True 視窗各自在自己的 try（該 try 不含
    ``PyWebViewCfTransport(`` 建構——helper 內已無 register，原述詞會恆真，見 BE-TEST-11/30）；
    ``attach_close_guards`` 對 jl_win／javten_win 各自以獨立斷言證明被涵蓋，且 hide＋return False。
  - 兩檔皆不得有 ``register_cf_transport`` 呼叫（transport 改交 CfShellAgent，T7 L2 lint 接手後可退場）。

Mirror 慣例來自 tests/integration/test_async_offload_guard.py：
  Path.read_text() + ast.parse, NO import of the target module; plain pytest class.
"""
import ast
import pathlib
from typing import Optional

STANDALONE_PATH = pathlib.Path(__file__).parents[2] / "windows" / "standalone.py"
CF_WINDOWS_PATH = pathlib.Path(__file__).parents[2] / "windows" / "cf_windows.py"


# ──────────────────────────────────────────────────────────────
# AST 工具
# ──────────────────────────────────────────────────────────────

def _find_main_func(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """Find the module-level `main` FunctionDef."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    return None


def _find_module_func(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_cf_builder(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """cf_windows.py 的模組層 `build_cf_windows`。"""
    return _find_module_func(tree, "build_cf_windows")


def _is_cf_build_call(call: ast.Call) -> bool:
    """`cf_windows.build_cf_windows(...)`。"""
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "build_cf_windows"
            and isinstance(f.value, ast.Name) and f.value.id == "cf_windows")


def _is_announce_call(call: ast.Call) -> bool:
    """`cf_agent.announce()`。"""
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == "announce"


def _is_attach_close_guards_call(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "attach_close_guards"
            and isinstance(f.value, ast.Name) and f.value.id == "cf_windows")


def _find_startup_in_main(main_node: ast.FunctionDef) -> Optional[ast.FunctionDef]:
    """Find the `startup` FunctionDef nested inside main()."""
    for node in ast.walk(main_node):
        if isinstance(node, ast.FunctionDef) and node.name == "startup":
            return node
    return None


def _is_webview_start_call(call: ast.Call) -> bool:
    """True iff call is `webview.start(...)` (not `server_thread.start()` etc.)."""
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "start"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "webview"
    )


def _is_webview_create_window_call(call: ast.Call) -> bool:
    """True iff call is `webview.create_window(...)` (not e.g. `win.create_window`)."""
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "create_window"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "webview"
    )


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = 'literal'` assignments (window titles live here, single source)."""
    out: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def _window_title_of(call: ast.Call, consts: dict[str, str]) -> str:
    """First positional arg of create_window, resolving a module-level Name constant."""
    if not call.args:
        return ""
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    if isinstance(first, ast.Name):
        return consts.get(first.id, "")
    return ""


def _is_jl_create_window_call(call: ast.Call, consts: dict[str, str]) -> bool:
    """
    True iff call is the JL webview.create_window(...), identified by its WINDOW TITLE
    (first positional arg — a literal or a module-level constant — contains 'JavLibrary').

    TASK-118a-T1 D-6: `hidden=True` is NOT part of the discriminator (it matches both
    CF windows; asserted separately per call, BE-TEST-05).
    TASK-163b-T7a: the old second-arg fingerprints (JAVLIBRARY_ORIGIN Name / 'about:blank'
    literal) are gone — with the proxy applied JL is also created on a variable URL /
    'about:blank', which would make those predicates count 0 or 2.
    """
    return _is_webview_create_window_call(call) and "JavLibrary" in _window_title_of(call, consts)


def _is_javten_create_window_call(call: ast.Call, consts: dict[str, str]) -> bool:
    """True iff call is the fc-javten webview.create_window(...), identified by its window
    title containing 'javten' (same title-based identification as JL)."""
    return _is_webview_create_window_call(call) and "javten" in _window_title_of(call, consts)


def _call_has_hidden_true(call: ast.Call) -> bool:
    """True iff call has keyword hidden=True. D-6: asserted separately per-call
    now that hidden=True no longer discriminates JL from javten."""
    for kw in call.keywords:
        if kw.arg == "hidden" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _is_register_cf_transport_call(call: ast.Call) -> bool:
    """True iff call is `register_cf_transport(...)` (bare or attribute form)."""
    f = call.func
    return ((isinstance(f, ast.Name) and f.id == "register_cf_transport")
            or (isinstance(f, ast.Attribute) and f.attr == "register_cf_transport"))


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """child → parent map so we can walk enclosing Try nodes."""
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_try_nodes(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[ast.Try]:
    """Innermost-first list of ast.Try ancestors of *node*."""
    tries: list[ast.Try] = []
    cur: ast.AST | None = node
    while cur is not None:
        cur = parents.get(cur)
        if isinstance(cur, ast.Try):
            tries.append(cur)
    return tries


def _is_transport_construction_call(call: ast.Call) -> bool:
    """True iff call is `PyWebViewCfTransport(...)`."""
    return isinstance(call.func, ast.Name) and call.func.id == "PyWebViewCfTransport"


def _try_contains_transport_construction(try_node: ast.Try) -> bool:
    return any(
        isinstance(n, ast.Call) and _is_transport_construction_call(n)
        for n in ast.walk(try_node)
    )


def _collect_calls_in_node(node: ast.AST) -> list[ast.Call]:
    """Collect all Call nodes under node (via ast.walk)."""
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _collect_direct_calls_in_main_body(main_node: ast.FunctionDef) -> list[ast.Call]:
    """
    Collect all Call nodes that appear in main()'s body, NOT descending into
    nested FunctionDef or AsyncFunctionDef nodes (i.e., not into startup()).

    This matches the surface-level body of main() only.
    """
    calls: list[ast.Call] = []

    def _walk(nodes):
        for child in nodes:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # do not descend into nested functions (e.g. startup)
            if isinstance(child, ast.Call):
                calls.append(child)
            _walk(ast.iter_child_nodes(child))

    _walk(ast.iter_child_nodes(main_node))
    return calls


def _find_func_def(node: ast.AST, name: str) -> Optional[ast.FunctionDef]:
    """Find a FunctionDef with the given name anywhere under node (ast.walk)."""
    for n in ast.walk(node):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


# ──────────────────────────────────────────────────────────────
# Guard tests
# ──────────────────────────────────────────────────────────────

def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class TestStandaloneInitOrderGuard:
    """CD-70c-1 + CD-70c-2 Layer 1: structural ordering guard（standalone.py ＋ cf_windows.py）。"""

    @staticmethod
    def _parse() -> tuple[ast.Module, str]:
        src = STANDALONE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(STANDALONE_PATH))
        return tree, src

    @staticmethod
    def _parse_cf() -> ast.Module:
        return _parse(CF_WINDOWS_PATH)

    def test_anti_rot_startup_still_exists_in_main(self):
        """startup FunctionDef 必須仍在 main() 內；改名／移走會讓守衛響亮失敗而非 0 斷言通過。"""
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() FunctionDef not found in standalone.py"
        startup_node = _find_startup_in_main(main_node)
        assert startup_node is not None, (
            "startup() FunctionDef not found inside main() — "
            "if it was renamed, update this guard too"
        )

    def test_cf_build_and_announce_not_inside_startup(self):
        """(a) build_cf_windows／announce 不得在 startup() 內——必須在 main() 直屬、webview.start 之前，
        否則首頁 SSR 時註冊表還沒有這台殼（CD-70c-1 競態）。"""
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        startup_node = _find_startup_in_main(main_node)
        assert startup_node is not None, "startup() not found inside main()"

        violations = [
            c for c in _collect_calls_in_node(startup_node)
            if _is_cf_build_call(c) or _is_announce_call(c) or _is_register_cf_transport_call(c)
        ]
        assert not violations, (
            f"build_cf_windows()/announce() found inside startup() at line(s) "
            f"{[c.lineno for c in violations]} — they must be in main() body BEFORE webview.start() (CD-70c-1)"
        )

    def test_jl_create_window_not_inside_startup(self):
        """(a) 驗證視窗的 create_window 不得在 startup() 內；只有主視窗那次在 main() 直屬。"""
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        startup_node = _find_startup_in_main(main_node)
        assert startup_node is not None, "startup() not found inside main()"

        wv_creates_in_startup = [
            c for c in _collect_calls_in_node(startup_node)
            if _is_webview_create_window_call(c) or _is_cf_build_call(c)
        ]
        assert not wv_creates_in_startup, (
            f"webview.create_window() found inside startup() at line(s) "
            f"{[c.lineno for c in wv_creates_in_startup]} — "
            "CF windows must be created in main() body BEFORE webview.start() (CD-70c-1)"
        )

    def test_cf_build_and_announce_before_webview_start(self):
        """(b) main() 直屬恰一次 build_cf_windows 與恰一次 announce，皆在 webview.start 前，build 在 announce 前。

        mutation: 刪掉 announce() → 恰一次斷言紅；把它移到 webview.start 之後 → 順序斷言紅。
        """
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        direct_calls = _collect_direct_calls_in_main_body(main_node)
        build_calls = [c for c in direct_calls if _is_cf_build_call(c)]
        announce_calls = [c for c in direct_calls if _is_announce_call(c)]
        start_calls = [c for c in direct_calls if _is_webview_start_call(c)]
        assert len(build_calls) == 1, f"expected exactly 1 cf_windows.build_cf_windows() in main(), found {len(build_calls)}"
        assert len(announce_calls) == 1, f"expected exactly 1 announce() in main(), found {len(announce_calls)}"
        assert start_calls, "webview.start() not found in main() body"
        first_start = min(c.lineno for c in start_calls)
        assert build_calls[0].lineno < announce_calls[0].lineno < first_start, (
            "order must be build_cf_windows() -> announce() -> webview.start() in main() (CD-70c-1)"
        )

    def test_no_register_cf_transport_call_in_windows_shell_files(self):
        """transport 不再登記成全域（改交 CfShellAgent）：standalone.py 與 cf_windows.py 都不得有呼叫。
        T7 的 L2 lint 接手後這半可退場。"""
        for path in (STANDALONE_PATH, CF_WINDOWS_PATH):
            tree = _parse(path)
            hits = [n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and _is_register_cf_transport_call(n)]
            assert not hits, f"{path.name} calls register_cf_transport at line(s) {hits}"

    def test_cf_transport_constructed_with_initial_origins(self):
        """PyWebViewCfTransport(...) 必須帶第二個引數（initial_urls 種子）。

        pre-merge Stage 2 FINDING 1：javlibrary 的視窗從不經過 navigate_and_settle，
        `_origins['javlibrary']` 唯一來源就是這顆種子；少了它每個 session 第一次查 JavLibrary
        CF 視窗會多彈一次（可自癒）——粗顆粒守衛：驗「有沒有傳」，不驗傳了什麼。
        """
        helper = _find_cf_builder(self._parse_cf())
        assert helper is not None, "build_cf_windows() not found in cf_windows.py"
        ctors = [c for c in ast.walk(helper) if isinstance(c, ast.Call) and _is_transport_construction_call(c)]
        assert ctors, "PyWebViewCfTransport(...) not found in build_cf_windows()"
        for c in ctors:
            has_seed = len(c.args) >= 2 or any(k.arg == "initial_urls" for k in c.keywords)
            n = len(c.args) + len(c.keywords)
            assert has_seed, (
                "PyWebViewCfTransport() 必須帶第二個引數（initial origins 種子）—— "
                f"實際引數數={n}"
            )

    def _create_call_checks(self, matcher, label):
        cf_tree = self._parse_cf()
        helper = _find_cf_builder(cf_tree)
        assert helper is not None, "build_cf_windows() not found in cf_windows.py"
        consts = _module_string_constants(cf_tree)   # 標題常數搬到 cf_windows.py 了
        creates = [c for c in _collect_direct_calls_in_main_body(helper) if matcher(c, consts)]
        assert len(creates) == 1, (
            f"Expected exactly 1 {label} webview.create_window() in build_cf_windows() body "
            f"(identified by its window title), found {len(creates)}"
        )
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        direct_calls = _collect_direct_calls_in_main_body(main_node)
        build_calls = [c for c in direct_calls if _is_cf_build_call(c)]
        start_calls = [c for c in direct_calls if _is_webview_start_call(c)]
        assert len(build_calls) == 1, "main() must call cf_windows.build_cf_windows() exactly once"
        assert start_calls, "webview.start() not found in main() body"
        assert build_calls[0].lineno < min(c.lineno for c in start_calls), (
            f"build_cf_windows() (creates the {label} window) must be called BEFORE webview.start() (CD-70c-1)"
        )
        assert _call_has_hidden_true(creates[0]), (
            f"{label} webview.create_window() (line {creates[0].lineno}) must carry hidden=True — "
            "it is a background CF window, not the main window"
        )

    def test_jl_create_window_before_webview_start(self):
        """(b) JL create_window（標題含 'JavLibrary'）在 build_cf_windows 內、hidden=True，
        且 main() 在 webview.start 前呼叫 build（BE-TEST-05：JL 與 javten 各自獨立斷言）。"""
        self._create_call_checks(_is_jl_create_window_call, "JavLibrary")

    def test_javten_create_window_before_webview_start(self):
        """(b) fc-javten create_window（標題含 'javten'）同上，獨立斷言（D-6／BE-TEST-05）。"""
        self._create_call_checks(_is_javten_create_window_call, "fc-javten")

    def _own_try_check(self, matcher, label):
        cf_tree = self._parse_cf()
        helper = _find_cf_builder(cf_tree)
        assert helper is not None, "build_cf_windows() not found in cf_windows.py"
        consts = _module_string_constants(cf_tree)
        creates = [c for c in _collect_direct_calls_in_main_body(helper) if matcher(c, consts)]
        assert len(creates) == 1, (
            f"Expected exactly 1 {label} webview.create_window() in build_cf_windows() body, found {len(creates)}"
        )
        parents = _build_parent_map(cf_tree)
        isolated = [t for t in _enclosing_try_nodes(creates[0], parents)
                    if not _try_contains_transport_construction(t)]
        assert isolated, (
            f"{label} webview.create_window() must sit inside an ast.Try that does not construct "
            "PyWebViewCfTransport — a window failure must not skip the transport build and take "
            "the other source down with it"
        )

    def test_javten_create_window_in_own_try_without_transport_construction(self):
        """P2-A：javten 的 create_window 要在自己的 try，該 try 不含 transport 建構。

        helper 內已無 register_cf_transport，舊述詞會恆真；改以 `PyWebViewCfTransport(` 建構為準。
        mutation: 拿掉內層 try（與 transport 建構共用同一個 try）→ red。
        """
        self._own_try_check(_is_javten_create_window_call, "fc-javten")

    def test_jl_create_window_in_own_try_without_transport_construction(self):
        """T11：JL 對稱版（JL 失敗不得讓 fc-javten 一起灰掉）。mutation 同上。"""
        self._own_try_check(_is_jl_create_window_call, "JavLibrary")

    def _attach_close_guards_def(self):
        helper = _find_module_func(self._parse_cf(), "attach_close_guards")
        assert helper is not None, "attach_close_guards() not found in cf_windows.py"
        return helper

    def test_attach_close_guards_binds_closing_hides_and_cancels(self):
        """(c) CD-70c-2 Layer 1：closing 的 `+=` 綁定存在、handler 對視窗呼叫 .hide() 且 return False。"""
        helper = self._attach_close_guards_def()
        bindings = [
            n for n in ast.walk(helper)
            if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add)
            and isinstance(n.target, ast.Attribute) and n.target.attr == "closing"
            and isinstance(n.target.value, ast.Attribute) and n.target.value.attr == "events"
        ]
        assert len(bindings) == 1, f"expected exactly 1 `<win>.events.closing += ...`, found {len(bindings)}"
        hides = [c for c in _collect_calls_in_node(helper)
                 if isinstance(c.func, ast.Attribute) and c.func.attr == "hide"]
        assert hides, "close-intercept must call <win>.hide() to prevent window destruction (CD-70c-2)"
        return_false = [n for n in ast.walk(helper)
                        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                        and n.value.value is False]
        assert return_false, "close-intercept must `return False` to cancel the close event (CD-70c-2)"

    def _iterated_window_fields(self):
        helper = self._attach_close_guards_def()
        loops = [n for n in ast.walk(helper) if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple)]
        assert len(loops) == 1, "attach_close_guards must iterate one literal tuple of windows"
        return {e.attr for e in loops[0].iter.elts if isinstance(e, ast.Attribute)}

    def test_attach_close_guards_covers_jl_win(self):
        """JL 視窗被涵蓋（獨立斷言，BE-TEST-05：不寫 len(...)==2）。"""
        assert "jl_win" in self._iterated_window_fields()

    def test_attach_close_guards_covers_javten_win(self):
        """fc-javten 視窗被涵蓋（獨立斷言）。"""
        assert "javten_win" in self._iterated_window_fields()

    def test_main_attaches_close_guards_exactly_once(self):
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        calls = [c for c in _collect_direct_calls_in_main_body(main_node) if _is_attach_close_guards_call(c)]
        assert len(calls) == 1, f"expected exactly 1 cf_windows.attach_close_guards() in main(), found {len(calls)}"

    def test_main_attaches_close_guards_to_the_built_window_set(self):
        """傳給 attach_close_guards 的第一引數必須是 build_cf_windows(...) 指派出來的那個 set；
        否則換成空的 CfWindowSet() 也全綠，但真正建出的 jl/javten 兩窗沒被綁（舊守衛逐站要求實際視窗被綁）。"""
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"
        targets = set()
        for n in ast.walk(main_node):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                if any(isinstance(c, ast.Call) and _is_cf_build_call(c) for c in ast.walk(n.value)):
                    targets.add(n.targets[0].id)
        assert len(targets) == 1, f"expected build_cf_windows() assigned to exactly one name, found {targets}"
        (calls,) = [[c for c in _collect_direct_calls_in_main_body(main_node) if _is_attach_close_guards_call(c)]]
        assert len(calls) == 1 and calls[0].args and isinstance(calls[0].args[0], ast.Name)
        assert calls[0].args[0].id in targets, (
            f"attach_close_guards() first argument {ast.dump(calls[0].args[0])} is not the set returned by build_cf_windows()"
        )

    def test_on_main_closing_destroys_jl_win(self):
        """
        B1 guard (TASK-70c-B): _on_main_closing must call jl_win.destroy() after
        setting quitting=True, so the hidden JL window is reaped when the main window
        closes. Without this, pywebview only exits when instances==0, but the hidden
        JL window keeps the instance list non-empty → process hangs (zombie).

        AST: find the _on_main_closing FunctionDef inside main(), walk it, assert
        a Call with func.attr=='destroy' and func.value.id=='jl_win'.
        """
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"

        handler_def = _find_func_def(main_node, "_on_main_closing")
        assert handler_def is not None, (
            "def _on_main_closing not found inside main() — "
            "B1 zombie-process fix requires _on_main_closing (standalone.py)"
        )

        # Walk _on_main_closing body for a Call: jl_win.destroy(...)
        handler_calls = _collect_calls_in_node(handler_def)
        jl_destroy_calls = [
            c for c in handler_calls
            if (
                isinstance(c.func, ast.Attribute)
                and c.func.attr == "destroy"
                and isinstance(c.func.value, ast.Name)
                and c.func.value.id == "jl_win"
            )
        ]
        assert jl_destroy_calls, (
            "jl_win.destroy() call not found in _on_main_closing body — "
            "B1 fix: must destroy the hidden JL window on app close so pywebview "
            "can reach instances==0 and exit cleanly (TASK-70c-B)"
        )

    def test_on_main_closing_destroys_javten_win(self):
        """
        TASK-118a-T1 / CD-118a-4b: mirrors test_on_main_closing_destroys_jl_win for
        the second (fc-javten) transport window — a SEPARATE, explicitly-named
        assertion (D-6 / BE-TEST-05): if only jl_win.destroy() is checked, adding
        the javten window without also destroying it on close would keep pywebview's
        instance count above 0 forever (the same zombie-process shape TASK-70c-B
        fixed for jl_win) and this guard would stay green.

        AST: find the _on_main_closing FunctionDef inside main(), walk it, assert
        a Call with func.attr=='destroy' and func.value.id=='javten_win'.
        """
        tree, _ = self._parse()
        main_node = _find_main_func(tree)
        assert main_node is not None, "main() not found"

        handler_def = _find_func_def(main_node, "_on_main_closing")
        assert handler_def is not None, (
            "def _on_main_closing not found inside main() — "
            "B1 zombie-process fix requires _on_main_closing (standalone.py)"
        )

        # Walk _on_main_closing body for a Call: javten_win.destroy(...)
        handler_calls = _collect_calls_in_node(handler_def)
        javten_destroy_calls = [
            c for c in handler_calls
            if (
                isinstance(c.func, ast.Attribute)
                and c.func.attr == "destroy"
                and isinstance(c.func.value, ast.Name)
                and c.func.value.id == "javten_win"
            )
        ]
        assert javten_destroy_calls, (
            "javten_win.destroy() call not found in _on_main_closing body — "
            "CD-118a-4b: must destroy the hidden fc-javten window on app close so "
            "pywebview can reach instances==0 and exit cleanly"
        )

"""166-T3：standalone.py／launcher.py 啟動計時接線（只 ast.parse，不 import 被測模組）。"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).parents[2]
STANDALONE = ROOT / "windows" / "standalone.py"
LAUNCHER = ROOT / "windows" / "launcher.py"

SEVEN = ["modules_loaded", "data_root_ready", "server_thread_started", "server_ready",
         "main_window_created", "cf_windows_created", "first_page_loaded"]


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _trace_calls(node, name):
    """startup_trace.<name>(...) 的 Call 節點。"""
    out = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == name and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "startup_trace"):
            out.append(n)
    return out


def _marks(node):
    """key -> lineno（第一個位置參數為字串常數）。"""
    out = {}
    for c in _trace_calls(node, "mark"):
        if c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str):
            out.setdefault(c.args[0].value, c.lineno)
    return out


def _func(node, name):
    for n in ast.walk(node):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


def _named_calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute | ast.Name)
            and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)]


def _import_linenos(tree):
    """模組層 import：(lineno, 模組名/名稱集合)。"""
    out = []
    for n in ast.iter_child_nodes(tree):
        if isinstance(n, ast.Import):
            out.append((n.lineno, {a.name for a in n.names}))
        elif isinstance(n, ast.ImportFrom):
            out.append((n.lineno, {n.module} | {a.name for a in n.names}))
    return out


def _trace_import_line(tree):
    for ln, names in _import_linenos(tree):
        if "startup_trace" in names:
            return ln
    return None


def _heavy_first_line(tree):
    heavy = {"webview", "pywebview_api", "tray", "webview2_proxy"}
    return min(ln for ln, names in _import_linenos(tree) if names & heavy)


def _last_import_line(tree):
    return max(ln for ln, _ in _import_linenos(tree))


def _module_level_marks(tree):
    return {c.args[0].value: n.lineno for n in ast.iter_child_nodes(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
            for c in [n.value] if c in _trace_calls(n, "mark") and c.args
            and isinstance(c.args[0], ast.Constant)}


def test_standalone_marks_all_seven_stages():
    tree = _tree(STANDALONE)
    keys = _marks(tree)
    assert all(k in keys for k in SEVEN), sorted(set(SEVEN) - set(keys))
    helper = _func(tree, "_arm_first_page_mark")
    assert helper is not None and "first_page_loaded" in _marks(helper)


def test_standalone_mark_order_in_main():
    main = _func(_tree(STANDALONE), "main")
    m = _marks(main)
    order = ["data_root_ready", "server_thread_started", "server_ready",
             "main_window_created", "cf_windows_created"]
    lines = [m[k] for k in order]
    assert lines == sorted(lines) and len(set(lines)) == 5


def test_standalone_flush_follows_setup_logging_before_first_mark():
    main = _func(_tree(STANDALONE), "main")
    flushes = _trace_calls(main, "flush")
    assert len(flushes) == 1
    setup = [c.lineno for c in _named_calls(main, "setup_logging")]
    assert setup and flushes[0].lineno > max(setup)
    assert flushes[0].lineno < min(_marks(main).values())


def test_standalone_arms_first_page_mark_inside_startup():
    tree = _tree(STANDALONE)
    startup = _func(_func(tree, "main"), "startup")
    assert startup is not None
    assert _named_calls(startup, "_arm_first_page_mark")
    first = startup.body[0]
    assert isinstance(first, ast.Expr) and getattr(first.value.func, "id", None) == "_arm_first_page_mark"
    helper = next(n for n in ast.iter_child_nodes(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_arm_first_page_mark")
    assert any(isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Add)
               and isinstance(n.target, ast.Attribute) and n.target.attr == "loaded"
               for n in ast.walk(helper))


def test_standalone_imports_startup_trace_before_heavy_imports():
    tree = _tree(STANDALONE)
    t = _trace_import_line(tree)
    assert t is not None and t < _heavy_first_line(tree)
    modules_loaded = _module_level_marks(tree).get("modules_loaded")
    assert modules_loaded is not None and modules_loaded > _last_import_line(tree)


def test_launcher_marks_subset_stages():
    keys = _marks(_tree(LAUNCHER))
    assert all(k in keys for k in ("modules_loaded", "main_window_created", "first_page_loaded")), keys


def test_launcher_flushes_after_setup_logging():
    tree = _tree(LAUNCHER)
    t = _trace_import_line(tree)
    assert t is not None and t < _heavy_first_line(tree)
    flushes = _trace_calls(tree, "flush")
    assert len(flushes) == 1
    setup = [c.lineno for c in _named_calls(tree, "setup_logging")]
    assert setup and flushes[0].lineno > max(setup)
    create = [c.lineno for c in _named_calls(tree, "create_window")]
    assert create and flushes[0].lineno < min(create)
    others = [ln for k, ln in _marks(tree).items() if k != "modules_loaded"]
    assert all(flushes[0].lineno < ln for ln in others)
    ml = _module_level_marks(tree).get("modules_loaded")
    assert ml is not None and ml > _last_import_line(tree)
    startup = _func(tree, "startup")
    assert startup is not None
    assert "first_page_loaded" in _marks(startup)


def test_standalone_client_path_marks_preflight_then_window_and_no_server_marks():
    tree = _tree(STANDALONE)
    client = _func(tree, "_run_client_mode")
    assert client is not None
    marks = _marks(client)
    assert set(marks) == {"client_preflight_done", "main_window_created"}
    assert marks["client_preflight_done"] < marks["main_window_created"]
    startup = _func(client, "startup")
    assert startup is not None and _named_calls(startup, "_arm_first_page_mark")


def test_launcher_marks_client_preflight_after_flush():
    tree = _tree(LAUNCHER)
    keys = _marks(tree)
    assert "client_preflight_done" in keys
    flushes = _trace_calls(tree, "flush")
    assert flushes and flushes[0].lineno < keys["client_preflight_done"]

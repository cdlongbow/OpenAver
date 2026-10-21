"""175a-T3：import 順序與頂層 import 守衛（新開直譯器；CD-175a-13）。

lint 表達不了 import 圖（173 的循環 import 在 `--fast` 全綠、全套才抓到），所以用 subprocess。
`-I` 會忽略 cwd 與 PYTHONPATH，子行程必須先把 repo 根放進 sys.path。
"""

import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path[:0]=[{str(ROOT)!r}]; {code}"],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    "first_import",
    ["core.scraper", "core.search_providers.pipeline", "core.search_providers.relay", "web.routers.search"],
)
def test_first_import_in_fresh_interpreter(first_import):
    proc = _run(f"import {first_import}")
    assert proc.returncode == 0, proc.stderr[-2000:]


def _provider_module_names() -> list[str]:
    import core.search_providers as pkg

    return sorted(m.name for m in pkgutil.walk_packages(pkg.__path__, prefix="core.search_providers."))


def test_package_top_level_does_not_pull_scraper_or_database():
    names = _provider_module_names()
    assert "core.search_providers.pipeline" in names  # 掃描本身沒壞
    code = (
        "import importlib, sys; "
        f"[importlib.import_module(n) for n in {names!r}]; "
        "bad = [m for m in ('core.scraper', 'core.database') if m in sys.modules]; "
        "assert not bad, bad"
    )
    proc = _run(code)
    assert proc.returncode == 0, proc.stderr[-2000:]

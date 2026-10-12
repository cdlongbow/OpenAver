"""CD-167-1：`proxy_verdict` ＝ metatube relay → 單一公網規則（兩層）。

真 host 名一律 `public_resolver`；字面 IP 免 resolver。每個反向斷言格都有
resolver 回私網的對照並斷言 `resolve.calls` 含該 host（BE-TEST-23）。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from core import image_host_policy
from core.image_host_policy import proxy_verdict
from core.metatube.state import metatube_state

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mt_disconnected():
    metatube_state.disconnect()
    yield
    metatube_state.disconnect()


# 1 ---------------------------------------------------------------------
@pytest.mark.parametrize("scheme", ["https", "http"])
def test_unlisted_public_host_allowed(public_resolver, scheme):
    resolve = public_resolver({"cdn.unlisted.example": ["8.8.8.8"]})
    v = proxy_verdict(f"{scheme}://cdn.unlisted.example/a.jpg")
    assert v.allowed is True and v.reason is None
    assert "cdn.unlisted.example" in resolve.calls


# 2 ---------------------------------------------------------------------
def test_unknown_host_resolving_private_denied(public_resolver):
    resolve = public_resolver({"cdn.unlisted.example": ["10.0.0.5"]})
    v = proxy_verdict("https://cdn.unlisted.example/a.jpg")
    assert v.allowed is False
    assert v.reason.startswith("非公網目標")
    assert "cdn.unlisted.example" in resolve.calls


# 3 ---------------------------------------------------------------------
def test_listed_host_resolving_private_denied(public_resolver):
    """名單不是放行條件（M1）：原名單 host 解私網照拒。"""
    resolve = public_resolver({"pics.dmm.co.jp": ["10.0.0.5"]})
    v = proxy_verdict("https://pics.dmm.co.jp/a.jpg")
    assert v.allowed is False
    assert "pics.dmm.co.jp" in resolve.calls


def test_unknown_host_resolving_public_allowed_listed_not_special(public_resolver):
    resolve = public_resolver({"pics.dmm.co.jp": ["8.8.8.8"]})
    assert proxy_verdict("https://pics.dmm.co.jp/a.jpg").allowed is True
    assert proxy_verdict("https://other.unlisted.example/a.jpg").allowed is True
    assert "other.unlisted.example" in resolve.calls


# 4 ---------------------------------------------------------------------
def test_image_hosts_emptied_gives_identical_verdicts(public_resolver, monkeypatch):
    urls = [
        "https://pics.dmm.co.jp/a.jpg",
        "http://javbus.com/a.jpg",
        "https://sub.javbus.com/a.jpg",
        "https://cdn.unlisted.example/a.jpg",
        "https://priv.example/a.jpg",
        "https://x.example:8443/a.jpg",
        "ftp://cdn.unlisted.example/a.jpg",
        "https://8.8.8.8/a.jpg",
        "https://10.0.0.5/a.jpg",
    ]
    public_resolver({"priv.example": ["10.0.0.5"]})
    before = [proxy_verdict(u) for u in urls]
    monkeypatch.setattr(image_host_policy, "IMAGE_HOSTS", ())
    after = [proxy_verdict(u) for u in urls]
    assert before == after


# 5 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "https://x.example:8443/a.jpg",
        "https://x.example:99999/a.jpg",
        "https://x.example:abc/a.jpg",
        "http://x.example:443/a.jpg",
    ],
)
def test_non_default_port_denied(public_resolver, url):
    public_resolver()
    v = proxy_verdict(url)
    assert v.allowed is False
    assert v.reason == "port 不符"


@pytest.mark.parametrize("url", ["ftp://x.example/a.jpg", "file:///etc/passwd"])
def test_non_http_scheme_denied(public_resolver, url):
    public_resolver()
    assert proxy_verdict(url).allowed is False


def test_http_listed_host_and_subdomain_allowed(public_resolver):
    public_resolver()
    assert proxy_verdict("http://javbus.com/a.jpg").allowed is True
    assert proxy_verdict("https://pics.dmm.co.jp.sub.example/a.jpg").allowed is True
    assert proxy_verdict("https://sub.pics.dmm.co.jp/a.jpg").allowed is True


def test_literal_private_and_empty_host_denied():
    assert proxy_verdict("https://10.0.0.5/a.jpg").allowed is False
    assert proxy_verdict("https://127.0.0.1/a.jpg").allowed is False
    assert proxy_verdict("https:///a.jpg").reason == "URL 無 host"
    assert proxy_verdict("https://8.8.8.8/a.jpg").allowed is True


# 6 ---------------------------------------------------------------------
def test_metatube_relay_private_ip_allowed(public_resolver, mt_disconnected):
    resolve = public_resolver()
    metatube_state.connect("http://192.168.1.177:8080", "", [])
    v = proxy_verdict("http://192.168.1.177:8080/v1/images/primary/X?ratio=0&quality=100")
    assert v.allowed is True and v.reason is None
    assert resolve.calls == []  # 走 metatube 條目，不經公網規則


def test_metatube_private_host_nonrelay_path_denied(public_resolver, mt_disconnected):
    public_resolver()
    metatube_state.connect("http://192.168.1.177:8080", "", [])
    v = proxy_verdict("http://192.168.1.177:8080/other.jpg")
    assert v.allowed is False


# 7 ---------------------------------------------------------------------
def test_metatube_host_nonrelay_path_denied_even_if_public(public_resolver, mt_disconnected):
    """比對失敗不得落到公網規則：預設埠 metatube host 解成公網，非 relay 路徑仍拒。"""
    resolve = public_resolver({"meta.example": ["8.8.8.8"]})
    metatube_state.connect("https://meta.example", "", [])
    assert proxy_verdict("https://meta.example/v1/images/primary/X").allowed is True
    v = proxy_verdict("https://meta.example/other.jpg")
    assert v.allowed is False
    assert v.reason == "path 不在白名單"
    assert "meta.example" not in resolve.calls


# 8 ---------------------------------------------------------------------
def test_guard_and_proxy_verdict_flip_together(public_resolver):
    """I2：同一 resolver、同一 URL，guard.check 與 proxy_verdict 同步由放行變拒絕。"""
    from core.custom_source import guard
    from core.custom_source.errors import BlockedTarget

    url = "https://flip.example/a.jpg"
    public_resolver({"flip.example": ["8.8.8.8"]})
    guard.check(url)
    assert proxy_verdict(url).allowed is True
    public_resolver({"flip.example": ["10.0.0.5"]})
    with pytest.raises(BlockedTarget):
        guard.check(url)
    assert proxy_verdict(url).allowed is False


# 9 ---------------------------------------------------------------------
def test_verdict_independent_of_custom_source_state(public_resolver, tmp_path, monkeypatch):
    """不存在／啟用／停用三態下，同一組 URL 的 verdict 逐欄位相等（行為 9）。"""
    import shutil

    import core.config as core_config
    from core.config import load_config, save_config
    from core.custom_source import registry, state
    from tests.unit._custom_source_fake import finalize_root
    from tests.unit._custom_source_pages import FIXTURE_DIR

    root = tmp_path / "root"
    root.mkdir()
    cfg_path = tmp_path / "cfg" / "config.json"
    cfg_path.parent.mkdir()
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(root))
    monkeypatch.setattr(core_config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(core_config, "CONFIG_DEFAULT_PATH", tmp_path / "none.json")
    monkeypatch.setattr(state, "_gens", {})
    monkeypatch.setattr(state, "_running_id", None)
    finalize_root(root)
    save_config(load_config())
    load_config()

    public_resolver({"pub.example": ["8.8.8.8"], "priv.example": ["10.0.0.5"]})
    urls = ["https://pub.example/a.jpg", "https://priv.example/a.jpg"]

    absent = [proxy_verdict(u) for u in urls]
    assert [v.allowed for v in absent] == [True, False]

    d = root / "custom_sources"
    d.mkdir(exist_ok=True)
    shutil.copy(FIXTURE_DIR / "single-og.yaml", d / "single-og.yaml")
    loaded = registry.load_one("single-og")
    result = {"total": 1, "failed": 0, "cases": [{"index": 0, "number": "SONE-205", "passed": True, "mismatches": []}]}
    assert state.record_result("single-og", loaded.sha256, "passed", result, state.get_gen("single-og"))
    assert state.set_enabled("single-og", True, loaded.sha256)
    enabled = [proxy_verdict(u) for u in urls]
    assert state.set_enabled("single-og", False, loaded.sha256)
    assert state.read_entry("single-og")["enabled"] is False
    disabled = [proxy_verdict(u) for u in urls]

    assert absent == enabled == disabled


# 11 --------------------------------------------------------------------
def test_policy_does_not_load_custom_source_in_subprocess():
    code = (
        "import sys, core.image_host_policy as p\n"
        "assert p.proxy_verdict('https://8.8.8.8/a.jpg').allowed\n"
        "assert not [m for m in sys.modules if m.startswith('core.custom_source')]\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr

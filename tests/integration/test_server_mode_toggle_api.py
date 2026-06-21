"""
TASK-80a-T6b: server_mode toggle 端點 + GET lan-port 整合測試

涵蓋：
  - PUT server_mode=true 成功 → start mock 回 lan_port，config 持久化 true，回傳 lan_ip
  - PUT server_mode=true 失敗（start 拋例外）→ {success:false}，config 不寫 true
  - PUT server_mode=false → stop mock，config 持久化 false，lan_port null
  - PUT server_mode 非 bool 字串 → 400（T1 回歸守衛）
  - GET /api/config/general/lan-port running → {lan_port: 49200, lan_ip: "192.168.1.50"}
  - GET /api/config/general/lan-port stopped → {lan_port: null, lan_ip: null}

Mock 策略：monkeypatch lan_listener singleton 的方法 / 屬性，避免真實 uvicorn 啟動。
          monkeypatch web.lan_listener.get_lan_ip 回固定值供 deterministic 斷言。
Style：mirror test_api_config_endpoints.py（client fixture + mock_config_path fixture）。
"""
import json
import pytest
from fastapi.testclient import TestClient
from web.app import app


class TestServerModeToggleAPI:
    """PUT /api/config/general/server_mode 端點 + GET lan-port（TASK-80a-T6b）"""

    @pytest.fixture
    def mock_config_path(self, tmp_path, monkeypatch):
        """Mock CONFIG_PATH，初始化含 general 的 config（server_mode 預設 false）"""
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"

        config_data = {
            "general": {
                "locale": "zh-TW",
                "theme": "light",
                "sidebar_collapsed": False,
                "tutorial_completed": False,
                "font_size": "md",
                "default_page": "search",
                "server_mode": False,
            },
        }
        config_path.write_text(json.dumps(config_data))
        default_path.write_text(json.dumps(config_data))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)

        return config_path

    def test_toggle_true_returns_lan_port(self, client, mock_config_path, monkeypatch):
        """PUT server_mode true（start mock → 49200）→ 200 {success:true, lan_port:49200, lan_ip:"192.168.1.50"}"""
        monkeypatch.setattr("web.lan_listener.lan_listener.start", lambda *a, **k: 49200)
        monkeypatch.setattr("web.lan_listener.get_lan_ip", lambda: "192.168.1.50")

        resp = client.put("/api/config/general/server_mode", json={"value": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["lan_port"] == 49200
        assert data["lan_ip"] == "192.168.1.50"

    def test_toggle_true_persists_server_mode(self, client, mock_config_path, monkeypatch):
        """PUT server_mode true 成功後 config.json server_mode 寫入 true"""
        monkeypatch.setattr("web.lan_listener.lan_listener.start", lambda *a, **k: 49200)

        client.put("/api/config/general/server_mode", json={"value": True})

        saved = json.loads(mock_config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is True

    def test_toggle_true_start_failure_not_persisted(self, client, mock_config_path, monkeypatch):
        """start() 拋 RuntimeError → {success:false, error:...}，config 不寫 true"""
        def _fail_start(*a, **k):
            raise RuntimeError("port occupied")

        monkeypatch.setattr("web.lan_listener.lan_listener.start", _fail_start)

        resp = client.put("/api/config/general/server_mode", json={"value": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "error" in data

        saved = json.loads(mock_config_path.read_text())
        # server_mode must NOT be persisted as true on start failure
        assert saved.get("general", {}).get("server_mode") is not True

    def test_toggle_false_returns_null_port(self, client, mock_config_path, monkeypatch):
        """PUT server_mode false → stop mock，{success:true, lan_port:null}"""
        stop_called = []

        def _mock_stop(*a, **k):
            stop_called.append(True)

        monkeypatch.setattr("web.lan_listener.lan_listener.stop", _mock_stop)

        resp = client.put("/api/config/general/server_mode", json={"value": False})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["lan_port"] is None
        assert stop_called, "stop() should have been called"

    def test_toggle_false_persists_server_mode_false(self, client, mock_config_path, monkeypatch):
        """PUT server_mode false → config.json server_mode 寫入 false"""
        monkeypatch.setattr("web.lan_listener.lan_listener.stop", lambda *a, **k: None)

        client.put("/api/config/general/server_mode", json={"value": False})

        saved = json.loads(mock_config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is False

    def test_toggle_non_bool_still_400(self, client, mock_config_path):
        """PUT server_mode {value: "true"} (字串) → 400（T1 回歸守衛）"""
        resp = client.put("/api/config/general/server_mode", json={"value": "true"})

        assert resp.status_code == 400

    def test_get_lan_port_running(self, client, mock_config_path, monkeypatch):
        """GET lan-port，listener is_running=True, lan_port=49200 → {lan_port: 49200, lan_ip: "192.168.1.50"}"""
        import web.lan_listener as _ll_mod

        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "is_running", property(lambda self: True))
        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "lan_port", property(lambda self: 49200))
        monkeypatch.setattr(_ll_mod, "get_lan_ip", lambda: "192.168.1.50")

        resp = client.get("/api/config/general/lan-port")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_port"] == 49200
        assert data["lan_ip"] == "192.168.1.50"

    def test_get_lan_port_stopped(self, client, mock_config_path, monkeypatch):
        """GET lan-port，listener is_running=False だが IP は取得可能
        → {lan_port: null, lan_ip: "192.168.1.50"}（P2-3: lan_ip は running に依存しない）

        理由：listener 停止中でも LAN IP は実際に検出可能な場合がある。
        frontend の `?? null` と組み合わせることで：
          - lan_port=null, lan_ip="192.168.1.50" → listener_down バナーを表示
          - lan_port=null, lan_ip=null            → no_lan_ip バナーを表示（IP 本当に不明）
        """
        import web.lan_listener as _ll_mod

        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "is_running", property(lambda self: False))
        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "lan_port", property(lambda self: None))
        monkeypatch.setattr(_ll_mod, "get_lan_ip", lambda: "192.168.1.50")

        resp = client.get("/api/config/general/lan-port")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_port"] is None
        assert data["lan_ip"] == "192.168.1.50"  # IP detectable even when listener is down

    def test_get_lan_port_stopped_ip_undetectable(self, client, mock_config_path, monkeypatch):
        """GET lan-port，listener is_running=False 且 IP も検出不可 → {lan_port: null, lan_ip: null}

        IP が genuinely undetectable の場合のみ lan_ip=null を返す。
        frontend: lanIp=null → no_lan_ip バナー表示。
        """
        import web.lan_listener as _ll_mod

        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "is_running", property(lambda self: False))
        monkeypatch.setattr(_ll_mod.lan_listener.__class__, "lan_port", property(lambda self: None))
        monkeypatch.setattr(_ll_mod, "get_lan_ip", lambda: None)

        resp = client.get("/api/config/general/lan-port")

        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_port"] is None
        assert data["lan_ip"] is None  # genuinely undetectable → no_lan_ip banner

    # ── P1 rollback / persist-first 修復守衛 ───────────────────────────────────

    def test_toggle_true_persist_failure_rolls_back_listener(
        self, client, mock_config_path, monkeypatch
    ):
        """start() 成功但 mutate_config 拋例外 → response success False，
        lan_listener.stop() 被呼叫（rollback），config 不寫 true。"""
        stop_called = []

        monkeypatch.setattr("web.lan_listener.lan_listener.start", lambda *a, **k: 49200)
        monkeypatch.setattr("web.lan_listener.lan_listener.stop",
                            lambda *a, **k: stop_called.append(True))

        def _fail_persist(fn):
            raise OSError("disk full")

        monkeypatch.setattr("web.routers.config.mutate_config", _fail_persist)

        resp = client.put("/api/config/general/server_mode", json={"value": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False, "persist 失敗應回傳 success=False"
        assert stop_called, "listener 應被 rollback stop() 呼叫"
        # config 檔案未被 mutate_config 修改（mock 拋例外前沒有寫入）
        saved = json.loads(mock_config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is not True, (
            "config 不應寫入 true（persist 失敗時）"
        )

    def test_toggle_false_persist_failure_keeps_running(
        self, client, mock_config_path, monkeypatch
    ):
        """disable 路徑：mutate_config 拋例外 → response success False，
        lan_listener.stop() 不被呼叫（config 仍 true，listener 仍跑，兩者一致）。"""
        stop_called = []

        monkeypatch.setattr("web.lan_listener.lan_listener.stop",
                            lambda *a, **k: stop_called.append(True))

        def _fail_persist(fn):
            raise OSError("disk full")

        monkeypatch.setattr("web.routers.config.mutate_config", _fail_persist)

        resp = client.put("/api/config/general/server_mode", json={"value": False})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False, "persist 失敗應回傳 success=False"
        assert not stop_called, "stop() 不應被呼叫（config 未改、listener 繼續跑保持一致）"
        # config 檔案仍為原始值（false，因為 mock_config_path 初始是 false）
        saved = json.loads(mock_config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is False, (
            "config server_mode 應維持 false（初始值，persist 失敗時不可改）"
        )

    # ── Loopback-only guard（feature/80 TASK-80b）─────────────────────────────

    def test_remote_cannot_enable_server_mode(self, mock_config_path, monkeypatch):
        """遠端 IP 的 PUT server_mode true → {success:false}，start 不被呼叫，config 不寫 true。

        遠端客人不得開啟 server_mode；LAN 伺服器是否開放是主機的決定。
        loopback-only guard 必須在 listener/config 操作前 early-return。

        注意：lan_access_gate middleware 讀 config.server_mode 決定放行；測試中先把
        config 設 true（模擬 server_mode 已開）讓 middleware 放行，再驗 router 層
        loopback guard 拒絕此遠端 IP 切換 server_mode。
        """
        import core.config as _cc
        # 讓 middleware 放行遠端 IP（模擬 server_mode 已開）
        _cc.mutate_config(lambda cfg: cfg.setdefault("general", {}).update({"server_mode": True}))

        start_called = []

        def _spy_start(*a, **k):
            start_called.append(True)
            return 49200

        monkeypatch.setattr("web.lan_listener.lan_listener.start", _spy_start)

        remote_client = TestClient(app, client=("192.168.1.50", 12345))
        resp = remote_client.put("/api/config/general/server_mode", json={"value": True})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False, "遠端 IP 應被拒絕（success=False）"
        assert data["reason"] == "remote_forbidden", "前端據此顯示 remote_only 專屬訊息"
        assert "error" in data
        assert not start_called, "lan_listener.start 不應被呼叫（guard 在 start 之前 early-return）"

        saved = json.loads(mock_config_path.read_text())
        # server_mode 仍為 true（我們設的初始值），remote 沒有修改它
        assert saved.get("general", {}).get("server_mode") is True, (
            "config server_mode 應維持初始 true（router guard 拒絕，不寫入任何新值）"
        )

    def test_remote_cannot_disable_server_mode(self, mock_config_path, monkeypatch):
        """遠端 IP 的 PUT server_mode false → {success:false}，stop 不被呼叫。

        遠端客人不得關閉 server_mode；防止遠端自鎖把自己踢出。
        middleware 放行條件同上：先設 server_mode=true 讓請求到達 router。
        """
        import core.config as _cc
        _cc.mutate_config(lambda cfg: cfg.setdefault("general", {}).update({"server_mode": True}))

        stop_called = []

        def _spy_stop(*a, **k):
            stop_called.append(True)

        monkeypatch.setattr("web.lan_listener.lan_listener.stop", _spy_stop)

        remote_client = TestClient(app, client=("192.168.1.50", 12345))
        resp = remote_client.put("/api/config/general/server_mode", json={"value": False})

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False, "遠端 IP 應被拒絕（success=False）"
        assert data["reason"] == "remote_forbidden", "前端據此顯示 remote_only 專屬訊息"
        assert "error" in data
        assert not stop_called, "lan_listener.stop 不應被呼叫（guard 在 stop 之前 early-return）"

    def test_loopback_passes_guard(self, mock_config_path, monkeypatch):
        """loopback（127.0.0.1）PUT server_mode false → guard 通過，進入正常 disable 流程。

        確認 loopback 守衛白名單正常放行（stop 被呼叫）。
        loopback 自帶 middleware 短路（不讀 config），所以不需要預先設 server_mode。
        """
        stop_called = []

        def _spy_stop(*a, **k):
            stop_called.append(True)

        monkeypatch.setattr("web.lan_listener.lan_listener.stop", _spy_stop)

        loopback_client = TestClient(app, client=("127.0.0.1", 50000))
        resp = loopback_client.put("/api/config/general/server_mode", json={"value": False})

        assert resp.status_code == 200
        data = resp.json()
        # loopback 通過 guard，進入 disable 分支（stop 被呼叫 → success=True）
        assert data["success"] is True, "loopback 應通過 guard（success=True）"
        assert stop_called, "loopback disable：lan_listener.stop 應被呼叫"

    def test_toggle_serialized_by_lock(self, mock_config_path, monkeypatch):
        """Codex P2：toggle 交易由 _server_mode_toggle_lock 序列化。

        持有鎖時，併發的 loopback toggle 請求必須被阻擋在鎖上、不得完成；釋放後才完成。
        mutation：若移除 `with _server_mode_toggle_lock`，請求會在持鎖期間就完成 → 本測 RED。
        """
        import threading
        import time
        from web.routers import config as _cfgmod

        monkeypatch.setattr("web.lan_listener.lan_listener.start", lambda *a, **k: 49200)
        monkeypatch.setattr("web.lan_listener.get_lan_ip", lambda: "192.168.1.50")

        result = {}

        def _fire():
            c = TestClient(app, client=("127.0.0.1", 50000))
            r = c.put("/api/config/general/server_mode", json={"value": True})
            result["status"] = r.status_code

        _cfgmod._server_mode_toggle_lock.acquire()
        t = threading.Thread(target=_fire, daemon=True)
        try:
            t.start()
            time.sleep(0.3)  # 給請求時間抵達鎖
            assert "status" not in result, "持鎖期間 toggle 不應完成（應阻塞在 _server_mode_toggle_lock）"
        finally:
            _cfgmod._server_mode_toggle_lock.release()

        t.join(timeout=5)
        assert result.get("status") == 200, "釋放鎖後 toggle 應完成（200）"

    def test_toggle_transaction_wrapped_in_lock(self):
        """結構守衛（deterministic，不依賴 timing）：toggle 交易 + reset 路徑須在
        _server_mode_toggle_lock 內。補強 test_toggle_serialized_by_lock（時間敏感）——
        移除任一 `with _server_mode_toggle_lock:` → count<2 → 本測 RED（mutation-sensitive）。"""
        import pathlib
        src = pathlib.Path(__file__).parents[2].joinpath(
            "web", "routers", "config.py"
        ).read_text(encoding="utf-8")
        assert "_server_mode_toggle_lock = threading.Lock()" in src, \
            "config.py 缺少 _server_mode_toggle_lock 模組級鎖"
        assert src.count("with _server_mode_toggle_lock:") >= 2, \
            "toggle 交易與 reset 路徑都須在 _server_mode_toggle_lock 內（Codex P2 序列化）"

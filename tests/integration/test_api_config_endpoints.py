import pytest
import os
import json
from pathlib import Path
from fastapi.testclient import TestClient
from web.app import app

class TestConfigAPI:
    """測試 web/routers/config.py 的 API 端點"""

    @pytest.fixture
    def mock_config_path(self, tmp_path, monkeypatch):
        """Mock CONFIG_PATH 和 CONFIG_DEFAULT_PATH 避免影響真實設定檔"""
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"
        
        # 建立預設設定檔作為基底
        default_data = {
            "general": {"tutorial_completed": False}
        }
        default_path.write_text(json.dumps(default_data))
        
        # Mock module variables（core.config は load_config/save_config が参照する実体）
        # web.routers.config は _core_config.CONFIG_PATH で動態参照するため、
        # core.config.CONFIG_PATH を差し替えるだけで DELETE /api/config も正しく動く
        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        
        # Mock reset_translate_service dependency to do nothing
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)
        
        return config_path

    def test_delete_config_success(self, client, mock_config_path):
        """測試成功刪除 config.json (恢復原廠設定)"""
        # 手動建立 config_path
        mock_config_path.write_text('{"some": "data"}')
        assert mock_config_path.exists()
        
        response = client.delete("/api/config")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "恢復預設" in data["message"]
        assert not mock_config_path.exists()

    def test_delete_config_not_exists(self, client, mock_config_path):
        """測試當 config.json 不存在時呼叫刪除，不應出錯"""
        if mock_config_path.exists():
            mock_config_path.unlink()
            
        response = client.delete("/api/config")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # 不會報錯，一樣回傳成功

    def test_tutorial_flow(self, client, mock_config_path):
        """測試 tutorial 相關的一系列流程"""
        # 1. 初始化狀態應該是 False
        resp = client.get("/api/tutorial-status")
        assert resp.status_code == 200
        assert resp.json()["completed"] is False
        
        # 2. 標記完成
        resp = client.post("/api/tutorial-completed")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        
        # 再次檢查狀態
        resp = client.get("/api/tutorial-status")
        assert resp.json()["completed"] is True
        
        # 確保檔案真的寫入了 config.json
        assert mock_config_path.exists()
        saved_config = json.loads(mock_config_path.read_text())
        assert saved_config.get("general", {}).get("tutorial_completed") is True
        
        # 3. 重置狀態
        resp = client.post("/api/tutorial-reset")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        
        # 第三次檢查狀態
        resp = client.get("/api/tutorial-status")
        assert resp.json()["completed"] is False
        
        saved_config = json.loads(mock_config_path.read_text())
        assert saved_config.get("general", {}).get("tutorial_completed") is False


class TestLocaleChangeResetsTranslateService:
    """locale 變更應觸發 translate service reset（auto 模式依賴 locale）"""

    @pytest.fixture
    def mock_config_path(self, tmp_path, monkeypatch):
        """Mock CONFIG_PATH，初始化含 general.locale 的 config"""
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"

        config_data = {
            "general": {"locale": "zh-TW", "theme": "light", "sidebar_collapsed": False,
                        "tutorial_completed": False, "font_size": "md", "default_page": "search"},
            "translate": {"enabled": False, "provider": "ollama",
                          "batch_size": 10,
                          "ollama": {"url": "http://localhost:11434", "model": "qwen3:8b"},
                          "gemini": {"api_key": "", "model": "gemini-flash-lite-latest"}},
        }
        config_path.write_text(json.dumps(config_data))
        default_path.write_text(json.dumps(config_data))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)

        return config_path

    def test_locale_change_calls_reset_translate_service(self, client, mock_config_path, monkeypatch):
        """PUT /api/config/general/locale 成功後呼叫 _reset_translate_service()"""
        reset_called = []

        def fake_reset():
            reset_called.append(True)

        monkeypatch.setattr("web.routers.config._reset_translate_service", fake_reset)

        resp = client.put("/api/config/general/locale", json={"value": "en"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(reset_called) == 1, "locale 變更後應呼叫一次 _reset_translate_service()"

    def test_other_field_change_does_not_call_reset(self, client, mock_config_path, monkeypatch):
        """PUT /api/config/general/theme 不應呼叫 _reset_translate_service()"""
        reset_called = []

        def fake_reset():
            reset_called.append(True)

        monkeypatch.setattr("web.routers.config._reset_translate_service", fake_reset)

        resp = client.put("/api/config/general/theme", json={"value": "dark"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(reset_called) == 0, "theme 變更不應呼叫 _reset_translate_service()"

    def test_invalid_locale_does_not_call_reset(self, client, mock_config_path, monkeypatch):
        """不支援的 locale 失敗後不應呼叫 _reset_translate_service()"""
        reset_called = []

        def fake_reset():
            reset_called.append(True)

        monkeypatch.setattr("web.routers.config._reset_translate_service", fake_reset)

        resp = client.put("/api/config/general/locale", json={"value": "ko"})

        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert len(reset_called) == 0, "失敗的 locale 設定不應呼叫 reset"


class TestServerModeEndpoint:
    """PUT /api/config/general/server_mode 端點測試（TASK-80a-T1）"""

    @pytest.fixture
    def mock_config_path(self, tmp_path, monkeypatch):
        """Mock CONFIG_PATH，初始化含 general 的 config。
        同時 mock lan_listener.start/stop 避免真實 uvicorn 啟動（T6b 起 server_mode true
        觸發 lan_listener.start()，測試環境未 wire → 需 mock）。"""
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"

        config_data = {
            "general": {"locale": "zh-TW", "theme": "light", "sidebar_collapsed": False,
                        "tutorial_completed": False, "font_size": "md", "default_page": "search"},
        }
        config_path.write_text(json.dumps(config_data))
        default_path.write_text(json.dumps(config_data))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)
        # T6b: server_mode toggle 呼叫 lan_listener.start()/stop() — mock 避免真實啟動
        monkeypatch.setattr("web.lan_listener.lan_listener.start", lambda *a, **k: 49200)
        monkeypatch.setattr("web.lan_listener.lan_listener.stop", lambda *a, **k: None)

        return config_path

    def test_server_mode_true_returns_200_success(self, client, mock_config_path):
        """PUT server_mode {value: true} → 200 {"success": True}"""
        resp = client.put("/api/config/general/server_mode", json={"value": True})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_server_mode_true_persisted(self, client, mock_config_path):
        """PUT server_mode {value: true} → config.json 寫入 general.server_mode=True"""
        client.put("/api/config/general/server_mode", json={"value": True})

        saved = json.loads(mock_config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is True

    def test_server_mode_reload_yields_true(self, client, mock_config_path, monkeypatch):
        """PUT server_mode true → 持久化後重讀 load_config() 仍為 True（AC-A8）"""
        import core.config as cc
        client.put("/api/config/general/server_mode", json={"value": True})

        reloaded = cc.load_config()
        assert reloaded.get("general", {}).get("server_mode") is True

    def test_server_mode_string_true_returns_400(self, client, mock_config_path):
        """PUT server_mode {value: "true"} (字串) → HTTP 400（gate 擋字串）"""
        resp = client.put("/api/config/general/server_mode", json={"value": "true"})

        assert resp.status_code == 400

    def test_server_mode_string_false_returns_400_not_stored(self, client, mock_config_path):
        """安全性關鍵：字串 "false" 是 truthy，必須 400 且不得寫入 config
        （否則 middleware bool("false")=True 會誤開對外）。"""
        resp = client.put("/api/config/general/server_mode", json={"value": "false"})

        assert resp.status_code == 400
        saved = json.loads(mock_config_path.read_text())
        assert "server_mode" not in saved.get("general", {})

    def test_server_mode_int_one_rejected(self, client, mock_config_path):
        """PUT server_mode {value: 1} (int) → 被拒（StrictBool|StrictStr schema 層擋整數 → 422）"""
        resp = client.put("/api/config/general/server_mode", json={"value": 1})

        assert resp.status_code == 422
        saved = json.loads(mock_config_path.read_text())
        assert "server_mode" not in saved.get("general", {})

    def test_theme_string_still_200_regression(self, client, mock_config_path):
        """PUT theme {value: "dark"} 字串路徑不受影響 → 仍 200 success（不回歸）"""
        resp = client.put("/api/config/general/theme", json={"value": "dark"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestFullConfigSavePreservesServerMode:
    """P2-1: PUT /api/config（全量儲存）不得改寫 server_mode（toggle-lifecycle 所有權）

    Divergence path（confirmed):
      PUT /api/config accepts AppConfig body → Pydantic model_validates the incoming
      general section.  If the payload's general.server_mode is False (Pydantic default
      when the key is absent) or explicitly False, the old save_config() call would write
      that value over a persisted True — leaving the LAN listener running but
      general.server_mode=false in config.json (diverged).

    Fix: update_config() now runs mutate_config(_write_preserving_server_mode) which
    reads the currently-persisted server_mode under the write lock and forces it into the
    payload before writing, regardless of what the incoming body says.
    """

    @pytest.fixture
    def mock_config_path_with_server_mode_true(self, tmp_path, monkeypatch):
        """Config pre-seeded with general.server_mode=true (listener "running")."""
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
                "server_mode": True,  # persisted True — listener is "running"
            },
            "translate": {
                "enabled": False,
                "provider": "ollama",
                "batch_size": 10,
                "ollama": {"url": "http://localhost:11434", "model": "qwen3:8b"},
                "gemini": {"api_key": "", "model": "gemini-flash-lite-latest"},
                "openai": {"base_url": "", "api_key": "", "model": "gpt-4o-mini",
                           "use_custom_model": False},
            },
            "thumbnail_cache_enabled": False,
        }
        config_path.write_text(json.dumps(config_data))
        default_path.write_text(json.dumps(config_data))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)

        return config_path

    def test_full_save_omitting_server_mode_preserves_true(
        self, client, mock_config_path_with_server_mode_true
    ):
        """PUT /api/config whose general body OMITS server_mode must NOT reset it to False.

        Simulates the frontend saveConfig() behaviour: it sends a full AppConfig body but
        the general section only sets known form fields (default_page, theme) and does NOT
        include server_mode.  The Pydantic default for missing server_mode is False —
        without the preservation guard this would silently overwrite the persisted True
        and diverge from lan_listener.is_running (still True).
        """
        config_path = mock_config_path_with_server_mode_true

        # Build a minimal valid AppConfig payload.  general.server_mode is deliberately
        # absent — Pydantic will default it to False.
        payload = {
            "general": {
                "default_page": "search",
                "theme": "dark",
                # server_mode intentionally omitted → Pydantic default False
            },
            "scraper": {},
            "search": {},
            "source_links": {},
            "translate": {
                "enabled": False,
                "provider": "ollama",
                "batch_size": 10,
                "ollama": {"url": "http://localhost:11434", "model": "qwen3:8b"},
                "gemini": {"api_key": "", "model": "gemini-flash-lite-latest"},
                "openai": {"base_url": "", "api_key": "", "model": "gpt-4o-mini",
                           "use_custom_model": False},
            },
            "gallery": {},
            "showcase": {},
            "sources": [],
            "thumbnail_cache_enabled": False,
            "metatube": {},
        }

        resp = client.put("/api/config", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        saved = json.loads(config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is True, (
            "PUT /api/config must preserve the persisted server_mode=true; "
            "omitting the field in the payload must not reset it to False "
            "(would diverge from running LAN listener)"
        )

    def test_full_save_explicit_false_server_mode_still_preserves_true(
        self, client, mock_config_path_with_server_mode_true
    ):
        """PUT /api/config with general.server_mode=false in the body must also be ignored.

        A stale GET → full PUT round-trip from an old client (or any direct API call)
        that explicitly sends server_mode=false must NOT overwrite the persisted True.
        Only PUT /api/config/general/server_mode (the toggle endpoint) is allowed to
        change this field.
        """
        config_path = mock_config_path_with_server_mode_true

        payload = {
            "general": {
                "default_page": "search",
                "theme": "light",
                "server_mode": False,  # stale / incorrect — must be ignored
            },
            "scraper": {},
            "search": {},
            "source_links": {},
            "translate": {
                "enabled": False,
                "provider": "ollama",
                "batch_size": 10,
                "ollama": {"url": "http://localhost:11434", "model": "qwen3:8b"},
                "gemini": {"api_key": "", "model": "gemini-flash-lite-latest"},
                "openai": {"base_url": "", "api_key": "", "model": "gpt-4o-mini",
                           "use_custom_model": False},
            },
            "gallery": {},
            "showcase": {},
            "sources": [],
            "thumbnail_cache_enabled": False,
            "metatube": {},
        }

        resp = client.put("/api/config", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        saved = json.loads(config_path.read_text())
        assert saved.get("general", {}).get("server_mode") is True, (
            "PUT /api/config with explicit server_mode=false in the body must be "
            "ignored — server_mode is owned by the toggle lifecycle endpoint only"
        )


class TestDeleteConfigStopsLanListener:
    """P2-4: DELETE /api/config (reset) は LAN listener を停止しなければならない

    reset_config_file() は server_mode を含む config を削除する → defaults では
    server_mode が存在しない（= false）。しかし listener は停止しないと
    runtime（listener 起動中）≠ persisted（server_mode absent）が分離し、
    0.0.0.0 socket が 403 を返し続けてしまう。
    """

    @pytest.fixture
    def mock_config_path(self, tmp_path, monkeypatch):
        """DELETE /api/config 用 fixture — lan_listener.stop() も mock する"""
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"

        config_data = {"general": {"server_mode": True}}
        config_path.write_text(json.dumps(config_data))
        default_path.write_text(json.dumps(config_data))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)

        return config_path

    def test_delete_config_calls_lan_listener_stop(self, client, mock_config_path, monkeypatch):
        """DELETE /api/config → lan_listener.stop() は必ず 1 回呼ばれる

        reset は server_mode を消去する（defaults = false）ため、listener の
        runtime↔persisted を一致させるために stop() を呼ぶ必要がある。
        stop() は idempotent なので listener が起動していなくても安全。
        """
        stop_called = []

        monkeypatch.setattr(
            "web.lan_listener.lan_listener.stop",
            lambda *a, **k: stop_called.append(True),
        )

        resp = client.delete("/api/config")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(stop_called) == 1, (
            "DELETE /api/config must call lan_listener.stop() once to keep "
            "runtime↔persisted consistent after config reset clears server_mode"
        )

    def test_delete_config_stop_called_even_when_not_running(
        self, client, mock_config_path, monkeypatch
    ):
        """stop() は idempotent なので listener が起動していなくても呼ばれてよい

        stop() の no-op 保証により、listener が実行中かどうかに関わらず
        reset ハンドラは stop() を呼び出す（毎回呼ぶ方が明確で安全）。
        """
        stop_called = []

        # Simulate listener already not running — stop() is still called (idempotent no-op)
        monkeypatch.setattr(
            "web.lan_listener.lan_listener.stop",
            lambda *a, **k: stop_called.append(True),
        )

        resp = client.delete("/api/config")

        assert resp.status_code == 200
        assert len(stop_called) == 1, "stop() must always be called on reset (idempotent)"


class TestSwitchExternalManagerEndpoint:
    """POST /api/config/switch-external-manager 端點測試（TASK-90c-T4）

    破壞性重設：切換全域 external_manager 時原子刪除離線（唯讀）來源的 DB 卡 +
    移除離線 config 條目 + 設新 external_manager。零檔案系統刪除。含可自癒失敗契約。

    測試以真 config.json（CONFIG_PATH monkeypatch）讓 mutate_config 真的 RMW，
    DB 側 mock（呼叫處 binding web.routers.config.VideoRepository），縮圖 spy。
    """

    class _FakeRepo:
        """有狀態的假 VideoRepository：delete 真的從內部清單移除，供收斂測試。"""
        def __init__(self, paths):
            self._paths = list(paths)
            self.delete_calls = []

        def get_all(self):
            import types
            return [types.SimpleNamespace(path=p) for p in self._paths]

        def delete_by_paths(self, paths):
            self.delete_calls.append(list(paths))
            if not paths:  # 對齊真實 delete_by_paths :669 早退
                return 0
            deleted = [p for p in paths if p in self._paths]
            for p in deleted:
                self._paths.remove(p)
            return len(deleted)

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        import types
        config_path = tmp_path / "config.json"
        default_path = tmp_path / "config.default.json"
        default_path.write_text(json.dumps({"general": {}}))

        monkeypatch.setattr("core.config.CONFIG_PATH", config_path)
        monkeypatch.setattr("core.config.CONFIG_DEFAULT_PATH", default_path)
        monkeypatch.setattr("web.routers.config._reset_translate_service", lambda: None)

        # DB 依賴：避免碰真實 DB（get_db_path/init_db no-op），VideoRepository 回共享 fake
        monkeypatch.setattr("web.routers.config.get_db_path", lambda: tmp_path / "videos.db")
        monkeypatch.setattr("web.routers.config.init_db", lambda *a, **k: None)

        holder = types.SimpleNamespace(repo=None, invalidated=[], config_path=config_path)
        monkeypatch.setattr("web.routers.config.VideoRepository", lambda *a, **k: holder.repo)

        # 縮圖 spy（best-effort）
        fake_tc = types.SimpleNamespace(invalidate=lambda p: holder.invalidated.append(p))
        monkeypatch.setattr("web.routers.config.thumbnail_cache", fake_tc)

        def write_config(directories, external_manager="off", path_mappings=None):
            gallery = {"directories": directories}
            if path_mappings:
                gallery["path_mappings"] = path_mappings
            config_path.write_text(json.dumps({
                "gallery": gallery,
                "scraper": {"external_manager": external_manager},
            }))

        def set_videos(paths):
            holder.repo = TestSwitchExternalManagerEndpoint._FakeRepo(paths)

        holder.write_config = write_config
        holder.set_videos = set_videos
        holder.read_config = lambda: json.loads(config_path.read_text())
        return holder

    def test_mixed_only_offline_deleted(self, client, env):
        """混合可寫 + 離線：只刪離線卡，可寫 config 條目 + 卡零影響。"""
        env.write_config([
            {"path": "file:///D:/writable_src", "readonly": False},
            {"path": "file:///D:/ro_src", "readonly": True},
        ], external_manager="off")
        env.set_videos([
            "file:///D:/writable_src/A/A.strm",
            "file:///D:/ro_src/B/B.strm",
        ])

        resp = client.post("/api/config/switch-external-manager",
                           json={"external_manager": "jellyfin"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["removed_sources"] == 1
        assert body["deleted_cards"] == 1
        assert body["external_manager"] == "jellyfin"

        # delete_by_paths 只收到離線來源下的卡
        assert env.repo.delete_calls == [["file:///D:/ro_src/B/B.strm"]]
        # 縮圖只對離線卡失效
        assert env.invalidated == ["file:///D:/ro_src/B/B.strm"]

        cfg = env.read_config()
        dirs = cfg["gallery"]["directories"]
        assert len(dirs) == 1
        assert dirs[0]["path"] == "file:///D:/writable_src"
        assert cfg["scraper"]["external_manager"] == "jellyfin"

    def test_no_offline_only_persists_external_manager(self, client, env):
        """無離線來源：delete_by_paths([]) 回 0，僅落盤 external_manager，removed_sources:0。"""
        env.write_config([
            {"path": "file:///D:/writable_src", "readonly": False},
        ], external_manager="off")
        env.set_videos(["file:///D:/writable_src/A/A.strm"])

        resp = client.post("/api/config/switch-external-manager",
                           json={"external_manager": "emby"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["removed_sources"] == 0
        assert body["deleted_cards"] == 0
        assert body["external_manager"] == "emby"

        assert env.repo.delete_calls == [[]]  # 空 list 呼叫、回 0
        assert env.invalidated == []

        cfg = env.read_config()
        dirs = cfg["gallery"]["directories"]
        assert len(dirs) == 1
        assert dirs[0]["path"] == "file:///D:/writable_src"
        assert cfg["scraper"]["external_manager"] == "emby"

    def test_file_uri_prefix_boundary(self, client, env):
        """file:/// 前綴命中：離線來源 file:///D:/ro_src，卡在其下 → 命中，兄弟前綴不誤中。"""
        env.write_config([
            {"path": "file:///D:/ro_src", "readonly": True},
        ], external_manager="off")
        env.set_videos([
            "file:///D:/ro_src/ABC-001/ABC-001.strm",  # 命中
            "file:///D:/ro_src2/XYZ/XYZ.strm",          # 兄弟前綴，不得誤中
        ])

        resp = client.post("/api/config/switch-external-manager",
                           json={"external_manager": "kodi"})

        assert resp.status_code == 200
        assert env.repo.delete_calls == [["file:///D:/ro_src/ABC-001/ABC-001.strm"]]
        assert resp.json()["deleted_cards"] == 1

    def test_unc_prefix_boundary_no_valueerror(self, client, env):
        """UNC 前綴邊界（唯讀主場景）：離線來源 \\\\nas\\media，卡落其下命中且不拋 ValueError。"""
        from core.path_utils import coerce_to_file_uri
        card = coerce_to_file_uri(r"\\nas\media\ABC-001\ABC-001.strm")
        env.write_config([
            {"path": r"\\nas\media", "readonly": True},
        ], external_manager="off")
        env.set_videos([card])

        resp = client.post("/api/config/switch-external-manager",
                           json={"external_manager": "jellyfin"})

        assert resp.status_code == 200  # 無 ValueError
        assert resp.json()["deleted_cards"] == 1
        assert env.repo.delete_calls == [[card]]

    def test_failure_contract_then_convergence(self, client, env):
        """失敗契約：mutate_config 拋錯 → success:False，卡已刪但離線仍在 config +
        external_manager 未變；重觸發 → delete no-op + config 落盤成功（收斂）。"""
        from unittest.mock import patch
        env.write_config([
            {"path": "file:///D:/writable_src", "readonly": False},
            {"path": "file:///D:/ro_src", "readonly": True},
        ], external_manager="off")
        env.set_videos([
            "file:///D:/writable_src/A/A.strm",
            "file:///D:/ro_src/B/B.strm",
        ])

        # 第一次：mutate_config 拋錯
        with patch("web.routers.config.mutate_config", side_effect=RuntimeError("boom")):
            resp1 = client.post("/api/config/switch-external-manager",
                                json={"external_manager": "jellyfin"})

        assert resp1.status_code == 200
        assert resp1.json()["success"] is False
        assert "error" in resp1.json()
        # 卡已刪（delete_by_paths 收到離線卡）
        assert env.repo.delete_calls == [["file:///D:/ro_src/B/B.strm"]]
        # config 未變：離線來源仍在，external_manager 仍 off
        cfg1 = env.read_config()
        paths1 = [d["path"] for d in cfg1["gallery"]["directories"]]
        assert "file:///D:/ro_src" in paths1
        assert cfg1["scraper"]["external_manager"] == "off"

        # 第二次（不 patch）：離線卡已缺席 → delete no-op 回 0；config 這次落盤成功
        resp2 = client.post("/api/config/switch-external-manager",
                            json={"external_manager": "jellyfin"})

        assert resp2.status_code == 200
        assert resp2.json()["success"] is True
        assert resp2.json()["deleted_cards"] == 0  # 已缺席 → no-op
        # 第二次的 delete 收到空 list（重算已無離線卡）
        assert env.repo.delete_calls[-1] == []
        cfg2 = env.read_config()
        paths2 = [d["path"] for d in cfg2["gallery"]["directories"]]
        assert "file:///D:/ro_src" not in paths2  # 離線條目已移除
        assert "file:///D:/writable_src" in paths2  # 可寫保留
        assert cfg2["scraper"]["external_manager"] == "jellyfin"

    def test_invalid_literal_returns_422_no_side_effect(self, client, env):
        """Literal-422：非法 external_manager → 422，端點體未執行、delete_by_paths 未呼叫、config 零變更。"""
        env.write_config([
            {"path": "file:///D:/ro_src", "readonly": True},
        ], external_manager="off")
        env.set_videos(["file:///D:/ro_src/B/B.strm"])

        resp = client.post("/api/config/switch-external-manager",
                           json={"external_manager": "invalid_mode"})

        assert resp.status_code == 422
        assert env.repo.delete_calls == []  # 端點體未執行
        cfg = env.read_config()
        # config 零變更
        assert [d["path"] for d in cfg["gallery"]["directories"]] == ["file:///D:/ro_src"]
        assert cfg["scraper"]["external_manager"] == "off"

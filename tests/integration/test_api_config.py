import json
from core.config import AppConfig

def test_get_config(client, temp_config_path):
    """測試獲取設定"""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "scraper" in data["data"]
    assert "gallery" in data["data"]
    
    # 驗證 Phase 3.2 新增的欄位
    gallery = data["data"]["gallery"]
    assert "output_dir" in gallery
    assert "output_filename" in gallery

def test_update_config(client, temp_config_path):
    """測試更新設定"""
    # 先獲取當前設定
    response = client.get("/api/config")
    current_config = response.json()["data"]
    
    # 修改設定
    current_config["gallery"]["output_dir"] = "test_output"
    current_config["gallery"]["output_filename"] = "test.html"
    current_config["general"]["theme"] = "dark"
    
    # PUT 更新
    response = client.put("/api/config", json=current_config)
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # 再次獲取驗證
    response = client.get("/api/config")
    new_config = response.json()["data"]
    assert new_config["gallery"]["output_dir"] == "test_output"
    assert new_config["gallery"]["output_filename"] == "test.html"
    assert new_config["general"]["theme"] == "dark"

def test_config_persistence(client, temp_config_path):
    """測試設定持久化（寫入檔案）"""
    # 修改設定
    response = client.get("/api/config")
    cfg = response.json()["data"]
    cfg["scraper"]["max_title_length"] = 99
    
    client.put("/api/config", json=cfg)
    
    # 直接讀取檔案驗證
    with open(temp_config_path, 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
        
    assert saved_data["scraper"]["max_title_length"] == 99


def test_update_config_preserves_newer_focal_device_against_stale_full_save(client, temp_config_path):
    """PR review finding（152c-Codex P2）：全量 PUT 不得用前端持有的舊快照覆蓋背景
    record_outcome 剛寫入的 focal_device —— 否則已被判定「裝置太慢、自動對焦停用」的機器
    會被一次不相關的整份存檔（如僅僅改資料夾清單）悄悄打回啟用，且重新湊滿兩次逾時後
    會再發一次「自動對焦已停用」通知，違反 spec F6「一次轉態一則」。
    regression for web/routers/config.py::_write_preserving_server_mode 新增的
    focal_device 保留邏輯（與 server_mode 同一 shape）。
    """
    from core.version import VERSION

    # Seed：背景對焦已把裝置判定停用（模擬 core.focal.device_state.record_outcome
    # 剛落盤的結果）——直接寫檔而非呼叫 record_outcome，維持本測試只驗證
    # web/routers/config.py 這一層的邊界（record_outcome 本身已有 tests/unit/
    # test_focal_device_state.py 的 INV-152c-1/2/3 覆蓋）。
    with open(temp_config_path, 'r', encoding='utf-8') as f:
        seeded = json.load(f)
    seeded_focal_device = {
        "disabled": True,
        "consecutive_timeout_count": 2,
        "judged_at_version": VERSION,
    }
    seeded["focal_device"] = seeded_focal_device
    with open(temp_config_path, 'w', encoding='utf-8') as f:
        json.dump(seeded, f)

    # 前端持有的舊快照：focal_device 停用前的樣子，外加一個「這次存檔真的要改」的
    # 不相關欄位（gallery.output_dir）——同時證明保留 focal_device 沒有讓整個
    # cfg.update(payload) 失效（否則第一條斷言在「PUT 整個壞掉、什麼都沒寫」的
    # 退化實作下也會通過）。
    stale_payload = json.loads(json.dumps(seeded))
    stale_payload["focal_device"] = {
        "disabled": False,
        "consecutive_timeout_count": 0,
        "judged_at_version": "",
    }
    stale_payload["gallery"]["output_dir"] = "regression_output"

    response = client.put("/api/config", json=stale_payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    with open(temp_config_path, 'r', encoding='utf-8') as f:
        persisted = json.load(f)

    # focal_device 必須逐字維持 seed 的值 —— 沒有被舊快照覆蓋。
    assert persisted["focal_device"] == seeded_focal_device
    # 不相關欄位確實被這次 PUT 更新（承重斷言：排除「整份存檔沒生效」的假陽性）。
    assert persisted["gallery"]["output_dir"] == "regression_output"


# ============ 路由改名向後兼容測試 ============

def test_gallery_legacy_redirect(client):
    """GET /gallery 應 302 轉址到 /scanner"""
    response = client.get("/gallery", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/scanner"


def test_scanner_route_ok(client):
    """GET /scanner 應正常回應 200"""
    response = client.get("/scanner")
    assert response.status_code == 200


class TestTranslateConfigRoundTrip:
    """測試 translate 設定 round-trip（GET → PUT → GET）"""

    def test_translate_config_roundtrip(self, client, temp_config_path):
        """translate.enabled 和 translate.provider 應在 round-trip 後保留"""
        response = client.get("/api/config")
        assert response.status_code == 200
        config_data = response.json()["data"]

        config_data["translate"]["enabled"] = True
        config_data["translate"]["provider"] = "gemini"

        response = client.put("/api/config", json=config_data)
        assert response.status_code == 200
        assert response.json()["success"] is True

        response = client.get("/api/config")
        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["translate"]["enabled"] is True
        assert updated["translate"]["provider"] == "gemini"

    def test_openai_config_roundtrip(self, client, temp_config_path):
        """translate.openai 設定在 round-trip 後應完整保留"""
        response = client.get("/api/config")
        assert response.status_code == 200
        config_data = response.json()["data"]

        config_data["translate"]["provider"] = "openai"
        config_data["translate"]["openai"] = {
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-roundtrip",
            "model": "gpt-4o"
        }

        response = client.put("/api/config", json=config_data)
        assert response.status_code == 200
        assert response.json()["success"] is True

        response = client.get("/api/config")
        assert response.status_code == 200
        updated = response.json()["data"]

        assert updated["translate"]["provider"] == "openai"
        openai_cfg = updated["translate"]["openai"]
        assert openai_cfg["base_url"] == "https://api.openai.com/v1"
        # CD-114c-8: API 層改斷言遮罩形狀；round-trip 保存性質下移到 load_config 函式層
        from core.secret_fields import mask_secret
        from core.config import load_config as _load_config
        assert openai_cfg["api_key"] == mask_secret("sk-test-roundtrip")
        assert _load_config()["translate"]["openai"]["api_key"] == "sk-test-roundtrip"
        assert openai_cfg["model"] == "gpt-4o"


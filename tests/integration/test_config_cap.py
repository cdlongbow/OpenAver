"""TASK-61c-2: PUT /api/config 來源啟用上限（cap=10）守衛測試。

endpoint-level check（非 model_validator）：
- enabled=true AND manual_only=false count > 10 → HTTP 400 {error:'cap_exceeded',max:10}
- 恰 10 → 200
- manual_only 不計入 cap basis（CD-61-17）
"""



def _make_source(idx, *, enabled=True, manual_only=False):
    return {
        "id": f"src{idx}",
        "type": "builtin",
        "display_name_key": f"Src{idx}",
        "display_name_raw": "",
        "enabled": enabled,
        "order": idx,
        "config": {},
        "is_beta": False,
        "manual_only": manual_only,
    }


def _base_config(client):
    resp = client.get("/api/config")
    return resp.json()["data"]


def test_manual_only_not_counted_toward_cap(client, temp_config_path):
    """10 enabled non-manual + 1 enabled manual_only → 200（manual_only 不吃 cap）。"""
    cfg = _base_config(client)
    cfg["sources"] = [_make_source(i) for i in range(10)] + [
        _make_source(99, enabled=True, manual_only=True)
    ]

    resp = client.put("/api/config", json=cfg)
    assert resp.status_code == 200
    assert resp.json()["success"] is True



"""tests/unit/test_focal_notification_wiring.py — CD-152c-20：web/app.py 在
module level 註冊 device_state 的通知埠，指向真正的 emit_notification。

不測「呼叫會不會轉發」（那件事已被 test_focal_device_state.py 的
TestNotificationSinkTransition 用假 sink 證過）；這支只測「注入的是誰」——
import web.app 這件事本身就要完成註冊，不依賴 lifespan（BE-ENV-09：桌面版不跑
lifespan shutdown/startup；且用 TestClient 但不啟 lifespan 的既有測試不能拿到
「沒註冊」的 app）。
"""
from __future__ import annotations


def test_importing_web_app_registers_emit_notification_as_sink():
    import web.app as webapp
    from core.focal import device_state

    assert device_state._notification_sink is webapp.emit_notification

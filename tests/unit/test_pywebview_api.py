"""
tests/unit/test_pywebview_api.py
TDD-lite: windows/pywebview_api.py の Api.open_url() 邊界條件測試

pywebview は Windows 専用。すべてのシステムコールをモックして実行する。
"""
import pytest
import sys
from unittest.mock import MagicMock
from pathlib import Path
import importlib.util

import core.client_settings as client_settings
from core.path_utils import uri_to_fs_path


@pytest.fixture
def api_module(monkeypatch):
    """
    pywebview_api モジュールをロードする。
    webview モジュールをモックして import エラーを回避する。
    """
    mock_webview = MagicMock()
    mock_webview.OPEN_DIALOG = 10
    mock_webview.FOLDER_DIALOG = 20
    monkeypatch.setitem(sys.modules, 'webview', mock_webview)
    monkeypatch.setitem(sys.modules, 'webview.dom', MagicMock())

    spec = importlib.util.spec_from_file_location(
        "pywebview_api_test",
        Path(__file__).parent.parent.parent / "windows" / "pywebview_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api_instance(api_module, monkeypatch, tmp_path):
    # 釘死本機模式：不讀開發機真實 client.json／config.json
    import core.config as core_config
    monkeypatch.setenv("OPENAVER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core_config, "CONFIG_PATH", tmp_path / "config.json")
    w = MagicMock()
    w.get_current_url.return_value = "http://127.0.0.1:8000/"
    api_module.set_window(w)
    inst = api_module.Api()
    inst._seen_origin = "http://127.0.0.1:8000"
    inst._trusted = True
    return inst


# ---------------------------------------------------------------------------
# Case 1: valid https URL → True
# ---------------------------------------------------------------------------
def test_open_url_https_success(api_module, api_instance, monkeypatch):
    """https:// URL を win32 で開いた場合 True を返す"""
    monkeypatch.setattr(sys, 'platform', 'win32')

    mock_startfile = MagicMock()
    monkeypatch.setattr(api_module.os, 'startfile', mock_startfile, raising=False)

    result = api_instance.open_url("https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=abc123/")
    assert result is True
    mock_startfile.assert_called_once_with("https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=abc123/")


# ---------------------------------------------------------------------------
# Case 2: valid http URL → True
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 3: empty string → False
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 4: javascript: scheme → False
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 5: file:// scheme → False
# ---------------------------------------------------------------------------
def test_open_url_file_scheme(api_module, api_instance, monkeypatch):
    """file:// スキームは拒否して False を返す"""
    monkeypatch.setattr(sys, 'platform', 'win32')

    mock_startfile = MagicMock()
    monkeypatch.setattr(api_module.os, 'startfile', mock_startfile, raising=False)

    result = api_instance.open_url("file:///C:/evil.exe")
    assert result is False
    mock_startfile.assert_not_called()


# ---------------------------------------------------------------------------
# Case 6: valid URL + os.startfile raises OSError → False
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 7: None → False
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 8: macOS subprocess returns non-zero → False
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Case 9: Linux subprocess returns zero → True
# ---------------------------------------------------------------------------


# ===========================================================================
# P1-2: Logger tests — verify all 7 except blocks emit the correct log level
# ===========================================================================

# ---------------------------------------------------------------------------
# Logger test 1: open_file — custom player Popen raises OSError → logger.warning
# ---------------------------------------------------------------------------
def test_open_file_custom_player_popen_oserror_logs_warning(api_module, api_instance, monkeypatch):
    """custom player の Popen が OSError → logger.warning を呼ぶ（fallback は継続）"""
    monkeypatch.setattr(sys, 'platform', 'win32')

    # ファイルとプレイヤーだけが存在するように見せる
    video = uri_to_fs_path('C:\\video.mp4')
    monkeypatch.setattr(api_module.os.path, 'exists', lambda p: p in {video, 'C:\\Players\\vlc.exe'})

    # player_path が有効なプレイヤーを返す
    monkeypatch.setattr(client_settings, 'player_path', lambda: 'C:\\Players\\vlc.exe')

    # Popen は失敗、startfile は成功
    monkeypatch.setattr(api_module.subprocess, 'Popen', MagicMock(side_effect=OSError("spawn failed")))
    monkeypatch.setattr(api_module.os, 'startfile', MagicMock(), raising=False)

    mock_logger = MagicMock()
    monkeypatch.setattr(api_module, 'logger', mock_logger)

    result = api_instance.open_file('C:\\video.mp4')

    mock_logger.warning.assert_called_once()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert 'custom player failed' in warning_msg
    assert 'falling back to OS default' in warning_msg
    # fallback should continue — startfile called and result is True
    api_module.os.startfile.assert_called_once()
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Logger test 2: open_file — OS default startfile raises OSError → logger.error
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Logger test 3: open_url — os.startfile raises OSError → logger.error
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Logger test 4: open_folder — subprocess.Popen raises OSError → logger.error
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Logger test 5-7: client_settings facade readers — 壞 JSON → logger.warning + fallback
# （原 _get_video_extensions／_get_player_path／_load_config_extensions 隨 facade 搬到
#  core.client_settings；原三種失敗原因各自保留斷言）
# ---------------------------------------------------------------------------
def _bad_config(monkeypatch, tmp_path, text='{invalid json'):
    import core.config as core_config
    bad = tmp_path / 'config.json'
    bad.write_text(text, encoding='utf-8')
    monkeypatch.setattr(core_config, "CONFIG_PATH", bad)
    mock_logger = MagicMock()
    monkeypatch.setattr(client_settings, 'logger', mock_logger)
    return mock_logger


# ---------------------------------------------------------------------------
# TASK-153b-T1: readers share core.config.CONFIG_PATH seam
# ---------------------------------------------------------------------------

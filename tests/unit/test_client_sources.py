"""TASK-168b-T2: core.client_sources.list_sources（CD-168b-10）。"""
from __future__ import annotations


from core.client_sources import list_sources


def test_list_sources_str_dict_and_readonly(tmp_path):
    cfg = {
        "gallery": {
            "directories": [
                str(tmp_path / "s"),
                {"path": str(tmp_path / "d"), "readonly": True},
            ]
        },
        "search": {"favorite_folder": ""},
    }
    out = list_sources(cfg)
    assert [(s["path"], s["kind"], s["readonly"]) for s in out] == [
        (str(tmp_path / "s"), "directory", False),
        (str(tmp_path / "d"), "directory", True),
    ]
    assert all(s["sample"] is None for s in out)


def test_list_sources_favorite_listed_once_as_favorite():
    out = list_sources({"gallery": {"directories": []}, "search": {"favorite_folder": "  /fav  "}})
    assert out == [{"path": "/fav", "kind": "favorite", "readonly": False, "sample": None}]


def test_list_sources_path_is_verbatim():
    weird = "/Volumes/AV/Mixed Case/"
    out = list_sources({"gallery": {"directories": [weird]}, "search": {"favorite_folder": "/Fav/UPPER"}})
    assert [s["path"] for s in out] == [weird, "/Fav/UPPER"]


def test_file_uri_source_outputs_bare_server_path_and_sample(tmp_path):
    from core.path_utils import to_file_uri

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "v.mp4").write_bytes(b"")
    uri = to_file_uri(str(tmp_path / "lib"))
    out = list_sources({"gallery": {"directories": [uri]}})
    assert out[0]["path"] == str(tmp_path / "lib")
    assert out[0]["sample"] == str(tmp_path / "lib" / "v.mp4")


def test_is_under_tolerates_trailing_slash_and_both_separators():
    """Windows 伺服器來源 `D:/AV/`（file:/// 轉換後尾斜線）仍認得底下的候選，
    `/`、`\\` 兩種分隔符都算；同前綴的兄弟資料夾不算。"""
    from core.client_sources import _is_under  # noqa: PLC2701

    assert _is_under("D:/AV/a/v.mp4", "D:/AV/")
    assert _is_under("D:\\AV\\a\\v.mp4", "D:/AV/")
    assert _is_under("D:/AV/v.mp4", "D:\\AV\\")
    assert not _is_under("D:/AV2/v.mp4", "D:/AV/")
    assert not _is_under("D:/AV", "D:/AV/")

"""TASK-168b-T2: core.client_sources.list_sources（CD-168b-10）。"""
from __future__ import annotations

import os
from types import SimpleNamespace

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


def test_list_sources_favorite_blank_not_listed():
    for blank in ("", "   "):
        assert list_sources({"gallery": {"directories": []}, "search": {"favorite_folder": blank}}) == []


def test_list_sources_favorite_listed_once_as_favorite():
    out = list_sources({"gallery": {"directories": []}, "search": {"favorite_folder": "  /fav  "}})
    assert out == [{"path": "/fav", "kind": "favorite", "readonly": False, "sample": None}]


def test_list_sources_dedup_keeps_directory():
    cfg = {"gallery": {"directories": [{"path": "/x", "readonly": True}]}, "search": {"favorite_folder": "/x"}}
    out = list_sources(cfg)
    assert len(out) == 1
    assert out[0]["kind"] == "directory"
    assert out[0]["readonly"] is True


def test_list_sources_path_is_verbatim():
    weird = "/Volumes/AV/Mixed Case/"
    out = list_sources({"gallery": {"directories": [weird]}, "search": {"favorite_folder": "/Fav/UPPER"}})
    assert [s["path"] for s in out] == [weird, "/Fav/UPPER"]


def test_sample_is_first_video_under_path(tmp_path):
    root = tmp_path / "Lib"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.MP4").write_bytes(b"")
    (root / "note.txt").write_bytes(b"")
    out = list_sources({"gallery": {"directories": [str(root)]}})
    sample = out[0]["sample"]
    assert sample == str(root / "sub" / "a.MP4")
    assert sample.startswith(str(root) + os.sep)


def test_sample_prefix_boundary_sibling_candidate_rejected(tmp_path, monkeypatch):
    """越界候選（`av2/v.mp4`）真的被 scandir 吐出來，必須被前綴邊界擋下，
    改取合法候選（`av/ok.mp4`）。刪掉 startswith 判斷時本測試必紅。"""
    (tmp_path / "av").mkdir()
    (tmp_path / "av2").mkdir()
    (tmp_path / "av2" / "v.mp4").write_bytes(b"")
    (tmp_path / "av" / "ok.mp4").write_bytes(b"")

    def _entry(path):
        return SimpleNamespace(
            name=os.path.basename(path),
            path=path,
            is_dir=lambda follow_symlinks=True: False,
            is_file=lambda follow_symlinks=True: True,
        )

    entries = [_entry(str(tmp_path / "av2" / "v.mp4")), _entry(str(tmp_path / "av" / "ok.mp4"))]

    class _Scan:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(entries)

    monkeypatch.setattr("core.client_sources.os.scandir", lambda p: _Scan())
    out = list_sources({"gallery": {"directories": [str(tmp_path / "av")]}})
    assert out[0]["sample"] == str(tmp_path / "av" / "ok.mp4")

    del entries[1]
    assert list_sources({"gallery": {"directories": [str(tmp_path / "av")]}})[0]["sample"] is None


def test_file_uri_source_outputs_bare_server_path_and_sample(tmp_path):
    from core.path_utils import to_file_uri

    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "v.mp4").write_bytes(b"")
    uri = to_file_uri(str(tmp_path / "lib"))
    out = list_sources({"gallery": {"directories": [uri]}})
    assert out[0]["path"] == str(tmp_path / "lib")
    assert out[0]["sample"] == str(tmp_path / "lib" / "v.mp4")


def test_sample_depth_limit(tmp_path):
    deep = tmp_path / "r" / "1" / "2" / "3" / "4"
    deep.mkdir(parents=True)
    (deep / "v.mp4").write_bytes(b"")
    assert list_sources({"gallery": {"directories": [str(tmp_path / "r")]}})[0]["sample"] is None


def test_sample_uses_configured_extensions(tmp_path):
    (tmp_path / "a.xyz").write_bytes(b"")
    cfg = {"gallery": {"directories": [str(tmp_path)]}, "scraper": {"video_extensions": [".xyz"]}}
    assert list_sources(cfg)[0]["sample"] == str(tmp_path / "a.xyz")


def test_sample_broken_symlink_does_not_crash(tmp_path):
    os.symlink(tmp_path / "nowhere", tmp_path / "broken")
    (tmp_path / "ok.mp4").write_bytes(b"")
    out = list_sources({"gallery": {"directories": [str(tmp_path)]}})
    assert out[0]["sample"] == str(tmp_path / "ok.mp4")


def test_sample_missing_directory_is_null():
    assert list_sources({"gallery": {"directories": ["/definitely/not/here"]}})[0]["sample"] is None


def test_sample_scan_is_bounded_to_200_entries(tmp_path, monkeypatch):
    seen = {"n": 0}

    class _FakeScan:
        def __init__(self, path):
            self._path = str(path)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            for i in range(5000):
                seen["n"] += 1
                name = f"f{i}.txt"
                yield SimpleNamespace(
                    name=name,
                    path=os.path.join(self._path, name),
                    is_dir=lambda follow_symlinks=True: False,
                    is_file=lambda follow_symlinks=True: True,
                )

    monkeypatch.setattr("core.client_sources.os.scandir", lambda p: _FakeScan(p))
    out = list_sources({"gallery": {"directories": [str(tmp_path)]}})
    assert out[0]["sample"] is None
    assert 0 < seen["n"] <= 200


def test_is_under_tolerates_trailing_slash_and_both_separators():
    """Windows 伺服器來源 `D:/AV/`（file:/// 轉換後尾斜線）仍認得底下的候選，
    `/`、`\\` 兩種分隔符都算；同前綴的兄弟資料夾不算。"""
    from core.client_sources import _is_under  # noqa: PLC2701

    assert _is_under("D:/AV/a/v.mp4", "D:/AV/")
    assert _is_under("D:\\AV\\a\\v.mp4", "D:/AV/")
    assert _is_under("D:/AV/v.mp4", "D:\\AV\\")
    assert not _is_under("D:/AV2/v.mp4", "D:/AV/")
    assert not _is_under("D:/AV", "D:/AV/")

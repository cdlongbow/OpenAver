"""
test_readonly_source.py — core/readonly_source.py 純函式直測（TASK-90c-T2）

兩個無 IO 純函式：
- is_path_readonly(file_uri, readonly_prefixes) -> bool
- readonly_source_prefixes(gallery_config, path_mappings) -> list

純邏輯、無 IO → 直接傳 dict/list，無需 mock。
"""

from core.readonly_source import is_path_readonly, readonly_source_prefixes
from core.path_utils import to_file_uri


class TestIsPathReadonly:
    """is_path_readonly：無 IO 純比對。"""

    def test_hit_returns_true(self):
        prefix = to_file_uri("/tmp/ro_src", {})
        file_uri = to_file_uri("/tmp/ro_src/ABC-001.mp4", {})
        assert is_path_readonly(file_uri, [prefix]) is True

    def test_miss_returns_false(self):
        prefix = to_file_uri("/tmp/ro_src", {})
        file_uri = to_file_uri("/tmp/rw_src/ABC-001.mp4", {})
        assert is_path_readonly(file_uri, [prefix]) is False

    def test_empty_prefixes_returns_false(self):
        file_uri = to_file_uri("/tmp/ro_src/ABC-001.mp4", {})
        assert is_path_readonly(file_uri, []) is False

    def test_hit_among_multiple_prefixes(self):
        p1 = to_file_uri("/tmp/other", {})
        p2 = to_file_uri("/tmp/ro_src", {})
        file_uri = to_file_uri("/tmp/ro_src/ABC-001.mp4", {})
        assert is_path_readonly(file_uri, [p1, p2]) is True

    def test_unc_prefix_hit(self):
        prefix = to_file_uri(r"\\server\share", {})
        file_uri = to_file_uri(r"\\server\share\ABC-001.mp4", {})
        assert is_path_readonly(file_uri, [prefix]) is True

    def test_canonical_file_uri_prefix(self):
        # 來源已是 canonical file:/// URI，片也是 → 命中
        prefix = "file:///D:/ro"
        file_uri = "file:///D:/ro/ABC.mp4"
        assert is_path_readonly(file_uri, [prefix]) is True


class TestReadonlySourcePrefixes:
    """readonly_source_prefixes：枚舉唯讀來源 → coerce 成前綴集。"""

    def test_readonly_source_filtered_in(self):
        gallery = {"directories": [{"path": "/tmp/ro_src", "readonly": True}]}
        prefixes = readonly_source_prefixes(gallery, {})
        assert prefixes == [to_file_uri("/tmp/ro_src", {})]

    def test_writable_source_filtered_out(self):
        gallery = {"directories": [{"path": "/tmp/rw_src", "readonly": False}]}
        assert readonly_source_prefixes(gallery, {}) == []

    def test_bare_str_source_filtered_out(self):
        # 裸 str 來源 → iter_gallery_sources 降級 readonly=False → 不計入
        gallery = {"directories": ["/tmp/bare_src"]}
        assert readonly_source_prefixes(gallery, {}) == []

    def test_empty_gallery_returns_empty(self):
        assert readonly_source_prefixes({}, {}) == []
        assert readonly_source_prefixes({"directories": []}, {}) == []

    def test_mixed_only_readonly_kept(self):
        gallery = {
            "directories": [
                {"path": "/tmp/ro_src", "readonly": True},
                {"path": "/tmp/rw_src", "readonly": False},
                "/tmp/bare_src",
            ]
        }
        prefixes = readonly_source_prefixes(gallery, {})
        assert prefixes == [to_file_uri("/tmp/ro_src", {})]

    def test_source_missing_path_skipped(self):
        gallery = {"directories": [{"path": "", "readonly": True}]}
        assert readonly_source_prefixes(gallery, {}) == []

    def test_dirty_source_raising_valueerror_skipped(self, mocker):
        """coerce_to_file_uri 拋 ValueError 的髒來源 → skip、不使整批拋。"""
        good_prefix = to_file_uri("/tmp/ro_good", {})

        def fake_coerce(value, mappings=None):
            if value == "DIRTY":
                raise ValueError("dirty path")
            return good_prefix

        mocker.patch("core.readonly_source.coerce_to_file_uri", side_effect=fake_coerce)
        gallery = {
            "directories": [
                {"path": "DIRTY", "readonly": True},
                {"path": "/tmp/ro_good", "readonly": True},
            ]
        }
        prefixes = readonly_source_prefixes(gallery, {})
        assert prefixes == [good_prefix]

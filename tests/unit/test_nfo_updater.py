"""
測試 core/nfo_updater.py 的 needs_update() 和 update_nfo_file()
新欄位：director / duration / series / label / plot / rating / mpaa

TDD-lite 策略：先 RED → 實作 GREEN
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import core.path_utils as path_utils
from core.nfo_updater import (
    add_actor,
    add_tags_and_genres,
    check_cache_needs_update,
    get_nfo_path_from_video,
    needs_update,
    update_nfo_file,
    update_nfo_user_tags,
)


# ============================================================
# Helper
# ============================================================

def make_base_info(**kwargs) -> dict:
    """建立最小有效的 info dict（has_nfo=True 的情境，有番號）。
    預設值模擬所有欄位皆有值，可用 kwargs 覆蓋。
    """
    base = {
        'num': 'TEST-001',
        'title': 'テストタイトル',
        'date': '2024-01-01',
        'actor': '女優A',
        'genre': 'ジャンルA',
        'maker': '片商A',
        'director': '監督A',
        'duration': 90,
        'series': 'シリーズA',
        'label': 'labelA',
    }
    base.update(kwargs)
    return base


def write_nfo(tmp_path: Path, content: str, filename: str = "test.nfo") -> str:
    """將 NFO 內容寫入 tmp_path，回傳路徑字串。"""
    nfo = tmp_path / filename
    nfo.write_text(content, encoding="utf-8")
    return str(nfo)


# ============================================================
# needs_update() 測試
# ============================================================

class TestNeedsUpdateNewFields:
    """needs_update() 對新欄位（director/duration/series/label）的判斷"""

    # 1. 缺 director → missing 含 'director'

    # 2. duration=None → missing 含 'duration'

    # 3. duration=0 → 不列入 missing（0 是有效值）

    # 4. 缺 series → 不再檢查（來源不一定有）
    @pytest.mark.parametrize("field", ["series", "label"])
    def test_missing_series_not_checked(self, field):
        info = make_base_info(**{field: ''})
        need, missing = needs_update(info, has_nfo=True)
        assert field not in missing

    # 7. 既有欄位（title/date/actor/genre/maker）檢查不受影響
    def test_existing_fields_still_checked(self):
        # 舊欄位全缺，新欄位全有
        info = make_base_info(
            title='', date='', actor='', genre='', maker=''
        )
        need, missing = needs_update(info, has_nfo=True)
        assert need is True
        for field in ('title', 'date', 'actor', 'genre', 'maker'):
            assert field in missing
        # 新欄位不應出現在 missing（全有值）
        for field in ('director', 'duration'):
            assert field not in missing


# ============================================================
# update_nfo_file() 測試
# ============================================================

class TestUpdateNfoFileNewFields:
    """update_nfo_file() 補入 / 不覆蓋 director/runtime/set/label"""

    # --- NFO template 工廠 ---

    @staticmethod
    def _minimal_nfo(*, title: str = "テストタイトル",
                      runtime: str = None,
                      director: str = None,
                      set_name: str = None,
                      label: str = None) -> str:
        """產生最小 NFO XML 字串，各新欄位可選。"""
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<movie>',
            f'  <title>{title}</title>',
            '  <num>TEST-001</num>',
        ]
        if runtime is not None:
            lines.append(f'  <runtime>{runtime}</runtime>')
        if director is not None:
            lines.append(f'  <director>{director}</director>')
        if set_name is not None:
            lines.append(f'  <set><name>{set_name}</name></set>')
        if label is not None:
            lines.append(f'  <label>{label}</label>')
        lines.append('</movie>')
        return '\n'.join(lines)

    # 8. 舊 NFO 缺 director/runtime/set/label → 補齊後 XML 含所有新 tag
    def test_fill_all_missing_new_fields(self, tmp_path):
        nfo_xml = self._minimal_nfo()  # 不含任何新欄位
        nfo_path = write_nfo(tmp_path, nfo_xml)
        info = make_base_info(director='', duration=None, series='', label='')
        metadata = {
            'director': '新監督',
            'duration': 120,
            'series': '新シリーズ',
            'label': '新label',
        }
        updated, msg = update_nfo_file(nfo_path, metadata, info)

        assert updated is True
        # 驗證 XML 結構
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        assert root.find('director') is not None
        assert root.find('director').text == '新監督'
        assert root.find('runtime') is not None
        assert root.find('runtime').text == '120'
        assert root.find('set/name') is not None
        assert root.find('set/name').text == '新シリーズ'
        assert root.find('label') is not None
        assert root.find('label').text == '新label'

    # 9. 已有 director 的 NFO + metadata 有 director → 不覆蓋
    @pytest.mark.parametrize(
        ("nfo_kwargs", "info_kwargs", "metadata", "xpath", "expected"),
        [
            ({'director': '既存監督'}, {'director': '既存監督'},
             {'director': '新監督'}, 'director', '既存監督'),
        ],
        ids=['director', ],
    )
    def test_existing_director_not_overwritten(
        self, tmp_path, nfo_kwargs, info_kwargs, metadata, xpath, expected
    ):
        nfo_xml = self._minimal_nfo(**nfo_kwargs)
        nfo_path = write_nfo(tmp_path, nfo_xml)
        info = make_base_info(**info_kwargs)
        updated, msg = update_nfo_file(nfo_path, metadata, info)

        # 不應修改
        root = ET.parse(nfo_path).getroot()
        assert root.find(xpath).text == expected

    # 12. duration=0 → 寫入 <runtime>0</runtime>

    # 14. metadata 無 series → 不建立空 <set>

    # 補充：既有欄位（title/maker）邏輯不受影響

    # 補充：<set> 已存在但缺 <name> → 補入 <name>，不重建 <set>


# ============================================================
# update_nfo_file() — plot / rating / mpaa（63c-5 / CD-63c-10）
# ============================================================

class TestUpdateNfoFilePlotRatingMpaa:
    """update_nfo_file() 補入 / 不覆蓋 <plot>/<rating>/<mpaa>（63c-5 US7 parity）"""

    @staticmethod
    def _nfo(*, plot: str = None, rating: str = None, mpaa: str = None,
              premiered: str = None) -> str:
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<movie>',
            '  <title>テスト</title>',
            '  <num>TEST-001</num>',
        ]
        if premiered is not None:
            lines.append(f'  <premiered>{premiered}</premiered>')
        if plot is not None:
            lines.append(f'  <plot>{plot}</plot>')
        if rating is not None:
            lines.append(f'  <rating>{rating}</rating>')
        if mpaa is not None:
            lines.append(f'  <mpaa>{mpaa}</mpaa>')
        lines.append('</movie>')
        return '\n'.join(lines)

    # ── P2-1: fill all three when missing ──


    # ── P2-2: rating × 2, format ──

    def test_rating_doubled_and_formatted(self, tmp_path):
        """rating × 2，格式為 X.X（一位小數）"""
        nfo_path = write_nfo(tmp_path, self._nfo())
        info = make_base_info()
        metadata = {'_summary': 'x', '_rating': 3.75}

        update_nfo_file(nfo_path, metadata, info)

        root = ET.parse(nfo_path).getroot()
        assert root.find('rating').text == '7.5'

    # ── P2-3: do not overwrite existing plot ──


    # ── P2-4: do not overwrite existing rating ──

    # ── P2-5: do not overwrite existing mpaa ──

    # ── P2-6: mpaa filled even without _summary/_rating (builtin path) ──


    # ── P2-7: zero rating is not written ──


    # ── P2-8: injection prevention via ET escaping ──


# ============================================================
# add_actor() 測試（TASK-73c-T1）
# ============================================================

class TestAddActor:
    """add_actor() — 演員新增與去重"""


    def test_add_duplicate_actor_returns_false_and_count_unchanged(self):
        """root 已有同名 actor → return False，<actor> 數量不變。"""
        root = ET.fromstring("<movie><actor><name>女優A</name></actor></movie>")
        result = add_actor(root, "女優A")
        assert result is False
        assert len(root.findall('.//actor')) == 1


# ============================================================
# add_tags_and_genres() 測試（TASK-73c-T1）
# ============================================================

class TestAddTagsAndGenres:
    """add_tags_and_genres() — tag/genre 獨立去重"""


    def test_existing_tag_not_duplicated_count_zero(self):
        """root 已有 <tag>東方</tag> 再加「東方」→ count == 0，<tag>東方</tag> 僅 1 個。"""
        root = ET.fromstring("<movie><tag>東方</tag><genre>東方</genre></movie>")
        count = add_tags_and_genres(root, ["東方"])
        assert count == 0
        assert len(root.findall('tag')) == 1


# ============================================================
# update_nfo_user_tags() 測試（TASK-73c-T1）
# ============================================================

class TestUpdateNfoUserTags:
    """update_nfo_user_tags() — user_tag 清空再寫入"""

    def test_replace_existing_user_tags_with_new_list(self, tmp_path):
        """含 2 個 <user_tag> 的 NFO + ["new1","new2","new3"] → return True，讀回 <user_tag> 恰 3 個。"""
        nfo = tmp_path / "test.nfo"
        nfo.write_text(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<movie><title>test</title>'
            '<user_tag>old1</user_tag>'
            '<user_tag>old2</user_tag>'
            '</movie>',
            encoding="utf-8",
        )
        result = update_nfo_user_tags(str(nfo), ["new1", "new2", "new3"])
        assert result is True
        root = ET.parse(str(nfo)).getroot()
        user_tags = root.findall('user_tag')
        assert len(user_tags) == 3
        texts = [e.text for e in user_tags]
        assert "new1" in texts
        assert "new2" in texts
        assert "new3" in texts

    def test_empty_list_clears_all_user_tags(self, tmp_path):
        """傳 [] → 所有 <user_tag> 被清除。"""
        nfo = tmp_path / "test.nfo"
        nfo.write_text(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<movie><user_tag>a</user_tag><user_tag>b</user_tag></movie>',
            encoding="utf-8",
        )
        result = update_nfo_user_tags(str(nfo), [])
        assert result is True
        root = ET.parse(str(nfo)).getroot()
        assert len(root.findall('user_tag')) == 0


# ============================================================
# update_nfo_file() 補欄分支測試（TASK-73c-T1）
# ============================================================

class TestUpdateNfoFileFillBranches:
    """update_nfo_file() date / actor 補欄 fill-only-if-missing 分支"""

    @staticmethod
    def _write_nfo(tmp_path: Path, xml_content: str, filename: str = "movie.nfo") -> str:
        nfo = tmp_path / filename
        nfo.write_text(xml_content, encoding="utf-8")
        return str(nfo)


    def test_existing_actor_in_info_no_new_actor_added(self, tmp_path):
        """NFO 已有 <actor><name>女優A</name></actor>，info={'actor':[{'name':'女優A'}]} → 無新 actor 加入。"""
        nfo_path = self._write_nfo(
            tmp_path,
            '<?xml version="1.0" encoding="utf-8"?>'
            '<movie><title>テスト</title><num>TEST-001</num>'
            '<actor><name>女優A</name></actor></movie>',
        )
        # info['actor'] is truthy → the fill branch is skipped entirely
        info = {"actor": [{"name": "女優A"}]}
        metadata = {"actors": ["女優A", "女優B"]}
        update_nfo_file(nfo_path, metadata, info)

        root = ET.parse(nfo_path).getroot()
        names = [e.text for e in root.findall('.//actor/name')]
        # Only the original actor should be present — the fill branch was skipped
        assert names == ["女優A"]


# ============================================================
# TASK-91-T4: get_nfo_path_from_video path_mappings 反解測試
# ============================================================

class TestGetNfoPathPathMappingReverse:
    """get_nfo_path_from_video 改用 uri_to_local_fs_path 後的行為驗證。

    場景 C：WSL + UNC path_mappings 下，NFO 存在性判斷需拿到真正可 exists() 的
    本機路徑，而非裸 uri_to_fs_path 產生的非法 WSL 路徑（恆 False）。
    """

    def test_wsl_mapping_hit(self, tmp_path, monkeypatch):
        """WSL + mapping 命中：video_path 經反解對應到真實存在的 NFO。"""
        nas_dir = tmp_path / "nas"
        nas_dir.mkdir()
        nfo_file = nas_dir / "movie.nfo"
        nfo_file.write_text("<movie></movie>", encoding="utf-8")

        mappings = {str(nas_dir): "//NAS/share"}
        video_path = "file://///NAS/share/movie.mp4"

        monkeypatch.setattr(path_utils, "CURRENT_ENV", "wsl")

        result = get_nfo_path_from_video(video_path, mappings)
        assert result == str(nfo_file)

        # 裸呼叫（無 mapping）在同一 WSL 環境下應回 None：
        # 證明是 mapping 讓它解得到，而非其他因素（mutation-sensitive）
        result_no_mapping = get_nfo_path_from_video(video_path)
        assert result_no_mapping is None


# ============================================================
# check_cache_needs_update() 測試
# ============================================================

class TestCheckCacheNeedsUpdateItems:
    """check_cache_needs_update() 對 items 清單與欄位完整度的判斷"""

    def test_check_cache_needs_update_items_include_path_number_missing(self):
        """只缺 director 時 missing 含 director，items 包含 path/number/missing 且不影響既有計數"""
        cache = {
            'file:///movies/TEST-001.mp4': {
                'nfo_mtime': 1234567890.0,
                'info': make_base_info(num='TEST-001', director=''),
            }
        }
        stats = check_cache_needs_update(cache)
        assert stats['need_update'] == 1
        assert stats['no_title'] == 0
        assert stats['no_date'] == 0
        assert stats['no_actor'] == 0
        assert stats['no_genre'] == 0
        assert stats['no_maker'] == 0
        assert len(stats['items']) == 1
        item = stats['items'][0]
        assert item['path'] == 'file:///movies/TEST-001.mp4'
        assert item['number'] == 'TEST-001'
        assert item['missing'] == ['director']



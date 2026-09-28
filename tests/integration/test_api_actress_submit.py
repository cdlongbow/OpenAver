"""AI 女優審稿提交端點：驗證、身分與部分更新的 DB round-trip。"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from urllib.parse import quote

from core.database import Actress, ActressRepository, AliasRepository, Video, VideoRepository, init_db
from core.organizer import sanitize_filename
from core.path_utils import to_file_uri


NAME = "三上悠亜"
URL = f"/api/actresses/{NAME}"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "actress_submit.db"
    init_db(path)
    monkeypatch.setattr("core.database.connection.get_db_path", lambda: path)
    return path


@pytest.fixture
def client(db_path):
    from web.app import app

    return TestClient(app)


def test_submit_actress_create_full_fields_and_get_round_trip(client, db_path):
    fields = {
        "name_en": "Yua Mikami", "birth": "1993-08-16", "height": "158cm",
        "cup": "E", "bust": 88, "waist": 58, "hip": 85,
        "hometown": "東京都", "hobby": "遊戲", "agency": "事務所",
        "debut_work": "作品", "tags": ["美少女", "演員"],
        "nickname": "暱稱", "blog_url": "https://example.com/blog",
        "official_url": "https://example.com",
    }
    response = client.post(URL, json=fields)

    assert response.status_code == 200
    assert set(response.json()) == {"success", "actress"}
    assert response.json()["success"] is True
    stored = ActressRepository(db_path).get_by_name(NAME)
    assert stored is not None
    for key, value in fields.items():
        assert getattr(stored, key) == value
        assert client.get(URL).json()["actress"][key] == value
    assert stored.primary_text_source == "ai"


def test_submit_actress_update_one_field_preserves_others(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, name_en="Original", hometown="大阪", tags=["原有"],
                      photo_source="wiki", auto_focal="0.3000,0.4000", crop_mode="manual"))

    response = client.post(URL, json={"name_en": "Updated"})

    assert response.status_code == 200
    stored = repo.get_by_name(NAME)
    assert stored.name_en == "Updated"
    assert stored.hometown == "大阪"
    assert stored.tags == ["原有"]
    assert (stored.photo_source, stored.auto_focal, stored.crop_mode) == (
        "wiki", "0.3000,0.4000", "manual")
    assert stored.primary_text_source == "ai"


def test_submit_actress_trailing_space_updates_existing_identity(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, name_en="Original"))

    response = client.post(f"{URL}%20", json={"name_en": "Updated"})

    assert response.status_code == 200
    assert response.json()["actress"]["name"] == NAME
    assert repo.get_by_name(NAME).name_en == "Updated"
    assert [actress.name for actress in repo.get_all()] == [NAME]


def test_submit_actress_tags_replace_then_clear(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, tags=["原有", "保留"]))

    assert client.post(URL, json={"tags": ["原有", "保留", "新增"]}).status_code == 200
    assert repo.get_by_name(NAME).tags == ["原有", "保留", "新增"]
    assert client.post(URL, json={"tags": []}).status_code == 200
    assert repo.get_by_name(NAME).tags == []


def test_submit_actress_explicit_empty_values_clear_fields(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, birth="1993-08-16", bust=88, tags=["原有"]))

    response = client.post(URL, json={"birth": "", "bust": None, "tags": []})

    assert response.status_code == 200
    stored = repo.get_by_name(NAME)
    assert (stored.birth, stored.bust, stored.tags) == ("", None, [])


@pytest.mark.parametrize("field", [
    "photo_source", "primary_text_source", "auto_focal", "crop_mode",
    "photo_fp_path", "photo_fp_mtime_ns", "photo_fp_size", "aliases",
    "name", "created_at", "updated_at",
])
def test_submit_actress_blacklist_field_rejected_400(client, db_path, field):
    response = client.post(URL, json={"name_en": "should not save", field: "forbidden"})

    assert response.status_code == 400
    assert field in response.json()["detail"]
    assert "保留欄位" in response.json()["detail"]
    assert ActressRepository(db_path).get_by_name(NAME) is None


def test_submit_actress_unknown_field_rejected_400(client, db_path):
    response = client.post(URL, json={"name_en": "should not save", "unknown": 1})

    assert response.status_code == 400
    assert "包含未知欄位: unknown" in response.json()["detail"]
    assert ActressRepository(db_path).get_by_name(NAME) is None


@pytest.mark.parametrize("field,value", [
    ("birth", "2024-13-40"), ("birth", "2024-1-01"),
    ("height", "99cm"), ("height", "221"), ("height", "tall"),
    # TASK-157-F4: 舊版 \d+ 正則不限位數，4301+ 位數字字串會讓 int() 撞上
    # Python 3.11+ 的 int-string 轉換位數上限，丟出未接住的 ValueError → 500，
    # 而不是預期中的 400。\d{1,3} 邊界應該在正則本身就擋下，不必等 int() 出錯。
    ("height", "9" * 5000),
    ("bust", 49), ("waist", "121cm"), ("hip", 151),
    ("cup", "AA"), ("cup", "a"), ("tags", ["ok", 3]),
    ("name_en", 42),
])
def test_submit_actress_invalid_field_rejects_whole_request(client, db_path, field, value):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, name_en="Before"))

    response = client.post(URL, json={"name_en": "After", field: value})

    assert response.status_code == 400
    assert repo.get_by_name(NAME).name_en == "Before"


@pytest.mark.parametrize("height,bust,waist,hip", [
    (158, 88, "58cm", "85cm"), ("159", "89cm", 59, 86),
    ("160cm", 90, 60, 87),
])
def test_submit_actress_measurements_normalize(client, db_path, height, bust, waist, hip):
    response = client.post(URL, json={
        "height": height, "bust": bust, "waist": waist, "hip": hip,
    })

    assert response.status_code == 200
    stored = ActressRepository(db_path).get_by_name(NAME)
    assert stored.height == f"{int(str(height).removesuffix('cm'))}cm"
    assert (stored.bust, stored.waist, stored.hip) == (
        int(str(bust).removesuffix("cm")), int(str(waist).removesuffix("cm")),
        int(str(hip).removesuffix("cm")))


def test_submit_actress_alias_identity_name_rejected_with_correct_name(client, db_path):
    primary, alias = "三上悠亜", "鬼頭桃菜"
    repo = ActressRepository(db_path)
    repo.save(Actress(name=primary, name_en="Before"))
    AliasRepository(db_path).sync_from_favorite(primary, [alias])

    response = client.post(f"/api/actresses/{alias}", json={"name_en": "Wrong"})

    assert response.status_code == 400
    assert primary in response.json()["detail"]
    assert repo.get_by_name(alias) is None
    assert repo.get_by_name(primary).name_en == "Before"


def test_submit_actress_orphan_alias_group_creates_new_actress(client, db_path):
    alias = "孤兒別名"
    AliasRepository(db_path).sync_from_favorite("未收藏本名", [alias])

    response = client.post(f"/api/actresses/{alias}", json={"nickname": "新人"})

    assert response.status_code == 200
    assert ActressRepository(db_path).get_by_name(alias).nickname == "新人"


def test_submit_actress_empty_update_still_marks_ai(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, primary_text_source="wiki"))

    response = client.post(URL, json={})

    assert response.status_code == 200
    assert repo.get_by_name(NAME).primary_text_source == "ai"


def test_submit_actress_photo_null_does_not_change_photo(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, photo_source="wiki", auto_focal="0.2000,0.3000"))

    response = client.post(URL, json={"photo": None, "nickname": "保留照片"})

    assert response.status_code == 200
    stored = repo.get_by_name(NAME)
    assert (stored.photo_source, stored.auto_focal) == ("wiki", "0.2000,0.3000")


def test_submit_actress_existing_photo_subroute_still_reachable(client):
    response = client.post(f"{URL}/photo", json={"source": "unknown"})

    assert response.status_code == 404
    assert response.json().get("error") == "not_found"


def test_submit_actress_text_and_photo_together_both_persist_invariant_a(client, db_path, tmp_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, height="155cm", photo_source="wiki",
                      auto_focal="0.2000,0.3000", crop_mode="manual"))
    photos = tmp_path / "photos"
    photos.mkdir()

    def download(name, url, source):
        (photos / f"{sanitize_filename(name)}.jpg").write_bytes(b"new photo")
        return True

    with patch("web.routers.actress.download_actress_photo", side_effect=download), \
         patch("core.actress_photo.GFRIENDS_DIR", photos):
        response = client.post(URL, json={"height": "160cm", "photo": {
            "source": "graphis", "url": "https://www.graphis.ne.jp/new.jpg"}})

    assert response.status_code == 200
    stored = repo.get_by_name(NAME)
    assert (stored.height, stored.photo_source) == ("160cm", "graphis")
    assert (stored.auto_focal, stored.crop_mode) == ("", "auto")
    assert response.json()["actress"]["photo_url"] == f"/api/actresses/photo/{quote(NAME)}"


def test_submit_actress_create_with_photo_saves_row_before_photo(client, db_path, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()

    def download(name, url, source):
        assert ActressRepository(db_path).exists(name)
        (photos / f"{sanitize_filename(name)}.jpg").write_bytes(b"new photo")
        return True

    with patch("web.routers.actress.download_actress_photo", side_effect=download), \
         patch("core.actress_photo.GFRIENDS_DIR", photos):
        response = client.post(URL, json={"nickname": "新人", "photo": {
            "source": "graphis", "url": "https://www.graphis.ne.jp/new.jpg"}})

    assert response.status_code == 200
    stored = ActressRepository(db_path).get_by_name(NAME)
    assert (stored.nickname, stored.photo_source) == ("新人", "graphis")
    assert response.json()["actress"]["photo_url"] == f"/api/actresses/photo/{quote(NAME)}"


@pytest.mark.parametrize("photo", [None])
def test_submit_actress_null_photo_skips_photo_helpers(client, db_path, photo):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, photo_source="wiki", auto_focal="0.2000,0.3000",
                      crop_mode="manual"))
    with patch("web.routers.actress.validate_photo_url") as validate, \
         patch("web.routers.actress._pre_invalidate_focal") as clear, \
         patch("web.routers.actress.download_actress_photo") as download:
        assert client.post(URL, json={"nickname": "保留", "photo": photo}).status_code == 200
        assert client.post(URL, json={"nickname": "再次保留"}).status_code == 200
        validate.assert_not_called()
        clear.assert_not_called()
        download.assert_not_called()
    stored = repo.get_by_name(NAME)
    assert (stored.photo_source, stored.auto_focal, stored.crop_mode) == (
        "wiki", "0.2000,0.3000", "manual")


@pytest.mark.parametrize("photo", [
    {"source": "invalid", "url": "https://www.graphis.ne.jp/a.jpg"},
    {"source": "graphis", "url": "https://evil.example.com/a.jpg"},
    {"source": "graphis"},
    {"source": "local_crop"},
])
def test_submit_actress_invalid_photo_rejects_before_any_write(client, db_path, photo):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, height="155cm", photo_source="wiki",
                      auto_focal="0.2000,0.3000", crop_mode="manual"))
    with patch("web.routers.actress._pre_invalidate_focal") as clear, \
         patch.object(ActressRepository, "update_fields", autospec=True) as update, \
         patch.object(ActressRepository, "save", autospec=True) as save:
        response = client.post(URL, json={"height": "160cm", "photo": photo})
        clear.assert_not_called()
        update.assert_not_called()
        save.assert_not_called()
    assert response.status_code == 400
    stored = repo.get_by_name(NAME)
    assert (stored.height, stored.photo_source, stored.auto_focal) == (
        "155cm", "wiki", "0.2000,0.3000")


def test_submit_actress_download_failure_rolls_back_update_invariant_b(client, db_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, height="155cm", nickname="原名", photo_source="wiki"))
    with patch("web.routers.actress.download_actress_photo", return_value=False):
        response = client.post(URL, json={"height": "160cm", "nickname": "新名", "photo": {
            "source": "graphis", "url": "https://www.graphis.ne.jp/new.jpg"}})
    assert response.status_code == 500
    stored = ActressRepository(db_path).get_by_name(NAME)
    assert (stored.height, stored.nickname, stored.photo_source) == ("155cm", "原名", "wiki")


def test_submit_actress_download_failure_removes_created_row_invariant_b(client, db_path, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    with patch("web.routers.actress.download_actress_photo", return_value=False), \
         patch("core.actress_photo.GFRIENDS_DIR", photos):
        response = client.post(URL, json={"nickname": "新名", "photo": {
            "source": "graphis", "url": "https://www.graphis.ne.jp/new.jpg"}})
    assert response.status_code == 500
    assert ActressRepository(db_path).exists(NAME) is False
    assert list(photos.iterdir()) == []


def test_submit_actress_local_crop_write_failure_rolls_back_update(client, db_path, tmp_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, height="155cm", photo_source="wiki"))
    video_path = tmp_path / "video.mp4"
    cover_path = tmp_path / "cover.jpg"
    VideoRepository(db_path).upsert(Video(path=to_file_uri(str(video_path)), title="測試",
                                         actresses=[NAME], cover_path=to_file_uri(str(cover_path))))
    with patch("web.routers.actress.crop_video_cover", return_value=b"crop"), \
         patch("web.routers.actress._write_actress_photo", side_effect=OSError("disk full")):
        response = client.post(URL, json={"height": "160cm", "photo": {
            "source": "local_crop", "video_path": to_file_uri(str(video_path))}})
    assert response.status_code == 500
    stored = repo.get_by_name(NAME)
    assert (stored.height, stored.photo_source) == ("155cm", "wiki")


def test_submit_actress_local_crop_updates_photo_and_focal(client, db_path, tmp_path):
    repo = ActressRepository(db_path)
    repo.save(Actress(name=NAME, photo_source="wiki"))
    assert repo.update_manual_focal(NAME, "0.2000,0.3000")
    video_path = tmp_path / "video.mp4"
    cover_path = tmp_path / "cover.jpg"
    VideoRepository(db_path).upsert(Video(path=to_file_uri(str(video_path)), title="測試",
                                         actresses=[NAME], cover_path=to_file_uri(str(cover_path))))
    photos = tmp_path / "photos"
    photos.mkdir()
    with patch("web.routers.actress.crop_video_cover", return_value=b"new crop"), \
         patch("web.routers.actress.GFRIENDS_DIR", photos), \
         patch("core.actress_photo.GFRIENDS_DIR", photos):
        response = client.post(URL, json={"photo": {
            "source": "local_crop", "video_path": to_file_uri(str(video_path))}})
    assert response.status_code == 200
    stored = repo.get_by_name(NAME)
    assert (stored.photo_source, stored.auto_focal, stored.crop_mode) == ("local_crop", "", "auto")
    assert (photos / f"{sanitize_filename(NAME)}.jpg").read_bytes() == b"new crop"


def test_submit_actress_photo_persist_failure_keeps_created_row_and_text(client, db_path, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    original_save = ActressRepository.save
    saves = 0

    def save_then_fail(repo, actress):
        nonlocal saves
        saves += 1
        if saves == 2:
            raise OSError("sqlite write failed")
        return original_save(repo, actress)

    def download(name, url, source):
        (photos / f"{sanitize_filename(name)}.jpg").write_bytes(b"new photo")
        return True

    with patch.object(ActressRepository, "save", autospec=True, side_effect=save_then_fail), \
         patch("web.routers.actress.download_actress_photo", side_effect=download), \
         patch("core.actress_photo.GFRIENDS_DIR", photos):
        response = client.post(URL, json={"nickname": "新名", "photo": {
            "source": "graphis", "url": "https://www.graphis.ne.jp/new.jpg"}})
    assert response.status_code == 500
    assert saves == 2
    stored = ActressRepository(db_path).get_by_name(NAME)
    assert (stored.nickname, stored.primary_text_source) == ("新名", "ai")
    assert (photos / f"{sanitize_filename(NAME)}.jpg").read_bytes() == b"new photo"

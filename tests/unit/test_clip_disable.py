"""
tests/unit/test_clip_disable.py
57b: clear_all_clip_embeddings / update_clip_embedding / get_videos_pending_clip_indexing
     均已改為 stub（57d 連帶刪）— 驗 NotImplementedError 正確拋出。
"""
import pytest


class TestClearAllClipEmbeddings:
    def test_stub_raises_not_implemented(self, tmp_path):
        """clear_all_clip_embeddings 已改為 stub — 呼叫時拋 NotImplementedError"""
        from core.database import VideoRepository, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        with pytest.raises(NotImplementedError):
            repo.clear_all_clip_embeddings()


class TestUpdateClipEmbedding:
    def test_stub_raises_not_implemented(self, tmp_path):
        """update_clip_embedding 已改為 stub — 呼叫時拋 NotImplementedError"""
        from core.database import VideoRepository, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        with pytest.raises(NotImplementedError):
            repo.update_clip_embedding(1, b"\x00\x01", "model-id")


class TestGetVideosPendingClipIndexing:
    def test_stub_raises_not_implemented(self, tmp_path):
        """get_videos_pending_clip_indexing 已改為 stub — 呼叫時拋 NotImplementedError"""
        from core.database import VideoRepository, init_db

        db_path = tmp_path / "test.db"
        init_db(db_path)
        repo = VideoRepository(db_path)
        with pytest.raises(NotImplementedError):
            repo.get_videos_pending_clip_indexing("model-id")

"""test_video_extensions.py - core/video_extensions.py unit tests"""


class TestNormalizeExtensions:
    """normalize_extensions() tests"""

    def test_lowercase(self):
        """uppercase extensions are lowercased"""
        from core.video_extensions import normalize_extensions
        result = normalize_extensions(['.MP4', '.AVI'])
        assert '.mp4' in result
        assert '.avi' in result

    def test_add_dot_prefix(self):
        """extensions without leading dot get one added"""
        from core.video_extensions import normalize_extensions
        result = normalize_extensions(['mp4', 'avi'])
        assert '.mp4' in result
        assert '.avi' in result


class TestGetVideoExtensions:
    """get_video_extensions(config) tests"""

    def test_reads_from_config(self):
        """reads extensions from config scraper.video_extensions"""
        from core.video_extensions import get_video_extensions
        config = {'scraper': {'video_extensions': ['.mp4', '.avi']}}
        result = get_video_extensions(config)
        assert '.mp4' in result
        assert '.avi' in result

    def test_fallback_when_empty(self):
        """falls back to DEFAULT when video_extensions is empty list"""
        from core.video_extensions import get_video_extensions, DEFAULT_VIDEO_EXTENSIONS
        config = {'scraper': {'video_extensions': []}}
        result = get_video_extensions(config)
        assert result == set(DEFAULT_VIDEO_EXTENSIONS)


class TestGetProxyExtensions:
    """get_proxy_extensions(config) tests"""

    def test_intersection_with_safe(self):
        """result is intersection of config extensions and SAFE_PROXY_EXTENSIONS"""
        from core.video_extensions import get_proxy_extensions
        config = {'scraper': {'video_extensions': ['.mp4', '.avi', '.exe']}}
        result = get_proxy_extensions(config)
        assert '.mp4' in result
        assert '.avi' in result
        assert '.exe' not in result


    def test_strm_not_in_proxy(self):
        """.strm is NOT in proxy extensions (it's a text file, not a video stream)"""
        from core.video_extensions import get_proxy_extensions, DEFAULT_VIDEO_EXTENSIONS
        config = {'scraper': {'video_extensions': list(DEFAULT_VIDEO_EXTENSIONS)}}
        result = get_proxy_extensions(config)
        assert '.strm' not in result



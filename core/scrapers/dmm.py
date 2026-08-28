"""DMM 爬蟲（官方 GraphQL API）"""
import json
import os
import re
import requests
from pathlib import Path
from typing import Optional

from core.logger import get_logger

logger = get_logger(__name__)
from .base import BaseScraper
from .models import Video, Actress, ScraperConfig
from .utils import rate_limit


# 快取檔案路徑（專案根目錄）
PROJECT_ROOT = Path(__file__).parent.parent.parent
CACHE_FILE = PROJECT_ROOT / "dmm_content_ids.json"      # 完整番號 → content_id
PREFIX_FILE = PROJECT_ROOT / "dmm_prefix_hints.json"    # 番號前綴 → DMM 前綴
SHIPPED_TABLE_FILE = PROJECT_ROOT / "dmm_prefix_table.json"  # 出貨前綴表（依片商分組）

# module-level capability cache（三態）
# None = 未知（首次或暫時性失敗），True = schema 支援，False = schema 不支援
_genres_supported: Optional[bool] = None
_sample_images_supported: Optional[bool] = None
_review_supported: Optional[bool] = None

# 出貨表／本機自學檔快取（None = 尚未讀）
_shipped_table_cache: Optional[dict] = None
_local_hints_cache: Optional[dict] = None
_local_hints_cache_mtime: Optional[float] = None


def _flatten_shipped_table(raw: dict) -> dict[str, dict]:
    """展平出貨表 makers → {prefix: entry}；跨片商撞名時 raise。"""
    flat: dict[str, dict] = {}
    for maker, prefixes in raw.get("makers", {}).items():
        for prefix, entry in prefixes.items():
            if prefix in flat:
                raise ValueError(
                    f"dmm_prefix_table.json 撞名：前綴 '{prefix}' 同時出現在片商 "
                    f"'{flat[prefix]['_maker']}' 與 '{maker}' 底下"
                )
            flat[prefix] = {**entry, "_maker": maker}
    return flat


class DMMScraper(BaseScraper):
    """
    DMM 爬蟲（使用官方 GraphQL API）

    優點：
    - 官方資料來源，資料最準確
    - 封面無浮水印、高畫質
    - 有完整簡介、導演資訊

    特點：
    - 雙層快取：前綴映射 + content_id 快取
    - 無需預設映射表

    注意：
    - 需要日本 IP（VPN）
    - API 可能隨時變動（非公開 API）
    """

    API_URL = "https://api.video.dmm.co.jp/graphql"

    DETAIL_QUERY = """
        query ContentPageData($id: ID!) {
            ppvContent(id: $id) {
                id
                title
                description
                packageImage { largeUrl }
                makerReleasedAt
                duration
                actresses { name }
                directors { name }
                series { name }
                maker { name }
                makerContentId
            }
        }
    """

    SEARCH_QUERY = """
        query AvSearch($limit: Int!, $sort: ContentSearchPPVSort!, $queryWord: String) {
            legacySearchPPV(limit: $limit, sort: $sort, queryWord: $queryWord) {
                result { contents { id } }
            }
        }
    """

    SEARCH_LIST_QUERY = """
        query AvSearch($limit: Int!, $offset: Int!, $sort: ContentSearchPPVSort!, $queryWord: String) {
            legacySearchPPV(limit: $limit, offset: $offset, sort: $sort, queryWord: $queryWord) {
                result {
                    contents {
                        id
                        title
                        packageImage { largeUrl }
                        actresses { name }
                        maker { name }
                    }
                }
            }
        }
    """

    # 獨立 probe query — 與 DETAIL_QUERY 分離，失敗不影響主流程
    GENRES_PROBE_QUERY = """
        query ProbeGenres($id: ID!) {
            ppvContent(id: $id) {
                genres { name }
                label { name }
            }
        }
    """

    SAMPLE_IMAGES_PROBE_QUERY = """
        query ProbeSampleImages($id: ID!) {
            ppvContent(id: $id) {
                sampleImages { imageUrl }
            }
        }
    """

    # 評分 probe — root field reviewSummary（arg 名 contentId，非 id）
    REVIEW_PROBE_QUERY = """
        query ProbeReview($contentId: ID!) {
            reviewSummary(contentId: $contentId) { average }
        }
    """

    # GraphQL schema error patterns — 不同實作回傳的訊息格式不同
    SCHEMA_ERROR_PATTERNS = ('Unknown field', 'Cannot query field')

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': self.config.user_agent,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        if self.config.proxy_url:
            self._session.proxies = {
                'http': self.config.proxy_url,
                'https': self.config.proxy_url,
            }
        else:
            # direct 模式：明確不走任何 proxy（包括環境變數）
            self._session.trust_env = False

    def _get_source_name(self) -> str:
        return "dmm"

    def _probe_genres(self, content_id: str) -> tuple[list[str], str]:
        """
        探測 ppvContent 是否支援 genres/label 欄位。

        三態 cache 控制：
        - _genres_supported is False → 立即回傳空（永久跳過）
        - _genres_supported is True  → 仍查詢（該片可能有 tags）
        - _genres_supported is None  → 首次查詢，依結果更新 cache

        Returns:
            (tags, label) — 探測失敗時回傳 ([], '')
        """
        global _genres_supported

        # 已確認 schema 不支援 → 永久跳過
        if _genres_supported is False:
            return [], ''

        try:
            payload = {
                'query': self.GENRES_PROBE_QUERY,
                'variables': {'id': content_id}
            }
            resp = self._session.post(self.API_URL, json=payload, timeout=5)

            if resp.status_code != 200:
                # HTTP 錯誤 → 暫時性失敗，維持 None
                return [], ''

            resp_json = resp.json()
            errors = resp_json.get('errors', [])

            # 判定 1：schema error（unknown field / validation error）→ 確認不支援
            if any(
                any(pat in (e.get('message', '') or '') for pat in self.SCHEMA_ERROR_PATTERNS)
                for e in errors
            ):
                _genres_supported = False
                logger.info("[DMM] GraphQL schema 不支援 genres，已永久停用 probe")
                return [], ''

            # 判定 2：GraphQL 錯誤但非 schema error → 暫時性，維持 None
            data = resp_json.get('data') or {}
            item = data.get('ppvContent')

            if item is None:
                # content_id 不存在或其他 null，無法判定 → 維持 None
                return [], ''

            # 判定 3：正常回應 → schema 支援（即使此片 tags 為空）
            _genres_supported = True
            genres = item.get('genres') or []
            tags = [g['name'] for g in genres if g.get('name')]
            label = (item.get('label') or {}).get('name', '')
            return tags, label

        except Exception:
            # 網路錯誤、timeout → 暫時性失敗，維持 None（不設 False）
            return [], ''

    def _probe_sample_images(self, content_id: str) -> list[str]:
        """
        探測 ppvContent 是否支援 sampleImages 欄位。

        獨立於 genres/label probe，避免互相干擾。
        三態 cache 控制同 _probe_genres()。
        """
        global _sample_images_supported

        if _sample_images_supported is False:
            return []

        try:
            payload = {
                'query': self.SAMPLE_IMAGES_PROBE_QUERY,
                'variables': {'id': content_id}
            }
            resp = self._session.post(self.API_URL, json=payload, timeout=5)

            if resp.status_code != 200:
                return []

            resp_json = resp.json()
            errors = resp_json.get('errors', [])

            if any(
                any(pat in (e.get('message', '') or '') for pat in self.SCHEMA_ERROR_PATTERNS)
                for e in errors
            ):
                _sample_images_supported = False
                logger.info("[DMM] GraphQL schema 不支援 sampleImages，已永久停用 probe")
                return []

            data = resp_json.get('data') or {}
            item = data.get('ppvContent')

            if item is None:
                return []

            _sample_images_supported = True
            raw_samples = item.get('sampleImages') or []
            return [re.sub(r'(?<!jp)-(\d+)\.jpg$', r'jp-\1.jpg', s['imageUrl']) for s in raw_samples if s.get('imageUrl')]

        except Exception:
            return []

    def _probe_review(self, content_id: str) -> Optional[float]:
        """
        探測 root field reviewSummary 是否被 schema 支援，並取回評分。

        三態 cache 控制同 _probe_genres()，但注意一處差異：
        reviewSummary 為 root field，主 query 已成功代表 content 存在，
        故 reviewSummary is None 代表「此片無評分」→ 判定 True + 回傳 None
        （非「無法判定」）。

        Returns:
            average（0–5）；此片無評分或探測失敗時回傳 None。
        """
        global _review_supported

        # 已確認 schema 不支援 → 永久跳過（不再發 POST）
        if _review_supported is False:
            return None

        try:
            payload = {
                'query': self.REVIEW_PROBE_QUERY,
                'variables': {'contentId': content_id}
            }
            resp = self._session.post(self.API_URL, json=payload, timeout=5)

            if resp.status_code != 200:
                # HTTP 錯誤 → 暫時性失敗，維持 None（不設 False）
                return None

            resp_json = resp.json()
            errors = resp_json.get('errors', [])

            # 判定 1：schema error → 確認不支援，永久停用
            if any(
                any(pat in (e.get('message', '') or '') for pat in self.SCHEMA_ERROR_PATTERNS)
                for e in errors
            ):
                _review_supported = False
                logger.info("[DMM] GraphQL schema 不支援 reviewSummary，已永久停用 probe")
                return None

            # 判定 2：正常回應 → schema 支援
            data = resp_json.get('data') or {}
            summary = data.get('reviewSummary')

            # content 一定存在（主 query 已成功），summary is None 代表此片無評分
            _review_supported = True

            if summary is None:
                return None

            average = summary.get('average')
            if average is None:
                return None
            return float(average)

        except Exception:
            # 網路錯誤、timeout → 暫時性失敗，維持 None（不設 False）
            return None

    def _fetch_tags_from_html(self, content_id: str) -> list[str]:
        """
        從 DMM 商品頁 HTML 抓取 genres（ジャンル）。
        使用同一 session（已設定 proxy），傳 age_check_done=1 cookie 繞過年齡驗證。

        兩種解析策略：
        1. JSON-LD VideoObject.genre（較快）
        2. XPath ジャンル 欄（備援）

        Returns:
            tags list（失敗時回傳 []，不 raise）
        """
        url = f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={content_id}/"
        try:
            resp = self._session.get(
                url,
                timeout=self.config.timeout,
                cookies={"age_check_done": "1"}
            )
            if resp.status_code != 200:
                return []

            from lxml import etree
            import json as _json

            html = etree.fromstring(resp.content, etree.HTMLParser())

            # 方法 1: JSON-LD VideoObject.genre
            for script in html.xpath('//script[@type="application/ld+json"]/text()'):
                try:
                    ld = _json.loads(script)
                    if isinstance(ld, dict) and ld.get('@type') == 'VideoObject':
                        genre = ld.get('genre')
                        if genre and isinstance(genre, list):
                            return [g for g in genre if isinstance(g, str)]
                except _json.JSONDecodeError:
                    continue

            # 方法 2: XPath ジャンル 表格欄
            tags = html.xpath(
                '//th[contains(.//text(),"ジャンル")]/following-sibling::td//a/text()'
            )
            return [t.strip() for t in tags if t.strip()]

        except Exception:
            return []

    # ========== 快取管理 ==========

    def _load_json(self, path: Path) -> dict:
        """讀取 JSON，檔案不存在返回空 dict"""
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_json(self, path: Path, data: dict):
        """儲存 JSON"""
        try:
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
        except IOError:
            pass

    def _load_cache(self) -> dict:
        """讀取 content_id 快取"""
        return self._load_json(CACHE_FILE)

    def _save_cache(self, number: str, content_id: str):
        """儲存到 content_id 快取"""
        cache = self._load_cache()
        cache[number.upper()] = content_id
        self._save_json(CACHE_FILE, cache)

    def _load_prefix_hints(self) -> dict:
        """讀出貨表 + 本機自學檔，本機優先合併（只讀、不寫）。"""
        global _shipped_table_cache, _local_hints_cache, _local_hints_cache_mtime

        # 1. 出貨表：process 內讀一次；缺席／壞 JSON／缺 makers → 空表（D1）
        if _shipped_table_cache is None:
            try:
                if not SHIPPED_TABLE_FILE.exists():
                    logger.warning(
                        "dmm_prefix_table.json 不存在，視為空表繼續"
                    )
                    _shipped_table_cache = {}
                else:
                    raw = json.loads(
                        SHIPPED_TABLE_FILE.read_text(encoding="utf-8")
                    )
                    if "makers" not in raw:
                        logger.warning(
                            "dmm_prefix_table.json 缺少 makers 鍵，視為空表繼續"
                        )
                        _shipped_table_cache = {}
                    else:
                        # 撞名 ValueError 不得在此吞掉（D2）
                        _shipped_table_cache = _flatten_shipped_table(raw)
            except (json.JSONDecodeError, OSError, AttributeError, TypeError) as e:
                # AttributeError/TypeError：JSON 語法合法但形狀不對（makers 是
                # null/list、片商底下不是 dict、entry 不是 mapping…）。這些同樣屬
                # D1「出貨表是加分項不是必要條件」的範圍——出貨表壞掉只該讓它失效，
                # 不該讓整支 DMM 來源在每次搜尋時噴例外（search() 步驟 2 沒有接例外）。
                # ⚠️ 不含 ValueError：撞名必須逃出去（D2），且 JSONDecodeError 是
                # ValueError 的子類、已單獨列在前面，順序不可調換。
                logger.warning(
                    "dmm_prefix_table.json 讀取失敗，視為空表繼續：%s", e
                )
                _shipped_table_cache = {}

        shipped = _shipped_table_cache

        # 2. 本機檔：mtime 未變沿用快取；檔案不存在回 {}（不拋例外）
        #    exists() 與 stat() 之間檔案被刪掉（防毒隔離／使用者手動刪）→ 回 {}，
        #    不讓一次 race 變成一次搜尋失敗。
        local: dict = {}
        try:
            if PREFIX_FILE.exists():
                mtime = os.stat(PREFIX_FILE).st_mtime
                if (
                    _local_hints_cache is not None
                    and _local_hints_cache_mtime == mtime
                ):
                    local = _local_hints_cache
                else:
                    local = self._load_json(PREFIX_FILE)
                    _local_hints_cache = local
                    _local_hints_cache_mtime = mtime
        except OSError as e:
            logger.warning("dmm_prefix_hints.json 讀取失敗，忽略本機值：%s", e)
            local = {}

        # 本機檔是使用者手可及的（手改／外部工具寫入），形狀不保證是 dict。
        # 不是 dict 就整份忽略——同 D1 的理由：它壞掉不該讓搜尋掛掉。
        if not isinstance(local, dict):
            logger.warning(
                "dmm_prefix_hints.json 不是物件（%s），忽略本機值",
                type(local).__name__,
            )
            local = {}

        # 3. 純合併，本機優先；只取 dmm_prefix 字串（sample 不得外洩）
        merged = {p: e.get("dmm_prefix", "") for p, e in shipped.items()}
        merged.update({p: v for p, v in local.items() if not p.startswith("_")})
        return merged

    # ========== content_id 轉換 ==========

    def _parse_number(self, number: str) -> tuple[str, str]:
        """
        解析番號，返回 (前綴, 數字)

        Examples:
            SONE-205 → ("sone", "205")
            STARS-804 → ("stars", "804")
        """
        number = number.upper().strip()
        match = re.match(r'^([A-Z]+)-?(\d+)$', number)
        if match:
            return match.group(1).lower(), match.group(2)
        return "", ""

    def _convert_with_hints(self, number: str) -> str:
        """
        用前綴映射轉換番號

        Examples:
            SONE-205 + hints={} → sone00205
            STARS-804 + hints={"stars": "1"} → 1stars00804
        """
        prefix, num = self._parse_number(number)
        if not prefix or not num:
            return ""

        # 數字補零到 5 位
        num_padded = num.zfill(5)

        # 查前綴映射
        hints = self._load_prefix_hints()
        dmm_prefix = hints.get(prefix, "")

        return f"{dmm_prefix}{prefix}{num_padded}"

    def _content_id_to_number(self, content_id: str) -> str:
        """
        從 content_id 推導標準番號格式。

        DMM content_id 固定 5 位數字零補位（zfill(5)）。
        反向推導時 strip leading zeros 但保留至少 3 位數字。

        Examples:
            sone00205   → SONE-205
            1stars00804 → STARS-804
            ssni00001   → SSNI-001
            ofje00709   → OFJE-709
            abp01234    → ABP-1234
        """
        m = re.match(r'^(\d*)([a-z]+)(\d+)$', content_id.lower())
        if m:
            alpha = m.group(2).upper()
            num = m.group(3)
            # Strip leading zeros but keep at least 3 digits
            stripped = num.lstrip('0') or '0'
            if len(stripped) < 3 and len(num) >= 3:
                stripped = num[-3:]
            return f"{alpha}-{stripped}"
        return content_id

    def _search_content_id(self, number: str) -> Optional[str]:
        """
        用搜索 API 查找正確的 content_id（MDCX 方法）
        """
        query_word = number.upper().replace('-', '')
        prefix, _ = self._parse_number(number)

        if not prefix:
            return None

        try:
            payload = {
                'query': self.SEARCH_QUERY,
                'variables': {
                    'limit': 5,
                    'sort': 'RELEASE_DATE',
                    'queryWord': query_word
                }
            }
            resp = self._session.post(self.API_URL, json=payload, timeout=10)

            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data.get('data') or not data['data'].get('legacySearchPPV'):
                return None

            contents = data['data']['legacySearchPPV']['result']['contents']
            if not contents:
                return None

            # 找系列段精確匹配番號前綴的結果（防誤學：搜 ERK-116 不應命中 gerk116，
            # 搜 ID-xxx 不應命中 midv 系）。結構 {dmm_prefix}{series}{num}，series 段
            # 必須 == prefix；找不到精確匹配 → 返回 None（不盲取第一個，避免誤刮）。
            for content in contents:
                cid = content['id']
                m = re.match(
                    r'^((?:h_\d+)|(?:\d+))?([a-z]+)(\d+)$',
                    cid.lower()
                )
                if m and m.group(2) == prefix:
                    return cid

            # 沒找到精確匹配 → 返回 None（原邏輯 return contents[0]['id'] 會誤刮
            # 子串相近的其他系列，例如 ERK-116 → gerk116）
            return None

        except Exception:
            return None

    def _fetch_by_id(self, content_id: str) -> Optional[Video]:
        """用 content_id 取得影片詳細資訊"""
        if not content_id:
            return None

        try:
            payload = {
                'query': self.DETAIL_QUERY,
                'variables': {'id': content_id}
            }

            response = self._session.post(
                self.API_URL,
                json=payload,
                timeout=self.config.timeout
            )

            if response.status_code != 200:
                return None

            data = response.json()

            if not data.get('data') or not data['data'].get('ppvContent'):
                return None

            item = data['data']['ppvContent']

            actresses = [
                Actress(name=a['name'])
                for a in item.get('actresses', [])
            ]

            release_date = item.get('makerReleasedAt') or ''
            if release_date and 'T' in release_date:
                release_date = release_date.split('T')[0]

            # T5a: GraphQL probe → T5b: HTML fallback
            tags, label = self._probe_genres(content_id)
            if not tags:
                tags = self._fetch_tags_from_html(content_id)

            sample_images = self._probe_sample_images(content_id)

            rating = self._probe_review(content_id)

            # 新欄位提取
            directors_list = item.get('directors') or []
            director = directors_list[0]['name'] if directors_list else ''

            raw_duration = item.get('duration')
            duration = raw_duration // 60 if raw_duration is not None else None

            series = (item.get('series') or {}).get('name', '')

            # null 防護：amateur 等內容的 largeUrl/makerReleasedAt 可能為 null，
            # 直接傳 None 給 pydantic str 欄位會 ValidationError（被 except 吞掉→整片失敗）。
            # 統一 or '' 歸一為空串；title 不加防護（內容標識保險絲，為空寧可失敗）。
            cover_url = (item.get('packageImage') or {}).get('largeUrl') or ''
            # amateur 封面兜底：老式無前綴 cid（如 erk116）無 largeUrl，
            # 但 DMM 封面有規律 {cid}jp.jpg（digital/amateur 目錄，1458×1458 方形）。
            # 帶前綴新 cid（hpet/hoip/herk 等）走 digital/video 目錄、largeUrl 有值，不觸發。
            if not cover_url and re.match(r'^[a-z]+\d+$', content_id):
                cover_url = (f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/amateur/"
                             f"{content_id}/{content_id}jp.jpg")

            video = Video(
                number=item.get('makerContentId', ''),
                title=item.get('title', ''),
                actresses=actresses,
                date=release_date,
                maker=item.get('maker', {}).get('name', ''),
                cover_url=cover_url,
                tags=tags,
                source=self.source_name,
                detail_url=f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={content_id}/",
                director=director,
                duration=duration,
                label=label,
                series=series,
                sample_images=sample_images,
                summary=item.get('description') or '',
                rating=rating,
            )

            return video

        except requests.Timeout as e:
            raise TimeoutError(f"DMM API timeout for {content_id}") from e
        except Exception:
            return None

    # ========== 主要搜尋方法 ==========

    def search(self, number: str) -> Optional[Video]:
        """
        搜尋影片資訊

        流程：
        1. 查快取 → 有就直接用（最快）
        2. 用前綴映射轉換 → 嘗試查詢（快）
        3. 搜索 API 發現 → 寫入快取（慢，但只需一次）
        4. 都失敗 → 返回 None

        Args:
            number: 番號（如 SONE-205）

        Returns:
            Video 物件，找不到返回 None
        """
        # 正規化番號（保留原始輸入，供第 4 步 cid 直拉兜底使用）
        raw_input = number.strip()
        number = self.normalize_number(number)
        number_upper = number.upper()

        # 不支援 FC2
        if 'FC2' in number_upper:
            return None

        # 1. 查快取（最快）
        cache = self._load_cache()
        if number_upper in cache:
            cached_cid = cache[number_upper]
            result = self._fetch_by_id(cached_cid)
            if result:
                rate_limit(self.config.delay)
                return result

        # 2. 用前綴映射轉換（快）
        converted_cid = self._convert_with_hints(number)
        if converted_cid:
            result = self._fetch_by_id(converted_cid)
            if result:
                self._save_cache(number, converted_cid)
                rate_limit(self.config.delay)
                return result

        # 3. 搜索 API 發現（慢，但會寫入快取）
        discovered_cid = self._search_content_id(number)
        if discovered_cid:
            result = self._fetch_by_id(discovered_cid)
            if result:
                self._save_cache(number, discovered_cid)
                rate_limit(self.config.delay)
                return result

        # 4. 使用者直接提供完整 cid 兜底（如 h_113id00057）
        #    - 觸發條件：輸入無法解析為標準番號（非 ABC-123 格式）
        #    - GraphQL 對 cid 大小寫敏感且僅認小寫 → 統一轉小寫
        #    - 成功後以返回的規範番號（makerContentId）為鍵存快取
        prefix, _ = self._parse_number(raw_input)
        if not prefix:
            result = self._fetch_by_id(raw_input.lower())
            if result:
                canonical = result.number or number_upper
                self._save_cache(canonical, raw_input.lower())
                rate_limit(self.config.delay)
                return result

        # 5. 完全失敗
        return None

    def search_by_keyword_with_ids(self, keyword: str, limit: int = 20, offset: int = 0) -> list[tuple[str, Video]]:
        """
        關鍵字搜尋（輕量版）— 回傳 (content_id, shallow_Video) tuples。
        供 facade 層 ThreadPoolExecutor enrichment 使用。
        不呼叫 _fetch_by_id（不做 enrichment）。
        """
        try:
            payload = {
                'query': self.SEARCH_LIST_QUERY,
                'variables': {
                    'limit': limit,
                    'offset': offset,
                    'sort': 'RELEASE_DATE',
                    'queryWord': keyword,
                }
            }
            response = self._session.post(
                self.API_URL,
                json=payload,
                timeout=self.config.timeout,
            )

            if response.status_code != 200:
                return []

            data = response.json()
            if not data.get('data') or not data['data'].get('legacySearchPPV'):
                return []

            contents = data['data']['legacySearchPPV']['result']['contents']
            if not contents:
                return []

            pairs = []
            for item in contents:
                content_id = item.get('id', '')
                if not content_id:
                    continue
                actresses = [
                    Actress(name=a['name'])
                    for a in (item.get('actresses') or [])
                    if a.get('name')
                ]
                video = Video(
                    number=self._content_id_to_number(content_id),
                    title=item.get('title', ''),
                    actresses=actresses,
                    maker=(item.get('maker') or {}).get('name', ''),
                    cover_url=(item.get('packageImage') or {}).get('largeUrl', ''),
                    source=self.source_name,
                    detail_url=f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={content_id}/",
                )
                pairs.append((content_id, video))

            return pairs

        except Exception:
            return []

    def search_by_keyword(self, keyword: str, limit: int = 20, offset: int = 0) -> list[Video]:
        """關鍵字搜尋（女優名、片商名等日文關鍵字）"""
        try:
            payload = {
                'query': self.SEARCH_LIST_QUERY,
                'variables': {
                    'limit': limit,
                    'offset': offset,
                    'sort': 'RELEASE_DATE',
                    'queryWord': keyword,
                }
            }
            response = self._session.post(
                self.API_URL,
                json=payload,
                timeout=self.config.timeout,
            )

            if response.status_code != 200:
                return []

            data = response.json()
            if not data.get('data') or not data['data'].get('legacySearchPPV'):
                return []

            contents = data['data']['legacySearchPPV']['result']['contents']
            if not contents:
                return []

            results = []
            for item in contents:
                content_id = item.get('id', '')
                if not content_id:
                    continue

                # Enrichment: 逐筆 _fetch_by_id 取得完整 Video
                try:
                    video = self._fetch_by_id(content_id)
                except Exception:
                    video = None
                if video is None:
                    # Fallback: 從搜尋結果建構 shallow Video
                    actresses = [
                        Actress(name=a['name'])
                        for a in (item.get('actresses') or [])
                        if a.get('name')
                    ]
                    video = Video(
                        number=self._content_id_to_number(content_id),
                        title=item.get('title', ''),
                        actresses=actresses,
                        maker=(item.get('maker') or {}).get('name', ''),
                        cover_url=(item.get('packageImage') or {}).get('largeUrl', ''),
                        source=self.source_name,
                        detail_url=f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={content_id}/",
                    )
                results.append(video)
                rate_limit(self.config.delay)

            return results

        except Exception:
            return []

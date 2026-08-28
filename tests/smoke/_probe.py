"""Per-source reachability probe for the live canary (TASK-73b-T3).

`_probe_reachable(source, number, scraper) -> bool` distinguishes state-1 (site
down / unreachable) from state-2 (200 but parser empty) for Group A sources.
Used only when `search()` returns None — a True probe + None search means the
site responded but parsing failed (state-2 fail); a False probe means the site
is unreachable (skip).

CONTRACT: this function MUST NEVER raise. Any exception (connection error,
timeout, proxy failure, missing attribute) -> return False (= unreachable ->
skip). probe false-positives (e.g. javbus soft-404 returning 200 for a delisted
number) are absorbed by quorum (>=1 pass wins).

Zero production scraper changes: reuses existing scraper URLs/helpers/session.
"""
import requests


def _probe_reachable(source: str, number: str, scraper) -> bool:
    """Return True if `source` looks reachable for `number`, else False.

    Group A only (javbus / heyzo / d2pass / jav321 / dmm / avsox). Group B and unknown
    sources return False (-> classify_one row 6 skip, never a false state-2 fail).
    """
    try:
        if source == "javbus":
            # Same URL as search() (javbus.py:95-96), including the lang prefix so
            # the probe stays faithful if the scraper is ever built non-default-lang
            # (default zh-tw prefix is ""). Reuse session headers for a browser-y
            # User-Agent (some edges 403 a bare requests UA).
            prefix = scraper._get_lang_prefix() if hasattr(scraper, "_get_lang_prefix") else ""
            headers = dict(getattr(scraper._session, "headers", {}))
            resp = requests.get(
                f"{scraper.BASE_URL}{prefix}/{number}", headers=headers, timeout=10
            )
            return resp.status_code == 200

        if source == "heyzo":
            num = scraper._extract_heyzo_num(number)
            if not num:
                return False
            resp = requests.get(
                f"https://en.heyzo.com/moviepages/{num}/index.html", timeout=10
            )
            return resp.status_code == 200

        if source == "d2pass":
            # Use the scraper's own JSON fetch: non-None = HTTP 200 + valid JSON.
            site = scraper._detect_site_order(number)[0]
            movie_id = scraper.normalize_number(number)
            return scraper._fetch_json(site, movie_id) is not None

        if source == "jav321":
            # Low-confidence: guessed detail URL (jav321.py:177). Real search is a
            # POST flow, so a 200 here may be a false-positive -> absorbed by quorum.
            resp = requests.get(
                f"https://www.jav321.com/video/{number.lower()}", timeout=10
            )
            return resp.status_code == 200

        if source == "dmm":
            # Proxy-reachability: a bare GET to the GraphQL API through the proxied
            # session. The endpoint may reject a GET (400/404/405) but ANY HTTP
            # response proves proxy + host are reachable. Only connection/proxy
            # errors (caught below) -> False.
            scraper._session.get(scraper.API_URL, timeout=10)
            return True

        if source == "avsox":
            base, _ = scraper._ensure_session()
            return base is not None

        if source == "javdb-api":
            # 契約：**任何 HTTP 回應 ＝ True**（主機在、網路通），只有連線層失敗 ＝ False。
            # 是不是 200、內容對不對，都是 classify_one 要判的事，不是 probe 的事。
            #
            # 🔴 **刻意不用 `javdb_api.api_search()`**（review P1）：它回答的是
            # 「有沒有拿到可用資料」，不是「主機有沒有回應」。簽章輪替、信封形狀改變、
            # 被擋——全都會讓它丟例外，而那些正是「**我們自己壞了**」的情形。
            # 那些例外被本函式底下的 `except Exception: return False` 收成 unreachable
            # 之後，`classify_one` 走 row 5（skip）⇒ **這顆燈在它最該紅的時候不會紅**。
            # 用同一支會用同一種方式失敗的函式同時當 probe 和 search，probe 就沒有資訊量。
            #
            # 所以這裡自己送一次請求，只在**連線層**失敗時回 False。
            # 沿用 javdb_api 的網域／路徑／簽名（同 javbus 分支重用 scraper 的 URL 與 session
            # 的理由）——網域知識不做第二份拷貝。
            from core.scrapers import javdb_api

            # 網域備援與參數名都跟著正式路徑走（`api_get()`）：
            # ① 只打第一個網域的話，「主網域死、鏡像活」會被判成 unreachable ⇒ skip，
            #    而正式路徑那時是活的——偵測器會在不該黃的時候黃。
            # ② 參數名是 `device_uuid` 不是 `uuid`（pre-merge branch review 抓到打錯）。
            #    這裡不重建參數字典，直接照 `api_get()` 的組法，避免第二份拷貝再漂一次。
            for _host in javdb_api._API_HOSTS:
                query = dict(javdb_api._PUBLIC_PARAMS)
                query["device_uuid"] = javdb_api._DEVICE_UUID
                query["q"] = number
                try:
                    requests.get(
                        _host + javdb_api._SEARCH_PATH,
                        params=query,
                        headers={
                            "jdsignature": javdb_api.sign(),
                            "user-agent": javdb_api._USER_AGENT,
                        },
                        timeout=10,
                    )
                except requests.exceptions.RequestException:
                    continue
                return True
            return False

        # Group B (javdb / fc2) or unknown source.
        return False
    except Exception:
        # NEVER raise — any failure means "treat as unreachable" -> skip.
        return False

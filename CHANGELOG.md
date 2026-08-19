# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.14.1] - 2026-08-20

### Added

#### 🏷️ 檔名裡的版本後綴，現在會變成標籤
- 檔名帶 `-C`／`-U`／`-UC`／`-leak`／`-4K`／`-VR` 的片，會被認出來並寫成「中文字幕」「無碼破解」「無碼流出」「4K」「VR」標籤（NFO 的 `<tag>` 與 `<genre>` 同步、資料庫一致），**瀏覽頁的標籤篩選立刻就能用**。過去這些字只被當成「改名時要保留的字」，沒有任何地方把它轉成語意。
- **整理入庫、掃描既有庫、補齊資料、唯讀來源產出四條路徑行為一致**——不管你的片是怎麼進來的，同一個檔名得到同一組標籤。已經整理好、檔名還帶著 `-C` 的舊庫，重掃一次就免費受惠。
- 「無碼破解」（AI 演算法去馬）和「無碼流出」（母帶外流）是兩件不同的事，**不互斥也不排序**：同時命中就兩個都給——想看原生畫質的人不要 AI 腦補的那一份。
- 分集檔（`-cd1`／`-pt2`）不會長出標籤；`ABCUC-123` 這種黏在番號裡的字、或 `Uncensored Paradise` 這種出現在句子裡的字也不會被誤認。
- 設定頁「版本標記」清單與這張表是**兩件獨立的事**：你把 `-4k` 從版本標記刪掉（因為不想要檔名裡有那幾個字），4K 標籤照樣產生。

### Fixed
- **按「補齊資料」補出來的中文字幕標籤，過去進得了 NFO 卻進不了資料庫**——Jellyfin 那邊看得到分類，OpenAver 自己的瀏覽頁卻篩不到，得再掃一次才會出現。
- **補齊資料過去只看有沒有外掛字幕檔、不看檔名**：`ABC-123-C.mp4` 旁邊沒有 `.srt` 時就認不出有字幕（整理入庫那條路本來就會看檔名）。兩條路現在對稱了。

### Changed
- **瀏覽頁的標籤條件現在也會比對你手貼的自訂標籤**：在燈箱打上「中字」，篩「中文字幕」就找得到那片——不必先去建別名組。統計（標籤排行）與相似探索維持只看刮到的標籤、不吃自訂標籤，那兩處混進私人標籤會失準。
- 重掃時，同一份 NFO 裡大小寫不同的重複分類（`<genre>VR</genre>` 與 `<genre>vr</genre>`）會併成一筆，瀏覽頁少一個近重複的標籤。

測試數 6827 → 6901（pytest；npm test 847 → 863）。

## [0.14.0] - 2026-08-19

### Added

#### 🎯 拿不到的時候，畫面上要有話說（issue #135）
- **燈箱**：碟沒插、檔案被移走或封面檔不見時，燈箱過去**看起來一切正常**——它疊了兩層圖，上層的原圖載不到只會保持透明，你看到的是底下那張本機縮圖。現在上層載不到會顯示一行提示，告訴你這片的封面現在讀不到。
- **瀏覽器／手機播放**：按播放開新分頁，檔案拿不到或格式瀏覽器不支援時，過去是**一片黑、一個字都沒有**；現在就地顯示提示。桌面版本來就有「播放失敗」提示，這次補的是瀏覽器與區網那一半。
- 播放頁的語言跟著設定走（過去寫死繁中）。

### Fixed

#### 🪟 Windows 啟動與安裝（issue #139）
- **裝了 WebView2 卻說沒裝**：以一般身分（非系統管理員）安裝官方 WebView2 Runtime 的人，過去啟動一律失敗並在 log 留下「WebView2 Runtime 未安裝」這句**假話**，只能自己摸索出「右鍵以系統管理員身分重裝」。偵測改為 pywebview 判準的忠實移植，一般身分安裝的 runtime 現在認得出來。
- **提示視窗根本沒跳出來**：打包版沒有 tkinter，那個要告訴你「請先安裝 WebView2」的視窗過去只在 log 留一行「無法顯示提示視窗」——等於什麼都看不到。改用 Windows 系統內建的訊息視窗，不再依賴打包裡不存在的東西。
- **log 不再說假話**：「視窗根本沒能顯示」過去被記成「用戶取消安裝」，往那個方向查只會更迷路。兩件事現在分開記。
- **開不了瀏覽器時，網址自動進剪貼簿**：訊息視窗裡的網址無法用滑鼠框選，過去只能手打。現在進到那個視窗之前就已經複製好，貼上就行；複製失敗時視窗會明說「請按 Ctrl+C 複製此視窗文字」，不會假裝已經複製。
- **安裝視窗不再閃一下就消失**：安裝出錯時紅字一閃而過，你不知道到底裝了沒。現在任何結束方式都會停住等你確認，出錯時還印得出是在哪一行出的問題；殘留的按鍵也不會再把停留吃掉。
- **啟動失敗回到靜默退出**：把 OpenAver 設成開機自動啟動、或放在沒人看的機器上時，啟動失敗不會卡在一個沒人會按的對話框上佔著 port 不結束。要看細節仍然是 `OpenAver_Debug.bat`（開主控台、印完整錯誤、不關窗）。

#### 👙 罩杯排序／篩選支援 L 以上（issue #142）
- L 罩杯以上的女優過去在「依罩杯排序」時**不論升冪降冪都被當成沒有罩杯資料、一律沉到最後**。同一個原因還造成兩個沒人發現的問題：掛上「≥K 罩杯」這類條件時 L 以上的女優會**整批被漏掉**，以及她們資料卡上的罩杯格子點了沒反應。三處由同一個取值函式修好，A–K 的既有結果逐值不變。

### Changed
- 打包產物的驗證加上標準函式庫巡檢：像 `ctypes` 這種被打包流程弄壞、平常測試又照不到的情況，現在會在 CI 就擋下來，不必等使用者開 issue 才發現。

測試數 6728 → 6827（pytest；npm test 825 → 847）。

## 0.13.x 系列 (v0.13.0 ~ v0.13.14, 2026-08-01 ~ 2026-08-15)

- **封面正典位置與媒體伺服器整合收斂**（v0.13.0、v0.13.2～v0.13.4，feature/109 起）：唯讀來源封面產出邏輯先收斂成單一入口（v0.13.0，純內部、零行為變更）；修好「補齊 Jellyfin 圖片」把只有 `-poster` 的片封面原圖就地裁小且不可還原、以及封面被記成 `-fanart` 誤判成缺 NFO 兩個問題（v0.13.3）；接著把封面「正典位置」翻面——不再多產一張同名封面、`-fanart` 升格為正典，修好接 Jellyfin／Emby／Kodi 時封面牆橫式圖塞進直式格子（v0.13.4）；外部媒體管理器設「關閉」時唯讀來源不再多產兩張沒人看的圖、省空間，同時修好 HEYZO 站方改版造成的搜尋整個查無問題（v0.13.2）。
- **第三方 NFO 誤判缺漏遭覆寫修復**（v0.13.5）：片庫裡若有 Jellyfin／Emby／其他刮削器留下的 `.nfo`，裡面明明有的演員／片商／發行日／分類標籤過去會被誤判缺漏、上網刮一份回來覆寫掉——四種讀不到的寫法全部修好；另修「欄位有標籤沒內容當成已有資料」「全空白標籤吃掉後面合法值」「補完寫完檔案卻整片報失敗」「同一女優兩個下載互相覆蓋」等靜默 bug。
- **區網與帳密安全性全面強化**（v0.13.1、v0.13.6～v0.13.8）：升級元件消除 17 個已知 CVE、整理與唯讀庫產出加上路徑逃逸最終防線（v0.13.1，feature/110）；metatube 帳密三處外流出口封閉、圖片來源改宣告式白名單（v0.13.6）；區網連線可設 4 位密碼，擋下的人看到偽裝頁而非登入畫面，連錯自動鎖定並加公網暴露警告（v0.13.7）；密碼保護開啟後可給 AI agent 專屬連線 token（改密碼即自動撤換），設定頁的 API 金鑰／metatube token 不再完整送進瀏覽器、只回後四碼（v0.13.8）。
- **瀏覽篩選與女優牆體驗升級**（v0.13.9～v0.13.11）：瀏覽頁篩選從「點一下就整段蓋掉關鍵字」改成可疊加的條件標籤（女優／標籤／片商／導演／系列／廠牌可同時掛上、取交集，v0.13.9）；女優燈箱的年齡／身高／罩杯也能點出條件，並可改成以下／以上／自訂區間（v0.13.10）；女優牆新增「從片庫加入女優」面板，依片數由多到少排序、一鍵收藏庫內尚未加入最愛的人（v0.13.11）。
- **FC2 來源修復**（v0.13.12～v0.13.13）：FC2 來源鏡像站整站被 Cloudflare 擋到搜尋 100% 查無資料，改打官方站恢復搜尋，並讓劇照支援的檔案類型對齊 Jellyfin、修好部分 Windows 上側邊欄 logo 顯示成破圖（v0.13.12）；官方站已下架的片再補一條備援來源 FC2-javten（僅限 Windows 桌面版、重刮彈窗手動選用，v0.13.13）。
- **桌面影片牆新增直式海報卡型**（v0.13.14）：桌面工具列的模式選單多一條「直式海報」，與「完整封面」並列可切換、切換即時記住；只是同一張封面在畫面上的裁切顯示，不動封面原檔、不碰 NFO。

測試數 5640 → 6728（pytest；npm test 287 → 825；v0.13.13 全文未附測試段落，範圍取有紀錄的相鄰版本）。

## 0.12.x 系列 (v0.12.0 ~ v0.12.10, 2026-07-14 ~ 2026-07-24)

- **焦點裁切上線與收尾**（v0.12.0～v0.12.1、v0.12.3，feature/98/99/101）：無碼封面（FC2／素人／uncensored）刮削或掃描時自動偵測人臉、以臉為中心裁切封面與燈箱大圖，有碼片維持原樣零成本；燈箱補上「自動對焦→左右拖曳微調→存檔」正式互動、唯讀來源也納入自動對焦、牆上小格裁切改與燈箱大圖同精準度；後續再擴及 Jellyfin/Emby/Kodi 媒體伺服器海報，對焦等待動畫改視覺連續交棒，影片對焦鈕改為只在窄螢幕／手機才出現。
- **女優照片管理更完整**（v0.12.2、v0.12.4，feature/100/102）：女優頭像可自行上傳照片、也能像影片一樣手動對焦裁切；修好改過名（有別名）的女優在照片挑選視窗選本機候選必失敗、雲端重抓永遠查不到圖的問題，重抓改為自動輪流用她的每個名字查詢；順手讓搜尋詳情、燈箱、劇照瀏覽都能用滑鼠滾輪切換上一片／下一片。
- **技術債清償**（v0.12.5，feature/103）：約 130 行硬編碼中文文字收進語言檔；拖曳檔案與貼上檔名的番號辨識規則統一為同一套後端規則（不再兩套邏輯漂移）、辨識失敗改明確提示；清除死碼、logger 與中文硬編碼機械 lint 守衛正式上線。
- **唯讀來源（雲端／NAS 分享盤）功能大幅強化**（v0.12.6、v0.12.7，feature/104/105）：已經整理好的唯讀庫（旁邊有 `.nfo`／封面）改為直接就地讀用、不再無腦重刮，唯讀片的放大鏡補料／齒輪重刮／補劇照三顆鈕全面解禁（產物仍一律落獨立輸出夾、來源零寫入）；並把散在四處、常常改一處漏改一處的「記帳與回報」邏輯收斂成一份共用實作，順手修好唯讀破圖、原文標題被清空等一批連帶 bug。
- **整理前手動修正 + 桌面體驗收尾**（v0.12.8～v0.12.10，feature/106/107/108）：拖檔進搜尋頁後可在整理前直接改演員名單、幫無碼片補發售日；桌面版加上開機自動檢查更新（可關）、修好深色主題幾顆看不清的按鈕；手機瀏覽封面吃滿寬度、觸控裝置封面不再擠一排操作圖示（改進燈箱操作）、女優牆卡片大小對齊影片牆不再忽大忽小。

測試數 5233 → 5640（0.12.0 全文未附測試段落，範圍取最早可查的 0.12.1 起；前一系列 0.11.12 收尾值為 5030）。

## 0.11.x 系列 (v0.11.0 ~ v0.11.12, 2026-06-27 ~ 2026-07-12)

- **v0.11.0**：JavBus 過度泛用清償 + exact 番號搜尋改優先序 cascade（feature/85）——直接搜番號改為依你拖曳的來源優先順序逐一查詢（cascade，命中即回），JavBus 不再無視優先序搶先短路；DMM proxy 透傳修復、前綴搜尋 `type` 參數修正；拔除已死的 JavBus variant（同番號多版本）探查死碼。
- **v0.11.1**：JavLibrary 同番號多版本手動切換（feature/86）——搜尋框直搜／燈箱換來源／結果卡替換來源三入口皆可看封面手動挑撞號版本（游標預設停最新發行日），桌面 standalone 限定（需 CF transport）。
- **v0.11.2**：`core/database.py` 模組化拆分（feature/87）——2,152 行單檔拆成 `core/database/` 套件（六個領域子模組 + 永久 re-export facade），消除 `AliasRepository`／`TagAliasRepository` 鏡像重複碼（共用泛型基類），零行為／API／schema 變更。
- **v0.11.3**：唯讀來源生成本地媒體庫「off 風味」首發（feature/88）——scanner 來源可勾「唯讀」＋設輸出夾，來源零寫入下生成每片一資料夾的本地庫（NFO + 封面 + 劇照）並直接寫進 DB，供 OpenAver 自身瀏覽／串流播放雲端原檔；給 Emby/Jellyfin/Kodi 的 media-server（`.strm`）風味延後至下一版（feature/89）。

- **v0.11.4**：唯讀產生庫「地基」+ 掃描頁「試過」記憶 + 來源刪檔清死卡（feature/89）——生成片記住輸出夾（`videos.output_dir`）重刮原地更新不長重複夾、off 風味固定輸出夾免設定；試過／已生成的片不再被「缺資料」嘮叨、刮不到只試一次；唯讀網盤掉線明確警告不誤報成功；來源刪檔後 DB-row-only 清死卡（零檔案刪除）。
- **v0.11.5**：唯讀來源生成媒體伺服器庫「.strm 風味」+ 跨機器路徑映射 + 唯讀寫入全面封鎖（feature/90）——唯讀來源可產出 `.strm` 捷徑檔給 Emby/Jellyfin/Kodi 掃描播放，跨機器「播放端路徑替換」規則讓 `.strm` 內路徑翻成播放端看得懂的形式、改規則一鍵同步改寫既有 `.strm`；同時把唯讀來源「零寫入」補到滴水不漏（勾唯讀破壞性確認、四個寫入入口全面停用、切模式清舊媒體卡、產生中斷乾淨收尾）。
- **v0.11.6**：跨機器路徑映射（WSL2+UNC）讀寫全棧收斂 + DB-key 命名空間守衛（feature/91）——純 correctness 重構：修好「讀取端忘了在碰磁碟前把映射路徑反解回本機路徑」導致縮圖／封面／串流跨機器讀不到的一類 silent bug，以及「已反解路徑又被裸餵回 DB key」導致重刮掉使用者標籤、女優照 403 的另一類；兩支 AST 結構守衛擋死回歸。

- **v0.11.7**：搜尋頁體驗優化（feature/92）——搜尋列右側控制項不再擠壓變形、整理入口常駐可見更好找、整理入庫「飛入側邊欄」動畫加強為三段節奏，並抽成可跨頁複用的共用元件；順手修好「重新整理已有結果頁面時出現兩組 ✕」的 latent bug。
- **v0.11.8**：各刮削來源評分/簡介補進 NFO（feature/93，NFO-only）——七源評分、六源簡介寫進 `<rating>`/`<plot>`，純服務媒體伺服器（Jellyfin/Emby/Kodi）用戶，OpenAver 自身介面不顯示；順手美化燈箱中繼資訊視覺層次。
- **v0.11.9**：掃描頁「補資料」升級成逐片進度卡 + 命中封面飛入圖書館（feature/94）——補資料時逐片可視進度（搜尋中／命中／查無／失敗／唯讀跳過），真封面命中飛入側邊欄「瀏覽」入口。
- **v0.11.10**：設定頁命名區膠囊化 + 列表生成兩層 IA 重排（feature/95）——檔案命名格式從手打字串改成「變數膠囊 + 字面文字」視覺化編輯器、資料夾層級改動態清單（硬上限 3 層）；列表生成設定拆成日常常用（常駐）+ 離線 HTML 匯出（摺疊進階）。
- **v0.11.11**：前端靜態守衛 pytest → lint 全面遷移（feature/96，test-deflation）——純內部工程里程碑（零產品碼、對使用者隱形）：把 `test_frontend_lint.py` 裡「讀原始碼做字串/結構斷言」的守衛搬回工具層（新增 `i18n_lint`／`static_guard_lint`／`css-guard` 三支 `.mjs` + eslint `SEL_*` 家族），`test_frontend_lint.py` 16,749→5,041 行（−70%）、36 個真 contract class relocate 進 `frontend_contracts/`；north-star＝「能用 lint 機械處理的不進 pytest、不耗 Codex 審」。
- **v0.11.12**：javdb 在 released 版復活（feature/97）——打包瘦身刪除所有 `.dist-info` 導致 curl_cffi import-time 拋 `PackageNotFoundError`、被靜默吞掉，released Windows/macOS 版 javdb 從第一天就零 HTTP 請求；不再剝除 dist-info 即修復，並補打包產物 runtime 驗證守衛（`verify_artifact_imports.py` + dist-info 靜態檢查 + CI verify job）堵死 dev-only 測試盲區；本版另 bundle 兩個後續修復：非 ASCII 安裝路徑 `curl error 77`（CAINFO 改用 ANSI code page 編碼）+ 番號 7 字母前綴拖檔截斷修復。

測試數 4735 → 5523（v0.11.10）→ 4985（v0.11.11 test-deflation：守衛遷 lint 層等價承接，−538 非覆蓋損失）→ 5030（v0.11.12，+45：打包產物驗證守衛 + javdb CAINFO + 番號 cap 對齊回歸鎖）。

## 0.10.x 系列 (v0.10.0 ~ v0.10.11, 2026-06-18 ~ 2026-06-24)

- **來源穩定性 + 測試硬化**（v0.10.0，feature/73）：8 源真實番號健康金絲雀 smoke（三態 quorum 判讀）+ avsox 復活（站方轉 SPA 後改打背後 JSON API）+ Tokyo Hot 單字母無碼番號查無修復 + 覆蓋率地板 84%（`cov-floor`）+ 五項高風險模組（含會改寫用戶 NFO 的 `nfo_updater`）離線單元測試債清償。
- **前端呈現與發現性優化**（v0.10.1～v0.10.2，feature/74/75）：進階搜尋畢業為永久常駐核心，隱形長壓手勢全面移除、改「來源膠囊」處處可見觸發挑源／換源；搜尋詳情資訊密度重排、封面正面裁切共用規則、行動裝置基礎相容（scroll trap／星空門檻／觸控 overlay）補齊。
- **開發工具鏈硬化 + 前端離線可靠性**（v0.10.5～v0.10.6，feature/78/79）：`ruff` + eslint/stylelint 進 CI 擋 PR（先前純本地、沒人本地跑就漏）；GSAP/Alpine/圖示字型改本機載入斷網仍可用、前端錯誤自動記錄；`requirements.txt` 精確鎖版並把 Starlette 鎖至最新修補版清除已知 CVE。
- **MPA 跨頁轉場 + Fluent 材質統一**（v0.10.3～v0.10.4，feature/76/77）：純 CSS View Transitions 讓 sidebar 切頁白屏閃爍改平滑淡換（Showcase 因常駐動畫維持硬切）；全站材質收斂成單一 token 系統的 6 角色（Mica canvas／Glass shell／panel／caption／overlay／Media frame）+ 浮動圓角玻璃 chrome 擴及 search／settings／scanner。
- **LAN 伺服器模式 + 手機體驗完整化**（v0.10.7～v0.10.11，feature/80/81/82/83/84）：一鍵把桌面 App 開放給同區網手機／平板瀏覽（dual-listener + 區網存取閘門）；手機加主畫面圖示、封面／燈箱左右滑換片、窄螢幕破版修補；Windows 系統匣關閉行為（最小化背景執行）；燈箱封面比例自適應不留白 + 行動星形爆射相似探索面板；Windows 雙擊安裝捷徑 + Help 頁一鍵更新按鈕。

測試數 4089 → 4735。

---

## 0.9.x 系列 (v0.9.0 ~ v0.9.11, 2026-05-29 ~ 2026-06-13)

- Scraper Federation + metatube HTTP 聯邦（30 provider Parts Bin + promote/demote + 無碼 staged + SSRF 驗證）、Settings 分區 IA + 資料驅動來源 schema + 進階重刮彈窗
- Active Row 拖曳順序成搜尋路由唯一真理（拔除 primary_source）；async-offload 慢 I/O 移出 event loop（NAS stat / sqlite / config / 同步 HTTP）+ config 鎖/原子寫 + AST 守衛；封面三態（skeleton/shimmer/破圖）+ Showcase console 清零
- 新增來源：JavLibrary（BETA，桌面借 PyWebView 過 Cloudflare）+ avsox 復活（轉 JSON API）+ Tokyo Hot 單字母番號修復；8 源真實番號健康金絲雀 smoke（三態 quorum 判讀）+ cov-floor 84% 流程地板
- 本地 WebP 縮圖快取（opt-in，SSD 出圖不碰 NAS + blur-up 燈箱）+ 燈箱單筆刪除（只刪 DB row）；VR 投影標籤保留 + 自動 VR tag
- 外部媒體管理器相容（Jellyfin/Emby/Kodi 四態：poster/fanart 命名 + cd1/cd2 合併 + NFO 補欄 + Scanner 識別外部封面）；dim 暗色主題色彩編碼修復；進階搜尋畢業為永久常駐核心

測試數 2937 → 4089。

## 0.8.x 系列 (v0.8.0 ~ v0.8.10, 2026-04-28 ~ 2026-05-28)

- Charter Pilot：Fluent 2 視覺語言全站統一（§1–§6 + ease/DURATION 三角色）+ Ghost-fly Lightbox 共用化 + Alpine 釘版四插件 + 全站通知中心
- 全站前端 ESM 模組化（Import Maps，巨型單檔全解體）+ lint toolchain（eslint flat config + stylelint，frontend_lint 905→450）
- 以圖搜圖 CLIP Beta 出貨後轉向純規則式相似度排序器（拔 ML 依賴、主 ZIP 271MB→43MB）
- Tag Alias 跨語言系統 + Search→Showcase pipeline 即時化（GhostFly + DB 即時 upsert）+ Onboarding Scanner-first 翻轉 + SSRF 白名單 + 女優查詢 json_each 重寫

測試數 2705 起（系列歷經 CLIP 上下架與 lint 瘦身，末值未單列）。

## 0.7.x 系列 (v0.7.0 ~ v0.7.8, 2026-04-10 ~ 2026-04-26)

- Agentic AI API 平台首發（batch-search / generate-from-ids / enrich-single / collection-sql / capabilities manifest）
- User Tags 三層整合（DB + NFO `<user_tag>` + API + Search/Showcase 雙頁 UI）
- Actress Favorite + Showcase 女優模式（actresses DB + Orchestrator 4 路並行 + 女優 Grid/Lightbox/Hero + GSAP）+ Actress Alias CRUD
- Scanner 一鍵補完（missing-check + batch-enrich SSE 分批）+ Ghost Fly 轉場 + WinFsp/rclone 掛載相容 + 劇照幽靈 URL 修正

測試數 1818 → 2705。

## 0.6.x 系列 (v0.6.0 ~ v0.6.7, 2026-03-29 ~ 2026-04-09)

- 四語系 i18n 建立（繁中/簡中/日文/英文，~477 key + `core/i18n.py` + `window.t()` + JavBus lang 連動）
- Agentic AI API 初版（batch-search / generate-from-ids / enrich-single / collection-sql / capabilities）+ OpenAI Compatible 翻譯 Provider
- Alpine.js 技術債清理（6 頁統一 `Alpine.data()` 註冊、移除 bridge.js/init.js、SearchCore 全域消除）
- Scanner Jellyfin 圖片手動觸發 + TTL 快取 + 前端動效補強（checkmark/shake + Load More stagger + alert→toast）

測試數 1366 → 1634。

## 0.5.x 系列 (v0.5.0 ~ v0.5.5, 2026-03-25 ~ 2026-03-28)

JavBus Scraper 完全重寫（移除 jvav 第三方依賴）+ Video Model 擴充（director/duration/label/series/sample_images）+ Sample Gallery 元件（extrafanart 全鏈路）+ Metadata Pipeline 補齊（NFO 讀寫全欄位）+ Maker 名稱對照表重建（雙層 JSON + shared loader）+ DMM 模糊搜尋 + 全來源欄位補齊（Jav321/AVSOX/HEYZO/FC2/D2Pass）+ 字幕檔自動偵測搬移 + Proxy direct 模式。測試數 1007 → 1366。

## 0.4.x 系列 (v0.4.0 ~ v0.4.4, 2026-03-08 ~ 2026-03-19)

GSAP 搜尋頁動畫系統（SSE 漸進搜尋 + Mini-Burst + Grid↔Detail 共享封面轉場 + Cover State Machine）+ GSAP Showcase 動效系統（Flip 排序 + stagger 分頁 + Motion Lab）+ Lightbox 重設計（glass circle overlay + metadata panel）+ Source Link 設定 + 安裝腳本升級 + 測試套件大整合（去重 + conftest 統一 + 覆蓋率補強）。測試數 731 → 1007。

## 0.3.x 系列 (v0.3.0 ~ v0.3.6, 2026-02-08 ~ 2026-02-20)

Bootstrap → DaisyUI + Alpine.js 全站遷移 + Showcase 動態化（SQLite SSR 取代靜態 iframe）+ Search Grid Mode + 女優資料卡（Graphis + JavBus 並行）+ Fluent Material Boost（Mica/Acrylic）+ GSAP 前置基礎建設 + Scraper 擴充（D2Pass/HEYZO/DMM/gfriends/Graphis）+ 路徑工具統一（uri_to_fs_path/pathToDisplay）+ UNC 路徑修正 + 版本標記覆蓋保護 + Jellyfin 圖片模式。測試數 523 → 817。

## 0.2.x 系列 (v0.2.0 ~ v0.2.4, 2026-01-22 ~ 2026-02-07)

Design System 建立（Fluent Design 2 視覺語言 + AV Card 4 變體 + Token 系統）+ macOS 支援（Alpha）+ AI 翻譯雙引擎（Ollama + Gemini）+ 多層目錄結構 + FC2/無碼搜尋 + SQLite 本地收藏庫 + Scraper 模組化架構（5 個獨立 scraper）+ 番號後綴清理修正。測試數 126 → 564。

## 0.1.x 系列 (v0.1.0 ~ v0.1.4, 2026-01-15 ~ 2026-01-17)

初始版本發布：多來源番號搜尋（JavBus/Jav321/JavDB）+ Gallery UI + 智慧搜尋 + 批次搜尋 + NFO 自動補全 + Settings（Dark Mode + Ollama 翻譯 + 輸出格式設定）+ 新手教學（Tutorial 4 步驟）+ Windows 打包 + 路徑工具統一（path_utils）+ 版本管理集中化。測試數 115 → 311。

> 完整歷史紀錄請見 [CHANGELOG_ARCHIVE.md](CHANGELOG_ARCHIVE.md)

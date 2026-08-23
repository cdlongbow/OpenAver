# Contributing to OpenAver

感謝您對 OpenAver 的興趣！我們歡迎各種形式的貢獻。

## 📋 目錄

- [行為準則](#行為準則)
- [報告 Bug](#報告-bug)
- [請求新功能](#請求新功能)
- [提交 Pull Request](#提交-pull-request)
- [開發環境設定](#開發環境設定)
- [代碼風格](#代碼風格)
- [Commit 訊息規範](#commit-訊息規範)

---

## 行為準則

參與本專案即表示您同意遵守我們的 [行為準則](CODE_OF_CONDUCT.md)。請尊重所有參與者。

---

## 報告 Bug

發現 Bug 了嗎？請按以下步驟報告：

1. **搜尋現有 Issues** - 確認問題尚未被回報
2. **建立新 Issue** - 使用 [Bug Report 模板](.github/ISSUE_TEMPLATE/bug_report.md)
3. **提供詳細資訊**：
   - 問題描述
   - 重現步驟
   - 預期行為 vs 實際行為
   - 環境資訊（作業系統、Python 版本）
   - 錯誤訊息或截圖（如有）

### 取得 Debug Log

Windows 打包版用戶：
1. 執行 `OpenAver_Debug.bat`
2. 重現問題
3. 附上 `%USERPROFILE%\OpenAver\logs\debug.log`

---

## 請求新功能

有好點子嗎？

1. **搜尋現有 Issues** - 確認功能尚未被請求
2. **建立新 Issue** - 使用 [Feature Request 模板](.github/ISSUE_TEMPLATE/feature_request.md)
3. **描述功能**：
   - 想解決什麼問題？
   - 建議的解決方案
   - 替代方案（如有）

---

## 提交 Pull Request

### 流程

1. **Fork** 本專案
2. **建立分支**：`git checkout -b feature/your-feature`
3. **開發**並確保測試通過
4. **Commit**（遵循 [Commit 規範](#commit-訊息規範)）
5. **Push**：`git push origin feature/your-feature`
6. **建立 Pull Request**

### PR 要求

- [ ] 測試通過：`pytest`
- [ ] 沒有引入新的 linting 錯誤
- [ ] 更新相關文檔（如有）
- [ ] PR 描述清楚說明變更內容

---

## 開發環境設定

```bash
# 1. Clone 專案
git clone https://github.com/slive777/OpenAver.git
cd OpenAver

# 2. 建立虛擬環境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 執行測試
pytest

# 5. 啟動開發伺服器
uvicorn web.app:app --reload --reload-include 'locales/*.json' --host 127.0.0.1 --port 8000
```

---

## 代碼風格

### Python

- 遵循 [PEP 8](https://peps.python.org/pep-0008/)
- 使用有意義的變數和函數名稱
- 加入適當的 docstring 和註釋
- 行寬上限：120 字元

### JavaScript

- 使用 2 spaces 縮排
- 使用 `const` / `let`，避免 `var`
- 函數和變數使用 camelCase

### HTML/CSS

- HTML 使用 2 spaces 縮排
- CSS 類名使用 kebab-case
- 遵循既有的 Bootstrap 5 結構

---

## Commit 訊息規範

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Type

| Type | 說明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修復 |
| `docs` | 文檔變更 |
| `style` | 代碼格式（不影響功能） |
| `refactor` | 重構（不是新功能或修復） |
| `test` | 測試相關 |
| `chore` | 建構或輔助工具變更 |

### 範例

```
feat(search): add batch file search functionality

- Add 20 files per batch processing
- Support pause/resume feature
- Show progress bar during search

Closes #123
```

---

## 💬 社群

加入 [Telegram 群組](https://t.me/+J-U2l96gv0FjZTBl) 與其他使用者交流分享！

---

## 🙏 感謝

感謝所有貢獻者讓 OpenAver 變得更好！

# 在 Linux 伺服器上跑 OpenAver

> **這是進階路徑，請自己承擔。** 一般使用者請走 [README 的 Win/Mac 一行安裝](../README.md#安裝)——
> 那條路有圖形介面、有安裝程式、有一鍵更新，這裡三樣都沒有。

這份文件寫給想把 OpenAver 架在**家裡那台沒有螢幕的 Linux 機器**上的人：舊主機、NAS、
Proxmox LXC、樹莓派都算。裝好之後你用**同一個網段內其他裝置的瀏覽器**操作它。

> ⛔ **不要架在公開的雲端主機上**（VPS、有公網 IP 的機器）。
> 理由見下方第 2 步的安全警告——這不是「不建議」，是這套軟體的門禁根本不是為那種場景設計的。

跟桌面版比，這條路少掉這些東西：

- **沒有應用程式視窗**，也沒有系統匣圖示
- **沒有「一鍵更新」按鈕**（那顆鈕是桌面版限定，見下方〈升級〉）
- **沒有原生的檔案選擇對話框**——改用網頁版的資料夾選擇彈窗（v0.14.8 起）

---

## 前置需求

- **系統上要有 Python 3.12**，以及建立虛擬環境用的 `venv` 模組
- `curl` 與 `tar`（幾乎所有 Linux 都內建）
- 影片檔所在的資料夾，這台機器讀得到

查一下你的版本：

```bash
python3 --version          # 要看到 3.12.x
```

**為什麼需要先裝 Python——不是有 venv 嗎？** venv **不含 Python 本體**，
它只是把系統上那支 python 用符號連結指過來，再獨立出一份套件目錄：

```
venv/bin/python3 -> /usr/bin/python3
```

所以 venv 隔離的是**套件**，不是直譯器；系統上沒有 python3，第一行 `python3 -m venv` 就跑不了。

Debian／Ubuntu 上另外要裝 venv 模組（Ubuntu 24.04 內建的就是 3.12）：

```bash
sudo apt install python3.12 python3.12-venv
```

3.12 是官方打包用的版本，也是唯一測過的。程式沒有硬性擋住其他版本，但別的版本沒人試過。

---

## 1. 安裝

抓最新**正式版**的原始碼，解壓到 `~/OpenAver`：

```bash
LATEST=$(curl -fsSL https://api.github.com/repos/slive777/OpenAver/releases/latest \
         | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
echo "最新正式版：$LATEST"

mkdir -p ~/OpenAver && cd ~/OpenAver
curl -fsSL "https://github.com/slive777/OpenAver/archive/refs/tags/$LATEST.tar.gz" \
  | tar xz --strip-components=1
```

裝相依套件：

```bash
python3 -m venv venv
grep -v '^pywebview' requirements.txt > /tmp/openaver-req.txt
venv/bin/pip install -r /tmp/openaver-req.txt
```

確認自己裝到哪一版：

```bash
grep -m1 '__version__' core/version.py
```

> 💡 **不想用那行自動查版號的話**，直接去 [Releases 頁面](https://github.com/slive777/OpenAver/releases)
> 看版號，把上面的 `$LATEST` 換成 `v0.13.14` 這種寫法即可。
>
> 也可以改用 `git clone` ——但那樣預設會停在 `main`，也就是**開發中的版本**（隨時可能半完成、
> 沒過發布驗收）。用 git 的話記得補一行切到正式版：
> `git checkout "$(git tag -l 'v[0-9]*' --sort=-v:refname | head -1)"`。
> 這份文件用原始碼壓縮檔，是因為不需要裝 git，升級也只是把同一行指令再跑一次。

**為什麼要 `grep -v '^pywebview'`**：`pywebview` 是桌面版拿來開應用程式視窗用的，
在沒有圖形環境的機器上既裝不起來也用不到。OpenAver 的伺服器端程式碼**完全沒有 import 它**，
排除掉不影響任何功能。

> ℹ️ 這份文件描述的網頁版資料夾選擇彈窗**需要 v0.14.8 以上**。更舊的版本在瀏覽器裡
> 按「加資料夾」不會有反應——那時候那顆鈕還是桌面版限定的。

---

## 2. 開啟伺服器模式（只需做一次）

**這步不能跳過。** OpenAver 預設只接受本機連線——不開伺服器模式的話，
同網段其他裝置連進來一律拿到 `403 Forbidden`，連登入畫面都看不到。

```bash
venv/bin/python -c "from core.config import mutate_config; mutate_config(lambda c: c.setdefault('general', {}).__setitem__('server_mode', True))"
```

這行會建立／更新 `web/config.json`。之後想關掉，把 `True` 改成 `False` 再跑一次即可。

> 🔒 **開啟之前務必看完這段。**
>
> 伺服器模式的門禁只分兩種來源：**本機**，以及**其他所有人**。
> 開啟之後，凡是連得到這台機器的 `8000` port 的裝置**一律放行**——
> 它**不會**去檢查對方是不是真的在你家網段內。家裡的智慧電視、訪客的手機、
> 室友的筆電都算；而如果這個 port 從網際網路連得到，**那就是全世界都算**。
>
> 所以：
>
> - **不要**把 `8000` port 轉發（port forward）到網際網路上
> - **不要**架在有公網 IP 的雲端主機上
> - 真的需要在外面看，請走 **Tailscale／WireGuard／Zero Trust** 這類把裝置拉進私有網路的方式，
>   而不是把服務開到公網
> - 家裡有人共用網路的話，連進去之後在「設定 → 區網存取」設一組 4 位數 PIN
>   （**預設是關閉的**，不設就等於沒有密碼）

---

## 3. 查出區網網址

```bash
venv/bin/python -c "from web.lan_listener import get_lan_ip; ip = get_lan_ip(); print('http://%s:8000' % ip if ip else '查不到，改用下面的備援做法')"
```

印出來的就是等一下要在別台裝置的瀏覽器打的網址，例如 `http://192.168.1.100:8000`。

**如果它說「查不到」**：這個查法是靠系統的預設路由反推的，
機器沒有對外預設路由時（純內網、沒接網際網路的環境）就會查不到。改用系統指令：

```bash
hostname -I
```

它會把這台機器所有的位址一次列出來，例如 `192.168.1.100 172.17.0.1`——
**挑那個跟你其他裝置同網段的**（通常是 `192.168.x.x` 或 `10.x.x.x` 開頭那個）。
`172.17.x.x` 通常是 Docker 的虛擬網卡，不是你要的。真的分不出來就去路由器的
裝置清單看這台機器被分到哪個 IP。

---

## 4. 啟動

```bash
venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8000
```

這是**前景執行**——關掉終端機或中斷 SSH，它就停了。
要它開機自動起來、斷線也不停，見下方〈選配：開機自動啟動〉。

`--port` 想換成別的數字都可以，記得第 3 步印出的網址要跟著改。

---

## 5. 升級 / 安裝指定版本

**就是把第 1 步的下載指令再跑一次**，蓋在原本的目錄上：

```bash
LATEST=$(curl -fsSL https://api.github.com/repos/slive777/OpenAver/releases/latest \
         | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)

cd ~/OpenAver
curl -fsSL "https://github.com/slive777/OpenAver/archive/refs/tags/$LATEST.tar.gz" \
  | tar xz --strip-components=1

grep -v '^pywebview' requirements.txt > /tmp/openaver-req.txt
venv/bin/pip install -r /tmp/openaver-req.txt
```

改完重啟伺服器（前景執行的按 `Ctrl-C` 再跑一次第 4 步；systemd 的話 `sudo systemctl restart openaver`）。

想**退回舊版**或裝特定版本，把 `$LATEST` 換成版號即可，例如 `v0.13.14`——
同一個目錄直接覆蓋回去就好，設定與資料庫一樣不受影響。

> ℹ️ 覆蓋升級只會蓋掉同名檔案，**不會刪掉舊版留下、新版已經移除的檔案**。
> 那些檔案沒有任何程式碼會去載入它們，放著不影響運作；真的想要一份乾乾淨淨的，
> 就解壓到新目錄，再把舊的 `web/config.json` 與 `output/` 搬過去。

**這裡沒有「一鍵更新」按鈕。** 設定頁上那顆更新鈕只在桌面版有作用，
從瀏覽器按它會得到 403——那是刻意的安全護欄，不是壞掉。伺服器要升級就是重跑上面這段。

你的**設定與資料庫不會被動到**：`web/config.json` 和 `output/`（資料庫、封面、縮圖都在裡面）
不在原始碼壓縮檔裡，覆蓋解壓不會碰到它們。

---

## 6. 忘記密碼 / 被鎖在外面

輸錯太多次 PIN 會觸發逐步拉長的鎖定（最長一小時）。不想等、或根本忘了密碼，
**在伺服器本機**跑這行：

```bash
venv/bin/python -c "from core.access_auth import set_auth; set_auth(enabled=False, pin='')"
```

密碼保護會被關掉、鎖定會被解除、所有已登入的裝置一併登出。

> ⚠️ **跑完一定要重啟伺服器**，否則沒有效果。
> 執行中的伺服器把密碼設定快取在記憶體裡，不會發現另一個行程改了資料庫——
> 指令跑完看起來成功了，瀏覽器卻還是擋在登入畫面。這不是指令失敗，是還沒重新讀取。

---

## 選配：開機自動啟動（systemd）

第 4 步的前景執行只適合先試跑。要它長期活著，建一個 systemd unit：

```bash
sudo tee /etc/systemd/system/openaver.service > /dev/null <<'EOF'
[Unit]
Description=OpenAver
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=CHANGE_ME
WorkingDirectory=/home/CHANGE_ME/OpenAver
ExecStart=/home/CHANGE_ME/OpenAver/venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now openaver
```

三個 `CHANGE_ME` 換成你的使用者名稱（`whoami` 印得出來），路徑也照實際位置改。
**`User=` 要填「讀得到你的影片資料夾」的那個使用者**——填 `root` 雖然一定讀得到，
但 OpenAver 會用它的身分寫 NFO 與封面到你的片庫裡，之後你自己的帳號可能反而改不動那些檔案。

看狀態與日誌：

```bash
systemctl status openaver
journalctl -u openaver -f
```

---

## Docker（實驗性）

> **先說結論：不想折騰的話，別用這段。**
> 上面的 CLI 安裝功能完全一樣，而且步驟更少。
> **官方 Docker image 已在規劃中**——等它出來再用，是完全合理的選擇。

**在 NAS 上未驗證，僅供參考。** 下面這份設定在 **x86_64 Linux + Docker 29** 上實際建置並
執行過（網頁開得起來、設定存得進去），但**沒有**在 Synology／QNAP／樹莓派這類目標 NAS
環境上跑過，也沒有長期使用的驗證。路徑、UID、port 都要照你的環境改。

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN grep -v '^pywebview' requirements.txt > /tmp/req-server.txt \
 && pip install --no-cache-dir -r /tmp/req-server.txt \
 && rm /tmp/req-server.txt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

同一層放一份 `.dockerignore`，否則 `COPY . .` 會把 `venv/`、`output/`、`.git/` 一起塞進 image：

```
.git
venv
output
node_modules
tests
```

### docker-compose.yml

```yaml
services:
  openaver:
    build: .
    ports:
      - "8000:8000"
    # 換成你自己的：id -u 與 id -g 印出來的數字。理由見下方〈UID/GID〉
    user: "1000:1000"
    environment:
      # 不能省，理由見下方〈為什麼要設 HOME〉
      - HOME=/app
    volumes:
      # 整個專案目錄掛進去，不是只掛設定檔。理由見下方〈為什麼掛整個目錄〉
      - ./:/app
      # 你的片庫（左邊換成實際路徑；右邊那個路徑就是你在 OpenAver 裡會看到的路徑）
      - /srv/media/av:/media/av
    restart: unless-stopped
```

### 啟動

```bash
LATEST=$(curl -fsSL https://api.github.com/repos/slive777/OpenAver/releases/latest \
         | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)

mkdir -p ~/OpenAver && cd ~/OpenAver
curl -fsSL "https://github.com/slive777/OpenAver/archive/refs/tags/$LATEST.tar.gz" \
  | tar xz --strip-components=1

# 把上面三份檔案（Dockerfile / .dockerignore / docker-compose.yml）放進這個目錄，然後：
echo '{"general": {"server_mode": true}}' > web/config.json
docker compose up -d --build
```

**`server_mode` 必須先開。** 從 host 或別台裝置連進容器時，來源位址是 Docker 的橋接網段
（`172.17.0.1` 之類，不是 loopback），沒開伺服器模式一律 `403 Forbidden`——實測如此。

### 升級

程式碼是從 host 掛進去的，所以升級不必重建 image：

```bash
LATEST=$(curl -fsSL https://api.github.com/repos/slive777/OpenAver/releases/latest \
         | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)

cd ~/OpenAver
curl -fsSL "https://github.com/slive777/OpenAver/archive/refs/tags/$LATEST.tar.gz" \
  | tar xz --strip-components=1
docker compose restart
```

你自己寫的 `Dockerfile`、`.dockerignore`、`docker-compose.yml` 不在壓縮檔裡，覆蓋解壓不會蓋掉它們。

只有 `requirements.txt` 有變動時才需要 `docker compose up -d --build`。

### 為什麼掛整個目錄，不是只掛設定檔

直覺上會想寫 `- ./data/config.json:/app/web/config.json` 只掛一個檔案。**那樣會壞。**

OpenAver 存設定用的是「先寫暫存檔再 `os.replace` 換過去」的原子寫入，
而 Docker 的單一檔案 bind mount 擋掉 `os.replace`，實測噴：

```
OSError: [Errno 16] Device or resource busy: '/app/web/tmpXXXX.tmp' -> '/app/web/config.json'
```

症狀是**網頁直接 500**，不是「設定沒存到」這種好認的樣子。
把整個專案目錄掛進去，`config.json` 就是目錄裡的普通檔案，這個問題不存在，
資料庫（`output/`）也一併留在 host 上。

### 為什麼要設 HOME

OpenAver 的日誌寫在 `~/OpenAver/logs/`。而 `user:` 指定一個容器內 `/etc/passwd` 沒有的
UID 時，`HOME` 會變成 `/`，程式一啟動就想在根目錄建資料夾：

```
PermissionError: [Errno 13] Permission denied: '/OpenAver'
```

容器**連起都起不來**。設 `HOME=/app` 之後日誌會落在專案目錄下的 `OpenAver/logs/debug.log`。

### UID/GID：容器化自架媒體庫最常見的隱形雷

比路徑掛錯更難查的是權限。host 端資料夾的擁有者，跟容器內執行程式的使用者 UID/GID 對不上時：

- **讀不了** → 掃描跑完「找到 0 部影片」，但路徑明明是對的
- **寫不了** → 掃到了，但 NFO 和封面存不進去，或整理／改名靜默失敗

兩種都很像「路徑掛錯」，成因卻完全不同。

**反過來也一樣糟：不設 `user:` 的話容器用 root 跑**，它寫出來的 `config.json`、資料庫、
還有寫進你片庫的 NFO 與封面**全部變成 root 所有**——你自己的帳號從此改不動那些檔案，
得 `sudo chown` 才救得回來。這是實測踩到的，不是假設。

做法是先查出你自己與片庫資料夾的 UID/GID：

```bash
id -u; id -g                      # 你自己
stat -c '%u:%g' /srv/media/av     # 片庫資料夾的擁有者
```

兩邊一致的話，把那組數字填進 compose 的 `user:` 就好。不一致的話，
填的那個 UID 必須對片庫資料夾有讀取權限（要 OpenAver 寫 NFO／封面的話還要寫入權限），
專案目錄本身也一樣。

---

## 遇到問題

- **連不進去、瀏覽器顯示無法連線** → 檢查防火牆（`sudo ufw allow 8000/tcp`），
  以及第 4 步是不是用了 `--host 0.0.0.0`（用 `127.0.0.1` 只有本機連得到）
- **連得到但顯示 `Forbidden`** → 第 2 步的伺服器模式沒開（這項改完立即生效，不用重啟）
- **一直停在登入畫面** → 見上方第 6 節，注意「跑完要重啟」
- **其他** → 日誌在 `~/OpenAver/logs/debug.log`（Docker 是專案目錄下的 `OpenAver/logs/debug.log`）；開 issue 時附上就好查很多

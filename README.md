# SIT-Web

以 Flask Application Factory 與 Vite、React、TypeScript 建立的 Discord 社群網站。後端負責登入、身份驗證、星之碎片帳本及遊戲結算；前端負責頁面、互動與動畫。

## 本地開發

請在 WSL 的專案根目錄執行，勿與 Windows 下的另一份專案或虛擬環境混用。需要 Python 3.14.7、Node.js 24 LTS 與 npm。

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python --version
pip install -r backend/requirements.txt
cp .env.example .env
cd frontend
npm ci
cd ..
./dev_run
```

若使用專案內的 Node.js，先執行 `export PATH="$PWD/.tools/node/bin:$PATH"`。已有 `.venv` 時直接啟用即可，不必重新建立。

前端預設為 `http://localhost:5173`，後端為 `http://localhost:5000`。Vite 將 `/api` 代理至後端，前端不必寫死 API 主機。`Ctrl+C` 可停止前後端；啟動前請確認這兩個連接埠未被其他程式占用。

也可分別在兩個終端執行：

```bash
# 專案根目錄，啟用虛擬環境後
cd backend
flask --app wsgi run --debug
```

```bash
# 專案根目錄
cd frontend
npm run dev
```

## 程式架構

| 路徑 | 中文說明 |
| --- | --- |
| `backend/app/__init__.py` | Application Factory，建立 Flask 應用程式與註冊路由 |
| `backend/app/api/` | HTTP 邊界，處理登入狀態、權限、CSRF、輸入與回應 |
| `backend/app/models/` | 領域物件、資料存取及交易規則，並非 ORM 模型集合 |
| `backend/app/services/` | 服務組合、Discord、OAuth、管理查閱等功能 |
| `backend/app/sql/` | SQLManager 與 SQLSession，管理連線及提交、回滾 |
| `backend/tests/` | 後端自動測試 |
| `frontend/src/` | React 頁面、元件、API 呼叫、型別與資源 |
| `nginx/` | 正式環境的前端與 API 反向代理設定 |
| `.github/workflows/` | 分開打包前後端，再部署至 GCP 的工作流程 |
| `docs/` | 各功能規則、部署與維運文件 |

後端採組合式 OOP：`ApplicationServices` 注入資料庫與設定，各服務負責自己的業務；交易內物件只在該交易期間使用。純計算函式及 Flask 路由仍保留函式形式，不為物件化而加入無必要的繼承。詳見[後端物件架構](docs/backend-architecture.md)。

## 登入與資料儲存

Discord OAuth 設定請參照 `.env.example`，設定 Client ID、Client Secret、Bot Token 與回呼網址。開發回呼使用 `http://localhost:5173/api/auth/discord/callback`，正式環境使用 `https://sit-web.sytes.net/api/auth/discord/callback`；兩者須分別加入 Discord 應用程式允許的回呼網址。

`SECRET_KEY` 必須使用安全隨機值，正式環境不可使用範例值。HTTP 開發環境與 HTTPS 正式環境需使用對應的 `SESSION_COOKIE_SECURE` 設定。

登入時會確認使用者的 Discord 群組身份。詳細資料與身份組存於 `member`；`login_sessions` 透過 `userId` 對應成員，登入有效期為七天。離開群組不刪除歷史成員與帳本資料。管理功能仍須通過後端權限檢查，不能只依賴前端隱藏入口。

本地資料預設存於 `storage/`，包括 SQLite 資料庫與 Discord JSON 快取；Docker 使用掛載的持久化儲存。請備份資料庫及持久化資料，勿把 `.env`、Token、私人資料或日誌提交至 Git。

## 測試與打包

```bash
# 在專案根目錄，啟用虛擬環境後
cd backend
python -m unittest discover -s tests
```

```bash
# 在 frontend 目錄
npm run lint
npm run build
```

前端建置輸出於 `frontend/dist/`。本地驗證 API 時應經由 Vite `/api` 代理，登入與 Cookie 請一致使用同一個主機名稱，不要混用 `localhost` 與 `127.0.0.1`。

## 正式部署

正式後端使用 Gunicorn，不使用 Flask debug server：

```bash
# 在 backend 目錄，先提供正式環境變數
gunicorn --workers 2 --bind 0.0.0.0:8000 wsgi:app
```

Docker 可在根目錄執行 `docker compose up --build -d`。GitHub Actions 由 `release/*` 標籤觸發，前端打包、後端打包與 GCP 部署分別使用不同 YAML，部署等待兩個打包工作完成。HTTPS、憑證自動更新與 VM 設定請依下方文件操作。

## 中文文件

- [後端物件架構與開發方式](docs/backend-architecture.md)
- [前端開發](frontend/README.md)
- [管理工具、身份與快取](ADMINISTRATION.md)
- [星之碎片帳本與轉帳](docs/star-shards.md)
- [每日轉盤與重置時間](docs/daily-spinner.md)
- [21 點規則與共享牌靴](docs/blackjack.md)
- [預測盤與結算](docs/predictions.md)
- [Discord 邀請紀錄](docs/invitations.md)
- [UUID 紀錄識別碼](docs/record-ids.md)
- [後端日誌與輪替](docs/logging.md)
- [GitHub Actions 與 GCP 部署](docs/deployment.md)
- [HTTPS 與憑證更新](docs/https.md)

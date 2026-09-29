# Discord 邀請選項與點擊紀錄

首頁「加入 Discord」會開啟邀請視窗，選項、描述與停用狀態由 SQLite 即時讀取。
正規成員需輸入目前 Discord 管理員的 **username**（不是顯示名稱或群組暱稱）。

## 資料表

第一次讀取 `GET /api/invitations` 或執行管理指令時自動建立：

| `invitation_url` 欄位 | 用途 |
| --- | --- |
| `code` | Discord 邀請網址最後一段，不保存完整 URL，需唯一 |
| `role` | 主鍵：訪客、一般成員、正規成員 |
| `description` | 視窗中顯示的描述 |
| `isExpired` | 0 可使用；1 停用並禁止開啟 |

僅首次建立資料表時填入三筆初始設定：`rnTHPNfjMx`、`HgtKZUX72K`、`UDNkUgQ4Yy`。
前端沒有寫死這些 code。之後修改、停用或刪除資料，不會被下次請求或 release 恢復成預設值。
`isExpired` 是本地管理狀態，並非定期向 Discord 自動偵測有效性；實際失效時可更新 code 或標記停用。

| `invitation_record` 欄位 | 用途 |
| --- | --- |
| `id` | UUID4 點擊紀錄 ID |
| `requestId` | 本次操作 UUID；同一次網路重試不重複計數 |
| `visitorId` | 瀏覽器 session 的隨機識別碼，不是 Discord 使用者 ID |
| `invitationCode` | 點擊當下的邀請 code 快照 |
| `role` | 點擊時選擇的加入類型 |
| `administratorId` | 正規成員代碼對應的 Discord 管理員 ID；其他類型為 NULL |
| `administratorUsername` | 點擊當下該管理員的 username；其他類型為 NULL |
| `clickedAt` | 點擊紀錄寫入時間，Unix 秒 |
| `eventType` | 固定為 `click`，不代表已加入群組 |

歷史紀錄使用快照，不會隨邀請網址更換或管理員改名而變動。紀錄不包含 IP、Discord access token 或實際入群狀態。
新的一次按下「前往 Discord」算另一筆點擊；同一操作的網路重試使用相同 `requestId`。
寫入失敗、邀請停用或代碼驗證失敗，不回傳邀請網址。

欄位統一採 camelCase。既有 snake_case 欄位會在更新版本後首次讀取邀請或執行管理指令時，
於同一交易中自動更名，保留歷史資料、唯一限制與檢查限制；可重複執行。
這僅調整資料庫欄位，API 請求的 `request_id` 等參數維持原格式。

## 管理員代碼

後端使用 Bot 即時讀取群組成員，確認該 username 擁有 `DISCORD_ADMIN_ROLE_IDS` 中的任一身分組。
目前使用管理員列表既有身分組 `513295891482804250`，排除 Bot 與尚未完成成員審核者。
Bot 須已加入群組、設定 `DISCORD_BOT_TOKEN`，並啟用 Server Members Intent。驗證不使用一天的公開成員快取。

username 是**推薦來源代碼，不是機密密碼或單次授權碼**。取得共用 Discord 邀請網址的人仍可直接分享網址，繞過網站的代碼輸入。
此功能只驗證網站操作並記錄點擊，不能證明誰實際入群，也不會自動授予 Discord 身分組。

## 更換網址或描述

在本機 WSL 專案根目錄執行，例如更換一般成員邀請（將 `NEW_CODE` 換成真實 code）：

```bash
cd backend
../.venv/bin/python -m flask --app wsgi invitations set \
  --role 一般成員 --code NEW_CODE --active
```

可加 `--description '新的描述'`。使用 `--expired` 停用、`--active` 恢復；每次指令都需指定目前要使用的 code。

在 GCP VM 上直接修改正式資料庫：

```bash
cd ~/sit-web
docker compose -p sit-web --env-file .env --env-file images.env \
  -f compose.production.yaml exec backend \
  flask --app wsgi invitations set --role 一般成員 --code NEW_CODE --active
```

指令不需重新部署映像；重新開啟邀請視窗即可讀取新設定。若視窗已開啟，送出時仍會重新檢查資料庫中的 code 與停用狀態。
資料保存在既有 `storage/database/sit.sqlite3` 與正式環境的 storage volume。

## Discord 邀請設定

- 訪客的離線自動退出行為，需在 Discord 邀請啟用 **Grant temporary membership**；已分配身分組的成員不會因這個設定而自動退出。網站登出不會主動踢除 Discord 成員。
- 一般成員與正規成員的身分組分配及授權，需由 Discord 的管理流程或 Bot 實作；此變更不包含自動授予權限。
- 視窗固定附註：「若邀請連結失效，請聯繫 discord/@lightinvi」。

[Discord 官方邀請設定說明](https://support.discord.com/hc/en-us/articles/208866998-Invites-101)

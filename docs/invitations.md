# Discord 邀請選項與點擊紀錄

首頁「加入 Discord」會開啟邀請視窗，選項、描述與停用狀態由後端設定提供。
正規成員需輸入目前 Discord 管理員的 **username**（不是顯示名稱或群組暱稱）。

## 動態邀請

後端以 `DISCORD_BOT_TOKEN` 呼叫 `POST https://discord.com/api/v10/channels/{channel_id}/invites`。
每次新操作設定 `max_age=600`、`max_uses=1`、`unique=true`。

| 加入類型 | channel_id | 設定 |
| --- | --- | --- |
| 訪客 | 1554311970226704444 | temporary=true，不指定角色 |
| 一般成員 | 751099765940289596 | temporary=false，role_ids=[578156037589172244] |
| 正規成員 | 578156795667808276 | temporary=false，role_ids=[749803225275695156] |

Bot 需要各頻道的建立邀請權限；賦予角色另需 Manage Roles，且 Bot 必須有權管理目標角色。
Discord 接受邀請時會依 `role_ids` 賦予角色，無須額外追蹤入群事件。
參數依據 [Discord 官方 API 文件](https://docs.discord.com/developers/resources/channel#create-channel-invite)。

首次存取邀請 API 時自動移除舊的 `invitation_url` 表，保留 `invitation_record` 歷史。
原本 `flask invitations set` 指令已移除；頻道、角色及描述設定於 `backend/app/models/invitation.py`。

## 資料表

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
寫入失敗、Discord API 失敗或代碼驗證失敗，不回傳邀請網址。

欄位統一採 camelCase。既有 snake_case 欄位會在更新版本後首次讀取邀請時，
於同一交易中自動更名，保留歷史資料、唯一限制與檢查限制；可重複執行。
這僅調整資料庫欄位，API 請求的 `request_id` 等參數維持原格式。

## 管理員代碼

後端使用 Bot 即時讀取群組成員，確認該 username 擁有 `DISCORD_ADMIN_ROLE_IDS` 中的任一身分組。
目前使用管理員列表既有身分組 `513295891482804250`，排除 Bot 與尚未完成成員審核者。
Bot 須已加入群組、設定 `DISCORD_BOT_TOKEN`，並啟用 Server Members Intent。驗證不使用一天的公開成員快取。

username 是推薦來源代碼，不是機密密碼或單次授權碼。連結限用一次，但持有連結的人仍可轉交他人。
點擊紀錄不代表實際入群；角色由 Discord 在接受邀請時授予。

## 重試與臨時成員

同一瀏覽器的相同 `requestId` 在 10 分鐘內沿用原邀請，不重新生成或增加紀錄。
過期重試回傳 410，需關閉視窗再取得新連結；已使用的連結由 Discord 拒絕再次接受。
並行重試在資料庫寫入鎖中序列化，確保只建立一筆紀錄。
若 API 已建立邀請但資料庫寫入失敗，網址不會提供給前端，未提供的邀請會自行在 10 分鐘後失效。

訪客設定為 Discord 臨時成員；如果其他 Bot 或管理員另外賦予角色，可能轉為永久成員。
網站登出不會主動踢除 Discord 成員。

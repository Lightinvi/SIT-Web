# 每日轉盤

登入後首頁顯示「介紹」與「每日轉盤」。介紹可於同一首頁展開，並返回功能選項。
首頁網格預留桌面 2 列 × 4 欄、手機 4 列 × 2 欄，其餘位置只保留 CSS 空間，不渲染佔位元素。
轉盤頁面：`/daily-spinner`。

## 獎勵與重置

每日依 **後端系統時區的 00:00** 重置，每位成員每日一次；不是距離上次抽獎 24 小時。
Compose 將 VM 的 `/etc/localtime` 唯讀掛載到後端容器，讓日期判定沿用主機設定，不需要 cron 清空資料。
直接執行 Flask 時沿用該程序的系統時區（若設定 `TZ` 則以該設定為準）。
前端將 `nextResetAt` 與領獎的 `createdAt` Unix 秒數轉成瀏覽器時區顯示，倒數仍以伺服器時間為準。
支援日光節約時間，重置間隔可能為 23 或 25 小時。

VM 的地理位置不會用來推算時區。部署前以 `timedatectl` 確認主機設定；若希望使用奧勒岡州當地時間，
可在 VM 執行 `sudo timedatectl set-timezone America/Los_Angeles`，再重新建立後端容器以重新載入掛載的時區檔案。
若主機仍設定 UTC，就會於 UTC 00:00 重置。此修改不會自動變更 VM 時區。
切換既有服務的時區會改變每日資格邊界；歷史 `spinDate` 不重寫，切換當天可能提早或延後下一次可領獎時間。
基礎獎勵 10 星之碎片，沒有參加費。

| 倍率 | 獎勵 | 機率 |
| --- | --- | --- |
| 0.5x | 5 | 8% |
| 1x | 10 | 65% |
| 2x | 20 | 12% |
| 2.5x | 25 | 11% |
| 5x | 50 | 4% |

後端使用 `secrets.randbelow(100)`，以整數權重決定結果。前端依照伺服器结果播放動畫，不決定獎勵。
轉盤扇區等分以保持標籤可讀性，頁面明確標示實際機率以上表為準。

## daily_spinner

| 欄位 | 用途 |
| --- | --- |
| `id` | UUID4 唯一紀錄 ID |
| `userId` | Discord 成員 ID |
| `spinDate` | 後端系統時區日期 YYYY-MM-DD，僅用於資格判斷 |
| `requestId` | 請求 UUID，供網路重試辨識 |
| `multiplier` | 本次倍率快照 |
| `baseReward` | 基礎獎勵 10 |
| `reward` | 本次實際發放數量 |
| `createdAt` | Unix 秒數 |

`UNIQUE(userId, spinDate)` 防止一天多次抽獎；`UNIQUE(userId, requestId)` 防止跨午夜重試被當作新的抽獎。
紀錄只新增，不刪除或改寫。重複請求回傳已存在結果，`awarded=false`，不再次發獎。

轉盤紀錄與 `star_shard` 獎勵在同一個 `BEGIN IMMEDIATE` 交易完成。
入帳設定 `transactionType='daily_spinner'`，`transactionSource=str(daily_spinner.id)`。
任何一方寫入失敗都回滾，餘額超過上限也不消耗抽獎次數。

## API 與前端

- `GET /api/daily-spinner`：公開機率、重置時間；登入者額外取得自己的今日結果、資格與 CSRF token。
- `POST /api/daily-spinner/spin`：登入與 CSRF 驗證，JSON `{ "requestId": "UUID" }`；忽略客戶端提供的身分、日期或獎勵。
- 回應不快取。前端於午夜或視窗重新取得焦點時更新資格，獎勵成功後重新讀取導覽列餘額。
- 不確定的請求 UUID 暫存於該分頁的 sessionStorage，重新開頁可確認既有結果；減少動態效果設定會略過旋轉動畫。
- 使用 [spin-wheel](https://github.com/CrazyTim/spin-wheel) 的 `spinToItem` 播放後端指定結果。

部署後首次存取登入狀態或抽獎 API 自動建立表格，沿用原有 SQLite 持久化 volume。

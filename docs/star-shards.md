# 星之碎片 Star Shard

`star_shard` 為只新增、不修改或刪除的帳本。欄位依需求保留 `beforeBlance`、`afterBlance` 的拼字。
`id` 為 UUID4 字串，`userId` 為 Discord ID 字串；`amount` 為帶正負號的整數。
每筆包含 `transactionType`、`transactionSource`、`description` 與 Unix 秒數 `createdAt`。
餘額依 `userId` 查詢最大內部 `sequence` 那一筆的 `afterBlance`，沒有紀錄時為 0。
`sequence` 僅用於提交順序，不作為識別碼或對外引用；API 不回傳此欄位。
分頁 `before` 與 `nextCursor` 使用 UUID，由後端解析成該帳號紀錄的排序位置。
不可用 UUID 大小或時間戳單獨判斷最新餘額。

## 轉帳

- 登入後可搜尋 `member` 中的其他使用者，每次搜尋最多 50 筆；可依名稱或完整 ID 縮小結果。
- 給予必須輸入正整數，並在第二步確認；不收手續費，不允許負餘額。
- 扣款與入帳在同一個 SQLite `BEGIN IMMEDIATE` 交易完成，失敗時全部回滾。
- 雙方 `transactionType` 都是 `transaction`。給予者的來源是接收者 ID，接收者的來源是給予者 ID。
- 輔助表 `star_shard_request` 保存請求 UUID 與雙方紀錄 ID，防止重試造成重複扣款；同一 UUID 不能更換對象或數量。
- 伺服器依登入 session 決定給予者，不接受客戶端指定自己的 ID 或餘額；寫入需 CSRF token。
- 單筆與總餘額上限為 JavaScript 安全整數 `9007199254740991`。

## API

全部需要有效登入，且回應不快取。

| 路徑 | 用途 |
| --- | --- |
| `GET /api/star-shards/balance` | 自己目前餘額 |
| `GET /api/star-shards/records?before=ID` | 自己紀錄，每頁 20 筆，回傳 `nextCursor` |
| `GET /api/star-shards/members?q=名稱` | 搜尋可給予的成員，排除自己 |
| `POST /api/star-shards/transfer` | `recipientId`、`amount`、`requestId`，搭配 `X-CSRF-Token` |

## 系統獎勵

不自動發放初始代幣，也不開放公開加值 API。[每日轉盤](daily-spinner.md) 已提供每日獎勵。
其他獎勵或遊戲服務可在
`db.transaction(immediate=True)` 內呼叫 `ensure_schema(tx)`、
`append_entry(tx, user_id, amount, transaction_type, source, description)`。
該功能需自行檢查權限與事件唯一性，`source` 放該獎勵或遊戲事件 ID。
錯誤交易應追加補償紀錄，不直接改歷史帳本。

資料表於首次使用 API 自動建立，沿用既有 SQLite 持久化路徑與 Docker volume。
舊整數 ID 的遷移與部署注意事項見 [UUID 紀錄識別碼](record-ids.md)。
前端使用既有 `frontend/src/assets/star_shard.png`；餘額在給予成功、視窗重新取得焦點或每分鐘更新。

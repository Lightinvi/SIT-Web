# UUID 紀錄識別碼

業務紀錄的主鍵統一由 Python `uuid.uuid4()` 產生並儲存為 TEXT，不再使用各表獨立的整數流水號：

- `daily_spinner.id`
- `star_shard.id`
- `invitation_record.id`

UUID 為跨表、跨程序獨立產生的隨機識別碼，碰撞機率極低；資料表主鍵限制會拒絕重複值。
新增其他業務紀錄時使用 `app.models.record_ids.new_record_id()`，不可把 SQL helper 回傳的 `lastrowid` 當作業務 ID。

`star_shard.transactionSource` 在 `transactionType='daily_spinner'` 時保存該次轉盤 UUID。
轉帳收據的 `debitId`、`creditId` 保存兩筆 `star_shard` UUID，外鍵關係保留。
來源仍需搭配 `transactionType` 解讀，UUID 本身不包含來源類型。

## 保留原值的識別碼

- Discord `userId`、`administratorId`、群組與身分組 ID：外部服務提供，不可重新產生。
- OAuth state 和登入 session 的 `id`：已是安全隨機 token 的 SHA-256 摘要，不是流水號；保留現有安全設計與有效登入。
- `requestId`：已由客戶端產生 UUID，保持原值以維持重試去重。
- `visitorId`：既有隨機瀏覽器識別碼，不改變既有點擊歸屬。
- 示範 `/api/users` 不是持久化資料表，不納入本次資料庫遷移。

## 既有資料遷移

任何邀請或星之碎片功能首次初始化時，會在同一個 `BEGIN IMMEDIATE` 交易中同步遷移相關舊表：

1. 為舊整數 ID 建立 UUID 對照。
2. 重建業務表，保留數量、餘額、時間、角色與請求識別碼。
3. 更新已知類型的 `transactionSource` 與转帳收據引用。
4. 恢復唯一限制、外鍵、查詢索引及只新增的保護觸發器。

任一步驟失敗會整筆回滾；再次執行不會重新更換 UUID。未知外鍵或無法解析的引用會阻止遷移，避免猜測造成資料錯配。
`star_shard.sequence` 保留歷史提交順序，新資料在寫入鎖內遞增，不以 UUID 字典序或可能相同的時間戳排序。

部署前請備份 SQLite，並確保舊版後端 worker 已停止，不能讓整數 ID 與 UUID 版本同時操作同一資料庫。
重新載入前端以清除舊整數分頁游標。外部自行保存的舊流水號不能再用於查詢；本次只更新程式已知的資料庫引用。
不會刪除會員、重發轉盤獎勵、重複轉帳或重建邀請點擊。

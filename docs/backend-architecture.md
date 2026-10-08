# 後端物件架構

Flask application factory 為每個應用程式建立獨立的 `ApplicationServices`，註冊於 `app.extensions['services']`。服務持有明確注入的 SQLManager 或設定，不持有跨請求共用的交易、使用者或牌局狀態。

## 責任分工

| 層次 | 物件 | 責任 |
| --- | --- | --- |
| 基礎設施 | SQLManager、SQLSession、DiscordService | 連線、交易、Discord 存取及快取 |
| 帳本 | ShardLedger、RecordSchemaManager、MemberProfileStore | 單次交易內的餘額、入帳驗證、UUID 遷移與成員資料 |
| 碎片業務 | ShardTransferService、ShardGrantService | 原子轉讓、系統發放及冪等憑證 |
| 每日轉盤 | DailySpinnerService、SpinnerRepository | 抽獎交易、派款及每日資格查詢 |
| 21 點 | BlackjackService、BlackjackRound、BlackjackShoe、BlackjackRepository | 命令、牌局狀態、共享牌靴及隱藏暗牌的檢視 |
| 預測盤 | PredictionService、PredictionRepository | 管理與押注操作、原子結算及本人資料檢視 |
| 邀請 | InvitationService | 邀請重用、動態產生及點擊歸屬 |
| 身份 | OAuthService、MemberRepository | 即時 OAuth 身份驗證與權威個人資料 |
| 管理查閱 | DatabaseReader、LogReader | 有界資料庫搜尋與簽章日誌快照 |

API 路由保留 Flask Blueprint 的函式形式，負責 HTTP、session、CSRF 與即時身份檢查，再委派服務執行業務操作。路由驗證不代表可忽略服務內的金額、版本或狀態約束。

純粹的規則計算與工具，例如文字驗證、最高身份映射、UUID 產生、手牌點數與比例分配，仍保留函式形式。物件透過組合協作，不使用無必要的繼承層級。

## 交易與生命週期

服務物件可在應用程式生命週期內重用。帶有 `tx` 的物件只可在建立它的 `with db.transaction(...)` 區塊內使用；不得在提交、回滾或關閉連線後繼續存取。失敗操作的記憶體牌局狀態必須丟棄，僅以重新讀取的資料庫紀錄作為下次操作基礎。

```python
from app.models.star_shard import ShardLedger

# app 為 create_app() 建立的 Flask 實例；其餘參數須先完成驗證。
services = app.extensions['services']
result = services.shards.transfer(sender, recipient, amount, request_id)

with app.extensions['sql'].transaction(immediate=True) as tx:
    ledger = ShardLedger(tx)
    ledger.ensure_schema()
    current_balance = ledger.balance(user_id)
```

既有公開函式暫時保留為相容轉接介面，實際實作位於物件方法。舊測試與外部呼叫者可繼續使用，新業務程式優先透過服務物件呼叫。API 網址、資料表欄位、身份組與派款規則不因本次重構而更動。

所有新增方法仍使用英文描述、中文描述、Args、Returns、必要的 Exceptions 及 Example 文件格式。

## 服務入口

在 Flask 路由中，透過 `current_app.extensions['services']` 取得目前應用程式的服務，不建立跨應用程式的全域單例。

| 屬性 | 使用方式與責任 |
| --- | --- |
| `members` | `get_member(user_id)`，查詢成員詳細資料 |
| `shards` | `transfer(...)`，處理星之碎片轉帳 |
| `grants` | `grant(...)`，處理管理員系統發放 |
| `spinner` | `spin(...)`，執行每日轉盤與派款 |
| `blackjack` | `play(...)`，處理 21 點遊戲命令 |
| `predictions` | `execute(...)`，處理預測盤操作 |
| `invitations` | `record_click(...)`，處理邀請與點擊紀錄 |
| `database` | `table_page(...)`，唯讀搜尋與分頁 |
| `oauth` | `authenticate(code)`，交換 OAuth 授權並驗證身份 |
| `logs` | `log_page(...)`，依目前日誌設定建立讀取物件 |

上表的 `...` 表示省略參數，不是可直接執行的呼叫範例；完整參數、回傳值與例外請參閱各方法 docstring。轉帳、發放及遊戲呼叫會實際修改資料，開發時應使用測試資料庫。

## OOP 設計原則

- **封裝**：帳本驗證、牌靴抽牌、牌局推進及預測結算放在各自物件內，避免路由直接操作散落的規則。
- **單一責任**：服務協調完整業務操作，Repository 負責資料查閱，交易物件負責同一筆交易中的資料與狀態。
- **依賴注入**：資料庫與設定由建構子傳入；邀請使用的 Discord 依賴按操作傳入，方便隔離測試。
- **組合優先**：例如 `BlackjackRound` 組合帳本及牌靴，而非繼承帳本或資料庫。
- **保留純函式**：不持有狀態的 UUID 產生、手牌點數與比例分配，維持函式可讓測試與重用更直接。

這次不是把每個函式包成 class。既有函式轉接介面可繼續使用，但新增業務應優先採用物件方法，避免同一套規則出現兩份實作。

## 新增功能流程

1. 在所屬領域建立服務，明確注入資料庫、設定或外部依賴，不在服務內直接讀取全域 Flask 狀態。
2. 涉及扣款、派款及事件紀錄時，使用同一個交易；需要帳本操作時建立 `ShardLedger(tx)`，不要另開交易造成部分提交。
3. 在 `ApplicationServices` 中註冊應用程式級服務；只適用單次交易的物件則在交易區塊內建立，不放入共用服務容器。
4. 在 Blueprint 路由驗證登入、身份、CSRF 與輸入，再委派服務。直接呼叫服務不會自動取得 HTTP 路由的授權保護。
5. 補上正常、失敗回滾、重試冪等與多應用程式隔離測試，並更新對應中文功能文件。

## Docstring 格式

每個函式與方法依序撰寫英文描述、中文描述、`Args`、`Returns`、必要的 `Exceptions`、`Example`。`Args` 是標準段落名稱；例外段落須說明實際行為，例如向外拋出、轉換成業務錯誤或交易回滾，不只列出例外名稱。

無參數或無回傳值也需明確註記。範例應交代依賴與前置條件，避免讀者誤以為發放代幣等操作可在正式資料庫隨意執行。

## 驗證

在啟用虛擬環境後，於 `backend` 執行 `python -m unittest discover -s tests`。`tests/test_services.py` 包含服務隔離、路由委派、帳本轉接一致性與牌局回滾測試；各領域測試則驗證既有業務規則。

相關文件：[專案說明](../README.md)、[星之碎片](star-shards.md)、[管理工具](../ADMINISTRATION.md)。

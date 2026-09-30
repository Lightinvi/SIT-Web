# 日誌追蹤

後端預設記錄 **INFO、WARNING、ERROR、CRITICAL**，忽略 DEBUG。
每行為 JSON，包含 UTC 時間、等級、worker PID 與 `requestId`。
每個 HTTP 回應提供 `X-Request-ID`，可用來比對完成紀錄與錯誤堆疊。
完成紀錄包含路由樣板、方法、HTTP 狀態碼和耗時；4xx 為 WARNING、5xx 為 ERROR。

## 儲存與輪替

正式環境的前後端健康檢查改用 `/api/health`，正常運行時各每小時檢查一次。
此端點僅確認 Flask HTTP 服務存活，不查詢資料库或 Discord；前端仍額外檢查首頁。
啟動寬限期為 60 秒，期間每 5 秒檢查，首次成功後切換至每小時。
需要 Docker Engine 25.0+ 與 Docker Compose 2.20.2+，以支援 `start_interval`。
參考：[Docker Compose healthcheck](https://docs.docker.com/reference/compose-file/services/#healthcheck)。
Flask 與容器 Nginx 不記錄 `/api/health` 成功的 2xx 請求；失敗紀錄照常保留。
一般 `/api/users` 請求仍會記錄；VM 外層代理與開發伺服器的日誌設定不受影響。
保留連續 6 次失敗才標示 unhealthy，故故障辨識可能需要約 6 小時；
Docker 的 restart policy 不會只因 unhealthy 自動重啟容器。

- 本機：`storage/logs/app.log`，可透過 `LOG_DIRECTORY` 改變目錄。
- Docker：`logs` named volume 掛載到後端 `/app/logs`，重建容器仍保留。
- 檔案：`app.log` 加 `app.log.1`，**合計最多兩份，不是兩份備份**。
- 每份最多 `10 * 1024 * 1024` bytes（10 MiB）；寫入前以 UTF-8 位元組數檢查。
- 超長事件截斷並標記 `truncated=true`，避免單筆訊息突破限制。
- `.app.lock` 是多程序協調用的空鎖檔，不是第三份日誌；請勿在服務運行時刪除。
- 兩個 Gunicorn worker 共用檔案鎖，輪替後重新開啟目前檔案，避免寫進已更名的檔案。

Docker 的 stdout/stderr（包含 Gunicorn 與 Nginx）另由 `json-file` 驅動管理，
每個容器設定 `max-size=10m`、`max-file=2`，與上述應用程式日誌各自輪替。
此為每個日誌流的上限，不是整台 VM 所有容器合計兩份。
Compose 設定變更需重新建立容器才生效。

## 查閱

本機：`tail -f storage/logs/app.log`

開發 Compose：

```bash
docker compose exec backend tail -f /app/logs/app.log
docker compose logs --tail=100 backend frontend
```

正式環境：

```bash
docker compose -p sit-web --env-file .env --env-file images.env \
  -f compose.production.yaml exec backend tail -f /app/logs/app.log
```

應用程式 JSON 日誌不記錄請求 query、body、Cookie 或 Authorization，錯誤堆疊不包含區域變數與例外值。
Nginx access log 使用不含 query 的 `$uri`，避免 OAuth code/state 進入一般存取紀錄。
Nginx 自身的 error log 仍由 Nginx 產生，可能包含診斷用 URI，請限制 log 的存取權。
自行新增 logger 訊息時仍不得寫入密碼、token 或完整使用者資料。
測試環境預設不寫入持久化日誌；日誌測試以臨時目錄明確啟用。
本實作使用 Linux/WSL 的 `flock`，與正式 Linux Docker 環境一致。

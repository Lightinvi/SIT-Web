# sit-web.sytes.net：HTTPS 與自動續期

## 架構

```text
瀏覽器 https://sit-web.sytes.net:443
  -> GCP VM 的 Nginx（TLS / Let's Encrypt）
  -> 127.0.0.1:8080
  -> frontend 容器的 Nginx（React / API proxy）
  -> backend:8000（Flask）
```

容器內的 Nginx 保留；VM 上的 Nginx 負責憑證與 HTTP 轉 HTTPS。
憑證存在 VM 的 `/etc/letsencrypt`，不放入映像或 Git，也不會因 release 重建容器而消失。
VM 的 Certbot timer 定期檢查並在憑證到期前續期；Nginx plugin 在續期後載入新憑證。

## 先確認

- 此腳本支援 Debian / Ubuntu、apt 與 systemd，需在 **GCP VM** 執行，不是在 WSL 或容器內。
- `sit-web.sytes.net` 的 A 記錄須指向 VM 的固定外部 IPv4；請在 GCP Console 比對 IP。若有 AAAA 記錄，IPv6 也必須能連到同一網站，否則修正或移除無效記錄。
- GCP VPC 防火牆與 VM 防火牆均需允許外部 TCP **80、443**。HTTP-01 續期仍需 port 80，HTTPS 啟用後也要保留。
- VM 80、443 不可被其他容器或 Web server 占用；既有 Docker 前端請維持 8080。若目前 `HTTP_PORT=80`，先改為 8080 並重建前端，再安裝 VM Nginx。
- 若 VM 已有 Nginx 與同名網站設定，先整合既有設定，避免重複 `server_name`。腳本只建立自己的站台檔案，不會移除其他網站。
- 若已使用 snap 安裝 Certbot，沿用該套 Certbot 與 timer，不要混用此 apt 安裝腳本。
- 準備一個你能收信的電子郵件地址；執行腳本會透過 `--agree-tos` 同意 Let's Encrypt 使用條款。

本次檢查時 DNS 解析為 `35.212.157.31`，但外部 port 80 尚未可連線；以部署當下 GCP Console / DNS 的結果為準。

## 1. 部署新版本

提交本次 HTTPS 相關修改，再推送新的 `release/*` tag。
原有流程仍更新前後端映像，另外會把 `setup-https.sh` 放到 VM 的 `~/sit-web/`。
流程不會自動執行 sudo、不會自動修改 DNS 或防火牆。

## 2. 在 GCP VM 申請憑證

先確認容器 API：

```bash
curl -fsS http://127.0.0.1:8080/api/users
```

使用自己的真實 email，執行一次性設定：

```bash
cd ~/sit-web
sudo bash setup-https.sh sit-web.sytes.net YOUR_EMAIL@example.com
```

若 Docker 對外映射不是 8080，將實際映射 port 作為最後一個參數傳入。
脚本會安裝 Nginx、Certbot 與 Nginx plugin，建立轉發設定，申請憑證並強制 HTTP 轉 HTTPS，啟用 `certbot.timer`，最後執行模擬續期。
重跑時保留 Certbot 加入的 TLS 設定，不會用 HTTP 初始設定覆蓋它；若需要更換上游 port，須先人工更新站台設定。

若申請失敗，先修正 DNS、80 連線或既有站台衝突，再重跑；不要頻繁強制簽發。若只有最後的 dry-run 失敗，HTTPS 可能已啟用，但仍須修正續期問題。

## 3. 將 Docker port 限制在 VM 本機

HTTPS 確認正常後，在 VM 的 `~/sit-web/.env` 保留既有 `SECRET_KEY`，加入或更新以下兩行（不要重複同名變數）：

```dotenv
HTTP_BIND=127.0.0.1
HTTP_PORT=8080
```

在 VM 套用：

```bash
cd ~/sit-web
docker compose -p sit-web --env-file .env --env-file images.env \
  -f compose.production.yaml up -d --no-deps --pull never --wait frontend
```

此步使用 VM 已拉取的映像，不需要重新登入 GHCR。之後的 release 會繼續使用 VM `.env` 的綁定設定。
確認後可關閉 GCP 對外 8080 防火牆規則。只讓使用者經過 VM Nginx；該 Nginx 會覆寫 forwarding headers，容器內 Nginx 保留 HTTPS 協定資訊供後端使用。

## 4. 驗證 HTTPS 與續期

從你自己的電腦：

```bash
curl -I http://sit-web.sytes.net
curl -I https://sit-web.sytes.net
curl -fsS https://sit-web.sytes.net/api/users
```

HTTP 應回應轉址至 HTTPS；HTTPS 首頁應為 200，API 應回傳成員資料。
瀏覽器開啟 <https://sit-web.sytes.net> 應沒有憑證警告。

在 VM 確認排程與憑證：

```bash
sudo certbot certificates
systemctl list-timers --all certbot.timer
sudo certbot renew --cert-name sit-web.sytes.net --dry-run
sudo journalctl -u certbot.service --since "7 days ago" --no-pager
```

`certbot.timer` 應有下一次執行時間，dry-run 應成功。timer 不是等到過期才續期，也不代表每次執行都會簽發新憑證；Certbot 決定何時需要更新。
排程失敗需從 journal 與 `/var/log/letsencrypt/letsencrypt.log` 排查；此流程未配置續期失敗通知，建議另外監控 HTTPS 與憑證有效期。
如果使用動態 DNS 服務，仍需維持網域有效且 IP 正確。

## 檔案與排錯

- VM Nginx：`/etc/nginx/sites-available/sit-web-sit-web.sytes.net.conf`
- 憑證：`/etc/letsencrypt/live/sit-web.sytes.net/`
- 續期設定：`/etc/letsencrypt/renewal/sit-web.sytes.net.conf`
- `sudo nginx -t`：檢查設定；修改後使用 `sudo systemctl reload nginx`。
- `sudo journalctl -u nginx --since "10 minutes ago"`：檢查 VM Nginx 錯誤。
- `sudo ss -ltnp`：確認 VM Nginx 接聽 80/443，Docker 8080 綁定 127.0.0.1。

現有 Flask 尚未使用 forwarding headers 產生外部 URL；日後若加入 OAuth、絕對網址或 HTTPS 判斷，需要按實際代理層數設定 Werkzeug ProxyFix，不能直接信任公開來源的 headers。

## 官方參考

- [Certbot Nginx plugin 與自動續期](https://eff-certbot.readthedocs.io/en/stable/using.html)
- [Let's Encrypt 保留 port 80 的建議](https://letsencrypt.org/docs/allow-port-80/)

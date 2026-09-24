# GitHub Actions 部署至 GCP VM

此流程沿用 SSH + GHCR 的部署方式，目標為 GCP Compute Engine VM，不是 Cloud Run。

## 流程

```text
push tag: release/v1.0.0
          |
     release.yml
       /     \
build-frontend.yml   build-backend.yml
       \     /
    deploy-gcp.yml
          |
    GCP VM / Docker Compose
```

- 只有推送符合 `release/*` 的 Git tag 才會啟動；不是 GitHub issue label，也不是 release 分支。
- 三個子流程使用 `workflow_call`，屬於同一個 Actions run。
- 前端 lint 後建置 Docker image；Dockerfile 內執行 TypeScript 與 Vite build。
- 後端先執行 unittest，再建置 Docker image。
- 映像名稱自動取用小寫的 GitHub repository：本專案為 `ghcr.io/lightinvi/sit-web/frontend` 與 `ghcr.io/lightinvi/sit-web/backend`。
- 映像標籤使用 commit SHA；部署傳遞本次建置的 `@sha256:...` digest，不使用會漂移的 `latest`。
- 兩個建置都成功才會部署。所有 release 共用 concurrency group，避免同時更新 VM；有多個待執行的 release 時，GitHub 可能以較新的取代尚未開始的 pending run。
- 部署拉取兩個映像後重建服務，等候後端、前端與 `/api/users` 代理健康檢查通過。
- 這是單一 VM 原地更新，可能短暫中斷；健康檢查失敗會讓流程失敗，但不會自動回滾。

## GitHub Secrets

在 repository 的 **Settings → Secrets and variables → Actions → Repository secrets** 設定：

| Secret | 內容 |
| --- | --- |
| `GCP_VM_HOST` | VM 外部 IPv4 或 DNS hostname，不含 `http://` 或連接埠 |
| `GCP_VM_USER` | 可 SSH 登入且可直接執行 Docker 的 Linux 帳號 |
| `GCP_VM_SSH_KEY` | 對應該帳號的完整、無密碼 SSH 私鑰；公鑰須先加入 VM |
| `GCP_VM_KNOWN_HOSTS` | 已確認身分的 VM SSH host key，使用 OpenSSH known_hosts 格式 |
| `GHCR_USERNAME` | 下方 PAT 所屬的 GitHub 使用者帳號 |
| `GHCR_PAT` | 可讀取兩個 GHCR package 的 classic PAT，至少 `read:packages`；組織需要 SSO 時也須授權 |

建置上傳使用 GitHub 自動提供的 `GITHUB_TOKEN`，不需另外設定；其 job 已宣告 `packages: write`。
Repository/organization 必須允許使用本流程中的 GitHub Actions。若 GHCR package 已存在，須允許本 repository 的 Actions 存取該 package。

SSH 固定使用 port 22 與 host key 驗證。可透過 GCP Console 的可信任 VM 終端機取得 host key：

```bash
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

將輸出組成 `GCP_VM_KNOWN_HOSTS`，其中 host 必須與 `GCP_VM_HOST` 相同：

```text
YOUR_VM_HOST ssh-ed25519 AAAAC3...完整公鑰...
```

## VM 一次性設定

1. 使用 Linux x86_64 / amd64 VM；目前映像建置平台為 `linux/amd64`。
2. 安裝 Docker Engine 與新版 Docker Compose plugin，須支援多個 `--env-file`、`up --wait` 及 `--wait-timeout`。
3. 確認部署帳號執行 `docker info` 與 `docker compose version` 不需要 sudo。
4. 讓 GitHub runner 能透過 SSH port 22 連入。此流程使用一般 SSH，不含 IAP tunnel 或 OS Login 設定。
5. 開放應用程式對外 TCP 8080，或將下面 `HTTP_PORT` 設為 80 並開放 TCP 80；避免其他程式占用該連接埠。後端 8000 不對外發布。
6. 使用部署帳號建立環境設定；不要提交此檔案到 Git。

```bash
mkdir -p ~/sit-web
chmod 700 ~/sit-web
umask 077
printf 'SECRET_KEY=%s\nHTTP_PORT=8080\n' "$(openssl rand -hex 32)" > ~/sit-web/.env
```

上述命令只在第一次初始化執行；再次執行會更換 SECRET_KEY。正式網域 `sit-web.sytes.net` 的 HTTPS 與自動續期請依照 [HTTPS 設定](https.md)。

部署腳本只在暫存目錄保留 GHCR 認證，結束後清除。VM 上的 `~/sit-web/.env` 不會被 workflow 覆寫。
若 VM 上已有用其他 Compose project name 或 `docker run` 啟動的 SIT-Web，先確認並停止舊服務，避免 8080 衝突；本流程不會刪除其他專案的容器。

## 發布

先提交並推送包含這些 workflows 的 commit，再建立新的 tag：

```bash
git add .github/workflows scripts compose.production.yaml docs/deployment.md README.md
git commit -m "Add release build and GCP deployment workflows"
git push origin main
git tag release/v1.0.0
git push origin release/v1.0.0
```

請依實際預設分支調整 `main`。在 GitHub Actions 查看 **Release to GCP**。部署完成後開啟 `http://VM_HOST:8080`，並檢查 `http://VM_HOST:8080/api/users`。

## 檢查與重啟

部署成功後，VM 的 `~/sit-web/` 會保留 compose 與該次映像 digest：

也會收到 `setup-https.sh`，供在 VM 上一次性安裝 HTTPS 與自動續期；release 不會覆寫 VM Nginx 或憑證。

```bash
cd ~/sit-web
docker compose -p sit-web --env-file .env --env-file images.env -f compose.production.yaml ps
docker compose -p sit-web --env-file .env --env-file images.env -f compose.production.yaml logs --tail=100
```

需要回滾時可重新執行先前成功的 release run，或以先前 commit 建立新的 `release/*` tag。映像須仍存在於 GHCR；回滾沒有資料庫遷移處理。

## 本機驗證

本機可執行不需 Docker 或 VM 的部署順序與失敗處理測試：

```bash
.venv/bin/python -m unittest discover -s scripts/tests -v
```

測試以暫存 Docker 替身驗證拉取失敗不更新容器、健康檢查失敗不覆寫成功版本紀錄，以及暫存認證清理。真正的容器健康狀態與 SSH 連線需由首次 release 部署驗證。

## 參考

- [GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
- [Docker build-push-action](https://github.com/docker/build-push-action)
- [Docker Compose up / health checks](https://docs.docker.com/reference/cli/docker/compose/up/)

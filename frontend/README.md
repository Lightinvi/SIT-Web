# 前端開發說明

本專案使用 Vite、React 與 TypeScript，並使用 React Router 管理頁面、react-select 提供可搜尋下拉選單、lucide-react 提供圖示，以及 spin-wheel 顯示每日轉盤。

## 開發與建置

在 WSL 專案的 `frontend` 目錄執行：

```bash
npm ci
npm run dev
```

| 指令 | 用途 |
| --- | --- |
| `npm run dev` | 啟動 Vite 開發伺服器 |
| `npm run lint` | 使用 Oxlint 檢查程式碼 |
| `npm run build` | TypeScript 檢查與正式建置，輸出至 `dist/` |
| `npm run preview` | 本地預覽已建置的前端，不等同完整前後端環境 |

若需同時開啟後端，請回到專案根目錄執行 `./dev_run`。Vite 開發時將 `/api` 代理至 `http://localhost:5000`；正式環境則由 Nginx 負責反向代理。`preview` 不可直接視為已具備相同的 API 代理配置。

## 目錄分工

| 目錄 | 中文說明 |
| --- | --- |
| `src/api/` | API 請求與回應處理 |
| `src/components/` | 可重用的介面元件 |
| `src/hooks/` | React 狀態與生命週期相關邏輯 |
| `src/layouts/` | 共用頁面配置 |
| `src/pages/` | 各路由的頁面與功能介面 |
| `src/types/` | TypeScript 型別 |
| `src/utils/` | 共用工具 |
| `src/assets/` | 星之碎片圖案、撲克牌等資源 |

## 前後端責任

前端顯示餘額、遊戲動畫、預測盤及管理介面，但不自行決定獎勵、牌局結果或權限。所有交易、結算、每日資格與身份驗證都由後端負責。

需要登入的請求沿用 Session Cookie；寫入操作需依既有 API 包裝帶上 CSRF Token。不可把 Discord Bot Token 或 OAuth Client Secret 放入前端或 `VITE_*` 變數，因為前端建置內容可被使用者讀取。

時間顯示轉換為使用者所在時區；每日轉盤重置仍依後端主機時區。下拉選擇沿用 react-select，日期與資料庫搜尋需依使用者提交後再發出請求。

新增功能時，沿用現有路由、API 包裝與樣式模式，並測試桌面及手機尺寸、登入與未登入狀態、載入及錯誤狀態。後端服務分工請參考[後端物件架構](../docs/backend-architecture.md)，完整啟動設定請參考[專案說明](../README.md)。

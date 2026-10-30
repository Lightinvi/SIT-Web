# WARDOGS 資料與圖片

本地快取位於 storage/wardogs（正式環境沿用 STORAGE_PATH 的 storage volume）。
資料庫透過 /api/wardogs/items 讀取本地物品資料，圖片透過 /api/wardogs/icons/<release>/<path> 提供。

首次瀏覽會在背景建立快取。每七天於資料庫被存取時檢查 GitHub 最新 release，
完整保留發布檔的 data/、assets/、README.md 與 LICENSE，包括全部 JSON、CSV、Schema、清單、地圖資料、地圖圖片與物品圖示。
完整下載約 700 MB，解壓後保存在 release 目錄；不保留原始壓縮檔。
只有 release ID 改變或快取格式升級才重新下載。既有僅包含 items 的快取會在下次存取或管理員更新時補齊，不受每週期限限制。
物品資料統一位於 <release>/data/items.json，不再於版本根目錄保存重複檔案；舊快取會自動搬移。icons/ 的既有路徑仍可使用。
未使用的舊版本保留於 storage/wardogs，可在無人瀏覽舊頁面後手動清理。

網頁管理員可在管理工具按「更新 WARDOGS 資料」，強制立即檢查。
端點沿用管理員即時 Discord 權限及 CSRF 驗證，更新於背景執行，頁面顯示更新結果。
來源暫時無法連線時保留舊快取，延後一小時再嘗試。應用程式重啟會中止執行中的背景更新，下次存取重新嘗試。

分類依網站自訂的標籤與資產路徑規則判定，不直接使用來源 subtitle。
固定順序為武器、配件、彈藥、裝備、背包(容器)、物品、投擲物、部署道具、建築、載具、載具武器、其他。
分類規則位於 frontend/src/utils/wardogsCategories.ts；無法辨識的資料歸入其他，空分類仍保留入口。缺少來源圖示的物品顯示「暫無圖片」。
資料與圖片來源：https://github.com/warpuppies/wardogs-data
非官方資料；遊戲名稱與圖片權利歸原開發者及發行商所有。

配件中顯示名稱為內部 ID（例如 Id.Item.*、WEPN_031），或屬於 Barrel、Grip（含 Pistol Grip）、Stock、Handguard、Dust Cover、Trigger 的項目，改歸入其他。

Foregrip、Bipod、Grip Pod 歸入配件；顯示名稱仍為內部 ID 的項目維持歸入其他。

IED（炸藥與觸發器）歸入部署道具。裝備僅保留頭盔、護甲、吉利服，其他工具與穿戴物歸入物品。原物品分類中的 Supplies 歸入建築，Cards 歸入其他；補給容器仍屬於背包(容器)。


## 完整來源資料

`GET /api/wardogs/datasets` 列出已下載的所有資料檔及是否完成完整快取升級。
`GET /api/wardogs/data/<release>/<filename>` 提供原始資料，例如 weapons.json、ammo.json、attachments.json、equipment.json、damage.json、vehicles.json、buildables.json、skills.json、roles.json、movement.json、loot.json、rewards.json，以及 csv/、schema/、maps/ 下的檔案。
`GET /api/wardogs/assets/<release>/<filename>` 提供地圖圖片、heightmap、圖示與資產清單。
目前物品卡片與基本詳細頁繼續使用 items.json；其他來源已完整保留供後續關聯展示使用。

## 物品跨來源詳細資料

`GET /api/wardogs/items/<itemId>` 讀取全部資料 JSON（排除 Schema 與檔案清單），
只使用相同 gameBuild，透過不區分大小寫的完整 ID、明確物品引用及口徑標籤比對。
回傳 item、sections（含來源檔名與原始數值）及 checkedSources。
武器、配件、彈藥、護甲、載具、外觀及掉落資料可依其實際引用關聯。
彈種修正使用 Item.Ammo.Type，傷害規則透過 damageContext / damageEntity 關聯，保留條件而不直接假定最終傷害。
商店售價只採 vendor.tag 與物品 ID 完整相符的項目，並搜尋其他物品條目內的販售紀錄。
缺少的名稱、描述、圖片與基本屬性可由同 ID 記錄補入；既有數值（包含 0）不覆蓋，耐久度不顯示。
無法確認對應的資料不以名稱猜測合併。各來源缺少的欄位不自行推估。
本次全物品檢查報告位於 <release>/details-audit.json；報告為檢查當下結果，後續更新需重新產生。

## 武器彈藥與傷害模擬

物品詳細 API 的 simulation 包含同版本的相容彈藥、彈丸數值、武器類別、命中倍率、護甲與 Infantry 傷害規則。
相容彈藥透過武器 calibers 與 Item.Caliber 標籤關聯，只納入 Item.Ammo；每件彈藥連到自己的詳細頁。
模擬基礎式：彈丸 damage × Universal 部位倍率 × Weapon 類別倍率 × damageFalloff × 符合條件的普通規則倍率 × 防護倍率。
普通 Percentage_Ongoing 規則依 source（全部符合）、target（覆蓋部位上的護甲）、hitLocations 篩選，每條乘以 (1 + amount/100)。忽略友軍及不明攻擊者條件。
防護倍率 = 1 - 護甲首階段 reduction × ammoTypes 的 effectiveness / 100；effectiveness 優先使用彈丸 Arms 對應的 byArmsClass，否則採 modifier。
致死發數 ceil(100 / 有效傷害)；TTK = (發數 - 1) × 60 / rpm。這是同部位、理想連射的估算，不包含換彈及點放間隔。
資料缺少角色自訂口徑倍率、飛行速度變化與完整遊戲執行環境，因此不宣稱為實測傷害。
Cubic 距離曲線以線性近似；未納入護甲耗損、穿透、技能、散布及彈丸飛行減速；霰彈按單顆彈丸顯示；爆炸型彈丸不估算。
公式查證來源：
- https://github.com/warpuppies/wardogs-data/blob/main/data/README.md
- https://github.com/warpuppies/wardogs-data/blob/dev/src/transform/damage.ts
- https://kiyogitpy.github.io/wardogs-data-docs/pipelines/Wardogs_DamagePipeline_v2.html

## 缺漏售價補充

目前 build 25937608 的部分武器沒有 vendor 紀錄。backend/app/services/wardogs_prices.py
記錄官方 Season 02 公告（2026-10-14）明列的缺漏價格：AK74 800、MAAWS 2400、T-21 1200、Super-45 5600、GGX 18 1000、MGL-40 7500。
只在相符 build 且來源沒有任何數字價格時使用；原始 JSON 不修改，既有價格（含 0）優先，前端售價旁附官方來源連結。
未核對的新 build 不套用舊公告補值；其他未確認價格維持未提供。
官方來源：https://store.steampowered.com/news/app/1867240/view/1846651706674560

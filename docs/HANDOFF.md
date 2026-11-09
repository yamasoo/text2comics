# 交接

## 目前狀態（2026-11-09，M1 修正完成；M-4 與 Windows 實機待使用者）

「M1 修正」做完了 M-1、M-3、M-2 與 L-1–L-7（版本 0.9.0，細節在 `CHANGELOG.md`）。M1 本身還不算完成：要等你在 Windows 上做完 `docs/qa/M1.md` 第 5 節的 7 步、決定 M-4 的角色記號。

### M1 修正做了什麼

- **M-1 畫面外的說話者（格式變更）**：對話框加種類 `radio`（通訊、電話：細密鋸齒的電子音框）與欄位 `offscreen: true`（說話的人不在這一格的畫面裡）。offscreen 的人**不准**列在 `characters`、不送進生圖、不算人數；尾巴：speech／shout／whisper 指向最近的格框邊、伸出去被框切掉，radio 沒有尾巴。劇本標記 `（通訊）`（電話、廣播、無線電）→ radio、`（畫面外）`→ offscreen，可寫 `（畫面外、喊）`。檢查、編譯、嵌字、提示詞、分鏡編輯區（多一個「畫面外」勾選）都改了。格式在 `docs/02_資料格式.md` 第 4、5 節。
- **M-3 `t2c/` 自足**：格子模板與 MOSS workflow 搬到 `t2c/data/`；`settings.load()` 要由呼叫端給設定檔或資料夾，範例專案由呼叫端給（`create_project(sample=…)`）。只複製 `t2c/` 到別處也能 import、讀模板、編譯一章（`tests/test_portable.py`）。I1／I3 照「整包複製到 vendor」做就好，設定檔路徑由宿主專案傳入。
- **M-2 閱讀順序**：嵌字自動擺位改用新的順序判斷（`letter.order_conflict`）、成本加重；擺完再檢查，順序顛倒就警告、嵌字頁畫紅框；分鏡檢查對 anchor 顛倒列提醒。〈大夜班〉31 組對話框順序錯的從 4 組 → 0 組，沒有新增壓臉。
- **L-1–L-7**：外觀字表補齊（道具 headset 放行、衣物名詞只提醒）；重複格 id／頁碼擋存檔；忠實度報告拆句比對（〈大夜班〉39／44 → 43／44，只剩故意改寫的「……是我。」）；規劃的原著依據找不到原文時提醒；提示詞的角色設定只取卡片第一段；錯誤訊息的換行顯示 ⏎；範例沒有出圖時測試跳過、介面停用「連同出圖」。
- **參考答案也更新了**：`work/m1_mars_ch1/`（不進版控）的劇本第 5、6 頁四句隔著通訊的台詞加了（通訊），分鏡的 p005_k3、p005_k5、p006_k3、p006_k5 拿掉邊緣的人、改成 radio＋offscreen。DeepSeek 實跑（第 5 節第 3 步）時可以看它會不會自己標（通訊）。

### M1 修正的決定

- **`radio` 是種類、`offscreen` 是另一個欄位**，不合成一個：通訊幾乎都是畫面外，但「臉在螢幕上」時 radio 的說話者在畫面上；反過來畫面外也可以是喊叫、小聲。兩個獨立比較不會互相卡。
- **畫面外的規則是雙向的**：沒標 offscreen 的說話者一定要在 characters，標了 offscreen 的一定不在。劇本沒標（畫面外）時，分鏡自己決定不畫說話者（只拍聽的人）也可以。
- **閱讀順序只抓明確的錯**：整個在上面、跑到右上方、同一高度整個在右邊。「在右下方、起頭比較低」的不算（讀者多半先往左），記在 backlog。
- **舊路徑相容**：`config.json` 的 `comfy.workflow` 是舊寫法 `workflows/moss_layout.api.json` 也會用內建的，你的 `config.json` 不用改（要改就改成空字串）。
- **範例出圖不進版控**（L-7 選了「沒圖就跳過」）：原圖約 35 MB；要不要縮小後放進 repo 記在 backlog 由你決定。
- 沒做：M-4（等你）、L-8–L-12、offscreen 尾巴指定方向、radio 尾巴指向通訊器（都在 backlog）。

### 你要做的

1. **刪掉兩個舊檔**（我這邊不能刪你電腦上的檔案，已搬到 `t2c/data/`）：`layouts\pages.json`、`workflows\moss_layout.api.json`。沒刪的話 `tests/test_portable.py::test_old_data_folders_are_gone` 會失敗提醒你。指令在下面的 Git。
2. `docs/qa/M1.md` 第 5 節的 7 步（照舊）。第 3 步用的是新的提示詞，順便看 DeepSeek 會不會在通訊的台詞標（通訊）、分鏡會不會用 offscreen。
3. M-4：決定陳嘉禾、周遠、阿海、`guard_plain` 各自的視覺記號。

### 待決問題（M1 修正新增）

16. 畫面外 radio 沒有尾巴、speech 尾巴伸出格框：看實際頁面滿不滿意（可以在嵌字頁拖尾巴覆寫）。
17. 閱讀順序的判斷會不會太嚴或太鬆：實際頁面上看到紅框或漏抓請回報。

### Git（M1 修正）

```powershell
cd E:\dev\text2comics
git rm layouts/pages.json workflows/moss_layout.api.json
git add -A
git commit -m "M1 修正：畫面外說話者（radio、offscreen）、t2c 自足、對話框閱讀順序、L-1–L-7"
```

（S6–S8 與 M1 報告如果還沒提交，上面的 `git add -A` 會一起帶進去；要分開提交就先照 `docs/qa/M1.md` 第 6 節提交一次。）

## M1 驗收（雲端部分，2026-11-09）

M1 的完整報告在 `docs/qa/M1.md`。重點：

- **通過的**：`pytest` 272 項全過；用《第一次火星獨立戰爭》第 1 章（不是範例）走完 小說 → 規劃 → 劇本 → 分鏡 → 編譯 → 出圖（假 ComfyUI）→ 組版 → 嵌字 → PDF／CBZ，7 頁 35 格；文字端由 Claude 代替模型回答真實提示詞，刻意放的 5 種錯誤都被驗證擋下、照訊息回修一次就過；送進 ComfyUI 的 70 份 prompt 沒有台詞、沒有中文、外觀逐字來自聖經、不在場的角色不出現、seed 可重現；PDF／CBZ 旗標正確、重跑位元組相同；介面開新專案各頁正常、無主控台錯誤。`CLAUDE.md` 規則 3.1–3.8、4.1–4.9 逐條檢查都遵守。
- **要修的（中等）**：M-1 隔著通訊／電話的聲音會被畫進格子（格式要加畫面外說話）；M-2 對話框閱讀順序錯了不會警告（這章 31 組有 4 組）；M-3 `t2c/` 靠上一層資料夾找 `layouts/`、`workflows/`，不能單獨搬走（I1／I3 會碰到）；M-4 陳嘉禾、周遠、阿海、`guard_plain` 的定裝圖幾乎分不出來（要你決定視覺記號）。輕微問題 L-1–L-12 見報告。都已記進 `docs/backlog.md`。
- **待你在 Windows 上做**：報告第 5 節的 7 步（pytest、LLM 連線、DeepSeek 實跑新章節、實際出圖、選圖與輸出、閱讀器右翻、定裝圖挑選）。做完回報後 M1 才算完成。
- **參考專案**：`work/m1_mars_ch1/`（不進版控）有這次產生的規劃、劇本、分鏡，可以當 DeepSeek 實跑的對照答案；實跑請先複製一份再刪掉 plan／script／storyboard。
- **交接文件與實際狀態不同的地方**：`work/mars_war` 的卡片已是 `status: confirmed`，定裝圖 11-08 晚上已在 GPU 出完（還沒挑，沒有 `bible/picks.json`）；下面 S6 段落寫的「還是草稿」已過時。
- **Git**：最後一個 commit 是 11-08 22:47（S4 修正），S6–S8 與 M1 的檔案需要提交，指令在報告第 6 節。

### 下一步建議

1. 你先做完報告第 5 節（不需要開對話）。
2. ~~開一個修正階段「M1 修正」~~：已完成（見最上面）。M-4 等你決定角色記號後在 S6 流程改卡片、重出定裝圖。
3. 修完、Windows 實機也過了，把 M1 標完成，再進 I1。

## S8（輸出）的交接（2026-11-09）

### S8 做了什麼

- **輸出**：`t2c/export.py`＋命令列 `tools/export.py`＋介面「頁面」分頁的下載按鈕。把已輸出的 `pages/chNNN/pNNN.png` 打包成右翻的 PDF 或 CBZ，整章或單頁，同時存在專案的 `out/`。格式見 `docs/02_資料格式.md` 第 15 節。
  - PDF：自己寫檔（Pillow 不能設閱讀方向）；`/ViewerPreferences << /Direction /R2L >>`，預設 `/PageLayout /TwoPageRight`。
  - CBZ：PNG 原檔＋`ComicInfo.xml`（`Manga=YesAndRightToLeft`）。
- 介面：「頁面」分頁多了「整章 PDF／整章 CBZ／這頁 PDF」與「PDF 用單頁檢視開啟」；頁面 PNG 沒輸出齊時按鈕停用並說明；API 是 `GET /api/chapter/export`。
- 測試：`tests/test_export.py` 22 項、`tests/test_ui.py` 多 1 項。雲端 Linux 全部通過（除了下面說明的一項環境問題）；用 poppler 把產生的 PDF 轉成圖，頁序與內容正確，`qpdf --check` 無錯。

### S8 的決定

- **不重新組版**：只打包現有的頁面 PNG。缺頁就報錯（列出全部缺的頁碼），PNG 比分鏡、選圖或嵌字舊就列提醒。這樣「輸出頁面」仍是唯一產生頁面的地方。
- **PDF 內頁預設 JPEG 品質 90**（約為無損的一半大小，範例頁 1.6 MB vs 3.0 MB／3 頁）；要無損加 `--lossless`。
- **PDF 預設用雙頁檢視開啟**（第 1 頁單獨在右，之後左右成對），因為右翻在單頁檢視看不出差別；要單頁加 `--single`（介面有勾選）。
- 閱讀方向固定右翻（和組版一致；`project.yaml` 的 `reading` 目前只支援 `rtl`）。
- 下載是同步的（打包幾秒內完成），不走背景任務。
- 沒做：多章合訂本、PDF 書籤／目錄、EPUB、把 CBZ 的 ComicInfo 加更多欄位（作者、簡介）。記在 backlog。

### 待決問題

（承接 S1–S7 的 1–13 項，見下方）

14. （S8）內頁 JPEG 90 夠不夠：嵌字的小字邊緣會不會看得出壓縮痕跡？不滿意就改 `--quality 95` 或 `--lossless`，也可以把預設改成無損。
15. （S8）PDF 預設雙頁檢視是否符合你的閱讀習慣（平板直立閱讀通常想要單頁）。要改預設就改 `export.export_chapter(spread=…)` 與介面勾選的預設。

### 沒有驗證的

- **真實閱讀器的右翻行為**：雲端只能驗證檔案內容（旗標存在、頁序正確、poppler 能轉圖）。請在你的閱讀器各開一次 `out\ch001.pdf` 與 `out\ch001.cbz`（建議 Acrobat／Edge 與 CBZ 閱讀器如 YACReader、CDisplayEx、Komga），確認：第 1 頁在右邊、翻頁方向由右往左。用範例一章做就好。
- Windows 上的 `pytest`（含 `tests/test_export.py`）。雲端我只複製了需要的檔案，所以 `test_ui.py::test_create_project_new_and_from_sample` 因為雲端沒有範例的出圖（`renders/`）而失敗，與 S8 無關；Windows 上有完整範例應該會通過。
- S7 與更早階段留下的項目照舊（見下）。

### 流程提醒

- 這台電腦沒有 shell 可用時，檔案透過檔案橋接寫入；git 提交要在你的終端機執行。

## S7（介面）的交接（2026-11-09）

### S7 做了什麼

- **介面**：設計在 `docs/05_介面設計.md`。啟動 `python run.py`（或 `start.bat`）後，在瀏覽器裡就能走完一章：專案頁開啟／新建（可複製範例）→ 第 N 章：原著 → 規劃 → 劇本 → 分鏡 → 出圖（點縮圖選圖、裁切）→ 頁面（即時嵌字預覽、輸出 PNG）→ 嵌字頁微調。章節頁頂端有「整章批次」。視覺聖經頁：草稿確認入庫、卡片編輯（原文引文並排）、新增卡片、定裝圖出圖與挑選。
- 程式：核心 `t2c/workspace.py`、`t2c/render.py`、`t2c/gpu.py`；後端 `server/`（`project_api.py`、`bible_api.py`、`tasks.py`、`common.py`）；前端 `web/static/` 的 `common.js`、`project.js`、`chapter.js`、`storyboard.js`、`panels.js`、`pages.js`、`bible.js`（`letter.js` 只改成預設用目前專案）。
- **VRAM 排程**：任務排隊、一次一個；用本機 LLM 前請 ComfyUI 卸模型（`/free`）；出圖前偵測到 llama-server 還在執行就暫停詢問（「已關閉，繼續／照樣出圖／停止」）。用 DeepSeek 時不會問。
- 測試 `tests/test_ui.py` 13 項；全部 249 項在雲端 Linux 通過。
- **瀏覽器實測（雲端，假服務）**：用假的 ComfyUI（照提示詞的框畫出簡圖）＋假的 llama.cpp（OpenAI 相容串流＋`/health`），以 Playwright 實際點介面：從範例新建專案 → 整章出圖（遇到 VRAM 詢問）→ 選圖、裁切 → 頁面預覽與輸出；另一個專案刪掉劇本與分鏡後按「整章批次」，看到模型輸出串流、規劃→劇本→分鏡→（詢問）→出圖→頁面全部完成；視覺聖經頁與卡片頁、嵌字頁都正常顯示，沒有主控台錯誤。

### S7 的決定

- **目前的專案存在瀏覽器**（`FE.store`），每個 API 都帶 `project`；後端不記狀態。
- **人改的檔案只擋「編譯不了」**：分鏡要能 `compile_chapter()` 才存；外觀字、字數、和劇本不一致等列成提醒。LLM 的輸出仍然全部要過（規則 6 不變）。定案卡片有錯就擋（分鏡要用）。
- **加畫**：seed 仍由格 id 決定，從候選編號 0 往上找沒畫過的，所以可重現、不覆蓋。「同 seed 重畫」才會覆蓋那一張。
- 挑圖、裁切按了就存；分鏡、劇本、原著、卡片按「存檔」才存（有未存修改時離開頁面會問）。
- 順手修了 `compose.candidates()`：帶出圖預設後綴的候選（`_draft`）原本沒列出。
- 沒做：介面設定金鑰與 `config.json`、用量費用、自動卸載 llama.cpp、分鏡拖曳改格序（都記在 backlog）。

### 待決問題

（承接 S1–S6 的 1–11 項，見下方）

12. （S7）出圖前「本機 LLM 還在執行」的判斷：`config.json` 裡網址是 localhost 的 provider，`/health` 有回應就算。如果你平常讓 llama-server 一直開著、但用 DeepSeek 寫文字，每次出圖都會被問一次——要不要改成「只在這個任務用過本機 LLM 才問」？
13. （S7）整章批次的出圖只補「沒畫過的候選」；要不要在批次裡也提供「每格加畫 N 張」？

### 沒有驗證的

- **Windows 上用真的 ComfyUI、DeepSeek／llama.cpp 走一章**：請照 `docs/qa/S7_介面驗收.md`。雲端只用假服務驗過。
- Windows 上的 `pytest`、Edge／Chrome 的實際操作手感（拖框、裁切）。
- S5、S6 留下的項目照舊（GPU 定裝圖、真的 DeepSeek 抽取與改編）。

### 流程提醒

- 這台電腦沒有 shell 可用時，檔案透過檔案橋接寫入；git 提交要在你的終端機執行。

## 之前的階段

### S6 做了什麼（2026-11-08）

- **流程**：掃描（逐章，LLM）→ 合併證據 → 逐人成卡（LLM）→ 人確認 → `accept`（先過規則檢查）→ 定裝圖工作（ComfyUI）→ 比較表 → `pick` → 服裝矩陣。命令列 `tools/bible.py`（子命令 `extract/scan/draft/check/accept/sheet/contact/pick/status`），說明見 `python tools\bible.py -h`。
- 程式：`t2c/bible_check.py`（純規則）、`t2c/bible_prompts.py`（提示詞）、`t2c/bible.py`（流程）。設計說明 `docs/04_提示詞設計.md` 第 7 節；格式 `docs/02_資料格式.md` 第 3、13 節。
- **外觀不准無中生有**：掃描時每條外觀／服裝事實都附原文逐字引文，程式用子字串比對，對不上就丟掉。成卡時模型補的部分必須列在 `invented`、與作者設定衝突的列在 `conflicts`，原樣放進草稿的「待確認」。原文與作者設定衝突時以原文為準。
- **定裝圖**：角色 3:4（全身 `full`、胸像 `bust`，每套服裝各一組），地點 4:3。用單格合成模板走 `compile_chapter()`，所以角色外觀仍只來自 `look_en`／`outfits`；種子由工作 id 決定。
- **挑選過期偵測**：`bible/picks.json` 記 `look_en`＋服裝的簽章；定案後改了就在 `status` 標 ⚠。
- 測試 `tests/test_bible.py` 30 項全過（假模型、假 ComfyUI、一項走假伺服器）。

### 《第一次火星獨立戰爭》草稿卡

小說是使用者用另一個專案寫的（`設定/角色*`、`設定/世界觀`、`正文` 12 章）。草稿卡由我讀原文整理（沒有用真的 DeepSeek 跑 `scan`），放在 `work/mars_war/`（`work/` 不進版控）：

- 角色 8 張：陳嘉禾、蘇硯（`default`＋`corridor_helmet`）、莫蘭、周遠、陶伯、阿海、門外左邊的人 `guard_gray`、門外右邊的人 `guard_plain`。
- 地點 9 張：值班室、餐廳、維修間、B區走廊、D區三號氣密門、D區老管線、避難層、工具間、三號碼頭。
- 全部通過 `python tools\bible.py check work\mars_war`；放進暫存目錄 `accept --all`、`sheet` 編譯（18 張）也都成功。**還是草稿，沒有確認。**
- 每張卡本文有「待確認」與「原文依據」。最需要你決定的：
  1. **蘇硯髮型**：作者設定是「短髮＋齊瀏海」（沒紮），正文第 4 章寫「短髮紮在後面」。草稿採正文（髮尾在後頸紮起）、保留齊瀏海。
  2. **莫蘭、周遠、陶伯、阿海、兩個守門人**：原文幾乎沒寫長相，髮型、臉、體型多半是補的（卡片逐項列在「補上的」）。尤其莫蘭是現場反派，建議先決定想要的氣質。
  3. **種族**：全部依姓名補成 East Asian（原文沒寫）。
  4. **性別**：`guard_gray` 依第 6 章周遠講的「她」推定為女性；`guard_plain` 原文沒寫，補為男性。
  5. **陳嘉禾的外套**（第 1、5 章）款式原文沒寫，沒有另設服裝。
  6. **工具間**畫的是第 9 章燒毀後的樣子。

### S6 的決定

- **Builder 獨立實作**，不動 S5 的 `Adapter`（它綁章節）；產生 → 驗證 → 回修的寫法刻意相同，之後要合併再重構。
- 草稿放 `bible/drafts/`，`Project` 只讀 `bible/characters`、`bible/locations`，所以草稿不會被分鏡編譯引用（CLAUDE.md 草稿與正式分開的精神）。
- `accept` 不覆蓋既有定案卡（`look_en` 定案後不改），要覆蓋加 `--force`；名字對不上任何草稿會報錯而不是默默略過。
- 只替出現兩章以上的人物成卡（`--min-chapters`，預設 2）；`--only` 例外。
- `look_en` 不放服裝、表情、動作，也不放暫時狀態（鬍渣、亂髮）；字表集中在 `bible_check.py`，提示詞與檢查共用。
- 定裝圖只給人確認外觀，**沒有**接進分鏡出圖當參考圖（記在 backlog）。

### 待決問題

（承接 S1–S5 的 1–8 項，見下方「之前的階段」；S6 新增）

9. （S6）`look_en` 的寫法在 MOSS 上是否真的穩定出對的人（性別、年齡、髮型）：要看定裝圖才知道。
10. （S6）定裝圖尺寸 3:4（864×1152）全身像會不會臉太小：請看比較表，必要時加大 `--megapixels` 或只出胸像。
11. （S6）要不要把定裝圖當參考圖接進分鏡（backlog）。

### 沒有驗證的

- **GPU 定裝圖**：雲端沒有 ComfyUI。請照 `docs/qa/S6_視覺聖經驗收.md` 在你的電腦跑，並回報哪些角色長得不對。
- **真的 DeepSeek 抽取**：`scan`／`draft` 只用假模型驗過流程。同一份驗收文件有指令；請比較 DeepSeek 抽出來的和 `work/mars_war` 的手工草稿。
- Windows 上的 `pytest`。雲端 Linux 全部測試通過（230 項；煙霧測試需要使用者電腦的 ComfyUI，未跑）。
- S5 留下的未驗證項目照舊（見下）。

### 流程提醒

- 這台電腦沒有 shell 可用時，檔案透過檔案橋接寫入；git 提交要在你的終端機執行。

### S5 做了什麼（2026-11-08）

- 三階段：① 改編規劃 `plan/chNNN.json` → ② 漫畫劇本 `script/chNNN.md`（逐頁）→ ③ 分鏡 `storyboard/chNNN.json`（逐頁）。設計說明在 `docs/04_提示詞設計.md`。
- `t2c/prompts.py`（提示詞）、`t2c/script.py`（劇本解析、忠實度報告）、`t2c/check.py`（驗證）、`t2c/adapt.py`（流程、回修）、`tools/adapt.py`（命令列；`--show-prompt` 不需要金鑰就能看全文）。
- 回修：驗證失敗時把**全部**錯誤（寫明頁、格）接在模型上一次的輸出後面回給它，最多 3 輪；每輪從原始提示詞重來。分鏡最後過 `compile_chapter()` 才存檔。
- 範例原著 `examples/sample_comic/source/ch001.txt`（原創，對應既有的範例劇本與分鏡，可當參考答案）。
- 測試 `tests/test_adapt.py` 49 項（假模型＋一項走假伺服器）全過。

### S5 的決定

- **劇本是分鏡的唯一依據**：分鏡只看劇本（不看原著），台詞、旁白、狀聲詞逐字比對。人改劇本 → 重跑 `--stage storyboard` 即可。
- **語氣**：劇本標了（心聲）（喊）（小聲）或旁白時 `kind` 必須照做；沒標的一般台詞，分鏡可以判斷成 speech／shout／whisper（範例 k3 就是這樣）。
- **每行 ≤ 12 字**（旁白 16）才不用 `\n`，解掉 S3 backlog 的斷詞問題；提示詞要求 8–10 字。
- **外觀詞**：scene／pose／expression 出現 wear、dressed in、「顏色或長短＋hair／eyes」、bangs、ponytail 就擋（規則 3）。可能有誤擋，實測後再調 `check.APPEARANCE`。
- 劇本與分鏡**逐頁**產生、前綴相同（快取）；`--page N` 只重做一頁，其他頁（含人改過的）不動。
- `id` 一律由程式補，模型寫的被覆蓋；多餘欄位丟掉並列在提醒。
- 提示詞範例用虛構角色（阿杰、小晴），測試保證範例本身通過檢查並能編譯。
- 授權（待決問題 6）：lhfer/codex-novel-to-comic-studio 是 MIT；只參考分工，沒有複製文字。
- 沒做介面（S7）與視覺聖經自動抽取（S6）；聖經沒有角色卡的人物會列在規劃的 `unlisted_characters`。

### 待決問題

1. （S2 留下）預設用 `final` 還是 `draft`；`config.example.json` 目前是 `final`。
2. （S1 留下）int8 文字編碼器＋CPU 沒有測。
3. （S1 留下）雙人以上的左右位置句只驗證過一格（k5）。
4. （S1 留下）4-step LoRA 是否完整套用沒有證明。
5. （S2 留下）黑白網點／二值化後製要不要做：請看嵌字後的 `pages/ch001/p001.png` 再決定。
6. （S3 留下）嵌字字型：Windows 上沒設定時會用微軟正黑體＋細明體；要發佈請裝 Noto Sans／Serif CJK TC 並填進 `config.json` 的 `lettering`。字級 9 pt 是否合適請看實際頁面。
7. `config.example.json` 的 DeepSeek `model` 是 `deepseek-flash`，沒有實測；請先跑 `python tools\llm_check.py --models` 確認帳號可用的名稱。
8. （S5）DeepSeek 要不要開思考模式（`reasoning`）：建議實測時比較 `adapt` 開 high 與關閉；`script`、`storyboard` 先關。

### 沒有驗證的

- **S5 用真的 DeepSeek 跑一章**：雲端沒有金鑰，只用假模型驗過流程。請在你的電腦（先 `setx DEEPSEEK_API_KEY …`）：

  ```powershell
  xcopy /E /I examples\sample_comic E:\comics\s5_test
  python tools\adapt.py E:\comics\s5_test 1 --force
  python tools\panels.py E:\comics\s5_test 1
  ```

  記下每階段回修幾次、`build\adapt\ch001\` 裡最後的輸出、`build\adapt\ch001_fidelity.md`，並和範例的 `script\ch001.md`、`storyboard\ch001.json` 比較，人工評分改編是否忠實（S5 驗收的後半）。回修常失敗的規則請回報，用來調整提示詞或放寬檢查。
- **llama.cpp**：使用者指示 S5 先不測；S4 的連線也還沒實測。
- **S4：真的 DeepSeek 與 llama.cpp 連線**：雲端沒有金鑰也沒有 llama-server，只用假伺服器驗過協定。請在你的電腦執行 `python tools\llm_check.py`（兩個 provider 都要 ✓）和 `python tools\llm_check.py --stop-after 5`（要顯示已中斷）。特別是 llama.cpp 按停止後 GPU 是否真的停止生成，請看 llama-server 的視窗。
- Windows 上的 `pytest`（含 S3 的嵌字、介面）。
- 微軟正黑體／細明體的排字結果、多頁分鏡（S3 留下）。


### 流程提醒

- 這台電腦沒有 shell 可用時，檔案透過檔案橋接寫入；git 提交要在你的終端機執行。
- `pages/ch001/p001.png` 是嵌好字的頁面；要沒有字的版本加 `--no-letter`。

## 之前的階段

### S4（LLM 連線）做了什麼

- `t2c/llm.py`：OpenAI 相容 Chat Completions（DeepSeek、llama.cpp 的 llama-server）。`find_provider(cfg, provider_id, stage)`、`chat()`（串流、`on_delta`／`on_thinking`、重試、`should_stop`）、`chat_json()`、`parse_json()`、`estimate_tokens()`／`check_context()`。providers 欄位與 Novel Studio 相同；金鑰先讀環境變數 `key_env`，再讀系統金鑰庫（服務 `novel-studio`、帳號 = provider id，和另外兩個專案共用，只讀不寫，需要 `pip install keyring`）。
- `tools/llm_check.py`：對每個 provider 要一份 JSON；`--stop-after N` 測停止；`--models` 列模型。
- `tests/test_llm.py` 39 項，用本機假伺服器（SSE、429／5xx、斷線、慢速串流、取消），雲端 Linux 全過。
- 資料格式與 `config.json` 沒有新欄位（`reasoning` 為選填）。細節見 `CHANGELOG.md` 0.4.0 與 `docs/03_建置與環境.md` 第 5 節。

### S4 的決定

- **不做內容驗證**：`chat_json()` 只處理 JSON 語法（錯了回修一次）。分鏡規則的驗證與回修（CLAUDE.md 規則 6）在 S5，用 `compile_chapter()` 的錯誤訊息，建議在 `chat_json()` 上層用同樣的「assistant 原文＋user 錯誤」格式再包一圈。
- **停止靠背景執行緒**：socket 讀取不能被中斷，所以讀取放在執行緒、主執行緒輪詢，取消時 `shutdown` socket。呼叫端收到 `llm.Cancelled` 後要自己呼叫 `job.checkpoint()`（核心不 import fekit）。
- **已吐字後斷線不重試**，避免輸出重複；呼叫端看到錯誤要整段重來。
- **思考強度**：`reasoning` 設定沿用 Novel Studio（`deepseek`、`openai_effort`、`qwen_template` 三種 adapter），`stage` 參數對應 `adapt`／`script`／`storyboard` 這類階段名稱；`config.example.json` 沒有填 `reasoning`，S5 實測 DeepSeek 後再決定要不要開。
- 沒做 `app.py` 的 LLM 端點與介面，那是 S5 以後（S7 整合進介面）。


### S3（嵌字）做了什麼

- `t2c/letter.py`：嵌字。對話框五種（`speech` 橢圓、`thought` 雲狀＋小圓點、`shout` 爆炸、`whisper` 虛線、`narration` 方框）；尾巴指向說話者臉框、停在臉外；直排繁中（`，。、` 置中、括號／刪節號轉 90 度、`！？` 縱中橫、禁則、標點後優先換欄、`\n` 強制換欄）；自動位置避開臉、其他對話框、重要物件，並顧閱讀順序；狀聲詞黑字白邊；`vertical: false` 時橫排。
- `t2c/compose.py`：抽出 `page_panels()`（每格的像素框、裁切範圍 window），嵌字用它把分鏡座標換到裁切後的格子；新增 `render_page()`、`save_page()`。
- `tools/pages.py`：預設組版＋嵌字；`--no-letter`、`--guides`（畫臉框、anchor）。
- 介面「嵌字」頁（`web/static/letter.js`＋`app.py` 的 `/api/letter/*`）：拖對話框、尾巴、臉框（可新增、刪除、縮放）、狀聲詞；改字級、每欄字數、尾巴有無；存檔寫 `letters/chNNN.json` 並重新輸出頁面。
- 資料格式：`letters/chNNN.json`（`docs/02_資料格式.md` 第 10 節）；`config.json` 的 `lettering` 多了 `shout_font`、`dialogue_pt`、`narration_pt`，字型可留空自動找（`docs/03_建置與環境.md` 第 7 節）。
- 驗收紀錄：`docs/qa/S3_嵌字驗收.md`（含成品圖）。測試 120 項在雲端 Linux 全過（嵌字 65、API 2）。

### 決定與取捨

- **嵌字在組版後的整頁上做**，不是逐格：對話框以格子為界（不跨格、不出血），但位置要看裁切後的畫面。
- 分鏡的座標相對於「生成的圖」，`letters/` 的座標相對於「裁切後的格子」（人在成品上拖的）。改了 picks 的焦點／放大，自動的對話框與臉框會跟著圖走，手動的不會。
- 臉的位置是從分鏡角色框**推估**（上緣、高度依鏡頭）。範例頁剛好推得準，不需要微調；S1 實測角色常不照框畫，所以介面可以直接改臉框。自動偵測記在 backlog。
- 微調只記「和自動不同的部分」，存檔時去掉空項；每個對話框覆寫記下當時的台詞，分鏡改台詞後會警告。
- 沒有中文斷詞：長句的斷欄只靠標點與評分。範例的兩句長台詞已用 `\n` 分句；S5 要讓 LLM 自己加 `\n`。
- 預設字級對話 9 pt、旁白 8.5 pt（254 dpi 時 32／30 px）。

## 下一階段：M1 里程碑驗收

先讀：本檔 → `docs/00_階段計畫.md` 的 M1。要另開對話、不能讓做的人自己驗：從一章小說到 PDF 全流程，檢查 `CLAUDE.md` 的架構規則與 `docs/02_資料格式.md` 的格式是否被遵守，結果寫進 `docs/qa/M1.md`。需要在 Windows 上用真的 ComfyUI 與 DeepSeek 走一遍（S1–S8 留下的「沒有驗證的」項目都在這裡收）。

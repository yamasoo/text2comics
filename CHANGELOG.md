# 更新紀錄

## 1.0.0 — 2026-11-09（M1 里程碑標完成）

M1（從一章小說到 PDF 的全流程驗收）的雲端部分全部通過：pytest 全過、用非範例章節走完 小說 → 規劃 → 劇本 → 分鏡 → 編譯 → 出圖 → 組版 → 嵌字 → PDF／CBZ、`CLAUDE.md` 的架構規則與 `docs/02_資料格式.md` 的格式逐條檢查。Windows 實機上的 7 步驗收（LLM 連線、DeepSeek 實跑、實際出圖、閱讀器右翻、定裝圖挑選）沒有逐項做，開發紀錄與後續修正留在 `dev` 分支。這一版只有文件變更，沒有程式變更。

## 0.9.0 — 2026-11-09（M1 修正）

依 M1 驗收紀錄修 M-1、M-2、M-3 與 L-1–L-7。M-4（長得像的角色）等使用者決定記號；L-8–L-12 未動。

- **M-1 畫面外的說話者（格式變更，`docs/02_資料格式.md` 第 4、5、10 節）**：
  - 對話框新增種類 `radio`（通訊、電話、廣播：細密規則鋸齒的電子音框）與選填欄位 `offscreen`（預設 `false`）。`offscreen: true` 時 `speaker` 仍必填、必須是聖經角色，但**不可以**列在這一格的 `characters`；不送進生圖、不算進「exactly N people」。`thought`、`narration` 不能 offscreen。
  - 嵌字：offscreen 的 speech／shout／whisper 尾巴指向最近的格框邊（左右優先）、伸出框外被框切掉；offscreen 的 radio 沒有尾巴；radio 但說話者在畫面上（螢幕裡的臉）尾巴照常。尾巴都能在嵌字頁覆寫。
  - 劇本新增標記 `（通訊）`／`（電話）`／`（廣播）`／`（無線電）`→ radio，`（畫面外）`→ offscreen，可併寫 `（畫面外、喊）`；（通訊）不能再加語氣，（畫面外）不能和心聲併用。分鏡檢查會比對：劇本（通訊）→ kind 要 radio；劇本（畫面外）→ 要 offscreen。
  - 提示詞：劇本規則加聲音來源標記與「隔著通訊對話時，每一格只畫一邊的人」；分鏡規則 4 改成「不在畫面上的人不要列進 characters，加 offscreen」（拿掉舊的「把他放在畫面邊緣」）；範例加一句 `阿杰（畫面外、喊）`。
  - 介面：分鏡編輯區的對話框多「畫面外」勾選，勾了以後說話的人可以選不在這一格的角色；種類多「通訊（電子音）」。
  - 舊的分鏡、劇本照樣能讀（沒有新欄位＝和以前一樣）。
- **M-2 對話框閱讀順序**：
  - `letter.order_conflict()`：右翻時後一個對話框會不會先被讀到（整個在上面、跑到右上方、差不多高但整個在右邊）。自動擺位的順序成本從 0.6 提高到 2.0 並改用這個判斷；擺完再檢查一次，順序顛倒就列警告、標 `order_issue`，嵌字頁把那個框畫成紅框。
  - 分鏡檢查：anchor 順序顛倒列提醒（`check.anchor_order_issues`）。
  - M1 的〈大夜班〉：31 組對話框裡順序錯的從 4 組變成 0 組，沒有新增壓臉。
- **M-3 `t2c/` 自足**：`layouts/pages.json` → `t2c/data/pages.json`，`workflows/moss_layout.api.json` → `t2c/data/moss_layout.api.json`（**舊檔請刪掉**）。`settings.load(path=None, root=None)` 要由呼叫端給設定檔或所在資料夾；`workspace.create_project(..., sample=範例資料夾)` 取代 `from_sample=True`；新增 `comfy.workflow_path(cfg)`／`config_workflow(cfg)`：`comfy.workflow` 留空或舊寫法 `workflows/moss_layout.api.json` 都用內建的，相對路徑以 `config.json` 所在資料夾為準。`config.example.json` 的 `workflow` 改成空字串。工具資料夾的位置現在只在 `app.py`、`server/common.py`、`tools/*.py`。
- **L-1** 外觀字：補髮色髮型（dark、tousled…）、twin tails、眼鏡、鬍子、光頭、`in a … uniform／dress`；`wearing a headset` 等道具放行；單獨出現的衣物名詞（jacket、lab coat）只提醒。
- **L-2** 人改的分鏡有重複的格 id 或頁碼就不存檔。
- **L-3** 忠實度報告：整句找不到時依句讀拆開再比（兩句原文併成一個對話框不算改寫）；兩三個字的短片段要和原著某一句整句相同才算，所以「……是我」這種改寫仍會列出。
- **L-4** 規劃的 `source`（原著依據）在原著找不到時提醒（可用「……」省略中間）。
- **L-5** 提示詞裡角色的「設定」只取卡片本文第一段（不再帶進「待確認」「原文依據」等標題）。
- **L-6** 錯誤訊息裡引用的台詞，換行顯示成 ⏎。
- **L-7** 範例的出圖不進版控：`test_create_project_from_sample_with_renders` 在範例沒有出圖時跳過；新建專案勾「連同範例的出圖」而範例沒有圖時，介面停用勾選、核心回明確的錯誤（`/api/info` 多回傳 `sample_renders`）。
- 測試：新增 `tests/test_offscreen.py`（M-1）、`tests/test_portable.py`（M-3：只複製 `t2c/` 到別處也能 import、讀模板與 workflow、編譯一章）、`tests/test_m1_fixes.py`（M-2、L-1–L-6）；全部 335 項在雲端 Linux 通過，模擬新 clone（範例沒有出圖）也全過（2 項跳過）。

## 0.8.0 — 2026-11-09（S8：輸出）

- 新增 `t2c/export.py`（只用標準函式庫與 Pillow）：已輸出的 `pages/chNNN/pNNN.png` → PDF 或 CBZ，整章或單頁，輸出到專案的 `out/`（不進版控）。格式見 `docs/02_資料格式.md` 第 15 節。
  - **PDF**：自己寫檔（Pillow 的 PDF 輸出不能設閱讀方向）。`/ViewerPreferences << /Direction /R2L >>`、預設雙頁檢視（`/PageLayout /TwoPageRight`，第 1 頁單獨在右）、`/Lang`、`/Title`；頁面大小由 PNG 的 dpi 換算（B5＝515.9×728.5 pt）；內頁預設 JPEG 品質 90，可調或無損（Flate）。
  - **CBZ**：頁面 PNG 原檔＋ `ComicInfo.xml`（`Manga` = `YesAndRightToLeft`、第 1 頁 `FrontCover`、每頁寬高）。
  - 不重新組版：缺頁就報錯（一次列出缺的頁碼）；PNG 比分鏡、選圖、嵌字舊時列提醒；同樣輸入產生同樣位元組；寫完才換名，不會留下半個檔。
- 新增 `tools/export.py`（`--format pdf|cbz|all`、`--page`、`--out`、`--quality`、`--lossless`、`--single`）。
- 介面：「頁面」分頁加「整章 PDF／整章 CBZ／這頁 PDF」下載與「PDF 用單頁檢視開啟」；頁面沒輸出齊時按鈕停用並說明。新增 `GET /api/chapter/export`，`GET /api/chapter/pages` 多回傳 `export`（`docs/05_介面設計.md`）。
- 測試：新增 `tests/test_export.py` 22 項（解析 PDF 的 xref 與頁序、右翻旗標、無損像素、CBZ 與 ComicInfo、可重現、缺頁／壞圖／提醒、命令列）、`tests/test_ui.py` 1 項（下載）。雲端 Linux 以 poppler 實際轉出 PDF 的頁面，頁序與內容正確，`qpdf --check` 無錯。

## 0.7.0 — 2026-11-09（S7：介面）

- **介面**（`docs/05_介面設計.md`）：
  - 專案頁：開啟（路徑或瀏覽）、最近開過、新建（空白或複製範例，可連同範例出圖）、章節表（各階段有沒有檔案、出圖與選圖進度）、視覺聖經摘要、環境檢查（ComfyUI 與 VRAM、各模型的金鑰、本機 LLM 是否在執行）。
  - 章節頁分頁：原著（貼上、從檔案匯入）、規劃（表格檢視、重新產生、進階改 JSON）、劇本（Markdown 檢視與編輯、只重寫某頁、忠實度報告）、分鏡（一頁一張表；點一格開編輯區：欄位、在格子比例的畫布上拖角色／物件／狀聲詞框與對話框位置、即時編譯的 MOSS 提示詞；換模板、加頁）、出圖（候選縮圖點選即選圖、裁切焦點與放大即時預覽、整章／整頁／一格出圖、加畫 N 張、同 seed 重畫、出圖預設）、頁面（即時嵌字預覽、輸出 PNG、到嵌字頁微調）。
  - 「整章批次」：規劃 → 劇本 → 分鏡 → 出圖 → 輸出頁面，已有的檔案跳過，可勾「重做」。
  - 視覺聖經頁：草稿清單與一鍵確認入庫、卡片編輯（卡片原文與「待確認／原文依據」並排、存檔即檢查）、新增卡片（規劃裡缺卡的人物一鍵建立）、定裝圖出圖、加畫與挑選、改了定案卡片會提醒定裝圖過期。
  - 嵌字頁沒帶專案時用目前開啟的專案。
- **VRAM 排程**（`t2c/gpu.py`）：任務排隊、一次一個；呼叫本機 LLM 前請 ComfyUI 卸下模型（`POST /free`）；出圖前若本機 llama-server 還在執行（`GET /health`），任務暫停詢問「已關閉，繼續／照樣出圖／停止」。
- 新增核心模組（只用標準函式庫、PyYAML、Pillow）：`t2c/workspace.py`（總覽、新建專案、原著／規劃／劇本／分鏡的讀寫與檢查、每格出圖狀態、選圖、加畫用的 seed）、`t2c/render.py`（逐格出圖，介面用；可停止、有進度事件）、`t2c/gpu.py`。
- 新增 `server/`（API 與背景任務）：`project_api.py`、`bible_api.py`、`tasks.py`、`common.py`；`app.py` 只組起來並保留嵌字端點。拿掉 S0 的示範端點（`/api/hello`、`/api/demo-task`）。
- **加畫的 seed**：仍由格 id 決定，從候選編號 0 往上找還沒畫過的（`workspace.next_seeds`），所以可重現、不覆蓋舊圖。
- **修正**：`compose.candidates()` 沒列出帶出圖預設後綴的候選（`…_s123_draft.png`），和它的說明不符；現在會列出。
- 人在介面改的分鏡：先過 `compile_chapter()`（不過就擋），其他檢查列成提醒；劇本、原著、草稿卡照存並回報檢查結果；定案卡片有錯就擋。資料格式沒有改變。
- 測試：新增 `tests/test_ui.py` 13 項（假模型、假 ComfyUI、假本機伺服器）；`test_smoke.py` 改成不依賴示範端點。雲端 Linux 全部 249 項通過。

## 0.6.0 — 2026-11-08（S6：視覺聖經）

- 新增 `t2c/bible_check.py`（純規則）：`look_en` 必須英文、≥ 6 字、有性別與年齡字，不得含服裝／表情／動作字；服裝要有 `default`、以 `He/She/They wears` 開頭、人稱與 `look_en` 一致；地點不得有人物字。掃描結果每條外觀事實要附原文逐字引文，對不上就丟掉。
- 新增 `t2c/bible_prompts.py`：掃描與成卡的提示詞（範例用虛構人物，測試保證範例通過檢查；字表和檢查共用同一份）。
- 新增 `t2c/bible.py`：`Builder`（逐章掃描 → 合併證據 → 逐人成卡；失敗把全部錯誤回修，最多 `max_fix`；章節雜湊快取）、`lint()`、`accept()`（草稿 → 定案，先過檢查，不覆蓋既有定案卡）、`sheet_jobs()`／`render_sheets()`（定裝圖：角色全身與胸像各服裝一組、地點一張，重用 `compile_chapter()` 與 ComfyUI）、`contact_sheet()`（Pillow 拼比較表）、`pick()`（挑選紀錄與過期偵測）、`status()`／`matrix_markdown()`（服裝矩陣：誰有哪些服裝、有沒有定裝圖、被哪些章用到）。provider 階段名 `bible`。
- 新增 `tools/bible.py`：`extract`、`scan`、`draft`、`check`、`accept`、`sheet`、`contact`、`pick`、`status`；`--show-prompt` 不需要金鑰。
- **資料格式新增**：角色卡 `outfit_notes`、`status`；`bible/drafts/`、`bible/picks.json`；`build/bible/`、`renders/bible/`（`docs/02_資料格式.md` 第 3、13 節）。舊卡片不受影響。
- `config.example.json`：`stage_providers.bible`。`.gitignore`：`work/`。
- 測試：新增 `tests/test_bible.py` 30 項（假模型；一項走假伺服器；出圖用假的 ComfyUI）；全部測試（不含需要 ComfyUI 的 `test_smoke.py`）在雲端 Linux 共 230 項通過。
- 範例：`work/mars_war` 的《第一次火星獨立戰爭》8 張角色與 9 張地點草稿（尚未確認，不是範例專案的一部分）。

## 0.5.0 — 2026-11-08（S5：文字端提示詞）

- 新增 `t2c/prompts.py`：三階段提示詞（改編規劃、漫畫劇本、分鏡 JSON）。模板清單由 `layouts/pages.json` 自動產生（每格的位置與形狀）；範例用虛構角色；同階段的前綴完全相同，DeepSeek／llama.cpp 的前綴快取會生效；每次只送 system＋一則 user。
- 新增 `t2c/script.py`：劇本解析（頁、格、鏡頭詞、角度詞、語氣標記、旁白、狀聲詞）、說話者對應聖經（姓名／別名／id）、劇本檢查、忠實度報告（台詞與原著逐字比對、原著引號台詞是否保留）。
- 新增 `t2c/check.py`：改編規劃與分鏡頁的驗證，一次列出全部錯誤（寫明頁、格）。分鏡台詞必須和劇本逐字相同（只能加 `\n`）、每行 ≤ 12 字（旁白 16）、英文欄位不可有中文、不可描述外觀、說話者要在場、座標與 id 合法、每格 ≤ 3 個對話框。
- 新增 `t2c/adapt.py`：`Adapter.run_plan()`／`run_script()`／`run_storyboard()`／`run_all()`。產生 → 驗證 → 把全部錯誤回給模型修（最多 `max_fix` 次，預設 3）→ 分鏡最後再過 `compile_chapter()` 才存檔。劇本、分鏡逐頁產生，可以只重做指定頁（其他頁、含人改過的維持原樣）；不覆蓋既有檔案（要 `force`）；模型原始輸出存在 `build/adapt/`；可依階段選 provider（`adapt`／`script`／`storyboard`）。
- `t2c/project.py`：新增 `source_path()`、`load_source()`（略過 frontmatter）、`plan_path()`、`script_path()`、`load_plan()`。
- 新增 `tools/adapt.py`：`--stage`、`--pages`、`--page`、`--provider`、`--force`、`--max-fix`、`--show-prompt`（只印提示詞，不需要金鑰）、`--stream`。
- **資料格式新增**：`source/chNNN.txt`、`plan/chNNN.json`（`docs/02_資料格式.md` 第 11、12 節）；劇本格式補上鏡頭詞表與語氣標記 `（喊）`、`（小聲）`（第 4 節）。分鏡格式沒有新欄位，補充每格 ≤ 3 個對話框、每行字數的規則。
- 範例：新增 `examples/sample_comic/source/ch001.txt`（原創，對應範例劇本）。
- 新增 `docs/04_提示詞設計.md`。
- 測試：新增 `tests/test_adapt.py` 49 項（腳本化假模型；最後一項透過假伺服器走真正的 `llm.chat_json`）；`test_core`、`test_llm`、`test_adapt` 在雲端 Linux 共 115 項，除了一項因工作區缺 `tools/panels.py` 無法執行外全部通過。

## 0.4.0 — 2026-11-08（S4：LLM 連線）

- 新增 `t2c/llm.py`（只用標準函式庫）：OpenAI 相容的串流 `chat()`、`chat_json()`（JSON 模式；語法錯誤時把錯誤回給模型修一次；`finish_reason=length` 直接報錯）、`parse_json()`（容忍 ```json 圍欄與前後雜訊，物件或陣列）。
- 重試：429、408、5xx、連線失敗、尚未收到任何字就斷線，最多 3 次，等待 2／4／8 秒（尊重 `Retry-After`）；401、402、404 等不重試；已經吐出字之後斷線不重試（會重複）。
- 取消：`should_stop` 在背景執行緒讀取、主執行緒每 0.2 秒檢查；按停止會切斷連線（本機模型也跟著停）並丟出 `Cancelled`。介面任務傳 `lambda: job.stopping`。
- token 估算：`estimate_tokens()`、`estimate_messages()`、`context_left()`、`check_context()`；中日韓字乘 `cjk_token_ratio`（沒設定時 DeepSeek 0.6、其他 1.2）。
- providers 沿用 Novel Studio 的欄位（`base_url`、`model`、`key_env`、`context_tokens`、`max_output`、`temperature`、`json_mode`、`extra`、`reasoning`）；`find_provider()` 依 指定 → `stage_providers` → `default_provider` 選。金鑰來源：環境變數 → 系統金鑰庫（服務 `novel-studio`、帳號 = provider id，與另外兩個專案共用，只讀不寫；需要 `pip install keyring`，沒裝就略過）。`list_models()` 也會先檢查金鑰。
- 新增 `tools/llm_check.py`：對每個 provider 要一份 JSON；`--stop-after N` 測停止；`--models` 列模型。
- 資料格式沒有變動；`config.json` 沒有新欄位（`reasoning` 為選填，格式同 Novel Studio）。
- 測試：新增 `tests/test_llm.py` 39 項（本機假伺服器）；雲端 Linux 全過。

## 0.3.0 — 2026-11-08（S3：嵌字）

- 新增 `t2c/letter.py`：對話框（橢圓、雲狀思考＋小圓點、爆炸喊叫、虛線悄悄話、旁白方框）、尾巴指向說話者的臉、直排繁中（欄由右到左、`，。、` 置中、括號與刪節號轉 90 度、`！？` 縱中橫）、斷行禁則、自動避開臉／其他對話框／重要物件、狀聲詞（黑字白邊、可傾斜）、橫排模式。
- `t2c/compose.py`：新增 `crop_box()`、`crop_window()`、`page_panels()`、`render_page()`、`save_page()`、`find_page()`；`compose_chapter()` 多了 `lettering`、`letters`、`guides` 參數（不給 `lettering` 時行為與 0.2.0 相同）。
- `tools/pages.py`：預設組版後嵌字；新增 `--no-letter`、`--guides`、`--config`。**`pages/chNNN/pNNN.png` 現在是嵌好字的頁面**，要沒有字的版本加 `--no-letter`。
- 介面新增「嵌字」頁（`web/static/letter.js`）：拖對話框、尾巴尖端、臉框、狀聲詞；改字級、每欄字數、尾巴有無；按「存檔」寫入 `letters/chNNN.json` 並重新輸出頁面。API：`/api/letter/plan`、`/api/letter/preview.jpg`、`/api/letter/art.png`、`/api/letter/save`。
- **資料格式新增**：`letters/chNNN.json`（格式版本 1），見 `docs/02_資料格式.md` 第 10 節；`config.json` 的 `lettering` 新增 `shout_font`、`dialogue_pt`、`narration_pt`，字型可以留空自動找（第 03 文件第 7 節）。分鏡格式沒有新增欄位，只補充說明：座標相對於生成的圖、台詞裡的 `\n` 強制換欄。
- 範例分鏡：k3 的喊叫、k5 的心聲加上 `\n` 分句（自動斷句會把「教／授」拆開）。
- 測試：新增 `tests/test_letter.py` 65 項、`tests/test_smoke.py` 2 項（嵌字 API）；全部 120 項在雲端 Linux 通過。
## 0.2.0 — 2026-11-08（S2：組版）

- 新增 `t2c/compose.py`：選圖紀錄 `picks/chNNN.json`、cover 裁切（`focus`、`zoom`）、格框與頁邊、輸出 `pages/chNNN/pNNN.png`（B5 比例 1820×2570、254 dpi、預設灰階）。
- 新增 `tools/pages.py`：`--list`、`--pick`、`--focus`、`--zoom`、`--numbers`、`--color`、`--out`。
- **資料格式新增**：`picks/chNNN.json`（格式版本 1），見 `docs/02_資料格式.md` 第 8、9 節。既有的 `project.yaml`、分鏡、聖經、模板沒有變動。
- 範例：新增 `examples/sample_comic/picks/ch001.json`（S1 初選的 5 張）。
- 測試：新增 `tests/test_compose.py` 20 項；`pytest tests/test_core.py tests/test_compose.py` 47 項全過（雲端 Linux）。

## 0.1.2 — 2026-11-08（S1：出圖預設）

- `config.json` 新增 `comfy.presets`、`comfy.default_preset`：每組可覆蓋 `steps`、`cfg`、`sampler`、`scheduler`，並可接 LoRA（`lora`、`lora_strength`）。`config.example.json` 附 `final`（照原 workflow）與 `draft`（4 步＋`moss_image_sft_4step_v2.0` LoRA）。沒有 `presets` 時行為與 0.1.0 相同。
- `t2c/comfy.py`：新增 `apply_preset()`、`render_name()`；`prepare()` 多一個 `preset` 參數。
- `tools/panels.py`：新增 `--preset`、`--seed`；非預設的出圖預設，檔名加 `_<預設名>` 後綴。
- 測試新增 6 項（含用假的 ComfyUI 跑命令列）；`pytest tests/test_core.py` 27 項全過。
- 專案資料格式（`project.yaml`、分鏡、聖經）沒有變動。

## 0.1.1 — 2026-11-08（S1 實測後的調整）

- 編譯：每格 summary 固定加 `The image has no border or frame.`（放在「不要對話框」句之前），避免圖內多畫邊框。
- 編譯：一格有 2 個以上角色時，角色 caption 最前面加左右位置句（依 `box` 中心判斷；He／She 由 `look_en` 推斷）。
- 範例：`project.yaml` 的 `candidates` 2 → 3；第 2 格的「a hand」改成「one hand」。
- 測試：新增 3 項（無邊框句、左右位置句、`side_of_frame` 門檻）。
- 資料格式沒有新增欄位。

## 0.1.0 — 2026-11-08（S0）

- 用 fekit 0.0.1 範本建立專案（模組：i18n、md、filepicker、table）。
- 核心 `t2c/`：格子模板與 MOSS bbox 換算、漫畫專案讀取、分鏡編譯、ComfyUI 客戶端。
- 資料格式第 1 版：`project.yaml`、角色／地點卡、漫畫劇本、分鏡 JSON（見 `docs/02_資料格式.md`）。
- 命令列 `tools/panels.py`；範例專案 `examples/sample_comic/`；測試 `tests/test_core.py`。

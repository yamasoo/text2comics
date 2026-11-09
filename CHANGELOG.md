# 更新紀錄

## 1.7.0 — 2026-11-09（介面入口：畫風預設集＋整本匯入切章，N7）

兩個「後端早就做好、介面沒有入口」的洞補起來：畫風預設集（N5 的待決問題 25）與整本匯入切章（N2 延後項）。核心與 CLI 都沒有重寫，只是把既有的 `t2c/styles.py`、`t2c/importer.py` 接上介面。

- **畫風（`t2c/workspace.py` 的 `set_style_preset()`，新增）**：換一部作品的畫風＝改 `project.yaml` 的 `style_preset`，並**拿掉明寫的 `style`／`meta`／`look`／`sfx`**（那幾欄會蓋掉預設集，不清掉就會「選了彩色卻沒變」）；`#` 開頭的註解行不動，回傳 `dropped` 說拿掉了哪些。名稱不認得丟 `WorkspaceError` 並列出 `american／color／mono`，失敗不寫檔。
- **API（`server/project_api.py`）**：`GET /api/styles`（三組預設集與中文標籤）、`POST /api/project/style`（換畫風並回最新 `overview`）、`/api/project/create` 收 `style_preset`；`POST /api/import/plan`（切章預覽，**不寫檔**）與 `POST /api/import/commit`（寫 `source/chNNN.txt`，`conflict` 支援 skip／overwrite，覆蓋前備份）。`styles.StylesError` 與 `importer.ImporterError` 都接進共用的 400 轉換。
- **介面（`web/static/project.js`）**：新建專案的「畫風」改成預設集下拉（`GET /api/styles`，預設選 `default`），下面留一個 `<details>` 的「自訂畫風（進階）」文字框（有填才送 `style`）；專案頁多一張「畫風」卡（顯示目前預設集名稱＋下拉，換了就寫回 `project.yaml`，並說明「畫風要在分鏡／編劇本之前改，已畫好的圖不會重畫」、若有 `dropped` 會寫出拿掉了哪些欄位）；專案頁多一顆「**匯入整本切章…**」（選檔 → 切章方式／章號編號／重複匯入／簡轉繁／把開頭當一章 → **預覽表格**（章號、章名、字數、旗標、開頭摘錄、提醒）→ 匯入 → 寫入／跳過／覆蓋摘要），任何選項一改預覽就作廢、匯入鈕回到停用（避免拿過期預覽去寫檔）。
- **測試**：`tests/test_styles_import.py`（10 項：換畫風與拿掉明寫欄位、註解行保留、亂寫名稱會擋且不寫檔、非專案資料夾、`/api/styles`、`/api/project/style` 成功與 400、`/api/import/plan` 六章且**用資料夾樹快照證明沒寫檔**、`/api/import/commit` 的 skip／overwrite＋備份）；`tests/test_ui.py` 追加 2 項。全專案 **529 passed, 1 skipped**（基準 517／1）。版本 1.7.0。
- **實機驗證（1280×800 瀏覽器，本機伺服器）**：專案頁換畫風 mono→color → `project.yaml` 變成 `style_preset: color`、明寫的 `style`／`meta` 被拿掉、畫面顯示「已拿掉 project.yaml 裡明寫的 style／meta，不然會蓋掉預設集」；「匯入整本切章」用 `tests/data/n2_sample_six_chapters.txt` → 預覽「共 6 章、合計 534 字」＋章名表 → 匯入「寫入 5 章（398 字）、跳過 1 章、覆蓋 0 章」（第 1 章專案裡已有，正確跳過），`source/ch002.txt` 第一行是 `# 第2章 失約`。截圖與紀錄在 `docs/qa/N7.md`。
- **文件**：`docs/05_介面設計.md` 第 5 節的 API 表補四列；`docs/03_建置與環境.md` 第 4.7 節（profile）之外另記畫風與匯入的入口。

## 1.6.0 — 2026-11-09（出圖設定與 LLM 設定改善，N6）

設定頁從「一堆 JSON 文字框」變成「一組出圖 profile 一張卡」，並且可以測 LLM 連線、把金鑰存進系統金鑰庫；出圖頁與視覺聖經的 profile 下拉會說清楚「這是哪一組模型」。核心沒有新依賴（ComfyUI 的模型清單只用標準函式庫問 `/object_info`）。

- **出圖 profile 清單與猜模型（`t2c/comfy.py`）**：移植 Novel Studio `studio/comfy.py` 的 `object_info`／`model_lists`／`guess_models`（只用標準函式庫，沒有 import 那支 repo），並補上取樣器與排程器清單：`available_models(base)` 回 `{unet, clip, vae, lora, sampler, scheduler}`，`guess_models(kind, lists)` 依檔名猜 moss／anima 該用哪三個模型（關鍵字表在 `GUESS`）。
- **`GET /api/comfy/models`**：設定頁的模型下拉。ComfyUI 沒開回 `ok: false`＋一句話（HTTP 200），介面直接顯示那句話；帶 `?kind=anima` 多回 `guessed`（「依 kind 自動挑」用的三個檔名）。
- **`POST /api/llm/probe`**：單一 provider 的連線探測（內部就是 `llm.list_models()`），回 `{ok, models, ms, message}`；失敗也是 200，訊息給介面顯示。沒有塞進 `/api/env`（那裡每次開頁面都會打，探測是使用者按了才打）。
- **`POST /api/llm/key`**：把貼進來的金鑰交給 `keyring.set_password("novel-studio", provider id, key)`，**不寫任何檔案**；存完下一次呼叫就生效（`api_key()` 的順序仍是環境變數優先，`t2c/llm.py:89` 沒變）。沒裝 keyring 回 `ok: false`＋安裝提示，介面維持唯讀。`t2c/llm.py` 新增 `keyring_available()`／`keyring_get()`／`keyring_set()`。
- **`/api/settings` 補資料**：多回 `stages`（可用階段：adapt、script、storyboard、bible、annotate、plan，來源是新的 `t2c/settings.STAGES`）、`keyring`（裝了沒有、服務名稱、提示）與 `keys[].keyring`（金鑰庫有沒有這一筆，只說有沒有、不說值）。
- **`GET /api/env` 依「這一章的 profile」**：帶 `project` 時 `comfy.profile`／`kind`／`unet`／`presets`／`default_preset` 都是 `project.yaml` 的 `comfy_profile` → `comfy.default_profile` 那一組；`comfy.profiles` 改成清單 `[{name, kind, unet}]`（沒有 `comfy.profiles` 的舊設定也回一組 moss）。專案路徑壞掉時當成沒開專案，設定頁不會因此打不開。`GET /api/chapter/panels` 另外回 `profile_info`（`profiles` 仍是名稱字串陣列，舊呼叫端不受影響）。
- **設定頁（`web/static/settings.js`，整頁重寫）**：一組 profile 一張卡（名稱、kind 下拉、workflow、unet／clip／vae 可自打＋datalist「從 ComfyUI 抓模型清單」、**依 kind 自動挑**、**複製這組**／**刪除這組**、negative、default_preset、presets 逐列編輯含 lora／lora_strength）；JSON 框收進 `<details>`「**進階：直接編輯 JSON**」預設收起。貼進 ComfyUI 的 workflow JSON（頂層鍵 1、2、3…含 `class_type`）當場顯示「**這是 workflow 不是 profiles；workflow 請填 profile.workflow 路徑或留空用內建**」，而且**不套用**（不會畫出 1～10 的假 profile）。**沒有 `comfy.profiles` 的舊 config 顯示成 moss 一張卡，按儲存升級成新格式**。provider 表每列多「**測試連線**」＋狀態 chip、「**存進金鑰庫**」（沒裝 keyring 時停用並顯示安裝提示）；階段下拉由 `stages` 產生（不再漏 annotate／plan）；存檔成功後重新 `GET /api/settings`＋`GET /api/env` 重整畫面，頁面明寫「**provider／模型／網址改完即生效，只有行程環境變數要重啟**」。
- **設定頁補「新增一組」**：原本只能「複製這組」（使用者回報：只有一組 moss 時不知道怎麼加 anima）。現在「預設 profile」旁邊有「新增一組」（新卡預設 kind=anima），只有一組時多一行步驟說明；**換 kind 會自動清掉另一種家族的 workflow 並重跑「依 kind 自動挑」**；workflow 欄旁邊直接寫出「這一組實際會用的檔案」（留空＝內建 `t2c/data/anima.api.json`／`moss_layout.api.json`，隨套件附）。流程寫進 `docs/03_建置與環境.md` 第 4.7 節。
- **出圖頁與定裝圖**：`web/static/panels.js` 與 `web/static/bible.js` 的 profile 下拉改成顯示「**anima · UnstableAnima-Art-V4.safetensors**」（值仍是 profile 名稱），換 profile 時提示「同一臺 ComfyUI 一次只掛一組模型：換 profile 請先在 ComfyUI 換模型」。定裝圖對話框多一個「出圖 profile」下拉，送進 `/api/task/bible_sheet`（`server/tasks.py:489` 早就收了）。
- **測試**：新增 `tests/test_comfy_models.py`（6 項）、`tests/test_llm_probe.py`（8 項），`tests/test_ui.py` 追加 6 項（env 的 profiles／這一章的 profile、panels 的 `profile_info`、舊設定的 `profile_info`、settings 的 stages／keyring、三個靜態檔的字串斷言）。全專案 **516 passed, 1 skipped**（基準 496／1）。版本 1.6.0。
- **實機驗證**（Windows，ComfyUI 開著、金鑰在系統金鑰庫）：`/api/comfy/models` 回 22 unet／9 clip／26 vae／406 lora／47 sampler／10 scheduler，`?kind=anima` 猜到 `UnstableAnima-Art-V4`／`qwen_3_06b_base`／`qwen_image_vae`；`probe` deepseek 拿到 `deepseek-flash`、`deepseek-v4-pro`（207 ms）；貼金鑰存進金鑰庫後不重啟就真的跑完一次 chat，`config.json` 前後 hash 相同；舊格式 `config.json` 在設定頁按儲存後長出 `comfy.profiles.moss`＋`default_profile`，並備份 `.bak`；「複製這組」→ 儲存後檔案多了 `moss_copy`。Before／After 截圖在 `work/n6_ui/shots/`（不進版控），紀錄在 `docs/qa/N6.md`。

## 1.5.0 — 2026-11-09（反推設定＋畫風，N5）

兩件事：① 從原著**反推視覺聖經草稿**（搬 novel-studio `studio/reverse.py` 的排程層，抽取與卡片仍走既有的 `t2c/bible.py`）；② **畫風變成預設集**（黑白／彩色／美式），`style`、`meta` 與文字端提示詞的畫風描述只有一個來源，順便把 `t2c/prompts.py` 寫死的「日式黑白頁漫」拿掉。舊的 `project.yaml`（明寫 `style`／`meta`）照舊可用且行為不變。

- **畫風預設集（`t2c/styles.py`、`t2c/data/styles.json`，新增）**：`mono`（日式黑白頁漫）／`color`（彩色日式頁漫）／`american`（美式彩色漫畫），每組有 `style`、`meta`、`look`（提示詞用的中文畫風描述）、`sfx`（狀聲詞交給 MOSS 畫時的英文）。`project.yaml` 用 `style_preset` 選一組，明寫的 `style`／`meta`／`look`／`sfx` **只蓋掉那一欄**。名稱不認得時錯誤訊息列出可用的 key。
- **提示詞去硬編碼（`t2c/prompts.py`）**：`SYSTEM` 改成含 `{look}` 的模板、新增 `system(look)`；`PLAN_RULES` 改成 `plan_rules(look)`；四個產生 messages 的函式（切對話、規劃、劇本、分鏡）都改吃 `styles.resolve(project.config)["look"]`。黑白專案的提示詞與改動前**逐字相同**（測試釘死舊字串）；彩色／美式專案的提示詞不含任何黑白字樣。
- **編譯（`t2c/compile.py`）**：`style`／`meta` 由預設集來（原本 `meta` 寫死 `["manga panel","black and white"]`），狀聲詞的文字描述也不再寫死 `in black ink`。
- **新建專案（`t2c/workspace.py`）**：`project.yaml` 改成寫 `style_preset: mono`，不再寫死 `style`／`meta` 兩行；`create_project(..., preset=)` 可以建彩色／美式專案，preset 不認得會在建立前就報錯。
- **反推排程（`t2c/reverse.py`、`tools/reverse.py`，新增）**：章節分批（一批最多 3 章）、用 `llm.estimate_tokens` 抓上下文預算（預設 32768 − 輸出預留 8192）、斷點續跑（`build/reverse/state.json`、`accumulated.json`、`batches/第NNN-NNN章.json`）、`--force` 全部重做。續跑以**單章**為單位：中間某一章的掃描快取失效，下一次只重掃那一章（不會靜默漏章，也不把後面的章一起重跑）。抽取與卡片提示詞不重寫，一律 `bible.Builder.scan()`／`draft()`；草稿只寫 `bible/drafts/`，要人按「採用」才進 `bible/characters|locations/`。
- **單章專案也會成卡**：`draft()` 的「出現 2 章以上才建卡」門檻改成 `min(2, 這次可用的章數)`——只有一章的專案所有角色都成卡，兩章以上維持既有規則；被跳過的名字用 `rare` 回報，CLI 會印出來。`t2c/bible.py` 的規則本身沒改。
- **測試**：新增 `tests/test_styles.py`（15 項）、`tests/test_prompts_look.py`（7 項）、`tests/test_reverse.py`（17 項）；全專案 `pytest`：**496 passed, 1 skipped**（基準 457／1）。版本 `t2c/__init__.py` 1.5.0。
- **真跑（deepseek-flash）**：範例小說《屋頂的便當》第 1 章（1 KB）→ 3 張草稿（2 角色＋1 地點）→ 規則檢查 0 問題 → 採用 → 編譯單格 832×1200、`look_en` 逐字貼進角色 caption；同一頁改 `style_preset: color` 重編譯，提示詞不含 `black and white`／`black ink`／「黑白」。《第一次火星獨立戰爭》第 1 章（4.7 KB，新專案）→ 6 張草稿（3 角色＋3 地點）、43 秒／7 次呼叫。紀錄在 `docs/qa/N5.md`。
- **文件**：`docs/02_資料格式.md` 第 2 節（`project.yaml` 欄位）、第 18 節（畫風預設集）、第 19 節（`build/reverse/`）；`docs/backlog.md` 記延後項（介面的畫風下拉、`--min-chapters`、美式左翻）。

## 1.4.0 — 2026-11-09（Anima 出圖＋版型外掛，N4）

出圖從「一組 MOSS workflow」變成「多組 profile」：同一臺 ComfyUI 可以換著用 MOSS-Image 與 Anima；版型（`pages.json`）可以由專案疊加或整份覆寫。舊的 `config.json` 照舊可用。

- **出圖 profile（`t2c/comfy.py`）**：`config.json` 的 `comfy.profiles.<名稱>` 每組帶 `kind`（`moss`／`anima`）、`workflow`（留空＝內建）、`models`（unet／clip／vae）、`presets`、`default_preset`、`negative`、`loras`；`comfy.default_profile` 是預設，`project.yaml` 的 `comfy_profile` 指定這一部作品用哪一組，`tools/panels.py --profile` 與介面／API 的 `profile` 可以臨時換。命名過的 profile 是自足的：不繼承頂層 `comfy.models`／`comfy.presets`（免得拿 MOSS 的模型或 4-step LoRA 去跑 Anima）。
- **內建 Anima workflow（`t2c/data/anima.api.json`，新增）**：照 Novel Studio 的 `examples/comfy/anima.api.json` 整理（`ModelSamplingAuraFlow` shift 5、CLIPLoader `lumina2`、`EmptySD3LatentImage`、12 步／cfg 1.8／`beta`），節點標題改成中文；MOSS workflow 仍叫 `moss_layout.api.json`，`kind: moss` 指到它。
- **檔名共存**：`<格 id>_s<seed>[_<預設>][__<profile>].png`，不是 `default_profile` 的才加 `__<profile>`，所以同一格同一 seed 用兩個 profile 各出一張不會互相蓋掉；`candidate_info()`、`existing_seeds()`、定裝圖的 `RENDER_RE` 都認這個後綴，既有 `renders/` 不必搬。
- **專案版型（`t2c/layout.py`、`t2c/project.py`）**：`project.yaml` 的 `layout: {file, mode}`（`merge` 預設＝疊加、同名換掉；`replace`＝只用專案檔的模板；`page` 只蓋有給的欄位）。`Project.pages()` 是唯一入口，編譯、組版、檢查、規劃檢查、介面都改用它；錯誤訊息寫出哪個檔案、哪個模板、第幾格、JSON 第幾行第幾欄。
- **介面**：出圖頁多「出圖 profile」下拉（換了會重新抓那一組的 presets，候選圖顯示 profile chip，重畫帶那一張自己的 profile）；分鏡編輯器的模板下拉標「專案」來源、顯示版型檔與模式，版型檔壞掉時把後端訊息原樣顯示（含檔名與第幾格）；設定頁的 ComfyUI 區多「預設 profile」與 profiles（JSON）。順手修掉分鏡頁 `replaceChildren(null)` 留在畫面上的 `null` 字串。
- **API**：`GET /api/chapter/panels` 回 `profiles`／`default_profile`／`project_profile`／`profile`／`kind`，並接受 `?profile=`（回那一組的 presets）；`GET /api/chapter/storyboard` 的 `vocab.templates[*].source` 與 `vocab.layout`；`POST /api/task/render`／`batch`／`bible_sheet` 接受 `profile`；`GET /api/chapter/pages` 用專案的 page 尺寸。
- **設定檢查**：`t2c/settings._validate_comfy()` 擋 `kind` 不是 `moss`／`anima`、`profiles` 形狀不對、`default_profile` 不在 `profiles` 裡。
- **測試**：`tests/test_profiles.py`（16 項）、`tests/test_pages_override.py`（24 項）、`tests/test_ui.py`（新增 6 項）；全專案 `pytest`：**457 passed, 1 skipped**（基準 411／1）。版本 `t2c/__init__.py` 1.4.0。
- **文件**：`docs/02_資料格式.md` 第 2、6、17 節；`docs/qa/N4.md`；`docs/backlog.md` 記延後項（模板包上傳介面、版型預覽、LoRA 由 ComfyUI 列舉、靜態檔快取）。

**待使用者驗（需要 GPU）**：同一頁用 moss 與 anima 各出一張、看畫風差異；步驟在 `docs/qa/N4.md` 第 4 節。

## 1.3.0 — 2026-11-09（切對話，N3）

新增「切對話」：小說的一章先切成一場一場，每一場照原著順序寫旁白、對話與演出，每一行都帶 `source_para` 回指原著段落。輸出 `scenes/chNNN.json`（格式見 `docs/02_資料格式.md` 第 16 節）；這一版先做核心與命令列（`tools/annotate.py`），介面與整章批次還沒接（見 `docs/backlog.md`）。

- `t2c/annotate.py`（只用標準函式庫）：`split_paragraphs()` 把原著切成段（Markdown 標題行與 `＊＊＊` 分隔線不算段落），模型輸出的是四種 op（`N` 整段旁白、`n` 敘述片段、`d` 對話、`x` 演出），`expand()` 展開成場與行，`SCHEMA_VERSION = 1`。形狀跟 VN 的 annotate 不同：換成漫畫的「場 → 頁 → 格」，所以一場只有 `location`、`setting_en`、`cast`、`lines`。
- 驗證：逐字（忽略標點，允許句首補一個代名詞當主詞）、段落全覆蓋、段落號不可倒退、`cast` 與 `speaker` 必須在聖經、英文欄位（`setting_en`、`expression`、`note`）、`m` 標記可用值（心聲不能標畫面外、通訊不能再加語氣）、演出至少一個；沒過就把全部錯誤回給模型修（沿用 `Adapter._generate()`）。展開後還會先試轉一次分鏡＋`check_page_panels()`，轉不過的輸出一開始就退回。
- 漏句修補與忠實度報告：`annotate.repair_omissions()` 把漏掉的敘述原文照順序補成旁白（不經過模型、不動台詞、重跑不會重複補）；`annotate.fidelity()`／`fidelity_markdown()` 寫出 `build/adapt/chNNN_scenes_fidelity.md`，有段落覆蓋率、對話逐字、原著引號台詞保留、逐字違規／漏敘述／補了幾行，前兩項與劇本的 `chNNN_fidelity.md` 同一算法，可以前後比較。
- `annotate.to_storyboard()`：場 → 分鏡（panels／bubbles）。台詞逐字複製，程式負責直排斷行與 anchor，`x` 的鏡頭、角度套用到後面的行；`compile_check=True` 時真的跑 `compile_chapter()`，通過才回傳，所以不寫劇本也能直接出分鏡。
- `prompts.annotate_messages()`／`scenes_ledger()`：劇本階段的提示詞會附「切對話帳本」（`- lin（小聲）：「……又不接。」〔p3〕`），台詞只有一個來源。
- 測試：`tests/test_annotate.py`（40 項）；全專案 `pytest`：411 passed, 1 skipped。版本 `t2c/__init__.py` 1.3.0。


## 1.2.0 — 2026-11-09（整本匯入切章，N2）

新增「整本小說匯入 → 自動切章」，核心與命令列完成，介面「匯入」頁延後（backlog）。

- `t2c/importer.py`（只用標準函式庫）：切章邏輯移植自 Novel Studio 的 `studio/importer.py`（`split_text`／`normalize`／`plan`／`preview`／`commit`），包含「第X章」、英文 `Chapter N`、`Prologue` 等特殊章、Markdown `#` 標題、卷名略過、開頭目錄略過、重複標題合併（有 opencc 時繁簡寫法視為同一章名）。
  - 吃 `Path`（或一批 Path），不用 Novel Studio 的 base64 檔案約定；支援 `.txt`／`.md`／`.docx`（zipfile＋ElementTree 讀 `word/document.xml`，不加依賴）。
  - 落地 `<專案>/source/chNNN.txt`：檔頭 `# 第N章 章名`、空一行、正文（格式見 `docs/02_資料格式.md` 第 11 節）。
  - 重複匯入 `conflict="skip"`（預設）或 `"overwrite"`；覆寫前備份到 `<專案>/build/import/backup/<原檔名>.<時間>.bak`，每章每種檔名留 10 份；舊的 `chNNN.md` 備份後由 `.txt` 取代。
  - 簡轉繁（opencc）選用：沒安裝就跳過並列在 `warnings`，不讓匯入失敗。章號 0 或超過 999 時自動改成依順序編號（`numbering="titles"` 則明確報錯）。
  - Novel Studio 的 `fix_punct`（標點檢查器）沒有搬過來，t2c 不做標點改寫。
- `tools/import.py`：命令列（預覽預設、`--commit` 才寫檔；`--mode`、`--lang`、`--convert`、`--preface-as-chapter`、`--numbering`、`--start`、`--conflict`、`--json`）。
- 測試：`tests/test_importer.py`（27 項）＋樣本 `tests/data/n2_sample_six_chapters.txt`（6 章、含目錄與重複標題）。全專案 `pytest`：371 passed, 1 skipped。
- 與 Novel Studio **同一份樣本**逐項比對（章號、章名、字數、flags、正規化後正文、前言、warnings）：8 種情境（auto／chapter／markdown／sequential／preface_as_chapter／titles／英文特殊章＋Markdown／純 Markdown）全部相同；`.docx` 的讀取與 plan 也相同。
- 版本號 `t2c/__init__.py` 從 0.9.0（N1 時漏改）補到 1.2.0。


## 1.1.0 — 2026-11-09（設定頁，N1）

介面上多一頁「設定」，可以直接改工具自己的 `config.json`，不必再開文字編輯器。

- `t2c/settings.save()`：只寫白名單的鍵（`providers`、`default_provider`、`stage_providers`、`comfy`、`lettering`），物件型段落做一層合併（只送部分欄位不會清掉其他欄位），寫之前把舊檔備份成 `config.json.bak`，用暫存檔換名（不會留下半寫的設定檔）。`_` 開頭的鍵（`_說明`、`_path`）不寫進檔案。
- 驗證：provider 一定要有 `id` 與 `base_url`（`claude_code` 除外）、id 不能重複、`default_provider` 一定要在 `providers` 裡。
- `GET /api/settings`、`POST /api/settings`（`server/settings_api.py`）：GET 會回「金鑰環境變數有沒有設」，**不回傳金鑰值**。
- 介面「設定」頁：模型（預設 provider、各階段 provider、providers 表格可改／新增／刪除）、ComfyUI（位址、模型、出圖預設 JSON）、嵌字（直排、字級、字型路徑）。
- 測試：`tests/test_settings.py`（10 項）。


## 1.0.0 — 2026-11-09（M1 里程碑標完成）

M1（從一章小說到 PDF 的全流程驗收）依使用者決定標完成：雲端部分全部通過（pytest、新章節全流程到 PDF、`CLAUDE.md` 規則與資料格式逐條），Windows 實機第 5–7 步沒有逐項回報，仍算「沒有實機驗證」的項目（`docs/qa/M1.md` 第 5 節）。M-4 與 L-8–L-12 未處理，留在 `docs/backlog.md`。這一版只有文件變更，沒有程式變更。

## 0.9.0 — 2026-11-09（M1 修正）

依 `docs/qa/M1.md` 修 M-1、M-2、M-3 與 L-1–L-7。M-4（長得像的角色）等使用者決定記號；L-8–L-12 未動。

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
- 依據與數字見 `docs/qa/S1_出圖實測.md`。資料格式沒有新增欄位。

## 0.1.0 — 2026-11-08（S0）

- 用 fekit 0.0.1 範本建立專案（模組：i18n、md、filepicker、table）。
- 核心 `t2c/`：格子模板與 MOSS bbox 換算、漫畫專案讀取、分鏡編譯、ComfyUI 客戶端。
- 資料格式第 1 版：`project.yaml`、角色／地點卡、漫畫劇本、分鏡 JSON（見 `docs/02_資料格式.md`）。
- 命令列 `tools/panels.py`；範例專案 `examples/sample_comic/`；測試 `tests/test_core.py`。

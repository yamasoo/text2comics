# 更新紀錄

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

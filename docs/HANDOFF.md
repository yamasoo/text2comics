# 交接

## 目前狀態（2026-11-08，S4 完成）

### S4 做了什麼

- `t2c/llm.py`：OpenAI 相容 Chat Completions（DeepSeek、llama.cpp 的 llama-server）。`find_provider(cfg, provider_id, stage)`、`chat()`（串流、`on_delta`／`on_thinking`、重試、`should_stop`）、`chat_json()`、`parse_json()`、`estimate_tokens()`／`check_context()`。providers 欄位與 Novel Studio 相同；金鑰只讀環境變數 `key_env`。
- `tools/llm_check.py`：對每個 provider 要一份 JSON；`--stop-after N` 測停止；`--models` 列模型。
- `tests/test_llm.py` 37 項，用本機假伺服器（SSE、429／5xx、斷線、慢速串流、取消），雲端 Linux 全過。
- 資料格式與 `config.json` 沒有新欄位（`reasoning` 為選填）。細節見 `CHANGELOG.md` 0.4.0 與 `docs/03_建置與環境.md` 第 5 節。

### S4 的決定

- **不做內容驗證**：`chat_json()` 只處理 JSON 語法（錯了回修一次）。分鏡規則的驗證與回修（CLAUDE.md 規則 6）在 S5，用 `compile_chapter()` 的錯誤訊息，建議在 `chat_json()` 上層用同樣的「assistant 原文＋user 錯誤」格式再包一圈。
- **停止靠背景執行緒**：socket 讀取不能被中斷，所以讀取放在執行緒、主執行緒輪詢，取消時 `shutdown` socket。呼叫端收到 `llm.Cancelled` 後要自己呼叫 `job.checkpoint()`（核心不 import fekit）。
- **已吐字後斷線不重試**，避免輸出重複；呼叫端看到錯誤要整段重來。
- **思考強度**：`reasoning` 設定沿用 Novel Studio（`deepseek`、`openai_effort`、`qwen_template` 三種 adapter），`stage` 參數對應 `adapt`／`script`／`storyboard` 這類階段名稱；`config.example.json` 沒有填 `reasoning`，S5 實測 DeepSeek 後再決定要不要開。
- 沒做 `app.py` 的 LLM 端點與介面，那是 S5 以後（S7 整合進介面）。

### 待決問題

1. （S2 留下）預設用 `final` 還是 `draft`；`config.example.json` 目前是 `final`。
2. （S1 留下）int8 文字編碼器＋CPU 沒有測。
3. （S1 留下）雙人以上的左右位置句只驗證過一格（k5）。
4. （S1 留下）4-step LoRA 是否完整套用沒有證明。
5. （S2 留下）黑白網點／二值化後製要不要做：請看嵌字後的 `pages/ch001/p001.png` 再決定。
6. lhfer/codex-novel-to-comic-studio 的授權還沒確認（S5 前）。
7. （S3 留下）嵌字字型：Windows 上沒設定時會用微軟正黑體＋細明體；要發佈請裝 Noto Sans／Serif CJK TC 並填進 `config.json` 的 `lettering`。字級 9 pt 是否合適請看實際頁面。
8. `config.example.json` 的 DeepSeek `model` 是 `deepseek-flash`，沒有實測；請先跑 `python tools\llm_check.py --models` 確認帳號可用的名稱。

### 沒有驗證的

- **真的 DeepSeek 與 llama.cpp**：雲端沒有金鑰也沒有 llama-server，只用假伺服器驗過協定。請在你的電腦執行 `python tools\llm_check.py`（兩個 provider 都要 ✓）和 `python tools\llm_check.py --stop-after 5`（要顯示已中斷）。特別是 llama.cpp 按停止後 GPU 是否真的停止生成，請看 llama-server 的視窗。
- Windows 上的 `pytest`（含 S3 的嵌字、介面）。
- 微軟正黑體／細明體的排字結果、多頁分鏡（S3 留下）。

### 流程提醒

- 這台電腦沒有 shell 可用時，檔案透過檔案橋接寫入；git 提交要在你的終端機執行。
- `pages/ch001/p001.png` 是嵌好字的頁面；要沒有字的版本加 `--no-letter`。

### 上一階段（S3 嵌字）做了什麼

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

## 下一階段：S5 文字端提示詞

先讀：本檔 → `docs/00_階段計畫.md` 的 S5 → `docs/02_資料格式.md` 第 4、5 節（劇本、分鏡）→ `t2c/llm.py` → `t2c/compile.py` 的 `compile_chapter()`（驗證與錯誤訊息）。授權待決問題 6 要在開工前處理。
S5 標 Opus 5.5／high，不外包。

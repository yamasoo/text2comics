# 交接

## 目前狀態（2026-11-08，S5 完成）

### S5 做了什麼

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

## 下一階段：S6 視覺聖經

先讀：本檔 → `docs/00_階段計畫.md` 的 S6 → `docs/02_資料格式.md` 第 3 節（角色卡、地點卡）→ `t2c/prompts.py`（沿用提示詞寫法）→ `t2c/adapt.py`（沿用產生 → 驗證 → 回修）→ `t2c/compile.py` 的 `character_caption()`（look_en 怎麼被用）。
S6 標 Sonnet 5.5／high，不外包。建議開工前先完成上面「S5 用真的 DeepSeek 跑一章」，S6 的抽取提示詞會沿用 S5 的寫法，先知道 DeepSeek 常犯什麼錯比較省事。

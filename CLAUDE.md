# CLAUDE.md — 文字轉漫畫（text2comics）

給在這個專案工作的 Claude Code／其他 AI 看的規則。新對話開始時先讀本檔，架構與流程見 `docs/01_架構與流程.md`。開發過程的交接、待辦與階段計畫不放在這個分支，在 `dev` 分支。

## 1. 這個專案是什麼

把小說改編成日式黑白頁漫的本機工具。文字端（改編、劇本、分鏡）用 DeepSeek 或本機 llama.cpp；出圖用 ComfyUI 的 MOSS-Image；嵌字與組版用 Pillow。
**先做成獨立工具，之後併入 Novel Studio 與 text_2_visual_novel。** 所以核心要能整包搬走（見第 3 節）。

## 2. 目錄權限

| 目錄 | 權限 | 說明 |
|---|---|---|
| `<專案根目錄>` | 讀寫 | 本專案 |
| `<novel-studio 專案根>` | **唯讀** | 參考它的 ComfyUI／MOSS 出圖機制（`studio/comfy.py`、`studio/illust.py`）、LLM 連線（`studio/providers.py`）、書庫格式。開發分支是 `dev` |
| `<text_2_visual_novel 專案根>` | **唯讀** | 之後的整合對象 |
| `<fekit 專案根>` | **唯讀** | fekit 本體。fekit 有問題到 fekit 自己的對話修 |
| 其他位置 | 不碰 | — |

整合階段（I2、I4）在**該專案自己的對話**、依它的 `CLAUDE.md` 進行，不在本專案的對話裡改它們。

## 3. 架構規則

1. **核心與介面分開**：漫畫邏輯全部放 `t2c/`，只能用標準函式庫、PyYAML、Pillow；不可以 import FastAPI、fekit。`app.py` 只是薄薄一層 API＋背景任務，呼叫 `t2c`。
2. **座標只有一種**：分鏡、模板、程式內部一律用比例 `[x0, y0, x1, y1]`（左上 0、右下 1）。換成 MOSS 的 `abs_centralized`／`yxyx` 像素只能在 `t2c/layout.to_moss_bbox()` 做。LLM 不准輸出像素座標。
3. **角色外觀只有一個來源**：視覺聖經的 `look_en`、`outfits`。分鏡只寫角色 id，由 `t2c/compile.py` 逐字貼上。不要讓 LLM 在分鏡裡重寫外觀。
4. **一格一張圖**：不要整頁一次生成。每格的 summary 只描述這一格、只放在場的角色。
5. **台詞不進生圖提示詞**：對話、旁白由嵌字程式疊上；狀聲詞依 `sfx_mode`。
6. **LLM 輸出一律過驗證**：分鏡 JSON 要先過 `compile_chapter()` 的檢查才能存檔；失敗就把錯誤訊息回給 LLM 修，不要手動猜。
7. **可重現**：seed 由格子 id 決定（`compile._seed`），同一格重跑結果一樣。
8. **產出不進版控**：漫畫專案的 `build/`、`renders/`、`pages/`、`out/`。

## 4. 技術規則（承襲 fekit）

1. 免建置：不用 Node、npm、打包工具；第三方檔案放 `vendor/`，附 LICENSE，不連 CDN。
2. 命名：key、ID、檔名、CSS class、函式與變數名一律英文 `[a-z0-9_-]`；中文只出現在顯示文字與值。分鏡 JSON 的欄位名也是英文。
3. DOM：用 `FE.h()` 建節點，不拼 `innerHTML`。Markdown 用 `FE.md.render()`。
4. 頁面：`FE.PAGES.<key> = (ctx) => {...}`，一律用 `ctx.view`／`ctx.crumbs`，請求傳 `signal: ctx.signal`。
5. 後端錯誤：`fekit.ApiError(status, "繁體中文訊息", code)`；任務失敗 `JobError("一句話")`。核心的錯誤用各模組自己的 Exception（`CompileError`、`ProjectError`…），訊息要寫出是哪一頁哪一格。
6. 長工作（出圖、LLM）一律用 `JobRunner` 背景任務，迴圈裡呼叫 `job.checkpoint()`。
7. `vendor/fekit/` 不要改；升級用 `<fekit 專案根>\tools\sync_kit.py`。
8. 介面文字與文件用繁體中文（台灣用語），不可出現簡體字。生圖提示詞用英文；要畫進圖裡的字保留原文。
9. 金鑰不寫進任何檔案：DeepSeek 先讀環境變數 `DEEPSEEK_API_KEY`，沒有再讀系統金鑰庫（服務 `novel-studio`、帳號 `deepseek`，與 Novel Studio、t2vn 共用；只讀不寫，需要 `pip install keyring`）；`config.json` 不進版控。

## 5. 工作流程

- **模型**：一律 DeepSeek。難題（資料格式、提示詞架構、整合計畫、獨立驗收）用 `deepseek-v4-pro`，其餘用 `deepseek-flash`；思考強度只有 `off`／`low`／`high`／`max`（沒有 medium、xhigh），最難的品質優先工作用 `max`。
- **一個對話只做一個階段。** 不要順手做下一階段的事；範圍外的需求先問。
- 動工前確認：本階段的範圍、要讀的參考檔、驗收方式。
- 需要 GPU 的驗收（出圖）只能在使用者的 Windows 電腦上做。不能實際出圖時，寫清楚哪些項目待使用者驗證，不要假裝驗過。
- 結束前：
  1. 依本階段的「驗收」實際檢查（`python -m pytest tests`、開頁面、看出圖結果），不要只靠描述。
  2. 有改資料格式就更新 `docs/02_資料格式.md` 與 `CHANGELOG.md`。
  3. git：能執行就提交；不能的話，在結束報告附上可以直接貼上執行的指令。

## 6. 階段結束報告（必做）

```
✅ 本階段完成：<階段編號與名稱>
驗證方式：<實際做了什麼檢查>
待決問題：<沒有就寫「無」>
Git：<已提交的 commit，或要貼上執行的指令>

➡ 下一階段：<階段編號與名稱>
建議模型：<模型名稱>　思考強度：<off / low / high / max>
理由：<一句話>
是否開新對話：<是／否，以及原因>
開場提示：<可以直接貼到新對話的第一句話>
```

## 7. 外包

適合外包給 DeepSeek 的工作在階段計畫標「可外包」。由 Claude 寫任務卡與測試（放 `docs/tasks/`），交回後由 Claude 審查。執行任務卡的 AI 只改卡片 `files_allowed` 列出的檔案，不改測試。

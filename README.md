# 文字轉漫畫（text2comics）

把小說改編成**日式黑白頁漫**的本機工具：

```
小說 → 改編規劃 → 漫畫劇本 → 分鏡 JSON → MOSS-Image 逐格出圖 → 組版 → 嵌字 → PDF／CBZ
        └──── DeepSeek／llama.cpp ────┘   └─ 程式編譯 ─┘   └ ComfyUI ┘   └──── Pillow ────┘
```

先做成獨立工具，之後再併入 Novel Studio（`E:\novel-studio`）與 text_2_visual_novel（`E:\text_2_visual_novel`）。

> 目前進度：**S8 輸出完成**（S7 介面之上）。在瀏覽器裡就能走完一章：開專案 → 貼原著 → 改編規劃 → 劇本 → 分鏡（表格＋框編輯器）→ 逐格出圖、挑圖、裁切 → 嵌字 → 輸出頁面；也可以按「整章批次」一次跑完（會照顧 VRAM：本機 LLM 與 ComfyUI 不同時佔 GPU）。視覺聖經的草稿確認與定裝圖挑選也在介面裡。「頁面」分頁可以直接下載整章 PDF／CBZ（右翻，S8）。進度見 `docs/00_階段計畫.md`，介面設計見 `docs/05_介面設計.md`。

## 快速開始

```powershell
cd E:\dev\text2comics
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json      # 再依自己的環境改
python -m pytest tests                     # 應該全部通過
python run.py                              # 或雙擊 start.bat
```

不開介面、直接用命令列：

```powershell
python tools\adapt.py E:\comics\作品 1                             # 原著 source\ch001.txt → 規劃、劇本、分鏡（需要 LLM）
python tools\panels.py examples\sample_comic 1                      # 編譯：每格的提示詞寫到 build\ch001\
python tools\panels.py examples\sample_comic 1 --page 1 --render    # 出圖：需要 ComfyUI 已啟動
python tools\pages.py examples\sample_comic 1                        # 組版＋嵌字：依 picks\ch001.json、letters\ch001.json 輸出 pages\ch001\p001.png
python tools\export.py examples\sample_comic 1 --format all          # 打包右翻的 PDF 與 CBZ → <專案>\out\ch001.pdf、ch001.cbz（--page N 只輸出一頁）
```

完整的環境建置（ComfyUI、模型、本機 LLM、git）見 `docs/03_建置與環境.md`。

## 資料夾

| 路徑 | 內容 |
|---|---|
| `t2c/` | **核心**：不依賴網頁框架（標準函式庫＋PyYAML＋Pillow），之後整包併入其他專案 |
| `t2c/layout.py` | 頁面格子模板、生圖尺寸、MOSS bbox 換算 |
| `t2c/compile.py` | 分鏡 JSON → 每格的 MOSS layout prompt |
| `t2c/project.py` | 讀漫畫專案資料夾（project.yaml、視覺聖經、分鏡） |
| `t2c/comfy.py` | 最小的 ComfyUI API 客戶端 |
| `t2c/compose.py` | 選圖紀錄、裁切、組版成整頁 |
| `t2c/letter.py` | 嵌字：對話框、尾巴、直排繁中、避開臉、狀聲詞、微調紀錄 |
| `t2c/export.py` | 輸出：頁面 PNG → 右翻的 PDF（`/Direction /R2L`）或 CBZ（`ComicInfo.xml` Manga） |
| `t2c/llm.py` | OpenAI 相容的 LLM 連線（DeepSeek、llama.cpp） |
| `t2c/prompts.py`、`t2c/adapt.py` | 文字端三階段的提示詞與流程（產生 → 驗證 → 回修） |
| `t2c/script.py`、`t2c/check.py` | 劇本解析、忠實度報告；規劃與分鏡的驗證 |
| `t2c/bible.py`、`t2c/bible_prompts.py`、`t2c/bible_check.py` | 視覺聖經：抽角色與地點 → 卡片草稿 → 規則檢查 → 定裝圖 → 服裝矩陣 |
| `layouts/pages.json` | 頁面格子模板（右翻閱讀順序） |
| `workflows/` | ComfyUI 的 API 格式 workflow |
| `tools/panels.py` | 命令列：編譯／出圖 |
| `tools/pages.py` | 命令列：選圖、組版、嵌字（頁面 PNG） |
| `tools/export.py` | 命令列：輸出 PDF／CBZ（整章或單頁） |
| `tools/adapt.py` | 命令列：改編規劃、劇本、分鏡 |
| `tools/bible.py` | 命令列：視覺聖經（掃描、草稿、檢查、確認、定裝圖、挑選、矩陣） |
| `tools/llm_check.py` | 命令列：檢查 LLM 連線 |
| `examples/sample_comic/` | 範例漫畫專案（原著一章、1 頁 5 格） |
| `app.py`、`server/`、`web/` | 介面（fekit：FastAPI＋免建置前端）：專案、章節（原著／規劃／劇本／分鏡／出圖／頁面）、視覺聖經、嵌字。`server/` 是 API 與背景任務，只呼叫 `t2c` |
| `vendor/fekit/` | fekit 的複製品，**不要直接改**（見下） |
| `docs/` | 計畫、架構、資料格式、建置說明、交接 |

## 文件

| 文件 | 什麼時候看 |
|---|---|
| `docs/00_階段計畫.md` | 下一步做什麼、每階段的驗收與建議模型 |
| `docs/01_架構與流程.md` | 為什麼這樣設計（MOSS-Image 的特性與限制） |
| `docs/02_資料格式.md` | 漫畫專案資料夾、角色卡、劇本、分鏡 JSON 的格式 |
| `docs/03_建置與環境.md` | 從零把環境建起來 |
| `docs/04_提示詞設計.md` | 文字端三階段的分工、提示詞、驗證與回修 |
| `docs/HANDOFF.md` | 給下一個對話的交接 |

## 更新 fekit

`vendor/fekit/` 由 fekit 本體同步（目前模組：`i18n`、`md`、`filepicker`、`table`）：

```powershell
python E:\dev\front-end\tools\sync_kit.py E:\dev\text2comics              # 更新
python E:\dev\front-end\tools\sync_kit.py E:\dev\text2comics --add graph  # 加模組
```

fekit 的問題回 `E:\dev\front-end` 修，再同步進來。

## 授權

MIT，見 `LICENSE`。fekit 的第三方檔案見 `vendor/fekit/THIRD_PARTY_NOTICES.md`。

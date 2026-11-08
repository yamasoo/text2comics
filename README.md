# 文字轉漫畫（text2comics）

把小說改編成**日式黑白頁漫**的本機工具：

```
小說 → 改編規劃 → 漫畫劇本 → 分鏡 JSON → MOSS-Image 逐格出圖 → 嵌字 → 組版 → PDF／CBZ
        └──── DeepSeek／llama.cpp ────┘   └─ 程式編譯 ─┘   └ ComfyUI ┘   └──── Pillow ────┘
```

先做成獨立工具，之後再併入 Novel Studio（`E:\novel-studio`）與 text_2_visual_novel（`E:\text_2_visual_novel`）。

> 目前進度：**S0 骨架完成**。已經能把範例分鏡編譯成每格的 MOSS layout prompt，並送 ComfyUI 出圖；組版、嵌字、LLM 改編還沒做。進度見 `docs/00_階段計畫.md`。

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
python tools\panels.py examples\sample_comic 1                      # 編譯：每格的提示詞寫到 build\ch001\
python tools\panels.py examples\sample_comic 1 --page 1 --render    # 出圖：需要 ComfyUI 已啟動
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
| `layouts/pages.json` | 頁面格子模板（右翻閱讀順序） |
| `workflows/` | ComfyUI 的 API 格式 workflow |
| `tools/panels.py` | 命令列：編譯／出圖 |
| `examples/sample_comic/` | 範例漫畫專案（1 頁 5 格） |
| `app.py`、`web/` | 介面（fekit：FastAPI＋免建置前端） |
| `vendor/fekit/` | fekit 的複製品，**不要直接改**（見下） |
| `docs/` | 計畫、架構、資料格式、建置說明、交接 |

## 文件

| 文件 | 什麼時候看 |
|---|---|
| `docs/00_階段計畫.md` | 下一步做什麼、每階段的驗收與建議模型 |
| `docs/01_架構與流程.md` | 為什麼這樣設計（MOSS-Image 的特性與限制） |
| `docs/02_資料格式.md` | 漫畫專案資料夾、角色卡、劇本、分鏡 JSON 的格式 |
| `docs/03_建置與環境.md` | 從零把環境建起來 |
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

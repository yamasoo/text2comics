# 交接

## 目前狀態（2026-11-08，S0 完成）

### 做了什麼

- 用 fekit 0.0.1 的 `new_project.py` 產生骨架（模組 `i18n`、`md`、`filepicker`、`table`），`vendor/fekit/fekit.json` 的 `source` 指向 `E:\dev\front-end`，可以直接用 `sync_kit.py` 更新。
- 核心 `t2c/`：
  - `layout.py`：格子模板、頁面像素框、生圖尺寸（約 1 MP、16 的倍數、長寬比夾在 1:3–3:1）、比例座標 ↔ MOSS bbox。
  - `project.py`：讀 `project.yaml`、角色／地點卡（YAML frontmatter）、分鏡 JSON。
  - `compile.py`：分鏡 → 每格的 MOSS layout prompt；角色外觀逐字從聖經取；台詞不進提示詞；seed 由格子 id 決定；錯誤訊息標出頁與格。
  - `comfy.py`：最小的 ComfyUI 客戶端（送出、等待、取圖）。
- `layouts/pages.json`：6 個右翻模板。`workflows/moss_layout.api.json`：從 Novel Studio 的 `examples/comfy/moss.api.json` 改來。
- `tools/panels.py`：命令列編譯／出圖。
- `examples/sample_comic/`：1 頁 5 格的原創範例（角色 2、地點 1、劇本、分鏡）。
- 介面：任務頁「編譯範例分鏡」（背景任務，結果寫到 build/）。
- 文件：`CLAUDE.md`、`README.md`、`docs/00`–`03`、本檔、`backlog.md`、`CHANGELOG.md`。

### 怎麼驗證的

- 在雲端 Linux（Python 3）：`pytest` 24 項全過；`tools/panels.py` 編譯範例；用假的 ComfyUI 伺服器測過 `comfy.run()` 的送出→等待→取圖；啟動 `run.py` 用瀏覽器按「編譯範例分鏡」，面板顯示 5 格、無主控台錯誤。
- **沒有驗證的**：Windows 上執行、真的 ComfyUI 出圖（沒有 GPU）、git 提交。

### 待決問題

1. 「The artwork has no speech bubbles, captions or lettering.」這句會不會反而讓模型畫字，要 S1 實測。
2. 黑白網點的效果要靠 `style` 文字，S1 看結果決定要不要加後製（轉灰階、加網點濾鏡）。
3. lhfer/codex-novel-to-comic-studio 的授權還沒確認（S5 前）。

## 下一階段：S1 出圖實測

先讀：本檔 → `docs/01_架構與流程.md` 第 2 節 → `docs/02_資料格式.md` 第 5 節。
要在使用者的 Windows 電腦上做（需要 GPU 與 ComfyUI）。

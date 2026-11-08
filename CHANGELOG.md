# 更新紀錄

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

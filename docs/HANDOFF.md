# 交接

## 目前狀態（2026-11-08，S1 完成）

### S1 做了什麼

- 在 Windows＋ComfyUI 0.41.0（RTX 5070 Ti）實測範例頁：每格 3 個 seed 共 15 張，記錄秒數、VRAM、角色位置、多出文字、人數。完整數字與挑選的圖見 `docs/qa/S1_出圖實測.md`。
- 依實測改了程式：`compile.py` 加「無邊框」句與兩人以上的左右位置句；`comfy.py`／`tools/panels.py` 加出圖預設（`comfy.presets`、`--preset`、`--seed`），`config.example.json` 附 `final`（25 步）與 `draft`（4 步＋LoRA）。
- 範例分鏡 k2 的「a hand」改成「one hand」；`candidates` 2 → 3。
- 測試 27 項（`tests/test_core.py`）在雲端 Linux 全過。

### 關鍵數字

- 25 步：每張約 14 秒；4 步＋LoRA：約 4 秒（快約 3.3 倍，線條較乾淨、網點較少）。
- 多出的文字 0/15；k5 左右位置 3/3（改前 1/3）；k2 邊框 0/15（改前 3/15）。
- 文字編碼器放 CPU（W4A8）：新提示詞 175 秒 vs 14.5 秒，VRAM 沒省，不建議。

### 待決問題

1. 預設用 `final` 還是 `draft`：目前 `config.example.json` 的 `default_preset` 是 `final`；使用者要看過 4 步的圖後決定。
2. int8 文字編碼器＋CPU 沒有測（需要下載 `qwen3.5_9b_int8_convrot.safetensors`）；只有 GPU 要和 llama.cpp 共用時才需要。
3. 雙人以上的左右位置句只驗證過一格（k5），要用更多分鏡再驗證。
4. 4-step LoRA 是否完整套用沒有證明（只是 log 沒出現 `lora key not loaded`）。
5. 黑白網點是否要加後製（轉灰階、網點濾鏡）：實測輸出本來就是黑白，先不做，S2 組版後再看。
6. lhfer/codex-novel-to-comic-studio 的授權還沒確認（S5 前）。

### 沒有驗證的

- `tests/test_smoke.py`（需 fastapi）、Windows 上的 `pytest`、ComfyUI 0.42.0（實測用 0.41.0）。

### 流程提醒

- 本電腦沒有 shell 可用時，檔案是透過檔案橋接寫入的；git 提交要在你的終端機執行。

## 下一階段：S2 組版

先讀：本檔 → `docs/01_架構與流程.md` 第 1、5 節 → `docs/02_資料格式.md`。
範例頁已有 15 張候選（`examples/sample_comic/renders/ch001/`）與初選（`docs/qa/S1_出圖實測.md` 第 5 節）可直接當組版素材。

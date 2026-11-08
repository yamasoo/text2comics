"""工具本身的設定：config.json（不進版控）；沒有就用 config.example.json。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path=None):
    for candidate in ([Path(path)] if path else [ROOT / "config.json", ROOT / "config.example.json"]):
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            data["_path"] = str(candidate)
            return data
    raise FileNotFoundError("找不到 config.json，請複製 config.example.json 再修改")

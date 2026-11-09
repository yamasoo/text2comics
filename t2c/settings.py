"""工具本身的設定：config.json（不進版控）；沒有就用 config.example.json。

設定檔在哪裡由呼叫端決定（M1 修正 M-3：t2c 要能整包搬進別的專案，不能假設上一層資料夾是什麼）：
獨立工具的 app.py、tools/*.py 傳 root=工具資料夾；併進別的專案時傳它自己的設定檔路徑。
"""
import json
from pathlib import Path


def load(path=None, root=None):
    """path：指定的設定檔；沒給就在 root 找 config.json，再找 config.example.json。回傳的 dict 帶 _path（相對路徑以它為準）。"""
    if not path and not root:
        raise ValueError("settings.load() 要給設定檔路徑 path，或設定檔所在的資料夾 root")
    for candidate in ([Path(path)] if path else [Path(root) / "config.json", Path(root) / "config.example.json"]):
        if candidate.is_file():
            data = json.loads(candidate.read_text(encoding="utf-8"))
            data["_path"] = str(candidate)
            return data
    raise FileNotFoundError("找不到 config.json，請複製 config.example.json 再修改")

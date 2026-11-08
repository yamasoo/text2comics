"""漫畫專案資料夾的讀取：project.yaml、視覺聖經（角色、地點）、分鏡 JSON。

漫畫專案資料夾（例：examples/sample_comic/）：
    project.yaml               專案設定：畫風、閱讀方向、生圖參數
    bible/characters/*.md      角色：YAML frontmatter（id、look_en、outfits…）＋人看的說明
    bible/locations/*.md       地點：同上（id、look_en）
    script/chNNN.md            漫畫劇本（人看、人改）
    storyboard/chNNN.json      分鏡（機器讀；格式見 docs/02_資料格式.md）
    build/、renders/、pages/   產出（不進版控）
"""
import json
import re
from pathlib import Path

import yaml

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
ID_RE = re.compile(r"^[a-z0-9_-]+$")


class ProjectError(Exception):
    """給人看的錯誤訊息。"""


def read_front_matter(path):
    """回傳 (frontmatter dict, 本文)。沒有 frontmatter 就丟錯。"""
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    match = FRONT.match(text)
    if not match:
        raise ProjectError("%s 開頭沒有 YAML frontmatter（--- 包起來的區塊）" % path)
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        raise ProjectError("%s 的 frontmatter 不是合法的 YAML：%s" % (path, error))
    if not isinstance(meta, dict):
        raise ProjectError("%s 的 frontmatter 要是 key: value 的形式" % path)
    return meta, text[match.end():]


def _load_cards(folder, kind):
    cards = {}
    for path in sorted(Path(folder).glob("*.md")):
        meta, _ = read_front_matter(path)
        cid = str(meta.get("id") or "")
        if not ID_RE.match(cid):
            raise ProjectError("%s：id 只能用 a-z、0-9、底線、連字號（目前是 %r）" % (path, cid))
        if cid in cards:
            raise ProjectError("%s：%s id「%s」重複了" % (path, kind, cid))
        if not str(meta.get("look_en") or "").strip():
            raise ProjectError("%s：缺少 look_en（固定的英文外觀描述，生圖時逐字使用）" % path)
        meta["_path"] = str(path)
        cards[cid] = meta
    return cards


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        cfg = self.root / "project.yaml"
        if not cfg.is_file():
            raise ProjectError("%s 不是漫畫專案資料夾（找不到 project.yaml）" % self.root)
        self.config = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        self.characters = _load_cards(self.root / "bible" / "characters", "角色")
        self.locations = _load_cards(self.root / "bible" / "locations", "地點")

    def storyboard_path(self, chapter):
        return self.root / "storyboard" / ("ch%03d.json" % int(chapter))

    def load_storyboard(self, chapter):
        path = self.storyboard_path(chapter)
        if not path.is_file():
            raise ProjectError("找不到分鏡：%s" % path)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProjectError("%s 不是合法的 JSON：%s" % (path, error))

    # --- S5：文字端的檔案 ---------------------------------------------------
    def source_path(self, chapter):
        """原著章節：source/chNNN.txt 或 .md；沒有就回傳 None。"""
        for ext in (".txt", ".md"):
            path = self.root / "source" / ("ch%03d%s" % (int(chapter), ext))
            if path.is_file():
                return path
        return None

    def load_source(self, chapter):
        path = self.source_path(chapter)
        if path is None:
            raise ProjectError("找不到原著：請把第 %d 章放在 %s（.txt 或 .md）" % (int(chapter), self.root / "source" / ("ch%03d.txt" % int(chapter))))
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").lstrip("﻿")
        match = FRONT.match(text)          # 允許原著檔開頭有 frontmatter（例如從 Novel Studio 匯出的），略過
        return (text[match.end():] if match else text).strip()

    def plan_path(self, chapter):
        return self.root / "plan" / ("ch%03d.json" % int(chapter))

    def script_path(self, chapter):
        return self.root / "script" / ("ch%03d.md" % int(chapter))

    def load_plan(self, chapter):
        path = self.plan_path(chapter)
        if not path.is_file():
            raise ProjectError("找不到改編規劃：%s（先執行 plan 階段）" % path)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProjectError("%s 不是合法的 JSON：%s" % (path, error))

    def out_dir(self, *parts):
        path = self.root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

"""N5 畫風預設集與 N2 整本匯入的介面端點：GET /api/styles、POST /api/project/style、
POST /api/import/plan、POST /api/import/commit，以及 t2c/workspace.py 的 set_style_preset()。

一律用 tmp_path 建專案（不動 repo 的 config.json 與 examples/），匯入樣本是
tests/data/n2_sample_six_chapters.txt（6 章）。執行：python -m pytest tests/test_styles_import.py
"""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from t2c import styles, workspace  # noqa: E402
from t2c.project import Project  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")
SAMPLE = ROOT / "examples" / "sample_comic"
SIX = ROOT / "tests" / "data" / "n2_sample_six_chapters.txt"      # 6 章：雨夜／失約／天台／舊信／車站／晴天
TITLES = ["雨夜", "失約", "天台", "舊信", "車站", "晴天"]


def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


def tree(root):
    """資料夾樹（相對路徑、排序）：用來確認 plan 沒有寫任何檔案。"""
    root = Path(root)
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*"))


def new_project(tmp_path, name="comic", yaml_extra=""):
    """tmp_path 底下的空白專案；yaml_extra 追加到 project.yaml（明寫的 style／meta…）。"""
    root = tmp_path / name
    workspace.create_project(str(root), "測試作品")
    if yaml_extra:
        path = root / "project.yaml"
        text = path.read_text(encoding="utf-8").rstrip()
        path.write_text(text + "\n" + yaml_extra, encoding="utf-8")
    return workspace.open_project(str(root))


# ---------------------------------------------------------------------------
# 核心：workspace.set_style_preset()
# ---------------------------------------------------------------------------
def test_set_style_preset_switches_preset_and_resolved_style(tmp_path):
    """換預設集：project.yaml 的 style_preset 改掉，styles.resolve() 的 style 跟著換，註解行不動。"""
    proj = new_project(tmp_path)
    before = styles.resolve(proj.config)
    assert before["preset"] == "mono"
    result = workspace.set_style_preset(proj, "color")
    assert result["preset"] == "color" and result["dropped"] == []
    assert Path(result["path"]).name == "project.yaml"
    text = (proj.root / "project.yaml").read_text(encoding="utf-8")
    assert "style_preset: color" in text
    assert "# 畫風預設集" in text                                  # 原本的註解還在
    assert "# style:" in text and "# meta:" in text                # 選填欄位的說明註解（# 開頭）不能被當成明寫的欄位
    after = styles.resolve(Project(proj.root).config)
    assert after["preset"] == "color"
    assert after["style"] != before["style"]
    assert after["style"] == styles.preset("color")["style"]
    assert after["name"] == styles.preset("color")["name"]


def test_set_style_preset_drops_explicit_fields_and_keeps_comments(tmp_path):
    """明寫的 style／meta 會蓋掉預設集，換預設集時要一起拿掉並回報；# 開頭的註解行不動。"""
    explicit = ("style: >-\n"
                "  手繪粗線條，重網點\n"
                "meta:\n"
                "  - manga panel\n"
                "  - screentone\n"
                "# style: 這一行是註解，換預設集時不能動\n")
    proj = new_project(tmp_path, yaml_extra=explicit)
    overridden = styles.resolve(proj.config)
    assert overridden["style"] == "手繪粗線條，重網點" and overridden["meta"] == ["manga panel", "screentone"]
    result = workspace.set_style_preset(proj, "american")
    assert result["dropped"] == ["style", "meta"]                   # 回報被拿掉的欄位
    text = (proj.root / "project.yaml").read_text(encoding="utf-8")
    assert "style_preset: american" in text
    lines = [line for line in text.splitlines() if line.strip()]
    assert not [line for line in lines if line.startswith("style:")]
    assert not [line for line in lines if line.startswith("meta:")]
    assert "  - screentone" not in text                             # 續行也要一起拿掉
    assert "# style: 這一行是註解，換預設集時不能動" in text
    assert "# meta: [manga panel]" in text
    resolved = styles.resolve(Project(proj.root).config)
    assert resolved["preset"] == "american"
    assert resolved["style"] == styles.preset("american")["style"]
    assert resolved["meta"] == styles.preset("american")["meta"]


def test_set_style_preset_unknown_name_and_not_a_project(tmp_path):
    """名稱不認得丟 WorkspaceError 並列出可用值（且不寫檔）；不是專案資料夾也丟 WorkspaceError。"""
    proj = new_project(tmp_path)
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.set_style_preset(proj, "no_such_preset")
    message = str(error.value)
    assert "可用：" in message
    for name in styles.names():
        assert name in message
    assert styles.resolve(Project(proj.root).config)["preset"] == "mono"      # 失敗時原檔不動
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.set_style_preset(empty, "color")
    assert "不是漫畫專案資料夾" in str(error.value)
    assert not (empty / "project.yaml").exists()


# ---------------------------------------------------------------------------
# GET /api/styles
# ---------------------------------------------------------------------------
def test_styles_api_lists_three_presets():
    """三組（american／color／mono）都有 label，預設是 mono。"""
    resp = client.get("/api/styles")
    assert resp.status_code == 200
    data = resp.json()
    assert [row["name"] for row in data["presets"]] == ["american", "color", "mono"]
    assert data["default"] == "mono"
    assert all(row["label"] for row in data["presets"])
    labels = {row["name"]: row["label"] for row in data["presets"]}
    assert labels["mono"] == styles.preset("mono")["name"]
    assert labels["color"] != labels["mono"]


# ---------------------------------------------------------------------------
# POST /api/project/style
# ---------------------------------------------------------------------------
def test_project_style_api_switches_preset(tmp_path):
    """換畫風：200、preset／resolved.name／overview.config.style_preset 都對，明寫的 style 被拿掉。"""
    proj = new_project(tmp_path, yaml_extra="style: >-\n  手繪粗線條\n")
    assert styles.resolve(proj.config)["style"] == "手繪粗線條"
    resp = post("/api/project/style", {"project": str(proj.root), "preset": "color"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["preset"] == "color"
    assert data["resolved"]["name"] == styles.preset("color")["name"]
    assert data["resolved"]["style"] == styles.preset("color")["style"]
    assert data["overview"]["config"]["style_preset"] == "color"
    assert "style" in data["dropped"]
    assert "style_preset: color" in (proj.root / "project.yaml").read_text(encoding="utf-8")
    assert styles.resolve(Project(proj.root).config)["style"] != "手繪粗線條"


def test_project_style_api_rejects_bad_preset_and_missing_project(tmp_path):
    """preset 亂寫回 400 且訊息含可用值；沒帶 project 回 400。"""
    proj = new_project(tmp_path)
    bad = post("/api/project/style", {"project": str(proj.root), "preset": "no_such_preset"})
    assert bad.status_code == 400
    assert "可用：" in bad.json()["error"] and "mono" in bad.json()["error"]
    assert styles.resolve(Project(proj.root).config)["preset"] == "mono"
    missing = post("/api/project/style", {"preset": "color"})
    assert missing.status_code == 400
    assert "請先選擇" in missing.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/import/plan
# ---------------------------------------------------------------------------
def test_import_plan_returns_six_chapters_without_writing(tmp_path):
    """六章樣本回 6 章（no 1..6、章名對、chars > 0），而且一個檔案都沒寫。"""
    proj = new_project(tmp_path)
    before = tree(tmp_path)
    before_data = tree(SIX.parent)
    resp = post("/api/import/plan", {"path": str(SIX)})
    assert resp.status_code == 200
    chapters = resp.json()["chapters"]
    assert [c["no"] for c in chapters] == [1, 2, 3, 4, 5, 6]
    assert [c["title"] for c in chapters] == TITLES
    assert all(c["chars"] > 0 for c in chapters)
    assert all(c["head"] for c in chapters)                        # 預覽要看的第一行
    assert tree(tmp_path) == before                                # 專案資料夾樹前後相同：plan 不寫檔
    assert tree(SIX.parent) == before_data                         # 樣本旁邊也沒有多出暫存檔
    assert not any((proj.root / "source").iterdir())


def test_import_plan_missing_file_and_no_path_are_400(tmp_path):
    """檔案不存在回 400 且訊息看得懂；完全沒給路徑也是 400。"""
    missing = post("/api/import/plan", {"path": str(tmp_path / "nope.txt")})
    assert missing.status_code == 400
    assert "讀不到" in missing.json()["error"]
    assert "nope.txt" in missing.json()["error"]
    empty = post("/api/import/plan", {})
    assert empty.status_code == 400
    assert "請先選" in empty.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/import/commit
# ---------------------------------------------------------------------------
def test_import_commit_writes_chapters_then_skips_and_overwrites(tmp_path):
    """第一次寫 6 章；再跑 conflict=skip 全部略過；conflict=overwrite 全部取代並備份。"""
    proj = new_project(tmp_path)
    body = {"project": str(proj.root), "path": str(SIX)}
    first = post("/api/import/commit", body)
    assert first.status_code == 200
    data = first.json()
    assert [w["no"] for w in data["written"]] == [1, 2, 3, 4, 5, 6]
    assert [w["file"] for w in data["written"]] == ["source/ch%03d.txt" % n for n in range(1, 7)]
    assert data["skipped"] == [] and data["replaced"] == [] and data["backups"] == []
    assert data["chars"] > 0
    for n, title in enumerate(TITLES, start=1):
        path = proj.root / "source" / ("ch%03d.txt" % n)
        assert path.is_file()
        assert path.read_text(encoding="utf-8").splitlines()[0] == "# 第%d章 %s" % (n, title)
    assert data["overview"]["chapters"] and len(data["overview"]["chapters"]) == 6
    assert [p.name for p in tmp_path.iterdir()] == ["comic"]        # 只寫進專案裡

    again = post("/api/import/commit", body).json()                 # 預設 conflict=skip
    assert again["written"] == []
    assert again["skipped"] == [1, 2, 3, 4, 5, 6]

    over = post("/api/import/commit", dict(body, conflict="overwrite")).json()
    assert [w["no"] for w in over["written"]] == [1, 2, 3, 4, 5, 6]
    assert over["replaced"] == [1, 2, 3, 4, 5, 6]
    assert [row["no"] for row in over["backups"]] == [1, 2, 3, 4, 5, 6]
    for row in over["backups"]:
        assert row["files"], row                                  # 每一章都留了備份
        for rel in row["files"]:
            backup = proj.root / rel
            assert backup.is_file() and "build/import/backup/" in rel
    assert (proj.root / "source" / "ch001.txt").read_text(encoding="utf-8").splitlines()[0] == "# 第1章 雨夜"


def test_import_commit_rejects_bad_project_and_missing_file(tmp_path):
    """不是專案資料夾、或來源檔不存在，都回 400（訊息看得出原因），而且不寫檔。"""
    not_project = tmp_path / "not_project"
    not_project.mkdir()
    bad = post("/api/import/commit", {"project": str(not_project), "path": str(SIX)})
    assert bad.status_code == 400
    assert "不是漫畫專案資料夾" in bad.json()["error"]
    assert not any(not_project.iterdir())
    proj = new_project(tmp_path)
    missing = post("/api/import/commit", {"project": str(proj.root), "path": str(tmp_path / "nope.txt")})
    assert missing.status_code == 400
    assert "讀不到" in missing.json()["error"]
    assert not any((proj.root / "source").iterdir())

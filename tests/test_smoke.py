"""最基本的檢查：首頁有權杖、API 能呼叫、沒帶權杖的變更請求被擋。
執行：pip install -r requirements.txt，再 python -m pytest
"""
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")   # fekit 只接受 127.0.0.1／localhost 的 Host


def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def test_index_has_token_and_app_name():
    html = client.get("/").text
    assert 'name="fe-token"' in html
    assert 'name="fe-app" content="text2comics"' in html


def test_info():
    assert client.get("/api/info").json()["version"]


def test_post_without_token_is_rejected():
    response = client.post("/api/task/pages", json={"project": "x", "chapter": 1})
    assert response.status_code == 403
    assert response.json()["code"] == "bad_token"


def test_index_is_not_served_without_token():
    assert client.get("/static/index.html").status_code == 404
    assert client.get("/fekit/py/fekit/__init__.py").status_code == 404


def test_kit_files_are_served():
    assert client.get("/fekit/fe/core.js").status_code == 200
    assert client.get("/fekit/css/tokens.css").status_code == 200


# ---- 嵌字頁的 API（S3）--------------------------------------------------------------------

def _comic(tmp_path):
    """範例專案（設定、聖經、分鏡），renders 放合成的灰圖。"""
    import shutil
    from PIL import Image
    root = tmp_path / "comic"
    sample = ROOT / "examples" / "sample_comic"
    for sub in ("bible", "storyboard"):
        shutil.copytree(sample / sub, root / sub)
    shutil.copy(sample / "project.yaml", root / "project.yaml")
    (root / "renders" / "ch001").mkdir(parents=True)
    for slot in range(1, 6):
        Image.new("L", (1000, 800), 120).save(root / "renders" / "ch001" / ("p001_k%d_s11.png" % slot))
    return root


def _need_font():
    import pytest
    from t2c import letter
    try:
        letter.Settings.from_config({})
    except letter.LetterError:
        pytest.skip("這台電腦找不到中文字型")


def test_letter_plan_preview_and_save(tmp_path):
    import json as _json
    _need_font()
    root = str(_comic(tmp_path))
    data = client.get("/api/letter/plan", params={"project": root, "chapter": 1, "page": 1}).json()
    assert data["pages"] == [1] and len(data["plan"]["panels"]) == 5 and data["letters"] == {}
    draft = {"p001_k4": {"bubbles": [{"center": [0.3, 0.7]}]}}
    moved = client.post("/api/letter/plan", json={"project": root, "page": 1, "panels": draft},
                        headers={"X-FE-Token": token()}).json()["plan"]["panels"][3]["bubbles"][0]
    assert moved["auto_center"] is False
    image = client.get("/api/letter/preview.jpg", params={"project": root, "page": 1, "draft": _json.dumps(draft)})
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert client.get("/api/letter/art.png", params={"project": root, "page": 1}).headers["content-type"] == "image/png"
    saved = client.post("/api/letter/save", json={"project": root, "page": 1, "panels": draft},
                        headers={"X-FE-Token": token()}).json()
    assert Path(saved["page_png"]).is_file()
    stored = _json.loads(Path(saved["letters"]).read_text(encoding="utf-8"))
    assert stored["panels"]["p001_k4"]["bubbles"][0]["center"] == [0.3, 0.7]
    assert client.get("/api/letter/plan", params={"project": root, "page": 1}).json()["letters"]["p001_k4"]


def test_letter_api_errors_are_readable(tmp_path):
    _need_font()
    root = str(_comic(tmp_path))
    bad = client.post("/api/letter/plan", json={"project": root, "page": 1, "panels": {"p001_k1": {"faces": "x"}}},
                      headers={"X-FE-Token": token()})
    assert bad.status_code == 400 and "faces" in bad.json()["error"]
    other = client.post("/api/letter/plan", json={"project": root, "page": 1, "panels": {"p009_k1": {}}},
                        headers={"X-FE-Token": token()})
    assert other.status_code == 400 and "p009_k1" in other.json()["error"]
    assert client.get("/api/letter/plan", params={"project": root, "page": 9}).status_code == 400
    assert client.get("/api/letter/plan", params={"project": str(tmp_path / "nope")}).status_code == 400
    assert client.post("/api/letter/save", json={"project": root, "page": 1, "panels": {}}).status_code == 403

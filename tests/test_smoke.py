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


def test_hello():
    assert client.get("/api/hello", params={"name": "測試"}).json() == {"message": "你好，測試！"}


def test_post_without_token_is_rejected():
    response = client.post("/api/demo-task")
    assert response.status_code == 403
    assert response.json()["code"] == "bad_token"


def test_post_with_token_starts_a_task():
    response = client.post("/api/demo-task", headers={"X-FE-Token": token()})
    assert response.status_code == 200
    assert response.json()["id"]
    app_module.runner.stop_all()


def test_index_is_not_served_without_token():
    assert client.get("/static/index.html").status_code == 404
    assert client.get("/fekit/py/fekit/__init__.py").status_code == 404


def test_kit_files_are_served():
    assert client.get("/fekit/fe/core.js").status_code == 200
    assert client.get("/fekit/css/tokens.css").status_code == 200

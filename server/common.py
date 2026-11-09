"""後端共用：任務佇列、設定、錯誤轉換。"""
from contextlib import contextmanager

from fekit import ApiError, JobRunner

from t2c import bible, comfy, compose, export, letter, llm, settings, workspace
from t2c.adapt import AdaptError
from t2c.compile import CompileError
from t2c.project import ProjectError
from t2c.render import RenderError

# 任務排隊、同時只跑一個：LLM 與 ComfyUI 不會被本工具同時叫起來（docs/05_介面設計.md 第 4 節）。
runner = JobRunner(queue=True)

CORE_ERRORS = (workspace.WorkspaceError, ProjectError, CompileError, compose.ComposeError, bible.BibleError,
               letter.LetterError, RenderError, AdaptError, llm.LLMError, comfy.ComfyError, export.ExportError)


@contextmanager
def guard(code="bad_request"):
    """核心的錯誤 → ApiError(400)。"""
    try:
        yield
    except CORE_ERRORS as error:
        raise ApiError(400, str(error), code)


def config():
    try:
        return settings.load()
    except (FileNotFoundError, ValueError) as error:
        raise ApiError(400, "讀不到工具設定：%s" % error, "no_config")


def project(path):
    with guard("bad_project"):
        return workspace.open_project(path)


def chapter(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "章節編號要是整數", "bad_chapter")
    if not 1 <= n <= workspace.MAX_CHAPTER:
        raise ApiError(400, "章節編號要在 1–%d 之間" % workspace.MAX_CHAPTER, "bad_chapter")
    return n


def body_project(body):
    if not isinstance(body, dict):
        raise ApiError(400, "請求內容要是 JSON 物件", "bad_request")
    return project(body.get("project"))

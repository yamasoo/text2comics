"""文字轉漫畫：後端。啟動請用 python run.py（或雙擊 start.bat）。

漫畫的核心邏輯在 t2c/（不依賴網頁框架）；這裡只放 API 與背景任務，呼叫 t2c。

fekit 的 Python 輔助放在 vendor/fekit/py/，不要直接改它（改法見 README.md「更新 fekit」）。
"""
import json
import sys
import threading
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "fekit" / "py"))

from fastapi import Body, FastAPI  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from fekit import ApiError, JobError, JobRunner, install  # noqa: E402

from t2c import compose, layout, letter  # noqa: E402
from t2c import settings as tool_settings  # noqa: E402

from t2c import __version__ as T2C_VERSION  # noqa: E402
from t2c.compile import CompileError, compile_chapter, save_job  # noqa: E402
from t2c.project import Project, ProjectError  # noqa: E402

WEB = ROOT / "web"
FEKIT = ROOT / "vendor" / "fekit"

app = FastAPI()
runner = JobRunner()                                   # 同時只跑 1 個任務；JobRunner(queue=True) 會排隊

# 本機保護（Host、權杖）、錯誤格式、任務端點 /api/jobs…。必須在 app 開始服務前呼叫。
fe = install(app, app_name="text2comics", jobs=runner)


# ---- 你的 API（從這裡開始改）----------------------------------------------------

@app.get("/api/hello")
def hello(name: str = "世界"):
    return {"message": "你好，%s！" % name}


def count_task(job, total):
    """任務函式在背景執行緒跑；第一個參數是 Job，面板會即時顯示它回報的東西。"""
    job.set(phase="streaming", note="共 %d 步" % total, progress=(0, total))
    job.begin("out", "輸出")
    for step in range(1, total + 1):
        job.checkpoint()                               # 使用者按了停止就在這裡結束
        job.write("out", "第 %d 步完成\n" % step)
        job.set(progress=(step, total))
        job.sleep(0.5)
    job.end("out")
    return "完成，共 %d 步。" % total


@app.post("/api/demo-task")
def start_demo_task():
    return runner.start(count_task, 6, kind="demo", title="示範任務").summary()


SAMPLE = ROOT / "examples" / "sample_comic"


@app.get("/api/info")
def info():
    return {"version": T2C_VERSION, "sample": str(SAMPLE)}


def compile_task(job, project_dir, chapter):
    """分鏡 → 每格的 MOSS layout prompt（不出圖），寫到專案的 build/。"""
    try:
        project = Project(project_dir)
        jobs = compile_chapter(project, project.load_storyboard(chapter))
    except (ProjectError, CompileError) as error:
        raise JobError(str(error))
    build = project.out_dir("build", "ch%03d" % chapter)
    job.set(phase="streaming", note="共 %d 格" % len(jobs), progress=(0, len(jobs)))
    job.begin("out", "每格的提示詞")
    for index, item in enumerate(jobs, 1):
        job.checkpoint()
        save_job(build, item)
        job.write("out", "%s　%d×%d　seeds %s\n" % (item["id"], item["width"], item["height"], item["seeds"]))
        job.set(progress=(index, len(jobs)))
    job.end("out")
    return "已編譯 %d 格，寫到 %s" % (len(jobs), build)


@app.post("/api/sample/compile")
def start_sample_compile():
    return runner.start(compile_task, SAMPLE, 1, kind="compile", title="編譯範例分鏡").summary()


# ---- 嵌字（S3）：介面拖曳微調 ----------------------------------------------------------
# 微調只存在瀏覽器裡（草稿），按「存檔」才寫進 letters/chNNN.json 並重新輸出頁面。

_ART = OrderedDict()                                   # 組好、還沒嵌字的頁面（拖曳預覽時重用）
_ART_MAX = 6
_LOCK = threading.Lock()
_SETTINGS = {}


def _lettering():
    """config.json 的 lettering → letter.Settings；設定檔沒變就重用（找字型要掃資料夾）。"""
    try:
        cfg = tool_settings.load()
        key = (cfg["_path"], Path(cfg["_path"]).stat().st_mtime)
        if key not in _SETTINGS:
            _SETTINGS.clear()
            _SETTINGS[key] = letter.Settings.from_config(cfg.get("lettering"))
        return _SETTINGS[key]
    except (letter.LetterError, FileNotFoundError) as error:
        raise ApiError(400, str(error), "no_font")


def _open(project_dir, chapter, page_no):
    try:
        project = Project(project_dir or SAMPLE)
        storyboard = project.load_storyboard(chapter)
        page = compose.find_page(storyboard, page_no)
        compile_chapter(project, storyboard, only_page=page_no)        # 先過分鏡驗證
        picks = compose.load_picks(project, chapter)
    except (ProjectError, CompileError, compose.ComposeError) as error:
        raise ApiError(400, str(error), "bad_project")
    return project, storyboard, page, picks


def _art(project, chapter, page, pages_data, picks):
    """沒有嵌字的頁面；圖、選圖、裁切都沒變就用快取。"""
    infos, _ = compose.page_panels(project, chapter, page, pages_data, picks)
    key = (str(project.root), chapter, page["page"],
           tuple((str(i["source"]), i["source"].stat().st_mtime if i["source"] else 0, tuple(i["window"])) for i in infos))
    with _LOCK:
        if key in _ART:
            _ART.move_to_end(key)
            return _ART[key]
    canvas, warnings = compose.compose_page(project, chapter, page, pages_data, picks)
    with _LOCK:
        _ART[key] = (canvas, warnings)
        while len(_ART) > _ART_MAX:
            _ART.popitem(last=False)
    return canvas, warnings


def _draft(project, chapter, page, panels):
    """介面送來的這一頁微調 {格 id: {...}} → 合併進整章的 letters（這一頁的格以草稿為準）。"""
    if panels is not None and not isinstance(panels, dict):
        raise ApiError(400, "panels 要是 {格 id: 微調}", "bad_letters")
    try:
        letters = letter.load_letters(project, chapter)
        if panels is None:
            return letters
        ids = {p.get("id") or "p%03d_k%d" % (page["page"], p["slot"]) for p in page.get("panels") or []}
        unknown = sorted(set(panels) - ids)
        if unknown:
            raise ApiError(400, "第 %s 頁沒有這些格：%s" % (page["page"], "、".join(unknown)), "bad_letters")
        for pid in ids:
            letters.pop(pid, None)
        for pid, entry in panels.items():
            letters[pid] = letter.check_panel_letters(pid, entry)
        return letters
    except letter.LetterError as error:
        raise ApiError(400, str(error), "bad_letters")


def _render(project, chapter, page, picks, letters, guides=False):
    pages_data = layout.load_pages()
    settings = _lettering()
    art, art_warnings = _art(project, chapter, page, pages_data, picks)
    try:
        canvas, plan, warnings = compose.render_page(project, chapter, page, pages_data, picks, lettering=settings,
                                                     letters=letters, guides=guides, art=art)
    except (compose.ComposeError, letter.LetterError) as error:
        raise ApiError(400, str(error), "letter_failed")
    plan["warnings"] = settings.notes + art_warnings + plan["warnings"]
    return canvas, plan


def _png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


def _jpeg(image):
    """拖曳預覽用：JPEG 比 PNG 小很多，畫質足夠看位置。"""
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return Response(buffer.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _page_numbers(storyboard):
    return [int(p["page"]) for p in storyboard.get("pages") or []]


@app.get("/api/letter/plan")
def letter_plan(project: str = "", chapter: int = 1, page: int = 1):
    """這一頁的嵌字位置（整頁像素）＋目前存檔的微調。"""
    proj, storyboard, pg, picks = _open(project, chapter, page)
    letters = _draft(proj, chapter, pg, None)
    _, plan = _render(proj, chapter, pg, picks, letters)
    ids = [p["id"] for p in plan["panels"]]
    return {"project": str(proj.root), "chapter": chapter, "page": page, "pages": _page_numbers(storyboard),
            "plan": plan, "letters": {pid: letter.clean_entry(letters[pid]) for pid in ids if pid in letters}}


@app.post("/api/letter/plan")
def letter_plan_draft(body: dict = Body(...)):
    """用草稿重算位置（不存檔）。"""
    chapter, page = int(body.get("chapter", 1)), int(body.get("page", 1))
    proj, _, pg, picks = _open(body.get("project", ""), chapter, page)
    _, plan = _render(proj, chapter, pg, picks, _draft(proj, chapter, pg, body.get("panels")))
    return {"plan": plan}


@app.get("/api/letter/art.png")
def letter_art(project: str = "", chapter: int = 1, page: int = 1):
    proj, _, pg, picks = _open(project, chapter, page)
    return _png(_art(proj, chapter, pg, layout.load_pages(), picks)[0])


@app.get("/api/letter/preview.jpg")
def letter_preview(project: str = "", chapter: int = 1, page: int = 1, draft: str = "", guides: bool = False):
    """嵌好字的頁面；draft 是這一頁微調的 JSON（沒給就用存檔的）。"""
    proj, _, pg, picks = _open(project, chapter, page)
    try:
        panels = json.loads(draft) if draft else None
    except json.JSONDecodeError:
        raise ApiError(400, "draft 不是合法的 JSON", "bad_letters")
    canvas, _ = _render(proj, chapter, pg, picks, _draft(proj, chapter, pg, panels), guides=guides)
    return _jpeg(canvas)


@app.post("/api/letter/save")
def letter_save(body: dict = Body(...)):
    """把這一頁的微調寫進 letters/chNNN.json，並重新輸出 pages/chNNN/pNNN.png。"""
    chapter, page = int(body.get("chapter", 1)), int(body.get("page", 1))
    proj, _, pg, picks = _open(body.get("project", ""), chapter, page)
    letters = _draft(proj, chapter, pg, body.get("panels") or {})
    canvas, plan = _render(proj, chapter, pg, picks, letters)
    path = letter.save_letters(proj, chapter, letters)
    out = compose.save_page(canvas, compose.pages_dir(proj, chapter) / ("p%03d.png" % page), layout.load_pages())
    return {"letters": str(path), "page_png": str(out), "warnings": plan["warnings"]}


# ---- 頁面與靜態檔 ---------------------------------------------------------------

@app.get("/")
def index():
    return fe.page(WEB / "index.html")                 # 把權杖寫進 <meta>，所以首頁不放在靜態資料夾


for sub in ("css", "fe", "vendor"):                    # 只公開瀏覽器要用的部分（不含 py/）
    if (FEKIT / sub).is_dir():
        app.mount("/fekit/" + sub, StaticFiles(directory=FEKIT / sub), name="fekit-" + sub)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

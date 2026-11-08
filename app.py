"""文字轉漫畫：後端。啟動請用 python run.py（或雙擊 start.bat）。

漫畫的核心邏輯在 t2c/（不依賴網頁框架）；這裡只放 API 與背景任務，呼叫 t2c。

fekit 的 Python 輔助放在 vendor/fekit/py/，不要直接改它（改法見 README.md「更新 fekit」）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor" / "fekit" / "py"))

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from fekit import JobError, JobRunner, install  # noqa: E402

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


# ---- 頁面與靜態檔 ---------------------------------------------------------------

@app.get("/")
def index():
    return fe.page(WEB / "index.html")                 # 把權杖寫進 <meta>，所以首頁不放在靜態資料夾


for sub in ("css", "fe", "vendor"):                    # 只公開瀏覽器要用的部分（不含 py/）
    if (FEKIT / sub).is_dir():
        app.mount("/fekit/" + sub, StaticFiles(directory=FEKIT / sub), name="fekit-" + sub)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

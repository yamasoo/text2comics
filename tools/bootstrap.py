"""第一次啟動：沒有 .venv 就建一個、裝 requirements.txt，然後啟動 run.py。

start.bat 只負責找 Python 並呼叫這裡（.bat 用 ASCII，中文訊息都由 Python 印）。
手動用法：python tools/bootstrap.py [run.py 的參數，例如 --port 9000 --no-open]
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PY = VENV / "Scripts" / "python.exe"
REQ = ROOT / "requirements.txt"


def say(text):
    print(text, flush=True)


def make_venv():
    say("[1/3] 找不到 .venv，建立虛擬環境…")
    try:
        import venv
        venv.EnvBuilder(with_pip=True, clear=False).create(str(VENV))
    except Exception as error:                                  # noqa: BLE001 - 任何原因都要給人看的訊息
        raise SystemExit("建立 .venv 失敗：%s\n請手動執行 python -m venv .venv 之後再試。" % error)
    if not PY.is_file():
        raise SystemExit("建立 .venv 後找不到 %s；請確認 Python 是 3.10 以上。" % PY)


def install():
    if not REQ.is_file():
        raise SystemExit("找不到 requirements.txt，這個資料夾不完整；請重新 clone 或下載。")
    say("[2/3] 安裝套件（requirements.txt）…")
    for cmd in ([str(PY), "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
                [str(PY), "-m", "pip", "install", "-r", str(REQ)]):
        if subprocess.call(cmd, cwd=str(ROOT)) != 0:
            raise SystemExit("安裝套件失敗。請檢查網路後重試，或手動執行：\n"
                             "  .venv\\Scripts\\python.exe -m pip install -r requirements.txt")


def main(argv):
    if not shutil.which("py") and not shutil.which("python") and not PY.is_file():
        raise SystemExit("找不到 Python 3。請安裝 Python 3.10 以上（安裝時勾選 Add Python to PATH）後再執行 start.bat。")
    if not PY.is_file():
        make_venv()
        install()
    if not (ROOT / "config.json").is_file():
        say("提醒：沒有 config.json，會用 config.example.json 的預設值。")
        say("      要保留自己的設定（provider、出圖 profile）就複製一份：copy config.example.json config.json")
        say("")
    say("[3/3] 啟動。")
    return subprocess.call([str(PY), str(ROOT / "run.py")] + list(argv), cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

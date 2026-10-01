"""One-command local startup after installing requirements (uses this interpreter)."""

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
os.chdir(root)
(root / "data").mkdir(exist_ok=True)
for command in [
    ["migrate", "--noinput"],
    ["seed_demo", "--once"],
    ["collectstatic", "--noinput"],
]:
    subprocess.run([sys.executable, "manage.py", *command], check=True)
subprocess.run(
    [sys.executable, "manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
    check=True,
)

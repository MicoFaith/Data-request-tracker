"""Run all frontend/build and backend checks using Docker from a clean checkout."""

import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
for command in [
    ["docker", "compose", "build"],
    [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "web",
        "python",
        "manage.py",
        "test",
        "--noinput",
    ],
    [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "web",
        "python",
        "manage.py",
        "makemigrations",
        "--check",
        "--dry-run",
    ],
]:
    subprocess.run(command, cwd=root, check=True)
print(
    "PASS: frontend tests, production build, backend tests and migration consistency."
)
subprocess.run([sys.executable, "scripts/test_postgres.py"], cwd=root, check=True)
print("PASS: PostgreSQL backend suite.")

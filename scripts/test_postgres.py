"""Run the same backend suite against a disposable local PostgreSQL database."""

import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
compose = [
    "docker",
    "compose",
    "-p",
    f"desk-postgres-test-{os.getpid()}",
    "-f",
    "compose.test.yaml",
]
try:
    subprocess.run(
        compose
        + ["up", "--build", "--abort-on-container-exit", "--exit-code-from", "tests"],
        cwd=root,
        check=True,
    )
finally:
    subprocess.run(compose + ["down", "--volumes"], cwd=root, check=True)

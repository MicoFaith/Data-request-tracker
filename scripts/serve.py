"""Supervise web and email processes inside one hosted service."""

import os
import signal
import subprocess
import sys
import time


def main():
    stopping = False
    processes = []

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        commands = [
            [
                sys.executable,
                "-m",
                "gunicorn",
                "config.wsgi:application",
                "--bind",
                f"0.0.0.0:{os.environ.get('PORT', '8000')}",
                "--workers",
                "2",
                "--timeout",
                "60",
            ],
            [sys.executable, "manage.py", "deliver_notifications", "--watch"],
        ]
        for command in commands:
            processes.append(subprocess.Popen(command))
        while not stopping:
            if any(process.poll() is not None for process in processes):
                print(
                    "A service process stopped; restarting the service is required.",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
            time.sleep(0.5)
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    sys.exit(main())

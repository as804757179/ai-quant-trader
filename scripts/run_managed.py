from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import threading


def _create_logger(name: str, path: Path, max_bytes: int, backups: int) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"managed.{name}.{path.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    if path.exists() and path.stat().st_size:
        handler.doRollover()
    logger.addHandler(handler)
    return logger


def _pump(stream: object, logger: logging.Logger) -> None:
    for line in iter(stream.readline, ""):
        logger.info(line.rstrip("\r\n"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--stdout-log", type=Path, required=True)
    parser.add_argument("--stderr-log", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--backups", type=int, default=3)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("缺少要运行的命令。", file=sys.stderr)
        return 2

    stdout_logger = _create_logger(
        f"{args.name}.stdout", args.stdout_log, args.max_bytes, args.backups
    )
    stderr_logger = _create_logger(
        f"{args.name}.stderr", args.stderr_log, args.max_bytes, args.backups
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=args.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as error:
        stderr_logger.error("无法启动子进程：%s", error)
        return 127
    assert process.stdout is not None
    assert process.stderr is not None
    threads = [
        threading.Thread(target=_pump, args=(process.stdout, stdout_logger)),
        threading.Thread(target=_pump, args=(process.stderr, stderr_logger)),
    ]
    for thread in threads:
        thread.start()
    exit_code = process.wait()
    for thread in threads:
        thread.join()
    for logger in (stdout_logger, stderr_logger):
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

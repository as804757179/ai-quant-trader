from pathlib import Path
import subprocess
import sys


def test_managed_runner_rotates_live_logs(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    runner = root / "scripts" / "run_managed.py"
    stdout_log = tmp_path / "stdout.log"
    stderr_log = tmp_path / "stderr.log"
    child_code = (
        "import sys;"
        "sys.stdout.write(('x' * 120 + '\\n') * 100);"
        "sys.stderr.write(('e' * 120 + '\\n') * 100)"
    )

    subprocess.run(
        [
            sys.executable,
            str(runner),
            "--name",
            "test",
            "--stdout-log",
            str(stdout_log),
            "--stderr-log",
            str(stderr_log),
            "--cwd",
            str(root),
            "--max-bytes",
            "1024",
            "--backups",
            "3",
            "--",
            sys.executable,
            "-c",
            child_code,
        ],
        check=True,
        timeout=10,
    )

    for log_path in (stdout_log, stderr_log):
        assert log_path.stat().st_size <= 1024
        assert all(Path(f"{log_path}.{index}").exists() for index in range(1, 4))
        assert not Path(f"{log_path}.4").exists()

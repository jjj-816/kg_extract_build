"""生产闭环验收命令使用的轻量摘要。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def acceptance_command() -> tuple[str, ...]:
    return ("conda", "run", "-n", "env_agent", "python", "-m", "pytest", "kg_extract_build/tests/test_production_closure.py", "kg_extract_build/tests/test_report_service.py", "kg_extract_build/tests/test_reasonableness.py", "-q")


def run_acceptance(cwd: str | Path) -> int:
    completed = subprocess.run(acceptance_command(), cwd=str(cwd), check=False)
    return completed.returncode

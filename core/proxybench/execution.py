from __future__ import annotations

import sys
from pathlib import Path


def cli_python() -> str:
    """Use console Python for awaited background CLI work, including a pythonw-launched UI."""
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
        if not executable.is_file():
            raise ValueError("安装包缺少后台 Python 执行器")
    return str(executable)

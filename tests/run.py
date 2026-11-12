#!/usr/bin/env python3
"""Test repository sources in an isolated home; never use installed workflow tools."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="repo-tools-tests-") as directory:
    stage = Path(directory)
    for name in ("install.py", "install_dependencies.py", "desktop_build.py", "standalone_build.py", "install_mods.py"):
        shutil.copy2(source / name, stage / name)
    shutil.copy2(source / "herdr/helpers/window.py", stage / "window_helper.py")
    shutil.copytree(source / "bin", stage, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in (source / "tests").glob("test_*.py"):
        shutil.copy2(path, stage / path.name)
    shutil.copy2(source / "tests/check_sources.py", stage / "check_sources.py")
    home = stage / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PYTHONPATH=str(stage),
               PYTHONDONTWRITEBYTECODE="1", XDG_STATE_HOME=str(home / "state"),
               XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"),
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    # Resolve only repository modules, even if this machine has an older install.
    subprocess.run(
        [
            sys.executable,
            "-c",
            'import repo_operations,unittest; unittest.main(module=None,argv=["tests","discover","-s",".","-p","test_*.py"])',
        ],
        cwd=stage,
        env=env,
        check=True,
    )

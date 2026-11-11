#!/usr/bin/env python3
"""Test the candidate scripts with installed dependencies, never live agents."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="repo-tools-tests-") as directory:
    stage = Path(directory)
    shutil.copy2(source / "install.py", stage / "install.py")
    for path in (source / "bin").iterdir():
        if path.is_file():
            shutil.copy2(path, stage / path.name)
    for path in (source / "tests").glob("test_*.py"):
        shutil.copy2(path, stage / path.name)
    env = dict(os.environ, PYTHONPATH=str(stage), PYTHONDONTWRITEBYTECODE="1")
    # Test_checkpoint puts installed tools first; load the shared contract explicitly
    # from this stage in the subprocess, before unittest discovers test modules.
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

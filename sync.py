#!/usr/bin/env python3
"""Fast-forward this source checkout, install the selected profile, and verify."""
import argparse
from pathlib import Path
import subprocess as sp
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("profile", choices=("laptop", "jumpbox"))
a = p.parse_args()
root = Path(__file__).resolve().parent
if sp.check_output(["git", "status", "--porcelain"], cwd=root).strip():
    sys.exit("Source checkout has changes; commit or reconcile them before syncing.")
sp.run(["git", "pull", "--ff-only"], cwd=root, check=True)
for option in ("--apply", "--verify"):
    sp.run([sys.executable, "install.py", a.profile, option], cwd=root, check=True)

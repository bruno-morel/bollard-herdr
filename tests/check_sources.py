#!/usr/bin/env python3
"""Check source syntax and accidental private configuration before publication."""
import json
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys

root = Path(__file__).resolve().parents[1]
sp.run([sys.executable, str(root / 'desktop_build.py'), '--check'], check=True)
count = 0
private = [
    rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
    rb'gh[pousr]_[A-Za-z0-9]{30,}',
    rb'sk-(?:ant-)?[A-Za-z0-9_-]{35,}',
    rb'/Users/[a-zA-Z][^/\s"\']*/',
    rb'192\.168\.\d+\.\d+',
]
for folder in ('bin', 'desktop', 'herdr', 'tui', 'zellij', 'shell'):
    for path in (root / folder).rglob('*'):
        if not path.is_file():
            continue
        if path.suffix == '.png':
            continue  # Gallery preview is visually inspected before publication.
        data = path.read_bytes()
        if b'\0' in data or any(re.search(pattern, data) for pattern in private):
            raise SystemExit('Unexpected binary/private configuration: ' + str(path))
        first = data.split(b'\n', 1)[0]
        if path.suffix == '.py' or (first.startswith(b'#!') and b'python' in first):
            compile(data, str(path), 'exec')
        elif path.suffix == '.zsh' or (first.startswith(b'#!') and b'sh' in first):
            shell = 'zsh' if path.suffix == '.zsh' or b'zsh' in first else 'sh'
            if not shutil.which(shell):
                raise SystemExit('Install ' + shell + ' to validate shell sources')
            sp.run([shell, '-n', str(path)], check=True)
        elif path.suffix == '.json':
            json.loads(data)
        count += 1
print('Validated', count, 'source files (syntax and private-configuration scan).')

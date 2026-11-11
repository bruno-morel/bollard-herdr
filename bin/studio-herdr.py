#!/usr/bin/env python3
"""Compatibility entry point; studio herdr uses the shared launcher."""
import sys
from repo_herdr import main
if __name__ == '__main__':
    sys.exit(main(['studio', *sys.argv[1:]]))

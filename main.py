"""Compatibility launcher for running from repo root."""

import os
import sys


def main():
    src_dir = os.path.join(os.path.dirname(__file__), "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from drmulperi.main import main as pkg_main

    pkg_main()


if __name__ == "__main__":
    main()

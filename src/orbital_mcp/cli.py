from __future__ import annotations

import argparse
from pathlib import Path

from .server import run_stdio


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Orbital MCP over stdio.")
    parser.add_argument("--base-dir", default=".", help="Directory containing orbital.config.json")
    args = parser.parse_args()
    run_stdio(Path(args.base_dir).resolve())


if __name__ == "__main__":
    main()

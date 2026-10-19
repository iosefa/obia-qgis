#!/usr/bin/env python3
"""Download and verify a committed manifest for release audits (maintainers only)."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.manager import _download_verified  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "platform", choices=["win-64", "linux-64", "osx-64", "osx-arm64"]
    )
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    packages = json.loads(
        (ROOT / "runtime/locks" / (args.platform + ".json")).read_text()
    )["packages"]

    def fetch(item):
        return _download_verified(
            item["url"],
            args.destination / item["filename"],
            item["sha256"],
            item["size"],
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        for index, path in enumerate(pool.map(fetch, packages), 1):
            print(f"{index}/{len(packages)} {path.name}", flush=True)


if __name__ == "__main__":
    main()

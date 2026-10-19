#!/usr/bin/env python3
"""Maintainer-only solver. Users install the committed, SHA256-pinned manifests.

Usage: python scripts/lock_engine.py /path/to/micromamba [platform ...]
The solver cache and temporary prefixes stay in --work (default /tmp/obia-lock).
Review new locks, regenerate the Windows path audit, then increment ENGINE_VERSION.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPECS = [
    "python=3.12",
    "numpy>=2.1.1",
    "rasterio>=1.3.11",
    "shapely>=2.0.3",
    "pillow>=10.3",
    "pandas>=2.2.2",
    "geopandas-base>=1.0.1",
    "pyogrio",
    "scipy>=1.14.1",
    "scikit-image>=0.23.2",
    "tqdm>=4.66.2",
    "scikit-learn>=1.4.2",
    "py-xgboost>=2.1.4=cpu*",
    "affine>=2.4.0",
    "pyproj>=3.6.1",
    "libopencv>=4.10=headless*",
    "py-opencv>=4.10=headless*",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("micromamba")
    parser.add_argument(
        "platforms", nargs="*", default=["osx-arm64", "osx-64", "linux-64", "win-64"]
    )
    parser.add_argument("--work", type=Path, default=Path("/tmp/obia-lock"))
    args = parser.parse_args()
    for tag in args.platforms:
        env = os.environ.copy()
        env.update(
            MAMBA_ROOT_PREFIX=str(args.work / "mamba"),
            CONDA_OVERRIDE_CUDA="",
            CONDA_OVERRIDE_GLIBC="2.28",
            CONDA_OVERRIDE_OSX="13.0",
        )
        result = subprocess.run(
            [
                args.micromamba,
                "create",
                "--dry-run",
                "--json",
                "--no-rc",
                "--no-env",
                "--root-prefix",
                str(args.work / "mamba"),
                "--prefix",
                str(args.work / tag),
                "--platform",
                tag,
                "--override-channels",
                "-c",
                "conda-forge",
                *SPECS,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        solved = json.loads(result.stdout)
        packages = []
        for item in solved["actions"]["LINK"]:
            packages.append(
                {
                    "name": item["name"],
                    "version": item["version"],
                    "build": item["build_string"],
                    "filename": item["fn"],
                    "url": item["url"],
                    "sha256": item["sha256"],
                    "size": item["size"],
                }
            )
        lock = {
            "engine_version": "0.2.0-1",
            "platform": tag,
            "channel": "https://conda.anaconda.org/conda-forge",
            "specs": SPECS,
            # Explicit installs preserve this sequence. A package's post-link
            # script may execute binaries requiring already installed DLLs.
            "packages": packages,
        }
        (ROOT / "runtime/locks" / (tag + ".json")).write_text(
            json.dumps(lock, indent=2) + "\n"
        )
        print(
            f"{tag}: {len(packages)} packages; {sum(p['size'] for p in packages) / 1e6:.1f} MB",
            flush=True,
        )


if __name__ == "__main__":
    main()

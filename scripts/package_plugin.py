#!/usr/bin/env python3
"""Build a reproducible QGIS Install-from-ZIP artifact, using only stdlib."""

import configparser
import hashlib
import json
from pathlib import Path
import zipfile

from check_plugin_zip import check_archive

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "obia_qgis"
FILES = [
    "__init__.py",
    "obia_plugin.py",
    "provider.py",
    "setup_dialog.py",
    "metadata.txt",
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "tests/README.md",
]
DIRECTORIES = ["algorithms", "runtime", "icons", "docs", "vendor"]


def build():
    if not (ROOT / "LICENSE").read_text().strip():
        raise ValueError("A plugin LICENSE is required.")
    source = json.loads((ROOT / "vendor/obia/SOURCE.json").read_text())
    for name, digest in source["files"].items():
        if (
            hashlib.sha256((ROOT / "vendor/obia" / name).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError(f"Bundled OBIA release source changed: {name}")
    audit = json.loads((ROOT / "runtime/windows-paths.json").read_text())
    bootstrap = json.loads((ROOT / "runtime/bootstrap.json").read_text())
    if (
        audit["lock_sha256"]
        != hashlib.sha256((ROOT / "runtime/locks/win-64.json").read_bytes()).hexdigest()
        or audit["installer_sha256"] != bootstrap["platforms"]["win-64"]["sha256"]
    ):
        raise ValueError("Regenerate the Windows path audit before packaging.")
    config = configparser.ConfigParser()
    config.read(ROOT / "metadata.txt")
    version = config["general"]["version"]
    entries = [ROOT / name for name in FILES]
    for name in DIRECTORIES:
        entries += [
            p
            for p in (ROOT / name).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in (".pyc", ".pyo")
            and not p.name.startswith(".")
        ]
    output = ROOT / "dist" / f"{PLUGIN}-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(entries):
            info = zipfile.ZipInfo(
                PLUGIN + "/" + path.relative_to(ROOT).as_posix(),
                date_time=(2026, 10, 19, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    check_archive(output)
    (output.parent / f"{PLUGIN}.zip").write_bytes(output.read_bytes())
    print(output)
    return output


if __name__ == "__main__":
    build()

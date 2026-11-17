"""One isolated process per operation; no scientific modules enter QGIS."""

import argparse
import faulthandler
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
_DLL_HANDLES = []


def configure_runtime():
    """Retain conda DLL directories for Windows Python 3.8+ native imports."""
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for relative in ("Library/bin", "DLLs"):
            directory = Path(sys.prefix) / relative
            if directory.is_dir():
                _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    sys.path.insert(0, str(ROOT / "vendor" / "obia"))
    sys.path.insert(0, str(ROOT / "runtime"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    code = 0
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if (
            not isinstance(request, dict)
            or request.get("protocol") != 1
            or not isinstance(request.get("payload"), dict)
        ):
            raise ValueError("Incompatible OBIA worker request.")
        if request.get("operation") == "selftest":
            # A native import can block before Python raises an exception. Keep
            # periodic thread stacks in the parent's validation log until exit.
            faulthandler.enable()
            faulthandler.dump_traceback_later(60, repeat=True)
            print(
                json.dumps(
                    {
                        "type": "validation",
                        "value": 0,
                        "message": "Starting engine checks",
                    }
                ),
                flush=True,
            )
        configure_runtime()
        from jobs import dispatch

        result = dispatch(request["operation"], request["payload"])
        if request["operation"] == "selftest":
            print(
                json.dumps(
                    {
                        "type": "validation",
                        "value": 100,
                        "message": "Finishing engine checks",
                    }
                ),
                flush=True,
            )
        response = {"protocol": 1, "ok": True, "result": result}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        response = {"protocol": 1, "ok": False, "error": {"message": str(exc)}}
        code = 1
    args.result.write_text(json.dumps(response, allow_nan=False), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Zip the add-on for Blender: Install from Disk / Install…"""

from __future__ import annotations

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FOLDER = "bilingual_ui"
OUT = os.path.join(ROOT, "bilingual_ui.zip")

INCLUDE = {
    "__init__.py",
    "core.py",
    "blender_manifest.toml",
    "README.md",
}


def main() -> None:
    if os.path.isfile(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(INCLUDE):
            src = os.path.join(ROOT, name)
            if not os.path.isfile(src):
                raise SystemExit(f"missing {name}")
            zf.write(src, f"{FOLDER}/{name}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()

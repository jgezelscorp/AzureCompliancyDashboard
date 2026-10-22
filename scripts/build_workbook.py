"""Regenerate workbooks/azure-compliance.workbook.json (+ Bicep parts) from workbooks/queries.

Use --check in CI. The deployed JSON is loaded by Bicep as two parts because loadTextContent is
limited to 131072 characters per file.
"""
import sys

from workbook_lib import PART_DIR, PART_PATHS, WORKBOOK_PATH, build_workbook, render, split_parts


def _read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""


def main() -> int:
    text = render(build_workbook())
    parts = split_parts(text)
    if "--check" in sys.argv:
        stale = [WORKBOOK_PATH] if _read(WORKBOOK_PATH) != text else []
        stale += [p for p, part in zip(PART_PATHS, parts) if _read(p) != part]
        if stale:
            print("out of date: " + ", ".join(p.name for p in stale) + " (run python scripts/build_workbook.py)")
            return 1
        print("workbook JSON is up to date")
        return 0
    PART_DIR.mkdir(parents=True, exist_ok=True)
    WORKBOOK_PATH.write_text(text, encoding="utf-8", newline="\n")
    for path, part in zip(PART_PATHS, parts):
        path.write_text(part, encoding="utf-8", newline="\n")
    print(f"wrote {WORKBOOK_PATH} ({len(text)} chars) and {len(parts)} parts")
    return 0


if __name__ == "__main__":
    sys.exit(main())

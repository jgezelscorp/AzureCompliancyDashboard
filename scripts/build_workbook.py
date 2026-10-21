"""Regenerate workbooks/azure-compliance.workbook.json from workbooks/queries (use --check in CI)."""
import sys

from workbook_lib import WORKBOOK_PATH, build_workbook, render


def main() -> int:
    text = render(build_workbook())
    if "--check" in sys.argv:
        current = WORKBOOK_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") if WORKBOOK_PATH.exists() else ""
        if current != text:
            print("workbook JSON is out of date: run python scripts/build_workbook.py")
            return 1
        print("workbook JSON is up to date")
        return 0
    WORKBOOK_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {WORKBOOK_PATH} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

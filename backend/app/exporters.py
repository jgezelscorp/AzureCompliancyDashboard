"""Export rendering (I09): injection-safe CSV and a dependency-free, text-only PDF writer.

The PDF writer only emits built-in Helvetica text: no images, fonts, links, scripts or any
remote asset, so source text cannot cause a fetch. All text is escaped.
"""

import csv
import io
import re
from collections.abc import Iterable, Sequence
from typing import Any

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "|", "%")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formulas in text; numbers and booleans pass through unchanged."""
    if value is None:
        return ""
    if isinstance(value, bool | int | float):
        return value
    text = _CONTROL.sub("", str(value))
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def build_csv(
    preamble: Sequence[str], header: Sequence[str], rows: Iterable[Sequence[Any]]
) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    for line in preamble:
        w.writerow([csv_cell("Disclosure"), csv_cell(line)])
    w.writerow([])
    w.writerow([csv_cell(h) for h in header])
    for row in rows:
        w.writerow([csv_cell(c) for c in row])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def pdf_text(value: Any) -> str:
    """Latin-1 printable text; anything else becomes '?'. Escaping happens when drawing."""
    text = _CONTROL.sub("", str(value)).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for raw in text.split("\n") or [""]:
        line = pdf_text(raw)
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = cut if cut > 0 else width
            out.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        out.append(line)
    return out


class PdfDoc:
    """Tiny A4 text document: (style, text) lines with style in {title, h, p, mono}."""

    WIDTH, HEIGHT, MARGIN = 595, 842, 50
    STYLES = {
        "title": ("F2", 16, 22, 70),
        "h": ("F2", 12, 18, 85),
        "p": ("F1", 10, 13, 100),
        "mono": ("F1", 8, 11, 125),
    }

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add(self, style: str, text: str) -> None:
        for line in _wrap(text, self.STYLES[style][3]):
            self.items.append((style, line))

    def render(self) -> bytes:
        pages: list[list[str]] = [[]]
        y = self.HEIGHT - self.MARGIN
        for style, line in self.items:
            font, size, lead, _ = self.STYLES[style]
            if y - lead < self.MARGIN:
                pages.append([])
                y = self.HEIGHT - self.MARGIN
            y -= lead
            pages[-1].append(f"BT /{font} {size} Tf {self.MARGIN} {y} Td ({_escape(line)}) Tj ET")
        objs: list[bytes] = []
        n = len(pages)
        # 1 catalog, 2 pages, 3/4 fonts, then page/content pairs
        kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(n))
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
        objs.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        objs.append(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        for i, lines in enumerate(pages):
            stream = "\n".join(lines).encode("latin-1")
            objs.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {self.WIDTH} {self.HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {6 + 2 * i} 0 R >>".encode()
            )
            objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        )
        return bytes(out)

"""A tiny PDF writer for the demo and test statements: text at absolute positions, nothing else.

Real bank PDFs are produced by report engines; what matters for the reader is the same thing here:
a text layer where every cell is drawn at its column's x position. Writing it by hand keeps the
sample data deterministic and adds no dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

A4 = (595, 842)


def _escape(s: str) -> str:
    s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


@dataclass
class Page:
    ops: list[str] = field(default_factory=list)

    def text(self, x: float, y: float, s: str, size: float = 8, bold: bool = False, right: bool = False) -> None:
        """Draw `s` with its left edge at x (or its right edge, for right-aligned numbers). y is from the top."""
        if right:
            x -= approx_width(s, size, bold)
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size} Tf {x:.2f} {A4[1] - y:.2f} Td ({_escape(s)}) Tj ET")

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        self.ops.append(f"{width} w {x1:.2f} {A4[1] - y1:.2f} m {x2:.2f} {A4[1] - y2:.2f} l S")


# Helvetica advance widths (per 1000 em) for the characters statements use; others fall back to 556.
_W = {**{c: 556 for c in "0123456789"}, " ": 278, ",": 278, ".": 278, "-": 333, "/": 278, ":": 278,
      "(": 333, ")": 333, "@": 1015}


def approx_width(s: str, size: float, bold: bool = False) -> float:
    w = sum(_W.get(c, 667 if c.isupper() else 500) for c in s)
    return w * size / 1000 * (1.05 if bold else 1.0)


def build_pdf(pages: list[Page], title: str = "Statement") -> bytes:
    objs: list[bytes] = []

    def add(body: str | bytes) -> int:
        objs.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objs)

    catalog = add("")                      # placeholders, filled once page ids are known
    pages_id = add("")
    f1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for p in pages:
        stream = "\n".join(p.ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                        f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {content} 0 R >>"))
    objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                          f"/Count {len(kids)} >>").encode()
    info = add(f"<< /Title ({_escape(title)}) /Producer (ledger-agent demo data) >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)

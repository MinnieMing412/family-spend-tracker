"""Small deterministic PDF builders for sanitized parser fixtures."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def _pdf_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path: Path, pages: tuple[str, ...]) -> None:
    """Write a minimal text PDF whose lines can be extracted by pypdf."""
    object_values: list[bytes] = []
    page_refs = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    object_values.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    object_values.append(
        f"<< /Type /Pages /Kids [{page_refs}] /Count {len(pages)} >>".encode()
    )
    font_ref = 3 + len(pages) * 2
    for index, page_text in enumerate(pages):
        page_object = 3 + index * 2
        content_object = page_object + 1
        object_values.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_ref} 0 R >> >> "
                f"/Contents {content_object} 0 R >>"
            ).encode()
        )
        commands = ["BT", "/F1 10 Tf", "50 750 Td", "13 TL"]
        for line in page_text.splitlines():
            commands.extend((f"({_pdf_string(line)}) Tj", "T*"))
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        object_values.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )
    object_values.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, value in enumerate(object_values, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(object_values) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(object_values) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(output)


def encrypt_pdf(source: Path, destination: Path, password: str = "fixture") -> None:
    """Encrypt a synthetic PDF for rejection-path coverage."""
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt(password)
    with destination.open("wb") as output:
        writer.write(output)

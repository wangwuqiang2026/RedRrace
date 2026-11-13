"""重建 `tests/fixtures/` 下的二进制样张（PDF / DOCX）。

为什么需要它：fixture 必须是**真实可解析**的文件，而不是假字节；而 PDF/DOCX 属于二进制，
手改不可行，所以把生成过程留在仓库里，`python tests/fixtures/build_fixtures.py` 即可重建。
HTML 与 TXT 是纯文本，直接放在同目录下可读可 diff，不经本脚本。

内容口径：只放中性说明文字与断言所需的标记串（如 `1925`），**不放任何语料正文**——
真实史料的版权与体量都不适合进版本库。
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT /F1 12 Tf 72 760 Td 16 TL"]
    for i, line in enumerate(lines):
        if i:
            parts.append("T*")
        parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return ("\n".join(parts) + "\n").encode("latin-1", "replace")


def build_pdf(path: Path, pages: list[list[str]]) -> Path:
    """写出结构合法的最小 PDF 1.4：标准字体 Helvetica，不嵌入字体。"""
    page_ids = [3 + 2 * i for i in range(len(pages))]
    content_ids = [4 + 2 * i for i in range(len(pages))]
    font_id = 100

    objects: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (
            2,
            f"<< /Type /Pages /Kids [{' '.join(f'{n} 0 R' for n in page_ids)}] "
            f"/Count {len(pages)} >>".encode("latin-1"),
        ),
    ]
    for idx, (page_id, content_id) in enumerate(zip(page_ids, content_ids)):
        objects.append(
            (
                page_id,
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode(
                    "latin-1"
                ),
            )
        )
        stream = _content_stream(pages[idx])
        objects.append(
            (content_id, f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        )
    objects.append(
        (font_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num, body in objects:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    max_num = max(offsets)
    xref_pos = len(out)
    out += f"xref\n0 {max_num + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        if num in offsets:
            out += f"{offsets[num]:010d} 00000 n \n".encode("latin-1")
        else:
            out += b"0000000000 65535 f \n"
    out += (
        f"trailer\n<< /Size {max_num + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    )
    path.write_bytes(bytes(out))
    return path


def build_docx(path: Path, paragraphs: list[str]) -> Path:
    """用 python-docx 造一份真实 Office Open XML 文档（主依赖内，非 extras）。"""
    from docx import Document

    doc = Document()
    doc.add_heading("示例文档标题", level=1)
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(path))
    return path


def build_all() -> list[Path]:
    made = [
        build_pdf(
            FIXTURES / "校史片段.pdf",
            [
                ["School history fragment, page one.", "The institute was founded in the 1920s."],
                ["Liberation year 1925 noted in this fragment."],
            ],
        ),
        build_docx(
            FIXTURES / "示例文档.docx",
            ["第一段正文，记述讲习所的创设经过。", "第二段正文，一九四九年四月解放。"],
        ),
    ]
    return made


if __name__ == "__main__":
    for p in build_all():
        print(f"已生成 {p.name}（{p.stat().st_size} 字节）")

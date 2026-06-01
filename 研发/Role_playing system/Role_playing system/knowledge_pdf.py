# -*- coding: utf-8 -*-
"""中文注释：说明当前模块、类或函数的用途。"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from data_processor import DataProcessor


ROLE_LABELS = {
    "lawyer": "法律助手",
    "stock_analyst": "财报分析助手",
    "teacher": "学习辅导助手",
    "psychological_counselor": "心理支持助手",
    "doctor": "健康科普助手",
    "scientist": "科研方法助手",
}


class KnowledgePdfExporter:
    """中文注释：说明当前模块、类或函数的用途。"""

    def __init__(self, output_path: str = "./generated/knowledge_base/roleplay_knowledge_base.pdf"):
        """中文注释：说明当前模块、类或函数的用途。"""
        self.output_path = Path(output_path).resolve()

    def export(self, documents: Sequence[Dict]) -> Path:
        """中文注释：说明当前模块、类或函数的用途。"""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        pages = self._build_pages(documents)
        pdf_bytes = self._render_pdf(pages)
        self.output_path.write_bytes(pdf_bytes)
        return self.output_path

    def _build_pages(self, documents: Sequence[Dict]) -> List[List[str]]:
        """中文注释：说明当前模块、类或函数的用途。"""
        lines: List[str] = [
            "角色扮演系统知识库",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"文档数量：{len(documents)}",
            "",
        ]

        current_role = ""
        for doc in documents:
            role_type = doc.get("role_type", "")
            if role_type != current_role:
                current_role = role_type
                lines.extend(["", ROLE_LABELS.get(role_type, role_type or "未分类"), ""])

            title = str(doc.get("title") or "").strip()
            source = str(doc.get("source") or "").strip()
            content = str(doc.get("content") or "").strip()
            if title:
                lines.extend(self._wrap(f"标题：{title}", 34))
            if source:
                lines.extend(self._wrap(f"来源：{source}", 42))
            if content:
                for paragraph in content.splitlines():
                    lines.extend(self._wrap(paragraph, 42))
            lines.append("")

        pages: List[List[str]] = []
        page: List[str] = []
        max_lines_per_page = 34
        # 中文注释：这里说明关键处理逻辑。
        for line in lines:
            if len(page) >= max_lines_per_page:
                pages.append(page)
                page = []
            page.append(line)
        if page:
            pages.append(page)
        return pages or [["角色扮演系统知识库", "暂无可导出的知识内容"]]

    def _wrap(self, text: str, limit: int) -> List[str]:
        """中文注释：说明当前模块、类或函数的用途。"""
        text = " ".join(str(text or "").split())
        if not text:
            return [""]

        lines: List[str] = []
        current = ""
        width = 0.0
        for char in text:
            char_width = 0.55 if ord(char) < 128 else 1.0
            if current and width + char_width > limit:
                lines.append(current)
                current = char
                width = char_width
            else:
                current += char
                width += char_width
        if current:
            lines.append(current)
        return lines

    def _render_pdf(self, pages: Sequence[Sequence[str]]) -> bytes:
        """中文注释：说明当前模块、类或函数的用途。"""
        objects: List[bytes] = []

        def add_object(payload: bytes) -> int:
            """中文注释：说明当前模块、类或函数的用途。"""
            objects.append(payload)
            return len(objects)

        catalog_id = add_object(b"")
        pages_id = add_object(b"")
        font_id = add_object(b"")
        cid_font_id = add_object(b"")
        to_unicode_id = add_object(self._to_unicode_cmap())

        font_payload = (
            f"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
            f"/Encoding /UniGB-UCS2-H /DescendantFonts [{cid_font_id} 0 R] "
            f"/ToUnicode {to_unicode_id} 0 R >>"
        ).encode("ascii")
        objects[font_id - 1] = font_payload

        objects[cid_font_id - 1] = (
            b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> "
            b"/DW 1000 >>"
        )

        page_ids: List[int] = []
        for page_number, page_lines in enumerate(pages, start=1):
            # 中文注释：这里说明关键处理逻辑。
            content_id = add_object(self._page_stream(page_lines, page_number, len(pages)))
            page_id = add_object(
                (
                    f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /ProcSet [/PDF /Text] /Font << /F1 {font_id} 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                ).encode("ascii")
            )
            page_ids.append(page_id)

        objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for object_id, payload in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{object_id} 0 obj\n".encode("ascii"))
            output.extend(payload)
            output.extend(b"\nendobj\n")

        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(output)

    def _page_stream(self, lines: Sequence[str], page_number: int, total_pages: int) -> bytes:
        """中文注释：说明当前模块、类或函数的用途。"""
        commands = ["BT", "/F1 12 Tf", "1 0 0 1 54 788 Tm", "16 TL"]
        for index, line in enumerate(lines):
            if index:
                commands.append("T*")
            commands.append(f"<{self._pdf_text_hex(line)}> Tj")
        commands.extend(["/F1 9 Tf", "1 0 0 1 500 38 Tm", f"<{self._pdf_text_hex(f'{page_number}/{total_pages}')}> Tj", "ET"])
        stream = "\n".join(commands).encode("ascii")
        return b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"

    def _pdf_text_hex(self, text: str) -> str:
        """中文注释：说明当前模块、类或函数的用途。"""
        return str(text or "").encode("utf-16-be").hex().upper()

    def _to_unicode_cmap(self) -> bytes:
        """中文注释：说明当前模块、类或函数的用途。"""
        cmap = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0000> <FFFF> <0000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""
        return b"<< /Length " + str(len(cmap)).encode("ascii") + b" >>\nstream\n" + cmap + b"endstream"


def build_pdf_knowledge_documents(documents: Iterable[Dict], pdf_path: Path) -> List[Dict]:
    """中文注释：说明当前模块、类或函数的用途。"""
    processor = DataProcessor()
    pdf_source = f"pdf://{pdf_path.as_posix()}"
    pdf_documents: List[Dict] = []

    for doc in documents:
        processed = processor.process_document(doc)
        source = processed.get("source") or "未知来源"
        pdf_documents.append(
            {
                **processed,
                "source": f"{pdf_source}；原始来源：{source}",
            }
        )
    return pdf_documents

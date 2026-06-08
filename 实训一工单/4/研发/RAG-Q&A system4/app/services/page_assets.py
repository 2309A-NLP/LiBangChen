from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderedPageImage:
    """用于多模态问答的 PDF 页面渲染结果。"""

    source_id: str
    page_number: int
    mime_type: str
    image_bytes: bytes
    label: str | None = None

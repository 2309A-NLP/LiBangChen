from __future__ import annotations

"""检索器基模块。

定义检索结果数据类 ``RetrievedChunk`` 和检索器抽象基类 ``BaseRetriever``。
所有检索器实现需继承 ``BaseRetriever`` 并实现 ``retrieve`` 方法。
"""

from dataclasses import dataclass, field

from app.services.document_ingestion import DocumentChunk


@dataclass
class RetrievedChunk:
    """检索到的文档片段，包含原始片段和相关度分数。"""
    chunk: DocumentChunk
    score: float
    metadata: dict[str, object] = field(default_factory=dict)


class BaseRetriever:
    """检索器抽象基类。

    ``prepare`` 用于提前构建索引，``retrieve`` 执行检索并返回排序结果，
    ``retrieve_more`` 用于获取更多候选结果（如混合检索的扩展阶段）。
    """
    def prepare(self, selected_only: bool = False) -> None:
        return None

    def retrieve(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError

    def retrieve_more(
        self,
        question: str,
        top_k: int,
        retrieval_hints: dict[str, object] | None = None,
    ) -> list[RetrievedChunk]:
        return self.retrieve(question=question, top_k=top_k, retrieval_hints=retrieval_hints)

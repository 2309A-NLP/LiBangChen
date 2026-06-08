from app.schemas.query import QueryUnderstandingResult
from app.services.document_ingestion import DocumentChunk
from app.services.retrieval_generation import RetrievalGenerationService
from app.services.retrievers.base import RetrievedChunk


class StubRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results

    def retrieve(self, question: str, top_k: int, retrieval_hints=None):
        return self.results[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        return None


class StubLLMClient:
    def generate_answer(self, **kwargs):
        raise AssertionError("local extraction should answer before remote generation")


def test_retrieval_generation_extracts_fundraising_use_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=171,
                        text=(
                            "本次发行募集资金扣除发行费用后，拟将 12,000.00 万元用于补充流动资金，"
                            "其余用于主营业务相关项目建设。"
                        ),
                    ),
                    score=0.92,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="武汉兴图新科电子股份有限公司计划使用本次发行募集资金的多少用于补充流动资金？",
        understanding=QueryUnderstandingResult(
            intent="fundraising_use",
            normalized_question="武汉兴图新科电子股份有限公司计划使用本次发行募集资金的多少用于补充流动资金？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位募集资金用途并回答补充流动资金金额。",
            retrieval_hints={
                "keywords": ["募集资金", "补充流动资金", "资金用途"],
                "prefer_sections": ["募集资金运用", "本次募集资金运用", "募集资金投资项目"],
            },
        ),
    )

    assert "12,000.00 万元" in response.answer

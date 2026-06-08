from app.schemas.query import QueryUnderstandingResult
from app.services.document_ingestion import DocumentChunk
from app.services.retrieval_generation import RetrievalGenerationService
from app.services.retrievers.base import RetrievedChunk


class StubRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.prepare_called = 0

    def retrieve(self, question: str, top_k: int, retrieval_hints=None):
        return self.results[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        self.prepare_called += 1


class StubLLMClient:
    def generate_answer(self, **kwargs):
        raise AssertionError("local extraction should answer before remote generation")


def test_retrieval_generation_prepare_forwards_to_retriever():
    retriever = StubRetriever([])
    service = RetrievalGenerationService(
        retriever=retriever,
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    service.prepare_retrieval()

    assert retriever.prepare_called == 1


def test_retrieval_generation_financial_citation_prefers_matched_table_row():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=129,
                        text=(
                            "other leading text "
                            "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10% "
                            "民用领域 1,021.81 5.16% 398.56 2.69% 1,409.12 17.90% "
                            "other trailing text"
                        ),
                    ),
                    score=0.95,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位报告期内军用领域收入并按年度给出金额。",
            retrieval_hints={"keywords": ["收入", "军用领域", "国防领域", "客户群体"]},
        ),
    )

    assert response.citations[0].page_number == 129
    assert response.citations[0].snippet.startswith(
        "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10%"
    )


def test_retrieval_generation_extracts_award_project_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=77,
                        text=(
                            "在“某情报、指挥、控制与通信网络一体化工程”中，"
                            "公司独立承担了视频指挥分系统的设计、开发、研制、部署工作，"
                            "该工程整体获得了国家科技进步一等奖。"
                        ),
                    ),
                    score=0.9,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="公司参与的哪个工程获得了国家科技进步一等奖？",
        understanding=QueryUnderstandingResult(
            intent="award_project",
            normalized_question="公司参与的哪个工程获得了国家科技进步一等奖？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位获奖工程名称。",
            retrieval_hints={"keywords": ["国家科技进步一等奖", "工程"]},
        ),
    )

    assert "某情报、指挥、控制与通信网络一体化工程" in response.answer
    assert response.debug is None


def test_retrieval_generation_extracts_technical_standard_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=21,
                        text="公司参与制定了全军第一个视频指挥系统技术标准（即《某视频技术规范1.0》）。",
                    ),
                    score=0.9,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="公司参与制定了哪个技术标准？",
        understanding=QueryUnderstandingResult(
            intent="technical_standard",
            normalized_question="公司参与制定了哪个技术标准？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位技术标准名称。",
            retrieval_hints={"keywords": ["技术标准", "参与制定"]},
        ),
    )

    assert "某视频技术规范1.0" in response.answer


def test_retrieval_generation_extracts_defense_revenue_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=129,
                        text=(
                            "2、按客户群体划分的销售情况。公司主要客户集中于国防、监狱、油田等领域，"
                            "其中以国防领域为主。报告期内，公司主营业务收入按客户列示如下："
                            "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10% "
                            "民用领域 1,021.81 5.16% 398.56 2.69% 1,409.12 17.90%。"
                        ),
                    ),
                    score=0.95,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位报告期内军用领域收入并按年度给出金额。",
            retrieval_hints={"keywords": ["收入", "军用领域", "国防领域", "客户群体"]},
        ),
    )

    assert "2016年 6,464.51 万元" in response.answer
    assert "2017年 14,414.16 万元" in response.answer
    assert "2018年 18,780.67 万元" in response.answer


def test_retrieval_generation_extracts_direct_and_indirect_military_sales_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=130,
                        text=(
                            "4、按销售模式划分的销售情况。报告期内，公司向各类型客户直销情况如下："
                            "直接军方 5,611.52 28.34% 6,277.49 42.38% 3,433.34 43.61% "
                            "间接军方 13,169.15 66.50% 8,136.66 54.93% 3,031.18 38.50% "
                            "民品客户 1,021.81 5.16% 398.57 2.69% 1,409.11 17.90%。"
                        ),
                    ),
                    score=0.95,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="报告期内直接军方收入分别是多少",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内直接军方收入分别是多少",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位直接军方收入并按年度给出金额。",
            retrieval_hints={"keywords": ["直接军方", "收入", "报告期"]},
        ),
    )

    assert "2016年 3,433.34 万元" in response.answer
    assert "2017年 6,277.49 万元" in response.answer
    assert "2018年 5,611.52 万元" in response.answer

from app.schemas.query import QueryUnderstandingResult
from app.core.config import Settings
from app.services.document_ingestion import DocumentChunk
from app.services.reranker import RerankerService, TFIDFReranker
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


class StubDocumentIngestionService:
    def all_chunks(self):
        return []

    def status(self):
        return {"selected_sources": []}


class StubLLMClient:
    def generate_answer(self, **kwargs):
        raise AssertionError("local extraction should answer before remote generation")


class StubAnswerLLMClient:
    def generate_answer(self, **kwargs):
        from app.services.llm.base import GeneratedAnswer

        return GeneratedAnswer(answer="这是一个测试回答。", metadata={"mode": "stub"})


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


def test_chart_fallback_runs_when_long_text_lacks_chart_evidence():
    class ChartDocumentIngestionService:
        def __init__(self) -> None:
            self.requested_pages = []

        def _can_use_doubao_vision(self) -> bool:
            return True

        def all_chunks(self):
            return [
                DocumentChunk(
                    chunk_id="page-308",
                    source_id="招股说明书2.pdf",
                    page_number=308,
                    text="力源信息拥有目录销售中心以及遍布全国的销售处。" * 20,
                )
            ]

        def parse_pages_with_vision(self, source_id, pages):
            self.requested_pages.append((source_id, pages))
            return {
                pages[0]: (
                    "## 组织结构图\n"
                    "销售部下设华北销售部、华东销售部、华南销售部。\n"
                    "华南销售部包含深圳销售处、广州销售处、厦门销售处。"
                )
            }, []

    ingestion = ChartDocumentIngestionService()
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="generic-sales",
                        source_id="招股说明书2.pdf",
                        page_number=308,
                        text="力源信息拥有目录销售中心以及遍布全国的销售处。" * 20,
                    ),
                    score=0.9,
                )
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        document_ingestion_service=ingestion,
    )

    response = service.answer(
        question="武汉力源信息技术股份有限公司组织结构图中，哪个销售部的销售处最多？有哪些销售处？",
        understanding=QueryUnderstandingResult(
            intent="chart_structure",
            normalized_question="武汉力源信息技术股份有限公司组织结构图中，哪个销售部的销售处最多？有哪些销售处？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位组织结构图并提取销售部和销售处关系。",
            retrieval_hints={"keywords": ["组织结构图", "销售部", "销售处"]},
        ),
        include_debug=True,
    )

    assert ingestion.requested_pages == [("招股说明书2.pdf", [308])]
    assert response.debug["chart_fallback_used"] is True
    assert response.citations[0].chunk_id == "chart-fallback-招股说明书2.pdf-p308"


def test_chart_fallback_prioritizes_question_focus_terms_and_neighbor_pages():
    class ChartDocumentIngestionService:
        def __init__(self) -> None:
            self.requested_pages = []

        def _can_use_doubao_vision(self) -> bool:
            return True

        def all_chunks(self):
            return [
                DocumentChunk(
                    chunk_id="page-38",
                    source_id="招股说明书2.pdf",
                    page_number=38,
                    text="武汉力源信息技术股份有限公司 公司组织结构图 董事会 总经理 财务部",
                ),
                DocumentChunk(
                    chunk_id="page-39",
                    source_id="招股说明书2.pdf",
                    page_number=39,
                    text=(
                        "武汉力源信息技术股份有限公司 销售部下设渠道销售部、"
                        "电话及网络销售部、大客户销售部和国际贸易部。"
                        "服务网络包含6个销售处和26家合作零售网点。"
                    ),
                ),
                DocumentChunk(
                    chunk_id="page-19",
                    source_id="招股说明书2.pdf",
                    page_number=19,
                    text="公司服务网络由设在武汉的电话及网络销售中心以及遍布全国的6个销售处组成。",
                ),
                DocumentChunk(
                    chunk_id="other-source-page-1",
                    source_id="招股说明书1.pdf",
                    page_number=1,
                    text="另一家公司组织结构图 销售部 销售处 公司治理",
                ),
            ]

        def parse_pages_with_vision(self, source_id, pages):
            self.requested_pages.append((source_id, pages))
            return {page: f"page {page}" for page in pages}, []

    ingestion = ChartDocumentIngestionService()
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="generic",
                        source_id="招股说明书2.pdf",
                        page_number=19,
                        text="公司服务网络由设在武汉的电话及网络销售中心以及遍布全国的6个销售处组成。" * 20,
                    ),
                    score=0.9,
                )
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        document_ingestion_service=ingestion,
    )

    service.answer(
        question="武汉力源信息技术股份有限公司组织结构图中，哪个销售部的销售处最多？有哪些销售处？",
        understanding=QueryUnderstandingResult(
            intent="chart_structure",
            normalized_question="武汉力源信息技术股份有限公司组织结构图中，哪个销售部的销售处最多？有哪些销售处？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位组织结构图并提取销售部和销售处关系。",
            retrieval_hints={
                "keywords": ["组织结构图", "销售部", "销售处"],
                "entities": ["武汉力源信息技术股份有限公司"],
            },
        ),
        include_debug=True,
    )

    assert ingestion.requested_pages == [("招股说明书2.pdf", [39, 38, 19])]


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


def test_retrieval_generation_extracts_four_period_defense_revenue_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=185,
                        text=(
                            "报告期内，公司主营业务收入按客户列示如下："
                            "类型 2019 年 1-6 月 2018 年度 2017 年度 2016 年度 "
                            "金额 占比 金额 占比 金额 占比 金额 占比 "
                            "国防领域 4,627.14 94.34% 18,780.67 94.84% "
                            "14,414.16 97.31% 6,464.51 82.10%"
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
        include_debug=True,
    )

    assert "2016年 6,464.51 万元" in response.answer
    assert "2017年 14,414.16 万元" in response.answer
    assert "2018年 18,780.67 万元" in response.answer
    assert "2019年1-6月 4,627.14 万元" in response.answer
    assert response.debug["llm_metadata"]["matched_chunk_id"] == "c1"


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


def test_retrieval_generation_extracts_legal_representative_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="wrong",
                        source_id="a.pdf",
                        page_number=16,
                        text="武汉兴图新科电子股份有限公司 法定代表人：程家明",
                    ),
                    score=0.99,
                ),
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="right",
                        source_id="b.pdf",
                        page_number=23,
                        text="发行人名称：武汉力源信息技术股份有限公司 法定代表人：赵马克",
                    ),
                    score=0.95,
                ),
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="武汉力源信息技术股份有限公司的法定代表人是谁？",
        understanding=QueryUnderstandingResult(
            intent="legal_representative",
            normalized_question="武汉力源信息技术股份有限公司的法定代表人是谁？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位发行人基本信息并提取法定代表人。",
            retrieval_hints={
                "keywords": ["法定代表人"],
                "entities": ["武汉力源信息技术股份有限公司"],
            },
        ),
        include_debug=True,
    )

    assert response.answer == "武汉力源信息技术股份有限公司的法定代表人是赵马克。"
    assert response.debug["llm_metadata"]["pattern"] == "legal_representative"
    assert response.debug["llm_metadata"]["matched_chunk_id"] == "right"
    assert response.citations[0].chunk_id == "right"


def test_retrieval_generation_extracts_legal_representative_from_table_spacing():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="xingtu-basic-info",
                        source_id="招股说明书1-无水印.pdf",
                        page_number=39,
                        text=(
                            "中文名称 武汉兴图新科电子股份有限公司 有限公司成立日期 2004 年6 月17 日 "
                            "注册资本 5,520.00 万元 法定代表人 程家明 注册地址 湖北省武汉市东湖新技术开发区"
                        ),
                    ),
                    score=0.99,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="这个公司的法定代表人是谁？",
        understanding=QueryUnderstandingResult(
            intent="legal_representative",
            normalized_question="武汉兴图新科电子股份有限公司的法定代表人是谁？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位发行人基本信息并提取法定代表人。",
            retrieval_hints={
                "keywords": ["法定代表人"],
                "entities": ["武汉兴图新科电子股份有限公司"],
            },
        ),
        include_debug=True,
    )

    assert response.answer == "武汉兴图新科电子股份有限公司的法定代表人是程家明。"
    assert response.debug["llm_metadata"]["pattern"] == "legal_representative"
    assert response.debug["llm_metadata"]["matched_chunk_id"] == "xingtu-basic-info"


def test_retrieval_generation_debug_includes_retriever_and_reranker_metadata():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=1,
                        text="公司主营业务是工业软件平台研发与销售。",
                    ),
                    score=0.1,
                ),
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c2",
                        source_id="a.pdf",
                        page_number=2,
                        text="公司注册地址位于武汉。",
                    ),
                    score=0.9,
                ),
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        reranker=RerankerService([TFIDFReranker()], top_n=2),
    )

    response = service.answer(
        question="公司主营业务是什么",
        understanding=QueryUnderstandingResult(
            intent="general",
            normalized_question="公司主营业务是什么",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位主营业务相关段落。",
            retrieval_hints={"keywords": ["主营业务"]},
        ),
        include_debug=True,
    )

    assert response.debug is not None
    assert response.debug["retriever_type"] == "StubRetriever"
    assert response.debug["reranker_strategies"] == ["tfidf"]


def test_retrieval_generation_can_switch_retriever_per_request():
    class AlternateRetriever(StubRetriever):
        pass

    primary = StubRetriever(
        [
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="primary",
                    source_id="a.pdf",
                    page_number=1,
                    text="主检索器结果",
                ),
                score=0.2,
            )
        ]
    )
    alternate = AlternateRetriever(
        [
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="alternate",
                    source_id="b.pdf",
                    page_number=2,
                    text="全文检索结果",
                ),
                score=0.9,
            )
        ]
    )

    service = RetrievalGenerationService(
        retriever=primary,
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        settings=Settings(retriever_type="hybrid"),
        document_ingestion_service=StubDocumentIngestionService(),
    )
    service._retriever_cache["fulltext"] = alternate

    response = service.answer(
        question="主营业务是什么",
        understanding=QueryUnderstandingResult(
            intent="general",
            normalized_question="主营业务是什么",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位主营业务相关段落。",
            retrieval_hints={"keywords": ["主营业务"]},
        ),
        include_debug=True,
        retrieval_mode="fulltext",
    )

    assert response.debug is not None
    assert response.debug["retriever_type"] == "AlternateRetriever"
    assert response.citations[0].chunk_id == "alternate"


def test_retrieval_generation_applies_score_threshold_before_rerank():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="low",
                        source_id="a.pdf",
                        page_number=1,
                        text="低分结果",
                    ),
                    score=0.2,
                ),
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="high",
                        source_id="a.pdf",
                        page_number=2,
                        text="高分结果",
                    ),
                    score=0.8,
                ),
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="测试",
        understanding=QueryUnderstandingResult(
            intent="general",
            normalized_question="测试",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="过滤低分结果。",
            retrieval_hints={},
        ),
        include_debug=True,
        score_threshold=0.5,
    )

    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == "high"
    assert response.debug["score_threshold"] == 0.5


def test_retrieval_generation_can_disable_reranker_per_request():
    class FailingReranker:
        strategy_names = ["tfidf"]

        def rerank(self, **kwargs):
            raise AssertionError("reranker should be skipped when disabled")

    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=1,
                        text="公司主营业务是工业软件平台研发与销售。",
                    ),
                    score=0.7,
                )
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        reranker=FailingReranker(),
    )

    response = service.answer(
        question="主营业务是什么",
        understanding=QueryUnderstandingResult(
            intent="general",
            normalized_question="主营业务是什么",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="测试禁用重排。",
            retrieval_hints={"keywords": ["主营业务"]},
        ),
        include_debug=True,
        reranker_enabled=False,
    )

    assert response.debug["reranker_enabled"] is False
    assert response.debug["reranker_strategies"] == []


def test_retrieval_generation_continues_when_reranker_fails():
    class FailingReranker:
        strategy_names = ["cross_encoder"]

        def rerank(self, **kwargs):
            raise ImportError("cannot import name '_maybe_view_chunk_cat' from 'torch._utils'")

    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=1,
                        text="公司主营业务是工业软件平台研发与销售。",
                    ),
                    score=0.7,
                )
            ]
        ),
        llm_client=StubAnswerLLMClient(),
        default_top_k=4,
        reranker=FailingReranker(),
    )

    response = service.answer(
        question="主营业务是什么",
        understanding=QueryUnderstandingResult(
            intent="general",
            normalized_question="主营业务是什么",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="测试重排失败降级。",
            retrieval_hints={"keywords": ["主营业务"]},
        ),
        include_debug=True,
    )

    assert response.answer
    assert response.citations[0].chunk_id == "c1"
    assert response.debug["reranker_enabled"] is True
    assert response.debug["reranker_strategies"] == ["cross_encoder"]
    assert "_maybe_view_chunk_cat" in response.debug["reranker_error"]


def test_retrieval_generation_extracts_annual_report_debt_investment_from_selected_source():
    source_id = "annual.pdf"
    debt_chunk = DocumentChunk(
        chunk_id="debt-table",
        source_id=source_id,
        page_number=229,
        text=(
            "14. 债权投资 2019 年12月31日 2018 年12月31日 "
            "债券 政府债 1,234,172 894,996 金融债 450,904 497,233 "
            "企业债 109,005 131,326 债权计划 120,494 151,873 "
            "理财产品投资 268,387 308,181 其他投资 114,982 104,847 "
            "总额 2,297,944 2,088,456 减 ： 减值准备 (16,719) (13,305)"
        ),
    )

    class SelectedDocumentIngestionService:
        def chunks(self):
            return [debt_chunk]

        def status(self):
            return {"selected_sources": [source_id]}

    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="less-useful",
                        source_id=source_id,
                        page_number=1,
                        text="年度报告摘要",
                    ),
                    score=0.5,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
        document_ingestion_service=SelectedDocumentIngestionService(),
    )

    response = service.answer(
        question="中国平安2019年年报中披露的债权投资总额是多少？主要包括哪些类型的债券？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="中国平安2019年年报中披露的债权投资总额是多少？主要包括哪些类型的债券？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位债权投资表。",
            retrieval_hints={"keywords": ["债权投资"]},
        ),
        include_debug=True,
    )

    assert "2,297,944百万元" in response.answer
    assert "政府债1,234,172百万元" in response.answer
    assert response.citations[0].chunk_id == "debt-table"

from app.schemas.query import QueryUnderstandingResult
from app.services.document_ingestion import DocumentChunk
from app.services.page_assets import RenderedPageImage
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


class CapturingLLMClient:
    def __init__(self) -> None:
        self.kwargs = None

    def generate_answer(self, **kwargs):
        self.kwargs = kwargs
        return type(
            "Result",
            (),
            {
                "answer": "视觉补充回答",
                "metadata": {
                    "mode": "openai_compatible_vision",
                    "used_page_image_count": len(kwargs.get("page_images") or []),
                },
            },
        )()


class StubDocumentIngestionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def render_page_image(self, source_id: str, page_number: int):
        self.calls.append((source_id, page_number))
        return RenderedPageImage(
            source_id=source_id,
            page_number=page_number,
            mime_type="image/jpeg",
            image_bytes=b"fake-image",
        )


class SelectableDocumentIngestionService(StubDocumentIngestionService):
    def __init__(self, selected_sources: list[str] | None = None) -> None:
        super().__init__()
        self._selected_sources = list(selected_sources or [])

    def status(self) -> dict[str, object]:
        return {"selected_sources": list(self._selected_sources)}

    def select_sources(self, source_files: list[str] | None) -> None:
        self._selected_sources = list(source_files or [])


class SelectionAwareRetriever:
    def __init__(
        self,
        document_ingestion_service: SelectableDocumentIngestionService,
        selected_results: list[RetrievedChunk],
        all_results: list[RetrievedChunk],
    ) -> None:
        self.document_ingestion_service = document_ingestion_service
        self.selected_results = selected_results
        self.all_results = all_results

    def retrieve(self, question: str, top_k: int, retrieval_hints=None):
        selected_sources = self.document_ingestion_service.status().get("selected_sources", [])
        results = self.selected_results if selected_sources else self.all_results
        return results[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        return None


def test_retrieval_generation_prepare_forwards_to_retriever():
    retriever = StubRetriever([])
    service = RetrievalGenerationService(
        retriever=retriever,
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    service.prepare_retrieval()

    assert retriever.prepare_called == 1


def test_retrieval_generation_collects_page_images_for_visual_followup():
    retriever = StubRetriever(
        [
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="c1",
                    source_id="a.pdf",
                    page_number=12,
                    text="图 3 报告期内主营业务收入趋势图",
                ),
                score=0.97,
            ),
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="c2",
                    source_id="a.pdf",
                    page_number=12,
                    text="图表说明：收入逐年增长。",
                ),
                score=0.9,
            ),
        ]
    )
    llm_client = CapturingLLMClient()
    ingestion_service = StubDocumentIngestionService()
    service = RetrievalGenerationService(
        retriever=retriever,
        llm_client=llm_client,
        default_top_k=4,
        document_ingestion_service=ingestion_service,
        vision_enabled=True,
        vision_max_pages=2,
    )

    response = service.answer(
        question="图表里主营业务收入趋势是什么？",
        understanding=QueryUnderstandingResult(
            intent="general_information",
            normalized_question="图表里主营业务收入趋势是什么？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="读取图表并回答趋势。",
            retrieval_hints={"keywords": ["图表", "收入趋势"]},
        ),
    )

    assert response.answer == "视觉补充回答"
    assert ingestion_service.calls == [("a.pdf", 12)]
    assert llm_client.kwargs is not None
    page_images = llm_client.kwargs["page_images"]
    assert len(page_images) == 1
    assert page_images[0].page_number == 12


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


def test_retrieval_generation_clarifies_vehicle_domain_as_civil_sales():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=129,
                        text=(
                            "2、按客户群体划分的销售情况。"
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
        question="报告期内，武汉兴图新科电子股份有限公司来自车用领域的收入分别是多少？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内，武汉兴图新科电子股份有限公司来自车用领域的收入分别是多少？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位报告期内车用领域收入并按年度给出金额。",
            retrieval_hints={"keywords": ["收入", "车用领域", "民用领域", "客户群体"]},
        ),
    )

    assert "未检索到“车用领域”这一披露口径" in response.answer
    assert "2016年 1,409.12 万元" in response.answer
    assert "2017年 398.56 万元" in response.answer
    assert "2018年 1,021.81 万元" in response.answer


def test_retrieval_generation_formats_four_period_customer_table_correctly():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=185,
                        text=(
                            "2、按客户群体划分的销售情况 "
                            "类型 2019 年 1-6 月 2018 年度 2017 年度 2016 年度 "
                            "金额 占比 金额 占比 金额 占比 金额 占比 "
                            "民用领域 277.57 5.66% 1,021.81 5.16% 398.56 2.69% 1,409.12 17.90% "
                            "合计 4,904.71 100.00%"
                        ),
                    ),
                    score=0.96,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="报告期内，武汉兴图新科电子股份有限公司来自车用领域的收入分别是多少？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内，武汉兴图新科电子股份有限公司来自车用领域的收入分别是多少？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位报告期内车用领域收入并按年度给出金额。",
            retrieval_hints={"keywords": ["收入", "车用领域", "民用领域", "客户群体"]},
        ),
    )

    assert "2016年 1,409.12 万元" in response.answer
    assert "2017年 398.56 万元" in response.answer
    assert "2018年 1,021.81 万元" in response.answer
    assert "2019年1-6月 277.57 万元" in response.answer


def test_retrieval_generation_extracts_fundraising_use_for_working_capital():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=479,
                        text=(
                            "本次发行募集资金运用计划 "
                            "序号 项目名称 总投资 拟投入募集资金 建设期 "
                            "1 基于云联邦架构的军用视频指挥平台升级及产业化项目 20,658.33 20,658.33 24个月 "
                            "2 研发中心建设项目 4,926.50 4,926.50 24个月 "
                            "3 补充流动资金 15,000.00 15,000.00 - "
                            "合计 40,584.83 40,584.83 -"
                        ),
                    ),
                    score=0.98,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="武汉兴图新科电子股份有限公司计划使用本次发行募集资金的多少用于补充流动资金？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="武汉兴图新科电子股份有限公司计划使用本次发行募集资金的多少用于补充流动资金？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位募集资金用途表并提取补充流动资金金额。",
            retrieval_hints={"keywords": ["募集资金", "补充流动资金", "募投项目"]},
        ),
    )

    assert response.answer == "公司计划使用本次发行募集资金 15,000.00 万元用于补充流动资金。"
    assert response.citations[0].page_number == 479


def test_retrieval_generation_retries_across_all_sources_when_selected_pdf_mismatches_entity():
    ingestion_service = SelectableDocumentIngestionService(selected_sources=["招股说明书2.pdf"])
    retriever = SelectionAwareRetriever(
        document_ingestion_service=ingestion_service,
        selected_results=[
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="wrong-1",
                    source_id="招股说明书2.pdf",
                    page_number=34,
                    text="武汉力源信息技术股份有限公司 招股意向书 发行人基本情况",
                ),
                score=0.8,
            )
        ],
        all_results=[
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="right-1",
                    source_id="招股说明书1.pdf",
                    page_number=129,
                    text=(
                        "武汉兴图新科电子股份有限公司 招股意向书 "
                        "2、按客户群体划分的销售情况 "
                        "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10%"
                    ),
                ),
                score=0.96,
            )
        ],
    )
    service = RetrievalGenerationService(
        retriever=retriever,
        llm_client=StubLLMClient(),
        default_top_k=4,
        document_ingestion_service=ingestion_service,
    )

    response = service.answer(
        question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少？",
        understanding=QueryUnderstandingResult(
            intent="financial_metric",
            normalized_question="报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位报告期内军用领域收入并按年度给出金额。",
            retrieval_hints={
                "keywords": ["收入", "军用领域", "国防领域", "客户群体"],
                "entities": ["武汉兴图新科电子股份有限公司"],
            },
        ),
    )

    assert "2016年 6,464.51 万元" in response.answer
    assert response.citations[0].source_id == "招股说明书1.pdf"
    assert ingestion_service.status()["selected_sources"] == ["招股说明书2.pdf"]


def test_retrieval_generation_extracts_market_chart_fact_locally():
    service = RetrievalGenerationService(
        retriever=StubRetriever(
            [
                RetrievedChunk(
                    chunk=DocumentChunk(
                        chunk_id="c1",
                        source_id="a.pdf",
                        page_number=72,
                        text=(
                            "2008 年中国 IC 市场应用结构与增长(亿元) "
                            "工业控制领域所占的比例虽然仅为 7%，但其增长率达 10.5%，"
                            "在所有应用行业中位列第二，仅次于汽车电子。"
                        ),
                    ),
                    score=0.96,
                )
            ]
        ),
        llm_client=StubLLMClient(),
        default_top_k=4,
    )

    response = service.answer(
        question="从2008年中国 IC 市场应用结构与增长图中可以看出，增长率最快的是哪个行业？负增长的是哪个行业？",
        understanding=QueryUnderstandingResult(
            intent="market_chart",
            normalized_question="从2008年中国 IC 市场应用结构与增长图中可以看出，增长率最快的是哪个行业？负增长的是哪个行业？",
            strategy="rules",
            sub_questions=[],
            abstracted_goal="定位市场应用结构图、增长率图或消费结构图，并识别最高增长、负增长及对应行业。",
            retrieval_hints={"keywords": ["应用结构", "增长图", "负增长"]},
        ),
    )

    assert "汽车电子行业（14.0%）" in response.answer
    assert "IC 卡行业（-2.0%）" in response.answer

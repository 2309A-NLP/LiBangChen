from app.core.config import Settings
from app.services.document_ingestion import DocumentChunk
from app.services.retrievers.fulltext import FullTextRetriever
from app.services.retrievers.base import RetrievedChunk
from app.services.retrievers.factory import build_retriever
from app.services.retrievers.hybrid_rrf import HybridRRFRetriever
from app.services.retrievers.keyword import KeywordRetriever
from app.services.retrievers.milvus import MilvusRetriever


class StubDocumentIngestionService:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks

    def chunks(self) -> list[DocumentChunk]:
        return list(self._chunks)

    def all_chunks(self) -> list[DocumentChunk]:
        return list(self._chunks)

    def status(self) -> dict[str, object]:
        return {
            "selected_sources": sorted({chunk.source_id for chunk in self._chunks}),
        }


class StubRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.prepare_called = 0

    def retrieve(self, question: str, top_k: int, retrieval_hints=None):
        return self.results[:top_k]

    def retrieve_more(self, question: str, top_k: int, retrieval_hints=None):
        return self.results[:top_k]

    def prepare(self, selected_only: bool = False) -> None:
        self.prepare_called += 1


def test_keyword_retriever_reuses_index_and_refreshes_when_chunk_count_changes():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="c1",
                source_id="a.pdf",
                page_number=1,
                text="公司的主营业务是软件服务。",
            )
        ]
    )
    retriever = KeywordRetriever(ingestion)

    first_results = retriever.retrieve("公司的主营业务是软件服务", top_k=3)
    assert len(first_results) >= 1

    indexed_chunks_before = retriever._indexed_chunks
    second_results = retriever.retrieve("公司的主营业务是软件服务", top_k=3)
    assert len(second_results) >= 1
    assert retriever._indexed_chunks is indexed_chunks_before

    ingestion._chunks.append(
        DocumentChunk(
            chunk_id="c2",
            source_id="b.pdf",
            page_number=1,
            text="公司的主营业务是平台软件产品。",
        )
    )
    refreshed_results = retriever.retrieve("公司的主营业务是平台软件产品", top_k=3)

    assert retriever._indexed_chunks is not indexed_chunks_before
    assert len(refreshed_results) >= 1


def test_keyword_retriever_prefers_focus_terms_over_company_name_matches():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="c1",
                source_id="a.pdf",
                page_number=21,
                text="公司参与制定了全军第一个视频指挥系统技术标准，即《某视频技术规范1.0》。",
            ),
            DocumentChunk(
                chunk_id="c2",
                source_id="a.pdf",
                page_number=37,
                text="武汉兴图新科电子股份有限公司成立于2011年，注册地址位于武汉。",
            ),
        ]
    )
    retriever = KeywordRetriever(ingestion)

    results = retriever.retrieve(
        question="武汉兴图新科电子股份有限公司参与制定了哪个技术标准",
        top_k=2,
        retrieval_hints={
            "keywords": ["技术标准", "参与制定"],
            "entities": ["武汉兴图新科电子股份有限公司"],
            "prefer_sections": ["技术先进性"],
        },
    )

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c1"


def test_hybrid_rrf_fuses_keyword_and_vector_results():
    chunk_a = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="a", source_id="a.pdf", page_number=1, text="A"),
        score=1.0,
    )
    chunk_b = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="b", source_id="a.pdf", page_number=2, text="B"),
        score=1.0,
    )
    chunk_c = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="c", source_id="a.pdf", page_number=3, text="C"),
        score=1.0,
    )

    retriever = HybridRRFRetriever(
        settings=Settings(retriever_type="hybrid_rrf", rrf_k=60),
        keyword_retriever=StubRetriever([chunk_a, chunk_b]),
        vector_retriever=StubRetriever([chunk_b, chunk_c]),
    )

    results = retriever.retrieve("测试问题", top_k=3)

    assert [item.chunk.chunk_id for item in results] == ["b", "a", "c"]


def test_fulltext_retriever_supports_phrase_and_multi_field_matching():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="c1",
                source_id="技术白皮书.pdf",
                page_number=1,
                text="主营业务概述\n公司主要从事工业软件和智能分析平台研发。",
            ),
            DocumentChunk(
                chunk_id="c2",
                source_id="招股说明书.pdf",
                page_number=5,
                text="风险提示\n主营业务包括智能检测设备销售与运维服务。",
            ),
        ]
    )
    retriever = FullTextRetriever(Settings(retriever_type="fulltext"), ingestion)

    results = retriever.retrieve('"工业软件" OR 主营业务', top_k=2)

    assert [item.chunk.chunk_id for item in results] == ["c1", "c2"]
    assert results[0].metadata["retriever"] == "fulltext"


def test_fulltext_retriever_boosts_legal_representative_basic_info():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="resume-page",
                source_id="招股说明书1.pdf",
                page_number=72,
                text=(
                    "武汉兴图新科电子股份有限公司 招股意向书 "
                    "某董事曾担任河南万顺包装材料有限公司法定代表人、董事。"
                ),
            ),
            DocumentChunk(
                chunk_id="basic-info",
                source_id="招股说明书1-无水印.pdf",
                page_number=37,
                text=(
                    "第五节 发行人基本情况 一、发行人的基本情况 "
                    "公司名称：武汉兴图新科电子股份有限公司 "
                    "法定代表人：程家明 注册资本：5,520 万元 注册地址：湖北省武汉东湖新技术开发区"
                ),
            ),
        ]
    )
    retriever = FullTextRetriever(Settings(retriever_type="fulltext"), ingestion)

    results = retriever.retrieve(
        "武汉兴图新科电子股份有限公司的法定代表人是谁？",
        top_k=2,
        retrieval_hints={
            "intent": "legal_representative",
            "keywords": ["法定代表人", "法定代表"],
            "prefer_sections": ["发行人基本情况", "发行概况"],
            "entities": ["武汉兴图新科电子股份有限公司"],
        },
    )

    assert [item.chunk.chunk_id for item in results] == ["basic-info", "resume-page"]
    assert results[0].metadata["field_scores"]["hints"] > 0


def test_fulltext_retriever_boosts_award_project_evidence():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="generic-c4isr",
                source_id="招股说明书1.pdf",
                page_number=13,
                text="C4ISR 系统是美国军事指挥当局使用的信息系统。",
            ),
            DocumentChunk(
                chunk_id="award-evidence",
                source_id="招股说明书1.pdf",
                page_number=117,
                text=(
                    "公司目前已经成为军队视频指挥领域的重要供应商。"
                    "在我国某大型研究所牵头承担的“某情报、指挥、控制与通信网络一体化工程”"
                    "（即相当于美军的 C4ISR 系统）中，公司独立承担了视频指挥分系统的设计、"
                    "开发、研制、部署工作，该工程整体获得了国家科技进步一等奖。"
                ),
            ),
        ]
    )
    retriever = FullTextRetriever(Settings(retriever_type="fulltext"), ingestion)

    results = retriever.retrieve(
        "他参与的哪个工程荣获了国家科技进步一等奖？",
        top_k=2,
        retrieval_hints={
            "intent": "award_project",
            "keywords": ["国家科技进步一等奖", "工程", "C4ISR 系统"],
            "prefer_sections": ["技术先进性", "科研实力和成果"],
        },
    )

    assert results[0].chunk.chunk_id == "award-evidence"
    assert results[0].metadata["field_scores"]["hints"] > 0


def test_fulltext_retriever_boosts_defense_revenue_table():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="product-revenue",
                source_id="招股说明书1.pdf",
                page_number=182,
                text=(
                    "主营业务收入按产品列示如下：视频指挥控制类 18,687.75 "
                    "视频预警控制类 92.92 合计 19,802.48"
                ),
            ),
            DocumentChunk(
                chunk_id="defense-revenue",
                source_id="招股说明书1.pdf",
                page_number=129,
                text=(
                    "2、按客户群体划分的销售情况。报告期内，公司主营业务收入按客户列示如下："
                    "类型 2019 年 1-6 月 2018 年度 2017 年度 2016 年度 "
                    "国防领域 4,627.14 94.34% 18,780.67 94.84% "
                    "14,414.16 97.31% 6,464.51 82.10%"
                ),
            ),
        ]
    )
    retriever = FullTextRetriever(Settings(retriever_type="fulltext"), ingestion)

    results = retriever.retrieve(
        "报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少？",
        top_k=2,
        retrieval_hints={
            "intent": "financial_metric",
            "keywords": ["收入", "报告期", "军用领域", "国防领域"],
            "prefer_sections": ["按客户群体划分的销售情况"],
            "entities": ["武汉兴图新科电子股份有限公司"],
        },
    )

    assert results[0].chunk.chunk_id == "defense-revenue"
    assert results[0].metadata["field_scores"]["hints"] > 0


def test_fulltext_retriever_supports_fuzzy_matching():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="c1",
                source_id="a.pdf",
                page_number=1,
                text="公司主营业务为视频指挥系统平台开发。",
            )
        ]
    )
    retriever = FullTextRetriever(
        Settings(retriever_type="fulltext", fulltext_fuzzy_max_distance=1),
        ingestion,
    )

    results = retriever.retrieve("主菅业务~", top_k=1)

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c1"


def test_hybrid_weighted_fusion_respects_weights():
    chunk_a = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="a", source_id="a.pdf", page_number=1, text="A"),
        score=1.0,
    )
    chunk_b = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="b", source_id="a.pdf", page_number=2, text="B"),
        score=0.2,
    )
    chunk_c = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="c", source_id="a.pdf", page_number=3, text="C"),
        score=1.0,
    )

    retriever = HybridRRFRetriever(
        settings=Settings(
            retriever_type="hybrid",
            hybrid_fusion_strategy="weighted",
            hybrid_fulltext_weight=0.8,
            hybrid_vector_weight=0.2,
        ),
        text_retriever=StubRetriever([chunk_a, chunk_b]),
        vector_retriever=StubRetriever([chunk_c, chunk_b]),
    )

    results = retriever.retrieve("测试问题", top_k=3)

    assert [item.chunk.chunk_id for item in results] == ["a", "b", "c"]
    assert results[0].metadata["fusion_strategy"] == "weighted"


def test_hybrid_vote_prefers_agreement():
    chunk_a = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="a", source_id="a.pdf", page_number=1, text="A"),
        score=1.0,
    )
    chunk_b = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="b", source_id="a.pdf", page_number=2, text="B"),
        score=0.8,
    )
    chunk_c = RetrievedChunk(
        chunk=DocumentChunk(chunk_id="c", source_id="a.pdf", page_number=3, text="C"),
        score=1.0,
    )

    retriever = HybridRRFRetriever(
        settings=Settings(
            retriever_type="hybrid",
            hybrid_fusion_strategy="vote",
            hybrid_vote_min_agreement=2,
        ),
        text_retriever=StubRetriever([chunk_a, chunk_b]),
        vector_retriever=StubRetriever([chunk_b, chunk_c]),
    )

    results = retriever.retrieve("测试问题", top_k=3)

    assert [item.chunk.chunk_id for item in results] == ["b"]
    assert results[0].metadata["votes"] == 2


def test_retriever_factory_returns_keyword_retriever_by_default():
    ingestion = StubDocumentIngestionService([])
    retriever = build_retriever(Settings(retriever_type="keyword"), ingestion)
    assert isinstance(retriever, KeywordRetriever)


def test_retriever_factory_returns_fulltext_retriever():
    ingestion = StubDocumentIngestionService([])
    retriever = build_retriever(Settings(retriever_type="fulltext"), ingestion)
    assert isinstance(retriever, FullTextRetriever)


def test_hybrid_rrf_prepare_warms_both_retrievers():
    keyword = StubRetriever([])
    vector = StubRetriever([])
    retriever = HybridRRFRetriever(
        settings=Settings(retriever_type="hybrid_rrf", rrf_k=60),
        keyword_retriever=keyword,
        vector_retriever=vector,
    )

    retriever.prepare()

    assert keyword.prepare_called == 1
    assert vector.prepare_called == 1


def test_milvus_prepare_uses_selected_chunks_only():
    class StubEmbeddingService:
        def embed_query(self, _: str):
            return [0.1, 0.2]

        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class StubSelectedDocumentIngestionService:
        def __init__(self) -> None:
            self._all_chunks = [
                DocumentChunk(chunk_id="a1", source_id="a.pdf", page_number=1, text="A"),
                DocumentChunk(chunk_id="b1", source_id="b.pdf", page_number=1, text="B"),
            ]
            self._selected_chunks = [self._all_chunks[0]]

        def all_chunks(self) -> list[DocumentChunk]:
            return list(self._all_chunks)

        def chunks(self) -> list[DocumentChunk]:
            return list(self._selected_chunks)

        def status(self) -> dict[str, object]:
            return {"selected_sources": ["a.pdf"]}

    retriever = MilvusRetriever(
        Settings(retriever_type="milvus"),
        StubSelectedDocumentIngestionService(),
        StubEmbeddingService(),
    )

    captured: list[list[DocumentChunk]] = []
    retriever._ensure_index = lambda chunks: captured.append(list(chunks))  # type: ignore[method-assign]

    retriever.prepare(selected_only=True)

    assert len(captured) == 1
    assert [chunk.source_id for chunk in captured[0]] == ["a.pdf"]


def test_milvus_retriever_get_collection_uses_milvus_client_management_api():
    class StubEmbeddingService:
        def embed_query(self, _: str):
            return [0.1, 0.2]

        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class StubClient:
        def __init__(self):
            self.loaded = []
            self.indexes_created = []

        def has_collection(self, collection_name: str):
            assert collection_name == "rag_qna_chunks"
            return True

        def list_indexes(self, collection_name: str):
            assert collection_name == "rag_qna_chunks"
            return []

        def load_collection(self, collection_name: str):
            self.loaded.append(collection_name)

        def create_index(self, collection_name: str, index_params):
            self.indexes_created.append((collection_name, index_params))

    settings = Settings(retriever_type="milvus")
    retriever = MilvusRetriever(settings, StubDocumentIngestionService([]), StubEmbeddingService())
    stub_client = StubClient()

    retriever._client = stub_client

    collection_name = retriever._get_collection()

    assert collection_name == settings.milvus_collection_name
    assert retriever._collection == settings.milvus_collection_name
    assert stub_client.loaded == [settings.milvus_collection_name]
    assert len(stub_client.indexes_created) == 1


def test_milvus_retriever_rebuilds_collection_on_stale_local_path_error():
    class StubEmbeddingService:
        def embed_query(self, _: str):
            return [0.1, 0.2]

        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class FakeMilvusException(Exception):
        pass

    class StubClient:
        def __init__(self):
            self.deleted = []
            self.flushed = []
            self.loaded = []
            self.inserted = []
            self.fail_first_insert = True

        def has_collection(self, collection_name: str):
            return True

        def list_indexes(self, collection_name: str):
            return ["embedding"]

        def load_collection(self, collection_name: str):
            self.loaded.append(collection_name)

        def get_collection_stats(self, collection_name: str):
            return {"row_count": 1}

        def delete(self, collection_name: str, filter: str):
            self.deleted.append((collection_name, filter))

        def flush(self, collection_name: str):
            self.flushed.append(collection_name)

        def insert(self, collection_name: str, data):
            if self.fail_first_insert:
                self.fail_first_insert = False
                raise FakeMilvusException("invalid local path: /var/lib/milvus/data/insert_log/...")
            self.inserted.append((collection_name, data))

        def drop_collection(self, collection_name: str):
            self.deleted.append(("drop", collection_name))

        def create_collection(self, collection_name: str, schema):
            self.inserted.append(("create", collection_name, schema))

        def create_index(self, collection_name: str, index_params):
            self.inserted.append(("index", collection_name, index_params))

    settings = Settings(retriever_type="milvus")
    chunks = [DocumentChunk(chunk_id="c1", source_id="a.pdf", page_number=1, text="测试文本")]
    retriever = MilvusRetriever(settings, StubDocumentIngestionService(chunks), StubEmbeddingService())
    stub_client = StubClient()
    retriever._client = stub_client
    retriever._collection = settings.milvus_collection_name
    retriever._indexed_signature = None

    created = {"count": 0}

    def fake_rebuild_collection():
        created["count"] += 1
        return settings.milvus_collection_name

    retriever._rebuild_collection = fake_rebuild_collection  # type: ignore[method-assign]

    retriever._ensure_index(chunks)

    assert created["count"] == 1
    assert stub_client.flushed

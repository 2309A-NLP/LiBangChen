from app.core.config import Settings
from app.services.document_ingestion import DocumentChunk
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


def test_keyword_retriever_prefers_exact_company_match_across_multiple_documents():
    ingestion = StubDocumentIngestionService(
        [
            DocumentChunk(
                chunk_id="c1",
                source_id="xingtu.pdf",
                page_number=16,
                text=(
                    "武汉兴图新科电子股份有限公司 第二节概览 本次发行概况 "
                    "发行股数不低于1840万股 占发行后总股本比例不低于25.00%"
                ),
            ),
            DocumentChunk(
                chunk_id="c2",
                source_id="liyuan.pdf",
                page_number=24,
                text=(
                    "武汉力源信息技术股份有限公司 二、本次发行的基本情况 "
                    "发行股数及占发行后总股本比例 1670万股，占发行后总股本的比例为25.04%"
                ),
            ),
        ]
    )
    retriever = KeywordRetriever(ingestion)

    results = retriever.retrieve(
        question="武汉力源信息技术股份有限公司本次发行股数是多少，占发行后总股本的比例是多少？",
        top_k=2,
        retrieval_hints={
            "keywords": ["发行股数", "占发行后总股本比例", "本次发行"],
            "entities": ["武汉力源信息技术股份有限公司"],
            "prefer_sections": ["本次发行概况"],
        },
    )

    assert len(results) == 2
    assert results[0].chunk.chunk_id == "c2"


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


def test_retriever_factory_returns_keyword_retriever_by_default():
    ingestion = StubDocumentIngestionService([])
    retriever = build_retriever(Settings(retriever_type="keyword"), ingestion)
    assert isinstance(retriever, KeywordRetriever)


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


def test_milvus_retriever_rebuilds_collection_on_stale_local_path_error():
    class StubEmbeddingService:
        def embed_query(self, _: str):
            return [0.1, 0.2]

        def embed_documents(self, texts):
            return [[0.1, 0.2] for _ in texts]

    class StubCollection:
        def __init__(self):
            self.indexes = []
            self.loaded = False
            self.num_entities = 0

        def create_index(self, field_name, index_params):
            self.indexes.append((field_name, index_params))

        def load(self):
            self.loaded = True

    settings = Settings(retriever_type="milvus")
    retriever = MilvusRetriever(settings, StubDocumentIngestionService([]), StubEmbeddingService())
    collection = StubCollection()

    calls = {"drop": 0, "create": 0}

    def fake_create_collection(name: str):
        assert name == settings.milvus_collection_name
        calls["create"] += 1
        return collection

    retriever._create_collection = fake_create_collection  # type: ignore[method-assign]

    from types import SimpleNamespace
    from unittest.mock import patch

    failing_collection = SimpleNamespace(indexes=[], create_index=lambda **kwargs: None)

    def collection_factory(name: str):
        assert name == settings.milvus_collection_name
        return failing_collection

    class FakeMilvusException(Exception):
        pass

    def load_failure():
        raise FakeMilvusException("invalid local path: /var/lib/milvus/data/insert_log/...")

    failing_collection.load = load_failure

    with patch("pymilvus.connections.connect"), patch(
        "pymilvus.utility.has_collection", return_value=True
    ), patch("pymilvus.utility.drop_collection") as drop_collection, patch(
        "pymilvus.Collection", side_effect=collection_factory
    ):
        retriever._rebuild_collection = lambda: fake_create_collection(settings.milvus_collection_name)  # type: ignore[method-assign]
        retriever._collection = failing_collection
        retriever._indexed_signature = None
        chunks = [
            DocumentChunk(chunk_id="c1", source_id="a.pdf", page_number=1, text="测试文本")
        ]
        retriever.document_ingestion_service = StubDocumentIngestionService(chunks)
        result = retriever._get_collection()

    assert result is failing_collection
    assert calls["create"] == 0
    drop_collection.assert_not_called()

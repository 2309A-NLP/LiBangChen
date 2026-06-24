from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.document_ingestion import DocumentChunk
from app.services.reranker import (
    FeedbackAdaptiveReranker,
    LLMReranker,
    RerankerService,
    TFIDFReranker,
    _ensure_safe_torch_model_loading,
)
from app.services.retrievers.base import RetrievedChunk


def _build_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk=DocumentChunk(
                chunk_id="a",
                source_id="a.pdf",
                page_number=1,
                text="公司主营业务是工业软件平台研发与销售。",
            ),
            score=0.2,
        ),
        RetrievedChunk(
            chunk=DocumentChunk(
                chunk_id="b",
                source_id="a.pdf",
                page_number=2,
                text="公司注册地址位于武汉东湖新技术开发区。",
            ),
            score=0.9,
        ),
    ]


def _build_model_dir(name: str) -> Path:
    model_dir = Path(".pytest-temp") / name
    model_dir.mkdir(parents=True, exist_ok=True)
    for child in model_dir.iterdir():
        if child.is_file():
            child.unlink()
    return model_dir


def _cleanup_model_dir(model_dir: Path) -> None:
    for child in model_dir.iterdir():
        if child.is_file():
            child.unlink()
    model_dir.rmdir()


def test_tfidf_reranker_promotes_more_relevant_chunk():
    reranker = TFIDFReranker()

    results = reranker.rerank("公司主营业务是什么", _build_chunks())

    assert [item.chunk.chunk_id for item in results] == ["a", "b"]
    assert results[0].metadata["reranker"] == "tfidf"


def test_feedback_reranker_uses_feedback_terms():
    feedback_dir = Path(".pytest-temp")
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / "test_feedback_reranker.jsonl"
    feedback_path.write_text(
        '{"question":"主营业务 是什么","rating":5,"comment":"回答主营业务很准确"}\n',
        encoding="utf-8",
    )
    reranker = FeedbackAdaptiveReranker(feedback_path, positive_rating_threshold=4)

    results = reranker.rerank("主营业务", _build_chunks())

    assert [item.chunk.chunk_id for item in results] == ["a", "b"]
    assert results[0].metadata["feedback_delta"] > 0
    feedback_path.unlink(missing_ok=True)


def test_llm_reranker_falls_back_to_heuristic_when_not_configured():
    reranker = LLMReranker(
        api_key=None,
        base_url=None,
        model=None,
        timeout_seconds=5.0,
    )

    results = reranker.rerank("主营业务", _build_chunks())

    assert [item.chunk.chunk_id for item in results] == ["a", "b"]
    assert results[0].metadata["llm_mode"] == "heuristic_fallback"


def test_reranker_service_applies_pipeline_order():
    service = RerankerService(rerankers=[TFIDFReranker()], top_n=1)

    results = service.rerank("主营业务", _build_chunks())

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "a"
    assert service.strategy_names == ["tfidf"]


def test_torch_model_loading_allows_torch_26_for_legacy_weights():
    model_dir = _build_model_dir("legacy-model-26")
    (model_dir / "pytorch_model.bin").write_bytes(b"weights")

    try:
        _ensure_safe_torch_model_loading(
            SimpleNamespace(__version__="2.6.0+cpu"),
            str(model_dir),
        )
    finally:
        _cleanup_model_dir(model_dir)


def test_torch_model_loading_rejects_old_torch_for_legacy_weights():
    model_dir = _build_model_dir("legacy-model-old")
    (model_dir / "pytorch_model.bin").write_bytes(b"weights")

    try:
        with pytest.raises(RuntimeError, match="PyTorch >=2.6"):
            _ensure_safe_torch_model_loading(
                SimpleNamespace(__version__="2.5.1"),
                str(model_dir),
            )
    finally:
        _cleanup_model_dir(model_dir)


def test_torch_model_loading_allows_old_torch_for_safetensors_only():
    model_dir = _build_model_dir("safe-model-old")
    (model_dir / "model.safetensors").write_bytes(b"weights")

    try:
        _ensure_safe_torch_model_loading(
            SimpleNamespace(__version__="2.5.1"),
            str(model_dir),
        )
    finally:
        _cleanup_model_dir(model_dir)

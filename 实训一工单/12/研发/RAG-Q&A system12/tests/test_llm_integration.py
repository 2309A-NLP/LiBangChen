from app.core.config import Settings
from app.schemas.query import QueryUnderstandingResult
from app.services.document_ingestion import DocumentChunk
from app.services.llm.factory import build_llm_client
from app.services.llm.openai_compatible import OpenAICompatibleLLMClient
from app.services.retrievers.base import RetrievedChunk


def test_build_llm_client_returns_openai_compatible_client():
    client = build_llm_client(
        Settings(
            llm_provider="openai_compatible",
            llm_api_key="test-key",
            llm_base_url="https://example.com/v1",
            llm_model="test-model",
        )
    )

    assert isinstance(client, OpenAICompatibleLLMClient)


def test_openai_compatible_llm_client_generates_answer_from_response(monkeypatch):
    client = OpenAICompatibleLLMClient(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        timeout_seconds=30.0,
        temperature=0.2,
    )

    def fake_create_chat_completion(payload: dict[str, object]) -> dict[str, object]:
        assert payload["model"] == "test-model"
        assert payload["messages"][1]["role"] == "user"
        return {
            "choices": [
                {
                    "message": {
                        "content": "根据当前检索到的内容，公司主营业务主要集中在核心产品销售。"
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_create_chat_completion", fake_create_chat_completion)

    result = client.generate_answer(
        question="公司的主营业务是什么？",
        understanding=QueryUnderstandingResult(
            intent="business_overview",
            normalized_question="公司的主营业务是什么？",
            strategy="online",
            sub_questions=[],
            abstracted_goal="定位主营业务并概括回答。",
            retrieval_hints={"keywords": ["主营业务"]},
        ),
        retrieved_chunks=[
            RetrievedChunk(
                chunk=DocumentChunk(
                    chunk_id="page-1-chunk-1",
                    source_id="prospectus.pdf",
                    page_number=1,
                    text="公司主营业务主要包括核心产品销售与配套服务。",
                ),
                score=3.2,
            )
        ],
        conversation_messages=[{"role": "user", "content": "先告诉我这是什么公司"}],
    )

    assert result.answer == "根据当前检索到的内容，公司主营业务主要集中在核心产品销售。"
    assert result.metadata["mode"] == "openai_compatible"
    assert result.metadata["model"] == "test-model"
    assert result.metadata["history_message_count"] == 1

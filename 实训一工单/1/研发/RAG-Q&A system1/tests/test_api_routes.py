from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


def test_document_select_and_stream_query(tmp_path, monkeypatch):
    class StubDocumentIngestionService:
        def __init__(self) -> None:
            self.selected = []
            self.documents = {
                "a.pdf": [
                    {
                        "chunk_id": "a-1",
                        "page_number": 1,
                        "text": "alpha",
                        "char_count": 5,
                    }
                ],
                "b.pdf": [
                    {
                        "chunk_id": "b-1",
                        "page_number": 2,
                        "text": "beta",
                        "char_count": 4,
                    }
                ],
            }

        def load_document(self, force: bool = False) -> None:
            return None

        def status(self) -> dict[str, object]:
            return {
                "source_pdf_dir": str(tmp_path),
                "source_files": ["a.pdf", "b.pdf"],
                "selected_sources": list(self.selected),
                "document_count": 2,
                "document_loaded": True,
                "chunk_count": 3,
                "last_loaded_at": None,
                "warnings": [],
            }

        def select_sources(self, source_files: list[str] | None) -> None:
            self.selected = source_files or []

        def save_uploaded_pdf(self, file_name: str, content: bytes) -> str:
            path = tmp_path / file_name
            path.write_bytes(content)
            self.documents[file_name] = [
                {
                    "chunk_id": f"{file_name}-1",
                    "page_number": 1,
                    "text": "uploaded chunk",
                    "char_count": 14,
                }
            ]
            return file_name

        def list_documents(self) -> list[dict]:
            return [
                {
                    "source_id": source_id,
                    "chunk_count": len(chunks),
                    "page_range": "1-1",
                    "text_preview": chunks[0]["text"] if chunks else "",
                }
                for source_id, chunks in self.documents.items()
            ]

        def get_document_chunks(self, source_id: str) -> list[dict]:
            if source_id not in self.documents:
                raise FileNotFoundError(source_id)
            return list(self.documents[source_id])

        def delete_source(self, source_id: str) -> bool:
            if source_id not in self.documents:
                return False
            self.documents.pop(source_id, None)
            self.selected = [item for item in self.selected if item != source_id]
            path = tmp_path / source_id
            if path.exists():
                path.unlink()
            return True

    class StubPipelineService:
        def answer_question(self, payload):
            class Response:
                def model_dump(self):
                    return {
                        "answer_id": "1",
                        "session_id": payload.session_id or "session-1",
                        "question": payload.question,
                        "answer": "这是流式回答。",
                        "citations": [],
                        "understanding": {
                            "intent": "general_information",
                            "normalized_question": payload.question,
                            "strategy": "local_first_rules",
                            "intent_confidence": None,
                            "ambiguous_terms": [],
                            "clarification_needed": False,
                            "clarification_question": None,
                            "sub_questions": [],
                            "abstracted_goal": "直接回答",
                            "assumptions": [],
                            "retrieval_hints": {},
                        },
                        "debug": None,
                    }

            return Response()

    class StubSessionService:
        def get_history(self, session_id: str):
            return []

    stub_container = SimpleNamespace(
        document_ingestion_service=StubDocumentIngestionService(),
        pipeline_service=StubPipelineService(),
        session_service=StubSessionService(),
        warmup_status_service=SimpleNamespace(
            start=lambda **kwargs: None,
            succeed=lambda *args, **kwargs: None,
            fail=lambda *args, **kwargs: None,
            snapshot=lambda: {
                "status": "ready",
                "message": "ready",
                "selected_only": True,
                "started_at": None,
                "finished_at": None,
                "error": None,
            }
        ),
        settings=SimpleNamespace(
            app_env="test",
            llm_provider="mock",
            query_understanding_mode="rules",
        ),
    )

    def prepare_retrieval(selected_only: bool = False) -> None:
        return None

    stub_container.prepare_retrieval = prepare_retrieval
    monkeypatch.setattr("app.main.AppContainer.build", lambda: stub_container)
    app = create_app()

    with patch("app.api.routes.Thread") as thread_cls, TestClient(app) as client:
        prepare_calls = {"count": 0}
        client.app.state.container.prepare_retrieval = lambda selected_only=False: prepare_calls.__setitem__(  # type: ignore[method-assign]
            "count",
            prepare_calls["count"] + 1,
        )
        thread_cls.side_effect = lambda target, daemon: SimpleNamespace(start=target)

        select_response = client.post("/api/document/select", json={"source_files": ["a.pdf"]})
        assert select_response.status_code == 200
        assert select_response.json() == {"selected_sources": ["a.pdf"]}

        upload_response = client.post(
            "/api/document/upload",
            files={"file": ("new.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert upload_response.status_code == 200
        assert (tmp_path / "new.pdf").exists()
        assert upload_response.json()["selected_sources"] == ["new.pdf"]
        assert prepare_calls["count"] == 1

        reload_response = client.post("/api/document/reload")
        assert reload_response.status_code == 200
        assert prepare_calls["count"] == 2

        warmup_response = client.get("/api/document/warmup")
        assert warmup_response.status_code == 200
        assert warmup_response.json()["status"] == "ready"

        kb_list_response = client.get("/api/kb/documents")
        assert kb_list_response.status_code == 200
        assert kb_list_response.json()["total_chunks"] >= 2

        kb_chunks_response = client.get("/api/kb/documents/a.pdf/chunks")
        assert kb_chunks_response.status_code == 200
        assert kb_chunks_response.json()["source_id"] == "a.pdf"
        assert kb_chunks_response.json()["total_chunks"] == 1

        kb_missing_chunks_response = client.get("/api/kb/documents/missing.pdf/chunks")
        assert kb_missing_chunks_response.status_code == 404

        delete_response = client.delete("/api/kb/documents/a.pdf")
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted_source"] == "a.pdf"
        assert prepare_calls["count"] == 3

        delete_missing_response = client.delete("/api/kb/documents/missing.pdf")
        assert delete_missing_response.status_code == 404

        stream_response = client.post(
            "/api/query/stream",
            json={"question": "主营业务是什么？", "source_files": ["a.pdf"]},
        )
        assert stream_response.status_code == 200
        assert '"type": "result"' in stream_response.text
        assert '"session_id": "session-1"' in stream_response.text

        session_response = client.get("/api/session/session-1")
        assert session_response.status_code == 200
        assert session_response.json() == {"session_id": "session-1", "messages": []}

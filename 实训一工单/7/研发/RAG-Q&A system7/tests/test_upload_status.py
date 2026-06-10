from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ingestion_status import IngestionStatusService


def test_upload_marks_processing_before_background_thread_runs(monkeypatch, tmp_path):
    class StubDocumentIngestionService:
        def __init__(self) -> None:
            self.selected = []

        def load_document(self, force: bool = False, source_files: list[str] | None = None) -> None:
            return None

        def status(self) -> dict[str, object]:
            return {
                "source_pdf_dir": str(tmp_path),
                "source_files": [],
                "selected_sources": list(self.selected),
                "document_count": 0,
                "document_loaded": False,
                "chunk_count": 0,
                "selected_chunk_count": 0,
                "last_loaded_at": None,
                "warnings": [],
            }

        def select_sources(self, source_files: list[str] | None) -> None:
            self.selected = list(source_files or [])

        def save_uploaded_pdf(self, file_name: str, content: bytes) -> str:
            (tmp_path / file_name).write_bytes(content)
            return file_name

    stub_container = SimpleNamespace(
        document_ingestion_service=StubDocumentIngestionService(),
        pipeline_service=SimpleNamespace(),
        session_service=SimpleNamespace(get_history=lambda session_id: []),
        ingestion_status_service=IngestionStatusService(),
        warmup_status_service=SimpleNamespace(
            start=lambda **kwargs: None,
            succeed=lambda *args, **kwargs: None,
            fail=lambda *args, **kwargs: None,
            snapshot=lambda: {
                "status": "idle",
                "message": "not_started",
                "selected_only": True,
                "started_at": None,
                "finished_at": None,
                "error": None,
            },
        ),
        settings=SimpleNamespace(
            app_env="test",
            llm_provider="mock",
            query_understanding_mode="rules",
        ),
        prepare_retrieval=lambda selected_only=False: None,
    )
    monkeypatch.setattr("app.main.AppContainer.build", lambda: stub_container)
    app = create_app()

    with patch("app.api.routes.Thread") as thread_cls, TestClient(app) as client:
        thread_cls.return_value = SimpleNamespace(start=lambda: None)
        response = client.post(
            "/api/document/upload",
            files=[("files", ("new.pdf", b"%PDF-1.4", "application/pdf"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processing_status"] == "running"
    assert payload["processing_message"] == "upload_received"
    assert payload["processing_sources"] == ["new.pdf"]
    assert payload["selected_sources"] == ["new.pdf"]


def test_document_status_recovers_ready_zero_document_state(monkeypatch, tmp_path):
    class RecoveringDocumentIngestionService:
        def __init__(self) -> None:
            self.loaded = False
            self.selected = []

        def load_document(self, force: bool = False, source_files: list[str] | None = None) -> None:
            self.loaded = True

        def status(self) -> dict[str, object]:
            if not self.loaded:
                return {
                    "source_pdf_dir": str(tmp_path),
                    "source_files": [],
                    "selected_sources": list(self.selected),
                    "document_count": 0,
                    "document_loaded": False,
                    "chunk_count": 0,
                    "selected_chunk_count": 0,
                    "last_loaded_at": None,
                    "warnings": [],
                }
            return {
                "source_pdf_dir": str(tmp_path),
                "source_files": ["new.pdf"],
                "selected_sources": list(self.selected),
                "document_count": 1,
                "document_loaded": True,
                "chunk_count": 3,
                "selected_chunk_count": 3,
                "last_loaded_at": "2026-06-07T14:00:01+00:00",
                "warnings": [],
            }

        def select_sources(self, source_files: list[str] | None) -> None:
            self.selected = list(source_files or [])

    stub_container = SimpleNamespace(
        document_ingestion_service=RecoveringDocumentIngestionService(),
        pipeline_service=SimpleNamespace(),
        session_service=SimpleNamespace(get_history=lambda session_id: []),
        ingestion_status_service=SimpleNamespace(
            snapshot=lambda: {
                "status": "ready",
                "message": "documents_ready",
                "source_files": ["new.pdf"],
                "started_at": "2026-06-07T14:00:00+00:00",
                "finished_at": "2026-06-07T14:00:01+00:00",
                "error": None,
            },
        ),
        warmup_status_service=SimpleNamespace(
            start=lambda **kwargs: None,
            succeed=lambda *args, **kwargs: None,
            fail=lambda *args, **kwargs: None,
            snapshot=lambda: {
                "status": "idle",
                "message": "not_started",
                "selected_only": True,
                "started_at": None,
                "finished_at": None,
                "error": None,
            },
        ),
        settings=SimpleNamespace(
            app_env="test",
            llm_provider="mock",
            query_understanding_mode="rules",
        ),
        prepare_retrieval=lambda selected_only=False: None,
    )
    monkeypatch.setattr("app.main.AppContainer.build", lambda: stub_container)
    app = create_app()

    with patch("app.main.Thread") as thread_cls, TestClient(app) as client:
        thread_cls.return_value = SimpleNamespace(start=lambda: None)
        response = client.get("/api/document/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_count"] == 1
    assert payload["selected_chunk_count"] == 3
    assert payload["selected_sources"] == ["new.pdf"]

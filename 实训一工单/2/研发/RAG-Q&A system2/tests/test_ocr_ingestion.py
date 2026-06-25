from types import SimpleNamespace

from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService
from app.services.ocr import OCRService


def test_document_ingestion_uses_ocr_when_pdf_looks_scanned(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "scan.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )

    class FakeOCRService:
        def is_available(self) -> bool:
            return True

        def extract_page_texts(self, pdf_path):
            assert pdf_path.name == "scan.pdf"
            return ["OCR extracted text from scanned page"]

        def status(self):
            return SimpleNamespace(
                enabled=True,
                available=True,
                engine="fake-ocr",
                message="ok",
            )

    service = DocumentIngestionService(settings, ocr_service=FakeOCRService())

    class FakePage:
        def extract_text(self) -> str:
            return ""

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    chunks = service.chunks()

    assert len(chunks) == 1
    assert "OCR extracted text from scanned page" in chunks[0].text
    assert any("OCR was applied" in warning for warning in service.status()["warnings"])


def test_document_ingestion_reports_warning_when_scanned_pdf_needs_ocr_but_unavailable(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "scan.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings, ocr_service=OCRService(enabled=False))

    class FakePage:
        def extract_text(self) -> str:
            return ""

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    warnings = service.status()["warnings"]

    assert any("OCR is unavailable" in warning for warning in warnings)

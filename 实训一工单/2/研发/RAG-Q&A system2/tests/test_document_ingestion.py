from pathlib import Path

from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService
from app.services.ocr import OCRService


def test_document_ingestion_discovers_multiple_pdfs(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"%PDF-1.4")
    (source_dir / "b.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, path: str) -> None:
            name = Path(path).name
            if name == "a.pdf":
                self.pages = [FakePage("doc a page 1"), FakePage("doc a page 2")]
            else:
                self.pages = [FakePage("doc b page 1")]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    status = service.status()

    assert status["document_loaded"] is True
    assert status["document_count"] == 2
    assert status["source_files"] == ["a.pdf", "b.pdf"]
    assert status["chunk_count"] == 3


def test_document_ingestion_uses_single_file_fallback_when_directory_has_no_pdfs(
    tmp_path,
    monkeypatch,
):
    source_dir = tmp_path / "empty-source"
    source_dir.mkdir()
    fallback_pdf = tmp_path / "fallback.pdf"
    fallback_pdf.write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=fallback_pdf,
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def extract_text(self) -> str:
            return "fallback content"

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    status = service.status()

    assert status["document_loaded"] is True
    assert status["document_count"] == 1
    assert status["source_files"] == ["fallback.pdf"]
    assert status["chunk_count"] == 1


def test_document_ingestion_filters_table_of_contents_lines(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def extract_text(self) -> str:
            return (
                "第二节 概览 ................................ 15\n"
                "技术先进性 ................................ 21\n"
                "公司参与制定了全军第一个视频指挥系统技术标准。"
            )

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    chunks = service.chunks()

    assert len(chunks) == 1
    assert "................................" not in chunks[0].text
    assert "技术标准" in chunks[0].text


def test_document_ingestion_keeps_table_page_more_complete(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
        max_chunk_length=80,
        table_chunk_length=400,
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def extract_text(self) -> str:
            return (
                "三、销售情况和主要客户\n"
                "2、按客户群体划分的销售情况\n"
                "单位：万元\n"
                "类型 2018年度 2017年度 2016年度\n"
                "金额 占比 金额 占比 金额 占比\n"
                "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10%\n"
                "民用领域 1,021.81 5.16% 398.56 2.69% 1,409.12 17.90%\n"
                "合计 19,802.48 100.00% 14,812.72 100.00% 7,873.63 100.00%\n"
            )

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    chunks = service.chunks()

    assert len(chunks) == 1
    assert "国防领域 18,780.67 94.84% 14,414.16 97.31% 6,464.51 82.10%" in chunks[0].text


def test_document_ingestion_loads_single_uploaded_pdf_without_full_reload(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"%PDF-1.4")
    (source_dir / "new.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, path: str) -> None:
            name = Path(path).name
            if name == "a.pdf":
                self.pages = [FakePage("old content")]
            else:
                self.pages = [FakePage("new content")]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    service.select_sources(["a.pdf"])
    service.load_single_document("new.pdf")

    assert "new.pdf" in service.available_source_files()
    assert any(chunk.source_id == "new.pdf" for chunk in service.all_chunks())
    assert service.status()["selected_sources"] == ["a.pdf"]


def test_document_ingestion_removes_repeated_headers_and_footers(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [
                FakePage(
                    "武汉兴图新科电子股份有限公司\n"
                    "2024年度报告\n"
                    "这是第一页正文内容。\n"
                    "更多正文信息。\n"
                    "第 1 页\n"
                ),
                FakePage(
                    "武汉兴图新科电子股份有限公司\n"
                    "2024年度报告\n"
                    "这是第二页正文内容。\n"
                    "仍然是正文。\n"
                    "第 2 页\n"
                ),
                FakePage(
                    "武汉兴图新科电子股份有限公司\n"
                    "2024年度报告\n"
                    "这是第三页正文内容。\n"
                    "最后一段正文。\n"
                    "第 3 页\n"
                ),
            ]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    combined = "\n".join(chunk.text for chunk in service.chunks())

    assert "武汉兴图新科电子股份有限公司" not in combined
    assert "2024年度报告" not in combined
    assert "第 1 页" not in combined
    assert "第 2 页" not in combined
    assert "第 3 页" not in combined
    assert "这是第一页正文内容。" in combined
    assert "这是第二页正文内容。" in combined
    assert "这是第三页正文内容。" in combined

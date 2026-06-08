from pathlib import Path

from app.core.config import Settings
from app.services.document_ingestion import DocumentIngestionService


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
                self.pages = [FakePage("甲文档第一页。"), FakePage("甲文档第二页。")]
            else:
                self.pages = [FakePage("乙文档第一页。")]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    service.load_document(force=True)
    status = service.status()

    assert status["document_loaded"] is True
    assert status["document_count"] == 2
    assert status["source_files"] == ["a.pdf", "b.pdf"]
    assert status["chunk_count"] == 3

    chunks = service.chunks()
    assert {chunk.source_id for chunk in chunks} == {"a.pdf", "b.pdf"}
    assert any(chunk.chunk_id.startswith("a-page-1-chunk-1") for chunk in chunks)


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
            return "兜底文档内容。"

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


def test_document_ingestion_merges_layout_text_for_chart_pages(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
    )
    service = DocumentIngestionService(settings)

    merged = service._merge_page_text(
        "公司组织结构如下图：\n销售部\n",
        "渠道销售部\n珠海销售处\n深圳销售处\n",
    )

    assert "销售部" in merged
    assert "渠道销售部" in merged
    assert "珠海销售处" in merged

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
        pdf_parser_provider="pypdf",
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
        pdf_parser_provider="pypdf",
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
        pdf_parser_provider="pypdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def extract_text(self) -> str:
            return (
                "第二节 概览 ................................ 15\n"
                "技术先进性 ................................ 21\n"
                "公司参与制定了相关技术标准。"
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
        pdf_parser_provider="pypdf",
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


def test_document_ingestion_can_use_doubao_markdown_output(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "chart.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
        pdf_parser_provider="doubao",
        llm_api_key="fake-key",
        llm_base_url="https://ark.example.com/api/v3",
        llm_model="doubao-vision-test",
    )
    service = DocumentIngestionService(settings)

    def fake_call_doubao(pdf_path: Path) -> str:
        assert pdf_path.name == "chart.pdf"
        return (
            "<!-- page: 37 -->\n"
            "## 销售部门组织结构图\n"
            "销售部下设客户销售部、大客户销售部、市场部。\n"
            "<!-- page: 38 -->\n"
            "## 电子元器件分销商毛利率图\n"
            "| 毛利率区间 | 占比 |\n"
            "| --- | --- |\n"
            "| 7%-10% | 30% |\n"
        )

    service._call_doubao_pdf_markdown = fake_call_doubao  # type: ignore[method-assign]

    service.load_document(force=True)
    chunks = service.chunks()

    assert len(chunks) == 2
    assert chunks[0].source_id == "chart.pdf"
    assert chunks[0].page_number == 37
    assert "大客户销售部" in chunks[0].text
    assert chunks[1].page_number == 38
    assert "7%-10%" in chunks[1].text


def test_document_ingestion_reuses_cached_result_for_unchanged_pdf(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "cached.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
        document_cache_path=tmp_path / "processed" / "document_cache.json",
        pdf_parser_provider="pypdf",
    )
    service = DocumentIngestionService(settings)

    class FakePage:
        def extract_text(self) -> str:
            return "缓存测试文本。"

    class FakeReader:
        def __init__(self, _: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    service.load_document(force=True)
    assert len(service.chunks()) == 1

    class ExplodingReader:
        def __init__(self, _: str) -> None:
            raise AssertionError("cache should avoid reparsing unchanged files")

    monkeypatch.setattr("pypdf.PdfReader", ExplodingReader)
    service.load_document(force=True)

    chunks = service.chunks()
    assert len(chunks) == 1
    assert chunks[0].text == "缓存测试文本。"


def test_document_ingestion_auto_upgrades_chart_like_page_with_doubao(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "auto.pdf").write_bytes(b"%PDF-1.4")

    settings = Settings(
        source_pdf_dir=source_dir,
        source_pdf_path=source_dir / "fallback.pdf",
        document_cache_path=tmp_path / "processed" / "document_cache.json",
        pdf_parser_provider="auto",
        llm_api_key="fake-key",
        llm_base_url="https://ark.example.com/api/v3",
        llm_model="doubao-vision-test",
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
                FakePage("这是一段正常的文本内容，长度足够长，不需要视觉升级。"),
                FakePage("图1 组织架构图"),
            ]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)
    service._iter_pdf_pages_as_jpeg_base64 = lambda pdf_path, only_pages=None: iter([(2, "fake-base64")])  # type: ignore[method-assign]
    service._call_doubao_page_markdown = lambda file_name, page_number, image_base64: (  # type: ignore[method-assign]
        "<!-- page: 2 -->\n"
        "## 组织架构图\n"
        "公司下设研发中心、制造中心、营销中心。"
    )

    service.load_document(force=True)
    chunks = service.chunks()

    assert len(chunks) == 2
    assert any("研发中心" in chunk.text for chunk in chunks)

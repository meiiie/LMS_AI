from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.adapters.document_parser_router import DocumentParserRouter
from app.ports.document_parser import ParsedDocument


class FakeParser:
    def __init__(self, parsed: ParsedDocument | None = None, error: Exception | None = None):
        self.parsed = parsed
        self.error = error
        self.calls = 0

    async def parse(self, file_path: str, options: dict | None = None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.parsed

    def supported_formats(self):
        return ["docx", "pdf"]


def _parsed(parser: str, provenance: str, *, sections: int = 0, assets: int = 0):
    return ParsedDocument(
        markdown="# Section\n\nBody",
        page_count=1 if provenance == "text_only" else 3,
        metadata={
            "parser": parser,
            "parser_chain": [parser],
            "provenance_level": provenance,
        },
        section_map={f"Section {idx}": [idx] for idx in range(1, sections + 1)},
        images=[{"kind": "image", "page": 2}] * assets,
        assets=[{"kind": "image", "page": 2}] * assets,
    )


@pytest.mark.asyncio
async def test_auto_promotes_weak_markitdown_parse_to_docling():
    markitdown = FakeParser(_parsed("markitdown", "text_only"))
    docling = FakeParser(_parsed("docling", "page_layout", sections=3, assets=1))
    router = DocumentParserRouter(
        markitdown_parser=markitdown,
        docling_parser=docling,
        mode="auto",
    )

    parsed = await router.parse("manual.docx")

    assert parsed.metadata["parser"] == "docling"
    assert parsed.metadata["parser_chain"] == ["markitdown", "docling"]
    assert parsed.metadata["provenance_level"] == "page_layout"
    assert "promoted" in parsed.metadata["parser_warning"]
    assert markitdown.calls == 1
    assert docling.calls == 1


@pytest.mark.asyncio
async def test_auto_keeps_markitdown_when_page_markers_are_available():
    markitdown = FakeParser(_parsed("markitdown", "page_marker", sections=2))
    docling = FakeParser(_parsed("docling", "page_layout", sections=3))
    router = DocumentParserRouter(
        markitdown_parser=markitdown,
        docling_parser=docling,
        mode="auto",
    )

    parsed = await router.parse("manual.docx")

    assert parsed.metadata["parser"] == "markitdown"
    assert docling.calls == 0


@pytest.mark.asyncio
async def test_auto_marks_warning_when_precision_upgrade_is_unavailable():
    markitdown = FakeParser(_parsed("markitdown", "text_only"))
    router = DocumentParserRouter(
        markitdown_parser=markitdown,
        docling_parser=None,
        mode="auto",
    )

    parsed = await router.parse("manual.docx")

    assert parsed.metadata["parser"] == "markitdown"
    assert "weak page/layout provenance" in parsed.metadata["parser_warning"]


@pytest.mark.asyncio
async def test_precision_falls_back_to_markitdown_with_warning():
    markitdown = FakeParser(_parsed("markitdown", "text_only"))
    docling = FakeParser(error=RuntimeError("docling unavailable"))
    router = DocumentParserRouter(
        markitdown_parser=markitdown,
        docling_parser=docling,
        mode="precision",
    )

    parsed = await router.parse("manual.docx")

    assert parsed.metadata["parser"] == "markitdown"
    assert "fell back to MarkItDown" in parsed.metadata["parser_warning"]


@pytest.mark.asyncio
async def test_docling_adapter_extracts_generic_sections_and_assets(monkeypatch, tmp_path):
    import sys
    import types

    from app.adapters.docling_parser import DoclingParserAdapter

    class FakeProv:
        page_no = 2
        bbox = SimpleNamespace(l=1, t=2, r=3, b=4)

    class FakeItem:
        def __init__(self, label: str, text: str, page_no: int = 2):
            self.label = label
            self.text = text
            self.prov = [SimpleNamespace(page_no=page_no, bbox=FakeProv.bbox)]

    class FakeDoc:
        name = "manual.docx"
        pages = {1: object(), 2: object()}

        def export_to_markdown(self):
            return "# Bridge manual\n\n## Chuong 2\n\nSee figure and table."

        def iterate_items(self):
            return iter(
                [
                    (FakeItem("title", "Bridge manual", 1), 1),
                    (FakeItem("section_header", "Chuong 2", 2), 2),
                    (FakeItem("picture", "Bridge console diagram", 2), 2),
                    (FakeItem("table", "Watchkeeping checklist", 2), 2),
                ]
            )

    class FakeDocumentConverter:
        def __init__(self, *args, **kwargs):
            pass

        def convert(self, file_path: str):
            return SimpleNamespace(document=FakeDoc())

    fake_converter_module = types.ModuleType("docling.document_converter")
    fake_converter_module.DocumentConverter = FakeDocumentConverter
    fake_converter_module.PdfFormatOption = object
    fake_base_models = types.ModuleType("docling.datamodel.base_models")
    fake_base_models.InputFormat = SimpleNamespace(PDF="pdf")
    monkeypatch.setitem(sys.modules, "docling", types.ModuleType("docling"))
    monkeypatch.setitem(sys.modules, "docling.datamodel", types.ModuleType("docling.datamodel"))
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_converter_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", fake_base_models)

    source = tmp_path / "manual.docx"
    source.write_bytes(b"fake")

    parser = DoclingParserAdapter()
    parsed = await parser.parse(str(source))

    assert parsed.metadata["parser"] == "docling"
    assert parsed.metadata["provenance_level"] == "page_layout"
    assert parsed.section_map["Bridge manual"] == [1]
    assert parsed.section_map["Chuong 2"] == [2]
    assert "<!-- page 1 -->" in parsed.markdown
    assert "<!-- page 2 -->" in parsed.markdown
    assert parsed.metadata["embedded_asset_count"] == 2
    assert parsed.metadata["figure_count"] == 1
    assert parsed.metadata["table_count"] == 1
    assert parsed.assets[0]["bbox"]["l"] == 1


@pytest.mark.asyncio
async def test_docling_adapter_keeps_structured_text_when_docx_has_no_pages(
    monkeypatch,
    tmp_path,
):
    import sys
    import types

    from app.adapters.docling_parser import DoclingParserAdapter

    class FakeItem:
        def __init__(self, label: str, text: str):
            self.label = label
            self.text = text
            self.prov = []

    class FakeDoc:
        name = "manual.docx"
        pages = {}

        def export_to_markdown(self):
            return "# Manual\n\n## 1. Course setup\n\nSee the screenshot and table."

        def iterate_items(self):
            return iter(
                [
                    (FakeItem("section_header", "1. Course setup"), 2),
                    (FakeItem("picture", ""), 3),
                    (FakeItem("table", ""), 3),
                ]
            )

    class FakeDocumentConverter:
        def __init__(self, *args, **kwargs):
            pass

        def convert(self, file_path: str):
            return SimpleNamespace(document=FakeDoc())

    fake_converter_module = types.ModuleType("docling.document_converter")
    fake_converter_module.DocumentConverter = FakeDocumentConverter
    fake_converter_module.PdfFormatOption = object
    fake_base_models = types.ModuleType("docling.datamodel.base_models")
    fake_base_models.InputFormat = SimpleNamespace(PDF="pdf")
    monkeypatch.setitem(sys.modules, "docling", types.ModuleType("docling"))
    monkeypatch.setitem(sys.modules, "docling.datamodel", types.ModuleType("docling.datamodel"))
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_converter_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", fake_base_models)

    source = tmp_path / "manual.docx"
    source.write_bytes(b"fake")

    parser = DoclingParserAdapter()
    parsed = await parser.parse(str(source))

    assert parsed.metadata["provenance_level"] == "structured_text"
    assert parsed.metadata["has_page_provenance"] is False
    assert parsed.metadata["section_count"] == 1
    assert parsed.section_map["1. Course setup"] == []
    assert parsed.assets[0]["page"] is None
    assert "<!-- page " not in parsed.markdown

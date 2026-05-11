from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_markitdown_parser_converts_local_file(monkeypatch, tmp_path):
    from app.adapters.markitdown_parser import MarkItDownConfig, MarkItDownParserAdapter

    class FakeMarkItDown:
        instances: list["FakeMarkItDown"] = []

        def __init__(self, *, enable_plugins: bool = False):
            self.enable_plugins = enable_plugins
            self.converted_paths: list[str] = []
            self.__class__.instances.append(self)

        def convert_local(self, path: str):
            self.converted_paths.append(path)
            return SimpleNamespace(
                markdown="<!-- page 2 -->\n# Radar plotting\nCPA/TCPA notes",
                title="Radar lesson",
            )

    fake_module = types.ModuleType("markitdown")
    fake_module.MarkItDown = FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)

    source = tmp_path / "lesson.docx"
    source.write_bytes(b"fake-docx")

    parser = MarkItDownParserAdapter(MarkItDownConfig(enable_plugins=True))
    parsed = await parser.parse(str(source))

    assert parsed.markdown.startswith("<!-- page 2 -->")
    assert parsed.page_count == 2
    assert parsed.section_map == {"Radar plotting": [2]}
    assert parsed.metadata["title"] == "Radar lesson"
    assert parsed.metadata["parser"] == "markitdown"
    assert parsed.metadata["parser_chain"] == ["markitdown"]
    assert parsed.metadata["provenance_level"] == "page_marker"
    assert FakeMarkItDown.instances[0].enable_plugins is True
    assert FakeMarkItDown.instances[0].converted_paths == [str(source)]


def test_course_generation_prefers_markitdown_for_office(monkeypatch):
    import app.api.v1.course_generation_parsers as parsers

    sentinel = object()

    def fake_markitdown(*, settings_obj, logger):
        return sentinel

    def fail_docling(*, settings_obj, logger):
        raise AssertionError("Docling should not be called when MarkItDown is available")

    monkeypatch.setattr(parsers, "try_build_markitdown_parser", fake_markitdown)
    monkeypatch.setattr(parsers, "try_build_docling_parser", fail_docling)

    parser = parsers.get_parser(
        "demo.xlsx",
        settings_obj=SimpleNamespace(use_docling_for_course_gen=False),
        logger=MagicMock(),
    )

    assert parser is sentinel


def test_course_generation_prefers_docling_when_precision_enabled(monkeypatch):
    import app.api.v1.course_generation_parsers as parsers

    sentinel = object()

    def fake_docling(*, settings_obj, logger):
        return sentinel

    def fail_markitdown(*, settings_obj, logger):
        raise AssertionError("MarkItDown should not be called when Docling precision is enabled")

    monkeypatch.setattr(parsers, "try_build_docling_parser", fake_docling)
    monkeypatch.setattr(parsers, "try_build_markitdown_parser", fail_markitdown)

    parser = parsers.get_parser(
        "demo.docx",
        settings_obj=SimpleNamespace(use_docling_for_course_gen=True),
        logger=MagicMock(),
    )

    assert parser is sentinel


def test_course_generation_non_pdf_accepts_markitdown(monkeypatch):
    import app.api.v1.course_generation_parsers as parsers

    monkeypatch.setattr(
        parsers,
        "try_build_markitdown_parser",
        lambda *, settings_obj, logger: object(),
    )
    monkeypatch.setattr(
        parsers,
        "try_build_docling_parser",
        lambda *, settings_obj, logger: None,
    )

    parsers.ensure_docling_available(
        ".docx",
        settings_obj=SimpleNamespace(markitdown_enable_plugins=False),
        logger=MagicMock(),
    )


def test_course_generation_non_pdf_rejects_when_no_rich_parser(monkeypatch):
    import app.api.v1.course_generation_parsers as parsers

    monkeypatch.setattr(
        parsers,
        "try_build_markitdown_parser",
        lambda *, settings_obj, logger: None,
    )
    monkeypatch.setattr(
        parsers,
        "try_build_docling_parser",
        lambda *, settings_obj, logger: None,
    )

    with pytest.raises(RuntimeError, match="MarkItDown or Docling"):
        parsers.ensure_docling_available(
            ".pptx",
            settings_obj=SimpleNamespace(markitdown_enable_plugins=False),
            logger=MagicMock(),
        )

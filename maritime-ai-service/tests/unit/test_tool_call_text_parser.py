from app.engine.multi_agent.tool_call_text_parser import (
    classify_raw_tool_call_text_start,
    extract_raw_tool_calls_from_text,
    find_raw_tool_call_marker_index,
)


def test_extract_raw_tool_calls_keeps_existing_json_path() -> None:
    calls = extract_raw_tool_calls_from_text(
        '{"name":"tool_web_search","arguments":{"query":"weather Hai Phong"}}',
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "raw_tool_call_0",
            "name": "tool_web_search",
            "args": {"query": "weather Hai Phong"},
        }
    ]


def test_extract_raw_tool_calls_maps_odysseus_style_fenced_search_alias() -> None:
    calls = extract_raw_tool_calls_from_text(
        "```web_search\nweather Hai Phong today\n```",
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "raw_fenced_tool_call_0",
            "name": "tool_web_search",
            "args": {"query": "weather Hai Phong today"},
        }
    ]


def test_extract_raw_tool_calls_rejects_fenced_tool_not_exposed_this_turn() -> None:
    calls = extract_raw_tool_calls_from_text(
        "```web_search\nweather Hai Phong today\n```",
        allowed_tool_names={"tool_fetch_url"},
    )

    assert calls == []


def test_extract_raw_tool_calls_parses_tool_call_block() -> None:
    calls = extract_raw_tool_calls_from_text(
        '[TOOL_CALL] {tool: "search", query: "IANA about H1"} [/TOOL_CALL]',
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "raw_tool_call_block_0",
            "name": "tool_web_search",
            "args": {"query": "IANA about H1"},
        }
    ]


def test_extract_raw_tool_calls_parses_xml_invoke_alias() -> None:
    calls = extract_raw_tool_calls_from_text(
        '<tool_call><invoke name="web_search">'
        '<parameter name="query">weather Hai Phong</parameter>'
        "</invoke></tool_call>",
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "raw_xml_tool_call_0",
            "name": "tool_web_search",
            "args": {"query": "weather Hai Phong"},
        }
    ]


def test_extract_raw_tool_calls_parses_deepseek_dsml() -> None:
    bar = "\uff5c"
    calls = extract_raw_tool_calls_from_text(
        f"<{bar}DSML{bar}tool_calls>"
        f'<{bar}DSML{bar}invoke name="web_search">'
        f'<{bar}DSML{bar}parameter name="query" string="true">'
        "weather Hai Phong"
        f"</{bar}DSML{bar}parameter>"
        f"</{bar}DSML{bar}invoke>"
        f"</{bar}DSML{bar}tool_calls>",
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "raw_xml_tool_call_0",
            "name": "tool_web_search",
            "args": {"query": "weather Hai Phong"},
        }
    ]


def test_extract_raw_tool_calls_parses_anthropic_tool_use_input() -> None:
    calls = extract_raw_tool_calls_from_text(
        '{"type":"tool_use","id":"toolu_1","name":"web_search","input":{"query":"weather Hai Phong"}}',
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "toolu_1",
            "name": "tool_web_search",
            "args": {"query": "weather Hai Phong"},
        }
    ]


def test_extract_raw_tool_calls_parses_content_block_tool_use_input() -> None:
    calls = extract_raw_tool_calls_from_text(
        '{"content":[{"type":"text","text":"Đang tra cứu"},'
        '{"type":"tool_use","id":"toolu_2","name":"web_search","input":{"query":"IANA H1"}}]}',
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "toolu_2",
            "name": "tool_web_search",
            "args": {"query": "IANA H1"},
        }
    ]


def test_extract_raw_tool_calls_preserves_responses_api_call_id() -> None:
    calls = extract_raw_tool_calls_from_text(
        '{"type":"function_call","call_id":"call_resp_1","name":"web_search",'
        '"arguments":"{\\"query\\":\\"IANA H1\\"}"}',
        allowed_tool_names={"tool_web_search"},
    )

    assert calls == [
        {
            "id": "call_resp_1",
            "name": "tool_web_search",
            "args": {"query": "IANA H1"},
        }
    ]


def test_classify_raw_tool_call_text_start_waits_for_ambiguous_fence() -> None:
    assert (
        classify_raw_tool_call_text_start(
            "```web_",
            allowed_tool_names={"tool_web_search"},
        )
        is None
    )
    assert (
        classify_raw_tool_call_text_start(
            "```web_search\nweather",
            allowed_tool_names={"tool_web_search"},
        )
        is True
    )


def test_classify_raw_tool_call_text_start_does_not_buffer_normal_code_block() -> None:
    assert (
        classify_raw_tool_call_text_start(
            "```python\nprint('hello')",
            allowed_tool_names={"tool_web_search"},
        )
        is False
    )


def test_classify_raw_tool_call_text_start_handles_xml_markers() -> None:
    assert (
        classify_raw_tool_call_text_start("<to", allowed_tool_names={"tool_web_search"})
        is None
    )
    assert (
        classify_raw_tool_call_text_start(
            '<tool_call><invoke name="web_search">',
            allowed_tool_names={"tool_web_search"},
        )
        is True
    )
    assert (
        classify_raw_tool_call_text_start("<p>Hello", allowed_tool_names={"tool_web_search"})
        is False
    )


def test_classify_raw_tool_call_text_start_handles_bracket_prefixes_precisely() -> None:
    assert (
        classify_raw_tool_call_text_start("[", allowed_tool_names={"tool_web_search"})
        is None
    )
    assert (
        classify_raw_tool_call_text_start(
            "[TOOL_",
            allowed_tool_names={"tool_web_search"},
        )
        is None
    )
    assert (
        classify_raw_tool_call_text_start(
            '[TOOL_CALL] {"tool": "web_search", "query": "weather"}',
            allowed_tool_names={"tool_web_search"},
        )
        is True
    )
    assert (
        classify_raw_tool_call_text_start(
            '[{"name": "tool_web_search", "arguments": {"query": "weather"}}]',
            allowed_tool_names={"tool_web_search"},
        )
        is True
    )
    assert (
        classify_raw_tool_call_text_start(
            "[Image #1] Đây là ảnh bạn gửi.",
            allowed_tool_names={"tool_web_search"},
        )
        is False
    )


def test_find_raw_tool_call_marker_index_detects_tool_after_preamble() -> None:
    text = "Để mình tra cứu ngay.\n```web_search\nweather Hai Phong today\n```"

    marker_index = find_raw_tool_call_marker_index(
        text,
        allowed_tool_names={"tool_web_search"},
    )

    assert marker_index == text.index("```web_search")


def test_find_raw_tool_call_marker_index_ignores_normal_visible_markers() -> None:
    assert (
        find_raw_tool_call_marker_index(
            "[Image #1] Đây là ảnh bạn gửi.\n```python\nprint('hello')\n```",
            allowed_tool_names={"tool_web_search"},
        )
        is None
    )

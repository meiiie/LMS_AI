import json

from app.engine.multi_agent.code_studio_event_payloads import (
    sanitize_code_studio_tool_call_args_for_stream,
)


def test_sanitize_code_studio_tool_call_args_redacts_code_html_without_mutation():
    code_html = "<html><body>" + ("secret-code" * 80) + "</body></html>"
    args = {
        "code_html": code_html,
        "title": "Pendulum simulation",
        "subtitle": "Interactive canvas",
    }

    public_args = sanitize_code_studio_tool_call_args_for_stream(
        "tool_create_visual_code",
        args,
    )

    assert args["code_html"] == code_html
    assert public_args["title"] == "Pendulum simulation"
    assert public_args["code_html"]["redacted"] is True
    assert public_args["code_html"]["chars"] == len(code_html)
    assert public_args["_public_contract"] == "code_studio_tool_call_args.v1"
    assert "secret-code" not in json.dumps(public_args, ensure_ascii=False)


def test_sanitize_code_studio_tool_call_args_summarizes_large_nested_values():
    public_args = sanitize_code_studio_tool_call_args_for_stream(
        "tool_other",
        {
            "query": "short prompt",
            "options": {"a": 1, "b": 2},
            "items": [1, 2, 3],
            "notes": "x" * 220,
        },
    )

    assert public_args["query"] == "short prompt"
    assert public_args["options"] == {"type": "object", "keys": ["a", "b"], "key_count": 2}
    assert public_args["items"] == {"type": "array", "item_count": 3}
    assert public_args["notes"]["truncated"] is True

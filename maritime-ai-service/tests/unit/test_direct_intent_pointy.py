from app.engine.multi_agent.direct_intent import _needs_pointy
from app.engine.multi_agent.supervisor_runtime_support import _looks_host_ui_navigation_turn
from app.engine.multi_agent.supervisor_hint_runtime import _normalize_router_text_impl


def test_needs_pointy_accepts_explicit_show_intent():
    assert _needs_pointy("Chi vao nut Gui tin nhan giup minh.") is True
    assert _needs_pointy("@wiii-pointy chi vao nut Gui tin nhan.") is True


def test_needs_pointy_does_not_trigger_on_topic_mentions_only():
    assert _needs_pointy("Pointy phai on dinh cho bao cao.") is False
    assert _needs_pointy("Uu tien bao cao: Pointy, Thinking, memory.") is False


def test_needs_pointy_respects_explicit_negative_instruction():
    assert _needs_pointy("Tra loi 3 gach dau dong, khong dung Pointy.") is False
    assert _needs_pointy("Dung su dung @wiii-pointy trong cau tra loi nay.") is False
    assert _needs_pointy("Recall the priorities, no Pointy.") is False


def test_pointy_mode_send_button_routes_as_host_ui_navigation():
    query = "Pointy mode: show the chat send button."

    assert _looks_host_ui_navigation_turn(_normalize_router_text_impl(query)) is True

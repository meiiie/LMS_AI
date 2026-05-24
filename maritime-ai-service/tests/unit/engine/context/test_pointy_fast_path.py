"""Tests for Pointy fast-path UI intent matching."""

from app.engine.context.pointy_actions import POINTY_ACTION_CLICK, POINTY_ACTION_HIGHLIGHT
from app.engine.context.pointy_fast_path import (
    POINTY_FAST_PATH_SOURCE,
    build_pointy_fast_path_action,
    get_pointy_targets_from_context,
    normalize_pointy_text,
)


def _context(targets, feedback=None):
    return {
        "host_context": {
            "page": {
                "type": "course_list",
                "metadata": {
                    "available_targets": targets,
                },
            },
        },
        **({"host_action_feedback": feedback} if feedback else {}),
    }


def test_normalize_pointy_text_handles_vietnamese():
    assert normalize_pointy_text("Wiii oi, nut Kham pha khoa hoc o dau?") == (
        "wiii oi nut kham pha khoa hoc o dau"
    )
    assert normalize_pointy_text("Wiii ơi, Khám phá khóa học ở đâu?") == (
        "wiii oi kham pha khoa hoc o dau"
    )


def test_extracts_valid_pointy_targets_from_host_context():
    ctx = _context([
        {"id": "browse-courses", "selector": '[data-wiii-id="browse-courses"]', "label": "Kham pha"},
        {"id": "", "selector": "#bad"},
        "noise",
    ])

    assert get_pointy_targets_from_context(ctx) == [
        {
            "id": "browse-courses",
            "selector": '[data-wiii-id="browse-courses"]',
            "label": "Kham pha",
            "click_safe": False,
            "click_kind": None,
        }
    ]


def test_empty_host_targets_do_not_fall_back_to_stale_page_context():
    ctx = {
        "host_context": {
            "page": {
                "type": "course_list",
                "metadata": {"available_targets": []},
            },
        },
        "page_context": {
            "available_targets": [
                {
                    "id": "stale-target",
                    "selector": '[data-wiii-id="stale-target"]',
                    "label": "Stale target",
                }
            ]
        },
    }

    assert get_pointy_targets_from_context(ctx) == []


def test_where_is_prompt_emits_highlight_action():
    action = build_pointy_fast_path_action(
        "Wiii oi, nut Kham pha khoa hoc o dau?",
        _context([
            {
                "id": "browse-courses",
                "selector": '[data-wiii-id="browse-courses"]',
                "label": "Kham pha khoa hoc",
                "click_safe": True,
            }
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["selector"] == "browse-courses"
    assert action["params"]["source"] == POINTY_FAST_PATH_SOURCE
    assert action["reason"] == "locate"


def test_accented_where_is_prompt_without_button_word_still_emits_highlight():
    action = build_pointy_fast_path_action(
        "Wiii ơi, Khám phá khóa học ở đâu?",
        _context([
            {
                "id": "browse-courses-link",
                "selector": '[data-wiii-id="browse-courses-link"]',
                "label": "Khám phá khóa học",
                "click_safe": True,
            }
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["selector"] == "browse-courses-link"
    assert action["reason"] == "locate"


def test_open_prompt_clicks_only_safe_navigation_target():
    action = build_pointy_fast_path_action(
        "Wiii mo Kham pha khoa hoc giup toi",
        _context([
            {
                "id": "browse-courses-link",
                "selector": '[data-wiii-id="browse-courses-link"]',
                "label": "Kham pha khoa hoc",
                "click_safe": True,
                "click_kind": "navigation",
            }
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_CLICK
    assert action["params"]["selector"] == "browse-courses-link"
    assert action["params"]["message"] == "Wiii đang mở Kham pha khoa hoc cho bạn."
    assert action["reason"] == "click"


def test_unsafe_click_intent_is_demoted_to_highlight():
    action = build_pointy_fast_path_action(
        "Wiii bam nut Nop bai giup toi",
        _context([
            {
                "id": "submit-quiz",
                "selector": '[data-wiii-id="submit-quiz"]',
                "label": "Nop bai",
                "click_safe": False,
            }
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["message"] == "Đây là Nop bai. Wiii trỏ vào để bạn thấy ngay."
    assert action["reason"] == "unsafe_click_demoted"


def test_send_message_prompt_prefers_send_button_over_message_edit_controls():
    action = build_pointy_fast_path_action(
        "Pointy hay chi vao nut Gui tin nhan va noi mot lan thoi.",
        _context([
            {
                "id": "auto:button:chinh-sua-tin-nhan-8",
                "selector": '[data-wiii-id="auto:button:chinh-sua-tin-nhan-8"]',
                "label": "Chinh sua tin nhan",
                "click_safe": False,
            },
            {
                "id": "chat-send-button",
                "selector": '[data-wiii-id="chat-send-button"]',
                "label": "Gui tin nhan",
                "click_safe": False,
            },
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["selector"] == "chat-send-button"


def test_natural_pointy_retry_prompt_matches_send_button():
    action = build_pointy_fast_path_action(
        "Pointy, chi lai nut Gui va noi that ngan thoi.",
        _context([
            {
                "id": "auto:button:chinh-sua-tin-nhan-8",
                "selector": '[data-wiii-id="auto:button:chinh-sua-tin-nhan-8"]',
                "label": "Chinh sua tin nhan",
                "click_safe": False,
            },
            {
                "id": "chat-send-button",
                "selector": '[data-wiii-id="chat-send-button"]',
                "label": "Gui tin nhan",
                "click_safe": False,
            },
        ]),
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["selector"] == "chat-send-button"


def test_wiii_desktop_send_message_prompt_uses_stable_send_button_when_inventory_is_stale():
    action = build_pointy_fast_path_action(
        "Pointy hay chi vao nut Gui tin nhan va noi mot lan thoi.",
        {
            "host_context": {
                "host_type": "wiii-desktop",
                "page": {
                    "type": "chat",
                    "metadata": {
                        "available_targets": [
                            {
                                "id": "auto:button:chinh-sua-tin-nhan-9",
                                "selector": '[data-wiii-id="auto:button:chinh-sua-tin-nhan-9"]',
                                "label": "Chinh sua tin nhan",
                                "click_safe": False,
                            }
                        ],
                    },
                },
            },
        },
    )

    assert action is not None
    assert action["action"] == POINTY_ACTION_HIGHLIGHT
    assert action["params"]["selector"] == "chat-send-button"


def test_pointy_topic_memory_prompt_does_not_emit_fast_path_action():
    action = build_pointy_fast_path_action(
        (
            "Trong phien nay, hay nho 3 uu tien bao cao: Pointy phai on dinh, "
            "Thinking phai hien ro, memory phai dang tin. Tra loi chi: Da ghi nhan."
        ),
        _context([
            {
                "id": "chat-send-button",
                "selector": '[data-wiii-id="chat-send-button"]',
                "label": "Gui tin nhan",
                "click_safe": False,
            }
        ]),
    )

    assert action is None


def test_web_search_prompt_does_not_emit_search_button_fast_path_action():
    action = build_pointy_fast_path_action(
        "Tim tren web giup minh: OpenAI Responses API dung de lam gi? Ma kiem thu WEB-528.",
        _context([
            {
                "id": "search-button",
                "selector": '[data-wiii-id="search-button"]',
                "label": "Mo tim kiem",
                "click_safe": True,
                "click_kind": "search",
            }
        ]),
    )

    assert action is None


def test_capability_inventory_prompt_does_not_emit_image_input_fast_path_action():
    action = build_pointy_fast_path_action(
        (
            "Wiii hien xu ly duoc anh dau vao, tao anh, Word, Excel, "
            "video toi muc nao? Tra loi trung thuc, 5 y ngan."
        ),
        _context([
            {
                "id": "image-upload-button",
                "selector": '[data-wiii-id="image-upload-button"]',
                "label": "Anh dau vao",
                "click_safe": True,
            }
        ]),
    )

    assert action is None


def test_visual_simulation_prompt_does_not_get_hijacked_by_open_term():
    action = build_pointy_fast_path_action(
        "Mô phỏng Quy tắc 15 COLREGs",
        _context([
            {
                "id": "auto:button:giai-thich-quy-tac-15-colregs",
                "selector": '[data-wiii-id="auto:button:giai-thich-quy-tac-15-colregs"]',
                "label": "Giai thich Quy tac 15 COLREGs",
                "click_safe": True,
            }
        ]),
    )

    assert action is None


def test_skips_when_frontend_fast_path_already_reported_feedback():
    action = build_pointy_fast_path_action(
        "Wiii oi, nut Kham pha khoa hoc o dau?",
        _context(
            [
                {
                    "id": "browse-courses",
                    "selector": '[data-wiii-id="browse-courses"]',
                    "label": "Kham pha khoa hoc",
                }
            ],
            feedback={
                "last_action_result": {
                    "params": {"source": POINTY_FAST_PATH_SOURCE},
                },
            },
        ),
    )

    assert action is None

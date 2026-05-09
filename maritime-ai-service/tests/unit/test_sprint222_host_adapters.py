"""Sprint 222: Host Adapter system — per-host-type context formatting."""
import pytest


class TestLMSHostAdapter:
    def test_format_lesson_page(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={
                "type": "lesson",
                "title": "COLREGs Rule 14",
                "metadata": {"course_name": "An toàn hàng hải"},
            },
            content={"snippet": "Khi hai tàu gặp nhau đối hướng..."},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "<host_context" in result
        assert "COLREGs Rule 14" in result
        assert "An toàn hàng hải" in result
        assert "Khi hai tàu" in result

    def test_format_quiz_page_has_socratic_warning(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={
                "type": "quiz",
                "title": "Kiểm tra",
                "metadata": {
                    "quiz_question": "Tàu nào nhường?",
                    "quiz_options": ["Tàu A", "Tàu B"],
                },
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "KHÔNG" in result  # Socratic warning
        assert "Tàu nào nhường" in result

    def test_format_with_user_state(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "lesson", "title": "Test"},
            user_state={"scroll_percent": 75, "time_on_page_ms": 180000},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "75" in result
        assert "3" in result  # 3 minutes

    def test_format_with_available_actions(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "lesson", "title": "Test"},
            available_actions=[
                {"action": "navigate", "label": "Đi tới bài tiếp"}
            ],
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Đi tới bài tiếp" in result

    def test_format_with_pointy_targets(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={
                "type": "course_list",
                "title": "Courses",
                "metadata": {
                    "available_targets": [
                        {
                            "id": "browse-courses",
                            "selector": '[data-wiii-id="browse-courses"]',
                            "label": "Browse courses",
                            "click_safe": True,
                            "click_kind": "navigation",
                        }
                    ]
                },
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "<available_targets>" in result
        assert "browse-courses" in result
        assert "[data-wiii-id=&quot;browse-courses&quot;]" in result
        assert "click_safe=true" in result
        assert "click_kind=navigation" in result

    def test_format_with_pointy_targets_escapes_dynamic_fields(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={
                "type": "course_list",
                "title": "Courses",
                "metadata": {
                    "available_targets": [
                        {
                            "id": "bad|id",
                            "selector": '[data-wiii-id="bad|id"]',
                            "label": 'Bad <script> "target" | ok',
                            "click_safe": True,
                            "click_kind": "nav|primary",
                        }
                    ]
                },
            },
        )

        result = adapter.format_context_for_prompt(ctx)

        assert "bad/id" in result
        assert "Bad &lt;script&gt; &quot;target&quot; / ok" in result
        assert "[data-wiii-id=&quot;bad/id&quot;]" in result
        assert "click_kind=nav/primary" in result
        assert "<script>" not in result

    def test_format_exam_page_has_socratic_warning(self):
        """Exam pages should also trigger Socratic warning like quiz."""
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "exam", "title": "Thi cuối kỳ"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "KHÔNG" in result

    def test_format_with_quiz_attempts_and_last_answer(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "quiz", "title": "Test"},
            user_state={
                "quiz_attempts": 2,
                "last_answer": "Tàu B",
                "is_correct": False,
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Lần thử: 2" in result
        assert "Tàu B" in result
        assert "Sai" in result

    def test_format_with_chapter(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={
                "type": "lesson",
                "title": "Rule 14",
                "metadata": {
                    "course_name": "Hàng hải",
                    "chapter_name": "Chương 3",
                },
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Chương 3" in result

    def test_format_with_progress(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "lesson", "title": "Test"},
            user_state={"progress_percent": 60},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "60" in result

    def test_get_page_skill_ids_lesson(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "lesson", "title": "X"},
        )
        assert adapter.get_page_skill_ids(ctx) == ["lms-lesson"]

    def test_get_page_skill_ids_quiz(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "quiz", "title": "X"},
        )
        assert adapter.get_page_skill_ids(ctx) == ["lms-quiz"]

    def test_get_page_skill_ids_unknown_page_type(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "forum", "title": "X"},
        )
        assert adapter.get_page_skill_ids(ctx) == ["lms-default"]

    def test_format_dashboard_page(self):
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "dashboard", "title": "Trang chủ"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Trang chủ" in result

    def test_format_minimal_page(self):
        """Minimal page with no metadata, content, state, or actions."""
        from app.engine.context.adapters.lms import LMSHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = LMSHostAdapter()
        ctx = HostContext(
            host_type="lms",
            page={"type": "lesson", "title": "Minimal"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "<host_context" in result
        assert "</host_context>" in result
        assert "Minimal" in result


class TestGenericHostAdapter:
    def test_format_unknown_host_type(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="custom_app",
            page={"type": "dashboard", "title": "My Dashboard"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "<host_context" in result
        assert "My Dashboard" in result

    def test_format_ecommerce(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="ecommerce",
            page={"type": "product", "title": "Máy Bơm"},
            content={"snippet": "Máy bơm nước chất lượng cao"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "ecommerce" in result
        assert "Máy bơm" in result

    def test_format_with_user_state(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="crm",
            page={"type": "contact", "title": "Contact"},
            user_state={"tab": "notes", "filter": "active"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "notes" in result
        assert "active" in result

    def test_format_with_actions(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="custom",
            page={"type": "list", "title": "Items"},
            available_actions=[{"action": "refresh", "label": "Refresh"}],
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Refresh" in result

    def test_format_minimal(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="trading",
            page={"type": "chart", "title": "BTC/USDT"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "<host_context" in result
        assert "</host_context>" in result
        assert "BTC/USDT" in result

    def test_host_type_preserved_in_output(self):
        """The generic adapter should include the actual host_type, not 'generic'."""
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="my_special_app",
            page={"type": "home", "title": "Home"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert 'type="my_special_app"' in result

    def test_get_page_skill_ids_returns_empty(self):
        from app.engine.context.adapters.generic import GenericHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = GenericHostAdapter()
        ctx = HostContext(
            host_type="custom",
            page={"type": "any", "title": "Any"},
        )
        assert adapter.get_page_skill_ids(ctx) == []

    def test_validate_action_returns_true(self):
        from app.engine.context.adapters.generic import GenericHostAdapter

        adapter = GenericHostAdapter()
        assert adapter.validate_action("navigate", {}, "student") is True


class TestAdapterRegistry:
    def setup_method(self):
        """Clear lru_cache between tests to avoid cross-test pollution."""
        from app.engine.context.adapters import get_host_adapter, _adapters

        get_host_adapter.cache_clear()
        _adapters.clear()

    def test_get_lms_adapter(self):
        from app.engine.context.adapters import get_host_adapter

        adapter = get_host_adapter("lms")
        assert adapter.host_type == "lms"

    def test_get_unknown_returns_generic(self):
        from app.engine.context.adapters import get_host_adapter

        adapter = get_host_adapter("unknown_app_xyz")
        assert adapter.host_type == "generic"

    def test_get_adapter_is_cached(self):
        from app.engine.context.adapters import get_host_adapter

        a1 = get_host_adapter("lms")
        a2 = get_host_adapter("lms")
        assert a1 is a2

    def test_register_custom_adapter(self):
        from app.engine.context.adapters import (
            get_host_adapter,
            register_host_adapter,
        )
        from app.engine.context.adapters.base import HostAdapter
        from app.engine.context.host_context import HostContext

        class CustomAdapter(HostAdapter):
            host_type = "my_custom"

            def format_context_for_prompt(self, ctx: HostContext) -> str:
                return "<custom/>"

        register_host_adapter(CustomAdapter())
        adapter = get_host_adapter("my_custom")
        assert adapter.host_type == "my_custom"

    def test_generic_adapter_for_various_unknown_types(self):
        from app.engine.context.adapters import get_host_adapter

        for host_type in ["trading", "crm", "helpdesk", "portal"]:
            adapter = get_host_adapter(host_type)
            assert adapter.host_type == "generic"


# ─────────────────────────────────────────────────────────────────────────
# Phase F2 (2026-05-06) — Wiii Desktop / Wiii Web standalone adapters.
# ─────────────────────────────────────────────────────────────────────────


class TestWiiiDesktopHostAdapter:
    def test_resolves_for_wiii_desktop_host_type(self):
        from app.engine.context.adapters import get_host_adapter
        from app.engine.context.adapters.wiii_desktop import WiiiDesktopHostAdapter

        adapter = get_host_adapter("wiii-desktop")
        assert isinstance(adapter, WiiiDesktopHostAdapter)

    def test_resolves_for_wiii_web_host_type(self):
        from app.engine.context.adapters import get_host_adapter
        from app.engine.context.adapters.wiii_desktop import WiiiWebHostAdapter

        adapter = get_host_adapter("wiii-web")
        assert isinstance(adapter, WiiiWebHostAdapter)

    def test_format_includes_anti_lms_hallucination_guardrail(self):
        from app.engine.context.adapters.wiii_desktop import WiiiDesktopHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = WiiiDesktopHostAdapter()
        ctx = HostContext(
            host_type="wiii-desktop",
            page={
                "type": "chat",
                "title": "Wiii — Trợ Lý",
                "url": "http://localhost:1420/",
                "metadata": {
                    "is_standalone": True,
                    "is_embedded": False,
                    "hostname": "localhost",
                },
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Wiii Desktop" in result
        assert "KHÔNG phải LMS" in result
        # Anti-hallucination guardrail explicitly bans the canned phrases.
        assert "panel Wiii" in result
        assert "trang LMS" in result

    def test_pointy_hint_lists_available_target_ids(self):
        from app.engine.context.adapters.wiii_desktop import WiiiDesktopHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = WiiiDesktopHostAdapter()
        ctx = HostContext(
            host_type="wiii-desktop",
            page={
                "type": "chat",
                "title": "Wiii",
                "metadata": {
                    "available_targets": [
                        {"id": "chat-send-button", "label": "Gửi"},
                        {"id": "settings-link", "label": "Cài đặt"},
                    ],
                },
            },
        )
        result = adapter.format_context_for_prompt(ctx)
        # v5.0 (2026-05-06): body schema language replaces tool/tag-only
        # framing. Cursor IS Wiii's body. Frontend parses response with
        # hybrid tag fast-path + embodied (intent + label) fallback.
        assert "body_schema" in result
        assert "Cursor" in result and "body" in result
        assert "[POINT:" in result  # tag fast-path still documented
        assert "chat-send-button" in result
        assert "settings-link" in result
        assert "exact-id" in result
        assert "auto:" in result
        # Route discipline prevents tag-vs-tool conflicts.
        assert "Route discipline" in result
        assert "tool_pointy_show" in result

    def test_pointy_hint_omitted_when_no_targets(self):
        from app.engine.context.adapters.wiii_desktop import WiiiDesktopHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = WiiiDesktopHostAdapter()
        ctx = HostContext(
            host_type="wiii-desktop",
            page={"type": "chat", "metadata": {}},
        )
        result = adapter.format_context_for_prompt(ctx)
        # No targets → no body schema instructions surfaced.
        assert "body_schema" not in result
        assert "[POINT:" not in result

    def test_wiii_web_adapter_says_wiii_web_not_desktop(self):
        from app.engine.context.adapters.wiii_desktop import WiiiWebHostAdapter
        from app.engine.context.host_context import HostContext

        adapter = WiiiWebHostAdapter()
        ctx = HostContext(
            host_type="wiii-web",
            page={"type": "chat", "title": "Wiii Web", "url": "https://wiii.holilihu.online/"},
        )
        result = adapter.format_context_for_prompt(ctx)
        assert "Wiii Web" in result
        assert "Wiii Desktop" not in result.replace("Wiii Web", "")  # only Wiii Web mentioned

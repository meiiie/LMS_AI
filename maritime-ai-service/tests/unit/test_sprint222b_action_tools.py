"""Sprint 222b Phase 5: Dynamic tool generation from host capabilities."""
import json


class TestGenerateHostActionTools:
    def test_generates_tools_for_role(self):
        from app.engine.context.action_tools import generate_host_action_tools
        capabilities_tools = [
            {"name": "create_course", "description": "Create a new course",
             "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
             "roles": ["teacher", "admin"]},
            {"name": "view_grades", "description": "View student grades",
             "roles": ["student", "teacher", "admin"]},
        ]
        tools = generate_host_action_tools(capabilities_tools, "student", event_bus_id="bus-1")
        assert len(tools) == 1
        assert tools[0].name == "host_action__view_grades"

    def test_generates_all_for_admin(self):
        from app.engine.context.action_tools import generate_host_action_tools
        capabilities_tools = [
            {"name": "create_course", "description": "Create", "roles": ["teacher", "admin"]},
            {"name": "view_grades", "description": "View", "roles": ["student", "teacher", "admin"]},
        ]
        tools = generate_host_action_tools(capabilities_tools, "admin", event_bus_id="bus-1")
        assert len(tools) == 2

    def test_tool_name_prefix(self):
        from app.engine.context.action_tools import generate_host_action_tools
        tools = generate_host_action_tools(
            [{"name": "navigate", "description": "Navigate to page"}],
            "student", event_bus_id="bus-1",
        )
        assert tools[0].name == "host_action__navigate"

    def test_tool_is_callable(self):
        from app.engine.context.action_tools import generate_host_action_tools
        tools = generate_host_action_tools(
            [{"name": "navigate", "description": "Go to page",
              "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}}],
            "student", event_bus_id="bus-1",
        )
        result = tools[0].invoke({"url": "/course/123"})
        assert "navigate" in str(result).lower() or "req-" in str(result)

    def test_tool_schema_preserves_required_fields_and_rejects_blank_required_input(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "wiii_connect.facebook_post.direct_apply",
                    "description": "Publish a Facebook post",
                    "input_schema": {
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {"type": "string"},
                            "provider_slug": {"type": "string", "default": "facebook"},
                        },
                    },
                }
            ],
            "student",
            event_bus_id="bus-1",
        )

        schema = tools[0].to_openai_schema()["function"]["parameters"]
        result = json.loads(tools[0].invoke({"message": "   "}))

        assert schema["required"] == ["message"]
        assert result["status"] == "validation_failed"
        assert result["missing_fields"] == ["message"]

    def test_empty_capabilities_returns_empty(self):
        from app.engine.context.action_tools import generate_host_action_tools
        tools = generate_host_action_tools([], "admin", event_bus_id="bus-1")
        assert tools == []

    def test_no_roles_means_all_allowed(self):
        from app.engine.context.action_tools import generate_host_action_tools
        tools = generate_host_action_tools(
            [{"name": "open_help", "description": "Open help panel"}],
            "student", event_bus_id="bus-1",
        )
        assert len(tools) == 1

    def test_dotted_action_names_are_sanitized(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.generate_lesson",
                    "description": "Open lesson generation flow",
                    "roles": ["teacher"],
                }
            ],
            "teacher",
            event_bus_id="bus-1",
        )
        assert len(tools) == 1
        assert tools[0].name == "host_action__authoring__generate_lesson"
        assert "authoring.generate_lesson" in tools[0].description

    def test_mutating_action_requires_explicit_confirmation(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_lesson_patch",
                    "description": "Apply lesson preview",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={"query": "preview xong roi", "host_action_feedback": {}},
        )

        result = tools[0].invoke({})
        assert '"status": "approval_required"' in result
        assert "authoring.apply_lesson_patch" in result

    def test_mutating_action_requires_matching_preview_before_apply(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_lesson_patch",
                    "description": "Apply lesson preview",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={"query": "dong y ap dung", "host_action_feedback": {}},
        )

        result = tools[0].invoke({})
        assert '"status": "preview_required"' in result
        assert '"expected_preview_kind": "lesson_patch"' in result

    def test_apply_tool_reuses_latest_matching_preview_token_after_confirmation(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "assessment.apply_quiz_commit",
                    "description": "Commit quiz preview",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "dong y, cu lam di",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "assessment.preview_quiz_commit",
                        "success": True,
                        "summary": "Quiz preview ready",
                        "data": {
                            "preview_token": "quiz-preview-123",
                            "preview_kind": "quiz_commit",
                        },
                    }
                },
            },
        )

        result = tools[0].invoke({})
        assert '"status": "action_requested"' in result
        assert '"preview_token": "quiz-preview-123"' in result

    def test_apply_tool_ignores_mismatched_preview_kind(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "publish.apply_quiz",
                    "description": "Publish quiz preview",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "confirm",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "assessment.preview_quiz_commit",
                        "success": True,
                        "summary": "Quiz preview ready",
                        "data": {
                            "preview_token": "quiz-preview-123",
                            "preview_kind": "quiz_commit",
                        },
                    }
                },
            },
        )

        result = tools[0].invoke({})
        assert '"status": "preview_required"' in result
        assert '"expected_preview_kind": "quiz_publish"' in result

    def test_preview_lesson_tool_description_mentions_source_references_schema(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.preview_lesson_patch",
                    "description": "Preview lesson changes",
                    "roles": ["teacher"],
                    "input_schema": {
                        "type": "object",
                        "required": ["lesson_id"],
                        "properties": {
                            "lesson_id": {"type": "string"},
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "source_references": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
        )

        assert (
            "Input fields: lesson_id, title, content, source_references"
            in tools[0].description
        )
        assert "Required: lesson_id" in tools[0].description
        assert "include `source_references`" in tools[0].description

    def test_preview_lesson_tool_passes_source_references_to_host(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.preview_lesson_patch",
                    "description": "Preview lesson changes",
                    "roles": ["teacher"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "lesson_id": {"type": "string"},
                            "source_references": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
        )

        result = json.loads(
            tools[0].invoke(
                {
                    "lesson_id": "lesson-1",
                    "source_references": [
                        {
                            "kind": "chapter",
                            "page_start": 2,
                            "page_end": 3,
                            "excerpt": "Nguon tai lieu",
                        }
                    ],
                }
            )
        )

        assert result["status"] == "action_requested"
        assert result["action"] == "authoring.preview_lesson_patch"
        assert result["params"]["source_references"] == [
            {
                "kind": "chapter",
                "page_start": 2,
                "page_end": 3,
                "excerpt": "Nguon tai lieu",
            }
        ]

    def test_generate_course_from_document_tool_contract_mentions_course_plan(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.generate_course_from_document",
                    "description": "Preview a course plan from an uploaded document",
                    "roles": ["teacher"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "course_id": {"type": "string"},
                            "course_plan": {"type": "object"},
                            "source_references": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
        )

        assert "Input fields: course_id, course_plan, source_references" in tools[0].description
        assert "structured `course_plan`" in tools[0].description
        assert "preview-first" in tools[0].description

    def test_apply_course_plan_requires_matching_preview_token(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_course_plan",
                    "description": "Apply a confirmed course plan",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "preview_token": {"type": "string"},
                            "approval_token": {"type": "string"},
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "đồng ý áp dụng",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "authoring.generate_course_from_document",
                        "data": {
                            "preview_token": "course-preview-1",
                            "approval_token": "course-approval-1",
                            "preview_kind": "course_plan",
                        },
                    }
                },
            },
        )

        result = json.loads(tools[0].invoke({}))

        assert result["status"] == "action_requested"
        assert result["params"]["preview_token"] == "course-preview-1"
        assert result["params"]["approval_token"] == "course-approval-1"

    def test_lms_apply_requires_approval_token_after_preview(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_lesson_patch",
                    "description": "Apply a confirmed lesson patch",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "preview_token": {"type": "string"},
                            "approval_token": {"type": "string"},
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "dong y ap dung",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "authoring.preview_lesson_patch",
                        "data": {
                            "preview_token": "lesson-preview-1",
                            "preview_kind": "lesson_patch",
                        },
                    }
                },
            },
        )

        result = json.loads(tools[0].invoke({}))

        assert result["status"] == "approval_token_required"
        assert result["expected_preview_kind"] == "lesson_patch"

    def test_lms_apply_requires_approval_token_even_if_host_misdeclares_action(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_lesson_patch",
                    "description": "Apply a confirmed lesson patch",
                    "roles": ["teacher"],
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "preview_token": {"type": "string"},
                            "approval_token": {"type": "string"},
                        },
                    },
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "dong y ap dung",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "authoring.preview_lesson_patch",
                        "data": {
                            "preview_token": "lesson-preview-1",
                            "preview_kind": "lesson_patch",
                        },
                    }
                },
            },
        )

        result = json.loads(tools[0].invoke({}))

        assert result["status"] == "approval_token_required"
        assert result["params"]["preview_token"] == "lesson-preview-1"

    def test_lms_apply_requires_confirmation_even_if_host_misdeclares_action(self):
        from app.engine.context.action_tools import generate_host_action_tools

        tools = generate_host_action_tools(
            [
                {
                    "name": "authoring.apply_course_plan",
                    "description": "Apply a confirmed course plan",
                    "roles": ["teacher"],
                }
            ],
            "teacher",
            event_bus_id="bus-1",
            approval_context={
                "query": "course preview looks good",
                "host_action_feedback": {
                    "last_action_result": {
                        "action": "authoring.generate_course_from_document",
                        "data": {
                            "preview_token": "course-preview-1",
                            "approval_token": "course-approval-1",
                            "preview_kind": "course_plan",
                        },
                    }
                },
            },
        )

        result = json.loads(tools[0].invoke({}))

        assert result["status"] == "approval_required"

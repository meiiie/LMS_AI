"""Sprint 222/234: Graph-level host and operator context injection."""

import inspect
from unittest.mock import patch


def test_inject_host_context_empty_when_no_context():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {"context": {}}
    result = _inject_host_context(state)
    assert result == ""


def test_inject_host_context_empty_when_context_missing():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {}
    result = _inject_host_context(state)
    assert result == ""


def test_inject_host_context_from_legacy_page_context():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "page_context": {
                "page_type": "lesson",
                "page_title": "COLREGs Rule 14",
                "course_name": "An toan hang hai",
            }
        }
    }
    result = _inject_host_context(state)
    assert "<host_context" in result
    assert "COLREGs Rule 14" in result
    assert "An toan hang hai" in result


def test_inject_host_context_from_new_schema():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "host_context": {
                "host_type": "ecommerce",
                "page": {"type": "product", "title": "May Bom Shimizu"},
            }
        }
    }
    result = _inject_host_context(state)
    assert "<host_context" in result
    assert "May Bom Shimizu" in result


def test_inject_host_context_populates_host_capabilities_prompt():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "host_context": {
                "host_type": "lms",
                "page": {"type": "course_editor", "title": "Curriculum"},
                "user_role": "teacher",
            },
            "host_capabilities": {
                "host_type": "lms",
                "host_name": "Maritime LMS",
                "resources": ["current-page"],
                "surfaces": ["ai_sidebar"],
                "tools": [
                    {
                        "name": "authoring.generate_lesson",
                        "description": "Generate lesson",
                        "roles": ["teacher"],
                        "requires_confirmation": True,
                        "mutates_state": True,
                    }
                ],
            },
        }
    }

    result = _inject_host_context(state)
    assert "<host_context" in result
    assert "Curriculum" in result
    assert "host_capabilities_prompt" in state
    assert "authoring.generate_lesson" in state["host_capabilities_prompt"]


def test_inject_host_context_uses_turn_role_when_host_role_missing():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "organization_id": "maritime-lms",
        "user_id": "teacher-1",
        "context": {
            "user_role": "teacher",
            "host_context": {
                "host_type": "lms",
                "page": {"type": "course_editor", "title": "Curriculum"},
            },
            "host_capabilities": {
                "host_type": "lms",
                "host_name": "Maritime LMS",
                "resources": ["current-page"],
                "surfaces": ["ai_sidebar"],
                "tools": [
                    {
                        "name": "authoring.preview_lesson_patch",
                        "description": "Preview lesson patch",
                        "roles": ["teacher", "admin"],
                        "permission": "manage:courses",
                        "requires_confirmation": False,
                        "mutates_state": False,
                    }
                ],
            },
        },
    }

    result = _inject_host_context(state)
    assert "<host_context" in result
    assert state["host_context"]["user_role"] == "teacher"
    assert "host_capabilities_prompt" in state
    assert "authoring.preview_lesson_patch" in state["host_capabilities_prompt"]
    assert state["host_capabilities"]["tools"][0]["name"] == "authoring.preview_lesson_patch"


def test_inject_host_context_keeps_legacy_lms_course_author_permission():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "organization_id": "maritime-lms",
        "user_id": "teacher-1",
        "context": {
            "user_role": "teacher",
            "host_context": {
                "host_type": "lms",
                "connector_id": "live-lms-test-course",
                "host_user_id": "teacher-1",
                "page": {"type": "course_editor", "title": "Curriculum"},
            },
            "host_capabilities": {
                "host_type": "lms",
                "host_name": "Maritime LMS",
                "connector_id": "live-lms-test-course",
                "tools": [
                    {
                        "name": "authoring.preview_lesson_patch",
                        "description": "Preview lesson patch",
                        "roles": ["teacher", "admin"],
                        "permission": "course.author",
                        "requires_confirmation": True,
                        "mutates_state": False,
                    }
                ],
            },
        },
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools", "manage:courses"],
    ):
        result = _inject_host_context(state)

    assert "<host_context" in result
    assert "host_capabilities_prompt" in state
    assert [tool["name"] for tool in state["host_capabilities"]["tools"]] == [
        "authoring.preview_lesson_patch"
    ]


def test_inject_host_context_filters_disallowed_capabilities_for_student():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "organization_id": "org-1",
        "user_id": "student-1",
        "context": {
            "host_context": {
                "host_type": "lms",
                "page": {"type": "quiz", "title": "Quiz 1"},
                "user_role": "student",
            },
            "host_capabilities": {
                "host_type": "lms",
                "host_name": "Maritime LMS",
                "resources": ["current-page"],
                "surfaces": ["ai_sidebar"],
                "tools": [
                    {
                        "name": "navigation.go_to",
                        "description": "Navigate",
                        "roles": ["student", "teacher", "admin"],
                        "permission": "use:tools",
                    },
                    {
                        "name": "authoring.apply_lesson_patch",
                        "description": "Apply lesson patch",
                        "roles": ["teacher", "admin"],
                        "permission": "manage:courses",
                        "requires_confirmation": True,
                        "mutates_state": True,
                    },
                ],
            },
        },
    }

    result = _inject_host_context(state)
    assert "<host_context" in result
    assert "navigation.go_to" in state["host_capabilities_prompt"]
    assert "authoring.apply_lesson_patch" not in state["host_capabilities_prompt"]


def test_inject_host_context_new_schema_takes_priority():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "host_context": {
                "host_type": "lms",
                "page": {"type": "quiz", "title": "New Quiz"},
            },
            "page_context": {
                "page_type": "lesson",
                "page_title": "Old Lesson",
            },
        }
    }
    result = _inject_host_context(state)
    assert "New Quiz" in result
    assert "Old Lesson" not in result


def test_inject_host_context_with_quiz_has_socratic():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "page_context": {
                "page_type": "quiz",
                "page_title": "Kiem tra",
                "quiz_question": "Tau nao nhuong?",
            }
        }
    }
    result = _inject_host_context(state)
    assert "KHÔNG" in result


def test_inject_host_context_graceful_on_bad_host_context():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {"context": {"host_context": "not_a_dict"}}
    result = _inject_host_context(state)
    assert isinstance(result, str)


def test_inject_host_context_graceful_on_bad_page_context():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {"context": {"page_context": 12345}}
    result = _inject_host_context(state)
    assert isinstance(result, str)


def test_inject_host_context_lms_host_type_from_legacy():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "page_context": {
                "page_type": "dashboard",
                "page_title": "Trang chu",
            }
        }
    }
    result = _inject_host_context(state)
    assert 'type="lms"' in result


def test_inject_host_context_with_student_state():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "page_context": {
                "page_type": "lesson",
                "page_title": "Bai 1",
            },
            "student_state": {
                "time_on_page_ms": 180000,
                "scroll_percent": 75.0,
            },
        }
    }
    result = _inject_host_context(state)
    assert "3 phút" in result
    assert "75%" in result


def test_inject_host_context_generic_host_type():
    from app.engine.multi_agent.graph import _inject_host_context

    state = {
        "context": {
            "host_context": {
                "host_type": "crm",
                "page": {"type": "contact", "title": "Customer Details"},
            }
        }
    }
    result = _inject_host_context(state)
    assert "<host_context" in result
    assert "Customer Details" in result
    assert 'type="crm"' in result


def test_inject_operator_context_builds_session_prompt():
    from app.engine.multi_agent.graph import _inject_operator_context

    state = {
        "query": "Tao quiz cho bai nay",
        "context": {
            "host_context": {
                "host_type": "lms",
                "page": {"type": "course_editor", "title": "Curriculum"},
                "user_role": "teacher",
                "workflow_stage": "authoring",
                "editable_scope": {
                    "type": "course",
                    "allowed_operations": ["quiz"],
                    "requires_confirmation": True,
                },
            },
            "host_capabilities": {
                "host_type": "lms",
                "resources": ["current-page"],
                "tools": [
                    {
                        "name": "assessment.create_quiz",
                        "description": "Create quiz",
                        "roles": ["teacher"],
                        "requires_confirmation": True,
                        "mutates_state": True,
                    }
                ],
            },
        },
    }

    prompt = _inject_operator_context(state)
    assert "Operator Session V1" in prompt
    assert "assessment.create_quiz" in prompt
    assert "operator_session" in state


def test_inject_operator_context_mentions_preview_confirmation_when_pending():
    from app.engine.multi_agent.graph import _inject_operator_context

    state = {
        "query": "Ok neu preview hop ly thi ap dung cho lesson nay",
        "context": {
            "host_context": {
                "host_type": "lms",
                "page": {"type": "course_editor", "title": "Curriculum"},
                "user_role": "teacher",
                "workflow_stage": "authoring",
            },
            "host_capabilities": {
                "host_type": "lms",
                "resources": ["current-page"],
                "tools": [
                    {
                        "name": "authoring.apply_lesson_patch",
                        "description": "Apply lesson patch",
                        "roles": ["teacher"],
                        "requires_confirmation": True,
                        "mutates_state": True,
                    }
                ],
            },
            "host_action_feedback": {
                "last_action_result": {
                    "action": "authoring.preview_lesson_patch",
                    "success": True,
                    "summary": "Lesson patch preview ready.",
                    "data": {
                        "preview_token": "lesson-preview-123",
                        "preview_kind": "lesson_patch",
                    },
                }
            },
        },
    }

    prompt = _inject_operator_context(state)
    assert "lesson-preview-123" not in prompt
    assert "authoring.apply_lesson_patch" in prompt


def test_streaming_path_has_host_context_injection():
    from app.engine.multi_agent import graph_stream_runtime

    source = inspect.getsource(graph_stream_runtime.build_stream_bootstrap_impl)
    assert "host_context_prompt" in source or "_inject_host_context" in source

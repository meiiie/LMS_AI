"""Sprint 234: Org-aware host capability policy."""

from unittest.mock import patch


def test_student_cannot_access_manage_courses_action():
    from app.engine.context.capability_policy import is_host_action_allowed

    tool = {
        "name": "authoring.apply_lesson_patch",
        "permission": "manage:courses",
        "roles": ["teacher", "admin"],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools"],
    ):
        assert is_host_action_allowed(
            tool,
            user_role="student",
            organization_id="org-1",
            user_id="user-1",
        ) is False


def test_teacher_can_access_manage_courses_action():
    from app.engine.context.capability_policy import is_host_action_allowed

    tool = {
        "name": "authoring.apply_lesson_patch",
        "permission": "manage:courses",
        "roles": ["teacher", "admin"],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools", "manage:courses"],
    ):
        assert is_host_action_allowed(
            tool,
            user_role="teacher",
            organization_id="org-1",
            user_id="teacher-1",
        ) is True


def test_teacher_can_access_legacy_lms_course_author_permission():
    from app.engine.context.capability_policy import is_host_action_allowed

    tool = {
        "name": "authoring.preview_lesson_patch",
        "permission": "course.author",
        "roles": ["teacher", "admin"],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools", "manage:courses"],
    ):
        assert is_host_action_allowed(
            tool,
            user_role="teacher",
            organization_id="org-1",
            user_id="teacher-1",
        ) is True


def test_role_restriction_wins_even_if_permission_exists():
    from app.engine.context.capability_policy import is_host_action_allowed

    tool = {
        "name": "governance.manage_branding",
        "permission": "manage:branding",
        "roles": ["admin"],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["manage:branding", "manage:settings"],
    ):
        assert is_host_action_allowed(
            tool,
            user_role="teacher",
            organization_id="org-1",
            user_id="teacher-1",
        ) is False


def test_org_admin_role_unlocks_governance_permissions_when_granted():
    from app.engine.context.capability_policy import is_host_action_allowed

    tool = {
        "name": "governance.update_org_policy",
        "permission": "manage:org_settings",
        "roles": ["teacher", "admin"],
    }

    with patch(
        "app.engine.context.capability_policy._resolve_org_role",
        return_value="owner",
    ), patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["manage:org_settings", "manage:knowledge"],
    ):
        assert is_host_action_allowed(
            tool,
            user_role="teacher",
            organization_id="org-1",
            user_id="teacher-1",
        ) is True


def test_filter_host_capabilities_removes_disallowed_tools():
    from app.engine.context.capability_policy import filter_host_capabilities_for_org

    caps = {
        "host_type": "lms",
        "tools": [
            {"name": "navigation.go_to", "permission": "use:tools", "roles": ["student", "teacher", "admin"]},
            {"name": "authoring.apply_lesson_patch", "permission": "manage:courses", "roles": ["teacher", "admin"]},
        ],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools"],
    ):
        filtered = filter_host_capabilities_for_org(
            caps,
            user_role="student",
            organization_id="org-1",
            user_id="student-1",
        )

    tool_names = [tool["name"] for tool in filtered["tools"]]
    assert tool_names == ["navigation.go_to"]


def test_filter_host_capabilities_keeps_legacy_lms_authoring_permission():
    from app.engine.context.capability_policy import filter_host_capabilities_for_org

    caps = {
        "host_type": "lms",
        "tools": [
            {
                "name": "authoring.preview_lesson_patch",
                "permission": "course.author",
                "roles": ["teacher", "admin"],
            }
        ],
    }

    with patch(
        "app.engine.context.capability_policy.get_org_permissions",
        return_value=["read:chat", "use:tools", "manage:courses"],
    ):
        filtered = filter_host_capabilities_for_org(
            caps,
            user_role="teacher",
            organization_id="org-1",
            user_id="teacher-1",
        )

    assert [tool["name"] for tool in filtered["tools"]] == [
        "authoring.preview_lesson_patch"
    ]

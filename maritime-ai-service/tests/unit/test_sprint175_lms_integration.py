"""
Sprint 175: "Cắm Phích Cắm" — Wiii x Maritime LMS Integration Tests

Tests all 4 phases:
  Phase 1: Foundation — adapter path config, pull endpoints, router registration
  Phase 2: Student Intelligence — LMS tools, enhanced enrichment, intent detection
  Phase 3: Teacher Dashboard — course overview, at-risk detection, grade distribution
  Phase 4: Push Service — bidirectional insights/alerts to LMS
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Phase 1: Foundation Tests
# =============================================================================


class TestSpringBootAdapterPaths:
    """Test configurable API path prefix (Phase 1.5)."""

    def _make_adapter(self, api_prefix=None):
        from app.integrations.lms.base import LMSBackendType, LMSConnectorConfig
        from app.integrations.lms.connectors.spring_boot import SpringBootLMSAdapter

        extra = {}
        if api_prefix:
            extra["api_prefix"] = api_prefix

        config = LMSConnectorConfig(
            id="test-lms",
            display_name="Test LMS",
            backend_type=LMSBackendType.SPRING_BOOT,
            base_url="http://localhost:8088",
            service_token="test-token",
            extra=extra,
        )
        return SpringBootLMSAdapter(config)

    def test_default_api_prefix(self):
        """Default prefix is api/v3/integration."""
        adapter = self._make_adapter()
        assert adapter._api_prefix == "api/v3/integration"

    def test_custom_api_prefix(self):
        """Custom prefix from config.extra."""
        adapter = self._make_adapter(api_prefix="api/v2/custom")
        assert adapter._api_prefix == "api/v2/custom"

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_student_profile_uses_prefix(self, mock_get):
        """get_student_profile uses configurable prefix."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "s1", "name": "Nguyen Van A", "email": "a@lms.edu",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        profile = adapter.get_student_profile("s1")

        assert profile is not None
        assert profile.name == "Nguyen Van A"
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/students/s1/profile" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_student_grades_uses_prefix(self, mock_get):
        """get_student_grades uses configurable prefix."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"course_id": "NHH101", "course_name": "Navigation", "grade": 8.5, "max_grade": 10},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        grades = adapter.get_student_grades("s1")

        assert len(grades) == 1
        assert grades[0].course_id == "NHH101"
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/students/s1/grades" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_upcoming_assignments_uses_prefix(self, mock_get):
        """get_upcoming_assignments uses configurable prefix."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "assignment_id": "a1", "assignment_name": "Essay",
                "course_id": "NHH101", "due_date": "2026-03-01T23:59:00Z",
            },
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        assignments = adapter.get_upcoming_assignments("s1")

        assert len(assignments) == 1
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/students/s1/assignments/upcoming" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_course_students(self, mock_get):
        """get_course_students calls correct path."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "s1", "name": "Student A"}]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        students = adapter.get_course_students("NHH101")

        assert len(students) == 1
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/courses/NHH101/students" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_course_stats(self, mock_get):
        """get_course_stats calls correct path."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "students_count": 30, "avg_grade": 7.2, "completion_rate": 85,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        stats = adapter.get_course_stats("NHH101")

        assert stats is not None
        assert stats["students_count"] == 30
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/courses/NHH101/stats" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_student_enrollments(self, mock_get):
        """get_student_enrollments calls correct path."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"course_id": "NHH101", "course_name": "Navigation", "semester": "HK1-2026"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        enrollments = adapter.get_student_enrollments("s1")

        assert len(enrollments) == 1
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/students/s1/enrollments" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_student_quiz_history(self, mock_get):
        """get_student_quiz_history calls correct path."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"quiz_id": "q1", "course_id": "NHH101", "score": 8, "max_score": 10},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        adapter = self._make_adapter()
        history = adapter.get_student_quiz_history("s1")

        assert len(history) == 1
        call_url = mock_get.call_args[0][0]
        assert "api/v3/integration/students/s1/quiz-history" in call_url

    @patch("app.integrations.lms.connectors.spring_boot.httpx.get")
    def test_circuit_breaker_on_failure(self, mock_get):
        """Circuit breaker records failures."""
        mock_get.side_effect = Exception("Connection refused")

        adapter = self._make_adapter()
        result = adapter.get_student_profile("s1")

        assert result is None

    def test_invalid_student_id_rejected(self):
        """Student IDs with special chars are rejected."""
        adapter = self._make_adapter()
        with pytest.raises(ValueError):
            adapter.get_student_profile("../etc/passwd")


# =============================================================================
# Phase 1.6: Pull Endpoint Tests
# =============================================================================


class TestLMSDataEndpoints:
    """Test on-demand pull API endpoints."""

    def test_router_has_correct_prefix(self):
        from app.api.v1.lms_data import router
        assert router.prefix == "/lms"

    @pytest.mark.asyncio
    async def test_check_student_access_allows_own_data(self):
        from app.api.v1.lms_data import _check_student_access
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            organization_id="lms-hang-hai",
        )
        with patch("app.api.v1.lms_data.resolve_lms_identity", new=AsyncMock(return_value=("student-1", "maritime-lms"))):
            await _check_student_access(auth, "student-1", connector_id="maritime-lms")

    @pytest.mark.asyncio
    async def test_check_student_access_blocks_other_student(self):
        from app.api.v1.lms_data import _check_student_access
        from fastapi import HTTPException
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            organization_id="lms-hang-hai",
        )
        with patch("app.api.v1.lms_data.resolve_lms_identity", new=AsyncMock(return_value=("student-1", "maritime-lms"))):
            with pytest.raises(HTTPException) as exc_info:
                await _check_student_access(auth, "student-2", connector_id="maritime-lms")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_check_student_access_allows_teacher(self):
        from app.api.v1.lms_data import _check_student_access
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            host_role="teacher",
        )
        await _check_student_access(auth, "student-2", connector_id="maritime-lms")

    @pytest.mark.asyncio
    async def test_check_student_access_allows_admin(self):
        from app.api.v1.lms_data import _check_student_access
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="admin",
            platform_role="platform_admin",
        )
        await _check_student_access(auth, "student-2", connector_id="maritime-lms")

    @pytest.mark.asyncio
    async def test_check_student_access_blocks_connector_mismatch(self):
        from app.api.v1.lms_data import _check_student_access
        from app.core.security import AuthenticatedUser
        from fastapi import HTTPException

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            organization_id="lms-hang-hai",
        )
        with patch("app.api.v1.lms_data.resolve_lms_identity", new=AsyncMock(return_value=("student-1", "other-lms"))):
            with pytest.raises(HTTPException) as exc_info:
                await _check_student_access(auth, "student-1", connector_id="maritime-lms")
        assert exc_info.value.status_code == 403


# =============================================================================
# Phase 2: Student Intelligence Tests
# =============================================================================


class TestLMSTools:
    """Test LMS agent tools."""

    def test_get_lms_student_tools_returns_3(self):
        from app.engine.tools.lms_tools import get_lms_student_tools
        tools = get_lms_student_tools()
        assert len(tools) == 3

    def test_get_lms_teacher_tools_returns_2(self):
        from app.engine.tools.lms_tools import get_lms_teacher_tools
        tools = get_lms_teacher_tools()
        assert len(tools) == 2

    def test_get_all_lms_tools_student_role(self):
        from app.engine.tools.lms_tools import get_all_lms_tools
        tools = get_all_lms_tools(role="student")
        assert len(tools) == 3  # Only student tools

    def test_get_all_lms_tools_teacher_role(self):
        from app.engine.tools.lms_tools import get_all_lms_tools
        tools = get_all_lms_tools(role="teacher")
        assert len(tools) == 5  # Student + teacher tools

    def test_get_all_lms_tools_admin_role(self):
        from app.engine.tools.lms_tools import get_all_lms_tools
        tools = get_all_lms_tools(role="admin")
        assert len(tools) == 5

    def test_tool_names(self):
        from app.engine.tools.lms_tools import get_all_lms_tools
        tools = get_all_lms_tools(role="admin")
        names = [t.name for t in tools]
        assert "tool_check_student_grades" in names
        assert "tool_list_upcoming_assignments" in names
        assert "tool_check_course_progress" in names
        assert "tool_get_class_overview" in names
        assert "tool_find_at_risk_students" in names

    @patch("app.engine.tools.lms_tools._get_connector")
    def test_check_grades_no_connector(self, mock_get):
        """Graceful when no LMS connector configured."""
        mock_get.return_value = None
        from app.engine.tools.lms_tools import tool_check_student_grades
        result = tool_check_student_grades.invoke({"student_id": "s1"})
        assert "Không thể kết nối" in result

    @patch("app.engine.tools.lms_tools._get_connector")
    def test_check_grades_with_data(self, mock_get):
        """Returns formatted grade text."""
        mock_connector = MagicMock()
        from app.integrations.lms.models import LMSGrade
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", course_name="Navigation", grade=8.5, max_grade=10),
            LMSGrade(course_id="NHH102", course_name="COLREG", grade=4.0, max_grade=10),
        ]
        mock_get.return_value = mock_connector

        from app.engine.tools.lms_tools import tool_check_student_grades
        result = tool_check_student_grades.invoke({"student_id": "s1"})

        assert "Navigation" in result
        assert "8.5/10" in result
        assert "COLREG" in result
        assert "Điểm trung bình" in result

    @patch("app.engine.tools.lms_tools._get_connector")
    def test_list_assignments_empty(self, mock_get):
        mock_connector = MagicMock()
        mock_connector.get_upcoming_assignments.return_value = []
        mock_get.return_value = mock_connector

        from app.engine.tools.lms_tools import tool_list_upcoming_assignments
        result = tool_list_upcoming_assignments.invoke({"student_id": "s1"})
        assert "Không có bài tập" in result

    @patch("app.engine.tools.lms_tools._get_connector")
    def test_class_overview_no_connector(self, mock_get):
        mock_get.return_value = None
        from app.engine.tools.lms_tools import tool_get_class_overview
        result = tool_get_class_overview.invoke({"course_id": "NHH101"})
        assert "Không thể kết nối" in result

    @patch("app.engine.tools.lms_tools._get_connector")
    def test_class_overview_with_stats(self, mock_get):
        mock_connector = MagicMock()
        mock_connector.get_course_stats.return_value = {
            "students_count": 30, "avg_grade": 7.2,
            "completion_rate": 85, "active_last_7d": 25, "at_risk_count": 3,
        }
        mock_get.return_value = mock_connector

        from app.engine.tools.lms_tools import tool_get_class_overview
        result = tool_get_class_overview.invoke({"course_id": "NHH101"})

        assert "30" in result
        assert "7.2" in result
        assert "85" in result

    def test_register_lms_tools(self):
        """Registration doesn't crash."""
        from app.engine.tools.lms_tools import register_lms_tools
        register_lms_tools()


class TestEnhancedEnrichment:
    """Test enhanced enrichment pipeline (Phase 2.1)."""

    @pytest.mark.asyncio
    async def test_grade_creates_course_context_fact(self):
        """Sprint 175: enrich_from_grade now creates course_context fact."""
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import GradeSavedPayload

        service = LMSEnrichmentService()

        with patch.object(service, "_save_fact", new_callable=AsyncMock, return_value=True):
            payload = GradeSavedPayload(
                student_id="s1", course_id="NHH101",
                course_name="Navigation", grade=7.5, max_grade=10,
            )
            count = await service.enrich_from_grade(payload, source_lms_id="test")

            # LEVEL + course_context = 2 (grade is 75%, no weakness or strength)
            assert count == 2

    @pytest.mark.asyncio
    async def test_grade_low_creates_weakness_and_context(self):
        """Low grade creates LEVEL + WEAKNESS + course_context."""
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import GradeSavedPayload

        service = LMSEnrichmentService()

        with patch.object(service, "_save_fact", new_callable=AsyncMock, return_value=True):
            payload = GradeSavedPayload(
                student_id="s1", course_id="NHH101",
                course_name="Navigation", grade=4.0, max_grade=10,
            )
            count = await service.enrich_from_grade(payload, source_lms_id="test")
            assert count == 3  # LEVEL + WEAKNESS + course_context

    @pytest.mark.asyncio
    async def test_grade_high_creates_strength_and_context(self):
        """High grade creates LEVEL + STRENGTH + course_context."""
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import GradeSavedPayload

        service = LMSEnrichmentService()

        with patch.object(service, "_save_fact", new_callable=AsyncMock, return_value=True):
            payload = GradeSavedPayload(
                student_id="s1", course_id="NHH101",
                course_name="Navigation", grade=9.0, max_grade=10,
            )
            count = await service.enrich_from_grade(payload, source_lms_id="test")
            assert count == 3  # LEVEL + STRENGTH + course_context

    @pytest.mark.asyncio
    async def test_attendance_absent_creates_fact(self):
        """Sprint 175: Attendance now tracks absences."""
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import AttendanceMarkedPayload

        service = LMSEnrichmentService()

        with patch.object(service, "_save_fact", new_callable=AsyncMock, return_value=True):
            payload = AttendanceMarkedPayload(
                student_id="s1", course_id="NHH101",
                course_name="Navigation", date="2026-02-20", status="absent",
            )
            count = await service.enrich_from_attendance(payload)
            assert count == 1

    @pytest.mark.asyncio
    async def test_attendance_late_creates_fact(self):
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import AttendanceMarkedPayload

        service = LMSEnrichmentService()

        with patch.object(service, "_save_fact", new_callable=AsyncMock, return_value=True):
            payload = AttendanceMarkedPayload(
                student_id="s1", course_id="NHH101",
                course_name="Navigation", date="2026-02-20", status="late",
            )
            count = await service.enrich_from_attendance(payload)
            assert count == 1

    @pytest.mark.asyncio
    async def test_attendance_present_no_fact(self):
        """Present attendance still skipped (not noisy signal)."""
        from app.integrations.lms.enrichment import LMSEnrichmentService
        from app.integrations.lms.models import AttendanceMarkedPayload

        service = LMSEnrichmentService()

        payload = AttendanceMarkedPayload(
            student_id="s1", course_id="NHH101",
            course_name="Navigation", date="2026-02-20", status="present",
        )
        count = await service.enrich_from_attendance(payload)
        assert count == 0


class TestLMSIntentDetection:
    """Test LMS intent detection in graph."""

    def test_lms_intent_keywords_exist(self):
        from app.engine.multi_agent.graph import _LMS_INTENT_KEYWORDS
        assert len(_LMS_INTENT_KEYWORDS) > 10

    @patch("app.core.config.settings")
    def test_needs_lms_query_enabled(self, mock_settings):
        mock_settings.enable_lms_integration = True
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Điểm của tôi thế nào?") is True

    @patch("app.core.config.settings")
    def test_needs_lms_query_disabled(self, mock_settings):
        mock_settings.enable_lms_integration = False
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Điểm của tôi thế nào?") is False

    @patch("app.core.config.settings")
    def test_needs_lms_query_assignment(self, mock_settings):
        mock_settings.enable_lms_integration = True
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Bài tập sắp đến hạn?") is True

    @patch("app.core.config.settings")
    def test_needs_lms_query_unrelated(self, mock_settings):
        mock_settings.enable_lms_integration = True
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Nấu cơm thế nào?") is False


class TestLMSIntentDetectionEdgeCases:
    @patch("app.core.config.settings")
    def test_needs_lms_query_does_not_treat_plain_quiz_generation_as_lms(self, mock_settings):
        mock_settings.enable_lms_integration = True
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Tao cho minh quiz 30 cau tieng Trung de luyen tap") is False

    @patch("app.core.config.settings")
    def test_needs_lms_query_keeps_quiz_with_grade_context(self, mock_settings):
        mock_settings.enable_lms_integration = True
        from app.engine.multi_agent.graph import _needs_lms_query
        assert _needs_lms_query("Diem quiz cua minh trong khoa hoc nay la bao nhieu?") is True


# =============================================================================
# Phase 3: Teacher Dashboard Tests
# =============================================================================


class TestRiskAnalyzer:
    """Test at-risk student detection."""

    @pytest.mark.asyncio
    async def test_no_connector_returns_unknown(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=None)
        assert result["level"] == "unknown"

    @pytest.mark.asyncio
    async def test_low_grades_high_risk(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        from app.integrations.lms.models import LMSGrade

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", grade=3.0, max_grade=10),
        ]
        mock_connector.get_upcoming_assignments.return_value = []
        mock_connector.get_student_quiz_history.return_value = []

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert result["score"] > 0.3
        assert any("thấp" in f.lower() or "cải thiện" in f.lower() for f in result["factors"])

    @pytest.mark.asyncio
    async def test_good_grades_low_risk(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        from app.integrations.lms.models import LMSGrade

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", grade=8.5, max_grade=10),
        ]
        mock_connector.get_upcoming_assignments.return_value = []
        mock_connector.get_student_quiz_history.return_value = []

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert result["level"] == "low"

    @pytest.mark.asyncio
    async def test_declining_grades_detected(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        from app.integrations.lms.models import LMSGrade

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", grade=8.0, max_grade=10),
            LMSGrade(course_id="NHH101", grade=5.0, max_grade=10),  # Decline
        ]
        mock_connector.get_upcoming_assignments.return_value = []
        mock_connector.get_student_quiz_history.return_value = []

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert any("giảm" in f.lower() for f in result["factors"])

    @pytest.mark.asyncio
    async def test_many_assignments_increases_risk(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        from app.integrations.lms.models import LMSGrade, LMSUpcomingAssignment

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", grade=7.0, max_grade=10),
        ]
        mock_connector.get_upcoming_assignments.return_value = [
            LMSUpcomingAssignment(
                assignment_id=f"a{i}", assignment_name=f"Bài {i}",
                course_id="NHH101", due_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
            for i in range(6)
        ]
        mock_connector.get_student_quiz_history.return_value = []

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert any("bài tập" in f.lower() for f in result["factors"])

    @pytest.mark.asyncio
    async def test_low_quiz_scores_increases_risk(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer
        from app.integrations.lms.models import LMSGrade

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = [
            LMSGrade(course_id="NHH101", grade=6.0, max_grade=10),
        ]
        mock_connector.get_upcoming_assignments.return_value = []
        mock_connector.get_student_quiz_history.return_value = [
            {"quiz_id": "q1", "course_id": "NHH101", "score": 3, "max_score": 10},
        ]

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert any("kiểm tra" in f.lower() for f in result["factors"])

    @pytest.mark.asyncio
    async def test_no_grades_mild_concern(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer

        mock_connector = MagicMock()
        mock_connector.get_student_grades.return_value = []
        mock_connector.get_upcoming_assignments.return_value = []
        mock_connector.get_student_quiz_history.return_value = []

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert result["score"] > 0  # Some concern for no data

    @pytest.mark.asyncio
    async def test_error_returns_unknown(self):
        from app.services.risk_analyzer import StudentRiskAnalyzer

        mock_connector = MagicMock()
        mock_connector.get_student_grades.side_effect = Exception("DB error")

        analyzer = StudentRiskAnalyzer()
        result = await analyzer.analyze("s1", "NHH101", connector=mock_connector)

        assert result["level"] == "unknown"


class TestDashboardEndpoints:
    """Test dashboard router registration and structure."""

    def test_dashboard_router_has_correct_prefix(self):
        from app.api.v1.lms_dashboard import router
        assert router.prefix == "/lms/dashboard"

    def test_require_teacher_allows_teacher(self):
        from app.api.v1.lms_dashboard import _require_teacher_or_admin
        _require_teacher_or_admin("teacher")  # Should not raise

    def test_require_teacher_allows_admin(self):
        from app.api.v1.lms_dashboard import _require_teacher_or_admin
        _require_teacher_or_admin("admin")  # Should not raise

    def test_require_teacher_blocks_student(self):
        from app.api.v1.lms_dashboard import _require_teacher_or_admin
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _require_teacher_or_admin("student")
        assert exc_info.value.status_code == 403

    def test_require_teacher_allows_host_org_admin(self):
        from app.api.v1.lms_dashboard import _require_teacher_or_admin
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            host_role="org_admin",
        )
        _require_teacher_or_admin(auth)

    def test_require_org_overview_allows_wiii_org_admin(self):
        from app.api.v1.lms_dashboard import _require_org_overview_access
        from app.core.security import AuthenticatedUser

        auth = AuthenticatedUser(
            user_id="wiii-user-1",
            auth_method="jwt",
            role="student",
            organization_role="admin",
        )
        _require_org_overview_access(auth)


# =============================================================================
# Phase 4: Push Service Tests
# =============================================================================


class TestPushService:
    """Test bidirectional Wiii → LMS push."""

    def _make_push_service(self):
        from app.integrations.lms.base import LMSBackendType, LMSConnectorConfig
        from app.integrations.lms.push_service import LMSPushService

        config = LMSConnectorConfig(
            id="test-lms",
            display_name="Test LMS",
            backend_type=LMSBackendType.SPRING_BOOT,
            base_url="http://localhost:8088",
            service_token="test-token",
            webhook_secret="test-secret",
        )
        return LMSPushService(config)

    def test_sign_payload(self):
        """HMAC signature is created correctly."""
        service = self._make_push_service()
        payload = b'{"test": "data"}'
        sig = service._sign_payload(payload)
        assert sig.startswith("sha256=")
        assert len(sig) > 10

    def test_sign_payload_no_secret(self):
        """No signature when no secret configured."""
        from app.integrations.lms.base import LMSBackendType, LMSConnectorConfig
        from app.integrations.lms.push_service import LMSPushService

        config = LMSConnectorConfig(
            id="test", display_name="Test",
            backend_type=LMSBackendType.SPRING_BOOT,
            base_url="http://localhost:8088",
        )
        service = LMSPushService(config)
        sig = service._sign_payload(b"data")
        assert sig == ""

    @patch("app.integrations.lms.push_service.httpx.post")
    def test_push_student_insight_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        service = self._make_push_service()
        result = service.push_student_insight(
            student_id="s1",
            insight_type="recommendation",
            content="Nên ôn tập COLREG Rule 13",
        )

        assert result is True
        call_kwargs = mock_post.call_args
        assert "insights" in call_kwargs[0][0]

    @patch("app.integrations.lms.push_service.httpx.post")
    def test_push_student_insight_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        service = self._make_push_service()
        result = service.push_student_insight(
            student_id="s1", insight_type="alert", content="Test",
        )

        assert result is False

    @patch("app.integrations.lms.push_service.httpx.post")
    def test_push_class_alert_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        service = self._make_push_service()
        result = service.push_class_alert(
            course_id="NHH101",
            alert_type="at_risk_student",
            content="3 sinh viên cần hỗ trợ",
            student_ids=["s1", "s2", "s3"],
        )

        assert result is True

    def test_push_no_base_url(self):
        """Graceful when no base_url configured."""
        from app.integrations.lms.base import LMSBackendType, LMSConnectorConfig
        from app.integrations.lms.push_service import LMSPushService

        config = LMSConnectorConfig(
            id="test", display_name="Test",
            backend_type=LMSBackendType.SPRING_BOOT,
        )
        service = LMSPushService(config)
        result = service.push_student_insight("s1", "alert", "test")
        assert result is False

    @patch("app.integrations.lms.push_service.httpx.post")
    def test_push_includes_hmac_header(self, mock_post):
        """Push requests include HMAC signature header."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        service = self._make_push_service()
        service.push_student_insight("s1", "recommendation", "Test")

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "X-Wiii-Signature" in headers

    def test_get_push_service_no_connector(self):
        from app.integrations.lms.push_service import get_push_service
        # Clear registry
        from app.integrations.lms.registry import get_lms_connector_registry
        registry = get_lms_connector_registry()
        original = dict(registry._connectors)
        registry._connectors.clear()

        result = get_push_service("nonexistent")
        assert result is None

        # Restore
        registry._connectors.update(original)


# =============================================================================
# Router Registration Tests
# =============================================================================


class TestRouterRegistration:
    """Test that new routers are properly registered in __init__.py."""

    def test_lms_data_router_importable(self):
        from app.api.v1.lms_data import router
        assert router is not None

    def test_lms_dashboard_router_importable(self):
        from app.api.v1.lms_dashboard import router
        assert router is not None

    def test_lms_data_endpoints_exist(self):
        from app.api.v1.lms_data import router
        paths = [getattr(route, "path", "") for route in router.routes]
        assert "/lms/students/{student_id}/profile" in paths
        assert "/lms/students/{student_id}/grades" in paths
        assert "/lms/students/{student_id}/enrollments" in paths
        assert "/lms/students/{student_id}/assignments" in paths
        assert "/lms/students/{student_id}/quiz-history" in paths

    def test_lms_dashboard_endpoints_exist(self):
        from app.api.v1.lms_dashboard import router
        paths = [getattr(route, "path", "") for route in router.routes]
        assert "/lms/dashboard/courses/{course_id}/overview" in paths
        assert "/lms/dashboard/courses/{course_id}/at-risk" in paths
        assert "/lms/dashboard/courses/{course_id}/grade-distribution" in paths
        assert "/lms/dashboard/courses/{course_id}/ai-report" in paths
        assert "/lms/dashboard/org/overview" in paths


# =============================================================================
# ABC Extension Tests
# =============================================================================


class TestBaseClassExtension:
    """Test ABC has new methods with safe defaults."""

    def test_base_has_get_student_enrollments(self):
        from app.integrations.lms.base import LMSConnectorAdapter
        assert hasattr(LMSConnectorAdapter, "get_student_enrollments")

    def test_base_has_get_student_quiz_history(self):
        from app.integrations.lms.base import LMSConnectorAdapter
        assert hasattr(LMSConnectorAdapter, "get_student_quiz_history")

    def test_base_has_get_course_students(self):
        from app.integrations.lms.base import LMSConnectorAdapter
        assert hasattr(LMSConnectorAdapter, "get_course_students")

    def test_base_has_get_course_stats(self):
        from app.integrations.lms.base import LMSConnectorAdapter
        assert hasattr(LMSConnectorAdapter, "get_course_stats")

    def test_base_default_returns_empty(self):
        """Base class defaults return empty results (not errors)."""
        from app.integrations.lms.base import LMSConnectorAdapter

        # Create a minimal concrete implementation
        class MinimalAdapter(LMSConnectorAdapter):
            def get_config(self):
                return None
            def normalize_webhook(self, raw_payload, headers):
                return None

        adapter = MinimalAdapter()
        assert adapter.get_student_enrollments("s1") == []
        assert adapter.get_student_quiz_history("s1") == []
        assert adapter.get_course_students("c1") == []
        assert adapter.get_course_stats("c1") is None

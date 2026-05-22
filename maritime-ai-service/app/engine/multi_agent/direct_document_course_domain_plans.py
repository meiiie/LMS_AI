"""Compatibility exports for uploaded-document course plan builders."""

from __future__ import annotations

from app.engine.multi_agent.direct_document_course_lms_plan import (
    _build_lms_manual_course_plan as _build_lms_manual_course_plan,
    _lms_manual_lesson as _lms_manual_lesson,
)
from app.engine.multi_agent.direct_document_course_maritime_plans import (
    _build_maritime_training_lms_course_plan as _build_maritime_training_lms_course_plan,
    _build_maritime_vessel_management_course_plan as _build_maritime_vessel_management_course_plan,
)

__all__ = [
    "_build_lms_manual_course_plan",
    "_build_maritime_training_lms_course_plan",
    "_build_maritime_vessel_management_course_plan",
    "_lms_manual_lesson",
]

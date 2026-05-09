"""Tests for the operator-facing LLM model health endpoint helpers."""

import pytest


@pytest.fixture(autouse=True)
def reset_model_health():
    from app.engine.llm_model_health import reset_model_health_state

    reset_model_health_state()
    yield
    reset_model_health_state()


def test_llm_model_health_report_redacts_raw_error_detail():
    from app.api.v1.health import _build_llm_model_health_report
    from app.engine.llm_model_health import record_model_failure

    record_model_failure(
        "nvidia",
        "deepseek-ai/deepseek-v4-flash",
        reason_code="timeout",
        error=RuntimeError("provider payload containing should-not-leak"),
        timeout_seconds=8.0,
    )

    report = _build_llm_model_health_report()

    assert report["status"] == "degraded"
    assert report["model_count"] == 1
    assert report["healthy_count"] == 0
    assert report["degraded_count"] == 1
    assert report["models"][0]["provider"] == "nvidia"
    assert report["models"][0]["model"] == "deepseek-ai/deepseek-v4-flash"
    assert report["models"][0]["state"] == "degraded"
    assert "last_error_detail" not in report["models"][0]
    assert "should-not-leak" not in str(report)


@pytest.mark.asyncio
async def test_check_llm_model_health_reports_degraded_component_when_all_known_models_degraded():
    from app.api.v1.health import check_llm_model_health
    from app.engine.llm_model_health import record_model_failure
    from app.models.schemas import ComponentStatus

    record_model_failure(
        "nvidia",
        "deepseek-ai/deepseek-v4-pro",
        reason_code="rate_limit",
    )

    component = await check_llm_model_health()

    assert component.name == "LLM Model Health"
    assert component.status is ComponentStatus.DEGRADED
    assert component.message == "All 1 model(s) degraded"


@pytest.mark.asyncio
async def test_check_llm_model_health_keeps_component_healthy_for_partial_degradation():
    from app.api.v1.health import _build_llm_model_health_report, check_llm_model_health
    from app.engine.llm_model_health import record_model_failure, record_model_success
    from app.models.schemas import ComponentStatus

    record_model_failure(
        "nvidia",
        "deepseek-ai/deepseek-v4-flash",
        reason_code="timeout",
        timeout_seconds=8.0,
    )
    record_model_success("nvidia", "deepseek-ai/deepseek-v4-pro")

    report = _build_llm_model_health_report()
    component = await check_llm_model_health()

    assert report["status"] == "healthy"
    assert report["model_count"] == 2
    assert report["healthy_count"] == 1
    assert report["degraded_count"] == 1
    assert component.status is ComponentStatus.HEALTHY
    assert component.message == (
        "1/2 model(s) degraded; 1 model(s) healthy for routing"
    )


@pytest.mark.asyncio
async def test_check_llm_model_health_is_healthy_before_probe_records():
    from app.api.v1.health import check_llm_model_health
    from app.models.schemas import ComponentStatus

    component = await check_llm_model_health()

    assert component.status is ComponentStatus.HEALTHY
    assert component.message == "No model health records yet"

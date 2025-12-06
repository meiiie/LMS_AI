"""
Property-Based Tests for Health Check Completeness
**Feature: maritime-ai-tutor, Property 21: Health Check Completeness**
**Validates: Requirements 8.4**

Tests that health check response includes status for all components: API, Memory, Knowledge_Graph.
"""
import sys

import pytest
from hypothesis import given, settings, strategies as st

# Add app to path
sys.path.insert(0, str(__file__).replace("tests/property/test_health_properties.py", ""))

from app.models.schemas import ComponentHealth, ComponentStatus, HealthResponse


# Required components that must be present in health check
REQUIRED_COMPONENTS = {"api", "memory", "knowledge_graph"}


# =============================================================================
# Custom Strategies
# =============================================================================

component_status_strategy = st.sampled_from(list(ComponentStatus))

component_health_strategy = st.builds(
    ComponentHealth,
    name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
    status=component_status_strategy,
    latency_ms=st.one_of(st.none(), st.floats(min_value=0, max_value=10000, allow_nan=False)),
    message=st.one_of(st.none(), st.text(max_size=200)),
)


# =============================================================================
# Property Tests
# =============================================================================

class TestHealthCheckCompleteness:
    """
    **Feature: maritime-ai-tutor, Property 21: Health Check Completeness**
    **Validates: Requirements 8.4**
    
    For any health check request, the response SHALL include status 
    for all components: API, Memory, Knowledge_Graph.
    """
    
    @given(
        api_status=component_status_strategy,
        memory_status=component_status_strategy,
        kg_status=component_status_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_health_response_contains_all_required_components(
        self,
        api_status: ComponentStatus,
        memory_status: ComponentStatus,
        kg_status: ComponentStatus,
    ):
        """
        Property: Health response always contains api, memory, and knowledge_graph components
        """
        components = {
            "api": ComponentHealth(name="API", status=api_status),
            "memory": ComponentHealth(name="Memory", status=memory_status),
            "knowledge_graph": ComponentHealth(name="Knowledge Graph", status=kg_status),
        }
        
        response = HealthResponse(
            status="healthy",
            version="0.1.0",
            environment="test",
            components=components,
        )
        
        # Verify all required components are present
        assert set(response.components.keys()) == REQUIRED_COMPONENTS
        assert "api" in response.components
        assert "memory" in response.components
        assert "knowledge_graph" in response.components


    @given(
        api_health=component_health_strategy,
        memory_health=component_health_strategy,
        kg_health=component_health_strategy,
        version=st.text(min_size=1, max_size=20).filter(lambda x: x.strip()),
        environment=st.sampled_from(["development", "staging", "production"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_health_response_serialization_preserves_components(
        self,
        api_health: ComponentHealth,
        memory_health: ComponentHealth,
        kg_health: ComponentHealth,
        version: str,
        environment: str,
    ):
        """
        Property: Serializing and deserializing HealthResponse preserves all components
        """
        components = {
            "api": api_health,
            "memory": memory_health,
            "knowledge_graph": kg_health,
        }
        
        response = HealthResponse(
            status="healthy",
            version=version,
            environment=environment,
            components=components,
        )
        
        # Serialize and deserialize
        json_str = response.model_dump_json()
        restored = HealthResponse.model_validate_json(json_str)
        
        # Verify all components are preserved
        assert set(restored.components.keys()) == set(response.components.keys())
        assert restored.version == response.version
        assert restored.environment == response.environment


class TestOverallStatusDetermination:
    """
    Tests for overall status determination logic.
    """
    
    def test_all_healthy_returns_healthy(self):
        """When all components are healthy, overall status should be healthy"""
        from app.api.v1.health import determine_overall_status
        
        components = {
            "api": ComponentHealth(name="API", status=ComponentStatus.HEALTHY),
            "memory": ComponentHealth(name="Memory", status=ComponentStatus.HEALTHY),
            "knowledge_graph": ComponentHealth(name="KG", status=ComponentStatus.HEALTHY),
        }
        
        assert determine_overall_status(components) == "healthy"
    
    def test_some_degraded_returns_degraded(self):
        """When some components are degraded, overall status should be degraded"""
        from app.api.v1.health import determine_overall_status
        
        components = {
            "api": ComponentHealth(name="API", status=ComponentStatus.HEALTHY),
            "memory": ComponentHealth(name="Memory", status=ComponentStatus.DEGRADED),
            "knowledge_graph": ComponentHealth(name="KG", status=ComponentStatus.HEALTHY),
        }
        
        assert determine_overall_status(components) == "degraded"
    
    def test_non_critical_unavailable_returns_degraded(self):
        """When non-critical components are unavailable, status should be degraded"""
        from app.api.v1.health import determine_overall_status
        
        components = {
            "api": ComponentHealth(name="API", status=ComponentStatus.HEALTHY),
            "memory": ComponentHealth(name="Memory", status=ComponentStatus.UNAVAILABLE),
            "knowledge_graph": ComponentHealth(name="KG", status=ComponentStatus.HEALTHY),
        }
        
        assert determine_overall_status(components) == "degraded"
    
    def test_api_unavailable_returns_unhealthy(self):
        """When API is unavailable, overall status should be unhealthy"""
        from app.api.v1.health import determine_overall_status
        
        components = {
            "api": ComponentHealth(name="API", status=ComponentStatus.UNAVAILABLE),
            "memory": ComponentHealth(name="Memory", status=ComponentStatus.HEALTHY),
            "knowledge_graph": ComponentHealth(name="KG", status=ComponentStatus.HEALTHY),
        }
        
        assert determine_overall_status(components) == "unhealthy"


class TestHealthCheckIntegration:
    """
    Integration tests for health check endpoint.
    """
    
    @pytest.mark.asyncio
    async def test_health_check_returns_all_components(self):
        """Test that health check endpoint returns all required components"""
        from app.api.v1.health import health_check_deep
        
        response = await health_check_deep()
        
        # Verify all required components are present
        assert "api" in response.components
        assert "memory" in response.components
        assert "knowledge_graph" in response.components
        
        # Verify response has required fields
        assert response.status in ["healthy", "degraded", "unhealthy"]
        assert response.version is not None
        assert response.environment is not None

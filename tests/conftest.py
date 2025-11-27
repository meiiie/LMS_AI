"""
Pytest Configuration and Fixtures for Maritime AI Service Tests
"""
import pytest
from hypothesis import settings

# Configure Hypothesis profiles
settings.register_profile("ci", max_examples=100, deadline=None)
settings.register_profile("dev", max_examples=50, deadline=5000)
settings.load_profile("dev")


@pytest.fixture
def sample_user_id():
    """Sample user ID for testing"""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def sample_chat_message():
    """Sample chat message for testing"""
    return "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng"

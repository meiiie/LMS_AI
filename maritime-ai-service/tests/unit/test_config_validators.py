"""Tests for config.py field validators added in Sprint 7."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestJWTExpireValidator:
    """Validate jwt_expire_minutes boundaries."""

    def test_valid_default(self):
        s = Settings(jwt_expire_minutes=30)
        assert s.jwt_expire_minutes == 30

    def test_minimum_one_minute(self):
        s = Settings(jwt_expire_minutes=1)
        assert s.jwt_expire_minutes == 1

    def test_max_30_days(self):
        s = Settings(jwt_expire_minutes=43200)
        assert s.jwt_expire_minutes == 43200

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(jwt_expire_minutes=0)

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(jwt_expire_minutes=-10)

    def test_exceeds_30_days_rejected(self):
        with pytest.raises(ValidationError, match="must not exceed 43200"):
            Settings(jwt_expire_minutes=43201)


class TestPostgresPortValidator:
    """Validate postgres_port range."""

    def test_default_port(self):
        s = Settings(postgres_port=5432)
        assert s.postgres_port == 5432

    def test_docker_mapped_port(self):
        s = Settings(postgres_port=5433)
        assert s.postgres_port == 5433

    def test_min_port(self):
        s = Settings(postgres_port=1)
        assert s.postgres_port == 1

    def test_max_port(self):
        s = Settings(postgres_port=65535)
        assert s.postgres_port == 65535

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="must be between 1 and 65535"):
            Settings(postgres_port=0)

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="must be between 1 and 65535"):
            Settings(postgres_port=-1)

    def test_too_high_rejected(self):
        with pytest.raises(ValidationError, match="must be between 1 and 65535"):
            Settings(postgres_port=65536)


class TestRateLimitValidators:
    """Validate rate limit settings."""

    def test_valid_rate_limit_requests(self):
        s = Settings(rate_limit_requests=100)
        assert s.rate_limit_requests == 100

    def test_zero_requests_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(rate_limit_requests=0)

    def test_negative_requests_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(rate_limit_requests=-5)

    def test_valid_window_seconds(self):
        s = Settings(rate_limit_window_seconds=60)
        assert s.rate_limit_window_seconds == 60

    def test_zero_window_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(rate_limit_window_seconds=0)

    def test_negative_window_rejected(self):
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(rate_limit_window_seconds=-10)


class TestEnvironmentValidator:
    """Validate environment field."""

    def test_development(self):
        s = Settings(environment="development")
        assert s.environment == "development"

    def test_staging(self):
        s = Settings(environment="staging")
        assert s.environment == "staging"

    def test_production(self):
        s = Settings(
            environment="production",
            enable_dev_login=False,
            api_key="a" * 32,
            jwt_secret_key="prod-jwt-secret-key-32-bytes-min!",
            session_secret_key="a]b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
            google_api_key="test",
        )
        assert s.environment == "production"

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="environment must be one of"):
            Settings(environment="testing")


class TestLogLevelValidator:
    """Validate log_level field."""

    def test_info(self):
        s = Settings(log_level="INFO")
        assert s.log_level == "INFO"

    def test_debug_uppercase(self):
        s = Settings(log_level="debug")
        assert s.log_level == "DEBUG"

    def test_invalid_rejected(self):
        with pytest.raises(ValidationError, match="log_level must be one of"):
            Settings(log_level="VERBOSE")


class TestPostgresUrl:
    """Test postgres_url property construction."""

    def test_local_url_construction(self):
        s = Settings(
            database_url=None,
            postgres_user="wiii",
            postgres_password="secret",
            postgres_host="localhost",
            postgres_port=5433,
            postgres_db="wiii_ai",
        )
        assert (
            "postgresql+asyncpg://wiii:secret@localhost:5433/"
            "wiii_ai?connect_timeout=5"
        ) == s.postgres_url

    def test_cloud_url_override(self):
        s = Settings(database_url="postgresql://user:pass@host/db")
        assert (
            s.postgres_url
            == "postgresql+asyncpg://user:pass@host/db?connect_timeout=5"
        )

    def test_postgres_prefix_conversion(self):
        s = Settings(database_url="postgres://user:pass@host/db")
        assert (
            s.postgres_url
            == "postgresql+asyncpg://user:pass@host/db?connect_timeout=5"
        )

    def test_sync_url_construction(self):
        s = Settings(
            database_url=None,
            postgres_user="wiii",
            postgres_password="secret",
            postgres_host="localhost",
            postgres_port=5433,
            postgres_db="wiii_ai",
        )
        assert (
            "postgresql://wiii:secret@localhost:5433/"
            "wiii_ai?connect_timeout=5"
        ) == s.postgres_url_sync

    def test_sync_url_ssl_conversion(self):
        s = Settings(database_url="postgres://user:pass@host/db?ssl=require")
        assert "sslmode=require" in s.postgres_url_sync
        assert "ssl=require" not in s.postgres_url_sync
        assert "connect_timeout=5" in s.postgres_url_sync

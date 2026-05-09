"""
Unit tests for Domain Plugin System.

Tests:
- DomainLoader: discovery, filtering, error handling
- DomainRegistry: register, get, default, list, keywords
- DomainRouter: 4-priority resolution (explicit, session, keyword, default)
- DomainRouter: Vietnamese diacritics normalization
- MaritimeDomain: config, skills, prompts, hyde templates, routing config
- TrafficLawDomain: config, skills, prompts, routing
- Multi-domain routing: maritime vs traffic_law differentiation
- Skill matching and activation (progressive disclosure)
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Domain system imports (no external dependencies)
from app.domains.base import DomainPlugin, DomainConfig, SkillManifest
from app.domains.registry import DomainRegistry
from app.domains.loader import DomainLoader
from app.domains.router import DomainRouter


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def domains_dir():
    """Path to domains directory."""
    return Path(__file__).parent.parent.parent / "app" / "domains"


@pytest.fixture
def registry():
    """Fresh DomainRegistry instance (not singleton)."""
    return DomainRegistry()


@pytest.fixture
def loader(domains_dir):
    """DomainLoader pointing to real domains directory."""
    return DomainLoader(domains_dir)


@pytest.fixture
def all_domains(loader):
    """All discovered domain plugins."""
    domains = loader.discover()
    assert len(domains) >= 2, "Should discover at least maritime + traffic_law"
    return {d.get_config().id: d for d in domains}


@pytest.fixture
def maritime_domain(all_domains):
    """MaritimeDomain plugin instance."""
    assert "maritime" in all_domains
    return all_domains["maritime"]


@pytest.fixture
def traffic_law_domain(all_domains):
    """TrafficLawDomain plugin instance."""
    assert "traffic_law" in all_domains
    return all_domains["traffic_law"]


@pytest.fixture
def populated_registry(registry, maritime_domain):
    """Registry with maritime domain registered."""
    registry.register(maritime_domain)
    registry.set_default("maritime")
    return registry


@pytest.fixture
def multi_domain_registry(registry, all_domains):
    """Registry with all domains registered."""
    for domain in all_domains.values():
        registry.register(domain)
    registry.set_default("maritime")
    return registry


@pytest.fixture
def router(populated_registry):
    """DomainRouter with populated registry."""
    # Patch the singleton to use our test registry
    with patch("app.domains.router.get_domain_registry", return_value=populated_registry):
        yield DomainRouter()


@pytest.fixture
def multi_router(multi_domain_registry):
    """DomainRouter with all domains registered."""
    with patch("app.domains.router.get_domain_registry", return_value=multi_domain_registry):
        yield DomainRouter()


# =============================================================================
# DomainLoader Tests
# =============================================================================

class TestDomainLoader:
    """Tests for domain auto-discovery."""

    def test_discover_finds_maritime(self, loader):
        """Should discover the maritime domain plugin."""
        domains = loader.discover()
        ids = [d.get_config().id for d in domains]
        assert "maritime" in ids

    def test_discover_finds_traffic_law(self, loader):
        """Should discover the traffic_law domain plugin."""
        domains = loader.discover()
        ids = [d.get_config().id for d in domains]
        assert "traffic_law" in ids

    def test_discover_finds_multiple_domains(self, loader):
        """Should discover at least 2 domains."""
        domains = loader.discover()
        assert len(domains) >= 2

    def test_discover_skips_template(self, loader):
        """Should skip _template directory."""
        domains = loader.discover()
        ids = [d.get_config().id for d in domains]
        assert "_template" not in ids

    def test_discover_returns_domain_plugins(self, loader):
        """All discovered items should be DomainPlugin subclasses."""
        domains = loader.discover()
        for d in domains:
            assert isinstance(d, DomainPlugin)

    def test_discover_nonexistent_dir(self):
        """Should return empty list for nonexistent directory."""
        loader = DomainLoader(Path("/nonexistent/path"))
        assert loader.discover() == []

    def test_discover_empty_dir(self, tmp_path):
        """Should return empty list for empty directory."""
        loader = DomainLoader(tmp_path)
        assert loader.discover() == []


# =============================================================================
# DomainRegistry Tests
# =============================================================================

class TestDomainRegistry:
    """Tests for domain registration and lookup."""

    def test_register_and_get(self, registry, maritime_domain):
        """Should register and retrieve domain by ID."""
        registry.register(maritime_domain)
        result = registry.get("maritime")
        assert result is not None
        assert result.get_config().id == "maritime"

    def test_get_nonexistent(self, registry):
        """Should return None for unregistered domain."""
        assert registry.get("nonexistent") is None

    def test_set_default(self, registry, maritime_domain):
        """Should set and retrieve default domain."""
        registry.register(maritime_domain)
        registry.set_default("maritime")
        default = registry.get_default()
        assert default is not None
        assert default.get_config().id == "maritime"

    def test_get_default_unset(self, registry):
        """Should return None when no default set."""
        assert registry.get_default() is None

    def test_list_all(self, populated_registry):
        """Should list all registered domains."""
        all_domains = populated_registry.list_all()
        assert "maritime" in all_domains
        assert len(all_domains) >= 1

    def test_get_all_keywords(self, populated_registry):
        """Should aggregate keywords from all domains."""
        keywords = populated_registry.get_all_keywords()
        assert "maritime" in keywords
        assert len(keywords["maritime"]) > 0

    def test_register_duplicate(self, registry, maritime_domain):
        """Registering same domain twice should overwrite."""
        registry.register(maritime_domain)
        registry.register(maritime_domain)
        assert len(registry.list_all()) == 1

    def test_multi_domain_keywords(self, multi_domain_registry):
        """Should have separate keywords for each domain."""
        keywords = multi_domain_registry.get_all_keywords()
        assert "maritime" in keywords
        assert "traffic_law" in keywords
        assert len(keywords) >= 2


# =============================================================================
# DomainRouter Tests
# =============================================================================

class TestDomainRouter:
    """Tests for 4-priority domain resolution."""

    def test_explicit_domain_id(self, router):
        """Priority 1: Explicit domain_id should be used directly."""
        result = asyncio.run(
            router.resolve("anything", explicit_domain_id="maritime")
        )
        assert result == "maritime"

    def test_session_sticky(self, router):
        """Priority 2: Session domain should be used when no explicit."""
        result = asyncio.run(
            router.resolve("anything", session_domain="maritime")
        )
        assert result == "maritime"

    def test_keyword_match(self, router):
        """Priority 3: Should match domain by keyword in query."""
        result = asyncio.run(
            router.resolve("colregs rule 15")
        )
        assert result == "maritime"

    def test_default_fallback(self, router):
        """Priority 4: Should fall back to default domain."""
        result = asyncio.run(
            router.resolve("hello world")
        )
        assert result == "maritime"  # Default

    def test_explicit_overrides_keyword(self, router):
        """Explicit domain_id should override keyword match."""
        result = asyncio.run(
            router.resolve("colregs rule 15", explicit_domain_id="maritime")
        )
        assert result == "maritime"


# =============================================================================
# MaritimeDomain Tests
# =============================================================================

class TestMaritimeDomain:
    """Tests for the maritime domain plugin."""

    def test_config_id(self, maritime_domain):
        """Config ID should be 'maritime'."""
        assert maritime_domain.get_config().id == "maritime"

    def test_config_name(self, maritime_domain):
        """Config should have name and Vietnamese name."""
        cfg = maritime_domain.get_config()
        assert cfg.name  # Non-empty
        assert cfg.name_vi  # Non-empty

    def test_config_version(self, maritime_domain):
        """Config should have version."""
        assert maritime_domain.get_config().version

    def test_routing_keywords(self, maritime_domain):
        """Should have routing keywords."""
        cfg = maritime_domain.get_config()
        assert len(cfg.routing_keywords) > 0
        # Should contain key maritime terms
        all_kw = " ".join(cfg.routing_keywords).lower()
        assert "colregs" in all_kw or "colreg" in all_kw

    def test_mandatory_search_triggers(self, maritime_domain):
        """Should have mandatory search triggers."""
        cfg = maritime_domain.get_config()
        assert len(cfg.mandatory_search_triggers) > 0

    def test_prompts_dir_exists(self, maritime_domain):
        """Prompts directory should exist."""
        prompts_dir = maritime_domain.get_prompts_dir()
        assert prompts_dir.exists()
        assert prompts_dir.is_dir()

    def test_prompts_has_agents(self, maritime_domain):
        """Should have agent prompt files."""
        prompts_dir = maritime_domain.get_prompts_dir()
        agents_dir = prompts_dir / "agents"
        assert agents_dir.exists()
        # Should have tutor.yaml at minimum
        assert (agents_dir / "tutor.yaml").exists()

    def test_get_tools_returns_list(self, maritime_domain):
        """get_tools() should return a list."""
        tools = maritime_domain.get_tools()
        assert isinstance(tools, list)

    def test_get_hyde_templates(self, maritime_domain):
        """Should return HyDE templates dict with vi and en keys."""
        templates = maritime_domain.get_hyde_templates()
        assert isinstance(templates, dict)
        assert "vi" in templates or "en" in templates

    def test_get_routing_config(self, maritime_domain):
        """Should return routing config with required keys."""
        config = maritime_domain.get_routing_config()
        assert isinstance(config, dict)
        assert "routing_keywords" in config

    def test_get_greetings(self, maritime_domain):
        """Should return greetings dict."""
        greetings = maritime_domain.get_greetings()
        assert isinstance(greetings, dict)

    def test_get_tool_instruction(self, maritime_domain):
        """Should return non-empty tool instruction."""
        instruction = maritime_domain.get_tool_instruction()
        assert isinstance(instruction, str)
        assert len(instruction) > 0


# =============================================================================
# Skill System Tests
# =============================================================================

class TestSkillSystem:
    """Tests for SKILL.md matching and progressive disclosure."""

    def test_get_skills_returns_list(self, maritime_domain):
        """Should return list of SkillManifest objects."""
        skills = maritime_domain.get_skills()
        assert isinstance(skills, list)
        assert len(skills) > 0
        for s in skills:
            assert isinstance(s, SkillManifest)

    def test_skill_has_required_fields(self, maritime_domain):
        """Each skill should have id, name, triggers."""
        for skill in maritime_domain.get_skills():
            assert skill.id, "Skill must have id"
            assert skill.name, "Skill must have name"
            assert len(skill.triggers) > 0, "Skill must have triggers"
            assert skill.domain_id == "maritime"

    def test_colregs_skill_exists(self, maritime_domain):
        """Should have a COLREGs skill."""
        skill_ids = [s.id for s in maritime_domain.get_skills()]
        assert "colregs" in skill_ids

    def test_solas_skill_exists(self, maritime_domain):
        """Should have a SOLAS skill."""
        skill_ids = [s.id for s in maritime_domain.get_skills()]
        assert "solas" in skill_ids

    def test_marpol_skill_exists(self, maritime_domain):
        """Should have a MARPOL skill."""
        skill_ids = [s.id for s in maritime_domain.get_skills()]
        assert "marpol" in skill_ids

    def test_match_skills_colregs(self, maritime_domain):
        """Should match COLREGs skill for relevant queries."""
        matched = maritime_domain.match_skills("Rule 15 COLREGs")
        ids = [s.id for s in matched]
        assert "colregs" in ids

    def test_match_skills_marpol(self, maritime_domain):
        """Should match MARPOL skill for relevant queries."""
        matched = maritime_domain.match_skills("MARPOL Annex VI")
        ids = [s.id for s in matched]
        assert "marpol" in ids

    def test_match_skills_solas(self, maritime_domain):
        """Should match SOLAS skill for relevant queries."""
        matched = maritime_domain.match_skills("SOLAS chapter II")
        ids = [s.id for s in matched]
        assert "solas" in ids

    def test_match_skills_no_match(self, maritime_domain):
        """Should return empty list for unrelated queries."""
        matched = maritime_domain.match_skills("Hello world weather forecast")
        assert len(matched) == 0

    def test_match_skills_case_insensitive(self, maritime_domain):
        """Skill matching should be case-insensitive."""
        matched_upper = maritime_domain.match_skills("COLREGS")
        matched_lower = maritime_domain.match_skills("colregs")
        assert len(matched_upper) == len(matched_lower)

    def test_activate_skill_returns_content(self, maritime_domain):
        """Activating a skill should return SKILL.md content."""
        content = maritime_domain.activate_skill("colregs")
        assert content is not None
        assert len(content) > 0
        assert "colregs" in content.lower() or "COLREGs" in content

    def test_activate_skill_nonexistent(self, maritime_domain):
        """Activating nonexistent skill should return None."""
        content = maritime_domain.activate_skill("nonexistent_skill")
        assert content is None

    def test_progressive_disclosure(self, maritime_domain):
        """Skills should support progressive disclosure pattern:
        1. get_skills() returns lightweight manifests (name + triggers)
        2. activate_skill() lazily loads full content
        """
        # Step 1: Lightweight discovery
        skills = maritime_domain.get_skills()
        for s in skills:
            assert s.id
            assert s.name
            assert s.triggers
            # Content is NOT loaded yet (just the path)
            assert s.content_path

        # Step 2: Lazy full load
        content = maritime_domain.activate_skill(skills[0].id)
        assert content is not None
        assert len(content) > 100  # Substantial content


# =============================================================================
# DomainConfig Tests
# =============================================================================

class TestDomainConfig:
    """Tests for DomainConfig dataclass."""

    def test_create_config(self):
        """Should create DomainConfig with required fields."""
        config = DomainConfig(
            id="test",
            name="Test Domain",
            name_vi="Domain Test",
            version="1.0.0",
            routing_keywords=["test", "example"],
            mandatory_search_triggers=["test keyword"],
            rag_agent_description="Test RAG",
            tutor_agent_description="Test Tutor"
        )
        assert config.id == "test"
        assert config.name == "Test Domain"
        assert len(config.routing_keywords) == 2

    def test_config_optional_fields(self):
        """Optional fields should have sensible defaults."""
        config = DomainConfig(
            id="test",
            name="Test",
            name_vi="Test",
            version="1.0"
        )
        assert config.description == ""
        assert config.rag_agent_description == ""
        assert config.tutor_agent_description == ""
        assert config.routing_keywords == []
        assert config.mandatory_search_triggers == []


# =============================================================================
# TrafficLawDomain Tests
# =============================================================================

class TestTrafficLawDomain:
    """Tests for the traffic_law domain plugin."""

    def test_config_id(self, traffic_law_domain):
        """Config ID should be 'traffic_law'."""
        assert traffic_law_domain.get_config().id == "traffic_law"

    def test_config_name(self, traffic_law_domain):
        """Config should have name and Vietnamese name."""
        cfg = traffic_law_domain.get_config()
        assert cfg.name
        assert cfg.name_vi

    def test_config_version(self, traffic_law_domain):
        """Config should have version."""
        assert traffic_law_domain.get_config().version == "1.0.0"

    def test_routing_keywords(self, traffic_law_domain):
        """Should have traffic law routing keywords."""
        cfg = traffic_law_domain.get_config()
        assert len(cfg.routing_keywords) > 0
        all_kw = " ".join(cfg.routing_keywords).lower()
        assert "giao" in all_kw or "traffic" in all_kw

    def test_mandatory_search_triggers(self, traffic_law_domain):
        """Should have mandatory search triggers."""
        cfg = traffic_law_domain.get_config()
        assert len(cfg.mandatory_search_triggers) > 0

    def test_prompts_dir_exists(self, traffic_law_domain):
        """Prompts directory should exist."""
        prompts_dir = traffic_law_domain.get_prompts_dir()
        assert prompts_dir.exists()
        assert prompts_dir.is_dir()

    def test_prompts_has_tutor(self, traffic_law_domain):
        """Should have tutor prompt."""
        prompts_dir = traffic_law_domain.get_prompts_dir()
        assert (prompts_dir / "agents" / "tutor.yaml").exists()

    def test_get_skills(self, traffic_law_domain):
        """Should have at least the traffic_signs skill."""
        skills = traffic_law_domain.get_skills()
        assert len(skills) >= 1
        ids = [s.id for s in skills]
        assert "traffic_signs" in ids

    def test_skill_domain_id(self, traffic_law_domain):
        """Skills should have domain_id='traffic_law'."""
        for skill in traffic_law_domain.get_skills():
            assert skill.domain_id == "traffic_law"

    def test_get_hyde_templates(self, traffic_law_domain):
        """Should return HyDE templates dict."""
        templates = traffic_law_domain.get_hyde_templates()
        assert isinstance(templates, dict)
        assert "vi" in templates or "en" in templates

    def test_get_tool_instruction(self, traffic_law_domain):
        """Should return non-empty tool instruction."""
        instruction = traffic_law_domain.get_tool_instruction()
        assert len(instruction) > 0

    def test_get_greetings(self, traffic_law_domain):
        """Should return greetings dict."""
        greetings = traffic_law_domain.get_greetings()
        assert isinstance(greetings, dict)
        assert len(greetings) > 0

    def test_match_skills_traffic_signs(self, traffic_law_domain):
        """Should match traffic_signs skill for sign queries."""
        matched = traffic_law_domain.match_skills("traffic sign road sign")
        ids = [s.id for s in matched]
        assert "traffic_signs" in ids

    def test_match_skills_no_match(self, traffic_law_domain):
        """Should return empty for unrelated queries."""
        matched = traffic_law_domain.match_skills("Hello weather forecast")
        assert len(matched) == 0

    def test_activate_skill(self, traffic_law_domain):
        """Should load full skill content."""
        content = traffic_law_domain.activate_skill("traffic_signs")
        assert content is not None
        assert len(content) > 100


# =============================================================================
# Multi-Domain Routing Tests
# =============================================================================

class TestMultiDomainRouting:
    """Tests for routing between maritime and traffic_law domains."""

    def test_maritime_keyword_routing(self, multi_router):
        """Maritime keywords should route to maritime."""
        result = asyncio.run(
            multi_router.resolve("COLREGs rule 15 crossing")
        )
        assert result == "maritime"

    def test_traffic_law_keyword_routing(self, multi_router):
        """Traffic law keywords (with diacritics) should route to traffic_law."""
        result = asyncio.run(
            multi_router.resolve("biển báo giao thông đường bộ")
        )
        assert result == "traffic_law"

    def test_traffic_law_no_diacritics(self, multi_router):
        """Traffic law keywords WITHOUT diacritics should still route correctly."""
        result = asyncio.run(
            multi_router.resolve("bien bao giao thong duong bo")
        )
        assert result == "traffic_law"

    def test_penalty_routes_to_traffic(self, multi_router):
        """Penalty/fine queries should route to traffic_law."""
        result = asyncio.run(
            multi_router.resolve("muc phat vuot den do")
        )
        assert result == "traffic_law"

    def test_solas_routes_to_maritime(self, multi_router):
        """SOLAS queries should route to maritime."""
        result = asyncio.run(
            multi_router.resolve("SOLAS chapter II fire safety")
        )
        assert result == "maritime"

    def test_driving_license_routes_to_traffic(self, multi_router):
        """Driving license queries should route to traffic_law."""
        result = asyncio.run(
            multi_router.resolve("bang lai xe B2 oto")
        )
        assert result == "traffic_law"

    def test_default_fallback_to_maritime(self, multi_router):
        """Unknown queries should fallback to maritime (default)."""
        result = asyncio.run(
            multi_router.resolve("hello world good morning")
        )
        assert result == "maritime"

    def test_explicit_overrides_keywords(self, multi_router):
        """Explicit domain_id should override keyword matching."""
        result = asyncio.run(
            multi_router.resolve("COLREGs rule 15", explicit_domain_id="traffic_law")
        )
        assert result == "traffic_law"

    def test_diacritics_normalization(self, multi_router):
        """Router._strip_diacritics should correctly normalize Vietnamese text."""
        assert multi_router._strip_diacritics("biển báo") == "bien bao"
        assert multi_router._strip_diacritics("đèn đỏ") == "den do"
        assert multi_router._strip_diacritics("giao thông") == "giao thong"
        assert multi_router._strip_diacritics("nghị định") == "nghi dinh"
        assert multi_router._strip_diacritics("tốc độ") == "toc do"

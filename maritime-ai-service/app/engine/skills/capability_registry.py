"""
Capability registry for Wiii tools and skills.

This is the first step away from hardcoded tool -> skill maps. It provides a
single registry that carries:
- capability path (for future tree retrieval)
- skill domain (for living-agent advancement)
- selector category hints
- semantic tags and descriptions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class ToolCapability:
    """Stable metadata for a tool's capability footprint."""

    tool_name: str
    capability_path: Tuple[str, ...]
    skill_domain: Optional[str] = None
    selector_category: Optional[str] = None
    description: str = ""
    tags: Tuple[str, ...] = field(default_factory=tuple)
    execution_mode: str = "single"


class CapabilityRegistry:
    """Read-only registry for tool capabilities."""

    def __init__(self, capabilities: Iterable[ToolCapability]):
        self._capabilities: Dict[str, ToolCapability] = {
            capability.tool_name: capability for capability in capabilities
        }

    def get(self, tool_name: str) -> Optional[ToolCapability]:
        return self._capabilities.get(tool_name)

    def all(self) -> tuple[ToolCapability, ...]:
        return tuple(self._capabilities.values())

    def get_skill_domain(self, tool_name: str) -> Optional[str]:
        capability = self.get(tool_name)
        return capability.skill_domain if capability else None

    def get_selector_category(self, tool_name: str) -> Optional[str]:
        capability = self.get(tool_name)
        return capability.selector_category if capability else None

    def searchable_text(self, tool_name: str) -> str:
        capability = self.get(tool_name)
        if capability is None:
            return ""
        parts = [
            capability.tool_name,
            capability.description,
            " ".join(capability.capability_path),
            " ".join(capability.tags),
        ]
        return " ".join(part for part in parts if part).strip()

    def reverse_lookup(self, skill_domain: str) -> list[str]:
        return [
            capability.tool_name
            for capability in self._capabilities.values()
            if capability.skill_domain == skill_domain
        ]

    def capability_tree(self) -> Dict[str, dict]:
        tree: Dict[str, dict] = {}
        for capability in self._capabilities.values():
            cursor = tree
            for segment in capability.capability_path:
                cursor = cursor.setdefault(segment, {})
            cursor.setdefault("__tools__", []).append(capability.tool_name)
        return tree


_DEFAULT_CAPABILITIES = (
    ToolCapability(
        tool_name="tool_knowledge_search",
        capability_path=("knowledge", "retrieval", "internal_docs"),
        skill_domain="knowledge_retrieval",
        selector_category="rag",
        description="Search internal knowledge and organization documents.",
        tags=("rag", "knowledge", "citations", "documents"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_maritime_search",
        capability_path=("knowledge", "retrieval", "maritime"),
        skill_domain="maritime_navigation",
        selector_category="utility",
        description="Search maritime regulations and maritime-specific sources.",
        tags=("maritime", "imo", "shipping", "regulations"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_search_maritime",
        capability_path=("knowledge", "retrieval", "maritime"),
        skill_domain="maritime_navigation",
        selector_category="utility",
        description="Search maritime news and international maritime sources.",
        tags=("maritime", "shipping", "news", "imo"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_web_search",
        capability_path=("knowledge", "retrieval", "web"),
        skill_domain="web_research",
        selector_category="utility",
        description="Search the public web (SearXNG meta-search + bilingual news merge).",
        tags=("web", "search", "news", "internet", "current", "searxng"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_fetch_url",
        capability_path=("knowledge", "retrieval", "deep_fetch"),
        skill_domain="web_research",
        selector_category="utility",
        description="Fetch full markdown of a URL via 4-tier extractor (Crawl4AI → Scrapling → Jina → httpx); cached 1h.",
        tags=("web", "fetch", "scrape", "deep", "markdown", "crawl4ai"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_search_news",
        capability_path=("knowledge", "retrieval", "news"),
        skill_domain="news_analysis",
        selector_category="utility",
        description="Search Vietnamese news sources.",
        tags=("news", "current", "press", "headlines"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_search_legal",
        capability_path=("knowledge", "retrieval", "legal"),
        skill_domain="legal_research",
        selector_category="utility",
        description="Search legal and regulatory documents.",
        tags=("legal", "law", "regulation", "decree"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_calculator",
        capability_path=("analysis", "computation", "math"),
        skill_domain="calculation",
        selector_category="utility",
        description="Compute equations and numeric expressions.",
        tags=("math", "calculation", "formula"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_current_datetime",
        capability_path=("utility", "time", "current_datetime"),
        selector_category="utility",
        description="Get the current date and time.",
        tags=("date", "time", "clock", "now"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_think",
        capability_path=("internal", "reasoning", "reflection"),
        description="Internal reasoning helper for multi-phase thinking.",
        tags=("thinking", "reflection"),
        execution_mode="internal",
    ),
    ToolCapability(
        tool_name="tool_report_progress",
        capability_path=("internal", "reasoning", "progress"),
        description="Report phase transitions during agent execution.",
        tags=("progress", "phase", "status"),
        execution_mode="internal",
    ),
    ToolCapability(
        tool_name="tool_character_note",
        capability_path=("relationship", "memory", "character_write"),
        description="Write character and relationship memory.",
        tags=("character", "memory", "relationship"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_character_read",
        capability_path=("relationship", "memory", "character_read"),
        description="Read character and relationship memory.",
        tags=("character", "memory", "relationship"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_browser_snapshot_url",
        capability_path=("knowledge", "observation", "browser"),
        skill_domain="web_research",
        selector_category="utility",
        description="Open a page in browser sandbox and inspect its rendered state.",
        tags=("browser", "visual", "verification", "screenshot"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_generate_html_file",
        capability_path=("creation", "artifacts", "html_file"),
        skill_domain="artifact_generation",
        selector_category="utility",
        description="Generate a self-contained HTML file such as a landing page or microsite.",
        tags=("html", "landing-page", "artifact", "website", "export"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_generate_excel_file",
        capability_path=("creation", "artifacts", "excel_file"),
        skill_domain="artifact_generation",
        selector_category="utility",
        description="Generate an Excel spreadsheet from structured JSON rows.",
        tags=("excel", "xlsx", "spreadsheet", "table", "export"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_generate_word_document",
        capability_path=("creation", "artifacts", "word_document"),
        skill_domain="artifact_generation",
        selector_category="utility",
        description="Generate a Word document from markdown-like content.",
        tags=("word", "docx", "document", "report", "export"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_search_google_shopping",
        capability_path=("commerce", "shopping", "google_shopping"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Google Shopping listings for products and prices.",
        tags=("shopping", "price", "comparison", "google", "product"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_shopee",
        capability_path=("commerce", "shopping", "shopee"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Shopee listings for products sold in Vietnam.",
        tags=("shopping", "shopee", "marketplace", "price", "product"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_lazada",
        capability_path=("commerce", "shopping", "lazada"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Lazada listings for products sold in Vietnam.",
        tags=("shopping", "lazada", "marketplace", "price", "product"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_tiktok_shop",
        capability_path=("commerce", "shopping", "tiktok_shop"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search TikTok Shop listings for products and current pricing.",
        tags=("shopping", "tiktok", "marketplace", "price", "product"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_websosanh",
        capability_path=("commerce", "comparison", "aggregator"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Compare prices across many Vietnamese stores via Websosanh.",
        tags=("shopping", "compare", "price", "aggregator", "websosanh"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_all_web",
        capability_path=("commerce", "shopping", "all_web"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search broader web stores and distributor sites for products.",
        tags=("shopping", "dealer", "distributor", "web", "price"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_facebook_marketplace",
        capability_path=("commerce", "marketplace", "facebook_marketplace"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Facebook Marketplace listings for second-hand or local offers.",
        tags=("facebook", "marketplace", "used", "local", "price"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_facebook_group",
        capability_path=("commerce", "community", "facebook_group"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search a specific Facebook group for product posts and offers.",
        tags=("facebook", "group", "community", "used", "price"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_facebook_groups_auto",
        capability_path=("commerce", "community", "facebook_groups_auto"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Automatically scan relevant Facebook groups for product offers.",
        tags=("facebook", "group", "community", "used", "price"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_facebook_search",
        capability_path=("commerce", "community", "facebook_search"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Facebook public posts for product mentions and listings.",
        tags=("facebook", "social", "shopping", "price", "listing"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_search_instagram_shopping",
        capability_path=("commerce", "social_commerce", "instagram"),
        skill_domain="product_research",
        selector_category="product_search",
        description="Search Instagram shopping posts and storefronts.",
        tags=("instagram", "shopping", "social", "price", "product"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_fetch_product_detail",
        capability_path=("commerce", "verification", "product_detail"),
        skill_domain="product_verification",
        selector_category="product_search",
        description="Open a product page and verify current price and specifications.",
        tags=("product", "verification", "detail", "price", "specs"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_generate_product_report",
        capability_path=("commerce", "reporting", "comparison_report"),
        skill_domain="product_reporting",
        selector_category="product_search",
        description="Generate a product comparison report or spreadsheet.",
        tags=("report", "excel", "comparison", "shopping"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_dealer_search",
        capability_path=("commerce", "sourcing", "dealer_search"),
        skill_domain="b2b_sourcing",
        selector_category="product_search",
        description="Find distributors, dealers, and B2B suppliers for a product.",
        tags=("dealer", "distributor", "supplier", "b2b", "contact"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_extract_contacts",
        capability_path=("commerce", "sourcing", "contact_extraction"),
        skill_domain="b2b_sourcing",
        selector_category="product_search",
        description="Extract phone, Zalo, email, and contact details from seller pages.",
        tags=("contact", "email", "phone", "zalo", "dealer"),
        execution_mode="single",
    ),
    ToolCapability(
        tool_name="tool_international_search",
        capability_path=("commerce", "comparison", "international_search"),
        skill_domain="b2b_sourcing",
        selector_category="product_search",
        description="Search international marketplaces for price benchmarks.",
        tags=("international", "1688", "taobao", "aliexpress", "amazon"),
        execution_mode="parallel",
    ),
    ToolCapability(
        tool_name="tool_identify_product_from_image",
        capability_path=("commerce", "vision", "product_identification"),
        skill_domain="visual_product_search",
        selector_category="product_search",
        description="Identify a product from an image and derive search keywords.",
        tags=("vision", "image", "product", "identify", "shopping"),
        execution_mode="single",
    ),
)


@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    """Return the shared capability registry."""

    return CapabilityRegistry(_DEFAULT_CAPABILITIES)

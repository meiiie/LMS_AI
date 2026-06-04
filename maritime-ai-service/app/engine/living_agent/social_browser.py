"""
Social Browser — Wiii's autonomous content discovery engine.

Sprint 170: "Linh Hồn Sống"
Sprint 171: "Quyền Tự Chủ" — Routes through existing web tools + safety.
Sprint 173: "Tự Khám Phá" — Facebook browsing via Serper site:facebook.com.

Browses news, tech blogs, and social media to discover content
aligned with Wiii's interests. Uses existing web_search_tools.py
(DuckDuckGo + circuit breaker + RSS) instead of raw Serper/HN API calls.

Sprint 171 changes:
    - Routes searches through existing tools (DuckDuckGo, RSS, maritime, news)
    - Inherits circuit breaker (3 failures × 120s recovery)
    - URL validation via safety.validate_url (SSRF prevention)
    - Content sanitization via safety.sanitize_content
    - Prompt injection detection before LLM calls
    - Serper + HackerNews kept as fallback only
    - Topic tracking for proper tool routing

Sprint 173 changes:
    - Added "facebook" topic with site:facebook.com queries
    - _search_facebook(): lightweight Serper-based search (no Playwright)
    - Facebook topic routes to _search_facebook() instead of _invoke_tool()
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import List, Optional

from app.engine.living_agent.models import BrowsingItem
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_AUTONOMOUS_USER_ID = "__wiii__"

# Topic → search queries mapping
_TOPIC_QUERIES = {
    "news": [
        "AI agent technology 2026",
        "maritime shipping news",
        "machine learning breakthroughs",
        "Vietnam technology",
    ],
    "tech": [
        "LLM autonomous agents",
        "LangGraph state machines",
        "Ollama local models",
        "Python async patterns",
    ],
    "maritime": [
        "IMO regulations 2026",
        "COLREGs updates",
        "SOLAS amendments",
        "MARPOL compliance",
        "maritime safety news",
    ],
    "science": [
        "astronomy discoveries 2026",
        "ocean conservation",
        "renewable energy maritime",
    ],
    "facebook": [
        "site:facebook.com maritime shipping news",
        "site:facebook.com hàng hải Việt Nam",
        "site:facebook.com AI technology 2026",
        "site:facebook.com machine learning news",
        "site:facebook.com Vietnam technology community",
    ],
    "general": [
        "trending technology news",
        "Vietnam news",
        "AI research papers",
    ],
}

# Topic → tool routing
_TOPIC_TOOL_MAP = {
    "maritime": "tool_search_maritime",
    "news": "tool_search_news",
}


class SocialBrowser:
    """Autonomous content browser for Wiii's learning.

    Browses various platforms to find content relevant to Wiii's interests.
    All content is filtered for safety and scored for relevance.

    Sprint 171: Routes through existing web_search_tools.py for DuckDuckGo
    integration with circuit breaker, RSS feeds, and site-restricted search.

    Usage:
        browser = SocialBrowser()
        items = await browser.browse_feed(topic="tech", interests=["AI", "ML"])
    """

    def __init__(self):
        self._current_topic: str = "general"
        self._smart_topics_enabled: bool = False
        self._recent_topics: list = []  # Sprint 188: Track recent topics for rotation

    @staticmethod
    def _log_scope_blocked(
        *,
        operation: str,
        scope: MemoryWriteScope,
        item_id: str | None = None,
    ) -> None:
        extra = ""
        if item_id:
            extra = f" item_hash={hash_memory_identifier(item_id)}"
        logger.warning(
            "[BROWSER] %s blocked scope=%s%s",
            operation,
            scope.state,
            extra,
        )

    async def browse_feed(
        self,
        topic: str = "general",
        interests: Optional[List[str]] = None,
        max_items: int = 5,
    ) -> List[BrowsingItem]:
        """Browse content for a topic, filtered by interests.

        Args:
            topic: Content category (news, tech, maritime, science, general).
            interests: List of interest strings for relevance filtering.
            max_items: Maximum items to return.

        Returns:
            List of BrowsingItem with relevance scores.
        """
        from app.core.config import settings

        if not settings.living_agent_enable_social_browse:
            return []

        self._current_topic = topic

        # Phase 3A: Smart topic selection when topic is "auto"
        if topic == "auto":
            topic = await self._select_smart_topic()
            self._current_topic = topic

        queries = _TOPIC_QUERIES.get(topic, _TOPIC_QUERIES["general"])
        query = random.choice(queries)

        # Search via existing tools (Sprint 171)
        items = await self._search_web(query, max_items * 2)

        if not items:
            logger.debug("[BROWSER] No results for query: %s", query)
            return []

        # Score relevance using local LLM
        if interests:
            items = await self._score_relevance(items, interests)

        # Sort by relevance, return top N
        items.sort(key=lambda x: x.relevance_score, reverse=True)
        results = items[:max_items]

        # Save to browsing log
        self._save_browsing_log(results)

        # Sprint 177: Feed results to skill learning pipeline
        if results and settings.living_agent_enable_skill_learning:
            try:
                from app.engine.living_agent.skill_learner import get_skill_learner
                learner = get_skill_learner()
                all_interests = interests or []
                learner.process_browsing_results(results, all_interests)
            except Exception as e:
                logger.debug("[BROWSER] Skill learning pipeline failed: %s", e)

        # Sprint 210: Extract insights from high-relevance items
        if getattr(settings, 'enable_living_continuity', False):
            try:
                saved = await self._extract_and_save_insights(results)
                if saved:
                    logger.info("[BROWSER] Saved %d insights from browsing", saved)
            except Exception as e:
                logger.debug("[BROWSER] Insight extraction failed: %s", e)

        logger.info(
            "[BROWSER] Browsed %d items for topic '%s' (query: %s)",
            len(results), topic, query,
        )
        return results

    async def _select_smart_topic(self) -> str:
        """Sprint 188: Context-aware topic selection.

        Priority:
        1. User interests from semantic_memories (conversation context)
        2. Active skills being learned (LEARNING status)
        3. Time-weighted topic distribution
        4. Topic rotation (no repeat within 3 cycles)
        """
        from datetime import timedelta

        now_vn = datetime.now(timezone.utc) + timedelta(hours=7)
        hour = now_vn.hour

        available_topics = list(_TOPIC_QUERIES.keys())

        # Sprint 188: Filter out recently used topics (no repeat within 3 cycles)
        if len(self._recent_topics) >= 3:
            self._recent_topics = self._recent_topics[-3:]
        fresh_topics = [t for t in available_topics if t not in self._recent_topics]
        if not fresh_topics:
            fresh_topics = available_topics  # Fallback if all exhausted

        # 1. Check semantic_memories for user interests
        topic_from_memory = await self._get_topic_from_memories()
        if topic_from_memory and topic_from_memory in fresh_topics:
            self._recent_topics.append(topic_from_memory)
            return topic_from_memory

        # 2. Check active skills
        topic_from_skills = self._get_topic_from_skills()
        if topic_from_skills and topic_from_skills in fresh_topics:
            self._recent_topics.append(topic_from_skills)
            return topic_from_skills

        # 3. Time-weighted selection from fresh topics
        time_weights = {}
        for t in fresh_topics:
            if hour < 10:
                time_weights[t] = 3.0 if t == "news" else 1.0
            elif hour < 16:
                time_weights[t] = 3.0 if t in ("tech", "maritime") else 1.0
            elif hour < 20:
                time_weights[t] = 3.0 if t in ("science", "general") else 1.0
            else:
                time_weights[t] = 2.0 if t == "general" else 1.0

        weighted_topics = list(time_weights.keys())
        weights = [time_weights[t] for t in weighted_topics]
        chosen = random.choices(weighted_topics, weights=weights, k=1)[0]
        self._recent_topics.append(chosen)
        return chosen

    async def _get_topic_from_memories(self) -> Optional[str]:
        """Sprint 188: Query semantic_memories for user interest patterns."""
        scope = resolve_memory_read_scope()
        if not scope.write_allowed or not scope.org_id:
            self._log_scope_blocked(operation="topic_memory_read", scope=scope)
            return None

        try:
            from app.core.database import get_shared_session_factory
            from sqlalchemy import text

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT content FROM semantic_memories
                        WHERE memory_type = 'fact'
                          AND organization_id = :org_id
                        ORDER BY importance DESC, updated_at DESC
                        LIMIT 5
                    """),
                    {"org_id": scope.org_id},
                ).fetchall()

            if not rows:
                return None

            # Simple keyword matching against topic names
            all_text = " ".join(r[0] for r in rows if r[0]).lower()
            topic_scores = {}
            for topic, queries in _TOPIC_QUERIES.items():
                keywords = set()
                for q in queries:
                    keywords.update(w.lower() for w in q.split() if len(w) > 3 and not w.startswith("site:"))
                matches = sum(1 for kw in keywords if kw in all_text)
                if matches > 0:
                    topic_scores[topic] = matches

            if topic_scores:
                return max(topic_scores, key=topic_scores.get)
        except Exception as e:
            logger.debug("[BROWSER] Topic scoring from goals failed: %s", e)
        return None

    def _get_topic_from_skills(self) -> Optional[str]:
        """Sprint 188: Check active skills for topic hints."""
        try:
            from app.engine.living_agent.skill_builder import get_skill_builder
            builder = get_skill_builder()
            skills = builder.get_all_skills(status=None)
            learning_skills = [s for s in skills if s.status.value == "learning"]
            if learning_skills:
                skill = random.choice(learning_skills)
                if skill.domain in _TOPIC_QUERIES:
                    return skill.domain
        except Exception:
            pass
        return None

    async def _search_web(self, query: str, max_results: int) -> List[BrowsingItem]:
        """Search using existing web_search_tools (DuckDuckGo + circuit breaker).

        Sprint 171: Routes by topic to appropriate existing tool, inheriting:
        - Circuit breaker (3 failures × 120s recovery)
        - DuckDuckGo Vietnamese region search
        - RSS feed aggregation for news
        - Maritime site-restricted search (IMO, Safety4Sea, VINAMARINE)
        """
        from app.engine.living_agent.safety import validate_url, sanitize_content

        items: List[BrowsingItem] = []

        # 1. Try Facebook-specific search for facebook topic (Sprint 173)
        if self._current_topic == "facebook":
            try:
                items = await self._search_facebook(query, max_results)
            except Exception as e:
                logger.debug("[BROWSER] Facebook search failed: %s", e)

        # 2. Try existing tools for other topics
        if not items:
            try:
                raw = await self._invoke_tool(query)
                if raw:
                    items = self._parse_tool_results(raw, max_results)
            except Exception as e:
                logger.debug("[BROWSER] Tool search failed: %s", e)

        # 3. Fallback to Serper/HN if tools returned nothing
        if not items:
            items = await self._fallback_search(query, max_results)

        # 4. Safety: validate URLs and sanitize content
        safe_items = []
        for item in items:
            if item.url and not validate_url(item.url):
                logger.warning("[BROWSER] Blocked unsafe URL: %s", (item.url or "")[:50])
                continue
            item.summary = sanitize_content(item.summary)
            safe_items.append(item)

        return safe_items

    async def _invoke_tool(self, query: str) -> str:
        """Invoke the appropriate existing web search tool based on current topic.

        Returns the raw formatted string output from the tool.
        """
        from app.engine.tools.web_search_tools import (
            tool_web_search,
            tool_search_news,
            tool_search_maritime,
        )

        tool_name = _TOPIC_TOOL_MAP.get(self._current_topic)

        if tool_name == "tool_search_maritime":
            tool_fn = tool_search_maritime
        elif tool_name == "tool_search_news":
            tool_fn = tool_search_news
        else:
            tool_fn = tool_web_search

        # Tools are sync (DuckDuckGo uses ThreadPoolExecutor internally)
        result = await asyncio.to_thread(tool_fn.invoke, query)
        return result

    async def _search_facebook(self, query: str, max_results: int) -> List[BrowsingItem]:
        """Search Facebook via Serper API (site:facebook.com).

        Sprint 173: Lightweight Facebook search — no Playwright, no cookies.
        Uses Google index of public Facebook content via Serper API.

        Args:
            query: Search query (should contain site:facebook.com).
            max_results: Maximum results to return.

        Returns:
            List of BrowsingItem with platform="facebook".
        """
        import httpx
        from app.core.config import settings

        api_key = settings.serper_api_key
        if not api_key:
            return []

        # Ensure query targets Facebook
        search_query = query if "site:facebook.com" in query else f"site:facebook.com {query}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": search_query, "num": max_results, "gl": "vn", "hl": "vi"},
            )
            resp.raise_for_status()
            data = resp.json()

        items = []
        for result in data.get("organic", [])[:max_results]:
            items.append(BrowsingItem(
                platform="facebook",
                url=result.get("link", ""),
                title=result.get("title", ""),
                summary=result.get("snippet", ""),
            ))
        return items

    def _parse_tool_results(self, raw: str, max_results: int) -> List[BrowsingItem]:
        """Parse formatted tool output back into BrowsingItem objects.

        Existing tools output markdown-formatted text like:
            **Title** (date) [source]
            Body text here
            URL: https://example.com

            ---

            **Title 2**
            ...
        """
        if not raw or raw.startswith("Không tìm") or raw.startswith("Lỗi") or raw.startswith("Tìm kiếm"):
            return []

        items = []
        blocks = raw.split("\n\n---\n\n")

        for block in blocks[:max_results]:
            block = block.strip()
            if not block:
                continue

            title = ""
            url = ""
            summary = ""

            lines = block.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("**") and not title:
                    # Extract title from **title** pattern
                    match = re.match(r"\*\*(.+?)\*\*", line)
                    if match:
                        title = match.group(1)
                elif line.startswith("URL:"):
                    url = line[4:].strip()
                else:
                    if line and not line.startswith("**"):
                        summary += line + " "

            if title:
                items.append(BrowsingItem(
                    platform="web_search",
                    url=url if url else None,
                    title=title[:500],
                    summary=summary.strip()[:2000],
                ))

        return items

    async def _fallback_search(self, query: str, max_results: int) -> List[BrowsingItem]:
        """Fallback search via Serper API and HackerNews when existing tools fail.

        Sprint 171: Only called when all existing tools fail (circuit breaker open).
        """
        items: List[BrowsingItem] = []

        # Try Serper API if available
        try:
            serper_items = await self._search_via_serper(query, max_results)
            items.extend(serper_items)
        except Exception as e:
            logger.debug("[BROWSER] Serper fallback failed: %s", e)

        # If Serper unavailable, try HackerNews API (free, no key)
        if not items:
            try:
                hn_items = await self._search_hackernews(query, max_results)
                items.extend(hn_items)
            except Exception as e:
                logger.debug("[BROWSER] HackerNews fallback failed: %s", e)

        return items

    async def _search_via_serper(self, query: str, max_results: int) -> List[BrowsingItem]:
        """Search via Serper API (fallback only)."""
        import httpx
        from app.core.config import settings

        api_key = settings.serper_api_key
        if not api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": max_results},
                )
                resp.raise_for_status()
                data = resp.json()

                items = []
                for result in data.get("organic", [])[:max_results]:
                    items.append(BrowsingItem(
                        platform="serper_fallback",
                        url=result.get("link", ""),
                        title=result.get("title", ""),
                        summary=result.get("snippet", ""),
                    ))
                return items
        except Exception as e:
            logger.debug("[BROWSER] Serper error: %s", e)
            return []

    async def _search_hackernews(self, query: str, max_results: int) -> List[BrowsingItem]:
        """Search HackerNews (free API, no key needed — fallback only)."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": query, "hitsPerPage": max_results, "tags": "story"},
                )
                resp.raise_for_status()
                data = resp.json()

                items = []
                for hit in data.get("hits", [])[:max_results]:
                    items.append(BrowsingItem(
                        platform="hackernews",
                        url=hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"),
                        title=hit.get("title", ""),
                        summary=hit.get("story_text", "")[:500] if hit.get("story_text") else "",
                        metadata={"points": hit.get("points", 0), "comments": hit.get("num_comments", 0)},
                    ))
                return items
        except Exception as e:
            logger.debug("[BROWSER] HackerNews error: %s", e)
            return []

    async def _score_relevance(
        self,
        items: List[BrowsingItem],
        interests: List[str],
    ) -> List[BrowsingItem]:
        """Score items by relevance to Wiii's interests using local LLM."""
        from app.engine.living_agent.local_llm import get_local_llm
        from app.engine.living_agent.safety import detect_prompt_injection, sanitize_content

        llm = get_local_llm()

        # Check if local LLM is available
        available = await llm.is_available()
        if not available:
            # Fallback: keyword-based scoring
            return self._keyword_score(items, interests)

        for item in items:
            content = f"{item.title} {item.summary}"
            if content.strip():
                # Sprint 171: Check for prompt injection before LLM call
                clean_content = sanitize_content(content, max_len=1000)
                if detect_prompt_injection(clean_content):
                    logger.warning("[BROWSER] Prompt injection detected in content: %s", item.title[:80])
                    item.relevance_score = 0.0
                    continue
                score = await llm.rate_relevance(clean_content, interests)
                item.relevance_score = score

        return items

    @staticmethod
    def _keyword_score(
        items: List[BrowsingItem],
        interests: List[str],
    ) -> List[BrowsingItem]:
        """Fallback keyword-based relevance scoring."""
        interest_keywords = set()
        for interest in interests:
            interest_keywords.update(interest.lower().split())

        for item in items:
            text = f"{item.title} {item.summary}".lower()
            matches = sum(1 for kw in interest_keywords if kw in text)
            item.relevance_score = min(1.0, matches / max(len(interest_keywords), 1))

        return items

    async def _extract_and_save_insights(
        self,
        items: List[BrowsingItem],
        *,
        session_id: str | None = None,
    ) -> int:
        """Save high-relevance browsing items as insights in semantic_memories.

        Sprint 210: Fixes 989 pages browsed, 0 insights saved.
        """
        from uuid import uuid4

        scope = resolve_memory_write_scope()
        if not scope.write_allowed or not scope.org_id:
            self._log_scope_blocked(operation="insight_write", scope=scope)
            await self._append_browsing_insight_audit(
                session_id=session_id,
                scope=scope,
                status="blocked",
                stored_count=0,
                warnings=["social_browsing_insight_blocked_missing_org_context"],
            )
            return 0

        saved = 0
        for item in items:
            if item.relevance_score >= 0.6 and item.title.strip():
                try:
                    from sqlalchemy import text
                    from app.core.database import get_shared_session_factory

                    if item.organization_id and item.organization_id != scope.org_id:
                        self._log_scope_blocked(
                            operation="insight_write_org_mismatch",
                            scope=scope,
                            item_id=str(item.id),
                        )
                        continue

                    content = f"[Discovery] {item.title}: {item.summary[:300]}"
                    session_factory = get_shared_session_factory()
                    with session_factory() as session:
                        session.execute(
                            text("""
                                INSERT INTO semantic_memories
                                (id, user_id, content, memory_type, importance,
                                 metadata, organization_id, created_at, updated_at)
                                VALUES (:id, :user_id, :content, 'insight', :importance,
                                        :metadata::jsonb, :org_id, NOW(), NOW())
                            """),
                            {
                                "id": str(uuid4()),
                                "user_id": _AUTONOMOUS_USER_ID,
                                "content": content[:2000],
                                "importance": item.relevance_score,
                                "metadata": json.dumps(
                                    {
                                        "source": "social_browser",
                                        "platform": item.platform,
                                        "url_hash": hash_memory_identifier(item.url),
                                        "browsing_item_id_hash": hash_memory_identifier(item.id),
                                    },
                                    ensure_ascii=False,
                                ),
                                "org_id": scope.org_id,
                            },
                        )
                        session.commit()

                    # Mark as insight in browsing log
                    self._mark_as_insight(str(item.id), org_id=scope.org_id)
                    saved += 1
                except Exception as e:
                    logger.debug("[BROWSER] Failed to save insight for item: %s", e)
        await self._append_browsing_insight_audit(
            session_id=session_id,
            scope=scope,
            status="saved" if saved else "skipped",
            stored_count=saved,
        )
        return saved

    async def _append_browsing_insight_audit(
        self,
        *,
        session_id: str | None,
        scope: MemoryWriteScope,
        status: str,
        stored_count: int,
        warnings: list[str] | None = None,
    ) -> None:
        payload = build_semantic_memory_write_audit(
            user_id=_AUTONOMOUS_USER_ID,
            session_id=session_id,
            message="",
            response="",
            scope=scope,
            write_kind="social_browsing_insight",
            message_saved=False,
            response_saved=False,
            extract_facts=False,
            stored_fact_count=0,
            stored_insight_count=stored_count,
            status=status,
            warnings=warnings,
        )
        await append_semantic_memory_write_audit_event(
            session_id=session_id,
            org_id=scope.org_id,
            payload=payload,
        )

    def _mark_as_insight(self, item_id: str, *, org_id: str | None = None) -> None:
        """Mark a browsing log entry as saved_as_insight=true."""
        if not org_id:
            scope = resolve_memory_write_scope()
            if not scope.write_allowed or not scope.org_id:
                self._log_scope_blocked(
                    operation="browsing_log_mark_insight",
                    scope=scope,
                    item_id=item_id,
                )
                return
            org_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        UPDATE wiii_browsing_log
                        SET saved_as_insight = true
                        WHERE id = :id
                          AND organization_id = :org_id
                    """),
                    {"id": item_id, "org_id": org_id},
                )
                session.commit()
        except Exception as e:
            logger.debug("[BROWSER] Failed to mark insight: %s", e)

    def _save_browsing_log(self, items: List[BrowsingItem]) -> None:
        """Save browsing items to the database log."""
        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        scope = resolve_memory_write_scope()
        if not scope.write_allowed or not scope.org_id:
            self._log_scope_blocked(operation="browsing_log_write", scope=scope)
            return

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                for item in items:
                    if item.organization_id and item.organization_id != scope.org_id:
                        self._log_scope_blocked(
                            operation="browsing_log_write_org_mismatch",
                            scope=scope,
                            item_id=str(item.id),
                        )
                        continue
                    session.execute(
                        text("""
                            INSERT INTO wiii_browsing_log
                            (id, platform, url, title, summary, relevance_score,
                             emotional_reaction, browsed_at, organization_id)
                            VALUES (:id, :platform, :url, :title, :summary, :score,
                                    :reaction, NOW(), :org_id)
                        """),
                        {
                            "id": str(item.id),
                            "platform": item.platform,
                            "url": item.url,
                            "title": item.title[:500],
                            "summary": item.summary[:2000],
                            "score": item.relevance_score,
                            "reaction": item.emotional_reaction,
                            "org_id": scope.org_id,
                        },
                    )
                session.commit()
                logger.debug("[BROWSER] Saved %d items to browsing log", len(items))
        except Exception as e:
            logger.warning("[BROWSER] Failed to save browsing log: %s", e)


# =============================================================================
# Singleton
# =============================================================================

_browser_instance: Optional[SocialBrowser] = None


def get_social_browser() -> SocialBrowser:
    """Get the singleton SocialBrowser instance."""
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = SocialBrowser()
    return _browser_instance
